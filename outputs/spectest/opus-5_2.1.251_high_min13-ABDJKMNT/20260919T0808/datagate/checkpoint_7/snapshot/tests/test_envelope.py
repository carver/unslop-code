"""Spec sections: Response Envelope and Cross-Origin Access."""

from tests.conftest import SIMPLE_CSV


# Phrase: "Success responses include `"ok": true`."
def test_success_responses_carry_ok_true(client, convert):
    converted = convert(SIMPLE_CSV)
    assert converted.get_json()["ok"] is True
    assert client.get(converted.get_json()["endpoint"]).get_json()["ok"] is True


# Phrase: "Error responses use: {"ok": false, "error": "<human-readable message>"}"
def test_error_responses_carry_ok_false_and_a_message(client):
    for path in ["/convert", "/convert?source=nonsense", "/datasets/unknown", "/nope"]:
        payload = client.get(path).get_json()
        assert payload["ok"] is False, path
        assert isinstance(payload["error"], str) and payload["error"].strip(), path


# Phrase: "All errors are JSON"
def test_all_errors_are_json(client):
    for path in ["/convert", "/datasets/unknown", "/nope", "/datasets/"]:
        response = client.get(path)
        assert response.mimetype == "application/json", path
        assert response.get_json() is not None, path


# Phrase: "unknown routes return `HTTP 404`."
def test_unknown_routes_are_404(client):
    for path in ["/", "/nope", "/convert/extra", "/datasets"]:
        assert client.get(path).status_code == 404, path


# Phrase: "All errors are JSON" - including a wrong method on a known route (T13).
def test_wrong_method_returns_json(client):
    response = client.post("/convert?source=http://example.com/a.csv")
    assert response.mimetype == "application/json"
    assert response.get_json()["ok"] is False
    assert response.status_code in (404, 405)


# Phrase: "Include CORS headers for browser access."
def test_success_responses_include_cors_headers(client, convert):
    converted = convert(SIMPLE_CSV)
    assert converted.headers["Access-Control-Allow-Origin"] == "*"
    assert client.get(converted.get_json()["endpoint"]).headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Include CORS headers for browser access." - errors are read by browsers too.
def test_error_responses_include_cors_headers(client):
    assert client.get("/datasets/unknown").headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Include CORS headers for browser access." - preflight is answered.
def test_preflight_request_is_answered(client):
    response = client.options(
        "/convert",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code in (200, 204)
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in response.headers.get("Access-Control-Allow-Methods", "")
