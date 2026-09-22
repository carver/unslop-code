"""Spec section: Ingestion: `GET /convert`."""

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\n"


# Phrase: "| `source` | yes | URL of the remote CSV file |" -- success case.
def test_convert_accepts_a_source_url(convert):
    response = convert("/simple.csv", SIMPLE)
    assert response.status_code == 200


# Phrase: 'Success (`HTTP 200`): {"ok": true, "endpoint": "/datasets/<id>"}'
def test_convert_success_body_shape(convert):
    response = convert("/shape.csv", SIMPLE)
    payload = response.get_json()
    assert payload["ok"] is True
    assert set(payload) == {"ok", "endpoint"}
    assert payload["endpoint"].startswith("/datasets/")
    assert payload["endpoint"] != "/datasets/"


# Context: the endpoint returned by /convert is directly fetchable.
def test_convert_endpoint_is_usable(convert, client):
    endpoint = convert("/usable.csv", SIMPLE).get_json()["endpoint"]
    follow_up = client.get(endpoint)
    assert follow_up.status_code == 200
    assert follow_up.get_json()["ok"] is True


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
def test_same_source_url_returns_same_endpoint(convert, client, origin):
    first = convert("/stable.csv", SIMPLE).get_json()["endpoint"]
    second = client.get(
        "/convert", query_string={"source": origin.url("/stable.csv")}
    ).get_json()["endpoint"]
    assert first == second


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
# Context: distinct source URLs are distinct datasets.
def test_different_source_urls_return_different_endpoints(convert):
    first = convert("/one.csv", SIMPLE).get_json()["endpoint"]
    second = convert("/two.csv", "x,y\n1,2\n").get_json()["endpoint"]
    assert first != second


# Phrase: "| `charset` | no | Character encoding for decoding CSV bytes. |"
def test_explicit_charset_decodes_bytes(dataset):
    body = "name,city\njosé,münchen\n".encode("cp1252")
    response = dataset("/cp1252.csv", body, params={"charset": "cp1252"})
    assert response.status_code == 200
    assert response.get_json()["rows"][0] == ["josé", "münchen"]


# Phrase: "If omitted, detect encoding from content."
def test_charset_omitted_detects_utf8(dataset):
    response = dataset("/utf8.csv", "name,city\nrené,paris\n".encode("utf-8"))
    assert response.status_code == 200
    assert response.get_json()["rows"][0] == ["rené", "paris"]


# Phrase: "If omitted, detect encoding from content."  (non-UTF-8 input)
def test_charset_omitted_detects_non_utf8(dataset):
    text = "name,note\n" + "".join(
        "row{},naïve café résumé señor\n".format(i) for i in range(40)
    )
    response = dataset("/latin1.csv", text.encode("cp1252"))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["columns"] == ["name", "note"]
    assert "\x00" not in "".join(payload["rows"][0])


# Phrase: "| Missing `source` | 400 |"
def test_missing_source_is_400(client):
    response = client.get("/convert")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Missing `source` | 400 |"  (present but empty)
def test_empty_source_is_400(client):
    response = client.get("/convert", query_string={"source": ""})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Invalid URL | 400 |"
@pytest.mark.parametrize(
    "source",
    [
        "not a url",
        "://missing-scheme",
        "http://",
        "httpx",
        "/relative/path.csv",
        "ftp://example.com/data.csv",
        "file:///etc/passwd",
    ],
)
def test_invalid_url_is_400(client, source):
    response = client.get("/convert", query_string={"source": source})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"
@pytest.mark.parametrize("charset", ["not-a-charset", "utf-99", "!!!", "utf 8 ish"])
def test_unsupported_charset_is_400(client, origin, charset):
    origin.add("/charset.csv", SIMPLE)
    response = client.get(
        "/convert",
        query_string={"source": origin.url("/charset.csv"), "charset": charset},
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"
# Context: a known charset that cannot decode these bytes (see AMBIGUITIES T5).
def test_charset_that_cannot_decode_is_400(client, origin):
    origin.add("/mismatch.csv", "name,city\njosé,münchen\n".encode("cp1252"))
    response = client.get(
        "/convert",
        query_string={"source": origin.url("/mismatch.csv"), "charset": "utf-8"},
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"
# Context: usual spellings/aliases must be accepted, not rejected.
@pytest.mark.parametrize("charset", ["utf-8", "UTF-8", "utf8", "latin-1", "ascii"])
def test_supported_charset_aliases_are_accepted(client, origin, charset):
    origin.add("/ascii.csv", b"a,b\n1,2\n")
    response = client.get(
        "/convert",
        query_string={"source": origin.url("/ascii.csv"), "charset": charset},
    )
    assert response.status_code == 200


# Phrase: "| Source unreachable or remote HTTP error | 404 |"  (unreachable)
def test_unreachable_source_is_404(client, origin):
    response = client.get("/convert", query_string={"source": origin.dead_url()})
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: unresolvable host.
def test_unresolvable_host_is_404(client):
    response = client.get(
        "/convert",
        query_string={"source": "http://datagate-nonexistent.invalid/data.csv"},
    )
    assert response.status_code == 404


# Phrase: "| Source unreachable or remote HTTP error | 404 |"  (remote HTTP error)
@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_remote_http_error_is_404(client, origin, status):
    path = "/err{}.csv".format(status)
    origin.add(path, SIMPLE, status=status)
    response = client.get("/convert", query_string={"source": origin.url(path)})
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "| Non-tabular content | 400 |"  (HTML)
def test_html_content_is_400(client, origin):
    origin.add(
        "/page.html",
        "<html><body><h1>Not a CSV</h1></body></html>",
        content_type="text/html",
    )
    response = client.get("/convert", query_string={"source": origin.url("/page.html")})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Non-tabular content | 400 |"  (JSON)
def test_json_content_is_400(client, origin):
    origin.add(
        "/data.json",
        '{"name": "alice", "age": 30}',
        content_type="application/json",
    )
    response = client.get("/convert", query_string={"source": origin.url("/data.json")})
    assert response.status_code == 400


# Phrase: "| Non-tabular content | 400 |"  (binary)
def test_binary_content_is_400(client, origin):
    origin.add(
        "/blob.bin",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00",
        content_type="application/octet-stream",
    )
    response = client.get("/convert", query_string={"source": origin.url("/blob.bin")})
    assert response.status_code == 400


# Phrase: "| Non-tabular content | 400 |"  (empty body)
def test_empty_content_is_400(client, origin):
    origin.add("/empty.csv", b"")
    response = client.get("/convert", query_string={"source": origin.url("/empty.csv")})
    assert response.status_code == 400


# Phrase: "| Non-tabular content | 400 |"
# Context: prose with no inferable delimiter (see AMBIGUITIES T6).
def test_prose_content_is_400(client, origin):
    origin.add(
        "/prose.txt",
        "hello world\nthis is not a csv at all\njust some words\n",
        content_type="text/plain",
    )
    response = client.get("/convert", query_string={"source": origin.url("/prose.txt")})
    assert response.status_code == 400


# Phrase: "A valid file requires at least one header row and one data row."
def test_header_only_is_400(client, origin):
    origin.add("/header-only.csv", "name,age\n")
    response = client.get(
        "/convert", query_string={"source": origin.url("/header-only.csv")}
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "A valid file requires at least one header row and one data row."
# Context: exactly one data row is enough.
def test_one_header_and_one_data_row_is_valid(dataset):
    response = dataset("/minimal.csv", "a,b\n1,2\n")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]
