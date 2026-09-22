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

> **Resolved by checkpoint 2.** The multi-format spec states "Use configured CSV
> dialect flags for output quoting/escaping and chosen null literal", which selects
> alternative 2. The writer now takes `--csv-quotechar`/`--csv-escapechar`; the
> checkpoint-1 tests that asserted a fixed output dialect were updated to match.

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

## T18 — The exit-code scheme

### Spec Text
> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2
> Mismatch is error 5
> literal tabs inside field not allowed (error 5)
> nested fields trigger error 6
> Keys must exist in resolved schema (error 3 otherwise)
> Exact exit codes and stderr message shape as specified

### Alternatives
1. The spec names 2, 3, 5 and 6, so the author's scheme has at least six codes.
   Fill the gaps as `1` = generic/I/O/schema-document error and `4` = cast failure
   under `--on-type-error=fail`, the one other fatal condition checkpoint 1 defines.
2. Fill the gaps the other way round (`1` = cast failure, `4` = generic), or keep
   every unnamed error at `1`.

### Choice
Alternative 1. The named codes are ordered roughly by pipeline stage — detection (2),
schema/key resolution (3), input decoding (5), unsupported structure (6) — which
leaves 4 sitting between key resolution and decoding, exactly where casting lives.
`1` stays the catch-all, as in checkpoint 1. Argparse's own usage exit stays `2`;
a malformed command line and an undetectable format are both "the invocation names
something I cannot read", so the collision is harmless.

### Risk: 45
Author most likely prefers: `1` for cast failures under `fail` (unchanged from
checkpoint 1, where only "non-zero" was required), leaving 4 unused.

## T19 — The precedence order of "typed sources"

### Spec Text
> `--schema-strategy=authoritative` (default): prefer typed sources in precedence order

### Alternatives
1. Format precedence: parquet > jsonl > csv/tsv. Parquet carries a declared physical
   schema, JSONL carries per-value JSON types, delimited text carries none.
2. Command-line precedence: the first (or last) input that has the column wins,
   "typed sources" merely meaning that such sources are preferred over text ones.
3. Two tiers only: any typed source (parquet or jsonl) outranks any text source, with
   parquet and jsonl treated as equals.

### Choice
Alternative 1. "Precedence order" implies a fixed ranking the author had in mind, and
the only ranking the spec itself supplies is the order in which it introduces and
describes the formats' type fidelity. Within the winning tier the files are combined
with the `--infer` rule, so equal-precedence disagreement still degrades to `string`.

### Risk: 55
Author most likely prefers: alternative 3 — parquet and jsonl pooled as one "typed"
tier, which differs from this choice whenever a parquet and a jsonl file disagree.

## T20 — How `--infer` and `--schema-strategy` interact

### Spec Text
> Type inference per `--infer` mode (strict or loose)
> **Schema disagreement strategy** when inputs have conflicting types for same column

### Alternatives
1. They compose on different axes: `--infer` decides what a single file's values
   say, `--schema-strategy` decides how disagreeing files are reconciled. Under the
   default `authoritative`, `--infer` also settles disagreement inside the winning
   precedence tier, which keeps checkpoint-1 behaviour exact for all-CSV inputs.
2. `--schema-strategy` supersedes `--infer` entirely once inputs disagree, so
   `--infer` only matters for single-source runs.

### Choice
Alternative 1. Checkpoint 1 defined `strict`/`loose` as cross-file rules, and this
checkpoint must stay backward compatible for CSV-only inputs: with the default
`authoritative` strategy every CSV file sits in one tier, so `strict` still means
"all files must agree or fall back to `string`" and `loose` still means "intersect
every observed value's candidate types". `consensus` and `union` define their own
cross-file rules and therefore ignore `--infer`.

### Risk: 40
Author most likely prefers: alternative 2 if their resolver dispatches on strategy
first and never consults `--infer` for multi-file columns.

## T21 — What "majority of files support" means under `consensus`

### Spec Text
> `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives
1. Support-counting: a file supports type `T` when every non-null value it has for
   the column casts to `T`. Choose the highest-priority `T` supported by strictly
   more than half of the files that have the column.
2. Vote-counting: each file resolves one type, and the type with the most votes wins
   (plurality, not majority), ties broken by type priority.

### Choice
Alternative 1, which is what the sentence literally says — "support", not "infer"
— and it always has an answer because every file supports `string`. It also behaves
better on the natural fixture: two `int` files and two `float` files give `float`
(all four support it) rather than a coin-flip tie.

### Risk: 50
Author most likely prefers: alternative 2, since counting one inferred type per file
is the easier thing to build and "majority" is often written loosely for "plurality".

## T22 — What "simplest common type" means under `union`

### Spec Text
> `--schema-strategy=union`: choose simplest common type that can hold all observed values

### Alternatives
1. Narrowest type that holds every observed value: intersect the candidate types of
   all non-null values across all files and resolve by the checkpoint-1 priority
   order, so `int` + `float` gives `float` and `int` + `"abc"` gives `string`.
2. "Union" as in "always widen to the join of the declared types", which for any
   disagreement at all collapses to `string`.

### Choice
Alternative 1. "Can hold all observed values" is a per-value test, not a per-type
join, and "simplest" selects the narrowest survivor rather than the most general.
This makes `union` the strategy that widens numerics instead of giving up on them,
which is the only reading under which it differs usefully from `authoritative`.

### Risk: 30
Author most likely prefers: alternative 1 as well; residual risk is over `bool`,
where priority places `bool` above `int` so a `true`/`1` mix resolves to `bool`.

## T23 — What counts as a compression "mismatch"

### Spec Text
> `--compression=auto` (default): detect `.gz` → gzip; otherwise none
> `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> Mismatch is error 5

