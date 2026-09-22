"""Spec section: Ingestion: `GET /convert`."""

from tests.conftest import SIMPLE_CSV


# Phrase: "Success (HTTP 200): {"ok": true, "endpoint": "/datasets/<id>"}"
def test_convert_returns_ok_and_endpoint(convert):
    response = convert(SIMPLE_CSV)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["endpoint"].startswith("/datasets/")
    assert payload["endpoint"].removeprefix("/datasets/") != ""


# Phrase: "`source` | yes | URL of the remote CSV file"
def test_converted_endpoint_serves_the_remote_file(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["name", "age"]


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
def test_same_source_yields_same_endpoint(client, origin):
    url = origin.serve("/stable.csv", SIMPLE_CSV)
    first = client.get(f"/convert?source={url}").get_json()
    second = client.get(f"/convert?source={url}").get_json()
    assert first["endpoint"] == second["endpoint"]


# Phrase: "the same endpoint for the same `source`" - different sources differ.
def test_different_sources_yield_different_endpoints(client, origin):
    one = origin.serve("/one.csv", SIMPLE_CSV)
    two = origin.serve("/two.csv", SIMPLE_CSV)
    assert (
        client.get(f"/convert?source={one}").get_json()["endpoint"]
        != client.get(f"/convert?source={two}").get_json()["endpoint"]
    )


# Phrase: "| Missing `source` | 400 |"
def test_missing_source_is_400(client):
    response = client.get("/convert")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Missing `source` | 400 |" - an empty value is equally unusable.
def test_empty_source_is_400(client):
    assert client.get("/convert?source=").status_code == 400


# Phrase: "| Invalid URL | 400 |"
def test_invalid_urls_are_400(client):
    for source in ["not a url", "http://", "example.com/data.csv", "://nope"]:
        response = client.get(f"/convert?source={source}")
        assert response.status_code == 400, source
        assert response.get_json()["ok"] is False


# Phrase: "| Invalid URL | 400 |" - non-HTTP schemes cannot be fetched (T7).
def test_non_http_schemes_are_400(client):
    for source in ["file:///etc/passwd", "ftp://example.com/data.csv"]:
        assert client.get(f"/convert?source={source}").status_code == 400, source


# Phrase: "| Unsupported or malformed `charset` | 400 |"
def test_unknown_charset_is_400(convert):
    response = convert(SIMPLE_CSV, query="&charset=utf-99")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"
def test_malformed_charset_is_400(convert):
    assert convert(SIMPLE_CSV, query="&charset=%20%25%25").status_code == 400


# Phrase: "| Unsupported or malformed `charset` | 400 |" - charset that cannot
# decode these bytes (T6).
def test_charset_that_fails_to_decode_is_400(convert):
    latin1_bytes = "name,city\nrené,münchen\n".encode("latin-1")
    assert convert(latin1_bytes, query="&charset=utf-8").status_code == 400


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
def test_unreachable_source_is_404(client):
    response = client.get("/convert?source=http://127.0.0.1:9/never.csv")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
def test_remote_http_error_is_404(convert):
    for status in (404, 500):
        response = convert("boom", status=status, content_type="text/html")
        assert response.status_code == 404, status


# Phrase: "| Source unreachable or remote HTTP error | 404 |" - unresolvable host.
def test_unresolvable_host_is_404(client):
    assert client.get("/convert?source=http://no.such.host.datagate/x.csv").status_code == 404


# Phrase: "| Non-tabular content | 400 |"
def test_non_tabular_content_is_400(convert):
    for body, content_type in [
        ("<html><body>hello, world</body></html>", "text/html"),
        ('{"name": "ada", "age": 36}', "application/json"),
        ("just a sentence of prose\nand another line\n", "text/plain"),
        ("", "text/csv"),
    ]:
        response = convert(body, content_type=content_type)
        assert response.status_code == 400, body
        assert response.get_json()["ok"] is False


# Phrase: "A valid file requires at least one header row and one data row."
def test_header_without_data_rows_is_400(convert):
    assert convert("name,age\n").status_code == 400
    assert convert("name,age\n\n\n").status_code == 400
