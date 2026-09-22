"""CLI additions: `--task`, `--eval-model`, input modes, output directories."""

from __future__ import annotations

import copy

from fake_server import FakeAPIServer, Reply, completion, system_of
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config


def _answers(payload, index):
    return Reply(completion("#### 5" if "math" in system_of(payload) else "The answer is B) Paris"))


GSM8K_ROW = {"question": "What is 2 + 3?", "answer": "5"}
MMLU_ROW = {
    "question": "What is the capital of France?",
    "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid",
    "answer": "B",
}
BOTH_TASKS = {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK}


# Spec: "explicit mapping mode: --input gsm8k=math.jsonl --input mmlu=qa.jsonl"
def test_explicit_mapping_mode_feeds_each_task(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input([GSM8K_ROW, GSM8K_ROW], name="math.jsonl")
        qa = write_input([MMLU_ROW], name="qa.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}")

    assert result.returncode == 0
    assert len(result.task_rows("gsm8k")) == 2
    assert len(result.task_rows("mmlu")) == 1


# Spec: "directory mode: --input-dir data/" with "--input-dir looks for
# <task_name>.jsonl"
def test_input_dir_mode_reads_task_named_files(workdir, write_config, write_input, run_argv):
    data = workdir / "data"
    data.mkdir()
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        write_input([GSM8K_ROW], name="data/gsm8k.jsonl")
        write_input([MMLU_ROW, MMLU_ROW], name="data/mmlu.jsonl")
        result = run_argv("--config", config, "--input-dir", data)

    assert result.returncode == 0
    assert len(result.task_rows("gsm8k")) == 1
    assert len(result.task_rows("mmlu")) == 2


# Spec: "--input-dir looks for <task_name>.jsonl" - an absent file for a task
# that must run is an input error
def test_input_dir_missing_file_exits_1(workdir, write_config, write_input, run_argv):
    data = workdir / "data"
    data.mkdir()
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    write_input([GSM8K_ROW], name="data/gsm8k.jsonl")
    result = run_argv("--config", config, "--input-dir", data)

    assert result.returncode == 1
    assert "mmlu" in result.stderr


# Spec: "explicit --input <task=path> and --input-dir are alternative modes;
# do not combine them"
def test_combining_input_and_input_dir_exits_1(workdir, write_config, write_input, run_argv):
    data = workdir / "data"
    data.mkdir()
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    math = write_input([GSM8K_ROW], name="math.jsonl")
    write_input([MMLU_ROW], name="data/mmlu.jsonl")
    result = run_argv("--config", config, "--input", f"gsm8k={math}", "--input-dir", data)

    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: multi-task input is required - neither mode supplied is an error
def test_multi_task_run_without_any_input_exits_1(write_config, run_argv):
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    result = run_argv("--config", config)

    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: explicit mapping mode - a task with no mapping cannot run
def test_missing_mapping_for_a_task_exits_1(write_config, write_input, run_argv):
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    math = write_input([GSM8K_ROW], name="math.jsonl")
    result = run_argv("--config", config, "--input", f"gsm8k={math}")

    assert result.returncode == 1
    assert "mmlu" in result.stderr


# Spec: explicit mapping mode names tasks from the config
def test_mapping_for_an_unknown_task_exits_1(write_config, write_input, run_argv):
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    math = write_input([GSM8K_ROW], name="math.jsonl")
    qa = write_input([MMLU_ROW], name="qa.jsonl")
    result = run_argv(
        "--config", config,
        "--input", f"gsm8k={math}", "--input", f"mmlu={qa}", "--input", f"nope={qa}",
    )

    assert result.returncode == 1
    assert "nope" in result.stderr


# Spec: "--task <name>: repeatable; run only the selected task or tasks"
def test_task_flag_runs_only_the_selected_task(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input([GSM8K_ROW], name="math.jsonl")
        result = run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--task", "gsm8k"
        )
        systems = {system_of(payload) for payload in api.payloads}

    assert result.returncode == 0
    assert systems == {GSM8K_TASK["prompt"]["system"]}


# Spec: "--task <name>: repeatable"
def test_task_flag_is_repeatable(workdir, write_config, write_input, run_argv):
    tasks = dict(BOTH_TASKS) | {"extra": copy.deepcopy(GSM8K_TASK)}
    data = workdir / "data"
    data.mkdir()
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, tasks))
        write_input([GSM8K_ROW], name="data/gsm8k.jsonl")
        write_input([MMLU_ROW], name="data/mmlu.jsonl")
        result = run_argv(
            "--config", config, "--input-dir", data, "--task", "gsm8k", "--task", "mmlu"
        )

    assert result.returncode == 0
    assert sorted(result.summary["tasks"]) == ["gsm8k", "mmlu"]


