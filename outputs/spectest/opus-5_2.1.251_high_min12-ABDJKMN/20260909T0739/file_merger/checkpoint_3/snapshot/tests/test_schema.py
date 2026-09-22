"""`Schema Resolution & Column Order`, branch 1: explicit `--schema`."""
import json

from conftest import merge, run, write, write_schema


# --- Spec: "If `--schema` is provided: JSON file with exact output schema and
#            column order" --------------------------------------------------
def test_schema_file_defines_exact_columns_and_order(tmp_path):
    schema = write(
        tmp_path,
        "schema.json",
        json.dumps(
            {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "ts", "type": "timestamp"},
                    {"name": "amount", "type": "float"},
                    {"name": "note", "type": "string"},
                    {"name": "is_active", "type": "bool"},
                ]
            }
        ),
    )
    files = {
        "a.csv": "note,is_active,amount,ts,id\nhi,1,2.50,2024-07-01T12:00:00,7\n"
    }
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    rows = r.rows()
    assert rows[0] == ["id", "ts", "amount", "note", "is_active"]
    assert rows[1] == ["7", "2024-07-01T12:00:00Z", "2.5", "hi", "true"]


# --- Spec: "Valid types: string, int, float, bool, date, timestamp" ---------
def test_all_valid_types_accepted(tmp_path):
    cols = [
        ("s", "string"),
        ("i", "int"),
        ("f", "float"),
        ("b", "bool"),
        ("d", "date"),
        ("t", "timestamp"),
    ]
    schema = write_schema(tmp_path, "s.json", cols)
    files = {"a.csv": "s,i,f,b,d,t\nx,1,1.5,true,2024-01-02,2024-01-02T03:04:05Z\n"}
    r = merge(tmp_path, files, "--key", "i", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [
        ["s", "i", "f", "b", "d", "t"],
        ["x", "1", "1.5", "true", "2024-01-02", "2024-01-02T03:04:05Z"],
    ]


# --- Spec: "Valid types: ..." - anything else is not a valid type -----------
def test_invalid_schema_type_is_error(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "integer")])
    files = {"a.csv": "id\n1\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: schema must be readable/parseable --------------------------------
def test_unreadable_schema_is_error(tmp_path):
    files = {"a.csv": "id\n1\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(tmp_path / "no.json"))
    assert not r.ok
    assert r.stderr.strip()


def test_malformed_schema_json_is_error(tmp_path):
    schema = write(tmp_path, "s.json", "{not json")
    files = {"a.csv": "id\n1\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: "Cast every input cell into target type (rules below)" -----------
def test_every_cell_is_cast(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("i", "int"), ("f", "float")])
    files = {"a.csv": "i,f\n007,3\n+2,1.50\n"}
    r = merge(tmp_path, files, "--key", "i", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1:] == [["2", "1.5"], ["7", "3.0"]]


# --- Spec: "Extra input columns not in schema are ignored" ------------------
def test_extra_input_columns_ignored(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int")])
    files = {"a.csv": "id,junk,more\n1,x,y\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [["id"], ["1"]]


# --- Spec: "Missing input columns filled with null literal" -----------------
def test_missing_input_columns_filled_with_null_literal(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("absent", "string")])
    files = {"a.csv": "id\n1\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [["id", "absent"], ["1", ""]]

    r2 = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--csv-null-literal", "NULL",
    )
    assert r2.ok, r2
    assert r2.rows()[1] == ["1", "NULL"]


# --- Spec: the schema applies uniformly across all inputs -------------------
def test_schema_applies_to_every_input(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    files = {
        "a.csv": "id,v,extra\n2,two,zzz\n",
        "b.csv": "v,id\none,1\n",
        "c.csv": "id\n3\n",
    }
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [
        ["id", "v"],
        ["1", "one"],
        ["2", "two"],
        ["3", ""],
    ]


# --- Spec ambiguity T20: `--infer` is ignored when `--schema` is given -------
def test_infer_ignored_when_schema_given(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "string")])
    files = {"a.csv": "id\n10\n9\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema), "--infer", "loose")
    assert r.ok, r
    # declared `string` wins over any inference => lexicographic
    assert [x[0] for x in r.rows()[1:]] == ["10", "9"]
