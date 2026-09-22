# Ambiguities

Interpretation decisions taken while implementing `merge_files.py`.
Each entry records the spec text, the readings it allows, the choice made, and
the estimated chance the spec author's own implementation disagrees.

---

## T1. What distinguishes `strict` from `loose` inference

### Spec Text

> - `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`
> - `loose`: prefer numeric/temporal types if all non-null observed values parse; otherwise fall back to `string`; empty strings are treated as nulls and don't affect inference

### Alternatives

1. **Per-file then reconcile (strict) vs. global (loose).** `strict` infers a type for a
   column independently *in each file* and downgrades to `string` when two files disagree;
   `loose` pools every value from every file and picks the best type that fits them all.
   These differ: file A holding `1` and file B holding `2.5` gives `string` under per-file
   reconciliation (int vs. float) but `float` under pooling.
2. **Both global**, with the only difference being the null handling sentence.
   Then `x=1` / `x=2.5` yields `float` in both modes.

### Choice

Alternative 1. The words "conflicting types **across files**" only mean something if a type
is computed per file first; under pooling there is no per-file type to conflict. `loose`'s
wording ("all non-null observed values parse") describes a single pooled pass.

### Risk: 45

The author may have written one shared inference routine whose only mode-dependent branch is
whether empty cells are skipped, making both modes pool values globally.

---

## T2. Do empty cells affect `strict` inference?

### Spec Text

> `loose`: ... empty strings are treated as nulls and don't affect inference

### Alternatives

1. The sentence is a `loose`-only rule, so under `strict` an empty cell is an observed value
   that only parses as `string`, dragging the whole column to `string`.
2. Empty cells are nulls everywhere; the sentence merely restates a global rule.

### Choice

Alternative 1. The sentence sits inside the `loose` bullet and is the only textual contrast
offered for null handling; reading it as global would make it redundant.

### Risk: 40

A single implementation that always skips empty cells (treating "" as missing data
everywhere, as the output rules do) is an easy and defensible thing for the author to have
written; a fixture with a sparse int column would then infer `int` under `strict`, not `string`.

---

## T3. `bool` outranks `int`, so `1`/`0` columns infer as `bool`

### Spec Text

> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> Inference recognises values by the casting rules below
> `bool` includes `1`/`0` along with standard values

### Alternatives

1. Priority is applied literally to the set of types that accept every value in the column,
   so a column of only `1` and `0` becomes `bool` (both parse as bool, int and float; bool wins).
2. Priority only breaks ties between "shape-compatible" types, and a numeric-looking column
   stays `int` unless the values are spelled `true`/`false`.

### Choice

Alternative 1. The spec states one ordering and says inference uses the casting rules; the
casting rules make `1`/`0` valid booleans, so the ordering decides.

### Risk: 45

If the author's inference tries parsers in priority order this falls out automatically, and
the sentence "inference recognises values by the casting rules" reads like it was written to
settle exactly this question. Against that: the rule also turns a lone `id` value of `1` into
`true`, which is jarring enough that the author may have restricted *inference* of `bool` to
the `true`/`false` spellings while `bool` casting still accepts `1`/`0` — that is the reading
they most likely prefer if they disagree.

---

## T4. Does a date-only string count as a `timestamp` during inference?

### Spec Text

