#!/usr/bin/env python3
"""End-to-end tests for part 5: rate limits, cost, schemas, resume, dry run, progress."""
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
CLI = os.path.join(ROOT, "rejector.py")
TMP = os.path.join(ROOT, "tests", "_tmp5")
os.makedirs(TMP, exist_ok=True)

results = []


def check(name, actual, expected):
    ok = actual == expected
    results.append((ok, name))
    print(("  ok   " if ok else "  FAIL ") + f"{name}: {actual!r}" + ("" if ok else f" != {expected!r}"))


def check_true(name, cond, detail=""):
    results.append((bool(cond), name))
    print(("  ok   " if cond else "  FAIL ") + f"{name} {detail}")


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    def __init__(self, script="mock5.py", **kw):
        self.port = kw.pop("port", None) or free_port()
        args = [PY, os.path.join(ROOT, "tests", script), "--port", str(self.port)]
        for k, v in kw.items():
            args += ["--" + k.replace("_", "-"), str(v)]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/stats", timeout=0.5).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    def stats(self):
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/stats").read())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()


def write(path, text):
    full = os.path.join(TMP, path)
    with open(full, "w") as fh:
        fh.write(text)
    return full


def write_jsonl(path, rows):
    return write(path, "".join(json.dumps(r) + "\n" for r in rows))


def cli(config, inp, out, *extra):
    outp = out if os.path.isabs(out) else os.path.join(TMP, out)
    proc = subprocess.run([PY, CLI, "run", "--config", config, "--input", inp,
                           "--output", outp, *extra], capture_output=True, text=True, cwd=ROOT)
    rows = []
    if os.path.exists(outp) and os.path.isfile(outp):
        with open(outp) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    summary = None
    if proc.stdout.strip():
        try:
            summary = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            summary = None
    return proc, rows, summary


DATA = [{"question": f"What is {i} + 1?", "answer": str(i + 1)} for i in range(1, 21)]

BASE = """task:
  name: "t"
  api_url: "http://127.0.0.1:{port}"
  model: "gpt-4"
  prompt:
    system: "Solve it. Final answer after ####."
    user: "{{question}}"
  generation:
    scheme: "{scheme}"
    temperature: {temp}
    max_tokens: {max_tokens}
    n: {n}
  output_field: "solution"
{extra}"""


def cfg(name, port, scheme="greedy", temp=0.0, n=1, max_tokens=256, extra=""):
    return write(name, BASE.format(port=port, scheme=scheme, temp=temp, n=n,
                                   max_tokens=max_tokens, extra=extra))


EVAL = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
"""

SCHEMA = """  output_schema:
    type: "object"
    required: ["code", "explanation"]
    properties:
      code:
        type: "string"
      explanation:
        type: "string"
