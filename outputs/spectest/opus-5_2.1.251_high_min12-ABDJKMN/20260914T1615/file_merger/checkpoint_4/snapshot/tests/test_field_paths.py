"""Spec section: Nested Types Support — "Keys & Partitioning with Nested"."""

import os

from conftest import (array_t, body, col, map_t, read_text, run, run_ok,
                      struct_t, write, write_jsonl, write_nested_schema,
                      write_schema)


def tree(root):
    """Every file under `root`, as root-relative posix paths, sorted."""
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            out.append(os.path.relpath(os.path.join(base, f), root)
                       .replace(os.sep, "/"))
    return sorted(out)


# --- Spec: "`--key` and `--partition-by` now accept **field paths** using dot
#           notation (e.g., `user.id`)" ---
# Context: Usage Additions; sorting on a struct leaf.
def test_key_on_a_struct_leaf(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("user", struct_t(("id", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "user": {"id": 3}},
                                     {"id": 2, "user": {"id": 1}},
                                     {"id": 3, "user": {"id": 2}}])
    res = run_ok("--output", "-", "--key", "user.id", "--schema", s, a)
    assert col(res.stdout, "id") == ["2", "3", "1"]


# --- Spec: "field paths ... (e.g., `user.id`, `items.0.sku`)" ---
# Context: Usage Additions; numeric indices into arrays.
def test_key_on_an_array_element_field(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("items", array_t(struct_t(("sku", "string"), ("qty", "int"))))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "items": [{"sku": "m", "qty": 1}]},
        {"id": 2, "items": [{"sku": "a", "qty": 2}]},
    ])
    res = run_ok("--output", "-", "--key", "items.0.sku", "--schema", s, a)
    assert col(res.stdout, "id") == ["2", "1"]


# --- Spec: "Map lookups with `["key"]` read value by exact key" ---
# Context: Keys & Partitioning with Nested.
def test_key_on_a_map_lookup(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("attrs", map_t("string"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "attrs": {"country": "US"}},
                                     {"id": 2, "attrs": {"country": "CA"}}])
    res = run_ok("--output", "-", "--key", 'attrs["country"]', "--schema", s, a)
    assert col(res.stdout, "id") == ["2", "1"]


# --- Spec: "If absent -> null for that fragment" ---
# Context: Keys & Partitioning with Nested; missing map key sorts as null.
def test_absent_map_key_is_a_null_fragment(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("attrs", map_t("string"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "attrs": {"x": "b"}},
                                     {"id": 2, "attrs": {"country": "a"}}])
    res = run_ok("--output", "-", "--key", 'attrs["country"]', "--schema", s, a)
    assert col(res.stdout, "id") == ["1", "2"]


# --- Spec: "If out of range or element is null/missing -> key fragment is null
#           for that row" ---
# Context: Keys & Partitioning with Nested.
def test_out_of_range_index_is_a_null_fragment(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": []},
                                     {"id": 2, "xs": [5]}])
    res = run_ok("--output", "-", "--key", "xs.0", "--schema", s, a)
    assert col(res.stdout, "id") == ["1", "2"]


# --- Spec: "If out of range or element is null/missing -> key fragment is
#           null" ---
# Context: Keys & Partitioning with Nested; a null element and a null parent.
def test_null_element_and_null_parent_are_null_fragments(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": None},
                                     {"id": 2, "u": {"a": None}},
                                     {"id": 3, "u": {"a": 7}}])
    res = run_ok("--output", "-", "--key", "u.a,id", "--schema", s, a)
    assert col(res.stdout, "id") == ["1", "2", "3"]


