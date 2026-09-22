# Multi-Format Merger and Sorter

`merge_files.py` reads several CSV, TSV, JSON Lines and Parquet files, aligns
them onto one schema and writes them out sorted by a composite key: as a single
CSV, or as a directory of `part-xxxxx.csv` files partitioned by column values,
row count or byte size.  It sorts with bounded memory and streams every format,
so inputs much larger than RAM are fine.

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

Mixed sources, schema inferred by consensus, sorted by a composite key:

```
python merge_files.py --output merged.csv --key ts,id \
        --schema-strategy consensus \
        inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
```

An explicit schema over gzipped TSV, descending, streamed to stdout:

```
python merge_files.py --output - --key created_at,id --desc \
        --schema schema.json --input-format tsv --compression gzip data/*.tsv.gz
```

Partitioned by column values, each partition cut into 50 MB parts:

```
python merge_files.py --output out/ --key ts,id \
        --partition-by country,dt --max-bytes-per-file 52428800 inputs/*.csv
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
from an input are filled with the null literal.

## Partitioned output

Without `--partition-by`, `--max-rows-per-file` and `--max-bytes-per-file` the
output is one CSV at `--output`, or on stdout for `-`.  Given any of them,
`--output` is a directory instead (`-` is then an error), created with its
parents if it is missing, and holding `part-00000.csv`, `part-00001.csv`, … in
the order the rows leave the sort.  The directory is built beside itself and
moved into place once the last row is written, so an interrupted run leaves the
previous output untouched and no temporary files behind; a successful run
replaces whatever was there.

`--partition-by` gives each combination of values its own directory tree of
Hive-style `<column>=<value>` segments, with its own `part-xxxxx.csv` sequence:

```
out/country=US/dt=2024-01-01/part-00000.csv
out/country=Fr%20an%2Fce/dt=2024-01-02/part-00000.csv
out/country=_null/dt=2024-01-02/part-00000.csv
```

- Values are the ones cast to the resolved schema, so `007` in an `int` column
  partitions as `7`.
- Names and values are percent-encoded by their UTF-8 bytes wherever a
  character falls outside `[A-Za-z0-9._-]`, so a space becomes `%20` and a
  slash `%2F`.
- A row with no value for a partition column lands in `<column>=_null`.
- Partition columns stay in the rows, so every part file is a complete CSV.

`--max-rows-per-file` and `--max-bytes-per-file` cut the part sequence of each
directory.  Rows are counted without the header; bytes are the size of the file
on disk, header and line endings included.  With both given, a file is cut at
whichever boundary comes first.  A row that does not fit an otherwise empty
file is written on its own and is allowed to exceed the byte limit.  Rows are
globally sorted across the parts, or sorted within each partition when
`--partition-by` is used.

## Inputs

`--input-format=auto` names each file's format from its extension — `.csv`,
`.tsv`, `.jsonl`, `.ndjson`, `.parquet`, each optionally followed by `.gz` — and
falls back to the Parquet magic bytes when the extension says nothing.
`--compression=auto` goes by the `.gz` suffix.  Either detection can be forced
for every input with `--input-format` or `--compression`, and a file whose
contents contradict the compression it is read with is an error.

| Format | Assumptions |
| --- | --- |
| CSV | RFC-4180, header row, `\n` endings, `"` quotes doubled; `--csv-quotechar` and `--csv-escapechar` override what is read |
| TSV | tab delimited, header row, `\n` or `\r\n` endings, no quoting and no escapes, so a literal tab inside a field is an error |
| JSONL | one flat UTF-8 JSON object per line, `null` allowed, case-sensitive keys, blank lines skipped; arrays and objects as values are an error |
| Parquet | flat schemas only, read row group by row group; lists, structs and maps are an error |

## Schema resolution

With `--schema` the file is the schema.  Otherwise the output columns are the
union of the input column names in lexicographic order, and each column's type
comes from what the inputs hold, settled by `--schema-strategy`:

