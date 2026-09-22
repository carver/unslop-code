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

### Annotation (checkpoint 2)
Partially resolved. Checkpoint 2 names exit codes `2`, `3`, `5` and `6` for
specific failures, so the single-code choice above no longer holds. The full
table now in use is recorded in T20; the codes this entry covers are `3` for a
key column missing from the resolved schema and `4` for a cast failure under
`--on-type-error fail` (still only constrained to be non-zero).

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

---

## T20: The full exit-code table

### Spec Text
> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet;
> otherwise error 2

> Mismatch is error 5

> Keys must exist in resolved schema (error 3 otherwise)

> nested fields trigger error 6

> Exact exit codes and stderr message shape as specified

### Alternatives
1. Only the four named codes exist; every other failure keeps checkpoint 1's
   single non-zero code.
2. The named codes are samples from a contiguous table, and the unnamed classes
   (`1`, `4`) fill the gaps with the obvious remaining failure kinds.

### Choice
Alternative 2, with this table:

| code | meaning |
| --- | --- |
| 0 | success |
| 1 | I/O failure (unreadable input, undeletable temp file, ...) |
| 2 | bad command line, or an input whose format cannot be determined |
| 3 | schema resolution failure: unusable `--schema`, unknown type name, key column absent from the resolved schema |
| 4 | cast failure under `--on-type-error fail` |
| 5 | source data does not match its declared format: compression mismatch, literal tab in a TSV field, unparseable JSONL line |
| 6 | nested structure in a JSONL object or a Parquet schema, with no `--schema` to declare it |

`2` doubles as argparse's own usage code, which is where a malformed command line
already lands, and "cannot determine the format of this input" is the same kind of
failure — the invocation does not describe a readable run.

**Annotation (nested-types checkpoint).** The table survives, and the new checkpoint
confirms it by spelling two of its rows out: `ERR 4 cannot cast ...` and `ERR 3 key
column ... does not resolve to a primitive`. It also settles the message *shape*,
which checkpoint 1 left open: every failure is now reported as `ERR <code> <text>`
rather than the `error: <text>` of the earlier checkpoints. See T62.

### Risk: 35
Author most likely prefers: this table for the four named codes (they are quoted
verbatim from the spec) but some other assignment for cast failures — `1` and `4`
are both plausible, and a table that reserves `1` for "generic error" would put
usage errors on `2` and cast failures on `4` exactly as here.

---

## T21: Source precedence under `--schema-strategy=authoritative`

### Spec Text
> `--schema-strategy=authoritative` (default): prefer typed sources in precedence
> order

### Alternatives
1. Precedence is by *format*, ranked by how much type information the format
   carries: Parquet (a declared schema) > JSONL (per-value JSON types) > CSV/TSV
   (no types at all). The highest-ranked format that contains the column decides.
2. Precedence is command-line order: the first input listed that has the column
   wins, "typed" being only a tie-break hint.
3. Precedence is command-line order restricted to typed inputs, falling back to
   text inputs only when no typed input has the column.

### Choice
Alternative 1. "Prefer typed sources" names a property of the format, not of the
argument position, and the phrase "in precedence order" then has to mean an order
over those formats. Parquet outranks JSONL because a Parquet column's type is
declared once in the file footer, while a JSONL column's type is only whatever its
values happened to be.

When several files share the winning rank and disagree, the `--infer` mode settles
it exactly as in checkpoint 1: `strict` falls back to `string`, `loose` pools the
evidence. That keeps an all-CSV run byte-identical to checkpoint 1, which the
default strategy has to do.

### Risk: 55
Author most likely prefers: the same Parquet > JSONL > CSV/TSV ranking, but with
first-listed-input order breaking ties inside a rank instead of falling back to
`string`.

---

## T22: What "majority of files support" means for `consensus`

### Spec Text
> `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives
1. Each file votes with the single type it resolves to on its own; the type with
   the most votes wins (a plurality, since a strict majority often does not exist).
2. Each file votes for *every* type all of its values could be cast to; the type
   supported by the most files wins. `string` is supported by every file, so this
   reading makes `string` win almost always — unless it is read as "the
   highest-priority type supported by a majority", which then behaves like a
   cross-file `union`.

### Choice
Alternative 1, with ties broken by the checkpoint 1 type priority
(`timestamp` > `date` > `bool` > `int` > `float` > `string`). Reading 2 taken
literally elects `string` for every column, which would make the option useless.
A plurality is used rather than a strict majority so that the strategy always
returns something without an extra fallback rule.

### Risk: 50
Author most likely prefers: plurality of per-file types as here, but with the tie
broken by widening the tied types (so `int` vs `float` at 1–1 gives `float`) rather
than by the priority list (which gives `int`).

---

## T23: The widening lattice for `--schema-strategy=union`

### Spec Text
> `--schema-strategy=union`: choose simplest common type that can hold all observed
> values

### Alternatives
1. A minimal lattice over the six types: `int`+`float` -> `float`,
   `date`+`timestamp` -> `timestamp`, every other mixture -> `string`.
2. A lattice that also widens `bool` into the numeric tower (`bool`+`int` ->
   `int`), since `1`/`0` are accepted bool spellings.
3. Re-derive the type from the pooled values of every file, i.e. make `union`
   behave like `--infer loose` regardless of the `--infer` flag.

### Choice
Alternative 1. `bool` is excluded from the numeric tower because a `bool` column
that spells its values `true`/`false` cannot be held by `int` at all — casting
would null every row — so `int` is not a type that "can hold all observed values".
Reading 3 is rejected because it would make `--infer` inert, and the two flags are
documented independently.

### Risk: 45
Author most likely prefers: alternative 1 as well, but an implementation that
widens by walking the priority list upward would produce alternative 2.

---

## T24: How `--infer` and `--schema-strategy` interact

### Spec Text
> Type inference per `--infer` mode (strict or loose)
> **Schema disagreement strategy** when inputs have conflicting types for same
> column

### Alternatives
1. `--infer` decides how one file's own values are typed (does a blank count as an
   observation?); `--schema-strategy` decides how the per-file answers are
   reconciled. The checkpoint 1 cross-file rules (`strict` -> `string` on
   disagreement, `loose` -> pool values) survive only inside `authoritative`.
2. `--schema-strategy` fully replaces the checkpoint 1 cross-file rules, so
   `--infer strict` with two disagreeing CSVs no longer yields `string` under the
   default strategy.
3. The two are independent pipelines and `--schema-strategy` only applies when the
   inputs are of different formats.

### Choice
Alternative 1. The default strategy must reproduce checkpoint 1 on a homogeneous
CSV run — no checkpoint 2 sentence announces a behaviour change for existing
invocations — and `authoritative` degenerates to "all files are the same rank"
there, so the checkpoint 1 rule is exactly what is left to apply. `consensus` and
`union` are new opt-in rules and override it.

### Risk: 40
Author most likely prefers: alternative 1 for the `strict`/`loose` blank handling,
but may well apply `consensus`/`union` only to the cross-*format* disagreement and
keep the checkpoint 1 rule for same-format files.

---

## T25: What counts as a compression "mismatch"

### Spec Text
> `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> Mismatch is error 5

