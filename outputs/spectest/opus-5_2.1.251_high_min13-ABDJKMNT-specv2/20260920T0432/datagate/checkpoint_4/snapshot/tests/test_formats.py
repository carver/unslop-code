"""Multi-format ingestion: CSV, .xls and .xlsx through /convert and /upload."""

import zipfile

TABLE = [["name", "age", "city"], ["ada", 36, "london"], ["grace", 45, "hopper"]]
EXPECTED_ROWS = [["ada", 36, "london"], ["grace", 45, "hopper"]]


def convert_bytes(client, origin, content, path):
    source = origin.serve(path, content, content_type="application/octet-stream")
    return client.get("/convert", query_string={"source": source})


# Spec: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: an .xlsx workbook uploaded as a file becomes the same dataset a CSV
# of the same table would.
def test_xlsx_upload_is_ingested(uploaded, xlsx):
    payload = uploaded(xlsx(TABLE), filename="table.xlsx")
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == EXPECTED_ROWS


# Spec: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: the same for the older .xls format.
def test_xls_upload_is_ingested(uploaded, xls):
    payload = uploaded(xls(TABLE), filename="table.xls")
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == EXPECTED_ROWS


# Spec: "`/convert` ... accept CSV, `.xls`, and `.xlsx`."
# Context: a workbook fetched from a URL, recognised by its bytes
# (AMBIGUITIES T30).
def test_convert_ingests_a_remote_xlsx(client, origin, xlsx):
    response = convert_bytes(client, origin, xlsx(TABLE), "/book.xlsx")
    assert response.status_code == 200
    endpoint = response.get_json()["endpoint"]
    assert client.get(endpoint).get_json()["rows"] == EXPECTED_ROWS


# Spec: "`/convert` ... accept CSV, `.xls`, and `.xlsx`."
# Context: an .xls fetched from a URL.
def test_convert_ingests_a_remote_xls(client, origin, xls):
    response = convert_bytes(client, origin, xls(TABLE), "/book.xls")
    assert response.status_code == 200
    endpoint = response.get_json()["endpoint"]
    assert client.get(endpoint).get_json()["rows"] == EXPECTED_ROWS


# Spec: "Only the first worksheet is ingested."
# Context: a workbook with several sheets exposes only the first one's table.
def test_only_the_first_worksheet_is_ingested(uploaded, xlsx):
    workbook = {
        "First": TABLE,
        "Second": [["other", "header"], ["x", "y"]],
    }
    payload = uploaded(xlsx(workbook), filename="two.xlsx")
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == EXPECTED_ROWS


# Spec: "Only the first worksheet is ingested."
# Context: the same rule for .xls.
def test_only_the_first_xls_worksheet_is_ingested(uploaded, xls):
    payload = uploaded(
        xls({"First": TABLE, "Second": [["other"], ["x"]]}), filename="two.xls"
    )
    assert payload["columns"] == ["name", "age", "city"]


# Spec: "spreadsheet columns preserve source order."
# Context: the header is read left to right, as written.
def test_spreadsheet_columns_preserve_source_order(uploaded, xlsx):
    payload = uploaded(xlsx([["zeta", "alpha", "mid"], [1, 2, 3]]), filename="order.xlsx")
    assert payload["columns"] == ["zeta", "alpha", "mid"]
    assert payload["rows"] == [[1, 2, 3]]


# Spec: "The first sheet must be tabular (header + at least one data row) or
# `HTTP 400`."
# Context: a sheet with only a header row, and a wholly empty sheet.
def test_non_tabular_first_sheet_is_400(upload, xlsx, xls):
    for content, name in (
        (xlsx([["name", "age"]]), "header-only.xlsx"),
        (xlsx([[]]), "empty.xlsx"),
        (xls([["name", "age"]]), "header-only.xls"),
    ):
        response = upload(content, filename=name)
        assert response.status_code == 400, name
        assert response.get_json()["ok"] is False


# Spec: "The first sheet must be tabular ... or `HTTP 400`."
# Context: the first sheet is empty even though a later sheet has a table.
def test_empty_first_sheet_is_400_despite_later_sheets(upload, xlsx):
    workbook = {"Empty": [], "Data": TABLE}
    assert upload(xlsx(workbook), filename="later.xlsx").status_code == 400


# Spec: "Unrecognized format: `HTTP 400`."
# Context: bytes that are neither a workbook nor tabular text.
def test_unrecognized_format_is_400(upload, client, origin):
    blobs = {
        "doc.pdf": b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
        "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01",
        "data.json": b'{"name": "ada", "age": 36}',
    }
    for name, content in blobs.items():
        assert upload(content, filename=name).status_code == 400, name
        response = convert_bytes(client, origin, content, f"/{name}")
        assert response.status_code == 400, name


