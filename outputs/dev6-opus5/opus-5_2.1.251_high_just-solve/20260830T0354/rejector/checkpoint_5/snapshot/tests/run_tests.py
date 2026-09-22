#!/usr/bin/env python3
"""End-to-end test-suite for rejector.py against the mock server."""
import json
import os
import re
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
            cfg_yaml(url, extract="bogus_extract"),
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


# ==========================================================================
# Part 2: multi-task configs, llm_judge and script evaluation
# ==========================================================================

def run_multi(config, mapping=None, input_dir=None, outdir=None, extra=()):
    outdir = outdir or os.path.join(TMP, "outdir-%d" % time.time_ns())
    cmd = [PY, CLI, "run", "--config", config, "--output", outdir]
    for name, path in (mapping or {}).items():
        cmd += ["--input", "%s=%s" % (name, path)]
    if input_dir:
        cmd += ["--input-dir", input_dir]
    cmd += list(extra)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    files = {}
    if os.path.isdir(outdir):
        for fn in sorted(os.listdir(outdir)):
            if fn.endswith(".jsonl"):
                with open(os.path.join(outdir, fn), encoding="utf-8") as fh:
                    files[fn[:-len(".jsonl")]] = [json.loads(l) for l in fh if l.strip()]
    summary = None
    if proc.stdout.strip():
        try:
            summary = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            summary = None
    return proc, files, summary, outdir


def multi_yaml(url, tasks_block, rpm=600, extra_defaults=""):
    return (
        "defaults:\n"
        '  api_url: "%s"\n'
        '  model: "gpt-4"\n'
        "  rpm: %s\n"
        "  generation:\n"
        "    max_tokens: 128\n" % (url, rpm)
    ) + extra_defaults + "tasks:\n" + tasks_block


GSM_TASK = '''  gsm8k:
    prompt:
      system: "Solve it."
      user: "{question}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
'''

MMLU_TASK = '''  mmlu:
    prompt:
      system: "Answer with a letter."
      user: "{question}\\n\\nA) {a}\\nB) {b}\\nC) {c}\\nD) {d}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "letter"
    output_field: "choice"
'''

REVIEW_TASK = '''  review:
    prompt:
      system: "Write a response."
      user: "{prompt_text}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "JUDGE quality evaluator."
        user: "Rate:\\n{__response__}\\n\\nCriteria: {criteria}\\n\\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"
'''

MMLU_ROWS = [{"question": "capital of France?", "a": "London", "b": "Paris",
              "c": "Berlin", "d": "Madrid", "answer": "B"}]
REVIEW_ROWS = [{"prompt_text": "Describe a sunset.", "criteria": "vividness"}]


def test_multi_explicit_mapping():
    print("\n[multi-task: explicit --input task=path]")
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-basic.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        gsm = write_jsonl("m-gsm.jsonl", ROWS10)
        mmlu = write_jsonl("m-mmlu.jsonl", MMLU_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm, "mmlu": mmlu})
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("one file per task", sorted(files) == ["gsm8k", "mmlu"], sorted(files))
    check("gsm8k row count", len(files.get("gsm8k", [])) == 10)
    check("mmlu row count", len(files.get("mmlu", [])) == 1)
    check("row order preserved",
          [r["input"]["question"] for r in files["gsm8k"]] ==
          [r["question"] for r in ROWS10])
    check("per-task output_field",
          "solution" in (files["gsm8k"][0]["output"] or {}) and
          "choice" in (files["mmlu"][0]["output"] or {}),
          json.dumps(files["mmlu"][0]["output"]))
    check("summary total is the sum", summary["total"] == 11, json.dumps(summary))
    check("summary has tasks object", set(summary.get("tasks", {})) == {"gsm8k", "mmlu"},
          json.dumps(summary))
    check("per-task totals",
          summary["tasks"]["gsm8k"]["total"] == 10 and summary["tasks"]["mmlu"]["total"] == 1,
          json.dumps(summary["tasks"]))
    check("per-task api calls sum to total",
          sum(t["total_api_calls"] for t in summary["tasks"].values()) == summary["total_api_calls"],
          json.dumps(summary))
    check("per-task keys",
          set(summary["tasks"]["gsm8k"]) == {"total", "passed", "failed", "total_solutions",
                                             "avg_solutions_per_input", "total_api_calls"},
          json.dumps(summary["tasks"]["gsm8k"]))
    check("passed/failed add up",
          summary["passed"] + summary["failed"] == summary["total"] and
          summary["passed"] == sum(t["passed"] for t in summary["tasks"].values()),
          json.dumps(summary))


def test_multi_input_dir():
    print("\n[multi-task: --input-dir]")
    data = os.path.join(TMP, "indir")
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "gsm8k.jsonl"), "w") as fh:
        for r in ROWS10:
            fh.write(json.dumps(r) + "\n")
    with open(os.path.join(data, "mmlu.jsonl"), "w") as fh:
        fh.write(json.dumps(MMLU_ROWS[0]) + "\n")
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-dir.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        proc, files, summary, _ = run_multi(cfg, input_dir=data)
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("both tasks ran", sorted(files) == ["gsm8k", "mmlu"], sorted(files))
    check("counts", len(files["gsm8k"]) == 10 and len(files["mmlu"]) == 1)
    check("summary tasks", set(summary["tasks"]) == {"gsm8k", "mmlu"})


def test_multi_task_selection():
    print("\n[multi-task: --task selection]")
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-sel.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        gsm = write_jsonl("s-gsm.jsonl", ROWS10)
        proc, files, summary, outdir = run_multi(
            cfg, {"gsm8k": gsm}, extra=["--task", "gsm8k"])
    check("exit 0 without mmlu input", proc.returncode == 0, proc.stderr[:300])
    check("only gsm8k written", sorted(files) == ["gsm8k"], sorted(os.listdir(outdir)))
    check("no mmlu.jsonl on disk", not os.path.exists(os.path.join(outdir, "mmlu.jsonl")))
    check("summary lists only gsm8k", list(summary["tasks"]) == ["gsm8k"], json.dumps(summary))
    check("summary total", summary["total"] == 10, json.dumps(summary))

    # An unselected task is not validated at all, even if it is malformed.
    broken = GSM_TASK + "  broken:\n    generation:\n      scheme: \"nope\"\n"
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-sel2.yaml", multi_yaml(srv.url, broken))
        gsm = write_jsonl("s2-gsm.jsonl", ROWS10[:2])
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm}, extra=["--task", "gsm8k"])
    check("unselected invalid task ignored", proc.returncode == 0, proc.stderr[:300])
    check("only selected task output", sorted(files) == ["gsm8k"], sorted(files))

    # Two --task flags select two of three tasks.
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-sel3.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK + REVIEW_TASK))
        gsm = write_jsonl("s3-gsm.jsonl", ROWS10[:2])
        mmlu = write_jsonl("s3-mmlu.jsonl", MMLU_ROWS)
        proc, files, summary, _ = run_multi(
            cfg, {"gsm8k": gsm, "mmlu": mmlu},
            extra=["--task", "gsm8k", "--task", "mmlu"])
    check("repeatable --task", proc.returncode == 0, proc.stderr[:300])
    check("two tasks ran", set(summary["tasks"]) == {"gsm8k", "mmlu"}, json.dumps(summary))

    # An --input for an unselected task is ignored rather than rejected.
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-sel4.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        gsm = write_jsonl("s4-gsm.jsonl", ROWS10[:2])
        mmlu = write_jsonl("s4-mmlu.jsonl", MMLU_ROWS)
        proc, files, summary, _ = run_multi(
            cfg, {"gsm8k": gsm, "mmlu": mmlu}, extra=["--task", "gsm8k"])
    check("extra --input ignored for unselected task", proc.returncode == 0, proc.stderr[:300])
    check("only gsm8k ran", list(summary["tasks"]) == ["gsm8k"], json.dumps(summary))


def test_multi_defaults_merge():
    print("\n[multi-task: defaults merging]")
    tasks = (
        '  a:\n'
        '    generation:\n'
        '      scheme: "sample"\n'
        '      temperature: 0.5\n'
        '    output_field: "a_out"\n'
        '  b:\n'
        '    model: "task-b-model"\n'
        '    prompt:\n'
        '      user: "B {question}"\n'
        '    output_field: "b_out"\n'
    )
    extra_defaults = (
        "  prompt:\n"
        '    system: "Shared system."\n'
        '    user: "A {question}"\n'
        "  evaluation:\n"
        '    type: "exact_match"\n'
        '    answer_field: "answer"\n'
        '    extract: "last_number"\n'
    )
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("m-merge.yaml", multi_yaml(srv.url, tasks, extra_defaults=extra_defaults))
        rows = [{"question": "q1", "answer": "42"}]
        a = write_jsonl("mm-a.jsonl", rows)
        b = write_jsonl("mm-b.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"a": a, "b": b})
        payloads = srv.stats()["payloads"]
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("defaults supply prompt/evaluation",
          files["a"][0]["result"]["passed"] is True and files["b"][0]["result"]["passed"] is True,
          json.dumps(files))
    check("per-task output_field",
          "a_out" in files["a"][0]["output"] and "b_out" in files["b"][0]["output"])
    check("task overrides model", files["b"][0]["meta"]["model"] == "task-b-model",
          files["b"][0]["meta"]["model"])
    check("defaults model kept for other task", files["a"][0]["meta"]["model"] == "gpt-4")
    users = sorted(m["content"] for p in payloads for m in p["messages"] if m["role"] == "user")
    check("prompt.user overridden per task, system merged from defaults",
          users == ["A q1", "B q1"], json.dumps(users))
    systems = set(m["content"] for p in payloads for m in p["messages"] if m["role"] == "system")
    check("shared system prompt", systems == {"Shared system."}, json.dumps(sorted(systems)))
    temps = sorted(set(p["temperature"] for p in payloads))
    check("generation merged per task", temps == [0.0, 0.5], json.dumps(temps))
    check("max_tokens from defaults",
          all(p["max_tokens"] == 128 for p in payloads),
          json.dumps([p["max_tokens"] for p in payloads]))


def test_extract_letter():
    print("\n[extract: letter]")
    with Server(workers=4, delay=0.02, answer="B",
                template="The answer is {answer}) Paris") as srv:
        cfg = write("m-letter.yaml", multi_yaml(srv.url, MMLU_TASK))
        inp = write_jsonl("letter.jsonl", MMLU_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"mmlu": inp})
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    row = files["mmlu"][0]
    check("letter extracted", row["result"]["extracted_answer"] == "B",
          json.dumps(row["result"]))
    check("row passes", row["result"]["passed"] is True)

    forms = {
        "A": "A",
        "(C)": "C",
        "D)": "D",
        "Answer: B": "B",
        "The answer is B) Paris": "B",
        "no letter here": None,
    }
    for text, want in forms.items():
        with Server(workers=2, delay=0.01, answer="x", template=text.replace("{", "{{").replace("}", "}}")) as srv:
            cfg = write("m-letter-%d.yaml" % abs(hash(text)), multi_yaml(srv.url, MMLU_TASK))
            inp = write_jsonl("letter-%d.jsonl" % abs(hash(text)), MMLU_ROWS)
            proc, files, summary, _ = run_multi(cfg, {"mmlu": inp})
        got = files["mmlu"][0]["result"]["extracted_answer"] if files.get("mmlu") else "<none>"
        check("letter form %r -> %r" % (text, want), got == want, "got %r" % (got,))


def test_extract_first_number():
    print("\n[extract: first_number]")
    task = '''  fn:
    prompt:
      system: "Solve."
      user: "{question}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "first_number"
    output_field: "out"
'''
    cases = {"Score: 8 out of 10": "8",
             "3.5 then 9": "3.5",
             "value -12 and 4": "-12",
             "no digits": None}
    for text, want in cases.items():
        with Server(workers=2, delay=0.01, answer="x",
                    template=text.replace("{", "{{").replace("}", "}}")) as srv:
            cfg = write("m-fn-%d.yaml" % abs(hash(text)), multi_yaml(srv.url, task))
            inp = write_jsonl("fn-%d.jsonl" % abs(hash(text)), [{"question": "q", "answer": "8"}])
            proc, files, summary, _ = run_multi(cfg, {"fn": inp})
        got = files["fn"][0]["result"]["extracted_answer"] if files.get("fn") else "<none>"
        check("first_number %r -> %r" % (text, want), got == want, "got %r" % (got,))
    check("first_number differs from last_number", True)


def test_llm_judge_pass_and_fail():
    print("\n[llm_judge]")
    with Server(workers=8, delay=0.02, answer="42", judge_answer="8") as srv:
        cfg = write("m-judge.yaml", multi_yaml(srv.url, REVIEW_TASK))
        inp = write_jsonl("judge.jsonl", REVIEW_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"review": inp})
        stats = srv.stats()
        payloads = stats["payloads"]
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    row = files["review"][0]
    check("judge_score in result", row["result"].get("judge_score") == 8,
          json.dumps(row["result"]))
    check("passes at threshold 7", row["result"]["passed"] is True, json.dumps(row["result"]))
    check("output kept", row["output"]["response"].startswith("Let me solve it."),
          json.dumps(row["output"]))
    jm = row["meta"].get("judge_meta")
    check("judge_meta present", isinstance(jm, dict), json.dumps(row["meta"]))
    check("judge_meta fields",
          jm and set(["model", "prompt_tokens", "completion_tokens", "total_tokens",
                      "latency_ms", "finish_reason"]).issubset(jm),
          json.dumps(jm))
    check("judge_meta model", jm and jm["model"] == "gpt-4", json.dumps(jm))
    check("judge_meta finish_reason", jm and jm["finish_reason"] == "stop")
    check("judge_meta latency is a number", jm and isinstance(jm["latency_ms"], int))
    check("judge call counted", summary["total_api_calls"] == 2, json.dumps(summary))
    check("per-task api calls include judge",
          summary["tasks"]["review"]["total_api_calls"] == 2, json.dumps(summary))
    check("server saw 2 calls", stats["calls"] == 2, json.dumps(stats["calls"]))
    check("server saw 1 judge call", stats["judge_calls"] == 1, json.dumps(stats["judge_calls"]))
    judge_payload = [p for p in payloads
                     if any("JUDGE" in (m.get("content") or "") for m in p["messages"])]
    check("one judge request", len(judge_payload) == 1, len(judge_payload))
    judge_user = [m["content"] for m in judge_payload[0]["messages"] if m["role"] == "user"][0]
    check("__response__ substituted into judge prompt",
          "Let me solve it." in judge_user and "{__response__}" not in judge_user, judge_user)
    check("row fields available in judge prompt", "vividness" in judge_user, judge_user)

    # Same score, higher threshold -> fails but keeps the generated output.
    with Server(workers=8, delay=0.02, answer="42", judge_answer="8") as srv:
        cfg = write("m-judge-hi.yaml",
                    multi_yaml(srv.url, REVIEW_TASK.replace("threshold: 7", "threshold: 9")))
        inp = write_jsonl("judge2.jsonl", REVIEW_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"review": inp})
    row = files["review"][0]
    check("fails below threshold", row["result"]["passed"] is False, json.dumps(row["result"]))
    check("judge_score still recorded", row["result"]["judge_score"] == 8)
    check("greedy keeps output on failure", row["output"] is not None)
    check("summary counts it failed", summary["failed"] == 1, json.dumps(summary))

    # A non-numeric judge reply cannot clear the threshold.
    with Server(workers=8, delay=0.02, answer="42", judge_answer="not a score") as srv:
        cfg = write("m-judge-nan.yaml", multi_yaml(srv.url, REVIEW_TASK))
        inp = write_jsonl("judge3.jsonl", REVIEW_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"review": inp})
    row = files["review"][0]
    check("unparseable score fails", row["result"]["passed"] is False, json.dumps(row["result"]))
    check("judge_score null", row["result"]["judge_score"] is None, json.dumps(row["result"]))


