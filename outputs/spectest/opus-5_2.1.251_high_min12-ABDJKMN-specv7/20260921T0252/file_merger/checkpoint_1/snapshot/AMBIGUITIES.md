# Ambiguities

Numbered record of under-specified points in the CSV Merger and Sorter spec,
the interpretation chosen for this implementation, and the residual risk that
the spec author's own implementation reads them differently.

---

## T1 — Do `--csv-quotechar` / `--csv-escapechar` also change the *output* dialect?

### Spec Text
> `[--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>]`

> **Deterministic Dialect Details**
> - Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first

### Alternatives
1. The flags describe the *input* dialect only; the output dialect is fixed by
   "Deterministic Dialect Details" (`,` / `"` / doubling).
2. The flags describe the dialect for both reading and writing, so
   `--csv-quotechar "'"` would emit `'a,b'` instead of `"a,b"`.

### Choice
Interpretation 1. The "Deterministic Dialect Details" section states the output
quote character and escaping unconditionally and is titled *deterministic*,
which only makes sense if it is not steerable by flags. It also keeps the output
readable by any RFC-4180 parser regardless of how odd the inputs were.

### Risk: 30
Most likely alternative preference: the author threads one dialect object
through both reader and writer, so a non-default `--csv-quotechar` shows up in
the output too.

---

## T2 — Meaning of "accepts backslash-escapes" when the default escape applies

### Spec Text
> Quote character defaults to `"`; escape character defaults to doubling the
> quote (`""`) and accepts backslash-escapes (`\"`), overrideable via flags

### Alternatives
1. By default, *both* `""` and `\"` are decoded inside a quoted field, and a
   backslash that is not followed by the quote (or by another backslash) is a
   literal backslash — so `C:\path` survives.
2. The default is strict doubling; backslash escapes only become active when
   `--csv-escapechar \` is passed explicitly.
3. Default escapechar is backslash in the `csv`-module sense, which silently
   drops *every* backslash, including in `C:\path` → `C:path`.

### Choice
Interpretation 1, implemented with a hand-written line splitter. The sentence
says the default "accepts backslash-escapes", so `\"` must work with no flags;
but consuming unrelated backslashes would corrupt ordinary data, which the spec
never asks for. Doubling and backslash escaping therefore coexist, and a
backslash before any other character is kept verbatim.

### Risk: 25
Most likely alternative preference: interpretation 3 — the author passes
`escapechar='\\'` to Python's `csv` module and inherits its
drop-every-backslash behaviour.

---

## T3 — What actually distinguishes `strict` from `loose` inference

### Spec Text
> - `strict` (default): infer types based on observed values; columns with
>   conflicting types across files fall back to `string`
> - `loose`: prefer numeric/temporal types if all non-null observed values
>   parse; otherwise fall back to `string`; empty strings are treated as nulls
>   and don't affect inference

### Alternatives
1. `strict` considers **all** observed values, empty cells included, so an
   empty cell (which only parses as `string`) forces the column to `string`;
   the type is computed per file and disagreeing files fall back to `string`.
   `loose` skips nulls and computes one type over all files together.
2. Both modes skip empty cells; the modes differ only in the per-file vs.
   global conflict rule.
3. Both modes are global; `strict` requires unanimity of a single type per
   value while `loose` allows type widening (e.g. `int` + `float` → `float`).

### Choice
Interpretation 1. The clause "empty strings are treated as nulls and don't
affect inference" is attached only to `loose`; read as a contrast, it implies
that under `strict` they do affect inference. And "conflicting types **across
files**" only has meaning if a type is computed per file first. This is also
the only reading under which the two modes differ on a single-file input, which
a mode flag ought to.

### Risk: 45
Most likely alternative preference: interpretation 2 — the author skips empty
cells in both modes and treats the empty-string sentence as a clarification
rather than a distinction.

---

## T4 — How "type priority" selects a column type, and `1`/`0` → `bool`

### Spec Text
> - Type priority: `timestamp` > `date` > `bool` > `int` > `float` > `string`
> - Inference recognises values by the casting rules below

and

> - `bool` includes `1`/`0` along with standard values

