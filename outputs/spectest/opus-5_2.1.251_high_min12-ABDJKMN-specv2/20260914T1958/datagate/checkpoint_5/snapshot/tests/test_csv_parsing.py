"""Spec section: CSV Parsing."""
import pytest

from conftest import convert_ok, dataset


# ---------------------------------------------------------------------------
# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
# Context: CSV parsing; the supplied charset wins over any detection.
# ---------------------------------------------------------------------------
def test_supplied_charset_is_used(gate, origin):
    # These bytes are valid in both encodings but decode differently.
    url = origin.add("/parse-cp1251.csv", "имя\nАня\n".encode("cp1251"))
    assert dataset(gate, url, charset="cp1251")["columns"] == ["имя"]


# ---------------------------------------------------------------------------
# Phrase: "Otherwise detect encoding."
# Context: CSV parsing; detection path (UTF-8 with a BOM).
# ---------------------------------------------------------------------------
def test_utf8_bom_is_detected_and_stripped(gate, origin):
    url = origin.add("/parse-bom.csv", "name,age\nAlice,30\n".encode("utf-8-sig"))
    body = dataset(gate, url)
    assert body["columns"] == ["name", "age"]


# ---------------------------------------------------------------------------
# Phrase: "Delimiter must be inferred from input, if present"
# Context: CSV parsing; comma.
# ---------------------------------------------------------------------------
def test_comma_delimiter_inferred(gate, origin):
    url = origin.add("/parse-comma.csv", "a,b,c\n1,2,3\n")
    body = dataset(gate, url)
    assert body["columns"] == ["a", "b", "c"]
    assert body["rows"] == [[1, 2, 3]]


# ---------------------------------------------------------------------------
# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`"
# Context: CSV parsing; semicolon.
# ---------------------------------------------------------------------------
def test_semicolon_delimiter_inferred(gate, origin):
    url = origin.add("/parse-semi.csv", "a;b;c\n1;2;3\n4;5;6\n")
    body = dataset(gate, url)
    assert body["columns"] == ["a", "b", "c"]
    assert body["rows"] == [[1, 2, 3], [4, 5, 6]]


# ---------------------------------------------------------------------------
# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`"
# Context: CSV parsing; tab.
# ---------------------------------------------------------------------------
def test_tab_delimiter_inferred(gate, origin):
    url = origin.add("/parse-tab.csv", "a\tb\tc\n1\t2\t3\n")
    body = dataset(gate, url)
    assert body["columns"] == ["a", "b", "c"]
    assert body["rows"] == [[1, 2, 3]]


# ---------------------------------------------------------------------------
# Phrase: "Delimiter must be inferred from input"
# Context: the dominant delimiter wins when another character also appears
#          inside field text.
# ---------------------------------------------------------------------------
def test_delimiter_inference_prefers_the_structural_character(gate, origin):
    url = origin.add("/parse-mixed.csv", "name;note\nAlice;likes a, b and c\nBob;x, y\n")
    body = dataset(gate, url)
    assert body["columns"] == ["name", "note"]
    assert body["rows"] == [["Alice", "likes a, b and c"], ["Bob", "x, y"]]


# ---------------------------------------------------------------------------
# Phrase: "Delimiter must be inferred from input"
# Context: quoted fields containing the delimiter stay intact.
# ---------------------------------------------------------------------------
def test_quoted_fields_containing_delimiter(gate, origin):
    url = origin.add("/parse-quoted.csv", 'name,city\n"Doe, Jane","Paris, FR"\n')
    assert dataset(gate, url)["rows"] == [["Doe, Jane", "Paris, FR"]]


# ---------------------------------------------------------------------------
# Phrase: "Delimiter must be inferred from input, if present"
# Context: no delimiter present -- a single-column file is still tabular
#          (see AMBIGUITIES T9).
# ---------------------------------------------------------------------------
def test_single_column_file_is_accepted(gate, origin):
    url = origin.add("/parse-onecol.csv", "value\n10\n20\n")
    body = dataset(gate, url)
    assert body["columns"] == ["value"]
    assert body["rows"] == [[10], [20]]


# ---------------------------------------------------------------------------
# Phrase: "A valid file requires at least one header row and one data row."
# Context: CSV parsing; a header with no data row is invalid.
# ---------------------------------------------------------------------------
def test_header_only_file_is_400(gate, origin):
    url = origin.add("/parse-headeronly.csv", "name,age\n")
    resp = gate.convert(source=url)
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "A valid file requires at least one header row and one data row."
# Context: exactly one header and one data row is the minimum valid file.
# ---------------------------------------------------------------------------
def test_one_header_and_one_data_row_is_valid(gate, origin):
    url = origin.add("/parse-minimal.csv", "name,age\nAlice,30\n")
    body = dataset(gate, url)
    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["Alice", 30]]


# ---------------------------------------------------------------------------
# Phrase: "A valid file requires at least one header row and one data row."
# Context: trailing blank lines do not count as data rows.
# ---------------------------------------------------------------------------
def test_trailing_blank_lines_are_not_data_rows(gate, origin):
    url = origin.add("/parse-trailingblank.csv", "name,age\n\n\n")
    assert gate.convert(source=url).status_code == 400


# ---------------------------------------------------------------------------
# Phrase: "CSV Parsing" (general)
# Context: CRLF line endings are handled like LF.
# ---------------------------------------------------------------------------
def test_crlf_line_endings(gate, origin):
    url = origin.add("/parse-crlf.csv", "a,b\r\n1,2\r\n3,4\r\n")
    body = dataset(gate, url)
    assert body["columns"] == ["a", "b"]
    assert body["rows"] == [[1, 2], [3, 4]]


# ---------------------------------------------------------------------------
# Phrase: "CSV Parsing" (general)
# Context: whitespace padding around cells (see AMBIGUITIES T5).
# ---------------------------------------------------------------------------
def test_padded_cells_are_trimmed(gate, origin):
    url = origin.add("/parse-padded.csv", "name, age\nAlice, 30\n")
    body = dataset(gate, url)
    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["Alice", 30]]


# ---------------------------------------------------------------------------
# Phrase: "columns" / "rows" alignment
# Context: ragged rows are normalised to the header width (AMBIGUITIES T10).
# ---------------------------------------------------------------------------
def test_ragged_rows_match_header_width(gate, origin):
    url = origin.add("/parse-ragged.csv", "a,b,c\n1,2\n1,2,3,4\n")
    body = dataset(gate, url)
    assert len(body["columns"]) == 3
    assert all(len(row) == 3 for row in body["rows"])


# ---------------------------------------------------------------------------
# Phrase: "rows" values
# Context: empty cells stay empty text (AMBIGUITIES T11).
# ---------------------------------------------------------------------------
def test_empty_cells_are_empty_strings(gate, origin):
    url = origin.add("/parse-empty-cell.csv", "a,b\n1,\n")
    assert dataset(gate, url)["rows"] == [[1, ""]]
