"""Caching and cache controls: `CACHE_ENABLED` and the `force` flag.

Every test serves its CSV at a path of its own, so the session-wide origin's
hit counter for that path counts only this test's downloads.
"""

from urllib.parse import quote

import pytest

from gateway.app import create_app
from gateway.caching import ConfigError

FIRST = "name,age\nada,36\n"
SECOND = "name,age\ngrace,45\n"
FIRST_ROWS = [["ada", 36]]
SECOND_ROWS = [["grace", 45]]


def convert(client, source, flags="", **params):
    """GET /convert for `source`, appending raw `flags` such as `&force`."""
    query = "".join(f"&{name}={quote(value)}" for name, value in params.items())
    return client.get(f"/convert?source={quote(source)}{query}{flags}")


def rows_of(client, endpoint):
    return client.get(endpoint).get_json()["rows"]


# Spec: "`/convert` caches results by default."
# Context: no CACHE_ENABLED in the environment at all.
def test_caching_is_on_by_default(client, origin):
    source = origin.serve("/cache-default.csv", FIRST)
    convert(client, source)
    convert(client, source)
    assert origin.hits["/cache-default.csv"] == 1


# Spec: "repeated `/convert` requests for the same source URL can return the
# cached dataset id without re-downloading."
# Context: the remote body changes between two conversions; the second is a
# cache hit, so the stored rows stay as they were (AMBIGUITIES T40).
def test_cache_hit_does_not_redownload(client, origin):
    source = origin.serve("/cache-hit.csv", FIRST)
    endpoint = convert(client, source).get_json()["endpoint"]
    origin.serve("/cache-hit.csv", SECOND)
    again = convert(client, source).get_json()
    assert again["endpoint"] == endpoint
    assert origin.hits["/cache-hit.csv"] == 1
    assert rows_of(client, endpoint) == FIRST_ROWS


# Spec: "Cache responses are identical to fresh parse responses."
# Context: the cached answer's status, headers and body against the first one.
def test_cache_response_is_identical_to_the_fresh_one(client, origin):
    source = origin.serve("/cache-identical.csv", FIRST)
    fresh = convert(client, source)
    cached = convert(client, source)
    assert cached.status_code == fresh.status_code == 200
    assert cached.get_json() == fresh.get_json()
    assert cached.headers["Content-Type"] == fresh.headers["Content-Type"]


# Spec: "repeated `/convert` requests for the same source URL"
# Context: a cache entry is keyed on the source URL, so a different URL serving
# the same bytes is still downloaded.
def test_a_different_source_is_not_a_cache_hit(client, origin):
    first = origin.serve("/cache-key-a.csv", FIRST)
    second = origin.serve("/cache-key-b.csv", FIRST)
    convert(client, first)
    convert(client, second)
    assert origin.hits["/cache-key-b.csv"] == 1


# Spec: "repeated `/convert` requests for the same source URL"
# Context: a second request differing only in `charset` is still the same source
# URL, so it hits the cache (AMBIGUITIES T39).
def test_charset_does_not_change_the_cache_key(client, origin):
    source = origin.serve("/cache-charset.csv", FIRST)
    convert(client, source)
    convert(client, source, charset="iso-8859-1")
    assert origin.hits["/cache-charset.csv"] == 1


# Spec: "`CACHE_ENABLED` accepts strict case-insensitive values: true: `1`,
# `true`, `yes`, `on`"
# Context: each accepted true spelling, in mixed case, caches.
def test_true_values_enable_caching(configured_client, origin):
    for index, value in enumerate(["1", "true", "yes", "on", "TRUE", "Yes", "ON"]):
        path = f"/cache-true-{index}.csv"
        source = origin.serve(path, FIRST)
        client = configured_client(value)
        convert(client, source)
        convert(client, source)
        assert origin.hits[path] == 1, value


