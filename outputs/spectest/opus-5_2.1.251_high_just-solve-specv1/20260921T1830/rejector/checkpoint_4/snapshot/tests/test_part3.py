#!/usr/bin/env python3
"""End-to-end test suite for the Part 3 features of rejector.py.

Usage: python tests/test_part3.py  (starts its own mock server)

Covers in-context learning setups (inline and file-backed), the selection
strategies, multiple solutions per input, the list output format and the new
summary fields.
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
sys.path.insert(0, ROOT)
import rejector  # noqa: E402  (in-process checks for prompt construction)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = int(os.environ["MOCK_PORT"]) if os.environ.get("MOCK_PORT") else free_port()
API = f"http://127.0.0.1:{PORT}"
CAPACITY = 16
LATENCY = 0.02


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


def server_total() -> int:
    with urllib.request.urlopen(f"{API}/stats", timeout=5) as resp:
        return json.loads(resp.read())["total"]


SETUPS = """
    icl:
      setups:
        - name: "chain_of_thought"
          examples:
            - input: {{question: "What is 2+2?"}}
              output: "Let me think step by step.\\n2 + 2 = 4\\n#### 4"
            - input: {{question: "If I have 3 cats and get 2 more, how many cats do I have?"}}
              output: "Step by step:\\nI start with 3 cats.\\nI get 2 more.\\n3 + 2 = 5\\n#### 5"
        - name: "direct"
          examples:
            - input: {{question: "What is 2+2?"}}
              output: "#### 4"
            - input: {{question: "If I have 3 cats and get 2 more, how many cats do I have?"}}
              output: "#### 5"
      k: {k}
      strategy: "{strategy}"
