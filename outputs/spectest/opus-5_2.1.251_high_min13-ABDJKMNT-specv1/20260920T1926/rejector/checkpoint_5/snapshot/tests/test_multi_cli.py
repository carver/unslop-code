"""CLI changes: `--task`, `--eval-model`, input modes and output directories."""

from __future__ import annotations

import json

from conftest import base_defaults, base_task, choice_task, judge_task, math_task, task_rows
from fake_api import FakeAPI, Reply, always, by_system

MATH_ROW = {"question": "2 + 3?", "answer": "5"}
CHOICE_ROW = {"question": "capital?", "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B"}


def two_task_document(api_url: str) -> dict:
    return {
        "defaults": base_defaults(api_url),
        "tasks": {"gsm8k": math_task(), "mmlu": choice_task()},
    }


# Spec: "python rejector.py run --config multi.yaml --input gsm8k=math.jsonl
# --input mmlu=qa.jsonl --output results/"
# Context: CLI Changes / explicit mapping mode.
def test_explicit_mapping_mode(write_yaml, write_input, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        math = write_input([MATH_ROW], "math.jsonl")
        qa = write_input([CHOICE_ROW], "qa.jsonl")
        result = run_args(
            "run", "--config", str(config),
            "--input", f"gsm8k={math}", "--input", f"mmlu={qa}",
            "--output", str(workdir / "results"),
        )
    assert result.returncode == 0
    assert len(task_rows(result, "gsm8k")) == 1
    assert len(task_rows(result, "mmlu")) == 1


# Spec: "python rejector.py run --config multi.yaml --input-dir data/
# --output results/" and "`--input-dir` looks for `<task_name>.jsonl`"
# Context: CLI Changes / directory mode.
def test_directory_mode_reads_task_named_files(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW, MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    assert result.returncode == 0
    assert len(task_rows(result, "gsm8k")) == 2
    assert len(task_rows(result, "mmlu")) == 1


# Spec: "for multi-task configs, explicit `--input <task=path>` and
# `--input-dir` are alternative modes; do not combine them"
# Context: CLI Changes / Rules.
def test_combining_input_modes_is_an_error(write_yaml, write_input, write_inputs, run_args, workdir):
    config = write_yaml(two_task_document("http://127.0.0.1:1"))
    math = write_input([MATH_ROW], "math.jsonl")
    data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
    result = run_args(
        "run", "--config", str(config), "--input", f"gsm8k={math}",
        "--input-dir", str(data), "--output", str(workdir / "results"),
    )
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "`--input-dir` looks for `<task_name>.jsonl`"
# Context: CLI Changes / Rules; a missing file for a selected task is an error.
def test_directory_mode_missing_file_is_an_error(write_yaml, write_inputs, run_args, workdir):
    config = write_yaml(two_task_document("http://127.0.0.1:1"))
    data = write_inputs({"gsm8k": [MATH_ROW]})
    result = run_args(
        "run", "--config", str(config), "--input-dir", str(data),
        "--output", str(workdir / "results"),
    )
    assert result.returncode == 1
    assert "mmlu" in result.stderr


# Spec: "for multi-task configs ... input is required for every task"
# Context: CLI Changes / Rules; an unmapped task in explicit mode is an error.
def test_explicit_mapping_must_cover_every_task(write_yaml, write_input, run_args, workdir):
    config = write_yaml(two_task_document("http://127.0.0.1:1"))
    math = write_input([MATH_ROW], "math.jsonl")
    result = run_args(
        "run", "--config", str(config), "--input", f"gsm8k={math}",
        "--output", str(workdir / "results"),
    )
    assert result.returncode == 1
    assert "mmlu" in result.stderr


# Spec: "`--task <name>`: repeatable; run only the selected task or tasks"
# Context: CLI Changes / New flags.
def test_task_flag_runs_only_the_selected_task(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"), "--task", "gsm8k",
        )
        assert api.call_count == 1
    assert list(result.summary["tasks"]) == ["gsm8k"]
    assert result.summary["tasks"]["gsm8k"]["total"] == 1


# Spec: "`--task <name>`: repeatable"
# Context: CLI Changes / New flags.
def test_task_flag_is_repeatable(write_yaml, write_inputs, run_args, workdir):
    document = two_task_document("placeholder")
    document["tasks"]["extra"] = math_task()
    with FakeAPI(responder=always("#### 5 B")) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW], "extra": [MATH_ROW]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"), "--task", "gsm8k", "--task", "mmlu",
        )
    assert sorted(result.summary["tasks"]) == ["gsm8k", "mmlu"]


# Spec: "when `--task` is present, require input only for selected tasks and
# ignore unselected tasks for validation and execution"
# Context: CLI Changes / Rules; "Input files for unselected tasks are not
# required." (Examples / Selected-task run)
def test_unselected_tasks_need_no_input(write_yaml, write_input, run_args, workdir):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_yaml(two_task_document(api.url))
        math = write_input([MATH_ROW], "math.jsonl")
        result = run_args(
            "run", "--config", str(config), "--input", f"gsm8k={math}",
            "--output", str(workdir / "results"), "--task", "gsm8k",
        )
    assert result.returncode == 0
    assert list(result.summary["tasks"]) == ["gsm8k"]


