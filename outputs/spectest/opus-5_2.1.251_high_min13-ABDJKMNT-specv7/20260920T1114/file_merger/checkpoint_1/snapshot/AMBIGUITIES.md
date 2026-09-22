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
