"""Spec section: Casting & Validation, and the temporal output rules."""
from conftest import column, table


# Phrase: "int, float, string: standard parsing"
# Context: T4 — a successful cast re-renders the value canonically.
def test_int_and_float_render_canonically(run, csv_file, schema_file):
    schema = schema_file([("i", "int"), ("f", "float")])
    csv_file("a.csv", "i,f\n0007,1.50\n-3,+2\n")
    res = run("--output", "-", "--key", "i", "--schema", schema, "a.csv")
    assert table(res.stdout)[1:] == [["-3", "2.0"], ["7", "1.5"]]


# Phrase: "int, float, string: standard parsing"
# Context: surrounding whitespace is tolerated by the numeric parsers.
def test_numeric_parsing_tolerates_whitespace(run, csv_file, schema_file):
    schema = schema_file([("i", "int")])
    csv_file("a.csv", "i\n 42 \n")
    res = run("--output", "-", "--key", "i", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "i") == ["42"]


# Phrase: "float: standard parsing"
# Context: exponent notation is standard float syntax.
def test_float_exponent_notation(run, csv_file, schema_file):
    schema = schema_file([("f", "float")])
    csv_file("a.csv", "f\n1e3\n")
    res = run("--output", "-", "--key", "f", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "f") == ["1000.0"]


# Phrase: "string: standard parsing"
# Context: string cells are emitted unchanged.
def test_string_cells_pass_through(run, csv_file, schema_file):
    schema = schema_file([("s", "string")])
    csv_file("a.csv", "s\n  spaced  \n")
    res = run("--output", "-", "--key", "s", "--schema", schema, "a.csv")
    assert column(res.stdout, "s") == ["  spaced  "]


