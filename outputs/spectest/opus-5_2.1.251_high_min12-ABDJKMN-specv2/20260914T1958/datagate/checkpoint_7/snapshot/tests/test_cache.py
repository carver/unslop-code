"""Spec section: Caching and Cache Controls."""
from urllib.parse import quote

import pytest

from conftest import (
    convert_ok,
    free_port,
    port_is_closed,
    start_expecting_failure,
)

A = "name,age\nAlice,30\n"
B = "name,age\nBrenda,41\nCarl,52\n"

ROWS_A = [["Alice", 30]]
ROWS_B = [["Brenda", 41], ["Carl", 52]]

TRUE_VALUES = ["1", "true", "yes", "on"]
FALSE_VALUES = ["0", "false", "no", "off"]


def raw_convert(gate, source, extra=""):
    """GET /convert with a hand-built query string (presence flags need one)."""
    query = "source=" + quote(source, safe="")
    if extra:
        query += "&" + extra
    return gate.get("/convert?" + query)


def body_of(gate, endpoint):
    resp = gate.get(endpoint)
    assert resp.status_code == 200, resp.text
    return resp.json()


def rows_of(gate, endpoint):
    return body_of(gate, endpoint)["rows"]


def assert_error_envelope(resp, status):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "`/convert` caches results by default."
# Context: no CACHE_ENABLED in the environment at all.
# ---------------------------------------------------------------------------
def test_caching_is_on_when_cache_enabled_is_unset(gate, origin):
    path = "/cache-default.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)
    before = origin.hit_count(path)

    origin.add(path, B)  # the origin now serves different bytes
    assert convert_ok(gate, url) == endpoint
    assert origin.hit_count(path) == before      # nothing was re-downloaded
    assert rows_of(gate, endpoint) == ROWS_A     # stored data was not replaced


# ---------------------------------------------------------------------------
# Phrase: "repeated `/convert` requests for the same source URL can return the
#          cached dataset id"
# Context: cache behavior with caching enabled.
# ---------------------------------------------------------------------------
def test_repeated_convert_returns_the_same_dataset_id(gate, origin):
    url = origin.add("/cache-same-id.csv", A)
    endpoints = {convert_ok(gate, url) for _ in range(4)}
    assert len(endpoints) == 1


# ---------------------------------------------------------------------------
# Phrase: "... without re-downloading."
# Context: cache behavior; the origin must not be contacted again.
# ---------------------------------------------------------------------------
def test_cached_convert_does_not_hit_the_origin_again(gate, origin):
    path = "/cache-no-refetch.csv"
    url = origin.add(path, A)
    convert_ok(gate, url)
    after_first = origin.hit_count(path)
    assert after_first >= 1

    for _ in range(3):
        convert_ok(gate, url)
    assert origin.hit_count(path) == after_first


# ---------------------------------------------------------------------------
# Phrase: "... without re-downloading."
# Context: a cached source that has since become unreachable still succeeds.
# ---------------------------------------------------------------------------
def test_cached_convert_succeeds_after_the_source_disappears(gate, origin):
    path = "/cache-gone.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)

    origin.remove(path)  # the origin would now answer 404
    assert convert_ok(gate, url) == endpoint
    assert rows_of(gate, endpoint) == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "Cache responses are identical to fresh parse responses."
# Context: status, body, and envelope must not reveal the cache.
# ---------------------------------------------------------------------------
def test_cache_response_is_byte_identical_to_the_fresh_response(gate, origin):
    url = origin.add("/cache-identical.csv", A)
    fresh = gate.convert(source=url)
    cached = gate.convert(source=url)

    assert fresh.status_code == cached.status_code == 200
    assert fresh.json() == cached.json()
    assert set(cached.json()) == {"ok", "endpoint"}
    assert cached.json()["ok"] is True
    assert fresh.headers.get("Content-Type") == cached.headers.get("Content-Type")


# ---------------------------------------------------------------------------
# Phrase: "Cache responses are identical to fresh parse responses."
# Context: the dataset a cache hit points at is queryable exactly as before.
# ---------------------------------------------------------------------------
def test_cached_endpoint_still_serves_the_full_dataset(gate, origin):
    url = origin.add("/cache-identical-data.csv", A)
    endpoint = convert_ok(gate, url)
    first = gate.get(endpoint).json()
    convert_ok(gate, url)
    second = gate.get(endpoint).json()

    assert first["columns"] == second["columns"] == ["name", "age"]
    assert first["rows"] == second["rows"] == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values: true: `1`,
