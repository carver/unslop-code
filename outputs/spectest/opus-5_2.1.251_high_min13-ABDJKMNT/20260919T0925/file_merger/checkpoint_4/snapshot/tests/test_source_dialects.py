"""Per-format source dialect rules: TSV, JSON Lines, and Parquet."""

import pyarrow as pa


# --- TSV -------------------------------------------------------------------


def test_tsv_splits_on_tabs_with_header_row(run_cli, text_file):
    # Spec: "**TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line endings"
    a = text_file("a.tsv", "id\tnote\n2\tbeta\n1\talpha\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["1", "alpha"], ["2", "beta"]]


def test_tsv_commas_and_quotes_are_literal(run_cli, text_file):
    # Spec: "delimiter is tab (`\t`), no quoting"
    a = text_file("a.tsv", 'id\tnote\n7\t"a,b"\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", '"a,b"']]


def test_tsv_ignores_csv_quotechar_flag(run_cli, text_file):
    # Spec: "no quoting" for TSV, while the flags are named `--csv-*` (AMBIGUITIES T31)
    a = text_file("a.tsv", "id\tnote\n1\t'a\tb'\n")
    result = run_cli("--output", "-", "--key", "id", "--csv-quotechar", "'", a)
    assert result.returncode == 5


def test_tsv_literal_tab_inside_field_is_error_5(run_cli, text_file):
    # Spec: "literal tabs inside field not allowed (error 5)"
    a = text_file("a.tsv", "id\tnote\n1\tha\tha\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 5
    assert "a.tsv" in result.stderr


def test_tsv_short_row_fills_missing_columns_with_null(run_cli, text_file):
    # Spec: "literal tabs inside field not allowed" constrains long rows only (AMBIGUITIES T25)
    a = text_file("a.tsv", "id\tnote\n7\n")
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "NA"]]


def test_tsv_without_header_row_is_error_5(run_cli, text_file):
    # Spec: "header row required" (AMBIGUITIES T25: an empty TSV has no header)
    a = text_file("a.tsv", "")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 5


def test_tsv_empty_cell_is_null(run_cli, text_file):
    # Spec: "CSV/TSV cell is empty, treat as missing → emit null literal"
    a = text_file("a.tsv", "id\tnote\n7\t\n")
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert result.rows == [["id", "note"], ["7", "NA"]]


# --- JSON Lines ------------------------------------------------------------


def test_jsonl_one_object_per_line(run_cli, jsonl_file):
    # Spec: "**JSONL**: one UTF-8 JSON object per line"
    a = jsonl_file("a.jsonl", [{"id": 2, "note": "b"}, {"id": 1, "note": "a"}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["1", "a"], ["2", "b"]]


def test_jsonl_utf8_values_round_trip(run_cli, text_file):
    # Spec: "one UTF-8 JSON object per line"
    a = text_file("a.jsonl", '{"id": 1, "note": "héllo ☃"}\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.rows == [["id", "note"], ["1", "héllo ☃"]]


def test_jsonl_null_is_permitted(run_cli, jsonl_file):
    # Spec: "`null` permitted" / "If JSONL/Parquet value is `null` ... → emit null literal"
    a = jsonl_file("a.jsonl", [{"id": 1, "note": None}])
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["1", "NA"]]


def test_jsonl_keys_are_case_sensitive(run_cli, jsonl_file):
    # Spec: "keys case-sensitive"
    a = jsonl_file("a.jsonl", [{"id": 1, "Note": "upper", "note": "lower"}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["Note", "id", "note"], ["upper", "1", "lower"]]


def test_jsonl_blank_and_whitespace_lines_ignored(run_cli, text_file):
    # Spec: "blank/whitespace lines ignored"
    a = text_file("a.jsonl", '\n{"id": 1}\n   \n\t\n{"id": 2}\n\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id"], ["1"], ["2"]]


def test_jsonl_array_value_is_error_6(run_cli, text_file):
    # Spec: "objects must be flat (no arrays/objects as values)" / "nested structures trigger error 6"
    a = text_file("a.jsonl", '{"id": 1, "tags": ["x", "y"]}\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 6
    assert "tags" in result.stderr


def test_jsonl_object_value_is_error_6(run_cli, text_file):
    # Spec: "no arrays/objects as values"
    a = text_file("a.jsonl", '{"id": 1, "meta": {"k": "v"}}\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 6


def test_jsonl_invalid_json_line_is_error_5(run_cli, text_file):
    # Spec: "one UTF-8 JSON object per line" (AMBIGUITIES T26: decoding failure is error 5)
    a = text_file("a.jsonl", '{"id": 1}\n{not json}\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 5
    assert "a.jsonl" in result.stderr


def test_jsonl_non_object_line_is_error_5(run_cli, text_file):
    # Spec: "one UTF-8 JSON object per line" (AMBIGUITIES T26)
    a = text_file("a.jsonl", "[1, 2]\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 5


def test_jsonl_rows_may_omit_keys(run_cli, jsonl_file):
    # Spec: "Column set: union of all encountered field names" + missing → null literal
    a = jsonl_file("a.jsonl", [{"id": 1, "note": "x"}, {"id": 2}])
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert result.rows == [["id", "note"], ["1", "x"], ["2", "NA"]]


# --- Parquet ---------------------------------------------------------------


def test_parquet_flat_schema_is_read(run_cli, parquet_file):
    # Spec: "**Parquet**: flat schemas only"
    a = parquet_file("a.parquet", {"id": [2, 1], "note": ["b", "a"]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["1", "a"], ["2", "b"]]


def test_parquet_list_column_is_error_6(run_cli, parquet_file):
    # Spec: "no nested/list/map types; nested fields trigger error 6"
    a = parquet_file("a.parquet", {"id": [1], "tags": [["x", "y"]]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 6
    assert "tags" in result.stderr


def test_parquet_struct_column_is_error_6(run_cli, parquet_file):
    # Spec: "no nested/list/map types"
    a = parquet_file("a.parquet", {"id": [1], "meta": [{"k": "v"}]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 6


def test_parquet_map_column_is_error_6(run_cli, parquet_file):
    # Spec: "no nested/list/map types"
    table = pa.table({"id": pa.array([1]), "meta": pa.array([[("k", "v")]], type=pa.map_(pa.string(), pa.string()))})
    a = parquet_file("a.parquet", table)
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 6


def test_parquet_null_cell_is_null_literal(run_cli, parquet_file):
    # Spec: "If JSONL/Parquet value is `null` ... treat as missing → emit null literal"
    a = parquet_file("a.parquet", {"id": [1], "note": [None]})
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NA", a)
    assert result.rows == [["id", "note"], ["1", "NA"]]


def test_parquet_streams_multiple_row_groups(run_cli, parquet_file, tmp_path):
    # Spec: "Parquet reading must be streamed row group–wise"
    import pyarrow.parquet as pq

    path = tmp_path / "many.parquet"
    table = pa.table({"id": list(range(500, 0, -1))})
    pq.write_table(table, path, row_group_size=25)
    result = run_cli("--output", "-", "--key", "id", "--memory-limit-mb", "64", path)
    assert result.returncode == 0, result.stderr
    assert result.rows[1:] == [[str(n)] for n in range(1, 501)]