# --- Spec: "Array indices must be non-negative integers" ---
# Context: Keys & Partitioning with Nested; a negative index is rejected (T79).
def test_negative_array_index_is_error_3(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1]}])
    res = run("--output", "-", "--key", "xs.-1", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: "Each path must resolve to a primitive value after casting.
#           Otherwise: `ERR 3 key column "<path>" does not resolve to a
#           primitive` (exit 3)" ---
# Context: Keys & Partitioning with Nested; the exact message.
def test_err3_message_for_a_non_primitive_path(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("items", array_t(struct_t(("sku", "string"))))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "items": [{"sku": "x"}]}])
    res = run("--output", "-", "--key", "items.0", "--schema", s, a)
    assert res.returncode == 3
    assert 'ERR 3 key column "items.0" does not resolve to a primitive' \
        in res.stderr


# --- Spec: "Each path must resolve to a primitive value after casting" ---
# Context: Keys & Partitioning with Nested; a struct field that does not exist.
def test_unknown_struct_field_in_a_path_is_error_3(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run("--output", "-", "--key", "u.nope", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: "Paths must resolve to primitive types (`string`, `int`, `float`,
#           `bool`, `date`, `timestamp`)" ---
# Context: Usage Additions; every primitive leaf type is a legal key.
def test_every_primitive_leaf_type_is_a_legal_key(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("u", struct_t(("s", "string"), ("i", "int"), ("f", "float"),
                       ("b", "bool"), ("d", "date"), ("t", "timestamp")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {
        "s": "x", "i": 1, "f": 1.5, "b": True, "d": "2024-01-01",
        "t": "2024-01-01T00:00:00Z"}}])
    for leaf in ("s", "i", "f", "b", "d", "t"):
        res = run_ok("--output", "-", "--key", f"u.{leaf}", "--schema", s, a)
        assert body(res.stdout)


# --- Spec: "Sorting/partitioning comparisons follow typed ordering and null
#           rules from earlier checkpoints" ---
# Context: Keys & Partitioning with Nested; numeric (not lexicographic) order.
def test_nested_key_uses_typed_ordering(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("n", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"n": 10}},
                                     {"id": 2, "u": {"n": 9}},
                                     {"id": 3, "u": {"n": 100}}])
    res = run_ok("--output", "-", "--key", "u.n", "--schema", s, a)
    assert col(res.stdout, "id") == ["2", "1", "3"]


# --- Spec: "--desc" with field paths ---
# Context: Keys & Partitioning with Nested; nulls last descending.
def test_nested_key_desc_puts_nulls_last(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("n", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"n": 1}},
                                     {"id": 2, "u": {}},
                                     {"id": 3, "u": {"n": 5}}])
    res = run_ok("--output", "-", "--key", "u.n", "--desc", "--schema", s, a)
    assert col(res.stdout, "id") == ["3", "1", "2"]


# --- Spec: "--key <fieldPath>[,<fieldPath>...]" ---
# Context: Usage Additions; multiple paths, comma separated.
def test_multiple_field_paths_in_one_key_flag(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("g", "string"), ("n", "int")))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "u": {"g": "b", "n": 1}},
        {"id": 2, "u": {"g": "a", "n": 2}},
        {"id": 3, "u": {"g": "a", "n": 1}},
    ])
    res = run_ok("--output", "-", "--key", "u.g,u.n", "--schema", s, a)
    assert col(res.stdout, "id") == ["3", "2", "1"]


# --- Spec: "--partition-by <fieldPath>[,<fieldPath>...]" with
#           "`--partition-by attrs["country"]`" ---
# Context: Examples; partitioning by a map value.
def test_partition_by_a_map_value(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("attrs", map_t("string"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "attrs": {"country": "US"}},
                                     {"id": 2, "attrs": {"country": "CA"}}])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--partition-by", 'attrs["country"]', "--schema", s, a)
    files = tree(out)
    assert len(files) == 2
    assert all(f.endswith("part-00000.csv") for f in files)
    joined = " ".join(files)
    assert "US" in joined and "CA" in joined


