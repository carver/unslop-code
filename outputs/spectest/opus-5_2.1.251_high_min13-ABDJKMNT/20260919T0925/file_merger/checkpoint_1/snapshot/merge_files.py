#!/usr/bin/env python3
"""Merge multiple CSV files into one schema-aligned, globally sorted CSV.

    python merge_files.py --output <PATH|-> --key <col>[,<col>...] [options] <INPUT.csv> ...

See AMBIGUITIES.md for the interpretations chosen where the specification is silent.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import closing
from pathlib import Path

from csvmerge.coltypes import render
from csvmerge.errors import MergeError
from csvmerge.reader import InputDialect, read_header, read_records
from csvmerge.rows import COERCE_NULL, POLICIES, RowCaster
from csvmerge.schema import LOOSE, STRICT, SchemaInferrer, load_schema
from csvmerge.sorting import ExternalSorter, SortOrder
from csvmerge.writer import open_output, write_rows

#: Share of the memory limit given to the sorter's row buffer; the rest covers the
#: interpreter, the CSV reader, and the merge phase's per-run lookahead.
_BUFFER_SHARE = 0.5


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV files into one schema-aligned, sorted CSV.",
    )
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument("--key", required=True, help="comma-separated sort key columns")
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument("--schema", help="schema JSON file (or inline JSON document)")
    parser.add_argument("--infer", choices=(STRICT, LOOSE), default=STRICT)
    parser.add_argument("--on-type-error", choices=POLICIES, default=COERCE_NULL)
    parser.add_argument("--memory-limit-mb", type=int, default=64)
    parser.add_argument("--temp-dir", help="directory for spilled sort runs")
    parser.add_argument("--csv-quotechar", default='"')
    parser.add_argument("--csv-escapechar", default=None)
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    return parser.parse_args(argv)


def resolve_schema(args, inputs, dialect):
    """Return the output schema, from `--schema` or inferred from the inputs."""
    if args.schema:
        return load_schema(args.schema)

    inferrer = SchemaInferrer(args.infer)
    for path in inputs:
        inferrer.add_header(read_header(path, dialect))
        for _, record in read_records(path, dialect):
            for name, text in record.items():
                if text is not None:
                    inferrer.observe(name, text)
        inferrer.end_file()
    return inferrer.resolve()


def build_order(schema, key_spec, descending):
    """Map `--key` column names onto the resolved schema."""
    names = schema.names
    keys = key_spec.split(",")
    missing = [key for key in keys if key not in names]
    if missing:
        raise MergeError(f"key column(s) not in resolved schema: {', '.join(missing)}")
    return SortOrder([names.index(key) for key in keys], descending)


def load_rows(sorter, inputs, dialect, caster, order, null_literal):
    """Cast every input row and feed it to the sorter in input-appearance order."""
    index = 0
    for path in inputs:
        for line_number, record in read_records(path, dialect):
            values = caster.cast_row(record, f"{path}:{line_number}")
            cells = [render(value, null_literal) for value in values]
            sorter.add(order.key_of(values), index, cells)
            index += 1


def run(args):
    dialect = InputDialect(args.csv_quotechar, args.csv_escapechar)
    inputs = [Path(path) for path in args.inputs]
    schema = resolve_schema(args, inputs, dialect)
    order = build_order(schema, args.key, args.desc)
    caster = RowCaster(schema, args.on_type_error)
    budget = int(args.memory_limit_mb * 1024 * 1024 * _BUFFER_SHARE)

    with closing(ExternalSorter(order, budget, args.temp_dir)) as sorter:
        load_rows(sorter, inputs, dialect, caster, order, args.csv_null_literal)
        with open_output(args.output) as stream:
            write_rows(stream, schema.names, sorter.merged())


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except MergeError as error:
        print(f"merge_files.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
