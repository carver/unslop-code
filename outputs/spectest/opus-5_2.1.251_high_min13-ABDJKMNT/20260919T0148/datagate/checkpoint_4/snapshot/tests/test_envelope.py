"""Spec sections: Response Envelope and Cross-Origin Access."""

CSV = "name,age\nada,36\n"


# Phrase: "Success responses include `"ok": true`."
def test_success_responses_carry_ok_true(client, origin):
    source = origin.serve("/data.csv", CSV)

    convert = client.get("/convert", query_string={"source": source})
    dataset = client.get(convert.get_json()["endpoint"])

    assert convert.get_json()["ok"] is True
    assert dataset.get_json()["ok"] is True


# Phrase: "Error responses use: {"ok": false, "error": "<human-readable message>"}"
def test_error_envelope_shape(client):
    body = client.get("/convert").get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str)
    assert body["error"].strip()


# Phrase: "All errors are JSON"
def test_errors_are_json(client):
    for path in ["/convert", "/datasets/unknown", "/no/such/route"]:
        response = client.get(path)
        assert response.status_code >= 400
        assert response.mimetype == "application/json"
        assert response.get_json()["ok"] is False


# Phrase: "unknown routes return `HTTP 404`."
def test_unknown_route_is_404(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "All errors are JSON" -- context: wrong method on a known route (AMBIGUITIES T9).
def test_wrong_method_is_json_error(client):
    response = client.post("/convert")

    assert response.status_code == 405
    assert response.get_json()["ok"] is False


# Phrase: "Include CORS headers for browser access."
def test_cors_headers_on_success(client, origin):
    source = origin.serve("/data.csv", CSV)

    response = client.get("/convert", query_string={"source": source})

    assert response.headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Include CORS headers for browser access." -- context: errors too.
def test_cors_headers_on_errors(client):
    response = client.get("/datasets/unknown")

    assert response.headers["Access-Control-Allow-Origin"] == "*"


# Phrase: "Include CORS headers for browser access." -- context: preflight.
def test_cors_preflight_is_allowed(client):
    response = client.options("/convert")

    assert response.status_code < 400
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
