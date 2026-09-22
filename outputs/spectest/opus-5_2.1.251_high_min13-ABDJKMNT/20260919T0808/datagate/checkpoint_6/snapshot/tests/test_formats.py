"""Spec section: Export, Upload, and Multi-Format Support - Multi-Format Ingestion."""

import io
import zipfile

from tests.conftest import (
    SIMPLE_CSV,
    TEAMS_SHEET,
    exported_rows,
    xls_bytes,
    xlsx_bytes,
)

SECOND_SHEET = [["ignored", "columns"], ["never", "read"]]


# Phrase: "`/convert` and `/upload` accept CSV"
def test_convert_accepts_csv(dataset):
    assert dataset(SIMPLE_CSV)["columns"] == ["name", "age"]


# Phrase: "`/convert` ... accept ... `.xlsx`"
def test_convert_accepts_xlsx(dataset):
    payload = dataset(xlsx_bytes(TEAMS_SHEET), path="/teams.xlsx")
    assert payload["columns"] == ["name", "team", "age"]
    assert payload["rows"] == [
        ["ada", "blue", 36],
        ["grace", "red", 45],
        ["alan", "blue", 41],
        ["edsger", "red", 30],
    ]


# Phrase: "`/convert` ... accept ... `.xls`"
def test_convert_accepts_xls(dataset):
    payload = dataset(xls_bytes(TEAMS_SHEET), path="/teams.xls")
    assert payload["columns"] == ["name", "team", "age"]
    assert payload["rows"] == [
        ["ada", "blue", 36],
        ["grace", "red", 45],
        ["alan", "blue", 41],
        ["edsger", "red", 30],
    ]


# Phrase: "Only the first worksheet is ingested." - xlsx.
def test_only_the_first_worksheet_of_an_xlsx_is_ingested(dataset):
    payload = dataset(xlsx_bytes(TEAMS_SHEET, SECOND_SHEET), path="/two-sheets.xlsx")
    assert payload["columns"] == ["name", "team", "age"]
    assert payload["total"] == 4


# Phrase: "Only the first worksheet is ingested." - xls.
def test_only_the_first_worksheet_of_an_xls_is_ingested(dataset):
    payload = dataset(xls_bytes(TEAMS_SHEET, SECOND_SHEET), path="/two-sheets.xls")
    assert payload["columns"] == ["name", "team", "age"]
    assert payload["total"] == 4


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
def test_header_only_worksheet_is_400(convert):
    for body, path in [
        (xlsx_bytes([["name", "age"]]), "/header-only.xlsx"),
        (xls_bytes([["name", "age"]]), "/header-only.xls"),
    ]:
        assert convert(body, path=path).status_code == 400, path


# Phrase: "The first sheet must be tabular ... or `HTTP 400`." - an empty first sheet,
# even when a later sheet holds a table.
def test_empty_first_worksheet_is_400(convert):
    assert convert(xlsx_bytes([], TEAMS_SHEET), path="/empty-first.xlsx").status_code == 400


# Phrase: "The first sheet must be tabular (header + at least one data row)" - one
# data row is enough.
def test_one_data_row_worksheet_is_accepted(dataset):
    payload = dataset(xlsx_bytes([["a", "b"], [1, 2]]), path="/minimal.xlsx")
    assert payload["rows"] == [[1, 2]]


# Phrase: "`charset` applies only to text CSV sources."
def test_charset_applies_to_csv_sources(dataset):
    latin1 = "name,city\nrené,münchen\n".encode("latin-1")
    payload = dataset(latin1, query="&charset=latin-1", path="/latin.csv")
    assert payload["rows"] == [["rené", "münchen"]]


# Phrase: "`charset` applies only to text CSV sources." - it is ignored, not applied,
# for a workbook (T36).
def test_charset_is_ignored_for_spreadsheet_sources(convert, client):
    for body, path in [
        (xlsx_bytes(TEAMS_SHEET), "/charset.xlsx"),
        (xls_bytes(TEAMS_SHEET), "/charset.xls"),
    ]:
        response = convert(body, query="&charset=utf-99", path=path)
        assert response.status_code == 200, path
        assert client.get(response.get_json()["endpoint"]).get_json()["total"] == 4


# Phrase: "Unrecognized format: `HTTP 400`."
def test_unrecognized_binary_format_is_400(convert):
    for body, path in [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "/image.png"),
        (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", "/doc.pdf"),
        (b"\x1f\x8b\x08\x00" + b"\x00" * 32, "/archive.gz"),
    ]:
        response = convert(body, path=path)
        assert response.status_code == 400, path
        assert response.get_json()["ok"] is False, path


# Phrase: "Unrecognized format: `HTTP 400`." - a zip archive that is not a workbook.
def test_zip_that_is_not_a_workbook_is_400(convert):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a workbook")
    assert convert(buffer.getvalue(), path="/plain.zip").status_code == 400


# Phrase: "spreadsheet columns preserve source order."
def test_spreadsheet_columns_preserve_source_order(dataset):
    header = [f"col{i}" for i in range(12)]
    payload = dataset(xlsx_bytes([header, list(range(12))]), path="/wide.xlsx")
    assert payload["columns"] == header
    assert payload["rows"] == [list(range(12))]


# Phrase: "spreadsheet columns preserve source order." - also for `.xls`.
def test_xls_columns_preserve_source_order(dataset):
    header = [f"col{i}" for i in range(12)]
    payload = dataset(xls_bytes([header, list(range(12))]), path="/wide.xls")
    assert payload["columns"] == header
    assert payload["rows"] == [list(range(12))]


# Phrase: "accept CSV, `.xls`, and `.xlsx`" - a workbook exports as CSV like any
# other dataset.
def test_workbook_dataset_exports_as_csv(client, convert):
    endpoint = convert(xlsx_bytes(TEAMS_SHEET), path="/export.xlsx").get_json()["endpoint"]
    response = client.get(f"{endpoint}/export")
    assert exported_rows(response)[:2] == [["name", "team", "age"], ["ada", "blue", "36"]]


# Phrase: "The first sheet must be tabular" - a single-column sheet is a table (T44).
def test_single_column_worksheet_is_accepted(dataset):
    payload = dataset(xlsx_bytes([["only"], ["a"], ["b"]]), path="/single.xlsx")
    assert payload["columns"] == ["only"]
    assert payload["rows"] == [["a"], ["b"]]
