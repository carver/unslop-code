# AMBIGUITIES

Interpretation decisions taken while implementing the `datagate` spec.

---

## T1. How the dataset id is derived from the source URL

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. Hash the exact `source` query-parameter string (byte-for-byte), so
   `http://h/a.csv` and `http://h/a.csv?` are different datasets.
2. Normalise the URL first (lower-case host, drop default port, strip trailing
   `/`, sort query parameters) and hash the normalised form.
3. Use a monotonically increasing counter plus a URL → id side table.

### Choice
Alternative 1: `sha256(source_string)` truncated to 16 hex characters. The spec
says "the same `source` URL **string**", which points at the literal parameter
value rather than a canonicalised URL. A counter would still satisfy the
"same URL, same id" rule but makes ids depend on server history, which the
Determinism section argues against.

### Risk: 10
Most likely author preference if different: the same string-keyed hash with a
different digest/length (invisible to any test that does not hard-code an id).

---

## T2. How encoding is "detected" when `charset` is omitted

### Spec Text
> `charset` ... If omitted, detect unambiguous encoding from content, else latin-1.

### Alternatives
1. BOM sniffing, then a strict UTF-8 decode attempt; fall back to latin-1.
2. A statistical detector (`chardet` / `charset_normalizer`), which may return
   `windows-1252`, `MacRoman`, `Shift_JIS`, ... for non-UTF-8 bytes.
3. Always latin-1 unless a BOM is present.

### Choice
Alternative 1. "Unambiguous" fits self-validating encodings: a BOM is explicit,
and a successful strict UTF-8 decode is statistically conclusive, while every
byte string is valid latin-1 so it can only ever be the fallback. Statistical
guesses are the opposite of unambiguous and are not deterministic across
library versions, which the Determinism section forbids.

### Risk: 20
Most likely author preference if different: `charset_normalizer` best-guess,
which would decode windows-1252 fixtures with smart quotes differently.

---

## T3. Which cell values become JSON numbers

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Strict regex: optional sign, digits, optional fractional part, optional
   exponent. `007` → `7`, `nan`/`inf`/`1_0`/`0x10` → text, `1,234` → text.
2. Naive `int()` then `float()` in a try/except, which additionally accepts
   `nan`, `inf`, `1_0`, and surrounding underscores.
3. Locale/currency aware parsing (`$1,234.50` → `1234.5`).

### Choice
Alternative 1. It covers exactly the "integers/decimals" wording, keeps
identifiers such as `08:30` and `12:00` as text, and never produces `NaN` or
`Infinity`, which are not valid JSON. Leading zeros are still converted
(`007` → `7`) because that is what any int/float based implementation does.

### Risk: 25
Most likely author preference if different: plain `int()`/`float()`
try/except, which would turn a literal `nan` or `inf` cell into a number.

---

## T4. What counts as "non-tabular content"

### Spec Text
> | Non-tabular content | 400 |
> Delimiter must be inferred from input, if present ...
> A valid file requires at least one header row and one data row.

### Alternatives
1. Reject only when the structural rules fail: empty body, binary (NUL bytes),
   an obvious markup/JSON payload, or fewer than two non-empty rows. A
   single-column file with a header and a data row is accepted.
2. Additionally require that one of the supported delimiters actually occurs,
   so any single-column file is rejected as non-tabular.
3. Trust the remote `Content-Type` only.

### Choice
Alternative 1, with the remote `Content-Type` used as an extra signal (an
`text/html` or `application/json` response is rejected without parsing).
"Delimiter must be inferred from input, **if present**" implies a delimiter may
legitimately be absent, so a one-column CSV is still a table.

### Risk: 35
Most likely author preference if different: requiring a delimiter to be
present, so a one-column CSV would return 400 instead of 200.

---

## T5. Rows whose field count differs from the header

### Spec Text
> `columns` and each row follow source column order.

### Alternatives
1. Pad short rows with empty strings and truncate long rows to the header width.
2. Keep ragged rows exactly as parsed, so row lengths vary.
3. Treat any ragged row as non-tabular and return 400.

### Choice
Alternative 1. It keeps every row aligned with `columns`, which is what a
consumer indexing `rows[i][j]` by column position needs, and it is the
behaviour of the common CSV → records conversions. Rejecting the whole file for
one short line is harsher than anything the spec asks for.

### Risk: 30
Most likely author preference if different: emitting the ragged rows verbatim.

---

## T6. Units and precision of `query_ms`

### Spec Text
> `"query_ms": 3.2` ... `query_ms` is present and non-negative.

