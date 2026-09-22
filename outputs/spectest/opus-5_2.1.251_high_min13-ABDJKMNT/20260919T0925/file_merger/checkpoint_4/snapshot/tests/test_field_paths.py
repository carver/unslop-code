"""`--key` and `--partition-by` field paths: traversal, null fragments, error 3."""

import pytest

NESTED_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {
            "name": "user",
            "type": {
                "struct": {
                    "fields": [{"name": "id", "type": "int"}, {"name": "name", "type": "string"}]
                }
            },
        },
        {
            "name": "items",
            "type": {
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
            },
        },
        {"name": "attrs", "type": {"map": {"key": "string", "value": "string"}}},
    ]
}


def row(id_, user_id=None, items=(), attrs=None):
    return {
        "id": id_,
        "user": {"id": user_id, "name": f"n{id_}"},
        "items": list(items),
        "attrs": attrs or {},
    }


@pytest.fixture
def nested_schema(json_file):
    return json_file("schema.json", NESTED_SCHEMA)


# Spec: "--key ... now accept field paths using dot notation (e.g., user.id)"
def test_key_on_a_struct_leaf(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, user_id=30), row(2, user_id=10), row(3, user_id=20)])
    result = run_cli("--output", "-", "--key", "user.id", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "3", "1"]


# Spec: "--key ... field paths ... (e.g., items.0.sku)"
def test_key_on_an_array_element_field(run_cli, jsonl_file, nested_schema):
    data = jsonl_file(
        "a.jsonl",
        [row(1, items=[{"sku": "z", "qty": 1}]), row(2, items=[{"sku": "a", "qty": 2}])],
    )
    result = run_cli("--output", "-", "--key", "items.0.sku", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: "Map lookups with [\"key\"] read value by exact key"
def test_key_on_a_map_lookup(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, attrs={"country": "US"}), row(2, attrs={"country": "DE"})])
    result = run_cli("--output", "-", "--key", 'attrs["country"]', "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: the first example — "--key user.id,event_time"
def test_multiple_keys_mixing_paths_and_plain_columns(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(2, user_id=1), row(1, user_id=1), row(3, user_id=0)])
    result = run_cli("--output", "-", "--key", "user.id,id", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["3", "1", "2"]


# Spec: "--desc" still applies to key paths
def test_desc_applies_to_key_paths(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, user_id=1), row(2, user_id=2)])
    result = run_cli("--output", "-", "--key", "user.id", "--desc", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: "Array indices ... If out of range or element is null/missing → key fragment is null"
def test_out_of_range_index_gives_a_null_fragment(run_cli, jsonl_file, nested_schema):
    data = jsonl_file(
        "a.jsonl",
        [
            row(1, items=[{"sku": "a", "qty": 1}, {"sku": "b", "qty": 2}]),
            row(2, items=[{"sku": "c", "qty": 3}]),
        ],
    )
    result = run_cli("--output", "-", "--key", "items.1.qty", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: "If out of range or element is null/missing → key fragment is null for that row"
def test_null_element_gives_a_null_fragment(run_cli, jsonl_file, nested_schema):
    data = jsonl_file(
        "a.jsonl", [row(1, items=[{"sku": "a", "qty": 1}]), row(2, items=[None])]
    )
    result = run_cli(
        "--output", "-", "--key", "items.0.qty", "--schema", nested_schema,
        "--on-type-error", "coerce-null", data,
    )
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: "Map lookups ... If absent → null for that fragment"
def test_absent_map_key_gives_a_null_fragment(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, attrs={"country": "US"}), row(2, attrs={"city": "x"})])
    result = run_cli("--output", "-", "--key", 'attrs["country"]', "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: "Sorting/partitioning comparisons follow typed ordering and null rules from earlier checkpoints"
def test_null_fragments_sort_last_when_descending(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, attrs={}), row(2, attrs={"country": "US"})])
    result = run_cli(
        "--output", "-", "--key", 'attrs["country"]', "--desc", "--schema", nested_schema, data
    )
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: "--partition-by <fieldPath>" — the first example partitions by a map value
def test_partition_by_a_map_lookup(run_cli, jsonl_file, nested_schema, tmp_path, tree):
    data = jsonl_file("a.jsonl", [row(1, attrs={"country": "US"}), row(2, attrs={"country": "DE"})])
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "id", "--partition-by", 'attrs["country"]',
        "--schema", nested_schema, data,
    )
    assert result.returncode == 0, result.stderr
    assert tree(out) == [
        'attrs%5B%22country%22%5D=DE/part-00000.csv',
        'attrs%5B%22country%22%5D=US/part-00000.csv',
    ]


