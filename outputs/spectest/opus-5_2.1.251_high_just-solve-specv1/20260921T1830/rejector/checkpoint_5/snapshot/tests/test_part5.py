#!/usr/bin/env python3
"""End-to-end test suite for the Part 5 features of rejector.py.

Covers token-aware scheduling (sliding RPM/TPM windows, `max_concurrent`),
cost accounting and budgets, structured output validation, `--resume`,
`--dry-run` and `--progress`.

Usage: python tests/test_part5.py  (starts its own mock server)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
REJECTOR = os.path.join(ROOT, "rejector.py")
MOCK = os.path.join(ROOT, "tests", "mock_server.py")
sys.path.insert(0, ROOT)
import rejector  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = int(os.environ["MOCK_PORT"]) if os.environ.get("MOCK_PORT") else free_port()
API = f"http://127.0.0.1:{PORT}"
MOCK_CAPACITY = 16
MOCK_LATENCY = 0.25

FAILURES: list[str] = []
PASSES = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global PASSES
    if condition:
        PASSES += 1
        print(f"  ok   {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL {label} {detail}")


def start_mock() -> subprocess.Popen | None:
    if os.environ.get("MOCK_PORT"):
        return None
    proc = subprocess.Popen(
        [PY, MOCK, "--port", str(PORT), "--capacity", str(MOCK_CAPACITY),
         "--latency", str(MOCK_LATENCY)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API}/stats", timeout=1):
                return proc
        except Exception:
            if proc.poll() is not None:
                raise SystemExit("mock server failed to start")
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit("mock server did not become ready")


def server_stats() -> dict:
    with urllib.request.urlopen(f"{API}/stats", timeout=5) as resp:
        return json.loads(resp.read())


def write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def jsonl(path: str, rows: list[dict]) -> str:
    return write(path, "".join(json.dumps(r) + "\n" for r in rows))


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run(args: list[str]) -> tuple[int, dict | None, str]:
    proc = subprocess.run([PY, REJECTOR, "run"] + args,
                          capture_output=True, text=True, cwd=ROOT)
    summary = None
    if proc.stdout.strip():
        try:
            summary = json.loads(proc.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            summary = None
    return proc.returncode, summary, proc.stderr


def config(path: str, body: str) -> str:
    return write(path, body)


MATH_ROWS = [{"question": f"What is {i} + {i}?", "answer": str(2 * i)}
             for i in range(1, 11)]


def base_task(**parts: str) -> str:
    return f"""
task:
  name: "math_solve"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    system: "Solve the math problem. Final answer after ####."
    user: "{{question}}"
  generation:
    scheme: "{parts.get('scheme', 'greedy')}"
    temperature: {parts.get('temperature', '0.0')}
    max_tokens: {parts.get('max_tokens', '64')}
    n: {parts.get('n', '1')}
  output_field: "solution"
{parts.get('extra', '')}"""


EVAL_EXACT = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
"""


# ---------------------------------------------------------------- limiter unit


