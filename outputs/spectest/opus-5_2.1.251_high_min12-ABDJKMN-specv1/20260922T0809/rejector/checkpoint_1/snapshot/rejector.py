#!/usr/bin/env python3
"""rejector - run a YAML-configured generation task against an OpenAI-compatible
chat completions API and write one JSONL result per input row.

Usage:
    python rejector.py run --config <path> --input <path> --output <path>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

try:
    import aiohttp
except ImportError:  # pragma: no cover - dependency is declared in requirements
    aiohttp = None


EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

MAX_REQUESTS_PER_CALL = 3        # 1 initial attempt + 2 retries
RETRY_BACKOFF_SECONDS = 0.05
MAX_IN_FLIGHT = 256

# `{field}` placeholders; anything else in braces is left alone (AMBIGUITIES T16).
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class UserError(Exception):
    """A configuration or input error: reported on stderr, exit code 1."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class Evaluation:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    pattern: str | None = None


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
    evaluation: Evaluation | None
    output_field: str

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def concurrency(self) -> int:
        # `rpm` is the server's approximate capacity, not a client budget
        # (AMBIGUITIES T14): keep roughly that many requests in flight.
        return max(1, min(int(self.rpm), MAX_IN_FLIGHT))


def _as_mapping(value: Any, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserError(f"config: '{label}' must be a mapping")
    return value


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError(f"config: '{label}' must be a number")
    return float(value)


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise UserError(f"config: '{label}' must be an integer")
    return int(value)


def load_config_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise UserError(f"config file not found: {path}")
    except OSError as exc:
        raise UserError(f"could not read config file {path}: {exc}")
    except yaml.YAMLError as exc:
        raise UserError(f"could not parse YAML config {path}: {exc}")
    if raw is None:
        raise UserError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise UserError("config: top level must be a mapping with a 'task' key")
    return raw


def build_config(raw: dict, args: argparse.Namespace) -> TaskConfig:
    """Merge the YAML config with CLI overrides and validate the result."""
    if "task" not in raw:
        raise UserError("config: missing required 'task' section")
    task = _as_mapping(raw["task"], "task")

    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if not api_url or not isinstance(api_url, str):
        raise UserError("config: 'task.api_url' is required")

    model = args.model if args.model is not None else task.get("model")
    if not model or not isinstance(model, str):
        raise UserError("config: 'task.model' is required")

    rpm = args.rpm if args.rpm is not None else task.get("rpm", 60)
    rpm = _as_int(rpm, "task.rpm")
    if rpm < 1:
        raise UserError("config: 'task.rpm' must be >= 1")

    if "prompt" not in task or task.get("prompt") is None:
        raise UserError("config: missing required 'task.prompt' section")
    prompt = _as_mapping(task["prompt"], "task.prompt")
    user_template = prompt.get("user")
    if not isinstance(user_template, str) or not user_template:
        raise UserError("config: 'task.prompt.user' is required")
    system_template = prompt.get("system")
    if system_template is not None and not isinstance(system_template, str):
        raise UserError("config: 'task.prompt.system' must be a string")

    generation = _as_mapping(task.get("generation"), "task.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme",
                                                                        "greedy")
    if scheme not in SCHEMES:
        raise UserError(
            f"config: unknown generation scheme {scheme!r}; "
            f"expected one of {', '.join(SCHEMES)}")

    if args.temperature is not None:
        temperature = float(args.temperature)
    else:
        temperature = _as_number(generation.get("temperature", 0.0),
                                 "task.generation.temperature")

    max_tokens = (args.max_tokens if args.max_tokens is not None
                  else generation.get("max_tokens", 512))
    max_tokens = _as_int(max_tokens, "task.generation.max_tokens")
    if max_tokens < 1:
        raise UserError("config: 'task.generation.max_tokens' must be >= 1")

    n = args.n if args.n is not None else generation.get("n", 1)
    n = _as_int(n, "task.generation.n")
    if n < 1:
        raise UserError("config: 'task.generation.n' must be >= 1")

    if scheme == "greedy":
        # greedy forces temperature to 0.0 (AMBIGUITIES T18).
        temperature = 0.0
    elif temperature <= 0:
        raise UserError(
            f"config: scheme {scheme!r} requires 'temperature' > 0 "
            f"(got {temperature})")

    evaluation = build_evaluation(task.get("evaluation"))
    if scheme == "rejection" and evaluation is None:
        raise UserError("config: 'task.evaluation' is required for "
                        "scheme 'rejection'")

    output_field = task.get("output_field", "output")
    if not isinstance(output_field, str) or not output_field:
        raise UserError("config: 'task.output_field' must be a non-empty string")

    name = task.get("name", "task")

    return TaskConfig(
        name=str(name),
        api_url=api_url,
        model=model,
        rpm=rpm,
        system_template=system_template,
        user_template=user_template,
        scheme=scheme,
        temperature=temperature,
        max_tokens=max_tokens,
        n=n,
        evaluation=evaluation,
        output_field=output_field,
    )


def build_evaluation(raw: Any) -> Evaluation | None:
    if raw is None:
        return None
    section = _as_mapping(raw, "task.evaluation")
    if not section:
        return None
    etype = section.get("type")
    if etype not in EVAL_TYPES:
        raise UserError(
            f"config: unknown evaluation type {etype!r}; "
            f"expected one of {', '.join(EVAL_TYPES)}")

    extract = section.get("extract", "full")
    if extract is None:
        extract = "full"
    if extract not in EXTRACT_METHODS:
        raise UserError(
            f"config: unknown extract method {extract!r}; "
            f"expected one of {', '.join(EXTRACT_METHODS)}")

    answer_field = section.get("answer_field")
    pattern = section.get("pattern")

    if etype in ("exact_match", "contains"):
        if not answer_field or not isinstance(answer_field, str):
            raise UserError(
                f"config: evaluation type {etype!r} requires 'answer_field'")
    if etype == "regex":
        if not pattern or not isinstance(pattern, str):
            raise UserError("config: evaluation type 'regex' requires 'pattern'")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise UserError(f"config: invalid regex 'pattern': {exc}")

    return Evaluation(type=etype, answer_field=answer_field, extract=extract,
                      pattern=pattern)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
def load_rows(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise UserError(f"input file not found: {path}")
    except OSError as exc:
        raise UserError(f"could not read input file {path}: {exc}")

    rows: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserError(f"input line {lineno}: invalid JSON: {exc}")
        if not isinstance(row, dict):
            raise UserError(f"input line {lineno}: expected a JSON object")
        rows.append(row)
    return rows


def template_fields(template: str | None) -> list[str]:
    if not template:
        return []
    seen: list[str] = []
    for name in PLACEHOLDER_RE.findall(template):
        if name not in seen:
            seen.append(name)
    return seen


def render_template(template: str, row: dict) -> str:
    return PLACEHOLDER_RE.sub(lambda m: str(row[m.group(1)]), template)


def validate_rows(cfg: TaskConfig, rows: list[dict]) -> None:
    """Fail before any request is issued (AMBIGUITIES T8)."""
    required = template_fields(cfg.system_template)
    for name in template_fields(cfg.user_template):
        if name not in required:
            required.append(name)

    answer_field = cfg.evaluation.answer_field if cfg.evaluation else None

    for index, row in enumerate(rows):
        for name in required:
            if name not in row:
                raise UserError(
                    f"input row {index}: missing field {name!r} referenced by "
                    f"the prompt template")
        if answer_field and answer_field not in row:
            raise UserError(
                f"input row {index}: missing field {answer_field!r} required by "
                f"the configured evaluation")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def extract_answer(text: str, method: str) -> str | None:
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
        matches = NUMBER_RE.findall(text)
        return matches[-1] if matches else None
    raise UserError(f"unknown extract method {method!r}")


def evaluate(cfg: TaskConfig, row: dict, text: str) -> tuple[bool, str | None]:
    """Return (passed, extracted_answer) for a response body."""
    evaluation = cfg.evaluation
    assert evaluation is not None
    extracted = extract_answer(text, evaluation.extract)

    if evaluation.type == "exact_match":
        expected = str(row.get(evaluation.answer_field, "")).strip()
        passed = extracted is not None and extracted.strip() == expected
    elif evaluation.type == "contains":
        expected = str(row.get(evaluation.answer_field, ""))
        passed = expected in text
    elif evaluation.type == "regex":
        passed = re.search(evaluation.pattern, text) is not None
    else:  # pragma: no cover - validated at config load
        raise UserError(f"unknown evaluation type {evaluation.type!r}")

    return passed, extracted


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    total_api_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    first_request: float | None = None
    last_response: float | None = None

    def mark_request(self, when: float) -> None:
        if self.first_request is None or when < self.first_request:
            self.first_request = when

    def mark_response(self, when: float) -> None:
        if self.last_response is None or when > self.last_response:
            self.last_response = when

    @property
    def elapsed(self) -> float:
        if self.first_request is None or self.last_response is None:
            return 0.0
        return max(0.0, self.last_response - self.first_request)


@dataclass
class Attempt:
    """One completed API call."""
    text: str
    meta: dict


@dataclass
class RowOutcome:
    output: Any
    passed: bool | None
    extracted: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)


class ApiClient:
    def __init__(self, session, cfg: TaskConfig, stats: Stats,
                 semaphore: asyncio.Semaphore):
        self.session = session
        self.cfg = cfg
        self.stats = stats
        self.semaphore = semaphore

    def build_payload(self, row: dict) -> dict:
        messages = []
        if self.cfg.system_template is not None:
            messages.append({"role": "system",
                             "content": render_template(self.cfg.system_template,
                                                        row)})
        messages.append({"role": "user",
                         "content": render_template(self.cfg.user_template, row)})
        return {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }

    async def complete(self, payload: dict) -> Attempt | None:
        """One logical attempt: up to MAX_REQUESTS_PER_CALL HTTP requests."""
        for request_index in range(MAX_REQUESTS_PER_CALL):
            async with self.semaphore:
                started = time.monotonic()
                self.stats.total_api_calls += 1
                self.stats.mark_request(started)
                try:
                    async with self.session.post(self.cfg.endpoint,
                                                 json=payload) as response:
                        status = response.status
                        body = await response.read()
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    # Transport failures are retried like a 5xx (T9).
                    self.stats.mark_response(time.monotonic())
                    status, body = None, b""
                finished = time.monotonic()
                self.stats.mark_response(finished)

            if status is not None and 200 <= status < 300:
                attempt = self._parse(body, finished - started)
                if attempt is not None:
                    self.stats.total_prompt_tokens += attempt.meta["prompt_tokens"] or 0
                    self.stats.total_completion_tokens += (
                        attempt.meta["completion_tokens"] or 0)
                    return attempt
                return None  # unusable 2xx body: not retryable
            if status is not None and not (500 <= status < 600):
                return None  # 4xx and friends are not retried (T9)
            if request_index < MAX_REQUESTS_PER_CALL - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        return None

    def _parse(self, body: bytes, latency: float) -> Attempt | None:
        try:
            data = json.loads(body.decode("utf-8"))
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError,
                UnicodeDecodeError):
            return None
        if text is None:
            text = ""
        usage = data.get("usage") or {}
        meta = {
            "model": self.cfg.model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "latency_ms": int(round(latency * 1000)),
            "finish_reason": choice.get("finish_reason"),
        }
        return Attempt(text=str(text), meta=meta)


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------
async def process_row(client: ApiClient, row: dict) -> RowOutcome:
    cfg = client.cfg
    payload = client.build_payload(row)

    if cfg.scheme == "rejection":
        return await process_rejection(client, row, payload)

    attempt = await client.complete(payload)
    if attempt is None:
        # Retries exhausted (or a non-retryable error): the row failed.
        return RowOutcome(output=None,
                          passed=False if cfg.evaluation else None,
                          extracted=None, attempts=1, metas=[])

    if cfg.evaluation is None:
        return RowOutcome(output=attempt.text, passed=None, extracted=None,
                          attempts=1, metas=[attempt.meta])

    passed, extracted = evaluate(cfg, row, attempt.text)
    return RowOutcome(output=attempt.text, passed=passed, extracted=extracted,
                      attempts=1, metas=[attempt.meta])


