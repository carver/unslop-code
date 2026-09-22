# Ambiguities

Numbered record of under-specified points in the CSV Merger and Sorter spec,
the interpretation chosen for this implementation, and the residual risk that
the spec author's own implementation reads them differently.

---

## T1 — Do `--csv-quotechar` / `--csv-escapechar` also change the *output* dialect?

### Spec Text
> `[--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>]`

> **Deterministic Dialect Details**
> - Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives
1. The flags describe the *input* dialect only; the output dialect is fixed by
   "Deterministic Dialect Details" (`,` / `"` / doubling).
2. The flags describe the dialect for both reading and writing, so
   `--csv-quotechar "'"` would emit `'a,b'` instead of `"a,b"`.

### Choice
Interpretation 1. The "Deterministic Dialect Details" section states the output
quote character and escaping unconditionally and is titled *deterministic*,
which only makes sense if it is not steerable by flags. It also keeps the output
readable by any RFC-4180 parser regardless of how odd the inputs were.

### Risk: 30
Most likely alternative preference: the author threads one dialect object
through both reader and writer, so a non-default `--csv-quotechar` shows up in
the output too.

---

## T2 — Meaning of "accepts backslash-escapes" when the default escape applies

### Spec Text
> Quote character defaults to `"`; escape character defaults to doubling the
> quote (`""`) and accepts backslash-escapes (`\"`), overrideable via flags

### Alternatives
1. By default, *both* `""` and `\"` are decoded inside a quoted field, and a
   backslash that is not followed by the quote (or by another backslash) is a
   literal backslash — so `C:\path` survives.
2. The default is strict doubling; backslash escapes only become active when
   `--csv-escapechar \` is passed explicitly.
3. Default escapechar is backslash in the `csv`-module sense, which silently
   drops *every* backslash, including in `C:\path` → `C:path`.

### Choice
Interpretation 1, implemented with a hand-written line splitter. The sentence
says the default "accepts backslash-escapes", so `\"` must work with no flags;
but consuming unrelated backslashes would corrupt ordinary data, which the spec
never asks for. Doubling and backslash escaping therefore coexist, and a
backslash before any other character is kept verbatim.

### Risk: 25
Most likely alternative preference: interpretation 3 — the author passes
`escapechar='\\'` to Python's `csv` module and inherits its
drop-every-backslash behaviour.

---

## T3 — What actually distinguishes `strict` from `loose` inference

### Spec Text
> - `strict` (default): infer types based on observed values; columns with
>   conflicting types across files fall back to `string`
> - `loose`: prefer numeric/temporal types if all non-null observed values
>   parse; otherwise fall back to `string`; empty strings are treated as nulls
>   and don't affect inference

### Alternatives
1. `strict` considers **all** observed values, empty cells included, so an
   empty cell (which only parses as `string`) forces the column to `string`;
   the type is computed per file and disagreeing files fall back to `string`.
   `loose` skips nulls and computes one type over all files together.
2. Both modes skip empty cells; the modes differ only in the per-file vs.
   global conflict rule.
3. Both modes are global; `strict` requires unanimity of a single type per
   value while `loose` allows type widening (e.g. `int` + `float` → `float`).

### Choice
Interpretation 1. The clause "empty strings are treated as nulls and don't
affect inference" is attached only to `loose`; read as a contrast, it implies
that under `strict` they do affect inference. And "conflicting types **across
files**" only has meaning if a type is computed per file first. This is also
the only reading under which the two modes differ on a single-file input, which
a mode flag ought to.

### Risk: 45
Most likely alternative preference: interpretation 2 — the author skips empty
cells in both modes and treats the empty-string sentence as a clarification
rather than a distinction.

---

## T4 — How "type priority" selects a column type, and `1`/`0` → `bool`

### Spec Text
> - Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> - Inference recognises values by the casting rules below

and

> - `bool` includes `1`/`0` along with standard values

### Alternatives
1. For each cell compute the set of types it can be cast to; a column's type is
   the highest-priority type that *every* cell admits. A column holding only
   `1` and `0` therefore infers as `bool` and prints `true` / `false`.
2. `bool` recognition during *inference* is restricted to `true`/`false`, and
   `1`/`0` are only accepted when a schema explicitly declares the column
   `bool` — so numeric-looking columns stay `int`.
3. The priority list is only a tie-breaker for schema merging and plays no role
   in inference, which would fall back to something like `int` before `bool`.

### Choice
Interpretation 1. "Inference recognises values by the casting rules below"
explicitly binds inference to the casting rules, and the casting rules put
`1`/`0` in `bool`; the priority list then puts `bool` ahead of `int`. The
priority list is otherwise inert, and an `is_active` column of `1`/`0` becoming
`bool` is exactly the case it appears designed for.

### Risk: 55
Most likely alternative preference: interpretation 2 — the author's fixtures
probably contain an `id` column whose first values are `1` and `0`, and the
expected output keeps them as `1`/`0` rather than `true`/`false`.

---

## T5 — Does a bare date satisfy `timestamp`?

