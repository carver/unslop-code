"""Spec section: Caching and Cache Controls.

    `/convert` caches results by default.
    ... `CACHE_ENABLED` ... per-request `force` bypass ... error handling.
"""

import json
from urllib.parse import quote

import pytest

import datagate
from conftest import free_port as _free_port, http_get as _http_get

SIMPLE = "name,age\nalice,30\nbob,41\n"
OTHER = "city,pop\nlisbon,545\n"


def _hits(origin, path):
    return origin.hits.get(path, 0)


def _convert_url(source, extra=""):
    """Build a raw /convert query string (duplicate/valueless params allowed)."""
    return "/convert?source={}{}".format(quote(source, safe=""), extra)


@pytest.fixture
def config():
    """Load configuration from an explicit environment; restore afterwards."""
    saved = (datagate.CACHE_ENABLED, datagate.CONFIG_ERROR)

    def _load(**environ):
        return datagate.load_config(environ)

    yield _load
    datagate.CACHE_ENABLED, datagate.CONFIG_ERROR = saved


@pytest.fixture
def caching(config):
    """Force the running app into a known caching mode for one test."""

    def _set(enabled):
        config(CACHE_ENABLED="true" if enabled else "false")
        assert datagate.CACHE_ENABLED is enabled

    return _set


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


# Phrase: "`/convert` caches results by default."
# Context: "by default" == no CACHE_ENABLED in the environment at all.
def test_caching_is_enabled_by_default(config):
    assert config() is None  # no configuration error
    assert datagate.CACHE_ENABLED is True


# Phrase: "`/convert` caches results by default."
def test_repeat_convert_does_not_refetch_by_default(config, client, origin):
    config()
    path = "/cache-default.csv"
    origin.add(path, SIMPLE)
    before = _hits(origin, path)

    client.get("/convert", query_string={"source": origin.url(path)})
    client.get("/convert", query_string={"source": origin.url(path)})

    assert _hits(origin, path) - before == 1


# Phrase: "With caching enabled, repeated `/convert` requests for the same
# source URL can return the cached dataset id without re-downloading."
def test_cache_hit_returns_the_same_dataset_id(caching, client, origin):
    caching(True)
    path = "/cache-id.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)

    first = client.get("/convert", query_string={"source": source})
    second = client.get("/convert", query_string={"source": source})

    assert first.status_code == second.status_code == 200
    assert first.get_json()["endpoint"] == second.get_json()["endpoint"]


# Phrase: "... without re-downloading."
# Context: the origin's content changed in between, so serving the old rows is
# proof that no second download happened.
def test_cache_hit_serves_the_previously_parsed_rows(caching, client, origin):
    caching(True)
    path = "/cache-stale.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    origin.add(path, OTHER)
    before = _hits(origin, path)
    client.get("/convert", query_string={"source": source})

    assert _hits(origin, path) == before
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "... can return the cached dataset id without re-downloading."
# Context: a source that has since started failing is never contacted again.
def test_cache_hit_survives_a_source_that_went_bad(caching, client, origin):
    caching(True)
    path = "/cache-died.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    first = client.get("/convert", query_string={"source": source})
    assert first.status_code == 200

    origin.add(path, "boom", status=500)
    second = client.get("/convert", query_string={"source": source})

    assert second.status_code == 200
    assert second.get_json() == first.get_json()


# Phrase: "repeated `/convert` requests for the same source URL"
# Context: the cache is per source URL -- a different URL still downloads.
def test_cache_is_keyed_per_source_url(caching, client, origin):
    caching(True)
    origin.add("/cache-k1.csv", SIMPLE)
    origin.add("/cache-k2.csv", OTHER)
    before = _hits(origin, "/cache-k2.csv")

    first = client.get("/convert", query_string={"source": origin.url("/cache-k1.csv")})
    second = client.get("/convert", query_string={"source": origin.url("/cache-k2.csv")})

    assert _hits(origin, "/cache-k2.csv") - before == 1
    assert first.get_json()["endpoint"] != second.get_json()["endpoint"]


