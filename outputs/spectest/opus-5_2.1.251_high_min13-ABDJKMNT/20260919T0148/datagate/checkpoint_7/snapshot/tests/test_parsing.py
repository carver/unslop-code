"""Spec section: CSV Parsing."""

import pytest

from datagate_core.errors import DatagateError
from datagate_core.parsing import infer_delimiter, parse_table


# Phrase: "Delimiter must be inferred from input; minimum supported delimiters are `,`, `;`, and `\t`."
@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_supported_delimiters_are_inferred(delimiter):
    text = delimiter.join(["name", "age", "city"]) + "\n" + delimiter.join(["ada", "36", "london"])

    assert infer_delimiter(text) == delimiter


# Phrase: "Delimiter must be inferred from input" -- context: end to end through the HTTP layer.
@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_delimiters_parse_end_to_end(converted, delimiter):
    body = converted(f"name{delimiter}age\nada{delimiter}36\n").get_json()

    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["ada", 36]]


# Phrase: "Delimiter must be inferred from input" -- context: the wrong delimiter also appears in cells.
def test_inference_prefers_the_consistent_delimiter():
    text = "name;note\nada;a, b, c\ngrace;d, e, f\n"

    assert infer_delimiter(text) == ";"


# Phrase: "A valid file requires at least one header row and one data row."
def test_header_and_one_data_row_is_valid():
    columns, rows = parse_table("name,age\nada,36\n")

    assert columns == ["name", "age"]
    assert rows == [["ada", "36"]]


# Phrase: "A valid file requires at least one header row and one data row."
def test_header_only_is_rejected():
    with pytest.raises(DatagateError):
        parse_table("name,age\n")


# Phrase: "A valid file requires at least one header row and one data row."
def test_empty_content_is_rejected():
    with pytest.raises(DatagateError):
        parse_table("")


# Phrase: "A valid file requires at least one header row and one data row."
# Context: via HTTP the failure is reported as non-tabular content, 400.
def test_header_only_is_400_over_http(client, origin):
    source = origin.serve("/data.csv", "name,age\n")

    assert client.get("/convert", query_string={"source": source}).status_code == 400


# Phrase: "CSV Parsing" -- context: quoted fields containing the delimiter and newlines.
def test_quoted_fields_are_honoured(converted):
    body = converted('name,note\n"ada","lovelace, augusta"\n').get_json()

    assert body["rows"] == [["ada", "lovelace, augusta"]]


# Phrase: "CSV Parsing" -- context: blank lines between records are skipped.
def test_blank_lines_are_skipped(converted):
    body = converted("name,age\n\nada,36\n\ngrace,45\n").get_json()

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "columns and each row follow source column order." -- ragged rows (AMBIGUITIES T8).
def test_ragged_rows_are_squared_to_the_header():
    columns, rows = parse_table("a,b,c\n1,2\n1,2,3,4\n")

    assert columns == ["a", "b", "c"]
    assert rows == [["1", "2", ""], ["1", "2", "3"]]
