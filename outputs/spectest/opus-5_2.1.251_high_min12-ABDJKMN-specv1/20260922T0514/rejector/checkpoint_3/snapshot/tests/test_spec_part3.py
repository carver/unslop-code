"""Tests derived phrase-by-phrase from the Part 3 spec.

Part 3 adds in-context-learning (ICL) setups and multiple solutions per input:
`icl.setups` / `icl.k` / `icl.strategy`, `num_solutions`, `max_attempts`, the
list-shaped `output`/`meta` row format and the new per-task summary fields.
Each section comment quotes the spec phrase under test plus the minimal
context needed to read it.
"""
import copy
import json

import pytest
import yaml

from conftest import completion, judge_split, make_config, make_multi_config

MATH_ROWS = [{"question": "What is 2 + 3?", "answer": "5"}]

# The two setups from the spec's canonical `icl` block.
COT = {
    "name": "chain_of_thought",
    "examples": [
        {"input": {"question": "What is 2+2?"},
         "output": "Let me think step by step.\n2 + 2 = 4\n#### 4"},
        {"input": {"question": "If I have 3 cats and get 2 more, how many cats do I have?"},
         "output": "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5"},
    ],
}
DIRECT = {
    "name": "direct",
    "examples": [
        {"input": {"question": "What is 2+2?"}, "output": "#### 4"},
        {"input": {"question": "If I have 3 cats and get 2 more, how many cats do I have?"},
         "output": "#### 5"},
    ],
}

PASS = "2 + 3 = 5\n#### 5"      # matches answer "5" under last_number
FAIL = "2 + 3 = 9\n#### 9"


def tagged(name, count=1):
    """A setup whose example turns identify it: input `ex-<name>-i`, output `ANS-<name>-i`."""
    return {
        "name": name,
        "examples": [{"input": {"question": "ex-%s-%d" % (name, i)},
                      "output": "ANS-%s-%d" % (name, i)} for i in range(count)],
    }


def used(body):
    """The setup tag baked into a request's example assistant turns, or None."""
    for msg in body.get("messages", []):
        if msg["role"] == "assistant":
            return msg["content"].split("-")[1]
    return None


def icl_config(url, setups, *, k=None, strategy=None, num_solutions=None, **over):
    """A single-task Part 1 config with an `icl` block bolted on."""
    cfg = make_config(url, **over)
    icl = {"setups": copy.deepcopy(setups)}
    if k is not None:
        icl["k"] = k
    if strategy is not None:
        icl["strategy"] = strategy
    cfg["task"]["icl"] = icl
    if num_solutions is not None:
        cfg["task"]["num_solutions"] = num_solutions
    return cfg


def rejection(**over):
    gen = {"scheme": "rejection", "temperature": 0.7, "n": 5}
    gen.update(over)
    return gen


def write_icl_file(tmp_path, relpath, lines):
    """Write raw JSONL lines at `relpath` under the config directory."""
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def jl(question, output):
    return json.dumps({"input": {"question": question}, "output": output})


# ---------------------------------------------------------------------------
# ICL Configuration
# "Tasks may define named ICL setups"
# ---------------------------------------------------------------------------

def test_task_with_an_icl_block_runs(run_cli, echo_api):
    r = run_cli(icl_config(echo_api.url, [COT, DIRECT]), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 1


def test_icl_setups_are_named(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT, DIRECT], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"][0]["icl_setup"] == "chain_of_thought"


def test_spec_canonical_icl_block(run_cli, api):
    """The exact `icl` block from the spec, with k: 2 and round_robin."""
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT, DIRECT], k=2, strategy="round_robin")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"][0]["icl_setup"] == "chain_of_thought"


