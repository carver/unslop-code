# AMBIGUITIES

Numbered record of under-specified points in the spec, the interpretation chosen for
this implementation, and the risk that the spec author's own implementation (and the
hidden tests written against it) reads them differently.

---

## T1. What distinguishes `--infer strict` from `--infer loose`

### Spec Text
> - `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`
> - `loose`: prefer numeric/temporal types if all non-null observed values parse; otherwise fall back to `string`; empty strings are treated as nulls and don't affect inference

### Alternatives
1. **Per-file typing + empties are values (chosen).** `strict` infers one type per
   (file, column) from that file's cells; a null/empty cell is an observed value that
   only `string` can hold, so it forces that file's column to `string`. If the per-file
   types are not all identical the column falls back to `string`. `loose` pools all
   cells from all files, ignores nulls/empties, and picks the highest-priority type that
   every remaining value parses as.
2. **Both modes ignore empties; strict differs only by requiring exact cross-file type
   equality** (e.g. file A `int` + file B `float` -> `string` in strict, `float` in loose).
3. **The two modes are effectively identical** (both pool values and ignore empties),
   the prose merely describing the same algorithm twice.

### Choice
Alternative 1. The only textual difference between the two bullets is null handling:
`loose` says "all **non-null** observed values" and then redundantly re-states that
"empty strings are treated as nulls and don't affect inference". That clarification is
only meaningful if it does *not* hold for `strict`. The per-file framing likewise comes
straight from strict's "conflicting types **across files**", which presupposes a type per
file. Note that a column simply *absent* from a file is a missing column, not an observed
empty value (see T11), so this reading does not degrade the common merge case.
Under this reading both stated differences of alternative 2 are also preserved.

### Risk: 40
Most likely author preference: `strict` also skips empty cells, differing from `loose`
only in cross-file conflict handling.

---

## T2. Meaning of the type-priority list, especially `int` > `float`

### Spec Text
> - Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`

### Alternatives
1. **Candidate selection (chosen):** when several types can hold every observed value,
   pick the highest-priority one. `1,2,3` -> `int`; `1,2.5` -> `float` (int fails on
   `2.5`); `true,false` -> `bool`; `1,0` -> `bool` (bool outranks int).
2. **Widening/promotion order:** the list is a lattice for merging two conflicting types
   (int + float -> the higher of the two, i.e. `int`), which would coerce `2.5` to null.

### Choice
Alternative 1. It is the only reading that produces sane results for mixed
integer/decimal columns, and it matches the way the list is worded (a ranking, not a
merge table). The list is printed in the `--schema` section but is only meaningful for
inference, so it is applied there.

### Risk: 20
Most likely author preference: same selection rule, but `1`/`0` columns inferred as
`int` rather than `bool` despite bool's higher priority.

---

## T3. Do date-only strings count as timestamps?

### Spec Text
> - `date`: ISO-8601 `YYYY-MM-DD`
> - `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output

### Alternatives
1. **(chosen)** For *inference*, a value is a `timestamp` candidate only if it carries a
   time component; `2024-07-01` is a `date` candidate only. For *casting* into a declared
   `timestamp` column, a date-only value is accepted and becomes `2024-07-01T00:00:00Z`.
2. Date-only strings are valid ISO-8601 timestamps everywhere, so any date column infers
   as `timestamp` (priority `timestamp` > `date`) and is emitted with `T00:00:00Z`.
3. Date-only strings are rejected by the timestamp caster, so a declared `timestamp`
   column containing `2024-07-01` triggers `--on-type-error`.

### Choice
Alternative 1. Under alternative 2 the `date` type could never be inferred at all, which
would make its presence in the priority list pointless. Casting is kept permissive
because a declared schema is an explicit user assertion about the column.

### Risk: 30
Most likely author preference: alternative 3 - date-only text rejected when cast into a
declared `timestamp` column.

---

## T4. Which literals parse as `bool`

### Spec Text
> - `bool` includes `1`/`0` along with standard values

### Alternatives
1. **(chosen)** `true`, `false`, `1`, `0`, case-insensitive.
2. Also `yes`/`no`, `t`/`f`, `y`/`n`, `on`/`off`.

