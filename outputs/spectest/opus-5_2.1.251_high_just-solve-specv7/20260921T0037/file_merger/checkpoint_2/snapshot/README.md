# Multi-Format Merger and Sorter

`merge_files.py` ingests multiple heterogeneous inputs (CSV, TSV, JSON Lines
and Parquet), reconciles their schemas (provided or inferred), casts every cell
to the resolved types and writes a single globally-sorted CSV. It uses an
external merge sort and streaming readers, so inputs much larger than
`--memory-limit-mb` are handled by spilling sorted runs to disk; all temporary
files are removed on exit (including on error).

Only `pyarrow` is needed, and only for Parquet inputs — see
`requirements.txt`. Everything else is the standard library.

## Usage

```
python merge_files.py --output <PATH|-> \
         --key <col>[,<col>...] \
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

`--schema` accepts either a path to a JSON file or the JSON document inline.

Examples:

```
python merge_files.py --output merged.csv --key ts,id \
       --schema-strategy consensus \
       inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet

python merge_files.py --output - --key created_at,id --desc \
       --schema schema.json --input-format tsv --compression gzip data/*.tsv.gz
```

## Input formats

`--input-format auto` (the default) detects each file independently:

| extension                | format  |
| ------------------------ | ------- |
| `.csv`                   | csv     |
| `.tsv`                   | tsv     |
| `.jsonl`, `.ndjson`      | jsonl   |
| `.parquet`               | parquet |

A `.gz` suffix may follow the base extension (`data.csv.gz`,
`events.jsonl.gz`). When the extension is ambiguous the first four
(decompressed) bytes are checked: `PAR1` means Parquet, anything else is an
error (exit 2). Any explicit `--input-format` applies to every input.

`--compression auto` maps a `.gz` suffix to gzip and everything else to none;
`none` and `gzip` force the choice. A declared/detected compression that
disagrees with the file's magic bytes is a mismatch (exit 5).

Source dialects:

* **CSV** — RFC-4180, header row, `\n` or `\r\n`, default quote `"`, escape by
  doubling. Quoted fields additionally accept backslash escapes (`\"`).
* **TSV** — tab delimited, no quoting, header row required, `\n` or `\r\n`.
  A row with more fields than the header means a literal tab leaked into a
  value, which is rejected (exit 5); shorter rows are padded with nulls.
* **JSONL** — one UTF-8 JSON object per line, flat only; `null` is permitted,
  keys are case-sensitive, and blank/whitespace lines are ignored. An
  object/array *value*, or a top-level array, is a nested structure (exit 6).
* **Parquet** — flat schemas only; list, struct, map and union columns are
  rejected (exit 6). Files are read row-group-wise via
  `iter_batches`; `--parquet-row-group-bytes` is an advisory target for batch
  sizing and is additionally capped by `--memory-limit-mb`.

## Schema resolution

With `--schema`, the document defines the exact output columns, types and
order: extra input columns are dropped and missing ones are emitted as nulls.

Without it, the column set is the union of all field names encountered across
every input, ordered ascending lexicographically, and each column's type is
inferred:

* **Type priority** — `timestamp > date > bool > int > float > string`.
  Inference picks the highest-priority type that *every* observed value
  supports. Because `bool` accepts `1`/`0` and outranks `int`, a column whose
  values are only `1` and `0` is inferred as `bool`. A bare `YYYY-MM-DD` is a
  `date`, not a `timestamp` (timestamps require a time part).
* **`--infer strict`** (default) derives a type per file and falls back to
  `string` when files disagree. An empty CSV/TSV cell is an observed value that
  only satisfies `string`, so a column with a blank cell resolves to `string`.
  **`--infer loose`** treats empty cells as nulls that do not affect inference
  and unifies across files, so e.g. `10` in one file and `1.5` in another
  yields `float`.
* CSV, TSV and JSONL string values are sniffed from their text. JSON numbers
  and booleans use their native JSON type. Parquet columns use their *declared*
  Arrow type, without inspecting values.

`--schema-strategy` decides what happens when files disagree about a column:

* **`authoritative`** (default) — only the most trustworthy sources get a vote.
  Precedence is Parquet (a real schema) above JSONL and CSV, which rank equal
  to each other, above TSV. Within the winning tier the rules above apply.
* **`consensus`** — the highest-priority type supported by a strict majority of
  the files that observed the column. Values that do not fit follow
  `--on-type-error`.
* **`union`** — the simplest type that can hold every observed value across all
  files (the intersection of their type sets).

## Behaviour notes

* **Casting** — CSV/TSV cells are raw text; JSONL and Parquet values arrive
  typed. JSON numbers prefer `int` when integral and inside the int64 range,
  otherwise `float`. A JSONL/Parquet `null`, an absent JSONL key, an absent
  column and an empty CSV/TSV cell are all missing and render as the null
  literal.
* **Nulls** — an empty cell (or one equal to `--csv-null-literal`) is null.
  Nulls always compare less than non-nulls, so they sort first ascending and
  last descending, and are written using the null literal.
* **Stability** — rows with equal keys keep input appearance order (file order
  on the command line, then row order) in both ascending and descending mode,
  across formats, and across spill/merge boundaries. Every input row appears
  exactly once; nothing is deduplicated.
* **Temporal output** — `date` stays `YYYY-MM-DD`; `timestamp` is normalised to
  UTC with a `Z` suffix, preserving fractional seconds. A source without a zone
  is treated as UTC.
* **Cast failures** — `coerce-null` (default) writes the null literal, `fail`
  reports the offending file/line/column on stderr and exits 1, and
  `keep-string` passes the original text through.
* **Output** — always a single CSV with a header row in the resolved column
  order, `\n` line endings, using the configured quote char (escaped by
  doubling) and null literal. `--output -` writes to stdout; any other path is
  written to a temporary file in the destination directory and then renamed
  into place, so a failed run never leaves a partial output.

## Exit codes

| code | meaning                                                          |
| ---- | ---------------------------------------------------------------- |
| 0    | success                                                          |
| 1    | cast failure under `--on-type-error=fail`                        |
| 2    | bad CLI usage, bad schema, or undetectable input format          |
| 3    | a `--key` column is absent from the resolved schema              |
| 4    | missing or unreadable input/output file                          |
| 5    | malformed source (dialect violation) or compression mismatch     |
| 6    | non-flat JSONL object or Parquet schema                          |

Errors are reported on stderr as `merge_files.py: error: <message>`.

## Tests

```
python -m unittest discover -s tests -v
```
