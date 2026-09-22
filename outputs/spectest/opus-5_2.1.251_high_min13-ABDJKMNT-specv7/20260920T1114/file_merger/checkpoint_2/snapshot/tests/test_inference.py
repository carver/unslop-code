"""Spec section: Schema Resolution — inference when --schema is absent."""

from conftest import column, header_of, rows_of


# Phrase: "If --schema not provided: infer schema from union of all input headers"
# Context: Schema Resolution.
def test_header_is_the_union_of_input_headers(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    csv_file("b.csv", "id,amount\n2,3.5\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert header_of(result.stdout) == ["amount", "id", "note"]


# Phrase: "Column order: ascending lexicographic order of column names"
# Context: Schema Resolution, inferred schema. Ambiguity T17: codepoint order.
def test_inferred_columns_are_in_lexicographic_order(csv_file, run_tool):
    csv_file("a.csv", "beta,Alpha,gamma\n1,2,3\n")
    result = run_tool("--output", "-", "--key", "beta", "a.csv")
    assert header_of(result.stdout) == ["Alpha", "beta", "gamma"]


# Phrase: "Missing columns in a file filled with null literal"
# Context: Schema Resolution, inferred schema.
def test_column_missing_from_one_file_is_null_there(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    csv_file("b.csv", "id\n2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(result.stdout) == [["1", "a"], ["2", ""]]


# Phrase: "strict (default): infer types based on observed values"
# Context: Inference mode. An all-integer column is typed int and sorts numerically.
def test_strict_infers_int_from_observed_values(csv_file, run_tool):
    csv_file("a.csv", "id\n100\n9\n20\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert column(result.stdout, "id") == ["9", "20", "100"]


# Phrase: "strict (default)"
# Context: Inference mode. Omitting --infer behaves like passing strict.
def test_strict_is_the_default_mode(csv_file, run_tool):
    csv_file("a.csv", "id\n10\n9\n")
    default = run_tool("--output", "-", "--key", "id", "a.csv")
    explicit = run_tool("--output", "-", "--key", "id", "--infer", "strict", "a.csv")
    assert default.stdout == explicit.stdout


# Phrase: "columns with conflicting types across files fall back to string"
# Context: strict inference. Ambiguity T1: per-file types are compared.
def test_strict_falls_back_to_string_on_cross_file_conflict(csv_file, run_tool):
    csv_file("a.csv", "id\n10\n9\n")
    csv_file("b.csv", "id\nabc\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(result.stdout, "id") == ["10", "9", "abc"]


# Phrase: "columns with conflicting types across files fall back to string"
# Context: strict inference. int in one file and float in another conflict.
def test_strict_int_and_float_files_conflict(csv_file, run_tool):
    csv_file("a.csv", "v\n10\n")
    csv_file("b.csv", "v\n9.5\n")
    result = run_tool("--output", "-", "--key", "v", "a.csv", "b.csv")
    assert column(result.stdout, "v") == ["10", "9.5"]


# Phrase: "infer types based on observed values"
# Context: strict inference, one file. Ambiguity T2: empty cells force string.
def test_strict_treats_empty_cells_as_string_observations(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n2,\n3,9\n")
    result = run_tool("--output", "-", "--key", "v", "a.csv")
    assert column(result.stdout, "v") == ["", "10", "9"]


# Phrase: "loose: prefer numeric/temporal types if all non-null observed values parse"
# Context: Inference mode. Values from all files are pooled.
def test_loose_pools_values_across_files(csv_file, run_tool):
    csv_file("a.csv", "v\n10\n")
    csv_file("b.csv", "v\n9.5\n")
    result = run_tool("--output", "-", "--key", "v", "--infer", "loose", "a.csv", "b.csv")
    assert column(result.stdout, "v") == ["9.5", "10.0"]


# Phrase: "empty strings are treated as nulls and don't affect inference"
# Context: loose inference.
def test_loose_ignores_empty_cells_when_inferring(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n2,\n3,9\n")
    result = run_tool("--output", "-", "--key", "v", "--infer", "loose", "a.csv")
    assert column(result.stdout, "v") == ["", "9", "10"]


# Phrase: "otherwise fall back to string"
# Context: loose inference. A value that parses as nothing numeric forces string.
def test_loose_falls_back_to_string(csv_file, run_tool):
    csv_file("a.csv", "v\n10\nabc\n")
    result = run_tool("--output", "-", "--key", "v", "--infer", "loose", "a.csv")
    assert column(result.stdout, "v") == ["10", "abc"]


# Phrase: "Type priority: timestamp > date > bool > int > float > string"
# Context: Inference. Ambiguity T3: 1/0 values are booleans before they are ints.
def test_priority_prefers_bool_over_int(csv_file, run_tool):
    csv_file("a.csv", "flag\n1\n0\n1\n")
    result = run_tool("--output", "-", "--key", "flag", "a.csv")
    assert column(result.stdout, "flag") == ["false", "true", "true"]


# Phrase: "Type priority: ... int > float"
# Context: Inference. Mixed int/float values settle on the lower-priority float.
def test_priority_falls_to_float_for_mixed_numbers(csv_file, run_tool):
    csv_file("a.csv", "v\n2\n1.5\n")
    result = run_tool("--output", "-", "--key", "v", "a.csv")
    assert column(result.stdout, "v") == ["1.5", "2.0"]


# Phrase: "Type priority: timestamp > date"
# Context: Inference. Ambiguity T4: date-only values infer as date, not timestamp.
def test_date_only_column_infers_as_date(csv_file, run_tool):
    csv_file("a.csv", "d\n2024-07-02\n2024-07-01\n")
    result = run_tool("--output", "-", "--key", "d", "a.csv")
    assert column(result.stdout, "d") == ["2024-07-01", "2024-07-02"]


# Phrase: "Inference recognises values by the casting rules below"
# Context: Inference. Timestamps are normalised once inferred.
def test_timestamp_column_is_inferred_and_normalised(csv_file, run_tool):
    csv_file("a.csv", "ts\n2024-07-01T12:00:00+02:00\n")
    result = run_tool("--output", "-", "--key", "ts", "a.csv")
    assert column(result.stdout, "ts") == ["2024-07-01T10:00:00Z"]


# Phrase: "infer schema from union of all input headers"
# Context: Inference. Ambiguity T20: an all-null column is a string column.
def test_all_null_column_infers_as_string(csv_file, run_tool):
    csv_file("a.csv", "id,blank\n1,\n2,\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert rows_of(result.stdout) == [["", "1"], ["", "2"]]


# Phrase: "columns with conflicting types across files fall back to string"
# Context: strict inference. A file lacking the column does not create a conflict.
def test_file_without_the_column_does_not_conflict(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n")
    csv_file("b.csv", "id\n2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(result.stdout, "v") == ["10", ""]
