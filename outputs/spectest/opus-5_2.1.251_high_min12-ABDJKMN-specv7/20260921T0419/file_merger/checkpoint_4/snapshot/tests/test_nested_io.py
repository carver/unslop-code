"""Spec sections: Input Handling for Nested / Casting & Validation /
Schema Inference (Unchanged, Flat-Only)."""
import json

import pytest

from conftest import body, header


def schema_file(work, name, columns):
    return work.write(
        name, json.dumps({"columns": [{"name": n, "type": t} for n, t in columns]})
    )


USER = {
    "struct": {
        "fields": [
            {"name": "name", "type": "string"},
            {"name": "age", "type": "int"},
        ]
    }
}


# --------------------------------------------------------------------------
# JSONL
# --------------------------------------------------------------------------

# Phrase: "JSONL: Accept nested objects/arrays only when schema declares column
#          as nested or json"
# Context: Input Handling for Nested.
def test_jsonl_nested_accepted_when_declared(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a", "age": 2}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"a","age":2}']]


def test_jsonl_nested_accepted_for_json_column(run, work):
    schema_file(work, "s.json", [("id", "int"), ("v", "json")])
    work.jsonl("a.jsonl", [{"id": 1, "v": [1, {"k": "v"}]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '[1,{"k":"v"}]']]


# Phrase: "If schema declares flat type but input has object/array, handle per
#          --on-type-error"
# Context: Input Handling for Nested.
def test_jsonl_object_in_flat_column_coerce_null(run, work):
    schema_file(work, "s.json", [("id", "int"), ("n", "int")])
    work.jsonl("a.jsonl", [{"id": 1, "n": {"a": 1}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "coerce-null", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


def test_jsonl_object_in_flat_column_keep_string(run, work):
    schema_file(work, "s.json", [("id", "int"), ("n", "int")])
    work.jsonl("a.jsonl", [{"id": 1, "n": {"b": 2, "a": 1}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "keep-string", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"a":1,"b":2}']]


def test_jsonl_object_in_flat_column_fail(run, work):
    schema_file(work, "s.json", [("id", "int"), ("n", "int")])
    work.jsonl("a.jsonl", [{"id": 1, "n": {"a": 1}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.returncode == 4
    assert "ERR 4" in r.stderr
    assert r.stdout == ""


# Phrase: "Parquet: ... Without schema, nested triggers error 6"
# Phrase: "ERR 6 nested structure requires provided --schema"
# Context: Input Handling for Nested / Schema Inference.
def test_jsonl_nested_without_schema_exits_6(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a"}}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in r.stderr


def test_jsonl_array_without_schema_exits_6(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "xs": [1, 2]}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6


# --------------------------------------------------------------------------
# CSV / TSV
# --------------------------------------------------------------------------

# Phrase: "CSV/TSV: Cell must contain single JSON literal when target type is
#          nested or json"
# Context: Input Handling for Nested.
def test_csv_cell_holds_a_json_literal(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.write("a.csv", 'id,user\n1,"{""name"":""a"",""age"":""2""}"\n')
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"a","age":2}']]


def test_tsv_cell_holds_a_json_literal(run, work):
    schema_file(work, "s.json", [("id", "int"), ("xs", {"array": {"element": "int"}})])
    work.write("a.tsv", "id\txs\n1\t[3,1]\n")
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.tsv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "[3,1]"]]


# Phrase: "Empty cell → null"
# Context: Input Handling for Nested (CSV/TSV).
def test_csv_empty_cell_for_nested_is_null(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.write("a.csv", "id,user\n1,\n")
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


# Phrase: "Invalid JSON → handled per --on-type-error/error 5"
# Context: Input Handling for Nested (AMBIGUITIES T45).
def test_csv_invalid_json_coerce_null(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.write("a.csv", "id,user\n1,notjson\n")
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "coerce-null", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


def test_csv_invalid_json_keep_string(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.write("a.csv", "id,user\n1,notjson\n")
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "keep-string", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "notjson"]]


def test_csv_invalid_json_fail_is_nonzero(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.write("a.csv", "id,user\n1,notjson\n")
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.csv"),
    )
    assert r.returncode in (4, 5)
    assert r.stdout == ""


# Phrase: "CSV/TSV cells containing JSON treated as string"
# Context: Schema Inference (Unchanged, Flat-Only); no --schema here.
def test_csv_json_cell_without_schema_is_a_string(run, work):
    work.write("a.csv", 'id,payload\n7,"{""a"": 1}"\n')
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["7", '{"a": 1}']]


# --------------------------------------------------------------------------
# Parquet
# --------------------------------------------------------------------------

# Phrase: "Parquet: Accept nested structs/lists/maps only when schema declares
#          compatible nested types"
# Context: Input Handling for Nested.
def test_parquet_struct_column(run, work):
    pa = pytest.importorskip("pyarrow")
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("user", pa.struct([("name", pa.string()), ("age", pa.int64())])),
        ]
    )
    work.parquet(
        "a.parquet", [{"id": 1, "user": {"name": "a", "age": 2}}], schema=schema
    )
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"a","age":2}']]


def test_parquet_list_column(run, work):
    pa = pytest.importorskip("pyarrow")
    schema = pa.schema([("id", pa.int64()), ("xs", pa.list_(pa.int64()))])
    work.parquet("a.parquet", [{"id": 1, "xs": [3, 1]}], schema=schema)
    schema_file(work, "s.json", [("id", "int"), ("xs", "array<int>")])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "[3,1]"]]


def test_parquet_map_column(run, work):
    pa = pytest.importorskip("pyarrow")
    schema = pa.schema(
        [("id", pa.int64()), ("m", pa.map_(pa.string(), pa.int64()))]
    )
    work.parquet("a.parquet", [{"id": 1, "m": {"b": 2, "a": 1}}], schema=schema)
    schema_file(work, "s.json", [("id", "int"), ("m", "map<string,int>")])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"a":1,"b":2}']]


# Phrase: "Timestamps inside nested values normalized to UTC Z"
# Context: Parquet carries real timestamps inside a struct.
def test_parquet_nested_timestamp_normalized(run, work):
    pa = pytest.importorskip("pyarrow")
    import datetime

    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("w", pa.struct([("ts", pa.timestamp("s", tz="+02:00"))])),
        ]
    )
    moment = datetime.datetime(2024, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    work.parquet("a.parquet", [{"id": 1, "w": {"ts": moment}}], schema=schema)
    struct = {"struct": {"fields": [{"name": "ts", "type": "timestamp"}]}}
    schema_file(work, "s.json", [("id", "int"), ("w", struct)])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"ts":"2024-01-02T03:04:05Z"}']]


# Phrase: "Without schema, nested triggers error 6"
# Context: Input Handling for Nested (Parquet).
def test_parquet_nested_without_schema_exits_6(run, work):
    pa = pytest.importorskip("pyarrow")
    schema = pa.schema(
        [("id", pa.int64()), ("user", pa.struct([("name", pa.string())]))]
    )
    work.parquet("a.parquet", [{"id": 1, "user": {"name": "a"}}], schema=schema)
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in r.stderr


# Phrase: "With --schema, Parquet/JSONL nesting must structurally match and cast
#          recursively"
# Context: Determinism Checklist; a list where a struct is declared cannot match.
def test_parquet_structure_mismatch_follows_on_type_error(run, work):
    pa = pytest.importorskip("pyarrow")
    schema = pa.schema([("id", pa.int64()), ("user", pa.list_(pa.int64()))])
    work.parquet("a.parquet", [{"id": 1, "user": [1, 2]}], schema=schema)
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "coerce-null", work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


# --------------------------------------------------------------------------
# Cast failures inside nested values
# --------------------------------------------------------------------------

# Phrase: "coerce-null: set field/element to JSON null"
# Context: Casting & Validation.
def test_nested_cast_failure_coerce_null(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a", "age": "abc"}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "coerce-null", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"a","age":null}']]


# Phrase: "keep-string: set to original unparsed JSON string or stringified form"
# Context: Casting & Validation.
def test_nested_cast_failure_keep_string(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a", "age": "abc"}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "keep-string", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"a","age":"abc"}']]


# Phrase: 'fail: emit ERR 4 cannot cast "<val>" to <type> in field "<path>"
#          (file=... line=...)'
# Context: Casting & Validation.
def test_nested_cast_failure_fail_message(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a", "age": "abc"}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.returncode == 4
    assert 'ERR 4 cannot cast "abc" to int in field "user.age"' in r.stderr
    assert "file=" in r.stderr and "line=" in r.stderr
    assert r.stdout == ""


# Phrase: "On cast failure within nested structures ... element"
# Context: Casting & Validation; the path names the array index.
def test_array_element_cast_failure_path(run, work):
    schema_file(work, "s.json", [("id", "int"), ("xs", "array<int>")])
    work.jsonl("a.jsonl", [{"id": 1, "xs": [1, "nope"]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.returncode == 4
    assert 'in field "xs.1"' in r.stderr


def test_array_element_cast_failure_coerce_null(run, work):
    schema_file(work, "s.json", [("id", "int"), ("xs", "array<int>")])
    work.jsonl("a.jsonl", [{"id": 1, "xs": [1, "nope"]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "[1,null]"]]


# Phrase: "Nested values cast recursively to declared types"
# Context: Casting & Validation; a scalar where a struct is declared fails.
def test_scalar_where_struct_declared_is_a_cast_failure(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": 5}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""]]


def test_map_value_cast_failure_path(run, work):
    schema_file(work, "s.json", [("id", "int"), ("m", "map<string,int>")])
    work.jsonl("a.jsonl", [{"id": 1, "m": {"k": "bad"}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.returncode == 4
    assert "ERR 4" in r.stderr


# --------------------------------------------------------------------------
# Mixed inputs (the spec's first example)
# --------------------------------------------------------------------------

# Phrase: "python merge_files.py --output out/ --key user.id,event_time
#          --partition-by attrs["country"] --schema schema_nested.json
#          --on-type-error coerce-null inputs/events.jsonl inputs/users.parquet"
# Context: Examples.
def test_example_mixed_jsonl_and_parquet(run, work, tmp_path):
    pa = pytest.importorskip("pyarrow")
    columns = [
        ("user", {"struct": {"fields": [{"name": "id", "type": "int"}]}}),
        ("event_time", "timestamp"),
        ("attrs", {"map": {"key": "string", "value": "string"}}),
    ]
    schema_file(work, "s.json", columns)
    work.jsonl(
        "events.jsonl",
        [
            {
                "user": {"id": 2},
                "event_time": "2024-01-01T00:00:00Z",
                "attrs": {"country": "US"},
            }
        ],
    )
    arrow = pa.schema(
        [
            ("user", pa.struct([("id", pa.int64())])),
            ("event_time", pa.string()),
            ("attrs", pa.map_(pa.string(), pa.string())),
        ]
    )
    work.parquet(
        "users.parquet",
        [
            {
                "user": {"id": 1},
                "event_time": "2024-01-02T00:00:00Z",
                "attrs": {"country": "CA"},
            }
        ],
        schema=arrow,
    )
    out = tmp_path / "out"
    r = run(
        "--output", out, "--key", "user.id,event_time",
        "--partition-by", 'attrs["country"]',
        "--schema", work.path("s.json"), "--on-type-error", "coerce-null",
        work.path("events.jsonl"), work.path("users.parquet"),
    )
    assert r.ok, r.stderr
    from conftest import dirs

    assert dirs(out) == ['attrs["country"]=CA', 'attrs["country"]=US']
