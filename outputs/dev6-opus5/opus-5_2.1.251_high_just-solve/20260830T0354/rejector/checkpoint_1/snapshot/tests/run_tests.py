#!/usr/bin/env python3
"""End-to-end test-suite for rejector.py against the mock server."""
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
PY = os.path.join(ROOT, ".venv", "bin", "python")
CLI = os.path.join(ROOT, "rejector.py")
MOCK = os.path.join(ROOT, "tests", "mock_server.py")

FAILURES = []
PASSES = []


def check(name, cond, detail=""):
    if cond:
        PASSES.append(name)
        print("  PASS  %s" % name)
    else:
        FAILURES.append((name, detail))
        print("  FAIL  %s %s" % (name, detail))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    def __init__(self, **kwargs):
        self.port = free_port()
        args = [PY, MOCK, "--port", str(self.port)]
        for key, value in kwargs.items():
            flag = "--" + key.replace("_", "-")
            if value is True:
                args.append(flag)
            elif value is not False and value is not None:
                args += [flag, str(value)]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.url = "http://127.0.0.1:%d" % self.port
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url + "/stats", timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("mock server did not start")

    def stats(self):
        return json.loads(urllib.request.urlopen(self.url + "/stats", timeout=5).read())

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


TMP = tempfile.mkdtemp(prefix="rejector-tests-")


def write(name, text):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def write_jsonl(name, rows):
    return write(name, "".join(json.dumps(r) + "\n" for r in rows))


def run_cli(config, inp, out=None, extra=()):
    out = out or os.path.join(TMP, "out-%d.jsonl" % time.time_ns())
    cmd = [PY, CLI, "run", "--config", config, "--input", inp, "--output", out] + list(extra)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    rows = []
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    summary = None
    if proc.stdout.strip():
        try:
            summary = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            summary = None
    return proc, rows, summary, out


def cfg_yaml(url, **kw):
    scheme = kw.get("scheme", "greedy")
    lines = [
        "task:",
        '  name: "t"',
        '  api_url: "%s"' % url,
        '  model: "%s"' % kw.get("model", "gpt-4"),
        "  rpm: %s" % kw.get("rpm", 60),
        "  prompt:",
        '    system: "Solve it."',
        '    user: "%s"' % kw.get("user_prompt", "{question}"),
        "  generation:",
        '    scheme: "%s"' % scheme,
        "    temperature: %s" % kw.get("temperature", 0.0),
        "    max_tokens: %s" % kw.get("max_tokens", 256),
        "    n: %s" % kw.get("n", 1),
    ]
    if kw.get("evaluation", True):
        lines += [
            "  evaluation:",
            '    type: "%s"' % kw.get("eval_type", "exact_match"),
        ]
        if kw.get("answer_field", "answer") is not None:
            lines.append('    answer_field: "%s"' % kw.get("answer_field", "answer"))
        if kw.get("pattern"):
            lines.append('    pattern: "%s"' % kw["pattern"])
        if kw.get("extract", "last_number"):
            lines.append('    extract: "%s"' % kw.get("extract", "last_number"))
    lines.append('  output_field: "%s"' % kw.get("output_field", "solution"))
    return "\n".join(lines) + "\n"


ROWS10 = [{"question": "What is %d?" % i, "answer": "42" if i % 2 == 0 else "7"}
          for i in range(10)]


