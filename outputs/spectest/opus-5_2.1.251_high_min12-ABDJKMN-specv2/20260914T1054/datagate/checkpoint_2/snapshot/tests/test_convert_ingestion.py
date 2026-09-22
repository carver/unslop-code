"""Spec section: Ingestion: `GET /convert`."""
import pytest

from conftest import unused_port

CSV = "name,qty\nwidget,3\n"


# Phrase: "Query parameters | `source` | yes | URL of the remote CSV file"
# Context: a well-formed CSV at a reachable URL is the happy path.
def test_convert_accepts_source_url(convert, origin):
    status, payload = convert(source=origin.add(CSV))
    assert status == 200
    assert payload["ok"] is True


# Phrase: 'Success (`HTTP 200`): {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: exact success envelope shape for /convert.
def test_convert_success_envelope(convert, origin):
    status, payload = convert(source=origin.add(CSV))
    assert status == 200
    assert payload["ok"] is True
    assert set(payload) >= {"ok", "endpoint"}
    assert isinstance(payload["endpoint"], str)


# Phrase: '"endpoint": "/datasets/<id>"'
# Context: the endpoint is a path under /datasets/ with a non-empty id.
def test_endpoint_is_datasets_path(convert, origin):
    _, payload = convert(source=origin.add(CSV))
    endpoint = payload["endpoint"]
    assert endpoint.startswith("/datasets/")
    assert len(endpoint[len("/datasets/"):]) > 0
    assert "/" not in endpoint[len("/datasets/"):]


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
# Context: repeated ingestion of one URL is idempotent in its endpoint.
def test_same_source_same_endpoint(convert, origin):
    url = origin.add(CSV)
    _, first = convert(source=url)
    _, second = convert(source=url)
    assert first["endpoint"] == second["endpoint"]


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
# Context: different URL strings are different datasets.
def test_different_sources_get_different_endpoints(convert, origin):
    _, a = convert(source=origin.add(CSV, path="/a.csv"))
    _, b = convert(source=origin.add("x,y\n1,2\n", path="/b.csv"))
    assert a["endpoint"] != b["endpoint"]


# Phrase: "The endpoint returned by /convert" is usable
# Context: /convert's endpoint must resolve to a live dataset.
def test_returned_endpoint_is_fetchable(client, convert, origin):
    _, payload = convert(source=origin.add(CSV))
    resp = client.get(payload["endpoint"])
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ---------------------------------------------------------------- charset ---

# Phrase: "`charset` | no | Character encoding for decoding CSV bytes."
# Context: an explicit charset decodes the bytes with that codec.
def test_explicit_charset_is_used(client, convert, origin):
    body = "name,city\nrené,köln\n".encode("cp1252")
    url = origin.add(body)
    _, payload = convert(source=url, charset="cp1252")
    rows = client.get(payload["endpoint"]).get_json()["rows"]
    assert rows[0] == ["rené", "köln"]


# Phrase: "`charset` ... Character encoding for decoding CSV bytes."
# Context: codec names are matched case/alias-insensitively as Python codecs are.
@pytest.mark.parametrize("name", ["utf-8", "UTF-8", "utf8", "latin-1", "iso-8859-1"])
def test_charset_aliases_accepted(convert, origin, name):
    body = "a,b\n1,2\n".encode("ascii")
    status, _ = convert(source=origin.add(body), charset=name)
    assert status == 200


# Phrase: "If omitted, detect unambiguous encoding from content, else latin-1."
# Context: valid UTF-8 content is unambiguous and must decode as UTF-8.
def test_detects_utf8_when_charset_omitted(client, convert, origin):
    url = origin.add("name,city\nrené,köln\n".encode("utf-8"))
    _, payload = convert(source=url)
    rows = client.get(payload["endpoint"]).get_json()["rows"]
    assert rows[0] == ["rené", "köln"]


# Phrase: "If omitted, detect unambiguous encoding from content, else latin-1."
# Context: bytes that are not valid UTF-8 fall back to latin-1 rather than failing.
def test_falls_back_to_latin1(client, convert, origin):
    url = origin.add("name,city\nrené,köln\n".encode("latin-1"))
    status, payload = convert(source=url)
    assert status == 200
    rows = client.get(payload["endpoint"]).get_json()["rows"]
    assert rows[0] == ["ren\xe9", "k\xf6ln"]