async def process_rejection(client: ApiClient, row: dict,
                            payload: dict) -> RowOutcome:
    cfg = client.cfg
    metas: list[dict] = []
    for _ in range(cfg.n):
        attempt = await client.complete(payload)
        if attempt is None:
            # A dead attempt fails the whole row (AMBIGUITIES T7).
            break
        metas.append(attempt.meta)
        passed, extracted = evaluate(cfg, row, attempt.text)
        if passed:
            return RowOutcome(output=attempt.text, passed=True,
                              extracted=extracted, attempts=len(metas),
                              metas=metas)
    return RowOutcome(output=None, passed=False, extracted=None,
                      attempts=max(1, len(metas)), metas=metas)


def render_row(cfg: TaskConfig, row: dict, outcome: RowOutcome) -> dict:
    if outcome.output is None:
        output = None
    else:
        output = {cfg.output_field: outcome.output}

    if len(outcome.metas) == 0:
        meta: Any = None                 # no completed API call (T1)
    elif len(outcome.metas) == 1:
        meta = outcome.metas[0]          # one-attempt row (T2)
    else:
        meta = outcome.metas

    return {
        "input": row,
        "output": output,
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted,
            "attempts": outcome.attempts,
        },
        "meta": meta,
    }


async def run_rows(cfg: TaskConfig, rows: list[dict]) -> tuple[list[dict], Stats]:
    stats = Stats()
    if not rows:
        return [], stats

    semaphore = asyncio.Semaphore(cfg.concurrency)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600)
    connector = aiohttp.TCPConnector(limit=cfg.concurrency + 8)
    async with aiohttp.ClientSession(timeout=timeout,
                                     connector=connector) as session:
        client = ApiClient(session, cfg, stats, semaphore)
        # Tasks are created in row order and the semaphore hands out slots
        # FIFO, so requests go out in input order (AMBIGUITIES T15).
        tasks = [asyncio.ensure_future(process_row(client, row)) for row in rows]
        outcomes = await asyncio.gather(*tasks)

    return [render_row(cfg, row, outcome)
            for row, outcome in zip(rows, outcomes)], stats


