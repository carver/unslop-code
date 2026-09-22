"""Spec section: Maximum Source Size."""

import io

import pytest

SMALL_CSV = "name,age\nada,36\n"
SMALL_SIZE = len(SMALL_CSV.encode("utf-8"))


@pytest.fixture
def limited(configured_client, origin):
    """A client started with `MAX_SOURCE_SIZE` set, plus helpers for both routes."""

    def _limited(limit=None):
        client = configured_client(MAX_SOURCE_SIZE=limit)
        counter = iter(range(1000))

        def convert(body):
            url = origin.serve(f"/size-{limit}-{next(counter)}.csv", body)
            return client.get(f"/convert?source={url}")

        def upload(body):
            payload = body.encode("utf-8") if isinstance(body, str) else body
            return client.post(
                "/upload",
                data={"file": (io.BytesIO(payload), "data.csv")},
                content_type="multipart/form-data",
            )

        return convert, upload

    return _limited


def padded_csv(size):
    """A valid CSV of exactly `size` bytes, padded with extra one-byte data rows.

    The padding is spread over rows rather than packed into one cell, which
    would run into the CSV reader's field size limit well before 200 kB.
    """
    header = "n,tag\n"
    rows = "".join(f"{index % 10},x\n" for index in range(size - len(header)))
    return header + rows[: size - len(header)]


# Phrase: "file size `= limit` accepted." - on `/convert`.
def test_convert_accepts_a_source_exactly_at_the_limit(limited):
    convert, _ = limited(SMALL_SIZE)

    assert convert(SMALL_CSV).status_code == 200


# Phrase: "file size `= limit` accepted." - on `/upload`.
def test_upload_accepts_a_file_exactly_at_the_limit(limited):
    _, upload = limited(SMALL_SIZE)

    assert upload(SMALL_CSV).status_code == 200


# Phrase: "Enforced for `/convert` and `/upload`" - a source under the limit is
# accepted by both.
def test_both_routes_accept_a_source_under_the_limit(limited):
    convert, upload = limited(SMALL_SIZE + 1)

    assert convert(SMALL_CSV).status_code == 200
    assert upload(SMALL_CSV).status_code == 200


# Phrase: "file size `> limit` => `HTTP 400`" - on `/convert`.
def test_convert_rejects_a_source_over_the_limit(limited):
    convert, _ = limited(SMALL_SIZE - 1)

    assert convert(SMALL_CSV).status_code == 400


# Phrase: "file size `> limit` => `HTTP 400`" - on `/upload`.
def test_upload_rejects_a_file_over_the_limit(limited):
    _, upload = limited(SMALL_SIZE - 1)

    assert upload(SMALL_CSV).status_code == 400


# Phrase: "one byte over is over" - the boundary is exact in both directions.
def test_the_limit_boundary_is_exact(limited):
    convert, _ = limited(64)

    assert convert(padded_csv(64)).status_code == 200
    assert convert(padded_csv(65)).status_code == 400


# Phrase: "`HTTP 400` with standard envelope" / "Size exceeded | 400 |
# `{"ok": false, "error": "<message>"}`".
def test_the_size_error_uses_the_standard_envelope(limited):
    _, upload = limited(SMALL_SIZE - 1)
    payload = upload(SMALL_CSV).get_json()

    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert set(payload) == {"ok", "error"}


# Phrase: "unset limit means no max." - nothing configured accepts a large source.
def test_an_unset_limit_imposes_no_maximum(limited):
    convert, upload = limited()
    big = padded_csv(200_000)

    assert convert(big).status_code == 200
    assert upload(big).status_code == 200


# Phrase: "| `MAX_SOURCE_SIZE` | integer bytes | unset |" - a limit of zero is a
# real limit, so every non-empty source is over it (T62).
def test_a_zero_limit_rejects_every_source(limited):
    convert, upload = limited(0)

    assert convert(SMALL_CSV).status_code == 400
    assert upload(SMALL_CSV).status_code == 400


# Phrase: "Enforced for `/convert` and `/upload`" - and nowhere else: a dataset
# ingested under a generous limit stays readable under a strict one.
def test_the_limit_does_not_apply_to_dataset_reads(limited, configured_client):
    _, upload = limited(200_000)
    endpoint = upload(padded_csv(1000)).get_json()["endpoint"]

    strict = configured_client(MAX_SOURCE_SIZE=10)
    assert strict.get(endpoint).status_code == 200
