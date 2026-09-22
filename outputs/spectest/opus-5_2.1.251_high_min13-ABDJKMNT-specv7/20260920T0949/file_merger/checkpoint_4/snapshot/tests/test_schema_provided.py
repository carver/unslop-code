"""Schema resolution when --schema is supplied."""

import json

from conftest import rows_of


# Spec: "If `--schema` is provided: JSON file with exact output schema and column order"
def test_schema_file_defines_columns_and_their_order(make_csv, make_schema, run):
    make_csv("a.csv", "amount,id,is_active\n1.5,7,true\n")
    make_schema("s.json", [("id", "int"), ("amount", "float"), ("is_active", "bool")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert rows_of(proc.stdout) == [["id", "amount", "is_active"], ["7", "1.5", "true"]]


# Spec: "Valid types: `string`, `int`, `float`, `bool`, `date`, `timestamp`"
def test_all_six_declared_types_are_accepted(make_csv, make_schema, run):
    make_csv("a.csv", "s,i,f,b,d,t\nhi,3,2.5,0,2024-07-01,2024-07-01T12:00:00Z\n")
    make_schema(
        "s.json",
        [("s", "string"), ("i", "int"), ("f", "float"), ("b", "bool"), ("d", "date"), ("t", "timestamp")],
    )
    proc = run("--output", "-", "--key", "i", "--schema", "s.json", "a.csv")
    assert rows_of(proc.stdout)[1] == ["hi", "3", "2.5", "false", "2024-07-01", "2024-07-01T12:00:00Z"]


# Spec: "Valid types: string, int, float, bool, date, timestamp"
# Context: anything else in the schema file is rejected.
def test_unknown_schema_type_is_an_error(make_csv, make_schema, run, workdir):
    make_csv("a.csv", "id\n1\n")
    (workdir / "s.json").write_text(json.dumps({"columns": [{"name": "id", "type": "decimal"}]}))
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv", expect_ok=False)
    assert proc.returncode != 0
    assert proc.stderr.strip()


# Spec: "Cast every input cell into target type"
# Context: the declared type wins over what the values look like.
def test_cells_are_cast_into_the_declared_type(make_csv, make_schema, run):
    make_csv("a.csv", "id,amount\n7,3\n")
    make_schema("s.json", [("id", "int"), ("amount", "float")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert rows_of(proc.stdout)[1] == ["7", "3.0"]


# Spec: "Extra input columns not in schema are ignored"
def test_extra_input_columns_are_dropped(make_csv, make_schema, run):
    make_csv("a.csv", "id,extra\n7,junk\n")
    make_schema("s.json", [("id", "int")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"]]


# Spec: "Missing input columns filled with null literal"
def test_columns_absent_from_an_input_are_filled_with_the_null_literal(make_csv, make_schema, run):
    make_csv("a.csv", "id\n7\n")
    make_schema("s.json", [("id", "int"), ("note", "string")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--csv-null-literal", "NA", "a.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["7", "NA"]]


# Spec: "If `--schema` is provided" together with "If `--schema` not provided: infer"
# Context: a provided schema takes precedence over the inference mode flag.
def test_schema_takes_precedence_over_infer_mode(make_csv, make_schema, run):
    make_csv("a.csv", "id\n7\n")
    make_schema("s.json", [("id", "string")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--infer", "loose", "a.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"]]
