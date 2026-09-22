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

---

## T46: Are the partition columns still written inside the partition CSV files?

### Spec Text

> - Emit directory tree inside `--output` using Hive-style segments:
>   `<col1>=<val1>/<col2>=<val2>/.../`

> - Each file contains header row (resolved schema header)

> **CSV Output Contents**
>
> - Every output CSV includes header row in resolved schema column order

### Alternatives

1. The partition columns remain ordinary columns: every part file carries the
   full resolved schema header and every row repeats the partition values.
2. Hive/Spark convention — the partition columns are *projected out* of the data
   files because their values are recoverable from the directory names, so the
   header is the resolved schema minus the partition columns.

### Choice

Reading 1. The spec says the header is "the resolved schema header" and, in a
separate section that applies to *every* output CSV, "header row in resolved
schema column order". Neither sentence carves out an exception for partition
columns, and the spec never describes a reduced header. A conforming reader is
also told each file is "independently valid CSV", which is friendlier when the
partition values are present in the rows.

### Risk: 20

The author may have followed the Hive convention and stripped the partition
columns from the data files.

---

## T47: What exactly gets percent-encoded in a Hive segment, and in which hex case?

### Spec Text

> - Apply percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`

### Alternatives

1. Encode both the column name and the value with the same rule, using
   upper-case hex digits, leaving the literal `=` that joins them unencoded.
2. Encode only the value (column names are assumed already safe).
3. Use lower-case hex (`%2f`).

### Choice

Reading 1 for the encoding target, and upper-case hex. The rule is stated as a
property of the segment text, and `%2F` in the spec itself is upper-case (as is
`%20`), which is also what `urllib.parse.quote` produces. The `=` separator is
structural — encoding it would make the segment unparseable — so it stays
literal. Encoding the name as well is a no-op for every ordinary identifier, so
this choice only differs on exotic column names.

### Risk: 12

The author most likely percent-encodes only the value and passes the column
name through verbatim.

---

## T48: `--output` already exists as a non-empty directory

### Spec Text

> - Create directory if doesn't exist
> - Perform atomic write by creating sibling temp directory and renaming on success

### Alternatives

1. The run *replaces* the destination: the freshly built temp directory is
   renamed into place and any previous contents disappear.
2. The new tree is merged into the existing directory, overwriting only the
   part files it happens to produce.
3. A non-empty destination is an error.

### Choice

Reading 1. "Renaming on success" is only atomic if the whole tree swaps in one
step, and a merge would leave stale `part-xxxxx.csv` files from an earlier run
lying around, which directly contradicts the determinism checklist ("Directory
layout and file names follow exact rules"). Implemented by moving the old
directory aside, renaming the temp directory into place, then deleting the old
one.

### Risk: 30

The author may simply `os.makedirs(out, exist_ok=True)` and then move
individual files in, which merges rather than replaces; a fixture that runs
twice into the same directory would then keep stale files.

---

## T49: Zero data rows in partitioned or sharded mode

### Spec Text

> - File naming (no field partitioning): write files directly under `--output` as `part-00000.csv`, `part-00001.csv`, … in exact order rows are emitted from sorted stream

### Alternatives

1. No rows means no part files: `--output` is created (possibly after making
   the directory) but left empty.
2. A single header-only `part-00000.csv` is always written, mirroring the
   non-partitioned mode, which does emit a header-only CSV for an empty input.

### Choice

Reading 1. Files are described as being created "in exact order rows are
emitted"; with no rows there is no first file. The same writer has to be lazy
for field partitioning (you cannot create a directory for a partition you never
saw), so a single lazy writer implementation naturally produces nothing here
too.

### Risk: 40

The author may open the first shard eagerly and emit a header-only
`part-00000.csv`.

---

## T50: Exit code for `--output -` together with a partitioning flag

### Spec Text

> - When any partitioning flag provided: `--output` must be directory path (not `-`)

### Alternatives

1. Exit 2 (usage) — the combination of flags is invalid on its face, decidable
   before any input is read.
2. Exit 1 (I/O) — treat it as a destination problem.

### Choice

Reading 1. This is a pure argument-combination constraint, in the same family as
the other exit-2 usage errors already in the taxonomy (see [[T26]]), and it is
detectable without touching the filesystem.

### Risk: 10

---

## T51: `--output` names an existing regular file while partitioning

### Spec Text

> - When any partitioning flag provided: `--output` must be directory path (not `-`)
> - Create directory if doesn't exist

### Alternatives

1. Exit 1 (I/O): the path cannot be made into a directory, which surfaces as a
   filesystem error when the tool tries to create/rename it.
2. Exit 2 (usage): "must be directory path" is read as an argument constraint,
   validated up front with a `stat`.

### Choice

Reading 1. The natural implementation reaches this state through
`os.makedirs`/`os.rename` raising `FileExistsError`/`NotADirectoryError`, which
the tool already funnels into the I/O exit code. Unlike [[T50]], it is not
decidable from the argv alone.

### Risk: 35

The author may validate the destination up front and report usage (exit 2).

---

## T52: A `--partition-by` column missing from the resolved schema

### Spec Text

> **Partitioning by Fields** (`--partition-by <col,...>`)
>
> - Rows for each unique combination of partition column values go into separate directory

### Alternatives

1. Exit 3 (schema), by analogy with the existing rule that key columns "must
   exist in resolved schema (error 3 otherwise)".
2. Exit 2 (usage).
3. Treat every row as having a null value for it and emit one `col=_null`
   directory.

### Choice

Reading 1. `--partition-by` names columns of the resolved schema exactly as
`--key` does, and the spec already fixes exit 3 for that failure; reusing it is
the only consistent reading. Reading 3 is silently wrong — a user who typos a
column name would get one giant `_null` partition.

### Risk: 25

The author may not validate partition columns at all and fall into reading 3.

---

## T53: Does the header count when deciding "if single row alone exceeds INT"?

### Spec Text

> - `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file (including header and line endings) is ≤ INT
>   - Exception: if single row alone exceeds INT, place that row in file by itself (allowed to exceed limit)

