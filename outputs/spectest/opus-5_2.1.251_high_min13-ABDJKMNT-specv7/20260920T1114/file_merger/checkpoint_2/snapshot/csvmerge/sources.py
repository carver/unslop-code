"""One input file each: what it is, and how its records are produced.

Every reader yields the same shape — a mapping from column name to a value, with
`None` for a missing or null cell — so that schema resolution, casting and sorting
never branch on the input format. Only inference cares whether the values arrived
typed.
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, TextIO

from csvmerge.delimited import read_csv, read_tsv
from csvmerge.detect import JSONL, PARQUET, TSV, open_binary
from csvmerge.dialect import CsvDialect
from csvmerge.jsonl import read_jsonl
from csvmerge.parquetio import open_parquet

Record = dict[str, object]
# Declared column names (empty for JSONL, which only reveals its fields per line)
# together with the file's records.
Contents = tuple[list[str], Iterator[Record]]


@dataclass(frozen=True)
class Source:
    """An input file, resolved to a format and a compression."""

    path: str
    format: str
    compression: str
    dialect: CsvDialect
    parquet_row_group_bytes: int

    @property
    def typed(self) -> bool:
        """Whether this format's values carry a type of their own."""
        return self.format in (JSONL, PARQUET)

    @contextmanager
    def read(self) -> Iterator[Contents]:
        """Open the file and yield its declared columns and its records."""
        with open_binary(self.path, self.compression) as handle:
            if self.format == PARQUET:
                with open_parquet(
                    handle, self.path, self.parquet_row_group_bytes
                ) as contents:
                    yield contents
                return
            with io.TextIOWrapper(handle, encoding="utf-8-sig", newline="") as stream:
                yield self._text_contents(stream)

    def _text_contents(self, stream: TextIO) -> Contents:
        if self.format == JSONL:
            return [], read_jsonl(stream, self.path)
        reader = read_tsv if self.format == TSV else read_csv
        return reader(stream, self.path, self.dialect)
