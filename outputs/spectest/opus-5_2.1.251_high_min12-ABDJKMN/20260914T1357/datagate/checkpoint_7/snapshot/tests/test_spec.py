"""Spec tests for datagate. Each section quotes the spec phrase it covers."""
import json
import os
import socket
import subprocess
import sys
import time

import pytest

from conftest import (ROOT, Client, _spawn, free_port, port_is_free,
                      wait_for_port)

SIMPLE = "name,age\nada,36\ngrace,45\n"


# ==========================================================================
# Spec: "`datagate` starts with: `python datagate.py start --port <port>
#        --address <address>`"
# ==========================================================================
def test_starts_with_start_subcommand_and_flags():
    port = free_port()
    proc = _spawn(port, "127.0.0.1", tag="cli")
    try:
        assert wait_for_port("127.0.0.1", port), "server did not bind given port"
        c = Client("http://127.0.0.1:%d" % port)
        status, _, data = c.get("/datasets/definitely-unknown")
        assert status == 404
        assert data["ok"] is False
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# Spec: "`--port` default `8001`." and "`--address` default `127.0.0.1`."
def test_default_port_and_address():
    if not port_is_free("127.0.0.1", 8001):
        pytest.skip("port 8001 already in use on this machine")
    proc = _spawn(0, args=["start"], tag="defaults")
    try:
        assert wait_for_port("127.0.0.1", 8001), "no listener on default 127.0.0.1:8001"
        c = Client("http://127.0.0.1:8001")
        status, _, data = c.get("/datasets/unknown-id")
        assert status == 404 and data["ok"] is False
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# Spec: "--port <port>" honoured — a non-default port is actually used.
def test_custom_port_is_honoured(server):
    status, _, data = server.get("/datasets/nope")
    assert status == 404
    assert data["ok"] is False


# ==========================================================================
# Ingestion: `GET /convert`
# ==========================================================================

# Spec: "| `source` | yes | URL of the remote CSV file |" and
#       Success (`HTTP 200`): {"ok": true, "endpoint": "/datasets/<id>"}
def test_convert_success_envelope(server, csv_url):
    url = csv_url(SIMPLE)
    status, _, data = server.convert(url)
    assert status == 200
    assert data["ok"] is True
    assert data["endpoint"].startswith("/datasets/")
    assert len(data["endpoint"]) > len("/datasets/")
    assert set(data.keys()) >= {"ok", "endpoint"}


# Spec: the returned endpoint must be usable to query the dataset.
def test_convert_endpoint_is_queryable(server, csv_url):
    url = csv_url(SIMPLE)
    endpoint = server.convert(url)[2]["endpoint"]
    status, _, data = server.get(endpoint)
    assert status == 200
    assert data["ok"] is True
    assert data["columns"] == ["name", "age"]


# Spec: "`/convert` returns the same endpoint for the same `source` URL string."
def test_same_source_same_endpoint(server, csv_url):
    url = csv_url(SIMPLE)
    a = server.convert(url)[2]["endpoint"]
    b = server.convert(url)[2]["endpoint"]
    assert a == b


# Spec: same phrase — different source URL strings get different endpoints.
def test_different_sources_different_endpoints(server, csv_url):
    u1 = csv_url(SIMPLE, name="one")
    u2 = csv_url(SIMPLE, name="two")
    e1 = server.convert(u1)[2]["endpoint"]
    e2 = server.convert(u2)[2]["endpoint"]
    assert e1 != e2


# Spec: "| Missing `source` | 400 |"
def test_missing_source_is_400(server):
    status, _, data = server.convert()
    assert status == 400
    assert data["ok"] is False
    assert isinstance(data["error"], str) and data["error"]


# Spec: "| Missing `source` | 400 |" (present but empty counts as missing)
def test_empty_source_is_400(server):
    status, _, data = server.convert("")
    assert status == 400
    assert data["ok"] is False


# Spec: "| Invalid URL | 400 |"
@pytest.mark.parametrize("bad", [
    "not a url",
    "://missing-scheme",
    "http://",
    "ftp://example.com/data.csv",
    "file:///etc/passwd",
    "javascript:alert(1)",
])
def test_invalid_url_is_400(server, bad):
    status, _, data = server.convert(bad)
    assert status == 400, (bad, data)
    assert data["ok"] is False


