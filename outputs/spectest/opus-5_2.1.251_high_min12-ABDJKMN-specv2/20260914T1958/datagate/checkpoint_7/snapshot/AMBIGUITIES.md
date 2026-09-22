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

### Resolved (Caching and Cache Controls)
The caching spec settles this against the choice above: `/convert` caches by
default, and "repeated `/convert` requests for the same source URL can return
the cached dataset id without re-downloading". Alternative 1 was right.
Alternative 2 survives only as the `CACHE_ENABLED=false` and `?force`
behaviour. The implementation now short-circuits on a cache hit, so a cached
source that later becomes unreachable still returns `200`; the unconditional
`404` in the error table applies only when an ingestion actually runs. See
T49 for what the cache is keyed by.

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

---

## T49. What is the cache keyed by?

### Spec Text
> With caching enabled, repeated `/convert` requests for the same source URL can
> return the cached dataset id without re-downloading.

### Alternatives
1. The key is the `source` URL alone, so a later request that adds or changes
   `charset` still hits the cache and never re-parses.
2. The key is the whole request (`source` + `charset`), so the same URL asked
   for with a different `charset` misses the cache and re-ingests.
3. Only the downloaded bytes are cached; every request re-parses them with its
   own `charset`, and only the network round-trip is skipped.

### Choice
Alternative 1. The spec names "the same source URL" as the thing that repeats,
and the cached thing it names is "the cached dataset id" -- which, by
T2, is already a function of the source URL alone. The minimal implementation
of that sentence is a lookup of the stored dataset by id, which is what this
implementation does: a hit returns the endpoint and touches neither the network
nor the parser. `source` and `charset` are still validated ahead of the lookup,
so a bad `charset` is a `400` even on an otherwise cacheable request.

### Risk: 30
Most likely different reading: the author keys the cache on the full parameter
set, so `?source=X&charset=cp1251` re-ingests after a bare `?source=X`.

---

## T50. Which `CACHE_ENABLED` values are "invalid"?

> **Resolved by the configuration spec.** "Boolean values are strict:
> `1/true/yes/on` or `0/false/no/off` (case-insensitive, trimmed)" settles this
> entry: the accepted spellings are exactly those eight, matching is
> case-insensitive, and surrounding whitespace is stripped before matching. The
> implementation now trims, so `" true"` and `"true "` are accepted where this
> entry previously rejected them; the empty string still fails, because after
> trimming it is not one of the eight spellings. The rest of the entry stands.

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:
> - true: `1`, `true`, `yes`, `on`
> - false: `0`, `false`, `no`, `off`
> Invalid values fail startup.

### Alternatives
1. Strict membership of the eight spellings after lower-casing only: an unset
   variable is the default (caching on), but an empty string, a padded
   `" true"`, or `y`/`t`/`2` all fail startup.
2. Lenient normalisation: strip surrounding whitespace first, and/or treat an
   empty value as "unset" and fall back to the default.

### Choice
Alternative 1, minus one carve-out: only a *missing* variable takes the default.
"Strict" is the spec's own word, and it qualifies nothing except case, so
lower-casing is the sole normalisation applied. An empty `CACHE_ENABLED=` is a
value that is not on either list, so it fails startup. Failure means the process
exits non-zero with a message naming `CACHE_ENABLED` on stderr, and never binds
its port -- an already-serving process would not have "failed startup".

### Risk: 25
Most likely different reading: the author reads the variable with
`os.environ.get("CACHE_ENABLED", "true").strip()`, which quietly accepts
`" true "` -- or treats the empty string as unset and starts with caching on.

---

## T51. Is `?force=` (present, empty value) a value?

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.
> Any `force` value is `HTTP 400`.

### Alternatives
1. The raw query string decides: `?force` is a presence flag, and `?force=`
   supplies an (empty) value, so it is a `400`.
2. The parsed parameter decides: a web framework collapses `?force` and
   `?force=` to the same empty string, so both are bare presence and only a
   non-empty value is a `400`.

### Choice
Alternative 1. "Any `force` value" reads as unrestricted, and the empty string
is a supplied value; this also matches the ruling already taken for empty
control parameters in T18, where `?_size=` is a bad value rather than an
omission. The implementation therefore inspects `request.query_string` rather
than `request.args`.

### Risk: 35
Most likely different reading: the author writes `request.args.get("force")` and
rejects only a truthy string, so `?force=` re-ingests with a `200`.

---

## T52. Is `force` given twice still "present once"?

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.

### Alternatives
1. "Present once" is exact: `?force&force` is not once, so it is a `400`,
   matching the "repeated control parameter" rule the query-controls spec
   already applies to `_size` and friends (T23).
2. "Present once" just means "present at all"; repeats are harmless and the
   flag is simply on.

