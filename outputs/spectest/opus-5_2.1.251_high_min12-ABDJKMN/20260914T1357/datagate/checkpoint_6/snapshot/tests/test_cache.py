"""Spec tests for "Caching and Cache Controls". Each section quotes its phrase."""
import contextlib
import json
import time
import urllib.parse

import pytest

from conftest import Client, free_port, spawn_env, stop, wait_for_port

SIMPLE = "name,age\nada,36\ngrace,45\n"
OTHER = "name,age\nlin,29\n"


def slug(value):
    """A URL-safe fixture name for a parametrised setting value."""
    return "".join(c if c.isalnum() else "-" for c in value.lower()) or "blank"


def path_of(url):
    return urllib.parse.urlsplit(url).path


def hits(origin, url):
    """How many times the origin has served this URL (0 if never)."""
    return origin.hits.get(path_of(url), 0)


@contextlib.contextmanager
def running(env, tag):
    """A datagate server started with `env` overrides, stopped on exit."""
    port = free_port()
    proc = spawn_env(port, env, tag=tag)
    try:
        assert wait_for_port("127.0.0.1", port), "datagate did not start"
        yield Client("http://127.0.0.1:%d" % port)
    finally:
        stop(proc)


@pytest.fixture(scope="module")
def cached():
    """A server with `CACHE_ENABLED` unset: caching on by default."""
    with running({"CACHE_ENABLED": None}, "cache_on") as client:
        yield client


@pytest.fixture(scope="module")
def uncached():
    """A server started with `CACHE_ENABLED=false`."""
    with running({"CACHE_ENABLED": "false"}, "cache_off") as client:
        yield client


@pytest.fixture
def source(origin, csv_url):
    """A mutable source: returns (url, rewrite) where rewrite swaps the body."""
    def make(body, name="cache", status=200, content_type="text/csv"):
        url = csv_url(body, name=name, status=status, content_type=content_type)

        def rewrite(new_body, status=200, content_type="text/csv"):
            origin.add(path_of(url), new_body, status=status,
                       content_type=content_type)

        return url, rewrite
    return make


def rows_at(client, endpoint):
    status, _, payload = client.get(endpoint)
    assert status == 200, payload
    return payload["rows"]


def assert_error_envelope(status, data, expected):
    """Spec: errors keep the existing `{"ok": false, "error": "..."}` envelope."""
    assert status == expected, data
    assert data is not None
    assert data["ok"] is False
    assert isinstance(data["error"], str) and data["error"].strip()


# ==========================================================================
# Spec: "`/convert` caches results by default."
# ==========================================================================
def test_convert_caches_by_default(cached, origin, source):
    url, _ = source(SIMPLE, name="default-on")
    first = cached.convert(url)
    assert first[0] == 200, first[2]
    after_first = hits(origin, url)
    second = cached.convert(url)
    assert second[0] == 200, second[2]
    assert hits(origin, url) == after_first  # no second download


# Spec: "caches results by default" — default means with CACHE_ENABLED unset,
# which is how the shared session server runs.
def test_default_server_caches_without_env_var(server, origin, source):
    url, rewrite = source(SIMPLE, name="default-session")
    endpoint = server.convert(url)[2]["endpoint"]
    rewrite(OTHER)
    assert server.convert(url)[2]["endpoint"] == endpoint
    assert rows_at(server, endpoint) == [["ada", 36], ["grace", 45]]


# ==========================================================================
# Spec: "With caching enabled, repeated `/convert` requests for the same
#        source URL can return the cached dataset id without re-downloading."
# ==========================================================================
def test_repeated_convert_returns_same_dataset_id(cached, source):
    url, _ = source(SIMPLE, name="same-id")
    ids = [cached.convert(url)[2]["endpoint"] for _ in range(3)]
    assert len(set(ids)) == 1
    assert ids[0].startswith("/datasets/")


# Spec: "... without re-downloading." — the origin is hit exactly once.
def test_cached_convert_does_not_redownload(cached, origin, source):
    url, _ = source(SIMPLE, name="no-redownload")
    cached.convert(url)
    baseline = hits(origin, url)
    for _ in range(4):
        assert cached.convert(url)[0] == 200
    assert hits(origin, url) == baseline


