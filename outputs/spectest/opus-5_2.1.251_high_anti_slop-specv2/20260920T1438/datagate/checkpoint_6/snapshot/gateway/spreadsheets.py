"""Reading the first worksheet of an ``.xls`` or ``.xlsx`` workbook."""

import io
from zipfile import BadZipFile

import xlrd
from openpyxl import load_workbook
from xlrd.compdoc import CompDocError

from gateway.errors import GateError

#: Leading bytes of the ZIP container an ``.xlsx`` workbook is packed into.
XLSX_MAGIC = b"PK\x03\x04"
#: Leading bytes of the OLE2 compound document holding a legacy ``.xls`` workbook.
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

#: What the two libraries raise for a container they cannot read as a workbook:
#: a truncated archive, a ZIP carrying something else than a workbook -- a
#: ``.docx`` say -- or an ``.xls`` whose record stream is unusable.
UNREADABLE = (BadZipFile, KeyError, OSError, xlrd.XLRDError, CompDocError)


def is_workbook(payload: bytes) -> bool:
    """Report whether ``payload`` is packaged as one of the workbook formats."""
    return payload.startswith((XLSX_MAGIC, XLS_MAGIC))


def read_sheet(payload: bytes) -> list[list[str]]:
    """Return the rows of the first worksheet, as text cells in source order.

    Later worksheets are ignored, and rows holding no content are dropped, so
    the trailing blanks a spreadsheet editor leaves behind do not become rows.
    """
    read = read_xlsx if payload.startswith(XLSX_MAGIC) else read_xls
    try:
        rows = read(payload)
    except UNREADABLE as exc:
        raise GateError(f"Source is not a readable workbook: {exc}", 400) from exc
    return [row for row in rows if any(cell.strip() for cell in row)]


def read_xlsx(payload: bytes) -> list[list[str]]:
    """Read the first worksheet of an Office Open XML workbook."""
    workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    return [[cell_text(value) for value in row] for row in sheet.values]


def read_xls(payload: bytes) -> list[list[str]]:
    """Read the first worksheet of a legacy BIFF workbook."""
    sheet = xlrd.open_workbook(file_contents=payload).sheet_by_index(0)
    return [
        [cell_text(value) for value in sheet.row_values(index)]
        for index in range(sheet.nrows)
    ]


def cell_text(value: object) -> str:
    """Render one cell as the text its CSV equivalent would carry.

    Spreadsheets store every number as a float, so whole numbers are written
    without their trailing ``.0`` and read back as integers, exactly as the
    same table written as CSV would be.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
