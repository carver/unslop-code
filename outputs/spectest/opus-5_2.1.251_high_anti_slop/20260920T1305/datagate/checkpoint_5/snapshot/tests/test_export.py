"""Tests for CSV export via GET /datasets/<id>/export."""

import csv
import io

import pytest

PEOPLE = (
    b"name,age,city\n"
    b"ada,36,london\n"
    b"alan,41,wilmslow\n"
    b"grace,45,new york\n"
)


@pytest.fixture
def people(upload):
    """Upload the sample dataset and return its export endpoint."""
    return upload(PEOPLE).json["endpoint"] + "/export"


def exported(response):
    """Read an export response back as a list of rows of text."""
    return list(csv.reader(io.StringIO(response.data.decode("utf-8"))))


def test_export_is_a_csv_attachment(client, upload):
    endpoint = upload(PEOPLE).json["endpoint"]

    response = client.get(f"{endpoint}/export")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv"
    identifier = endpoint.rsplit("/", 1)[1]
    assert (
        response.headers["Content-Disposition"]
        == f'attachment; filename="{identifier}.csv"'
    )


def test_export_leads_with_the_source_column_order(client, people):
    assert exported(client.get(people))[0] == ["name", "age", "city"]


def test_export_writes_every_row(client, people):
    assert exported(client.get(people))[1:] == [
        ["ada", "36", "london"],
        ["alan", "41", "wilmslow"],
        ["grace", "45", "new york"],
    ]


def test_export_applies_filters(client, people):
    response = client.get(people, query_string={"age__greater": "40"})

    assert exported(response)[1:] == [
        ["alan", "41", "wilmslow"],
        ["grace", "45", "new york"],
    ]


def test_export_sorts_before_paginating(client, people):
    response = client.get(people, query_string={"_sort_desc": "age", "_size": "2"})

    assert exported(response)[1:] == [
        ["grace", "45", "new york"],
        ["alan", "41", "wilmslow"],
    ]


def test_export_honours_the_offset(client, people):
    response = client.get(people, query_string={"_offset": "2"})

    assert exported(response)[1:] == [["grace", "45", "new york"]]


@pytest.mark.parametrize(
    "ignored",
    [{"_shape": "objects"}, {"_shape": "objects", "_rowid": "hide"}, {"_total": "hide"}],
)
def test_shape_controls_do_not_change_the_export(client, people, ignored):
    assert exported(client.get(people, query_string=ignored)) == exported(
        client.get(people)
    )


def test_export_quotes_cells_that_need_it(client, upload):
    endpoint = upload(b'note;n\n"hello, world";1\n').json["endpoint"]

    response = client.get(f"{endpoint}/export")

    assert exported(response) == [["note", "n"], ["hello, world", "1"]]


def test_export_of_an_unknown_dataset_is_not_found(client):
    response = client.get("/datasets/0123456789abcdef/export")

    assert response.status_code == 404
    assert response.json["ok"] is False


def test_export_rejects_a_bad_control_parameter(client, people):
    response = client.get(people, query_string={"_size": "0"})

    assert response.status_code == 400
    assert response.json["ok"] is False
