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

### Update (checkpoint 5)
Resolved by the nested-types spec: `ERR 4 cannot cast ...` and `ERR 3 key column ...`
confirm exit 4 for a failed cast and exit 3 for a key/partition path problem, and
`error 2` is now attached to alias cycles as well. The message *shape* left open here is
settled in [[T53]].

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

---

## T41. Do partition columns still appear inside the partition CSV files?

### Spec Text
> - Rows for each unique combination of partition column values go into separate directory
> - Emit directory tree inside `--output` using Hive-style segments:
>   `<col1>=<val1>/<col2>=<val2>/.../`

and

> - Every output CSV includes header row in resolved schema column order

### Alternatives
1. **(chosen)** The CSV files keep every resolved-schema column, including the partition
   columns; the directory names duplicate information that is also in the rows.
2. True Hive layout: the partition columns are *projected out* of the data files (their
   value is recoverable from the path), so the header of a partitioned file is the
   resolved schema minus the partition columns.

### Choice
Alternative 1. "Every output CSV includes header row in resolved schema column order"
is stated in the `CSV Output Contents` section that governs partitioned files too, and
it says *the* resolved schema, not a projection of it. The spec also stresses that "each
partition file is independently valid CSV" and that the same header appears in every
file; dropping columns would make the header depend on `--partition-by`, which the spec
never mentions. Hive's projection is a storage optimisation of a specific engine, not
something the prose asks for.

### Risk: 20
Most likely author preference: alternative 2 - genuine Hive-style projection with the
partition columns removed from the files.

---

## T42. What happens when `--output` already exists

### Spec Text
> - Create directory if doesn't exist
> - Perform atomic write by creating sibling temp directory and renaming on success

### Alternatives
1. **(chosen)** Build everything in a sibling temp directory. If the target does not
   exist, `rename` the temp directory into place (one atomic step). If the target already
   exists (the common "empty output directory pre-created by the caller" case, and a
   plain `rename` onto it would fail), move the generated tree into it entry by entry,
   replacing same-named files and leaving unrelated pre-existing files alone.
2. Replace the target wholesale: delete the existing directory (or swap it aside and
   delete afterwards) so the run's output is the only thing in it.
3. Refuse to run when the target already exists.

### Choice
Alternative 1. `rename` semantics are the spec's own stated mechanism, and they only work
directly when the destination is absent, so some fallback is required for an existing
directory; the least destructive one that still lands every generated file is a merge.
Alternative 3 contradicts "create directory if doesn't exist" being the only
precondition mentioned, and alternative 2 deletes user data the spec never says may be
deleted. Under any of the three readings the observable result is identical for the two
cases a test is likely to exercise (target absent, or target present but empty).

### Risk: 30
Most likely author preference: alternative 2 - stale files from a previous run are wiped,
so a re-run into a directory that previously held more partitions leaves no extra parts.

---

## T43. What is written when the sorted stream is empty

### Spec Text
> - `--max-rows-per-file <INT>`: cut output into files with at most INT data rows each (header not counted)
> - Within each partition directory, write CSV files named sequentially: `part-00000.csv`, ...
> - Each file contains header row (resolved schema header)

### Alternatives
1. **(chosen)** With sharding but no field partitioning, `part-00000.csv` always exists
   and holds at least the header, even when zero data rows are emitted. With field
   partitioning there are no partitions at all for an empty stream, so the output
   directory is created but stays empty.
2. Files are opened lazily on the first row in both modes, so an empty stream produces an
   empty output directory.
3. An empty stream produces no output directory at all.

### Choice
Alternative 1. Sharding is described as cutting *the* output stream into files, and that
stream always has a header row ("Each file contains header row"); the natural
implementation opens the first shard and writes the header before it knows whether any
row follows, because the header's byte size is needed to enforce `--max-bytes-per-file`.
A field partition, by contrast, only exists if some row has that combination of values,
so nothing can be emitted for it. Alternative 3 is ruled out by "create directory if
doesn't exist" being unconditional.

