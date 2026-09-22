#!/usr/bin/env python3
"""End-to-end test suite for the Part 2 features of rejector.py.

Usage: python tests/test_part2.py  (starts its own mock server)

Covers multi-task configs, task selection, input/output modes, the new
extract methods, and the script / llm_judge evaluation types.
"""

from __future__ import annotations

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


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = int(os.environ["MOCK_PORT"]) if os.environ.get("MOCK_PORT") else free_port()
API = f"http://127.0.0.1:{PORT}"
CAPACITY = 16
LATENCY = 0.05


def start_mock() -> subprocess.Popen | None:
    if os.environ.get("MOCK_PORT"):
        return None
    proc = subprocess.Popen(
        [PY, MOCK, "--port", str(PORT), "--capacity", str(CAPACITY),
         "--latency", str(LATENCY)],
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


MULTI = """
defaults:
  api_url: "{api}"
  model: "gpt-4"
  rpm: 60
  generation:
    max_tokens: 256

tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem. Put your final answer after ####."
      user: "{{question}}"
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"

  mmlu:
    prompt:
      system: "Answer the multiple choice question with a single letter."
      user: "{{question}}\\n\\nA) {{a}}\\nB) {{b}}\\nC) {{c}}\\nD) {{d}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "letter"
    output_field: "choice"
"""


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="rejector-part2-")
    print(f"workdir: {tmp}\n")

    def path(*parts):
        return os.path.join(tmp, *parts)

    multi_cfg = write(path("multi.yaml"), MULTI.format(api=API))
    math_rows = [{"question": "What is 2 + 3?", "answer": "5"},
                 {"question": "What is 10 - 4?", "answer": "6"},
                 {"question": "What is 7 * 6?", "answer": "42"}]
    mmlu_rows = [
        {"question": "SAY:The answer is B) Paris", "a": "London", "b": "Paris",
         "c": "Berlin", "d": "Madrid", "answer": "B"},
        {"question": "SAY:(C)", "a": "a", "b": "b", "c": "c", "d": "d", "answer": "C"},
        {"question": "SAY:Answer: D", "a": "a", "b": "b", "c": "c", "d": "d",
         "answer": "D"},
        {"question": "SAY:A", "a": "a", "b": "b", "c": "c", "d": "d", "answer": "B"},
    ]
    math = jsonl(path("math.jsonl"), math_rows)
    qa = jsonl(path("qa.jsonl"), mmlu_rows)

    # ------------------------------------------------- multi-task happy path
    print("[multi-task: explicit mapping]")
    out = path("results1")
    code, summary, err = run(["--config", multi_cfg, "--input", f"gsm8k={math}",
                              "--input", f"mmlu={qa}", "--output", out])
    check(code == 0, "multi-task run exit 0", err)
    gsm = read_jsonl(os.path.join(out, "gsm8k.jsonl"))
    mmlu = read_jsonl(os.path.join(out, "mmlu.jsonl"))
    check(sorted(os.listdir(out)) == ["gsm8k.jsonl", "mmlu.jsonl"],
          "one output file per task", str(os.listdir(out)))
    check([r["input"] for r in gsm] == math_rows, "gsm8k rows in input order")
    check([r["input"] for r in mmlu] == mmlu_rows, "mmlu rows in input order")
    check(all(r["result"]["passed"] for r in gsm), "gsm8k all pass",
          str([r["result"] for r in gsm]))
    check(list(gsm[0]["output"]) == ["solution"], "gsm8k output_field",
          str(gsm[0]["output"]))
    check(list(mmlu[0]["output"]) == ["choice"], "mmlu output_field")
    check([r["result"]["extracted_answer"] for r in mmlu] == ["B", "C", "D", "A"],
          "letter extraction forms", str([r["result"] for r in mmlu]))
    check([r["result"]["passed"] for r in mmlu] == [True, True, True, False],
          "letter comparison against answer_field")
    check(summary["total"] == 7 and summary["passed"] == 6 and summary["failed"] == 1,
          "aggregate summary counts", str(summary))
    check(set(summary) == {"total", "passed", "failed", "total_prompt_tokens",
                           "total_completion_tokens", "total_api_calls",
                           "elapsed_seconds", "throughput_rpm", "tasks"},
          "multi summary has tasks object", str(sorted(summary)))
    check(set(summary["tasks"]) == {"gsm8k", "mmlu"}, "tasks keyed by task name")
    check(summary["tasks"]["gsm8k"] == {"total": 3, "passed": 3, "failed": 0,
                                        "total_api_calls": 3},
          "per-task summary shape", str(summary["tasks"]["gsm8k"]))
    check(summary["tasks"]["mmlu"] == {"total": 4, "passed": 3, "failed": 1,
                                       "total_api_calls": 4},
          "per-task mmlu summary", str(summary["tasks"]["mmlu"]))
    check(summary["total_api_calls"]
          == summary["tasks"]["gsm8k"]["total_api_calls"]
          + summary["tasks"]["mmlu"]["total_api_calls"],
          "per-task api calls add up to the total")
    check(gsm[0]["meta"]["model"] == "gpt-4", "defaults supply shared model")
    check(set(gsm[0]["meta"]) == {"model", "prompt_tokens", "completion_tokens",
                                  "total_tokens", "latency_ms", "finish_reason"},
          "non-judge meta keys unchanged", str(gsm[0]["meta"]))
    check(set(gsm[0]["result"]) == {"passed", "extracted_answer", "attempts"},
          "non-judge result keys unchanged", str(gsm[0]["result"]))

    # -------------------------------------------------------- directory mode
    print("\n[--input-dir]")
    data_dir = path("data")
    jsonl(os.path.join(data_dir, "gsm8k.jsonl"), math_rows)
    jsonl(os.path.join(data_dir, "mmlu.jsonl"), mmlu_rows)
    out = path("results2")
    code, summary, err = run(["--config", multi_cfg, "--input-dir", data_dir,
                              "--output", out])
    check(code == 0, "--input-dir exit 0", err)
    check(len(read_jsonl(os.path.join(out, "gsm8k.jsonl"))) == 3
          and len(read_jsonl(os.path.join(out, "mmlu.jsonl"))) == 4,
          "--input-dir found <task_name>.jsonl for both tasks")

    code, _, err = run(["--config", multi_cfg, "--input-dir", data_dir,
                        "--input", f"gsm8k={math}", "--output", path("results3")])
    check(code == 1, "--input and --input-dir cannot be combined", err)

    missing_dir = path("emptydir")
    os.makedirs(missing_dir, exist_ok=True)
    code, _, err = run(["--config", multi_cfg, "--input-dir", missing_dir,
                        "--output", path("results4")])
    check(code == 1 and "gsm8k" in err, "--input-dir missing a task file exits 1", err)

    # ----------------------------------------------------------- task select
    print("\n[--task selection]")
    out = path("results5")
    code, summary, err = run(["--config", multi_cfg, "--input", f"gsm8k={math}",
                              "--output", out, "--task", "gsm8k"])
    check(code == 0, "selected-task run exit 0", err)
    check(os.listdir(out) == ["gsm8k.jsonl"],
          "only the selected task's output file is written", str(os.listdir(out)))
    check(set(summary["tasks"]) == {"gsm8k"}, "summary only lists tasks that ran",
          str(summary))
    check(summary["total"] == 3, "totals cover only the selected task")

    out = path("results6")
    code, summary, err = run(["--config", multi_cfg, "--input-dir", data_dir,
                              "--output", out, "--task", "mmlu", "--task", "mmlu"])
    check(code == 0 and os.listdir(out) == ["mmlu.jsonl"],
          "repeated --task is deduplicated", err)

    code, _, err = run(["--config", multi_cfg, "--input", f"gsm8k={math}",
                        "--output", path("r7"), "--task", "nope"])
    check(code == 1 and "nope" in err, "unknown --task exits 1", err)

    code, _, err = run(["--config", multi_cfg, "--input", f"nope={math}",
                        "--output", path("r8")])
    check(code == 1 and "nope" in err, "unknown task in --input exits 1", err)

    code, _, err = run(["--config", multi_cfg, "--input", f"gsm8k={math}",
                        "--output", path("r9")])
    check(code == 1 and "mmlu" in err, "missing input for a task exits 1", err)

    code, _, err = run(["--config", multi_cfg, "--input", math, "--output", path("r10")])
    check(code == 1, "bare --input with a multi-task config exits 1", err)

    # An unselected task with a broken config must not block the run.
    broken = write(path("broken.yaml"), MULTI.format(api=API) + """
  busted:
    prompt:
      user: "{question}"
""")
    out = path("results11")
    code, summary, err = run(["--config", broken, "--input", f"gsm8k={math}",
                              "--output", out, "--task", "gsm8k"])
    check(code == 0 and set(summary["tasks"]) == {"gsm8k"},
          "unselected tasks are not validated", err)
    code, _, err = run(["--config", broken, "--input-dir", data_dir,
                        "--output", path("r12")])
    check(code == 1, "selected broken task still exits 1", err)

    # -------------------------------------------------------------- output
    print("\n[output handling]")
    stale = write(path("afile"), "not a directory\n")
    code, _, err = run(["--config", multi_cfg, "--input-dir", data_dir,
                        "--output", stale])
    check(code == 1 and "director" in err,
          "multi-task --output pointing at a file exits 1", err)

    nested = path("deep", "nested", "out")
    code, summary, err = run(["--config", multi_cfg, "--input-dir", data_dir,
                              "--output", nested])
    check(code == 0 and os.path.isdir(nested),
          "multi-task output directory is created", err)

    # ------------------------------------------------- single-task unchanged
    print("\n[single-task configs unchanged]")
    single = write(path("single.yaml"), f"""
task:
  name: "math_solve"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{question}}"
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
  output_field: "solution"
""")
    single_out = path("single.jsonl")
    code, summary, err = run(["--config", single, "--input", math,
                              "--output", single_out])
    check(code == 0 and os.path.isfile(single_out),
          "single-task --output writes one file", err)
    check("tasks" not in summary, "single-task summary has no tasks object",
          str(summary))
    check(set(summary) == {"total", "passed", "failed", "total_prompt_tokens",
                           "total_completion_tokens", "total_api_calls",
                           "elapsed_seconds", "throughput_rpm"},
          "single-task summary keys unchanged", str(sorted(summary)))
    code, summary, err = run(["--config", single, "--input", math,
                              "--output", single_out, "--task", "math_solve"])
    check(code == 0, "--task naming the single task works", err)
    code, _, err = run(["--config", single, "--input", math,
                        "--output", single_out, "--task", "other"])
    check(code == 1, "--task naming an unknown single task exits 1", err)
    code, _, err = run(["--config", single, "--output", single_out])
    check(code == 1, "no --input at all exits 1", err)

    # defaults + task (single-task format still honours defaults)
    single_defaults = write(path("single_defaults.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
  generation:
    max_tokens: 128
task:
  name: "math_solve"
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
""")
    code, summary, err = run(["--config", single_defaults, "--input", math,
                              "--output", path("sd.jsonl")])
    check(code == 0 and summary["total"] == 3,
          "single-task config can draw required fields from defaults", err)

    # ------------------------------------------------------ first_number
    print("\n[first_number extract]")
    fn_cfg = write(path("firstnum.yaml"), f"""
task:
  name: "firstnum"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{question}}"
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "first_number"
""")
    fn_rows = [{"question": "SAY:Score is 8 out of 10", "answer": "8"},
               {"question": "SAY:no digits here", "answer": "1"},
               {"question": "SAY:3.5 then 9", "answer": "3.5"}]
    code, _, err = run(["--config", fn_cfg,
                        "--input", jsonl(path("fn.jsonl"), fn_rows),
                        "--output", path("fn_out.jsonl")])
    rows = read_jsonl(path("fn_out.jsonl"))
    check(code == 0, "first_number run exit 0", err)
    check([r["result"]["extracted_answer"] for r in rows] == ["8", None, "3.5"],
          "first_number extraction", str([r["result"] for r in rows]))
    check([r["result"]["passed"] for r in rows] == [True, False, True],
          "first_number comparison")

    # ------------------------------------------------------------- script
    print("\n[script evaluation]")
    script_cfg = write(path("script.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  code_gen:
    prompt:
      user: "{{problem}}"
    evaluation:
      type: "script"
      command_template: "{{test_code}}"
      success_exit_code: 0
    output_field: "code"
""")
    script_rows = [
        {"problem": "SAY:good code",
         "test_code": "echo '{__response__}' | grep -q 'good code'"},
        {"problem": "SAY:bad code",
         "test_code": "echo '{__response__}' | grep -q 'good code'"},
        # output text the command itself does not contain, so finding it in the
        # JSONL would prove stdout/stderr leaked.
        {"problem": "SAY:noisy",
         "test_code": "echo loud_out | tr a-z A-Z; echo loud_err | tr a-z A-Z >&2"},
    ]
    out = path("script_out")
    code, summary, err = run(["--config", script_cfg,
                              "--input", "code_gen=" + jsonl(path("sc.jsonl"),
                                                             script_rows),
                              "--output", out])
    rows = read_jsonl(os.path.join(out, "code_gen.jsonl"))
    check(code == 0, "script run exit 0", err)
    check([r["result"]["passed"] for r in rows] == [True, False, True],
          "script exit code decides pass/fail", str([r["result"] for r in rows]))
    check(rows[1]["output"] == {"code": "bad code"},
          "non-rejection script failure keeps the response", str(rows[1]))
    raw = open(os.path.join(out, "code_gen.jsonl"), encoding="utf-8").read()
    check("LOUD_OUT" not in raw and "LOUD_ERR" not in raw,
          "command stdout/stderr stay out of the JSONL")

    # {__response__} nested inside a row field, plus a non-zero success code
    script2 = write(path("script2.yaml"), f"""
task:
  name: "code_gen"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{problem}}"
  evaluation:
    type: "script"
    command_template: "python3 -c \\"{{test_code}}\\""
    success_exit_code: 3
""")
    rows_in = [{"problem": "SAY:42", "test_code": "import sys; sys.exit(3 if '{__response__}' == '42' else 0)"},
               {"problem": "SAY:41", "test_code": "import sys; sys.exit(3 if '{__response__}' == '42' else 0)"}]
    code, _, err = run(["--config", script2,
                        "--input", jsonl(path("sc2.jsonl"), rows_in),
                        "--output", path("sc2_out.jsonl")])
    rows = read_jsonl(path("sc2_out.jsonl"))
    check(code == 0, "nested-placeholder script run exit 0", err)
    check([r["result"]["passed"] for r in rows] == [True, False],
          "success_exit_code honoured with nested {__response__}",
          str([r["result"] for r in rows]))

    print("  (timeout case takes ~10s)")
    script3 = write(path("script3.yaml"), f"""
task:
  name: "slow"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{problem}}"
  evaluation:
    type: "script"
    command_template: "sleep 30"
""")
    started = time.time()
    code, _, err = run(["--config", script3,
                        "--input", jsonl(path("sc3.jsonl"), [{"problem": "SAY:x"}]),
                        "--output", path("sc3_out.jsonl")])
    took = time.time() - started
    rows = read_jsonl(path("sc3_out.jsonl"))
    check(code == 0 and rows and rows[0]["result"]["passed"] is False,
          "script timeout is a failed evaluation", err)
    check(took < 25, f"script timeout fires at ~10s (took {took:.1f}s)")

    # rejection + script
    script4 = write(path("script4.yaml"), f"""
task:
  name: "code_gen"
  api_url: "{API}"
  model: "gpt-4"
  generation:
    scheme: "rejection"
    temperature: 0.8
    n: 3
  prompt:
    user: "{{problem}}"
  evaluation:
    type: "script"
    command_template: "exit 1"
""")
    code, summary, err = run(["--config", script4,
                              "--input", jsonl(path("sc4.jsonl"), [{"problem": "SAY:x"}]),
                              "--output", path("sc4_out.jsonl")])
    rows = read_jsonl(path("sc4_out.jsonl"))
    check(code == 0 and rows[0]["output"] is None
          and rows[0]["result"]["attempts"] == 3,
          "rejection retries a failing script", str(rows[0]["result"]))

    # ----------------------------------------------------------- llm_judge
    print("\n[llm_judge evaluation]")
    judge_cfg = write(path("judge.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
  rpm: 60
tasks:
  review:
    prompt:
      system: "You are a writing assistant."
      user: "{{prompt_text}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "JUDGE: respond with only a single integer from 1 to 10."
        user: "Rate this response.\\n\\n{{__response__}}\\n\\nCriteria: {{criteria}}\\n{{hint}}\\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"
""")
    judge_rows = [
        {"prompt_text": "SAY:A fine response", "criteria": "clarity", "hint": "SCORE=8"},
        {"prompt_text": "SAY:A poor response", "criteria": "clarity", "hint": "SCORE=3"},
        {"prompt_text": "SAY:Exactly at threshold", "criteria": "clarity",
         "hint": "SCORE=7"},
    ]
    out = path("judge_out")
    code, summary, err = run(["--config", judge_cfg,
                              "--input", "review=" + jsonl(path("jr.jsonl"), judge_rows),
                              "--output", out])
    rows = read_jsonl(os.path.join(out, "review.jsonl"))
    check(code == 0, "llm_judge run exit 0", err)
    check([r["result"]["passed"] for r in rows] == [True, False, True],
          "score >= threshold passes", str([r["result"] for r in rows]))
    check([r["result"]["judge_score"] for r in rows] == [8, 3, 7],
          "judge_score recorded", str([r["result"] for r in rows]))
    check([r["result"]["extracted_answer"] for r in rows] == ["8", "3", "7"],
          "extracted_answer is the judge's extracted text")
    check(list(rows[0]["result"]) == ["passed", "extracted_answer", "judge_score",
                                      "attempts"],
          "result keys for llm_judge", str(rows[0]["result"]))
    check(rows[0]["output"] == {"response": "A fine response"},
          "generated response is the output", str(rows[0]["output"]))
    jm = rows[0]["meta"].get("judge_meta")
    check(isinstance(jm, dict), "meta.judge_meta present", str(rows[0]["meta"]))
    check(set(jm) == {"model", "prompt_tokens", "completion_tokens", "total_tokens",
                      "latency_ms", "finish_reason"}, "judge_meta keys", str(jm))
    check(jm.get("model") == "gpt-4" and jm.get("finish_reason") == "stop"
          and jm.get("prompt_tokens") == 10 and jm.get("latency_ms") > 0,
          "judge_meta values", str(jm))
    check(summary["tasks"]["review"]["total_api_calls"] == 6,
          "judge calls count toward per-task api calls", str(summary))
    check(summary["total_api_calls"] == 6, "judge calls count toward total_api_calls")
    check(summary["total_prompt_tokens"] == 60,
          "judge tokens count toward the totals", str(summary))
    check(summary["throughput_rpm"] > 0, "throughput includes judge calls")

    # judge model defaults to the task model; evaluation.model and --eval-model win
    judge_model_cfg = write(path("judge_model.yaml"), f"""
task:
  name: "review"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{prompt_text}}"
  evaluation:
    type: "llm_judge"
    model: "judge-model"
    judge_prompt:
      system: "JUDGE: integer only."
      user: "Rate: {{__response__}} {{hint}}"
    threshold: 5
""")
    rows_in = [{"prompt_text": "SAY:ok", "hint": "SCORE=9"}]
    code, _, err = run(["--config", judge_model_cfg,
                        "--input", jsonl(path("jm.jsonl"), rows_in),
                        "--output", path("jm_out.jsonl")])
    rows = read_jsonl(path("jm_out.jsonl"))
    check(code == 0 and rows[0]["meta"]["model"] == "gpt-4"
          and rows[0]["meta"]["judge_meta"]["model"] == "judge-model",
          "evaluation.model is used for the judge call", str(rows[0]["meta"]))
    check(rows[0]["result"]["judge_score"] == 9 and rows[0]["result"]["passed"] is True,
          "default extract for llm_judge finds the score",
          str(rows[0]["result"]))

    code, _, err = run(["--config", judge_model_cfg,
                        "--input", jsonl(path("jm.jsonl"), rows_in),
                        "--output", path("jm_out2.jsonl"),
                        "--eval-model", "cli-judge"])
    rows = read_jsonl(path("jm_out2.jsonl"))
    check(code == 0 and rows[0]["meta"]["judge_meta"]["model"] == "cli-judge"
          and rows[0]["meta"]["model"] == "gpt-4",
          "--eval-model overrides only the judge model", str(rows[0]["meta"]))

    no_model_cfg = write(path("judge_nomodel.yaml"),
                         open(judge_model_cfg).read().replace(
                             '    model: "judge-model"\n', ""))
    code, _, err = run(["--config", no_model_cfg,
                        "--input", jsonl(path("jm.jsonl"), rows_in),
                        "--output", path("jm_out3.jsonl")])
    rows = read_jsonl(path("jm_out3.jsonl"))
    check(code == 0 and rows[0]["meta"]["judge_meta"]["model"] == "gpt-4",
          "judge falls back to the task model", err)

    # rejection + llm_judge
    judge_rej = write(path("judge_rej.yaml"), f"""
task:
  name: "review"
  api_url: "{API}"
  model: "gpt-4"
  generation:
    scheme: "rejection"
    temperature: 0.8
    n: 4
  prompt:
    user: "{{prompt_text}}"
  evaluation:
    type: "llm_judge"
    judge_prompt:
      system: "JUDGE: integer only."
      user: "Rate: {{__response__}} {{hint}}"
    threshold: 7
    extract: "first_number"
""")
    code, summary, err = run(["--config", judge_rej,
                              "--input", jsonl(path("jrj.jsonl"),
                                               [{"prompt_text": "SAY:candidate",
                                                 "hint": "SCORE=2,3,9"}]),
                              "--output", path("jrj_out.jsonl")])
    rows = read_jsonl(path("jrj_out.jsonl"))
    check(code == 0, "rejection + llm_judge exit 0", err)
    check(rows[0]["result"]["attempts"] == 3 and rows[0]["result"]["passed"] is True
          and rows[0]["result"]["judge_score"] == 9,
          "rejection keeps sampling until the judge passes", str(rows[0]["result"]))
    check(isinstance(rows[0]["meta"], list) and len(rows[0]["meta"]) == 3
          and all("judge_meta" in m for m in rows[0]["meta"]),
          "one judge_meta per attempt", str(rows[0]["meta"]))
    check(summary["total_api_calls"] == 6,
          "6 api calls for 3 generate+judge attempts", str(summary))

    # judge config validation
    bad_judge = write(path("bad_judge.yaml"), f"""
task:
  name: "review"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{prompt_text}}"
  evaluation:
    type: "llm_judge"
    threshold: 5
