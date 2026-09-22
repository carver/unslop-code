"""Spec section: Caching and Cache Controls.

Every test here drives `/convert` against the local origin fixture, which counts how
many HTTP requests each source URL actually received - that count is the only direct
evidence of "without re-downloading".
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

import datagate
from conftest import unused_port

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")

CSV = "name,qty\nwidget,3\n"
CSV2 = "x,y,z\n7,8,9\n"

TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


def make_client(monkeypatch, value=None):
    """A fresh app whose startup environment carries the given CACHE_ENABLED."""
    if value is None:
        monkeypatch.delenv("CACHE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CACHE_ENABLED", value)
    app = datagate.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def convert(client, url, extra=""):
    """GET /convert with a raw query string, so `force` can be sent bare."""
    query = "source=" + urllib.parse.quote(url, safe="") + extra
    return client.get("/convert", query_string=query)


def endpoint_of(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["endpoint"]


def body_of(client, endpoint):
    response = client.get(endpoint)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def assert_error_envelope(response, status):
    assert response.status_code == status, response.get_data(as_text=True)
    payload = response.get_json()
    assert set(payload) == {"ok", "error"}
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# --------------------------------------------------------------- startup ----

def spawn(args, env_extra=None, log_path="/tmp/datagate_cache_server.log"):
    """Start the server detached, with output to a file (never an undrained pipe)."""
    env = dict(os.environ)
    env.pop("CACHE_ENABLED", None)
    env.update(env_extra or {})
    log = open(log_path, "wb")
    return subprocess.Popen([PY, str(ROOT / "datagate.py")] + args,
                            stdout=log, stderr=log, cwd=str(ROOT), env=env)


def wait_for(url, proc, timeout=15.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError("server exited early with code %s" % proc.returncode)
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:  # server is up; it answered
            return e.code, json.loads(e.read().decode())
        except Exception as e:  # not listening yet
            last = e
            time.sleep(0.1)
    raise AssertionError("server never came up: %r" % last)


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


# =============================================================================
# Phrase: "`/convert` caches results by default."
# Context: no CACHE_ENABLED in the environment at all.
# =============================================================================

def test_default_is_caching_second_convert_does_not_refetch(monkeypatch, origin):
    client = make_client(monkeypatch)
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    assert origin.hits(url) - before == 1


def test_default_cache_keeps_the_first_parse(monkeypatch, origin):
    """A cached hit must not pick up content that changed at the origin."""
    client = make_client(monkeypatch)
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, CSV2)
    convert(client, url)
    assert body_of(client, endpoint)["columns"] == ["name", "qty"]


def test_default_caching_is_not_affected_by_later_environment_changes(monkeypatch, origin):
    """CACHE_ENABLED is read once at startup (see AMBIGUITIES T57)."""
    client = make_client(monkeypatch)
    url = origin.add(CSV)
    convert(client, url)
    monkeypatch.setenv("CACHE_ENABLED", "0")
    before = origin.hits(url)
    convert(client, url)
    assert origin.hits(url) == before


def test_failed_conversions_are_not_cached(monkeypatch, origin):
    """Only a dataset id can be cached, so a failure must not stick (T63)."""
    client = make_client(monkeypatch)
    url = origin.add(CSV, path="/cache-negative.csv", status=500)
    assert_error_envelope(convert(client, url), 404)
    origin.update(url, CSV)
    assert body_of(client, endpoint_of(convert(client, url)))["columns"] == ["name", "qty"]


# =============================================================================
# Phrase: "With caching enabled, repeated `/convert` requests for the same source
#          URL can return the cached dataset id without re-downloading."
# Context: the cached answer is the same dataset id, and the origin is untouched.
# =============================================================================

def test_repeated_converts_return_the_same_dataset_id(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    endpoints = {endpoint_of(convert(client, url)) for _ in range(5)}
    assert len(endpoints) == 1


def test_repeated_converts_download_once(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    before = origin.hits(url)
    for _ in range(5):
        convert(client, url)
    assert origin.hits(url) - before == 1


def test_cache_is_keyed_per_source_url(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    first = origin.add(CSV)
    second = origin.add(CSV2)
    a = endpoint_of(convert(client, first))
    before = origin.hits(second)
    b = endpoint_of(convert(client, second))
    assert a != b
    assert origin.hits(second) - before == 1
    assert body_of(client, b)["columns"] == ["x", "y", "z"]


def test_cached_dataset_stays_queryable(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    convert(client, url)
    payload = body_of(client, endpoint)
    assert payload["columns"] == ["name", "qty"]
    assert payload["rows"] == [["widget", 3]]


def test_cache_does_not_leak_between_processes(monkeypatch, origin):
    """The store is per-process: a fresh app re-downloads (T63)."""
    url = origin.add(CSV)
    first = make_client(monkeypatch, "true")
    convert(first, url)
    before = origin.hits(url)
    second = make_client(monkeypatch, "true")
    convert(second, url)
    assert origin.hits(url) - before == 1


# =============================================================================
# Phrase: "Cache responses are identical to fresh parse responses."
# Context: the cached /convert reply must be indistinguishable from the first one.
# =============================================================================

def test_cached_response_body_is_identical(monkeypatch, origin):
    client = make_client(monkeypatch, "on")
    url = origin.add(CSV)
    fresh = convert(client, url)
    cached = convert(client, url)
    assert cached.status_code == fresh.status_code == 200
    assert cached.get_data() == fresh.get_data()
    assert cached.get_json() == {"ok": True, "endpoint": fresh.get_json()["endpoint"]}


def test_cached_response_has_identical_headers(monkeypatch, origin):
    client = make_client(monkeypatch, "on")
    url = origin.add(CSV)
    fresh = convert(client, url)
    cached = convert(client, url)
    for header in ("Content-Type", "Access-Control-Allow-Origin",
                   "Access-Control-Allow-Methods", "Access-Control-Allow-Headers"):
        assert cached.headers.get(header) == fresh.headers.get(header)
    assert cached.headers["Access-Control-Allow-Origin"] == "*"


def test_cached_response_matches_a_fresh_parse_in_another_app(monkeypatch, origin):
    """Same URL, cached here and freshly parsed there: byte-identical replies."""
    url = origin.add(CSV)
    cached_client = make_client(monkeypatch, "1")
    convert(cached_client, url)
    cached = convert(cached_client, url)
    fresh = convert(make_client(monkeypatch, "1"), url)
    assert cached.get_data() == fresh.get_data()
    assert cached.status_code == fresh.status_code


# =============================================================================
# Phrase: "`CACHE_ENABLED` accepts strict case-insensitive values - true: `1`,
#          `true`, `yes`, `on`"
# Context: each spelling, in any case, turns caching on.
# =============================================================================

@pytest.mark.parametrize("value", TRUE_VALUES)
def test_true_values_enable_caching(monkeypatch, origin, value):
    client = make_client(monkeypatch, value)
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    assert origin.hits(url) - before == 1


@pytest.mark.parametrize("value", ["TRUE", "True", "tRuE", "YES", "Yes", "ON", "On", "oN",
                                  " true", "on ", "  YES  "])
def test_true_values_are_case_insensitive(monkeypatch, origin, value):
    """Case is forgiven, and so is surrounding whitespace (T58, updated)."""
    client = make_client(monkeypatch, value)
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    assert origin.hits(url) - before == 1


# =============================================================================
# Phrase: "false: `0`, `false`, `no`, `off`"
# Context: each spelling, in any case, turns caching off.
# =============================================================================

@pytest.mark.parametrize("value", FALSE_VALUES)
def test_false_values_disable_caching(monkeypatch, origin, value):
    client = make_client(monkeypatch, value)
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    assert origin.hits(url) - before == 2


@pytest.mark.parametrize("value", ["FALSE", "False", "fAlSe", "NO", "No", "OFF", "Off"])
def test_false_values_are_case_insensitive(monkeypatch, origin, value):
    client = make_client(monkeypatch, value)
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url)
    assert origin.hits(url) - before == 2


# =============================================================================
# Phrase: "Invalid values fail startup."
# Context: anything outside the eight literals must stop the process coming up.
#          An empty or whitespace-only value is invalid too; surrounding padding
#          is *not*, now that the configuration spec says booleans are trimmed
#          (AMBIGUITIES T58, updated).
# =============================================================================

@pytest.mark.parametrize("value", [
    "maybe", "2", "-1", "tru", "t", "f", "y", "n", "enabled", "disabled",
    "true false", "", "   ", "null", "None", "1.0", "01",
])
def test_invalid_values_fail_startup(value):
    port = unused_port()
    proc = spawn(["start", "--port", str(port)], {"CACHE_ENABLED": value},
                 log_path="/tmp/datagate_cache_bad.log")
    try:
        try:
            code = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            raise AssertionError("server kept running with CACHE_ENABLED=%r" % value)
        assert code != 0
    finally:
        stop(proc)


def test_startup_failure_names_the_variable():
    port = unused_port()
    log_path = "/tmp/datagate_cache_msg.log"
    proc = spawn(["start", "--port", str(port)], {"CACHE_ENABLED": "maybe"},
                 log_path=log_path)
    try:
        proc.wait(timeout=15)
    finally:
        stop(proc)
    assert "CACHE_ENABLED" in Path(log_path).read_text(errors="replace")


def test_invalid_value_never_binds_the_port():
    port = unused_port()
    proc = spawn(["start", "--port", str(port)], {"CACHE_ENABLED": "sometimes"},
                 log_path="/tmp/datagate_cache_bad.log")
    try:
        proc.wait(timeout=15)
        with pytest.raises(Exception):
            urllib.request.urlopen("http://127.0.0.1:%d/datasets/nope" % port, timeout=2)
    finally:
        stop(proc)


@pytest.mark.parametrize("value", ["on", "off", "TRUE", "0"])
def test_valid_values_start_the_server(value):
    port = unused_port()
    proc = spawn(["start", "--port", str(port)], {"CACHE_ENABLED": value})
    try:
        status, payload = wait_for("http://127.0.0.1:%d/datasets/nope" % port, proc)
        assert status == 404
        assert payload["ok"] is False
    finally:
        stop(proc)


def test_unset_variable_starts_the_server():
    port = unused_port()
    proc = spawn(["start", "--port", str(port)])
    try:
        status, _ = wait_for("http://127.0.0.1:%d/datasets/nope" % port, proc)
        assert status == 404
    finally:
        stop(proc)


# =============================================================================
# Phrase: "When disabled, every `/convert` request re-downloads/parses and
#          replaces stored data."
# Context: CACHE_ENABLED is one of the false spellings.
# =============================================================================

def test_disabled_downloads_on_every_request(monkeypatch, origin):
    client = make_client(monkeypatch, "off")
    url = origin.add(CSV)
    before = origin.hits(url)
    for _ in range(3):
        convert(client, url)
    assert origin.hits(url) - before == 3


def test_disabled_replaces_stored_data(monkeypatch, origin):
    client = make_client(monkeypatch, "0")
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, CSV2)
    convert(client, url)
    payload = body_of(client, endpoint)
    assert payload["columns"] == ["x", "y", "z"]
    assert payload["rows"] == [[7, 8, 9]]


def test_disabled_keeps_the_same_dataset_id(monkeypatch, origin):
    client = make_client(monkeypatch, "no")
    url = origin.add(CSV)
    first = endpoint_of(convert(client, url))
    origin.update(url, CSV2)
    assert endpoint_of(convert(client, url)) == first


# =============================================================================
# Phrase: "`force` is a presence flag. If present once, it forces re-ingestion
#          and replaces the cached dataset."
# Context: caching enabled; `force` sent bare, with no `=`.
# =============================================================================

def test_force_re_downloads(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    before = origin.hits(url)
    convert(client, url)
    convert(client, url, "&force")
    assert origin.hits(url) - before == 2


def test_force_replaces_the_cached_dataset(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, CSV2)
    assert endpoint_of(convert(client, url, "&force")) == endpoint
    payload = body_of(client, endpoint)
    assert payload["columns"] == ["x", "y", "z"]
    assert payload["rows"] == [[7, 8, 9]]


def test_force_response_is_a_normal_convert_response(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    plain = convert(client, url)
    forced = convert(client, url, "&force")
    assert forced.status_code == 200
    assert forced.get_data() == plain.get_data()


def test_force_on_a_never_converted_url_just_converts(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    before = origin.hits(url)
    response = convert(client, url, "&force")
    assert response.status_code == 200
    assert origin.hits(url) - before == 1
    assert body_of(client, response.get_json()["endpoint"])["columns"] == ["name", "qty"]


def test_after_force_the_new_dataset_is_what_gets_cached(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, CSV2)
    convert(client, url, "&force")
    before = origin.hits(url)
    convert(client, url)
    assert origin.hits(url) == before
    assert body_of(client, endpoint)["columns"] == ["x", "y", "z"]


def test_force_does_not_disturb_other_cached_datasets(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    a = origin.add(CSV)
    b = origin.add(CSV2)
    endpoint_b = endpoint_of(convert(client, b))
    convert(client, a)
    before = origin.hits(b)
    convert(client, a, "&force")
    assert origin.hits(b) == before
    assert body_of(client, endpoint_b)["columns"] == ["x", "y", "z"]


# =============================================================================
# Phrase: "Any `force` value is `HTTP 400`."
# Context: a value - even one that looks like a boolean - is a malformed request.
# =============================================================================

@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "0", "false", "no",
                                   "off", "x", "force", "%20", "TRUE"])
def test_force_with_a_value_is_400(monkeypatch, origin, value):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    assert_error_envelope(convert(client, url, "&force=" + value), 400)


def test_force_value_does_not_re_ingest(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    convert(client, url)
    before = origin.hits(url)
    assert convert(client, url, "&force=1").status_code == 400
    assert origin.hits(url) == before


def test_force_value_on_a_fresh_url_does_not_ingest(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    before = origin.hits(url)
    response = convert(client, url, "&force=true")
    assert_error_envelope(response, 400)
    assert origin.hits(url) == before
    assert client.get("/datasets/" + datagate.dataset_id(url)).status_code == 404


# Chosen reading (AMBIGUITIES T60): `?force=` supplies no value, so it is presence.
def test_force_with_an_empty_value_is_presence(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    convert(client, url)
    before = origin.hits(url)
    response = convert(client, url, "&force=")
    assert response.status_code == 200
    assert origin.hits(url) - before == 1


# Chosen reading (AMBIGUITIES T61): "present once" - a repeat is a 400.
def test_repeated_force_is_400(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV)
    convert(client, url)
    before = origin.hits(url)
    assert_error_envelope(convert(client, url, "&force&force"), 400)
    assert origin.hits(url) == before


def test_invalid_url_with_force_is_still_400(monkeypatch):
    client = make_client(monkeypatch, "true")
    response = client.get("/convert", query_string="source=not%20a%20url&force")
    assert_error_envelope(response, 400)


# =============================================================================
# Phrase: "If caching is disabled, `force` has no additional effect."
# Context: every request already re-ingests, so forcing changes nothing.
# =============================================================================

def test_force_with_caching_disabled_matches_a_plain_request(monkeypatch, origin):
    client = make_client(monkeypatch, "off")
    url = origin.add(CSV)
    plain = convert(client, url)
    before = origin.hits(url)
    forced = convert(client, url, "&force")
    assert forced.status_code == 200
    assert forced.get_data() == plain.get_data()
    assert origin.hits(url) - before == 1


def test_force_with_caching_disabled_still_replaces_stored_data(monkeypatch, origin):
    client = make_client(monkeypatch, "false")
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, CSV2)
    convert(client, url, "&force")
    assert body_of(client, endpoint)["columns"] == ["x", "y", "z"]


# Chosen reading (AMBIGUITIES T62): a `force` *value* is malformed in either mode.
@pytest.mark.parametrize("value", ["1", "true", "0", "x"])
def test_force_value_is_400_even_when_caching_disabled(monkeypatch, origin, value):
    client = make_client(monkeypatch, "0")
    url = origin.add(CSV)
    assert_error_envelope(convert(client, url, "&force=" + value), 400)


# =============================================================================
# Phrase: "Re-ingestion failures keep existing error codes and envelope."
# Context: a second /convert that fails answers exactly as a first one would.
# =============================================================================

def test_re_ingestion_unreachable_is_404(monkeypatch, origin):
    client = make_client(monkeypatch, "off")
    url = origin.add(CSV, path="/reingest-gone.csv")
    assert convert(client, url).status_code == 200
    origin.remove(url)
    assert_error_envelope(convert(client, url), 404)


def test_re_ingestion_remote_error_is_404(monkeypatch, origin):
    client = make_client(monkeypatch, "off")
    url = origin.add(CSV, path="/reingest-500.csv")
    assert convert(client, url).status_code == 200
    origin.update(url, b"boom", status=503)
    assert_error_envelope(convert(client, url), 404)


def test_re_ingestion_non_tabular_is_400(monkeypatch, origin):
    client = make_client(monkeypatch, "off")
    url = origin.add(CSV, path="/reingest-junk.csv")
    assert convert(client, url).status_code == 200
    origin.update(url, b"\x00\x01\x02binary garbage")
    assert_error_envelope(convert(client, url), 400)


def test_re_ingestion_failure_matches_a_first_time_failure(monkeypatch, origin):
    """Same URL, same broken content: the repeat and the first attempt agree."""
    client = make_client(monkeypatch, "off")
    url = origin.add(CSV, path="/reingest-compare.csv")
    convert(client, url)
    origin.update(url, b"", content_type="text/csv")
    repeat = convert(client, url)
    first_time = convert(make_client(monkeypatch, "off"),
                         origin.add(b"", path="/first-time-empty.csv"))
    assert repeat.status_code == first_time.status_code
    assert repeat.get_json()["ok"] is first_time.get_json()["ok"] is False


# =============================================================================
# Phrase: "Forced re-ingestion failure keeps prior dataset queryable."
# Context: the failed refresh must not evict what was already stored.
# =============================================================================

def test_forced_failure_keeps_prior_dataset(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV, path="/forced-gone.csv")
    endpoint = endpoint_of(convert(client, url))
    origin.remove(url)
    assert_error_envelope(convert(client, url, "&force"), 404)
    payload = body_of(client, endpoint)
    assert payload["columns"] == ["name", "qty"]
    assert payload["rows"] == [["widget", 3]]


def test_forced_parse_failure_keeps_prior_dataset(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV, path="/forced-junk.csv")
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, b"\x00\x01\x02not a table")
    assert_error_envelope(convert(client, url, "&force"), 400)
    assert body_of(client, endpoint)["rows"] == [["widget", 3]]


def test_forced_failure_leaves_the_cache_usable(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV, path="/forced-then-cached.csv")
    endpoint = endpoint_of(convert(client, url))
    origin.remove(url)
    assert convert(client, url, "&force").status_code == 404
    before = origin.hits(url)
    assert endpoint_of(convert(client, url)) == endpoint
    assert origin.hits(url) == before


def test_forced_failure_then_success_replaces_the_dataset(monkeypatch, origin):
    client = make_client(monkeypatch, "true")
    url = origin.add(CSV, path="/forced-recover.csv")
    endpoint = endpoint_of(convert(client, url))
    origin.remove(url)
    assert convert(client, url, "&force").status_code == 404
    origin.add(CSV2, path="/forced-recover.csv")
    assert convert(client, url, "&force").status_code == 200
    assert body_of(client, endpoint)["columns"] == ["x", "y", "z"]


def test_failed_re_ingestion_keeps_prior_dataset_when_caching_disabled(monkeypatch, origin):
    client = make_client(monkeypatch, "0")
    url = origin.add(CSV, path="/disabled-gone.csv")
    endpoint = endpoint_of(convert(client, url))
    origin.remove(url)
    assert convert(client, url).status_code == 404
    assert body_of(client, endpoint)["rows"] == [["widget", 3]]


# =============================================================================
# Phrase: "`/convert` caches results by default." (scope)
# Context: the section speaks only of /convert - /upload holds its own bytes
#          and has nothing to re-download (AMBIGUITIES T64).
# =============================================================================

def test_upload_still_ingests_with_caching_enabled(monkeypatch, client, upload):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    status, payload = upload(body=CSV.encode())
    assert status == 200
    assert payload["endpoint"].startswith("/datasets/")


def test_upload_ignores_force(monkeypatch, client):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    app = datagate.create_app()
    app.config.update(TESTING=True)
    import io as _io

    response = app.test_client().post(
        "/upload",
        data={"file": (_io.BytesIO(CSV.encode()), "data.csv")},
        content_type="multipart/form-data",
        query_string="force=1",
    )
    assert response.status_code == 200
