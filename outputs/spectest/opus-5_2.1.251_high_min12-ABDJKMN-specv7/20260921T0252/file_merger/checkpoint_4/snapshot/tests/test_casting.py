"""Spec section: Casting & Validation."""
from conftest import run_tool, write_csv, write_schema, col


def one(tmp_path, columns, lines, key=None, *extra):
    schema = write_schema(tmp_path / "s.json", columns)
    src = write_csv(tmp_path / "a.csv", lines)
    key = key or columns[0][0]
    return run_tool("--output", "-", "--key", key, "--schema", schema,
                    *(list(extra) + [src]))


# Phrase: "int ... standard parsing"
# Context: plain, signed and zero-padded integers all parse.
def test_int_standard_parsing(tmp_path):
    res = one(tmp_path, [("n", "int")], ["n", "42", "-7", "+3", "007"])
    assert sorted(int(v) for v in col(res.rows(), "n")) == [-7, 3, 7, 42]


# Phrase: "int ... standard parsing"
# Context: a non integer is not an int.
def test_int_rejects_non_integer(tmp_path):
    res = one(tmp_path, [("n", "int")], ["n", "1.5"], None,
              "--on-type-error", "keep-string")
    assert col(res.rows(), "n") == ["1.5"]


# Phrase: "float ... standard parsing"
# Context: decimal and exponent notation parse.
def test_float_standard_parsing(tmp_path):
    res = one(tmp_path, [("n", "float")], ["n", "1.5", "-0.25", "2e3", ".5"])
    assert sorted(float(v) for v in col(res.rows(), "n")) == [-0.25, 0.5, 1.5,
                                                              2000.0]


# Phrase: "bool includes 1/0 along with standard values"
# Context: both 1/0 and true/false are recognised.
def test_bool_accepts_one_zero_and_words(tmp_path):
    res = one(tmp_path, [("b", "bool"), ("i", "int")],
              ["b,i", "1,1", "0,2", "true,3", "false,4"], "i")
    assert col(res.rows(), "b") == ["true", "false", "true", "false"]


# Phrase: "bool includes 1/0 along with standard values"
# Context: case variations of the standard words are recognised.
def test_bool_is_case_insensitive(tmp_path):
    res = one(tmp_path, [("b", "bool"), ("i", "int")],
              ["b,i", "TRUE,1", "False,2"], "i")
    assert col(res.rows(), "b") == ["true", "false"]


# Phrase: "bool ..."
# Context: an unrecognised word is a cast failure.
def test_bool_rejects_other_words(tmp_path):
    res = one(tmp_path, [("b", "bool"), ("i", "int")],
              ["b,i", "maybe,1"], "i", "--on-type-error", "keep-string")
    assert col(res.rows(), "b") == ["maybe"]


# Phrase: "date: ISO-8601 YYYY-MM-DD"
# Context: the documented form parses.
def test_date_iso_form(tmp_path):
    res = one(tmp_path, [("d", "date")], ["d", "2024-07-01"])
    assert col(res.rows(), "d") == ["2024-07-01"]


# Phrase: "date: ISO-8601 YYYY-MM-DD"
# Context: other layouts are cast failures.
def test_date_rejects_other_layouts(tmp_path):
    res = one(tmp_path, [("d", "date"), ("i", "int")],
              ["d,i", "07/01/2024,1", "20240701,2"], "i",
              "--on-type-error", "keep-string")
    assert col(res.rows(), "d") == ["07/01/2024", "20240701"]


# Phrase: "date: ISO-8601 YYYY-MM-DD"
# Context: an impossible calendar date is a cast failure.
def test_date_rejects_invalid_calendar_date(tmp_path):
    res = one(tmp_path, [("d", "date"), ("i", "int")],
              ["d,i", "2024-02-31,1"], "i", "--on-type-error", "coerce-null")
    assert col(res.rows(), "d") == [""]


# Phrase: "timestamp: ISO-8601 format; normalize to UTC with Z suffix"
# Context: an offset is converted to UTC.
def test_timestamp_offset_normalised_to_utc(tmp_path):
    res = one(tmp_path, [("ts", "timestamp")],
              ["ts", "2024-07-01T14:30:00+02:00"])
    assert col(res.rows(), "ts") == ["2024-07-01T12:30:00Z"]


# Phrase: "normalize to UTC with Z suffix in output"
# Context: an already-UTC value keeps the Z suffix.
def test_timestamp_utc_keeps_z(tmp_path):
    res = one(tmp_path, [("ts", "timestamp")], ["ts", "2024-07-01T12:00:00Z"])
    assert col(res.rows(), "ts") == ["2024-07-01T12:00:00Z"]