def test_greedy_basic():
    print("\n[greedy basic]")
    with Server(workers=4, delay=0.2) as srv:
        cfg = write("greedy.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("d10.jsonl", ROWS10)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit code 0", proc.returncode == 0, proc.stderr)
        check("row count", len(rows) == 10, str(len(rows)))
        check("order preserved", [r["input"] for r in rows] == ROWS10)
        r0 = rows[0]
        check("output field name", r0["output"] == {"solution": "Let me solve it.\nThe result is 42\n#### 42"}, json.dumps(r0["output"]))
        check("passed true", r0["result"]["passed"] is True)
        check("extracted", r0["result"]["extracted_answer"] == "42")
        check("attempts 1", r0["result"]["attempts"] == 1)
        check("meta is dict", isinstance(r0["meta"], dict))
        check("meta keys", set(r0["meta"]) == {"model", "prompt_tokens", "completion_tokens",
                                              "total_tokens", "latency_ms", "finish_reason"},
              str(sorted(r0["meta"])))
        check("meta model", r0["meta"]["model"] == "gpt-4")
        check("meta latency int", isinstance(r0["meta"]["latency_ms"], int))
        check("meta finish_reason", r0["meta"]["finish_reason"] == "stop")
        check("row keys", list(r0) == ["input", "output", "result", "meta"], str(list(r0)))
        check("result keys", list(r0["result"]) == ["passed", "extracted_answer", "attempts"])
        check("failing row passed=false", rows[1]["result"]["passed"] is False)
        check("failing row keeps output", rows[1]["output"] is not None)
        check("summary keys", list(summary) == ["total", "passed", "failed",
                                                "total_prompt_tokens", "total_completion_tokens",
                                                "total_api_calls", "elapsed_seconds",
                                                "throughput_rpm"], str(list(summary)))
        check("summary total", summary["total"] == 10)
        check("summary passed", summary["passed"] == 5, str(summary))
        check("summary failed", summary["failed"] == 5, str(summary))
        check("summary tokens", summary["total_prompt_tokens"] == 100 and
              summary["total_completion_tokens"] == 50, str(summary))
        check("summary api calls", summary["total_api_calls"] == 10, str(summary))
        payload = srv.stats()["payloads"][0]
        check("payload keys", set(payload) == {"model", "messages", "temperature", "max_tokens"},
              str(sorted(payload)))
        check("payload temperature 0", payload["temperature"] == 0.0)
        check("payload max_tokens", payload["max_tokens"] == 256)
        check("payload messages", payload["messages"][0] == {"role": "system", "content": "Solve it."}
              and payload["messages"][1]["role"] == "user")
        check("user prompt rendered", payload["messages"][1]["content"].startswith("What is "))


def test_greedy_forces_temperature():
    print("\n[greedy forces temperature 0]")
    with Server(workers=4, delay=0.05) as srv:
        cfg = write("greedy_t.yaml", cfg_yaml(srv.url, temperature=0.9))
        inp = write_jsonl("d1.jsonl", ROWS10[:1])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("temperature forced to 0.0", srv.stats()["payloads"][0]["temperature"] == 0.0)


def test_no_evaluation():
    print("\n[no evaluation configured]")
    with Server(workers=4, delay=0.05) as srv:
        cfg = write("noeval.yaml", cfg_yaml(srv.url, evaluation=False))
        inp = write_jsonl("d10b.jsonl", ROWS10)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("passed is null", all(r["result"]["passed"] is None for r in rows))
        check("extracted is null", all(r["result"]["extracted_answer"] is None for r in rows))
        check("summary counts all passed", summary["passed"] == 10 and summary["failed"] == 0,
              str(summary))


def test_eval_variants():
    print("\n[evaluation variants]")
    with Server(workers=4, delay=0.05) as srv:
        rows_in = [{"question": "q", "answer": "The result is 42"}]
        inp = write_jsonl("dv.jsonl", rows_in)
        cfg = write("contains.yaml", cfg_yaml(srv.url, eval_type="contains", extract="last_line"))
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("contains passes", rows[0]["result"]["passed"] is True, json.dumps(rows[0]["result"]))
        check("contains extracted uses extract method",
              rows[0]["result"]["extracted_answer"] == "#### 42", str(rows[0]["result"]))

        cfg = write("contains_fail.yaml", cfg_yaml(srv.url, eval_type="contains", extract="full"))
        proc, rows, _, _ = run_cli(cfg, write_jsonl("dv2.jsonl", [{"question": "q", "answer": "nope"}]))
        check("contains fails", rows[0]["result"]["passed"] is False)
        check("full extract", rows[0]["result"]["extracted_answer"] ==
              "Let me solve it.\nThe result is 42\n#### 42")

        cfg = write("regex.yaml", cfg_yaml(srv.url, eval_type="regex", answer_field=None,
                                           pattern="####\\\\s*42", extract="last_number"))
        proc, rows, _, _ = run_cli(cfg, write_jsonl("dv3.jsonl", [{"question": "q"}]))
        check("regex passes without answer_field", rows[0]["result"]["passed"] is True,
              proc.stderr + json.dumps(rows[0]["result"]) if rows else proc.stderr)

        cfg = write("regex_fail.yaml", cfg_yaml(srv.url, eval_type="regex", answer_field=None,
                                                pattern="#### 999", extract="full"))
        proc, rows, _, _ = run_cli(cfg, write_jsonl("dv4.jsonl", [{"question": "q"}]))
        check("regex fails", rows[0]["result"]["passed"] is False)


