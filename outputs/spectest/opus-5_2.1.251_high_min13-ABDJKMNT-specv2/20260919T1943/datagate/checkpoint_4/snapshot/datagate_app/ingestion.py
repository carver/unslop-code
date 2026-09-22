"""Ingestion: recognise a payload's format, then turn it into a `Dataset`."""

from .decoding import decode_document
from .formats import SourceDocument, SourceFormat, detect_format
from .parsing import Dataset, build_table, parse_table, reject_non_tabular
from .spreadsheets import read_workbook


def build_dataset(document: SourceDocument, charset: str | None = None) -> Dataset:
    """Turn a fetched or uploaded payload into a `Dataset`.

    `charset` only ever reaches the CSV branch: a workbook carries its own
    encoding, so for one the parameter is neither applied nor validated (T41).
    """
    source_format = detect_format(document.data)
    if source_format is SourceFormat.CSV:
        text = decode_document(document.data, charset)
        reject_non_tabular(document.content_type, text)
        return parse_table(text)
    return build_table(read_workbook(document.data, source_format))
