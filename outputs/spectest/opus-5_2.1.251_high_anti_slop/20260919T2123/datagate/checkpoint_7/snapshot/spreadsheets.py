"""Reading the first worksheet of an .xls or .xlsx workbook into a grid of cells."""

import io
import zipfile

import openpyxl
import xlrd
from openpyxl.utils.exceptions import InvalidFileException
from xlrd.compdoc import CompDocError

from csv_parsing import infer_value
from errors import DatagateError
from store import Cell, Grid


def read_xlsx_grid(data: bytes) -> Grid:
    """Read the first worksheet of an .xlsx workbook, taking cached values over formulas."""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError) as exc:
        raise DatagateError(400, "Source content is not a readable .xlsx workbook") from exc
    rows = workbook.worksheets[0].iter_rows(values_only=True)
    grid = [[_cell_value(raw) for raw in row] for row in rows]
    workbook.close()
    return grid


def read_xls_grid(data: bytes) -> Grid:
    """Read the first worksheet of a legacy .xls workbook."""
    try:
        sheet = xlrd.open_workbook(file_contents=data).sheet_by_index(0)
    except (xlrd.XLRDError, CompDocError) as exc:
        raise DatagateError(400, "Source content is not a readable .xls workbook") from exc
    return [[_cell_value(raw) for raw in sheet.row_values(index)] for index in range(sheet.nrows)]


def _cell_value(raw: object) -> Cell:
    """Give spreadsheet cells the same types the CSV reader produces.

    Numbers stay numbers, whole floats narrowing to int because .xls stores every number as a
    float. Everything else — dates, booleans, blanks — is read as text and then inferred the
    way CSV text is, so the same table has the same types whichever format it arrived in.
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(raw) if isinstance(raw, float) and raw.is_integer() else raw
    return "" if raw is None else infer_value(str(raw))