### Risk: 45
Most likely author preference: alternative 2 - both modes open part files lazily, so an
empty input leaves an empty output directory.

---

## T44. Is the partition *column name* percent-encoded, or only the value?

### Spec Text
> `<col1>=<val1>/<col2>=<val2>/.../`
> - Apply percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`; space → `%20`; `/` encoded as `%2F`

### Alternatives
1. **(chosen)** Both sides of the `=` are encoded with the same rule; the `=` and `/`
   that build the segment structure are of course literal.
2. Only the value is encoded; the column name is emitted verbatim.

### Choice
Alternative 1. The rule is stated for the segment as a whole, and a column name may
legally contain a space, a slash or non-ASCII text, which would corrupt the directory
layout if left raw. For the ordinary identifier-shaped column names of every example in
the spec the two readings produce byte-identical paths.

### Risk: 15
Most likely author preference: alternative 2 (encode only the value) - which differs only
for exotic column names.

---

## T45. Which cells count as "null (missing)" for a partition segment

### Spec Text
> - Null (missing) partition values use literal `_null`

### Alternatives
1. **(chosen)** Every cell that ends up null in the output is `_null`: a field absent
   from the record, an explicit JSON/Parquet null, a cell equal to the null literal (or
   empty), and a cell whose cast failed under `--on-type-error coerce-null`.
2. Only a *missing* field (the parenthetical reading) is `_null`; a cell present but
   empty produces an empty segment `col=`.

### Choice
Alternative 1. The partition value is "derived after casting to resolved schema types",
so the thing being encoded is the post-cast value, and post-cast there is only one kind
of null. `col=` would also be an ambiguous, near-invisible directory name, and the spec
introduces `_null` precisely to avoid a name that no filesystem-friendly encoding of
"nothing" could produce. Under `--on-type-error keep-string` a failed cast keeps its
original text and is therefore *not* null - that text is encoded as-is.

### Risk: 20
Most likely author preference: same, except that a cell equal to a non-empty
`--csv-null-literal` might be encoded literally rather than as `_null`.

---

## T46. How a typed partition value is rendered before encoding

### Spec Text
> - Values derived after casting to resolved schema types

### Alternatives
1. **(chosen)** The segment uses exactly the text the same cell would have in the CSV
   body: timestamps normalised to `...Z`, booleans as `true`/`false`, floats in the
   tool's canonical float form. `dt=2024-07-01`, `ts=2024-07-01T12%3A00%3A00Z`.
2. The segment uses the raw input text of the cell, before casting.
3. The segment uses a repr of the parsed value (e.g. Python's `True`, `1.0`).

### Choice
Alternative 1. "After casting" rules out alternative 2, and the only rendering rule the
spec has ever defined for a cast value is the CSV output formatting, so reusing it keeps
a partition directory name and the column's own cell in agreement. This also makes the
layout independent of which input file a row came from, which is what the determinism
checklist asks for.

### Risk: 15
Most likely author preference: same reading.

---

## T47. A real value that is literally `_null`

### Spec Text
> - Apply percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`
> - Null (missing) partition values use literal `_null`

### Alternatives
1. **(chosen)** No special casing: `_` is inside the safe set, so the string value
   `_null` encodes to `_null` and shares a directory with the null partition.
2. Escape a real `_null` (e.g. `%5Fnull`) so the two are distinguishable.

### Choice
Alternative 1. The encoding rule is exhaustive and lists `_` as safe; adding an escape
hatch would be an extra rule the spec does not state, and it would make the encoder
non-uniform.

### Risk: 10
Most likely author preference: same reading.

---

## T48. Byte accounting for `--max-bytes-per-file`

### Spec Text
> - `--max-bytes-per-file <INT>`: cut so on-disk byte size of each file (including header and line endings) is ≤ INT
>   - Exception: if single row alone exceeds INT, place that row in file by itself (allowed to exceed limit)