### Alternatives
1. Milliseconds as a float measuring the time spent serving the query, rounded
   to 3 decimals.
2. Milliseconds as an integer.
3. Time spent on the original ingestion, stored with the dataset.

### Choice
Alternative 1. The sample value `3.2` is fractional, and "query_ms" names the
query request, not ingestion.

### Risk: 5
Most likely author preference if different: a different rounding precision,
which only matters to a test asserting an exact value (impossible for a timer).

---

## T7. `charset` is a real encoding but the bytes do not decode with it

### Spec Text
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. 400 — an encoding that cannot decode the payload is unusable.
2. 200 with `errors="replace"` (or `errors="ignore"`), treating the table as
   successfully ingested with replacement characters.
3. 404, folding it into "source unreachable".

### Choice
Alternative 1. "Malformed" most naturally covers the whole
charset-plus-payload combination failing, and a table full of U+FFFD is a
silent data corruption the caller asked to be told about.

### Risk: 25
Most likely author preference if different: decoding with `errors="replace"`
and returning 200.

---

## T8. What makes a URL "invalid"

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Require an `http`/`https` scheme and a non-empty host; everything else
   (`not-a-url`, `htp:/x`, `file:///etc/passwd`, `ftp://h/a.csv`) is 400.
2. Only reject strings that have no scheme or no host, and let `requests` fail
   on exotic schemes, which would report them as 404.
3. Accept anything and map every failure to 404.

### Choice
Alternative 1. Alternative 3 contradicts the table (400 would be unreachable),
and restricting to http/https also keeps the fetcher from reading local files
through `file://`.

### Risk: 25
Most likely author preference if different: `ftp://`/`file://` sources
surfacing as 404 rather than 400.

---

## T9. Which remote responses count as a "remote HTTP error"

### Spec Text
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Any status `>= 400` (404, 403, 500, ...), plus connection/timeout/DNS
   failures. Redirects are followed first.
2. Only 4xx, with 5xx surfacing as 502/500.
3. Anything other than exactly 200.

### Choice
Alternative 1. The spec collapses every remote failure into one row, and
following redirects is the default behaviour of any HTTP client the author
would have used.

### Risk: 15
Most likely author preference if different: treating a 3xx that is not followed
as an error too.

---

## T10. Converting the same source twice

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Re-fetch the source every time and overwrite the stored dataset, always
   returning the same endpoint.
2. Serve the cached dataset without a second network request.
3. Return an error/conflict on the second conversion.

### Choice
Alternative 1. The spec pins the *endpoint* to the URL, not the payload, and a
second call with a different `charset` clearly has to change what is stored.
Re-fetching keeps the dataset current and keeps the two parameters meaningful.

### Risk: 20
Most likely author preference if different: caching, so the source is fetched
only once per URL.

---

## T11. Whether the row limit is adjustable

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. A fixed limit of 100 with no override.
2. "Default" implies an override: accept an optional `limit` query parameter,
   defaulting to 100.
3. An override plus `offset` paging.

### Choice
Alternative 2, with unusable values (non-numeric, zero, negative) falling back
to 100 rather than erroring. Calling 100 a *default* only makes sense if it can
be overridden, and a caller who never sends `limit` sees exactly the fixed
behaviour of alternative 1.

### Risk: 20
Most likely author preference if different: a hard-coded 100 that ignores
`limit` entirely.

> **Annotation (pagination spec):** resolved. The page size is now the
> documented `_size` control (positive integer, default `100`), and an unusable
> value is a `400` rather than a fallback. The undocumented `limit` parameter
> this entry invented is gone; it is now ignored like any other unknown
> parameter (see T24).

---

## T12. Surrounding whitespace in cells

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.

### Alternatives
1. Trim whitespace only to decide the type; emit text cells exactly as they
   appear in the source (` 42 ` → `42`, ` x ` → `" x "`).
2. Strip every cell, so text values lose their padding too.
3. Strip nothing, so ` 42 ` stays text.

### Choice
Alternative 1. It matches an `int()`/`float()` based implementation (both of
which ignore surrounding whitespace) while leaving text content untouched, as
"strings remain text" asks.

### Risk: 20
Most likely author preference if different: stripping text cells as well.

---

## T13. Header cell handling

### Spec Text
> ```json
> "columns": ["<col1>", "<col2>", "..."]
> ```

### Alternatives
1. Header cells are always strings, trimmed, with a leading BOM removed;
   duplicate and empty names are preserved as they appear.
2. Apply type inference to the header too, so a numeric header becomes a number.
3. De-duplicate or auto-name empty headers (`col_2`, `Unnamed: 2`).

