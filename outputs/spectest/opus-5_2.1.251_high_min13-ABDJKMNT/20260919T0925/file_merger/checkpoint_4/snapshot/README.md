# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and Parquet inputs, reconciles them
onto one schema, and writes a sorted CSV — a single file, or a directory of
Hive-style partitions and size-capped shards.

```
python merge_files.py --output <PATH|-> --key <fieldPath>[,<fieldPath>...] [--desc]
        [--partition-by <fieldPath>[,<fieldPath>...]]
        [--max-rows-per-file <INT>] [--max-bytes-per-file <INT>]
        [--schema <SCHEMA_JSON>] [--type-alias-file <ALIASES_JSON>] [--infer {strict,loose}]
        [--schema-strategy {authoritative,consensus,union}]
        [--on-type-error {coerce-null,fail,keep-string}]
        [--memory-limit-mb <INT>] [--temp-dir <PATH>]
        [--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>] [--csv-null-literal <STRING>]
        [--input-format {auto,csv,tsv,jsonl,parquet}] [--compression {auto,none,gzip}]
        [--parquet-row-group-bytes <INT>]
        <INPUT1> [<INPUT2> ...]
```

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

## Layout

| Path | Responsibility |
| --- | --- |
| `merge_files.py` | CLI parsing and the read → cast → sort → write pipeline |
| `csvmerge/coltypes.py` | Type vocabulary, priority, text parsing, inference probes, rendering |
| `csvmerge/values.py` | The same two operations for values that arrive already typed |
| `csvmerge/dialect.py` | The CSV dialect shared by the CSV reader and the writer |
| `csvmerge/formats/detect.py` | Format and gzip detection, and opening a source stream |
| `csvmerge/formats/delimited.py` | CSV and TSV readers |
| `csvmerge/formats/jsonl.py` | JSON Lines reader |
| `csvmerge/formats/parquet.py` | Parquet reader, batched over row groups |
| `csvmerge/schema.py` | Schema documents and explicit `--schema` loading |
| `csvmerge/typespec.py` | Declared types: primitives, `struct`, `array<T>`, `map<string,T>`, `json` |
| `csvmerge/aliases.py` | Built-in and `--type-alias-file` type aliases, resolved transitively |
| `csvmerge/paths.py` | `--key` / `--partition-by` field paths, resolved against the schema |
| `csvmerge/inference.py` | Inference, and the `--schema-strategy` reconciliation rules |
| `csvmerge/casting.py` | Casting records — recursively, for nested types — under `--on-type-error` |
| `csvmerge/origin.py` | Where a record came from, as error messages quote it |
| `csvmerge/sorting.py` | Key encoding, direction/null-aware ordering, external merge sort |
| `csvmerge/partition.py` | Hive-style segment names and percent-encoding |
| `csvmerge/shards.py` | Cutting the sorted stream into `part-xxxxx.csv` files |
| `csvmerge/writer.py` | Atomic file or directory output, or stdout |
| `csvmerge/errors.py` | Fatal errors and the exit code each carries |

## How it runs

Inference makes one streaming pass over every source, then the merge pass reads them
again; neither pass holds a whole input in memory. Parquet is read row group by row
group with a batch size derived from `--parquet-row-group-bytes`. Rows are buffered
until they exceed a share of `--memory-limit-mb`, then spilled to temporary files as
sorted runs and k-way merged. Spill files are unlinked at creation and closed on
exit, including on the error path; file output lands through a temporary file in the
destination directory that is renamed into place only once the run succeeds.

## Nested types

`--schema` may declare a column as a `struct` (ordered named fields), an
`array<T>`, a `map<string,T>`, or `json` (any JSON value, normalized but never
cast); nested types compose to any depth. Type names are case-insensitive and go
through the alias table — `integer`, `long`, `double`, `number`, `boolean`,
`datetime`, `timestamptz`, `text`, `varchar`, `list<T>` and `json` are always
present, and `--type-alias-file` adds more, resolved transitively and checked for
cycles. Values are cast recursively; a failure inside a nested value is nulled,
kept as text or fails the run, one field at a time, per `--on-type-error`.

A nested column's cell is canonical JSON: minified UTF-8, struct fields in declared
order, map keys sorted, array order preserved, timestamps normalized to UTC `Z`.
The CSV null literal is used only when the whole column value is null. Nested input
is readable only with a schema: JSONL and Parquet nesting without one is error 6,
and a CSV or TSV cell holds the value as a single JSON literal.

`--key` and `--partition-by` take field paths — `user.id`, `items.0.sku`,
`attrs["country"]` — which traverse structs, index arrays and look up map keys. A
step that cannot be taken yields a null fragment; a path that lands on a struct,
array or map is error 3.

## Partitioned output

Any of `--partition-by`, `--max-rows-per-file` or `--max-bytes-per-file` turns
`--output` into a directory. `--partition-by` sends each combination of values to its
own `<fieldPath>=<value>/` path, with values rendered from their cast form,
percent-encoded, and `_null` standing in for a missing one; the two limits cut each
directory's rows into `part-00000.csv`, `part-00001.csv`, … at the first row that
would breach either. The partition directory leads the sort key, so each directory's
rows arrive together and in `--key` order without holding more than one output file
open. The whole tree is built in a sibling temporary directory and renamed onto
`--output` once the run succeeds.

## Exit codes

| Code | Condition |
| --- | --- |
| 0 | success |
| 1 | any other fatal error (unreadable input, bad schema document, unusable `--output`) |
| 2 | input format could not be determined |
| 2 | a type alias resolves back to itself |
| 3 | a `--key` or `--partition-by` path is unknown or does not name a primitive |
| 4 | a cast failed under `--on-type-error fail` |
| 5 | an input contradicts its dialect or its compression |
| 6 | a JSONL or Parquet field holds a nested structure and no `--schema` declares it |

`AMBIGUITIES.md` records every place the spec admits more than one reading, the
interpretation implemented here, and the risk attached to it.
