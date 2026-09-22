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

---

## T49. Where `CACHE_ENABLED` is read from, and when

### Spec Text
> ### `CACHE_ENABLED`
> `CACHE_ENABLED` accepts strict case-insensitive values:
> Invalid values fail startup.

### Alternatives
1. An environment variable, read once while the application is built, so the
   setting is fixed for the life of the process.
2. A command line option on `start` (`--cache-enabled=...`), since the only
   other configuration the spec describes arrives that way.
3. An environment variable re-read on every `/convert` request, so the setting
   can be flipped without a restart.

### Choice
Alternative 1. The `SHOUTING_SNAKE_CASE` name is environment-variable spelling,
not an option name, and "fail **startup**" only makes sense for something read
at startup: a per-request read would fail a request, not the server, and the
CLI section of the spec lists `--port` and `--address` and nothing else.

### Risk: 8
Most likely author preference if different: the same variable, additionally
overridable by a `--cache-enabled` flag.

---

## T50. Unset, empty and padded `CACHE_ENABLED` values

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:
> - true: `1`, `true`, `yes`, `on`
> - false: `0`, `false`, `no`, `off`
> Invalid values fail startup.

### Alternatives
1. Unset means the documented default (`/convert` caches by default); anything
   else is compared, lower-cased, against the eight literals and nothing else,
   so `""` and `" true "` both fail startup.
2. Unset *and* empty both mean the default, because an exported-but-empty
   variable is conventionally "not set".
3. Trim surrounding whitespace before matching, accepting `" true "`.

### Choice
Alternative 1. "Strict" is the spec's own word, and it qualifies a list that
already spells out the one liberty taken (case). An empty value is a value the
operator supplied; treating it as unset would mean `CACHE_ENABLED=` silently
enables caching, which is exactly the quiet misconfiguration that "fail
startup" exists to prevent.

### Risk: 25
Most likely author preference if different: `raw.strip().lower()` before the
lookup, which accepts padded values instead of rejecting them.

> **Resolved by the Configuration spec.** "Boolean values are strict:
> `1/true/yes/on` or `0/false/no/off` (case-insensitive, **trimmed**)" settles
> it the other way: values are now trimmed before the lookup, so `" true "` is
> accepted. Empty stays a failure -- it is not one of the eight literals -- and
> the rule now covers `REQUIRE_TLS` as well as `CACHE_ENABLED`. See [T60] for
> how an empty value is read for the non-boolean settings.

---

## T51. How "fail startup" manifests

### Spec Text
> Invalid values fail startup.

### Alternatives
1. Building the application raises, so `python datagate.py start` prints the
   reason on stderr and exits non-zero without ever binding the port.
2. The server starts and every `/convert` returns `HTTP 500`.
3. The server starts with the default (caching on) and logs a warning.

### Choice
Alternative 1. "Fail startup" names the moment: the process must not come up.
Validation therefore happens in `create_app`, before `app.run`, so no socket is
opened and nothing is served from a configuration nobody vouched for. The exit
message names `CACHE_ENABLED` and the offending value.

### Risk: 12
Most likely author preference if different: the same refusal with a specific
exit code (`2`) that a test could assert on, rather than any non-zero status.

---

## T52. Whether `force=` counts as "a value"

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.
> Any `force` value is `HTTP 400`.

### Alternatives
1. `?force` and `?force=` are both the bare flag. A query string parser reports
   both as the empty string, so "a value" means a non-empty one.
2. `?force=` supplies an (empty) value and is therefore `HTTP 400`; only a
   `force` with no `=` at all is the presence flag.

### Choice
Alternative 1. `?force` and `?force=` are indistinguishable once the query
string has been parsed -- WSGI hands both to the application as `force` mapped
to `""` -- so telling them apart means re-parsing the raw query string to
enforce a distinction no client controls deliberately. "Any `force` value"
reads as "any value a caller meant to send", and an empty one is not that.

