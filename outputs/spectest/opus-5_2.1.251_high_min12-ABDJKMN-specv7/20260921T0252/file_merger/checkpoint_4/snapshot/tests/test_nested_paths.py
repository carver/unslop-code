"""Spec section: Keys & Partitioning with Nested (checkpoint 4)."""
import json

from conftest import (array_t, cell, col, concat_col, map_t, part_files,
                      read_rows, run_tool, struct_t, tree_dirs, tree_files,
                      write_csv, write_json, write_jsonl,
                      write_nested_schema)


def user_schema(tmp_path):
    """id + user{id,name} + items[{sku,qty}] + attrs map<string,string>."""
    return write_nested_schema(
        tmp_path / "s.json",
        ("id", "int"),
        ("user", struct_t(("id", "int"), ("name", "string"))),
        ("items", array_t(struct_t(("sku", "string"), ("qty", "int")))),
        ("attrs", map_t("string")))


def rows_jsonl(tmp_path, objects, name="a.jsonl"):
    return write_jsonl(tmp_path / name, objects)


# --------------------------------------------------------------------------
# Phrase: "--key and --partition-by now accept field paths using dot notation
#          (e.g., user.id, items.0.sku)"
# Context: Usage Additions.
# --------------------------------------------------------------------------
def test_key_on_a_struct_field(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "user": {"id": 30, "name": "c"}},
        {"id": 2, "user": {"id": 10, "name": "a"}},
        {"id": 3, "user": {"id": 20, "name": "b"}},
    ])
    res = run_tool("--output", "-", "--key", "user.id", "--schema", schema,
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "3", "1"]


def test_key_on_an_array_index_path(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "items": [{"sku": "m", "qty": 1}]},
        {"id": 2, "items": [{"sku": "a", "qty": 2}]},
    ])
    res = run_tool("--output", "-", "--key", "items.0.sku", "--schema",
                   schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]


def test_key_on_a_map_lookup(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "attrs": {"country": "US"}},
        {"id": 2, "attrs": {"country": "DE"}},
    ])
    res = run_tool("--output", "-", "--key", 'attrs["country"]',
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]


# Phrase: "--key <fieldPath>[,<fieldPath>...]"
# Context: several paths in one comma separated argument.
def test_multiple_paths_in_one_key_argument(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 3, "user": {"id": 1, "name": "b"}},
        {"id": 1, "user": {"id": 1, "name": "a"}},
        {"id": 2, "user": {"id": 0, "name": "z"}},
    ])
    res = run_tool("--output", "-", "--key", "user.id,user.name",
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1", "3"]


# Phrase: "[--desc]"
# Context: a descending sort on a nested leaf.
def test_desc_on_a_nested_key(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "user": {"id": 1, "name": "a"}},
        {"id": 2, "user": {"id": 2, "name": "b"}},
    ])
    res = run_tool("--output", "-", "--key", "user.id", "--desc",
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]


# Phrase: "Paths must resolve to primitive types (string, int, float, bool,
#          date, timestamp)"
# Context: typed ordering, not text ordering, applies to the leaf.
def test_nested_int_key_sorts_numerically(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "user": {"id": 100, "name": "a"}},
        {"id": 2, "user": {"id": 9, "name": "b"}},
    ])
    res = run_tool("--output", "-", "--key", "user.id", "--schema", schema,
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]


def test_nested_timestamp_key_sorts_chronologically(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("ts", "timestamp"))))
    src = rows_jsonl(tmp_path, [
        {"id": 1, "u": {"ts": "2024-01-02T03:04:05.5Z"}},
        {"id": 2, "u": {"ts": "2024-01-02T03:04:05Z"}},
        {"id": 3, "u": {"ts": "2024-01-02T00:00:00+05:00"}},
    ])
    res = run_tool("--output", "-", "--key", "u.ts", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["3", "2", "1"]


# --------------------------------------------------------------------------
# Phrase: "Referencing non-primitive (struct/array/map) in keys/partitions is
#          error 3"
# Context: Usage Additions; the message is quoted in Keys & Partitioning.
# --------------------------------------------------------------------------
def test_key_on_a_struct_column_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "user": {"id": 1, "name": "a"}}])
    res = run_tool("--output", "-", "--key", "user", "--schema", schema, src)
    assert res.returncode == 3
    assert "does not resolve to a primitive" in res.stderr
    assert '"user"' in res.stderr


