"""Spec tests for CSV export, file upload, and multi-format ingestion.

Each section quotes the spec phrase (and its minimal context) that it covers.
"""
import pytest

from conftest import make_xls, make_xlsx, multipart_body, read_csv_bytes

# name,age,city — `age` is numeric and the header order is not alphabetical.
PEOPLE = (
    "name,age,city\n"
    "ada,36,London\n"
    "grace,45,New York\n"
    "lin,29,london\n"
    "Ada,50,Paris\n"
)
SIMPLE = "name,age\nada,36\ngrace,45\n"
MANY = "n,tag\n" + "".join("%d,%s\n" % (i, "even" if i % 2 == 0 else "odd")
                           for i in range(1, 121))

SHEET = [["name", "age", "city"], ["ada", 36, "London"], ["grace", 45, "Paris"]]


@pytest.fixture
def ds(server, csv_url):
    """Convert a CSV body; return its /datasets/<id> endpoint path."""
    def make(body, name="exp", charset=None):
        url = csv_url(body, name=name)
        status, _, data = server.convert(url, charset=charset)
        assert status == 200, data
        return data["endpoint"]
    return make


def assert_json_error(status, data, expected):
    """Spec: "all errors use the standard JSON envelope"."""
    assert status == expected, data
    assert data is not None, "error body was not JSON"
    assert data["ok"] is False
    assert isinstance(data["error"], str) and data["error"].strip()


def export_of(server, endpoint, query=""):
    """Raw (status, headers, bytes) of <endpoint>/export."""
    return server.raw(endpoint + "/export" + query)


# ==========================================================================
# Spec: "`GET /datasets/<id>/export` returns CSV bytes"
# ==========================================================================
def test_export_returns_csv_bytes(server, ds):
    endpoint = ds(PEOPLE, name="csv-bytes")
    status, headers, body = export_of(server, endpoint)
    assert status == 200
    assert isinstance(body, bytes) and body
    assert read_csv_bytes(body)[0] == ["name", "age", "city"]


# Spec: "returns CSV bytes" — the body parses as CSV with one row per record.
def test_export_body_is_the_dataset(server, ds):
    endpoint = ds(SIMPLE, name="body")
    rows = read_csv_bytes(export_of(server, endpoint)[2])
    assert rows == [["name", "age"], ["ada", "36"], ["grace", "45"]]


# ==========================================================================
# Spec: "- `Content-Type: text/csv`"
# ==========================================================================
def test_export_content_type_is_text_csv(server, ds):
    endpoint = ds(SIMPLE, name="ctype")
    headers = export_of(server, endpoint)[1]
    ctype = headers.get("Content-Type", "")
    assert ctype.split(";")[0].strip().lower() == "text/csv"


# ==========================================================================
# Spec: '- `Content-Disposition: attachment; filename="<dataset-id>.csv"`'
# ==========================================================================
def test_export_content_disposition_is_attachment_with_id_filename(server, ds):
    endpoint = ds(SIMPLE, name="disp")
    ident = endpoint[len("/datasets/"):]
    headers = export_of(server, endpoint)[1]
    disposition = headers.get("Content-Disposition", "")
    assert disposition.split(";")[0].strip().lower() == "attachment"
    assert 'filename="%s.csv"' % ident in disposition


# ==========================================================================
# Spec: "The CSV uses source column order"
#       (Determinism: "export columns follow source column order.")
# ==========================================================================
def test_export_uses_source_column_order(server, ds):
    endpoint = ds("zeta,alpha,mid\n1,2,3\n", name="order")
    rows = read_csv_bytes(export_of(server, endpoint)[2])
    assert rows[0] == ["zeta", "alpha", "mid"]
    assert rows[1] == ["1", "2", "3"]


# Spec: "The CSV uses source column order" — matching /datasets/<id> columns.
def test_export_columns_match_json_columns(server, ds):
    endpoint = ds(PEOPLE, name="same-cols")
    columns = server.get(endpoint)[2]["columns"]
    assert read_csv_bytes(export_of(server, endpoint)[2])[0] == columns


