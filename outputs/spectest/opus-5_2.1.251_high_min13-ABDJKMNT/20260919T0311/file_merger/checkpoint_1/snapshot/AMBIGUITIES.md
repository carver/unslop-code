# Ambiguities

Numbered record of spec under-specification, the interpretation chosen for this
implementation, and the risk that the spec author's own implementation (and the
hidden tests written against it) reads the spec differently.

---

## T1: Type priority makes `bool` outrank `int` during inference

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`

> `bool` includes `1`/`0` along with standard values

### Alternatives
1. Inference walks the priority list and returns the first type that parses every
   observed value, using the same `bool` parser as casting. A column holding only
   `1`/`0` therefore infers as `bool`, because `bool` outranks `int`.
2. The `1`/`0` acceptance is a *casting* concession only (it is written under
   "Casting & Validation"). Inference uses a narrower bool test (`true`/`false`),
   so a `1`/`0` column infers as `int`.

### Choice
Alternative 1. The priority list exists precisely to break ties between types that
both parse the same text, and the only pairs that actually overlap are
`timestamp`/`date` and `bool`/`int`. Reading `bool > int` as meaningful requires
`1`/`0` to be bool-parseable during inference, so a single shared parser table is
used for both inference and casting.

### Risk: 40
Author most likely prefers: a column of bare `1`/`0` values infers as `int`, with
`bool` inference reserved for `true`/`false` spellings.

---

## T2: Date-only values when `timestamp` outranks `date`

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`

> `date`: ISO-8601 `YYYY-MM-DD`
> `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output

### Alternatives
1. `YYYY-MM-DD` is valid ISO-8601, so it parses as a `timestamp` too; priority then
   makes every pure-date column infer as `timestamp` and render as
   `2024-07-01T00:00:00Z`. The `date` type becomes unreachable by inference.
2. Inference only proposes `timestamp` when at least one observed value carries a
   time component; pure `YYYY-MM-DD` columns infer as `date`. Explicit
   `type: timestamp` in a schema still accepts a date-only cell (midnight UTC).

### Choice
Alternative 2. Reading 1 makes the `date` inference type dead code, which cannot be
the intent of listing it as a valid inferred type. Requiring a time component only
for the *inference* proposal keeps casting lenient while keeping `date` reachable.

### Risk: 30
Author most likely prefers: alternative 2 as well, but an implementation built on a
bare `datetime.fromisoformat` probe would silently produce alternative 1.

---

## T3: Empty cells during `strict` inference

### Spec Text
> `strict` (default): infer types based on observed values; columns with conflicting
> types across files fall back to `string`
> `loose`: prefer numeric/temporal types if all non-null observed values parse;
> otherwise fall back to `string`; empty strings are treated as nulls and don't
> affect inference

### Alternatives
1. The null-skipping clause is called out only for `loose` because it is the
   difference between the modes: under `strict` an empty cell is an observed value
   that only parses as `string`, so any column with a blank cell falls back to
   `string`.
2. Empty cells are nulls everywhere; the clause is merely restated under `loose`.
   The modes then differ only in the per-file-conflict rule.

### Choice
Alternative 1. `strict` and `loose` need an observable difference beyond the
conflict rule, and the clause is deliberately attached to one mode only. So under
`strict`, blanks force `string`; under `loose`, blanks are ignored. Both modes also
apply the per-file conflict rule (`strict` resolves a type per file and falls back
to `string` when files disagree; `loose` pools all non-null values across files).

### Risk: 45
Author most likely prefers: alternative 2 — blanks ignored in both modes, with
`strict` differing only by resolving types per-file and demanding agreement.

---

## T4: Rendering of cast values

### Spec Text
> Cast every input cell into target type (rules below)

> `int`, `float`, `string`: standard parsing
> `bool` includes `1`/`0` along with standard values

### Alternatives
1. A cast cell is re-rendered from the parsed value: `007` -> `7`, `1.50` -> `1.5`,
   `1`/`TRUE` -> `true`.
2. A cast cell that parses successfully is echoed verbatim; casting only validates
   and only temporal types are reformatted (those are the only ones the spec gives
   an output form for).

### Alternatives for the bool spelling specifically: `true`/`false`, `True`/`False`,
or `1`/`0`.

### Choice
Alternative 1 with lowercase `true`/`false`. "Cast every input cell into target
type" describes a conversion, not a validation, and the spec's insistence on a
deterministic dialect points at canonical rendering. Floats render via Python's
shortest round-trip repr (`2.0`, `1.5`, `1e+30`); ints render without padding or
`+`; bools render lowercase, matching JSON/SQL convention and the spec's own
lowercase `bool` type name.

### Risk: 45
Author most likely prefers: `True`/`False` (Python's `str(bool)`) for the bool
spelling, which is what an implementation that formats with `str()` emits.

---

## T5: Does casting apply when the schema was inferred?

### Spec Text
> **If `--schema` is provided**: JSON file with exact output schema and column
> order: ... Cast every input cell into target type (rules below)

> **If `--schema` not provided**: infer schema from union of all input headers

### Alternatives
1. Casting is described under the `--schema` branch only, so inferred runs pass
   cell text through unchanged (inference still drives sort comparisons).
2. The resolved schema is a schema either way; cells are cast and rendered
   identically in both branches.

### Choice
Alternative 2. The spec speaks of a single "resolved schema" downstream ("Columns in
output header must match the resolved schema order", "If a key column is not present
in resolved schema"), and `--on-type-error` is documented globally rather than under
the `--schema` branch, which only makes sense if inferred runs can hit cast errors.

### Risk: 30
Author most likely prefers: alternative 2, but an implementation that never
normalizes inferred columns would emit `2024-07-01T12:00:00+00:00` untouched.

---

## T6: Is `--csv-null-literal` recognised on input?

### Spec Text
> Missing values emitted as the null literal (default empty string; override with
> `--csv-null-literal`)

> `[--csv-null-literal <STRING>]`

### Alternatives
1. Output-only: it is only ever described as what gets *emitted*. On input, only an
   empty cell (or an absent column) is null.
2. Symmetric: a cell whose text equals the null literal is read as null, so the tool
   round-trips its own output.

### Choice
Alternative 2, plus empty string always counting as null on input. Round-tripping is
the behaviour a user setting `--csv-null-literal NULL` expects, and for `string`
columns the two readings produce identical output anyway (the literal is read as
null and re-emitted as the literal); they differ only for typed columns, where
reading 1 would route the literal through `--on-type-error`.

### Risk: 35
Author most likely prefers: output-only, with the literal in a typed column treated
as a cast failure.

---

## T7: Do `--csv-quotechar` / `--csv-escapechar` affect the output dialect?

### Spec Text
> Quote character defaults to `"`; escape character defaults to doubling the quote
> (`""`), overrideable via flags

