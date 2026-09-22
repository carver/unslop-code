# CSV Merger and Sorter

`merge_files.py` merges several CSV files onto one schema and writes a single,
globally sorted CSV.

```
python merge_files.py --output <PATH|-> --key <col>[,<col>...] [options] <INPUT.csv> ...
```

```
--desc                          sort every key column descending
--schema SCHEMA_JSON            fix the output columns, their types and their order
--infer {strict,loose}          inference mode when no schema is given (default: strict)
--on-type-error {coerce-null,fail,keep-string}
                                policy for a cell that will not cast (default: coerce-null)
--memory-limit-mb INT           memory ceiling for buffered rows (default: 256)
--temp-dir PATH                 where spilled sort runs are kept
--csv-quotechar CHAR            input quote character (default: ")
--csv-escapechar CHAR           input escape character; quotes are doubled when unset
--csv-null-literal STRING       text standing in for a null, on input and output (default: empty)
```

## Layout

| File | Responsibility |
| --- | --- |
| `merge_files.py` | command line interface, wiring the pipeline together |
| `csvmerge/schema.py` | resolving the output schema from JSON or by inference |
| `csvmerge/values.py` | per-type parsing, formatting and inference rules |
| `csvmerge/csvio.py` | input dialect, header alignment, output writing |
| `csvmerge/records.py` | casting rows into records, applying the type-error policy |
| `csvmerge/sorting.py` | key comparison and the memory-bounded external sort |

## Behaviour worth knowing

**Type inference.** Each column keeps the set of types that accept *every*
value seen for it, across all files, and the survivor with the highest
priority wins (`timestamp` > `date` > `bool` > `int` > `float` > `string`).
Disagreement between files therefore collapses to `string` on its own. The
two modes differ in how they read a null: `loose` skips nulls, so a column is
numeric or temporal as long as every real value parses, while `strict` counts
an empty cell as an observation - and since only `string` accepts it, such a
column stays text. A column a file does not carry is not an observation in
either mode.

A date without a time component is never inferred as a `timestamp`, otherwise
the type priority would promote every `date` column.

**Sorting.** Rows are ordered by the composite key, with nulls ranking below
every real value - so they lead an ascending result and trail a descending
one. Rows with equal keys keep their input appearance order: inputs in the
order given on the command line, rows in file order.

**Memory.** Rows are buffered up to a fraction of `--memory-limit-mb`, sorted,
and spilled to `--temp-dir` as runs that are streamed back through a k-way
merge; deep run counts are collapsed in earlier passes so the final merge
holds a bounded number of files open. A 92 MB input sorts under
`--memory-limit-mb 64` at ~55 MB peak RSS. Spilled runs live in a temporary
directory that is removed on exit, including when the run fails.

## Tests

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests
```