# Spec: "when `--task` is present, write output files only for the tasks that
# ran"
# Context: CLI Changes / Output handling.
def test_only_selected_tasks_get_output_files(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"), "--task", "gsm8k",
        )
    assert [path.name for path in result.output_path.iterdir()] == ["gsm8k.jsonl"]


# Spec: "for multi-task configs, `--output` must be a directory" and "write
# `<output_dir>/<task_name>.jsonl`"
# Context: CLI Changes / Output handling.
def test_output_directory_holds_one_file_per_task(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    assert result.output_path.is_dir()
    assert sorted(path.name for path in result.output_path.iterdir()) == [
        "gsm8k.jsonl",
        "mmlu.jsonl",
    ]


# Spec: "for multi-task configs, `--output` must be a directory"
# Context: CLI Changes / Output handling; see AMBIGUITIES T30.
def test_output_pointing_at_a_file_is_an_error(write_yaml, write_inputs, run_args, workdir):
    config = write_yaml(two_task_document("http://127.0.0.1:1"))
    data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
    existing = workdir / "results"
    existing.write_text("not a directory\n")
    result = run_args(
        "run", "--config", str(config), "--input-dir", str(data), "--output", str(existing)
    )
    assert result.returncode == 1


# Spec: "for single-task configs, `--input <path>` without `=` still behaves as
# in Part 1"
# Context: CLI Changes / Rules.
def test_single_task_config_keeps_plain_input(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([MATH_ROW])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: "for single-task configs, `--output <path>` still writes a single file"
# Context: CLI Changes / Output handling.
def test_single_task_config_writes_one_file(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([MATH_ROW, MATH_ROW])
        result = run_cli(config, data)
    assert result.output_path.is_file()
    assert len(result.rows) == 2


# Spec: "for single-task configs, the stdout summary keeps its previous keys
# and has no `tasks` object"
# Context: CLI Changes / Output handling.
def test_single_task_summary_has_no_tasks_object(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([MATH_ROW])
        result = run_cli(config, data)
    summary = result.summary
    assert "tasks" not in summary
    assert set(summary) == {
        "total",
        "passed",
        "failed",
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_api_calls",
        "elapsed_seconds",
        "throughput_rpm",
    }


# Spec: "`--eval-model <string>`: override the judge model for all selected
# `llm_judge` tasks"
# Context: CLI Changes / New flags.
def test_eval_model_overrides_the_judge_model(write_yaml, write_inputs, run_args, workdir):
    document = {"defaults": base_defaults("placeholder"), "tasks": {"review": judge_task()}}
    responder = by_system(
        {
            "You are a writing assistant.": Reply(content="a poem"),
            "You are a quality evaluator.": Reply(content="8"),
        }
    )
    with FakeAPI(responder=responder) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs({"review": [{"prompt_text": "p", "criteria": "clarity"}]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"), "--eval-model", "cheap-judge",
        )
        models = {
            request["messages"][0]["content"]: request["model"] for request in api.requests
        }
    assert result.returncode == 0
    assert models["You are a quality evaluator."] == "cheap-judge"
    assert models["You are a writing assistant."] == "gpt-4"


# Spec: "`--task <name>`: repeatable; run only the selected task or tasks"
# Context: CLI Changes; a name the config does not define is a config error.
def test_unknown_task_name_is_an_error(write_yaml, write_inputs, run_args, workdir):
    config = write_yaml(two_task_document("http://127.0.0.1:1"))
    data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
    result = run_args(
        "run", "--config", str(config), "--input-dir", str(data),
        "--output", str(workdir / "results"), "--task", "nope",
    )
    assert result.returncode == 1
    assert "nope" in result.stderr


# Spec: "python rejector.py run --config multi.yaml --input gsm8k=math.jsonl
# --output results/ --task gsm8k" / "Only `gsm8k` runs."
# Context: Examples / Selected-task run.
def test_selected_task_run_example(write_yaml, write_input, run_args, workdir):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_yaml(two_task_document(api.url))
        math = write_input([MATH_ROW], "math.jsonl")
        result = run_args(
            "run", "--config", str(config), "--input", f"gsm8k={math}",
            "--output", str(workdir / "results"), "--task", "gsm8k",
        )
        assert api.call_count == 1
    assert [path.name for path in result.output_path.iterdir()] == ["gsm8k.jsonl"]
    assert json.loads(result.stdout)["tasks"]["gsm8k"]["total"] == 1


# Spec: Part 1 overrides still apply.
# Context: "Existing behavior from Part 1 is unchanged unless stated here."
def test_part_one_overrides_apply_to_every_task(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
        run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"), "--model", "gpt-4o-mini",
        )
        assert {request["model"] for request in api.requests} == {"gpt-4o-mini"}