### Spec Text
> - `date`: ISO-8601 `YYYY-MM-DD`
> - `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output

> - `date` stays `YYYY-MM-DD`

### Alternatives
1. `YYYY-MM-DD` is a valid ISO-8601 timestamp, so a date-only column would
   infer as `timestamp` (priority `timestamp` > `date`) and print
   `2024-07-01T00:00:00Z`.
2. Inference requires a time component before calling something a
   `timestamp`, so date-only columns infer as `date`; but an explicit
   `timestamp` schema entry still *casts* a bare date to midnight UTC.
3. Both inference and casting require a time component; casting `2024-07-01`
   into a `timestamp` column is a cast error.

### Choice
Interpretation 2. Under interpretation 1 the rule "`date` stays `YYYY-MM-DD`"
could never fire for an inferred schema, and the `date` type would be
unreachable — so inference must require a time part. Casting stays lenient
because the schema is an explicit instruction from the user and losing the data
to a null would be the harsher reading.

### Risk: 30
Most likely alternative preference: interpretation 3 — a single strict
`parse_timestamp` shared by inference and casting, which makes a bare date in a
`timestamp` column a cast failure.

---

## T6 — Output text for `bool` values

### Spec Text
> - `bool` includes `1`/`0` along with standard values

(The spec fixes the output text for `date` and `timestamp` but never for
`bool`.)

### Alternatives
1. Canonical lowercase `true` / `false`.
2. Python's `str(bool)`: `True` / `False`.
3. `1` / `0`.
4. Echo the original source text unchanged.

### Choice
Lowercase `true` / `false`. The tool's stated job is to normalise (it does so
explicitly for timestamps), so a single canonical spelling is required, and
lowercase is the CSV/JSON-idiomatic one. It is also the spelling the spec itself
uses when listing "standard values".

### Risk: 40
Most likely alternative preference: `True` / `False`, if the author stores
parsed Python `bool`s and hands them straight to `csv.writer`.

---

## T7 — Output text for successfully cast `int` and `float` values

### Spec Text
> - Cast every input cell into target type (rules below)
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. Cast values are re-rendered canonically: `007` → `7`, `+5` → `5`, and a
   `float` column renders `3` as `3.0` (Python `repr` shortest round trip).
2. The original source text is echoed whenever the cast succeeds, so `007`
   stays `007` and a `float` column prints `3`.

### Choice
Interpretation 1. "Cast every input cell into target type" describes a value
conversion, not a validation pass, and the output section says output columns
follow the *resolved schema* — a column declared `float` should read as floats.
The spec's own normalisation of timestamps shows the intent that the output is
canonical rather than pass-through.

### Risk: 35
Most likely alternative preference: `float` rendering — the author may use
`str(value)` with trailing-zero trimming or keep the source text, so a `float`
column containing `3` prints `3` rather than `3.0`.

---

## T8 — Is an empty cell a null, and is `--csv-null-literal` recognised on input?

### Spec Text
> - Missing values emitted as the null literal (default empty string; override
>   with `--csv-null-literal`)

> empty strings are treated as nulls

> - Nulls always compare less than non-null values

### Alternatives
1. An empty cell is a null for **every** type (`string` included), so with
   `--csv-null-literal NULL` an empty `note` cell prints `NULL`; in addition a
   cell whose text equals the null literal is read back as a null.
2. Empty cells are nulls only for non-`string` types; an empty `string` cell is
   the empty string and prints as `""` even under a custom null literal.
3. The null literal is output-only and is never recognised when reading.

### Choice
Interpretation 1. The spec's only statement about empty strings ("treated as
nulls") is unqualified by type, and treating the null literal symmetrically
means the tool's own output can be fed back in without changing meaning — a
property a merge tool plainly wants.

### Risk: 40
Most likely alternative preference: interpretation 2 combined with 3 — an
empty `string` cell stays empty and the null literal is written but never read.

---

## T9 — Rendering of fractional seconds in normalised timestamps

### Spec Text
> - `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`),
>   keeping fractional seconds

### Alternatives
1. Microsecond precision: no fractional part when it is zero, otherwise exactly
   six digits (`.500000`), matching the spec's zero-fraction example.
2. The source's own digit count is preserved (`.5` stays `.5`, `.123` stays
   `.123`).
3. Always six digits, even when zero (`2024-07-01T12:00:00.000000Z`) — ruled
   out by the spec's example.

### Choice
Interpretation 1, i.e. Python's `datetime.isoformat()`. The worked example
`2024-07-01T12:00:00Z` shows a zero fraction must be omitted, and once the
value has been parsed into a `datetime` the source's digit count is gone, so
six digits is the natural canonical width.

### Risk: 30
Most likely alternative preference: interpretation 2, if the author normalises
the zone by string surgery instead of parsing to a `datetime`.

---

## T10 — Default value of `--memory-limit-mb`

### Spec Text
> `[--memory-limit-mb <INT>]`

> - Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily
>   large inputs

### Alternatives
1. Default 64 MB, the figure the spec itself calls out.
2. No default: unlimited, purely in-memory unless the flag is given.
3. Some other round number (128, 256, 512).

### Choice
64 MB. It is the only number the spec names in this context, and defaulting to
unbounded would contradict "arbitrarily large inputs" for the documented
example invocation, which omits the flag.

### Risk: 20
Most likely alternative preference: unlimited by default — but since the
default only changes *when* spilling starts and never the emitted bytes, it is
very unlikely to be observable in a test.

---

## T11 — Where `keep-string` survivors sort relative to properly typed values

### Spec Text
> - `keep-string`: emit original text as string

> - Nulls always compare less than non-null values

### Alternatives
1. Kept strings form their own class that sorts after all successfully typed
   (non-null) values of the same column, preserving a total order.
2. Kept strings are compared as strings against the string rendering of the
   typed values.
3. Kept strings are treated as nulls for ordering purposes and sort first.

### Choice
Interpretation 1. The spec gives no rule, and mixing a raw string with parsed
numbers or datetimes has no meaningful order; segregating them keeps the sort
total, deterministic and stable, and keeps the typed values in correct relative
order among themselves — which is the part the spec does constrain.

### Risk: 45
Most likely alternative preference: interpretation 2, if the author's sort key
falls back to comparing rendered text once a cell failed to cast.

---

## T12 — Exit status and message format for errors

### Spec Text
> - `fail`: write error to stderr and exit non-zero

> - If a key column is not present in resolved schema, that is an error

### Alternatives
1. All user-facing errors (cast failure under `fail`, unknown key column,
   unreadable input, bad schema JSON, unknown schema type) behave the same way:
   a message on stderr and exit status 1; argparse usage errors keep
   argparse's status 2.
2. Only cast failures under `fail` are specified to print to stderr; other
   errors might raise a traceback or use distinct exit codes.

### Choice
Interpretation 1. The spec only ever distinguishes "non-zero" from zero, so a
single non-zero status with a one-line stderr message satisfies every stated
requirement, and applying it uniformly to the other error conditions is the
least surprising extension.

### Risk: 10
Most likely alternative preference: a specific exit code such as 2 for all
errors — unlikely to be asserted beyond "non-zero".

---

## T13 — Ragged rows: fewer or more fields than the header

### Spec Text
> - All inputs are UTF-8, RFC-4180 compliant, with a **header row**

> - Missing values emitted as the null literal

### Alternatives
1. A short row leaves the absent trailing columns null; a long row's surplus
   fields are ignored (they correspond to no header name).
2. Any row whose field count differs from the header is an error.
3. Surplus fields are appended under synthesised column names.

### Choice
Interpretation 1. The spec already prescribes nulls for values a row does not
supply and ignoring columns that the resolved schema does not name, so applying
both rules positionally is consistent. Erroring out is not mentioned anywhere
in the error list.

### Risk: 20
Most likely alternative preference: the same, since the inputs are promised to
be RFC-4180 compliant and ragged rows may simply never be tested.

---

## T14 — A blank line in the body of a CSV

### Spec Text
> - Delimiter is comma (`,`); line ending `\n`
> - No multiline fields will be present in tests

### Alternatives
1. A blank line is a one-field row whose single value is null — which matters
   for a single-column CSV where a null row *is* an empty line. Blank lines
   trailing at end of file are dropped.
2. Every blank line is skipped, so a single-column file cannot express a null
   row.
3. Every blank line, including a trailing one, produces a row.

### Choice
Interpretation 1. RFC-4180 has no blank-line construct, so the only coherent
reading of an interior blank line in a one-column file is a row holding the
empty (null) value; dropping trailing blanks avoids inventing a row from a
file that merely ends with a newline or two.

### Risk: 15
Most likely alternative preference: interpretation 2 — the author skips blank
lines unconditionally, which is only observable on a single-column input with a
null row.

---

## T15 — Accepted spellings for `bool`, and whether surrounding spaces parse

### Spec Text
> - `bool` includes `1`/`0` along with standard values
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. `bool` accepts `true`/`false` in any letter case plus `1`/`0`, and nothing
   else; numeric and temporal parsers ignore surrounding whitespace.
2. `bool` additionally accepts `yes`/`no`, `t`/`f`, `y`/`n`.
3. Parsing is byte-exact: `TRUE` and ` 5` are cast failures.

### Choice
Interpretation 1. "standard values" for a boolean means `true`/`false`, and
widening to `yes`/`no` would silently change *inference* results for ordinary
text columns, which is the more damaging error. Case-insensitivity and
whitespace tolerance are the conventional meaning of "standard parsing".

### Risk: 25
Most likely alternative preference: case-sensitive `true`/`false` only, if the
author compares against a literal set without lowering the input.

---

## T16 — Duplicate and repeated key specifications

### Spec Text
> `--key <col>[,<col>...]`

### Alternatives
1. The flag may be repeated and each occurrence may carry a comma list; all
   parts concatenate in order, and a column named twice is only used once.
2. Only a single `--key` occurrence is legal; a repeat replaces the earlier one.
3. A repeated column is an error.

### Choice
Interpretation 1. The documented form is a single comma list, which this
supports exactly; accepting repeats as well is a superset that cannot break a
conforming invocation, and de-duplicating a repeated column is harmless because
a second comparison on the same column can never change the order.

### Risk: 5
Most likely alternative preference: identical behaviour on every documented
invocation; the difference is only visible on inputs the usage line does not
describe.

---

## T17 — Non-finite floats

### Spec Text
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. `nan`, `inf`, `infinity` are cast failures, so a column containing them
   falls back to `string` on inference and follows `--on-type-error` under an
   explicit `float` schema.
2. They parse as floats, following Python's `float()`.

### Choice
Interpretation 1. A `NaN` in a sort key destroys the total order the spec
demands ("sorted globally by the key(s)", stable), so admitting it would make
the output non-deterministic. Rejecting these three spellings keeps every
`float` column totally ordered.

### Risk: 10
Most likely alternative preference: interpretation 2 by accident (a bare
`float()` call), but a fixture containing `nan` is unlikely.

# Checkpoint 2 — Multi-Format CSV Merger

## Annotations to earlier entries

- **T1 is now resolved by the checkpoint 2 spec.** The Output section says
  "Use configured CSV dialect flags for output quoting/escaping and chosen
  null literal", which selects interpretation 2: `--csv-quotechar` now applies
  to the writer as well as the reader. The implementation was changed
  accordingly. What escaping means for the *writer* is still unstated and is
  recorded below as T29.
- **T12 is partially superseded.** Checkpoint 2 names concrete exit codes
  (2, 3, 5, 6) for specific failures, so the "one non-zero status for
  everything" choice no longer holds. The replacement table is T18; the stderr
  message shape (`error: <message>`, one line) is unchanged.
- **T8 is refined.** Checkpoint 2 states the missing-value rule as "If
  JSONL/Parquet value is `null` or CSV/TSV cell is empty", which confirms
  interpretation 1 for CSV/TSV text but restricts it to text sources; see T27
  and T33.
- **T10 is confirmed.** "Implementation must work with `--memory-limit-mb` as
  low as 64" again names 64 as the reference figure; the default stays 64.

---

## T18 — The exit code table

### Spec Text
> - If extension is ambiguous and magic bytes indicate Parquet, treat as
>   parquet; otherwise error 2
> - Mismatch is error 5
> - nested fields trigger error 6
> - Keys must exist in resolved schema (error 3 otherwise)
> - Exact exit codes and stderr message shape as specified

### Alternatives
1. The named codes classify *families* of failure, and the gaps are filled in
   the obvious way: 1 = I/O or otherwise unclassified error, 2 = usage /
   argument / format-detection error, 3 = schema or key error, 4 = cast failure
   under `--on-type-error=fail`, 5 = source dialect or compression violation,
   6 = unsupported nested structure.
2. Only the four named codes exist and everything else, including a cast
   failure under `fail`, exits 1.
3. Every error exits with the same code (checkpoint 1's reading), with 2/3/5/6
   used only as the message text.

### Choice
Interpretation 1. "Exact exit codes … as specified" only makes sense if each
failure class has its own code, and the four given codes already pin down the
classes they belong to. 4 is the only unused small code left between the cast
error (a checkpoint-1 concept) and the dialect errors, and argparse's own usage
failures naturally occupy 2, which is also the code the spec assigns to the
other argument-shaped failure (undetectable format).

### Risk: 40
Most likely alternative preference: cast failures under `--on-type-error=fail`
exit 1 (or 4 is used for something else entirely, such as I/O).

---

## T19 — Does an unambiguous extension outrank the magic bytes?

### Spec Text
> `--input-format=auto` (default): detect per file by extension and magic
> bytes:
> - `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
> - If extension is ambiguous and magic bytes indicate Parquet, treat as
>   parquet; otherwise error 2