> `date`: ISO-8601 `YYYY-MM-DD`
> `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output

### Alternatives

1. `timestamp` requires a time component, so `2024-07-01` is a `date` and never a `timestamp`.
2. `timestamp` accepts any ISO-8601 value including date-only (this is what
   `datetime.fromisoformat` does), in which case priority `timestamp > date` makes *every*
   date column infer as `timestamp` and the `date` type becomes unreachable by inference.

### Choice

Alternative 1. Reading 2 makes the `date` inference type dead code, which cannot be the intent
of a spec that lists `date` as an inferable type.

### Risk: 20

The author would have to special-case `fromisoformat` to get this, but they almost certainly
did, since otherwise their own `date` type could never be inferred.

---

## T5. How is `bool` rendered in the output?

### Spec Text

> `bool` includes `1`/`0` along with standard values
> Cast every input cell into target type

### Alternatives

1. Canonical lowercase `true` / `false`.
2. Python-style `True` / `False` (what `str(bool)` gives).
3. Pass the original text through unchanged.

### Choice

Alternative 1. The output dialect section insists on normalized, deterministic rendering
(explicitly for timestamps), and lowercase `true`/`false` is the conventional CSV/JSON spelling.

### Risk: 50

Nothing in the spec pins the spelling. `str(value)` is the single most likely line of code in
a quick implementation, which would make the author's fixture say `True`/`False`.

---

## T6. How are `float` values rendered?

### Spec Text

> `int`, `float`, `string`: standard parsing
> Cast every input cell into target type (rules below)

### Alternatives

1. Render the parsed number canonically (`repr`), so `1.50` → `1.5` and `1` → `1.0`.
2. Echo the original text once it has been validated as a float.

### Choice

Alternative 1. "Cast every input cell into target type" plus a "deterministic" output dialect
implies the emitted value is the cast value, not the source text; otherwise two files spelling
the same number differently would produce inconsistent output.

### Risk: 40

Only observable for non-canonical spellings (`1.50`, `007`, `1e3`). An author who validates
but passes text through would produce different fixtures for exactly those inputs.

---

## T7. How are `int` values rendered?

### Spec Text

> `int`, `float`, `string`: standard parsing

### Alternatives

1. Canonical decimal form: `007` → `7`, `+5` → `5`.
2. Original text preserved.

### Choice

Alternative 1, for the same reason as T6.

### Risk: 25

Same class of disagreement as T6 but rarer in fixtures, since ints are usually written canonically.

---

## T8. Fractional-second digits in normalized timestamps

### Spec Text

> `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`), keeping fractional seconds

### Alternatives

1. Emit microsecond precision when a fraction is present (`.123` → `.123000`), and no fraction
   when it is zero — the behaviour of `datetime.isoformat()`.
2. Preserve the number of fractional digits present in the source (`.123` → `.123`).

### Choice

Alternative 1. "Keeping fractional seconds" asks that the fraction not be dropped; datetime
round-tripping is the natural mechanism and gives a single canonical width.

### Risk: 35

Both readings agree on 6-digit and zero-fraction inputs. If the author's fixture uses `.123`,
they may well have preserved it by string surgery rather than through `datetime`.

---

## T9. Does `--csv-null-literal` also affect *input* parsing?

### Spec Text

> Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives

1. The literal is symmetric: an input cell equal to it (or empty) reads as null, and nulls are
   written back as it.
2. Output-only: only empty cells are null on input.

### Choice

Alternative 1, with the empty string always also counting as null. Symmetry makes the tool
round-trip its own output, which is the only behaviour that keeps `--csv-null-literal NULL`
usable in a pipeline.

### Risk: 30

The bullet is written from the output side. An author reading it narrowly would emit `NULL`
for empty cells but treat a literal `NULL` in the input as a `string`/cast failure.

---

## T10. Do `--csv-quotechar` / `--csv-escapechar` affect the output dialect?

### Spec Text

> Quote character defaults to `"`; escape character defaults to doubling the quote (`""`) and accepts backslash-escapes (`\"`), overrideable via flags
> **Deterministic Dialect Details** - Output delimiter `,`, quote `"`; escape by doubling quotes

### Alternatives

1. Input-only: the flags describe how inputs are parsed, while output is always `"` + doubling.
2. Both sides: the flags also change how output is quoted/escaped.

### Choice

Alternative 1. The flags are introduced under "Fixed CSV assumptions" (about inputs) and the
output dialect is separately declared fixed and deterministic.

### Risk: 25

An implementation that builds one `csv.Dialect` object and uses it for both reading and
writing would show the override in the output too.

---

## T11. Backslash escapes are honoured by default on input

### Spec Text

> escape character defaults to doubling the quote (`""`) and accepts backslash-escapes (`\"`)

### Alternatives

1. Both escape conventions are active by default (`doublequote=True`, `escapechar='\'`), so
   `\"` yields `"` — and, as a side effect, a lone backslash in data is consumed (`C:\temp` → `C:temp`).
2. Backslash handling only applies to the `\"` pair, leaving other backslashes untouched.

### Choice

Alternative 1. It is what the sentence asks for and what the standard CSV reader does when an
escape character is configured; special-casing only `\"` would require a hand-written parser.

### Risk: 30

A fixture containing a literal backslash that is *not* followed by a quote would expose the
difference, and an author who wrote a custom unescape step would keep such a backslash.

---

## T12. Ordering of `keep-string` fallbacks against successfully cast values

### Spec Text

> `keep-string`: emit original text as string
> Nulls always compare less than non-null values

### Alternatives

1. Uncastable cells kept as text sort after every successfully cast value in that column
   (nulls < cast values < kept strings), which avoids comparing text to numbers.
