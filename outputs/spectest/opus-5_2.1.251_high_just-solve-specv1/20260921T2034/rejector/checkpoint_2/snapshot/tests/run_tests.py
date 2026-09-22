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

    def requests(self):
        return json.loads(urllib.request.urlopen(self.url + "/requests", timeout=5).read())

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


# --------------------------------------------------------------------------- #
# Part 2: multiple named tasks, llm_judge and script evaluation
# --------------------------------------------------------------------------- #


def write_jsonl(path, rows):
    with open(path, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def multi_cfg(api_url, tasks, defaults=None):
    import yaml
    base = {
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": 60,
        "generation": {"max_tokens": 256},
    }
    base.update(defaults or {})
    return yaml.safe_dump({"defaults": base, "tasks": tasks}, sort_keys=False)


def run_many(config_text, inputs, extra_args=(), mode="explicit", workdir=None,
             output=None):
    """Run a multi-task config; returns (proc, {task: rows}, workdir, outdir)."""
    workdir = workdir or tempfile.mkdtemp()
    config_path = os.path.join(workdir, "multi.yaml")
    with open(config_path, "w") as handle:
        handle.write(config_text)
    outdir = output if output is not None else os.path.join(workdir, "results")

    args = []
    if mode in ("dir", "both"):
        datadir = os.path.join(workdir, "data")
        os.makedirs(datadir, exist_ok=True)
        for name, rows in inputs.items():
            write_jsonl(os.path.join(datadir, "%s.jsonl" % name), rows)
        args += ["--input-dir", datadir]
    if mode in ("explicit", "both"):
        for name, rows in inputs.items():
            path = os.path.join(workdir, "in_%s.jsonl" % name)
            write_jsonl(path, rows)
            args += ["--input", "%s=%s" % (name, path)]

    cmd = [PY, REJECTOR, "run", "--config", config_path, "--output", outdir]
    proc = subprocess.run(cmd + args + list(extra_args), capture_output=True,
                          text=True, timeout=600)
    outputs = {}
    if os.path.isdir(outdir):
        for filename in sorted(os.listdir(outdir)):
            if filename.endswith(".jsonl"):
                with open(os.path.join(outdir, filename)) as handle:
                    outputs[filename[:-6]] = [json.loads(l) for l in handle if l.strip()]
    return proc, outputs, workdir, outdir


GSM_TASK = {
    "prompt": {"system": "TASKA Solve the math problem. Final answer after ####.",
               "user": "{question}"},
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "exact_match", "answer_field": "answer",
                   "extract": "last_number"},
    "output_field": "solution",
}

MMLU_TASK = {
    "prompt": {"system": "TASKB Answer the multiple choice question with a single letter.",
               "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}\nECHO:{reply}"},
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
    "output_field": "choice",
}

MMLU_ROWS = [
    {"question": "What is the capital of France?", "a": "London", "b": "Paris",
     "c": "Berlin", "d": "Madrid", "answer": "B", "reply": "The answer is B) Paris"},
    {"question": "Which is largest?", "a": "one", "b": "two", "c": "three", "d": "four",
     "answer": "D", "reply": "(A)"},
]

JUDGE_TASK = {
    "prompt": {"system": "You are a writing assistant.", "user": "{prompt_text} ECHO:{reply}"},
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only an integer 1-10.",
            "user": "Rate the quality.\n\nResponse:\n{__response__}\n\n"
                    "Criteria: {criteria}\n\nScore:ECHO:{judge_reply}",
        },
        "threshold": 7,
        "extract": "first_number",
    },
    "output_field": "response",
}

JUDGE_ROWS = [
    {"prompt_text": "Write a poem", "reply": "Roses are red", "criteria": "creativity",
     "judge_reply": "8"},
    {"prompt_text": "Write an essay", "reply": "meh", "criteria": "depth",
     "judge_reply": "3"},
]

SCRIPT_TASK = {
    "prompt": {"system": "Write a Python function.", "user": "{problem} ECHO:{reply}"},
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "script", "command_template": "{test_code}",
                   "success_exit_code": 0},
    "output_field": "code",
}


