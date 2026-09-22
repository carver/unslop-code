"""Configuration shape, prompt templating and validation rules."""

import json

import pytest

import fake_api


# ---------------------------------------------------------------------------
# Spec: the documented config shape (task.name/api_url/model/rpm/prompt/
#       generation/evaluation/output_field)
# Context: Configuration.  The example config from the spec must run as-is.
# ---------------------------------------------------------------------------
def test_spec_example_config_shape_runs(run_cli, write_input, workdir):
    with fake_api.FakeAPI(fake_api.always("5 + 3 = 8\n#### 8")) as api:
        cfg = workdir / "task.yaml"
        cfg.write_text("""
task:
  name: "gsm8k_solve"
  api_url: "%s"
  model: "gpt-4"
  rpm: 60

  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"

  generation:
    scheme: "greedy"
    temperature: 0.0
    max_tokens: 512
    n: 1

  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"

  output_field: "solution"
""" % api.url)
        inp = write_input([{"question": "5 + 3?", "answer": "8"}])
        res = run_cli("run", "--config", str(cfg), "--input", inp, check=0)
    assert res.rows[0]["output"] == {"solution": "5 + 3 = 8\n#### 8"}
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
#        each input row."
# Context: Configuration.  Both templates are rendered per row.
# ---------------------------------------------------------------------------
def test_placeholders_resolved_from_row_in_both_templates(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api,
                 task={"prompt": {"system": "You are a {persona}.",
                                  "user": "Q: {question}"}},
                 rows=[{"question": "2+3?", "answer": "5",
                        "persona": "tutor"}], check=0)
        req = api.requests[0]
    assert req.system_content == "You are a tutor."
    assert req.user_content == "Q: 2+3?"


# ---------------------------------------------------------------------------
# Spec: "{field} placeholders resolved from each input row"
# Context: Configuration.  Each row renders with its own values, and a
# placeholder may appear more than once.
# ---------------------------------------------------------------------------
def test_placeholders_render_per_row_and_repeat(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api,
                 task={"prompt": {"system": "s", "user": "{q} / {q}"}},
                 rows=[{"q": "a", "answer": "5"}, {"q": "b", "answer": "5"}],
                 check=0)
        got = sorted(r.user_content for r in api.requests)
    assert got == ["a / a", "b / b"]


# ---------------------------------------------------------------------------
# Spec: "{field} placeholders resolved from each input row"
# Context: Configuration.  Non-string row values are usable as substitutions.
# ---------------------------------------------------------------------------
def test_non_string_field_values_render(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api,
                 task={"prompt": {"system": "s", "user": "n={count}"},
                       "evaluation": None},
                 rows=[{"count": 7}], check=0)
        assert api.requests[0].user_content == "n=7"


# ---------------------------------------------------------------------------
# Spec: "If a placeholder references a missing field, exit with code 1 and
#        print an error to stderr naming the row index and missing field."
# Context: Configuration + the worked example: row 0 is {"text": "hello"} and
# the template references {question}.
# ---------------------------------------------------------------------------
def test_missing_placeholder_field_exits_one_naming_row_and_field(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"text": "hello"}])
    assert res.returncode == 1
    assert "0" in res.stderr
    assert "question" in res.stderr
    # Nothing was generated for a run that never got off the ground.
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "naming the row index and missing field"
# Context: Configuration.  The index is that of the offending row, not always 0.
# ---------------------------------------------------------------------------
def test_missing_field_reports_the_offending_row_index(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "ok"}, {"question": "ok"},
                             {"text": "bad"}])
    assert res.returncode == 1
    assert "2" in res.stderr
    assert "question" in res.stderr


# ---------------------------------------------------------------------------
# Spec: "If a placeholder references a missing field, exit with code 1"
# Context: Configuration.  A system-prompt placeholder counts too.
# ---------------------------------------------------------------------------
def test_missing_field_in_system_template_exits_one(run_task):
    res = run_task(task={"prompt": {"system": "You are {persona}.",
                                    "user": "{question}"},
                         "evaluation": None},
                   rows=[{"question": "q"}])
    assert res.returncode == 1
    assert "persona" in res.stderr


# ---------------------------------------------------------------------------
# Spec: "When the configured evaluation uses answer_field, each row must also
#        contain that field."
# Context: Input.  Missing answer_field is an input error (AMBIGUITIES T12).
# ---------------------------------------------------------------------------
def test_row_missing_answer_field_exits_one(run_task):
    res = run_task(rows=[{"question": "q"}])
    assert res.returncode == 1
    assert "answer" in res.stderr


