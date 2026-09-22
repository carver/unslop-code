"""Recognising which of the accepted formats an ingested payload is.

The format comes from the payload's own bytes rather than from a filename or a
declared media type (T42): both spreadsheet formats have a fixed container
signature, while everything else is handed to the CSV text path. Signatures that
belong to other document formats are rejected outright (T43).
"""

from dataclasses import dataclass
from enum import Enum

from .errors import DataGateError


class SourceFormat(Enum):
    """The formats `/convert` and `/upload` ingest."""

    CSV = "csv"
    XLS = "xls"
    XLSX = "xlsx"


@dataclass(frozen=True)
class SourceDocument:
    """A payload to ingest, plus the media type whoever sent it claimed."""

    data: bytes
    content_type: str = ""


# An `.xlsx` is a ZIP archive; an `.xls` is an OLE2 compound file.
_WORKBOOK_SIGNATURES = (
    (b"PK\x03\x04", SourceFormat.XLSX),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", SourceFormat.XLS),
)
# Formats that identify themselves clearly and are documents rather than tables.
_FOREIGN_SIGNATURES = (b"%PDF-", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"\x1f\x8b")


def detect_format(data: bytes) -> SourceFormat:
    """Name the format of `data`, or reject it as one we do not ingest."""
    for signature, source_format in _WORKBOOK_SIGNATURES:
        if data.startswith(signature):
            return source_format
    if data.startswith(_FOREIGN_SIGNATURES):
        raise DataGateError("Unrecognized format: expected CSV, .xls or .xlsx", 400)
    return SourceFormat.CSV
