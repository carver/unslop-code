"""Dotted and bracketed field paths in --key and --partition-by."""

from conftest import array, column, mapping, rows_of, struct


def _schema(make_schema):
    """A schema holding every shape a path can traverse."""
    return make_schema(
        "s.json",
        [
            ("id", "int"),
            ("user", struct(("id", "int"), ("name", "string"))),
            ("items", array(struct(("sku", "string"), ("qty", "int")))),
            ("attrs", mapping("string")),
        ],
    )


# Spec: "`--key` and `--partition-by` now accept field paths using dot notation
# (e.g., `user.id`)"
def test_key_path_sorts_by_a_struct_field(make_jsonl, make_schema, run):
    make_jsonl(
        "a.jsonl",
        [{"id": 1, "user": {"id": 3, "name": "c"}}, {"id": 2, "user": {"id": 1, "name": "a"}}],
    )
    _schema(make_schema)
    proc = run("--output", "-", "--key", "user.id", "--schema", "s.json", "a.jsonl")
    assert column(rows_of(proc.stdout), "id") == ["2", "1"]


# Spec: "Field paths ... use numeric indices into arrays" (e.g., `items.0.sku`)
def test_key_path_indexes_into_an_array(make_jsonl, make_schema, run):
    make_jsonl(
        "a.jsonl",
        [{"id": 1, "items": [{"sku": "z", "qty": 1}]}, {"id": 2, "items": [{"sku": "a", "qty": 2}]}],
    )
    _schema(make_schema)
    proc = run("--output", "-", "--key", "items.0.sku", "--schema", "s.json", "a.jsonl")
    assert column(rows_of(proc.stdout), "id") == ["2", "1"]


# Spec: "map lookups with bracketed, double-quoted string keys ... `attrs["country"]`"
def test_key_path_looks_a_map_key_up(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "attrs": {"country": "US"}}, {"id": 2, "attrs": {"country": "FR"}}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", 'attrs["country"]', "--schema", "s.json", "a.jsonl")
    assert column(rows_of(proc.stdout), "id") == ["2", "1"]


# Spec: "Nested schema; key on nested leaf; partition by map value" - the
# checkpoint's own example.
def test_partition_by_a_map_value(make_jsonl, make_schema, run, tree):
    make_jsonl(
        "a.jsonl",
        [
            {"id": 1, "user": {"id": 2}, "attrs": {"country": "US"}},
            {"id": 2, "user": {"id": 1}, "attrs": {"country": "FR"}},
        ],
    )
    _schema(make_schema)
    run(
        "--output", "out", "--key", "user.id", "--partition-by", 'attrs["country"]',
        "--schema", "s.json", "a.jsonl",
    )
    assert tree("out") == ['attrs["country"]=FR/part-00000.csv', 'attrs["country"]=US/part-00000.csv']


# Spec: "If out of range or element is null/missing -> key fragment is null for
# that row"
def test_an_out_of_range_index_is_a_null_fragment(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "items": [{"sku": "a", "qty": 1}]}, {"id": 2, "items": []}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", "items.0.sku", "--schema", "s.json", "a.jsonl")
    assert column(rows_of(proc.stdout), "id") == ["2", "1"]


# Spec: "If out of range or element is null/missing -> key fragment is null for
# that row"
def test_a_missing_struct_parent_is_a_null_fragment(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"id": 5}}, {"id": 2}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", "user.id", "--schema", "s.json", "a.jsonl")
    assert column(rows_of(proc.stdout), "id") == ["2", "1"]


# Spec: "Map lookups with `["key"]` read value by exact key ... If absent -> null
# for that fragment"
def test_an_absent_map_key_is_a_null_fragment(make_jsonl, make_schema, run, tree):
    make_jsonl("a.jsonl", [{"id": 1, "attrs": {"country": "US"}}, {"id": 2, "attrs": {"city": "NYC"}}])
    _schema(make_schema)
    run("--output", "out", "--key", "id", "--partition-by", 'attrs["country"]', "--schema", "s.json", "a.jsonl")
    assert tree("out") == ['attrs["country"]=US/part-00000.csv', 'attrs["country"]=_null/part-00000.csv']


# Spec: "Map lookups with `["key"]` read value by exact key"
def test_map_lookup_is_by_exact_key(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "attrs": {"Country": "US", "country": "FR"}}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", 'attrs["country"]', "--schema", "s.json", "--desc", "a.jsonl")
    assert column(rows_of(proc.stdout), "attrs") == ['{"Country":"US","country":"FR"}']


