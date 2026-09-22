"""CLI surface for multi-task configs: input modes, task selection, outputs."""

from __future__ import annotations

import json

from tests.conftest import SPEC_ROWS, multi_config, task_config
from tests.fake_api import ok

GSM8K_ROW = SPEC_ROWS["gsm8k"]
MMLU_ROW = SPEC_ROWS["mmlu"]


def two_task_server(api):
    """A server answering the `gsm8k` and `mmlu` prompts with passing responses."""

    def responder(index, body):
        system = body["messages"][0]["content"]
        return ok("#### 5") if "math" in system else ok("The answer is B) Paris")

    return api(responder)


# "--input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/"
def test_explicit_mapping_mode_runs_every_mapped_task(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW], "mmlu": [MMLU_ROW]})
    assert run.returncode == 0, run.stderr
    assert run.task_rows("gsm8k")[0]["output"] == {"solution": "#### 5"}
    assert run.task_rows("mmlu")[0]["output"] == {"choice": "The answer is B) Paris"}


# "write `<output_dir>/<task_name>.jsonl`"
def test_output_directory_holds_one_file_per_task(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW], "mmlu": [MMLU_ROW]})
    assert sorted(path.name for path in run.output_path.iterdir()) == [
        "gsm8k.jsonl", "mmlu.jsonl",
    ]


# "for multi-task configs, `--output` must be a directory"
def test_output_pointing_at_an_existing_file_is_an_error(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", defaults={"api_url": server.url})
    taken = cli.tmp_path / "results"
    taken.write_text("not a directory\n")
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW]})
    assert run.returncode == 1
    assert run.stderr.strip()


# "--input-dir data/" - "looks for `<task_name>.jsonl`"
def test_input_dir_mode_finds_files_named_after_tasks(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    data = cli.tmp_path / "data"
    data.mkdir()
    (data / "gsm8k.jsonl").write_text(json.dumps(GSM8K_ROW) + "\n")
    (data / "mmlu.jsonl").write_text(json.dumps(MMLU_ROW) + "\n")
    run = cli.invoke(
        "--config", str(cli.write_config(config)),
        "--input-dir", str(data),
        "--output", str(cli.tmp_path / "out"),
        output=cli.tmp_path / "out",
    )
    assert run.returncode == 0, run.stderr
    assert len(run.task_rows("gsm8k")) == 1 and len(run.task_rows("mmlu")) == 1


# "--input-dir looks for `<task_name>.jsonl`" (a task with no file is an error)
def test_input_dir_missing_a_task_file_is_an_error(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    data = cli.tmp_path / "data"
    data.mkdir()
    (data / "gsm8k.jsonl").write_text(json.dumps(GSM8K_ROW) + "\n")
    run = cli.invoke(
        "--config", str(cli.write_config(config)),
        "--input-dir", str(data),
        "--output", str(cli.tmp_path / "out"),
        output=cli.tmp_path / "out",
    )
    assert run.returncode == 1
    assert "mmlu" in run.stderr


# "explicit `--input <task=path>` and `--input-dir` are alternative modes;
#  do not combine them"
def test_combining_input_modes_is_an_error(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", defaults={"api_url": server.url})
    data = cli.tmp_path / "data"
    data.mkdir()
    (data / "gsm8k.jsonl").write_text(json.dumps(GSM8K_ROW) + "\n")
    run = cli.invoke(
        "--config", str(cli.write_config(config)),
        "--input", f"gsm8k={data / 'gsm8k.jsonl'}",
        "--input-dir", str(data),
        "--output", str(cli.tmp_path / "out"),
        output=cli.tmp_path / "out",
    )
    assert run.returncode == 1
    assert run.stderr.strip()


# "for multi-task configs, explicit `--input <task=path>`" - a task with no
# input given and no `--task` selection is an error
def test_missing_input_for_a_configured_task_is_an_error(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW]})
    assert run.returncode == 1
    assert "mmlu" in run.stderr


# "--input <task=path>" naming a task the config does not define
def test_input_for_an_unknown_task_is_an_error(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW], "ghost": [GSM8K_ROW]})
    assert run.returncode == 1
    assert "ghost" in run.stderr


# "--task <name>: repeatable; run only the selected task or tasks"
# "Only `gsm8k` runs. Input files for unselected tasks are not required."
def test_task_selection_runs_only_the_selected_task(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW]}, "--task", "gsm8k")
    assert run.returncode == 0, run.stderr
    assert len(run.task_rows("gsm8k")) == 1
    assert list(run.summary["tasks"]) == ["gsm8k"]


