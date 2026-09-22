#!/usr/bin/env python3
"""rejector - run YAML-configured prompt tasks against an OpenAI-compatible API.

Usage:
    python rejector.py run --config <path> --input <path> --output <path> [options]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

MAX_HTTP_TRIES = 3  # total requests per logical attempt, including the first

# Placeholder such as {question}. Deliberately narrow so that JSON braces or
# prose inside a prompt template are left untouched.
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Integers/decimals, preferring a comma-grouped form when one is present.
NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?|-?\.\d+")


class ConfigError(Exception):
    """Raised for any configuration or input problem (exit code 1)."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def to_text(value: Any) -> str:
    """Render an arbitrary JSON value as text for prompts/comparisons."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_template(template: str, row: Dict[str, Any], row_index: int) -> str:
    """Substitute {field} placeholders from ``row``.

    Raises ConfigError naming the row index and the first missing field.
    """
    missing: List[str] = []

    def repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in row:
            missing.append(name)
            return match.group(0)
        return to_text(row[name])

    rendered = PLACEHOLDER_RE.sub(repl, template)
    if missing:
        raise ConfigError(
            "row %d: missing field %r referenced by prompt template"
            % (row_index, missing[0])
        )
    return rendered


def template_fields(template: str) -> List[str]:
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(template or "")))


def extract_value(text: str, method: str) -> Optional[str]:
    """Apply an extract method to a model response."""
    if method == "full":
        return text
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        if not matches:
            return None
        return matches[-1].replace(",", "")
    raise ConfigError("unknown extract method: %r" % (method,))


def _normalize(value: str) -> str:
    out = value.strip()
    out = out.replace(",", "")
    out = out.lstrip("$").strip()
    out = out.rstrip(".").strip()
    return out


def _as_float(value: str) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def answers_match(extracted: str, expected: str) -> bool:
    if extracted == expected:
        return True
    left, right = _normalize(extracted), _normalize(expected)
    if left == right:
        return True
    left_num, right_num = _as_float(left), _as_float(right)
    if left_num is not None and right_num is not None:
        return math.isclose(left_num, right_num, rel_tol=1e-9, abs_tol=1e-9)
    return left.casefold() == right.casefold()


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


class Evaluation:
    def __init__(
        self,
        type_: str,
        answer_field: Optional[str],
        extract: Optional[str],
        pattern: Optional[str],
    ) -> None:
        self.type = type_
        self.answer_field = answer_field
        self.extract = extract
        self.pattern_source = pattern
        self.pattern = re.compile(pattern) if pattern is not None else None

    def evaluate(self, text: str, row: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Return (passed, extracted_answer) for one response."""
        if self.type == "exact_match":
            extracted = extract_value(text, self.extract or "full")
            expected = to_text(row.get(self.answer_field))
            passed = extracted is not None and answers_match(extracted, expected)
            return passed, extracted

        if self.type == "contains":
            expected = to_text(row.get(self.answer_field))
            passed = expected in text
            if self.extract:
                extracted = extract_value(text, self.extract)
            else:
                extracted = expected if passed else None
            return passed, extracted

        # regex
        match = self.pattern.search(text) if self.pattern else None
        passed = match is not None
        if self.extract:
            extracted = extract_value(text, self.extract)
        elif match is None:
            extracted = None
        elif match.groups():
            extracted = match.group(1)
        else:
            extracted = match.group(0)
        return passed, extracted


class TaskConfig:
    def __init__(self) -> None:
        self.name: str = "task"
        self.api_url: str = ""
        self.model: str = ""
        self.rpm: int = 60
        self.system_template: Optional[str] = None
        self.user_template: Optional[str] = None
        self.scheme: str = "greedy"
        self.temperature: float = 0.0
        self.max_tokens: int = 512
        self.n: int = 1
        self.evaluation: Optional[Evaluation] = None
        self.output_field: str = "output"
        self.concurrency: int = 0
        self.timeout: float = 600.0

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def max_attempts(self) -> int:
        return self.n if self.scheme == "rejection" else 1

    def prompt_fields(self) -> List[str]:
        fields = template_fields(self.system_template or "")
        for field in template_fields(self.user_template or ""):
            if field not in fields:
                fields.append(field)
        return fields


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError("%s must be a mapping" % label)
    return value


def _as_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a positive integer" % label)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a positive integer, got %r" % (label, value))
    if number < 1:
        raise ConfigError("%s must be a positive integer, got %r" % (label, value))
    return number


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a number" % label)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a number, got %r" % (label, value))


