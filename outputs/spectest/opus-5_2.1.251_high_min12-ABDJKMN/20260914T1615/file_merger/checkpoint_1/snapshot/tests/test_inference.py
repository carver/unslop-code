"""Spec section: Schema Resolution & Column Order — inferred schema (`--infer`)."""

from conftest import body, col, header, run_ok, write


# --- Spec: "If --schema not provided: infer schema from union of all input headers" ---
# Context: Schema Resolution item 2.
def test_union_of_all_input_headers(ws):
    a = write(ws / "a.csv", "id,alpha\n1,x\n")
    b = write(ws / "b.csv", "id,beta\n2,y\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert header(res.stdout) == ["alpha", "beta", "id"]


# --- Spec: "Column order: ascending lexicographic order of column names" ---
# Context: Schema Resolution item 2.
def test_inferred_column_order_is_lexicographic(ws):
    a = write(ws / "a.csv", "zz,mm\n1,2\n")
    b = write(ws / "b.csv", "aa,zz\n3,4\n")
    res = run_ok("--output", "-", "--key", "zz", a, b)
    assert header(res.stdout) == ["aa", "mm", "zz"]


# --- Spec: "ascending lexicographic order of column names" with mixed case ---
# Context: Schema Resolution item 2; see AMBIGUITIES T23 (code-point order).
def test_inferred_column_order_is_codepoint_lexicographic(ws):
    a = write(ws / "a.csv", "b,A,a,B\n1,2,3,4\n")
    res = run_ok("--output", "-", "--key", "a", a)
    assert header(res.stdout) == ["A", "B", "a", "b"]


# --- Spec: "strict (default)" ---
# Context: Schema Resolution item 2; omitting --infer behaves like --infer strict.
def test_strict_is_the_default_mode(ws):
    a = write(ws / "a.csv", "v\n1\n2\n")
    b = write(ws / "b.csv", "v\n1.5\n")
    default = run_ok("--output", "-", "--key", "v", a, b)
    strict = run_ok("--output", "-", "--key", "v", "--infer", "strict", a, b)
    assert default.stdout == strict.stdout


# --- Spec: "strict: ... columns with conflicting types across files fall back to string" ---
# Context: Schema Resolution item 2. int in one file, float in another -> string.
def test_strict_conflicting_types_across_files_fall_back_to_string(ws):
    a = write(ws / "a.csv", "v\n1\n2\n")
    b = write(ws / "b.csv", "v\n1.5\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "strict", a, b)
    assert col(res.stdout, "v") == ["1", "1.5", "2"]


# --- Spec: "loose: prefer numeric/temporal types if all non-null observed values parse" ---
# Context: Schema Resolution item 2. Same inputs as strict, but unified to float.
def test_loose_unifies_int_and_float_across_files(ws):
    a = write(ws / "a.csv", "v\n1\n2\n")
    b = write(ws / "b.csv", "v\n1.5\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "loose", a, b)
    assert col(res.stdout, "v") == ["1.0", "1.5", "2.0"]


# --- Spec: "strict: infer types based on observed values" ---
# Context: Files that agree keep the inferred type (no fallback).
def test_strict_agreeing_files_keep_inferred_type(ws):
    a = write(ws / "a.csv", "v\n10\n")
    b = write(ws / "b.csv", "v\n9\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "strict", a, b)
    assert col(res.stdout, "v") == ["9", "10"]


# --- Spec: "loose: ... otherwise fall back to string" ---
# Context: Schema Resolution item 2; a non-parsing value defeats numeric typing.
def test_loose_falls_back_to_string(ws):
    a = write(ws / "a.csv", "v\n10\n")
    b = write(ws / "b.csv", "v\nabc\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "loose", a, b)
    assert col(res.stdout, "v") == ["10", "abc"]


# --- Spec: "strict: columns with conflicting types across files fall back to string" ---
# Context: A text column beside a numeric column also conflicts.
def test_strict_string_vs_int_conflict_is_string(ws):
    a = write(ws / "a.csv", "v\n10\n")
    b = write(ws / "b.csv", "v\nabc\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "strict", a, b)
    assert col(res.stdout, "v") == ["10", "abc"]


# --- Spec: "loose: ... empty strings are treated as nulls and don't affect inference" ---
# Context: Schema Resolution item 2.
def test_loose_empty_strings_do_not_affect_inference(ws):
    a = write(ws / "a.csv", "v\n10\n\n9\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "loose", a)
    assert col(res.stdout, "v") == ["", "9", "10"]


# --- Spec: "empty strings are treated as nulls" ---
# Context: Schema Resolution item 2; this implementation applies it in strict too.
# See AMBIGUITIES T1.
def test_strict_empty_strings_treated_as_nulls(ws):
    a = write(ws / "a.csv", "v\n10\n\n9\n")
    res = run_ok("--output", "-", "--key", "v", "--infer", "strict", a)
    assert col(res.stdout, "v") == ["", "9", "10"]


# --- Spec: "infer types based on observed values" with no observed values ---
# Context: Schema Resolution item 2; an all-empty column has no evidence -> string.
def test_column_with_no_observed_values_is_string(ws):
    a = write(ws / "a.csv", "k,v\n1,\n2,\n")
    res = run_ok("--output", "-", "--key", "k", "--csv-null-literal", "NA", a)
    assert col(res.stdout, "v") == ["NA", "NA"]


# --- Spec: "Type priority: timestamp > date > bool > int > float > string" ---
# Context: applied to inference; 1/0 parse as bool, int and float -> bool wins.
# See AMBIGUITIES T2.
def test_priority_zero_one_column_infers_bool(ws):
    a = write(ws / "a.csv", "k,flag\n1,1\n2,0\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert col(res.stdout, "flag") == ["true", "false"]


# --- Spec: "Type priority: ... int > float" ---
# Context: a column that parses as both int and float is typed int.
def test_priority_int_beats_float(ws):
    a = write(ws / "k.csv", "k,v\n1,7\n2,8\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert col(res.stdout, "v") == ["7", "8"]


# --- Spec: "loose: prefer numeric ... types if all non-null observed values parse" ---
# Context: mixed int/float text within one column becomes float.
def test_mixed_int_and_float_values_infer_float(ws):
    a = write(ws / "a.csv", "k,v\n1,7\n2,8.5\n")
    res = run_ok("--output", "-", "--key", "k", "--infer", "loose", a)
    assert col(res.stdout, "v") == ["7.0", "8.5"]


# --- Spec: "prefer ... temporal types" — `date`: ISO-8601 YYYY-MM-DD ---
# Context: Schema Resolution item 2 + Casting; date-only text infers as date
# and keeps its YYYY-MM-DD rendering. See AMBIGUITIES T6.
def test_date_column_infers_as_date(ws):
    a = write(ws / "a.csv", "k,d\n2,2024-07-01\n1,2023-01-31\n")
    res = run_ok("--output", "-", "--key", "d", a)
    assert col(res.stdout, "d") == ["2023-01-31", "2024-07-01"]


# --- Spec: "prefer ... temporal types" — timestamp inference ---
# Context: values with a time component infer as timestamp and normalize to UTC.
def test_timestamp_column_infers_as_timestamp(ws):
    a = write(ws / "a.csv", "k,ts\n1,2024-07-01T12:00:00+02:00\n2,2024-07-01T09:00:00Z\n")
    res = run_ok("--output", "-", "--key", "ts", a)
    assert col(res.stdout, "ts") == ["2024-07-01T09:00:00Z", "2024-07-01T10:00:00Z"]


# --- Spec: "columns with conflicting types across files fall back to string" ---
# Context: the fallback keeps the original text of every cell verbatim.
def test_string_fallback_preserves_original_text(ws):
    a = write(ws / "a.csv", "k,v\n1,007\n")
    b = write(ws / "b.csv", "k,v\n2,x\n")
    res = run_ok("--output", "-", "--key", "k", a, b)
    assert col(res.stdout, "v") == ["007", "x"]


# --- Spec: "infer schema from union of all input headers" ---
# Context: a column present in only one file still appears in the output.
def test_column_unique_to_one_file_is_in_schema(ws):
    a = write(ws / "a.csv", "k\n1\n")
    b = write(ws / "b.csv", "k,only\n2,v\n")
    res = run_ok("--output", "-", "--key", "k", a, b)
    assert header(res.stdout) == ["k", "only"]
    assert body(res.stdout) == ["1,", "2,v"]


# --- Spec: "--infer {strict,loose}" ---
# Context: Usage; an unknown mode is a usage error.
def test_invalid_infer_mode_rejected(ws):
    from conftest import run
    a = write(ws / "a.csv", "k\n1\n")
    res = run("--output", "-", "--key", "k", "--infer", "wild", a)
    assert not res.ok


# --- Spec: bool inference from standard literals ---
# Context: Casting & Validation ("bool includes 1/0 along with standard values")
# combined with inference.
def test_true_false_column_infers_bool(ws):
    a = write(ws / "a.csv", "k,flag\n1,true\n2,FALSE\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert col(res.stdout, "flag") == ["true", "false"]
