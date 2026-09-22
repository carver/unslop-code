"""Building datasets from the two sources of files: a URL and an upload."""

from .errors import ApiError
from .formats import build_table
from .sourcing import fetch_source
from .store import Dataset, content_id, dataset_id


def ingest_source(source: str, charset: str | None, max_size: int | None) -> Dataset:
    """Build the dataset for the file at `source`.

    Raises `ApiError` at whichever stage rejects the input.
    """
    raw = fetch_source(source)
    _check_size(raw, max_size)
    columns, rows = build_table(raw, charset)
    return Dataset(id=dataset_id(source), columns=columns, rows=rows)


def ingest_upload(raw: bytes, charset: str | None, max_size: int | None) -> Dataset:
    """Build the dataset for an uploaded file, identified by its bytes."""
    _check_size(raw, max_size)
    columns, rows = build_table(raw, charset)
    return Dataset(id=content_id(raw), columns=columns, rows=rows)


def _check_size(raw: bytes, max_size: int | None) -> None:
    """Refuse a file past `MAX_SOURCE_SIZE`; one exactly at the limit passes.

    The file's own bytes are what is measured — not a declared length, not the
    multipart envelope an upload arrives in — and they are measured before any
    parsing, so an oversized file costs no more than receiving it.
    """
    if max_size is not None and len(raw) > max_size:
        raise ApiError(400, f"file is {len(raw)} bytes, over the {max_size} byte limit")