""")
    code, _, err = run(["--config", bad_judge, "--input", path("jm.jsonl"),
                        "--output", path("bj.jsonl")])
    check(code == 1 and "judge_prompt" in err, "llm_judge needs judge_prompt", err)

    bad_script = write(path("bad_script.yaml"), f"""
task:
  name: "s"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{prompt_text}}"
  evaluation:
    type: "script"
""")
    code, _, err = run(["--config", bad_script, "--input", path("jm.jsonl"),
                        "--output", path("bs.jsonl")])
    check(code == 1 and "command_template" in err, "script needs command_template", err)

    bad_extract = write(path("bad_extract.yaml"), f"""
task:
  name: "s"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{prompt_text}}"
  evaluation:
    type: "exact_match"
    answer_field: "hint"
    extract: "bogus"
""")
    code, _, err = run(["--config", bad_extract, "--input", path("jm.jsonl"),
                        "--output", path("be.jsonl")])
    check(code == 1 and "extract" in err, "invalid extract method exits 1", err)

    judge_missing_field = write(path("judge_missing.yaml"), f"""
task:
  name: "review"
  api_url: "{API}"
  model: "gpt-4"
  prompt:
    user: "{{prompt_text}}"
  evaluation:
    type: "llm_judge"
    judge_prompt:
      user: "Rate: {{__response__}} {{nope}}"
    threshold: 5