2. Everything in the column is compared as text once any cell is kept as text.
3. The kept text is compared directly against typed values (raises in most languages).

### Choice

Alternative 1. It keeps the spec's only stated rule (nulls first) intact, is total and
deterministic, and leaves the ordering of well-typed rows unchanged.

### Risk: 35

Only observable when a *key* column has a cast failure under `keep-string`. The author may
instead have degraded the whole column to string comparison, which reorders numeric keys.

---

## T13. Rows that are shorter or longer than their header

### Spec Text

> All inputs are UTF-8, RFC-4180 compliant, with a **header row**
> Missing input columns filled with null literal

### Alternatives

1. Tolerate ragged rows: absent trailing cells read as null, surplus cells ignored, and a
   blank line (which carries no cells at all) skipped rather than emitted as an all-null row.
2. Treat a ragged row as a hard error, or emit a blank line as a row of nulls.

### Choice

Alternative 1. The spec only ever prescribes errors for cast failures under `fail` and for a
missing key column; missing data is filled with the null literal everywhere else.

### Risk: 10

Inputs are declared RFC-4180 compliant, so this should not arise in fixtures at all.

---

## T14. Default for `--memory-limit-mb`

### Spec Text

> `[--memory-limit-mb <INT>]`
> Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs

### Alternatives

1. Default to a concrete budget (64 MB) and always use the spill-capable sort path.
2. Unlimited when the flag is absent.

### Choice

Alternative 1, with 64 MB — the figure the spec itself names as an example.

### Risk: 5

The sorted output is identical either way; only temp-file usage differs, which is not
observable from the CSV.

---

## T15. Exit status for `--on-type-error fail` and other errors

### Spec Text

> `fail`: write error to stderr and exit non-zero

### Alternatives

1. Exit code 1 for every user-facing error.
2. Distinct codes per error class (e.g. 2 for CLI misuse).

### Choice

Alternative 1 for errors raised by the tool itself; argparse keeps its own code 2 for
malformed command lines.

### Risk: 15

The spec only requires "non-zero", so a test would have to assert an exact code to disagree.

---

## T16. Which literals are "standard values" for `bool`

### Spec Text

> `bool` includes `1`/`0` along with standard values

### Alternatives

1. `true`/`false` case-insensitively, plus `1`/`0`.
2. Also `yes`/`no`, `t`/`f`, `y`/`n`, `on`/`off`.

### Choice

Alternative 1. `true`/`false` is the standard boolean spelling in CSV/JSON data; the wider set
is a convention of specific parsers, and admitting it would also change inference results for
columns holding words like `no`.

### Risk: 30

If the author leaned on a permissive helper, a column of `yes`/`no` would cast to bool rather
than failing or inferring as `string`.

---

## T17. "Ascending lexicographic order" of inferred column names

### Spec Text

> Column order: ascending lexicographic order of column names

### Alternatives

1. Plain codepoint ordering (`Z` before `a`).
2. Case-insensitive or locale-aware collation.

### Choice

Alternative 1 — the default ordering of strings in essentially every language, and the only
one that is deterministic without naming a locale.

### Risk: 10

Mixed-case headers in a fixture would be needed to tell these apart.

---

## T18. A `date`-typed schema column fed a value carrying a time

### Spec Text

> `date`: ISO-8601 `YYYY-MM-DD`
> On cast failure, apply `--on-type-error`

### Alternatives

1. `2024-07-01T12:00:00Z` is not `YYYY-MM-DD`, so it is a cast failure and goes through the
   error policy.
2. Truncate the timestamp to its date part.

### Choice

Alternative 1. The spec pins the `date` format exactly and provides an error policy for
everything that does not fit; silent truncation loses data the user did not ask to drop.

### Risk: 15

Truncation requires deliberately parsing a wider grammar for `date`, which the stated format
argues against.

---

## T19. Stability when `--desc` is given

### Spec Text

> Sort must be stable with respect to input appearance for equal keys
> Default order is ascending; `--desc` applies to all keys

### Alternatives

1. `--desc` reverses only the key comparison; rows with equal keys stay in input order.
2. `--desc` reverses the whole result, so equal-key rows appear in reverse input order.

### Choice

Alternative 1. Stability is stated unconditionally, and `--desc` is described as applying to
the *keys*, not to the output as a whole.

### Risk: 20

An implementation that sorts ascending and then reverses the list would produce reading 2;
a fixture with duplicate keys plus `--desc` would catch it.

---

## T20. Inference for a column whose observed values are all null

### Spec Text