def test_multi_basic():
    print("\n[multi-task: defaults merge, per-task outputs, summary.tasks]")
    tasks = {"gsm8k": dict(GSM_TASK), "mmlu": dict(MMLU_TASK, model="mmlu-model")}
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.2) as server:
        proc, out, work, outdir = run_many(
            multi_cfg(server.url, tasks), {"gsm8k": ROWS, "mmlu": MMLU_ROWS})
        requests = server.requests()

    check("exit 0", proc.returncode == 0, proc.stderr)
    check("one output file per task", sorted(out) == ["gsm8k", "mmlu"], str(sorted(out)))
    check("only task files in output dir",
          sorted(os.listdir(outdir)) == ["gsm8k.jsonl", "mmlu.jsonl"],
          str(sorted(os.listdir(outdir))))
    if sorted(out) != ["gsm8k", "mmlu"]:
        return
    check("gsm8k rows", len(out["gsm8k"]) == 4, str(len(out["gsm8k"])))
    check("mmlu rows", len(out["mmlu"]) == 2, str(len(out["mmlu"])))
    check("gsm8k output field", list(out["gsm8k"][0]["output"]) == ["solution"],
          str(out["gsm8k"][0]["output"]))
    check("mmlu output field", list(out["mmlu"][0]["output"]) == ["choice"],
          str(out["mmlu"][0]["output"]))
    check("gsm8k all passed", all(r["result"]["passed"] is True for r in out["gsm8k"]),
          str([r["result"] for r in out["gsm8k"]]))
    check("letter extraction", out["mmlu"][0]["result"]["extracted_answer"] == "B",
          str(out["mmlu"][0]["result"]))
    check("letter row passes", out["mmlu"][0]["result"]["passed"] is True)
    check("wrong letter fails", out["mmlu"][1]["result"]["passed"] is False
          and out["mmlu"][1]["result"]["extracted_answer"] == "A",
          str(out["mmlu"][1]["result"]))
    check("row order preserved per task",
          [r["input"]["question"] for r in out["gsm8k"]] == [r["question"] for r in ROWS])
    check("defaults model used by gsm8k",
          all(r["meta"]["model"] == "gpt-4" for r in out["gsm8k"]),
          str(out["gsm8k"][0]["meta"]))
    check("task overrides default model",
          all(r["meta"]["model"] == "mmlu-model" for r in out["mmlu"]),
          str(out["mmlu"][0]["meta"]))
    check("defaults generation.max_tokens merged into tasks",
          all(r["max_tokens"] == 256 for r in requests), str(requests[0]))

    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("summary has tasks object", "tasks" in summary, json.dumps(summary))
    check("summary top-level keys",
          set(summary) == {"total", "passed", "failed", "total_prompt_tokens",
                           "total_completion_tokens", "total_api_calls",
                           "elapsed_seconds", "throughput_rpm", "tasks"},
          str(sorted(summary)))
    check("summary totals", summary["total"] == 6 and summary["passed"] == 5
          and summary["failed"] == 1, json.dumps(summary))
    check("summary api calls", summary["total_api_calls"] == 6, json.dumps(summary))
    check("tasks keys", sorted(summary["tasks"]) == ["gsm8k", "mmlu"],
          str(sorted(summary["tasks"])))
    check("per-task keys",
          set(summary["tasks"]["gsm8k"]) == {"total", "passed", "failed", "total_api_calls"},
          str(sorted(summary["tasks"]["gsm8k"])))
    check("per-task gsm8k", summary["tasks"]["gsm8k"] == {"total": 4, "passed": 4,
                                                          "failed": 0, "total_api_calls": 4},
          json.dumps(summary["tasks"]["gsm8k"]))
    check("per-task mmlu", summary["tasks"]["mmlu"] == {"total": 2, "passed": 1,
                                                        "failed": 1, "total_api_calls": 2},
          json.dumps(summary["tasks"]["mmlu"]))
    check("stdout is exactly one JSON object",
          len(proc.stdout.strip().splitlines()) == 1, proc.stdout)