### Alternatives
1. The effective compression is always checked against the file's leading magic
   bytes, in every mode and both directions: gzip expected but absent, or gzip
   present but not expected, is error 5.
2. Only an explicit `--compression=gzip` over a non-gzip file is a mismatch;
   `none` genuinely "forces no decompression" and reading gzip bytes as text is the
   user's problem.
3. Mismatch means only the name-versus-flag disagreement (`--compression=none` with
   a `.gz` file), independent of the bytes.

### Choice
Alternative 1. The sentence follows the whole detection paragraph rather than just
the `gzip` clause, so it reads as "whatever compression we settled on must match the
file". It also converts every silent-garbage path into a precise error.

### Risk: 40
Author most likely prefers: alternative 2 — a check written only where gzip
decompression fails, leaving a gzip-magic file read as raw text undiagnosed.

## T24 — When is an extension "ambiguous"?

### Spec Text
> `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
> For gzip, allow `.gz` suffix after base extension
> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

### Alternatives
1. Ambiguous = the base extension (after stripping one `.gz`) is not one of the five
   known suffixes, including the no-extension case. Recognised extensions are never
   second-guessed, so a `.csv` file holding Parquet bytes is still read as CSV.
2. Ambiguous = magic bytes always win, and the extension is only a hint.

### Choice
Alternative 1. The mapping list is stated as a decision, with the magic-byte rule
introduced as the fallback for what it does not cover. The `PAR1` probe reads the
stream after decompression, so `blob.gz` containing gzipped Parquet is detected too.

### Risk: 25
Author most likely prefers: alternative 1; residual risk is over whether the author
also probes magic bytes for a recognised-but-wrong extension.

## T25 — Detecting a "literal tab inside a field" in TSV

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line
> endings; literal tabs inside field not allowed (error 5)

### Alternatives
1. A stray tab is unobservable except as an arity change, so a data row with more
   fields than the header is error 5. Rows with fewer fields keep the checkpoint-1
   behaviour (missing trailing columns become null).
2. Any arity difference at all, short or long, is error 5.
3. Undetectable in principle: accept everything and just document the assumption.

### Choice
Alternative 1. It is the only detection a tab-delimited reader can actually perform,
and it stays consistent with the CSV reader, which already tolerates short rows.
"Header row required" is enforced as: an empty TSV file (no header line) is error 5.

### Risk: 45
Author most likely prefers: alternative 2 — one `len(fields) != len(header)` check
covering both directions is the shorter thing to write.

## T26 — Malformed JSONL lines that are not nested values

### Spec Text
> **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects
> as values); `null` permitted; keys case-sensitive; blank/whitespace lines ignored
> Flat-only enforcement for JSONL/Parquet; nested structures trigger error 6

### Alternatives
1. Split by cause: unparseable JSON, or a valid JSON document that is not an object
   (`[1,2]`, `"x"`, `7`), is a decoding failure → error 5; an object with an array or
   object *value* is a nested structure → error 6.
2. Everything that is not a flat object is error 6, including syntax errors.

### Choice
Alternative 1. Error 6 is introduced specifically as the "nested structures" code and
error 5 is the code the spec already uses for a source violating its dialect rules
(the TSV tab case), so a broken line belongs with the dialect violations.

### Risk: 40
Author most likely prefers: alternative 1 for syntax errors, with a real chance they
map a top-level JSON array to error 6 since an array is itself a nested structure.

## T27 — What a typed value contributes to inference

### Spec Text
> JSONL values come typed (string/number/bool/null)
> Parquet values come typed
> For JSONL numbers, prefer `int` if integer and within range; otherwise `float`

### Alternatives
1. A typed value supports its own type plus the types it can be cast into without
   loss: JSON `true` → {bool, string}; `5` and `5.0` → {int, float, string};
   `5.5` → {float, string}; a Parquet date → {date, string}; a timestamp →
   {timestamp, string}. JSON *strings* are probed as text, exactly like a CSV cell,
   so `"2024-07-01"` in JSONL still supports `date`.
2. A typed value supports only its own type, so a JSON string never infers as
   temporal and a mixed CSV/JSONL date column always resolves to `string`.

### Choice
Alternative 1. The spec's whole point is reconciling formats, which requires a common
vocabulary; probing JSON strings as text is what lets a CSV `2024-07-01` and a JSONL
`"2024-07-01"` agree on `date`. Numbers deliberately do *not* offer `bool`, since
JSON has a real boolean type — unlike CSV, where `1`/`0` is the only way to spell one
(see [T5](#t5--01-columns-infer-as-bool)). "Within range" is read as int64.

### Risk: 45
Author most likely prefers: alternative 2 for JSON strings — mapping the JSON type
straight onto a schema type is the obvious implementation, and it changes the result
for any date/timestamp column that mixes JSONL with CSV.

## T28 — Casting an already-typed value into a different schema type

### Spec Text
> Apply target output schema cast rules to every cell
> If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal

### Alternatives
1. Mirror the text cast rules: `bool` ↔ `int`/`float` (`0`/`1`) convert, a `float`
   with a fractional part fails an `int` column, a `date` widens to midnight UTC in a
   `timestamp` column, a `timestamp` *fails* a `date` column (the text parser rejects
   date-with-time too), and any value renders into a `string` column.
2. Round-trip through text: render the value and run the checkpoint-1 string parser.
3. Reject every cross-family cast so only exact type matches survive.

### Choice
Alternative 1. It keeps a typed source and its text equivalent behaving identically,
which is the property the rest of the spec is built on. Alternative 2 would differ
only in corner cases but would make `float` → `int` depend on the repr.

### Risk: 35
Author most likely prefers: alternative 2 (stringify then reuse one cast path), which
agrees with this choice except for oddities such as `1e16` or a truncating
`timestamp` → `date`.

## T29 — What "write atomically" requires

### Spec Text
> `--output -` writes to stdout; otherwise write atomically

### Alternatives
1. Write to a temporary file in the destination's own directory, then `os.replace`
   onto the destination, so a reader sees either the old file or the complete new
   one, and a failed run leaves no partial output.
2. Write in place and merely `flush`/`fsync` at the end.

### Choice
Alternative 1, the standard meaning. Same-directory placement keeps the rename on one
filesystem; the temporary file is removed if the run fails.

### Risk: 10
Author most likely prefers: the same. Only observable difference is whether a failed
run leaves a partial file behind.

## T30 — `--parquet-row-group-bytes` semantics and default

### Spec Text
> Parquet reading must be streamed row group–wise; `--parquet-row-group-bytes` is
> advisory for batch sizing

### Alternatives
1. Advisory target in bytes for one in-memory batch: divide it by the file's average
   uncompressed row size (from Parquet metadata) to get a batch row count, clamped to
   at least one row. Default 8 MiB, and never more than the memory budget allows.
2. A row-group *size* used only when writing, hence inert on the read path.

### Choice
Alternative 1, since the spec says "for batch sizing" on the reading side. The flag
is explicitly advisory, so it changes only memory profile, never output.

### Risk: 10
Author most likely prefers: any of these; no output is observable either way, so only
a test asserting the flag is accepted matters.

## T31 — Do the CSV dialect flags apply to TSV inputs?

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required
> `[--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>]`

### Alternatives
1. No. The flags are named `--csv-*` and TSV is defined as having "no quoting", so a
   `"` in a TSV field is a literal character. They still shape the CSV *output*.
