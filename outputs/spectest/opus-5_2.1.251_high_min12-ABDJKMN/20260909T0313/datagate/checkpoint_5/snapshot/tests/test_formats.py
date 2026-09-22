"""Spec section: Multi-Format Ingestion."""

import csv
import io
import zipfile

import pytest

from conftest import build_xls, build_xlsx

TABLE = [["name", "age"], ["alice", 30], ["bob", 41]]


@pytest.fixture
def convert_bytes(client, origin):
    """Serve raw bytes from the origin and ingest them via /convert."""

    def _convert(path, body, content_type="application/octet-stream", params=None):
        origin.add(path, body, content_type=content_type)
        query = {"source": origin.url(path)}
        query.update(params or {})
        return client.get("/convert", query_string=query)

    return _convert


def payload_of(client, response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return client.get(response.get_json()["endpoint"]).get_json()


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: CSV via /convert is the pre-existing behaviour.
def test_convert_accepts_csv(convert_bytes):
    response = convert_bytes("/f-plain.csv", b"name,age\nalice,30\n",
                             content_type="text/csv")
    assert response.status_code == 200


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
def test_convert_accepts_xlsx(convert_bytes, client):
    response = convert_bytes("/f.xlsx", build_xlsx([("Sheet1", TABLE)]))
    assert payload_of(client, response)["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
def test_convert_accepts_xls(convert_bytes, client):
    response = convert_bytes("/f.xls", build_xls([("Sheet1", TABLE)]))
    assert payload_of(client, response)["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
def test_upload_accepts_xlsx(upload, client):
    response = upload(build_xlsx([("Sheet1", TABLE)]), filename="book.xlsx")
    assert payload_of(client, response)["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
def test_upload_accepts_xls(upload, client):
    response = upload(build_xls([("Sheet1", TABLE)]), filename="book.xls")
    assert payload_of(client, response)["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: the rows come through, not just the header.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_spreadsheet_rows_are_ingested(upload, client, build):
    payload = payload_of(client, upload(build([("S", TABLE)]), filename="b.xlsx"))
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Only the first worksheet is ingested."
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_only_first_worksheet_is_ingested(upload, client, build):
    book = build([
        ("First", TABLE),
        ("Second", [["other", "cols"], ["x", "y"]]),
    ])
    payload = payload_of(client, upload(book, filename="two.xlsx"))
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Only the first worksheet is ingested."
# Context: a broken second sheet cannot make the ingest fail.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_second_worksheet_being_empty_is_harmless(upload, client, build):
    book = build([("First", TABLE), ("Empty", [])])
    assert payload_of(client, upload(book, filename="two.xlsx"))["rows"] == [
        ["alice", 30], ["bob", 41]
    ]


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_header_only_first_sheet_is_400(upload, build):
    book = build([("First", [["name", "age"]])])
    response = upload(book, filename="hdr.xlsx")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_empty_first_sheet_is_400(upload, build):
    response = upload(build([("First", [])]), filename="empty.xlsx")
    assert response.status_code == 400


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: a data-bearing second sheet does not rescue an empty first sheet.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_empty_first_sheet_is_400_even_with_a_good_second(upload, build):
    response = upload(build([("First", []), ("Second", TABLE)]), filename="e.xlsx")
    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`."
def test_random_binary_is_400(upload):
    response = upload(bytes(range(256)) * 4, filename="blob.bin")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Unrecognized format: `HTTP 400`."
def test_pdf_is_400(upload):
    response = upload(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", filename="doc.pdf")
    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: a ZIP that is not an OOXML workbook is not an .xlsx.
def test_plain_zip_is_400(upload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    response = upload(buffer.getvalue(), filename="archive.zip")
    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: also on the /convert path, not just uploads.
def test_convert_unrecognized_format_is_400(convert_bytes):
    response = convert_bytes("/f.bin", b"\x89PNG\r\n\x1a\n" + bytes(64),
                             content_type="image/png")
    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: a truncated/corrupt xlsx is not ingestible.
def test_corrupt_xlsx_is_400(upload):
    book = build_xlsx([("First", TABLE)])
    response = upload(book[: len(book) // 2], filename="broken.xlsx")
    assert response.status_code == 400


# Phrase: "`charset` applies only to text CSV sources."
def test_charset_decodes_a_text_csv_source(client, origin):
    body = "name,city\nrené,köln\n".encode("cp1252")
    origin.add("/f-cs.csv", body, content_type="text/csv")
    response = client.get("/convert", query_string={
        "source": origin.url("/f-cs.csv"), "charset": "cp1252"})
    payload = client.get(response.get_json()["endpoint"]).get_json()
    assert payload["rows"] == [["rené", "köln"]]


# Phrase: "`charset` applies only to text CSV sources."
# Context: a charset supplied alongside a spreadsheet is ignored, not an error.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_charset_is_ignored_for_spreadsheets(client, origin, build):
    origin.add("/f-cs.xlsx", build([("S", TABLE)]),
               content_type="application/octet-stream")
    response = client.get("/convert", query_string={
        "source": origin.url("/f-cs.xlsx"), "charset": "cp1252"})
    assert response.status_code == 200
    payload = client.get(response.get_json()["endpoint"]).get_json()
    assert payload["columns"] == ["name", "age"]


# Phrase: "`charset` applies only to text CSV sources."
# Context: an unusable charset on a spreadsheet does not break ingestion, since
# the bytes are never decoded as text.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_utf16_charset_does_not_break_a_spreadsheet(client, origin, build):
    origin.add("/f-cs2.xlsx", build([("S", TABLE)]),
               content_type="application/octet-stream")
    response = client.get("/convert", query_string={
        "source": origin.url("/f-cs2.xlsx"), "charset": "utf-16"})
    assert response.status_code == 200


# Phrase: "spreadsheet columns preserve source order." (Determinism)
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_spreadsheet_columns_preserve_source_order(upload, client, build):
    book = build([("S", [["zeta", "alpha", "mid"], [1, 2, 3]])])
    payload = payload_of(client, upload(book, filename="order.xlsx"))
    assert payload["columns"] == ["zeta", "alpha", "mid"]
    assert payload["rows"] == [[1, 2, 3]]


# Phrase: "spreadsheet columns preserve source order." (Determinism)
# Context: repeated ingestion of the same workbook gives the same order.
def test_spreadsheet_order_is_stable_across_ingests(upload, client):
    book = build_xlsx([("S", [["c", "a", "b"], [1, 2, 3]])])
    first = payload_of(client, upload(book, filename="s.xlsx"))["columns"]
    second = payload_of(client, upload(book, filename="s.xlsx"))["columns"]
    assert first == second == ["c", "a", "b"]


# Phrase: "Integers/decimals are JSON numbers." (type inference, earlier section)
# Context: numeric spreadsheet cells arrive as JSON numbers, not strings.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_numeric_cells_are_json_numbers(upload, client, build):
    book = build([("S", [["n", "d"], [7, 2.5]])])
    payload = payload_of(client, upload(book, filename="num.xlsx"))
    assert payload["rows"] == [[7, 2.5]]


# Phrase: "The first sheet must be tabular (header + at least one data row)"
# Context: blank cells become empty strings rather than dropping the column.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_blank_cells_become_empty_strings(upload, client, build):
    book = build([("S", [["a", "b"], ["x", None]])])
    payload = payload_of(client, upload(book, filename="blank.xlsx"))
    assert payload["rows"] == [["x", ""]]


# Phrase: "Only the first worksheet is ingested."
# Context: spreadsheet datasets behave like CSV ones under the query surface.
def test_spreadsheet_dataset_filters_and_sorts(upload, client):
    book = build_xlsx([("S", [["name", "age"], ["alice", 30], ["bob", 41],
                              ["carol", 25]])])
    endpoint = upload(book, filename="q.xlsx").get_json()["endpoint"]
    response = client.get(endpoint, query_string={"age__greater": "26",
                                                  "_sort_desc": "age"})
    assert [row[0] for row in response.get_json()["rows"]] == ["bob", "alice"]


# Phrase: "export columns follow source column order." (Determinism)
# Context: exporting a spreadsheet-sourced dataset yields the sheet's order.
def test_spreadsheet_export_preserves_column_order(upload, client):
    book = build_xlsx([("S", [["z", "a"], [1, 2]])])
    endpoint = upload(book, filename="x.xlsx").get_json()["endpoint"]
    response = client.get(endpoint + "/export")
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True), newline="")))
    assert rows[0] == ["z", "a"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: format is decided by the bytes, so a misleading content type or file
# name does not prevent a real workbook from being ingested.
def test_xlsx_served_as_application_zip_is_accepted(convert_bytes, client):
    response = convert_bytes("/f-zip", build_xlsx([("S", TABLE)]),
                             content_type="application/zip")
    assert payload_of(client, response)["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: a CSV named .xlsx is still a CSV by its bytes.
def test_csv_bytes_named_xlsx_are_ingested_as_csv(upload, client):
    payload = payload_of(client, upload(b"name,age\nalice,30\n", filename="lie.xlsx"))
    assert payload["columns"] == ["name", "age"]


# Phrase: "Formula/computed-cell behavior is not required."
# Context: a workbook containing a formula must not crash the ingest; whatever
# the cell resolves to, the request succeeds.
def test_workbook_with_a_formula_still_ingests(upload, client):
    book = build_xlsx([("S", [["a", "b"], [1, "=A2+1"]])])
    response = upload(book, filename="formula.xlsx")
    assert response.status_code == 200
    assert payload_of(client, response)["columns"] == ["a", "b"]


# Phrase: "Only the first worksheet is ingested."
# Context: a single-column sheet has a header and a data row, so it is tabular
# even though single-column CSV text is rejected for want of a delimiter.
@pytest.mark.parametrize("build", [build_xlsx, build_xls])
def test_single_column_sheet_is_tabular(upload, client, build):
    book = build([("S", [["only"], ["a"], ["b"]])])
    payload = payload_of(client, upload(book, filename="one.xlsx"))
    assert payload["columns"] == ["only"]
    assert payload["rows"] == [["a"], ["b"]]


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: holds for spreadsheet bytes as well as CSV bytes.
def test_same_workbook_bytes_same_id(upload):
    book = build_xlsx([("S", TABLE)])
    assert (upload(book, filename="a.xlsx").get_json()["endpoint"]
            == upload(book, filename="b.xlsx").get_json()["endpoint"])
