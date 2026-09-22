# CSV Merger and Sorter

`merge_files.py` ingests several CSVs, aligns them onto one schema, and writes a
single globally sorted CSV.

```
python merge_files.py --output merged.csv --key id data/*.csv
python merge_files.py --output - --key ts,id --desc --schema schema.json \
        --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv
```

Run `python merge_files.py --help` for the full flag list.

## Layout

| Module | Responsibility |
| --- | --- |
| `merge_files.py` | entry point |
| `csvmerge/cli.py` | flags, validation, wiring of the stages |
| `csvmerge/reader.py` | input dialect, headers, row alignment |
| `csvmerge/schema.py` | resolved schema and `--schema` loader |
| `csvmerge/inference.py` | `strict` / `loose` type inference |
| `csvmerge/casting.py` | the six types: parse, render, order, recognise |
| `csvmerge/pipeline.py` | input rows to rendered cells plus sort key |
| `csvmerge/sorting.py` | stable external merge sort |
| `csvmerge/writer.py` | deterministic output dialect, atomic file output |

Rows stream from the inputs into the sorter, which buffers up to the memory
budget and spills sorted runs to `--temp-dir`, so memory use follows
`--memory-limit-mb` rather than the input size.

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation follows.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
