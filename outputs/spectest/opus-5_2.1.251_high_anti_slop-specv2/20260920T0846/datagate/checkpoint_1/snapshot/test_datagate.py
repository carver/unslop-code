"""End-to-end tests for the datagate HTTP API and CSV pipeline."""

import pytest
import requests

from app import create_app
from errors import ApiError
from tabular import decode, detect_delimiter, infer_value

SAMPLE_CSV = b"name,start,score,ratio\nAda,08:30,42,1.5\nGrace,9:15,7,0.25\n"


@pytest.fixture
def client(monkeypatch):
    """A test client whose fetches are served from an in-test payload table."""
    payloads = {"https://example.com/data.csv": SAMPLE_CSV}

    def fake_fetch(url):
        if url not in payloads:
            raise ApiError(f"Source unreachable: {url}", 404)
        return payloads[url]

    monkeypatch.setattr("app.fetch", fake_fetch)
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    client.payloads = payloads
    return client


def convert(client, **params):
    return client.get("/convert", query_string=params)


def test_convert_returns_stable_endpoint(client):
    first = convert(client, source="https://example.com/data.csv")
    second = convert(client, source="https://example.com/data.csv")

    assert first.status_code == 200
    assert first.json["ok"] is True
    assert first.json["endpoint"] == second.json["endpoint"]


def test_dataset_preserves_order_and_infers_types(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    response = client.get(endpoint)

    assert response.status_code == 200
    assert response.json["columns"] == ["name", "start", "score", "ratio"]
    assert response.json["rows"] == [["Ada", "08:30", 42, 1.5], ["Grace", "9:15", 7, 0.25]]
    assert response.json["query_ms"] >= 0


def test_rows_are_capped_at_one_hundred_by_default(client):
    rows = "\n".join(f"row{index};{index}" for index in range(250))
    client.payloads["https://example.com/big.csv"] = f"label;value\n{rows}\n".encode()
    endpoint = convert(client, source="https://example.com/big.csv").json["endpoint"]

    assert len(client.get(endpoint).json["rows"]) == 100
    assert len(client.get(endpoint, query_string={"limit": 5}).json["rows"]) == 5


def test_explicit_charset_decodes_payload(client):
    client.payloads["https://example.com/cp1252.csv"] = "city,temp\nMünchen,21\n".encode("cp1252")

    response = convert(client, source="https://example.com/cp1252.csv", charset="cp1252")

    assert client.get(response.json["endpoint"]).json["rows"] == [["München", 21]]


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({}, 400),
        ({"source": "not-a-url"}, 400),
        ({"source": "https://example.com/data.csv", "charset": "klingon-8"}, 400),
        ({"source": "https://example.com/missing.csv"}, 404),
    ],
)
def test_convert_errors(client, params, status):
    response = convert(client, **params)

    assert response.status_code == status
    assert response.json["ok"] is False
    assert response.json["error"]


def test_non_tabular_source_is_rejected(client):
    client.payloads["https://example.com/page.html"] = b"<html>\n<body>hello</body>\n</html>\n"

    assert convert(client, source="https://example.com/page.html").status_code == 400


def test_single_row_source_is_rejected(client):
    client.payloads["https://example.com/header.csv"] = b"name,score\n"

    assert convert(client, source="https://example.com/header.csv").status_code == 400


def test_unknown_dataset_and_route_return_json_404(client):
    for path in ("/datasets/deadbeef", "/nope"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json["ok"] is False


def test_responses_carry_cors_headers(client):
    assert client.get("/nope").headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_delimiters_are_detected(delimiter):
    text = delimiter.join(["a", "b", "c"]) + "\n" + delimiter.join(["1", "2", "3"])

    assert detect_delimiter(text) == delimiter


@pytest.mark.parametrize(
    ("field", "expected"),
    [("42", 42), ("-3", -3), ("1.5", 1.5), ("2e3", 2000.0), ("08:30", "08:30"), ("n/a", "n/a")],
)
def test_value_inference(field, expected):
    assert infer_value(field) == expected


def test_encoding_detection_falls_back_to_latin1():
    assert decode("café".encode("utf-8")) == "café"
    assert decode("café".encode("utf-8-sig")) == "café"
    assert decode("café".encode("latin-1")) == "café"


def test_transport_failure_reports_missing_source(monkeypatch):
    def explode(url, timeout):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr("fetcher.requests.get", explode)
    client = create_app().test_client()

    assert convert(client, source="https://example.invalid/x.csv").status_code == 404
