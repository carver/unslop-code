"""Spec section: Input Handling for Nested (checkpoint 4)."""
import json

from conftest import (array_t, cell, col, map_t, needs_parquet, pa, run_tool,
                      struct_t, write_csv, write_file, write_json,
                      write_jsonl, write_nested_schema, write_parquet,
                      write_tsv)


# --------------------------------------------------------------------------
# Phrase: "JSONL: Accept nested objects/arrays only when schema declares
#          column as nested or json"
# Context: Input Handling for Nested.
# --------------------------------------------------------------------------
def test_jsonl_nested_object_with_struct_declaration(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("n", "string"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"n": "x"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"n":"x"}'


def test_jsonl_nested_array_with_array_declaration(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1, 2]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1,2]"


def test_jsonl_nested_value_with_json_declaration(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": [{"a": 1}]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "v") == '[{"a":1}]'


# Phrase: "If schema declares flat type but input has object/array, handle
#          per --on-type-error"
def test_jsonl_nested_against_flat_declaration_coerce_null(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "string"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "coerce-null", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == [""]


def test_jsonl_nested_against_flat_declaration_keep_string(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "string"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": {"b": 2, "a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ['{"a":1,"b":2}']


def test_jsonl_nested_against_flat_declaration_fail(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "int"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": [1]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert "ERR 4" in res.stderr


# Phrase: "Without --schema, nested inputs not allowed (error 6)"
def test_jsonl_nested_without_schema_is_error_6(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6
    assert "ERR 6" in res.stderr


def test_jsonl_nested_array_without_schema_is_error_6(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": []}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


# Phrase: "Accept nested objects/arrays only when schema declares column as
#          nested or json"
# Context: a column the schema does not declare is never materialised (T57).
def test_jsonl_nested_in_undeclared_column_is_ignored(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "junk": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows() == [["id"], ["1"]]


# Phrase: "JSONL: ... null permitted" (carried forward)
# Context: a null in a nested column is a null column value.
def test_jsonl_null_for_nested_column(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "t": None}, {"id": 2}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["", ""]


# --------------------------------------------------------------------------
# Phrase: "CSV/TSV: Cell must contain single JSON literal when target type is
#          nested or json"
# Context: Input Handling for Nested.
# --------------------------------------------------------------------------
def test_csv_cell_holding_json_for_nested_column(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("n", "string"),
                                                ("q", "int"))))
    src = write_csv(tmp_path / "a.csv",
                    ["id,u", '1,"{""n"": ""x"", ""q"": ""7""}"'])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"n":"x","q":7}'


def test_tsv_cell_holding_json_for_nested_column(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_tsv(tmp_path / "a.tsv", ["id\tt", '1\t[1, 2, 3]'])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1,2,3]"


# Phrase: "Empty cell -> null"
def test_csv_empty_cell_for_nested_column_is_null(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_csv(tmp_path / "a.csv", ["id,t", "1,", "2,[1]"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["", "[1]"]


def test_csv_null_literal_for_nested_column_is_null(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_csv(tmp_path / "a.csv", ["id,t", "1,NULL"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NULL", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["NULL"]


# Phrase: "Invalid JSON -> handled per --on-type-error/error 5"
def test_csv_invalid_json_coerce_null(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_csv(tmp_path / "a.csv", ["id,t", "1,[1,"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "coerce-null", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == [""]


def test_csv_invalid_json_keep_string(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_csv(tmp_path / "a.csv", ["id,t", "1,notjson"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["notjson"]


def test_csv_invalid_json_fail_is_nonzero(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_csv(tmp_path / "a.csv", ["id,t", "1,{oops}"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Phrase: "Inferred columns remain flat / CSV/TSV cells containing JSON
#          treated as string"
def test_csv_json_cell_without_schema_is_a_string(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,t", '1,"{""a"": 1}"'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ['{"a": 1}']


# --------------------------------------------------------------------------
# Phrase: "Parquet: Accept nested structs/lists/maps only when schema declares
#          compatible nested types"
# Context: Input Handling for Nested.
# --------------------------------------------------------------------------
@needs_parquet
def test_parquet_struct_with_struct_declaration(tmp_path):
    arrow = pa.schema([("id", pa.int64()),
                       ("u", pa.struct([("n", pa.string()),
                                        ("q", pa.int64())]))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "u": [{"n": "x", "q": 4}]}, schema=arrow)
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("n", "string"),
                                                ("q", "int"))))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"n":"x","q":4}'


@needs_parquet
def test_parquet_list_with_array_declaration(tmp_path):
    arrow = pa.schema([("id", pa.int64()), ("t", pa.list_(pa.string()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "t": [["a", "b"]]}, schema=arrow)
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("string")))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == '["a","b"]'


@needs_parquet
def test_parquet_map_with_map_declaration(tmp_path):
    arrow = pa.schema([("id", pa.int64()),
                       ("m", pa.map_(pa.string(), pa.int64()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "m": [[("b", 2), ("a", 1)]]}, schema=arrow)
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", map_t("int")))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"a":1,"b":2}'


@needs_parquet
def test_parquet_nested_timestamps_normalise(tmp_path):
    arrow = pa.schema([("id", pa.int64()),
                       ("u", pa.struct([("ts", pa.timestamp("ms"))]))])
    import datetime as _dt
    value = _dt.datetime(2024, 3, 4, 5, 6, 7)
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "u": [{"ts": value}]}, schema=arrow)
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("ts", "timestamp"))))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"ts":"2024-03-04T05:06:07Z"}'


@needs_parquet
def test_parquet_nested_null_is_a_null_column_value(tmp_path):
    arrow = pa.schema([("id", pa.int64()), ("t", pa.list_(pa.int64()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1, 2], "t": [None, [3]]}, schema=arrow)
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["", "[3]"]


# Phrase: "Without schema, nested triggers error 6"
@needs_parquet
def test_parquet_nested_without_schema_is_error_6(tmp_path):
    arrow = pa.schema([("id", pa.int64()), ("t", pa.list_(pa.int64()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "t": [[1]]}, schema=arrow)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


@needs_parquet
def test_parquet_flat_column_declared_nested_is_a_cast_failure(tmp_path):
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "t": ["x"]})
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "coerce-null", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == [""]


# Phrase: "With --schema, Parquet/JSONL nesting must structurally match and
#          cast recursively"
# Context: Determinism Checklist; a list declared as a struct does not match.
@needs_parquet
def test_parquet_list_declared_as_struct_coerces_to_null(tmp_path):
    arrow = pa.schema([("id", pa.int64()), ("t", pa.list_(pa.int64()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "t": [[1]]}, schema=arrow)
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", struct_t(("a", "int"))))
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == [""]


# --------------------------------------------------------------------------
# Phrase: "Nested schema; key on nested leaf; partition by map value" example
# Context: Examples; JSONL and Parquet merged under one nested schema.
# --------------------------------------------------------------------------
@needs_parquet
def test_jsonl_and_parquet_merge_under_one_nested_schema(tmp_path):
    arrow = pa.schema([("id", pa.int64()),
                       ("u", pa.struct([("n", pa.string())]))])
    pq_src = write_parquet(tmp_path / "b.parquet",
                           {"id": [2], "u": [{"n": "bob"}]}, schema=arrow)
    js_src = write_jsonl(tmp_path / "a.jsonl",
                         [{"id": 1, "u": {"n": "ada"}}])
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("n", "string"))))
    res = run_tool("--output", "-", "--key", "u.n", "--schema", schema,
                   js_src, pq_src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "u") == ['{"n":"ada"}', '{"n":"bob"}']
