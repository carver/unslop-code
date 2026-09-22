# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and Parquet files, reconciles them onto one schema,
and writes a globally sorted CSV — either as one file or as a directory of part files, partitioned
by field values (Hive-style) and/or cut to a maximum size or row count. Inputs larger than memory
are handled with an external merge sort, and every format is streamed — nothing is ever read whole.

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
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # pyarrow, for Parquet

# Mixed CSV + JSON Lines + Parquet, schema inferred by consensus, composite key
.venv/bin/python merge_files.py --output merged.csv \
        --key ts,id --schema-strategy consensus \
        examples/inputs/users.csv examples/inputs/events.jsonl.gz examples/inputs/metrics.parquet

# Provided schema, TSV sources, gzip forced, descending
.venv/bin/python merge_files.py --output - \
        --key created_at,id --desc \
        --schema examples/data/schema.json \
        --input-format tsv --compression gzip \
        examples/data/*.tsv.gz

# Hive-style partitions, each sharded into parts of at most 50 MB
.venv/bin/python merge_files.py --output out/ \
        --key ts,id --partition-by country,dt \
        --max-bytes-per-file 52428800 \
        inputs/*.csv

# One globally sorted stream cut into files of at most a million rows
.venv/bin/python merge_files.py --output out/ \
        --key ts,id --max-rows-per-file 1000000 \
        examples/inputs/users.csv examples/inputs/events.jsonl.gz examples/inputs/metrics.parquet

.venv/bin/python -m unittest discover -s tests
```

## Layout

| File | Responsibility |
| --- | --- |
| `merge_files.py` | Command line: argument parsing, validation, exit codes |
| `csvmerge/merge.py` | The pipeline — detect inputs, resolve schema, stream, sort, write |
| `csvmerge/schema.py` | Explicit schema loading, inference, and the disagreement strategies |
| `csvmerge/types.py` | Column types and their parse / format / sort-encode tables |
| `csvmerge/casting.py` | Casting values, the `--on-type-error` policies, sort fragments |
| `csvmerge/records.py` | Projecting input rows onto the resolved schema |
| `csvmerge/sorting.py` | Stable external merge sort with spill files |
| `csvmerge/partitioning.py` | Hive-style partition segments and their percent-encoding |
| `csvmerge/shards.py` | The output directory: part files, size/row cutting, atomic moves |
| `csvmerge/sources/` | One reader per input format, behind a single interface |
| `csvmerge/sources/files.py` | Format and compression detection, opening the bytes |
| `csvmerge/sources/delimited.py` | CSV and TSV |
| `csvmerge/sources/jsonl.py` | JSON Lines / NDJSON |
| `csvmerge/sources/parquet.py` | Parquet, read row group by row group |
| `csvmerge/sources/scanning.py` | Collecting per-column type candidates from rows |
| `csvmerge/output.py` | Writing a single result to stdout or atomically to a file |
| `csvmerge/dialect.py` | The CSV dialect shared by CSV inputs and the output |

## How it works

Every reader turns its file into dictionaries keyed by field name, with anything missing reported as
`None` — an empty CSV cell, a JSON `null`, an absent field. CSV and TSV hand over text; JSON Lines
and Parquet hand over values that are already typed. Casting renders a typed value the way this tool
would have written it and then runs the usual parser over it, so a column ends up holding the same
thing whichever format it arrived in. The one shortcut is that a whole float (`3.0`) satisfies an
`int` column, which text like `"3.0"` would not.

Rows are cast and rendered to their final text once, at read time, so the sorter only ever moves
finished output. Records accumulate until they reach the memory budget, each full buffer is sorted
and spilled to a JSON-lines run file, and the runs are then merged lazily with `heapq.merge`. Spill
files live in a temporary directory that is removed when the sort finishes or fails. A single run
that fits in the budget never touches disk.

Sorting compares a list of key fragments per record. Each fragment is `[tier, value]`, where the
tier puts nulls below every real value and `--desc` reverses only the key comparison — the input
sequence number always breaks ties ascending, so equal keys stay in input order in both directions,
across files and across formats. A record carries its partition segments ahead of its key fragments,
so the merged stream arrives grouped by partition and the writer only ever keeps one file open,
however many partitions the data has.

## Partitioned output

Passing `--partition-by`, `--max-rows-per-file` or `--max-bytes-per-file` turns `--output` into a
directory (created if absent, `-` rejected) instead of a single CSV.

- **Field partitions.** Each unique combination of `--partition-by` values gets its own directory,
  nested in the order the columns were given: `country=US/dt=2024-07-01/`. Values are spelled the
  way the resolved schema renders them — an `int` column yields `n=7` for `007`, a `timestamp`
  yields its UTC form — and a missing value becomes `_null`. Everything outside `[A-Za-z0-9._-]` is
  percent-encoded per UTF-8 byte, in both the column name and the value: a space is `%20`, `/` is
  `%2F`, `ï` is `%C3%AF`.
- **Part files.** Every directory holds `part-00000.csv`, `part-00001.csv`, … in the exact order
  rows leave the sorted stream, each with the resolved schema header and each independently valid
  CSV under the configured dialect. A partition with no rows writes no file.
- **Cutting.** `--max-rows-per-file` counts data rows, `--max-bytes-per-file` counts on-disk bytes
  including the header and line endings; given both, a part ends at whichever boundary comes first.
  A single row too large for an empty part is written anyway and ends up in a file of its own.
- **Sorting.** Without field partitions the parts are one globally sorted stream cut into pieces.
  With them, the rows inside each partition directory are sorted by `--key`.
- **Atomicity.** The tree is built in a sibling `.csvmerge-*` directory and renamed into place once
  the last row is written. A failed run removes it, leaving whatever was at `--output` untouched; a
  successful run replaces that directory as a whole, so a rerun never mixes fresh parts with stale
  ones.

## Inputs

Detection is per file. The extension decides first, with `.gz` allowed after the base extension:
`.csv`, `.tsv`, `.jsonl`, `.ndjson`, `.parquet`, plus `.csv.gz` and friends. A file whose extension
says nothing is read as Parquet if it begins with `PAR1`, and is otherwise rejected. `--input-format`
and `--compression` override the detection for every input; a file whose leading bytes contradict
the compression in force is rejected rather than guessed at.

- **CSV** — RFC-4180 with a header row, `\n` endings, and the configured quote and escape characters.
- **TSV** — tab-separated with a header row and no quoting at all. Tabs cannot be escaped, so a row
  that is not exactly as wide as its header is reported as malformed.
- **JSON Lines** — one flat UTF-8 object per line; blank and whitespace-only lines are skipped, keys
  are case-sensitive, and `null` is a missing value. Arrays and objects as values are rejected.
- **Parquet** — flat schemas only; list, map and struct columns are rejected. Batches are sized from
  the file's own bytes-per-row and `--parquet-row-group-bytes`, capped so that a highly compressed
  file cannot produce a batch whose Python rows dwarf the budget.

## Semantics worth knowing

- **Schema order.** With `--schema`, the file's column order is the output order; extra input
  columns are dropped and absent ones become nulls. Without it, the output is the union of every
  input's columns in ascending lexicographic order.
- **Inference priority.** `timestamp > date > bool > int > float > string`: the highest-priority
  type that accepts every observed value wins. For text, inference is deliberately narrower than
  casting in two places, so a higher-priority type cannot swallow values a lower one describes
  better: a bare date stays a `date`, and `1`/`0` stay numeric. A column *declared* `bool` still
  accepts `1`/`0`. Typed values are judged by their own type instead: a Parquet or JSON string of
  digits can still infer as an `int`, but a number that reads like a date does not become one.
  A Parquet file is inferred from its schema alone, so no data is read to type it.
- **`strict` vs `loose`.** `--infer` decides what a single file observes. `strict` resolves a type
  per file and falls back to `string` when files disagree; a null is an observation that only
  `string` satisfies. `loose` ignores nulls and merges files onto the type they all still fit, so
  ints in one file and floats in another still resolve to `float`.
- **`--schema-strategy`.** How files that disagree are reconciled. `authoritative` (the default)
  lets the most strongly typed sources present decide — Parquet outranks JSON Lines, which outranks
  CSV and TSV — and ignores the rest. `consensus` takes the type that most files resolve to on
  their own, falling back to the union rule when they tie. `union` takes the simplest type every
  observed value still fits into.
- **Nulls.** An empty cell, a cell equal to `--csv-null-literal`, a JSON `null`, a Parquet null and
  a field a file simply does not have are all the same missing value, written as the configured null
  literal. Nulls always compare below real values: first ascending, last descending.
- **`keep-string`.** Text kept after a failed cast cannot be compared against parsed values of the
  column's type, so it sorts after them, ordered among itself as text.
- **Timestamps.** Normalised to UTC with a `Z` suffix; a source without a zone is read as UTC. A
  column declared `timestamp` accepts a bare date and reads it as UTC midnight. `date` columns stay
  `YYYY-MM-DD`.
- **Output.** A header plus every input row exactly once, no deduplication. Without a partitioning
  flag that is a single CSV, built beside its destination and renamed into place so a failed run
  leaves the previous file untouched; with one it is the directory tree described above.

## Memory

`--memory-limit-mb` bounds the rows buffered before the sorter spills, not the whole process:
importing pyarrow alone costs about 58 MB. Merging 600k rows spread over an 11 MB CSV, a gzipped
JSON Lines file and a Parquet file at `--memory-limit-mb 64` peaks at roughly 118 MB of RSS, of
which 58 MB is the interpreter and its imports.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | An I/O failure, or a cast rejected by `--on-type-error fail` |
| 2 | A usage error: an input whose format cannot be determined, or an `--output` that cannot hold partitioned parts |
| 3 | An unusable schema file, or a key or partition column missing from the resolved schema |
| 5 | An input that contradicts its dialect or its compression |
| 6 | A JSON Lines or Parquet input holding nested values |

Errors are reported on stderr as `merge_files.py: error: <message>`.