# Spec: "`CACHE_ENABLED` accepts strict case-insensitive values: false: `0`,
# `false`, `no`, `off`"
# Context: each accepted false spelling, in mixed case, disables caching.
def test_false_values_disable_caching(configured_client, origin):
    for index, value in enumerate(["0", "false", "no", "off", "FALSE", "No", "OFF"]):
        path = f"/cache-false-{index}.csv"
        source = origin.serve(path, FIRST)
        client = configured_client(value)
        convert(client, source)
        convert(client, source)
        assert origin.hits[path] == 2, value


# Spec: "Invalid values fail startup."
# Context: values outside the two accepted sets, including a padded and an empty
# one, stop the app from being built at all (AMBIGUITIES T38, T45).
@pytest.mark.parametrize("value", ["maybe", "2", "", " true ", "trueish", "enabled", "-1"])
def test_invalid_values_fail_startup(monkeypatch, value):
    monkeypatch.setenv("CACHE_ENABLED", value)
    with pytest.raises(ConfigError):
        create_app()


# Spec: "Invalid values fail startup."
# Context: the CLI turns that refusal into a non-zero exit without serving.
def test_invalid_value_stops_the_cli(monkeypatch):
    import datagate

    monkeypatch.setenv("CACHE_ENABLED", "maybe")
    monkeypatch.setattr("flask.Flask.run", lambda *args, **kwargs: pytest.fail("served"))
    with pytest.raises(SystemExit) as exit_info:
        datagate.main(["start"])
    assert exit_info.value.code != 0


# Spec: "When disabled, every `/convert` request re-downloads/parses and
# replaces stored data."
# Context: the remote body changes between two conversions with caching off.
def test_disabled_cache_replaces_stored_data(configured_client, origin):
    client = configured_client("off")
    source = origin.serve("/cache-off.csv", FIRST)
    endpoint = convert(client, source).get_json()["endpoint"]
    origin.serve("/cache-off.csv", SECOND)
    again = convert(client, source).get_json()
    assert again["endpoint"] == endpoint
    assert origin.hits["/cache-off.csv"] == 2
    assert rows_of(client, endpoint) == SECOND_ROWS


# Spec: "`force` is a presence flag. If present once, it forces re-ingestion and
# replaces the cached dataset."
# Context: a bare `?force` on a source that is already cached.
def test_force_replaces_the_cached_dataset(client, origin):
    source = origin.serve("/force-refresh.csv", FIRST)
    endpoint = convert(client, source).get_json()["endpoint"]
    origin.serve("/force-refresh.csv", SECOND)
    forced = convert(client, source, flags="&force")
    assert forced.status_code == 200
    assert forced.get_json()["endpoint"] == endpoint
    assert origin.hits["/force-refresh.csv"] == 2
    assert rows_of(client, endpoint) == SECOND_ROWS


# Spec: "`force` is a presence flag."
# Context: an explicitly empty `force=` cannot be told apart from a bare one by
# any query parser, so it is presence too (AMBIGUITIES T41).
def test_empty_force_value_is_presence(client, origin):
    source = origin.serve("/force-empty.csv", FIRST)
    assert convert(client, source, flags="&force=").status_code == 200
    assert convert(client, source, flags="&force=").status_code == 200
    assert origin.hits["/force-empty.csv"] == 2


# Spec: "If present once, it forces re-ingestion"
# Context: forcing a source that was never converted is an ordinary ingestion.
def test_force_on_an_uncached_source_ingests(client, origin):
    source = origin.serve("/force-first.csv", FIRST)
    response = convert(client, source, flags="&force")
    assert response.status_code == 200
    assert rows_of(client, response.get_json()["endpoint"]) == FIRST_ROWS


# Spec: "Any `force` value is `HTTP 400`."
# Context: the flag carrying a value, truthy or falsy.
@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "0", "false", "please"])
def test_force_with_a_value_is_400(client, origin, value):
    source = origin.serve("/force-valued.csv", FIRST)
    response = convert(client, source, flags=f"&force={value}")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "If present **once**, it forces re-ingestion"
# Context: a repeated flag is not "once" (AMBIGUITIES T42).
def test_repeated_force_is_400(client, origin):
    source = origin.serve("/force-repeated.csv", FIRST)
    assert convert(client, source, flags="&force&force").status_code == 400


