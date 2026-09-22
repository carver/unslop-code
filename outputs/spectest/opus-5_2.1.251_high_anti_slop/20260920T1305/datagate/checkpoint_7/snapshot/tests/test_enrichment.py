"""Tests for the optional ingestion metadata /convert computes with enrich=yes."""

import pytest

from datagate.app import create_app
from tests.workbooks import xls, xlsx

CSV = b"name,age,score,note\nada,36,1.5,\nalan,41,2,x\ngrace,,3.25,x\n"
SHEET = [["name", "age"], ["ada", 36], ["alan", 41]]


@pytest.fixture
def convert(client, serve):
    """Return a factory converting a published CSV and returning the query response."""

    def run(payload: bytes = CSV, **params: str):
        source = serve("a.csv", payload)
        endpoint = client.get(
            "/convert", query_string={"source": source, **params}
        ).json["endpoint"]
        return client.get(endpoint).json

    return run


def test_enrichment_answers_with_the_usual_envelope(client, serve):
    source = serve("a.csv", CSV)
    plain = client.get("/convert", query_string={"source": source})

    response = client.get("/convert", query_string={"source": source, "enrich": "yes"})

    assert response.status_code == 200
    assert response.json == plain.json


def test_enriched_csv_reports_its_summary(convert):
    assert convert(enrich="yes")["dataset_summary"] == {
        "filetype": "csv",
        "row_count": 3,
        "column_count": 4,
    }


def test_enriched_csv_reports_every_column(convert):
    assert convert(enrich="yes")["column_details"] == {
        "name": {"type": "text", "distinct_count": 3, "missing_count": 0},
        "age": {"type": "integer", "distinct_count": 2, "missing_count": 1},
        "score": {"type": "number", "distinct_count": 3, "missing_count": 0},
        "note": {"type": "text", "distinct_count": 1, "missing_count": 1},
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"value,other\nada,1\nalan,2\n", "text"),
        (b"value,other\n36,1\n41,2\n", "integer"),
        (b"value,other\n1.5,1\n2.25,2\n", "float"),
        (b"value,other\n1.5,1\n2,2\n", "number"),
        (b"value,other\n36,1\nn/a,2\n", "text"),
        (b"value,other\n,1\n,2\n", "text"),
    ],
)
def test_column_types_are_labelled_by_their_cells(convert, payload, expected):
    details = convert(payload, enrich="yes")["column_details"]

    assert details["value"]["type"] == expected


def test_enriched_spreadsheet_is_summarised_only(client, serve):
    source = serve("a.xlsx", xlsx(SHEET))
    endpoint = client.get(
        "/convert", query_string={"source": source, "enrich": "yes"}
    ).json["endpoint"]

    body = client.get(endpoint).json

    assert body["dataset_summary"] == {
        "filetype": "excel",
        "row_count": 2,
        "column_count": 2,
    }
    assert "column_details" not in body


def test_an_enriched_xls_workbook_is_summarised_too(client, serve):
    source = serve("a.xls", xls(SHEET))
    endpoint = client.get(
        "/convert", query_string={"source": source, "enrich": "yes"}
    ).json["endpoint"]

    assert client.get(endpoint).json["dataset_summary"]["filetype"] == "excel"


def test_enrichment_leaves_the_rest_of_the_response_alone(convert):
    plain = convert()
    enriched = convert(enrich="yes", force="")

    assert enriched["rows"] == plain["rows"]
    assert enriched["columns"] == plain["columns"]
    assert enriched["total"] == plain["total"]
    assert enriched["ok"] is True
    assert isinstance(enriched["query_ms"], float)


def test_a_plain_conversion_reports_no_metadata(convert):
    body = convert()

    assert "dataset_summary" not in body
    assert "column_details" not in body


@pytest.mark.parametrize("value", ["no", "YES", "Yes", "1", "true", "", "yes "])
def test_only_an_exact_yes_enriches(convert, value):
    body = convert(enrich=value)

    assert "dataset_summary" not in body


def test_a_repeated_enrich_does_not_enrich(client, serve):
    source = serve("a.csv", CSV)
    endpoint = client.get(f"/convert?source={source}&enrich=yes&enrich=yes").json[
        "endpoint"
    ]

    assert "dataset_summary" not in client.get(endpoint).json


def test_enrich_is_ignored_when_querying_a_dataset(convert, client, serve):
    source = serve("a.csv", CSV)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]

    body = client.get(endpoint, query_string={"enrich": "yes"}).json

    assert body["ok"] is True
    assert "dataset_summary" not in body


def test_an_upload_is_never_enriched(upload, client):
    endpoint = upload(CSV, field="file").json["endpoint"]

    assert "dataset_summary" not in client.get(endpoint).json