def limiter_units() -> None:
    print("\n[rate limiter windows]")
    original = rejector.RATE_WINDOW_SECONDS
    rejector.RATE_WINDOW_SECONDS = 1.0  # a 1s stand-in for the 60s window
    try:
        async def rpm_case() -> float:
            limiter = rejector.RateLimiter(rpm=3)
            started = time.monotonic()
            for _ in range(5):
                await limiter.acquire(0)
            return time.monotonic() - started

        elapsed = asyncio.run(rpm_case())
        check(0.9 <= elapsed < 1.9,
              "rpm uses a sliding window (5 requests at rpm 3 span one window)",
              f"{elapsed:.2f}s")

        async def rpm_off() -> float:
            limiter = rejector.RateLimiter(rpm=None)
            started = time.monotonic()
            for _ in range(50):
                await limiter.acquire(0)
            return time.monotonic() - started

        check(asyncio.run(rpm_off()) < 0.2, "an omitted rpm disables rate limiting")

        async def tpm_case() -> tuple[float, float]:
            limiter = rejector.RateLimiter(tpm=100)
            started = time.monotonic()
            first = await limiter.acquire(80)
            # 80 + 80 does not fit, so the second request has to wait...
            waiter = asyncio.ensure_future(limiter.acquire(80))
            await asyncio.sleep(0.2)
            pending = not waiter.done()
            # ...until the first reservation is replaced by the real usage.
            limiter.record_usage(first, 5, 5)
            await asyncio.wait_for(waiter, timeout=1.0)
            return pending, time.monotonic() - started

        pending, elapsed = asyncio.run(tpm_case())
        check(pending, "tpm blocks a request that does not fit the token window")
        check(elapsed < 0.9,
              "recording real usage frees the reservation before the window ends",
              f"{elapsed:.2f}s")

        async def both_case() -> bool:
            limiter = rejector.RateLimiter(rpm=1, tpm=100000)
            await limiter.acquire(10)
            waiter = asyncio.ensure_future(limiter.acquire(10))
            await asyncio.sleep(0.2)
            blocked = not waiter.done()
            await asyncio.wait_for(waiter, timeout=2.0)
            return blocked

        check(asyncio.run(both_case()),
              "a request waits until both budgets have capacity")

        async def concurrency_case() -> int:
            limiter = rejector.RateLimiter(max_concurrent=2)
            peak = 0
            live = 0

            async def hold() -> None:
                nonlocal peak, live
                async with limiter.slot():
                    live += 1
                    peak = max(peak, live)
                    await asyncio.sleep(0.05)
                    live -= 1

            await asyncio.gather(*[hold() for _ in range(8)])
            return peak

        check(asyncio.run(concurrency_case()) == 2,
              "max_concurrent caps in-flight work independently of rpm/tpm")
    finally:
        rejector.RATE_WINDOW_SECONDS = original

    print("\n[prompt token estimation]")
    messages = [{"role": "system", "content": "one two three"},
                {"role": "user", "content": "four five six"}]
    # 6 words / 0.75 = 8 tokens.
    check(rejector.estimate_prompt_tokens(messages) == 8,
          "1 token ~= 0.75 words, rounded up",
          str(rejector.estimate_prompt_tokens(messages)))
    check(rejector.estimate_prompt_tokens(
        [{"role": "user", "content": "a b c d e"}]) == 7,
        "estimation rounds up")


# ------------------------------------------------------------------ main suite


def main() -> int:
    proc = start_mock()
    try:
        return suite()
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)


