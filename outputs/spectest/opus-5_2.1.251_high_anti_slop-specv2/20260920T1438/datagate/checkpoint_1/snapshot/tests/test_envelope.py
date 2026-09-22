"""Response envelope, CORS headers and routing fallbacks."""


def test_unknown_route_returns_json_404(client):
    response = client.get("/nowhere")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_cors_headers_are_present(client):
    assert client.get("/nowhere").headers["Access-Control-Allow-Origin"] == "*"
