"""Spec section: Part 2 / CLI Changes (--task, --eval-model, input/output modes)."""
from __future__ import annotations

import copy
import os

import pytest

from conftest import (GSM8K_TASK, JUDGE_TASK, MMLU_TASK, base_config,
                      judge_responder, multi_config)
from mock_server import MockAPI, always, completion


MATH_ROW = {"question": "5+3?", "answer": "8"}
QA_ROW = {"question": "capital?", "a": "London", "b": "Paris", "c": "Berlin",
          "d": "Madrid", "answer": "B"}


def _two_task_cfg(api_url):
    return multi_config(api_url, {
        "gsm8k": copy.deepcopy(GSM8K_TASK),
        "mmlu": copy.deepcopy(MMLU_TASK),
    })


def _responder(req, i):
    user = req["messages"][-1]["content"]
    if "capital" in user:
        return 200, completion("The answer is B) Paris")
    return 200, completion("#### 8")


# ---------------------------------------------------------------------------
# Phrase: "explicit mapping mode:
#   --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl
#   --output results/"
# Context: Part 2 / CLI Changes.  The spec's documented invocation.
# ---------------------------------------------------------------------------
def test_explicit_input_mapping_mode(run_tool, write_config, write_input,
                                     workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    assert res.rows_for("gsm8k")[0]["input"] == MATH_ROW
    assert res.rows_for("mmlu")[0]["input"] == QA_ROW


# Context: same phrase - a mapping naming a task that is not in the config is
# an error (AMBIGUITIES T31).
def test_input_mapping_for_unknown_task_exits_1(run_tool, write_config,
                                                write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"nope={math}"], output=out)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a missing mapping for a configured task is an error
# (AMBIGUITIES T30).
def test_missing_input_mapping_exits_1(run_tool, write_config, write_input,
                                       workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out)
    assert res.returncode == 1
    assert "mmlu" in res.stderr


# Context: same phrase - a mapping pointing at a file that does not exist is
# an input error.
def test_input_mapping_to_missing_file_exits_1(run_tool, write_config,
                                               write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={workdir}/nope.jsonl"],
                       output=out)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "directory mode:
#   --config multi.yaml --input-dir data/ --output results/"
# Context: Part 2 / CLI Changes.
# ---------------------------------------------------------------------------
def test_input_dir_mode(run_tool, write_config, write_input, workdir):
    data_dir = workdir / "data"
    data_dir.mkdir()
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        write_input([MATH_ROW], name="data/gsm8k.jsonl")
        write_input([QA_ROW], name="data/mmlu.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, None, output=out,
                       extra=["--input-dir", str(data_dir)])
    assert res.returncode == 0, res
    assert len(res.rows_for("gsm8k")) == 1
    assert len(res.rows_for("mmlu")) == 1


# ---------------------------------------------------------------------------
# Phrase: "`--input-dir` looks for `<task_name>.jsonl`"
# Context: Part 2 / CLI Changes.  Files named after anything else are not
# picked up, and a missing one is an error (AMBIGUITIES T30).
# ---------------------------------------------------------------------------
def test_input_dir_requires_the_task_named_file(run_tool, write_config,
                                                write_input, workdir):
    data_dir = workdir / "data"
    data_dir.mkdir()
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        write_input([MATH_ROW], name="data/gsm8k.jsonl")
        write_input([QA_ROW], name="data/questions.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, None, output=out,
                       extra=["--input-dir", str(data_dir)])
    assert res.returncode == 1
    assert "mmlu" in res.stderr