> **Deterministic Dialect Details**
> Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings;
> header row first

### Alternatives
1. The flags configure parsing only; output is always `,` + `"` + doubling, exactly
   as the "Deterministic Dialect Details" section states.
2. The flags configure both ends, so the tool emits with the caller's quote/escape
   characters.

### Choice
Alternative 1. The output section is unconditional and titled "Deterministic", while
the flags live under "Fixed CSV assumptions", which describes the *inputs*. A file
quoted with `'` therefore re-emits quoted with `"`.

### Risk: 35
Author most likely prefers: alternative 2 for `--csv-quotechar` (a single dialect
object shared by reader and writer), which is the shortest implementation.

---

## T8: Where `keep-string` fallbacks sort inside a typed key column

### Spec Text
> `keep-string`: emit original text as string
> Nulls always compare less than non-null values, regardless of sort direction

### Alternatives
1. Uncomparable leftovers sort after every well-typed value of the column (a third
   rank: null < typed < kept-string), ascending.
2. Everything in the column degrades to string comparison once any cell is kept.
3. Kept strings sort with the nulls.

### Choice
Alternative 1. The spec gives an explicit rank only for nulls, so the remaining
values keep their typed ordering (`10` after `9`, not before it), and the
uncomparable residue is appended in a deterministic, stable position. Reading 2
would let one bad cell silently reorder every good row.

### Risk: 40
Author most likely prefers: a comparison that falls back to string ordering of the
raw text within the affected column.

---

## T9: Exit codes and error reporting

### Spec Text
> `fail`: write error to stderr and exit non-zero
> If a key column is not present in resolved schema, that is an error

### Alternatives
1. A single non-zero code (e.g. `1`) for every operational failure.
2. Distinct codes per failure class.

### Choice
Alternative 1: operational failures (cast failure under `fail`, unknown key column,
unreadable input, bad schema JSON, invalid type name) print `error: ...` to stderr
and exit `1`. Malformed command lines exit `2` via argparse's default. Only
"non-zero" is testable from the spec.

### Risk: 15
Author most likely prefers: also non-zero, possibly `2`, for cast failures.

---

## T10: `--schema <SCHEMA_JSON>` — path or inline JSON?

### Spec Text
> `[--schema <SCHEMA_JSON>]`
> **If `--schema` is provided**: JSON file with exact output schema and column order

### Alternatives
1. Strictly a filesystem path.
2. Either a path or an inline JSON document, since the placeholder names the JSON
   rather than a file.

### Choice
Alternative 2, resolved unambiguously: a value whose first non-space character is
`{` is parsed inline, anything else is opened as a file. The prose ("JSON file") is
honoured and the placeholder spelling is tolerated.

### Risk: 10
Author most likely prefers: path only — but every path-based test also passes here.

---

## T11: Default `--memory-limit-mb`

### Spec Text
> `[--memory-limit-mb <INT>]`
> Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large
> inputs

### Alternatives
1. Unbounded when omitted (sort entirely in memory).
2. A finite default; `64` is the figure the spec names.

### Choice
Alternative 2 with a default of `64`. The spill threshold is a budget for buffered
row data, not a hard RSS cap; a run under the limit never touches the temp
directory, so behaviour is identical either way and only spilling differs.

