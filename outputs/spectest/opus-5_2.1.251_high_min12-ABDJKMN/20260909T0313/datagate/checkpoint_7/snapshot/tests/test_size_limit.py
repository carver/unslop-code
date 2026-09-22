"""Spec section: Maximum Source Size.

    Enforced for `/convert` and `/upload`:
    - file size `= limit` accepted.
    - file size `> limit` => `HTTP 400` with standard envelope.
    - unset limit means no max.
"""

import pytest

import datagate

SIMPLE = "name,age\nalice,30\nbob,41\n"


def body_of(size):
    """A valid two-column CSV whose encoded length is exactly `size` bytes."""
    assert size >= 8, size
    text = "a,b\nx," + "y" * (size - 7) + "\n"
    assert len(text.encode("utf-8")) == size, len(text)
    return text


# Phrase: "file size `= limit` accepted." (context: /convert)
def test_convert_accepts_size_exactly_at_the_limit(configure, client, origin):
    body = body_of(64)
    assert configure(MAX_SOURCE_SIZE="64") is None
    origin.add("/size-eq.csv", body)
    response = client.get("/convert", query_string={"source": origin.url("/size-eq.csv")})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["ok"] is True


# Phrase: "file size `= limit` accepted." -- anything under the limit too.
def test_convert_accepts_size_below_the_limit(configure, client, origin):
    assert configure(MAX_SOURCE_SIZE="1000") is None
    origin.add("/size-lt.csv", SIMPLE)
    response = client.get("/convert", query_string={"source": origin.url("/size-lt.csv")})
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "file size `> limit` => `HTTP 400` with standard envelope." (/convert)
def test_convert_rejects_one_byte_over_the_limit(configure, client, origin):
    body = body_of(65)
    assert configure(MAX_SOURCE_SIZE="64") is None
    origin.add("/size-gt.csv", body)
    response = client.get("/convert", query_string={"source": origin.url("/size-gt.csv")})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"].strip()


# Phrase: "Enforced for `/convert` and `/upload`" -- an oversized source is not
# stored, so its dataset endpoint does not exist afterwards.
def test_oversized_convert_stores_nothing(configure, client, origin):
    assert configure(MAX_SOURCE_SIZE="10") is None
    source = origin.add("/size-nostore.csv", SIMPLE)
    assert client.get("/convert", query_string={"source": source}).status_code == 400
    identifier = datagate.dataset_id(source)
    assert client.get("/datasets/{}".format(identifier)).status_code == 404


# Phrase: "file size `= limit` accepted." (context: /upload)
def test_upload_accepts_size_exactly_at_the_limit(configure, client, upload):
    body = body_of(48)
    assert configure(MAX_SOURCE_SIZE="48") is None
    response = upload(body)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["ok"] is True


# Phrase: "file size `> limit` => `HTTP 400` with standard envelope." (/upload)
def test_upload_rejects_one_byte_over_the_limit(configure, client, upload):
    body = body_of(49)
    assert configure(MAX_SOURCE_SIZE="48") is None
    response = upload(body)
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"].strip()


# Phrase: "file size" is the size of the uploaded file, not of the whole
# multipart request body (AMBIGUITIES T69): the framing pushes the request well
# past the limit while the file itself is exactly at it.
def test_upload_limit_measures_the_file_part_only(configure, client, upload):
    body = body_of(40)
    assert configure(MAX_SOURCE_SIZE="40") is None
    response = upload(body, filename="a-fairly-long-file-name-for-padding.csv")
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "unset limit means no max." (context: /convert)
def test_unset_limit_allows_any_convert_size(configure, client, origin):
    assert configure() is None
    assert datagate.MAX_SOURCE_SIZE is None
    origin.add("/size-unset.csv", body_of(20000))
    response = client.get("/convert",
                          query_string={"source": origin.url("/size-unset.csv")})
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "unset limit means no max." (context: /upload)
def test_unset_limit_allows_any_upload_size(configure, client, upload):
    assert configure() is None
    response = upload(body_of(20000))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "`MAX_SOURCE_SIZE` | integer bytes" -- zero is a real limit, not a
# sentinel for "no max" (AMBIGUITIES T70).
def test_zero_limit_rejects_a_non_empty_source(configure, client, upload):
    assert configure(MAX_SOURCE_SIZE="0") is None
    assert upload(SIMPLE).status_code == 400


# Phrase: "Enforced for `/convert` and `/upload`" -- the limit comes from the
# config file just as well as from the environment.
def test_limit_from_the_config_file_is_enforced(configure, config_file, client, upload):
    assert configure(DATAGATE_CONFIG=config_file("MAX_SOURCE_SIZE=8\n")) is None
    assert datagate.MAX_SOURCE_SIZE == 8
    assert upload(SIMPLE).status_code == 400


# Phrase: "Enforced for `/convert` and `/upload`" -- and nowhere else: a
# dataset that was ingested under a larger limit stays queryable when the limit
# is later lowered, because /datasets is not gated on source size.
def test_limit_does_not_gate_dataset_reads(configure, client, upload):
    assert configure(MAX_SOURCE_SIZE="10000") is None
    response = upload(SIMPLE)
    endpoint = response.get_json()["endpoint"]
    assert configure(MAX_SOURCE_SIZE="1") is None
    assert client.get(endpoint).status_code == 200


# Phrase: "`> limit` => `HTTP 400`" -- the rejection is about size, so an
# oversized source that is also unparseable is still a 400.
@pytest.mark.parametrize("payload", [b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09",
                                     "not,a\nvalid csv table"])
def test_oversized_is_400_whatever_the_content(configure, client, upload, payload):
    assert configure(MAX_SOURCE_SIZE="2") is None
    response = upload(payload)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
