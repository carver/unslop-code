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

`--schema` and `--type-alias-file` each accept either a path to a JSON file or
the JSON document inline.

`--key` and `--partition-by` take *field paths* (`user.id`, `items.0.sku`,
`attrs["country"]`), which must resolve to a primitive — see
[Nested types](#nested-types).

Examples:

```
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

python merge_files.py --output out/ --key user.id,event_time \
       --partition-by 'attrs["country"]' \
       --schema schema_nested.json --on-type-error coerce-null \
       inputs/events.jsonl inputs/users.parquet

python merge_files.py --output merged.csv --key id \
       --schema schema_with_json.json data/*.tsv
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
* **JSONL** — one UTF-8 JSON object per line; `null` is permitted, keys are
  case-sensitive, and blank/whitespace lines are ignored. An object/array
  *value* is only accepted where `--schema` declares a nested (or `json`)
  column; without a schema it is a nested structure (exit 6), as is a
  top-level array in any case.
* **Parquet** — list, struct and map columns are accepted only when `--schema`
  declares a compatible nested type; without a schema they are rejected
  (exit 6). Files are read row-group-wise via
  `iter_batches`; `--parquet-row-group-bytes` is an advisory target for batch
  sizing and is additionally capped by `--memory-limit-mb`.

## Schema resolution

With `--schema`, the document defines the exact output columns, types and
order: extra input columns are dropped and missing ones are emitted as nulls.
Column types may be nested — see [Nested types](#nested-types).

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

## Nested types

A `--schema` column may declare a nested type. Nested columns are still written
to the CSV, as a single canonical JSON cell.

```json
{
  "columns": [
    {"name": "id", "type": "int"},
    {"name": "user", "type": {
      "struct": {
        "fields": [
          {"name": "name", "type": "string"},
          {"name": "age", "type": "int"},
          {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}}
        ]
      }
    }},
    {"name": "items", "type": {"array": {"element": {
      "struct": {"fields": [
        {"name": "sku", "type": "string"},
        {"name": "qty", "type": "int"}
      ]}}
    }}}
  ]
}
```

* **struct** — an ordered list of named fields; names must be unique within the
  struct.
* **array\<T>** — a homogeneous element type, itself nestable.
* **map\<string,T>** — string keys only (a non-string `key` is rejected,
  exit 2); the value type may be nested.

The primitives (`string`, `int`, `float`, `bool`, `date`, `timestamp`) are
unchanged. The equivalent textual spellings `array<int>`, `map<string,int>` and
`struct<a:int,b:string>` are accepted wherever a type is expected.

### Type aliases

Type names are lowercased before being looked up, so aliases are
case-insensitive. These are always available:

| alias                                  | resolves to |
| -------------------------------------- | ----------- |
| `integer`, `long`                      | `int`       |
| `double`, `number`                     | `float`     |
| `boolean`                              | `bool`      |
| `datetime`, `timestamptz`              | `timestamp` |
| `text`, `varchar`                      | `string`    |
| `list<T>`                              | `array<T>`  |
| `json`                                 | `struct`    |

`--type-alias-file` adds more:

```json
{"aliases": {"smallint": "int", "decimal": "float",
             "uuid": "string", "myts": "timestamp"}}