# ---------------------------------------------------------------------------
# Phrase: "for multi-task configs, explicit `--input <task=path>` and
#          `--input-dir` are alternative modes; do not combine them"
# Context: Part 2 / CLI Changes (AMBIGUITIES T31).
# ---------------------------------------------------------------------------
def test_combining_input_and_input_dir_exits_1(run_tool, write_config,
                                               write_input, workdir):
    data_dir = workdir / "data"
    data_dir.mkdir()
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="data/gsm8k.jsonl")
        write_input([QA_ROW], name="data/mmlu.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out,
                       extra=["--input-dir", str(data_dir)])
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - neither mode given is an error.
def test_multi_config_with_no_input_exits_1(run_tool, write_config, workdir):
    cfg = write_config(_two_task_cfg("http://127.0.0.1:1"))
    res = run_tool(cfg, None, output=str(workdir / "results"))
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a bare `--input <path>` cannot be attributed to a task
# in a multi-task config (AMBIGUITIES T31).
def test_bare_input_path_with_multi_config_exits_1(run_tool, write_config,
                                                   write_input, workdir):
    cfg = write_config(_two_task_cfg("http://127.0.0.1:1"))
    math = write_input([MATH_ROW], name="math.jsonl")
    res = run_tool(cfg, math, output=str(workdir / "results"))
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "`--task <name>`: repeatable; run only the selected task or tasks"
# Context: Part 2 / CLI Changes, and the Examples "Selected-task run".
# ---------------------------------------------------------------------------
def test_task_flag_runs_only_the_selected_task(run_tool, write_config,
                                               write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out,
                       extra=["--task", "gsm8k"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1
    assert list(res.summary["tasks"]) == ["gsm8k"]


# Context: same phrase - repeatable, selecting a subset of three tasks.
def test_task_flag_is_repeatable(run_tool, write_config, write_input, workdir):
    tasks = {
        "gsm8k": copy.deepcopy(GSM8K_TASK),
        "mmlu": copy.deepcopy(MMLU_TASK),
        "other": copy.deepcopy(GSM8K_TASK),
    }
    with MockAPI(_responder) as api:
        cfg = write_config(multi_config(api.url, tasks))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out,
                       extra=["--task", "gsm8k", "--task", "mmlu"])
    assert res.returncode == 0, res
    assert set(res.summary["tasks"]) == {"gsm8k", "mmlu"}


# ---------------------------------------------------------------------------
# Phrase: "when `--task` is present, require input only for selected tasks and
#          ignore unselected tasks for validation and execution"
# Context: Part 2 / CLI Changes.  "Input files for unselected tasks are not
# required."
# ---------------------------------------------------------------------------
def test_unselected_tasks_need_no_input(run_tool, write_config, write_input,
                                        workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out,
                       extra=["--task", "gsm8k"])
    assert res.returncode == 0, res


# Context: same phrase - an unselected task is not validated, so its broken
# config does not stop the selected task from running.
def test_unselected_task_config_is_not_validated(run_tool, write_config,
                                                 write_input, workdir):
    broken = copy.deepcopy(MMLU_TASK)
    broken.pop("prompt")
    with MockAPI(_responder) as api:
        cfg = write_config(multi_config(api.url, {
            "gsm8k": copy.deepcopy(GSM8K_TASK), "mmlu": broken}))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out,
                       extra=["--task", "gsm8k"])
    assert res.returncode == 0, res
    assert len(res.rows_for("gsm8k")) == 1


# Context: same phrase - under `--input-dir`, only the selected task's file
# must exist.
def test_input_dir_with_task_selection(run_tool, write_config, write_input,
                                       workdir):
    data_dir = workdir / "data"
    data_dir.mkdir()
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        write_input([MATH_ROW], name="data/gsm8k.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, None, output=out,
                       extra=["--input-dir", str(data_dir),
                              "--task", "gsm8k"])
    assert res.returncode == 0, res
    assert len(res.rows_for("gsm8k")) == 1


