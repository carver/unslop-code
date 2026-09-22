"""Caching of ``GET /convert``, its environment switch and its bypass flag."""

import pytest

from gateway.app import create_app
from gateway.caching import CACHE_SETTING, ConfigurationError

FIRST = b"name,age\nada,36\n"
SECOND = b"name,age\ngrace,45\n"


@pytest.fixture
def gateway(files, base_url, monkeypatch):
    """Publish payloads at ``/data.csv`` and convert them under a caching policy."""

    class Gateway:
        def __init__(self, setting: str | None) -> None:
            monkeypatch.delenv(CACHE_SETTING, raising=False)
            if setting is not None:
                monkeypatch.setenv(CACHE_SETTING, setting)
            self.client = create_app().test_client()

        def convert(self, payload: bytes | None = None, query: str = ""):
            """Serve ``payload`` from now on and convert it, ``query`` appended."""
            if payload is not None:
                files["/data.csv"] = payload
            source = f"source={base_url}/data.csv"
            return self.client.get(f"/convert?{source}{query}")

        def rows(self, response) -> list:
            endpoint = response.get_json()["endpoint"]
            return self.client.get(endpoint).get_json()["rows"]

    return Gateway


def test_repeated_source_is_answered_from_the_cache(gateway, downloads):
    service = gateway(None)
    first = service.convert(FIRST)
    second = service.convert(SECOND)

    assert second.get_json() == first.get_json()
    assert downloads == ["/data.csv"]
    assert service.rows(second) == [["ada", 36]]


def test_force_replaces_the_cached_dataset(gateway, downloads):
    service = gateway(None)
    service.convert(FIRST)
    refreshed = service.convert(SECOND, query="&force")

    assert refreshed.get_json()["ok"] is True
    assert downloads == ["/data.csv", "/data.csv"]
    assert service.rows(refreshed) == [["grace", 45]]


@pytest.mark.parametrize("query", ["&force=1", "&force=true", "&force=yes", "&force="])
def test_force_with_a_value_is_rejected(gateway, query):
    response = gateway(None).convert(FIRST, query=query)
    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "Query parameter 'force' takes no value",
    }


def test_force_may_be_given_only_once(gateway):
    response = gateway(None).convert(FIRST, query="&force&force")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("setting", ["0", "false", "FALSE", "no", "off", "Off"])
def test_disabled_cache_re_ingests_every_request(gateway, downloads, setting):
    service = gateway(setting)
    service.convert(FIRST)
    second = service.convert(SECOND)

    assert downloads == ["/data.csv", "/data.csv"]
    assert service.rows(second) == [["grace", 45]]


@pytest.mark.parametrize("setting", ["1", "true", "TRUE", "yes", "on", "On"])
def test_enabled_cache_serves_the_stored_dataset(gateway, downloads, setting):
    service = gateway(setting)
    service.convert(FIRST)
    service.convert(SECOND)
    assert downloads == ["/data.csv"]


def test_force_still_works_when_caching_is_disabled(gateway, downloads):
    service = gateway("off")
    service.convert(FIRST)
    refreshed = service.convert(SECOND, query="&force")

    assert downloads == ["/data.csv", "/data.csv"]
    assert service.rows(refreshed) == [["grace", 45]]


@pytest.mark.parametrize("setting", ["", "maybe", "2", " true", "true ", "TRUE!"])
def test_unreadable_setting_fails_startup(monkeypatch, setting):
    monkeypatch.setenv(CACHE_SETTING, setting)
    with pytest.raises(ConfigurationError):
        create_app()


def test_failed_re_ingestion_keeps_the_stored_dataset(gateway, files):
    service = gateway(None)
    endpoint = service.convert(FIRST).get_json()["endpoint"]

    files.pop("/data.csv")
    failed = service.convert(query="&force")
    assert failed.status_code == 404
    assert failed.get_json()["ok"] is False

    assert service.client.get(endpoint).get_json()["rows"] == [["ada", 36]]


def test_failed_re_ingestion_keeps_the_parse_error(gateway):
    service = gateway(None)
    service.convert(FIRST)
    failed = service.convert(b"<html></html>", query="&force")

    assert failed.status_code == 400
    assert failed.get_json() == {"ok": False, "error": "Source content is not tabular"}
