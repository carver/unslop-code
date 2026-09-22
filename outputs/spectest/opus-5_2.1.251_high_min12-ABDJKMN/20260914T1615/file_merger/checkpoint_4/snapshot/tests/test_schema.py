"""Spec section: Schema Resolution & Column Order — explicit `--schema`."""

import json

from conftest import (body, col, header, run, run_ok, write, write_schema)


SCHEMA_DOC = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "ts", "type": "timestamp"},
        {"name": "amount", "type": "float"},
        {"name": "note", "type": "string"},
        {"name": "is_active", "type": "bool"},
    ]
}


# --- Spec: "If `--schema` is provided: JSON file with exact output schema and
#            column order" (the documented example document) ---
# Context: Schema Resolution & Column Order, item 1.
def test_documented_schema_document_shape(ws):
    s = write(ws / "s.json", json.dumps(SCHEMA_DOC))
    a = write(ws / "a.csv",
              "note,id,is_active,amount,ts\nhi,1,true,2.5,2024-07-01T12:00:00Z\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id", "ts", "amount", "note", "is_active"]
    assert body(res.stdout) == ["1,2024-07-01T12:00:00Z,2.5,hi,true"]


# --- Spec: "exact output schema and column order" ---
# Context: The schema's declared order wins over input header order and over
# lexicographic order.
def test_schema_column_order_is_not_lexicographic(ws):
    s = write_schema(ws / "s.json", [("z", "string"), ("a", "string"), ("m", "string")])
    a = write(ws / "a.csv", "a,m,z\n1,2,3\n")
    res = run_ok("--output", "-", "--key", "a", "--schema", s, a)
    assert header(res.stdout) == ["z", "a", "m"]
    assert body(res.stdout) == ["3,1,2"]


# --- Spec: "Valid types: string, int, float, bool, date, timestamp" ---
# Context: Schema Resolution item 1. All six are accepted in a schema document.
def test_all_valid_types_accepted(ws):
    s = write_schema(ws / "s.json", [("a", "string"), ("b", "int"), ("c", "float"),
                                     ("d", "bool"), ("e", "date"), ("f", "timestamp")])
    a = write(ws / "a.csv", "a,b,c,d,e,f\nx,1,2.0,0,2024-01-02,2024-01-02T03:04:05Z\n")
    res = run_ok("--output", "-", "--key", "a", "--schema", s, a)
    assert body(res.stdout) == ["x,1,2.0,false,2024-01-02,2024-01-02T03:04:05Z"]


# --- Spec: "Valid types: string, int, float, bool, date, timestamp" ---
# Context: An unknown type in the schema document is invalid.
def test_unknown_schema_type_is_error(ws):
    s = write(ws / "s.json", json.dumps({"columns": [{"name": "a", "type": "decimal"}]}))
    a = write(ws / "a.csv", "a\n1\n")
    res = run("--output", "-", "--key", "a", "--schema", s, a)
    assert not res.ok
    assert res.stderr.strip() != ""


# --- Spec: "Extra input columns not in schema are ignored" ---
# Context: Schema Resolution item 1.
def test_extra_input_columns_ignored(ws):
    s = write_schema(ws / "s.json", [("id", "int")])
    a = write(ws / "a.csv", "id,junk,more\n1,x,y\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id"]
    assert body(res.stdout) == ["1"]


