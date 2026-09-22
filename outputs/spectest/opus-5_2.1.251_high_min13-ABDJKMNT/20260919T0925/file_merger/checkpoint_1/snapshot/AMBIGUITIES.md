# Ambiguities

Numbered record of spec under-specification, the interpretation chosen, and the
risk that the spec author's own implementation reads it differently.

## T1 — Output rendering of `bool` values

### Spec Text
> `bool` includes `1`/`0` along with standard values

> Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first
> Temporal outputs: `date` stays `YYYY-MM-DD`; `timestamp` normalized to UTC with `Z`

### Alternatives
1. Emit Python's native rendering: `True` / `False`.
2. Emit lowercase `true` / `false` (JSON/CSV convention).
3. Emit `1` / `0`, or preserve the original input text verbatim.

### Choice
`True` / `False`. The "Deterministic Dialect Details" section normalizes temporal
output explicitly and says nothing about booleans, which suggests the author never
special-cased bool rendering — in which case a cast Python `bool` handed to
`csv.writer`/`str()` renders as `True`/`False`.

### Risk: 45
Author most likely prefers: lowercase `true`/`false` if they wrote a deliberate
renderer per type.

## T2 — Are empty strings nulls during `strict` inference?

### Spec Text
> `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`
> `loose`: ... empty strings are treated as nulls and don't affect inference

