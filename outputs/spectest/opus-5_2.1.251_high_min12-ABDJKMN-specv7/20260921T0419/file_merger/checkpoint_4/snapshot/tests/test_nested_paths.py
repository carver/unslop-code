"""Spec section: Keys & Partitioning with Nested."""
import json

from conftest import body, dirs, read_csv_file, tree


def schema_file(work, name, columns):
    return work.write(
        name, json.dumps({"columns": [{"name": n, "type": t} for n, t in columns]})
    )


USER = {
    "struct": {
        "fields": [
            {"name": "id", "type": "int"},
            {"name": "name", "type": "string"},
        ]
    }
}
ITEMS = {
    "array": {
        "element": {
            "struct": {
                "fields": [
                    {"name": "sku", "type": "string"},
                    {"name": "qty", "type": "int"},
                ]
            }
        }
    }
}
ATTRS = {"map": {"key": "string", "value": "string"}}


# Phrase: "--key and --partition-by now accept field paths using dot notation
#          (e.g., user.id)"
# Context: Usage Additions.
def test_key_on_struct_leaf_sorts_rows(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "c", "user": {"id": 3, "name": "c"}},
            {"tag": "a", "user": {"id": 1, "name": "a"}},
            {"tag": "b", "user": {"id": 2, "name": "b"}},
        ],
    )
    r = run(
        "--output", "-", "--key", "user.id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["a", "b", "c"]


# Phrase: "use numeric indices into arrays" / "items.0.sku"
# Context: Keys & Partitioning with Nested.
def test_key_on_array_index_path(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("items", ITEMS)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "x", "items": [{"sku": "s", "qty": 9}]},
            {"tag": "y", "items": [{"sku": "s", "qty": 2}, {"sku": "t", "qty": 99}]},
        ],
    )
    r = run(
        "--output", "-", "--key", "items.0.qty", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["y", "x"]


# Phrase: "map lookups with bracketed, double-quoted string keys" / 'attrs["country"]'
# Context: Keys & Partitioning with Nested.
def test_key_on_map_lookup(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("attrs", ATTRS)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "x", "attrs": {"country": "US"}},
            {"tag": "y", "attrs": {"country": "CA"}},
        ],
    )
    r = run(
        "--output", "-", "--key", 'attrs["country"]', "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["y", "x"]


# Phrase: "--partition-by attrs["country"]"
# Context: Examples; partition directories come from a nested leaf.
def test_partition_by_map_lookup(run, work, tmp_path):
    schema_file(work, "s.json", [("tag", "string"), ("attrs", ATTRS)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "x", "attrs": {"country": "US"}},
            {"tag": "y", "attrs": {"country": "CA"}},
        ],
    )
    out = tmp_path / "out"
    r = run(
        "--output", out, "--key", "tag", "--partition-by", 'attrs["country"]',
        "--schema", work.path("s.json"), work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert dirs(out) == ['attrs["country"]=CA', 'attrs["country"]=US']
    rows = read_csv_file(out / 'attrs["country"]=US' / "part-00000.csv")
    assert rows[1][0] == "x"


def test_partition_by_struct_leaf(run, work, tmp_path):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "x", "user": {"id": 7, "name": "a"}},
            {"tag": "y", "user": {"id": 8, "name": "b"}},
        ],
    )
    out = tmp_path / "out"
    r = run(
        "--output", out, "--key", "tag", "--partition-by", "user.id",
        "--schema", work.path("s.json"), work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert tree(out) == ["user.id=7/part-00000.csv", "user.id=8/part-00000.csv"]


# Phrase: "If out of range or element is null/missing → key fragment is null for that row"
# Context: Keys & Partitioning with Nested; nulls sort first (checkpoint 1).
def test_array_index_out_of_range_is_null_fragment(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("items", ITEMS)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "has", "items": [{"sku": "s", "qty": 1}, {"sku": "t", "qty": 2}]},
            {"tag": "short", "items": [{"sku": "s", "qty": 1}]},
            {"tag": "none", "items": []},
        ],
    )
    r = run(
        "--output", "-", "--key", "items.1.qty", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["short", "none", "has"]


def test_null_element_in_array_is_null_fragment(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("items", ITEMS)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "b", "items": [None]},
            {"tag": "a", "items": [{"sku": "s", "qty": 5}]},
        ],
    )
    r = run(
        "--output", "-", "--key", "items.0.qty", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["b", "a"]


# Phrase: "Map lookups with ["key"] read value by exact key ... If absent → null
#          for that fragment"
# Context: Keys & Partitioning with Nested.
def test_absent_map_key_is_null_fragment(run, work, tmp_path):
    schema_file(work, "s.json", [("tag", "string"), ("attrs", ATTRS)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "x", "attrs": {"Country": "US"}},
            {"tag": "y", "attrs": {"country": "CA"}},
        ],
    )
    out = tmp_path / "out"
    r = run(
        "--output", out, "--key", "tag", "--partition-by", 'attrs["country"]',
        "--schema", work.path("s.json"), work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert dirs(out) == ['attrs["country"]=CA', 'attrs["country"]=_null']


# Phrase: "quotes are required"
# Context: Keys & Partitioning with Nested; a bare bracket key is an error.
def test_unquoted_map_lookup_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("attrs", ATTRS)])
    work.jsonl("a.jsonl", [{"tag": "x", "attrs": {"country": "US"}}])
    r = run(
        "--output", "-", "--key", "attrs[country]", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
    assert r.stdout == ""


# Phrase: "Array indices must be non-negative integers"
# Context: Keys & Partitioning with Nested.
def test_negative_array_index_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("items", ITEMS)])
    work.jsonl("a.jsonl", [{"tag": "x", "items": [{"sku": "s", "qty": 1}]}])
    r = run(
        "--output", "-", "--key", "items.-1.qty", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
    assert r.stdout == ""


# Phrase: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
# Phrase: 'ERR 3 key column "<path>" does not resolve to a primitive'
# Context: Usage Additions / Keys & Partitioning with Nested.
def test_struct_column_as_key_exits_3_with_message(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl("a.jsonl", [{"tag": "x", "user": {"id": 1, "name": "a"}}])
    r = run(
        "--output", "-", "--key", "user", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
    assert 'ERR 3 key column "user" does not resolve to a primitive' in r.stderr


def test_array_column_as_key_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("items", ITEMS)])
    work.jsonl("a.jsonl", [{"tag": "x", "items": []}])
    r = run(
        "--output", "-", "--key", "items", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3


def test_partial_path_to_struct_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("items", ITEMS)])
    work.jsonl("a.jsonl", [{"tag": "x", "items": [{"sku": "s", "qty": 1}]}])
    r = run(
        "--output", "-", "--key", "items.0", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3


def test_map_column_as_partition_exits_3(run, work, tmp_path):
    schema_file(work, "s.json", [("tag", "string"), ("attrs", ATTRS)])
    work.jsonl("a.jsonl", [{"tag": "x", "attrs": {"country": "US"}}])
    r = run(
        "--output", tmp_path / "out", "--key", "tag", "--partition-by", "attrs",
        "--schema", work.path("s.json"), work.path("a.jsonl"),
    )
    assert r.returncode == 3


# Phrase: "Paths must resolve to primitive types"
# Context: Usage Additions; a path through a primitive goes nowhere.
def test_path_below_a_primitive_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl("a.jsonl", [{"tag": "x", "user": {"id": 1, "name": "a"}}])
    r = run(
        "--output", "-", "--key", "user.id.more", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)" (checkpoint 1)
# Context: an unknown root column is still error 3.
def test_unknown_root_column_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl("a.jsonl", [{"tag": "x", "user": {"id": 1, "name": "a"}}])
    r = run(
        "--output", "-", "--key", "nobody.id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3


# Phrase: "Field paths traverse structs" -- a field the struct does not declare
# Context: Keys & Partitioning with Nested (AMBIGUITIES T54).
def test_undeclared_struct_field_in_path_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl("a.jsonl", [{"tag": "x", "user": {"id": 1, "name": "a"}}])
    r = run(
        "--output", "-", "--key", "user.nope", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3


# Phrase: "Each path must resolve to primitive value after casting"
# Context: a `json` column is dynamic: a primitive leaf is fine ...
def test_path_into_json_column_resolving_to_primitive(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("v", "json")])
    work.jsonl(
        "a.jsonl",
        [{"tag": "x", "v": {"n": 2}}, {"tag": "y", "v": {"n": 1}}],
    )
    r = run(
        "--output", "-", "--key", "v.n", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["y", "x"]


# ... and a container leaf is error 3.
def test_path_into_json_column_resolving_to_container_exits_3(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("v", "json")])
    work.jsonl("a.jsonl", [{"tag": "x", "v": {"n": {"deep": 1}}}])
    r = run(
        "--output", "-", "--key", "v.n", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3


# Phrase: "--key <fieldPath>[,<fieldPath>...]"
# Context: Usage Additions; several paths, comma separated, mixed with flat names.
def test_multiple_key_paths(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "b", "user": {"id": 1, "name": "z"}},
            {"tag": "a", "user": {"id": 1, "name": "z"}},
            {"tag": "c", "user": {"id": 0, "name": "y"}},
        ],
    )
    r = run(
        "--output", "-", "--key", "user.id,tag", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["c", "a", "b"]


# Phrase: "--desc" with nested keys
# Context: Usage Additions; ordering rules carry over from earlier checkpoints.
def test_desc_with_nested_key(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "a", "user": {"id": 1, "name": "a"}},
            {"tag": "b", "user": {"id": 2, "name": "b"}},
        ],
    )
    r = run(
        "--output", "-", "--key", "user.id", "--desc", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["b", "a"]


# Phrase: "Sorting/partitioning comparisons follow typed ordering and null rules
#          from earlier checkpoints"
# Context: the leaf's declared type decides ordering (int, not text).
def test_nested_key_uses_typed_ordering(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl(
        "a.jsonl",
        [
            {"tag": "ten", "user": {"id": 10, "name": "a"}},
            {"tag": "nine", "user": {"id": 9, "name": "b"}},
        ],
    )
    r = run(
        "--output", "-", "--key", "user.id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["nine", "ten"]


# Phrase: "--key <fieldPath>" where a flat column is literally named with a dot
# Context: Usage Additions (AMBIGUITIES T53).
def test_flat_column_named_with_a_dot_is_matched_exactly(run, work):
    schema_file(work, "s.json", [("user.id", "int")])
    work.csv("a.csv", ["user.id"], [["2"], ["1"]])
    r = run(
        "--output", "-", "--key", "user.id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"]]


# Phrase: "the entire column value is null" rows still partition and sort
# Context: a null struct column yields a null fragment.
def test_null_struct_column_yields_null_key_fragment(run, work):
    schema_file(work, "s.json", [("tag", "string"), ("user", USER)])
    work.jsonl(
        "a.jsonl", [{"tag": "b", "user": {"id": 5, "name": "x"}}, {"tag": "a"}]
    )
    r = run(
        "--output", "-", "--key", "user.id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert [row[0] for row in body(r)] == ["a", "b"]


# Phrase: "Without --schema, nested inputs not allowed (error 6)"
# Context: Usage Additions; paths need a schema to mean anything.
def test_nested_path_without_schema_exits_3(run, work):
    work.csv("a.csv", ["user", "id"], [["x", "1"]])
    r = run("--output", "-", "--key", "user.id", work.path("a.csv"))
    assert r.returncode == 3
    assert r.stdout == ""
