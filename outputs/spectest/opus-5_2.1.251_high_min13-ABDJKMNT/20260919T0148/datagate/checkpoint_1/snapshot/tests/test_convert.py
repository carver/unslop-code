"""Spec section: Ingestion: `GET /convert`."""

CSV = "name,age\nada,36\n"


# Phrase: "Success (`HTTP 200`): {"ok": true, "endpoint": "/datasets/<id>"}"
def test_convert_returns_ok_and_dataset_endpoint(client, origin):
    source = origin.serve("/data.csv", CSV)

    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert body["endpoint"].removeprefix("/datasets/")


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
def test_same_source_yields_same_endpoint(client, origin):
    source = origin.serve("/data.csv", CSV)

    first = client.get("/convert", query_string={"source": source}).get_json()
    second = client.get("/convert", query_string={"source": source}).get_json()

    assert first["endpoint"] == second["endpoint"]


# Phrase: "`/convert` returns the same endpoint for the same `source` URL string."
# Context: different source strings are different datasets.
def test_different_sources_yield_different_endpoints(client, origin):
    one = origin.serve("/one.csv", CSV)
    two = origin.serve("/two.csv", "city,pop\noslo,700000\n")

    first = client.get("/convert", query_string={"source": one}).get_json()
    second = client.get("/convert", query_string={"source": two}).get_json()

    assert first["endpoint"] != second["endpoint"]


# Phrase: "The endpoint returned by /convert is immediately queryable."
# Context: the returned endpoint serves the converted dataset.
def test_returned_endpoint_serves_the_dataset(client, origin):
    source = origin.serve("/data.csv", CSV)

    endpoint = client.get("/convert", query_string={"source": source}).get_json()["endpoint"]
    dataset = client.get(endpoint)

    assert dataset.status_code == 200
    assert dataset.get_json()["columns"] == ["name", "age"]


# Phrase: "| Missing `source` | 400 |"
def test_missing_source_is_400(client):
    response = client.get("/convert")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Missing `source` | 400 |" -- context: an empty value is no value.
def test_blank_source_is_400(client):
    assert client.get("/convert", query_string={"source": ""}).status_code == 400


# Phrase: "| Invalid URL | 400 |"
def test_unparseable_source_is_400(client):
    for source in ["not a url", "http://", "://missing-scheme", "ftp://example.com/x.csv"]:
        response = client.get("/convert", query_string={"source": source})
        assert response.status_code == 400, source


# Phrase: "| Unsupported or malformed `charset` | 400 |"
def test_unknown_charset_is_400(client, origin):
    source = origin.serve("/data.csv", CSV)

    response = client.get("/convert", query_string={"source": source, "charset": "klingon-9"})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "| Unsupported or malformed `charset` | 400 |"
# Context: a known codec that cannot decode the fetched bytes (see AMBIGUITIES T4).
def test_charset_that_cannot_decode_the_bytes_is_400(client, origin):
    source = origin.serve("/data.csv", "name,city\nada,münchen\n".encode("utf-8"))

    response = client.get("/convert", query_string={"source": source, "charset": "ascii"})

    assert response.status_code == 400


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
def test_remote_http_error_is_404(client, origin):
    source = origin.serve("/boom.csv", "server exploded", status=500)

    assert client.get("/convert", query_string={"source": source}).status_code == 404


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
def test_remote_404_is_404(client, origin):
    assert (
        client.get("/convert", query_string={"source": origin.url("/nope.csv")}).status_code
        == 404
    )


# Phrase: "| Source unreachable or remote HTTP error | 404 |"
# Context: connection failures, not just HTTP status codes.
def test_unreachable_host_is_404(client):
    source = "http://127.0.0.1:9/unreachable.csv"

    response = client.get("/convert", query_string={"source": source})

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "| Non-tabular content | 400 |"
def test_html_content_is_400(client, origin):
    source = origin.serve("/page.html", "<!DOCTYPE html><html><body>hi</body></html>")

    assert client.get("/convert", query_string={"source": source}).status_code == 400


# Phrase: "| Non-tabular content | 400 |"
def test_json_content_is_400(client, origin):
    source = origin.serve("/data.json", '{"name": "ada", "age": 36}')

    assert client.get("/convert", query_string={"source": source}).status_code == 400


# Phrase: "| Non-tabular content | 400 |" -- context: no inferable delimiter (AMBIGUITIES T3).
def test_prose_without_delimiters_is_400(client, origin):
    source = origin.serve("/notes.txt", "just some prose\nwith another line\n")

    assert client.get("/convert", query_string={"source": source}).status_code == 400