def test_multi_input_dir():
    print("\n[multi-task: --input-dir mode]")
    tasks = {"gsm8k": dict(GSM_TASK), "mmlu": dict(MMLU_TASK)}
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.2) as server:
        proc, out, work, _ = run_many(multi_cfg(server.url, tasks),
                                      {"gsm8k": ROWS, "mmlu": MMLU_ROWS}, mode="dir")
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("both tasks ran from <task>.jsonl", sorted(out) == ["gsm8k", "mmlu"], str(sorted(out)))
    check("rows read", len(out.get("gsm8k", [])) == 4 and len(out.get("mmlu", [])) == 2)

    print("\n[multi-task: --input and --input-dir cannot be combined]")
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks),
                                   {"gsm8k": ROWS, "mmlu": MMLU_ROWS}, mode="both")
    check("combining modes exits 1", proc.returncode == 1, proc.stdout)
    check("combining modes message", "input-dir" in proc.stderr, proc.stderr)
    check("nothing on stdout", proc.stdout.strip() == "", proc.stdout)

    print("\n[multi-task: --input-dir missing a file exits 1]")
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks), {"gsm8k": ROWS}, mode="dir")
    check("missing dir input exits 1", proc.returncode == 1, proc.stdout)
    check("names the task", "mmlu" in proc.stderr, proc.stderr)


def test_multi_task_selection():
    print("\n[multi-task: --task selects a subset]")
    tasks = {"gsm8k": dict(GSM_TASK), "mmlu": dict(MMLU_TASK)}
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.2) as server:
        proc, out, _, outdir = run_many(multi_cfg(server.url, tasks), {"gsm8k": ROWS},
                                        ["--task", "gsm8k"])
    check("exit 0 with only the selected input", proc.returncode == 0, proc.stderr)
    check("only selected output file", sorted(os.listdir(outdir)) == ["gsm8k.jsonl"],
          str(sorted(os.listdir(outdir))))
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("summary lists only the task that ran", list(summary["tasks"]) == ["gsm8k"],
          json.dumps(summary))
    check("summary totals for one task", summary["total"] == 4 and summary["passed"] == 4,
          json.dumps(summary))

    print("\n[multi-task: repeated --task]")
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.2) as server:
        proc, out, _, outdir = run_many(multi_cfg(server.url, tasks),
                                        {"gsm8k": ROWS, "mmlu": MMLU_ROWS},
                                        ["--task", "gsm8k", "--task", "mmlu"])
    check("both selected tasks ran", proc.returncode == 0 and sorted(out) == ["gsm8k", "mmlu"],
          proc.stderr)

    print("\n[multi-task: unselected tasks are ignored for validation]")
    broken = {"gsm8k": dict(GSM_TASK), "broken": {"prompt": {"user": "{nope}"}}}
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.2) as server:
        proc, out, _, outdir = run_many(multi_cfg(server.url, broken), {"gsm8k": ROWS},
                                        ["--task", "gsm8k"])
    check("invalid unselected task does not fail the run", proc.returncode == 0, proc.stderr)
    check("only gsm8k written", sorted(os.listdir(outdir)) == ["gsm8k.jsonl"],
          str(sorted(os.listdir(outdir))))

    print("\n[multi-task: missing input / unknown task names exit 1]")
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks), {"gsm8k": ROWS})
    check("missing input for a selected task exits 1", proc.returncode == 1, proc.stdout)
    check("names the missing task", "mmlu" in proc.stderr, proc.stderr)

    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks),
                                   {"gsm8k": ROWS, "mmlu": MMLU_ROWS},
                                   ["--task", "nope"])
    check("unknown --task exits 1", proc.returncode == 1, proc.stdout)
    check("unknown --task message", "nope" in proc.stderr, proc.stderr)

    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks),
                                   {"gsm8k": ROWS, "nosuch": MMLU_ROWS})
    check("unknown --input task exits 1", proc.returncode == 1, proc.stdout)

    print("\n[multi-task: --output must be a directory]")
    work = tempfile.mkdtemp()
    target = os.path.join(work, "file.jsonl")
    with open(target, "w") as handle:
        handle.write("x\n")
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks),
                                   {"gsm8k": ROWS, "mmlu": MMLU_ROWS}, output=target)
    check("file --output exits 1", proc.returncode == 1, proc.stdout)
    check("directory message", "directory" in proc.stderr, proc.stderr)