### Alternatives
1. A mismatch is between the *declared* compression and the actual bytes: forcing
   `gzip` on a plain file, or forcing `none` on a file that starts with the gzip
   magic `1f 8b`.
2. A mismatch is between the flag and the *file name*: `--compression=none` on
   `data.csv.gz`, regardless of content.
3. Only the first half is checked — forcing `gzip` on a plain file errors, while
   forcing `none` on gzip bytes is honoured literally and produces garbage.

### Choice
Alternative 1. The magic bytes are what the detection rules elsewhere in the spec
appeal to, and reading 3 asks the tool to knowingly parse binary as CSV. Both
directions are checked before any row is read.

### Risk: 30
Author most likely prefers: alternative 1, though an implementation that only wraps
in `gzip.open` when asked gets reading 3 for free.

---

## T26: When an extension counts as "ambiguous"

### Spec Text
> `.csv` -> csv, `.tsv` -> tsv, `.jsonl`/`.ndjson` -> jsonl, `.parquet` -> parquet
> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet;
> otherwise error 2

### Alternatives
1. "Ambiguous" means the extension (after stripping a trailing `.gz`) is not one of
   the five listed suffixes — including the no-extension case. A recognised
   extension is trusted without sniffing.
2. Every file is sniffed and the magic bytes override the extension, so a Parquet
   file named `.csv` is read as Parquet.
3. "Ambiguous" means only a genuinely shared extension such as `.txt` or `.dat`,
   and a file with no extension at all is an immediate error 2.

### Choice
Alternative 1. It is the only reading under which the sentence has work to do for
every unnamed extension, and trusting a recognised extension keeps detection from
depending on the first bytes of text files. `data.txt` holding `PAR1...` is read as
Parquet; `data.txt` holding CSV text is error 2.

### Risk: 30
Author most likely prefers: alternative 1, with a possible extra allowance that a
recognised extension is also overridden by Parquet magic bytes (alternative 2).

---

## T27: Detecting a literal tab inside a TSV field

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line
> endings; literal tabs inside field not allowed (error 5)

### Alternatives
1. Undetectable in principle, so the sentence is only a statement of the input
   contract and nothing is checked; a row that splits into more fields than the
   header simply has its surplus dropped.
2. The observable symptom is a data row with more fields than the header, and that
   is what error 5 reports.

### Choice
Alternative 2. The spec attaches a specific exit code to the condition, so it has
to be detectable, and "more cells than there are columns" is the only evidence a
tab-delimited reader can ever have. Rows with *fewer* fields than the header stay
non-fatal (missing cells become nulls, as in T13), since only the extra-tab case is
called out.

### Risk: 35
Author most likely prefers: alternative 2, but may also reject short rows as
malformed rather than null-filling them.

---

## T28: JSONL lines that are not flat objects

### Spec Text
> **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects
> as values); `null` permitted; keys case-sensitive; blank/whitespace lines ignored
> Flat-only enforcement for JSONL/Parquet; nested structures trigger error 6

### Alternatives
1. Three separate failures: unparseable JSON is malformed input (error 5), a line
   whose top-level value is not an object violates "one JSON object per line"
   (error 5), and a *value* that is an array or object is the nested case
   (error 6).
2. Anything that is not a flat object is a flatness violation, so a top-level array
   and an unparseable line both give error 6.

### Choice
Alternative 1. Error 6 is introduced specifically as the nested-structure code, and
a syntax error is not a nested structure; grouping both under one code would lose
the distinction the spec just drew. A top-level array is counted as a format
violation (error 5) rather than a nested value, because the failing rule is "one
JSON object per line".

### Risk: 45
Author most likely prefers: error 6 for a top-level array (it is, literally, an
array where an object was expected) while agreeing on error 5 for a syntax error.

