# Ambiguities

Each entry records a place where the spec admits more than one conforming
behaviour, the reading this implementation chose, and the risk that the spec
author's own implementation (and therefore the hidden tests) reads it
differently.

## T1. Backslash escaping while reading input

### Spec Text
> escape character defaults to doubling the quote (`""`) and accepts backslash-escapes (`\"`), overrideable via flags

### Alternatives
1. Configure the CSV reader with `escapechar="\\"` (plus `doublequote=True`), so a
   backslash escapes the following character anywhere in a record.
2. Unescape only the exact sequence `\"` inside quoted fields, leaving every
   other backslash as literal data (so `C:\tmp` survives untouched).

### Choice
Alternative 1. It is the single-line `csv.reader(..., escapechar="\\")` spelling
the flag name (`--csv-escapechar`) already implies, and it is the only reading
under which `--csv-escapechar` has a meaning for the reader.

### Risk: 25
Author's likely preference if different: backslash consumed only before a quote
character, so that literal backslashes in ordinary text are preserved.

## T2. Do the dialect flags affect the output too?

### Spec Text
> Quote character defaults to `"` ... overrideable via flags

> Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives
1. `--csv-quotechar` / `--csv-escapechar` describe the *input* dialect only; the
   output dialect is always comma, `"`, doubled quotes.
2. One dialect object is shared, so `--csv-quotechar "'"` also quotes output
   fields with `'`.

### Choice
Alternative 1. The "Deterministic Dialect Details" section states the output
quote character as a fact rather than as a default, and calls the output
deterministic, which only holds if the flags do not reach it.

### Risk: 35
Author's likely preference if different: a single dialect built from the flags
and handed to both the reader and the writer.

### Resolved by checkpoint 2
> Use configured CSV dialect flags for output quoting/escaping and chosen null
> literal

Alternative 2 is now the specified behaviour: `--csv-quotechar` and
`--csv-escapechar` configure the writer as well as the reader. The
implementation and the test for this entry were changed accordingly; see T33
for what "escaping" then means on output.

## T3. Empty strings during `strict` inference

### Spec Text
> `strict` (default): infer types based on observed values; columns with conflicting types across files fall back to `string`

> `loose`: prefer numeric/temporal types if all non-null observed values parse; otherwise fall back to `string`; empty strings are treated as nulls and don't affect inference

### Alternatives
1. The "empty strings are nulls" rule is stated only for `loose`, so in `strict`
   an empty cell is an observed value that only `string` accepts: a column with
   any empty cell is inferred as `string`.
2. Empty cells are nulls in both modes; the modes differ only in how per-file
   types are combined.

### Choice
Alternative 1. The clause is attached to `loose` as one of the things that make
it loose, which only distinguishes the modes if `strict` does the opposite.

### Risk: 45
Author's likely preference if different: empty cells ignored by inference in
both modes, with `strict` differing only by the per-file agreement rule.

## T4. `strict` with an int column in one file and a float column in another

### Spec Text
> columns with conflicting types across files fall back to `string`

### Alternatives
1. Any disagreement between per-file types, including `int` vs `float`, resolves
   to `string`.
2. Numerically compatible types widen (`int` + `float` -> `float`) and only
   genuinely incompatible types fall back to `string`.

### Choice
Alternative 1: the sentence says "conflicting types", without an exception for
numeric widening, and widening is exactly what `loose` is described as doing.

### Risk: 25
Author's likely preference if different: widen `int` + `float` to `float` in
`strict` as well.

## T5. `timestamp` versus `date` for a bare `YYYY-MM-DD`

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`

> `date`: ISO-8601 `YYYY-MM-DD`; `timestamp`: ISO-8601 format

### Alternatives
1. Inference only calls a value a timestamp when it carries a time of day, so
   `2024-07-01` is inferred as `date`; casting a bare date into a declared
   `timestamp` column still succeeds and yields midnight UTC.
2. A bare date is an ISO-8601 timestamp everywhere, which by the priority order
   makes `date` unreachable by inference.
3. A bare date is a `date` everywhere, so casting it into a `timestamp` column
   fails and follows `--on-type-error`.

### Choice
Alternative 1. The priority list only makes sense if `date` is reachable, and
casting is the more permissive direction ("cast every input cell into target
type").

### Risk: 30
Author's likely preference if different: alternative 3, where a `timestamp`
column rejects a date-only cell.

## T6. Which "standard values" a bool accepts

### Spec Text
> `bool` includes `1`/`0` along with standard values

### Alternatives
1. `true` / `false`, case-insensitive, plus `1` / `0`.
2. Additionally `yes` / `no`, `t` / `f`, `y` / `n`.

### Choice
Alternative 1: `true`/`false` are the values every CSV and JSON tool agrees on,
and a wider set would silently turn `yes`/`no` text columns into bools.

### Risk: 30
Author's likely preference if different: a wider set that also accepts
`yes`/`no` (and possibly `t`/`f`).

## T7. How a bool is rendered in the output

### Spec Text
> Cast every input cell into target type (rules below)

(The "Deterministic Dialect Details" section pins down temporal rendering but
says nothing about bools.)

### Alternatives
1. `true` / `false` (lower case), matching the input literals the spec names.
2. `True` / `False`, i.e. Python's `str(bool)`.
3. `1` / `0`.

### Choice
Alternative 1: lower case matches the literal spelling used in the spec's own
schema example and is the conventional CSV/JSON rendering.

### Risk: 40
Author's likely preference if different: `True` / `False` from a plain
`str(value)` on the parsed Python object.

## T8. Are successfully cast values re-rendered or echoed?

### Spec Text
> Cast every input cell into target type (rules below)

### Alternatives
1. The parsed value is rendered back, so `007` becomes `7`, `-2.50` becomes
   `-2.5`, and `3` in a `float` column becomes `3.0`.
2. The original text is echoed whenever the cast succeeds, and only nulls and
   temporal normalisation change the text.

### Choice
Alternative 1: "cast every input cell into target type" describes a conversion,
and the spec separately calls out `keep-string` as the mode that preserves
original text.

### Risk: 30
Author's likely preference if different: echoing the original text for numeric
columns while still normalising timestamps.

## T9. Rendering of fractional seconds

### Spec Text
> `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`), keeping fractional seconds

### Alternatives
1. Render from the parsed datetime, i.e. no fraction when it is zero and six
   digits otherwise (`...T12:00:00.500000Z` for an input of `...T12:00:00.5`).
2. Preserve the digit count that the source had (`...T12:00:00.5Z`).

### Choice
Alternative 1: it is what `datetime.isoformat()` produces, and "keeping
fractional seconds" reads as "do not truncate them" rather than as a
digit-for-digit promise.

### Risk: 35
Author's likely preference if different: preserving the source's own number of
fractional digits.

## T10. Is `--csv-null-literal` recognised on input?

### Spec Text
> Missing values emitted as the null literal (default empty string; override with `--csv-null-literal`)

### Alternatives
1. The literal is both written for nulls and recognised as a null on input, so a
   merge round-trips.
2. It is output-only; on input only an empty cell is null.

### Choice
Alternative 1, so that `--csv-null-literal NA` on a file previously produced by
this tool gives back the same nulls instead of `NA` strings.

### Risk: 25
Author's likely preference if different: output-only, which makes `NA` in an
`int` column a cast failure under `--on-type-error fail`.

## T11. Default memory limit

### Spec Text
> `[--memory-limit-mb <INT>]`

### Alternatives
1. Default to 64 MB, the figure the performance section uses as its example.
2. No limit unless the flag is given (sort everything in memory).

### Choice
Alternative 1: the tool is required to work on arbitrarily large inputs, which
an unbounded default cannot guarantee.

### Risk: 10
Author's likely preference if different: an unbounded default, which is only
observable through memory use, not through output.

## T12. A column with no observed non-null value

### Spec Text
> `strict` (default): infer types based on observed values

### Alternatives
1. With nothing observed, fall back to `string`.
2. Keep the highest priority type (`timestamp`) since no value contradicts it.

### Choice
Alternative 1: `string` is the spec's fallback everywhere else, and every cell
of such a column is a null anyway, so only the header type differs.

### Risk: 15
Author's likely preference if different: also `string`; the only visible
difference would be a column of nulls used as a sort key.

## T13. Ordering of values kept by `keep-string`

### Spec Text
> `keep-string`: emit original text as string

> Nulls always compare less than non-null values, regardless of sort direction

### Alternatives
1. Within a key column, properly cast values sort among themselves and kept text
   sorts after all of them (but still after nulls).
2. Compare every cell by its rendered text once any cell was kept as a string.
3. Compare the raw Python objects, which raises on `int` vs `str`.

### Choice
Alternative 1: it keeps the ordering of the well-typed majority intact, is
total, and never compares values of different Python types.

### Risk: 40
Author's likely preference if different: alternative 2, comparing the rendered
text of the whole column once any cell fails to cast.

## T14. `bool` outranks `int`, so `0`/`1` columns infer as bool

### Spec Text
> Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`

