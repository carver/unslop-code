"""Spec section: Caching and Cache Controls."""

import os
import pathlib
import subprocess
import sys

import pytest
from conftest import SIMPLE_CSV, SOURCE_URL

from datagate_app.config import ConfigurationError, load_settings
from datagate_app.server import create_app

ROOT = pathlib.Path(__file__).resolve().parents[1]

OTHER_CSV = "name,age\nlinus,52\n"


@pytest.fixture
def cache_client(monkeypatch):
    """Build a client whose app read a given raw `CACHE_ENABLED` value at startup."""

    def _cache_client(value=None):
        if value is None:
            monkeypatch.delenv("CACHE_ENABLED", raising=False)
        else:
            monkeypatch.setenv("CACHE_ENABLED", value)
        app = create_app()
        app.config.update(TESTING=True)
        return app.test_client()

    return _cache_client


def convert(client, source=SOURCE_URL, **params):
    return client.get("/convert", query_string={"source": source, **params})


# Phrase: "`/convert` caches results by default." (context: no CACHE_ENABLED in the environment)
def test_convert_caches_by_default(cache_client, serve, remote):
    serve(SIMPLE_CSV)
    client = cache_client()

    convert(client, SOURCE_URL)
    convert(client, SOURCE_URL)

    assert len(remote.calls) == 1


# Phrase: "repeated `/convert` requests for the same source URL can return the cached dataset id"
def test_repeated_convert_returns_the_cached_dataset_id(client, serve):
    source = serve(SIMPLE_CSV)

    first = convert(client, source).get_json()["endpoint"]
    second = convert(client, source).get_json()["endpoint"]

    assert first == second


# Phrase: "... without re-downloading."
def test_cache_hit_does_not_re_download(client, serve, remote):
    source = serve(SIMPLE_CSV)

    convert(client, source)
    convert(client, source)

    assert len(remote.calls) == 1


# Phrase: "... without re-downloading." (context: the stored rows stay the ones first parsed)
def test_cache_hit_keeps_the_originally_parsed_rows(client, serve):
    serve(SIMPLE_CSV)
    serve(OTHER_CSV)

    convert(client, SOURCE_URL)
    endpoint = convert(client, SOURCE_URL).get_json()["endpoint"]

    assert client.get(endpoint).get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Cache responses are identical to fresh parse responses."
def test_cached_response_is_identical_to_the_fresh_one(client, serve):
    source = serve(SIMPLE_CSV)

    fresh = convert(client, source)
    cached = convert(client, source)

    assert (cached.status_code, cached.get_json()) == (fresh.status_code, fresh.get_json())
    assert cached.mimetype == fresh.mimetype


# Phrase: "Cache responses are identical to fresh parse responses." (context: the dataset is still queryable)
def test_endpoint_from_a_cached_response_is_usable(client, serve):
    source = serve(SIMPLE_CSV)
    convert(client, source)

    endpoint = convert(client, source).get_json()["endpoint"]

    assert client.get(endpoint).status_code == 200


# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values: - true: `1`, `true`, `yes`, `on`"
@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "Yes", "ON"])
def test_true_values_enable_caching(cache_client, serve, remote, value):
    serve(SIMPLE_CSV)
    client = cache_client(value)

    convert(client, SOURCE_URL)
    convert(client, SOURCE_URL)

    assert len(remote.calls) == 1


# Phrase: "- false: `0`, `false`, `no`, `off`"
@pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE", "No", "Off"])
def test_false_values_disable_caching(cache_client, serve, remote, value):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    client = cache_client(value)

    convert(client, SOURCE_URL)
    convert(client, SOURCE_URL)

    assert len(remote.calls) == 2


# Phrase: "Invalid values fail startup."
@pytest.mark.parametrize("value", ["maybe", "2", "", "tru", "enabled", "y", "t", "-1", "true false"])
def test_invalid_values_fail_startup(cache_client, value):
    with pytest.raises(ConfigurationError):
        cache_client(value)


