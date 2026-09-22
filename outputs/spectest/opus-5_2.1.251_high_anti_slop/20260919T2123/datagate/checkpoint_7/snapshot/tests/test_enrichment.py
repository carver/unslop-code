"""Tests for the optional `/convert` enrichment asked for with `enrich=yes`."""

import pytest

from helpers import convert, endpoint_of, load, upload

METADATA_FIELDS = ("dataset_summary", "column_details")
# The fields enrichment has nothing to say about; `query_ms` is a timing and differs run to run.
SHARED_FIELDS = ("ok", "columns", "rows", "total")

FIRST = b"name,age\nAda,36\n"
SECOND = b"city,population\nOslo,709000\nBergen,286000\n"
NOT_TABULAR = b"<html><body><p>Not a table at all.</p></body></html>\n"


def enriched(client, base_url, fixture, **params):
    """Convert a fixture with enrichment on and return the payload of its dataset endpoint."""
    return load(client, base_url, fixture, enrich="yes", **params)


def test_an_enriched_conversion_answers_with_the_usual_envelope(client, base_url):
    response = convert(client, base_url, "staff.csv", enrich="yes")
    endpoint = endpoint_of(client, base_url, "staff.csv")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "endpoint": endpoint}


def test_an_enriched_csv_dataset_is_summarised(client, base_url):
    assert enriched(client, base_url, "staff.csv")["dataset_summary"] == {
        "filetype": "csv",
        "row_count": 4,
        "column_count": 4,
    }


def test_column_details_are_keyed_by_column_name(client, base_url):
    details = enriched(client, base_url, "types.csv")["column_details"]
    assert list(details) == ["label", "whole", "decimal", "mixed", "sparse"]


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("label", {"type": "text", "distinct_count": 2, "missing_count": 0}),
        ("whole", {"type": "integer", "distinct_count": 3, "missing_count": 0}),
        ("decimal", {"type": "float", "distinct_count": 3, "missing_count": 0}),
        ("mixed", {"type": "number", "distinct_count": 3, "missing_count": 0}),
        ("sparse", {"type": "integer", "distinct_count": 1, "missing_count": 2}),
    ],
)
def test_a_column_reports_its_type_distinct_values_and_blanks(client, base_url, column, expected):
    assert enriched(client, base_url, "types.csv")["column_details"][column] == expected


def test_a_column_mixing_numbers_with_text_is_text(client, base_url):
    details = enriched(client, base_url, "staff.csv")["column_details"]
    assert details["rating"]["type"] == "text"
    assert details["age"]["type"] == "integer"


@pytest.mark.parametrize("fixture", ["staff.xls", "staff.xlsx"])
def test_an_enriched_workbook_is_summarised_as_excel(client, base_url, fixture):
    assert enriched(client, base_url, fixture)["dataset_summary"] == {
        "filetype": "excel",
        "row_count": 4,
        "column_count": 4,
    }


@pytest.mark.parametrize("fixture", ["staff.xls", "staff.xlsx"])
def test_an_enriched_workbook_reports_no_column_details(client, base_url, fixture):
    assert "column_details" not in enriched(client, base_url, fixture)


@pytest.mark.parametrize("fixture", ["staff.csv", "staff.xlsx"])
def test_a_plain_conversion_reports_no_metadata_at_all(client, base_url, fixture):
    payload = load(client, base_url, fixture)
    assert not any(field in payload for field in METADATA_FIELDS)


@pytest.mark.parametrize("value", ["no", "YES", "Yes", "yes ", "1", "true", "on", ""])
def test_only_the_exact_value_yes_enriches(client, base_url, changing_source, value):
    fixture = changing_source(FIRST)
    payload = load(client, base_url, fixture, enrich=value)
    assert not any(field in payload for field in METADATA_FIELDS)