### Risk: 15
Author most likely prefers: same observable output regardless, since the flag only
changes spill behaviour.

---

## T12: Fractional seconds in normalized timestamps

### Spec Text
> `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`); if source
> lacked zone, treat as UTC

### Alternatives
1. Truncate to whole seconds: `...T12:00:00.500Z` -> `2024-07-01T12:00:00Z`.
2. Preserve the fractional part: `2024-07-01T12:00:00.500000Z`.

### Choice
Alternative 2. "Normalize" is specified as a zone/suffix operation, not a precision
change; discarding data the input carried would be lossy. Seconds are always
emitted, so the spec's own example renders identically under either reading.

### Risk: 40
Author most likely prefers: truncation to seconds, which is what a
`strftime('%Y-%m-%dT%H:%M:%SZ')` implementation produces.

---

## T13: Rows whose field count differs from their header

### Spec Text
> All inputs are UTF-8, RFC-4180 compliant, with a **header row**

### Alternatives
1. Short/long rows are a fatal error.
2. Missing trailing fields are nulls; surplus fields are dropped, mirroring the
   documented handling of missing and extra *columns*.

### Choice
Alternative 2. The spec already says missing columns become nulls and extra columns
are ignored, so applying the same rule inside a row is consistent, and "RFC-4180
compliant" suggests ragged rows simply will not be tested.

### Risk: 20
Author most likely prefers: alternative 2, or an untested crash.

---

## T14: Inferred type for a column with no observed values

### Spec Text
> infer schema from union of all input headers

### Alternatives
1. `string`.
2. The top-priority type (`timestamp`), since "all values parse" is vacuously true.

### Choice
Alternative 1. A column with nothing but nulls (or no data rows at all) carries no
evidence, and `string` is the spec's stated fallback for every unresolved case.

### Risk: 20
Author most likely prefers: `string` as well, though a vacuous-truth loop yields
`timestamp`.

---

## T15: Which literals `bool` accepts

### Spec Text
> `bool` includes `1`/`0` along with standard values

### Alternatives
1. `true`/`false` (case-insensitive) plus `1`/`0`.
2. Also `yes`/`no`, `t`/`f`, `y`/`n`, `on`/`off`.

### Choice
Alternative 1. "Standard values" for a CSV boolean means the `true`/`false` pair;
accepting `yes`/`no` would also make ordinary English text parse as bool during
inference, which is clearly undesirable. Matching is case-insensitive
(`TRUE`, `True`, `true`).

### Risk: 25
Author most likely prefers: alternative 1, with a possible extra allowance for
`yes`/`no`.

---

## T16: Stability under `--desc`

### Spec Text
> Sort must be stable with respect to input appearance for equal keys
> Default order is ascending; `--desc` applies to all keys

### Alternatives
1. Stability is a property of the sort in both directions: rows with equal keys keep
   input order whether ascending or descending.
2. Descending is the ascending result reversed, so tied rows appear in reverse input
   order.

### Choice
Alternative 1. The stability requirement is stated unconditionally and separately
from the direction flag. Implemented by inverting only the key comparison while the
input sequence number always breaks ties ascending.

### Risk: 25
Author most likely prefers: alternative 1 (Python's `sorted(reverse=True)` is stable
in exactly this way), but an implementation that reverses a sorted list gives 2.

---

## T17: Ordering of inferred columns

### Spec Text
> Column order: ascending lexicographic order of column names

### Alternatives
1. Python's default codepoint ordering, where all uppercase letters precede all
   lowercase (`Zebra` < `apple`).
2. Case-insensitive / locale-aware collation (`apple` < `Zebra`).

### Choice
Alternative 1. "Lexicographic" is the literal codepoint reading and is what a plain
`sorted()` produces; locale collation would be non-deterministic across machines,
which conflicts with the spec's determinism goal.

### Risk: 15
Author most likely prefers: alternative 1 (plain `sorted()`).

---

## T18: Precedence of `--schema` over `--infer`

### Spec Text
> **If `--schema` is provided**: JSON file with exact output schema and column order
> **If `--schema` not provided**: infer schema from union of all input headers
> Inference mode (`--infer`)

### Alternatives
1. Passing both is an error.
2. `--schema` wins and `--infer` is ignored.

### Choice
Alternative 2. The two branches are mutually exclusive by construction ("if not
provided"), so `--infer` is simply inert when a schema is supplied; rejecting the
combination would break the common case of a wrapper script that always passes
`--infer`.

### Risk: 10
Author most likely prefers: alternative 2.

---

## T19: Whether `--key` may name a column absent from the inferred union

### Spec Text
> If a key column is not present in resolved schema, that is an error

### Alternatives
1. Only checked against an explicit `--schema`.
2. Checked against the resolved schema in both branches, i.e. a key naming a column
   that appears in no input header is an error.

### Choice
Alternative 2. The spec says "resolved schema", a term that covers both branches;
sorting by a column that exists nowhere would otherwise silently emit an
all-null-keyed passthrough.

### Risk: 10
Author most likely prefers: alternative 2.
