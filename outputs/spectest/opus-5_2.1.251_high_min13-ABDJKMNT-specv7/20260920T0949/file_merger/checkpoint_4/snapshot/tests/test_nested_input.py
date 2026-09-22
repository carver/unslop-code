"""How each input format delivers nested values, and when nesting is refused."""

import pyarrow as pa

from conftest import array, cell, mapping, rows_of, struct


# Spec: "JSONL: Accept nested objects/arrays only when schema declares column as
# nested or `json`"
def test_jsonl_nested_object_is_accepted_for_a_struct_column(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann", "age": 30}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("age", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann","age":30}'


# Spec: "JSONL: Accept nested objects/arrays only when schema declares column as
# nested or `json`"
def test_jsonl_nested_array_is_accepted_for_a_json_column(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "flex": [1, {"a": 2}]}])
    make_schema("s.json", [("id", "int"), ("flex", "json")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "flex") == '[1,{"a":2}]'


# Spec: "If schema declares flat type but input has object/array, handle per
# `--on-type-error`"
def test_jsonl_object_in_a_flat_column_coerces_to_null(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "v") == ""


# Spec: "If schema declares flat type but input has object/array, handle per
# `--on-type-error`" with "keep-string: set to original unparsed JSON string or
# stringified form"
def test_jsonl_object_in_a_flat_column_can_be_kept_as_its_json_text(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "keep-string", "a.jsonl",
    )
    assert cell(rows_of(proc.stdout), "v") == '{"a":1}'


# Spec: "If schema declares flat type but input has object/array, handle per
# `--on-type-error`" with "fail: emit `ERR 4 ...`"
def test_jsonl_object_in_a_flat_column_can_fail(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.jsonl", expect_ok=False,
    )
    assert proc.returncode == 4
    assert "ERR 4" in proc.stderr


# Spec: "Without `--schema`, nested inputs not allowed (error 6)" and
# "ERR 6 nested structure requires provided --schema"
def test_jsonl_nesting_without_a_schema_is_error_six(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann"}}])
    proc = run("--output", "-", "--key", "id", "a.jsonl", expect_ok=False)
    assert proc.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in proc.stderr


# Spec: "Parquet: Accept nested structs/lists/maps only when schema declares
# compatible nested types"
def test_parquet_struct_list_and_map_are_accepted(make_parquet, make_schema, run):
    make_parquet(
        "a.parquet",
        {
            "id": pa.array([1], type=pa.int64()),
            "user": pa.array([{"name": "ann", "age": 30}], type=pa.struct([("name", pa.string()), ("age", pa.int64())])),
            "items": pa.array([[{"sku": "x", "qty": 2}]], type=pa.list_(pa.struct([("sku", pa.string()), ("qty", pa.int64())]))),
            "attrs": pa.array([[("country", "US")]], type=pa.map_(pa.string(), pa.string())),
        },
    )
    make_schema(
        "s.json",
        [
            ("id", "int"),
            ("user", struct(("name", "string"), ("age", "int"))),
            ("items", array(struct(("sku", "string"), ("qty", "int")))),
            ("attrs", mapping("string")),
        ],
    )
    rows = rows_of(run("--output", "-", "--key", "id", "--schema", "s.json", "a.parquet").stdout)
    assert cell(rows, "user") == '{"name":"ann","age":30}'
    assert cell(rows, "items") == '[{"sku":"x","qty":2}]'
    assert cell(rows, "attrs") == '{"country":"US"}'


# Spec: "Parquet ... Without schema, nested triggers error 6"
def test_parquet_nesting_without_a_schema_is_error_six(make_parquet, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "user": pa.array([{"name": "ann"}])})
    proc = run("--output", "-", "--key", "id", "a.parquet", expect_ok=False)
    assert proc.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in proc.stderr


# Spec: "With `--schema`, Parquet/JSONL nesting must structurally match and cast
# recursively"
# Context: see AMBIGUITIES T59 - a list where a struct is declared is a cast
# failure, so --on-type-error decides.
def test_parquet_structural_mismatch_follows_the_type_error_policy(make_parquet, make_schema, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "user": pa.array([[1, 2]], type=pa.list_(pa.int64()))})
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.parquet")
    assert cell(rows_of(proc.stdout), "user") == ""


# Spec: "CSV/TSV: Cell must contain single JSON literal when target type is
# nested or `json`"
def test_csv_cell_carrying_a_json_literal_is_parsed(make_csv, make_schema, run):
    make_csv("a.csv", 'id,user\n1,"{""name"":""ann"",""age"":30}"\n')
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("age", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann","age":30}'


# Spec: "CSV/TSV ... Empty cell -> null"
def test_csv_empty_cell_for_a_nested_column_is_null(make_csv, make_schema, run):
    make_csv("a.csv", "id,user\n1,\n")
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert cell(rows_of(proc.stdout), "user") == ""


# Spec: "CSV/TSV ... Invalid JSON -> handled per `--on-type-error`/error 5"
def test_csv_invalid_json_coerces_to_null(make_csv, make_schema, run):
    make_csv("a.csv", "id,user\n1,{oops\n")
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert cell(rows_of(proc.stdout), "user") == ""


# Spec: "CSV/TSV ... Invalid JSON -> handled per `--on-type-error`/error 5"
# Context: see AMBIGUITIES T48 - under `fail` the unparsable cell is error 5.
def test_csv_invalid_json_under_fail_is_error_five(make_csv, make_schema, run):
    make_csv("a.csv", "id,user\n1,{oops\n")
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.csv", expect_ok=False,
    )
    assert proc.returncode == 5
    assert "ERR 5" in proc.stderr


# Spec: "CSV/TSV ... Invalid JSON -> handled per `--on-type-error`"
# Context: keep-string keeps the cell's own text.
def test_csv_invalid_json_can_be_kept_as_a_string(make_csv, make_schema, run):
    make_csv("a.csv", "id,user\n1,{oops\n")
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "keep-string", "a.csv",
    )
    assert cell(rows_of(proc.stdout), "user") == "{oops"


# Spec: "CSV/TSV: Cell must contain single JSON literal when target type is
# nested or `json`"
# Context: the same rule holds for the TSV dialect.
def test_tsv_cell_carrying_a_json_literal_is_parsed(make_text, make_schema, run):
    make_text("a.tsv", 'id\tns\n1\t[1, 2]\n')
    make_schema("s.json", [("id", "int"), ("ns", array("int"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.tsv")
    assert cell(rows_of(proc.stdout), "ns") == "[1,2]"


# Spec: "Without `--schema`: ... CSV/TSV cells containing JSON treated as string"
def test_csv_json_text_without_a_schema_stays_a_string(make_csv, run):
    make_csv("a.csv", 'id,user\n1,"{""name"":""ann""}"\n')
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann"}'


# Spec: "Without `--schema`: ... Inferred columns remain flat"
def test_inference_still_reads_flat_inputs(make_csv, run):
    make_csv("a.csv", "id,n\n7,5\n")
    rows = rows_of(run("--output", "-", "--key", "id", "a.csv").stdout)
    assert rows == [["id", "n"], ["7", "5"]]


# Spec: "With `--schema`, Parquet/JSONL nesting must structurally match"
# Context: see AMBIGUITIES T60 - with a schema present, a nested column the
# schema never mentions is simply dropped rather than error 6.
def test_nested_column_outside_the_schema_is_dropped(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "extra": {"a": 1}}])
    make_schema("s.json", [("id", "int")])
    rows = rows_of(run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl").stdout)
    assert rows == [["id"], ["1"]]
