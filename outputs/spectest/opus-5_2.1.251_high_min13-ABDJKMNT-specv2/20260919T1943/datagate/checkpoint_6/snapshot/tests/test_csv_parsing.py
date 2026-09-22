"""Spec section: CSV Parsing."""

import codecs


# Phrase: "If /convert receives `charset`, use it to decode bytes."
def test_given_charset_decodes_bytes(client, serve):
    source = serve("name\ncafé\n".encode("latin-1"))

    endpoint = client.get("/convert", query_string={"source": source, "charset": "latin-1"}).get_json()["endpoint"]

    assert client.get(endpoint).get_json()["rows"] == [["café"]]


# Phrase: "Otherwise detect encoding." (context: unambiguous UTF-8 content)
def test_utf8_is_detected_without_a_charset(dataset):
    body = dataset("name,city\nzoë,münchen\n".encode("utf-8"))

    assert body["rows"] == [["zoë", "münchen"]]


# Phrase: "Otherwise detect encoding." (context: a UTF-8 BOM is unambiguous)
def test_utf8_bom_is_detected_and_stripped(dataset):
    body = dataset(codecs.BOM_UTF8 + "name,city\nada,london\n".encode("utf-8"))

    assert body["columns"] == ["name", "city"]


# Phrase: "detect unambiguous encoding from content, else latin-1"
def test_undetectable_bytes_fall_back_to_latin_1(dataset):
    body = dataset("name\nrésumé\n".encode("latin-1"))

    assert body["rows"] == [["résumé"]]


# Phrase: "Delimiter must be inferred from input ... minimum supported delimiters are `,`, `;`, and `\t`."
def test_comma_delimiter_is_inferred(dataset):
    assert dataset("a,b\n1,2\n")["columns"] == ["a", "b"]


def test_semicolon_delimiter_is_inferred(dataset):
    body = dataset("a;b;c\n1;2;3\n")

    assert body["columns"] == ["a", "b", "c"]
    assert body["rows"] == [[1, 2, 3]]


def test_tab_delimiter_is_inferred(dataset):
    body = dataset("a\tb\tc\n1\t2\t3\n")

    assert body["columns"] == ["a", "b", "c"]
    assert body["rows"] == [[1, 2, 3]]


# Phrase: "Delimiter must be inferred from input, if present" (context: T4 — a single column has none)
def test_single_column_file_is_still_a_table(dataset):
    body = dataset("name\nada\ngrace\n")

    assert body["columns"] == ["name"]
    assert body["rows"] == [["ada"], ["grace"]]


# Phrase: "Delimiter must be inferred from input" (context: text cells containing other delimiters)
def test_inference_prefers_the_consistent_delimiter(dataset):
    body = dataset("name;note\nada;a, b, c\ngrace;x, y\n")

    assert body["columns"] == ["name", "note"]
    assert body["rows"] == [["ada", "a, b, c"], ["grace", "x, y"]]


# Phrase (context: standard CSV quoting must survive delimiter inference)
def test_quoted_fields_keep_embedded_delimiters(dataset):
    body = dataset('a,b\n"x,y",2\n')

    assert body["rows"] == [["x,y", 2]]


# Phrase: "A valid file requires at least one header row and one data row."
def test_header_only_file_is_rejected(client, serve):
    response = client.get("/convert", query_string={"source": serve("a,b,c\n")})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "at least one header row and one data row" (context: blank lines are not data rows)
def test_header_plus_blank_lines_is_rejected(client, serve):
    assert client.get("/convert", query_string={"source": serve("a,b\n\n\n")}).status_code == 400


# Phrase: "at least one header row and one data row" (context: the minimum valid file)
def test_one_header_and_one_data_row_is_enough(dataset):
    body = dataset("a,b\n1,2\n")

    assert body["columns"] == ["a", "b"]
    assert body["rows"] == [[1, 2]]
