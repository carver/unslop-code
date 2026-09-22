"""Spec section: Export, Upload, and Multi-Format Support -- Multi-Format Ingestion."""

import datetime
import io
import zipfile

from conftest import SIMPLE_SHEET, xls_bytes, xlsx_bytes

XLSX_URL = "https://example.test/book.xlsx"
XLS_URL = "https://example.test/book.xls"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_TYPE = "application/vnd.ms-excel"


# Phrase: "`/convert` ... accept[s] CSV" (context: unchanged by multi-format support)
def test_convert_still_accepts_csv(dataset):
    assert dataset("name,age\nada,36\n")["columns"] == ["name", "age"]


# Phrase: "`/convert` ... accept[s] ... `.xlsx`"
def test_convert_accepts_xlsx(dataset):
    body = dataset(xlsx_bytes(SIMPLE_SHEET), url=XLSX_URL, content_type=XLSX_TYPE)

    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`/convert` ... accept[s] ... `.xls`"
def test_convert_accepts_xls(dataset):
    body = dataset(xls_bytes(SIMPLE_SHEET), url=XLS_URL, content_type=XLS_TYPE)

    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`/upload` accept[s] ... `.xlsx`"
def test_upload_accepts_xlsx(uploaded):
    body = uploaded(xlsx_bytes(SIMPLE_SHEET), filename="book.xlsx")

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`/upload` accept[s] ... `.xls`"
def test_upload_accepts_xls(uploaded):
    body = uploaded(xls_bytes(SIMPLE_SHEET), filename="book.xls")

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Only the first worksheet is ingested."
def test_only_the_first_worksheet_is_ingested(uploaded):
    sheets = {"first": [["a"], [1]], "second": [["b"], [2]]}

    body = uploaded(xlsx_bytes(sheets), filename="book.xlsx")

    assert body["columns"] == ["a"]
    assert body["rows"] == [[1]]


# Phrase: "Only the first worksheet is ingested." (context: `.xls`)
def test_only_the_first_xls_worksheet_is_ingested(uploaded):
    sheets = {"first": [["a"], [1]], "second": [["b"], [2]]}

    body = uploaded(xls_bytes(sheets), filename="book.xls")

    assert body["columns"] == ["a"]


# Phrase: "Only the first worksheet is ingested." (context: first in tab order, not the active sheet, T47)
def test_the_first_sheet_wins_over_the_active_sheet(uploaded):
    data = xlsx_bytes({"first": [["a"], [1]], "second": [["b"], [2]]}, active=1)

    assert uploaded(data, filename="book.xlsx")["columns"] == ["a"]


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
def test_a_header_only_sheet_is_400(upload):
    response = upload(xlsx_bytes({"s": [["name", "age"]]}), filename="book.xlsx")

    assert response.status_code == 400


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`." (context: empty sheet)
def test_an_empty_sheet_is_400(upload):
    response = upload(xlsx_bytes({"s": []}), filename="book.xlsx")

    assert response.status_code == 400


# Phrase: "The first sheet must be tabular ... or `HTTP 400`." (context: only the first sheet is judged)
def test_a_tabular_second_sheet_does_not_rescue_the_first(upload):
    sheets = {"first": [["a"]], "second": [["b"], [2]]}

    response = upload(xlsx_bytes(sheets), filename="book.xlsx")

    assert response.status_code == 400


# Phrase: "`charset` applies and validates only for text CSV sources." (context: ignored for `.xlsx`, T41)
def test_charset_is_ignored_for_xlsx(upload):
    response = upload(xlsx_bytes(SIMPLE_SHEET), filename="book.xlsx", query={"charset": "not-an-encoding"})

    assert response.status_code == 200


# Phrase: "`charset` applies and validates only for text CSV sources." (context: ignored for `.xls`)
def test_charset_is_ignored_for_xls(upload):
    response = upload(xls_bytes(SIMPLE_SHEET), filename="book.xls", query={"charset": "utf-32"})

    assert response.status_code == 200


# Phrase: "`charset` applies and validates only for text CSV sources." (context: enforced for CSV)
def test_charset_is_enforced_for_csv(upload):
    response = upload(b"name\nada\n", query={"charset": "bogus-codec"})

    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`."
def test_a_pdf_is_400(upload):
    response = upload(b"%PDF-1.7\nnot a table", filename="doc.pdf")

    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`." (context: a zip container that is not a workbook)
def test_a_non_workbook_zip_is_400(upload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")

    response = upload(buffer.getvalue(), filename="archive.zip")

    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`." (context: an OLE2 document that is not a workbook)
