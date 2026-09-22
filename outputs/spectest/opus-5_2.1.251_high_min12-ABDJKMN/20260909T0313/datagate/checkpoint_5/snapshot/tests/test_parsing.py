"""Spec section: CSV Parsing."""

import pytest


# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
def test_charset_is_used_for_decoding(dataset):
    body = "col,value\ncafé,1\n".encode("cp1252")
    payload = dataset("/p-cp1252.csv", body, params={"charset": "cp1252"}).get_json()
    assert payload["rows"][0][0] == "café"


# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
# Context: the declared charset wins over what detection would guess.
def test_declared_charset_wins_over_detection(dataset):
    body = "col,value\ncafé,1\n".encode("utf-8")
    payload = dataset(
        "/p-forced.csv", body, params={"charset": "latin-1"}
    ).get_json()
    assert payload["rows"][0][0] == "cafÃ©"


# Phrase: "Otherwise detect encoding."
def test_detection_handles_utf8_bom(dataset):
    body = "﻿name,age\nalice,30\n".encode("utf-8")
    payload = dataset("/p-bom.csv", body).get_json()
    assert payload["columns"] == ["name", "age"]


# Phrase: "Otherwise detect encoding."
def test_detection_handles_utf16(dataset):
    body = "name,age\nalice,30\nbob,41\n".encode("utf-16")
    payload = dataset("/p-utf16.csv", body).get_json()
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Delimiter must be inferred from input" -- comma.
def test_comma_delimiter_inferred(dataset):
    payload = dataset("/d-comma.csv", "a,b,c\n1,2,3\n4,5,6\n").get_json()
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`" -- semicolon.
def test_semicolon_delimiter_inferred(dataset):
    payload = dataset("/d-semi.csv", "a;b;c\n1;2;3\n4;5;6\n").get_json()
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`" -- tab.
def test_tab_delimiter_inferred(dataset):
    payload = dataset("/d-tab.csv", "a\tb\tc\n1\t2\t3\n4\t5\t6\n").get_json()
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


# Phrase: "Delimiter must be inferred from input."
# Context: text fields containing a rival delimiter must not mislead inference.
def test_delimiter_inference_with_rival_characters(dataset):
    csv_text = "name;note\nalice;likes a, b and c\nbob;x, y, z\n"
    payload = dataset("/d-rival.csv", csv_text).get_json()
    assert payload["columns"] == ["name", "note"]
    assert payload["rows"][0] == ["alice", "likes a, b and c"]


# Phrase: "Delimiter must be inferred from input."
# Context: quoted fields containing the delimiter and embedded newlines.
def test_quoted_fields_with_embedded_delimiter(dataset):
    csv_text = 'name,note\n"alice","a,b,c"\n"bob","line1\nline2"\n'
    payload = dataset("/d-quoted.csv", csv_text).get_json()
    assert payload["columns"] == ["name", "note"]
    assert payload["rows"][0] == ["alice", "a,b,c"]
    assert payload["rows"][1] == ["bob", "line1\nline2"]


# Phrase: "Delimiter must be inferred from input."
# Context: CRLF line endings are common in exported CSV.
def test_crlf_line_endings(dataset):
    payload = dataset("/d-crlf.csv", "a,b\r\n1,2\r\n3,4\r\n").get_json()
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2], [3, 4]]


# Phrase: "A valid file requires at least one header row and one data row."
# Context: a trailing newline does not create a phantom data row (AMBIGUITIES T15).
def test_trailing_newline_is_not_a_row(dataset):
    payload = dataset("/d-trailing.csv", "a,b\n1,2\n\n").get_json()
    assert payload["rows"] == [[1, 2]]


# Phrase: "A valid file requires at least one header row and one data row."
# Context: a file with no trailing newline is still valid.
def test_no_trailing_newline(dataset):
    payload = dataset("/d-nonewline.csv", "a,b\n1,2").get_json()
    assert payload["rows"] == [[1, 2]]


# Phrase: "columns and each row follow source column order."
# Context: ragged rows are aligned to the header (AMBIGUITIES T8).
def test_ragged_rows_align_to_header(dataset):
    payload = dataset("/d-ragged.csv", "a,b,c\n1,2\n4,5,6,7\n").get_json()
    assert payload["columns"] == ["a", "b", "c"]
    assert all(len(row) == len(payload["columns"]) for row in payload["rows"])


# Phrase: "A valid file requires at least one header row and one data row."
# Context: duplicate header labels are preserved as-is.
def test_duplicate_header_labels_preserved(dataset):
    payload = dataset("/d-dupes.csv", "a,a,b\n1,2,3\n").get_json()
    assert payload["columns"] == ["a", "a", "b"]
    assert payload["rows"] == [[1, 2, 3]]


# Phrase: "Delimiter must be inferred from input."
# Context: a numeric-looking header stays in `columns` and is not a data row.
def test_header_row_is_not_a_data_row(dataset):
    payload = dataset("/d-header.csv", "1,2\n3,4\n").get_json()
    assert payload["columns"] == ["1", "2"]
    assert payload["rows"] == [[3, 4]]


# Phrase: "minimum supported delimiters" -- context: semicolon file whose data
# contains decimal commas.
@pytest.mark.parametrize(
    "name,csv_text,expected_columns",
    [
        ("decimal-comma", "x;y\n1,5;2\n", ["x", "y"]),
        ("tabs", "x\ty\n1\t2\n", ["x", "y"]),
        ("semis-with-commas", "x;y;z\na,b;c;d\ne;f;g\n", ["x", "y", "z"]),
    ],
)
def test_delimiter_inference_cases(dataset, name, csv_text, expected_columns):
    payload = dataset("/d-case-{}.csv".format(name), csv_text).get_json()
    assert payload["columns"] == expected_columns
