"""Ingestion endpoint: GET /convert."""

import re

CSV = "name,age\nada,36\n"


# Spec: "Success (HTTP 200): {"ok": true, "endpoint": "/datasets/<id>"}"
# Context: a reachable CSV source with only the required `source` parameter.
def test_success_payload_shape(convert):
    response = convert(CSV)
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert re.fullmatch(r"/datasets/[A-Za-z0-9_.-]+", body["endpoint"])
    assert set(body) == {"ok", "endpoint"}


# Spec: "| `source` | yes | URL of the remote CSV file |" and "| Missing `source` | 400 |"
# Context: /convert called with no query string at all.
def test_missing_source_is_400(client):
    response = client.get("/convert")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "| Missing `source` | 400 |"
# Context: `source` present but empty is the same as absent.
def test_empty_source_is_400(client):
    assert client.get("/convert", query_string={"source": ""}).status_code == 400


# Spec: "| Invalid URL | 400 |"
# Context: strings that are not fetchable http(s) URLs (see AMBIGUITIES T9).
def test_invalid_urls_are_400(client):
    for source in ["not-a-url", "http://", "://missing-scheme", "ftp://host/f.csv"]:
        response = client.get("/convert", query_string={"source": source})
        assert response.status_code == 400, source
        assert response.get_json()["ok"] is False


# Spec: "| Source unreachable or remote HTTP error | 404 |"
# Context: the host refuses the connection.
def test_unreachable_source_is_404(client):
    source = "http://127.0.0.1:1/never-listening.csv"
    assert client.get("/convert", query_string={"source": source}).status_code == 404


# Spec: "| Source unreachable or remote HTTP error | 404 |"
# Context: the origin answers with a non-2xx status.
def test_remote_http_error_is_404(client, origin):
    for status in (404, 500):
        source = origin.serve(f"/err-{status}.csv", CSV, status=status)
        response = client.get("/convert", query_string={"source": source})
        assert response.status_code == 404, status
        assert response.get_json()["ok"] is False


# Spec: "| `charset` | no | Character encoding for decoding CSV bytes. |"
# Context: an explicit charset decodes the bytes that were served.
def test_explicit_charset_decodes_bytes(dataset):
    body = "city,note\nmalmö,café\n".encode("iso-8859-1")
    payload = dataset(body, params={"charset": "iso-8859-1"})
    assert payload["rows"] == [["malmö", "café"]]


# Spec: "| Unsupported or malformed `charset` | 400 |"
# Context: a codec name no decoder knows.
def test_unknown_charset_is_400(convert):
    response = convert(CSV, params={"charset": "definitely-not-a-charset"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "| Unsupported or malformed `charset` | 400 |"
# Context: an empty charset value is malformed.
def test_empty_charset_is_400(convert):
    assert convert(CSV, params={"charset": ""}).status_code == 400


# Spec: "| Unsupported or malformed `charset` | 400 |"
# Context: a real codec that cannot decode these bytes (AMBIGUITIES T2).
def test_charset_that_cannot_decode_the_body_is_400(convert):
    body = "city,note\nmalm\xf6,caf\xe9\n".encode("iso-8859-1")
    assert convert(body, params={"charset": "utf-8"}).status_code == 400


# Spec: "| Non-tabular content | 400 |"
# Context: bodies with no delimited structure (AMBIGUITIES T6).
def test_non_tabular_content_is_400(convert):
    bodies = [
        b"<html><body>Not a CSV at all</body></html>",
        b'{"name": "ada", "age": 36}',
        b"",
        b"\x00\x01\x02\x03binary",
    ]
    for body in bodies:
        response = convert(body)
        assert response.status_code == 400, body
        assert response.get_json()["ok"] is False


# Spec: "A valid file requires at least one header row and one data row."
# Context: a header with no data row underneath it.
def test_header_without_data_row_is_400(convert):
    assert convert("name,age\n").status_code == 400


# Spec: "A valid file requires at least one header row and one data row."
# Context: exactly one header and one data row is enough.
def test_single_data_row_is_accepted(convert):
    assert convert("name,age\nada,36\n").status_code == 200


# Spec: "/convert returns the same endpoint for the same source URL string."
# Context: repeated conversions of one URL.
def test_same_source_returns_same_endpoint(client, origin):
    source = origin.serve("/stable.csv", CSV)
    first = client.get("/convert", query_string={"source": source}).get_json()
    second = client.get("/convert", query_string={"source": source}).get_json()
    assert first["endpoint"] == second["endpoint"]


# Spec: "/convert returns the same endpoint for the same source URL string."
# Context: different URLs must not collide on one endpoint.
def test_different_sources_return_different_endpoints(client, origin):
    a = origin.serve("/a.csv", CSV)
    b = origin.serve("/b.csv", CSV)
    endpoint_a = client.get("/convert", query_string={"source": a}).get_json()["endpoint"]
    endpoint_b = client.get("/convert", query_string={"source": b}).get_json()["endpoint"]
    assert endpoint_a != endpoint_b


# Spec: "/convert returns the same endpoint for the same source URL string."
# Context: re-converting refreshes the stored data under the same id
# (AMBIGUITIES T8).
def test_reconvert_refreshes_stored_rows(client, origin):
    source = origin.serve("/refresh.csv", "name,age\nada,36\n")
    endpoint = client.get("/convert", query_string={"source": source}).get_json()["endpoint"]
    origin.serve("/refresh.csv", "name,age\ngrace,45\n")
    again = client.get("/convert", query_string={"source": source}).get_json()
    assert again["endpoint"] == endpoint
    assert client.get(endpoint).get_json()["rows"] == [["grace", 45]]