### Risk: 20
Most likely author preference if different: raw query-string inspection where
only a bare `force` (no `=`) is the flag and `force=` is a `400`.

---

## T53. `force` supplied more than once

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.

### Alternatives
1. "Once" is a requirement: `?force&force` is not "present once" and is
   `HTTP 400`, matching how the spec already treats a repeated control
   parameter.
2. "Once" is incidental prose about the ordinary case, and repeats collapse to
   plain presence, so `?force&force` forces re-ingestion and returns `200`.

### Choice
Alternative 1. The spec pointedly says "if present **once**" rather than "if
present", in the same breath as making any accompanying value an error -- both
sentences are about the flag being malformed. The rest of the API rejects
repeated parameters instead of picking one occurrence, so repeats failing keeps
the surface consistent.

### Risk: 30
Most likely author preference if different: repeats treated as ordinary
presence, returning `200` and re-ingesting.

---

## T54. `force` with a value while caching is disabled

### Spec Text
> Any `force` value is `HTTP 400`.
> If caching is disabled, `force` has no additional effect.

### Alternatives
1. The `400` is a statement about the request's shape and is raised before the
   cache is consulted, so `CACHE_ENABLED=0` plus `force=1` is still `400`.
2. "No additional effect" means `force` is ignored entirely when caching is
   off, including its validation, so `force=1` is then a `200`.

### Choice
Alternative 1. "No additional effect" is about what `force` *does* -- with
caching off, re-ingestion already happens on every request, so forcing it adds
nothing. A malformed parameter is rejected before behaviour is decided, and it
would be odd for the same request to be valid or invalid depending on a server
setting the caller cannot see.

### Risk: 18
Most likely author preference if different: a cache-disabled server ignoring
`force` completely, value and all.

---

## T55. Whether `charset` takes part in the cache key

### Spec Text
> With caching enabled, repeated `/convert` requests for the same source URL can
> return the cached dataset id without re-downloading.

### Alternatives
1. The cache is keyed on the dataset id alone, which the spec derives from the
   source URL. A repeat with a different `charset` is still a cache hit and
   returns the dataset as first parsed.
2. `charset` joins the key, so changing it misses the cache and re-ingests --
   but then the same URL would have to yield one dataset id for two different
   parses, contradicting the id rule.
3. A differing `charset` invalidates the entry and forces re-ingestion under
   the same id.

### Choice
Alternative 1. The spec says "for the same source URL", and the dataset id --
the thing the cache is looking up -- is defined by that URL and nothing else.
Callers who want a different decoding have `force`, which is exactly the
documented way to replace a cached dataset.

### Risk: 22
Most likely author preference if different: a differing `charset` re-ingesting
under the same id (alternative 3).

---

## T56. What a cache hit still validates

### Spec Text
> ... can return the cached dataset id without re-downloading.
> Cache responses are identical to fresh parse responses.

### Alternatives
1. A cache hit short-circuits everything the download fed: the payload is not
   re-fetched, re-decoded or re-parsed, so an unusable `charset` is never
   examined and the request succeeds.
2. `charset` is validated as a codec name on every request, before the cache is
   consulted, so `charset=utf-99` is `400` even on a hit.

### Choice
Alternative 1. The only per-request validation the caching section adds is for
`force`; everything else about the hit path is defined by what it skips.
`charset` exists to decode bytes, and on a hit no bytes are decoded, so there is
nothing for it to be unsupported *for*. This also keeps "identical to fresh
parse responses" literally true of the stored response.

### Risk: 15
Most likely author preference if different: validating the `charset` name up
front, making an unusable one `400` even when the dataset is cached.

---

## T57. Whether `force` means anything on `/upload`

### Spec Text
> ### Per-request bypass
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.

### Alternatives
1. `force` belongs to `/convert`, the only route the section describes as
   caching. `/upload` already re-parses and replaces on every request, so the
   parameter is ignored there like any other unknown one.
