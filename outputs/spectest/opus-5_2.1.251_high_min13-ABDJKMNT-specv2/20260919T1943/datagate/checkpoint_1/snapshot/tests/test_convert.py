"""Spec section: Ingestion `GET /convert`."""

import responses

from conftest import SIMPLE_CSV, SOURCE_URL


# Phrase: "Success (HTTP 200): {"ok": true, "endpoint": "/datasets/<id>"}"
def test_convert_returns_ok_and_dataset_endpoint(client, serve):
    response = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert set(body) == {"ok", "endpoint"}


# Phrase: "endpoint": "/datasets/<id>" — the advertised endpoint is immediately usable.
def test_reported_endpoint_serves_the_dataset(client, serve):
    endpoint = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)}).get_json()["endpoint"]

    assert client.get(endpoint).status_code == 200


# Phrase: "`charset` | no | Character encoding for decoding CSV bytes."
def test_explicit_charset_is_used_to_decode(client, serve):
    body = "city,note\nzürich,groß\n".encode("cp1252")
    source = serve(body, content_type="text/csv")

    endpoint = client.get("/convert", query_string={"source": source, "charset": "cp1252"}).get_json()["endpoint"]

    assert client.get(endpoint).get_json()["rows"] == [["zürich", "groß"]]


# Phrase: "| Missing `source` | 400 |"
def test_missing_source_is_400(client):
    response = client.get("/convert")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase (context: `source` is required): an empty `source` value is also missing.
def test_empty_source_is_400(client):
    assert client.get("/convert", query_string={"source": ""}).status_code == 400


# Phrase: "| Invalid URL | 400 |"
@responses.activate
def test_invalid_urls_are_400(client):
    for source in ["not-a-url", "htp:/broken", "http://", "://example.test/a.csv", "/local/path.csv"]:
        response = client.get("/convert", query_string={"source": source})
        assert response.status_code == 400, source
        assert response.get_json()["ok"] is False


# Phrase: "| Invalid URL | 400 |" (context: a fetchable dataset must live behind http/https)
@responses.activate
def test_non_http_scheme_is_invalid(client):
    assert client.get("/convert", query_string={"source": "file:///etc/passwd"}).status_code == 400
    assert client.get("/convert", query_string={"source": "ftp://example.test/a.csv"}).status_code == 400


# Phrase: "| Unsupported or malformed `charset` | 400 |"
def test_unknown_charset_is_400(client, serve):
    source = serve(SIMPLE_CSV)

    response = client.get("/convert", query_string={"source": source, "charset": "utf-99"})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |" (context: empty / nonsense values)
def test_malformed_charset_is_400(client, serve):
    source = serve(SIMPLE_CSV)

    for charset in ["", "  ", "utf 8 ish!!"]:
        assert client.get("/convert", query_string={"source": source, "charset": charset}).status_code == 400


# Phrase: "| Unsupported or malformed `charset` | 400 |" (context: T7 — bytes that the charset cannot decode)
def test_charset_that_cannot_decode_the_body_is_400(client, serve):
    source = serve("city\nzürich\n".encode("cp1252"))

    assert client.get("/convert", query_string={"source": source, "charset": "utf-8"}).status_code == 400


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
def test_remote_http_error_is_404(client, serve):
    for status in (404, 403, 500):
        source = serve("nope", url=f"https://example.test/{status}.csv", status=status)
        response = client.get("/convert", query_string={"source": source})
        assert response.status_code == 404, status
        assert response.get_json()["ok"] is False


# Phrase: "| Source unreachable ... | 404 |" (context: connection failures)
@responses.activate
def test_unreachable_source_is_404(client):
    responses.add(responses.GET, SOURCE_URL, body=ConnectionError("no route"))

    assert client.get("/convert", query_string={"source": SOURCE_URL}).status_code == 404


# Phrase: "| Non-tabular content | 400 |"
def test_html_content_is_non_tabular(client, serve):
    source = serve("<html><body><p>not a csv</p></body></html>", content_type="text/html")

    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Non-tabular content | 400 |" (context: JSON payloads)
def test_json_content_is_non_tabular(client, serve):
    source = serve('{"name": "ada", "age": 36}', content_type="application/json")

    assert client.get("/convert", query_string={"source": source}).status_code == 400


# Phrase: "| Non-tabular content | 400 |" (context: binary payloads)
def test_binary_content_is_non_tabular(client, serve):
    source = serve(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00", content_type="image/png")

    assert client.get("/convert", query_string={"source": source}).status_code == 400


# Phrase: "| Non-tabular content | 400 |" (context: empty bodies)
def test_empty_content_is_non_tabular(client, serve):
    assert client.get("/convert", query_string={"source": serve("")}).status_code == 400


# Phrase: "/convert returns the same endpoint for the same `source` URL string."
def test_same_source_returns_same_endpoint(client, serve):
    source = serve(SIMPLE_CSV)

    first = client.get("/convert", query_string={"source": source}).get_json()["endpoint"]
    second = client.get("/convert", query_string={"source": source}).get_json()["endpoint"]

    assert first == second


# Phrase: "the same `source` URL string" (context: different URLs are different datasets)
def test_different_sources_return_different_endpoints(client, serve):
    first_url = serve(SIMPLE_CSV, url="https://example.test/one.csv")
    second_url = serve(SIMPLE_CSV, url="https://example.test/two.csv")

    first = client.get("/convert", query_string={"source": first_url}).get_json()["endpoint"]
    second = client.get("/convert", query_string={"source": second_url}).get_json()["endpoint"]

    assert first != second