### Choice
Alternative 1. The response schema types `columns` as strings, and renaming
columns would break "columns ... follow source column order" as a faithful echo
of the header row.

### Risk: 15
Most likely author preference if different: leaving the BOM or the surrounding
whitespace on the first column name.

---

## T14. Empty cells

### Spec Text
> - Strings remain text.

### Alternatives
1. An empty cell is the empty string `""`.
2. An empty cell is JSON `null`.

### Choice
Alternative 1. `null` is not one of the three documented value kinds, and an
empty CSV field is textually empty rather than absent.

### Risk: 15
Most likely author preference if different: `null` for empty cells.

---

## T15. Wrong HTTP method on a known route

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` → 405 (JSON envelope), since the route exists.
2. `POST /convert` → 404, treating "route" as method + path.

### Choice
Alternative 1. The spec constrains *unknown* routes; `/convert` is known, and
405 is the standard (and framework-default) answer for a method mismatch. The
error body still uses the `{"ok": false, "error": ...}` envelope.

### Risk: 15
Most likely author preference if different: 404 for any request that does not
match a documented method + path pair.

---

## T16. The delimiter candidate set

### Spec Text
> minimum supported delimiters are `,`, `;`, and `\t`.

### Alternatives
1. Exactly `,`, `;`, `\t`.
2. Those three plus `|` (explicitly allowed by "minimum supported").
3. Full `csv.Sniffer` auto-detection over any punctuation, which can pick `:`
   or `.` for files of times or decimals.

### Choice
Alternative 2. "Minimum" invites a superset, `|` is a conventional CSV
delimiter, and a closed candidate list avoids `csv.Sniffer` choosing `:` for a
column of `08:30` style values — which would contradict the type-handling rule.

### Risk: 10
Most likely author preference if different: only the three listed delimiters,
so a pipe-separated file would be read as a single column.

---

## T17. Which CORS headers to send

### Spec Text
> Include CORS headers for browser access.

### Alternatives
1. `Access-Control-Allow-Origin: *` plus allowed methods/headers on every
   response, including errors.
2. Only echo the request `Origin`, with credentials support.
3. Only on successful responses.

### Choice
Alternative 1. The API is read-only and unauthenticated, so a wildcard origin
is the useful reading of "browser access"; a browser also needs the headers on
error responses to read the status.

### Risk: 8
Most likely author preference if different: origin echoing instead of `*`.


---

## T18. Where `rowid` numbering starts

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number, starting at the header).

### Alternatives
1. The header is row 1, so the first data row is `rowid` 2.
2. Counting starts at the first data row, so the first data row is `rowid` 1.
3. 0-based data-row index.

### Choice
Alternative 1. "1-based source-file row number" points at a position in the
file rather than in `rows`, and "starting at the header" only adds information
if the header is what consumes number 1. Alternative 3 contradicts "1-based".

### Risk: 25
Most likely author preference if different: the first data row numbered 1,
shifting every `rowid` down by one.

---

## T19. Whether `rowid` appears outside `_shape=objects`

### Spec Text
> `_shape=lists` (default): `rows` is arrays.
> `_shape=objects`: `rows` is objects and includes `rowid` ...
> `_rowid=hide` removes `rowid`.

### Alternatives
1. `rowid` exists only in `objects` rows; `_rowid=hide` is accepted but has
   nothing to remove from `lists` rows.
2. `lists` rows are prefixed with the rowid as an extra leading array element,
   which `_rowid=hide` strips.
3. `rowid` is reported per row in a parallel top-level array.

### Choice
Alternative 1. The spec attaches `rowid` to the `objects` shape only, and says
`rowid` is not in `columns` — a leading array element with no matching column
name would make `rows[i][j]` no longer line up with `columns[j]`, which the
dataset section requires.

### Risk: 20
Most likely author preference if different: `lists` rows carrying the rowid as
their first element.

---

## T20. Comparing values while sorting

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.
> Sorting is stable and applied before pagination.

### Alternatives
1. Numbers compare numerically among themselves, text compares
   lexicographically, and in a mixed column every number sorts before every
   string (the SQLite/SQL ordering); descending is the stable reverse, so tied
   rows keep source order in both directions.
2. Compare the string form of every cell, so `10` sorts before `9`.
3. Compare values directly and let a mixed column raise (HTTP 500).

### Choice
Alternative 1. A column of typed numbers has to sort numerically to be useful,
so alternative 2 is out; alternative 3 turns ordinary data into a server error.
Ranking numbers before text is the behaviour of the database engines this API
mimics, and a stable reverse honours the "sorting is stable" rule for
`_sort_desc` as well as `_sort`.

### Risk: 30
Most likely author preference if different: text-before-numbers in mixed
columns, or a descending sort implemented as `reversed(ascending)`, which flips
the order of tied rows.

---

## T21. Validating `_sort` when `_sort_desc` wins

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. Both parameters are validated whenever they are supplied; `_sort_desc` only
   decides the direction, so `?_sort=nope&_sort_desc=name` is a 400.
2. `_sort_desc` shadows `_sort` completely, so a losing `_sort` is never
   checked and `?_sort=nope&_sort_desc=name` sorts descending by `name`.

### Choice
Alternative 1. The validation sentence is stated over the sort parameters
without an exception for the losing one, and reporting a typo the caller
plainly meant as a sort key is more useful than silently discarding it.
"Wins" reads as a rule about precedence of the ordering, not about validation.

### Risk: 35
Most likely author preference if different: resolving `_sort_desc or _sort`
first and validating only the winner.

---

## T22. Accepted syntax for `_size` and `_offset`

### Spec Text
> `_size` (positive integer, default `100`) ... `_offset` (non-negative
> integer, default `0`) ... Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Parse with `int()`: `5`, `+5` and surrounding whitespace are accepted,
   `1.5`, `1e3`, `abc` and an empty value are 400, and `_size` has no upper
   cap.
2. Digits only (`[0-9]+`), so `+5` is a 400 as well.
3. Truncate floats (`_size=1.9` → 1) and clamp out-of-range values instead of
   failing.

### Choice
Alternative 1. It is what an `int()`-based reading of "integer" accepts, and
the spec asks for a 400 rather than the clamping of alternative 3. No cap is
imposed because "If it exceeds available rows, return all" is the only stated
behaviour for a large `_size`.

### Risk: 15
Most likely author preference if different: a strict digit test that rejects
`_size=+5`, or a cap on `_size` borrowed from a Datasette-style maximum.

---

## T23. Repeated control parameters that agree

### Spec Text
> Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
> `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`.

### Alternatives
1. Any second occurrence is a 400, even `?_size=5&_size=5`.
2. Only conflicting repeats are a 400; identical values collapse.

### Choice
Alternative 1. "Any repeated control parameter" is unconditional, and
duplicate-key detection that also compares values is extra machinery the spec
does not ask for. Non-control parameters are unaffected (see T24).

### Risk: 12
Most likely author preference if different: tolerating exact duplicates.

---

## T24. Query parameters the spec does not define

### Spec Text
> `GET /datasets/<id>` accepts control parameters for pagination, sorting, and
> shape.

### Alternatives
1. Ignore any parameter that is not a documented control, repeats included.
2. Reject unknown parameters with a 400.
3. Treat unknown parameters as column filters, the way Datasette does.

### Choice
Alternative 1. The error table enumerates exactly which conditions are 400 and
an unknown parameter is not among them; filtering (alternative 3) is a whole
feature the spec never describes. The leading underscore on every control is
itself the convention that keeps controls and future non-control parameters
apart.

### Risk: 20
Most likely author preference if different: 400 on any unrecognised parameter.

### Resolved
The filtering spec supersedes alternative 3 for parameters containing `__`:
those are now filters, and an unknown column among them is a 400. Parameters
with neither a leading `_` nor a `__` are still ignored, as chosen here.

---

## T25. An unknown dataset id combined with invalid controls

### Spec Text
> If `<id>` is unknown, return `HTTP 404`.
> | control parameter repeated | 400 |

### Alternatives
1. Resolve the dataset first: `/datasets/missing?_size=0` is a 404.
2. Validate controls first, so the same request is a 400.

### Choice
Alternative 1. Sort columns can only be validated against a dataset that
exists, so the lookup has to come first anyway, and a 404 tells the caller
about the more fundamental problem.

### Risk: 20
Most likely author preference if different: parameter validation running
before the store lookup, yielding a 400.

---

## T26. `rowid` and source lines that are not returned

### Spec Text
> `rowid` (1-based source-file row number, starting at the header)

### Alternatives
1. Number every record the CSV reader produces, so blank lines dropped during
   parsing still consume their number and the returned `rowid`s may have gaps.
2. Number only the rows that survive parsing, so `rowid`s are always
   contiguous.

### Choice
Alternative 1. "Source-file row number" describes a position in the file, and
the number stays a faithful pointer back into the source, which is the only
reason to expose it. A file without blank lines behaves identically under both
readings.

### Risk: 30
Most likely author preference if different: contiguous numbering over the rows
that were kept.

---

## T27. Splitting `<column>__<comparator>` when the column name contains `__`

### Spec Text
> `<column>__<comparator>=<value>`
> Column matching is exact and case-sensitive.

### Alternatives
1. Split on the *last* `__`, so `first__name__exact` filters the column
   `first__name` with `exact`.
2. Split on the *first* `__`, so the same key asks for column `first` with the
   comparator `name__exact`, which is invalid and therefore `HTTP 400`.

### Choice
Alternative 1. The comparator is the suffix of the key and belongs to a closed
four-word set, while the column name is arbitrary text taken from a CSV header,
so the only split that can ever address a header containing `__` is the last
one. Keys without `__` inside the column name behave identically either way.

### Risk: 20
Most likely author preference if different: `key.split("__", 1)`, which rejects
such columns with an invalid-comparator 400.

---

## T28. What `exact` and `contains` compare against

### Spec Text
> `exact`: case-sensitive string equality.
> `contains`: case-sensitive substring.

### Alternatives
1. Compare the filter value against the *stored* cell rendered as text, so a
   cell parsed as the number `36` matches `age__exact=36`, and `45` matches
   `age__contains=4`.
2. Restrict the string comparators to cells that are stored as text, so no
   numeric cell ever matches.
3. Compare against the original CSV text of the cell, preserving the source
   spelling (`36.50`, `+7`, surrounding spaces).

### Choice
Alternative 1. The spec offers no other way to filter a numeric column for
equality -- `less`/`greater` are both strict -- so alternative 2 would leave a
gap the error table never hints at. Alternative 3 needs the pre-coercion text,
which the dataset deliberately does not keep; `str(value)` on the stored cell
is the reading an implementation that stores typed rows naturally lands on.

### Risk: 30
Most likely author preference if different: the same `str()` rule, but applied
to a stored value whose source spelling differs from its repr (`36.50` becomes
`36.5`, `+7` becomes `7`), so a filter quoting the CSV text fails to match.

---

## T29. What counts as numeric for `less` and `greater`

### Spec Text
> `less`: numeric strict less (`float` parse on stored and filter values).
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.
> Rows with non-numeric stored values are not matched for numeric comparators.

### Alternatives
1. "Numeric" is exactly what `float()` accepts on both sides: a filter value
   `float()` rejects is a 400, and a stored cell it rejects is skipped. This
   admits `1e3`, ` 5 ` and also `inf`/`nan`.
2. Accept only the cells the ingester already typed as int/float, and require
   the filter value to match the same stricter numeric pattern, so `inf` and
   `nan` are rejected on both sides.

### Choice
Alternative 1. The spec names the mechanism -- "`float` parse on stored and
filter values" -- rather than a syntax, so `float()` succeeding is the test for
both sides. The two readings differ only on `inf`/`nan`-like text, and even
there a stored `nan` matches nothing, because every comparison against it is
false.

### Risk: 20
Most likely author preference if different: rejecting `inf`/`nan` filter values
with a 400 instead of accepting them as numbers that match no row.

---

## T30. The value and scope of the query timeout

### Spec Text
> Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. Give filter evaluation a fixed wall-clock budget (5 seconds), checked as the
   rows are scanned, and report exhaustion as a 400.
2. Time the whole request, sorting and shaping included.
3. Treat the row it as unreachable on in-memory data and never raise.

### Choice
Alternative 1. The spec puts the timeout in the filtering section, and scanning
every row against every filter is the part of the query whose cost grows with
both the table and the request. A budget large enough that no honest query
reaches it keeps the rule from firing on ordinary traffic; the tests drive it by
shrinking the budget rather than by building a slow dataset.

### Risk: 15
Most likely author preference if different: a deadline over the whole
`/datasets/<id>` handler, or a different budget -- either way only observable
on a dataset far larger than a fixture.

---

## T31. Names that begin with `_` and also contain `__`

### Spec Text
> Control params (names beginning with `_`) are not filters.
> | Unknown filter column | 400 |

### Alternatives
1. The leading underscore decides first: `_mystery__exact=ada` is not a filter,
   and since it is not a known control either it is ignored (T24). The same rule
   covers `__exact=ada`, whose column name would be empty.
2. Only the documented controls are exempt, so any other `_`-prefixed name
   containing `__` is a filter with the unknown column `_mystery` and a 400.

### Choice
Alternative 1. The spec defines the exemption by spelling -- "names beginning
with `_`" -- not by membership of the control list, and the underscore prefix is
the convention that reserves a namespace for controls. Rejecting a reserved
name as a bad column would make future controls breaking changes.

### Risk: 15
Most likely author preference if different: matching only the known control
names and treating the rest as filters.

---

## T32. What makes two filter keys "duplicate"

### Spec Text
> Duplicate filter keys are invalid (`HTTP 400`).
> Multiple filters are ANDed.

### Alternatives
1. A duplicate is the same full key string repeated, so `age__less=40&age__less=50`
   is a 400 while `age__greater=30&age__less=46` is two ANDed filters.
2. A duplicate is a repeated *column*, so any two filters on `age` are a 400.

### Choice
Alternative 1. The spec says "filter keys", and the key is the whole
`<column>__<comparator>` pair; reading it as the column would make ranges
(`greater` plus `less`) impossible, which is the most obvious use of having both
comparators. Repeats that agree are rejected as well, matching how repeated
control parameters already behave (T23).

### Risk: 10
Most likely author preference if different: one filter per column.

---

## T33. Whether `/export` paginates by default

### Spec Text
> The CSV uses source column order and applies the same filters, sort, and
> pagination as `/datasets/<id>`.
> export rows follow filter -> sort -> paginate.

### Alternatives
1. Identical behaviour, defaults included: with no `_size` the export carries the
   same first `100` rows the JSON endpoint would return.
2. Export means "the whole result set", so `_size`/`_offset` only page the CSV
   when they are supplied and are otherwise unbounded.

### Choice
Alternative 1. "the same ... pagination as `/datasets/<id>`" describes the
pagination behaviour as a whole, and the default page size is part of that
behaviour; reading it as "only when asked" would make the two endpoints disagree
on the same query string, which the Determinism section argues against. The
endpoint therefore shares one control parser and one filter/sort/page pipeline
with the JSON route.

### Risk: 25
Most likely author preference if different: an unbounded export unless `_size`
is given, visible only on a dataset with more than 100 rows.

---

## T34. Whether `_shape`, `_rowid` and `_total` are still validated on `/export`

### Spec Text
> `_shape`, `_rowid`, and `_total` do not affect CSV output.

### Alternatives
1. They are parsed and validated exactly as on `/datasets/<id>` -- so
   `_shape=bogus` is still `HTTP 400` -- but a valid value changes nothing about
   the bytes returned.
2. They are ignored outright on `/export`, so any value at all is accepted.

### Choice
Alternative 1. The sentence constrains the *output*, not the request validation,
and the neighbouring sentence says the endpoint applies the same controls as
`/datasets/<id>`; keeping one strict parser for both routes means a query string
cannot be silently valid on one endpoint and rejected on the other.

### Risk: 20
Most likely author preference if different: skipping shape/rowid/total
validation on `/export`, so `?_shape=objects&_shape=lists` or `?_total=yes`
would be a `200` there.

---

## T35. Whether the exported CSV carries a header row

### Spec Text
> `GET /datasets/<id>/export` returns CSV bytes
> export columns follow source column order.
> semantically-correct CSV is required

### Alternatives
1. The first line is the column names, followed by one line per exported row.
2. Data rows only, since the caller already knows the columns from
   `/datasets/<id>`.

### Choice
Alternative 1. A bare block of values would carry no column information at all,
which makes "export columns follow source column order" unobservable and the
file unusable as a CSV in its own right -- the format's header line is what
"semantically-correct CSV" means for a named-column table.

### Risk: 8
Most likely author preference if different: headerless rows.

---

## T36. How stored cells are rendered back into CSV text

### Spec Text
> semantically-correct CSV is required; exact newline/quoting is not.
> `_shape`, `_rowid`, and `_total` do not affect CSV output.

### Alternatives
1. Render the *stored* dataset: the inferred values, so the integer `36` writes
   as `36` and the decimal `2.5` as `2.5`, and text cells write verbatim.
2. Reproduce the original source text byte-for-byte, so `2.50`, `036` and
   `+7` survive a round trip.

### Choice
Alternative 1. Export is described in terms of the dataset's columns and rows
-- the same rows the JSON endpoint serves -- not in terms of the bytes that were
ingested, and a spreadsheet source has no original CSV text to reproduce at all.
Values are written by a standard CSV writer, so quoting and escaping follow
RFC 4180 and only appear where they are needed.

### Risk: 25
Most likely author preference if different: echoing the raw source text, which
differs on cells like `2.50` or `007`.

---

## T37. The exact `Content-Type` and byte encoding of the export

### Spec Text
> - `Content-Type: text/csv`

### Alternatives
1. Exactly `text/csv`, with the body encoded as UTF-8.
2. `text/csv; charset=utf-8`, the framework's default for a text mimetype.

### Choice
Alternative 1: the header is quoted in the spec without parameters, so it is set
literally. UTF-8 is the only encoding that can represent every cell the ingest
side accepts.

### Risk: 10
Most likely author preference if different: a `charset=utf-8` parameter
appended, which breaks an exact-equality assertion but not a prefix one.

---

## T38. How an upload's dataset id is derived

### Spec Text
> Re-uploading the same file bytes yields the same dataset id.

### Alternatives
1. `sha256` of the uploaded bytes, truncated the same way URL ids are; the
   filename, the form field used and `charset` play no part.
2. Hash the bytes together with the filename, so the same file under two names
   is two datasets.
3. Hash the parsed dataset, so two encodings of the same table share an id.

### Choice
Alternative 1. The spec keys identity on "the same file bytes" and mentions
nothing else, so every other part of the request is excluded; re-uploading known
bytes therefore replaces the stored dataset in place, exactly as re-converting a
known URL does (T10). Upload ids are the same shape as URL ids so a caller
cannot tell the two routes apart from the endpoint alone.

### Risk: 12
Most likely author preference if different: the same byte-keyed hash with a
different digest or length, invisible unless a test hard-codes an id.

---

## T39. Both `file` and `attachment` present

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`

