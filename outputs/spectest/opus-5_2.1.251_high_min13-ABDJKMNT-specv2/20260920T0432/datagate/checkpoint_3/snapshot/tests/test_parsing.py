"""CSV parsing: encoding resolution, delimiter inference, table shape."""


# Spec: "If /convert receives `charset`, use it to decode bytes."
# Context: the same bytes read under two different charsets give different text.
def test_supplied_charset_wins_over_detection(dataset):
    body = b"city,note\nmalmo,smart\x93quote\n"
    assert dataset(body, params={"charset": "cp1252"})["rows"][0][1] == "smart\u201cquote"
    assert dataset(body, params={"charset": "latin-1"})["rows"][0][1] == "smart\x93quote"


# Spec: "Otherwise detect encoding." / "detect unambiguous encoding from content"
# Context: a UTF-8 body with multi-byte characters and no charset parameter.
def test_utf8_is_detected_without_charset(dataset):
    payload = dataset("city,note\nmalmö,naïve café\n".encode("utf-8"))
    assert payload["rows"] == [["malmö", "naïve café"]]


# Spec: "detect unambiguous encoding from content, else latin-1"
# Context: bytes that are not valid UTF-8 fall back to latin-1 (AMBIGUITIES T3).
def test_latin1_fallback_for_undetectable_bytes(dataset):
    payload = dataset("city,note\nmalm\xf6,caf\xe9\n".encode("latin-1"))
    assert payload["rows"] == [["malmö", "café"]]


# Spec: "detect unambiguous encoding from content"
# Context: a UTF-8 byte-order mark is not part of the first column name.
def test_utf8_bom_is_stripped(dataset):
    payload = dataset("﻿name,age\nada,36\n".encode("utf-8-sig"))
    assert payload["columns"] == ["name", "age"]


# Spec: "Delimiter must be inferred from input ... minimum supported delimiters
# are `,`, `;`, and `\t`."
# Context: each supported delimiter, inferred without any hint from the caller.
def test_supported_delimiters_are_inferred(dataset):
    for delimiter in (",", ";", "\t"):
        body = f"name{delimiter}age\nada{delimiter}36\n"
        payload = dataset(body)
        assert payload["columns"] == ["name", "age"], delimiter
        assert payload["rows"] == [["ada", 36]], delimiter


# Spec: "Delimiter must be inferred from input"
# Context: a semicolon file whose text fields contain commas must not be split
# on the comma.
def test_delimiter_inference_prefers_the_consistent_candidate(dataset):
    payload = dataset("name;note\nada;one, two, three\ngrace;four, five\n")
    assert payload["columns"] == ["name", "note"]
    assert payload["rows"][0] == ["ada", "one, two, three"]


# Spec: standard CSV quoting.
# Context: quoted fields may contain the delimiter and embedded newlines.
def test_quoted_fields_are_unquoted(dataset):
    payload = dataset('name,note\n"ada","hello, world"\n"grace","line1\nline2"\n')
    assert payload["rows"] == [["ada", "hello, world"], ["grace", "line1\nline2"]]


# Spec: "The endpoint returns stored rows and columns, in source order."
# Context: rows shorter or longer than the header are squared off
# (AMBIGUITIES T7).
def test_ragged_rows_are_padded_and_truncated(dataset):
    payload = dataset("a,b,c\n1,2\n4,5,6,7\n")
    assert payload["rows"] == [[1, 2, ""], [4, 5, 6]]


# Spec: "A valid file requires at least one header row and one data row."
# Context: blank lines are not data rows.
def test_blank_lines_are_ignored(dataset):
    payload = dataset("name,age\n\nada,36\n\n")
    assert payload["rows"] == [["ada", 36]]


# Spec: "A valid file requires at least one header row and one data row."
# Context: a file whose only content is blank lines after the header is invalid.
def test_only_blank_lines_after_header_is_400(convert):
    assert convert("name,age\n\n\n").status_code == 400


# Spec: "Delimiter must be inferred from input" / "| Non-tabular content | 400 |"
# Context: CRLF line endings are normal CSV, not a parsing failure.
def test_crlf_line_endings_are_supported(dataset):
    payload = dataset("name,age\r\nada,36\r\ngrace,45\r\n")
    assert payload["rows"] == [["ada", 36], ["grace", 45]]
