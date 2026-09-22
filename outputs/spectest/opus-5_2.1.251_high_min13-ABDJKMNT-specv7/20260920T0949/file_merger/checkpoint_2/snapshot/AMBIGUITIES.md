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
