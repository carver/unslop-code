"""Multi-task config files: `defaults` plus a `tasks` mapping."""

from __future__ import annotations

import copy

from fake_server import FakeAPIServer, Reply, completion, system_of
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config


def _answers(payload, index):
    """Answers both sample tasks: a number for gsm8k, a letter for mmlu."""
    return Reply(completion("#### 5" if "math" in system_of(payload) else "The answer is B) Paris"))


def _gsm8k_row():
    return {"question": "What is 2 + 3?", "answer": "5"}


def _mmlu_row():
    return {
        "question": "What is the capital of France?",
        "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid",
        "answer": "B",
    }


# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping" - each
# named task runs and produces its own output file
def test_every_task_in_the_mapping_runs(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK}))
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        mmlu = write_input([_mmlu_row()], name="mmlu.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}", "--input", f"mmlu={mmlu}")

    assert result.returncode == 0
    assert result.task_rows("gsm8k")[0]["result"]["passed"] is True
    assert result.task_rows("mmlu")[0]["result"]["passed"] is True


# Spec: "Each task has its own prompt, generation settings, evaluation, and
# output field."
def test_each_task_uses_its_own_prompt_and_output_field(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK}))
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        mmlu = write_input([_mmlu_row()], name="mmlu.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}", "--input", f"mmlu={mmlu}")
        systems = sorted(system_of(payload) for payload in api.payloads)

    assert systems == sorted([GSM8K_TASK["prompt"]["system"], MMLU_TASK["prompt"]["system"]])
    assert "solution" in result.task_rows("gsm8k")[0]["output"]
    assert "choice" in result.task_rows("mmlu")[0]["output"]


# Spec: "`defaults` provides shared values; each task overrides `defaults`"
def test_task_value_overrides_the_default(write_config, write_input, run_argv):
    task = copy.deepcopy(GSM8K_TASK) | {"model": "task-model"}
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": task}, model="default-model"))
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}")
        payloads = api.payloads

    assert payloads[0]["model"] == "task-model"
    assert result.task_rows("gsm8k")[0]["meta"]["model"] == "task-model"


# Spec: "`defaults` provides shared values" - a task that overrides nothing
# inherits every shared value
def test_defaults_supply_values_the_task_omits(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": GSM8K_TASK}, model="default-model"))
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        run_argv("--config", config, "--input", f"gsm8k={gsm8k}")
        payloads = api.payloads

    assert payloads[0]["model"] == "default-model"


# Spec: "nested sections such as `prompt`, `generation`, and `evaluation` are
# merged per task using the Part 1 structure"
def test_generation_section_merges_with_defaults(write_config, write_input, run_argv):
    task = copy.deepcopy(GSM8K_TASK)
    task["generation"] = {"scheme": "sample", "temperature": 0.7}
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": task}))
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        run_argv("--config", config, "--input", f"gsm8k={gsm8k}")
        payloads = api.payloads

    assert payloads[0]["temperature"] == 0.7
    assert payloads[0]["max_tokens"] == 512


# Spec: "nested sections such as `prompt`, `generation`, and `evaluation` are
# merged per task"
def test_evaluation_section_merges_with_defaults(write_config, write_input, run_argv):
    task = copy.deepcopy(GSM8K_TASK)
    task["evaluation"] = {"extract": "last_number"}
    shared_evaluation = {"type": "exact_match", "answer_field": "answer"}
    with FakeAPIServer(_answers) as api:
        config = write_config(
            multi_config(api.url, {"gsm8k": task}, evaluation=shared_evaluation)
        )
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}")

    assert result.returncode == 0
    assert result.task_rows("gsm8k")[0]["result"]["passed"] is True


# Spec: "nested sections such as `prompt` ... are merged per task"
def test_prompt_section_merges_with_defaults(write_config, write_input, run_argv):
    task = copy.deepcopy(GSM8K_TASK)
    task["prompt"] = {"user": "{question}"}
    with FakeAPIServer(_answers) as api:
        config = write_config(
            multi_config(api.url, {"gsm8k": task}, prompt={"system": "shared math system"})
        )
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        run_argv("--config", config, "--input", f"gsm8k={gsm8k}")
        payloads = api.payloads

    assert system_of(payloads[0]) == "shared math system"


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task" - satisfied by `defaults`
def test_required_field_may_come_from_defaults(write_config, write_input, run_argv):
    task = copy.deepcopy(GSM8K_TASK)
    del task["output_field"]
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, {"gsm8k": task}, output_field="solution"))
        gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}")

    assert result.returncode == 0
    assert "solution" in result.task_rows("gsm8k")[0]["output"]


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task" - satisfied by neither
def test_missing_required_field_exits_1(write_config, write_input, run_argv):
    task = copy.deepcopy(GSM8K_TASK)
    del task["output_field"]
    config = write_config(multi_config("http://127.0.0.1:1", {"gsm8k": task}))
    gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
    result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}")

    assert result.returncode == 1
    assert "output_field" in result.stderr


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task" - api_url and model are required too
def test_missing_model_exits_1(write_config, write_input, run_argv):
    config_map = multi_config("http://127.0.0.1:1", {"gsm8k": GSM8K_TASK})
    del config_map["defaults"]["model"]
    config = write_config(config_map)
    gsm8k = write_input([_gsm8k_row()], name="gsm8k.jsonl")
    result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}")

    assert result.returncode == 1
    assert "model" in result.stderr


# Spec: "if the config still uses a top-level `task` key, treat it as the
# Part 1 single-task format"
def test_top_level_task_key_is_the_part_1_format(write_config, write_input, run_cli):
    with FakeAPIServer(_answers) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([_gsm8k_row()]))

    assert result.returncode == 0
    assert result.output_path.is_file()
    assert result.rows[0]["output"] == {"solution": "#### 5"}


# Spec: "the task name is `task.name`" - selection by that name runs the task
def test_single_task_name_comes_from_task_name(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(base_config(api.url))
        rows = write_input([_gsm8k_row()])
        result = run_argv(
            "--config", config, "--input", rows, "--task", "gsm8k_solve",
            output="results.jsonl",
        )

    assert result.returncode == 0
    assert len(result.rows) == 1


# Spec: "the task name is `task.name`" - a name that is not the task's is not
# a selectable task
def test_single_task_selection_of_another_name_exits_1(write_config, write_input, run_argv):
    config = write_config(base_config("http://127.0.0.1:1"))
    rows = write_input([_gsm8k_row()])
    result = run_argv(
        "--config", config, "--input", rows, "--task", "other", output="results.jsonl"
    )

    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: a config that is neither format is a configuration error
def test_config_without_task_or_tasks_exits_1(write_config, write_input, run_argv):
    config = write_config({"defaults": {"model": "gpt-4"}})
    rows = write_input([_gsm8k_row()])
    result = run_argv("--config", config, "--input", rows, output="results.jsonl")

    assert result.returncode == 1
    assert result.stderr.strip()