# Spec: "| Unsupported or malformed `charset` | 400 |"
@pytest.mark.parametrize("bad", ["utf-99", "not-a-charset", "!!!", "  "])
def test_unsupported_charset_is_400(server, csv_url, bad):
    url = csv_url(SIMPLE)
    status, _, data = server.convert(url, charset=bad)
    assert status == 400, (bad, data)
    assert data["ok"] is False


# Spec: "| Unsupported or malformed `charset` | 400 |" — a valid codec that
# cannot decode these bytes is also a charset problem.
def test_charset_that_cannot_decode_is_400(server, csv_url):
    body = "name,city\nada,café\n".encode("utf-16")
    url = csv_url(body)
    status, _, data = server.convert(url, charset="ascii")
    assert status == 400
    assert data["ok"] is False


# Spec: "| Source unreachable or remote HTTP error | 404 |"
def test_unreachable_source_is_404(server):
    dead = "http://127.0.0.1:%d/nothing.csv" % free_port()
    status, _, data = server.convert(dead)
    assert status == 404
    assert data["ok"] is False


# Spec: "| Source unreachable or remote HTTP error | 404 |"
@pytest.mark.parametrize("code", [404, 403, 500, 503])
def test_remote_http_error_is_404(server, csv_url, code):
    url = csv_url(SIMPLE, status=code)
    status, _, data = server.convert(url)
    assert status == 404, (code, data)
    assert data["ok"] is False


# Spec: "| Source unreachable or remote HTTP error | 404 |" (bad host)
def test_unresolvable_host_is_404(server):
    status, _, data = server.convert("http://nonexistent.invalid/data.csv")
    assert status == 404
    assert data["ok"] is False


# Spec: "| Non-tabular content | 400 |"
@pytest.mark.parametrize("body,ctype", [
    ("<html><body><h1>hello</h1></body></html>", "text/html"),
    ('{"a": 1, "b": [2, 3]}', "application/json"),
    ("just one line of prose with no delimiters at all", "text/plain"),
    ("", "text/csv"),
    ("   \n\n  \n", "text/csv"),
])
def test_non_tabular_content_is_400(server, csv_url, body, ctype):
    url = csv_url(body, content_type=ctype)
    status, _, data = server.convert(url)
    assert status == 400, (body[:30], data)
    assert data["ok"] is False


# Spec: "| Non-tabular content | 400 |" + "A valid file requires at least one
# header row and one data row."
def test_header_only_is_400(server, csv_url):
    url = csv_url("name,age\n")
    status, _, data = server.convert(url)
    assert status == 400
    assert data["ok"] is False


# Spec: "| Non-tabular content | 400 |" (binary payload)
def test_binary_content_is_400(server, csv_url):
    url = csv_url(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01\x02\x03\xff\xfe",
                  content_type="image/png")
    status, _, data = server.convert(url)
    assert status == 400
    assert data["ok"] is False


# ==========================================================================
# Dataset Query: `GET /datasets/<id>`
# ==========================================================================

# Spec: Success shape {"ok", "columns", "rows", "query_ms"}
def test_dataset_success_shape(dataset):
    payload = dataset(SIMPLE)
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36], ["grace", 45]]
    assert isinstance(payload["query_ms"], (int, float))
    assert not isinstance(payload["query_ms"], bool)


# Spec: "The endpoint returns stored rows and columns, in source order."
def test_source_order_preserved(dataset):
    body = "z,a,m\n3,1,2\n6,4,5\n9,7,8\n"
    payload = dataset(body)
    assert payload["columns"] == ["z", "a", "m"]
    assert payload["rows"] == [[3, 1, 2], [6, 4, 5], [9, 7, 8]]


# Spec: "The endpoint returns stored rows ... in source order." — repeated
# queries return identical payloads (minus query_ms).
def test_repeated_queries_are_stable(server, csv_url):
    url = csv_url("a,b\n1,2\n3,4\n")
    endpoint = server.convert(url)[2]["endpoint"]
    first = server.get(endpoint)[2]
    second = server.get(endpoint)[2]
    assert first["columns"] == second["columns"]
    assert first["rows"] == second["rows"]


# Spec: "`rows` returns at most 100 items (or all rows if fewer)."
def test_rows_capped_at_100(dataset):
    body = "n,sq\n" + "".join("%d,%d\n" % (i, i * i) for i in range(1, 251))
    payload = dataset(body)
    assert len(payload["rows"]) == 100
    assert payload["rows"][0] == [1, 1]
    assert payload["rows"][-1] == [100, 10000]


# Spec: "(or all rows if fewer)"
def test_all_rows_when_fewer_than_100(dataset):
    body = "n,v\n" + "".join("%d,x\n" % i for i in range(7))
    payload = dataset(body)
    assert len(payload["rows"]) == 7