# Spec: "... without re-downloading." — a hit succeeds even though the remote
# has since started failing, which proves no request was made.
def test_cache_hit_survives_broken_remote(cached, source):
    url, rewrite = source(SIMPLE, name="broken-remote")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite(b"gone", status=500, content_type="text/plain")
    status, _, data = cached.convert(url)
    assert status == 200, data
    assert data["endpoint"] == endpoint


# Spec: "... without re-downloading." — the stored dataset is the one parsed on
# the first request, not whatever the remote serves now.
def test_cache_hit_keeps_original_data(cached, source):
    url, rewrite = source(SIMPLE, name="keeps-data")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite("a,b\n1,2\n")
    cached.convert(url)
    assert rows_at(cached, endpoint) == [["ada", 36], ["grace", 45]]


# Spec: "for the same source URL" — a different URL is a miss and is fetched.
def test_different_url_is_not_a_cache_hit(cached, origin, source):
    url_a, _ = source(SIMPLE, name="miss-a")
    url_b, _ = source(OTHER, name="miss-b")
    a = cached.convert(url_a)[2]["endpoint"]
    b = cached.convert(url_b)[2]["endpoint"]
    assert a != b
    assert hits(origin, url_b) >= 1
    assert rows_at(cached, b) == [["lin", 29]]


# ==========================================================================
# Spec: "Cache responses are identical to fresh parse responses."
# ==========================================================================
def test_cached_response_is_identical_to_fresh(cached, source):
    url, _ = source(SIMPLE, name="identical")
    fresh_status, fresh_headers, fresh_body = cached.raw("/convert?source="
                                                         + urllib.parse.quote(url, safe=""))
    hit_status, hit_headers, hit_body = cached.raw("/convert?source="
                                                   + urllib.parse.quote(url, safe=""))
    assert fresh_status == hit_status == 200
    assert fresh_body == hit_body
    assert json.loads(hit_body.decode("utf-8")) == {
        "ok": True, "endpoint": json.loads(fresh_body.decode("utf-8"))["endpoint"]}
    assert (hit_headers.get("Content-Type", "").split(";")[0]
            == fresh_headers.get("Content-Type", "").split(";")[0])


# Spec: "identical to fresh parse responses" — same keys, same envelope shape.
def test_cached_response_envelope(cached, source):
    url, _ = source(SIMPLE, name="envelope")
    first = cached.convert(url)[2]
    second = cached.convert(url)[2]
    assert first == second
    assert first["ok"] is True
    assert list(first.keys()) == list(second.keys())


# ==========================================================================
# Spec: "`CACHE_ENABLED` accepts strict case-insensitive values:
#        - true: `1`, `true`, `yes`, `on`"
# ==========================================================================
@pytest.mark.parametrize("value", ["1", "true", "yes", "on",
                                   "TRUE", "Yes", "ON", "True", "oN",
                                   " true ", "on\t"])
def test_cache_enabled_true_values(origin, source, value):
    url, rewrite = source(SIMPLE, name="true-" + slug(value))
    with running({"CACHE_ENABLED": value}, "cache_true") as client:
        endpoint = client.convert(url)[2]["endpoint"]
        baseline = hits(origin, url)
        rewrite(OTHER)
        assert client.convert(url)[2]["endpoint"] == endpoint
        assert hits(origin, url) == baseline
        assert rows_at(client, endpoint) == [["ada", 36], ["grace", 45]]


# ==========================================================================
# Spec: "- false: `0`, `false`, `no`, `off`"
# ==========================================================================
@pytest.mark.parametrize("value", ["0", "false", "no", "off",
                                   "FALSE", "No", "OFF", "False", "oFf",
                                   " false ", "\toff\n"])
def test_cache_enabled_false_values(origin, source, value):
    url, rewrite = source(SIMPLE, name="false-" + slug(value))
    with running({"CACHE_ENABLED": value}, "cache_false") as client:
        endpoint = client.convert(url)[2]["endpoint"]
        baseline = hits(origin, url)
        rewrite(OTHER)
        assert client.convert(url)[2]["endpoint"] == endpoint
        assert hits(origin, url) > baseline
        assert rows_at(client, endpoint) == [["lin", 29]]