# Spec: "when --task is present, require input only for selected tasks and
# ignore unselected tasks for validation and execution"
def test_unselected_tasks_need_no_input(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input([GSM8K_ROW], name="math.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={math}", "--task", "gsm8k")

    assert result.returncode == 0
    assert result.task_rows("gsm8k")[0]["result"]["passed"] is True


# Spec: "--task <name>" names a task in the config
def test_unknown_task_name_exits_1(write_config, write_input, run_argv):
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    math = write_input([GSM8K_ROW], name="math.jsonl")
    result = run_argv("--config", config, "--input", f"gsm8k={math}", "--task", "nope")

    assert result.returncode == 1
    assert "nope" in result.stderr


# Spec: "when --task is present, ... ignore unselected tasks for validation"
# - an unselected task with a broken section does not stop the run
def test_unselected_task_config_is_not_validated(write_config, write_input, run_argv):
    broken = copy.deepcopy(MMLU_TASK)
    del broken["output_field"]
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": GSM8K_TASK, "mmlu": broken}))
        math = write_input([GSM8K_ROW], name="math.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={math}", "--task", "gsm8k")

    assert result.returncode == 0


# Spec: "for multi-task configs, --output must be a directory" and "write
# <output_dir>/<task_name>.jsonl"
def test_output_directory_holds_one_file_per_task(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input([GSM8K_ROW], name="math.jsonl")
        qa = write_input([MMLU_ROW], name="qa.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}")

    assert result.output_path.is_dir()
    assert sorted(path.name for path in result.output_path.iterdir()) == [
        "gsm8k.jsonl", "mmlu.jsonl",
    ]


# Spec: "for multi-task configs, --output must be a directory" - an existing
# file at that path is an error
def test_output_path_that_is_a_file_exits_1(workdir, write_config, write_input, run_argv):
    (workdir / "results").write_text("not a directory\n")
    config = write_config(multi_config("http://127.0.0.1:1", BOTH_TASKS))
    math = write_input([GSM8K_ROW], name="math.jsonl")
    qa = write_input([MMLU_ROW], name="qa.jsonl")
    result = run_argv("--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}")

    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "when --task is present, write output files only for the tasks that
# ran"
def test_only_selected_tasks_get_output_files(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input([GSM8K_ROW], name="math.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={math}", "--task", "gsm8k")

    assert [path.name for path in result.output_path.iterdir()] == ["gsm8k.jsonl"]


# Spec: "for single-task configs, --input <path> without = still behaves as in
# Part 1" and "--output <path> still writes a single file"
def test_single_task_config_keeps_part_1_input_and_output(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(base_config(api.url))
        rows = write_input([GSM8K_ROW])
        result = run_argv("--config", config, "--input", rows, output="results.jsonl")

    assert result.returncode == 0
    assert result.output_path.is_file()
    assert len(result.rows) == 1


# Spec: "--eval-model <string>: override the judge model for all selected
# llm_judge tasks"
def test_eval_model_overrides_the_judge_model(write_config, write_input, run_argv):
    review = {
        "prompt": {"system": "You are a writing assistant.", "user": "{prompt_text}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {"system": "quality evaluator", "user": "Rate:\n{__response__}"},
            "threshold": 7,
            "extract": "first_number",
            "model": "config-judge",
        },
        "output_field": "response",
    }

    def responder(payload, index):
        return Reply(completion("9" if "evaluator" in system_of(payload) else "an essay"))

    with FakeAPIServer(responder) as api:
        config = write_config(multi_config(api.url, {"review": review}))
        rows = write_input([{"prompt_text": "write something"}], name="review.jsonl")
        result = run_argv(
            "--config", config, "--input", f"review={rows}", "--eval-model", "flag-judge"
        )
        judge_models = [
            payload["model"] for payload in api.payloads if "evaluator" in system_of(payload)
        ]

    assert result.returncode == 0
    assert judge_models == ["flag-judge"]


# Spec: "--eval-model ... for all selected llm_judge tasks" - tasks of other
# types have no judge model to override
def test_eval_model_is_harmless_without_a_judge_task(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": GSM8K_TASK}))
        math = write_input([GSM8K_ROW], name="math.jsonl")
        result = run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--eval-model", "flag-judge"
        )
        models = [payload["model"] for payload in api.payloads]

    assert result.returncode == 0
    assert models == ["gpt-4"]