# Phrase: "normalize to UTC with Z (e.g., 2024-07-01T12:00:00Z)"
# Context: the exact example from the spec.
def test_timestamp_spec_example(tmp_path):
    res = one(tmp_path, [("ts", "timestamp")],
              ["ts", "2024-07-01T12:00:00+00:00"])
    assert col(res.rows(), "ts") == ["2024-07-01T12:00:00Z"]


# Phrase: "keeping fractional seconds"
# Context: sub-second precision is not discarded.
def test_timestamp_keeps_fractional_seconds(tmp_path):
    res = one(tmp_path, [("ts", "timestamp")],
              ["ts", "2024-07-01T12:00:00.123456Z"])
    assert col(res.rows(), "ts") == ["2024-07-01T12:00:00.123456Z"]


# Phrase: "if source lacked zone, treat as UTC"
# Context: a naive timestamp is not shifted.
def test_timestamp_naive_treated_as_utc(tmp_path):
    res = one(tmp_path, [("ts", "timestamp")], ["ts", "2024-07-01T12:00:00"])
    assert col(res.rows(), "ts") == ["2024-07-01T12:00:00Z"]


# Phrase: "timestamp: ISO-8601 format"
# Context: a negative offset is converted to UTC.
def test_timestamp_negative_offset(tmp_path):
    res = one(tmp_path, [("ts", "timestamp")],
              ["ts", "2024-07-01T06:00:00-05:00"])
    assert col(res.rows(), "ts") == ["2024-07-01T11:00:00Z"]


# Phrase: "timestamp: ISO-8601 format"
# Context: garbage is a cast failure.
def test_timestamp_rejects_garbage(tmp_path):
    res = one(tmp_path, [("ts", "timestamp"), ("i", "int")],
              ["ts,i", "not-a-time,1"], "i")
    assert col(res.rows(), "ts") == [""]


# Phrase: "coerce-null (default): emit null literal for that cell"
# Context: default behaviour when the flag is omitted.
def test_coerce_null_is_default(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("n", "int"), ("i", "int")])
    src = write_csv(tmp_path / "a.csv", ["n,i", "oops,1"])
    res = run_tool("--output", "-", "--key", "i", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == [""]


# Phrase: "coerce-null ... emit null literal for that cell"
# Context: the null literal override is used for coerced cells too.
def test_coerce_null_uses_null_literal(tmp_path):
    res = one(tmp_path, [("n", "int"), ("i", "int")], ["n,i", "oops,1"], "i",
              "--on-type-error", "coerce-null", "--csv-null-literal", "NULL")
    assert col(res.rows(), "n") == ["NULL"]


# Phrase: "coerce-null ... for that cell"
# Context: only the failing cell is nulled, the rest of the row survives.
def test_coerce_null_is_per_cell(tmp_path):
    res = one(tmp_path, [("n", "int"), ("s", "string")],
              ["n,s", "oops,keepme"], "s")
    assert res.rows()[1] == ["", "keepme"]


# Phrase: "fail: write error to stderr and exit non-zero"
# Context: a cast failure aborts the run.
def test_fail_mode_exits_non_zero_with_stderr(tmp_path):
    res = one(tmp_path, [("n", "int"), ("i", "int")], ["n,i", "oops,1"], "i",
              "--on-type-error", "fail")
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Phrase: "fail: ..."
# Context: clean data in fail mode succeeds.
def test_fail_mode_passes_clean_data(tmp_path):
    res = one(tmp_path, [("n", "int")], ["n", "1", "2"], None,
              "--on-type-error", "fail")
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["1", "2"]


# Phrase: "keep-string: emit original text as string"
# Context: the unparsed source text is preserved verbatim.
def test_keep_string_preserves_original_text(tmp_path):
    res = one(tmp_path, [("n", "int"), ("i", "int")],
              ["n,i", "12abc,1"], "i", "--on-type-error", "keep-string")
    assert col(res.rows(), "n") == ["12abc"]


# Phrase: "keep-string: emit original text as string"
# Context: successfully cast cells in the same column are still normalised.
def test_keep_string_only_affects_failures(tmp_path):
    res = one(tmp_path, [("n", "float"), ("i", "int")],
              ["n,i", "12abc,1", "3,2"], "i", "--on-type-error", "keep-string")
    assert col(res.rows(), "n") == ["12abc", "3.0"]


# Phrase: "Missing values emitted as the null literal" + casting
# Context: an empty cell is a null, not a cast failure, even in fail mode.
def test_empty_cell_is_null_not_a_cast_error(tmp_path):
    res = one(tmp_path, [("n", "int"), ("i", "int")],
              ["n,i", ",1"], "i", "--on-type-error", "fail")
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == [""]


# Phrase: "Cast every input cell into target type"
# Context: a string-typed column passes text through untouched.
def test_string_type_passes_text_through(tmp_path):
    res = one(tmp_path, [("s", "string")], ["s", "  padded  ", "2024-07-01"])
    assert sorted(col(res.rows(), "s")) == ["  padded  ", "2024-07-01"]
