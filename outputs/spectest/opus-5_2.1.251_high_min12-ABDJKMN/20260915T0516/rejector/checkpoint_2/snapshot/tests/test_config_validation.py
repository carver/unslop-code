"""Configuration parsing, generation-scheme rules and validation rules."""
import pytest

from conftest import make_config
from mock_api import MockAPI, always


ROW = {"question": "q", "answer": "5"}


# Spec: "greedy: force temperature to 0.0; n is ignored"
# Context: Generation behavior.
def test_greedy_forces_temperature_to_zero(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="greedy",
                                   temperature=0.9), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["temperature"] == 0.0


def test_greedy_ignores_n(run_tool):
    # n: 5 must not produce five attempts for a greedy row.
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="greedy", n=5), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 1
    assert run.rows[0]["result"]["attempts"] == 1


def test_greedy_is_valid_without_temperature(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="greedy",
                                   temperature=None), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["temperature"] == 0.0


# Spec: "sample: temperature must be > 0; n is ignored"
def test_sample_with_positive_temperature_is_valid(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="sample",
                                   temperature=0.7), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["temperature"] == pytest.approx(0.7)


def test_sample_with_zero_temperature_exits_1(run_tool):
    run = run_tool(make_config(scheme="sample", temperature=0.0), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_sample_with_negative_temperature_exits_1(run_tool):
    run = run_tool(make_config(scheme="sample", temperature=-0.5), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


# T6: temperature omitted defaults to 0.0, so sample/rejection are invalid.
def test_sample_without_temperature_exits_1(run_tool):
    run = run_tool(make_config(scheme="sample", temperature=None), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_sample_ignores_n(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="sample",
                                   temperature=0.7, n=4), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 1
    assert run.rows[0]["result"]["attempts"] == 1


# Spec: "rejection: temperature must be > 0"
def test_rejection_with_zero_temperature_exits_1(run_tool):
    run = run_tool(make_config(scheme="rejection", temperature=0.0, n=3), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


# Spec: "evaluation is required for rejection and optional otherwise"
# Context: Validation rules.
def test_rejection_without_evaluation_exits_1(run_tool):
    run = run_tool(make_config(scheme="rejection", temperature=0.7, n=3,
                               evaluation=None), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


@pytest.mark.parametrize("scheme,temperature", [("greedy", None), ("sample", 0.7)])
def test_evaluation_optional_for_greedy_and_sample(run_tool, scheme, temperature):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, scheme=scheme,
                                   temperature=temperature, evaluation=None), [ROW])
    assert run.returncode == 0, run.stderr


# Spec: "exact_match and contains require answer_field"
def test_exact_match_without_answer_field_exits_1(run_tool):
    run = run_tool(make_config(evaluation={"type": "exact_match",
                                           "extract": "last_number"}), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_contains_without_answer_field_exits_1(run_tool):
    run = run_tool(make_config(evaluation={"type": "contains"}), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


# Spec: "regex requires pattern and does not require answer_field"
def test_regex_without_pattern_exits_1(run_tool):
    run = run_tool(make_config(evaluation={"type": "regex"}), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_regex_without_answer_field_is_valid(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "regex",
                                               "pattern": r"####\s*\d+"}),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


# Spec: "Invalid configuration exits with code 1 and a descriptive message on
#        stderr."
def test_unknown_evaluation_type_exits_1(run_tool):
    run = run_tool(make_config(evaluation={"type": "bleu",
                                           "answer_field": "answer"}), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_unknown_extract_method_exits_1(run_tool):
    # Part 2 added `letter` and `first_number`; `middle_number` is still not
    # an extract method.
    run = run_tool(make_config(evaluation={"type": "exact_match",
                                           "answer_field": "answer",
                                           "extract": "middle_number"}), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_unknown_scheme_in_config_exits_1(run_tool):
    run = run_tool(make_config(scheme="beam_search"), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_config_without_task_key_exits_1(run_tool):
    run = run_tool({"name": "no task wrapper"}, [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_config_missing_api_url_exits_1(run_tool):
    cfg = make_config()
    del cfg["task"]["api_url"]
    run = run_tool(cfg, [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_config_missing_model_exits_1(run_tool):
    cfg = make_config()
    del cfg["task"]["model"]
    run = run_tool(cfg, [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_config_missing_user_prompt_exits_1(run_tool):
    run = run_tool(make_config(user=None), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_config_error_message_goes_to_stderr_not_stdout(run_tool):
    run = run_tool(make_config(scheme="sample", temperature=0.0), [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()
    assert run.stdout.strip() == ""


def test_invalid_config_writes_no_output_file(run_tool):
    run = run_tool(make_config(scheme="sample", temperature=0.0), [ROW])
    assert run.returncode == 1
    assert not run.output_exists


# T7: optional keys default rather than erroring.
def test_system_prompt_is_optional(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, system=None), [ROW])
    assert run.returncode == 0, run.stderr
    roles = [m["role"] for m in api.calls[0]["messages"]]
    assert roles == ["user"]


def test_scheme_defaults_to_greedy_when_absent(run_tool):
    cfg = make_config()
    del cfg["task"]["generation"]["scheme"]
    with MockAPI(always("#### 5")) as api:
        cfg["task"]["api_url"] = api.url
        run = run_tool(cfg, [ROW])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["temperature"] == 0.0


def test_max_tokens_defaults_to_512_when_absent(run_tool):
    cfg = make_config()
    del cfg["task"]["generation"]["max_tokens"]
    with MockAPI(always("#### 5")) as api:
        cfg["task"]["api_url"] = api.url
        run = run_tool(cfg, [ROW])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["max_tokens"] == 512
