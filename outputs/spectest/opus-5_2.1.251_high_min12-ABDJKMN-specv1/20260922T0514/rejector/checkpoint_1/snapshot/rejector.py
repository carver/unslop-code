#!/usr/bin/env python3
"""rejector — run a YAML-configured generation task against an OpenAI-compatible API.

    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

Exit codes: 0 success, 1 configuration or input error.
"""
import argparse
import asyncio
import json
import re
import string
import sys
import time

import aiohttp
import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACTS = ("last_number", "last_line", "full")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_N = 1
DEFAULT_TEMPERATURE = 0.0
DEFAULT_EXTRACT = "full"

HTTP_RETRIES = 3          # total requests per API call, including the first
REQUEST_TIMEOUT = 300.0   # seconds


class UserError(Exception):
    """Configuration or input error: reported on stderr, exit code 1."""


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

class Task:
    def __init__(self, cfg):
        self.name = cfg.get("name")
        self.api_url = cfg.get("api_url")
        self.model = cfg.get("model")
        self.rpm = cfg.get("rpm", DEFAULT_RPM)
        self.prompt = cfg.get("prompt") or {}
        self.generation = cfg.get("generation") or {}
        self.evaluation = cfg.get("evaluation")
        self.output_field = cfg.get("output_field")

        self.scheme = self.generation.get("scheme", "greedy")
        self.temperature = self.generation.get("temperature", DEFAULT_TEMPERATURE)
        self.max_tokens = self.generation.get("max_tokens", DEFAULT_MAX_TOKENS)
        self.n = self.generation.get("n", DEFAULT_N)

        self.system_template = self.prompt.get("system") if isinstance(self.prompt, dict) else None
        self.user_template = self.prompt.get("user") if isinstance(self.prompt, dict) else None

        self.eval_type = None
        self.answer_field = None
        self.extract = DEFAULT_EXTRACT
        self.pattern = None
        self.regex = None


def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError:
        raise UserError("config file not found: %s" % path)
    except OSError as exc:
        raise UserError("could not read config file %s: %s" % (path, exc))
    except yaml.YAMLError as exc:
        raise UserError("could not parse YAML config %s: %s" % (path, exc))
    if raw is None:
        raise UserError("config file %s is empty" % path)
    if not isinstance(raw, dict):
        raise UserError("config must be a mapping with a top-level 'task' key")
    if "task" not in raw:
        raise UserError("config is missing the top-level 'task' key")
    task = raw["task"]
    if not isinstance(task, dict):
        raise UserError("config key 'task' must be a mapping")
    return task


