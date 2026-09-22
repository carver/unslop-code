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

---

# Checkpoint: Multi-Format CSV Merger

Entries T26 onward cover the heterogeneous-input extension. Earlier entries
still apply unchanged unless annotated.

---

## T26: The exit-code taxonomy is only partially given

### Spec Text

> - If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2
> - Keys must exist in resolved schema (error 3 otherwise)
> - Mismatch is error 5
> - literal tabs inside field not allowed (error 5)
> - nested fields trigger error 6
> - Exact exit codes and stderr message shape as specified

### Alternatives

The spec names 2, 3, 5 and 6 but never states what 1 and 4 mean, nor which code
covers I/O failures or a cast failure under `--on-type-error fail` (checkpoint 1
said only "exit non-zero").

1. A layered taxonomy inferred from the four given points:
   `1` = I/O / unexpected runtime error, `2` = usage / CLI / undeterminable input
   format, `3` = schema error (bad schema document, key column absent),
   `4` = cast/type error (`--on-type-error fail`), `5` = malformed input data or
   compression mismatch, `6` = unsupported structure (nested JSONL/Parquet).
2. Keep checkpoint 1's flat `1` for everything not explicitly numbered, so a cast
   failure under `fail` still exits 1.

### Choice

Reading 1. The four fixed points are mutually consistent with exactly this ladder
(argv problems before schema problems before value problems before data problems
before unsupported-feature problems), and it leaves no gap at 4 — a spec that
numbers 2, 3, 5 and 6 almost certainly assigned 4 to the one remaining error class
it has, which is the cast failure `--on-type-error fail` already defines.
Every `Fatal` in the implementation carries an explicit code.

### Risk: 55

Author most likely prefers: the same for 2/3/5/6 (they are stated), but `1` rather
than `4` for a `fail`-mode cast error, and possibly `2` rather than `1` for a
missing input file.

---

## T27: Extension says one format, magic bytes say Parquet

### Spec Text

> - `--input-format=auto` (default): detect per file by extension and magic bytes:
>   - `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
>   - If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

### Alternatives

1. Extension first: a recognized extension decides the format outright, and magic
   bytes are consulted only when the extension is not one of the five listed
   (`data.txt`, `data`, `data.dat`).
2. Magic bytes win whenever they say `PAR1`, so `data.csv` holding a Parquet file
   is read as Parquet.

### Choice

Reading 1. The magic-byte clause is written as a subordinate rule for the
"ambiguous" case only, and the sub-bullet order (extension table, then the
ambiguity fallback) matches a `by_extension(path) or by_magic(path) or error(2)`
implementation. A `.parquet` file that is not Parquet therefore fails as malformed
input (error 5) rather than being re-detected.

### Risk: 30

Author most likely prefers: the same; reading 2 only differs on deliberately
mislabelled fixtures.

---

## T28: `--compression=none` pointed at a gzip file

### Spec Text

> - `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> - Mismatch is error 5

### Alternatives

1. "Mismatch" is any disagreement between the resolved compression and the file's
   actual gzip magic bytes, in either direction and under `auto` too: `gzip` forced
   on a plain file, `none` forced on a gzip file, and a `.gz`-named file that is not
   gzip all exit 5.
2. "Mismatch" only covers `--compression=gzip` on a non-gzip file (the case that
   would otherwise throw inside the gzip reader); `none` genuinely "forces no
   decompression" and lets the binary garbage flow into the CSV parser.
3. "Mismatch" refers only to a disagreement between the `.gz` extension and the
   magic bytes.

### Choice

Reading 1. The sentence is placed directly after the two forcing flags and is
symmetric in form, and reading 2 would produce mojibake rather than a diagnostic —
a spec this concerned with exact exit codes would not prefer silent corruption.
Detection is by magic bytes (`1f 8b`), so an empty file is "not gzip".

### Risk: 40

