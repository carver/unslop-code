"""Checkpoint 2 - Source Dialect Assumptions for TSV, JSONL and Parquet."""
import json

import pytest

from conftest import (HAVE_PARQUET, needs_parquet, run_tool, write_csv,
                      write_file, write_jsonl, write_parquet, write_tsv,
                      body, col)

if HAVE_PARQUET:
    import pyarrow as pa


# ==========================================================================
# TSV
# ==========================================================================
# --------------------------------------------------------------------------
# Phrase: "TSV: delimiter is tab (\t)"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_tsv_splits_on_tabs_only(tmp_path):
    src = write_tsv(tmp_path / "a.tsv", ["a\tb\tc", "4\t2\t3"])
    res = run_tool("--output", "-", "--key", "a", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["a", "b", "c"]
    assert body(res.rows()) == [["4", "2", "3"]]


def test_tsv_comma_inside_field_is_data(tmp_path):
    src = write_tsv(tmp_path / "a.tsv", ["id\tname", "1\tfoo, bar"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["foo, bar"]


# --------------------------------------------------------------------------
# Phrase: "TSV: ... no quoting"
# Context: a double quote in a TSV field is an ordinary character.
# --------------------------------------------------------------------------
def test_tsv_quotes_are_literal(tmp_path):
    src = write_tsv(tmp_path / "a.tsv", ['id\tname', '1\t"quoted"'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ['"quoted"']


def test_tsv_quote_does_not_absorb_the_delimiter(tmp_path):
    src = write_tsv(tmp_path / "a.tsv",
                    ['id\tname\tmore\tx', '7\t"a\tb"\tz'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ['"a']
    assert col(res.rows(), "more") == ['b"']
    assert col(res.rows(), "x") == ['z']


# --------------------------------------------------------------------------
# Phrase: "TSV: ... header row required"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_tsv_header_names_the_columns(tmp_path):
    src = write_tsv(tmp_path / "a.tsv", ["ts\tid", "5\t9"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["id", "ts"]


def test_tsv_without_a_header_row_is_error_5(tmp_path):
    src = write_file(tmp_path / "a.tsv", "")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


# --------------------------------------------------------------------------
# Phrase: "TSV: ... `\n` or `\r\n` line endings"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_tsv_accepts_crlf_line_endings(tmp_path):
    src = write_file(tmp_path / "a.tsv", "id\tname\r\n2\tb\r\n1\ta\r\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_tsv_crlf_does_not_leak_into_values(tmp_path):
    src = write_file(tmp_path / "a.tsv", "id\tname\r\n1\ta\r\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]
    assert "\r" not in res.stdout


# --------------------------------------------------------------------------
# Phrase: "TSV: ... literal tabs inside field not allowed (error 5)"
# Context: with no quoting, a field-internal tab shows up as a surplus field.
# --------------------------------------------------------------------------
def test_tsv_row_with_extra_tab_is_error_5(tmp_path):
    src = write_tsv(tmp_path / "a.tsv", ["id\tname", "1\ta\tb"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


def test_tsv_extra_tab_error_mentions_the_file(tmp_path):
    src = write_tsv(tmp_path / "broken.tsv", ["id\tname", "1\ta\tb"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5
    assert "broken.tsv" in res.stderr


def test_tsv_short_row_is_not_an_error(tmp_path):
    # Only surplus fields indicate an embedded tab; a short row is padded.
    src = write_tsv(tmp_path / "a.tsv", ["id\tname", "1"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == [""]


# ==========================================================================
# JSONL
# ==========================================================================
# --------------------------------------------------------------------------
# Phrase: "JSONL: one UTF-8 JSON object per line"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_jsonl_one_object_per_line(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "v": "x"}, {"id": 2, "v": "y"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["x", "y"]


def test_jsonl_is_utf8(tmp_path):
    src = write_file(tmp_path / "a.jsonl",
                     '{"id": 1, "v": "café"}\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["café"]


def test_jsonl_column_set_is_the_union_of_row_keys(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "a": "p"}, {"id": 2, "b": "q"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["a", "b", "id"]


# --------------------------------------------------------------------------
# Phrase: "JSONL: ... objects must be flat (no arrays/objects as values)"
#         plus "nested structures trigger error 6"
# Context: Determinism Checklist / Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_jsonl_array_value_is_error_6(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "tags": ["x", "y"]}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


def test_jsonl_object_value_is_error_6(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "meta": {"k": "v"}}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


def test_jsonl_empty_array_value_is_error_6(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "tags": []}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


def test_jsonl_nested_error_names_the_file(tmp_path):
    src = write_jsonl(tmp_path / "nested.jsonl", [{"id": 1, "m": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6
    assert "nested.jsonl" in res.stderr


def test_jsonl_nested_value_in_an_unused_column_is_ignored(tmp_path):
    # Superseded by checkpoint 4 (see AMBIGUITIES.md T57): error 6 is now
    # conditioned on "without --schema", and a column the schema does not
    # declare is never materialised.
    schema = write_file(tmp_path / "s.json",
                        json.dumps({"columns": [{"name": "id",
                                                 "type": "int"}]}))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr


# --------------------------------------------------------------------------
# Phrase: "JSONL: ... `null` permitted"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_jsonl_null_is_allowed(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "v": None}, {"id": 2, "v": "x"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["", "x"]


# --------------------------------------------------------------------------
# Phrase: "JSONL: ... keys case-sensitive"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_jsonl_keys_are_case_sensitive(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "Name": "x",
                                              "name": "y"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["Name", "id", "name"]
    assert col(res.rows(), "Name") == ["x"]
    assert col(res.rows(), "name") == ["y"]


def test_jsonl_case_differing_keys_do_not_merge_across_rows(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "V": "u"}, {"id": 2, "v": "l"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "V") == ["u", ""]
    assert col(res.rows(), "v") == ["", "l"]


# --------------------------------------------------------------------------
# Phrase: "JSONL: ... blank/whitespace lines ignored"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
def test_jsonl_blank_lines_ignored(tmp_path):
    src = write_file(tmp_path / "a.jsonl",
                     '{"id": 1}\n\n{"id": 2}\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


def test_jsonl_whitespace_lines_ignored(tmp_path):
    src = write_file(tmp_path / "a.jsonl",
                     '{"id": 1}\n   \n\t\n{"id": 2}\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


def test_jsonl_file_of_only_blank_lines_yields_no_rows(tmp_path):
    a = write_file(tmp_path / "a.jsonl", "\n\n   \n")
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 5}])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["5"]


def test_jsonl_trailing_newline_optional(tmp_path):
    src = write_file(tmp_path / "a.jsonl", '{"id": 1}\n{"id": 2}')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


# ==========================================================================
# Parquet
# ==========================================================================
# --------------------------------------------------------------------------
# Phrase: "Parquet: flat schemas only (no nested/list/map types); nested
#          fields trigger error 6"
# Context: Source Dialect Assumptions.
# --------------------------------------------------------------------------
@needs_parquet
def test_parquet_flat_schema_ok(tmp_path):
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1, 2], "v": ["x", "y"]})
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["x", "y"]


@needs_parquet
def test_parquet_list_column_is_error_6(tmp_path):
    schema = pa.schema([("id", pa.int64()),
                        ("tags", pa.list_(pa.string()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "tags": [["x", "y"]]}, schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


@needs_parquet
def test_parquet_struct_column_is_error_6(tmp_path):
    schema = pa.schema([("id", pa.int64()),
                        ("meta", pa.struct([("k", pa.string())]))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "meta": [{"k": "v"}]}, schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


@needs_parquet
def test_parquet_map_column_is_error_6(tmp_path):
    schema = pa.schema([("id", pa.int64()),
                        ("m", pa.map_(pa.string(), pa.int64()))])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "m": [[("a", 1)]]}, schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6


@needs_parquet
def test_parquet_nested_error_names_the_file(tmp_path):
    schema = pa.schema([("id", pa.int64()), ("t", pa.list_(pa.string()))])
    src = write_parquet(tmp_path / "nested.parquet",
                        {"id": [1], "t": [["x"]]}, schema=schema)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 6
    assert "nested.parquet" in res.stderr


@needs_parquet
def test_parquet_nulls_are_missing_values(tmp_path):
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1, 2], "v": ["x", None]})
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["x", ""]


# --------------------------------------------------------------------------
# Phrase: "Parquet reading must be streamed row group-wise;
#          --parquet-row-group-bytes is advisory for batch sizing"
# Context: Performance & Memory.
# --------------------------------------------------------------------------
@needs_parquet
def test_parquet_multiple_row_groups_all_read(tmp_path):
    n = 500
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": list(range(n)),
                         "v": ["v%d" % i for i in range(n)]},
                        row_group_size=50)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert len(body(res.rows())) == n
    assert col(res.rows(), "id") == [str(i) for i in range(n)]


@needs_parquet
def test_parquet_row_group_bytes_does_not_change_output(tmp_path):
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": list(range(100))}, row_group_size=10)
    small = run_tool("--output", "-", "--key", "id",
                     "--parquet-row-group-bytes", "1024", src)
    big = run_tool("--output", "-", "--key", "id",
                   "--parquet-row-group-bytes", "104857600", src)
    assert small.returncode == 0, small.stderr
    assert big.returncode == 0, big.stderr
    assert small.stdout == big.stdout