2. `force` is validated on both ingest routes, so `POST /upload?force=1` is
   `400` for symmetry.

### Choice
Alternative 1. The whole section is scoped by its opening line, "`/convert`
caches results by default", and an upload carries its bytes with it -- there is
no download to skip and no cached fetch to bypass, so the flag has nothing to
mean there.

### Risk: 12
Most likely author preference if different: `force` with a value rejected on
`/upload` too.

---

## T58. A failed re-ingestion that was not forced

### Spec Text
> When disabled, every `/convert` request re-downloads/parses and replaces
> stored data.
> - Re-ingestion failures keep existing error codes and envelope.
> - Forced re-ingestion failure keeps prior dataset queryable.

### Alternatives
1. Stored data is replaced only by a successful parse, in every mode. A failed
   re-ingestion -- forced or on a cache-disabled server -- leaves the previous
   dataset queryable and returns the ordinary error envelope.
2. The guarantee is written only for the forced case, so with caching disabled
   a failed re-download clears the stored dataset and later queries `404`.

### Choice
Alternative 1. "Replaces stored data" describes what a successful ingestion
does with the result it produced; a request that produced no dataset has
nothing to replace anything with. Dropping good data because a later fetch
failed would also make the failure destructive, which no error row in the spec
suggests.

### Risk: 10
Most likely author preference if different: a cache-disabled failure evicting
the previous dataset.

---

## T59. Unknown keys and lines without `=` in the config file

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values,
> blank/comment lines ignored.
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. A line that is not blank, not a comment and carries no `=` is invalid config
   and stops startup; a well-formed line whose key is outside the settings table
   is parsed and then simply unused.
2. Both are fatal: a key the service does not recognise is as much a
   misconfiguration as a malformed line, and failing loudly catches typos like
   `MAX_SOURCE_SIZ=10`.
3. Neither is fatal: anything the parser cannot use is skipped, so the file is
   best-effort and only bad *values* fail startup.

### Choice
Alternative 1. "`KEY=VALUE` lines" describes the shape of the file, and a line
without a `=` has no shape to read -- that is the one structural failure the
"invalid config" row can be about, since blank and comment lines are explicitly
excused. Rejecting unknown keys is a different promise: config files are
routinely shared between versions and tools, and the spec's table lists the
settings that are read, not the only keys that may appear.

### Risk: 25
Most likely author preference if different: a no-`=` line skipped silently
alongside comments, so only bad values ever fail startup.

---