### Alternatives
1. The extension decides whenever it is one of the four listed ones; magic
   bytes are consulted only when it is not (the "ambiguous" case). A Parquet
   blob named `weird.csv` is therefore read as CSV and fails.
2. Magic bytes always win when they say Parquet, whatever the extension says.
3. Magic bytes are sniffed for every format (JSON `{`, tab counts, …), not just
   Parquet.

### Choice
Interpretation 1. The magic-byte clause is explicitly conditioned on "if
extension is ambiguous", and Parquet is the only format the spec gives a magic
signature for. Reading the listed extensions first also makes detection a pure
function of the file name in the common case, which is what the determinism
checklist asks for.

### Risk: 10
Most likely alternative preference: the same; a mislabelled Parquet file is an
unlikely fixture.

---

## T20 — A JSONL line that is not a JSON object

### Spec Text
> **JSONL**: one UTF-8 JSON object per line; objects must be flat (no
> arrays/objects as values); `null` permitted

### Alternatives
1. A line that is not parseable JSON, or that parses to something other than an
   object (array, scalar, a whole `[{...},{...}]` document), violates the
   *dialect* and is error 5 — the same class as a literal tab in TSV.
2. A top-level array is a nested structure, so it is error 6, while invalid
   JSON is error 5.
3. Such lines are skipped silently, like blank lines.

### Choice
Interpretation 1. Error 6 is introduced specifically for "nested fields" /
"nested structures" *inside* a row, whereas "one JSON object per line" is a
line-shape rule of exactly the kind whose TSV counterpart (a literal tab) is
called out as error 5. Silently skipping data would also contradict "All rows
from all inputs appear exactly once".

### Risk: 45
Most likely alternative preference: error 6 for a top-level array, since the
author's flatness check may well be the same code path for both.

---

## T21 — "header row required" for an empty TSV file

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` or
> `\r\n` line endings

### Alternatives
1. A TSV file with no first line at all violates "header row required" and is
   error 5.
2. An empty file is simply a source with no columns and no rows, as checkpoint
   1 treated an empty CSV.
3. An empty file is error 2 (an input the tool cannot interpret).

### Choice
Interpretation 1. "Header row required" is stated only for TSV, so it must add
a constraint that CSV does not have, and the only way an input can fail it is
by not having a first line. Error 5 is the code the spec already uses for TSV
dialect violations.

### Risk: 50
Most likely alternative preference: interpretation 2 — the author's reader
probably yields nothing for an empty file and never checks, treating "header
row required" as documentation of the fixture shape rather than a validation.

---

## T22 — What "majority of files support" means for `consensus`

### Spec Text
> - `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives
1. A file *supports* type `T` for a column when every value it has in that
   column can be cast to `T`. Count the files supporting each type, keep the
   types supported by a strict majority, and take the most specific one by the
   checkpoint-1 priority list (`timestamp` > `date` > `bool` > `int` > `float`
   > `string`). `string` is supported by every file, so it is the guaranteed
   fallback.
2. Each file casts one vote for its own inferred type; the type with the most
   votes wins, ties broken by priority.
3. "Majority" means at least half rather than strictly more than half.

### Choice
Interpretation 1. The spec says "support", not "infer" — and support is what
makes the rule useful, because it lets two files of `int` and one file of
`float` agree on `float` instead of deadlocking. The tie-break has to exist
because `string` always has unanimous support; using the priority list the spec
already defines keeps it deterministic. A strict majority is the ordinary
meaning of the word, and it makes a 1–1 split fall back to `string`.

### Risk: 45
Most likely alternative preference: interpretation 2, counting one vote per
file for its inferred type — which agrees with this choice on the simple
"two files of ints, one file of text" fixture but differs on mixed numeric
inputs.

---

## T23 — The widening lattice behind `union`

### Spec Text
> - `--schema-strategy=union`: choose simplest common type that can hold all
>   observed values

### Alternatives
1. Fold the per-file types pairwise through a small lattice: equal types stay,
   `int`+`float` → `float`, `date`+`timestamp` → `timestamp`, anything else
   mixed → `string`.
2. Intersect the per-file candidate-type sets and take the highest-priority
   survivor; `date`+`timestamp` then collapses to `string` because a bare date
   is not recognised as a `timestamp` during inference.
3. "Simplest" means the *widest* type, so any numeric mix becomes `float` and
   any temporal mix becomes `timestamp`, but a `bool`+`int` mix becomes `int`.

### Choice
Interpretation 1. "Can hold all observed values" rules out narrowing, and
"simplest" then selects the narrowest type that still holds everything, which
is exactly a widening fold. `date` → `timestamp` is a widening the casting
rules already support (a bare date casts to midnight UTC), whereas `bool` and
`int` have no common supertype other than text.

### Risk: 35
Most likely alternative preference: `bool`+`int` widening to `int` (treating
`1`/`0` as the overlap) rather than to `string`.

---

## T24 — How the cast rules apply to values that arrive already typed

### Spec Text
> - Apply target output schema cast rules to every cell
> - JSONL values come typed (string/number/bool/null)
> - Parquet values come typed

### Alternatives
1. Every incoming value is first rendered to its canonical text (the same text
   the tool would emit for it) and then run through the checkpoint-1 string
   cast rules. A Parquet `bool` therefore fails a cast to `int` (because
   `true` is not an integer literal) while a JSONL `1` casts to `bool`
   (because `1` is a recognised boolean).
2. Typed values are cast with Python-level conversions, so `bool` → `int`
   yields 1/0 and `float` 2.5 → `int` truncates.
3. A typed value whose type differs from the target is always a cast failure.

### Choice
Interpretation 1. "Apply *target output schema cast rules*" points at the one
set of cast rules the spec has already defined, and those are defined on text.
Routing everything through canonical text also guarantees that the same logical
value merged from a CSV and from a Parquet file lands in the same output cell,
which is the whole point of schema reconciliation.

### Risk: 40
Most likely alternative preference: interpretation 2 for the numeric cases —
`float` → `int` silently truncating, or `bool` → `int` giving 1/0.

---

## T25 — Is `--schema <SCHEMA_JSON>` a path or a document?

### Spec Text
> `[--schema <SCHEMA_JSON>]`

> ```
> --schema schema.json
> ```

### Alternatives
1. Accept both: a value starting with `{` is parsed as an inline JSON
   document, anything else is a path.
2. Path only, as in checkpoint 1 and the worked example.
3. Inline JSON only, as the metavariable name suggests.

### Choice
Interpretation 1. The example passes a file name, so paths must work; the
metavariable `SCHEMA_JSON` hints at a document, and accepting both costs
nothing and cannot break a path-shaped argument (no path starts with `{`).

