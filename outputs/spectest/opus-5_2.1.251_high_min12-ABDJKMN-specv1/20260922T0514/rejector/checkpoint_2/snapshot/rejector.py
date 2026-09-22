#!/usr/bin/env python3
"""rejector — run YAML-configured generation tasks against an OpenAI-compatible API.

    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
    python rejector.py run --config multi.yaml --input-dir data/ --output results/

Exit codes: 0 success, 1 configuration or input error.
"""
import argparse
import asyncio
import json
import os
import re
import string
import subprocess
import sys
import time

import aiohttp
import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACTS = ("last_number", "last_line", "full", "letter", "first_number")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_N = 1
DEFAULT_TEMPERATURE = 0.0
DEFAULT_EXTRACT = "full"
DEFAULT_JUDGE_EXTRACT = "first_number"      # T42
DEFAULT_SUCCESS_EXIT_CODE = 0               # T21

HTTP_RETRIES = 3          # total requests per API call, including the first
REQUEST_TIMEOUT = 300.0   # seconds
SCRIPT_TIMEOUT = 10.0     # seconds, per rendered script command

RESPONSE_KEY = "__response__"
RESPONSE_PLACEHOLDER = "{%s}" % RESPONSE_KEY


class UserError(Exception):
    """Configuration or input error: reported on stderr, exit code 1."""


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

class Task:
    def __init__(self, cfg, name=None, label="task"):
        self.name = name if name is not None else cfg.get("name")
        self.label = label          # how this task is named in error messages
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
        # script evaluation
        self.command_template = None
        self.success_exit_code = DEFAULT_SUCCESS_EXIT_CODE
        # llm_judge evaluation
        self.judge_system_template = None
        self.judge_user_template = None
        self.judge_model = None
        self.threshold = None


def read_config(path):
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
        raise UserError("config must be a mapping with a top-level 'task' or "
                        "'tasks' key")
    return raw


def deep_merge(base, over):
    """Recursive mapping merge; non-mapping values replace wholesale (T33)."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _as_number(value, label, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise UserError("%s must be a %s, got %r" % (label, cast.__name__, value))


def apply_overrides(cfg, args):
    """Merge CLI overrides into one task's config mapping."""
    cfg = dict(cfg)
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
        raise UserError("generation must be a mapping")
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
    return cfg


def build_task(cfg, args, name=None, label="task"):
    """Validate one task's merged config and return a Task."""
    cfg = apply_overrides(cfg, args)
    task = Task(cfg, name=name, label=label)
    p = task.label + "."

    if not task.api_url or not isinstance(task.api_url, str):
        raise UserError("%sapi_url is required (or pass --api-url)" % p)
    if not task.model or not isinstance(task.model, str):
        raise UserError("%smodel is required (or pass --model)" % p)
    if not isinstance(task.prompt, dict) or not task.prompt:
        raise UserError("%sprompt is required and must be a mapping "
                        "with 'system' and/or 'user' templates" % p)
    if not task.user_template and not task.system_template:
        raise UserError("%sprompt must define at least one of 'system' or 'user'" % p)
    for key in ("system", "user"):
        value = task.prompt.get(key)
        if value is not None and not isinstance(value, str):
            raise UserError("%sprompt.%s must be a string" % (p, key))
    if not task.output_field or not isinstance(task.output_field, str):
        raise UserError("%soutput_field is required" % p)

    if task.scheme not in SCHEMES:
        raise UserError("%sgeneration.scheme must be one of %s, got %r"
                        % (p, ", ".join(SCHEMES), task.scheme))

    task.rpm = _as_number(task.rpm, p + "rpm", int)
    if task.rpm <= 0:
        raise UserError("%srpm must be a positive integer, got %r" % (p, task.rpm))
    task.max_tokens = _as_number(task.max_tokens, p + "generation.max_tokens", int)
    if task.max_tokens <= 0:
        raise UserError("%sgeneration.max_tokens must be a positive integer, got %r"
                        % (p, task.max_tokens))
    task.n = _as_number(task.n, p + "generation.n", int)
    if task.n <= 0:
        raise UserError("%sgeneration.n must be a positive integer, got %r" % (p, task.n))
    task.temperature = _as_number(task.temperature, p + "generation.temperature", float)

    if task.scheme == "greedy":
        task.temperature = 0.0          # forced, per spec
        task.attempt_budget = 1         # n is ignored
    elif task.scheme == "sample":
        if task.temperature <= 0:
            raise UserError("%sgeneration.temperature must be > 0 for scheme 'sample', "
                            "got %r" % (p, task.temperature))
        task.attempt_budget = 1         # n is ignored
    else:  # rejection
        if task.temperature <= 0:
            raise UserError("%sgeneration.temperature must be > 0 for scheme 'rejection', "
                            "got %r" % (p, task.temperature))
        task.attempt_budget = task.n

    validate_evaluation(task, args)
    return task


