"""The merge pipeline: resolve a schema, stream, sort, write."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .casting import TypeErrorPolicy
from .csvio import open_output, write_csv
from .dialect import CsvDialect
from .records import iter_records
from .schema import InferMode, Schema, infer_schema, load_schema
from .sorting import ExternalSorter


@dataclass(frozen=True)
class MergeConfig:
    """Everything the pipeline needs, already validated by the CLI."""

    inputs: Sequence[str]
    output: str
    keys: Sequence[str]
    descending: bool
    schema_path: str | None
    infer_mode: InferMode
    policy: TypeErrorPolicy
    memory_limit_mb: int
    temp_dir: str | None
    dialect: CsvDialect


def run_merge(config: MergeConfig) -> None:
    """Merge the inputs into one globally sorted CSV."""
    schema = _resolve_schema(config)
    key_indexes = [schema.index_of(name) for name in config.keys]
    records = iter_records(config.inputs, schema, config.dialect, config.policy, key_indexes)
    sorter = ExternalSorter(
        descending=config.descending,
        memory_limit_mb=config.memory_limit_mb,
        temp_dir=config.temp_dir,
    )
    with sorter:
        # Sorting drains every input first, so a fatal cast error is reported
        # before the output is opened and an existing file is truncated.
        ordered = sorter.sort(records)
        with open_output(config.output) as stream:
            write_csv(stream, config.dialect, schema.names, (record.row for record in ordered))


def _resolve_schema(config: MergeConfig) -> Schema:
    if config.schema_path is not None:
        return load_schema(config.schema_path)
    return infer_schema(config.inputs, config.dialect, config.infer_mode)
