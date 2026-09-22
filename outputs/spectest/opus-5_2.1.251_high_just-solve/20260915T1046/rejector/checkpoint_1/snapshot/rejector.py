#!/usr/bin/env python3
"""rejector - run a YAML-configured generation task against an OpenAI-compatible API.

Usage:
    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import string
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

MAX_RETRIES = 3  # retries after the initial attempt, for HTTP 5xx / transport errors
SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")


class ConfigError(Exception):
    """Configuration or input problem: reported on stderr, exit code 1."""


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass
class Evaluation:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    pattern: str | None = None
    regex: re.Pattern[str] | None = None


@dataclass
class Config:
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
    evaluation: Evaluation | None = None


def _require_mapping(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"config: '{what}' must be a mapping")
    return value


def _as_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"config: '{what}' must be an integer")
    try:
        ivalue = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"config: '{what}' must be an integer, got {value!r}") from None
    return ivalue


def _as_float(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"config: '{what}' must be a number")
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"config: '{what}' must be a number, got {value!r}") from None


def template_fields(template: str, what: str) -> list[str]:
    """Field names referenced by {placeholders} in a template."""
    fields: list[str] = []
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ConfigError(f"config: invalid placeholder syntax in {what}: {exc}") from None
    for _literal, name, _spec, _conv in parsed:
        if name is None:
            continue
        if name == "":
            raise ConfigError(f"config: positional placeholder '{{}}' not supported in {what}")
        root = name.split(".")[0].split("[")[0]
        if not root:
            raise ConfigError(f"config: invalid placeholder '{{{name}}}' in {what}")
        if root not in fields:
            fields.append(root)
    return fields


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML config {path}: {exc}") from None
    if raw is None:
        raise ConfigError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigError("config: top level must be a mapping with a 'task' key")
    return raw


def build_config(raw: dict, args: argparse.Namespace) -> Config:
    if "task" not in raw:
        raise ConfigError("config: missing required section 'task'")
    task = _require_mapping(raw["task"], "task")

    name = str(task.get("name", "task"))

    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if api_url is None or str(api_url).strip() == "":
        raise ConfigError("config: 'task.api_url' is required (or pass --api-url)")
    api_url = str(api_url).strip().rstrip("/")

    model = args.model if args.model is not None else task.get("model")
    if model is None or str(model).strip() == "":
        raise ConfigError("config: 'task.model' is required (or pass --model)")
    model = str(model)

    rpm_raw = args.rpm if args.rpm is not None else task.get("rpm", 60)
    rpm = _as_int(rpm_raw, "task.rpm")
    if rpm <= 0:
        raise ConfigError(f"config: 'task.rpm' must be > 0, got {rpm}")

    if "prompt" not in task:
        raise ConfigError("config: missing required section 'task.prompt'")
    prompt = _require_mapping(task["prompt"], "task.prompt")
    if "user" not in prompt or prompt["user"] is None:
        raise ConfigError("config: 'task.prompt.user' is required")
    user_template = str(prompt["user"])
    system_template = None if prompt.get("system") is None else str(prompt["system"])

    generation = _require_mapping(task.get("generation", {}) or {}, "task.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    scheme = str(scheme).strip()
    if scheme not in SCHEMES:
        raise ConfigError(
            f"config: 'task.generation.scheme' must be one of {', '.join(SCHEMES)}, got {scheme!r}"
        )

    if args.temperature is not None:
        temperature = float(args.temperature)
    elif generation.get("temperature") is not None:
        temperature = _as_float(generation["temperature"], "task.generation.temperature")
    else:
        temperature = 0.0

    max_tokens_raw = (
        args.max_tokens if args.max_tokens is not None else generation.get("max_tokens", 512)
    )
    max_tokens = _as_int(max_tokens_raw, "task.generation.max_tokens")
    if max_tokens <= 0:
        raise ConfigError(f"config: 'task.generation.max_tokens' must be > 0, got {max_tokens}")

    n_raw = args.n if args.n is not None else generation.get("n", 1)
    n = _as_int(n_raw, "task.generation.n")
    if n <= 0:
        raise ConfigError(f"config: 'task.generation.n' must be > 0, got {n}")

    if scheme == "greedy":
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError(
                "config: scheme 'sample' requires 'task.generation.temperature' > 0, "
                f"got {temperature}"
            )
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError(
                "config: scheme 'rejection' requires 'task.generation.temperature' > 0, "
                f"got {temperature}"
            )

    evaluation = build_evaluation(task.get("evaluation"), scheme)

    output_field_raw = task.get("output_field", "output")
    if output_field_raw is None or str(output_field_raw).strip() == "":
        raise ConfigError("config: 'task.output_field' must be a non-empty string")
    output_field = str(output_field_raw)

    # validates placeholder syntax up front
    template_fields(user_template, "task.prompt.user")
    if system_template is not None:
        template_fields(system_template, "task.prompt.system")

    return Config(
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


def build_evaluation(raw: Any, scheme: str) -> Evaluation | None:
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("config: 'task.evaluation' is required for scheme 'rejection'")
        return None

    section = _require_mapping(raw, "task.evaluation")
    eval_type = section.get("type")
    if eval_type is None:
        raise ConfigError("config: 'task.evaluation.type' is required")
    eval_type = str(eval_type).strip()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            f"config: 'task.evaluation.type' must be one of {', '.join(EVAL_TYPES)}, "
            f"got {eval_type!r}"
        )

    answer_field = section.get("answer_field")
    if answer_field is not None:
        answer_field = str(answer_field)

    extract = section.get("extract", "full")
    extract = "full" if extract is None else str(extract).strip()
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"config: 'task.evaluation.extract' must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got {extract!r}"
        )

    pattern = section.get("pattern")
    compiled = None

    if eval_type in ("exact_match", "contains"):
        if not answer_field:
            raise ConfigError(
                f"config: evaluation type '{eval_type}' requires 'task.evaluation.answer_field'"
            )
    else:  # regex
        if pattern is None or str(pattern) == "":
            raise ConfigError("config: evaluation type 'regex' requires 'task.evaluation.pattern'")
        pattern = str(pattern)
        try:
            compiled = re.compile(pattern, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise ConfigError(f"config: invalid 'task.evaluation.pattern': {exc}") from None

    return Evaluation(
        type=eval_type,
        answer_field=answer_field,
        extract=extract,
        pattern=pattern if isinstance(pattern, str) else None,
        regex=compiled,
    )


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------


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
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"input: row {len(rows)} (line {lineno}) is not valid JSON: {exc}")
        if not isinstance(row, dict):
            raise ConfigError(f"input: row {len(rows)} (line {lineno}) is not a JSON object")
        rows.append(row)
    return rows


def render_template(template: str, row: dict, index: int, what: str) -> str:
    try:
        return template.format(**row)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "?"
        raise ConfigError(
            f"input: row {index} is missing field {missing!r} referenced by {what}"
        ) from None
    except (IndexError, ValueError) as exc:
        raise ConfigError(f"config: could not render {what}: {exc}") from None


def prepare_prompts(config: Config, rows: list[dict]) -> list[list[dict]]:
    """Render every prompt up front so template/field errors surface before any request."""
    messages_per_row: list[list[dict]] = []
    answer_field = config.evaluation.answer_field if config.evaluation else None
    for index, row in enumerate(rows):
        messages: list[dict] = []
        if config.system_template is not None:
            messages.append(
                {
                    "role": "system",
                    "content": render_template(
                        config.system_template, row, index, "prompt.system"
                    ),
                }
            )
        messages.append(
            {
                "role": "user",
                "content": render_template(config.user_template, row, index, "prompt.user"),
            }
        )
        if answer_field and answer_field not in row:
            raise ConfigError(
                f"input: row {index} is missing field {answer_field!r} "
                f"required by evaluation.answer_field"
            )
        messages_per_row.append(messages)
    return messages_per_row


# --------------------------------------------------------------------------
# extraction + evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d*\.\d+|-?\d+")


def extract_value(text: str, method: str) -> str | None:
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return ""
    if method == "last_number":
        matches = _NUMBER_RE.findall(text)
        if not matches:
            return None
        return matches[-1].replace(",", "")
    return text.strip()


def _normalize(value: str) -> str:
    value = value.strip()
    value = value.replace(",", "").replace("$", "").replace("%", "")
    value = value.strip().rstrip(".")
    return value.strip()


def values_match(extracted: str | None, expected: Any) -> bool:
    if extracted is None or expected is None:
        return False
    expected_str = expected if isinstance(expected, str) else str(expected)
    if extracted.strip() == expected_str.strip():
        return True
    left, right = _normalize(extracted), _normalize(expected_str)
    if left == right:
        return True
    try:
        lnum, rnum = float(left), float(right)
    except (TypeError, ValueError):
        return False
    if math.isnan(lnum) or math.isnan(rnum):
        return False
    return math.isclose(lnum, rnum, rel_tol=1e-9, abs_tol=1e-9)


def evaluate(config: Config, text: str, row: dict) -> tuple[bool | None, str | None]:
    """Return (passed, extracted_answer) for a response."""
    ev = config.evaluation
    if ev is None:
        return None, None

    if ev.type == "regex":
        match = ev.regex.search(text) if ev.regex is not None else None
        if match is not None:
            extracted = match.group(1) if match.groups() else match.group(0)
            return True, extracted
        return False, extract_value(text, ev.extract)

    extracted = extract_value(text, ev.extract)
    expected = row.get(ev.answer_field) if ev.answer_field else None

    if ev.type == "contains":
        expected_str = "" if expected is None else str(expected)
        return (expected_str in text), extracted

    return values_match(extracted, expected), extracted


# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------


@dataclass
class CallResult:
    ok: bool
    content: str | None
    meta: dict
    api_calls: int
    error: str | None = None


class Counter:
    def __init__(self) -> None:
        self.api_calls = 0
        self.first_request_at: float | None = None
        self.last_response_at: float | None = None

    def mark_request(self, at: float) -> None:
        self.api_calls += 1
        if self.first_request_at is None or at < self.first_request_at:
            self.first_request_at = at

    def mark_response(self, at: float) -> None:
        if self.last_response_at is None or at > self.last_response_at:
            self.last_response_at = at


def _empty_meta(model: str, latency_ms: int) -> dict:
    return {
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": latency_ms,
        "finish_reason": None,
    }


async def call_api(
    client: httpx.AsyncClient,
    config: Config,
    messages: list[dict],
    temperature: float,
    counter: Counter,
) -> CallResult:
    """One logical API call, retrying HTTP 5xx / transport failures."""
    url = f"{config.api_url}/v1/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": config.max_tokens,
    }

    calls = 0
    last_error = "request failed"
    total_latency_ms = 0

    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        counter.mark_request(started)
        calls += 1
        try:
            response = await client.post(url, json=payload)
            elapsed = time.perf_counter() - started
            counter.mark_response(time.perf_counter())
            latency_ms = int(round(elapsed * 1000))
            total_latency_ms += latency_ms

            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
            elif response.status_code >= 400:
                return CallResult(
                    False,
                    None,
                    _empty_meta(config.model, latency_ms),
                    calls,
                    f"HTTP {response.status_code}",
                )
            else:
                try:
                    body = response.json()
                except ValueError as exc:
                    return CallResult(
                        False,
                        None,
                        _empty_meta(config.model, latency_ms),
                        calls,
                        f"invalid JSON response: {exc}",
                    )
                parsed = parse_completion(body, config.model, latency_ms)
                if parsed is None:
                    return CallResult(
                        False,
                        None,
                        _empty_meta(config.model, latency_ms),
                        calls,
                        "malformed completion response",
                    )
                content, meta = parsed
                return CallResult(True, content, meta, calls)
        except (httpx.HTTPError, OSError) as exc:
            elapsed = time.perf_counter() - started
            counter.mark_response(time.perf_counter())
            total_latency_ms += int(round(elapsed * 1000))
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < MAX_RETRIES:
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))

    return CallResult(False, None, _empty_meta(config.model, total_latency_ms), calls, last_error)


def parse_completion(body: Any, model: str, latency_ms: int) -> tuple[str, dict] | None:
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    message = choice.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = choice.get("text")
    if content is None:
        return None

    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    def _tok(key: str) -> int:
        value = usage.get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    meta = {
        "model": body.get("model") or model,
        "prompt_tokens": _tok("prompt_tokens"),
        "completion_tokens": _tok("completion_tokens"),
        "total_tokens": _tok("total_tokens"),
        "latency_ms": latency_ms,
        "finish_reason": choice.get("finish_reason"),
    }
    return str(content), meta


# --------------------------------------------------------------------------
# row processing
# --------------------------------------------------------------------------


async def process_row(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    messages: list[dict],
    counter: Counter,
) -> dict:
    metas: list[dict] = []
    attempts = 0
    passed: bool | None = None
    extracted: str | None = None
    content: str | None = None

    max_attempts = config.n if config.scheme == "rejection" else 1

    while attempts < max_attempts:
        attempts += 1
        result = await call_api(client, config, messages, config.temperature, counter)
        metas.append(result.meta)
        if not result.ok:
            content = None
            passed = False if config.evaluation is not None else None
            extracted = None
            break

        passed, extracted = evaluate(config, result.content, row)
        content = result.content
        if config.scheme != "rejection" or passed:
            break
        # rejection: this attempt failed evaluation, drop it and try again
        content = None
        extracted = None

    if content is None and config.scheme == "rejection":
        passed = False
        extracted = None

    output = None if content is None else {config.output_field: content}
    meta_out: Any = metas[0] if len(metas) == 1 else metas
    if not metas:
        meta_out = None

    return {
        "input": row,
        "output": output,
        "result": {
            "passed": passed,
            "extracted_answer": extracted if output is not None else None,
            "attempts": attempts,
        },
        "meta": meta_out,
    }


def choose_concurrency(config: Config, row_count: int) -> int:
    if row_count <= 0:
        return 1
    limit = max(8, min(config.rpm, 256))
    return max(1, min(limit, row_count))


async def run_all(config: Config, rows: list[dict], prompts: list[list[dict]]) -> tuple[list[dict], Counter]:
    counter = Counter()
    results: list[dict | None] = [None] * len(rows)
    if not rows:
        return [], counter

    concurrency = choose_concurrency(config, len(rows))
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(
        max_connections=concurrency + 8, max_keepalive_connections=concurrency + 8
    )
    timeout = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=600.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:

        # Gentle ramp: avoids a thundering herd of simultaneous connects on
        # servers with a small listen backlog, without pacing below capacity.
        ramp = min(0.004, 0.25 / concurrency) if concurrency > 1 else 0.0

        async def worker(index: int) -> None:
            if index < concurrency and ramp:
                await asyncio.sleep(index * ramp)
            async with semaphore:
                results[index] = await process_row(
                    client, config, rows[index], prompts[index], counter
                )

        await asyncio.gather(*(worker(i) for i in range(len(rows))))

    return [r for r in results if r is not None], counter


# --------------------------------------------------------------------------
# summary + main
# --------------------------------------------------------------------------


def build_summary(results: list[dict], counter: Counter) -> dict:
    total = len(results)
    passed = 0
    failed = 0
    prompt_tokens = 0
    completion_tokens = 0

    for record in results:
        metas = record["meta"]
        if isinstance(metas, dict):
            metas = [metas]
        elif metas is None:
            metas = []
        for meta in metas:
            prompt_tokens += meta.get("prompt_tokens") or 0
            completion_tokens += meta.get("completion_tokens") or 0

        row_passed = record["result"]["passed"]
        has_output = record["output"] is not None
        if row_passed is True or (row_passed is None and has_output):
            passed += 1
        else:
            failed += 1

    if counter.first_request_at is not None and counter.last_response_at is not None:
        elapsed = max(0.0, counter.last_response_at - counter.first_request_at)
    else:
        elapsed = 0.0

    throughput = (counter.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_api_calls": counter.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def write_results(path: str, results: list[dict]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for record in results:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write output file {path}: {exc}") from None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D102 - argparse hook
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rejector.py", description="Run generation tasks against an OpenAI-compatible API.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw = load_config(args.config)
        config = build_config(raw, args)
        rows = load_rows(args.input)
        prompts = prepare_prompts(config, rows)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        results, counter = asyncio.run(run_all(config, rows, prompts))
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR

    try:
        write_results(args.output, results)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(json.dumps(build_summary(results, counter)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
