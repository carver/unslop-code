# Ambiguities

Numbered record of spec passages that admit more than one conforming
implementation, the reading chosen here, and the risk that the spec author's
own implementation (and therefore the hidden tests) reads it differently.

---

## T1. What distinguishes `strict` from `loose` inference

### Spec Text
> - `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`
> - `loose`: prefer numeric/temporal types if all non-null observed values parse; otherwise fall back to `string`; empty strings are treated as nulls and don't affect inference

### Alternatives
1. **Per-file then agree (strict) vs. global pool (loose).** In `strict`, each
   file independently yields a type for the column; if two files disagree the
   column becomes `string`. In `loose`, all values from all files are pooled and
   the highest-priority type that *every* non-null value parses as is chosen.
   Under this reading `{10}` in A and `{9.5}` in B is `string` in strict but
   `float` in loose.
2. **Same algorithm in both modes**, differing only in null handling (loose
   ignores empty strings, strict does not). `{10}`/`{9.5}` would be `float` in
   both.
3. **Strict means "one exact type per value"**: a column is typed only if every
   value has the identical top-priority type; any widening (int+float,
   bool+int) is a conflict — even within a single file.

### Choice
Alternative 1. The two bullets are written as a contrast: strict's clause is
about *files disagreeing*, loose's clause is about *all values parsing*. That
only carries information if strict is computed per file and loose globally, and
it explains why loose is described as the more permissive "prefer numeric /
temporal" mode. Within a file (and within loose's global pool) the type is the
highest-priority type that all non-null values parse as, which is exactly
loose's stated rule and makes the published priority list meaningful.

### Risk: 45
The author most likely prefers: strict and loose share one pooled inference
pass and differ only in whether empty strings count as observations.

---

## T2. Do empty cells affect inference in `strict` mode?

### Spec Text
> `loose`: ... empty strings are treated as nulls and don't affect inference

### Alternatives
1. The clause merely defines "non-null" for loose; empty strings are nulls
   everywhere, so a column of `10`, ``, `9` is `int` in both modes.
2. The clause is a *contrast* with strict: in strict an empty string is an
   observed value that parses as nothing but `string`, so the same column is
   `string` in strict and `int` in loose.

### Choice
Alternative 1. Empty cells are nulls throughout the rest of the spec ("Missing
values emitted as the null literal", "Missing columns in a file filled with
null literal", "Nulls always compare less than non-null values"). Making a
single blank cell demote an otherwise-numeric column to `string` in the default
mode would also make the default mode nearly useless on the ragged, multi-file
input this tool exists to merge. The loose bullet is the only place the term
"non-null" appears, so reading the clause as a definition of that term fits.

### Risk: 35
The author most likely prefers: in `strict`, an empty cell is an observation
that forces the column to `string`.

---

## T3. Output text for `bool` values

### Spec Text
> `bool` includes `1`/`0` along with standard values

(No output form is specified for booleans, unlike the explicit temporal rules.)

### Alternatives
1. Normalize to lowercase `true` / `false`.
2. Emit Python's `str(bool)` → `True` / `False`.
3. Pass the original input text through unchanged (`1` stays `1`, `TRUE` stays
   `TRUE`).

### Choice
Alternative 1. The spec's "Deterministic Dialect Details" section shows the tool
normalizes typed values on output (timestamps most explicitly), so a bool column
fed `1`, `TRUE`, `true` should have one canonical rendering; `true`/`false` is
the CSV/JSON convention and is itself a "standard value" the tool can re-read.

### Risk: 40
The author most likely prefers: `True` / `False`, the direct result of `str()`
on a Python bool.

---

## T4. Output text for successfully cast `int` / `float` values

### Spec Text
> - Cast every input cell into target type (rules below)
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. Emit the normalized Python value (`str(7)` → `7` for input `007`;
   `str(9.5)` → `9.5`; `1e2` → `100.0`).
2. Emit the original cell text whenever the cast succeeds, so only failures and
   temporal values are rewritten (`007` stays `007`, `1e2` stays `1e2`).

### Choice
Alternative 1. The pipeline is defined as cast → sort → emit; once a cell is an
`int`, the only way back to text is formatting it, and an implementation that
kept the raw text would have no reason to describe `keep-string` as the mode
that "emit[s] original text as string" — that phrase implies the other modes do
*not* emit original text.

### Risk: 35
The author most likely prefers: original text preserved for cells that cast
cleanly, with only temporal columns rewritten.

---

## T5. How many fractional-second digits a normalized timestamp keeps

### Spec Text
> `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`), keeping fractional seconds

### Alternatives
1. Preserve the source's fractional digits: `.123` → `.123`, `.5` → `.5`.
2. Always six digits, the result of `datetime.isoformat().replace("+00:00","Z")`:
   `.123` → `.123000`.
3. Six digits with trailing zeros stripped: `.123` → `.123`, `.100` → `.1`.