def test_single_task_config_unchanged():
    print("\n[single-task config keeps Part 1 CLI and summary]")
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2) as server:
        proc, rows, _ = run_tool(cfg(server.url), ROWS)
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("single-task summary has no tasks object", "tasks" not in summary,
          json.dumps(summary))
    check("single output file written", len(rows) == 4, str(len(rows)))

    print("\n[a top-level 'task' key wins over 'tasks']")
    import yaml
    single = yaml.safe_load(cfg("http://x"))
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.2) as server:
        single["task"]["api_url"] = server.url
        single["tasks"] = {"other": dict(GSM_TASK)}
        proc, rows, _ = run_tool(yaml.safe_dump(single, sort_keys=False), ROWS)
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("treated as single-task", proc.returncode == 0 and "tasks" not in summary,
          proc.stderr + proc.stdout)
    check("single-task rows written", len(rows) == 4, str(len(rows)))


def test_new_extract_methods():
    print("\n[extract: letter, first_number]")
    import rejector
    ev = rejector.extract_value
    check("letter bare", ev("B", "letter") == "B")
    check("letter parens", ev("(A)", "letter") == "A")
    check("letter paren-right", ev("C) Berlin", "letter") == "C")
    check("letter answer prefix", ev("Answer: D", "letter") == "D")
    check("letter in a sentence", ev("The answer is B) Paris", "letter") == "B",
          str(ev("The answer is B) Paris", "letter")))
    check("letter ignores lowercase", ev("the answer is b", "letter") is None,
          str(ev("the answer is b", "letter")))
    check("letter ignores E", ev("E) none", "letter") is None, str(ev("E) none", "letter")))
    check("letter ignores words", ev("A cat sat. Answer: C", "letter") == "C",
          str(ev("A cat sat. Answer: C", "letter")))
    check("letter none", ev("no choice here", "letter") is None)
    check("first_number int", ev("Score: 8 out of 10", "first_number") == "8")
    check("first_number decimal", ev("7.5 then 9", "first_number") == "7.5")
    check("first_number negative", ev("-3 and 4", "first_number") == "-3")
    check("first_number commas", ev("1,234 then 5", "first_number") == "1234")
    check("first_number none", ev("no digits", "first_number") is None)
    check("extract methods advertised",
          set(rejector.EXTRACT_METHODS) == {"last_number", "last_line", "full",
                                            "letter", "first_number"},
          str(rejector.EXTRACT_METHODS))
    check("eval types advertised",
          set(rejector.EVAL_TYPES) == {"exact_match", "contains", "regex",
                                       "llm_judge", "script"},
          str(rejector.EVAL_TYPES))


