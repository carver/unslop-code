"""Reading each input format into a common stream of row mappings."""
from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from typing import Iterator, TextIO

from .cli import Options
from .csvio import reader_dialect
from .errors import EXIT_NESTED, EXIT_SOURCE, MergeError, NESTED_REFUSAL
from .formats import InputFile, Source, open_text
from .parquetio import open_parquet
from .values import prefer_ints


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
def open_jsonl(source: InputFile, nested_allowed: bool):
    """Open a JSON Lines input; its columns are only known once the lines are read."""
    with open_text(source, newline="\n") as stream:
        yield Source((), _jsonl_rows(source.path, stream, nested_allowed), typed=True)


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


def _jsonl_rows(path: str, stream: TextIO, nested_allowed: bool) -> Iterator[dict]:
    for number, line in enumerate(stream, start=1):
        if line.strip():
            yield _parse_object(line, f"{path}:{number}", nested_allowed)


def _parse_object(line: str, where: str, nested_allowed: bool) -> dict:
    """One JSON Lines record: an object, with its numbers normalised.

    Nested values are only read when a `--schema` declares what they are; there
    is no inferred type for them otherwise.
    """
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MergeError(f"{where}: invalid JSON ({exc.msg})", EXIT_SOURCE) from None
    if not isinstance(record, dict):
        raise MergeError(f"{where}: expected one JSON object per line", EXIT_SOURCE)
    if not nested_allowed and any(isinstance(value, (list, dict)) for value in record.values()):
        raise MergeError(NESTED_REFUSAL, EXIT_NESTED)
    return prefer_ints(record)


#: How each format is opened. Every entry returns a `Source` context manager.
_OPENERS = {
    "csv": lambda src, opts, nested: open_delimited(
        src, reader_dialect(opts.quotechar, opts.escapechar)),
    "tsv": lambda src, opts, nested: open_tsv(src),
    "jsonl": lambda src, opts, nested: open_jsonl(src, nested),
    "parquet": lambda src, opts, nested: open_parquet(
        src, opts.parquet_row_group_bytes, nested),
}


def open_source(source: InputFile, options: Options, nested_allowed: bool = False):
    """Open one resolved input as a `Source`, in whatever format it was detected as."""
    return _OPENERS[source.format](source, options, nested_allowed)
