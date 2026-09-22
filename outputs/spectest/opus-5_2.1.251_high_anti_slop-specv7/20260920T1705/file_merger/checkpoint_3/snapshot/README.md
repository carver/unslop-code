# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and Parquet files, reconciles
them onto one schema and writes the sorted result as a single CSV, or as a
directory of CSV parts split by field value, row count or file size.

## Usage

```
python merge_files.py --output <PATH|-> \
        --key <col>[,<col>...] \
        [--partition-by <col>[,<col>...]] \
        [--max-rows-per-file <INT>] \
        [--max-bytes-per-file <INT>] \
        [--desc] \
        [--schema <SCHEMA_JSON>] \
        [--infer {strict,loose}] \
        [--schema-strategy {authoritative,consensus,union}] \
        [--on-type-error {coerce-null,fail,keep-string}] \
        [--memory-limit-mb <INT>] \
        [--temp-dir <PATH>] \
        [--csv-quotechar <CHAR>] \
        [--csv-escapechar <CHAR>] \
        [--csv-null-literal <STRING>] \
        [--input-format {auto,csv,tsv,jsonl,parquet}] \
        [--compression {auto,none,gzip}] \
        [--parquet-row-group-bytes <INT>] \
        <INPUT1> [<INPUT2> ...]
```

```bash
python merge_files.py --output merged.csv --key ts,id --schema-strategy consensus \
       inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet

python merge_files.py --output - --key created_at,id --desc --schema schema.json \
       --input-format tsv --compression gzip data/*.tsv.gz

python merge_files.py --output out/ --key ts,id --partition-by country,dt \
       --max-bytes-per-file 52428800 inputs/*.csv

python merge_files.py --output out/ --key user_id,ts --max-rows-per-file 1000000 \
       inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
```

