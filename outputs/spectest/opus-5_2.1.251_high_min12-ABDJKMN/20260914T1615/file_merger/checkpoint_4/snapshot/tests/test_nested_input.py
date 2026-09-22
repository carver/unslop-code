"""Spec section: Nested Types Support — "Input Handling for Nested"."""

import json

from conftest import (array_t, body, col, header, map_t, pa, run, run_ok,
                      struct_t, write, write_json, write_jsonl,
                      write_nested_schema, write_parquet, write_schema,
                      write_tsv)


# --- Spec: "**JSONL**: Accept nested objects/arrays only when schema declares
#           column as nested or `json`" ---
# Context: Input Handling for Nested; declared nested -> accepted.
def test_jsonl_nested_accepted_when_declared_nested(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"))), ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 5}, "xs": [1, 2]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert body(res.stdout) == ['1,"{""a"":5}","[1,2]"']


# --- Spec: "Accept nested objects/arrays only when schema declares column as
#           nested or `json`" ---
# Context: Input Handling for Nested; `json` accepts the same values.
def test_jsonl_nested_accepted_when_declared_json(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"a": [1]}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ['{"a":[1]}']


# --- Spec: "If schema declares flat type but input has object/array, handle
#           per `--on-type-error`" ---
# Context: Input Handling for Nested; coerce-null is the default.
def test_jsonl_object_into_flat_column_coerce_null(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "coerce-null", "--csv-null-literal", "NA", a)
    assert body(res.stdout) == ["1,NA"]


# --- Spec: "If schema declares flat type but input has object/array, handle
#           per `--on-type-error`" ---
# Context: Input Handling for Nested; keep-string keeps a stringified form.
def test_jsonl_object_into_flat_column_keep_string(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert col(res.stdout, "v") == ['{"a":1}']


# --- Spec: "If schema declares flat type but input has object/array, handle
#           per `--on-type-error`" ---
# Context: Input Handling for Nested; fail exits 4 with the ERR 4 message.
def test_jsonl_object_into_flat_column_fail(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode == 4
    assert "ERR 4" in res.stderr
    assert 'in field "v"' in res.stderr


# --- Spec: "`fail`: emit `ERR 4 cannot cast "<val>" to <type> in field
#           "<path>" (file=... line=...)`" ---
# Context: Casting & Validation; the message carries file and line.
def test_err4_message_carries_file_and_line(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}},
                                     {"id": 2, "u": {"a": "zz"}}])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode == 4
    assert "ERR 4" in res.stderr
    assert 'cannot cast "zz" to int' in res.stderr
    assert 'in field "u.a"' in res.stderr
    assert "file=" in res.stderr and "line=2" in res.stderr


# --- Spec: "**Parquet**: Accept nested structs/lists/maps only when schema
#           declares compatible nested types" ---
# Context: Input Handling for Nested; struct, list and map columns.
def test_parquet_nested_accepted_with_matching_schema(ws):
    pyarrow = pa()
    schema = pyarrow.schema([
        ("id", pyarrow.int64()),
        ("u", pyarrow.struct([("a", pyarrow.int64()),
                              ("b", pyarrow.string())])),
        ("xs", pyarrow.list_(pyarrow.int64())),
        ("m", pyarrow.map_(pyarrow.string(), pyarrow.int64())),
    ])
    p = write_parquet(ws / "p.parquet", {
        "id": [1], "u": [{"a": 7, "b": "z"}], "xs": [[1, 2]],
        "m": [[("b", 2), ("a", 1)]]}, schema=schema)
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"), ("b", "string"))),
        ("xs", array_t("int")), ("m", map_t("int"))])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, p)
    assert col(res.stdout, "u") == ['{"a":7,"b":"z"}']
    assert col(res.stdout, "xs") == ["[1,2]"]
    assert col(res.stdout, "m") == ['{"a":1,"b":2}']


# --- Spec: "With `--schema`, Parquet/JSONL nesting must structurally match
#           and cast recursively" ---
# Context: Determinism Checklist; parquet ints widen to the declared float.
def test_parquet_nested_casts_recursively(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("xs", pyarrow.list_(pyarrow.int64()))])
    p = write_parquet(ws / "p.parquet", {"id": [1], "xs": [[1, 2]]},
                      schema=schema)
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("float"))])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, p)
    assert col(res.stdout, "xs") == ["[1.0,2.0]"]


# --- Spec: "Without schema, nested triggers error 6" ---
# Context: Input Handling for Nested (Parquet).
def test_parquet_nested_without_schema_is_error_6(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("u", pyarrow.struct([("a", pyarrow.int64())]))])
    p = write_parquet(ws / "p.parquet", {"id": [1], "u": [{"a": 1}]},
                      schema=schema)
    res = run("--output", "-", "--key", "id", p)
    assert res.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in res.stderr