# Spec: "Unrecognized format: `HTTP 400`."
# Context: a zip archive that is not a workbook shares the .xlsx magic bytes.
def test_zip_that_is_not_a_workbook_is_400(upload):
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a workbook")
    response = upload(buffer.getvalue(), filename="archive.zip")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "Unrecognized format: `HTTP 400`."
# Context: an OLE2 container that is not a legacy workbook.
def test_corrupt_xls_is_400(upload):
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    response = upload(content, filename="broken.xls")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "`charset` applies and validates only for text CSV sources."
# Context: an unusable charset is ignored for a workbook (AMBIGUITIES T32).
def test_charset_is_ignored_for_spreadsheets(upload, xlsx, xls):
    for content, name in ((xlsx(TABLE), "a.xlsx"), (xls(TABLE), "a.xls")):
        response = upload(content, filename=name, params={"charset": "nonsense-codec"})
        assert response.status_code == 200, name


# Spec: "`charset` applies and validates only for text CSV sources."
# Context: on a CSV source the same charset still fails, through both routes.
def test_charset_still_validates_for_csv(upload, client, origin):
    assert upload("a,b\n1,2\n", params={"charset": "nonsense-codec"}).status_code == 400
    source = origin.serve("/charset-check.csv", "a,b\n1,2\n")
    response = client.get("/convert", query_string={"source": source, "charset": "nonsense"})
    assert response.status_code == 400


# Spec: "Re-uploading the same file bytes yields the same dataset id."
# Context: workbooks are identified by their bytes like any other upload.
def test_workbook_uploads_are_content_addressed(upload, xlsx):
    content = xlsx(TABLE)
    first = upload(content, filename="one.xlsx").get_json()["endpoint"]
    again = upload(content, filename="two.xlsx").get_json()["endpoint"]
    assert first == again


# Spec: "export columns follow source column order." / "spreadsheet columns
# preserve source order."
# Context: a workbook exports as CSV just like a converted CSV does.
def test_workbook_exports_as_csv(client, upload, xlsx):
    endpoint = upload(xlsx(TABLE), filename="table.xlsx").get_json()["endpoint"]
    response = client.get(f"{endpoint}/export")
    assert response.status_code == 200
    assert response.get_data(as_text=True).splitlines()[0] == "name,age,city"


# Spec: "The first sheet must be tabular (header + at least one data row)"
# Context: a sheet's blank rows and trailing blank columns are not data
# (AMBIGUITIES T34).
def test_blank_rows_are_not_data(uploaded, xlsx):
    payload = uploaded(
        xlsx([["name", "age"], [None, None], ["ada", 36]]), filename="gaps.xlsx"
    )
    assert payload["rows"] == [["ada", 36]]


# Spec: "The first sheet must be tabular (header + at least one data row)"
# Context: a short data row is padded to the header width (AMBIGUITIES T34).
def test_short_rows_are_padded_to_the_header(uploaded, xlsx):
    payload = uploaded(xlsx([["name", "age", "city"], ["ada"]]), filename="short.xlsx")
    assert payload["rows"] == [["ada", "", ""]]


# Spec: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: workbook values keep their own types, with text cells read like CSV
# fields (AMBIGUITIES T33).
def test_workbook_cell_typing(uploaded, xlsx):
    payload = uploaded(
        xlsx([["n", "d", "t", "blank"], [36, 1.5, "0042", None]]), filename="types.xlsx"
    )
    assert payload["rows"] == [[36, 1.5, 42, ""]]


# Spec: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# Context: .xls numbers arrive as floats from the reader but read as CSV would
# (AMBIGUITIES T33).
def test_xls_whole_numbers_are_integers(uploaded, xls):
    payload = uploaded(xls([["n"], [36]]), filename="n.xls")
    assert payload["rows"] == [[36]]
    assert isinstance(payload["rows"][0][0], int)


# Spec: "filters/sort/pagination" (carried forward) over a workbook dataset.
# Context: an ingested workbook behaves like any other dataset.
def test_workbook_dataset_supports_filters_and_sort(uploaded, xlsx):
    payload = uploaded(
        xlsx(TABLE), filename="q.xlsx", query={"age__greater": "40", "_sort": "name"}
    )
    assert payload["rows"] == [["grace", 45, "hopper"]]
