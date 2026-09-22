"""Spec section: Casting & Validation (+ Deterministic Dialect temporal outputs)."""

import pytest

from conftest import body, col, run, run_ok, write, write_schema


def one_col(ws, typ, values, extra=(), name="v"):
    """Build a single-typed-column input + schema; return (csv_path, schema_path)."""
    a = write(ws / "a.csv", f"{name}\n" + "".join(v + "\n" for v in values))
    s = write_schema(ws / "s.json", [(name, typ)])
    return a, s


def cast(ws, typ, values, *flags):
    a, s = one_col(ws, typ, values)
    res = run_ok("--output", "-", "--key", "v", "--schema", s, *flags, a)
    return col(res.stdout, "v")


# --- Spec: "`int` ... standard parsing" ---
# Context: Casting & Validation.
@pytest.mark.parametrize("text,expected", [
    ("0", "0"), ("7", "7"), ("-7", "-7"), ("+7", "7"), ("007", "7"),
    ("1000000", "1000000"),
])
def test_int_parsing(ws, text, expected):
    assert cast(ws, "int", [text]) == [expected]


# --- Spec: "`float` ... standard parsing" ---
# Context: Casting & Validation; see AMBIGUITIES T4 for the output rendering.
@pytest.mark.parametrize("text,expected", [
    ("1.5", "1.5"), ("1", "1.0"), ("-0.25", "-0.25"), ("1e3", "1000.0"),
    ("0.0", "0.0"), ("1.50", "1.5"),
])
def test_float_parsing_and_rendering(ws, text, expected):
    assert cast(ws, "float", [text]) == [expected]


# --- Spec: "`string`: standard parsing" ---
# Context: Casting & Validation; text passes through unchanged.
@pytest.mark.parametrize("text", ["abc", "007", "1.50", " padded ", "TRUE"])
def test_string_passthrough(ws, text):
    assert cast(ws, "string", [text]) == [text]


# --- Spec: "`bool` includes `1`/`0` along with standard values" ---
# Context: Casting & Validation; see AMBIGUITIES T3 (lowercase rendering)
# and T18 (accepted literals).
@pytest.mark.parametrize("text,expected", [
    ("1", "true"), ("0", "false"),
    ("true", "true"), ("false", "false"),
    ("True", "true"), ("False", "false"),
    ("TRUE", "true"), ("FALSE", "false"),
])
def test_bool_parsing(ws, text, expected):
    assert cast(ws, "bool", [text]) == [expected]


# --- Spec: "`date`: ISO-8601 `YYYY-MM-DD`" ---
# Context: Casting & Validation + "date stays YYYY-MM-DD" on output.
@pytest.mark.parametrize("text", ["2024-07-01", "1999-12-31", "2024-02-29"])
def test_date_parsing_round_trips(ws, text):
    assert cast(ws, "date", [text]) == [text]


# --- Spec: "`date`: ISO-8601 `YYYY-MM-DD`" (rejects other shapes) ---
# Context: Casting & Validation; non-conforming text is a cast failure.
@pytest.mark.parametrize("text", ["07/01/2024", "2024-13-01", "2024-07-32", "20240701"])
def test_date_rejects_non_iso(ws, text):
    assert cast(ws, "date", [text]) == [""]


# --- Spec: "`timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix" ---
# Context: Casting & Validation + Deterministic Dialect Details.
@pytest.mark.parametrize("text,expected", [
    ("2024-07-01T12:00:00Z", "2024-07-01T12:00:00Z"),
    ("2024-07-01T12:00:00+00:00", "2024-07-01T12:00:00Z"),
    ("2024-07-01T14:30:00+02:30", "2024-07-01T12:00:00Z"),
    ("2024-07-01T07:00:00-05:00", "2024-07-01T12:00:00Z"),
])
def test_timestamp_normalized_to_utc_z(ws, text, expected):
    assert cast(ws, "timestamp", [text]) == [expected]


# --- Spec: "if source lacked zone, treat as UTC" ---
# Context: Deterministic Dialect Details / temporal outputs.
def test_naive_timestamp_treated_as_utc(ws):
    assert cast(ws, "timestamp", ["2024-07-01T12:00:00"]) == ["2024-07-01T12:00:00Z"]


# --- Spec: "`timestamp`: ISO-8601 format" (liberal input forms) ---
# Context: Casting & Validation; see AMBIGUITIES T5.
@pytest.mark.parametrize("text,expected", [
    ("2024-07-01 12:00:00", "2024-07-01T12:00:00Z"),
    ("2024-07-01T12:00:00.000Z", "2024-07-01T12:00:00Z"),
    ("2024-07-01", "2024-07-01T00:00:00Z"),
])
def test_timestamp_liberal_inputs(ws, text, expected):
    assert cast(ws, "timestamp", [text]) == [expected]


# --- Spec: "`timestamp`: ISO-8601 format" (rejects non-ISO text) ---
# Context: Casting & Validation.
def test_timestamp_rejects_garbage(ws):
    assert cast(ws, "timestamp", ["yesterday"]) == [""]


# --- Spec: "On cast failure, apply --on-type-error: coerce-null (default):
#            emit null literal for that cell" ---
# Context: Casting & Validation.
def test_coerce_null_is_the_default(ws):
    a, s = one_col(ws, "int", ["1", "oops"])
    default = run_ok("--output", "-", "--key", "v", "--schema", s, a)
    explicit = run_ok("--output", "-", "--key", "v", "--schema", s,
                      "--on-type-error", "coerce-null", a)
    assert default.stdout == explicit.stdout
    assert col(default.stdout, "v") == ["", "1"]