#          `true`, `yes`, `on`"
# Context: each documented true spelling starts the server with caching on.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", TRUE_VALUES)
def test_true_values_enable_caching(fresh_gate, origin, value):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": value})
    path = f"/cache-true-{value}.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(server, url)
    before = origin.hit_count(path)

    origin.add(path, B)
    assert convert_ok(server, url) == endpoint
    assert origin.hit_count(path) == before
    assert rows_of(server, endpoint) == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values"
# Context: true spellings in mixed/upper case are equally accepted.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["TRUE", "True", "tRuE", "YES", "Yes", "ON", "On"])
def test_true_values_are_case_insensitive(fresh_gate, origin, value):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": value})
    path = f"/cache-truecase-{value}.csv"
    url = origin.add(path, A)
    convert_ok(server, url)
    before = origin.hit_count(path)
    convert_ok(server, url)
    assert origin.hit_count(path) == before


# ---------------------------------------------------------------------------
# Phrase: "false: `0`, `false`, `no`, `off`"
# Context: each documented false spelling disables the cache.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", FALSE_VALUES)
def test_false_values_disable_caching(fresh_gate, origin, value):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": value})
    path = f"/cache-false-{value}.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(server, url)
    before = origin.hit_count(path)

    origin.add(path, B)
    assert convert_ok(server, url) == endpoint
    assert origin.hit_count(path) > before
    assert rows_of(server, endpoint) == ROWS_B


# ---------------------------------------------------------------------------
# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values"
# Context: false spellings in mixed/upper case are equally accepted.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["FALSE", "False", "NO", "No", "OFF", "Off", "oFf"])
def test_false_values_are_case_insensitive(fresh_gate, origin, value):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": value})
    path = f"/cache-falsecase-{value}.csv"
    url = origin.add(path, A)
    convert_ok(server, url)
    before = origin.hit_count(path)
    convert_ok(server, url)
    assert origin.hit_count(path) > before


# ---------------------------------------------------------------------------
# Phrase: "Invalid values fail startup."
# Context: anything outside the two documented lists, including near misses
#          and empty (see AMBIGUITIES T50). Padded spellings moved out of this
#          list once the configuration spec said booleans are "trimmed".
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["2", "-1", "maybe", "enabled", "disabled", "y", "n", "t", "f",
     "truthy", "", "tru", "onoff", "null", "None"],
)
def test_invalid_cache_enabled_fails_startup(value):
    returncode, log, port = start_expecting_failure(env={"CACHE_ENABLED": value})
    assert returncode != 0, log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "Invalid values fail startup."
# Context: the failure names the offending variable so it is diagnosable.
# ---------------------------------------------------------------------------
def test_padded_boolean_spellings_are_trimmed(fresh_gate, origin):
    """Configuration spec: boolean values are "(case-insensitive, trimmed)"."""
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "  off  "})
    path = "/cache-padded-off.csv"
    url = origin.add(path, A)
    convert_ok(server, url)
    before = origin.hit_count(path)
    convert_ok(server, url)
    assert origin.hit_count(path) > before


def test_invalid_cache_enabled_reports_the_variable():
    returncode, log, _ = start_expecting_failure(env={"CACHE_ENABLED": "sometimes"})
    assert returncode != 0
    assert "CACHE_ENABLED" in log


# ---------------------------------------------------------------------------
# Phrase: "When disabled, every `/convert` request re-downloads/parses and
#          replaces stored data."
# Context: every request, not just the second one.
# ---------------------------------------------------------------------------
def test_disabled_cache_redownloads_on_every_request(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "off"})
    path = "/cache-off-every.csv"
    url = origin.add(path, A)
    convert_ok(server, url)
    first = origin.hit_count(path)
    for expected in range(1, 4):
        convert_ok(server, url)
        assert origin.hit_count(path) == first + expected


# ---------------------------------------------------------------------------
# Phrase: "... and replaces stored data."
# Context: cache disabled; the stored rows track the latest download.
# ---------------------------------------------------------------------------
def test_disabled_cache_replaces_stored_data(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "0"})
    path = "/cache-off-replace.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(server, url)
    assert rows_of(server, endpoint) == ROWS_A

    origin.add(path, "city,pop\nOslo,700000\n")
    assert convert_ok(server, url) == endpoint
    body = body_of(server, endpoint)
    assert body["columns"] == ["city", "pop"]
    assert body["rows"] == [["Oslo", 700000]]


# ---------------------------------------------------------------------------
# Phrase: "`force` is a presence flag."
# Context: `?force` carries no value and is accepted.
# ---------------------------------------------------------------------------
def test_bare_force_is_accepted(gate, origin):
    url = origin.add("/cache-force-bare.csv", A)
    resp = raw_convert(gate, url, "force")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Phrase: "If present once, it forces re-ingestion and replaces the cached
