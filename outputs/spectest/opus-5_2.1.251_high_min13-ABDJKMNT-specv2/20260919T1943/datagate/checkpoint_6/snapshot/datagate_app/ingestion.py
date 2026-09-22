"""Ingestion: enforce the size limit, recognise the format, then build a `Dataset`."""

from .decoding import decode_document
from .errors import DataGateError
from .formats import SourceDocument, SourceFormat, detect_format
from .parsing import Dataset, build_table, parse_table, reject_non_tabular
from .spreadsheets import read_workbook


def build_dataset(document: SourceDocument, charset: str | None = None, max_size: int | None = None) -> Dataset:
    """Turn a fetched or uploaded payload into a `Dataset`.

    `charset` only ever reaches the CSV branch: a workbook carries its own
    encoding, so for one the parameter is neither applied nor validated (T41).
    """
    enforce_size_limit(document.data, max_size)
    source_format = detect_format(document.data)
    if source_format is SourceFormat.CSV:
        text = decode_document(document.data, charset)
        reject_non_tabular(document.content_type, text)
        return parse_table(text)
    return build_table(read_workbook(document.data, source_format))


def enforce_size_limit(data: bytes, max_size: int | None) -> None:
    """Reject a payload past `MAX_SOURCE_SIZE`; a file exactly at the limit passes.

    The limit is about the file rather than what is in it, so it is measured on
    the raw bytes before the format is recognised (T63, T65).
    """
    if max_size is not None and len(data) > max_size:
        raise DataGateError(f"Source is {len(data)} bytes, over the {max_size} byte maximum", 400)
