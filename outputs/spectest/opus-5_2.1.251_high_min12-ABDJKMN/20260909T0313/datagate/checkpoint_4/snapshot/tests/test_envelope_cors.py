"""Spec sections: Response Envelope, Cross-Origin Access."""

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\n"


# Phrase: 'Success responses include `"ok": true`.'  (/convert)
def test_convert_success_includes_ok_true(convert):
    payload = convert("/ok.csv", SIMPLE).get_json()
    assert payload["ok"] is True


# Phrase: 'Success responses include `"ok": true`.'  (/datasets/<id>)
def test_dataset_success_includes_ok_true(dataset):
    payload = dataset("/ok2.csv", SIMPLE).get_json()
    assert payload["ok"] is True


# Phrase: 'Error responses use: {"ok": false, "error": "<human-readable message>"}'
@pytest.mark.parametrize(
    "path,query",
    [
        ("/convert", {}),
        ("/convert", {"source": "not a url"}),
        ("/datasets/unknown-id", {}),
        ("/nope", {}),
    ],
)
def test_error_envelope_shape(client, path, query):
    response = client.get(path, query_string=query)
    assert response.status_code >= 400
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)
    assert payload["error"].strip()


# Phrase: "All errors are JSON"
@pytest.mark.parametrize(
    "path,query",
    [
        ("/convert", {}),
        ("/convert", {"source": "http://"}),
        ("/datasets/unknown-id", {}),
        ("/totally/unknown/route", {}),
        ("/", {}),
    ],
)
def test_all_errors_are_json(client, path, query):
    response = client.get(path, query_string=query)
    assert response.status_code >= 400
    assert response.mimetype == "application/json"
    assert response.get_json()["ok"] is False


# Phrase: "unknown routes return `HTTP 404`."
@pytest.mark.parametrize(
    "path", ["/", "/nope", "/dataset/abc", "/datasets", "/convert/extra", "/favicon.ico"]
)
def test_unknown_routes_are_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "Cross-Origin Access: Include CORS headers for browser access."
# Context: success responses.
def test_cors_headers_on_success(convert, client):
    response = convert("/cors.csv", SIMPLE)
    assert response.headers.get("Access-Control-Allow-Origin") == "*"
    endpoint = response.get_json()["endpoint"]
    assert client.get(endpoint).headers.get("Access-Control-Allow-Origin") == "*"


# Phrase: "Include CORS headers for browser access."  Context: error responses too.
@pytest.mark.parametrize("path", ["/convert", "/datasets/unknown-id", "/nope"])
def test_cors_headers_on_errors(client, path):
    response = client.get(path)
    assert response.headers.get("Access-Control-Allow-Origin") == "*"


# Phrase: "Include CORS headers for browser access."
# Context: a browser preflight must be answered with the allowed methods/headers.
def test_cors_preflight(client):
    response = client.options(
        "/convert",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code < 400
    assert response.headers.get("Access-Control-Allow-Origin") == "*"
    assert "GET" in response.headers.get("Access-Control-Allow-Methods", "")


# Phrase: "Include CORS headers for browser access."
# Context: an explicit Origin header is still answered permissively.
def test_cors_with_origin_header(convert, client, origin):
    convert("/cors2.csv", SIMPLE)
    response = client.get(
        "/convert",
        query_string={"source": origin.url("/cors2.csv")},
        headers={"Origin": "http://example.com"},
    )
    assert response.headers.get("Access-Control-Allow-Origin") in ("*", "http://example.com")


# Phrase: "All errors are JSON" -- context: a wrong method still yields the
# JSON envelope (status choice recorded in AMBIGUITIES T13).
def test_wrong_method_is_json_error(client):
    response = client.post("/convert", query_string={"source": "http://x/y.csv"})
    assert response.status_code in (404, 405)
    assert response.mimetype == "application/json"
    assert response.get_json()["ok"] is False