### Choice
Alternative 1. "Keeping fractional seconds" reads as *keep what was there*, and
the example shows that a timestamp with no fraction gains no `.000000`, which
already rules out unconditional six-digit formatting of every value. Preserving
the source digits agrees with alternative 3 on the common fixtures (`.123`,
`.5`) and differs only on trailing zeros.

### Risk: 45
The author most likely prefers: `datetime.astimezone(utc).isoformat()` with
`+00:00` replaced by `Z`, i.e. six-digit microseconds whenever a fraction is
present.

---

## T6. Applying the type priority list to values that match several types

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> Inference recognises values by the casting rules below

### Alternatives
1. A column's type is the highest-priority type that *all* its non-null values
   parse as. A column of `1`/`0` is therefore `bool` (bool outranks int), while
   `1`/`0`/`5` is `int` and `1`/`2.5` is `float`.
2. Priority only breaks ties between whole columns (e.g. one file says `int`,
   another says `float` → take the higher-priority `int`), with per-value typing
   done by a first-match cascade.
3. Priority is only documentation for the schema path and inference never
   produces `bool` from `1`/`0`.

### Choice
Alternative 1. It is the only reading under which the published order is fully
operative, it makes `date` reachable (a `timestamp` that accepted date-only text
would starve `date` of every value), and it matches loose mode's wording
"prefer numeric/temporal types if all non-null observed values parse".
`timestamp` accordingly requires a time component; `date` is `YYYY-MM-DD` only.

### Risk: 30
The author most likely prefers: the same all-values rule but with `int` ranked
ahead of `bool` in practice, so a 0/1 column infers as `int`.

---

## T7. Is `--csv-null-literal` recognised on input, or only used on output?

### Spec Text
> Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives
1. Symmetric: a cell equal to the null literal is read as null (in addition to
   the empty string, which is always null), so the tool round-trips its own
   output.
2. Output-only: with `--csv-null-literal NULL`, the text `NULL` in an `int`
   column is a cast failure handled by `--on-type-error`.

### Choice
Alternative 1. Round-tripping is the only behaviour that makes the flag
coherent for a tool whose output can be another run's input. Note the two
readings agree on the default `coerce-null` path (a failed cast is emitted as
the null literal anyway) and differ mainly for `--on-type-error fail` and for
type inference.

### Risk: 30
The author most likely prefers: output-only, with input nulls being empty
strings exclusively.

---

## T8. Does `--csv-quotechar` / `--csv-escapechar` affect the *output* dialect?

### Spec Text
> Quote character defaults to `"`; escape character defaults to doubling the quote (`""`) and accepts backslash-escapes (`\"`), overrideable via flags

> Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives
1. The flags configure input parsing only; output is always `,` / `"` /
   doubling, as the "Deterministic Dialect Details" section states
   unconditionally.
2. The flags configure both sides, so `--csv-quotechar "'"` also quotes output
   fields with `'`.

### Choice
Alternative 1. The dialect section is titled "Deterministic" and enumerates the
output properties with no reference to the flags; the flags live under "Fixed
CSV assumptions", which describes inputs. Treating the output quote as fixed is
also the only reading consistent with output escaping being fixed to doubling
even when `--csv-escapechar` is supplied.

### Risk: 20
The author most likely prefers: the quote character flag applies to output too.

---

## T9. Ordering when `keep-string` leaves mixed value kinds in one key column

### Spec Text
> `keep-string`: emit original text as string
> Nulls always compare less than non-null values, regardless of sort direction

### Alternatives
1. Order by kind first (null < number < date < timestamp < string), then within
   a kind by natural value order, so a kept string always sorts after the typed
   values of that column.
2. Compare everything as text once any cell in the column is kept as a string.
3. Leave it undefined / let the comparison raise.

### Choice
Alternative 1. It is total, deterministic, and preserves the spec's only stated
cross-kind rule (nulls first) by treating "null" as the lowest kind; degrading
the whole column to text would contradict "cast every input cell into target
type" for the cells that did cast.

### Risk: 25
The author most likely prefers: kept strings compared against typed values via
their string forms.

---

## T10. Default value of `--memory-limit-mb`

### Spec Text
> [--memory-limit-mb <INT>]
> Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs

### Alternatives
1. A finite default (e.g. 128MB) with the same external-sort code path always
   in use.
2. Unlimited by default (pure in-memory sort unless the flag is given).

### Choice
Alternative 1, with the external merge sort always active: chunk size is the
only thing the limit changes, so the emitted bytes are identical for every
value of the flag and for its absence. The default is 128MB.

### Risk: 5
Output cannot differ between the readings; only peak RSS does.

---

## T11. Which texts a `timestamp`-typed column accepts, and whether `date` text is one

