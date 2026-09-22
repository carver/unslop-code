"""Turning fetched bytes into text.

An explicit ``charset`` always wins. Without one the encoding is detected, but
only from evidence that cannot be misread: a byte order mark, or a payload that
decodes as strict UTF-8. Everything else falls back to latin-1, which accepts
any byte sequence.
"""

import codecs

from .errors import DataGateError

FALLBACK_ENCODING = "latin-1"

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def detect_encoding(data: bytes) -> str:
    """Name the encoding that `data` unambiguously uses, else the fallback."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return encoding
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return FALLBACK_ENCODING
    return "utf-8"


def decode_document(data: bytes, charset: str | None = None) -> str:
    """Decode `data` with `charset`, or with the detected encoding when omitted."""
    encoding = charset if charset is not None else detect_encoding(data)
    try:
        text = data.decode(encoding)
    except LookupError:
        raise DataGateError(f"Unsupported charset: {charset!r}", 400) from None
    except UnicodeDecodeError:
        raise DataGateError(f"Content is not valid {encoding!r} text", 400) from None
    return text.removeprefix("\ufeff")
