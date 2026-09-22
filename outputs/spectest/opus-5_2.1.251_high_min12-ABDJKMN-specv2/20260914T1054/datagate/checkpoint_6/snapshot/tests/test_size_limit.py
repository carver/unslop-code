"""Spec section: Maximum Source Size.

`MAX_SOURCE_SIZE` is a byte count, so every fixture here is built to an exact byte
length and the boundary (`= limit`) is tested from both sides.
"""
import io
import urllib.parse

from conftest import assert_error_envelope

CSV = "name,qty\nwidget,3\n"


def csv_of(size):
    """A valid CSV table of exactly `size` bytes: a header plus 4-byte data rows.

    Padding is spread over rows rather than into one enormous cell, so the fixture
    stays an ordinary table at every size.
    """
    assert size >= 8, "the smallest possible table is 8 bytes"
    remaining = size - len("a,b\n")
    rows, extra = divmod(remaining, 4)
    body = "a,b\n" + "1,x\n" * (rows - 1) + "1," + "x" * (1 + extra) + "\n"
    assert len(body.encode("utf-8")) == size, (len(body), size)
    return body


def convert(client, url):
    query = "source=" + urllib.parse.quote(url, safe="")
    return client.get("/convert", query_string=query)


def upload(client, body, field="file"):
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post("/upload", data={field: (io.BytesIO(body), "data.csv")},
                       content_type="multipart/form-data")


# =============================================================================
# Phrase: "file size `= limit` accepted." (/convert)
# Context: the limit is inclusive - a file exactly at the limit goes through.
# =============================================================================

def test_convert_file_exactly_at_the_limit_is_accepted(make_app, origin):
    body = csv_of(64)
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    response = convert(client, origin.add(body))
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["ok"] is True


