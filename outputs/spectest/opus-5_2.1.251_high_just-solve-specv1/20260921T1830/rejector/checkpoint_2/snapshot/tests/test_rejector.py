#!/usr/bin/env python3
"""End-to-end test suite for rejector.py against the mock server.

Usage: python tests/test_rejector.py  (starts its own mock server)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import socket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
REJECTOR = os.path.join(ROOT, "rejector.py")
MOCK = os.path.join(ROOT, "tests", "mock_server.py")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = int(os.environ["MOCK_PORT"]) if os.environ.get("MOCK_PORT") else free_port()
API = f"http://127.0.0.1:{PORT}"

# The mock is capped at 60 rpm (2 slots x 2s), matching the configs' rpm: 60.
# A sequential client could only reach 30 rpm.
MOCK_CAPACITY = 2
MOCK_LATENCY = 2.0


def start_mock() -> subprocess.Popen | None:
    if os.environ.get("MOCK_PORT"):
        return None  # caller manages the server
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


def write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def jsonl(path: str, rows: list[dict]) -> str:
    return write(path, "".join(json.dumps(r) + "\n" for r in rows))


def run(args: list[str], tmp: str) -> tuple[int, dict | None, str, list[dict]]:
    out_path = os.path.join(tmp, "out.jsonl")
    proc = subprocess.run(
        [PY, REJECTOR, "run", "--output", out_path] + args,
        capture_output=True, text=True, cwd=ROOT,
    )
    summary = None
    if proc.stdout.strip():
        try:
            summary = json.loads(proc.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            summary = None
    rows = []
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    return proc.returncode, summary, proc.stderr, rows


BASE_CONFIG = """
task:
  name: "math_solve"
  api_url: "{api}"
  model: "gpt-4"
  rpm: {rpm}
  prompt:
    system: "Solve the math problem. Final answer after ####."
    user: "{{question}}"
  generation:
    scheme: "{scheme}"
    temperature: {temperature}
    max_tokens: 256
    n: {n}
{evaluation}
  output_field: "solution"
"""

EVAL_EXACT = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
"""


