"""Spec section: Export, Upload, and Multi-Format Support -> CSV export."""
import csv
import io

from conftest import convert_ok, read_csv_text

PEOPLE = (
    "name,age,city\n"
    "Ada,36,London\n"
    "Grace,45,New York\n"
    "Linus,28,Helsinki\n"
    "Barbara,52,New York\n"
)


def export(gate, endpoint, **params):
    return gate.get(endpoint + "/export", params=params or None)


def export_rows(gate, endpoint, **params):
    resp = export(gate, endpoint, **params)
    assert resp.status_code == 200, resp.text
    return read_csv_text(resp.text)


# ---------------------------------------------------------------------------
# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
# Context: the export route exists and answers with the dataset as CSV.
# ---------------------------------------------------------------------------
def test_export_returns_csv_bytes(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-basic.csv", PEOPLE))
    resp = export(gate, endpoint)
    assert resp.status_code == 200
    assert isinstance(resp.content, bytes)
    header, rows = read_csv_text(resp.content.decode("utf-8"))
    assert header == ["name", "age", "city"]
    assert rows == [
        ["Ada", "36", "London"],
        ["Grace", "45", "New York"],
        ["Linus", "28", "Helsinki"],
        ["Barbara", "52", "New York"],
    ]


# ---------------------------------------------------------------------------
# Phrase: "`Content-Type: text/csv`"
# Context: response headers of /datasets/<id>/export.
# ---------------------------------------------------------------------------
def test_export_content_type_is_text_csv(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-ct.csv", PEOPLE))
    resp = export(gate, endpoint)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].split(";")[0].strip() == "text/csv"


# ---------------------------------------------------------------------------
# Phrase: "`Content-Disposition: attachment; filename=\"<dataset-id>.csv\"`"
# Context: response headers of /datasets/<id>/export.
# ---------------------------------------------------------------------------
def test_export_content_disposition_names_the_dataset_id(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-cd.csv", PEOPLE))
    dataset_id = endpoint.rsplit("/", 1)[-1]
    resp = export(gate, endpoint)
    assert resp.status_code == 200
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert f'filename="{dataset_id}.csv"' in disposition


# ---------------------------------------------------------------------------
# Phrase: "The CSV uses source column order"
# Context: also "export columns follow source column order" (Determinism).
# ---------------------------------------------------------------------------
def test_export_uses_source_column_order(gate, origin):
    source = origin.add("/export-order.csv", "zeta,alpha,mid\n1,2,3\n4,5,6\n")
    endpoint = convert_ok(gate, source)
    header, rows = export_rows(gate, endpoint)
    assert header == ["zeta", "alpha", "mid"]
    assert rows == [["1", "2", "3"], ["4", "5", "6"]]
    # identical to the JSON view's column order
    assert gate.get(endpoint).json()["columns"] == header


# ---------------------------------------------------------------------------
# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: column filters carry over unchanged to the CSV.
# ---------------------------------------------------------------------------
def test_export_applies_the_same_filters(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-filter.csv", PEOPLE))
    header, rows = export_rows(gate, endpoint, city__exact="New York")
    assert header == ["name", "age", "city"]
    assert [row[0] for row in rows] == ["Grace", "Barbara"]


def test_export_applies_numeric_filters(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-filter2.csv", PEOPLE))
    _, rows = export_rows(gate, endpoint, age__greater="40")
    assert [row[0] for row in rows] == ["Grace", "Barbara"]


def test_export_rejects_an_unknown_filter_column(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-filter3.csv", PEOPLE))
    resp = export(gate, endpoint, nope__exact="x")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "applies the same ... sort ... as `/datasets/<id>`"
# Context: _sort / _sort_desc carry over unchanged to the CSV.
# ---------------------------------------------------------------------------
def test_export_applies_the_same_sort(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-sort.csv", PEOPLE))
    _, rows = export_rows(gate, endpoint, _sort="age")
    assert [row[0] for row in rows] == ["Linus", "Ada", "Grace", "Barbara"]


def test_export_applies_descending_sort(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-sort2.csv", PEOPLE))
    _, rows = export_rows(gate, endpoint, _sort_desc="age")
    assert [row[0] for row in rows] == ["Barbara", "Grace", "Ada", "Linus"]


def test_export_rejects_an_unknown_sort_column(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-sort3.csv", PEOPLE))
    resp = export(gate, endpoint, _sort="nope")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "applies the same ... pagination as `/datasets/<id>`"
# Context: _size / _offset carry over unchanged to the CSV.
# ---------------------------------------------------------------------------
def test_export_applies_size_and_offset(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-page.csv", PEOPLE))
    _, rows = export_rows(gate, endpoint, _size="2", _offset="1")
    assert [row[0] for row in rows] == ["Grace", "Linus"]


def test_export_default_page_is_the_first_hundred_rows(gate, origin):
    body = "n\n" + "".join(f"{i}\n" for i in range(250))
    endpoint = convert_ok(gate, origin.add("/export-page2.csv", body))
    header, rows = export_rows(gate, endpoint)
    assert header == ["n"]
    assert len(rows) == 100
    assert rows[0] == ["0"] and rows[-1] == ["99"]


def test_export_rejects_an_invalid_size(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-page3.csv", PEOPLE))
    resp = export(gate, endpoint, _size="0")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "`_shape` ... do not affect CSV output"
# Context: the objects/lists switch is meaningless for a flat CSV.
# ---------------------------------------------------------------------------
def test_shape_does_not_affect_csv_output(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-shape.csv", PEOPLE))
    plain = export(gate, endpoint).content
    assert export(gate, endpoint, _shape="objects").content == plain
    assert export(gate, endpoint, _shape="lists").content == plain


# ---------------------------------------------------------------------------
# Phrase: "`_rowid` ... do not affect CSV output"
# Context: no rowid column is added or removed by the toggle.
# ---------------------------------------------------------------------------
def test_rowid_does_not_affect_csv_output(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-rowid.csv", PEOPLE))
    plain = export(gate, endpoint).content
    assert export(gate, endpoint, _rowid="hide").content == plain
    header, _ = read_csv_text(plain.decode("utf-8"))
    assert "rowid" not in header


def test_rowid_does_not_appear_even_with_objects_shape(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-rowid2.csv", PEOPLE))
    header, _ = export_rows(gate, endpoint, _shape="objects")
    assert header == ["name", "age", "city"]


# ---------------------------------------------------------------------------
# Phrase: "`_total` ... do not affect CSV output"
# Context: the total count never appears in, or is removed from, the CSV.
# ---------------------------------------------------------------------------
def test_total_does_not_affect_csv_output(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-total.csv", PEOPLE))
    plain = export(gate, endpoint).content
    assert export(gate, endpoint, _total="hide").content == plain
    assert b"total" not in plain


# ---------------------------------------------------------------------------
# Phrase: "export rows follow filter -> sort -> paginate" (Determinism)
# Context: the three stages compose in that order, not any other.
# ---------------------------------------------------------------------------
def test_export_rows_follow_filter_then_sort_then_paginate(gate, origin):
    body = "name,age,city\n" + "".join(
        f"p{i},{100 - i},{'X' if i % 2 else 'Y'}\n" for i in range(20)
    )
    endpoint = convert_ok(gate, origin.add("/export-pipeline.csv", body))
    _, rows = export_rows(gate, endpoint, city__exact="Y", _sort="age", _size="3")
    # city=Y keeps the even i; sorting by age ascending puts the largest i first.
    assert [row[0] for row in rows] == ["p18", "p16", "p14"]
    assert all(row[2] == "Y" for row in rows)


def test_export_matches_the_json_view_row_for_row(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-parity.csv", PEOPLE))
    params = {"_sort_desc": "age", "_size": "3", "city__contains": "o"}
    payload = gate.get(endpoint, params=params).json()
    _, rows = export_rows(gate, endpoint, **params)
    assert [[str(cell) for cell in row] for row in payload["rows"]] == rows


# ---------------------------------------------------------------------------
# Phrase: "semantically-correct CSV is required; exact newline/quoting is not"
# Context: values containing separators/quotes survive a round trip.
# ---------------------------------------------------------------------------
def test_export_quotes_values_that_need_it(gate, origin):
    body = 'a,b\n"x,y","he said ""hi"""\n'
    endpoint = convert_ok(gate, origin.add("/export-quote.csv", body))
    header, rows = export_rows(gate, endpoint)
    assert header == ["a", "b"]
    assert rows == [["x,y", 'he said "hi"']]


def test_export_round_trips_unicode(gate, origin):
    body = "city,note\nZürich,café\n"
    endpoint = convert_ok(gate, origin.add("/export-unicode.csv", body))
    resp = export(gate, endpoint)
    assert resp.status_code == 200
    header, rows = read_csv_text(resp.content.decode("utf-8"))
    assert header == ["city", "note"]
    assert rows == [["Zürich", "café"]]


def test_export_of_an_empty_result_set_keeps_the_header(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-empty.csv", PEOPLE))
    header, rows = export_rows(gate, endpoint, city__exact="Atlantis")
    assert header == ["name", "age", "city"]
    assert rows == []


def test_export_is_byte_identical_across_repeats(gate, origin):
    endpoint = convert_ok(gate, origin.add("/export-repeat.csv", PEOPLE))
    first = export(gate, endpoint, _sort="name").content
    second = export(gate, endpoint, _sort="name").content
    assert first == second


# ---------------------------------------------------------------------------
# Phrase: "all errors use the standard JSON envelope" (Error Handling)
# Context: applied to the export route's own failure modes.
# ---------------------------------------------------------------------------
def test_export_of_unknown_dataset_is_404_envelope(gate):
    resp = gate.get("/datasets/nosuchdataset/export")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]