### Alternatives
1. Empty strings are nulls in both modes (the null rule is stated once, under
   `loose`, but describes the tool's general null handling).
2. Only `loose` skips empty strings; under `strict` an empty cell is an observed
   value that fails every non-string parse, so any column with a blank cell becomes
   `string`.

### Choice
Alternative 1. Blank cells are converted to nulls once, at read time, before any
type logic runs — the same conversion that makes "Missing values emitted as the
null literal" work. Under alternative 2 a single blank cell anywhere would collapse
almost every real-world column to `string`, which makes `strict` inference useless
rather than merely stricter.

### Risk: 30
Author most likely prefers: alternative 2 if they implemented the two modes as
separate code paths and only added the null skip to `loose`.

## T3 — What counts as a "conflicting type" in `strict` mode

### Spec Text
> `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`

### Alternatives
1. Resolve one type per file, then require every file's answer to be identical;
   anything else (including `int` in one file and `float` in another) is a conflict
   and yields `string`.
2. Intersect the per-file candidate type sets and take the highest-priority survivor,
   so `int` + `float` widens to `float` and only genuinely disjoint cases yield `string`.

### Choice
Alternative 1. The spec contrasts `strict` with `loose` ("prefer numeric/temporal
types if all non-null observed values parse"), so widening across files is the
behaviour that distinguishes `loose`; if `strict` also widened, the two modes would
be identical for every numeric input.

### Risk: 35
Author most likely prefers: alternative 2 for the specific `int` + `float` pairing
(a single shared "merge types" helper that widens numerics in both modes).

## T4 — Does a date-only value parse as a `timestamp`?

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> `date`: ISO-8601 `YYYY-MM-DD`
> `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output
> if source lacked zone, treat as UTC

### Alternatives
1. Inference: `timestamp` requires a time component, so `2024-07-01` infers as
   `date`. Casting: a schema that declares `timestamp` still accepts `2024-07-01`
   and yields `2024-07-01T00:00:00Z`.
2. `YYYY-MM-DD` is valid ISO-8601 for both, so with `timestamp` outranking `date`
   every date column infers as `timestamp`.
3. Symmetric strictness: a `timestamp` column rejects date-only text entirely
   (cast error).

### Choice
Alternative 1. Under alternative 2 the `date` type is unreachable by inference,
which would make its presence in the priority list pointless. Casting stays lenient
because "if source lacked zone, treat as UTC" shows the author widens incomplete
temporal input rather than rejecting it.

### Risk: 35
Author most likely prefers: alternative 2, if their timestamp parser is a bare
`datetime.fromisoformat` (which accepts date-only input) shared by inference and casting.

## T5 — `0`/`1` columns infer as `bool`

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> `bool` includes `1`/`0` along with standard values

### Alternatives
1. Apply the stated priority literally: a column whose values are all `0`/`1`
   parses as both `bool` and `int`, and `bool` outranks `int`, so it infers `bool`.
2. Treat `1`/`0` as bool only when the column also contains a textual `true`/`false`,
   keeping pure digit columns numeric.

### Choice
Alternative 1. The priority list is explicit and the author placed `bool` above `int`
knowing that `1`/`0` is accepted by both.

### Risk: 30
Author most likely prefers: alternative 2 — inferring `bool` for a column of 0/1
integers surprises people, so their inference may only offer `bool` for textual values.

## T6 — Does `--csv-null-literal` also mark nulls on input?

### Spec Text
> Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives
1. Output only: the literal is how nulls are rendered; on input only empty cells and
   absent columns are null.
2. Both directions: an input cell equal to the literal is read as null (round-trip).

### Choice
Alternative 1. The sentence sits in the **Output** section and describes emission;
the inference rules separately name "empty strings", not "the null literal", as the
input-side null.

### Risk: 30
Author most likely prefers: alternative 2 if they threaded one `null_literal`
value through both reader and writer for symmetry.

## T7 — Do `--csv-quotechar` / `--csv-escapechar` affect the output dialect?

### Spec Text
> Quote character defaults to `"`; escape character defaults to doubling the quote (`""`), overrideable via flags

> Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives
1. Input only — the flags appear under "Fixed CSV assumptions" (which describes
   inputs), and the output dialect is declared deterministic.
2. Both — a single dialect object is built from the flags and reused for the writer.

### Choice
Alternative 1. "Deterministic Dialect Details" states the output quoting rules
unconditionally, so a flag that changed them would contradict it.

### Risk: 35
Author most likely prefers: alternative 2, the least-effort implementation
(one `csv.Dialect` shared by reader and writer).

## T8 — Sort ordering when `keep-string` leaves untyped text in a typed column

### Spec Text
> `keep-string`: emit original text as string
> Nulls always compare less than non-null values, regardless of sort direction

### Alternatives
1. Three ordering classes per key column: null < successfully-typed value <
   kept-string fallback, comparing within a class.
2. Compare every value by its rendered output string.
3. Undefined/crash on mixed types (Python would raise comparing `int` to `str`).

### Choice
Alternative 1. It preserves the spec's stated null rule, keeps typed values in true
type order, and gives a total order without ever comparing values of different
Python types.

### Risk: 40
Author most likely prefers: alternative 2 — sorting on the rendered strings is a
simple way to dodge the mixed-type comparison, and `keep-string` is where it shows.

## T9 — Canonical vs. verbatim rendering of numeric cells

### Spec Text
> Cast every input cell into target type (rules below)
> `int`, `float`, `string`: standard parsing

### Alternatives
1. Render from the cast value: `007` → `7`, `1.50` → `1.5`, an `int`-valued cell in
   a `float` column → `5.0`.
2. Echo the original text whenever the cast succeeded, reserving normalization for
   timestamps (the only case the spec explicitly normalizes).

### Choice
Alternative 1. The spec says every cell is cast into the target type, and the output
column is that type; rendering the cast value is what makes the column type
meaningful in the output.

### Risk: 30
Author most likely prefers: alternative 2 for `float`, where `1.50` → `1.5` is a
visible, easy-to-miss change to the data.

## T10 — Stability under `--desc`

### Spec Text
> Sort must be stable with respect to input appearance for equal keys
> Default order is ascending; `--desc` applies to all keys

### Alternatives
1. A stable descending sort: rows with equal keys stay in input-appearance order.
2. Descending implemented as "sort ascending, then reverse", which reverses ties too.

### Choice
Alternative 1. Stability is stated unconditionally and is the standard meaning of a
stable descending sort.

### Risk: 20
Author most likely prefers: alternative 2 only if they implemented `--desc` with
`list.reverse()`/`reversed()` rather than a reverse comparator.

## T11 — Empty string in a `string`-typed column

### Spec Text
> Missing values emitted as the null literal
> empty strings are treated as nulls

### Alternatives
1. Empty cells are null for every column type, so with `--csv-null-literal NULL` a
   blank cell in a string column emits `NULL`.
2. Blank-to-null applies only to typed columns; a `string` column keeps `""` as a
   real (non-null) empty value.

### Choice
Alternative 1. A single blank-to-null conversion at read time, before type logic,
is the simplest reading and matches the inference rule's wording.

### Risk: 25
Author most likely prefers: alternative 2 if their null check is "value is missing
from the row" rather than "value is empty text".

## T12 — `--schema` argument: file path or inline JSON?

### Spec Text
> `[--schema <SCHEMA_JSON>]`
> **If `--schema` is provided**: JSON file with exact output schema and column order
> `--schema schema.json`

### Alternatives
1. Always a path to a JSON file.
2. Either a path or an inline JSON document.

### Choice
Alternative 2, resolved as: text beginning with `{` is parsed as inline JSON,
anything else is a path. The prose and the example both say "file", so path support
is what is tested; accepting inline JSON costs nothing and covers the
`<SCHEMA_JSON>` placeholder reading.

### Risk: 10
Author most likely prefers: path-only (a superset implementation still passes
path-based fixtures).

## T13 — Exit codes and error reporting

### Spec Text
> `fail`: write error to stderr and exit non-zero
> If a key column is not present in resolved schema, that is an error

### Alternatives
1. Exit `1` for every runtime error (bad schema, unknown key column, cast failure
   under `fail`), with argparse's own `2` for malformed command lines.
2. Distinct codes per error class.

### Choice
Alternative 1; the spec only ever requires "non-zero".

### Risk: 15
Author most likely prefers: the same, since only non-zero is specified — residual
risk is a test asserting a specific code such as `2`.

## T14 — Columns with no non-null observed values

### Spec Text
> infer schema from union of all input headers
> empty strings are treated as nulls and don't affect inference

### Alternatives
1. Fall back to `string` (lowest priority type, nothing observed to argue otherwise).
2. Some other default such as the highest-priority type.

### Choice
Alternative 1: `string`, matching the "otherwise fall back to `string`" rule.

### Risk: 10
Author most likely prefers: the same.

## T15 — Surrounding whitespace in numeric cells

### Spec Text
> `int`, `float`, `string`: standard parsing

### Alternatives
1. "Standard parsing" is the language's own: `int(" 5 ")` succeeds, so ` 5 ` is a
   valid int (and infers as one), while temporal/bool parsing does not strip.
2. Strip whitespace before every parse, uniformly.
3. Reject any cell that is not already trimmed.

### Choice
Alternative 1 — plain `int()`/`float()` on the cell text, no extra trimming logic.

### Risk: 15
Author most likely prefers: the same (identical code), with minor divergence if they
call `.strip()` on every cell first.

## T16 — Duplicate column names in an input header

### Spec Text
> infer schema from union of all input headers

### Alternatives
1. The union is a set of names; a repeated name maps to its first occurrence in that file.
2. Disambiguate or error.

### Choice
Alternative 1 — first occurrence wins, the header union stays a set of distinct names.

### Risk: 15
Author most likely prefers: the same, or last-occurrence-wins if they build a dict
by overwriting.

## T17 — Default `--memory-limit-mb` and how the limit maps to spilling

### Spec Text
> `[--memory-limit-mb <INT>]`
> Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs

### Alternatives
1. Default to 64 MB and treat the limit as a budget for the in-memory run buffer,
   spilling a sorted run to a temp file whenever the estimated buffer size exceeds it.
2. Treat it as a hard cap on total process RSS (enforced via `resource.setrlimit`).

### Choice
Alternative 1. Process-wide RSS enforcement would kill the interpreter on small
limits; the observable requirement is that output is correct regardless of the limit.

### Risk: 5
Author most likely prefers: the same — the flag's effect is not directly observable,
only output correctness under a small value is.
