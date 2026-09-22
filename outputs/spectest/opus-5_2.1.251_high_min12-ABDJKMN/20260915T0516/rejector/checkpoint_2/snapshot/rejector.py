#!/usr/bin/env python3
"""rejector.py - run YAML-configured generation tasks over JSONL inputs.

Reads a task config (single-task, or `defaults` + a `tasks` mapping) and one
JSONL input per task, sends one prompt per row to an OpenAI-compatible chat
completions API with enough requests in flight to use the configured request
budget, evaluates each response, and writes one JSONL result per input row.
"""
import argparse
import asyncio
import json
import math
import os
import re
import signal
import sys
import time

import aiohttp
import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

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

# Part 2: `script` evaluation commands are killed after this many seconds and
# the evaluation counts as a failure.
SCRIPT_TIMEOUT = 10.0
KILL_GRACE = 5.0

RESPONSE_KEY = "__response__"
RESPONSE_PLACEHOLDER = "{%s}" % RESPONSE_KEY

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
# A standalone uppercase answer choice: `A`, `(A)`, `A)`, `Answer: A` (the
# `A` of "Answer" is rejected because it is followed by a letter).
LETTER_RE = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")
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


def merge_task(defaults, task):
    """Overlay one task on `defaults`; nested sections merge key by key."""
    merged = dict(defaults)
    for key, value in task.items():
        base = merged.get(key)
        if isinstance(value, dict) and isinstance(base, dict):
            nested = dict(base)
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def split_config(raw):
    """Returns (multi, [(name, task_mapping), ...]) in config order."""
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping with a 'task' or "
                          "'tasks' key")
    if "task" in raw:
        # A top-level `task` key is the Part 1 single-task format.
        task = raw.get("task")
        if not isinstance(task, dict):
            raise ConfigError("config must contain a 'task' mapping")
        name = task.get("name")
        if name is not None and not isinstance(name, str):
            raise ConfigError("task.name must be a string")
        return False, [(name or "task", task)]

    tasks = raw.get("tasks")
    if not isinstance(tasks, dict):
        raise ConfigError("config must contain a 'task' mapping or a 'tasks' "
                          "mapping")
    if not tasks:
        raise ConfigError("config 'tasks' mapping is empty")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("config 'defaults' must be a mapping")

    specs = []
    for name, task in tasks.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("task names must be non-empty strings")
        if task is None:
            task = {}
        if not isinstance(task, dict):
            raise ConfigError("tasks.%s must be a mapping" % name)
        specs.append((name, merge_task(defaults, task)))
    return True, specs


def build_config(raw, args):
    """Part 1 entry point: build the single TaskConfig from a raw config."""
    multi, specs = split_config(raw)
    name, task = specs[0]
    return build_task_config(task, args, name, multi)


def build_task_config(task, args, name, multi=False):
    """Validate one (already merged) task mapping into a TaskConfig."""
    label = ("tasks.%s" % name) if multi else "task"

    prompt = task.get("prompt") or {}
    if not isinstance(prompt, dict):
        raise ConfigError("%s.prompt must be a mapping" % label)
    generation = task.get("generation") or {}
    if not isinstance(generation, dict):
        raise ConfigError("%s.generation must be a mapping" % label)

    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    model = args.model if args.model is not None else task.get("model")
    rpm = args.rpm if args.rpm is not None else task.get("rpm", 60)
    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    temperature = (args.temperature if args.temperature is not None
                   else generation.get("temperature", 0.0))
    max_tokens = (args.max_tokens if args.max_tokens is not None
                  else generation.get("max_tokens", 512))
    n = args.n if args.n is not None else generation.get("n", 1)

    api_url = _require_text(api_url, "%s.api_url" % label)
    model = _require_text(model, "%s.model" % label)
    user = _require_text(prompt.get("user"), "%s.prompt.user" % label)
    system = prompt.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError("%s.prompt.system must be a string" % label)

    if scheme not in SCHEMES:
        raise ConfigError("%s.generation.scheme must be one of %s (got %r)"
                          % (label, ", ".join(SCHEMES), scheme))

    rpm = _require_number(rpm, "%s.rpm" % label)
    if rpm <= 0:
        raise ConfigError("%s.rpm must be greater than 0" % label)
    max_tokens = _require_int(max_tokens, "%s.generation.max_tokens" % label)
    if max_tokens <= 0:
        raise ConfigError("%s.generation.max_tokens must be greater than 0" % label)
    temperature = float(_require_number(temperature, "%s.generation.temperature" % label))

    if scheme == "greedy":
        # greedy forces temperature to 0.0 and ignores n.
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError("%s.generation.temperature must be > 0 for "
                              "scheme 'sample'" % label)
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError("%s.generation.temperature must be > 0 for "
                              "scheme 'rejection'" % label)
        n = _require_int(n, "%s.generation.n" % label)
        if n < 1:
            raise ConfigError("%s.generation.n must be >= 1 for scheme "
                              "'rejection'" % label)

    eval_model = getattr(args, "eval_model", None)
    evaluation = build_evaluation(task.get("evaluation"), scheme, label,
                                  model, eval_model)

    output_field = task.get("output_field", "output")
    output_field = _require_text(output_field, "%s.output_field" % label)

    return TaskConfig(name, api_url, model, rpm, system, user, scheme,
                      temperature, max_tokens, n, evaluation, output_field)