# "ICL examples are inserted between the system message and the final user
#  message as alternating user and assistant turns"
def test_examples_sit_between_system_and_final_user_message(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    roles = [m["role"] for m in mock.bodies[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]


def test_final_user_message_is_the_rendered_row(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["messages"][-1]["content"] == "What is 2 + 3?"


def test_system_message_is_still_first(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    first = mock.bodies[0]["messages"][0]
    assert first["role"] == "system"
    assert first["content"] == "Solve the math problem. Final answer after ####."


def test_examples_alternate_user_then_assistant(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [tagged("a", 3)], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    middle = mock.bodies[0]["messages"][1:-1]
    assert [m["role"] for m in middle] == ["user", "assistant"] * 3


# "each example's `input` is rendered with the task's `prompt.user` template"
def test_example_input_is_rendered_with_the_user_template(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed")
    cfg["task"]["prompt"]["user"] = "Q: {question}"
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    msgs = mock.bodies[0]["messages"]
    assert msgs[1]["content"] == "Q: What is 2+2?"
    assert msgs[-1]["content"] == "Q: What is 2 + 3?"


def test_example_input_may_use_several_template_fields(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    setup = {"name": "s", "examples": [
        {"input": {"question": "q1", "hint": "h1"}, "output": "#### 4"}]}
    cfg = icl_config(mock.url, [setup], strategy="fixed")
    cfg["task"]["prompt"]["user"] = "{question} // {hint}"
    r = run_cli(cfg, [{"question": "What is 2 + 3?", "hint": "add", "answer": "5"}])
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["messages"][1]["content"] == "q1 // h1"


# "each example's `output` is inserted verbatim as the assistant message"
def test_example_output_is_verbatim(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    assistants = [m["content"] for m in mock.bodies[0]["messages"]
                  if m["role"] == "assistant"]
    assert assistants == [e["output"] for e in COT["examples"]]


def test_example_output_keeps_newlines_and_markers(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    setup = {"name": "s", "examples": [
        {"input": {"question": "q"}, "output": "line one\nline two\n#### 4"}]}
    r = run_cli(icl_config(mock.url, [setup], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["messages"][2]["content"] == "line one\nline two\n#### 4"


# a task with no `prompt.system` still gets the example turns first.
def test_examples_come_first_when_there_is_no_system_message(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("a", 1)], strategy="fixed")
    cfg["task"]["prompt"] = {"user": "{question}"}
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [m["role"] for m in mock.bodies[0]["messages"]] == \
        ["user", "assistant", "user"]


# ---------------------------------------------------------------------------
# "Setups may also come from files"
# "file paths are relative to the config file directory"
# ---------------------------------------------------------------------------

def test_file_backed_setup_is_used(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/gsm8k_detailed.jsonl",
                   [jl("What is 10 / 2?", "10 divided by 2 is 5.\n#### 5")])
    cfg = icl_config(mock.url, [{"name": "detailed",
                                 "file": "icl/gsm8k_detailed.jsonl"}],
                     strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    msgs = mock.bodies[0]["messages"]
    assert msgs[1]["content"] == "What is 10 / 2?"
    assert msgs[2]["content"] == "10 divided by 2 is 5.\n#### 5"


def test_file_path_is_relative_to_the_config_directory(run_cli, api, tmp_path):
    """A bare file name resolves next to the config, not to the CWD."""
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "shots.jsonl", [jl("q-from-file", "a-from-file")])
    cfg = icl_config(mock.url, [{"name": "detailed", "file": "shots.jsonl"}],
                     strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["messages"][1]["content"] == "q-from-file"


def test_file_setup_records_its_name(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", [jl("q", "a")])
    cfg = icl_config(mock.url, [{"name": "detailed", "file": "icl/d.jsonl"}],
                     strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.rows[0]["output"][0]["icl_setup"] == "detailed"


def test_file_setup_keeps_line_order(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl",
                   [jl("q1", "a1"), jl("q2", "a2"), jl("q3", "a3")])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    contents = [m["content"] for m in mock.bodies[0]["messages"][1:-1]]
    assert contents == ["q1", "a1", "q2", "a2", "q3", "a3"]


# T59: "each non-empty line" — blank lines anywhere are skipped.
def test_blank_lines_in_an_icl_file_are_skipped(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl",
                   ["", jl("q1", "a1"), "   ", jl("q2", "a2"), ""])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(mock.bodies[0]["messages"]) == 1 + 4 + 1


# "malformed lines or missing keys must terminate the run with exit code 1
#  before any API requests are sent"
# "malformed line errors include `not valid JSON`"
def test_malformed_icl_line_exits_one_with_not_valid_json(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", [jl("q1", "a1"), "{not json"])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert "not valid JSON" in r.stderr


def test_malformed_icl_line_sends_no_api_requests(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", ["{not json"])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


@pytest.mark.parametrize("line", [
    '{"output": "a"}',                       # missing input
    '{"input": {"question": "q"}}',          # missing output
])
def test_icl_line_missing_a_key_exits_one(run_cli, api, tmp_path, line):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", [line])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


@pytest.mark.parametrize("line", [
    '{"input": "not an object", "output": "a"}',
    '{"input": ["q"], "output": "a"}',
    '{"input": {"question": "q"}, "output": 5}',
    '{"input": {"question": "q"}, "output": {"text": "a"}}',
    '["input", "output"]',
])
def test_icl_line_with_wrong_types_exits_one(run_cli, api, tmp_path, line):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", [line])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_icl_error_names_the_offending_file(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/broken.jsonl", ["nope"])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/broken.jsonl"}],
                     strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert "broken.jsonl" in r.stderr


def test_missing_icl_file_exits_one(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/absent.jsonl"}],
                     strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_an_empty_icl_file_leaves_no_example_turns(run_cli, api, tmp_path):
    """An empty file is valid JSONL with zero examples."""
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", [""])
    cfg = icl_config(mock.url, [{"name": "d", "file": "icl/d.jsonl"}], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [m["role"] for m in mock.bodies[0]["messages"]] == ["system", "user"]
    assert r.rows[0]["output"][0]["icl_setup"] == "d"


# ---------------------------------------------------------------------------
# "each setup has a `name` and exactly one of `examples` or `file`"
# ---------------------------------------------------------------------------

def test_setup_without_a_name_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [{"examples": COT["examples"]}])
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_setup_with_both_examples_and_file_exits_one(run_cli, api, tmp_path):
    mock = api(lambda body, i: (200, completion(PASS)))
    write_icl_file(tmp_path, "icl/d.jsonl", [jl("q", "a")])
    cfg = icl_config(mock.url, [{"name": "d", "examples": COT["examples"],
                                 "file": "icl/d.jsonl"}])
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_setup_with_neither_examples_nor_file_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [{"name": "d"}]), MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_inline_example_missing_output_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [{"name": "d", "examples": [
        {"input": {"question": "q"}}]}])
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_inline_example_with_a_non_string_output_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [{"name": "d", "examples": [
        {"input": {"question": "q"}, "output": 5}]}])
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1


# T57: an `icl` block that declares no usable setups is a config error.
@pytest.mark.parametrize("icl", [
    {"k": 2},                       # no setups key
    {"setups": []},                 # empty list
    {"setups": {"name": "d"}},      # not a list
])
def test_malformed_icl_block_exits_one(run_cli, api, icl):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url)
    cfg["task"]["icl"] = icl
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_icl_that_is_not_a_mapping_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url)
    cfg["task"]["icl"] = ["chain_of_thought"]
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1


# T46: ICL examples must be renderable with `prompt.user`.
def test_icl_without_a_user_template_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT])
    cfg["task"]["prompt"] = {"system": "Solve it."}
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


def test_example_input_missing_a_template_field_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [{"name": "d", "examples": [
        {"input": {"not_question": "q"}, "output": "#### 4"}]}])
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


# ---------------------------------------------------------------------------
# "`icl.k` defaults to all examples in the selected setup"
# "if `k` is smaller than the number of examples in the setup, use the first `k`"
# ---------------------------------------------------------------------------

def test_k_defaults_to_all_examples(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [tagged("a", 4)], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(mock.bodies[0]["messages"]) == 1 + 8 + 1


def test_k_smaller_than_the_setup_uses_the_first_k(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [tagged("a", 4)], k=2, strategy="fixed"),
                MATH_ROWS)
    assert r.code == 0, r.stderr
    contents = [m["content"] for m in mock.bodies[0]["messages"][1:-1]]
    assert contents == ["ex-a-0", "ANS-a-0", "ex-a-1", "ANS-a-1"]


def test_k_of_one_keeps_only_the_first_example(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], k=1, strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    msgs = mock.bodies[0]["messages"]
    assert len(msgs) == 4
    assert msgs[1]["content"] == "What is 2+2?"


# T45: `k` is a cap, so a shorter setup contributes everything it has.
def test_k_larger_than_the_setup_uses_every_example(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [tagged("a", 2)], k=9, strategy="fixed"),
                MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(mock.bodies[0]["messages"]) == 1 + 4 + 1


def test_k_applies_to_the_selected_setup(run_cli, api):
    """Each attempt slices the setup it actually chose."""
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("a", 3), tagged("b", 3)], k=2,
                     strategy="round_robin", num_solutions=2,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["a", "b"]
    for body in mock.bodies:
        assert len(body["messages"]) == 1 + 4 + 1


def test_k_must_be_a_positive_integer(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], k=0), MATH_ROWS)
    assert r.code == 1


def test_k_that_is_not_a_number_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], k="two"), MATH_ROWS)
    assert r.code == 1


# ---------------------------------------------------------------------------
# "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", ["fixed", "random", "round_robin"])
def test_every_documented_strategy_is_accepted(run_cli, api, strategy):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT, DIRECT], strategy=strategy), MATH_ROWS)
    assert r.code == 0, r.stderr


