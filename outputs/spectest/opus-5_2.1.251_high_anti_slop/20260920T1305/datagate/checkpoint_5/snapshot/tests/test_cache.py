"""Tests for /convert caching, the CACHE_ENABLED setting and the force bypass."""

from pathlib import Path

import pytest

from datagate.app import create_app
from datagate.caching import ConfigError

FIRST = b"name,age\nada,36\n"
SECOND = b"name,age\nalan,41\n"


@pytest.fixture
def make_client(monkeypatch):
    """A client whose app is built after the test has set CACHE_ENABLED."""
    monkeypatch.delenv("CACHE_ENABLED", raising=False)

    def build(setting: str | None = None):
        if setting is not None:
            monkeypatch.setenv("CACHE_ENABLED", setting)
        return create_app().test_client()

    return build


def rows(client, endpoint):
    return client.get(endpoint).json["rows"]


def test_repeated_conversion_is_served_from_the_cache(make_client, serve):
    client = make_client()
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", SECOND)

    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 200
    assert response.json == {"ok": True, "endpoint": endpoint}
    assert rows(client, endpoint) == [["ada", 36]]


def test_force_replaces_the_cached_dataset(make_client, serve):
    client = make_client()
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", SECOND)

    response = client.get("/convert", query_string={"source": source, "force": ""})

    assert response.json == {"ok": True, "endpoint": endpoint}
    assert rows(client, endpoint) == [["alan", 41]]


def test_force_needs_no_value(make_client, serve):
    client = make_client()
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", SECOND)

    client.get(f"/convert?source={source}&force")

    assert rows(client, endpoint) == [["alan", 41]]


def test_repeated_force_is_rejected(make_client, serve):
    client = make_client()
    source = serve("a.csv", FIRST)

    response = client.get(f"/convert?source={source}&force&force")

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_repeated_force_is_rejected_with_caching_disabled(make_client, serve):
    client = make_client("off")
    source = serve("a.csv", FIRST)

    response = client.get(f"/convert?source={source}&force&force")

    assert response.status_code == 400


@pytest.mark.parametrize("setting", ["0", "false", "NO", "Off"])
def test_disabled_caching_re_ingests_every_request(make_client, serve, setting):
    client = make_client(setting)
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", SECOND)

    client.get("/convert", query_string={"source": source})

    assert rows(client, endpoint) == [["alan", 41]]


@pytest.mark.parametrize("setting", ["1", "true", "YES", "On"])
def test_enabled_caching_keeps_the_stored_dataset(make_client, serve, setting):
    client = make_client(setting)
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", SECOND)

    client.get("/convert", query_string={"source": source})

    assert rows(client, endpoint) == [["ada", 36]]


def test_force_is_harmless_when_caching_is_disabled(make_client, serve):
    client = make_client("no")
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", SECOND)

    response = client.get("/convert", query_string={"source": source, "force": "1"})

    assert response.json == {"ok": True, "endpoint": endpoint}
    assert rows(client, endpoint) == [["alan", 41]]


@pytest.mark.parametrize("setting", ["", "maybe", "2", "true ", "y"])
def test_invalid_setting_fails_startup(make_client, setting):
    with pytest.raises(ConfigError):
        make_client(setting)


def test_failed_re_ingestion_keeps_its_error_envelope(make_client, serve):
    client = make_client()
    source = serve("a.csv", FIRST)
    client.get("/convert", query_string={"source": source})
    serve("a.csv", b"<html><body><p>hello</p></body></html>")

    response = client.get("/convert", query_string={"source": source, "force": ""})

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


def test_failed_re_ingestion_leaves_the_stored_dataset_queryable(make_client, serve):
    client = make_client()
    source = serve("a.csv", FIRST)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]
    serve("a.csv", b"<html><body><p>hello</p></body></html>")

    client.get("/convert", query_string={"source": source, "force": ""})

    assert rows(client, endpoint) == [["ada", 36]]


def test_source_gone_missing_on_re_ingestion_is_not_found(make_client, serve, tmp_path):
    client = make_client()
    source = serve("a.csv", FIRST)
    client.get("/convert", query_string={"source": source})
    Path(tmp_path, "a.csv").unlink()

    response = client.get("/convert", query_string={"source": source, "force": ""})

    assert response.status_code == 404
