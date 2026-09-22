"""Multi-task configs: defaults merging, task selection and the new evaluation types."""

from copy import deepcopy

import pytest
import yaml

from config import load_tasks
from errors import RejectorError
from test_config import NO_OVERRIDES
from test_icl import SETUPS

MULTI = {
    "defaults": {
        "api_url": "http://localhost:8000",
        "model": "gpt-4",
        "rpm": 60,
        "generation": {"max_tokens": 512},
    },
    "tasks": {
        "gsm8k": {
            "prompt": {"system": "Solve it.", "user": "{question}"},
            "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5},
            "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
            "output_field": "solution",
        },
        "mmlu": {
            "prompt": {"system": "One letter.", "user": "{question}"},
            "generation": {"scheme": "greedy"},
            "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
            "output_field": "choice",
        },
        "code_gen": {
            "model": "gpt-4-code",
            "prompt": {"system": "Write code.", "user": "{problem}"},
            "evaluation": {"type": "script", "command_template": 'python3 -c "{test_code}"'},
            "output_field": "code",
        },
        "review": {
            "prompt": {"system": "Write.", "user": "{prompt_text}"},
            "evaluation": {
                "type": "llm_judge",
                "judge_prompt": {"system": "Rate it.", "user": "{__response__} / {criteria}"},
                "threshold": 7,
                "extract": "first_number",
            },
            "output_field": "response",
        },
    },
}


def write_config(tmp_path, document=None):
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump(document or MULTI, sort_keys=False))
    return str(path)


def load(tmp_path, document=None, selected=None, **overrides):
    return load_tasks(write_config(tmp_path, document), {**NO_OVERRIDES, **overrides}, selected)


def by_name(suite):
    return {task.name: task for task in suite.tasks}


def test_every_task_is_loaded_in_config_order(tmp_path):
    suite = load(tmp_path)
    assert suite.multi is True
    assert [task.name for task in suite.tasks] == ["gsm8k", "mmlu", "code_gen", "review"]


def test_defaults_fill_in_and_tasks_override_them(tmp_path):
    tasks = by_name(load(tmp_path))
    assert (tasks["gsm8k"].api_url, tasks["gsm8k"].model) == ("http://localhost:8000", "gpt-4")
    assert tasks["gsm8k"].limits.rpm == 60
    assert tasks["code_gen"].model == "gpt-4-code"


def test_nested_sections_are_merged_per_task(tmp_path):
    tasks = by_name(load(tmp_path))
    assert tasks["gsm8k"].generation.max_tokens == 512  # from defaults
    assert (tasks["gsm8k"].generation.scheme, tasks["gsm8k"].generation.n) == ("rejection", 5)
    assert tasks["mmlu"].generation.scheme == "greedy"


def test_num_solutions_comes_from_defaults_unless_a_task_sets_its_own(tmp_path):
    document = deepcopy(MULTI)
    document["defaults"]["num_solutions"] = 3
    document["tasks"]["mmlu"]["num_solutions"] = 1
    tasks = by_name(load(tmp_path, document))
    assert (tasks["gsm8k"].num_solutions, tasks["mmlu"].num_solutions) == (3, 1)
    assert tasks["gsm8k"].generation.max_attempts == 9


def test_icl_defaults_are_merged_key_by_key(tmp_path):
    document = deepcopy(MULTI)
    document["defaults"]["icl"] = {"setups": SETUPS, "k": 1, "strategy": "fixed"}
    document["tasks"]["gsm8k"]["icl"] = {"strategy": "round_robin"}
    tasks = by_name(load(tmp_path, document))
    assert (tasks["gsm8k"].icl.strategy, tasks["gsm8k"].icl.k) == ("round_robin", 1)
    assert tasks["mmlu"].icl.strategy == "fixed"


def test_cli_overrides_apply_to_every_selected_task(tmp_path):
    tasks = by_name(load(tmp_path, model="mini", rpm=120))
    assert {task.model for task in tasks.values()} == {"mini"}
    assert {task.limits.rpm for task in tasks.values()} == {120}


def test_task_selection_validates_only_the_selected_tasks(tmp_path):
    document = deepcopy(MULTI)
    document["tasks"]["mmlu"].pop("output_field")
    suite = load(tmp_path, document, selected=["gsm8k"])
    assert [task.name for task in suite.tasks] == ["gsm8k"]
    assert suite.names == ("gsm8k", "mmlu", "code_gen", "review")


def test_unknown_selected_task_is_rejected(tmp_path):
    with pytest.raises(RejectorError, match="unknown task"):
        load(tmp_path, selected=["arc"])


def test_judge_model_falls_back_to_the_task_model(tmp_path):
    assert by_name(load(tmp_path))["review"].evaluation.model == "gpt-4"


def test_eval_model_override_wins_over_the_config(tmp_path):
    document = deepcopy(MULTI)
    document["tasks"]["review"]["evaluation"]["model"] = "judge-7b"
    assert by_name(load(tmp_path, document))["review"].evaluation.model == "judge-7b"
    assert by_name(load(tmp_path, document, eval_model="judge-70b"))["review"].evaluation.model == "judge-70b"


def test_script_evaluation_defaults_to_exit_code_zero(tmp_path):
    evaluation = by_name(load(tmp_path))["code_gen"].evaluation
    assert (evaluation.command_template, evaluation.success_exit_code) == ('python3 -c "{test_code}"', 0)


@pytest.mark.parametrize(
    "task, changes, message",
    [
        ("review", {"threshold": None}, "threshold is required"),
        ("review", {"judge_prompt": {"system": "Rate it."}}, "judge_prompt.user is required"),
        ("code_gen", {"command_template": None}, "command_template is required"),
    ],
)
def test_new_evaluation_types_validate_their_fields(tmp_path, task, changes, message):
    document = deepcopy(MULTI)
    for key, value in changes.items():
        document["tasks"][task]["evaluation"][key] = value
    with pytest.raises(RejectorError, match=message):
        load(tmp_path, document)


def test_errors_name_the_offending_task(tmp_path):
    document = deepcopy(MULTI)
    document["tasks"]["mmlu"].pop("output_field")
    with pytest.raises(RejectorError, match="tasks.mmlu.output_field is required"):
        load(tmp_path, document)


def test_tasks_mapping_must_not_be_empty(tmp_path):
    with pytest.raises(RejectorError, match="non-empty 'tasks' mapping"):
        load(tmp_path, {"defaults": {}, "tasks": {}})
