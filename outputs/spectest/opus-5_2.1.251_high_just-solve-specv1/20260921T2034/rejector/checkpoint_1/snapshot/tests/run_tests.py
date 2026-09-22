#!/usr/bin/env python3
"""End-to-end test suite for rejector.py."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = sys.executable
REJECTOR = os.path.join(ROOT, "rejector.py")
MOCK = os.path.join(ROOT, "tests", "mock_server.py")

PASSES = []
FAILURES = []


def check(name, condition, detail=""):
    if condition:
        PASSES.append(name)
        print("  PASS  %s" % name)
    else:
        FAILURES.append((name, detail))
        print("  FAIL  %s  %s" % (name, detail))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, **env):
        self.port = free_port()
        self.env = dict(os.environ)
        self.env["MOCK_PORT"] = str(self.port)
        for key, value in env.items():
            self.env[key] = str(value)
        self.proc = None

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port

    def __enter__(self):
        self.proc = subprocess.Popen(
            [PY, MOCK], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url + "/stats", timeout=1).read()
                return self
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("mock server did not start")

    def stats(self):
        return json.loads(urllib.request.urlopen(self.url + "/stats", timeout=5).read())

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def run_tool(config_text, rows, extra_args=(), workdir=None):
    workdir = workdir or tempfile.mkdtemp()
    config_path = os.path.join(workdir, "task.yaml")
    input_path = os.path.join(workdir, "in.jsonl")
    output_path = os.path.join(workdir, "out.jsonl")
    with open(config_path, "w") as handle:
        handle.write(config_text)
    with open(input_path, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    cmd = [
        PY, REJECTOR, "run",
        "--config", config_path,
        "--input", input_path,
        "--output", output_path,
    ] + list(extra_args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    out_rows = []
    if os.path.exists(output_path):
        with open(output_path) as handle:
            out_rows = [json.loads(line) for line in handle if line.strip()]
    return proc, out_rows, workdir


def cfg(api_url, scheme="greedy", evaluation=True, **kw):
    generation = {
        "scheme": scheme,
        "max_tokens": kw.get("max_tokens", 256),
    }
    if "temperature" in kw:
        generation["temperature"] = kw["temperature"]
    elif scheme != "greedy":
        generation["temperature"] = 0.8
    if "n" in kw:
        generation["n"] = kw["n"]

    task = {
        "name": "math_solve",
        "api_url": api_url,
        "model": kw.get("model", "gpt-4"),
        "rpm": kw.get("rpm", 60),
        "prompt": {
            "system": "Solve the math problem. Final answer after ####.",
            "user": "{question}",
        },
        "generation": generation,
        "output_field": kw.get("output_field", "solution"),
    }
    if evaluation:
        task["evaluation"] = kw.get(
            "evaluation_cfg",
            {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        )
    import yaml
    return yaml.safe_dump({"task": task}, sort_keys=False)


ROWS = [
    {"question": "What is 2 + 3?", "answer": "5"},
    {"question": "Sarah has 5 apples and buys 3 more. How many does she have?", "answer": "8"},
    {"question": "A train travels 60 miles in 2 hours. What is its speed in mph?", "answer": "30"},
    {"question": "What is 10 + 7?", "answer": "17"},
]


# --------------------------------------------------------------------------- #


def test_greedy_shape():
    print("\n[greedy: output shape + exit code + summary]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=1.0) as server:
        proc, rows, _ = run_tool(cfg(server.url), ROWS)
    check("exit code 0", proc.returncode == 0, proc.stderr)
    check("one output row per input", len(rows) == len(ROWS), str(len(rows)))
    if not rows:
        return
    row = rows[0]
    check("top-level keys", set(row) == {"input", "output", "result", "meta"}, str(sorted(row)))
    check("input unchanged", row["input"] == ROWS[0], str(row["input"]))
    check("output field name", list(row["output"]) == ["solution"], str(row["output"]))
    check("result keys", set(row["result"]) == {"passed", "extracted_answer", "attempts"},
          str(sorted(row["result"])))
    check("greedy attempts == 1", all(r["result"]["attempts"] == 1 for r in rows))
    check("all passed", all(r["result"]["passed"] is True for r in rows),
          str([r["result"] for r in rows]))
    check("extracted answers correct",
          [r["result"]["extracted_answer"] for r in rows] == ["5", "8", "30", "17"],
          str([r["result"]["extracted_answer"] for r in rows]))
    check("meta is a single object", isinstance(row["meta"], dict), str(type(row["meta"])))
    check("meta keys",
          set(row["meta"]) == {"model", "prompt_tokens", "completion_tokens",
                               "total_tokens", "latency_ms", "finish_reason"},
          str(sorted(row["meta"])))
    check("meta.model is configured model", row["meta"]["model"] == "gpt-4")
    check("meta.finish_reason", row["meta"]["finish_reason"] == "stop")
    check("meta.latency_ms plausible", isinstance(row["meta"]["latency_ms"], int)
          and row["meta"]["latency_ms"] >= 900, str(row["meta"]["latency_ms"]))
    check("rows in input order",
          [r["input"]["question"] for r in rows] == [r["question"] for r in ROWS])

    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("summary keys",
          set(summary) == {"total", "passed", "failed", "total_prompt_tokens",
                           "total_completion_tokens", "total_api_calls",
                           "elapsed_seconds", "throughput_rpm"}, str(sorted(summary)))
    check("summary totals", summary["total"] == 4 and summary["passed"] == 4
          and summary["failed"] == 0, json.dumps(summary))
    check("summary tokens", summary["total_prompt_tokens"] == 4 * 45
          and summary["total_completion_tokens"] == 4 * 120, json.dumps(summary))
    check("summary api calls", summary["total_api_calls"] == 4, json.dumps(summary))
    check("stdout is exactly one JSON object",
          len(proc.stdout.strip().splitlines()) == 1, proc.stdout)


def test_greedy_forces_temperature_zero():
    print("\n[greedy: temperature forced to 0.0 even with --temperature]")
    import rejector
    ns = type("NS", (), {})()
    for key in ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n", "concurrency"):
        setattr(ns, key, None)
    ns.temperature = "0.9"
    ns.scheme = "greedy"
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "c.yaml")
    with open(path, "w") as handle:
        handle.write(cfg("http://x", scheme="greedy"))
    conf = rejector.load_config(path, ns)
    check("greedy forces temperature 0.0", conf.temperature == 0.0, str(conf.temperature))
    check("endpoint path", conf.endpoint == "http://x/v1/chat/completions", conf.endpoint)


def test_throughput():
    print("\n[throughput: >= 80% of configured rpm]")
    rows = [{"question": "What is %d + %d?" % (i, i + 1), "answer": str(2 * i + 1)}
            for i in range(60)]
    with Server(MOCK_RPM=120, MOCK_LATENCY=2.0) as server:
        proc, out, _ = run_tool(cfg(server.url, rpm=120), rows)
        stats = server.stats()
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("throughput >= 80%% of rpm (got %.1f of 120)" % summary["throughput_rpm"],
          summary["throughput_rpm"] >= 0.8 * 120, json.dumps(summary))
    check("server saw concurrent requests (max_inflight=%d)" % stats["max_inflight"],
          stats["max_inflight"] > 1, json.dumps(stats))
    check("all 60 rows passed", sum(1 for r in out if r["result"]["passed"]) == 60)
    check("order preserved under concurrency",
          [r["input"]["question"] for r in out] == [r["question"] for r in rows])


def test_rejection_success():
    print("\n[rejection: first two attempts fail, third passes]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.3, MOCK_MODE="fail_first_k", MOCK_K=2) as server:
        proc, rows, _ = run_tool(cfg(server.url, scheme="rejection", n=3), ROWS)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("attempts == 3", all(r["result"]["attempts"] == 3 for r in rows),
          str([r["result"]["attempts"] for r in rows]))
    check("passed true", all(r["result"]["passed"] is True for r in rows))
    check("meta is list of 3", all(isinstance(r["meta"], list) and len(r["meta"]) == 3
                                   for r in rows))
    check("output kept from passing attempt",
          rows[0]["output"]["solution"].endswith("#### 5"), rows[0]["output"]["solution"])
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("api calls == 12", summary["total_api_calls"] == 12, json.dumps(summary))
    check("summary passed == 4", summary["passed"] == 4, json.dumps(summary))


def test_rejection_exhausted():
    print("\n[rejection: all attempts fail]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2, MOCK_MODE="wrong") as server:
        proc, rows, _ = run_tool(cfg(server.url, scheme="rejection", n=5), ROWS[:2])
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("output null", all(r["output"] is None for r in rows))
    check("passed false", all(r["result"]["passed"] is False for r in rows))
    check("extracted null", all(r["result"]["extracted_answer"] is None for r in rows))
    check("attempts == 5", all(r["result"]["attempts"] == 5 for r in rows))
    check("meta list of 5", all(isinstance(r["meta"], list) and len(r["meta"]) == 5
                                for r in rows))
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("summary failed == 2", summary["failed"] == 2 and summary["passed"] == 0,
          json.dumps(summary))
    check("api calls == 10", summary["total_api_calls"] == 10, json.dumps(summary))


def test_rejection_single_attempt_meta():
    print("\n[rejection: one attempt -> meta is a single object]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2) as server:
        proc, rows, _ = run_tool(cfg(server.url, scheme="rejection", n=3), ROWS[:2])
    check("attempts == 1", all(r["result"]["attempts"] == 1 for r in rows))
    check("meta single object", all(isinstance(r["meta"], dict) for r in rows))


def test_retry_5xx():
    print("\n[retry: two 5xx then success]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2, MOCK_MODE="flaky5xx", MOCK_5XX_N=2) as server:
        proc, rows, _ = run_tool(cfg(server.url), ROWS[:2])
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("rows succeeded", all(r["output"] is not None for r in rows),
          str([r["output"] for r in rows]))
    check("logical attempts still 1", all(r["result"]["attempts"] == 1 for r in rows),
          str([r["result"]["attempts"] for r in rows]))
    check("retries counted in api calls (6)", summary["total_api_calls"] == 6,
          json.dumps(summary))
    check("meta still single object", all(isinstance(r["meta"], dict) for r in rows))


def test_retry_exhausted():
    print("\n[retry: 5xx forever -> row failed, 3 calls, continues]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1, MOCK_MODE="always5xx") as server:
        proc, rows, _ = run_tool(cfg(server.url), ROWS[:2])
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("exit 0 (continues past failures)", proc.returncode == 0, proc.stderr)
    check("all rows emitted", len(rows) == 2, str(len(rows)))
    check("output null", all(r["output"] is None for r in rows))
    check("passed false", all(r["result"]["passed"] is False for r in rows))
    check("3 requests per row", summary["total_api_calls"] == 6, json.dumps(summary))
    check("counted as failed", summary["failed"] == 2 and summary["passed"] == 0,
          json.dumps(summary))
    check("attempts == 1 for greedy", all(r["result"]["attempts"] == 1 for r in rows),
          str([r["result"]["attempts"] for r in rows]))


def test_no_evaluation():
    print("\n[no evaluation configured -> passed is null]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2) as server:
        proc, rows, _ = run_tool(cfg(server.url, evaluation=False), ROWS)
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("passed is null", all(r["result"]["passed"] is None for r in rows))
    check("extracted is null", all(r["result"]["extracted_answer"] is None for r in rows))
    check("summary counts API successes as passed", summary["passed"] == 4
          and summary["failed"] == 0, json.dumps(summary))


def test_sample_scheme():
    print("\n[sample scheme]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2) as server:
        proc, rows, _ = run_tool(cfg(server.url, scheme="sample", temperature=0.7), ROWS)
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("attempts == 1", all(r["result"]["attempts"] == 1 for r in rows))
    check("meta single object", all(isinstance(r["meta"], dict) for r in rows))

    print("\n[sample: failing evaluation keeps the response, passed=false]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2, MOCK_MODE="wrong") as server:
        proc, rows, _ = run_tool(cfg(server.url, scheme="sample", temperature=0.7), ROWS[:2])
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("passed false", all(r["result"]["passed"] is False for r in rows))
    check("output retained", all(r["output"] is not None for r in rows))
    check("summary failed == 2", summary["failed"] == 2, json.dumps(summary))


def test_contains_and_regex():
    print("\n[evaluation types: contains, regex]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2) as server:
        proc, rows, _ = run_tool(
            cfg(server.url, evaluation_cfg={"type": "contains", "answer_field": "answer"}),
            ROWS)
        check("contains passes", all(r["result"]["passed"] is True for r in rows),
              str([r["result"] for r in rows]))
        check("contains extracted", rows[0]["result"]["extracted_answer"] == "5",
              str(rows[0]["result"]))

        proc, rows, _ = run_tool(
            cfg(server.url, evaluation_cfg={"type": "regex", "pattern": r"####\s*(\d+)"}),
            ROWS)
        check("regex passes", all(r["result"]["passed"] is True for r in rows))
        check("regex extracts group 1", rows[0]["result"]["extracted_answer"] == "5",
              str(rows[0]["result"]))

        proc, rows, _ = run_tool(
            cfg(server.url, evaluation_cfg={"type": "regex", "pattern": r"NOPE\d+"}),
            ROWS[:1])
        check("regex non-match fails", rows[0]["result"]["passed"] is False)
        check("regex non-match extracted null",
              rows[0]["result"]["extracted_answer"] is None)

        proc, rows, _ = run_tool(
            cfg(server.url, evaluation_cfg={"type": "exact_match", "answer_field": "answer",
                                            "extract": "last_line"}),
            ROWS[:1])
        check("last_line extract", rows[0]["result"]["extracted_answer"] == "#### 5",
              str(rows[0]["result"]))
        check("last_line exact_match fails vs '5'", rows[0]["result"]["passed"] is False)


def test_extract_units():
    print("\n[extract + comparison units]")
    import rejector
    check("last_number basic", rejector.extract_value("a 1 b 42", "last_number") == "42")
    check("last_number decimal", rejector.extract_value("#### 3.5", "last_number") == "3.5")
    check("last_number commas", rejector.extract_value("#### 1,234", "last_number") == "1234")
    check("last_number negative", rejector.extract_value("x = -7", "last_number") == "-7")
    check("last_number trailing period",
          rejector.extract_value("The answer is 8.", "last_number") == "8")
    check("last_number none", rejector.extract_value("no digits", "last_number") is None)
    check("last_line", rejector.extract_value("a\nb\n\n  \n", "last_line") == "b")
    check("last_line none", rejector.extract_value("\n \n", "last_line") is None)
    check("full", rejector.extract_value("x\ny", "full") == "x\ny")
    check("match numeric", rejector.answers_match("8.0", "8"))
    check("match commas", rejector.answers_match("1000", "1,000"))
    check("match text", rejector.answers_match(" Paris ", "paris"))
    check("no match", not rejector.answers_match("9", "8"))


def test_missing_field():
    print("\n[input error: missing template field]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        proc, rows, work = run_tool(cfg(server.url), [{"text": "hello"}])
    check("exit code 1", proc.returncode == 1, str(proc.returncode))
    check("stderr names row 0", "row 0" in proc.stderr, proc.stderr)
    check("stderr names question", "question" in proc.stderr, proc.stderr)
    check("nothing on stdout", proc.stdout.strip() == "", proc.stdout)

    print("\n[input error: row missing answer_field]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        proc, rows, _ = run_tool(cfg(server.url),
                                 [ROWS[0], {"question": "What is 1 + 1?"}])
    check("exit code 1", proc.returncode == 1, str(proc.returncode))
    check("stderr names row 1 and answer", "row 1" in proc.stderr and "answer" in proc.stderr,
          proc.stderr)


def test_config_errors():
    print("\n[config validation errors]")
    import yaml

    def bad(task, args=()):
        with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
            task.setdefault("api_url", server.url)
            text = yaml.safe_dump({"task": task}, sort_keys=False)
            return run_tool(text, ROWS[:1], args)

    base_prompt = {"system": "s", "user": "{question}"}

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "nonsense"}, "output_field": "solution"})
    check("bad scheme exits 1", proc.returncode == 1, proc.stdout)
    check("bad scheme message", "scheme" in proc.stderr, proc.stderr)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "sample", "temperature": 0.0},
                      "output_field": "solution"})
    check("sample temp 0 exits 1", proc.returncode == 1)
    check("sample temp message", "temperature" in proc.stderr, proc.stderr)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "rejection", "temperature": 0.7, "n": 3},
                      "output_field": "solution"})
    check("rejection without evaluation exits 1", proc.returncode == 1)
    check("rejection eval message", "evaluation" in proc.stderr, proc.stderr)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"},
                      "evaluation": {"type": "exact_match"}, "output_field": "solution"})
    check("exact_match without answer_field exits 1", proc.returncode == 1)
    check("answer_field message", "answer_field" in proc.stderr, proc.stderr)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"},
                      "evaluation": {"type": "contains"}, "output_field": "solution"})
    check("contains without answer_field exits 1", proc.returncode == 1)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"},
                      "evaluation": {"type": "regex"}, "output_field": "solution"})
    check("regex without pattern exits 1", proc.returncode == 1)
    check("pattern message", "pattern" in proc.stderr, proc.stderr)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"},
                      "evaluation": {"type": "regex", "pattern": "[unclosed"},
                      "output_field": "solution"})
    check("invalid regex exits 1", proc.returncode == 1, proc.stderr)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"},
                      "evaluation": {"type": "bogus", "answer_field": "answer"},
                      "output_field": "solution"})
    check("bad evaluation type exits 1", proc.returncode == 1)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"},
                      "evaluation": {"type": "exact_match", "answer_field": "answer",
                                     "extract": "bogus"},
                      "output_field": "solution"})
    check("bad extract method exits 1", proc.returncode == 1)

    proc, _, _ = bad({"model": "m", "generation": {"scheme": "greedy"},
                      "output_field": "solution"})
    check("missing prompt exits 1", proc.returncode == 1)

    proc, _, _ = bad({"prompt": base_prompt, "generation": {"scheme": "greedy"},
                      "output_field": "solution"})
    check("missing model exits 1", proc.returncode == 1)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "greedy"}})
    check("missing output_field exits 1", proc.returncode == 1)

    proc, _, _ = bad({"model": "m", "prompt": base_prompt,
                      "generation": {"scheme": "rejection", "temperature": 0.5, "n": 0},
                      "evaluation": {"type": "exact_match", "answer_field": "answer"},
                      "output_field": "solution"})
    check("n=0 exits 1", proc.returncode == 1)

    # regex needs pattern but not answer_field
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        proc, rows, _ = run_tool(
            cfg(server.url, evaluation_cfg={"type": "regex", "pattern": "####"}), ROWS[:1])
    check("regex without answer_field is valid", proc.returncode == 0, proc.stderr)

    # missing files
    tmp = tempfile.mkdtemp()
    proc = subprocess.run([PY, REJECTOR, "run", "--config", os.path.join(tmp, "nope.yaml"),
                           "--input", os.path.join(tmp, "nope.jsonl"),
                           "--output", os.path.join(tmp, "o.jsonl")],
                          capture_output=True, text=True)
    check("missing config exits 1", proc.returncode == 1, proc.stderr)

    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        conf = os.path.join(tmp, "c.yaml")
        with open(conf, "w") as handle:
            handle.write(cfg(server.url))
        proc = subprocess.run([PY, REJECTOR, "run", "--config", conf,
                               "--input", os.path.join(tmp, "nope.jsonl"),
                               "--output", os.path.join(tmp, "o.jsonl")],
                              capture_output=True, text=True)
    check("missing input exits 1", proc.returncode == 1, proc.stderr)

    # malformed jsonl
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        work = tempfile.mkdtemp()
        conf = os.path.join(work, "c.yaml")
        inp = os.path.join(work, "i.jsonl")
        with open(conf, "w") as handle:
            handle.write(cfg(server.url))
        with open(inp, "w") as handle:
            handle.write('{"question": "a", "answer": "1"}\nnot json\n')
        proc = subprocess.run([PY, REJECTOR, "run", "--config", conf, "--input", inp,
                               "--output", os.path.join(work, "o.jsonl")],
                              capture_output=True, text=True)
    check("malformed jsonl exits 1", proc.returncode == 1, proc.stderr)

    # missing required CLI flag
    proc = subprocess.run([PY, REJECTOR, "run", "--config", "x"], capture_output=True, text=True)
    check("missing CLI flags exit 1", proc.returncode == 1, str(proc.returncode))


def test_cli_overrides():
    print("\n[CLI overrides]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2, MOCK_MODE="fail_first_k", MOCK_K=1) as server:
        # config says greedy/no-n; override to rejection with n=3
        base = cfg("http://127.0.0.1:1", scheme="greedy")
        proc, rows, _ = run_tool(base, ROWS[:2], [
            "--api-url", server.url,
            "--model", "override-model",
            "--scheme", "rejection",
            "--temperature", "0.9",
            "--n", "3",
            "--rpm", "30",
            "--max-tokens", "64",
        ])
    check("exit 0 with overrides", proc.returncode == 0, proc.stderr)
    check("scheme override applied (attempts 2)",
          all(r["result"]["attempts"] == 2 for r in rows),
          str([r["result"]["attempts"] for r in rows]))
    check("model override in meta",
          all(m["model"] == "override-model" for r in rows for m in r["meta"]),
          str(rows[0]["meta"]))

    print("\n[output file is overwritten]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        work = tempfile.mkdtemp()
        out = os.path.join(work, "out.jsonl")
        with open(out, "w") as handle:
            handle.write("STALE\nSTALE\nSTALE\n")
        run_tool(cfg(server.url), ROWS[:1], workdir=work)
        with open(out) as handle:
            content = handle.read()
    check("stale content gone", "STALE" not in content, content[:80])
    check("one line written", len(content.strip().splitlines()) == 1, content[:200])


def test_request_payload():
    print("\n[request payload shape]")
    import asyncio
    from aiohttp import web

    captured = []

    async def handler(request):
        captured.append(await request.json())
        return web.json_response({
            "id": "chatcmpl-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "#### 5"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        })

    port = free_port()
    loop = asyncio.new_event_loop()

    async def serve():
        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        return runner

    import threading
    runner_box = {}

    def run_loop():
        asyncio.set_event_loop(loop)
        runner_box["r"] = loop.run_until_complete(serve())
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    time.sleep(1.0)

    proc, rows, _ = run_tool(cfg("http://127.0.0.1:%d" % port, max_tokens=256), ROWS[:1])
    loop.call_soon_threadsafe(loop.stop)
    time.sleep(0.3)

    check("one request captured", len(captured) == 1, str(len(captured)))
    if captured:
        body = captured[0]
        check("payload keys",
              set(body) == {"model", "messages", "temperature", "max_tokens"},
              str(sorted(body)))
        check("model", body["model"] == "gpt-4")
        check("temperature 0.0 for greedy", body["temperature"] == 0.0, str(body["temperature"]))
        check("max_tokens", body["max_tokens"] == 256, str(body["max_tokens"]))
        check("messages roles", [m["role"] for m in body["messages"]] == ["system", "user"],
              str(body["messages"]))
        check("user template rendered",
              body["messages"][1]["content"] == "What is 2 + 3?",
              body["messages"][1]["content"])
        check("system rendered",
              body["messages"][0]["content"] == "Solve the math problem. Final answer after ####.",
              body["messages"][0]["content"])


def test_empty_input():
    print("\n[empty input file]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        proc, rows, _ = run_tool(cfg(server.url), [])
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("no output rows", rows == [])
    summary = json.loads(proc.stdout.strip())
    check("zeroed summary", summary["total"] == 0 and summary["total_api_calls"] == 0
          and summary["elapsed_seconds"] == 0.0 and summary["throughput_rpm"] == 0.0,
          json.dumps(summary))


def test_braces_in_prompt():
    print("\n[prompt containing JSON braces is not treated as a placeholder]")
    import rejector
    text = rejector.render_template('Reply {"a": 1} for {question}', {"question": "q"}, 0)
    check("json braces preserved", text == 'Reply {"a": 1} for q', text)


def main():
    tests = [
        test_greedy_shape,
        test_greedy_forces_temperature_zero,
        test_request_payload,
        test_sample_scheme,
        test_rejection_success,
        test_rejection_exhausted,
        test_rejection_single_attempt_meta,
        test_retry_5xx,
        test_retry_exhausted,
        test_no_evaluation,
        test_contains_and_regex,
        test_extract_units,
        test_braces_in_prompt,
        test_missing_field,
        test_config_errors,
        test_cli_overrides,
        test_empty_input,
        test_throughput,
    ]
    for test in tests:
        test()

    print("\n%s" % ("=" * 60))
    print("PASSED: %d   FAILED: %d" % (len(PASSES), len(FAILURES)))
    for name, detail in FAILURES:
        print("  FAILED: %s  %s" % (name, detail))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
