"""CLI surface for multi-task configs: input modes, `--task`, `--eval-model`."""

from __future__ import annotations

from conftest import exact_match_task, make_config, make_multi_config

GSM8K = [{"question": "2+3?", "answer": "42"}]
MMLU = [{"question": "capital?", "answer": "42"}]


def two_task_config(server_url) -> dict:
    return make_multi_config(
        server_url,
        {"gsm8k": exact_match_task(), "mmlu": exact_match_task(output_field="choice")},
    )


def judge_task(**overrides) -> dict:
    task = {
        "prompt": {"system": "Write a response.", "user": "{prompt_text}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {
                "system": "You are a quality evaluator.",
                "user": "Rate:\n{__response__}\n\nCriteria: {criteria}\n\nScore:",
            },
            "threshold": 7,
            "extract": "first_number",
        },
        "output_field": "response",
    }
    task.update(overrides)
    return task


# Spec: explicit mapping mode -- "--input gsm8k=math.jsonl --input mmlu=qa.jsonl
# --output results/".
def test_explicit_mapping_mode_runs_every_task(server, run_multi):
    result = run_multi(two_task_config(server.url), {"gsm8k": GSM8K, "mmlu": MMLU})
    assert result.exit_code == 0, result.stderr
    assert result.written_tasks() == {"gsm8k", "mmlu"}


# Spec: directory mode -- "--input-dir data/" looks for `<task_name>.jsonl`.
def test_directory_mode_reads_task_named_files(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": GSM8K, "mmlu": MMLU}, mode="dir"
    )
    assert result.exit_code == 0, result.stderr
    assert result.rows("gsm8k")[0]["input"] == GSM8K[0]
    assert result.rows("mmlu")[0]["input"] == MMLU[0]


# Spec: "--input-dir looks for <task_name>.jsonl" -- a task without its file
# cannot run.
def test_directory_mode_missing_file_exits_1(server, run_multi):
    result = run_multi(two_task_config(server.url), {"gsm8k": GSM8K}, mode="dir")
    assert result.exit_code == 1
    assert "mmlu" in result.stderr


# Spec: "explicit `--input <task=path>` and `--input-dir` are alternative
# modes; do not combine them".
def test_combining_input_and_input_dir_exits_1(server, run_multi, tmp_path):
    result = run_multi(
        two_task_config(server.url),
        {"gsm8k": GSM8K, "mmlu": MMLU},
        "--input-dir",
        str(tmp_path / "data"),
    )
    assert result.exit_code == 1
    assert "--input-dir" in result.stderr


# Spec: a multi-task run needs one of the two input modes.
def test_no_input_source_exits_1(server, run_multi):
    result = run_multi(two_task_config(server.url), {})
    assert result.exit_code == 1
    assert "--input" in result.stderr


# Spec: explicit mapping mode -- every task that runs needs a mapping.
def test_missing_mapping_for_a_task_exits_1(server, run_multi):
    result = run_multi(two_task_config(server.url), {"gsm8k": GSM8K})
    assert result.exit_code == 1
    assert "mmlu" in result.stderr


# Spec: "--input <task=path>" naming a task the config does not define.
def test_input_for_unknown_task_exits_1(server, run_multi):
    result = run_multi(
        two_task_config(server.url),
        {"gsm8k": GSM8K, "mmlu": MMLU},
        "--input",
        "nope=/tmp/nope.jsonl",
    )
    assert result.exit_code == 1
    assert "nope" in result.stderr


# Spec: an input file that does not exist is an input error.
def test_missing_input_file_exits_1(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {}, "--input", "gsm8k=/no/such/file.jsonl"
    )
    assert result.exit_code == 1
    assert result.stderr.strip()


# Spec: "--task <name>: repeatable; run only the selected task or tasks" and
# "Only gsm8k runs. Input files for unselected tasks are not required."
def test_task_flag_selects_one_task(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": GSM8K}, "--task", "gsm8k"
    )
    assert result.exit_code == 0, result.stderr
    assert result.written_tasks() == {"gsm8k"}
    assert server.call_count == 1