### Risk: 5
Most likely alternative preference: path only — which this choice still
satisfies.

---

## T26 — Duplicate column names inside one source

### Spec Text
> - Column set: union of all encountered field names

### Alternatives
1. The first occurrence wins, matching checkpoint 1's CSV header handling, for
   every format (Parquet allows repeated field names; a JSON object cannot
   actually repeat a key once parsed).
2. The last occurrence wins.
3. Duplicates are an error.

### Choice
Interpretation 1, for consistency with the checkpoint-1 CSV reader, which
already resolves a repeated header name to its first index.

### Risk: 10
Most likely alternative preference: the same, or untested.

---

## T27 — Does `--csv-null-literal` apply on input to non-CSV sources?

### Spec Text
> - If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as
>   missing → emit null literal

> `[--csv-null-literal <STRING>]`

### Alternatives
1. The null literal is recognised on input only for the text formats (CSV and
   TSV), exactly as checkpoint 1's T8 decided, and for typed sources only a
   real `null` is missing. The literal is always used on output.
2. The literal is recognised in every source, so a JSONL string equal to it is
   also a null.
3. The literal is output-only everywhere.

### Choice
Interpretation 1. The spec's missing-value rule distinguishes the two source
kinds explicitly, and the flag is named `--csv-null-literal`, which scopes its
input side to the CSV-shaped formats. Checkpoint 1's round-trip argument still
applies there.

### Risk: 30
Most likely alternative preference: interpretation 3 — the literal is never
recognised on input, which would also be consistent with this spec's wording.

---

## T28 — What counts as a compression "mismatch"

### Spec Text
> - `--compression=none` forces no decompression; `--compression=gzip` forces
>   gzip
> - Mismatch is error 5

### Alternatives
1. Mismatch means the bytes disagree with the effective compression setting:
   `gzip` requested (or a `.gz` name under `auto`) but the file does not start
   with the gzip magic `1f 8b`, or `none` requested but the file does. A
   truncated or corrupt gzip stream is also error 5.
2. Mismatch means only the flag-versus-extension disagreement (`.gz` file with
   `--compression=none`, or a plain name with `--compression=gzip`), decided
   from the file name alone.
3. Mismatch refers to a format-versus-compression conflict, e.g. asking for
   Parquet and gzip at once.

### Choice
Interpretation 1. Checking the actual bytes is the only test that catches the
case the error is plainly for — being told to gunzip something that is not
gzipped — and it keeps `--compression=none` on a plainly-named-but-compressed
file an error too. Interpretation 2 would make `--compression=none` on
`data.csv.gz` an error even when the file genuinely is not compressed, which
contradicts "forces no decompression".

### Risk: 35
Most likely alternative preference: interpretation 2, where the `.gz` suffix
plus an explicit contradicting `--compression` is the only mismatch.

---

## T29 — What "configured dialect flags for output escaping" means

### Spec Text
> - Use configured CSV dialect flags for output quoting/escaping and chosen
>   null literal

> (checkpoint 1) Output delimiter `,`, quote `"`; escape by doubling quotes

### Alternatives
1. The writer uses `--csv-quotechar` as its quote character and always escapes
   it by doubling; `--csv-escapechar` remains an input-side concern.
2. The writer also uses `--csv-escapechar`, emitting `\"` style escapes instead
   of doubling whenever the flag is present.
3. Nothing changes: the output dialect stays fixed at `,` / `"` / doubling
   (checkpoint 1's reading, now contradicted).

### Choice
Interpretation 1. Checkpoint 1 states the doubling rule unconditionally, and
the default `--csv-escapechar` is a backslash, so honouring it on output would
change the default output of every run that contains a quote — a change the
spec would have to state outright. Quoting with the configured quote character
is the part the new sentence actually adds.

### Risk: 35
Most likely alternative preference: interpretation 3, if the author never
rewired the writer and the hidden tests only ever use the default quote.

---

## T30 — Mapping Parquet physical/logical types onto the type vocabulary

### Spec Text
> - **Parquet**: flat schemas only (no nested/list/map types)
> - Parquet values come typed

### Alternatives
1. All integer widths → `int`; `float`/`double`/`decimal` → `float`;
   `bool` → `bool`; `date32`/`date64` → `date`; any `timestamp` → `timestamp`
   (naive values read as UTC); `string`/`binary`/anything else → `string`.
2. Decimals map to `string` to avoid precision loss, and `time` types too.
3. Parquet columns are re-inferred from their rendered text like CSV columns,
   so a string column of digits becomes `int`.

### Choice
Interpretation 1. It is the smallest total mapping onto the six checkpoint-1
types, and re-inferring (3) would throw away exactly the type information that
makes Parquet the authoritative source in the default strategy. A naive
timestamp is read as UTC because that is how checkpoint 1 treats a zone-less
timestamp string.

### Risk: 25
Most likely alternative preference: decimals rendered as exact text (`string`)
rather than as floats.

---

## T31 — "within range" for JSONL numbers

### Spec Text
> - For JSONL numbers, prefer `int` if integer and within range; otherwise
>   `float`

### Alternatives
1. "Within range" is signed 64-bit; a JSON integer outside ±2^63 becomes a
   float, and a JSON `5.0` becomes the integer 5.
2. "Within range" means representable as a Python `int`, i.e. unbounded, so
   only non-integral numbers become floats.
3. "Within range" means exactly representable as a double (±2^53).

### Choice
Interpretation 1. 64-bit is the range every other component in this pipeline
(Parquet `int64`, most JSON producers) uses for integers, and the clause has to
exclude *something* to be worth writing, which rules out (2).

### Risk: 20
Most likely alternative preference: interpretation 2 — Python integers are
unbounded, so an author who does not add an explicit bound check gets it for
free.

---

## T32 — The `authoritative` precedence order, and how ties inside a rank break

### Spec Text
> - `--schema-strategy=authoritative` (default): prefer typed sources in
>   precedence order; JSONL ranks equal to CSV.

### Alternatives
1. Two ranks: Parquet first, then {JSONL, CSV, TSV} together. For a column, the
   highest rank that observed it decides; within that rank the checkpoint-1
   `--infer` rules apply (strict: disagreeing files fall back to `string`;
   loose: the shared candidate types are intersected).
2. Three ranks — Parquet, then JSONL, then CSV/TSV — reading "JSONL ranks equal
   to CSV" as applying only to some narrower situation.
3. Precedence is command-line order: the first file that observed the column
   dictates its type.

### Choice
Interpretation 1. The sentence names exactly one demotion ("JSONL ranks equal
to CSV"), which leaves Parquet as the only source above the rest; since JSONL
types are per-row rather than declared, treating them like CSV text is also the
only way the column type stays well defined. Falling back to the checkpoint-1
rules inside a rank keeps every all-CSV invocation byte-identical to
checkpoint 1, which "Extend your tool" demands.

### Risk: 45
Most likely alternative preference: within-rank disagreements widen (int+float
→ float) instead of falling back to `string` under the default `strict`,
i.e. the author reuses the union rule as the tie-breaker everywhere.

---

## T33 — Is an empty string from a typed source a missing value?

### Spec Text
> - If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as
>   missing → emit null literal

### Alternatives
1. No: the rule names two distinct cases, and a JSONL/Parquet empty string is
   neither. It stays an empty string, sorts as one, and is written as `""`
   rather than as the null literal.
2. Yes: empty text is missing in every source, matching checkpoint 1's T8.
3. Yes for Parquet (where empty and null are easily confused) but not JSONL.

### Choice
Interpretation 1. The sentence goes out of its way to attach "is `null`" to the
typed formats and "is empty" to the text formats; a typed source can express
the difference between an absent value and an empty one, so the tool should
preserve it.

### Risk: 30
Most likely alternative preference: interpretation 2, if the author funnels
every value through one "looks empty → null" helper.

---

## T34 — Default and effect of `--parquet-row-group-bytes`

### Spec Text
> - Parquet reading must be streamed row group–wise;
>   `--parquet-row-group-bytes` is advisory for batch sizing

### Alternatives
1. Advisory means it can only influence how many rows are pulled per batch,
   never the bytes emitted; the default is a fixed internal batch budget
   (64 MiB here), and any value is accepted.
2. It caps the row group size and errors when a file's row groups are larger.
3. It is ignored entirely.

### Choice
Interpretation 1. "Advisory" says the value is a hint, and the determinism
checklist would be violated if the flag changed the output. It is still used —
smaller values produce smaller record batches — so that memory stays bounded.

### Risk: 5
Most likely alternative preference: ignored entirely, which is
indistinguishable from this choice in any output-comparing test.

---

## T35 — Do `--input-format` and `--compression` apply per file or globally?

### Spec Text
> `[--input-format {auto,csv,tsv,jsonl,parquet}]`
> `[--compression {auto,none,gzip}]`

> ```
> --input-format tsv --compression gzip data/*.tsv.gz
> ```

### Alternatives
1. Both flags are global: an explicit value applies to every input, and `auto`
   means "detect each file independently".
2. The flags apply only to the first input, or are positional per input.

### Choice
Interpretation 1. The example passes a shell glob that expands to many files
with a single `--input-format tsv --compression gzip`, so the value must cover
all of them; and the detection rules are described as "detect per file", which
only distinguishes itself from the forced case under this reading.

### Risk: 5
Most likely alternative preference: the same.

---

## T36 — Does a JSONL row that omits a key count as a null for inference?

### Spec Text
> - Column set: union of all encountered field names
> - Type inference per `--infer` mode (strict or loose)
> - `strict` (default): infer types based on observed values

### Alternatives
1. An omitted key is not an observation at all, so it never affects the
   column's type; only a present `null` does (which, under `strict`, still
   forces `string` the way an empty CSV cell does).
2. An omitted key is equivalent to a null, so under `strict` any JSONL file
   with a sparse column infers that column as `string`.
3. An omitted key is equivalent to a null under both modes.

### Choice
Interpretation 1. "Encountered field names" and "observed values" both speak of
what the file actually contains; a key that is not there was not encountered.
It also keeps a column that only some sources carry usable — otherwise nearly
every heterogeneous merge would degrade to all-`string`, which would make the
schema strategies pointless.

### Risk: 35
Most likely alternative preference: interpretation 2, if the author
materialises every row against the running column union before inferring,
which turns absent keys into nulls automatically.

---

## T37 — Which flags are "partitioning flags"

### Spec Text
> - When no partitioning flags provided: write single CSV to `--output` (file
>   path or `-` for stdout)
> - When any partitioning flag provided: `--output` must be directory path
>   (not `-`)

### Alternatives
1. The partitioning flags are exactly the three new ones: `--partition-by`,
   `--max-rows-per-file` and `--max-bytes-per-file`. Any one of them switches
   the tool into directory mode.
2. Only `--partition-by` is a "partitioning flag"; the two sharding flags keep
   single-file output and are simply ignored (or cut a single file into
   numbered siblings of `--output`).
3. Directory mode is inferred from `--output` instead (trailing slash, or the
   path already being a directory).

### Choice
Interpretation 1. The section that introduces the size/row flags is itself
titled "Partitioning by Size or Rows (sharding)", and it specifies file naming
"(no field partitioning): write files directly under `--output` as
`part-00000.csv`…", which only makes sense if `--output` is a directory when
those flags are used alone.

### Risk: 5
Most likely alternative preference: none material; the spec's own second
example shards with `--output out/` and no `--partition-by`.

---

## T38 — Do partition columns stay in the output CSVs?

### Spec Text
> - Each file contains header row (resolved schema header)

> **CSV Output Contents**
> - Every output CSV includes header row in resolved schema column order

### Alternatives
1. Every column of the resolved schema is written, including the partition
   columns, so a part file is self-describing and identical in shape to the
   single-file output.
2. Hive convention: the partition columns are projected out of the data files
   because their values are already encoded in the directory names.

### Choice
Interpretation 1. The spec says the header is *the resolved schema header* and
that output column order is *resolved schema column order*, with no exception
carved out for partition columns; dropping them would make the header depend on
`--partition-by`.

### Risk: 15
Most likely alternative preference: interpretation 2, if the author leaned on
real Hive/Spark behaviour rather than on the header sentence.

---

## T39 — Exact form of a Hive segment: what is encoded and how

### Spec Text
> `<col1>=<val1>/<col2>=<val2>/.../`
>   - Values derived after casting to resolved schema types
>   - Values use percent-encoding of UTF-8 bytes for characters outside
>     `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`

### Alternatives
1. Only the *value* is encoded; the column name is copied verbatim. The value
   encoded is the cell's rendered output text (the same text the CSV cell
   holds after casting), and hex digits are uppercase, matching `%2F`/`%20`.