> `bool` includes `1`/`0` along with standard values

> Inference recognises values by the casting rules below

### Alternatives
1. Follow the priority list literally: a column whose values are all `0`/`1` is
   a `bool` column and is emitted as `true`/`false`.
2. Treat `1`/`0` as bools only when casting into a declared `bool` column, and
   let inference see them as ints.

### Choice
Alternative 1: the three quoted sentences together say inference uses the
casting rules and prefers `bool` over `int`.

### Risk: 35
Author's likely preference if different: alternative 2, keeping numeric-looking
identifier columns as ints.

## T15. Blank lines inside an input

### Spec Text
> All inputs are UTF-8, RFC-4180 compliant, with a **header row**

### Alternatives
1. A blank line carries no record and is skipped.
2. A blank line is a record whose every column is null.

### Choice
Alternative 1: RFC-4180 has no empty record, and emitting an all-null row for a
stray newline would invent data.

### Risk: 15
Author's likely preference if different: whatever `csv.reader` yields, i.e. an
all-null row.

## T16. Exit codes

### Spec Text
> `fail`: write error to stderr and exit non-zero

### Alternatives
1. `1` for runtime errors (bad cast, unknown key column, unreadable input) and
   argparse's `2` for usage errors.
2. A single non-zero code for everything.

### Choice
Alternative 1, since the spec only requires "non-zero" and argparse already
owns the usage-error code.

### Risk: 5
Author's likely preference if different: a different specific code; tests can
only reasonably assert "non-zero".

## T17. Rows with the wrong number of fields

### Spec Text
> All inputs are UTF-8, RFC-4180 compliant, with a **header row**

### Alternatives
1. Pad a short row with nulls and ignore fields beyond the header width.
2. Treat a ragged row as an error.

### Choice
Alternative 1: it matches the spec's own treatment of a column that is missing
from a file (filled with the null literal) and keeps the tool streaming.

### Risk: 20
Author's likely preference if different: also padding, since `csv.DictReader`
behaves this way by default; an error is the less likely reading.

## T18. An input file with no header line at all

### Spec Text
> All inputs are UTF-8, RFC-4180 compliant, with a **header row**

### Alternatives
1. A zero-byte file contributes no columns and no rows.
2. A missing header row is an error.

### Choice
Alternative 1: `data/*.csv` style invocations routinely pick up an empty file,
and the merge result is unambiguous.

### Risk: 20
Author's likely preference if different: erroring on a file without a header.

## T19. Repeating `--key`

### Spec Text
> `--key <col>[,<col>...]`

### Alternatives
1. Accept both `--key a,b` and `--key a --key b`, concatenating in order.
2. Accept only the comma-separated form; a second `--key` replaces the first.

### Choice
Alternative 1: it is a superset of the documented form, so anything the spec
describes still behaves as written.

### Risk: 5
Author's likely preference if different: last-flag-wins, which the documented
usage never exercises.

## T20. A run that fails after output has started

### Spec Text
> All intermediate resources must be cleaned up on exit

### Alternatives
1. A file destination is written through a temporary sibling file and moved into
   place on success, so a failed run leaves no output file.
2. Write straight to the destination, leaving a truncated file behind on
   failure.

### Choice
Alternative 1: it is the only way "cleaned up on exit" can hold for a failing
run, and successful runs are indistinguishable.

### Risk: 10
Author's likely preference if different: writing straight to the destination
(observable only by inspecting the file after a failed run).

## T21. Surrounding whitespace in typed cells

### Spec Text
> `int`, `float`, `string`: standard parsing

### Alternatives
1. Strip surrounding whitespace before parsing non-string types; `string` cells
   keep their spacing verbatim.
2. Never strip, so ` 5 ` fails to cast to `int`.