### Alternatives
1. **(chosen)** A file's size is the exact UTF-8 byte length of what is written: the
   rendered header line plus every rendered data line, each terminated by `\n`. A row is
   appended to the current file only while the resulting total stays `<= INT`; otherwise
   the file is cut first. A file always receives the header and at least one data row, so
   a header-plus-one-row file may exceed INT (the stated exception, which is read as
   covering the header too since the header is unavoidable).
2. The limit applies only to the data rows, with the header not counted (contradicted by
   "including header").
3. The exception applies only when the row *alone* exceeds INT, so a row that only
   exceeds INT once the header is added would instead loop forever / be dropped.

### Choice
Alternative 1. It is the only reading under which every row is emitted exactly once for
every value of INT, including INT smaller than the header. The comparison is on the total
after the write, so `size + row <= INT` keeps the file, `>` cuts it.

### Risk: 20
Most likely author preference: same reading; the residual risk is an off-by-one at
exactly `INT` (a `<` rather than `<=` boundary).

---

## T49. Errors specific to partitioned output, and their exit codes

### Spec Text
> - When any partitioning flag provided: `--output` must be directory path (not `-`)
> - Exact exit codes and stderr message shapes as specified

### Alternatives
1. **(chosen)** Reuse the established table: `--output -` together with any partitioning
   flag, a non-positive `--max-rows-per-file`/`--max-bytes-per-file`, and an `--output`
   path that exists as a non-directory are invocation problems -> exit 2. A
   `--partition-by` column that is not in the resolved schema is a schema problem, like
   the existing rule for `--key` -> exit 3. Failure to create the directory is
   operational -> exit 1.
2. Every partitioning problem is a plain usage error -> exit 2, including the unknown
   partition column.

### Choice
Alternative 1. The unknown-column case cannot be detected from argv alone - it depends on
the resolved schema, exactly like the pre-existing "key column not present in the
resolved schema" error, which the earlier checkpoint assigned to the schema class. Every
other case is detectable before any input is read and is a plain misuse of the CLI.

### Risk: 25
Most likely author preference: exit 2 for an unknown `--partition-by` column as well.

---

## T50. Where the sibling temp directory lives, and what `--temp-dir` controls

### Spec Text
> - Perform atomic write by creating sibling temp directory and renaming on success
> - On failure, remove temp directory and partial files

### Alternatives
1. **(chosen)** The temp directory is created next to the final output directory (same
   parent, so the rename stays within one filesystem) under a dotted, obviously temporary
   name. `--temp-dir` keeps its established meaning - the location of external-merge
   spill files - and does not move the output staging area.
2. `--temp-dir`, when given, also holds the output staging directory (which would break
   the atomic rename whenever it is on another filesystem).

### Choice
Alternative 1. "Sibling" is explicit about the location, and it is what makes the rename
atomic at all. The exact temp name is unobservable on success and is removed on failure,
so only its parent directory is testable.

### Risk: 10
Most likely author preference: same reading.

---

## T51. Segment order for multiple partition columns

### Spec Text
> `--partition-by <col>[,<col>...]` ... `<col1>=<val1>/<col2>=<val2>/.../`

