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


def big_dataset(client):
    """Convert a 250 row source and return its dataset endpoint."""
    rows = "\n".join(f"row{index};{index}" for index in range(250))
    client.payloads["https://example.com/big.csv"] = f"label;value\n{rows}\n".encode()
    return convert(client, source="https://example.com/big.csv").json["endpoint"]


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
    assert response.json["total"] == 2
    assert response.json["query_ms"] >= 0


def test_rows_are_capped_at_one_hundred_by_default(client):
    endpoint = big_dataset(client)

    assert len(client.get(endpoint).json["rows"]) == 100
    assert len(client.get(endpoint, query_string={"_size": 5}).json["rows"]) == 5


def test_size_beyond_the_row_count_returns_everything(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    assert len(client.get(endpoint, query_string={"_size": 500}).json["rows"]) == 2


def test_offset_skips_rows_and_total_ignores_pagination(client):
    endpoint = big_dataset(client)

    response = client.get(endpoint, query_string={"_offset": 248, "_size": 10})

    assert response.json["rows"] == [["row248", 248], ["row249", 249]]
    assert response.json["total"] == 250


def test_offset_past_the_end_returns_no_rows(client):
    endpoint = big_dataset(client)

    assert client.get(endpoint, query_string={"_offset": 400}).json["rows"] == []


def test_total_counts_rows_before_pagination(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    assert client.get(endpoint, query_string={"_size": 1}).json["total"] == 2


def test_sorting_runs_before_pagination(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    ascending = client.get(endpoint, query_string={"_sort": "score", "_size": 1})
    descending = client.get(endpoint, query_string={"_sort_desc": "score", "_size": 1})

    assert ascending.json["rows"] == [["Grace", "9:15", 7, 0.25]]
    assert descending.json["rows"] == [["Ada", "08:30", 42, 1.5]]


def test_descending_sort_wins_over_ascending(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    response = client.get(endpoint, query_string={"_sort": "name", "_sort_desc": "name"})

    assert [row[0] for row in response.json["rows"]] == ["Grace", "Ada"]


def test_sorting_keeps_tied_rows_in_source_order(client):
    client.payloads["https://example.com/ties.csv"] = (
        b"name,team\nAda,blue\nGrace,blue\nKay,amber\n"
    )
    endpoint = convert(client, source="https://example.com/ties.csv").json["endpoint"]

    for params in ({"_sort": "team"}, {"_sort_desc": "team"}):
        response = client.get(endpoint, query_string=params)
        assert [row[0] for row in response.json["rows"] if row[1] == "blue"] == ["Ada", "Grace"]


def test_object_shape_carries_rowid(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    response = client.get(endpoint, query_string={"_shape": "objects", "_size": 1})

    assert response.json["rows"] == [
        {"rowid": 2, "name": "Ada", "start": "08:30", "score": 42, "ratio": 1.5}
    ]
    assert "rowid" not in response.json["columns"]


def test_rowid_follows_the_row_through_sorting(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    response = client.get(endpoint, query_string={"_shape": "objects", "_sort_desc": "name"})

    assert [row["rowid"] for row in response.json["rows"]] == [3, 2]


def test_visibility_toggles_drop_fields(client):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    hidden = client.get(endpoint, query_string={"_shape": "objects", "_rowid": "hide"})
    totalless = client.get(endpoint, query_string={"_total": "hide"})

    assert all("rowid" not in row for row in hidden.json["rows"])
    assert "total" not in totalless.json


@pytest.mark.parametrize(
    "params",
    [
        {"_size": 0},
        {"_size": -1},
        {"_size": "many"},
        {"_offset": -1},
        {"_offset": "1.5"},
        {"_shape": "tuples"},
        {"_rowid": "show"},
        {"_total": ""},
        {"_sort": ""},
        {"_sort": "nope"},
        {"_sort_desc": "nope"},
    ],
)
def test_control_parameter_errors(client, params):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    response = client.get(endpoint, query_string=params)

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert response.json["error"]


@pytest.mark.parametrize(
    "name", ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]
)
def test_repeated_control_parameters_are_rejected(client, name):
    endpoint = convert(client, source="https://example.com/data.csv").json["endpoint"]

    assert client.get(f"{endpoint}?{name}=1&{name}=1").status_code == 400


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
