# Multi-Format Merger and Sorter

`merge_files.py` merges CSV, TSV, JSON Lines and Parquet inputs onto one
schema and writes them out sorted - as a single CSV, or as a directory of
part files split by column values, row count or byte size.

```
python merge_files.py --output <PATH|-> --key <col>[,<col>...] [options] <INPUT> ...
```

```
--desc                          sort every key column descending
--partition-by COLS             comma separated columns whose values become output directories
--max-rows-per-file INT         split the output into files of at most this many data rows
--max-bytes-per-file INT        split the output into files of at most this many bytes
--schema SCHEMA_JSON            fix the output columns, their types and their order
--infer {strict,loose}          inference mode when no schema is given (default: strict)
--schema-strategy {authoritative,consensus,union}
                                how to settle a column the inputs disagree on
                                (default: authoritative)
--on-type-error {coerce-null,fail,keep-string}
                                policy for a cell that will not cast (default: coerce-null)
--memory-limit-mb INT           memory ceiling for buffered rows (default: 256)
--temp-dir PATH                 where spilled sort runs are kept
--csv-quotechar CHAR            CSV quote character, read and written (default: ")
--csv-escapechar CHAR           CSV escape character; quotes are doubled when unset
--csv-null-literal STRING       text standing in for a null, on input and output (default: empty)
--input-format {auto,csv,tsv,jsonl,parquet}
                                format of every input (default: auto, per file)
--compression {auto,none,gzip}  compression of every input (default: auto, per file)
--parquet-row-group-bytes INT   advisory size of a Parquet read batch (default: 1048576)
```

## Layout

| File | Responsibility |
| --- | --- |
| `merge_files.py` | command line interface, wiring the pipeline together |
| `csvmerge/formats.py` | naming each input's format and compression, and opening it |
| `csvmerge/sources.py` | the reader contract, the text formats, and the reader per input |
| `csvmerge/parquetio.py` | the Parquet reader, kept apart so pyarrow loads on demand |
| `csvmerge/schema.py` | resolving the output schema from JSON or by inference |
| `csvmerge/values.py` | per-type parsing, formatting and inference rules |
| `csvmerge/csvio.py` | the CSV dialect, rendering rows, and writing one CSV |
| `csvmerge/records.py` | casting rows into records, applying the type-error policy |
| `csvmerge/sorting.py` | key comparison and the memory-bounded external sort |
| `csvmerge/partition.py` | naming the Hive-style directory a row belongs in |
| `csvmerge/output.py` | the output shape: one CSV, or a tree of part files |

## Inputs

Every input is read as a stream of flat name-to-value mappings; a column a
file does not carry is simply absent from them, and a missing value is
`None` whatever spelled it.

| Format | Recognised by | Read as |
| --- | --- | --- |
| CSV | `.csv` | RFC-4180 text, header row, the configured quoting |
| TSV | `.tsv` | tab separated text with no quoting, header row |
| JSON Lines | `.jsonl`, `.ndjson` | one flat JSON object per line, blank lines ignored |
| Parquet | `.parquet`, or a `PAR1` header | flat schemas only, streamed batch by batch |

A `.gz` suffix after the base extension means gzip (`events.jsonl.gz`), and
`--input-format` or `--compression` override the detection for every input.
Whichever compression is settled on is checked against the file's first
bytes, so a mismatch is reported instead of being read as noise. A file whose
extension says nothing is Parquet if it starts with `PAR1`, and an error
otherwise.

CSV and TSV cells arrive as text; JSON Lines and Parquet values arrive with a
type already. A typed value is rendered to its canonical text before being
cast, so the same logical value lands in the output the same way whichever
format carried it. A JSON integer stays an `int` while it fits 64 bits and
widens to a `float` beyond that.

## Output shape

With no partitioning flag the result is one CSV, written to `--output PATH`
or to stdout for `-`, and put in place only once it is complete.

`--partition-by`, `--max-rows-per-file` and `--max-bytes-per-file` each turn
`--output` into a directory instead - stdout cannot take a tree, so `-` is
refused. The directory is created if it does not exist, is built in a hidden
sibling directory, and is moved onto `--output` in one step at the end; a run
that fails removes that staging directory and leaves an earlier result
readable throughout.

**`--partition-by <col,...>`** puts every distinct combination of those
columns in its own directory, nested in the order the columns were given:

```
out/country=US/dt=2024-05-01/part-00000.csv
out/country=_null/dt=2024-05-02/part-00000.csv
```

A segment is `<column>=<value>`, where the value is the one cast to the
resolved schema and rendered the way the CSV cell is - so `01` and `1` share
an `int` partition, and a timestamp uses its canonical UTC form. Everything
outside `[A-Za-z0-9._-]` is percent-encoded a UTF-8 byte at a time, upper
case (a space is `%20`, a `/` is `%2F`), and a missing value becomes `_null`.