def load_config(path: str, args: argparse.Namespace) -> TaskConfig:
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError("could not parse YAML config %s: %s" % (path, exc))
    except OSError as exc:
        raise ConfigError("could not read config %s: %s" % (path, exc))

    if raw is None:
        raise ConfigError("config file is empty: %s" % path)
    raw = _require_mapping(raw, "config")

    if "task" in raw:
        task = _require_mapping(raw["task"], "'task'")
    elif "prompt" in raw:
        task = raw  # tolerate a config written without the 'task' wrapper
    else:
        raise ConfigError("config must contain a 'task' section")

    cfg = TaskConfig()
    cfg.name = str(task.get("name") or "task")

    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if not api_url or not str(api_url).strip():
        raise ConfigError("task.api_url is required")
    cfg.api_url = str(api_url).strip()

    model = args.model if args.model is not None else task.get("model")
    if not model or not str(model).strip():
        raise ConfigError("task.model is required")
    cfg.model = str(model).strip()

    rpm = args.rpm if args.rpm is not None else task.get("rpm", 60)
    cfg.rpm = _as_positive_int(rpm, "task.rpm")

    if "prompt" not in task:
        raise ConfigError("task.prompt is required")
    prompt = _require_mapping(task["prompt"], "task.prompt")
    system = prompt.get("system")
    user = prompt.get("user")
    if system is None and user is None:
        raise ConfigError("task.prompt must define 'system' and/or 'user'")
    cfg.system_template = None if system is None else to_text(system)
    cfg.user_template = None if user is None else to_text(user)

    generation = _require_mapping(task.get("generation") or {}, "task.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    scheme = str(scheme).strip().lower()
    if scheme not in SCHEMES:
        raise ConfigError(
            "task.generation.scheme must be one of %s, got %r"
            % (", ".join(SCHEMES), scheme)
        )
    cfg.scheme = scheme

    max_tokens = (
        args.max_tokens if args.max_tokens is not None else generation.get("max_tokens", 512)
    )
    cfg.max_tokens = _as_positive_int(max_tokens, "task.generation.max_tokens")

    temp_raw = (
        args.temperature
        if args.temperature is not None
        else generation.get("temperature")
    )
    if scheme == "greedy":
        cfg.temperature = 0.0  # greedy always forces temperature 0.0
    else:
        if temp_raw is None:
            cfg.temperature = 1.0
        else:
            cfg.temperature = _as_number(temp_raw, "task.generation.temperature")
        if cfg.temperature <= 0:
            raise ConfigError(
                "task.generation.temperature must be > 0 for scheme %r, got %s"
                % (scheme, cfg.temperature)
            )

    n_raw = args.n if args.n is not None else generation.get("n", 1)
    cfg.n = _as_positive_int(n_raw, "task.generation.n")

    evaluation_raw = task.get("evaluation")
    if evaluation_raw is not None:
        evaluation = _require_mapping(evaluation_raw, "task.evaluation")
        eval_type = evaluation.get("type")
        if eval_type is None:
            raise ConfigError("task.evaluation.type is required")
        eval_type = str(eval_type).strip()
        if eval_type not in EVAL_TYPES:
            raise ConfigError(
                "task.evaluation.type must be one of %s, got %r"
                % (", ".join(EVAL_TYPES), eval_type)
            )

        answer_field = evaluation.get("answer_field")
        pattern = evaluation.get("pattern")
        extract = evaluation.get("extract")

        if eval_type in ("exact_match", "contains"):
            if answer_field is None or not str(answer_field).strip():
                raise ConfigError(
                    "task.evaluation.answer_field is required for type %r" % eval_type
                )
            answer_field = str(answer_field)
        else:  # regex
            if pattern is None or not str(pattern):
                raise ConfigError("task.evaluation.pattern is required for type 'regex'")
            answer_field = str(answer_field) if answer_field is not None else None

        if pattern is not None:
            pattern = to_text(pattern)
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError("task.evaluation.pattern is not a valid regex: %s" % exc)

        if extract is not None:
            extract = str(extract).strip()
            if extract not in EXTRACT_METHODS:
                raise ConfigError(
                    "task.evaluation.extract must be one of %s, got %r"
                    % (", ".join(EXTRACT_METHODS), extract)
                )

        cfg.evaluation = Evaluation(eval_type, answer_field, extract, pattern)

    if cfg.scheme == "rejection" and cfg.evaluation is None:
        raise ConfigError("task.evaluation is required for scheme 'rejection'")

    output_field = task.get("output_field")
    if output_field is None or not str(output_field).strip():
        raise ConfigError("task.output_field is required")
    cfg.output_field = str(output_field)

    if args.concurrency is not None:
        cfg.concurrency = _as_positive_int(args.concurrency, "--concurrency")
    else:
        # Enough in-flight requests to keep a server with `rpm` capacity busy
        # even when individual requests sit in its queue for a while.
        cfg.concurrency = min(max(cfg.rpm, 8), 512)

    return cfg


def load_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise ConfigError("input file not found: %s" % path)
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ConfigError(
                        "input line %d is not valid JSON: %s" % (lineno + 1, exc)
                    )
                if not isinstance(obj, dict):
                    raise ConfigError(
                        "input line %d must be a JSON object" % (lineno + 1)
                    )
                rows.append(obj)
    except OSError as exc:
        raise ConfigError("could not read input %s: %s" % (path, exc))
    return rows


def validate_rows(cfg: TaskConfig, rows: List[Dict[str, Any]]) -> None:
    """Fail fast (exit 1) before any API call if a row cannot be used."""
    fields = cfg.prompt_fields()
    answer_field = (
        cfg.evaluation.answer_field
        if cfg.evaluation is not None and cfg.evaluation.answer_field
        else None
    )
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(
                    "row %d: missing field %r referenced by prompt template"
                    % (index, field)
                )
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                "row %d: missing field %r required by task.evaluation.answer_field"
                % (index, answer_field)
            )


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #


class Stats:
    def __init__(self) -> None:
        self.api_calls = 0
        self.first_start: Optional[float] = None
        self.last_end: Optional[float] = None

    def mark(self, start: float, end: float) -> None:
        if self.first_start is None or start < self.first_start:
            self.first_start = start
        if self.last_end is None or end > self.last_end:
            self.last_end = end

    @property
    def elapsed(self) -> float:
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


class CallResult:
    def __init__(
        self,
        ok: bool,
        content: str = "",
        meta: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        self.ok = ok
        self.content = content
        self.meta = meta or {}
        self.error = error


async def call_api(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    messages: List[Dict[str, str]],
    stats: Stats,
) -> CallResult:
    """One logical attempt: up to MAX_HTTP_TRIES requests, retrying 5xx."""
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    last_error = "request failed"
    last_latency_ms = 0

    for attempt_index in range(MAX_HTTP_TRIES):
        start = time.monotonic()
        stats.api_calls += 1
        retryable = False
        try:
            async with session.post(cfg.endpoint, json=payload) as response:
                body = await response.read()
                end = time.monotonic()
                stats.mark(start, end)
                last_latency_ms = int(round((end - start) * 1000))
                status = response.status
                if status >= 500:
                    last_error = "HTTP %d" % status
                    retryable = True
                elif status >= 400:
                    return CallResult(
                        False,
                        meta=_error_meta(cfg, last_latency_ms, "HTTP %d" % status),
                        error="HTTP %d" % status,
                    )
                else:
                    try:
                        data = json.loads(body.decode("utf-8"))
                        choice = data["choices"][0]
                        content = choice.get("message", {}).get("content")
                        if content is None:
                            content = ""
                        usage = data.get("usage") or {}
                        meta = {
                            "model": cfg.model,
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(
                                usage.get("completion_tokens") or 0
                            ),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                            "latency_ms": last_latency_ms,
                            "finish_reason": choice.get("finish_reason"),
                        }
                        return CallResult(True, content=str(content), meta=meta)
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                        message = "malformed API response: %s" % exc
                        return CallResult(
                            False,
                            meta=_error_meta(cfg, last_latency_ms, message),
                            error=message,
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            end = time.monotonic()
            stats.mark(start, end)
            last_latency_ms = int(round((end - start) * 1000))
            last_error = "%s: %s" % (type(exc).__name__, exc) if str(exc) else type(exc).__name__
            retryable = True

        if not retryable:
            break
        if attempt_index < MAX_HTTP_TRIES - 1:
            await asyncio.sleep(min(0.2 * (2 ** attempt_index), 2.0))

    return CallResult(
        False, meta=_error_meta(cfg, last_latency_ms, last_error), error=last_error
    )


def _error_meta(cfg: TaskConfig, latency_ms: int, error: str) -> Dict[str, Any]:
    return {
        "model": cfg.model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": latency_ms,
        "finish_reason": None,
        "error": error,
    }


# --------------------------------------------------------------------------- #
# Row processing
# --------------------------------------------------------------------------- #


def build_messages(cfg: TaskConfig, row: Dict[str, Any], index: int) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if cfg.system_template is not None:
        messages.append(
            {"role": "system", "content": render_template(cfg.system_template, row, index)}
        )
    if cfg.user_template is not None:
        messages.append(
            {"role": "user", "content": render_template(cfg.user_template, row, index)}
        )
    return messages


async def process_row(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    messages = build_messages(cfg, row, index)
    metas: List[Dict[str, Any]] = []
    attempts = 0
    content: Optional[str] = None
    extracted: Optional[str] = None
    passed: Optional[bool] = None

    for _ in range(cfg.max_attempts):
        attempts += 1
        call = await call_api(session, cfg, messages, stats)
        metas.append(call.meta)
        if not call.ok:
            content = None
            extracted = None
            passed = None if cfg.evaluation is None else False
            break

        if cfg.evaluation is None:
            content = call.content
            extracted = None
            passed = None
            break

        attempt_passed, attempt_extracted = cfg.evaluation.evaluate(call.content, row)
        if attempt_passed:
            content = call.content
            extracted = attempt_extracted
            passed = True
            break

        # Failed evaluation: keep the response for non-rejection schemes.
        if cfg.scheme != "rejection":
            content = call.content
            extracted = attempt_extracted
            passed = False
            break

        content = None
        extracted = None
        passed = False

    output = None if content is None else {cfg.output_field: content}
    if output is None:
        extracted = None

    return {
        "input": row,
        "output": output,
        "result": {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": attempts,
        },
        "meta": metas[0] if len(metas) == 1 else metas,
    }


async def run_rows(cfg: TaskConfig, rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Stats]:
    stats = Stats()
    results: List[Optional[Dict[str, Any]]] = [None] * len(rows)
    if not rows:
        return [], stats

    queue: "asyncio.Queue[int]" = asyncio.Queue()
    for index in range(len(rows)):  # dispatched in input order
        queue.put_nowait(index)

    worker_count = max(1, min(cfg.concurrency, len(rows)))
    connector = aiohttp.TCPConnector(limit=worker_count, limit_per_host=worker_count)
    timeout = aiohttp.ClientTimeout(total=cfg.timeout, connect=60, sock_connect=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:

        async def worker() -> None:
            while True:
                try:
                    index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                results[index] = await process_row(session, cfg, rows[index], index, stats)

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    return [r for r in results if r is not None], stats


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def write_results(path: str, results: List[Dict[str, Any]]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")


def build_summary(results: List[Dict[str, Any]], stats: Stats) -> Dict[str, Any]:
    passed = 0
    failed = 0
    prompt_tokens = 0
    completion_tokens = 0

    for result in results:
        outcome = result["result"]["passed"]
        has_output = result["output"] is not None
        if outcome is True or (outcome is None and has_output):
            passed += 1
        if outcome is False or not has_output:
            failed += 1

        meta = result["meta"]
        metas = meta if isinstance(meta, list) else [meta]
        for entry in metas:
            if isinstance(entry, dict):
                prompt_tokens += int(entry.get("prompt_tokens") or 0)
                completion_tokens += int(entry.get("completion_tokens") or 0)

    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

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


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class ArgumentParser(argparse.ArgumentParser):
    """argparse parser that exits 1 (config error) instead of 2 on bad usage."""

    def error(self, message: str) -> "None":  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="rejector.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", default=None)
    run.add_argument("--max-tokens", dest="max_tokens", default=None)
    run.add_argument("--scheme", default=None, choices=list(SCHEMES))
    run.add_argument("--temperature", default=None)
    run.add_argument("--n", default=None)
    run.add_argument("--concurrency", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config, args)
        rows = load_rows(args.input)
        validate_rows(cfg, rows)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    try:
        results, stats = asyncio.run(run_rows(cfg, rows))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    try:
        write_results(args.output, results)
    except OSError as exc:
        sys.stderr.write("error: could not write output %s: %s\n" % (args.output, exc))
        return EXIT_ERROR

    sys.stdout.write(json.dumps(build_summary(results, stats)) + "\n")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_ERROR)