> `strict` (default): infer types based on observed values

### Alternatives

1. No non-null observation → `string`.
2. Some other default such as `int` or dropping the column.

### Choice

Alternative 1. `string` is the spec's stated fallback whenever inference cannot commit, and
the column must still appear in the output header.

### Risk: 10

Every value in the column renders as the null literal regardless of the type chosen, so this
is nearly unobservable.

---

# Checkpoint 2 — Multi-Format CSV Merger

## T10 (revised by checkpoint 2)

Checkpoint 2 states "Use configured CSV dialect flags for output quoting/escaping and
chosen null literal", which settles T10 against the choice made there: `--csv-quotechar`
and `--csv-escapechar` now shape the *output* dialect as well as the input one. The
implementation and the test `test_output_dialect_follows_the_configured_quotechar` were
changed accordingly; the original entry is kept for the record.

## T2 (extended by checkpoint 2)

Checkpoint 2 unifies missing data across formats ("If JSONL/Parquet value is `null` or
CSV/TSV cell is empty, treat as missing"), so the T2 choice — a missing value is an
observation that only `string` accepts under `strict`, and is skipped under `loose` — now
applies to JSONL nulls and Parquet nulls too. See T28 for the risk this carries.

---

## T21. The exit-code taxonomy

### Spec Text

> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2
> Mismatch is error 5
> nested fields trigger error 6
> Keys must exist in resolved schema (error 3 otherwise)
> Exact exit codes and stderr message shape as specified

### Alternatives

The spec names 2, 3, 5 and 6 but never lists the whole table, so 1 and 4 are unassigned and
the classes that checkpoint 1 only required to be "non-zero" must be placed somewhere.

1. A full ladder: 1 generic/IO failure, 2 command-line misuse and undetectable format,
   3 schema problems (including a key absent from the resolved schema and an unusable
   `--schema` file), 4 cast failure under `--on-type-error fail`, 5 malformed input or a
   compression mismatch, 6 nested structures.
2. Keep checkpoint 1's flat "everything is 1" and use the named codes only for the four
   conditions the spec spells out.

### Choice

Alternative 1. A spec that hands out 2, 3, 5 and 6 to distinct conditions is quoting from a
table; leaving 4 unused while cast failure — the one error class checkpoint 1 discusses at
length — shares code 1 with a missing file would be an odd table to have written. Argparse
already exits 2 for misuse, which anchors that row.

### Risk: 55

The gaps are guesses. The most likely disagreement is cast failure under `fail`: the author
may exit 1 (or 4 for something else entirely, such as an unreadable input).

---

## T22. The "stderr message shape"

### Spec Text

> Exact exit codes and stderr message shape as specified

### Alternatives

1. Checkpoint 1's shape, carried forward: one line, `merge_files.py: error: <message>`.
2. Some other shape (bare message, `ERROR:` prefix, an error code in the text).

### Choice

Alternative 1 — "as specified" refers back to the earlier checkpoint, and nothing in this one
redefines the shape.

### Risk: 25

A hidden test that pattern-matches the message text rather than merely requiring non-empty
stderr would disagree; most such tests only assert that stderr is non-empty.

---

## T23. `authoritative` precedence between source formats

### Spec Text

> `--schema-strategy=authoritative` (default): prefer typed sources in precedence order; JSONL ranks equal to CSV.

### Alternatives

1. Two tiers: Parquet (the only source with a declared, per-column schema) outranks CSV,
   TSV and JSONL, which are peers. Within the winning tier the reconciliation of checkpoint 1
   applies (`strict` → conflicting per-file types fall back to `string`; `loose` → pooled).
2. A four-way order such as parquet > jsonl > csv > tsv — contradicted by the sentence's
   second half.
3. Parquet > JSONL = CSV > TSV, treating TSV as the least trustworthy text format.

### Choice

Alternative 1. "Typed sources" is the criterion, and the only clarification given is that
JSONL's typing does *not* buy it precedence over CSV; TSV is the same kind of untyped text
as CSV, so it belongs in the same tier. Keeping checkpoint 1's rule inside a tier also makes
`authoritative` + `strict` reproduce checkpoint 1 exactly on CSV-only inputs, which the
"Extend your tool" framing demands.

### Risk: 55

Within-tier conflict resolution is the soft spot: the author may widen conflicting peers to
their common type (as `union` does) instead of falling back to `string`, or may place TSV in
a tier of its own.

---

## T24. What "majority of files support" counts

### Spec Text

> `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives

1. Each file votes with the type it would infer on its own; the type with the most votes wins
   and ties break by the checkpoint 1 type priority.
2. For each candidate type, count the files all of whose values that type accepts, and take
   the highest count. Because every file accepts `string`, the winner is then always a type
   accepted by *every* file — which makes `consensus` indistinguishable from `union`.
3. As 2, but requiring a strict majority (> half) and falling back to `string` otherwise.

### Choice

Alternative 1. It is the only reading under which `consensus` is a distinct strategy from
`union`, and "majority of files" reads as a per-file vote. A file whose values do not fit the
winning type then goes through `--on-type-error`, which the spec provides for exactly this.

### Risk: 50

Reading 3 is also defensible, and differs whenever the plurality type is not supported by a
majority; the author may also have made the losing files' values survive by widening.

---

## T25. "Simplest common type" for `union`

### Spec Text

> `--schema-strategy=union`: choose simplest common type that can hold all observed values

### Alternatives

1. Promotion: the *most specific* type in the priority list that accepts every observed value
   (`int` + `float` → `float`, `int` + `abc` → `string`).
2. Literally the simplest type, which is always `string`.

### Choice

Alternative 1. Reading 2 makes the strategy a no-op that ignores its own "that can hold all
observed values" qualifier; "simplest" is the usual type-promotion sense of "least widening
needed".

### Risk: 20

Only an author who wanted `union` to mean "give up and use text" would disagree, and they
would not have written the qualifier.

---

## T26. How `--infer` and `--schema-strategy` interact

### Spec Text

> Type inference per `--infer` mode (strict or loose)
> **Schema disagreement strategy** when inputs have conflicting types for same column

### Alternatives

1. They compose: `--infer` decides what each file's values are evidence *for* (in particular
   whether missing values count) and how peers inside the authoritative tier reconcile, while
   `--schema-strategy` decides how the per-file evidence is combined across files.
2. `--schema-strategy` replaces `--infer` entirely whenever it is not `authoritative`.

### Choice

Alternative 1. The two flags are described in separate bullets with no statement that one
disables the other, and `--infer`'s null handling has to apply under every strategy for the
modes to keep meaning anything.

### Risk: 35

Under reading 2, `--infer loose` would have no effect together with `consensus` or `union`;
a fixture combining both flags with sparse columns would separate them.

---

## T27. What a typed JSONL/Parquet value contributes to inference

### Spec Text

> JSONL values come typed (string/number/bool/null)
> Parquet values come typed
> Type inference per `--infer` mode

### Alternatives

1. A typed value is evidence for its own kind: a JSON/Parquet boolean is `bool`, an integer is
   `int` (widenable to `float`), a float is `float`, a date/timestamp is itself, and only a
   *string* value is re-examined as text (so a JSON string `"2024-07-01"` can infer `date`).
2. Every value is rendered to text and re-inferred exactly like a CSV cell, which would make
   the JSON integer `1` infer as `bool` (per T3's priority rule).

### Choice

Alternative 1. "Values come typed" is stated precisely to distinguish these sources from the
raw text of CSV/TSV, and it keeps `authoritative`'s preference for typed sources meaningful.
Casting still goes through the canonical text of the value, so an explicit `bool` column in
`--schema` still accepts a JSON `1`.

### Risk: 40

An implementation that funnels everything through one text-based inference routine is simpler
to write; a fixture with a JSONL column of `0`/`1` would expose the difference (`int` here,
`bool` there).

---

## T28. Nulls from typed sources under `strict` inference

### Spec Text

> If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal
> `strict` (default): infer types based on observed values

### Alternatives

1. Missing values are treated uniformly across formats, so T2 carries over: under `strict` a
   null is an observation that only `string` accepts, and under `loose` it is skipped.
2. Only *textual* emptiness is an observation; an explicit JSON/Parquet `null` carries no type
   information and is skipped in both modes.

### Choice

Alternative 1. The spec's own sentence puts JSONL/Parquet nulls and empty CSV cells in one
bucket ("treat as missing"), so splitting them for inference would need a rule the spec does
not give.

### Risk: 45

Reading 2 is the more natural behaviour for a typed source — a nullable Parquet `int64` column
is still an `int` column — and is what the author most likely implemented if their Parquet
inference consults the Arrow schema rather than the values.

---

## T29. Which direction of compression mismatch is error 5

### Spec Text

> `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> Mismatch is error 5

### Alternatives

1. Both directions are checked against the file's magic bytes: forcing `gzip` on plain bytes
   and forcing `none` on gzip bytes are both error 5.
2. Only the first direction: "forces no decompression" means `none` reads the raw bytes
   whatever they are, and the resulting garbage fails later (or is read as data).

### Choice

Alternative 1. "Mismatch" is symmetric, and a deterministic, named error beats handing a
DEFLATE stream to the CSV reader.

### Risk: 35

`--compression=none` is worded as a *force*, so the author may have let it through; their
fixture would then be a garbled parse error rather than exit 5.

---

## T30. JSONL lines that are not objects

### Spec Text

> **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects as values)
> Flat-only enforcement for JSONL/Parquet; nested structures trigger error 6

