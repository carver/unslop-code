#!/usr/bin/env python3
"""rejector.py - run a YAML-configured generation task over a JSONL input.

Reads a task config and a JSONL input file, sends one prompt per row to an
OpenAI-compatible chat completions API with enough requests in flight to use
the configured request budget, and writes one JSONL result per input row.
"""
import argparse
import asyncio
import json
import math
import os
import re
import sys
import time

import aiohttp
import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

# Total HTTP calls for one logical request: the original plus retries, ending
# on the third failure (see AMBIGUITIES.md T3).
MAX_HTTP_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.05

# Concurrency is sized from the configured rpm, which the spec describes as
# the server's approximate capacity; a little oversubscription keeps the
# server's internal queue fed without ever exceeding its capacity.
CONCURRENCY_FACTOR = 1.25
MIN_CONCURRENCY = 4
MAX_CONCURRENCY = 256

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


class ConfigError(Exception):
    """Invalid configuration; exits 1."""


class InputError(Exception):
    """Invalid input file or row; exits 1."""


# --------------------------------------------------------------- config ---

class TaskConfig(object):
    def __init__(self, name, api_url, model, rpm, system, user, scheme,
                 temperature, max_tokens, n, evaluation, output_field):
        self.name = name
        self.api_url = api_url
        self.model = model
        self.rpm = rpm
        self.system = system
        self.user = user
        self.scheme = scheme
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.n = n
        self.evaluation = evaluation
        self.output_field = output_field

    @property
    def endpoint(self):
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def concurrency(self):
        want = int(math.ceil(self.rpm * CONCURRENCY_FACTOR))
        return max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, want))


def _require_text(value, label):
    if value is None:
        raise ConfigError("%s is required" % label)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s must be a non-empty string" % label)
    return value


def _require_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("%s must be a number" % label)
    return value


def _require_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        raise ConfigError("%s must be an integer" % label)
    return value


def load_config_file(path):
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path) as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError("could not parse YAML config %s: %s" % (path, exc))
    except OSError as exc:
        raise ConfigError("could not read config %s: %s" % (path, exc))
    return raw


def build_config(raw, args):
    """Merge a raw config mapping with CLI overrides and validate it."""
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping with a 'task' key")
    task = raw.get("task")
    if not isinstance(task, dict):
        raise ConfigError("config must contain a 'task' mapping")

    prompt = task.get("prompt") or {}
    if not isinstance(prompt, dict):
        raise ConfigError("task.prompt must be a mapping")
    generation = task.get("generation") or {}
    if not isinstance(generation, dict):
        raise ConfigError("task.generation must be a mapping")

    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    model = args.model if args.model is not None else task.get("model")
    rpm = args.rpm if args.rpm is not None else task.get("rpm", 60)
    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    temperature = (args.temperature if args.temperature is not None
                   else generation.get("temperature", 0.0))
    max_tokens = (args.max_tokens if args.max_tokens is not None
                  else generation.get("max_tokens", 512))
    n = args.n if args.n is not None else generation.get("n", 1)

    api_url = _require_text(api_url, "task.api_url")
    model = _require_text(model, "task.model")
    user = _require_text(prompt.get("user"), "task.prompt.user")
    system = prompt.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError("task.prompt.system must be a string")

    if scheme not in SCHEMES:
        raise ConfigError("task.generation.scheme must be one of %s (got %r)"
                          % (", ".join(SCHEMES), scheme))

    rpm = _require_number(rpm, "task.rpm")
    if rpm <= 0:
        raise ConfigError("task.rpm must be greater than 0")
    max_tokens = _require_int(max_tokens, "task.generation.max_tokens")
    if max_tokens <= 0:
        raise ConfigError("task.generation.max_tokens must be greater than 0")
    temperature = float(_require_number(temperature, "task.generation.temperature"))

    if scheme == "greedy":
        # greedy forces temperature to 0.0 and ignores n.
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError("task.generation.temperature must be > 0 for "
                              "scheme 'sample'")
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError("task.generation.temperature must be > 0 for "
                              "scheme 'rejection'")
        n = _require_int(n, "task.generation.n")
        if n < 1:
            raise ConfigError("task.generation.n must be >= 1 for scheme "
                              "'rejection'")

    evaluation = build_evaluation(task.get("evaluation"), scheme)

    output_field = task.get("output_field", "output")
    output_field = _require_text(output_field, "task.output_field")

    return TaskConfig(task.get("name"), api_url, model, rpm, system, user,
                      scheme, temperature, max_tokens, n, evaluation,
                      output_field)


