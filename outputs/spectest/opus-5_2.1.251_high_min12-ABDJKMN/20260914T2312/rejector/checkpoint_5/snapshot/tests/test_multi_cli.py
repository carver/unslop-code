"""Part 2 CLI: --task, --eval-model, input modes and output handling."""

import json
import os

import pytest

import fake_api


def _args(cfg, inputs=None, input_dir=None, out=None, tasks=(), extra=()):
    argv = ["run", "--config", cfg]
    for task, path in (inputs or {}).items():
        argv += ["--input", "%s=%s" % (task, path)]
    if input_dir is not None:
        argv += ["--input-dir", input_dir]
    for name in tasks:
        argv += ["--task", name]
    argv += ["--output", out]
    return argv + list(extra)


ROWS = {"gsm8k": [{"question": "2+3?", "answer": "5"}],
        "mmlu": [{"question": "capital?", "answer": "B"}]}


# ---------------------------------------------------------------------------
# Spec: "python rejector.py run --config multi.yaml --input gsm8k=math.jsonl
#        --input mmlu=qa.jsonl --output results/"
# Context: CLI Changes, explicit mapping mode.
# ---------------------------------------------------------------------------
def test_explicit_mapping_mode(run_cli, write_multi_config, write_inputs,
                               workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out), output=out, check=0)
    assert sorted(res.output_listing) == ["gsm8k.jsonl", "mmlu.jsonl"]


# ---------------------------------------------------------------------------
# Spec: "--input <task=path>"
# Context: CLI Changes.  The mapping really routes each file to its task.
# ---------------------------------------------------------------------------
def test_explicit_mapping_routes_each_file_to_its_task(run_cli,
                                                       write_multi_config,
                                                       write_inputs, workdir):
    rows = {"gsm8k": [{"question": "MATH ROW", "answer": "5"}],
            "mmlu": [{"question": "QA ROW", "answer": "B"}]}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(rows)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out), output=out, check=0)
    assert res.task_rows("gsm8k")[0]["input"]["question"] == "MATH ROW"
    assert res.task_rows("mmlu")[0]["input"]["question"] == "QA ROW"


# ---------------------------------------------------------------------------
# Spec: "python rejector.py run --config multi.yaml --input-dir data/
#        --output results/"
# Context: CLI Changes, directory mode.
# ---------------------------------------------------------------------------
def test_directory_mode(run_cli, write_multi_config, write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        write_inputs(ROWS, subdir="data")
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, input_dir=str(workdir / "data"), out=out),
                      output=out, check=0)
    assert sorted(res.output_listing) == ["gsm8k.jsonl", "mmlu.jsonl"]
    assert res.summary["total"] == 2


# ---------------------------------------------------------------------------
# Spec: "`--input-dir` looks for `<task_name>.jsonl`"
# Context: CLI Changes.  A directory missing a task's file is an error.
# ---------------------------------------------------------------------------
def test_directory_mode_requires_a_file_per_task(run_cli, write_multi_config,
                                                 write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        write_inputs({"gsm8k": ROWS["gsm8k"]}, subdir="data")
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, input_dir=str(workdir / "data"), out=out),
                      output=out)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "`--input-dir` looks for `<task_name>.jsonl`"
# Context: CLI Changes.  Files whose name is not a task name are ignored.
# ---------------------------------------------------------------------------
def test_directory_mode_ignores_unrelated_files(run_cli, write_multi_config,
                                                write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        write_inputs(dict(ROWS, other=[{"question": "x", "answer": "1"}]),
                     subdir="data")
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, input_dir=str(workdir / "data"), out=out),
                      output=out, check=0)
    assert sorted(res.output_listing) == ["gsm8k.jsonl", "mmlu.jsonl"]


# ---------------------------------------------------------------------------
# Spec: "for multi-task configs, explicit `--input <task=path>` and
#        `--input-dir` are alternative modes; do not combine them"
# Context: CLI Changes.  Combining them is a configuration error.
# ---------------------------------------------------------------------------
def test_combining_input_and_input_dir_is_an_error(run_cli,
                                                   write_multi_config,
                                                   write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        write_inputs(ROWS, subdir="data")
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths,
                             input_dir=str(workdir / "data"), out=out),
                      output=out)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "--input <task=path>" for every task of a multi-task config
