#!/usr/bin/env python3
"""rejector.py - batch prompting CLI for OpenAI-compatible chat completion APIs.

Reads a YAML task config and a JSONL input file, renders prompts for every row,
issues chat-completion requests concurrently (dispatched in input order),
optionally evaluates each response, and writes one JSONL result per input row.

Supported generation schemes: greedy, sample, rejection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

MAX_HTTP_ATTEMPTS = 3  # total requests per logical attempt: 1 try + 2 retries
RETRY_BACKOFF_SECONDS = (0.25, 0.5)
DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_OUTPUT_FIELD = "output"
MAX_CONCURRENCY = 512
MIN_CONCURRENCY = 8
RAMP_BUDGET_SECONDS = 0.25
MAX_STAGGER_SECONDS = 0.005


class ConfigError(Exception):
    """Configuration or input problem; reported on stderr with exit code 1."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass
class EvaluationConfig:
    type: str
    answer_field: str | None = None
    pattern: str | None = None
    extract: str | None = None  # as configured (may be None)
    compiled: re.Pattern[str] | None = None

    @property
    def extract_method(self) -> str:
        return self.extract or "full"


@dataclass
class TaskConfig:
    name: str
    api_url: str
    model: str
    rpm: int
    system_template: str | None
    user_template: str
    scheme: str
    temperature: float
    max_tokens: int
    n: int
    output_field: str
    evaluation: EvaluationConfig | None = None

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def max_attempts(self) -> int:
        return self.n if self.scheme == "rejection" else 1


def _require_mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _as_str(value: Any, label: str) -> str:
    if value is None:
        raise ConfigError(f"{label} is required")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConfigError(f"{label} must be a string")
    text = str(value).strip()
    if not text:
        raise ConfigError(f"{label} must be a non-empty string")
    return text