"""


def icl_task(scheme: str, strategy: str = "round_robin", k: int = 2,
             num_solutions: int = 3, extra_generation: str = "",
             evaluation: bool = True) -> str:
    temperature = "0.0" if scheme == "greedy" else "0.7"
    eval_block = """
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
""" if evaluation else ""
    return f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
  rpm: 60
tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem step by step. Final answer after ####."
      user: "{{question}}"
{SETUPS.format(k=k, strategy=strategy)}
    generation:
      scheme: "{scheme}"
      temperature: {temperature}
{extra_generation}{eval_block}
    output_field: "solution"
    num_solutions: {num_solutions}
"""


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="rejector-part3-")
    print(f"workdir: {tmp}\n")

    def path(*parts):
        return os.path.join(tmp, *parts)

    rows = [{"question": "What is 15 + 27?", "answer": "42"},
            {"question": "What is 7 * 6?", "answer": "42"}]
    data = jsonl(path("math.jsonl"), rows)

    # ------------------------------------------------------ prompt assembly
    print("[ICL prompt construction]")
    cfg = write(path("rr.yaml"), icl_task("rejection", "round_robin"))
    bundle = rejector.load_config(cfg, {}, None)
    task = bundle.tasks[0]
    messages = rejector.with_icl(
        rejector.build_messages(task, rows[0], 0), task.icl.setups[0]
    )
    check([m["role"] for m in messages]
          == ["system", "user", "assistant", "user", "assistant", "user"],
          "examples become alternating user/assistant turns",
          str([m["role"] for m in messages]))
    check(messages[0]["content"].startswith("Solve the math problem"),
          "system message stays first")
    check(messages[1]["content"] == "What is 2+2?",
          "example input rendered through prompt.user", messages[1]["content"])
    check(messages[2]["content"] == "Let me think step by step.\n2 + 2 = 4\n#### 4",
          "example output inserted verbatim", messages[2]["content"])
    check(messages[-1]["content"] == "What is 15 + 27?",
          "row prompt remains the final user turn", messages[-1]["content"])
    check([s.name for s in task.icl.setups] == ["chain_of_thought", "direct"],
          "setups keep declaration order")

    cfg_k1 = write(path("k1.yaml"), icl_task("rejection", "fixed", k=1))
    task_k1 = rejector.load_config(cfg_k1, {}, None).tasks[0]
    check([len(s.examples) for s in task_k1.icl.setups] == [1, 1],
          "k smaller than the example count keeps the first k",
          str([len(s.examples) for s in task_k1.icl.setups]))
    check(task_k1.icl.setups[0].examples[0].input == {"question": "What is 2+2?"},
          "k keeps the first examples, in order")
    no_k = write(path("nok.yaml"), icl_task("rejection", "fixed", k=99))
    task_no_k = rejector.load_config(no_k, {}, None).tasks[0]
    check([len(s.examples) for s in task_no_k.icl.setups] == [2, 2],
          "k larger than the setup uses every example")
    task_cli_k = rejector.load_config(cfg, {"icl_k": 1}, None).tasks[0]
    check(len(task_cli_k.icl.setups[0].examples) == 1, "--icl-k overrides config k")
    task_cli_s = rejector.load_config(cfg, {"icl_strategy": "fixed"}, None).tasks[0]
    check(task_cli_s.icl.strategy == "fixed", "--icl-strategy overrides config")

    # ----------------------------------------------------------- round robin
    print("\n[strategies]")
    out = path("rr.jsonl")
    code, summary, err = run(["--config", cfg, "--input", f"gsm8k={data}",
                              "--output", path("rr_out"), "--task", "gsm8k"])
    check(code == 0, "round_robin run exit 0", err)
    rr = read_jsonl(path("rr_out", "gsm8k.jsonl"))

    rr_rows = [{"question": "REJECT4 What is 2 + 3?", "answer": "5"}]
    rr_data = jsonl(path("rr_rows.jsonl"), rr_rows)
    code, summary, err = run(["--config", cfg, "--input", f"gsm8k={rr_data}",
                              "--output", path("rr_out2")])
    check(code == 0, "round_robin rejection run exit 0", err)
    row = read_jsonl(path("rr_out2", "gsm8k.jsonl"))[0]
    check([m["icl_setup"] for m in row["meta"]][:5]
          == ["chain_of_thought", "direct", "chain_of_thought", "direct",
              "chain_of_thought"],
          "round_robin cycles setups across attempts",
          str([m["icl_setup"] for m in row["meta"]]))

    fixed_cfg = write(path("fixed.yaml"), icl_task("rejection", "fixed"))
    code, _, err = run(["--config", fixed_cfg, "--input", f"gsm8k={rr_data}",
                        "--output", path("fx_out")])
    fx = read_jsonl(path("fx_out", "gsm8k.jsonl"))[0]
    check(code == 0 and {m["icl_setup"] for m in fx["meta"]} == {"chain_of_thought"},
          "fixed always uses the first setup", str([m["icl_setup"] for m in fx["meta"]]))

    rand_cfg = write(path("rand.yaml"), icl_task("rejection", "random"))
    code, _, err = run(["--config", rand_cfg, "--input", f"gsm8k={rr_data}",
                        "--output", path("rd_out")])
    rd = read_jsonl(path("rd_out", "gsm8k.jsonl"))[0]
    check(code == 0
          and {m["icl_setup"] for m in rd["meta"]} <= {"chain_of_thought", "direct"},
          "random picks a declared setup for each attempt", err)

    code, _, err = run(["--config", fixed_cfg, "--input", f"gsm8k={rr_data}",
                        "--output", path("cli_out"), "--icl-strategy", "round_robin"])
    cli = read_jsonl(path("cli_out", "gsm8k.jsonl"))[0]
    check(code == 0 and [m["icl_setup"] for m in cli["meta"]][:2]
          == ["chain_of_thought", "direct"],
          "--icl-strategy changes the run's strategy", err)

    # ----------------------------------------------------------- output shape
    print("\n[list output format]")
    check(isinstance(rr[0]["output"], list) and isinstance(rr[0]["meta"], list),
          "output and meta are lists", str(type(rr[0]["output"])))
    check(len(rr[0]["output"]) == 3 and all(
        set(o) == {"solution", "icl_setup"} for o in rr[0]["output"]),
        "each solution carries output_field plus icl_setup", str(rr[0]["output"]))
    check(rr[0]["result"] == {"passed": 3, "failed": 0, "attempts": 3},
          "result reports passed/failed/attempts", str(rr[0]["result"]))
    check(set(rr[0]["meta"][0]) == {"model", "prompt_tokens", "completion_tokens",
                                    "total_tokens", "latency_ms", "finish_reason",
                                    "icl_setup", "evaluation_passed"},
          "meta entries gain icl_setup and evaluation_passed",
          str(rr[0]["meta"][0]))
    check(all(m["evaluation_passed"] is True for m in rr[0]["meta"]),
          "evaluation_passed recorded per attempt")
    check(summary is not None, "summary printed")

    single = write(path("single_icl.yaml"),
                   icl_task("rejection", "fixed", num_solutions=1))
    code, summary, err = run(["--config", single, "--input", f"gsm8k={data}",
                              "--output", path("single_out")])
    srows = read_jsonl(path("single_out", "gsm8k.jsonl"))
    check(code == 0 and isinstance(srows[0]["output"], list)
          and len(srows[0]["output"]) == 1,
          "ICL with num_solutions 1 still uses the list format", err)
    check(srows[0]["output"][0]["icl_setup"] == "chain_of_thought",
          "the single output records its setup")
    check(isinstance(srows[0]["meta"], list)
          and srows[0]["meta"][0]["evaluation_passed"] is True,
          "meta is a list with evaluation_passed", str(srows[0]["meta"]))

    # -------------------------------------------------------- greedy with ICL
    print("\n[greedy with ICL]")
    greedy = write(path("greedy.yaml"), icl_task("greedy", "round_robin",
                                                 num_solutions=5))
    code, summary, err = run(["--config", greedy, "--input", f"gsm8k={data}",
                              "--output", path("greedy_out")])
    grows = read_jsonl(path("greedy_out", "gsm8k.jsonl"))
    check(code == 0, "greedy ICL run exit 0", err)
    check(len(grows[0]["output"]) == 2 and grows[0]["result"]["attempts"] == 2,
          "greedy produces at most one solution per setup", str(grows[0]["result"]))
    check([o["icl_setup"] for o in grows[0]["output"]]
          == ["chain_of_thought", "direct"],
          "greedy walks setups in declared order",
          str([o["icl_setup"] for o in grows[0]["output"]]))
    check(summary["tasks"]["gsm8k"]["total_solutions"] == 4,
          "greedy solution count", str(summary))

    greedy1 = write(path("greedy1.yaml"), icl_task("greedy", "fixed",
                                                   num_solutions=1))
    code, _, err = run(["--config", greedy1, "--input", f"gsm8k={data}",
                        "--output", path("greedy1_out")])
    g1 = read_jsonl(path("greedy1_out", "gsm8k.jsonl"))
    check(code == 0 and len(g1[0]["output"]) == 1, "greedy num_solutions 1", err)

    # -------------------------------------------------------- sample with ICL
    print("\n[sample]")
    sample = write(path("sample.yaml"), icl_task("sample", "round_robin",
                                                 num_solutions=4))
    never = jsonl(path("never.jsonl"), [{"question": "NEVER What is 1 + 1?",
                                         "answer": "2"}])
    code, summary, err = run(["--config", sample, "--input", f"gsm8k={never}",
                              "--output", path("sample_out")])
    srow = read_jsonl(path("sample_out", "gsm8k.jsonl"))[0]
    check(code == 0 and len(srow["output"]) == 4,
          "sample makes one generation per requested solution", err)
    check(srow["result"] == {"passed": 0, "failed": 4, "attempts": 4},
          "sample keeps rejected solutions but counts them failed",
          str(srow["result"]))
    check([o["icl_setup"] for o in srow["output"]]
          == ["chain_of_thought", "direct", "chain_of_thought", "direct"],
          "sample follows the ICL strategy", str(srow["output"]))
    check(summary["passed"] == 0 and summary["failed"] == 1,
          "a row with no passing solution counts as failed", str(summary))

    plain = write(path("plain_sample.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  gsm8k:
    prompt:
      user: "{{question}}"
    generation:
      scheme: "sample"
      temperature: 0.7
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
    num_solutions: 3
""")
    code, summary, err = run(["--config", plain, "--input", f"gsm8k={data}",
                              "--output", path("plain_out")])
    prow = read_jsonl(path("plain_out", "gsm8k.jsonl"))[0]
    check(code == 0 and len(prow["output"]) == 3,
          "sample without ICL makes num_solutions requests", err)
    check(all(o["icl_setup"] is None for o in prow["output"])
          and all(m["icl_setup"] is None for m in prow["meta"]),
          "icl_setup is null without ICL", str(prow["output"]))
    check(summary["tasks"]["gsm8k"] == {
        "total": 2, "passed": 2, "failed": 0, "total_solutions": 6,
        "avg_solutions_per_input": 3.0, "total_api_calls": 6},
        "per-task summary gains solution counts", str(summary["tasks"]))
    check(summary["total_solutions"] == 6 and summary["avg_solutions_per_input"] == 3.0,
          "run summary gains solution counts", str(summary))

    # ------------------------------------------------------------- rejection
    print("\n[rejection with multiple solutions]")
    rej = write(path("rej.yaml"), icl_task(
        "rejection", "round_robin", num_solutions=3,
        extra_generation="      max_attempts: 8\n"))
    reject_rows = [{"question": "REJECT2 What is 2 + 3?", "answer": "5"}]
    rdata = jsonl(path("rej.jsonl"), reject_rows)
    code, summary, err = run(["--config", rej, "--input", f"gsm8k={rdata}",
                              "--output", path("rej_out")])
    rrow = read_jsonl(path("rej_out", "gsm8k.jsonl"))[0]
    check(code == 0 and rrow["result"] == {"passed": 3, "failed": 2, "attempts": 5},
          "rejection collects num_solutions passing solutions", str(rrow["result"]))
    check(len(rrow["output"]) == 3, "only passing solutions are written")
    check([m["evaluation_passed"] for m in rrow["meta"]]
          == [False, False, True, True, True],
          "each attempt records its evaluation result", str(rrow["meta"]))

    # exhausting the budget: NEVER never passes
    code, summary, err = run(["--config", rej, "--input", f"gsm8k={never}",
                              "--output", path("rej_out2")])
    nrow = read_jsonl(path("rej_out2", "gsm8k.jsonl"))[0]
    check(code == 0 and nrow["result"] == {"passed": 0, "failed": 8, "attempts": 8},
          "max_attempts bounds the rejection loop", str(nrow["result"]))
    check(nrow["output"] == [], "no passing solution writes an empty list")

    # max_attempts defaults to 3 * num_solutions
    nodefault = write(path("nodefault.yaml"),
                      icl_task("rejection", "fixed", num_solutions=2))
    code, _, err = run(["--config", nodefault, "--input", f"gsm8k={never}",
                        "--output", path("def_out")])
    drow = read_jsonl(path("def_out", "gsm8k.jsonl"))[0]
    check(code == 0 and drow["result"]["attempts"] == 6,
          "max_attempts defaults to 3 * num_solutions", str(drow["result"]))

    # partial results: a judge that only scores the first two attempts highly
    judge = write(path("judge.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  review:
    prompt:
      system: "You are a writing assistant."
      user: "{{prompt_text}}"
    generation:
      scheme: "rejection"
      temperature: 0.7
      max_attempts: 10
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "JUDGE: respond with only a single integer from 1 to 10."
        user: "Rate this response.\\n\\n{{__response__}}\\nScore:"
      threshold: 7
    output_field: "response"
    num_solutions: 5
""")
    jdata = jsonl(path("judge.jsonl"),
                  [{"prompt_text": "SAY:A response SCORE=9,9,1,1,1,1,1,1,1,1"}])
    code, summary, err = run(["--config", judge, "--input", f"review={jdata}",
                              "--output", path("judge_out")])
    jrow = read_jsonl(path("judge_out", "review.jsonl"))[0]
    check(code == 0 and jrow["result"] == {"passed": 2, "failed": 8, "attempts": 10},
          "partial rejection result", str(jrow["result"]))
    check(len(jrow["output"]) == 2, "only the passing attempts are written")
    check(all("judge_meta" in m for m in jrow["meta"]),
          "judge metadata still recorded per attempt")
    check(summary["tasks"]["review"]["total_api_calls"] == 20,
          "judge calls count toward the task total", str(summary))

    # ------------------------------------------------------ no evaluation
    print("\n[no evaluation in list format]")
    noeval = write(path("noeval.yaml"), icl_task("sample", "round_robin",
                                                 num_solutions=2,
                                                 evaluation=False))
    code, summary, err = run(["--config", noeval, "--input", f"gsm8k={data}",
                              "--output", path("noeval_out")])
    erow = read_jsonl(path("noeval_out", "gsm8k.jsonl"))[0]
    check(code == 0 and all(m["evaluation_passed"] is None for m in erow["meta"]),
          "evaluation_passed is null without evaluation", err)
    check(erow["result"] == {"passed": 2, "failed": 0, "attempts": 2},
          "passed counts emitted outputs without evaluation", str(erow["result"]))

    # ------------------------------------------------------ legacy behaviour
    print("\n[legacy single-solution behaviour]")
    legacy = write(path("legacy.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  gsm8k:
    prompt:
      user: "{{question}}"
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
      max_attempts: 2
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
""")
    legacy_rows = jsonl(path("legacy.jsonl"),
                        [{"question": "REJECT3 What is 2 + 3?", "answer": "5"}])
    code, summary, err = run(["--config", legacy, "--input", f"gsm8k={legacy_rows}",
                              "--output", path("legacy_out")])
    lrow = read_jsonl(path("legacy_out", "gsm8k.jsonl"))[0]
    check(code == 0 and isinstance(lrow["output"], dict),
          "num_solutions 1 without ICL keeps the Part 1 output shape", str(lrow))
    check(lrow["result"] == {"passed": True, "extracted_answer": "5", "attempts": 4},
          "legacy rejection uses generation.n and ignores max_attempts",
          str(lrow["result"]))
    check(set(summary["tasks"]["gsm8k"]) == {"total", "passed", "failed",
                                             "total_api_calls"},
          "legacy tasks keep the Part 2 summary shape", str(summary["tasks"]))
    check("total_solutions" not in summary, "legacy run summary unchanged",
          str(summary))

    code, summary, err = run(["--config", legacy, "--input", f"gsm8k={data}",
                              "--output", path("cli_ns"), "--num-solutions", "2"])
    crow = read_jsonl(path("cli_ns", "gsm8k.jsonl"))[0]
    check(code == 0 and isinstance(crow["output"], list) and len(crow["output"]) == 2,
          "--num-solutions overrides the config", err)

    # ------------------------------------------------------------ file setups
    print("\n[file-backed setups]")
    write(path("files", "icl", "detailed.jsonl"),
          '{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\\n#### 5"}\n'
          '\n'
          '{"input": {"question": "What is 4 - 1?"}, "output": "#### 3"}\n')
    file_cfg = write(path("files", "file.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  gsm8k:
    prompt:
      user: "{{question}}"
    icl:
      setups:
        - name: "detailed"
          file: "icl/detailed.jsonl"
      k: 3
      strategy: "fixed"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
""")
    ftask = rejector.load_config(file_cfg, {}, None).tasks[0]
    check([e.output for e in ftask.icl.setups[0].examples]
          == ["10 divided by 2 is 5.\n#### 5", "#### 3"],
          "JSONL examples load (blank lines skipped)",
          str([e.output for e in ftask.icl.setups[0].examples]))
    check(ftask.icl.setups[0].messages[1]["content"] == "10 divided by 2 is 5.\n#### 5",
          "file example output used verbatim")
    code, summary, err = run(["--config", file_cfg, "--input", f"gsm8k={data}",
                              "--output", path("file_out")])
    frow = read_jsonl(path("file_out", "gsm8k.jsonl"))[0]
    check(code == 0 and frow["output"][0]["icl_setup"] == "detailed",
          "file-backed setup runs", err)

    def broken(name: str, content: str) -> str:
        write(path("files", "icl", name), content)
        return write(path("files", f"{name}.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  gsm8k:
    prompt:
      user: "{{question}}"
    icl:
      setups:
        - name: "broken"
          file: "icl/{name}"
    generation:
      scheme: "greedy"
    output_field: "solution"
""")

    before = server_total()
    bad_json = broken("bad.jsonl",
                      '{"input": {"question": "ok"}, "output": "fine"}\n'
                      'not json at all\n')
    code, _, err = run(["--config", bad_json, "--input", f"gsm8k={data}",
                        "--output", path("bad_out")])
    check(code == 1 and "not valid JSON" in err,
          "malformed JSONL line exits 1 with 'not valid JSON'", err)
    check(server_total() == before, "no API requests were sent first")

    missing = broken("missing.jsonl", '{"input": {"question": "ok"}}\n')
    code, _, err = run(["--config", missing, "--input", f"gsm8k={data}",
                        "--output", path("m_out")])
    check(code == 1 and "output" in err, "missing 'output' key exits 1", err)

    badtype = broken("badtype.jsonl", '{"input": "nope", "output": "x"}\n')
    code, _, err = run(["--config", badtype, "--input", f"gsm8k={data}",
                        "--output", path("t_out")])
    check(code == 1, "non-object 'input' exits 1", err)

    code, _, err = run(["--config", broken("gone.jsonl", ""), "--input",
                        f"gsm8k={data}", "--output", path("g_out")])
    check(code == 1, "an empty example file exits 1", err)
    os.remove(path("files", "icl", "gone.jsonl"))
    code, _, err = run(["--config", path("files", "gone.jsonl.yaml"), "--input",
                        f"gsm8k={data}", "--output", path("g2_out")])
    check(code == 1 and "not found" in err, "a missing example file exits 1", err)

    # ------------------------------------------------------ config validation
    print("\n[ICL config validation]")

    def icl_cfg(name: str, body: str) -> str:
        return write(path(f"{name}.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
tasks:
  gsm8k:
    prompt:
      user: "{{question}}"
    icl:
{body}
    generation:
      scheme: "greedy"
    output_field: "solution"
""")

    cases = [
        ("no_setups", "      k: 2\n", "setups is required"),
        ("empty_setups", "      setups: []\n", "non-empty"),
        ("no_name", "      setups:\n        - examples:\n"
                    "            - input: {question: \"a\"}\n"
                    "              output: \"b\"\n", "name"),
        ("both", "      setups:\n        - name: \"x\"\n          file: \"icl/detailed.jsonl\"\n"
                 "          examples:\n            - input: {question: \"a\"}\n"
                 "              output: \"b\"\n", "exactly one"),
        ("neither", "      setups:\n        - name: \"x\"\n", "exactly one"),
        ("bad_strategy", "      setups:\n        - name: \"x\"\n          examples:\n"
                         "            - input: {question: \"a\"}\n              output: \"b\"\n"
                         "      strategy: \"nope\"\n", "strategy"),
        ("bad_k", "      setups:\n        - name: \"x\"\n          examples:\n"
                  "            - input: {question: \"a\"}\n              output: \"b\"\n"
                  "      k: 0\n", "k"),
        ("bad_output", "      setups:\n        - name: \"x\"\n          examples:\n"
                       "            - input: {question: \"a\"}\n              output: 5\n",
         "output"),
        ("missing_field", "      setups:\n        - name: \"x\"\n          examples:\n"
                          "            - input: {other: \"a\"}\n              output: \"b\"\n",
         "question"),
    ]
    for name, body, needle in cases:
        code, _, err = run(["--config", icl_cfg(name, body), "--input",
                            f"gsm8k={data}", "--output", path(f"v_{name}")])
        check(code == 1 and needle in err, f"invalid icl config: {name}", err)

    code, _, err = run(["--config", cfg, "--input", f"gsm8k={data}",
                        "--output", path("ns_out"), "--num-solutions", "0"])
    check(code == 1, "--num-solutions 0 exits 1", err)
    code, _, err = run(["--config", cfg, "--input", f"gsm8k={data}",
                        "--output", path("ns_out"), "--icl-k", "x"])
    check(code == 1, "non-integer --icl-k exits 1", err)

    # defaults may carry icl / num_solutions for every task
    shared = write(path("shared.yaml"), f"""
defaults:
  api_url: "{API}"
  model: "gpt-4"
  num_solutions: 2
  icl:
    setups:
      - name: "shared_setup"
        examples:
          - input: {{question: "What is 2+2?"}}
            output: "#### 4"
    strategy: "fixed"
tasks:
  gsm8k:
    prompt:
      user: "{{question}}"
    generation:
      scheme: "sample"
      temperature: 0.5
    output_field: "solution"
""")
    code, summary, err = run(["--config", shared, "--input", f"gsm8k={data}",
                              "--output", path("shared_out")])
    shrow = read_jsonl(path("shared_out", "gsm8k.jsonl"))[0]
    check(code == 0 and len(shrow["output"]) == 2
          and shrow["output"][0]["icl_setup"] == "shared_setup",
          "defaults can supply icl and num_solutions", err)
    check(summary["tasks"]["gsm8k"]["avg_solutions_per_input"] == 2.0,
          "avg_solutions_per_input", str(summary))

    # ------------------------------------------------- failures keep working
    print("\n[failures]")
    fail_rows = jsonl(path("fail.jsonl"),
                      [{"question": "ALWAYS_500 What is 1 + 1?", "answer": "2"}])
    code, summary, err = run(["--config", plain, "--input", f"gsm8k={fail_rows}",
                              "--output", path("fail_out")])
    frow = read_jsonl(path("fail_out", "gsm8k.jsonl"))[0]
    check(code == 0 and frow["output"] == [] and frow["result"]["passed"] == 0,
          "a failing row yields no solutions", str(frow))
    check(summary["failed"] == 1, "failing rows still count as failed",
          str(summary))

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