# Phrase: "bool includes 1/0 along with standard values"
# Context: T4/T15 — accepted spellings and the canonical rendering.
def test_bool_accepted_spellings(run, csv_file, schema_file):
    schema = schema_file([("id", "int"), ("b", "bool")])
    csv_file("a.csv", "id,b\n1,1\n2,0\n3,true\n4,FALSE\n5,True\n")
    res = run("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "b") == ["true", "false", "true", "false", "true"]


# Phrase: "bool includes 1/0 along with standard values"
# Context: T15 — other words are not bools.
def test_bool_rejects_other_words(run, csv_file, schema_file):
    schema = schema_file([("b", "bool")])
    csv_file("a.csv", "b\nyes\n")
    res = run("--output", "-", "--key", "b", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode != 0


# Phrase: "date: ISO-8601 YYYY-MM-DD" and "date stays YYYY-MM-DD"
# Context: dates are emitted in the same form they were parsed from.
def test_date_round_trips(run, csv_file, schema_file):
    schema = schema_file([("d", "date")])
    csv_file("a.csv", "d\n2024-07-01\n")
    res = run("--output", "-", "--key", "d", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "d") == ["2024-07-01"]


# Phrase: "date: ISO-8601 YYYY-MM-DD"
# Context: other date spellings are cast failures.
def test_non_iso_date_fails_to_cast(run, csv_file, schema_file):
    schema = schema_file([("d", "date")])
    csv_file("a.csv", "d\n07/01/2024\n")
    res = run("--output", "-", "--key", "d", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode != 0


# Phrase: "timestamp: ISO-8601 format; normalize to UTC with Z suffix in output"
# Context: an offset-bearing timestamp is shifted to UTC.
def test_timestamp_offset_normalized_to_utc(run, csv_file, schema_file):
    schema = schema_file([("t", "timestamp")])
    csv_file("a.csv", "t\n2024-07-01T14:00:00+02:00\n")
    res = run("--output", "-", "--key", "t", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "t") == ["2024-07-01T12:00:00Z"]


# Phrase: "if source lacked zone, treat as UTC"
# Context: a naive timestamp keeps its wall clock and gains the Z suffix.
def test_naive_timestamp_treated_as_utc(run, csv_file, schema_file):
    schema = schema_file([("t", "timestamp")])
    csv_file("a.csv", "t\n2024-07-01T12:00:00\n")
    res = run("--output", "-", "--key", "t", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "t") == ["2024-07-01T12:00:00Z"]


# Phrase: "timestamp normalized to UTC with Z (e.g., 2024-07-01T12:00:00Z)"
# Context: a value already in the canonical form is unchanged.
def test_zulu_timestamp_is_stable(run, csv_file, schema_file):
    schema = schema_file([("t", "timestamp")])
    csv_file("a.csv", "t\n2024-07-01T12:00:00Z\n")
    res = run("--output", "-", "--key", "t", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "t") == ["2024-07-01T12:00:00Z"]


# Phrase: "timestamp: ISO-8601 format"
# Context: T12 — sub-second precision present in the input is preserved.
def test_timestamp_keeps_fractional_seconds(run, csv_file, schema_file):
    schema = schema_file([("t", "timestamp")])
    csv_file("a.csv", "t\n2024-07-01T12:00:00.250000Z\n")
    res = run("--output", "-", "--key", "t", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "t") == ["2024-07-01T12:00:00.250000Z"]


# Phrase: "timestamp: ISO-8601 format"
# Context: T2 — an explicit timestamp column accepts a date-only cell as midnight UTC.
def test_timestamp_accepts_date_only_value(run, csv_file, schema_file):
    schema = schema_file([("t", "timestamp")])
    csv_file("a.csv", "t\n2024-07-01\n")
    res = run("--output", "-", "--key", "t", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert column(res.stdout, "t") == ["2024-07-01T00:00:00Z"]


# Phrase: "coerce-null (default): emit null literal for that cell"
# Context: the default behaviour on a bad cast.
def test_coerce_null_is_the_default(run, csv_file, schema_file):
    schema = schema_file([("id", "int"), ("n", "int")])
    csv_file("a.csv", "id,n\n1,oops\n")
    default = run("--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "~", "a.csv")
    explicit = run(
        "--output", "-", "--key", "id", "--schema", schema,
        "--on-type-error", "coerce-null", "--csv-null-literal", "~", "a.csv",
    )
    assert default.returncode == 0, default.stderr
    assert column(default.stdout, "n") == ["~"]
    assert default.stdout == explicit.stdout


# Phrase: "fail: write error to stderr and exit non-zero"
# Context: T9 — the run aborts and explains itself on stderr.
def test_fail_mode_reports_and_exits_non_zero(run, csv_file, schema_file):
    schema = schema_file([("id", "int"), ("n", "int")])
    csv_file("a.csv", "id,n\n1,oops\n")
    res = run("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode != 0
    assert "oops" in res.stderr


# Phrase: "fail: ... exit non-zero"
# Context: a failing run must not leave a partial output file behind.
def test_fail_mode_leaves_no_output_file(run, csv_file, schema_file, tmp_path):
    schema = schema_file([("id", "int"), ("n", "int")])
    csv_file("a.csv", "id,n\n1,oops\n")
    res = run("--output", "out.csv", "--key", "id", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode != 0
    assert not (tmp_path / "out.csv").exists()


# Phrase: "keep-string: emit original text as string"
# Context: the uncastable cell survives verbatim.
def test_keep_string_preserves_original_text(run, csv_file, schema_file):
    schema = schema_file([("id", "int"), ("n", "int")])
    csv_file("a.csv", "id,n\n1,oops\n2,05\n")
    res = run("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "keep-string", "a.csv")
    assert column(res.stdout, "n") == ["oops", "5"]


# Phrase: "On cast failure, apply --on-type-error"
# Context: T5 — cast failures are possible under an inferred schema too, and a
#   null cell is never a cast failure.
def test_nulls_are_not_cast_failures(run, csv_file, schema_file):
    schema = schema_file([("id", "int"), ("n", "int"), ("t", "timestamp")])
    csv_file("a.csv", "id,n\n1,\n")
    res = run("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", "", ""]
