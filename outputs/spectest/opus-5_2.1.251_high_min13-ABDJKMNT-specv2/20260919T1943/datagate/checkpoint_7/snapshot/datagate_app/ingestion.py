"""Ingestion: enforce the size limit, recognise the format, then build a `Dataset`."""

from dataclasses import replace

from .decoding import decode_document
from .enrichment import describe
from .errors import DataGateError
from .formats import SourceDocument, SourceFormat, detect_format
from .parsing import Dataset, build_table, parse_table, reject_non_tabular
from .spreadsheets import read_workbook


def build_dataset(
    document: SourceDocument,
    charset: str | None = None,
    max_size: int | None = None,
    enrich: bool = False,
) -> Dataset:
    """Turn a fetched or uploaded payload into a `Dataset`.

    `charset` only ever reaches the CSV branch: a workbook carries its own
    encoding, so for one the parameter is neither applied nor validated (T41).

    Metadata is attached here rather than at the storage layer, so a failure
    anywhere in an enriched ingestion happens before the dataset is written and
    cannot leave the table stored without it (T80).
    """
    enforce_size_limit(document.data, max_size)
    source_format = detect_format(document.data)
    dataset = _read_table(document, source_format, charset)
    if not enrich:
        return dataset
    return replace(dataset, metadata=describe(dataset, source_format))


def _read_table(document: SourceDocument, source_format: SourceFormat, charset: str | None) -> Dataset:
    """Parse the payload along the path its format calls for."""
    if source_format is not SourceFormat.CSV:
        return build_table(read_workbook(document.data, source_format))
    text = decode_document(document.data, charset)
    reject_non_tabular(document.content_type, text)
    return parse_table(text)


def enforce_size_limit(data: bytes, max_size: int | None) -> None:
    """Reject a payload past `MAX_SOURCE_SIZE`; a file exactly at the limit passes.

    The limit is about the file rather than what is in it, so it is measured on
    the raw bytes before the format is recognised (T63, T65).
    """
    if max_size is not None and len(data) > max_size:
        raise DataGateError(f"Source is {len(data)} bytes, over the {max_size} byte maximum", 400)
