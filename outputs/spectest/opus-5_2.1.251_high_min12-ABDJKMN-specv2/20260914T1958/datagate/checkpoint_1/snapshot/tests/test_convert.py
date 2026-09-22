"""Spec section: Ingestion: `GET /convert`."""
import socket

import pytest

from conftest import convert_ok

SIMPLE = "name,age\nAlice,30\nBob,41\n"


def closed_port_url():
    """A URL whose host is up but whose port refuses connections."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/gone.csv"


# ---------------------------------------------------------------------------
# Phrase: "| `source` | yes | URL of the remote CSV file |"
# Context: /convert query parameters.
# ---------------------------------------------------------------------------
def test_source_is_fetched_and_converted(gate, origin):
    url = origin.add("/convert-simple.csv", SIMPLE)
    body = gate.convert(source=url).json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# Phrase: 'Success (`HTTP 200`): {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: /convert success response.
# ---------------------------------------------------------------------------
def test_success_shape_is_ok_and_endpoint(gate, origin):
    url = origin.add("/convert-shape.csv", SIMPLE)
    resp = gate.convert(source=url)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ok", "endpoint"}
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert body["endpoint"] != "/datasets/"  # an id is actually present


# ---------------------------------------------------------------------------
# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
# Context: /convert idempotence.
# ---------------------------------------------------------------------------
def test_same_source_returns_same_endpoint(gate, origin):
    url = origin.add("/convert-idem.csv", SIMPLE)
    first = gate.convert(source=url).json()["endpoint"]
    second = gate.convert(source=url).json()["endpoint"]
    assert first == second


# ---------------------------------------------------------------------------
# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
# Context: distinct sources must not collide onto one endpoint.
# ---------------------------------------------------------------------------
def test_different_sources_get_different_endpoints(gate, origin):
    a = origin.add("/convert-a.csv", SIMPLE)
    b = origin.add("/convert-b.csv", "x,y\n1,2\n")
    assert convert_ok(gate, a) != convert_ok(gate, b)


# ---------------------------------------------------------------------------
# Phrase: "| `charset` | no | Character encoding for decoding CSV bytes."
# Context: /convert query parameters; explicit charset is honoured.
# ---------------------------------------------------------------------------
def test_explicit_charset_decodes_bytes(gate, origin):
    url = origin.add("/convert-cp1252.csv", "name\ncafé\n".encode("cp1252"))
    endpoint = convert_ok(gate, url, charset="cp1252")
    assert gate.get(endpoint).json()["rows"] == [["café"]]


# ---------------------------------------------------------------------------
# Phrase: "If omitted, detect unambiguous encoding from content, else latin-1."
# Context: /convert charset parameter; UTF-8 is detectable from content.
# ---------------------------------------------------------------------------
def test_utf8_is_detected_when_charset_omitted(gate, origin):
    url = origin.add("/convert-detect-utf8.csv", "name\ncafé\n".encode("utf-8"))
    endpoint = convert_ok(gate, url)
    assert gate.get(endpoint).json()["rows"] == [["café"]]


# ---------------------------------------------------------------------------
# Phrase: "If omitted, detect unambiguous encoding from content, else latin-1."
# Context: bytes that are not valid UTF-8 are ambiguous -> latin-1 fallback.
# ---------------------------------------------------------------------------
def test_ambiguous_bytes_fall_back_to_latin1(gate, origin):
    url = origin.add("/convert-detect-latin1.csv", "name\ncafé\n".encode("latin-1"))
    endpoint = convert_ok(gate, url)
    assert gate.get(endpoint).json()["rows"] == [["café"]]


# ---------------------------------------------------------------------------
# Phrase: "| Missing `source` | 400 |"
# Context: /convert errors.
# ---------------------------------------------------------------------------
def test_missing_source_is_400(gate):
    resp = gate.get("/convert")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Missing `source` | 400 |"
# Context: an empty source value is no source at all.
# ---------------------------------------------------------------------------
def test_empty_source_is_400(gate):
    assert gate.convert(source="").status_code == 400


# ---------------------------------------------------------------------------
# Phrase: "| Invalid URL | 400 |"
# Context: /convert errors; malformed or non-fetchable URL forms.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "not a url",
        "example.com/data.csv",   # no scheme
        "http://",                # no host
        "://missing-scheme.csv",
        "ftp://example.com/data.csv",   # scheme datagate cannot fetch
        "file:///etc/passwd",
    ],
)
def test_invalid_url_is_400(gate, bad):
    resp = gate.convert(source=bad)
    assert resp.status_code == 400, (bad, resp.text)
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Unsupported or malformed `charset` | 400 |"
# Context: /convert errors; the codec name is not usable.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["not-a-charset", "utf-99", "!!!", "base64"])
def test_unsupported_charset_is_400(gate, origin, bad):
    url = origin.add("/convert-charset.csv", SIMPLE)
    resp = gate.convert(source=url, charset=bad)
    assert resp.status_code == 400, (bad, resp.text)
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Unsupported or malformed `charset` | 400 |"
# Context: a real codec that cannot decode these bytes (see AMBIGUITIES T7).
# ---------------------------------------------------------------------------
def test_charset_that_cannot_decode_the_bytes_is_400(gate, origin):
    url = origin.add("/convert-baddecode.csv", "name\ncafé\n".encode("latin-1"))
    resp = gate.convert(source=url, charset="utf-8")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: /convert errors; nothing is listening.
# ---------------------------------------------------------------------------
def test_unreachable_source_is_404(gate):
    resp = gate.convert(source=closed_port_url())
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: /convert errors; DNS failure.
# ---------------------------------------------------------------------------
def test_unresolvable_host_is_404(gate):
    resp = gate.convert(source="http://datagate-no-such-host.invalid/data.csv")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: /convert errors; the remote answers with an HTTP error status.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", [404, 403, 500, 503])
def test_remote_http_error_is_404(gate, origin, status):
    url = origin.add(f"/convert-remote-{status}.csv", SIMPLE, status=status)
    resp = gate.convert(source=url)
    assert resp.status_code == 404, (status, resp.text)
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Non-tabular content | 400 |"
# Context: /convert errors; the body is reachable but is not a table.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,body,ctype",
    [
        ("html", "<!DOCTYPE html><html><body><h1>Hi</h1></body></html>", "text/html"),
        ("json", '{"name": "Alice", "age": 30}', "application/json"),
        ("json-array", '[{"a": 1}, {"a": 2}]', "application/json"),
        ("empty", "", "text/csv"),
        ("blank", "   \n\n \n", "text/csv"),
        ("prose", "This file is not a CSV at all.\nIt is just some English prose.\n", "text/plain"),
        ("binary", "\x00\x01\x02binarygarbage\x00", "application/octet-stream"),
    ],
)
def test_non_tabular_content_is_400(gate, origin, name, body, ctype):
    url = origin.add(f"/convert-nontabular-{name}", body, content_type=ctype)
    resp = gate.convert(source=url)
    assert resp.status_code == 400, (name, resp.text)
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "| Unsupported or malformed `charset` | 400 |" vs
#         "| Source unreachable ... | 404 |"
# Context: error precedence -- caller input is validated first (AMBIGUITIES T14).
# ---------------------------------------------------------------------------
def test_charset_validated_before_fetching(gate):
    resp = gate.convert(source=closed_port_url(), charset="not-a-charset")
    assert resp.status_code == 400
