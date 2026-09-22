"""Part 3 CLI: --num-solutions, --icl-strategy, --icl-k and config precedence."""
import pytest

from conftest import (icl_block, make_config, make_multi_config,
                      marker_setups)
from mock_api import MockAPI, always

ROWS = [{"question": "q", "answer": "42"}]
SAMPLE = dict(scheme="sample", temperature=0.7)


# Spec: "New flags: --num-solutions <int>"
# Context: Multiple Solutions.
def test_num_solutions_flag_sets_the_number_of_solutions(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, **SAMPLE), ROWS,
                       args=["--num-solutions", "3"])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    assert len(run.rows[0]["output"]) == 3


# Spec: "CLI flags override config values"
# Context: Multiple Solutions rules.
def test_num_solutions_flag_overrides_the_config(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=5, **SAMPLE),
                       ROWS, args=["--num-solutions", "2"])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2


# Spec: "New flags: --icl-strategy <fixed|random|round_robin>"
# Context: Multiple Solutions.
def test_icl_strategy_flag_overrides_the_config(run_tool):
    icl = icl_block(marker_setups(["A", "B"]), strategy="fixed")
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, **SAMPLE), ROWS,
                       args=["--num-solutions", "4",
                             "--icl-strategy", "round_robin"])
    assert run.returncode == 0, run.stderr
    assert [o["icl_setup"] for o in run.rows[0]["output"]] == ["A", "B",
                                                               "A", "B"]


def test_icl_strategy_flag_rejects_an_unknown_value(run_tool):
    icl = icl_block(marker_setups(["A", "B"]))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS,
                       args=["--icl-strategy", "cycle"])
    assert run.returncode == 1
    assert api.call_count == 0


# Spec: "New flags: --icl-k <int>"
# Context: Multiple Solutions.
def test_icl_k_flag_overrides_the_config(run_tool):
    icl = icl_block(marker_setups(["A"], per_setup=4), k=4)
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS,
                       args=["--icl-k", "1"])
    assert run.returncode == 0, run.stderr
    assistants = [m for m in api.calls[0]["messages"]
                  if m["role"] == "assistant"]
    assert [m["content"] for m in assistants] == ["MARK_A0"]


@pytest.mark.parametrize("value", ["0", "-2", "abc"])
def test_invalid_icl_k_flag_exits_1(run_tool, value):
    icl = icl_block(marker_setups(["A"], per_setup=2))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS,
                       args=["--icl-k", value])
    assert run.returncode == 1
    assert api.call_count == 0


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "x"])
def test_invalid_num_solutions_exits_1(run_tool, value):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, **SAMPLE), ROWS,
                       args=["--num-solutions", value])
    assert run.returncode == 1
    assert api.call_count == 0


@pytest.mark.parametrize("value", [0, -3, "two"])
def test_invalid_num_solutions_in_config_exits_1(run_tool, value):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=value,
                                   **SAMPLE), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# T56: the ICL flags are ignored by a task that has no ICL block.
def test_icl_flags_are_ignored_without_icl(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS,
                       args=["--icl-k", "2", "--icl-strategy", "random"])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] == {"solution": "#### 42"}


# Spec: "`num_solutions` may be set in `defaults` or per task"
# Context: Multiple Solutions rules.
def _sample_tasks():
    base = {"prompt": {"system": "S", "user": "{question}"},
            "generation": {"scheme": "sample", "temperature": 0.7},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution"}
    return {"gsm8k": dict(base), "mmlu": dict(base)}


def test_num_solutions_from_defaults_applies_to_every_task(multi):
    config = make_multi_config(defaults={"num_solutions": 3},
                               tasks=_sample_tasks())
    with MockAPI(always("#### 42")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": ROWS, "mmlu": ROWS})
    assert run.returncode == 0, run.stderr
    assert len(run.rows("gsm8k")[0]["output"]) == 3
    assert len(run.rows("mmlu")[0]["output"]) == 3


def test_per_task_num_solutions_overrides_defaults(multi):
    tasks = _sample_tasks()
    tasks["mmlu"]["num_solutions"] = 2
    config = make_multi_config(defaults={"num_solutions": 4}, tasks=tasks)
    with MockAPI(always("#### 42")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": ROWS, "mmlu": ROWS})
    assert run.returncode == 0, run.stderr
    assert len(run.rows("gsm8k")[0]["output"]) == 4
    assert len(run.rows("mmlu")[0]["output"]) == 2


def test_num_solutions_flag_overrides_every_task(multi):
    tasks = _sample_tasks()
    tasks["mmlu"]["num_solutions"] = 2
    config = make_multi_config(defaults={"num_solutions": 4}, tasks=tasks)
    with MockAPI(always("#### 42")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": ROWS, "mmlu": ROWS},
                        args=["--num-solutions", "1"])
    assert run.returncode == 0, run.stderr
    # num_solutions 1 with no ICL is the Part 1 row format.
    assert run.rows("gsm8k")[0]["output"] == {"solution": "#### 42"}
    assert run.rows("mmlu")[0]["output"] == {"solution": "#### 42"}


# Spec: the config block from Multiple Solutions.
# Context: Multiple Solutions.
SPEC_MULTI = """
tasks:
  gsm8k:
    api_url: "%s"
    model: "gpt-4"
    rpm: 60
    prompt:
      system: "Solve."
      user: "{question}"
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
      max_attempts: 15
    num_solutions: 5
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
"""


def test_spec_multiple_solutions_config(multi):
    with MockAPI(always("#### 42")) as api:
        run = multi.run(None, {"gsm8k": ROWS}, config_text=SPEC_MULTI % api.url)
    assert run.returncode == 0, run.stderr
    row = run.rows("gsm8k")[0]
    assert len(row["output"]) == 5
    assert row["result"] == {"passed": 5, "failed": 0, "attempts": 5}
