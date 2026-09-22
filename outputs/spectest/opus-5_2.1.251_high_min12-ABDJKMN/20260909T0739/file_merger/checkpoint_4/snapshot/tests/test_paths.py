"""Checkpoint 5: dotted/bracketed field paths in --key and --partition-by."""
from conftest import (array_of, cell, cells, dirs, map_of, merge, merge_paths,
                      nested_schema, run, struct_of, tree, write, write_jsonl)


def user_schema(tmp_path, name="s.json"):
    return nested_schema(tmp_path, name, [
        ("id", "int"),
        ("user", struct_of(("id", "int"), ("name", "string"))),
        ("items", array_of(struct_of(("sku", "string"), ("qty", "int")))),
        ("attrs", map_of("string")),
    ])


def rows_for(tmp_path):
    return write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "user": {"id": 30, "name": "c"},
         "items": [{"sku": "s1", "qty": 5}], "attrs": {"country": "NL"}},
        {"id": 2, "user": {"id": 10, "name": "a"},
         "items": [{"sku": "s2", "qty": 7}, {"sku": "s3", "qty": 1}],
         "attrs": {"country": "DE"}},
        {"id": 3, "user": {"id": 20, "name": "b"},
         "items": [], "attrs": {}},
    ])


# --- Spec: "--key ... now accept field paths using dot notation
#            (e.g., user.id)" ----------------------------------------------
def test_key_on_a_struct_field(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "user.id",
                    "--schema", str(user_schema(tmp_path)))
    assert r.ok, r
    assert cells(r, "id") == ["2", "3", "1"]


# --- Spec: "use numeric indices into arrays" (e.g., items.0.sku) ----------
def test_key_on_an_array_element_field(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "items.0.sku",
                    "--schema", str(user_schema(tmp_path)))
    assert r.ok, r
    # row 3 has no element 0 -> null fragment sorts first
    assert cells(r, "id") == ["3", "1", "2"]


# --- Spec: 'map lookups with bracketed string keys (attrs["country"])' ----
def test_key_on_a_map_lookup(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", 'attrs["country"]',
                    "--schema", str(user_schema(tmp_path)))
    assert r.ok, r
    assert cells(r, "id") == ["3", "2", "1"]


# --- Spec: "--key <fieldPath>[,<fieldPath>...]" (multiple paths) ---------
def test_multiple_paths_in_one_key_flag(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("a", "int"), ("b", "int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "u": {"a": 1, "b": 2}},
        {"id": 2, "u": {"a": 1, "b": 1}},
        {"id": 3, "u": {"a": 0, "b": 9}},
    ])
    r = merge_paths([src], "--key", "u.a,u.b", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["3", "2", "1"]


def test_comma_inside_a_bracketed_key_is_not_a_separator(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "m": {"a,b": 2}}, {"id": 2, "m": {"a,b": 1}},
    ])
    r = merge_paths([src], "--key", 'm["a,b"]', "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["2", "1"]


# --- Spec: "--desc" still applies to paths -------------------------------
def test_desc_applies_to_path_keys(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "user.id", "--desc",
                    "--schema", str(user_schema(tmp_path)))
    assert r.ok, r
    assert cells(r, "id") == ["1", "3", "2"]


# --- Spec: "Paths must resolve to primitive types" ------------------------
def test_primitive_paths_of_every_type(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("u", struct_of(("s", "string"), ("i", "int"), ("f", "float"),
                        ("b", "bool"), ("d", "date"), ("t", "timestamp"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {
        "s": "x", "i": 1, "f": 1.5, "b": True,
        "d": "2024-01-01", "t": "2024-01-01T00:00:00Z"}}])
    for leaf in ("s", "i", "f", "b", "d", "t"):
        r = merge_paths([src], "--key", f"u.{leaf}", "--schema", str(schema))
        assert r.ok, (leaf, r)


# --- Spec: 'Referencing non-primitive (struct/array/map) in keys/partitions
#            is error 3' + 'ERR 3 key column "<path>" does not resolve to a
#            primitive' ---------------------------------------------------
def test_struct_as_key_is_error_3(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "user",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r
    assert r.stderr == ('ERR 3 key column "user" does not resolve to a '
                        'primitive\n'), r.stderr


def test_array_as_key_is_error_3(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "items",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


def test_map_as_key_is_error_3(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "attrs",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


def test_struct_element_of_array_as_key_is_error_3(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "items.0",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


def test_nested_column_as_partition_is_error_3(tmp_path):
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "user",
            "--schema", str(user_schema(tmp_path)), str(rows_for(tmp_path)))
    assert r.returncode == 3, r
    assert "user" in r.stderr


def test_unknown_root_column_in_a_path_is_error_3(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "nope.id",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


def test_unknown_struct_field_in_a_path_is_error_3(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "user.nope",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


# --- Spec: "Array indices must be non-negative integers" -----------------
def test_negative_array_index_is_rejected(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "items.-1.qty",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


def test_non_numeric_segment_on_an_array_is_rejected(tmp_path):
    r = merge_paths([rows_for(tmp_path)], "--key", "items.sku",
                    "--schema", str(user_schema(tmp_path)))
    assert r.returncode == 3, r


# --- Spec: "If out of range or element is null/missing -> key fragment is
#            null for that row" -------------------------------------------
def test_out_of_range_index_yields_a_null_fragment(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "xs": [9, 9]}, {"id": 2, "xs": [5]}, {"id": 3, "xs": None},
    ])
    r = merge_paths([src], "--key", "xs.1,id", "--schema", str(schema))
    assert r.ok, r
    # nulls sort first, and ties fall back to id
    assert cells(r, "id") == ["2", "3", "1"]


def test_null_element_yields_a_null_fragment(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "xs": [1]}, {"id": 2, "xs": [None]}])
    r = merge_paths([src], "--key", "xs.0", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["2", "1"]


# --- Spec: 'Map lookups with ["key"] read value by exact key. If absent ->
#            null for that fragment' --------------------------------------
def test_map_lookup_is_exact_and_missing_keys_are_null(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of("string"))])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "m": {"k": "v"}},
        {"id": 2, "m": {"K": "v"}},
        {"id": 3, "m": {}},
    ])
    r = merge_paths([src], "--key", 'm["k"],id', "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["2", "3", "1"]


# --- Spec: "Field paths traverse structs" through several levels ---------
def test_deeply_nested_path(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("a", struct_of(("b", map_of(array_of(struct_of(("c", "int"))))))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "a": {"b": {"k": [{"c": 2}]}}},
        {"id": 2, "a": {"b": {"k": [{"c": 1}]}}},
    ])
    r = merge_paths([src], "--key", 'a.b["k"].0.c', "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["2", "1"]


# --- Spec: "--partition-by <fieldPath>" - 'partition by map value' -------
def test_partition_by_a_map_value(tmp_path):
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id",
            "--partition-by", 'attrs["country"]',
            "--schema", str(user_schema(tmp_path)), str(rows_for(tmp_path)))
    assert r.ok, r
    assert dirs(out) == ['attrs%5B%22country%22%5D=DE',
                         'attrs%5B%22country%22%5D=NL',
                         'attrs%5B%22country%22%5D=_null']


