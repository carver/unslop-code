"""Spec section: Export, Upload, and Multi-Format Support -> Multi-Format Ingestion."""
import zipfile

from conftest import convert_ok, dataset, upload, upload_ok, xls_bytes, xlsx_bytes

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_CT = "application/vnd.ms-excel"

PEOPLE_ROWS = [["name", "age", "city"], ["Ada", 36, "London"], ["Grace", 45, "NYC"]]


# ---------------------------------------------------------------------------
# Phrase: "`/convert` and `/upload` accept CSV"
# Context: the pre-existing text path keeps working under multi-format rules.
# ---------------------------------------------------------------------------
def test_convert_still_accepts_csv(gate, origin):
    source = origin.add("/fmt-plain.csv", "name,age\nAda,36\n")
    payload = dataset(gate, source)
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["Ada", 36]]


def test_upload_still_accepts_csv(gate):
    endpoint = upload_ok(gate, "name,age\nAda,36\n", filename="p.csv")
    assert gate.get(endpoint).json()["columns"] == ["name", "age"]


# ---------------------------------------------------------------------------
# Phrase: "`/convert` and `/upload` accept ... `.xlsx`"
# Context: modern Excel workbooks are a first-class source format.
# ---------------------------------------------------------------------------
def test_convert_accepts_xlsx(gate, origin):
    data = xlsx_bytes([("Sheet1", PEOPLE_ROWS)])
    source = origin.add("/fmt-book.xlsx", data, content_type=XLSX_CT)
    payload = dataset(gate, source)
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["Ada", 36, "London"], ["Grace", 45, "NYC"]]


def test_upload_accepts_xlsx(gate):
    data = xlsx_bytes([("Sheet1", PEOPLE_ROWS)])
    endpoint = upload_ok(gate, data, filename="book.xlsx", content_type=XLSX_CT)
    payload = gate.get(endpoint).json()
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["Ada", 36, "London"], ["Grace", 45, "NYC"]]


# ---------------------------------------------------------------------------
# Phrase: "`/convert` and `/upload` accept ... `.xls`"
# Context: the legacy binary Excel format is also accepted.
# ---------------------------------------------------------------------------
def test_convert_accepts_xls(gate, origin):
    data = xls_bytes([("Sheet1", PEOPLE_ROWS)])
    source = origin.add("/fmt-book.xls", data, content_type=XLS_CT)
    payload = dataset(gate, source)
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["Ada", 36, "London"], ["Grace", 45, "NYC"]]


def test_upload_accepts_xls(gate):
    data = xls_bytes([("Sheet1", PEOPLE_ROWS)])
    endpoint = upload_ok(gate, data, filename="book.xls", content_type=XLS_CT)
    payload = gate.get(endpoint).json()
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["Ada", 36, "London"], ["Grace", 45, "NYC"]]


# ---------------------------------------------------------------------------
# Phrase: "Only the first worksheet is ingested."
# Context: later sheets contribute no columns and no rows.
# ---------------------------------------------------------------------------
def test_xlsx_ingests_only_the_first_worksheet(gate, origin):
    data = xlsx_bytes(
        [
            ("First", [["a", "b"], ["1", "2"]]),
            ("Second", [["x", "y", "z"], ["9", "9", "9"]]),
        ]
    )
    payload = dataset(gate, origin.add("/fmt-multi.xlsx", data, content_type=XLSX_CT))
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


def test_xls_ingests_only_the_first_worksheet(gate, origin):
    data = xls_bytes(
        [
            ("First", [["a", "b"], ["1", "2"]]),
            ("Second", [["x", "y", "z"], ["9", "9", "9"]]),
        ]
    )
    payload = dataset(gate, origin.add("/fmt-multi.xls", data, content_type=XLS_CT))
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


def test_a_bad_second_sheet_does_not_spoil_a_good_first_sheet(gate):
    data = xlsx_bytes([("Good", [["a"], ["1"]]), ("Empty", [])])
    endpoint = upload_ok(gate, data, filename="m.xlsx", content_type=XLSX_CT)
    assert gate.get(endpoint).json()["columns"] == ["a"]


