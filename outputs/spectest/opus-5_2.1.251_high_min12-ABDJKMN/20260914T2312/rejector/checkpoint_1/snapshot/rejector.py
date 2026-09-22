#!/usr/bin/env python3
"""rejector.py -- run a YAML-configured prompting task over a JSONL file.

    python rejector.py run --config task.yaml --input data.jsonl \
        --output results.jsonl

Reads a task config and a JSONL input file, sends one chat-completion request
per row (per attempt, for rejection sampling) to an OpenAI-compatible API,
writes one JSONL result per input row and prints a JSON summary on stdout.

Interpretation decisions for under-specified corners are recorded in
AMBIGUITIES.md; the code refers to them as T1, T2, ...
"""

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

# Total HTTP calls per logical attempt: the initial call plus retries, given up
# on after the third failure (T1).
MAX_HTTP_CALLS = 3

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_OUTPUT_FIELD = "output"          # T13
DEFAULT_EXTRACT = "full"                 # T4
MAX_CONCURRENCY = 64                     # T20
REQUEST_TIMEOUT = 300

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")   # T10


class UserError(Exception):
    """A configuration or input error: reported on stderr, exit code 1."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Task:
    """The merged, validated task definition."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def endpoint(self):
        return self.api_url.rstrip("/") + "/v1/chat/completions"


def load_config(path):
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError as exc:
        raise UserError("cannot read config file %s: %s" % (path, exc))
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UserError("config file %s is not valid YAML: %s" % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("task"), dict):
        raise UserError("config file %s must contain a top-level 'task' "
                        "mapping" % path)
    return data["task"]


def _require_text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise UserError("%s is required and must be a non-empty string" % what)
    return value


def _as_number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError("%s must be a number" % what)
    return float(value)


def _as_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise UserError("%s must be an integer" % what)
    return value


def build_task(raw, args):
    """Merge CLI overrides over the config file and validate the result."""
    generation = raw.get("generation") or {}
    if not isinstance(generation, dict):
        raise UserError("task.generation must be a mapping")

    api_url = args.api_url if args.api_url is not None else raw.get("api_url")
    model = args.model if args.model is not None else raw.get("model")
    rpm = args.rpm if args.rpm is not None else raw.get("rpm", DEFAULT_RPM)
    scheme = args.scheme if args.scheme is not None \
        else generation.get("scheme", "greedy")
    temperature = args.temperature if args.temperature is not None \
        else generation.get("temperature", 0.0)          # T7
    max_tokens = args.max_tokens if args.max_tokens is not None \
        else generation.get("max_tokens", DEFAULT_MAX_TOKENS)
    n = args.n if args.n is not None else generation.get("n", 1)

    _require_text(api_url, "task.api_url")
    _require_text(model, "task.model")
    rpm = _as_int(rpm, "task.rpm")
    if rpm <= 0:
        raise UserError("task.rpm must be a positive integer")
    max_tokens = _as_int(max_tokens, "task.generation.max_tokens")
    if max_tokens <= 0:
        raise UserError("task.generation.max_tokens must be positive")
    temperature = _as_number(temperature, "task.generation.temperature")
    n = _as_int(n, "task.generation.n")

    if scheme not in SCHEMES:
        raise UserError("task.generation.scheme must be one of %s (got %r)"
                        % (", ".join(SCHEMES), scheme))

    prompt = raw.get("prompt")
    if not isinstance(prompt, dict):
        raise UserError("task.prompt is required and must be a mapping")
    system = prompt.get("system")                                   # T19
    if system is not None and not isinstance(system, str):
        raise UserError("task.prompt.system must be a string")
    user = _require_text(prompt.get("user"), "task.prompt.user")

    if scheme == "greedy":
        temperature = 0.0                                           # T8
    else:
        if temperature <= 0:
            raise UserError("task.generation.temperature must be > 0 for "
                            "scheme %r (got %r)" % (scheme, temperature))
    if scheme == "rejection" and n < 1:
        raise UserError("task.generation.n must be >= 1 for rejection sampling")

    evaluation = build_evaluation(raw.get("evaluation"), scheme)

    output_field = raw.get("output_field", DEFAULT_OUTPUT_FIELD)
    if output_field is None:
        output_field = DEFAULT_OUTPUT_FIELD
    _require_text(output_field, "task.output_field")

    return Task(name=raw.get("name"), api_url=api_url, model=model, rpm=rpm,
                system_template=system, user_template=user, scheme=scheme,
                temperature=temperature, max_tokens=max_tokens, n=n,
                evaluation=evaluation, output_field=output_field)


