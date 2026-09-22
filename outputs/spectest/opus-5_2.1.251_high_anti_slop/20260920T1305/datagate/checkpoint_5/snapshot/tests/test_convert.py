"""Tests for ingestion via /convert."""

CSV = b"name,age\nada,36\n"


def test_convert_returns_dataset_endpoint(client, serve):
    response = client.get("/convert", query_string={"source": serve("a.csv", CSV)})

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["endpoint"].startswith("/datasets/")


def test_same_source_maps_to_same_endpoint(client, serve):
    source = serve("a.csv", CSV)

    first = client.get("/convert", query_string={"source": source})
    second = client.get("/convert", query_string={"source": source})

    assert first.json["endpoint"] == second.json["endpoint"]


def test_missing_source_is_rejected(client):
    response = client.get("/convert")

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


def test_invalid_url_is_rejected(client):
    response = client.get("/convert", query_string={"source": "not a url"})

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_unknown_charset_is_rejected(client, serve):
    response = client.get(
        "/convert", query_string={"source": serve("a.csv", CSV), "charset": "utf-99"}
    )

    assert response.status_code == 400


def test_charset_that_cannot_decode_the_body_is_rejected(client, serve):
    source = serve("a.csv", "name;city\nada;münchen\n".encode("utf-8"))

    response = client.get(
        "/convert", query_string={"source": source, "charset": "ascii"}
    )

    assert response.status_code == 400


def test_unreachable_source_is_not_found(client):
    response = client.get(
        "/convert", query_string={"source": "http://127.0.0.1:1/a.csv"}
    )

    assert response.status_code == 404


def test_remote_http_error_is_not_found(client, serve):
    source = serve("a.csv", CSV).replace("a.csv", "missing.csv")

    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 404


def test_non_tabular_content_is_rejected(client, serve):
    source = serve("page.html", b"<html><body><p>hello</p></body></html>")

    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 400


def test_header_without_data_row_is_rejected(client, serve):
    response = client.get(
        "/convert", query_string={"source": serve("a.csv", b"name,age\n")}
    )

    assert response.status_code == 400


def test_unknown_route_returns_json_404(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json["ok"] is False


def test_responses_carry_cors_headers(client):
    response = client.get("/convert")

    assert response.headers["Access-Control-Allow-Origin"] == "*"
