"""Spec sections: Response Envelope, Cross-Origin Access."""
import pytest

from conftest import convert_ok

SIMPLE = "name,age\nAlice,30\n"


# ---------------------------------------------------------------------------
# Phrase: "Success responses include `\"ok\": true`."
# Context: response envelope, both success routes.
# ---------------------------------------------------------------------------
def test_success_responses_include_ok_true(gate, origin):
    url = origin.add("/env-ok.csv", SIMPLE)
    convert_resp = gate.convert(source=url)
    assert convert_resp.json()["ok"] is True
    endpoint = convert_resp.json()["endpoint"]
    assert gate.get(endpoint).json()["ok"] is True


# ---------------------------------------------------------------------------
# Phrase: 'Error responses use: {"ok": false, "error": "<human-readable message>"}'
# Context: response envelope for every documented error.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,params",
    [
        ("/convert", {}),                                     # missing source
        ("/convert", {"source": "not a url"}),                # invalid URL
        ("/convert", {"source": "http://127.0.0.1:1/x.csv"}),  # unreachable
        ("/datasets/unknown-id", None),                        # unknown dataset
        ("/no-such-route", None),                              # unknown route
    ],
)
def test_error_envelope(gate, path, params):
    resp = gate.get(path, params=params or {})
    assert resp.status_code >= 400
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()


# ---------------------------------------------------------------------------
# Phrase: "All errors are JSON"
# Context: response envelope; content type of failures.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/convert", "/datasets/unknown", "/nope", "/"])
def test_all_errors_are_json(gate, path):
    resp = gate.get(path)
    assert resp.status_code >= 400
    assert resp.headers["Content-Type"].split(";")[0] == "application/json"
    resp.json()  # must parse


# ---------------------------------------------------------------------------
# Phrase: "unknown routes return `HTTP 404`"
# Context: response envelope.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/nope", "/datasets", "/convert/extra", "/a/b/c"])
def test_unknown_routes_are_404(gate, path):
    resp = gate.get(path)
    assert resp.status_code == 404, (path, resp.text)
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "All errors are JSON"
# Context: a wrong method on a known route still yields the JSON envelope
#          (status choice documented in AMBIGUITIES T13).
# ---------------------------------------------------------------------------
def test_wrong_method_is_json_error(gate):
    resp = gate.request("POST", "/convert")
    assert resp.status_code in (404, 405)
    assert resp.headers["Content-Type"].split(";")[0] == "application/json"
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "Include CORS headers for browser access."
# Context: cross-origin access on a success response.
# ---------------------------------------------------------------------------
def test_cors_headers_on_success(gate, origin):
    url = origin.add("/cors.csv", SIMPLE)
    resp = gate.convert(source=url, **{})
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"
    endpoint = resp.json()["endpoint"]
    assert gate.get(endpoint).headers.get("Access-Control-Allow-Origin") == "*"


# ---------------------------------------------------------------------------
# Phrase: "Include CORS headers for browser access."
# Context: a browser must be able to read error responses too.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/convert", "/datasets/unknown", "/nope"])
def test_cors_headers_on_errors(gate, path):
    resp = gate.get(path)
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


# ---------------------------------------------------------------------------
# Phrase: "Include CORS headers for browser access."
# Context: preflight request from a browser.
# ---------------------------------------------------------------------------
def test_cors_preflight(gate):
    resp = gate.request(
        "OPTIONS",
        "/convert",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code < 400
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"
    assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "")
