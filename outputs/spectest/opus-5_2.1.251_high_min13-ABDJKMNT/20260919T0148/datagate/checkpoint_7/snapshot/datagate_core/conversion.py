"""The ingestion pipeline: bytes in, stored dataset out, whatever the format."""

from .decoding import decode_csv_bytes
from .enrichment import build_metadata
from .fetching import fetch_bytes, validate_source
from .formats import Format, detect_format
from .inference import coerce_value
from .limits import enforce_size
from .parsing import parse_table
from .spreadsheets import read_workbook
from .store import Dataset, content_id, dataset_id


def convert_source(source, charset, store, reuse_cached=True, max_size=None, enrich=False):
    """Fetch, parse and store the table at `source`, returning its dataset id.

    A dataset already stored under that id is returned untouched while
    `reuse_cached` holds and it already carries whatever `enrich` asks for, which is
    how `CACHE_ENABLED`, the `force` flag and `enrich=yes` reach the pipeline. The
    source URL alone decides the hit, so `charset` never gets a chance to matter
    when there is no download to decode (AMBIGUITIES T48). A hit also downloads
    nothing, so `max_size` has no file to measure (AMBIGUITIES T63).
    """
    url = validate_source(source)
    identifier = dataset_id(url)
    if reuse_cached and _satisfies(store.get(identifier), enrich):
        return identifier
    return _ingest(fetch_bytes(url), charset, identifier, store, max_size, enrich)


def convert_upload(raw, charset, store, max_size=None):
    """Parse and store an uploaded payload, returning the id its bytes map to.

    Uploads are never enriched: `enrich` applies only on `/convert`.
    """
    return _ingest(raw, charset, content_id(raw), store, max_size, enrich=False)


def _satisfies(cached, enrich):
    """True when `cached` can answer a request asking for `enrich` without re-ingesting.

    An enriched request finds a non-enriched dataset wanting and re-ingests, which
    is what upgrades the stored state; the reverse is not true, since a plain
    request has nothing to gain by discarding metadata (AMBIGUITIES T81).
    """
    return cached is not None and (cached.metadata is not None or not enrich)


def _ingest(raw, charset, identifier, store, max_size, enrich):
    """Check, parse and file `raw` under `identifier`, whichever route supplied it.

    Storing happens only once the size check, the parse and the enrichment have all
    succeeded, so a rejected, unreadable or unenrichable re-ingestion leaves the
    previous dataset queryable and never downgrades it.
    """
    enforce_size(raw, max_size)
    detected = detect_format(raw)
    columns, rows = _read_table(raw, charset, detected)
    typed = [[coerce_value(cell) for cell in row] for row in rows]

    metadata = build_metadata(detected, columns, typed) if enrich else None
    store.put(identifier, Dataset(columns, typed, metadata))
    return identifier


def _read_table(raw, charset, detected):
    """Read `raw` with the reader for its format; `charset` only reaches text CSV."""
    if detected is Format.CSV:
        return parse_table(decode_csv_bytes(raw, charset))
    return read_workbook(raw, detected)