# Spec: "Referencing non-primitive (struct/array/map) in keys/partitions is
# error 3" and "ERR 3 key column "<path>" does not resolve to a primitive"
def test_a_key_on_a_struct_is_error_three(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"id": 5}}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", "user", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode == 3
    assert 'ERR 3 key column "user" does not resolve to a primitive' in proc.stderr


# Spec: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
def test_a_key_on_an_array_or_a_map_is_error_three(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    _schema(make_schema)
    for path in ("items", "items.0", "attrs"):
        proc = run("--output", "-", "--key", path, "--schema", "s.json", "a.jsonl", expect_ok=False)
        assert proc.returncode == 3, path


# Spec: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
# Context: a partition path is checked the same way.
def test_a_partition_on_a_struct_is_error_three(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"id": 5}}])
    _schema(make_schema)
    proc = run(
        "--output", "out", "--key", "id", "--partition-by", "user",
        "--schema", "s.json", "a.jsonl", expect_ok=False,
    )
    assert proc.returncode == 3


# Spec: "Each path must resolve to a primitive value after casting"
# Context: see AMBIGUITIES T54 - a `json` column declares nothing primitive.
def test_a_key_inside_a_json_column_is_error_three(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "flex": {"a": 1}}])
    make_schema("s.json", [("id", "int"), ("flex", "json")])
    proc = run("--output", "-", "--key", "flex.a", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode == 3


# Spec: "Array indices must be non-negative integers"
def test_a_negative_or_non_numeric_array_index_is_rejected(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    _schema(make_schema)
    for path in ("items.-1.sku", "items.x.sku"):
        proc = run("--output", "-", "--key", path, "--schema", "s.json", "a.jsonl", expect_ok=False)
        assert proc.returncode == 3, path


# Spec: "Map lookups with `["key"]` ... quotes are required"
# Context: see AMBIGUITIES T56 - a bracket without quotes is a usage error.
def test_a_map_lookup_without_quotes_is_a_usage_error(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", "attrs[country]", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode == 2


# Spec: "Paths must resolve to primitive types"
# Context: a path whose first segment names no column is the checkpoint-1 error.
def test_an_unknown_first_segment_is_error_three(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    _schema(make_schema)
    proc = run("--output", "-", "--key", "nope.id", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode == 3


# Spec: "`--key <fieldPath>[,<fieldPath>...]`"
def test_several_paths_sort_most_significant_first(make_jsonl, make_schema, run):
    make_jsonl(
        "a.jsonl",
        [
            {"id": 1, "user": {"id": 1, "name": "b"}},
            {"id": 2, "user": {"id": 1, "name": "a"}},
            {"id": 3, "user": {"id": 0, "name": "z"}},
        ],
    )
    _schema(make_schema)
    proc = run("--output", "-", "--key", "user.id,user.name", "--schema", "s.json", "a.jsonl")
    assert column(rows_of(proc.stdout), "id") == ["3", "2", "1"]


# Spec: "Sorting/partitioning comparisons follow typed ordering and null rules
# from earlier checkpoints"
def test_paths_sort_by_the_cast_type_and_honour_desc(make_jsonl, make_schema, run):
    make_jsonl(
        "a.jsonl",
        [{"id": 1, "user": {"id": "10"}}, {"id": 2, "user": {"id": "9"}}],
    )
    _schema(make_schema)
    ascending = run("--output", "-", "--key", "user.id", "--schema", "s.json", "a.jsonl")
    descending = run("--output", "-", "--key", "user.id", "--desc", "--schema", "s.json", "a.jsonl")
    assert column(rows_of(ascending.stdout), "id") == ["2", "1"]
    assert column(rows_of(descending.stdout), "id") == ["1", "2"]


# Spec: "`--key` and `--partition-by` now accept field paths using dot notation"
# Context: see AMBIGUITIES T63 - a column whose own name contains a dot is still
# reachable by naming it in full.
def test_a_column_named_with_a_dot_is_still_a_column(make_csv, run):
    make_csv("a.csv", "user.id\n2\n1\n")
    proc = run("--output", "-", "--key", "user.id", "a.csv")
    assert rows_of(proc.stdout) == [["user.id"], ["1"], ["2"]]
