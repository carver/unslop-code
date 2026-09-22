"""Turning downloaded CSV bytes into text."""

import codecs

from .errors import ApiError

FALLBACK_ENCODING = "latin-1"

# Ordered longest-first: the UTF-32 marks start with the UTF-16 ones.
BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_bytes(raw: bytes, charset: str | None) -> str:
    """Decode `raw`, using `charset` when the caller supplied one.

    A charset the caller names is applied strictly: an unknown codec name and
    bytes the codec rejects are both reported as a malformed charset.
    """
    if charset is None:
        return _detect_and_decode(raw)
    try:
        return raw.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ApiError(400, f"unsupported or malformed charset '{charset}': {exc}") from exc


def _detect_and_decode(raw: bytes) -> str:
    """Decode without a hint: a BOM or clean UTF-8 is the only unambiguous
    evidence of an encoding, so everything else falls back to latin-1."""
    encoding = _bom_encoding(raw) or "utf-8"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return raw.decode(FALLBACK_ENCODING)


def _bom_encoding(raw: bytes) -> str | None:
    for bom, encoding in BOM_ENCODINGS:
        if raw.startswith(bom):
            return encoding
    return None
