# Ambiguities

Numbered record of under-specified points in the CSV Merger and Sorter spec,
the interpretation chosen for this implementation, and the residual risk that
the spec author's own implementation (and therefore the hidden tests) reads it
differently.

---

## T1: `strict` vs `loose` inference semantics

### Spec Text

> - `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`
> - `loose`: prefer numeric/temporal types if all non-null observed values parse; otherwise fall back to `string`; empty strings are treated as nulls and don't affect inference

### Alternatives

1. **Per-file vs. global**: `strict` infers a type *per input file* and falls back to
   `string` when two files disagree; `loose` infers over the union of all values from
   all files. Under this reading `{1,2}` in file A and `{1.5}` in file B is `string`
   in strict (int vs float conflict) but `float` in loose.
2. **Identical algorithm, different leniency**: both modes infer globally, and the only
   difference is that `loose` ignores empty strings while `strict` lets an empty string
   force `string`.
3. Empty-string handling: (a) empty is a null in *both* modes (shared helper), or
   (b) empty counts as an observed value in `strict`, so any blank cell forces `string`.

### Choice

Reading 1 combined with 3(a): per-file inference + cross-file conflict → `string` for
`strict`; global inference for `loose`; empty strings are treated as nulls (ignored) in
both modes. Reading 1 is the only one that gives the phrase "conflicting types across
files" any work to do, and a single shared `infer(values)` helper — used per file in
strict and over the union in loose — is the shortest implementation that satisfies both
bullets. A column with no non-null observed values infers as `string`.

### Risk: 35

Author most likely prefers: same per-file/global split, but with empty strings counted
as observed values in `strict` (so a blank cell degrades that column to `string`),
because the spec calls out null-skipping only under `loose`.

---

## T2: Type priority applied to inference makes `0`/`1` columns `bool`

### Spec Text

> - Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`

### Alternatives

1. Priority is the tie-break for inference: a column is typed as the **highest-priority**
   type that *every* non-null value parses as. A column of `1`/`0` parses as bool, int and
   float, so it becomes `bool`.
2. Priority is only a widening order used to merge conflicting per-file types (pick the
   highest-priority of the conflicting types), leaving inference itself to prefer the
   "narrowest" numeric type, so `1`/`0` → `int`.
3. Priority is inert documentation attached to the `--schema` section (where it appears)
   and never affects behavior.

### Choice

Reading 1. The priority list is the only tie-break rule in the spec, and an explicit
schema needs no priority at all, so the list must be aimed at inference. Reading 2 is
unusable for merging conflicts because the higher-priority type is not guaranteed to
parse the other file's values (int vs float → `int` would fail on `1.5`), and strict
mode already says conflicts fall back to `string`. Consequence: `1`/`0` columns infer as
`bool`, and `2024-07-01` columns infer as `date` (see T6).

### Risk: 40

Author most likely prefers: `int` for a column of `1`/`0` values, with bool inference
restricted to literal `true`/`false` text.

---

## T3: Rendering of `bool` values in the output

### Spec Text

> - `bool` includes `1`/`0` along with standard values

### Alternatives

1. Emit lowercase `true` / `false`.
2. Emit Python's `str(bool)` — `True` / `False` (what `csv.writer` produces if native
   `bool` objects are handed to it).
3. Preserve the original source text (`1` stays `1`, `TRUE` stays `TRUE`).

### Choice

Lowercase `true`/`false`. The spec demands a canonical normalized rendering for the other
non-string type it discusses (`timestamp` → UTC `Z`), so a canonical rendering for bool is
in keeping; `true`/`false` is the JSON/CSV convention and matches the `"type": "bool"`
spelling used in the schema document. Reading 3 is ruled out by "Cast every input cell
into target type".

### Risk: 45

Author most likely prefers: `True`/`False`, which is what falls out of writing native
Python bools through `csv.writer` without a formatting hook.

---

## T4: Rendering of `float` values in the output

### Spec Text

> - `int`, `float`, `string`: standard parsing

### Alternatives

1. Canonical Python `repr` of the parsed float: `1` → `1.0`, `1.50` → `1.5`,
   `1e3` → `1000.0`.
2. Preserve the original text whenever it parses (`1` stays `1`, `1.50` stays `1.50`).
3. Fixed decimal formatting (e.g. `%.6f`).

### Choice

Reading 1. "Cast every input cell into target type" implies the output is a rendering of
the parsed value, not of the source text, and `repr`/`str` is the shortest round-trip
representation, which is the natural default in Python.

### Risk: 35

Author most likely prefers: the same, but source-text preservation for values that
already look canonical is the plausible alternative, which differs on inputs like `1`
and `1.50` in a float column.

---

## T5: Accepted `timestamp` inputs and fractional seconds on output

### Spec Text

> - `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output
> - `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`); if source lacked zone, treat as UTC