def build_evaluation(raw, scheme, label="task", task_model=None,
                     eval_model=None):
    """Validate the evaluation block; returns a normalised dict or None."""
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("%s.evaluation is required for scheme "
                              "'rejection'" % label)
        return None
    if not isinstance(raw, dict):
        raise ConfigError("%s.evaluation must be a mapping" % label)

    eval_type = raw.get("type")
    if eval_type not in EVAL_TYPES:
        raise ConfigError("%s.evaluation.type must be one of %s (got %r)"
                          % (label, ", ".join(EVAL_TYPES), eval_type))

    # A judge response is a bare score, so `first_number` is its default.
    default_extract = "first_number" if eval_type == "llm_judge" else "full"
    extract = raw.get("extract", default_extract)
    if extract not in EXTRACT_METHODS:
        raise ConfigError("%s.evaluation.extract must be one of %s (got %r)"
                          % (label, ", ".join(EXTRACT_METHODS), extract))

    evaluation = {"type": eval_type, "extract": extract, "answer_field": None,
                  "pattern": None, "command_template": None,
                  "success_exit_code": 0, "judge_system": None,
                  "judge_user": None, "threshold": None, "model": None}

    if eval_type in ("exact_match", "contains"):
        evaluation["answer_field"] = _require_text(
            raw.get("answer_field"),
            "%s.evaluation.answer_field (required for type '%s')"
            % (label, eval_type))
    elif eval_type == "regex":
        pattern = _require_text(
            raw.get("pattern"),
            "%s.evaluation.pattern (required for type 'regex')" % label)
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError("%s.evaluation.pattern is not a valid regular "
                              "expression: %s" % (label, exc))
        evaluation["pattern"] = pattern
    elif eval_type == "script":
        evaluation["command_template"] = _require_text(
            raw.get("command_template"),
            "%s.evaluation.command_template (required for type 'script')"
            % label)
        exit_code = raw.get("success_exit_code", 0)
        evaluation["success_exit_code"] = _require_int(
            exit_code, "%s.evaluation.success_exit_code" % label)
    else:  # llm_judge
        judge_prompt = raw.get("judge_prompt")
        if not isinstance(judge_prompt, dict):
            raise ConfigError("%s.evaluation.judge_prompt must be a mapping "
                              "(required for type 'llm_judge')" % label)
        evaluation["judge_user"] = _require_text(
            judge_prompt.get("user"), "%s.evaluation.judge_prompt.user" % label)
        judge_system = judge_prompt.get("system")
        if judge_system is not None and not isinstance(judge_system, str):
            raise ConfigError("%s.evaluation.judge_prompt.system must be a "
                              "string" % label)
        evaluation["judge_system"] = judge_system
        threshold = raw.get("threshold")
        if threshold is None:
            raise ConfigError("%s.evaluation.threshold is required for type "
                              "'llm_judge'" % label)
        evaluation["threshold"] = _require_number(
            threshold, "%s.evaluation.threshold" % label)
        model = raw.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ConfigError("%s.evaluation.model must be a non-empty string"
                              % label)
        # --eval-model beats the config, which beats the task's own model.
        evaluation["model"] = eval_model or model or task_model

    return evaluation


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