### Choice
Alternative 1. The spec had no reason to write "once" if any number of
occurrences behaved alike, and every other repeated parameter in this service is
a `400`. Repetition is detected on the raw query string, alongside the
value check.

### Risk: 30
Most likely different reading: the author tests `"force" in request.args`, which
is true for any number of occurrences, so `?force&force` returns `200`.

---

## T53. Does `force=<value>` still fail when caching is disabled?

### Spec Text
> Any `force` value is `HTTP 400`.
> If caching is disabled, `force` has no additional effect.

### Alternatives
1. The `400` is a parameter-validation rule and is unconditional; "no additional
   effect" only describes the re-ingestion behaviour, which is already what
   every request does when the cache is off.
2. With caching off, `force` is inert in every respect, so `?force=1` is simply
   ignored and the request succeeds.

### Choice
Alternative 1. "Any `force` value is `HTTP 400`" sits in the per-request bypass
section with no condition attached, and validation that changes shape with an
environment variable would make the same request 400 on one deployment and 200
on another. "No additional effect" is about what forcing *does*, not about what
counts as a well-formed request.

### Risk: 20
Most likely different reading: the author short-circuits the whole `force`
branch when the cache is off, so `?force=1` returns `200`.

---

## T54. What survives a failed re-ingestion?

### Spec Text
> - Re-ingestion failures keep existing error codes and envelope.
> - Forced re-ingestion failure keeps prior dataset queryable.

### Alternatives
1. The stored dataset is only replaced after a re-ingestion fully succeeds, so a
   failure leaves both the rows and the cache entry exactly as they were -- a
   later unforced `/convert` is still a cache hit.
2. The failure invalidates the cache entry (the dataset stays queryable, but the
   next `/convert` re-downloads), or the dataset is evicted first and the
   failure leaves the id unqueryable.

### Choice
Alternative 1. "Keeps prior dataset queryable" is stated without qualification,
and the simplest way to honour it is to never touch the store until an ingestion
has produced a complete table. Nothing in the spec says a failure disturbs the
cache, so a subsequent plain `/convert` still returns the cached id without
re-downloading. Failures are likewise never cached: an ingestion that ends in an
error stores nothing, so a later request retries the source.

### Risk: 10
Most likely different reading: the author drops the cache entry on a failed
forced re-ingestion, so the next unforced `/convert` re-downloads (the dataset
stays queryable either way, so only a hit-count assertion would notice).

---

## T55. What exactly is the `DATAGATE_CONFIG` "file"?

### Spec Text
> Service configuration sources, in order of precedence:
> 1. Built-in defaults
> 2. `DATAGATE_CONFIG` file
> 3. Direct environment variables

### Alternatives
1. `DATAGATE_CONFIG` is an environment variable holding the path of a config
   file; unset means there is no file layer at all.
2. `DATAGATE_CONFIG` is a fixed filename (e.g. `./datagate.config`) that is read
   if present, and the name in the spec is the file's name, not a variable.
3. `DATAGATE_CONFIG` holds the configuration *text* itself rather than a path.

### Choice
Alternative 1. The name is spelled in the same `UPPER_SNAKE` style as the four
environment variables in the settings table, and the third precedence layer is
called "direct environment variables" -- "direct" only makes sense in contrast
to an indirect one, i.e. a variable that points at a file. An unset (or empty)
`DATAGATE_CONFIG` simply skips the file layer and is never an error; a set
variable whose file cannot be opened is the documented "read failure".

### Risk: 6
Most likely different reading: the author also reads a fixed default path when
`DATAGATE_CONFIG` is unset, so a stray `datagate.conf` in the working directory
would take effect.

---

## T56. Are unknown keys in the config file "invalid config"?

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values,
> blank/comment lines ignored.
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. Unknown keys are ignored: only the five documented settings are consumed, and
   anything else is somebody else's `KEY=VALUE` line.
2. Any key outside the settings table is invalid config and fails startup.

### Choice
Alternative 1. "Invalid config" is attached to the file's *grammar* and to the
documented value types, both of which the spec pins down; nothing says the key
space is closed. A config file is a natural place for deployment notes and for
settings a later version adds, and failing startup on an unrecognised key makes
the file impossible to share across versions. Structural problems -- a line that
is neither blank, a comment, nor `KEY=VALUE`, or an empty key -- do fail startup,
because those really are unparseable.

### Risk: 22
Most likely different reading: the author validates the key set and exits on an
unknown key, so a file containing `UNKNOWN=1` fails startup.

---

## T57. Which config-file lines are structurally invalid?

### Spec Text
> The config file is `KEY=VALUE` lines, ... blank/comment lines ignored.
> Invalid config ... at startup returns an error and exits.