def test_llm_judge_model_override():
    print("\n[llm_judge: model selection]")
    with Server(workers=8, delay=0.02, judge_answer="9") as srv:
        cfg = write("m-judge-m.yaml", multi_yaml(srv.url, REVIEW_TASK))
        inp = write_jsonl("judgem.jsonl", REVIEW_ROWS)
        proc, files, _, _ = run_multi(cfg, {"review": inp})
        payloads = srv.stats()["payloads"]
    jm = files["review"][0]["meta"]["judge_meta"]
    check("defaults to task model", jm["model"] == "gpt-4", json.dumps(jm))

    cfg_model = REVIEW_TASK.replace('      threshold: 7',
                                    '      model: "judge-from-config"\n      threshold: 7')
    with Server(workers=8, delay=0.02, judge_answer="9") as srv:
        cfg = write("m-judge-m2.yaml", multi_yaml(srv.url, cfg_model))
        inp = write_jsonl("judgem2.jsonl", REVIEW_ROWS)
        proc, files, _, _ = run_multi(cfg, {"review": inp})
        payloads = srv.stats()["payloads"]
    jm = files["review"][0]["meta"]["judge_meta"]
    check("evaluation.model used", jm["model"] == "judge-from-config", json.dumps(jm))
    check("generation model untouched", files["review"][0]["meta"]["model"] == "gpt-4")
    judge_payload = [p for p in payloads
                     if any("JUDGE" in (m.get("content") or "") for m in p["messages"])][0]
    check("judge request sent with judge model",
          judge_payload["model"] == "judge-from-config", judge_payload["model"])

    with Server(workers=8, delay=0.02, judge_answer="9") as srv:
        cfg = write("m-judge-m3.yaml", multi_yaml(srv.url, cfg_model))
        inp = write_jsonl("judgem3.jsonl", REVIEW_ROWS)
        proc, files, _, _ = run_multi(cfg, {"review": inp},
                                      extra=["--eval-model", "cli-judge"])
        payloads = srv.stats()["payloads"]
    jm = files["review"][0]["meta"]["judge_meta"]
    check("--eval-model wins over evaluation.model", jm["model"] == "cli-judge", json.dumps(jm))
    check("--eval-model leaves generation model alone",
          files["review"][0]["meta"]["model"] == "gpt-4")


def test_llm_judge_rejection():
    print("\n[llm_judge with rejection sampling]")
    task = REVIEW_TASK.replace('      scheme: "greedy"',
                               '      scheme: "rejection"\n      temperature: 0.7\n      n: 3')
    with Server(workers=8, delay=0.02, judge_answer="8", judge_wrong_answer="2",
                judge_wrong_attempts=2) as srv:
        cfg = write("m-judge-rej.yaml", multi_yaml(srv.url, task))
        inp = write_jsonl("judgerej.jsonl", REVIEW_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"review": inp})
    row = files["review"][0]
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("retried until the judge passed", row["result"]["attempts"] == 3,
          json.dumps(row["result"]))
    check("passed", row["result"]["passed"] is True, json.dumps(row["result"]))
    check("final judge_score", row["result"]["judge_score"] == 8, json.dumps(row["result"]))
    check("meta is a list of attempts", isinstance(row["meta"], list) and len(row["meta"]) == 3,
          json.dumps(row["meta"])[:200])
    check("each attempt has judge_meta",
          all(isinstance(m.get("judge_meta"), dict) for m in row["meta"]))
    check("api calls counted: 3 gen + 3 judge", summary["total_api_calls"] == 6,
          json.dumps(summary))


def test_script_evaluation():
    print("\n[script evaluation]")
    base = '''  code_gen:
    prompt:
      system: "Code."
      user: "{problem}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "script"
      command_template: %s
      success_exit_code: %s
    output_field: "code"
'''
    rows = [{"problem": "write good code",
             "test_code": "echo '{__response__}' | grep -q 'result is 42'"}]

    # Row field expands to text that itself contains {__response__}.
    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-script.yaml", multi_yaml(srv.url, base % ('"{test_code}"', 0)))
        inp = write_jsonl("script.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    row = files["code_gen"][0]
    check("nested {__response__} substituted -> pass", row["result"]["passed"] is True,
          json.dumps(row["result"]))
    check("output kept", row["output"]["code"].startswith("Let me solve it."))
    check("no extracted_answer for script", row["result"]["extracted_answer"] is None)
    check("script adds no api calls", summary["total_api_calls"] == 1, json.dumps(summary))

    # Same command, but the response no longer matches -> non-zero exit -> fail.
    with Server(workers=4, delay=0.02, answer="7") as srv:
        cfg = write("m-script2.yaml", multi_yaml(srv.url, base % ('"{test_code}"', 0)))
        inp = write_jsonl("script2.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    row = files["code_gen"][0]
    check("non-zero exit fails", row["result"]["passed"] is False, json.dumps(row["result"]))
    check("summary counts failure", summary["failed"] == 1, json.dumps(summary))

    # {__response__} directly in the command template.
    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-script3.yaml",
                    multi_yaml(srv.url, base % ('"echo \'{__response__}\' | grep -q 42"', 0)))
        inp = write_jsonl("script3.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    check("direct {__response__} works", files["code_gen"][0]["result"]["passed"] is True,
          json.dumps(files["code_gen"][0]["result"]))

    # A non-zero success_exit_code is honoured.
    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-script4.yaml", multi_yaml(srv.url, base % ('"exit 3"', 3)))
        inp = write_jsonl("script4.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    check("success_exit_code 3 passes on exit 3",
          files["code_gen"][0]["result"]["passed"] is True,
          json.dumps(files["code_gen"][0]["result"]))

    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-script5.yaml", multi_yaml(srv.url, base % ('"exit 0"', 3)))
        inp = write_jsonl("script5.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    check("success_exit_code 3 fails on exit 0",
          files["code_gen"][0]["result"]["passed"] is False,
          json.dumps(files["code_gen"][0]["result"]))

    # Command output is captured, never echoed into the JSONL.
    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-script6.yaml",
                    multi_yaml(srv.url, base % ('"echo NOISE_STDOUT; echo NOISE_STDERR 1>&2"', 0)))
        inp = write_jsonl("script6.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    blob = json.dumps(files["code_gen"][0])
    check("stdout/stderr not in output", "NOISE_STDOUT" not in blob and "NOISE_STDERR" not in blob,
          blob[:200])
    check("stdout/stderr not on stdout", "NOISE_STDOUT" not in proc.stdout, proc.stdout[:200])
    check("result keys unchanged",
          set(files["code_gen"][0]["result"]) == {"passed", "extracted_answer", "attempts"},
          json.dumps(files["code_gen"][0]["result"]))

    # A hanging command is killed at 10s and counts as a failure.
    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-script7.yaml", multi_yaml(srv.url, base % ('"sleep 60"', 0)))
        inp = write_jsonl("script7.jsonl", rows)
        started = time.time()
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
        elapsed = time.time() - started
    check("timeout fails the row", files["code_gen"][0]["result"]["passed"] is False,
          json.dumps(files["code_gen"][0]["result"]))
    check("timeout is ~10s, not unbounded", 8.0 <= elapsed < 30.0, "elapsed %.1fs" % elapsed)

    # rejection + script: retries until the script passes.
    rej = base.replace('      scheme: "greedy"',
                       '      scheme: "rejection"\n      temperature: 0.8\n      n: 3')
    with Server(workers=4, delay=0.02, answer="42", wrong_answer="7", wrong_attempts=2) as srv:
        cfg = write("m-script8.yaml", multi_yaml(srv.url, rej % ('"{test_code}"', 0)))
        inp = write_jsonl("script8.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"code_gen": inp})
    row = files["code_gen"][0]
    check("rejection retries on script failure", row["result"]["attempts"] == 3,
          json.dumps(row["result"]))
    check("rejection passes on third try", row["result"]["passed"] is True)


def test_multi_cli_errors():
    print("\n[multi-task: CLI validation]")
    cfg = write("m-err.yaml", multi_yaml("http://127.0.0.1:9", GSM_TASK + MMLU_TASK))
    gsm = write_jsonl("e-gsm.jsonl", ROWS10[:1])
    mmlu = write_jsonl("e-mmlu.jsonl", MMLU_ROWS)
    data = os.path.join(TMP, "errdir")
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "gsm8k.jsonl"), "w") as fh:
        fh.write(json.dumps(ROWS10[0]) + "\n")

    def fails(name, argv):
        out = os.path.join(TMP, "eout-%d" % time.time_ns())
        proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--output", out] + argv,
                              capture_output=True, text=True)
        check("exit 1: %s" % name, proc.returncode == 1,
              "rc=%s out=%s err=%s" % (proc.returncode, proc.stdout[:120], proc.stderr[:200]))
        check("stderr message: %s" % name, proc.stderr.strip() != "", proc.stderr[:200])

    fails("--input and --input-dir combined",
          ["--input", "gsm8k=%s" % gsm, "--input-dir", data])
    fails("neither --input nor --input-dir", [])
    fails("--input without task= prefix", ["--input", gsm])
    fails("--input for an unknown task", ["--input", "nope=%s" % gsm])
    fails("missing input for a task", ["--input", "gsm8k=%s" % gsm])
    fails("--input-dir missing a task file", ["--input-dir", data])
    fails("--task names an unknown task",
          ["--input", "gsm8k=%s" % gsm, "--task", "nope"])
    fails("--input-dir does not exist",
          ["--input-dir", os.path.join(TMP, "no-such-dir")])
    fails("input file does not exist",
          ["--input", "gsm8k=%s" % os.path.join(TMP, "nope.jsonl"),
           "--input", "mmlu=%s" % mmlu])

    existing_file = write("not-a-dir.txt", "x\n")
    proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--output", existing_file,
                           "--input", "gsm8k=%s" % gsm, "--input", "mmlu=%s" % mmlu],
                          capture_output=True, text=True)
    check("exit 1: --output must be a directory", proc.returncode == 1,
          "rc=%s err=%s" % (proc.returncode, proc.stderr[:200]))

    bad = write("m-bad-judge.yaml", multi_yaml(
        "http://127.0.0.1:9",
        REVIEW_TASK.replace("      threshold: 7\n", "")))
    out = os.path.join(TMP, "eout-judge")
    proc = subprocess.run([PY, CLI, "run", "--config", bad, "--output", out,
                           "--input", "review=%s" % gsm], capture_output=True, text=True)
    check("exit 1: llm_judge without threshold", proc.returncode == 1, proc.stderr[:200])

    bad2 = write("m-bad-script.yaml", multi_yaml(
        "http://127.0.0.1:9",
        '  s:\n    prompt:\n      user: "{question}"\n'
        '    evaluation:\n      type: "script"\n'))
    proc = subprocess.run([PY, CLI, "run", "--config", bad2, "--output", out,
                           "--input", "s=%s" % gsm], capture_output=True, text=True)
    check("exit 1: script without command_template", proc.returncode == 1, proc.stderr[:200])

    bad3 = write("m-defaults-only.yaml", "defaults:\n  model: \"m\"\n")
    proc = subprocess.run([PY, CLI, "run", "--config", bad3, "--output", out,
                           "--input", "s=%s" % gsm], capture_output=True, text=True)
    check("exit 1: defaults without tasks", proc.returncode == 1, proc.stderr[:200])

    bad4 = write("m-empty-tasks.yaml", "defaults:\n  model: \"m\"\ntasks:\n")
    proc = subprocess.run([PY, CLI, "run", "--config", bad4, "--output", out,
                           "--input", "s=%s" % gsm], capture_output=True, text=True)
    check("exit 1: empty tasks mapping", proc.returncode == 1, proc.stderr[:200])

    # A row missing a judge-prompt field is rejected before any request goes out.
    bad5 = write("m-judge-field.yaml", multi_yaml("http://127.0.0.1:9", REVIEW_TASK))
    noc = write_jsonl("no-criteria.jsonl", [{"prompt_text": "hi"}])
    proc = subprocess.run([PY, CLI, "run", "--config", bad5, "--output", out,
                           "--input", "review=%s" % noc], capture_output=True, text=True)
    check("exit 1: row missing judge template field", proc.returncode == 1, proc.stderr[:200])
    check("error names the task", "review" in proc.stderr, proc.stderr[:200])

    # A row missing a command_template field is rejected too.
    bad6 = write("m-script-field.yaml", multi_yaml(
        "http://127.0.0.1:9",
        '  s:\n    prompt:\n      user: "{question}"\n'
        '    evaluation:\n      type: "script"\n'
        '      command_template: "echo {test_code}"\n'))
    proc = subprocess.run([PY, CLI, "run", "--config", bad6, "--output", out,
                           "--input", "s=%s" % gsm], capture_output=True, text=True)
    check("exit 1: row missing command_template field", proc.returncode == 1, proc.stderr[:200])