### Choice
Alternative 1. "standard values" most plainly means the boolean literals `true`/`false`;
a wider set would make ordinary short string columns (a `y`/`n` flag, a `t` column of
initials) infer as bool.

### Risk: 25
Most likely author preference: additionally accepting `yes`/`no` and `t`/`f`.

---

## T5. Output representation of a `bool` cell

### Spec Text
> - Cast every input cell into target type (rules below)
> ...
> **Deterministic Dialect Details** ... Temporal outputs: ...

### Alternatives
1. **(chosen)** Normalized lowercase `true` / `false`.
2. Python's `str(bool)`: `True` / `False`.
3. Original input text preserved (`1` stays `1`, `TRUE` stays `TRUE`).

### Choice
Alternative 1. The dialect section normalizes temporal output but is silent on bool;
since casting is mandatory for every cell, a canonical form is expected, and lowercase
`true`/`false` is the conventional CSV/JSON spelling.

### Risk: 45
Most likely author preference: alternative 2, `True`/`False` from a bare Python
`str(value)` in the writer.

---

## T6. Output representation of a `float` cell

### Spec Text
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. **(chosen)** Round-trip repr of the parsed float: `1.50` -> `1.5`, `3` -> `3.0`,
   `1e3` -> `1000.0`.
2. Original text preserved verbatim after a successful parse.
3. Fixed decimal formatting (e.g. `%g` or a fixed precision).

### Choice
Alternative 1. "Cast every input cell into target type" implies the value, not the
lexeme, survives; `str(float(x))` is the natural Python realization of "standard parsing"
and is deterministic.

### Risk: 40
Most likely author preference: alternative 2, echoing the original text for values that
parsed cleanly.

---

## T7. Output representation of an `int` cell

### Spec Text
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. **(chosen)** `str(int(x))`: `007` -> `7`, `+5` -> `5`, `-0` -> `0`.
2. Original text preserved.

### Choice
Alternative 1, for the same reason as T6. Accepted int syntax is restricted to
`[+-]?digits` (no underscores, no surrounding whitespace, no `5.0`).

### Risk: 20
Most likely author preference: same normalization, but with `int(x.strip())` so that
padded cells like ` 7 ` also parse.

---

## T8. Do `--csv-quotechar` / `--csv-escapechar` affect the output dialect?

### Spec Text
> - Quote character defaults to `"`; escape character defaults to doubling the quote (`""`), overrideable via flags
>
> **Deterministic Dialect Details**
> - Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives
1. **(chosen)** The flags configure *input* parsing only; output is always
   `,` / `"` / doubled quotes / `\n`, exactly as the "Deterministic" section states.
2. The flags configure both input and output.

### Choice
Alternative 1. The dialect section is unconditional and would otherwise be contradicted
by the flags. Supplying `--csv-escapechar` switches input parsing to backslash-style
escaping (quote doubling disabled) for that read.

### Risk: 30
Most likely author preference: alternative 2, the quote character echoed into the writer.

---

## T9. Does `--csv-null-literal` affect input as well as output?

### Spec Text
> - Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives
1. **(chosen)** Symmetric: a cell whose text equals the null literal is read as null, and
   nulls are written as the null literal. The empty string is *always* treated as null on
   input regardless of the flag.
2. Output-only: the literal is only a rendering of missing values; on input only `""` is
   null.

### Choice
Alternative 1. A merge tool that writes `NULL` but cannot read back its own output would
not be round-trippable, and treating the sentinel as data would make it sort as a
non-null string. The empty string stays null-ish under both readings for the common case.

### Risk: 35
Most likely author preference: alternative 2, output-only rendering.

---

## T10. Is `--schema` a path or inline JSON?

### Spec Text
> `[--schema <SCHEMA_JSON>]` ... **If `--schema` is provided**: JSON file with exact output schema and column order

### Alternatives
1. **(chosen)** A filesystem path (as in the `schema.json` example); as a convenience, a
   value that is not an existing path but does parse as a JSON object is accepted inline.
2. Path only; anything else is an error.

### Choice
Alternative 1 - a strict superset of alternative 2 for every input the spec describes.

### Risk: 10
Most likely author preference: path only, erroring on inline JSON.

