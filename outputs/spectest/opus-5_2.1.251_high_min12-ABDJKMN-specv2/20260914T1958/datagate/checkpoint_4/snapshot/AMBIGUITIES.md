# AMBIGUITIES

Ambiguities found in the `datagate` spec, with the interpretation chosen for this
implementation. Risk is the estimated chance (0-100) that the spec author's own
implementation (against which the hidden tests are written) behaves differently
from the choice below on some tested input.

---

## T1. Derivation and format of the dataset id

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. A hash of the source URL (sha256/md5, full or truncated hex).
2. A deterministic UUID (uuid5 over the URL).
3. A URL-safe encoding of the source URL itself (base64/percent-encoding).
4. A monotonic counter keyed by URL (deterministic within a process, but not
   across restarts).

### Choice
`sha256(source.encode("utf-8")).hexdigest()[:16]` — a stable, opaque, URL-safe
hex id. The spec constrains only the *mapping* (same URL -> same id), never the
literal id text, and every success path returns the id back to the caller inside
`endpoint`, so tests can only reasonably assert stability and round-tripping.
A hash also survives process restarts, which a counter does not.

### Risk: 8
Most likely different reading: the author uses a different digest/length (e.g.
full sha256 hex or md5) and asserts the exact id string in a fixture.

---

## T2. Does the id depend on anything besides the source URL?

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. The id is a function of `source` alone; a second `/convert` with a different
   `charset` reuses the same id and replaces the stored dataset.
2. The id is a function of `(source, charset)`, so the same URL decoded two
   different ways yields two distinct datasets.

### Choice
Alternative 1. The spec says "the same `source` URL string" with no mention of
`charset`, and states the rule again under Determinism as a property of the
source URL only. Re-converting the same URL overwrites the stored rows, so the
most recent decode wins.

### Risk: 12
Most likely different reading: the author keys storage by URL but never
overwrites, so the *first* conversion's rows persist for later `charset` calls.

---

## T3. Is the 100-row cap adjustable?

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. 100 is a hard cap; no query parameter exists.
2. "Default" implies an undocumented override, e.g. `/datasets/<id>?limit=N`.

### Choice
Support an optional `limit` (and `offset`) query parameter that defaults to 100,
clamped to `>= 0`; with no parameter the behaviour is exactly the documented
cap. The word "default" reads as if an override exists, and honouring one cannot
change behaviour for any request that does not send it — the documented contract
is preserved either way.

### Risk: 15
Most likely different reading: the author ignores `limit` entirely and a fixture
requesting `?limit=5` still expects 100 rows (or expects `limit` to be capped at
100 rather than allowed to exceed it).

