"""Spec section: Export, Upload, and Multi-Format Support -- CSV export."""

import csv
from io import StringIO

from conftest import SIMPLE_CSV, SOURCE_URL

from datagate_app.store import dataset_id


def rows_of(response):
    """Parse an export response body back into a list of CSV records."""
    return list(csv.reader(StringIO(response.get_data(as_text=True))))


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
def test_export_returns_the_table_as_csv(client, endpoint):
    response = client.get(endpoint() + "/export")

    assert response.status_code == 200
    assert rows_of(response) == [["name", "age"], ["ada", "36"], ["grace", "45"]]


# Phrase: "`Content-Type: text/csv`"
def test_export_declares_the_csv_content_type(client, endpoint):
    response = client.get(endpoint() + "/export")

    assert response.headers["Content-Type"] == "text/csv"


# Phrase: "`Content-Disposition: attachment; filename="<dataset-id>.csv"`"
def test_export_declares_an_attachment_named_after_the_dataset(client, endpoint):
    response = client.get(endpoint() + "/export")

    expected = f'attachment; filename="{dataset_id(SOURCE_URL)}.csv"'
    assert response.headers["Content-Disposition"] == expected


# Phrase: "The CSV uses source column order" (context: header order is not alphabetical)
def test_export_columns_follow_source_order(client, endpoint):
    response = client.get(endpoint("z,a,m\n1,2,3\n") + "/export")

    assert rows_of(response)[0] == ["z", "a", "m"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
def test_export_applies_filters(client, endpoint):
    response = client.get(endpoint() + "/export?age__greater=40")

    assert rows_of(response) == [["name", "age"], ["grace", "45"]]


# Phrase: "applies the same ... sort ... as `/datasets/<id>`"
def test_export_applies_sort(client, endpoint):
    response = client.get(endpoint() + "/export?_sort_desc=name")

    assert rows_of(response) == [["name", "age"], ["grace", "45"], ["ada", "36"]]


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
def test_export_applies_offset_and_size(client, endpoint):
    response = client.get(endpoint() + "/export?_offset=1&_size=1")

    assert rows_of(response) == [["name", "age"], ["grace", "45"]]


# Phrase: "applies the same ... pagination as `/datasets/<id>`" (context: the default page size, T33)
def test_export_applies_the_default_page_size(client, endpoint):
    body = "n\n" + "".join(f"{number}\n" for number in range(150))

    response = client.get(endpoint(body) + "/export")

    assert len(rows_of(response)) == 101


# Phrase: "export rows follow filter -> sort -> paginate."
def test_export_filters_before_sorting_and_paging(client, endpoint):
    body = "name,age\nada,36\ngrace,45\nalan,41\nedsger,30\n"

    response = client.get(endpoint(body) + "/export?age__greater=31&_sort=age&_offset=1&_size=1")

    assert rows_of(response) == [["name", "age"], ["alan", "41"]]


# Phrase: "`_shape` ... do not affect CSV output."
def test_shape_does_not_change_the_csv(client, endpoint):
    path = endpoint()

    assert client.get(path + "/export?_shape=objects").get_data() == client.get(path + "/export").get_data()


# Phrase: "`_rowid` ... do not affect CSV output."
def test_rowid_is_never_a_csv_column(client, endpoint):
    response = client.get(endpoint() + "/export?_shape=objects&_rowid=hide")

    assert rows_of(response)[0] == ["name", "age"]


# Phrase: "`_total` ... do not affect CSV output."
def test_total_does_not_change_the_csv(client, endpoint):
    path = endpoint()

    assert client.get(path + "/export?_total=hide").get_data() == client.get(path + "/export").get_data()


# Phrase: "`_shape`, `_rowid`, and `_total` do not affect CSV output." (context: still validated, T34)
def test_export_still_rejects_an_unusable_shape(client, endpoint):
    response = client.get(endpoint() + "/export?_shape=bogus")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "all errors use the standard JSON envelope" (context: export of an unknown dataset)
def test_export_of_an_unknown_dataset_is_404_json(client):
    response = client.get("/datasets/deadbeefdeadbeef/export")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False
    assert response.headers["Content-Type"].startswith("application/json")


# Phrase: "all errors use the standard JSON envelope" (context: a bad filter on export)
def test_export_reports_a_bad_filter_as_json(client, endpoint):
    response = client.get(endpoint() + "/export?nope__exact=1")

    assert response.status_code == 400
    assert "nope" in response.get_json()["error"]


# Phrase: "semantically-correct CSV is required" (context: cells containing the delimiter and quotes)
def test_export_quotes_cells_that_need_it(client, endpoint):
    response = client.get(endpoint('note\n"a,b"\n"say ""hi"""\n') + "/export")

    assert rows_of(response) == [["note"], ["a,b"], ['say "hi"']]


# Phrase: "semantically-correct CSV is required" (context: inferred values render as text, T36)
def test_export_renders_inferred_values(client, endpoint):
    response = client.get(endpoint("n,d,t\n36,2.5,ada\n") + "/export")

    assert rows_of(response)[1] == ["36", "2.5", "ada"]


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes" (context: export is deterministic)
def test_repeated_exports_are_byte_identical(client, endpoint):
    path = endpoint(SIMPLE_CSV)

    assert client.get(path + "/export").get_data() == client.get(path + "/export").get_data()


# Phrase: "applies the same filters ... as `/datasets/<id>`" (context: nothing matched)
def test_export_of_an_empty_result_is_header_only(client, endpoint):
    response = client.get(endpoint() + "/export?name__exact=nobody")

    assert response.status_code == 200
    assert rows_of(response) == [["name", "age"]]


# Phrase: "applies the same ... pagination as `/datasets/<id>`" (context: offset past the end)
def test_export_past_the_last_row_is_header_only(client, endpoint):
    response = client.get(endpoint() + "/export?_offset=99")

    assert rows_of(response) == [["name", "age"]]
