"""Turning fetched bytes into text, either with a declared charset or by detection."""

import codecs

from charset_normalizer import from_bytes

from datagate_core.errors import CharsetError

BOM = "\ufeff"


def decode(data: bytes, charset: str | None) -> str:
    """Decode `data` with `charset` when given, otherwise with a detected encoding."""
    text = _decode_as(data, charset) if charset else _detect_and_decode(data)
    return text.lstrip(BOM)


def _decode_as(data: bytes, charset: str) -> str:
    """Decode strictly with a caller-supplied encoding name."""
    try:
        codecs.lookup(charset)
    except (LookupError, TypeError, ValueError):
        raise CharsetError(f"unsupported or malformed charset: {charset!r}")
    try:
        return data.decode(charset)
    except (UnicodeDecodeError, ValueError):
        raise CharsetError(f"charset {charset!r} cannot decode the source bytes")


def _detect_and_decode(data: bytes) -> str:
    """Detect the encoding from the content itself."""
    detected = from_bytes(data).best()
    if detected is None:
        return data.decode("utf-8", errors="replace")
    return str(detected)
