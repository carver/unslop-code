"""Tests for how enrich=yes and the /convert cache decide when a source is re-ingested."""

import pytest

from datagate.app import create_app

FIRST = b"name,age\nada,36\n"
SECOND = b"name,age\nalan,41\ngrace,45\n"
BROKEN = b"<html><body><p>hello</p></body></html>"


@pytest.fixture
def convert(client, serve):
    """Return a factory publishing bytes at one URL and converting them."""

    def run(payload: bytes, **params: str):
        source = serve("a.csv", payload)
        return client.get("/convert", query_string={"source": source, **params})

    return run


def body(client, response):
    return client.get(response.json["endpoint"]).json


def test_enrichment_upgrades_a_cached_plain_dataset(client, convert):
    convert(FIRST)

    upgraded = body(client, convert(SECOND, enrich="yes"))

    assert "dataset_summary" in upgraded
    assert upgraded["rows"] == [["alan", 41], ["grace", 45]]


def test_a_cached_enriched_dataset_answers_from_the_cache(client, convert):
    convert(FIRST, enrich="yes")

    cached = body(client, convert(SECOND, enrich="yes"))

    assert cached["rows"] == [["ada", 36]]
    assert cached["dataset_summary"]["row_count"] == 1


def test_a_plain_request_keeps_a_cached_dataset_enriched(client, convert):
    convert(FIRST, enrich="yes")

    cached = body(client, convert(SECOND))

    assert cached["dataset_summary"]["row_count"] == 1
    assert cached["rows"] == [["ada", 36]]


def test_a_forced_plain_re_ingestion_stores_no_metadata(client, convert):
    convert(FIRST, enrich="yes")

    replaced = body(client, convert(SECOND, force=""))

    assert "dataset_summary" not in replaced
    assert replaced["rows"] == [["alan", 41], ["grace", 45]]


def test_a_forced_re_ingestion_recomputes_the_metadata(client, convert):
    convert(FIRST, enrich="yes")

    recomputed = body(client, convert(SECOND, enrich="yes", force=""))

    assert recomputed["dataset_summary"]["row_count"] == 2


def test_enrichment_is_recomputed_on_every_request_without_caching(
    monkeypatch, serve, client
):
    monkeypatch.setenv("CACHE_ENABLED", "off")
    uncached = create_app().test_client()
    source = serve("a.csv", FIRST)
    uncached.get("/convert", query_string={"source": source, "enrich": "yes"})
    serve("a.csv", SECOND)

    endpoint = uncached.get(
        "/convert", query_string={"source": source, "enrich": "yes"}
    ).json["endpoint"]

    assert uncached.get(endpoint).json["dataset_summary"]["row_count"] == 2


def test_a_failed_upgrade_reports_a_json_error(client, convert):
    convert(FIRST)

    response = convert(BROKEN, enrich="yes")

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


def test_a_failed_upgrade_leaves_the_stored_dataset_queryable(client, convert):
    stored = convert(FIRST)

    convert(BROKEN, enrich="yes")

    assert body(client, stored)["rows"] == [["ada", 36]]


def test_a_failed_re_ingestion_does_not_strip_stored_metadata(client, convert):
    stored = convert(FIRST, enrich="yes")

    convert(BROKEN, enrich="yes", force="")

    assert body(client, stored)["dataset_summary"]["row_count"] == 1