Author most likely prefers: reading 2 restricted to the forced-gzip direction, with
`--compression=none` simply reading raw bytes.

---

## T29: How a "literal tab inside field" is detected in TSV

### Spec Text

> - **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line endings; literal tabs inside field not allowed (error 5)

### Alternatives

1. With no quoting there is no way to distinguish an embedded tab from a delimiter,
   so the only observable symptom is a data row with *more* fields than the header;
   that is reported as error 5. Rows with *fewer* fields are padded with nulls, as
   checkpoint 1 does for ragged CSV (T16).
2. Any field-count mismatch in either direction is error 5.
3. The rule is unenforceable and purely advisory; ragged rows are tolerated.

### Choice

Reading 1. The spec bothers to assign an exit code, so the condition must be
detectable, and a surplus field is exactly the trace an embedded tab leaves.
Short rows are a different defect that the spec never mentions, so checkpoint 1's
tolerance is preserved.

### Risk: 35

Author most likely prefers: reading 2 (any width mismatch is error 5), which
differs on a short TSV row.

---

## T30: A JSONL line that parses but is not an object

### Spec Text

> - **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects as values); `null` permitted; keys case-sensitive; blank/whitespace lines ignored

### Alternatives

1. Invalid JSON syntax is malformed input (error 5); a syntactically valid line that
   is not an object (`[1,2]`, `"x"`, `3`, `null`) violates the flat-object structure
   rule and is error 6, the code the spec assigns to structure violations.
2. Any line that is not a flat object — including a syntax error — is error 5.
3. Any such line is error 6, including syntax errors.

### Choice

Reading 1. The spec ties error 6 to "flat-only enforcement ... nested structures"
in the determinism checklist, and a top-level array is precisely a non-flat
structure appearing where an object was required; a truncated line, by contrast, is
ordinary corrupt data.

### Risk: 35

Author most likely prefers: error 5 for a non-object line, reserving 6 strictly for
a nested *value* inside an otherwise valid object.

---

## T31: The precedence order behind `--schema-strategy=authoritative`

### Spec Text

> - `--schema-strategy=authoritative` (default): prefer typed sources in precedence order

### Alternatives

1. Precedence is by source format, ranked by how much type information the format
   carries: Parquet (declared schema) > JSONL (per-value JSON types) > TSV/CSV
   (raw text). The column's type is taken from the highest-ranked format that
   actually carries the column.
2. Precedence is command-line order: the first input listed that has the column
   wins, typed or not.
3. Precedence is command-line order but restricted to typed sources (Parquet/JSONL),
   with CSV/TSV consulted only if no typed source has the column.

### Choice

Reading 1, with command-line order as the tie-break inside a rank. The phrase
"prefer *typed* sources" makes typedness the ranking criterion, and the spec's own
list of formats — "CSV/TSV values are raw strings ... JSONL values come typed ...
Parquet values come typed" — supplies the ordering, with Parquet ahead of JSONL
because its types are declared in metadata rather than re-derived per value.
When several files of the winning rank disagree, the tie is broken by `--infer`
(see T34).

### Risk: 45

Author most likely prefers: reading 3 — any typed source beats any text source, but
Parquet and JSONL are peers resolved by argument order. This differs whenever a
JSONL file precedes a Parquet file and they disagree.

---

## T32: What "majority of files support" counts under `consensus`

### Spec Text