def build_summary(rows: list[dict], stats: Stats) -> dict:
    passed = 0
    failed = 0
    for row in rows:
        verdict = row["result"]["passed"]
        if verdict is True:
            passed += 1
        elif verdict is False or row["output"] is None:
            failed += 1
        else:
            # No evaluation configured: a successful API row counts as passed.
            passed += 1

    elapsed = stats.elapsed
    throughput = (stats.total_api_calls / elapsed * 60) if elapsed > 0 else 0.0
    return {
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.total_prompt_tokens,
        "total_completion_tokens": stats.total_completion_tokens,
        "total_api_calls": stats.total_api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def write_output(path: str, rows: list[dict]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise UserError(f"could not write output file {path}: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class Parser(argparse.ArgumentParser):
    """argparse, but usage errors exit 1 - the spec documents only 0 and 1."""

    def error(self, message: str):  # noqa: D102
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="rejector.py",
        description="Run a YAML-configured generation task against an "
                    "OpenAI-compatible chat completions API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a task over a JSONL input file")
    run.set_defaults(command="run")
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


def command_run(args: argparse.Namespace) -> int:
    if aiohttp is None:  # pragma: no cover
        raise UserError("missing dependency 'aiohttp'; "
                        "install it with: pip install -r requirements.txt")

    cfg = build_config(load_config_file(args.config), args)
    rows = load_rows(args.input)
    validate_rows(cfg, rows)

    result_rows, stats = asyncio.run(run_rows(cfg, rows))
    write_output(args.output, result_rows)

    summary = build_summary(result_rows, stats)
    print(json.dumps(summary))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return command_run(args)
        parser.error(f"unknown command {args.command!r}")
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
