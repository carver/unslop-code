"""Type aliases: the built-in table, `--type-alias-file`, and their resolution."""
from conftest import column, table

BUILT_INS = [("integer", "int"), ("long", "int"), ("double", "float"),
             ("number", "float"), ("boolean", "bool"), ("datetime", "timestamp"),
             ("timestamptz", "timestamp"), ("text", "string"), ("varchar", "string")]


# Phrase: "Built-in aliases (always present)"
# Context: each alias must cast exactly as the type it names.
def test_every_built_in_alias_casts_as_its_target(run, csv_file, json_file):
    for alias, target in BUILT_INS:
        value = {"int": "7", "float": "1.5", "bool": "true", "string": "x",
                 "timestamp": "2024-07-01T00:00:00Z"}[target]
        data = csv_file("a.csv", f"id,v\n1,{value}\n")
        schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                                  {"name": "v", "type": alias}]})
        direct = json_file("d.json", {"columns": [{"name": "id", "type": "int"},
                                                  {"name": "v", "type": target}]})
        aliased = run("--output", "-", "--key", "id", "--schema", schema, data)
        plain = run("--output", "-", "--key", "id", "--schema", direct, data)
        assert aliased.returncode == 0, (alias, aliased.stderr)
        assert aliased.stdout == plain.stdout, alias


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: the type name itself is lowercased before anything else happens.
def test_type_names_are_case_insensitive(run, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "INT"},
                                              {"name": "v", "type": "Integer"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", "7"]


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: "anywhere" includes the element and value types inside nested kinds.
def test_aliases_apply_inside_nested_types(run, jsonl_file, json_file):
    items = {"array": {"element": {"struct": {"fields": [
        {"name": "qty", "type": "LONG"}]}}}}
    data = jsonl_file("a.jsonl", [{"id": 1, "items": [{"qty": "4"}]}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "items", "type": items}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "items") == ['[{"qty":4}]']


# Phrase: "Optional alias file via --type-alias-file <ALIASES_JSON>"
# Context: the spec's own alias document.
def test_alias_file_entries_are_accepted_as_types(run, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,2.5\n")
    aliases = json_file("al.json", {"aliases": {"smallint": "int", "decimal": "float",
                                                "uuid": "string", "myts": "timestamp"}})
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "smallint"},
                                              {"name": "v", "type": "decimal"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--type-alias-file", aliases, data)
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", "2.5"]


# Phrase: "Aliases apply after lowercasing names"
# Context: an alias declared in mixed case still matches a mixed-case use.
def test_alias_file_names_are_lowercased(run, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    aliases = json_file("al.json", {"aliases": {"SmallInt": "INT"}})
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "v", "type": "SMALLINT"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--type-alias-file", aliases, data)
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", "7"]


# Phrase: "May refer to built-ins or other aliases (resolve transitively)"
# Context: a chain of user aliases ending at a built-in alias.
def test_aliases_resolve_transitively(run, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    aliases = json_file("al.json", {"aliases": {"a": "b", "b": "integer"}})
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "v", "type": "a"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--type-alias-file", aliases, data)
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", "7"]


# Phrase: "detect cycles -> error 2"
# Context: a cycle is reported even though everything else about the run is valid.
def test_alias_cycle_exits_2(run, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    aliases = json_file("al.json", {"aliases": {"a": "b", "b": "a"}})
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "v", "type": "a"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--type-alias-file", aliases, data)
    assert res.returncode == 2, res.stderr


# Phrase: "detect cycles -> error 2"
# Context: T51 - an alias naming itself is the shortest cycle there is.
def test_self_referential_alias_exits_2(run, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    aliases = json_file("al.json", {"aliases": {"loop": "loop"}})
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "v", "type": "loop"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--type-alias-file", aliases, data)
    assert res.returncode == 2, res.stderr


# Phrase: "list<T>->array<T>"
# Context: the alias rewrites the generic head, leaving the argument alone.
def test_list_alias_is_an_array(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "tags": [2, 1]}])
    by_alias = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                                {"name": "tags", "type": "list<int>"}]})
    by_kind = json_file("d.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "tags", "type": {"array": {"element": "int"}}}]})
    aliased = run("--output", "-", "--key", "id", "--schema", by_alias, data)
    plain = run("--output", "-", "--key", "id", "--schema", by_kind, data)
    assert aliased.returncode == 0, aliased.stderr
    assert aliased.stdout == plain.stdout == 'id,tags\n1,"[2,1]"\n'


# Phrase: "Special alias json: ... accept any JSON value (object/array/primitive)
#          and emit as JSON text"
# Context: one json column fed three shapes of value.
def test_json_type_accepts_any_json_value(run, jsonl_file, json_file):
    rows = [{"id": 1, "v": {"b": 1, "a": [1, "x"]}}, {"id": 2, "v": [1, 2]},
            {"id": 3, "v": "text"}, {"id": 4, "v": 5}]
    data = jsonl_file("a.jsonl", rows)
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "v", "type": "json"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == ['{"a":[1,"x"],"b":1}', "[1,2]", '"text"', "5"]


# Phrase: "json->struct"
# Context: T50 - the built-in alias makes a bare `struct` mean the same thing.
def test_bare_struct_behaves_like_json(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": [1]}}])
    as_json = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                               {"name": "v", "type": "json"}]})
    as_struct = json_file("d.json", {"columns": [{"name": "id", "type": "int"},
                                                 {"name": "v", "type": "struct"}]})
    assert (run("--output", "-", "--key", "id", "--schema", as_json, data).stdout
            == run("--output", "-", "--key", "id", "--schema", as_struct, data).stdout
            == 'id,v\n1,"{""k"":[1]}"\n')


# Phrase: "Optional alias file"
# Context: the flag is optional, so the built-ins work without one.
def test_alias_file_is_optional(run, csv_file, json_file):
    data = csv_file("a.csv", "id\n7\n")
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "integer"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert (res.returncode, res.stdout) == (0, "id\n7\n")
