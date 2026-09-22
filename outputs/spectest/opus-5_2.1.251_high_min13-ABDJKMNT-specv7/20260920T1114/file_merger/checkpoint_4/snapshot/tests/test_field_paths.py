"""Spec section: Keys & Partitioning with Nested — dotted and bracketed field paths."""

from conftest import column, rows_of, tree
from nested_helpers import INT, array, mapping, struct, write_schema


USER = {"name": "user", "type": struct(("id", "int"), ("name", "string"))}
ITEMS = {"name": "items", "type": array(struct(("sku", "string"), ("qty", "int")))}
ATTRS = {"name": "attrs", "type": mapping("string")}


# Phrase: "--key and --partition-by now accept field paths using dot notation (e.g. user.id)"
# Context: Usage Additions. The sort follows the nested leaf, not the column text.
def test_key_on_a_struct_field(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, USER])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "user": {"id": 30, "name": "c"}},
            {"id": 2, "user": {"id": 4, "name": "a"}},
            {"id": 3, "user": {"id": 200, "name": "b"}},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "user.id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["2", "1", "3"]


# Phrase: "use numeric indices into arrays ... Examples: items.0.qty"
# Context: Keys & Partitioning with Nested.
def test_key_on_an_array_element(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ITEMS])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "items": [{"sku": "x", "qty": 9}]},
            {"id": 2, "items": [{"sku": "y", "qty": 2}, {"sku": "z", "qty": 99}]},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "items.0.qty", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["2", "1"]


# Phrase: 'map lookups with bracketed, double-quoted string keys ... attrs["country"]'
# Context: Keys & Partitioning with Nested.
def test_key_on_a_map_entry(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "attrs": {"country": "US"}},
            {"id": 2, "attrs": {"country": "DE"}},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", 'attrs["country"]', "--schema", "schema.json",
        "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["2", "1"]


# Phrase: "If out of range or element is null/missing -> key fragment is null for that row"
# Context: Keys & Partitioning with Nested. Nulls sort before values.
def test_out_of_range_index_is_a_null_fragment(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ITEMS])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "items": [{"sku": "x", "qty": 1}, {"sku": "y", "qty": 5}]},
            {"id": 2, "items": [{"sku": "x", "qty": 1}]},
            {"id": 3, "items": None},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "items.1.qty", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["2", "3", "1"]


# Phrase: "If absent -> null for that fragment"
# Context: Keys & Partitioning with Nested (map lookups).
def test_absent_map_key_is_a_null_fragment(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file(
        "a.jsonl",
        [{"id": 1, "attrs": {"country": "US"}}, {"id": 2, "attrs": {"city": "Berlin"}}],
    )
    result = run_tool(
        "--output", "-", "--key", 'attrs["country"]', "--schema", "schema.json",
        "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["2", "1"]


# Phrase: "Map lookups with [\"key\"] read value by exact key"
# Context: Keys & Partitioning with Nested. Lookup is exact, not case-folded.
def test_map_lookup_is_exact(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file(
        "a.jsonl",
        [{"id": 1, "attrs": {"Country": "US"}}, {"id": 2, "attrs": {"country": "US"}}],
    )
    result = run_tool(
        "--output", "-", "--key", 'attrs["country"],id', "--schema", "schema.json",
        "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["1", "2"]


# Phrase: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
# Context: Usage Additions.
def test_struct_column_as_key_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, USER])
    jsonl_file("a.jsonl", [{"id": 1, "user": {"id": 1, "name": "a"}}])
    result = run_tool(
        "--output", "-", "--key", "user", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert 'ERR 3 key column "user" does not resolve to a primitive' in result.stderr


# Phrase: "Each path must resolve to a primitive value after casting"
# Context: Keys & Partitioning with Nested. An array-typed leaf is not primitive.
def test_array_leaf_as_key_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": [1]}])
    result = run_tool(
        "--output", "-", "--key", "xs", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert "does not resolve to a primitive" in result.stderr


# Phrase: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
# Context: Usage Additions. Partitions are checked the same way.
def test_non_primitive_partition_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file("a.jsonl", [{"id": 1, "attrs": {"a": "b"}}])
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "attrs",
        "--schema", "schema.json", "a.jsonl",
    )
    assert result.returncode == 3
    assert "does not resolve to a primitive" in result.stderr


# Phrase: "Array indices must be non-negative integers"
# Context: Keys & Partitioning with Nested.
def test_negative_array_index_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ITEMS])
    jsonl_file("a.jsonl", [{"id": 1, "items": []}])
    result = run_tool(
        "--output", "-", "--key", "items.-1.qty", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "quotes are required"
# Context: Keys & Partitioning with Nested (map lookups).
def test_unquoted_map_lookup_is_rejected(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file("a.jsonl", [{"id": 1, "attrs": {"country": "US"}}])
    result = run_tool(
        "--output", "-", "--key", "attrs[country]", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "Field paths traverse structs"
# Context: Keys & Partitioning with Nested. An unknown field is a schema error.
def test_unknown_struct_field_in_a_path_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, USER])
    jsonl_file("a.jsonl", [{"id": 1, "user": {"id": 1, "name": "a"}}])
    result = run_tool(
        "--output", "-", "--key", "user.nope", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "Sorting/partitioning comparisons follow typed ordering and null rules"
# Context: Keys & Partitioning with Nested. --desc reverses a nested key.
def test_descending_sort_on_a_nested_key(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, USER])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "user": {"id": 2, "name": "a"}},
            {"id": 2, "user": {"id": 10, "name": "b"}},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "user.id", "--desc", "--schema", "schema.json",
        "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["2", "1"]


# Phrase: "--key <fieldPath>[,<fieldPath>...]"
# Context: Usage Additions. Several paths compose one key, left to right.
def test_several_paths_make_one_key(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, USER])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 2, "user": {"id": 1, "name": "b"}},
            {"id": 1, "user": {"id": 1, "name": "b"}},
            {"id": 3, "user": {"id": 0, "name": "a"}},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "user.id,id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "id") == ["3", "1", "2"]