> - `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives

1. One vote per file: each file that observes the column contributes the single type
   it resolves to on its own, and the type with the most votes wins.
2. Support-set counting: for every candidate type, count files all of whose observed
   values are representable in it, then take the maximum. Because every value is
   representable as `string`, this makes `string` win (or tie for the win) always.
3. Value-weighted counting (a file with more rows counts more).

### Choice

Reading 1. Reading 2 is degenerate — `string` would be the consensus answer for
every column in every input set, making the strategy useless — and reading 3
contradicts "majority of *files*". A tie is broken by widening across the tied
files only: the simplest type that holds every value they observed, using the
same intersection rule as `union` (T33). A 1–1 int/float split therefore yields
`float` rather than an arbitrary pick, and a 1–1 date/timestamp split yields
`string`, since neither type holds the other's values.

### Risk: 50

Author most likely prefers: the same per-file vote, but a tie broken by *priority*
(int over float) or by first-file-wins, which differs on any even split.

---

## T33: What "simplest common type that can hold all observed values" means

### Spec Text

> - `--schema-strategy=union`: choose simplest common type that can hold all observed values

### Alternatives

1. Intersect the candidate-type sets of every observed value across all files and
   take the highest-priority survivor — exactly checkpoint 1's `loose` inference,
   which is already defined as "prefer numeric/temporal types if all non-null
   observed values parse". `int` in one file and `float` in another yields `float`;
   `int` and free text yields `string`.
2. A hand-written widening lattice (`int → float → string`, `date → timestamp →
   string`, everything else `→ string`) applied pairwise to per-file types, which
   agrees with reading 1 on ordinary cases but yields `string` where reading 1 can
   still find a common temporal type.

### Choice

Reading 1: reuse the existing candidate-bitmask intersection. It is the only rule
already defined in the spec family for "a type all values parse as", and reusing it
keeps `--schema-strategy=union` on CSV-only inputs identical to checkpoint 1's
`--infer loose`, which is where those inputs previously landed.

### Risk: 30

Author most likely prefers: the same; a pairwise lattice differs mainly on mixed
`date`/`timestamp` columns.

---

## T34: How `--infer` and `--schema-strategy` compose

### Spec Text

> - Type inference per `--infer` mode (strict or loose)
> - **Schema disagreement strategy** when inputs have conflicting types for same column

### Alternatives

1. `--infer` decides each *file's* own type for a column, and — under the default
   `authoritative` strategy — what happens when the files that get a say still
   disagree: `strict` falls back to `string` (checkpoint 1's rule), `loose` widens
   to the intersection type. `consensus` and `union` name their own conflict rule,
   so they always widen and ignore `--infer` beyond the per-file step.
2. `--schema-strategy` fully supersedes `--infer`; `--infer` only survives as the
   checkpoint-1 knob and is ignored whenever conflicts arise.
3. `--infer loose` implies `union` regardless of `--schema-strategy`.

### Choice

Reading 1. It is the only composition under which both flags keep meaning, and it
is exactly backward compatible: with CSV-only inputs every file has the same
precedence rank, so the default `authoritative` + `strict` reproduces checkpoint 1's
"conflicting types across files fall back to `string`", and `authoritative` +
`loose` reproduces checkpoint 1's global widening.

### Risk: 40

Author most likely prefers: reading 2, with `authoritative` widening or picking the
first typed source even in `strict` mode — differing on CSV-only inputs that
conflict, which is exactly the checkpoint-1 regression surface.

---

## T35: Are string values from typed sources re-inferred as numbers/dates?

### Spec Text

> - JSONL values come typed (string/number/bool/null)
> - Parquet values come typed

### Alternatives

1. JSONL: a JSON *string* carries no more type information than a CSV cell, so it is
   re-inferred with the same rules (`"2024-07-01"` infers `date`, `"12"` infers
   `int`), while JSON numbers/booleans use their JSON type directly (a JSON `1` is
   `int`/`float`, never `bool`). Parquet: the declared column type is used verbatim
   and values are never re-inferred, so a Parquet `string` column stays `string`.
2. Any value from a typed source keeps its source type, so a JSONL string column of
   ISO dates infers as `string`.
3. Every source, Parquet included, is re-inferred from the rendered text.

### Choice

Reading 1. It keeps text-valued columns consistent across CSV and JSONL (otherwise
the same date column read from two formats would "conflict" purely because of
transport), while honouring "Parquet values come typed" where a real schema exists —
and it means a JSON `0`/`1` column is `int`, not `bool`, which is the one place
checkpoint 1's T2 behaviour should not leak into typed data.

### Risk: 40

Author most likely prefers: reading 2 for JSONL strings (source type wins
uniformly), which differs for JSONL columns holding ISO dates or numeric strings.

---

## T36: "prefer `int` if integer and within range"

### Spec Text

> - For JSONL numbers, prefer `int` if integer and within range; otherwise `float`

### Alternatives

1. "Within range" is the 64-bit signed integer range: a JSON number that is integral
   (including `1.0`, which `json` decodes as a float) and fits in
   [-2^63, 2^63-1] becomes `int`; anything else — fractional, or a huge integer
   literal — becomes `float`.
2. "Within range" is Python's unbounded `int`, so the clause never excludes anything
   and any integral JSON number is an `int`.
3. Only JSON values already decoded as `int` are ints; `1.0` stays `float`.

### Choice

Reading 1. A range qualifier is meaningless in Python unless it refers to a
machine integer width, and 64-bit is the width every columnar format in this spec
(Parquet included) uses. Consequence: `{"n": 1.0}` renders `1` in a string column
and `1e30` renders as a float.

### Risk: 20

Author most likely prefers: the same; reading 3 differs only on JSON numbers
written with a redundant `.0`.

---

## T37: Cast rules for values that arrive already typed

### Spec Text

> - Apply target output schema cast rules to every cell

### Alternatives

1. Normalize each typed value to its canonical text (the same text the tool would
   *emit* for it) and then apply checkpoint 1's parse rules for the target type.
   So Parquet `int64` 1 → `"1"` → a `bool` column accepts it (checkpoint 1 treats
   `1` as a bool literal); a `float` 1.5 → `"1.5"` → an `int` column fails it and
   `--on-type-error` applies.
2. A dedicated native-to-native cast matrix (int→bool forbidden, float→int allowed
   by truncation, etc.).

### Choice

Reading 1. One parse path for all formats is the only way the same logical value
lands identically whether it arrived as CSV text or a Parquet column, which is what
"apply target output schema cast rules to *every* cell" asks for, and it inherits
every checkpoint-1 decision (bool spellings, timestamp normalization, float
rendering) for free.

### Risk: 30

Author most likely prefers: the same for the common cases; divergence is likeliest
on int→bool and float→int.

---

## T38: An explicit empty string from a typed source

### Spec Text

> - If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal

### Alternatives

1. Literal reading: the nullness test is per source class. `{"a": ""}` is a real
   empty string, not a missing value, so with `--csv-null-literal NULL` it emits an
   empty field while a JSONL `null` emits `NULL`.
2. Uniform reading: any empty string is missing regardless of source, so both emit
   `NULL`.

### Choice

Reading 1. The sentence deliberately splits the two source classes and attaches
emptiness only to CSV/TSV, which are the formats that cannot express the
distinction. This is observable only with a non-default null literal or under
`--on-type-error fail` (where `""` in an `int` column from JSONL is a cast failure).

### Risk: 30

Author most likely prefers: reading 2, if their reader funnels every value through
one `is_null(value)` helper.

---

## T39: Default and meaning of `--parquet-row-group-bytes`

### Spec Text

> - Parquet reading must be streamed row group–wise; `--parquet-row-group-bytes` is advisory for batch sizing

### Alternatives

1. Advisory only: it caps the approximate uncompressed bytes per read batch and is
   converted to a row count using the file's own average row size, additionally
   clamped by `--memory-limit-mb`. Default 8 MiB. Not observable in the output.
2. It is a row count, not a byte count.
3. It also controls output Parquet writing (there is none).

### Choice

Reading 1. "Advisory" and "batch sizing" both point at a memory-shaping hint, and
the output is byte-identical for any value, so only peak memory changes.

### Risk: 10

---

## T40: "write atomically"

### Spec Text

> - `--output -` writes to stdout; otherwise write atomically

### Alternatives

1. Write to a temporary file in the destination's own directory, `fsync`-free but
   fully flushed, then `os.replace` it over the destination — so the destination
   either does not exist / keeps its old content, or is the complete new output.
   A failure anywhere before the rename leaves no partial file and no stray temp.
2. Write in place and merely truncate on failure.

### Choice

Reading 1, the standard meaning. Same-directory placement keeps the rename on one
filesystem; `--temp-dir` is not used for it, since that directory may be on another
device and would make the rename non-atomic.

### Risk: 10

---

## T41: Mapping Parquet logical types onto the six schema types

### Spec Text

> - **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6

### Alternatives

1. `bool`→`bool`; all integer widths (signed and unsigned)→`int`; `float16/32/64`
   and `decimal`→`float`; `date32/64`→`date`; `timestamp`→`timestamp`;
   `string/large_string/binary`→`string`; `time32/64` and `null`→`string`.
2. `decimal`→`string` to preserve exact scale.
3. `timestamp` with a timezone →`timestamp`, without →`string`.

### Choice

Reading 1. The spec's type vocabulary has no decimal or time-of-day member, so each
Parquet type maps to the closest of the six; decimal is numeric, so `float` is
closer than `string`. Timezone-naive Parquet timestamps are treated as UTC, which
is checkpoint 1's rule for zone-less input.

### Risk: 35

Author most likely prefers: the same for the common types (bool/int/float/string/
timestamp); decimal and time-of-day are the likely divergence, and `decimal` →
`string` is the plausible alternative.

---

## T42: Gzip-compressed Parquet

### Spec Text

> - For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz`, `events.jsonl.gz`)