# ==========================================================================
# Spec: "Invalid values fail startup." (see AMBIGUITIES T62/T64)
#
# The later Configuration spec settles T63: boolean values are "case-insensitive,
# trimmed", so padded spellings (" true ", "on\n") are now *valid* and are tested
# with the accepted values above; a value that trims to nothing stays invalid.
# ==========================================================================
@pytest.mark.parametrize("value", [
    "maybe", "2", "-1", "truthy", "enabled", "disabled", "tru", "yess",
    "y", "n", "t", "f", "null", "none", "", " ", "\t",
    "yes,no", "TRUE!", "true false",
])
def test_invalid_cache_enabled_fails_startup(value):
    port = free_port()
    proc = spawn_env(port, {"CACHE_ENABLED": value}, tag="cache_bad")
    try:
        deadline = time.time() + 20
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        assert proc.poll() is not None, "server started despite invalid value"
        assert proc.returncode != 0, "startup failure must exit non-zero"
        assert not wait_for_port("127.0.0.1", port, timeout=0.5)
    finally:
        stop(proc)


# Spec: "Invalid values fail startup." — a valid value does not.
@pytest.mark.parametrize("value", ["on", "off"])
def test_valid_cache_enabled_starts(value):
    with running({"CACHE_ENABLED": value}, "cache_ok") as client:
        status, _, data = client.get("/datasets/definitely-unknown")
        assert status == 404
        assert data["ok"] is False


# ==========================================================================
# Spec: "When disabled, every `/convert` request re-downloads/parses and
#        replaces stored data."
# ==========================================================================
def test_disabled_redownloads_every_request(uncached, origin, source):
    url, _ = source(SIMPLE, name="redownload")
    uncached.convert(url)
    baseline = hits(origin, url)
    for n in range(1, 4):
        assert uncached.convert(url)[0] == 200
        assert hits(origin, url) == baseline + n


# Spec: "... and replaces stored data." — the new parse wins.
def test_disabled_replaces_stored_data(uncached, source):
    url, rewrite = source(SIMPLE, name="replace")
    endpoint = uncached.convert(url)[2]["endpoint"]
    assert rows_at(uncached, endpoint) == [["ada", 36], ["grace", 45]]
    rewrite("name,age\nlin,29\nkay,31\n")
    assert uncached.convert(url)[2]["endpoint"] == endpoint
    assert rows_at(uncached, endpoint) == [["lin", 29], ["kay", 31]]


# Spec: "... replaces stored data." — including a change of columns.
def test_disabled_replaces_columns(uncached, source):
    url, rewrite = source(SIMPLE, name="replace-cols")
    endpoint = uncached.convert(url)[2]["endpoint"]
    rewrite("x,y,z\n1,2,3\n")
    uncached.convert(url)
    _, _, payload = uncached.get(endpoint)
    assert payload["columns"] == ["x", "y", "z"]
    assert payload["rows"] == [[1, 2, 3]]


# Spec: "every `/convert` request re-downloads" — the dataset id still derives
# from the URL, so the endpoint is unchanged across re-ingestions.
def test_disabled_keeps_dataset_id_stable(uncached, source):
    url, rewrite = source(SIMPLE, name="stable-id")
    first = uncached.convert(url)[2]["endpoint"]
    rewrite(OTHER)
    assert uncached.convert(url)[2]["endpoint"] == first


# Spec: caching is a `/convert` concern; stored datasets stay queryable when it
# is disabled (see AMBIGUITIES T73).
def test_disabled_dataset_still_queryable_and_exportable(uncached, source):
    url, _ = source(SIMPLE, name="still-queryable")
    endpoint = uncached.convert(url)[2]["endpoint"]
    assert rows_at(uncached, endpoint) == [["ada", 36], ["grace", 45]]
    status, _, body = uncached.raw(endpoint + "/export")
    assert status == 200
    assert b"ada" in body


