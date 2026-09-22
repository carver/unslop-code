"""Part 2 configuration: `defaults` + `tasks`, merging, and the Part 1 form."""

import json

import pytest
import yaml

import fake_api


# ---------------------------------------------------------------------------
# Spec: "Extend Part 1 to support multiple named tasks in one config file."
# Context: Configuration.  A config with two tasks runs both of them.
# ---------------------------------------------------------------------------
def test_two_named_tasks_in_one_config_both_run(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, check=0)
    assert set(res.summary["tasks"]) == {"gsm8k", "mmlu"}
    assert res.task_output_exists("gsm8k")
    assert res.task_output_exists("mmlu")


# ---------------------------------------------------------------------------
# Spec: "Each task has its own prompt, ... and output field."
# Context: Configuration.  Each task's own prompt is sent and its own
# output_field wraps its own response.
# ---------------------------------------------------------------------------
def test_each_task_uses_its_own_prompt_and_output_field(run_multi):
    with fake_api.FakeAPI(fake_api.echo_user()) as api:
        res = run_multi(api, inputs={
            "gsm8k": [{"question": "2+3?", "answer": "5"}],
            "mmlu": [{"question": "capital?", "answer": "B"}],
        }, check=0)
    assert res.task_rows("gsm8k")[0]["output"] == {"solution": "2+3?"}
    assert res.task_rows("mmlu")[0]["output"] == {"choice": "capital?"}


# ---------------------------------------------------------------------------
# Spec: "Each task has its own ... generation settings"
# Context: Configuration.  A per-task `generation` block is used for that
# task's requests only.
# ---------------------------------------------------------------------------
def test_each_task_uses_its_own_generation_settings(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, tasks={
            "gsm8k": {"generation": {"scheme": "sample", "temperature": 0.7}},
            "mmlu": {"generation": {"scheme": "greedy"}},
        }, check=0)
    temps = sorted(b["temperature"] for b in api.bodies())
    assert temps == [0.0, 0.7]
    assert res.summary["total"] == 2


# ---------------------------------------------------------------------------
# Spec: "Each task has its own ... evaluation"
# Context: Configuration.  One task can pass while the other fails, using its
# own extract method.
# ---------------------------------------------------------------------------
def test_each_task_uses_its_own_evaluation(run_multi):
    with fake_api.FakeAPI(fake_api.always("The answer is B) Paris")) as api:
        res = run_multi(api, inputs={
            "gsm8k": [{"question": "q", "answer": "5"}],
            "mmlu": [{"question": "q2", "answer": "B"}],
        }, check=0)
    # gsm8k extracts last_number (none present) and fails; mmlu extracts "B".
    assert res.task_rows("gsm8k")[0]["result"]["passed"] is False
    assert res.task_rows("mmlu")[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "`defaults` provides shared values"
# Context: Configuration rules.  A value present only in `defaults` is used by
# every task.
# ---------------------------------------------------------------------------
def test_defaults_supply_shared_values_to_every_task(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"model": "shared-model"}, check=0)
    assert {b["model"] for b in api.bodies()} == {"shared-model"}


# ---------------------------------------------------------------------------
# Spec: "each task overrides `defaults`"
# Context: Configuration rules.  A task-level scalar wins over `defaults`.
# ---------------------------------------------------------------------------
def test_task_value_overrides_defaults(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"model": "shared-model"},
                        tasks={"mmlu": {"model": "own-model"}}, check=0)
    models = sorted(b["model"] for b in api.bodies())
    assert models == ["own-model", "shared-model"]


# ---------------------------------------------------------------------------
# Spec: "nested sections such as `prompt`, `generation`, and `evaluation` are
#        merged per task using the Part 1 structure"
# Context: Configuration rules.  A task that sets only `generation.scheme`
# keeps `generation.max_tokens` from `defaults` (merge, not replace).
# ---------------------------------------------------------------------------
def test_nested_generation_section_is_merged_not_replaced(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"generation": {"max_tokens": 77}},
                        tasks={"gsm8k": {"generation": {"scheme": "greedy"}}},
                        check=0)
    assert {b["max_tokens"] for b in api.bodies()} == {77}


# ---------------------------------------------------------------------------
# Spec: "nested sections such as `prompt` ... are merged per task"
# Context: Configuration rules.  A shared `prompt.system` in `defaults` plus a
# per-task `prompt.user` merge into one prompt.
# ---------------------------------------------------------------------------
def test_nested_prompt_section_is_merged(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api,
                        defaults={"prompt": {"system": "SHARED SYSTEM"}},
                        tasks={"gsm8k": {"prompt": {"system": None,
                                                    "user": "{question}"}},
                               "mmlu": {"prompt": {"system": None,
                                                   "user": "{question}"}}},
                        check=0)
    assert {r.system_content for r in api.requests} == {"SHARED SYSTEM"}