def test_unknown_strategy_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT], strategy="shuffle"), MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


# T44: an omitted strategy behaves as `fixed`.
def test_strategy_defaults_to_fixed(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("a"), tagged("b"), tagged("c")],
                     num_solutions=3,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["a", "a", "a"]


# "`fixed`: always use the first setup"
def test_fixed_always_uses_the_first_setup(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("a"), tagged("b")], strategy="fixed",
                     num_solutions=4,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["a"] * 4
    assert {o["icl_setup"] for o in r.rows[0]["output"]} == {"a"}


def test_fixed_uses_the_first_setup_in_declaration_order(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [DIRECT, COT], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.rows[0]["output"][0]["icl_setup"] == "direct"


# "`round_robin`: cycle through setups in order across attempts"
# Example: setups [A, B, C] -> attempts use A, B, C, A, B
def test_round_robin_cycles_in_declaration_order(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     strategy="round_robin", num_solutions=5,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["A", "B", "C", "A", "B"]


def test_round_robin_is_recorded_per_output_item(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     strategy="round_robin", num_solutions=5,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == \
        ["A", "B", "C", "A", "B"]


def test_round_robin_with_a_single_setup_repeats_it(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A")], strategy="round_robin",
                     num_solutions=3,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert [used(b) for b in mock.bodies] == ["A", "A", "A"]


# T47: the cycle restarts for every input row.
def test_round_robin_restarts_for_each_row(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")],
                     strategy="round_robin", num_solutions=2,
                     generation={"scheme": "sample", "temperature": 0.7})
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(3)]
    r = run_cli(cfg, rows)
    assert r.code == 0, r.stderr
    for row in r.rows:
        assert [o["icl_setup"] for o in row["output"]] == ["A", "B"]


# "`random`: choose a setup independently for each attempt"
def test_random_only_ever_picks_a_declared_setup(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     strategy="random", num_solutions=6,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert set(used(b) for b in mock.bodies) <= {"A", "B", "C"}
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == \
        [used(b) for b in mock.bodies]


def test_random_eventually_uses_more_than_one_setup(run_cli, api):
    """With 30 draws from two setups, both should appear."""
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], strategy="random",
                     num_solutions=30,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert set(used(b) for b in mock.bodies) == {"A", "B"}


# ---------------------------------------------------------------------------
# Multiple Solutions
# "`num_solutions` may be set in `defaults` or per task"
# ---------------------------------------------------------------------------

def test_num_solutions_in_a_single_task_config(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["output"]) == 3


def test_num_solutions_from_defaults(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": {"prompt": {"system": "s", "user": "{question}"},
                  "generation": {"scheme": "sample", "temperature": 0.7},
                  "evaluation": {"type": "exact_match", "answer_field": "answer",
                                 "extract": "last_number"},
                  "output_field": "solution"},
    }, defaults={"num_solutions": 3})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert len(r.rows("gsm8k")[0]["output"]) == 3


def test_task_num_solutions_overrides_defaults(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    base = {"prompt": {"system": "s", "user": "{question}"},
            "generation": {"scheme": "sample", "temperature": 0.7},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution"}
    cfg = make_multi_config(mock.url, {
        "a": dict(base),
        "b": dict(base, num_solutions=4),
    }, defaults={"num_solutions": 2})
    r = run_multi(cfg, {"a": MATH_ROWS, "b": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert len(r.rows("a")[0]["output"]) == 2
    assert len(r.rows("b")[0]["output"]) == 4


# T60: counts are positive integers.
@pytest.mark.parametrize("value", [0, -1, "many"])
def test_invalid_num_solutions_exits_one(run_cli, api, value):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, num_solutions=value)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1
    assert mock.call_count == 0


# ---------------------------------------------------------------------------
# "New flags: --num-solutions, --icl-strategy, --icl-k"
# "CLI flags override config values"
# ---------------------------------------------------------------------------

def test_num_solutions_flag_overrides_the_config(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS, args=["--num-solutions", "4"])
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["output"]) == 4
    assert mock.call_count == 4


def test_num_solutions_flag_without_a_config_value(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS, args=["--num-solutions", "3"])
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["output"]) == 3


def test_icl_strategy_flag_overrides_the_config(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], strategy="fixed",
                     num_solutions=2,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS, args=["--icl-strategy", "round_robin"])
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["A", "B"]


def test_icl_k_flag_overrides_the_config(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A", 4)], k=4, strategy="fixed")
    r = run_cli(cfg, MATH_ROWS, args=["--icl-k", "1"])
    assert r.code == 0, r.stderr
    assert len(mock.bodies[0]["messages"]) == 1 + 2 + 1


def test_icl_strategy_flag_rejects_an_unknown_value(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(icl_config(mock.url, [COT]), MATH_ROWS,
                args=["--icl-strategy", "spiral"])
    assert r.code == 1


# T58: the ICL flags are inert for a task that declares no setups.
def test_icl_flags_do_not_create_icl_for_a_plain_task(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(make_config(mock.url), MATH_ROWS,
                args=["--icl-k", "2", "--icl-strategy", "round_robin"])
    assert r.code == 0, r.stderr
    assert [m["role"] for m in mock.bodies[0]["messages"]] == ["system", "user"]
    assert r.rows[0]["output"] == {"solution": PASS}


def test_cli_flags_apply_to_every_selected_task(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    base = {"prompt": {"system": "s", "user": "{question}"},
            "generation": {"scheme": "sample", "temperature": 0.7},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution"}
    cfg = make_multi_config(mock.url, {"a": dict(base), "b": dict(base)})
    r = run_multi(cfg, {"a": MATH_ROWS, "b": MATH_ROWS},
                  args=["--num-solutions", "2"])
    assert r.code == 0, r.stderr
    assert len(r.rows("a")[0]["output"]) == 2
    assert len(r.rows("b")[0]["output"]) == 2


# ---------------------------------------------------------------------------
# "`max_attempts` applies to rejection sampling in this part"
# "if `max_attempts` is omitted for rejection, default it to 3 * num_solutions"
# ---------------------------------------------------------------------------

def test_max_attempts_bounds_rejection(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=4),
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 4
    assert r.rows[0]["result"]["attempts"] == 4


def test_max_attempts_defaults_to_three_times_num_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(), num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 6
    assert r.rows[0]["result"]["attempts"] == 6


def test_max_attempts_default_with_icl(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [COT], strategy="fixed", num_solutions=3,
                     generation=rejection())
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 9


# T49: `generation.n` no longer bounds attempts once the new mode is active.
def test_generation_n_does_not_cap_the_new_rejection_loop(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(n=2, max_attempts=7),
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 7


# T56: greedy and sample are not bounded by max_attempts.
def test_max_attempts_does_not_bound_sample(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, num_solutions=4,
                      generation={"scheme": "sample", "temperature": 0.7,
                                  "max_attempts": 2})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 4


def test_invalid_max_attempts_exits_one(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=0),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1


# ---------------------------------------------------------------------------
# "legacy compatibility: when num_solutions == 1 and no ICL is configured, keep
#  the Part 1 rejection behavior (generation.n logical attempts) and do not
#  apply max_attempts"
# ---------------------------------------------------------------------------

def test_legacy_rejection_uses_n_logical_attempts(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    r = run_cli(make_config(mock.url, generation=rejection(n=3)), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 3
    assert r.rows[0]["result"]["attempts"] == 3


# T61: an explicit max_attempts is ignored in the legacy case.
def test_legacy_rejection_ignores_max_attempts(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    r = run_cli(make_config(mock.url, generation=rejection(n=4, max_attempts=2)),
                MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 4


def test_legacy_rejection_stops_at_the_first_pass(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL if i == 0 else PASS)))
    r = run_cli(make_config(mock.url, generation=rejection(n=5)), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 2
    assert r.rows[0]["result"]["passed"] is True


def test_legacy_rejection_keeps_the_part_one_row_shape(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(make_config(mock.url, generation=rejection(n=3)), MATH_ROWS)
    row = r.rows[0]
    assert row["output"] == {"solution": PASS}
    assert set(row["result"]) == {"passed", "extracted_answer", "attempts"}
    assert isinstance(row["meta"], dict)


def test_explicit_num_solutions_one_without_icl_is_legacy(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation=rejection(n=3), num_solutions=1)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"solution": PASS}


# ---------------------------------------------------------------------------
# Scheme behavior when num_solutions > 1
# "greedy with ICL: generate at temperature 0 once per selected setup and stop
#  when num_solutions solutions are collected or all setups are exhausted"
# ---------------------------------------------------------------------------

def test_greedy_icl_generates_once_per_setup(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["A", "B", "C"]
    assert len(r.rows[0]["output"]) == 3


def test_greedy_icl_uses_temperature_zero(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert {b["temperature"] for b in mock.bodies} == {0.0}


def test_greedy_icl_stops_once_num_solutions_are_collected(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 2
    assert [used(b) for b in mock.bodies] == ["A", "B"]


# "because the same setup is deterministic, the maximum number of produced
#  solutions is the number of available setups"
# "Greedy cap: if there are two setups and num_solutions: 5, produce at most
#  two solutions"
def test_greedy_cap_is_the_number_of_setups(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], num_solutions=5)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["output"]) == 2


# "do not retry the same greedy setup to manufacture additional outputs"
def test_greedy_does_not_retry_a_setup(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], num_solutions=5)
    r = run_cli(cfg, MATH_ROWS)
    assert mock.call_count == 2
    assert sorted(used(b) for b in mock.bodies) == ["A", "B"]
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == ["A", "B"]


# "selection ignores the above strategy and instead walks setups in declared
#  order, at most once per setup"
@pytest.mark.parametrize("strategy", ["fixed", "random", "round_robin"])
def test_greedy_ignores_the_strategy_and_walks_declared_order(run_cli, api, strategy):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     strategy=strategy, num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["A", "B", "C"]


def test_greedy_icl_emits_failing_solutions_too(run_cli, api):
    """Greedy is not gated by evaluation, so both setups contribute output."""
    mock = api(lambda body, i: (200, completion(PASS if i == 0 else FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["output"]) == 2
    assert r.rows[0]["result"] == {"passed": 1, "failed": 1, "attempts": 2}


# T48: a greedy task with no ICL has exactly one deterministic prompt.
def test_greedy_without_icl_produces_one_solution(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, num_solutions=4)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 1
    assert len(r.rows[0]["output"]) == 1
    assert r.rows[0]["output"][0]["icl_setup"] is None


# ---------------------------------------------------------------------------
# "sample with ICL: make one sampled generation per requested solution using
#  the chosen ICL strategy; evaluation does not gate whether a solution is
#  included"
# ---------------------------------------------------------------------------

def test_sample_icl_makes_one_request_per_solution(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], strategy="round_robin",
                     num_solutions=4,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 4
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == ["A", "B", "A", "B"]


def test_sample_icl_includes_failing_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A")], strategy="fixed", num_solutions=3,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["output"]) == 3
    assert r.rows[0]["result"] == {"passed": 0, "failed": 3, "attempts": 3}


def test_sample_icl_uses_the_configured_temperature(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A")], strategy="fixed", num_solutions=2,
                     generation={"scheme": "sample", "temperature": 0.9})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert {b["temperature"] for b in mock.bodies} == {0.9}


def test_sample_icl_still_reports_evaluation_results(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS if i % 2 == 0 else FAIL)))
    cfg = icl_config(mock.url, [tagged("A")], strategy="fixed", num_solutions=4,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert [m["evaluation_passed"] for m in r.rows[0]["meta"]] == \
        [True, False, True, False]
    assert r.rows[0]["result"] == {"passed": 2, "failed": 2, "attempts": 4}


# "sample without ICL: make num_solutions independent sampled requests"
def test_sample_without_icl_makes_num_solutions_requests(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=5)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 5
    assert len(r.rows[0]["output"]) == 5


def test_sample_without_icl_sends_the_same_prompt_each_time(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert all(b["messages"] == mock.bodies[0]["messages"] for b in mock.bodies)
    assert all(len(b["messages"]) == 2 for b in mock.bodies)


# T55: sample is not gated by evaluation with or without ICL.
def test_sample_without_icl_includes_failing_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert len(r.rows[0]["output"]) == 3
    assert r.rows[0]["result"]["passed"] == 0


def test_sample_without_icl_records_a_null_setup(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == [None, None]
    assert [m["icl_setup"] for m in r.rows[0]["meta"]] == [None, None]


# ---------------------------------------------------------------------------
# "rejection with ICL: keep generating and evaluating until num_solutions
#  passing solutions have been collected or max_attempts is exhausted"
# ---------------------------------------------------------------------------

def test_rejection_stops_once_enough_solutions_pass(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [tagged("A")], strategy="fixed", num_solutions=3,
                     generation=rejection(max_attempts=10))
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 3
    assert r.rows[0]["result"] == {"passed": 3, "failed": 0, "attempts": 3}


def test_rejection_only_keeps_passing_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS if i % 2 == 0 else FAIL)))
    cfg = icl_config(mock.url, [tagged("A")], strategy="fixed", num_solutions=2,
                     generation=rejection(max_attempts=10))
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 3
    assert [o["solution"] for o in r.rows[0]["output"]] == [PASS, PASS]
    assert r.rows[0]["result"] == {"passed": 2, "failed": 1, "attempts": 3}


def test_rejection_with_icl_follows_the_strategy(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], strategy="round_robin",
                     num_solutions=2, generation=rejection(max_attempts=4))
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [used(b) for b in mock.bodies] == ["A", "B", "A", "B"]


def test_rejection_records_the_setup_of_each_passing_solution(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL if i == 0 else PASS)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B"), tagged("C")],
                     strategy="round_robin", num_solutions=2,
                     generation=rejection(max_attempts=10))
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == ["B", "C"]


# "rejection without ICL: same as above, but every attempt uses the same prompt"
def test_rejection_without_icl_repeats_one_prompt(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=4),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert all(b["messages"] == mock.bodies[0]["messages"] for b in mock.bodies)
    assert all(len(b["messages"]) == 2 for b in mock.bodies)


def test_rejection_without_icl_collects_several_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=10),
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert len(r.rows[0]["output"]) == 3
    assert all(o["icl_setup"] is None for o in r.rows[0]["output"])


# "Rejection partial result: if num_solutions: 5 and max_attempts: 10 and only
#  two attempts pass before the tenth attempt, write only those two passing
#  outputs; report passed: 2, failed: 8, and attempts: 10"
def test_rejection_partial_result(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS if i in (2, 6) else FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=10),
                      num_solutions=5)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 10
    row = r.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}


def test_rejection_with_no_passing_attempt_writes_an_empty_list(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=3),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == []
    assert r.rows[0]["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# ---------------------------------------------------------------------------
# Output Changes
# "If ICL is configured or num_solutions > 1, the per-row output format changes"
# "output becomes a list of objects, each containing the task's output_field
#  plus icl_setup"
# ---------------------------------------------------------------------------

def test_output_is_a_list_of_objects(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    out = r.rows[0]["output"]
    assert isinstance(out, list)
    assert out == [{"solution": PASS, "icl_setup": "chain_of_thought"}]


def test_output_item_uses_the_task_output_field(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed", output_field="answer_text")
    r = run_cli(cfg, MATH_ROWS)
    assert set(r.rows[0]["output"][0]) == {"answer_text", "icl_setup"}


def test_output_item_keys_are_exactly_field_and_setup(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    for item in r.rows[0]["output"]:
        assert set(item) == {"solution", "icl_setup"}


# "icl_setup is the chosen setup name, or null when no ICL is configured"
def test_icl_setup_is_null_without_icl(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=5),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert all(o["icl_setup"] is None for o in r.rows[0]["output"])
    assert all(m["icl_setup"] is None for m in r.rows[0]["meta"])


def test_icl_setup_is_the_chosen_name(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT, DIRECT], strategy="round_robin",
                     num_solutions=2,
                     generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert [o["icl_setup"] for o in r.rows[0]["output"]] == \
        ["chain_of_thought", "direct"]


# "when num_solutions == 1 and no ICL is configured, keep the Part 1 output
#  format"
def test_plain_single_solution_task_keeps_the_part_one_format(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    row = r.rows[0]
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert isinstance(row["meta"], dict)
    assert set(row["result"]) == {"passed", "extracted_answer", "attempts"}


def test_part_one_format_has_no_icl_setup_key(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert "icl_setup" not in r.rows[0]["output"]
    assert "icl_setup" not in r.rows[0]["meta"]


# "when ICL is configured, use the list format even if num_solutions == 1"
def test_icl_with_one_solution_still_uses_the_list_format(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed", num_solutions=1)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert isinstance(row["output"], list) and len(row["output"]) == 1
    assert isinstance(row["meta"], list) and len(row["meta"]) == 1


# "Single-solution ICL run: the single output item records the chosen
#  icl_setup; meta is also a list and includes evaluation_passed"
def test_single_solution_icl_run_records_setup_and_evaluation(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [DIRECT, COT], strategy="fixed", num_solutions=1)
    r = run_cli(cfg, MATH_ROWS)
    row = r.rows[0]
    assert row["output"][0]["icl_setup"] == "direct"
    assert row["meta"][0]["icl_setup"] == "direct"
    assert row["meta"][0]["evaluation_passed"] is True


def test_num_solutions_greater_than_one_without_icl_uses_the_list_format(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert isinstance(r.rows[0]["output"], list)
    assert isinstance(r.rows[0]["meta"], list)


# ---------------------------------------------------------------------------
# "result.passed is the count of passing solutions"
# "result.failed is the count of failed attempts"
# "result.attempts is the total number of generation attempts for the row"
# ---------------------------------------------------------------------------

def test_result_counts_are_integers(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS if i in (0, 2) else FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=4),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    res = r.rows[0]["result"]
    assert res == {"passed": 2, "failed": 1, "attempts": 3}
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in res.values())


# T50: the list format's result object carries exactly these three keys.
def test_result_key_set_in_list_format(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert set(r.rows[0]["result"]) == {"passed", "failed", "attempts"}


# T63: passed + failed == attempts.
def test_passed_plus_failed_equals_attempts(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS if i % 3 == 0 else FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=7),
                      num_solutions=9)
    r = run_cli(cfg, MATH_ROWS)
    res = r.rows[0]["result"]
    assert res["passed"] + res["failed"] == res["attempts"] == 7


def test_result_matches_the_spec_example_shape(run_cli, api):
    """The spec's example row: two kept solutions out of seven attempts."""
    mock = api(lambda body, i: (200, completion(PASS if i in (0, 1) else FAIL)))
    cfg = icl_config(mock.url, [COT, DIRECT], strategy="round_robin",
                     num_solutions=2, generation=rejection(max_attempts=7))
    r = run_cli(cfg, MATH_ROWS)
    row = r.rows[0]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [o["icl_setup"] for o in row["output"]] == ["chain_of_thought", "direct"]


# ---------------------------------------------------------------------------
# "meta is a list with one entry per attempt"
# "each metadata entry includes icl_setup and evaluation_passed"
# ---------------------------------------------------------------------------

def test_meta_has_one_entry_per_attempt(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=4),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert len(r.rows[0]["meta"]) == r.rows[0]["result"]["attempts"] == 4


def test_meta_entry_keeps_the_part_one_fields(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    entry = r.rows[0]["meta"][0]
    assert set(entry) == {"model", "prompt_tokens", "completion_tokens",
                          "total_tokens", "latency_ms", "finish_reason",
                          "icl_setup", "evaluation_passed"}
    assert entry["model"] == "gpt-4"
    assert entry["prompt_tokens"] == 30
    assert entry["completion_tokens"] == 10
    assert entry["total_tokens"] == 40
    assert entry["finish_reason"] == "stop"
    assert isinstance(entry["latency_ms"], int)


def test_meta_evaluation_passed_tracks_each_attempt(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL if i < 2 else PASS)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=6),
                      num_solutions=1)
    cfg["task"]["icl"] = {"setups": [COT], "strategy": "fixed"}
    r = run_cli(cfg, MATH_ROWS)
    assert [m["evaluation_passed"] for m in r.rows[0]["meta"]] == \
        [False, False, True]


def test_meta_records_the_setup_of_every_attempt(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = icl_config(mock.url, [tagged("A"), tagged("B")], strategy="round_robin",
                     num_solutions=2, generation=rejection(max_attempts=3))
    r = run_cli(cfg, MATH_ROWS)
    assert [m["icl_setup"] for m in r.rows[0]["meta"]] == ["A", "B", "A"]


# "if evaluation is omitted in list format, evaluation_passed is null for each
#  metadata entry, result.passed is the number of emitted outputs, and
#  result.failed is the number of attempts that produced no output"
def test_without_evaluation_evaluation_passed_is_null(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, evaluation=None, num_solutions=3,
                      generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert [m["evaluation_passed"] for m in r.rows[0]["meta"]] == [None, None, None]


def test_without_evaluation_passed_counts_emitted_outputs(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, evaluation=None, num_solutions=3,
                      generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.rows[0]["result"] == {"passed": 3, "failed": 0, "attempts": 3}


def test_without_evaluation_failed_counts_attempts_with_no_output(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)) if i != 1 else (400, {"error": "no"}))
    cfg = make_config(mock.url, evaluation=None, num_solutions=3,
                      generation={"scheme": "sample", "temperature": 0.7})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


def test_without_evaluation_icl_still_uses_the_list_format(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed", evaluation=None)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == [{"solution": PASS, "icl_setup": "chain_of_thought"}]
    assert r.rows[0]["meta"][0]["evaluation_passed"] is None


# ---------------------------------------------------------------------------
# "Per-task summary fields gain: total_solutions, avg_solutions_per_input"
# ---------------------------------------------------------------------------

def sample_task(**over):
    base = {"prompt": {"system": "s", "user": "{question}"},
            "generation": {"scheme": "sample", "temperature": 0.7},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution"}
    base.update(over)
    return base


def test_per_task_summary_gains_solution_counts(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {"gsm8k": sample_task(num_solutions=3)})
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(2)]
    r = run_multi(cfg, {"gsm8k": rows})
    assert r.code == 0, r.stderr
    task_summary = r.summary["tasks"]["gsm8k"]
    assert task_summary["total"] == 2
    assert task_summary["total_solutions"] == 6
    assert task_summary["avg_solutions_per_input"] == 3.0
    assert task_summary["total_api_calls"] == 6


def test_avg_solutions_per_input_is_fractional(run_multi, api):
    """Two rows, three solutions between them."""
    mock = api(lambda body, i: (200, completion(PASS if i < 3 else FAIL)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": sample_task(num_solutions=2,
                             generation=rejection(max_attempts=2))})
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(2)]
    r = run_multi(cfg, {"gsm8k": rows})
    assert r.code == 0, r.stderr
    task_summary = r.summary["tasks"]["gsm8k"]
    assert task_summary["total_solutions"] == 3
    assert task_summary["avg_solutions_per_input"] == 1.5


# T52: passed/failed still count input rows.
def test_per_task_passed_and_failed_still_count_rows(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS if i % 2 == 0 else FAIL)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": sample_task(num_solutions=1,
                             generation=rejection(max_attempts=1))})
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(2)]
    r = run_multi(cfg, {"gsm8k": rows})
    assert r.code == 0, r.stderr
    task_summary = r.summary["tasks"]["gsm8k"]
    assert task_summary["passed"] + task_summary["failed"] == 2


def test_per_task_summary_key_set(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {"gsm8k": sample_task(num_solutions=2)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert set(r.summary["tasks"]["gsm8k"]) == {
        "total", "passed", "failed", "total_solutions",
        "avg_solutions_per_input", "total_api_calls"}


# T64: single-solution tasks report one solution per produced output.
def test_solution_counts_for_a_legacy_task(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": sample_task(generation={"scheme": "greedy"})})
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(3)]
    r = run_multi(cfg, {"gsm8k": rows})
    assert r.code == 0, r.stderr
    assert r.summary["tasks"]["gsm8k"]["total_solutions"] == 3
    assert r.summary["tasks"]["gsm8k"]["avg_solutions_per_input"] == 1.0


def test_total_api_calls_counts_every_attempt(run_multi, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": sample_task(num_solutions=2,
                             generation=rejection(max_attempts=5))})
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(2)]
    r = run_multi(cfg, {"gsm8k": rows})
    assert r.code == 0, r.stderr
    assert r.summary["tasks"]["gsm8k"]["total_api_calls"] == 10
    assert r.summary["total_api_calls"] == 10


# T53: the top-level summary keeps its Part 1 key set.
def test_top_level_summary_keys_are_unchanged(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed", num_solutions=1)
    r = run_cli(cfg, MATH_ROWS)
    assert set(r.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm"}


def test_summary_tokens_include_every_attempt(run_cli, api):
    mock = api(lambda body, i: (200, completion(FAIL)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=3),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.summary["total_prompt_tokens"] == 90
    assert r.summary["total_completion_tokens"] == 30


def test_summary_counts_a_multi_solution_row_once(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=3)
    r = run_cli(cfg, MATH_ROWS)
    assert r.summary["total"] == 1
    assert r.summary["passed"] + r.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Interaction with earlier parts
# "Existing behavior from earlier parts is unchanged unless stated here."
# ---------------------------------------------------------------------------

def test_icl_applies_per_task_in_a_multi_task_config(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {
        "with_icl": sample_task(icl={"setups": [tagged("A")], "strategy": "fixed"},
                                generation={"scheme": "greedy"}),
        "plain": sample_task(generation={"scheme": "greedy"}),
    })
    r = run_multi(cfg, {"with_icl": MATH_ROWS, "plain": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert r.rows("with_icl")[0]["output"] == [{"solution": PASS, "icl_setup": "A"}]
    assert r.rows("plain")[0]["output"] == {"solution": PASS}


def test_icl_may_come_from_defaults(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(
        mock.url, {"gsm8k": sample_task(generation={"scheme": "greedy"})},
        defaults={"icl": {"setups": [tagged("A")], "strategy": "fixed"}})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert r.rows("gsm8k")[0]["output"][0]["icl_setup"] == "A"


def test_icl_file_in_a_multi_task_config_resolves_beside_the_config(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": sample_task(generation={"scheme": "greedy"},
                             icl={"setups": [{"name": "d", "file": "icl/shots.jsonl"}],
                                  "strategy": "fixed"})})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS},
                  files={"icl/shots.jsonl": jl("q-from-file", "a-from-file") + "\n"})
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["messages"][1]["content"] == "q-from-file"


def test_icl_error_in_one_task_fails_the_run(run_multi, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_multi_config(mock.url, {
        "good": sample_task(generation={"scheme": "greedy"}),
        "bad": sample_task(generation={"scheme": "greedy"},
                           icl={"setups": [{"name": "d"}]}),
    })
    r = run_multi(cfg, {"good": MATH_ROWS, "bad": MATH_ROWS})
    assert r.code == 1
    assert mock.call_count == 0


# T51: a dead request is one failed attempt; the row keeps its budget.
def test_hard_http_failure_is_one_failed_attempt(run_cli, api):
    def responder(body, i):
        if i < 3:                       # attempt 1 exhausts its three retries
            return 500, {"error": "boom"}
        return 200, completion(PASS)

    mock = api(responder)
    cfg = make_config(mock.url, generation=rejection(max_attempts=3),
                      num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


def test_hard_http_failure_still_gets_a_meta_entry(run_cli, api):
    def responder(body, i):
        if i < 3:
            return 500, {"error": "boom"}
        return 200, completion(PASS)

    mock = api(responder)
    cfg = make_config(mock.url, generation=rejection(max_attempts=3),
                      num_solutions=2)
    row = run_cli(cfg, MATH_ROWS).rows[0]
    assert len(row["meta"]) == row["result"]["attempts"] == 3
    assert row["meta"][0]["prompt_tokens"] is None
    assert row["meta"][0]["finish_reason"] is None


# Part 2 evaluation types keep working under multiple solutions.
def test_llm_judge_with_multiple_solutions(run_cli, api):
    mock = judge_split(api, PASS, "9")
    cfg = make_config(
        mock.url, generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=2,
        evaluation={"type": "llm_judge", "threshold": 7,
                    "judge_prompt": {
                        "system": "You are a quality evaluator.",
                        "user": "Rate:\n{__response__}"}})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert len(row["output"]) == 2
    assert [m["evaluation_passed"] for m in row["meta"]] == [True, True]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}


# T62: judge requests do not receive the ICL example turns.
def test_judge_prompt_has_no_icl_examples(run_cli, api):
    mock = judge_split(api, PASS, "9")
    cfg = icl_config(
        mock.url, [tagged("A")], strategy="fixed",
        evaluation={"type": "llm_judge", "threshold": 7,
                    "judge_prompt": {
                        "system": "You are a quality evaluator.",
                        "user": "Rate:\n{__response__}"}})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    judge_bodies = [b for b in mock.bodies
                    if "evaluator" in b["messages"][0]["content"]]
    assert judge_bodies
    for body in judge_bodies:
        assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_script_evaluation_with_multiple_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion("good code" if i % 2 == 0 else "bad")))
    cfg = make_config(
        mock.url, generation=rejection(max_attempts=4), num_solutions=2,
        evaluation={"type": "script",
                    "command_template": "echo '{__response__}' | grep -q 'good code'"})
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"] == {"passed": 2, "failed": 1, "attempts": 3}


def test_rows_stay_in_input_order_with_multiple_solutions(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation={"scheme": "sample", "temperature": 0.7},
                      num_solutions=2)
    rows = [dict(MATH_ROWS[0], question="q%d" % i) for i in range(4)]
    r = run_cli(cfg, rows)
    assert [row["input"]["question"] for row in r.rows] == \
        ["q0", "q1", "q2", "q3"]


def test_input_is_echoed_unchanged(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert r.rows[0]["input"] == MATH_ROWS[0]


def test_row_key_set_is_unchanged_in_list_format(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = icl_config(mock.url, [COT], strategy="fixed")
    r = run_cli(cfg, MATH_ROWS)
    assert set(r.rows[0]) == {"input", "output", "result", "meta"}


def test_rejection_without_evaluation_is_still_an_error(run_cli, api):
    mock = api(lambda body, i: (200, completion(PASS)))
    cfg = make_config(mock.url, generation=rejection(max_attempts=3),
                      evaluation=None, num_solutions=2)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 1


def test_icl_examples_do_not_have_to_pass_evaluation(run_cli, api):
    """Example outputs are prompt material, never evaluated."""
    mock = api(lambda body, i: (200, completion(PASS)))
    setup = {"name": "s", "examples": [
        {"input": {"question": "q"}, "output": "no answer marker here"}]}
    r = run_cli(icl_config(mock.url, [setup], strategy="fixed"), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] == 1
