"""Spec section: Multi-Format Ingestion (CSV, .xls, .xlsx)."""
import pytest

from conftest import csv_rows, xls_bytes, xlsx_bytes, zip_bytes

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME = "application/vnd.ms-excel"
TABLE = [["name", "qty"], ["widget", 3], ["gadget", 10]]


@pytest.fixture()
def convert_bytes(client, convert, origin):
    """Serve raw bytes over HTTP, /convert them, return (status, payload)."""

    def _convert_bytes(body, content_type="application/octet-stream", charset=None):
        return convert(source=origin.add(body, content_type=content_type),
                       charset=charset)

    return _convert_bytes


@pytest.fixture()
def rows_of(client):
    def _rows_of(payload):
        body = client.get(payload["endpoint"]).get_json()
        return body["columns"], body["rows"]

    return _rows_of


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: an .xlsx workbook uploaded through /upload is ingested.
def test_upload_accepts_xlsx(upload, rows_of):
    status, payload = upload(body=xlsx_bytes(TABLE), filename="book.xlsx")
    assert status == 200, payload
    assert rows_of(payload) == (["name", "qty"], [["widget", 3], ["gadget", 10]])


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: an .xls workbook uploaded through /upload is ingested.
def test_upload_accepts_xls(upload, rows_of):
    status, payload = upload(body=xls_bytes(TABLE), filename="book.xls")
    assert status == 200, payload
    assert rows_of(payload) == (["name", "qty"], [["widget", 3], ["gadget", 10]])


# Phrase: "`/convert` ... accept[s] CSV, `.xls`, and `.xlsx`."
# Context: a remote .xlsx source is ingested by /convert.
def test_convert_accepts_xlsx(convert_bytes, rows_of):
    status, payload = convert_bytes(xlsx_bytes(TABLE), content_type=XLSX_MIME)
    assert status == 200, payload
    assert rows_of(payload) == (["name", "qty"], [["widget", 3], ["gadget", 10]])


# Phrase: "`/convert` ... accept[s] CSV, `.xls`, and `.xlsx`."
# Context: a remote .xls source is ingested by /convert.
def test_convert_accepts_xls(convert_bytes, rows_of):
    status, payload = convert_bytes(xls_bytes(TABLE), content_type=XLS_MIME)
    assert status == 200, payload
    assert rows_of(payload) == (["name", "qty"], [["widget", 3], ["gadget", 10]])


# Phrase: "`/convert` and `/upload` accept CSV, ..."
# Context: plain CSV keeps working through /upload alongside the new formats.
def test_upload_still_accepts_csv(upload, rows_of):
    status, payload = upload(body=b"name,qty\nwidget,3\n")
    assert status == 200, payload
    assert rows_of(payload) == (["name", "qty"], [["widget", 3]])


# Phrase: "Only the first worksheet is ingested."
# Context: a second sheet's columns and rows never appear.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_only_first_worksheet_xlsx(upload, rows_of, build):
    body = build(TABLE, extra_sheets=[("Second", [["x", "y"], [1, 2], [3, 4]])])
    status, payload = upload(body=body, filename="book.xlsx")
    assert status == 200, payload
    columns, rows = rows_of(payload)
    assert columns == ["name", "qty"]
    assert rows == [["widget", 3], ["gadget", 10]]


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: the first sheet is empty even though a later sheet is tabular.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_empty_first_sheet_is_400(upload, build):
    body = build([], extra_sheets=[("Second", TABLE)])
    status, payload = upload(body=body, filename="book.xlsx")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: a header row with no data rows under it.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_header_only_sheet_is_400(upload, build):
    status, payload = upload(body=build([["name", "qty"]]), filename="book.xlsx")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "spreadsheet columns preserve source order." (Determinism)
# Context: column order is the sheet's left-to-right order.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_spreadsheet_column_order(upload, rows_of, build):
    body = build([["zeta", "alpha", "mid"], [1, 2, 3]])
    status, payload = upload(body=body, filename="book.xlsx")
    assert status == 200, payload
    columns, rows = rows_of(payload)
    assert columns == ["zeta", "alpha", "mid"]
    assert rows == [[1, 2, 3]]


# Phrase: "export columns follow source column order." (Determinism)
# Context: exporting a spreadsheet-sourced dataset keeps the sheet's order.
def test_export_of_spreadsheet_keeps_order(client, upload):
    _, payload = upload(body=xlsx_bytes([["zeta", "alpha"], [1, 2]]),
                        filename="book.xlsx")
    resp = client.get(payload["endpoint"] + "/export")
    assert resp.status_code == 200
    assert csv_rows(resp) == [["zeta", "alpha"], ["1", "2"]]


# Phrase: "accept CSV, `.xls`, and `.xlsx`." (cell typing, see AMBIGUITIES T48)
# Context: numeric cells arrive as JSON numbers, text cells as strings.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_spreadsheet_cell_types(upload, rows_of, build):
    body = build([["s", "i", "f"], ["text", 7, 2.5]])
    status, payload = upload(body=body, filename="book.xlsx")
    assert status == 200, payload
    _, rows = rows_of(payload)
    assert rows == [["text", 7, 2.5]]


