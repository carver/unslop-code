# CSV Merger and Sorter

`merge_files.py` reads several CSV files, aligns them onto one schema and
writes a single CSV sorted by a composite key.  It sorts with bounded memory,
so inputs much larger than RAM are fine.

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

Infer the schema, sort by `id`, write to a file:

```
python merge_files.py --output merged.csv --key id data/*.csv
```

Use an explicit schema, sort by a descending composite key, stream to stdout:

```
python merge_files.py --output - --key ts,id --desc --schema schema.json \
        --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv
```

The schema file names the output columns, their order and their types
(`string`, `int`, `float`, `bool`, `date`, `timestamp`):

```json
{
  "columns": [
    { "name": "id", "type": "int" },
    { "name": "ts", "type": "timestamp" },
    { "name": "amount", "type": "float" }
  ]
}
```

Input columns missing from the schema are dropped and schema columns missing
from an input are filled with the null literal.  Without `--schema` the output
columns are the union of the input headers in lexicographic order, typed by
inference: `strict` types each file on its own and falls back to `string` when
files disagree, `loose` pools the values of all files and keeps a numeric or
temporal type as long as every non-null value parses.

## Behaviour worth knowing

- **Ordering.** Nulls are the smallest value, so they come first ascending and
  last descending.  Rows with equal keys keep their order of appearance, files
  in the order given on the command line.  Text kept by
  `--on-type-error=keep-string` sorts after the typed values of its column.
- **Output dialect.** Comma delimited, `"` quoted with doubled quotes, `\n`
  line endings, header row first.  Inputs also accept backslash escapes, and
  `--csv-quotechar` / `--csv-escapechar` override what they are read with.
- **Temporal values.** Dates stay `YYYY-MM-DD`; timestamps are normalised to
  UTC with a `Z` suffix and keep their fractional seconds.  A source without a
  zone is read as UTC.
- **Failures.** Bad casts follow `--on-type-error`; `fail` reports the offending
  column on stderr and exits non-zero without writing an output file.

## Memory

Rows are buffered up to a share of `--memory-limit-mb`, then written to the
temporary directory (`--temp-dir`) as sorted runs and merged back with a k-way
merge.  Runs are combined in batches first when there are many of them, so a
run of any size keeps both memory and open file handles bounded.  Every
temporary file is removed when the tool exits, including on error.

## Layout

| File | Contents |
| --- | --- |
| `merge_files.py` | Command line entry point and the merge pipeline |
| `schema.py` | Schema loading and type inference |
| `column_types.py` | Parsing, rendering and ordering per column type |
| `rows.py` | Casting records into the schema, sort key comparison |
| `external_sort.py` | Bounded-memory sort with spilled runs |
| `csv_io.py` | Input and output dialects |
| `errors.py` | The error type reported to the user |

## Development

The tool needs only the standard library (Python 3.10+).

```
python -m venv .venv
.venv/bin/python -m unittest -v
```
