# Multi-Format Merger and Sorter

`merge_files.py` ingests CSV, TSV, JSON Lines and Parquet inputs, reconciles them
onto one schema, and writes a single globally sorted CSV.

```
python merge_files.py --output <PATH|-> --key <col>[,<col>...] [--desc]
        [--schema <SCHEMA_JSON>] [--infer {strict,loose}]
        [--schema-strategy {authoritative,consensus,union}]
        [--on-type-error {coerce-null,fail,keep-string}]
        [--memory-limit-mb <INT>] [--temp-dir <PATH>]
        [--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>] [--csv-null-literal <STRING>]
        [--input-format {auto,csv,tsv,jsonl,parquet}] [--compression {auto,none,gzip}]
        [--parquet-row-group-bytes <INT>]
        <INPUT1> [<INPUT2> ...]
```

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

## Layout

| Path | Responsibility |
| --- | --- |
| `merge_files.py` | CLI parsing and the read → cast → sort → write pipeline |
| `csvmerge/coltypes.py` | Type vocabulary, priority, text parsing, inference probes, rendering |
| `csvmerge/values.py` | The same two operations for values that arrive already typed |
| `csvmerge/dialect.py` | The CSV dialect shared by the CSV reader and the writer |
| `csvmerge/formats/detect.py` | Format and gzip detection, and opening a source stream |
| `csvmerge/formats/delimited.py` | CSV and TSV readers |
| `csvmerge/formats/jsonl.py` | JSON Lines reader |
| `csvmerge/formats/parquet.py` | Parquet reader, batched over row groups |
| `csvmerge/schema.py` | Schema documents and explicit `--schema` loading |
| `csvmerge/inference.py` | Inference, and the `--schema-strategy` reconciliation rules |
| `csvmerge/rows.py` | Casting records under the `--on-type-error` policy |
| `csvmerge/sorting.py` | Key encoding, direction/null-aware ordering, external merge sort |
| `csvmerge/writer.py` | Atomic file output, or stdout |
| `csvmerge/errors.py` | Fatal errors and the exit code each carries |

## How it runs

Inference makes one streaming pass over every source, then the merge pass reads them
again; neither pass holds a whole input in memory. Parquet is read row group by row
group with a batch size derived from `--parquet-row-group-bytes`. Rows are buffered
until they exceed a share of `--memory-limit-mb`, then spilled to temporary files as
sorted runs and k-way merged. Spill files are unlinked at creation and closed on
exit, including on the error path; file output lands through a temporary file in the
destination directory that is renamed into place only once the run succeeds.

## Exit codes

| Code | Condition |
| --- | --- |
| 0 | success |
| 1 | any other fatal error (unreadable input, bad schema document) |
| 2 | input format could not be determined |
| 3 | a `--key` column is not in the resolved schema |
| 4 | a cast failed under `--on-type-error fail` |
| 5 | an input contradicts its dialect or its compression |
| 6 | a JSONL or Parquet field holds a nested structure |

`AMBIGUITIES.md` records every place the spec admits more than one reading, the
interpretation implemented here, and the risk attached to it.
