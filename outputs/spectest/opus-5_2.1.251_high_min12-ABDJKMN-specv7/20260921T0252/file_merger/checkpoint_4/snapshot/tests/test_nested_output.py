"""Spec section: Normalization & Output Encoding (checkpoint 4)."""
import json

from conftest import (array_t, cell, col, map_t, read_text, run_tool,
                      struct_t, write_csv, write_json, write_jsonl,
                      write_nested_schema)


# --------------------------------------------------------------------------
# Phrase: "If entire column value is null -> emit CSV null literal"
# Context: Normalization & Output Encoding.
# --------------------------------------------------------------------------
def test_null_nested_column_uses_the_null_literal(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": None}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "\\N", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "u") == ["\\N"]


# Phrase: "All struct fields included (even when null) with explicit null
#          values"
def test_all_struct_fields_present_even_when_null(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("u", struct_t(("a", "int"), ("b", "string"), ("c", "bool"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"b": "x"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":null,"b":"x","c":null}'


# Phrase: "If entire column value is null" (T66)
# Context: a struct whose every field is null is still serialised.
def test_all_null_struct_is_not_a_null_cell(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":null}'


def test_empty_array_and_map_are_not_null_cells(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("t", array_t("int")), ("m", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [], "m": {}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    rows = res.rows()
    assert cell(rows, "t") == "[]"
    assert cell(rows, "m") == "{}"


# --------------------------------------------------------------------------
# Phrase: "Minified (no spaces), UTF-8, RFC 8259 JSON escaping"
# Context: Normalization & Output Encoding.
# --------------------------------------------------------------------------
def test_output_json_is_minified(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"), ("b", "int"))))
    src = write_csv(tmp_path / "a.csv",
                    ["id,u", '1,"{ ""a"" : 1 , ""b"" : 2 }"'])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":1,"b":2}'


def test_non_ascii_is_emitted_as_utf8_text(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "string"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": "café"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":"café"}'


def test_json_escaping_of_control_characters(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "string"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "u": {"a": "q\"\\\n\t"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":"q\\"\\\\\\n\\t"}'


def test_nested_json_cell_is_csv_quoted(tmp_path):
    # The JSON contains commas and quotes, so the CSV writer must quote it.
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"), ("b", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": 1, "b": 2}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == 'id,u\n1,"{""a"":1,""b"":2}"\n'


# --------------------------------------------------------------------------
# Phrase: "Struct fields in schema-declared order"
# --------------------------------------------------------------------------
def test_struct_fields_follow_declared_order(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("u", struct_t(("z", "int"), ("a", "int"), ("m", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "u": {"a": 1, "m": 2, "z": 3}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"z":3,"a":1,"m":2}'


# Phrase: "Map keys sorted lexicographically"
def test_map_keys_are_sorted(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "m": {"b": 1, "A": 2, "a": 3, "0": 4}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"0":4,"A":2,"a":3,"b":1}'


# Phrase: "Arrays preserve original element order after casting"
def test_array_order_is_preserved(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("string")))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "t": ["c", "a", "b"]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == '["c","a","b"]'


# Phrase: "Timestamps inside nested values normalized to UTC Z; date stays
#          YYYY-MM-DD"
def test_nested_timestamp_and_date_rendering(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("t", array_t("timestamp")), ("d", array_t("date")))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1,
         "t": ["2024-01-02T03:04:05-05:00", "2024-01-02 03:04:05"],
         "d": ["2024-01-02"]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    rows = res.rows()
    assert cell(rows, "t") == '["2024-01-02T08:04:05Z","2024-01-02T03:04:05Z"]'
    assert cell(rows, "d") == '["2024-01-02"]'


# Phrase: "serialize nested value as canonical JSON"
# Context: the same logical value serialises identically from any source.
def test_same_value_from_csv_and_jsonl_serialises_identically(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("m", map_t("int")))
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"b": 1, "a": 2}}])
    b = write_csv(tmp_path / "b.csv",
                  ["id,m", '2,"{ ""a"": 2, ""b"": 1 }"'])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a, b)
    assert res.returncode == 0, res.stderr
    values = col(res.rows(), "m")
    assert values == ['{"a":2,"b":1}', '{"a":2,"b":1}']


# Phrase: "This JSON is the CSV cell content for nested columns"
# Context: booleans and floats inside JSON keep JSON spelling, not CSV.
def test_json_scalar_spelling_inside_nested(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("u", struct_t(("b", "bool"), ("f", "float"), ("i", "int"),
                       ("s", "string"))))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1, "u": {"b": False, "f": 2.5, "i": 7, "s": "7"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"b":false,"f":2.5,"i":7,"s":"7"}'


# Phrase: "Output remains CSV with nested columns as canonical JSON"
# Context: nested output also works when written to a file.
def test_nested_output_to_a_file(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1, 2]}])
    out = tmp_path / "out.csv"
    res = run_tool("--output", str(out), "--key", "id", "--schema", schema,
                   src)
    assert res.returncode == 0, res.stderr
    assert read_text(out) == 'id,t\n1,"[1,2]"\n'
