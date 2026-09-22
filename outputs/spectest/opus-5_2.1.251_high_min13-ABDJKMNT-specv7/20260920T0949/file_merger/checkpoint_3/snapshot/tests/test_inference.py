"""Schema resolution when --schema is absent."""

from conftest import rows_of


# Spec: "infer schema from union of all input headers"
def test_header_union_covers_every_input_column(make_csv, run):
    make_csv("a.csv", "id,note\n7,x\n")
    make_csv("b.csv", "id,amount\n8,1.5\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(proc.stdout)[0] == ["amount", "id", "note"]


# Spec: "Column order: ascending lexicographic order of column names"
def test_columns_are_ordered_lexicographically(make_csv, run):
    make_csv("a.csv", "zebra,Beta,alpha\n1,2,3\n")
    proc = run("--output", "-", "--key", "alpha", "a.csv")
    assert rows_of(proc.stdout)[0] == ["Beta", "alpha", "zebra"]


# Spec: "Missing columns in a file filled with null literal"
def test_column_absent_from_one_file_is_null_for_its_rows(make_csv, run):
    make_csv("a.csv", "id,note\n7,x\n")
    make_csv("b.csv", "id\n8\n")
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.csv", "b.csv")
    assert rows_of(proc.stdout)[1:] == [["7", "x"], ["8", "NA"]]


# Spec: "strict (default): infer types based on observed values"
# Context: a column whose values all parse as ints is an int column.
def test_strict_infers_int_from_observed_values(make_csv, run):
    make_csv("a.csv", "id\n10\n9\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["9"], ["10"]]


# Spec: "strict ...: columns with conflicting types across files fall back to `string`"
def test_strict_falls_back_to_string_on_cross_file_conflict(make_csv, run):
    make_csv("a.csv", "id\n10\n")
    make_csv("b.csv", "id\n9.5\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    # string ordering, and 9.5 keeps its original text
    assert rows_of(proc.stdout)[1:] == [["10"], ["9.5"]]


# Spec: "strict (default)" - strict is what you get without --infer.
def test_strict_is_the_default_mode(make_csv, run):
    make_csv("a.csv", "id\n10\n")
    make_csv("b.csv", "id\n9.5\n")
    implicit = run("--output", "-", "--key", "id", "a.csv", "b.csv").stdout
    explicit = run("--output", "-", "--key", "id", "--infer", "strict", "a.csv", "b.csv").stdout
    assert implicit == explicit


# Spec: "loose: prefer numeric/temporal types if all non-null observed values parse"
# Context: the same int/float mix that conflicts in strict unifies as float in loose.
def test_loose_unifies_numeric_values_across_files(make_csv, run):
    make_csv("a.csv", "id\n10\n")
    make_csv("b.csv", "id\n9.5\n")
    proc = run("--output", "-", "--key", "id", "--infer", "loose", "a.csv", "b.csv")
    assert rows_of(proc.stdout)[1:] == [["9.5"], ["10.0"]]


# Spec: "loose: ... otherwise fall back to `string`"
def test_loose_falls_back_to_string_when_a_value_does_not_parse(make_csv, run):
    make_csv("a.csv", "id\n10\nabc\n")
    proc = run("--output", "-", "--key", "id", "--infer", "loose", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["10"], ["abc"]]


# Spec: "loose: ... empty strings are treated as nulls and don't affect inference"
def test_loose_ignores_empty_strings_when_inferring(make_csv, run):
    make_csv("a.csv", "id,v\n4,\n5,10\n6,9\n")
    proc = run("--output", "-", "--key", "v", "--infer", "loose", "a.csv")
    # numeric ordering proves v stayed int; the empty cell sorts first as a null
    assert rows_of(proc.stdout)[1:] == [["4", ""], ["6", "9"], ["5", "10"]]


# Spec: "strict ...: infer types based on observed values" vs loose's "empty strings ... don't affect inference"
# Context: see AMBIGUITIES T3 - in strict an observed empty value is only compatible with string.
def test_strict_treats_an_observed_empty_value_as_a_string_observation(make_csv, run):
    make_csv("a.csv", "id,v\n4,\n5,10\n6,9\n")
    proc = run("--output", "-", "--key", "v", "a.csv")
    # lexicographic ordering proves v fell back to string
    assert rows_of(proc.stdout)[1:] == [["4", ""], ["5", "10"], ["6", "9"]]


# Spec: "Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`"
# Context: 1/0 values satisfy both bool and int, and bool has the higher priority.
def test_zero_one_column_infers_as_bool(make_csv, run):
    make_csv("a.csv", "flag,id\n1,7\n0,8\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["true", "7"], ["false", "8"]]


# Spec: "Type priority: ... `int` > `float`"
# Context: a mix of ints and floats is not all-int, so the next priority that fits is float.
def test_mixed_int_and_float_values_infer_as_float(make_csv, run):
    make_csv("a.csv", "v\n1\n2.5\n")
    proc = run("--output", "-", "--key", "v", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["1.0"], ["2.5"]]


# Spec: "Type priority: `timestamp` > `date`" with "date: ISO-8601 YYYY-MM-DD"
# Context: see AMBIGUITIES T5 - date-only values are recognised as date, not timestamp.
def test_date_only_column_infers_as_date(make_csv, run):
    make_csv("a.csv", "d\n2024-07-02\n2024-07-01\n")
    proc = run("--output", "-", "--key", "d", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["2024-07-01"], ["2024-07-02"]]


# Spec: "Inference recognises values by the casting rules below" for timestamp
def test_timestamp_column_is_inferred_and_normalised(make_csv, run):
    make_csv("a.csv", "t\n2024-07-01T12:00:00+02:00\n")
    proc = run("--output", "-", "--key", "t", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["2024-07-01T10:00:00Z"]]


# Spec: "infer types based on observed values"
# Context: see AMBIGUITIES T12 - a column with no observed value falls back to string.
def test_column_without_observed_values_falls_back_to_string(make_csv, run):
    make_csv("a.csv", "id,note\n7,\n")
    proc = run("--output", "-", "--key", "id", "--infer", "loose", "a.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["7", ""]]