```

Aliases may point at built-ins or at other aliases and are resolved
transitively; the whole table is checked for cycles up front, whether or not
the alias is used (exit 2). A user alias may point at a parameterised type
(`{"ints": "list<int>"}`), and a parameterised alias keeps its argument
(`list<uuid>` becomes `array<string>`).

A column typed `json` — equivalently a field-less `struct` — accepts *any* JSON
value (object, array or primitive). Its contents are never cast, only
normalised, and are emitted as JSON text.

### Nested input

* **JSONL** — objects and arrays are accepted where the schema declares a
  nested or `json` column. A nested value in a column declared flat is a cast
  failure and follows `--on-type-error`. Without `--schema` any nested value is
  an error (exit 6).
* **Parquet** — struct, list and map columns decode into the same shapes; maps
  become objects. Without `--schema` they are an error (exit 6).
* **CSV/TSV** — the cell must hold a single JSON literal when the target type is
  nested or `json`. An empty cell (or one equal to `--csv-null-literal`) is
  null; anything that is not one complete JSON literal is a cast failure and
  follows `--on-type-error`. Without `--schema` such a cell is just a string.

### Casting inside nested values

Values are cast recursively to the declared type: primitive rules, temporal
normalisation and null handling all apply at every depth. Struct fields absent
from the input are null, and input fields absent from the schema are dropped.
A failure *within* a nested value follows `--on-type-error` for that field or
element alone:

* `coerce-null` — the field/element becomes JSON `null`;
* `keep-string` — it becomes the original unparsed JSON text (or the stringified
  value);
* `fail` — `cannot cast "<val>" to <type> in field "<path>" (file=… line=…)` on
  stderr, exit 1.

### Output encoding

A nested cell is minified UTF-8 JSON with RFC-8259 escaping:

* struct fields appear in schema-declared order, and **every** field is present,
  explicitly `null` when absent;
* map keys are sorted lexicographically (as are the keys of a `json` object);
* arrays keep their original element order;
* `timestamp` is normalised to UTC `Z`, `date` stays `YYYY-MM-DD`;
* a column whose value is null as a whole is written with the CSV null literal
  instead — `null` appears only *inside* a JSON cell.

### Field paths

`--key` and `--partition-by` accept dotted/bracketed paths into nested columns:

| path               | meaning                                    |
| ------------------ | ------------------------------------------ |
| `user.id`          | struct field                               |
| `items.0.sku`      | array element (`items[0].sku` also works)  |
| `attrs["country"]` | map lookup; the quotes are required        |

A path that exactly matches a column name always wins, so a column literally
named `a.b` is still reachable. Array indices must be non-negative integers; an
index out of range, a missing map key, and a null or missing value anywhere
along the path all make that key fragment null (which sorts first ascending,
last descending, and partitions as `_null`). Everything else about ordering,
stability and partitioning is unchanged.

Every path must resolve to a primitive after casting. Naming a struct, array,
map or `json` — or mis-spelling a step — is
`key column "<path>" does not resolve to a primitive` (exit 3).

## Partitioned output

With none of `--partition-by`, `--max-rows-per-file` and `--max-bytes-per-file`,
the output is a single CSV as described above. As soon as any of them is given,
`--output` must be a *directory* path (`-` is rejected, exit 2) and the tool
writes a tree of CSV parts there instead. The tree is built in a sibling
temporary directory and renamed into place once the last row is written, so a
failed run leaves neither a partial tree nor a temp directory behind; a
successful run replaces whatever was at `--output` before. An existing
non-directory at that path is an error (exit 4).

**By field (`--partition-by path[,path...]`)** — rows are grouped by their tuple
of partition values and land in a Hive-style directory tree,
`<path1>=<val1>/<path2>=<val2>/…`, one level per column in the order given; a
field path is used verbatim as the directory label (`attrs["country"]=US`).
Values are taken *after* the cast to the resolved type (so a `float` column
partitions on `1.0`, not `001`), and every byte of their UTF-8 encoding outside
`[A-Za-z0-9._-]` is percent-encoded: space becomes `%20` and `/` becomes `%2F`.
A null or missing value uses the literal `_null`. A partition path that is
absent from the resolved schema, or that does not resolve to a primitive, is an
error (exit 3). Partition columns remain in the CSV payload.

**By size or row count** — `--max-rows-per-file` caps the data rows per file
(the header is not counted) and `--max-bytes-per-file` caps the on-disk size of
each file *including* its header and line endings. Given both, a file is cut at
whichever boundary comes first. A single row that does not fit in an empty file
is written on its own and allowed to exceed the byte cap.

Files are named `part-00000.csv`, `part-00001.csv`, … (zero-padded to width 5),
numbered from zero in each partition directory — or directly under `--output`
when no field partitioning is used. Every file repeats the resolved schema
header and is independently valid CSV. Without a size or row cap each partition
gets exactly one file.

Rows are globally sorted by `--key` when there is no field partitioning, and
sorted by `--key` within each partition directory when there is; in both cases
the parts are filled in that order, so concatenating `part-00000.csv`,
`part-00001.csv`, … (minus repeated headers) reproduces the sorted stream. A run
that produces no rows at all yields a single header-only `part-00000.csv` when
sharding without field partitions, and an empty output directory when field
partitions are in play.

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
* **Output** — a CSV with a header row in the resolved column
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
| 3    | a `--key`/`--partition-by` path that is absent, malformed, or not primitive |
| 4    | missing or unreadable input/output path                          |
| 5    | malformed source (dialect violation) or compression mismatch     |
| 6    | nested JSONL/Parquet input without a `--schema` that declares it |

Errors are reported on stderr as `merge_files.py: error: <message>`.

## Tests

```
python -m unittest discover -s tests -v
```
