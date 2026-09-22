"""Spec sections: Response Envelope and Cross-Origin Access."""

from conftest import SIMPLE_CSV


# Phrase: "Success responses include "ok": true."
def test_success_responses_carry_ok_true(client, serve):
    convert = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)})

    assert convert.get_json()["ok"] is True
    assert client.get(convert.get_json()["endpoint"]).get_json()["ok"] is True


# Phrase: "Error responses use: {"ok": false, "error": "<human-readable message>"}"
def test_error_envelope_has_ok_false_and_message(client):
    body = client.get("/convert").get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()
    assert set(body) == {"ok", "error"}


# Phrase: "All errors are JSON"
def test_all_errors_are_json(client, serve):
    failures = [
        client.get("/convert"),
        client.get("/convert", query_string={"source": "not-a-url"}),
        client.get("/datasets/does-not-exist"),
        client.get("/nope"),
        client.post("/convert"),
    ]

    for response in failures:
        assert response.mimetype == "application/json", response.status
        assert response.get_json()["ok"] is False


# Phrase: "unknown routes return HTTP 404."
def test_unknown_routes_are_404_json(client):
    response = client.get("/definitely/not/a/route")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "unknown routes return HTTP 404." (context: T15 — a known route with the wrong method)
def test_wrong_method_on_known_route_is_json(client):
    response = client.post("/convert")

    assert response.status_code in (404, 405)
    assert response.get_json()["ok"] is False


# Phrase: "Include CORS headers for browser access."
def test_cors_headers_on_success(client, serve):
    response = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)})

    assert response.headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Include CORS headers for browser access." (context: browsers also read error responses)
def test_cors_headers_on_errors(client):
    assert client.get("/convert").headers["Access-Control-Allow-Origin"] == "*"
    assert client.get("/nope").headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Include CORS headers for browser access." (context: preflight)
def test_preflight_is_answered(client):
    response = client.options("/convert")

    assert response.status_code < 400
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