def build_evaluation(raw, scheme):
    """Validate the evaluation block; None means 'no evaluation configured'."""
    if raw is None:
        if scheme == "rejection":
            raise UserError("task.evaluation is required for scheme "
                            "'rejection'")
        return None
    if not isinstance(raw, dict):
        raise UserError("task.evaluation must be a mapping")

    etype = raw.get("type")
    if etype not in EVAL_TYPES:
        raise UserError("task.evaluation.type must be one of %s (got %r)"
                        % (", ".join(EVAL_TYPES), etype))

    extract = raw.get("extract") or DEFAULT_EXTRACT
    if extract not in EXTRACT_METHODS:
        raise UserError("task.evaluation.extract must be one of %s (got %r)"
                        % (", ".join(EXTRACT_METHODS), extract))

    answer_field = None
    pattern = None
    if etype in ("exact_match", "contains"):
        answer_field = _require_text(
            raw.get("answer_field"),
            "task.evaluation.answer_field (required for %s)" % etype)
    else:  # regex requires pattern, not answer_field
        pattern = _require_text(raw.get("pattern"),
                                "task.evaluation.pattern (required for regex)")
        try:
            pattern = re.compile(pattern)
        except re.error as exc:
            raise UserError("task.evaluation.pattern is not a valid regular "
                            "expression: %s" % exc)

    return {"type": etype, "extract": extract, "answer_field": answer_field,
            "pattern": pattern}


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def load_rows(path):
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise UserError("cannot read input file %s: %s" % (path, exc))
    rows = []
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue                                               # T17
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise UserError("input file %s line %d is not valid JSON: %s"
                            % (path, lineno, exc))
        if not isinstance(row, dict):
            raise UserError("input file %s line %d is not a JSON object"
                            % (path, lineno))
        rows.append(row)
    return rows


def template_fields(template):
    return [] if template is None else PLACEHOLDER_RE.findall(template)


def validate_rows(rows, task):
    """Pre-flight every row so a bad file fails before any request (T11)."""
    fields = template_fields(task.system_template) + \
        template_fields(task.user_template)
    answer_field = task.evaluation["answer_field"] if task.evaluation else None
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise UserError("row %d: missing field '%s' referenced by "
                                "prompt template" % (index, field))
        if answer_field is not None and answer_field not in row:   # T12
            raise UserError("row %d: missing field '%s' required by "
                            "evaluation" % (index, answer_field))


def render(template, row):
    if template is None:
        return None
    return PLACEHOLDER_RE.sub(lambda m: str(row[m.group(1)]), template)


def build_messages(task, row):
    messages = []
    if task.system_template is not None:
        messages.append({"role": "system",
                         "content": render(task.system_template, row)})
    messages.append({"role": "user", "content": render(task.user_template, row)})
    return messages


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def extract_answer(text, method):
    """Reduce a response to the value the evaluation compares (None if absent)."""
    if method == "full":
        return text
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        return matches[-1] if matches else None                    # T18
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    raise UserError("unknown extract method %r" % method)


def evaluate(text, row, evaluation):
    """-> (passed, extracted_answer).  passed is None with no evaluation."""
    if evaluation is None:
        return None, None
    extracted = extract_answer(text, evaluation["extract"])        # T5
    if extracted is None:
        return False, None
    etype = evaluation["type"]
    if etype == "exact_match":
        expected = str(row[evaluation["answer_field"]])
        return extracted.strip() == expected.strip(), extracted    # T9
    if etype == "contains":
        expected = str(row[evaluation["answer_field"]])
        return expected in extracted, extracted
    return evaluation["pattern"].search(extracted) is not None, extracted  # T6


# ---------------------------------------------------------------------------
# API access
# ---------------------------------------------------------------------------

class Stats:
    """Thread-safe run-wide counters."""

    def __init__(self):
        self._lock = threading.Lock()
        self.api_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.first_start = None
        self.last_end = None

    def start_call(self, when):
        with self._lock:
            if self.first_start is None or when < self.first_start:
                self.first_start = when

    def end_call(self, when, prompt_tokens=0, completion_tokens=0):
        with self._lock:
            self.api_calls += 1
            self.prompt_tokens += prompt_tokens                    # T22
            self.completion_tokens += completion_tokens
            if self.last_end is None or when > self.last_end:
                self.last_end = when

    @property
    def elapsed(self):
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


class Attempt:
    """The outcome of one logical generation attempt."""

    def __init__(self, ok, content, meta):
        self.ok = ok
        self.content = content
        self.meta = meta


def _meta(model, latency_ms, usage=None, finish_reason=None):
    if usage is None:                                              # T3
        return {"model": model, "prompt_tokens": None,
                "completion_tokens": None, "total_tokens": None,
                "latency_ms": latency_ms, "finish_reason": None}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total = usage.get("total_tokens")
    total = int(total) if total is not None else prompt_tokens + completion_tokens
    return {"model": model, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "total_tokens": total,
            "latency_ms": latency_ms, "finish_reason": finish_reason}