# ==========================================================================
# Spec: "applies the same filters ... as `/datasets/<id>`"
# ==========================================================================
def test_export_applies_exact_filter(server, ds):
    endpoint = ds(PEOPLE, name="filter-exact")
    rows = read_csv_bytes(export_of(server, endpoint, "?city__exact=Paris")[2])
    assert rows == [["name", "age", "city"], ["Ada", "50", "Paris"]]


# Spec: "applies the same filters" — numeric comparators too, and ANDed.
def test_export_applies_numeric_filters(server, ds):
    endpoint = ds(PEOPLE, name="filter-num")
    body = export_of(server, endpoint, "?age__greater=30&age__less=46")[2]
    assert [row[0] for row in read_csv_bytes(body)[1:]] == ["ada", "grace"]


# Spec: "applies the same filters" — an invalid filter is the same 400.
def test_export_rejects_invalid_filter(server, ds):
    endpoint = ds(PEOPLE, name="filter-bad")
    status, _, data = server.get(endpoint + "/export?nope__exact=1")
    assert_json_error(status, data, 400)


# ==========================================================================
# Spec: "applies the same ... sort ... as `/datasets/<id>`"
# ==========================================================================
def test_export_applies_sort(server, ds):
    endpoint = ds(PEOPLE, name="sort")
    body = export_of(server, endpoint, "?_sort=age")[2]
    assert [row[1] for row in read_csv_bytes(body)[1:]] == ["29", "36", "45", "50"]


# Spec: "applies the same ... sort" — `_sort_desc` reverses it.
def test_export_applies_sort_desc(server, ds):
    endpoint = ds(PEOPLE, name="sort-desc")
    body = export_of(server, endpoint, "?_sort_desc=age")[2]
    assert [row[1] for row in read_csv_bytes(body)[1:]] == ["50", "45", "36", "29"]


# ==========================================================================
# Spec: "applies the same ... pagination as `/datasets/<id>`"
# ==========================================================================
def test_export_applies_size_and_offset(server, ds):
    endpoint = ds(PEOPLE, name="page")
    body = export_of(server, endpoint, "?_size=2&_offset=1")[2]
    rows = read_csv_bytes(body)
    assert rows[0] == ["name", "age", "city"]
    assert [row[0] for row in rows[1:]] == ["grace", "lin"]


# Spec: "the same ... pagination" — an invalid `_size` is the same 400.
def test_export_rejects_invalid_size(server, ds):
    endpoint = ds(PEOPLE, name="page-bad")
    status, _, data = server.get(endpoint + "/export?_size=0")
    assert_json_error(status, data, 400)


# ==========================================================================
# Determinism: "export rows follow filter -> sort -> paginate."
# ==========================================================================
def test_export_order_is_filter_then_sort_then_paginate(server, ds):
    endpoint = ds(PEOPLE, name="pipeline")
    # filter -> {ada 36, grace 45, Ada 50}; sort desc -> 50, 45, 36;
    # offset 1 size 1 -> grace.
    body = export_of(
        server, endpoint,
        "?age__greater=30&_sort_desc=age&_offset=1&_size=1")[2]
    assert read_csv_bytes(body)[1:] == [["grace", "45", "New York"]]


# Determinism: the same request twice yields byte-identical CSV.
def test_export_is_deterministic(server, ds):
    endpoint = ds(PEOPLE, name="determinism")
    first = export_of(server, endpoint, "?_sort=name")[2]
    second = export_of(server, endpoint, "?_sort=name")[2]
    assert first == second


# ==========================================================================
# Spec: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# ==========================================================================
def test_shape_does_not_affect_csv(server, ds):
    endpoint = ds(PEOPLE, name="shape")
    plain = export_of(server, endpoint)[2]
    assert export_of(server, endpoint, "?_shape=objects")[2] == plain
    assert export_of(server, endpoint, "?_shape=lists")[2] == plain


# Spec: "`_rowid` ... do not affect CSV output" — no rowid column appears.
def test_rowid_does_not_affect_csv(server, ds):
    endpoint = ds(PEOPLE, name="rowid")
    plain = export_of(server, endpoint)[2]
    assert export_of(server, endpoint, "?_rowid=hide")[2] == plain
    assert export_of(server, endpoint, "?_shape=objects&_rowid=hide")[2] == plain
    assert read_csv_bytes(plain)[0] == ["name", "age", "city"]