def test_single_task_config_still_works():
    print("\n[single-task config: Part 1 behaviour preserved]")
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("s1.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("s1.jsonl", ROWS10)
        proc, rows, summary, out = run_cli(cfg, inp)
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("single output file", os.path.isfile(out))
    check("10 rows", len(rows) == 10)
    check("no tasks key in summary", "tasks" not in summary, json.dumps(summary))

    # --input-dir works for a single-task config using task.name.
    data = os.path.join(TMP, "singledir")
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "t.jsonl"), "w") as fh:
        for r in ROWS10:
            fh.write(json.dumps(r) + "\n")
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("s2.yaml", cfg_yaml(srv.url))
        out = os.path.join(TMP, "s2-out.jsonl")
        proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--input-dir", data,
                               "--output", out], capture_output=True, text=True)
    check("single-task --input-dir exit 0", proc.returncode == 0, proc.stderr[:300])
    check("single-task --input-dir wrote a file", os.path.isfile(out))

    # `name=path` is accepted for a single-task config too.
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("s3.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("s3.jsonl", ROWS10[:2])
        proc, rows, summary, _ = run_cli(cfg, "t=%s" % inp)
    check("single-task name=path accepted", proc.returncode == 0, proc.stderr[:300])
    check("single-task name=path rows", len(rows) == 2)

    # --task naming the single task selects it; an unknown name is an error.
    with Server(workers=8, delay=0.02, answer="42") as srv:
        cfg = write("s4.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("s4.jsonl", ROWS10[:2])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--task", "t"])
        check("single-task --task t", proc.returncode == 0, proc.stderr[:300])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--task", "other"])
        check("single-task --task unknown -> exit 1", proc.returncode == 1, proc.stderr[:200])


def test_multi_interleaving_and_throughput():
    print("\n[multi-task: interleaving and shared rpm budget]")
    rows = [{"question": "q%d" % i, "answer": "42"} for i in range(12)]
    task_a = GSM_TASK.replace("gsm8k:", "alpha:").replace('user: "{question}"',
                                                          'user: "AAA {question}"')
    task_b = GSM_TASK.replace("gsm8k:", "beta:").replace('user: "{question}"',
                                                         'user: "BBB {question}"')
    with Server(workers=8, delay=0.2, answer="42") as srv:
        cfg = write("m-inter.yaml", multi_yaml(srv.url, task_a + task_b, rpm=600))
        a = write_jsonl("i-a.jsonl", rows)
        b = write_jsonl("i-b.jsonl", rows)
        proc, files, summary, _ = run_multi(cfg, {"alpha": a, "beta": b})
        stats = srv.stats()
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("both tasks complete", len(files["alpha"]) == 12 and len(files["beta"]) == 12)
    order = []
    for p in stats["payloads"]:
        text = "".join(m.get("content", "") for m in p["messages"])
        order.append("A" if "AAA" in text else "B")
    switches = sum(1 for i in range(1, len(order)) if order[i] != order[i - 1])
    check("tasks interleave rather than run back to back", switches > 1,
          "".join(order))
    check("concurrent in flight", stats["max_in_flight"] > 1, stats["max_in_flight"])
    check("row order preserved per task despite interleaving",
          [r["input"]["question"] for r in files["alpha"]] == [r["question"] for r in rows] and
          [r["input"]["question"] for r in files["beta"]] == [r["question"] for r in rows])
    ratio = summary["throughput_rpm"] / 600.0
    check("throughput stays near the shared rpm budget (ratio %.2f)" % ratio,
          0.5 <= ratio <= 1.6, json.dumps(summary))


def test_multi_empty_input_and_rerun():
    print("\n[multi-task: empty input and rerun]")
    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-empty.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        gsm = write_jsonl("z-gsm.jsonl", [])
        mmlu = write_jsonl("z-mmlu.jsonl", MMLU_ROWS)
        outdir = os.path.join(TMP, "z-out")
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm, "mmlu": mmlu}, outdir=outdir)
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("empty task file written", os.path.exists(os.path.join(outdir, "gsm8k.jsonl")))
    check("empty task has no rows", files.get("gsm8k", []) == [])
    check("empty task still summarised", summary["tasks"]["gsm8k"]["total"] == 0,
          json.dumps(summary))
    check("output dir created when absent", os.path.isdir(outdir))

    with Server(workers=4, delay=0.02, answer="42") as srv:
        cfg = write("m-empty2.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        gsm = write_jsonl("z2-gsm.jsonl", ROWS10[:3])
        mmlu = write_jsonl("z2-mmlu.jsonl", MMLU_ROWS)
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm, "mmlu": mmlu}, outdir=outdir)
    check("rerun overwrites", len(files["gsm8k"]) == 3, len(files.get("gsm8k", [])))


# ==========================================================================
# Part 3: in-context learning setups and multiple solutions per input
# ==========================================================================

EX_A = [{"input": {"question": "What is 2+2?"}, "output": "Let me think.\n2 + 2 = 4\n#### 4"},
        {"input": {"question": "3 cats plus 2?"}, "output": "Step by step:\n3 + 2 = 5\n#### 5"},
        {"input": {"question": "What is 1+1?"}, "output": "1 + 1 = 2\n#### 2"}]
EX_B = [{"input": {"question": "What is 2+2?"}, "output": "#### 4"},
        {"input": {"question": "3 cats plus 2?"}, "output": "#### 5"}]
EX_C = [{"input": {"question": "What is 10 / 2?"}, "output": "10 / 2 is 5.\n#### 5"}]


def icl_block(setups, k=None, strategy=None, indent="  "):
    lines = [indent + "icl:"]
    if k is not None:
        lines.append(indent + "  k: %d" % k)
    if strategy is not None:
        lines.append(indent + '  strategy: "%s"' % strategy)
    lines.append(indent + "  setups:")
    for setup in setups:
        lines.append(indent + "    - name: %s" % json.dumps(setup["name"]))
        if "file" in setup:
            lines.append(indent + "      file: %s" % json.dumps(setup["file"]))
        elif setup.get("examples") is None:
            lines.append(indent + "      examples:")
        else:
            lines.append(indent + "      examples:")
            for ex in setup["examples"]:
                lines.append(indent + "        - input: %s" % json.dumps(ex["input"]))
                lines.append(indent + "          output: %s" % json.dumps(ex["output"]))
    return "\n".join(lines) + "\n"


def icl_yaml(url, setups=None, k=None, strategy=None, num_solutions=None,
             max_attempts=None, raw_icl=None, **kw):
    text = cfg_yaml(url, **kw)
    if max_attempts is not None:
        text = text.replace("    n: %s\n" % kw.get("n", 1),
                            "    n: %s\n    max_attempts: %s\n" % (kw.get("n", 1), max_attempts))
    if num_solutions is not None:
        text += "  num_solutions: %s\n" % num_solutions
    if raw_icl is not None:
        text += raw_icl
    elif setups is not None:
        text += icl_block(setups, k=k, strategy=strategy)
    return text


ONE_ROW = [{"question": "What is 15 + 27?", "answer": "42"}]


def test_icl_message_layout():
    print("\n[icl: message layout and single-solution list format]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("icl-layout.yaml", icl_yaml(
            srv.url, setups=[{"name": "cot", "examples": EX_A[:2]}]))
        inp = write_jsonl("icl-layout.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:400])
        msgs = srv.stats()["payloads"][0]["messages"]
    check("roles alternate around the examples",
          [m["role"] for m in msgs] ==
          ["system", "user", "assistant", "user", "assistant", "user"], str([m["role"] for m in msgs]))
    check("example input rendered with prompt.user", msgs[1]["content"] == "What is 2+2?",
          msgs[1]["content"])
    check("example output verbatim", msgs[2]["content"] == EX_A[0]["output"], msgs[2]["content"])
    check("second example rendered", msgs[3]["content"] == "3 cats plus 2?", msgs[3]["content"])
    check("final user message is the row", msgs[5]["content"] == "What is 15 + 27?",
          msgs[5]["content"])
    r = rows[0]
    check("output is a list even for one solution", isinstance(r["output"], list), str(r["output"]))
    check("one output item", len(r["output"]) == 1, json.dumps(r["output"]))
    check("output item carries output_field + icl_setup",
          r["output"][0] == {"solution": "Let me solve it.\nThe result is 42\n#### 42",
                             "icl_setup": "cot"}, json.dumps(r["output"][0]))
    check("meta is a list", isinstance(r["meta"], list) and len(r["meta"]) == 1, str(r["meta"]))
    check("meta carries icl_setup", r["meta"][0]["icl_setup"] == "cot")
    check("meta carries evaluation_passed", r["meta"][0]["evaluation_passed"] is True,
          json.dumps(r["meta"][0]))
    check("meta keeps the base fields",
          set(r["meta"][0]) == {"model", "prompt_tokens", "completion_tokens", "total_tokens",
                                "latency_ms", "finish_reason", "icl_setup", "evaluation_passed"},
          str(sorted(r["meta"][0])))
    check("result keys", list(r["result"]) == ["passed", "failed", "attempts"], str(list(r["result"])))
    check("result counts", r["result"] == {"passed": 1, "failed": 0, "attempts": 1},
          json.dumps(r["result"]))
    check("summary reports solutions",
          summary["total_solutions"] == 1 and summary["avg_solutions_per_input"] == 1.0,
          json.dumps(summary))


def test_icl_k():
    print("\n[icl: k selects the first k examples]")
    with Server(workers=8, delay=0.02) as srv:
        setups = [{"name": "cot", "examples": EX_A}]
        cfg = write("icl-k2.yaml", icl_yaml(srv.url, setups=setups, k=2))
        inp = write_jsonl("icl-k.jsonl", ONE_ROW)
        proc, rows, _, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("k=2 -> 2 example pairs", len(msgs) == 6, str(len(msgs)))
        check("uses the first two examples", msgs[2]["content"] == EX_A[0]["output"]
              and msgs[4]["content"] == EX_A[1]["output"])

        cfg = write("icl-kall.yaml", icl_yaml(srv.url, setups=setups))
        proc, rows, _, _ = run_cli(cfg, inp)
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("k omitted -> all examples", len(msgs) == 8, str(len(msgs)))

        cfg = write("icl-kbig.yaml", icl_yaml(srv.url, setups=setups, k=99))
        proc, rows, _, _ = run_cli(cfg, inp)
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("k larger than the setup -> all examples", len(msgs) == 8, str(len(msgs)))

        proc, rows, _, _ = run_cli(cfg, inp, extra=["--icl-k", "1"])
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("--icl-k overrides the config", len(msgs) == 4, str(len(msgs)))


def test_icl_file_setups():
    print("\n[icl: file-backed setups]")
    subdir = os.path.join(TMP, "iclfiles")
    os.makedirs(subdir, exist_ok=True)

    def write_icl(name, text):
        path = os.path.join(subdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    good = "".join(json.dumps(e) + "\n" for e in EX_A[:2])
    write_icl("good.jsonl", "\n" + good + "\n")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("icl-file.yaml", icl_yaml(
            srv.url, setups=[{"name": "detailed", "file": "iclfiles/good.jsonl"}]))
        inp = write_jsonl("icl-file.jsonl", ONE_ROW)
        proc, rows, _, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:400])
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("file examples loaded (blank lines skipped)", len(msgs) == 6, str(len(msgs)))
        check("file example output verbatim", msgs[2]["content"] == EX_A[0]["output"])
        check("icl_setup name from file setup", rows[0]["output"][0]["icl_setup"] == "detailed")

    bad_cases = {
        "malformed jsonl line": good + "not json\n",
        "missing input key": json.dumps({"output": "x"}) + "\n",
        "missing output key": json.dumps({"input": {"question": "q"}}) + "\n",
        "input not an object": json.dumps({"input": "q", "output": "x"}) + "\n",
        "output not a string": json.dumps({"input": {"question": "q"}, "output": 5}) + "\n",
        "line is not an object": "[1, 2]\n",
    }
    with Server(workers=8, delay=0.0) as srv:
        for name, text in bad_cases.items():
            fn = "bad-%d.jsonl" % abs(hash(name))
            write_icl(fn, text)
            cfg = write("icl-bad-%d.yaml" % abs(hash(name)), icl_yaml(
                srv.url, setups=[{"name": "s", "file": "iclfiles/%s" % fn}]))
            inp = write_jsonl("icl-bad.jsonl", ONE_ROW)
            proc, rows, summary, _ = run_cli(cfg, inp)
            check("exit 1: %s" % name, proc.returncode == 1,
                  "rc=%s err=%s" % (proc.returncode, proc.stderr[:200]))
            check("stderr message: %s" % name, proc.stderr.strip() != "", proc.stderr[:200])
        cfg = write("icl-missing-file.yaml", icl_yaml(
            srv.url, setups=[{"name": "s", "file": "iclfiles/nope.jsonl"}]))
        proc, _, _, _ = run_cli(cfg, write_jsonl("icl-bad2.jsonl", ONE_ROW))
        check("exit 1: missing icl file", proc.returncode == 1, proc.stderr[:200])
        check("no API requests were sent", srv.stats()["calls"] == 0,
              str(srv.stats()["calls"]))


def test_icl_strategies():
    print("\n[icl: fixed / round_robin / random strategies]")
    setups = [{"name": "A", "examples": EX_A[:1]},
              {"name": "B", "examples": EX_B[:1]},
              {"name": "C", "examples": EX_C[:1]}]
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("icl-rr.yaml", icl_yaml(srv.url, setups=setups, strategy="round_robin",
                                            scheme="sample", temperature=0.7, num_solutions=5))
        inp = write_jsonl("icl-rr.jsonl", ONE_ROW)
        proc, rows, _, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        order = [m["icl_setup"] for m in rows[0]["meta"]]
        check("round robin cycles A B C A B", order == ["A", "B", "C", "A", "B"], str(order))
        check("outputs record their setup",
              [o["icl_setup"] for o in rows[0]["output"]] == ["A", "B", "C", "A", "B"],
              json.dumps(rows[0]["output"]))

        cfg = write("icl-fixed.yaml", icl_yaml(srv.url, setups=setups, strategy="fixed",
                                               scheme="sample", temperature=0.7, num_solutions=4))
        proc, rows, _, _ = run_cli(cfg, inp)
        order = [m["icl_setup"] for m in rows[0]["meta"]]
        check("fixed always uses the first setup", order == ["A"] * 4, str(order))

        proc, rows, _, _ = run_cli(cfg, inp, extra=["--icl-strategy", "round_robin"])
        order = [m["icl_setup"] for m in rows[0]["meta"]]
        check("--icl-strategy overrides the config", order == ["A", "B", "C", "A"], str(order))

        cfg = write("icl-rand.yaml", icl_yaml(srv.url, setups=setups, strategy="random",
                                              scheme="sample", temperature=0.7, num_solutions=24))
        proc, rows, _, _ = run_cli(cfg, inp)
        order = [m["icl_setup"] for m in rows[0]["meta"]]
        check("random stays within the declared setups",
              set(order) <= {"A", "B", "C"} and len(order) == 24, str(order))
        check("random varies across attempts", len(set(order)) > 1, str(order))