def test_key_on_an_array_column_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "items": []}])
    res = run_tool("--output", "-", "--key", "items", "--schema", schema, src)
    assert res.returncode == 3


def test_key_on_a_map_column_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "attrs": {}}])
    res = run_tool("--output", "-", "--key", "attrs", "--schema", schema, src)
    assert res.returncode == 3


def test_key_on_a_partial_path_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "items": []}])
    res = run_tool("--output", "-", "--key", "items.0", "--schema", schema,
                   src)
    assert res.returncode == 3


def test_partition_on_a_non_primitive_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "attrs": {}}])
    res = run_tool("--output", str(tmp_path / "out"), "--key", "id",
                   "--partition-by", "attrs", "--schema", schema, src)
    assert res.returncode == 3


def test_key_on_a_json_column_is_error_3(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = rows_jsonl(tmp_path, [{"id": 1, "v": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "v.a", "--schema", schema, src)
    assert res.returncode == 3


def test_unknown_leading_column_in_a_path_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1}])
    res = run_tool("--output", "-", "--key", "nope.x", "--schema", schema,
                   src)
    assert res.returncode == 3


def test_unknown_struct_field_in_a_path_is_error_3(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1}])
    res = run_tool("--output", "-", "--key", "user.nope", "--schema", schema,
                   src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# Phrase: "Array indices must be non-negative integers"
# Context: Keys & Partitioning with Nested.
# --------------------------------------------------------------------------
def test_negative_array_index_is_an_error(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "items": []}])
    res = run_tool("--output", "-", "--key", "items.-1.sku", "--schema",
                   schema, src)
    assert res.returncode == 3


def test_non_integer_array_index_is_an_error(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "items": []}])
    res = run_tool("--output", "-", "--key", "items.first.sku", "--schema",
                   schema, src)
    assert res.returncode == 3


# Phrase: "If out of range or element is null/missing -> key fragment is null
#          for that row"
def test_out_of_range_index_is_a_null_fragment(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "items": []},
        {"id": 2, "items": [{"sku": "a", "qty": 1}]},
    ])
    res = run_tool("--output", "-", "--key", "items.0.sku", "--schema",
                   schema, src)
    assert res.returncode == 0, res.stderr
    # Nulls sort first (checkpoint 1 rule) and the row survives.
    assert col(res.rows(), "id") == ["1", "2"]


def test_null_element_is_a_null_fragment(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("t", array_t("int")))
    src = rows_jsonl(tmp_path, [
        {"id": 1, "t": [None]},
        {"id": 2, "t": [5]},
    ])
    res = run_tool("--output", "-", "--key", "t.0", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


def test_missing_nested_column_is_a_null_fragment(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1},
        {"id": 2, "user": {"id": 5, "name": "x"}},
    ])
    res = run_tool("--output", "-", "--key", "user.id", "--schema", schema,
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


# --------------------------------------------------------------------------
# Phrase: "Map lookups with ["key"] read value by exact key; quotes are
#          required"
# --------------------------------------------------------------------------
def test_map_lookup_is_exact(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "attrs": {"Country": "US"}},
        {"id": 2, "attrs": {"country": "DE"}},
    ])
    res = run_tool("--output", "-", "--key", 'attrs["country"]',
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    # Row 1 has no exact "country" key -> null fragment, sorts first.
    assert col(res.rows(), "id") == ["1", "2"]


def test_absent_map_key_is_a_null_fragment(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "attrs": {}},
        {"id": 2, "attrs": {"country": "DE"}},
    ])
    res = run_tool("--output", "-", "--key", 'attrs["country"]',
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


def test_unquoted_map_key_is_an_error(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "attrs": {"country": "US"}}])
    res = run_tool("--output", "-", "--key", "attrs[country]", "--schema",
                   schema, src)
    assert res.returncode == 3


def test_dotted_map_access_is_an_error(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "attrs": {"country": "US"}}])
    res = run_tool("--output", "-", "--key", "attrs.country", "--schema",
                   schema, src)
    assert res.returncode == 3


def test_map_key_with_a_dot_inside(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("m", map_t("int")))
    src = rows_jsonl(tmp_path, [
        {"id": 1, "m": {"a.b": 2}},
        {"id": 2, "m": {"a.b": 1}},
    ])
    res = run_tool("--output", "-", "--key", 'm["a.b"]', "--schema", schema,
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]


