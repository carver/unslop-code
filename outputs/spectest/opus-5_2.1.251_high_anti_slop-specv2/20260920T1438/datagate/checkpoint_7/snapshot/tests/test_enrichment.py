"""Optional ingestion enrichment: its trigger, its output and its storage."""

import pytest

from gateway.app import create_app
from gateway.config import load_settings
from tests.workbooks import xls_bytes, xlsx_bytes

PEOPLE = b"name,age\nada,36\ngrace,45\n"
REPLACEMENT = b"name,age,city\nada,36,london\n"
SHEET = [["name", "age"], ["ada", 36]]

#: Everything that is not the one trigger, written as a raw query string.
OFF = [
    "enrich=no",
    "enrich=YES",
    "enrich=1",
    "enrich=",
    "enrich",
    "enrich=yes&enrich=yes",
]


@pytest.fixture
def source(files, base_url):
    """Publish ``payload`` at ``/data.csv`` and return the URL serving it."""

    def run(payload: bytes) -> str:
        files["/data.csv"] = payload
        return f"{base_url}/data.csv"

    return run


@pytest.fixture
def ingest(client, source):
    """Convert ``payload`` with ``query`` appended raw, and read the dataset back."""

    def run(payload: bytes, query: str = ""):
        converted = client.get(f"/convert?source={source(payload)}{query}")
        assert converted.status_code == 200
        return client.get(converted.get_json()["endpoint"]).get_json()

    return run


def test_enriched_response_body_is_unchanged(client, source):
    response = client.get(f"/convert?source={source(PEOPLE)}&enrich=yes")
    body = response.get_json()

    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert set(body) == {"ok", "endpoint"}


def test_enrichment_summarises_a_csv_dataset(ingest):
    summary = ingest(PEOPLE, "&enrich=yes")["dataset_summary"]

    assert summary["filetype"] == "csv"
    assert summary["row_count"] == 2
    assert summary["column_count"] == 2


def test_enrichment_details_every_column(ingest):
    details = ingest(PEOPLE, "&enrich=yes")["column_details"]

    assert set(details) == {"name", "age"}
    assert details["name"] == {"type": "text", "distinct_count": 2, "missing_count": 0}
    assert details["age"] == {
        "type": "integer",
        "distinct_count": 2,
        "missing_count": 0,
    }


@pytest.mark.parametrize(
    "column, expected",
    [
        (b"08:30\n09:15", "text"),
        (b"1\n2", "integer"),
        (b"1.5\n2.25", "float"),
        (b"1\n2.5", "number"),
    ],
)
def test_column_types_are_read_from_the_values(ingest, column, expected):
    details = ingest(b"value\n" + column, "&enrich=yes")["column_details"]
    assert details["value"]["type"] == expected


def test_blank_cells_are_missing_rather_than_values(ingest):
    body = ingest(b"name,age\nada,36\ngrace,\nada,\n", "&enrich=yes")
    details = body["column_details"]

    assert details["age"]["missing_count"] == 2
    assert details["age"]["distinct_count"] == 1
    assert details["age"]["type"] == "integer"
    assert details["name"]["distinct_count"] == 2


def test_a_column_a_ragged_row_never_reaches_is_missing_there(ingest):
    details = ingest(b"name,age\nada,36\ngrace\n", "&enrich=yes")["column_details"]
    assert details["age"]["missing_count"] == 1


def test_an_empty_column_is_text(ingest):
    details = ingest(b"name,age\nada,\n", "&enrich=yes")["column_details"]
    assert details["age"] == {"type": "text", "distinct_count": 0, "missing_count": 1}


@pytest.mark.parametrize("workbook", [xlsx_bytes, xls_bytes])
def test_enriched_workbooks_are_summarised_without_column_details(ingest, workbook):
    body = ingest(workbook(SHEET), "&enrich=yes")

    assert body["dataset_summary"] == {
        "filetype": "excel",
        "row_count": 1,
        "column_count": 2,
    }
    assert "column_details" not in body


def test_enrichment_is_off_without_the_trigger(ingest):
    body = ingest(PEOPLE)

    assert "dataset_summary" not in body
    assert "column_details" not in body


@pytest.mark.parametrize("query", OFF)
def test_only_a_single_exact_yes_enriches(ingest, query):
    assert "dataset_summary" not in ingest(PEOPLE, f"&{query}")