### Alternatives

1. Split by cause: a line that is not valid JSON, or is valid but is a scalar, violates "one
   JSON object per line" and is malformed input → error 5; a *nested* structure (an array or
   object appearing as a value, or a whole line that is an array) is error 6.
2. Everything that is not a flat object is error 6.
3. Everything that is not a flat object is error 5.

### Choice

Alternative 1. Error 6 is introduced as the flat-only code, so it should track nesting; a
truncated or non-JSON line is a different failure and belongs with the other malformed-input
conditions.

### Risk: 40

The boundary cases (a bare scalar line, a top-level array) are unlikely to appear in fixtures
in more than one shape, but if they do, the author may route them all to 5 or all to 6.

---

## T31. TSV rows that do not match the header width

### Spec Text

> **TSV**: delimiter is tab (`\t`), no quoting, header row required ... literal tabs inside field not allowed (error 5)

### Alternatives

1. A literal tab in a field is observable only as a row with more fields than the header, so
   that is what error 5 is raised for; a short row keeps checkpoint 1's tolerance and fills
   its missing columns with nulls; a file with no header line at all is error 5.
2. Any width mismatch (short rows included) is error 5.
3. Width mismatches are tolerated in both directions and error 5 is unreachable.

### Choice

Alternative 1. It is the only way an unquotable delimiter can be detected at all, and it keeps
the checkpoint 1 treatment of ragged rows (T13) for the case the new sentence does not cover.

