# CSV Merger and Sorter

`merge_files.py` ingests several CSV files, aligns them onto one schema and
writes a single globally sorted CSV.

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

```bash
python merge_files.py --output merged.csv --key id data/*.csv
python merge_files.py --output - --key ts,id --desc --schema schema.json \
       --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv
```

The tool needs no third-party packages; `requirements.txt` pins `pytest` for
the test suite.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest tests/
```

## Layout

| File | Responsibility |
| --- | --- |
| `merge_files.py` | Command line interface and exit codes |
| `csvmerge/coltypes.py` | Type recognition, casting, output formatting |
| `csvmerge/schema.py` | Schema loading from JSON and inference from inputs |
| `csvmerge/csvio.py` | Input/output dialects, reading and writing |
| `csvmerge/sorting.py` | Stable external sort (spill to disk, k-way merge) |
| `csvmerge/merge.py` | Orchestration of the above |

## Behaviour notes

**Schema.** With `--schema`, the JSON file fixes the output columns and their
order; extra input columns are dropped and absent ones are filled with the null
literal. Without it, the output columns are the union of all input headers in
ascending lexicographic order.

**Inference.** Each value contributes the set of types it can be cast to, and a
column takes the most specific type shared by all of its values. `date` is
preferred over `timestamp` while every value is a plain `YYYY-MM-DD`; a single
value carrying a time promotes the whole column to `timestamp`. Because `bool`
outranks `int` and accepts `1`/`0`, a column made only of `1` and `0` is a
boolean and prints as `true`/`false`.

- `strict` (default) resolves a type per file and falls back to `string` when
  files disagree. Empty cells are values here, so a column with a blank cell is
  a `string`.
- `loose` ignores nulls and intersects the candidate types across all files, so
  the most specific type that fits every non-null value wins.

**Casting.** Failures follow `--on-type-error`: `coerce-null` (default) writes
the null literal, `keep-string` writes the original text, and `fail` reports the
file, line and column on stderr and exits non-zero. `date` is ISO-8601
`YYYY-MM-DD`; `timestamp` accepts ISO-8601 with or without a zone (naive input
is read as UTC) and is always written normalised to UTC with a `Z` suffix,
fractional seconds preserved.

**Nulls.** Empty cells, cells equal to `--csv-null-literal` and columns a file
does not have are all nulls. They are written as the null literal and always
compare lower than any real value, so they lead in ascending order and trail in
descending order.

**Sorting.** The sort is stable: rows with equal keys keep their input order
(file order, then line order). Rows are accumulated until they reach half of
`--memory-limit-mb`, then sorted and spilled to a temporary directory
(`--temp-dir`) that is removed on exit; the spilled runs are merged lazily, so
inputs far larger than the limit sort fine — and inputs that fit never touch
disk.

**Dialects.** Inputs are read with `"` quoting, doubled-quote escapes and
backslash escapes (`--csv-quotechar`, `--csv-escapechar`; pass `''` to the
latter to accept doubled quotes only). Output is always comma delimited, `"`
quoted with doubled-quote escaping, and `\n` terminated.
