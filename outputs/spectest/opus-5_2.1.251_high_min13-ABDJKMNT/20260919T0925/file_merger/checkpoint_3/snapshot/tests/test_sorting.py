"""Global sort order: composite keys, direction, stability, and null placement."""

import json

import pytest


@pytest.fixture
def schema_file(tmp_path):
    def _write(columns):
        path = tmp_path / "schema.json"
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    return _write


def test_sorts_globally_across_inputs(run_cli, csv_file):
    # Spec: "all rows from inputs, sorted globally by the key(s)"
    a = csv_file("a.csv", "k\nc\na\n")
    b = csv_file("b.csv", "k\nd\nb\n")
    result = run_cli("--output", "-", "--key", "k", a, b)
    assert [row[0] for row in result.rows[1:]] == ["a", "b", "c", "d"]


def test_numeric_keys_sort_by_value_not_text(run_cli, csv_file):
    # Spec: "sorted globally by the key(s)" with an inferred int column
    a = csv_file("a.csv", "id\n10\n9\n100\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert [row[0] for row in result.rows[1:]] == ["9", "10", "100"]


def test_composite_key_sorts_left_to_right(run_cli, csv_file):
    # Spec: "Sort by composite key specified via --key (one or more columns)"
    a = csv_file("a.csv", "g,id\nb,2\na,20\nb,1\na,3\n")
    result = run_cli("--output", "-", "--key", "g,id", a)
    assert result.rows[1:] == [["a", "3"], ["a", "20"], ["b", "1"], ["b", "2"]]


def test_default_order_is_ascending(run_cli, csv_file):
    # Spec: "Default order is ascending"
    a = csv_file("a.csv", "k\nb\na\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert [row[0] for row in result.rows[1:]] == ["a", "b"]


def test_desc_applies_to_all_keys(run_cli, csv_file):
    # Spec: "--desc applies to all keys"
    a = csv_file("a.csv", "g,id\nb,2\na,20\nb,1\na,3\n")
    result = run_cli("--output", "-", "--key", "g,id", "--desc", a)
    assert result.rows[1:] == [["b", "2"], ["b", "1"], ["a", "20"], ["a", "3"]]


def test_ties_keep_input_appearance_order(run_cli, csv_file):
    # Spec: "Sort must be stable with respect to input appearance for equal keys"
    a = csv_file("a.csv", "k,seq\nsame,a1\nsame,a2\n")
    b = csv_file("b.csv", "k,seq\nsame,b1\n")
    result = run_cli("--output", "-", "--key", "k", a, b)
    assert [row[1] for row in result.rows[1:]] == ["a1", "a2", "b1"]


def test_ties_keep_input_appearance_order_when_descending(run_cli, csv_file):
    # Spec: "stable with respect to input appearance" combined with "--desc" (AMBIGUITIES T10)
    a = csv_file("a.csv", "k,seq\nsame,a1\nsame,a2\n")
    b = csv_file("b.csv", "k,seq\nsame,b1\n")
    result = run_cli("--output", "-", "--key", "k", "--desc", a, b)
    assert [row[1] for row in result.rows[1:]] == ["a1", "a2", "b1"]


def test_nulls_sort_first_when_ascending(run_cli, csv_file):
    # Spec: "Nulls always compare less than non-null values ... (first in ascending"
    a = csv_file("a.csv", "k,seq\nb,1\n,2\na,3\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert [row[1] for row in result.rows[1:]] == ["2", "3", "1"]


def test_nulls_sort_last_when_descending(run_cli, csv_file):
    # Spec: "... last in descending)"
    a = csv_file("a.csv", "k,seq\nb,1\n,2\na,3\n")
    result = run_cli("--output", "-", "--key", "k", "--desc", a)
    assert [row[1] for row in result.rows[1:]] == ["1", "3", "2"]


def test_missing_key_column_in_one_file_sorts_as_null(run_cli, csv_file):
    # Spec: "Missing columns in a file filled with null literal" + the null ordering rule
    a = csv_file("a.csv", "k,seq\nb,1\n")
    b = csv_file("b.csv", "seq\n2\n")
    result = run_cli("--output", "-", "--key", "k", a, b)
    assert [row[1] for row in result.rows[1:]] == ["2", "1"]


def test_temporal_keys_sort_chronologically(run_cli, csv_file, schema_file):
    # Spec: "Sort by composite key" on timestamp values normalized to UTC
    schema = schema_file([{"name": "ts", "type": "timestamp"}, {"name": "seq", "type": "int"}])
    a = csv_file("a.csv", "ts,seq\n2024-07-01T12:00:00Z,1\n2024-07-01T09:00:00+02:00,2\n")
    result = run_cli("--output", "-", "--key", "ts", "--schema", schema, a)
    assert [row[1] for row in result.rows[1:]] == ["2", "1"]


def test_bool_keys_sort_false_before_true(run_cli, csv_file, schema_file):
    # Spec: "bool" as a sortable key type
    schema = schema_file([{"name": "flag", "type": "bool"}, {"name": "seq", "type": "int"}])
    a = csv_file("a.csv", "flag,seq\ntrue,1\nfalse,2\n")
    result = run_cli("--output", "-", "--key", "flag", "--schema", schema, a)
    assert [row[1] for row in result.rows[1:]] == ["2", "1"]


def test_keep_string_values_sort_after_typed_values(run_cli, csv_file, schema_file):
    # Spec: "keep-string: emit original text as string" ordered against typed values
    #       (AMBIGUITIES T8)
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "seq", "type": "string"}])
    a = csv_file("a.csv", "id,seq\noops,bad\n5,five\n,null\n")
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "keep-string", a)
    assert [row[1] for row in result.rows[1:]] == ["null", "five", "bad"]


def test_composite_key_columns_may_be_listed_in_any_order(run_cli, csv_file):
    # Spec: "--key <col>[,<col>...]" names keys independently of schema column order
    a = csv_file("a.csv", "g,id\nb,2\na,20\nb,1\na,3\n")
    result = run_cli("--output", "-", "--key", "id,g", a)
    assert result.rows[1:] == [["b", "1"], ["b", "2"], ["a", "3"], ["a", "20"]]
