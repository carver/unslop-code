"""Spec section: Export - `GET /datasets/<id>/export`."""

import pytest

from conftest import csv_rows

CSV = "name,qty,note\nwidget,3,red\ngadget,10,blue\ndoohickey,7,red\n"


def dataset_id_of(endpoint):
    return endpoint.rsplit("/", 1)[-1]


@pytest.fixture()
def ingest(client, convert, origin):
    """Ingest a CSV and return (dataset_id, export_path)."""

    def _ingest(body=CSV):
        status, payload = convert(source=origin.add(body))
        assert status == 200, payload
        identifier = dataset_id_of(payload["endpoint"])
        return identifier, payload["endpoint"] + "/export"

    return _ingest


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
# Context: the endpoint exists on a known dataset and answers 200.
def test_export_returns_200(export):
    resp = export(CSV)
    assert resp.status_code == 200


# Phrase: "returns CSV bytes"
# Context: the body is a byte string that parses as CSV, not a JSON envelope.
def test_export_body_is_csv_bytes(export):
    resp = export(CSV)
    assert isinstance(resp.get_data(), bytes)
    assert resp.get_json(silent=True) is None
    assert csv_rows(resp)[0] == ["name", "qty", "note"]


# Phrase: "`Content-Type: text/csv`"
# Context: the declared media type of the export response.
def test_export_content_type(export):
    resp = export(CSV)
    assert resp.headers["Content-Type"].split(";")[0].strip() == "text/csv"


# Phrase: '`Content-Disposition: attachment; filename="<dataset-id>.csv"`'
# Context: the download is an attachment named after the dataset id.
def test_export_content_disposition(client, convert, origin):
    status, payload = convert(source=origin.add(CSV))
    assert status == 200
    identifier = dataset_id_of(payload["endpoint"])
    resp = client.get(payload["endpoint"] + "/export")
    assert resp.headers["Content-Disposition"] == (
        'attachment; filename="%s.csv"' % identifier
    )


# Phrase: "The CSV uses source column order"
# Context: the header row is exactly the source columns, in file order.
def test_export_header_is_source_column_order(export):
    resp = export("zeta,alpha,mid\n1,2,3\n")
    assert csv_rows(resp)[0] == ["zeta", "alpha", "mid"]


# Phrase: "export columns follow source column order." (Determinism)
# Context: order is the file's, never alphabetical or otherwise re-derived.
def test_export_columns_not_sorted(export):
    resp = export("b,a,c\n1,2,3\n")
    assert csv_rows(resp)[0] == ["b", "a", "c"]


# Phrase: "returns CSV bytes" + header row
# Context: data rows follow the header, one line per row, in source order.
def test_export_rows_follow_header(export):
    rows = csv_rows(export(CSV))
    assert rows[1:] == [
        ["widget", "3", "red"],
        ["gadget", "10", "blue"],
        ["doohickey", "7", "red"],
    ]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: an `exact` filter narrows the exported rows.
