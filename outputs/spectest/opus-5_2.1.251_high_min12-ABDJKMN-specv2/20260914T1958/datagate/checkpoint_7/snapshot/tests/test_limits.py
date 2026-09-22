"""Spec section: Maximum Source Size."""
import hashlib

import pytest

from conftest import (
    assert_error_envelope,
    convert_ok,
    free_port,
    upload,
    upload_ok,
    write_config,
    xlsx_bytes,
)

HEADER = "a,b\n"


def csv_of_size(n):
    """A valid two-column CSV of exactly `n` bytes (n >= 8)."""
    assert n >= 8
    body = HEADER
    while len(body) + 4 <= n:
        body += "1,2\n"
    remainder = n - len(body)
    if remainder:  # widen the last row's second cell to land exactly on `n`
        body = body[:-4] + "1," + "2" * (1 + remainder) + "\n"
    assert len(body) == n, (len(body), n)
    return body


# ---------------------------------------------------------------------------
# Phrase: "Enforced for `/convert` ... file size `= limit` accepted."
# Context: a source whose byte length is exactly the configured limit.
# ---------------------------------------------------------------------------
def test_convert_accepts_a_source_exactly_at_the_limit(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "64"})
    url = origin.add("/lim-exact.csv", csv_of_size(64))
    assert convert_ok(gate, url).startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "file size `> limit` => `HTTP 400` with standard envelope."
# Context: /convert, one byte over the configured limit.
# ---------------------------------------------------------------------------
def test_convert_rejects_one_byte_over_the_limit(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "64"})
    url = origin.add("/lim-over.csv", csv_of_size(65))
    assert_error_envelope(gate.convert(source=url), 400)


# ---------------------------------------------------------------------------
# Phrase: "file size `< limit` accepted" (implied by "= limit accepted")
# Context: comfortably under the limit.
# ---------------------------------------------------------------------------
def test_convert_accepts_a_source_under_the_limit(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "1024"})
    url = origin.add("/lim-under.csv", csv_of_size(64))
    assert convert_ok(gate, url).startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "Enforced for ... `/upload`. file size `= limit` accepted."
# Context: an uploaded file whose byte length is exactly the limit.
# ---------------------------------------------------------------------------
def test_upload_accepts_a_file_exactly_at_the_limit(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "64"})
    assert upload_ok(gate, csv_of_size(64)).startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "file size `> limit` => `HTTP 400` with standard envelope."
# Context: /upload, one byte over the configured limit.
# ---------------------------------------------------------------------------
def test_upload_rejects_one_byte_over_the_limit(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "64"})
    assert_error_envelope(upload(gate, csv_of_size(65)), 400)


# ---------------------------------------------------------------------------
# Phrase: "unset limit means no max."
# Context: no MAX_SOURCE_SIZE anywhere -- a large source still converts.
# ---------------------------------------------------------------------------
def test_unset_limit_means_no_maximum(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    url = origin.add("/lim-unset.csv", csv_of_size(200000))
    assert convert_ok(gate, url).startswith("/datasets/")
    assert upload_ok(gate, csv_of_size(200000)).startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "`MAX_SOURCE_SIZE` | integer bytes | unset"
# Context: a limit of zero is a real limit -- only an empty source fits.
# ---------------------------------------------------------------------------
def test_zero_limit_rejects_every_non_empty_source(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "0"})
    url = origin.add("/lim-zero.csv", "a,b\n1,2\n")
    assert_error_envelope(gate.convert(source=url), 400)
    assert_error_envelope(upload(gate, b"a,b\n1,2\n"), 400)


# ---------------------------------------------------------------------------
# Phrase: "Size exceeded | 400 | `{"ok": false, "error": "<message>"}`"
# Context: the error table pins the body shape for an over-size source.
# ---------------------------------------------------------------------------
def test_size_exceeded_uses_the_standard_envelope(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "8"})
    url = origin.add("/lim-envelope.csv", csv_of_size(40))
    body = assert_error_envelope(gate.convert(source=url), 400)
    assert set(body) == {"ok", "error"}
    body = assert_error_envelope(upload(gate, csv_of_size(40)), 400)
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "Enforced for `/convert` and `/upload`"
# Context: the limit is about source bytes, so it applies to workbooks too.
# ---------------------------------------------------------------------------
def test_limit_applies_to_spreadsheet_uploads(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "64"})
    book = xlsx_bytes([("S", [["a", "b"], [1, 2]])])
    assert len(book) > 64
    assert_error_envelope(upload(gate, book, filename="t.xlsx"), 400)


# ---------------------------------------------------------------------------
# Phrase: "Enforced for `/convert` and `/upload`"
# Context: the limit does not apply to dataset queries or exports.
# ---------------------------------------------------------------------------
def test_limit_does_not_apply_to_dataset_queries(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "64"})
    url = origin.add("/lim-query.csv", csv_of_size(64))
    endpoint = convert_ok(gate, url)
    assert gate.get(endpoint).status_code == 200
    assert gate.get(endpoint + "/export").status_code == 200


# ---------------------------------------------------------------------------
# Phrase: "`MAX_SOURCE_SIZE` | integer bytes" from the `DATAGATE_CONFIG` file
# Context: the limit is a configuration setting like any other.
# ---------------------------------------------------------------------------
def test_limit_can_come_from_the_config_file(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "MAX_SOURCE_SIZE=64\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    assert convert_ok(gate, origin.add("/lim-cfg-ok.csv", csv_of_size(64)))
    assert_error_envelope(
        gate.convert(source=origin.add("/lim-cfg-bad.csv", csv_of_size(65))), 400
    )


# ---------------------------------------------------------------------------
# Phrase: "3. Direct environment variables" applied to MAX_SOURCE_SIZE
# Context: the environment raises a limit set lower in the config file.
# ---------------------------------------------------------------------------
def test_limit_environment_overrides_config_file(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "MAX_SOURCE_SIZE=8\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg, "MAX_SOURCE_SIZE": "4096"})
    url = origin.add("/lim-env-over-file.csv", csv_of_size(64))
    assert convert_ok(gate, url).startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "file size `> limit` => `HTTP 400`"
# Context: an over-size source must not become a queryable dataset.
# ---------------------------------------------------------------------------
def test_over_size_source_is_not_stored(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": "16"})
    url = origin.add("/lim-not-stored.csv", csv_of_size(64))
    assert gate.convert(source=url).status_code == 400
    ident = hashlib.sha256(url.encode()).hexdigest()[:16]
    assert gate.get(f"/datasets/{ident}").status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "file size `> limit` => `HTTP 400`"
# Context: an empty source is zero bytes, so it never exceeds any limit;
#          it fails later for not being tabular, not for size.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("limit", ["0", "1", "1024"])
def test_empty_payload_never_exceeds_the_limit(fresh_gate, limit):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"MAX_SOURCE_SIZE": limit})
    resp = upload(gate, b"")
    body = assert_error_envelope(resp, 400)
    assert "too large" not in body["error"].lower()
