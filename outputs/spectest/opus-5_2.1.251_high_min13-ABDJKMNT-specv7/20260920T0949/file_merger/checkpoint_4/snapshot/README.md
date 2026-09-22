# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and parquet inputs (optionally
gzipped), reconciles them onto one schema, and writes the sorted result either
as a single CSV or as a directory of partitioned, size-bounded part files.

A provided `--schema` may declare nested columns - `struct`, `array<T>`,
`map<string,T>` and the `json` wildcard - which are cast recursively and
written out as canonical JSON in their CSV cell. `--key` and `--partition-by`
then take field paths into those columns.

```
python merge_files.py --output merged.csv --key ts,id --schema-strategy consensus \
        inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
python merge_files.py --output - --key created_at,id --desc --schema schema.json \
        --input-format tsv --compression gzip data/*.tsv.gz
```

Give any of `--partition-by`, `--max-rows-per-file` or `--max-bytes-per-file`
and `--output` becomes a directory instead: a Hive-style tree of
`<col>=<value>/` directories, each holding `part-00000.csv`, `part-00001.csv`,
... cut at the row and byte limits. The tree is built in a sibling temporary
directory and renamed into place, so a failed run leaves nothing behind.

```
python merge_files.py --output out/ --key ts,id --partition-by country,dt \
        --max-bytes-per-file 52428800 inputs/*.csv
python merge_files.py --output out/ --key user_id,ts --max-rows-per-file 1000000 \
        inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
```

Paths address a struct field by name, an array element by index and a map value
by a bracketed, double-quoted key; each must land on a primitive value. Type
names are case-insensitive and pass through the built-in alias table
(`integer`, `list<T>`, `json`, ...), which `--type-alias-file` extends.

```
python merge_files.py --output out/ --key user.id,event_time \
        --partition-by 'attrs["country"]' --schema schema_nested.json \
        --type-alias-file aliases.json inputs/events.jsonl inputs/users.parquet
```

Run `python merge_files.py --help` for the full flag list.

## Layout

| Module | Responsibility |
| --- | --- |
| `merge_files.py` | entry point |
| `csvmerge/cli.py` | flags, validation, wiring of the stages |
| `csvmerge/formats.py` | per-file format and compression detection |
| `csvmerge/records.py` | what a reader yields; typed values to text |
| `csvmerge/reader.py` | the CSV and TSV dialects |
| `csvmerge/jsonl.py` | the JSON Lines dialect |
| `csvmerge/parquet.py` | batched parquet reading and its declared types |
| `csvmerge/sources.py` | one entry point onto the four formats |
| `csvmerge/schema.py` | resolved schema and `--schema` loader |
| `csvmerge/datatypes.py` | the declared types: primitives, struct, array, map, json |
| `csvmerge/aliases.py` | the alias table and `--type-alias-file` |
| `csvmerge/cells.py` | casting a cell, and rendering it as text or canonical JSON |
| `csvmerge/paths.py` | field paths: parsing, resolving, and reading a leaf |
| `csvmerge/inference.py` | `--infer` modes and `--schema-strategy` |
| `csvmerge/casting.py` | the six types: parse, render, order, recognise |
| `csvmerge/pipeline.py` | records to rendered cells plus sort key |
| `csvmerge/sorting.py` | stable external merge sort |
| `csvmerge/writer.py` | output dialect, atomic file and directory output |
| `csvmerge/hive.py` | partition segment names and their percent-encoding |
| `csvmerge/shards.py` | cutting one directory's `part-NNNNN.csv` sequence |
| `csvmerge/partition.py` | the output plan, and routing rows to their directory |
| `csvmerge/errors.py` | user-facing errors and their exit codes |

Every input is read twice when the schema is inferred (once to observe its
types, once to merge its rows) and once when `--schema` is given. Rows stream
from the readers into the sorter, which buffers up to the memory budget and
spills sorted runs to `--temp-dir`; parquet is read row group batch by batch.
Memory use therefore follows `--memory-limit-mb` rather than the input size.
When partitioning by fields, the sort key leads with the partition segments, so
the sorted stream arrives grouped by directory and one part file is open at a
time however many partitions there are.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | unreadable input, or a bad `--schema` or `--type-alias-file` |
| 2 | usage error, an undetectable input format, an alias cycle, a malformed path |
| 3 | a `--key` or `--partition-by` path names no primitive of the resolved schema |
| 4 | a failed cast under `--on-type-error fail` |
| 5 | dialect violation: compression mismatch, stray TSV tab, malformed JSON |
| 6 | a nested input value with no `--schema` to declare its shape |

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation follows.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
