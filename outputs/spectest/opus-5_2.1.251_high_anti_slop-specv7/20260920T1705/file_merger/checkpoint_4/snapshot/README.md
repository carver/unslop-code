# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and Parquet files, reconciles
them onto one schema and writes the sorted result as a single CSV, or as a
directory of CSV parts split by field value, row count or file size. A provided
schema may declare nested columns — structs, arrays and maps — which are
written out as canonical JSON.

## Usage

```
python merge_files.py --output <PATH|-> \
        --key <fieldPath>[,<fieldPath>...] \
        [--partition-by <fieldPath>[,<fieldPath>...]] \
        [--max-rows-per-file <INT>] \
        [--max-bytes-per-file <INT>] \
        [--desc] \
        [--schema <SCHEMA_JSON>] \
        [--type-alias-file <ALIASES_JSON>] \
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

python merge_files.py --output out/ --key user.id,event_time \
       --partition-by 'attrs["country"]' --schema schema_nested.json \
       --on-type-error coerce-null inputs/events.jsonl inputs/users.parquet

python merge_files.py --output merged.csv --key id --schema schema_with_json.json data/*.tsv
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
| `csvmerge/coltypes.py` | Primitive type recognition, casting, output formatting |
| `csvmerge/aliases.py` | Built-in and user type-name aliases |
| `csvmerge/datatypes.py` | The nested type model and its JSON spelling |
| `csvmerge/casting.py` | Recursive casting onto the schema, and cell rendering |
| `csvmerge/paths.py` | Field paths for `--key` and `--partition-by` |
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
a field contained a literal tab and is rejected; JSON Lines is one UTF-8 object
per line, with blank lines skipped; Parquet is read through its own schema.

Nested input is only read when `--schema` declares its shape. JSON Lines and
Parquet hand over objects, lists and maps as they are; a delimited cell holds a
single JSON literal for its nested column, and an empty one is null. Without
`--schema`, an input carrying nesting is rejected, since inference only ever
produces flat columns — a JSON literal in a CSV or TSV cell is then just a
string.

**Schema.** With `--schema`, the JSON file fixes the output columns and their
order; extra input columns are dropped and absent ones are filled with the null
literal. Without it, the output columns are the union of all input columns in
ascending lexicographic order.

**Nested types.** A column's `"type"` is either a type name or a single-key
object naming one of the three nested kinds. They nest to any depth.

```json
{"columns": [
  {"name": "id", "type": "int"},
  {"name": "user", "type": {"struct": {"fields": [
    {"name": "name", "type": "string"},
    {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}}
  ]}}},
  {"name": "items", "type": {"array": {"element": {"struct": {"fields": [
    {"name": "sku", "type": "string"},
    {"name": "qty", "type": "int"}
  ]}}}}}
]}
```

- `struct` takes an ordered `fields` array of `{"name", "type"}`; names must be
  unique within the struct.
- `array` takes one `element` type, so every element is cast the same way.
- `map` takes a `value` type and an optional `key`, which has to be `string`.
- `json` accepts any JSON value — object, array or scalar — and only normalises
  it. A bare `struct` without fields means the same thing.

**Type aliases.** Type names are matched case-insensitively, after the aliases
are applied. Every run understands `integer` and `long` (`int`), `double` and
`number` (`float`), `boolean` (`bool`), `datetime` and `timestamptz`
(`timestamp`), `text` and `varchar` (`string`), `list` (`array`) and `json`
(a fieldless `struct`). `--type-alias-file` adds more:

```json
{"aliases": {"smallint": "int", "decimal": "float", "uuid": "string"}}
```

An alias may name another alias and is followed to the end of the chain; a
table that loops is reported before any schema is read.

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
as text, and `fail` reports the value, the type, the field path and the file and
line on stderr and exits 4. `date` is ISO-8601 `YYYY-MM-DD`; `timestamp` accepts
ISO-8601 with or without a zone (naive input is read as UTC) and is always
written normalised to UTC with a `Z` suffix, fractional seconds preserved.

Nested values are cast member by member with the same rules, and the policy
applies where the failure is: one bad array element leaves the rest of the array
alone. A value whose shape does not match its declared type — an object for an
`int` column, a string for an array, a cell that is not a JSON literal — fails
as a whole. Inside a nested column `keep-string` yields a JSON string, so a
nested cell always holds valid JSON. The `json` type never fails: it takes the
value as it comes.

**Nulls.** Empty CSV/TSV cells, cells equal to `--csv-null-literal`, JSON and
Parquet nulls, and columns a file does not have are all nulls. They are written
as the null literal and always compare lower than any real value, so they lead
in ascending order and trail in descending order.

**Field paths.** `--key` and `--partition-by` name values by path: a column
name, then `.field` into a struct, `.0` into an array and `["key"]` into a map.
`user.id`, `items.0.qty` and `attrs["country"]` are all paths. Array indices are
non-negative integers, map keys must be double-quoted, and a comma inside a
quoted key does not separate two paths. A path that runs past the end of an
array, or through a missing or null value, reads as null for that row. Every
path has to end on a primitive; one that ends on a struct, array, map or `json`
is an error, as is one that names a field the schema does not declare.

**Sorting.** Keys are compared as cast values, and the sort is stable: rows with
equal keys keep their input order (file order, then line order). Rows are
accumulated until they reach half of `--memory-limit-mb`, then sorted and
spilled to a temporary directory (`--temp-dir`) that is removed on exit; the
spilled runs are merged lazily, so inputs far larger than the limit sort fine —
and inputs that fit never touch disk. Parquet is read batch by batch, sized
from the advisory `--parquet-row-group-bytes`, so no file is ever loaded whole.

**Output.** Every output CSV has a header row in the resolved column order and
holds its input rows exactly once — nothing is deduplicated. A nested column's
cell is the value as minified UTF-8 JSON: struct fields in the order the schema
declares them and all of them present, null ones spelled `null`; map and `json`
object keys in lexicographic order; array elements in their original order;
timestamps normalised to UTC `Z` and dates left as `YYYY-MM-DD`. Only a cell
that is null as a whole is written as the null literal instead. Without any
partitioning flag, `--output` is one file, or `-` for stdout; a file is written
to a hidden sibling and renamed into place at the end, so a failed run leaves
no partial CSV.

**Partitioned output.** `--partition-by`, `--max-rows-per-file` and
`--max-bytes-per-file` each turn `--output` into a directory — `-` is then a
usage error. The tree is built in a hidden sibling directory and moved onto
`--output` once the last row is written, replacing whatever directory was
there; a run that fails takes its temporary tree with it and leaves no partial
output.

`--partition-by` gives every distinct combination of its paths a directory of
Hive-style segments, `<path>=<val>/<path>=<val>/`, the path spelled as it was
written on the command line. Values are the ones the CSV
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
| 1 | Unreadable input or output, or a malformed schema or alias file |
| 2 | Bad command line, including an unreadable field path or an alias cycle |
| 3 | A `--key` or `--partition-by` path does not reach a primitive |
| 4 | A cell does not fit its type and `--on-type-error fail` is in force |
| 5 | Input does not match the dialect or compression it was read with |
| 6 | Input carries nested values but no `--schema` describes them |

Errors are reported on stderr as `merge_files.py: ERR <code> <message>`.
