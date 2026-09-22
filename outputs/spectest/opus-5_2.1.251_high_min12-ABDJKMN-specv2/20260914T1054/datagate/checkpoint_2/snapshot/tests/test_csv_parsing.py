"""Spec section: CSV Parsing."""
import pytest


# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
# Context: an explicit charset wins over what detection would have chosen.
def test_explicit_charset_overrides_detection(dataset):
    body = "a,b\ncafé,x\n".encode("utf-8")
    # utf-8 bytes read as latin-1 give mojibake - proof the parameter was honoured.
    _, out = dataset(body, charset="latin-1")
    assert out["rows"][0][0] == "cafÃ©"


# Phrase: "Otherwise detect encoding."
# Context: same bytes without the parameter decode as UTF-8.
def test_detection_used_when_charset_absent(dataset):
    _, out = dataset("a,b\ncafé,x\n".encode("utf-8"))
    assert out["rows"][0][0] == "café"


# Phrase: "Delimiter must be inferred from input ... minimum supported delimiters are `,`, `;`, `\t`"
# Context: comma-delimited input.
def test_comma_delimiter(dataset):
    _, out = dataset("name,qty,city\nwidget,3,köln\n")
    assert out["columns"] == ["name", "qty", "city"]
    assert out["rows"] == [["widget", 3, "köln"]]


# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`"
# Context: semicolon-delimited input.
def test_semicolon_delimiter(dataset):
    _, out = dataset("name;qty;city\nwidget;3;koln\n")
    assert out["columns"] == ["name", "qty", "city"]
    assert out["rows"] == [["widget", 3, "koln"]]


# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`"
# Context: tab-delimited input.
def test_tab_delimiter(dataset):
    _, out = dataset("name\tqty\tcity\nwidget\t3\tkoln\n")
    assert out["columns"] == ["name", "qty", "city"]
    assert out["rows"] == [["widget", 3, "koln"]]


# Phrase: "Delimiter must be inferred from input"
# Context: a comma-delimited file containing semicolons inside field text must not
# be mis-split; the inferred delimiter is the one that yields a consistent table.
def test_delimiter_inference_prefers_consistent_table(dataset):
    csv = 'name,note\nwidget,"a; b; c"\ngadget,"d; e; f"\n'
    _, out = dataset(csv)
    assert out["columns"] == ["name", "note"]
    assert out["rows"][0] == ["widget", "a; b; c"]


# Phrase: "Delimiter must be inferred from input"
# Context: tab-delimited data whose fields contain commas.
def test_tab_wins_over_commas_in_fields(dataset):
    csv = "name\tnote\nwidget\ta,b,c\ngadget\td,e,f\n"
    _, out = dataset(csv)
    assert out["columns"] == ["name", "note"]
    assert out["rows"][0] == ["widget", "a,b,c"]


# Phrase: "Delimiter must be inferred from input, if present"  (see AMBIGUITIES T7)
# Context: chosen reading - a single-column file has no delimiter and is still tabular.
def test_single_column_file(dataset):
    status, out = dataset("name\nwidget\ngadget\n")
    assert status == 200
    assert out["columns"] == ["name"]
    assert out["rows"] == [["widget"], ["gadget"]]


# Phrase: "A valid file requires at least one header row and one data row."
# Context: header + exactly one data row is the minimum valid file.
def test_minimum_valid_file(dataset):
    status, out = dataset("a,b\n1,2\n")
    assert status == 200
    assert out["columns"] == ["a", "b"]
    assert len(out["rows"]) == 1


# Phrase: "A valid file requires at least one header row and one data row."
# Context: a header with no data row is rejected at ingestion time.
def test_header_only_is_400(convert, origin):
    status, payload = convert(source=origin.add("a,b,c\n"))
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "A valid file requires at least one header row and one data row."
# Context: whitespace-only content has neither.
@pytest.mark.parametrize("body", ["\n", "   \n\n  \n", ",,\n"])
def test_blank_content_is_400(convert, origin, body):
    status, payload = convert(source=origin.add(body))
    assert status == 400, payload


# Phrase: standard CSV quoting  (context: "CSV Parsing")
# Context: quoted fields may contain the delimiter, quotes, and newlines.
def test_quoted_fields(dataset):
    csv = 'name,note\n"widget, large","says ""hi"""\n"multi","line\nbreak"\n'
    _, out = dataset(csv)
    assert out["rows"][0] == ["widget, large", 'says "hi"']
    assert out["rows"][1] == ["multi", "line\nbreak"]


# Phrase: CSV line endings (context: "CSV Parsing")
# Context: CRLF and LF files parse identically.
@pytest.mark.parametrize("nl", ["\n", "\r\n", "\r"])
def test_line_endings(dataset, nl):
    csv = nl.join(["a,b", "1,2", "3,4"]) + nl
    _, out = dataset(csv)
    assert out["columns"] == ["a", "b"]
    assert out["rows"] == [[1, 2], [3, 4]]


# Phrase: "at least one header row and one data row"  (see AMBIGUITIES T17)
# Context: a trailing newline does not create a phantom empty row.
def test_trailing_newline_no_phantom_row(dataset):
    _, out = dataset("a,b\n1,2\n\n")
    assert out["rows"] == [[1, 2]]


# Phrase: "columns and each row follow source column order"  (see AMBIGUITIES T11)
# Context: chosen reading - short rows are padded, long rows truncated, to the header width.
def test_ragged_rows_normalised(dataset):
    _, out = dataset("a,b,c\n1,2\n1,2,3,4\n")
    assert out["columns"] == ["a", "b", "c"]
    assert out["rows"][0] == [1, 2, ""]
    assert out["rows"][1] == [1, 2, 3]


# Phrase: "`columns`" (see AMBIGUITIES T15)
# Context: chosen reading - header cells are passed through verbatim, whitespace-stripped.
def test_header_whitespace_and_duplicates(dataset):
    _, out = dataset(" a , b ,a\n1,2,3\n")
    assert out["columns"] == ["a", "b", "a"]
    assert out["rows"] == [[1, 2, 3]]