### Alternatives
1. For each cell compute the set of types it can be cast to; a column's type is
   the highest-priority type that *every* cell admits. A column holding only
   `1` and `0` therefore infers as `bool` and prints `true` / `false`.
2. `bool` recognition during *inference* is restricted to `true`/`false`, and
   `1`/`0` are only accepted when a schema explicitly declares the column
   `bool` — so numeric-looking columns stay `int`.
3. The priority list is only a tie-breaker for schema merging and plays no role
   in inference, which would fall back to something like `int` before `bool`.

### Choice
Interpretation 1. "Inference recognises values by the casting rules below"
explicitly binds inference to the casting rules, and the casting rules put
`1`/`0` in `bool`; the priority list then puts `bool` ahead of `int`. The
priority list is otherwise inert, and an `is_active` column of `1`/`0` becoming
`bool` is exactly the case it appears designed for.

### Risk: 55
Most likely alternative preference: interpretation 2 — the author's fixtures
probably contain an `id` column whose first values are `1` and `0`, and the
expected output keeps them as `1`/`0` rather than `true`/`false`.

---

## T5 — Does a bare date satisfy `timestamp`?

### Spec Text
> - `date`: ISO-8601 `YYYY-MM-DD`
> - `timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix in output

> - `date` stays `YYYY-MM-DD`

### Alternatives
1. `YYYY-MM-DD` is a valid ISO-8601 timestamp, so a date-only column would
   infer as `timestamp` (priority `timestamp` > `date`) and print
   `2024-07-01T00:00:00Z`.
2. Inference requires a time component before calling something a
   `timestamp`, so date-only columns infer as `date`; but an explicit
   `timestamp` schema entry still *casts* a bare date to midnight UTC.
3. Both inference and casting require a time component; casting `2024-07-01`
   into a `timestamp` column is a cast error.

### Choice
Interpretation 2. Under interpretation 1 the rule "`date` stays `YYYY-MM-DD`"
could never fire for an inferred schema, and the `date` type would be
unreachable — so inference must require a time part. Casting stays lenient
because the schema is an explicit instruction from the user and losing the data
to a null would be the harsher reading.

### Risk: 30
Most likely alternative preference: interpretation 3 — a single strict
`parse_timestamp` shared by inference and casting, which makes a bare date in a
`timestamp` column a cast failure.

---

## T6 — Output text for `bool` values

### Spec Text
> - `bool` includes `1`/`0` along with standard values

(The spec fixes the output text for `date` and `timestamp` but never for
`bool`.)

### Alternatives
1. Canonical lowercase `true` / `false`.
2. Python's `str(bool)`: `True` / `False`.
3. `1` / `0`.
4. Echo the original source text unchanged.

### Choice
Lowercase `true` / `false`. The tool's stated job is to normalise (it does so
explicitly for timestamps), so a single canonical spelling is required, and
lowercase is the CSV/JSON-idiomatic one. It is also the spelling the spec itself
uses when listing "standard values".

### Risk: 40
Most likely alternative preference: `True` / `False`, if the author stores
parsed Python `bool`s and hands them straight to `csv.writer`.

---

## T7 — Output text for successfully cast `int` and `float` values

### Spec Text
> - Cast every input cell into target type (rules below)
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. Cast values are re-rendered canonically: `007` → `7`, `+5` → `5`, and a
   `float` column renders `3` as `3.0` (Python `repr` shortest round trip).
2. The original source text is echoed whenever the cast succeeds, so `007`
   stays `007` and a `float` column prints `3`.

### Choice
Interpretation 1. "Cast every input cell into target type" describes a value
conversion, not a validation pass, and the output section says output columns
follow the *resolved schema* — a column declared `float` should read as floats.
The spec's own normalisation of timestamps shows the intent that the output is
canonical rather than pass-through.

### Risk: 35
Most likely alternative preference: `float` rendering — the author may use
`str(value)` with trailing-zero trimming or keep the source text, so a `float`
column containing `3` prints `3` rather than `3.0`.

---

## T8 — Is an empty cell a null, and is `--csv-null-literal` recognised on input?

### Spec Text
> - Missing values emitted as the null literal (default empty string; override
>   with `--csv-null-literal`)

> empty strings are treated as nulls

> - Nulls always compare less than non-null values

### Alternatives
1. An empty cell is a null for **every** type (`string` included), so with
   `--csv-null-literal NULL` an empty `note` cell prints `NULL`; in addition a
   cell whose text equals the null literal is read back as a null.
2. Empty cells are nulls only for non-`string` types; an empty `string` cell is
   the empty string and prints as `""` even under a custom null literal.
3. The null literal is output-only and is never recognised when reading.

### Choice
Interpretation 1. The spec's only statement about empty strings ("treated as
nulls") is unqualified by type, and treating the null literal symmetrically
means the tool's own output can be fed back in without changing meaning — a
property a merge tool plainly wants.

### Risk: 40
Most likely alternative preference: interpretation 2 combined with 3 — an
empty `string` cell stays empty and the null literal is written but never read.

---

## T9 — Rendering of fractional seconds in normalised timestamps

### Spec Text
> - `timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`),
>   keeping fractional seconds

### Alternatives
1. Microsecond precision: no fractional part when it is zero, otherwise exactly
   six digits (`.500000`), matching the spec's zero-fraction example.
2. The source's own digit count is preserved (`.5` stays `.5`, `.123` stays
   `.123`).
3. Always six digits, even when zero (`2024-07-01T12:00:00.000000Z`) — ruled
   out by the spec's example.

### Choice
Interpretation 1, i.e. Python's `datetime.isoformat()`. The worked example
`2024-07-01T12:00:00Z` shows a zero fraction must be omitted, and once the
value has been parsed into a `datetime` the source's digit count is gone, so
six digits is the natural canonical width.

### Risk: 30
Most likely alternative preference: interpretation 2, if the author normalises
the zone by string surgery instead of parsing to a `datetime`.

---

## T10 — Default value of `--memory-limit-mb`

### Spec Text
> `[--memory-limit-mb <INT>]`

> - Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily
>   large inputs

### Alternatives
1. Default 64 MB, the figure the spec itself calls out.
2. No default: unlimited, purely in-memory unless the flag is given.
3. Some other round number (128, 256, 512).

### Choice
64 MB. It is the only number the spec names in this context, and defaulting to
unbounded would contradict "arbitrarily large inputs" for the documented
example invocation, which omits the flag.

### Risk: 20
Most likely alternative preference: unlimited by default — but since the
default only changes *when* spilling starts and never the emitted bytes, it is
very unlikely to be observable in a test.

---

## T11 — Where `keep-string` survivors sort relative to properly typed values

### Spec Text
> - `keep-string`: emit original text as string

> - Nulls always compare less than non-null values

### Alternatives
1. Kept strings form their own class that sorts after all successfully typed
   (non-null) values of the same column, preserving a total order.
2. Kept strings are compared as strings against the string rendering of the
   typed values.
3. Kept strings are treated as nulls for ordering purposes and sort first.

### Choice
Interpretation 1. The spec gives no rule, and mixing a raw string with parsed
numbers or datetimes has no meaningful order; segregating them keeps the sort
total, deterministic and stable, and keeps the typed values in correct relative
order among themselves — which is the part the spec does constrain.

### Risk: 45
Most likely alternative preference: interpretation 2, if the author's sort key
falls back to comparing rendered text once a cell failed to cast.

---

## T12 — Exit status and message format for errors

### Spec Text
> - `fail`: write error to stderr and exit non-zero

> - If a key column is not present in resolved schema, that is an error

### Alternatives
1. All user-facing errors (cast failure under `fail`, unknown key column,
   unreadable input, bad schema JSON, unknown schema type) behave the same way:
   a message on stderr and exit status 1; argparse usage errors keep
   argparse's status 2.
2. Only cast failures under `fail` are specified to print to stderr; other
   errors might raise a traceback or use distinct exit codes.

### Choice
Interpretation 1. The spec only ever distinguishes "non-zero" from zero, so a
single non-zero status with a one-line stderr message satisfies every stated
requirement, and applying it uniformly to the other error conditions is the
least surprising extension.

### Risk: 10
Most likely alternative preference: a specific exit code such as 2 for all
errors — unlikely to be asserted beyond "non-zero".

---

## T13 — Ragged rows: fewer or more fields than the header

### Spec Text
> - All inputs are UTF-8, RFC-4180 compliant, with a **header row**

> - Missing values emitted as the null literal

### Alternatives
1. A short row leaves the absent trailing columns null; a long row's surplus
   fields are ignored (they correspond to no header name).
2. Any row whose field count differs from the header is an error.
3. Surplus fields are appended under synthesised column names.

### Choice
Interpretation 1. The spec already prescribes nulls for values a row does not
supply and ignoring columns that the resolved schema does not name, so applying
both rules positionally is consistent. Erroring out is not mentioned anywhere
in the error list.

### Risk: 20
Most likely alternative preference: the same, since the inputs are promised to
be RFC-4180 compliant and ragged rows may simply never be tested.

---

## T14 — A blank line in the body of a CSV

### Spec Text
> - Delimiter is comma (`,`); line ending `\n`
> - No multiline fields will be present in tests

### Alternatives
1. A blank line is a one-field row whose single value is null — which matters
   for a single-column CSV where a null row *is* an empty line. Blank lines
   trailing at end of file are dropped.
2. Every blank line is skipped, so a single-column file cannot express a null
   row.
3. Every blank line, including a trailing one, produces a row.

### Choice
Interpretation 1. RFC-4180 has no blank-line construct, so the only coherent
reading of an interior blank line in a one-column file is a row holding the
empty (null) value; dropping trailing blanks avoids inventing a row from a
file that merely ends with a newline or two.

### Risk: 15
Most likely alternative preference: interpretation 2 — the author skips blank
lines unconditionally, which is only observable on a single-column input with a
null row.

---

## T15 — Accepted spellings for `bool`, and whether surrounding spaces parse

### Spec Text
> - `bool` includes `1`/`0` along with standard values
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. `bool` accepts `true`/`false` in any letter case plus `1`/`0`, and nothing
   else; numeric and temporal parsers ignore surrounding whitespace.
2. `bool` additionally accepts `yes`/`no`, `t`/`f`, `y`/`n`.
3. Parsing is byte-exact: `TRUE` and ` 5` are cast failures.

### Choice
Interpretation 1. "standard values" for a boolean means `true`/`false`, and
widening to `yes`/`no` would silently change *inference* results for ordinary
text columns, which is the more damaging error. Case-insensitivity and
whitespace tolerance are the conventional meaning of "standard parsing".

### Risk: 25
Most likely alternative preference: case-sensitive `true`/`false` only, if the
author compares against a literal set without lowering the input.

---

## T16 — Duplicate and repeated key specifications

### Spec Text
> `--key <col>[,<col>...]`

### Alternatives
1. The flag may be repeated and each occurrence may carry a comma list; all
   parts concatenate in order, and a column named twice is only used once.
2. Only a single `--key` occurrence is legal; a repeat replaces the earlier one.
3. A repeated column is an error.

### Choice
Interpretation 1. The documented form is a single comma list, which this
supports exactly; accepting repeats as well is a superset that cannot break a
conforming invocation, and de-duplicating a repeated column is harmless because
a second comparison on the same column can never change the order.

### Risk: 5
Most likely alternative preference: identical behaviour on every documented
invocation; the difference is only visible on inputs the usage line does not
describe.

---

## T17 — Non-finite floats

### Spec Text
> - `int`, `float`, `string`: standard parsing

### Alternatives
1. `nan`, `inf`, `infinity` are cast failures, so a column containing them
   falls back to `string` on inference and follows `--on-type-error` under an
   explicit `float` schema.
2. They parse as floats, following Python's `float()`.

### Choice
Interpretation 1. A `NaN` in a sort key destroys the total order the spec
demands ("sorted globally by the key(s)", stable), so admitting it would make
the output non-deterministic. Rejecting these three spellings keeps every
`float` column totally ordered.

### Risk: 10
Most likely alternative preference: interpretation 2 by accident (a bare
`float()` call), but a fixture containing `nan` is unlikely.