# Context: same phrase - a mapping supplied for an unselected task is ignored
# rather than run (AMBIGUITIES T31).
def test_mapping_for_unselected_task_is_ignored(run_tool, write_config,
                                                write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out,
                       extra=["--task", "gsm8k"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1
    assert list(res.summary["tasks"]) == ["gsm8k"]


# Context: same phrase - an unknown `--task` name is an error
# (AMBIGUITIES T37).
def test_unknown_task_name_exits_1(run_tool, write_config, write_input,
                                   workdir):
    cfg = write_config(_two_task_cfg("http://127.0.0.1:1"))
    math = write_input([MATH_ROW], name="math.jsonl")
    res = run_tool(cfg, [f"gsm8k={math}"], output=str(workdir / "results"),
                   extra=["--task", "nope"])
    assert res.returncode == 1
    assert "nope" in res.stderr


# ---------------------------------------------------------------------------
# Phrase: "`--eval-model <string>`: override the judge model for all selected
#          `llm_judge` tasks"
# Context: Part 2 / CLI Changes.
# ---------------------------------------------------------------------------
def test_eval_model_overrides_the_judge_model(run_tool, write_config,
                                              write_input, workdir):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(multi_config(api.url,
                                        {"review": copy.deepcopy(JUDGE_TASK)}))
        data = write_input([{"prompt_text": "p", "criteria": "c"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review={data}"], output=out,
                       extra=["--eval-model", "judge-9000"])
        models = {}
        for req in api.requests:
            system = req["messages"][0]["content"]
            key = "judge" if "evaluator" in system.lower() else "gen"
            models[key] = req["model"]
    assert res.returncode == 0, res
    assert models["gen"] == "gpt-4"
    assert models["judge"] == "judge-9000"


# Context: same phrase - it wins over an explicit `evaluation.model`.
def test_eval_model_wins_over_evaluation_model(run_tool, write_config,
                                               write_input, workdir):
    task = copy.deepcopy(JUDGE_TASK)
    task["evaluation"]["model"] = "configured-judge"
    with MockAPI(judge_responder()) as api:
        cfg = write_config(multi_config(api.url, {"review": task}))
        data = write_input([{"prompt_text": "p", "criteria": "c"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review={data}"], output=out,
                       extra=["--eval-model", "cli-judge"])
        judge_models = [r["model"] for r in api.requests
                        if "evaluator" in r["messages"][0]["content"].lower()]
    assert res.returncode == 0, res
    assert judge_models == ["cli-judge"]


# Context: same phrase - it applies to every selected llm_judge task.
def test_eval_model_applies_to_all_selected_judge_tasks(run_tool, write_config,
                                                        write_input, workdir):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(multi_config(api.url, {
            "review_a": copy.deepcopy(JUDGE_TASK),
            "review_b": copy.deepcopy(JUDGE_TASK),
        }))
        a = write_input([{"prompt_text": "p", "criteria": "c"}], name="a.jsonl")
        b = write_input([{"prompt_text": "p2", "criteria": "c"}],
                        name="b.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review_a={a}", f"review_b={b}"], output=out,
                       extra=["--eval-model", "cli-judge"])
        judge_models = {r["model"] for r in api.requests
                        if "evaluator" in r["messages"][0]["content"].lower()}
    assert res.returncode == 0, res
    assert judge_models == {"cli-judge"}


# Context: same phrase - a no-op when nothing selected is an llm_judge task
# (AMBIGUITIES T36).
def test_eval_model_is_a_noop_without_judge_tasks(run_tool, write_config,
                                                  write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(multi_config(api.url,
                                        {"gsm8k": copy.deepcopy(GSM8K_TASK)}))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out,
                       extra=["--eval-model", "judge-9000"])
        models = {r["model"] for r in api.requests}
    assert res.returncode == 0, res
    assert models == {"gpt-4"}


# ---------------------------------------------------------------------------
# Phrase: "for multi-task configs, `--output` must be a directory" /
#         "write `<output_dir>/<task_name>.jsonl`"
# Context: Part 2 / CLI Changes (AMBIGUITIES T32).
# ---------------------------------------------------------------------------
def test_output_directory_is_created(run_tool, write_config, write_input,
                                     workdir):
    out = workdir / "nested" / "results"
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=str(out))
    assert res.returncode == 0, res
    assert (out / "gsm8k.jsonl").exists()
    assert (out / "mmlu.jsonl").exists()


def test_output_path_that_is_a_file_exits_1(run_tool, write_config,
                                            write_input, workdir):
    out = workdir / "results"
    out.write_text("not a directory\n")
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=str(out))
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "when `--task` is present, write output files only for the tasks
#          that ran"
# Context: Part 2 / CLI Changes.
# ---------------------------------------------------------------------------
def test_only_selected_tasks_get_output_files(run_tool, write_config,
                                              write_input, workdir):
    out = workdir / "results"
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        res = run_tool(cfg, [f"gsm8k={math}"], output=str(out),
                       extra=["--task", "gsm8k"])
    assert res.returncode == 0, res
    assert (out / "gsm8k.jsonl").exists()
    assert not (out / "mmlu.jsonl").exists()


# ---------------------------------------------------------------------------
# Phrase: "for single-task configs, `--input <path>` without `=` still behaves
#          as in Part 1" / "`--output <path>` still writes a single file"
# Context: Part 2 / CLI Changes.
# ---------------------------------------------------------------------------
def test_single_task_config_keeps_part1_cli(run_tool, write_config,
                                            write_input, workdir):
    out = workdir / "out.jsonl"
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([MATH_ROW])
        res = run_tool(cfg, data, output=str(out))
    assert res.returncode == 0, res
    assert out.is_file()
    assert len(res.rows) == 1


# Context: same phrase - a single-task config accepts `<name>=<path>` when the
# name matches `task.name` (AMBIGUITIES T40).
def test_single_task_config_accepts_matching_mapping(run_tool, write_config,
                                                     write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(api.url, name="gsm8k_solve"))
        data = write_input([MATH_ROW])
        res = run_tool(cfg, f"gsm8k_solve={data}")
    assert res.returncode == 0, res
    assert len(res.rows) == 1


# Context: same phrase - two `--input` flags make no sense for a single task.
def test_single_task_config_rejects_two_inputs(run_tool, write_config,
                                               write_input, workdir):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    a = write_input([MATH_ROW], name="a.jsonl")
    b = write_input([MATH_ROW], name="b.jsonl")
    res = run_tool(cfg, [a, b])
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "Optional overrides replace the corresponding config values" (Part 1)
#         applied to a multi-task config
# Context: Part 2 / CLI Changes (AMBIGUITIES T35).
# ---------------------------------------------------------------------------
def test_part1_overrides_apply_to_every_task(run_tool, write_config,
                                             write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg("http://127.0.0.1:1"))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out,
                       extra=["--api-url", api.url, "--model", "llama-3"])
        models = {r["model"] for r in api.requests}
    assert res.returncode == 0, res
    assert models == {"llama-3"}