def suite() -> int:
    tmp = tempfile.mkdtemp(prefix="rejector-part5-")
    path = lambda name: os.path.join(tmp, name)  # noqa: E731
    data = jsonl(path("math.jsonl"), MATH_ROWS)

    # ------------------------------------------------- max_concurrent (first)
    print("\n[max_concurrent]")
    cfg = config(path("conc.yaml"), base_task(extra="""  rate_limits:
    rpm: 600
    max_concurrent: 3
"""))
    before = server_stats()["max_inflight"]
    code, summary, err = run(["--config", cfg, "--input", data,
                              "--output", path("conc.jsonl")])
    after = server_stats()["max_inflight"]
    check(code == 0 and summary["total"] == 10, "max_concurrent run exit 0", err)
    check(before == 0 and after <= 3,
          "never more than max_concurrent requests in flight", str(after))
    check(after > 1, "requests still overlap up to the cap", str(after))

    cfg = config(path("conc2.yaml"), base_task(extra="""  rate_limits:
    rpm: 600
"""))
    code, summary, err = run(["--config", cfg, "--input", data,
                              "--output", path("conc2.jsonl"),
                              "--max-concurrent", "1"])
    check(code == 0 and summary["total"] == 10, "--max-concurrent run exit 0", err)
    check(server_stats()["max_inflight"] <= 3,
          "--max-concurrent 1 serialises requests",
          str(server_stats()["max_inflight"]))

    limiter_units()

    # ----------------------------------------------------------------- config
    print("\n[rate_limits + cost configuration]")
    multi = config(path("multi.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
    tpm: 50000
    max_concurrent: 10
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 64
  output_field: "solution"
tasks:
  plain: {{}}
  tuned:
    rate_limits:
      tpm: 30000
    cost:
      prompt_cost_per_1k: 0.005
""")
    bundle = rejector.load_config(multi, {}, None)
    plain, tuned = bundle.tasks
    check((plain.rpm, plain.tpm, plain.max_concurrent) == (600, 50000, 10),
          "defaults.rate_limits merge into a task",
          str((plain.rpm, plain.tpm, plain.max_concurrent)))
    check((tuned.rpm, tuned.tpm, tuned.max_concurrent) == (600, 30000, 10),
          "per-task rate_limits override only the keys they specify",
          str((tuned.rpm, tuned.tpm, tuned.max_concurrent)))
    check((plain.cost.prompt_cost_per_1k, plain.cost.completion_cost_per_1k,
           plain.cost.budget) == (0.01, 0.03, 50.0), "defaults.cost merge")
    check((tuned.cost.prompt_cost_per_1k, tuned.cost.completion_cost_per_1k,
           tuned.cost.budget) == (0.005, 0.03, 50.0),
          "per-task cost overrides only the keys it specifies")
    overridden = rejector.load_config(
        multi, {"tpm": 111, "max_concurrent": 2, "budget": 7.5}, None)
    check(all(t.tpm == 111 and t.max_concurrent == 2 and t.cost.budget == 7.5
              for t in overridden.tasks),
          "--tpm / --max-concurrent / --budget override every task")
    no_rpm = rejector.load_config(
        config(path("norpm.yaml"), f"""
task:
  name: "x"
  api_url: "{API}"
  model: "m"
  prompt:
    user: "{{question}}"
"""), {}, None)
    check(no_rpm.tasks[0].rpm is None, "an omitted rpm stays unset")

    # ---------------------------------------------------------- cost tracking
    print("\n[cost tracking]")
    cfg = config(path("cost.yaml"), base_task(extra=EVAL_EXACT + """  rate_limits:
    rpm: 600
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
"""))
    code, summary, err = run(["--config", cfg, "--input", data,
                              "--output", path("cost.jsonl")])
    check(code == 0, "cost run exit 0", err)
    # The mock bills 10 prompt + 5 completion tokens per call.
    expected_prompt = 10 * 10 / 1000 * 0.01
    expected_completion = 10 * 5 / 1000 * 0.03
    cost = summary.get("cost", {})
    check(abs(cost.get("prompt", 0) - expected_prompt) < 1e-9
          and abs(cost.get("completion", 0) - expected_completion) < 1e-9
          and abs(cost.get("total", 0) - (expected_prompt + expected_completion)) < 1e-9,
          "prompt/completion/total cost", str(cost))
    check(cost.get("budget") is None and cost.get("budget_exceeded") is False,
          "no budget configured", str(cost))
    check(len(str(cost.get("total")).split(".")[-1]) >= 4,
          "cost is reported to at least four decimal places", str(cost.get("total")))

    cfg = config(path("nocost.yaml"), base_task(extra=EVAL_EXACT + """  rate_limits:
    rpm: 600
"""))
    code, summary, err = run(["--config", cfg, "--input", data,
                              "--output", path("nocost.jsonl")])
    check(code == 0 and "cost" not in summary,
          "no cost configuration omits the cost field", str(summary))

    print("\n[cost includes judge calls]")
    judge_cfg = config(path("judge.yaml"), f"""
task:
  name: "judged"
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
  prompt:
    system: "Answer."
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 64
  evaluation:
    type: "llm_judge"
    judge_prompt:
      system: "JUDGE: you are a quality evaluator."
      user: "Rate SCORE=9 for {{__response__}}"
    threshold: 7
  output_field: "solution"
""")
    judge_rows = [{"question": "SAY:hello"} for _ in range(4)]
    judge_data = jsonl(path("judge.jsonl"), judge_rows)
    code, summary, err = run(["--config", judge_cfg, "--input", judge_data,
                              "--output", path("judge_out.jsonl")])
    check(code == 0 and summary["total_api_calls"] == 8, "judge calls made", err)
    check(abs(summary["cost"]["total"] - 8 * (10 / 1000 * 0.01 + 5 / 1000 * 0.03))
          < 1e-9, "judge calls are billed too", str(summary["cost"]))

    # --------------------------------------------------------------- budget
    print("\n[budget exhaustion]")
    cfg = config(path("budget.yaml"), base_task(extra=EVAL_EXACT + """  rate_limits:
    rpm: 600
    max_concurrent: 1
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 0.0006
"""))
    out = path("budget.jsonl")
    code, summary, err = run(["--config", cfg, "--input", data, "--output", out])
    rows = read_jsonl(out)
    check(code == 0, "budget exhaustion exits 0", err)
    check(summary["cost"]["budget_exceeded"] is True, "budget_exceeded true",
          str(summary.get("cost")))
    check(summary["cost"]["budget"] == 0.0006
          and summary["cost"]["budget_remaining"] == 0.0,
          "budget and remaining reported", str(summary.get("cost")))
    check(0 < summary["total"] < 10, "partial output is valid", str(summary["total"]))
    check(len(rows) == summary["total"], "completed rows are written", str(len(rows)))
    check([r["input"] for r in rows] == MATH_ROWS[:len(rows)],
          "written rows are the leading input rows")

    code, summary, err = run(["--config", path("cost.yaml"), "--input", data,
                              "--output", path("budget2.jsonl"),
                              "--budget", "0.0006"])
    check(code == 0 and summary["cost"]["budget_exceeded"] is True,
          "--budget overrides the config", str(summary.get("cost")))

    # ----------------------------------------------------- structured output
    print("\n[structured output validation]")
    good = json.dumps({"code": "def add(a, b): return a + b",
                       "explanation": "Simple addition function"})
    schema_rows = [
        {"question": "SAY:" + good},
        {"question": "SAY:" + json.dumps({"code": "x"})},
        {"question": "SAY:definitely not json"},
        {"question": "SAY:" + json.dumps({"code": 5, "explanation": "e"})},
    ]
    schema_data = jsonl(path("schema.jsonl"), schema_rows)
    cfg = config(path("schema.yaml"), f"""
task:
  name: "code_gen"
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 64
  output_schema:
    type: "object"
    required: ["code", "explanation"]
    properties:
      code:
        type: "string"
      explanation:
        type: "string"
  output_field: "code"
""")
    out = path("schema_out.jsonl")
    code, summary, err = run(["--config", cfg, "--input", schema_data, "--output", out])
    rows = read_jsonl(out)
    check(code == 0 and len(rows) == 4, "schema run exit 0", err)
    check(rows[0]["output"] == {"code": {"code": "def add(a, b): return a + b",
                                         "explanation": "Simple addition function"}},
          "valid JSON is stored parsed under output_field", str(rows[0]["output"]))
    check(rows[0]["result"]["passed"] is True
          and rows[0]["result"]["schema_valid"] is True,
          "schema success passes the row", str(rows[0]["result"]))
    check("schema_error" not in rows[0]["result"],
          "no schema_error on success", str(rows[0]["result"]))
    check(rows[1]["output"] is None
          and rows[1]["result"]["passed"] is False
          and rows[1]["result"]["schema_valid"] is False
          and rows[1]["result"]["schema_error"] == "Missing required field: explanation",
          "missing required field", str(rows[1]["result"]))
    check(rows[2]["output"] is None and rows[2]["result"]["schema_valid"] is False
          and "JSON" in rows[2]["result"]["schema_error"],
          "invalid JSON counts as a schema failure", str(rows[2]["result"]))
    check(rows[3]["output"] is None and rows[3]["result"]["schema_valid"] is False
          and "code" in rows[3]["result"]["schema_error"],
          "wrong property type fails", str(rows[3]["result"]))
    check(summary["passed"] == 1 and summary["failed"] == 3,
          "schema failures count as failed rows", str(summary))

    print("\n[schema runs before evaluation]")
    cfg = config(path("schema_eval.yaml"), f"""
task:
  name: "code_gen"
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 64
  output_schema:
    type: "object"
    required: ["answer"]
    properties:
      answer:
        type: "string"
  evaluation:
    type: "contains"
    answer_field: "answer"
  output_field: "solution"
""")
    eval_rows = [
        {"question": "SAY:" + json.dumps({"answer": "42 is right"}), "answer": "42"},
        {"question": "SAY:" + json.dumps({"answer": "nope"}), "answer": "42"},
        {"question": "SAY:broken", "answer": "42"},
    ]
    out = path("schema_eval.jsonl")
    code, summary, err = run(["--config", cfg, "--input",
                              jsonl(path("se.jsonl"), eval_rows), "--output", out])
    rows = read_jsonl(out)
    check(code == 0 and rows[0]["result"]["passed"] is True,
          "schema + evaluation both pass", err)
    check(rows[1]["result"]["passed"] is False
          and rows[1]["result"]["schema_valid"] is True,
          "evaluation still gates a schema-valid row", str(rows[1]["result"]))
    check(rows[2]["result"]["schema_valid"] is False
          and rows[2]["result"]["passed"] is False,
          "evaluation is skipped when the schema fails", str(rows[2]["result"]))

    print("\n[schema keywords]")
    keyword_schema = {
        "type": "object",
        "required": ["name", "score", "tags", "kind"],
        "properties": {
            "name": {"type": "string", "minLength": 2, "maxLength": 6,
                     "pattern": "^[a-z]+$"},
            "score": {"type": "number", "minimum": 1, "maximum": 10},
            "tags": {"type": "array", "items": {"type": "string"}},
            "kind": {"enum": ["a", "b"]},
        },
    }
    ok_value = {"name": "abc", "score": 5, "tags": ["x"], "kind": "a"}
    cases = [
        (ok_value, None),
        ({**ok_value, "name": "a"}, "at least 2 characters"),
        ({**ok_value, "name": "abcdefg"}, "at most 6 characters"),
        ({**ok_value, "name": "AB1"}, "does not match pattern"),
        ({**ok_value, "score": 0}, ">= 1"),
        ({**ok_value, "score": 99}, "<= 10"),
        ({**ok_value, "tags": [1]}, "must be of type string"),
        ({**ok_value, "kind": "z"}, "must be one of"),
        ({**ok_value, "kind": None}, "must be one of"),
    ]
    for value, expected in cases:
        error = rejector.validate_schema(value, keyword_schema)
        if expected is None:
            check(error is None, "valid value passes every keyword", str(error))
        else:
            check(error is not None and expected in error,
                  f"schema keyword rejects {expected!r}", str(error))
    check(rejector.validate_schema(3, {"type": "integer"}) is None
          and rejector.validate_schema(3.0, {"type": "integer"}) is None
          and rejector.validate_schema(True, {"type": "integer"}) is not None,
          "draft 7 integer semantics")
    check(rejector.validate_schema([1, 2], {"type": "array",
                                            "items": {"type": "number"}}) is None,
          "array items validate")

    print("\n[schema with rejection sampling]")
    cfg = config(path("schema_rej.yaml"), f"""
task:
  name: "code_gen"
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "rejection"
    temperature: 0.7
    max_tokens: 64
    n: 3
  output_schema:
    type: "object"
    required: ["code"]
  output_field: "code"
""")
    rej_rows = [{"question": "SAY:" + json.dumps({"code": "ok"})},
                {"question": "SAY:not json"}]
    out = path("schema_rej.jsonl")
    code, summary, err = run(["--config", cfg, "--input",
                              jsonl(path("sr.jsonl"), rej_rows), "--output", out])
    rows = read_jsonl(out)
    check(code == 0, "rejection with only an output_schema is a valid config", err)
    check(rows[0]["result"]["attempts"] == 1
          and rows[0]["output"] == {"code": {"code": "ok"}},
          "a schema-valid sample is accepted at once", str(rows[0]["result"]))
    check(rows[1]["result"]["attempts"] == 3 and rows[1]["output"] is None
          and rows[1]["result"]["schema_valid"] is False,
          "a schema failure is a rejected attempt", str(rows[1]["result"]))

    print("\n[schema with several solutions]")
    cfg = config(path("schema_multi.yaml"), f"""
task:
  name: "code_gen"
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "sample"
    temperature: 0.7
    max_tokens: 64
  num_solutions: 2
  output_schema:
    type: "object"
    required: ["code"]
  output_field: "code"
""")
    out = path("schema_multi.jsonl")
    code, summary, err = run(["--config", cfg, "--input",
                              jsonl(path("sm.jsonl"), rej_rows), "--output", out])
    rows = read_jsonl(out)
    check(code == 0 and len(rows[0]["output"]) == 2,
          "valid rows keep the list output shape", err)
    check(rows[0]["output"][0]["code"] == {"code": "ok"},
          "list outputs hold the parsed value", str(rows[0]["output"][0]))
    check(rows[1]["output"] == [] and rows[1]["meta"][0]["schema_valid"] is False,
          "an invalid attempt emits no solution", str(rows[1]))

    print("\n[schema config validation]")
    bad = config(path("badschema.yaml"), base_task(extra="""  output_schema:
    type: "banana"
"""))
    code, summary, err = run(["--config", bad, "--input", data,
                              "--output", path("bad.jsonl")])
    check(code == 1 and "type" in err, "an unknown schema type exits 1", err.strip())

    # --------------------------------------------------------------- dry run
    print("\n[dry run]")
    cfg = config(path("dry.yaml"), base_task(max_tokens="512",
                                             extra=EVAL_EXACT + """  rate_limits:
    rpm: 100
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
"""))
    before = server_stats()["total"]
    out = path("dry.jsonl")
    code, summary, err = run(["--config", cfg, "--input", data, "--output", out,
                              "--dry-run"])
    check(code == 0, "dry run exits 0", err)
    check(server_stats()["total"] == before, "dry run makes no API calls")
    check(not os.path.exists(out), "dry run writes no output file")
    check(set(summary) == {"tasks", "total_inputs", "est_total_tokens",
                           "est_total_cost", "est_time_minutes"},
          "dry run summary keys", str(summary))
    entry = summary["tasks"]["math_solve"]
    check(set(entry) == {"inputs", "est_prompt_tokens", "est_completion_tokens",
                         "est_total_tokens", "est_cost"},
          "dry run task keys", str(entry))
    words = sum(len(("Solve the math problem. Final answer after ####. "
                     + row["question"]).split()) for row in MATH_ROWS) / 10
    check(entry["inputs"] == 10
          and entry["est_prompt_tokens"] == round(10 * words * 1.33),
          "prompt tokens estimated as average words * 1.33", str(entry))
    check(entry["est_completion_tokens"] == 10 * 512
          and entry["est_total_tokens"] == entry["est_prompt_tokens"] + 10 * 512,
          "completion tokens estimated as max_tokens per input", str(entry))
    expected_cost = (entry["est_prompt_tokens"] / 1000 * 0.01
                     + entry["est_completion_tokens"] / 1000 * 0.03)
    check(abs(entry["est_cost"] - expected_cost) < 1e-6, "estimated cost",
          str(entry["est_cost"]))
    check(abs(summary["est_time_minutes"] - 10 / 100) < 1e-6,
          "time estimated as inputs * avg_attempts / rpm",
          str(summary["est_time_minutes"]))

    cfg = config(path("dryrej.yaml"), base_task(
        scheme="rejection", temperature="0.7", n="4",
        extra=EVAL_EXACT + """  rate_limits:
    rpm: 100
"""))
    code, summary, err = run(["--config", cfg, "--input", data,
                              "--output", path("dryrej.jsonl"), "--dry-run"])
    check(code == 0 and abs(summary["est_time_minutes"] - 10 * 4 / 100) < 1e-6,
          "rejection plans for n attempts per input", str(summary))
    check(summary["est_total_cost"] == 0.0,
          "no cost configuration estimates zero", str(summary))

    code, summary, err = run(["--config", path("badschema.yaml"), "--input", data,
                              "--output", path("x.jsonl"), "--dry-run"])
    check(code == 1, "dry run still validates the config", err.strip())

    # ---------------------------------------------------------------- resume
    print("\n[resume]")
    cfg = config(path("resume.yaml"), base_task(extra=EVAL_EXACT + """  rate_limits:
    rpm: 600
"""))
    out = path("resume.jsonl")
    code, full, err = run(["--config", cfg, "--input", data, "--output", out])
    check(code == 0 and full["total"] == 10, "baseline run", err)
    complete = read_jsonl(out)
    write(out, "".join(json.dumps(r) + "\n" for r in complete[:4]))
    before = server_stats()["total"]
    code, summary, err = run(["--config", cfg, "--input", data, "--output", out,
                              "--resume"])
    rows = read_jsonl(out)
    check(code == 0 and summary["total"] == 6 and summary["resumed_from"] == 4,
          "summary covers only new rows and reports resumed_from", str(summary))
    check(server_stats()["total"] - before == 6, "only the missing rows are sent")
    check(len(rows) == 10 and [r["input"] for r in rows] == MATH_ROWS,
          "rows are appended in input order", str(len(rows)))
    check(rows[:4] == complete[:4], "existing rows are preserved verbatim")

    code, summary, err = run(["--config", cfg, "--input", data, "--output", out,
                              "--resume"])
    check(code == 0 and summary["total"] == 0 and summary["resumed_from"] == 10,
          "a finished run resumes to nothing", str(summary))

    missing = path("missing.jsonl")
    code, summary, err = run(["--config", cfg, "--input", data, "--output", missing,
                              "--resume"])
    check(code == 0 and summary["total"] == 10 and summary["resumed_from"] == 0,
          "--resume with no existing output runs everything", str(summary))

    print("\n[resume reprocesses incomplete rejection rows]")
    rej_cfg = config(path("resume_rej.yaml"), base_task(
        scheme="rejection", temperature="0.7", n="2",
        extra=EVAL_EXACT + """  rate_limits:
    rpm: 600
"""))
    rej_rows_in = [{"question": "What is 1 + 1?", "answer": "2"},
                   {"question": "NEVER What is 2 + 2?", "answer": "4"},
                   {"question": "What is 3 + 3?", "answer": "6"}]
    rej_data = jsonl(path("rej.jsonl"), rej_rows_in)
    out = path("resume_rej.jsonl")
    code, summary, err = run(["--config", rej_cfg, "--input", rej_data, "--output", out])
    rows = read_jsonl(out)
    check(code == 0 and rows[1]["output"] is None,
          "the middle row exhausts its rejection budget", err)
    write(out, "".join(json.dumps(r) + "\n" for r in rows[:2]))
    before = server_stats()["total"]
    code, summary, err = run(["--config", rej_cfg, "--input", rej_data, "--output", out,
                              "--resume"])
    rows = read_jsonl(out)
    check(summary["resumed_from"] == 1 and summary["total"] == 2,
          "an incomplete rejection row is not skipped", str(summary))
    check(len(rows) == 3 and [r["input"] for r in rows] == rej_rows_in,
          "the reprocessed row keeps its place", str(len(rows)))
    check(server_stats()["total"] - before >= 3, "the incomplete row is retried")

    print("\n[resume per task file]")
    multi_cfg = config(path("resume_multi.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 64
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
  output_field: "solution"
tasks:
  alpha: {{}}
  beta: {{}}
""")
    out_dir = path("resume_multi")
    code, summary, err = run(["--config", multi_cfg, "--input", f"alpha={data}",
                              "--input", f"beta={data}", "--output", out_dir])
    check(code == 0 and summary["total"] == 20, "multi-task baseline", err)
    alpha_path = os.path.join(out_dir, "alpha.jsonl")
    beta_path = os.path.join(out_dir, "beta.jsonl")
    alpha_rows = read_jsonl(alpha_path)
    write(alpha_path, "".join(json.dumps(r) + "\n" for r in alpha_rows[:3]))
    write(beta_path, "".join(json.dumps(r) + "\n" for r in read_jsonl(beta_path)[:7]))
    code, summary, err = run(["--config", multi_cfg, "--input", f"alpha={data}",
                              "--input", f"beta={data}", "--output", out_dir,
                              "--resume"])
    check(code == 0 and summary["resumed_from"] == 10 and summary["total"] == 10,
          "resume applies per task output file", str(summary))
    check(summary["tasks"]["alpha"]["total"] == 7
          and summary["tasks"]["beta"]["total"] == 3,
          "each task resumes from its own file", str(summary["tasks"]))
    check(len(read_jsonl(alpha_path)) == 10 and len(read_jsonl(beta_path)) == 10,
          "both files are complete again")

    # -------------------------------------------------------------- progress
    print("\n[progress]")
    cfg = config(path("progress.yaml"), base_task(extra=EVAL_EXACT + """  rate_limits:
    rpm: 600
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
"""))
    code, summary, err = run(["--config", cfg, "--input", data,
                              "--output", path("progress.jsonl"), "--progress"])
    lines = [line for line in err.splitlines() if line.strip()]
    check(code == 0 and lines, "progress writes to stderr", err)
    pattern = re.compile(
        r"^\[(\d+)/10\] (\d+)% complete \| (\d+) passed, (\d+) failed "
        r"\| [\d.]+ rpm \| \$[\d.]+ spent \| ETA: .+$")
    check(all(pattern.match(line) for line in lines),
          "progress line format", lines[0] if lines else "")
    check(any(line.startswith("[10/10] 100% complete") for line in lines),
          "a final 100% line is printed", str(lines[-1:]))
    # every 10% of 10 inputs is every row
    check(len(lines) >= 10, "progress at least every 10% of the inputs",
          str(len(lines)))

    code, summary, err = run(["--config", path("nocost.yaml"), "--input", data,
                              "--output", path("progress2.jsonl"), "--progress"])
    lines = [line for line in err.splitlines() if line.strip()]
    check(lines and all("spent" not in line for line in lines),
          "cost field omitted when cost tracking is off", str(lines[:1]))
    check(all("passed" in line for line in lines),
          "passed/failed kept when evaluation is configured", str(lines[:1]))

    plain_cfg = config(path("plain.yaml"), base_task(extra="""  rate_limits:
    rpm: 600
"""))
    code, summary, err = run(["--config", plain_cfg, "--input", data,
                              "--output", path("progress3.jsonl"), "--progress"])
    lines = [line for line in err.splitlines() if line.strip()]
    check(lines and all("passed" not in line and "spent" not in line
                        for line in lines),
          "passed/failed omitted without evaluation", str(lines[:1]))
    check(all(re.match(r"^\[\d+/10\] \d+% complete \| [\d.]+ rpm \| ETA: .+$", line)
              for line in lines),
          "minimal progress line format", str(lines[:1]))

    # ------------------------------------------------------------ tpm paces
    print("\n[tpm is the binding limit] (~60s)")
    cfg = config(path("tpm.yaml"), base_task(max_tokens="50", extra="""  rate_limits:
    rpm: 600
    tpm: 200
"""))
    tpm_rows = [{"question": f"What is {i} + {i}?"} for i in range(1, 16)]
    started = time.time()
    code, summary, err = run(["--config", cfg, "--input",
                              jsonl(path("tpm.jsonl"), tpm_rows),
                              "--output", path("tpm_out.jsonl")])
    elapsed = time.time() - started
    check(code == 0 and summary["total"] == 15, "tpm run exit 0", err)
    check(summary["throughput_rpm"] < 200,
          "the run paces to the token budget, not the request budget",
          str(summary["throughput_rpm"]))
    check(elapsed > 30,
          "a tpm far below rpm slows the run down", f"{elapsed:.1f}s")
    rows = read_jsonl(path("tpm_out.jsonl"))
    check([r["input"] for r in rows] == tpm_rows,
          "rows stay in input order while the limiter paces them")

    print(f"\n{PASSES} passed, {len(FAILURES)} failed")
    for name in FAILURES:
        print(f"  - {name}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