def test_a_non_workbook_ole_document_is_400(upload):
    response = upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512, filename="doc.doc")

    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`." (context: JSON)
def test_a_json_payload_is_400(upload):
    response = upload(b'{"rows": [1, 2]}', filename="data.json")

    assert response.status_code == 400


# Phrase: "Unrecognized format: `HTTP 400`." (context: the envelope)
def test_an_unrecognized_format_uses_the_envelope(upload):
    body = upload(b"%PDF-1.7\nnope", filename="doc.pdf").get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str)


# Phrase: "spreadsheet columns preserve source order."
def test_spreadsheet_columns_preserve_source_order(uploaded):
    body = uploaded(xlsx_bytes({"s": [["z", "a", "m"], [1, 2, 3]]}), filename="book.xlsx")

    assert body["columns"] == ["z", "a", "m"]
    assert body["rows"] == [[1, 2, 3]]


# Phrase: "spreadsheet columns preserve source order." (context: exporting a workbook, T35/T36)
def test_exporting_a_workbook_keeps_column_order(client, upload):
    endpoint = upload(xlsx_bytes({"s": [["z", "a"], [1, 2]]}), filename="book.xlsx").get_json()["endpoint"]

    response = client.get(endpoint + "/export")

    assert response.get_data(as_text=True).splitlines()[0] == "z,a"


# Phrase: "`/convert` and `/upload` accept ... `.xls`" (context: whole numbers are integers, T44)
def test_xls_whole_numbers_are_integers(uploaded):
    body = uploaded(xls_bytes({"s": [["n", "d"], [36, 2.5]]}), filename="book.xls")

    assert body["rows"] == [[36, 2.5]]


# Phrase: "`/convert` and `/upload` accept ... `.xlsx`" (context: dates become ISO text, T44)
def test_spreadsheet_dates_become_iso_text(uploaded):
    sheets = {"s": [["when"], [datetime.date(2020, 1, 2)], [datetime.datetime(2021, 3, 4, 5, 6, 7)]]}

    body = uploaded(xlsx_bytes(sheets), filename="book.xlsx")

    assert body["rows"] == [["2020-01-02"], ["2021-03-04T05:06:07"]]


# Phrase: "`/convert` and `/upload` accept ... `.xlsx`" (context: booleans and blanks, T44)
def test_spreadsheet_booleans_and_blanks(uploaded):
    body = uploaded(xlsx_bytes({"s": [["flag", "gap"], [True, None], [False, None]]}), filename="book.xlsx")

    assert body["rows"] == [["TRUE", ""], ["FALSE", ""]]


# Phrase: "The first sheet must be tabular" (context: blank rows are dropped but keep their row number, T45/T46)
def test_blank_sheet_rows_are_dropped_and_still_consume_a_rowid(uploaded):
    sheets = {"s": [["a"], [None], [1]]}

    body = uploaded(xlsx_bytes(sheets), filename="book.xlsx", dataset_query="?_shape=objects")

    assert body["rows"] == [{"rowid": 3, "a": 1}]


# Phrase: "spreadsheet columns preserve source order." (context: short rows pad to the header, T45)
def test_short_spreadsheet_rows_pad_to_the_header(uploaded):
    body = uploaded(xlsx_bytes({"s": [["a", "b"], [1]]}), filename="book.xlsx")

    assert body["rows"] == [[1, ""]]


# Phrase: "`/convert` and `/upload` accept CSV" (context: a CSV uploaded under a spreadsheet name, T42)
def test_format_comes_from_the_bytes_not_the_name(uploaded):
    body = uploaded(b"name,age\nada,36\n", filename="mislabelled.xlsx")

    assert body["columns"] == ["name", "age"]


# Phrase: "`/convert` and `/upload` accept ... `.xlsx`" (context: an extensionless URL, T42)
def test_convert_detects_a_workbook_without_an_extension(dataset):
    body = dataset(xlsx_bytes(SIMPLE_SHEET), url="https://example.test/download", content_type=XLSX_TYPE)

    assert body["columns"] == ["name", "age"]


# Phrase: "Re-uploading the same file bytes yields the same dataset id." (context: workbooks)
def test_re_uploading_a_workbook_yields_the_same_id(upload):
    data = xlsx_bytes(SIMPLE_SHEET)

    first = upload(data, filename="book.xlsx").get_json()["endpoint"]
    second = upload(data, filename="book.xlsx").get_json()["endpoint"]

    assert first == second