# Spec: "Any `force` value is `HTTP 400`."
# Context: a rejected request must not ingest anything, so the source stays
# unknown afterwards.
def test_rejected_force_does_not_ingest(client, origin):
    source = origin.serve("/force-rejected.csv", FIRST)
    assert convert(client, source, flags="&force=1").status_code == 400
    assert origin.hits["/force-rejected.csv"] == 0


# Spec: "If caching is disabled, `force` has no additional effect."
# Context: with caching off, forcing behaves exactly like not forcing.
def test_force_is_redundant_when_caching_is_disabled(configured_client, origin):
    client = configured_client("0")
    source = origin.serve("/force-off.csv", FIRST)
    plain = convert(client, source)
    forced = convert(client, source, flags="&force")
    assert plain.get_json() == forced.get_json()
    assert origin.hits["/force-off.csv"] == 2


# Spec: "Any `force` value is `HTTP 400`." / "If caching is disabled, `force`
# has no additional effect."
# Context: a disabled cache does not make a valued `force` acceptable, since
# only the effect is redundant (AMBIGUITIES T44).
def test_valued_force_is_400_when_caching_is_disabled(configured_client, origin):
    client = configured_client("false")
    source = origin.serve("/force-off-valued.csv", FIRST)
    assert convert(client, source, flags="&force=1").status_code == 400


# Spec: "Re-ingestion failures keep existing error codes and envelope."
# Context: a forced re-ingestion of a source that has since broken, across the
# unreachable, remote-error and bad-charset cases.
def test_reingestion_failures_keep_their_status_and_envelope(client, origin):
    source = origin.serve("/reingest-error.csv", FIRST)
    convert(client, source)
    origin.serve("/reingest-error.csv", FIRST, status=500)
    remote_error = convert(client, source, flags="&force")
    assert remote_error.status_code == 404
    assert remote_error.get_json()["ok"] is False
    assert set(remote_error.get_json()) == {"ok", "error"}

    origin.serve("/reingest-error.csv", "city,note\nmalmö,café\n".encode("iso-8859-1"))
    bad_charset = convert(client, source, flags="&force", charset="utf-8")
    assert bad_charset.status_code == 400
    assert bad_charset.get_json()["ok"] is False

    unreachable = convert(client, "http://127.0.0.1:1/gone.csv", flags="&force")
    assert unreachable.status_code == 404


# Spec: "Re-ingestion failures keep existing error codes and envelope."
# Context: with caching off, the failure of an ordinary repeat request is
# reported the same way.
def test_uncached_reingestion_failure_keeps_its_status(configured_client, origin):
    client = configured_client("no")
    source = origin.serve("/reingest-off.csv", FIRST)
    convert(client, source)
    origin.serve("/reingest-off.csv", FIRST, status=503)
    response = convert(client, source)
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Spec: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: the dataset endpoint still answers with the rows from before the
# failed forced re-ingestion.
def test_failed_forced_reingestion_keeps_the_prior_dataset(client, origin):
    source = origin.serve("/reingest-keep.csv", FIRST)
    endpoint = convert(client, source).get_json()["endpoint"]
    origin.serve("/reingest-keep.csv", b"<html>not a table</html>")
    assert convert(client, source, flags="&force").status_code == 400
    assert rows_of(client, endpoint) == FIRST_ROWS


# Spec: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: the same guarantee when caching is disabled, where the replacement
# is what failed.
def test_failed_reingestion_keeps_the_prior_dataset_when_disabled(configured_client, origin):
    client = configured_client("off")
    source = origin.serve("/reingest-keep-off.csv", FIRST)
    endpoint = convert(client, source).get_json()["endpoint"]
    origin.serve("/reingest-keep-off.csv", FIRST, status=500)
    assert convert(client, source).status_code == 404
    assert rows_of(client, endpoint) == FIRST_ROWS


# Spec: "`/convert` caches results by default." (the section is scoped to
# /convert)
# Context: an upload carries its own bytes, so it is never served from a cache
# and `force` means nothing there (AMBIGUITIES T43).
def test_upload_ignores_force(upload):
    assert upload(FIRST, params={"force": "1"}).status_code == 200
