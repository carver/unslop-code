"""Tests for the /datasets control parameters: pagination, sorting and shape."""

import pytest

CSV = (
    b"name,age,city\n"
    b"ada,36,london\n"
    b"grace,45,new york\n"
    b"alan,41,wilmslow\n"
    b"edsger,36,austin\n"
)


@pytest.fixture
def endpoint(client, serve):
    """Convert the four-row fixture CSV and return its dataset endpoint."""
    source = serve("people.csv", CSV)
    return client.get("/convert", query_string={"source": source}).json["endpoint"]


def query(client, endpoint, **controls):
    return client.get(endpoint, query_string=controls)


def names(response):
    return [row[0] for row in response.json["rows"]]


def test_total_counts_rows_before_pagination(client, endpoint):
    response = query(client, endpoint, _size=2)

    assert response.json["total"] == 4
    assert len(response.json["rows"]) == 2


def test_size_beyond_available_rows_returns_all(client, endpoint):
    assert len(query(client, endpoint, _size=500).json["rows"]) == 4


def test_offset_skips_rows(client, endpoint):
    assert names(query(client, endpoint, _offset=2)) == ["alan", "edsger"]


def test_offset_past_the_end_returns_no_rows(client, endpoint):
    response = query(client, endpoint, _offset=10)

    assert response.json["rows"] == []
    assert response.json["total"] == 4


def test_size_and_offset_paginate_together(client, endpoint):
    assert names(query(client, endpoint, _size=2, _offset=1)) == ["grace", "alan"]


def test_sort_orders_ascending(client, endpoint):
    assert names(query(client, endpoint, _sort="name")) == [
        "ada",
        "alan",
        "edsger",
        "grace",
    ]


def test_sort_desc_orders_descending(client, endpoint):
    assert names(query(client, endpoint, _sort_desc="age")) == [
        "grace",
        "alan",
        "ada",
        "edsger",
    ]


def test_sort_desc_wins_when_both_are_given(client, endpoint):
    response = client.get(f"{endpoint}?_sort=name&_sort_desc=age")

    assert names(response) == ["grace", "alan", "ada", "edsger"]


def test_sorting_is_stable_for_equal_values(client, endpoint):
    assert names(query(client, endpoint, _sort="age"))[:2] == ["ada", "edsger"]
    assert names(query(client, endpoint, _sort_desc="age"))[2:] == ["ada", "edsger"]


def test_sorting_is_applied_before_pagination(client, endpoint):
    assert names(query(client, endpoint, _sort="name", _size=1, _offset=3)) == ["grace"]


def test_mixed_value_types_sort_without_error(client, serve):
    source = serve("mixed.csv", b"label,score\na,3\nb,n/a\nc,1.5\n")
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]

    assert names(query(client, endpoint, _sort="score")) == ["c", "a", "b"]


def test_default_shape_is_lists(client, endpoint):
    assert query(client, endpoint, _size=1).json["rows"] == [["ada", 36, "london"]]


def test_objects_shape_names_cells_and_adds_rowid(client, endpoint):
    response = query(client, endpoint, _shape="objects", _size=1, _offset=1)

    assert response.json["rows"] == [
        {"rowid": 2, "name": "grace", "age": 45, "city": "new york"}
    ]
    assert response.json["columns"] == ["name", "age", "city"]


def test_rowid_follows_the_source_row_through_sorting(client, endpoint):
    response = query(client, endpoint, _shape="objects", _sort_desc="name")

    assert [row["rowid"] for row in response.json["rows"]] == [2, 4, 3, 1]


def test_rowid_hide_removes_rowid(client, endpoint):
    response = query(client, endpoint, _shape="objects", _rowid="hide", _size=1)

    assert response.json["rows"] == [{"name": "ada", "age": 36, "city": "london"}]


def test_total_hide_removes_total(client, endpoint):
    assert "total" not in query(client, endpoint, _total="hide").json


@pytest.mark.parametrize(
    "controls",
    [
        {"_size": "0"},
        {"_size": "-1"},
        {"_size": "two"},
        {"_size": ""},
        {"_size": "1.5"},
        {"_offset": "-1"},
        {"_offset": "last"},
        {"_shape": "tuples"},
        {"_rowid": "show"},
        {"_total": ""},
        {"_sort": "height"},
        {"_sort": ""},
        {"_sort_desc": "height"},
        {"_sort_desc": ""},
    ],
)
def test_invalid_control_values_are_rejected(client, endpoint, controls):
    response = query(client, endpoint, **controls)

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


@pytest.mark.parametrize(
    "control", ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]
)
def test_repeated_control_parameters_are_rejected(client, endpoint, control):
    response = client.get(f"{endpoint}?{control}=1&{control}=1")

    assert response.status_code == 400
    assert response.json["ok"] is False