## T60. What an empty value means

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> | `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |
> | `STORAGE_DIR` | path | implementation-defined |
> Boolean values are strict: `1/true/yes/on` or `0/false/no/off`

### Alternatives
1. Split by setting: for the three whose default is "unset" or
   "implementation-defined", an empty value supplies nothing and the default
   stands; for the two booleans, an empty string is not one of the eight strict
   literals and so fails startup.
2. Empty always means unset, booleans included, so `CACHE_ENABLED=` starts with
   caching on.
3. Empty always fails startup, because the operator wrote the key.

### Choice
Alternative 1. The boolean rule is the spec's only enumerated value set and it
calls itself strict, so `""` cannot be read as `false` or as `true` without
inventing a ninth literal. The other three settings have no value set at all --
their defaults are named "unset" -- so `ORIGIN_ALLOWLIST=` has an obvious
reading: a list with no entries, which is what "unset" already means. That also
keeps `MAX_SOURCE_SIZE=` and a commented-out line equivalent.

### Risk: 35
Most likely author preference if different: an empty `MAX_SOURCE_SIZE` treated
as an invalid integer and failing startup, matching the boolean strictness.

---

## T61. What counts as "integer bytes" for `MAX_SOURCE_SIZE`

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. A run of decimal digits, parsed as a non-negative byte count. `-1`, `4.5`,
   `1e3`, `0x10`, `10MB` and `10 000` all fail startup.
2. Anything Python's `int()` accepts, which additionally allows a leading `+`
   or `-`, surrounding whitespace and digit underscores (`1_000`).
3. A human-readable size grammar with `K`/`M`/`G` suffixes.

### Choice
Alternative 1. The type column says "integer bytes", and a byte count below
zero is not a size any file can be compared against -- accepting `-1` would
silently reject every request instead of failing startup, which is the outcome
the "invalid config" row exists to prevent. Suffixed sizes are a grammar the
spec never mentions.

### Risk: 20
Most likely author preference if different: a bare `int(value)`, which accepts
`-1` and `+10` and then rejects (or accepts) everything at request time.

---

## T62. The domain-boundary rules for an allowed suffix

### Spec Text
> 3. Accept only hostnames matching any allowed suffix case-insensitively with
>    domain-boundary rules.

### Alternatives
1. `hostname == suffix` or `hostname.endswith("." + suffix)`, both lower-cased,
   with a trailing root dot on the hostname and an optional leading dot on the
   configured suffix normalised away. `example.com` therefore covers
   `example.com` and `app.eu.example.com`, but not `notexample.com` and not
   `example.com.evil.net`.
2. Plain `hostname.endswith(suffix)`, which is what "suffix" says literally and
   which lets `notexample.com` through -- the very thing "domain-boundary rules"
   is there to stop.
3. Boundary matching on labels only, with no exact match: a configured
   `example.com` would allow `app.example.com` but reject `example.com` itself.

### Choice
Alternative 1. "Domain-boundary" means the suffix has to begin at a label
break, which rules out alternative 2, and a domain is a suffix of itself, which
rules out alternative 3 -- an allowlist naming the site the service is embedded
in that then refused that site's own pages would be useless. Normalising a
leading dot means `.example.com` and `example.com` cannot be configured to mean
different things, and the trailing root dot is not part of the name.

### Risk: 15
Most likely author preference if different: the same label matching without the
trailing-dot and leading-dot normalisation, so `https://example.com./page` is
refused.

---

## T63. Which size is measured for `/convert`

### Spec Text
> ### Maximum Source Size
> Enforced for `/convert` and `/upload`:
> - file size `= limit` accepted.
> - file size `> limit` => `HTTP 400` with standard envelope.

### Alternatives
1. The byte length of the payload the service actually has: the downloaded body
   for `/convert`, the uploaded part for `/upload`. The source is fetched, then
   measured.
2. The `Content-Length` header the origin advertised, so an oversized source is
   refused before its body is read -- and one that advertises no length is
   accepted regardless of size.
3. The size after decoding to text, i.e. a character count.

### Choice
Alternative 1. "File size" is a property of the file, and the only figure the
service can be sure of is the one it holds; `Content-Length` is a claim, is
absent from chunked responses and would make the same file pass or fail
depending on how the origin served it. Bytes rather than characters also keeps
the limit meaningful for the two binary formats, where "characters" has no
meaning at all.

### Risk: 25
Most likely author preference if different: a `Content-Length` pre-check that
refuses an oversized source without downloading it.

---

## T64. Whether a `/convert` cache hit is re-measured

### Spec Text
> Enforced for `/convert` and `/upload`
> `/convert` caches results by default ... repeated requests for the same source
> URL return the cached dataset id without re-downloading.

### Alternatives
1. The limit applies to ingestion. A cache hit fetches no file, so there is no
   file size to compare and the stored dataset is served as usual -- including
   after a restart that lowered `MAX_SOURCE_SIZE`.
2. The limit applies to the route. A dataset whose source exceeds the current
   limit is refused even on a hit, which would mean re-downloading it to find
   out its size, undoing the caching guarantee.

### Choice
Alternative 1. The size rule is written about a file, and a cache hit never
touches one: measuring it would require exactly the download the caching
section promises not to make. The limit therefore governs what may enter the
store, not what may leave it -- which is also why `/datasets/<id>` and its
export are unaffected.

### Risk: 20
Most likely author preference if different: the limit stored alongside the
dataset and re-checked, so lowering it retires oversized datasets.