def _as_number(value, label, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise UserError("%s must be a %s, got %r" % (label, cast.__name__, value))


def build_task(cfg, args):
    """Merge CLI overrides into the config and validate the result."""
    if args.api_url is not None:
        cfg["api_url"] = args.api_url
    if args.model is not None:
        cfg["model"] = args.model
    if args.rpm is not None:
        cfg["rpm"] = args.rpm
    gen = cfg.get("generation")
    if gen is None:
        gen = {}
    if not isinstance(gen, dict):
        raise UserError("task.generation must be a mapping")
    gen = dict(gen)
    if args.max_tokens is not None:
        gen["max_tokens"] = args.max_tokens
    if args.scheme is not None:
        gen["scheme"] = args.scheme
    if args.temperature is not None:
        gen["temperature"] = args.temperature
    if args.n is not None:
        gen["n"] = args.n
    cfg["generation"] = gen

    task = Task(cfg)

    if not task.api_url or not isinstance(task.api_url, str):
        raise UserError("task.api_url is required (or pass --api-url)")
    if not task.model or not isinstance(task.model, str):
        raise UserError("task.model is required (or pass --model)")
    if not isinstance(task.prompt, dict) or not task.prompt:
        raise UserError("task.prompt is required and must be a mapping "
                        "with 'system' and/or 'user' templates")
    if not task.user_template and not task.system_template:
        raise UserError("task.prompt must define at least one of 'system' or 'user'")
    for key in ("system", "user"):
        value = task.prompt.get(key)
        if value is not None and not isinstance(value, str):
            raise UserError("task.prompt.%s must be a string" % key)
    if not task.output_field or not isinstance(task.output_field, str):
        raise UserError("task.output_field is required")

    if task.scheme not in SCHEMES:
        raise UserError("task.generation.scheme must be one of %s, got %r"
                        % (", ".join(SCHEMES), task.scheme))

    task.rpm = _as_number(task.rpm, "task.rpm", int)
    if task.rpm <= 0:
        raise UserError("task.rpm must be a positive integer, got %r" % task.rpm)
    task.max_tokens = _as_number(task.max_tokens, "task.generation.max_tokens", int)
    if task.max_tokens <= 0:
        raise UserError("task.generation.max_tokens must be a positive integer, got %r"
                        % task.max_tokens)
    task.n = _as_number(task.n, "task.generation.n", int)
    if task.n <= 0:
        raise UserError("task.generation.n must be a positive integer, got %r" % task.n)
    task.temperature = _as_number(task.temperature, "task.generation.temperature", float)

    if task.scheme == "greedy":
        task.temperature = 0.0          # forced, per spec
        task.attempt_budget = 1         # n is ignored
    elif task.scheme == "sample":
        if task.temperature <= 0:
            raise UserError("task.generation.temperature must be > 0 for scheme 'sample', "
                            "got %r" % task.temperature)
        task.attempt_budget = 1         # n is ignored
    else:  # rejection
        if task.temperature <= 0:
            raise UserError("task.generation.temperature must be > 0 for scheme 'rejection', "
                            "got %r" % task.temperature)
        task.attempt_budget = task.n

    validate_evaluation(task)
    return task


def validate_evaluation(task):
    ev = task.evaluation
    if ev is None:
        if task.scheme == "rejection":
            raise UserError("task.evaluation is required for scheme 'rejection'")
        return
    if not isinstance(ev, dict):
        raise UserError("task.evaluation must be a mapping")
    etype = ev.get("type")
    if etype not in EVAL_TYPES:
        raise UserError("task.evaluation.type must be one of %s, got %r"
                        % (", ".join(EVAL_TYPES), etype))
    task.eval_type = etype
    extract = ev.get("extract", DEFAULT_EXTRACT)
    if extract not in EXTRACTS:
        raise UserError("task.evaluation.extract must be one of %s, got %r"
                        % (", ".join(EXTRACTS), extract))
    task.extract = extract

    if etype in ("exact_match", "contains"):
        answer_field = ev.get("answer_field")
        if not answer_field or not isinstance(answer_field, str):
            raise UserError("task.evaluation.answer_field is required for type %r" % etype)
        task.answer_field = answer_field
    else:  # regex
        pattern = ev.get("pattern")
        if not pattern or not isinstance(pattern, str):
            raise UserError("task.evaluation.pattern is required for type 'regex'")
        try:
            task.regex = re.compile(pattern)
        except re.error as exc:
            raise UserError("task.evaluation.pattern is not a valid regex: %s" % exc)
        task.pattern = pattern


# --------------------------------------------------------------------------
# Prompt templates
# --------------------------------------------------------------------------

_FORMATTER = string.Formatter()


def template_fields(template):
    """Field names referenced by {placeholders} in a template."""
    if not template:
        return []
    fields = []
    try:
        for _literal, field, _spec, _conv in _FORMATTER.parse(template):
            if field is None:
                continue
            name = field.split(".")[0].split("[")[0]
            if name == "":
                raise UserError("prompt template uses an unnamed placeholder '{}': %r" % template)
            if name not in fields:
                fields.append(name)
    except ValueError as exc:
        raise UserError("invalid prompt template %r: %s" % (template, exc))
    return fields


def render(template, row):
    """Render a template against a row; fields are known to be present."""
    if not template:
        return None
    out = []
    for literal, field, spec, conv in _FORMATTER.parse(template):
        out.append(literal)
        if field is None:
            continue
        name = field.split(".")[0].split("[")[0]
        value = row[name]
        if conv:
            value = _FORMATTER.convert_field(value, conv)
        if spec:
            out.append(format(value, spec))
        else:
            out.append(value if isinstance(value, str) else json_scalar(value))
    return "".join(out)


def json_scalar(value):
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------

def load_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        raise UserError("input file not found: %s" % path)
    except OSError as exc:
        raise UserError("could not read input file %s: %s" % (path, exc))
    rows = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            raise UserError("input line %d is not valid JSON: %s" % (lineno, exc))
        if not isinstance(obj, dict):
            raise UserError("input line %d is not a JSON object" % lineno)
        rows.append(obj)
    return rows


def validate_rows(rows, task):
    """Every row must supply the prompt fields and, if used, the answer field."""
    prompt_fields = []
    for template in (task.system_template, task.user_template):
        for field in template_fields(template):
            if field not in prompt_fields:
                prompt_fields.append(field)
    for index, row in enumerate(rows):
        for field in prompt_fields:
            if field not in row:
                raise UserError("row %d is missing field '%s' referenced by the prompt template"
                                % (index, field))
        if task.answer_field is not None and task.answer_field not in row:
            raise UserError("row %d is missing field '%s' required by task.evaluation.answer_field"
                            % (index, task.answer_field))


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_GROUPED_RE = re.compile(r"(?<=\d),(?=\d\d\d(?!\d))")


def extract_value(text, method):
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    if method == "last_number":
        numbers = _NUMBER_RE.findall(_GROUPED_RE.sub("", text))
        return numbers[-1] if numbers else None
    raise UserError("unknown extract method %r" % method)


def _numeric(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def values_match(extracted, expected):
    if extracted is None:
        return False
    left = str(extracted).strip()
    right = str(expected).strip()
    if left == right:
        return True
    a, b = _numeric(left), _numeric(right)
    return a is not None and b is not None and a == b


def evaluate(task, row, text):
    """Return (passed, extracted_answer) for one response."""
    if task.eval_type is None:
        return None, None
    extracted = extract_value(text, task.extract)
    if task.eval_type == "exact_match":
        passed = values_match(extracted, row.get(task.answer_field))
    elif task.eval_type == "contains":
        expected = row.get(task.answer_field)
        passed = str(expected) in (text or "")
    else:  # regex
        passed = task.regex.search(text or "") is not None
    return passed, extracted


# --------------------------------------------------------------------------
# API calls
# --------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.api_calls = 0
        self.first_request = None
        self.last_response = None

    def mark_request(self, when):
        if self.first_request is None or when < self.first_request:
            self.first_request = when

    def mark_response(self, when):
        if self.last_response is None or when > self.last_response:
            self.last_response = when


def build_payload(task, row):
    messages = []
    system = render(task.system_template, row)
    if system is not None:
        messages.append({"role": "system", "content": system})
    user = render(task.user_template, row)
    if user is not None:
        messages.append({"role": "user", "content": user})
    return {
        "model": task.model,
        "messages": messages,
        "temperature": task.temperature,
        "max_tokens": task.max_tokens,
    }


async def call_api(session, url, payload, task, stats, semaphore):
    """One logical API call, retrying 5xx up to HTTP_RETRIES total requests.

    Returns (text, meta) on success or (None, None) on failure.
    """
    for attempt in range(HTTP_RETRIES):
        async with semaphore:
            stats.api_calls += 1
            started = time.time()
            stats.mark_request(started)
            status = None
            data = None
            try:
                async with session.post(url, json=payload) as response:
                    status = response.status
                    body = await response.read()
                    if status < 400:
                        data = json.loads(body.decode("utf-8", "replace"))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                status = None
            finished = time.time()
            stats.mark_response(finished)

        if data is not None:
            try:
                choice = data["choices"][0]
                text = choice.get("message", {}).get("content")
                if text is None:
                    raise KeyError("content")
                usage = data.get("usage") or {}
                meta = {
                    "model": data.get("model") or task.model,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "latency_ms": int(round((finished - started) * 1000)),
                    "finish_reason": choice.get("finish_reason"),
                }
                return text, meta
            except (KeyError, IndexError, TypeError, AttributeError):
                return None, None       # malformed body: not retryable
        if status is not None and 400 <= status < 500:
            return None, None           # client error: not retryable
        # 5xx, transport error or unparsable body: retry while budget remains
    return None, None


async def process_row(session, url, task, row, stats, semaphore):
    """Run one input row through the configured scheme."""
    payload = build_payload(task, row)
    metas = []
    attempts = 0
    for _ in range(task.attempt_budget):
        attempts += 1
        text, meta = await call_api(session, url, payload, task, stats, semaphore)
        if meta is None:
            # Hard failure after the retry budget: the row is failed.
            return make_row(task, row, None, None, None, attempts, metas)
        metas.append(meta)
        passed, extracted = evaluate(task, row, text)
        if task.scheme != "rejection" or passed:
            return make_row(task, row, text, passed, extracted, attempts, metas)
    # Rejection exhausted its attempts without a pass.
    return make_row(task, row, None, False, None, attempts, metas)


def make_row(task, row, text, passed, extracted, attempts, metas):
    if text is None:
        output = None
        extracted = None
        if task.eval_type is not None:
            passed = False
    else:
        output = {task.output_field: text}
    if attempts <= 1:
        meta = metas[0] if metas else None
    else:
        meta = metas if metas else None
    return {
        "input": row,
        "output": output,
        "result": {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": attempts,
        },
        "meta": meta,
    }


def concurrency_for(task, rows):
    """In-flight request budget: sized from rpm, capped by the work available."""
    if not rows:
        return 1
    pending = len(rows) * (task.attempt_budget if task.scheme == "rejection" else 1)
    return max(1, min(max(8, task.rpm), pending, 512))


async def run_all(task, rows):
    url = task.api_url.rstrip("/") + "/v1/chat/completions"
    stats = Stats()
    limit = concurrency_for(task, rows)
    semaphore = asyncio.Semaphore(limit)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=limit + 8)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [asyncio.ensure_future(process_row(session, url, task, row, stats, semaphore))
                 for row in rows]
        results = await asyncio.gather(*tasks) if tasks else []
    return list(results), stats


def summarize(results, stats):
    passed = 0
    failed = 0
    prompt_tokens = 0
    completion_tokens = 0
    for res in results:
        verdict = res["result"]["passed"]
        has_output = res["output"] is not None
        if verdict is True or (verdict is None and has_output):
            passed += 1
        if verdict is False or not has_output:
            failed += 1
        meta = res["meta"]
        metas = meta if isinstance(meta, list) else ([meta] if meta else [])
        for entry in metas:
            prompt_tokens += entry.get("prompt_tokens") or 0
            completion_tokens += entry.get("completion_tokens") or 0
    if stats.first_request is None or stats.last_response is None:
        elapsed = 0.0
    else:
        elapsed = max(0.0, stats.last_response - stats.first_request)
    throughput = (stats.api_calls / elapsed * 60) if elapsed > 0 else 0.0
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def write_results(path, results):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for res in results:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise UserError("could not write output file %s: %s" % (path, exc))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

class Parser(argparse.ArgumentParser):
    def error(self, message):
        # The spec defines only exit codes 0 and 1.
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser():
    parser = Parser(prog="rejector.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True)
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    return parser


def command_run(args):
    cfg = load_config(args.config)
    task = build_task(cfg, args)
    rows = load_rows(args.input)
    validate_rows(rows, task)

    results, stats = asyncio.run(run_all(task, rows))
    write_results(args.output, results)
    print(json.dumps(summarize(results, stats), ensure_ascii=False))
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return command_run(args)
        parser.error("unknown command %r" % args.command)
    except UserError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