# --------------------------------------------------------------------------
# Phrase: "--partition-by <fieldPath>[,<fieldPath>...]"
# Context: partition by a map value, as in the spec's example.
# --------------------------------------------------------------------------
def test_partition_by_a_map_value(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "attrs": {"country": "US"}},
        {"id": 2, "attrs": {"country": "DE"}},
    ])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "id",
                   "--partition-by", 'attrs["country"]',
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    dirs = tree_dirs(out)
    assert len(dirs) == 2
    assert all(d.endswith("=US") or d.endswith("=DE") for d in dirs)


def test_partition_by_a_struct_field(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [
        {"id": 1, "user": {"id": 7, "name": "a"}},
        {"id": 2, "user": {"id": 8, "name": "b"}},
    ])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "id",
                   "--partition-by", "user.id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert sorted(tree_dirs(out)) == ["user.id=7", "user.id=8"]


def test_partition_value_is_the_leaf_not_the_cell(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "user": {"id": 7, "name": "a"}}])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "id",
                   "--partition-by", "user.id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    rows = read_rows(out / "user.id=7" / "part-00000.csv")
    assert rows[0] == ["id", "user", "items", "attrs"]
    assert rows[1][1] == '{"id":7,"name":"a"}'


def test_null_nested_partition_value_uses_the_null_segment(tmp_path):
    schema = user_schema(tmp_path)
    src = rows_jsonl(tmp_path, [{"id": 1, "attrs": {}}])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "id",
                   "--partition-by", 'attrs["country"]',
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    dirs = tree_dirs(out)
    assert len(dirs) == 1
    assert dirs[0].endswith("=_null")


# Phrase: "Sorting/partitioning comparisons follow typed ordering and null
#          rules from earlier checkpoints"
def test_sorting_inside_a_nested_partition_is_stable(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("g", "string"),
                                                ("k", "int"))))
    src = rows_jsonl(tmp_path, [
        {"id": 1, "u": {"g": "a", "k": 2}},
        {"id": 2, "u": {"g": "a", "k": 1}},
        {"id": 3, "u": {"g": "b", "k": 3}},
    ])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "u.k",
                   "--partition-by", "u.g", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert concat_col(out / "u.g=a", "id") == ["2", "1"]
    assert concat_col(out / "u.g=b", "id") == ["3"]


# --------------------------------------------------------------------------
# Phrase: "user.id" / dotted names (T58)
# Context: a flat column whose name literally contains a dot still resolves.
# --------------------------------------------------------------------------
def test_literal_dotted_column_name_wins(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["user.id,v", "2,x", "1,y"])
    res = run_tool("--output", "-", "--key", "user.id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["y", "x"]


def test_dotted_key_without_schema_and_without_column_is_error_3(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,v", "1,x"])
    res = run_tool("--output", "-", "--key", "user.id", src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# Phrase: "Without --schema, nested inputs not allowed (error 6)"
# Context: Determinism Checklist; paths need a schema to mean anything.
# --------------------------------------------------------------------------
def test_example_command_shape(tmp_path):
    # python merge_files.py --output out/ --key user.id,event_time
    #          --partition-by attrs["country"] --schema schema_nested.json
    #          --on-type-error coerce-null inputs/events.jsonl
    schema = write_nested_schema(
        tmp_path / "schema_nested.json",
        ("user", struct_t(("id", "int"))),
        ("event_time", "timestamp"),
        ("attrs", map_t("string")))
    src = write_jsonl(tmp_path / "events.jsonl", [
        {"user": {"id": 2}, "event_time": "2024-01-01T00:00:00Z",
         "attrs": {"country": "US"}},
        {"user": {"id": 1}, "event_time": "2024-01-02T00:00:00Z",
         "attrs": {"country": "DE"}},
    ])
    out = tmp_path / "out"
    res = run_tool("--output", str(out), "--key", "user.id,event_time",
                   "--partition-by", 'attrs["country"]',
                   "--schema", schema, "--on-type-error", "coerce-null", src)
    assert res.returncode == 0, res.stderr
    files = tree_files(out)
    assert len(files) == 2
    assert all(f.endswith("part-00000.csv") for f in files)