---

## T65. Where the size check sits among the other `400`s

### Spec Text
> - file size `> limit` => `HTTP 400` with standard envelope.

### Alternatives
1. First: the payload is measured before its format is recognised, decoded or
   checked for a header row, so an oversized file reports its size whatever is
   in it.
2. Last: the file is parsed first and the size reported only if the parse
   succeeded, so an oversized PDF reports the format problem instead.

### Choice
Alternative 1. Both orders produce `HTTP 400`, so only the message differs, but
a size limit exists to cap the work a request can cause -- parsing megabytes
before admitting they were too many defeats it. Measuring bytes also needs
nothing from the payload, so it is the cheapest check available.

### Risk: 10
Most likely author preference if different: format recognition first, changing
only which message an oversized non-tabular payload returns.

---

## T66. What "check every request before routing" covers

### Spec Text
> If configured, check every request before routing:
> 1. Require `Referer`.
> ...
> 4. Otherwise return `HTTP 403`.

### Alternatives
1. Every request the service receives, on any method and any path. A path that
   does not exist is `403` rather than `404`, because the check runs before the
   URL is matched.
2. Only the documented routes, with unknown paths still `404`: a request that
   matches nothing was never going to reach a handler.
3. Only the ingest routes, `/convert` and `/upload`, since those are the ones
   that act on a caller's behalf.

### Choice
Alternative 1. "Every request" and "before routing" are both explicit, and the
ordering is the point: an access check that runs after routing tells an
unlisted origin which paths exist. Reading a dataset is a request too, so
`/datasets/<id>` and its export are guarded like the rest.

### Risk: 30
Most likely author preference if different: unknown paths still answering `404`
because the framework matches the route before the guard runs.

---

## T67. Which host the absolute `https://` endpoint uses

### Spec Text
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request
> host.

### Alternatives
1. The `Host` header of the request being answered, port and all, so a service
   reachable under several names advertises the one the client used.
2. The host the server is bound to (`--address` and `--port`), which is what the
   process knows about itself.
3. The `Host` header with any port stripped, on the grounds that an `https://`
   URL should carry the TLS port.

### Choice
Alternative 1. "Request host" names the request, not the socket, and it is the
value a client can actually reach again. Keeping the port preserves that
property for a service behind a non-default port; dropping it would invent an
address nothing is listening on. Only the prefix changes -- the dataset id and
path are the same ones the relative form returns.

### Risk: 15
Most likely author preference if different: the port stripped, so
`https://host:8443/...` is advertised as `https://host/...`.

---

## T68. Whether `REQUIRE_TLS` also rejects plain-`http` requests

### Spec Text
> ### TLS-aware endpoint URLs
> `REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints.
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request
> host.

### Alternatives
1. The setting only shapes the URLs the service advertises. A request arriving
   over plain `http` is served normally, and the endpoint it gets back is an
   `https://` URL.
2. The name is taken at face value: with `REQUIRE_TLS=true`, a request that did
   not arrive over TLS is refused (`403`) or redirected.

### Choice
Alternative 1. The section is titled "TLS-aware endpoint URLs" and describes
only what the two ingest routes return; the error table adds no row for a
plain-`http` request, while it does spell out every other refusal in this spec.
A service behind a TLS-terminating proxy also sees plain `http` on the wire, so
refusing those requests would break the ordinary deployment the setting is for.

### Risk: 30
Most likely author preference if different: `REQUIRE_TLS=true` additionally
refusing requests whose scheme is not `https`.

---

## T69. The default `STORAGE_DIR`, and what "persisted" means

### Spec Text
> ### Storage Directory
> Create `STORAGE_DIR` if missing.
> Persisted datasets must survive restart when the same directory is reused.
> | `STORAGE_DIR` | path | implementation-defined |