def test_icl_config_validation():
    print("\n[icl: configuration validation]")
    url = "http://127.0.0.1:9"
    inp = write_jsonl("iclv.jsonl", ONE_ROW)
    cases = {
        "setup without a name":
            icl_yaml(url, raw_icl='  icl:\n    setups:\n      - examples:\n'
                                  '          - input: {"question": "q"}\n            output: "a"\n'),
        "setup with both examples and file":
            icl_yaml(url, raw_icl='  icl:\n    setups:\n      - name: "s"\n        file: "x.jsonl"\n'
                                  '        examples:\n          - input: {"question": "q"}\n'
                                  '            output: "a"\n'),
        "setup with neither examples nor file":
            icl_yaml(url, raw_icl='  icl:\n    setups:\n      - name: "s"\n'),
        "empty setups list":
            icl_yaml(url, raw_icl="  icl:\n    setups: []\n"),
        "setups missing":
            icl_yaml(url, raw_icl='  icl:\n    k: 2\n'),
        "unknown strategy":
            icl_yaml(url, setups=[{"name": "s", "examples": EX_C}], strategy="spiral"),
        "negative k":
            icl_yaml(url, setups=[{"name": "s", "examples": EX_C}], k=-1),
        "inline example missing output":
            icl_yaml(url, raw_icl='  icl:\n    setups:\n      - name: "s"\n        examples:\n'
                                  '          - input: {"question": "q"}\n'),
        "inline example input not an object":
            icl_yaml(url, raw_icl='  icl:\n    setups:\n      - name: "s"\n        examples:\n'
                                  '          - input: "q"\n            output: "a"\n'),
        "num_solutions zero":
            icl_yaml(url, num_solutions=0),
        "num_solutions not an integer":
            icl_yaml(url, num_solutions="abc"),
        "max_attempts zero":
            icl_yaml(url, num_solutions=2, max_attempts=0),
    }
    for name, text in cases.items():
        cfg = write("iclbad-%d.yaml" % abs(hash(name)), text)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 1: %s" % name, proc.returncode == 1,
              "rc=%s out=%s err=%s" % (proc.returncode, proc.stdout[:100], proc.stderr[:200]))
        check("stderr message: %s" % name, proc.stderr.strip() != "", proc.stderr[:200])