2. Both the column name and the value are percent-encoded.
3. "After casting" means the *typed* value formatted some other way (e.g. a
   timestamp as an epoch number, an int as the raw input text `007`).
4. Lowercase hex (`%2f`), as `urllib.parse.quote` would produce with a custom
   safe set — except `quote` emits uppercase too, so this needs deliberate
   effort.

### Choice
Interpretation 1. The bullet says "**Values** use percent-encoding", and the
two worked-out examples in the spec (`%20`, `%2F`) are uppercase. Reusing the
rendered CSV text keeps the directory name and the cell in the file consistent,
which is what "derived after casting" buys you: `007` and `7` in an `int`
column land in the same partition.

### Risk: 20
Most likely alternative preference: interpretation 2 — the author runs one
`quote()` helper over the whole `name=value` segment, which would also encode
odd characters in column names.

---

## T40 — What counts as a null partition value

### Spec Text
> - Null (missing) partition values use literal `_null`

### Alternatives
1. A value is null exactly when the tool's own casting produced a missing
   value (empty CSV cell, JSON `null`, Parquet null, or a `coerce-null` cast
   failure). Nullness is decided on the value, not on the text it renders as.
2. A value is null when its rendered text equals `--csv-null-literal`, so with
   the default empty null literal any empty string is `_null`.
3. Only a *missing* column (absent key) is null; an empty CSV cell is an empty
   string and gets an empty segment `col=`.

### Choice
Interpretation 1. It is the only reading that stays consistent with the
existing null model (T8/T33): a JSONL `""` is a real empty string and gets the
segment `c=`, while an omitted key gets `c=_null`. Deciding from the rendered
text would make the layout depend on `--csv-null-literal` in a way the spec
never mentions. Note that `_null` is entirely inside the safe character set, so
a row whose value is literally the string `_null` shares the null directory —
the spec offers no escape hatch for that collision.

### Risk: 30
Most likely alternative preference: interpretation 2, if the author formats the
row first and then tests the resulting text against the null literal.

---

## T41 — Renaming onto an output directory that already exists

### Spec Text
> - Create directory if doesn't exist
> - Perform atomic write by creating sibling temp directory and renaming on
>   success

### Alternatives
1. The staged tree *replaces* whatever was at `--output`: the old directory is
   moved aside, the temp directory is renamed into place, and the old one is
   then deleted. After the run, `--output` contains exactly this run's files.
2. The staged tree is *merged into* an existing directory, file by file, so
   unrelated files (and stale `part-*.csv` from a previous, longer run)
   survive.
3. An existing non-empty `--output` is an error.

### Choice
Interpretation 1. A directory rename cannot land on a non-empty directory on
POSIX, so "renaming on success" only works as a commit step if the old tree is
cleared out of the way first. It is also the only variant that keeps the
Determinism Checklist's promise that the layout follows the rules exactly —
merging would let a previous run's shard count leak into the current one.

### Risk: 40
Most likely alternative preference: interpretation 2, if the author writes into
the temp directory and then moves its *entries* into an
`os.makedirs(output, exist_ok=True)` target.

---

## T42 — What the `--max-bytes-per-file` budget counts

