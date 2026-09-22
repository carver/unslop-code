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
