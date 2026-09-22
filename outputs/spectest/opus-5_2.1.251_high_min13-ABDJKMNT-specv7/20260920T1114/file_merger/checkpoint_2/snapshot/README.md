# Multi-Format Merger and Sorter

`merge_files.py` reads CSV, TSV, JSON Lines and Parquet inputs, reconciles them onto one
schema, and writes a single globally sorted CSV.

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

Examples:

```
python merge_files.py --output merged.csv --key ts,id --schema-strategy consensus \
    inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet

python merge_files.py --output - --key created_at,id --desc --schema schema.json \
    --input-format tsv --compression gzip data/*.tsv.gz
```

## Behaviour

* **Inputs** — each file's format comes from its extension (`.csv`, `.tsv`, `.jsonl`,
  `.ndjson`, `.parquet`, each optionally followed by `.gz`); anything else is read as
  Parquet if its magic bytes say so and is otherwise an error. `--input-format` and
  `--compression` force the choice for every input, and a file whose first bytes disagree
  with the compression in force is rejected. Parquet is pulled in batches rather than
  loaded, and JSON Lines a line at a time.
* **Dialects** — CSV follows RFC-4180 with the configurable quote and escape characters;
  TSV is tab separated and unquoted, so a row wider than its header (the only trace a
  literal tab leaves) is an error; JSON Lines holds one flat object per line, blank lines
  skipped; Parquet schemas must be flat. Nested JSON Lines or Parquet values are an error.
* **Schema** — with `--schema`, the JSON file fixes the output columns, their order and
  their types; extra input columns are dropped and absent ones read as null. Without it,
  the columns are the union of every field name in lexicographic order and the types are
  inferred: `--infer` decides what each file's values are evidence for (`strict` counts a
  missing value as text, `loose` skips it) and `--schema-strategy` decides how files that
  disagree are reconciled — `authoritative` lets the typed sources (Parquet) speak for a
  column and falls back to checkpoint 1's rules among peers, `consensus` gives each file
  one vote, `union` takes the most specific type that accepts every observed value.
* **Casting** — CSV and TSV cells arrive as text; JSON Lines and Parquet values arrive
  typed and are spelled canonically before the same cast rules apply (JSON integers stay
  integers while they fit 64 bits). Supported types are `string`, `int`, `float`, `bool`
  (`true`/`false`/`1`/`0`), `date` (`YYYY-MM-DD`) and `timestamp` (ISO-8601, normalised to
  UTC with a `Z` suffix). Null and empty cells become the null literal; cells that do not
  parse follow `--on-type-error`.
* **Sorting** — stable, global, by the casted `--key` columns; `--desc` reverses every key
  while rows with equal keys keep their input order. Nulls compare less than everything
  else.
* **Output** — one CSV, header first, in the resolved column order, quoted with the
  configured dialect flags. `--output -` writes to stdout; a named path is written to a
  temporary file in the same directory and renamed into place, so it never appears partly
  written.
* **Memory** — rows buffer up to `--memory-limit-mb` (64 by default), then spill to sorted
  temporary files under `--temp-dir` that are merged on the way out and removed on exit.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | an input could not be read or the output could not be written |
| 2 | command-line misuse, or an input whose format could not be determined |
| 3 | a schema file that cannot be used, or a key column outside the resolved schema |
| 4 | a cell that will not cast, under `--on-type-error fail` |
| 5 | malformed input, or a compression mismatch |
| 6 | a nested JSON Lines or Parquet structure |

Errors are reported on stderr as `merge_files.py: error: <message>`.

## Layout

| Path | Contents |
| --- | --- |
| `merge_files.py` | entry point and error reporting |
| `csvmerge/cli.py` | argument parsing into `Options` |
| `csvmerge/detect.py` | per-file format and compression detection |
| `csvmerge/sources.py` | an input file and the records it yields |
| `csvmerge/delimited.py` | the CSV and TSV readers |
| `csvmerge/jsonl.py` | the JSON Lines reader |
| `csvmerge/parquetio.py` | the batched Parquet reader |
| `csvmerge/dialect.py` | the CSV dialect shared by reader and writer |
| `csvmerge/values.py` | canonical text and inference evidence for typed values |
| `csvmerge/types.py` | the six column types: parse, render, sort value |
| `csvmerge/schema.py` | resolved schema and `--schema` loading |
| `csvmerge/inference.py` | reading the inputs for type evidence |
| `csvmerge/strategies.py` | reconciling that evidence per `--schema-strategy` |
| `csvmerge/rows.py` | casting a record to output text plus sort keys |
| `csvmerge/sorter.py` | stable external merge sort |
| `csvmerge/writer.py` | the output dialect and the atomic write |
| `csvmerge/errors.py` | the error type and the exit codes |

`AMBIGUITIES.md` records the interpretation choices made where the spec allowed more
than one reading.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests
```
