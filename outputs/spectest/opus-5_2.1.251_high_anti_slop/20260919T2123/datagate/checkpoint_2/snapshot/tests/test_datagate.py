"""End-to-end tests for the datagate HTTP service."""

import pytest

from csv_parsing import infer_value


def convert(client, base_url, name, **params):
    return client.get("/convert", query_string={"source": f"{base_url}/{name}", **params})


def load(client, base_url, name, **params):
    """Convert a fixture and return the payload of its dataset endpoint."""
    endpoint = convert(client, base_url, name, **params).get_json()["endpoint"]
    return client.get(endpoint).get_json()


def read(client, base_url, name, **controls):
    """Convert a fixture and read its dataset endpoint with the given control parameters."""
    endpoint = convert(client, base_url, name).get_json()["endpoint"]
    return client.get(endpoint, query_string=controls)


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


def test_default_page_holds_the_first_hundred_rows(client, base_url):
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


def test_total_counts_rows_before_pagination(client, base_url):
    payload = read(client, base_url, "wide.csv", _size=5, _offset=10).get_json()
    assert payload["total"] == 150
    assert len(payload["rows"]) == 5


def test_size_limits_rows_and_offset_skips_them(client, base_url):
    payload = read(client, base_url, "wide.csv", _size=3, _offset=2).get_json()
    assert payload["rows"] == [[2, "row2"], [3, "row3"], [4, "row4"]]


def test_size_beyond_the_row_count_returns_everything(client, base_url):
    assert len(read(client, base_url, "wide.csv", _size=1000).get_json()["rows"]) == 150


def test_offset_beyond_the_row_count_returns_no_rows(client, base_url):
    payload = read(client, base_url, "wide.csv", _offset=500).get_json()
    assert payload["rows"] == []
    assert payload["total"] == 150


@pytest.mark.parametrize(
    "controls",
    [
        {"_size": "0"},
        {"_size": "-1"},
        {"_size": "2.5"},
        {"_size": "many"},
        {"_size": ""},
        {"_offset": "-1"},
        {"_offset": "later"},
        {"_offset": ""},
    ],
)
def test_bad_pagination_is_rejected(client, base_url, controls):
    response = read(client, base_url, "wide.csv", **controls)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_sort_orders_ascending(client, base_url):
    payload = read(client, base_url, "basic.csv", _sort="age").get_json()
    assert [row[0] for row in payload["rows"]] == ["Ada", "Grace"]


def test_sort_desc_orders_descending(client, base_url):
    payload = read(client, base_url, "basic.csv", _sort_desc="age").get_json()
    assert [row[0] for row in payload["rows"]] == ["Grace", "Ada"]


def test_sort_desc_wins_over_sort(client, base_url):
    payload = read(client, base_url, "basic.csv", _sort="age", _sort_desc="age").get_json()
    assert [row[0] for row in payload["rows"]] == ["Grace", "Ada"]


@pytest.mark.parametrize("direction", ["_sort", "_sort_desc"])
def test_sorting_is_stable_within_ties(client, base_url, direction):
    payload = read(client, base_url, "ties.csv", **{direction: "team"}).get_json()
    tied = [row[1] for row in payload["rows"] if row[0] == "blue"]
    assert tied == ["ada", "alan"]


def test_sorting_happens_before_pagination(client, base_url):
    payload = read(client, base_url, "wide.csv", _sort_desc="n", _size=3).get_json()
    assert payload["rows"] == [[149, "row149"], [148, "row148"], [147, "row147"]]


def test_sorting_a_column_of_mixed_types(client, base_url):
    payload = read(client, base_url, "mixed.csv", _sort="score").get_json()
    assert payload["rows"] == [["Alan", 2], ["Ada", 7], ["Grace", "n/a"]]


@pytest.mark.parametrize("controls", [{"_sort": ""}, {"_sort": "nope"}, {"_sort_desc": "nope"}])
def test_bad_sort_column_is_rejected(client, base_url, controls):
    response = read(client, base_url, "basic.csv", **controls)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_default_shape_is_lists(client, base_url):
    payload = read(client, base_url, "basic.csv", _shape="lists").get_json()
    assert payload["rows"][0] == ["Ada", 36, 9.5, "08:30"]


def test_objects_shape_keys_rows_by_column_and_adds_rowid(client, base_url):
    payload = read(client, base_url, "basic.csv", _shape="objects").get_json()
    assert payload["rows"][1] == {
        "rowid": 2,
        "name": "Grace",
        "age": 45,
        "score": 8.25,
        "start": "9:15",
    }
    assert payload["columns"] == ["name", "age", "score", "start"]


def test_rowid_follows_the_source_row_through_sorting_and_pagination(client, base_url):
    payload = read(
        client, base_url, "wide.csv", _shape="objects", _sort_desc="n", _size=2, _offset=1
    ).get_json()
    assert [row["rowid"] for row in payload["rows"]] == [149, 148]


def test_rowid_can_be_hidden(client, base_url):
    payload = read(client, base_url, "basic.csv", _shape="objects", _rowid="hide").get_json()
    assert payload["rows"][0] == {"name": "Ada", "age": 36, "score": 9.5, "start": "08:30"}


def test_total_can_be_hidden(client, base_url):
    assert "total" not in read(client, base_url, "basic.csv", _total="hide").get_json()


@pytest.mark.parametrize(
    "controls",
    [
        {"_shape": "tuples"},
        {"_shape": ""},
        {"_rowid": "show"},
        {"_rowid": ""},
        {"_total": "show"},
        {"_total": "hidden"},
    ],
)
def test_bad_shape_and_toggle_values_are_rejected(client, base_url, controls):
    response = read(client, base_url, "basic.csv", **controls)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize(
    "controls",
    [
        {"_size": ["1", "2"]},
        {"_offset": ["0", "1"]},
        {"_shape": ["lists", "objects"]},
        {"_sort": ["name", "age"]},
        {"_sort_desc": ["name", "age"]},
        {"_rowid": ["hide", "hide"]},
        {"_total": ["hide", "hide"]},
    ],
)
def test_repeated_control_parameters_are_rejected(client, base_url, controls):
    response = read(client, base_url, "basic.csv", **controls)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