### Spec Text
> `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output
> if source lacked zone, treat as UTC

### Alternatives
1. Accept any ISO-8601 datetime (`T` or space separator, optional fraction,
   optional offset or `Z`) and also bare `YYYY-MM-DD`, which becomes
   `…T00:00:00Z`.
2. Require a time component; a bare date in a `timestamp` column is a cast
   failure.

### Choice
Alternative 1 for *casting* (a date is a valid ISO-8601 instant designation and
midnight UTC is the natural completion), while *inference* still assigns bare
dates to `date` — otherwise the `date` type could never be inferred (see T6).

### Risk: 35
The casting half is low risk (`datetime.fromisoformat` accepts a bare date, so
most implementations will too). The exposure is the inference half: an
implementation whose `timestamp` predicate is just "`fromisoformat` succeeds"
will, under the priority list, infer `timestamp` for a column of bare dates and
emit `2024-07-01T00:00:00Z` where this implementation emits `2024-07-01`.

The author most likely prefers: a single ISO parser shared by cast and
inference, so bare-date columns infer as `timestamp`, not `date`.

---

## T12. "Stable with respect to input appearance" across files

### Spec Text
> Sort must be stable with respect to input appearance for equal keys

### Alternatives
1. Appearance order = the order files are listed on the command line, then row
   order within each file.
2. Some other total order (sorted file names, interleaved reads).

### Choice
Alternative 1 — the only order a reader would call "input appearance", and the
one produced by concatenating the inputs in argv order before sorting. Note
shell globs such as `data/*.csv` arrive already sorted by the shell.

### Risk: 5

---

## T13. "Ascending lexicographic order of column names"

### Spec Text
> Column order: ascending lexicographic order of column names

### Alternatives
1. Code-point order (`Alpha` < `beta` < `zeta`; all uppercase before lowercase).
2. Case-insensitive / locale-aware collation.

### Choice
Alternative 1: plain code-point ordering, i.e. Python's `sorted()`. It is what
"lexicographic" means for a byte/character sequence and needs no locale.

### Risk: 10
The author most likely prefers: the same; risk is limited to fixtures that mix
letter cases in column names.

---

## T14. Error reporting details (exit status, when `fail` aborts, partial output)

### Spec Text
> `fail`: write error to stderr and exit non-zero
> If a key column is not present in resolved schema, that is an error

### Alternatives
1. Exit status 1 for tool errors (2 for argparse usage errors), abort on the
   first offending cell, and write nothing to the output destination — no
   partial file, no partial stdout.
2. Continue scanning and report all failures, or emit rows already sorted
   before aborting.

### Choice
Alternative 1. The spec only constrains "non-zero", and an aborted run that has
already emitted a prefix of an unsorted-looking CSV would violate "produces one
sorted CSV output". Output is therefore materialized only after all casting
succeeds. Unreadable/missing input files are reported the same way.

### Risk: 5
Any non-zero status satisfies the text; only a test asserting an exact code
(e.g. 2) would diverge.

---

## T15. Extreme float texts (`nan`, `inf`) and underscore digit grouping

### Spec Text
> `int`, `float`, `string`: standard parsing

### Alternatives
1. "Standard parsing" is Python's `int()` / `float()`, which accept `nan`,
   `inf`, `1_000` and surrounding whitespace.
2. A stricter numeric grammar that rejects them.

### Choice
Alternative 1 for the cast path (leading/trailing whitespace is stripped), but
inference does **not** recognise `nan`/`inf` as numeric, so a column containing
them stays `string` unless a schema says otherwise. This keeps accidental words
from turning text columns into float columns while leaving explicit schemas
permissive.

### Risk: 15
The author most likely prefers: plain `float()` everywhere, so a column of
`inf`/`nan` would infer as `float`.

---

## T16. Repeated `--key` flags and duplicate key columns

### Spec Text
> --key <col>[,<col>...]

### Alternatives
1. Only the comma-separated form is meaningful; a repeated flag replaces the
   previous value.
2. Repeated flags accumulate, appending to the key list.

### Choice
Alternative 2 (a superset): `--key a --key b` behaves like `--key a,b`, and
`--key a,b` behaves identically under both readings, so the documented form is
unaffected. Empty key names are rejected as usage errors.

### Risk: 5
The documented single-flag form is identical either way.

---

## T17. Blank lines, short rows, and rows longer than the header

### Spec Text
> All inputs are UTF-8, RFC-4180 compliant, with a header row
> Missing values emitted as the null literal

### Alternatives
1. A blank line yields no fields and is skipped; a row with fewer fields than
   the header has its remaining columns treated as null; extra fields beyond
   the header are dropped.
2. A blank line is a data row of all-null columns; a short row is an error.

### Choice
Alternative 1, the lenient reading (`for row in reader: if not row: continue`).
Inputs are declared RFC-4180 compliant, so this only governs edge inputs; a
trailing newline at end of file must not become a spurious all-null row.
Consequence worth noting: in a *single-column* file, a row whose only value is
empty is textually identical to a blank line and is skipped.

### Risk: 15
The author most likely prefers: the same, since it is what a plain
`csv.reader` loop with a blank-row guard produces.