#          dataset."
# Context: per-request bypass with caching enabled.
# ---------------------------------------------------------------------------
def test_force_re_ingests_and_replaces_the_cached_dataset(gate, origin):
    path = "/cache-force-replace.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)
    before = origin.hit_count(path)

    origin.add(path, B)
    resp = raw_convert(gate, url, "force")
    assert resp.status_code == 200, resp.text
    assert resp.json()["endpoint"] == endpoint   # same id, replaced contents
    assert origin.hit_count(path) > before
    assert rows_of(gate, endpoint) == ROWS_B


# ---------------------------------------------------------------------------
# Phrase: "If present once, it forces re-ingestion ..."
# Context: forcing is per-request -- the next unforced request is cached again.
# ---------------------------------------------------------------------------
def test_force_does_not_disable_caching_for_later_requests(gate, origin):
    path = "/cache-force-per-request.csv"
    url = origin.add(path, A)
    convert_ok(gate, url)
    raw_convert(gate, url, "force")
    after_force = origin.hit_count(path)

    convert_ok(gate, url)
    assert origin.hit_count(path) == after_force


# ---------------------------------------------------------------------------
# Phrase: "If present once ..."
# Context: `force` repeated in one query string is not "present once"
#          (see AMBIGUITIES T52).
# ---------------------------------------------------------------------------
def test_repeated_force_is_400(gate, origin):
    url = origin.add("/cache-force-repeat.csv", A)
    assert_error_envelope(raw_convert(gate, url, "force&force"), 400)


# ---------------------------------------------------------------------------
# Phrase: "Any `force` value is `HTTP 400`."
# Context: per-request bypass; even "true"-looking values are rejected.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["1", "0", "true", "false", "yes", "on", "force", "x"])
def test_force_with_a_value_is_400(gate, origin, value):
    url = origin.add("/cache-force-value.csv", A)
    assert_error_envelope(raw_convert(gate, url, f"force={value}"), 400)


# ---------------------------------------------------------------------------
# Phrase: "Any `force` value is `HTTP 400`."
# Context: an empty value is still a value (see AMBIGUITIES T51).
# ---------------------------------------------------------------------------
def test_force_with_an_empty_value_is_400(gate, origin):
    url = origin.add("/cache-force-empty.csv", A)
    assert_error_envelope(raw_convert(gate, url, "force="), 400)


# ---------------------------------------------------------------------------
# Phrase: "Any `force` value is `HTTP 400`."
# Context: the rejected request must not re-ingest or disturb the cache.
# ---------------------------------------------------------------------------
def test_rejected_force_leaves_the_cached_dataset_alone(gate, origin):
    path = "/cache-force-value-noop.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)
    before = origin.hit_count(path)

    origin.add(path, B)
    assert_error_envelope(raw_convert(gate, url, "force=1"), 400)
    assert origin.hit_count(path) == before
    assert rows_of(gate, endpoint) == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "Any `force` value is `HTTP 400`."
# Context: the 400 applies with caching disabled too (see AMBIGUITIES T53).
# ---------------------------------------------------------------------------
def test_force_with_a_value_is_400_when_caching_is_disabled(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "no"})
    url = origin.add("/cache-off-force-value.csv", A)
    assert_error_envelope(raw_convert(server, url, "force=1"), 400)


# ---------------------------------------------------------------------------
# Phrase: "If caching is disabled, `force` has no additional effect."
# Context: `?force` and a plain request behave identically without a cache.
# ---------------------------------------------------------------------------
def test_force_is_a_no_op_when_caching_is_disabled(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "false"})
    path = "/cache-off-force.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(server, url)
    before = origin.hit_count(path)

    origin.add(path, B)
    resp = raw_convert(server, url, "force")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "endpoint": endpoint}
    assert origin.hit_count(path) == before + 1
    assert rows_of(server, endpoint) == ROWS_B


# ---------------------------------------------------------------------------
# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: caching disabled; the source has become unreachable.
# ---------------------------------------------------------------------------
def test_re_ingestion_failure_keeps_the_404_envelope(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "off"})
    path = "/cache-reingest-404.csv"
    url = origin.add(path, A)
    convert_ok(server, url)

    origin.remove(path)
    assert_error_envelope(server.convert(source=url), 404)


