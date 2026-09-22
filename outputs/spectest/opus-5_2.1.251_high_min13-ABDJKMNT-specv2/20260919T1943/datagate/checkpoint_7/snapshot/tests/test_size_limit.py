"""Spec section: Maximum Source Size."""

import io

from conftest import SIMPLE_CSV, SOURCE_URL

from datagate_app.store import dataset_id

CSV_BYTES = SIMPLE_CSV.encode()
EXACT = str(len(CSV_BYTES))
ONE_SHORT = str(len(CSV_BYTES) - 1)
GENEROUS = str(len(CSV_BYTES) + 1000)


def convert(client, source=SOURCE_URL):
    return client.get("/convert", query_string={"source": source})


def post_upload(client, data, filename="data.csv"):
    payload = {"file": (io.BytesIO(data), filename)}
    return client.post("/upload", data=payload, content_type="multipart/form-data")


# Phrase: "file size `= limit` accepted." (context: /convert)
def test_convert_accepts_a_source_exactly_at_the_limit(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(MAX_SOURCE_SIZE=EXACT)

    assert convert(client).status_code == 200


# Phrase: "file size `= limit` accepted." (context: /upload)
def test_upload_accepts_a_file_exactly_at_the_limit(configured):
    client = configured(MAX_SOURCE_SIZE=EXACT)

    assert post_upload(client, CSV_BYTES).status_code == 200


# Phrase: "file size `> limit` => `HTTP 400`" (context: /convert)
def test_convert_rejects_a_source_over_the_limit(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(MAX_SOURCE_SIZE=ONE_SHORT)

    assert convert(client).status_code == 400


# Phrase: "file size `> limit` => `HTTP 400`" (context: /upload)
def test_upload_rejects_a_file_over_the_limit(configured):
    client = configured(MAX_SOURCE_SIZE=ONE_SHORT)

    assert post_upload(client, CSV_BYTES).status_code == 400


# Phrase: "`HTTP 400` with standard envelope."
def test_size_failure_uses_the_standard_envelope(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(MAX_SOURCE_SIZE=ONE_SHORT)

    body = convert(client).get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()
    assert set(body) == {"ok", "error"}


# Phrase: "Enforced for `/convert` and `/upload`" (context: an over-limit source stores nothing)
def test_rejected_source_is_not_stored(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(MAX_SOURCE_SIZE=ONE_SHORT)

    convert(client)

    assert client.get(f"/datasets/{dataset_id(SOURCE_URL)}").status_code == 404


# Phrase: "unset limit means no max."
def test_unset_limit_accepts_any_size(client, serve):
    serve("name,age\n" + "".join(f"row{n},{n}\n" for n in range(5000)))

    assert convert(client).status_code == 200


# Phrase: "unset limit means no max." (context: a generous limit still accepts)
def test_a_limit_above_the_file_size_accepts(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(MAX_SOURCE_SIZE=GENEROUS)

    assert convert(client).status_code == 200


# Phrase: "Enforced for `/convert` and `/upload`" (context: querying a stored dataset is not an ingest)
def test_limit_does_not_apply_to_dataset_queries(configured, serve, client):
    serve(SIMPLE_CSV)
    endpoint = convert(client).get_json()["endpoint"]

    limited = configured(MAX_SOURCE_SIZE=ONE_SHORT)

    assert limited.get(endpoint).status_code == 200
    assert limited.get(endpoint + "/export").status_code == 200


# Phrase: "Enforced for `/convert` and `/upload`" (context: T64 -- a cache hit ingests nothing)
def test_cache_hit_is_not_re_measured(configured, serve, client):
    serve(SIMPLE_CSV)
    convert(client)

    limited = configured(MAX_SOURCE_SIZE=ONE_SHORT)

    assert convert(limited).status_code == 200


# Phrase: "file size `> limit`" (context: T63 -- the measured size is the downloaded byte count)
def test_size_is_measured_in_bytes_not_characters(configured, serve):
    body = "name,note\nada,ééé\n"
    serve(body.encode("utf-8"))
    client = configured(MAX_SOURCE_SIZE=str(len(body)))

    assert convert(client).status_code == 400
