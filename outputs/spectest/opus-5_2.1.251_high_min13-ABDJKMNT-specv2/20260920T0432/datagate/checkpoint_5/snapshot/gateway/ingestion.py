"""Building datasets from the two sources of files: a URL and an upload."""

from .formats import build_table
from .sourcing import fetch_source
from .store import Dataset, content_id, dataset_id


def ingest_source(source: str, charset: str | None) -> Dataset:
    """Build the dataset for the file at `source`.

    Raises `ApiError` at whichever stage rejects the input.
    """
    columns, rows = build_table(fetch_source(source), charset)
    return Dataset(id=dataset_id(source), columns=columns, rows=rows)


def ingest_upload(raw: bytes, charset: str | None) -> Dataset:
    """Build the dataset for an uploaded file, identified by its bytes."""
    columns, rows = build_table(raw, charset)
    return Dataset(id=content_id(raw), columns=columns, rows=rows)
