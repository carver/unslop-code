"""Spec tests for "Maximum Source Size". Each section quotes its phrase."""
import urllib.parse

import pytest

from conftest import assert_error_envelope, running

LIMIT = 64


def csv_of(size):
    """A valid two-column CSV of exactly `size` bytes."""
    assert size >= 12, size
    head = "a,b\n"                             # 4 bytes
    remaining = size - len(head)
    rows = ["1,2\n"] * (remaining // 4 - 1)     # 4 bytes each
    rows.append("1," + "2" * (1 + remaining % 4) + "\n")   # absorbs the rest
    return head + "".join(rows)


def hits(origin, url):
    return origin.hits.get(urllib.parse.urlsplit(url).path, 0)


@pytest.fixture(scope="module")
def limited():
    """A server with `MAX_SOURCE_SIZE=64`."""
    with running({"MAX_SOURCE_SIZE": str(LIMIT), "DATAGATE_CONFIG": None},
                 "size_limited") as client:
        yield client


@pytest.fixture(scope="module")
def unlimited():
    """A server with `MAX_SOURCE_SIZE` unset."""
    with running({"MAX_SOURCE_SIZE": None, "DATAGATE_CONFIG": None},
                 "size_unlimited") as client:
        yield client


# ==========================================================================
# Spec: "Enforced for `/convert` and `/upload`: ... file size `= limit`
#        accepted."
# ==========================================================================
def test_upload_of_exactly_the_limit_is_accepted(limited):
    payload = csv_of(LIMIT).encode("utf-8")
    assert len(payload) == LIMIT
    status, _, data = limited.upload(payload)
    assert status == 200, data
    assert data["ok"] is True


def test_convert_of_exactly_the_limit_is_accepted(limited, csv_url):
    body = csv_of(LIMIT)
    url = csv_url(body, name="size-exact")
    status, _, data = limited.convert(url)
    assert status == 200, data
    assert data["endpoint"].startswith("/datasets/")


@pytest.mark.parametrize("size", [12, 20, LIMIT - 1, LIMIT])
def test_sizes_up_to_the_limit_are_accepted(limited, size):
    assert limited.upload(csv_of(size).encode("utf-8"))[0] == 200


# ==========================================================================
# Spec: "file size `> limit` => `HTTP 400` with standard envelope."
# ==========================================================================
def test_upload_over_the_limit_is_rejected(limited):
    payload = csv_of(LIMIT + 1).encode("utf-8")
    status, _, data = limited.upload(payload)
    assert_error_envelope(status, data, 400)


def test_convert_over_the_limit_is_rejected(limited, csv_url):
    url = csv_url(csv_of(LIMIT + 1), name="size-over")
    status, _, data = limited.convert(url)
    assert_error_envelope(status, data, 400)


@pytest.mark.parametrize("size", [LIMIT + 1, LIMIT + 2, LIMIT * 4])
def test_every_size_over_the_limit_is_rejected(limited, size):
    status, _, data = limited.upload(csv_of(size).encode("utf-8"))
    assert_error_envelope(status, data, 400)


# Spec: "with standard envelope" — the body is the usual error object and
# carries no dataset endpoint.
def test_size_error_envelope_has_no_endpoint(limited):
    status, _, data = limited.upload(csv_of(LIMIT + 10).encode("utf-8"))
    assert_error_envelope(status, data, 400)
    assert "endpoint" not in data


# A rejected source is not stored: the id it would have had stays unknown.
def test_rejected_convert_stores_nothing(limited, csv_url):
    url = csv_url(csv_of(LIMIT + 8), name="size-nostore")
    assert limited.convert(url)[0] == 400
    # Retrying still fails (nothing was cached as a success).
    assert limited.convert(url)[0] == 400


# ==========================================================================
# Spec: "unset limit means no max."
# ==========================================================================
def test_no_limit_accepts_large_uploads(unlimited):
    payload = csv_of(100000).encode("utf-8")
    status, _, data = unlimited.upload(payload)
    assert status == 200, data


def test_no_limit_accepts_large_sources(unlimited, csv_url):
    url = csv_url(csv_of(100000), name="size-nolimit")
    status, _, data = unlimited.convert(url)
    assert status == 200, data


# Spec: "unset limit means no max." — an explicitly empty value is unset too
# (AMBIGUITIES T81).
def test_empty_limit_means_no_max():
    with running({"MAX_SOURCE_SIZE": "", "DATAGATE_CONFIG": None},
                 "size_empty") as client:
        assert client.upload(csv_of(200000).encode("utf-8"))[0] == 200


# ==========================================================================
# Boundary cases of the limit value itself
# ==========================================================================
# Spec: "integer bytes" — `0` is a limit, not "unset" (AMBIGUITIES T82).
def test_zero_limit_rejects_any_non_empty_file():
    with running({"MAX_SOURCE_SIZE": "0", "DATAGATE_CONFIG": None},
                 "size_zero") as client:
        status, _, data = client.upload(b"a,b\n1,2\n")
        assert_error_envelope(status, data, 400)


# Spec: "file size `= limit` accepted" — measured on the file's bytes, so a
# multibyte character counts as its encoded length (AMBIGUITIES T83).
def test_limit_counts_bytes_not_characters():
    body = "naïve,b\n1,2\n"                  # 13 bytes, 12 characters
    payload = body.encode("utf-8")
    assert len(payload) == 13 and len(body) == 12
    with running({"MAX_SOURCE_SIZE": "12", "DATAGATE_CONFIG": None},
                 "size_bytes") as client:
        assert client.upload(payload)[0] == 400
    with running({"MAX_SOURCE_SIZE": "13", "DATAGATE_CONFIG": None},
                 "size_bytes") as client:
        assert client.upload(payload)[0] == 200


# Spec: "file size" — for `/upload` that is the uploaded part, not the whole
# multipart body, which is a few hundred bytes larger (AMBIGUITIES T83).
def test_limit_ignores_multipart_framing():
    payload = csv_of(LIMIT).encode("utf-8")
    with running({"MAX_SOURCE_SIZE": str(LIMIT), "DATAGATE_CONFIG": None},
                 "size_framing") as client:
        status, _, data = client.upload(payload, filename="a-long-name.csv")
        assert status == 200, data


# ==========================================================================
# Spec: "Enforced for `/convert` and `/upload`" — and nowhere else.
# ==========================================================================
def test_limit_does_not_affect_queries_or_export(limited, csv_url):
    """A dataset accepted at ingest stays fully queryable and exportable."""
    url = csv_url(csv_of(LIMIT), name="size-query")
    endpoint = limited.convert(url)[2]["endpoint"]
    assert limited.get(endpoint)[0] == 200
    status, headers, body = limited.raw(endpoint + "/export")
    assert status == 200, body
    assert len(body) > 0
