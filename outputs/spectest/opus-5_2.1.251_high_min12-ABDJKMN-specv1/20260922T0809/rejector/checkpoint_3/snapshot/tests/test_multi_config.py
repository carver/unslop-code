"""Spec section: Part 2 / Configuration (`defaults` + `tasks`, merging rules)."""
from __future__ import annotations

import copy
import json

import pytest

from conftest import (GSM8K_TASK, JUDGE_TASK, MMLU_TASK, SCRIPT_TASK,
                      base_config, multi_config)
from mock_server import MockAPI, always, completion


# ---------------------------------------------------------------------------
# Phrase: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Part 2 / Configuration.  The spec's own multi-task config must load
# and run both tasks, producing one output file per task.
# ---------------------------------------------------------------------------
def test_defaults_plus_tasks_config_runs_every_task(run_tool, write_config,
                                                    write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(multi_config(api.url, {
            "gsm8k": copy.deepcopy(GSM8K_TASK),
            "mmlu": copy.deepcopy(MMLU_TASK),
        }))
        math = write_input([{"question": "q", "answer": "8"}], name="math.jsonl")
        qa = write_input([{"question": "capital?", "a": "London", "b": "Paris",
                           "c": "Berlin", "d": "Madrid", "answer": "B"}],
                         name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    assert len(res.rows_for("gsm8k")) == 1
    assert len(res.rows_for("mmlu")) == 1


# ---------------------------------------------------------------------------
# Phrase: "`defaults` provides shared values; each task overrides `defaults`"
# Context: Part 2 / Configuration.  `api_url`/`model` live only in `defaults`
# and must reach every task.
# ---------------------------------------------------------------------------
def test_defaults_supply_shared_scalar_values(run_tool, write_config,
                                              write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(multi_config(api.url,
                                        {"gsm8k": copy.deepcopy(GSM8K_TASK)}))
        math = write_input([{"question": "q", "answer": "8"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["model"] == "gpt-4"


# Context: same phrase - a task-level scalar wins over the `defaults` value.
def test_task_scalar_overrides_defaults(run_tool, write_config, write_input,
                                        workdir):
    with MockAPI(always("#### 8")) as api:
        task = copy.deepcopy(GSM8K_TASK)
        task["model"] = "llama-3"
        cfg = write_config(multi_config(api.url, {"gsm8k": task}))
        math = write_input([{"question": "q", "answer": "8"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["model"] == "llama-3"
    assert res.rows_for("gsm8k")[0]["meta"]["model"] == "llama-3"


# ---------------------------------------------------------------------------
# Phrase: "nested sections such as `prompt`, `generation`, and `evaluation` are
#          merged per task using the Part 1 structure"
# Context: Part 2 / Configuration.  `defaults.generation.max_tokens` must
# survive a task that sets only `scheme`/`temperature`/`n` (AMBIGUITIES T20).
# ---------------------------------------------------------------------------
def test_generation_sections_merge_rather_than_replace(run_tool, write_config,
                                                       write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        task = copy.deepcopy(GSM8K_TASK)
        task["generation"] = {"scheme": "sample", "temperature": 0.7}
        cfg = write_config(multi_config(
            api.url, {"gsm8k": task},
            defaults={"generation": {"max_tokens": 777}}))
        math = write_input([{"question": "q", "answer": "8"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["max_tokens"] == 777
    assert sent["temperature"] == pytest.approx(0.7)


# Context: same phrase - a `prompt` section is merged key-by-key, so a task
# that supplies only `user` inherits `defaults.prompt.system`.
def test_prompt_section_merges_with_defaults(run_tool, write_config,
                                             write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        task = copy.deepcopy(GSM8K_TASK)
        task["prompt"] = {"user": "{question}"}
        cfg = write_config(multi_config(
            api.url, {"gsm8k": task},
            defaults={"prompt": {"system": "SHARED SYSTEM"}}))
        math = write_input([{"question": "q", "answer": "8"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out)
        sent = api.requests[0]
    assert res.returncode == 0, res
    roles = {m["role"]: m["content"] for m in sent["messages"]}
    assert roles["system"] == "SHARED SYSTEM"


# Context: same phrase - an `evaluation` section is merged, so a task can
# inherit `answer_field` from defaults and set only `extract`.
def test_evaluation_section_merges_with_defaults(run_tool, write_config,
                                                 write_input, workdir):
    with MockAPI(always("The answer is B) Paris")) as api:
        task = copy.deepcopy(MMLU_TASK)
        task["evaluation"] = {"extract": "letter"}
        cfg = write_config(multi_config(
            api.url, {"mmlu": task},
            defaults={"evaluation": {"type": "exact_match",
                                     "answer_field": "answer"}}))
        qa = write_input([{"question": "capital?", "a": "London", "b": "Paris",
                           "c": "Berlin", "d": "Madrid", "answer": "B"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    assert res.rows_for("mmlu")[0]["result"]["passed"] is True


# Context: same phrase - nested `judge_prompt` merges too (AMBIGUITIES T20).
def test_judge_prompt_merges_with_defaults(run_tool, write_config, write_input,
                                           workdir):
    from conftest import judge_responder
    with MockAPI(judge_responder()) as api:
        task = copy.deepcopy(JUDGE_TASK)
        task["evaluation"]["judge_prompt"] = {
            "user": "Rate this response:\n{__response__}\n\nScore:"}
        cfg = write_config(multi_config(
            api.url, {"review": task},
            defaults={"evaluation": {"judge_prompt": {
                "system": "You are a quality evaluator."}}}))
        data = write_input([{"prompt_text": "write a poem"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review={data}"], output=out)
        judge_req = [r for r in api.requests
                     if "Rate this" in r["messages"][-1]["content"]][0]
    assert res.returncode == 0, res
    roles = {m["role"]: m["content"] for m in judge_req["messages"]}
    assert roles["system"] == "You are a quality evaluator."


# ---------------------------------------------------------------------------
# Phrase: "required Part 1 fields must still come from either `defaults` or the
#          task"
# Context: Part 2 / Configuration.  `prompt.user` present only on the task and
# `api_url`/`model` present only in `defaults` is a complete config.
# ---------------------------------------------------------------------------
def test_required_fields_may_come_from_either_level(run_tool, write_config,
                                                    write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config({
            "defaults": {"api_url": api.url, "model": "gpt-4", "rpm": 600,
                         "output_field": "solution"},
            "tasks": {"gsm8k": {
                "prompt": {"user": "{question}"},
                "evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": "last_number"},
            }},
        })
        math = write_input([{"question": "q", "answer": "8"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out)
    assert res.returncode == 0, res
    assert "solution" in res.rows_for("gsm8k")[0]["output"]


# Context: same phrase - a required field missing from both levels exits 1.
def test_missing_required_field_in_both_levels_exits_1(run_tool, write_config,
                                                       write_input, workdir):
    task = copy.deepcopy(GSM8K_TASK)
    task.pop("prompt")
    cfg = write_config(multi_config("http://127.0.0.1:1", {"gsm8k": task}))
    math = write_input([{"question": "q", "answer": "8"}])
    res = run_tool(cfg, [f"gsm8k={math}"], output=str(workdir / "results"))
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - no `model` anywhere is a config error.
def test_missing_model_in_multi_config_exits_1(run_tool, write_config,
                                               write_input, workdir):
    cfg_dict = multi_config("http://127.0.0.1:1",
                            {"gsm8k": copy.deepcopy(GSM8K_TASK)})
    del cfg_dict["defaults"]["model"]
    cfg = write_config(cfg_dict)
    math = write_input([{"question": "q", "answer": "8"}])
    res = run_tool(cfg, [f"gsm8k={math}"], output=str(workdir / "results"))
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "if the config still uses a top-level `task` key, treat it as the
#          Part 1 single-task format; the task name is `task.name`"
# Context: Part 2 / Configuration.  Part 1 configs keep working untouched.
# ---------------------------------------------------------------------------
def test_top_level_task_key_is_single_task_format(run_tool, write_config,
                                                  write_input):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "8"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert len(res.rows) == 1
    assert "tasks" not in res.summary


# Context: same phrase - the single-task name comes from `task.name`, which is
# what `--task` and `--input-dir` key off (AMBIGUITIES T40).
def test_single_task_name_comes_from_task_name_key(run_tool, write_config,
                                                   write_input, workdir):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(api.url, name="gsm8k_solve"))
        data = write_input([{"question": "q", "answer": "8"}],
                           name="gsm8k_solve.jsonl")
        out = str(workdir / "single.jsonl")
        res = run_tool(cfg, None, output=out,
                       extra=["--input-dir", str(workdir)])
    assert res.returncode == 0, res
    assert len(res.rows) == 1


# Context: same phrase - a config carrying both `task` and `tasks` is read as
# the Part 1 single-task format (AMBIGUITIES T41).
def test_task_key_wins_over_tasks_key(run_tool, write_config, write_input):
    with MockAPI(always("#### 8")) as api:
        cfg_dict = base_config(api.url)
        cfg_dict["tasks"] = {"other": copy.deepcopy(MMLU_TASK)}
        cfg = write_config(cfg_dict)
        data = write_input([{"question": "q", "answer": "8"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert len(res.rows) == 1
    assert "tasks" not in res.summary


# ---------------------------------------------------------------------------
# Phrase: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Part 2 / Configuration.  A `tasks` mapping that is empty or not a
# mapping is a configuration error.
# ---------------------------------------------------------------------------
def test_empty_tasks_mapping_exits_1(run_tool, write_config, write_input,
                                     workdir):
    cfg = write_config({"defaults": {"api_url": "http://127.0.0.1:1",
                                     "model": "gpt-4"},
                        "tasks": {}})
    data = write_input([{"question": "q", "answer": "8"}])
    res = run_tool(cfg, [f"gsm8k={data}"], output=str(workdir / "results"))
    assert res.returncode == 1
    assert res.stderr.strip()


def test_tasks_not_a_mapping_exits_1(run_tool, write_config, write_input,
                                     workdir):
    cfg = write_config({"defaults": {"api_url": "http://127.0.0.1:1",
                                     "model": "gpt-4"},
                        "tasks": ["gsm8k"]})
    data = write_input([{"question": "q", "answer": "8"}])
    res = run_tool(cfg, [f"gsm8k={data}"], output=str(workdir / "results"))
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a config with neither `task` nor `tasks` exits 1.
def test_config_with_neither_task_nor_tasks_exits_1(run_tool, write_config,
                                                    write_input):
    cfg = write_config({"defaults": {"api_url": "http://127.0.0.1:1"}})
    data = write_input([{"question": "q", "answer": "8"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "Each task has its own prompt, generation settings, evaluation, and
#          output field."
# Context: Part 2 / opening paragraph.  Two tasks with different prompts,
# schemes, evaluations and output fields run side by side without bleeding.
# ---------------------------------------------------------------------------
def test_tasks_keep_independent_settings(run_tool, write_config, write_input,
                                         workdir):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        if "capital" in user:
            return 200, completion("The answer is B) Paris")
        return 200, completion("#### 8")

    with MockAPI(responder) as api:
        cfg = write_config(multi_config(api.url, {
            "gsm8k": copy.deepcopy(GSM8K_TASK),
            "mmlu": copy.deepcopy(MMLU_TASK),
        }))
        math = write_input([{"question": "5+3?", "answer": "8"}],
                           name="math.jsonl")
        qa = write_input([{"question": "capital?", "a": "London", "b": "Paris",
                           "c": "Berlin", "d": "Madrid", "answer": "B"}],
                         name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    gsm = res.rows_for("gsm8k")[0]
    mmlu = res.rows_for("mmlu")[0]
    assert gsm["output"] == {"solution": "#### 8"}
    assert gsm["result"]["extracted_answer"] == "8"
    assert mmlu["output"] == {"choice": "The answer is B) Paris"}
    assert mmlu["result"]["extracted_answer"] == "B"