def _as_int(value: Any, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{label} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{label} must be an integer, got {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be an integer, got {value!r}") from None
    if number < minimum:
        raise ConfigError(f"{label} must be >= {minimum}, got {number}")
    return number


def _as_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{label} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be a number, got {value!r}") from None


def load_config(path: str, overrides: dict[str, Any]) -> TaskConfig:
    """Load, override-merge and validate the YAML task configuration."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config file {path}: {exc}") from None

    if raw is None:
        raise ConfigError(f"config file {path} is empty")
    root = _require_mapping(raw, "config")
    if "task" not in root:
        raise ConfigError("config must contain a top-level 'task' section")
    task = _require_mapping(root["task"], "task")

    name = str(task.get("name") or "task")

    api_url = overrides.get("api_url") or task.get("api_url")
    api_url = _as_str(api_url, "task.api_url")
    if not re.match(r"^https?://", api_url):
        raise ConfigError(f"task.api_url must start with http:// or https://, got {api_url!r}")

    model = overrides.get("model") or task.get("model")
    model = _as_str(model, "task.model")

    rpm_value = overrides.get("rpm")
    if rpm_value is None:
        rpm_value = task.get("rpm", DEFAULT_RPM)
    rpm = _as_int(rpm_value, "task.rpm", minimum=1)

    prompt = task.get("prompt")
    if prompt is None:
        raise ConfigError("task.prompt is required")
    prompt = _require_mapping(prompt, "task.prompt")
    if "user" not in prompt or prompt.get("user") is None:
        raise ConfigError("task.prompt.user is required")
    user_template = prompt["user"]
    if not isinstance(user_template, str):
        raise ConfigError("task.prompt.user must be a string")
    system_template = prompt.get("system")
    if system_template is not None and not isinstance(system_template, str):
        raise ConfigError("task.prompt.system must be a string")

    generation = task.get("generation") or {}
    generation = _require_mapping(generation, "task.generation")

    scheme = overrides.get("scheme") or generation.get("scheme") or "greedy"
    scheme = str(scheme).strip().lower()
    if scheme not in SCHEMES:
        raise ConfigError(
            f"task.generation.scheme must be one of {', '.join(SCHEMES)}, got {scheme!r}"
        )

    temperature_value = overrides.get("temperature")
    if temperature_value is None:
        temperature_value = generation.get("temperature", 0.0)
    temperature = _as_float(temperature_value, "task.generation.temperature")
    if temperature < 0:
        raise ConfigError(
            f"task.generation.temperature must be >= 0, got {temperature}"
        )

    max_tokens_value = overrides.get("max_tokens")
    if max_tokens_value is None:
        max_tokens_value = generation.get("max_tokens", DEFAULT_MAX_TOKENS)
    max_tokens = _as_int(max_tokens_value, "task.generation.max_tokens", minimum=1)

    n_value = overrides.get("n")
    if n_value is None:
        n_value = generation.get("n", 1)
    n = _as_int(n_value, "task.generation.n", minimum=1)

    output_field = task.get("output_field", DEFAULT_OUTPUT_FIELD)
    output_field = _as_str(output_field, "task.output_field")

    evaluation = parse_evaluation(task.get("evaluation"))

    # Scheme-specific rules.
    if scheme == "greedy":
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError(
                "scheme 'sample' requires task.generation.temperature > 0, "
                f"got {temperature}"
            )
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError(
                "scheme 'rejection' requires task.generation.temperature > 0, "
                f"got {temperature}"
            )
        if evaluation is None:
            raise ConfigError("scheme 'rejection' requires a task.evaluation section")

    return TaskConfig(
        name=name,
        api_url=api_url,
        model=model,
        rpm=rpm,
        system_template=system_template,
        user_template=user_template,
        scheme=scheme,
        temperature=temperature,
        max_tokens=max_tokens,
        n=n,
        output_field=output_field,
        evaluation=evaluation,
    )


def parse_evaluation(raw: Any) -> EvaluationConfig | None:
    if raw is None:
        return None
    section = _require_mapping(raw, "task.evaluation")
    eval_type = section.get("type")
    if eval_type is None:
        raise ConfigError("task.evaluation.type is required")
    eval_type = str(eval_type).strip().lower()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            f"task.evaluation.type must be one of {', '.join(EVAL_TYPES)}, "
            f"got {eval_type!r}"
        )

    extract = section.get("extract")
    if extract is not None:
        extract = str(extract).strip().lower()
        if extract not in EXTRACT_METHODS:
            raise ConfigError(
                f"task.evaluation.extract must be one of "
                f"{', '.join(EXTRACT_METHODS)}, got {extract!r}"
            )

    answer_field = section.get("answer_field")
    pattern = section.get("pattern")
    compiled = None

    if eval_type in ("exact_match", "contains"):
        if answer_field is None or str(answer_field).strip() == "":
            raise ConfigError(
                f"task.evaluation.answer_field is required for type '{eval_type}'"
            )
        answer_field = str(answer_field)
    else:  # regex
        if pattern is None or str(pattern) == "":
            raise ConfigError("task.evaluation.pattern is required for type 'regex'")
        pattern = str(pattern)
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"task.evaluation.pattern is not a valid regex: {exc}") from None
        answer_field = str(answer_field) if answer_field is not None else None

    return EvaluationConfig(
        type=eval_type,
        answer_field=answer_field,
        pattern=pattern,
        extract=extract,
        compiled=compiled,
    )


# --------------------------------------------------------------------------
# Input loading and prompt rendering
# --------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_rows(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"input file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read input file {path}: {exc}") from None

    rows: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"invalid JSON on line {lineno} of input file {path}: {exc.msg}"
            ) from None
        if not isinstance(value, dict):
            raise ConfigError(
                f"line {lineno} of input file {path} must be a JSON object"
            )
        rows.append(value)
    return rows


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def render_template(template: str, row: dict, row_index: int) -> str:
    def replace(match: re.Match[str]) -> str:
        field_name = match.group(1)
        if field_name not in row:
            raise ConfigError(
                f"row {row_index}: missing field '{field_name}' "
                f"referenced by prompt template"
            )
        return _stringify(row[field_name])

    return PLACEHOLDER_RE.sub(replace, template)


def build_messages(config: TaskConfig, row: dict, row_index: int) -> list[dict]:
    messages: list[dict] = []
    if config.system_template is not None:
        messages.append(
            {
                "role": "system",
                "content": render_template(config.system_template, row, row_index),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": render_template(config.user_template, row, row_index),
        }
    )
    return messages


def prepare_rows(config: TaskConfig, rows: list[dict]) -> list[list[dict]]:
    """Render every prompt up-front so template/input errors surface before any I/O."""
    answer_field = None
    if config.evaluation is not None and config.evaluation.type in (
        "exact_match",
        "contains",
    ):
        answer_field = config.evaluation.answer_field

    prepared: list[list[dict]] = []
    for index, row in enumerate(rows):
        prepared.append(build_messages(config, row, index))
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                f"row {index}: missing field '{answer_field}' "
                f"required by task.evaluation.answer_field"
            )
    return prepared


# --------------------------------------------------------------------------
# Answer extraction and evaluation
# --------------------------------------------------------------------------

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def extract_answer(text: str, method: str) -> str | None:
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    if method == "last_number":
        matches = NUMBER_RE.findall(text.replace(",", ""))
        return matches[-1] if matches else None
    return text.strip()


def _to_number(text: str) -> float | None:
    try:
        return float(text.replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _normalize(text: str) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed.strip().strip(".").casefold()


def values_match(extracted: str | None, expected: Any) -> bool:
    if extracted is None:
        return False
    left = str(extracted).strip()
    right = _stringify(expected).strip()
    if left == right:
        return True
    left_number = _to_number(left)
    right_number = _to_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return _normalize(left) == _normalize(right)


def evaluate_response(
    evaluation: EvaluationConfig, text: str, row: dict
) -> tuple[bool, str | None]:
    """Return (passed, extracted_answer) for one response."""
    if evaluation.type == "exact_match":
        extracted = extract_answer(text, evaluation.extract_method)
        expected = row.get(evaluation.answer_field)
        return values_match(extracted, expected), extracted

    if evaluation.type == "contains":
        expected = _stringify(row.get(evaluation.answer_field))
        passed = expected in (text or "")
        if evaluation.extract is not None:
            extracted = extract_answer(text, evaluation.extract_method)
        else:
            extracted = expected if passed else None
        return passed, extracted

    # regex
    match = evaluation.compiled.search(text or "")
    if match is None:
        extracted = (
            extract_answer(text, evaluation.extract_method)
            if evaluation.extract is not None
            else None
        )
        return False, extracted
    if evaluation.extract is not None:
        extracted = extract_answer(text, evaluation.extract_method)
    else:
        extracted = match.group(1) if match.groups() else match.group(0)
    return True, extracted


# --------------------------------------------------------------------------
# API calls
# --------------------------------------------------------------------------


@dataclass
class Stats:
    total_api_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    first_request_at: float | None = None
    last_response_at: float | None = None

    def mark_start(self, moment: float) -> None:
        if self.first_request_at is None or moment < self.first_request_at:
            self.first_request_at = moment

    def mark_end(self, moment: float) -> None:
        if self.last_response_at is None or moment > self.last_response_at:
            self.last_response_at = moment


@dataclass
class CallResult:
    ok: bool
    content: str | None = None
    meta: dict = field(default_factory=dict)


def _usage_int(usage: Any, key: str) -> int:
    if isinstance(usage, dict):
        value = usage.get(key)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
    return 0


async def call_api(
    client: httpx.AsyncClient, config: TaskConfig, messages: list[dict], stats: Stats
) -> CallResult:
    """One logical attempt: up to MAX_HTTP_ATTEMPTS HTTP requests on 5xx/transport errors."""
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    last_error = "request failed"
    last_latency = 0

    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        started = time.monotonic()
        stats.total_api_calls += 1
        stats.mark_start(started)
        retryable = False
        try:
            response = await client.post(config.endpoint, json=payload)
            finished = time.monotonic()
            stats.mark_end(finished)
            last_latency = int(round((finished - started) * 1000))

            if response.status_code >= 500:
                retryable = True
                last_error = f"HTTP {response.status_code} from API"
            elif response.status_code >= 400:
                last_error = f"HTTP {response.status_code} from API"
            else:
                try:
                    body = response.json()
                except ValueError:
                    last_error = "API response was not valid JSON"
                    body = None
                if body is not None:
                    parsed = _parse_completion(body)
                    if parsed is None:
                        last_error = "API response did not contain a message choice"
                    else:
                        content, finish_reason, usage = parsed
                        stats.prompt_tokens += _usage_int(usage, "prompt_tokens")
                        stats.completion_tokens += _usage_int(usage, "completion_tokens")
                        return CallResult(
                            ok=True,
                            content=content,
                            meta={
                                "model": config.model,
                                "prompt_tokens": _usage_int(usage, "prompt_tokens"),
                                "completion_tokens": _usage_int(usage, "completion_tokens"),
                                "total_tokens": _usage_int(usage, "total_tokens")
                                or (
                                    _usage_int(usage, "prompt_tokens")
                                    + _usage_int(usage, "completion_tokens")
                                ),
                                "latency_ms": last_latency,
                                "finish_reason": finish_reason,
                            },
                        )
        except httpx.HTTPError as exc:
            finished = time.monotonic()
            stats.mark_end(finished)
            last_latency = int(round((finished - started) * 1000))
            retryable = True
            last_error = f"{type(exc).__name__}: {exc}"

        if not retryable or attempt == MAX_HTTP_ATTEMPTS:
            break
        await asyncio.sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])

    return CallResult(
        ok=False,
        content=None,
        meta={
            "model": config.model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": last_latency,
            "finish_reason": None,
            "error": last_error,
        },
    )


def _parse_completion(body: Any) -> tuple[str, Any, Any] | None:
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    message = choice.get("message")
    content: Any = None
    if isinstance(message, dict):
        content = message.get("content")
    if content is None:
        content = choice.get("text")
    if content is None:
        return None
    return str(content), choice.get("finish_reason"), body.get("usage")


# --------------------------------------------------------------------------
# Row processing
# --------------------------------------------------------------------------


async def process_row(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    messages: list[dict],
    stats: Stats,
) -> dict:
    evaluation = config.evaluation
    metas: list[dict] = []
    attempts = 0
    output_text: str | None = None
    passed: bool | None = None
    extracted: str | None = None

    for _ in range(config.max_attempts):
        attempts += 1
        call = await call_api(client, config, messages, stats)
        metas.append(call.meta)

        if not call.ok:
            # Hard failure after retries: the row fails and we stop here.
            output_text = None
            passed = False if evaluation is not None else None
            extracted = None
            break

        if evaluation is None:
            output_text = call.content
            passed = None
            extracted = None
            break

        attempt_passed, attempt_extracted = evaluate_response(
            evaluation, call.content or "", row
        )
        if config.scheme != "rejection":
            output_text = call.content
            passed = attempt_passed
            extracted = attempt_extracted
            break

        if attempt_passed:
            output_text = call.content
            passed = True
            extracted = attempt_extracted
            break

        # Rejected: discard this candidate and try again (if budget remains).
        output_text = None
        passed = False
        extracted = None

    meta: Any = metas[0] if len(metas) == 1 else metas

    return {
        "input": row,
        "output": None if output_text is None else {config.output_field: output_text},
        "result": {
            "passed": passed,
            "extracted_answer": extracted if output_text is not None else None,
            "attempts": attempts,
        },
        "meta": meta,
    }


def compute_concurrency(config: TaskConfig, row_count: int) -> int:
    if row_count <= 0:
        return 1
    target = max(config.rpm, MIN_CONCURRENCY)
    return max(1, min(target, MAX_CONCURRENCY, row_count))


async def run_rows(
    config: TaskConfig, rows: list[dict], prepared: list[list[dict]]
) -> tuple[list[dict], Stats]:
    stats = Stats()
    results: list[dict | None] = [None] * len(rows)
    if not rows:
        return [], stats

    concurrency = compute_concurrency(config, len(rows))
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(rows)):
        queue.put_nowait(index)

    limits = httpx.Limits(
        max_connections=concurrency + 8,
        max_keepalive_connections=concurrency + 8,
    )
    timeout = httpx.Timeout(connect=30.0, read=900.0, write=120.0, pool=None)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:

        async def worker() -> None:
            while True:
                try:
                    index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    results[index] = await process_row(
                        client, config, rows[index], prepared[index], stats
                    )
                finally:
                    queue.task_done()

        # Ramp workers up one at a time. Each worker takes the next row from the
        # queue, so rows are dispatched in input order; the small stagger keeps
        # simultaneous connection setup from reordering the first requests on
        # the wire. The whole ramp is bounded by RAMP_BUDGET_SECONDS.
        stagger = min(MAX_STAGGER_SECONDS, RAMP_BUDGET_SECONDS / concurrency)
        workers = []
        for slot in range(concurrency):
            workers.append(asyncio.create_task(worker()))
            if slot + 1 < concurrency and not queue.empty():
                await asyncio.sleep(stagger)

        await asyncio.gather(*workers)

    return [result for result in results if result is not None], stats


# --------------------------------------------------------------------------
# Summary and output
# --------------------------------------------------------------------------


def build_summary(results: list[dict], stats: Stats) -> dict:
    total = len(results)
    passed = 0
    failed = 0
    for result in results:
        row_passed = result["result"]["passed"]
        has_output = result["output"] is not None
        if row_passed is True or (row_passed is None and has_output):
            passed += 1
        if row_passed is False or not has_output:
            failed += 1

    if stats.first_request_at is not None and stats.last_response_at is not None:
        elapsed = max(0.0, stats.last_response_at - stats.first_request_at)
    else:
        elapsed = 0.0
    throughput = (stats.total_api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.total_api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def write_results(path: str, results: list[dict]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write output file {path}: {exc}") from None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that exits with code 1 (not 2) on usage errors."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="rejector.py",
        description="Run a YAML-configured prompting task against an "
        "OpenAI-compatible chat completions API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run a task over a JSONL input file")
    run_parser.add_argument("--config", required=True, help="path to the YAML task config")
    run_parser.add_argument("--input", required=True, help="path to the JSONL input file")
    run_parser.add_argument("--output", required=True, help="path to the JSONL output file")
    run_parser.add_argument("--api-url", dest="api_url", default=None)
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument("--rpm", default=None)
    run_parser.add_argument("--max-tokens", dest="max_tokens", default=None)
    run_parser.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run_parser.add_argument("--temperature", default=None)
    run_parser.add_argument("--n", default=None)
    return parser


def collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.api_url is not None:
        overrides["api_url"] = args.api_url
    if args.model is not None:
        overrides["model"] = args.model
    if args.scheme is not None:
        overrides["scheme"] = args.scheme
    if args.rpm is not None:
        overrides["rpm"] = _cli_int(args.rpm, "--rpm")
    if args.max_tokens is not None:
        overrides["max_tokens"] = _cli_int(args.max_tokens, "--max-tokens")
    if args.n is not None:
        overrides["n"] = _cli_int(args.n, "--n")
    if args.temperature is not None:
        overrides["temperature"] = _cli_float(args.temperature, "--temperature")
    return overrides


def _cli_int(value: str, flag: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"{flag} must be an integer, got {value!r}") from None


def _cli_float(value: str, flag: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"{flag} must be a number, got {value!r}") from None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        overrides = collect_overrides(args)
        config = load_config(args.config, overrides)
        rows = load_rows(args.input)
        prepared = prepare_rows(config, rows)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        results, stats = asyncio.run(run_rows(config, rows, prepared))
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR

    try:
        write_results(args.output, results)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(json.dumps(build_summary(results, stats)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
