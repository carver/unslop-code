"""Turning raw CSV bytes into text, either with a named charset or by detection."""

import codecs

from charset_normalizer import from_bytes

from .errors import DatagateError

BOM = "﻿"


def decode_csv_bytes(raw, charset=None):
    """Decode `raw` using `charset` when given, otherwise by detecting the encoding."""
    text = _decode_with(raw, charset) if charset is not None else _decode_detected(raw)
    return text.lstrip(BOM)


def _decode_with(raw, charset):
    try:
        codecs.lookup(charset)
    except (LookupError, TypeError) as error:
        raise DatagateError(400, f"Unsupported charset: {charset!r}.") from error

    try:
        return raw.decode(charset)
    except (UnicodeDecodeError, ValueError) as error:
        raise DatagateError(
            400,
            f"Content could not be decoded as {charset!r}; "
            "the charset is malformed for this source.",
        ) from error


def _decode_detected(raw):
    best = from_bytes(raw).best()
    if best is not None:
        return str(best)

    # Detection only comes up empty for input it cannot make sense of. UTF-8 is the
    # likely intent, and latin-1 accepts any byte sequence, so this always terminates.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
