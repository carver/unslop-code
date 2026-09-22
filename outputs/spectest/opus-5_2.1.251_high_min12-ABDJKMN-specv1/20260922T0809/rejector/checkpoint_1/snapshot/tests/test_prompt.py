"""Spec section: Configuration / prompt templates and Input field requirements."""
from __future__ import annotations

from conftest import base_config
from mock_server import MockAPI, always


# ---------------------------------------------------------------------------
# Phrase: "prompt.system and prompt.user use {field} placeholders resolved from
#          each input row."
# Context: Configuration.  Both templates are rendered per row.
# ---------------------------------------------------------------------------
def test_placeholders_rendered_from_row(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, prompt={
            "system": "You grade {subject} problems.",
            "user": "Q: {question}",
        }))
        data = write_input([{"question": "2+3?", "subject": "math",
                             "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][0]["content"] == "You grade math problems."
    assert sent["messages"][1]["content"] == "Q: 2+3?"


# Context: same phrase - each row gets its own rendering.
def test_each_row_renders_its_own_values(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "alpha", "answer": "5"},
                            {"question": "beta", "answer": "5"}])
        res = run_tool(cfg, data)
        users = sorted(r["messages"][-1]["content"] for r in api.requests)
    assert res.returncode == 0, res
    assert users == ["alpha", "beta"]


# Context: same phrase - a repeated placeholder is substituted everywhere.
def test_repeated_placeholder(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, prompt={
            "system": "sys", "user": "{question} / {question}"}))
        data = write_input([{"question": "x", "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][1]["content"] == "x / x"


# Context: same phrase - non-string row values are rendered as text.
def test_non_string_placeholder_value(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": 42, "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][1]["content"] == "42"


# ---------------------------------------------------------------------------
# Phrase: "If a placeholder references a missing field, exit with code 1 and
#          print an error to stderr naming the row index and missing field."
# Context: Configuration.  The spec's own example: template references
# {question}, row 0 is {"text": "hello"}.
# ---------------------------------------------------------------------------
def test_missing_placeholder_field_exits_1_naming_row_and_field(
        run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input([{"text": "hello"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert "0" in res.stderr
    assert "question" in res.stderr


# Context: same phrase - the named index is the offending row's index, not 0.
def test_missing_field_names_correct_row_index(run_tool, write_config,
                                               write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input([{"question": "ok", "answer": "1"},
                        {"question": "ok", "answer": "2"},
                        {"text": "no question here"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert "2" in res.stderr
    assert "question" in res.stderr


# Context: same phrase - a placeholder missing from the *system* template counts.
def test_missing_field_in_system_template(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1", prompt={
        "system": "Domain: {domain}", "user": "{question}"}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert "domain" in res.stderr


# Context (ambiguity T8): validation happens before any request is issued.
def test_missing_field_validated_before_any_api_call(run_tool, write_config,
                                                     write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "fine", "answer": "5"},
                            {"nope": 1}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1
    assert calls == 0


# ---------------------------------------------------------------------------
# Phrase: "When the configured evaluation uses answer_field, each row must also
#          contain that field."
# Context: Input.
# ---------------------------------------------------------------------------
def test_missing_answer_field_is_input_error(run_tool, write_config,
                                             write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert "answer" in res.stderr


# Context: same phrase - a regex evaluation needs no answer_field in the rows.
def test_regex_evaluation_needs_no_answer_field_in_rows(run_tool, write_config,
                                                        write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url, evaluation={
            "type": "regex", "pattern": r"\d+", "answer_field": None,
            "extract": None}))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res


# ---------------------------------------------------------------------------
# Phrase (ambiguity T16): braces that are not `{identifier}` placeholders pass
#         through untouched.
# Context: Configuration / prompt templates.
# ---------------------------------------------------------------------------
def test_literal_braces_survive_rendering(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, prompt={
            "system": 'Reply as {"answer": N}.', "user": "{question}"}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][0]["content"] == 'Reply as {"answer": N}.'
