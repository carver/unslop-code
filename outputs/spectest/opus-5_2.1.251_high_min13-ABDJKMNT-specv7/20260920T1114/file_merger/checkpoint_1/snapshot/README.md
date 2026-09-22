# CSV Merger and Sorter

`merge_files.py` reads several CSV files, aligns them onto one schema, and writes a
single globally sorted CSV.

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

```
python merge_files.py --output merged.csv --key id data/*.csv

python merge_files.py --output - --key ts,id --desc --schema schema.json \
    --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv
```

## Behaviour

* **Schema** — with `--schema`, the JSON file fixes the output columns, their order and
  their types; extra input columns are dropped and absent ones read as null. Without it,
  the columns are the union of the input headers in lexicographic order and the types are
  inferred (`--infer strict` per file with conflicts falling back to `string`, `--infer
  loose` from the pooled non-null values).
* **Casting** — `string`, `int`, `float`, `bool` (`true`/`false`/`1`/`0`), `date`
  (`YYYY-MM-DD`) and `timestamp` (ISO-8601, normalised to UTC with a `Z` suffix; a value
  without a zone is taken as UTC). Cells that do not parse follow `--on-type-error`.
* **Sorting** — stable, global, by the `--key` columns; `--desc` reverses every key while
  rows with equal keys keep their input order. Nulls compare less than everything else.
* **Memory** — rows buffer up to `--memory-limit-mb` (64 by default), then spill to sorted
  temporary files under `--temp-dir` that are merged on the way out and removed on exit.

## Layout

| Path | Contents |
| --- | --- |
| `merge_files.py` | entry point and error reporting |
| `csvmerge/cli.py` | argument parsing into `Options` |
| `csvmerge/types.py` | the six column types: parse, render, sort value |
| `csvmerge/schema.py` | resolved schema and `--schema` loading |
| `csvmerge/inference.py` | type inference for the `strict` and `loose` modes |
| `csvmerge/reader.py` | input dialect and row alignment |
| `csvmerge/rows.py` | casting a row to output text plus sort keys |
| `csvmerge/sorter.py` | stable external merge sort |
| `csvmerge/writer.py` | the fixed output dialect |

`AMBIGUITIES.md` records the interpretation choices made where the spec allowed more
than one reading.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests
```