Parquet input needs `pyarrow`, which is imported only when a Parquet file is
actually read; everything else is standard library.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/
```

## Layout

| File | Responsibility |
| --- | --- |
| `merge_files.py` | Command line interface and exit codes |
| `csvmerge/errors.py` | The failures the tool reports, with their exit codes |
| `csvmerge/formats.py` | Format and compression detection, input dialect, stream opening |
| `csvmerge/readers.py` | Dispatch from a format to its reader |
| `csvmerge/csvio.py` | CSV and TSV input, and the CSV output dialect |
| `csvmerge/jsonlio.py` | JSON Lines input |
| `csvmerge/parquetio.py` | Parquet input, streamed batch by batch |
| `csvmerge/coltypes.py` | Type recognition, casting, output formatting |
| `csvmerge/schema.py` | Schema loading from JSON and inference from inputs |
| `csvmerge/partitioning.py` | Hive-style naming of a row's partition directory |
| `csvmerge/sharding.py` | Part files, their size limits and the atomic output directory |
| `csvmerge/sorting.py` | Stable external sort (spill to disk, k-way merge) |
| `csvmerge/merge.py` | Orchestration of the above |

## Behaviour notes

**Input formats.** `--input-format auto` (the default) names each file from its
extension — `.csv`, `.tsv`, `.jsonl`/`.ndjson`, `.parquet`, optionally followed
by `.gz` — and falls back to the magic bytes, so a Parquet file under any name
is still read as Parquet. Anything else is a usage error. `--compression auto`
reads `.gz` as gzip and everything else as plain; a forced `--compression` that
contradicts the file's first bytes is reported rather than obeyed.

Per format: CSV is RFC-4180 with a header row and tunable quoting; TSV is tab
separated and unquoted with a header row, so a row wider than the header means
a field contained a literal tab and is rejected; JSON Lines is one flat UTF-8
object per line, with blank lines skipped; Parquet must have a flat schema.
Nested values in JSON Lines or Parquet are rejected.

**Schema.** With `--schema`, the JSON file fixes the output columns and their
order; extra input columns are dropped and absent ones are filled with the null
literal. Without it, the output columns are the union of all input columns in
ascending lexicographic order.

**Inference.** Each value contributes the set of types it can be cast to, and a
column takes the most specific type shared by all of its values. Parquet needs
no scan: its declared types are used directly. `date` is preferred over
`timestamp` while every value is a plain `YYYY-MM-DD`; a single value carrying
a time promotes the whole column to `timestamp`. Because `bool` outranks `int`
and accepts `1`/`0`, a column made only of `1` and `0` is a boolean and prints
as `true`/`false`.

- `--infer strict` (default) resolves a type per file. Empty cells are values
  here, so a column with a blank cell is a `string`.
- `--infer loose` ignores nulls, so the most specific type that fits every
  non-null value wins.

**Schema strategy.** When files disagree about a column, `--schema-strategy`
decides:

- `authoritative` (default) lets the highest-precedence format that carries the
  column decide. Parquet states its types and so outranks the formats whose
  types are inferred; JSON Lines ranks equal to CSV and TSV. Within that group,
  `strict` falls back to `string` on disagreement and `loose` keeps the most
  specific type that fits every value.
- `consensus` takes the most specific type a majority of the files support.
- `union` takes the simplest type that can hold every observed value, so `int`
  and `float` files merge into a `float` column.

**Casting.** CSV and TSV cells arrive as text and are parsed; JSON Lines and
Parquet cells arrive typed and are converted, so a JSON number stays an `int`
only while it is whole and fits in 64 bits. Failures follow `--on-type-error`:
`coerce-null` (default) writes the null literal, `keep-string` writes the value
as text, and `fail` reports the file, line and column on stderr and exits
non-zero. `date` is ISO-8601 `YYYY-MM-DD`; `timestamp` accepts ISO-8601 with or
without a zone (naive input is read as UTC) and is always written normalised to
UTC with a `Z` suffix, fractional seconds preserved.

**Nulls.** Empty CSV/TSV cells, cells equal to `--csv-null-literal`, JSON and
Parquet nulls, and columns a file does not have are all nulls. They are written
as the null literal and always compare lower than any real value, so they lead
in ascending order and trail in descending order.

**Sorting.** Keys are compared as cast values, and the sort is stable: rows with
equal keys keep their input order (file order, then line order). Rows are
accumulated until they reach half of `--memory-limit-mb`, then sorted and
spilled to a temporary directory (`--temp-dir`) that is removed on exit; the
spilled runs are merged lazily, so inputs far larger than the limit sort fine —
and inputs that fit never touch disk. Parquet is read batch by batch, sized
from the advisory `--parquet-row-group-bytes`, so no file is ever loaded whole.

**Output.** Every output CSV has a header row in the resolved column order and
holds its input rows exactly once — nothing is deduplicated. Without any
partitioning flag, `--output` is one file, or `-` for stdout; a file is written
to a hidden sibling and renamed into place at the end, so a failed run leaves
no partial CSV.

**Partitioned output.** `--partition-by`, `--max-rows-per-file` and
`--max-bytes-per-file` each turn `--output` into a directory — `-` is then a
usage error. The tree is built in a hidden sibling directory and moved onto
`--output` once the last row is written, replacing whatever directory was
there; a run that fails takes its temporary tree with it and leaves no partial
output.

`--partition-by` gives every distinct combination of its columns a directory of
Hive-style segments, `<col>=<val>/<col>=<val>/`. Values are the ones the CSV
prints, so they follow the resolved schema types, and every byte outside
`[A-Za-z0-9._-]` is percent-encoded — a space becomes `%20` and a separator
`%2F`. A row with no value for a partition column lands under `_null`. The
partition columns stay in the CSV as ordinary columns.

Inside each directory — or directly under `--output` when only sharding — rows
go into `part-00000.csv`, `part-00001.csv`, … in the order they are emitted,
each with its own header. `--max-rows-per-file` counts data rows only;
`--max-bytes-per-file` counts the whole file including the header and the line
endings, and cuts before the row that would exceed it. A row that is larger
than the limit on its own gets a file to itself and overruns it, since it fits
nowhere else. Given both limits, a file is cut as soon as either would be
broken.

**Sorting partitioned output.** Rows are sorted by partition first and by
`--key` second, so a partition's rows are written contiguously and in key
order, one open file at a time. Without `--partition-by` the whole stream is
one partition, which is the global ordering, and sharding only decides where it
is cut.

**Dialects.** `--csv-quotechar` and `--csv-escapechar` apply to CSV only (pass
`''` to the latter to accept doubled quotes only); TSV is unquoted by
definition. Output is always comma delimited, `"` quoted with doubled-quote
escaping, and `\n` terminated.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Unreadable input or output, or a malformed schema file |
| 2 | Bad command line, including a file whose format cannot be detected |
| 3 | A `--key` or `--partition-by` column is not in the resolved schema |
| 5 | Input does not match the dialect or compression it was read with |
| 6 | Input carries nested values |

Errors are reported on stderr as `merge_files.py: <message>`.