# ==========================================================================
# Spec: "`force` is a presence flag." (see AMBIGUITIES T59)
# ==========================================================================
@pytest.mark.parametrize("spelling", ["force", "force=", "force=1", "force=0",
                                      "force=true", "force=false", "force=x"])
def test_force_is_a_presence_flag(cached, origin, source, spelling):
    url, _ = source(SIMPLE, name="presence")
    cached.convert(url)
    baseline = hits(origin, url)
    status, _, data = cached.convert(url, extra=spelling)
    assert status == 200, data
    assert hits(origin, url) == baseline + 1


# Spec: "`force` is a presence flag." — absent means no forcing (cache hit).
def test_absent_force_does_not_re_ingest(cached, origin, source):
    url, _ = source(SIMPLE, name="absent-force")
    cached.convert(url)
    baseline = hits(origin, url)
    cached.convert(url)
    assert hits(origin, url) == baseline


# ==========================================================================
# Spec: "If present once, it forces re-ingestion and replaces the cached
#        dataset."
# ==========================================================================
def test_force_re_ingests(cached, origin, source):
    url, _ = source(SIMPLE, name="forces")
    cached.convert(url)
    baseline = hits(origin, url)
    assert cached.convert(url, extra="force")[0] == 200
    assert hits(origin, url) == baseline + 1


# Spec: "... and replaces the cached dataset."
def test_force_replaces_cached_dataset(cached, source):
    url, rewrite = source(SIMPLE, name="force-replace")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite("name,age\nlin,29\nkay,31\n")
    forced = cached.convert(url, extra="force")
    assert forced[0] == 200
    assert forced[2]["endpoint"] == endpoint
    assert rows_at(cached, endpoint) == [["lin", 29], ["kay", 31]]


# Spec: "... replaces the cached dataset." — the replacement is what later
# unforced requests serve.
def test_after_force_cache_serves_new_data(cached, origin, source):
    url, rewrite = source(SIMPLE, name="force-then-cache")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite(OTHER)
    cached.convert(url, extra="force")
    baseline = hits(origin, url)
    assert cached.convert(url)[2]["endpoint"] == endpoint
    assert hits(origin, url) == baseline
    assert rows_at(cached, endpoint) == [["lin", 29]]


# Spec: "If present once, it forces re-ingestion" — forcing an unknown URL is
# an ordinary first ingestion, not an error.
def test_force_on_first_conversion(cached, source):
    url, _ = source(SIMPLE, name="force-first")
    status, _, data = cached.convert(url, extra="force")
    assert status == 200, data
    assert rows_at(cached, data["endpoint"]) == [["ada", 36], ["grace", 45]]


# Spec: "forces re-ingestion" — the forced response is the same envelope.
def test_forced_response_matches_cached_response(cached, source):
    url, _ = source(SIMPLE, name="force-envelope")
    plain = cached.convert(url)[2]
    forced = cached.convert(url, extra="force")[2]
    assert forced == plain


# ==========================================================================
# Spec: "Any additional `force` value is `HTTP 400`."
# ==========================================================================
@pytest.mark.parametrize("extra", [
    "force&force",
    "force=1&force=1",
    "force=1&force=2",
    "force=&force=",
    "force&force=1",
    "force&force&force",
])
def test_duplicate_force_is_400(cached, source, extra):
    url, _ = source(SIMPLE, name="dup-force")
    status, _, data = cached.convert(url, extra=extra)
    assert_error_envelope(status, data, 400)


# Spec: "Any additional `force` value is `HTTP 400`." — the rejected request
# must not have re-ingested anything.
def test_duplicate_force_does_not_re_ingest(cached, origin, source):
    url, rewrite = source(SIMPLE, name="dup-no-ingest")
    endpoint = cached.convert(url)[2]["endpoint"]
    baseline = hits(origin, url)
    rewrite(OTHER)
    assert cached.convert(url, extra="force&force")[0] == 400
    assert hits(origin, url) == baseline
    assert rows_at(cached, endpoint) == [["ada", 36], ["grace", 45]]


