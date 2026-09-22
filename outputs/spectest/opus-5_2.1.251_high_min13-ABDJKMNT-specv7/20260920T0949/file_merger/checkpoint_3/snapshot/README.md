# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and parquet inputs (optionally
gzipped), reconciles them onto one schema, and writes the sorted result either
as a single CSV or as a directory of partitioned, size-bounded part files.

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
| 1 | unreadable input, bad `--schema` file, failed cast under `--on-type-error fail` |
| 2 | usage error, or an input whose format cannot be determined |
| 3 | a `--key` or `--partition-by` column is absent from the resolved schema |
| 5 | dialect violation: compression mismatch, stray TSV tab, malformed JSON |
| 6 | a nested value in a JSON Lines or parquet input |

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation follows.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
