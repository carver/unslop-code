"""Prompt template rendering, the request payload, and input validation."""
import json

import pytest

from conftest import make_config
from mock_api import MockAPI, always


# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
#        each input row."
# Context: Configuration.
def test_user_placeholder_resolved_from_row(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, user="{question}"),
                       [{"question": "What is 2 + 3?", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    user = [m for m in api.calls[0]["messages"] if m["role"] == "user"][0]
    assert user["content"] == "What is 2 + 3?"


def test_system_placeholder_resolved_from_row(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   system="You are a {persona}.",
                                   user="{question}"),
                       [{"question": "q", "answer": "5", "persona": "tutor"}])
    assert run.returncode == 0, run.stderr
    system = [m for m in api.calls[0]["messages"] if m["role"] == "system"][0]
    assert system["content"] == "You are a tutor."


def test_multiple_and_repeated_placeholders(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   user="{a} then {b} then {a}"),
                       [{"a": "X", "b": "Y", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    user = [m for m in api.calls[0]["messages"] if m["role"] == "user"][0]
    assert user["content"] == "X then Y then X"


def test_non_string_field_values_are_stringified(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, user="n={count}"),
                       [{"count": 7, "answer": "5"}])
    assert run.returncode == 0, run.stderr
    user = [m for m in api.calls[0]["messages"] if m["role"] == "user"][0]
    assert user["content"] == "n=7"


# Spec: "If a placeholder references a missing field, exit with code 1 and
#        print an error to stderr naming the row index and missing field."
# Context: Configuration.
def test_missing_placeholder_field_exits_1_naming_row_and_field(run_tool):
    # Spec example: template references {question} and row 0 is {"text": "hello"}
    run = run_tool(make_config(user="{question}", evaluation=None),
                   [{"text": "hello"}])
    assert run.returncode == 1
    assert "0" in run.stderr
    assert "question" in run.stderr


def test_missing_placeholder_names_the_offending_row_index(run_tool):
    rows = [{"question": "ok", "answer": "5"},
            {"question": "ok", "answer": "5"},
            {"text": "hello", "answer": "5"}]
    run = run_tool(make_config(user="{question}"), rows)
    assert run.returncode == 1
    assert "2" in run.stderr
    assert "question" in run.stderr


def test_missing_system_placeholder_field_exits_1(run_tool):
    run = run_tool(make_config(system="You are a {persona}.", user="{question}",
                               evaluation=None),
                   [{"question": "q"}])
    assert run.returncode == 1
    assert "persona" in run.stderr


# T12: rows are validated before any request is issued, and no output is
# written for a failed run.
def test_missing_field_run_issues_no_api_calls_and_writes_no_output(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, user="{question}"),
                       [{"question": "fine", "answer": "5"}, {"text": "hello"}])
    assert run.returncode == 1
    assert api.call_count == 0
    assert not run.output_exists


# Spec: "When the configured evaluation uses answer_field, each row must also
#        contain that field."
# Context: Input.
def test_row_missing_answer_field_exits_1(run_tool):
    run = run_tool(make_config(evaluation={"type": "exact_match",
                                           "answer_field": "answer",
                                           "extract": "last_number"}),
                   [{"question": "q"}])
    assert run.returncode == 1
    assert "answer" in run.stderr


def test_regex_evaluation_does_not_require_answer_field_in_rows(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "regex",
                                               "pattern": r"\d+"}),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr


# Spec: "The input file is JSONL with one object per line."
# Context: Input.
def test_multiple_rows_each_produce_a_request(run_tool):
    rows = [
        {"question": "Sarah has 5 apples and buys 3 more. How many does she have?",
         "answer": "8"},
        {"question": "A train travels 60 miles in 2 hours. What is its speed in mph?",
         "answer": "30"},
    ]
    with MockAPI(always("#### 8")) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert len(run.rows) == 2


def test_blank_lines_in_input_are_skipped(run_tool):
    text = '{"question": "a", "answer": "5"}\n\n{"question": "b", "answer": "5"}\n'
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), [], input_text=text)
    assert run.returncode == 0, run.stderr
    assert run.summary["total"] == 2


# T15: an empty input file is a valid zero-row run.
def test_empty_input_produces_empty_output_and_zero_summary(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), [], input_text="")
    assert run.returncode == 0, run.stderr
    assert run.rows == []
    assert run.summary["total"] == 0
    assert run.summary["total_api_calls"] == 0
    assert run.summary["elapsed_seconds"] == 0.0
    assert run.summary["throughput_rpm"] == 0.0


# Spec: 'Send POST requests to "{api_url}/v1/chat/completions"'
# Context: API Contract.
def test_requests_go_to_chat_completions_path(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/chat/completions"]


def test_trailing_slash_in_api_url_is_handled(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url + "/"),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/chat/completions"]


# Spec: request body shape
#   {"model": ..., "messages": [{"role": "system", ...}, {"role": "user", ...}],
#    "temperature": 0.0, "max_tokens": 512}
# Context: API Contract.
def test_request_body_shape(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, model="gpt-4",
                                   system="SYS", user="{question}",
                                   max_tokens=512),
                       [{"question": "Q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    payload = api.calls[0]
    assert payload["model"] == "gpt-4"
    assert payload["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "Q"},
    ]
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 512
