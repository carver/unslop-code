"""Spec section: Export, Upload, and Multi-Format Support -> `GET /datasets/<id>/export`."""

import csv
import io

CSV = "name,age,city\nada,36,london\ngrace,45,new york\nalan,41,london\n"


def records(response):
    """Parse an export body back into its header row and its data rows."""
    parsed = list(csv.reader(io.StringIO(response.get_data(as_text=True), newline="")))
    return parsed[0], [row for row in parsed[1:] if row]


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
def test_export_returns_the_table_as_csv(client, dataset):
    response = client.get(dataset(CSV) + "/export")

    assert response.status_code == 200
    header, rows = records(response)
    assert header == ["name", "age", "city"]
    assert rows == [["ada", "36", "london"], ["grace", "45", "new york"], ["alan", "41", "london"]]


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
# Context: the payload is bytes, not a JSON envelope.
def test_export_body_is_not_json(client, dataset):
    response = client.get(dataset(CSV) + "/export")

    assert isinstance(response.get_data(), bytes)
    assert not response.get_data().startswith(b"{")


# Phrase: "- `Content-Type: text/csv`"
def test_export_content_type_is_text_csv(client, dataset):
    response = client.get(dataset(CSV) + "/export")

    assert response.headers["Content-Type"] == "text/csv"


# Phrase: '- `Content-Disposition: attachment; filename="<dataset-id>.csv"`'
def test_export_is_an_attachment_named_after_the_dataset(client, dataset):
    endpoint = dataset(CSV)
    identifier = endpoint.removeprefix("/datasets/")

    response = client.get(endpoint + "/export")

    assert response.headers["Content-Disposition"] == f'attachment; filename="{identifier}.csv"'


# Phrase: "The CSV uses source column order"
def test_export_columns_follow_source_order(client, dataset):
    response = client.get(dataset("z,m,a\n1,2,3\n") + "/export")

    header, rows = records(response)
    assert header == ["z", "m", "a"]
    assert rows == [["1", "2", "3"]]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
def test_export_applies_filters(client, dataset):
    response = client.get(dataset(CSV) + "/export?city__exact=london")

    _, rows = records(response)
    assert [row[0] for row in rows] == ["ada", "alan"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
# Context: numeric comparators work on the export route too.
def test_export_applies_numeric_filters(client, dataset):
    response = client.get(dataset(CSV) + "/export?age__greater=40")

    _, rows = records(response)
    assert [row[0] for row in rows] == ["grace", "alan"]


# Phrase: "applies the same ... sort ... as `/datasets/<id>`"
def test_export_applies_sort(client, dataset):
    endpoint = dataset(CSV)

    ascending = client.get(endpoint + "/export?_sort=age")
    descending = client.get(endpoint + "/export?_sort_desc=age")

    assert [row[0] for row in records(ascending)[1]] == ["ada", "alan", "grace"]
    assert [row[0] for row in records(descending)[1]] == ["grace", "alan", "ada"]


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
def test_export_applies_size_and_offset(client, dataset):
    response = client.get(dataset(CSV) + "/export?_size=1&_offset=1")

    header, rows = records(response)
    assert header == ["name", "age", "city"]
    assert rows == [["grace", "45", "new york"]]


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
# Context: the default page size of 100 applies to an unparameterised export
# (AMBIGUITIES T33).
def test_export_uses_the_default_page_size(client, dataset):
    body = "n,v\n" + "".join(f"{index},x\n" for index in range(150))

    response = client.get(dataset(body) + "/export")

    assert len(records(response)[1]) == 100


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
def test_shape_does_not_change_the_bytes(client, dataset):
    endpoint = dataset(CSV)

    default = client.get(endpoint + "/export")
    objects = client.get(endpoint + "/export?_shape=objects")

    assert objects.get_data() == default.get_data()


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: no `rowid` column is ever added to the CSV.
def test_export_never_carries_a_rowid_column(client, dataset):
    endpoint = dataset(CSV)

    shown = client.get(endpoint + "/export?_shape=objects")
    hidden = client.get(endpoint + "/export?_shape=objects&_rowid=hide")

    assert "rowid" not in records(shown)[0]
    assert hidden.get_data() == shown.get_data()


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
def test_total_hide_does_not_change_the_bytes(client, dataset):
    endpoint = dataset(CSV)

    default = client.get(endpoint + "/export")
    hidden = client.get(endpoint + "/export?_total=hide")

    assert hidden.get_data() == default.get_data()


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output."
# Context: they are still validated as on `/datasets/<id>` (AMBIGUITIES T34).
def test_invalid_shape_is_still_rejected(client, dataset):
    response = client.get(dataset(CSV) + "/export?_shape=banana")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "all errors use the standard JSON envelope"
# Context: an unknown dataset id on the export route.
def test_export_of_unknown_dataset_is_404(client):
    response = client.get("/datasets/deadbeefdeadbeef/export")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "all errors use the standard JSON envelope"
# Context: a bad control or filter on export answers JSON, not CSV.
def test_export_errors_answer_json(client, dataset):
    endpoint = dataset(CSV)

    assert client.get(endpoint + "/export?_size=0").status_code == 400
    assert client.get(endpoint + "/export?nope__exact=x").get_json()["ok"] is False


# Phrase: "semantically-correct CSV is required; exact newline/quoting is not."
def test_export_quotes_cells_containing_delimiters_and_quotes(client, dataset):
    source = 'name,note\nada,"a, b"\ngrace,"say ""hi"""\n'

    response = client.get(dataset(source) + "/export")

    assert records(response)[1] == [["ada", "a, b"], ["grace", 'say "hi"']]


# Phrase: "semantically-correct CSV is required; exact newline/quoting is not."
# Context: a cell holding a newline survives the round trip.
def test_export_preserves_embedded_newlines(client, dataset):
    source = 'name,note\nada,"line one\nline two"\n'

    response = client.get(dataset(source) + "/export")

    assert records(response)[1] == [["ada", "line one\nline two"]]


# Phrase: "export rows follow filter -> sort -> paginate."
def test_export_orders_the_three_stages(client, dataset):
    body = "name,age,city\nada,36,london\ngrace,45,london\nalan,41,london\nedsger,30,delft\n"

    response = client.get(dataset(body) + "/export?city__exact=london&_sort_desc=age&_size=2")

    _, rows = records(response)
    assert [row[0] for row in rows] == ["grace", "alan"]


# Phrase: "export columns follow source column order."
# Context: filters and sorting never reorder or drop columns.
def test_export_columns_survive_filtering_and_sorting(client, dataset):
    response = client.get(dataset(CSV) + "/export?_sort_desc=name&city__contains=lond")

    assert records(response)[0] == ["name", "age", "city"]
