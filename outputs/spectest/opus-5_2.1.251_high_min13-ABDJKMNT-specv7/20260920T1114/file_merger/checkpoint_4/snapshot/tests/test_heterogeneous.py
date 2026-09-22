"""Spec section: Schema Resolution Across Heterogeneous Inputs."""

from conftest import column, header_of, rows_of


# Phrase: "Column set: union of all encountered field names"
# Context: Schema Resolution. Field names come from every format alike.
def test_column_set_unions_all_formats(csv_file, jsonl_file, parquet_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    jsonl_file("b.jsonl", [{"id": 2, "tag": "t"}])
    parquet_file("c.parquet", {"id": [3], "amount": [1.5]})
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet")
    assert header_of(result.stdout) == ["amount", "id", "note", "tag"]


# Phrase: "Column order: ascending lexicographic by column name"
# Context: Schema Resolution, inferred schema.
def test_inferred_column_order_is_lexicographic(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"zeta": 1, "alpha": 2, "Mid": 3}])
    result = run_tool("--output", "-", "--key", "alpha", "a.jsonl")
    assert header_of(result.stdout) == ["Mid", "alpha", "zeta"]


# Phrase: "--schema-strategy=authoritative (default): prefer typed sources in precedence order"
# Context: Schema disagreement. Ambiguity T23: Parquet outranks the text formats.
def test_authoritative_prefers_the_parquet_type(csv_file, parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [1], "v": [10]})
    csv_file("b.csv", "id,v\n2,abc\n")
    result = run_tool("--output", "-", "--key", "id", "a.parquet", "b.csv")
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["10", ""]


# Phrase: "JSONL ranks equal to CSV"
# Context: Schema disagreement, authoritative. Neither source wins, so they conflict.
def test_authoritative_treats_jsonl_and_csv_as_peers(csv_file, jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "v": 10}])
    csv_file("b.csv", "id,v\n2,abc\n")
    result = run_tool("--output", "-", "--key", "id", "a.jsonl", "b.csv")
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["10", "abc"]


# Phrase: "--schema-strategy=authoritative (default)"
# Context: Schema disagreement. Omitting the flag behaves like passing authoritative.
def test_authoritative_is_the_default_strategy(csv_file, parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [1], "v": [10]})
    csv_file("b.csv", "id,v\n2,abc\n")
    default = run_tool("--output", "-", "--key", "id", "a.parquet", "b.csv")
    explicit = run_tool(
        "--output", "-", "--key", "id",
        "--schema-strategy", "authoritative", "a.parquet", "b.csv",
    )
    assert default.stdout == explicit.stdout


