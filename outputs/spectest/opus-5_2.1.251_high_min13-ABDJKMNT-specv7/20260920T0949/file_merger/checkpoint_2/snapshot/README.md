# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and parquet inputs (optionally
gzipped), reconciles them onto one schema, and writes a single globally sorted
CSV.

```
python merge_files.py --output merged.csv --key ts,id --schema-strategy consensus \
        inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
python merge_files.py --output - --key created_at,id --desc --schema schema.json \
        --input-format tsv --compression gzip data/*.tsv.gz
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
| `csvmerge/writer.py` | output dialect, atomic file output |
| `csvmerge/errors.py` | user-facing errors and their exit codes |

Every input is read twice when the schema is inferred (once to observe its
types, once to merge its rows) and once when `--schema` is given. Rows stream
from the readers into the sorter, which buffers up to the memory budget and
spills sorted runs to `--temp-dir`; parquet is read row group batch by batch.
Memory use therefore follows `--memory-limit-mb` rather than the input size.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | unreadable input, bad `--schema` file, failed cast under `--on-type-error fail` |
| 2 | usage error, or an input whose format cannot be determined |
| 3 | a `--key` column is absent from the resolved schema |
| 5 | dialect violation: compression mismatch, stray TSV tab, malformed JSON |
| 6 | a nested value in a JSON Lines or parquet input |

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation follows.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