### Alternatives

1. The invariant is "never cut a file that has no data rows in it yet": a row is
   always appended to a file that is still empty of data, even if
   `header + row > INT`. So the exception fires whenever header+row exceeds the
   limit, not only when the row's own bytes do.
2. The exception fires strictly when `len(row) > INT`; if `len(row) <= INT` but
   `len(header) + len(row) > INT`, something else must happen (an error, or a
   headerless file), which the spec never describes.

### Choice

Reading 1. It is the only reading that keeps every file both non-empty and
header-bearing, and it is what falls out of the obvious writer loop — "if the
current file already has at least one row and adding this one would exceed the
limit, roll over". Reading 2 has no defined behaviour for the gap case.

### Risk: 15

### Related

Under this choice `--max-bytes-per-file` smaller than the header itself still
produces one data row per file rather than an error.

---

## T54: An empty-string partition value versus a missing one

### Spec Text

> - Null (missing) partition values use literal `_null`

### Alternatives

1. Whatever the cast pipeline already calls null becomes `_null`. That includes
   an absent column, an empty CSV cell (already treated as null — see [[T8]]),
   and a value that failed to cast under `coerce-null`.
2. Only a structurally absent field is `_null`; an empty cell produces an empty
   segment `col=`.

### Choice

Reading 1. The spec's own gloss is "Null (missing)", equating the two, and the
partition value is taken "after casting to resolved schema types" — after
casting there is exactly one null representation and no way to distinguish the
origins. An empty segment would also be an awkward directory name.

### Risk: 10

---

## T55: Validation of the sharding integers

### Spec Text

> - `--max-rows-per-file <INT>`: cut output into files with at most INT data rows each
> - `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file … is ≤ INT

### Alternatives

1. Both must be strictly positive; `0` or a negative value is a usage error
   (exit 2), because a limit of 0 makes "at most INT rows" unsatisfiable.
2. `0` is accepted and degenerates (infinite files, or treated as unlimited).

### Choice

Reading 1, matching how `--memory-limit-mb` and `--parquet-row-group-bytes` are
already validated by this tool. A zero limit cannot be honoured by any output.

### Risk: 18

The author may not validate at all, in which case `--max-rows-per-file 0` would
put one row per file (the [[T53]] exception applied to rows).

---

## T56: Spelling of the `--partition-by` column list

### Spec Text

> `[--partition-by <col>[,<col>...]]`

### Alternatives

1. Comma-separated, and additionally repeatable, exactly like `--key` (which
   has the same `<col>[,<col>...]` metavar).
2. Comma-separated only; a repeated flag replaces the earlier value.

### Choice

Reading 1 — a superset of reading 2 for every input the spec shows, and the
identical metavar to `--key` invites the identical handling. Ordering is the
order written, since that order defines the directory nesting.

### Risk: 5

---

## T57: Where the "sibling temp directory" lives and when it is removed

### Spec Text

> - Perform atomic write by creating sibling temp directory and renaming on success
> - On failure, remove temp directory and partial files

### Alternatives

1. Sibling means "in the parent directory of `--output`", so the rename is a
   same-filesystem operation and therefore atomic. It is removed on any failure
   path, including a cast/IO error raised mid-stream.
2. Sibling means "inside `--temp-dir`", reusing the spill directory.

### Choice

Reading 1. A rename across filesystems is not atomic, and `--temp-dir` is
documented for spill files; only the destination's own parent guarantees the
rename works. The temp directory is created with a `.merge_files-` prefix and
torn down in a `finally`/`except` guard.

### Risk: 8

---

## T58: Interaction of `--partition-by` with a partition column that is also a key

### Spec Text

> - With field partitioning: rows in each partition directory must be sorted by `--key` within that partition

### Alternatives

1. No special case: partitioning and sorting are independent, so a column may
   appear in both `--key` and `--partition-by`. Within a partition that key is
   constant, and the remaining keys break ties.
2. Overlap is rejected as a usage error.

### Choice

Reading 1. Nothing in the spec forbids the overlap, and it is harmless: the
global sort is computed first and rows are routed to partitions in that order,
which satisfies the per-partition guarantee for free.

### Risk: 5

---

## T59: Are empty partition directories or intermediate directories created?

### Spec Text

> - Emit directory tree inside `--output` using Hive-style segments:
>   `<col1>=<val1>/<col2>=<val2>/.../`

### Alternatives

1. Only leaf directories that actually receive a row exist; the tree is created
   lazily on the first row of each combination. No directory for a combination
   that no row has.
2. The full cartesian product of observed values per column is materialised.

### Choice

Reading 1 — "Rows for each unique combination of partition column values go into
separate directory" describes combinations that occur in the data, and a
cartesian product would create empty directories the spec never asks for.

### Risk: 3

---

# Checkpoint: Nested Types Support (T60+)

---

## T60: Does the new `ERR <n> ...` text replace the `merge_files.py: error: ` prefix?

### Spec Text

> * `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

> * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

> * Error: `ERR 6 nested structure requires provided --schema` (exit 6)

### Alternatives

1. The `ERR <n> ...` text is the *whole* stderr line: earlier checkpoints' shape
   (`merge_files.py: error: <message>`) is dropped for these three messages.
2. The `ERR <n> ...` text is the *message body*, carried by the existing prefix, so
   the line reads `merge_files.py: error: ERR 4 cannot cast ...`.

### Choice

Reading 2. Earlier checkpoints pin "Exact exit codes and stderr message shape", and
this checkpoint's Determinism Checklist says "exit codes/messages continue from prior
checkpoints" — so the prefix continues and the new strings are the bodies. A test
that greps for `ERR 4` (by far the most natural fixture, because the spec's own
`file=...`/`line=...` placeholders are unwritable as an exact match) passes under
either reading, while a test for the old prefix only passes under this one.

### Risk: 20

Author most likely prefers: the bare `ERR n ...` line with no program prefix.

---

## T61: Do *flat* cast failures also switch to the `ERR 4` wording?

### Spec Text

> * On cast failure within nested structures:
>   * ...
>   * `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

### Alternatives

1. The `ERR 4` wording is scoped to failures *within nested structures*; a top-level
   primitive column keeps whatever wording earlier checkpoints used.
2. This checkpoint finally pins the wording of the cast-failure message, and it applies
   to every cast failure; a top-level column is simply a `<path>` of one segment.

### Choice

Reading 2 — one message builder for every cast failure, with `<path>` being the dotted
path of the failing node (`amt` for a flat column, `user.age` inside a struct). The
earlier checkpoints never specified an exact cast-failure string, so nothing is lost by
adopting the one the spec now supplies, and a single code path cannot drift between the
flat and nested cases.

### Risk: 15

Author most likely prefers: same, but possibly keeping a distinct legacy string for
flat columns.

---

## T62: What `file=` and `line=` hold for each input format

### Spec Text

> `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

### Alternatives

1. `file=` is the input path exactly as given on the command line and `line=` is a
   1-based physical line number (CSV/TSV/JSONL). Parquet has no lines, so `line=` is
   the 1-based row ordinal within the file.
2. `line=` is omitted (or `-`) for Parquet.
3. `file=` is an absolute path.

### Choice

Reading 1: `file=<argv path> line=<1-based line or row ordinal>`. The path as typed is
what a user can act on, and a row ordinal is the only "line-like" coordinate Parquet
has. For CSV/TSV the number is the physical line of the record (header = line 1), which
is what earlier checkpoints already reported.

### Risk: 30

Author most likely prefers: the same for text formats; Parquet numbering may be
0-based or row-group relative.

---

## T63: Is the string form `array<T>` / `map<string,T>` accepted where a type is expected?

### Spec Text

> * Built-in aliases (always present):
>   * ...
>   * `list<T>`→`array<T>`

> * Case-insensitive aliases accepted anywhere type is expected

### Alternatives

1. Types are written only in the object form shown in the schema example
   (`{"array": {"element": ...}}`); the `list<T>`→`array<T>` line is prose about the
   *object* key `list` and generic string syntax is not supported.
2. Both forms are accepted: the object form from the example, and a string form
   `array<int>`, `list<map<string,float>>`, `map<string,int>`, since `list<T>`→`array<T>`
   is written as a textual rewrite and an alias file's values are plain strings
   (`"decimal": "float"`), so a user could equally write `"intlist": "array<int>"`.