# Spec: "Any additional `force` value is `HTTP 400`." — argument validation
# precedes the fetch, so a dead source still reports 400 (AMBIGUITIES T67).
def test_duplicate_force_beats_unreachable_source(cached):
    dead = "http://127.0.0.1:%d/gone.csv" % free_port()
    status, _, data = cached.convert(dead, extra="force&force")
    assert_error_envelope(status, data, 400)


# Spec: a single `force` is never a 400, however it is spelled.
@pytest.mark.parametrize("extra", ["force", "force=", "force=0"])
def test_single_force_is_not_400(cached, source, extra):
    url, _ = source(SIMPLE, name="single-force")
    assert cached.convert(url, extra=extra)[0] == 200


# ==========================================================================
# Spec: "If caching is disabled, `force` has no additional effect."
# ==========================================================================
def test_force_is_noop_when_cache_disabled(uncached, origin, source):
    url, _ = source(SIMPLE, name="force-noop")
    uncached.convert(url)
    baseline = hits(origin, url)
    assert uncached.convert(url, extra="force")[0] == 200
    assert hits(origin, url) == baseline + 1  # exactly one re-download
    assert uncached.convert(url)[0] == 200
    assert hits(origin, url) == baseline + 2


# Spec: "no additional effect" — forced and unforced responses agree.
def test_forced_and_unforced_agree_when_disabled(uncached, source):
    url, rewrite = source(SIMPLE, name="force-agree")
    forced = uncached.convert(url, extra="force")[2]
    plain = uncached.convert(url)[2]
    assert forced == plain
    rewrite(OTHER)
    assert uncached.convert(url, extra="force")[2] == forced
    assert rows_at(uncached, forced["endpoint"]) == [["lin", 29]]


# Spec: "no additional effect" describes the behaviour, not the arity rule:
# a duplicate `force` is still a 400 (see AMBIGUITIES T68).
def test_duplicate_force_still_400_when_disabled(uncached, source):
    url, _ = source(SIMPLE, name="dup-disabled")
    status, _, data = uncached.convert(url, extra="force&force")
    assert_error_envelope(status, data, 400)


# ==========================================================================
# Spec: "Re-ingestion failures keep existing error codes and envelope."
# ==========================================================================
def test_re_ingestion_remote_error_is_404(cached, source):
    url, rewrite = source(SIMPLE, name="reingest-404")
    cached.convert(url)
    rewrite(b"boom", status=500, content_type="text/plain")
    status, _, data = cached.convert(url, extra="force")
    assert_error_envelope(status, data, 404)


# Spec: same phrase — a source that becomes non-tabular keeps the 400.
def test_re_ingestion_non_tabular_is_400(cached, source):
    url, rewrite = source(SIMPLE, name="reingest-400")
    cached.convert(url)
    rewrite("<html><body>nope</body></html>", content_type="text/html")
    status, _, data = cached.convert(url, extra="force")
    assert_error_envelope(status, data, 400)


# Spec: same phrase — an unrecognised binary format keeps the 400.
def test_re_ingestion_unrecognised_format_is_400(cached, source):
    url, rewrite = source(SIMPLE, name="reingest-binary")
    cached.convert(url)
    rewrite(b"%PDF-1.4\n%\xc7\xec\x8f\xa2\n", content_type="application/pdf")
    status, _, data = cached.convert(url, extra="force")
    assert_error_envelope(status, data, 400)


# Spec: same phrase — with caching disabled, the ordinary re-ingestion of every
# request reports the same codes.
def test_re_ingestion_failure_codes_when_disabled(uncached, source):
    url, rewrite = source(SIMPLE, name="reingest-off")
    uncached.convert(url)
    rewrite(b"nope", status=404, content_type="text/plain")
    assert_error_envelope(*uncached.convert(url)[::2], expected=404)
    rewrite("<html>no</html>", content_type="text/html")
    assert_error_envelope(*uncached.convert(url)[::2], expected=400)


# Spec: same phrase — a bad `charset` alongside `force` is still a 400.
def test_re_ingestion_bad_charset_is_400(cached, source):
    url, _ = source(SIMPLE, name="reingest-charset")
    cached.convert(url)
    status, _, data = cached.convert(url, charset="utf-99", extra="force")
    assert_error_envelope(status, data, 400)