### Alternatives

1. The rule is general, so `data.parquet.gz` is legal; because Parquet needs random
   access, the stream is decompressed into the temp area first and then read row
   group–wise from there.
2. Only text formats may be gzipped; `.parquet.gz` is an error.

### Choice

Reading 1 — the rule is stated for the suffix in general and the two examples are
introduced with "e.g.". The extra decompression is invisible apart from temp-space
use, and the temp file is cleaned up like every other intermediate.

### Risk: 15

---

## T43: A Parquet or TSV file that declares columns but has no rows

### Spec Text

> - Column set: union of all encountered field names

### Alternatives

1. "Encountered field names" includes names declared in a header row or a Parquet
   schema even when no data row follows; a Parquet column contributes its declared
   type to resolution even with zero rows. A JSONL file, having no header, can only
   contribute names it actually encounters in values.
2. Only names attached to at least one observed value count.

### Choice

Reading 1. Checkpoint 1 already derives inferred columns from CSV headers rather
than from values (T22: a header-only file contributes its columns), and a Parquet
schema is the direct analogue of a header.

### Risk: 20

---

## T44: Scope of an explicit `--input-format` / `--compression`

### Spec Text

> ```
> python merge_files.py --output - ... --input-format tsv --compression gzip data/*.tsv.gz
> ```

### Alternatives

1. The flags are global: an explicit value applies to every positional input and
   suppresses per-file detection for that dimension (format and compression are
   independent, so `--input-format tsv --compression auto` still detects `.gz`
   per file).
2. They apply only to files whose type cannot be detected.

### Choice

Reading 1 — the example passes a glob of uniformly-typed files, and "forces" is the
verb the spec uses for `--compression`.

### Risk: 10

---

## T45: Duplicate and case-differing keys inside one JSON object

### Spec Text

> - one UTF-8 JSON object per line; ... keys case-sensitive

### Alternatives

1. `"a"` and `"A"` are two distinct columns (stated), and a key repeated within one
   object takes its last value (`json.loads` semantics) rather than being an error.
2. A repeated key is a malformed record (error 5).

### Choice

Reading 1. Case sensitivity is explicit; duplicate keys are never mentioned, and the
JSON parser's own last-wins behaviour is the path of least resistance for any
implementation.

### Risk: 15
