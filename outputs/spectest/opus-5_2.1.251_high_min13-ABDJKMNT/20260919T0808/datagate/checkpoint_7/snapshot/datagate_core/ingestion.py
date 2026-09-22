"""Choosing how to read incoming bytes - workbook or text CSV - into a dataset."""

from datagate_core.datasets import Dataset
from datagate_core.decoding import decode
from datagate_core.enrichment import CSV, EXCEL, describe
from datagate_core.spreadsheets import is_workbook, read_first_sheet
from datagate_core.tables import Table, build_table, parse_table


def ingest(data: bytes, charset: str | None, enrich: bool) -> Dataset:
    """Read `data` in whichever supported format it is written in.

    The format is taken from the bytes themselves, not from a file name or URL
    (T35), so `charset` is only consulted for text CSV sources (T36); it also
    decides the `filetype` an enriched dataset reports and how much its metadata
    can say. Enrichment happens here, as part of ingestion, so a dataset only
    ever reaches the store once its metadata is in hand (T82).
    """
    table, filetype = _read(data, charset)
    return Dataset(table, describe(table, filetype) if enrich else {})


def _read(data: bytes, charset: str | None) -> tuple[Table, str]:
    """The parsed table, and the name of the format it was read from."""
    if is_workbook(data):
        return build_table(read_first_sheet(data)), EXCEL
    return parse_table(decode(data, charset)), CSV