"""


def main():
    data = write_jsonl("data.jsonl", DATA)

    print("\n[1] max_concurrent caps in-flight requests")
    with Server(mode="text", workers=20, latency=0.1) as srv:
        c = cfg("mc.yaml", srv.port, extra=EVAL + "  rate_limits:\n    max_concurrent: 3\n    rpm: 600\n")
        proc, rows, summary = cli(c, data, "mc.jsonl")
        check("exit", proc.returncode, 0)
        check("rows", len(rows), 20)
        check_true("max_inflight <= 3", srv.stats()["max_inflight"] <= 3, str(srv.stats()["max_inflight"]))
        check_true("max_inflight > 1", srv.stats()["max_inflight"] > 1, str(srv.stats()["max_inflight"]))

    print("\n[2] --max-concurrent CLI override")
    with Server(mode="text", workers=20, latency=0.1) as srv:
        c = cfg("mc2.yaml", srv.port, extra=EVAL)
        proc, rows, summary = cli(c, data, "mc2.jsonl", "--max-concurrent", "2")
        check("exit", proc.returncode, 0)
        check_true("max_inflight <= 2", srv.stats()["max_inflight"] <= 2, str(srv.stats()["max_inflight"]))

    print("\n[3] rpm sliding window paces requests")
    with Server(mode="text", workers=20, latency=0.01) as srv:
        rows_in = write_jsonl("d30.jsonl", DATA[:12])
        c = cfg("rpm.yaml", srv.port, extra=EVAL + "  rate_limits:\n    rpm: 6\n")
        started = time.time()
        proc, rows, summary = cli(c, rows_in, "rpm.jsonl")
        elapsed = time.time() - started
        check("exit", proc.returncode, 0)
        check("rows", len(rows), 12)
        check_true("first 6 burst, rest waits ~60s? (bounded run)", elapsed < 120, f"{elapsed:.1f}s")
        times = srv.stats()["times"]
        check_true("6 requests in the first second", sum(1 for t in times if t - times[0] < 1.0) == 6,
                   str(sum(1 for t in times if t - times[0] < 1.0)))

    print("\n[4] tpm reservations bound the burst; actual usage refills the window")
    with Server(mode="text", workers=20, latency=0.5, prompt_tokens=100,
                completion_tokens=100) as srv:
        rows_in = write_jsonl("d9.jsonl", DATA[:9])
        # reserve per request = ceil(prompt words / 0.75) + max_tokens ~= 1014
        c = cfg("tpm.yaml", srv.port, max_tokens=1000,
                extra=EVAL + "  rate_limits:\n    rpm: 600\n    tpm: 4000\n")
        proc, rows, summary = cli(c, rows_in, "tpm.jsonl")
        check("exit", proc.returncode, 0)
        check("rows", len(rows), 9)
        times = srv.stats()["times"]
        burst = sum(1 for t in times if t - times[0] < 0.4)
        check("tpm admitted 3 before any response", burst, 3)
        check_true("the rest followed once usage was recorded", len(times) == 9, str(len(times)))

    print("\n[4b] rpm alone does not throttle when tpm has room")
    with Server(mode="text", workers=20, latency=0.5) as srv:
        rows_in = write_jsonl("d9b.jsonl", DATA[:9])
        c = cfg("tpm2.yaml", srv.port, max_tokens=1000,
                extra=EVAL + "  rate_limits:\n    rpm: 600\n    tpm: 100000\n")
        proc, rows, summary = cli(c, rows_in, "tpm2.jsonl")
        times = srv.stats()["times"]
        burst = sum(1 for t in times if t - times[0] < 0.4)
        check("no tpm bottleneck", burst, 9)

    print("\n[5] cost accounting")
    with Server(mode="text", workers=10, latency=0.01, prompt_tokens=1000,
                completion_tokens=1000) as srv:
        c = cfg("cost.yaml", srv.port,
                extra=EVAL + "  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03\n    budget: 50.0\n")
        proc, rows, summary = cli(c, data, "cost.jsonl")
        check("exit", proc.returncode, 0)
        check("cost keys", sorted(summary["cost"]),
              ["budget", "budget_exceeded", "budget_remaining", "completion", "prompt", "total"])
        check("prompt cost", summary["cost"]["prompt"], round(20 * 0.01, 6))
        check("completion cost", summary["cost"]["completion"], round(20 * 0.03, 6))
        check("total cost", summary["cost"]["total"], 0.8)
        check("budget", summary["cost"]["budget"], 50.0)
        check("remaining", summary["cost"]["budget_remaining"], 49.2)
        check("not exceeded", summary["cost"]["budget_exceeded"], False)

    print("\n[6] no cost config -> no cost field")
    with Server(mode="text", workers=10, latency=0.01) as srv:
        c = cfg("nocost.yaml", srv.port, extra=EVAL)
        proc, rows, summary = cli(c, data, "nocost.jsonl")
        check("no cost key", "cost" in summary, False)

    print("\n[7] budget exhaustion stops early, exit 0")
    with Server(mode="text", workers=2, latency=0.2, prompt_tokens=1000,
                completion_tokens=1000) as srv:
        c = cfg("budget.yaml", srv.port,
                extra=EVAL + "  rate_limits:\n    max_concurrent: 2\n  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03\n    budget: 0.15\n")
        proc, rows, summary = cli(c, data, "budget.jsonl")
        check("exit", proc.returncode, 0)
        check("budget_exceeded", summary["cost"]["budget_exceeded"], True)
        check_true("partial output", 0 < len(rows) < 20, str(len(rows)))
        check("written rows are a prefix of the input",
              [r["input"]["question"] for r in rows],
              [d["question"] for d in DATA[:len(rows)]])
        check("summary total matches rows", summary["total"], len(rows))
        check_true("stopped near budget", summary["cost"]["total"] >= 0.15,
                   str(summary["cost"]["total"]))
        check_true("did not overspend much", summary["cost"]["total"] < 0.35,
                   str(summary["cost"]["total"]))

    print("\n[8] --budget CLI flag")
    with Server(mode="text", workers=2, latency=0.2, prompt_tokens=1000,
                completion_tokens=1000) as srv:
        c = cfg("budget2.yaml", srv.port,
                extra=EVAL + "  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03\n")
        proc, rows, summary = cli(c, data, "budget2.jsonl", "--budget", "0.1",
                                  "--max-concurrent", "2")
        check("exit", proc.returncode, 0)
        check("budget", summary["cost"]["budget"], 0.1)
        check("exceeded", summary["cost"]["budget_exceeded"], True)

    print("\n[9] output_schema: valid JSON is parsed into output")
    with Server(mode="json", workers=8, latency=0.01) as srv:
        c = cfg("schema.yaml", srv.port, extra=SCHEMA)
        proc, rows, summary = cli(c, data, "schema.jsonl")
        check("exit", proc.returncode, 0)
        check("output parsed", sorted(rows[0]["output"]["solution"]), ["code", "explanation"])
        check("passed", rows[0]["result"]["passed"], True)
        check("schema_valid", rows[0]["result"]["schema_valid"], True)
        check("no schema_error", "schema_error" in rows[0]["result"], False)
        check("summary passed", summary["passed"], 20)

    print("\n[10] output_schema: missing required field")
    with Server(mode="json_missing", workers=8, latency=0.01) as srv:
        c = cfg("schema_bad.yaml", srv.port, extra=SCHEMA)
        proc, rows, summary = cli(c, data, "schema_bad.jsonl")
        check("exit", proc.returncode, 0)
        check("output null", rows[0]["output"], None)
        check("passed false", rows[0]["result"]["passed"], False)
        check("schema_valid false", rows[0]["result"]["schema_valid"], False)
        check("schema_error", rows[0]["result"]["schema_error"], "Missing required field: explanation")
        check("summary failed", summary["failed"], 20)

    print("\n[11] output_schema: invalid JSON counts as schema failure")
    with Server(mode="json_bad", workers=8, latency=0.01) as srv:
        c = cfg("schema_nojson.yaml", srv.port, extra=SCHEMA)
        proc, rows, summary = cli(c, data, "schema_nojson.jsonl")
        check("output null", rows[0]["output"], None)
        check("schema_valid false", rows[0]["result"]["schema_valid"], False)
        check_true("schema_error mentions JSON", "JSON" in rows[0]["result"]["schema_error"],
                   rows[0]["result"]["schema_error"])

    print("\n[12] output_schema: wrong property type")
    with Server(mode="json_typed", workers=8, latency=0.01) as srv:
        c = cfg("schema_type.yaml", srv.port, extra=SCHEMA)
        proc, rows, summary = cli(c, data, "schema_type.jsonl")
        check("schema_valid false", rows[0]["result"]["schema_valid"], False)
        check_true("error mentions type", "type" in rows[0]["result"]["schema_error"].lower(),
                   rows[0]["result"]["schema_error"])

    print("\n[13] rejection sampling gated by output_schema alone")
    with Server(mode="json_flaky", workers=8, latency=0.01, fail_n=2) as srv:
        c = cfg("schema_rej.yaml", srv.port, scheme="rejection", temp=0.7, n=5, extra=SCHEMA)
        proc, rows, summary = cli(c, data, "schema_rej.jsonl")
        check("exit", proc.returncode, 0)
        check("attempts", rows[0]["result"]["attempts"], 3)
        check("passed", rows[0]["result"]["passed"], True)
        check("parsed output", sorted(rows[0]["output"]["solution"]), ["code", "explanation"])

    print("\n[14] --dry-run makes no API calls")
    with Server(mode="text", workers=4, latency=0.01) as srv:
        c = cfg("dry.yaml", srv.port, max_tokens=512,
                extra=EVAL + "  rate_limits:\n    rpm: 100\n  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03\n")
        proc, rows, summary = cli(c, data, "dry.jsonl", "--dry-run")
        check("exit", proc.returncode, 0)
        check("no API calls", srv.stats()["calls"], 0)
        check("keys", sorted(summary),
              ["est_time_minutes", "est_total_cost", "est_total_tokens", "tasks", "total_inputs"])
        task = summary["tasks"]["t"]
        check("task keys", sorted(task),
              ["est_completion_tokens", "est_cost", "est_prompt_tokens", "est_total_tokens", "inputs"])
        check("inputs", task["inputs"], 20)
        check("completion tokens", task["est_completion_tokens"], 20 * 512)
        check("total tokens", task["est_total_tokens"],
              task["est_prompt_tokens"] + task["est_completion_tokens"])
        check("total inputs", summary["total_inputs"], 20)
        check("est time", summary["est_time_minutes"], round(20 / 100, 2))
        check_true("cost > 0", summary["est_total_cost"] > 0, str(summary["est_total_cost"]))
        check_true("no output file written", not os.path.exists(os.path.join(TMP, "dry.jsonl")), "")

    print("\n[15] --resume skips completed rows and appends")
    with Server(mode="text", workers=8, latency=0.01) as srv:
        c = cfg("resume.yaml", srv.port, extra=EVAL)
        proc, rows, summary = cli(c, data, "resume.jsonl")
        check("first run rows", len(rows), 20)
        # keep the first 8 rows, rerun with --resume
        full = os.path.join(TMP, "resume.jsonl")
        with open(full) as fh:
            lines = fh.readlines()
        with open(full, "w") as fh:
            fh.writelines(lines[:8])
        before = srv.stats()["calls"]
        proc, rows, summary = cli(c, data, "resume.jsonl", "--resume")
        check("exit", proc.returncode, 0)
        check("file has all rows", len(rows), 20)
        check("resumed_from", summary["resumed_from"], 8)
        check("summary counts new rows only", summary["total"], 12)
        check("only 12 new calls", srv.stats()["calls"] - before, 12)
        check("order preserved", [r["input"]["question"] for r in rows],
              [d["question"] for d in DATA])

    print("\n[16] --resume with no existing file processes everything")
    with Server(mode="text", workers=8, latency=0.01) as srv:
        c = cfg("resume2.yaml", srv.port, extra=EVAL)
        path = os.path.join(TMP, "resume_new.jsonl")
        if os.path.exists(path):
            os.remove(path)
        proc, rows, summary = cli(c, data, "resume_new.jsonl", "--resume")
        check("rows", len(rows), 20)
        check("resumed_from", summary["resumed_from"], 0)

    print("\n[17] --resume reprocesses an incomplete rejection row")
    with Server(mode="json_flaky", workers=8, latency=0.01, fail_n=1) as srv:
        c = cfg("resume3.yaml", srv.port, scheme="rejection", temp=0.7, n=5, extra=SCHEMA)
        path = os.path.join(TMP, "resume3.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"input": DATA[0], "output": {"solution": {"code": "x", "explanation": "y"}},
                                 "result": {"passed": True, "attempts": 1, "schema_valid": True},
                                 "meta": {}}) + "\n")
            fh.write(json.dumps({"input": DATA[1], "output": None,
                                 "result": {"passed": False, "attempts": 5, "schema_valid": False},
                                 "meta": {}}) + "\n")
        proc, rows, summary = cli(c, write_jsonl("d3.jsonl", DATA[:3]), "resume3.jsonl", "--resume")
        check("exit", proc.returncode, 0)
        check("resumed_from", summary["resumed_from"], 1)
        check("new rows", summary["total"], 2)
        check("file rows", len(rows), 3)
        check("row 1 reprocessed", rows[1]["output"] is not None, True)

    print("\n[18] --progress writes to stderr")
    with Server(mode="text", workers=4, latency=0.05) as srv:
        c = cfg("prog.yaml", srv.port,
                extra=EVAL + "  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03\n")
        proc, rows, summary = cli(c, data, "prog.jsonl", "--progress")
        check("exit", proc.returncode, 0)
        lines = [l for l in proc.stderr.splitlines() if "complete" in l]
        check_true("progress lines", len(lines) >= 2, str(len(lines)))
        pattern = re.compile(
            r"^\[\d+/20\] \d+% complete \| \d+ passed, \d+ failed \| [\d.]+ rpm \| \$[\d.]+ spent \| ETA: \d+s$")
        check_true("format", all(pattern.match(l) for l in lines), lines[:2])
        check_true("ends at 100%", "[20/20] 100% complete" in lines[-1], lines[-1])
        check("stdout still parses as summary", summary["total"], 20)

    print("\n[19] --progress without evaluation or cost omits those fields")
    with Server(mode="text", workers=4, latency=0.05) as srv:
        c = cfg("prog2.yaml", srv.port)
        proc, rows, summary = cli(c, data, "prog2.jsonl", "--progress")
        lines = [l for l in proc.stderr.splitlines() if "complete" in l]
        check_true("no passed/failed", all("passed" not in l for l in lines), lines[:1])
        check_true("no cost", all("spent" not in l for l in lines), lines[:1])
        check_true("has rpm and ETA", all("rpm" in l and "ETA" in l for l in lines), lines[:1])

    print("\n[20] multi-task defaults merging for rate_limits and cost")
    with Server(mode="text", workers=10, latency=0.01, prompt_tokens=1000,
                completion_tokens=1000) as srv:
        multi = write("multi5.yaml", f"""defaults:
  api_url: "http://127.0.0.1:{srv.port}"
  model: "gpt-4"
  generation:
    max_tokens: 128
  rate_limits:
    rpm: 600
    tpm: 900000
    max_concurrent: 4
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 100.0

