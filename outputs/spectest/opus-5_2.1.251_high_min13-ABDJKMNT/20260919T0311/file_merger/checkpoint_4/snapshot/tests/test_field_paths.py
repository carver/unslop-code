"""`--key` and `--partition-by` field paths into nested values."""
from conftest import column, tree

USER = {"struct": {"fields": [{"name": "id", "type": "int"},
                              {"name": "name", "type": "string"}]}}
ITEMS = {"array": {"element": {"struct": {"fields": [{"name": "sku", "type": "string"},
                                                     {"name": "qty", "type": "int"}]}}}}
ATTRS = {"map": {"key": "string", "value": "string"}}


def _schema(json_file):
    return json_file("s.json", {"columns": [
        {"name": "row", "type": "int"},
        {"name": "user", "type": USER},
        {"name": "items", "type": ITEMS},
        {"name": "attrs", "type": ATTRS}]})


def _rows(jsonl_file, *users):
    return jsonl_file("a.jsonl", [
        {"row": index, "user": {"id": user, "name": "n"},
         "items": [{"sku": "s", "qty": user}], "attrs": {"country": f"c{user}"}}
        for index, user in enumerate(users)])


# Phrase: "--key and --partition-by now accept field paths using dot notation
#          (e.g., user.id)"
# Context: the sort order is the order of the nested leaf, not of the column.
def test_key_on_a_struct_field(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 3, 1, 2)
    res = run("--output", "-", "--key", "user.id", "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["1", "2", "0"]


# Phrase: "Field paths ... use numeric indices into arrays (e.g. items.0.sku)"
# Context: the first element's field decides the row order.
def test_key_on_an_array_element_field(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 3, 1, 2)
    res = run("--output", "-", "--key", "items.0.qty", "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["1", "2", "0"]


# Phrase: 'map lookups with bracketed string keys ... attrs["country"]'
# Context: the bracketed key reads the value by exact key.
def test_key_on_a_map_lookup(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 3, 1, 2)
    res = run("--output", "-", "--key", 'attrs["country"]', "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["1", "2", "0"]


# Phrase: "If out of range or element is null/missing -> key fragment is null for
#          that row"
# Context: nulls sort first, as they do for a flat key column.
def test_array_index_out_of_range_is_null(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [
        {"row": 0, "items": [{"sku": "a", "qty": 1}, {"sku": "b", "qty": 2}]},
        {"row": 1, "items": [{"sku": "a", "qty": 1}]}])
    res = run("--output", "-", "--key", "items.1.qty", "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["1", "0"]


# Phrase: "Map lookups with ["key"] read value by exact key. If absent -> null for
#          that fragment"
# Context: a key that no row spells exactly leaves every fragment null, so the
# sort falls back to input order.
def test_absent_map_key_is_null(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"row": 0, "attrs": {"COUNTRY": "x"}},
                                  {"row": 1, "attrs": {"country": "y"}}])
    res = run("--output", "-", "--key", 'attrs["country"]', "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["0", "1"]


# Phrase: "Array indices must be non-negative integers"
# Context: T57 - a negative index cannot address an element, so the path is bad.
def test_negative_array_index_exits_3(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 1)
    res = run("--output", "-", "--key", "items.-1.qty", "--schema", _schema(json_file), data)
    assert res.returncode == 3, res.stderr


# Phrase: 'Otherwise: ERR 3 key column "<path>" does not resolve to a primitive
#          (exit 3)'
# Context: the column itself is a struct.
def test_key_on_a_nested_column_exits_3(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 1)
    res = run("--output", "-", "--key", "user", "--schema", _schema(json_file), data)
    assert res.returncode == 3
    assert 'key column "user" does not resolve to a primitive' in res.stderr


# Phrase: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
# Context: a path that stops on an array rather than a leaf.
def test_key_on_an_array_path_exits_3(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 1)
    res = run("--output", "-", "--key", "items.0", "--schema", _schema(json_file), data)
    assert res.returncode == 3, res.stderr


# Phrase: "Referencing non-primitive (struct/array/map) in keys/partitions is error 3"
# Context: the same rule for --partition-by.
def test_partition_on_a_nested_column_exits_3(run, jsonl_file, json_file, tmp_path):
    data = _rows(jsonl_file, 1)
    res = run("--output", "out", "--key", "row", "--partition-by", "attrs",
              "--schema", _schema(json_file), data)
    assert res.returncode == 3, res.stderr


# Phrase: "Paths must resolve to primitive types"
# Context: a struct field the schema never declared cannot resolve.
def test_unknown_struct_field_exits_3(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 1)
    res = run("--output", "-", "--key", "user.missing", "--schema", _schema(json_file), data)
    assert res.returncode == 3, res.stderr


# Phrase: "--partition-by <fieldPath>[,<fieldPath>...]"
# Context: T58 - the partition directory is named by the path as written.
def test_partition_by_a_map_lookup(run, jsonl_file, json_file, tmp_path):
    data = _rows(jsonl_file, 1, 2)
    res = run("--output", "out", "--key", "row", "--partition-by", 'attrs["country"]',
              "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == [
        'attrs%5B%22country%22%5D=c1/part-00000.csv',
        'attrs%5B%22country%22%5D=c2/part-00000.csv']


# Phrase: "--partition-by <fieldPath>"
# Context: a dotted path keeps its dots in the directory name.
def test_partition_by_a_dotted_path(run, jsonl_file, json_file, tmp_path):
    data = _rows(jsonl_file, 1, 2)
    res = run("--output", "out", "--key", "row", "--partition-by", "user.id",
              "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["user.id=1/part-00000.csv", "user.id=2/part-00000.csv"]


# Phrase: "--key <fieldPath>[,<fieldPath>...]"
# Context: T59 - a comma inside a bracketed key does not split the list.
def test_bracketed_key_may_contain_a_comma(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"row": 0, "attrs": {"a,b": "z"}},
                                  {"row": 1, "attrs": {"a,b": "y"}}])
    res = run("--output", "-", "--key", 'attrs["a,b"]', "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["1", "0"]


# Phrase: "--key <fieldPath>[,<fieldPath>...]"
# Context: a composite key mixing a nested leaf and a flat column.
def test_composite_key_of_nested_and_flat_paths(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"row": 0, "user": {"id": 1, "name": "b"}},
                                  {"row": 1, "user": {"id": 1, "name": "a"}},
                                  {"row": 2, "user": {"id": 0, "name": "z"}}])
    res = run("--output", "-", "--key", "user.id,user.name", "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["2", "1", "0"]


# Phrase: "Sorting/partitioning comparisons follow typed ordering and null rules
#          from earlier checkpoints"
# Context: an int leaf orders numerically, and --desc flips it.
def test_nested_key_ordering_is_typed_and_reversible(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 10, 9)
    ascending = run("--output", "-", "--key", "user.id", "--schema", _schema(json_file), data)
    descending = run("--output", "-", "--key", "user.id", "--desc",
                     "--schema", _schema(json_file), data)
    assert column(ascending.stdout, "row") == ["1", "0"]
    assert column(descending.stdout, "row") == ["0", "1"]


# Phrase: "Each path must resolve to primitive value after casting"
# Context: T56 - a json column promises nothing about its shape, so paths into it
# cannot be accepted.
def test_path_into_a_json_column_exits_3(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"row": 0, "blob": {"id": 1}}])
    schema = json_file("s.json", {"columns": [{"name": "row", "type": "int"},
                                              {"name": "blob", "type": "json"}]})
    res = run("--output", "-", "--key", "blob.id", "--schema", schema, data)
    assert res.returncode == 3, res.stderr


# Phrase: "--key <fieldPath>"
# Context: a path whose first segment is not a column at all is still exit 3.
def test_unknown_leading_column_exits_3(run, jsonl_file, json_file):
    data = _rows(jsonl_file, 1)
    res = run("--output", "-", "--key", "nope.id", "--schema", _schema(json_file), data)
    assert res.returncode == 3, res.stderr


# Phrase: "If out of range or element is null/missing -> key fragment is null"
# Context: a null struct makes every leaf below it null.
def test_null_parent_makes_the_fragment_null(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"row": 0, "user": {"id": 5, "name": "n"}},
                                  {"row": 1, "user": None}])
    res = run("--output", "-", "--key", "user.id", "--schema", _schema(json_file), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "row") == ["1", "0"]
