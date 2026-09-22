"""Decoding of raw payloads and parsing of their CSV content."""

import codecs
import csv
import io
from collections import Counter

from charset_normalizer import from_bytes

from gateway.errors import GateError

FALLBACK_ENCODING = "latin-1"
DELIMITERS = (",", ";", "\t")
#: Openings of formats that are recognisable, but never a table.
FOREIGN_PREFIXES = ("<", "{", "[", "%PDF-")
BOM = "\ufeff"
#: Share of rows that must agree on a field count for a delimiter to be trusted.
CONSISTENCY_THRESHOLD = 0.9


def detect_encoding(payload: bytes) -> str:
    """Return the encoding of ``payload`` when detection is unambiguous, else latin-1.

    Self-describing encodings such as UTF-8, UTF-16 and ASCII leave a single
    plausible reading of the bytes. Legacy single-byte encodings do not: one
    high byte is a different letter in cp1250 than in cp1252, and nothing in the
    content settles it, so whenever candidates disagree latin-1 decides.
    """
    candidates = list(from_bytes(payload))
    if not candidates or len({match.fingerprint for match in candidates}) > 1:
        return FALLBACK_ENCODING
    return candidates[0].encoding


def decode_payload(payload: bytes, charset: str | None) -> str:
    """Decode ``payload`` with the requested ``charset``, or with a detected one."""
    if charset is None:
        return payload.decode(detect_encoding(payload))

    try:
        codecs.lookup(charset)
    except LookupError as exc:
        raise GateError(f"Unsupported charset: {charset!r}", 400) from exc

    try:
        return payload.decode(charset)
    except UnicodeDecodeError as exc:
        raise GateError(f"Source content is not valid {charset} text", 400) from exc


def parse_csv(text: str) -> list[list[str]]:
    """Split CSV ``text`` into its rows, the header row first.

    Content that carries no table at all -- markup, a document, a binary
    blob -- is rejected here; whether the rows form a usable table is decided
    later.
    """
    text = text.lstrip(BOM).strip()
    if not text or "\x00" in text or text.startswith(FOREIGN_PREFIXES):
        raise GateError("Source content is not tabular", 400)
    return split_rows(text)


def split_rows(text: str) -> list[list[str]]:
    """Parse ``text`` with the delimiter that yields the widest coherent table.

    Candidates are compared on how many fields they produce and on how many
    rows agree on that count, so a file using ``;`` is not mistaken for a
    single-column table just because it contains no commas.
    """
    chosen_rows = read_rows(text, DELIMITERS[0])
    widest = 1
    for delimiter in DELIMITERS:
        rows = read_rows(text, delimiter)
        width, share = dominant_width(rows)
        if width > widest and share >= CONSISTENCY_THRESHOLD:
            chosen_rows, widest = rows, width
    return chosen_rows


def read_rows(text: str, delimiter: str) -> list[list[str]]:
    """Parse ``text`` as CSV, dropping rows that hold no content."""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def dominant_width(rows: list[list[str]]) -> tuple[int, float]:
    """Return the most common field count and the share of rows having it."""
    counts = Counter(len(row) for row in rows)
    width, matching = counts.most_common(1)[0]
    return width, matching / len(rows)