# "when `--task` is present, write output files only for the tasks that ran"
def test_unselected_tasks_write_no_output_file(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW]}, "--task", "gsm8k")
    assert [path.name for path in run.output_path.iterdir()] == ["gsm8k.jsonl"]


# "--task <name>: repeatable"
def test_task_flag_is_repeatable(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", "review", defaults={"api_url": server.url})
    run = cli.run_multi(
        config, {"gsm8k": [GSM8K_ROW], "mmlu": [MMLU_ROW]},
        "--task", "gsm8k", "--task", "mmlu",
    )
    assert run.returncode == 0, run.stderr
    assert sorted(run.summary["tasks"]) == ["gsm8k", "mmlu"]


# "--task <name>" naming a task the config does not define
def test_unknown_selected_task_is_an_error(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW]}, "--task", "ghost")
    assert run.returncode == 1
    assert "ghost" in run.stderr


# "--input-dir" combined with "--task": only the selected task needs a file
def test_input_dir_only_requires_selected_tasks(cli, api):
    server = two_task_server(api)
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    data = cli.tmp_path / "data"
    data.mkdir()
    (data / "gsm8k.jsonl").write_text(json.dumps(GSM8K_ROW) + "\n")
    run = cli.invoke(
        "--config", str(cli.write_config(config)),
        "--input-dir", str(data),
        "--output", str(cli.tmp_path / "out"),
        "--task", "gsm8k",
        output=cli.tmp_path / "out",
    )
    assert run.returncode == 0, run.stderr
    assert [path.name for path in run.output_path.iterdir()] == ["gsm8k.jsonl"]


# "within each task's output file, row order must still match input order"
def test_row_order_matches_input_order_per_task(cli, api):
    def responder(index, body):
        return ok(f"#### {body['messages'][-1]['content']}")

    server = api(responder)
    config = multi_config("gsm8k", defaults={"api_url": server.url, "rpm": 600})
    config["tasks"]["gsm8k"]["generation"] = {"scheme": "greedy"}
    rows = [{"question": str(value), "answer": str(value)} for value in range(12)]
    run = cli.run_multi(config, {"gsm8k": rows})
    assert run.returncode == 0, run.stderr
    assert [row["input"]["question"] for row in run.task_rows("gsm8k")] == [
        str(value) for value in range(12)
    ]


# "for single-task configs, `--input <path>` without `=` still behaves as in Part 1"
# "for single-task configs, `--output <path>` still writes a single file"
def test_single_task_config_keeps_part_one_io(cli, static_api):
    server = static_api("2 + 3 = 5\n#### 5")
    run = cli.run(task_config(api_url=server.url), [GSM8K_ROW])
    assert run.returncode == 0, run.stderr
    assert run.output_path.is_file()
    assert len(run.rows) == 1


# "for single-task configs, the stdout summary keeps its previous keys and has
#  no `tasks` object"
def test_single_task_summary_has_no_tasks_object(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [GSM8K_ROW])
    assert "tasks" not in run.summary
    assert set(run.summary) == {
        "total", "passed", "failed", "total_prompt_tokens", "total_completion_tokens",
        "total_api_calls", "elapsed_seconds", "throughput_rpm",
    }


# "for single-task configs, `--input <path>` without `=` still behaves as in Part 1"
# (a `task=path` mapping is not meaningful for a single-task config)
def test_single_task_config_rejects_two_inputs(cli, static_api):
    server = static_api("#### 5")
    config_path = cli.write_config(task_config(api_url=server.url))
    input_path = cli.write_input([GSM8K_ROW])
    run = cli.invoke(
        "--config", str(config_path),
        "--input", str(input_path),
        "--input", str(input_path),
        "--output", str(cli.tmp_path / "results.jsonl"),
        output=cli.tmp_path / "results.jsonl",
    )
    assert run.returncode == 1
    assert run.stderr.strip()


# "If the model returns `\"The answer is B) Paris\"`, `letter` extracts `\"B\"`
#  and the row passes."
def test_mmlu_example_row_passes(cli, static_api):
    server = static_api("The answer is B) Paris")
    config = multi_config("mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"mmlu": [MMLU_ROW]})
    assert run.returncode == 0, run.stderr
    result = run.task_rows("mmlu")[0]["result"]
    assert result["extracted_answer"] == "B"
    assert result["passed"] is True