### Alternatives
1. A non-blank, non-comment line without `=` is invalid and exits; `#` starts a
   comment only at the start of a (stripped) line; the first `=` separates key
   from value, so values may contain `=`; a repeated key takes its last value;
   keys and values are whitespace-trimmed.
2. Lines without `=` are silently skipped, the way blank lines are.
3. `#` also starts an inline comment anywhere on a line.

### Choice
Alternative 1. The spec names exactly two ignorable line kinds -- blank and
comment -- which implies everything else must parse as `KEY=VALUE`, and it
explicitly promises an error for invalid config. Inline `#` comments are
rejected because `#` is legal inside a value (a URL fragment, a password) and
the spec never mentions them. Splitting on the first `=` keeps `=` usable inside
values, which matters for list entries and paths.

### Risk: 18
Most likely different reading: the author skips unparseable lines instead of
exiting, so a junk line is tolerated rather than fatal.

---

## T58. Does the allowlist check really run on *every* request?

### Spec Text
> If configured, check every request before routing:
> 1. Require `Referer`. ... 4. Otherwise return `HTTP 403`.

### Alternatives
1. Literally every request: unknown paths 403 rather than 404, `/convert` with
   no `source` 403 rather than 400, and a CORS `OPTIONS` preflight 403 too.
2. Only the documented API endpoints (`/convert`, `/upload`, `/datasets/...`)
   are checked; unknown paths still 404.
3. Everything except `OPTIONS`, so browser preflights keep working.

### Choice
Alternative 1. "Check every request before routing" is about as explicit as a
spec gets: *before routing* means the check cannot know which endpoint was
addressed, so it cannot exempt one. The hook is registered ahead of the
preflight responder for the same reason. This is the reading that makes the
allowlist an actual access control rather than a per-endpoint decoration.

### Risk: 30
Most likely different reading: the author leaves the CORS preflight responder
first, so `OPTIONS` returns `204` without a `Referer` even with an allowlist
active.

---

## T59. What are the "domain-boundary rules" for suffix matching?

### Spec Text
> 3. Accept only hostnames matching any allowed suffix case-insensitively with
>    domain-boundary rules.

### Alternatives
1. `host == suffix` or `host` ends with `"." + suffix` -- the suffix must cover
   whole DNS labels, so `example.com` admits `example.com` and `a.example.com`
   but not `notexample.com` or `example.com.evil.test`.
2. Plain `str.endswith`, which would admit `notexample.com`.
3. Subdomains only: `a.example.com` matches but the bare `example.com` does not.

### Choice
Alternative 1. "Domain-boundary rules" exists precisely to rule out alternative
2's `notexample.com` hole, and a suffix that did not match itself would be a
strange thing to call a suffix -- an operator writing `example.com` plainly
means that site. A leading dot in a configured entry (`.example.com`) is
stripped, so both spellings mean the same thing, and a trailing dot on the
Referer host (`www.example.com.`, a fully qualified name) is stripped too.

### Risk: 10
Most likely different reading: the author treats a configured `.example.com` as
subdomains-only, so the bare `example.com` would be refused.

---

## T60. What counts as a usable `Referer`?

### Spec Text
> 1. Require `Referer`.
> 2. Parse hostname.
> ...
> | Missing `Referer` (allowlist active) | 403 | ... |
> | Referer not allowed | 403 | ... |

### Alternatives
1. Absent, empty, or whitespace-only `Referer` is "missing"; a present value
   with no parseable hostname (`not a url`, `/path`, `about:blank`, `http://`,
   or a bare `example.com` with no scheme) is "not allowed". Userinfo and port
   are not part of the hostname.
2. An unparseable `Referer` is a `400` malformed-request rather than a `403`.
3. A scheme-less `example.com` is parsed leniently as a hostname and allowed.

### Choice
Alternative 1. The error table offers only `403` for the two Referer rows and no
`400` anywhere in the access-control flow, and step 4 says "otherwise return
`HTTP 403`" -- *otherwise* covers every way steps 1-3 can fail. Both rows carry
the identical body shape, so the split between them changes only the message.
`urlparse(...).hostname` is what drops userinfo and port, which is the behaviour
an operator writing a domain suffix expects.

### Risk: 12
Most likely different reading: the author parses a scheme-less `example.com` as
a hostname (e.g. by prefixing `//`), so that Referer would be accepted.

---

## T61. What does "file size" measure on `/convert` and `/upload`?

### Spec Text
> Enforced for `/convert` and `/upload`:
> - file size `= limit` accepted.
> - file size `> limit` => `HTTP 400` with standard envelope.

### Alternatives
1. The number of bytes of the source itself: the fetched response body for
   `/convert`, and the bytes of the selected multipart part for `/upload`.
2. For `/upload`, the whole HTTP request body including multipart framing.
3. The decoded character count, or the row/cell count after parsing.

