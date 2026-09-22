"""`Source Dialect Assumptions`: JSON Lines."""
from conftest import merge_paths, write, write_jsonl, write_schema


# --- Spec: "JSONL: one UTF-8 JSON object per line" ------------------------
def test_one_object_per_line(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl",
                    [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "a"], ["2", "b"]]


def test_utf8_values_survive(tmp_path):
    a = write(tmp_path, "a.jsonl", '{"id": 1, "name": "é中"}\n')
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["1", "é中"]


# --- Spec: "JSONL: ... objects must be flat (no arrays/objects as values)"
#     with "nested structures trigger error 6" ------------------------------
def test_array_value_is_error_6(tmp_path):
    a = write(tmp_path, "a.jsonl", '{"id": 1, "tags": ["x", "y"]}\n')
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r
    assert r.stderr.strip()


def test_object_value_is_error_6(tmp_path):
    a = write(tmp_path, "a.jsonl", '{"id": 1, "meta": {"k": 1}}\n')
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r


def test_empty_array_value_is_still_error_6(tmp_path):
    a = write(tmp_path, "a.jsonl", '{"id": 1, "tags": []}\n')
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r


def test_top_level_array_line_is_error_6(tmp_path):
    a = write(tmp_path, "a.jsonl", '[1, 2, 3]\n')
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 6, r


# --- Spec: "JSONL: ... `null` permitted" ----------------------------------
def test_null_value_is_permitted_and_renders_as_null_literal(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "name": None}])
    r = merge_paths([a], "--key", "id", "--csv-null-literal", "NULL")
    assert r.ok, r
    assert r.rows()[1] == ["1", "NULL"]


# --- Spec: "JSONL: ... keys case-sensitive" -------------------------------
def test_keys_are_case_sensitive(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl", [{"ID": 1, "id": 2}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[0] == ["ID", "id"]
    assert r.rows()[1] == ["1", "2"]


# --- Spec: "JSONL: ... blank/whitespace lines ignored" --------------------
def test_blank_and_whitespace_lines_ignored(tmp_path):
    a = write(tmp_path, "a.jsonl",
              '\n{"id": 1}\n   \n\t\n{"id": 2}\n\n')
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id"], ["1"], ["2"]]


# --- Spec: "Column set: union of all encountered field names" - JSONL rows
#            may carry different key sets ---------------------------------
def test_ragged_objects_union_their_keys(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl",
                    [{"id": 1, "x": "p"}, {"id": 2, "y": "q"}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "x", "y"], ["1", "p", ""], ["2", "", "q"]]


# --- Spec: "Extra input columns ignored; missing columns filled with null
#            literal" (with an explicit schema) ---------------------------
def test_schema_selects_and_orders_jsonl_fields(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("z", "string")])
    a = write_jsonl(tmp_path, "a.jsonl", [{"x": 9, "id": 1}])
    r = merge_paths([a], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [["id", "z"], ["1", ""]]


# --- Spec: "one UTF-8 JSON object per line" - a broken line is malformed
#            input (error 5) -----------------------------------------------
def test_malformed_json_line_is_error_5(tmp_path):
    a = write(tmp_path, "a.jsonl", '{"id": 1}\n{"id": \n')
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 5, r
