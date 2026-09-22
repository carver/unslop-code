"""Spec section: Export, Upload, and Multi-Format Support -> Multi-Format Ingestion."""

import io
import zipfile

import pytest
from builders import make_xls, make_xlsx

TABLE = [["name", "age", "city"], ["ada", 36, "london"], ["grace", 45, "new york"]]
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture(params=["xlsx", "xls"])
def workbook(request):
    """Build a workbook in each supported spreadsheet format from `(title, rows)` pairs."""
    return make_xlsx if request.param == "xlsx" else make_xls


def rejected(client, origin, upload, payload):
    """Offer `payload` to both ingestion routes and return their status codes."""
    source = origin.serve("/payload.bin", payload, content_type="application/octet-stream")
    return (
        client.get("/convert", query_string={"source": source}).status_code,
        upload(payload).status_code,
    )


def ingested(client, dataset, upload, payload):
    """Convert `payload` and upload it, asserting the two routes agree on the table."""
    converted = client.get(dataset(payload, content_type="application/octet-stream"))
    uploaded = client.get(upload(payload).get_json()["endpoint"])

    assert converted.status_code == 200, converted.get_json()
    assert uploaded.get_json()["rows"] == converted.get_json()["rows"]
    return converted.get_json()


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
def test_both_routes_ingest_a_workbook(client, dataset, upload, workbook):
    body = ingested(client, dataset, upload, workbook([("Sheet1", TABLE)]))

    assert body["columns"] == ["name", "age", "city"]
    assert body["rows"] == [["ada", 36, "london"], ["grace", 45, "new york"]]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: CSV keeps working alongside the spreadsheet formats.
def test_csv_still_ingests_on_both_routes(client, dataset, upload):
    body = ingested(client, dataset, upload, b"name,age\nada,36\n")

    assert body["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: numeric cells are typed exactly as the CSV path types them; `.xls`
# stores whole numbers as doubles (AMBIGUITIES T43).
def test_workbook_numbers_become_json_numbers(client, dataset, upload, workbook):
    rows = [["n", "d", "t"], [36, 1.5, "ada"]]

    body = ingested(client, dataset, upload, workbook([("Sheet1", rows)]))

    assert body["rows"] == [[36, 1.5, "ada"]]


# Phrase: "Only the first worksheet is ingested."
def test_later_worksheets_are_ignored(client, dataset, upload, workbook):
    other = [["x", "y"], ["ignored", "ignored"]]

    body = ingested(client, dataset, upload, workbook([("First", TABLE), ("Second", other)]))

    assert body["columns"] == ["name", "age", "city"]
    assert body["total"] == 2


# Phrase: "Only the first worksheet is ingested."
# Context: worksheet order, not worksheet name, decides which sheet wins.
def test_first_sheet_wins_regardless_of_its_name(client, dataset, upload, workbook):
    sheets = [("zzz", TABLE), ("aaa", [["x", "y"], [1, 2]])]

    body = ingested(client, dataset, upload, workbook(sheets))

    assert body["columns"] == ["name", "age", "city"]


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
def test_header_only_worksheet_is_400(client, origin, upload, workbook):
    payload = workbook([("Sheet1", [["name", "age"]])])

    assert rejected(client, origin, upload, payload) == (400, 400)


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: an empty first sheet fails even when a later sheet is tabular
# (AMBIGUITIES T44).
def test_empty_first_sheet_is_400_despite_a_good_second(client, origin, upload, workbook):
    payload = workbook([("Empty", []), ("Data", TABLE)])

    assert rejected(client, origin, upload, payload) == (400, 400)


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: a single-column sheet is tabular; the CSV two-column rule is about
# delimiter inference and does not apply here (AMBIGUITIES T41).
def test_single_column_worksheet_is_tabular(client, dataset, upload, workbook):
    payload = workbook([("Sheet1", [["name"], ["ada"], ["grace"]])])

    body = ingested(client, dataset, upload, payload)

    assert body["columns"] == ["name"]
    assert body["rows"] == [["ada"], ["grace"]]


# Phrase: "`charset` applies only to text CSV sources."
# Context: the parameter is ignored, not rejected, for a workbook
# (AMBIGUITIES T40).
def test_charset_is_ignored_for_workbooks(client, origin, workbook):
    source = origin.serve("/book.bin", workbook([("Sheet1", TABLE)]), content_type="text/csv")

    response = client.get("/convert", query_string={"source": source, "charset": "utf-16"})

    assert response.status_code == 200
    endpoint = response.get_json()["endpoint"]
    assert client.get(endpoint).get_json()["columns"] == ["name", "age", "city"]


# Phrase: "`charset` applies only to text CSV sources."
# Context: it still decodes a text CSV source.
def test_charset_still_decodes_csv(client, origin):
    source = origin.serve("/data.csv", "name,city\nada,köln\n".encode("cp1252"))

    endpoint = client.get(
        "/convert", query_string={"source": source, "charset": "cp1252"}
    ).get_json()["endpoint"]

    assert client.get(endpoint).get_json()["rows"] == [["ada", "köln"]]


# Phrase: "Unrecognized format: `HTTP 400`."
def test_pdf_is_rejected_on_both_routes(client, origin, upload):
    assert rejected(client, origin, upload, PDF_BYTES) == (400, 400)


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: a zip archive that is not a workbook (AMBIGUITIES T45).
def test_plain_zip_archive_is_rejected(upload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")

    response = upload(buffer.getvalue())

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: random binary noise is not a table.
def test_binary_noise_is_rejected(upload):
    assert upload(bytes(range(256)) * 4).status_code == 400


# Phrase: "all errors use the standard JSON envelope"
def test_format_errors_use_the_envelope(upload, workbook):
    body = upload(workbook([("Sheet1", [["only-a-header"]])])).get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Phrase: "spreadsheet columns preserve source order."
def test_workbook_column_order_is_preserved(client, dataset, upload, workbook):
    rows = [["z", "m", "a"], [1, 2, 3]]

    body = ingested(client, dataset, upload, workbook([("Sheet1", rows)]))

    assert body["columns"] == ["z", "m", "a"]
    assert body["rows"] == [[1, 2, 3]]


# Phrase: "spreadsheet columns preserve source order."
# Context: the export of a workbook-backed dataset keeps that order too.
def test_workbook_export_keeps_column_order(client, upload, workbook):
    endpoint = upload(workbook([("Sheet1", [["z", "m", "a"], [1, 2, 3]])])).get_json()["endpoint"]

    response = client.get(endpoint + "/export")

    assert response.get_data(as_text=True).splitlines()[0] == "z,m,a"


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: a short row is padded to the header width, as the CSV path pads.
def test_short_workbook_rows_are_padded(client, dataset, upload, workbook):
    rows = [["a", "b", "c"], [1, 2, 3], [4]]

    body = ingested(client, dataset, upload, workbook([("Sheet1", rows)]))

    assert body["rows"] == [[1, 2, 3], [4, "", ""]]


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: trailing blank rows do not count as data rows (AMBIGUITIES T42).
def test_trailing_blank_rows_are_trimmed(client, dataset, upload, workbook):
    payload = workbook([("Sheet1", [["a", "b"], [1, 2], ["", ""], ["", ""]])])

    body = ingested(client, dataset, upload, payload)

    assert body["rows"] == [[1, 2]]