def build_evaluation(raw, scheme):
    """Validate the evaluation block; returns a normalised dict or None."""
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("task.evaluation is required for scheme "
                              "'rejection'")
        return None
    if not isinstance(raw, dict):
        raise ConfigError("task.evaluation must be a mapping")

    eval_type = raw.get("type")
    if eval_type not in EVAL_TYPES:
        raise ConfigError("task.evaluation.type must be one of %s (got %r)"
                          % (", ".join(EVAL_TYPES), eval_type))

    extract = raw.get("extract", "full")
    if extract not in EXTRACT_METHODS:
        raise ConfigError("task.evaluation.extract must be one of %s (got %r)"
                          % (", ".join(EXTRACT_METHODS), extract))

    answer_field = raw.get("answer_field")
    pattern = raw.get("pattern")
    if eval_type in ("exact_match", "contains"):
        answer_field = _require_text(
            answer_field, "task.evaluation.answer_field (required for type "
            "'%s')" % eval_type)
    if eval_type == "regex":
        pattern = _require_text(
            pattern, "task.evaluation.pattern (required for type 'regex')")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError("task.evaluation.pattern is not a valid regular "
                              "expression: %s" % exc)

    return {"type": eval_type, "extract": extract,
            "answer_field": answer_field, "pattern": pattern}


# ---------------------------------------------------------------- input ---

def load_rows(path):
    if not os.path.exists(path):
        raise InputError("input file not found: %s" % path)
    rows = []
    try:
        with open(path) as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise InputError("input line %d is not valid JSON: %s"
                                     % (lineno, exc))
                if not isinstance(obj, dict):
                    raise InputError("input line %d is not a JSON object"
                                     % lineno)
                rows.append(obj)
    except OSError as exc:
        raise InputError("could not read input %s: %s" % (path, exc))
    return rows