""")
    code, _, err = run(["--config", judge_missing_field, "--input", path("jm.jsonl"),
                        "--output", path("jmf.jsonl")])
    check(code == 1 and "nope" in err and "row 0" in err,
          "judge template field missing from a row exits 1 before any request", err)

    # ------------------------------------------------------- task overriding
    print("\n[defaults / task merging]")
    merge_cfg = write(path("merge.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "default-model"
  rpm: 60
  generation:
    scheme: "greedy"
    max_tokens: 64
  prompt:
    system: "shared system"
    user: "{{question}}"
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
  output_field: "shared"
tasks:
  inherits: {{}}
  overrides:
    model: "task-model"
    prompt:
      user: "override {{question}}"
    output_field: "own"
""")
    out = path("merge_out")
    code, summary, err = run(["--config", merge_cfg, "--input-dir", data_dir,
                              "--output", out, "--task", "inherits"])
    check(code == 1, "merged task still needs its own input file", err)
    rows_in = [{"question": "What is 2 + 3?", "answer": "5"}]
    inherits_in = jsonl(path("inh.jsonl"), rows_in)
    code, summary, err = run(["--config", merge_cfg,
                              "--input", f"inherits={inherits_in}",
                              "--input", f"overrides={inherits_in}",
                              "--output", out])
    check(code == 0, "defaults-only task runs", err)
    inh = read_jsonl(os.path.join(out, "inherits.jsonl"))
    ovr = read_jsonl(os.path.join(out, "overrides.jsonl"))
    check(inh[0]["meta"]["model"] == "default-model"
          and ovr[0]["meta"]["model"] == "task-model",
          "task overrides defaults", str([inh[0]["meta"]["model"],
                                          ovr[0]["meta"]["model"]]))
    check(list(inh[0]["output"]) == ["shared"] and list(ovr[0]["output"]) == ["own"],
          "output_field merged per task")
    check("override" in ovr[0]["output"]["own"],
          "prompt section merged per task", str(ovr[0]["output"]))
    check(inh[0]["result"]["passed"] is True and ovr[0]["result"]["passed"] is True,
          "inherited evaluation applies to both tasks")

    # ------------------------------------------------------- concurrency
    print("\n[cross-task concurrency]")
    big_a = jsonl(path("big_a.jsonl"),
                  [{"question": f"What is {i} + {i}?", "answer": str(2 * i)}
                   for i in range(1, 21)])
    big_b = jsonl(path("big_b.jsonl"),
                  [{"question": f"SAY:The answer is B) {i}", "a": "1", "b": "2",
                    "c": "3", "d": "4", "answer": "B"} for i in range(1, 21)])
    with urllib.request.urlopen(f"{API}/stats", timeout=5) as resp:
        before = len(json.loads(resp.read())["arrivals"])
    out = path("conc_out")
    code, summary, err = run(["--config", multi_cfg, "--input", f"gsm8k={big_a}",
                              "--input", f"mmlu={big_b}", "--output", out])
    check(code == 0 and summary["total"] == 40, "concurrent multi-task run exit 0", err)
    with urllib.request.urlopen(f"{API}/stats", timeout=5) as resp:
        stats = json.loads(resp.read())
    arrivals = stats["arrivals"][before:]
    kinds = ["mmlu" if "SAY:" in a else "gsm8k" for a in arrivals]
    check(len(set(kinds[:8])) == 2, "requests from both tasks interleave",
          str(kinds[:8]))
    gsm_arrivals = [int(a.split("What is ")[1].split(" ")[0])
                    for a in arrivals if "What is " in a]
    # Dispatch is strictly in input order per task; arrival order is best effort
    # (concurrent connection setup can swap neighbours on a loaded machine).
    displacement = max((abs(value - index - 1)
                        for index, value in enumerate(gsm_arrivals)), default=0)
    check(displacement <= 2,
          "each task's requests reach the server in input order", str(gsm_arrivals))
    gsm = read_jsonl(os.path.join(out, "gsm8k.jsonl"))
    check([r["input"]["question"] for r in gsm]
          == [f"What is {i} + {i}?" for i in range(1, 21)],
          "output order matches input order under concurrency")

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