### Choice

Reading 2 — accept both. `list<T>`→`array<T>` is only meaningful as a rewrite of a
*string* type name, and accepting the object form too costs nothing. `struct` has no
string form (it needs named fields), so a bare `struct` string is treated as the
any-JSON type (see T65).

### Risk: 30

Author most likely prefers: the same, though an author who only implemented the object
form would reject `"type": "array<int>"` outright.

---

## T64: Are alias names accepted as *object* keys, and inside nested positions?

### Spec Text

> * Case-insensitive aliases accepted anywhere type is expected

### Alternatives

1. Aliases only rewrite scalar type names (`"type": "integer"`), never the object-form
   discriminator keys.
2. "anywhere type is expected" includes the object-form key, so `{"list": {"element":
   "long"}}` is the same as `{"array": {"element": "int"}}`, and element/value/field
   types are alias-resolved recursively.

### Choice

Reading 2 — the phrase is emphatic ("anywhere"), and `list<T>`→`array<T>` already shows
`list` standing in for `array` as a constructor and not just a scalar. Discriminator
keys are lower-cased and alias-resolved exactly like scalar names.

### Risk: 25

Author most likely prefers: aliases on scalar names and on `list`, with other
constructor keys taken literally.

---

## T65: What `json`→`struct` means, and what a bare `struct`/`array`/`map` name means

### Spec Text

> * `json`→`struct` (accept any JSON, see below)

> * Special alias `json`: when field declared as `"type":"json"`, accept any JSON value (object/array/primitive) and emit as JSON text

### Alternatives

1. `json` literally resolves to a struct type with zero declared fields, so every value
   would normalize to `{}` — contradicted by "accept any JSON value (object/array/
   primitive)".
2. `json` is its own wildcard kind: values of any JSON shape pass through uncast and are
   re-emitted as canonical JSON text. The `→struct` note only says it is a *nested* (not
   primitive) kind, which is what matters for the error-3 rule.

### Choice

Reading 2. A bare `"struct"` / `"array"` / `"map"` string (no fields/element/value given)
is also treated as the same wildcard kind, because it carries no structure to cast
against — this is exactly what `json`→`struct` implies. All of them are non-primitive,
so using them in `--key`/`--partition-by` is error 3.

### Risk: 25

Author most likely prefers: `json` as a wildcard (same as here) but a bare `struct`
string rejected as an unknown/invalid type.

---

## T66: Object key order for a `json`-typed value

### Spec Text

> * For `json` type: accept any JSON value without casting; normalize only

> * Otherwise, serialize nested value as canonical JSON:
>   * Struct fields in schema-declared order
>   * Map keys sorted lexicographically

### Alternatives

1. A `json` value's object keys keep their input order — "without casting; normalize
   only" means just minify and re-escape.
2. A `json` value's objects have no schema-declared order, so the only canonical
   choice left is the map rule: sort keys lexicographically.

### Choice

Reading 2 — sort keys. "Canonical JSON" is the section heading, and canonicality is
precisely the property that two inputs differing only in key order produce the same
cell. An unknown-keyed object is structurally a `map<string,json>`, so the map rule is
the one that applies.

### Risk: 45

Author most likely prefers: input order preserved (a plain `json.dumps` of the parsed
value, with no `sort_keys`).

---

## T67: Exit code for an unknown type name

### Spec Text

> * Alias resolution is case-insensitive, transitive, cycle-checked; unknown types error deterministically

> * May refer to built-ins or other aliases (resolve transitively; detect cycles → error 2)

### Alternatives

1. Unknown type names are usage errors like cycles → exit 2.
2. Unknown type names are schema errors → exit 3, as in earlier checkpoints where an
   unrecognised `"type"` in `--schema` was a schema error.

### Choice