def call_api(task, messages, stats):
    """One logical attempt: up to MAX_HTTP_CALLS HTTP calls for 5xx (T1, T23)."""
    payload = json.dumps({
        "model": task.model,
        "messages": messages,
        "temperature": task.temperature,
        "max_tokens": task.max_tokens,
    }).encode("utf-8")

    latency_ms = 0
    for call in range(MAX_HTTP_CALLS):
        request = urllib.request.Request(
            task.endpoint, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"})
        started = time.time()
        stats.start_call(started)
        retryable = False
        try:
            with urllib.request.urlopen(request,
                                        timeout=REQUEST_TIMEOUT) as response:
                body = response.read()
            latency_ms = int(round((time.time() - started) * 1000))
            try:
                data = json.loads(body.decode("utf-8"))
                choice = data["choices"][0]
                content = choice["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                stats.end_call(time.time())
                return Attempt(False, None, _meta(task.model, latency_ms))
            usage = data.get("usage") or {}
            meta = _meta(task.model, latency_ms, usage,
                         choice.get("finish_reason"))
            stats.end_call(time.time(), meta["prompt_tokens"],
                           meta["completion_tokens"])
            return Attempt(True, content, meta)
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:
                pass
            retryable = 500 <= exc.code < 600
        except Exception:
            # Transport-level failure (connection refused, timeout, ...): the
            # transient class, so retried like a 5xx (T23).
            retryable = True
        latency_ms = int(round((time.time() - started) * 1000))
        stats.end_call(time.time())
        if not retryable:
            break
    return Attempt(False, None, _meta(task.model, latency_ms))


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------

class RowResult:
    def __init__(self, row, output, passed, extracted, metas):
        self.row = row
        self.output = output
        self.passed = passed
        self.extracted = extracted
        self.metas = metas

    @property
    def attempts(self):
        return len(self.metas)

    def to_json(self, task):
        metas = self.metas
        meta = metas[0] if len(metas) == 1 else metas              # T2
        output = None if self.output is None \
            else {task.output_field: self.output}
        return {
            "input": self.row,
            "output": output,
            "result": {"passed": self.passed,
                       "extracted_answer": self.extracted,
                       "attempts": self.attempts},
            "meta": meta,
        }

    @property
    def counts_as_passed(self):
        if self.passed is True:
            return True
        return self.passed is None and self.output is not None

    @property
    def counts_as_failed(self):
        return self.passed is False or self.output is None


def process_row(row, task, stats):
    messages = build_messages(task, row)
    limit = task.n if task.scheme == "rejection" else 1            # n ignored
    metas = []
    for _ in range(limit):
        attempt = call_api(task, messages, stats)
        metas.append(attempt.meta)
        if not attempt.ok:
            # Retries exhausted (or a non-retryable error): the row is done (T15)
            return RowResult(row, None, False, None, metas)
        passed, extracted = evaluate(attempt.content, row, task.evaluation)
        if task.scheme != "rejection":
            return RowResult(row, attempt.content, passed, extracted, metas)
        if passed:
            return RowResult(row, attempt.content, True, extracted, metas)
    return RowResult(row, None, False, None, metas)                # exhausted


def concurrency_for(rpm, row_count):
    """In-flight budget: saturate the server's rpm without unbounded threads."""
    return max(1, min(max(rpm, 4), MAX_CONCURRENCY, max(row_count, 1)))


def run(task, rows, output_path):
    stats = Stats()
    results = [None] * len(rows)
    if rows:
        workers = concurrency_for(task.rpm, len(rows))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_row, row, task, stats): index
                       for index, row in enumerate(rows)}
            for future, index in futures.items():
                results[index] = future.result()

    try:
        with open(output_path, "w") as fh:
            for result in results:
                fh.write(json.dumps(result.to_json(task)) + "\n")
    except OSError as exc:
        raise UserError("cannot write output file %s: %s" % (output_path, exc))

    elapsed = round(stats.elapsed, 1)
    # Reported throughput stays consistent with the reported elapsed time (T24);
    # on runs too short to round to 0.1s the raw time avoids a bogus 0.0.
    divisor = elapsed or stats.elapsed
    throughput = round(stats.api_calls / divisor * 60, 1) if divisor else 0.0
    return {
        "total": len(rows),
        "passed": sum(1 for r in results if r.counts_as_passed),
        "failed": sum(1 for r in results if r.counts_as_failed),
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": elapsed,
        "throughput_rpm": throughput,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class ArgumentParser(argparse.ArgumentParser):
    """Usage errors are configuration errors: exit 1, not argparse's 2 (T21)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser():
    parser = ArgumentParser(prog="rejector.py",
                            description="Run a prompting task over a JSONL file.")
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="run a task")
    run_parser.add_argument("--config", required=True, help="YAML task config")
    run_parser.add_argument("--input", required=True, help="JSONL input file")
    run_parser.add_argument("--output", required=True, help="JSONL output file")
    run_parser.add_argument("--api-url", dest="api_url", default=None)
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument("--rpm", type=int, default=None)
    run_parser.add_argument("--max-tokens", dest="max_tokens", type=int,
                            default=None)
    run_parser.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run_parser.add_argument("--temperature", type=float, default=None)
    run_parser.add_argument("--n", type=int, default=None)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_usage(sys.stderr)
        sys.stderr.write("error: a command is required (run)\n")
        return 1
    try:
        task = build_task(load_config(args.config), args)
        rows = load_rows(args.input)
        validate_rows(rows, task)
        summary = run(task, rows, args.output)
    except UserError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
