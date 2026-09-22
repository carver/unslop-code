"""Spec section: Schema Resolution & Column Order."""
import json

from conftest import run_tool, write_csv, write_file, write_schema, col


# Phrase: "If --schema is provided: JSON file with exact output schema and
#          column order"
# Context: the documented schema document shape is accepted verbatim.
def test_documented_schema_document(tmp_path):
    doc = {
        "columns": [
            {"name": "id", "type": "int"},
            {"name": "ts", "type": "timestamp"},
            {"name": "amount", "type": "float"},
            {"name": "note", "type": "string"},
            {"name": "is_active", "type": "bool"},
        ]
    }
    schema = write_file(tmp_path / "schema.json", json.dumps(doc))
    src = write_csv(tmp_path / "a.csv",
                    ["id,ts,amount,note,is_active",
                     "7,2024-07-01T12:00:00Z,1.5,hi,1"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["id", "ts", "amount", "note", "is_active"]


# Phrase: "Valid types: string, int, float, bool, date, timestamp"
# Context: all six type names are accepted.
def test_all_valid_types_accepted(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("a", "string"), ("b", "int"), ("c", "float"),
                           ("d", "bool"), ("e", "date"), ("f", "timestamp")])
    src = write_csv(tmp_path / "a.csv",
                    ["a,b,c,d,e,f",
                     "x,1,2.5,true,2024-01-02,2024-01-02T03:04:05Z"])
    res = run_tool("--output", "-", "--key", "b", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["x", "1", "2.5", "true", "2024-01-02",
                             "2024-01-02T03:04:05Z"]


# Phrase: "Valid types: string, int, float, bool, date, timestamp"
# Context: an unknown type name is rejected.
def test_unknown_schema_type_rejected(tmp_path):
    schema = write_file(tmp_path / "s.json",
                        json.dumps({"columns": [{"name": "id",
                                                 "type": "decimal"}]}))
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Phrase: "Cast every input cell into target type"
# Context: the declared type, not the observed data, drives the output text.
def test_schema_type_drives_casting(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("n", "float")])
    src = write_csv(tmp_path / "a.csv", ["n", "3"])
    res = run_tool("--output", "-", "--key", "n", "--schema", schema, src)
    assert res.rows()[1] == ["3.0"]


# Phrase: "Extra input columns not in schema are ignored"
# Context: columns present in the input but absent from the schema disappear.
def test_extra_input_columns_ignored(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    src = write_csv(tmp_path / "a.csv", ["id,junk,more", "1,x,y"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.rows() == [["id"], ["1"]]


# Phrase: "Missing input columns filled with null literal"
# Context: schema columns absent from the input become nulls.
def test_missing_input_columns_filled(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("absent", "string")])
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.rows() == [["id", "absent"], ["1", ""]]

    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NA", src)
    assert res.rows()[1] == ["1", "NA"]


# Phrase: "If --schema not provided: infer schema from union of all input
#          headers"
# Context: the output carries every column seen in any input.
def test_inferred_schema_is_union_of_headers(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,x", "1,ax"])
    b = write_csv(tmp_path / "b.csv", ["id,y", "2,by"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.rows()[0] == ["id", "x", "y"]


# Phrase: "Column order: ascending lexicographic order of column names"
# Context: inferred columns are ordered by name, not by first appearance.
def test_inferred_column_order_is_lexicographic(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["zz,b", "1,2"])
    b = write_csv(tmp_path / "b.csv", ["Aa,mm", "3,4"])
    res = run_tool("--output", "-", "--key", "b", a, b)
    assert res.rows()[0] == ["Aa", "b", "mm", "zz"]


# Phrase: "Missing columns in a file filled with null literal"
# Context: under inference, a file lacking a union column yields nulls.
def test_inferred_missing_columns_filled(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,x", "1,ax"])
    b = write_csv(tmp_path / "b.csv", ["id", "2"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.rows() == [["id", "x"], ["1", "ax"], ["2", ""]]


# Phrase: "strict (default): infer types based on observed values"
# Context: a clean integer column becomes int (numeric ordering proves it).
def test_strict_infers_int(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "10", "9", "100"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert col(res.rows(), "id") == ["9", "10", "100"]


# Phrase: "strict (default)"
# Context: strict is used when --infer is omitted.
def test_strict_is_the_default_mode(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["v", "1"])
    b = write_csv(tmp_path / "b.csv", ["v", "x"])
    default = run_tool("--output", "-", "--key", "v", a, b)
    explicit = run_tool("--output", "-", "--key", "v", "--infer", "strict",
                        a, b)
    assert default.stdout == explicit.stdout


# Phrase: "columns with conflicting types across files fall back to string"
# Context: file 1 says int, file 2 says string -> string ordering.
def test_strict_conflicting_types_fall_back_to_string(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["v", "10", "9"])
    b = write_csv(tmp_path / "b.csv", ["v", "abc"])
    res = run_tool("--output", "-", "--key", "v", a, b)
    # string ordering: "10" < "9" < "abc"
    assert col(res.rows(), "v") == ["10", "9", "abc"]


# Phrase: "columns with conflicting types across files fall back to string"
# Context: consistent types across files keep the inferred type.
def test_strict_agreeing_types_kept(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["v", "10"])
    b = write_csv(tmp_path / "b.csv", ["v", "9"])
    res = run_tool("--output", "-", "--key", "v", a, b)
    assert col(res.rows(), "v") == ["9", "10"]


# Phrase: "loose: prefer numeric/temporal types if all non-null observed
#          values parse"
# Context: all values parse as numbers -> numeric ordering.
def test_loose_prefers_numeric_when_all_parse(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v", "10", "9.5", "100"])
    res = run_tool("--output", "-", "--key", "v", "--infer", "loose", src)
    assert [float(x) for x in col(res.rows(), "v")] == [9.5, 10.0, 100.0]


# Phrase: "loose: ... otherwise fall back to string"
# Context: one unparseable value drags the column to string.
def test_loose_falls_back_to_string(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v", "10", "9", "abc"])
    res = run_tool("--output", "-", "--key", "v", "--infer", "loose", src)
    assert col(res.rows(), "v") == ["10", "9", "abc"]


# Phrase: "loose: ... empty strings are treated as nulls and don't affect
#          inference"
# Context: an empty cell does not force the column to string in loose mode.
def test_loose_ignores_empty_strings_for_inference(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v", "10", "", "9", "100"])
    res = run_tool("--output", "-", "--key", "v", "--infer", "loose", src)
    values = col(res.rows(), "v")
    assert values[0] == ""            # null first
    assert values[1:] == ["9", "10", "100"]   # numeric ordering


# Phrase: "loose ... temporal types"
# Context: all values parse as dates -> date type and chronological order.
def test_loose_infers_temporal(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["d", "2024-10-01", "", "2024-02-11"])
    res = run_tool("--output", "-", "--key", "d", "--infer", "loose", src)
    assert col(res.rows(), "d") == ["", "2024-02-11", "2024-10-01"]


# Phrase: "Type priority: timestamp > date > bool > int > float > string"
# Context: a column of only 1/0 is recognised as bool (bool outranks int).
def test_priority_bool_outranks_int(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["flag,n", "1,x", "0,y"])
    res = run_tool("--output", "-", "--key", "n", "--infer", "loose", src)
    assert col(res.rows(), "flag") == ["true", "false"]


# Phrase: "Type priority: ... int > float"
# Context: whole numbers infer as int, not float.
def test_priority_int_outranks_float(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["n", "3", "4"])
    res = run_tool("--output", "-", "--key", "n", "--infer", "loose", src)
    assert col(res.rows(), "n") == ["3", "4"]


# Phrase: "Type priority: ... int > float"
# Context: mixing an integer and a real number resolves to float.
def test_int_and_float_resolve_to_float(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["n", "3", "4.5"])
    res = run_tool("--output", "-", "--key", "n", "--infer", "loose", src)
    assert col(res.rows(), "n") == ["3.0", "4.5"]


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: inferred schema case.
def test_key_not_in_inferred_schema_is_error(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "nope", src)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: the column exists in the input but was dropped by the schema.
def test_key_dropped_by_schema_is_error(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    src = write_csv(tmp_path / "a.csv", ["id,other", "1,x"])
    res = run_tool("--output", "-", "--key", "other", "--schema", schema, src)
    assert res.returncode != 0


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: one bad member of a composite key is enough.
def test_composite_key_with_unknown_column_is_error(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id,ghost", src)
    assert res.returncode != 0


# Phrase: "If --schema is provided: JSON file"
# Context: a schema column may be absent from every input.
def test_schema_column_absent_everywhere(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("ghost", "int")])
    src = write_csv(tmp_path / "a.csv", ["id", "2", "1"])
    res = run_tool("--output", "-", "--key", "ghost,id",
                   "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows() == [["id", "ghost"], ["1", ""], ["2", ""]]