# Phrase: "Boolean values are strict: ... (case-insensitive, trimmed)" (context: T50, resolved)
def test_padded_value_is_trimmed(cache_client, serve, remote):
    serve(SIMPLE_CSV)
    client = cache_client(" true ")

    convert(client, SOURCE_URL)
    convert(client, SOURCE_URL)

    assert len(remote.calls) == 1


# Phrase: "Invalid values fail startup." (context: T51 -- the server process exits non-zero)
def test_invalid_value_stops_the_start_command():
    result = subprocess.run(
        [sys.executable, str(ROOT / "datagate.py"), "start", "--port", "8123"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "CACHE_ENABLED": "maybe"},
        timeout=60,
    )

    assert result.returncode != 0
    assert "CACHE_ENABLED" in result.stderr


# Phrase: "When disabled, every `/convert` request re-downloads/parses ..."
def test_disabled_caching_re_downloads_every_request(cache_client, serve, remote):
    for _ in range(3):
        serve(SIMPLE_CSV)
    client = cache_client("off")

    for _ in range(3):
        convert(client, SOURCE_URL)

    assert len(remote.calls) == 3


# Phrase: "... and replaces stored data."
def test_disabled_caching_replaces_stored_data(cache_client, serve):
    serve(SIMPLE_CSV)
    serve(OTHER_CSV)
    client = cache_client("no")

    convert(client, SOURCE_URL)
    endpoint = convert(client, SOURCE_URL).get_json()["endpoint"]

    assert client.get(endpoint).get_json()["rows"] == [["linus", 52]]


# Phrase: "`force` is a presence flag. If present once, it forces re-ingestion ..."
def test_force_forces_re_ingestion(client, serve, remote):
    source = serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)

    convert(client, source)
    response = client.get("/convert", query_string=f"source={source}&force")

    assert response.status_code == 200
    assert len(remote.calls) == 2


# Phrase: "... and replaces the cached dataset."
def test_force_replaces_the_cached_dataset(client, serve):
    source = serve(SIMPLE_CSV)
    serve(OTHER_CSV)
    convert(client, source)

    endpoint = client.get("/convert", query_string=f"source={source}&force").get_json()["endpoint"]

    assert client.get(endpoint).get_json()["rows"] == [["linus", 52]]


# Phrase: "If present once, it forces re-ingestion" (context: the dataset id does not change)
def test_forced_re_ingestion_keeps_the_same_endpoint(client, serve):
    source = serve(SIMPLE_CSV)
    serve(OTHER_CSV)

    first = convert(client, source).get_json()["endpoint"]
    second = client.get("/convert", query_string=f"source={source}&force").get_json()["endpoint"]

    assert first == second


# Phrase: "`force` is a presence flag" (context: it is optional -- an absent flag caches as usual)
def test_absent_force_leaves_caching_alone(client, serve, remote):
    source = serve(SIMPLE_CSV)

    convert(client, source)
    convert(client, source)

    assert len(remote.calls) == 1


# Phrase: "Any `force` value is `HTTP 400`."
@pytest.mark.parametrize("value", ["1", "0", "true", "false", "yes", "on", "force", "please"])
def test_any_force_value_is_400(client, serve, value):
    source = serve(SIMPLE_CSV)

    response = client.get("/convert", query_string={"source": source, "force": value})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Any `force` value is `HTTP 400`." (context: T52 -- `force=` carries no value)
def test_empty_force_value_is_accepted_as_presence(client, serve, remote):
    source = serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, source)

    response = client.get("/convert", query_string=f"source={source}&force=")

    assert response.status_code == 200
    assert len(remote.calls) == 2


# Phrase: "If present once ..." (context: T53 -- a repeated flag is not "once")
def test_repeated_force_is_400(client, serve):
    source = serve(SIMPLE_CSV)

    response = client.get("/convert", query_string=f"source={source}&force&force")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Any `force` value is `HTTP 400`." (context: a rejected request ingests nothing)
