"""Part 3: how ICL examples are turned into chat messages."""

import fake_api

from test_icl_config import icl, inline_setup


TWO_EXAMPLES = icl([{
    "name": "chain_of_thought",
    "examples": [
        {"input": {"question": "What is 2+2?"},
         "output": "Let me think step by step.\n2 + 2 = 4\n#### 4"},
        {"input": {"question": "If I have 3 cats and get 2 more, how many "
                               "cats do I have?"},
         "output": "Step by step:\nI start with 3 cats.\nI get 2 more.\n"
                   "3 + 2 = 5\n#### 5"},
    ],
}])


# ---------------------------------------------------------------------------
# Spec: "ICL examples are inserted between the system message and the final
#        user message as alternating user and assistant turns"
# Context: ICL Configuration.  Message roles for a two-example setup.
# ---------------------------------------------------------------------------
def test_examples_are_alternating_user_assistant_turns(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"icl": TWO_EXAMPLES}, check=0)
    assert api.requests[0].roles == [
        "system", "user", "assistant", "user", "assistant", "user"]


# ---------------------------------------------------------------------------
# Spec: "ICL examples are inserted between the system message and the final
#        user message"
# Context: ICL Configuration.  The system message stays first and the row's own
# user message stays last.
# ---------------------------------------------------------------------------
def test_examples_sit_between_the_system_and_the_final_user_message(run_task):
    rows = [{"question": "What is 15 + 27?", "answer": "42"}]
    with fake_api.FakeAPI(fake_api.always("#### 42")) as api:
        run_task(api, task={"icl": TWO_EXAMPLES}, rows=rows, check=0)
    messages = api.requests[0].messages
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("Solve the math problem")
    assert messages[-1] == {"role": "user", "content": "What is 15 + 27?"}


# ---------------------------------------------------------------------------
# Spec: "each example's `input` is rendered with the task's `prompt.user`
#        template"
# Context: ICL Configuration.
# ---------------------------------------------------------------------------
def test_example_input_is_rendered_with_the_user_template(run_task):
    task = {"prompt": {"user": "Question: {question}\nAnswer:"},
            "icl": TWO_EXAMPLES}
    rows = [{"question": "What is 15 + 27?", "answer": "42"}]
    with fake_api.FakeAPI(fake_api.always("#### 42")) as api:
        run_task(api, task=task, rows=rows, check=0)
    assert api.requests[0].user_contents == [
        "Question: What is 2+2?\nAnswer:",
        "Question: If I have 3 cats and get 2 more, how many cats do I "
        "have?\nAnswer:",
        "Question: What is 15 + 27?\nAnswer:",
    ]


# ---------------------------------------------------------------------------
# Spec: "each example's `output` is inserted verbatim as the assistant message"
# Context: ICL Configuration.  No extraction, trimming or re-wrapping.
# ---------------------------------------------------------------------------
def test_example_output_is_verbatim_assistant_content(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"icl": TWO_EXAMPLES}, check=0)
    assert api.requests[0].assistant_contents == [
        "Let me think step by step.\n2 + 2 = 4\n#### 4",
        "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5",
    ]


# ---------------------------------------------------------------------------
# Spec: "ICL examples are inserted between the system message and the final
#        user message"
# Context: ICL Configuration; T57.  With no `prompt.system` the examples lead.
# ---------------------------------------------------------------------------
def test_without_a_system_message_the_examples_lead(run_task):
    task = {"prompt": {"system": None}, "icl": TWO_EXAMPLES}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.requests[0].roles == [
        "user", "assistant", "user", "assistant", "user"]


# ---------------------------------------------------------------------------
# Spec: "if `k` is smaller than the number of examples in the setup, use the
#        first `k`"
# Context: ICL Configuration.  `k` shortens the turn sequence itself.
# ---------------------------------------------------------------------------
def test_k_shortens_the_message_sequence(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1", "ex-2", "ex-3")], k=1)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.requests[0].roles == ["system", "user", "assistant", "user"]
    assert api.requests[0].assistant_contents == ["ex-1"]


# ---------------------------------------------------------------------------
# Spec: "each example's `input` is rendered with the task's `prompt.user`
#        template"
# Context: ICL Configuration; T55.  An example whose input does not cover the
# template renders leniently rather than failing the run.
# ---------------------------------------------------------------------------
def test_example_input_missing_a_template_field_renders_leniently(run_task):
    task = {"prompt": {"user": "{question} ({difficulty})"},
            "icl": icl([{"name": "cot",
                         "examples": [{"input": {"question": "2+2?"},
                                       "output": "#### 4"}]}])}
    rows = [{"question": "15+27?", "answer": "42", "difficulty": "easy"}]
    with fake_api.FakeAPI(fake_api.always("#### 42")) as api:
        run_task(api, task=task, rows=rows, check=0)
    assert api.requests[0].user_contents == ["2+2? ({difficulty})",
                                             "15+27? (easy)"]


# ---------------------------------------------------------------------------
# Spec: "Existing behavior from earlier parts is unchanged unless stated here."
# Context: A task with no `icl` block still sends system + user only.
# ---------------------------------------------------------------------------
def test_without_icl_the_prompt_is_unchanged(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, check=0)
    assert api.requests[0].roles == ["system", "user"]


# ---------------------------------------------------------------------------
# Spec: "ICL examples are inserted between the system message and the final
#        user message"
# Context: ICL Configuration.  Every attempt of a multi-attempt row carries the
# examples of the setup chosen for that attempt.
# ---------------------------------------------------------------------------
def test_every_attempt_carries_its_setups_examples(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1", "ex-2")]),
            "num_solutions": 3,
            "generation": {"scheme": "sample", "temperature": 0.7}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.call_count == 3
    for rec in api.requests:
        assert rec.assistant_contents == ["ex-1", "ex-2"]
