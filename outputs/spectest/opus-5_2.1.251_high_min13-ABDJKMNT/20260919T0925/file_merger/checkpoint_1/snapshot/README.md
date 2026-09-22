# CSV Merger and Sorter

`merge_files.py` ingests multiple CSVs, aligns them onto one schema, and writes a
single globally sorted CSV.

```
python merge_files.py --output <PATH|-> --key <col>[,<col>...] [--desc]
        [--schema <SCHEMA_JSON>] [--infer {strict,loose}]
        [--on-type-error {coerce-null,fail,keep-string}]
        [--memory-limit-mb <INT>] [--temp-dir <PATH>]
        [--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>] [--csv-null-literal <STRING>]
        <INPUT1.csv> [<INPUT2.csv> ...]
```

The tool itself is stdlib-only; `requirements.txt` covers the test suite.

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

## Layout

| Path | Responsibility |
| --- | --- |
| `merge_files.py` | CLI parsing and the read → cast → sort → write pipeline |
| `csvmerge/coltypes.py` | Type vocabulary, priority, parsing, inference probes, rendering |
| `csvmerge/schema.py` | Schema documents, and `strict`/`loose` inference |
| `csvmerge/reader.py` | Input dialect, headers, header-aligned records |
| `csvmerge/rows.py` | Casting records under the `--on-type-error` policy |
| `csvmerge/sorting.py` | Key encoding, direction/null-aware ordering, external merge sort |
| `csvmerge/writer.py` | Fixed output dialect, stdout or file |

Rows are buffered until they exceed a share of `--memory-limit-mb`, then spilled to
temporary files as sorted runs and k-way merged, so inputs may exceed memory. Spill
files are unlinked at creation and closed on exit, including on the error path.

`AMBIGUITIES.md` records every place the spec admits more than one reading, the
interpretation implemented here, and the risk attached to it.