# --- Spec: "Missing input columns filled with null literal" ---
# Context: Schema Resolution item 1.
def test_schema_column_absent_from_input_is_null(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("ghost", "string")])
    a = write(ws / "a.csv", "id\n1\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert body(res.stdout) == ["1,NA"]


# --- Spec: "Cast every input cell into target type" ---
# Context: Schema Resolution item 1 — the schema type wins over what the text
# looks like, e.g. an int-looking cell in a string column stays text.
def test_schema_type_forces_cast_over_appearance(ws):
    s = write_schema(ws / "s.json", [("v", "string")])
    a = write(ws / "a.csv", "v\n10\n9\n")
    res = run_ok("--output", "-", "--key", "v", "--schema", s, a)
    assert col(res.stdout, "v") == ["10", "9"]


# --- Spec: "If `--schema` is provided" the schema applies to every input file ---
# Context: Schema Resolution item 1, with heterogeneous input headers.
def test_schema_applies_across_heterogeneous_inputs(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "float")])
    a = write(ws / "a.csv", "id,v,extra\n2,1.5,zzz\n")
    b = write(ws / "b.csv", "v,id\n0.5,1\n")
    c = write(ws / "c.csv", "id\n3\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a, b, c)
    assert body(res.stdout) == ["1,0.5", "2,1.5", "3,"]


# --- Spec: "If a key column is not present in resolved schema, that is an error" ---
# Context: Casting & Validation (second block), explicit schema case.
def test_key_not_in_explicit_schema_is_error(ws):
    s = write_schema(ws / "s.json", [("id", "int")])
    a = write(ws / "a.csv", "id,other\n1,x\n")
    res = run("--output", "-", "--key", "other", "--schema", s, a)
    assert not res.ok
    assert res.stderr.strip() != ""


# --- Spec: "If a key column is not present in resolved schema, that is an error" ---
# Context: Same rule for an inferred schema (column in no input header).
def test_key_not_in_inferred_schema_is_error(ws):
    a = write(ws / "a.csv", "id,other\n1,x\n")
    res = run("--output", "-", "--key", "nope", a)
    assert not res.ok
    assert res.stderr.strip() != ""


# --- Spec: "If a key column is not present in resolved schema, that is an error" ---
# Context: Any one member of a composite key triggers it.
def test_one_bad_composite_key_member_is_error(ws):
    a = write(ws / "a.csv", "id,other\n1,x\n")
    res = run("--output", "-", "--key", "id,nope", a)
    assert not res.ok


# --- Spec: a key column may be a schema column absent from every input ---
# Context: Casting & Validation; presence in the *resolved schema* is the test.
# See AMBIGUITIES T20.
def test_key_present_in_schema_but_absent_from_inputs_is_ok(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("ghost", "int")])
    a = write(ws / "a.csv", "id\n2\n1\n")
    res = run_ok("--output", "-", "--key", "ghost", "--schema", s, a)
    assert col(res.stdout, "id") == ["2", "1"]


# --- Spec: "--infer {strict,loose}" has no effect when --schema is given ---
# Context: Schema Resolution items 1 and 2; see AMBIGUITIES T21.
def test_infer_flag_ignored_with_explicit_schema(ws):
    s = write_schema(ws / "s.json", [("v", "string")])
    a = write(ws / "a.csv", "v\n1\n")
    strict = run_ok("--output", "-", "--key", "v", "--schema", s, "--infer", "strict", a)
    loose = run_ok("--output", "-", "--key", "v", "--schema", s, "--infer", "loose", a)
    assert strict.stdout == loose.stdout == "v\n1\n"


# --- Spec: "[--schema <SCHEMA_JSON>]" ---
# Context: Usage; the argument may also be given as literal JSON text.
# See AMBIGUITIES T11.
def test_schema_accepts_inline_json(ws):
    a = write(ws / "a.csv", "id,name\n1,x\n")
    res = run_ok("--output", "-", "--key", "id",
                 "--schema", json.dumps({"columns": [{"name": "id", "type": "int"}]}), a)
    assert res.stdout == "id\n1\n"


# --- Spec: "--schema <SCHEMA_JSON>" pointing at unreadable/invalid JSON ---
# Context: Schema Resolution item 1.
def test_malformed_schema_file_is_error(ws):
    s = write(ws / "s.json", "{not json")
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert not res.ok


# --- Spec: "Type priority: timestamp > date > bool > int > float > string" ---
# Context: Schema Resolution item 1; the listed names are exactly the valid types.
def test_priority_list_names_are_the_valid_type_names(ws):
    for t in ("timestamp", "date", "bool", "int", "float", "string"):
        s = write_schema(ws / f"s_{t}.json", [("k", "string"), ("v", t)])
        a = write(ws / "a.csv", "k,v\nx,\n")
        res = run_ok("--output", "-", "--key", "k", "--schema", s, a)
        assert res.stdout == "k,v\nx,\n", t


# --- Spec: "Missing values emitted as the null literal (default empty string)" ---
# Context: Output; a row whose only field is null is written as a quoted empty
# field, since a bare empty line would not be a distinguishable CSV record.
# See AMBIGUITIES T25.
def test_single_column_null_row_is_quoted_empty_field(ws):
    s = write_schema(ws / "s.json", [("v", "int")])
    a = write(ws / "a.csv", "v\n\n")
    res = run_ok("--output", "-", "--key", "v", "--schema", s, a)
    assert res.stdout == 'v\n""\n'