Reading 2 for a type appearing in the `--schema` document (exit 3, continuing the prior
checkpoint's behaviour), reading 1 for a dangling *alias target* inside
`--type-alias-file` (exit 2, alongside the cycle rule which the spec does pin to 2).
The spec pins only cycles, and it pins them while talking about the alias file — so the
alias file is the exit-2 surface and the schema document keeps its exit-3 surface.

### Risk: 40

Author most likely prefers: exit 2 for every alias/type resolution failure, including
unknown types named in `--schema`.

---

## T68: When are alias cycles detected?

### Spec Text

> * May refer to built-ins or other aliases (resolve transitively; detect cycles → error 2)

### Alternatives

1. Lazily: only if a cyclic alias is actually referenced by a `--schema` column.
2. Eagerly: every entry of the alias file is resolved when the file is loaded, so a
   cycle is reported even when no column uses it.

### Choice

Reading 2 — "detect cycles" is listed as a property of alias-file loading, and eager
validation is deterministic regardless of which columns happen to be declared. It is
also the only reading under which a cycle is reported when `--schema` is absent.

### Risk: 20

Author most likely prefers: lazy resolution, reporting a cycle only when the alias is
used.

---

## T69: May a user alias shadow a built-in alias or a primitive name?

### Spec Text

> * Optional alias file via `--type-alias-file <ALIASES_JSON>`
> * Aliases apply after lowercasing names
> * May refer to built-ins or other aliases

### Alternatives

1. The user map is merged over the built-ins, so `{"integer": "string"}` wins and even
   `{"int": "string"}` redefines a primitive.
2. Built-ins win over user entries.
3. Primitive names (`int`, `float`, ...) are not aliasable, but built-in *aliases* may be
   overridden.

### Choice

Reading 3. "Built-in aliases (always present)" reads as a floor the user extends, and
the natural implementation is `aliases = {**builtin, **user}` — but a primitive name is
resolved *before* the alias map is consulted (the six primitive names are the terminals
of the resolution), so `int` always means `int`. This also keeps cycle detection
well-founded.

### Risk: 25

Author most likely prefers: a plain dict merge in which a user entry can shadow anything,
including a primitive name.

---

## T70: `--on-type-error fail` on a CSV cell whose JSON literal is invalid — exit 4 or 5?

### Spec Text

> * **CSV/TSV**: Cell must contain single JSON literal when target type is nested or `json`
>   * Empty cell → null
>   * Invalid JSON → handled per `--on-type-error`/error 5

### Alternatives

1. Invalid JSON is routed through `--on-type-error`, and `fail` reports the cast-failure
   error, exit 4 — the trailing "/error 5" being shorthand for "it is bad input data".
2. Invalid JSON is a data error in its own right: `fail` exits 5, and possibly all three
   modes exit 5.

### Choice

Reading 1 — exit 4 with the `ERR 4 cannot cast "<cell>" to <type> in field "<col>"`
message. The bullet leads with "handled per `--on-type-error`", which only has meaning
if all three modes apply, and the Casting section gives `fail` exactly one message and
one code. `coerce-null` and `keep-string` behave as for any other cast failure.

### Risk: 45

Author most likely prefers: exit 5 for an unparseable JSON cell under `fail`.

---

## T71: Input nesting that does not match the declared type

### Spec Text

> * If schema declares flat type but input has object/array, handle per `--on-type-error`

> * **Parquet**: Accept nested structs/lists/maps only when schema declares compatible nested types

> * With `--schema`, Parquet/JSONL nesting must structurally match and cast recursively

### Alternatives

1. Every structural mismatch (array where a struct is declared, struct where `int` is
   declared, Parquet `list` where the schema says `map`, ...) is a cast failure handled
   per `--on-type-error`.
2. JSONL mismatches follow `--on-type-error` (the spec says so) but a Parquet mismatch is
   a hard error — "must structurally match" — exiting 6 or 3.

### Choice

Reading 1, uniformly. The spec states the `--on-type-error` rule for the flat-declared
case and never states a different code for the nested-declared case; using one recursive
cast for both means a `list` arriving where `map<string,int>` is declared nulls (or
keeps, or fails) exactly like a string arriving where `int` is declared. "Must
structurally match" then describes what has to hold for data to survive, not a separate
exit code.

### Risk: 35

Author most likely prefers: `--on-type-error` for JSONL, but a hard error (6) for a
Parquet column whose physical nesting differs from the declared nesting.

---

## T72: A *string* arriving for a nested column from JSONL or Parquet

### Spec Text

> * **JSONL**: Accept nested objects/arrays only when schema declares column as nested or `json`
> * **CSV/TSV**: Cell must contain single JSON literal when target type is nested or `json`

### Alternatives

1. Only CSV/TSV cells are re-parsed as JSON text; a JSON string `"{\"a\":1}"` in JSONL,
   or a Parquet `string` column, arriving where a struct is declared is a cast failure
   handled per `--on-type-error`.
2. Any string is opportunistically parsed as JSON when the target is nested, whatever the
   source format.

### Choice

Reading 1. The "cell contains a JSON literal" rule is stated only for the text formats,
which is exactly where types are carried by text; JSONL and Parquet carry real types, so
a string there means the string. (For a `json`-typed column a string is not a failure at
all: a JSON string is itself a valid JSON value and is emitted as `"..."`.)

### Risk: 30

Author most likely prefers: the same, but may well re-parse strings for Parquet
`string` columns declared nested, since that is the only way such data can be carried.

---

## T73: What `keep-string` stores for a failed node inside a nested value

### Spec Text

> * `keep-string`: set to original unparsed JSON string or stringified form

### Alternatives

1. The node becomes a JSON *string* holding the original text: for an input string, the
   string itself; for a number/bool, its canonical text; for an object/array, its
   canonical JSON text.
2. The node is left exactly as it arrived (a number stays a JSON number, an object stays
   an object).

### Choice

Reading 1 — "set to ... string ... or stringified form" says the result is a string in
every case. So `{"qty": "abc"}` against `int` keeps `"abc"`, `{"qty": {}}` against `int`
keeps `"{}"`, and a struct declared where `7` arrived keeps `"7"`.

### Risk: 30

Author most likely prefers: the same for strings; a passed-through raw value (reading 2)
for objects/arrays is the plausible variant.

---

## T74: Missing struct fields, extra input keys, and non-object input for a struct

### Spec Text

> * All struct fields included (even when null) with explicit `null` values
> * **struct**: ordered list of named fields (names unique within struct)

### Alternatives

1. A declared field absent from the input is `null`; an input key not declared in the
   struct is dropped (mirrors the top-level "Extra input columns ignored / missing
   columns filled with null" rule from earlier checkpoints).
2. An undeclared key is a cast failure, or is carried through into the output.

### Choice

Reading 1: structs behave like the top-level schema does — declared fields only, in
declared order, missing ones explicitly `null`, extras dropped. A value that is not a
JSON object where a struct is declared is a cast failure for the whole struct node,
handled per `--on-type-error` (so `coerce-null` makes the whole struct `null`, not a
struct of nulls).

### Risk: 20

Author most likely prefers: the same, but `coerce-null` might produce an all-null struct
`{"a":null,"b":null}` rather than a bare `null` for the node.

---

## T75: Maps whose input keys are not strings

### Spec Text

> * **map\<string,T>**: string keys only; value type T can be nested or primitive

### Alternatives

1. Non-string keys (a Parquet `map<int64,...>`) are a cast failure for the map node.
2. Keys are stringified and kept.

### Choice

Reading 2 for Parquet/at-rest keys that are not strings — the key is rendered with the
same canonical text used for primitive output (`5`, `true`, `2024-01-01`) and the map is
otherwise cast normally, because the *values* are what the declared type is about and a
JSON object literally cannot have a non-string key. JSON sources always deliver string
keys, so this only affects Parquet.

### Risk: 20

Author most likely prefers: the same (or a hard structural mismatch for a non-string-keyed
Parquet map).

---

## T76: Field-path syntax details

### Spec Text

> * Field paths traverse structs, use numeric indices into arrays, and map lookups with bracketed string keys
> * Examples: `user.id`, `items.0.qty`, `attrs["country"]`

### Alternatives

1. Strictly as shown: `.` for struct fields, `.<n>` for array indices, `["..."]` only for
   map keys.
2. Also accept the obvious near-misses: `items[0]` for an array index, `attrs.country`
   for a map key, `user["name"]` for a struct field, single-quoted bracket keys.

### Choice

Reading 2 — the documented spellings all work, plus the near-misses resolve the same way,
because nothing in the spec says the other spellings are errors and each is unambiguous
given the declared type at that point. A bracketed key containing `.` (`attrs["a.b"]`) is
one key, `\"` and `\\` are escapes inside a bracketed key, and an *unquoted* bracket
holding digits is an array index.

### Risk: 25

Author most likely prefers: the strict reading, erroring (exit 3) on `attrs.country`.

---

## T77: A column whose *name* contains dots or brackets

### Spec Text

> * `--key` and `--partition-by` now accept **field paths** using dot notation (e.g., `user.id`, `items.0.sku`)

### Alternatives

1. The path is always parsed first, so a flat column literally named `user.id` becomes
   unreachable.
2. An exact match against a declared column name wins; only when no column is named by
   the whole string is it parsed as a path.

### Choice

Reading 2. Earlier checkpoints allowed any column name as a key, so a schema with a
literal `user.id` column must keep working; an exact whole-string match is the only rule
that is backwards compatible, and it is still deterministic.

### Risk: 20

Author most likely prefers: path parsing first, unconditionally.

---

## T78: The Hive directory segment name for a nested partition path

### Spec Text

> * `--partition-by attrs["country"]`

> (earlier checkpoint) Emit directory tree inside `--output` using Hive-style segments:
> `<col1>=<val1>/<col2>=<val2>/.../`

### Alternatives

1. `<col>` is the path exactly as given, percent-encoded by the earlier checkpoint's
   segment rule: `attrs%5B%22country%22%5D=US`.
2. `<col>` is the *leaf* of the path: `country=US`, `id=7` for `user.id`.
3. `<col>` is the path with separators sanitised to `_`: `attrs_country=US`.

### Choice

Reading 1 — the partition column *is* the string the user passed, and the existing
encoder already defines what happens to characters outside `[A-Za-z0-9._-]`. Leaf naming
(reading 2) would collide whenever two paths share a leaf name (`a.id` and `b.id`), which
a Hive layout cannot represent. Note `user.id` needs no encoding at all, since `.` is a
safe character, so only bracketed map lookups look noisy.

### Risk: 40

Author most likely prefers: reading 2, the leaf name, because the example
`attrs["country"]` is clearly meant to yield a readable `country=...` tree.

---

## T79: Malformed or out-of-range array indices

### Spec Text

> * Array indices must be non-negative integers
>   * If out of range or element is null/missing → key fragment is null for that row

### Alternatives

1. A negative or non-integer index is rejected up front as a path that cannot resolve →
   `ERR 3` exit 3; an in-range-but-absent element is a null fragment at run time.
2. A negative index is a usage error (exit 2).
3. A negative index silently yields null, like an out-of-range one.

### Choice

Reading 1. "Must be non-negative integers" is a constraint on the path, and the only
error the spec attaches to a bad path is `ERR 3 key column "<path>" does not resolve to a
primitive` with exit 3. Out-of-range (`items.9` on a 2-element array), `null` elements
and missing map keys stay null fragments, exactly as the spec says.

### Risk: 25

Author most likely prefers: exit 3 as well, though exit 2 is plausible since it is an
argument-shaped mistake.

---

## T80: A path that descends into a `json`-typed column

### Spec Text

> * Each path must resolve to a primitive value after casting
>   * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives

1. Static rejection: a `json` column has no declared inner structure, so no path through
   it can be *proved* to reach a primitive → `ERR 3`, exit 3, before reading any data.
2. Dynamic: navigate the actual value per row, using it when it happens to be a
   primitive and nulling the fragment otherwise.

### Choice

Reading 1. "Resolve to a primitive" is checked against the *schema*; that is the only way
the check can be deterministic across inputs (otherwise the same command would succeed or
fail depending on which rows happen to be present). This also makes `--key` on a whole
nested/`json` column error 3, as the Deliverables section requires.

### Risk: 30

Author most likely prefers: the same for whole nested columns; a dynamic per-row reading
for paths that descend into `json` is the plausible variant.

---

## T81: When is "the entire column value null"?

### Spec Text

> * If entire column value is null → emit CSV null literal
> * Otherwise, serialize nested value as canonical JSON

### Alternatives

1. Only a top-level `null` (or a missing/empty cell, or a whole-node cast failure under
   `coerce-null`) produces the CSV null literal. `{}`, `[]`, and a struct whose every
   field ended up `null` still serialize as JSON (`{}`, `[]`, `{"a":null}`).
2. A struct of all-nulls, or an empty container, also counts as "entirely null" and
   collapses to the null literal.

### Choice

Reading 1 — "entire column value is null" means the value *is* JSON null, which is
distinguishable from an object that merely contains nulls; the very next bullet insists
struct fields are emitted even when null, which reading 2 would frequently erase.

### Risk: 15

---

## T82: `keep-string` when the *whole* nested cell fails

### Spec Text

> * `keep-string`: set to original unparsed JSON string or stringified form
> * This JSON is the CSV cell content for nested columns

### Alternatives

1. The cell holds the original text verbatim (e.g. the raw CSV cell `{oops`), not
   wrapped in JSON quotes — matching how `keep-string` behaves for flat columns in
   earlier checkpoints.
2. The cell holds the JSON *encoding* of that string (`"{oops"` with quotes), keeping the
   column's "always canonical JSON" property.

### Choice

Reading 1 for the top-level cell (the earlier checkpoints' `keep-string` contract is
"the cell keeps its original text", and that is what a user diffing inputs expects), and
reading 2 for a failure *inside* a nested value, where the surrounding structure forces
JSON quoting. This is the same rule stated once: the kept string is the original text,
and it is JSON-escaped only when it sits inside a JSON document.

### Risk: 35

Author most likely prefers: JSON-encoding the kept string at the top level too, so the
cell is always valid JSON.

---

## T83: Does a failure inside a nested value poison its ancestors?

### Spec Text

> * On cast failure within nested structures:
>   * `coerce-null`: set field/element to JSON `null`

### Alternatives

1. Only the failing leaf is nulled/kept; ancestors keep their remaining good data.
2. The failure bubbles up and nulls the whole cell.

### Choice

Reading 1 — "set *field/element* to JSON null" names the failing node, not the column.
Under `fail`, of course, the first failure anywhere aborts the run.

### Risk: 10

---

## T84: `--type-alias-file` without `--schema`, and alias-file shape errors

### Spec Text

> * Optional alias file via `--type-alias-file <ALIASES_JSON>`:
> ```json
> { "aliases": { ... } }
> ```

### Alternatives

1. `--type-alias-file` without `--schema` is a usage error (nothing could use it).
2. It is accepted and simply has no effect on an inferred (flat) schema, but is still
   loaded and validated (so a cycle still exits 2).

### Choice

Reading 2 — the flag is documented as optional and independent, the spec never pairs it
with `--schema`, and eager validation (T68) means a cyclic file is still reported. A
missing alias file is an I/O error (exit 1) and a malformed one (not an object, no
`aliases` object, non-string entries) is a usage error (exit 2), matching the exit-2
surface the spec gives the alias file.

### Risk: 25

Author most likely prefers: same acceptance; the malformed-file exit code may be 3.

---

## T85: Nested columns and `--csv-null-literal`, quoting, and CSV mechanics

### Spec Text

> * This JSON is the CSV cell content for nested columns
> * Minified (no spaces), UTF-8, RFC 8259 JSON escaping

### Alternatives

1. The canonical JSON is an ordinary CSV field: it is quoted by the normal
   `QUOTE_MINIMAL` rules (so `{"a":1}` becomes `"{""a"":1}"` with the default
   quotechar), and a null cell uses `--csv-null-literal`.
2. Nested cells bypass CSV quoting.

### Choice

Reading 1 — "This JSON is the CSV cell *content*", i.e. the field value, which the CSV
writer then encodes exactly like any other value containing commas and quotes. Anything
else would produce unparseable CSV.

### Risk: 5

---

## T86: Does a nested column's JSON go through UTF-8 escaping or `\uXXXX` escaping?

### Spec Text

> * Minified (no spaces), UTF-8, RFC 8259 JSON escaping

### Alternatives

1. Non-ASCII characters are emitted literally as UTF-8 (`{"n":"café"}`); only the
   characters RFC 8259 *requires* escaping (`"`, `\`, and C0 controls) are escaped.
2. Non-ASCII is escaped as `\uXXXX` (Python's `json.dumps` default).

### Choice

Reading 1 — the bullet says "UTF-8" and "RFC 8259 escaping" in the same breath, and RFC
8259 requires escapes only for quote, backslash and controls. The output file is UTF-8
throughout, so literal characters round-trip.

### Risk: 20

Author most likely prefers: the same; `ensure_ascii=True` (the Python default) is the
plausible accident.

---

## T87: Duplicate keys within one JSON object for a struct or map

### Spec Text

> * **struct**: ordered list of named fields (names unique within struct)

### Alternatives

1. Last occurrence wins (what every JSON parser does by default).
2. First occurrence wins, mirroring the earlier checkpoint's rule for duplicate *column*
   names in a record.

### Choice

Reading 1, last wins — the value has already been through a JSON parser by the time
casting sees it, and re-implementing a duplicate-preserving parser to get first-wins
would contradict "accept any JSON value" for `json` columns. (The uniqueness sentence
constrains the *schema*, not the data: a struct that declares the same field name twice
is a schema error, exit 3.)

### Risk: 20

---

## T88: Are `date`/`timestamp`-looking strings inside a `json` value normalized?

### Spec Text

> * For `json` type: accept any JSON value without casting; normalize only
> * Timestamps inside nested values normalized to UTC `Z`; `date` stays `YYYY-MM-DD`

### Alternatives

1. Temporal normalization applies only where the *schema declares* `timestamp`/`date`;
   inside a `json` value a string stays exactly as it arrived.
2. Any string that looks temporal is normalized wherever it appears.

### Choice

Reading 1 — "without casting" is explicit, and normalizing by pattern-sniffing would
corrupt strings that merely look like dates. The temporal bullet lives under the rules
for *declared* nested values.

### Risk: 10

---

## T89: Sorting when two rows' key fragments come from different nesting depths

### Spec Text

> * Sorting/partitioning comparisons follow typed ordering and null rules from earlier checkpoints

### Alternatives

1. Nothing changes: a fragment is a cast primitive of the path's declared type, ordered
   by that type, nulls first ascending / last descending, `keep-string` raws after cast
   values, ties broken by input order (stability).
2. Nested paths introduce their own ordering.

### Choice

Reading 1, literally as the bullet says — the extraction produces the same `(rank,
payload)` token the flat case produced, so every earlier ordering rule applies unchanged.

### Risk: 5

---

## T90: Nested inputs *not* selected by the schema

### Spec Text

> * **JSONL**: Accept nested objects/arrays only when schema declares column as nested or `json`
> * Without `--schema`, nested inputs not allowed (error 6)

### Alternatives

1. With `--schema` present, a nested value in a column the schema does not declare at all
   is simply ignored (extra columns are ignored), no error.
2. Any nested value in the input needs a matching nested declaration, even in a column
   that will never be emitted → error 6.

### Choice

Reading 1 — extra input columns have been "ignored" since the schema checkpoint, so a
value that is never read cannot fail. Error 6 stays tied to the *no-schema* case, which
is how both the Input Handling and Schema Inference sections phrase it.

### Risk: 20

Author most likely prefers: the same; strict reading 2 would make many mixed inputs
unusable.
