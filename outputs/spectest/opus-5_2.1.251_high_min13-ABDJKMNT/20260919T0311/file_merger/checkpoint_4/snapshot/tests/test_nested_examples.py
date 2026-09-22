"""The spec's worked examples, and the nested determinism checklist."""
import pyarrow as pa

from conftest import column, data_rows, parts, table, tree

SCHEMA_NESTED = {"columns": [
    {"name": "user", "type": {"struct": {"fields": [
        {"name": "id", "type": "int"},
        {"name": "name", "type": "string"},
        {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}}]}}},
    {"name": "event_time", "type": "timestamp"},
    {"name": "attrs", "type": {"map": {"key": "string", "value": "string"}}},
]}


# Phrase: "python merge_files.py --output out/ --key user.id,event_time
#          --partition-by attrs["country"] --schema schema_nested.json
#          --on-type-error coerce-null inputs/events.jsonl inputs/users.parquet"
# Context: the spec's first nested example, run end to end over both formats.
def test_nested_example_over_jsonl_and_parquet(run, tmp_path, jsonl_file, parquet_file,
                                               json_file):
    events = jsonl_file("inputs/events.jsonl", [
        {"user": {"id": 2, "name": "b", "prefs": {"tz": "UTC"}},
         "event_time": "2024-01-02T00:00:00Z", "attrs": {"country": "US"}},
        {"user": {"id": 1, "name": "a", "prefs": {}},
         "event_time": "2024-01-03T00:00:00Z", "attrs": {"country": "DE"}}])
    users = parquet_file("inputs/users.parquet", {
        "user": ([{"id": 1, "name": "c", "prefs": [("lang", "en")]}],
                 pa.struct([("id", pa.int64()), ("name", pa.string()),
                            ("prefs", pa.map_(pa.string(), pa.string()))])),
        "event_time": ([None], pa.string()),
        "attrs": ([[("country", "US")]], pa.map_(pa.string(), pa.string()))})
    schema = json_file("schema_nested.json", SCHEMA_NESTED)
    res = run("--output", "out", "--key", "user.id,event_time",
              "--partition-by", 'attrs["country"]', "--schema", schema,
              "--on-type-error", "coerce-null", events, users)
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["attrs%5B%22country%22%5D=DE/part-00000.csv",
                                      "attrs%5B%22country%22%5D=US/part-00000.csv"]
    us = data_rows(parts(tmp_path / "out" / "attrs%5B%22country%22%5D=US")[0])
    assert [row[0] for row in us] == ['{"id":1,"name":"c","prefs":{"lang":"en"}}',
                                      '{"id":2,"name":"b","prefs":{"tz":"UTC"}}']


# Phrase: "python merge_files.py --output merged.csv --key id
#          --schema schema_with_json.json data/*.tsv
#          where schema_with_json.json contains "type":"json" for flexible column"
# Context: the spec's second example: arbitrary JSON alongside a primitive key.
def test_json_column_example_over_tsv(run, tmp_path, text_file, json_file):
    text_file("data/a.tsv", 'id\tpayload\n2\t{"b":[1,2],"a":null}\n')
    text_file("data/b.tsv", 'id\tpayload\n1\t"plain"\n')
    schema = json_file("schema_with_json.json", {"columns": [
        {"name": "id", "type": "int"}, {"name": "payload", "type": "json"}]})
    res = run("--output", "merged.csv", "--key", "id", "--schema", schema,
              "data/a.tsv", "data/b.tsv")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "merged.csv").read_text(encoding="utf-8") == (
        'id,payload\n1,"""plain"""\n2,"{""a"":null,""b"":[1,2]}"\n')


# Phrase: "Alias resolution is case-insensitive, transitive, cycle-checked;
#          unknown types error deterministically"
# Context: the same unknown type fails the same way on repeated runs.
def test_unknown_type_is_deterministic(run, csv_file, json_file):
    data = csv_file("a.csv", "id\n1\n")
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int32"}]})
    first, second = (run("--output", "-", "--key", "id", "--schema", schema, data)
                     for _ in range(2))
    assert first.returncode == 3
    assert (first.returncode, first.stderr) == (second.returncode, second.stderr)


# Phrase: "External sort/merge, partitioning, stability, and exit codes/messages
#          continue from prior checkpoints"
# Context: rows with equal nested keys keep their input order across a spill.
def test_nested_keys_are_stable_under_spilling(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"row": index, "user": {"id": 1}}
                                  for index in range(300)])
    schema = json_file("s.json", {"columns": [
        {"name": "row", "type": "int"},
        {"name": "user", "type": {"struct": {"fields": [{"name": "id", "type": "int"}]}}}]})
    res = run("--output", "-", "--key", "user.id", "--memory-limit-mb", "1",
              "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == [str(index) for index in range(300)]


# Phrase: "Nested casting/normalization yields canonical JSON per ordering rules"
# Context: the same row through JSONL and through CSV lands on the same cell.
def test_same_value_from_two_formats_encodes_identically(run, jsonl_file, csv_file,
                                                         json_file):
    type_ = {"map": {"key": "string", "value": "int"}}
    from_jsonl = jsonl_file("a.jsonl", [{"id": 1, "v": {"b": 2, "a": 1}}])
    from_csv = csv_file("b.csv", 'id,v\n1,"{""b"": 2, ""a"": 1}"\n')
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "v", "type": type_}]})
    first = run("--output", "-", "--key", "id", "--schema", schema, from_jsonl)
    second = run("--output", "-", "--key", "id", "--schema", schema, from_csv)
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout == 'id,v\n1,"{""a"":1,""b"":2}"\n'


# Phrase: "Without --schema, nested inputs rejected (error 6)"
# Context: the whole run fails, leaving no output file behind.
def test_error_6_writes_no_output(run, tmp_path, jsonl_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run("--output", "out.csv", "--key", "id", data)
    assert res.returncode == 6
    assert tree(tmp_path) == ["a.jsonl"]


# Phrase: "Output remains CSV with nested columns as canonical JSON"
# Context: the header still names the nested column once, flat columns unchanged.
def test_header_is_unchanged_by_nesting(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    schema = json_file("s.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "v", "type": {"struct": {"fields": [{"name": "a", "type": "int"}]}}}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert table(res.stdout)[0] == ["id", "v"]
