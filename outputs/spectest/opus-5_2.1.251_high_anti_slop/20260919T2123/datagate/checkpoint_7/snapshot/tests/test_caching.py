"""Tests for the `/convert` cache: the `CACHE_ENABLED` setting and the per-request `force` flag."""

import pytest

from config import load_settings
from helpers import convert, endpoint_of

CACHE_ENABLED_VAR = "CACHE_ENABLED"

FIRST = b"name,age\nAda,36\n"
SECOND = b"city,population\nOslo,709000\n"
NOT_TABULAR = b"<html><body><p>Not a table at all.</p></body></html>\n"


def test_repeat_convert_serves_the_cached_dataset(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture)

    changing_source(SECOND)
    assert endpoint_of(client, base_url, fixture) == endpoint
    assert client.get(endpoint).get_json()["columns"] == ["name", "age"]


def test_cached_response_matches_the_first_one(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    fresh = convert(client, base_url, fixture)
    cached = convert(client, base_url, fixture)

    assert cached.status_code == fresh.status_code
    assert cached.get_json() == fresh.get_json()


def test_force_replaces_the_cached_dataset(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture)

    changing_source(SECOND)
    assert endpoint_of(client, base_url, fixture, force="") == endpoint
    assert client.get(endpoint).get_json()["columns"] == ["city", "population"]


def test_force_needs_no_value(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture)

    changing_source(SECOND)
    client.get("/convert", query_string=f"source={base_url}/{fixture}&force")
    assert client.get(endpoint).get_json()["columns"] == ["city", "population"]


@pytest.mark.parametrize("client_name", ["client", "uncached_client"])
def test_repeated_force_is_rejected(request, base_url, client_name):
    client = request.getfixturevalue(client_name)
    response = convert(client, base_url, "basic.csv", force=["", ""])
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_disabled_cache_reingests_every_request(uncached_client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(uncached_client, base_url, fixture)

    changing_source(SECOND)
    assert endpoint_of(uncached_client, base_url, fixture) == endpoint
    assert uncached_client.get(endpoint).get_json()["columns"] == ["city", "population"]


def test_force_adds_nothing_when_the_cache_is_disabled(uncached_client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(uncached_client, base_url, fixture)

    changing_source(SECOND)
    assert endpoint_of(uncached_client, base_url, fixture, force="") == endpoint
    assert uncached_client.get(endpoint).get_json()["columns"] == ["city", "population"]


def test_failed_forced_reingestion_keeps_the_stored_dataset(client, base_url, changing_source):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture)

    changing_source(NOT_TABULAR)
    response = convert(client, base_url, fixture, force="")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert client.get(endpoint).get_json()["rows"] == [["Ada", 36]]


def test_reingestion_of_a_vanished_source_reports_it_as_missing(
    client, base_url, fixtures_root, changing_source
):
    fixture = changing_source(FIRST)
    endpoint = endpoint_of(client, base_url, fixture)

    (fixtures_root / fixture).unlink()
    assert convert(client, base_url, fixture, force="").status_code == 404
    assert client.get(endpoint).get_json()["rows"] == [["Ada", 36]]


def test_cache_is_enabled_when_the_variable_is_unset():
    assert load_settings({}).cache_enabled is True


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("Yes", True),
        ("on", True),
        (" true ", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("OFF", False),
    ],
)
def test_cache_setting_is_read_case_insensitively(value, enabled):
    assert load_settings({CACHE_ENABLED_VAR: value}).cache_enabled is enabled


@pytest.mark.parametrize("value", ["", "maybe", "2", "y", "n", "enabled"])
def test_invalid_cache_setting_is_rejected(value):
    with pytest.raises(ValueError):
        load_settings({CACHE_ENABLED_VAR: value})