### Spec Text
> - `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file
>   (including header and line endings) is ≤ INT
>   - Exception: if single row alone exceeds INT, place that row in file by
>     itself (allowed to exceed limit)

### Alternatives
1. The budget is the exact UTF-8 byte length of what is written: the header
   line (with its `\n`) plus each rendered data line (with quoting applied and
   its `\n`). Packing is greedy: rows are appended while the running total
   stays ≤ INT, and the file is cut before the first row that would exceed it.
   An oversized row is written into a fresh file on its own and that file is
   then closed immediately.
2. The budget counts data rows only, with the header exempt.
3. "Single row alone exceeds INT" is measured without the header, so a row
   that is smaller than INT but does not fit next to the header is not an
   "exception" case and something else must happen (the spec does not say
   what).

### Choice
Interpretation 1. The parenthesis "(including header and line endings)" pins
down both ends of the measurement, and greedy packing is the only cutting rule
that makes the result deterministic without lookahead. Readings 1 and 3 in fact
produce the same files — a row that cannot share a file with the header ends up
alone either way — so the difference is only in vocabulary.

### Risk: 20
Most likely alternative preference: the author writes through Python's `csv`
module to a text handle and counts `len(text)` in *characters*, which differs
from interpretation 1 for non-ASCII data.

---

## T43 — Partitioned output when the sorted stream is empty

### Spec Text
> - Create directory if doesn't exist
> - Within each partition directory, write CSV files named sequentially:
>   `part-00000.csv` …

### Alternatives
1. Sharding without field partitioning emits exactly one header-only
   `part-00000.csv`; field partitioning emits no directories at all (there is
   no partition to name), leaving `--output` created but empty.
2. Nothing is written in either case; `--output` is just created.
3. A header-only `part-00000.csv` is written at the root even when
   `--partition-by` was given.

### Choice
Interpretation 1. With no field partitioning the run still has exactly one
output stream, and the single-CSV mode emits a header-only file for empty
input, so the sharded form of the same stream should too. With field
partitioning there is no unique directory name to invent, so no file can be
placed.

### Risk: 35
Most likely alternative preference: interpretation 2 — the author creates part
files lazily on the first row and never special-cases the empty stream.

---

## T44 — Part indices beyond `part-99999.csv`

### Spec Text
> `part-00000.csv`, `part-00001.csv`, … (zero-padded width 5)

### Alternatives
1. Width 5 is a minimum: index 100000 becomes `part-100000.csv`.
2. The counter wraps or the width is a hard cap (truncating / erroring).

### Choice
Interpretation 1, i.e. `"part-%05d.csv"`. Zero padding is a formatting rule,
not a limit on the number of shards, and the spec insists the tool "must work
on arbitrarily large inputs".

### Risk: 5
Most likely alternative preference: none plausible; any other reading loses
data.

---

## T45 — Whether the shard counter is global or per directory

### Spec Text
> - File naming (with field partitioning): same `part-xxxxx.csv` sequence per
>   partition directory

### Alternatives
1. Each partition directory has its own counter starting at `part-00000.csv`.
2. One global counter, so file names are unique across the whole tree and most
   directories never contain a `part-00000.csv`.

### Choice
Interpretation 1. "per partition directory" attaches the sequence to the
directory, and the field-partition-only example is described as "one file per
partition", which under a global counter would give every partition a different
name.

### Risk: 5
Most likely alternative preference: none material.

---

## T46 — Shape of the `--partition-by` argument list

### Spec Text
> `[--partition-by <col>[,<col>...]]`

### Alternatives
1. Comma separated, repeatable (like `--key`), evaluated left to right; the
   list is de-duplicated, and an empty name (`"a,"`) is an error.
2. Single occurrence only; a repeat replaces the earlier value.
3. Duplicates are kept, producing a doubled directory level `c=x/c=x`.

### Choice
Interpretation 1, mirroring how `--key` is already handled — the two flags have
identical syntax in the usage block, so they should behave identically. A
repeated column contributes no extra information, and nesting it twice would
only lengthen the path.

### Risk: 15
Most likely alternative preference: interpretation 3, if the author maps the
list straight to segments without de-duplicating.

---

## T47 — Validation of the shard limits

### Spec Text
> `[--max-rows-per-file <INT>] [--max-bytes-per-file <INT>]`

### Alternatives
1. Both must be positive integers; `0` or a negative value is a usage error
   (exit 2), as is a non-integer (argparse's own exit 2).
2. `0` means "unlimited" (i.e. the flag is ignored).
3. `0` is accepted and produces an infinite stream of empty files or a crash.

### Choice
Interpretation 1. A limit of zero rows per file cannot be satisfied by any file
that contains a row, and the tool already rejects the other non-sensical
numeric flags (`--memory-limit-mb`, `--parquet-row-group-bytes`) with exit 2.

### Risk: 25
Most likely alternative preference: interpretation 2, if the author uses `0`
as the "unset" sentinel instead of `None`.

---

## T48 — Sort direction inside partitions

### Spec Text
> - With field partitioning: rows in each partition directory must be sorted by
>   `--key` within that partition

### Alternatives
1. `--desc` applies inside partitions exactly as it does globally; partitions
   are just a projection of the one globally sorted stream.
2. `--desc` is a global-output-only concept and partitions are always
   ascending.

### Choice
Interpretation 1. The partition rule is written as a weakening of the global
rule ("within that partition"), not as a different ordering, and implementing
it by routing the single sorted stream makes the two automatically agree.

### Risk: 5
Most likely alternative preference: none plausible.

---

## T49 — `--output` points at an existing regular file

### Spec Text
> - When any partitioning flag provided: `--output` must be directory path
>   (not `-`)
>   - Create directory if doesn't exist

### Alternatives
1. Exit 2 (usage), treating it as the same class of mistake as `--output -`.
2. Exit 1, treating it as an I/O failure discovered while preparing the output
   tree — the existing file is left untouched either way.

### Choice
Interpretation 2, with the message shape `error: cannot write output <path>:
…`. Only `-` is rejected by argument validation; whether a path happens to be a
file is a property of the filesystem, which the tool discovers at write time
alongside every other output I/O failure.

### Risk: 45
Most likely alternative preference: interpretation 1 — the author validates
`--output` once, up front, and emits exit 2 for both "is `-`" and "is a file".

---

## T50 — What directory mode writes to stdout

### Spec Text
> - When any partitioning flag provided: `--output` must be directory path
>   (not `-`)

> - Exact exit codes and stderr message shapes as specified

### Alternatives
1. Nothing: stdout stays empty and only errors are reported, on stderr with the
   existing `error: <message>` shape and the existing exit-code table (T18).
2. A manifest / summary of the files written is printed to stdout.

### Choice
Interpretation 1. The spec never describes a manifest format, and the
Determinism Checklist only asks for exact file names and "exact exit codes and
stderr message shapes as specified", which is the checkpoint-1 shape carried
forward.

### Risk: 5
Most likely alternative preference: none plausible.

# Checkpoint 4 — Nested Types Support

## Annotations to earlier entries

- **T18 is confirmed and extended.** The nested-types spec writes
  `ERR 4 cannot cast ...` for a cast failure under `--on-type-error=fail` and
  `ERR 3 key column ... does not resolve to a primitive`, which pins exit code
  4 to cast failures and 3 to key/partition resolution — exactly the table
  chosen in T18. Error 2 gains a new member (alias cycles) and error 6 is
  narrowed to "nested input without `--schema`".
- **T12's message shape is superseded.** The checkpoint-4 spec quotes literal
  stderr text beginning with `ERR <code> `, so the `error: <message>` prefix
  chosen in checkpoint 1 is replaced; see T51.
- **T16 still applies to keys**, but "same key" now means the same *field
  path* after normalisation, not the same column name.
- **T25 is reused for `--type-alias-file`**: like `--schema`, the argument is
  taken as a path unless it starts with `{`, in which case it is an inline
  document.
- **T38 is unchanged**: nested columns used for partitioning stay in the
  output CSV, and the partition value is the leaf primitive, not the cell.
- **The checkpoint-2 rule "any nested value in a JSONL/Parquet source is
  error 6" is superseded** by "Without `--schema`, nested inputs not allowed
  (error 6)"; with a schema the per-column rules apply. See T57.

---

## T51 — The stderr message shape for this checkpoint

### Spec Text
> * `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

> * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. Every error line now has the shape `ERR <code> <text>`, replacing the
   `error: <text>` prefix used since checkpoint 1.
2. Only these two messages are literal; every other failure keeps
   `error: <text>`, giving a mixed vocabulary.
3. The old prefix is kept and the `ERR n` text is embedded after it
   (`error: ERR 4 cannot cast ...`), so both shapes match.

### Choice
Interpretation 1. The spec spells two messages out in full and neither
carries the old prefix, and previous checkpoints only ever said "stderr
message shape as specified" — this is the first checkpoint that actually
specifies one. A single vocabulary is also the only reading under which the
code is always recoverable from the text. Tests written against the earlier
prefix were updated.

### Risk: 40
Most likely alternative preference: interpretation 2 — the author special-
cases the two documented messages and leaves every other error on whatever
prefix their checkpoint-1 code used.

---

## T52 — Are type *expressions* (`array<int>`) accepted where a type is expected?

### Spec Text
> * `list<T>`→`array<T>`

> `--schema` JSON file shape: ... `{"map": {"key": "string", "value": "string"}}`

### Alternatives
1. Nested types may be written either in the object form shown in the schema
   example or as a textual generic (`array<int>`, `map<string,int>`,
   `list<list<int>>`), since the alias table lists a parameterised alias
   `list<T>`→`array<T>` which is meaningless unless textual generics parse.
2. Only the object form exists; `list<T>`→`array<T>` describes the object key
   `{"list": {"element": ...}}` being an alias for `{"array": ...}`.
3. Both of the above.

### Choice
Interpretation 3: the object form is accepted with `list` as an alias for the
`array` key, *and* textual generics are parsed. This is the union of the two
readings, so a fixture written for either shape works. Textual generics are
also the only way an alias file entry such as `"tags": "array<string>"` can
be useful.

### Risk: 25
Most likely alternative preference: interpretation 1 only (no `{"list": ...}`
object key), which is a subset of what is implemented and so only differs on
inputs the author's implementation would reject.

---

## T53 — What `json` actually resolves to

### Spec Text
> * `json`→`struct` (accept any JSON, see below)

> Special alias `json`: when field declared as `"type":"json"`, accept any JSON
> value (object/array/primitive) and emit as JSON text

### Alternatives
1. `json` is a distinct "any" type; the alias line merely says it belongs to
   the struct family. A *bare* `"struct"` with no field list means the same
   thing, since the alias maps one onto the other.
2. `json` literally becomes `struct` with zero declared fields, so a `json`
   column would always emit `{}` — contradicted by "accept any JSON value
   (object/array/primitive)".
3. `json` is an "any" type but a bare `"struct"` string is an error, because
   a struct must always carry a `fields` list.

### Choice
Interpretation 1. Emitting `{}` for every value cannot be what the alias
means, so `json` is an accept-anything type, and because the alias table says
`json`→`struct`, a bare `"struct"` is accepted as a spelling of the same
thing rather than rejected.

### Risk: 20
Most likely alternative preference: interpretation 3 — same behaviour for
`"type":"json"`, but a bare `"type":"struct"` is a schema error (exit 3).

---

## T54 — Key order for objects inside a `json` value

### Spec Text
> * Struct fields in schema-declared order
> * Map keys sorted lexicographically
> * For `json` type: accept any JSON value without casting; normalize only

### Alternatives
1. A `json` value has no declared field order, so every object inside it is
   treated like a map: keys sorted lexicographically.
2. "Normalize only" means whitespace/escaping normalisation alone; object key
   order is preserved from the input text.

### Choice
Interpretation 1. The checkpoint's whole theme is byte-identical deterministic
output; preserving input key order would make the same logical value serialise
differently depending on which file it came from (and Parquet has no textual
order at all). Sorting is also the rule already given for the only other
undeclared-key construct, `map`.

### Risk: 35
Most likely alternative preference: interpretation 2 — `json.dumps(json.loads(cell))`
with default settings preserves input order, which is the path of least
resistance in a Python implementation.

---

## T55 — Invalid JSON in a CSV/TSV cell for a nested column

### Spec Text
> * **CSV/TSV**: Cell must contain single JSON literal when target type is nested or `json`
>   * Empty cell → null
>   * Invalid JSON → handled per `--on-type-error`/error 5

### Alternatives
1. It is an ordinary cast failure: `coerce-null` nulls the cell,
   `keep-string` keeps the raw text, `fail` exits 4 with the `ERR 4` message.
   The "/error 5" is a loose reference to the dialect-error family.
2. It is a dialect violation: the run always exits 5 regardless of
   `--on-type-error`.
3. Hybrid: `--on-type-error` decides, but `fail` exits 5 rather than 4
   because the failure is a dialect problem rather than a cast problem.

### Choice
Interpretation 1. "Handled per `--on-type-error`" is unconditional, and the
Casting & Validation section defines exactly one failure message, `ERR 4`, for
that path. Reading "/error 5" as the always-fatal rule would make the first
half of the same sentence dead text.

### Risk: 45
Most likely alternative preference: interpretation 3 — the author's code
raises its checkpoint-2 dialect error (exit 5) for unparseable JSON under
`--on-type-error=fail`.

---

## T56 — A Parquet nested column whose schema type is flat

### Spec Text
> * **Parquet**: Accept nested structs/lists/maps only when schema declares compatible nested types
>   * Without schema, nested triggers error 6

> * **JSONL**: ... If schema declares flat type but input has object/array, handle per `--on-type-error`

### Alternatives
1. Parquet behaves like JSONL: a nested column declared flat is a cast
   failure handled per `--on-type-error`.
2. "Only when schema declares compatible nested types" is a hard structural
   rule, so a nested Parquet column against a flat declaration is error 6.
3. It is a schema mismatch, exit 3.

### Choice
Interpretation 1. The JSONL bullet states the rule for exactly this situation
and nothing suggests the two formats diverge; error 6 is tied by the
Determinism Checklist to "without `--schema`", which is not the case here.

### Risk: 40
Most likely alternative preference: interpretation 2 — the author checks the
Arrow schema against the declared schema up front and raises error 6 on any
structural mismatch.

---

## T57 — Nested input in a column the schema does not declare

### Spec Text
> * Without `--schema`, nested inputs not allowed (error 6)

> * **JSONL**: Accept nested objects/arrays only when schema declares column as nested or `json`

### Alternatives
1. With a schema present, columns absent from the schema are never
   materialised, so a nested value there is ignored like any other undeclared
   column.
2. Flatness stays a property of the *source*: any nested value anywhere in a
   JSONL/Parquet file is error 6 unless the schema declares that very column
   nested (the checkpoint-2 behaviour, extended).

### Choice
Interpretation 1. Error 6 is now explicitly conditioned on "without
`--schema`", and a column that is not in the output schema is never cast, so
there is no type to be incompatible with. The checkpoint-2 test asserting
error 6 for this case was updated and annotated.

### Risk: 30
Most likely alternative preference: interpretation 2 — the author's JSONL
reader still rejects nested values as it walks the row, before the schema is
consulted.

---

## T58 — A literal column name that contains a dot

### Spec Text
> * `--key` and `--partition-by` now accept **field paths** using dot notation (e.g., `user.id`, `items.0.sku`)

### Alternatives
1. If the whole argument equals a declared/inferred column name, it is that
   column; otherwise it is parsed as a path.
2. The argument is always parsed as a path, so a flat column literally named
   `user.id` becomes unreachable.
3. Path parsing is only attempted when a schema is provided.

### Choice
Interpretation 1. It keeps every checkpoint-1..3 behaviour intact (inferred
CSV headers routinely contain dots) and still resolves `user.id` as a path
whenever no such column exists. Interpretation 3 is implied by it in practice,
because inference never produces nested columns.

### Risk: 25
Most likely alternative preference: interpretation 2 — the author splits on
`.` unconditionally, so a dotted flat column name now errors.

---

## T59 — The Hive directory label for a nested partition path

### Spec Text
> * Nested schema; key on nested leaf; partition by map value:
>   `--partition-by attrs["country"]`

> (checkpoint 3) Hive-style `<col>=<value>` subdirectories

### Alternatives
1. `<col>` is the path exactly as written: `attrs["country"]=US`.
2. `<col>` is the last path segment: `country=US`, `sku=...`, `id=...`.
3. `<col>` is the path percent-encoded like the value:
   `attrs%5B%22country%22%5D=US`.

### Choice
Interpretation 1. Checkpoint 3 fixed that only the *value* is encoded, and the
label has always been the thing the user named on the command line; the path
is that thing now. Interpretation 2 also collides whenever two paths share a
leaf name (`a.id` and `b.id`).

### Risk: 50
Most likely alternative preference: interpretation 2 — the author uses the
leaf name because bracket and quote characters in a directory name look
wrong; a fixture partitioning on `attrs["country"]` would then expect a
`country=US` directory.

---

## T60 — Struct input with missing or extra members

### Spec Text
> * All struct fields included (even when null) with explicit `null` values
> * **struct**: ordered list of named fields (names unique within struct)

### Alternatives
1. Declared fields missing from the input become `null`; keys present in the
   input but not declared are dropped. The schema is a projection.
2. A missing declared field is a cast failure handled per `--on-type-error`.
3. An undeclared key is an error (strict structural match).

### Choice
Interpretation 1. "All struct fields included (even when null)" only needs
saying if absent members are normal, and the declared field list is described
as the output order — i.e. the schema selects, exactly as the top-level
column list does for flat columns.

### Risk: 15
Most likely alternative preference: interpretation 3 under a hypothetical
"structurally match" reading of the Determinism Checklist.

---

## T61 — How far alias validation goes, and when

### Spec Text
> * May refer to built-ins or other aliases (resolve transitively; detect cycles proactively → error 2)

> * Alias resolution is case-insensitive, transitive, cycle-checked; unknown types error deterministically

### Alternatives
1. Cycles are detected when the alias file is loaded, over every entry,
   whether used or not (that is what "proactively" adds) → exit 2. An alias
   whose target is simply unknown is only an error when a schema actually uses
   it → exit 3, the existing unknown-type code.
2. Both cycles and unknown targets are validated at load time, both exit 2.
3. Everything is lazy: an unused cyclic alias is never noticed.

### Choice
Interpretation 1. "Proactively" is attached specifically to cycle detection,
so cycles — and only cycles — are checked over the whole file up front.
Unknown type names stay on the checkpoint-1 path where "unknown type for
column X" is a schema error.

### Risk: 30
Most likely alternative preference: interpretation 2 — the author validates
the closure of the alias table once and reports any unresolvable target with
the same code as a cycle.

---

## T62 — Using a path that enters a `json` column as a key

### Spec Text
> * Each path must resolve to primitive value after casting
>   * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. Resolution is *static*, against the declared schema. A `json` column has no
   declared interior, so any path into it (and the column itself) fails with
   error 3 before a row is read.
2. Resolution is *dynamic*, per row: the path is walked through the actual
   value, and a row where it lands on a primitive is fine, while a row where it
   lands on a container errors — or yields null.

### Choice
Interpretation 1. Exit code 3 is the schema family, and the error is phrased
as a property of the key column rather than of a row; a data-dependent exit
code would also defeat the determinism the checklist demands.

### Risk: 35
Most likely alternative preference: interpretation 2 with a null fragment for
non-primitive landings, which lets `json` columns be sorted on.

---

## T63 — Map traversal with a dot, array traversal with brackets

### Spec Text
> * Map lookups with `["key"]` read value by exact key; quotes are required

### Alternatives
1. The bracket form is the *only* map accessor: `attrs.country` against a map
   is error 3, as is `items["0"]` against an array, and `user["name"]`
   against a struct.
2. The accessors are interchangeable — a dot segment against a map is a key
   lookup, a bracket against an array is an index.

### Choice
Interpretation 1. "Quotes are required" is a syntax rule that only bites if
the bracket form is mandatory for maps, and keeping one accessor per kind
makes a path's meaning independent of the data.

### Risk: 30
Most likely alternative preference: interpretation 2 for the struct/dot side
at least — many implementations walk containers generically by string key and
would happily resolve `attrs.country`.

---

## T64 — Rendering of `<val>`, `<type>`, `<path>` and `(file=... line=...)`

### Spec Text
> * `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

### Alternatives
1. `<val>` is the offending scalar (JSON-escaped, in double quotes); `<type>`
   is the declared type rendered as `int` / `array<int>` / `map<string,int>` /
   `struct` / `json`; `<path>` is the dotted/bracketed path from the column
   root (`user.age`, `items.0.qty`, `attrs["x"]`); `file=` is the input path
   as given on the command line and `line=` the 1-based line (row number for
   Parquet).
2. `<path>` is only the field name, without its ancestors.
3. `<val>` is the whole cell rather than the failing leaf.

### Choice
Interpretation 1 — it is the only reading in which `<path>` earns its name,
and it matches the path syntax the same spec defines for `--key`. Flat columns
use the bare column name as the path, which keeps one message for both worlds.

### Risk: 45
Most likely alternative preference: the same fields with different spacing or
punctuation (e.g. `line=` omitted for Parquet, or `<type>` printed as
`array<int64>`); tests that match the message exactly rather than by prefix
would then differ.

---

## T65 — What `keep-string` keeps inside a nested value

### Spec Text
> * `keep-string`: set to original unparsed JSON string or stringified form

### Alternatives
1. The failing node is replaced by a JSON *string* containing the canonical
   JSON text of the original subvalue (`{"a":1}` for an object, `abc` for a
   string that failed to cast, `1.5` for a number).
2. The failing node keeps its original JSON *value* unchanged (an object stays
   an object), which is "unparsed" in the loosest sense.

### Choice
Interpretation 1. "Set to ... string" is explicit, and the flag's flat-column
behaviour (keep the raw text as a string) generalises directly. Keeping a
whole object in place would also break the declared type of the node for
sorting.

### Risk: 35
Most likely alternative preference: interpretation 2 for container nodes and
interpretation 1 for scalars, since "original unparsed JSON" reads like "leave
it as it came".

---

## T66 — "Entire column value is null" versus an all-null struct

### Spec Text
> * If entire column value is null → emit CSV null literal
> * All struct fields included (even when null) with explicit `null` values

### Alternatives
1. Only a value that is itself JSON `null` (or a missing/empty cell) prints
   the CSV null literal. A struct whose members are all null still prints
   `{"a":null,"b":null}`, and an empty array prints `[]`.
2. A value that contains no data at all (all members null, empty containers)
   also counts as "entirely null" and prints the null literal.

### Choice
Interpretation 1. The two bullets are adjacent and the second one insists
explicit nulls are emitted, which only makes sense if such a struct is still
serialised. "Entire column value" points at the value as a whole being null,
not at its contents.

### Risk: 25
Most likely alternative preference: interpretation 2 for the specific case of
an input row that simply has no such key at all — which interpretation 1 also
renders as the null literal, so the readings differ only for an explicitly
empty container.

---

## T67 — Malformed path syntax

### Spec Text
> * Array indices must be non-negative integers
> * Map lookups with `["key"]` read value by exact key; quotes are required

### Alternatives
1. A path that cannot be parsed at all (`items[0]` unquoted, `a..b`,
   `items.-1.sku`, an unterminated bracket) is a key/partition resolution
   failure: exit 3, like every other bad key column.
2. It is an argument error: exit 2.

### Choice
Interpretation 1. Every other "this key column is unusable" outcome in the
spec is exit 3 (missing column, non-primitive target), and the spec never
routes a `--key` problem to exit 2. A single code for the whole family is the
easier one to predict.

### Risk: 30
Most likely alternative preference: interpretation 2, if the author validates
path syntax while parsing arguments rather than while resolving them against
the schema.

---

## T68 — Duplicate field names and bad map key types in a schema

### Spec Text
> * **struct**: ordered list of named fields (names unique within struct)
> * **map\<string,T>**: string keys only

### Alternatives
1. Both are schema errors (exit 3), like the existing duplicate-column check:
   a struct with two fields named `a`, or a map declared with a non-string
   key, is rejected before any input is read.
2. Duplicates are tolerated, last (or first) wins; a non-string map key is
   coerced to string.

### Choice
Interpretation 1. "Names unique within struct" and "string keys only" are
stated as constraints on a valid schema, and checkpoint 1 already rejects
duplicate top-level column names with exit 3, so the nested case inherits it.

### Risk: 15
Most likely alternative preference: silently accepting a missing `"key"`
member (which this implementation also does, defaulting it to `string`) but
tolerating a declared non-string key.

---

## T69 — Do aliases apply to the type inside `--schema` only?

### Spec Text
> * Case-insensitive aliases accepted anywhere type is expected

### Alternatives
1. Aliases apply to every position where a type name appears: top-level
   column types, struct field types, array element types, map key and value
   types. Inference is untouched (it never reads type names from the user).
2. Aliases also rename *columns* or affect how inferred types are printed.

### Choice
Interpretation 1, literally: "anywhere type is expected". `--type-alias-file`
with no `--schema` is accepted (and still cycle-checked) but has nothing to
apply to.

### Risk: 10
Most likely alternative preference: rejecting `--type-alias-file` without
`--schema` as a usage error.

---

## T70 — Non-string keys arriving in a map value

### Spec Text
> * **map\<string,T>**: string keys only; value type T can be nested or primitive

### Alternatives
1. Keys that arrive as non-strings (a Parquet `map<int32,…>`, a JSON object
   can only have string keys) are stringified with the primitive `string`
   rules and then sorted, so the value survives.
2. A non-string key is a cast failure for the whole map, handled per
   `--on-type-error`.

### Choice
Interpretation 1. "String keys only" describes the declared type, and the
lexicographic sort in the output section presumes textual keys; stringifying
is the normalisation that makes that true rather than a reason to discard
data.

### Risk: 20
Most likely alternative preference: interpretation 2, reached by validating
the Arrow map key type against the declaration up front (which pairs with the
T56 alternative).