- `authoritative` (default): the inputs carrying the most type information
  decide.  Parquet declares its types and outranks CSV and JSON Lines, which
  rank equally; TSV has neither quoting nor types and ranks last.
- `consensus`: the type most inputs infer for the column wins.
- `union`: the most specific type that can hold every value of every input wins,
  so `int` in one input and `float` in another becomes `float`.

Where a strategy still has to settle a disagreement it follows `--infer`:
`strict` falls back to `string`, `loose` widens to the type that holds them all.
`union` is widening by definition, so `--infer` does not apply to it.

## Behaviour worth knowing

- **Casting.** CSV and TSV cells are text; JSON Lines and Parquet values arrive
  typed, and a whole number that fits in 64 bits stays an `int`.  Every value is
  then cast to its column's type, and a `null`, an empty cell or a missing
  column becomes the null literal.  Bad casts follow `--on-type-error`; `fail`
  reports the offending column on stderr and writes no output.
- **Ordering.** Sorting uses the cast values.  Nulls are the smallest value, so
  they come first ascending and last descending.  Rows with equal keys keep
  their order of appearance, inputs in the order given on the command line.
  Text kept by `--on-type-error=keep-string` sorts after the typed values of its
  column.  Rows are never deduplicated.
- **Output.** Every CSV written, single or part file, starts with the header,
  is comma delimited with `\n` line endings and is quoted with
  `--csv-quotechar` and doubled quotes, so `--csv-escapechar` only matters on
  the way in.  `--output -` streams to stdout; a path is written to a temporary
  file beside it and renamed into place, so a failed run leaves no partial
  output.  See [Partitioned output](#partitioned-output) for the directory
  form.
- **Temporal values.** Dates stay `YYYY-MM-DD`; timestamps are normalised to
  UTC with a `Z` suffix and keep their fractional seconds.  A source without a
  zone is read as UTC.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | an input or the output could not be read or written |
| 2 | the invocation is unusable, including an unknown partition column, a size limit below 1, a partitioned output on stdout and an undetectable input format |
| 3 | a `--key` column is missing from the resolved schema |
| 4 | a cell does not fit its type and `--on-type-error=fail` |
| 5 | an input contradicts its dialect, format or compression |
| 6 | the schema is unusable, including nested JSONL or Parquet fields |

Every failure is reported as `merge_files.py: error: <message>` on stderr.

## Memory

Rows are buffered up to a share of `--memory-limit-mb`, then written to the
temporary directory (`--temp-dir`) as sorted runs and merged back with a k-way
merge.  Runs are combined in batches first when there are many of them, so an
input of any size keeps memory, open file handles and temporary files bounded;
every temporary file is removed when the tool exits, including on error.
Partitions leave that merge grouped, so a partitioned run writes one part file
at a time whatever the number of partitions.
Parquet is read in batches whose size follows `--parquet-row-group-bytes`, so no
file is ever held whole.  The limit covers the row buffer and the read batches,
not the fixed cost of the interpreter and of pyarrow itself (~50 MB).

## Layout

| File | Contents |
| --- | --- |
| `merge_files.py` | Command line entry point and the merge pipeline |
| `output.py` | The single CSV and the partitioned directory of part files |
| `partitions.py` | Hive-style partition segments and their encoding |
| `sources.py` | Format and compression detection, reader dispatch |
| `streams.py` | Opening an input, transparently un-gzipping it |
| `csv_io.py` | The CSV and TSV readers, the output dialect and row rendering |
| `jsonl_io.py` | The JSON Lines reader |
| `parquet_io.py` | The Parquet reader |
| `schema.py` | Schema loading and the inference strategies |
| `inference.py` | Narrowing the candidate types of one input's columns |
| `column_types.py` | Parsing, rendering and ordering per column type |
| `rows.py` | Casting records into the schema, sort key comparison |
| `external_sort.py` | Bounded-memory sort with spilled runs |
| `errors.py` | The reported errors and their exit codes |

## Development

Python 3.10+ and pyarrow for Parquet.

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest -v
```