def validate_evaluation(task, args):
    ev = task.evaluation
    p = task.label + "."
    if ev is None:
        if task.scheme == "rejection":
            raise UserError("%sevaluation is required for scheme 'rejection'" % p)
        return
    if not isinstance(ev, dict):
        raise UserError("%sevaluation must be a mapping" % p)
    etype = ev.get("type")
    if etype not in EVAL_TYPES:
        raise UserError("%sevaluation.type must be one of %s, got %r"
                        % (p, ", ".join(EVAL_TYPES), etype))
    task.eval_type = etype
    default_extract = DEFAULT_JUDGE_EXTRACT if etype == "llm_judge" else DEFAULT_EXTRACT
    extract = ev.get("extract", default_extract)
    if extract not in EXTRACTS:
        raise UserError("%sevaluation.extract must be one of %s, got %r"
                        % (p, ", ".join(EXTRACTS), extract))
    task.extract = extract

    if etype in ("exact_match", "contains"):
        answer_field = ev.get("answer_field")
        if not answer_field or not isinstance(answer_field, str):
            raise UserError("%sevaluation.answer_field is required for type %r" % (p, etype))
        task.answer_field = answer_field
    elif etype == "regex":
        pattern = ev.get("pattern")
        if not pattern or not isinstance(pattern, str):
            raise UserError("%sevaluation.pattern is required for type 'regex'" % p)
        try:
            task.regex = re.compile(pattern)
        except re.error as exc:
            raise UserError("%sevaluation.pattern is not a valid regex: %s" % (p, exc))
        task.pattern = pattern
    elif etype == "script":
        command = ev.get("command_template")
        if not command or not isinstance(command, str):
            raise UserError("%sevaluation.command_template is required for type 'script'" % p)
        task.command_template = command
        task.success_exit_code = _as_number(
            ev.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE),
            p + "evaluation.success_exit_code", int)
    else:  # llm_judge
        judge = ev.get("judge_prompt")
        if not isinstance(judge, dict) or not judge:
            raise UserError("%sevaluation.judge_prompt is required for type 'llm_judge'" % p)
        for key in ("system", "user"):
            value = judge.get(key)
            if value is not None and not isinstance(value, str):
                raise UserError("%sevaluation.judge_prompt.%s must be a string" % (p, key))
        task.judge_system_template = judge.get("system")
        task.judge_user_template = judge.get("user")
        if not task.judge_system_template and not task.judge_user_template:
            raise UserError("%sevaluation.judge_prompt must define at least one of "
                            "'system' or 'user'" % p)
        if "threshold" not in ev or ev.get("threshold") is None:
            raise UserError("%sevaluation.threshold is required for type 'llm_judge'" % p)
        task.threshold = _as_number(ev["threshold"], p + "evaluation.threshold", float)
        judge_model = args.eval_model or ev.get("model") or task.model
        if not isinstance(judge_model, str) or not judge_model:
            raise UserError("%sevaluation.model must be a string" % p)
        task.judge_model = judge_model


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


