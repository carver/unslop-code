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

> **Checkpoint 2 annotation - resolved against this choice.** The new spec's Output
> section says "Use configured CSV dialect flags for **output** quoting/escaping and
> chosen null literal", which is the explicit statement checkpoint 1 lacked. The
> implementation now follows alternative 2: the output writer uses `--csv-quotechar` as
> its quote character and, when `--csv-escapechar` is given, escapes with it instead of
> doubling quotes. The output delimiter stays `,` and line endings stay `\n` - the new
> sentence mentions only quoting/escaping and the null literal, and the tool has no
> delimiter flag. Residual risk (~20) that the author kept the checkpoint-1 fixed writer.

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

> **Checkpoint 2 annotation.** Reaffirmed: "Implementation must work with
> `--memory-limit-mb` as low as 64 and terabyte-scale inputs" - still a budget that
> shapes streaming/spilling behaviour, not an enforced RSS ceiling. The default stays
> 64, which is now the value the spec explicitly calls out.

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

> **Checkpoint 2 annotation - partly resolved.** The new spec names distinct exit codes
> (`error 2` for undetectable format, `error 3` for a key column missing from the
> resolved schema, `error 5` for a compression/dialect mismatch, `error 6` for nested
> structures) and requires "Exact exit codes and stderr message shape as specified".
> Alternative 2 therefore wins for the named classes; the missing-key error moves from
> exit 1 to exit 3. The codes the spec does *not* name are still open - see T24.

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

---

## T24. The complete exit-code table

### Spec Text
> - If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise **error 2**
> - Mismatch is **error 5**
> - literal tabs inside field not allowed (**error 5**)
> - nested fields trigger **error 6**
> - Keys must exist in resolved schema (**error 3** otherwise)
> - Exact exit codes and stderr message shape as specified