2. Yes, the flags configure every delimited reader.

### Choice
Alternative 1. "No quoting" is stated as part of the TSV dialect, not as a default to
be overridden, so the TSV reader splits on tabs and nothing else.

### Risk: 20
Author most likely prefers: the same; the residual risk is a shared dialect object
that quietly carries the quote character into the TSV reader.

## T32 — Column set contributed by a source with no rows

### Spec Text
> Column set: union of all encountered field names

### Alternatives
1. "Encountered" includes names a source declares without populating: a CSV/TSV
   header row and a Parquet file's schema contribute their columns even with zero
   data rows, while JSONL — which has no declaration — contributes only keys that
   actually appear on some line.
2. Only names that appear in an actual row count, so a header-only CSV contributes
   nothing.

### Choice
Alternative 1, which preserves the checkpoint-1 behaviour that a header-only CSV
still produces its header in the output. Such a column has no observed values, so it
resolves to `string` per [T14](#t14--columns-with-no-non-null-observed-values).

### Risk: 15
Author most likely prefers: the same for CSV/TSV; slight risk that a Parquet file's
unused columns are handled differently.

## T33 — The stderr message shape

### Spec Text
> Exact exit codes and stderr message shape as specified

### Alternatives
1. Keep checkpoint 1's shape: a single line `merge_files.py: <message>`, where the
   message names the offending input and, where relevant, its line or row.
2. Some other shape the spec never actually states (e.g. `ERROR <code>: ...`).

### Choice
Alternative 1. No message shape is specified anywhere in either checkpoint, so the
only defensible reading is "stay consistent with what the tool already emits".

### Risk: 20
Author most likely prefers: any shape; a hidden test most likely asserts the exit
code plus a non-empty stderr, since no literal text is given to match.