### Alternatives

1. Accept the ISO-8601 forms `datetime.fromisoformat` accepts (`T` or space separator,
   optional fractional seconds, `Z` or `±HH:MM` offset, and bare dates), and render
   `%Y-%m-%dT%H:%M:%SZ`, appending `.ffffff` only when the microsecond field is non-zero.
2. Accept only `YYYY-MM-DDTHH:MM:SS[Z|±HH:MM]` and always render whole seconds,
   truncating any fractional part.
3. Always render six fractional digits.

### Choice

Reading 1: be liberal on input (ISO-8601 covers all of these), canonical on output, and
never silently discard sub-second precision that was present in the source. A bare date
in a `timestamp` column casts to midnight UTC.

### Risk: 30

Author most likely prefers: truncating fractional seconds so every timestamp renders as
`YYYY-MM-DDTHH:MM:SSZ`.

---

## T6: `timestamp` outranks `date`, but date-only text must still infer as `date`

### Spec Text

> - Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> - `date`: ISO-8601 `YYYY-MM-DD`

### Alternatives

1. During *inference*, `timestamp` requires a time component, so `2024-07-01` is only a
   `date` candidate; during *casting* against an explicit schema, a `timestamp` column
   accepts a bare date (midnight UTC).
2. `timestamp` accepts bare dates everywhere, in which case priority makes every date
   column infer as `timestamp` and `2024-07-01` renders as `2024-07-01T00:00:00Z` —
   making the `date` type unreachable by inference.

### Choice

Reading 1. Reading 2 makes `date` dead code under inference, which cannot be the intent
of a spec that lists `date` as an inferable type and pins its output format.

### Risk: 20

Author most likely prefers: the same; the alternative only bites if their timestamp
parser is a bare `fromisoformat` used for both inference and casting.

---

## T7: Does `--csv-null-literal` also mean "null" when *reading*?

### Spec Text

> - Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives

1. Output-only: on input, a cell is null iff it is the empty string. `--csv-null-literal`
   only controls emission.
2. Symmetric: an input cell equal to the null literal is also read as null.

### Choice

Reading 1. Every mention of the null literal in the spec is on the emission side
("emitted as", "filled with"), and the input side is described independently
("empty strings are treated as nulls"). Making it symmetric would additionally change
inference and sort position for any column that legitimately contains the literal text.

### Risk: 25

Author most likely prefers: the same; symmetry is the plausible alternative and would
differ on sort position of a cell whose text equals a non-empty null literal.

---

## T8: Is an empty cell in a typed column a cast failure?

### Spec Text

> - On cast failure, apply `--on-type-error`:
>   - `fail`: write error to stderr and exit non-zero

### Alternatives

1. An empty cell is a *missing value*, not a bad value: it becomes null in every mode,
   and `--on-type-error fail` does not trigger on it.
2. An empty cell fails to parse as `int`, so `fail` mode aborts on it.

### Choice

