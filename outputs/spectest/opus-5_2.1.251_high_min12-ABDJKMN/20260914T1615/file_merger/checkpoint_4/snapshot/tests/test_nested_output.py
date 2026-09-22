"""Spec section: Nested Types Support — "Normalization & Output Encoding"."""

import json

from conftest import (array_t, body, col, header, map_t, read_text, run,
                      run_ok, struct_t, write, write_jsonl,
                      write_nested_schema)


# --- Spec: "If entire column value is null -> emit CSV null literal" ---
# Context: Normalization & Output Encoding.
def test_null_nested_column_uses_the_csv_null_literal(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": None}, {"id": 2}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NULL", a)
    assert body(res.stdout) == ["1,NULL", "2,NULL"]


# --- Spec: "If entire column value is null -> emit CSV null literal" ---
# Context: Normalization & Output Encoding; a struct of nulls is NOT null (T81).
def test_struct_of_nulls_is_still_json(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NULL", a)
    assert col(res.stdout, "u") == ['{"a":null}']


# --- Spec: "Minified (no spaces)" ---
# Context: Normalization & Output Encoding.
def test_output_json_is_minified(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"), ("b", array_t("int"))))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1, "b": [1, 2]}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    cell = col(res.stdout, "u")[0]
    assert cell == '{"a":1,"b":[1,2]}'
    assert " " not in cell


# --- Spec: "Struct fields in schema-declared order" ---
# Context: Normalization & Output Encoding; input order is irrelevant.
def test_struct_field_order_is_the_schema_order(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("c", "int"), ("b", "int"), ("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1, "b": 2, "c": 3}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"c":3,"b":2,"a":1}']


# --- Spec: "Map keys sorted lexicographically" ---
# Context: Normalization & Output Encoding.
def test_map_keys_are_sorted_lexicographically(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("m", map_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "m": {"b": 1, "A": 2, "a": 3, "0": 4}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "m") == ['{"0":4,"A":2,"a":3,"b":1}']


# --- Spec: "Arrays preserve original element order after casting" ---
# Context: Normalization & Output Encoding.
def test_arrays_preserve_element_order(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("string"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": ["z", "a", "m"]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "xs") == ['["z","a","m"]']


# --- Spec: "Timestamps inside nested values normalized to UTC `Z`;
#           `date` stays `YYYY-MM-DD`" ---
# Context: Normalization & Output Encoding.
def test_temporal_normalization_inside_nested(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("u", struct_t(("t", "timestamp"), ("d", "date")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {
        "t": "2024-03-04T10:00:00-05:00", "d": "2024-03-04"}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == [
        '{"t":"2024-03-04T15:00:00Z","d":"2024-03-04"}']


# --- Spec: "All struct fields included (even when null) with explicit `null`
#           values" ---
# Context: Normalization & Output Encoding; nested struct inside an array.
def test_all_struct_fields_present_in_every_element(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("items", array_t(struct_t(("sku", "string"), ("qty", "int"))))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "items": [{"sku": "a"}, {"qty": 2}]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "items") == [
        '[{"sku":"a","qty":null},{"sku":null,"qty":2}]']


# --- Spec: "UTF-8, RFC 8259 JSON escaping" ---
# Context: Normalization & Output Encoding; non-ASCII stays literal (T86).
def test_non_ascii_is_emitted_as_utf8(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("n", "string")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"n": "café ☕"}}])
    out = ws / "o.csv"
    run_ok("--output", str(out), "--key", "id", "--schema", s, a)
    text = read_text(out)
    assert "café ☕" in text
    assert "\\u" not in text


# --- Spec: "RFC 8259 JSON escaping" ---
# Context: Normalization & Output Encoding; quotes, backslashes and controls.
def test_required_json_escapes(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("n", "string")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"n": 'a"b\\c\nd\te'}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert json.loads(col(res.stdout, "u")[0]) == {"n": 'a"b\\c\nd\te'}
    assert col(res.stdout, "u") == ['{"n":"a\\"b\\\\c\\nd\\te"}']


# --- Spec: "This JSON is the CSV cell content for nested columns" ---
# Context: Normalization & Output Encoding; ordinary CSV quoting applies (T85).
def test_nested_cell_is_csv_quoted(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert body(res.stdout) == ['1,"{""a"":1}"']


# --- Spec: "Output remains CSV with nested columns as canonical JSON" ---
# Context: Nested Types Support (intro); the header is unchanged.
def test_header_lists_nested_columns_like_any_other(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"))), ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}, "xs": []}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id", "u", "xs"]
    assert col(res.stdout, "xs") == ["[]"]


# --- Spec: "Map keys sorted lexicographically" ---
# Context: Normalization & Output Encoding; json values canonicalize too (T66).
def test_json_value_object_keys_are_canonicalized(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"b": 1, "a": {"d": 1,
                                                                   "c": 2}}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ['{"a":{"c":2,"d":1},"b":1}']


# --- Spec: "Minified (no spaces)" ---
# Context: Normalization & Output Encoding; a json cell is re-minified.
def test_json_cell_from_csv_is_reminified(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    x = write(ws / "x.csv", 'id,v\n1,"[1,  2,   3]"\n')
    res = run_ok("--output", "-", "--key", "id", "--schema", s, x)
    assert col(res.stdout, "v") == ["[1,2,3]"]
