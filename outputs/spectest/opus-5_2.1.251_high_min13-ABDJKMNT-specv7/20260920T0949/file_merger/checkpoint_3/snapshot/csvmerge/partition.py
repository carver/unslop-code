"""Routing the sorted stream into a partitioned directory of part files."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .hive import directory
from .shards import ShardLimits, ShardWriter
from .writer import RowFormatter


@dataclass(frozen=True)
class PartitionPlan:
    """How the result is split: by which columns, under which file limits."""

    columns: tuple[str, ...]
    limits: ShardLimits

    @property
    def to_directory(self) -> bool:
        """Whether any partitioning flag was given, which makes the output a tree."""
        return bool(self.columns) or self.limits.bounded


class PartitionedWriter:
    """One shard sequence per partition directory, fed by a grouped stream.

    Rows arrive grouped by partition value - the sort key leads with the
    partition segments - so a directory is finished before the next one starts
    and only one part file is ever open.
    """

    def __init__(self, root: Path, columns, header: str, limits: ShardLimits):
        self._root = root
        self._columns = columns
        self._header = header
        self._limits = limits
        self._segments = None
        self._writer = None

    def write(self, segments, text: str) -> None:
        if self._writer is None or segments != self._segments:
            self.close()
            self._segments = segments
            target = directory(self._root, self._columns, segments)
            self._writer = ShardWriter(target, self._header, self._limits)
        self._writer.write(text)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None


def write_partitions(root: Path, header, rows, plan: PartitionPlan, fmt) -> None:
    """Write the sorted stream under ``root`` as part files.

    Each row arrives as its ``(key parts, cells)`` pair; the leading key parts
    are the row's partition segments. With no partition columns there are no
    such parts and every row lands in one shard sequence directly under
    ``root``.
    """
    formatter = RowFormatter(fmt)
    depth = len(plan.columns)
    writer = PartitionedWriter(root, plan.columns, formatter.text(header), plan.limits)
    with closing(writer):
        for parts, cells in rows:
            writer.write(parts[:depth], formatter.text(cells))