### Alternatives
1. **(chosen)** "error N" means "exit with status N". The four named codes are wired to
   exactly the situations named, and the unnamed classes are filled in to form a
   coherent table: `0` success, `1` other operational failure (output/temp-file I/O),
   `2` bad invocation - unusable flag value, missing/unreadable input, undetectable
   format (argparse's own usage errors already exit 2), `3` schema problems - invalid or
   unloadable `--schema`, unknown type name, key column absent from the resolved schema,
   `4` a cast failure under `--on-type-error fail`, `5` malformed or misdeclared input -
   compression mismatch, TSV field-count violation, unparsable CSV/JSONL, `6` a nested
   value in JSONL/Parquet.
2. Only the four named codes exist and every other error is exit 1.
3. "error N" numbers an error *class* in prose, unrelated to the process exit status
   (everything exits 1).

### Choice
Alternative 1. "Exact exit codes ... as specified" only makes sense if the numbers are
statuses, and a hidden test can only observe them that way. Codes 1 and 4 are the two
holes; 4 is placed on cast failure because that is the only remaining error class the
spec describes in detail (`--on-type-error fail`), and 1 is kept as the catch-all so an
unclassified failure never masquerades as a classified one.

### Risk: 45
Most likely author preference: same for 2/3/5/6, but `--on-type-error fail` exiting 1
(or 4 used for something else entirely, such as I/O).

---

## T25. Scope of an explicit `--input-format`

### Spec Text
> `[--input-format {auto,csv,tsv,jsonl,parquet}]`
> `--input-format=auto` (default): detect per file by extension and magic bytes

### Alternatives
1. **(chosen)** A non-`auto` value applies to *every* input, overriding extensions
   entirely (`--input-format tsv data/*.tsv.gz` reads all of them as TSV). Compression is
   still resolved independently, so `--input-format tsv` on `a.tsv.gz` still gunzips
   under `--compression auto`.
2. It is a fallback used only for files whose extension is unrecognised.

### Choice
Alternative 1. The wording contrasts "detect per file" (auto) with the explicit setting,
and the spec's own example passes `--input-format tsv` alongside `data/*.tsv.gz`, i.e.
for files whose extension already says tsv - only a global override makes that flag
meaningful there.

### Risk: 10
Most likely author preference: same.

---

## T26. Which extensions count as "ambiguous", and how far magic-byte sniffing goes

### Spec Text
> - `.csv` → csv, `.tsv` → tsv, `.jsonl`/`.ndjson` → jsonl, `.parquet` → parquet
> - For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz`, `events.jsonl.gz`)
> - If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

### Alternatives
1. **(chosen)** "Ambiguous" = the (gzip-stripped) extension is not one of the five known
   ones, including the no-extension case. Such a file is sniffed: if the decompressed
   stream starts with `PAR1` it is parquet, otherwise exit 2. A *recognised* extension is
   authoritative and is never overridden by magic bytes.
2. Magic bytes are consulted for every file, overriding the extension when they disagree
   (so `data.csv` containing `PAR1...` is read as parquet).
3. "Ambiguous" means only the extensionless case; a file with an unknown-but-present
   extension (`.dat`, `.txt`) is exit 2 without sniffing.

### Choice
Alternative 1. The extension table is stated first and unconditionally, so it should win
when it applies; sniffing is described as the tie-breaker for the leftover case, and
treating "unknown extension" and "no extension" alike is the least surprising split.
Note that only the parquet magic is checked - the spec offers no magic for csv/tsv/jsonl,
so an unrecognised non-parquet file is exit 2 rather than a guessed text format.

### Risk: 30
Most likely author preference: alternative 2 - sniff every file and let `PAR1` win over
the extension.

---

## T27. What "mismatch" means for `--compression`

### Spec Text
> - `--compression=auto` (default): detect `.gz` → gzip; otherwise none
> - `--compression=none` forces no decompression; `--compression=gzip` forces gzip
> - Mismatch is error 5

### Alternatives
1. **(chosen)** Mismatch = the resolved compression disagrees with the file's actual
   first two bytes: `--compression gzip` (or a `.gz` name under auto) on a file that does
   not start with `1f 8b`, and `--compression none` (or a non-`.gz` name under auto) on a
   file that does. Either way: exit 5. A zero-byte file matches anything.
2. Mismatch = the *flag* disagrees with the *extension* (`--compression none` on
   `a.csv.gz`), regardless of content.
3. Mismatch = a gzip decoding failure surfacing while reading.

### Choice
Alternative 1. It is the only reading that also covers `--compression gzip` on plain
data (the flag is described as forcing, so it cannot be a no-op) and it subsumes
alternative 3 for the common truncated/invalid-header case. Reading a gzip stream as
plain bytes would otherwise produce garbage rows rather than a diagnosable error.

### Risk: 35
Most likely author preference: alternative 2 or a narrower version of 1 that only
errors when gzip decoding actually fails, leaving `--compression none` on a gzip file to
fail later as malformed input.

---

## T28. Precedence order under `--schema-strategy=authoritative`

### Spec Text
> - `--schema-strategy=authoritative` (default): prefer typed sources in precedence order

### Alternatives
1. **(chosen)** Sources are ranked by how much type information they carry: parquet (2)
   > jsonl (1) > csv/tsv (0). For each column, only the files in the highest-ranked tier
   that actually contain that column decide its type; lower tiers are ignored. If several
   files inside the winning tier disagree, the `--infer` rule breaks the tie (strict ->
   `string`, loose -> the pooled candidate intersection). If no typed source has the
   column, the checkpoint-1 inference over the text sources decides it.
2. Precedence follows command-line order: the first file that has the column wins.
3. Precedence is parquet > jsonl > csv = tsv, but a disagreement *within* the winning
   tier is an error.

### Choice
Alternative 1. "Prefer typed sources" is explicit that the axis is typedness, and
parquet's physical schema is stronger evidence than JSON's dynamic types, which in turn
beat untyped text. Falling back to checkpoint 1's rules for the all-text case keeps the
default strategy byte-compatible with checkpoint 1, which matters because
`authoritative` is the default and every checkpoint-1 invocation implicitly uses it.

### Risk: 40
Most likely author preference: same tiering, but resolving an intra-tier conflict by
first-file-wins (alternative 2) rather than by `--infer`.

---

## T29. What "majority of files support" means under `--schema-strategy=consensus`

### Spec Text
> - `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives
1. **(chosen)** Each file that contains the column votes for the single type it would
   infer on its own (its best candidate type). The type with the most votes wins; ties
   are broken by the checkpoint-1 priority order `timestamp > date > bool > int > float >
   string`. A file lacking the column casts no vote.
2. Each file votes for *every* type it could support (its whole candidate set), and the
   most-supported type wins. Because every file supports `string`, `string` can never
   lose, so the rule degenerates unless ties are broken by priority - and then it is very
   close to `union`.
3. A strict majority (> 50% of files) is required, otherwise fall back to `string`.

### Choice
Alternative 1. It is the only reading under which `consensus` behaves differently from
both other strategies and matches the intuition the name carries: two int files and one
string file yield `int`. Alternative 2's degeneracy and alternative 3's silent
`string` fallback both make the flag much less useful than the spec's example
(`--schema-strategy consensus` over CSV + JSONL + Parquet) implies.

### Risk: 45
Most likely author preference: alternative 3's "no strict majority -> string" refinement
layered on top of alternative 1.

---

## T30. "Simplest common type" under `--schema-strategy=union`

### Spec Text
> - `--schema-strategy=union`: choose simplest common type that can hold all observed values

### Alternatives
1. **(chosen)** Intersect the candidate-type sets of every observed value in every file
   and take the highest-priority survivor (`string` always survives, so the result is
   total). `int` + `float` -> `float`; `int` + `date` -> `string`; `1`/`0` + `true` ->
   `bool`.
2. "Simplest" = lowest priority, i.e. always `string` whenever more than one type is in
   play - which would make the strategy useless.
3. Numeric widening only (int+float -> float), anything else -> `string`.

### Choice
Alternative 1. "Can hold all observed values" is exactly the intersection of candidate
sets; "simplest" then selects among the survivors, and the spec's own priority list is
the only ranking available. This makes `union` identical to checkpoint 1's `loose`
pooling, which is a reassuring convergence rather than a coincidence.

### Risk: 25
Most likely author preference: same, modulo the `int`+`float` -> `float` case, which
alternative 3 also gets right; disagreement is likelier on exotic pairs.

---

## T31. How `--infer` and `--schema-strategy` interact

### Spec Text
> - Type inference per `--infer` mode (strict or loose)
> - **Schema disagreement strategy** when inputs have conflicting types for same column

### Alternatives
1. **(chosen)** Two stages. `--infer` governs how one file's candidate types for a column
   are derived (in particular whether an empty text cell is an observation that forces
   `string`, per T1); `--schema-strategy` governs how the per-file results are combined
   into the final type. Under the default `authoritative` with only text inputs, the
   combination step is checkpoint 1's rule, so checkpoint-1 behaviour is preserved
   exactly.
2. `--schema-strategy` fully supersedes `--infer` whenever inputs disagree, making
   `strict`/`loose` relevant only for single-file runs.
3. The two flags are alternative spellings of the same knob and the later one wins.

### Choice
Alternative 1. The spec introduces the strategies specifically as a *disagreement*
policy ("when inputs have conflicting types for same column") while still listing
`--infer` as the inference mode, so they compose rather than compete. Preserving
checkpoint 1's observable behaviour under the defaults is a strong tie-breaker.

### Risk: 35
Most likely author preference: alternative 2, with `authoritative` + text-only inputs
still collapsing conflicts to `string` (which coincides with this choice for `strict`,
but not for `loose`).

---

## T32. "For JSONL numbers, prefer `int` if integer and within range; otherwise `float`"

### Spec Text
> - For JSONL numbers, prefer `int` if integer and within range; otherwise `float`

### Alternatives
1. **(chosen)** Applies to the JSON *value*: any JSON number whose value is integral and
   fits in signed 64 bits becomes a Python `int` (so `5`, `5.0` and `5e0` all become
   `5`); everything else (`2.5`, `1e30`, `12345678901234567890`) becomes a `float`. The
   resulting value is then cast to the column's target type like any other.
2. Applies only to numbers JSON wrote without a decimal point, i.e. exactly what
   `json.loads` already returns (`5.0` stays a float and renders as `5.0`).
3. "Within range" refers to the target column's declared range rather than int64.

### Choice
Alternative 1. If the rule merely restated `json.loads` behaviour it would not need
stating, and "if integer" is a statement about the value, not the lexeme. The int64
bound is the only "range" that exists for a Python int, which is otherwise unbounded -
and it matches what a Parquet or database-backed implementation would enforce.

### Risk: 45
Most likely author preference: alternative 2 - `5.0` in a `string` column rendering as
`5.0` rather than `5`.

---

## T33. Casting already-typed values across type families

### Spec Text
> - JSONL values come typed (string/number/bool/null)
> - Parquet values come typed
> - Apply target output schema cast rules to every cell
> - On cast failure, follow `--on-type-error` from checkpoint 1

### Alternatives
1. **(chosen)** A typed value is cast by value, mirroring what the text caster accepts:
   int/float -> `int` (only when integral), `float`, `string`; `bool` -> `bool` and
   `string` only (a JSON `true` in an int column fails, exactly as the text `true` does);
   int `0`/`1` -> `bool` (the text caster accepts `0`/`1`, so the typed one does too);
   datetime/date -> `timestamp`/`date`/`string`; numbers -> temporal types fail (no epoch
   interpretation). A typed *string* value is routed through the ordinary text caster, so
   `"7"` in an int column is `7` and `""` is a null.
2. Everything is stringified first and then run through the checkpoint-1 text caster
   (so `true` -> `bool` works, but `1.0` -> int fails and floats round-trip through
   `repr`).
3. Strict typing: a value whose Python type does not already match the target type is a
   cast failure (no int -> float, no `"7"` -> int).

### Choice
Alternative 1. "Apply target output schema cast rules to every cell" says the same rules
govern typed and untyped cells, so the typed path is built to accept exactly the value
set the text path accepts. Alternative 3 would make mixed CSV+Parquet merges fail
constantly; alternative 2 loses precision for large ints and is awkward for temporal
values that arrive as real datetimes.

### Risk: 35
Most likely author preference: alternative 2 - stringify, then reuse the checkpoint-1
caster verbatim.

---

## T34. TSV details: literal tabs, the required header, and short rows

### Spec Text
> - **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` line endings; literal tabs inside field not allowed (error 5)

### Alternatives
1. **(chosen)** No quoting at all: `"` is an ordinary character and there is no escape
   character. A literal tab inside a field is therefore only *observable* as a data row
   with more fields than the header, which is exit 5. A row with fewer fields than the
   header is padded with nulls (checkpoint 1's rule for short rows, T19). A completely
   empty file contributes nothing and is not an error; a file whose first line exists is
   its header.
2. A row with a different field count in either direction is exit 5.
3. An empty TSV file violates "header row required" and is exit 5.

### Choice
Alternative 1. "Literal tabs inside field not allowed" describes only the over-long case
(an extra tab creates an extra field); nothing in the spec makes a *missing* trailing
field a tab problem, and checkpoint 1 already pads short CSV rows, so keeping the two
formats consistent is the least surprising choice. Treating an empty file as empty rather
than as an error likewise follows T19.

### Risk: 35
Most likely author preference: alternative 2 - any field-count deviation in a TSV row is
error 5.

---

## T35. JSONL edge cases: bad JSON, non-object lines, duplicate keys

### Spec Text
> - **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects as values); `null` permitted; keys case-sensitive; blank/whitespace lines ignored

### Alternatives
1. **(chosen)** A line that is not valid JSON is malformed input -> exit 5. A line whose
   top-level value is not an object (an array, a number, a string) violates the flatness
   contract -> exit 6, the same code as a nested value, since both are "not a flat
   object". A value that is a JSON array or object -> exit 6. Duplicate keys on one line
   resolve last-wins (Python's `json` behaviour). Keys are compared case-sensitively, so
   `id` and `ID` are two different output columns.
2. A non-object line is exit 5 (malformed record) and only *values* that are nested give
   exit 6.
3. Non-object and malformed lines are skipped silently.

### Choice
Alternative 1. The spec ties error 6 to "Flat-only enforcement for JSONL/Parquet;
nested structures trigger error 6" in the determinism checklist, and a top-level array is
the most nested structure a line can be. Skipping bad lines (alternative 3) would violate
"All rows from all inputs appear exactly once".

### Risk: 40
Most likely author preference: alternative 2 - a non-object top-level line reported as
malformed input (5) rather than as a nesting violation (6).

---

## T36. Parquet: when nesting is detected, and which physical types are supported

### Spec Text
> - **Parquet**: flat schemas only (no nested/list/map types); nested fields trigger error 6
> - Parquet reading must be streamed row group–wise; `--parquet-row-group-bytes` is advisory for batch sizing

### Alternatives
1. **(chosen)** Nesting is rejected from the file's *schema*, before any row is read, so
   an empty parquet file with a list column still exits 6. Supported leaves are the flat
   arrow types: bool, all int/uint widths, float/double, decimal, string/large_string,
   binary, date32/64, timestamp (tz-aware normalised to UTC, naive assumed UTC), time and
   null. Anything list/struct/map/union-shaped is exit 6.
2. Nesting is detected per value while streaming, so a nested column that happens to hold
   only nulls is tolerated.
3. Only the exact six spec types are readable and any other physical type is an error.

### Choice
Alternative 1. "Flat *schemas* only" is a statement about the schema, and checking it up
front is both cheaper and deterministic regardless of file contents. Accepting the wider
set of flat physical types (alternative 1 over 3) follows from "Parquet values come
typed" plus "apply target output schema cast rules to every cell": the cast layer, not
the reader, decides whether a value fits the requested column type.

### Risk: 20
Most likely author preference: same.

---

## T37. What "write atomically" requires

### Spec Text
> - `--output -` writes to stdout; otherwise write atomically

### Alternatives
1. **(chosen)** Rows are streamed into a temporary file created in the destination's own
   directory, flushed, and then `os.replace`d onto the destination, so the destination
   either does not change or changes to the complete result in one step. On any failure
   the temporary file is removed and the destination is left untouched (in particular, an
   existing file is not truncated). `--output -` is exempt.
2. Buffer the entire output in memory and write it in a single `write()` call - which
   would contradict the memory limit.
3. Ordinary open/truncate/write; "atomically" is aspirational.

### Choice
Alternative 1: the standard temp-file-plus-rename idiom, and the only one compatible with
terabyte-scale streaming output. The temporary file lives beside the target (not in
`--temp-dir`) because `os.replace` is only atomic within a filesystem.

### Risk: 10
Most likely author preference: same.

---

## T38. Default and units of `--parquet-row-group-bytes`

### Spec Text
> - `--parquet-row-group-bytes <INT>` ... is advisory for batch sizing

### Alternatives
1. **(chosen)** A byte budget for one in-flight batch, defaulting to 8 MiB, converted to
   a row count using a rough per-row size estimate derived from the file's schema and
   clamped to `[1, 8192]` rows and to the `--memory-limit-mb` budget. It never
   changes the output, only the batch granularity; a value of 0 or a negative value
   is exit 2.
2. It is a row count rather than a byte count.
3. It sizes row groups when *writing* parquet - but the tool never writes parquet.

### Choice
Alternative 1, which is what the name and the word "advisory" say. Because it cannot
affect output bytes, the only externally visible consequence is memory use, so the
default is chosen to sit comfortably under a 64 MB budget.

### Risk: 5
Most likely author preference: same (unobservable in output).

---

## T39. Empty strings and the null literal inside typed sources

### Spec Text
> - If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing → emit null literal

### Alternatives
1. **(chosen)** A typed *string* value is handed to the ordinary text cast path, so an
   empty JSONL/Parquet string is a null exactly like an empty CSV cell, and a string equal
   to `--csv-null-literal` is a null too (T9's symmetry, applied uniformly).
2. The sentence is an exhaustive parallel: for typed sources *only* JSON/parquet `null` is
   missing, so `""` is a genuine empty string - which renders as an empty field in a
   `string` column and is a cast failure in an `int` column.

### Choice
Alternative 1. Checkpoint 1 already decided (T18) that the tool has one uniform notion of
null; routing typed strings through the same caster keeps `""`, the null literal and a
missing key indistinguishable in the output, which is also what a natural implementation
that reuses the checkpoint-1 caster for `str` values does.

### Risk: 30
Most likely author preference: alternative 2 for the `string`-column case, where an
empty JSONL string is echoed as an empty field rather than as a custom null literal.

---

## T40. How typed sources contribute to *inference*: declared type or re-read text?

### Spec Text
> - JSONL values come typed (string/number/bool/null)
> - Parquet values come typed
> - Type inference per `--infer` mode (strict or loose)
> - `--schema-strategy=authoritative` (default): prefer typed sources in precedence order

### Alternatives
1. **(chosen)** For inference, a typed source's value contributes the type it already
   carries: a JSON/Parquet string contributes `string`, a number `int`/`float`, a boolean
   `bool`, a Parquet timestamp/date the matching temporal type. Text inside a typed
   string is *not* re-inferred, so `"2024-01-01"` in JSONL is a `string` column, not a
   `date` one. Casting is unaffected: that same string still casts fine into a declared
   `date` column, and into a `date` column chosen by another source.
2. Every string value, whatever its source, is re-inferred from its text, so a JSONL
   column of date-looking strings infers as `date`.

### Choice
Alternative 1. The spec enumerates the JSONL value types as exactly "string/number/bool/
null", which is a statement about what type a JSONL value *has*; and the whole point of
"prefer typed sources" is that a typed source's own type declaration outranks a guess
made from text. Under alternative 2 a Parquet `string` column of `"01"`, `"02"` would
infer as `int` and the tool would print `1`, `2` - silently destroying data the source
explicitly typed as text, which is exactly what a precedence rule exists to prevent.

### Risk: 40
Most likely author preference: alternative 2 for JSONL specifically (re-inferring
date/timestamp strings), since JSON has no temporal type and a merged `ts` column drawn
from CSV and JSONL is the spec's own headline example.