def render_template(template, row, row_index, extra=None):
    """Substitute {field} placeholders from `row` (and `extra`)."""
    missing = []

    def replace(match):
        field = match.group(1)
        if extra is not None and field in extra:
            return to_text(extra[field])
        if field not in row:
            missing.append(field)
            return match.group(0)
        return to_text(row[field])

    rendered = PLACEHOLDER_RE.sub(replace, template)
    if missing:
        raise InputError("row %d: missing field '%s'" % (row_index, missing[0]))
    return rendered


def render_command(template, row, response, row_index):
    """Render a script command; row text may itself carry {__response__}."""
    rendered = render_template(template, row, row_index,
                               {RESPONSE_KEY: response})
    if RESPONSE_PLACEHOLDER in rendered:
        # A row field such as {test_code} expanded to text containing
        # {__response__}; substitute it before the command is executed.
        rendered = rendered.replace(RESPONSE_PLACEHOLDER, to_text(response))
    return rendered


def check_fields(template, row, row_index):
    """Fail fast on placeholders a row cannot fill (ignoring __response__)."""
    for match in PLACEHOLDER_RE.finditer(template):
        field = match.group(1)
        if field == RESPONSE_KEY:
            continue
        if field not in row:
            raise InputError("row %d: missing field '%s'" % (row_index, field))


def build_messages(cfg, rows):
    """Render every row up front so input errors abort before any request."""
    prepared = []
    evaluation = cfg.evaluation or {}
    answer_field = evaluation.get("answer_field")
    for index, row in enumerate(rows):
        messages = []
        if cfg.system is not None:
            messages.append({"role": "system",
                             "content": render_template(cfg.system, row, index)})
        messages.append({"role": "user",
                         "content": render_template(cfg.user, row, index)})
        if answer_field is not None and answer_field not in row:
            raise InputError("row %d: missing field '%s'" % (index, answer_field))
        if evaluation.get("command_template"):
            check_fields(evaluation["command_template"], row, index)
        if evaluation.get("judge_user"):
            check_fields(evaluation["judge_user"], row, index)
        if evaluation.get("judge_system"):
            check_fields(evaluation["judge_system"], row, index)
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
    if method == "first_number":
        match = NUMBER_RE.search(text)
        return match.group(0) if match else None
    if method == "letter":
        match = LETTER_RE.search(text)
        return match.group(1) if match else None
    raise ConfigError("unknown extract method: %r" % method)


def to_number(text):
    """Parse an extracted number; int when it has no fractional part."""
    if text is None:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value.is_integer() and "." not in text:
        return int(value)
    return value


def evaluate(text, row, evaluation):
    """Returns (passed, extracted_answer) for one non-async evaluation."""
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


async def run_script_eval(evaluation, row, response, row_index):
    """Run a `script` evaluation; returns True when the exit code matches."""
    command = render_command(evaluation["command_template"], row, response,
                             row_index)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own process group: a timeout can then take the shell and every
            # process it spawned, not just the shell.
            start_new_session=True)
    except OSError:
        return False
    try:
        # stdout/stderr are captured but deliberately not reported anywhere.
        await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        _kill_process_group(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE)
        except (asyncio.TimeoutError, ProcessLookupError, OSError):
            pass
        return False
    return proc.returncode == evaluation["success_exit_code"]


