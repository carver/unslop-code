# Multi-Format Merger and Sorter

`merge_files.py` ingests multiple tabular inputs — CSV, TSV, JSON Lines (NDJSON) and
Parquet, optionally gzip compressed — reconciles their schemas and writes a single
globally sorted CSV, or a directory of CSV parts split by field values (Hive-style)
and/or by row count and file size. Everything is streamed, so inputs far larger than
memory work.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # pyarrow, for Parquet inputs only
```

`pyarrow` is imported lazily: CSV, TSV and JSONL inputs need nothing but the
standard library (Python 3.8+).

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

Examples:

```bash
python merge_files.py --output merged.csv --key ts,id \
       --schema-strategy consensus \
       inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet

python merge_files.py --output - --key created_at,id --desc \
       --schema schema.json --input-format tsv --compression gzip data/*.tsv.gz

python merge_files.py --output out/ --key ts,id \
       --partition-by country,dt --max-bytes-per-file 52428800 inputs/*.csv

python merge_files.py --output out/ --key user_id,ts \
       --max-rows-per-file 1000000 \
       inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
```

## Inputs

* **Detection** — with `--input-format auto` (default) each file is classified on its
  own: `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet,
  each optionally followed by `.gz` (`events.jsonl.gz`). When the extension is
  ambiguous the (decompressed) first bytes are checked for the Parquet magic `PAR1`;
  anything else is exit 2. `--input-format` forces one format for every input.
* **Compression** — `--compression auto` (default) treats a `.gz` suffix as gzip and
  everything else as plain. `none`/`gzip` force the decision; if the actual bytes
  disagree with the resolved compression the run fails with exit 5.
* **CSV** — RFC-4180: header row, `,` delimiter, `"` quoting (override with
  `--csv-quotechar`), quotes escaped by doubling or with `--csv-escapechar`, a UTF-8
  BOM and CRLF line endings are tolerated, ragged rows are padded/truncated.
* **TSV** — tab delimited, no quoting (a `"` is literal), header row required, `\n`
  or `\r\n` line endings. A row with more fields than the header means a literal tab
  inside a field and is exit 5; short rows are padded with nulls.
* **JSONL** — one UTF-8 JSON object per line, flat only (an array or object *value*,
  or a line holding an array, is exit 6), `null` allowed, keys case sensitive, blank
  and whitespace-only lines ignored. Numbers become `int` when they are integral and
  fit in 64 bits, otherwise `float`.
* **Parquet** — read row group–wise through `pyarrow.ParquetFile.iter_batches`;
  `--parquet-row-group-bytes` is an advisory batch size (also bounded by
  `--memory-limit-mb`). Only flat schemas are supported: list, struct, map and union
  columns are exit 6. Gzipped Parquet is staged into `--temp-dir` first, because
  Parquet needs random access.

## Behaviour

* **Schema** — with `--schema`, the JSON document (`{"columns": [{"name": ..., "type": ...}]}`)
  fixes the output columns, their types and their order; extra input columns are
  dropped and absent ones filled with the null literal. A path or an inline JSON
  document is accepted. Without `--schema`, the columns are the union of all field
  names across all inputs in ascending lexicographic order and the types are inferred:
  * `--infer strict` (default) resolves a type per file; `loose` combines the observed
    values of several files into one type.
  * Nulls (empty CSV/TSV cells, cells equal to the null literal, JSON/Parquet `null`,
    columns missing from a file) never influence inference; a column with no observed
    value becomes `string`.
  * Candidates are tried in priority order `timestamp > date > bool > int > float >
    string`, so a column of `1`/`0` is a `bool` and a column of `YYYY-MM-DD` values is
    a `date` (a `timestamp` requires a time component during inference). Parquet
    columns contribute their declared type instead of their values.
* **Schema strategy** — how inputs that disagree about a column are reconciled:
  * `authoritative` (default) — the most authoritative sources decide, in the
    precedence order Parquet > JSONL = CSV > TSV. Within that group `--infer strict`
    falls back to `string` when the files still disagree and `loose` combines them.
  * `consensus` — the type resolved by most files wins; ties are broken by widening to
    the simplest type that holds all tied types.
  * `union` — the simplest common type that can hold every observed value of every
    file (`int` + `float` → `float`, `date` + `timestamp` → `timestamp`, otherwise
    `string`).
* **Casting** — CSV/TSV cells are raw strings, JSONL and Parquet values arrive typed;
  both are cast to the resolved column type: `int` (`[+-]digits`), `float` (finite
  values only), `bool` (`true`/`false`/`1`/`0`, case-insensitive, emitted as
  `true`/`false`), `date` (`YYYY-MM-DD`), `timestamp` (ISO-8601; a missing zone is
  treated as UTC, values are normalised to UTC with a `Z` suffix and the original
  fractional digits are preserved). Failures follow `--on-type-error`: `coerce-null`
  (default), `keep-string` or `fail` (message on stderr, exit 4, no output written).
* **Sorting** — by the casted `--key` values, stable with respect to input order
  (inputs are numbered in command-line order, rows in file order); `--desc` reverses
  all keys while keeping equal keys in input order. Nulls always compare less than
  non-null values. A key column absent from the resolved schema is exit 3. Rows are
  never deduplicated: every input row appears exactly once.
* **Output** — one CSV, header first, `,` delimited, `\n` terminated, using the
  configured quote character, escape character and null literal. `--output -` writes
  to stdout, any other path is written to a temporary file in the target directory and
  then renamed into place, so readers never see a partial file. With any partitioning
  flag the output becomes a directory instead — see below.
* **Memory** — rows are buffered up to a fraction of `--memory-limit-mb`, spilled to
  sorted run files under `--temp-dir` and k-way merged (multi-pass above 32 runs);
  every reader streams (Parquet batch-wise, JSONL line-wise), so `--memory-limit-mb 64`
  handles arbitrarily large inputs. Temporary files are removed on normal exit, on
  error and on SIGINT/SIGTERM/SIGHUP.

## Partitioned output

`--partition-by`, `--max-rows-per-file` and `--max-bytes-per-file` turn the single
output CSV into a directory of CSV parts. When any of them is given, `--output` must
be a directory path (`-` is exit 2); the directory is created if it is missing, and it
is always built in a sibling temporary directory that is renamed into place only after
the last row landed — a failed run removes the temporary tree and leaves an existing
output directory untouched.

* **By field** — `--partition-by country,dt` sends every unique combination of
  partition values into its own Hive-style directory
  `country=<val>/dt=<val>/`, nested in the order the columns were listed.
  * Values are the ones written to the CSV, i.e. produced *after* casting to the
    resolved schema type (`1` in a `bool` column becomes `true`, timestamps are
    normalised to UTC).
  * Every byte of the UTF-8 value outside `[A-Za-z0-9._-]` is percent-encoded with
    upper-case hex, so a space becomes `%20`, `/` becomes `%2F` and `ü` becomes
    `%C3%BC`. The encoding is injective: distinct values never share a directory.
  * A null or missing value uses the literal segment `_null`.
  * Partition columns stay in the CSV rows; the header is always the full resolved
    schema.
  * A partition column that is not part of the resolved schema is exit 3.
* **By size** — `--max-rows-per-file N` closes a file after `N` data rows (the header
  is not counted); `--max-bytes-per-file N` keeps the on-disk size of each file,
  header and line endings included, at or below `N`. A single row that does not fit
  into an empty file is written on its own anyway, so that file may exceed the limit.
  Given both, a file is cut at whichever boundary comes first.
* **File names** — `part-00000.csv`, `part-00001.csv`, … (zero padded to width 5) in
  the exact order rows leave the sorted stream, counted from zero again inside every
  partition directory. Without any size limit each partition holds exactly one file.
  Without field partitioning the parts sit directly under `--output`, and an empty
  input still produces a header-only `part-00000.csv`.
* **Sorting** — without field partitioning the parts concatenate to the globally
  sorted stream; with it, the rows of every partition directory are sorted by `--key`
  (`--desc` included). Partitioning is part of the external sort, so it costs no extra
  memory and only one output file is open at a time.

## Exit codes

| code | meaning |
| ---- | ------- |
| 0 | success |
| 2 | bad invocation: unusable flag, `--output -` or an existing file as a partitioned output, missing/unreadable input, undetectable input format |
| 3 | schema problem: invalid schema document, key or partition column not in the resolved schema |
| 4 | a value could not be cast and `--on-type-error=fail` was requested |
| 5 | malformed input: broken CSV/JSON, literal tab in a TSV field, compression mismatch |
| 6 | unsupported structure: nested JSONL values or nested Parquet columns |

Errors are reported on stderr as `merge_files.py: error: <message>`.

## Tests

```bash
.venv/bin/python -m unittest test_merge_files -v
```
