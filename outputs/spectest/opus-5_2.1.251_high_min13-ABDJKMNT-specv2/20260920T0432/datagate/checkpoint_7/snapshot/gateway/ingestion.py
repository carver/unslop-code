"""Building datasets from the two sources of files: a URL and an upload."""

from .enrichment import describe
from .errors import ApiError
from .formats import Table, build_table
from .sourcing import fetch_source
from .store import Dataset, content_id, dataset_id


def ingest_source(
    source: str, charset: str | None, max_size: int | None, enrich: bool = False
) -> Dataset:
    """Build the dataset for the file at `source`, enriched if asked for.

    Raises `ApiError` at whichever stage rejects the input.
    """
    raw = fetch_source(source)
    _check_size(raw, max_size)
    return _dataset(dataset_id(source), build_table(raw, charset), enrich)


def ingest_upload(raw: bytes, charset: str | None, max_size: int | None) -> Dataset:
    """Build the dataset for an uploaded file, identified by its bytes.

    Enrichment is a `/convert` option, so an upload is always plain.
    """
    _check_size(raw, max_size)
    return _dataset(content_id(raw), build_table(raw, charset), enrich=False)


def _dataset(identifier: str, table: Table, enrich: bool) -> Dataset:
    """Assemble the dataset, computing its metadata before it can be stored.

    Metadata is part of building the dataset rather than a step after it, so a
    failure here leaves nothing to store and cannot replace an enriched dataset
    with a non-enriched one.
    """
    metadata = _metadata(table) if enrich else None
    return Dataset(
        id=identifier, columns=table.columns, rows=table.rows, metadata=metadata
    )


def _metadata(table: Table) -> dict:
    """The enrichment metadata, reported through the JSON envelope if it fails."""
    try:
        return describe(table)
    except Exception as exc:
        raise ApiError(500, f"enrichment failed: {exc}") from exc


def _check_size(raw: bytes, max_size: int | None) -> None:
    """Refuse a file past `MAX_SOURCE_SIZE`; one exactly at the limit passes.

    The file's own bytes are what is measured — not a declared length, not the
    multipart envelope an upload arrives in — and they are measured before any
    parsing, so an oversized file costs no more than receiving it.
    """
    if max_size is not None and len(raw) > max_size:
        raise ApiError(400, f"file is {len(raw)} bytes, over the {max_size} byte limit")
