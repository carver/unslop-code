"""The ingestion pipeline: bytes in, stored dataset out, whatever the format."""

from .decoding import decode_csv_bytes
from .fetching import fetch_bytes, validate_source
from .formats import Format, detect_format
from .inference import coerce_value
from .limits import enforce_size
from .parsing import parse_table
from .spreadsheets import read_workbook
from .store import Dataset, content_id, dataset_id


def convert_source(source, charset, store, reuse_cached=True, max_size=None):
    """Fetch, parse and store the table at `source`, returning its dataset id.

    A dataset already stored under that id is returned untouched while
    `reuse_cached` holds, which is how `CACHE_ENABLED` and the `force` flag reach
    the pipeline. The source URL alone decides the hit, so `charset` never gets a
    chance to matter when there is no download to decode (AMBIGUITIES T48). A hit
    also downloads nothing, so `max_size` has no file to measure (AMBIGUITIES T63).
    """
    url = validate_source(source)
    identifier = dataset_id(url)
    if reuse_cached and store.get(identifier) is not None:
        return identifier
    return _ingest(fetch_bytes(url), charset, identifier, store, max_size)


def convert_upload(raw, charset, store, max_size=None):
    """Parse and store an uploaded payload, returning the id its bytes map to."""
    return _ingest(raw, charset, content_id(raw), store, max_size)


def _ingest(raw, charset, identifier, store, max_size):
    """Check, parse and file `raw` under `identifier`, whichever route supplied it.

    Storing happens only once the size check and the parse have succeeded, so a
    rejected or unreadable re-ingestion leaves the previous dataset queryable.
    """
    enforce_size(raw, max_size)
    columns, rows = _read_table(raw, charset)
    store.put(identifier, Dataset(columns, [[coerce_value(cell) for cell in row] for row in rows]))
    return identifier


def _read_table(raw, charset):
    """Read `raw` with the reader for its format; `charset` only reaches text CSV."""
    detected = detect_format(raw)
    if detected is Format.CSV:
        return parse_table(decode_csv_bytes(raw, charset))
    return read_workbook(raw, detected)
