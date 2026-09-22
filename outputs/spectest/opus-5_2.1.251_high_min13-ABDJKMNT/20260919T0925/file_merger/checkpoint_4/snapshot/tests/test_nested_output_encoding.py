"""Canonical JSON encoding of a nested column's cell."""

MAP_OF_STRING = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "v", "type": {"map": {"key": "string", "value": "string"}}},
    ]
}


def struct_schema(*fields):
    return {
        "columns": [
            {"name": "id", "type": "int"},
            {"name": "v", "type": {"struct": {"fields": list(fields)}}},
        ]
    }


# Spec: "If entire column value is null → emit CSV null literal"
def test_null_column_value_uses_the_null_literal(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": None}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", ""]


# Spec: "If entire column value is null → emit CSV null literal" — honouring --csv-null-literal
def test_null_column_value_honours_the_configured_literal(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": None}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "NULL", data
    )
    assert result.rows[1] == ["1", "NULL"]


# Spec: "CSV null literal applies only when entire cell is null"
def test_a_struct_of_nulls_is_not_a_null_cell(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {}}])
    schema = json_file("s.json", struct_schema({"name": "a", "type": "int"}))
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "NULL", data
    )
    assert result.rows[1] == ["1", '{"a":null}']


# Spec: "All struct fields included (even when null) with explicit null values"
def test_missing_struct_fields_are_emitted_as_null(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"b": 2}}])
    schema = json_file(
        "s.json",
        struct_schema(
            {"name": "a", "type": "int"}, {"name": "b", "type": "int"}, {"name": "c", "type": "int"}
        ),
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"a":null,"b":2,"c":null}'


# Spec: "Struct fields in schema-declared order" (AMBIGUITIES T54: undeclared keys dropped)
def test_undeclared_struct_keys_are_dropped(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1, "zzz": 9}}])
    schema = json_file("s.json", struct_schema({"name": "a", "type": "int"}))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"a":1}'


# Spec: "Map keys sorted lexicographically"
def test_map_keys_are_sorted(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"b": "2", "A": "1", "a": "3", "": "4"}}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"":"4","A":"1","a":"3","b":"2"}'


# Spec: "Arrays preserve original element order after casting"
def test_array_order_is_preserved(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [3, 1, 2]}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"array": {"element": "int"}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == "[3,1,2]"


# Spec: "Minified (no spaces)"
def test_output_json_is_minified(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": "a b"}}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"k":"a b"}'


# Spec: "RFC 8259 JSON escaping"
def test_special_characters_are_json_escaped(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": 'q"\\\n\t'}}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"k":"q\\"\\\\\\n\\t"}'


# Spec: "Minified (no spaces), UTF-8" (AMBIGUITIES T48: raw UTF-8, not \uXXXX)
def test_non_ascii_text_stays_utf8(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": "café"}}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"k":"café"}'


# Spec: "Timestamps inside nested values normalized to UTC Z; date stays YYYY-MM-DD"
def test_temporal_rendering_inside_nested(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"d": "2024-03-04", "t": "2024-03-04T23:00:00-05:00"}}])
    schema = json_file(
        "s.json",
        struct_schema({"name": "d", "type": "date"}, {"name": "t", "type": "timestamp"}),
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"d":"2024-03-04","t":"2024-03-05T04:00:00Z"}'


# Spec: "This JSON is the CSV cell content for nested columns" — CSV quoting still applies
def test_the_json_cell_is_csv_quoted(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": "x"}}])
    schema = json_file("s.json", MAP_OF_STRING)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.stdout == 'id,v\n1,"{""k"":""x""}"\n'


# Spec: "Struct fields in schema-declared order" — nested structs order independently
def test_ordering_rules_compose_at_every_depth(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [{"m": {"z": 1, "a": 2}, "n": 3}]}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {
                    "name": "v",
                    "type": {
                        "array": {
                            "element": {
                                "struct": {
                                    "fields": [
                                        {"name": "m", "type": {"map": {"key": "string", "value": "int"}}},
                                        {"name": "n", "type": "int"},
                                    ]
                                }
                            }
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '[{"m":{"a":2,"z":1},"n":3}]'
