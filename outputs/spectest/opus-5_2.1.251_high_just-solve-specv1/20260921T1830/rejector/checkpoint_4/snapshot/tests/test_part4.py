#!/usr/bin/env python3
"""End-to-end test suite for the Part 4 features of rejector.py.

Usage: python tests/test_part4.py  (starts its own mock server)

Covers the `agentic` generation scheme (tool handlers, the tool-calling loop,
its output shape, the list format and concurrency) and completions mode with
the four built-in chat templates.
"""

from __future__ import annotations

import asyncio
import json
import os
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
import rejector  # noqa: E402  (in-process checks for templates and handlers)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = int(os.environ["MOCK_PORT"]) if os.environ.get("MOCK_PORT") else free_port()
API = f"http://127.0.0.1:{PORT}"
CAPACITY = 16
LATENCY = 0.02


def start_server(port: int, capacity: int, latency: float) -> subprocess.Popen:
    proc = subprocess.Popen(
        [PY, MOCK, "--port", str(port), "--capacity", str(capacity),
         "--latency", str(latency)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/stats", timeout=1):
                return proc
        except Exception:
            if proc.poll() is not None:
                raise SystemExit("mock server failed to start")
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit("mock server did not become ready")


def start_mock() -> subprocess.Popen | None:
    if os.environ.get("MOCK_PORT"):
        return None
    return start_server(PORT, CAPACITY, LATENCY)


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def jsonl(path: str, rows: list[dict]) -> str:
    return write(path, "".join(json.dumps(r) + "\n" for r in rows))


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


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def stats(base: str = API) -> dict:
    with urllib.request.urlopen(f"{base}/stats", timeout=5) as resp:
        return json.loads(resp.read())


def requests_seen(base: str = API) -> list[dict]:
    with urllib.request.urlopen(f"{base}/requests", timeout=5) as resp:
        return json.loads(resp.read())["requests"]


# --------------------------------------------------------------------------
# Config fragments
# --------------------------------------------------------------------------

TOOLS = """
    tools:
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
      - name: "calculate"
        description: "Evaluate a mathematical expression"
        parameters:
          type: "object"
          properties:
            expression:
              type: "string"
              description: "The math expression to evaluate"
          required: ["expression"]
        handler:
          type: "echo"
      - name: "python"
        description: "Run a python snippet"
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

EVALUATION = """
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
"""


def agentic_config(
    path: str,
    *,
    extra_task: str = "",
    evaluation: str = EVALUATION,
    max_iterations: int = 10,
    defaults: str = "",
    api: str | None = None,
) -> str:
    return write(path, f"""
defaults:
  api_url: "{api or API}"
  model: "gpt-4"
  rpm: 60
  generation:
    max_tokens: 512
{defaults}
tasks:
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools."
      user: "{{question}}"
    generation:
      scheme: "agentic"
      max_iterations: {max_iterations}
      temperature: 0.0
{evaluation}    output_field: "answer"
{extra_task}{TOOLS}
""")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="rejector-part4-")

    def path(*parts: str) -> str:
        return os.path.join(tmp, *parts)

    # ------------------------------------------------------- agentic basics
    print("\n[agentic loop]")
    cfg = agentic_config(path("agentic.yaml"))
    rows = [
        {"question": "What is the total revenue for Q1 and Q2?\n"
                     "TOOLS:lookup:key=revenue_q1;lookup:key=revenue_q2"
                     "|calculate:expression=1250000+1480000\n"
                     "FINAL:The total revenue for Q1 and Q2 is 2730000.",
         "answer": "2730000"},
        {"question": "How many employees are there?\nTOOLS:lookup:key=employees\n"
                     "FINAL:The company has 142 employees.",
         "answer": "142"},
        {"question": "What about the missing key?\nTOOLS:lookup:key=nope\n"
                     "FINAL:I found 0 matches.",
         "answer": "0"},
    ]
    data = jsonl(path("data.jsonl"), rows)
    code, summary, err = run(["--config", cfg, "--input", f"data_lookup={data}",
                              "--output", path("out")])
    out = read_jsonl(path("out", "data_lookup.jsonl"))
    check(code == 0 and len(out) == 3, "agentic run exit 0 with one row each", err)

    first = out[0]
    check(first["output"] == {"answer": "The total revenue for Q1 and Q2 is 2730000."},
          "final text becomes the output field", str(first["output"]))
    check(first["result"]["passed"] is True
          and first["result"]["extracted_answer"] == "2730000",
          "final text is evaluated normally", str(first["result"]))
    check(first["result"]["attempts"] == 1, "single-solution agentic attempts is 1",
          str(first["result"]))
    check(first["result"]["iterations"] == 3,
          "iterations counts the API requests in the loop", str(first["result"]))
    calls = first["result"]["tool_calls"]
    check([(c["iteration"], c["tool"], c["args"]) for c in calls] == [
              (1, "lookup", {"key": "revenue_q1"}),
              (1, "lookup", {"key": "revenue_q2"}),
              (2, "calculate", {"expression": "1250000+1480000"}),
          ],
          "tool calls recorded in execution order with iteration and args",
          json.dumps(calls))
    check([c["result"] for c in calls] == [
              "1250000", "1480000", '{"expression": "1250000+1480000"}'],
          "static_map and echo handler results recorded", json.dumps(calls))

    meta = first["meta"]
    detail = meta["iterations_detail"]
    check(len(detail) == 3 and [d["finish_reason"] for d in detail]
          == ["tool_calls", "tool_calls", "stop"],
          "iterations_detail has one entry per request", json.dumps(detail))
    check(meta["total_prompt_tokens"] == sum(d["prompt_tokens"] for d in detail)
          and meta["total_completion_tokens"]
          == sum(d["completion_tokens"] for d in detail)
          and meta["total_tokens"] == sum(d["total_tokens"] for d in detail),
          "meta totals aggregate every iteration", json.dumps(meta))
    check(meta["finish_reason"] == "stop", "finish_reason is stop for final text",
          json.dumps(meta))
    check(meta["latency_ms"] >= max(d["latency_ms"] for d in detail),
          "latency_ms covers the whole loop", json.dumps(meta))
    check(all("prompt_tokens" in d and "latency_ms" in d for d in detail),
          "each iteration records usage and latency", json.dumps(detail))

    second = out[1]
    check(second["result"]["iterations"] == 2
          and len(second["result"]["tool_calls"]) == 1
          and second["result"]["tool_calls"][0]["result"] == "142",
          "one lookup then a final answer is two iterations", str(second["result"]))
    check(out[2]["result"]["tool_calls"][0]["result"] == "KEY_NOT_FOUND",
          "static_map falls back to the configured default", str(out[2]["result"]))
    check(summary["total_api_calls"] == 7,
          "every request inside the loop counts toward the totals", str(summary))
    check(summary["passed"] == 3 and "total_solutions" not in summary,
          "single-solution agentic keeps the earlier summary shape", str(summary))

    # tool definitions travel in the request body in chat mode
    bodies = [r["body"] for r in requests_seen()
              if r["path"] == "/v1/chat/completions" and "tools" in r["body"]]
    check(bool(bodies), "chat requests carry the tool definitions")
    if bodies:
        names = [t["function"]["name"] for t in bodies[-1]["tools"]]
        check(names == ["lookup", "calculate", "python"],
              "every configured tool is advertised", str(names))
        first_tool = bodies[-1]["tools"][0]
        check(first_tool["type"] == "function"
              and first_tool["function"]["description"]
              == "Look up a value in the database by key"
              and first_tool["function"]["parameters"]["required"] == ["key"],
              "tool definitions keep name, description and parameters",
              json.dumps(first_tool))

    # ------------------------------------------------------- script handler
    print("\n[script handler]")
    script_rows = [
        {"question": "run it\nTOOLS:python:code=print(6*7)\nFINAL:The answer is 42.",
         "answer": "42"},
        {"question": "break it\nTOOLS:python:code=raise ValueError('nope')\n"
                     "FINAL:It failed 0 times.", "answer": "0"},
        {"question": "quiet failure\nTOOLS:python:code=raise SystemExit(3)\n"
                     "FINAL:It exited 0 times.", "answer": "0"},
        {"question": "missing\nTOOLS:python:expr=1\nFINAL:No code 0.", "answer": "0"},
        {"question": "unknown\nTOOLS:nosuch:key=a\nFINAL:No tool 0.", "answer": "0"},
    ]
    script_data = jsonl(path("script.jsonl"), script_rows)
    code, _, err = run(["--config", cfg, "--input", f"data_lookup={script_data}",
                        "--output", path("script_out")])
    srows = read_jsonl(path("script_out", "data_lookup.jsonl"))
    check(code == 0 and srows[0]["result"]["tool_calls"][0]["result"] == "42",
          "script handler returns the command's stdout", str(srows[0]["result"]))
    failed_result = srows[1]["result"]["tool_calls"][0]["result"]
    check(failed_result.startswith("ERROR:") and "ValueError: nope" in failed_result,
          "a failing script returns ERROR: with stderr", failed_result)
    quiet = srows[2]["result"]["tool_calls"][0]["result"]
    check(quiet.startswith("ERROR:") and "3" in quiet,
          "a non-zero exit without stderr still returns ERROR:", quiet)
    check(srows[3]["result"]["tool_calls"][0]["result"].startswith("ERROR:"),
          "a missing arg_field is reported as an error",
          str(srows[3]["result"]["tool_calls"]))
    check("unknown tool" in srows[4]["result"]["tool_calls"][0]["result"],
          "an unknown tool name is reported back to the model",
          str(srows[4]["result"]["tool_calls"]))
    check(all(row["output"] is not None for row in srows),
          "handler errors do not abort the loop")

    # in-process handler checks
    def handler_result(tool: rejector.ToolConfig, args: dict) -> str:
        return asyncio.run(rejector.run_tool(tool, args))

    echo_tool = rejector.ToolConfig(
        "calc", "", {"type": "object", "properties": {"expression": {}},
                     "required": ["expression"]},
        rejector.ToolHandler(type="echo"))
    check(handler_result(echo_tool, {"expression": "1+2"}) == '{"expression": "1+2"}',
          "echo handler returns the parsed arguments as JSON")
    map_tool = rejector.ToolConfig(
        "lookup", "", {"type": "object", "properties": {"key": {}},
                       "required": ["key"]},
        rejector.ToolHandler(type="static_map", mapping={"a": "1"}))
    check(handler_result(map_tool, {"key": "a"}) == "1"
          and handler_result(map_tool, {"key": "b"}) == "NOT_FOUND"
          and handler_result(map_tool, {}) == "NOT_FOUND",
          "static_map default defaults to NOT_FOUND")
    slow = rejector.ToolConfig(
        "py", "", {"type": "object", "properties": {"code": {}}, "required": ["code"]},
        rejector.ToolHandler(type="script", command="python3 -c", arg_field="code"))
    saved = rejector.TOOL_TIMEOUT_SECONDS
    rejector.TOOL_TIMEOUT_SECONDS = 0.5
    timed_out = handler_result(slow, {"code": "import time; time.sleep(30)"})
    rejector.TOOL_TIMEOUT_SECONDS = saved
    check(timed_out.startswith("ERROR:") and "timed out" in timed_out,
          "a script timeout returns an ERROR: message", timed_out)

    # ------------------------------------------------------- max_iterations
    print("\n[max_iterations]")
    loop_cfg = agentic_config(path("loop.yaml"), max_iterations=3)
    loop_rows = [{"question": "never stops\nTOOLS:lookup:key=employees\nLOOP_TOOLS",
                  "answer": "142"}]
    loop_data = jsonl(path("loop.jsonl"), loop_rows)
    code, summary, err = run(["--config", loop_cfg, "--input",
                              f"data_lookup={loop_data}", "--output", path("loop_out")])
    lrow = read_jsonl(path("loop_out", "data_lookup.jsonl"))[0]
    check(code == 0 and lrow["output"] is None,
          "hitting max_iterations writes output null", str(lrow["output"]))
    check(lrow["meta"]["finish_reason"] == "max_iterations",
          "finish_reason is max_iterations", str(lrow["meta"]["finish_reason"]))
    check(lrow["result"]["iterations"] == 3 and len(lrow["meta"]["iterations_detail"]) == 3,
          "the loop stops at the iteration limit", str(lrow["result"]))
    check(lrow["result"]["passed"] is False
          and lrow["result"]["extracted_answer"] is None,
          "evaluation fails when there is no output", str(lrow["result"]))
    check(len(lrow["result"]["tool_calls"]) == 3,
          "tool calls made before the limit are still recorded",
          str(lrow["result"]["tool_calls"]))
    check(summary["failed"] == 1, "a max_iterations row counts as failed", str(summary))

    # no evaluation section
    noeval_cfg = agentic_config(path("noeval.yaml"), evaluation="", max_iterations=2)
    code, _, err = run(["--config", noeval_cfg, "--input", f"data_lookup={loop_data}",
                        "--output", path("noeval_loop")])
    nrow = read_jsonl(path("noeval_loop", "data_lookup.jsonl"))[0]
    check(code == 0 and nrow["result"]["passed"] is False,
          "without evaluation, max_iterations still fails the row", str(nrow["result"]))
    code, _, err = run(["--config", noeval_cfg, "--input", f"data_lookup={data}",
                        "--output", path("noeval_out")])
    nrows = read_jsonl(path("noeval_out", "data_lookup.jsonl"))
    check(code == 0 and nrows[1]["result"]["passed"] is None
          and nrows[1]["output"] is not None,
          "without evaluation a finished loop has passed null", str(nrows[1]["result"]))

    # ------------------------------------------------------- list format
    print("\n[list format]")
    multi_cfg = agentic_config(path("multi.yaml"), extra_task="    num_solutions: 2\n")
    multi_data = jsonl(path("multi.jsonl"), [rows[1]])
    code, summary, err = run(["--config", multi_cfg, "--input",
                              f"data_lookup={multi_data}", "--output", path("multi_out")])
    mrow = read_jsonl(path("multi_out", "data_lookup.jsonl"))[0]
    check(code == 0 and isinstance(mrow["output"], list) and len(mrow["output"]) == 2,
          "num_solutions > 1 keeps the checkpoint 3 list format", str(mrow["output"]))
    check(mrow["result"] == {"passed": 2, "failed": 0, "attempts": 2},
          "result counts loops, not API requests", str(mrow["result"]))
    check(isinstance(mrow["meta"], list) and len(mrow["meta"]) == 2,
          "one meta entry per loop", str(mrow["meta"]))
    entry = mrow["meta"][0]
    check(entry["icl_setup"] is None and entry["evaluation_passed"] is True,
          "meta entries keep icl_setup and evaluation_passed", json.dumps(entry))
    check(entry["total_tokens"] == sum(d["total_tokens"]
                                       for d in entry["iterations_detail"])
          and entry["finish_reason"] == "stop"
          and len(entry["iterations_detail"]) == 2,
          "meta entries carry that loop's aggregated agentic metadata",
          json.dumps(entry))
    check(all(item["icl_setup"] is None and "answer" in item
              for item in mrow["output"]),
          "each output item is one completed loop", str(mrow["output"]))
    check(summary["tasks"]["data_lookup"]["total_solutions"] == 2,
          "solution counts appear in the summary", str(summary))

    # list format, no evaluation, one loop that never answers
    noeval_multi = agentic_config(path("nm.yaml"), evaluation="", max_iterations=2,
                                 extra_task="    num_solutions: 2\n")
    code, _, err = run(["--config", noeval_multi, "--input",
                        f"data_lookup={multi_data}", "--output", path("nm_out")])
    nmrow = read_jsonl(path("nm_out", "data_lookup.jsonl"))[0]
    check(code == 0 and nmrow["result"] == {"passed": 2, "failed": 0, "attempts": 2}
          and all(e["evaluation_passed"] is None for e in nmrow["meta"]),
          "without evaluation the list format counts emitted outputs",
          str(nmrow["result"]))
    code, _, err = run(["--config", noeval_multi, "--input",
                        f"data_lookup={loop_data}", "--output", path("nm_loop")])
    nlrow = read_jsonl(path("nm_loop", "data_lookup.jsonl"))[0]
    check(code == 0 and nlrow["output"] == []
          and nlrow["result"] == {"passed": 0, "failed": 2, "attempts": 2}
          and all(e["finish_reason"] == "max_iterations" for e in nlrow["meta"]),
          "loops that produce no output count as failed", str(nlrow["result"]))

    # ICL keeps the list format for a single solution
    icl_cfg = agentic_config(path("icl.yaml"), extra_task="""    icl:
      setups:
        - name: "demo"
          examples:
            - input: {question: "What is 2+2?"}
              output: "#### 4"
""")
    code, _, err = run(["--config", icl_cfg, "--input", f"data_lookup={multi_data}",
                        "--output", path("icl_out")])
    irow = read_jsonl(path("icl_out", "data_lookup.jsonl"))[0]
    check(code == 0 and isinstance(irow["output"], list)
          and irow["output"][0]["icl_setup"] == "demo"
          and irow["meta"][0]["icl_setup"] == "demo",
          "agentic works with ICL and records the setup", str(irow))
    icl_bodies = [r["body"] for r in requests_seen()
                  if r["path"] == "/v1/chat/completions"
                  and any(m.get("role") == "assistant" and m.get("content") == "#### 4"
                          for m in r["body"].get("messages", []))]
    check(bool(icl_bodies), "ICL example turns are sent in the agentic conversation")

    # ------------------------------------------------- other evaluations
    print("\n[evaluation types]")
    judge_cfg = agentic_config(path("judge.yaml"), evaluation="""    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "JUDGE: respond with a single integer."
        user: "Rate this answer:\n{__response__}\nSCORE=9\nScore:"
      threshold: 7
""")
    code, summary, err = run(["--config", judge_cfg, "--input",
                              f"data_lookup={multi_data}", "--output", path("judge_out")])
    jrow = read_jsonl(path("judge_out", "data_lookup.jsonl"))[0]
    check(code == 0 and jrow["result"]["passed"] is True
          and jrow["result"]["judge_score"] == 9,
          "an agentic answer can be scored by a judge", str(jrow["result"]))
    check(jrow["meta"]["judge_meta"]["finish_reason"] == "stop"
          and jrow["result"]["iterations"] == 2,
          "the judge call is recorded outside the loop metadata", str(jrow["meta"]))
    check(summary["tasks"]["data_lookup"]["total_api_calls"] == 3,
          "the judge call counts toward the task totals", str(summary))

    contains_cfg = agentic_config(path("contains.yaml"), evaluation="""    evaluation:
      type: "contains"
      answer_field: "answer"
""")
    code, _, err = run(["--config", contains_cfg, "--input",
                        f"data_lookup={multi_data}", "--output", path("contains_out")])
    crow2 = read_jsonl(path("contains_out", "data_lookup.jsonl"))[0]
    check(code == 0 and crow2["result"]["passed"] is True,
          "contains evaluation runs against the final text", str(crow2["result"]))

    # ------------------------------------------------------- concurrency
    print("\n[concurrency]")
    conc_port = free_port()
    conc_latency = 0.3
    conc_server = start_server(conc_port, 8, conc_latency)
    try:
        conc_api = f"http://127.0.0.1:{conc_port}"
        conc_cfg = agentic_config(path("conc.yaml"), api=conc_api)
        conc_rows = [
            {"question": f"row {index}\nTOOLS:lookup:key=employees\n"
                         f"FINAL:The company has 142 employees.",
             "answer": "142"}
            for index in range(3)
        ]
        conc_data = jsonl(path("conc.jsonl"), conc_rows)
        started = time.time()
        code, summary, err = run(["--config", conc_cfg, "--input",
                                  f"data_lookup={conc_data}",
                                  "--output", path("conc_out")])
        elapsed = time.time() - started
        conc_stats = stats(conc_api)
        check(code == 0 and conc_stats["total"] == 6,
              "three two-request loops make six requests", str(conc_stats["total"]))
        check(conc_stats["max_inflight"] >= 2,
              "requests from different rows overlap in flight",
              str(conc_stats["max_inflight"]))
        # six requests, serialized, would take 6 * latency; three overlapping
        # two-request loops take about 2 * latency plus process startup.
        check(elapsed < 6 * conc_latency,
              "short agentic batches are not fully serialized", f"{elapsed:.2f}s")
        arrivals = conc_stats["arrivals"][:3]
        check(len(set(arrivals)) == 3,
              "the first request of every row is sent before any second one",
              str(arrivals))
    finally:
        conc_server.terminate()
        try:
            conc_server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            conc_server.kill()

    # ------------------------------------------------------- templates
    print("\n[chat templates]")
    conversation = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
        {"role": "user", "content": "Q2"},
    ]
    single = conversation[:2]
    expected_single = {
        "chatml": "<|im_start|>system\nSYS<|im_end|>\n"
                  "<|im_start|>user\nQ1<|im_end|>\n<|im_start|>assistant\n",
        "llama3": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
                  "SYS<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
                  "Q1<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "mistral": "[INST] SYS\n\nQ1 [/INST]",
        "zephyr": "<|system|>\nSYS</s>\n<|user|>\nQ1</s>\n<|assistant|>\n",
    }
    for name, expected in expected_single.items():
        rendered = rejector.render_chat_prompt(single, name)
        check(rendered == expected, f"{name} renders a system+user prompt",
              repr(rendered))

    expected_multi = {
        "chatml": "<|im_start|>system\nSYS<|im_end|>\n<|im_start|>user\nQ1<|im_end|>\n"
                  "<|im_start|>assistant\nA1<|im_end|>\n<|im_start|>user\nQ2<|im_end|>\n"
                  "<|im_start|>assistant\n",
        "llama3": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
                  "SYS<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
                  "Q1<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
                  "A1<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
                  "Q2<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "mistral": "[INST] SYS\n\nQ1 [/INST] A1</s>[INST] Q2 [/INST]",
        "zephyr": "<|system|>\nSYS</s>\n<|user|>\nQ1</s>\n<|assistant|>\nA1</s>\n"
                  "<|user|>\nQ2</s>\n<|assistant|>\n",
    }
    for name, expected in expected_multi.items():
        rendered = rejector.render_chat_prompt(conversation, name)
        check(rendered == expected, f"{name} repeats role markers for every turn",
              repr(rendered))

    tool_turn = [{"role": "user", "content": "Q"},
                 {"role": "tool", "name": "lookup", "content": "142"}]
    for name in rejector.CHAT_TEMPLATES:
        rendered = rejector.render_chat_prompt(tool_turn, name)
        check("142" in rendered, f"{name} renders tool results into the prompt",
              repr(rendered))

    # ------------------------------------------------------- completions mode
    print("\n[completions mode]")
    comp_cfg = write(path("comp.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "meta-llama/llama-3-70b"
  api_type: "completions"
  chat_template: "llama3"
tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem."
      user: "{{question}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
""")
    comp_data = jsonl(path("comp.jsonl"), [{"question": "What is 15 + 27?",
                                            "answer": "42"}])
    code, summary, err = run(["--config", comp_cfg, "--input", f"gsm8k={comp_data}",
                              "--output", path("comp_out")])
    crow = read_jsonl(path("comp_out", "gsm8k.jsonl"))[0]
    check(code == 0 and crow["result"]["passed"] is True
          and crow["output"]["solution"].endswith("#### 42"),
          "completions responses are read from choices[].text", str(crow))
    comp_requests = [r for r in requests_seen() if r["path"] == "/v1/completions"]
    check(bool(comp_requests), "completions requests go to /v1/completions")
    body = comp_requests[-1]["body"]
    check(set(body) == {"model", "prompt", "temperature", "max_tokens"},
          "completions requests send prompt, temperature, max_tokens and model",
          json.dumps(sorted(body)))
    check(body["model"] == "meta-llama/llama-3-70b" and body["max_tokens"] == 512
          and body["temperature"] == 0.0,
          "completions request values come from the config", json.dumps(body))
    check(body["prompt"].startswith("<|begin_of_text|><|start_header_id|>system")
          and "What is 15 + 27?" in body["prompt"],
          "the configured template renders the prompt", repr(body["prompt"]))

    # CLI overrides, verified through the echoed prompt
    echo_data = jsonl(path("echo.jsonl"), [{"question": "ECHO_PROMPT", "answer": "1"}])
    echo_cfg = write(path("echo.yaml"), f"""
task:
  name: "echo"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    system: "SYS"
    user: "{{question}}"
  generation:
    scheme: "greedy"
  output_field: "text"
""")
    for template, expected in expected_single.items():
        code, _, err = run(["--config", echo_cfg, "--input", echo_data,
                            "--output", path(f"echo_{template}.jsonl"),
                            "--api-type", "completions",
                            "--chat-template", template])
        erow = read_jsonl(path(f"echo_{template}.jsonl"))
        rendered = erow[0]["output"]["text"] if erow else ""
        check(code == 0 and rendered == expected.replace("Q1", "ECHO_PROMPT"),
              f"--api-type completions --chat-template {template}", repr(rendered))

    code, _, err = run(["--config", comp_cfg, "--input", f"gsm8k={comp_data}",
                        "--output", path("chat_override"), "--api-type", "chat"])
    check(code == 0 and any(
              r["path"] == "/v1/chat/completions"
              and r["body"].get("model") == "meta-llama/llama-3-70b"
              for r in requests_seen()),
          "--api-type chat overrides a completions config", err)

    # ------------------------------------------- agentic in completions mode
    print("\n[agentic + completions]")
    ac_cfg = agentic_config(
        path("agentic_comp.yaml"),
        defaults='  api_type: "completions"\n  chat_template: "chatml"\n')
    code, summary, err = run(["--config", ac_cfg, "--input", f"data_lookup={data}",
                              "--output", path("ac_out")])
    acrows = read_jsonl(path("ac_out", "data_lookup.jsonl"))
    check(code == 0 and len(acrows) == 3
          and acrows[0]["result"]["iterations"] == 3
          and acrows[0]["result"]["passed"] is True,
          "the agentic loop works over /v1/completions", str(acrows[0]["result"]))
    check([(c["tool"], c["result"]) for c in acrows[0]["result"]["tool_calls"]] == [
              ("lookup", "1250000"), ("lookup", "1480000"),
              ("calculate", '{"expression": "1250000+1480000"}')],
          "text tool calls are parsed and executed",
          str(acrows[0]["result"]["tool_calls"]))
    ac_bodies = [r["body"]["prompt"] for r in requests_seen()
                 if r["path"] == "/v1/completions" and "<tool_call>" in r["body"]["prompt"]]
    check(bool(ac_bodies), "tool definitions are rendered into the prompt")
    if ac_bodies:
        longest = max(ac_bodies, key=len)
        check('"name": "lookup"' in longest and '"required": ["key"]' in longest,
              "the rendered tool documentation lists every tool")
        check("<|im_start|>tool\n" in longest and "1250000" in longest,
              "tool results are fed back with the template's tool role",
              repr(longest[-400:]))
    check(all("tools" not in r["body"] for r in requests_seen()
              if r["path"] == "/v1/completions"),
          "completions requests never send a native tools field")

    # ------------------------------------------------------- mixed tasks
    print("\n[mixed tasks]")
    mixed_cfg = write(path("mixed.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  gsm8k:
    api_type: "completions"
    chat_template: "zephyr"
    prompt:
      user: "{{question}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools."
      user: "{{question}}"
    generation:
      scheme: "agentic"
      max_iterations: 5
{EVALUATION}    output_field: "answer"
{TOOLS}
""")
    code, summary, err = run(["--config", mixed_cfg, "--input", f"gsm8k={comp_data}",
                              "--input", f"data_lookup={data}",
                              "--output", path("mixed_out")])
    grows = read_jsonl(path("mixed_out", "gsm8k.jsonl"))
    drows = read_jsonl(path("mixed_out", "data_lookup.jsonl"))
    check(code == 0 and len(grows) == 1 and len(drows) == 3
          and grows[0]["result"]["passed"] is True
          and all(row["result"]["passed"] for row in drows),
          "a completions task and an agentic task run together", err)
    check(summary["tasks"]["gsm8k"]["total_api_calls"] == 1
          and summary["tasks"]["data_lookup"]["total_api_calls"] == 7
          and summary["total_api_calls"] == 8,
          "per-task request accounting covers both modes", str(summary))

    # ------------------------------------------------------- validation
    print("\n[validation]")
    bad_cases = [
        ("api_type", '  api_type: "grpc"\n', "api_type"),
        ("chat_template", '  chat_template: "alpaca"\n', "chat_template"),
    ]
    for name, defaults, needle in bad_cases:
        bad = agentic_config(path(f"bad_{name}.yaml"), defaults=defaults)
        code, _, err = run(["--config", bad, "--input", f"data_lookup={data}",
                            "--output", path(f"bad_{name}")])
        check(code == 1 and needle in err, f"invalid {name} exits 1", err)

    tool_cases = [
        ("not_a_list", '    tools: "lookup"\n', "must be a list"),
        ("no_name", "    tools:\n      - handler: {type: \"echo\"}\n", "name"),
        ("dupe", '''    tools:
      - name: "a"
        handler: {type: "echo"}
      - name: "a"
        handler: {type: "echo"}
''', "duplicate tool name"),
        ("bad_handler", '''    tools:
      - name: "a"
        handler: {type: "magic"}
''', "handler.type"),
        ("no_handler", '    tools:\n      - name: "a"\n', "handler is required"),
        ("no_command", '''    tools:
      - name: "a"
        handler: {type: "script", arg_field: "code"}
''', "command"),
        ("no_arg_field", '''    tools:
      - name: "a"
        handler: {type: "script", command: "python3 -c"}
''', "arg_field"),
        ("bad_params", '''    tools:
      - name: "a"
        parameters: "object"
        handler: {type: "echo"}
''', "parameters"),
        ("bad_mapping", '''    tools:
      - name: "a"
        handler: {type: "static_map", mapping: "x"}
''', "mapping"),
    ]
    for name, block in [(case[0], case[1]) for case in tool_cases]:
        needle = dict((c[0], c[2]) for c in tool_cases)[name]
        cfg_text = write(path(f"tools_{name}.yaml"), f"""
tasks:
  data_lookup:
    api_url: "{API}"
    model: "gpt-4"
    prompt:
      user: "{{question}}"
    generation:
      scheme: "agentic"
    output_field: "answer"
{block}""")
        code, _, err = run(["--config", cfg_text, "--input", f"data_lookup={data}",
                            "--output", path(f"tools_{name}_out")])
        check(code == 1 and needle in err, f"invalid tools config: {name}", err)

    for value in ("0", "abc"):
        bad_iter = agentic_config(path(f"iter_{value}.yaml"))
        bad_iter = write(path(f"iter_{value}.yaml"),
                         open(bad_iter, encoding="utf-8").read().replace(
                             "max_iterations: 10", f"max_iterations: {value}"))
        code, _, err = run(["--config", bad_iter, "--input", f"data_lookup={data}",
                            "--output", path(f"iter_{value}_out")])
        check(code == 1 and "max_iterations" in err,
              f"max_iterations {value!r} exits 1", err)

    code, _, err = run(["--config", cfg, "--input", f"data_lookup={data}",
                        "--output", path("cli_bad"), "--api-type", "soap"])
    check(code == 1, "--api-type soap exits 1", err)
    code, _, err = run(["--config", cfg, "--input", f"data_lookup={data}",
                        "--output", path("cli_bad"), "--chat-template", "vicuna"])
    check(code == 1, "--chat-template vicuna exits 1", err)

    # ------------------------------------------------------- failures
    print("\n[failures]")
    fail_data = jsonl(path("fail.jsonl"),
                      [{"question": "ALWAYS_500 lookup\nTOOLS:lookup:key=employees",
                        "answer": "142"}])
    code, summary, err = run(["--config", cfg, "--input", f"data_lookup={fail_data}",
                              "--output", path("fail_out")])
    frow = read_jsonl(path("fail_out", "data_lookup.jsonl"))[0]
    check(code == 0 and frow["output"] is None and frow["result"]["passed"] is False,
          "a hard API failure fails the agentic row", str(frow["result"]))
    check(frow["result"]["iterations"] == 1
          and len(frow["meta"]["iterations_detail"]) == 1,
          "a failed request is one iteration", str(frow["result"]))

    # ------------------------------------------------------- other schemes
    print("\n[unchanged behaviour]")
    plain_cfg = write(path("plain.yaml"), f"""
tasks:
  gsm8k:
    api_url: "{API}"
    model: "gpt-4"
    prompt:
      user: "{{question}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
""")
    code, summary, err = run(["--config", plain_cfg, "--input", f"gsm8k={comp_data}",
                              "--output", path("plain_out")])
    prow = read_jsonl(path("plain_out", "gsm8k.jsonl"))[0]
    check(code == 0 and prow["result"] == {"passed": True, "extracted_answer": "42",
                                           "attempts": 1}
          and set(prow["meta"]) == {"model", "prompt_tokens", "completion_tokens",
                                    "total_tokens", "latency_ms", "finish_reason"},
          "chat mode keeps the earlier row shape", str(prow))

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