def response_context(row, text):
    ctx = dict(row)
    ctx[RESPONSE_KEY] = text
    return ctx


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


def required_fields(task):
    """Row fields every input row must supply for this task."""
    fields = []

    def add(template):
        for field in template_fields(template):
            if field != RESPONSE_KEY and field not in fields:
                fields.append(field)

    add(task.system_template)
    add(task.user_template)
    if task.eval_type == "script":
        add(task.command_template)
    elif task.eval_type == "llm_judge":
        add(task.judge_system_template)
        add(task.judge_user_template)
    return fields


def validate_rows(rows, task):
    """Every row must supply the referenced fields and, if used, the answer field."""
    fields = required_fields(task)
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise UserError("row %d is missing field '%s' referenced by the prompt template"
                                % (index, field))
        if task.answer_field is not None and task.answer_field not in row:
            raise UserError("row %d is missing field '%s' required by evaluation.answer_field"
                            % (index, task.answer_field))


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_GROUPED_RE = re.compile(r"(?<=\d),(?=\d\d\d(?!\d))")
_LETTER_RE = re.compile(r"\b([A-D])\b")


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
    if method in ("last_number", "first_number"):
        numbers = _NUMBER_RE.findall(_GROUPED_RE.sub("", text))
        if not numbers:
            return None
        return numbers[-1] if method == "last_number" else numbers[0]
    if method == "letter":
        match = _LETTER_RE.search(text)
        return match.group(1) if match else None
    raise UserError("unknown extract method %r" % method)


