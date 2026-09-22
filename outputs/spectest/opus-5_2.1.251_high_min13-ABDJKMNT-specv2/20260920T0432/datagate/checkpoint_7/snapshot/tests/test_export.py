"""CSV export: GET /datasets/<id>/export."""

import csv
import io

PEOPLE = "name,age,city\ngrace,45,hopper\nada,36,london\nalan,41,london\n"


def rows_of(response):
    """The exported CSV parsed back into records, header first."""
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def export(client, convert, body=PEOPLE, query=None):
    endpoint = convert(body).get_json()["endpoint"]
    return client.get(f"{endpoint}/export", query_string=query or {})


# Spec: "`GET /datasets/<id>/export` returns CSV bytes"
# Context: the export of a converted dataset is its header row plus its rows.
def test_export_returns_csv_bytes(client, convert):
    response = export(client, convert)
    assert response.status_code == 200
    assert rows_of(response) == [
        ["name", "age", "city"],
        ["grace", "45", "hopper"],
        ["ada", "36", "london"],
        ["alan", "41", "london"],
    ]


# Spec: "- `Content-Type: text/csv`"
# Context: the body is served as CSV, not as JSON (AMBIGUITIES T36).
def test_export_content_type(client, convert):
    response = export(client, convert)
    assert response.headers["Content-Type"].startswith("text/csv")
    assert response.mimetype == "text/csv"


# Spec: "- `Content-Disposition: attachment; filename="<dataset-id>.csv"`"
# Context: the filename is the dataset id the endpoint was read from.
def test_export_content_disposition_names_the_dataset(client, convert):
    endpoint = convert(PEOPLE).get_json()["endpoint"]
    identifier = endpoint.rsplit("/", 1)[1]
    response = client.get(f"{endpoint}/export")
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="{identifier}.csv"'
    )


# Spec: "The CSV uses source column order"
# Context: the header row repeats the source header, in source order.
def test_export_header_follows_source_column_order(client, convert):
    response = export(client, convert, "zeta,alpha,mid\n1,2,3\n")
    assert rows_of(response)[0] == ["zeta", "alpha", "mid"]


# Spec: "applies the same filters ... as `/datasets/<id>`"
# Context: a filter narrows the exported rows exactly as it narrows the JSON.
def test_export_applies_filters(client, convert):
    response = export(client, convert, query={"city__exact": "london"})
    assert rows_of(response) == [
        ["name", "age", "city"],
        ["ada", "36", "london"],
        ["alan", "41", "london"],
    ]


# Spec: "applies the same ... sort ... as `/datasets/<id>`"
# Context: `_sort` and `_sort_desc` order the exported rows.
def test_export_applies_sort(client, convert):
    ascending = export(client, convert, query={"_sort": "name"})
    descending = export(client, convert, query={"_sort_desc": "name"})
    assert [row[0] for row in rows_of(ascending)[1:]] == ["ada", "alan", "grace"]
    assert [row[0] for row in rows_of(descending)[1:]] == ["grace", "alan", "ada"]


# Spec: "applies the same ... pagination as `/datasets/<id>`"
# Context: `_size` and `_offset` cut the same window out of the sorted rows.
def test_export_applies_pagination(client, convert):
    response = export(client, convert, query={"_sort": "name", "_size": "1", "_offset": "1"})
    assert rows_of(response) == [["name", "age", "city"], ["alan", "41", "london"]]


# Spec: "export rows follow filter -> sort -> paginate."
# Context: the three stages compose in that order, so the window is cut last.
def test_export_orders_filter_sort_paginate(client, convert):
    response = export(
        client, convert, query={"city__exact": "london", "_sort_desc": "age", "_size": "1"}
    )
    assert rows_of(response) == [["name", "age", "city"], ["alan", "41", "london"]]


# Spec: "applies the same ... pagination as `/datasets/<id>`"
# Context: with no `_size`, the default page size still caps the export
# (AMBIGUITIES T26).
def test_export_uses_the_default_page_size(client, convert):
    body = "n,squared\n" + "".join(f"{i},{i * i}\n" for i in range(150))
    assert len(rows_of(export(client, convert, body))) == 101


# Spec: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: all their accepted values leave the same bytes behind.
def test_shape_rowid_and_total_do_not_change_the_csv(client, convert):
    plain = export(client, convert).get_data()
    for query in (
        {"_shape": "objects"},
        {"_shape": "lists"},
        {"_rowid": "hide"},
        {"_total": "hide"},
        {"_shape": "objects", "_rowid": "hide", "_total": "hide"},
    ):
        assert export(client, convert, query=query).get_data() == plain, query


# Spec: "`_rowid` ... do not affect CSV output."
# Context: no rowid column is added to the export, in either shape.
def test_export_carries_no_rowid_column(client, convert):
    header = rows_of(export(client, convert, query={"_shape": "objects"}))[0]
    assert header == ["name", "age", "city"]


# Spec: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: being ignored is not the same as being unvalidated (AMBIGUITIES T27).
def test_export_still_rejects_unusable_control_values(client, convert):
    for query in ({"_shape": "fancy"}, {"_rowid": "yes"}, {"_total": "1"}, {"_size": "-1"}):
        response = export(client, convert, query=query)
        assert response.status_code == 400, query
        assert response.get_json()["ok"] is False


# Spec: "all errors use the standard JSON envelope"
# Context: exporting a dataset that was never converted.
def test_export_of_unknown_dataset_is_404(client):
    response = client.get("/datasets/nope/export")
    assert response.status_code == 404
    assert response.get_json() == {"ok": False, "error": response.get_json()["error"]}
    assert response.mimetype == "application/json"


# Spec: "all errors use the standard JSON envelope"
# Context: a bad filter on the export route answers like the JSON route does.
def test_export_filter_errors_use_the_envelope(client, convert):
    response = export(client, convert, query={"nosuch__exact": "x"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "semantically-correct CSV is required"
# Context: cells holding the delimiter, quotes or newlines survive a round trip.
def test_export_quotes_awkward_cells(client, convert):
    body = 'name;note\nada;"a, comma"\ngrace;"a ""quote"""\n'
    response = export(client, convert, body)
    assert rows_of(response) == [
        ["name", "note"],
        ["ada", "a, comma"],
        ["grace", 'a "quote"'],
    ]