# Phrase: "accept CSV, `.xls`, and `.xlsx`." (see AMBIGUITIES T49)
# Context: a short data row is padded to the header width.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_spreadsheet_short_row_padded(upload, rows_of, build):
    body = build([["a", "b", "c"], [1, 2, 3], [4]])
    status, payload = upload(body=body, filename="book.xlsx")
    assert status == 200, payload
    _, rows = rows_of(payload)
    assert [len(r) for r in rows] == [3, 3]
    assert rows[1][0] == 4


# Phrase: "The first sheet must be tabular" (see AMBIGUITIES T49)
# Context: trailing blank rows do not become rows of empty cells.
def test_trailing_blank_rows_ignored(upload, rows_of):
    import openpyxl, io as _io

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["a", "b"])
    sheet.append([1, 2])
    sheet["A9"] = None
    buffer = _io.BytesIO()
    book.save(buffer)
    status, payload = upload(body=buffer.getvalue(), filename="book.xlsx")
    assert status == 200, payload
    _, rows = rows_of(payload)
    assert rows == [[1, 2]]


# Phrase: "`charset` applies and validates only for text CSV sources."
# Context: a bogus charset is ignored for an .xlsx upload.
def test_charset_ignored_for_xlsx_upload(upload):
    status, payload = upload(body=xlsx_bytes(TABLE), filename="b.xlsx",
                             charset="klingon")
    assert status == 200, payload


# Phrase: "`charset` applies and validates only for text CSV sources."
# Context: a bogus charset is ignored for an .xls upload.
def test_charset_ignored_for_xls_upload(upload):
    status, payload = upload(body=xls_bytes(TABLE), filename="b.xls",
                             charset="klingon")
    assert status == 200, payload


# Phrase: "`charset` applies and validates only for text CSV sources."
# Context: the same rule holds for a spreadsheet fetched by /convert.
def test_charset_ignored_for_xlsx_convert(convert_bytes):
    status, payload = convert_bytes(xlsx_bytes(TABLE), content_type=XLSX_MIME,
                                    charset="klingon")
    assert status == 200, payload


# Phrase: "`charset` applies and validates only for text CSV sources."
# Context: a valid-but-wrong charset does not corrupt spreadsheet cells.
def test_charset_does_not_decode_spreadsheet(upload, rows_of):
    status, payload = upload(body=xlsx_bytes([["name"], ["café"]]),
                             filename="b.xlsx", charset="latin-1")
    assert status == 200, payload
    _, rows = rows_of(payload)
    assert rows == [["café"]]


# Phrase: "`charset` applies ... for text CSV sources."
# Context: the charset still applies (and still validates) for CSV uploads.
def test_charset_still_applies_to_csv_upload(upload, rows_of):
    status, payload = upload(body="a\ncafé\n".encode("cp1252"), charset="cp1252")
    assert status == 200, payload
    assert rows_of(payload)[1] == [["café"]]


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: a PNG is neither CSV nor a workbook.
def test_png_is_400(upload):
    blob = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + bytes(range(64))
    status, payload = upload(body=blob, filename="x.png")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: a zip archive that is not a workbook.
def test_plain_zip_is_400(upload):
    status, payload = upload(body=zip_bytes({"readme.txt": b"hello"}),
                             filename="x.zip")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: a PDF header followed by binary noise.
def test_pdf_is_400(upload):
    status, payload = upload(body=b"%PDF-1.7\n\x00\x01\x02binary\x00stuff",
                             filename="x.pdf")
    assert status == 400, payload


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: the same rule applies to a remote source through /convert.
def test_unrecognised_format_via_convert_is_400(convert_bytes):
    status, payload = convert_bytes(zip_bytes({"a.txt": b"hi"}),
                                    content_type="application/zip")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "all errors use the standard JSON envelope"
# Context: format errors are JSON envelopes like every other error.
def test_format_error_envelope(upload):
    status, payload = upload(body=b"\x00\x01\x02\x03", filename="x.bin")
    assert status == 400
    assert payload["ok"] is False and isinstance(payload["error"], str)


# Phrase: "Formula/computed-cell behavior is not required."
# Context: a sheet containing a formula must still ingest without erroring.
def test_formula_cells_do_not_break_ingestion(upload, rows_of):
    body = xlsx_bytes([["a", "b"], [1, "=A2+1"]])
    status, payload = upload(body=body, filename="book.xlsx")
    assert status == 200, payload
    columns, rows = rows_of(payload)
    assert columns == ["a", "b"] and len(rows) == 1


# Phrase: "accept CSV, `.xls`, and `.xlsx`."
# Context: spreadsheet datasets support the same query controls as CSV ones.
def test_spreadsheet_dataset_supports_controls(client, upload):
    body = xlsx_bytes([["name", "qty"], ["a", 5], ["b", 1], ["c", 9]])
    _, payload = upload(body=body, filename="book.xlsx")
    resp = client.get(payload["endpoint"],
                      query_string={"_sort": "qty", "_size": "2"})
    assert resp.status_code == 200
    assert resp.get_json()["rows"] == [["b", 1], ["a", 5]]


# Phrase: "accept CSV, `.xls`, and `.xlsx`."
# Context: spreadsheet header cells become column names as written.
@pytest.mark.parametrize("build", [xlsx_bytes, xls_bytes])
def test_spreadsheet_numeric_header_becomes_column_name(upload, rows_of, build):
    status, payload = upload(body=build([["id", 2024], ["x", 1]]),
                             filename="book.xlsx")
    assert status == 200, payload
    columns, _ = rows_of(payload)
    assert columns[0] == "id"
    assert len(columns) == 2
