"""CSV structure: delimiter inference and extraction of a rectangular table."""

import csv
import io
from collections import Counter

from .errors import DatagateError
from .tables import split_header

DELIMITERS = (",", ";", "\t")
SAMPLE_LINES = 25
MARKUP_PREFIXES = ("<", "{", "[")
SOURCE = "a CSV file"


def infer_delimiter(text):
    """Return the delimiter that splits `text` into the most table-like rows.

    Candidates are scored on whether they produce more than one column, then on how
    consistent the row widths are, then on the width itself; ties keep `DELIMITERS`
    order, so a comma wins over a semicolon on equal evidence.
    """
    sample = text.splitlines()[:SAMPLE_LINES]
    return max(DELIMITERS, key=lambda delimiter: _score(sample, delimiter))


def parse_table(text):
    """Split CSV text into header names and string rows, all of the header's width.

    Raises a 400 `DatagateError` for content that is not a table: markup, a payload
    with no inferable delimiter, or a file without both a header and a data row.
    """
    if text.lstrip().startswith(MARKUP_PREFIXES):
        raise DatagateError(400, "Non-tabular content: the source is markup, not a CSV table.")

    columns, rows = split_header(_read_records(text, infer_delimiter(text)), SOURCE)
    if len(columns) < 2:
        raise DatagateError(
            400, "Non-tabular content: no delimiter (',', ';' or tab) separates the columns."
        )
    return columns, rows


def _read_records(text, delimiter):
    """Parse every non-blank CSV record, honouring quoting and embedded newlines."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [record for record in reader if record and record != [""]]


def _score(sample, delimiter):
    widths = [len(record) for record in _read_records("\n".join(sample), delimiter)]
    if not widths:
        return (False, 0.0, 0)

    common, occurrences = Counter(widths).most_common(1)[0]
    return (common > 1, occurrences / len(widths), common)