# Spec: "(or all rows if fewer)" — exactly 100 rows are all returned.
def test_exactly_100_rows(dataset):
    body = "n,v\n" + "".join("%d,v%d\n" % (i, i) for i in range(100))
    payload = dataset(body)
    assert len(payload["rows"]) == 100


# Spec: "Type handling: - Strings remain text."
def test_strings_remain_text(dataset):
    body = "word,note\nada,hello world\ngrace,COBOL\n"
    payload = dataset(body)
    assert payload["rows"] == [["ada", "hello world"], ["grace", "COBOL"]]
    for row in payload["rows"]:
        for value in row:
            assert isinstance(value, str)


# Spec: "- Integers/decimals are JSON numbers."
def test_integers_and_decimals_are_numbers(dataset):
    body = "i,d,neg,negd\n42,3.5,-7,-0.25\n0,12.50,-100,-9.125\n"
    payload = dataset(body)
    assert payload["rows"][0] == [42, 3.5, -7, -0.25]
    assert payload["rows"][1] == [0, 12.5, -100, -9.125]
    assert isinstance(payload["rows"][0][0], int)
    assert isinstance(payload["rows"][0][1], float)


# Spec: "- Integers/decimals are JSON numbers." — verified on the JSON wire
# format, not just after parsing.
def test_numbers_are_unquoted_in_json(server, csv_url):
    url = csv_url("a,b\n1,2.5\n")
    endpoint = server.convert(url)[2]["endpoint"]
    raw = server.raw(endpoint)[2].decode("utf-8")
    assert '"1"' not in raw and '"2.5"' not in raw
    assert "1" in raw and "2.5" in raw


# Spec: "- Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
def test_time_like_values_remain_text(dataset):
    body = "start,mid,end\n08:30,9:15,12:00\n23:59,00:00,7:05\n"
    payload = dataset(body)
    assert payload["rows"] == [["08:30", "9:15", "12:00"],
                               ["23:59", "00:00", "7:05"]]


# Spec: "- Time-like values ... remain text." (with seconds / mixed columns)
def test_time_like_with_seconds_and_mixed_columns(dataset):
    body = "label,at,count\nopen,08:30:15,3\nclose,17:00,12\n"
    payload = dataset(body)
    assert payload["rows"] == [["open", "08:30:15", 3], ["close", "17:00", 12]]


# Spec: "If `<id>` is unknown, return `HTTP 404`."
@pytest.mark.parametrize("bad_id", ["unknown", "0" * 64, "abc123", "../etc"])
def test_unknown_dataset_id_is_404(server, bad_id):
    status, _, data = server.get("/datasets/" + bad_id.replace("/", "%2F"))
    assert status == 404, bad_id
    assert data is not None and data["ok"] is False


# ==========================================================================
# Response Envelope
# ==========================================================================

# Spec: "Success responses include `"ok": true`."
def test_success_responses_have_ok_true(server, csv_url):
    url = csv_url(SIMPLE)
    conv = server.convert(url)[2]
    assert conv["ok"] is True
    ds = server.get(conv["endpoint"])[2]
    assert ds["ok"] is True


# Spec: 'Error responses use: {"ok": false, "error": "<human-readable message>"}'
def test_error_envelope_shape(server):
    status, _, data = server.convert()
    assert status == 400
    assert data["ok"] is False
    assert isinstance(data.get("error"), str)
    assert data["error"].strip() != ""


# Spec: "All errors are JSON; unknown routes return `HTTP 404`."
@pytest.mark.parametrize("path", ["/", "/nope", "/datasets", "/convert/extra",
                                  "/DATASETS/abc", "/favicon.ico"])
def test_unknown_routes_are_json_404(server, path):
    status, headers, body = server.raw(path)
    assert status == 404, path
    assert "application/json" in headers.get("Content-Type", "")
    data = json.loads(body.decode("utf-8"))
    assert data["ok"] is False
    assert isinstance(data["error"], str)


# Spec: "All errors are JSON" — including non-GET methods on known routes.
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_other_methods_return_json_errors(server, method):
    status, headers, body = server.raw("/convert", method=method)
    assert status >= 400
    assert "application/json" in headers.get("Content-Type", "")
    assert json.loads(body.decode("utf-8"))["ok"] is False