def _numeric(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def score_number(value):
    """A judge score as JSON: int when integral, float otherwise (T39)."""
    number = _numeric(value)
    if number is None or number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number == int(number) else number


def values_match(extracted, expected):
    if extracted is None:
        return False
    left = str(extracted).strip()
    right = str(expected).strip()
    if left == right:
        return True
    a, b = _numeric(left), _numeric(right)
    return a is not None and b is not None and a == b


def render_command(task, row, text):
    """Render command_template, then substitute any {__response__} a row field
    itself expanded to (spec: "substitute __response__ before executing")."""
    command = render(task.command_template, response_context(row, text))
    if RESPONSE_PLACEHOLDER in command:
        command = command.replace(RESPONSE_PLACEHOLDER, text)
    return command


def _run_shell(command, timeout):
    """Run one shell command, capturing (and discarding) stdout/stderr.

    Returns the exit code, or None if the command timed out.
    """
    try:
        done = subprocess.run(command, shell=True, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        return None
    except (OSError, ValueError):
        return None
    return done.returncode


async def run_script(task, row, text):
    """Run the rendered command in a shell; True when it exits successfully.

    stdout/stderr are captured but never reported (spec); a timeout fails.
    """
    command = render_command(task, row, text)
    code = await asyncio.to_thread(_run_shell, command, SCRIPT_TIMEOUT)
    return code == task.success_exit_code


def build_judge_payload(task, row, text):
    ctx = response_context(row, text)
    messages = []
    system = render(task.judge_system_template, ctx)
    if system is not None:
        messages.append({"role": "system", "content": system})
    user = render(task.judge_user_template, ctx)
    if user is not None:
        messages.append({"role": "user", "content": user})
    return {
        "model": task.judge_model,
        "messages": messages,
        "temperature": 0.0,             # T34: judging is deterministic
        "max_tokens": task.max_tokens,
    }


class Verdict:
    __slots__ = ("passed", "extracted", "judge_score", "judge_meta")

    def __init__(self, passed=None, extracted=None, judge_score=None, judge_meta=None):
        self.passed = passed
        self.extracted = extracted
        self.judge_score = judge_score
        self.judge_meta = judge_meta


async def evaluate(session, url, task, row, text, stats):
    """Evaluate one response, making a judge API call when configured."""
    if task.eval_type is None:
        return Verdict()
    if task.eval_type == "llm_judge":
        payload = build_judge_payload(task, row, text)
        reply, judge_meta = await call_api(session, url, payload, task,
                                           task.judge_model, stats)
        if judge_meta is None:
            return Verdict(passed=False)                # T22
        extracted = extract_value(reply, task.extract)
        score = score_number(extracted)
        passed = score is not None and score >= task.threshold
        return Verdict(passed=passed, extracted=extracted,
                       judge_score=score, judge_meta=judge_meta)

    extracted = extract_value(text, task.extract)
    if task.eval_type == "exact_match":
        passed = values_match(extracted, row.get(task.answer_field))
    elif task.eval_type == "contains":
        passed = str(row.get(task.answer_field)) in (text or "")
    elif task.eval_type == "regex":
        passed = task.regex.search(text or "") is not None
    else:  # script
        passed = await run_script(task, row, text)
    return Verdict(passed=passed, extracted=extracted)


# --------------------------------------------------------------------------
# API calls
# --------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.api_calls = 0
        self.per_task = {}
        self.first_request = None
        self.last_response = None

    def count(self, task_name):
        self.api_calls += 1
        self.per_task[task_name] = self.per_task.get(task_name, 0) + 1

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


async def call_api(session, url, payload, task, fallback_model, stats):
    """One logical API call, retrying 5xx up to HTTP_RETRIES total requests.

    Returns (text, meta) on success or (None, None) on failure.
    """
    semaphore = task.semaphore
    for _attempt in range(HTTP_RETRIES):
        async with semaphore:
            stats.count(task.name)
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
                    "model": data.get("model") or fallback_model,
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


async def process_row(session, url, task, row, stats):
    """Run one input row through the configured scheme."""
    payload = build_payload(task, row)
    metas = []
    attempts = 0
    for _ in range(task.attempt_budget):
        attempts += 1
        text, meta = await call_api(session, url, payload, task, task.model, stats)
        if meta is None:
            # Hard failure after the retry budget: the row is failed.
            return make_row(task, row, None, Verdict(), attempts, metas)
        verdict = await evaluate(session, url, task, row, text, stats)
        if verdict.judge_meta is not None:
            meta = dict(meta, judge_meta=verdict.judge_meta)
        metas.append(meta)
        if task.scheme != "rejection" or verdict.passed:
            return make_row(task, row, text, verdict, attempts, metas)
    # Rejection exhausted its attempts without a pass.
    return make_row(task, row, None, Verdict(passed=False), attempts, metas)


def make_row(task, row, text, verdict, attempts, metas):
    passed = verdict.passed
    extracted = verdict.extracted
    judge_score = verdict.judge_score
    if text is None:
        output = None
        extracted = None
        judge_score = None
        if task.eval_type is not None:
            passed = False
    else:
        output = {task.output_field: text}
    if attempts <= 1:
        meta = metas[0] if metas else None
    else:
        meta = metas if metas else None
    result = {
        "passed": passed,
        "extracted_answer": extracted,
        "attempts": attempts,
    }
    if task.eval_type == "llm_judge":
        result["judge_score"] = judge_score
    return {
        "input": row,
        "output": output,
        "result": result,
        "meta": meta,
    }


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

def concurrency_for(jobs):
    """In-flight request budget: sized from rpm, capped by the work available."""
    pending = 0
    rpm = DEFAULT_RPM
    for task, rows in jobs:
        budget = task.attempt_budget if task.scheme == "rejection" else 1
        if task.eval_type == "llm_judge":
            budget *= 2                 # each attempt also makes a judge call
        pending += len(rows) * budget
        rpm = max(rpm, task.rpm)        # one shared server capacity (T37)
    if pending <= 0:
        return 1
    return max(1, min(max(8, rpm), pending, 512))


async def run_all(jobs):
    """Run every (task, rows) pair on one event loop, interleaved."""
    stats = Stats()
    limit = concurrency_for(jobs)
    semaphore = asyncio.Semaphore(limit)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=limit + 8)
    results = {}
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        plan = []
        for task, rows in jobs:
            task.semaphore = semaphore
            url = task.api_url.rstrip("/") + "/v1/chat/completions"
            plan.append((task, url, rows))
        # Round-robin over tasks so work from different tasks interleaves
        # rather than one task's rows monopolising the front of the queue.
        futures = {task.name: [None] * len(rows) for task, _url, rows in plan}
        longest = max([len(rows) for _task, _url, rows in plan] or [0])
        for index in range(longest):
            for task, url, rows in plan:
                if index < len(rows):
                    futures[task.name][index] = asyncio.ensure_future(
                        process_row(session, url, task, rows[index], stats))
        for task, _url, _rows in plan:
            pending = futures[task.name]
            results[task.name] = list(await asyncio.gather(*pending)) if pending else []
    return results, stats


# --------------------------------------------------------------------------
# Summary and output
# --------------------------------------------------------------------------

def count_rows(results):
    passed = failed = prompt_tokens = completion_tokens = 0
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
            for part in (entry, entry.get("judge_meta")):
                if not part:
                    continue
                prompt_tokens += part.get("prompt_tokens") or 0
                completion_tokens += part.get("completion_tokens") or 0
    return passed, failed, prompt_tokens, completion_tokens


def summarize(jobs, results, stats, multi):
    total = passed = failed = prompt_tokens = completion_tokens = 0
    per_task = {}
    for task, _rows in jobs:
        rows = results.get(task.name, [])
        t_passed, t_failed, t_prompt, t_completion = count_rows(rows)
        total += len(rows)
        passed += t_passed
        failed += t_failed
        prompt_tokens += t_prompt
        completion_tokens += t_completion
        per_task[task.name] = {
            "total": len(rows),
            "passed": t_passed,
            "failed": t_failed,
            "total_api_calls": stats.per_task.get(task.name, 0),
        }
    if stats.first_request is None or stats.last_response is None:
        elapsed = 0.0
    else:
        elapsed = max(0.0, stats.last_response - stats.first_request)
    throughput = (stats.api_calls / elapsed * 60) if elapsed > 0 else 0.0
    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }
    if multi:
        summary["tasks"] = per_task
    return summary


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
    run = sub.add_parser("run", help="run one or more tasks over JSONL input")
    run.add_argument("--config", required=True)
    run.add_argument("--input", action="append", default=None,
                     help="input path, or <task>=<path> for a multi-task config")
    run.add_argument("--input-dir", dest="input_dir", default=None,
                     help="directory holding <task_name>.jsonl per task")
    run.add_argument("--output", required=True)
    run.add_argument("--task", action="append", default=None,
                     help="run only this task; repeatable")
    run.add_argument("--eval-model", dest="eval_model", default=None,
                     help="override the judge model for llm_judge tasks")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    return parser