---

## T11. Are cells of a column that a file lacks "observed values"?

### Spec Text
> - Missing columns in a file filled with null literal
> - `strict` (default): infer types based on observed values

### Alternatives
1. **(chosen)** A column absent from a file's header contributes nothing to inference for
   that file; only cells that physically exist are observed.
2. Every output row observes every column, so a file lacking the column observes a run of
   nulls.

### Choice
Alternative 1. Under alternative 2 (combined with T1) any column not shared by all inputs
would collapse to `string`, defeating the point of merging heterogeneous headers.

### Risk: 10
Most likely author preference: same.

---

## T12. Sub-second precision and time-zone handling in `timestamp` output

### Spec Text
> - `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`); if source lacked zone, treat as UTC

### Alternatives
1. **(chosen)** Seconds precision `YYYY-MM-DDTHH:MM:SSZ`, extended with a fractional part
   only when the parsed value has a non-zero microsecond component (`...:00.500Z`).
2. Always seconds precision, truncating any fraction.
3. Always microsecond precision.

### Choice
Alternative 1. It reproduces the spec's worked example exactly while not silently
discarding data the input carried.

### Risk: 30
Most likely author preference: alternative 2, dropping fractional seconds outright.

---

## T13. Sort comparison of cells that failed to cast under `--on-type-error keep-string`

### Spec Text
> - `keep-string`: emit original text as string
> - Nulls always compare less than non-null values, regardless of sort direction

### Alternatives
1. **(chosen)** Three-rank ordering per key cell: null (0) < properly typed value (1) <
   retained raw string (2). Within rank 1 the column's declared type governs; within
   rank 2 it is codepoint order.
2. Retained strings compare against typed values by coercing everything to text.
3. Retained strings sort before typed values (adjacent to nulls).

### Choice
Alternative 1. Comparing a retained string with, say, an int is otherwise undefined
(Python would raise), and grouping the "bad" cells at the non-null end keeps the ordering
total, deterministic, and stable.

### Risk: 30
Most likely author preference: alternative 2, everything stringified for comparison.

---

## T14. Interaction of `--desc` with sort stability

### Spec Text
> - Sort must be stable with respect to input appearance for equal keys
> - Default order is ascending; `--desc` applies to all keys

### Alternatives
1. **(chosen)** Only the key comparison is reversed; ties keep original input order
   (file order on the command line, then row order within a file).
2. The whole ascending result is reversed, so ties appear in reverse input order.

### Choice
Alternative 1. "Stable" is a property of the sort itself and is stated unconditionally;
reversing the entire output would break it for every tied group.

### Risk: 15
Most likely author preference: same.

---

## T15. Default `--memory-limit-mb`, and what the limit governs

### Spec Text
> `[--memory-limit-mb <INT>]` ... Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs

### Alternatives
1. **(chosen)** Default 64. The value sizes the in-memory run buffer of an external merge
   sort (spill files under `--temp-dir`, removed on exit); it is an approximate budget for
   buffered row data, not an enforced RSS ceiling.
2. A hard process ceiling enforced with `resource.setrlimit`.

### Choice
Alternative 1. A hard rlimit would abort the interpreter rather than "work under" the
limit. The behaviour is observable only as correct output plus cleaned-up temp files.

### Risk: 5
Most likely author preference: same.

---

## T16. Error reporting channel and exit status

### Spec Text
> - If a key column is not present in resolved schema, that is an error
> - `fail`: write error to stderr and exit non-zero

### Alternatives
1. **(chosen)** All operational errors (unknown key column, unreadable/invalid schema,
   missing input file, cast failure under `fail`) print a `merge_files.py: error: ...`
   line to stderr and exit with status 1; argparse usage errors exit with its own
   status 2. Nothing is written to a `-` stdout stream before an error is detected other
   than rows already flushed.
2. A distinct exit code per error class.

### Choice
Alternative 1: the spec only ever requires "non-zero", so a single code keeps it simple
while remaining compatible with any test that asserts non-zero.

### Risk: 10
Most likely author preference: same (any specific nonzero code assertion would be a
coin flip).

---

## T17. Malformed or partial schema entries

### Spec Text
> - Valid types: `string`, `int`, `float`, `bool`, `date`, `timestamp`