# Context: CLI Changes.  With no --task, every task needs an input.
# ---------------------------------------------------------------------------
def test_missing_input_for_one_task_is_an_error(run_cli, write_multi_config,
                                                write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs({"gsm8k": ROWS["gsm8k"]})
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out), output=out)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "`--task <name>`: repeatable; run only the selected task or tasks"
# Context: CLI Changes.  One selected task: only it runs.
# ---------------------------------------------------------------------------
def test_task_flag_runs_only_the_selected_task(run_cli, write_multi_config,
                                               write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs({"gsm8k": ROWS["gsm8k"]})
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out, tasks=["gsm8k"]),
                      output=out, check=0)
    assert list(res.summary["tasks"]) == ["gsm8k"]
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "`--task <name>`: repeatable"
# Context: CLI Changes.  Two --task flags select two tasks.
# ---------------------------------------------------------------------------
def test_task_flag_is_repeatable(run_cli, write_multi_config, write_inputs,
                                 workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out,
                             tasks=["gsm8k", "mmlu"]), output=out, check=0)
    assert set(res.summary["tasks"]) == {"gsm8k", "mmlu"}


# ---------------------------------------------------------------------------
# Spec: "when `--task` is present, require input only for selected tasks and
#        ignore unselected tasks for validation and execution"
# Context: CLI Changes.  Example: "Only gsm8k runs. Input files for unselected
# tasks are not required."
# ---------------------------------------------------------------------------
def test_unselected_tasks_need_no_input(run_cli, write_multi_config,
                                        write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs({"gsm8k": ROWS["gsm8k"]})
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out, tasks=["gsm8k"]),
                      output=out, check=0)
    assert res.returncode == 0
    assert not res.task_output_exists("mmlu")


# ---------------------------------------------------------------------------
# Spec: "ignore unselected tasks for validation"
# Context: CLI Changes.  An unselected task with a broken config does not
# block the selected task.
# ---------------------------------------------------------------------------
def test_unselected_task_config_is_not_validated(run_cli, write_multi_config,
                                                 write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url},
                                 {"mmlu": {"prompt": {"user": None}}})
        paths = write_inputs({"gsm8k": ROWS["gsm8k"]})
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out, tasks=["gsm8k"]),
                      output=out, check=0)
    assert list(res.summary["tasks"]) == ["gsm8k"]


# ---------------------------------------------------------------------------
# Spec: "when `--task` is present, require input only for selected tasks"
# Context: CLI Changes.  Directory mode only needs the selected task's file.
# ---------------------------------------------------------------------------
def test_directory_mode_with_task_needs_only_the_selected_file(
        run_cli, write_multi_config, write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        write_inputs({"gsm8k": ROWS["gsm8k"]}, subdir="data")
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, input_dir=str(workdir / "data"), out=out,
                             tasks=["gsm8k"]), output=out, check=0)
    assert res.output_listing == ["gsm8k.jsonl"]


# ---------------------------------------------------------------------------
# Spec: "`--task <name>`: ... run only the selected task or tasks"
# Context: CLI Changes.  A name that is not a task in the config is an error.
# ---------------------------------------------------------------------------
def test_unknown_task_name_is_an_error(run_cli, write_multi_config,
                                       write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out, tasks=["nope"]),
                      output=out)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "--input gsm8k=math.jsonl"
