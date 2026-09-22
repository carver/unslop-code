"""Spec section: Maximum Source Size -- the `MAX_SOURCE_SIZE` ceiling on ingestion."""

import pytest

from helpers import post_upload

CSV = "name,age\nada,36\ngrace,45\n"
CSV_BYTES = len(CSV.encode("utf-8"))


def convert(client, source):
    return client.get("/convert", query_string={"source": source})


# Phrase: "file size `= limit` accepted." / "Enforced for `/convert`"
def test_convert_accepts_a_source_exactly_at_the_limit(settings_client, origin):
    client = settings_client(MAX_SOURCE_SIZE=str(CSV_BYTES))
    source = origin.serve("/data.csv", CSV)

    response = convert(client, source)

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# Phrase: "file size `> limit` => `HTTP 400` with standard envelope."
def test_convert_rejects_a_source_one_byte_over_the_limit(settings_client, origin):
    client = settings_client(MAX_SOURCE_SIZE=str(CSV_BYTES - 1))
    source = origin.serve("/data.csv", CSV)

    response = convert(client, source)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"]


# Phrase: "file size `> limit` => `HTTP 400` with standard envelope."
# Context: the rejected source is not stored, so its dataset stays unknown.
def test_a_rejected_source_is_not_stored(settings_client, origin):
    client = settings_client(MAX_SOURCE_SIZE="1")
    source = origin.serve("/data.csv", CSV)
    convert(client, source)

    from datagate_core.store import dataset_id

    assert client.get(f"/datasets/{dataset_id(source)}").status_code == 404


# Phrase: "Enforced for ... `/upload`" / "file size `= limit` accepted."
def test_upload_accepts_a_payload_exactly_at_the_limit(settings_client):
    client = settings_client(MAX_SOURCE_SIZE=str(CSV_BYTES))

    response = post_upload(client, CSV)

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# Phrase: "Enforced for ... `/upload`" / "file size `> limit` => `HTTP 400`"
def test_upload_rejects_a_payload_over_the_limit(settings_client):
    client = settings_client(MAX_SOURCE_SIZE=str(CSV_BYTES - 1))

    response = post_upload(client, CSV)

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": response.get_json()["error"]}
    assert response.get_json()["error"]


# Phrase: "Enforced for ... `/upload`"
# Context: the multipart framing is not part of the file size (AMBIGUITIES T62).
def test_upload_measures_the_part_not_the_whole_request_body(settings_client):
    client = settings_client(MAX_SOURCE_SIZE=str(CSV_BYTES))

    response = post_upload(client, CSV, filename="a-very-long-file-name-indeed.csv")

    assert response.status_code == 200


# Phrase: "unset limit means no max."
def test_no_limit_accepts_any_size(settings_client, origin):
    client = settings_client()
    body = "name,value\n" + "".join(f"row{value},{value}\n" for value in range(5000))
    source = origin.serve("/big.csv", body)

    assert convert(client, source).status_code == 200


# Phrase: "unset limit means no max."
# Context: the same holds for `/upload`.
def test_no_limit_accepts_any_upload(settings_client):
    client = settings_client()

    assert post_upload(client, "name,value\n" + "x,1\n" * 10000).status_code == 200


# Phrase: "file size `> limit`"
# Context: a limit of zero admits nothing a parser would accept.
def test_a_zero_limit_rejects_any_non_empty_payload(settings_client):
    client = settings_client(MAX_SOURCE_SIZE="0")

    assert post_upload(client, CSV).status_code == 400


# Phrase: "Enforced for `/convert`"
# Context: the limit is read at startup, so it applies to every later request.
@pytest.mark.parametrize("size, status", [(CSV_BYTES, 200), (CSV_BYTES - 1, 400)])
def test_the_limit_applies_to_every_request(settings_client, origin, size, status):
    client = settings_client(MAX_SOURCE_SIZE=str(size))
    source = origin.serve("/data.csv", CSV)

    for _ in range(2):
        assert convert(client, source).status_code == status


# Phrase: "Enforced for `/convert`"
# Context: a cache hit downloads nothing, so there is no file to measure
# (AMBIGUITIES T63); with caching off, every request is measured again.
def test_re_download_is_measured_when_caching_is_off(settings_client, origin):
    client = settings_client(MAX_SOURCE_SIZE=str(CSV_BYTES), CACHE_ENABLED="off")
    source = origin.serve("/data.csv", CSV)
    assert convert(client, source).status_code == 200

    origin.serve("/data.csv", CSV + "alan,41\n")

    assert convert(client, source).status_code == 400


# Phrase: "file size `> limit` => `HTTP 400` with standard envelope."
# Context: the message says what was measured against what.
def test_the_error_message_reports_the_limit(settings_client):
    client = settings_client(MAX_SOURCE_SIZE="4")

    assert "4" in post_upload(client, CSV).get_json()["error"]