### Risk: 35

An author who validates TSV rows strictly would also reject short rows; one who does not
validate at all would silently drop the surplus field.

---

## T32. When Parquet nesting is detected

### Spec Text

> **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6

### Alternatives

1. The file's schema is checked when it is opened, so a nested column is rejected even if the
   file has no rows and even if that column is not in the output schema.
2. Only values actually read are checked.

### Choice

Alternative 1 — the spec says "flat *schemas* only", and schema resolution reads the file's
field names before any row is used.

### Risk: 15

Only an empty or column-filtered fixture could tell the readings apart.

---

## T33. Default and meaning of `--parquet-row-group-bytes`

### Spec Text

> Parquet reading must be streamed row group–wise; `--parquet-row-group-bytes` is advisory for batch sizing

### Alternatives

1. A byte budget per batch, converted to a row count from the file's own average row size,
   defaulting to 8 MiB.
2. Some other default (64 MiB, or the file's row-group size).

### Choice

Alternative 1. "Advisory" and "batch sizing" say the number only steers how many rows are
pulled at a time; 8 MiB sits comfortably inside the 64 MB memory floor the spec insists on.

### Risk: 10

The flag is explicitly advisory, so no output can depend on it.

---

## T34. What "write atomically" means

### Spec Text

> `--output -` writes to stdout; otherwise write atomically

### Alternatives

1. Write to a temporary file in the destination's directory and `os.replace` it into place, so
   the destination is either the old file or the complete new one and a failed run leaves no
   partial output.
2. Write in place and merely `flush`/`fsync` at the end.

### Choice

Alternative 1 — the standard meaning of an atomic file write, and the only one that survives
an error partway through the row stream.

### Risk: 10

Observable only through a failing run's leftovers or a concurrent reader.

---

## T35. Does `--csv-null-literal` apply to typed sources?

### Spec Text

> If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal

### Alternatives

1. Typed sources mark missing data with a real `null`; a JSONL/Parquet *string* that happens to
   equal the null literal (`"NULL"`) is ordinary data. The literal keeps its checkpoint 1
   double role (T9) only for CSV/TSV text.
2. The literal is recognised in every source.

### Choice

Alternative 1. The sentence names the missing-value condition for each source separately, and
a typed source has no need of a sentinel spelling.

### Risk: 30

Reading 2 is what an implementation that normalises everything to text before applying the
null rule would do — a plausible shortcut.

---

## T36. `--csv-escapechar` on the output side

### Spec Text

> Use configured CSV dialect flags for output quoting/escaping and chosen null literal

### Alternatives

1. The output writer takes the configured quote character and escape character but keeps
   checkpoint 1's "escape by doubling", so the escape character only appears where doubling
   cannot be used.
2. The escape character replaces doubling on output, so `"` inside a quoted field is written
   `\"`.

### Choice

Alternative 1. Checkpoint 1 fixes doubling as the escape convention and describes the escape
character as an additional accepted form on input; carrying doubling over keeps the tool's own
output readable by its own reader under the default flags.

### Risk: 30

An author who builds a single `csv.Dialect` with `doublequote=False` when `--csv-escapechar`
is given would emit backslash escapes instead.

---

## T37. Column discovery for schema-less sources

### Spec Text

> Column set: union of all encountered field names

### Alternatives

1. "Encountered" is literal for JSONL — the union of the keys of every line, which requires
   reading each file once before writing — while CSV/TSV contribute their header and Parquet
   its schema, so those two contribute columns even when they hold no rows.
2. Only the first record of a JSONL file defines its columns.

### Choice

Alternative 1. "All encountered field names" is unambiguous about pooling every line, and the
inference pass already visits every row.

### Risk: 15

Reading 2 is cheaper but would drop columns that appear only in later lines, which the wording
does not allow.

---

## T38. What makes an extension "ambiguous"

### Spec Text

> `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

### Alternatives

1. A recognised extension decides on its own (magic bytes are never consulted for it); any
   other name — `data.dat`, `part-00000`, a bare `data.gz` — is ambiguous and falls back to the
   Parquet magic check, then to error 2.
2. Magic bytes are always consulted and override the extension, so `data.csv` holding Parquet
   bytes is read as Parquet.

### Choice

Alternative 1. The mapping is stated unconditionally and the magic-byte rule is guarded by "if
extension is ambiguous", which only makes sense if a known extension short-circuits it. A
trailing `.gz` is stripped before the extension is read whatever `--compression` says, so
`--compression none data.csv.gz` still reads CSV.

### Risk: 20

A fixture with a deliberately mislabelled `.csv` Parquet file would separate the readings.

---

## T39. Publishing into an `--output` directory that already exists

### Spec Text

> - Create directory if doesn't exist
> - Perform atomic write by creating sibling temp directory and renaming on success

### Alternatives

1. **Merge into it.** The staging directory is renamed into place when the target is
   absent; when it already exists, each staged entry is moved in, replacing a file of the
   same name and recursing into a partition directory of the same name. Unrelated content
   that was already there survives.
2. **Replace it wholesale.** Delete the existing tree, then rename the staging directory
   over it, so the output directory holds exactly this run's files and nothing else.

### Choice

Alternative 1. The spec only promises to create the directory when it is missing and never
says an existing one is discarded; deleting a tree the user named is not something the
prose asks for, and a rename onto an absent target still gives the atomic case the spec
describes. Files this run produces win over same-named files already present.

### Risk: 40

`shutil.rmtree(target); os.rename(tmp, target)` is the shortest way to make "renaming on
success" work against an existing directory, so the author most likely replaces the
directory wholesale, leaving no stale parts from an earlier run.

---

## T40. What a run with no rows writes in directory mode

### Spec Text

> Within each partition directory, write CSV files named sequentially: `part-00000.csv` …
> Each file contains header row (resolved schema header)

### Alternatives

1. Part files exist only where rows do: an input with no data rows creates the output
   directory and nothing inside it, whether or not `--partition-by` was given.
2. The sharded stream always has at least one file, so with no field partitioning an empty
   input still yields `part-00000.csv` holding just the header (a field-partitioned run
   would still write nothing, there being no partitions).

### Choice

Alternative 1. A part file belongs to a partition and a partition exists because rows fall
in it; the same rule then covers both layouts, and no name is invented for rows that do not
exist.

### Risk: 40

For the no-field-partition case the author may have kept the checkpoint-1 habit of always
emitting a header, in which case an empty input gives a header-only `part-00000.csv`.

---

## T41. Whether partition columns stay in the part-file CSVs

### Spec Text

> - Every output CSV includes header row in resolved schema column order
> - Values derived after casting to resolved schema types

### Alternatives

1. Every part file carries the full resolved schema, partition columns included, so the
   value appears both in the directory name and in each row.
2. Hive's own convention: the partition columns are dropped from the files because the path
   already carries them.

### Choice

Alternative 1. "Every output CSV includes header row in resolved schema column order" is
unconditional, and nothing in the section removes columns; a reader of one part file in
isolation then still sees the complete schema.

### Risk: 15

Only an author following Hive semantics past the spec's own sentence would drop them.

---

## T42. Exit codes when `--output` cannot be a directory

### Spec Text

> When any partitioning flag provided: `--output` must be directory path (not `-`)

### Alternatives

1. The two failures are different classes: `--output -` together with a partitioning flag
   is command-line misuse (exit 2, the checkpoint-1 code for a bad invocation), while a
   path that exists as a regular file is an output that cannot be written (exit 1).
2. Both are misuse, exit 2, since both violate the same sentence.
3. Both are output failures, exit 1.

### Choice

Alternative 1. Whether `-` was passed is decided from the command line alone, which is what
exit 2 covers in this tool; whether the path happens to hold a file is a property of the
filesystem, which is what exit 1 covers. Both are reported in the usual
`merge_files.py: error: …` shape.

### Risk: 35

An author who validates both in one place when parsing arguments would return exit 2 for the
existing-file case as well.

---

## T43. Whether part numbering restarts in each partition

### Spec Text

> File naming (with field partitioning): same `part-xxxxx.csv` sequence per partition directory

### Alternatives

1. "Per partition directory" means each directory owns a sequence that starts at
   `part-00000.csv`.
2. One counter runs across the whole output, so the second partition's first file might be
   `part-00007.csv`.

### Choice

Alternative 1. "Sequence per partition directory" reads as one sequence for each directory,
and a per-directory counter is also what makes the layout reproducible regardless of which
partition is written first.

### Risk: 12

A global counter would make file names depend on partition write order, which the
determinism checklist argues against.

---

## T44. Exactly which characters percent-encoding touches

### Spec Text

> Values use percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`

### Alternatives

1. The set is read literally: every character that is not an ASCII letter, digit, `.`, `_`
   or `-` becomes one `%XX` group per UTF-8 byte, in upper-case hex — so `~` → `%7E`,
   `=` → `%3D`, `%` → `%25`, `é` → `%C3%A9`. Column names are left alone, the spec only
   speaking of values.
2. `urllib.parse.quote(value, safe="")`, which matches that set except that it never encodes
   `~`, RFC 3986 counting it as unreserved.

### Choice

Alternative 1. The spec gives the safe set explicitly and `~` is not in it; `%2F` for `/`
confirms upper-case hex, and per-byte encoding is what "percent-encoding of UTF-8 bytes"
says.

### Risk: 20

`quote(value, safe="")` is the obvious one-liner, so a value containing `~` would come out
unencoded in the author's tree; nothing else separates the two readings.

---

## T45. What counts as a null partition value

### Spec Text

> - Values derived after casting to resolved schema types
> - Null (missing) partition values use literal `_null`

### Alternatives

1. A partition value is null exactly when the cell the row would print is null: the field is
   absent, the cell is empty or the configured null literal, or `--on-type-error coerce-null`
   turned a bad cast into a null. Under `keep-string` the kept text is the value.
2. Only a genuinely absent field is `_null`; an empty string is a value in its own right and
   gives the segment `<col>=`.

### Choice

Alternative 1. The parenthesis equates "null" with "missing", and checkpoint 1 already
treats an empty cell as a missing value on both the input and the output side, so the two
should not disagree here. Deriving the segment "after casting" also means a cast that
produced a null produces `_null`.

### Risk: 35

An author who reads the partition value straight from the record before the null rules are
applied would emit an empty segment for an empty cell.

---

## T46. Byte accounting for `--max-bytes-per-file`

### Spec Text

> `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file (including header and line endings) is ≤ INT

### Alternatives

1. Bytes are counted as the file is written: the UTF-8 encoding of the header line plus each
   rendered row including its `\n`, which is exactly the size the file ends with. A row that
   does not fit in a file already holding the header alone is written anyway, so the
   oversize exception applies to header-plus-row, not to the row in isolation. A limit below
   1 is command-line misuse rather than a file per row.
2. Characters rather than bytes, which understates multi-byte values.

### Choice

Alternative 1. "On-disk byte size … including header and line endings" names the whole file
as it lands, so the header counts against the limit of every part and multi-byte characters
count as their encoded length.

### Risk: 25

A stricter reading of the exception — a file whose header plus first row exceeds INT is
allowed only if the row alone does — gives the same files here; the likelier divergence is
an author who accepts `0` or a negative limit instead of rejecting it.
