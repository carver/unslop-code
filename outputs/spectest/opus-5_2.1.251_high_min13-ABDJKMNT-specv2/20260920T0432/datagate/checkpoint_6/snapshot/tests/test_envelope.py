"""Response envelope and routing rules."""


# Spec: "Success responses include "ok": true."
# Context: both documented success paths.
def test_success_responses_carry_ok_true(client, convert):
    convert_body = convert("a,b\n1,2\n").get_json()
    assert convert_body["ok"] is True
    assert client.get(convert_body["endpoint"]).get_json()["ok"] is True


# Spec: "Error responses use: {"ok": false, "error": "<human-readable message>"}"
# Context: a representative error from each status.
def test_error_envelope_shape(client):
    responses = [
        client.get("/convert"),
        client.get("/datasets/unknown-id"),
        client.get("/no-such-route"),
    ]
    for response in responses:
        body = response.get_json()
        assert body["ok"] is False
        assert isinstance(body["error"], str) and body["error"]
        assert set(body) == {"ok", "error"}


# Spec: "All errors are JSON"
# Context: error responses carry a JSON content type, never Flask's HTML page.
def test_errors_are_json_content_type(client):
    for path in ("/convert", "/datasets/unknown-id", "/nope"):
        response = client.get(path)
        assert response.mimetype == "application/json", path


# Spec: "unknown routes return HTTP 404"
# Context: paths outside the two documented routes.
def test_unknown_routes_are_404(client):
    for path in ("/", "/nope", "/datasets", "/convert/extra"):
        assert client.get(path).status_code == 404, path


# Spec: "All errors are JSON; unknown routes return HTTP 404."
# Context: a known route with an unsupported method (AMBIGUITIES T10).
def test_wrong_method_is_json_error(client):
    response = client.post("/convert")
    assert response.status_code == 405
    assert response.get_json()["ok"] is False
