"""Spec section: Export, Upload, and Multi-Format Support -> export."""

import csv
import io

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\ncarol,25\n"


def read_csv(response):
    """Parse the exported body as CSV; returns [[cell, ...], ...] of strings."""
    text = response.get_data(as_text=True)
    return [row for row in csv.reader(io.StringIO(text, newline="")) if row]


@pytest.fixture
def export(convert, client):
    """Ingest a CSV and GET its /export endpoint with `query`."""

    def _export(path, body, query=None, **kwargs):
        response = convert(path, body, **kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        endpoint = response.get_json()["endpoint"]
        return client.get(endpoint + "/export", query_string=query or {})

    return _export


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
def test_export_returns_ok(export):
    response = export("/e-ok.csv", SIMPLE)
    assert response.status_code == 200


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
# Context: the body is bytes that parse as CSV, not a JSON envelope.
def test_export_body_is_csv_bytes(export):
    response = export("/e-bytes.csv", SIMPLE)
    assert isinstance(response.get_data(), bytes)
    assert read_csv(response) == [
        ["name", "age"], ["alice", "30"], ["bob", "41"], ["carol", "25"],
    ]


# Phrase: "- `Content-Type: text/csv`"
def test_export_content_type_is_text_csv(export):
    response = export("/e-ct.csv", SIMPLE)
    assert response.headers["Content-Type"].split(";")[0].strip() == "text/csv"


# Phrase: "- `Content-Type: text/csv`"
# Context: the spec writes the header value with no parameters attached.
def test_export_content_type_header_verbatim(export):
    response = export("/e-ct2.csv", SIMPLE)
    assert response.headers["Content-Type"] == "text/csv"


# Phrase: '- `Content-Disposition: attachment; filename="<dataset-id>.csv"`'
def test_export_content_disposition(export, convert):
    response = convert("/e-cd.csv", SIMPLE)
    identifier = response.get_json()["endpoint"].rsplit("/", 1)[-1]
    exported = export("/e-cd.csv", SIMPLE)
    assert exported.headers["Content-Disposition"] == (
        'attachment; filename="{}.csv"'.format(identifier)
    )


# Phrase: '- `Content-Disposition: attachment; filename="<dataset-id>.csv"`'
# Context: the filename stem is the dataset id, not the source file name.
def test_export_filename_is_dataset_id_not_source_name(export, convert):
    identifier = convert("/e-name.csv", SIMPLE).get_json()["endpoint"].rsplit("/", 1)[-1]
    disposition = export("/e-name.csv", SIMPLE).headers["Content-Disposition"]
    assert "e-name.csv" not in disposition
    assert identifier in disposition


# Phrase: "The CSV uses source column order"
def test_export_header_row_is_source_column_order(export):
    response = export("/e-order.csv", "z,a,m\n1,2,3\n")
    assert read_csv(response)[0] == ["z", "a", "m"]


# Phrase: "The CSV uses source column order"
# Context: values in each data row line up positionally with the header.
def test_export_rows_follow_column_order(export):
    response = export("/e-order2.csv", "z,a,m\n1,2,3\n4,5,6\n")
    assert read_csv(response) == [["z", "a", "m"], ["1", "2", "3"], ["4", "5", "6"]]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
def test_export_applies_exact_filter(export):
    response = export("/e-filter.csv", SIMPLE, query={"name__exact": "bob"})
    assert read_csv(response) == [["name", "age"], ["bob", "41"]]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: numeric comparators too.
def test_export_applies_greater_filter(export):
    response = export("/e-gt.csv", SIMPLE, query={"age__greater": "26"})
    assert [row[0] for row in read_csv(response)[1:]] == ["alice", "bob"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: a filter matching nothing leaves the header row alone.
def test_export_filter_matching_nothing_keeps_header(export):
    response = export("/e-none.csv", SIMPLE, query={"name__exact": "zoe"})
    assert read_csv(response) == [["name", "age"]]


# Phrase: "applies the same filters, sort, ... as `/datasets/<id>`"
def test_export_applies_sort(export):
    response = export("/e-sort.csv", SIMPLE, query={"_sort": "age"})
    assert [row[0] for row in read_csv(response)[1:]] == ["carol", "alice", "bob"]


# Phrase: "applies the same filters, sort, ... as `/datasets/<id>`"
# Context: `_sort_desc` reverses the order.
def test_export_applies_sort_desc(export):
    response = export("/e-sortd.csv", SIMPLE, query={"_sort_desc": "age"})
    assert [row[0] for row in read_csv(response)[1:]] == ["bob", "alice", "carol"]


# Phrase: "applies the same filters, sort, and pagination as `/datasets/<id>`"
def test_export_applies_size(export):
    response = export("/e-size.csv", SIMPLE, query={"_size": "2"})
    assert [row[0] for row in read_csv(response)[1:]] == ["alice", "bob"]


# Phrase: "applies the same filters, sort, and pagination as `/datasets/<id>`"
def test_export_applies_offset(export):
    response = export("/e-offset.csv", SIMPLE, query={"_offset": "1", "_size": "1"})
    assert [row[0] for row in read_csv(response)[1:]] == ["bob"]


# Phrase: "export rows follow filter -> sort -> paginate." (Determinism)
def test_export_pipeline_is_filter_then_sort_then_paginate(export):
    body = "name,age\nalice,30\nbob,41\ncarol,25\ndan,55\nerin,33\n"
    response = export(
        "/e-pipeline.csv", body,
        query={"age__greater": "26", "_sort_desc": "age", "_size": "2"},
    )
    # filter -> alice/bob/dan/erin; sort desc -> dan/bob/erin/alice; take 2.
    assert [row[0] for row in read_csv(response)[1:]] == ["dan", "bob"]


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
# Context: the default page size of `/datasets/<id>` is 100 rows.
def test_export_defaults_to_the_same_page_size(export):
    body = "id,val\n" + "".join("{},{}\n".format(i, i) for i in range(1, 151))
    response = export("/e-default.csv", body)
    assert len(read_csv(response)) == 101  # header + the default 100 rows


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
def test_shape_objects_does_not_change_csv(export):
    plain = read_csv(export("/e-shape-a.csv", SIMPLE))
    shaped = read_csv(export("/e-shape-b.csv", SIMPLE, query={"_shape": "objects"}))
    assert plain == shaped


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
def test_shape_lists_does_not_change_csv(export):
    plain = read_csv(export("/e-shape-c.csv", SIMPLE))
    shaped = read_csv(export("/e-shape-d.csv", SIMPLE, query={"_shape": "lists"}))
    assert plain == shaped


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: no `rowid` column is ever emitted, with or without `_rowid=hide`.
def test_export_never_emits_a_rowid_column(export):
    for query in ({}, {"_rowid": "hide"}, {"_shape": "objects"}):
        response = export("/e-rowid.csv", SIMPLE, query=query)
        assert read_csv(response)[0] == ["name", "age"]


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
def test_rowid_hide_does_not_change_csv(export):
    plain = read_csv(export("/e-rid-a.csv", SIMPLE))
    hidden = read_csv(export("/e-rid-b.csv", SIMPLE, query={"_rowid": "hide"}))
    assert plain == hidden


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: nothing resembling a total is appended to the CSV either way.
def test_total_hide_does_not_change_csv(export):
    plain = read_csv(export("/e-tot-a.csv", SIMPLE))
    hidden = read_csv(export("/e-tot-b.csv", SIMPLE, query={"_total": "hide"}))
    assert plain == hidden
    assert len(plain) == 4


# Phrase: "semantically-correct CSV is required; exact newline/quoting is not."
def test_export_quotes_embedded_delimiters_and_quotes(export):
    body = 'name,note\nalice,"a,b"\nbob,"say ""hi"""\n'
    response = export("/e-quote.csv", body)
    assert read_csv(response) == [
        ["name", "note"], ["alice", "a,b"], ["bob", 'say "hi"'],
    ]


# Phrase: "semantically-correct CSV is required; exact newline/quoting is not."
# Context: an embedded newline must survive a round-trip through the export.
def test_export_preserves_embedded_newlines(export):
    body = 'name,note\nalice,"line1\nline2"\n'
    response = export("/e-nl.csv", body)
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True), newline="")))
    assert ["alice", "line1\nline2"] in rows


# Phrase: "semantically-correct CSV is required"
# Context: numeric cells are written as bare numbers, not JSON literals.
def test_export_writes_numbers_without_json_decoration(export):
    response = export("/e-num.csv", "a,b\n1,2.5\n")
    assert read_csv(response)[1] == ["1", "2.5"]


# Phrase: "all errors use the standard JSON envelope" (Error Handling)
# Context: an unknown dataset id is still a 404 on the export route.
def test_export_unknown_dataset_is_404_envelope(client):
    response = client.get("/datasets/deadbeefdeadbeef/export")
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False and isinstance(payload["error"], str)


# Phrase: "applies the same filters, sort, and pagination as `/datasets/<id>`"
# Context: the same invalid controls that 400 on /datasets 400 here too.
@pytest.mark.parametrize("query", [
    {"_sort": "nosuch"}, {"_size": "0"}, {"_offset": "-1"}, {"nosuch__exact": "x"},
])
def test_export_rejects_invalid_controls(export, query):
    response = export("/e-bad.csv", SIMPLE, query=query)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
