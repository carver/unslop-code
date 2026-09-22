"""Recognising which of the supported wire formats a payload arrived in."""

from enum import Enum

from .errors import DatagateError


class Format(Enum):
    """The ingestion formats `/convert` and `/upload` accept."""

    CSV = "csv"
    XLS = "xls"
    XLSX = "xlsx"


# `.xlsx` is a zip container and `.xls` an OLE2 compound document, so both are
# identified by their container signature rather than by a filename or a served
# content type, neither of which a source is obliged to get right (AMBIGUITIES T39).
SIGNATURES = {
    b"PK\x03\x04": Format.XLSX,
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": Format.XLS,
}

# Formats that are unmistakable and unsupported. Anything else falls through to
# the CSV reader, which answers 400 for whatever turns out not to be a table.
REJECTED = {
    b"%PDF": "PDF",
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"\xff\xd8\xff": "JPEG",
    b"GIF8": "GIF",
    b"\x1f\x8b": "gzip",
    b"\x7fELF": "ELF",
    b"BZh": "bzip2",
}


def detect_format(raw):
    """Return the `Format` of `raw`, raising a 400 for a recognisably unsupported one."""
    for signature, name in REJECTED.items():
        if raw.startswith(signature):
            raise DatagateError(
                400, f"Unrecognized format: {name} is not CSV, .xls or .xlsx."
            )

    for signature, detected in SIGNATURES.items():
        if raw.startswith(signature):
            return detected
    return Format.CSV