# Phrase: "Cache responses are identical to fresh parse responses."
def test_cached_response_is_identical_to_the_fresh_one(caching, client, origin):
    caching(True)
    path = "/cache-identical.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)

    fresh = client.get("/convert", query_string={"source": source})
    cached = client.get("/convert", query_string={"source": source})

    assert cached.status_code == fresh.status_code == 200
    assert cached.get_json() == fresh.get_json()
    assert set(cached.get_json()) == {"ok", "endpoint"}
    assert cached.get_json()["ok"] is True
    assert cached.mimetype == fresh.mimetype
    assert cached.headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Cache responses are identical to fresh parse responses."
# Context: the endpoint a cache hit hands back is fully queryable.
def test_cached_endpoint_is_queryable(caching, client, origin):
    caching(True)
    path = "/cache-queryable.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    client.get("/convert", query_string={"source": source})
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    response = client.get(endpoint, query_string={"name__exact": "bob"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["bob", 41]]


# Phrase: "repeated `/convert` requests for the same source URL" (T55)
# Context: the cache key is the source URL alone; `charset` does not reopen it.
def test_charset_does_not_change_the_cache_key(caching, client, origin):
    caching(True)
    path = "/cache-charset.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    first = client.get("/convert", query_string={"source": source})
    before = _hits(origin, path)

    second = client.get(
        "/convert", query_string={"source": source, "charset": "utf-8"}
    )

    assert second.status_code == 200
    assert second.get_json() == first.get_json()
    assert _hits(origin, path) == before


# Phrase: "Unsupported or malformed `charset` -> 400" under a cache hit (T61)
# Context: a hit does not bypass request validation.
def test_cache_hit_still_validates_the_request(caching, client, origin):
    caching(True)
    path = "/cache-validate.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    assert client.get("/convert", query_string={"source": source}).status_code == 200

    response = client.get(
        "/convert", query_string={"source": source, "charset": "definitely-not-a-codec"}
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# `CACHE_ENABLED`
# ---------------------------------------------------------------------------


# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values: true: `1`,
# `true`, `yes`, `on`"
@pytest.mark.parametrize(
    "value",
    ["1", "true", "yes", "on", "TRUE", "True", "YES", "Yes", "ON", "On", "oN", "tRuE"],
)
def test_true_values_enable_caching(config, value):
    assert config(CACHE_ENABLED=value) is None
    assert datagate.CACHE_ENABLED is True


# Phrase: "false: `0`, `false`, `no`, `off`"
@pytest.mark.parametrize(
    "value",
    ["0", "false", "no", "off", "FALSE", "False", "NO", "No", "OFF", "Off", "oFf"],
)
def test_false_values_disable_caching(config, value):
    assert config(CACHE_ENABLED=value) is None
    assert datagate.CACHE_ENABLED is False


# Phrase: "Invalid values fail startup."
# Context: "strict" -- anything outside the two lists is rejected, including an
# empty value and whitespace-padded tokens (T56).
@pytest.mark.parametrize(
    "value",
    ["", " ", "2", "-1", "y", "n", "t", "f", "yeah", "enabled", "disabled", "null",
     "none", "true false", " true", "true ", "\ttrue", "on\n", "1.0", "01", "TRUE!"],
)
def test_invalid_values_are_rejected(config, value):
    error = config(CACHE_ENABLED=value)
    assert isinstance(error, str) and error
    assert "CACHE_ENABLED" in error


# Phrase: "Invalid values fail startup."
# Context: the process must not end up serving.
def test_invalid_value_fails_startup(server):
    port = _free_port()
    instance = server(
        "--port", str(port), name="cache-invalid", env={"CACHE_ENABLED": "maybe"}
    )
    status = instance.wait_for_exit(timeout=20)
    assert status is not None and status != 0, instance.log()
    assert "CACHE_ENABLED" in instance.log()


# Phrase: "Invalid values fail startup." (empty value, T56)
def test_empty_value_fails_startup(server):
    port = _free_port()
    instance = server(
        "--port", str(port), name="cache-empty", env={"CACHE_ENABLED": ""}
    )
    status = instance.wait_for_exit(timeout=20)
    assert status is not None and status != 0, instance.log()


# Phrase: "`CACHE_ENABLED` accepts ... `on` / `off`"
# Context: a valid value starts the server normally.
@pytest.mark.parametrize("value", ["On", "off"])
def test_valid_value_starts_the_server(server, value):
    port = _free_port()
    instance = server(
        "--port", str(port),
        name="cache-valid-{}".format(value.lower()),
        env={"CACHE_ENABLED": value},
    )
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()


# Phrase: "`/convert` caches results by default."
# Context: end-to-end through a spawned server with no CACHE_ENABLED set.
def test_spawned_server_caches_by_default(server, origin):
    port = _free_port()
    path = "/cache-proc-default.csv"
    origin.add(path, SIMPLE)
    instance = server("--port", str(port), name="cache-proc-default")
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()
    before = _hits(origin, path)

    target = _convert_url(origin.url(path))
    first = _http_get("127.0.0.1", port, target)
    second = _http_get("127.0.0.1", port, target)

    assert first[0] == second[0] == 200
    assert json.loads(first[1]) == json.loads(second[1])
    assert _hits(origin, path) - before == 1


# Phrase: "When disabled, every `/convert` request re-downloads/parses and
# replaces stored data."
# Context: end-to-end through a spawned server with CACHE_ENABLED=0.
def test_spawned_server_with_caching_off_refetches(server, origin):
    port = _free_port()
    path = "/cache-proc-off.csv"
    origin.add(path, SIMPLE)
    instance = server(
        "--port", str(port), name="cache-proc-off", env={"CACHE_ENABLED": "0"}
    )
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()
    before = _hits(origin, path)

    target = _convert_url(origin.url(path))
    _http_get("127.0.0.1", port, target)
    _http_get("127.0.0.1", port, target)

    assert _hits(origin, path) - before == 2


# Phrase: "When disabled, every `/convert` request re-downloads/parses"
def test_disabled_refetches_on_every_request(caching, client, origin):
    caching(False)
    path = "/cache-off-refetch.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    before = _hits(origin, path)

    for _ in range(3):
        assert client.get("/convert", query_string={"source": source}).status_code == 200

    assert _hits(origin, path) - before == 3


# Phrase: "... and replaces stored data."
def test_disabled_replaces_stored_data(caching, client, origin):
    caching(False)
    path = "/cache-off-replace.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    origin.add(path, OTHER)
    again = client.get("/convert", query_string={"source": source})

    assert again.get_json()["endpoint"] == endpoint  # same id, new contents
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["city", "pop"]
    assert payload["rows"] == [["lisbon", 545]]


# Phrase: "When disabled, every `/convert` request re-downloads/parses and
# replaces stored data."
# Context: replacement is a replacement, not an append.
def test_disabled_does_not_accumulate_rows(caching, client, origin):
    caching(False)
    path = "/cache-off-noappend.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]
    client.get("/convert", query_string={"source": source})

    payload = client.get(endpoint).get_json()
    assert payload["rows"] == [["alice", 30], ["bob", 41]]
    assert payload["total"] == 2


# ---------------------------------------------------------------------------
# Per-request bypass
# ---------------------------------------------------------------------------


# Phrase: "`force` is a presence flag. If present once, it forces re-ingestion
# and replaces the cached dataset."
def test_force_reingests_a_cached_source(caching, client, origin):
    caching(True)
    path = "/force-basic.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    origin.add(path, OTHER)
    before = _hits(origin, path)
    forced = client.get(_convert_url(source, "&force"))

    assert forced.status_code == 200
    assert _hits(origin, path) - before == 1
    assert forced.get_json()["endpoint"] == endpoint
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["city", "pop"]
    assert payload["rows"] == [["lisbon", 545]]


# Phrase: "`force` is a presence flag."
# Context: the value carried is irrelevant -- presence alone forces (T58).
@pytest.mark.parametrize(
    "index,suffix",
    list(enumerate(["&force", "&force=", "&force=1", "&force=0", "&force=false",
                    "&force=no", "&force=whatever"])),
)
def test_force_value_is_ignored(caching, client, origin, index, suffix):
    caching(True)
    path = "/force-value{}.csv".format(index)
    origin.add(path, SIMPLE)
    source = origin.url(path)
    client.get("/convert", query_string={"source": source})

    origin.add(path, OTHER)
    before = _hits(origin, path)
    response = client.get(_convert_url(source, suffix))

    assert response.status_code == 200
    assert _hits(origin, path) - before == 1
    endpoint = response.get_json()["endpoint"]
    assert client.get(endpoint).get_json()["columns"] == ["city", "pop"]


# Phrase: "If present once, it forces re-ingestion"
# Context: forcing a source that was never cached simply ingests it.
def test_force_on_an_unknown_source_ingests_normally(caching, client, origin):
    caching(True)
    path = "/force-fresh.csv"
    origin.add(path, SIMPLE)
    response = client.get(_convert_url(origin.url(path), "&force"))

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"ok", "endpoint"}
    assert client.get(payload["endpoint"]).status_code == 200


# Phrase: "If present once, it forces re-ingestion and replaces the cached
# dataset."
# Context: after a forced refresh, a plain request caches the *new* data.
def test_plain_request_after_force_serves_the_refreshed_dataset(
    caching, client, origin
):
    caching(True)
    path = "/force-then-plain.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    client.get("/convert", query_string={"source": source})
    origin.add(path, OTHER)
    endpoint = client.get(_convert_url(source, "&force")).get_json()["endpoint"]

    before = _hits(origin, path)
    assert client.get("/convert", query_string={"source": source}).status_code == 200

    assert _hits(origin, path) == before
    assert client.get(endpoint).get_json()["columns"] == ["city", "pop"]


# Phrase: "Any additional `force` value is `HTTP 400`."
@pytest.mark.parametrize("suffix", ["&force&force", "&force=1&force=1",
                                    "&force=1&force=2", "&force=&force=",
                                    "&force&force=1", "&force&force&force"])
def test_repeated_force_is_400(caching, client, origin, suffix):
    caching(True)
    path = "/force-repeat.csv"
    origin.add(path, SIMPLE)
    response = client.get(_convert_url(origin.url(path), suffix))

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "Any additional `force` value is `HTTP 400`."
# Context: the rejected request performs no ingestion at all.
def test_repeated_force_does_not_ingest(caching, client, origin):
    caching(True)
    path = "/force-repeat-noingest.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    before = _hits(origin, path)

    response = client.get(_convert_url(source, "&force&force"))
    assert response.status_code == 400
    assert _hits(origin, path) == before

    identifier = datagate.dataset_id(source)
    assert client.get("/datasets/{}".format(identifier)).status_code == 404


# Phrase: "Any additional `force` value is `HTTP 400`."
# Context: a repeat does not damage a dataset that is already cached.
def test_repeated_force_leaves_a_cached_dataset_intact(caching, client, origin):
    caching(True)
    path = "/force-repeat-intact.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    assert client.get(_convert_url(source, "&force&force")).status_code == 400

    payload = client.get(endpoint).get_json()
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "If caching is disabled, `force` has no additional effect."
def test_force_has_no_additional_effect_when_disabled(caching, client, origin):
    caching(False)
    path = "/force-disabled.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    plain = client.get("/convert", query_string={"source": source})

    origin.add(path, OTHER)
    before = _hits(origin, path)
    forced = client.get(_convert_url(source, "&force"))

    assert forced.status_code == 200
    assert forced.get_json() == plain.get_json()  # same id, same envelope
    assert _hits(origin, path) - before == 1  # exactly one download, as usual
    endpoint = forced.get_json()["endpoint"]
    assert client.get(endpoint).get_json()["columns"] == ["city", "pop"]


# Phrase: "If caching is disabled, `force` has no additional effect."
# Context: the repeat rule is request validation, so it still applies (T60).
def test_repeated_force_is_still_400_when_disabled(caching, client, origin):
    caching(False)
    path = "/force-disabled-repeat.csv"
    origin.add(path, SIMPLE)
    response = client.get(_convert_url(origin.url(path), "&force&force"))

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: remote HTTP error on a forced refresh -> the documented 404 row.
def test_forced_reingestion_remote_error_is_404(caching, client, origin):
    caching(True)
    path = "/reingest-500.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    assert client.get("/convert", query_string={"source": source}).status_code == 200

    origin.add(path, "boom", status=500)
    response = client.get(_convert_url(source, "&force"))

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert set(payload) == {"ok", "error"}


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: non-tabular content on a forced refresh -> the documented 400 row.
def test_forced_reingestion_non_tabular_is_400(caching, client, origin):
    caching(True)
    path = "/reingest-html.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    client.get("/convert", query_string={"source": source})

    origin.add(path, "<html><body>hi</body></html>", content_type="text/html")
    response = client.get(_convert_url(source, "&force"))

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert set(payload) == {"ok", "error"}


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: the same failures on the caching-disabled path (no `force`).
def test_reingestion_failure_when_disabled_keeps_error_codes(caching, client, origin):
    caching(False)
    path = "/reingest-off.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    assert client.get("/convert", query_string={"source": source}).status_code == 200

    origin.add(path, "nope", status=503)
    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
def test_prior_dataset_survives_a_forced_failure(caching, client, origin):
    caching(True)
    path = "/reingest-keep.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    origin.add(path, "boom", status=500)
    assert client.get(_convert_url(source, "&force")).status_code == 404

    payload = client.get(endpoint).get_json()
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: "queryable" -- filters/sorting still work on the surviving dataset.
def test_surviving_dataset_still_supports_queries(caching, client, origin):
    caching(True)
    path = "/reingest-keep-query.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    origin.add(path, "<html>x</html>", content_type="text/html")
    assert client.get(_convert_url(source, "&force")).status_code == 400

    response = client.get(endpoint, query_string={"age__greater": "35"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["bob", 41]]


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: a plain request afterwards still finds the cached dataset.
def test_cache_still_hits_after_a_failed_force(caching, client, origin):
    caching(True)
    path = "/reingest-keep-hit.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    first = client.get("/convert", query_string={"source": source})

    origin.add(path, "boom", status=500)
    assert client.get(_convert_url(source, "&force")).status_code == 404

    before = _hits(origin, path)
    again = client.get("/convert", query_string={"source": source})
    assert again.status_code == 200
    assert again.get_json() == first.get_json()
    assert _hits(origin, path) == before


# Phrase: "Forced re-ingestion failure keeps prior dataset queryable." (T62)
# Context: the same atomicity on the caching-disabled path.
def test_prior_dataset_survives_a_failure_when_caching_disabled(
    caching, client, origin
):
    caching(False)
    path = "/reingest-off-keep.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    endpoint = client.get("/convert", query_string={"source": source}).get_json()[
        "endpoint"
    ]

    origin.add(path, "boom", status=500)
    assert client.get("/convert", query_string={"source": source}).status_code == 404

    payload = client.get(endpoint).get_json()
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: an unreachable host on a forced refresh is still the 404 row.
def test_forced_reingestion_unreachable_source_is_404(caching, client, origin):
    caching(False)
    dead = origin.dead_url("/never.csv")
    response = client.get(_convert_url(dead, "&force"))

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "`/convert` caches results by default." (T63)
# Context: the section is scoped to `/convert`; `/upload` keeps ingesting the
# bytes it is handed under either setting.
@pytest.mark.parametrize("enabled", [True, False])
def test_upload_is_unaffected_by_the_cache_setting(caching, upload, client, enabled):
    caching(enabled)
    first = upload(SIMPLE, filename="cache.csv")
    assert first.status_code == 200
    endpoint = first.get_json()["endpoint"]

    second = upload(SIMPLE, filename="cache.csv")
    assert second.status_code == 200
    assert second.get_json() == first.get_json()
    assert client.get(endpoint).get_json()["rows"] == [["alice", 30], ["bob", 41]]