# Spec: "--task <name>: repeatable".
def test_task_flag_is_repeatable(server, run_multi):
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(),
            "mmlu": exact_match_task(output_field="choice"),
            "extra": exact_match_task(output_field="extra"),
        },
    )
    result = run_multi(
        config,
        {"gsm8k": GSM8K, "mmlu": MMLU},
        "--task",
        "gsm8k",
        "--task",
        "mmlu",
    )
    assert result.exit_code == 0, result.stderr
    assert result.written_tasks() == {"gsm8k", "mmlu"}


# Spec: "when `--task` is present, require input only for selected tasks and
# ignore unselected tasks for validation and execution" -- directory mode only
# needs the selected task's file.
def test_directory_mode_with_task_flag_ignores_other_files(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": GSM8K}, "--task", "gsm8k", mode="dir"
    )
    assert result.exit_code == 0, result.stderr
    assert result.written_tasks() == {"gsm8k"}


# Spec: "--task <name>" naming a task the config does not define.
def test_unknown_task_name_exits_1(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": GSM8K}, "--task", "ghost"
    )
    assert result.exit_code == 1
    assert "ghost" in result.stderr


# Spec: "for multi-task configs, `--output` must be a directory".
def test_output_pointing_at_a_file_exits_1(server, run_multi, tmp_path):
    existing = tmp_path / "results.jsonl"
    existing.write_text("")
    result = run_multi(
        two_task_config(server.url), {"gsm8k": GSM8K, "mmlu": MMLU}, output=existing
    )
    assert result.exit_code == 1
    assert "directory" in result.stderr


# Spec: "write `<output_dir>/<task_name>.jsonl`".
def test_output_files_are_named_after_tasks(server, run_multi):
    result = run_multi(two_task_config(server.url), {"gsm8k": GSM8K, "mmlu": MMLU})
    assert result.path("gsm8k").exists()
    assert result.path("mmlu").exists()


# Spec: "when `--task` is present, write output files only for the tasks that
# ran".
def test_unselected_tasks_write_no_output(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": GSM8K}, "--task", "gsm8k"
    )
    assert not result.path("mmlu").exists()


# Spec: "for single-task configs, `--input <path>` without `=` still behaves as
# in Part 1" and "--output <path> still writes a single file".
def test_single_task_config_keeps_part_1_io(server, run_cli):
    result = run_cli(make_config(server.url), GSM8K)
    assert result.exit_code == 0
    assert result.output_path.is_file()
    assert len(result.rows) == 1


# Spec: "--eval-model <string>: override the judge model for all selected
# llm_judge tasks".
def test_eval_model_overrides_the_judge_model(servers, run_multi):
    server = servers(contents=["a response"], content_if_contains={"evaluator": "9"})
    config = make_multi_config(server.url, {"review": judge_task()})
    rows = [{"prompt_text": "write something", "criteria": "clarity"}]
    result = run_multi(config, {"review": rows}, "--eval-model", "judge-model")
    assert result.exit_code == 0, result.stderr
    models = [payload["model"] for payload in server.payloads]
    assert "judge-model" in models
    assert result.rows("review")[0]["meta"]["judge_meta"]["model"] == "judge-model"


# Spec: "--eval-model ... for all selected llm_judge tasks" -- the generation
# model is untouched, and non-judge tasks are unaffected. (T29)
def test_eval_model_leaves_generation_models_alone(servers, run_multi):
    server = servers(contents=["#### 42"], content_if_contains={"evaluator": "9"})
    config = make_multi_config(
        server.url, {"gsm8k": exact_match_task(), "review": judge_task()}
    )
    rows = {
        "gsm8k": GSM8K,
        "review": [{"prompt_text": "write something", "criteria": "clarity"}],
    }
    result = run_multi(config, rows, "--eval-model", "judge-model")
    assert result.exit_code == 0, result.stderr
    generation_models = [
        payload["model"]
        for payload in server.payloads
        if "evaluator" not in str(payload["messages"])
    ]
    assert set(generation_models) == {"gpt-4"}


# Spec: the Part 1 overrides still apply, now to every selected task. (T28)
def test_model_override_applies_to_every_task(server, run_multi):
    result = run_multi(
        two_task_config(server.url),
        {"gsm8k": GSM8K, "mmlu": MMLU},
        "--model",
        "o3-mini",
    )
    assert result.exit_code == 0, result.stderr
    assert {payload["model"] for payload in server.payloads} == {"o3-mini"}