# --- Spec: "--partition-by <fieldPath>" ---
# Context: Keys & Partitioning with Nested; a dotted struct path partitions.
def test_partition_by_a_struct_leaf(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("user", struct_t(("g", "string")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "user": {"g": "x"}},
                                     {"id": 2, "user": {"g": "y"}}])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--partition-by", "user.g", "--schema", s, a)
    assert tree(out) == ["user.g=x/part-00000.csv", "user.g=y/part-00000.csv"]


# --- Spec: "If absent -> null for that fragment" ---
# Context: Keys & Partitioning with Nested; null partition value segment.
def test_partition_null_fragment_uses_the_null_segment(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("user", struct_t(("g", "string")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "user": {}},
                                     {"id": 2, "user": {"g": "y"}}])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--partition-by", "user.g", "--schema", s, a)
    files = tree(out)
    assert len(files) == 2
    assert any(f.startswith("user.g=y/") for f in files)


# --- Spec: "Referencing non-primitive (struct/array/map) in keys/partitions is
#           error 3" ---
# Context: Usage Additions; partitioning by a map (not a map value).
def test_partition_by_whole_map_is_error_3(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("attrs", map_t("string"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "attrs": {"c": "US"}}])
    res = run("--output", str(ws / "out"), "--key", "id",
              "--partition-by", "attrs", "--schema", s, a)
    assert res.returncode == 3
    assert "ERR 3" in res.stderr


# --- Spec: "field paths using dot notation" ---
# Context: Usage Additions; a flat column keeps working as a key (T77).
def test_plain_column_names_still_work_as_keys(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "string")])
    x = write(ws / "x.csv", "id,v\n2,b\n1,a\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, x)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "field paths using dot notation" ---
# Context: Usage Additions; a column literally named with a dot (T77).
def test_column_named_with_a_dot_wins_over_path_parsing(ws):
    s = write_schema(ws / "s.json", [("user.id", "int"), ("v", "string")])
    x = write(ws / "x.csv", "user.id,v\n2,b\n1,a\n")
    res = run_ok("--output", "-", "--key", "user.id", "--schema", s, x)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "Each path must resolve to a primitive value after casting" ---
# Context: Keys & Partitioning with Nested; a path whose root column is absent.
def test_unknown_root_column_in_a_path_is_error_3(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1}])
    res = run("--output", "-", "--key", "nosuch.leaf", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: "Each path must resolve to a primitive value after casting" ---
# Context: Keys & Partitioning with Nested; the cast value, not the raw one.
def test_key_fragment_uses_the_cast_value(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("t", "timestamp")))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "u": {"t": "2024-01-01T05:00:00+05:00"}},
        {"id": 2, "u": {"t": "2024-01-01T01:00:00Z"}},
    ])
    res = run_ok("--output", "-", "--key", "u.t", "--schema", s, a)
    assert col(res.stdout, "id") == ["1", "2"]


# --- Spec example: "--key user.id,event_time --partition-by attrs["country"]
#                    --schema schema_nested.json --on-type-error coerce-null" ---
# Context: Examples; the end-to-end shape of the first example.
def test_spec_example_key_and_partition(ws):
    s = write_nested_schema(ws / "s.json", [
        ("user", struct_t(("id", "int"))),
        ("event_time", "timestamp"),
        ("attrs", map_t("string")),
    ])
    a = write_jsonl(ws / "a.jsonl", [
        {"user": {"id": 2}, "event_time": "2024-01-01T00:00:00Z",
         "attrs": {"country": "US"}},
        {"user": {"id": 1}, "event_time": "2024-01-02T00:00:00Z",
         "attrs": {"country": "US"}},
    ])
    out = ws / "out"
    run_ok("--output", str(out), "--key", "user.id,event_time",
           "--partition-by", 'attrs["country"]', "--schema", s,
           "--on-type-error", "coerce-null", a)
    files = tree(out)
    assert len(files) == 1
    text = read_text(os.path.join(out, files[0]))
    assert col(text, "user") == ['{"id":1}', '{"id":2}']