# ---------------------------------------------------------------------------
# Spec: "greedy: force temperature to 0.0"
# Context: Generation behavior.  A non-zero configured temperature is
# overridden on the wire.
# ---------------------------------------------------------------------------
def test_greedy_forces_temperature_zero(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"generation": {"scheme": "greedy",
                                           "temperature": 0.9}}, check=0)
        assert api.bodies()[0]["temperature"] == 0.0


# ---------------------------------------------------------------------------
# Spec: "greedy: ... n is ignored"
# Context: Generation behavior.  n > 1 does not produce extra calls.
# ---------------------------------------------------------------------------
def test_greedy_ignores_n(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 999")) as api:
        res = run_task(api, task={"generation": {"scheme": "greedy", "n": 5}},
                       check=0)
        assert api.call_count == 1
    assert res.rows[0]["result"]["attempts"] == 1


# ---------------------------------------------------------------------------
# Spec: "sample: temperature must be > 0"
# Context: Generation behavior.  A positive temperature is valid and is sent.
# ---------------------------------------------------------------------------
def test_sample_with_positive_temperature_is_valid(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"generation": {"scheme": "sample",
                                           "temperature": 0.7}}, check=0)
        assert api.bodies()[0]["temperature"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Spec: "sample: temperature must be > 0"
# Context: Generation behavior.  Zero is invalid -> exit 1 (config error).
# ---------------------------------------------------------------------------
def test_sample_with_zero_temperature_exits_one(run_task):
    res = run_task(task={"generation": {"scheme": "sample",
                                        "temperature": 0.0}})
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "sample: temperature must be > 0"
# Context: Generation behavior.  Negative is invalid too.
# ---------------------------------------------------------------------------
def test_sample_with_negative_temperature_exits_one(run_task):
    res = run_task(task={"generation": {"scheme": "sample",
                                        "temperature": -0.5}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "sample: ... n is ignored"
# Context: Generation behavior.  One call per row regardless of n.
# ---------------------------------------------------------------------------
def test_sample_ignores_n(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 999")) as api:
        res = run_task(api, task={"generation": {"scheme": "sample",
                                                 "temperature": 0.7, "n": 4}},
                       check=0)
        assert api.call_count == 1
    assert res.rows[0]["result"]["attempts"] == 1


# ---------------------------------------------------------------------------
# Spec: "rejection: temperature must be > 0"
# Context: Generation behavior.  Zero temperature is a config error.
# ---------------------------------------------------------------------------
def test_rejection_with_zero_temperature_exits_one(run_task):
    res = run_task(task={"generation": {"scheme": "rejection",
                                        "temperature": 0.0, "n": 3}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "evaluation is required for rejection and optional otherwise"
# Context: Validation rules.  rejection without evaluation -> exit 1.
# ---------------------------------------------------------------------------
def test_rejection_without_evaluation_exits_one(run_task):
    res = run_task(task={"generation": {"scheme": "rejection",
                                        "temperature": 0.8, "n": 3},
                         "evaluation": None})
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "evaluation is required for rejection and optional otherwise"
# Context: Validation rules.  greedy without evaluation is legal.
# ---------------------------------------------------------------------------
def test_greedy_without_evaluation_is_valid(run_task):
    with fake_api.FakeAPI(fake_api.always("hello")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["output"] == {"solution": "hello"}


# ---------------------------------------------------------------------------
# Spec: "evaluation is required for rejection and optional otherwise"
# Context: Validation rules.  sample without evaluation is legal.
# ---------------------------------------------------------------------------
def test_sample_without_evaluation_is_valid(run_task):
    with fake_api.FakeAPI(fake_api.always("hello")) as api:
        res = run_task(api, task={"generation": {"scheme": "sample",
                                                 "temperature": 0.5},
                                  "evaluation": None},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is None


# ---------------------------------------------------------------------------
# Spec: "exact_match and contains require answer_field"
# Context: Validation rules.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("etype", ["exact_match", "contains"])
def test_missing_answer_field_is_a_config_error(run_task, etype):
    res = run_task(task={"evaluation": {"type": etype, "answer_field": None,
                                        "extract": "full"}})
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "regex requires pattern and does not require answer_field"
# Context: Validation rules.  Missing pattern is a config error.
# ---------------------------------------------------------------------------
def test_regex_without_pattern_is_a_config_error(run_task):
    res = run_task(task={"evaluation": {"type": "regex", "answer_field": None,
                                        "extract": None}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "regex requires pattern and does not require answer_field"
# Context: Validation rules.  A regex config with no answer_field is valid,
# and rows need not carry any answer field.
# ---------------------------------------------------------------------------
def test_regex_without_answer_field_is_valid(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 42")) as api:
        res = run_task(api, task={"evaluation": {"type": "regex",
                                                 "pattern": r"####\s*\d+",
                                                 "answer_field": None,
                                                 "extract": None}},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "if evaluation is omitted for greedy or sample, result.passed must be
#        null"
# Context: Validation rules.
# ---------------------------------------------------------------------------
def test_no_evaluation_yields_null_passed(run_task):
    with fake_api.FakeAPI(fake_api.always("whatever")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is None


# ---------------------------------------------------------------------------
# Spec: "Invalid configuration exits with code 1 and a descriptive message on
#        stderr."
# Context: Validation rules.  An unknown evaluation type is invalid.
# ---------------------------------------------------------------------------
def test_unknown_evaluation_type_exits_one(run_task):
    res = run_task(task={"evaluation": {"type": "bleu",
                                        "answer_field": "answer"}})
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "Invalid configuration exits with code 1"
# Context: Validation rules.  An unknown extract method is invalid.
# ---------------------------------------------------------------------------
def test_unknown_extract_method_exits_one(run_task):
    res = run_task(task={"evaluation": {"type": "exact_match",
                                        "answer_field": "answer",
                                        "extract": "first_number"}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "Invalid configuration exits with code 1"
# Context: Validation rules.  An unknown scheme in the config file is invalid.
# ---------------------------------------------------------------------------
def test_unknown_scheme_in_config_exits_one(run_task):
    res = run_task(task={"generation": {"scheme": "beam"}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "Invalid configuration exits with code 1"
# Context: Configuration.  A config with no `task:` block is invalid.
# ---------------------------------------------------------------------------
def test_config_without_task_block_exits_one(run_task):
    res = run_task(config_raw="other: {}\n")
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "Invalid configuration exits with code 1"
# Context: Configuration.  Model and api_url are needed to issue requests;
# absent both in config and CLI the run cannot start.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field", ["model", "api_url"])
def test_missing_required_task_field_exits_one(run_task, field):
    res = run_task(task={field: None})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "Invalid configuration exits with code 1"
# Context: Configuration.  The prompt block is what gets sent; without a user
# template there is nothing to ask (AMBIGUITIES T19).
# ---------------------------------------------------------------------------
def test_missing_prompt_user_exits_one(run_task):
    res = run_task(task={"prompt": {"user": None}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: the prompt block shows both system and user, but only `user` carries
#       the task input (AMBIGUITIES T19).
# Context: Configuration.  An omitted system prompt sends only a user message.
# ---------------------------------------------------------------------------
def test_system_prompt_is_optional(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"prompt": {"system": None, "user": "{question}"},
                            "evaluation": None},
                 rows=[{"question": "q"}], check=0)
        msgs = api.bodies()[0]["messages"]
    assert [m["role"] for m in msgs] == ["user"]


# ---------------------------------------------------------------------------
# Spec: "generation: ... temperature ... max_tokens ... n" with greedy forcing
#       temperature to 0.0 (AMBIGUITIES T7, T8, T13).
# Context: Configuration.  A minimal greedy config (no temperature, no n, no
# output_field) is usable; output_field defaults to "output".
# ---------------------------------------------------------------------------
def test_minimal_greedy_config_defaults(run_task):
    with fake_api.FakeAPI(fake_api.always("hi")) as api:
        res = run_task(api, task={"generation": {"scheme": "greedy",
                                                 "temperature": None,
                                                 "n": None},
                                  "evaluation": None,
                                  "output_field": None},
                       rows=[{"question": "q"}], check=0)
        assert api.bodies()[0]["temperature"] == 0.0
    assert res.rows[0]["output"] == {"output": "hi"}


# ---------------------------------------------------------------------------
# Spec: "sample: temperature must be > 0" (AMBIGUITIES T7)
# Context: Generation behavior.  With no temperature configured the default is
# 0.0, so a sample config that omits it fails validation.
# ---------------------------------------------------------------------------
def test_sample_without_temperature_exits_one(run_task):
    res = run_task(task={"generation": {"scheme": "sample",
                                        "temperature": None}})
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "--temperature <float>" + "greedy: force temperature to 0.0"
# Context: AMBIGUITIES T8 — the greedy rule wins over the CLI override.
# ---------------------------------------------------------------------------
def test_greedy_forces_zero_even_with_cli_temperature(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, extra=["--temperature", "0.9"], check=0)
        assert api.bodies()[0]["temperature"] == 0.0