# Phrase: "--partition-by <fieldPath>[,<fieldPath>...]"
# Context: Usage Additions. Ambiguity T54: the path itself names the directory.
def test_partition_directory_is_named_after_the_path(workdir, jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, USER])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "user": {"id": 7, "name": "a"}},
            {"id": 2, "user": {"id": 8, "name": "b"}},
        ],
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", "user.id",
        "--schema", "schema.json", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "user.id=7/part-00000.csv",
        "user.id=8/part-00000.csv",
    ]


# Phrase: "If out of range or element is null/missing -> key fragment is null"
# Context: Keys & Partitioning with Nested. A null fragment partitions under _null.
def test_null_fragment_partitions_under_null(workdir, jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file(
        "a.jsonl",
        [{"id": 1, "attrs": {"country": "US"}}, {"id": 2, "attrs": {}}],
    )
    result = run_tool(
        "--output", "out", "--key", "id", "--partition-by", 'attrs["country"]',
        "--schema", "schema.json", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        'attrs["country"]=US/part-00000.csv',
        'attrs["country"]=_null/part-00000.csv',
    ]


# Phrase: "Each path must resolve to a primitive value after casting"
# Context: Keys & Partitioning with Nested. Ambiguity T55: a flat dotted name still works.
def test_flat_column_named_with_a_dot(csv_file, run_tool):
    csv_file("a.csv", "user.id\n2\n1\n")
    result = run_tool("--output", "-", "--key", "user.id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["2"]]


# Phrase: "--key <fieldPath>[,<fieldPath>...]"
# Context: Usage Additions. Ambiguity T56: commas inside a quoted key do not split.
def test_comma_inside_a_map_key_does_not_split_the_list(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, ATTRS])
    jsonl_file("a.jsonl", [{"id": 1, "attrs": {"a,b": "z"}}])
    result = run_tool(
        "--output", "-", "--key", 'attrs["a,b"]', "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", '{"a,b":"z"}']]


# Phrase: "Each path must resolve to a primitive value after casting"
# Context: Keys & Partitioning with Nested. Ambiguity T59: a json column has no
# declared leaves, so a path through one cannot be shown to reach a primitive.
def test_path_into_a_json_column_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "p", "type": "json"}])
    jsonl_file("a.jsonl", [{"id": 1, "p": {"x": 1}}])
    result = run_tool(
        "--output", "-", "--key", "p.x", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr
