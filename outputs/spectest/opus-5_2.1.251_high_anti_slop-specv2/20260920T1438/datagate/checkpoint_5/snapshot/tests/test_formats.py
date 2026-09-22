"""Ingestion of the spreadsheet formats ``/convert`` and ``/upload`` accept."""

import io
import zipfile

import pytest
from workbooks import xls_bytes, xlsx_bytes

TABLE = [["name", "score"], ["ada", 36], ["lin", 7.5]]


@pytest.fixture(params=[xlsx_bytes, xls_bytes], ids=["xlsx", "xls"])
def workbook(request):
    """Build a workbook payload, once per supported spreadsheet format."""
    return request.param


@pytest.fixture
def read_upload(client, upload):
    """Upload ``payload`` and return the dataset it is served as."""

    def run(payload: bytes, **params):
        endpoint = upload(payload, **params).get_json()["endpoint"]
        return client.get(endpoint).get_json()

    return run


def test_upload_reads_a_workbook(read_upload, workbook):
    body = read_upload(workbook(TABLE))
    assert body["columns"] == ["name", "score"]
    assert body["rows"] == [["ada", 36], ["lin", 7.5]]


def test_convert_reads_a_workbook(client, convert, workbook):
    endpoint = convert(workbook(TABLE)).get_json()["endpoint"]
    assert client.get(endpoint).get_json()["rows"] == [["ada", 36], ["lin", 7.5]]


def test_only_the_first_worksheet_is_ingested(read_upload, workbook):
    other = [["city", "pop"], ["oslo", 700]]
    body = read_upload(workbook(TABLE, other))
    assert body["columns"] == ["name", "score"]
    assert body["total"] == 2


def test_header_without_data_rows_is_rejected(upload, workbook):
    assert upload(workbook([["name", "score"]])).status_code == 400


def test_empty_first_worksheet_is_rejected(upload, workbook):
    assert upload(workbook([], [["name", "score"], ["ada", 36]])).status_code == 400


def test_charset_is_ignored_for_workbooks(read_upload, workbook):
    body = read_upload(workbook(TABLE), charset="klingon-8")
    assert body["rows"][0] == ["ada", 36]


def test_workbook_text_keeps_its_own_encoding(read_upload, workbook):
    body = read_upload(workbook([["city"], ["München"]]))
    assert body["rows"] == [["München"]]


def test_workbook_columns_keep_their_source_order(read_upload, workbook):
    body = read_upload(workbook([["c", "a", "b"], [3, 1, 2]]))
    assert body["columns"] == ["c", "a", "b"]
    assert body["rows"] == [[3, 1, 2]]


def test_exported_workbook_rows_are_csv(client, upload, workbook):
    endpoint = upload(workbook(TABLE)).get_json()["endpoint"]
    response = client.get(f"{endpoint}/export")
    assert response.get_data(as_text=True).splitlines() == [
        "name,score",
        "ada,36",
        "lin,7.5",
    ]


def test_truncated_workbook_is_rejected(upload):
    assert upload(b"PK\x03\x04 truncated").status_code == 400


@pytest.mark.parametrize("entry", ["notes.txt", "[Content_Types].xml"])
def test_zip_that_is_not_a_workbook_is_rejected(upload, entry):
    """A bare archive and a sibling Office format both fail the same way."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(entry, "<Types/>")
    assert upload(buffer.getvalue()).status_code == 400


def test_document_format_is_rejected(upload):
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    assert upload(pdf).status_code == 400


def test_binary_payload_is_rejected(upload):
    assert upload(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00").status_code == 400