def test_a_repeated_enrich_parameter_leaves_enrichment_off(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    response = convert(client, base_url, fixture, enrich=["yes", "yes"])
    assert response.status_code == 200
    assert not any(field in load(client, base_url, fixture) for field in METADATA_FIELDS)


def test_enrichment_leaves_the_rest_of_the_response_alone(client, base_url):
    plain = load(client, base_url, "staff.csv")
    payload = enriched(client, base_url, "staff.csv")
    rest = {key: value for key, value in payload.items() if key not in METADATA_FIELDS}

    assert rest.keys() == plain.keys()
    assert [rest[key] for key in SHARED_FIELDS] == [plain[key] for key in SHARED_FIELDS]


def test_enriched_rows_still_filter_sort_and_paginate(client, base_url):
    endpoint = endpoint_of(client, base_url, "staff.csv", enrich="yes")
    payload = client.get(
        endpoint, query_string={"role__exact": "engineer", "_sort_desc": "age", "_size": 1}
    ).get_json()
    assert payload["rows"] == [["Grace", "engineer", 45, 8.25]]
    assert payload["total"] == 2
    assert payload["dataset_summary"]["row_count"] == 4


def test_enrichment_upgrades_a_cached_plain_dataset(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture)

    changing_source(SECOND)
    assert endpoint_of(client, base_url, fixture, enrich="yes") == endpoint
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["city", "population"]
    assert payload["dataset_summary"] == {"filetype": "csv", "row_count": 2, "column_count": 2}


def test_an_upgraded_dataset_stays_enriched_for_later_reads(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    convert(client, base_url, fixture)
    endpoint = endpoint_of(client, base_url, fixture, enrich="yes")

    assert "dataset_summary" in client.get(endpoint).get_json()


def test_a_cached_enriched_dataset_answers_a_repeat_request_unchanged(
    client, base_url, changing_source
):
    fixture = changing_source(FIRST)
    first = convert(client, base_url, fixture, enrich="yes")

    changing_source(SECOND)
    repeat = convert(client, base_url, fixture, enrich="yes")
    assert repeat.get_json() == first.get_json()
    assert load(client, base_url, fixture, enrich="yes")["dataset_summary"]["row_count"] == 1


def test_a_plain_request_does_not_strip_a_cached_dataset_of_its_metadata(
    client, base_url, changing_source
):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture, enrich="yes")

    convert(client, base_url, fixture)
    assert "dataset_summary" in client.get(endpoint).get_json()


def test_a_forced_plain_reingestion_drops_the_metadata(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture, enrich="yes")

    convert(client, base_url, fixture, force="")
    assert "dataset_summary" not in client.get(endpoint).get_json()


def test_a_forced_reingestion_describes_the_current_source(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture, enrich="yes")

    changing_source(SECOND)
    convert(client, base_url, fixture, enrich="yes", force="")
    assert client.get(endpoint).get_json()["dataset_summary"] == {
        "filetype": "csv",
        "row_count": 2,
        "column_count": 2,
    }


def test_a_disabled_cache_still_enriches_every_conversion(uncached_client, base_url):
    assert enriched(uncached_client, base_url, "staff.csv")["dataset_summary"]["row_count"] == 4


def test_an_enriched_dataset_survives_a_restart(make_client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(make_client(), base_url, fixture, enrich="yes")

    assert "dataset_summary" in make_client().get(endpoint).get_json()


def test_an_upload_is_never_enriched(client):
    endpoint = upload(client, b"name,age\nAda,36\n").get_json()["endpoint"]
    assert not any(field in client.get(endpoint).get_json() for field in METADATA_FIELDS)


def test_enrich_on_the_dataset_endpoint_is_ignored(client, base_url):
    endpoint = endpoint_of(client, base_url, "staff.csv")
    response = client.get(endpoint, query_string={"enrich": "yes"})
    assert response.status_code == 200
    assert not any(field in response.get_json() for field in METADATA_FIELDS)


def test_an_unreadable_source_reports_the_usual_error(client, base_url, changing_source):
    fixture = changing_source(NOT_TABULAR)
    response = convert(client, base_url, fixture, enrich="yes")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_a_failed_enriched_reingestion_keeps_the_stored_metadata(
    client, base_url, changing_source
):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture, enrich="yes")

    changing_source(NOT_TABULAR)
    assert convert(client, base_url, fixture, enrich="yes", force="").status_code == 400
    payload = client.get(endpoint).get_json()
    assert payload["rows"] == [["Ada", 36]]
    assert payload["dataset_summary"]["row_count"] == 1