def cfg(tmp, name, *, scheme="greedy", temperature=0.0, n=1, rpm=60,
        evaluation=EVAL_EXACT, api=API):
    return write(
        os.path.join(tmp, name),
        BASE_CONFIG.format(api=api, rpm=rpm, scheme=scheme,
                           temperature=temperature, n=n, evaluation=evaluation),
    )


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="rejector-tests-")
    print(f"workdir: {tmp}\n")

    # ---------------------------------------------------------------- greedy
    print("[greedy: happy path, output shape, summary]")
    data = jsonl(os.path.join(tmp, "d1.jsonl"),
                 [{"question": "What is 2 + 3?", "answer": "5"},
                  {"question": "What is 10 - 4?", "answer": "6"}])
    code, summary, err, rows = run(["--config", cfg(tmp, "c1.yaml"), "--input", data], tmp)
    check(code == 0, "greedy exit code 0", f"stderr={err}")
    check(len(rows) == 2, "one output row per input row")
    r0 = rows[0] if rows else {}
    check(r0.get("input") == {"question": "What is 2 + 3?", "answer": "5"},
          "input echoed unchanged")
    check(isinstance(r0.get("output"), dict) and list(r0["output"]) == ["solution"],
          "output keyed by output_field", str(r0.get("output")))
    check(r0.get("result", {}).get("passed") is True, "passed true on match")
    check(r0.get("result", {}).get("extracted_answer") == "5", "extracted last_number")
    check(r0.get("result", {}).get("attempts") == 1, "greedy attempts == 1")
    meta = r0.get("meta")
    check(isinstance(meta, dict), "meta is a single object for one-attempt rows")
    check(set(meta) == {"model", "prompt_tokens", "completion_tokens", "total_tokens",
                        "latency_ms", "finish_reason"}, "meta keys", str(meta))
    check(meta.get("model") == "gpt-4" and meta.get("finish_reason") == "stop", "meta values")
    check(isinstance(meta.get("latency_ms"), int) and meta["latency_ms"] > 0, "latency_ms > 0")
    check(summary == {"total": 2, "passed": 2, "failed": 0, "total_prompt_tokens": 20,
                      "total_completion_tokens": 10, "total_api_calls": 2,
                      "elapsed_seconds": summary.get("elapsed_seconds"),
                      "throughput_rpm": summary.get("throughput_rpm")},
          "summary fields", str(summary))
    check(set(summary) == {"total", "passed", "failed", "total_prompt_tokens",
                           "total_completion_tokens", "total_api_calls",
                           "elapsed_seconds", "throughput_rpm"}, "summary keys exact")
    check(round(summary["elapsed_seconds"], 1) == summary["elapsed_seconds"]
          and round(summary["throughput_rpm"], 1) == summary["throughput_rpm"],
          "summary numbers rounded to 1dp")

    print("\n[greedy: forces temperature 0, wrong answer fails]")
    data = jsonl(os.path.join(tmp, "d2.jsonl"),
                 [{"question": "What is 2 + 3?", "answer": "99"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c2.yaml", temperature=0.9), "--input", data], tmp)
    check(code == 0, "greedy with configured temperature still valid", err)
    check(rows[0]["result"]["passed"] is False, "passed false on mismatch")
    check(summary["passed"] == 0 and summary["failed"] == 1, "summary counts failure")

    # ------------------------------------------------------------ no evaluation
    print("\n[no evaluation configured]")
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c3.yaml", evaluation=""), "--input", data], tmp)
    check(code == 0, "no-evaluation run succeeds", err)
    check(rows[0]["result"]["passed"] is None, "passed is null without evaluation")
    check(rows[0]["result"]["extracted_answer"] is None, "extracted_answer null")
    check(summary["passed"] == 1 and summary["failed"] == 0,
          "successful API rows counted as passed", str(summary))

    # ---------------------------------------------------------------- sample
    print("\n[sample]")
    data = jsonl(os.path.join(tmp, "d4.jsonl"),
                 [{"question": "What is 7 * 6?", "answer": "42"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c4.yaml", scheme="sample", temperature=0.7),
         "--input", data], tmp)
    check(code == 0, "sample exit 0", err)
    check(rows[0]["result"]["attempts"] == 1, "sample attempts == 1")
    check(rows[0]["result"]["passed"] is True, "sample evaluated")

    code, _, err, _ = run(
        ["--config", cfg(tmp, "c5.yaml", scheme="sample", temperature=0.0),
         "--input", data], tmp)
    check(code == 1 and "temperature" in err, "sample with temperature 0 exits 1", err)

    # ------------------------------------------------------------- rejection
    print("\n[rejection]")
    data = jsonl(os.path.join(tmp, "d6.jsonl"),
                 [{"question": "REJECT2 What is 4 + 4?", "answer": "8"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c6.yaml", scheme="rejection", temperature=0.8, n=5),
         "--input", data], tmp)
    check(code == 0, "rejection exit 0", err)
    check(rows[0]["result"]["attempts"] == 3, "attempts == 3 (2 rejected, 3rd passes)",
          str(rows[0]["result"]))
    check(rows[0]["result"]["passed"] is True, "rejection passed")
    check(isinstance(rows[0]["meta"], list) and len(rows[0]["meta"]) == 3,
          "meta is a 3-entry list", str(type(rows[0]["meta"])))
    check(rows[0]["output"]["solution"].endswith("#### 8"), "keeps the passing response")
    check(summary["total_api_calls"] == 3, "rejection attempts counted in total_api_calls")

    print("\n[rejection: exhausted]")
    data = jsonl(os.path.join(tmp, "d7.jsonl"),
                 [{"question": "NEVER What is 4 + 4?", "answer": "8"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c7.yaml", scheme="rejection", temperature=0.8, n=4),
         "--input", data], tmp)
    check(code == 0, "exhausted rejection exit 0", err)
    check(rows[0]["output"] is None, "output null when all attempts fail")
    check(rows[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 4},
          "result on exhaustion", str(rows[0]["result"]))
    check(isinstance(rows[0]["meta"], list) and len(rows[0]["meta"]) == 4,
          "one meta per attempt")
    check(summary["failed"] == 1 and summary["passed"] == 0, "exhausted row counted failed")

    print("\n[rejection: single attempt -> meta is an object]")
    data = jsonl(os.path.join(tmp, "d8.jsonl"),
                 [{"question": "What is 4 + 4?", "answer": "8"}])
    code, _, err, rows = run(
        ["--config", cfg(tmp, "c8.yaml", scheme="rejection", temperature=0.8, n=3),
         "--input", data], tmp)
    check(rows[0]["result"]["attempts"] == 1 and isinstance(rows[0]["meta"], dict),
          "one-attempt rejection row has object meta")

    print("\n[rejection requires evaluation]")
    code, _, err, _ = run(
        ["--config", cfg(tmp, "c9.yaml", scheme="rejection", temperature=0.8,
                         evaluation=""), "--input", data], tmp)
    check(code == 1 and "evaluation" in err, "rejection without evaluation exits 1", err)
    code, _, err, _ = run(
        ["--config", cfg(tmp, "c10.yaml", scheme="rejection", temperature=0.0),
         "--input", data], tmp)
    check(code == 1 and "temperature" in err, "rejection with temperature 0 exits 1", err)

    # ------------------------------------------------------------ 5xx retries
    print("\n[5xx retry behaviour]")
    data = jsonl(os.path.join(tmp, "d11.jsonl"),
                 [{"question": "FLAKY2 What is 5 + 5?", "answer": "10"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c11.yaml"), "--input", data], tmp)
    check(code == 0, "flaky row eventually succeeds", err)
    check(rows[0]["result"]["attempts"] == 1, "retries do not raise logical attempts")
    check(summary["total_api_calls"] == 3, "retries counted in total_api_calls",
          str(summary))
    check(isinstance(rows[0]["meta"], dict), "retried row keeps single meta object")

    data = jsonl(os.path.join(tmp, "d12.jsonl"),
                 [{"question": "ALWAYS_500 What is 5 + 5?", "answer": "10"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c12.yaml"), "--input", data], tmp)
    check(code == 0, "persistent 5xx does not abort the run", err)
    check(rows[0]["output"] is None, "failed row emits null output")
    check(rows[0]["result"]["attempts"] == 1, "greedy failure attempts == 1")
    check(summary["total_api_calls"] == 3, "exactly 3 total requests", str(summary))
    check(summary["failed"] == 1 and summary["total"] == 1, "failed row counted")

    # ------------------------------------------------------- evaluation types
    print("\n[evaluation types and extract methods]")
    contains = """  evaluation:
    type: "contains"
    answer_field: "answer"
"""
    data = jsonl(os.path.join(tmp, "d13.jsonl"),
                 [{"question": "What is 2 + 3?", "answer": "#### 5"},
                  {"question": "What is 2 + 3?", "answer": "zebra"}])
    code, _, err, rows = run(
        ["--config", cfg(tmp, "c13.yaml", evaluation=contains), "--input", data], tmp)
    check(code == 0, "contains run ok", err)
    check(rows[0]["result"]["passed"] is True and rows[1]["result"]["passed"] is False,
          "contains substring semantics",
          str([r["result"]["passed"] for r in rows]))

    regex = """  evaluation:
    type: "regex"
    pattern: "####\\\\s*(\\\\d+)"
"""
    data = jsonl(os.path.join(tmp, "d14.jsonl"), [{"question": "What is 2 + 3?"}])
    code, _, err, rows = run(
        ["--config", cfg(tmp, "c14.yaml", evaluation=regex), "--input", data], tmp)
    check(code == 0, "regex run ok (no answer_field required)", err)
    check(rows[0]["result"]["passed"] is True, "regex match")
    check(rows[0]["result"]["extracted_answer"] == "5", "regex extracted group",
          str(rows[0]["result"]))

    last_line = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_line"
"""
    data = jsonl(os.path.join(tmp, "d15.jsonl"),
                 [{"question": "What is 2 + 3?", "answer": "#### 5"}])
    code, _, err, rows = run(
        ["--config", cfg(tmp, "c15.yaml", evaluation=last_line), "--input", data], tmp)
    check(rows[0]["result"]["extracted_answer"] == "#### 5"
          and rows[0]["result"]["passed"] is True, "last_line extract",
          str(rows[0]["result"]))

    full = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "full"
"""
    data = jsonl(os.path.join(tmp, "d16.jsonl"),
                 [{"question": "What is 2 + 3?",
                   "answer": "Let me solve this step by step.\nWhat is 2 + 3?\n#### 5"}])
    code, _, err, rows = run(
        ["--config", cfg(tmp, "c16.yaml", evaluation=full), "--input", data], tmp)
    check(rows[0]["result"]["passed"] is True, "full extract", str(rows[0]["result"]))

    # -------------------------------------------------------------- overrides
    print("\n[CLI overrides]")
    data = jsonl(os.path.join(tmp, "d17.jsonl"),
                 [{"question": "REJECT1 What is 3 + 3?", "answer": "6"}])
    code, summary, err, rows = run(
        ["--config", cfg(tmp, "c17.yaml"), "--input", data,
         "--scheme", "rejection", "--temperature", "0.7", "--n", "3",
         "--model", "override-model", "--rpm", "120", "--max-tokens", "64",
         "--api-url", API], tmp)
    check(code == 0, "overrides accepted", err)
    check(rows[0]["result"]["attempts"] == 2, "scheme/n overrides applied",
          str(rows[0]["result"]))
    check(rows[0]["meta"][0]["model"] == "override-model", "model override applied")

    code, _, err, _ = run(
        ["--config", cfg(tmp, "c18.yaml"), "--input", data, "--scheme", "bogus"], tmp)
    check(code == 1, "invalid --scheme exits 1", err)
    code, _, err, _ = run(
        ["--config", cfg(tmp, "c19.yaml"), "--input", data, "--n", "abc"], tmp)
    check(code == 1, "non-integer --n exits 1", err)

    # ------------------------------------------------------------ input errors
    print("\n[config and input errors]")
    bad_rows = jsonl(os.path.join(tmp, "d20.jsonl"), [{"text": "hello"}])
    code, _, err, rows = run(["--config", cfg(tmp, "c20.yaml"), "--input", bad_rows], tmp)
    check(code == 1, "missing template field exits 1")
    check("0" in err and "question" in err,
          "error names row index and missing field", err.strip())

    data = jsonl(os.path.join(tmp, "d21.jsonl"), [{"question": "What is 1 + 1?"}])
    code, _, err, _ = run(["--config", cfg(tmp, "c21.yaml"), "--input", data], tmp)
    check(code == 1 and "answer" in err, "missing answer_field exits 1", err.strip())

    code, _, err, _ = run(["--config", os.path.join(tmp, "nope.yaml"),
                           "--input", data], tmp)
    check(code == 1 and "config" in err, "missing config file exits 1", err.strip())
    code, _, err, _ = run(["--config", cfg(tmp, "c22.yaml"),
                           "--input", os.path.join(tmp, "nope.jsonl")], tmp)
    check(code == 1 and "input" in err, "missing input file exits 1", err.strip())

    write(os.path.join(tmp, "broken.jsonl"), '{"question": "x"\n')
    code, _, err, _ = run(["--config", cfg(tmp, "c23.yaml"),
                           "--input", os.path.join(tmp, "broken.jsonl")], tmp)
    check(code == 1 and "JSON" in err, "malformed JSONL exits 1", err.strip())

    bad_eval = """  evaluation:
    type: "exact_match"
"""
    code, _, err, _ = run(["--config", cfg(tmp, "c24.yaml", evaluation=bad_eval),
                           "--input", data], tmp)
    check(code == 1 and "answer_field" in err, "exact_match without answer_field exits 1",
          err.strip())
    bad_eval = """  evaluation:
    type: "regex"
"""
    code, _, err, _ = run(["--config", cfg(tmp, "c25.yaml", evaluation=bad_eval),
                           "--input", data], tmp)
    check(code == 1 and "pattern" in err, "regex without pattern exits 1", err.strip())
    bad_eval = """  evaluation:
    type: "nonsense"
    answer_field: "answer"
"""
    code, _, err, _ = run(["--config", cfg(tmp, "c26.yaml", evaluation=bad_eval),
                           "--input", data], tmp)
    check(code == 1 and "type" in err, "invalid evaluation type exits 1", err.strip())
    write(os.path.join(tmp, "c27.yaml"), "task:\n  name: x\n")
    code, _, err, _ = run(["--config", os.path.join(tmp, "c27.yaml"),
                           "--input", data], tmp)
    check(code == 1, "config missing required fields exits 1", err.strip())
    write(os.path.join(tmp, "c28.yaml"), "task: [1, 2\n  - bad yaml")
    code, _, err, _ = run(["--config", os.path.join(tmp, "c28.yaml"),
                           "--input", data], tmp)
    check(code == 1 and "YAML" in err, "invalid YAML exits 1", err.strip())

    # ------------------------------------------------------------- empty input
    print("\n[empty input]")
    empty = write(os.path.join(tmp, "empty.jsonl"), "")
    code, summary, err, rows = run(["--config", cfg(tmp, "c29.yaml"),
                                    "--input", empty], tmp)
    check(code == 0 and rows == [], "empty input succeeds with empty output", err)
    check(summary["total"] == 0 and summary["elapsed_seconds"] == 0.0
          and summary["throughput_rpm"] == 0.0, "empty summary", str(summary))

    # ------------------------------------------------- ordering and throughput
    print("\n[ordering + throughput]")
    rows_in = [{"question": f"What is {i} + {i}?", "answer": str(2 * i)}
               for i in range(1, 41)]
    data = jsonl(os.path.join(tmp, "d30.jsonl"), rows_in)
    started = time.time()
    code, summary, err, rows = run(["--config", cfg(tmp, "c30.yaml"), "--input", data], tmp)
    wall = time.time() - started
    check(code == 0, "bulk run exit 0", err)
    check([r["input"] for r in rows] == rows_in, "output rows in input order")
    check(all(r["result"]["passed"] for r in rows), "all bulk rows pass")
    check(summary["throughput_rpm"] >= 48.0,
          f"throughput >= 80% of rpm (got {summary.get('throughput_rpm')})")
    # Server cap is 60 rpm, so 40 rows need >=40s; a sequential client would need ~80s.
    check(wall < 60, f"40 rows beat a sequential client (took {wall:.1f}s, seq ~80s)")
    with urllib.request.urlopen(f"{API}/stats", timeout=5) as resp:
        stats = json.loads(resp.read())
    check(stats["max_inflight"] > 1, "requests genuinely concurrent", str(stats))
    arrivals = [int(re.search(r"What is (\d+)", a).group(1))
                for a in stats["arrivals"][-40:]]
    check(arrivals == sorted(arrivals), "requests reach the server in input order",
          str(arrivals))
    check(all(r["input"]["answer"] == r["output"]["solution"].rsplit("#### ", 1)[-1]
              for r in rows), "each row keeps its own response")

    # --------------------------------------------------------- misc edge cases
    print("\n[misc]")
    write(os.path.join(tmp, "d31.jsonl"),
          json.dumps({"question": "What is 2 + 3?", "answer": "5"}))  # no trailing \n
    code, _, err, rows = run(["--config", cfg(tmp, "c31.yaml"),
                              "--input", os.path.join(tmp, "d31.jsonl")], tmp)
    check(code == 0 and len(rows) == 1, "input without trailing newline", err)

    write(os.path.join(tmp, "d32.jsonl"),
          json.dumps({"question": "What is 2 + 3? \u00e9\u00fc \u4f60\u597d",
                      "answer": "5"}, ensure_ascii=False) + "\n")
    code, _, err, rows = run(["--config", cfg(tmp, "c32.yaml"),
                              "--input", os.path.join(tmp, "d32.jsonl")], tmp)
    check(code == 0 and "\u4f60\u597d" in rows[0]["input"]["question"],
          "unicode round-trips", err)

    out_path = os.path.join(tmp, "out.jsonl")
    write(out_path, "STALE CONTENT THAT MUST BE REPLACED\n" * 50)
    code, _, err, rows = run(["--config", cfg(tmp, "c33.yaml"),
                              "--input", os.path.join(tmp, "d32.jsonl")], tmp)
    check(code == 0 and len(rows) == 1, "existing output file is overwritten", err)

    # A row whose prompt needs several fields, with a non-string value.
    multi = BASE_CONFIG.format(api=API, rpm=60, scheme="greedy", temperature=0.0, n=1,
                               evaluation=EVAL_EXACT).replace(
        'user: "{question}"', 'user: "Q{idx}: {question}"')
    write(os.path.join(tmp, "c34.yaml"), multi)
    jsonl(os.path.join(tmp, "d34.jsonl"),
          [{"idx": 7, "question": "What is 2 + 3?", "answer": "5"}])
    code, _, err, rows = run(["--config", os.path.join(tmp, "c34.yaml"),
                              "--input", os.path.join(tmp, "d34.jsonl")], tmp)
    check(code == 0 and rows[0]["result"]["passed"] is True,
          "multi-placeholder template with non-string field", err)

    code, _, err, _ = run(["--config", os.path.join(tmp, "c34.yaml"),
                           "--input", jsonl(os.path.join(tmp, "d35.jsonl"),
                                            [{"idx": 1, "question": "q", "answer": "1"},
                                             {"question": "q", "answer": "1"}])], tmp)
    check(code == 1 and "row 1" in err and "idx" in err,
          "second-row missing field names row 1", err.strip())

    print(f"\n{PASSES} passed, {len(FAILURES)} failed")
    for name in FAILURES:
        print(f"  - {name}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    server = start_mock()
    try:
        code = main()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    sys.exit(code)