def test_partition_by_a_struct_field(tmp_path):
    out = tmp_path / "out"
    r = run("--output", str(out), "--key", "id", "--partition-by", "user.name",
            "--schema", str(user_schema(tmp_path)), str(rows_for(tmp_path)))
    assert r.ok, r
    assert dirs(out) == ["user.name=a", "user.name=b", "user.name=c"]


# --- Spec: "Sorting/partitioning comparisons follow typed ordering and null
#            rules from earlier checkpoints" ------------------------------
def test_typed_ordering_of_path_keys(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "u": {"n": 10}}, {"id": 2, "u": {"n": 9}}, {"id": 3, "u": {"n": 100}},
    ])
    r = merge_paths([src], "--key", "u.n", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["2", "1", "3"]


def test_stability_for_equal_path_keys(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("n", "int")))])
    a = write_jsonl(tmp_path, "a.jsonl",
                    [{"id": 1, "u": {"n": 1}}, {"id": 2, "u": {"n": 1}}])
    b = write_jsonl(tmp_path, "b.jsonl", [{"id": 3, "u": {"n": 1}}])
    r = merge_paths([a, b], "--key", "u.n", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["1", "2", "3"]


# --- Spec: paths still work when the column is a `json` blob
#           (AMBIGUITIES T63) ---------------------------------------------
def test_path_into_a_json_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "v": {"k": 2}}, {"id": 2, "v": {"k": 1}}])
    r = merge_paths([src], "--key", "v.k", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["2", "1"]


def test_json_column_itself_as_key_is_error_3(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": {"k": 2}}])
    r = merge_paths([src], "--key", "v", "--schema", str(schema))
    assert r.returncode == 3, r


# --- Spec: a flat column name that contains a dot (AMBIGUITIES T59) ------
def test_literal_dotted_column_name_still_usable_as_key(tmp_path):
    files = {"a.csv": "user.id,v\n2,x\n1,y\n"}
    r = merge(tmp_path, files, "--key", "user.id")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == ["1", "2"]


# --- Spec: keys/partitions on plain columns keep working -----------------
def test_flat_key_beside_a_nested_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 2, "u": {"a": 1}}, {"id": 1, "u": {"a": 2}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "id") == ["1", "2"]