tasks:
  alpha:
    prompt:
      user: "{{question}}"
    output_field: "solution"
  beta:
    prompt:
      user: "{{question}}"
    output_field: "solution"
    rate_limits:
      max_concurrent: 1
    cost:
      prompt_cost_per_1k: 0.002
""")
        outdir = os.path.join(TMP, "multi_out")
        os.makedirs(outdir, exist_ok=True)
        for f in os.listdir(outdir):
            os.remove(os.path.join(outdir, f))
        a = write_jsonl("alpha.jsonl", DATA[:5])
        b = write_jsonl("beta.jsonl", DATA[:5])
        proc = subprocess.run([PY, CLI, "run", "--config", multi, "--input", f"alpha={a}",
                               "--input", f"beta={b}", "--output", outdir],
                              capture_output=True, text=True, cwd=ROOT)
        summary = json.loads(proc.stdout.strip().splitlines()[-1])
        check("exit", proc.returncode, 0)
        check("tasks", sorted(summary["tasks"]), ["alpha", "beta"])
        # alpha: 5 calls at 0.01 + 0.03; beta: 5 calls at 0.002 + 0.03
        expected = round(5 * (0.01 + 0.03) + 5 * (0.002 + 0.03), 6)
        check("merged per-task cost rates", summary["cost"]["total"], expected)
        check("budget merged", summary["cost"]["budget"], 100.0)
        check_true("max_concurrent honoured", srv.stats()["max_inflight"] <= 5,
                   str(srv.stats()["max_inflight"]))

    print("\n[21] budget stop leaves a file --resume can extend")
    with Server(mode="text", workers=2, latency=0.1, prompt_tokens=1000,
                completion_tokens=1000) as srv:
        c = cfg("budget3.yaml", srv.port,
                extra=EVAL + "  rate_limits:\n    max_concurrent: 2\n  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03\n    budget: 0.15\n")
        path = os.path.join(TMP, "budget3.jsonl")
        if os.path.exists(path):
            os.remove(path)
        proc, rows, summary = cli(c, data, "budget3.jsonl")
        first = len(rows)
        check_true("stopped early", first < 20, str(first))
        c2 = cfg("budget3b.yaml", srv.port, extra=EVAL)  # no budget this time
        proc, rows, summary = cli(c2, data, "budget3.jsonl", "--resume")
        check("resume finishes the file", len(rows), 20)
        check("resumed_from matches the partial file", summary["resumed_from"], first)
        check("order preserved", [r["input"]["question"] for r in rows],
              [d["question"] for d in DATA])

    print("\n[22] JSON Schema keyword coverage")
    sys.path.insert(0, ROOT)
    import rejector

    def valid(schema, value):
        return rejector.validate_schema(value, schema) is None

    check("enum ok", valid({"enum": ["a", "b"]}, "a"), True)
    check("enum rejects", valid({"enum": ["a", "b"]}, "c"), False)
    check("minimum", valid({"type": "number", "minimum": 5}, 4), False)
    check("maximum", valid({"type": "number", "maximum": 5}, 6), False)
    check("minimum ok", valid({"type": "number", "minimum": 5}, 5), True)
    check("minLength", valid({"type": "string", "minLength": 3}, "ab"), False)
    check("maxLength", valid({"type": "string", "maxLength": 3}, "abcd"), False)
    check("pattern", valid({"type": "string", "pattern": "^a+$"}, "aaa"), True)
    check("pattern rejects", valid({"type": "string", "pattern": "^a+$"}, "bbb"), False)
    check("items", valid({"type": "array", "items": {"type": "integer"}}, [1, 2]), True)
    check("items rejects", valid({"type": "array", "items": {"type": "integer"}}, [1, "x"]), False)
    check("integer accepts int", valid({"type": "integer"}, 3), True)
    check("integer rejects float", valid({"type": "integer"}, 3.5), False)
    check("boolean is not integer", valid({"type": "integer"}, True), False)
    check("null type", valid({"type": "null"}, None), True)
    check("nested required", valid(
        {"type": "object", "properties": {"a": {"type": "object", "required": ["b"]}}},
        {"a": {}}), False)
    check("nested message", rejector.validate_schema(
        {"a": {}}, {"type": "object", "properties": {"a": {"type": "object", "required": ["b"]}}}),
        "Missing required field: b")
    check("type union", valid({"type": ["string", "null"]}, None), True)
    check("fenced json parses", rejector.check_output_schema(
        {"type": "object", "required": ["a"]}, '```json\n{"a": 1}\n```').valid, True)

    print("\n[23] config validation for the new sections")
    bad = write("bad_rl.yaml", BASE.format(port=8000, scheme="greedy", temp=0.0, n=1,
                                           max_tokens=32, extra="  rate_limits:\n    tpm: 0\n"))
    proc, rows, summary = cli(bad, data, "badrl.jsonl")
    check("tpm 0 exits 1", proc.returncode, 1)
    bad2 = write("bad_schema.yaml", BASE.format(port=8000, scheme="greedy", temp=0.0, n=1,
                                                max_tokens=32,
                                                extra='  output_schema:\n    type: "mapping"\n'))
    proc, rows, summary = cli(bad2, data, "badschema.jsonl")
    check("bad schema type exits 1", proc.returncode, 1)

    ok = sum(1 for r in results if r[0])
    bad_count = len(results) - ok
    print(f"\n==== {ok} passed, {bad_count} failed ====")
    return 1 if bad_count else 0


if __name__ == "__main__":
    sys.exit(main())