# --- Spec: "Error: `ERR 6 nested structure requires provided --schema`
#           (exit 6)" ---
# Context: Schema Inference; the JSONL side of the same rule.
def test_jsonl_nested_without_schema_is_error_6(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in res.stderr


# --- Spec: "Reject inputs containing nested objects/arrays in JSONL/Parquet" ---
# Context: Schema Inference (Unchanged, Flat-Only); arrays count too.
def test_jsonl_array_without_schema_is_error_6(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1, 2]}])
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "**CSV/TSV**: Cell must contain single JSON literal when target
#           type is nested or `json`" ---
# Context: Input Handling for Nested.
def test_csv_cell_holding_a_json_literal(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"), ("b", "string")))])
    x = write(ws / "x.csv", 'id,u\n1,"{""a"": 1, ""b"": ""q""}"\n')
    res = run_ok("--output", "-", "--key", "id", "--schema", s, x)
    assert col(res.stdout, "u") == ['{"a":1,"b":"q"}']


# --- Spec: "CSV/TSV: Cell must contain single JSON literal when target type is
#           nested or `json`" ---
# Context: Input Handling for Nested; the TSV flavour.
def test_tsv_cell_holding_a_json_literal(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    x = write_tsv(ws / "x.tsv", ["id", "xs"], [["1", "[1, 2, 3]"]])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, x)
    assert col(res.stdout, "xs") == ["[1,2,3]"]


# --- Spec: "Empty cell -> null" ---
# Context: Input Handling for Nested (CSV/TSV); the whole cell is null.
def test_csv_empty_cell_for_nested_is_null(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    x = write(ws / "x.csv", "id,xs\n1,\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NULL", x)
    assert body(res.stdout) == ["1,NULL"]


# --- Spec: "Invalid JSON -> handled per `--on-type-error`/error 5" ---
# Context: Input Handling for Nested (CSV/TSV); coerce-null.
def test_csv_invalid_json_coerce_null(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    x = write(ws / "x.csv", "id,xs\n1,{oops\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "coerce-null", "--csv-null-literal", "NA", x)
    assert body(res.stdout) == ["1,NA"]


# --- Spec: "Invalid JSON -> handled per `--on-type-error`/error 5" ---
# Context: Input Handling for Nested (CSV/TSV); keep-string keeps the cell (T82).
def test_csv_invalid_json_keep_string(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    x = write(ws / "x.csv", "id,xs\n1,{oops\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "keep-string", x)
    assert col(res.stdout, "xs") == ["{oops"]


# --- Spec: "Invalid JSON -> handled per `--on-type-error`/error 5" ---
# Context: Input Handling for Nested (CSV/TSV); fail stops the run (T70).
def test_csv_invalid_json_fail_is_nonzero(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    x = write(ws / "x.csv", "id,xs\n1,{oops\n")
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", x)
    assert res.returncode == 4
    assert "ERR 4" in res.stderr


# --- Spec: "CSV/TSV cells containing JSON treated as string" ---
# Context: Schema Inference (Unchanged, Flat-Only); no schema, no nesting.
def test_csv_json_cell_without_schema_is_a_string(ws):
    x = write(ws / "x.csv", 'id,v\n1,"{""a"": 1}"\n')
    res = run_ok("--output", "-", "--key", "id", x)
    assert col(res.stdout, "v") == ['{"a": 1}']


# --- Spec: "Without `--schema`, nested inputs not allowed (error 6)" ---
# Context: Usage Additions; a CSV-only run is never nested, so it still works.
def test_flat_inputs_without_schema_still_work(ws):
    x = write(ws / "x.csv", "id,v\n2,a\n1,b\n")
    res = run_ok("--output", "-", "--key", "id", x)
    assert body(res.stdout) == ["1,b", "2,a"]


# --- Spec: "Accept nested objects/arrays only when schema declares column as
#           nested or `json`" ---
# Context: Input Handling for Nested; an undeclared nested column is ignored (T90).
def test_nested_value_in_an_undeclared_column_is_ignored(ws):
    s = write_schema(ws / "s.json", [("id", "int")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "extra": {"a": 1}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id"]
    assert body(res.stdout) == ["1"]


# --- Spec: "With `--schema`, Parquet/JSONL nesting must structurally match" ---
# Context: Determinism Checklist; a list where a map is declared (T71).
def test_structural_mismatch_follows_on_type_error(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("m", map_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "m": [1, 2]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert body(res.stdout) == ["1,NA"]


# --- Spec: "Nested values cast recursively to declared types" ---
# Context: Casting & Validation; mixing formats in one run.
def test_nested_columns_merge_across_formats(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 2, "u": {"a": 2}}])
    x = write(ws / "x.csv", 'id,u\n1,"{""a"": 1}"\n')
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a, x)
    assert col(res.stdout, "u") == ['{"a":1}', '{"a":2}']