# ---------------------------------------------------------------------------
# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: a re-ingest whose new bytes are not tabular keeps the 400 code.
# ---------------------------------------------------------------------------
def test_re_ingestion_failure_keeps_the_400_envelope(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "off"})
    path = "/cache-reingest-400.csv"
    url = origin.add(path, A)
    convert_ok(server, url)

    origin.add(path, b"%PDF-1.4\n%not tabular at all\n", content_type="application/pdf")
    assert_error_envelope(server.convert(source=url), 400)


# ---------------------------------------------------------------------------
# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: caching disabled; a failed re-ingest leaves the stored rows intact.
# ---------------------------------------------------------------------------
def test_failed_re_ingestion_keeps_the_prior_rows(fresh_gate, origin):
    server = fresh_gate(port=free_port(), address="127.0.0.1",
                        env={"CACHE_ENABLED": "0"})
    path = "/cache-reingest-keep.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(server, url)

    origin.remove(path)
    assert server.convert(source=url).status_code == 404
    assert rows_of(server, endpoint) == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: caching enabled; `?force` against a now-unreachable source.
# ---------------------------------------------------------------------------
def test_forced_re_ingestion_failure_keeps_prior_dataset(gate, origin):
    path = "/cache-force-fail.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)

    origin.remove(path)
    assert_error_envelope(raw_convert(gate, url, "force"), 404)

    resp = gate.get(endpoint)
    assert resp.status_code == 200, resp.text
    assert resp.json()["columns"] == ["name", "age"]
    assert resp.json()["rows"] == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: a failed forced re-ingest must not evict the cache entry either.
# ---------------------------------------------------------------------------
def test_cache_survives_a_failed_forced_re_ingestion(gate, origin):
    path = "/cache-force-fail-then-hit.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)

    origin.remove(path)
    assert raw_convert(gate, url, "force").status_code == 404
    hits = origin.hit_count(path)

    assert convert_ok(gate, url) == endpoint     # still served from cache
    assert origin.hit_count(path) == hits
    assert rows_of(gate, endpoint) == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: a forced re-ingest that fails on parsing, not on the network.
# ---------------------------------------------------------------------------
def test_forced_parse_failure_keeps_prior_dataset(gate, origin):
    path = "/cache-force-parse-fail.csv"
    url = origin.add(path, A)
    endpoint = convert_ok(gate, url)

    origin.add(path, b"%PDF-1.4\n%binary\n", content_type="application/pdf")
    assert_error_envelope(raw_convert(gate, url, "force"), 400)
    assert rows_of(gate, endpoint) == ROWS_A


# ---------------------------------------------------------------------------
# Phrase: "repeated `/convert` requests for the same source URL"
# Context: the cache is keyed by the source URL, not by other parameters
#          (see AMBIGUITIES T49).
# ---------------------------------------------------------------------------
def test_cache_is_keyed_by_source_url_only(gate, origin):
    path = "/cache-key-charset.csv"
    url = origin.add(path, A)
    convert_ok(gate, url)
    before = origin.hit_count(path)

    assert convert_ok(gate, url, charset="utf-8") == convert_ok(gate, url)
    assert origin.hit_count(path) == before


# ---------------------------------------------------------------------------
# Phrase: "repeated `/convert` requests for the same source URL"
# Context: a different URL is a different cache entry.
# ---------------------------------------------------------------------------
def test_a_different_source_is_not_served_from_the_cache(gate, origin):
    first = origin.add("/cache-distinct-1.csv", A)
    second_path = "/cache-distinct-2.csv"
    second = origin.add(second_path, B)

    one = convert_ok(gate, first)
    two = convert_ok(gate, second)
    assert one != two
    assert origin.hit_count(second_path) >= 1
    assert rows_of(gate, two) == ROWS_B


# ---------------------------------------------------------------------------
# Phrase: "`/convert` caches results by default."
# Context: validation still runs ahead of any cache hit.
# ---------------------------------------------------------------------------
def test_cached_source_still_validates_its_charset(gate, origin):
    url = origin.add("/cache-validate.csv", A)
    convert_ok(gate, url)
    assert_error_envelope(gate.convert(source=url, charset="not-a-charset"), 400)


# ---------------------------------------------------------------------------
# Phrase: "`/convert` caches results by default."
# Context: a failed convert caches nothing, so a later good one still fetches.
# ---------------------------------------------------------------------------
def test_failures_are_not_cached(gate, origin):
    path = "/cache-failure-not-cached.csv"
    url = origin.url(path)
    assert gate.convert(source=url).status_code == 404

    origin.add(path, A)
    endpoint = convert_ok(gate, url)
    assert rows_of(gate, endpoint) == ROWS_A
