"""Checkpoint 5: the spec's worked examples and determinism checklist."""
import json

from conftest import (array_of, cell, cells, dirs, map_of, merge_paths,
                      nested_schema, pa_modules, run, struct_of, tree, write,
                      write_jsonl, write_parquet, write_tsv)


# --- Spec example 1: "Nested schema; key on nested leaf; partition by map
#     value" ---------------------------------------------------------------
#   python merge_files.py --output out/ --key user.id,event_time \
#            --partition-by attrs["country"] --schema schema_nested.json \
#            --on-type-error coerce-null inputs/events.jsonl inputs/users.parquet
def test_spec_example_one(tmp_path):
    pa, _pq = pa_modules()
    schema = nested_schema(tmp_path, "schema_nested.json", [
        ("event_time", "timestamp"),
        ("user", struct_of(("id", "int"), ("name", "string"))),
        ("attrs", map_of("string")),
    ])
    events = write_jsonl(tmp_path, "inputs/events.jsonl", [
        {"event_time": "2024-01-02T10:00:00Z",
         "user": {"id": 2, "name": "b"}, "attrs": {"country": "NL"}},
        {"event_time": "2024-01-01T10:00:00+01:00",
         "user": {"id": 1, "name": "a"}, "attrs": {"country": "DE"}},
    ])
    pa_schema = pa.schema([
        pa.field("event_time", pa.string()),
        pa.field("user", pa.struct([pa.field("id", pa.int64()),
                                    pa.field("name", pa.string())])),
        pa.field("attrs", pa.map_(pa.string(), pa.string())),
    ])
    users = write_parquet(tmp_path, "inputs/users.parquet", [
        {"event_time": "2024-01-03T00:00:00Z", "user": {"id": 1, "name": "a"},
         "attrs": [("country", "DE")]},
    ], schema=pa_schema)
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "user.id,event_time",
            "--partition-by", 'attrs["country"]', "--schema", str(schema),
            "--on-type-error", "coerce-null", str(events), str(users))
    assert r.ok, r
    assert dirs(out) == ['attrs%5B%22country%22%5D=DE',
                         'attrs%5B%22country%22%5D=NL']
    de = (out / 'attrs%5B%22country%22%5D=DE' / "part-00000.csv")
    from conftest import read_rows
    rows = read_rows(de)
    assert rows[0] == ["event_time", "user", "attrs"]
    assert len(rows) == 3                 # header + both DE rows
    assert [row[1] for row in rows[1:]] == ['{"id":1,"name":"a"}'] * 2
    assert [row[0] for row in rows[1:]] == ["2024-01-01T09:00:00Z",
                                            "2024-01-03T00:00:00Z"]


# --- Spec example 2: "Accept arbitrary JSON in column while sorting by
#     primitive field" ------------------------------------------------------
#   python merge_files.py --output merged.csv --key id \
#            --schema schema_with_json.json data/*.tsv
def test_spec_example_two(tmp_path):
    schema = nested_schema(tmp_path, "schema_with_json.json",
                           [("id", "int"), ("payload", "json")])
    a = write_tsv(tmp_path, "data/a.tsv",
                  [["id", "payload"], ["2", '{"b": 1, "a": [1, 2]}']])
    b = write_tsv(tmp_path, "data/b.tsv",
                  [["id", "payload"], ["1", '"just a string"']])
    merged = tmp_path / "merged.csv"
    r = run("--output", str(merged), "--key", "id", "--schema", str(schema),
            str(a), str(b))
    assert r.ok, r
    text = merged.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines()]
    assert rows[0] == "id,payload"
    assert rows[1].startswith("1,")
    assert '"just a string"' in rows[1]
    assert rows[2].startswith("2,")


# --- Determinism checklist: "Alias resolution is case-insensitive,
#     transitive, cycle-checked; unknown types error deterministically" -----
def test_checklist_alias_resolution(tmp_path):
    from conftest import alias_file
    aliases = alias_file(tmp_path, "al.json", {"a": "b", "b": "Integer"})
    schema = nested_schema(tmp_path, "s.json", [("id", "A")])
    src = write(tmp_path, "a.csv", "id\n5\n")
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--type-alias-file", str(aliases))
    assert r.ok, r
    assert cell(r, 0, "id") == "5"


# --- Determinism checklist: "CSV null literal applies only when entire cell
#     is null" -------------------------------------------------------------
def test_checklist_null_literal_only_for_whole_cell(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "u": None}, {"id": 2, "u": {"a": None}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--csv-null-literal", "NULL")
    assert r.ok, r
    assert cells(r, "u") == ["NULL", '{"a":null}']


# --- Determinism checklist: "External sort/merge ... continue from prior
#     checkpoints" (nested rows survive spilling to disk) ------------------
def test_checklist_nested_rows_survive_external_sort(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("a", "int"), ("s", "string"))),
    ])
    n = 2000
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": (i * 7919) % n, "u": {"a": i, "s": "x" * 40}} for i in range(n)
    ])
    r = merge_paths([src], "--key", "u.a", "--schema", str(schema),
                    "--memory-limit-mb", "1")
    assert r.ok, r
    values = [json.loads(v)["a"] for v in cells(r, "u")]
    assert values == list(range(n))


# --- Determinism checklist: "identical inputs produce byte-identical
#     output" for nested columns ------------------------------------------
def test_checklist_repeated_runs_are_byte_identical(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("m", map_of("string")), ("xs", array_of("int")),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 2, "m": {"b": "2", "a": "1"}, "xs": [3, 2, 1]},
        {"id": 1, "m": {"z": "9"}, "xs": []},
    ])
    first = merge_paths([src], "--key", "id", "--schema", str(schema))
    second = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert first.ok and second.ok
    assert first.stdout == second.stdout


# --- Determinism checklist: "Dotted/bracketed field paths resolve to
#     primitives or error 3" ----------------------------------------------
def test_checklist_path_must_be_primitive(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of(array_of("int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"k": [1]}}])
    ok = merge_paths([src], "--key", 'm["k"].0', "--schema", str(schema))
    assert ok.ok, ok
    bad = merge_paths([src], "--key", 'm["k"]', "--schema", str(schema))
    assert bad.returncode == 3, bad


# --- Determinism checklist: "exit codes and messages continue from prior
#     checkpoints" ---------------------------------------------------------
def test_checklist_success_is_still_quiet(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.returncode == 0 and r.stderr == ""


# --- Usage: "--output <PATH|-> ... --schema ... --type-alias-file ..." ----
def test_usage_flags_are_accepted_together(tmp_path):
    from conftest import alias_file
    aliases = alias_file(tmp_path, "al.json", {"smallint": "int"})
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "smallint"), ("u", struct_of(("a", "int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "u": {"a": 1}}, {"id": 2, "u": {"a": 2}}])
    out = tmp_path / "o"
    r = run("--output", str(out), "--key", "u.a", "--partition-by", "id",
            "--schema", str(schema), "--type-alias-file", str(aliases),
            "--desc", "--on-type-error", "coerce-null", str(src))
    assert r.ok, r
    assert tree(out) == ["id=1/part-00000.csv", "id=2/part-00000.csv"]