def test_llm_judge():
    print("\n[llm_judge: score, threshold, judge_meta, api call accounting]")
    tasks = {"review": dict(JUDGE_TASK)}
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.2) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks), {"review": JUDGE_ROWS})
        requests = server.requests()
    check("exit 0", proc.returncode == 0, proc.stderr)
    rows = out.get("review", [])
    check("two rows", len(rows) == 2, str(len(rows)))
    if len(rows) != 2:
        return
    check("result keys include judge_score",
          set(rows[0]["result"]) == {"passed", "extracted_answer", "attempts", "judge_score"},
          str(sorted(rows[0]["result"])))
    check("score 8 passes threshold 7", rows[0]["result"]["passed"] is True,
          str(rows[0]["result"]))
    check("judge_score is 8", rows[0]["result"]["judge_score"] == 8,
          str(rows[0]["result"]))
    check("extracted_answer is the judge text", rows[0]["result"]["extracted_answer"] == "8",
          str(rows[0]["result"]))
    check("output holds the generated response",
          rows[0]["output"] == {"response": "Roses are red"}, str(rows[0]["output"]))
    check("score 3 fails threshold", rows[1]["result"]["passed"] is False
          and rows[1]["result"]["judge_score"] == 3, str(rows[1]["result"]))
    check("failed judge keeps the response (greedy)", rows[1]["output"] is not None,
          str(rows[1]["output"]))

    meta = rows[0]["meta"]
    check("meta is a single object", isinstance(meta, dict), str(type(meta)))
    check("meta has judge_meta", isinstance(meta.get("judge_meta"), dict), str(meta))
    if isinstance(meta.get("judge_meta"), dict):
        check("judge_meta keys",
              set(meta["judge_meta"]) == {"model", "prompt_tokens", "completion_tokens",
                                          "total_tokens", "latency_ms", "finish_reason"},
              str(sorted(meta["judge_meta"])))
        check("judge_meta model defaults to the task model",
              meta["judge_meta"]["model"] == "gpt-4", str(meta["judge_meta"]))
        check("judge_meta finish_reason", meta["judge_meta"]["finish_reason"] == "stop")
        check("judge_meta latency", isinstance(meta["judge_meta"]["latency_ms"], int)
              and meta["judge_meta"]["latency_ms"] >= 150,
              str(meta["judge_meta"]["latency_ms"]))
        check("judge_meta tokens", meta["judge_meta"]["total_tokens"] == 165,
              str(meta["judge_meta"]))

    judge_requests = [r for r in requests
                      if any("Rate the quality" in m["content"] for m in r["messages"])]
    check("judge is a separate API call", len(judge_requests) == 2, str(len(judge_requests)))
    check("judge prompt contains __response__ substitution",
          any("Roses are red" in m["content"]
              for r in judge_requests for m in r["messages"]), str(judge_requests[:1]))
    check("judge prompt renders row fields",
          any("Criteria: creativity" in m["content"]
              for r in judge_requests for m in r["messages"]), str(judge_requests[:1]))
    check("judge system prompt sent",
          all(any(m["role"] == "system" for m in r["messages"]) for r in judge_requests))

    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("judge calls count toward total_api_calls", summary["total_api_calls"] == 4,
          json.dumps(summary))
    check("judge calls count per task", summary["tasks"]["review"]["total_api_calls"] == 4,
          json.dumps(summary))
    check("throughput counts judge calls", summary["throughput_rpm"] > 0, json.dumps(summary))

    print("\n[llm_judge: evaluation.model and --eval-model]")
    judged = dict(JUDGE_TASK)
    judged["evaluation"] = dict(JUDGE_TASK["evaluation"], model="judge-9000")
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"review": judged}),
                                   {"review": JUDGE_ROWS[:1]})
    row = out.get("review", [{}])[0]
    check("evaluation.model used for the judge",
          row["meta"]["judge_meta"]["model"] == "judge-9000", str(row["meta"]))
    check("generation still uses the task model", row["meta"]["model"] == "gpt-4",
          str(row["meta"]))

    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"review": judged}),
                                   {"review": JUDGE_ROWS[:1]}, ["--eval-model", "cli-judge"])
    row = out.get("review", [{}])[0]
    check("--eval-model overrides the judge model",
          row["meta"]["judge_meta"]["model"] == "cli-judge", str(row["meta"]))
    check("--eval-model leaves generation model alone", row["meta"]["model"] == "gpt-4",
          str(row["meta"]))


def test_llm_judge_rejection():
    print("\n[llm_judge + rejection: retry until the judge passes]")
    task = {
        "prompt": {"system": "Write.", "user": "{prompt_text} ECHO:{reply}"},
        "generation": {"scheme": "rejection", "temperature": 0.7, "n": 3},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {"system": "Judge.",
                             "user": "Rate:\n{__response__}\nECHO_SEQ:{judge_seq}"},
            "threshold": 7,
            "extract": "first_number",
        },
        "output_field": "response",
    }
    rows = [{"prompt_text": "Write a poem", "reply": "Roses are red", "judge_seq": "2|9"}]
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"review": task}), {"review": rows})
    check("exit 0", proc.returncode == 0, proc.stderr)
    row = out.get("review", [{}])[0]
    check("attempts == 2", row["result"]["attempts"] == 2, str(row["result"]))
    check("passed on the second judgement", row["result"]["passed"] is True,
          str(row["result"]))
    check("judge_score from the passing attempt", row["result"]["judge_score"] == 9,
          str(row["result"]))
    check("meta is a list of 2", isinstance(row["meta"], list) and len(row["meta"]) == 2,
          str(row["meta"]))
    check("every attempt has judge_meta",
          all(isinstance(m.get("judge_meta"), dict) for m in row["meta"]), str(row["meta"]))
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("4 api calls (2 generate + 2 judge)", summary["total_api_calls"] == 4,
          json.dumps(summary))

    print("\n[llm_judge + rejection: exhausted]")
    rows = [{"prompt_text": "Write a poem", "reply": "meh", "judge_seq": "1"}]
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"review": task}), {"review": rows})
    row = out.get("review", [{}])[0]
    check("attempts == 3", row["result"]["attempts"] == 3, str(row["result"]))
    check("output null", row["output"] is None, str(row["output"]))
    check("passed false", row["result"]["passed"] is False, str(row["result"]))
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("6 api calls", summary["total_api_calls"] == 6, json.dumps(summary))
    check("summary failed == 1", summary["failed"] == 1 and summary["passed"] == 0,
          json.dumps(summary))