def test_enrichment_leaves_the_rest_of_the_response_alone(ingest):
    plain = ingest(PEOPLE)
    enriched = ingest(PEOPLE, "&force&enrich=yes")

    assert enriched["rows"] == plain["rows"]
    assert enriched["columns"] == plain["columns"]
    assert enriched["total"] == plain["total"]
    assert enriched["ok"] is True
    assert isinstance(enriched["query_ms"], float)


def test_enrichment_upgrades_a_cached_plain_dataset(ingest, downloads):
    ingest(PEOPLE)
    upgraded = ingest(REPLACEMENT, "&enrich=yes")

    assert downloads == ["/data.csv", "/data.csv"]
    assert upgraded["dataset_summary"]["column_count"] == 3
    assert upgraded["rows"] == [["ada", 36, "london"]]


def test_an_enriched_dataset_may_be_served_from_the_cache(ingest, downloads):
    ingest(PEOPLE, "&enrich=yes")
    cached = ingest(REPLACEMENT, "&enrich=yes")

    assert downloads == ["/data.csv"]
    assert cached["dataset_summary"]["column_count"] == 2


def test_a_cache_hit_keeps_the_stored_enrichment(ingest, downloads):
    ingest(PEOPLE, "&enrich=yes")
    plain_request = ingest(PEOPLE)

    assert downloads == ["/data.csv"]
    assert plain_request["dataset_summary"]["row_count"] == 2


def test_re_ingestion_describes_the_current_source_bytes(ingest):
    ingest(PEOPLE, "&enrich=yes")
    refreshed = ingest(REPLACEMENT, "&force&enrich=yes")

    assert refreshed["dataset_summary"] == {
        "filetype": "csv",
        "row_count": 1,
        "column_count": 3,
    }
    assert set(refreshed["column_details"]) == {"name", "age", "city"}


def test_re_ingestion_without_the_trigger_stores_a_plain_dataset(ingest):
    ingest(PEOPLE, "&enrich=yes")
    assert "dataset_summary" not in ingest(PEOPLE, "&force")


def test_a_failed_enrichment_keeps_the_description(client, source, ingest):
    ingest(PEOPLE, "&enrich=yes")

    failed = client.get(
        f"/convert?source={source(b'<html></html>')}&force&enrich=yes"
    )
    assert failed.status_code == 400
    assert failed.get_json() == {"ok": False, "error": "Source content is not tabular"}

    assert ingest(PEOPLE)["dataset_summary"]["column_count"] == 2


def test_a_failed_upgrade_stores_nothing(client, source, ingest):
    ingest(PEOPLE)

    failed = client.get(f"/convert?source={source(b'<html></html>')}&enrich=yes")
    assert failed.status_code == 400

    source(PEOPLE)
    assert ingest(PEOPLE)["rows"] == [["ada", 36], ["grace", 45]]


def test_a_failed_download_leaves_the_description_alone(
    client, base_url, files, ingest
):
    ingest(PEOPLE, "&enrich=yes")
    files.pop("/data.csv")

    failed = client.get(f"/convert?source={base_url}/data.csv&force&enrich=yes")
    assert failed.status_code == 404
    assert failed.get_json()["ok"] is False

    files["/data.csv"] = PEOPLE
    assert ingest(PEOPLE)["dataset_summary"]["row_count"] == 2


def test_each_request_is_enriched_on_its_own_when_caching_is_off(settings, source):
    environment = {"STORAGE_DIR": str(settings.storage_dir), "CACHE_ENABLED": "off"}
    client = create_app(load_settings(environment)).test_client()

    def convert(payload: bytes, query: str = "") -> dict:
        converted = client.get(f"/convert?source={source(payload)}{query}")
        return client.get(converted.get_json()["endpoint"]).get_json()

    assert convert(PEOPLE, "&enrich=yes")["dataset_summary"]["column_count"] == 2
    assert "dataset_summary" not in convert(REPLACEMENT)


def test_uploads_are_never_enriched(client, upload):
    endpoint = upload(PEOPLE, enrich="yes").get_json()["endpoint"]
    assert "dataset_summary" not in client.get(endpoint).get_json()


def test_reading_a_dataset_cannot_ask_for_enrichment(client, source):
    endpoint = client.get(f"/convert?source={source(PEOPLE)}").get_json()["endpoint"]

    response = client.get(f"{endpoint}?enrich=yes")
    assert response.status_code == 200
    assert "dataset_summary" not in response.get_json()