# Spec: "All errors are JSON" — every error path in the spec's tables.
def test_all_spec_errors_are_json(server, csv_url):
    cases = [
        "/convert",
        "/convert?source=not-a-url",
        "/convert?source=" + csv_url(SIMPLE) + "&charset=utf-99",
        "/datasets/missing",
    ]
    for path in cases:
        status, headers, body = server.raw(path)
        assert status >= 400, path
        assert "application/json" in headers.get("Content-Type", ""), path
        assert json.loads(body.decode("utf-8"))["ok"] is False


# ==========================================================================
# Cross-Origin Access: "Include CORS headers for browser access."
# ==========================================================================
def test_cors_header_on_success(server, csv_url):
    url = csv_url(SIMPLE)
    status, headers, _ = server.raw("/convert?source=" + url)
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_cors_header_on_dataset_and_errors(server, csv_url):
    url = csv_url(SIMPLE)
    endpoint = server.convert(url)[2]["endpoint"]
    _, h1, _ = server.raw(endpoint)
    assert h1.get("Access-Control-Allow-Origin") == "*"
    _, h2, _ = server.raw("/datasets/unknown")
    assert h2.get("Access-Control-Allow-Origin") == "*"


def test_cors_preflight(server):
    status, headers, _ = server.raw(
        "/convert", method="OPTIONS",
        headers={"Origin": "http://example.com",
                 "Access-Control-Request-Method": "GET"})
    assert status < 400
    assert headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com")


# ==========================================================================
# CSV Parsing
# ==========================================================================

# Spec: "If `/convert` receives `charset`, use it to decode bytes."
def test_explicit_charset_is_used(server, csv_url):
    body = "name,city\nrene,café crowd\n".encode("cp1252")
    url = csv_url(body)
    endpoint = server.convert(url, charset="cp1252")[2]["endpoint"]
    payload = server.get(endpoint)[2]
    assert payload["rows"] == [["rene", "café crowd"]]


# Spec: "If `/convert` receives `charset`, use it to decode bytes." — charset
# names are matched case-insensitively / with common aliases.
@pytest.mark.parametrize("name", ["UTF-8", "utf8", "utf_8"])
def test_charset_aliases_accepted(server, csv_url, name):
    url = csv_url("a,b\ncañon,2\n".encode("utf-8"))
    status, _, data = server.convert(url, charset=name)
    assert status == 200, (name, data)
    payload = server.get(data["endpoint"])[2]
    assert payload["rows"] == [["cañon", 2]]


# Spec: "Otherwise detect encoding." (latin-1 family, no charset given)
def test_encoding_detected_when_charset_omitted_latin1(server, csv_url):
    text = ("name,city\n" + "".join(
        "n%d,Zürich café naïve\n" % i for i in range(40)))
    url = csv_url(text.encode("cp1252"), content_type="text/csv")
    status, _, data = server.convert(url)
    assert status == 200, data
    payload = server.get(data["endpoint"])[2]
    assert all(len(r) == 2 for r in payload["rows"])
    assert "�" not in json.dumps(payload)


# Spec: "Otherwise detect encoding." (plain utf-8)
def test_encoding_detected_utf8(dataset):
    payload = dataset("name,note\nada,élève\nあ,中文\n".encode("utf-8"))
    assert payload["rows"] == [["ada", "élève"], ["あ", "中文"]]


# Spec: "Otherwise detect encoding." (utf-8 with BOM: BOM must not leak into
# the first column name)
def test_utf8_bom_is_stripped(dataset):
    payload = dataset("﻿name,age\nada,36\n".encode("utf-8-sig"))
    assert payload["columns"] == ["name", "age"]


# Spec: "Delimiter must be inferred from input; minimum supported delimiters
# are `,`, `;`, and `\t`." (comma)
def test_delimiter_comma(dataset):
    payload = dataset("a,b,c\n1,2,3\n")
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, 3]]


# Spec: same phrase (semicolon)
def test_delimiter_semicolon(dataset):
    payload = dataset("a;b;c\n1;2;3\n4;5;6\n")
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


# Spec: same phrase (tab)
def test_delimiter_tab(dataset):
    payload = dataset("a\tb\tc\n1\t2\t3\n4\t5\t6\n")
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6]]


# Spec: same phrase — semicolon file whose values contain commas must not be
# split on the comma.
def test_semicolon_with_commas_in_values(dataset):
    payload = dataset("city;note\nParis;a, b, c\nLyon;x, y\n")
    assert payload["columns"] == ["city", "note"]
    assert payload["rows"] == [["Paris", "a, b, c"], ["Lyon", "x, y"]]


