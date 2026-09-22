"""The `--num-solutions`, `--icl-strategy` and `--icl-k` flags."""

from __future__ import annotations

from conftest import base_task, icl_block, inline_setup, used_setup
from fake_api import FakeAPI, always

COT = inline_setup("chain_of_thought", "#### 4", "#### 40")
DIRECT = inline_setup("direct", "#### 4", "#### 40")

ROW = {"question": "real", "answer": "5"}


def flag_task(api_url: str, **overrides) -> dict:
    """A sampled ICL task whose config values the flags are meant to replace."""
    task = base_task(api_url)
    task["generation"] = {"scheme": "sample", "temperature": 0.8}
    task["icl"] = icl_block([COT, DIRECT], k=2, strategy="fixed")
    task["num_solutions"] = 2
    task.update(overrides)
    return task


# Spec: "New flags: `--num-solutions <int>`" / "CLI flags override config
# values"
# Context: Multiple Solutions / Rules.
def test_num_solutions_flag_overrides_the_config(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(flag_task(api.url))
        result = run_cli(config, write_input([ROW]), "--num-solutions", "4")
        assert api.call_count == 4
    assert len(result.rows[0]["output"]) == 4


# Spec: "`--icl-strategy <fixed|random|round_robin>`"
# Context: Multiple Solutions / Rules.
def test_icl_strategy_flag_overrides_the_config(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(flag_task(api.url))
        run_cli(config, write_input([ROW]), "--icl-strategy", "round_robin")
        used = [used_setup(body) for body in api.requests]
    assert used == ["chain_of_thought", "direct"]


# Spec: "`--icl-k <int>`"
# Context: Multiple Solutions / Rules.
def test_icl_k_flag_overrides_the_config(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(flag_task(api.url))
        run_cli(config, write_input([ROW]), "--icl-k", "1")
        messages = api.requests[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


# Spec: "CLI flags override config values" — `--num-solutions 1` on a task
# without ICL returns the row to the Part 1 output format.
# Context: Multiple Solutions / Output Changes.
def test_num_solutions_one_restores_the_part_1_format(write_config, write_input, run_cli):
    task = base_task("placeholder")
    task["generation"] = {"scheme": "sample", "temperature": 0.8}
    task["num_solutions"] = 3
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        result = run_cli(config, write_input([ROW]), "--num-solutions", "1")
        assert api.call_count == 1
    assert result.rows[0]["output"] == {"solution": "#### 5"}


# Spec: "`--num-solutions <int>`" applies to every selected task of a
# multi-task config.
# Context: Multiple Solutions / Rules.
def test_num_solutions_flag_applies_to_every_task(write_yaml, write_inputs, run_args, workdir):
    from conftest import base_defaults, math_task, task_rows

    with FakeAPI(responder=always("#### 5")) as api:
        document = {
            "defaults": base_defaults(api.url, generation={"scheme": "sample", "temperature": 0.8}),
            "tasks": {"gsm8k": math_task(generation={"scheme": "sample", "temperature": 0.8})},
        }
        config = write_yaml(document)
        data = write_inputs({"gsm8k": [ROW]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"), "--num-solutions", "3",
        )
        assert api.call_count == 3
    assert len(task_rows(result, "gsm8k")[0]["output"]) == 3


# Spec: "`--icl-strategy` ... `--icl-k`" only describe ICL, so a task without
# an `icl` block is unaffected (see AMBIGUITIES T42).
# Context: Multiple Solutions / Rules.
def test_icl_flags_are_inert_without_an_icl_block(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        result = run_cli(config, write_input([ROW]), "--icl-strategy", "random", "--icl-k", "2")
    assert result.returncode == 0
    assert result.rows[0]["output"] == {"solution": "#### 5"}
