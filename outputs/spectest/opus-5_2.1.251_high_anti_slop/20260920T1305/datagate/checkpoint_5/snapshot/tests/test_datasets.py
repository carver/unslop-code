"""Tests for querying stored datasets, including parsing and type inference."""

import pytest


def convert(client, source):
    return client.get("/convert", query_string={"source": source}).json["endpoint"]


def test_dataset_returns_columns_and_rows_in_source_order(client, serve):
    source = serve("a.csv", b"name,age,city\nada,36,london\nalan,41,wilmslow\n")

    response = client.get(convert(client, source))

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["columns"] == ["name", "age", "city"]
    assert response.json["rows"] == [["ada", 36, "london"], ["alan", 41, "wilmslow"]]
    assert response.json["query_ms"] >= 0


def test_numbers_and_time_like_values(client, serve):
    source = serve("a.csv", b"start,count,ratio,label\n08:30,7,-2.5,9:15 am\n")

    rows = client.get(convert(client, source)).json["rows"]

    assert rows == [["08:30", 7, -2.5, "9:15 am"]]


def test_rows_are_capped_at_one_hundred(client, serve):
    body = b"n\tsquare\n" + b"".join(
        f"{n}\t{n * n}\n".encode() for n in range(150)
    )
    source = serve("a.tsv", body)

    rows = client.get(convert(client, source)).json["rows"]

    assert len(rows) == 100
    assert rows[0] == [0, 0]


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_delimiters_are_inferred(client, serve, delimiter):
    body = f"name{delimiter}age\nada{delimiter}36\n".encode()
    source = serve(f"a{ord(delimiter)}.csv", body)

    response = client.get(convert(client, source))

    assert response.json["columns"] == ["name", "age"]
    assert response.json["rows"] == [["ada", 36]]


def test_declared_charset_is_used_for_decoding(client, serve):
    source = serve("latin.csv", "name;city\nada;münchen\n".encode("latin-1"))

    endpoint = client.get(
        "/convert", query_string={"source": source, "charset": "latin-1"}
    ).json["endpoint"]

    assert client.get(endpoint).json["rows"] == [["ada", "münchen"]]


def test_encoding_is_detected_when_charset_is_omitted(client, serve):
    source = serve("utf16.csv", "name,city\nada,münchen\n".encode("utf-16"))

    assert client.get(convert(client, source)).json["rows"] == [["ada", "münchen"]]


def test_unknown_dataset_is_not_found(client):
    response = client.get("/datasets/0123456789abcdef")

    assert response.status_code == 404
    assert response.json["ok"] is False
