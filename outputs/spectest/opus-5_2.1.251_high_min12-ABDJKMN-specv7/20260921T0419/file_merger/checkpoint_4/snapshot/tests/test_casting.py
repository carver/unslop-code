"""Spec sections: Casting & Validation / Deterministic Dialect Details (temporal)."""
from conftest import body, header


# Phrase: "`int`, `float`, `string`: standard parsing"
# Context: Casting & Validation.
def test_int_cast_standard_parsing(run, work):
    work.schema("s.json", [("k", "int")])
    work.csv("a.csv", ["k"], [["42"], ["-7"], ["+3"]])
    r = run(
        "--output", "-", "--key", "k", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["-7"], ["3"], ["42"]]


def test_float_cast_standard_parsing(run, work):
    work.schema("s.json", [("k", "float")])
    work.csv("a.csv", ["k"], [["2.5"], ["-0.5"], ["1e2"]])
    r = run(
        "--output", "-", "--key", "k", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert [float(row[0]) for row in body(r)] == [-0.5, 2.5, 100.0]


def test_int_typed_column_of_floats_is_a_cast_failure(run, work):
    work.schema("s.json", [("k", "int"), ("id", "int")])
    work.csv("a.csv", ["k", "id"], [["1.5", "1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["", "1"]]


def test_string_cast_keeps_text(run, work):
    work.schema("s.json", [("k", "string")])
    work.csv("a.csv", ["k"], [["007"]])
    r = run(
        "--output", "-", "--key", "k", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["007"]]


# Phrase: "`bool` includes `1`/`0` along with standard values"
# Context: Casting & Validation.
def test_bool_accepts_one_and_zero(run, work):
    work.schema("s.json", [("id", "int"), ("b", "bool")])
    work.csv("a.csv", ["id", "b"], [["1", "1"], ["2", "0"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["true", "false"]


def test_bool_accepts_true_false_case_insensitively(run, work):
    work.schema("s.json", [("id", "int"), ("b", "bool")])
    work.csv(
        "a.csv", ["id", "b"],
        [["1", "true"], ["2", "False"], ["3", "TRUE"], ["4", "false"]],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["true", "false", "true", "false"]


def test_bool_sorts_false_before_true(run, work):
    work.schema("s.json", [("b", "bool"), ("v", "string")])
    work.csv("a.csv", ["b", "v"], [["true", "t"], ["false", "f"]])
    r = run(
        "--output", "-", "--key", "b", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["f", "t"]


# Phrase: "`date`: ISO-8601 `YYYY-MM-DD`"
# Context: Casting & Validation.
def test_date_cast_iso(run, work):
    work.schema("s.json", [("d", "date")])
    work.csv("a.csv", ["d"], [["2024-07-01"], ["2023-01-31"]])
    r = run(
        "--output", "-", "--key", "d", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["2023-01-31"], ["2024-07-01"]]


def test_non_iso_date_is_cast_failure(run, work):
    work.schema("s.json", [("id", "int"), ("d", "date")])
    work.csv("a.csv", ["id", "d"], [["1", "07/01/2024"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


# Phrase: "`date` stays `YYYY-MM-DD`"
# Context: Deterministic Dialect Details; no time component is added.
def test_date_output_format_unchanged(run, work):
    work.schema("s.json", [("d", "date")])
    work.csv("a.csv", ["d"], [["2024-07-01"]])
    r = run(
        "--output", "-", "--key", "d", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["2024-07-01"]]


# Phrase: "`timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output"
# Context: Casting & Validation + Deterministic Dialect Details.
def test_timestamp_offset_normalized_to_utc(run, work):
    work.schema("s.json", [("id", "int"), ("t", "timestamp")])
    work.csv(
        "a.csv", ["id", "t"],
        [["1", "2024-07-01T14:00:00+02:00"], ["2", "2024-07-01T07:00:00-05:00"]],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == [
        "2024-07-01T12:00:00Z", "2024-07-01T12:00:00Z",
    ]


def test_timestamp_z_input_preserved(run, work):
    work.schema("s.json", [("t", "timestamp")])
    work.csv("a.csv", ["t"], [["2024-07-01T12:00:00Z"]])
    r = run(
        "--output", "-", "--key", "t", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["2024-07-01T12:00:00Z"]]


# Phrase: "if source lacked zone, treat as UTC"
# Context: Deterministic Dialect Details.
def test_naive_timestamp_treated_as_utc(run, work):
    work.schema("s.json", [("t", "timestamp")])
    work.csv("a.csv", ["t"], [["2024-07-01T12:00:00"]])
    r = run(
        "--output", "-", "--key", "t", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["2024-07-01T12:00:00Z"]]


# Phrase: "keeping fractional seconds"
# Context: Deterministic Dialect Details.
def test_timestamp_keeps_fractional_seconds(run, work):
    work.schema("s.json", [("t", "timestamp")])
    work.csv("a.csv", ["t"], [["2024-07-01T12:00:00.123Z"]])
    r = run(
        "--output", "-", "--key", "t", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r)[0][0].startswith("2024-07-01T12:00:00.123")
    assert body(r)[0][0].endswith("Z")


def test_timestamp_without_fraction_has_no_decimal_point(run, work):
    work.schema("s.json", [("t", "timestamp")])
    work.csv("a.csv", ["t"], [["2024-07-01T12:00:00Z"]])
    r = run(
        "--output", "-", "--key", "t", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert "." not in body(r)[0][0]


# Phrase: "`timestamp`: ISO-8601 format"
# Context: Casting & Validation; a space-separated ISO form is accepted and normalized.
def test_timestamp_space_separator_normalized_to_T(run, work):
    work.schema("s.json", [("t", "timestamp")])
    work.csv("a.csv", ["t"], [["2024-07-01 12:00:00"]])
    r = run(
        "--output", "-", "--key", "t", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["2024-07-01T12:00:00Z"]]


# Phrase: "On cast failure, apply `--on-type-error`: coerce-null (default)"
# Context: Casting & Validation.
def test_coerce_null_is_default(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "abc"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


def test_coerce_null_uses_null_literal(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "abc"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "coerce-null", "--csv-null-literal", "NULL",
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "NULL"]]


# Phrase: "fail: write error to stderr and exit non-zero"
# Context: Casting & Validation.
def test_fail_mode_exits_non_zero_with_stderr(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "abc"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.csv"),
    )
    assert r.returncode != 0
    assert r.stderr.strip() != ""


def test_fail_mode_succeeds_when_all_casts_valid(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "2"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "2"]]


# Phrase: "keep-string: emit original text as string"
# Context: Casting & Validation.
def test_keep_string_emits_original_text(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "abc"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "keep-string", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "abc"]]


def test_keep_string_only_affects_failing_cells(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "abc"], ["2", "007"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "keep-string", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "abc"], ["2", "7"]]


# Phrase: "On cast failure ..."; empty cells are nulls, not cast failures.
# Context: Casting & Validation + Output null handling.
def test_empty_cell_is_null_not_cast_failure(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", ""]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: Casting & Validation.
def test_key_not_in_schema_is_error(run, work):
    work.schema("s.json", [("id", "int")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "nope", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.returncode != 0
    assert r.stderr.strip() != ""


def test_key_not_in_inferred_schema_is_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "missing", work.path("a.csv"))
    assert r.returncode != 0
    assert r.stderr.strip() != ""


def test_key_present_in_schema_but_absent_from_inputs_is_ok(run, work):
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "k", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


# Phrase: "one of several composite keys not in schema is an error"
# Context: Casting & Validation; validation covers every key column.
def test_second_key_not_in_schema_is_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "id,missing", work.path("a.csv"))
    assert r.returncode != 0