# Spec: "`_total` ... do not affect CSV output" — no total row/column either.
def test_total_does_not_affect_csv(server, ds):
    endpoint = ds(PEOPLE, name="total")
    plain = export_of(server, endpoint)[2]
    assert export_of(server, endpoint, "?_total=hide")[2] == plain
    rows = read_csv_bytes(plain)
    assert len(rows) == 5 and all(len(row) == 3 for row in rows)


# ==========================================================================
# Spec: "`POST /upload` accepts multipart form with field `file`"
# ==========================================================================
def test_upload_accepts_file_field(up):
    status, _, data = up.upload(SIMPLE, field="file")
    assert status == 200, data
    assert data["ok"] is True


# Spec: "... or `attachment`."
def test_upload_accepts_attachment_field(up):
    status, _, data = up.upload(PEOPLE, field="attachment",
                                filename="people.csv")
    assert status == 200, data
    assert data["ok"] is True


# ==========================================================================
# Spec: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
# ==========================================================================
def test_upload_success_envelope(up):
    status, _, data = up.upload(SIMPLE)
    assert status == 200, data
    assert data["ok"] is True
    assert data["endpoint"].startswith("/datasets/")
    assert data["endpoint"][len("/datasets/"):]


# Spec: the returned endpoint is a real, queryable dataset.
def test_uploaded_dataset_is_queryable(up):
    endpoint = up.upload(PEOPLE, filename="people.csv")[2]["endpoint"]
    status, _, payload = up.get(endpoint)
    assert status == 200, payload
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"][0] == ["ada", 36, "London"]


# Spec: the uploaded dataset exports like any other.
def test_uploaded_dataset_exports(up):
    endpoint = up.upload(SIMPLE)[2]["endpoint"]
    status, headers, body = up.raw(endpoint + "/export")
    assert status == 200
    assert headers["Content-Type"].split(";")[0].strip() == "text/csv"
    assert read_csv_bytes(body)[0] == ["name", "age"]


# ==========================================================================
# Spec: "Re-uploading the same file bytes yields the same dataset id."
# ==========================================================================
def test_same_bytes_same_dataset_id(up):
    first = up.upload(PEOPLE, filename="a.csv")[2]["endpoint"]
    second = up.upload(PEOPLE, filename="a.csv")[2]["endpoint"]
    assert first == second


# Spec: "the same file bytes" — the field name used is not part of the identity.
def test_same_bytes_via_either_field_same_id(up):
    first = up.upload(PEOPLE, field="file", filename="a.csv")[2]["endpoint"]
    second = up.upload(PEOPLE, field="attachment", filename="a.csv")[2]["endpoint"]
    assert first == second


# Spec: different bytes yield a different dataset id.
def test_different_bytes_different_dataset_id(up):
    first = up.upload(SIMPLE)[2]["endpoint"]
    second = up.upload(PEOPLE)[2]["endpoint"]
    assert first != second


# ==========================================================================
# Spec: "Upload status: - non-multipart request: `HTTP 415`"
#       (Error Handling: "non-multipart upload: `HTTP 415`")
# ==========================================================================
def test_non_multipart_json_body_is_415(up):
    status, _, data = up.post("/upload", b'{"a": 1}',
                              content_type="application/json")
    assert_json_error(status, data, 415)


# Spec: "non-multipart request: HTTP 415" — urlencoded form is not multipart.
def test_urlencoded_upload_is_415(up):
    status, _, data = up.post("/upload", b"file=abc",
                              content_type="application/x-www-form-urlencoded")
    assert_json_error(status, data, 415)


# Spec: "non-multipart request: HTTP 415" — raw CSV with a text content type.
def test_raw_csv_body_is_415(up):
    status, _, data = up.post("/upload", SIMPLE.encode("utf-8"),
                              content_type="text/csv")
    assert_json_error(status, data, 415)


# Spec: "non-multipart request: HTTP 415" — no Content-Type at all.
def test_missing_content_type_is_415(up):
    status, _, data = up.post("/upload", SIMPLE.encode("utf-8"),
                              content_type=None)
    assert status == 415, data
    assert data is not None and data["ok"] is False


