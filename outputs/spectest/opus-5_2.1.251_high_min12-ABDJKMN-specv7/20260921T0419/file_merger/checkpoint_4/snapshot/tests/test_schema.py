"""Spec section: Schema Resolution & Column Order."""
import json

from conftest import body, header


# Phrase: "If `--schema` is provided: JSON file with exact output schema and column order"
# Context: Schema Resolution 1.
def test_schema_defines_exact_columns_and_order(run, work):
    work.write(
        "s.json",
        json.dumps({"columns": [
            {"name": "id", "type": "int"},
            {"name": "ts", "type": "timestamp"},
            {"name": "amount", "type": "float"},
            {"name": "note", "type": "string"},
            {"name": "is_active", "type": "bool"},
        ]}),
    )
    work.csv(
        "a.csv", ["note", "id", "is_active", "amount", "ts"],
        [["hi", "7", "true", "1.25", "2024-07-01T12:00:00Z"]],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id", "ts", "amount", "note", "is_active"]
    assert body(r) == [["7", "2024-07-01T12:00:00Z", "1.25", "hi", "true"]]


# Phrase: "Valid types: `string`, `int`, `float`, `bool`, `date`, `timestamp`"
# Context: Schema Resolution 1.
def test_all_valid_schema_types_accepted(run, work):
    work.schema(
        "s.json",
        [("s", "string"), ("i", "int"), ("f", "float"),
         ("b", "bool"), ("d", "date"), ("t", "timestamp")],
    )
    work.csv(
        "a.csv", ["s", "i", "f", "b", "d", "t"],
        [["x", "1", "2.5", "0", "2024-01-02", "2024-01-02T03:04:05Z"]],
    )
    r = run(
        "--output", "-", "--key", "i", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["x", "1", "2.5", "false", "2024-01-02", "2024-01-02T03:04:05Z"]]


# Checkpoint 4 note: `integer` became a built-in alias for `int`, so the
# unknown type here is one no alias table defines.
def test_invalid_schema_type_is_error(run, work):
    work.schema("s.json", [("id", "blobbo")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.returncode != 0
    assert r.stderr.strip() != ""


# Phrase: "Extra input columns not in schema are ignored"
# Context: Schema Resolution 1.
def test_extra_input_columns_ignored(run, work):
    work.schema("s.json", [("id", "int")])
    work.csv("a.csv", ["id", "junk"], [["1", "drop me"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id"]
    assert body(r) == [["1"]]


# Phrase: "Missing input columns filled with null literal"
# Context: Schema Resolution 1.
def test_schema_column_missing_from_input_is_null(run, work):
    work.schema("s.json", [("id", "int"), ("note", "string")])
    work.csv("a.csv", ["id"], [["1"]])
    work.csv("b.csv", ["id", "note"], [["2", "hi"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""], ["2", "hi"]]


# Phrase: "Cast every input cell into target type"
# Context: Schema Resolution 1; the schema type wins over what the text looks like.
def test_schema_type_forces_cast(run, work):
    work.schema("s.json", [("id", "int"), ("v", "string")])
    work.csv("a.csv", ["id", "v"], [["007", "1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["7", "1"]]


# Phrase: "If `--schema` not provided: infer schema from union of all input headers"
# Context: Schema Resolution 2.
def test_inferred_schema_is_union_of_headers(run, work):
    work.csv("a.csv", ["id", "a"], [["1", "x"]])
    work.csv("b.csv", ["id", "b"], [["2", "y"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert header(r) == ["a", "b", "id"]
    assert body(r) == [["x", "", "1"], ["", "y", "2"]]


# Phrase: "Column order: ascending lexicographic order of column names"
# Context: Schema Resolution 2.
def test_inferred_columns_sorted_lexicographically(run, work):
    work.csv("a.csv", ["zeta", "Alpha", "beta"], [["1", "2", "3"]])
    r = run("--output", "-", "--key", "beta", work.path("a.csv"))
    assert r.ok, r.stderr
    assert header(r) == sorted(["zeta", "Alpha", "beta"])


# Phrase: "Missing columns in a file filled with null literal"
# Context: Schema Resolution 2.
def test_inferred_missing_column_filled_with_null(run, work):
    work.csv("a.csv", ["id", "only_a"], [["1", "x"]])
    work.csv("b.csv", ["id"], [["2"]])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "-",
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "x"], ["2", "-"]]


# Phrase: "strict (default): infer types based on observed values"
# Context: Schema Resolution 2; observed values drive the type (numeric sort proves int).
def test_strict_infers_int_from_values(run, work):
    work.csv("a.csv", ["id"], [["10"], ["9"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["9"], ["10"]]


def test_strict_is_the_default_infer_mode(run, work):
    work.csv("a.csv", ["id"], [["2"], ["10"]])
    default = run("--output", "-", "--key", "id", work.path("a.csv"))
    explicit = run(
        "--output", "-", "--key", "id", "--infer", "strict", work.path("a.csv")
    )
    assert default.ok and explicit.ok, default.stderr + explicit.stderr
    assert default.stdout == explicit.stdout


# Phrase: "columns with conflicting types across files fall back to `string`"
# Context: Schema Resolution 2, strict mode.
def test_strict_conflicting_types_fall_back_to_string(run, work):
    work.csv("a.csv", ["k"], [["10"], ["9"]])
    work.csv("b.csv", ["k"], [["abc"]])
    r = run(
        "--output", "-", "--key", "k", "--infer", "strict",
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    # string ordering, not numeric
    assert body(r) == [["10"], ["9"], ["abc"]]


def test_strict_int_and_float_across_files_fall_back_to_string(run, work):
    work.csv("a.csv", ["k"], [["10"]])
    work.csv("b.csv", ["k"], [["9.5"]])
    r = run(
        "--output", "-", "--key", "k", "--infer", "strict",
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["10"], ["9.5"]]


# Phrase: "loose: prefer numeric/temporal types if all non-null observed values parse"
# Context: Schema Resolution 2, loose mode.
def test_loose_unifies_int_and_float_across_files(run, work):
    work.csv("a.csv", ["k"], [["10"]])
    work.csv("b.csv", ["k"], [["9.5"]])
    r = run(
        "--output", "-", "--key", "k", "--infer", "loose",
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["9.5"], ["10.0"]]


def test_loose_prefers_temporal_when_all_values_parse(run, work):
    work.csv("a.csv", ["t"], [["2024-07-01T12:00:00+02:00"]])
    work.csv("b.csv", ["t"], [["2024-07-01T09:30:00Z"]])
    r = run(
        "--output", "-", "--key", "t", "--infer", "loose",
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["2024-07-01T09:30:00Z"], ["2024-07-01T10:00:00Z"]]


# Phrase: "otherwise fall back to `string`"
# Context: Schema Resolution 2, loose mode.
def test_loose_falls_back_to_string(run, work):
    work.csv("a.csv", ["k"], [["10"], ["abc"]])
    r = run("--output", "-", "--key", "k", "--infer", "loose", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["10"], ["abc"]]


# Phrase: "empty strings are treated as nulls and don't affect inference"
# Context: Schema Resolution 2, loose mode.
def test_loose_ignores_empty_strings_for_inference(run, work):
    work.csv("a.csv", ["k", "v"], [["10", "a"], ["", "b"], ["9", "c"]])
    r = run("--output", "-", "--key", "k", "--infer", "loose", work.path("a.csv"))
    assert r.ok, r.stderr
    # k stays numeric (9 before 10), the blank cell is a null and sorts first
    assert body(r) == [["", "b"], ["9", "c"], ["10", "a"]]


# Phrase: "Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`"
# Context: Schema Resolution; used when several types could describe the values.
def test_priority_prefers_bool_over_int_for_zero_one(run, work):
    work.csv("a.csv", ["flag", "id"], [["1", "1"], ["0", "2"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["true", "false"]


def test_priority_prefers_int_over_float(run, work):
    work.csv("a.csv", ["k"], [["3"], ["2"]])
    r = run("--output", "-", "--key", "k", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["2"], ["3"]]


def test_priority_prefers_date_over_string(run, work):
    work.csv("a.csv", ["d"], [["2024-01-02"], ["2023-12-31"]])
    r = run("--output", "-", "--key", "d", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["2023-12-31"], ["2024-01-02"]]


# Phrase: "Inference recognises values by the casting rules below"
# Context: Schema Resolution; e.g. bool values true/false are recognised.
def test_inference_recognises_bool_words(run, work):
    work.csv("a.csv", ["flag", "id"], [["true", "1"], ["FALSE", "2"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["true", "false"]


# Phrase: "If `--schema` is provided ... exact output schema"
# Context: Schema Resolution 1; --infer is irrelevant when a schema is given.
def test_schema_overrides_inference(run, work):
    work.schema("s.json", [("k", "string")])
    work.csv("a.csv", ["k"], [["10"], ["9"]])
    r = run(
        "--output", "-", "--key", "k", "--schema", work.path("s.json"),
        "--infer", "loose", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["10"], ["9"]]
