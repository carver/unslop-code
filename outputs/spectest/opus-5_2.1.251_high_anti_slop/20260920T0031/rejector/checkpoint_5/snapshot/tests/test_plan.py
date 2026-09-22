"""Resolving `--input`, `--input-dir` and `--output` into per-task work."""

import json

import pytest
import yaml
from test_config import NO_OVERRIDES
from test_multi_config import MULTI

from config import load_tasks
from errors import RejectorError
from plan import build_plan

GSM8K_ROW = {"question": "2 + 3?", "answer": "5"}
MMLU_ROW = {"question": "Capital of France?", "answer": "B"}

SINGLE = {
    "task": {
        "name": "demo",
        "api_url": "http://localhost:8000",
        "model": "gpt-4",
        "prompt": {"user": "{question}"},
        "evaluation": {"type": "exact_match", "answer_field": "answer"},
        "output_field": "solution",
    }
}


def write_jsonl(path, *rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return str(path)


def suite_for(tmp_path, document, selected=None):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return load_tasks(str(path), NO_OVERRIDES, selected)


@pytest.fixture
def multi(tmp_path):
    """A two-task suite with `gsm8k` and `mmlu` selected and their inputs on disk."""
    document = {"defaults": MULTI["defaults"], "tasks": {name: MULTI["tasks"][name] for name in ("gsm8k", "mmlu")}}
    write_jsonl(tmp_path / "math.jsonl", GSM8K_ROW)
    write_jsonl(tmp_path / "qa.jsonl", MMLU_ROW)
    return suite_for(tmp_path, document)


def test_explicit_mapping_loads_each_task_input(multi, tmp_path):
    plan = build_plan(multi, [f"gsm8k={tmp_path}/math.jsonl", f"mmlu={tmp_path}/qa.jsonl"], None, str(tmp_path / "out"))
    assert [(run.task.name, run.rows) for run in plan] == [("gsm8k", [GSM8K_ROW]), ("mmlu", [MMLU_ROW])]
    assert [run.output_path for run in plan] == [f"{tmp_path}/out/gsm8k.jsonl", f"{tmp_path}/out/mmlu.jsonl"]


def test_output_directory_is_created(multi, tmp_path):
    build_plan(multi, [f"gsm8k={tmp_path}/math.jsonl", f"mmlu={tmp_path}/qa.jsonl"], None, str(tmp_path / "out"))
    assert (tmp_path / "out").is_dir()


def test_input_dir_uses_the_task_name(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    write_jsonl(data / "gsm8k.jsonl", GSM8K_ROW)
    write_jsonl(data / "mmlu.jsonl", MMLU_ROW)
    document = {"defaults": MULTI["defaults"], "tasks": {name: MULTI["tasks"][name] for name in ("gsm8k", "mmlu")}}

    plan = build_plan(suite_for(tmp_path, document), [], str(data), str(tmp_path / "out"))
    assert [run.rows for run in plan] == [[GSM8K_ROW], [MMLU_ROW]]


def test_selected_tasks_need_no_input_for_the_others(tmp_path):
    document = {"defaults": MULTI["defaults"], "tasks": {name: MULTI["tasks"][name] for name in ("gsm8k", "mmlu")}}
    suite = suite_for(tmp_path, document, selected=["gsm8k"])
    source = write_jsonl(tmp_path / "math.jsonl", GSM8K_ROW)

    plan = build_plan(suite, [f"gsm8k={source}", "mmlu=nowhere.jsonl"], None, str(tmp_path / "out"))
    assert [run.task.name for run in plan] == ["gsm8k"]


def test_missing_input_for_a_selected_task_is_reported(multi, tmp_path):
    with pytest.raises(RejectorError, match="no --input given for task\\(s\\): mmlu"):
        build_plan(multi, [f"gsm8k={tmp_path}/math.jsonl"], None, str(tmp_path / "out"))


def test_input_and_input_dir_cannot_be_combined(multi, tmp_path):
    with pytest.raises(RejectorError, match="cannot be combined"):
        build_plan(multi, [f"gsm8k={tmp_path}/math.jsonl"], str(tmp_path), str(tmp_path / "out"))


def test_an_input_needs_a_task_name_in_a_multi_task_config(multi, tmp_path):
    with pytest.raises(RejectorError, match="must be given as <task>=<path>"):
        build_plan(multi, [f"{tmp_path}/math.jsonl"], None, str(tmp_path / "out"))


def test_an_input_for_an_unknown_task_is_reported(multi, tmp_path):
    with pytest.raises(RejectorError, match="unknown task 'arc'"):
        build_plan(multi, [f"arc={tmp_path}/math.jsonl"], None, str(tmp_path / "out"))


def test_single_task_config_keeps_the_bare_input_and_output_paths(tmp_path):
    suite = suite_for(tmp_path, SINGLE)
    source = write_jsonl(tmp_path / "input.jsonl", GSM8K_ROW)

    plan = build_plan(suite, [source], None, str(tmp_path / "out.jsonl"))
    assert [(run.rows, run.output_path) for run in plan] == [([GSM8K_ROW], f"{tmp_path}/out.jsonl")]


def test_an_input_is_required(tmp_path):
    with pytest.raises(RejectorError, match="one of --input or --input-dir"):
        build_plan(suite_for(tmp_path, SINGLE), [], None, str(tmp_path / "out.jsonl"))