# Spec: a bad `charset` is a 400 even on what would be a cache hit
# (see AMBIGUITIES T66).
def test_bad_charset_on_cache_hit_is_400(cached, source):
    url, _ = source(SIMPLE, name="hit-charset")
    assert cached.convert(url)[0] == 200
    status, _, data = cached.convert(url, charset="not-a-charset")
    assert_error_envelope(status, data, 400)


# Spec: failures are not themselves cached — a source that recovers converts
# (see AMBIGUITIES T69).
def test_failed_conversion_is_not_cached(cached, source):
    url, rewrite = source(b"down", name="recovers", status=503,
                          content_type="text/plain")
    assert cached.convert(url)[0] == 404
    rewrite(SIMPLE)
    status, _, data = cached.convert(url)
    assert status == 200, data
    assert rows_at(cached, data["endpoint"]) == [["ada", 36], ["grace", 45]]


# ==========================================================================
# Spec: "Forced re-ingestion failure keeps prior dataset queryable."
# ==========================================================================
def test_forced_failure_keeps_prior_dataset(cached, source):
    url, rewrite = source(SIMPLE, name="keep-prior")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite(b"boom", status=500, content_type="text/plain")
    assert cached.convert(url, extra="force")[0] == 404
    status, _, payload = cached.get(endpoint)
    assert status == 200, payload
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36], ["grace", 45]]


# Spec: same phrase — a parse failure (not a transport failure) also leaves the
# prior dataset in place.
def test_forced_parse_failure_keeps_prior_dataset(cached, source):
    url, rewrite = source(SIMPLE, name="keep-prior-parse")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite("<html><body>nope</body></html>", content_type="text/html")
    assert cached.convert(url, extra="force")[0] == 400
    assert rows_at(cached, endpoint) == [["ada", 36], ["grace", 45]]


# Spec: same phrase — the surviving dataset is still exportable and filterable.
def test_prior_dataset_fully_usable_after_forced_failure(cached, source):
    url, rewrite = source(SIMPLE, name="keep-prior-usable")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite(b"\x89PNG\r\n\x1a\n", content_type="image/png")
    assert cached.convert(url, extra="force")[0] == 400
    assert rows_at(cached, endpoint + "?name__exact=ada") == [["ada", 36]]
    status, _, body = cached.raw(endpoint + "/export")
    assert status == 200
    assert b"grace" in body


# Spec: same phrase — the cache entry survives too, so a later unforced
# request is still a hit (see AMBIGUITIES T69/T73).
def test_cache_entry_survives_forced_failure(cached, origin, source):
    url, rewrite = source(SIMPLE, name="entry-survives")
    endpoint = cached.convert(url)[2]["endpoint"]
    rewrite(b"boom", status=500, content_type="text/plain")
    assert cached.convert(url, extra="force")[0] == 404
    baseline = hits(origin, url)
    status, _, data = cached.convert(url)
    assert status == 200, data
    assert data["endpoint"] == endpoint
    assert hits(origin, url) == baseline


# Spec: "keeps prior dataset queryable" — the same holds with caching disabled
# (see AMBIGUITIES T70).
def test_failed_re_ingestion_keeps_dataset_when_disabled(uncached, source):
    url, rewrite = source(SIMPLE, name="keep-prior-off")
    endpoint = uncached.convert(url)[2]["endpoint"]
    rewrite(b"boom", status=500, content_type="text/plain")
    assert uncached.convert(url)[0] == 404
    assert rows_at(uncached, endpoint) == [["ada", 36], ["grace", 45]]


# ==========================================================================
# Interaction with `POST /upload` (see AMBIGUITIES T71)
# ==========================================================================
def test_upload_ignores_force(up):
    status, _, data = up.upload(SIMPLE.encode("utf-8"), path="/upload?force")
    assert status == 200, data
    endpoint = data["endpoint"]
    status2, _, data2 = up.upload(SIMPLE.encode("utf-8"),
                                  path="/upload?force&force")
    assert status2 == 200, data2
    assert data2["endpoint"] == endpoint