# ---------------------------------------------------------------------------
# Phrase: "The first sheet must be tabular (header + at least one data row)
#          or `HTTP 400`."
# Context: applies to both spreadsheet formats and both entry points.
# ---------------------------------------------------------------------------
def test_xlsx_first_sheet_with_only_a_header_is_400(gate):
    data = xlsx_bytes([("Only", [["a", "b"]])])
    resp = upload(gate, data, filename="hdr.xlsx", content_type=XLSX_CT)
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_xlsx_empty_first_sheet_is_400(gate, origin):
    data = xlsx_bytes([("Empty", []), ("Full", [["a"], ["1"]])])
    source = origin.add("/fmt-emptyfirst.xlsx", data, content_type=XLSX_CT)
    resp = gate.convert(source=source)
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_xls_first_sheet_with_only_a_header_is_400(gate):
    data = xls_bytes([("Only", [["a", "b"]])])
    resp = upload(gate, data, filename="hdr.xls", content_type=XLS_CT)
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_xls_empty_first_sheet_is_400(gate):
    data = xls_bytes([("Empty", []), ("Full", [["a"], ["1"]])])
    resp = upload(gate, data, filename="ef.xls", content_type=XLS_CT)
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "spreadsheet columns preserve source order" (Determinism)
# Context: column order is the sheet's left-to-right order, never sorted.
# ---------------------------------------------------------------------------
def test_spreadsheet_columns_preserve_source_order(gate):
    rows = [["zeta", "alpha", "mid"], ["1", "2", "3"]]
    endpoint = upload_ok(
        gate, xlsx_bytes([("S", rows)]), filename="order.xlsx", content_type=XLSX_CT
    )
    assert gate.get(endpoint).json()["columns"] == ["zeta", "alpha", "mid"]


def test_spreadsheet_export_preserves_source_column_order(gate):
    rows = [["zeta", "alpha", "mid"], ["1", "2", "3"]]
    endpoint = upload_ok(
        gate, xlsx_bytes([("S", rows)]), filename="order2.xlsx", content_type=XLSX_CT
    )
    text = gate.get(endpoint + "/export").text
    assert text.splitlines()[0].strip() == "zeta,alpha,mid"


def test_xls_columns_preserve_source_order(gate):
    rows = [["zeta", "alpha", "mid"], ["1", "2", "3"]]
    endpoint = upload_ok(
        gate, xls_bytes([("S", rows)]), filename="order.xls", content_type=XLS_CT
    )
    assert gate.get(endpoint).json()["columns"] == ["zeta", "alpha", "mid"]


# ---------------------------------------------------------------------------
# Phrase: "`charset` applies and validates only for text CSV sources."
# Context: a spreadsheet payload ignores charset entirely, valid or not.
# ---------------------------------------------------------------------------
def test_charset_is_ignored_for_xlsx_upload(gate):
    data = xlsx_bytes([("S", PEOPLE_ROWS)])
    resp = upload(
        gate, data, filename="cs.xlsx", content_type=XLSX_CT, charset="not-a-charset"
    )
    assert resp.status_code == 200, resp.text
    endpoint = resp.json()["endpoint"]
    assert gate.get(endpoint).json()["columns"] == ["name", "age", "city"]


def test_charset_is_ignored_for_xls_upload(gate):
    data = xls_bytes([("S", PEOPLE_ROWS)])
    resp = upload(
        gate, data, filename="cs.xls", content_type=XLS_CT, charset="not-a-charset"
    )
    assert resp.status_code == 200, resp.text


def test_charset_is_ignored_for_xlsx_convert(gate, origin):
    data = xlsx_bytes([("S", PEOPLE_ROWS)])
    source = origin.add("/fmt-cs.xlsx", data, content_type=XLSX_CT)
    resp = gate.convert(source=source, charset="not-a-charset")
    assert resp.status_code == 200, resp.text


def test_a_valid_charset_does_not_change_a_spreadsheet(gate):
    data = xlsx_bytes([("S", PEOPLE_ROWS)])
    plain = upload_ok(gate, data, filename="cs2.xlsx", content_type=XLSX_CT)
    with_cs = upload_ok(
        gate, data, filename="cs2.xlsx", content_type=XLSX_CT, charset="utf-16"
    )
    assert plain == with_cs
    assert gate.get(plain).json()["rows"] == [
        ["Ada", 36, "London"],
        ["Grace", 45, "NYC"],
    ]


