# CSV Merger and Sorter

`merge_files.py` ingests multiple CSV files, aligns their schemas (provided or
inferred), and writes a single globally-sorted CSV. It uses an external merge
sort, so inputs much larger than `--memory-limit-mb` are handled by spilling
sorted runs to disk; all temporary files are removed on exit (including on
error).

Only the Python standard library is required (Python 3.8+); `requirements.txt`
is therefore empty of dependencies.

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

`--schema` accepts either a path to a JSON file or the JSON document inline.

Examples:

```
python merge_files.py --output merged.csv --key id data/*.csv
python merge_files.py --output - --key ts,id --desc --schema schema.json \
       --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv
```

## Behaviour notes

* **Column order** — from the schema when given, otherwise ascending
  lexicographic order over the union of all input headers. Input columns not in
  the schema are dropped; columns missing from a file are emitted as nulls.
* **Type priority** — `timestamp > date > bool > int > float > string`.
  Inference picks the highest-priority type that *every* observed value parses
  as under the casting rules. Because `bool` accepts `1`/`0` and outranks `int`,
  a column whose values are only `1` and `0` is inferred as `bool`. A bare
  `YYYY-MM-DD` is a `date`, not a `timestamp` (timestamps require a time part),
  so `date` columns are inferable.
* **`--infer strict`** (default) infers a type per file and falls back to
  `string` when files disagree. Empty cells are observed values and only satisfy
  `string`, so a column with a blank cell resolves to `string`.
  **`--infer loose`** treats empty cells as nulls that do not affect inference
  and unifies across all files at once, so e.g. `10` in one file and `1.5` in
  another yields `float`.
* **Nulls** — an empty cell (or one equal to `--csv-null-literal`) is null.
  Nulls always compare less than non-nulls, so they sort first ascending and
  last descending, and are written using the null literal.
* **Stability** — rows with equal keys keep input appearance order (file order
  on the command line, then row order) in both ascending and descending mode,
  and across spill/merge boundaries.
* **Temporal output** — `date` stays `YYYY-MM-DD`; `timestamp` is normalised to
  UTC with a `Z` suffix, preserving the source's fractional seconds. A source
  without a zone is treated as UTC.
* **Input dialect** — quoted fields accept both doubled quotes (`""`) and
  backslash escapes (`\"`). A backslash that does not precede the quote char,
  escape char, or delimiter is kept literally. The output dialect is fixed:
  comma delimiter, `"` quoting with doubling, `\n` line endings.
* **Cast failures** — `coerce-null` (default) writes the null literal, `fail`
  reports the offending file/line/column on stderr and exits non-zero, and
  `keep-string` passes the original text through.
* A missing key column, an unknown schema type, or a missing input file is an
  error reported on stderr with a non-zero exit status.

## Tests

```
python -m unittest discover -s tests -v
```