# Phrase: "detect unambiguous encoding from content"
# Context: a BOM is the least ambiguous possible signal; it must not leak into columns.
def test_utf8_bom_detected_and_stripped(client, convert, origin):
    url = origin.add("﻿name,qty\nwidget,3\n".encode("utf-8"))
    _, payload = convert(source=url)
    body = client.get(payload["endpoint"]).get_json()
    assert body["columns"] == ["name", "qty"]


# ----------------------------------------------------------------- errors ---

# Phrase: "| Missing `source` | 400 |"
# Context: /convert with no query parameters at all.
def test_missing_source_is_400(client):
    resp = client.get("/convert")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "| Missing `source` | 400 |"
# Context: source present but empty is equally unusable.
def test_empty_source_is_400(convert):
    status, payload = convert(source="")
    assert status == 400
    assert payload["ok"] is False


# Phrase: "| Invalid URL | 400 |"
# Context: strings that are not retrievable http(s) URLs.
@pytest.mark.parametrize("bad", [
    "not a url",
    "://missing-scheme",
    "http://",
    "   ",
    "httpx://example.com/a.csv",
])
def test_invalid_url_is_400(convert, bad):
    status, payload = convert(source=bad)
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Invalid URL | 400 |"  (see AMBIGUITIES T2)
# Context: non-http schemes are rejected as input rather than fetched.
@pytest.mark.parametrize("bad", ["file:///etc/passwd", "ftp://example.com/a.csv"])
def test_non_http_scheme_is_400(convert, bad):
    status, payload = convert(source=bad)
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"
# Context: a codec name Python does not know.
@pytest.mark.parametrize("bad", ["klingon", "utf-99", "not a charset!"])
def test_unknown_charset_is_400(convert, origin, bad):
    status, payload = convert(source=origin.add(CSV), charset=bad)
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"  (see AMBIGUITIES T8)
# Context: a real codec that cannot decode this payload is "malformed" for this request.
def test_charset_that_cannot_decode_is_400(convert, origin):
    url = origin.add("name,city\nrené,köln\n".encode("latin-1"))
    status, payload = convert(source=url, charset="utf-8")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"  (see AMBIGUITIES T19)
# Context: charset= present but empty names no codec.
def test_empty_charset_is_400(convert, origin):
    status, payload = convert(source=origin.add(CSV), charset="")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: nothing is listening on the target port.
def test_unreachable_source_is_404(convert):
    status, payload = convert(source="http://127.0.0.1:%d/a.csv" % unused_port())
    assert status == 404
    assert payload["ok"] is False


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: a host that does not resolve.
def test_unresolvable_host_is_404(convert):
    status, payload = convert(source="http://nonexistent.invalid/a.csv")
    assert status == 404
    assert payload["ok"] is False


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: remote returns an HTTP error status (4xx and 5xx alike).
@pytest.mark.parametrize("code", [400, 403, 404, 500, 503])
def test_remote_http_error_is_404(convert, origin, code):
    url = origin.add(CSV, path="/err%d.csv" % code, status=code)
    status, payload = convert(source=url)
    assert status == 404, payload
    assert payload["ok"] is False


# Phrase: "| Non-tabular content | 400 |"
# Context: an HTML page served where a CSV was expected.
def test_html_content_is_400(convert, origin):
    html = "<!DOCTYPE html>\n<html>\n<body><p>hello</p></body>\n</html>\n"
    status, payload = convert(source=origin.add(html, content_type="text/html"))
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Non-tabular content | 400 |"
# Context: a JSON document is structured, but not tabular.
def test_json_content_is_400(convert, origin):
    body = '{\n  "a": 1,\n  "b": 2\n}\n'
    status, payload = convert(source=origin.add(body, content_type="application/json"))
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Non-tabular content | 400 |"
# Context: empty body has neither header nor data row.
def test_empty_body_is_400(convert, origin):
    status, payload = convert(source=origin.add(b"", path="/empty.csv"))
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "| Non-tabular content | 400 |"
# Context: binary content is not a decodable table.
def test_binary_content_is_400(convert, origin):
    blob = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + bytes(range(64))
    status, payload = convert(source=origin.add(blob, content_type="image/png"))
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: error-table precedence (see AMBIGUITIES T16)
# Context: local input validation runs before the network fetch.
def test_bad_charset_beats_unreachable_source(convert):
    status, _ = convert(source="http://127.0.0.1:%d/a.csv" % unused_port(), charset="klingon")
    assert status == 400