### Alternatives
1. Every ingested dataset is written to the directory as one JSON document per
   id, and `/datasets/<id>` reads it back, so a dataset outlives the process
   that ingested it. The default is a fixed path under the system temporary
   directory (`<tmp>/datagate`), which is writable without setup and is itself
   reused across restarts.
2. The directory is a cache of downloaded *source* files rather than parsed
   datasets, so a restart re-parses on demand.
3. Datasets stay in memory and the directory only holds an index, which would
   not survive anything.

### Choice
Alternative 1. "Persisted datasets" names datasets, not downloads, and the only
observable promise is that the same id answers after a restart -- which means
the parsed table, including each row's source row number, has to be on disk.
One file per id keeps ids independent, and writing through a temporary name
means a reader never sees a partial document. The default has to be a real path
the spec does not name; a fixed temporary-directory entry keeps a bare
`python datagate.py start` working while still reusing its own storage.

### Risk: 25
Most likely author preference if different: a default under the working
directory (`./datagate-data` or similar) rather than the temporary directory --
invisible to any test that sets `STORAGE_DIR` itself.

---

## T70. A `Referer` that parses to no hostname

### Spec Text
> 1. Require `Referer`.
> 2. Parse hostname.
> 3. Accept only hostnames matching any allowed suffix ...
> 4. Otherwise return `HTTP 403`.

### Alternatives
1. An empty header, a relative URL (`/page`) and an unparseable value all end
   at step 4: there is no hostname, so nothing can match and the request is
   `403`.
2. An empty header is "missing `Referer`" while an unparseable one is "referer
   not allowed" -- two rows of the error table, but the same status.

### Choice
Alternative 1 for the outcome, with the message following the distinction: a
header that is absent or empty reports the missing-`Referer` failure, anything
that parses to no hostname reports the not-allowed failure. Both error rows are
`403` with the same envelope, so only the wording differs.

### Risk: 5
Most likely author preference if different: the same status with the other
message, which no status-and-shape assertion can see.

---

## T71. How the layers merge

### Spec Text
> Service configuration sources, in order of precedence:
> 1. Built-in defaults
> 2. `DATAGATE_CONFIG` file
> 3. Direct environment variables

### Alternatives
1. Per key: each setting is taken from the highest-precedence layer that names
   it, so a file of five settings plus one environment variable yields four
   file values and one environment value.
2. Whole-file: if any direct environment variable is set, the config file is
   ignored entirely.
3. The file wins over the environment, reading the list as least-precedence-last.

### Choice
Alternative 1. Per-key merging is what a precedence list means everywhere it
appears, and the list is numbered from the weakest source: built-in defaults
are unambiguously the thing everything else overrides, so the numbering runs
low-to-high and the environment is the strongest. `DATAGATE_CONFIG` itself is
read from the environment and names the file, so it is not one of the settings
the file can supply.

### Risk: 10
Most likely author preference if different: the same ordering read in reverse,
making the config file override the environment.

---

## T72. Which `enrich` states are "off" and which are errors

### Spec Text
> Only a single, exact `enrich=yes` enables enrichment.
> All other states keep enrichment off.

### Alternatives
1. Every state other than one exact `enrich=yes` simply leaves enrichment off:
   `enrich=YES`, `enrich=1`, `enrich=no`, a bare `enrich`, an empty `enrich=`
   and a repeated `enrich=yes&enrich=yes` are all accepted and unenriched.
2. Only absence and a recognised negative are off; an unrecognised value is
   `HTTP 400`, the way `force` rejects a value it cannot use (T52, T53).
3. Case-insensitive truthiness: `YES`, `1`, `true` also enable enrichment.

### Choice
Alternative 1. "All other states keep enrichment off" is an outcome, not an
error, and it is worded to cover every state rather than a list of accepted
ones; "a single" additionally settles the repeated case as off rather than as a
rejection. This is the one control on `/convert` the spec describes in terms of
what it does instead of what it validates, so it is deliberately unlike `force`.

