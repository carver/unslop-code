"""CSV download behaviour of ``GET /datasets/<id>/export``."""

import csv
import io

import pytest

TABLE = b"name,score\nada,36\nlin,7\nmax,12\n"


@pytest.fixture
def export(client, convert):
    """Convert ``TABLE`` and export it with the given control parameters."""

    def run(payload: bytes = TABLE, **controls):
        endpoint = convert(payload).get_json()["endpoint"]
        return client.get(f"{endpoint}/export", query_string=controls)

    return run


def rows_of(response) -> list[list[str]]:
    """Read the CSV body back into rows, header first."""
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def test_serves_a_named_csv_attachment(client, convert, export):
    endpoint = convert(TABLE).get_json()["endpoint"]
    identifier = endpoint.rsplit("/", 1)[1]

    response = export()
    assert response.mimetype == "text/csv"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="{identifier}.csv"'
    )


def test_header_and_rows_follow_source_order(export):
    assert rows_of(export()) == [
        ["name", "score"],
        ["ada", "36"],
        ["lin", "7"],
        ["max", "12"],
    ]


def test_filters_sort_and_pagination_apply(export):
    response = export(score__greater="8", _sort_desc="score", _size=1)
    assert rows_of(response) == [["name", "score"], ["ada", "36"]]


def test_offset_cuts_into_the_sorted_rows(export):
    response = export(_sort="score", _offset=1)
    assert rows_of(response)[1:] == [["max", "12"], ["ada", "36"]]


@pytest.mark.parametrize(
    "controls",
    [{"_shape": "objects"}, {"_rowid": "hide"}, {"_total": "hide"}],
)
def test_response_shaping_parameters_do_not_change_the_csv(export, controls):
    assert rows_of(export(**controls)) == rows_of(export())


def test_quoting_survives_a_round_trip(export):
    response = export(b'name,note\nada,"born, 1815"\n')
    assert rows_of(response) == [["name", "note"], ["ada", "born, 1815"]]


def test_unknown_id_is_not_found(client):
    response = client.get("/datasets/deadbeef/export")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_unusable_control_parameter_is_rejected(export):
    assert export(_size="0").status_code == 400
