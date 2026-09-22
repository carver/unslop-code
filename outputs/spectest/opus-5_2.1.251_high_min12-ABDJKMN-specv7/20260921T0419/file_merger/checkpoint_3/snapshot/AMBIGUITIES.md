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

### Annotation (checkpoint 2)
**Resolved against this choice.** Checkpoint 2 states "Use configured CSV dialect
flags for output quoting/escaping and chosen null literal", so `--csv-quotechar`
now quotes output fields as well. The implementation was changed accordingly; see
[T29] for what "escaping" means on the output side, where doubling is retained.

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

### Annotation (checkpoint 2)
**Partly resolved.** Checkpoint 2 names specific codes (2 for undetectable input
format, 3 for a key column missing from the resolved schema, 5 for
dialect/compression violations, 6 for nested structures) and demands "Exact exit
codes". The "abort before writing anything" half of this choice stands; the
"always exit 1" half does not. The full code map now used is in [T18].

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

---

# Checkpoint 2 — Multi-Format CSV Merger

---

## T18. The full exit-code map

### Spec Text
> otherwise error 2
> Keys must exist in resolved schema (error 3 otherwise)
> Mismatch is error 5
> nested fields trigger error 6
> Exact exit codes and stderr message shape as specified

### Alternatives
1. The named codes are points on a per-error-class map, and the classes the spec
   does not number get the remaining small codes: `1` generic/I-O,
   `2` usage + undetectable format, `3` schema/key problems, `4` cast failure
   under `--on-type-error fail`, `5` malformed input or dialect/compression
   violation, `6` nested structure.
2. Only the four named situations get their codes and every other failure keeps
   checkpoint 1's blanket `1` (so a `fail` cast error and an invalid schema file
   both exit 1).
3. Codes are per *phase* rather than per class (e.g. everything discovered while
   reading inputs is 5).