def test_rejected_force_does_not_ingest(client, serve, remote):
    source = serve(SIMPLE_CSV)

    client.get("/convert", query_string={"source": source, "force": "1"})

    assert len(remote.calls) == 0


# Phrase: "If caching is disabled, `force` has no additional effect."
def test_force_changes_nothing_when_caching_is_disabled(cache_client, serve, remote):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    client = cache_client("0")

    plain = convert(client, SOURCE_URL)
    forced = client.get("/convert", query_string=f"source={SOURCE_URL}&force")

    assert (forced.status_code, forced.get_json()) == (plain.status_code, plain.get_json())
    assert len(remote.calls) == 2


# Phrase: "If caching is disabled, `force` has no additional effect." (context: T54 -- a value is still 400)
def test_force_value_is_400_even_when_caching_is_disabled(cache_client, serve):
    serve(SIMPLE_CSV)
    client = cache_client("off")

    assert convert(client, SOURCE_URL, force="1").status_code == 400


# Phrase: "Re-ingestion failures keep existing error codes and envelope." (context: remote HTTP error -> 404)
def test_forced_re_ingestion_remote_error_keeps_404(client, serve):
    source = serve(SIMPLE_CSV)
    convert(client, source)
    serve("nope", status=500)

    response = client.get("/convert", query_string=f"source={source}&force")

    body = response.get_json()
    assert response.status_code == 404
    assert set(body) == {"ok", "error"}
    assert body["ok"] is False and isinstance(body["error"], str)


# Phrase: "Re-ingestion failures keep existing error codes and envelope." (context: non-tabular -> 400)
def test_forced_re_ingestion_non_tabular_keeps_400(client, serve):
    source = serve(SIMPLE_CSV)
    convert(client, source)
    serve("<html><body>nope</body></html>", content_type="text/html")

    response = client.get("/convert", query_string=f"source={source}&force")

    assert response.status_code == 400
    assert set(response.get_json()) == {"ok", "error"}
    assert response.get_json()["ok"] is False


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
def test_forced_failure_keeps_prior_dataset_queryable(client, serve):
    source = serve(SIMPLE_CSV)
    endpoint = convert(client, source).get_json()["endpoint"]
    serve("nope", status=500)

    client.get("/convert", query_string=f"source={source}&force")

    body = client.get(endpoint).get_json()
    assert body["rows"] == [["ada", 36], ["grace", 45]]
    assert body["columns"] == ["name", "age"]


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable." (context: parse failures too)
def test_forced_parse_failure_keeps_prior_dataset_queryable(client, serve):
    source = serve(SIMPLE_CSV)
    endpoint = convert(client, source).get_json()["endpoint"]
    serve('{"not": "tabular"}', content_type="application/json")

    client.get("/convert", query_string=f"source={source}&force")

    assert client.get(endpoint).get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "every `/convert` request re-downloads/parses" (context: T58 -- an unforced failure also keeps prior data)
def test_failed_re_ingestion_without_caching_keeps_prior_dataset(cache_client, serve):
    serve(SIMPLE_CSV)
    client = cache_client("off")
    endpoint = convert(client, SOURCE_URL).get_json()["endpoint"]
    serve("nope", status=404)

    assert convert(client, SOURCE_URL).status_code == 404
    assert client.get(endpoint).get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Per-request bypass" (context: T57 -- `force` belongs to `/convert`, uploads always re-ingest)
def test_force_is_ignored_by_upload(upload):
    response = upload(SIMPLE_CSV.encode(), query={"force": "1"})

    assert response.status_code == 200


# Phrase: "`CACHE_ENABLED` | boolean | `true`" (unit: the setting parser, T49)
def test_cache_enabled_parses_the_environment():
    assert load_settings({}).cache_enabled is True
    assert load_settings({"CACHE_ENABLED": "On"}).cache_enabled is True
    assert load_settings({"CACHE_ENABLED": "NO"}).cache_enabled is False
    with pytest.raises(ConfigurationError):
        load_settings({"CACHE_ENABLED": "maybe"})