def test_script_eval():
    print("\n[script: exit code decides, nested {__response__} substitution]")
    rows = [
        {"problem": "p1", "reply": "here is good code",
         "test_code": "echo '{__response__}' | grep -q 'good code'"},
        {"problem": "p2", "reply": "nothing useful",
         "test_code": "echo '{__response__}' | grep -q 'good code'"},
    ]
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, outdir = run_many(multi_cfg(server.url, {"code_gen": dict(SCRIPT_TASK)}),
                                        {"code_gen": rows})
    check("exit 0", proc.returncode == 0, proc.stderr)
    got = out.get("code_gen", [])
    check("two rows", len(got) == 2, str(len(got)))
    if len(got) != 2:
        return
    check("zero exit passes", got[0]["result"]["passed"] is True, str(got[0]["result"]))
    check("non-zero exit fails", got[1]["result"]["passed"] is False, str(got[1]["result"]))
    check("script extracted_answer is null",
          got[0]["result"]["extracted_answer"] is None, str(got[0]["result"]))
    check("result keys unchanged for script",
          set(got[0]["result"]) == {"passed", "extracted_answer", "attempts"},
          str(sorted(got[0]["result"])))
    check("output holds the response", got[0]["output"] == {"code": "here is good code"},
          str(got[0]["output"]))
    check("no extra API calls for script evaluation",
          json.loads(proc.stdout.strip().splitlines()[-1])["total_api_calls"] == 2,
          proc.stdout)

    print("\n[script: {__response__} directly in command_template]")
    task = dict(SCRIPT_TASK)
    task["evaluation"] = {"type": "script",
                          "command_template": "test \"{__response__}\" = \"{expected}\""}
    rows = [{"problem": "p", "reply": "abc", "expected": "abc"},
            {"problem": "p", "reply": "abc", "expected": "xyz"}]
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"code_gen": task}),
                                   {"code_gen": rows})
    got = out.get("code_gen", [])
    check("template-level __response__ matches", got[0]["result"]["passed"] is True,
          str(got[0]["result"]))
    check("template-level __response__ mismatch fails", got[1]["result"]["passed"] is False,
          str(got[1]["result"]))
    check("success_exit_code defaults to 0", proc.returncode == 0, proc.stderr)

    print("\n[script: custom success_exit_code, output never carries stdout/stderr]")
    task = dict(SCRIPT_TASK)
    task["evaluation"] = {"type": "script", "command_template": "{test_code}",
                          "success_exit_code": 3}
    # printf assembles the markers, so they exist only in the command's output
    rows = [{"problem": "p", "reply": "r",
             "test_code": "printf 'SEC%s\\n' RETOUT; printf 'SEC%s\\n' RETERR 1>&2; exit 3"},
            {"problem": "p", "reply": "r2", "test_code": "exit 0"}]
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, outdir = run_many(multi_cfg(server.url, {"code_gen": task}),
                                        {"code_gen": rows})
    got = out.get("code_gen", [])
    check("exit 3 passes when configured", got[0]["result"]["passed"] is True,
          str(got[0]["result"]))
    check("exit 0 fails when success_exit_code is 3", got[1]["result"]["passed"] is False,
          str(got[1]["result"]))
    with open(os.path.join(outdir, "code_gen.jsonl")) as handle:
        raw = handle.read()
    check("stdout not in output file", "SECRETOUT" not in raw, raw[:200])
    check("stderr not in output file", "SECRETERR" not in raw, raw[:200])
    check("no stdout/stderr fields added", "stdout" not in raw and "stderr" not in raw,
          raw[:200])
    check("row keys unchanged",
          all(set(r) == {"input", "output", "result", "meta"} for r in got),
          str([sorted(r) for r in got]))

    print("\n[script: 10s timeout is a failed evaluation]")
    rows = [{"problem": "p", "reply": "r", "test_code": "sleep 40"}]
    started = time.time()
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"code_gen": dict(SCRIPT_TASK)}),
                                   {"code_gen": rows})
    elapsed = time.time() - started
    got = out.get("code_gen", [])
    check("timeout fails the row", got and got[0]["result"]["passed"] is False,
          str(got))
    check("timed out at ~10s (took %.1fs)" % elapsed, elapsed < 25, "%.1f" % elapsed)
    check("exit 0 after a timeout", proc.returncode == 0, proc.stderr)

    print("\n[script + rejection: retry until the script passes]")
    task = {
        "prompt": {"system": "Write code.", "user": "{problem} ECHO_SEQ:{seq}"},
        "generation": {"scheme": "rejection", "temperature": 0.8, "n": 3},
        "evaluation": {"type": "script", "command_template": "{test_code}",
                       "success_exit_code": 0},
        "output_field": "code",
    }
    rows = [{"problem": "p", "seq": "bad|PASS good",
             "test_code": "echo '{__response__}' | grep -q PASS"}]
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, {"code_gen": task}),
                                   {"code_gen": rows})
    got = out.get("code_gen", [])
    check("attempts == 2", got and got[0]["result"]["attempts"] == 2, str(got))
    check("kept the passing response", got and got[0]["output"] == {"code": "PASS good"},
          str(got))