def test_convert_file_below_the_limit_is_accepted(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    assert convert(client, origin.add(csv_of(63))).status_code == 200


def test_accepted_file_at_the_limit_is_fully_queryable(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE=str(len(CSV))).test_client()
    response = convert(client, origin.add(CSV))
    assert response.status_code == 200
    payload = client.get(response.get_json()["endpoint"]).get_json()
    assert payload["columns"] == ["name", "qty"]
    assert payload["rows"] == [["widget", 3]]


# =============================================================================
# Phrase: "file size `> limit` => `HTTP 400` with standard envelope." (/convert)
# Context: one byte over the limit is already too big.
# =============================================================================

def test_convert_file_one_byte_over_the_limit_is_rejected(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    assert_error_envelope(convert(client, origin.add(csv_of(65))), 400)


def test_convert_far_over_the_limit_is_rejected(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="10").test_client()
    assert_error_envelope(convert(client, origin.add(csv_of(5000))), 400)


def test_oversized_convert_stores_no_dataset(make_app, origin):
    """A rejected source must not become a queryable dataset."""
    import datagate
    client = make_app(MAX_SOURCE_SIZE="10").test_client()
    url = origin.add(csv_of(500))
    assert convert(client, url).status_code == 400
    assert client.get("/datasets/%s" % datagate.dataset_id(url)).status_code == 404


def test_zero_limit_rejects_every_non_empty_file(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="0").test_client()
    assert_error_envelope(convert(client, origin.add(CSV)), 400)


def test_limit_is_measured_in_bytes_not_characters(make_app, origin):
    """A multi-byte character counts for all of its bytes."""
    body = "name,qty\nwidgét,3\n"
    assert len(body.encode("utf-8")) == len(body) + 1  # one two-byte character
    client = make_app(MAX_SOURCE_SIZE=str(len(body))).test_client()
    assert_error_envelope(convert(client, origin.add(body)), 400)


def test_limit_applies_to_spreadsheet_sources_too(make_app, origin):
    from conftest import xlsx_bytes
    book = xlsx_bytes([["name", "qty"], ["widget", 3]])
    client = make_app(MAX_SOURCE_SIZE=str(len(book) - 1)).test_client()
    assert_error_envelope(
        convert(client, origin.add(book, content_type="application/octet-stream")), 400)


# =============================================================================
# Phrase: "Enforced for `/convert` and `/upload`" - the `/upload` half.
# Context: the same inclusive boundary applies to the uploaded file's bytes.
# =============================================================================

def test_upload_exactly_at_the_limit_is_accepted(make_app):
    body = csv_of(64)
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    response = upload(client, body)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["ok"] is True


def test_upload_one_byte_over_the_limit_is_rejected(make_app):
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    assert_error_envelope(upload(client, csv_of(65)), 400)


def test_upload_below_the_limit_is_accepted(make_app):
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    assert upload(client, csv_of(20)).status_code == 200


def test_upload_limit_measures_the_file_part_not_the_multipart_envelope(make_app):
    """Boundary lines and headers are not part of the file (AMBIGUITIES T70)."""
    body = csv_of(64)  # the envelope adds well over 100 bytes of overhead
    client = make_app(MAX_SOURCE_SIZE="64").test_client()
    assert upload(client, body).status_code == 200


def test_upload_limit_applies_to_the_attachment_field_too(make_app):
    client = make_app(MAX_SOURCE_SIZE="20").test_client()
    assert_error_envelope(upload(client, csv_of(200), field="attachment"), 400)


def test_oversized_upload_stores_no_dataset(make_app):
    import datagate
    client = make_app(MAX_SOURCE_SIZE="20").test_client()
    body = csv_of(200).encode("utf-8")
    assert upload(client, body).status_code == 400
    assert client.get("/datasets/%s" % datagate.upload_id(body)).status_code == 404


# =============================================================================
# Phrase: "unset limit means no max."
# Context: with MAX_SOURCE_SIZE unset nothing is ever rejected for size.
# =============================================================================

def test_unset_limit_accepts_a_large_source(make_app, origin):
    client = make_app().test_client()
    assert convert(client, origin.add(csv_of(250_000))).status_code == 200


def test_unset_limit_accepts_a_large_upload(make_app):
    client = make_app().test_client()
    assert upload(client, csv_of(250_000)).status_code == 200


def test_empty_limit_value_means_unset(make_app, origin):
    """An explicitly empty value is "no limit", not a parse error (T69)."""
    client = make_app(MAX_SOURCE_SIZE="").test_client()
    assert convert(client, origin.add(csv_of(100000))).status_code == 200


# =============================================================================
# Phrase (error table): "Size exceeded | 400 | {"ok": false, "error": "<message>"}"
# Context: the envelope shape is exactly two keys, with a non-empty message.
# =============================================================================

def test_size_error_envelope_shape(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="8").test_client()
    payload = assert_error_envelope(convert(client, origin.add(csv_of(100))), 400)
    assert payload == {"ok": False, "error": payload["error"]}


def test_size_error_is_json(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="8").test_client()
    response = convert(client, origin.add(csv_of(100)))
    assert response.headers["Content-Type"].startswith("application/json")


def test_upload_size_error_envelope_shape(make_app):
    client = make_app(MAX_SOURCE_SIZE="8").test_client()
    assert_error_envelope(upload(client, csv_of(100)), 400)


def test_size_error_still_carries_cors_headers(make_app, origin):
    client = make_app(MAX_SOURCE_SIZE="8").test_client()
    response = convert(client, origin.add(csv_of(100)))
    assert response.headers["Access-Control-Allow-Origin"] == "*"


# =============================================================================
# Phrase: "Enforced for `/convert` and `/upload`" - and nowhere else.
# Context: the limit gates ingestion, not querying an already-stored dataset.
# =============================================================================

def test_limit_does_not_block_queries_of_a_stored_dataset(make_app, origin, tmp_path):
    """Ingest under a generous limit, restart under a tight one: the id still reads."""
    store = str(tmp_path / "store")
    body = csv_of(500)
    url = origin.add(body)
    first = make_app(STORAGE_DIR=store, MAX_SOURCE_SIZE="1000").test_client()
    endpoint = convert(first, url).get_json()["endpoint"]
    second = make_app(STORAGE_DIR=store, MAX_SOURCE_SIZE="10").test_client()
    assert second.get(endpoint).status_code == 200