# ==========================================================================
# Spec: "malformed multipart ... : `HTTP 400`"
# ==========================================================================
def test_malformed_multipart_body_is_400(up):
    # Declares a boundary that the body never uses.
    body = b"this is not a multipart body at all\r\n"
    status, _, data = up.post(
        "/upload", body,
        content_type="multipart/form-data; boundary=----nope")
    assert_json_error(status, data, 400)


# Spec: "malformed multipart" — a truncated body with no closing boundary.
def test_truncated_multipart_is_400(up):
    body = multipart_body([("file", "a.csv", SIMPLE)])
    truncated = body[:len(body) // 2]
    status, _, data = up.post(
        "/upload", truncated,
        content_type="multipart/form-data; boundary=----datagateTestBoundary9d7f")
    assert_json_error(status, data, 400)


# Spec: "malformed multipart" — `multipart/form-data` without a boundary.
def test_multipart_without_boundary_is_400(up):
    body = multipart_body([("file", "a.csv", SIMPLE)])
    status, _, data = up.post("/upload", body,
                              content_type="multipart/form-data")
    assert_json_error(status, data, 400)


# ==========================================================================
# Spec: "... or missing both `file` and `attachment`: `HTTP 400`"
#       (Error Handling: "missing file field: `HTTP 400`")
# ==========================================================================
def test_missing_both_fields_is_400(up):
    status, _, data = up.upload(None, extra=[("other", "x.csv", SIMPLE)])
    assert_json_error(status, data, 400)


# Spec: "missing both `file` and `attachment`" — an empty multipart form.
def test_empty_multipart_form_is_400(up):
    status, _, data = up.upload(None)
    assert_json_error(status, data, 400)


# Spec: "missing file field" — non-file form fields do not satisfy the route.
def test_only_plain_form_fields_is_400(up):
    status, _, data = up.upload(None, extra=[("name", "ada"), ("age", "36")])
    assert_json_error(status, data, 400)


# ==========================================================================
# Spec: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`."
# ==========================================================================
def test_convert_accepts_csv(server, ds):
    endpoint = ds(SIMPLE, name="fmt-csv")
    assert server.get(endpoint)[2]["columns"] == ["name", "age"]


def test_convert_accepts_xlsx(server, csv_url):
    url = csv_url(make_xlsx([("Sheet1", SHEET)]), name="fmt-xlsx")
    status, _, data = server.convert(url)
    assert status == 200, data
    payload = server.get(data["endpoint"])[2]
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["ada", 36, "London"], ["grace", 45, "Paris"]]


def test_convert_accepts_xls(server, csv_url):
    url = csv_url(make_xls([("Sheet1", SHEET)]), name="fmt-xls")
    status, _, data = server.convert(url)
    assert status == 200, data
    payload = server.get(data["endpoint"])[2]
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["ada", 36, "London"], ["grace", 45, "Paris"]]


def test_upload_accepts_xlsx(up):
    status, _, data = up.upload(make_xlsx([("S", SHEET)]), filename="t.xlsx")
    assert status == 200, data
    payload = up.get(data["endpoint"])[2]
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["ada", 36, "London"], ["grace", 45, "Paris"]]


def test_upload_accepts_xls(up):
    status, _, data = up.upload(make_xls([("S", SHEET)]), filename="t.xls")
    assert status == 200, data
    payload = up.get(data["endpoint"])[2]
    assert payload["columns"] == ["name", "age", "city"]
    assert payload["rows"] == [["ada", 36, "London"], ["grace", 45, "Paris"]]


def test_upload_accepts_csv(up):
    status, _, data = up.upload(PEOPLE, filename="people.csv")
    assert status == 200, data
    assert up.get(data["endpoint"])[2]["columns"] == ["name", "age", "city"]


# ==========================================================================
# Spec: "Only the first worksheet is ingested."
# ==========================================================================
def test_only_first_worksheet_xlsx(up):
    raw = make_xlsx([
        ("First", [["a", "b"], [1, 2]]),
        ("Second", [["x", "y", "z"], [7, 8, 9]]),
    ])
    endpoint = up.upload(raw, filename="two.xlsx")[2]["endpoint"]
    payload = up.get(endpoint)[2]
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


