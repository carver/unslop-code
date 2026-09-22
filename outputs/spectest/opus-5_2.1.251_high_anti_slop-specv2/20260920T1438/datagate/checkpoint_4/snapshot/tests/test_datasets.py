"""Query behaviour of ``GET /datasets/<id>``."""

import pytest

TABLE = b"name,score,start\nada,36.5,08:30\nlin,7,9:15\n"


@pytest.fixture
def dataset(client, convert):
    """Convert ``TABLE`` and return the parsed dataset response body."""

    def load(payload: bytes = TABLE, **params):
        endpoint = convert(payload, **params).get_json()["endpoint"]
        return client.get(endpoint).get_json()

    return load


def test_columns_and_rows_follow_source_order(dataset):
    body = dataset()
    assert body["columns"] == ["name", "score", "start"]
    assert body["rows"][0] == ["ada", 36.5, "08:30"]


def test_numbers_are_json_numbers_and_times_stay_text(dataset):
    assert dataset()["rows"][1] == ["lin", 7, "9:15"]


def test_query_ms_is_present_and_non_negative(dataset):
    assert dataset()["query_ms"] >= 0


def test_rows_are_capped_at_one_hundred(dataset):
    payload = b"n\n" + b"".join(b"%d\n" % index for index in range(250))
    body = dataset(payload)
    assert len(body["rows"]) == 100
    assert body["rows"][0] == [0]


def test_unknown_id_is_not_found(client):
    response = client.get("/datasets/deadbeef")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("delimiter", [b",", b";", b"\t"])
def test_delimiters_are_inferred(dataset, delimiter):
    payload = delimiter.join([b"city", b"pop\n"]) + delimiter.join([b"oslo", b"700\n"])
    body = dataset(payload)
    assert body["columns"] == ["city", "pop"]
    assert body["rows"] == [["oslo", 700]]


def test_quoted_delimiters_stay_inside_the_field(dataset):
    body = dataset(b'name,note\n"ada","born, 1815"\n')
    assert body["rows"] == [["ada", "born, 1815"]]


def test_declared_charset_decodes_the_payload(dataset):
    body = dataset("city\nMünchen\n".encode("cp1252"), charset="cp1252")
    assert body["rows"] == [["München"]]


def test_utf8_is_detected_without_a_charset(dataset):
    body = dataset("city\n東京\n".encode("utf-8"))
    assert body["rows"] == [["東京"]]


def test_ambiguous_single_byte_content_falls_back_to_latin1(dataset):
    body = dataset("city\nBærum\n".encode("latin-1"))
    assert body["rows"] == [["Bærum"]]


def test_utf8_bom_is_stripped_from_the_first_column(dataset):
    body = dataset("city,pop\noslo,7\n".encode("utf-8-sig"))
    assert body["columns"] == ["city", "pop"]