### Risk: 18
Most likely author preference if different: a repeated `enrich` rejected with
`HTTP 400`, by analogy with the repeated-`force` rule.

---

## T73. The `filetype` label for a CSV dataset

### Spec Text
> - `dataset_summary` with at least `filetype`, `row_count`, `column_count`
> For enriched spreadsheet datasets, add only `dataset_summary` with `filetype: "excel"`.

### Alternatives
1. `"csv"`, the short format name that matches the style of `"excel"`.
2. The media type, `"text/csv"`.
3. The concrete extension the bytes came in as, so `.xls` and `.xlsx` would also
   be distinguished from each other.

### Choice
Alternative 1. `"excel"` is the only label the spec fixes, and it is a short,
lower-case format family name rather than a media type or an extension -- it
covers both `.xls` and `.xlsx`. `"csv"` is the same kind of token for the other
family, so the two labels stay in one vocabulary.

### Risk: 8
Most likely author preference if different: `"text/csv"`, from the media type
the fetch reported.

---

## T74. Whether the spreadsheet `dataset_summary` also carries the two counts

### Spec Text
> For enriched spreadsheet datasets, add only `dataset_summary` with `filetype: "excel"`.

### Alternatives
1. "Only" scopes which top-level fields are added -- `dataset_summary` and not
   `column_details` -- so the summary keeps the same shape as for CSV, with
   `row_count` and `column_count` alongside `filetype`.
2. "Only" scopes the contents too, so the summary of a workbook is exactly
   `{"filetype": "excel"}`.

### Choice
Alternative 1. The field is introduced one paragraph earlier as having "at
least `filetype`, `row_count`, `column_count`", and nothing about a workbook
makes a row or column count unavailable -- it is parsed into the same table as a
CSV. Reading "only" as being about the two named metadata fields also matches
the following sentence, which talks about omitting "both metadata fields".

### Risk: 18
Most likely author preference if different: a workbook summary holding
`filetype` alone.

---

## T75. How the four type labels are assigned to a column

### Spec Text
> - `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`
> Type labels: `text`, `number`, `integer`, `float`.

### Alternatives
1. A hierarchy: a column with any non-numeric cell is `text`; an all-numeric
   column is `integer` when every cell is a whole number, `float` when every
   cell is a decimal, and `number` when it mixes the two.
2. `number` for every numeric column, with `integer`/`float` unused in practice
   (or reserved for a per-cell rather than per-column label).
3. Widening: a numeric column that mixes whole and decimal cells is `float`,
   and `number` is used for a column mixing numbers with text.

### Choice
Alternative 1. The label list reads as two families -- `text` and `number` --
with `integer` and `float` as the refinements of the numeric one, which is the
only arrangement that gives all four labels a job. A column that mixes whole and
decimal cells is numeric but neither refinement, so `number` is what is left for
it; a column that mixes numbers with words is not numeric at all, and `text` is
the only label that can carry it.

### Risk: 35
Most likely author preference if different: a mixed whole/decimal column
labelled `float`, with `number` kept for columns that mix numbers and text.

---

## T76. What counts as a missing cell, and whether missing cells affect `type`

### Spec Text
> - `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`

### Alternatives
1. A cell is missing when it is empty or holds only whitespace -- including the
   padding cells of a short row -- and missing cells are excluded before the
   type is decided, so a numeric column with gaps is still `integer`/`float`.
2. Only the exact empty string is missing; a whitespace-only cell is text.
3. Missing cells count as values for typing, so any gap makes a numeric column
   `text`.

### Choice
Alternative 1. `missing_count` exists precisely so that absent cells are
reported separately from the column's type, so letting them decide the type
would make one of the two fields misleading; and a short row is padded with
empty cells by the table builder, which is the same absence as a `,,` gap.
Whitespace-only is treated as empty because the header names and the numeric
inference already read cells trimmed.

### Risk: 22
Most likely author preference if different: only `""` counted as missing, so a
`" "` cell is a text value and turns its column's type to `text`.