### Resolved (Pagination, Sorting, and Response Controls)
The controls spec names the override explicitly: `_size` (positive integer,
default `100`) and `_offset` (non-negative integer, default `0`). Alternative 2
was right that an override exists, but the guessed spelling was wrong. The bare
`limit`/`offset` parameters have been **removed**; they are now ordinary unknown
query parameters and are ignored. `_size` is still allowed to exceed 100 ("if it
exceeds available rows, return all" caps it at the dataset, not at the default).

### Amended (Column-Level Filtering)
"Ignored" is now narrower: a param is ignored only if it neither begins with `_`
nor contains `__`. `limit`/`offset` still qualify, but an unknown name containing
`__` is a filter and is validated (400), not ignored.

---

## T4. How strict is numeric type inference?

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Naive `int(s)` then `float(s)`: accepts `1e5`, `007`, `nan`, `inf`, `0x1f`
   (no), surrounding whitespace, and unicode digits.
2. Strict decimal-only regexes: `[+-]?\d+` -> int, `[+-]?\d*.\d*` -> float;
   everything else (exponents, `nan`, `inf`, `1,234`, `$5`, `50%`) stays text.

### Choice
Alternative 2, with leading zeros still converted (`007` -> `7`). "Integers /
decimals" names exactly two lexical forms, and `nan`/`inf` are not
representable in strict JSON, so admitting them via `float()` would break the
envelope. Thousands separators and decimal commas are excluded because the spec
forbids locale dependence.

### Risk: 30
Most likely different reading: the author uses bare `float()` as a fallback, so
`1e5` (and possibly `nan`) comes back as a JSON number rather than text.

---

## T5. Is surrounding whitespace in a field preserved?

### Spec Text
> The endpoint returns stored rows and columns, in source order.

### Alternatives
1. Preserve cell text byte-for-byte, so `a, b` yields the column name `" b"`.
2. Strip leading/trailing whitespace from every header and data cell before
   type inference and storage.

### Choice
Alternative 2. A header of `name, value` almost certainly intends the columns
`["name", "value"]`, and Python's own `int(" 2")` already tolerates padding, so
stripping makes the string and numeric paths agree. Interior whitespace and
whitespace inside quoted fields that a csv dialect preserves are untouched.

### Risk: 18
Most likely different reading: the author does not strip, and a fixture with
spaces after the delimiter expects the padded column name verbatim.

---

## T6. What counts as an "unambiguous" detected encoding?

### Spec Text
> `charset` ... If omitted, detect unambiguous encoding from content, else latin-1.

### Alternatives
1. Run a statistical detector (chardet / charset-normalizer) and accept its best
   guess whenever confidence is high, else latin-1.
2. Accept only self-identifying encodings: a BOM, or bytes that decode cleanly
   as UTF-8; every other byte string is ambiguous, hence latin-1.

### Choice
Alternative 2. "Unambiguous" is doing real work in that sentence: UTF-8 and
BOM-marked UTF-16/32 can be *proved* from the bytes, while single-byte legacy
encodings genuinely cannot be distinguished from one another — which is exactly
why latin-1 (the encoding that never fails) is the stated fallback. This also
satisfies Determinism, since no probabilistic detector is involved.

### Risk: 22
Most likely different reading: the author calls a detector library, so a cp1252
file with smart quotes decodes to the intended punctuation instead of latin-1's
C1 control characters.

---

## T7. Explicit `charset` that cannot decode the bytes

### Spec Text
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. "Unsupported or malformed" describes only the codec *name*; a real codec that
   raises `UnicodeDecodeError` is handled leniently (`errors="replace"`).
2. Both a bad codec name and a failed strict decode are 400.

### Choice
Alternative 2 — strict decoding, and any `LookupError` or `UnicodeDecodeError`
becomes 400 with a human-readable message. Silently substituting U+FFFD would
store corrupted values while reporting `"ok": true`, and the spec offers no
other status for "you told me the wrong encoding".

### Risk: 25
Most likely different reading: the author decodes with `errors="replace"` (or
`errors="ignore"`) and returns 200 with mojibake when a mismatched-but-valid
codec name is supplied.

---

## T8. What makes a URL "invalid"?

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Only syntactically unparseable strings are invalid; `ftp://` or `file:///etc`
   are well-formed and so fail later as "unreachable" (404).
2. Anything that is not an absolute `http`/`https` URL with a host is invalid
   (400): no scheme, unknown scheme, or empty host.

### Choice
Alternative 2. The service fetches "a remote CSV file" over HTTP, so a scheme it
cannot fetch is a caller error, not a reachability problem — and it keeps
`file://` from turning the service into a local-file reader. Reserving 404 for
network/HTTP outcomes matches the table's wording.

### Risk: 12
Most likely different reading: the author passes non-HTTP schemes straight to
the fetch layer and reports the resulting failure as 404.

---

## T9. What is "non-tabular content"?

### Spec Text
> | Non-tabular content | 400 |
> - Delimiter must be inferred from input, if present; minimum supported delimiters are `,`, `;`, and `\t`.
> - A valid file requires at least one header row and one data row.

### Alternatives
1. Tabular means "a delimiter was found". A file with no `,`/`;`/`\t` (the
   typical `csv.Sniffer` failure) is non-tabular, so single-column CSV is 400.
2. "if present" explicitly contemplates input with no delimiter, so a
   single-column file with a header and a data row is valid; only markup,
   JSON, binary, empty, or header-only content is 400.

### Choice
Alternative 2, plus guards, because "if present" only makes sense if absence is
survivable. Rejected as non-tabular: empty/blank bodies, fewer than two
non-blank lines, NUL bytes (binary), content whose first non-space character is
`<` (HTML/XML) or `{`/`[` (JSON), and — when no delimiter is found —
prose-looking content, defined as any line carrying more than four
whitespace-separated tokens. The prose guard exists because otherwise an HTML-
free block of English text would masquerade as a one-column dataset.

### Risk: 35
Most likely different reading: the author delegates to `csv.Sniffer`, whose
failure to find a delimiter is itself the 400 — making every single-column file
non-tabular.

---

## T10. Rows whose field count differs from the header

### Spec Text
> `columns` and each row follow source column order.

### Alternatives
1. Ragged input is malformed, hence non-tabular: 400.
2. Normalise each row to the header width: pad short rows, truncate long rows.
3. Return rows at their natural width, so rows have differing lengths.

### Choice
Alternative 2. Delimiter inference already scores candidates by how consistent
the field counts are, so the winning delimiter is the one that best explains the
file; rejecting the leftovers outright would fail real-world CSV that a lenient
reader handles. Padding uses `""`, which is also what an absent value looks like
elsewhere (T11). Column order is preserved either way.

### Risk: 28
Most likely different reading: the author returns whatever `csv.reader` produced
for each line, leaving rows of unequal length in the response.

---

## T11. Empty cells

### Spec Text
> ```json
> "rows": [ ["<val1>", "<val2>", "..."], ["..."] ]
> ```

### Alternatives
1. An empty field is the empty string `""` (a string that remains text).
2. An empty field is JSON `null` (a missing value).

### Choice
Alternative 1. The type-handling rules describe only text and numbers; there is
no null case anywhere in the spec, and an empty CSV field is literally a
zero-length string.

### Risk: 12
Most likely different reading: the author maps blank cells to `null`.

---

## T12. Does a repeat `/convert` re-fetch the source?

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Short-circuit on a known URL: return the cached endpoint without any network
   access (so a later outage still yields 200).
2. Always fetch, validate, and refresh the stored dataset; the endpoint returned
   happens to be identical because the id is a function of the URL.

### Choice
Alternative 2. The error table is written as an unconditional property of
`/convert` ("Source unreachable ... 404"), which would be false for a
short-circuited second call, and re-fetching keeps stored rows current.

### Risk: 15
Most likely different reading: the author caches by URL and returns the stored
endpoint without re-fetching.

---

## T13. Wrong HTTP method on a known route

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` is not a route that exists, so 404.
2. The path exists and the method does not: 405, still JSON-enveloped.

### Choice
Alternative 2. The sentence constrains unknown *routes*; `/convert` is a known
route, and 405 is the accurate status. The response body is still
`{"ok": false, "error": ...}` as required, and `Allow` is set.

### Risk: 20
Most likely different reading: the author registers GET-only handlers and a
fixture asserts 404 for a non-GET request (or the framework's HTML 405 leaks).

---

## T14. Order of validation vs. fetching

### Spec Text
> | Missing `source` | 400 |
> | Invalid URL | 400 |
> | Unsupported or malformed `charset` | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Validate every parameter (including `charset`) before any network I/O, so a
   bad charset with an unreachable source gives 400.
2. Fetch first and validate the charset only when decoding, giving 404.

### Choice
Alternative 1 — the table's order, and the cheap-checks-first convention.
Requests are thus rejected as 400 whenever the caller's own input is at fault,
regardless of the remote's health.

### Risk: 15
Most likely different reading: the author decodes inside the fetch path, so a
request that is *both* bad-charset and unreachable reports 404.

---

## T15. What `query_ms` measures

### Spec Text
> `"query_ms": 3.2`
> `query_ms` is present and non-negative.

### Alternatives
1. Time spent serving this `/datasets/<id>` request (lookup + slicing).
2. Time the original conversion/ingestion took, recorded at `/convert`.

### Choice
Alternative 1, a monotonic (`perf_counter`) measurement of the dataset query,
rounded to three decimals and floored at `0.0`. It is the "Dataset Query"
response field, and Determinism carves it out as the *only* permitted timing
dependence — which only makes sense if it measures this request.

### Risk: 5
Most likely different reading: the author reports ingestion time instead; any
test can still only assert presence and non-negativity.

---

## T16. Which CORS headers, and on which responses?

### Spec Text
> Include CORS headers for browser access.

### Alternatives
1. `Access-Control-Allow-Origin: *` on success responses only.
2. The full simple-CORS set on *every* response (successes, errors, 404s,
   405s) plus an `OPTIONS` preflight handler.

### Choice
Alternative 2: `Access-Control-Allow-Origin: *`,
`Access-Control-Allow-Methods: GET, OPTIONS`, `Access-Control-Allow-Headers: *`,
`Access-Control-Max-Age: 86400`, and a 204 answer to any `OPTIONS` request.
"For browser access" implies a browser must be able to *read* failures too,
which requires the header on error responses.

### Risk: 10
Most likely different reading: the author echoes the request `Origin` instead of
`*`, or omits the headers on error responses.

---

## T17. How strictly must `_size`/`_offset` be parsed?

### Spec Text
> `_size` (positive integer, default `100`) limits returned rows.
> `_offset` (non-negative integer, default `0`) skips that many rows before returning.
> Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Lenient: `int(raw)` and a range check. That silently accepts `+5`, `" 5 "`,
   `"5\n"`, and non-ASCII digits such as `٥`, because Python's `int()` does.
2. Strict lexical form: `^[0-9]+$`, then range-check. Anything with a sign,
   surrounding whitespace, an exponent, or a decimal point is 400.

### Choice
Alternative 2. "positive integer" / "non-negative integer" reads as a statement
about the *literal* the caller sends, and a strict form makes `_size=-1` and
`_size=+1` fail for the same reason rather than by accident of `int()`'s
tolerance. Both readings agree on every obvious fixture (`abc`, `1.5`, `0`,
`-1`, empty).

### Risk: 10
Most likely different reading: the author wraps `int()` in a try/except, so
`_size=+5` and `_size=%205` (leading space) return rows instead of 400.

---

## T18. Is an empty `_size`/`_offset`/`_shape` value an error or an omission?

### Spec Text
> `_size` (positive integer, default `100`)
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. `?_size=` means "no value supplied", so fall back to the default.
2. `?_size=` is a supplied value that is not a positive integer, so 400.

### Choice
Alternative 2, uniformly for `_size`, `_offset`, `_shape`, `_rowid`, `_total`
and both sort parameters. The spec spells out "empty values ... return 400" for
sorting, and the empty string is not a positive integer, a non-negative integer,
`lists`/`objects`, or `hide`. Treating a present-but-empty parameter as absent
would need a rule the spec never states.

### Risk: 12
Most likely different reading: the author reads parameters with a
`args.get(name) or default` idiom, which quietly turns `?_size=` into the
default 100 and returns 200.

---

## T19. Ordering rules for `_sort` / `_sort_desc`

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.
> `_sort_desc=<column>` sorts descending by `<column>`.
> Sorting is stable and applied before pagination.

### Alternatives
1. Compare stored values directly with Python's `<`. A column mixing numbers and
   text raises `TypeError` -> 500.
2. Compare as text always (`str(value)`), so `100` sorts before `9`.
3. A total order keyed by type: numbers first (numerically), then text
   (lexicographically, code-point order).
4. Descending = `reversed(ascending)`, which reverses tie groups as well.

### Choice
Alternative 3 for the key, and `list.sort(reverse=True)` (not `reversed`) for
descending. Numeric columns must sort numerically or the feature is useless on
the very type the converter goes out of its way to infer; text-vs-number is
otherwise uncomparable and a 500 is not in the error table. `reverse=True` is
what keeps the descending sort *stable* as the spec requires — tie groups stay
in source order in both directions.

### Risk: 35
Most likely different reading: the author sorts descending with `reverse=True`
too (agreeing on stability) but breaks type ties the other way — text before
numbers — or uses a plain `key=lambda r: r[i]` that only ever sees homogeneous
fixture columns, leaving mixed columns unspecified in practice.

---

## T20. Sorting by `rowid`, and validating the sort parameter that loses

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.
> `rowid` is not in `columns`.

### Alternatives
1. `rowid` is sortable (it is a real per-row value, even if hidden from
   `columns`), and a losing `_sort` is ignored without validation.
2. Validity is decided against `columns` alone, and *both* parameters are
   validated even when only `_sort_desc` takes effect.

### Choice
Alternative 2. The spec defines the legal set as the columns and then says
plainly that `rowid` is not one of them, so `_sort=rowid` is an unknown column
-> 400. Validating the losing parameter follows the same principle: "`_sort_desc`
wins" resolves which ordering applies, not whether the other input was legal.

### Risk: 30
Most likely different reading: the author checks `_sort_desc` first and returns
early, so `?_sort=bogus&_sort_desc=name` sorts happily and returns 200; a
`_sort=rowid` fixture is less likely to exist either way.

---

## T21. Does `rowid` exist outside the `objects` shape?

### Spec Text
> `_shape=lists` (default): `rows` is arrays.
> `_shape=objects`: `rows` is objects and includes `rowid` ...
> `_rowid=hide` removes `rowid`.

### Alternatives
1. `rowid` is a property of the `objects` shape only. Under `lists` it appears
   nowhere, and `_rowid=hide` is merely a valid no-op.
2. `lists` rows also carry the rowid, prepended as an extra leading array
   element (so `_rowid=hide` has something to remove there too).

### Choice
Alternative 1. Only the `objects` bullet mentions `rowid`, and prepending an
unnamed extra element to every list row would silently break the documented
"each row follows source column order" contract from the dataset-query spec.
`_rowid=hide` is still validated under `lists` (a non-`hide` value is 400) but
changes nothing.

### Risk: 15
Most likely different reading: the author emits `rowid` as a leading element of
each list row as well, so `_shape=lists` rows are one element longer than
`columns`.

---

## T22. What exactly is the "source-file row number" behind `rowid`?

### Spec Text
> `rowid` (1-based source-file row number, starting at the header).

### Alternatives
1. A physical line number in the decoded source text: the header is on line 1,
   so the first data row is 2, and blank lines (which the parser drops) and
   multi-line quoted records still consume line numbers.
2. An index over the *parsed records only*: header = 1, first kept data row = 2,
   regardless of where those records sit in the file.

### Choice
Alternative 1, implemented by tracking `csv.reader.line_num` and recording the
line on which each record begins. The spec says "source-file row number", not
"record index", and the parenthetical "starting at the header" only fixes the
origin. For the ordinary file with no blank lines and no embedded newlines the
two readings are identical, which is what most fixtures will look like. `rowid`
is a property of the row, so it survives sorting and offsetting unchanged.

### Risk: 20
Most likely different reading: the author numbers parsed records
(`enumerate(rows, start=2)`), so a file containing a blank line or a quoted
embedded newline yields lower rowids than this implementation.

---

## T23. Are identical repeats of a control parameter also errors?

### Spec Text
> Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
> `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`.

### Alternatives
1. Only *conflicting* repeats are errors; `?_size=5&_size=5` is harmless.
2. Any second occurrence is an error, identical or not.

### Choice
Alternative 2 — "any repeated control parameter", with no exception for equal
values. This is also the cheaper and more predictable rule to implement
(`len(args.getlist(name)) > 1`), and it is almost certainly what the author's
own one-liner does. Non-control parameters are unaffected: repeating an unknown
parameter such as `?colour=red&colour=blue` is still a 200, since the rule is
scoped to the seven named controls.

### Risk: 8
Most likely different reading: the author compares the distinct values and lets
an identical repeat through.

---

## T24. Precedence between an unknown dataset id and invalid controls

### Spec Text
> If `<id>` is unknown, return `HTTP 404`.
> | control parameter repeated | 400 |

### Alternatives
1. Parse and validate the controls first, so `/datasets/nope?_size=0` is 400.
2. Resolve the dataset first, so an unknown id is 404 regardless of the query
   string.

### Choice
Alternative 2. The id is the addressed resource and the controls only shape a
response that a missing dataset cannot produce; 404-before-400 is also the
ordinary routing-then-validation shape of a Flask handler. Additionally, column
validation for `_sort` is impossible before the dataset is known, so at least
part of control validation must follow the lookup anyway.

### Risk: 18
Most likely different reading: the author validates the simple scalar controls
(`_size`, `_offset`, `_shape`, toggles, repeats) at the top of the handler and
only then looks the dataset up, returning 400 for an unknown id with a bad
`_size`.

---

## T25. Where does `total` sit, and does anything else change the envelope?

### Spec Text
> Responses include integer `total` for the row count before pagination.
> `_total=hide` removes `total`.

### Alternatives
1. `total` is the count of rows in the stored dataset (sorting cannot change a
   count, so "before pagination" simply excludes `_size`/`_offset`).
2. `total` reflects the number of rows actually returned when the window is
   short — i.e. it is really `len(rows)`.
3. `_total=hide` sets `total` to `null` / `0` rather than dropping the key.

### Choice
Alternative 1 with a genuinely absent key when hidden. "The row count before
pagination" is unambiguous about excluding the window, and "removes `total`"
means the key is gone, not nulled. `total` counts data rows only — the header is
not a row — and it is present in both shapes. All previously specified fields
(`ok`, `columns`, `rows`, `query_ms`) are unchanged.

### Risk: 5
Most likely different reading: the author emits `total: null` for
`_total=hide` instead of omitting the key.

---

## T26. Where does `<column>__<comparator>` split when the column contains `__`?

### Spec Text
> `GET /datasets/<id>` accepts filter params in this form:
> `<column>__<comparator>=<value>`

### Alternatives
1. Split at the **last** `__`, so a column literally named `a__b` is filterable
   as `a__b__exact=…`.
2. Split at the **first** `__`, so `a__b__exact` filters column `a` with
   comparator `b__exact` — an invalid comparator, hence 400.
3. Try every split position and accept the first that names a real column.

### Choice
Alternative 1 (`name.rsplit("__", 1)`). The comparator is a fixed, short,
underscore-free token drawn from a closed set, while the column name is
arbitrary CSV header text that may well contain `__`; splitting from the right
is the only rule that keeps every column reachable. It also makes
`name__exact__extra` a clean "invalid comparator `extra`" rather than a silent
match.

### Risk: 25
Most likely different reading: the author splits on the first `__`
(`name.split("__", 1)`), so a header containing `__` is unfilterable and yields
an invalid-comparator 400.

---

## T27. What text do `exact`/`contains` compare against?

### Spec Text
> `exact`: case-sensitive string equality.
> `contains`: case-sensitive substring.

### Alternatives
1. Compare against the **stored typed value rendered as text** (`str(value)`),
   so the JSON number `12.5` matches `score__exact=12.5`.
2. Compare against the **original raw cell text** kept alongside the typed
   value, so `score__exact=12.50` would match a cell written `12.50`.
3. Compare only string-typed cells; numeric cells never match a string
   comparator.

### Choice
Alternative 1. The dataset the server holds is the typed one (that is what
`rows` returns), and "string equality" against that value means its textual
form. `str()` round-trips every value this implementation infers
(`int` and plain decimals), so the common case — `score__exact=30` matching a
cell written `30` — works. Alternative 3 would make `exact` useless on the many
columns that happen to parse as numbers.

### Risk: 30
Most likely different reading: the author compares against the raw pre-inference
cell text, which differs on non-canonical spellings such as `12.50`, `+7` or
`007`.

---

## T28. Is `rowid` a filterable column?

### Spec Text
> Unknown filter column | 400
> Column matching is exact and case-sensitive.

### Alternatives
1. `rowid` is response metadata, not a column of the dataset, so
   `rowid__exact=2` is an unknown column (400).
2. `rowid` is filterable like a real column, mirroring its availability to
   `_sort`.

### Choice
Alternative 1. `columns` in the response never contains `rowid`, and the earlier
section describes `rowid` as an added field of the `objects` shape rather than
part of the table. "Unknown filter column" is judged against `columns`. (This
matches T20, where sorting by `rowid` was also treated as a non-column.)

### Risk: 15
Most likely different reading: the author allows `rowid` as a pseudo-column for
filtering as well as sorting.

---

## T29. Params that begin with `_` but are not known controls

### Spec Text
> Control params (names beginning with `_`) are not filters.

### Alternatives
1. Any name beginning with `_` is a control name; unrecognised ones are ignored
   silently (never filters, never errors) — even `_city__exact=Paris`.
2. Only the documented control names are exempt; other `_`-prefixed names
   containing `__` are treated as filters and validated.
3. Unknown `_`-prefixed names are a 400 (unknown control).

### Choice
Alternative 1. The spec defines the exemption by spelling ("names beginning with
`_`"), not by membership of the control list, and the pre-existing behaviour for
unrecognised query parameters is to ignore them. Nothing in the spec introduces
an "unknown control" error.

### Risk: 12
Most likely different reading: the author 400s on unrecognised `_` parameters.

---

## T30. Which filter values are "numeric" for `less`/`greater`?

### Spec Text
> `less`: numeric strict less (`float` parse on stored and filter values).
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.

### Alternatives
1. Literally `float(value)`: exponents (`1e1`), surrounding whitespace and
   `inf`/`nan` are all accepted; only a `ValueError` is a 400.
2. The stricter decimal grammar this implementation already uses for type
   inference (no exponents, no `inf`/`nan`).
3. `float(value)` but with `inf`/`nan` additionally rejected.

### Choice
Alternative 1. The spec names the mechanism — "`float` parse" — rather than a
grammar, and the natural implementation is `try: float(v) except ValueError:
400`. A `nan` filter value simply matches nothing, which is what a literal
implementation does.

### Risk: 18
Most likely different reading: the author reuses the strict inference grammar, so
`score__greater=1e1` is a 400 instead of a filter.

---

## T31. What makes a filter key a "duplicate"?

### Spec Text
> Duplicate filter keys are invalid (`HTTP 400`).

### Alternatives
1. The same full parameter **name** appears more than once
   (`city__exact=a&city__exact=b`), regardless of the values; two different
   comparators on one column are fine.
2. The same **column** appears more than once, whatever the comparator, so
   `city__exact=a&city__contains=b` is a 400.
3. Only conflicting values are duplicates; identical repeats collapse silently.

### Choice
Alternative 1. "Filter key" is the parameter key, and the spec separately says
multiple filters are ANDed — which is exactly what two comparators on one column
need in order to be useful. Identical repeats are still repeats (consistent with
T23 for control parameters).

### Risk: 12
Most likely different reading: the author allows identical repeats, or counts
any second filter on the same column as a duplicate.

---

## T32. What is a "query timeout", given no configured budget?

### Spec Text
> Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. A server-side wall-clock budget for the filter/sort/paginate phase of
   `/datasets/<id>`; exceeding it yields the documented 400 envelope.
2. A caller-supplied timeout control parameter (none is documented).
3. Dead prose inherited from a SQL-backed design; nothing to implement.

### Choice
Alternative 1, with a generous default budget (2000 ms) checked while filtering
and sorting, so no ordinary request can ever hit it. The budget is overridable
via the `DATAGATE_QUERY_TIMEOUT_MS` environment variable purely so the error
path is testable; the default behaviour is unchanged by it.

### Risk: 20
Most likely different reading: the author never triggers this path at all (no
fixture can reach it), in which case the choice is untested; second most likely,
the author accepts a `_timeout` style control parameter.

---

## T33. Which stored values are "non-numeric" for numeric comparators?

### Spec Text
> `float` parse on stored and filter values.
> Rows with non-numeric stored values are not matched for numeric comparators.

### Alternatives
1. A stored value is numeric iff `float(str(value))` succeeds — so a cell
   written `1e5` (kept as text by type inference) still compares numerically.
2. A stored value is numeric iff type inference already turned it into a JSON
   number; anything still a string is skipped.
3. Non-numeric stored values are an error rather than a silent skip.

### Choice
Alternative 1. The spec says the comparator does a `float` parse on stored
values, which only makes sense if the parse is attempted on the text; a failed
parse is the "non-numeric stored value" that is skipped. Alternative 3 is ruled
out explicitly ("are not matched"), and it would make any column with one dirty
cell unfilterable. Empty cells parse as non-numeric and are skipped.

### Risk: 22
Most likely different reading: the author checks `isinstance(value, (int,
float))` against the inferred type, so exotic spellings like `1e5` or `  7  `
are skipped rather than compared.

---

## T34. Empty filter values for the string comparators

### Spec Text
> `exact`: case-sensitive string equality.
> `contains`: case-sensitive substring.
> Control params (names beginning with `_`) are not filters.

### Alternatives
1. An empty value is an ordinary filter: `col__exact=` matches only empty cells,
   and `col__contains=` matches every row (`"" in s` is always true).
2. An empty value means "parameter omitted" and the filter is dropped, mirroring
   T18's treatment of empty control values.
3. An empty value is a 400.

### Choice
Alternative 1. Unlike the controls, a filter value is arbitrary user data with no
grammar to violate, and empty cells are real, matchable values in this
implementation (T11). Applying the comparator literally needs no special case.
(`less`/`greater` differ: an empty value fails the `float` parse, so it is the
documented non-numeric 400.)

### Risk: 15
Most likely different reading: the author skips filters with empty values, so
`name__exact=` returns every row instead of only the empty-named ones.

---

## T35. Does `/datasets/<id>/export` validate the controls it does not use?

### Spec Text
> The CSV uses source column order and applies the same filters, sort, and
> pagination as `/datasets/<id>`.
> `_shape`, `_rowid`, and `_total` do not affect CSV output.

### Alternatives
1. The export route parses the whole control set exactly as `/datasets/<id>`
   does — so `?_shape=nonsense` is still a 400 — and then simply ignores the
   three presentation flags when writing the CSV.
2. The export route reads only filters, `_sort`/`_sort_desc`, `_size`/`_offset`
   and ignores `_shape`/`_rowid`/`_total` entirely, including their grammar, so
   `?_shape=nonsense` exports successfully.

### Choice
Alternative 1. "Do not affect CSV output" is a statement about the *bytes
written*, not a licence to accept garbage. The natural implementation shares one
query-parsing function between the JSON and CSV views, which is exactly what
this implementation does (`_plan`), so an invalid control is rejected uniformly
and a valid-but-inapplicable one is silently dropped.

### Risk: 20
Most likely different reading: the author never touches the three flags on the
export path, so `?_shape=bogus&...` returns 200 CSV where this returns 400.

---

## T36. Does the exported CSV carry a header row?

### Spec Text
> The CSV uses source column order ...
> export columns follow source column order.

### Alternatives
1. Row 1 of the export is the column names, followed by the data rows.
2. Only data rows are written; "column order" constrains field order alone.

### Choice
Alternative 1. Both Determinism and the main paragraph speak of *export
columns*, which only exist as an observable artefact if the names are written;
and a CSV attachment without a header is not a useful download. The header is
always present, even when filters match nothing.

### Risk: 5
Most likely different reading: the author omits the header, making a filtered-to-
empty export a zero-byte body rather than a single header line.

---

## T37. Is the export paginated by default?

### Spec Text
> ... applies the same filters, sort, and pagination as `/datasets/<id>`.
> export rows follow filter -> sort -> paginate.

### Alternatives
1. Identical pagination, defaults included: with no `_size`, an export of a
   300-row dataset contains the first 100 rows.
2. Pagination applies only when `_size`/`_offset` are supplied; a bare export
   dumps the whole dataset, because an export is meant to be complete.

### Choice
Alternative 1. "The same ... pagination as `/datasets/<id>`" is unqualified, and
the default row limit is part of that endpoint's pagination, not an extra. A
caller who wants everything asks for `_size=<n>`, which the controls spec allows
to exceed 100.

### Risk: 15
Most likely different reading: the author treats an export as a full dump and
only paginates when asked, so a >100-row fixture exports every row.

---

## T38. How is an uploaded dataset's id derived?

### Spec Text
> Success: `{"ok": true, "endpoint": "/datasets/<id>"}`
> Re-uploading the same file bytes yields the same dataset id.

### Alternatives
1. `sha256` of the uploaded bytes, truncated the same way `/convert` truncates
   its URL hash — an id that is a pure function of the payload.
2. A hash of the payload *and* the uploaded filename, so the same table under
   two names is two datasets.
3. A hash of the payload and the `charset`, so the two decodes coexist.
4. A random/sequential id memoised in a bytes-keyed table.

### Choice
Alternative 1. The spec names exactly one input — "the same file bytes" — and
says nothing about filename or charset, so neither may participate. Using the
same digest and truncation as `/convert` keeps one id shape across the service;
uploading again simply replaces the stored rows for that id (the analogue of
T2/T12 for URLs). Upload ids and convert ids share one namespace but, being
hashes of different things, never collide in practice.

### Risk: 8
Most likely different reading: the author mixes the filename into the id, so the
same bytes uploaded as `a.csv` and `b.csv` give two endpoints.

---

## T39. Which part wins when both `file` and `attachment` are present?

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment` ...
> malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. `file` takes precedence; `attachment` is the fallback name.
2. Sending both is ambiguous and therefore a 400.
3. The last part in wire order wins.

### Choice
Alternative 1, with `file` checked first. The error clause is phrased as
"missing *both*", which frames the two names as interchangeable aliases rather
than a mutually exclusive pair — so supplying both cannot be an error, and a
fixed precedence is the only deterministic resolution. `file` is named first in
the spec, so it is named first here.

### Risk: 12
Most likely different reading: the author has no fixture for both-at-once, so
the behaviour is untested; failing that, `attachment` wins by dict ordering.

---

## T40. What separates "non-multipart" (415) from "malformed multipart" (400)?

### Spec Text
> - non-multipart request: `HTTP 415`
> - malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. The request's media type alone decides: a `Content-Type` that is not
   `multipart/*` (including a missing one, `application/json`, `text/csv`, and
   `application/x-www-form-urlencoded`) is 415; anything claiming multipart that
   then fails to parse is 400.
2. Only a body that actually parses as multipart avoids 415, so a corrupt
   multipart body is also 415.
3. Anything that is not exactly `multipart/form-data` — including
   `multipart/mixed` and a `multipart/form-data` with no `boundary` — is 415.

### Choice
Alternative 1. The two clauses partition on *what the client claimed*: declaring
a non-multipart type is a media-type dispute (415), while declaring multipart
and then sending something unparseable is a bad request (400). A
`multipart/form-data` header with no `boundary`, and a corrupt or truncated
body, are therefore both 400. To make this real the request class parses form
data non-silently, so Werkzeug's default "swallow the error and return an empty
dict" cannot disguise a broken body as a missing field.

### Risk: 28
Most likely different reading: the author checks `Content-Type ==
multipart/form-data` for the 415 gate, which sends a boundary-less
`multipart/form-data` (and any `multipart/mixed`) to 415 rather than 400.

---

## T41. Is a multipart part without a filename an acceptable upload?

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment` ...
> missing file field: `HTTP 400`

### Alternatives
1. Only a true file part (one carrying a `filename`) counts; a plain text field
   named `file` is "missing the file field" and is a 400.
2. Any part named `file`/`attachment` counts, whether or not it declares a
   filename; its bytes are the payload.

### Choice
Alternative 2, with file parts preferred over text parts of the same name. The
spec identifies the payload purely by *field name*, never by the presence of a
filename, and a filename is optional in `multipart/form-data`. Being permissive
here cannot turn a documented 400 into a 200 for any request that omits both
names — a multipart body carrying only `note`/`other` parts is still a 400.

### Risk: 10
Most likely different reading: the author reads `request.files` only, so a
filename-less `file` part is a 400.

---

## T42. How is the source format recognised?

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> Unrecognized format: `HTTP 400`.

### Alternatives
1. By content: a `PK\x03\x04` prefix means xlsx, the OLE2 compound-file
   signature means xls, and everything else is tried as text CSV.
2. By name: the URL path's or the uploaded part's extension decides, and a
   mismatch between name and content is an error.
3. By the `Content-Type` of the fetched response / multipart part.

### Choice
Alternative 1. `/upload` need not receive a filename at all and `/convert` need
not be pointed at an extension-bearing URL, so neither name nor declared type is
reliably available; magic bytes always are. The spec's `.xls`/`.xlsx` are
therefore read as naming the *formats*, not as a filename rule. A payload whose
signature is a known non-tabular binary (PDF, PNG, gzip, …), or a ZIP/OLE2
container that the workbook readers reject, is the "unrecognized format" 400;
text that decodes but is not a delimited table keeps the existing non-tabular
400.

### Risk: 18
Most likely different reading: the author dispatches on the extension, so a CSV
served from a URL ending `.xlsx` is a 400 there and a success here.

---

## T43. When is `charset` validated, now that it "validates only for text CSV"?

### Spec Text
> `charset` applies and validates only for text CSV sources.

### Alternatives
1. Validate `charset` only after the payload has been classified, so a bogus
   charset with a workbook payload is a 200 and with a CSV payload a 400.
2. Keep validating `charset` before any I/O (AMBIGUITIES T14) and merely ignore
   its *value* for spreadsheets.

### Choice
Alternative 1 for `/upload`, where the bytes are already in hand, and a hybrid
for `/convert`: the charset is still validated before the fetch — preserving
T14, under which a caller's own bad input outranks a dead remote — *unless* the
source URL's path ends in `.xls`/`.xlsx`, in which case validation is deferred
until the format is known. That keeps the earlier spec's "bad charset -> 400"
table intact for CSV URLs while honouring this spec's rule on exactly the
requests that would naturally be written to test it.

### Risk: 25
Most likely different reading: the author defers charset validation
unconditionally, so a bogus charset pointed at an unreachable or extension-less
workbook URL reports 404 / 200 where this reports 404 / 400.

### Amends T14
T14 chose "validate every parameter before any network I/O". That still holds
for `source`, and for `charset` on every source that does not announce itself as
a workbook.

---

## T44. How are spreadsheet cell values typed?

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> - Strings remain text.
> - Integers/decimals are JSON numbers.

### Alternatives
1. Stringify every cell and run it through the CSV type inference, so the
   spreadsheet path and the CSV path agree by construction.
2. Keep the workbook's own types: numeric cells become JSON numbers directly,
   text cells stay text without re-inference.
3. A hybrid: numeric cells stay numbers (with whole floats normalised to
   integers), text cells are re-inferred, and everything else is rendered as
   text.

### Choice
Alternative 3. Pure stringification (1) is lossy in an observable way: `.xls`
stores every number as a float, so `36` would arrive as `36.0` from `.xls` and
`36` from `.xlsx` for the same table. Normalising integral floats makes the two
formats agree and matches what the sheet displays. Text cells are re-inferred so
that a spreadsheet column of digit strings behaves like the same CSV column.
Blank cells become `""` (consistent with T11), dates/times become ISO-8601
strings, booleans become `"TRUE"`/`"FALSE"`, and error cells become `""`.

### Risk: 22
Most likely different reading: the author stringifies and re-infers, so `.xls`
numeric columns come back as `36.0`-style floats and spreadsheet booleans as
`True`/`False` text.

---

## T45. What is the `rowid` of a spreadsheet row?

### Spec Text
> Only the first worksheet is ingested.
> (with, from the datasets spec) `rowid` is the source-file row number.

### Alternatives
1. The worksheet's own 1-based row number, so a header on sheet row 1 gives the
   first data row `rowid` 2, and a blank row in the middle leaves a gap.
2. A gap-free sequence over the ingested data rows (2, 3, 4, …).

### Choice
Alternative 1. "Source-file row number" is a property of the source, and a
worksheet's rows are natively numbered; preserving that numbering is the only
way the id points back at anything. The two readings coincide for any sheet
without blank rows, which is the common case.

### Risk: 15
Most likely different reading: the author enumerates the surviving rows, so a
sheet with an interior blank row yields consecutive rowids rather than a gap.

---

## T46. Blank rows and columns in a worksheet

### Spec Text
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.
> spreadsheet columns preserve source order.

### Alternatives
1. Take the sheet's used range verbatim, blank rows and trailing blank columns
   included — a trailing empty column becomes a column named `""`.
2. Drop entirely blank rows and trailing entirely blank columns, then require
   two rows to remain.
3. Drop blank rows only; keep every column the used range reports.

### Choice
Alternative 2. Spreadsheet "used ranges" routinely overshoot after edits, so a
verbatim reading would give many real workbooks phantom `""` columns and blank
rows that the CSV path already discards (it skips blank records). Dropping
blanks first also makes the tabular test meaningful: a sheet holding one header
and nothing but empty rows is correctly a 400. Interior blank *columns* are
kept, because they sit between real columns and dropping them would break
"preserve source order".

### Risk: 25
Most likely different reading: the author reads the used range as-is, so a
workbook with a trailing blank column reports one extra empty-named column.

---

## T47. Is a one-column worksheet tabular?

### Spec Text
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. Yes: the stated test is purely about rows, so one column with a header and a
   data row is a valid dataset.
2. No: "tabular" implies at least two columns, mirroring the CSV path's
   delimiter detection, which needs two fields to identify a delimiter.

### Choice
Alternative 1. For a worksheet there is no delimiter to infer — the cell grid is
explicit — so the only stated requirement is the row count, and the spec spells
that requirement out in parentheses rather than leaving "tabular" to do the
work. The CSV path's stricter behaviour is an artefact of sniffing, not a rule
about tables.

### Risk: 12
Most likely different reading: the author applies one shared "at least two
columns" check to both paths, making a single-column sheet a 400.

---

## T48. How are numbers rendered into the exported CSV?

### Spec Text
> semantically-correct CSV is required; exact newline/quoting is not.

### Alternatives
1. Write each stored value with its JSON spelling: integers as digits, floats
   via Python's shortest round-trip repr, text verbatim.
2. Re-emit the original source text of each cell, so the export is a byte-level
   echo of the input.
3. Format floats to a fixed number of decimal places.

### Choice
Alternative 1. Nothing in the spec asks for the original bytes back — the export
is defined as the *dataset* rendered as CSV, and the dataset holds typed values
— and a round-trip repr is the only float rendering that loses nothing. Quoting
is left to Python's `csv` writer, which the spec explicitly declines to
constrain; values containing delimiters, quotes, or newlines therefore round-trip
through any conforming CSV reader.

### Risk: 10
Most likely different reading: the author stores and re-emits the raw cell text,
so a source cell written `1.50` exports as `1.50` where this exports `1.5`.
