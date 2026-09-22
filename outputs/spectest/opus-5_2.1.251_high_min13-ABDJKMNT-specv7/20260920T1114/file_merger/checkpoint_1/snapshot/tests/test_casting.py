"""Spec section: Casting & Validation — per-type parsing, rendering, error policy."""

import json

from conftest import rows_of


def typed(csv_file, column_type, body, name="v"):
    """Write a one-column input plus a schema declaring that column's type."""
    csv_file("schema.json", json.dumps({"columns": [{"name": name, "type": column_type}]}))
    csv_file("a.csv", f"{name}\n{body}")


def cast(run_tool, *extra):
    """Run the tool over the one-column fixture written by `typed`."""
    return run_tool("--output", "-", "--key", "v", "--schema", "schema.json", *extra, "a.csv")


# Phrase: "int, float, string: standard parsing"
# Context: Casting. Ambiguity T7: ints are rendered canonically.
def test_int_values_are_normalised(csv_file, run_tool):
    typed(csv_file, "int", "007\n+5\n-3\n")
    assert rows_of(cast(run_tool).stdout) == [["-3"], ["5"], ["7"]]


# Phrase: "int, float, string: standard parsing"
# Context: Casting. Ambiguity T6: floats are rendered canonically.
def test_float_values_are_normalised(csv_file, run_tool):
    typed(csv_file, "float", "1.50\n2\n")
    assert rows_of(cast(run_tool).stdout) == [["1.5"], ["2.0"]]


# Phrase: "int, float, string: standard parsing"
# Context: Casting. String cells are passed through untouched.
def test_string_values_pass_through(csv_file, run_tool):
    typed(csv_file, "string", "007\n hi \n")
    assert rows_of(cast(run_tool).stdout) == [[" hi "], ["007"]]


# Phrase: "bool includes 1/0 along with standard values"
# Context: Casting. Ambiguity T5/T16: true/false plus 1/0, rendered lowercase.
def test_bool_accepts_words_and_digits(csv_file, run_tool):
    typed(csv_file, "bool", "1\n0\ntrue\nFALSE\n")
    assert rows_of(cast(run_tool, "--on-type-error", "fail").stdout) == [
        ["false"], ["false"], ["true"], ["true"]
    ]


# Phrase: "bool includes 1/0 along with standard values"
# Context: Casting. Ambiguity T16: other words are not booleans.
def test_bool_rejects_other_words(csv_file, run_tool):
    typed(csv_file, "bool", "yes\n")
    result = cast(run_tool, "--on-type-error", "fail")
    assert result.returncode != 0


# Phrase: "date: ISO-8601 YYYY-MM-DD"
# Context: Casting.
def test_date_accepts_iso_dates(csv_file, run_tool):
    typed(csv_file, "date", "2024-07-01\n2023-12-31\n")
    assert rows_of(cast(run_tool, "--on-type-error", "fail").stdout) == [
        ["2023-12-31"], ["2024-07-01"]
    ]


# Phrase: "date: ISO-8601 YYYY-MM-DD"
# Context: Casting. Ambiguity T18: a value carrying a time is not a date.
def test_date_rejects_timestamps(csv_file, run_tool):
    typed(csv_file, "date", "2024-07-01T12:00:00Z\n")
    assert cast(run_tool, "--on-type-error", "fail").returncode != 0


# Phrase: "date stays YYYY-MM-DD"
# Context: Deterministic Dialect Details.
def test_date_output_format_is_unchanged(csv_file, run_tool):
    typed(csv_file, "date", "2024-01-05\n")
    assert rows_of(cast(run_tool).stdout) == [["2024-01-05"]]


# Phrase: "timestamp: ISO-8601 format; normalize to UTC with Z suffix in output"
# Context: Casting.
def test_timestamp_offsets_are_normalised_to_utc(csv_file, run_tool):
    typed(csv_file, "timestamp", "2024-07-01T14:30:00+02:30\n")
    assert rows_of(cast(run_tool).stdout) == [["2024-07-01T12:00:00Z"]]


# Phrase: "if source lacked zone, treat as UTC"
# Context: Deterministic Dialect Details.
def test_naive_timestamp_is_treated_as_utc(csv_file, run_tool):
    typed(csv_file, "timestamp", "2024-07-01T12:00:00\n")
    assert rows_of(cast(run_tool).stdout) == [["2024-07-01T12:00:00Z"]]


# Phrase: "normalized to UTC with Z (e.g., 2024-07-01T12:00:00Z), keeping fractional seconds"
# Context: Deterministic Dialect Details. Ambiguity T8: microsecond precision.
def test_fractional_seconds_are_kept(csv_file, run_tool):
    typed(csv_file, "timestamp", "2024-07-01T12:00:00.123456Z\n")
    assert rows_of(cast(run_tool).stdout) == [["2024-07-01T12:00:00.123456Z"]]


# Phrase: "timestamp: ISO-8601 format"
# Context: Casting. A Z-suffixed value is already UTC and stays put.
def test_utc_timestamp_round_trips(csv_file, run_tool):
    typed(csv_file, "timestamp", "2024-07-01T12:00:00Z\n")
    assert rows_of(cast(run_tool).stdout) == [["2024-07-01T12:00:00Z"]]


# Phrase: "coerce-null (default): emit null literal for that cell"
# Context: Casting & Validation.
def test_coerce_null_is_the_default_policy(csv_file, run_tool):
    typed(csv_file, "int", "1\noops\n")
    assert rows_of(cast(run_tool).stdout) == [[""], ["1"]]


# Phrase: "coerce-null (default): emit null literal for that cell"
# Context: Casting & Validation. The coerced cell uses the configured literal.
def test_coerce_null_uses_the_null_literal(csv_file, run_tool):
    typed(csv_file, "int", "oops\n")
    result = cast(run_tool, "--on-type-error", "coerce-null", "--csv-null-literal", "NA")
    assert rows_of(result.stdout) == [["NA"]]


# Phrase: "fail: write error to stderr and exit non-zero"
# Context: Casting & Validation. Ambiguity T15.
def test_fail_policy_reports_and_exits_non_zero(csv_file, run_tool):
    typed(csv_file, "int", "1\noops\n")
    result = cast(run_tool, "--on-type-error", "fail")
    assert result.returncode != 0
    assert "oops" in result.stderr


# Phrase: "keep-string: emit original text as string"
# Context: Casting & Validation.
def test_keep_string_preserves_the_original_text(csv_file, run_tool):
    typed(csv_file, "int", "1\noops\n")
    result = cast(run_tool, "--on-type-error", "keep-string")
    assert sorted(rows_of(result.stdout)) == [["1"], ["oops"]]


# Phrase: "keep-string: emit original text as string"
# Context: Casting & Validation. Ambiguity T12: kept text sorts after cast values.
def test_keep_string_cells_sort_after_typed_values(csv_file, run_tool):
    typed(csv_file, "int", 'oops\n2\n""\n')  # a quoted empty field is a null cell
    result = cast(run_tool, "--on-type-error", "keep-string")
    assert rows_of(result.stdout) == [[""], ["2"], ["oops"]]


# Phrase: "On cast failure, apply --on-type-error"
# Context: Casting & Validation. A null cell is missing data, not a cast failure.
def test_null_cells_are_not_cast_failures(csv_file, run_tool):
    typed(csv_file, "int", '""\n1\n')  # a quoted empty field is a null cell
    result = cast(run_tool, "--on-type-error", "fail")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [[""], ["1"]]