### Choice
Alternative 1. `MAX_SOURCE_SIZE` is typed "integer bytes" and named after the
*source*, and `/convert` has no request body at all -- so the only quantity the
two endpoints share is "how many bytes the source file is". Counting multipart
boundaries would make the same file pass or fail depending on the client's
boundary string. The limit is checked while streaming the download, so an
over-size source is refused without being buffered, and it is checked before
parsing, so an over-size workbook is a size error rather than a format error.

### Risk: 15
Most likely different reading: the author enforces the limit on `/upload` via a
request-body cap (e.g. Flask's `MAX_CONTENT_LENGTH`), which counts the multipart
envelope and so rejects a file a little *under* the limit.

---

## T62. What is the default `STORAGE_DIR`, and what is persisted?

### Spec Text
> | `STORAGE_DIR` | path | implementation-defined |
> Create `STORAGE_DIR` if missing.
> Persisted datasets must survive restart when the same directory is reused.

### Alternatives
1. A stable default path outside the working tree (`$TMPDIR/datagate-storage`),
   with every stored dataset -- converted *and* uploaded -- written to it as one
   file per dataset id, and reads falling back to the directory on a miss.
2. A path under the current working directory (`./.datagate`).
3. Only converted datasets persist; uploads stay in memory.
4. A fresh per-process temporary directory, which would make the default never
   survive a restart.

### Choice
Alternative 1. The default is explicitly "implementation-defined", so only the
*reuse* property is testable, and alternative 4 fails it: reusing the default
directory is still "the same directory". Uploads are persisted because they are
the case where persistence matters most -- an uploaded dataset has no source URL
to re-fetch, so losing the file loses the data. Writes are atomic
(temp file plus `os.replace`) and a write failure is swallowed rather than
failing the request, since the spec makes storage a durability feature, not a
precondition for answering. A dataset id is a hex digest, and only hex ids are
ever turned into a filename, so a crafted `/datasets/<id>` cannot escape the
directory.

### Risk: 20
Most likely different reading: the author defaults to a directory under the
working tree, which only matters if a fixture inspects the default location.

---

## T63. Does persistence also make the `/convert` cache survive a restart?

### Spec Text
> Persisted datasets must survive restart when the same directory is reused.
> (with, from the caching section) `/convert` returns the cached endpoint
> without re-downloading.

### Alternatives
1. The store *is* the cache: a dataset restored from disk (with its recorded
   source URL) is a cache hit, so a restarted service answers `/convert` for a
   known URL without re-downloading.
2. Persistence only makes `/datasets/<id>` answerable; the cache is
   process-local, so the first `/convert` after a restart re-downloads.

### Choice
Alternative 1. The cache and the store were never two things in this spec --
the caching section describes `/convert` returning an endpoint for an
already-converted source, and the source URL is part of what a dataset is. A
restored record keeps its `source`, and a cache hit requires that source to
match exactly, so an id restored from an upload (which has no source) never
satisfies a `/convert` lookup.

### Risk: 25
Most likely different reading: the author keeps the cache index in memory only,
so the first `/convert` after a restart re-downloads while the dataset stays
queryable throughout.

---

## T64. Does `REQUIRE_TLS=true` change anything besides the endpoint URLs?

### Spec Text
> `REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints.
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request
> host.

### Alternatives
1. It changes only the shape of the `endpoint` string the two endpoints return.
   Plain-HTTP requests keep working, and nothing is redirected or refused.
2. It also *requires* TLS: a plain-HTTP request is refused or redirected.
3. It also rewrites `source` URL validation to demand `https://` sources.

### Choice
Alternative 1. The whole section is titled "TLS-aware endpoint URLs" and both
sentences talk about what the endpoints "return"; the error table -- which is
the spec's exhaustive list of new failure modes -- has no row for a non-TLS
request. A service behind a TLS-terminating proxy sees plain HTTP on the wire
and still needs to advertise `https://` URLs, which is exactly what this
setting is for.

### Risk: 12
Most likely different reading: the author also rejects or redirects plain-HTTP
requests when `REQUIRE_TLS=true`.

---

## T65. Which host goes into the absolute `https://` URL?

### Spec Text
> ... same endpoints are absolute `https://` URLs using request host.

### Alternatives
1. The request's `Host` header verbatim, including any port
   (`https://data.example.com/datasets/<id>`,
   `https://127.0.0.1:8001/datasets/<id>`).
2. The `Host` header with any port stripped, since the URL is `https://`.
3. `X-Forwarded-Host` when present, falling back to `Host`.

### Choice
Alternative 1. "Using request host" names the host the client actually
addressed, and that is the `Host` header; dropping the port would break every
non-443 deployment, which is precisely the case a test can easily construct.
`X-Forwarded-Host` is not mentioned anywhere in the spec and is attacker-
controlled without a trusted proxy in front, so it is not consulted.

### Risk: 15
Most likely different reading: the author strips the port (or uses Flask's
`url_for(..., _external=True, _scheme="https")`, which keeps it), so a
non-default port would appear or disappear against expectation.

---

## T66. Is an empty or absent value the same as "unset"?

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> | `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |
> Boolean values are strict ...
> Invalid config ... returns an error and exits.

### Alternatives
1. Per type: an empty `ORIGIN_ALLOWLIST` (or one that is all separators) means
   no allowlist; an empty `STORAGE_DIR` means the default; but an empty
   `MAX_SOURCE_SIZE`, `REQUIRE_TLS`, or `CACHE_ENABLED` is invalid, because
   `""` is not an integer and not one of the eight boolean spellings.
2. Empty always means "unset", for every setting.
3. Empty is always invalid config, for every setting.

### Choice
Alternative 1. The two strict grammars in the spec -- "integer bytes" and the
enumerated boolean spellings -- simply have no member spelled `""`, and the
spec says invalid config exits; this also preserves the already-settled
`CACHE_ENABLED=""` behaviour. A list, by contrast, has a natural empty value,
and an empty allowlist that refused every request would be a footgun with no
support in the text ("No allowlist means all requests pass").

### Risk: 30
Most likely different reading: the author treats an empty value as unset across
the board, so `MAX_SOURCE_SIZE=` starts cleanly with no limit instead of
failing startup.

---

## T67. Which spellings does `MAX_SOURCE_SIZE` accept?

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |

### Alternatives
1. Digits only after trimming: `0`, `1024`, `  2048  `. No sign, no decimal
   point, no underscores, no `0x`, no `10KB`/`1M` unit suffixes. `0` is a real
   limit of zero bytes, not "unset".
2. Also accept human byte suffixes (`10KB`, `1M`).
3. Accept any value Python's `int()` would take, including `+5`, `-1`, `1_000`.
4. Treat `0` as "no limit".

### Choice
Alternative 1. "Integer bytes" names a unit, which is the opposite of inviting
unit suffixes, and the spec already spells out "unset limit means no max" --
so "unset" is how you say no max, and `0` has to keep its arithmetic meaning
under "`> limit` => 400". A negative byte count is not a limit any source could
satisfy, so it is rejected as invalid config rather than silently blocking
everything.

### Risk: 12
Most likely different reading: the author accepts `int(value)` directly, so a
negative or underscore-separated number starts instead of failing.

---

## T68. Is `MAX_SOURCE_SIZE` checked before or after the allowlist and parsing?

### Spec Text
> Enforced for `/convert` and `/upload` ...
> If configured, check every request before routing ...

### Alternatives
1. Allowlist first (it is "before routing", so before any endpoint runs), then
   the size limit, then format detection and parsing.
2. Size first, then allowlist.
3. Size checked only after a successful parse.

### Choice
Alternative 1. The allowlist is the only rule the spec places "before routing",
which puts it ahead of everything an endpoint does; the size limit is described
inside the endpoints' own behaviour. Putting size ahead of parsing follows from
`> limit => HTTP 400` being unconditional -- an over-size file never gets as far
as being judged non-tabular -- and an over-size source is never stored, so its
id stays unknown.

### Risk: 10
Most likely different reading: the author parses first and reports a format
error for an over-size non-tabular file.

---

## T69. Are config-file keys matched case-sensitively?

### Spec Text
> The config file is `KEY=VALUE` lines ...

### Alternatives
1. Case-sensitive: only the exact `UPPER_SNAKE` spellings in the settings table
   are recognised, matching how the environment variables are named.
2. Case-insensitive: `require_tls=true` configures `REQUIRE_TLS`.

### Choice
Alternative 1. The spec writes every key in upper case and puts the file in the
same precedence chain as environment variables, which are case-sensitive on
this platform; making one layer looser than the other would mean the same
spelling configures the service through the file but not through the
environment. Since unknown keys are ignored (T56), a lower-case key is simply
inert rather than fatal.

### Risk: 12
Most likely different reading: the author upper-cases keys on read, so
`require_tls=true` takes effect.

---

## T70. Do config values get quote-stripped?

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values ...

### Alternatives
1. No quote handling: the value is the text after the first `=`, trimmed of
   surrounding whitespace, quotes included if written.
2. Shell-style: surrounding `"` or `'` are stripped, and escapes are honoured.

### Choice
Alternative 1. The spec describes the format in a single clause and mentions
exactly one piece of structure -- commas inside a value -- with no hint of
quoting or escaping. Adding quote stripping would make a path that legitimately
contains a quote character unrepresentable, and no rule in the spec would say
so. Whitespace around `=` and around list separators is trimmed, since a domain
suffix or a boolean with a stray space is plainly a formatting artefact rather
than data (and the spec says booleans are "trimmed").

### Risk: 8
Most likely different reading: the author strips matching surrounding quotes, so
`STORAGE_DIR="/tmp/x"` names `/tmp/x` rather than a directory whose name
includes quotes.

---

## T71. Is a non-matching `enrich` value an error, or just "enrichment off"?

### Spec Text
> Only a single, exact `enrich=yes` enables enrichment.
> All other states keep enrichment off.
> Success response remains:
> ```json
> {"ok": true, "endpoint": "/datasets/<id>"}
> ```

### Alternatives
1. Every other state -- `enrich=no`, `enrich=1`, bare `enrich`, `enrich=` --
   is accepted and simply runs the ordinary non-enriched conversion.
2. Only `enrich=yes` and an absent `enrich` are accepted; any other value is a
   400, the way `force=<value>` is rejected elsewhere in the service.

### Choice
Alternative 1. The spec's own sentence is "All other states keep enrichment
off" -- it describes a behaviour (off), not a rejection, and the very next line
says the success response "remains" the standard envelope. Had the author
wanted validation they would have written an error rule, as the spec does
everywhere it means one. `force` is explicitly a presence flag with no value;
`enrich` is explicitly a valued parameter whose one meaningful value is `yes`.

### Risk: 12
Most likely different reading: the author rejects obviously-wrong spellings
such as `enrich=maybe` with a 400 while treating `enrich=no` as off.

---

## T72. What does "exact" exclude -- case, whitespace, and repeats?

### Spec Text
> Only a single, exact `enrich=yes` enables enrichment.

### Alternatives
1. Byte-exact after ordinary percent-decoding: the value must be the three
   characters `yes`. `YES`, `Yes`, `yes ` and ` yes` do not enrich, and
   `enrich=yes&enrich=yes` does not enrich either, because it is not *single*.
2. Case-insensitive and/or trimmed, matching how the service parses its
   booleans (`1/true/yes/on`, "strict, case-insensitive, and trimmed").
3. "Single" is about the value only, so a repeated `enrich=yes&enrich=yes` --
   every occurrence agreeing -- still enriches.

### Choice
Alternative 1. The spec deliberately says "single, exact" rather than reusing
the documented boolean vocabulary, and it enumerates exactly one accepted
spelling instead of a list; the word "single" has no work to do unless a
repeated parameter is one of the "other states". Percent-decoding still
applies, since that is transport encoding rather than the value itself.

### Risk: 18
Most likely different reading: the author compares the raw value case-
insensitively, so `enrich=YES` enriches.

---

## T73. What is `filetype` for a CSV dataset?

### Spec Text
> `dataset_summary` with at least `filetype`, `row_count`, `column_count`
> For enriched spreadsheet datasets, add only `dataset_summary` with
> `filetype: "excel"`.

### Alternatives
1. `"csv"` -- the label the spec uses for the format throughout.
2. A MIME type (`"text/csv"`), or the sniffed delimiter dialect.
3. The URL/filename extension, so a `.txt` source reports `"txt"`.

### Choice
Alternative 1. The spec fixes one sibling value literally (`"excel"`, not
`application/vnd.ms-excel` and not `xlsx`), so `filetype` is plainly a short
format family label from the same vocabulary; the service's own two families
are CSV text and workbooks. The label is derived from the sniffed content, not
from the filename, because content decides the format everywhere else here.

### Risk: 6
Most likely different reading: the author reports `"text/csv"`.

---

## T74. What separates the `number` type label from `integer` and `float`?

### Spec Text
> `column_details` keyed by column name with at least `type`,
> `distinct_count`, `missing_count`.
> Type labels: `text`, `number`, `integer`, `float`.

### Alternatives
1. A hierarchy of leaves: an all-whole-number column is `integer`, an
   all-fractional column is `float`, and a column mixing the two is the generic
   `number`. `text` covers everything else.
2. `number` is the only numeric label actually emitted for columns, with
   `integer`/`float` reserved for a finer per-value notion that never surfaces.
3. `integer`/`float` are the only labels emitted and `number` is dead
   vocabulary.

### Choice
Alternative 1. The spec lists four labels as the labels a conforming
implementation emits, so all four must be reachable; the only distinction the
data affords is whole versus fractional, and the only case that fits the
generic word "number" is a column containing both. This also matches the
ingestion rules already in place, where a cell becomes a JSON integer or a JSON
float.

### Risk: 35
Most likely different reading: the author emits `number` for every numeric
column and uses `integer`/`float` only when the column is uniformly one of
them -- i.e. the same rule -- but a plausible alternative is that mixed columns
degrade to `text`.

---

## T75. Does `distinct_count` count the missing value as a distinct value?

### Spec Text
> `column_details` keyed by column name with at least `type`,
> `distinct_count`, `missing_count`

### Alternatives
1. Distinct over the non-missing values only, so `missing_count` and
   `distinct_count` describe disjoint parts of the column (the data-profiling
   convention, e.g. pandas `nunique()`).
2. Distinct over every cell, so a column with at least one blank gets one extra
   distinct value (the naive `len(set(column))`).

### Choice
Alternative 1. The two statistics are introduced side by side as a description
of a column, and a profile reads much more naturally when "how many blanks" and
"how many different values" do not double-count the same cells; treating the
blank as a value would also make `distinct_count` depend on whether a column
happens to be ragged.

### Risk: 45
Most likely different reading: the author computed `len(set(values))` over the
whole column, so a column with blanks reports one more distinct value.

---

## T76. Does a blank cell make a numeric column `text`?

### Spec Text
> `column_details` keyed by column name with at least `type`, ...
> Type labels: `text`, `number`, `integer`, `float`.

### Alternatives
1. Missing cells are excluded before typing, so `30`, `41`, `` is an `integer`
   column with `missing_count: 1`.
2. Every cell participates, so one blank makes the column `text` because a
   blank is stored as an empty string.

### Choice
Alternative 1. `missing_count` exists precisely to account for the empty cells
separately; if blanks also forced the type to `text` then `type` would be
almost useless on real data and the `integer`/`float` labels would rarely
appear. A column with no non-missing cells at all has nothing to infer from and
is reported as `text`.

### Risk: 20
Most likely different reading: the author types the raw column and a single
blank demotes it to `text`.

---

## T77. What counts as "missing"?

### Spec Text
> ... `distinct_count`, `missing_count`.

### Alternatives
1. An empty cell: an empty string, a whitespace-only cell, or a cell absent
   from a short row (which ingestion already pads with `""`).
2. Only a strictly empty string, so a cell containing a space is data.
3. Empty cells plus sentinel words such as `NA`, `N/A`, `null`, `-`.

### Choice
Alternative 1. Ingestion already strips a cell before deciding whether it is a
number, so a whitespace-only cell is treated as empty everywhere else in the
service and it would be inconsistent for the profile to call it a value.
Sentinel words are a convention the spec never mentions, and guessing them
would silently rewrite legitimate text data.

### Risk: 22
Most likely different reading: the author counts only the exact empty string as
missing, so a whitespace-only cell is a value.

---

## T78. Does a spreadsheet's `dataset_summary` still carry the counts?

### Spec Text
> For enriched spreadsheet datasets, add only `dataset_summary` with
> `filetype: "excel"`.

### Alternatives
1. "only `dataset_summary`" restricts *which metadata fields* appear -- the
   summary, and not `column_details` -- while the summary keeps its documented
   shape, including `row_count` and `column_count`.
2. A spreadsheet's summary is literally the single key `filetype`.

### Choice
Alternative 1. The sentence contrasts with the CSV rule directly above, which
adds two fields; "only" is doing the work of excluding `column_details`. The
summary's required keys were stated once as a property of `dataset_summary`
itself, and row and column counts are format-independent facts that the service
already knows for a workbook. A one-key summary would also make
`dataset_summary` mean two different things.

### Risk: 25
Most likely different reading: the author emits `{"filetype": "excel"}` alone
for workbooks.

---

## T79. Does a re-ingestion *without* `enrich=yes` downgrade a stored enriched dataset?

### Spec Text
> `enrich=yes` on a cached non-enriched dataset forces re-ingestion and
> upgrades stored state.
> Requests without re-ingestion do not change stored enrichment state.
> Re-ingestion recomputes metadata from current source bytes.

### Alternatives
1. Stored enrichment state is whatever the request that last re-ingested asked
   for: a `force`d (or cache-disabled) conversion with no `enrich` re-ingests
   and leaves the dataset non-enriched.
2. Enrichment is a one-way upgrade: once stored enriched, a dataset stays
   enriched until something explicitly turns it off.

### Choice
Alternative 1. The spec singles out "requests without re-ingestion" as the ones
that leave stored state alone, which only says something if requests *with*
re-ingestion do set it; and "re-ingestion recomputes metadata from current
source bytes" describes the stored metadata as a product of the ingestion that
produced it. The only protection the spec gives an enriched dataset is against
*failures* (see the error-handling rule), not against a deliberate plain
re-conversion.

### Risk: 40
Most likely different reading: the author treats enrichment as sticky, so a
plain `force`d re-conversion keeps the dataset enriched and merely recomputes
its metadata.

---

## T80. What happens to `enrich` on the other endpoints?

### Spec Text
> `enrich` applies only on `/convert`.

### Alternatives
1. Elsewhere it is an ordinary unknown query parameter: ignored, with no
   enrichment and no error. `/upload` stores a non-enriched dataset,
   `/datasets/<id>?enrich=yes` returns the plain payload, and
   `/datasets/<id>/export?enrich=yes` exports as usual.
2. `enrich` outside `/convert` is a 400.

### Choice
Alternative 1. "Applies only on `/convert`" says where the parameter has an
effect, not that it is policed elsewhere; the service already ignores unknown
query parameters on the dataset endpoints (only `_`-prefixed controls and
`<column>__<comparator>` filters are interpreted), and inventing a rejection
would contradict that.

### Risk: 10
Most likely different reading: the author rejects `enrich` on `/upload`.

---

## T81. Where does the enrichment metadata appear?

### Spec Text
> ### Enriched query output
> For enriched CSV datasets, add: ...
> `rows`, `columns`, `ok`, `query_ms`, and `total` do not change.

### Alternatives
1. In the JSON body of `GET /datasets/<id>` only -- the response whose other
   keys are `rows`, `columns`, `ok`, `query_ms`, `total`.
2. Also in the `/convert` response.
3. Also somehow in the CSV export.

### Choice
Alternative 1. The heading is "Enriched query output" and the untouched keys
the spec lists are exactly the dataset-query envelope, so that is the response
being described. The `/convert` envelope is separately and explicitly said to
remain `{"ok": true, "endpoint": ...}`, and a CSV export is a flat table with
nowhere to put a nested object.

### Risk: 5

---

## T82. What do `row_count` and `column_count` count?

### Spec Text
> `dataset_summary` with at least `filetype`, `row_count`, `column_count`

### Alternatives
1. The dataset as stored: data rows excluding the header, and the number of
   columns in the header. Both are properties of the whole dataset, independent
   of any filter, sort, or pagination on the query that returns them.
2. The header row counts as a row.
3. The counts describe the current query result (the filtered/paginated window),
   making them a duplicate of `total` and the page length.

### Choice
Alternative 1. `dataset_summary` is named for the *dataset*, and it is stored
at ingestion time ("re-ingestion recomputes metadata"), which cannot depend on
a later query's parameters. The service's own vocabulary already treats the
header as `columns` and never as a row.

### Risk: 12
Most likely different reading: the author recomputes the counts per query, so a
filtered request reports the filtered row count.

---

## T83. What is an "enrichment failure", and what must not be downgraded?

### Spec Text
> Enrichment failures return standard JSON errors and must not downgrade to
> non-enriched storage.

### Alternatives
1. If anything in an enriched conversion fails -- the fetch, the parse, or the
   metadata computation -- the request answers with the standard
   `{"ok": false, "error": "..."}` envelope and nothing is stored, so a
   previously enriched dataset stays enriched and queryable with its old
   metadata.
2. Only the metadata computation counts, and a failure there should still store
   the parsed rows without metadata (explicitly what the spec forbids).
3. A failure should delete the stored dataset.

### Choice
Alternative 1. The sentence forbids exactly one fallback -- silently storing
the non-enriched result -- so the failure has to be surfaced instead; the
service already replaces a stored dataset only after an ingestion fully
succeeds, which makes "must not downgrade" a property of leaving the prior
record untouched. Deleting the dataset would be a second, unmentioned side
effect.

### Risk: 8

---

## T84. Does `enrich=yes` on an already-enriched cached dataset refetch?

### Spec Text
> `enrich=yes` on a cached enriched dataset may use cache.

### Alternatives
1. It behaves like any other cache hit: no fetch, the stored metadata is
   returned unchanged. `force` is still the documented way to refetch.
2. "may" is permission to refetch, and the author's implementation always
   re-ingests when `enrich=yes` is given.

### Choice
Alternative 1. "May use cache" grants the cache hit, and the caching section
elsewhere makes a cache hit indistinguishable from a fresh parse; re-ingesting
anyway would make `enrich=yes` an undocumented second spelling of `force`.
Because the spec only permits rather than requires this, the tests here assert
the observable outcome (still enriched, same endpoint) rather than the absence
of an origin fetch.

### Risk: 5

---

## T85. What happens to `column_details` when two columns share a name?

### Spec Text
> `column_details` keyed by column name with at least `type`,
> `distinct_count`, `missing_count`

### Alternatives
1. A JSON object keyed by name, so duplicate headers collapse into one entry --
   the last column with that name wins.
2. The first column with that name wins.
3. Keys are disambiguated (`name`, `name_2`), or the value becomes a list.

### Choice
Alternative 1. The spec says "keyed by column name", which fixes the key and
therefore the collision; building the object in column order makes the later
column the surviving one, exactly as a plain dict assignment does. Inventing
suffixes would produce keys that are not column names, contradicting the rule.
`columns` and `rows` still carry every duplicate column, so nothing is lost
from the dataset itself.

### Risk: 15
Most likely different reading: the author builds the object first-wins, or
never tests duplicate headers at all.
