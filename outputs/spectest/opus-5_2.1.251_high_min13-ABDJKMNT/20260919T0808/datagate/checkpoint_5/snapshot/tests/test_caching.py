"""Spec section: Caching and Cache Controls."""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from datagate_core.caching import ConfigurationError
from datagate_core.server import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent

FIRST_CSV = "name,age\nada,36\n"
SECOND_CSV = "city,country\nlyon,france\n"

TRUE_VALUES = ["1", "true", "yes", "on"]
FALSE_VALUES = ["0", "false", "no", "off"]


def convert(client, url, query=""):
    return client.get(f"/convert?source={url}{query}")


def columns_of(client, response):
    """The columns currently stored behind a `/convert` response's endpoint."""
    payload = client.get(response.get_json()["endpoint"]).get_json()
    return payload["columns"]


# Phrase: "`/convert` caches results by default." - no `CACHE_ENABLED` in the
# environment still caches.
def test_convert_caches_by_default(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-default.csv", FIRST_CSV)

    convert(client, url)
    downloads = origin.hits("/cache-default.csv")
    assert convert(client, url).status_code == 200
    assert origin.hits("/cache-default.csv") == downloads


# Phrase: "repeated `/convert` requests for the same source URL can return the
# cached dataset id without re-downloading."
def test_repeated_convert_returns_the_cached_id_without_downloading(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-repeat.csv", FIRST_CSV)

    first = convert(client, url)
    origin.serve("/cache-repeat.csv", SECOND_CSV)
    downloads = origin.hits("/cache-repeat.csv")
    second = convert(client, url)

    assert second.get_json()["endpoint"] == first.get_json()["endpoint"]
    assert origin.hits("/cache-repeat.csv") == downloads
    # The replaced body was never fetched, so the stored table is the first one.
    assert columns_of(client, second) == ["name", "age"]


# Phrase: "Cache responses are identical to fresh parse responses."
def test_cache_response_is_identical_to_the_fresh_response(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-identical.csv", FIRST_CSV)

    fresh = convert(client, url)
    cached = convert(client, url)

    assert cached.status_code == fresh.status_code == 200
    assert cached.get_json() == fresh.get_json()
    assert cached.headers["Content-Type"] == fresh.headers["Content-Type"]


# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values: true: `1`,
# `true`, `yes`, `on`"
@pytest.mark.parametrize("value", TRUE_VALUES)
def test_true_values_enable_caching(cached_client, origin, value):
    client = cached_client(value)
    path = f"/cache-true-{value}.csv"
    url = origin.serve(path, FIRST_CSV)

    convert(client, url)
    downloads = origin.hits(path)
    convert(client, url)
    assert origin.hits(path) == downloads


# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values: false: `0`,
# `false`, `no`, `off`"
@pytest.mark.parametrize("value", FALSE_VALUES)
def test_false_values_disable_caching(cached_client, origin, value):
    client = cached_client(value)
    path = f"/cache-false-{value}.csv"
    url = origin.serve(path, FIRST_CSV)

    convert(client, url)
    downloads = origin.hits(path)
    convert(client, url)
    assert origin.hits(path) == downloads + 1


# Phrase: "accepts strict case-insensitive values" - spelling case is ignored.
@pytest.mark.parametrize("value", ["TRUE", "True", "YeS", "ON", "Off", "FALSE", "No"])
def test_values_are_case_insensitive(cached_client, value):
    assert cached_client(value) is not None


# Phrase: "Invalid values fail startup." - anything outside the two lists,
# including near misses, whitespace-padded spellings and the empty string (T50).
@pytest.mark.parametrize(
    "value", ["", " ", "maybe", "2", "-1", "enabled", "truthy", "t", "y", " true", "true "]
)
def test_invalid_values_fail_startup(monkeypatch, value):
    monkeypatch.setenv("CACHE_ENABLED", value)
    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Invalid values fail startup." - the server process refuses to run.
def test_invalid_value_stops_the_server_process(tmp_path):
    log = (tmp_path / "startup.log").open("w")
    try:
        completed = subprocess.run(
            [sys.executable, "datagate.py", "start", "--port", "8124"],
            cwd=REPO_ROOT,
            env={"PATH": "/usr/bin:/bin", "CACHE_ENABLED": "sometimes"},
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    finally:
        log.close()
    assert completed.returncode != 0
    assert "CACHE_ENABLED" in (tmp_path / "startup.log").read_text()


# Phrase: "When disabled, every `/convert` request re-downloads/parses and
# replaces stored data."
def test_disabled_cache_redownloads_every_request(cached_client, origin):
    client = cached_client("off")
    url = origin.serve("/cache-disabled.csv", FIRST_CSV)

    convert(client, url)
    downloads = origin.hits("/cache-disabled.csv")
    convert(client, url)
    convert(client, url)
    assert origin.hits("/cache-disabled.csv") == downloads + 2


# Phrase: "every `/convert` request re-downloads/parses and replaces stored data."
def test_disabled_cache_replaces_the_stored_dataset(cached_client, origin):
    client = cached_client("no")
    url = origin.serve("/cache-replace.csv", FIRST_CSV)

    first = convert(client, url)
    origin.serve("/cache-replace.csv", SECOND_CSV)
    second = convert(client, url)

    assert second.get_json()["endpoint"] == first.get_json()["endpoint"]
    assert columns_of(client, second) == ["city", "country"]


# Phrase: "`force` is a presence flag. If present once, it forces re-ingestion
# and replaces the cached dataset."
def test_force_re_ingests_and_replaces_the_cached_dataset(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-force.csv", FIRST_CSV)

    first = convert(client, url)
    origin.serve("/cache-force.csv", SECOND_CSV)
    downloads = origin.hits("/cache-force.csv")
    forced = convert(client, url, query="&force")

    assert forced.status_code == 200
    assert forced.get_json() == first.get_json()
    assert origin.hits("/cache-force.csv") == downloads + 1
    assert columns_of(client, forced) == ["city", "country"]


# Phrase: "`force` is a presence flag" - presence alone decides, so the value
# carried by a single `force` is irrelevant (T51).
@pytest.mark.parametrize("spelling", ["force", "force=", "force=1", "force=0", "force=no"])
def test_force_ignores_its_value(cached_client, origin, spelling):
    client = cached_client()
    path = f"/cache-flag-{spelling.replace('=', '-')}.csv"
    url = origin.serve(path, FIRST_CSV)

    convert(client, url)
    origin.serve(path, SECOND_CSV)
    forced = convert(client, url, query=f"&{spelling}")

    assert forced.status_code == 200
    assert columns_of(client, forced) == ["city", "country"]


# Phrase: "If present once, it forces re-ingestion" - a first-ever request that
# carries `force` simply ingests.
def test_force_on_an_uncached_source_converts_normally(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-force-first.csv", FIRST_CSV)

    response = convert(client, url, query="&force")
    assert response.status_code == 200
    assert columns_of(client, response) == ["name", "age"]


# Phrase: "Any additional `force` value is `HTTP 400`."
def test_repeated_force_is_400(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-force-twice.csv", FIRST_CSV)

    response = convert(client, url, query="&force&force")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "Any additional `force` value is `HTTP 400`." - differing values are
# still two occurrences.
def test_repeated_force_with_values_is_400(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-force-values.csv", FIRST_CSV)
    assert convert(client, url, query="&force=1&force=2").status_code == 400


# Phrase: "Any additional `force` value is `HTTP 400`." - the rule is about the
# request, so it holds with caching disabled too (T53).
def test_repeated_force_is_400_with_caching_disabled(cached_client, origin):
    client = cached_client("false")
    url = origin.serve("/cache-force-off.csv", FIRST_CSV)
    assert convert(client, url, query="&force&force").status_code == 400


# Phrase: "If caching is disabled, `force` has no additional effect."
def test_force_changes_nothing_when_caching_is_disabled(cached_client, origin):
    client = cached_client("0")
    url = origin.serve("/cache-force-noop.csv", FIRST_CSV)

    plain = convert(client, url)
    downloads = origin.hits("/cache-force-noop.csv")
    origin.serve("/cache-force-noop.csv", SECOND_CSV)
    forced = convert(client, url, query="&force")

    assert forced.status_code == plain.status_code == 200
    assert forced.get_json() == plain.get_json()
    assert origin.hits("/cache-force-noop.csv") == downloads + 1
    assert columns_of(client, forced) == ["city", "country"]


# Phrase: "Re-ingestion failures keep existing error codes and envelope." - the
# source is gone on the forced second pass.
def test_forced_re_ingestion_of_a_failing_source_keeps_its_status(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-gone.csv", FIRST_CSV)
    convert(client, url)

    origin.serve("/cache-gone.csv", "nope", status=500, content_type="text/html")
    failed = convert(client, url, query="&force")

    assert failed.status_code == 404
    assert failed.get_json()["ok"] is False


# Phrase: "Re-ingestion failures keep existing error codes and envelope." - the
# body is no longer tabular, and the charset error is unchanged as well.
def test_forced_re_ingestion_keeps_parse_and_charset_errors(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-prose.csv", FIRST_CSV)
    convert(client, url)

    origin.serve("/cache-prose.csv", "<html><body>hello</body></html>", content_type="text/html")
    non_tabular = convert(client, url, query="&force")
    assert non_tabular.status_code == 400
    assert non_tabular.get_json()["ok"] is False

    charset = convert(client, url, query="&force&charset=utf-99")
    assert charset.status_code == 400
    assert charset.get_json()["ok"] is False


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
def test_failed_forced_re_ingestion_leaves_the_dataset_queryable(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-survivor.csv", FIRST_CSV)
    endpoint = convert(client, url).get_json()["endpoint"]

    origin.serve("/cache-survivor.csv", "", content_type="text/csv")
    assert convert(client, url, query="&force").status_code == 400

    payload = client.get(endpoint).get_json()
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36]]


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable." - an
# unreachable source on re-ingestion leaves the stored rows in place too.
def test_unreachable_forced_re_ingestion_keeps_the_dataset(cached_client, origin):
    client = cached_client()
    url = origin.serve("/cache-unreachable.csv", FIRST_CSV)
    endpoint = convert(client, url).get_json()["endpoint"]

    dead = "http://127.0.0.1:9/cache-unreachable.csv"
    assert client.get(f"/convert?source={dead}").status_code == 404
    assert convert(client, url, query="&force").status_code == 200
    assert client.get(endpoint).get_json()["columns"] == ["name", "age"]


# Phrase: "`force` is a presence flag" - the flag belongs to `/convert`, so an
# upload, which re-parses its own bytes anyway, is unaffected (T52).
def test_force_is_not_a_control_on_upload(client):
    response = client.post(
        "/upload?force&force",
        data={"file": (io.BytesIO(FIRST_CSV.encode()), "data.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200


# Phrase: "caches results by default" - caching keys on the source URL, so a
# different source is still fetched and parsed on its own.
def test_cache_is_keyed_by_source_url(cached_client, origin):
    client = cached_client()
    one = origin.serve("/cache-key-one.csv", FIRST_CSV)
    two = origin.serve("/cache-key-two.csv", SECOND_CSV)

    first = convert(client, one)
    second = convert(client, two)

    assert first.get_json()["endpoint"] != second.get_json()["endpoint"]
    assert columns_of(client, second) == ["city", "country"]