### Alternatives
1. **(chosen)** Segments appear in the order the columns are listed on the command line
   (`col1`, `col2`, ... are the flag's own operands), independent of schema order.
   Repeated names are de-duplicated, as `--key` already does.
2. Segments follow resolved-schema column order.

### Choice
Alternative 1. The spec names the segments `<col1>`, `<col2>` in the same breath as the
flag's `<col>[,<col>...]` operand list, and the worked example writes
`--partition-by country,dt` while showing `country=.../dt=...`. Nesting order is a
user-visible layout choice, so honouring the given order is what makes it controllable.

### Risk: 5
Most likely author preference: same reading.

---

## T52. Are shard counters per directory, and does a shard limit apply across partitions?

### Spec Text
> - File naming (with field partitioning): same `part-xxxxx.csv` sequence per partition directory

### Alternatives
1. **(chosen)** Each partition directory has its own independent `part-00000.csv...`
   sequence and its own row/byte counters; a partition holding two rows gets a single
   `part-00000.csv` no matter how full other partitions are.
2. A single global counter shared by all partitions, so file numbers are unique across
   the whole output tree.

### Choice
Alternative 1. "per partition directory" says the sequence restarts, and the no-sharding
rule ("otherwise one file per partition") requires every partition's single file to be
named `part-00000.csv`.

### Risk: 5
Most likely author preference: same reading.

---

## T53. The literal shape of an error line, now that `ERR <n> ...` is shown

### Spec Text
> * `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

> * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. **(chosen)** Every error line the tool writes is exactly `ERR <code> <message>\n`
   on stderr, one line, and the two messages above are reproduced verbatim (with the
   ellipses filled in as `file=<path> line=<n>`). Earlier checkpoints' messages keep
   their wording but gain the `ERR <code> ` prefix.
2. Only these two messages carry an `ERR n` prefix; every other error keeps the
   `merge_files.py: error: <message>` shape used through checkpoint 4.
3. The prefix is additive: `merge_files.py: error: ERR 4 cannot cast ...`, which keeps
   both the previous prefix and the newly specified text.

### Choice
Alternative 1. The spec quotes these lines as whole stderr lines, not as fragments
embedded in a longer sentence, and it introduces `ERR <n>` without ever defining it -
which reads like a convention the author's implementation has used since checkpoint 1
(the "exact ... stderr message shape as specified" line has been in the spec all along).
A tool whose messages are `ERR 4 ...` here and `merge_files.py: error: ...` elsewhere
would be the odd one out. Alternative 3 survives a substring assertion but fails
`startswith`, so it is strictly worse than 1 if 1 is right and only marginally better if
it is wrong. This supersedes the message-shape half of [[T24]]; the exit codes there are
confirmed (cast failure is 4, and the nested/schema codes 6/3 are re-stated here).

### Risk: 25
Most likely author preference: alternative 1 exactly, but with a different rendering of
the trailing context (e.g. `(file=a.jsonl, line=3)` or the file path quoted).

---

## T54. Which exit code covers a bad `--type-alias-file`

### Spec Text
> * May refer to built-ins or other aliases (resolve transitively; detect cycles → error 2)

### Alternatives
1. **(chosen)** Everything wrong with the alias file - unreadable path, invalid JSON,
   a non-object `aliases` value, a non-string target, and an alias cycle - is exit 2,
   the invocation-error class. Unknown *type names* remain a schema error (exit 3),
   including a type name produced by resolving an alias to something unknown.
2. Only cycles are exit 2; other alias-file problems are schema errors (exit 3).
3. Alias problems are all schema errors (exit 3) and "error 2" is a typo for 3.

### Choice
Alternative 1. A cycle in the alias file is not conceptually different from a syntax
error in it, so the code the spec does name is read as covering the file as a whole:
the alias file is part of the invocation rather than part of the schema. Exit 3 is kept
for the schema document, which is where an unresolvable type name is actually written.

### Risk: 35
Most likely author preference: cycles exit 2 as specified but a malformed/missing alias
file exits 3 with the other schema errors.

---

## T55. Whether an alias cycle is detected eagerly or only when used

### Spec Text
> * May refer to built-ins or other aliases (resolve transitively; detect cycles → error 2)

### Alternatives
1. **(chosen)** Every alias in the file is resolved when the file is loaded, so a cycle
   is reported even when no schema column uses it.
2. Aliases are resolved lazily, so a cycle only errors when a column's declared type
   reaches it.

### Choice
Alternative 1. "Detect cycles" reads as a property of the alias table, and eager
validation makes the outcome independent of which columns happen to be declared -
squarely the spec's "unknown types error deterministically" intent. A fixture for this
rule is most naturally written as "alias file with a->b->a, exit 2", with a schema that
may or may not mention the cycle.

### Risk: 20
Most likely author preference: lazy resolution, so a cycle nobody references is ignored.

---

## T56. Does a bare `struct` (or `json`) type accept arbitrary JSON?

### Spec Text
> * `json`→`struct` (accept any JSON, see below)

> * Special alias `json`: when field declared as `"type":"json"`, accept any JSON value (object/array/primitive) and emit as JSON text

### Alternatives
1. **(chosen)** `"type": "json"` and `"type": "struct"` (the string form, with no field
   list) are the same type: a free-form JSON value, accepted as-is and normalised. The
   alias table maps `json` onto it exactly as the spec says.
2. `json` is its own type and the string `"struct"` alone is an error, because a struct
   is only meaningful with a declared field list; the alias table entry is loose prose.
3. `"struct"` alone means an empty struct, i.e. every input object becomes `{}`.

### Choice
Alternative 1. The spec states the alias mapping (`json`→`struct`) as a fact about the
alias table, and alias resolution is a pure name rewrite - so whatever `json` means,
`struct` must mean the same thing after resolution. Alternative 3 would make the
declared alias useless.

### Risk: 30
Most likely author preference: alternative 2 - `json` handled as a distinct type and a
bare `"struct"` rejected as an incomplete type (exit 3).

---

## T57. Key order of a `json`-typed value in the output

### Spec Text
> * Struct fields in schema-declared order
> * Map keys sorted lexicographically

> * For `json` type: accept any JSON value without casting; normalize only

### Alternatives
1. **(chosen)** A JSON object inside a `json`-typed value has no schema-declared order,
   so it is normalised like a map: keys sorted lexicographically, recursively.
2. Object keys keep the order they had in the input; "normalize only" means whitespace
   and number formatting only.

### Choice
Alternative 1. The output must be *canonical* JSON, and canonical forms of a
schema-less object sort their keys (RFC 8785 does the same). Under alternative 2 the
same logical record arriving from a JSONL file and from a Parquet file could produce two
different cells, which the determinism checklist rules out.

### Risk: 40
Most likely author preference: alternative 2 - input key order preserved for `json`
columns, since the spec only mandates sorting for `map`.

---

## T58. Are non-ASCII characters escaped in the emitted JSON?

### Spec Text
> * Minified (no spaces), UTF-8, RFC 8259 JSON escaping

### Alternatives
1. **(chosen)** Emit the characters literally as UTF-8; escape only what RFC 8259
   requires (`"`, `\`, and C0 controls, with `\b \f \n \r \t` short forms and `\u00XX`
   otherwise).