# ---------------------------------------------------------------------------
# Spec: "nested sections such as ... `evaluation` are merged per task"
# Context: Configuration rules.  `evaluation.answer_field` from `defaults`
# combines with a per-task `evaluation.extract`.
# ---------------------------------------------------------------------------
def test_nested_evaluation_section_is_merged(run_multi):
    with fake_api.FakeAPI(fake_api.always("value is 42")) as api:
        res = run_multi(api,
                        defaults={"evaluation": {"type": "exact_match",
                                                 "answer_field": "answer"}},
                        tasks={"gsm8k": {"evaluation": {"extract":
                                                        "last_number"}},
                               "mmlu": {"evaluation": {"extract":
                                                       "last_number"}}},
                        inputs={"gsm8k": [{"question": "q", "answer": "42"}],
                                "mmlu": [{"question": "q", "answer": "42"}]},
                        check=0)
    assert res.task_rows("gsm8k")[0]["result"]["passed"] is True
    assert res.task_rows("mmlu")[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "required Part 1 fields must still come from either `defaults` or the
#        task"
# Context: Configuration rules.  `model` given only in `defaults` is enough.
# ---------------------------------------------------------------------------
def test_required_field_may_come_from_defaults_alone(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, check=0)
    assert res.summary["total"] == 2


# ---------------------------------------------------------------------------
# Spec: "required Part 1 fields must still come from either `defaults` or the
#        task"
# Context: Configuration rules.  Supplying it only on the task is also enough.
# ---------------------------------------------------------------------------
def test_required_field_may_come_from_the_task_alone(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"model": None},
                        tasks={"gsm8k": {"model": "m1"},
                               "mmlu": {"model": "m2"}}, check=0)
    assert sorted(b["model"] for b in api.bodies()) == ["m1", "m2"]


# ---------------------------------------------------------------------------
# Spec: "required Part 1 fields must still come from either `defaults` or the
#        task"
# Context: Configuration rules.  A field in neither is a config error (exit 1).
# ---------------------------------------------------------------------------
def test_required_field_missing_from_both_is_an_error(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"model": None}, check=None)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "required Part 1 fields must still come from either `defaults` or the
#        task"
# Context: Configuration rules.  `prompt.user` is required per task.
# ---------------------------------------------------------------------------
def test_missing_prompt_user_in_a_task_is_an_error(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, tasks={"mmlu": {"prompt": {"user": None}}},
                        check=None)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "if the config still uses a top-level `task` key, treat it as the
#        Part 1 single-task format"
# Context: Configuration rules.  Part 1 configs keep working unchanged.
# ---------------------------------------------------------------------------
def test_top_level_task_key_is_the_part1_single_task_format(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    assert res.rows[0]["result"]["passed"] is True
    assert res.rows[0]["output"] == {"solution": "#### 5"}


# ---------------------------------------------------------------------------
# Spec: "if the config still uses a top-level `task` key ... the task name is
#        `task.name`"
# Context: Configuration rules.  AMBIGUITIES T43 — the single task still
# appears in the summary's `tasks` object, keyed by `task.name`.
# ---------------------------------------------------------------------------
def test_single_task_config_is_named_by_task_name(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, {"name": "my_task"}, check=0)
    assert list(res.summary["tasks"]) == ["my_task"]


# ---------------------------------------------------------------------------
# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Configuration.  AMBIGUITIES T25 — `defaults` may be omitted when
# every task is self-contained.
# ---------------------------------------------------------------------------
def test_tasks_mapping_without_defaults(run_cli, write_input, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = workdir / "multi.yaml"
        cfg.write_text(yaml.safe_dump({"tasks": {"solo": {
            "api_url": api.url, "model": "gpt-4",
            "prompt": {"user": "{question}"},
            "generation": {"scheme": "greedy"},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "out",
        }}}))
        inp = write_input([{"question": "q", "answer": "5"}])
        out = str(workdir / "results")
        res = run_cli("run", "--config", str(cfg), "--input", "solo=%s" % inp,
                      "--output", out, output=out, check=0)
    assert res.task_rows("solo")[0]["output"] == {"out": "#### 5"}


# ---------------------------------------------------------------------------
# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Configuration.  A config with neither `task` nor `tasks` is a
# configuration error.
# ---------------------------------------------------------------------------
def test_config_without_task_or_tasks_is_an_error(run_cli, write_input,
                                                  workdir):
    cfg = workdir / "bad.yaml"
    cfg.write_text(yaml.safe_dump({"defaults": {"model": "gpt-4"}}))
    inp = write_input([{"question": "q", "answer": "5"}])
    res = run_cli("run", "--config", str(cfg), "--input", inp)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "if the config still uses a top-level `task` key, treat it as the
#        Part 1 single-task format"
# Context: Configuration rules.  AMBIGUITIES T26 — a config with both keys is
# read as the Part 1 format; `tasks` is ignored.
# ---------------------------------------------------------------------------
def test_top_level_task_key_wins_over_tasks(run_cli, write_input, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = workdir / "both.yaml"
        cfg.write_text(yaml.safe_dump({
            "task": {"name": "single", "api_url": api.url, "model": "gpt-4",
                     "prompt": {"user": "{question}"},
                     "generation": {"scheme": "greedy"},
                     "evaluation": {"type": "exact_match",
                                    "answer_field": "answer",
                                    "extract": "last_number"},
                     "output_field": "solution"},
            "tasks": {"ignored": {"prompt": {"user": "{question}"}}},
        }))
        inp = write_input([{"question": "q", "answer": "5"}])
        out = str(workdir / "out.jsonl")
        res = run_cli("run", "--config", str(cfg), "--input", inp,
                      "--output", out, output=out, check=0)
    assert list(res.summary["tasks"]) == ["single"]