def test_multi_config_errors():
    print("\n[multi-task config validation]")
    tasks = {"gsm8k": dict(GSM_TASK)}

    def bad(task_cfg, defaults=None, args=(), inputs=None):
        with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
            text = multi_cfg(server.url, task_cfg, defaults)
            return run_many(text, inputs or {"t": ROWS[:1]}, args)

    proc, _, _, _ = bad({"t": {"prompt": {"user": "{question}"},
                               "generation": {"scheme": "greedy"},
                               "output_field": "o",
                               "evaluation": {"type": "llm_judge", "threshold": 7}}})
    check("llm_judge without judge_prompt exits 1", proc.returncode == 1, proc.stdout)
    check("judge_prompt message", "judge_prompt" in proc.stderr, proc.stderr)

    proc, _, _, _ = bad({"t": {"prompt": {"user": "{question}"},
                               "generation": {"scheme": "greedy"},
                               "output_field": "o",
                               "evaluation": {"type": "llm_judge",
                                              "judge_prompt": {"user": "x"}}}})
    check("llm_judge without threshold exits 1", proc.returncode == 1, proc.stdout)
    check("threshold message", "threshold" in proc.stderr, proc.stderr)

    proc, _, _, _ = bad({"t": {"prompt": {"user": "{question}"},
                               "generation": {"scheme": "greedy"},
                               "output_field": "o",
                               "evaluation": {"type": "script"}}})
    check("script without command_template exits 1", proc.returncode == 1, proc.stdout)
    check("command_template message", "command_template" in proc.stderr, proc.stderr)

    proc, _, _, _ = bad({"t": {"generation": {"scheme": "greedy"}, "output_field": "o"}})
    check("task without prompt exits 1", proc.returncode == 1, proc.stdout)

    proc, _, _, _ = bad({"t": {"prompt": {"user": "{question}"},
                               "generation": {"scheme": "greedy"}}})
    check("task without output_field exits 1", proc.returncode == 1, proc.stdout)

    # required fields may come from defaults alone
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        text = multi_cfg(server.url,
                         {"t": {"prompt": {"user": "{question}"}}},
                         defaults={"output_field": "solution",
                                   "generation": {"scheme": "greedy", "max_tokens": 32}})
        proc, out, _, _ = run_many(text, {"t": ROWS[:1]})
    check("defaults can supply required fields", proc.returncode == 0, proc.stderr)
    check("defaults output_field used", out.get("t", [{}])[0]["output"] is not None
          and list(out["t"][0]["output"]) == ["solution"], str(out.get("t")))

    # a row missing a field referenced by a judge prompt fails before any call
    judge = dict(JUDGE_TASK)
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        text = multi_cfg(server.url, {"review": judge})
        proc, out, _, _ = run_many(text, {"review": [{"prompt_text": "x", "reply": "y",
                                                      "judge_reply": "8"}]})
    check("missing judge template field exits 1", proc.returncode == 1, proc.stdout)
    check("names the field", "criteria" in proc.stderr, proc.stderr)

    # empty tasks mapping
    import yaml
    with Server(MOCK_RPM=60, MOCK_LATENCY=0.1) as server:
        text = yaml.safe_dump({"defaults": {"api_url": server.url, "model": "m"},
                               "tasks": {}}, sort_keys=False)
        proc, out, _, _ = run_many(text, {"t": ROWS[:1]})
    check("empty tasks mapping exits 1", proc.returncode == 1, proc.stdout)


