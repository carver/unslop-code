"""End-to-end tests for the datagate HTTP service."""

import pytest

from csv_parsing import infer_value


def convert(client, base_url, name, **params):
    return client.get("/convert", query_string={"source": f"{base_url}/{name}", **params})


def load(client, base_url, name, **params):
    """Convert a fixture and return the payload of its dataset endpoint."""
    endpoint = convert(client, base_url, name, **params).get_json()["endpoint"]
    return client.get(endpoint).get_json()


def test_convert_returns_dataset_endpoint(client, base_url):
    payload = convert(client, base_url, "basic.csv").get_json()
    assert payload["ok"] is True
    assert payload["endpoint"].startswith("/datasets/")


def test_same_source_maps_to_same_endpoint(client, base_url):
    first = convert(client, base_url, "basic.csv").get_json()["endpoint"]
    second = convert(client, base_url, "basic.csv").get_json()["endpoint"]
    assert first == second


def test_dataset_preserves_order_and_types(client, base_url):
    payload = load(client, base_url, "basic.csv")
    assert payload["columns"] == ["name", "age", "score", "start"]
    assert payload["rows"] == [["Ada", 36, 9.5, "08:30"], ["Grace", 45, 8.25, "9:15"]]
    assert payload["query_ms"] >= 0


@pytest.mark.parametrize(
    ("name", "columns"),
    [("semicolon.csv", ["city", "population"]), ("tabbed.tsv", ["product", "price"])],
)
def test_delimiter_is_inferred(client, base_url, name, columns):
    assert load(client, base_url, name)["columns"] == columns


def test_charset_is_detected_when_absent(client, base_url):
    assert load(client, base_url, "latin1.csv")["rows"][0] == ["José", "Málaga"]


def test_single_byte_encoding_does_not_hide_the_delimiter(client, base_url):
    """Detection alone ranks this cp1252 sample as a multi-byte codec, which swallows the ';'."""
    payload = load(client, base_url, "latin1_semicolon.csv")
    assert payload["columns"] == ["name", "city"]
    assert payload["rows"] == [["José", "Málaga"], ["René", "Nîmes"]]


def test_byte_order_mark_is_stripped_from_the_first_column(client, base_url):
    assert load(client, base_url, "bom.csv")["columns"] == ["name", "city"]


def test_explicit_charset_is_used(client, base_url):
    payload = load(client, base_url, "latin1.csv", charset="cp1252")
    assert payload["rows"][1] == ["René", "Nîmes"]


def test_rows_are_capped_at_one_hundred(client, base_url):
    payload = load(client, base_url, "wide.csv")
    assert len(payload["rows"]) == 100
    assert payload["rows"][0] == [0, "row0"]


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({}, 400),
        ({"source": "not-a-url"}, 400),
        ({"source": "http://127.0.0.1:1/x.csv"}, 404),
    ],
)
def test_convert_rejects_bad_requests(client, params, status):
    response = client.get("/convert", query_string=params)
    assert response.status_code == status
    assert response.get_json()["ok"] is False


def test_unknown_charset_is_rejected(client, base_url):
    assert convert(client, base_url, "basic.csv", charset="not-a-charset").status_code == 400


def test_charset_that_cannot_decode_is_rejected(client, base_url):
    assert convert(client, base_url, "latin1.csv", charset="utf-8").status_code == 400


def test_remote_http_error_is_reported_as_missing(client, base_url):
    assert convert(client, base_url, "absent.csv").status_code == 404


@pytest.mark.parametrize("name", ["page.html", "header_only.csv"])
def test_non_tabular_content_is_rejected(client, base_url, name):
    assert convert(client, base_url, name).status_code == 400


def test_unknown_dataset_and_route_return_json_404(client):
    for path in ("/datasets/deadbeef", "/nope"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.get_json()["ok"] is False


def test_cors_headers_are_present(client):
    assert client.get("/nope").headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [("7", 7), ("-2.5", -2.5), ("08:30", "08:30"), ("12:00:59", "12:00:59"), ("n/a", "n/a")],
)
def test_type_inference(cell, expected):
    assert infer_value(cell) == expected
