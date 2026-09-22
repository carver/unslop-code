"""Ingestion behaviour of ``GET /convert``."""

SIMPLE = b"name,age\nada,36\n"


def test_returns_dataset_endpoint(convert):
    body = convert(SIMPLE).get_json()
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")


def test_same_source_maps_to_same_endpoint(convert):
    first = convert(SIMPLE).get_json()["endpoint"]
    assert convert(SIMPLE).get_json()["endpoint"] == first


def test_missing_source_is_rejected(client):
    response = client.get("/convert")
    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "Query parameter 'source' is required",
    }


def test_invalid_url_is_rejected(client):
    assert client.get("/convert", query_string={"source": "not a url"}).status_code == 400


def test_unknown_charset_is_rejected(convert):
    response = convert(SIMPLE, charset="klingon-8")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_remote_error_status_is_reported_as_missing(client, base_url):
    response = client.get("/convert", query_string={"source": f"{base_url}/absent.csv"})
    assert response.status_code == 404


def test_unreachable_host_is_reported_as_missing(client):
    response = client.get(
        "/convert", query_string={"source": "http://127.0.0.1:1/data.csv"}
    )
    assert response.status_code == 404


def test_markup_is_not_tabular(convert):
    assert convert(b"<html><body>hello</body></html>").status_code == 400


def test_header_without_data_rows_is_rejected(convert):
    assert convert(b"name,age\n").status_code == 400