def split_mapping(value):
    """"name=path" -> (name, path); a bare path -> (None, path)."""
    if "=" in value:
        name, _, path = value.partition("=")
        name = name.strip()
        if name:
            return name, path
    return None, value


def single_task_input(args, task):
    """Resolve the one input path for a Part 1 style config."""
    if args.input and args.input_dir:
        raise UserError("--input and --input-dir may not be combined")
    if args.input:
        if len(args.input) > 1:
            raise UserError("a single-task config takes exactly one --input")
        name, path = split_mapping(args.input[0])
        if name is not None and task.name is not None and name != task.name:
            # A mapping naming some other task cannot be meant for this config.
            raise UserError("--input names unknown task %r; this config defines %r"
                            % (name, task.name))
        return path
    if args.input_dir:
        if not task.name:
            raise UserError("--input-dir needs the task to have a name")
        if not os.path.isdir(args.input_dir):
            raise UserError("input directory not found: %s" % args.input_dir)
        return os.path.join(args.input_dir, "%s.jsonl" % task.name)
    raise UserError("--input or --input-dir is required")


def multi_task_inputs(args, names, selected):
    """Resolve {task name: input path} for a Part 2 style config."""
    if args.input and args.input_dir:
        raise UserError("--input and --input-dir are alternative modes and may "
                        "not be combined")
    paths = {}
    if args.input:
        for entry in args.input:
            name, path = split_mapping(entry)
            if name is None:
                raise UserError("a multi-task config needs --input <task>=<path>, "
                                "got %r" % entry)
            if name not in names:
                raise UserError("--input names unknown task %r; config defines %s"
                                % (name, ", ".join(sorted(names))))
            paths[name] = path
        missing = [n for n in selected if n not in paths]
        if missing:
            raise UserError("no --input given for task %s" % ", ".join(missing))
    elif args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise UserError("input directory not found: %s" % args.input_dir)
        for name in selected:
            path = os.path.join(args.input_dir, "%s.jsonl" % name)
            if not os.path.isfile(path):
                raise UserError("no input file %s.jsonl in %s for task %s"
                                % (name, args.input_dir, name))
            paths[name] = path
    else:
        raise UserError("--input <task>=<path> or --input-dir is required for a "
                        "multi-task config")
    return {name: paths[name] for name in selected}


