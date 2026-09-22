"""The merge pipeline: resolve a schema, stream, sort, write."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .casting import TypeErrorPolicy
from .output import open_output, write_csv
from .partitioning import PartitionScheme
from .paths import FieldPath, resolve
from .records import iter_records
from .schema import InferMode, Schema, SchemaStrategy, infer_schema, load_schema
from .shards import ShardLimits, atomic_directory, write_tree
from .sorting import ExternalSorter, Record
from .sources import Compression, InputFormat, InputSpec, ReadOptions, detect_input
from .typespec import load_aliases


@dataclass(frozen=True)
class MergeConfig:
    """Everything the pipeline needs, already validated by the CLI."""

    inputs: Sequence[str]
    output: str
    keys: Sequence[FieldPath]
    descending: bool
    partition_by: Sequence[FieldPath]
    limits: ShardLimits
    schema_path: str | None
    alias_path: str | None
    infer_mode: InferMode
    strategy: SchemaStrategy
    policy: TypeErrorPolicy
    memory_limit_mb: int
    temp_dir: str | None
    options: ReadOptions
    input_format: InputFormat
    compression: Compression

    @property
    def writes_directory(self) -> bool:
        """Report whether the output is a tree of part files rather than one CSV."""
        return bool(self.partition_by) or self.limits.bounded


def run_merge(config: MergeConfig) -> None:
    """Merge the inputs into one sorted CSV, or into a directory of part files."""
    specs = [detect_input(path, config.input_format, config.compression) for path in config.inputs]
    schema = _resolve_schema(config, specs)
    keys = [resolve(schema, path, "key") for path in config.keys]
    scheme = PartitionScheme.resolve(schema, config.partition_by)
    records = iter_records(
        specs, schema, config.options, config.policy, keys, scheme, config.schema_path is not None
    )
    sorter = ExternalSorter(
        descending=config.descending,
        memory_limit_mb=config.memory_limit_mb,
        temp_dir=config.temp_dir,
    )
    with sorter:
        # Sorting drains every input first, so a fatal cast error is reported
        # before the output is opened and an existing file is truncated.
        _write(config, schema, sorter.sort(records))


def _write(config: MergeConfig, schema: Schema, ordered: Iterable[Record]) -> None:
    if config.writes_directory:
        with atomic_directory(config.output) as pending:
            write_tree(pending, config.options.dialect, schema.names, config.limits, ordered)
        return
    with open_output(config.output) as stream:
        write_csv(stream, config.options.dialect, schema.names, (record.row for record in ordered))


def _resolve_schema(config: MergeConfig, specs: Sequence[InputSpec]) -> Schema:
    """Load the declared schema, or infer a flat one from the inputs themselves.

    The alias table is built either way, so a broken ``--type-alias-file`` is
    reported even when there is no schema to apply it to.
    """
    aliases = load_aliases(config.alias_path)
    if config.schema_path is not None:
        return load_schema(config.schema_path, aliases)
    return infer_schema(specs, config.options, config.infer_mode, config.strategy)
