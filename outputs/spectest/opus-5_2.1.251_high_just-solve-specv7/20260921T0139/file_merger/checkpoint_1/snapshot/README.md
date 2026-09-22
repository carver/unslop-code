# CSV Merger and Sorter

`merge_files.py` ingests multiple CSV files, aligns their schemas and writes a single
globally sorted CSV. It uses only the Python standard library (Python 3.8+).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # no third-party dependencies
```

## Usage

```
python merge_files.py --output <PATH|-> \
         --key <col>[,<col>...] \
         [--desc] \
         [--schema <SCHEMA_JSON>] \
         [--infer {strict,loose}] \
         [--on-type-error {coerce-null,fail,keep-string}] \
         [--memory-limit-mb <INT>] \
         [--temp-dir <PATH>] \
         [--csv-quotechar <CHAR>] \
         [--csv-escapechar <CHAR>] \
         [--csv-null-literal <STRING>] \
         <INPUT1.csv> [<INPUT2.csv> ...]
```

Examples:

```bash
python merge_files.py --output merged.csv --key id data/*.csv
python merge_files.py --output - --key ts,id --desc --schema schema.json \
       --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv
```

## Behaviour

* **Schema** — with `--schema`, the JSON document (`{"columns": [{"name": ..., "type": ...}]}`)
  fixes the output columns and their order; extra input columns are dropped and absent
  ones are filled with the null literal. A path or an inline JSON document is accepted.
  Without `--schema`, columns are the union of all input headers in ascending
  lexicographic order and the types are inferred:
  * `strict` (default) resolves a type per file and falls back to `string` when files disagree.
  * `loose` resolves one type over all observed values across all files.
  * In both modes nulls (empty cells, cells equal to the null literal, and columns missing
    from a file) are ignored by inference; a column with no observed value becomes `string`.
  * Candidates are tried in priority order `timestamp > date > bool > int > float > string`,
    so a column of `1`/`0` is a `bool` and a column of `YYYY-MM-DD` values is a `date`
    (a `timestamp` requires a time component during inference).
* **Casting** — `int` (`[+-]digits`), `float` (finite values only), `bool`
  (`true`/`false`/`1`/`0`, case-insensitive, emitted as `true`/`false`), `date`
  (`YYYY-MM-DD`), `timestamp` (ISO-8601; a missing zone is treated as UTC, the value is
  normalised to UTC with a `Z` suffix and the original fractional digits are preserved).
  Failures follow `--on-type-error`: `coerce-null` (default), `keep-string` or `fail`
  (message on stderr, non-zero exit, no output written).
* **Sorting** — stable with respect to input order (inputs are numbered in command-line
  order); `--desc` reverses all keys while keeping equal keys in input order. Nulls always
  compare less than non-null values, so they come first ascending and last descending.
  A key column that is not in the resolved schema is an error.
* **Dialect** — input uses `,`, the quote character from `--csv-quotechar` (default `"`),
  accepts both `""` and `\"` escapes (override with `--csv-escapechar`), and tolerates a
  UTF-8 BOM and CRLF line endings. Output is always `,`-delimited, `"`-quoted with doubled
  quotes, `\n`-terminated, header first.
* **Memory** — rows are buffered up to a fraction of `--memory-limit-mb`, spilled to sorted
  run files under `--temp-dir` and k-way merged (multi-pass above 32 runs), so inputs much
  larger than the limit are handled. Temporary files are removed on normal exit, on error
  and on SIGINT/SIGTERM/SIGHUP.

## Tests

```bash
.venv/bin/python -m unittest test_merge_files -v
```