2. Escape every non-ASCII character as `\uXXXX` (Python's `json.dumps` default).

### Choice
Alternative 1. "UTF-8" next to "RFC 8259 JSON escaping" only adds information if
non-ASCII text is meant to survive as UTF-8 bytes; RFC 8259 itself calls `\u` escaping
of ordinary characters optional. The whole output file is UTF-8 already.

### Risk: 25
Most likely author preference: alternative 2, if the implementation calls
`json.dumps(...)` without `ensure_ascii=False`.

---

## T59. A dotted path that is also a literal column name

### Spec Text
> * `--key` and `--partition-by` now accept **field paths** using dot notation (e.g., `user.id`, `items.0.sku`)

### Alternatives
1. **(chosen)** A path that exactly matches a top-level column name is that column
   (whatever dots it contains); otherwise the string is parsed as a path and its first
   segment names the column.
2. The string is always parsed as a path, so a column literally named `user.id` can no
   longer be used as a key.
3. Path parsing only happens when the first segment names a nested column.

### Choice
Alternative 1. Earlier checkpoints accepted arbitrary column names in `--key`, and
nothing in this checkpoint withdraws that; whole-name-first keeps every previously valid
invocation working while making paths available for everything else.

### Risk: 20
Most likely author preference: alternative 2 - dots always split, since the author's
fixtures are unlikely to contain a dotted column name at all.

---

## T60. What happens to a nested value in a column the schema does not declare

### Spec Text
> * **JSONL**: Accept nested objects/arrays only when schema declares column as nested or `json`

> * Without `--schema`, nested inputs not allowed (error 6)

### Alternatives
1. **(chosen)** With `--schema` given, a nested value in a field the schema never
   mentions is ignored along with the rest of that undeclared field: no error.
2. It is error 6, because the schema does not declare *that column* as nested.
3. It is a schema error (exit 3), an undeclared column carrying structure.

### Choice
Alternative 1. Error 6's own text is "nested structure requires provided `--schema`", so
the error is about the *absence* of a schema; once one is supplied, undeclared columns
are dropped before their contents can matter (that is the established rule for
undeclared flat columns too). Alternative 2 would make an unrelated nested field in a
wide input file fatal.

### Risk: 30
Most likely author preference: alternative 2 - any nested value that is not covered by a
nested declaration is rejected with error 6.

---

## T61. `--on-type-error fail` on a CSV cell that is not valid JSON: exit 4 or 5?

### Spec Text
> * **CSV/TSV**: Cell must contain single JSON literal when target type is nested or `json`
>   * Empty cell → null
>   * Invalid JSON → handled per `--on-type-error`/error 5

### Alternatives
1. **(chosen)** The cell is handled exactly like any other cast failure: `coerce-null`
   nulls the cell, `keep-string` keeps the raw cell text, `fail` emits the `ERR 4 cannot
   cast ...` line and exits 4. The "/error 5" is read as pointing at the pre-existing
   malformed-input class for reference.
2. Invalid JSON in such a cell is a malformed-input error (exit 5) regardless of
   `--on-type-error`.
3. `--on-type-error` decides between nulling/keeping, but its `fail` mode exits 5 here
   rather than 4, since the spec names 5 in this bullet.

### Choice
Alternative 1. The casting section says a cast failure under `fail` emits `ERR 4 ... in
field "<path>"`, and this is a cast failure in a field; making the same user mistake
exit 4 in JSONL and 5 in CSV would be arbitrary. Alternative 2 also contradicts the
first half of the same bullet.

### Risk: 45
Most likely author preference: alternative 3 - `fail` on an unparsable JSON cell exits 5.

---

## T62. Bare `array`/`map` with no element or value type

### Spec Text
> * **array\<T>**: homogeneous element type T (can be nested)
> * **map\<string,T>**: string keys only; value type T can be nested or primitive

### Alternatives
1. **(chosen)** The parameter is mandatory: `"array"`, `"list"` and `"map"` on their own
   are unknown types and exit 3, just like `"widget"`.
2. They default to a free-form JSON element/value type.
3. They default to `string`.

### Choice
Alternative 1. Both kinds are written with their parameter everywhere in the spec, and
inventing a default would silently accept a schema the author would have rejected.
Erroring is also the recoverable direction: a hidden fixture is far more likely to test
that a nonsense type errors than that a truncated one works.

### Risk: 15
Most likely author preference: same - bare `array`/`map` rejected.

---

## T63. Can a path descend into a `json`-typed column?

### Spec Text
> * Each path must resolve to primitive value after casting
> * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. **(chosen)** Yes. A `json` column has no declared shape, so the path is checked per
   row instead of against the schema: a row whose value at that path is a primitive (or
   null/missing) contributes that fragment, and a row whose value there is an object or
   array raises `ERR 3` and exits 3. A `json` column named with no path at all is
   rejected up front - it is not a primitive.
2. Any path into a `json` column is rejected up front, because it cannot be proven
   primitive from the schema.
3. Non-primitive values found at run time are silently treated as null fragments.

### Choice
Alternative 1. The rule is phrased about the *value* "after casting", not about the
declared type, which points at a run-time check wherever a static one is impossible.
The spec's own second example sorts by a primitive key while carrying a `json` column,
so a schema containing `json` must not be crippled for key purposes.

### Risk: 30
Most likely author preference: alternative 2 - static rejection of paths into `json`.

---

## T64. Wording of the error 3 line for a partition path

### Spec Text
> * Each path must resolve to primitive value after casting
>   * Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. **(chosen)** Keys report `key column "<path>"`, partitions report the parallel
   `partition column "<path>"`; both exit 3.
2. Both report the literal `key column "<path>"` text, since the section covers keys and
   partitions together.

### Choice
Alternative 1. The paragraph is headed "Keys & Partitioning with Nested" and describes
both, but calling a `--partition-by` path a "key column" would be actively misleading;
prior checkpoints already used the "partition column ..." wording for its sibling error.

### Risk: 25
Most likely author preference: alternative 2 - one shared message that always says
"key column".

---

## T65. A string that happens to contain JSON, in a field declared nested

### Spec Text
> * **JSONL**: Accept nested objects/arrays only when schema declares column as nested or `json`

### Alternatives
1. **(chosen)** For JSONL and Parquet the *value* must already be structured: a JSON
   *string* like `"{\"a\":1}"` in a column declared `struct` is a cast failure handled
   per `--on-type-error`. Only CSV/TSV cells are parsed as JSON text, because there the
   cell is text by definition.
2. Any string is re-parsed as JSON wherever the target type is nested, in every format.

### Choice
Alternative 1. The spec draws the parse-the-text rule specifically under CSV/TSV, and
JSONL values "come typed" per earlier checkpoints - re-parsing strings would make the
format-specific bullet redundant.

### Risk: 20
Most likely author preference: same, with the string treated as an ordinary failed cast.

---

## T66. Null handling inside nested values

### Spec Text
> * Primitive casting rules, temporal normalization, null handling apply recursively inside nested values

### Alternatives
1. **(chosen)** The `--csv-null-literal` test that turns a cell into null also applies
   to string leaves inside nested values: an empty string (or the configured literal)
   at a leaf becomes JSON `null`, whatever the leaf's declared type.
2. Only JSON `null` is null inside nested values; the CSV null literal is an output/CSV
   concern and empty strings survive as `""`.

### Choice
Alternative 1. The sentence lists "null handling" alongside casting and temporal
normalisation as things that "apply recursively", and the established rule from earlier
checkpoints is that an empty string is a null cell. Note the converse still holds at the
top level only: the CSV null *literal* is emitted for a whole-column null, never inside
the JSON, where `null` is written.

### Risk: 40
Most likely author preference: alternative 2 - empty strings stay empty strings inside
nested values.

---

## T67. Are struct field names matched case-sensitively, and are extra input keys kept?

### Spec Text
> * **struct**: ordered list of named fields (names unique within struct)
> * All struct fields included (even when null) with explicit `null` values

### Alternatives
1. **(chosen)** Field names match exactly (case-sensitively); an input key that no
   declared field matches is dropped, and a declared field with no matching input key is
   `null`. The emitted object therefore has exactly the declared fields, in declared
   order.
2. Extra input keys are preserved after the declared ones.
3. Extra input keys are an error.

### Choice
Alternative 1. "All struct fields included (even when null)" describes the emitted
object exhaustively in terms of the declared fields, and case-insensitivity is only ever
claimed for *type* names, not field names. Dropping undeclared keys also mirrors how
undeclared top-level columns are already handled.

### Risk: 10
Most likely author preference: same.

---

## T68. Can an alias file redefine a built-in alias?

### Spec Text
> * Built-in aliases (always present):
> * Optional alias file via `--type-alias-file <ALIASES_JSON>`
>   * May refer to built-ins or other aliases

### Alternatives
1. **(chosen)** The file's entries are layered over the built-in table, so
   `{"number": "string"}` makes `number` mean `string`. "Always present" is read as
   "the built-in *names* always resolve to something", not "are immutable".
2. Built-ins win, and a file entry that repeats a built-in name is ignored.
3. Redefining a built-in is an error.

### Choice
Alternative 1. A user-supplied table that silently loses to the defaults would be a
surprising way to spell "always present", and layering is the ordinary meaning of an
override file. Note that no *primitive* name (`int`, `string`, ...) can be shadowed this
way, because primitives are matched only after the alias chain has been followed and the
built-ins never map a primitive name onto anything.

### Risk: 20
Most likely author preference: alternative 2 - built-ins take precedence, if the
implementation builds `{**user, **builtin}` in that order.