# --- Spec: "coerce-null ... emit null literal for that cell" ---
# Context: Casting & Validation; the literal honours --csv-null-literal.
def test_coerce_null_uses_null_literal(ws):
    a, s = one_col(ws, "int", ["oops"])
    res = run_ok("--output", "-", "--key", "v", "--schema", s,
                 "--on-type-error", "coerce-null", "--csv-null-literal", "<NA>", a)
    assert col(res.stdout, "v") == ["<NA>"]


# --- Spec: "fail: write error to stderr and exit non-zero" ---
# Context: Casting & Validation; see AMBIGUITIES T12.
def test_fail_mode_exits_non_zero_with_stderr(ws):
    a, s = one_col(ws, "int", ["1", "oops"])
    res = run("--output", "-", "--key", "v", "--schema", s, "--on-type-error", "fail", a)
    assert not res.ok
    assert res.stderr.strip() != ""


# --- Spec: "fail: ... exit non-zero" only when a cast actually fails ---
# Context: Casting & Validation.
def test_fail_mode_succeeds_on_clean_input(ws):
    a, s = one_col(ws, "int", ["2", "1"])
    res = run_ok("--output", "-", "--key", "v", "--schema", s,
                 "--on-type-error", "fail", a)
    assert col(res.stdout, "v") == ["1", "2"]


# --- Spec: "fail: write error to stderr" and produce no output file ---
# Context: Casting & Validation + "All intermediate resources must be cleaned up";
# see AMBIGUITIES T12.
def test_fail_mode_writes_no_output_file(ws):
    a, s = one_col(ws, "int", ["oops"])
    out = ws / "out.csv"
    res = run("--output", str(out), "--key", "v", "--schema", s,
              "--on-type-error", "fail", a)
    assert not res.ok
    assert not out.exists()


# --- Spec: "keep-string: emit original text as string" ---
# Context: Casting & Validation.
def test_keep_string_emits_original_text(ws):
    a, s = one_col(ws, "int", ["1", "oops"])
    res = run_ok("--output", "-", "--key", "v", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert sorted(col(res.stdout, "v")) == ["1", "oops"]


# --- Spec: "keep-string: emit original text as string" ---
# Context: Casting & Validation; well-formed cells still cast normally.
def test_keep_string_leaves_good_cells_cast(ws):
    a = write(ws / "a.csv", "k,v\n1,2.50\n2,nope\n")
    s = write_schema(ws / "s.json", [("k", "int"), ("v", "float")])
    res = run_ok("--output", "-", "--key", "k", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert col(res.stdout, "v") == ["2.5", "nope"]


# --- Spec: "keep-string" residue in a key column sorts after cast values ---
# Context: Casting & Validation + Sorting; see AMBIGUITIES T9.
def test_keep_string_residue_sorts_after_values(ws):
    a, s = one_col(ws, "int", ["10", "zz", "9", ""])
    res = run_ok("--output", "-", "--key", "v", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert col(res.stdout, "v") == ["", "9", "10", "zz"]


# --- Spec: an empty cell is a missing value, not a cast failure ---
# Context: Casting & Validation; see AMBIGUITIES T8.
def test_empty_cell_is_null_not_a_cast_error(ws):
    a, s = one_col(ws, "int", ["", "1"])
    res = run_ok("--output", "-", "--key", "v", "--schema", s,
                 "--on-type-error", "fail", a)
    assert col(res.stdout, "v") == ["", "1"]


# --- Spec: "--on-type-error {coerce-null,fail,keep-string}" ---
# Context: Usage; unknown modes are a usage error.
def test_invalid_on_type_error_mode_rejected(ws):
    a, s = one_col(ws, "int", ["1"])
    res = run("--output", "-", "--key", "v", "--schema", s,
              "--on-type-error", "explode", a)
    assert not res.ok


# --- Spec: "Cast every input cell into target type" applies to non-key columns ---
# Context: Casting & Validation.
def test_casting_applies_to_non_key_columns(ws):
    a = write(ws / "a.csv", "k,ts\n1,2024-07-01T00:00:00+01:00\n")
    s = write_schema(ws / "s.json", [("k", "int"), ("ts", "timestamp")])
    res = run_ok("--output", "-", "--key", "k", "--schema", s, a)
    assert col(res.stdout, "ts") == ["2024-06-30T23:00:00Z"]


# --- Spec: "int ... standard parsing" rejects non-integer numerals ---
# Context: Casting & Validation; see AMBIGUITIES T17.
@pytest.mark.parametrize("text", ["1.0", "1e3", "abc", "1_0", " 7 "])
def test_int_rejects_non_integer_text(ws, text):
    assert cast(ws, "int", [text]) == [""]


# --- Spec: "float ... standard parsing" rejects non-numeric text ---
# Context: Casting & Validation; see AMBIGUITIES T17.
@pytest.mark.parametrize("text", ["abc", "1.2.3", "nan", "inf"])
def test_float_rejects_non_numeric_text(ws, text):
    assert cast(ws, "float", [text]) == [""]


# --- Spec: "bool includes 1/0 along with standard values" and nothing else ---
# Context: Casting & Validation; see AMBIGUITIES T18.
@pytest.mark.parametrize("text", ["yes", "2", "t", "on"])
def test_bool_rejects_non_standard_literals(ws, text):
    assert cast(ws, "bool", [text]) == [""]