def test_only_first_worksheet_xls(up):
    raw = make_xls([
        ("First", [["a", "b"], [1, 2]]),
        ("Second", [["x", "y", "z"], [7, 8, 9]]),
    ])
    endpoint = up.upload(raw, filename="two.xls")[2]["endpoint"]
    payload = up.get(endpoint)[2]
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


# Spec: "Only the first worksheet is ingested" — a later sheet cannot rescue a
# non-tabular first sheet.
def test_later_sheet_does_not_rescue_first(up):
    raw = make_xlsx([("First", [["a", "b"]]), ("Second", [["x"], [1]])])
    status, _, data = up.upload(raw, filename="rescue.xlsx")
    assert_json_error(status, data, 400)


# ==========================================================================
# Spec: "The first sheet must be tabular (header + at least one data row)
#        or `HTTP 400`."
# ==========================================================================
def test_header_only_sheet_is_400(up):
    status, _, data = up.upload(make_xlsx([("S", [["a", "b"]])]),
                                filename="header.xlsx")
    assert_json_error(status, data, 400)


def test_empty_sheet_is_400(up):
    status, _, data = up.upload(make_xlsx([("S", [])]), filename="empty.xlsx")
    assert_json_error(status, data, 400)


def test_header_only_xls_sheet_is_400(up):
    status, _, data = up.upload(make_xls([("S", [["a", "b"]])]),
                                filename="header.xls")
    assert_json_error(status, data, 400)


def test_sheet_with_header_and_one_row_is_ok(up):
    status, _, data = up.upload(make_xlsx([("S", [["a", "b"], [1, 2]])]),
                                filename="minimal.xlsx")
    assert status == 200, data
    assert up.get(data["endpoint"])[2]["rows"] == [[1, 2]]


# ==========================================================================
# Spec: "`charset` applies only to text CSV sources."
# ==========================================================================
def test_charset_applies_to_csv_source(server, origin):
    body = "name,city\nada,Köln\n".encode("cp1252")
    url = origin.add("/charset-csv.csv", body)
    status, _, data = server.convert(url, charset="cp1252")
    assert status == 200, data
    assert server.get(data["endpoint"])[2]["rows"] == [["ada", "Köln"]]


# Spec: "charset applies only to text CSV sources" — a workbook ingests the
# same way whether or not a charset was supplied.
def test_charset_is_not_applied_to_xlsx(server, origin):
    raw = make_xlsx([("S", [["name", "city"], ["ada", "Köln"]])])
    url = origin.add("/charset-xlsx.xlsx", raw)
    status, _, data = server.convert(url, charset="cp1252")
    assert status == 200, data
    assert server.get(data["endpoint"])[2]["rows"] == [["ada", "Köln"]]


def test_charset_is_not_applied_to_xls(server, origin):
    raw = make_xls([("S", [["name", "city"], ["ada", "Köln"]])])
    url = origin.add("/charset-xls.xls", raw)
    status, _, data = server.convert(url, charset="utf-8")
    assert status == 200, data
    assert server.get(data["endpoint"])[2]["rows"] == [["ada", "Köln"]]


# ==========================================================================
# Spec: "Unrecognized format: `HTTP 400`."
#       (Error Handling: "unsupported format: `HTTP 400`")
# ==========================================================================
@pytest.mark.parametrize("payload", [
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01\x02\x03",
    b"%PDF-1.4\n%\xc7\xec\x8f\xa2\n1 0 obj\n",
    b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03abc",
    b"GIF89a\x01\x00\x01\x00\x00\xff\x00,",
])
def test_upload_unrecognized_binary_is_400(up, payload):
    status, _, data = up.upload(payload, filename="thing.bin")
    assert_json_error(status, data, 400)


def test_convert_unrecognized_binary_is_400(server, csv_url):
    url = csv_url(b"%PDF-1.4\n%\xc7\xec\x8f\xa2\n", name="pdf",
                  content_type="application/pdf")
    status, _, data = server.convert(url)
    assert_json_error(status, data, 400)


