"""Tests for the CSV export endpoint."""

import csv
import io

from helpers import endpoint_of


def export(client, base_url, fixture, **params):
    return client.get(f"{endpoint_of(client, base_url, fixture)}/export", query_string=params)


def exported(response):
    """Read an export response back as rows of text, so quoting style does not matter."""
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def test_export_is_a_named_csv_attachment(client, base_url):
    endpoint = endpoint_of(client, base_url, "basic.csv")
    response = client.get(f"{endpoint}/export")
    dataset_id = endpoint.rsplit("/", 1)[1]
    assert response.headers["Content-Type"] == "text/csv"
    assert response.headers["Content-Disposition"] == f'attachment; filename="{dataset_id}.csv"'


def test_export_writes_the_header_then_the_rows_in_source_order(client, base_url):
    assert exported(export(client, base_url, "basic.csv")) == [
        ["name", "age", "score", "start"],
        ["Ada", "36", "9.5", "08:30"],
        ["Grace", "45", "8.25", "9:15"],
    ]


def test_export_quotes_cells_that_need_it(client, base_url):
    assert exported(export(client, base_url, "quoted.csv"))[1:] == [
        ["Ada", "first, and foremost"],
        ["Grace", 'said "hi"'],
    ]


def test_export_carries_non_ascii_text(client, base_url):
    assert exported(export(client, base_url, "latin1.csv"))[1] == ["José", "Málaga"]


def test_export_applies_filters_then_sorting_then_pagination(client, base_url):
    response = export(
        client, base_url, "staff.csv", rating__greater="0", _sort_desc="age", _size=2
    )
    assert exported(response) == [
        ["name", "role", "age", "rating"],
        ["Grace", "engineer", "45", "8.25"],
        ["Alan", "analyst", "41", "9.5"],
    ]


def test_export_paginates_like_the_dataset_endpoint(client, base_url):
    rows = exported(export(client, base_url, "wide.csv", _size=3, _offset=2))
    assert rows == [["n", "label"], ["2", "row2"], ["3", "row3"], ["4", "row4"]]


def test_shape_parameters_do_not_change_the_csv(client, base_url):
    plain = export(client, base_url, "basic.csv").get_data()
    shaped = export(
        client, base_url, "basic.csv", _shape="objects", _rowid="hide", _total="hide"
    ).get_data()
    assert shaped == plain


def test_export_follows_the_source_column_order_of_a_workbook(client, base_url):
    assert exported(export(client, base_url, "staff.xlsx"))[:2] == [
        ["name", "role", "age", "rating"],
        ["Ada", "engineer", "36", "9.5"],
    ]


def test_export_of_an_unknown_dataset_is_a_json_404(client):
    response = client.get("/datasets/deadbeef/export")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_export_rejects_a_bad_query_parameter(client, base_url):
    response = export(client, base_url, "basic.csv", _sort="nope")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
