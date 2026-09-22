"""Spec section: CSV Parsing."""

from tests.conftest import SIMPLE_CSV


# Phrase: "Delimiter must be inferred from input; minimum supported delimiters
# are `,`, `;`, and `\t`."
def test_comma_delimiter(dataset):
    payload = dataset("name,age\nada,36\n")
    assert payload["columns"] == ["name", "age"] and payload["rows"] == [["ada", 36]]


def test_semicolon_delimiter(dataset):
    payload = dataset("name;age\nada;36\ngrace;45\n")
    assert payload["columns"] == ["name", "age"] and payload["rows"] == [["ada", 36], ["grace", 45]]


def test_tab_delimiter(dataset):
    payload = dataset("name\tage\nada\t36\ngrace\t45\n")
    assert payload["columns"] == ["name", "age"] and payload["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Delimiter must be inferred from input" - the delimiter is picked from
# structure, not from a stray character in the text.
def test_delimiter_choice_prefers_consistent_structure(dataset):
    body = "name;note\nada;a, b, c\ngrace;d, e, f\n"
    payload = dataset(body)
    assert payload["columns"] == ["name", "note"]
    assert payload["rows"] == [["ada", "a, b, c"], ["grace", "d, e, f"]]


# Phrase: "Delimiter must be inferred from input" - quoted fields keep embedded
# delimiters and newlines.
def test_quoted_fields_are_respected(dataset):
    payload = dataset('name,note\n"ada","lovelace, augusta"\n"grace","hopper"\n')
    assert payload["rows"] == [["ada", "lovelace, augusta"], ["grace", "hopper"]]


# Phrase: "A valid file requires at least one header row and one data row."
def test_one_header_and_one_data_row_is_enough(convert):
    assert convert("a,b\n1,2\n").status_code == 200


# Phrase: "A valid file requires at least one header row and one data row." -
# blank lines do not count as data rows.
def test_blank_lines_are_ignored(dataset):
    payload = dataset("a,b\n\n1,2\n\n3,4\n\n")
    assert payload["rows"] == [[1, 2], [3, 4]]


# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
def test_explicit_charset_decodes_bytes(dataset):
    payload = dataset("name,city\nrené,münchen\n".encode("latin-1"), query="&charset=latin-1")
    assert payload["rows"] == [["rené", "münchen"]]


# Phrase: "If `/convert` receives `charset`, use it..." - aliases are accepted.
def test_charset_aliases_are_accepted(dataset):
    payload = dataset("name,city\ncafé,paris\n".encode("cp1252"), query="&charset=windows-1252")
    assert payload["rows"] == [["café", "paris"]]


# Phrase: "Otherwise detect encoding."
def test_encoding_is_detected_for_utf8(dataset):
    payload = dataset("name,city\nrené,münchen\nzoë,kraków\n".encode("utf-8"))
    assert payload["rows"] == [["rené", "münchen"], ["zoë", "kraków"]]


# Phrase: "Otherwise detect encoding." - non-UTF-8 bytes are detected too.
def test_encoding_is_detected_for_utf16(dataset):
    body = "name,city\nrene,munich\ngrace,york\n".encode("utf-16")
    payload = dataset(body, content_type="application/octet-stream")
    assert payload["columns"] == ["name", "city"]
    assert payload["rows"] == [["rene", "munich"], ["grace", "york"]]


# Phrase: "Otherwise detect encoding." - a UTF-8 BOM is not part of the header.
def test_utf8_bom_is_stripped(dataset):
    assert dataset(SIMPLE_CSV.encode("utf-8-sig"))["columns"] == ["name", "age"]


# Phrase: "Otherwise detect encoding." - explicit charset also strips the BOM.
def test_explicit_utf8_sig_charset(dataset):
    assert dataset(SIMPLE_CSV.encode("utf-8-sig"), query="&charset=utf-8")["columns"] == ["name", "age"]


# Phrase: "CSV Parsing" - CRLF line endings parse like LF (no clock/locale/format
# dependence beyond what the spec allows).
def test_crlf_line_endings(dataset):
    payload = dataset("name,age\r\nada,36\r\ngrace,45\r\n")
    assert payload["columns"] == ["name", "age"] and payload["rows"] == [["ada", 36], ["grace", 45]]