def prepare_output_dir(path):
    if os.path.exists(path) and not os.path.isdir(path):
        raise UserError("--output must be a directory for a multi-task config: %s" % path)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise UserError("could not create output directory %s: %s" % (path, exc))


def select_names(args, names):
    if not args.task:
        return list(names)
    selected = []
    for name in args.task:
        if name not in names:
            raise UserError("unknown --task %r; config defines %s"
                            % (name, ", ".join(sorted(names))))
        if name not in selected:
            selected.append(name)
    return selected


def command_run(args):
    raw = read_config(args.config)
    if "task" in raw:
        return run_single(args, raw)
    return run_multi(args, raw)


def run_single(args, raw):
    cfg = raw["task"]
    if not isinstance(cfg, dict):
        raise UserError("config key 'task' must be a mapping")
    task = build_task(cfg, args, name=cfg.get("name"), label="task")
    if args.task:
        for name in args.task:
            if task.name is None or name != task.name:
                raise UserError("unknown --task %r; config defines the single task %r"
                                % (name, task.name))
    path = single_task_input(args, task)
    rows = load_rows(path)
    validate_rows(rows, task)

    jobs = [(task, rows)]
    results, stats = asyncio.run(run_all(jobs))
    write_results(args.output, results.get(task.name, []))
    print(json.dumps(summarize(jobs, results, stats, multi=False), ensure_ascii=False))
    return 0


def run_multi(args, raw):
    if "tasks" not in raw:
        raise UserError("config must define a top-level 'task' or 'tasks' key")
    tasks_cfg = raw["tasks"]
    if not isinstance(tasks_cfg, dict) or not tasks_cfg:
        raise UserError("config key 'tasks' must be a non-empty mapping")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise UserError("config key 'defaults' must be a mapping")

    selected = select_names(args, list(tasks_cfg))
    tasks = []
    for name in selected:                       # T31: unselected tasks are skipped
        cfg = tasks_cfg[name]
        if not isinstance(cfg, dict):
            raise UserError("tasks.%s must be a mapping" % name)
        tasks.append(build_task(deep_merge(defaults, cfg), args,
                                name=name, label="tasks.%s" % name))

    paths = multi_task_inputs(args, list(tasks_cfg), selected)
    prepare_output_dir(args.output)

    jobs = []
    for task in tasks:
        rows = load_rows(paths[task.name])
        try:
            validate_rows(rows, task)
        except UserError as exc:
            raise UserError("task %s: %s" % (task.name, exc))
        jobs.append((task, rows))

    results, stats = asyncio.run(run_all(jobs))
    for task, _rows in jobs:
        write_results(os.path.join(args.output, "%s.jsonl" % task.name),
                      results.get(task.name, []))
    print(json.dumps(summarize(jobs, results, stats, multi=True), ensure_ascii=False))
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
