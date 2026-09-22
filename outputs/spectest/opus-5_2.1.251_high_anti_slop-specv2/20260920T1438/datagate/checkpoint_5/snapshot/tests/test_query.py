"""Pagination, sorting and response controls of ``GET /datasets/<id>``."""

import pytest

from gateway.query import CONTROLS

TABLE = b"name,score\nada,36\nlin,7\nbo,22\n"
#: Two rows share a score, so their relative order proves sorting is stable.
TIES = b"name,score\nada,7\nlin,7\nbo,1\n"


def names(response) -> list:
    """The first cell of every returned row, whatever shape was asked for."""
    rows = response.get_json()["rows"]
    return [row["name"] if isinstance(row, dict) else row[0] for row in rows]


def test_total_counts_rows_before_pagination(read):
    body = read(TABLE, _size=1).get_json()
    assert body["total"] == 3
    assert len(body["rows"]) == 1


def test_size_defaults_to_one_hundred(read):
    payload = b"n\n" + b"".join(b"%d\n" % index for index in range(250))
    body = read(payload).get_json()
    assert len(body["rows"]) == 100
    assert body["total"] == 250


def test_size_beyond_the_table_returns_every_row(read):
    assert len(read(TABLE, _size=500).get_json()["rows"]) == 3


def test_offset_skips_rows(read):
    assert names(read(TABLE, _offset=1)) == ["lin", "bo"]


def test_offset_beyond_the_table_returns_no_rows(read):
    body = read(TABLE, _offset=9).get_json()
    assert body["rows"] == []
    assert body["total"] == 3


def test_size_and_offset_select_a_window(read):
    assert names(read(TABLE, _offset=1, _size=1)) == ["lin"]


@pytest.mark.parametrize("size", ["0", "-1", "1.5", "abc", ""])
def test_invalid_size_is_rejected(read, size):
    response = read(TABLE, _size=size)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("offset", ["-1", "1.5", "abc", ""])
def test_invalid_offset_is_rejected(read, offset):
    assert read(TABLE, _offset=offset).status_code == 400


def test_sort_orders_ascending(read):
    assert names(read(TABLE, _sort="score")) == ["lin", "bo", "ada"]


def test_sort_desc_orders_descending(read):
    assert names(read(TABLE, _sort_desc="score")) == ["ada", "bo", "lin"]


def test_sort_desc_wins_over_sort(read):
    assert names(read(TABLE, _sort="name", _sort_desc="score")) == ["ada", "bo", "lin"]


def test_sorting_keeps_tied_rows_in_source_order(read):
    assert names(read(TIES, _sort="score")) == ["bo", "ada", "lin"]
    assert names(read(TIES, _sort_desc="score")) == ["ada", "lin", "bo"]


def test_sorting_happens_before_pagination(read):
    assert names(read(TABLE, _sort_desc="score", _size=1)) == ["ada"]


def test_sorting_orders_text_columns(read):
    assert names(read(TABLE, _sort="name")) == ["ada", "bo", "lin"]


@pytest.mark.parametrize("parameter", ["_sort", "_sort_desc"])
@pytest.mark.parametrize("column", ["", "missing"])
def test_unknown_sort_column_is_rejected(read, parameter, column):
    response = read(TABLE, **{parameter: column})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_lists_is_the_default_shape(read):
    assert read(TABLE).get_json()["rows"][0] == ["ada", 36]
    assert read(TABLE, _shape="lists").get_json()["rows"][0] == ["ada", 36]


def test_objects_shape_keys_rows_by_column(read):
    body = read(TABLE, _shape="objects").get_json()
    assert body["rows"][0] == {"rowid": 2, "name": "ada", "score": 36}
    assert body["columns"] == ["name", "score"]


def test_rowid_follows_the_source_row_through_sorting(read):
    body = read(TABLE, _shape="objects", _sort="score", _offset=1).get_json()
    assert [row["rowid"] for row in body["rows"]] == [4, 2]


@pytest.mark.parametrize("shape", ["arrays", "", "OBJECTS"])
def test_unknown_shape_is_rejected(read, shape):
    assert read(TABLE, _shape=shape).status_code == 400


def test_rowid_can_be_hidden(read):
    body = read(TABLE, _shape="objects", _rowid="hide").get_json()
    assert body["rows"][0] == {"name": "ada", "score": 36}


def test_total_can_be_hidden(read):
    assert "total" not in read(TABLE, _total="hide").get_json()


@pytest.mark.parametrize("parameter", ["_rowid", "_total"])
@pytest.mark.parametrize("value", ["show", "", "Hide"])
def test_toggles_accept_only_hide(read, parameter, value):
    response = read(TABLE, **{parameter: value})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("parameter", CONTROLS)
def test_repeated_control_parameter_is_rejected(client, convert, parameter):
    endpoint = convert(TABLE).get_json()["endpoint"]
    response = client.get(endpoint, query_string={parameter: ["1", "2"]})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