### Choice
Alternative 1: `int(" 5 ")` succeeds in Python, so "standard parsing" most
plausibly tolerates padding, while a string column must stay byte-faithful.

### Risk: 25
Author's likely preference if different: no stripping, so padded numbers become
nulls (or stay strings during inference).

## T22. Exotic numeric literals

### Spec Text
> `int`, `float`, `string`: standard parsing

### Alternatives
1. Accept only plain decimal integers and decimal/exponent floats, rejecting
   `1_000`, `nan`, `inf`, `0x1f` (all of which Python's `int()`/`float()` take).
2. Accept whatever `int()` / `float()` accept.

### Choice
Alternative 1: `1_000` and `Infinity` are not CSV numbers, and accepting them
would let inference retype clearly textual columns.

### Risk: 15
Author's likely preference if different: a bare `int()` / `float()` in a
`try/except`, which also accepts `nan` and underscores.

## T23. What counts as a compression "mismatch"

### Spec Text
> `--compression=none` forces no decompression; `--compression=gzip` forces gzip

> Mismatch is error 5

### Alternatives
1. A mismatch is a disagreement between the compression the tool is going to
   apply and what the file's first two bytes say: `--compression=gzip` on a file
   without the `1f 8b` magic, `--compression=none` on a file that has it, and in
   `auto` mode a `.gz` name whose content is not gzip. A gzip body under a name
   without `.gz` is accepted in `auto` mode, because the magic bytes are part of
   detection.
2. A mismatch is only the `.gz` extension disagreeing with `--compression`, so
   `--compression=none data.csv.gz` is the error and content is never inspected.
3. A mismatch is only a gzip decoding failure raised while reading.

### Choice
Alternative 1. The detection rules elsewhere in the section are explicitly
"by extension and magic bytes", so the magic bytes are the authority a forced
flag can contradict; and it is the only reading under which both forcing
directions are checkable before any data is produced.

### Risk: 45
Author's likely preference if different: alternative 2, comparing the flag with
the `.gz` extension only.

## T24. Magic bytes versus a known extension

### Spec Text
> `--input-format=auto` (default): detect per file by extension and magic bytes

> If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2

### Alternatives
1. A recognised extension decides the format outright; magic bytes are only
   consulted when the extension is not one of the five listed ones ("ambiguous"
   means "not recognised"), and then only to spot Parquet.
2. Magic bytes always win, so `PAR1` content named `data.csv` is read as
   parquet.
3. A recognised extension that disagrees with the magic bytes is an error.

### Choice
Alternative 1. The sentence guards the magic-byte rule with "if extension is
ambiguous", which only adds information if a recognised extension is decided
without them.

### Risk: 30
Author's likely preference if different: alternative 2, sniffing `PAR1` on every
input regardless of its name.

## T25. Detecting a literal tab inside a TSV field

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required, `\n` or `\r\n` line endings; literal tabs inside field not allowed (error 5)

### Alternatives
1. Without quoting a stray tab is indistinguishable from a delimiter, so the
   observable symptom is a row with more fields than the header has columns;
   that is reported as error 5. A short row is still padded with nulls, as in
   checkpoint 1.
2. Rows of any width are tolerated (padded/truncated like CSV) and the sentence
   is only documentation of an input assumption, never enforced.
3. Any row width other than the header's width, short rows included, is error 5.

### Choice
Alternative 1. The spec attaches an error code to the rule, so something must be
enforced, and a surplus field is exactly the trace a literal tab leaves.

### Risk: 40
Author's likely preference if different: alternative 3, treating any ragged TSV
row as error 5.

## T26. Quote characters inside TSV data

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting

### Alternatives
1. "No quoting" means the reader performs no quote processing at all: `"x"`
   arrives as the three-character value `"x"`, and `--csv-quotechar` does not
   apply to TSV inputs.
2. TSV is read with the same quoting rules as CSV, just with a tab delimiter.

### Choice
Alternative 1: the phrase is listed as a property of the TSV dialect, in
contrast with the CSV entry that names a quote character.

### Risk: 15
Author's likely preference if different: also no quoting; the only visible
difference is an input whose fields contain quote characters.

## T27. A JSONL line that is valid JSON but not an object

### Spec Text
> **JSONL**: one UTF-8 JSON object per line; objects must be flat (no arrays/objects as values)

> Flat-only enforcement for JSONL/Parquet; nested structures trigger error 6

### Alternatives
1. A line that does not parse as JSON is a malformed source (error 5); a line
   that parses but is not an object, and an object with a list or dict value,
   are both violations of the flat-object rule (error 6).
2. Anything that is not a flat object is error 5, with error 6 reserved for
   parquet.
3. A top-level array is error 6 (it is nested) but a top-level scalar is error 5.

### Choice
Alternative 1. The determinism checklist names "flat-only enforcement for
JSONL/Parquet" as the error 6 rule, and "one JSON object per line" is the same
flatness requirement applied to the line itself.

### Risk: 35
Author's likely preference if different: alternative 3, where a bare scalar line
is a parse error rather than a flatness error.

## T28. The precedence order behind `--schema-strategy=authoritative`

### Spec Text
> `--schema-strategy=authoritative` (default): prefer typed sources in precedence order; JSONL ranks equal to CSV.

### Alternatives
1. Parquet is the only source that carries a declared schema, so it is the one
   "typed source": if any parquet input has the column, its declared type wins;
   otherwise CSV, TSV and JSONL are pooled and resolved exactly as in
   checkpoint 1 (by `--infer`). The second sentence is what demotes JSONL out of
   the typed tier.
2. Three tiers, parquet > jsonl = csv > tsv.
3. JSONL is a typed source too and ties with CSV only when they disagree, with
   some other rule breaking the tie.

### Choice
Alternative 1. "JSONL ranks equal to CSV" is only worth saying if JSONL would
otherwise have counted as typed, which leaves parquet alone at the top and makes
the default behave exactly like checkpoint 1 when no parquet input is present.

### Risk: 45
Author's likely preference if different: a fixed precedence list such as
parquet > jsonl > csv > tsv applied per column without regard to `--infer`.

## T29. Counting votes for `--schema-strategy=consensus`

### Spec Text
> `--schema-strategy=consensus`: choose type that majority of files support

### Alternatives
1. Each file votes with the type it infers for the column on its own; the most
   voted type wins, ties broken by the spec's type priority. A value that does
   not fit the winner then follows `--on-type-error`.
2. Every file "supports" a whole set of types (those all its values fit) and the
   type supported by the most files wins.
3. As 1, but a type needs a strict majority (more than half the files) or the
   column falls back to `string`.

### Choice
Alternative 1. Alternative 2 is the more literal reading of "support", but every
text source supports `string`, so the set-based count always lands on the
intersection of the supported sets - which is exactly what `union` is defined to
do, leaving two of the three strategies indistinguishable. Alternative 1 is the
only reading that makes `consensus` a strategy of its own: two integer files and
one text file yield an `int` column whose stray text is coerced.

### Risk: 50
Author's likely preference if different: the same plurality vote with a
different tie-break, most plausibly the type of the first file that reaches the
winning count.

## T30. "Simplest common type" for `--schema-strategy=union`

### Spec Text
> `--schema-strategy=union`: choose simplest common type that can hold all observed values

### Alternatives
1. Intersect the per-file supported sets and take the highest priority type left,
   falling back to `string` when the intersection is empty. `int` plus `float`
   becomes `float`; `int` plus `abc` becomes `string`.
2. "Simplest" means lowest priority, i.e. always `string` whenever more than one
   type is in play.

### Choice
Alternative 1: "that can hold all observed values" is the constraint and
"simplest" selects among the types that satisfy it, which is exactly what
`--infer loose` already does within a file.

### Risk: 20
Author's likely preference if different: a widening lattice that stops at
`string` only for genuinely unrelated types, which agrees with this choice on
every example in the spec.

## T31. JSONL numbers that are integral floats

### Spec Text
> For JSONL numbers, prefer `int` if integer and within range; otherwise `float`

### Alternatives
1. The test is on the value: `5` and `5.0` both become the integer `5`, provided
   it fits in a signed 64-bit range; `5.5` and `1e300` stay floats.
2. The test is on the JSON literal: `5` is an int, `5.0` keeps its decimal point
   and stays a float.

### Choice
Alternative 1: "if integer" describes the number, not its spelling, and "within
range" is a value test as well, so both clauses read as properties of the value.

### Risk: 35
Author's likely preference if different: alternative 2, i.e. Python's own
`json` typing, where `5.0` arrives as a float and stays one.

## T32. Are JSONL string values inspected by the type recognisers?

### Spec Text
> JSONL values come typed (string/number/bool/null)

> Column set: union of all encountered field names ... Type inference per `--infer` mode

### Alternatives
1. Inference recognises a JSONL string exactly as it would the same text in a
   CSV cell, so `"2024-07-01T12:00:00Z"` contributes a timestamp observation.
2. A JSON string is a `string` observation and nothing else, so any column a
   JSONL file writes as text infers as `string`.

### Choice
Alternative 1. The spec's own example sorts a mixed CSV/JSONL/Parquet merge by a
`ts` key, which JSON can only carry as a string; under alternative 2 that column
would degrade to text ordering.

### Risk: 30
Author's likely preference if different: alternative 2, taking the JSON type at
face value and only ever inferring `string` from JSONL text.

## T33. What the dialect flags mean for the output

### Spec Text
> Use configured CSV dialect flags for output quoting/escaping and chosen null literal

### Alternatives
1. Hand `--csv-quotechar` and `--csv-escapechar` to the writer as well as the
   reader, keeping `doublequote` on so quotes are still escaped by doubling and
   the escape character escapes itself. Output then round-trips through the same
   flags, but a literal backslash is written as `\\` while the default escape
   character is in force.
2. Pass only the quote character to the writer and leave the escape character
   for the reader, so output quoting stays "escape by doubling" exactly.

### Choice
Alternative 1: the sentence names quoting *and* escaping, and only a writer that
also applies the escape character produces a file the same flags can read back.

### Risk: 40
Author's likely preference if different: alternative 2, where the output escapes
by doubling quotes only and backslashes are emitted verbatim.

## T34. Exit codes the checkpoint does not number

### Spec Text
> Exact exit codes and stderr message shape as specified

(The checkpoint numbers 2 for undetectable formats, 3 for a key column absent
from the resolved schema, 5 for dialect/compression violations and 6 for nested
structures.)

### Alternatives
1. Use the four numbered codes for exactly the conditions that name them, keep
   argparse's 2 for usage errors (it coincides with the format code), and leave
   every other error - a failed cast under `--on-type-error fail`, an unreadable
   input, a malformed `--schema` file - on the generic code 1 that checkpoint 1
   used.
2. Spread those remaining errors over the unused codes (for instance 4 for I/O
   and 5 for a failed cast).

### Choice
Alternative 1: checkpoint 1 only required "non-zero" for those conditions, so
changing them now would be inventing a taxonomy the spec never states.

### Risk: 35
Author's likely preference if different: a fuller taxonomy in which an I/O
failure is 4 and a cast failure under `fail` has its own code.

### Resolved by checkpoint 4
> `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>"
> (file=... line=...)`

A failed cast does have a code of its own after all: 4. The other conditions
this entry lists - an unreadable input, a malformed `--schema` file - stay on
code 1. See T47 for the reading of `ERR 4` this implementation follows.

## T35. The meaning and default of `--parquet-row-group-bytes`

### Spec Text
> Parquet reading must be streamed row group-wise; `--parquet-row-group-bytes` is advisory for batch sizing

### Alternatives
1. It is a byte budget per batch: the reader converts it into a row count using
   the file's own average row size and asks pyarrow for batches of that many
   rows, clamped to a sane range. Unset, it defaults to 8 MiB.
2. It is ignored entirely, since it is "advisory".
3. It selects whole row groups rather than sizing batches within them.

### Choice
Alternative 1: the flag is documented as advisory *for batch sizing*, so it
influences batch size without being a hard guarantee, and no output can depend
on the value.

### Risk: 10
Author's likely preference if different: any of these; the flag is explicitly
advisory and cannot change the merged output.

## T36. Does the null literal apply to typed sources?

### Spec Text
> If JSONL/Parquet value is `null` or CSV/TSV cell is empty, treat as missing -> emit null literal

### Alternatives
1. Nullness is decided per source kind exactly as written: for JSONL and parquet
   only a real `null` is missing (an empty JSON string stays an empty string),
   while for CSV and TSV an empty cell - or one equal to `--csv-null-literal` -
   is missing.
2. `--csv-null-literal` is also matched against JSONL and parquet strings.

### Choice
Alternative 1. The sentence lists the missing-value test separately for typed
and text sources, and the flag is named for the CSV dialect.

### Risk: 25
Author's likely preference if different: alternative 2, one null literal matched
against every string value whatever its source.

## T37. A TSV input with no header line

### Spec Text
> **TSV**: delimiter is tab (`\t`), no quoting, header row required

### Alternatives
1. "Header row required" is enforced: an empty TSV file is error 5.
2. An empty file contributes nothing, as for CSV in checkpoint 1 (T18).

### Choice
Alternative 1: the requirement is stated for TSV only, which distinguishes it
from the CSV entry, and the dialect violations of that same sentence are error 5.

### Risk: 30
Author's likely preference if different: alternative 2, an empty input of any
format simply contributing no rows.

## T38. Writing into an output directory that already exists

### Spec Text
> When any partitioning flag provided: `--output` must be directory path (not `-`)
>   - Create directory if doesn't exist
>   - Perform atomic write by creating sibling temp directory and renaming on success

### Alternatives
1. The rename replaces whatever is at `--output`: a previous tree (or any other
   file at that path) is removed once the new tree is complete, so the run's
   output is exactly the tree it produced.
2. The new tree is merged into the existing directory, leaving part files from
   earlier runs in place beside the new ones.
3. A non-empty destination is refused with an error.

### Choice
Alternative 1. "Renaming on success" only describes a single rename of the temp
directory onto `--output`, which cannot leave earlier content behind, and the
determinism checklist wants the layout to follow from the rules alone rather
than from what happened to be on disk. A stale `part-00007.csv` from a previous,
larger run would otherwise be indistinguishable from output of this run.

### Risk: 30
Author's likely preference if different: create the destination up front and
move (or write) the part files into it, so leftovers from an earlier run survive.

## T39. Do partition columns still appear inside the part files?

### Spec Text
> Emit directory tree inside `--output` using Hive-style segments

> Each file contains header row (resolved schema header)

> Every output CSV includes header row in resolved schema column order

### Alternatives
1. Every part file carries the full resolved schema, partition columns included,
   so the value appears both in the path and in every row.
2. Hive's own convention: the partition columns are projected out of the data
   files because the path already carries them.

### Choice
Alternative 1. The spec states the header twice, both times as the *resolved
schema* header with no exception for partition columns, and the "independently
valid CSV" requirement reads more naturally when a file does not need its path
to be understood.

### Risk: 15
Author's likely preference if different: drop the partition columns from the
part files, following Hive literally.

## T40. Is the column name of a Hive segment percent-encoded too?

### Spec Text
> `<col1>=<val1>/<col2>=<val2>/.../`
>   - Values use percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`

### Alternatives
1. Only the value is encoded; the column name is written exactly as it appears
   in the resolved schema.
2. Both halves of a segment are encoded with the same rule.

### Choice
Alternative 1. The rule is stated for "values", and column names come from the
resolved schema rather than from data, so they are not the part of the segment
the spec is guarding against.

### Risk: 15
Author's likely preference if different: run the same encoder over the column
name, which only shows up when a header itself contains an exotic character.

## T41. What counts as a null partition value

### Spec Text
> Null (missing) partition values use literal `_null`

### Alternatives
1. `_null` stands for every value the tool considers null at output time: an
   absent column, an empty cell, a cell equal to `--csv-null-literal`, and a
   cell that `--on-type-error coerce-null` turned into a null.
2. `_null` stands only for a column absent from that input's schema, while an
   empty cell yields the empty segment `col=`.

### Choice
Alternative 1. The tool already has one notion of null - the one the null
literal renders on output - and the spec's parenthetical "(missing)" matches it.
Under alternative 2 a partition directory could have an empty segment
(`country=/`), which no other rule anticipates.

### Risk: 20
Author's likely preference if different: only structurally absent values become
`_null`, with an empty string kept as an empty segment.

## T42. A run that produces no rows at all

### Spec Text
> Within each partition directory, write CSV files named sequentially:
> `part-00000.csv`, `part-00001.csv`, ...

### Alternatives
1. Part files are created when their first row arrives, so an empty result is an
   empty output directory - with field partitioning there are no partitions, and
   with sharding alone there is nothing to shard.
2. The sharded stream always yields at least `part-00000.csv`, holding only the
   header, mirroring the single-file mode that always writes a header.

### Choice
Alternative 1. Field partitioning forces lazy file creation (a partition only
exists because a row named it), and using one rule for both modes keeps the
layout a function of the rows that exist.

### Risk: 35
Author's likely preference if different: a header-only `part-00000.csv` when
sharding without field partitioning, because their writer opens the first shard
before reading the stream.

## T43. A `--partition-by` column that is not in the resolved schema

### Spec Text
> `[--partition-by <col>[,<col>...]]`

### Alternatives
1. Reuse the exit code for a missing `--key` column (3), since both are
   "a column named on the command line is not in the resolved schema".
2. Treat it as a usage error (exit 2).

### Choice
Alternative 1. The two flags name columns of the same resolved schema and the
failure is detected at the same point, so the tool reports it the same way,
with a message naming `--partition-by`.

### Risk: 40
Author's likely preference if different: exit 2, keeping code 3 reserved for the
key columns the earlier checkpoint numbered.

## T44. Zero or negative file limits

### Spec Text
> `--max-rows-per-file <INT>` ... `--max-bytes-per-file <INT>`

### Alternatives
1. Reject values below 1 as usage errors (exit 2): no file can hold at most zero
   rows, and the byte exception already covers limits smaller than one row.
2. Accept `0` and let the oversize exception put one row in every file.

### Choice
Alternative 1. A limit of zero states an impossible requirement rather than a
degenerate one, and argparse already owns this class of complaint, so the user
gets the usual usage message instead of a directory full of one-row files.

### Risk: 25
Author's likely preference if different: no validation at all, with `0`
behaving like `1`.

## T45. Emission order across partitions

### Spec Text
> With field partitioning: rows in each partition directory must be sorted by
> `--key` within that partition

> in exact order rows are emitted from sorted stream

### Alternatives
1. With field partitioning the stream is grouped by partition value first and by
   `--key` inside each group, so one part file is open at a time.
2. The globally key-sorted stream is walked as is and rows are appended to
   whichever partition they belong to, keeping every partition's file open.

### Choice
Alternative 1. Both produce identical bytes - the spec only constrains order
*within* a partition - but grouping first bounds the number of open files by
one, which is what "arbitrarily large inputs" needs when the partition count is
large.

### Risk: 10
Author's likely preference if different: a writer per partition held open, which
gives the same files.

## T46. More than 100000 part files in one directory

### Spec Text
> `part-00000.csv`, `part-00001.csv`, ... (zero-padded width 5)

### Alternatives
1. Width 5 is a minimum: part 100000 is `part-100000.csv`.
2. The counter wraps or the run fails.

### Choice
Alternative 1. Zero padding describes how short numbers are written; dropping
digits would make two parts share a name.

### Risk: 5

## T47. The exit code and wording of a failed cast

### Spec Text
> `fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)`

> External sort/merge, partitioning, stability, and exit codes/messages continue
> from prior checkpoints

### Alternatives
1. `ERR n` names the exit code, as it demonstrably does for the checkpoint's
   other two numbered errors (`ERR 3 ... (exit 3)`, `ERR 6 ... (exit 6)`), so a
   failed cast now exits 4 and prints that line - for a flat column as much as
   for a field inside a nested one, since one caster serves both.
2. Keep the generic code 1 this implementation used for a failed cast until now
   (T34) and treat `ERR 4` as a message identifier only, or emit the `ERR 4`
   line for nested fields alone and leave flat columns on their old wording.

### Choice
Alternative 1. The two ERR numbers the checkpoint does spell out are exit codes,
so the third almost certainly is too, and the rule reads as one rule about
casting rather than as two that differ by where the value sat.

### Risk: 35
Author's likely preference if different: `ERR 4` for values inside nested
structures only, with a flat column's failure keeping whatever code and wording
checkpoint 1 gave it.

## T48. An unparsable JSON literal in a delimited cell

### Spec Text
> **CSV/TSV**: Cell must contain single JSON literal when target type is nested
> or `json`
>   - Empty cell → null
>   - Invalid JSON → handled per `--on-type-error`/error 5

### Alternatives
1. The policy decides: `coerce-null` nulls the cell, `keep-string` keeps its raw
   text, and `fail` reports error 5 - the code the sentence names, and the code
   checkpoint 3 already gives malformed JSON in a JSON Lines input.
2. The policy decides, and `fail` reports it as the cast failure it resembles,
   `ERR 4`.
3. Invalid JSON is always error 5, whatever `--on-type-error` says.

### Choice
Alternative 1. The sentence puts `--on-type-error` first, so the policy clearly
applies; the trailing "error 5" is then only reachable as what `fail` does, and
it matches the code a malformed JSON document gets elsewhere in the tool.

### Risk: 40
Author's likely preference if different: `ERR 4` for this too, since the value
is being cast to a declared type like any other.

## T49. The exit code for an unknown type name

### Spec Text
> Alias resolution is case-insensitive, transitive, cycle-checked; unknown types
> error deterministically

> May refer to built-ins or other aliases (resolve transitively; detect cycles
> proactively → error 2)

### Alternatives
1. "Deterministically" only promises the same error every time, so an unknown
   type stays on the bad-`--schema` code 1 the earlier checkpoints gave it, and
   2 is reserved for the cycle the spec numbers.
2. Both failures of type resolution share code 2, on the grounds that a schema
   naming a type the tool does not know is a usage error.

### Choice
Alternative 1. Checkpoint 1 already rejected an unsupported type with code 1 and
this checkpoint does not renumber it; only the cycle gets a number of its own.

### Risk: 40
Author's likely preference if different: code 2 for every type resolution
failure, cycles and unknown names alike.

## T50. Whether an alias may redefine a primitive

### Spec Text
> Built-in aliases (always present)

> Aliases apply after lowercasing names

### Alternatives
1. Primitive and kind names (`int`, `string`, `struct`, `array`, `map`) are
   terminal: resolution stops at them, so an alias file entry for `int` is dead
   and the six primitives always mean themselves. Aliases the file does define
   for other names override a built-in of the same name.
2. The alias table is consulted first, so `{"int": "string"}` really does make
   every `int` column a string column.

### Choice
Alternative 1. "Primitive types unchanged" is stated as a fact about this
checkpoint, and a schema whose `int` columns silently stopped being ints would
make the determinism checklist's "unknown types error deterministically" the
least of the surprises.

### Risk: 25
Author's likely preference if different: a plain lookup that lets any name be
remapped, primitives included.

## T51. Types written as text, and what a bare `struct` means

### Spec Text
> `list<T>`→`array<T>`

> `json`→`struct` (accept any JSON, see below)

### Alternatives
1. A type is either the object form the schema example shows or a text name, and
   the text form carries parameters: `array<int>`, `map<string,int>`,
   `list<map<string,int>>`. A bare `struct` - which is what `json` resolves to -
   is a struct with no declared fields, that is, any JSON value.
2. Only the object form may be parameterised; `list<T>`→`array<T>` is a
   shorthand for "the alias `list` behaves like `array` in the object form", and
   a bare `struct` is an error.

### Choice
Alternative 1. Both built-in entries are written as text generics, which only
means something if a declared type may be text; and reading `json`→`struct`
literally is what makes the two halves of that bullet agree.

### Risk: 20
Author's likely preference if different: text generics accepted but a bare
`struct` rejected, so that only `json` reaches the wildcard.

## T52. Non-ASCII characters in canonical JSON

### Spec Text
> Minified (no spaces), UTF-8, RFC 8259 JSON escaping

### Alternatives
1. "UTF-8" names the encoding of the output: a non-ASCII character is written as
   itself, and only the characters RFC 8259 requires escaping (quote, backslash,
   the controls below 0x20) are escaped.
2. Escape every non-ASCII character as `\uXXXX`, which RFC 8259 also permits.

### Choice
Alternative 1. Naming UTF-8 beside the escaping rule is otherwise redundant - the
whole output is UTF-8 already - and `\uXXXX` escaping would make the encoding
irrelevant to the cell's bytes.

### Risk: 25
Author's likely preference if different: `json.dumps` defaults, which escape
non-ASCII characters.

## T53. Key order inside a `json` column

### Spec Text
> Map keys sorted lexicographically

> For `json` type: accept any JSON value without casting; normalize only

### Alternatives
1. "Normalize" means the same canonical form the rest of the section describes,
   so an object inside a `json` value sorts its keys like a map.
2. A `json` value is reproduced with its keys in input order, since nothing
   declares it to be a map.

### Choice
Alternative 1. A `json` value is an undeclared map as far as the encoder is
concerned, and "normalize only" has little content if the only normalisation
available to an object is skipped.

### Risk: 30
Author's likely preference if different: input order preserved, with `json`
values re-emitted as they arrived.

## T54. A path that descends into a `json` column

### Spec Text
> Each path must resolve to primitive value after casting
>   - Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive`