# Spec: "--partition-by <fieldPath>" — a dotted path names a struct leaf
def test_partition_by_a_struct_leaf(run_cli, jsonl_file, nested_schema, tmp_path, tree):
    data = jsonl_file("a.jsonl", [row(1, user_id=7), row(2, user_id=7), row(3, user_id=8)])
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "id", "--partition-by", "user.id", "--schema", nested_schema, data
    )
    assert result.returncode == 0, result.stderr
    assert tree(out) == ["user.id=7/part-00000.csv", "user.id=8/part-00000.csv"]


# Spec: "If out of range or element is null/missing → key fragment is null" — partition side
def test_partition_by_a_missing_path_uses_the_null_segment(run_cli, jsonl_file, nested_schema, tmp_path, tree):
    data = jsonl_file("a.jsonl", [row(1, attrs={})])
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "id", "--partition-by", 'attrs["country"]',
        "--schema", nested_schema, data,
    )
    assert result.returncode == 0, result.stderr
    assert tree(out) == ["attrs%5B%22country%22%5D=_null/part-00000.csv"]


# Spec: 'Otherwise: ERR 3 key column "<path>" does not resolve to a primitive (exit 3)'
@pytest.mark.parametrize("path", ["user", "items", "attrs", "items.0"])
def test_non_primitive_key_path_is_error_3(run_cli, jsonl_file, nested_schema, path):
    data = jsonl_file("a.jsonl", [row(1)])
    result = run_cli("--output", "-", "--key", path, "--schema", nested_schema, data)
    assert result.returncode == 3, result.stderr
    assert f'key column "{path}" does not resolve to a primitive' in result.stderr
    assert "ERR 3" in result.stderr


# Spec: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
def test_non_primitive_partition_path_is_error_3(run_cli, jsonl_file, nested_schema, tmp_path):
    data = jsonl_file("a.jsonl", [row(1)])
    result = run_cli(
        "--output", tmp_path / "out", "--key", "id", "--partition-by", "user",
        "--schema", nested_schema, data,
    )
    assert result.returncode == 3, result.stderr
    assert "does not resolve to a primitive" in result.stderr


# Spec: "Array indices must be non-negative integers" (AMBIGUITIES T61)
@pytest.mark.parametrize("path", ["items.-1.qty", "items.x.qty"])
def test_invalid_array_index_is_error_3(run_cli, jsonl_file, nested_schema, path):
    data = jsonl_file("a.jsonl", [row(1)])
    result = run_cli("--output", "-", "--key", path, "--schema", nested_schema, data)
    assert result.returncode == 3, result.stderr


# Spec: "--key ... field paths" — a path whose head column does not exist is still error 3
def test_unknown_key_path_head_is_error_3(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1)])
    result = run_cli("--output", "-", "--key", "nope.id", "--schema", nested_schema, data)
    assert result.returncode == 3, result.stderr


# Spec: "Field paths traverse structs" — an undeclared struct field cannot resolve
def test_unknown_struct_field_is_error_3(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1)])
    result = run_cli("--output", "-", "--key", "user.nope", "--schema", nested_schema, data)
    assert result.returncode == 3, result.stderr


# Spec: "Each path must resolve to primitive value after casting" (AMBIGUITIES T58: json is dynamic)
def test_path_into_a_json_column_resolves_per_row(run_cli, jsonl_file, json_file):
    schema = json_file(
        "s.json", {"columns": [{"name": "id", "type": "int"}, {"name": "doc", "type": "json"}]}
    )
    data = jsonl_file("a.jsonl", [{"id": 1, "doc": {"k": 2}}, {"id": 2, "doc": {"k": 1}}])
    result = run_cli("--output", "-", "--key", "doc.k", "--schema", schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]


# Spec: 'Otherwise: ERR 3 key column "<path>" does not resolve to a primitive (exit 3)'
def test_json_column_path_landing_on_an_object_is_error_3(run_cli, jsonl_file, json_file):
    schema = json_file(
        "s.json", {"columns": [{"name": "id", "type": "int"}, {"name": "doc", "type": "json"}]}
    )
    data = jsonl_file("a.jsonl", [{"id": 1, "doc": {"k": {"deep": 1}}}])
    result = run_cli("--output", "-", "--key", "doc.k", "--schema", schema, data)
    assert result.returncode == 3, result.stderr


# Spec: "Paths must resolve to primitive types (string, int, float, bool, date, timestamp)"
def test_paths_resolve_to_typed_values_not_text(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, user_id=9), row(2, user_id=10)])
    result = run_cli("--output", "-", "--key", "user.id", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["1", "2"]


# Spec: "Field paths ... map lookups with bracketed string keys" (AMBIGUITIES T53)
def test_dotted_lookup_into_a_map(run_cli, jsonl_file, nested_schema):
    data = jsonl_file("a.jsonl", [row(1, attrs={"country": "US"}), row(2, attrs={"country": "DE"})])
    result = run_cli("--output", "-", "--key", "attrs.country", "--schema", nested_schema, data)
    assert [line[0] for line in result.rows[1:]] == ["2", "1"]