# Phrase: "--schema-strategy=consensus: choose type that majority of files support"
# Context: Schema disagreement. Ambiguity T24: each file votes with its own type.
def test_consensus_follows_the_majority_of_files(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n")
    csv_file("b.csv", "id,v\n2,20\n")
    csv_file("c.csv", "id,v\n3,9.5\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema-strategy", "consensus",
        "a.csv", "b.csv", "c.csv",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["10", "20", ""]


# Phrase: "--schema-strategy=union: choose simplest common type that can hold all observed values"
# Context: Schema disagreement. int and float widen to float rather than to string.
def test_union_widens_int_and_float_to_float(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n")
    csv_file("b.csv", "id,v\n2,9.5\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema-strategy", "union", "a.csv", "b.csv"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["10.0", "9.5"]


# Phrase: "choose simplest common type that can hold all observed values"
# Context: Schema disagreement, union. Text that is not numeric forces string.
def test_union_falls_back_to_string_when_nothing_else_fits(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n")
    csv_file("b.csv", "id,v\n2,abc\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema-strategy", "union", "a.csv", "b.csv"
    )
    assert column(result.stdout, "v") == ["10", "abc"]


# Phrase: "--schema-strategy {authoritative,consensus,union}"
# Context: Usage. Only the listed values are accepted.
def test_unknown_schema_strategy_is_rejected(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema-strategy", "vote", "a.csv"
    )
    assert result.returncode != 0


# Phrase: "If --schema provided, it defines exact output columns, types, and order"
# Context: Schema Resolution. The strategy flags do not apply to a given schema.
def test_provided_schema_fixes_columns_across_formats(
    csv_file, jsonl_file, parquet_file, run_tool
):
    csv_file(
        "schema.json",
        '{"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "float"}]}',
    )
    csv_file("a.csv", "id,v,extra\n1,2,drop me\n")
    jsonl_file("b.jsonl", [{"id": 2, "v": 3}])
    parquet_file("c.parquet", {"id": [3], "other": ["x"]})
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "a.csv", "b.jsonl", "c.parquet",
    )
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "v"]
    assert rows_of(result.stdout) == [["1", "2.0"], ["2", "3.0"], ["3", ""]]


# Phrase: "Type inference per --infer mode (strict or loose)"
# Context: Schema Resolution. Ambiguity T26: --infer still drives the reconciliation.
def test_loose_inference_pools_values_across_formats(csv_file, jsonl_file, run_tool):
    csv_file("a.csv", "id,v\n1,10\n")
    jsonl_file("b.jsonl", [{"id": 2, "v": 9.5}])
    result = run_tool(
        "--output", "-", "--key", "id", "--infer", "loose", "a.csv", "b.jsonl"
    )
    assert column(result.stdout, "v") == ["10.0", "9.5"]


# Phrase: "Sorting by --key uses casted key values"
# Context: Sorting and Stability. Numeric keys from mixed sources compare numerically.
def test_keys_from_mixed_sources_sort_by_value(csv_file, jsonl_file, parquet_file, run_tool):
    csv_file("a.csv", "id\n100\n")
    jsonl_file("b.jsonl", [{"id": 9}])
    parquet_file("c.parquet", {"id": [20]})
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet")
    assert column(result.stdout, "id") == ["9", "20", "100"]


# Phrase: "Sort must be stable for equal keys"
# Context: Sorting and Stability. Rows tie across formats and keep input order.
def test_equal_keys_keep_input_order_across_sources(csv_file, jsonl_file, run_tool):
    csv_file("a.csv", "id,src\n1,csv-first\n1,csv-second\n")
    jsonl_file("b.jsonl", [{"id": 1, "src": "jsonl"}])
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    assert column(result.stdout, "src") == ["csv-first", "csv-second", "jsonl"]


# Phrase: "Sort must be stable for equal keys"
# Context: Sorting and Stability, with --desc. Equal keys still keep input order.
def test_descending_sort_is_stable_across_sources(csv_file, jsonl_file, run_tool):
    csv_file("a.csv", "id,src\n1,csv\n2,csv-high\n")
    jsonl_file("b.jsonl", [{"id": 1, "src": "jsonl"}])
    result = run_tool("--output", "-", "--key", "id", "--desc", "a.csv", "b.jsonl")
    assert column(result.stdout, "src") == ["csv-high", "csv", "jsonl"]


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: Sorting and Stability.
def test_missing_key_column_is_error_3(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1}])
    result = run_tool("--output", "-", "--key", "missing", "a.jsonl")
    assert result.returncode == 3
    assert result.stderr


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: Sorting and Stability. A column dropped by --schema is no longer a valid key.
def test_key_outside_a_provided_schema_is_error_3(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}]}')
    result = run_tool(
        "--output", "-", "--key", "note", "--schema", "schema.json", "a.csv"
    )
    assert result.returncode == 3


# Phrase: "All rows from all inputs appear exactly once; no deduplication"
# Context: Output. Identical rows from different formats are both kept.
def test_identical_rows_are_not_deduplicated(csv_file, jsonl_file, run_tool):
    csv_file("a.csv", "id,note\n1,same\n")
    jsonl_file("b.jsonl", [{"id": 1, "note": "same"}])
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    assert rows_of(result.stdout) == [["1", "same"], ["1", "same"]]


# Phrase: "Always produce single CSV with header row in resolved column order"
# Context: Output. Parquet and JSONL inputs still yield CSV on stdout.
def test_output_is_csv_regardless_of_input_format(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [1], "note": ["hi, there"]})
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.stdout == 'id,note\n1,"hi, there"\n'