### Alternatives
1. `file` wins; `attachment` is the fallback name.
2. `attachment` wins.
3. Supplying both is ambiguous and is `HTTP 400`.

### Choice
Alternative 1. The spec names `file` first and treats the two as
interchangeable spellings of one input rather than two inputs, so the pair is
an ordered preference list; rejecting the combination would invent an error the
spec does not list, since it only makes *missing both* a `400`.

### Risk: 15
Most likely author preference if different: `attachment` winning, from a lookup
that checks the fallback name last-write-wins.

---

## T40. Whether a plain text field named `file` counts as the upload

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`
> missing file field: `HTTP 400`

### Alternatives
1. Only a real file part (one with a `filename`) counts; a multipart *text*
   field named `file` leaves the file field missing, so the request is a `400`.
2. Any part named `file`/`attachment` counts, its body becoming the payload.

### Choice
Alternative 1. The spec calls the thing a "file field" and keys dataset identity
on "file bytes", which is the vocabulary of an uploaded file rather than of a
form value; reading the request's file parts is also what makes the `charset`
query parameter meaningful, since only a file part carries bytes to decode.

### Risk: 15
Most likely author preference if different: accepting any same-named part,
making a text-valued `file=a,b%0A1,2` field a successful upload.

---

## T41. `charset` on a source that is not text CSV

### Spec Text
> `charset` applies and validates only for text CSV sources.

### Alternatives
1. For `.xls`/`.xlsx` the parameter is ignored completely -- even a nonsense
   encoding name is accepted, because no validation happens.
2. The name is still validated as a known encoding, it is just not used to
   decode anything.

### Choice
Alternative 1. The sentence scopes both verbs, "applies *and validates*", to
text CSV sources, so a spreadsheet upload carrying `charset=not-an-encoding`
succeeds while the same parameter on a CSV is `HTTP 400`. Format detection
therefore runs before any decoding.

### Risk: 10
Most likely author preference if different: validating the encoding name for
every source and only skipping its use.

---

## T42. How the source format is detected

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> Unrecognized format: `HTTP 400`.

### Alternatives
1. From the payload's own bytes: the ZIP signature `PK\x03\x04` means `.xlsx`,
   the OLE2 signature means `.xls`, anything else takes the text CSV path.
2. From the filename extension of the upload, or the path of the `source` URL.
3. From the declared media type (the multipart part's type, or the response's
   `Content-Type`).

### Choice
Alternative 1, with the declared media type still able to veto a text payload
through the existing non-tabular content-type check. Both formats have fixed,
unambiguous signatures, whereas the other two signals are caller-supplied and
frequently absent -- a `/convert` URL need not end in `.csv`, and browsers send
`application/octet-stream` for spreadsheets often enough. Sniffing also makes
the two routes agree, which matters because the spec gives them one rule.

### Risk: 30
Most likely author preference if different: extension-driven dispatch, which
would reject CSV bytes served from a URL with no extension or uploaded as
`data.xlsx`, and would try to open CSV bytes named `.xls` as a workbook.

---

## T43. What makes a format "unrecognized"

### Spec Text
> Unrecognized format: `HTTP 400`.
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. Anything that is neither a readable workbook nor text that parses as a table:
   a ZIP or OLE2 container that no workbook reader can open (a `.docx`, a plain
   archive), a payload with a known document signature, or bytes that the
   existing non-tabular checks already reject.
2. An allowlist of extensions or media types, rejecting everything not named
   `.csv`, `.xls` or `.xlsx` before looking at the content at all.

### Choice
Alternative 1, which follows from detecting the format by content (T42): a
container that announces itself as a workbook but cannot be opened is an
unrecognized format, and so is a payload with a document signature such as
`%PDF-`. Everything else reaches the CSV path, where markup, NUL bytes, empty
bodies and non-tabular content are already `400`s, so no separate allowlist is
needed to produce the required status.

### Risk: 25
Most likely author preference if different: an extension/media-type allowlist,
which would also reject CSV bytes arriving under an unfamiliar extension.

---

## T44. How spreadsheet cell values become dataset values

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> Formula/computed-cell behavior is not required.

### Alternatives
1. Render every cell to deterministic text and then apply the same per-cell
   inference CSV uses: a number that is integral loses its `.0`, dates and times
   become ISO 8601 text, booleans become `TRUE`/`FALSE`, blank and error cells
   become empty.
2. Pass the reader's native Python objects straight through, so `.xls` numbers
   stay floats (`36.0`) and dates stay `datetime` objects.

### Choice
Alternative 1. `.xls` stores every number as a double, so alternative 2 would
make the same table type-infer differently depending on which of the two
spreadsheet formats it arrived in, and `datetime` is not JSON-representable at
all. Routing spreadsheet cells through the CSV inference rules keeps one
type-inference story for every source, and ISO 8601 keeps dates free of locale
influence as the Determinism section requires. Cached formula results are used
when the file carries them and are otherwise empty, which the spec permits.

### Risk: 30
Most likely author preference if different: `.xls` whole numbers surfacing as
`36.0`, straight from the reader.

---

## T45. Blank rows and the sheet's reported used range

### Spec Text
> spreadsheet columns preserve source order.
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. Treat the sheet like CSV lines: drop rows with no non-blank cell (they still
   consume their row number), and drop trailing columns that are empty in every
   row, since styling or a stray cell can inflate the used range.
2. Keep exactly what the reader reports, so a sheet whose used range is wider
   than its data gains columns named `""`.

### Choice
Alternative 1. Blank-line handling already exists for CSV and there is no reason
for the two source kinds to differ; a used range padded by formatting is an
artefact of the file format rather than part of the table's column order, and
carrying it through would produce unnamed columns that no filter or sort could
address.

### Risk: 15
Most likely author preference if different: the reader's raw used range,
differing only on a fixture with formatted-but-empty trailing cells.

---

## T46. `rowid` for rows that came from a spreadsheet

### Spec Text
> spreadsheet columns preserve source order.

### Alternatives
1. The sheet's own 1-based row number, so the header is row 1 and the first data
   row is row 2, matching how CSV source lines are numbered (T18, T26).
2. A fresh 1-based counter over the data rows that survived the blank-row drop.

### Choice
Alternative 1, for the same reason CSV keeps its source line numbers: `rowid`
identifies where a row sits in the source, and a spreadsheet row number is the
directly analogous coordinate.

### Risk: 12
Most likely author preference if different: sequential numbering of the kept
data rows, which differs only when a sheet contains blank rows.

---

## T47. Which sheet is "the first worksheet"

### Spec Text
> Only the first worksheet is ingested.

### Alternatives
1. The first sheet in tab order, whatever the file marks as active.
2. The workbook's active/selected sheet.

### Choice
Alternative 1. "First" is a position, and tab order is the only position a
workbook defines; the active sheet is view state that depends on where the
author last clicked, which would make ingestion non-deterministic in spirit.

### Risk: 8
Most likely author preference if different: the active sheet.

---

## T48. `multipart/form-data` with no usable boundary

### Spec Text
> - non-multipart request: `HTTP 415`
> - malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. The declared media type alone decides: the request says multipart, so a
   missing or wrong `boundary` parameter is *malformed multipart* and is `400`.
2. A multipart request that cannot be parsed at all was never really multipart,
   so it is `415`.

### Choice
Alternative 1. `415 Unsupported Media Type` is a statement about the media type
the client declared, and a request declaring `multipart/form-data` has declared
a supported one; everything that goes wrong after that is a malformed body,
which the spec routes to `400` in the very next bullet.

### Risk: 20
Most likely author preference if different: `415` for anything the multipart
parser cannot handle.
