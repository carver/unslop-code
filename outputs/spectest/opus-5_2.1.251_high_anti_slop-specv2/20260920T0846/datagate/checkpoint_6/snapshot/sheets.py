"""Reading the first worksheet out of an ``.xls`` or ``.xlsx`` workbook."""

import io

import openpyxl
import xlrd

from errors import ApiError

# Workbook formats announce themselves in their first bytes: ``.xlsx`` files
# are ZIP archives, ``.xls`` files are OLE2 compound documents.
XLSX_SIGNATURE = b"PK\x03\x04"
XLS_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def looks_like_workbook(payload: bytes) -> bool:
    """Report whether a payload carries a spreadsheet signature."""
    return payload.startswith((XLSX_SIGNATURE, XLS_SIGNATURE))


def read_workbook(payload: bytes) -> list[list[str]]:
    """Return the cells of the workbook's first worksheet, row by row.

    Only the first sheet is ingested, and every cell is rendered as the text
    the spreadsheet shows so one type inference can serve every format.

    A payload that merely looks like a workbook — a plain ZIP archive, a
    truncated document — is rejected by the reader for it, each through its own
    exception hierarchy, so whatever they raise becomes one "unreadable" answer.
    """
    read = _read_xlsx if payload.startswith(XLSX_SIGNATURE) else _read_xls
    try:
        return read(payload)
    except Exception as exc:
        raise ApiError("Source is not a readable spreadsheet", 400) from exc


def _read_xlsx(payload: bytes) -> list[list[str]]:
    workbook = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    try:
        return [[_cell_text(cell) for cell in row] for row in workbook.worksheets[0].values]
    finally:
        workbook.close()


def _read_xls(payload: bytes) -> list[list[str]]:
    sheet = xlrd.open_workbook(file_contents=payload).sheet_by_index(0)
    return [[_cell_text(cell) for cell in sheet.row_values(index)] for index in range(sheet.nrows)]


def _cell_text(value) -> str:
    """Render one cell as the text a spreadsheet would display for it.

    Both readers report whole numbers as floats where a sheet shows an integer,
    so the trailing ``.0`` goes before type inference ever sees the value.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
