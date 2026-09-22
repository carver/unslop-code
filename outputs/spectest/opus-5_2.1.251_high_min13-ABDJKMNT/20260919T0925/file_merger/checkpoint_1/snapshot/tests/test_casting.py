"""Casting rules and the `--on-type-error` policies."""

import json

import pytest


@pytest.fixture
def typed(tmp_path, csv_file, run_cli):
    """Run one single-column CSV through an explicit schema of the given type."""

    def _run(column_type, values, *extra):
        schema = tmp_path / "schema.json"
        schema.write_text(
            json.dumps({"columns": [{"name": "k", "type": "string"}, {"name": "v", "type": column_type}]}),
            encoding="utf-8",
        )
        body = "".join(f"k{i},{value}\n" for i, value in enumerate(values))
        source = csv_file("in.csv", "k,v\n" + body)
        return run_cli("--output", "-", "--key", "k", "--schema", schema, *extra, source)

    return _run


def test_int_and_float_and_string_standard_parsing(typed):
    # Spec: "int, float, string: standard parsing"
    assert [row[1] for row in typed("int", ["42", "-7"]).rows[1:]] == ["42", "-7"]
    assert [row[1] for row in typed("float", ["1.5", "-2", "1e3"]).rows[1:]] == ["1.5", "-2.0", "1000.0"]
    assert [row[1] for row in typed("string", ["1.50", " pad "]).rows[1:]] == ["1.50", " pad "]


def test_bool_accepts_one_and_zero_and_standard_values(typed):
    # Spec: "bool includes 1/0 along with standard values"
    result = typed("bool", ["1", "0", "true", "false", "TRUE", "False"])
    assert [row[1] for row in result.rows[1:]] == ["True", "False", "True", "False", "True", "False"]


def test_date_requires_iso_yyyy_mm_dd(typed):
    # Spec: "date: ISO-8601 YYYY-MM-DD" / "date stays YYYY-MM-DD"
    result = typed("date", ["2024-07-01", "07/01/2024"])
    assert [row[1] for row in result.rows[1:]] == ["2024-07-01", ""]


def test_timestamp_normalized_to_utc_with_z(typed):
    # Spec: "timestamp: ISO-8601 format; normalize to UTC with Z suffix in output
    #        (e.g., 2024-07-01T12:00:00Z)"
    result = typed("timestamp", ["2024-07-01T14:00:00+02:00", "2024-07-01T12:00:00Z"])
    assert [row[1] for row in result.rows[1:]] == ["2024-07-01T12:00:00Z", "2024-07-01T12:00:00Z"]


def test_timestamp_without_zone_is_treated_as_utc(typed):
    # Spec: "if source lacked zone, treat as UTC"
    result = typed("timestamp", ["2024-07-01T12:00:00"])
    assert result.rows[1][1] == "2024-07-01T12:00:00Z"


def test_date_only_text_casts_into_a_timestamp_column(typed):
    # Spec: "timestamp: ISO-8601 format" applied to a date-only source (AMBIGUITIES T4)
    result = typed("timestamp", ["2024-07-01"])
    assert result.rows[1][1] == "2024-07-01T00:00:00Z"


def test_coerce_null_is_the_default_type_error_policy(typed):
    # Spec: "coerce-null (default): emit null literal for that cell"
    assert typed("int", ["oops"]).rows[1][1] == ""
    assert typed("int", ["oops"], "--on-type-error", "coerce-null").rows[1][1] == ""


def test_coerce_null_uses_the_configured_null_literal(typed):
    # Spec: "emit null literal for that cell"
    result = typed("int", ["oops"], "--csv-null-literal", "NA")
    assert result.rows[1][1] == "NA"


def test_fail_writes_to_stderr_and_exits_non_zero(typed):
    # Spec: "fail: write error to stderr and exit non-zero"
    result = typed("int", ["oops"], "--on-type-error", "fail")
    assert result.returncode != 0
    assert "oops" in result.stderr


def test_keep_string_emits_original_text(typed):
    # Spec: "keep-string: emit original text as string"
    result = typed("int", ["oops"], "--on-type-error", "keep-string")
    assert result.rows[1][1] == "oops"


def test_empty_cell_in_typed_column_is_null_not_a_type_error(typed):
    # Spec: "Missing values emitted as the null literal" (empty cells are nulls, AMBIGUITIES T11)
    result = typed("int", [""], "--on-type-error", "fail")
    assert result.returncode == 0, result.stderr
    assert result.rows[1][1] == ""