def to_text(value):
    """Render a row value as text for prompts and comparisons."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_template(template, row, row_index):
    """Substitute {field} placeholders from `row`."""
    missing = []

    def replace(match):
        field = match.group(1)
        if field not in row:
            missing.append(field)
            return match.group(0)
        return to_text(row[field])

    rendered = PLACEHOLDER_RE.sub(replace, template)
    if missing:
        raise InputError("row %d: missing field '%s'" % (row_index, missing[0]))
    return rendered


def build_messages(cfg, rows):
    """Render every row up front so input errors abort before any request."""
    prepared = []
    answer_field = cfg.evaluation.get("answer_field") if cfg.evaluation else None
    for index, row in enumerate(rows):
        messages = []
        if cfg.system is not None:
            messages.append({"role": "system",
                             "content": render_template(cfg.system, row, index)})
        messages.append({"role": "user",
                         "content": render_template(cfg.user, row, index)})
        if answer_field is not None and answer_field not in row:
            raise InputError("row %d: missing field '%s'" % (index, answer_field))
        prepared.append(messages)
    return prepared


# ----------------------------------------------------------- evaluation ---

def extract_answer(text, method):
    """Pull the comparison value out of a response body."""
    if text is None:
        return None
    if method == "full":
        return text
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else ""
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        return matches[-1] if matches else None
    raise ConfigError("unknown extract method: %r" % method)


def evaluate(text, row, evaluation):
    """Returns (passed, extracted_answer) for one response."""
    if evaluation is None:
        return None, None
    extracted = extract_answer(text, evaluation["extract"])
    eval_type = evaluation["type"]
    if eval_type == "exact_match":
        expected = to_text(row.get(evaluation["answer_field"]))
        passed = (extracted is not None
                  and extracted.strip() == expected.strip())
    elif eval_type == "contains":
        expected = to_text(row.get(evaluation["answer_field"]))
        passed = expected in text
    else:  # regex
        passed = re.search(evaluation["pattern"], text) is not None
    return bool(passed), extracted


# ------------------------------------------------------------- pipeline ---

class Stats(object):
    def __init__(self):
        self.api_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.first_request = None
        self.last_response = None

    def opened(self, when):
        self.api_calls += 1
        if self.first_request is None or when < self.first_request:
            self.first_request = when

    def closed(self, when):
        if self.last_response is None or when > self.last_response:
            self.last_response = when

    @property
    def elapsed(self):
        if self.first_request is None or self.last_response is None:
            return 0.0
        return max(0.0, self.last_response - self.first_request)


def _token(usage, key):
    value = usage.get(key) if isinstance(usage, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


class Runner(object):
    def __init__(self, cfg, session, semaphore, stats):
        self.cfg = cfg
        self.session = session
        self.semaphore = semaphore
        self.stats = stats

    async def call_api(self, messages):
        """One logical request, with retries. Returns (content, meta) or None."""
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        for attempt in range(MAX_HTTP_ATTEMPTS):
            retryable, outcome = await self._post_once(payload)
            if outcome is not None:
                return outcome
            if not retryable:
                return None
            if attempt < MAX_HTTP_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        return None

    async def _post_once(self, payload):
        """Returns (retryable, (content, meta) or None)."""
        async with self.semaphore:
            start = time.monotonic()
            self.stats.opened(start)
            try:
                async with self.session.post(self.cfg.endpoint,
                                             json=payload) as response:
                    status = response.status
                    body = await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                self.stats.closed(time.monotonic())
                return True, None
            end = time.monotonic()
            self.stats.closed(end)

        if status >= 500:
            return True, None
        if not 200 <= status < 300:
            return False, None

        try:
            data = json.loads(body)
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("content is not a string")
        except (ValueError, KeyError, IndexError, TypeError):
            return False, None

        usage = data.get("usage") or {}
        meta = {
            "model": self.cfg.model,
            "prompt_tokens": _token(usage, "prompt_tokens"),
            "completion_tokens": _token(usage, "completion_tokens"),
            "total_tokens": _token(usage, "total_tokens"),
            "latency_ms": int(round((end - start) * 1000)),
            "finish_reason": choice.get("finish_reason"),
        }
        self.stats.prompt_tokens += meta["prompt_tokens"]
        self.stats.completion_tokens += meta["completion_tokens"]
        return False, (content, meta)

    async def run_row(self, row, messages):
        """Produce the output record for one input row."""
        max_attempts = self.cfg.n if self.cfg.scheme == "rejection" else 1
        metas = []
        attempts = 0
        for _ in range(max_attempts):
            attempts += 1
            outcome = await self.call_api(messages)
            if outcome is None:
                # The request never produced a response: the row has failed.
                return self._record(row, None, False, None, attempts, metas)
            content, meta = outcome
            metas.append(meta)
            passed, extracted = evaluate(content, row, self.cfg.evaluation)
            if self.cfg.scheme != "rejection" or passed:
                return self._record(row, content, passed, extracted, attempts,
                                    metas)
        # Rejection sampling exhausted every attempt without a passing response.
        return self._record(row, None, False, None, attempts, metas)

    def _record(self, row, content, passed, extracted, attempts, metas):
        if content is None:
            output = None
            extracted = None
        else:
            output = {self.cfg.output_field: content}
        if not metas:
            meta = None
        elif len(metas) == 1:
            meta = metas[0]
        else:
            meta = metas
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


async def process(cfg, rows, prepared):
    if not rows:
        return [], Stats()
    stats = Stats()
    concurrency = min(cfg.concurrency, max(1, len(rows)))
    connector = aiohttp.TCPConnector(limit=concurrency,
                                     limit_per_host=concurrency)
    timeout = aiohttp.ClientTimeout(total=None, connect=None,
                                    sock_connect=30, sock_read=None)
    async with aiohttp.ClientSession(connector=connector,
                                     timeout=timeout) as session:
        semaphore = asyncio.Semaphore(concurrency)
        runner = Runner(cfg, session, semaphore, stats)
        tasks = [asyncio.ensure_future(runner.run_row(row, messages))
                 for row, messages in zip(rows, prepared)]
        records = await asyncio.gather(*tasks)
    return list(records), stats


def summarise(records, stats):
    passed = 0
    failed = 0
    for record in records:
        if record["result"]["passed"] is True:
            passed += 1
        elif record["result"]["passed"] is None and record["output"] is not None:
            # No evaluation configured: a successful API row counts as passed.
            passed += 1
        else:
            failed += 1
    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0
    return {
        "total": len(records),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def write_output(path, records):
    try:
        with open(path, "w") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise InputError("could not write output %s: %s" % (path, exc))


# ------------------------------------------------------------------ cli ---

class Parser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors; the spec only defines 0 and 1."""

    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser():
    parser = Parser(prog="rejector.py", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=SCHEMES, default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    return parser


def run_command(args):
    cfg = build_config(load_config_file(args.config), args)
    rows = load_rows(args.input)
    prepared = build_messages(cfg, rows)
    records, stats = asyncio.run(process(cfg, rows, prepared))
    write_output(args.output, records)
    sys.stdout.write(json.dumps(summarise(records, stats)) + "\n")
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        sys.stderr.write("error: usage: rejector.py run --config <path> "
                         "--input <path> --output <path>\n")
        return 1
    try:
        return run_command(args)
    except (ConfigError, InputError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
