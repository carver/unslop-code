"""Reading nested values out of each input format, with and without a schema."""
import pyarrow as pa

from conftest import column, table

STRUCT = {"struct": {"fields": [{"name": "name", "type": "string"},
                                {"name": "age", "type": "int"}]}}


def _schema(json_file, **columns):
    return json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                            *({"name": n, "type": t}
                                              for n, t in columns.items())]})


# Phrase: "JSONL: Accept nested objects/arrays only when schema declares column as
#          nested or json"
# Context: with the column declared, the object is read instead of rejected.
def test_jsonl_nested_accepted_when_declared(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": 30}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, user=STRUCT), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"ada","age":30}']


# Phrase: "If schema declares flat type but input has object/array, handle per
#          --on-type-error"
# Context: coerce-null empties the cell rather than failing the run.
def test_jsonl_nested_against_flat_type_follows_on_type_error(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada"}}])
    schema = _schema(json_file, user="string")
    nulled = run("--output", "-", "--key", "id", "--schema", schema,
                 "--on-type-error", "coerce-null", data)
    kept = run("--output", "-", "--key", "id", "--schema", schema,
               "--on-type-error", "keep-string", data)
    failed = run("--output", "-", "--key", "id", "--schema", schema,
                 "--on-type-error", "fail", data)
    assert column(nulled.stdout, "user") == [""]
    assert column(kept.stdout, "user") == ['{"name":"ada"}']
    assert failed.returncode == 4, failed.stderr


# Phrase: "Without --schema, nested inputs not allowed (error 6)"
# Context: JSONL, which is where a nested value can appear without any declaration.
def test_jsonl_nested_without_schema_exits_6(run, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada"}}])
    res = run("--output", "-", "--key", "id", data)
    assert res.returncode == 6, res.stderr
    assert "nested structure requires provided --schema" in res.stderr


# Phrase: "Error: ERR 6 nested structure requires provided --schema (exit 6)"
# Context: a top-level array value is nesting just as an object is.
def test_jsonl_array_value_without_schema_exits_6(run, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "tags": [1, 2]}])
    res = run("--output", "-", "--key", "id", data)
    assert res.returncode == 6, res.stderr


# Phrase: "Parquet: Accept nested structs/lists/maps only when schema declares
#          compatible nested types"
# Context: all three Arrow nested kinds in one file.
def test_parquet_nested_accepted_when_declared(run, parquet_file, json_file):
    columns = {
        "id": ([1], pa.int64()),
        "user": ([{"name": "ada", "age": 30}],
                 pa.struct([("name", pa.string()), ("age", pa.int64())])),
        "tags": ([["b", "a"]], pa.list_(pa.string())),
        "attrs": ([[("z", "1"), ("a", "2")]], pa.map_(pa.string(), pa.string())),
    }
    data = parquet_file("a.parquet", columns)
    schema = json_file("s.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "user", "type": STRUCT},
        {"name": "tags", "type": {"array": {"element": "string"}}},
        {"name": "attrs", "type": {"map": {"key": "string", "value": "int"}}}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", '{"name":"ada","age":30}', '["b","a"]',
                                    '{"a":2,"z":1}']


# Phrase: "Parquet ... Without schema, nested triggers error 6"
# Context: the footer alone is enough to reject the file.
def test_parquet_nested_without_schema_exits_6(run, parquet_file):
    data = parquet_file("a.parquet", {"id": ([1], pa.int64()),
                                      "tags": ([["x"]], pa.list_(pa.string()))})
    res = run("--output", "-", "--key", "id", data)
    assert res.returncode == 6, res.stderr
    assert "nested structure requires provided --schema" in res.stderr


# Phrase: "CSV/TSV: Cell must contain single JSON literal when target type is nested
#          or json"
# Context: the JSON travels as one quoted CSV field.
def test_csv_cell_holding_json_is_parsed_for_a_nested_column(run, csv_file, json_file):
    data = csv_file("a.csv", 'id,user\n1,"{""name"": ""ada"", ""age"": ""30""}"\n')
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, user=STRUCT), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"ada","age":30}']


# Phrase: "CSV/TSV: Cell must contain single JSON literal ... Empty cell -> null"
# Context: the empty cell is the whole column value, so it is the CSV null literal.
def test_empty_csv_cell_for_a_nested_column_is_null(run, csv_file, json_file):
    data = csv_file("a.csv", "id,user\n1,\n")
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, user=STRUCT),
              "--csv-null-literal", "NULL", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ["NULL"]


# Phrase: "Invalid JSON -> handled per --on-type-error/error 5"
# Context: T53 - a cell that is not JSON at all, under each mode.
def test_invalid_json_in_a_nested_cell_follows_on_type_error(run, csv_file, json_file):
    data = csv_file("a.csv", "id,user\n1,not-json\n")
    schema = _schema(json_file, user=STRUCT)
    nulled = run("--output", "-", "--key", "id", "--schema", schema, data)
    kept = run("--output", "-", "--key", "id", "--schema", schema,
               "--on-type-error", "keep-string", data)
    failed = run("--output", "-", "--key", "id", "--schema", schema,
                 "--on-type-error", "fail", data)
    assert column(nulled.stdout, "user") == [""]
    assert column(kept.stdout, "user") == ["not-json"]
    assert failed.returncode == 4, failed.stderr


# Phrase: "CSV/TSV: Cell must contain single JSON literal"
# Context: trailing text after the literal leaves the cell unparseable.
def test_csv_cell_with_trailing_text_after_json_is_invalid(run, csv_file, json_file):
    data = csv_file("a.csv", 'id,user\n1,"{""name"":""a"",""age"":1} tail"\n')
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, user=STRUCT), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == [""]


# Phrase: "CSV/TSV: Cell must contain single JSON literal when target type is nested
#          or json"
# Context: TSV carries the same JSON without any quoting of its own.
def test_tsv_cell_holding_json_for_a_json_column(run, text_file, json_file):
    data = text_file("a.tsv", 'id\tv\n1\t{"b":1,"a":2}\n')
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, v="json"), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == ['{"a":2,"b":1}']


# Phrase: "Inferred columns remain flat ... CSV/TSV cells containing JSON treated as
#          string"
# Context: without a schema the same cell is text, and the run still succeeds.
def test_csv_json_cell_without_schema_stays_a_string(run, csv_file):
    data = csv_file("a.csv", 'id,v\n1,"{""a"": 1}"\n')
    res = run("--output", "-", "--key", "id", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == ['{"a": 1}']


# Phrase: "With --schema, Parquet/JSONL nesting must structurally match and cast
#          recursively"
# Context: a list where the schema declares a struct is a cast failure, not a crash.
def test_structural_mismatch_is_a_cast_failure(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": [1, 2]}])
    schema = _schema(json_file, user=STRUCT)
    assert column(run("--output", "-", "--key", "id", "--schema", schema, data).stdout,
                  "user") == [""]
    failed = run("--output", "-", "--key", "id", "--schema", schema,
                 "--on-type-error", "fail", data)
    assert failed.returncode == 4, failed.stderr