def _kill_process_group(proc):
    """SIGKILL the timed-out command's whole process group, by pid."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


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

    @classmethod
    def combine(cls, parts):
        total = cls()
        for part in parts:
            total.api_calls += part.api_calls
            total.prompt_tokens += part.prompt_tokens
            total.completion_tokens += part.completion_tokens
            if part.first_request is not None and (
                    total.first_request is None
                    or part.first_request < total.first_request):
                total.first_request = part.first_request
            if part.last_response is not None:
                total.closed(part.last_response)
        return total


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

    async def call_api(self, messages, model=None):
        """One logical request, with retries. Returns (content, meta) or None."""
        model = model or self.cfg.model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        for attempt in range(MAX_HTTP_ATTEMPTS):
            retryable, outcome = await self._post_once(payload, model)
            if outcome is not None:
                return outcome
            if not retryable:
                return None
            if attempt < MAX_HTTP_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        return None

    async def _post_once(self, payload, model):
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
            "model": model,
            "prompt_tokens": _token(usage, "prompt_tokens"),
            "completion_tokens": _token(usage, "completion_tokens"),
            "total_tokens": _token(usage, "total_tokens"),
            "latency_ms": int(round((end - start) * 1000)),
            "finish_reason": choice.get("finish_reason"),
        }
        self.stats.prompt_tokens += meta["prompt_tokens"]
        self.stats.completion_tokens += meta["completion_tokens"]
        return False, (content, meta)

    async def judge(self, row, response, row_index):
        """Returns (passed, extracted, judge_score, judge_meta)."""
        evaluation = self.cfg.evaluation
        extra = {RESPONSE_KEY: response}
        messages = []
        if evaluation["judge_system"] is not None:
            messages.append({
                "role": "system",
                "content": render_template(evaluation["judge_system"], row,
                                           row_index, extra)})
        messages.append({
            "role": "user",
            "content": render_template(evaluation["judge_user"], row,
                                       row_index, extra)})
        outcome = await self.call_api(messages, model=evaluation["model"])
        if outcome is None:
            return False, None, None, None
        text, meta = outcome
        extracted = extract_answer(text, evaluation["extract"])
        score = to_number(extracted)
        passed = score is not None and score >= evaluation["threshold"]
        return bool(passed), extracted, score, meta

    async def evaluate_response(self, content, row, row_index):
        """Returns (passed, extracted, judge_score, judge_meta)."""
        evaluation = self.cfg.evaluation
        if evaluation is None:
            return None, None, None, None
        if evaluation["type"] == "script":
            passed = await run_script_eval(evaluation, row, content, row_index)
            return bool(passed), None, None, None
        if evaluation["type"] == "llm_judge":
            return await self.judge(row, content, row_index)
        passed, extracted = evaluate(content, row, evaluation)
        return passed, extracted, None, None

    async def run_row(self, row, messages, row_index):
        """Produce the output record for one input row."""
        max_attempts = self.cfg.n if self.cfg.scheme == "rejection" else 1
        metas = []
        attempts = 0
        judge_score = None
        for _ in range(max_attempts):
            attempts += 1
            outcome = await self.call_api(messages)
            if outcome is None:
                # The request never produced a response: the row has failed.
                return self._record(row, None, False, None, attempts, metas,
                                    judge_score)
            content, meta = outcome
            passed, extracted, judge_score, judge_meta = \
                await self.evaluate_response(content, row, row_index)
            if self.is_judge:
                meta["judge_meta"] = judge_meta
            metas.append(meta)
            if self.cfg.scheme != "rejection" or passed:
                return self._record(row, content, passed, extracted, attempts,
                                    metas, judge_score)
        # Rejection sampling exhausted every attempt without a passing response.
        return self._record(row, None, False, None, attempts, metas, judge_score)

    @property
    def is_judge(self):
        return (self.cfg.evaluation is not None
                and self.cfg.evaluation["type"] == "llm_judge")

    def _record(self, row, content, passed, extracted, attempts, metas,
                judge_score=None):
        if content is None:
            output = None
            extracted = None
            judge_score = None
        else:
            output = {self.cfg.output_field: content}
        if not metas:
            meta = None
        elif len(metas) == 1:
            meta = metas[0]
        else:
            meta = metas
        result = {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": attempts,
        }
        if self.is_judge:
            result["judge_score"] = judge_score
        return {
            "input": row,
            "output": output,
            "result": result,
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
        tasks = [asyncio.ensure_future(runner.run_row(row, messages, index))
                 for index, (row, messages) in enumerate(zip(rows, prepared))]
        records = await asyncio.gather(*tasks)
    return list(records), stats


async def process_all(jobs):
    """Run every task concurrently; requests may interleave across tasks."""
    results = await asyncio.gather(
        *[process(cfg, rows, prepared) for cfg, rows, prepared in jobs])
    return list(results)


def count_rows(records):
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
    return passed, failed


def summarise(records, stats):
    passed, failed = count_rows(records)
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


def summarise_all(names, results):
    """Aggregate summary plus a per-task block for every task that ran."""
    all_records = []
    for records, _ in results:
        all_records.extend(records)
    combined = Stats.combine([stats for _, stats in results])
    summary = summarise(all_records, combined)
    tasks = {}
    for name, (records, stats) in zip(names, results):
        passed, failed = count_rows(records)
        tasks[name] = {
            "total": len(records),
            "passed": passed,
            "failed": failed,
            "total_api_calls": stats.api_calls,
        }
    summary["tasks"] = tasks
    return summary


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
    run = sub.add_parser("run", help="run tasks over JSONL input files")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", action="append", default=None,
                     help="JSONL input file, or <task>=<path> for multi-task "
                          "configs (repeatable)")
    run.add_argument("--input-dir", dest="input_dir", default=None,
                     help="directory holding <task_name>.jsonl inputs")
    run.add_argument("--output", required=True,
                     help="JSONL output file, or output directory for "
                          "multi-task configs")
    run.add_argument("--task", action="append", dest="task_names", default=None,
                     help="run only the named task (repeatable)")
    run.add_argument("--eval-model", dest="eval_model", default=None,
                     help="override the judge model for llm_judge tasks")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=SCHEMES, default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    return parser


def select_tasks(specs, selected):
    """Filter (name, task) specs by the --task flags, preserving order."""
    if not selected:
        return specs
    known = set(name for name, _ in specs)
    for name in selected:
        if name not in known:
            raise ConfigError("config has no task named %r" % name)
    wanted = set(selected)
    return [(name, task) for name, task in specs if name in wanted]


def resolve_inputs(cfgs, multi, args, all_names):
    """Returns a list of input paths aligned with `cfgs`."""
    entries = args.input or []
    if entries and args.input_dir:
        raise ConfigError("--input and --input-dir may not be combined")

    if args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise InputError("input directory not found: %s" % args.input_dir)
        return [os.path.join(args.input_dir, "%s.jsonl" % cfg.name)
                for cfg in cfgs]

    if not entries:
        raise ConfigError("--input or --input-dir is required")

    if multi:
        mapping = {}
        for entry in entries:
            if "=" not in entry:
                raise ConfigError("multi-task configs require --input "
                                  "<task>=<path> (got %r)" % entry)
            name, _, path = entry.partition("=")
            if name not in all_names:
                raise ConfigError("--input names unknown task %r" % name)
            mapping[name] = path
        paths = []
        for cfg in cfgs:
            if cfg.name not in mapping:
                raise InputError("no --input given for task '%s'" % cfg.name)
            paths.append(mapping[cfg.name])
        return paths

    if len(entries) > 1:
        raise ConfigError("--input may only be given once for single-task "
                          "configs")
    entry = entries[0]
    if "=" in entry:
        name, _, path = entry.partition("=")
        if name == cfgs[0].name:
            return [path]
    return [entry]


def resolve_outputs(cfgs, multi, output):
    """Returns a list of output paths aligned with `cfgs`."""
    if not multi:
        return [output]
    if os.path.exists(output) and not os.path.isdir(output):
        raise ConfigError("--output must be a directory for multi-task "
                          "configs: %s" % output)
    try:
        os.makedirs(output, exist_ok=True)
    except OSError as exc:
        raise InputError("could not create output directory %s: %s"
                         % (output, exc))
    return [os.path.join(output, "%s.jsonl" % cfg.name) for cfg in cfgs]


def run_command(args):
    raw = load_config_file(args.config)
    multi, specs = split_config(raw)
    all_names = [name for name, _ in specs]
    selected = select_tasks(specs, args.task_names)
    cfgs = [build_task_config(task, args, name, multi)
            for name, task in selected]

    inputs = resolve_inputs(cfgs, multi, args, all_names)
    out_paths = resolve_outputs(cfgs, multi, args.output)

    jobs = []
    for cfg, path in zip(cfgs, inputs):
        rows = load_rows(path)
        jobs.append((cfg, rows, build_messages(cfg, rows)))

    results = asyncio.run(process_all(jobs))
    for path, (records, _) in zip(out_paths, results):
        write_output(path, records)
    summary = summarise_all([cfg.name for cfg in cfgs], results)
    sys.stdout.write(json.dumps(summary) + "\n")
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