def test_export_applies_exact_filter(export):
    rows = csv_rows(export(CSV, query_string={"note__exact": "red"}))
    assert rows[0] == ["name", "qty", "note"]
    assert [r[0] for r in rows[1:]] == ["widget", "doohickey"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: `contains` behaves as it does on the JSON endpoint.
def test_export_applies_contains_filter(export):
    rows = csv_rows(export(CSV, query_string={"name__contains": "gad"}))
    assert [r[0] for r in rows[1:]] == ["gadget"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: numeric comparators apply to the exported rows too.
def test_export_applies_numeric_filter(export):
    rows = csv_rows(export(CSV, query_string={"qty__greater": "5"}))
    assert [r[0] for r in rows[1:]] == ["gadget", "doohickey"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: multiple filters are ANDed exactly as on the JSON endpoint.
def test_export_ands_multiple_filters(export):
    rows = csv_rows(
        export(CSV, query_string={"note__exact": "red", "qty__greater": "5"})
    )
    assert [r[0] for r in rows[1:]] == ["doohickey"]


# Phrase: "applies the same ... sort ... as `/datasets/<id>`"
# Context: `_sort` orders the exported rows ascending.
def test_export_applies_sort(export):
    rows = csv_rows(export(CSV, query_string={"_sort": "qty"}))
    assert [r[1] for r in rows[1:]] == ["3", "7", "10"]


# Phrase: "applies the same ... sort ... as `/datasets/<id>`"
# Context: `_sort_desc` orders descending.
def test_export_applies_sort_desc(export):
    rows = csv_rows(export(CSV, query_string={"_sort_desc": "qty"}))
    assert [r[1] for r in rows[1:]] == ["10", "7", "3"]


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
# Context: `_size` limits the number of exported data rows.
def test_export_applies_size(export):
    rows = csv_rows(export(CSV, query_string={"_size": "2"}))
    assert len(rows) == 3  # header + 2


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
# Context: `_offset` skips rows before the page.
def test_export_applies_offset(export):
    rows = csv_rows(export(CSV, query_string={"_offset": "1", "_size": "1"}))
    assert rows[1:] == [["gadget", "10", "blue"]]


# Phrase: "export rows follow filter -> sort -> paginate." (Determinism)
# Context: the page is taken after filtering and sorting, not before.
def test_export_order_is_filter_sort_paginate(export):
    body = "name,qty\na,5\nb,1\nc,9\nd,3\ne,7\n"
    rows = csv_rows(
        export(body, query_string={"qty__greater": "2", "_sort": "qty", "_size": "2"})
    )
    assert rows[1:] == [["d", "3"], ["a", "5"]]


# Phrase: "export rows follow filter -> sort -> paginate." (Determinism)
# Context: descending sort, offset into the sorted+filtered sequence.
def test_export_offset_into_sorted_filtered(export):
    body = "name,qty\na,5\nb,1\nc,9\nd,3\ne,7\n"
    rows = csv_rows(
        export(body, query_string={"qty__less": "9", "_sort_desc": "qty",
                                   "_offset": "1", "_size": "2"})
    )
    assert rows[1:] == [["a", "5"], ["d", "3"]]


# Phrase: "`_shape` ... do not affect CSV output."
# Context: _shape=objects produces the same bytes as the default.
def test_shape_does_not_affect_csv(export):
    plain = export(CSV).get_data()
    assert export(CSV, query_string={"_shape": "objects"}).get_data() == plain
    assert export(CSV, query_string={"_shape": "lists"}).get_data() == plain


# Phrase: "`_rowid` ... do not affect CSV output."
# Context: no rowid column appears, and _rowid=hide changes nothing.
def test_rowid_does_not_affect_csv(export):
    plain = export(CSV).get_data()
    assert export(CSV, query_string={"_rowid": "hide"}).get_data() == plain
    assert "rowid" not in csv_rows(export(CSV))[0]


# Phrase: "`_total` do not affect CSV output."
# Context: no total line or column, and _total=hide changes nothing.
def test_total_does_not_affect_csv(export):
    plain = export(CSV).get_data()
    assert export(CSV, query_string={"_total": "hide"}).get_data() == plain
    rows = csv_rows(export(CSV))
    assert len(rows) == 4 and all(len(r) == 3 for r in rows)


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: they are inert even when combined with filters/sort/pagination.
def test_ignored_controls_combined_with_active_ones(export):
    query = {"_sort": "qty", "_size": "2"}
    plain = export(CSV, query_string=query).get_data()
    noisy = dict(query, _shape="objects", _rowid="hide", _total="hide")
    assert export(CSV, query_string=noisy).get_data() == plain


# Phrase: "semantically-correct CSV is required; exact newline/quoting is not."
# Context: values containing the delimiter survive a round trip through a parser.
def test_export_quotes_embedded_delimiters(export):
    resp = export('name,note\nwidget,"a,b"\n')
    assert csv_rows(resp)[1] == ["widget", "a,b"]


# Phrase: "semantically-correct CSV is required"
# Context: embedded quotes and newlines round-trip through a CSV parser.
def test_export_quotes_embedded_quotes_and_newlines(export):
    resp = export('name,note\nwidget,"say ""hi"""\ngadget,"two\nlines"\n')
    rows = csv_rows(resp)
    assert rows[1] == ["widget", 'say "hi"']
    assert rows[2] == ["gadget", "two\nlines"]


# Phrase: "returns CSV bytes" with the same values as the JSON endpoint
# Context: numbers are rendered without JSON syntax, empties stay empty.
def test_export_renders_values_plainly(export):
    resp = export("a,b,c\n3,4.5,\n")
    assert csv_rows(resp)[1] == ["3", "4.5", ""]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: a filter matching nothing leaves a header-only CSV.
def test_export_empty_result_keeps_header(export):
    rows = csv_rows(export(CSV, query_string={"name__exact": "nope"}))
    assert rows == [["name", "qty", "note"]]


# Phrase: "all errors use the standard JSON envelope"
# Context: exporting an unknown dataset id is a JSON 404, not CSV.
def test_export_unknown_dataset_is_404_envelope(client):
    resp = client.get("/datasets/deadbeefdeadbeef/export")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["ok"] is False and isinstance(body["error"], str)


# Phrase: "applies the same filters ... as `/datasets/<id>`" (error behaviour)
# Context: an invalid filter is rejected the same way as on the JSON endpoint.
def test_export_invalid_filter_is_400_envelope(export):
    resp = export(CSV, query_string={"nosuch__exact": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "applies the same ... sort ... as `/datasets/<id>`" (error behaviour)
# Context: an unknown sort column is rejected.
def test_export_invalid_sort_is_400(export):
    resp = export(CSV, query_string={"_sort": "nope"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "applies the same ... pagination as `/datasets/<id>`" (error behaviour)
# Context: a non-integer _size is rejected.
def test_export_invalid_size_is_400(export):
    resp = export(CSV, query_string={"_size": "many"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "`_shape` ... do not affect CSV output." (see AMBIGUITIES T40)
# Context: inert controls are still validated when malformed.
def test_export_invalid_shape_is_400(export):
    resp = export(CSV, query_string={"_shape": "bogus"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "applies the same ... pagination as `/datasets/<id>`" (see AMBIGUITIES T39)
# Context: the default page size matches the JSON endpoint's default of 100.
def test_export_default_page_size_matches_json(client, convert, origin):
    body = "n\n" + "".join("%d\n" % i for i in range(150))
    status, payload = convert(source=origin.add(body))
    assert status == 200
    json_rows = client.get(payload["endpoint"]).get_json()["rows"]
    resp = client.get(payload["endpoint"] + "/export")
    assert len(csv_rows(resp)) == len(json_rows) + 1


# Phrase: "`GET /datasets/<id>/export`"
# Context: only GET is offered; a POST to the export path is not allowed.
def test_export_rejects_post(client, convert, origin):
    _, payload = convert(source=origin.add(CSV))
    resp = client.post(payload["endpoint"] + "/export")
    assert resp.status_code == 405
    assert resp.get_json()["ok"] is False