def test_multi_empty_input():
    print("\n[multi-task: a selected task with no rows still reports and writes a file]")
    tasks = {"gsm8k": dict(GSM_TASK), "mmlu": dict(MMLU_TASK)}
    with Server(MOCK_RPM=120, MOCK_LATENCY=0.1) as server:
        proc, out, _, outdir = run_many(multi_cfg(server.url, tasks),
                                        {"gsm8k": ROWS, "mmlu": []})
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("empty task file written", os.path.exists(os.path.join(outdir, "mmlu.jsonl")),
          str(os.listdir(outdir)))
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("empty task reported with zeros",
          summary["tasks"]["mmlu"] == {"total": 0, "passed": 0, "failed": 0,
                                       "total_api_calls": 0}, json.dumps(summary))
    check("totals ignore the empty task", summary["total"] == 4, json.dumps(summary))


def test_multi_concurrency():
    print("\n[multi-task: tasks run concurrently and interleave]")
    gsm_rows = [{"question": "What is %d + %d?" % (i, i + 1), "answer": str(2 * i + 1)}
                for i in range(10)]
    mmlu_rows = [dict(MMLU_ROWS[0], question="Q%d" % i) for i in range(10)]
    tasks = {"gsm8k": dict(GSM_TASK), "mmlu": dict(MMLU_TASK)}
    started = time.time()
    with Server(MOCK_RPM=240, MOCK_LATENCY=1.0) as server:
        proc, out, _, _ = run_many(multi_cfg(server.url, tasks, {"rpm": 240}),
                                   {"gsm8k": gsm_rows, "mmlu": mmlu_rows})
        requests = server.requests()
        stats = server.stats()
    elapsed = time.time() - started
    check("exit 0", proc.returncode == 0, proc.stderr)
    check("server saw concurrent requests (max_inflight=%s)" % stats["max_inflight"],
          stats["max_inflight"] > 1, json.dumps(stats))

    labels = []
    for req in requests:
        text = " ".join(m["content"] for m in req["messages"])
        labels.append("A" if "TASKA" in text else "B")
    interleaved = any(labels[i] != labels[i + 1] for i in range(len(labels) - 1)) and \
        len(set(labels)) == 2 and labels.count("A") == 10 and labels.count("B") == 10
    first_b = labels.index("B") if "B" in labels else -1
    last_a = len(labels) - 1 - labels[::-1].index("A") if "A" in labels else -1
    check("requests from both tasks interleave", interleaved and last_a > first_b,
          "".join(labels))
    check("order preserved per task under concurrency",
          [r["input"]["question"] for r in out["gsm8k"]] == [r["question"] for r in gsm_rows]
          and [r["input"]["question"] for r in out["mmlu"]] == [r["question"] for r in mmlu_rows])
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    check("wall clock reflects sharing the server (%.1fs)" % elapsed, elapsed < 20,
          "%.1f" % elapsed)
    check("summary throughput counts every task",
          summary["total_api_calls"] == 20 and summary["throughput_rpm"] > 0,
          json.dumps(summary))


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
        # Part 2
        test_new_extract_methods,
        test_multi_basic,
        test_multi_input_dir,
        test_multi_task_selection,
        test_single_task_config_unchanged,
        test_llm_judge,
        test_llm_judge_rejection,
        test_script_eval,
        test_multi_config_errors,
        test_multi_empty_input,
        test_multi_concurrency,
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
