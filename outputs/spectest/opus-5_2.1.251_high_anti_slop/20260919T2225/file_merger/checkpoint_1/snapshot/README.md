# CSV Merger and Sorter

`merge_files.py` ingests several CSV files, aligns them onto one schema, and writes a single
globally sorted CSV. Inputs larger than memory are handled with an external merge sort.

## Usage

```
python merge_files.py --output <PATH|-> \
        --key <col>[,<col>...] \
        [--desc] \
        [--schema <SCHEMA_JSON>] \
        [--infer {strict,loose}] \
        [--on-type-error {coerce-null,fail,keep-string}] \
        [--memory-limit-mb <INT>] \
        [--temp-dir <PATH>] \
        [--csv-quotechar <CHAR>] \
        [--csv-escapechar <CHAR>] \
        [--csv-null-literal <STRING>] \
        <INPUT1.csv> [<INPUT2.csv> ...]
```

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # no third-party packages
.venv/bin/python merge_files.py --output merged.csv --key id examples/*.csv
.venv/bin/python merge_files.py --output - --key ts,id --desc --schema examples/schema.json examples/*.csv
.venv/bin/python -m unittest discover -s tests
```

## Layout

| File | Responsibility |
| --- | --- |
| `merge_files.py` | Command line: argument parsing, validation, exit codes |
| `csvmerge/merge.py` | The pipeline — resolve schema, stream, sort, write |
| `csvmerge/schema.py` | Explicit schema loading and inference from input headers |
| `csvmerge/types.py` | Column types and their parse / format / sort-encode tables |
| `csvmerge/casting.py` | Casting cells, the `--on-type-error` policies, sort fragments |
| `csvmerge/records.py` | Projecting input rows onto the resolved schema |
| `csvmerge/sorting.py` | Stable external merge sort with spill files |
| `csvmerge/csvio.py` | CSV reading and writing plumbing |
| `csvmerge/dialect.py` | The dialect shared by inputs and output |

## How it works

Rows are cast and rendered to their final text once, at read time, so the sorter only ever moves
finished output. Records accumulate until they reach the memory budget, each full buffer is sorted
and spilled to a JSON-lines run file, and the runs are then merged lazily with `heapq.merge`. Spill
files live in a temporary directory that is removed when the sort finishes or fails. A single run
that fits in the budget never touches disk. Peak RSS merging two 11 MB inputs under
`--memory-limit-mb 8` is roughly 26 MB, most of it the interpreter itself.

Sorting compares a list of key fragments per record. Each fragment is `[tier, value]`, where the
tier puts nulls below every real value and `--desc` reverses only the key comparison — the input
sequence number always breaks ties ascending, so equal keys stay in input order in both directions.

## Semantics worth knowing

- **Schema order.** With `--schema`, the file's column order is the output order; extra input
  columns are dropped and absent ones become nulls. Without it, the output is the union of all input
  headers in ascending lexicographic order.
- **Inference priority.** `timestamp > date > bool > int > float > string`: the highest-priority
  type that accepts every observed value wins. Inference is deliberately narrower than casting in
  two places, so a higher-priority type cannot swallow values a lower one describes better: a bare
  date stays a `date`, and `1`/`0` stay numeric. A column *declared* `bool` still accepts `1`/`0`.
- **`strict` vs `loose`.** `strict` resolves a type per file and falls back to `string` when files
  disagree; a blank cell is an observation that only `string` satisfies. `loose` ignores blanks and
  unifies all files at once, so ints in one file and floats in another still resolve to `float`.
- **Nulls.** An empty cell — or one equal to `--csv-null-literal` — reads as null, so output can be
  fed back in. Nulls always compare below real values: first ascending, last descending.
- **`keep-string`.** Text kept after a failed cast cannot be compared against parsed values of the
  column's type, so it sorts after them, ordered among itself as text.
- **Timestamps.** Normalised to UTC with a `Z` suffix; a source without a zone is read as UTC. A
  column declared `timestamp` accepts a bare date and reads it as UTC midnight. `date` columns stay
  `YYYY-MM-DD`.
- **Blank lines** in an input are skipped; a row of empty fields (`,,`) is a real row of nulls.