### Alternatives
1. **(chosen)** A schema whose JSON is invalid, whose top level lacks a `columns` list,
   whose entry lacks a `name`, or whose entry names a type outside the six valid ones is
   a hard error (stderr + non-zero). An entry with a `name` but no `type` defaults to
   `string`. Duplicate schema column names are an error; a duplicated column name in an
   *input* header binds to its first occurrence.
2. Unknown types silently degrade to `string`.

### Choice
Alternative 1. "Valid types" enumerates a closed set, so violating it is a user error
worth surfacing rather than silently reinterpreting.

### Risk: 20
Most likely author preference: same for unknown types; the `type`-less default and the
duplicate-name rules are unlikely to be tested.

---

## T18. Empty cells inside a `string` column

### Spec Text
> - Missing values emitted as the null literal
> - empty strings are treated as nulls

### Alternatives
1. **(chosen)** An empty cell is a null everywhere, including in a `string` column, so it
   is emitted as the null literal and sorts before all non-null values.
2. An empty cell in a string column is the empty string, distinct from a missing value,
   and is emitted verbatim.

### Choice
Alternative 1: one uniform notion of null across casting, output and sorting. With the
default null literal the two readings are indistinguishable in the output; they differ
only under `--csv-null-literal`.

### Risk: 25
Most likely author preference: alternative 2, where only *absent* columns render as a
custom null literal.

---

## T19. Degenerate inputs

### Spec Text
> - All inputs are UTF-8, RFC-4180 compliant, with a **header row**

### Alternatives
1. **(chosen)** A completely empty file (zero bytes) contributes no columns and no rows;
   a header-only file contributes columns but no rows. Neither is an error. A UTF-8 BOM
   on the header is stripped. Short rows are padded with nulls and over-long rows are
   truncated to the header width. A wholly blank line is a separator, not a one-null
   record (RFC-4180 has no empty record); a quoted empty field (`""`) on its own line
   *is* a record.
2. Any file without a header row is an error.

### Choice
Alternative 1: tolerant handling of trivially degenerate inputs, since the spec promises
inputs are well-formed and says nothing about rejecting empty ones.

### Risk: 15
Most likely author preference: same.

---

## T20. `--infer` supplied together with `--schema`

### Spec Text
> 1. **If `--schema` is provided**: ... 2. **If `--schema` not provided**: infer schema

### Alternatives
1. **(chosen)** The explicit schema wins outright and `--infer` is ignored (no warning).
2. Combining them is a usage error.

### Choice
Alternative 1. The two branches are presented as mutually exclusive on the presence of
`--schema` alone; the example command line even passes other inference-irrelevant flags
alongside a schema.

### Risk: 5
Most likely author preference: same.

---

## T21. Non-finite floats

### Spec Text
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. **(chosen)** `nan`, `inf`, `-infinity` and friends are *not* accepted as floats; they
   fail the cast (and never infer a column as float).
2. Python's `float()` accepts them, so they are valid float values.

### Choice
Alternative 1. `NaN` breaks the total order the sort requires, and a column of the word
"nan" is far more likely to be text than a number.

### Risk: 10
Most likely author preference: same, or untested.

---

## T22. Spelling of `--key` for composite keys

### Spec Text
> `--key <col>[,<col>...]`

### Alternatives
1. **(chosen)** Comma-separated in a single flag; additionally, repeating `--key` appends
   further key columns, and an empty/blank key name is an error. A key column named twice
   is accepted (the later occurrence is redundant but harmless).
2. Comma-separated only, one occurrence.

### Choice
Alternative 1 - a superset of the documented form.

### Risk: 5
Most likely author preference: same for the documented form.

---

## T23. Input row order across multiple files

### Spec Text
> - Sort must be stable with respect to input appearance for equal keys

### Alternatives
1. **(chosen)** "Input appearance" is the concatenation of the files in the order they
   appear on the command line (the shell expands `data/*.csv` to sorted order), each file
   read top to bottom.
2. Files sorted by name internally regardless of argv order.

### Choice
Alternative 1: argv order is the only ordering the tool actually observes.

### Risk: 5
Most likely author preference: same.
