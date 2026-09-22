#!/usr/bin/env python3
"""Merge heterogeneous inputs into one schema-aligned, globally sorted CSV.

    python merge_files.py --output <PATH|-> --key <col>[,<col>...] [options] <INPUT> ...

Inputs may be CSV, TSV, JSON Lines or Parquet, optionally gzipped; the output is
always a single CSV. See AMBIGUITIES.md for the interpretations chosen where the
specification is silent.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import closing
from pathlib import Path

from csvmerge.coltypes import render
from csvmerge.dialect import CsvDialect
from csvmerge.errors import MergeError, MissingKeyError
from csvmerge.formats import (
    COMPRESSIONS,
    DEFAULT_PARQUET_BATCH_BYTES,
    INPUT_FORMATS,
    InputOptions,
    open_source,
)
from csvmerge.inference import AUTHORITATIVE, STRATEGIES, SchemaInferrer
from csvmerge.rows import COERCE_NULL, POLICIES, RowCaster
from csvmerge.schema import INFER_MODES, STRICT, load_schema
from csvmerge.sorting import ExternalSorter, SortOrder
from csvmerge.writer import open_output, write_rows

#: Share of the memory limit given to the sorter's row buffer; the rest covers the
#: interpreter, the source readers, and the merge phase's per-run lookahead.
_BUFFER_SHARE = 0.5


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and Parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument("--key", required=True, help="comma-separated sort key columns")
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument("--schema", help="schema JSON file (or inline JSON document)")
    parser.add_argument("--infer", choices=INFER_MODES, default=STRICT)
    parser.add_argument("--schema-strategy", choices=STRATEGIES, default=AUTHORITATIVE)
    parser.add_argument("--on-type-error", choices=POLICIES, default=COERCE_NULL)
    parser.add_argument("--memory-limit-mb", type=int, default=64)
    parser.add_argument("--temp-dir", help="directory for spilled sort runs")
    parser.add_argument("--csv-quotechar", default='"')
    parser.add_argument("--csv-escapechar", default=None)
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument("--input-format", choices=INPUT_FORMATS, default="auto")
    parser.add_argument("--compression", choices=COMPRESSIONS, default="auto")
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=DEFAULT_PARQUET_BATCH_BYTES,
        help="advisory byte budget for one Parquet read batch",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser.parse_args(argv)


def input_options(args):
    """Collect everything the flags say about reading inputs."""
    return InputOptions(
        dialect=CsvDialect(args.csv_quotechar, args.csv_escapechar),
        input_format=args.input_format,
        compression=args.compression,
        parquet_batch_bytes=args.parquet_row_group_bytes,
    )


def resolve_schema(args, sources):
    """Return the output schema, from `--schema` or inferred from every source."""
    if args.schema:
        return load_schema(args.schema)

    inferrer = SchemaInferrer(args.infer, args.schema_strategy)
    for source in sources:
        inferrer.declare(source.fields())
        for _, record in source.records():
            inferrer.observe(record)
        inferrer.end_file(source.tier)
    return inferrer.resolve()


def build_order(schema, key_spec, descending):
    """Map `--key` column names onto the resolved schema."""
    names = schema.names
    keys = key_spec.split(",")
    missing = [key for key in keys if key not in names]
    if missing:
        raise MissingKeyError(f"key column(s) not in resolved schema: {', '.join(missing)}")
    return SortOrder([names.index(key) for key in keys], descending)


def load_rows(sorter, sources, caster, order, null_literal):
    """Cast every input row and feed it to the sorter in input-appearance order."""
    index = 0
    for source in sources:
        for origin, record in source.records():
            values = caster.cast_row(record, origin)
            sorter.add(order.key_of(values), index, [render(value, null_literal) for value in values])
            index += 1


def run(args):
    options = input_options(args)
    sources = [open_source(Path(path), options) for path in args.inputs]
    schema = resolve_schema(args, sources)
    order = build_order(schema, args.key, args.desc)
    caster = RowCaster(schema, args.on_type_error)
    budget = int(args.memory_limit_mb * 1024 * 1024 * _BUFFER_SHARE)

    with closing(ExternalSorter(order, budget, args.temp_dir)) as sorter:
        load_rows(sorter, sources, caster, order, args.csv_null_literal)
        with open_output(args.output) as stream:
            write_rows(stream, schema.names, sorter.merged(), options.dialect)


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except MergeError as error:
        print(f"merge_files.py: {error}", file=sys.stderr)
        return error.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
