"""Spec sections: Response Envelope, Cross-Origin Access."""
import pytest

from conftest import unused_port

CSV = "a,b\n1,2\n"


# Phrase: 'Success responses include `"ok": true`.'
# Context: applies to /convert.
def test_convert_success_has_ok_true(convert, origin):
    status, payload = convert(source=origin.add(CSV))
    assert status == 200
    assert payload["ok"] is True


# Phrase: 'Success responses include `"ok": true`.'
# Context: applies to /datasets/<id>.
def test_dataset_success_has_ok_true(dataset):
    status, body = dataset(CSV)
    assert status == 200
    assert body["ok"] is True


# Phrase: 'Error responses use: {"ok": false, "error": "<human-readable message>"}'
# Context: every documented error carries ok=false plus a non-empty message string.
@pytest.mark.parametrize("path,query", [
    ("/convert", {}),                                   # missing source
    ("/convert", {"source": "not a url"}),              # invalid URL
    ("/datasets/unknown-id", {}),                       # unknown dataset
    ("/no/such/route", {}),                             # unknown route
])
def test_error_envelope_shape(client, path, query):
    resp = client.get(path, query_string=query)
    assert resp.status_code >= 400
    body = resp.get_json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()


# Phrase: 'Error responses use: {"ok": false, "error": ...}'
# Context: the error body carries no success fields.
def test_error_body_has_no_success_fields(client):
    body = client.get("/convert").get_json()
    assert "rows" not in body and "columns" not in body and "endpoint" not in body


# Phrase: "All errors are JSON"
# Context: content type must be JSON for errors, not HTML.
@pytest.mark.parametrize("path", ["/convert", "/datasets/nope", "/totally/unknown"])
def test_errors_are_json_content_type(client, path):
    resp = client.get(path)
    assert resp.status_code >= 400
    assert "application/json" in resp.headers.get("Content-Type", "")
    assert resp.get_json() is not None


# Phrase: "unknown routes return `HTTP 404`."
# Context: any unrouted path, at any depth, including the site root.
@pytest.mark.parametrize("path", ["/", "/datasets", "/convert/extra", "/favicon.ico", "/a/b/c"])
def test_unknown_routes_are_404_json(client, path):
    resp = client.get(path)
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


# Phrase: "All errors are JSON" (see AMBIGUITIES T13)
# Context: a wrong method on a known path still yields a JSON error envelope.
@pytest.mark.parametrize("path", ["/convert", "/datasets/nope"])
def test_wrong_method_is_json_error(client, path):
    resp = client.post(path)
    assert resp.status_code >= 400
    body = resp.get_json()
    assert body is not None and body["ok"] is False


# Phrase: "All errors are JSON"
# Context: an internal 5xx path, if any, must not leak an HTML traceback page.
def test_server_errors_are_json(client, convert):
    status, payload = convert(source="http://127.0.0.1:%d/x.csv" % unused_port())
    assert payload is not None and payload["ok"] is False


# --------------------------------------------------------- Cross-Origin -----

# Phrase: "Include CORS headers for browser access."
# Context: successful /convert response.
def test_cors_header_on_convert_success(client, origin):
    resp = client.get("/convert", query_string={"source": origin.add(CSV)},
                      headers={"Origin": "http://example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com")


# Phrase: "Include CORS headers for browser access."
# Context: successful dataset response.
def test_cors_header_on_dataset_success(client, convert, origin):
    _, payload = convert(source=origin.add(CSV))
    resp = client.get(payload["endpoint"], headers={"Origin": "http://example.com"})
    assert resp.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com")


# Phrase: "Include CORS headers for browser access."  (see AMBIGUITIES T14)
# Context: browsers must also be able to read error bodies.
@pytest.mark.parametrize("path", ["/convert", "/datasets/nope", "/unknown"])
def test_cors_header_on_errors(client, path):
    resp = client.get(path, headers={"Origin": "http://example.com"})
    assert resp.status_code >= 400
    assert resp.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com")


# Phrase: "Include CORS headers for browser access."
# Context: a preflight request must be answered with the allowed methods.
def test_cors_preflight(client):
    resp = client.options("/convert", headers={
        "Origin": "http://example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert resp.status_code < 400
    assert resp.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com")
    assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "GET")
