"""Cross-origin access."""


# Spec: "Include CORS headers for browser access."
# Context: successful responses are readable from a browser origin.
def test_cors_header_on_success(client, convert):
    response = convert("a,b\n1,2\n")
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    endpoint = response.get_json()["endpoint"]
    assert client.get(endpoint).headers["Access-Control-Allow-Origin"] == "*"


# Spec: "Include CORS headers for browser access."
# Context: error responses need the header too, or the browser hides the body.
def test_cors_header_on_errors(client):
    for path in ("/convert", "/datasets/unknown-id", "/nope"):
        assert client.get(path).headers["Access-Control-Allow-Origin"] == "*", path


# Spec: "Include CORS headers for browser access."
# Context: preflight requests are answered with the allowed methods.
def test_preflight_is_answered(client):
    response = client.options("/convert")
    assert response.status_code < 400
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