Reading 1. The spec treats emptiness as nullness elsewhere ("empty strings are treated as
nulls"), and the output contract has a dedicated representation for missing values, so a
blank cell is well-defined input rather than an error.

### Risk: 20

Author most likely prefers: the same; reading 2 only arises from a naive `int(cell)` in a
`try` block with no null pre-check.

---

## T9: Sort position of `keep-string` residue in a key column

### Spec Text

> - `keep-string`: emit original text as string
> - Nulls always compare less than non-null values, regardless of sort direction

### Alternatives

1. Within one key column, values that were successfully cast compare among themselves,
   and uncast (kept-string) values form a second class that sorts *after* all cast
   values in ascending order (and correspondingly before them under `--desc`),
   comparing lexicographically among themselves.
2. Uncast values sort *before* cast values.
3. Everything in the column is compared as its output text (string comparison),
   discarding numeric ordering entirely.

### Choice

Reading 1. It preserves correct numeric/temporal ordering for the well-formed majority
(which reading 3 would destroy: `10` before `9`), and putting the anomalous values last
mirrors the spec's only stated class rule, where the "special" class (nulls) is pinned to
one end.

### Risk: 30

Author most likely prefers: reading 3 (compare the emitted text) if their sort key is
built from the output row rather than typed values — though that contradicts null-first
ordering, which needs typed knowledge.

---

## T10: Scope of `--csv-quotechar` and `--csv-escapechar`

### Spec Text

> - Quote character defaults to `"`; escape character defaults to doubling the quote (`""`), overrideable via flags
> - Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives

1. Both flags affect input parsing; `--csv-quotechar` additionally affects the output
   quote character; output always escapes by doubling (never uses `--csv-escapechar`).
2. Both flags affect input parsing only; the output dialect is frozen at `"`/doubling.
3. Both flags affect input and output.

### Choice

Reading 1. The "Deterministic Dialect Details" section describes the defaults of a
dialect the flags are explicitly allowed to override, so honoring `--csv-quotechar` on
output keeps input and output round-trippable; but "escape by doubling quotes" is stated
twice as the output rule, so `--csv-escapechar` stays an input-side concern.

### Risk: 30

Author most likely prefers: reading 2 (frozen output dialect). This is only observable
when an output field actually requires quoting.

---

## T11: `--schema <SCHEMA_JSON>` — path or inline JSON?

### Spec Text

> [--schema <SCHEMA_JSON>]
> **If `--schema` is provided**: JSON file with exact output schema and column order

### Alternatives

1. Always a filesystem path.
2. Either: a path if it names an existing file, otherwise parse the argument as inline
   JSON text.

### Choice

Reading 2 — a strict superset of reading 1. The prose says "JSON file" (so a path must
work), while the metavar `SCHEMA_JSON` hints at literal JSON; accepting both cannot break
a path-based test.

### Risk: 10

Author most likely prefers: path-only, which this implementation still satisfies.

---

## T12: Failure signalling

### Spec Text

> - `fail`: write error to stderr and exit non-zero
> - If a key column is not present in resolved schema, that is an error

### Alternatives

1. Exit code `1` for all runtime errors (bad cast under `fail`, unknown key column,
   unreadable input, bad schema), message on stderr, no output file written.
2. Distinct exit codes per error class.

### Choice

Reading 1, with the additional guarantee that the destination file is not created (all
casting happens during ingest, before any output byte is written), and that a pre-existing
destination file is left untouched. Tests assert only "non-zero", as the spec does.

### Risk: 15

Author most likely prefers: the same; the only plausible divergence is whether a partly
written output file is left behind.

---

## T13: What "stable with respect to input appearance" orders by

### Spec Text

> - Sort must be stable with respect to input appearance for equal keys

### Alternatives

1. Input appearance = (position of the file in the command-line argument list, then row
   position within that file); this tiebreak is always ascending, including under
   `--desc`.
2. Under `--desc`, the tiebreak is also reversed.

### Choice

Reading 1. "Stable" is a term of art meaning equal elements retain their original relative
order; reversing the tiebreak under `--desc` would make the sort unstable by definition.

### Risk: 10

Author most likely prefers: the same (Python's `sorted(..., reverse=True)` is also stable
in exactly this way).

---

## T14: Default `--memory-limit-mb`

### Spec Text

> [--memory-limit-mb <INT>]
> - Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs

### Alternatives

1. Default to a modest bound (64 MB) and always use the external-sort path when the
   buffer exceeds it.
2. Unbounded by default (pure in-memory sort unless the flag is given).

### Choice

64 MB, matching the example the spec calls "small". The value is not observable in the
output; only peak memory and temp-file usage change.

### Risk: 5

Author most likely prefers: any default; output is identical either way.

---

## T15: Duplicate column names within one input header

### Spec Text

> **If `--schema` not provided**: infer schema from union of all input headers

### Alternatives

1. First occurrence wins; later duplicates are ignored.
2. Last occurrence wins.
3. Hard error.

### Choice

First occurrence wins. `csv.DictReader` semantics are last-wins, but first-wins matches
"the column named X is the one the header first introduces" and avoids an error on input
the spec never forbids.

### Risk: 15

Author most likely prefers: whatever `DictReader` does (last wins) if they built on it.

---

## T16: Rows whose field count differs from the header

### Spec Text

> - All inputs are UTF-8, RFC-4180 compliant, with a **header row**

### Alternatives

1. Tolerate: pad short rows with nulls, ignore surplus fields.
2. Error out.

### Choice

Tolerate. The spec promises well-formed input, so this path should never be exercised by
conforming fixtures; being permissive cannot fail a test that never produces ragged rows,
whereas erroring could.

### Risk: 15

Author most likely prefers: the same tolerance (a `dict(zip(...))` naturally drops/pads).

---

## T17: Numeric parsing edge cases

### Spec Text

> - `int`, `float`, `string`: standard parsing

### Alternatives

1. `int`: optional sign, decimal digits only (`+5`, `-5`, `007` ok; `1e3`, `1.0`,
   `1_0`, whitespace-padded not ok). `float`: anything `float()` accepts *except*
   `nan`/`inf`/`infinity`, which are rejected so that text columns containing the word
   "nan" don't infer as numeric.
2. Whatever `int()`/`float()` accept, including `1_0`, `nan` and `inf`.

### Choice

Reading 1. Python's underscore-in-literal and non-finite spellings are language features,
not CSV conventions, and admitting them would silently retype text columns.

### Risk: 25

Author most likely prefers: a bare `int(s)`/`float(s)` in a try/except, which additionally
accepts `1_0`, `nan` and `inf` and strips surrounding whitespace.

---

## T18: Which literals count as "standard values" for `bool`

### Spec Text

> - `bool` includes `1`/`0` along with standard values

### Alternatives

1. `true`/`false` (case-insensitive) plus `1`/`0`.
2. Also `yes`/`no`, `y`/`n`, `t`/`f`, `on`/`off`.

### Choice

Reading 1. `true`/`false` is what "standard" means for a type spelled `bool` in a JSON
schema document; widening the set would additionally retype genuine text columns
(a "yes"/"no" survey column) under inference.

### Risk: 25

Author most likely prefers: the same narrow set, possibly extended with `yes`/`no`.

---

## T19: Sorting compares typed values, not emitted text

### Spec Text

> - Single CSV with header row and all rows from inputs, sorted globally by the key(s)

### Alternatives

1. Sort on the values after schema casting (numeric columns order numerically,
   temporal columns chronologically).
2. Sort on the emitted text lexicographically.

### Choice

Reading 1. The null-ordering rule ("Nulls always compare less than non-null values")
presumes typed knowledge of each cell, and schema resolution is described as happening
before output, so the sort operates on cast values. `9` therefore precedes `10` in an
`int` key column.

### Risk: 15

Author most likely prefers: the same; lexicographic-on-text is the fallback only if their
pipeline never materializes typed values.

---

## T20: Behavior when a key column exists in the schema but in none of the inputs

### Spec Text

> - If a key column is not present in resolved schema, that is an error
> - Missing input columns filled with null literal

### Alternatives

1. Not an error: the column is in the resolved schema, every row's value is null, so the
   key contributes nothing and rows keep input order.
2. Error, because no input supplies the column.

### Choice

Reading 1 — the spec makes presence *in the resolved schema* the sole criterion, and an
all-null column is well-defined under the null-ordering rule.

### Risk: 10

Author most likely prefers: the same, since the error condition is stated in terms of the
resolved schema only.

---

## T21: `--infer` when `--schema` is also given

### Spec Text

> 1. **If `--schema` is provided**: JSON file with exact output schema and column order

### Alternatives

1. `--infer` is silently ignored; the explicit schema wins completely.
2. Conflict is an error.

### Choice

Reading 1 ("exact output schema"). No inference happens at all when a schema is supplied.

### Risk: 5

---

## T22: Degenerate inputs (no rows, missing header, zero-byte file)

### Spec Text

> - All inputs are UTF-8, RFC-4180 compliant, with a **header row**
> - Single CSV with header row and all rows from inputs

### Alternatives

1. A file with only a header contributes no rows; a zero-byte file contributes no columns
   and no rows; the output is still written with its header row.
2. Zero-byte input is an error.

### Choice

Reading 1. Emitting a header-only output for an empty merge is the behavior that keeps the
output a valid CSV of the resolved schema.

### Risk: 10

---

## T23: What "ascending lexicographic order" means for mixed-case column names

### Spec Text

> - Column order: ascending lexicographic order of column names

### Alternatives

1. Code-point ordering (`sorted(names)`), so `Zebra` precedes `apple`.
2. Case-insensitive ordering, so `apple` precedes `Zebra`.

### Choice

Code-point ordering — the plain meaning of "lexicographic" and the default of every
language's string sort, including Python's `sorted`.

### Risk: 15

Author most likely prefers: the same; case-insensitive ordering is only plausible if
their fixtures happen to use a case-folding sort.

---

## T24: A `--temp-dir` that does not exist

### Spec Text

> [--temp-dir <PATH>]
> - All intermediate resources must be cleaned up on exit

### Alternatives

1. Require the directory to exist; a missing path is an error (the semantics of
   `tempfile.mkdtemp(dir=...)`).
2. Create the directory tree on demand.

### Choice

Reading 1: validate at startup and fail loudly, so a typo cannot silently send spill
files to the default temp location. Intermediates live in a private subdirectory of the
given path and are removed on exit, success or failure.

### Risk: 10

Author most likely prefers: the same; this path is unlikely to be exercised by fixtures.

---

## T25: A row whose only field is null

### Spec Text

> - Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives

1. Emit a quoted empty field (`""`) when a record consists of a single empty field, so
   the record is distinguishable from a blank line (Python's `csv.writer` behavior under
   `QUOTE_MINIMAL`).
2. Emit a bare empty line.

### Choice

Reading 1 — it round-trips through an RFC-4180 reader, whereas a bare empty line does
not. Multi-column rows are unaffected: empty fields there are written unquoted.

### Risk: 10

Author most likely prefers: the same, since it is what the standard CSV writer emits.
