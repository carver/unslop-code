"""Reading each input format into a common stream of row mappings."""
from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from typing import Iterator, TextIO

from .cli import Options
from .csvio import reader_dialect
from .errors import EXIT_NESTED, EXIT_SOURCE, MergeError
from .formats import InputFile, Source, open_text
from .parquetio import open_parquet

#: JSON numbers above this magnitude stay floats rather than becoming ints.
_INT64_LIMIT = 2 ** 63


@contextmanager
def open_delimited(source: InputFile, dialect: dict):
    """Open a CSV input: a header row, then rows parsed with the CSV dialect."""
    with open_text(source, newline="") as stream:
        rows = csv.reader(stream, **dialect)
        header = next(rows, [])
        yield Source(
            tuple(header),
            (dict(zip(header, row)) for row in rows if row),
            typed=False,
            first_row=2,
        )


@contextmanager
def open_tsv(source: InputFile):
    """Open a TSV input: tab-delimited, unquoted, with a required header row."""
    with open_text(source, newline="\n") as stream:
        header = next(stream, "").rstrip("\n").split("\t")
        yield Source(tuple(header), _tsv_rows(source.path, header, stream), typed=False,
                     first_row=2)


@contextmanager
def open_jsonl(source: InputFile):
    """Open a JSON Lines input; its columns are only known once the lines are read."""
    with open_text(source, newline="\n") as stream:
        yield Source((), _jsonl_rows(source.path, stream), typed=True)


def _tsv_rows(path: str, header: list[str], stream: TextIO) -> Iterator[dict]:
    for number, line in enumerate(stream, start=2):
        fields = line.rstrip("\n").split("\t")
        if fields == [""]:
            continue
        if len(fields) > len(header):
            raise MergeError(
                f"{path}:{number}: {len(fields)} fields for {len(header)} columns, "
                "so a field contains a literal tab",
                EXIT_SOURCE,
            )
        yield dict(zip(header, fields))


def _jsonl_rows(path: str, stream: TextIO) -> Iterator[dict]:
    for number, line in enumerate(stream, start=1):
        if line.strip():
            yield _parse_object(line, f"{path}:{number}")


def _parse_object(line: str, where: str) -> dict:
    """One JSON Lines record: a flat object, with its numbers normalised."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MergeError(f"{where}: invalid JSON ({exc.msg})", EXIT_SOURCE) from None
    if not isinstance(record, dict):
        raise MergeError(f"{where}: expected one JSON object per line", EXIT_SOURCE)

    nested = [name for name, value in record.items() if isinstance(value, (list, dict))]
    if nested:
        raise MergeError(
            f"{where}: nested value in field(s) {', '.join(sorted(nested))}", EXIT_NESTED
        )
    return {name: _prefer_int(value) for name, value in record.items()}


def _prefer_int(value):
    """A JSON number is an int when it is integral and fits a 64-bit integer."""
    if type(value) is float and value.is_integer() and abs(value) < _INT64_LIMIT:
        return int(value)
    return value


#: How each format is opened. Every entry returns a `Source` context manager.
_OPENERS = {
    "csv": lambda src, opts: open_delimited(src, reader_dialect(opts.quotechar, opts.escapechar)),
    "tsv": lambda src, opts: open_tsv(src),
    "jsonl": lambda src, opts: open_jsonl(src),
    "parquet": lambda src, opts: open_parquet(src, opts.parquet_row_group_bytes),
}


def open_source(source: InputFile, options: Options):
    """Open one resolved input as a `Source`, in whatever format it was detected as."""
    return _OPENERS[source.format](source, options)