def test_charset_still_validates_for_csv_upload(gate):
    resp = upload(gate, "a,b\n1,2\n", filename="v.csv", charset="not-a-charset")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_charset_still_validates_for_csv_convert(gate, origin):
    source = origin.add("/fmt-v.csv", "a,b\n1,2\n")
    resp = gate.convert(source=source, charset="not-a-charset")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "Unrecognized format: `HTTP 400`."
# Context: bytes that are neither text CSV nor a readable spreadsheet.
# ---------------------------------------------------------------------------
def test_pdf_upload_is_400(gate):
    resp = upload(gate, b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", filename="d.pdf")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_png_upload_is_400(gate):
    resp = upload(gate, b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, filename="i.png")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_a_zip_that_is_not_a_workbook_is_400(gate):
    import io as _io

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")
    resp = upload(gate, buffer.getvalue(), filename="a.zip")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_truncated_xlsx_is_400(gate):
    data = xlsx_bytes([("S", PEOPLE_ROWS)])
    resp = upload(gate, data[: len(data) // 2], filename="broken.xlsx")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_truncated_xls_is_400(gate):
    data = xls_bytes([("S", PEOPLE_ROWS)])
    resp = upload(gate, data[:200], filename="broken.xls")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_unrecognized_format_via_convert_is_400(gate, origin):
    source = origin.add(
        "/fmt-bad.bin", b"\x00\x01\x02\x03binary junk\x00", content_type="application/octet-stream"
    )
    resp = gate.convert(source=source)
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "Formula/computed-cell behavior is not required."
# Context: a workbook containing a formula must still ingest without error.
# ---------------------------------------------------------------------------
def test_a_workbook_with_a_formula_still_ingests(gate):
    data = xlsx_bytes([("S", [["a", "b", "total"], [1, 2, "=A2+B2"]])])
    resp = upload(gate, data, filename="f.xlsx", content_type=XLSX_CT)
    assert resp.status_code == 200, resp.text
    payload = gate.get(resp.json()["endpoint"]).json()
    assert payload["columns"] == ["a", "b", "total"]
    assert len(payload["rows"]) == 1


# ---------------------------------------------------------------------------
# Phrase: "Integers/decimals are JSON numbers" (type inference, applied to
#          spreadsheet cells).
# Context: numeric cells arrive already typed and stay numbers.
# ---------------------------------------------------------------------------
def test_spreadsheet_numeric_cells_are_json_numbers(gate):
    data = xlsx_bytes([("S", [["n", "d", "s"], [7, 1.5, "seven"]])])
    endpoint = upload_ok(gate, data, filename="n.xlsx", content_type=XLSX_CT)
    assert gate.get(endpoint).json()["rows"] == [[7, 1.5, "seven"]]


def test_spreadsheet_blank_cells_become_empty_text(gate):
    data = xlsx_bytes([("S", [["a", "b"], ["x", None]])])
    endpoint = upload_ok(gate, data, filename="b.xlsx", content_type=XLSX_CT)
    assert gate.get(endpoint).json()["rows"] == [["x", ""]]


def test_spreadsheet_rows_are_filterable_and_sortable(gate):
    data = xlsx_bytes([("S", PEOPLE_ROWS)])
    endpoint = upload_ok(gate, data, filename="q.xlsx", content_type=XLSX_CT)
    payload = gate.get(endpoint, params={"age__greater": "40"}).json()
    assert payload["rows"] == [["Grace", 45, "NYC"]]


def test_spreadsheet_objects_shape_exposes_a_rowid(gate):
    data = xlsx_bytes([("S", PEOPLE_ROWS)])
    endpoint = upload_ok(gate, data, filename="r.xlsx", content_type=XLSX_CT)
    rows = gate.get(endpoint, params={"_shape": "objects"}).json()["rows"]
    assert [row["rowid"] for row in rows] == [2, 3]
    assert rows[0]["name"] == "Ada"
