"""Reading the first worksheet of an `.xls` or `.xlsx` workbook.

A workbook is recognised by its magic bytes rather than by a filename, so the
same rules apply to an uploaded file and to one fetched from a URL. Each reader
returns the sheet as a grid of typed cells; `tabular.shape_table` then gives it
the header and the row width every dataset has.
"""

import io
import math
from zipfile import BadZipFile

import openpyxl
import xlrd

from .errors import ApiError
from .tabular import Cell, coerce

XLSX_SIGNATURE = b"PK\x03\x04"
XLS_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def read_xlsx(raw: bytes) -> list[list[Cell]]:
    """The first worksheet of an `.xlsx` workbook, formulas read as cached values.

    A ZIP that is not a workbook shares the signature, so an unreadable archive
    is reported as the unsupported format it is.
    """
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    except (BadZipFile, KeyError) as exc:
        raise ApiError(400, f"file is not a readable .xlsx workbook: {exc}") from exc
    rows = _content_rows(workbook.worksheets[0].iter_rows(values_only=True))
    workbook.close()
    return rows


def read_xls(raw: bytes) -> list[list[Cell]]:
    """The first worksheet of a legacy `.xls` workbook."""
    try:
        workbook = xlrd.open_workbook(file_contents=raw)
    except (xlrd.XLRDError, xlrd.compdoc.CompDocError) as exc:
        raise ApiError(400, f"file is not a readable .xls workbook: {exc}") from exc
    sheet = workbook.sheet_by_index(0)
    return _content_rows(sheet.row_values(index) for index in range(sheet.nrows))


def workbook_reader(raw):
    """The reader for the format `raw` announces, or `None` when it is not a
    workbook at all."""
    for signature, reader in ((XLSX_SIGNATURE, read_xlsx), (XLS_SIGNATURE, read_xls)):
        if raw.startswith(signature):
            return reader
    return None


def _content_rows(rows) -> list[list[Cell]]:
    """The sheet's rows as dataset values, minus the wholly empty ones.

    Spreadsheets carry blank rows a viewer never shows, and counting them as
    data would make a table tabular in one format and not in another.
    """
    typed = [[_value(cell) for cell in row] for row in rows]
    return [row for row in typed if any(cell != "" for cell in row)]


def _value(cell) -> Cell:
    """One workbook cell as a dataset value.

    The workbook's own types carry over, so a date keeps its spelling and a
    number stays a number; a text cell is read like a CSV field, which keeps a
    text-formatted `36` sortable as the number the sheet displays.
    """
    return CONVERTERS.get(type(cell), str)(cell)


def _number(value: int | float) -> Cell:
    """A whole number reads as an integer, so `.xls` floats match CSV's `36`.

    Values JSON cannot spell stay text, exactly as in `tabular.coerce`.
    """
    if not math.isfinite(value):
        return str(value)
    return int(value) if value == int(value) else value


# Keyed by exact type, so `bool` never reaches the numeric reader.
CONVERTERS = {
    type(None): lambda _blank: "",
    bool: str,
    int: _number,
    float: _number,
    str: coerce,
}