# Context: CLI Changes.  An --input naming a task absent from the config is an
# error.
# ---------------------------------------------------------------------------
def test_input_for_an_unknown_task_is_an_error(run_cli, write_multi_config,
                                               write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        argv = _args(cfg, inputs=paths, out=out)
        argv += ["--input", "ghost=%s" % paths["gsm8k"]]
        res = run_cli(*argv, output=out)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "for single-task configs, `--input <path>` without `=` still behaves
#        as in Part 1"
# Context: CLI Changes.
# ---------------------------------------------------------------------------
def test_single_task_input_without_equals(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Spec: "for single-task configs, `--output <path>` still writes a single file"
# Context: CLI Changes, output handling.
# ---------------------------------------------------------------------------
def test_single_task_output_is_a_single_file(run_cli, write_config,
                                             write_input, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        inp = write_input([{"question": "q", "answer": "5"}])
        out = str(workdir / "out.jsonl")
        res = run_cli("run", "--config", cfg, "--input", inp, "--output", out,
                      output=out, check=0)
    assert os.path.isfile(out)
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Spec: "for multi-task configs, `--output` must be a directory"
# Context: CLI Changes, output handling.  An existing file at that path is an
# error rather than being overwritten.
# ---------------------------------------------------------------------------
def test_multi_output_pointing_at_a_file_is_an_error(run_cli,
                                                     write_multi_config,
                                                     write_inputs, workdir):
    out = workdir / "results.jsonl"
    out.write_text("")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        res = run_cli(*_args(cfg, inputs=paths, out=str(out)),
                      output=str(out))
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "write `<output_dir>/<task_name>.jsonl`"
# Context: CLI Changes, output handling.
# ---------------------------------------------------------------------------
def test_output_file_is_named_after_the_task(run_cli, write_multi_config,
                                             write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out), output=out, check=0)
    assert os.path.isfile(os.path.join(out, "gsm8k.jsonl"))
    assert os.path.isfile(os.path.join(out, "mmlu.jsonl"))
    assert len(res.task_rows("gsm8k")) == 1


# ---------------------------------------------------------------------------
# Spec: "for multi-task configs, `--output` must be a directory"
# Context: CLI Changes.  AMBIGUITIES T42 — a directory that does not exist yet
# is created.
# ---------------------------------------------------------------------------
def test_output_directory_is_created_when_missing(run_cli, write_multi_config,
                                                  write_inputs, workdir):
    out = str(workdir / "nested" / "results")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        res = run_cli(*_args(cfg, inputs=paths, out=out), output=out, check=0)
    assert sorted(res.output_listing) == ["gsm8k.jsonl", "mmlu.jsonl"]


# ---------------------------------------------------------------------------
# Spec: "when `--task` is present, write output files only for the tasks that
#        ran"
# Context: CLI Changes, output handling.
# ---------------------------------------------------------------------------
def test_only_selected_tasks_get_output_files(run_cli, write_multi_config,
                                              write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out, tasks=["mmlu"]),
                      output=out, check=0)
    assert res.output_listing == ["mmlu.jsonl"]


# ---------------------------------------------------------------------------
# Spec (Examples): "python rejector.py run --config multi.yaml --input
#        gsm8k=math.jsonl --output results/ --task gsm8k" -> "Only gsm8k runs."
# Context: Examples, selected-task run.
# ---------------------------------------------------------------------------
def test_selected_task_run_example(run_cli, write_multi_config, write_inputs,
                                   workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs({"gsm8k": ROWS["gsm8k"]})
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out, tasks=["gsm8k"]),
                      output=out, check=0)
        assert api.call_count == 1
    assert res.output_listing == ["gsm8k.jsonl"]
    assert list(res.summary["tasks"]) == ["gsm8k"]


# ---------------------------------------------------------------------------
# Spec: "`--eval-model <string>`: override the judge model for all selected
#        `llm_judge` tasks"
# Context: CLI Changes.
# ---------------------------------------------------------------------------
def test_eval_model_overrides_the_judge_model(run_task):
    task = {"prompt": {"user": "{prompt_text}", "system": None},
            "model": "task-model",
            "evaluation": {"type": "llm_judge", "answer_field": None,
                           "judge_prompt": {"user": "Rate: {__response__}"},
                           "threshold": 7, "extract": "first_number",
                           "model": "config-judge"},
            "output_field": "response"}

    def responder(rec):
        judge = (rec.user_content or "").startswith("Rate:")
        return 200, fake_api.completion("8" if judge else "a poem")

    with fake_api.FakeAPI(responder) as api:
        run_task(api, task, rows=[{"prompt_text": "p"}],
                 extra=["--eval-model", "cli-judge"], check=0)
        models = {(r.user_content or "").startswith("Rate:"): r.body["model"]
                  for r in api.requests}
    assert models == {False: "task-model", True: "cli-judge"}


