"""ICL setups and multiple solutions per input, end to end against the mock API."""

import json

import pytest
import yaml
from mock_server import start_mock_server

import rejector

SETUPS = [
    {
        "name": "chain_of_thought",
        "examples": [
            {"input": {"question": "What is 2+2?"}, "output": "Let me think step by step.\n#### 4"},
            {"input": {"question": "3 cats plus 2?"}, "output": "Step by step:\n#### 5"},
        ],
    },
    {
        "name": "direct",
        "examples": [
            {"input": {"question": "What is 2+2?"}, "output": "#### 4"},
            {"input": {"question": "3 cats plus 2?"}, "output": "#### 5"},
        ],
    },
]

TASK = {
    "name": "math_solve",
    "model": "gpt-4",
    "rpm": 600,
    "prompt": {"system": "Solve the math problem.", "user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 256},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}

ROW = {"question": "What is 15 + 27?", "answer": "42"}


@pytest.fixture
def api():
    """Start a mock server whose responder the test installs afterwards."""
    servers = []

    def start(responder):
        url, state, shutdown = start_mock_server(responder)
        servers.append(shutdown)
        return url, state

    yield start
    for shutdown in servers:
        shutdown()


def run(tmp_path, capsys, url=None, rows=(ROW,), argv=(), files=None, **task):
    """Write a config plus its ICL files, run the CLI and return `(code, records, summary)`."""
    for name, text in (files or {}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    config = {**TASK, **task, "api_url": url or "http://127.0.0.1:1"}
    (tmp_path / "task.yaml").write_text(yaml.safe_dump({"task": config}))
    (tmp_path / "in.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    code = rejector.main(
        [
            "run",
            "--config", str(tmp_path / "task.yaml"),
            "--input", str(tmp_path / "in.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
            *argv,
        ]
    )
    streams = capsys.readouterr()
    output = tmp_path / "out.jsonl"
    lines = output.read_text().splitlines() if output.exists() else []
    summary = json.loads(streams.out) if streams.out.strip() else None
    return code, [json.loads(line) for line in lines], summary, streams.err


def setups_of(state):
    """The setup each recorded call replayed, read back from its example turns."""
    names = {SETUPS[0]["examples"][0]["output"]: "chain_of_thought", "#### 4": "direct"}
    return [names.get(call["messages"][2]["content"]) for call in state.calls]


def test_single_solution_with_icl_uses_the_list_format(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    _, records, _, _ = run(
        tmp_path, capsys, url, icl={"setups": SETUPS, "strategy": "fixed"},
    )

    assert records[0]["output"] == [{"solution": "#### 42", "icl_setup": "chain_of_thought"}]
    assert records[0]["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert records[0]["meta"][0]["icl_setup"] == "chain_of_thought"
    assert records[0]["meta"][0]["evaluation_passed"] is True
    # System message, then the two example turns as user/assistant pairs, then the question.
    assert [message["role"] for message in state.calls[0]["messages"]] == [
        "system", "user", "assistant", "user", "assistant", "user"
    ]
    assert state.calls[0]["messages"][1] == {"role": "user", "content": "What is 2+2?"}
    assert state.calls[0]["messages"][-1] == {"role": "user", "content": "What is 15 + 27?"}


def test_round_robin_cycles_setups_across_attempts(tmp_path, api, capsys):
    three = SETUPS + [{"name": "terse", "examples": [{"input": {"question": "q"}, "output": "#### 1"}]}]
    url, state = api(lambda payload, call: "#### 0")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 5},
        icl={"setups": three, "strategy": "round_robin", "k": 1},
        num_solutions=5,
    )

    assert [meta["icl_setup"] for meta in records[0]["meta"]] == [
        "chain_of_thought", "direct", "terse", "chain_of_thought", "direct"
    ]
    assert len(state.calls) == 5


def test_greedy_is_capped_by_the_number_of_setups(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    _, records, _, summary = run(
        tmp_path, capsys, url,
        icl={"setups": SETUPS, "strategy": "round_robin"},
        num_solutions=5,
    )

    assert [item["icl_setup"] for item in records[0]["output"]] == ["chain_of_thought", "direct"]
    assert records[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert setups_of(state) == ["chain_of_thought", "direct"]
    assert all(call["temperature"] == 0.0 for call in state.calls)


def test_rejection_stops_once_enough_solutions_pass(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 42" if call % 2 else "#### 0")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "rejection", "temperature": 0.7},
        icl={"setups": SETUPS[:1]},
        num_solutions=2,
    )

    # The mock alternates per prompt, so the first and third attempts pass.
    assert records[0]["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert records[0]["output"] == [
        {"solution": "#### 42", "icl_setup": "chain_of_thought"},
        {"solution": "#### 42", "icl_setup": "chain_of_thought"},
    ]


def test_rejection_gives_up_at_max_attempts_with_a_partial_result(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 42" if call <= 2 else "#### 0")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 10},
        num_solutions=5,
    )

    assert len(records[0]["output"]) == 2
    assert records[0]["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert [meta["evaluation_passed"] for meta in records[0]["meta"]][:3] == [True, True, False]
    assert all(meta["icl_setup"] is None for meta in records[0]["meta"])


def test_max_attempts_defaults_to_three_per_solution(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 0")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "rejection", "temperature": 0.7},
        num_solutions=4,
    )

    assert records[0]["result"] == {"passed": 0, "failed": 12, "attempts": 12}
    assert records[0]["output"] == []
    assert len(state.calls) == 12


def test_sample_keeps_every_solution_regardless_of_evaluation(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42" if call == 1 else "#### 0")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "sample", "temperature": 0.7},
        icl={"setups": SETUPS, "strategy": "round_robin"},
        num_solutions=3,
    )

    assert [item["icl_setup"] for item in records[0]["output"]] == [
        "chain_of_thought", "direct", "chain_of_thought"
    ]
    assert records[0]["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert all(call["temperature"] == 0.7 for call in state.calls)


def test_sample_without_icl_makes_one_request_per_solution(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=3,
    )

    assert len(state.calls) == 3
    assert records[0]["output"] == [{"solution": "#### 42", "icl_setup": None}] * 3


def test_random_strategy_only_draws_from_the_declared_setups(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "sample", "temperature": 0.7},
        icl={"setups": SETUPS, "strategy": "random"},
        num_solutions=8,
    )

    assert set(setups_of(state)) <= {"chain_of_thought", "direct"}
    assert {item["icl_setup"] for item in records[0]["output"]} <= {"chain_of_thought", "direct"}


def test_k_keeps_the_first_examples_of_the_setup(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    run(tmp_path, capsys, url, icl={"setups": SETUPS, "k": 1})

    assert [message["role"] for message in state.calls[0]["messages"]] == [
        "system", "user", "assistant", "user"
    ]
    assert state.calls[0]["messages"][1]["content"] == "What is 2+2?"


def test_icl_k_flag_overrides_the_config(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    run(tmp_path, capsys, url, argv=["--icl-k", "1"], icl={"setups": SETUPS, "k": 2})

    assert len(state.calls[0]["messages"]) == 4


def test_num_solutions_flag_overrides_the_config(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        argv=["--num-solutions", "2"],
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=5,
    )

    assert len(state.calls) == 2 and len(records[0]["output"]) == 2


def test_file_backed_setup_is_read_relative_to_the_config(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    lines = '{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\\n#### 5"}\n'
    _, records, _, _ = run(
        tmp_path, capsys, url,
        files={"icl/detailed.jsonl": lines},
        icl={"setups": [{"name": "detailed", "file": "icl/detailed.jsonl"}]},
    )

    assert records[0]["output"][0]["icl_setup"] == "detailed"
    assert state.calls[0]["messages"][1]["content"] == "What is 10 / 2?"
    assert state.calls[0]["messages"][2]["content"] == "10 divided by 2 is 5.\n#### 5"


def test_without_evaluation_the_pass_count_is_the_emitted_outputs(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "anything")
    _, records, _, _ = run(
        tmp_path, capsys, url,
        generation={"scheme": "sample", "temperature": 0.7},
        evaluation=None,
        num_solutions=3,
    )

    assert records[0]["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert all(meta["evaluation_passed"] is None for meta in records[0]["meta"])


def test_summary_reports_solutions_per_input(tmp_path, api, capsys):
    rows = [{"question": f"What is {index} + 0?", "answer": "42"} for index in range(4)]
    url, _ = api(lambda payload, call: "#### 42" if call == 1 else "#### 0")
    task = {key: value for key, value in TASK.items() if key != "name"}
    document = {
        "defaults": {"api_url": url},
        "tasks": {
            "math": {
                **task,
                "generation": {"scheme": "sample", "temperature": 0.7},
                "num_solutions": 3,
            }
        },
    }
    (tmp_path / "multi.yaml").write_text(yaml.safe_dump(document))
    (tmp_path / "in.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    code = rejector.main(
        [
            "run",
            "--config", str(tmp_path / "multi.yaml"),
            "--input", f"math={tmp_path / 'in.jsonl'}",
            "--output", str(tmp_path / "results"),
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert summary["tasks"]["math"] == {
        "total": 4, "passed": 4, "failed": 0,
        "total_solutions": 12, "avg_solutions_per_input": 3.0, "total_api_calls": 12,
    }


def test_malformed_icl_file_fails_before_any_request(tmp_path, capsys):
    code, records, _, err = run(
        tmp_path, capsys,
        files={"icl/broken.jsonl": '{"input": {"question": "q"}, "output": "a"}\nnot json\n'},
        icl={"setups": [{"name": "broken", "file": "icl/broken.jsonl"}]},
    )

    assert code == 1 and not records
    assert "line 2 is not valid JSON" in err


def test_icl_file_missing_output_key_is_reported(tmp_path, capsys):
    code, _, _, err = run(
        tmp_path, capsys,
        files={"icl/broken.jsonl": '{"input": {"question": "q"}}\n'},
        icl={"setups": [{"name": "broken", "file": "icl/broken.jsonl"}]},
    )

    assert code == 1 and "'output' must be a string" in err


def test_a_setup_needs_exactly_one_source(tmp_path, capsys):
    code, _, _, err = run(
        tmp_path, capsys,
        icl={"setups": [{"name": "both", "examples": [], "file": "icl/x.jsonl"}]},
    )

    assert code == 1 and "needs exactly one of 'examples' or 'file'" in err


def test_an_unknown_strategy_is_reported(tmp_path, capsys):
    code, _, _, err = run(tmp_path, capsys, icl={"setups": SETUPS, "strategy": "shuffle"})

    assert code == 1 and "strategy must be one of fixed, random, round_robin" in err


def test_an_example_missing_a_template_field_is_reported(tmp_path, capsys):
    setups = [{"name": "bad", "examples": [{"input": {"prompt": "q"}, "output": "a"}]}]
    code, _, _, err = run(tmp_path, capsys, icl={"setups": setups})

    assert code == 1
    assert "icl setup 'bad' example 0" in err and "missing field 'question'" in err


def test_icl_strategy_flag_overrides_the_config(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 42")
    run(
        tmp_path, capsys, url,
        argv=["--icl-strategy", "round_robin"],
        generation={"scheme": "sample", "temperature": 0.7},
        icl={"setups": SETUPS, "strategy": "fixed"},
        num_solutions=2,
    )

    assert setups_of(state) == ["chain_of_thought", "direct"]


def test_icl_flags_are_ignored_by_a_task_without_setups(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 42")
    code, records, _, _ = run(
        tmp_path, capsys, url, argv=["--icl-strategy", "random", "--icl-k", "2"]
    )

    assert code == 0
    assert records[0]["output"] == {"solution": "#### 42"}