---

## T77. What `distinct_count` counts

### Spec Text
> - `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`

### Alternatives
1. Distinct values among the cells that are present, so the gaps reported by
   `missing_count` do not add a value of their own.
2. Distinct values over every cell, so a column with a gap has one extra
   distinct value (the empty one).
3. Distinct over the raw source text rather than the typed value, so `1` and
   `1.0` are two values.

### Choice
Alternative 1. The two counts read as a partition of the column -- what is
there, and what is not -- so counting the absence as one of the distinct values
would double-report it. Counting typed values matches what a query returns:
`rows` never exposes the source text, and the type label describes typed cells.

### Risk: 28
Most likely author preference if different: distinct taken over all cells
including the empty ones, adding one to any column with a gap.

---

## T78. Whether the counts describe the stored dataset or the current query

### Spec Text
> - `dataset_summary` with at least `filetype`, `row_count`, `column_count`
> Re-ingestion recomputes metadata from current source bytes.
> `rows`, `columns`, `ok`, `query_ms`, and `total` do not change.

### Alternatives
1. Metadata is computed once, at ingestion, over the whole table, so filters,
   sorting and pagination never change it: `row_count` is every data row and
   `column_details` describes whole columns.
2. Metadata is computed per request over the rows the query selected, so it
   tracks `total` and the page.

### Choice
Alternative 1. The spec calls it "ingestion enrichment", ties recomputation to
re-ingestion and to "current source bytes", and makes enrichment a property of
what is *stored* -- a cached dataset is "enriched" or not. A per-query
computation would also make `total` and `row_count` redundant where they differ.

### Risk: 12
Most likely author preference if different: `row_count` following the filtered
row count of the request.

---

## T79. Whether a re-ingestion without `enrich=yes` downgrades stored state

### Spec Text
> - `enrich=yes` on a cached non-enriched dataset forces re-ingestion and upgrades stored state.
> - Requests without re-ingestion do not change stored enrichment state.
> Enrichment failures ... must not downgrade to non-enriched storage.

### Alternatives
1. Enrichment state is a property of each ingestion: any re-ingestion -- a
   `force` request, or every request while `CACHE_ENABLED=false` -- stores what
   that request asked for, so re-ingesting without `enrich=yes` leaves the
   dataset non-enriched.
2. Enrichment is sticky: once a dataset has been enriched, later re-ingestions
   keep computing metadata whether or not they asked for it.

### Choice
Alternative 1. The cache rules are written as a pair: requests that do not
re-ingest leave the stored state alone, which only needs saying if requests that
do re-ingest set it. The one place the spec forbids losing enrichment is a
*failed* enrichment, which would be redundant if enrichment could never be
dropped by a successful re-ingestion.

### Risk: 32
Most likely author preference if different: enrichment sticky across
re-ingestions, so a plain `force` on an enriched dataset stays enriched.

---

## T80. What an "enrichment failure" is

### Spec Text
> Enrichment failures return standard JSON errors and must not downgrade to non-enriched storage.

### Alternatives
1. Any failure of a request that asked for enrichment -- the download, the
   format, the decode, the tabular check, or computing the metadata itself.
   Metadata is computed before anything is written, so a failure reports the
   usual status and envelope and leaves the previously stored dataset exactly as
   it was, enriched or not (the same rule as T58).
2. Only a failure inside the metadata computation, with the dataset still stored
   unenriched so the rows remain queryable.
3. A failure to enrich degrades silently to a non-enriched success.

### Choice
Alternative 1. "Standard JSON errors" points at the existing envelope and
status table rather than a new class of error, and "must not downgrade to
non-enriched storage" rules out Alternatives 2 and 3 directly: storing the table
without its metadata is the downgrade being forbidden. Writing the dataset only
after its metadata exists gives both properties at once.

### Risk: 20
Most likely author preference if different: the same statuses, with the
requirement tested only through a failing re-ingestion over an already enriched
dataset.