**`--max-rows-per-file`** and **`--max-bytes-per-file`** cut the stream into
`part-00000.csv`, `part-00001.csv`, … - numbered from zero in each partition
directory, or directly under `--output` when no columns partition it. The
byte limit counts the file as it lands on disk, header and line endings
included; the one row that is larger than the limit all by itself gets a file
to itself and exceeds it. Given both limits, a file is cut at whichever
boundary comes first. Without either, each partition gets a single
`part-00000.csv`.

Every part file carries the resolved schema header and is valid CSV on its
own. Rows are globally sorted when nothing partitions them, and sorted within
each partition directory when something does - the sort orders by partition
first so that one directory, and one file, is open at a time however many
partitions a merge produces.

## Behaviour worth knowing

**Type inference.** Each column keeps the set of types that fit *every* value
seen for it, and the survivor with the highest priority wins (`timestamp` >
`date` > `bool` > `int` > `float` > `string`). The `--infer` modes differ in
how they read a missing value: `loose` skips it, so a column is numeric or
temporal as long as every real value parses, while `strict` counts an empty
cell or a `null` as an observation - and since only `string` fits one, such a
column stays text. A column a file does not carry, or carries without ever
filling, is not an observation. Parquet states its own types, so it is not
inferred and the mode does not apply to it.

A date without a time component is never inferred as a `timestamp`, otherwise
the type priority would promote every `date` column.

**Schema strategies** settle a column whose files disagree, e.g. two CSV
files holding `10` and `20` against a JSON Lines file holding `1.5`:

| Strategy | Chooses | Result |
| --- | --- | --- |
| `authoritative` | the type of the first input that carries types of its own, which is any JSON Lines or Parquet input | `float`, the JSON Lines type |
| `consensus` | the type the most files resolve to alone, ties going to the most specific | `int`, two files out of three - `1.5` then follows `--on-type-error` |
| `union` | the most specific type that fits every value in every file | `float`, which holds all three |

Inferred columns are the union of every input's columns, in ascending
lexicographic order. A `--schema` file instead fixes the columns, their types
and their order outright: inputs' extra columns are dropped and columns no
input carries are filled with the null literal.

**Sorting.** Rows are ordered by the composite key after casting, with nulls
ranking below every real value - so they lead an ascending result and trail a
descending one. Rows with equal keys keep their input appearance order:
inputs in the order given on the command line, rows in file order. Nothing is
deduplicated. Partition directories are grouped ahead of the key, which is
what `--desc` does not reach - it reverses the rows inside a partition, never
the partitions themselves.

**Memory.** Rows are buffered up to a fraction of `--memory-limit-mb`,
sorted, and spilled to `--temp-dir` as runs that are streamed back through a
k-way merge; deep run counts are collapsed in earlier passes so the final
merge holds a bounded number of files open. Peak memory therefore depends on
the limit, not on the size of the inputs: 500k and 1.5M Parquet rows both
sort under `--memory-limit-mb 64` at ~122 MB peak RSS, and 500k gzipped JSON
Lines rows at ~59 MB. The difference is pyarrow, which costs about 60 MB of
resident memory once a Parquet input loads it - which is why it is only
imported when one does. `--parquet-row-group-bytes` trades that working set
against read speed; row groups are never read whole.

Partitioning does not change any of this: the part files are written from the
same streamed merge, so 400k rows across 15 partitions still sort under
`--memory-limit-mb 32` at ~37 MB peak RSS.

Spilled runs live in a temporary directory that is removed on exit, including
when the run fails.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | merged |
| 1 | a cell would not cast under `--on-type-error fail`, or a file would not open |
| 2 | the command line was wrong: an unusable `--output`, a limit below 1, or an input whose format could not be determined |
| 3 | the schema is unusable: an unknown type, or a `--key` or `--partition-by` column it does not define |
| 5 | an input contradicts its format: a compression mismatch, a stray tab in a TSV field, a broken JSON line |
| 6 | an input is not flat: a nested Parquet column, or a JSON Lines value that is an object or an array |

## Examples

Field-partitioned by `country,dt`, each partition cut into parts of at most
50 MB:

```
python merge_files.py --output out/ --key ts,id \
    --partition-by country,dt --max-bytes-per-file 52428800 inputs/*.csv
```

One globally sorted stream across three formats, cut into files of a million
rows:

```
python merge_files.py --output out/ --key user_id,ts --max-rows-per-file 1000000 \
    inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet
```

One file per partition, newest row first:

```
python merge_files.py --output out/ --key created_at,id --desc \
    --partition-by account_id inputs/*.tsv.gz
```

## Tests

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests
```