### Choice
Alternative 1. The numbering the spec does hand out is class-shaped, not
incidental: 2 = "I cannot tell what this input is" (argparse's own usage code),
3 = schema/key, 5 = the bytes violate the declared dialect, 6 = the data model is
richer than flat. The unnamed gap at 4 sits exactly where checkpoint 1's only
other distinct failure mode lives ("`fail`: write error to stderr and exit
non-zero"), so cast failure is assigned 4, and plain I/O errors keep 1. Every
message keeps checkpoint 1's shape: `merge_files.py: error: <detail>` on stderr,
nothing on stdout.

### Risk: 40
The author most likely prefers: the same 2/3/5/6 assignments (these are
dictated), but `1` — not `4` — for a `--on-type-error fail` cast failure.

---

## T19. `authoritative` precedence order, and what "typed sources" means

### Spec Text
> `--schema-strategy=authoritative` (default): prefer typed sources in precedence order; JSONL ranks equal to CSV.

### Alternatives
1. Two tiers: Parquet (self-describing, physically typed) outranks
   {JSONL, CSV, TSV}, which are equal. The highest tier that carries the column
   decides its type; lower-tier files never vote.
2. Three tiers: Parquet > JSONL > CSV = TSV, reading "JSONL ranks equal to CSV"
   as being about *rank ties elsewhere*. (Hard to sustain: the sentence says the
   opposite.)
3. Precedence by command-line position — the first file that has the column wins.

### Choice
Alternative 1. Parquet is the only input whose types are carried in the file
itself, so it is "the typed source"; the trailing sentence exists precisely to
stop a reader from assuming JSON's value types promote JSONL above CSV. When
two files in the *winning* tier disagree, the tier is resolved by the `--infer`
rule from checkpoint 1 (strict → `string`; loose → the widest type all their
values fit), which keeps CSV-only runs byte-identical to checkpoint 1 — the one
compatibility constraint an extension must satisfy.

### Risk: 55
The author most likely prefers: the same two tiers, but resolving an intra-tier
disagreement by first-file-wins rather than by falling back to `string`.

---

## T20. What "majority of files support" counts in `consensus`

### Spec Text
> `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives
1. One vote per file for the type that file infers on its own (its per-file
   inferred type); the type with the most votes wins; ties are broken by the
   published type priority (`timestamp` > `date` > `bool` > `int` > `float` >
   `string`).
2. Literal "support": for each candidate type, count the files all of whose
   values can cast to it, and take the type with the highest count. Degenerate —
   every file supports `string`, so `string` always wins.
3. Majority means *strict* majority (> half); with no strict majority fall back
   to `string`.

### Choice
Alternative 1. Reading 2 makes the flag a no-op, so the useful reading is a vote
over per-file inferred types. Priority breaks ties because the spec already
publishes a total order over types for exactly this purpose, and it keeps the
result independent of the order the files were listed in.

### Risk: 50
The author most likely prefers: the same vote, but ties broken by falling back
to `string` (or by first-file-wins) rather than by type priority.

---

## T21. What "simplest common type that can hold all observed values" is in `union`

### Spec Text
> `--schema-strategy=union`: choose simplest common type that can hold all observed values

### Alternatives
1. The highest-priority type that *every* non-null observed value (pooled across
   all files) can cast to — `int` + `float` → `float`, `date` + `timestamp` →
   `timestamp`, `int` + `"abc"` → `string`.
2. A fixed widening lattice over the *per-file types* only (int ⊑ float ⊑ string,
   date ⊑ timestamp ⊑ string) without re-examining values, so `int` + `bool`
   → `string` even when the ints are all 0/1.
3. "Simplest" = fewest constraints = always `string`.

### Choice
Alternative 1. "Can hold all observed values" points at the values, not at the
per-file labels, and it is the same all-values rule checkpoint 1's `loose` mode
already uses — so `union` is `loose` pooling applied across heterogeneous
sources. Reading 3 would make the option pointless.

### Risk: 30
The author most likely prefers: the lattice of reading 2, which agrees with this
choice on int/float and date/timestamp fixtures and differs only on mixed cases
such as `bool` + `int`.

---

## T22. How `--infer` and `--schema-strategy` compose

### Spec Text
> - Type inference per `--infer` mode (strict or loose)
> - **Schema disagreement strategy** when inputs have conflicting types for same column

### Alternatives
1. Two stages: `--infer` governs how each *file* types a column; the strategy
   governs how files are reconciled. `union` and `consensus` fully determine the
   reconciliation; `authoritative` defers a within-tier disagreement back to
   `--infer` (strict → `string`, loose → widen).
2. `--schema-strategy` supersedes `--infer` entirely whenever it is given.
3. `--infer` supersedes the strategy (strict always collapses conflicts to
   `string`, so `union`/`consensus` only take effect in loose mode).

### Choice
Alternative 1. The two flags are described in separate bullets at different
stages of the same pipeline, and only this composition leaves checkpoint 1's
behaviour intact for CSV-only runs: with the default `authoritative` all text
files sit in one tier, so `strict` still means "files must agree or the column
is `string`" and `loose` still means "widest type all pooled values fit".

### Risk: 45
The author most likely prefers: the strategy alone decides cross-file conflicts,
with `--infer` reduced to a per-value strictness knob — which differs from this
choice whenever `--infer loose` is combined with the default strategy.

---

## T23. How typed (JSONL/Parquet) values participate in *inference*

### Spec Text
> - JSONL values come typed (string/number/bool/null)
> - Parquet values come typed
> - Type inference per `--infer` mode (strict or loose)

### Alternatives
1. Hybrid: a non-string typed value contributes its own type (JSON `true` →
   `bool`, JSON `7` → `int`, Parquet `double` → `float`, Parquet `date32` →
   `date`); a *string* value — from JSONL or a Parquet `string` column — is
   sniffed exactly like a CSV cell, so `"2024-07-01T00:00:00Z"` in JSONL infers
   `timestamp` just as the same text in CSV does.
2. Text-first: render every typed value as text and run checkpoint 1's sniffer,
   so a JSON `1` infers `bool` (1 is a bool literal in checkpoint 1's rules).
3. Types-only: strings from typed sources stay `string` and are never sniffed,
   so a JSONL ISO-8601 field can never infer as `timestamp`.

### Choice
Alternative 1. "Values come typed" is the spec's reason not to sniff numbers and
booleans, but it says nothing about the *content* of strings, and the mixed
example sorts a `ts` key that arrives as CSV text in one file and as a JSON
string in another — those two must land on the same type for the sort to mean
anything. The visible cost is that CSV `"1"` infers `bool` while JSONL `1`
infers `int`; that follows from the typed source actually being typed.

### Risk: 45
The author most likely prefers: reading 3, where JSONL/Parquet strings are just
`string` and only CSV/TSV text is ever sniffed.

---

## T24. "prefer `int` if integer and within range"

### Spec Text
> For JSONL numbers, prefer `int` if integer and within range; otherwise `float`

### Alternatives
1. "Within range" is the signed 64-bit range: a JSON number that is integral and
   fits in int64 becomes a Python `int` (so `2.0` → `2`, `1e30` stays a float);
   an integer *literal* stays `int` at any magnitude, since it never needed a
   float in the first place.
2. "Within range" is Python's unbounded `int`, so any integral float (including
   `1e30`) becomes an `int` and prints as `1000000000000000019884624838656`.
3. Only JSON integer literals are ints; `2.0` is always a float.

### Choice
Alternative 1. A bare "within range" only means something if the range is
bounded, and int64 is the range every other format here uses (Parquet's `int64`,
the range a downstream loader will assume). Reading 2 would also print the
float's binary noise, which is the opposite of the spec's determinism aims.

### Risk: 20
The author most likely prefers: the same, with the boundary only observable on
values above 2^63.

---

## T25. Detecting "literal tabs inside field" in TSV, and the required header

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required ... literal tabs inside field not allowed (error 5)

### Alternatives
1. With no quoting, an embedded tab is indistinguishable from a delimiter, so the
   only observable symptom is a data row with *more* fields than the header:
   that is error 5. Rows with fewer fields stay lenient (missing → null, as in
   checkpoint 1), and a file with no header line at all (empty file) is error 5.
2. Any row whose field count differs from the header's (too few as well as too
   many) is error 5.
3. The rule is unenforceable and is documentation only; never raise error 5 while
   reading TSV.

### Choice
Alternative 1. The spec bothers to give the violation an error code, so it must
be detectable, and "more fields than the header" is the only detectable trace an
embedded tab can leave. Short rows are left lenient because checkpoint 1 already
fixed that behaviour for CSV and nothing in checkpoint 2 revisits it; "header row
required" is read as making a headerless (empty) TSV an error rather than an
empty result.

### Risk: 40
The author most likely prefers: the same too-many-fields rule; the exposure is
the empty-file case and whether short TSV rows are also error 5.

---

## T26. What counts as a compression "mismatch"

### Spec Text
> - `--compression=auto` (default): detect `.gz` → gzip; otherwise none
> - `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> - Mismatch is error 5

### Alternatives
1. Mismatch = the declared/derived compression disagrees with the file's magic
   bytes, in every direction: `--compression=gzip` on non-gzip bytes, 
   `--compression=none` on gzip bytes, and (under `auto`) a `.gz` name whose
   bytes are not gzip. Under `auto`, gzip magic without a `.gz` name is accepted
   as gzip rather than treated as an error, since `auto` is a detector.
2. Mismatch only covers the forced directions; `auto` never errors and simply
   believes the extension.
3. Mismatch means the *format* and the compression disagree (e.g. `.parquet.gz`),
   not the bytes.

### Choice
Alternative 1. The sentence sits directly under the three detection bullets and
is the only way any of them can fail, so it is about detection disagreeing with
reality. Erroring on `data.csv.gz` that is not gzip is more useful than handing
the CSV reader binary noise, and `auto` accepting gzip magic on an odd name is
what "detect" implies.

### Risk: 35
The author most likely prefers: `auto` trusts the extension only (so gzip magic
under a plain name is read as text and fails later, if at all), while the two
forced directions error.

---

## T27. When is an extension "ambiguous"?

### Spec Text
> - `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
> - If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

### Alternatives
1. "Ambiguous" = not one of the four listed extensions (including no extension at
   all). A listed extension is always trusted and never sniffed; anything else is
   sniffed for the `PAR1` magic and, failing that, is error 2.
2. "Ambiguous" also covers listed-but-contradicted cases, so a `.csv` file whose
   bytes start with `PAR1` is read as parquet.
3. Unknown extensions fall back to CSV rather than erroring.

### Choice
Alternative 1. The two bullets are a cascade: map the known extensions first,
and only when that fails consult the bytes. Reading 3 contradicts the explicit
"otherwise error 2". `--input-format` remains the escape hatch for oddly named
files, and it suppresses detection entirely.

### Risk: 25
The author most likely prefers: the same cascade, plus magic-byte override for a
`.csv`/`.tsv`/`.jsonl` file that is really Parquet.

---

## T28. `--schema <SCHEMA_JSON>`: file path or inline JSON?

### Spec Text
> [--schema <SCHEMA_JSON>]
> ```
> --schema schema.json
> ```

### Alternatives
1. A path to a JSON file (as in checkpoint 1 and the example), but also accept a
   literal JSON document when the argument starts with `{` and no such file
   exists — a superset that cannot change the behaviour of the documented form.
2. Strictly a path.

### Choice
Alternative 1: the documented form is a path and behaves identically either way;
the inline form only rescues an invocation that would otherwise be a
file-not-found error.

### Risk: 10
Only reachable by an argument that is not an existing file.

---

## T29. What "configured dialect flags for output quoting/escaping" means

### Spec Text
> Use configured CSV dialect flags for output quoting/escaping and chosen null literal

### Alternatives
1. `--csv-quotechar` becomes the output quote character (minimal quoting: quote
   only when the field contains the delimiter, the quote character, or a newline),
   and quotes inside a field are still escaped by **doubling**; `--csv-escapechar`
   remains an input-side concession. The output delimiter stays `,` because the
   spec says "Always produce single CSV".
2. `--csv-escapechar` also switches the output to backslash-style escaping
   (`doublequote=False`).
3. Full symmetry, including using the escape char to escape delimiters in
   unquoted fields.

### Choice
Alternative 1. `--csv-escapechar` has a non-`None` default (`\`) inherited from
checkpoint 1, so honouring it on output under reading 2 would silently change the
default output encoding of every quoted field — which contradicts checkpoint 1's
"escape by doubling" and would break byte-comparisons of unrelated runs. Quote
character has no such default hazard, so it is honoured.

### Risk: 25
The author most likely prefers: the same for the quote character; divergence is
limited to files where a value containing the quote character is emitted while
`--csv-escapechar` was passed explicitly.

---

## T30. Is an empty *string* from JSONL/Parquet a null?

### Spec Text
> If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal

### Alternatives
1. Read literally: for typed sources only an actual `null` is missing, so a JSON
   `""` is an empty string value (it casts like any other text, and only an
   explicit `null` bypasses casting). For inference, however, an empty string is
   treated as a non-observation in every format, as checkpoint 1 already does.
2. Empty strings are missing everywhere, typed sources included.

### Choice
Alternative 1 for casting: the sentence is carefully split by source kind, which
is only meaningful if `""` from JSONL is *not* the same as an empty CSV cell.
Inference keeps ignoring empty strings everywhere because checkpoint 1's [T2]
choice already treats them as nulls for that purpose and nothing here revisits
it.

### Risk: 30
The author most likely prefers: empty strings are missing everywhere, since a
single `is_missing()` helper is the natural implementation.

---

## T31. Mapping Parquet/Arrow types onto the six schema types

### Spec Text
> - **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6
> - Parquet values come typed

### Alternatives
1. `int*`/`uint*` → `int`; `float`/`double`/`decimal` → `float`; `bool` → `bool`;
   `date32`/`date64` → `date`; `timestamp` → `timestamp` (naive values read as
   UTC, zoned values converted to UTC, matching checkpoint 1's rule "if source
   lacked zone, treat as UTC"); `string`/`binary` → `string`; `time`/`duration`/
   `interval` → `string` via their ISO-ish text. List/struct/map/union → error 6.
2. Decimal → `string` to avoid binary-float rounding.
3. Any type outside the six → error 6, not just nested ones.

### Choice
Alternative 1. The spec reserves error 6 for *nested* fields specifically, so
exotic-but-flat types degrade to `string` rather than failing, and the numeric
families map onto the obvious targets. Decimals become `float` because `float` is
the only numeric type the schema vocabulary offers for non-integers.

### Risk: 30
The author most likely prefers: the same for the common int/float/bool/string/
date/timestamp columns (the only ones a fixture is likely to contain); decimal
and time columns are where readings diverge.

---

## T32. "write atomically", and cleanup of the temporary output

### Spec Text
> `--output -` writes to stdout; otherwise write atomically

### Alternatives
1. Write to a temporary file in the destination's own directory, flush it, then
   `os.replace()` it onto the destination — so a reader sees either the old file
   or the complete new one, never a prefix. On any error the temporary file is
   removed and the destination is left untouched.
2. Write in place and rely on the process not failing.

### Choice
Alternative 1, the standard meaning of atomic replacement (same directory keeps
the rename on one filesystem). Combined with checkpoint 1's [T14] choice, a run
that fails for any reason leaves no output file at all — and no stray temporary
beside it. `--parquet-row-group-bytes` is likewise given a harmless default
(128 MiB, advisory) that cannot change emitted bytes.

### Risk: 5
Observable only as the absence of partial files.

---

## T33. Casting an already-typed value to a different target type

### Spec Text
> Apply target output schema cast rules to every cell

### Alternatives
1. One cast path for everything: render the typed value into its canonical text
   (the same text this tool would emit for it) and apply checkpoint 1's cast
   rules to that text. So a Parquet `double` 2.0 under a schema of `int` fails
   (text `2.0` is not an int) exactly as the CSV text `2.0` would, and a JSON
   `2.0` succeeds because the JSONL reader has already made it the int `2`.
2. A type-pair matrix that truncates or rounds numerics in-memory, so Parquet
   `double` 2.0 → `int` 2 while CSV `"2.0"` → `int` still fails.

### Choice
Alternative 1. "Apply target output schema cast rules" points back at the one set
of cast rules the spec defines — the checkpoint 1 text rules — and a single path
guarantees that a value which round-trips through CSV casts the same way as the
value read from Parquet directly.

### Risk: 35
The author most likely prefers: a lenient numeric path where an integral float
from a typed source casts to `int`.

---

## T34. Which flags switch `--output` from "a file" to "a directory"

### Spec Text
> - When no partitioning flags provided: write single CSV to `--output` (file path or `-` for stdout)
> - When any partitioning flag provided: `--output` must be directory path (not `-`)

### Alternatives
1. "Partitioning flag" means any of the three new flags — `--partition-by`,
   `--max-rows-per-file`, `--max-bytes-per-file`. Any one of them makes
   `--output` a directory; `-` is then a usage error (exit 2, argparse shape).
2. Only `--partition-by` switches modes; the sharding flags alone still write a
   single file (and are silently ignored, or cut a file that cannot be named).
3. Directory mode is entered, but `--output -` is tolerated by streaming the
   first shard to stdout.

### Choice
Alternative 1. The second example in the spec uses `--max-rows-per-file` with no
`--partition-by` and still writes `out/` containing `part-xxxxx.csv` files, which
rules out Alternative 2 directly. `-` is rejected before any work is done, with
the usage-error code argparse already owns (2) — the same code [T18] assigns to
"the command line does not describe a runnable job".

### Risk: 25
The author most likely prefers: the same mode rule (it is spelled out), but
possibly exit 1 rather than 2 for the `--output -` rejection, since that check is
easy to write as a runtime `ToolError` after parsing.

---

## T35. Are the partition columns still written inside the CSV files?

### Spec Text
> - Each file contains header row (resolved schema header)
> - Every output CSV includes header row in resolved schema column order

### Alternatives
1. Keep every column, partition columns included. The header is *the* resolved
   schema header, unconditionally, so a partition file has the same columns as a
   non-partitioned run; the value is simply also encoded in the path.
2. Drop the partition columns from the files (classic Hive/Spark behaviour —
   the value lives only in the directory name and is reconstructed on read).

### Choice
Alternative 1. Both bullets say "resolved schema header" with no subtraction
clause, and the "CSV Output Contents" section repeats it for *every* output CSV.
Dropping columns would also make the header depend on `--partition-by`, which the
determinism checklist never mentions.

### Risk: 20
The author most likely prefers: the same (keeping the columns), but a spec author
steeped in Hive semantics could plausibly have pruned them.

---

## T36. Exactly which bytes are percent-encoded, and in what case

### Spec Text
> Values use percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`

### Alternatives
1. Encode every byte of the UTF-8 encoding whose character is not in
   `[A-Za-z0-9._-]`, as `%` + two **upper-case** hex digits. `%` itself is
   outside the safe set, so it becomes `%25`; `=` becomes `%3D`; every byte of a
   non-ASCII character is encoded individually (`é` → `%C3%A9`). The
   *column name* in `name=value` is written verbatim — the rule is scoped to
   values.
2. Lower-case hex (`%2f`), as `urllib.parse.quote` would produce if asked for
   lower case.
3. Encode the column name too, or leave `%` unescaped (so encoding is not
   reversible).

### Choice
Alternative 1. The two worked examples in the sentence (`%20`, `%2F`) are both
upper case, which settles the hex case, and "percent-encoding of UTF-8 bytes"
settles the multi-byte behaviour. Escaping `%` itself is required for the scheme
to be a function of the value at all. Scoping to values follows the sentence's
subject ("Values use…"): column names come from the schema and are left alone.

### Risk: 20
The author most likely prefers: the same safe set and upper-case hex (both are
`urllib.parse.quote(v, safe='')`-shaped), with the residual risk concentrated on
whether `%` and `=` are themselves escaped.

---

## T37. `_null` versus an empty-string partition value

### Spec Text
> Null (missing) partition values use literal `_null`

### Alternatives
1. `_null` marks a *missing* cell only — an empty CSV cell, an absent JSONL key,
   a Parquet null, or a cell coerced to null by `--on-type-error coerce-null`. A
   genuine empty string (e.g. `""` from JSONL, which [T30] keeps as a value)
   partitions as `col=` with an empty segment tail.
2. Anything that renders as the empty output text — including a real empty
   string — becomes `_null`, i.e. the check is `rendered == null_literal`.

### Choice
Alternative 1. The spec writes "Null (missing)", glossing null *as* missing,
which is the same distinction checkpoint 2 drew between a JSON `null` and a JSON
`""`; reusing it keeps one notion of missing across the tool. It also keeps the
directory name a function of the cell's state rather than of
`--csv-null-literal`, which would otherwise make the layout depend on an
output-formatting flag.

### Risk: 35
The author most likely prefers: Alternative 2 in practice, because comparing the
already-rendered text against the null literal is the shortest implementation —
the two readings differ only on empty strings reaching the tool from JSONL or
Parquet.

---

## T38. What "renaming on success" does when `--output` already exists

### Spec Text
> - Create directory if doesn't exist
> - Perform atomic write by creating sibling temp directory and renaming on success

### Alternatives
1. Build everything in a sibling temp directory, then install it as `--output`,
   **replacing** whatever directory was there: the destination ends up holding
   exactly this run's files, never a mixture with an earlier run's. (POSIX cannot
   rename onto a non-empty directory, so an existing destination is first moved
   aside to a second sibling temp name and deleted after the swap succeeds.)
2. Merge: move the temp directory's entries *into* the existing destination,
   leaving unrelated files from earlier runs in place and overwriting
   same-named ones.
3. Refuse to run when the destination already exists.

### Choice
Alternative 1. Checkpoint 1's single-file mode replaces the destination wholesale
via `os.replace`, and the sentence here asks for the directory analogue of that;
a merge would leave stale `part-00007.csv` files from a longer previous run
sitting beside a shorter new one, which contradicts "Directory layout and file
names follow exact rules". A pre-existing *empty* destination is simply removed
and renamed over, so the common "mkdir out/ first" case is a plain atomic rename.

### Risk: 30
The author most likely prefers: the same for a fresh or empty destination (almost
certainly what the fixtures use); a merge into a dirty destination is the likely
divergence, and only a test that deliberately pre-seeds `out/` would see it.

---

## T39. Output when the sorted stream is empty

### Spec Text
> Within each partition directory, write CSV files named sequentially: `part-00000.csv`, `part-00001.csv`, …
> Every output CSV includes header row in resolved schema column order

### Alternatives
1. Field partitioning emits directories only for partition values that actually
   occur, so zero rows means an empty (but created) `--output` directory. With
   sharding and **no** field partitioning there is exactly one stream, so a
   header-only `part-00000.csv` is written — mirroring checkpoint 1, where an
   input with no data rows still produces a header-only CSV.
2. Zero rows produces an empty output directory in both cases.
3. Zero rows produces no directory at all.

### Choice
Alternative 1. A partition directory is defined by "rows for each unique
combination", so with no rows there are no combinations and nothing to name; but
the unpartitioned sharded stream is the same single output checkpoint 1 wrote,
and dropping its header would lose the schema a downstream reader needs.

### Risk: 45
The author most likely prefers: the same empty-directory result for field
partitioning; whether a header-only `part-00000.csv` appears for the
sharding-only case is a genuine coin flip and depends on whether their writer
opens the first file eagerly or lazily.

---

## T40. What counts toward `--max-bytes-per-file`, and how the two limits combine

### Spec Text
> `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file (including header and line endings) is ≤ INT
> - Exception: if single row alone exceeds INT, place that row in file by itself (allowed to exceed limit)
> When both `--max-rows-per-file` and `--max-bytes-per-file` provided, cut at earliest boundary that would violate either constraint

### Alternatives
1. The budget is measured in UTF-8 bytes of the file as written: the header line
   (with its `\n`) counts in **every** part, each data row costs its rendered
   CSV line including quoting and its `\n`, and no BOM or trailing blank line is
   added. A row is appended only if `bytes_so_far + row_bytes <= INT`; otherwise
   the part is cut first. The "single row" exception applies when the row does
   not fit even into a file that holds only the header — the row is written
   anyway, alone. The two limits are evaluated together before each row: the part
   is cut as soon as either would be violated, so the file that would have
   overflowed never gets written.
2. The header counts only once (in the first part), or the limit applies to data
   bytes only.
3. Rows are appended first and the file is cut *after* the limit is exceeded, so
   each part overshoots by one row.

### Choice
Alternative 1. "including header and line endings" makes the measurement the
literal size of the file on disk, and a file's size on disk includes its own
header, not a previous file's. "cut at the earliest boundary that would violate
either constraint" is explicitly pre-emptive — the cut happens *before* the
violation, which rules out Alternative 3. The single-row exception is scoped to
the case where no cut could help.

### Risk: 25
The author most likely prefers: the same accounting; the divergence, if any, is
whether a row that fits in an empty part but not the current one is preceded by a
cut (chosen here) or triggers the exception path.

---

## T41. A `--partition-by` column that is not in the resolved schema

### Spec Text
> `--partition-by <col>[,<col>...]`
> Keys must exist in resolved schema (error 3 otherwise)

### Alternatives
1. Partition columns are held to the same rule as key columns: a name not in the
   resolved schema is a schema error, exit 3, with the same message shape.
2. It is a usage error (exit 2).
3. Unknown partition columns are treated as all-null and produce a single
   `col=_null` directory.

### Choice
Alternative 1. `--partition-by` names resolved-schema columns exactly as `--key`
does — the values are explicitly "derived after casting to resolved schema
types", so a name outside that schema has no value to derive. Reusing code 3
keeps one meaning for "you named a column that does not exist".

### Risk: 30
The author most likely prefers: the same code 3; the alternative worth naming is
exit 2, if their check lives in argument validation rather than after schema
resolution.

---

## T42. Part numbering scope and what happens past `part-99999`

### Spec Text
> write CSV files named sequentially: `part-00000.csv`, `part-00001.csv`, … (zero-padded width 5)
> File naming (with field partitioning): same `part-xxxxx.csv` sequence per partition directory

### Alternatives
1. The counter is **per directory**: every partition directory starts again at
   `part-00000.csv`, and with no field partitioning there is one counter for
   `--output` itself. Past 99999 the width simply grows (`part-100000.csv`),
   since zero-padding to 5 is a minimum, not a truncation.
2. One global counter shared across all partition directories, so names are
   unique tool-wide and most directories start at some arbitrary index.
3. Numbering wraps or errors past 99999.

### Choice
Alternative 1. "same `part-xxxxx.csv` sequence per partition directory" says the
sequence is a property of the directory, and the first example's `part-00000.csv`
is described without reference to which partition it is in. Growing the width is
the only option that keeps names unique and ordered.

### Risk: 10
Reaching six digits requires 100k parts; the per-directory reading is stated.

---

## T43. Which text a partition value is taken from

### Spec Text
> Values derived after casting to resolved schema types

### Alternatives
1. The partition segment uses exactly the text the tool would write into the CSV
   cell for that value — the canonical rendering of the cast value. So a `bool`
   column partitions as `flag=true`, a `timestamp` as its normalized form, a
   `float` `1.50` as `1.5`. Under `--on-type-error keep-string` a cell that
   failed to cast keeps its original text (and partitions by it); under
   `coerce-null` it is missing and partitions as `_null`.
2. The raw input text before casting, so `1.50` and `1.5` land in different
   directories.
3. A separate "partition rendering" (e.g. `True`/`False` from Python) distinct
   from the CSV rendering.

### Choice
Alternative 1. "after casting" excludes Alternative 2, and using the same
rendering the cell gets in the file keeps a partition directory name consistent
with the column it was derived from — a reader that reconstructs the column from
the path gets the same string the file contains. `keep-string` and `coerce-null`
follow from the cell's post-cast state for the same reason.

### Risk: 20
The author most likely prefers: the same rendering; the `keep-string` and
`coerce-null` corners are where an implementation could differ, and they are
unlikely to be combined with `--partition-by` in a fixture.