### Alternatives
1. Resolution is static, against the declared schema: a `json` column declares
   nothing primitive anywhere inside it, so `flex.a` is error 3 before any row
   is read.
2. Resolution is dynamic: follow the path into each row's value and use whatever
   primitive is found there, nulling the fragment when it is a structure.

### Choice
Alternative 1. The checkpoint reports this error as a property of the path
rather than of a row, and a key whose type depends on the row could not be
compared under the typed ordering rules the same section invokes.

### Risk: 40
Author's likely preference if different: a dynamic lookup that lets a path reach
into a `json` column as long as it lands on a scalar.

## T55. Does the output dialect escape the backslashes of JSON escaping?

### Spec Text
> This JSON is the CSV cell content for nested columns

> Use configured CSV dialect flags for output quoting/escaping (checkpoint 2)

### Alternatives
1. The canonical JSON is the cell's *content*, and the writer then encodes that
   content in the output dialect as it would any other text: quotes doubled,
   and backslashes doubled because `--csv-escapechar` defaults to `\`. Reading
   the file back with the same dialect yields the JSON again.
2. Nested cells bypass the escape character, so the JSON text appears in the
   file with its backslashes untouched (quoting alone).

### Choice
Alternative 1. Checkpoint 2 made the dialect flags the writer's, without an
exception for any kind of cell, and only this reading round-trips under the
dialect the tool itself documents.

### Risk: 40
Author's likely preference if different: JSON written through with quote
doubling only, which is what a writer configured with no escape character does.

## T56. Path syntax: brackets, quotes and array indices

### Spec Text
> Field paths traverse structs, use numeric indices into arrays, and map lookups
> with bracketed, double-quoted string keys

> Array indices must be non-negative integers

> Map lookups with `["key"]` read value by exact key; quotes are required

### Alternatives
1. A dotted segment is a struct field name or, against an array, a run of digits
   naming an index; a bracketed segment must be a double-quoted string. A
   bracket without quotes (`attrs[country]`) is a malformed path - a usage error,
   exit 2 - while a segment that is well formed but cannot be followed (`items.x`,
   `items.-1`, a field the struct does not declare) is the resolution failure the
   checkpoint numbers 3.
2. Every malformed path is error 3 as well, since it arrives through `--key`.
3. Accept `items[0]` for indices too, and unquoted bracket keys as map lookups.

### Choice
Alternative 1. "Quotes are required" makes the unquoted form a syntax error
rather than a lookup that fails, and the checkpoint's own error 3 sentence is
about paths that do not *resolve*, which presumes they parse.

### Risk: 35
Author's likely preference if different: one code for both, most likely 3 for
anything a `--key` value does wrong.

## T57. A value whose shape does not match its declared kind

### Spec Text
> Nested values cast recursively to declared types

> On cast failure within nested structures: `coerce-null`: set field/element to
> JSON `null`

### Alternatives
1. A value of the wrong shape - an array where a struct is declared, a scalar
   where an array is - is one cast failure for that whole subtree, handled by
   the policy exactly like a scalar that will not parse.
2. It is a structural error that ends the run whatever `--on-type-error` says.

### Choice
Alternative 1. The checkpoint gives `--on-type-error` as the single answer to
"cast failure within nested structures", and a shape mismatch is discovered by
the same recursive cast as a bad scalar.

### Risk: 25
Author's likely preference if different: a hard structural error, at least for
parquet, whose declared schema could have been checked up front.

## T58. Input fields a struct does not declare

### Spec Text
> **struct**: ordered list of named fields (names unique within struct)

> All struct fields included (even when null) with explicit `null` values

### Alternatives
1. The declared fields are exactly the output fields: undeclared keys in the
   input are dropped, the way an undeclared column is.
2. Undeclared keys are carried through after the declared ones.

### Choice
Alternative 1. The output is "all struct fields", which the schema alone names,
and checkpoint 1 already drops input columns the resolved schema does not list.

### Risk: 15
Author's likely preference if different: keeping the extra keys, which would
also make the field order of two rows differ.

## T59. Parquet nesting that does not structurally match

### Spec Text
> **Parquet**: Accept nested structs/lists/maps only when schema declares
> compatible nested types

> With `--schema`, Parquet/JSONL nesting must structurally match and cast
> recursively

### Alternatives
1. "Must match" is enforced value by value during the recursive cast, so a
   mismatch is a cast failure and `--on-type-error` decides what becomes of it
   (see T57).
2. The parquet schema is compared with the declared schema before reading and a
   mismatch ends the run, error 6 or error 1.

### Choice
Alternative 1. It is the only rule that can also serve JSON Lines, which has no
schema to compare, and it keeps one answer for "the input does not fit the
declared type" across all four formats.

### Risk: 35
Author's likely preference if different: an up-front comparison of the parquet
schema against the declared one, failing the run when the shapes disagree.

## T60. A nested column a provided schema never selects

### Spec Text
> Without `--schema`, nested inputs not allowed (error 6)

> **Parquet**: ... Without schema, nested triggers error 6

### Alternatives
1. Error 6 is about running without a schema. With one, nesting is allowed
   everywhere in the input: a nested column the schema does not list is dropped
   like any other unlisted column.
2. Keep checkpoint 3's stricter reading, where a nested parquet column is
   rejected as soon as the file's schema is read even if a provided `--schema`
   never selects it.

### Choice
Alternative 1. Both statements of the rule are conditioned on the absence of
`--schema`, and this checkpoint's whole point is that a schema makes nesting
readable.

### Risk: 20
Author's likely preference if different: rejecting any nested column that no
declared column matches, so that nesting is never silently ignored.

### Note
Checkpoint 3's test for the stricter reading has been rewritten accordingly.

## T61. What `keep-string` keeps

### Spec Text
> `keep-string`: set to original unparsed JSON string or stringified form

### Alternatives
1. Inside a nested value, the failing field or element becomes a JSON string
   holding the text of what was there - the scalar's own text, or the JSON text
   of a subtree that did not fit. A whole cell that held no JSON literal at all
   is kept verbatim as the cell's text, exactly as `keep-string` treats a flat
   column.
2. Keep the whole cell verbatim whenever anything inside it fails, so one bad
   field discards the casting of its siblings.

### Choice
Alternative 1. "Set to ... `<value>`" is phrased per field and element, like the
`coerce-null` bullet above it, and a nested cell has to stay valid JSON for the
canonical encoding rules to mean anything.

### Risk: 30
Author's likely preference if different: the same, but writing an unparsable
cell out as a JSON string (`"{oops"`) rather than as its raw text.

## T62. The column half of a Hive segment for a field path

### Spec Text
> `--partition-by attrs["country"]`

> `<col1>=<val1>/<col2>=<val2>/.../` (checkpoint 3)

### Alternatives
1. The segment names the path as it was written: `attrs["country"]=US`,
   `user.id=7`. The name half is not encoded (T40), so the path's own
   punctuation survives into the directory name.
2. Use the last component of the path (`country=US`), which reads like a Hive
   column but collides when two paths end in the same name.
3. Percent-encode the path, which hides the collision but not the awkwardness.

### Choice
Alternative 1. Checkpoint 3 puts the column "as it appears in the resolved
schema" on the left of the `=`, and the nearest thing a path has to a name is
the path itself - which is also the only choice that cannot collide.

### Risk: 40
Author's likely preference if different: the last component of the path, giving
tidier directory names.

## T63. A column whose own name contains a dot

### Spec Text
> `--key` and `--partition-by` now accept **field paths** using dot notation
> (e.g., `user.id`, `items.0.sku`)

### Alternatives
1. A `--key` value that is exactly a column name of the resolved schema is that
   column, whatever punctuation it contains; only when no column bears the whole
   name is it parsed as a path. So a JSON Lines input whose keys are literally
   `user.id` keeps working as it did in checkpoint 1.
2. Dots always mean traversal, so such a column becomes unreachable.

### Choice
Alternative 1. Nothing in the checkpoint withdraws support for the flat columns
of the earlier ones, and a schema is free to declare a name with a dot in it.

### Risk: 20
Author's likely preference if different: always parsing the path first, leaving
a dotted column name unreachable.

## T64. When the alias file is read

### Spec Text
> detect cycles proactively → error 2

### Alternatives
1. The alias table is built and checked at start-up, whether or not `--schema`
   was given and whether or not the schema names the alias in question, so a
   cycle anywhere in the file is error 2.
2. Aliases are resolved lazily, so a cycle is only found when a schema actually
   walks into it.

### Choice
Alternative 1. That is what "proactively" asks for, and it makes the error
independent of which columns a particular run happens to declare.

### Risk: 10
Author's likely preference if different: lazy resolution with cycle detection on
the chains that are actually used.

## T65. Crossing a map with a dot, or a struct with brackets

### Spec Text
> Field paths traverse structs, use numeric indices into arrays, and map lookups
> with bracketed, double-quoted string keys

### Alternatives
1. Take the sentence as the rule for maps and as a permission for structs: a map
   is only ever entered by a bracketed key (`attrs.country` does not resolve),
   while a struct answers to both `user.name` and `user["name"]`, which cannot
   be read any other way.
2. Bind each notation strictly to one kind, so `user["name"]` is error 3 too.

### Choice
Alternative 1. Requiring brackets for maps is what the "quotes are required"
rule protects; refusing them for a struct field would serve nothing.

### Risk: 20
Author's likely preference if different: a strict pairing of notation to kind.

## T66. A null struct versus a struct of nulls

### Spec Text
> If entire column value is null → emit CSV null literal

> All struct fields included (even when null) with explicit `null` values

### Alternatives
1. Only a value that is itself null - absent from the record, JSON `null`, an
   empty cell, or coerced away by `coerce-null` - gives the null literal. A
   struct that exists but whose every field is null is still a value, and is
   written `{"a":null}`.
2. A structure that holds nothing but nulls is null as well.

### Choice
Alternative 1. The two bullets sit next to each other: the second says a null
field is written as `null` inside the JSON, which presumes the JSON is written.

### Risk: 15
Author's likely preference if different: collapsing an all-null structure to the
null literal.

## T67. Temporal text inside a `json` column

### Spec Text
> For `json` type: accept any JSON value without casting; normalize only

> Timestamps inside nested values normalized to UTC `Z`

### Alternatives
1. Normalisation of temporal values follows from the declared type, so a string
   inside a `json` value stays the string it was: nothing declares it a
   timestamp.
2. Sniff strings inside `json` values for ISO-8601 shapes and normalise them.

### Choice
Alternative 1. "Without casting" rules out recognising types by their text, and
sniffing would rewrite data the column exists to carry verbatim.

### Risk: 15
Author's likely preference if different: normalising anything that parses as a
timestamp, wherever it sits.

## T68. The integral-float rule inside nested values

### Spec Text
> Primitive casting rules, temporal normalization, null handling apply
> recursively inside nested values

### Alternatives
1. The JSON Lines number rule of checkpoint 1 (T31) - a JSON number with a
   fractional part that holds a whole number within int64 range reads as that
   integer - is one of the primitive casting rules, so `[2.0, 3.0]` casts to
   `[2,3]` for an `array<int>`.
2. The rule was stated for top-level JSON Lines values only, so `2.0` fails to
   cast to `int` inside a nested value.

### Choice
Alternative 1. The sentence says the primitive rules apply recursively, and it
would be odd for `{"n": 2.0}` to cast where `{"u": {"n": 2.0}}` does not.

### Risk: 25
Author's likely preference if different: a strict int check inside nested
values, with the number rule applying only where checkpoint 1 stated it.

## T69. The `ERR 3` wording for a `--partition-by` path

### Spec Text
> Each path must resolve to primitive value after casting
>   - Otherwise: `ERR 3 key column "<path>" does not resolve to a primitive` (exit 3)

### Alternatives
1. The template names the flag the path came from, so a partition path reports
   `ERR 3 partition column "..." does not resolve to a primitive` - the same
   wording with the role substituted, as T43 already chose for a partition
   column missing from the schema.
2. Both flags print the literal words "key column", since that is the only
   wording the checkpoint spells out.

### Choice
Alternative 1. The sentence introducing the rule covers "keys/partitions"
together and the message is the one this tool has been giving since checkpoint
3, where the flag's own name was what made the error actionable.

### Risk: 30
Author's likely preference if different: one literal message for both flags,
with "key column" in it whatever the path came from.