def test_extract_last_number_forms():
    print("\n[extract last_number]")
    sys.path.insert(0, ROOT)
    import rejector
    cases = [
        ("2 + 3 = 5\n#### 5", "5"),
        ("The answer is 8.", "8"),
        ("value: -12.5 done", "-12.5"),
        ("total 1,234 items", "1234"),
        ("no digits here", None),
        ("first 1 then 2 then 3", "3"),
    ]
    for text, expected in cases:
        got = rejector.extract_answer(text, "last_number")
        check("last_number %r" % text[:22], got == expected, "got %r want %r" % (got, expected))
    check("last_line", rejector.extract_answer("a\nb\n\n  \n", "last_line") == "b")
    check("full", rejector.extract_answer("  hi  ", "full") == "hi")
    check("numeric match 8 vs 8.0", rejector.values_match("8", "8.0"))
    check("string match", rejector.values_match("abc", "abc"))
    check("mismatch", not rejector.values_match("8", "9"))
    check("none mismatch", not rejector.values_match(None, "9"))


def test_rejection_success_on_third():
    print("\n[rejection: passes on 3rd attempt]")
    with Server(workers=8, delay=0.05, wrong_attempts=2) as srv:
        cfg = write("rej.yaml", cfg_yaml(srv.url, scheme="rejection", temperature=0.8, n=5))
        inp = write_jsonl("rej.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        r = rows[0]
        check("attempts 3", r["result"]["attempts"] == 3, json.dumps(r["result"]))
        check("passed true", r["result"]["passed"] is True)
        check("meta is list of 3", isinstance(r["meta"], list) and len(r["meta"]) == 3,
              str(r["meta"]))
        check("kept passing response", "#### 42" in r["output"]["solution"])
        check("api calls 3", summary["total_api_calls"] == 3, str(summary))
        check("summary passed 1", summary["passed"] == 1 and summary["failed"] == 0)


def test_rejection_first_try():
    print("\n[rejection: passes first attempt -> single meta dict]")
    with Server(workers=8, delay=0.05) as srv:
        cfg = write("rej1.yaml", cfg_yaml(srv.url, scheme="rejection", temperature=0.8, n=5))
        inp = write_jsonl("rej1.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("attempts 1", rows[0]["result"]["attempts"] == 1)
        check("meta is dict", isinstance(rows[0]["meta"], dict), str(type(rows[0]["meta"])))
        check("api calls 1", summary["total_api_calls"] == 1)


def test_rejection_exhausted():
    print("\n[rejection: all attempts fail]")
    with Server(workers=8, delay=0.05, wrong_attempts=99) as srv:
        cfg = write("rej2.yaml", cfg_yaml(srv.url, scheme="rejection", temperature=0.8, n=5))
        inp = write_jsonl("rej2.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        r = rows[0]
        check("output null", r["output"] is None, json.dumps(r["output"]))
        check("passed false", r["result"]["passed"] is False)
        check("extracted null", r["result"]["extracted_answer"] is None)
        check("attempts n", r["result"]["attempts"] == 5, str(r["result"]))
        check("meta list of 5", isinstance(r["meta"], list) and len(r["meta"]) == 5)
        check("api calls 5", summary["total_api_calls"] == 5)
        check("summary failed", summary["failed"] == 1 and summary["passed"] == 0)


def test_rejection_temperature_sent():
    print("\n[rejection sends configured temperature]")
    with Server(workers=8, delay=0.05) as srv:
        cfg = write("rej3.yaml", cfg_yaml(srv.url, scheme="rejection", temperature=0.7, n=3))
        inp = write_jsonl("rej3.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        payload = srv.stats()["payloads"][0]
        check("temperature 0.7", payload["temperature"] == 0.7, str(payload))
        check("no n in payload", "n" not in payload, str(payload))


def test_retries_5xx_permanent():
    print("\n[5xx: exhausted retries]")
    with Server(workers=8, delay=0.0, always_500=True) as srv:
        cfg = write("r500.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("r500.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        r = rows[0]
        check("output null", r["output"] is None)
        check("attempts stays 1", r["result"]["attempts"] == 1, str(r["result"]))
        check("api calls = 4 (1 + 3 retries)", summary["total_api_calls"] == 4, str(summary))
        check("counted failed", summary["failed"] == 1 and summary["passed"] == 0, str(summary))
        check("meta is dict", isinstance(r["meta"], dict))


def test_retries_5xx_transient():
    print("\n[5xx: transient then success]")
    with Server(workers=8, delay=0.0, fail_prompt_calls=2) as srv:
        cfg = write("r500b.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("r500b.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        r = rows[0]
        check("succeeded after retries", r["output"] is not None, json.dumps(r))
        check("attempts still 1", r["result"]["attempts"] == 1)
        check("api calls 3", summary["total_api_calls"] == 3, str(summary))
        check("passed", summary["passed"] == 1)


def test_4xx_no_retry():
    print("\n[4xx is not retried]")
    with Server(workers=8, delay=0.0, always_400=True) as srv:
        cfg = write("r400.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("r400.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("output null", rows[0]["output"] is None)
        check("api calls 1", summary["total_api_calls"] == 1, str(summary))
        check("failed 1", summary["failed"] == 1)


def test_rejection_api_failure():
    print("\n[rejection with hard API failure]")
    with Server(workers=8, delay=0.0, always_500=True) as srv:
        cfg = write("rej4.yaml", cfg_yaml(srv.url, scheme="rejection", temperature=0.8, n=3))
        inp = write_jsonl("rej4.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("output null", rows[0]["output"] is None)
        check("passed false", rows[0]["result"]["passed"] is False)
        check("api calls 4", summary["total_api_calls"] == 4, str(summary))
        check("failed", summary["failed"] == 1)


def test_missing_prompt_field():
    print("\n[missing template field]")
    with Server(workers=8, delay=0.0) as srv:
        cfg = write("mf.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("mf.jsonl", [{"text": "hello"}])
        out = os.path.join(TMP, "mf-out.jsonl")
        proc, rows, summary, _ = run_cli(cfg, inp, out)
        check("exit 1", proc.returncode == 1, str(proc.returncode))
        check("stderr names row 0", "0" in proc.stderr and "question" in proc.stderr, proc.stderr)
        check("nothing on stdout", proc.stdout.strip() == "", proc.stdout)
        check("no api calls", srv.stats()["calls"] == 0)


def test_missing_answer_field():
    print("\n[missing answer field]")
    with Server(workers=8, delay=0.0) as srv:
        cfg = write("ma.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("ma.jsonl", [{"question": "q"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 1", proc.returncode == 1, str(proc.returncode))
        check("stderr names answer", "answer" in proc.stderr, proc.stderr)


def test_invalid_configs():
    print("\n[invalid configuration]")
    url = "http://127.0.0.1:9"
    inp = write_jsonl("ic.jsonl", [{"question": "q", "answer": "42"}])
    cases = {
        "sample requires temperature > 0":
            cfg_yaml(url, scheme="sample", temperature=0.0),
        "rejection requires temperature > 0":
            cfg_yaml(url, scheme="rejection", temperature=0.0, n=3),
        "rejection requires evaluation":
            cfg_yaml(url, scheme="rejection", temperature=0.7, n=3, evaluation=False),
        "unknown scheme":
            cfg_yaml(url, scheme="beam").replace('"beam"', '"beam"'),
        "unknown evaluation type":
            cfg_yaml(url, eval_type="fuzzy"),
        "exact_match needs answer_field":
            cfg_yaml(url, answer_field=None),
        "regex needs pattern":
            cfg_yaml(url, eval_type="regex", answer_field=None),
        "unknown extract":
            cfg_yaml(url, extract="first_number"),
        "missing api_url":
            "task:\n  model: \"m\"\n  prompt:\n    user: \"{question}\"\n",
        "missing model":
            "task:\n  api_url: \"%s\"\n  prompt:\n    user: \"{question}\"\n" % url,
        "missing prompt":
            "task:\n  api_url: \"%s\"\n  model: \"m\"\n" % url,
        "bad rpm":
            cfg_yaml(url).replace("rpm: 60", "rpm: 0"),
        "empty config": "",
    }
    for name, text in cases.items():
        cfg = write("bad-%s.yaml" % abs(hash(name)), text)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 1: %s" % name, proc.returncode == 1, "rc=%s out=%s err=%s"
              % (proc.returncode, proc.stdout[:120], proc.stderr[:160]))
        check("stderr message: %s" % name, proc.stderr.strip() != "", proc.stderr)


def test_missing_files():
    print("\n[missing files]")
    inp = write_jsonl("mfiles.jsonl", [{"question": "q", "answer": "42"}])
    cfg = write("mfiles.yaml", cfg_yaml("http://127.0.0.1:9"))
    proc, _, _, _ = run_cli(os.path.join(TMP, "nope.yaml"), inp)
    check("missing config exit 1", proc.returncode == 1, proc.stderr)
    proc, _, _, _ = run_cli(cfg, os.path.join(TMP, "nope.jsonl"))
    check("missing input exit 1", proc.returncode == 1, proc.stderr)
    bad = write("bad.jsonl", '{"question": "q"}\nnot json\n')
    proc, _, _, _ = run_cli(cfg, bad)
    check("bad jsonl exit 1", proc.returncode == 1, proc.stderr)
    proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--input", inp],
                          capture_output=True, text=True)
    check("missing --output exit 1", proc.returncode == 1, str(proc.returncode))
    proc = subprocess.run([PY, CLI], capture_output=True, text=True)
    check("no subcommand exit 1", proc.returncode == 1, str(proc.returncode))


def test_cli_overrides():
    print("\n[cli overrides]")
    with Server(workers=8, delay=0.05, wrong_attempts=1) as srv:
        cfg = write("ov.yaml", cfg_yaml("http://127.0.0.1:9", model="cfg-model", max_tokens=11))
        inp = write_jsonl("ov.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=[
            "--api-url", srv.url, "--model", "override-model", "--rpm", "120",
            "--max-tokens", "77", "--scheme", "rejection", "--temperature", "0.5", "--n", "4"])
        check("exit 0", proc.returncode == 0, proc.stderr)
        payload = srv.stats()["payloads"][0]
        check("model override", payload["model"] == "override-model", str(payload))
        check("max_tokens override", payload["max_tokens"] == 77)
        check("temperature override", payload["temperature"] == 0.5)
        check("scheme override -> 2 attempts", rows[0]["result"]["attempts"] == 2,
              json.dumps(rows[0]["result"]))
        check("meta model uses override", rows[0]["meta"][0]["model"] == "override-model")


def test_empty_input_and_overwrite():
    print("\n[empty input / output overwrite]")
    with Server(workers=8, delay=0.0) as srv:
        cfg = write("e.yaml", cfg_yaml(srv.url))
        inp = write("empty.jsonl", "")
        out = os.path.join(TMP, "pre-existing.jsonl")
        with open(out, "w") as fh:
            fh.write("STALE\nSTALE\n")
        proc, rows, summary, _ = run_cli(cfg, inp, out)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("no rows", rows == [])
        check("summary zeros", summary["total"] == 0 and summary["total_api_calls"] == 0
              and summary["elapsed_seconds"] == 0.0 and summary["throughput_rpm"] == 0.0,
              str(summary))
        with open(out) as fh:
            check("output overwritten", fh.read() == "")

        inp2 = write_jsonl("one.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp2, out)
        check("overwrite writes fresh rows", len(rows) == 1)


def test_throughput():
    print("\n[throughput >= 80% of rpm]")
    # capacity: 5 workers * (1/0.5s) = 10 rps = 600 rpm; configured rpm 300
    with Server(workers=25, delay=0.5) as srv:
        rows = [{"question": "q%d" % i, "answer": "42"} for i in range(150)]
        cfg = write("tp.yaml", cfg_yaml(srv.url, rpm=300))
        inp = write_jsonl("tp.jsonl", rows)
        proc, out_rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("all rows", len(out_rows) == 150)
        ratio = summary["throughput_rpm"] / 300.0
        check("throughput >= 80%% of rpm (got %.1f, ratio %.2f)"
              % (summary["throughput_rpm"], ratio), ratio >= 0.8, str(summary))
        check("does not blow past the rpm budget (ratio %.2f)" % ratio, ratio <= 1.5,
              str(summary))
        check("concurrent requests in flight (max %d)" % srv.stats()["max_in_flight"],
              srv.stats()["max_in_flight"] > 1)
        check("elapsed rounded 1dp",
              round(summary["elapsed_seconds"], 1) == summary["elapsed_seconds"])


def test_throughput_slow_server():
    print("\n[throughput with slow per-request latency]")
    # 60 rpm capacity via 6 workers with 6s latency each
    with Server(workers=6, delay=6.0) as srv:
        rows = [{"question": "q%d" % i, "answer": "42"} for i in range(60)]
        cfg = write("tp2.yaml", cfg_yaml(srv.url, rpm=60))
        inp = write_jsonl("tp2.jsonl", rows)
        proc, out_rows, summary, _ = run_cli(cfg, inp)
        ratio = summary["throughput_rpm"] / 60.0
        check("throughput >= 80%% of rpm (got %.1f)" % summary["throughput_rpm"],
              ratio >= 0.8, str(summary))
        check("stays near the rpm budget (ratio %.2f)" % ratio, ratio <= 1.5, str(summary))


def test_sample_scheme():
    print("\n[sample scheme]")
    with Server(workers=8, delay=0.05, wrong_attempts=99) as srv:
        cfg = write("s.yaml", cfg_yaml(srv.url, scheme="sample", temperature=0.9, n=5))
        inp = write_jsonl("s.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        check("n ignored -> 1 call", summary["total_api_calls"] == 1, str(summary))
        check("attempts 1", rows[0]["result"]["attempts"] == 1)
        check("meta dict", isinstance(rows[0]["meta"], dict))
        check("temperature sent", srv.stats()["payloads"][0]["temperature"] == 0.9)
        check("failing eval keeps output", rows[0]["output"] is not None)
        check("passed false", rows[0]["result"]["passed"] is False)


def test_no_system_prompt():
    print("\n[prompt without system message]")
    with Server(workers=8, delay=0.05) as srv:
        text = cfg_yaml(srv.url).replace('    system: "Solve it."\n', "")
        cfg = write("nosys.yaml", text)
        inp = write_jsonl("nosys.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        msgs = srv.stats()["payloads"][0]["messages"]
        check("only user message", len(msgs) == 1 and msgs[0]["role"] == "user", str(msgs))


def test_placeholders_multiple_fields():
    print("\n[multiple placeholders / non-string fields]")
    with Server(workers=8, delay=0.05) as srv:
        text = cfg_yaml(srv.url, user_prompt="{question} [{hint}] #{idx}")
        cfg = write("ph.yaml", text)
        inp = write_jsonl("ph.jsonl", [{"question": "q", "hint": "h", "idx": 3, "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr)
        content = srv.stats()["payloads"][0]["messages"][1]["content"]
        check("rendered", content == "q [h] #3", content)
        check("input preserved verbatim",
              rows[0]["input"] == {"question": "q", "hint": "h", "idx": 3, "answer": "42"})


def test_stdout_is_only_summary():
    print("\n[stdout contains only the summary]")
    with Server(workers=8, delay=0.05) as srv:
        cfg = write("so.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("so.jsonl", ROWS10[:3])
        proc, rows, summary, _ = run_cli(cfg, inp)
        lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        check("one stdout line", len(lines) == 1, proc.stdout)
        check("valid json", isinstance(json.loads(lines[0]), dict))


def test_yaml_fallback_parser():
    print("\n[built-in YAML fallback parser]")
    sys.path.insert(0, ROOT)
    import rejector
    text = cfg_yaml("http://x", scheme="rejection", temperature=0.7, n=3)
    parsed = rejector._MiniYAML(text).parse()
    ref = None
    try:
        import yaml
        ref = yaml.safe_load(text)
    except ImportError:
        pass
    check("fallback matches pyyaml", ref is None or parsed == ref,
          json.dumps(parsed) + " != " + json.dumps(ref))
    block = 'task:\n  name: t  # comment\n  prompt:\n    system: |\n      line one\n      line two\n    user: "{q}"\n  items: [1, 2, 3]\n'
    parsed = rejector._MiniYAML(block).parse()
    ok = (parsed["task"]["name"] == "t"
          and parsed["task"]["prompt"]["system"] == "line one\nline two\n"
          and parsed["task"]["items"] == [1, 2, 3])
    check("fallback handles block scalars, comments, flow seqs", ok, json.dumps(parsed))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    order = [
        test_greedy_basic, test_greedy_forces_temperature, test_no_evaluation,
        test_eval_variants, test_extract_last_number_forms, test_sample_scheme,
        test_rejection_success_on_third, test_rejection_first_try, test_rejection_exhausted,
        test_rejection_temperature_sent, test_retries_5xx_permanent, test_retries_5xx_transient,
        test_4xx_no_retry, test_rejection_api_failure, test_missing_prompt_field,
        test_missing_answer_field, test_invalid_configs, test_missing_files,
        test_cli_overrides, test_empty_input_and_overwrite, test_no_system_prompt,
        test_placeholders_multiple_fields, test_stdout_is_only_summary,
        test_yaml_fallback_parser, test_throughput, test_throughput_slow_server,
    ]
    assert len(order) == len(tests), (len(order), len(tests))
    for fn in order:
        try:
            fn()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            FAILURES.append((fn.__name__, "exception: %s" % exc))
    print("\n==================================")
    print("passed: %d   failed: %d" % (len(PASSES), len(FAILURES)))
    for name, detail in FAILURES:
        print("  FAILED: %s  %s" % (name, detail))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