# Spec: same phrase — tab file whose values contain commas and semicolons.
def test_tab_with_other_punctuation(dataset):
    payload = dataset("k\tv\na\t1;2,3\nb\t4;5,6\n")
    assert payload["rows"] == [["a", "1;2,3"], ["b", "4;5,6"]]


# Spec: CSV quoting is standard RFC4180 behaviour.
def test_quoted_fields_with_embedded_delimiter(dataset):
    payload = dataset('name,note\n"Doe, Jane","says ""hi"""\n')
    assert payload["rows"] == [["Doe, Jane", 'says "hi"']]


# Spec: "A valid file requires at least one header row and one data row."
def test_one_header_and_one_data_row_is_valid(server, csv_url):
    url = csv_url("a,b\n1,2\n")
    status, _, data = server.convert(url)
    assert status == 200, data
    payload = server.get(data["endpoint"])[2]
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


# Spec: CRLF line endings are ordinary CSV.
def test_crlf_line_endings(dataset):
    payload = dataset("a,b\r\n1,2\r\n3,4\r\n")
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2], [3, 4]]


# ==========================================================================
# Determinism
# ==========================================================================

# Spec: "Same `source` URL always maps to the same dataset id." (stable across
# server restarts, since the id derives from the URL string)
def test_dataset_id_stable_across_restarts(origin, csv_url):
    url = csv_url(SIMPLE, name="stable")
    ids = []
    for i in range(2):
        port = free_port()
        proc = _spawn(port, tag="restart")
        try:
            assert wait_for_port("127.0.0.1", port)
            c = Client("http://127.0.0.1:%d" % port)
            ids.append(c.convert(url)[2]["endpoint"])
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    assert ids[0] == ids[1]


# Spec: "`columns` and each row follow source column order."
def test_column_order_follows_source(dataset):
    payload = dataset("c,b,a\n3,2,1\n")
    assert payload["columns"] == ["c", "b", "a"]
    assert payload["rows"][0] == [3, 2, 1]


# Spec: "`query_ms` is present and non-negative."
def test_query_ms_present_and_non_negative(dataset):
    payload = dataset(SIMPLE)
    assert "query_ms" in payload
    assert isinstance(payload["query_ms"], (int, float))
    assert payload["query_ms"] >= 0


# Spec: "Type inference is deterministic." — same input, same types every time.
def test_type_inference_deterministic(server, csv_url):
    body = "s,i,f,t\nabc,1,2.5,08:30\n"
    url = csv_url(body)
    endpoint = server.convert(url)[2]["endpoint"]
    seen = {json.dumps(server.get(endpoint)[2]["rows"]) for _ in range(3)}
    assert len(seen) == 1
    assert json.loads(seen.pop()) == [["abc", 1, 2.5, "08:30"]]


# Spec: "Default row limit is 100."
def test_default_row_limit_is_100(dataset):
    body = "n,v\n" + "".join("%d,a\n" % i for i in range(120))
    payload = dataset(body)
    assert len(payload["rows"]) == 100


# Spec: "No dependence on clock/locale/timezone beyond `query_ms`."
def test_no_clock_or_locale_dependence(server, csv_url):
    body = "when,amount\n08:30,1.5\n12:00,2.25\n"
    url = csv_url(body)
    endpoint = server.convert(url)[2]["endpoint"]
    first = server.get(endpoint)[2]
    time.sleep(0.2)
    second = server.get(endpoint)[2]
    first.pop("query_ms"), second.pop("query_ms")
    assert first == second


# Spec: "No dependence on ... locale" — decimals use '.' and results do not
# change when the server runs under a different locale/timezone.
def test_decimal_point_is_locale_independent(csv_url):
    url = csv_url("amount,when\n1234.5,08:30\n")
    port = free_port()
    env = dict(os.environ, LC_ALL="C", LANG="C", TZ="Asia/Kolkata")
    log = open(os.path.join(ROOT, "tests", "_locale.log"), "ab")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "datagate.py"), "start",
         "--port", str(port)],
        cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=env)
    try:
        assert wait_for_port("127.0.0.1", port)
        c = Client("http://127.0.0.1:%d" % port)
        endpoint = c.convert(url)[2]["endpoint"]
        payload = c.get(endpoint)[2]
        assert payload["rows"] == [[1234.5, "08:30"]]
        raw = c.raw(endpoint)[2].decode("utf-8")
        assert "1234.5" in raw and "1,234" not in raw
    finally:
        proc.terminate()
        proc.wait(timeout=10)
