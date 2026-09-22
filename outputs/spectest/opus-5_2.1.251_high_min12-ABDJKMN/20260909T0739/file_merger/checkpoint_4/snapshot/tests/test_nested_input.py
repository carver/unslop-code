"""Checkpoint 5: reading nested values out of JSONL, Parquet and CSV/TSV."""
from conftest import (array_of, cell, cells, map_of, merge, merge_paths,
                      nested_schema, pa_modules, struct_of, write, write_jsonl,
                      write_parquet, write_tsv)


# --- Spec: "JSONL: Accept nested objects/arrays only when schema declares
#            column as nested or json" -------------------------------------
def test_jsonl_object_accepted_for_struct_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "string")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"n": "ann"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"n":"ann"}'


def test_jsonl_array_accepted_for_array_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, 2, 3]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[1,2,3]"


def test_jsonl_object_accepted_for_json_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": [{"a": 1}, 2, "x"]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == '[{"a":1},2,"x"]'


# --- Spec: "If schema declares flat type but input has object/array, handle
#            per --on-type-error" ------------------------------------------
def test_jsonl_nested_in_flat_column_coerces_to_null(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "v") == ""


def test_jsonl_nested_in_flat_column_keep_string(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": {"b": 1, "a": 2}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "keep-string")
    assert r.ok, r
    assert cell(r, 0, "v").startswith("{") and '"a"' in cell(r, 0, "v")


def test_jsonl_nested_in_flat_column_fail_is_exit_4(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": [1]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r


# --- Spec: "JSONL: Accept nested ... only when schema declares column as
#            nested" - a plain string is not structure (AMBIGUITIES T65) ----
def test_jsonl_json_text_string_is_not_parsed_for_struct_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "string")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": "{\"n\": \"ann\"}"}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r


# --- Spec: "CSV/TSV: Cell must contain single JSON literal when target type
#            is nested or json" --------------------------------------------
def test_csv_cell_holds_a_json_literal(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "string"),
                                                           ("a", "int")))])
    files = {"a.csv": 'id,u\n1,"{""n"":""ann"",""a"":3}"\n'}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"n":"ann","a":3}'


def test_tsv_cell_holds_a_json_literal(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_tsv(tmp_path, "a.tsv", [["id", "xs"], ["1", "[1, 2]"]])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[1,2]"


# --- Spec: "CSV/TSV ... Empty cell -> null" -------------------------------
def test_csv_empty_cell_for_nested_column_is_null(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "string")))])
    files = {"a.csv": "id,u\n1,\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == ""


def test_csv_empty_cell_honours_the_null_literal(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    files = {"a.csv": "id,v\n1,NULL\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--csv-null-literal", "NULL")
    assert r.ok, r
    assert cell(r, 0, "v") == "NULL"


# --- Spec: "CSV/TSV ... Invalid JSON -> handled per --on-type-error" -------
def test_csv_invalid_json_coerces_to_null(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    files = {"a.csv": "id,v\n1,{oops\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "v") == ""


def test_csv_invalid_json_keep_string_keeps_the_raw_cell(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    files = {"a.csv": "id,v\n1,{oops\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--on-type-error", "keep-string")
    assert r.ok, r
    assert cell(r, 0, "v") == "{oops"


def test_csv_invalid_json_fail_is_an_error(tmp_path):
    # AMBIGUITIES T61: read as an ordinary cast failure, so exit 4.
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    files = {"a.csv": "id,v\n1,{oops\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert r.stderr.strip()


# --- Spec: "Cell must contain a *single* JSON literal" --------------------
def test_csv_trailing_garbage_after_json_is_invalid(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    files = {"a.csv": 'id,xs\n1,"[1] [2]"\n'}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--on-type-error", "fail")
    assert r.returncode == 4, r


def test_csv_bare_scalar_is_a_json_literal_for_json_columns(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    files = {"a.csv": "id,v\n1,42\n2,true\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "v") == ["42", "true"]


# --- Spec: "Parquet: Accept nested structs/lists/maps only when schema
#            declares compatible nested types" -----------------------------
def test_parquet_struct_column(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([
        pa.field("id", pa.int64()),
        pa.field("u", pa.struct([pa.field("n", pa.string()),
                                 pa.field("a", pa.int32())])),
    ])
    src = write_parquet(tmp_path, "a.parquet",
                        [{"id": 1, "u": {"n": "ann", "a": 30}}], schema=schema_pa)
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("n", "string"), ("a", "int"))),
    ])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"n":"ann","a":30}'


def test_parquet_list_column(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([pa.field("id", pa.int64()),
                           pa.field("xs", pa.list_(pa.int64()))])
    src = write_parquet(tmp_path, "a.parquet", [{"id": 1, "xs": [3, 1]}],
                        schema=schema_pa)
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[3,1]"


def test_parquet_map_column(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([
        pa.field("id", pa.int64()),
        pa.field("m", pa.map_(pa.string(), pa.string())),
    ])
    src = write_parquet(tmp_path, "a.parquet",
                        [{"id": 1, "m": [("b", "2"), ("a", "1")]}],
                        schema=schema_pa)
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of("string"))])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"a":"1","b":"2"}'


def test_parquet_nested_struct_in_list(tmp_path):
    pa, _pq = pa_modules()
    element = pa.struct([pa.field("sku", pa.string()), pa.field("qty", pa.int64())])
    schema_pa = pa.schema([pa.field("id", pa.int64()),
                           pa.field("items", pa.list_(element))])
    src = write_parquet(tmp_path, "a.parquet",
                        [{"id": 1, "items": [{"sku": "x", "qty": 2}]}],
                        schema=schema_pa)
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("items", array_of(struct_of(("sku", "string"), ("qty", "int")))),
    ])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "items") == '[{"sku":"x","qty":2}]'


# --- Spec: "Parquet ... Without schema, nested triggers error 6" ----------
def test_parquet_nested_without_schema_is_error_6(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([pa.field("id", pa.int64()),
                           pa.field("xs", pa.list_(pa.int64()))])
    src = write_parquet(tmp_path, "a.parquet", [{"id": 1, "xs": [1]}],
                        schema=schema_pa)
    r = merge_paths([src], "--key", "id")
    assert r.returncode == 6, r


# --- Spec: "With --schema, Parquet/JSONL nesting must structurally match" --
def test_parquet_structure_mismatch_is_handled_as_a_cast_failure(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([pa.field("id", pa.int64()),
                           pa.field("xs", pa.list_(pa.int64()))])
    src = write_parquet(tmp_path, "a.parquet", [{"id": 1, "xs": [1]}],
                        schema=schema_pa)
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", struct_of(("a", "int")))])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r


def test_parquet_flat_column_declared_nested_fails(tmp_path):
    src = write_parquet(tmp_path, "a.parquet", [{"id": 1, "v": "x"}])
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("v", array_of("int"))])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "v") == ""


# --- Spec: nested inputs from several formats merge into one output -------
def test_jsonl_and_parquet_nesting_merge(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([
        pa.field("id", pa.int64()),
        pa.field("u", pa.struct([pa.field("n", pa.string())])),
    ])
    p = write_parquet(tmp_path, "b.parquet", [{"id": 2, "u": {"n": "bob"}}],
                      schema=schema_pa)
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"n": "ann"}}])
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "string")))])
    r = merge_paths([j, p], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "u") == ['{"n":"ann"}', '{"n":"bob"}']


# --- Spec: an undeclared nested field is ignored (AMBIGUITIES T60) --------
def test_undeclared_nested_field_is_ignored_when_schema_given(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "extra": {"a": [1]}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [["id"], ["1"]]