**Annotation (nested-types checkpoint).** Flat-only enforcement is now conditional:
error 6 is raised only when no `--schema` was given ("Without `--schema`, nested
inputs not allowed (error 6)"). With a schema, a nested value is read and cast
against the declared type, and a nested value under a *flat* declared type is a cast
failure rather than error 6. The split of this entry (syntax error 5, nesting 6) is
unchanged.

---

## T29: How typed values are cast to the target type

### Spec Text
> JSONL values come typed (string/number/bool/null)
> Parquet values come typed
> Apply target output schema cast rules to every cell

### Alternatives
1. A typed value is rendered to its canonical text and then run through the same
   parser a CSV cell would use. One cast path, so a JSON `1` and a CSV `1` behave
   identically in every column type.
2. Typed values get their own conversion matrix (Python `int(value)`,
   `float(value)`, `bool(value)`, ...), which is more permissive: `1.7` into an
   `int` column truncates to `1`, a non-empty string into a `bool` column is
   `true`.

### Choice
Alternative 1. "Apply target output schema cast rules to every cell" says the rules
are the schema's, not the source's, and the spec's determinism goal is much better
served by mixed sources that cannot disagree about the same value. So `1.7` into an
`int` column is a cast failure routed through `--on-type-error`, not a silent
truncation.

### Risk: 30
Author most likely prefers: alternative 1, but with Python-level coercion for the
numeric pair specifically (a JSON float landing in an `int` column).

---

## T30: "prefer `int` if integer and within range"

### Spec Text
> For JSONL numbers, prefer `int` if integer and within range; otherwise `float`

### Alternatives
1. A JSON number is normalised at read time: a float whose value is integral and
   fits a signed 64-bit integer becomes a Python `int`, so `1.0` and `1` are the
   same cell. "Within range" is the int64 range, the range a Parquet or SQL
   integer column has.
2. "Within range" means Python's unbounded `int`, so the clause only excludes
   non-integral numbers and `1e400`.
3. The clause is only about *inference* (which type the column gets) and does not
   change the value, so `1.0` still renders as `1.0` in a `float` column.

### Choice
Alternative 1. Normalising the value makes inference and casting agree by
construction: a column of `1.0`, `2.0` infers as `int` under this clause, and a
reading that left the value alone would then fail to cast its own inferred type.
The int64 bound is the only "range" a JSON number can meaningfully exceed, since
Python integers do not overflow.

### Risk: 40
Author most likely prefers: alternative 1 with an unbounded range (alternative 2's
bound), since a huge integer literal in JSON has no reason to demote to `float` in
a Python implementation.

---

## T31: Inferring a type from a typed source

### Spec Text
> JSONL values come typed (string/number/bool/null)
> Column set: union of all encountered field names
> Type inference per `--infer` mode (strict or loose)

### Alternatives
1. A typed source reports the types it declares: a JSONL string field is `string`
   even if every value spells a number, and a Parquet column's type comes from the
   file footer without reading a single row.
2. Typed sources are sniffed like CSV: the value is rendered to text and matched
   against the type priority list, so a JSONL `"123"` infers as `int`.

### Choice
Alternative 1. The whole point of `authoritative` preferring "typed sources" is
that those sources already know their types; sniffing them would discard exactly
the information the strategy is built to prefer. It also means a Parquet input
costs one footer read during schema resolution instead of a full scan, which is
what "don't load entire Parquet files" asks for.

### Risk: 25
Author most likely prefers: alternative 1.

---

## T32: Mapping Parquet physical types onto the six schema types

### Spec Text
> **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger
> error 6
> Parquet values come typed

### Alternatives
1. Map each Arrow type onto its nearest schema type — every integer width to `int`,
   every float width to `float`, `bool` to `bool`, `date32`/`date64` to `date`,
   `timestamp` to `timestamp`, and everything else (`string`, `binary`, `decimal`,
   `time`, ...) to `string`.
2. As above, but decimals map to `float` since they are numbers.
3. Any type outside the six is an error.

### Choice
Alternative 1. `string` is the spec's universal fallback everywhere else, so an
unmapped physical type lands there rather than failing a run. Decimals stay
`string` to avoid a lossy binary-float conversion the spec never asks for; a user
who wants them numeric can say so with `--schema`. Binary columns are decoded as
UTF-8, matching the spec's "all inputs are UTF-8" assumption.

### Risk: 25
Author most likely prefers: alternative 1, with decimal-to-`float` (alternative 2)
as the plausible variant.

**Annotation (nested-types checkpoint).** Still the mapping used for *inference*.
Arrow struct/list/map columns are no longer rejected outright: with a `--schema`
declaring a compatible nested type they are read and cast recursively, and only a
run without `--schema` still refuses them (error 6).

---

## T33: Missing values from typed sources

### Spec Text
> If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing ->
> emit null literal

### Alternatives
1. The sentence is exhaustive per format: for a typed source only JSON/Parquet
   `null` is missing, so a JSONL empty string is a real empty string and a JSONL
   value equal to `--csv-null-literal` is real text.
2. T6's symmetric null-literal reading extends to typed sources, so a JSONL string
   equal to the null literal is also missing.

### Choice
Alternative 1. The spec draws the per-format distinction explicitly in one
sentence, and a typed source has a real `null` available, so a string that merely
*looks* like the CSV null spelling carries no such intent. The flag is named
`--csv-null-literal`, which is a further hint that it describes the CSV surface
syntax.

### Risk: 25
Author most likely prefers: alternative 1, though an implementation with one shared
`is_null(text)` helper would get alternative 2.

---

## T34: Whether an absent JSONL key differs from an explicit `null`

### Spec Text
> Column set: union of all encountered field names
> missing columns filled with null literal

### Alternatives
1. Identical: a key absent from one line and a key present with value `null` both
   produce the null literal.
2. An absent key is a hard error because the object does not match the column set.

### Choice
Alternative 1. JSONL objects are explicitly allowed to be heterogeneous (the column
set is the *union* of field names, which only matters if lines differ), and the
schema branch already says missing columns are filled with the null literal.

### Risk: 10
Author most likely prefers: alternative 1.

---

## T35: `--parquet-row-group-bytes` when omitted

### Spec Text
> `--parquet-row-group-bytes` is advisory for batch sizing

### Alternatives
1. There is a fixed default byte budget per batch.
2. Omitting the flag leaves the Parquet reader's own default batch size in place.

### Choice
Alternative 2. The flag is declared "advisory", so it can only influence batch
sizing, never output; with no advice given, the reader's default stands. When a
value is supplied it is divided by the average row size recorded in the file's
metadata to pick a row count. No output can distinguish the readings — only peak
memory and batch count can.

### Risk: 5
Author most likely prefers: any of these; the spec makes the flag unobservable.

---

## T36: Atomic output writes

### Spec Text
> `--output -` writes to stdout; otherwise write atomically

### Alternatives
1. "Atomically" means the destination path never holds a partial file: write to a
   temporary file in the destination directory, then `os.replace` it into place.
2. It only means the file is opened late, after every input has been read
   successfully (checkpoint 1's behaviour).

### Choice
Alternative 1, keeping the late open as well. `os.replace` on the same filesystem
is the standard meaning of an atomic file write, and a failure mid-write (a full
disk, a cast error under `fail` while streaming out) then leaves any previous file
at that path untouched rather than truncated.

### Risk: 15
Author most likely prefers: alternative 1; the only observable difference is what
the destination holds after a failed run.

---

## T37: What happens to an output directory that already has contents

### Spec Text
> Create directory if doesn't exist

> Perform atomic write by creating sibling temp directory and renaming on success

### Alternatives
1. The destination ends up holding exactly the tree this run produced: the staged
   directory is renamed into place and whatever was there before is discarded, so a
   `part-00007.csv` left by a larger earlier run cannot linger.
2. The staged tree is merged into the existing directory file by file, so unrelated
   (or stale) files under `--output` survive the run.

### Choice
Alternative 1. "Renaming on success" describes moving one directory onto another,
not copying entries into it; the result of a rename is that the destination *is*
the staged tree. It also keeps the determinism checklist honest — rereading the
output directory after a run always yields the rows that were just written, with no
survivors from a previous partitioning of the same data.

### Risk: 30
Author most likely prefers: alternative 1, but an implementation that only renames
when the destination is absent (and otherwise writes entries in) would keep stale
files, which a fixture that runs the tool twice into one directory would catch.

---

## T38: Exit code for `--output -` together with a partitioning flag

### Spec Text
> When any partitioning flag provided: `--output` must be directory path (not `-`)

### Alternatives
1. It is a command-line contradiction, reported like every other malformed
   invocation: argparse-style usage error on stderr, exit code 2.
2. It is a runtime output error with its own code (for example 1), since the
   combination is only invalid once the flags are read together.

### Choice
Alternative 1. The rule constrains the *arguments*, not the data, and checkpoint 1
already reports every argument-level contradiction with exit 2 (`EXIT_USAGE`);
splitting this one out would make two shapes of the same kind of failure.

### Risk: 20
Author most likely prefers: alternative 1, exit 2.

---

## T39: Whether partition columns stay in the part files

### Spec Text
> Every output CSV includes header row in resolved schema column order

> Each file contains header row (resolved schema header)

### Alternatives
1. Part files carry the full resolved schema, partition columns included, so the
   value appears both in the directory name and in every row.
2. Hive convention: the partition columns are projected out of the files because the
   directory names already carry them, leaving a narrower header.

### Choice
Alternative 1. The spec names the *resolved schema* header twice and never mentions
dropping columns; reading 2 would also make the part files inconsistent with the
unpartitioned output of the same command, and would leave a `--partition-by` of every
column producing headerless-in-practice files with no columns at all.

### Risk: 25
Author most likely prefers: alternative 1; readers coming from Hive/Spark habits are
the main reason to expect 2.

---

## T40: Directory output when the merged stream has no rows

### Spec Text
> Within each partition directory, write CSV files named sequentially: `part-00000.csv`, `part-00001.csv`, … (zero-padded width 5)

> `--max-rows-per-file <INT>`: cut output into files with at most INT data rows each (header not counted)

### Alternatives
1. With `--partition-by`, no rows means no unique combinations, so no directories are
   created — but the (empty) `--output` directory itself still exists. With sharding
   only, the output root is the single destination and gets one `part-00000.csv`
   holding just the header, mirroring the single-file mode's header-only output.
2. Nothing at all is written in either case: with no rows there is no part file.
3. A header-only `part-00000.csv` is created for every case, which for
   `--partition-by` is impossible (there is no partition value to name a directory
   with), so it would land in the output root.

### Choice
Alternative 1. Checkpoint 1 established that a zero-row merge still emits the header,
and the sharded stream is the same stream written to a directory instead of a file,
so the header belongs somewhere. Under `--partition-by` there is no directory a
header could belong to, so nothing is emitted.

### Risk: 45
Author most likely prefers: alternative 2 for the sharding-only case — an
implementation that opens a part file lazily on the first row writes no file at all
for an empty stream.

---

## T41: Exact form of the percent-encoding

### Spec Text
> Apply percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`

### Alternatives
1. Upper-case hex digits (`%C3%A9`, `%2F`), applied to both sides of a segment, so a
   column name with an odd character is escaped too. `=` (`%3D`) and `%` (`%25`) are
   outside the unreserved set and are therefore escaped, which keeps the
   `col=val` split unambiguous.
2. Lower-case hex digits (`%c3%a9`), as `urllib.parse.quote` would produce if asked
   for them.
3. Only the *value* is encoded; the column name is written verbatim.

### Choice
Alternative 1. Both examples in the spec (`%20`, `%2F`) use upper-case hex, which is
also what `urllib.parse.quote` emits by default. Encoding the column name costs
nothing for ordinary identifiers and removes the only other way a `/` or `=` could
reach a path.

### Risk: 20
Author most likely prefers: alternative 1 for values; a column name containing a
character outside the safe set is the piece most likely to differ (and least likely
to be tested).

---

## T42: What "single row alone exceeds INT" includes

### Spec Text
> `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file (including header and line endings) is ≤ INT
>   - Exception: if single row alone exceeds INT, place that row in file by itself (allowed to exceed limit)

### Alternatives
1. The exception fires whenever the current file has no data rows yet: the row is
   written after the mandatory header, so the file is `header + row` and may exceed
   INT by the header's size as well.
2. The exception is only about the row's own bytes, and a row that fits INT on its
   own but not alongside the header should still be written headerless, or dropped.

### Choice
Alternative 1. Every part file must carry the header, so "a file by itself" is a
header plus that row; testing "would this file, empty of rows, still overflow?" is the
only rule that terminates. An INT smaller than the header alone therefore yields one
row per file rather than an endless run of empty files.

### Risk: 15
Author most likely prefers: alternative 1; the observable difference is only for
limits near the header size.

---

## T43: Which partition values count as null

### Spec Text
> Null (missing) partition values use literal `_null`

### Alternatives
1. Whatever the tool already treats as null becomes `_null`: a column missing from
   that input file, an empty cell, a cell spelled as `--csv-null-literal`, and a
   JSON `null`. The data cell in the row still renders as the null literal.
2. Only a *missing* column is `_null`, while an empty cell produces the empty segment
   `col=`.

### Choice
Alternative 1. The parenthesis "(missing)" glosses null rather than narrowing it, and
the tool has one definition of null that casting, sorting and the null literal already
share; a second, narrower one for directory names would make `v=` and `v=_null`
directories appear side by side for values the rest of the tool cannot distinguish.

### Risk: 25
Author most likely prefers: alternative 1. A value that is literally the text `_null`
collides with the null directory under either reading; the spec gives no escape for it
and this implementation does not invent one.

---

## T44: `--output` pointing at an existing plain file in directory mode

### Spec Text
> When any partitioning flag provided: `--output` must be directory path (not `-`)
>   - Create directory if doesn't exist

### Alternatives
1. An existing non-directory at that path is an error; the file is left untouched and
   the run exits 2 with a message, since `--output` does not name a directory.
2. The file is deleted and replaced by the directory tree.

### Choice
Alternative 1. "Create directory if doesn't exist" licenses creating a *missing* path,
not destroying an existing file; silently removing user data to make room is the more
surprising of the two behaviours, and the exit code matches the other `--output`
misuse (T38).

### Risk: 30
Author most likely prefers: an error, but likely whatever code the underlying
`os.replace`/`os.rename` failure surfaces (a generic exit 1) rather than 2.

---

## T45: A `--partition-by` column the resolved schema does not have

### Spec Text
> `--partition-by <col>[,<col>...]`

> Rows for each unique combination of partition column values go into separate directory

### Alternatives
1. It is a schema resolution failure, like an unknown `--key` column: exit 3.
2. It is a usage error (exit 2), because it is about a flag's value.
3. The column is treated as entirely null, producing a single `col=_null` directory.

### Choice
Alternative 1. `--partition-by` names columns of the resolved schema exactly as
`--key` does, and checkpoint 1 already reports an unknown `--key` column as a schema
error; the check cannot even run until the schema is resolved, so it belongs with it.

### Risk: 25
Author most likely prefers: alternative 1, sharing the `--key` check; alternative 3
would follow from reusing the "missing column is null" rule without a check.

---

## T46: Non-positive `--max-rows-per-file` / `--max-bytes-per-file`

### Spec Text
> `--max-rows-per-file <INT>`: cut output into files with at most INT data rows each

### Alternatives
1. A limit below 1 cannot describe a file that holds anything, so it is rejected as a
   usage error (exit 2).
2. `0` is honoured literally: every file holds at most zero rows, which either never
   terminates or produces one header-only file per row.
3. `0` is read as "no limit", like an unset flag.

### Choice
Alternative 1. Reading 2 has no finite output and reading 3 silently turns a typo into
directory mode with no cutting; refusing the value keeps both out. The check runs
while parsing arguments, so it is reported before any input is opened.

### Risk: 30
Author most likely prefers: rejecting it, though an implementation that never
validates would instead loop or emit empty files for `--max-rows-per-file 0`.

---

## T47: Whether nested types may be spelled as generic strings

### Spec Text
> `list<T>`→`array<T>`

> Case-insensitive aliases accepted anywhere type is expected

### Alternatives
1. A nested type may be written either as the object form (`{"array": {"element": ...}}`)
   or as a generic string (`array<int>`, `map<string,int>`, `list<int>`); the alias
   table rewrites the head name of the generic form.
2. Only the object form declares a nested type; `list<T>` is documentation of the
   *concept* `array<T>`, so `"type": "list<int>"` is an unknown type name.

### Choice
Alternative 1. The built-in alias table is a map from one written type name to
another, and `list<T>`→`array<T>` can only be exercised if `list<...>` is a writable
type name; a bare `list` with no element would not need the `<T>` in the rule at all.
Both spellings therefore parse, and the object form remains the one the spec's own
schema example uses.

### Risk: 20
Author most likely prefers: alternative 1 — but an implementation that only pattern
matches the literal prefix `list<` and rewrites it to `array<` would reject a
hand-written `array<int>` while accepting `list<int>`.

---

## T48: Duplicate field names inside one struct

### Spec Text
> **struct**: ordered list of named fields (names unique within struct)

### Alternatives
1. Uniqueness is a rule the schema must satisfy, so a duplicate makes the schema
   unusable: exit 3, before any input is read.
2. Uniqueness is descriptive; a duplicate is tolerated and the last (or first)
   declaration wins.

### Choice
Alternative 1. Every other schema defect (unknown type name, unusable JSON) is an
exit-3 schema resolution failure, and a duplicated field has no deterministic output
encoding — the canonical JSON object would carry the name twice, which the ordering
rules cannot describe.

### Risk: 25
Author most likely prefers: alternative 1, though an implementation that builds the
struct as a dict keyed by field name would silently collapse the duplicate
(alternative 2) without ever checking.

---

## T49: A map declared with a non-string key type

### Spec Text
> **map\<string,T>**: string keys only; value type T can be nested or primitive

### Alternatives
1. `{"map": {"key": "int", ...}}` contradicts "string keys only" and is a schema
   resolution failure: exit 3.
2. The `key` entry is decorative; whatever it says, keys are read as strings.

### Choice
Alternative 1. The schema document spells the key type out, so it can disagree with
the rule, and a schema that disagrees with the type system is exactly what exit 3
reports. Aliases are resolved first, so `{"key": "varchar"}` is accepted.

### Risk: 20
Author most likely prefers: alternative 1; an implementation that simply ignores the
`key` entry (alternative 2) is the plausible variant, and it differs only on a schema
no sane fixture would contain.

---

## T50: What the built-in `json`→`struct` alias means for a bare `struct`

### Spec Text
> `json`→`struct` (accept any JSON, see below)

> Special alias `json`: when field declared as `"type":"json"`, accept any JSON value
> (object/array/primitive) and emit as JSON text

### Alternatives
1. The alias is literal: `json` resolves to the type name `struct`, and a `struct`
   written without any `fields` therefore also means "any JSON value".
2. `json` is special-cased before alias resolution and a bare `struct` (no fields) is
   an incomplete type declaration: exit 3.

### Choice
Alternative 1. The alias table is described as a plain name-to-name mapping, and
listing `json`→`struct` inside it only makes sense if the target is a real, usable
type name; the parenthetical "(accept any JSON, see below)" then describes what that
target does. Treating a field-less struct as "any object or value" also keeps
`{"struct": {"fields": []}}`-style degenerate declarations from needing a rule of
their own. An unparameterized `array`/`map` likewise holds `json` elements/values.

### Risk: 30
Author most likely prefers: `json` handled as its own type kind, with a bare `struct`
either erroring (alternative 2) or being an empty struct that encodes as `{}`.

---

## T51: What counts as an alias cycle, and where an unusable alias file lands

### Spec Text
> May refer to built-ins or other aliases (resolve transitively; detect cycles → error 2)

### Alternatives
1. A cycle is any repeat while following the chain, including `{"loop": "loop"}`, and
   it is reported when the alias is resolved. An alias file that is unreadable, is not
   JSON, or has no `aliases` object is the same class of failure: exit 2.
2. Only cycles of length ≥ 2 count; a self-alias resolves to itself and then fails as
   an unknown type (exit 3). An unusable alias file is a schema failure (exit 3).

### Choice
Alternative 1. A self-referential alias never terminates under naive resolution,
which is precisely what cycle detection exists to stop. The spec puts cycles on exit
2 rather than on the schema code, which reads as "the alias file itself is bad input
to the command line", so every other way the alias file can be bad lands there too.

### Risk: 30
Author most likely prefers: alternative 1 for cycles (it is the natural
`seen`-set implementation), with the exit code for a malformed alias *file* being the
genuinely uncertain half — exit 3 alongside `--schema` is just as plausible.

---

## T52: An alias file entry that redefines a built-in

### Spec Text
> Built-in aliases (always present)

> Optional alias file via `--type-alias-file <ALIASES_JSON>`

### Alternatives
1. The two tables are merged with the file's entries last, so a file entry overrides
   the built-in of the same name.
2. "Always present" means the built-ins are immutable and win over the file.
3. A clash is an error.

### Choice
Alternative 1. "Always present" answers "must I declare them myself?", not "may I
change them?", and merging a user table over a default table is what an
implementation does without thinking about it. Nothing in the spec asks for a clash
check, which rules out 3.

### Risk: 20
Author most likely prefers: alternative 1, for the same
`{**builtin, **user}` reason; alternative 2 is the reading of "always present" that
would flip a fixture that remaps `integer`.

---

## T53: A CSV/TSV cell that is not valid JSON under a nested target

### Spec Text
> **CSV/TSV**: Cell must contain single JSON literal when target type is nested or
> `json`
>   * Empty cell → null
>   * Invalid JSON → handled per `--on-type-error`/error 5

### Alternatives
1. The cell is handled per `--on-type-error`: `coerce-null` nulls it, `keep-string`
   keeps its text, and `fail` raises the cast error, which is exit 4.
2. Invalid JSON is a source-format violation, so `fail` (or every mode) exits 5,
   as the "/error 5" half of the sentence says.

### Choice
Alternative 1. The sentence leads with `--on-type-error`, and the three modes only
have meaning if they all apply; "error 5" then describes what the `fail` mode's
failure *is*, which cannot be right for CSV — the CSV file itself parsed perfectly
well, and it is the cell's content that will not become the declared type. That is
the same condition every other cast failure reports, so it reports it the same way:
`ERR 4`. A trailing `,` after a complete JSON literal counts as invalid, since the
cell must hold a *single* literal.

### Risk: 45
Author most likely prefers: `coerce-null`/`keep-string` exactly as here, with `fail`
exiting 5 rather than 4 — the "/error 5" is hard to explain otherwise.

---

## T54: Object key order inside a `json`-typed value

### Spec Text
> For `json` type: accept any JSON value without casting; normalize only

> * Struct fields in schema-declared order
> * Map keys sorted lexicographically

### Alternatives
1. A `json` value has no declared field order, so its objects are normalized like
   maps: keys sorted lexicographically at every depth.
2. "Without casting ... normalize only" means only whitespace is removed; the input's
   own key order is preserved.

### Choice
Alternative 1. The determinism checklist demands that "nested
casting/normalization yields canonical JSON per ordering rules", and the only
ordering rule that can apply to an undeclared object is the map rule. Preserving
input order would also make one value encode two ways depending on which file it
arrived in, which is what canonicalisation exists to prevent.

### Risk: 40
Author most likely prefers: alternative 2 — `json.dumps` of a parsed value preserves
key order by default, so an implementation only sorts if it decided to.

---

## T55: `keep-string` at the top of a nested column

### Spec Text
> `keep-string`: set to original unparsed JSON string or stringified form

### Alternatives
1. Inside a nested value the failed field becomes a JSON *string* holding the
   original text (so the cell is still canonical JSON). When the whole column value
   fails — a CSV cell that is not JSON at all — the cell is that raw text, exactly as
   a flat column's `keep-string` cell would be.
2. The whole-column case is also wrapped as a JSON string, so a cell reading
   `not-json` is emitted as `"not-json"` with quotes.

### Choice
Alternative 1. "Original unparsed JSON string" is the inner case and "stringified
form" the outer one. A nested column whose text was never JSON has no JSON form to
canonicalise, and `keep-string` everywhere else in the spec means "the cell keeps the
bytes it arrived with"; wrapping would change them.

### Risk: 35
Author most likely prefers: alternative 1 for the inner case (it is the only reading)
and possibly alternative 2 for the outer one, where an implementation that always
serializes the column value would add the quotes.

---

## T56: A field path that descends into a `json` column

### Spec Text
> Each path must resolve to primitive value after casting
>   * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. Paths are checked against the declared type tree before any row is read. A `json`
   column declares nothing about its shape, so no path into it can be shown to reach
   a primitive: exit 3.
2. "After casting" means the check is per row: the path is resolved against each
   row's value, and a row whose leaf is an object or array fails there.

### Choice
Alternative 1. A per-row check would make the same command succeed or fail depending
on the data, which contradicts the deterministic, up-front treatment `--key`
validation has had since checkpoint 1 (an unknown key column fails before any input
is opened). Declared nested types are checkable statically — struct fields, array
elements and map values all have declared types — so `json` is the only type this
excludes, and it is excluded precisely because it promises nothing.

### Risk: 35
Author most likely prefers: alternative 1's static check for struct/array/map, with
`json` allowed through and resolved per row (a hybrid), since nothing in the spec
calls the `json` case out.

---

## T57: An array index that is not a non-negative integer

### Spec Text
> Array indices must be non-negative integers
>   * If out of range or element is null/missing → key fragment is null for that row

### Alternatives
1. "Must be" is a rule about the *path*: `items.-1.qty` or `items.x.qty` is a path
   that cannot address an element, so it fails path resolution with exit 3. Only a
   well-formed index that happens to point past the end yields a null fragment.
2. Anything that does not address an element yields a null fragment, negative indices
   included, so `items.-1.qty` is null for every row.

### Choice
Alternative 1. The two bullets separate the two cases: the first constrains what may
be written, the second says what happens when a legal index finds nothing. Reading a
negative index as "null everywhere" would silently turn a typo into a run that sorts
every row equally.

### Risk: 35
Author most likely prefers: alternative 1, though an implementation that reaches for
Python's own list indexing would give `items.-1` the last element instead — a third
reading this choice also rejects.

---

## T58: The partition directory name for a field path

### Spec Text
> `--partition-by attrs["country"]`

> Rows for each unique combination of partition column values go into separate
> directory (Hive-style `col=val`)

### Alternatives
1. `col` is the path as written, percent-encoded by checkpoint 3's rules:
   `attrs%5B%22country%22%5D=US`.
2. `col` is the path's last segment: `country=US`.
3. `col` is the path as written but left unencoded: `attrs["country"]=US`.

### Choice
Alternative 1. The directory name has to identify the partition column, and the only
name the user gave is the whole path — two different paths can end in the same
segment (`a["x"]` and `b["x"]`), so 2 is not injective. Checkpoint 3 already
percent-encodes both halves of the segment so that no value or name can introduce a
path separator or a quote the shell has to fight, and brackets and quotes are exactly
the characters that rule exists for.

### Risk: 40
Author most likely prefers: alternative 1's use of the full path, with the encoding
of `[`/`"` being the coin flip; a `user.id=1` directory (dots are unreserved) is the
same under every reading.

---

## T59: Splitting `--key` and `--partition-by` on commas

### Spec Text
> `--key <fieldPath>[,<fieldPath>...]`

> Map lookups with `["key"]` read value by exact key

### Alternatives
1. The list is split on commas that are not inside brackets, so `attrs["a,b"]` is one
   path.
2. The list is split on every comma, and a map key containing a comma is simply
   unreachable.

### Choice
Alternative 1. Map keys are arbitrary strings and the bracket syntax exists to quote
them; splitting inside a quoted key would make the quoting pointless. The scan is
otherwise identical to a plain split.

### Risk: 15
Author most likely prefers: alternative 2 by accident (a bare `split(",")`), but the
two agree on every path that has no comma inside a bracket, which is every path a
fixture is likely to contain.

---

## T60: Struct fields the input has but the schema does not declare

### Spec Text
> **struct**: ordered list of named fields

> All struct fields included (even when null) with explicit `null` values

### Alternatives
1. The declared field list is the whole value: undeclared input fields are dropped,
   and declared fields missing from the input appear as `null`.
2. Undeclared fields are carried through after the declared ones.

### Choice
Alternative 1. "All struct fields included" names the *schema's* fields, and a
carried-through field would have no declared type to cast to and no defined position
in the ordering. This also matches how the top level already behaves: a column no
schema declares does not reach the output.

### Risk: 15
Author most likely prefers: alternative 1; carrying unknown fields would break the
"struct fields in schema-declared order" rule.

---

## T61: The text and context of the error-6 message

### Spec Text
> Error: `ERR 6 nested structure requires provided --schema` (exit 6)

### Alternatives
1. The message is exactly that sentence, with no file or line appended, for both
   JSONL values and Parquet schemas.
2. The message is a template and the offending file, line and field are appended, as
   the cast error's `(file=... line=...)` suffix is.

### Choice
Alternative 1. The spec writes this message out in full, without the `<...>`
placeholders it uses in the messages that do take context (`ERR 4 ... (file=...
line=...)`), so what is written is what is emitted.

### Risk: 25
Author most likely prefers: alternative 1, with an appended file name being the
natural embellishment if their implementation reuses a located-error helper.

---

## T62: The stderr message shape for every error

### Spec Text
> `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

> `ERR 3 key column "<path>" does not resolve to a primitive`

> `ERR 6 nested structure requires provided --schema`

### Alternatives
1. `ERR <code> <text>` is the tool's one message shape, so every failure — including
   the ones earlier checkpoints only gave exit codes for — is now spelled that way.
2. Only the three messages quoted here take the `ERR` prefix; other failures keep
   whatever shape they had.

### Choice
Alternative 1. Three unrelated error classes are all written `ERR <code> <text>`,
which is a house style rather than three coincidences, and a tool whose messages
change shape by error class would be the odder outcome. Earlier checkpoints never
fixed a prefix (they said only "exact exit codes and stderr message shape as
specified", with no shape given), so nothing is contradicted. Argparse's own usage
errors keep argparse's wording, as they always have.

### Risk: 30
Author most likely prefers: alternative 1, but the risk is in the details of the
messages this checkpoint does *not* quote — their wording is still this
implementation's invention.

---

## T63: Which punctuation reaches which kind of container

### Spec Text
> Field paths traverse structs, use numeric indices into arrays, and map lookups with
> bracketed string keys

### Alternatives
1. The punctuation is advisory: a dot segment reads a struct field, an array index or
   a map key, and a bracketed segment reads a map key or a struct field. Whichever is
   written, the container decides how to read it.
2. The punctuation is binding: `attrs.country` cannot read a map, and
   `user["name"]` cannot read a struct; both are exit 3.

### Choice
Alternative 1. The sentence describes the three traversals, not a grammar that
forbids the other pairings, and brackets exist to make keys with dots or commas
writable at all. Accepting both spellings can only turn an exit-3 run into a working
one, never the reverse.

### Risk: 20
Author most likely prefers: alternative 1 (one generic "look this segment up" step is
the smaller implementation), with alternative 2 following from a parser that types
each step as it reads it.

---

## T64: The wording of the exit-3 message for a `--partition-by` path

### Spec Text
> Referencing non-primitive (struct/array/map) in keys/partitions is error 3

> Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. One rule, one message: a partition path that is not primitive reports
   `key column "<path>" does not resolve to a primitive` too.
2. The message is adapted, reading `partition column "<path>" ...`.

### Choice
Alternative 1. The rule is stated once for "keys/partitions" together and the message
is given once, under a section covering both; a shared check emitting a shared
message is what that describes.

### Risk: 35
Author most likely prefers: alternative 1 by code reuse — but an implementation that
already distinguishes the two roles in its earlier "column not in schema" message
(as this one does) would naturally adapt this one too.

---

## T65: Numbers inside nested values

### Spec Text
> Primitive casting rules, temporal normalization, null handling apply recursively
> inside nested values

### Alternatives
1. The JSON-number rule from checkpoint 2 (prefer `int` when the value is integral
   and in 64-bit range) applies at every depth, so `{"qty": 4.0}` casts to `4` for an
   `int` field and encodes as `4` in a `json` column.
2. The rule is a top-level convenience only; nested `4.0` stays a float and fails an
   `int` field.

### Choice
Alternative 1. "Apply recursively" is stated without exception, and the rule it names
is part of how a JSON value is read rather than part of any one type's cast.

### Risk: 25
Author most likely prefers: alternative 1, though a `json` column is where the two
readings visibly differ — `4.0` re-emitted as `4` is a normalization an author may
not have intended.

---

## T66: A nested cell whose text is the CSV null literal

### Spec Text
> **CSV/TSV**: Cell must contain single JSON literal when target type is nested or
> `json`
>   * Empty cell → null

> If entire column value is null → emit CSV null literal

### Alternatives
1. Null detection for a nested target is the same as for a flat one: an empty cell,
   or a cell equal to `--csv-null-literal`, is null before any JSON parsing is tried.
2. Only a literally empty cell is null; with `--csv-null-literal NULL`, the text
   `NULL` is handed to the JSON parser and fails as invalid JSON.

### Choice
Alternative 1. `--csv-null-literal` defines how the CSV dialect spells a null cell,
which cannot depend on the declared type of the column; the "empty cell" bullet is
the default spelling of that same literal. Reading 2 would also make the flag
unusable with a nested column.

### Risk: 15
Author most likely prefers: alternative 1, with the difference only visible when a
non-default null literal is combined with a nested column.
