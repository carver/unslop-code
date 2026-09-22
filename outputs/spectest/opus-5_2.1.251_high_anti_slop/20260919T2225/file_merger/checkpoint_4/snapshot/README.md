# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and Parquet files, reconciles them onto one schema,
and writes a globally sorted CSV — either as one file or as a directory of part files, partitioned
by field values (Hive-style) and/or cut to a maximum size or row count. Inputs larger than memory
are handled with an external merge sort, and every format is streamed — nothing is ever read whole.

A provided schema may declare nested columns — `struct`, `array<T>`, `map<string,T>`, or the
catch-all `json` — which are written as canonical JSON in their CSV cell. Sort keys and partitions
reach into them with field paths such as `user.id`, `items.0.sku` or `attrs["country"]`.

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

# Nested schema: key on a struct leaf, partition by a map value
.venv/bin/python merge_files.py --output out/ \
        --key user.id,event_time \
        --partition-by 'attrs["country"]' \
        --schema examples/nested/schema_nested.json \
        --type-alias-file examples/nested/aliases.json \
        --on-type-error coerce-null \
        examples/nested/events.jsonl examples/nested/users.parquet

# An arbitrary JSON column carried through, sorted by a primitive one
.venv/bin/python merge_files.py --output merged.csv \
        --key id --schema examples/nested/schema_with_json.json \
        examples/nested/*.tsv

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
| `csvmerge/types.py` | Primitive types and their parse / format / JSON / sort-encode tables |
| `csvmerge/datatypes.py` | The declared type of a column: a primitive, a struct, an array, a map, or `json` |
| `csvmerge/typespec.py` | Reading a declared type out of the schema file, and the type aliases |
| `csvmerge/casting.py` | Casting one value, the `--on-type-error` policies, sort fragments |
| `csvmerge/nested.py` | Casting a whole column recursively, and its canonical JSON encoding |
| `csvmerge/paths.py` | Field paths: parsing them, and resolving them against the schema and a row |
| `csvmerge/records.py` | Projecting input rows onto the resolved schema |
| `csvmerge/sorting.py` | Stable external merge sort with spill files |
| `csvmerge/partitioning.py` | Hive-style partition segments and their percent-encoding |
| `csvmerge/shards.py` | The output directory: part files, size/row cutting, atomic moves |
| `csvmerge/sources/` | One reader per input format, behind a single interface |
| `csvmerge/sources/files.py` | Format and compression detection, opening the bytes |
| `csvmerge/sources/delimited.py` | CSV and TSV |
| `csvmerge/sources/jsonl.py` | JSON Lines / NDJSON |
| `csvmerge/sources/parquet.py` | Parquet, read row group by row group |
| `csvmerge/sources/rows.py` | The row and provenance every reader hands back |
| `csvmerge/sources/scanning.py` | Collecting per-column type candidates from rows |
| `csvmerge/output.py` | Writing a single result to stdout or atomically to a file |
| `csvmerge/dialect.py` | The CSV dialect shared by CSV inputs and the output |

## How it works

Every reader turns its file into rows of values keyed by field name, with anything missing reported
as `None` — an empty CSV cell, a JSON `null`, an absent field — and each row carrying the line it
came from, for the error messages. CSV and TSV hand over text; JSON Lines and Parquet hand over
values that are already typed. Casting renders a typed value the way this tool would have written it
and then runs the usual parser over it, so a column ends up holding the same thing whichever format
it arrived in. The one shortcut is that a whole float (`3.0`) satisfies an `int` column, which text
like `"3.0"` would not.

A cast column is a tree: a cell at every primitive leaf, a dictionary for a struct or a map, a list
for an array. The row's output text, its sort-key fragments and its partition directories are all
read back out of that one tree, so a value is spelled the same way wherever it appears.

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

## Nested types

`--schema` is what makes nesting possible: without one, a JSON Lines or Parquet input holding an
object, an array or a map is rejected (exit 6) and inference stays flat, so a CSV cell that happens
to hold JSON is just a string.

```json
{
  "columns": [
    {"name": "id", "type": "int"},
    {"name": "user", "type": {"struct": {"fields": [
      {"name": "name", "type": "string"},
      {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}}
    ]}}},
    {"name": "items", "type": {"array": {"element": "int"}}},
    {"name": "payload", "type": "json"}
  ]
}
```

- **`struct`** — an ordered list of named fields, whose names must be unique within it. The
  declaration order is the output order, and every field is written, nulls included.
- **`array<T>`** — any number of elements, all of type `T`, which may itself be nested.
- **`map<string,T>`** — string keys only, values of type `T`.
- **`json`** — any JSON value at all: object, array or scalar. It is normalised but never cast.

A type may also be written as text — `array<int>`, `map<string,array<int>>` — which is how the
nested kinds appear inside `<...>`; only a struct needs the object spelling, because only a struct
has field names. A bare `struct` with no fields is the same thing as `json`.

### Type aliases

Type names are lowercased and then resolved through the alias table, so `INTEGER`, `Integer` and
`integer` are one type. These are always present:

| Alias | Type |
| --- | --- |
| `integer`, `long` | `int` |
| `double`, `number` | `float` |
| `boolean` | `bool` |
| `datetime`, `timestamptz` | `timestamp` |
| `text`, `varchar` | `string` |
| `list<T>` | `array<T>` |
| `json` | `struct` with no fields, which takes any JSON |

`--type-alias-file` layers more on top, and may respell a built-in:

```json
{"aliases": {"smallint": "int", "decimal": "float", "uuid": "string", "myts": "timestamp"}}
```

An alias may name another alias, or a whole type such as `array<int>`; the chain is followed until
it reaches a type. A chain that comes back to where it started is rejected before anything is read
(exit 2), and a name that resolves to nothing is a schema error (exit 3).

### Reading nested values

- **JSON Lines** — objects and arrays are handed over as they are and cast against the declared
  type. A value whose shape does not match — an array where a struct was declared, or text where a
  number was — follows `--on-type-error`.
- **Parquet** — structs, lists and maps are accepted when the declared type matches them; Arrow's
  key/value pairs are read as a map. Columns are still rejected outright without a schema.
- **CSV and TSV** — the cell has to hold a single JSON literal. An empty cell is a null, and
  anything else that is not JSON follows `--on-type-error`.

Casting descends: every leaf is parsed by the rules its primitive type already had, so a timestamp
inside a struct is normalised to UTC and a `date` stays `YYYY-MM-DD` wherever it sits. A leaf that
fails to cast becomes JSON `null` under `coerce-null`, the original text under `keep-string`, and
under `fail` ends the run with the field path and the line it came from:

```
merge_files.py: error: ERR 4 cannot cast "many" to int in field "items.0.qty" (file=events.jsonl line=3)
```

### Writing them

A column whose value is null as a whole is written as the configured null literal. Anything else is
written as canonical JSON: minified, UTF-8 (never `\u`-escaped), struct fields in schema order, map
and object keys sorted lexicographically, array elements in their original order, and every struct
field present even when its value is `null`.

## Field paths

`--key` and `--partition-by` take paths, not just column names. A path starts at a column and
descends: `.name` into a struct field, `.0` into an array by index, and `["key"]` — or `.key`, when
the key needs no quoting — into a map. Commas separate paths, except inside `[...]`.

- A path has to end on a primitive. `--key user` where `user` is a struct, or a path that tries to
  descend through a scalar, is `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3).
- Array indices are non-negative integers. An index past the end of an array, a key the map does
  not hold, or anything under a null is a null for that key fragment — the row still sorts, nulls
  first ascending as ever.
- Partition directories are named after the dotted spelling of the path, percent-encoded as before:
  `--partition-by 'attrs["country"]'` writes `attrs.country=US/`.

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
  column's type, so it sorts after them, ordered among itself as text. Inside a nested value it is
  written as a JSON string; a whole nested column that failed keeps its original text as it stood.
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

| Code | `ERR` | Meaning |
| --- | --- | --- |
| 0 | | Success |
| 1 | 1, 4 | An I/O failure, or a cast rejected by `--on-type-error fail` |
| 2 | 2 | A usage error: an input whose format cannot be determined, an `--output` that cannot hold partitioned parts, or a cyclic type alias |
| 3 | 3 | An unusable schema, or a key or partition path the schema cannot resolve |
| 5 | 5 | An input that contradicts its dialect or its compression |
| 6 | 6 | A nested input value with no `--schema` declaring what it is |

Errors are reported on stderr as `merge_files.py: error: ERR <n> <message>`, where `<n>` names the
kind of failure. It is the exit code too, with one exception kept for continuity with the earlier
releases: a cast rejected by `--on-type-error fail` is reported as `ERR 4` but still exits 1.
