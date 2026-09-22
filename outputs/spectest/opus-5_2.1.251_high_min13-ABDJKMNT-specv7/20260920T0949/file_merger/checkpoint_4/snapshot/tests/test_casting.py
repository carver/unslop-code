"""Casting rules, temporal normalisation and --on-type-error behaviour."""

from conftest import rows_of


def _one_row(run, make_csv, make_schema, coltype, value, *extra):
    """Cast a single cell of ``coltype`` and return the rendered output row."""
    make_csv("a.csv", "id,v\n1,{}\n".format(value))
    make_schema("s.json", [("id", "int"), ("v", coltype)])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", *extra, "a.csv")
    return rows_of(proc.stdout)[1]


# Spec: "`int`, `float`, `string`: standard parsing"
def test_int_float_and_string_standard_parsing(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "int", "-42")[1] == "-42"
    assert _one_row(run, make_csv, make_schema, "float", "-2.50")[1] == "-2.5"
    assert _one_row(run, make_csv, make_schema, "float", "1e3")[1] == "1000.0"
    assert _one_row(run, make_csv, make_schema, "string", "hello")[1] == "hello"


# Spec: "`int` ... standard parsing"
# Context: see AMBIGUITIES T8 - a cast int is re-rendered from the parsed value.
def test_int_output_is_normalised(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "int", "007")[1] == "7"


# Spec: "`bool` includes `1`/`0` along with standard values"
def test_bool_accepts_one_zero_and_true_false(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "bool", "1")[1] == "true"
    assert _one_row(run, make_csv, make_schema, "bool", "0")[1] == "false"
    assert _one_row(run, make_csv, make_schema, "bool", "true")[1] == "true"
    assert _one_row(run, make_csv, make_schema, "bool", "False")[1] == "false"


# Spec: "`date`: ISO-8601 `YYYY-MM-DD`" and "date stays `YYYY-MM-DD`"
def test_date_is_parsed_and_kept_in_iso_form(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "date", "2024-07-01")[1] == "2024-07-01"


# Spec: "`date`: ISO-8601 `YYYY-MM-DD`"
# Context: an impossible calendar date is a cast failure.
def test_invalid_calendar_date_fails_to_cast(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "date", "2024-13-45")[1] == ""


# Spec: "timestamp: ... normalize to UTC with `Z` suffix in output"
def test_timestamp_offset_is_converted_to_utc(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "timestamp", "2024-07-01T12:00:00+02:00")[1] == "2024-07-01T10:00:00Z"


# Spec: "timestamp normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`)"
def test_timestamp_already_in_utc_keeps_its_instant(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "timestamp", "2024-07-01T12:00:00Z")[1] == "2024-07-01T12:00:00Z"


# Spec: "if source lacked zone, treat as UTC"
def test_naive_timestamp_is_treated_as_utc(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "timestamp", "2024-07-01T12:00:00")[1] == "2024-07-01T12:00:00Z"


# Spec: "keeping fractional seconds"
# Context: see AMBIGUITIES T9 - fractional seconds survive the UTC conversion.
def test_fractional_seconds_are_kept(run, make_csv, make_schema):
    out = _one_row(run, make_csv, make_schema, "timestamp", "2024-07-01T12:00:00.123456Z")[1]
    assert out.startswith("2024-07-01T12:00:00.123456") and out.endswith("Z")


# Spec: "On cast failure, apply `--on-type-error`: `coerce-null` (default): emit null literal for that cell"
def test_coerce_null_is_the_default_failure_policy(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "int", "abc")[1] == ""


# Spec: "coerce-null ...: emit null literal for that cell"
# Context: the emitted text is the configured null literal.
def test_coerced_cell_uses_the_null_literal(run, make_csv, make_schema):
    row = _one_row(run, make_csv, make_schema, "int", "abc", "--csv-null-literal", "NA")
    assert row[1] == "NA"


# Spec: "`keep-string`: emit original text as string"
def test_keep_string_emits_the_original_text(run, make_csv, make_schema):
    row = _one_row(run, make_csv, make_schema, "int", "abc", "--on-type-error", "keep-string")
    assert row[1] == "abc"


# Spec: "`fail`: write error to stderr and exit non-zero"
def test_fail_policy_exits_non_zero_with_stderr(make_csv, make_schema, run):
    make_csv("a.csv", "id,v\n1,abc\n")
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.csv", expect_ok=False,
    )
    assert proc.returncode != 0
    assert proc.stderr.strip()


# Spec: "On cast failure" - an empty cell is a null, not a failure.
def test_empty_cell_is_null_rather_than_a_cast_failure(make_csv, make_schema, run):
    make_csv("a.csv", "id,v\n1,\n")
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--on-type-error", "fail", "a.csv")
    assert rows_of(proc.stdout)[1] == ["1", ""]


# Spec: "--csv-null-literal <STRING>" with "Missing values emitted as the null literal"
# Context: see AMBIGUITIES T10 - the null literal is also recognised on input.
def test_null_literal_is_recognised_on_input(make_csv, make_schema, run):
    make_csv("a.csv", "id,v\n1,NA\n")
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--csv-null-literal", "NA", "--on-type-error", "fail", "a.csv",
    )
    assert rows_of(proc.stdout)[1] == ["1", "NA"]


# Spec: "Cast every input cell into target type (rules below)"
# Context: a float-looking value in an int column is a cast failure.
def test_float_text_does_not_satisfy_an_int_column(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "int", "1.5")[1] == ""


# Spec: "`float`: standard parsing"
# Context: an int-looking value is a valid float.
def test_int_text_satisfies_a_float_column(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "float", "3")[1] == "3.0"


# Spec: "`int`, `float`, `string`: standard parsing"
# Context: see AMBIGUITIES T21 - padding around a number is tolerated, while a
# string column keeps its text verbatim.
def test_whitespace_is_stripped_for_numbers_but_not_for_strings(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "int", '" 5 "')[1] == "5"
    assert _one_row(run, make_csv, make_schema, "string", '" 5 "')[1] == " 5 "


# Spec: "`int`, `float`: standard parsing"
# Context: see AMBIGUITIES T22 - Python's own literal quirks are not CSV numbers.
def test_exotic_numeric_literals_are_not_numbers(run, make_csv, make_schema):
    assert _one_row(run, make_csv, make_schema, "int", "1_000")[1] == ""
    assert _one_row(run, make_csv, make_schema, "float", "nan")[1] == ""


# Spec: "`keep-string`: emit original text as string" with "sorted globally by the key(s)"
# Context: see AMBIGUITIES T13 - kept text sorts after the values that did cast,
# and nulls still come first.
def test_kept_strings_sort_after_cast_values(make_csv, make_schema, run):
    make_csv("a.csv", "id,v\n1,abc\n2,5\n3,\n4,10\n")
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "v", "--schema", "s.json",
        "--on-type-error", "keep-string", "a.csv",
    )
    assert [row[0] for row in rows_of(proc.stdout)[1:]] == ["3", "2", "4", "1"]
