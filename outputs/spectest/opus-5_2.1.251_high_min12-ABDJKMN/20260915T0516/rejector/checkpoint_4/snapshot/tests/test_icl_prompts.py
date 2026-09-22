"""Part 3: where ICL example turns go and how they are rendered."""
import json

from conftest import icl_block, icl_setup, make_config, marker_setups
from mock_api import MockAPI, always

ROWS = [{"question": "2+2?", "answer": "4"}]


def roles(payload):
    return [m["role"] for m in payload["messages"]]


def contents(payload):
    return [m["content"] for m in payload["messages"]]


# Spec: "ICL examples are inserted between the system message and the final
#        user message as alternating user and assistant turns"
# Context: ICL Configuration rules.
def test_examples_sit_between_system_and_the_final_user_turn(run_tool):
    setups = marker_setups(["A"], per_setup=2)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl_block(setups)),
                       ROWS)
    assert run.returncode == 0, run.stderr
    payload = api.calls[0]
    assert roles(payload) == ["system", "user", "assistant", "user",
                              "assistant", "user"]
    assert payload["messages"][0]["content"].startswith("Solve the math")
    assert payload["messages"][-1]["content"] == "2+2?"


def test_examples_alternate_user_then_assistant(run_tool):
    setups = marker_setups(["A"], per_setup=3)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl_block(setups)),
                       ROWS)
    assert run.returncode == 0, run.stderr
    body = api.calls[0]["messages"][1:-1]
    assert [m["role"] for m in body] == ["user", "assistant"] * 3
    assert [m["content"] for m in body] == [
        "demo A 0", "MARK_A0", "demo A 1", "MARK_A1", "demo A 2", "MARK_A2"]


# Spec: "ICL examples are inserted between the system message and ..." with no
#        system message configured.
def test_examples_lead_the_conversation_when_there_is_no_system_message(run_tool):
    setups = marker_setups(["A"], per_setup=1)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, system=None,
                                   icl=icl_block(setups)), ROWS)
    assert run.returncode == 0, run.stderr
    assert roles(api.calls[0]) == ["user", "assistant", "user"]
    assert contents(api.calls[0]) == ["demo A 0", "MARK_A0", "2+2?"]


# Spec: "each example's `input` is rendered with the task's `prompt.user`
#        template"
# Context: ICL Configuration rules.
def test_example_input_is_rendered_through_the_user_template(run_tool):
    icl = icl_block([icl_setup("s", examples=[({"question": "What is 2+2?"},
                                               "#### 4")])])
    config = make_config(api_url="", icl=icl,
                         user="Question: {question}\nAnswer:")
    with MockAPI(always("#### 4")) as api:
        config["task"]["api_url"] = api.url
        run = run_tool(config, ROWS)
    assert run.returncode == 0, run.stderr
    users = [m["content"] for m in api.calls[0]["messages"]
             if m["role"] == "user"]
    assert users == ["Question: What is 2+2?\nAnswer:",
                     "Question: 2+2?\nAnswer:"]


def test_example_input_may_fill_several_placeholders(run_tool):
    icl = icl_block([icl_setup(
        "s", examples=[({"question": "q1", "hint": "h1"}, "out")])])
    rows = [{"question": "2+2?", "hint": "add", "answer": "4"}]
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl,
                                   user="{question} [{hint}]"), rows)
    assert run.returncode == 0, run.stderr
    users = [m["content"] for m in api.calls[0]["messages"]
             if m["role"] == "user"]
    assert users == ["q1 [h1]", "2+2? [add]"]


# Spec: "each example's `output` is inserted verbatim as the assistant
#        message"
# Context: ICL Configuration rules.
def test_example_output_is_verbatim(run_tool):
    text = "Let me think step by step.\n2 + 2 = 4\n#### 4  {question}"
    icl = icl_block([icl_setup("s", examples=[({"question": "x"}, text)])])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 0, run.stderr
    assistants = [m["content"] for m in api.calls[0]["messages"]
                  if m["role"] == "assistant"]
    assert assistants == [text]


# The ICL prefix is identical for every input row: examples are rendered from
# their own `input`, never from the row.
def test_every_row_receives_the_same_example_turns(run_tool):
    setups = marker_setups(["A"], per_setup=1)
    rows = [{"question": "a", "answer": "4"}, {"question": "b", "answer": "4"}]
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl_block(setups)),
                       rows)
    assert run.returncode == 0, run.stderr
    prefixes = [json.dumps(c["messages"][:-1], sort_keys=True)
                for c in api.calls]
    assert len(set(prefixes)) == 1
    assert sorted(c["messages"][-1]["content"] for c in api.calls) == ["a", "b"]