# ---------------------------------------------------------------------------
# Spec: "override the judge model for all selected `llm_judge` tasks"
# Context: CLI Changes.  It applies to every selected judge task, and leaves
# the generation model alone.
# ---------------------------------------------------------------------------
def test_eval_model_applies_to_every_selected_judge_task(
        run_cli, write_multi_config, write_inputs, workdir):
    judge_eval = {"type": "llm_judge",
                  "judge_prompt": {"user": "Rate: {__response__}"},
                  "threshold": 7, "extract": "first_number"}
    tasks = {"r1": {"prompt": {"user": "{prompt_text}"},
                    "generation": {"scheme": "greedy"},
                    "evaluation": dict(judge_eval), "output_field": "response"},
             "r2": {"prompt": {"user": "{prompt_text}"},
                    "generation": {"scheme": "greedy"},
                    "evaluation": dict(judge_eval), "output_field": "response"}}

    def responder(rec):
        judge = (rec.user_content or "").startswith("Rate:")
        return 200, fake_api.completion("8" if judge else "a poem")

    with fake_api.FakeAPI(responder) as api:
        cfg = write_multi_config({"api_url": api.url, "model": "task-model"},
                                 tasks, replace_tasks=True)
        paths = write_inputs({"r1": [{"prompt_text": "p1"}],
                              "r2": [{"prompt_text": "p2"}]})
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out,
                             extra=["--eval-model", "cli-judge"]),
                      output=out, check=0)
        judge_models = [r.body["model"] for r in api.requests
                        if (r.user_content or "").startswith("Rate:")]
        gen_models = [r.body["model"] for r in api.requests
                      if not (r.user_content or "").startswith("Rate:")]
    assert judge_models == ["cli-judge", "cli-judge"]
    assert gen_models == ["task-model", "task-model"]


# ---------------------------------------------------------------------------
# Spec: "New flags: --task ... --eval-model"
# Context: CLI Changes.  AMBIGUITIES T40 — neither input mode given is an
# error, as in Part 1.
# ---------------------------------------------------------------------------
def test_no_input_flag_at_all_is_an_error(run_cli, write_multi_config,
                                          workdir):
    cfg = write_multi_config()
    out = str(workdir / "results")
    res = run_cli("run", "--config", cfg, "--output", out, output=out)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "Existing behavior from Part 1 is unchanged unless stated here."
# Context: CLI Changes.  Part 1's generation overrides still apply.
# ---------------------------------------------------------------------------
def test_part1_overrides_still_apply_to_multi_task_runs(
        run_cli, write_multi_config, write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs(ROWS)
        out = str(workdir / "results")
        res = run_cli(*_args(cfg, inputs=paths, out=out,
                             extra=["--model", "cli-model",
                                    "--max-tokens", "33"]),
                      output=out, check=0)
        assert {b["model"] for b in api.bodies()} == {"cli-model"}
        assert {b["max_tokens"] for b in api.bodies()} == {33}


# ---------------------------------------------------------------------------
# Spec: "for single-task configs, `--input <path>` without `=` still behaves
#        as in Part 1"
# Context: CLI Changes.  AMBIGUITIES T41 — `<task.name>=<path>` is also
# accepted for a single-task config.
# ---------------------------------------------------------------------------
def test_single_task_accepts_the_mapping_form(run_cli, write_config,
                                              write_input, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url, "name": "solo"})
        inp = write_input([{"question": "q", "answer": "5"}])
        out = str(workdir / "out.jsonl")
        res = run_cli("run", "--config", cfg, "--input", "solo=%s" % inp,
                      "--output", out, output=out, check=0)
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Spec: "Input handling for multi-task configs: ... directory mode"
# Context: CLI Changes.  AMBIGUITIES T40 — `--input-dir` is a multi-task mode;
# a single-task config still needs `--input`.
# ---------------------------------------------------------------------------
def test_input_dir_with_a_single_task_config_is_an_error(run_cli,
                                                         write_config,
                                                         write_inputs,
                                                         workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url, "name": "gsm8k"})
        write_inputs(ROWS, subdir="data")
        out = str(workdir / "out.jsonl")
        res = run_cli("run", "--config", cfg, "--input-dir",
                      str(workdir / "data"), "--output", out, output=out)
    assert res.returncode == 1