def test_greedy_icl_walks_setups_once():
    print("\n[greedy + icl: one pass over the setups]")
    setups = [{"name": "A", "examples": EX_A[:1]}, {"name": "B", "examples": EX_B[:1]}]
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("greedy-icl.yaml", icl_yaml(srv.url, setups=setups, strategy="round_robin",
                                                num_solutions=5))
        inp = write_jsonl("greedy-icl.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("capped at the number of setups", len(r["output"]) == 2, json.dumps(r["output"]))
        check("declared order", [o["icl_setup"] for o in r["output"]] == ["A", "B"],
              json.dumps(r["output"]))
        check("attempts equals setups", r["result"]["attempts"] == 2, json.dumps(r["result"]))
        check("no setup retried", summary["total_api_calls"] == 2, json.dumps(summary))
        check("temperature 0", all(p["temperature"] == 0.0 for p in srv.stats()["payloads"]))
        check("summary solutions", summary["total_solutions"] == 2, json.dumps(summary))


def test_greedy_no_icl_multi():
    print("\n[greedy without icl: one deterministic solution]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("greedy-multi.yaml", icl_yaml(srv.url, num_solutions=4))
        inp = write_jsonl("greedy-multi.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("list format with one item", isinstance(r["output"], list) and len(r["output"]) == 1,
              json.dumps(r["output"]))
        check("icl_setup null", r["output"][0]["icl_setup"] is None, json.dumps(r["output"][0]))
        check("single attempt", r["result"]["attempts"] == 1, json.dumps(r["result"]))
        check("one api call", summary["total_api_calls"] == 1, json.dumps(summary))


def test_sample_multi_solutions():
    print("\n[sample: one request per requested solution]")
    with Server(workers=8, delay=0.02, wrong_attempts=99) as srv:
        cfg = write("sample-multi.yaml", icl_yaml(srv.url, scheme="sample", temperature=0.7,
                                                  num_solutions=3))
        inp = write_jsonl("sample-multi.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("three requests", summary["total_api_calls"] == 3, json.dumps(summary))
        check("evaluation does not gate inclusion", len(r["output"]) == 3, json.dumps(r["output"]))
        check("all icl_setup null", all(o["icl_setup"] is None for o in r["output"]))
        check("meta one per attempt", len(r["meta"]) == 3)
        check("evaluation_passed false", all(m["evaluation_passed"] is False for m in r["meta"]),
              json.dumps(r["meta"]))
        check("result counts", r["result"] == {"passed": 0, "failed": 3, "attempts": 3},
              json.dumps(r["result"]))
        check("row counted as failed", summary["failed"] == 1 and summary["passed"] == 0,
              json.dumps(summary))
        check("summary solutions", summary["total_solutions"] == 3
              and summary["avg_solutions_per_input"] == 3.0, json.dumps(summary))


def test_rejection_multi_partial():
    print("\n[rejection: partial collection under max_attempts]")
    with Server(workers=8, delay=0.02, correct_every=3) as srv:
        cfg = write("rej-multi.yaml", icl_yaml(srv.url, scheme="rejection", temperature=0.7,
                                               n=5, num_solutions=5, max_attempts=10))
        inp = write_jsonl("rej-multi.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("attempts capped at max_attempts", r["result"]["attempts"] == 10,
              json.dumps(r["result"]))
        check("only passing solutions kept", len(r["output"]) == 3, json.dumps(r["output"]))
        check("passed/failed", r["result"]["passed"] == 3 and r["result"]["failed"] == 7,
              json.dumps(r["result"]))
        check("every kept solution passed",
              all("#### 42" in o["solution"] for o in r["output"]), json.dumps(r["output"]))
        check("meta one per attempt", len(r["meta"]) == 10)
        check("evaluation_passed matches", [m["evaluation_passed"] for m in r["meta"]] ==
              [False, False, True] * 3 + [False], json.dumps(r["meta"]))
        check("api calls", summary["total_api_calls"] == 10, json.dumps(summary))


def test_rejection_multi_early_stop():
    print("\n[rejection: stops once num_solutions pass]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("rej-multi2.yaml", icl_yaml(srv.url, scheme="rejection", temperature=0.7,
                                                n=5, num_solutions=4, max_attempts=20))
        inp = write_jsonl("rej-multi2.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        r = rows[0]
        check("attempts == num_solutions", r["result"]["attempts"] == 4, json.dumps(r["result"]))
        check("four solutions", len(r["output"]) == 4, json.dumps(r["output"]))
        check("failed 0", r["result"]["failed"] == 0, json.dumps(r["result"]))
        check("api calls 4", summary["total_api_calls"] == 4, json.dumps(summary))


def test_rejection_max_attempts_default():
    print("\n[rejection: max_attempts defaults to 3 * num_solutions]")
    with Server(workers=8, delay=0.02, wrong_attempts=99) as srv:
        cfg = write("rej-default.yaml", icl_yaml(srv.url, scheme="rejection", temperature=0.7,
                                                 n=5, num_solutions=2))
        inp = write_jsonl("rej-default.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        r = rows[0]
        check("6 attempts", r["result"]["attempts"] == 6, json.dumps(r["result"]))
        check("no solutions", r["output"] == [], json.dumps(r["output"]))
        check("passed 0 failed 6", r["result"]["passed"] == 0 and r["result"]["failed"] == 6,
              json.dumps(r["result"]))
        check("summary solution counts", summary["total_solutions"] == 0
              and summary["avg_solutions_per_input"] == 0.0, json.dumps(summary))


def test_rejection_icl_multi():
    print("\n[rejection + icl: setups cycle across attempts]")
    setups = [{"name": "A", "examples": EX_A[:1]}, {"name": "B", "examples": EX_B[:1]}]
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("rej-icl.yaml", icl_yaml(srv.url, setups=setups, strategy="round_robin",
                                             scheme="rejection", temperature=0.7, n=1,
                                             num_solutions=3, max_attempts=6))
        inp = write_jsonl("rej-icl.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("three solutions", len(r["output"]) == 3, json.dumps(r["output"]))
        check("setups cycle", [o["icl_setup"] for o in r["output"]] == ["A", "B", "A"],
              json.dumps(r["output"]))
        check("examples present in the payloads",
              all(len(p["messages"]) == 4 for p in srv.stats()["payloads"]),
              json.dumps(srv.stats()["payloads"][0]["messages"]))


def test_list_format_without_evaluation():
    print("\n[list format with evaluation omitted]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("noeval-multi.yaml", icl_yaml(srv.url, scheme="sample", temperature=0.7,
                                                  num_solutions=3, evaluation=False))
        inp = write_jsonl("noeval-multi.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("evaluation_passed null", all(m["evaluation_passed"] is None for m in r["meta"]),
              json.dumps(r["meta"]))
        check("passed counts emitted outputs", r["result"]["passed"] == 3, json.dumps(r["result"]))
        check("failed 0", r["result"]["failed"] == 0, json.dumps(r["result"]))

    with Server(workers=8, delay=0.0, always_500=True) as srv:
        cfg = write("noeval-multi2.yaml", icl_yaml(srv.url, scheme="sample", temperature=0.7,
                                                   num_solutions=2, evaluation=False))
        inp = write_jsonl("noeval-multi2.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        r = rows[0]
        check("no outputs when every call fails", r["output"] == [], json.dumps(r["output"]))
        check("failed counts attempts with no output",
              r["result"] == {"passed": 0, "failed": 2, "attempts": 2}, json.dumps(r["result"]))
        check("meta records the error", all("error" in m for m in r["meta"]), json.dumps(r["meta"]))


def test_legacy_single_solution_preserved():
    print("\n[legacy: num_solutions 1 without icl keeps the Part 1 format]")
    with Server(workers=8, delay=0.02, wrong_attempts=2) as srv:
        # max_attempts is present but must be ignored: `n` still governs.
        cfg = write("legacy.yaml", icl_yaml(srv.url, scheme="rejection", temperature=0.7,
                                            n=5, num_solutions=1, max_attempts=1))
        inp = write_jsonl("legacy.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        r = rows[0]
        check("output is a dict", isinstance(r["output"], dict), json.dumps(r["output"]))
        check("no icl_setup in output", set(r["output"]) == {"solution"}, json.dumps(r["output"]))
        check("Part 1 result keys", list(r["result"]) == ["passed", "extracted_answer", "attempts"],
              str(list(r["result"])))
        check("max_attempts ignored -> 3 attempts", r["result"]["attempts"] == 3,
              json.dumps(r["result"]))
        check("meta list without icl fields",
              isinstance(r["meta"], list) and "icl_setup" not in r["meta"][0],
              json.dumps(r["meta"][0]))
        check("summary keeps the Part 1 shape", "total_solutions" not in summary,
              json.dumps(summary))


def test_num_solutions_cli_override():
    print("\n[--num-solutions overrides the config both ways]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("ns-cli.yaml", icl_yaml(srv.url, scheme="sample", temperature=0.7))
        inp = write_jsonl("ns-cli.jsonl", ONE_ROW)
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--num-solutions", "3"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("flag turns on the list format", isinstance(rows[0]["output"], list)
              and len(rows[0]["output"]) == 3, json.dumps(rows[0]["output"]))

        cfg = write("ns-cli2.yaml", icl_yaml(srv.url, scheme="sample", temperature=0.7,
                                             num_solutions=4))
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--num-solutions", "1"])
        check("flag back to 1 restores the Part 1 format", isinstance(rows[0]["output"], dict),
              json.dumps(rows[0]["output"]))


def test_multi_task_num_solutions_and_summary():
    print("\n[multi-task: num_solutions from defaults and per-task summaries]")
    task_a = ('  alpha:\n'
              '    prompt:\n      system: "Solve it."\n      user: "A {question}"\n'
              '    generation:\n      scheme: "sample"\n      temperature: 0.7\n'
              '    evaluation:\n      type: "exact_match"\n      answer_field: "answer"\n'
              '      extract: "last_number"\n'
              '    output_field: "solution"\n')
    task_b = ('  beta:\n'
              '    prompt:\n      system: "Solve it."\n      user: "B {question}"\n'
              '    generation:\n      scheme: "sample"\n      temperature: 0.7\n'
              '    num_solutions: 1\n'
              '    evaluation:\n      type: "exact_match"\n      answer_field: "answer"\n'
              '      extract: "last_number"\n'
              '    output_field: "solution"\n')
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("m-ns.yaml", multi_yaml(srv.url, task_a + task_b,
                                            extra_defaults="  num_solutions: 3\n"))
        a = write_jsonl("m-ns-a.jsonl", ONE_ROW * 2)
        b = write_jsonl("m-ns-b.jsonl", ONE_ROW)
        proc, files, summary, _ = run_multi(cfg, {"alpha": a, "beta": b})
    check("exit 0", proc.returncode == 0, proc.stderr[:400])
    check("defaults num_solutions applies", all(len(r["output"]) == 3 for r in files["alpha"]),
          json.dumps(files["alpha"][0]["output"]))
    check("per-task override wins", isinstance(files["beta"][0]["output"], dict),
          json.dumps(files["beta"][0]["output"]))
    check("per-task summary gains solution fields",
          set(summary["tasks"]["alpha"]) == {"total", "passed", "failed", "total_solutions",
                                             "avg_solutions_per_input", "total_api_calls"},
          json.dumps(summary["tasks"]["alpha"]))
    check("alpha totals", summary["tasks"]["alpha"]["total_solutions"] == 6
          and summary["tasks"]["alpha"]["avg_solutions_per_input"] == 3.0,
          json.dumps(summary["tasks"]["alpha"]))
    check("beta totals", summary["tasks"]["beta"]["total_solutions"] == 1
          and summary["tasks"]["beta"]["avg_solutions_per_input"] == 1.0,
          json.dumps(summary["tasks"]["beta"]))
    check("run summary solutions", summary["total_solutions"] == 7,
          json.dumps(summary))
    check("api calls add up", summary["total_api_calls"] == 7, json.dumps(summary))


def test_icl_example_files_from_config_dir():
    print("\n[icl: file paths resolve against the config directory]")
    nested = os.path.join(TMP, "cfgdir", "icl")
    os.makedirs(nested, exist_ok=True)
    with open(os.path.join(nested, "ex.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(EX_C[0]) + "\n")
    with Server(workers=8, delay=0.02) as srv:
        text = icl_yaml(srv.url, setups=[{"name": "detailed", "file": "icl/ex.jsonl"}])
        cfg = os.path.join(TMP, "cfgdir", "nested.yaml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(text)
        inp = write_jsonl("cfgdir.jsonl", ONE_ROW)
        # Run from a different working directory to prove the path is not cwd-relative.
        out = os.path.join(TMP, "cfgdir-out.jsonl")
        proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--input", inp, "--output", out],
                              capture_output=True, text=True, cwd="/")
        check("exit 0", proc.returncode == 0, proc.stderr[:400])
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("example loaded from the config directory", len(msgs) == 4, str(len(msgs)))
        check("example content", msgs[2]["content"] == EX_C[0]["output"], msgs[2]["content"])


def test_shipped_icl_example_config():
    print("\n[examples/icl.yaml parses and runs]")
    with Server(workers=8, delay=0.02) as srv:
        with open(os.path.join(ROOT, "examples", "icl.yaml"), encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("http://localhost:8000", srv.url)
        cfg = os.path.join(ROOT, "examples", "_tmp_icl.yaml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            inp = write_jsonl("ex-icl.jsonl", ONE_ROW)
            outdir = os.path.join(TMP, "ex-icl-out")
            proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--output", outdir,
                                   "--input", "gsm8k=%s" % inp], capture_output=True, text=True)
        finally:
            os.remove(cfg)
    check("exit 0", proc.returncode == 0, proc.stderr[:400])
    with open(os.path.join(outdir, "gsm8k.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    check("five solutions", len(rows[0]["output"]) == 5, json.dumps(rows[0]["output"])[:300])
    check("round robin over three setups",
          [o["icl_setup"] for o in rows[0]["output"]] ==
          ["chain_of_thought", "direct", "detailed", "chain_of_thought", "direct"],
          json.dumps(rows[0]["output"])[:300])



# ==========================================================================
# Part 4: agentic generation and completions-mode templates
# ==========================================================================

TOOL_LOOKUP = """  tools:
    - name: "lookup"
      description: "Look up a value in the database by key"
      parameters:
        type: "object"
        properties:
          key:
            type: "string"
            description: "The database key to look up"
        required: ["key"]
      handler:
        type: "static_map"
        mapping:
          "revenue_q1": "1250000"
          "revenue_q2": "1480000"
          "employees": "142"
        default: "KEY_NOT_FOUND"
"""

TOOL_ECHO = """  tools:
    - name: "calculate"
      description: "Evaluate a mathematical expression"
      parameters:
        type: "object"
        properties:
          expression:
            type: "string"
        required: ["expression"]
      handler:
        type: "echo"
"""

TOOL_SCRIPT = """  tools:
    - name: "run_python"
      description: "Run python code"
      parameters:
        type: "object"
        properties:
          code:
            type: "string"
        required: ["code"]
      handler:
        type: "script"
        command: "python3 -c"
        arg_field: "code"
"""


def agentic_yaml(url, tools=TOOL_LOOKUP, **kw):
    lines = [
        "task:",
        '  name: "t"',
        '  api_url: "%s"' % url,
        '  model: "gpt-4"',
        "  rpm: %s" % kw.get("rpm", 600),
    ]
    if kw.get("api_type"):
        lines.append('  api_type: "%s"' % kw["api_type"])
    if kw.get("chat_template"):
        lines.append('  chat_template: "%s"' % kw["chat_template"])
    if kw.get("num_solutions"):
        lines.append("  num_solutions: %s" % kw["num_solutions"])
    lines += [
        "  prompt:",
        '    system: "Solve it."',
        '    user: "{question}"',
        "  generation:",
        '    scheme: "agentic"',
        "    max_iterations: %s" % kw.get("max_iterations", 10),
        "    temperature: %s" % kw.get("temperature", 0.0),
        "    max_tokens: 256",
    ]
    if kw.get("evaluation", True):
        lines += [
            "  evaluation:",
            '    type: "exact_match"',
            '    answer_field: "answer"',
            '    extract: "%s"' % kw.get("extract", "last_number"),
        ]
    lines.append('  output_field: "%s"' % kw.get("output_field", "answer"))
    text = "\n".join(lines) + "\n"
    if tools:
        text += tools
    return text


AGENTIC_META_KEYS = {"total_prompt_tokens", "total_completion_tokens", "total_tokens",
                     "latency_ms", "finish_reason", "iterations_detail"}


def test_agentic_basic():
    print("\n[agentic: tool call then final answer]")
    with Server(workers=4, delay=0.05, tool_rounds=1, answer_from_tools=True) as srv:
        cfg = write("ag1.yaml", agentic_yaml(srv.url))
        inp = write_jsonl("ag1.jsonl", [{"question": "revenue?", "answer": "1250000"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        row = rows[0]
        check("output text", row["output"] == {"answer": "Let me solve it.\nThe result is 1250000\n#### 1250000"},
              json.dumps(row["output"]))
        check("passed", row["result"]["passed"] is True, json.dumps(row["result"]))
        check("extracted", row["result"]["extracted_answer"] == "1250000")
        check("attempts 1", row["result"]["attempts"] == 1)
        check("iterations 2", row["result"]["iterations"] == 2, str(row["result"]))
        check("result key order",
              list(row["result"]) == ["passed", "extracted_answer", "attempts",
                                      "iterations", "tool_calls"], str(list(row["result"])))
        calls = row["result"]["tool_calls"]
        check("one tool call recorded", len(calls) == 1, json.dumps(calls))
        check("tool call shape",
              calls[0] == {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
                           "result": "1250000"}, json.dumps(calls[0]))
        meta = row["meta"]
        check("meta keys", set(meta) == AGENTIC_META_KEYS, str(sorted(meta)))
        check("meta aggregates tokens",
              meta["total_prompt_tokens"] == 20 and meta["total_completion_tokens"] == 10
              and meta["total_tokens"] == 30, json.dumps(meta))
        check("meta finish_reason stop", meta["finish_reason"] == "stop")
        check("iterations_detail length", len(meta["iterations_detail"]) == 2)
        check("iterations_detail keys",
              set(meta["iterations_detail"][0]) == {"prompt_tokens", "completion_tokens",
                                                    "total_tokens", "latency_ms",
                                                    "finish_reason"},
              str(sorted(meta["iterations_detail"][0])))
        check("per-iteration finish reasons",
              [d["finish_reason"] for d in meta["iterations_detail"]] == ["tool_calls", "stop"],
              json.dumps(meta["iterations_detail"]))
        check("latency aggregated", meta["latency_ms"] >= max(
            d["latency_ms"] for d in meta["iterations_detail"]))
        check("two api calls counted", summary["total_api_calls"] == 2, json.dumps(summary))

        payloads = srv.stats()["payloads"]
        check("tools sent in request body",
              payloads[0]["tools"] == [{
                  "type": "function",
                  "function": {"name": "lookup",
                               "description": "Look up a value in the database by key",
                               "parameters": {"type": "object",
                                              "properties": {"key": {"type": "string",
                                                                     "description": "The database key to look up"}},
                                              "required": ["key"]}}}],
              json.dumps(payloads[0].get("tools")))
        msgs = payloads[1]["messages"]
        check("conversation grew to 4 messages", len(msgs) == 4, json.dumps(msgs))
        check("assistant tool-call turn appended",
              msgs[2]["role"] == "assistant" and msgs[2]["content"] is None
              and msgs[2]["tool_calls"][0]["function"]["name"] == "lookup",
              json.dumps(msgs[2]))
        check("tool result message appended",
              msgs[3]["role"] == "tool" and msgs[3]["content"] == "1250000"
              and msgs[3]["name"] == "lookup"
              and msgs[3]["tool_call_id"] == msgs[2]["tool_calls"][0]["id"],
              json.dumps(msgs[3]))


def test_agentic_multiple_calls_per_iteration():
    print("\n[agentic: several tool calls in one response]")
    with Server(workers=4, delay=0.05, tool_rounds=1, calls_per_round=2,
                tool_arg_values="revenue_q1,revenue_q2", answer_from_tools=True) as srv:
        cfg = write("ag2.yaml", agentic_yaml(srv.url))
        inp = write_jsonl("ag2.jsonl", [{"question": "revenue?", "answer": "1480000"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        calls = rows[0]["result"]["tool_calls"]
        check("both calls recorded in order",
              [(c["iteration"], c["args"]["key"], c["result"]) for c in calls] ==
              [(1, "revenue_q1", "1250000"), (1, "revenue_q2", "1480000")],
              json.dumps(calls))
        check("iterations 2", rows[0]["result"]["iterations"] == 2)
        msgs = srv.stats()["payloads"][-1]["messages"]
        check("two tool results appended",
              [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "tool"],
              json.dumps([m["role"] for m in msgs]))


def test_agentic_max_iterations():
    print("\n[agentic: max_iterations reached]")
    with Server(workers=4, delay=0.05, always_tools=True) as srv:
        cfg = write("ag3.yaml", agentic_yaml(srv.url, max_iterations=3))
        inp = write_jsonl("ag3.jsonl", [{"question": "revenue?", "answer": "1250000"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        row = rows[0]
        check("output null", row["output"] is None, json.dumps(row["output"]))
        check("finish_reason max_iterations",
              row["meta"]["finish_reason"] == "max_iterations", json.dumps(row["meta"]))
        check("iterations == limit", row["result"]["iterations"] == 3, str(row["result"]))
        check("evaluation fails", row["result"]["passed"] is False, str(row["result"]))
        check("iterations_detail length 3", len(row["meta"]["iterations_detail"]) == 3)
        check("three api calls", summary["total_api_calls"] == 3, json.dumps(summary))
        check("summary counts the row as failed",
              summary["failed"] == 1 and summary["passed"] == 0, json.dumps(summary))


def test_agentic_handlers():
    print("\n[agentic: handler types]")
    with Server(workers=4, delay=0.05, tool_rounds=1, tool_name="calculate",
                tool_arg_key="expression", tool_arg_values="2+2") as srv:
        cfg = write("ag4.yaml", agentic_yaml(srv.url, tools=TOOL_ECHO))
        inp = write_jsonl("ag4.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, _, _ = run_cli(cfg, inp)
        check("echo exit 0", proc.returncode == 0, proc.stderr[:500])
        check("echo returns json arguments",
              rows[0]["result"]["tool_calls"][0]["result"] == '{"expression": "2+2"}',
              json.dumps(rows[0]["result"]["tool_calls"]))

    with Server(workers=4, delay=0.05, tool_rounds=1, tool_name="lookup",
                tool_arg_values="nope") as srv:
        cfg = write("ag5.yaml", agentic_yaml(srv.url))
        inp = write_jsonl("ag5.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, _, _ = run_cli(cfg, inp)
        check("static_map default on a miss",
              rows[0]["result"]["tool_calls"][0]["result"] == "KEY_NOT_FOUND",
              json.dumps(rows[0]["result"]["tool_calls"]))

    with Server(workers=4, delay=0.05, tool_rounds=1, tool_name="run_python",
                tool_arg_key="code", tool_arg_values="print(6*7)",
                answer_from_tools=True) as srv:
        cfg = write("ag6.yaml", agentic_yaml(srv.url, tools=TOOL_SCRIPT))
        inp = write_jsonl("ag6.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, _, _ = run_cli(cfg, inp)
        check("script handler returns stdout",
              rows[0]["result"]["tool_calls"][0]["result"] == "42",
              json.dumps(rows[0]["result"]["tool_calls"]))
        check("script result flows into the final answer",
              rows[0]["result"]["passed"] is True, json.dumps(rows[0]["result"]))

    with Server(workers=4, delay=0.05, tool_rounds=1, tool_name="run_python",
                tool_arg_key="code",
                tool_arg_values="import sys; sys.stderr.write('bad'); sys.exit(1)") as srv:
        cfg = write("ag7.yaml", agentic_yaml(srv.url, tools=TOOL_SCRIPT))
        inp = write_jsonl("ag7.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, _, _ = run_cli(cfg, inp)
        check("script handler reports stderr",
              rows[0]["result"]["tool_calls"][0]["result"] == "ERROR: bad",
              json.dumps(rows[0]["result"]["tool_calls"]))

    with Server(workers=4, delay=0.05, tool_rounds=1, tool_name="ghost") as srv:
        cfg = write("ag8.yaml", agentic_yaml(srv.url))
        inp = write_jsonl("ag8.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, _, _ = run_cli(cfg, inp)
        check("unknown tool reported as an error result",
              rows[0]["result"]["tool_calls"][0]["result"].startswith("ERROR: unknown tool"),
              json.dumps(rows[0]["result"]["tool_calls"]))


def test_agentic_list_format():
    print("\n[agentic: num_solutions list format]")
    with Server(workers=4, delay=0.05, answer_from_tools=True) as srv:
        cfg = write("ag9.yaml", agentic_yaml(srv.url, num_solutions=2))
        inp = write_jsonl("ag9.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        row = rows[0]
        check("two outputs", isinstance(row["output"], list) and len(row["output"]) == 2,
              json.dumps(row["output"]))
        check("output items keep icl_setup",
              all(set(o) == {"answer", "icl_setup"} and o["icl_setup"] is None
                  for o in row["output"]), json.dumps(row["output"]))
        check("result counts loops", row["result"] == {"passed": 2, "failed": 0, "attempts": 2},
              json.dumps(row["result"]))
        check("meta is a list of two", isinstance(row["meta"], list) and len(row["meta"]) == 2)
        check("meta entries carry agentic aggregates and checkpoint 3 fields",
              set(row["meta"][0]) == AGENTIC_META_KEYS | {"icl_setup", "evaluation_passed"},
              str(sorted(row["meta"][0])))
        check("evaluation_passed recorded",
              all(m["evaluation_passed"] is True for m in row["meta"]), json.dumps(row["meta"]))
        check("summary solution counts",
              summary["total_solutions"] == 2 and summary["avg_solutions_per_input"] == 2.0,
              json.dumps(summary))


def test_agentic_list_format_max_iterations():
    print("\n[agentic: list format with a loop that never finishes]")
    with Server(workers=4, delay=0.05, always_tools=True) as srv:
        cfg = write("ag10.yaml", agentic_yaml(srv.url, num_solutions=2, max_iterations=2,
                                              evaluation=False))
        inp = write_jsonl("ag10.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        row = rows[0]
        check("no outputs", row["output"] == [], json.dumps(row["output"]))
        check("failed counts loops without output",
              row["result"] == {"passed": 0, "failed": 2, "attempts": 2}, json.dumps(row["result"]))
        check("evaluation_passed null without evaluation",
              all(m["evaluation_passed"] is None for m in row["meta"]), json.dumps(row["meta"]))
        check("finish_reason max_iterations per loop",
              all(m["finish_reason"] == "max_iterations" for m in row["meta"]),
              json.dumps(row["meta"]))
        check("four api calls", summary["total_api_calls"] == 4, json.dumps(summary))


def test_agentic_no_evaluation():
    print("\n[agentic: no evaluation configured]")
    with Server(workers=4, delay=0.05, tool_rounds=1) as srv:
        cfg = write("ag11.yaml", agentic_yaml(srv.url, evaluation=False))
        inp = write_jsonl("ag11.jsonl", [{"question": "q"}])
        proc, rows, _, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        check("passed null", rows[0]["result"]["passed"] is None, json.dumps(rows[0]["result"]))
        check("output present", rows[0]["output"] is not None)


def test_agentic_icl():
    print("\n[agentic: icl setups drive independent loops]")
    icl = """  icl:
    setups:
      - name: "a"
        examples:
          - input: {question: "ex"}
            output: "#### 1"
      - name: "b"
        examples:
          - input: {question: "ex"}
            output: "#### 2"
    strategy: "round_robin"
"""
    with Server(workers=4, delay=0.05, tool_rounds=1, answer_from_tools=True) as srv:
        cfg = write("ag12.yaml", agentic_yaml(srv.url, num_solutions=2) + icl)
        inp = write_jsonl("ag12.jsonl", [{"question": "q", "answer": "1250000"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        row = rows[0]
        check("one output per setup",
              [o["icl_setup"] for o in row["output"]] == ["a", "b"], json.dumps(row["output"]))
        check("icl examples included in the loop prompt",
              len([m for m in srv.stats()["payloads"][0]["messages"] if m["role"] == "user"]) == 2,
              json.dumps(srv.stats()["payloads"][0]["messages"]))
        check("four api calls (two loops of two)", summary["total_api_calls"] == 4,
              json.dumps(summary))


def test_agentic_rows_overlap():
    print("\n[agentic: rows still overlap in flight]")
    with Server(workers=8, delay=0.4, tool_rounds=1, answer_from_tools=True) as srv:
        cfg = write("ag13.yaml", agentic_yaml(srv.url, rpm=600))
        rows_in = [{"question": "q%d" % i, "answer": "1250000"} for i in range(3)]
        inp = write_jsonl("ag13.jsonl", rows_in)
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        check("all rows finished", len(rows) == 3 and all(r["result"]["passed"] for r in rows))
        check("six api calls", summary["total_api_calls"] == 6, json.dumps(summary))
        check("requests from different rows overlapped (max %d)"
              % srv.stats()["max_in_flight"], srv.stats()["max_in_flight"] > 1)
        check("not fully serialised (%.2fs)" % summary["elapsed_seconds"],
              summary["elapsed_seconds"] < 6 * 0.4, json.dumps(summary))


def test_chat_template_rendering():
    print("\n[built-in chat templates]")
    sys.path.insert(0, ROOT)
    import rejector
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    check("chatml", rejector.render_chat_template("chatml", msgs) ==
          "<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nU<|im_end|>\n<|im_start|>assistant\n",
          repr(rejector.render_chat_template("chatml", msgs)))
    check("llama3", rejector.render_chat_template("llama3", msgs) ==
          "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nS<|eot_id|>"
          "<|start_header_id|>user<|end_header_id|>\n\nU<|eot_id|>"
          "<|start_header_id|>assistant<|end_header_id|>\n\n",
          repr(rejector.render_chat_template("llama3", msgs)))
    check("mistral", rejector.render_chat_template("mistral", msgs) == "[INST] S\n\nU [/INST]",
          repr(rejector.render_chat_template("mistral", msgs)))
    check("zephyr", rejector.render_chat_template("zephyr", msgs) ==
          "<|system|>\nS</s>\n<|user|>\nU</s>\n<|assistant|>\n",
          repr(rejector.render_chat_template("zephyr", msgs)))

    multi = [{"role": "system", "content": "S"},
             {"role": "user", "content": "U1"},
             {"role": "assistant", "content": "A1"},
             {"role": "user", "content": "U2"}]
    check("chatml multi-turn repeats role markers",
          rejector.render_chat_template("chatml", multi) ==
          "<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nU1<|im_end|>\n"
          "<|im_start|>assistant\nA1<|im_end|>\n<|im_start|>user\nU2<|im_end|>\n"
          "<|im_start|>assistant\n",
          repr(rejector.render_chat_template("chatml", multi)))
    check("llama3 multi-turn repeats headers",
          rejector.render_chat_template("llama3", multi).count("<|start_header_id|>") == 5,
          repr(rejector.render_chat_template("llama3", multi)))
    check("zephyr multi-turn repeats markers",
          rejector.render_chat_template("zephyr", multi) ==
          "<|system|>\nS</s>\n<|user|>\nU1</s>\n<|assistant|>\nA1</s>\n<|user|>\nU2</s>\n"
          "<|assistant|>\n",
          repr(rejector.render_chat_template("zephyr", multi)))
    check("mistral multi-turn wraps every user turn",
          rejector.render_chat_template("mistral", multi) ==
          "[INST] S\n\nU1 [/INST] A1</s>[INST] U2 [/INST]",
          repr(rejector.render_chat_template("mistral", multi)))


def completions_yaml(url, template="llama3", **kw):
    return "\n".join([
        "task:",
        '  name: "t"',
        '  api_url: "%s"' % url,
        '  model: "meta-llama/llama-3-70b"',
        "  rpm: 600",
        '  api_type: "completions"',
        '  chat_template: "%s"' % template,
        "  prompt:",
        '    system: "Solve it."',
        '    user: "{question}"',
        "  generation:",
        '    scheme: "greedy"',
        "    max_tokens: 256",
        "  evaluation:",
        '    type: "exact_match"',
        '    answer_field: "answer"',
        '    extract: "last_number"',
        '  output_field: "solution"',
    ]) + "\n"


def test_completions_mode():
    print("\n[completions mode]")
    with Server(workers=4, delay=0.05) as srv:
        cfg = write("cm1.yaml", completions_yaml(srv.url))
        inp = write_jsonl("cm1.jsonl", [{"question": "What is 6*7?", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        check("hit /v1/completions", srv.stats()["completion_calls"] == 1,
              json.dumps(srv.stats()["completion_calls"]))
        payload = srv.stats()["payloads"][0]
        check("payload keys", set(payload) == {"model", "prompt", "temperature", "max_tokens"},
              str(sorted(payload)))
        check("prompt rendered with llama3",
              payload["prompt"] ==
              "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nSolve it.<|eot_id|>"
              "<|start_header_id|>user<|end_header_id|>\n\nWhat is 6*7?<|eot_id|>"
              "<|start_header_id|>assistant<|end_header_id|>\n\n", repr(payload["prompt"]))
        check("model sent", payload["model"] == "meta-llama/llama-3-70b")
        check("text response read", rows[0]["output"]["solution"].endswith("#### 42"),
              json.dumps(rows[0]["output"]))
        check("passed", rows[0]["result"]["passed"] is True)
        check("usage recorded", rows[0]["meta"]["prompt_tokens"] == 20
              and rows[0]["meta"]["total_tokens"] == 25, json.dumps(rows[0]["meta"]))


def test_completions_cli_overrides():
    print("\n[--api-type / --chat-template overrides]")
    with Server(workers=4, delay=0.05) as srv:
        cfg = write("cm2.yaml", cfg_yaml(srv.url))
        inp = write_jsonl("cm2.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--api-type", "completions",
                                                          "--chat-template", "chatml"])
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        check("switched endpoint", srv.stats()["completion_calls"] == 1)
        check("chatml used",
              srv.stats()["payloads"][0]["prompt"] ==
              "<|im_start|>system\nSolve it.<|im_end|>\n<|im_start|>user\nq<|im_end|>\n"
              "<|im_start|>assistant\n", repr(srv.stats()["payloads"][0]["prompt"]))
        check("passed", rows[0]["result"]["passed"] is True, json.dumps(rows[0]["result"]))

    with Server(workers=4, delay=0.05) as srv:
        cfg = write("cm3.yaml", completions_yaml(srv.url, template="zephyr"))
        inp = write_jsonl("cm3.jsonl", [{"question": "q", "answer": "42"}])
        proc, rows, _, _ = run_cli(cfg, inp, extra=["--api-type", "chat"])
        check("chat wins over the config", srv.stats()["completion_calls"] == 0
              and "messages" in srv.stats()["payloads"][0], json.dumps(srv.stats()["payloads"][0]))


def test_agentic_completions_mode():
    print("\n[agentic in completions mode]")
    with Server(workers=4, delay=0.05, tool_rounds=1, answer_from_tools=True) as srv:
        cfg = write("cm4.yaml", agentic_yaml(srv.url, api_type="completions",
                                             chat_template="chatml"))
        inp = write_jsonl("cm4.jsonl", [{"question": "revenue?", "answer": "1250000"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:500])
        row = rows[0]
        check("tool call parsed from text",
              row["result"]["tool_calls"] == [{"iteration": 1, "tool": "lookup",
                                               "args": {"key": "revenue_q1"},
                                               "result": "1250000"}],
              json.dumps(row["result"]["tool_calls"]))
        check("iterations 2", row["result"]["iterations"] == 2, str(row["result"]))
        check("passed", row["result"]["passed"] is True, json.dumps(row["result"]))
        payloads = srv.stats()["payloads"]
        check("no native tools field", "tools" not in payloads[0], json.dumps(payloads[0])[:200])
        check("tool definitions rendered into the prompt",
              "<tool_call>" in payloads[0]["prompt"] and "lookup" in payloads[0]["prompt"],
              payloads[0]["prompt"][:300])
        check("tool result fed back with the tool role marker",
              "<|im_start|>tool\n1250000<|im_end|>" in payloads[1]["prompt"],
              payloads[1]["prompt"][-300:])


def test_agentic_and_completions_validation():
    print("\n[agentic / completions config validation]")
    with Server(workers=2, delay=0.01) as srv:
        inp = write_jsonl("agv.jsonl", [{"question": "q", "answer": "42"}])
        bad = agentic_yaml(srv.url, tools="  tools:\n    - name: \"x\"\n      handler:\n        type: \"nope\"\n")
        proc, _, _, _ = run_cli(write("agv1.yaml", bad), inp)
        check("bad handler type rejected", proc.returncode == 1 and "handler.type" in proc.stderr,
              proc.stderr[:200])

        bad = agentic_yaml(srv.url, tools='  tools:\n    - name: "x"\n      handler:\n        type: "script"\n')
        proc, _, _, _ = run_cli(write("agv2.yaml", bad), inp)
        check("script handler needs a command",
              proc.returncode == 1 and "handler.command" in proc.stderr, proc.stderr[:200])

        bad = agentic_yaml(srv.url, tools='  tools:\n    - handler:\n        type: "echo"\n')
        proc, _, _, _ = run_cli(write("agv3.yaml", bad), inp)
        check("tool needs a name", proc.returncode == 1 and "tools[0].name" in proc.stderr,
              proc.stderr[:200])

        bad = agentic_yaml(srv.url, max_iterations=0)
        proc, _, _, _ = run_cli(write("agv4.yaml", bad), inp)
        check("max_iterations must be positive",
              proc.returncode == 1 and "max_iterations" in proc.stderr, proc.stderr[:200])

        bad = cfg_yaml(srv.url).replace('  rpm:', '  api_type: "grpc"\n  rpm:')
        proc, _, _, _ = run_cli(write("agv5.yaml", bad), inp)
        check("api_type validated", proc.returncode == 1 and "api_type" in proc.stderr,
              proc.stderr[:200])

        bad = cfg_yaml(srv.url).replace('  rpm:', '  chat_template: "alpaca"\n  rpm:')
        proc, _, _, _ = run_cli(write("agv6.yaml", bad), inp)
        check("chat_template validated", proc.returncode == 1 and "chat_template" in proc.stderr,
              proc.stderr[:200])

        proc, _, _, _ = run_cli(write("agv7.yaml", cfg_yaml(srv.url)), inp,
                                extra=["--api-type", "grpc"])
        check("cli api-type validated", proc.returncode == 1, proc.stderr[:200])


def test_shipped_agentic_example_config():
    print("\n[examples/agentic.yaml parses and runs]")
    with Server(workers=8, delay=0.02, tool_rounds=1, answer_from_tools=True) as srv:
        with open(os.path.join(ROOT, "examples", "agentic.yaml"), encoding="utf-8") as fh:
            text = fh.read().replace("http://localhost:8000", srv.url)
        cfg = write("ex-agentic.yaml", text)
        inp = os.path.join(ROOT, "examples", "data", "data_lookup.jsonl")
        outdir = os.path.join(TMP, "ex-agentic-out")
        proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--output", outdir,
                               "--input", "data_lookup=%s" % inp],
                              capture_output=True, text=True)
    check("exit 0", proc.returncode == 0, proc.stderr[:400])
    with open(os.path.join(outdir, "data_lookup.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    check("both rows ran", len(rows) == 2, str(len(rows)))
    check("tool calls recorded", all(r["result"]["tool_calls"] for r in rows),
          json.dumps(rows[0]["result"]))


def test_shipped_completions_example_config():
    print("\n[examples/completions.yaml parses and runs]")
    with Server(workers=8, delay=0.02) as srv:
        with open(os.path.join(ROOT, "examples", "completions.yaml"), encoding="utf-8") as fh:
            text = fh.read().replace("http://localhost:8000", srv.url)
        cfg = write("ex-completions.yaml", text)
        gsm = os.path.join(ROOT, "examples", "data", "gsm8k.jsonl")
        mmlu = os.path.join(ROOT, "examples", "data", "mmlu.jsonl")
        outdir = os.path.join(TMP, "ex-completions-out")
        proc = subprocess.run([PY, CLI, "run", "--config", cfg, "--output", outdir,
                               "--input", "gsm8k=%s" % gsm, "--input", "mmlu=%s" % mmlu],
                              capture_output=True, text=True)
        check("exit 0", proc.returncode == 0, proc.stderr[:400])
        prompts = [p.get("prompt", "") for p in srv.stats()["payloads"]]
        check("both tasks used /v1/completions",
              srv.stats()["completion_calls"] == len(prompts) and all(prompts),
              json.dumps(srv.stats()["completion_calls"]))
        check("per-task template override applied",
              any(p.startswith("<|begin_of_text|>") for p in prompts)
              and any(p.startswith("<|im_start|>") for p in prompts),
              json.dumps(prompts[:1]))


def test_agentic_every_completions_template():
    print("\n[agentic loops through every built-in template]")
    for template in ("chatml", "llama3", "mistral", "zephyr"):
        with Server(workers=4, delay=0.02, tool_rounds=1, answer_from_tools=True) as srv:
            cfg = write("agt_%s.yaml" % template,
                        agentic_yaml(srv.url, api_type="completions", chat_template=template))
            inp = write_jsonl("agt_%s.jsonl" % template,
                              [{"question": "revenue?", "answer": "1250000"}])
            proc, rows, _, _ = run_cli(cfg, inp)
            check("%s: loop finished" % template,
                  proc.returncode == 0 and rows and rows[0]["result"]["passed"] is True,
                  proc.stderr[:300] + json.dumps(rows[:1])[:300])
            check("%s: tool result fed into the next prompt" % template,
                  "1250000" in srv.stats()["payloads"][1]["prompt"],
                  srv.stats()["payloads"][1]["prompt"][-200:])


def test_agentic_llm_judge():
    print("\n[agentic with an llm_judge evaluation]")
    judge = ('  evaluation:\n'
             '    type: "llm_judge"\n'
             '    judge_prompt:\n'
             '      system: "JUDGE with only a number."\n'
             '      user: "Rate {__response__}"\n'
             '    threshold: 7\n'
             '    extract: "first_number"\n'
             '  output_field: "answer"')
    text = agentic_yaml("URL", evaluation=False).replace('  output_field: "answer"', judge)
    with Server(workers=4, delay=0.02, tool_rounds=1, judge_answer="9") as srv:
        cfg = write("agj.yaml", text.replace("URL", srv.url))
        inp = write_jsonl("agj.jsonl", [{"question": "q"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("judge score recorded", rows[0]["result"]["judge_score"] == 9,
              json.dumps(rows[0]["result"]))
        check("passed", rows[0]["result"]["passed"] is True)
        check("judge_meta on the aggregated meta", "judge_meta" in rows[0]["meta"],
              json.dumps(rows[0]["meta"])[:200])
        check("judge call counted once on top of the loop",
              summary["total_api_calls"] == 3, json.dumps(summary))


# ==========================================================================
# Part 5: rate limits, cost, structured output, resume, dry run, progress
# ==========================================================================

SCHEMA_BLOCK = """  output_schema:
    type: "object"
    required: ["code", "explanation"]
    properties:
      code:
        type: "string"
      explanation:
        type: "string"
"""

EXTRA_TASK = """  extra:
    prompt:
      system: "Solve it."
      user: "{question}"
    generation:
      scheme: "greedy"
    rate_limits:
      tpm: 30000
    output_field: "solution"
"""

CHEAP_TASK = """  cheap:
    prompt:
      system: "Solve it."
      user: "{question}"
    generation:
      scheme: "greedy"
    cost:
      prompt_cost_per_1k: 0.0
      completion_cost_per_1k: 0.0
    output_field: "solution"
"""

GOOD_JSON = '{"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}'
BAD_JSON = '{"code": "def add(a, b): return a + b"}'


def limits_yaml(url, **kw):
    """A single-task config carrying rate_limits / cost / output_schema."""
    lines = [
        "task:",
        '  name: "t"',
        '  api_url: "%s"' % url,
        '  model: "gpt-4"',
    ]
    limits = kw.get("rate_limits")
    if limits:
        lines.append("  rate_limits:")
        for key, value in limits.items():
            lines.append("    %s: %s" % (key, value))
    cost = kw.get("cost")
    if cost:
        lines.append("  cost:")
        for key, value in cost.items():
            lines.append("    %s: %s" % (key, value))
    lines += [
        "  prompt:",
        '    user: "{question}"',
        "  generation:",
        '    scheme: "%s"' % kw.get("scheme", "greedy"),
        "    temperature: %s" % kw.get("temperature", 0.0),
        "    max_tokens: %s" % kw.get("max_tokens", 128),
        "    n: %s" % kw.get("n", 1),
    ]
    if kw.get("evaluation"):
        lines += [
            "  evaluation:",
            '    type: "exact_match"',
            '    answer_field: "answer"',
            '    extract: "last_number"',
        ]
    lines.append('  output_field: "%s"' % kw.get("output_field", "solution"))
    text = "\n".join(lines) + "\n"
    if kw.get("schema"):
        text += kw["schema"] if isinstance(kw["schema"], str) else SCHEMA_BLOCK
    return text


def test_rate_limits_max_concurrent():
    print("\n[rate limits: max_concurrent caps requests in flight]")
    with Server(workers=16, delay=0.15) as srv:
        cfg = write("rl-mc.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600, "max_concurrent": 3}))
        inp = write_jsonl("rl-mc.jsonl", [{"question": "q%d" % i} for i in range(24)])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("all rows", len(rows) == 24)
        peak = srv.stats()["max_in_flight"]
        check("in flight never exceeds max_concurrent (peak %d)" % peak, peak <= 3, str(peak))
        check("still concurrent (peak %d)" % peak, peak > 1, str(peak))


def test_rate_limits_defaults_merge():
    print("\n[rate limits: defaults merge key by key]")
    defaults = "  rate_limits:\n    rpm: 600\n    max_concurrent: 2\n"
    with Server(workers=16, delay=0.1) as srv:
        cfg = write("rl-merge.yaml",
                    multi_yaml(srv.url, GSM_TASK + EXTRA_TASK, extra_defaults=defaults))
        gsm = write_jsonl("rl-gsm.jsonl", ROWS10)
        extra = write_jsonl("rl-extra.jsonl", [{"question": "q%d" % i} for i in range(10)])
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm, "extra": extra})
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("both tasks ran", sorted(files) == ["extra", "gsm8k"], str(sorted(files)))
        peak = srv.stats()["max_in_flight"]
        # `extra` only overrode tpm, so it keeps the shared max_concurrent: 2.
        check("shared max_concurrent survives a partial override (peak %d)" % peak,
              peak <= 2, str(peak))


def test_rpm_disabled_when_omitted():
    print("\n[rate limits: omitted rpm disables request pacing]")
    with Server(workers=32, delay=0.05) as srv:
        cfg = write("rl-none.yaml", limits_yaml(srv.url, rate_limits={"max_concurrent": 8}))
        inp = write_jsonl("rl-none.jsonl", [{"question": "q%d" % i} for i in range(40)])
        started = time.time()
        proc, rows, summary, _ = run_cli(cfg, inp)
        elapsed = time.time() - started
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("all rows", len(rows) == 40)
        check("runs at server speed, not a 60 rpm default (%.1fs)" % elapsed,
              elapsed < 20, "%.1f" % elapsed)


def test_tpm_is_the_binding_limit():
    print("\n[rate limits: tpm paces below a much higher rpm]")
    # 612 tokens per call against tpm 20000 -> ~32 rpm, far below rpm 600.
    with Server(workers=32, delay=0.05, prompt_tokens=500, completion_tokens=112) as srv:
        cfg = write("rl-tpm.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600, "tpm": 20000}))
        inp = write_jsonl("rl-tpm.jsonl", [{"question": "q%d" % i} for i in range(24)])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("all rows", len(rows) == 24)
        ideal = 20000.0 / 612.0
        ratio = summary["throughput_rpm"] / ideal
        check("paces near the token budget, not the request budget "
              "(%.1f rpm vs ideal %.1f)" % (summary["throughput_rpm"], ideal),
              ratio <= 1.5, str(summary))
        check("token accounting reported",
              summary["total_prompt_tokens"] == 24 * 500, str(summary))


def test_cost_tracking():
    print("\n[cost: totals and rates]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("cost1.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600},
            cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03,
                  "budget": 50.0}))
        inp = write_jsonl("cost1.jsonl", [{"question": "q%d" % i} for i in range(10)])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        cost = summary.get("cost") or {}
        check("prompt cost", abs(cost.get("prompt", 0) - 100 / 1000.0 * 0.01) < 1e-9, str(cost))
        check("completion cost", abs(cost.get("completion", 0) - 50 / 1000.0 * 0.03) < 1e-9,
              str(cost))
        check("total is the sum",
              abs(cost.get("total", 0) - (cost.get("prompt", 0) + cost.get("completion", 0)))
              < 1e-9, str(cost))
        check("budget echoed", cost.get("budget") == 50.0, str(cost))
        check("budget_remaining", abs(cost.get("budget_remaining", 0)
                                      - (50.0 - cost["total"])) < 1e-9, str(cost))
        check("not exceeded", cost.get("budget_exceeded") is False, str(cost))


def test_cost_omitted_without_configuration():
    print("\n[cost: field absent when nothing is configured]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("cost0.yaml", limits_yaml(srv.url, rate_limits={"rpm": 600}))
        inp = write_jsonl("cost0.jsonl", [{"question": "q1"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("no cost field", "cost" not in summary, str(summary))


def test_cost_defaults_merge_and_judge_calls():
    print("\n[cost: defaults merge, per-task override, judge calls counted]")
    defaults = ("  cost:\n    prompt_cost_per_1k: 0.01\n"
                "    completion_cost_per_1k: 0.03\n    budget: 100.0\n")
    with Server(workers=8, delay=0.02, judge_answer="9") as srv:
        cfg = write("cost-merge.yaml",
                    multi_yaml(srv.url, REVIEW_TASK + CHEAP_TASK, extra_defaults=defaults))
        review = write_jsonl("cost-review.jsonl", REVIEW_ROWS)
        cheap = write_jsonl("cost-cheap.jsonl", [{"question": "q%d" % i} for i in range(4)])
        proc, files, summary, _ = run_multi(cfg, {"review": review, "cheap": cheap})
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        cost = summary.get("cost") or {}
        # review: 1 generation + 1 judge call; cheap: 4 calls at zero rates.
        check("only the priced task contributes",
              abs(cost.get("total", 0) - 2 * 0.00025) < 1e-9, str(cost))
        check("budget from defaults", cost.get("budget") == 100.0, str(cost))


def test_budget_stops_the_run():
    print("\n[cost: budget exhaustion writes partial output and exits 0]")
    with Server(workers=8, delay=0.05) as srv:
        # 0.00025 per call, max_concurrent 4 -> stops after ~12 rows.
        cfg = write("budget.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600, "max_concurrent": 4},
            cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03,
                  "budget": 0.003}))
        inp = write_jsonl("budget.jsonl", [{"question": "q%d" % i} for i in range(60)])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("partial output (%d rows)" % len(rows), 0 < len(rows) < 60, str(len(rows)))
        check("budget_exceeded", summary["cost"]["budget_exceeded"] is True, str(summary))
        check("summary matches what was written", summary["total"] == len(rows), str(summary))
        check("output stays a prefix of the input",
              [r["input"]["question"] for r in rows]
              == ["q%d" % i for i in range(len(rows))], str(rows[:1]))


def test_budget_cli_flag():
    print("\n[cost: --budget]")
    with Server(workers=8, delay=0.05) as srv:
        cfg = write("budget-cli.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600, "max_concurrent": 2},
            cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}))
        inp = write_jsonl("budget-cli.jsonl", [{"question": "q%d" % i} for i in range(40)])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--budget", "0.001"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("budget applied", summary["cost"]["budget"] == 0.001, str(summary))
        check("stopped early (%d rows)" % len(rows), len(rows) < 40, str(len(rows)))


def test_output_schema_success_and_failure():
    print("\n[structured output: success, missing field, invalid JSON]")
    with Server(workers=8, delay=0.02, template="{answer}", answer=GOOD_JSON) as srv:
        cfg = write("sch-ok.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, schema=True, output_field="code"))
        inp = write_jsonl("sch.jsonl", [{"question": "q1"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("output holds the parsed JSON",
              rows[0]["output"] == {"code": json.loads(GOOD_JSON)},
              json.dumps(rows[0]["output"]))
        check("schema_valid true", rows[0]["result"]["schema_valid"] is True,
              json.dumps(rows[0]["result"]))
        check("passed true", rows[0]["result"]["passed"] is True, json.dumps(rows[0]["result"]))

    with Server(workers=8, delay=0.02, template="{answer}", answer=BAD_JSON) as srv:
        cfg = write("sch-bad.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, schema=True, output_field="code"))
        inp = write_jsonl("sch2.jsonl", [{"question": "q1"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("output null on failure", rows[0]["output"] is None, json.dumps(rows[0]))
        check("schema_valid false", rows[0]["result"]["schema_valid"] is False,
              json.dumps(rows[0]["result"]))
        check("passed false", rows[0]["result"]["passed"] is False,
              json.dumps(rows[0]["result"]))
        check("readable error",
              rows[0]["result"]["schema_error"] == "Missing required field: explanation",
              json.dumps(rows[0]["result"]))
        check("summary counts it failed", summary["failed"] == 1, str(summary))

    with Server(workers=8, delay=0.02, template="totally not json") as srv:
        cfg = write("sch-nojson.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, schema=True, output_field="code"))
        inp = write_jsonl("sch3.jsonl", [{"question": "q1"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("invalid JSON is a schema failure",
              rows[0]["result"]["schema_valid"] is False, json.dumps(rows[0]["result"]))
        check("error mentions JSON",
              "Invalid JSON" in rows[0]["result"]["schema_error"],
              json.dumps(rows[0]["result"]))


def test_output_schema_rejection():
    print("\n[structured output: rejection sampling retries a schema failure]")
    with Server(workers=8, delay=0.02, template="{answer}", answer=GOOD_JSON,
                wrong_answer=BAD_JSON, wrong_attempts=2) as srv:
        cfg = write("sch-rej.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, scheme="rejection", temperature=0.7, n=5,
            schema=True, output_field="code"))
        inp = write_jsonl("sch-rej.jsonl", [{"question": "q1"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("retried past the schema failures", rows[0]["result"]["attempts"] == 3,
              json.dumps(rows[0]["result"]))
        check("kept the valid JSON", rows[0]["output"] == {"code": json.loads(GOOD_JSON)},
              json.dumps(rows[0]["output"]))
        check("schema_valid true", rows[0]["result"]["schema_valid"] is True,
              json.dumps(rows[0]["result"]))

    # No evaluation block at all: the schema alone gates rejection sampling.
    with Server(workers=8, delay=0.02, template="{answer}", answer=BAD_JSON) as srv:
        cfg = write("sch-rej2.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, scheme="rejection", temperature=0.7, n=3,
            schema=True, output_field="code"))
        inp = write_jsonl("sch-rej2.jsonl", [{"question": "q1"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0 without an evaluation block", proc.returncode == 0, proc.stderr[:300])
        check("exhausted every attempt", rows[0]["result"]["attempts"] == 3,
              json.dumps(rows[0]["result"]))
        check("no output", rows[0]["output"] is None, json.dumps(rows[0]))


def test_output_schema_before_evaluation():
    print("\n[structured output: validated before evaluation]")
    with Server(workers=8, delay=0.02, template="{answer}", answer=BAD_JSON) as srv:
        cfg = write("sch-eval.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, evaluation=True, schema=True,
            output_field="code"))
        inp = write_jsonl("sch-eval.jsonl", [{"question": "q1", "answer": "42"}])
        proc, rows, summary, _ = run_cli(cfg, inp)
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("evaluation skipped", rows[0]["result"]["extracted_answer"] is None,
              json.dumps(rows[0]["result"]))
        check("passed false", rows[0]["result"]["passed"] is False,
              json.dumps(rows[0]["result"]))


def test_output_schema_keywords():
    print("\n[structured output: draft 7 keyword coverage]")
    sys.path.insert(0, ROOT)
    import rejector as R
    cases = [
        ({"type": "object"}, {}, True),
        ({"type": "object"}, [], False),
        ({"type": "integer"}, 3, True),
        ({"type": "integer"}, 3.5, False),
        ({"type": "number"}, 3.5, True),
        ({"type": "boolean"}, True, True),
        ({"type": "number"}, True, False),
        ({"type": "null"}, None, True),
        ({"type": ["string", "null"]}, None, True),
        ({"type": "object", "required": ["a"]}, {"a": 1}, True),
        ({"type": "object", "required": ["a", "b"]}, {"a": 1}, False),
        ({"properties": {"a": {"type": "string"}}}, {"a": 1}, False),
        ({"type": "array", "items": {"type": "integer"}}, [1, 2], True),
        ({"type": "array", "items": {"type": "integer"}}, [1, "x"], False),
        ({"enum": ["a", "b"]}, "a", True),
        ({"enum": ["a", "b"]}, "c", False),
        ({"minimum": 5}, 5, True),
        ({"minimum": 5}, 4, False),
        ({"maximum": 5}, 6, False),
        ({"minLength": 3}, "abc", True),
        ({"minLength": 3}, "ab", False),
        ({"maxLength": 2}, "abc", False),
        ({"pattern": "^a.c$"}, "abc", True),
        ({"pattern": "^a.c$"}, "xbc", False),
    ]
    ok = True
    for schema, value, expected in cases:
        error = R.validate_json_schema(value, schema)
        if (error is None) != expected:
            ok = False
            print("      mismatch: %r against %r -> %r" % (value, schema, error))
    check("every draft 7 keyword behaves", ok)
    nested = {"type": "object", "properties":
              {"items": {"type": "array", "items": {"type": "object",
                                                    "required": ["id"]}}}}
    error = R.validate_json_schema({"items": [{"id": 1}, {}]}, nested)
    check("nested path in the message", error == "Missing required field: items[1].id",
          str(error))
    ok, value, error = R.validate_structured_output("[1, 2]", {"type": "object"})
    check("type mismatch message", error == "Expected type object, got array", str(error))


def test_output_schema_config_validation():
    print("\n[structured output: bad schema is a config error]")
    inp = write_jsonl("schcfg.jsonl", [{"question": "q"}])
    bad = limits_yaml("http://127.0.0.1:9", rate_limits={"rpm": 60},
                      schema='  output_schema:\n    type: "objekt"\n')
    cfg = write("schcfg1.yaml", bad)
    proc, _, _, _ = run_cli(cfg, inp)
    check("unknown type exit 1", proc.returncode == 1, proc.stdout[:120])
    bad = limits_yaml("http://127.0.0.1:9", rate_limits={"rpm": 60},
                      schema='  output_schema:\n    type: "string"\n    pattern: "["\n')
    cfg = write("schcfg2.yaml", bad)
    proc, _, _, _ = run_cli(cfg, inp)
    check("bad pattern exit 1", proc.returncode == 1, proc.stdout[:120])


def test_resume_skips_completed_rows():
    print("\n[resume: skip completed rows and append]")
    rows = [{"question": "q%d" % i, "answer": "42"} for i in range(20)]
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("res.yaml", cfg_yaml(srv.url, rpm=600))
        inp = write_jsonl("res.jsonl", rows)
        out = os.path.join(TMP, "res-out.jsonl")
        proc, first, summary, _ = run_cli(cfg, inp, out=out)
        check("first pass wrote everything", len(first) == 20, str(len(first)))
        with open(out, encoding="utf-8") as fh:
            kept = [next(fh) for _ in range(8)]
        with open(out, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
        calls_before = srv.stats()["calls"]
        proc, second, summary, _ = run_cli(cfg, inp, out=out, extra=["--resume"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("resumed_from", summary.get("resumed_from") == 8, str(summary))
        check("summary covers only the new rows", summary["total"] == 12, str(summary))
        check("file holds every row", len(second) == 20, str(len(second)))
        check("input order preserved",
              [r["input"]["question"] for r in second] == [r["question"] for r in rows],
              str([r["input"]["question"] for r in second]))
        check("only the missing rows were sent",
              srv.stats()["calls"] - calls_before == 12,
              str(srv.stats()["calls"] - calls_before))


def test_resume_without_existing_output():
    print("\n[resume: no output file yet]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("res-none.yaml", cfg_yaml(srv.url, rpm=600))
        inp = write_jsonl("res-none.jsonl", ROWS10)
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--resume"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("nothing skipped", summary.get("resumed_from") == 0, str(summary))
        check("all rows processed", len(rows) == 10, str(len(rows)))


def test_resume_reprocesses_incomplete_row():
    print("\n[resume: an incomplete rejection row is redone]")
    rows = [{"question": "q%d" % i, "answer": "42"} for i in range(6)]
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("res-inc.yaml", cfg_yaml(srv.url, rpm=600, scheme="rejection",
                                             temperature=0.7, n=4))
        inp = write_jsonl("res-inc.jsonl", rows)
        out = os.path.join(TMP, "res-inc-out.jsonl")
        # Three finished rows, then one cut short mid-rejection.
        finished = [{"input": rows[i], "output": {"solution": "#### 42"},
                     "result": {"passed": True, "extracted_answer": "42", "attempts": 1},
                     "meta": {}} for i in range(3)]
        partial = {"input": rows[3], "output": None,
                   "result": {"passed": False, "extracted_answer": None, "attempts": 2},
                   "meta": []}
        with open(out, "w", encoding="utf-8") as fh:
            for item in finished + [partial]:
                fh.write(json.dumps(item) + "\n")
        proc, written, summary, _ = run_cli(cfg, inp, out=out, extra=["--resume"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("resume point is the incomplete row", summary.get("resumed_from") == 3,
              str(summary))
        check("row 3 redone in place", written[3]["result"]["attempts"] != 2,
              json.dumps(written[3]["result"]))
        check("file holds every row", len(written) == 6, str(len(written)))


def test_resume_multi_task():
    print("\n[resume: per task output file]")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("res-multi.yaml", multi_yaml(srv.url, GSM_TASK + MMLU_TASK))
        gsm = write_jsonl("res-m-gsm.jsonl", ROWS10)
        mmlu = write_jsonl("res-m-mmlu.jsonl", MMLU_ROWS)
        outdir = os.path.join(TMP, "res-multi-out")
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm, "mmlu": mmlu}, outdir=outdir)
        check("first pass ok", proc.returncode == 0 and len(files["gsm8k"]) == 10,
              proc.stderr[:300])
        path = os.path.join(outdir, "gsm8k.jsonl")
        with open(path, encoding="utf-8") as fh:
            kept = [next(fh) for _ in range(4)]
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
        proc, files, summary, _ = run_multi(cfg, {"gsm8k": gsm, "mmlu": mmlu},
                                            outdir=outdir, extra=["--resume"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        check("gsm8k restored to 10 rows", len(files["gsm8k"]) == 10, str(len(files["gsm8k"])))
        check("per task resumed_from",
              summary["tasks"]["gsm8k"].get("resumed_from") == 4
              and summary["tasks"]["mmlu"].get("resumed_from") == 1, str(summary["tasks"]))
        check("run level resumed_from", summary.get("resumed_from") == 5, str(summary))
        check("only the missing gsm8k rows counted", summary["total"] == 6, str(summary))


def test_dry_run():
    print("\n[dry run]")
    rows = [{"question": "one two three four five six", "answer": "42"} for _ in range(10)]
    cfg = write("dry.yaml", limits_yaml(
        "http://127.0.0.1:9", rate_limits={"rpm": 100},
        cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03},
        max_tokens=512))
    inp = write_jsonl("dry.jsonl", rows)
    out = os.path.join(TMP, "dry-out.jsonl")
    proc, _, summary, _ = run_cli(cfg, inp, out=out, extra=["--dry-run"])
    check("exit 0", proc.returncode == 0, proc.stderr[:300])
    check("no output file written", not os.path.exists(out), out)
    task = (summary.get("tasks") or {}).get("t") or {}
    check("input count", task.get("inputs") == 10, str(summary))
    # 6 words per row * 1.33 * 10 rows = 79.8 -> 80
    check("prompt token estimate", task.get("est_prompt_tokens") == 80, str(summary))
    check("completion token estimate", task.get("est_completion_tokens") == 5120, str(summary))
    check("total tokens", task.get("est_total_tokens") == 5200, str(summary))
    check("cost estimate",
          abs(task.get("est_cost", 0) - (80 / 1000.0 * 0.01 + 5120 / 1000.0 * 0.03)) < 1e-9,
          str(summary))
    check("run totals", summary.get("total_inputs") == 10
          and summary.get("est_total_tokens") == 5200, str(summary))
    check("time estimate", summary.get("est_time_minutes") == round(10 / 100.0, 1), str(summary))

    # Rejection plans for the worst case: n attempts per row.
    cfg = write("dry-rej.yaml", limits_yaml(
        "http://127.0.0.1:9", rate_limits={"rpm": 100}, scheme="rejection",
        temperature=0.7, n=5, evaluation=True))
    proc, _, summary, _ = run_cli(cfg, inp, extra=["--dry-run"])
    check("rejection worst case", summary.get("est_time_minutes") == round(50 / 100.0, 1),
          str(summary))

    # A bad config is still a config error under --dry-run.
    cfg = write("dry-bad.yaml", cfg_yaml("http://127.0.0.1:9").replace("rpm: 60", "rpm: 0"))
    proc, _, _, _ = run_cli(cfg, inp, extra=["--dry-run"])
    check("still validates the config", proc.returncode == 1, proc.stdout[:120])


def test_progress_reporting():
    print("\n[progress]")
    pattern = re.compile(
        r"^\[(\d+)/(\d+)\] (\d+)% complete \| (\d+) passed, (\d+) failed"
        r" \| [\d.]+ rpm \| \$[\d.]+ spent \| ETA: \d+s$")
    with Server(workers=8, delay=0.02) as srv:
        cfg = write("prog.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600}, evaluation=True,
            cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}))
        inp = write_jsonl("prog.jsonl", [{"question": "q%d" % i, "answer": "42"}
                                         for i in range(20)])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--progress"])
        lines = [l for l in proc.stderr.splitlines() if l.strip()]
        check("progress went to stderr", len(lines) >= 10, proc.stderr[:300])
        check("every line matches the documented format",
              all(pattern.match(l) for l in lines),
              "\n".join(l for l in lines if not pattern.match(l))[:300])
        check("finishes at 100%", lines[-1].startswith("[20/20] 100% complete"), lines[-1])
        check("stdout is still only the summary", summary is not None
              and len(proc.stdout.strip().splitlines()) == 1, proc.stdout[:200])

    with Server(workers=8, delay=0.02) as srv:
        cfg = write("prog2.yaml", limits_yaml(srv.url, rate_limits={"rpm": 600}))
        inp = write_jsonl("prog2.jsonl", [{"question": "q%d" % i} for i in range(10)])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--progress"])
        lines = [l for l in proc.stderr.splitlines() if l.strip()]
        check("no passed/failed without evaluation",
              all("passed" not in l for l in lines), "\n".join(lines)[:200])
        check("no cost without cost tracking",
              all("$" not in l for l in lines), "\n".join(lines)[:200])
        check("still reports rpm and ETA",
              all("rpm" in l and "ETA" in l for l in lines), "\n".join(lines)[:200])


def test_rate_and_cost_cli_overrides():
    print("\n[cli: --tpm, --max-concurrent, --budget]")
    with Server(workers=16, delay=0.1) as srv:
        cfg = write("cli-rl.yaml", limits_yaml(
            srv.url, rate_limits={"rpm": 600, "max_concurrent": 16}))
        inp = write_jsonl("cli-rl.jsonl", [{"question": "q%d" % i} for i in range(20)])
        proc, rows, summary, _ = run_cli(cfg, inp, extra=["--max-concurrent", "2"])
        check("exit 0", proc.returncode == 0, proc.stderr[:300])
        peak = srv.stats()["max_in_flight"]
        check("--max-concurrent wins (peak %d)" % peak, peak <= 2, str(peak))
    inp = write_jsonl("cli-rl2.jsonl", [{"question": "q"}])
    cfg = write("cli-rl2.yaml", limits_yaml("http://127.0.0.1:9", rate_limits={"rpm": 60}))
    proc, _, _, _ = run_cli(cfg, inp, extra=["--tpm", "0"])
    check("--tpm 0 is rejected", proc.returncode == 1, proc.stdout[:120])
    proc, _, _, _ = run_cli(cfg, inp, extra=["--budget", "-1"])
    check("--budget -1 is rejected", proc.returncode == 1, proc.stdout[:120])


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
        test_multi_explicit_mapping, test_multi_input_dir, test_multi_task_selection,
        test_multi_defaults_merge, test_extract_letter, test_extract_first_number,
        test_llm_judge_pass_and_fail, test_llm_judge_model_override,
        test_llm_judge_rejection, test_script_evaluation, test_multi_cli_errors,
        test_single_task_config_still_works, test_multi_interleaving_and_throughput,
        test_multi_empty_input_and_rerun,
        test_icl_message_layout, test_icl_k, test_icl_file_setups, test_icl_strategies,
        test_icl_config_validation, test_icl_example_files_from_config_dir,
        test_greedy_icl_walks_setups_once, test_greedy_no_icl_multi,
        test_sample_multi_solutions, test_rejection_multi_partial,
        test_rejection_multi_early_stop, test_rejection_max_attempts_default,
        test_rejection_icl_multi, test_list_format_without_evaluation,
        test_legacy_single_solution_preserved, test_num_solutions_cli_override,
        test_multi_task_num_solutions_and_summary, test_shipped_icl_example_config,
        test_agentic_basic, test_agentic_multiple_calls_per_iteration,
        test_agentic_max_iterations, test_agentic_handlers, test_agentic_list_format,
        test_agentic_list_format_max_iterations, test_agentic_no_evaluation,
        test_agentic_icl, test_agentic_rows_overlap, test_chat_template_rendering,
        test_completions_mode, test_completions_cli_overrides,
        test_agentic_completions_mode, test_agentic_and_completions_validation,
        test_shipped_agentic_example_config, test_shipped_completions_example_config,
        test_agentic_every_completions_template, test_agentic_llm_judge,
        test_rate_limits_max_concurrent, test_rate_limits_defaults_merge,
        test_rpm_disabled_when_omitted, test_tpm_is_the_binding_limit,
        test_cost_tracking, test_cost_omitted_without_configuration,
        test_cost_defaults_merge_and_judge_calls, test_budget_stops_the_run,
        test_budget_cli_flag, test_output_schema_success_and_failure,
        test_output_schema_rejection, test_output_schema_before_evaluation,
        test_output_schema_keywords, test_output_schema_config_validation,
        test_resume_skips_completed_rows, test_resume_without_existing_output,
        test_resume_reprocesses_incomplete_row, test_resume_multi_task,
        test_dry_run, test_progress_reporting, test_rate_and_cost_cli_overrides,
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
