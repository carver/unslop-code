"""Format detection: turning downloaded or uploaded bytes into a dataset."""

from dataclasses import replace

from csv_parsing import read_csv_grid
from enrichment import CSV_FILETYPE, EXCEL_FILETYPE, describe
from errors import DatagateError
from spreadsheets import read_xls_grid, read_xlsx_grid
from store import Dataset, Grid, Row

# .xlsx workbooks are zip archives and .xls workbooks are OLE2 compound files, so the format is
# read from the payload itself rather than from a file name or a declared content type.
ZIP_SIGNATURE = b"PK\x03\x04"
OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def parse_payload(data: bytes, charset: str | None, enrich: bool) -> Dataset:
    """Parse CSV, .xls or .xlsx bytes into a dataset, describing it when `enrich` asks.

    Anything that is not a recognised workbook is read as CSV text, which is where `charset`
    applies; unreadable content of any format is a 400. The detected format is what names the
    dataset's filetype and decides how much of it can be described.
    """
    if data.startswith(ZIP_SIGNATURE):
        return build_dataset(read_xlsx_grid(data), EXCEL_FILETYPE, enrich)
    if data.startswith(OLE2_SIGNATURE):
        return build_dataset(read_xls_grid(data), EXCEL_FILETYPE, enrich)
    return build_dataset(read_csv_grid(data, charset), CSV_FILETYPE, enrich)


def build_dataset(grid: Grid, filetype: str, enrich: bool) -> Dataset:
    """Split a grid into its header row and data rows, discarding rows that are entirely blank.

    Enrichment is computed here, from the rows as they were just parsed, so that a dataset is
    only ever stored with metadata that describes the bytes it came from.
    """
    rows = [row for row in grid if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise DatagateError(400, "Source content needs a header row and at least one data row")
    columns = [str(cell).strip() for cell in rows[0]]
    dataset = Dataset(columns, [_fit(row, len(columns)) for row in rows[1:]])
    return replace(dataset, enrichment=describe(dataset, filetype)) if enrich else dataset


def _fit(row: Row, width: int) -> Row:
    """Fit a row to the header width, padding short rows and dropping surplus cells."""
    return row[:width] + [""] * (width - len(row))
