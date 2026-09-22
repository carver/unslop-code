#!/usr/bin/env python3
"""rejector - run prompts from a JSONL file against an OpenAI-compatible API.

Usage:
    python rejector.py run --config task.yaml --input data.jsonl --output out.jsonl
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

MAX_HTTP_RETRIES = 3          # retries after the initial request (4 calls total)
RETRY_BACKOFF_BASE = 0.05     # seconds; doubled per retry
DEFAULT_CONCURRENCY_CAP = 512


def _bootstrap_venv() -> None:
    """Re-exec inside the project virtualenv when dependencies are missing."""
    if os.environ.get("REJECTOR_NO_BOOTSTRAP"):
        return
    try:
        import yaml  # noqa: F401
        return
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, ".venv", "bin", "python"),
                      os.path.join(here, "venv", "bin", "python")):
        if os.path.exists(candidate) and os.path.realpath(candidate) != os.path.realpath(sys.executable):
            os.environ["REJECTOR_NO_BOOTSTRAP"] = "1"
            try:
                os.execv(candidate, [candidate, os.path.abspath(__file__)] + sys.argv[1:])
            except OSError:
                return


_bootstrap_venv()

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - fallback parser is used instead
    yaml = None


class ConfigError(Exception):
    """Configuration or input problem -> exit code 1."""


# --------------------------------------------------------------------------
# YAML loading
# --------------------------------------------------------------------------

def load_yaml(text: str):
    if yaml is not None:
        return yaml.safe_load(text)
    return _MiniYAML(text).parse()


class _MiniYAML:
    """Very small YAML subset parser, used only when PyYAML is unavailable.

    Supports nested mappings, block sequences, flow sequences of scalars,
    block scalars (| and >) and the usual scalar types.
    """

    def __init__(self, text: str):
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.i = 0

    # -- line helpers -----------------------------------------------------
    def _indent(self, line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _is_skippable(self, line: str) -> bool:
        s = line.strip()
        return not s or s.startswith("#") or s in ("---", "...")

    def _peek(self):
        while self.i < len(self.lines) and self._is_skippable(self.lines[self.i]):
            self.i += 1
        if self.i >= len(self.lines):
            return None, None
        line = self.lines[self.i]
        return self._indent(line), self._strip_comment(line.strip())

    @staticmethod
    def _strip_comment(s: str) -> str:
        out = []
        quote = None
        prev = ""
        for ch in s:
            if quote:
                out.append(ch)
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
                out.append(ch)
            elif ch == "#" and (prev == "" or prev.isspace()):
                break
            else:
                out.append(ch)
            prev = ch
        return "".join(out).rstrip()

    # -- parsing ----------------------------------------------------------
    def parse(self):
        indent, _ = self._peek()
        if indent is None:
            return None
        return self._parse_block(indent)

    def _parse_block(self, indent: int):
        cur, content = self._peek()
        if cur is None or cur < indent:
            return None
        if content == "-" or content.startswith("- "):
            return self._parse_seq(cur)
        return self._parse_map(cur)

    def _parse_seq(self, indent: int):
        items = []
        while True:
            cur, content = self._peek()
            if cur is None or cur < indent or not (content == "-" or content.startswith("- ")):
                return items
            rest = content[1:].strip()
            self.i += 1
            if not rest:
                nxt, _ = self._peek()
                if nxt is not None and nxt > indent:
                    items.append(self._parse_block(nxt))
                else:
                    items.append(None)
            elif re.match(r"^[^\s:]+\s*:(\s|$)", rest) or re.match(r"^(\"[^\"]*\"|'[^']*')\s*:(\s|$)", rest):
                # inline mapping start inside a sequence item
                self.lines[self.i - 1] = " " * (indent + 2) + rest
                self.i -= 1
                items.append(self._parse_map(indent + 2))
            else:
                items.append(self._scalar(rest))

    def _parse_map(self, indent: int):
        result = {}
        while True:
            cur, content = self._peek()
            if cur is None or cur < indent:
                return result
            if cur > indent:
                raise ConfigError("invalid YAML indentation near: %r" % content)
            m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:]+?)\s*:(?:\s+(.*))?$", content)
            if not m:
                raise ConfigError("cannot parse YAML line: %r" % content)
            key = self._scalar(m.group(1))
            rest = (m.group(2) or "").strip()
            self.i += 1
            if rest.startswith("|") or rest.startswith(">"):
                result[key] = self._block_scalar(rest, indent)
            elif rest:
                result[key] = self._scalar(rest)
            else:
                nxt, _ = self._peek()
                if nxt is not None and nxt > indent:
                    result[key] = self._parse_block(nxt)
                else:
                    result[key] = None

    def _block_scalar(self, header: str, indent: int) -> str:
        folded = header[0] == ">"
        chomp = "clip"
        if "-" in header:
            chomp = "strip"
        elif "+" in header:
            chomp = "keep"
        body = []
        block_indent = None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.strip():
                ind = self._indent(line)
                if ind <= indent:
                    break
                if block_indent is None:
                    block_indent = ind
                body.append(line[block_indent:] if len(line) >= block_indent else line.lstrip())
            else:
                body.append("")
            self.i += 1
        while body and not body[-1].strip():
            body.pop()
        if folded:
            out, buf = [], []
            for ln in body:
                if ln.strip():
                    buf.append(ln.strip())
                else:
                    out.append(" ".join(buf))
                    buf = []
                    out.append("")
            if buf:
                out.append(" ".join(buf))
            text = "\n".join(out)
        else:
            text = "\n".join(body)
        if chomp == "strip":
            return text
        return text + "\n" if text else text

    def _scalar(self, s: str):
        s = s.strip()
        if not s:
            return None
        if s[0] == '"' and s[-1] == '"' and len(s) >= 2:
            return self._unescape(s[1:-1])
        if s[0] == "'" and s[-1] == "'" and len(s) >= 2:
            return s[1:-1].replace("''", "'")
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            if not inner:
                return []
            return [self._scalar(p) for p in self._split_flow(inner)]
        if s.startswith("{") and s.endswith("}"):
            inner = s[1:-1].strip()
            out = {}
            if inner:
                for part in self._split_flow(inner):
                    k, _, v = part.partition(":")
                    out[self._scalar(k)] = self._scalar(v)
            return out
        low = s.lower()
        if low in ("null", "~", "none"):
            return None
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s

    @staticmethod
    def _split_flow(s: str):
        parts, buf, quote, depth = [], [], None, 0
        for ch in s:
            if quote:
                buf.append(ch)
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
                buf.append(ch)
            elif ch in "[{":
                depth += 1
                buf.append(ch)
            elif ch in "]}":
                depth -= 1
                buf.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        if buf:
            parts.append("".join(buf).strip())
        return [p for p in parts if p != ""]

    @staticmethod
    def _unescape(s: str) -> str:
        out, i = [], 0
        mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "0": "\0", "/": "/"}
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                out.append(mapping.get(s[i + 1], s[i + 1]))
                i += 2
            else:
                out.append(s[i])
                i += 1
        return "".join(out)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

VALID_SCHEMES = ("greedy", "sample", "rejection")
VALID_EVAL_TYPES = ("exact_match", "contains", "regex")
VALID_EXTRACTS = ("last_number", "last_line", "full")


class Config:
    def __init__(self, data: dict, overrides: dict):
        if data is None:
            raise ConfigError("config file is empty")
        if not isinstance(data, dict):
            raise ConfigError("config root must be a mapping")
        task = data.get("task", data if "task" not in data else None)
        if not isinstance(task, dict):
            raise ConfigError("config must contain a 'task' mapping")
        self.raw = task

        self.name = task.get("name")

        self.api_url = _first(overrides.get("api_url"), task.get("api_url"))
        if not isinstance(self.api_url, str) or not self.api_url.strip():
            raise ConfigError("task.api_url is required (or pass --api-url)")
        self.api_url = self.api_url.strip().rstrip("/")

        self.model = _first(overrides.get("model"), task.get("model"))
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigError("task.model is required (or pass --model)")

        rpm = _first(overrides.get("rpm"), task.get("rpm"), 60)
        if isinstance(rpm, bool) or not isinstance(rpm, (int, float)):
            raise ConfigError("task.rpm must be a number, got %r" % (rpm,))
        if rpm <= 0:
            raise ConfigError("task.rpm must be greater than 0, got %r" % (rpm,))
        self.rpm = float(rpm)

        prompt = task.get("prompt")
        if not isinstance(prompt, dict):
            raise ConfigError("task.prompt is required and must be a mapping")
        self.system_prompt = prompt.get("system")
        self.user_prompt = prompt.get("user")
        if self.system_prompt is not None and not isinstance(self.system_prompt, str):
            raise ConfigError("task.prompt.system must be a string")
        if not isinstance(self.user_prompt, str) or not self.user_prompt:
            raise ConfigError("task.prompt.user is required and must be a string")

        gen = task.get("generation") or {}
        if not isinstance(gen, dict):
            raise ConfigError("task.generation must be a mapping")

        self.scheme = _first(overrides.get("scheme"), gen.get("scheme"), "greedy")
        if self.scheme not in VALID_SCHEMES:
            raise ConfigError(
                "task.generation.scheme must be one of %s, got %r"
                % (", ".join(VALID_SCHEMES), self.scheme))

        temperature = _first(overrides.get("temperature"), gen.get("temperature"), 0.0)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ConfigError("task.generation.temperature must be a number, got %r" % (temperature,))
        self.temperature = float(temperature)

        max_tokens = _first(overrides.get("max_tokens"), gen.get("max_tokens"), 512)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, (int, float)):
            raise ConfigError("task.generation.max_tokens must be an integer, got %r" % (max_tokens,))
        if int(max_tokens) <= 0:
            raise ConfigError("task.generation.max_tokens must be greater than 0")
        self.max_tokens = int(max_tokens)

        n = _first(overrides.get("n"), gen.get("n"), 1)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or int(n) != n:
            raise ConfigError("task.generation.n must be an integer, got %r" % (n,))
        if int(n) < 1:
            raise ConfigError("task.generation.n must be at least 1, got %r" % (n,))
        self.n = int(n)

        if self.scheme == "greedy":
            self.temperature = 0.0
            self.n = 1
        elif self.scheme == "sample":
            if self.temperature <= 0:
                raise ConfigError(
                    "scheme 'sample' requires generation.temperature > 0, got %s" % self.temperature)
            self.n = 1
        else:  # rejection
            if self.temperature <= 0:
                raise ConfigError(
                    "scheme 'rejection' requires generation.temperature > 0, got %s" % self.temperature)

        ev = task.get("evaluation")
        self.evaluation = None
        if ev is not None:
            if not isinstance(ev, dict):
                raise ConfigError("task.evaluation must be a mapping")
            self.evaluation = self._parse_evaluation(ev)
        elif self.scheme == "rejection":
            raise ConfigError("task.evaluation is required for scheme 'rejection'")

        output_field = task.get("output_field", "output")
        if not isinstance(output_field, str) or not output_field:
            raise ConfigError("task.output_field must be a non-empty string")
        self.output_field = output_field

    @staticmethod
    def _parse_evaluation(ev: dict) -> dict:
        etype = ev.get("type")
        if etype not in VALID_EVAL_TYPES:
            raise ConfigError(
                "task.evaluation.type must be one of %s, got %r"
                % (", ".join(VALID_EVAL_TYPES), etype))
        answer_field = ev.get("answer_field")
        pattern = ev.get("pattern")
        extract = ev.get("extract", "full")
        if extract is None:
            extract = "full"
        if extract not in VALID_EXTRACTS:
            raise ConfigError(
                "task.evaluation.extract must be one of %s, got %r"
                % (", ".join(VALID_EXTRACTS), extract))
        if etype in ("exact_match", "contains"):
            if not isinstance(answer_field, str) or not answer_field:
                raise ConfigError("task.evaluation.answer_field is required for type %r" % etype)
        if etype == "regex":
            if not isinstance(pattern, str) or not pattern:
                raise ConfigError("task.evaluation.pattern is required for type 'regex'")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError("task.evaluation.pattern is not a valid regex: %s" % exc)
        return {
            "type": etype,
            "answer_field": answer_field if isinstance(answer_field, str) else None,
            "pattern": pattern,
            "extract": extract,
        }


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


# --------------------------------------------------------------------------
# Prompt templating
# --------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_\-\.]*)\}")


def template_fields(template: str):
    if not template:
        return []
    return [m.group(1) for m in _PLACEHOLDER.finditer(template)]


def render_template(template: str, row: dict) -> str:
    def repl(match):
        key = match.group(1)
        value = row[key]
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(value, ensure_ascii=False)

    return _PLACEHOLDER.sub(repl, template)


# --------------------------------------------------------------------------
# Extraction and evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")


def extract_answer(text: str, method: str):
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


def _to_number(value):
    try:
        return float(str(value).strip().replace(",", "").rstrip("."))
    except (TypeError, ValueError):
        return None


def values_match(extracted, expected) -> bool:
    if extracted is None:
        return False
    a = str(extracted).strip()
    b = ("" if expected is None else str(expected)).strip()
    if a == b:
        return True
    na, nb = _to_number(a), _to_number(b)
    if na is not None and nb is not None:
        return na == nb or math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return False


def evaluate(config: Config, text: str, row: dict):
    """Return (passed, extracted_answer). passed is None when no evaluation."""
    ev = config.evaluation
    if ev is None:
        return None, None
    extracted = extract_answer(text, ev["extract"])
    etype = ev["type"]
    if etype == "exact_match":
        passed = values_match(extracted, row.get(ev["answer_field"]))
    elif etype == "contains":
        expected = row.get(ev["answer_field"])
        expected = "" if expected is None else str(expected)
        passed = expected in (text or "")
    else:  # regex
        passed = re.search(ev["pattern"], text or "") is not None
    return bool(passed), extracted


# --------------------------------------------------------------------------
# HTTP transport
# --------------------------------------------------------------------------

class HttpError(Exception):
    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class Transport:
    """POST JSON and return a decoded object. aiohttp when available."""

    def __init__(self, concurrency: int, timeout: float = 1200.0):
        self.concurrency = concurrency
        self.timeout = timeout
        self._session = None
        self._executor = None
        self._aiohttp = None

    async def __aenter__(self):
        try:
            import aiohttp  # type: ignore
            self._aiohttp = aiohttp
            connector = aiohttp.TCPConnector(limit=max(self.concurrency, 1))
            timeout = aiohttp.ClientTimeout(total=self.timeout, sock_connect=30)
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        except ImportError:
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=max(self.concurrency, 1) + 4)
        return self

    async def __aexit__(self, *exc):
        if self._session is not None:
            await self._session.close()
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        return False

    async def post_json(self, url: str, payload: dict) -> dict:
        if self._session is not None:
            return await self._post_aiohttp(url, payload)
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, self._post_urllib, url, payload)

    async def _post_aiohttp(self, url: str, payload: dict) -> dict:
        aiohttp = self._aiohttp
        try:
            async with self._session.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"}) as resp:
                body = await resp.read()
                status = resp.status
        except asyncio.TimeoutError:
            raise HttpError("request timed out", retryable=True)
        except aiohttp.ClientError as exc:
            raise HttpError("connection error: %s" % exc, retryable=True)
        return _handle_response(status, body)

    def _post_urllib(self, url: str, payload: dict) -> dict:
        import urllib.error
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _handle_response(resp.status, resp.read())
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            return _handle_response(exc.code, body)
        except Exception as exc:
            raise HttpError("connection error: %s" % exc, retryable=True)


def _handle_response(status: int, body: bytes) -> dict:
    if 500 <= status < 600:
        raise HttpError("server error: HTTP %d" % status, status=status, retryable=True)
    if status < 200 or status >= 300:
        raise HttpError("HTTP %d: %s" % (status, _snippet(body)), status=status, retryable=False)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError("invalid JSON response: %s" % exc, status=status, retryable=False)


def _snippet(body: bytes, limit: int = 200) -> str:
    try:
        text = body.decode("utf-8", "replace")
    except Exception:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:limit]


class RateLimiter:
    """Token bucket pacing requests at `rpm` per minute.

    The bucket capacity is the number of requests we are willing to have in
    flight at once. By Little's law, sustaining `rate` requests per second
    against a server that takes L seconds per request needs rate * L requests
    in flight, so the capacity grows as request latency is observed. Growing
    it credits the difference as tokens, which fills the pipeline once and
    then leaves the steady-state issue rate at `rpm`.
    """

    def __init__(self, rpm: float, max_burst: int):
        self.rate = max(rpm, 1e-9) / 60.0
        self.max_burst = max(1, max_burst)
        # Start out assuming roughly one second of latency.
        self.capacity = max(1.0, min(float(self.max_burst), self.rate + 1.0))
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    def observe_latency(self, seconds: float):
        target = min(float(self.max_burst), self.rate * seconds * 1.25 + 1.0)
        if target > self.capacity:
            self.tokens = min(target, self.tokens + (target - self.capacity))
            self.capacity = target

    async def acquire(self):
        while True:
            async with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
            await asyncio.sleep(min(wait, 5.0))


class Stats:
    def __init__(self):
        self.api_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.first_start = None
        self.last_end = None

    def mark_start(self, t: float):
        if self.first_start is None or t < self.first_start:
            self.first_start = t

    def mark_end(self, t: float):
        if self.last_end is None or t > self.last_end:
            self.last_end = t

    @property
    def elapsed(self) -> float:
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

class Runner:
    def __init__(self, config: Config, transport: Transport, limiter: RateLimiter,
                 semaphore: asyncio.Semaphore, stats: Stats):
        self.config = config
        self.transport = transport
        self.limiter = limiter
        self.semaphore = semaphore
        self.stats = stats
        self.url = config.api_url + "/v1/chat/completions"

    def build_messages(self, row: dict):
        messages = []
        if self.config.system_prompt is not None:
            messages.append({"role": "system",
                             "content": render_template(self.config.system_prompt, row)})
        messages.append({"role": "user",
                         "content": render_template(self.config.user_prompt, row)})
        return messages

    def build_payload(self, messages):
        return {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    async def call_once(self, payload: dict) -> dict:
        """One logical API call, retrying 5xx up to MAX_HTTP_RETRIES times.

        Returns a dict with 'ok', 'content', 'meta'.
        """
        last_error = None
        attempt = 0
        while attempt <= MAX_HTTP_RETRIES:
            if attempt:
                await asyncio.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
            await self.limiter.acquire()
            async with self.semaphore:
                start = time.monotonic()
                self.stats.mark_start(start)
                self.stats.api_calls += 1
                try:
                    data = await self.transport.post_json(self.url, payload)
                    error = None
                except HttpError as exc:
                    data, error = None, exc
                except Exception as exc:  # unexpected client-side failure
                    data, error = None, HttpError(str(exc), retryable=False)
                end = time.monotonic()
                self.stats.mark_end(end)
            latency_ms = int(round((end - start) * 1000))
            self.limiter.observe_latency(end - start)
            attempt += 1

            if error is None:
                try:
                    content, meta = self._parse_completion(data, latency_ms)
                except HttpError as exc:
                    last_error = exc
                    break
                self.stats.prompt_tokens += meta["prompt_tokens"] or 0
                self.stats.completion_tokens += meta["completion_tokens"] or 0
                return {"ok": True, "content": content, "meta": meta}

            last_error = error
            if not error.retryable:
                break

        return {
            "ok": False,
            "content": None,
            "meta": {
                "model": self.config.model,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "latency_ms": latency_ms,
                "finish_reason": None,
                "error": str(last_error) if last_error else "request failed",
            },
        }

    def _parse_completion(self, data, latency_ms: int):
        if not isinstance(data, dict):
            raise HttpError("unexpected response shape")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HttpError("response contained no choices")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if content is None:
            content = choice.get("text")
        if content is None:
            content = ""
        usage = data.get("usage") or {}
        meta = {
            "model": self.config.model,
            "prompt_tokens": _as_int(usage.get("prompt_tokens")),
            "completion_tokens": _as_int(usage.get("completion_tokens")),
            "total_tokens": _as_int(usage.get("total_tokens")),
            "latency_ms": latency_ms,
            "finish_reason": choice.get("finish_reason"),
        }
        return content, meta

    async def process_row(self, row: dict) -> dict:
        cfg = self.config
        payload = self.build_payload(self.build_messages(row))
        metas = []
        attempts = 0
        content = None
        passed = None
        extracted = None
        max_attempts = cfg.n if cfg.scheme == "rejection" else 1

        while attempts < max_attempts:
            result = await self.call_once(payload)
            attempts += 1
            metas.append(result["meta"])
            if not result["ok"]:
                content = None
                passed = False if cfg.evaluation is not None else None
                extracted = None
                break
            content = result["content"]
            passed, extracted = evaluate(cfg, content, row)
            if cfg.scheme != "rejection":
                break
            if passed:
                break
            if attempts < max_attempts:
                content = None
                extracted = None

        api_failed = bool(metas) and metas[-1].get("error") is not None
        if cfg.scheme == "rejection" and (api_failed or not passed):
            content = None
            extracted = None
            passed = False

        if content is None:
            output = None
            extracted = None
            if api_failed:
                passed = None if cfg.evaluation is None else False
        else:
            output = {cfg.output_field: content}

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


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Input / output
# --------------------------------------------------------------------------

def read_config(path: str) -> dict:
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise ConfigError("cannot read config file %s: %s" % (path, exc))
    try:
        data = load_yaml(text)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError("cannot parse YAML config %s: %s" % (path, exc))
    return data


def read_rows(path: str):
    if not os.path.exists(path):
        raise ConfigError("input file not found: %s" % path)
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise ConfigError(
                        "invalid JSON on line %d of %s: %s" % (lineno, path, exc))
                if not isinstance(obj, dict):
                    raise ConfigError(
                        "line %d of %s is not a JSON object" % (lineno, path))
                rows.append(obj)
    except OSError as exc:
        raise ConfigError("cannot read input file %s: %s" % (path, exc))
    return rows


def validate_rows(config: Config, rows):
    fields = list(template_fields(config.system_prompt or ""))
    fields += list(template_fields(config.user_prompt))
    answer_field = None
    if config.evaluation is not None:
        answer_field = config.evaluation.get("answer_field")
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(
                    "row %d is missing field %r required by the prompt template"
                    % (index, field))
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                "row %d is missing field %r required by the evaluation"
                % (index, answer_field))


def write_results(path: str, results):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise ConfigError("cannot create output directory %s: %s" % (directory, exc))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for item in results:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError("cannot write output file %s: %s" % (path, exc))


def summarize(results, stats: Stats) -> dict:
    passed = failed = 0
    for item in results:
        row_passed = item["result"]["passed"]
        if item["output"] is None:
            failed += 1
        elif row_passed is True or row_passed is None:
            passed += 1
        else:
            failed += 1
    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def compute_concurrency(config: Config, row_count: int) -> int:
    """Upper bound on requests in flight; the rate limiter does the pacing."""
    target = max(int(math.ceil(config.rpm)), 32)
    concurrency = max(1, min(target, DEFAULT_CONCURRENCY_CAP))
    return max(1, min(concurrency, max(row_count, 1)))


async def run_async(config: Config, rows) -> tuple:
    stats = Stats()
    if not rows:
        return [], stats
    concurrency = compute_concurrency(config, len(rows))
    limiter = RateLimiter(config.rpm, max_burst=concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    async with Transport(concurrency) as transport:
        runner = Runner(config, transport, limiter, semaphore, stats)
        tasks = [asyncio.ensure_future(runner.process_row(row)) for row in rows]
        results = await asyncio.gather(*tasks)
    return list(results), stats


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rejector.py",
                     description="Run prompts against an OpenAI-compatible chat API.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(VALID_SCHEMES), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    return parser


def command_run(args) -> int:
    overrides = {
        "api_url": args.api_url,
        "model": args.model,
        "rpm": args.rpm,
        "max_tokens": args.max_tokens,
        "scheme": args.scheme,
        "temperature": args.temperature,
        "n": args.n,
    }
    config = Config(read_config(args.config), overrides)
    rows = read_rows(args.input)
    validate_rows(config, rows)

    results, stats = asyncio.run(run_async(config, rows))
    write_results(args.output, results)
    summary = summarize(results, stats)
    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        sys.stderr.write("error: a command is required (try 'run')\n")
        return 1
    try:
        return command_run(args)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("error: interrupted\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