# Spec: "Unrecognized format" — a ZIP that is not a workbook is not ingestible.
def test_zip_that_is_not_a_workbook_is_400(up):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "not a workbook")
    status, _, data = up.upload(buf.getvalue(), filename="plain.zip")
    assert_json_error(status, data, 400)


# ==========================================================================
# Determinism: "spreadsheet columns preserve source order."
# ==========================================================================
def test_spreadsheet_columns_preserve_source_order_xlsx(up):
    rows = [["zeta", "alpha", "mid"], [1, 2, 3], [4, 5, 6]]
    endpoint = up.upload(make_xlsx([("S", rows)]),
                         filename="order.xlsx")[2]["endpoint"]
    payload = up.get(endpoint)[2]
    assert payload["columns"] == ["zeta", "alpha", "mid"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


def test_spreadsheet_columns_preserve_source_order_xls(up):
    rows = [["zeta", "alpha", "mid"], [1, 2, 3], [4, 5, 6]]
    endpoint = up.upload(make_xls([("S", rows)]),
                         filename="order.xls")[2]["endpoint"]
    payload = up.get(endpoint)[2]
    assert payload["columns"] == ["zeta", "alpha", "mid"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


# Determinism: a workbook exports in the same source column order.
def test_spreadsheet_export_column_order(up):
    rows = [["zeta", "alpha", "mid"], [1, 2, 3]]
    endpoint = up.upload(make_xlsx([("S", rows)]),
                         filename="order-exp.xlsx")[2]["endpoint"]
    body = up.raw(endpoint + "/export")[2]
    assert read_csv_bytes(body)[0] == ["zeta", "alpha", "mid"]


# ==========================================================================
# Determinism: "semantically-correct CSV is required; exact newline/quoting
#              is not."
# ==========================================================================
def test_export_quotes_embedded_separators_and_quotes(server, ds):
    body = 'a,b\n"x,y","he said ""hi"""\n'
    endpoint = ds(body, name="quoting")
    rows = read_csv_bytes(export_of(server, endpoint)[2])
    assert rows == [["a", "b"], ["x,y", 'he said "hi"']]


# Determinism: a newline inside a field survives the round trip.
def test_export_preserves_embedded_newlines(server, ds):
    endpoint = ds('a,b\n"line1\nline2",2\n', name="newline")
    rows = read_csv_bytes(export_of(server, endpoint)[2])
    assert rows == [["a", "b"], ["line1\nline2", "2"]]


# Determinism: the export re-ingests to the same dataset content.
def test_export_round_trips_through_convert(server, origin, ds):
    endpoint = ds(PEOPLE, name="roundtrip")
    original = server.get(endpoint)[2]
    body = export_of(server, endpoint)[2]
    url = origin.add("/roundtrip-export.csv", body)
    again = server.convert(url)[2]["endpoint"]
    reloaded = server.get(again)[2]
    assert reloaded["columns"] == original["columns"]
    assert reloaded["rows"] == original["rows"]


# ==========================================================================
# Spec: "all errors use the standard JSON envelope"
# ==========================================================================
def test_export_unknown_dataset_is_json_envelope(server):
    status, headers, data = server.get("/datasets/definitely-missing/export")
    assert_json_error(status, data, 404)
    assert "json" in headers.get("Content-Type", "").lower()


def test_upload_error_bodies_are_json(up):
    for status, ctype in ((415, "application/json"), (400, None)):
        if ctype is not None:
            got, headers, data = up.post("/upload", b"{}", content_type=ctype)
        else:
            got, headers, data = up.upload(None)
        assert got == status, data
        assert "json" in headers.get("Content-Type", "").lower()
        assert data["ok"] is False and isinstance(data["error"], str)


# Spec: "Formula/computed-cell behavior is not required." — a workbook holding
# a formula must still ingest (whatever the cell's value ends up being).
def test_formula_cells_do_not_break_ingestion(up):
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    ws.append([1, "=A2+1"])
    buf = io.BytesIO()
    wb.save(buf)
    status, _, data = up.upload(buf.getvalue(), filename="formula.xlsx")
    assert status == 200, data
    payload = up.get(data["endpoint"])[2]
    assert payload["columns"] == ["a", "b"]
    assert len(payload["rows"]) == 1
