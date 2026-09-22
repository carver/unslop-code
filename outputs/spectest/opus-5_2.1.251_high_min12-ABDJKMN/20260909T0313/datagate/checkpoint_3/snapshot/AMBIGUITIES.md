# AMBIGUITIES

Ambiguities found in the `datagate` spec, the interpretation chosen, and the
risk that the spec author's own implementation reads it differently.

---

## T1. How the dataset id is derived from `source`

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. Hash the raw `source` query-parameter string verbatim; any textual
   difference (trailing slash, case of host, percent-encoding, `?a=1&b=2` vs
   `?b=2&a=1`) yields a different id.
2. Normalize the URL first (lowercase scheme/host, sort query params, drop
   default ports, drop fragment) so equivalent URLs collapse to one id.
3. Derive the id from the *content* of the fetched CSV, so two URLs serving
   the same bytes share an id.

### Choice
Alternative 1: `sha256(source_string).hexdigest()[:16]`. The spec says
"the same `source` **URL string**" and "Same `source` URL always maps to the
same dataset id" — it is phrased over the string, not over a normalized URL
nor over content. Content hashing is directly excluded, since a source whose
content changes would then change its endpoint.

### Risk: 12
Most likely author reading if different: normalizing the URL (at minimum
lowercasing the host) before hashing, so `HTTP://Host/a.csv` and
`http://host/a.csv` share an id.

---

## T2. What makes a URL "invalid"

### Spec Text
> | Invalid URL | 400 |

### Alternatives
1. Only syntactically unparseable strings are invalid; any parseable URL with
   any scheme (`ftp:`, `file:`, `data:`) is accepted and then fails at fetch
   time with 404.
2. A URL is valid only if it parses *and* uses `http`/`https` *and* has a
   non-empty host. Everything else (`not a url`, `ftp://h/f.csv`,
   `file:///etc/passwd`, `http:///f.csv`) is a 400.

### Choice
Alternative 2. `source` is documented as "URL of the remote CSV file" and the
error table distinguishes "Invalid URL" (400) from "Source unreachable" (404);
a `file://` or `ftp://` URL is never reachable by an HTTP client, so treating
it as a 404 would make the 400 row nearly unreachable in practice. Restricting
to http/https also avoids local-file exfiltration through the fetcher.

### Risk: 22
Most likely author reading if different: only a bare unparseable string is a
400 and any non-http scheme falls through to the fetch path and reports 404.

---

## T3. Precedence between error conditions

### Spec Text
> | Missing `source` | 400 |
> | Invalid URL | 400 |
> | Unsupported or malformed `charset` | 400 |
> | Source unreachable or remote HTTP error | 404 |
> | Non-tabular content | 400 |

### Alternatives
1. Validate in table order: missing source, URL syntax, charset, then fetch,
   then tabularity. A bad `charset` with an unreachable URL gives 400.
2. Fetch first and only validate `charset` once bytes are in hand, so an
   unreachable source with a bad charset gives 404.

### Choice
Alternative 1 — validate everything that is knowable from the request itself
before doing any network I/O. The table is ordered with the request-level
checks first, and it avoids a network round trip for a request that can never
succeed.

### Risk: 15
Most likely author reading if different: charset is only checked at decode
time, so fetch failures win over charset failures.

---

## T4. An empty `charset` value (`?charset=`)

### Spec Text
> `charset` | no | Character encoding for decoding CSV bytes. If omitted, detect encoding from content.
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. `?charset=` (present but empty) counts as *provided* and is a malformed
   charset -> 400.
2. An empty value counts as "omitted" -> fall back to detection -> 200.

### Choice
Alternative 2. The overwhelmingly common implementation shape is
`charset = request.args.get("charset")` followed by a truthiness test
(`if charset:`), under which `""` behaves exactly like an absent parameter.
Whitespace-only values are treated the same way.

### Risk: 20
Most likely author reading if different: an explicitly supplied empty charset
is looked up, `codecs.lookup("")` raises, and the result is a 400.

---

## T5. Bytes that a *valid* charset cannot decode

### Spec Text
> If `/convert` receives `charset`, use it to decode bytes.
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. Decoding failure is a 400 — the caller named a charset that does not
   describe the bytes, i.e. the charset was wrong for this source.
2. Decode with `errors="replace"` and return 200 with replacement characters.
3. Treat it as a content problem -> "Non-tabular content" 400.

### Choice
Alternative 1 (400). A strict `bytes.decode(charset)` that raises is the
natural implementation, and both readings 1 and 3 produce 400 anyway, so the
status code is stable across the two most likely implementations.

### Risk: 8
Most likely author reading if different: lenient decoding with replacement
characters and a 200.

---

## T6. Whether a single-column file is "tabular"

### Spec Text
> | Non-tabular content | 400 |
> Delimiter must be inferred from input; minimum supported delimiters are `,`, `;`, and `\t`.
> A valid file requires at least one header row and one data row.

### Alternatives
1. A one-column file (`name\nalice\nbob`) is a legitimate CSV: it has a header
   row and a data row, so accept it with `columns == ["name"]`.
2. If no delimiter can be inferred, the input is not tabular -> 400. This also
   rejects prose ("hello world\nthis is not a csv"), which otherwise parses as
   two one-column rows and would be accepted.

### Choice
Alternative 2 — require at least two inferred columns. The spec makes
delimiter inference a hard requirement, and `csv.Sniffer.sniff()` (the obvious
building block) raises `Could not determine delimiter` on single-column input,
so a Sniffer-based implementation rejects it. It is also the only way that
plain prose — the most natural "non-tabular content" fixture besides HTML —
gets rejected.

### Risk: 28
Most likely author reading if different: a one-column CSV is accepted and only
HTML/JSON/binary bodies are non-tabular.

---

## T7. Which other bodies count as "non-tabular content"

### Spec Text
> | Non-tabular content | 400 |

### Alternatives
1. Sniff the body only: reject empty bodies, bodies starting with `<` (HTML or
   XML), bodies that parse as JSON, and bodies containing NUL bytes.
2. Trust the remote `Content-Type` header only.
3. Both signals: reject on an obviously non-CSV content type *or* on a body
   that sniffs as non-CSV.

### Choice
Alternative 3, with body sniffing as the primary signal. Real CSV endpoints
serve `text/csv`, `text/plain`, and `application/octet-stream`
interchangeably, so a content-type-only rule would reject good input; but a
fixture that returns an HTML error page or a JSON document is the canonical
"non-tabular" case and both signals agree on it. Only unmistakably non-tabular
content types (`text/html`, `application/json`, `application/xml`,
`application/pdf`, `image/*`, `audio/*`, `video/*`) trigger a rejection on the
header alone.

### Risk: 18
Most likely author reading if different: body sniffing only, ignoring the
declared content type entirely.

---

## T8. Rows whose field count differs from the header

### Spec Text
> `columns` and each row follow source column order.
> "rows": [ ["<val1>", "<val2>", "..."], ["..."] ]

### Alternatives
1. Emit rows exactly as parsed, so a short or long row has a different length
   from `columns`.
2. Normalize every row to the header width: pad short rows with `""`,
   truncate extra trailing fields.
3. Reject a ragged file as non-tabular.

### Choice
Alternative 2. The response shape is a rectangular table keyed positionally by
`columns`, and `csv.DictReader` — the other obvious parsing route — likewise
pads missing fields. Rejecting the file (3) is too aggressive for a single
stray field, and (1) produces rows that cannot be zipped against `columns`.

### Risk: 35
Most likely author reading if different: `csv.reader` output passed straight
through, leaving ragged rows ragged.

---

## T9. Leading-zero numerics such as `007` or a zip code `01234`

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.

### Alternatives
1. Any token matching an integer/decimal becomes a number, so `01234` -> 1234.
2. Preserve leading zeros as text, since the zero is significant (zip codes,
   product codes) and round-tripping to a number loses it.

### Choice
Alternative 1. The rule as written is unconditional — "Integers/decimals are
JSON numbers" — with no carve-out, and the natural implementation
(`int(s)` in a `try`) converts `01234` without hesitation. The spec author
called out only *time-like* values as a text exception; had leading zeros been
a second exception, the same bullet list would say so.

### Risk: 25
Most likely author reading if different: leading-zero tokens stay text.

---

## T10. How wide "integers/decimals" is

### Spec Text
> - Integers/decimals are JSON numbers.
> - Type inference is deterministic.
> - No dependence on clock/locale/timezone beyond `query_ms`.

### Alternatives
1. Whatever Python's `int()`/`float()` accept: includes `1_000`, `nan`, `inf`,
   Unicode digits such as `١٢٣`, and surrounding whitespace.
2. An explicit ASCII grammar: optional sign, ASCII digits, optional decimal
   part, optional exponent. `nan`/`inf`/`1_000`/Unicode digits stay text.

### Choice
Alternative 2. `nan` and `inf` are not representable in JSON, Unicode digits
are exactly the kind of locale dependence the determinism section rules out,
and `1_000` is Python syntax rather than CSV data. Exponent form (`1e5`) is
kept as a number because it is a decimal literal that `float()` and JSON both
accept. Surrounding whitespace is tolerated (` 5 ` -> `5`).

### Risk: 20
Most likely author reading if different: a bare `try: int(s) / except: try:
float(s)`, which turns `nan` into a JSON `NaN` token and accepts `1_000`.

---

## T11. Whether `/convert` re-fetches a source it has already ingested

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Cache on first success; later `/convert` calls for the same URL return the
   stored endpoint without touching the network (so a source that later goes
   down still yields 200).
2. Re-fetch and re-parse every time, refreshing the stored dataset; the id is
   still a pure function of the URL string, so the endpoint is unchanged.

### Choice
Alternative 2. The endpoint identity requirement is satisfied either way
because the id comes from the URL string alone, and `/convert` is described as
"Ingestion" — re-ingesting should pick up the current contents. It also keeps
the documented error rows live on repeat calls (a source that has since become
unreachable correctly reports 404).

### Risk: 22
Most likely author reading if different: a memoizing cache that short-circuits
the second `/convert` for the same URL.

---

## T12. Whether `/datasets/<id>` accepts a row-count parameter

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. 100 is hard-coded; there is no parameter, and any `?limit=` is ignored.
2. Calling 100 the *default* implies a `limit` parameter that can override it.

### Choice
Support an optional `?limit=` (Alternative 2), clamped to the range
`0..100` so the documented "at most 100 items" guarantee still holds, with
unparseable or negative values falling back to 100. Requests that omit the
parameter — which is what the spec actually documents — behave identically
under both readings, so this only adds behaviour where the spec is silent.

### Risk: 30
Most likely author reading if different: no parameter at all, and a
`?limit=5` request still returns 100 rows. (A third reading, where `limit`
may exceed 100, is also possible.)

### Update (resolved by the pagination spec)
The later "Pagination, Sorting, and Response Controls" section names the
parameter `_size` ("positive integer, default `100`"), so the row-count
override is now specified rather than inferred. `_size` takes precedence;
the `limit` spelling is retained only as a fallback for requests that do not
send `_size`, so nothing that the newer section pins down is affected. The
third reading noted above is also resolved: see [[T18]] — `_size` may exceed
100.

---

## T13. Wrong HTTP method on a known route

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` is a 405 Method Not Allowed with a JSON envelope.
2. Anything that is not a documented `GET` route is "unknown" -> 404.

### Choice
Alternative 1 (405, JSON body). The sentence constrains *unknown routes*;
`/convert` is a known route, and 405 is the accurate status. Both readings
agree on the JSON envelope, which is the part the spec actually pins down.

### Risk: 18
Most likely author reading if different: every non-matching request, method
mismatch included, is folded into the 404 handler.

---

## T14. What `query_ms` measures

### Spec Text
> "query_ms": 3.2
> `query_ms` is present and non-negative.

### Alternatives
1. Time spent serving the `/datasets/<id>` request (slice + serialize).
2. Time spent ingesting the source at `/convert`, stored and replayed.

### Choice
Alternative 1: a monotonic (`perf_counter`) measurement of the current query,
in milliseconds, rounded to 4 decimal places. The field lives in the dataset
*query* response and the name says "query"; using a monotonic clock keeps it
non-negative and independent of wall-clock adjustments.

### Risk: 5
Most likely author reading if different: total request time including
framework overhead — indistinguishable to any test that only asserts
presence and non-negativity.

---

## T15. Blank lines and a trailing newline in the CSV

### Spec Text
> A valid file requires at least one header row and one data row.

### Alternatives
1. Keep blank lines as empty rows, so a trailing newline adds an empty row.
2. Skip rows that are entirely empty/whitespace, both when counting rows and
   in the output.

### Choice
Alternative 2. A trailing newline is universal in CSV files and must not
produce a phantom `[""]` row; the same rule applied to interior blank lines
keeps the "at least one data row" check meaningful.

### Risk: 10
Most likely author reading if different: interior blank lines are preserved as
rows of empty strings while only the trailing newline is absorbed.

---

## T16. What "1-based source-file row number" makes `rowid` for the first data row

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number). `rowid` is not in `columns`.

### Alternatives
1. `rowid` counts *data* rows: the first data row is `1`, the second `2`, and
   the header is not counted.
2. `rowid` counts *physical lines of the file*: the header is line 1, so the
   first data row is `2`.
3. `rowid` is the row's position in the response after sorting/pagination, so
   the first returned row is always `1`.

### Choice
Alternative 1. "1-based" is the tell: it exists to say the counter starts at
`1` rather than `0`, which is only worth saying about an index over the data
rows — if the header were counted there would be no 0-based reading to rule
out. The "source-file" qualifier is doing different work: it pins `rowid` to
the row's original position, so it survives `_sort`/`_sort_desc` and `_offset`
rather than renumbering per page (which rules out Alternative 3). This also
matches the SQLite/Datasette `rowid` that the parameter names are modelled on,
where the first imported data row is `rowid` 1.

### Risk: 25
Most likely author reading if different: the header occupies row 1, so the
first data row reports `rowid` 2.

---

## T17. An empty `_size` / `_offset` value (`?_size=`)

### Spec Text
> `_size` (positive integer, default `100`) limits returned rows.
> `_offset` (non-negative integer, default `0`) skips that many rows before
> returning.
> Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. A present-but-empty value is not a positive/non-negative integer, so it is
   invalid -> 400.
2. An empty value counts as "not supplied" and the default applies -> 200.

### Choice
Alternative 1 (400), which also covers whitespace-only values. The spec's
defaults are stated for the parameter being *absent*, and the error table
keys on the value's form ("not a positive integer") rather than on presence.
`""` is not a positive integer, and the natural implementation
(`int(request.args["_size"])` inside a `try`) raises on it. This is the
opposite of the choice made for `charset` in [[T4]], because there the spec
itself says "if omitted, detect" without any accompanying validity table row
keyed to the value's form.

The same entry covers the accepted integer *grammar*: an explicit ASCII
`[+-]?[0-9]+` is required, so `5` and `+5` are accepted, `-0` is an accepted
`_offset` of `0`, and `1_0`, `５` (fullwidth digits), `1.0`, `1e2` and `0x5`
are all 400 — consistent with the deterministic ASCII-only numeric grammar
chosen in [[T10]]. Surrounding whitespace is tolerated.

### Risk: 30
Most likely author reading if different: `raw = args.get("_size")` guarded by
`if raw:`, under which `?_size=` silently falls back to the default 100.

---

## T18. Whether `_size` may exceed 100

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> `_size` (positive integer, default `100`) limits returned rows. If it exceeds
> available rows, return all.

### Alternatives
1. 100 is a hard ceiling from the earlier section; `_size=500` still returns at
   most 100 rows.
2. 100 is only the *default*; `_size=500` returns up to 500 rows, and the
   earlier "at most 100" sentence describes the default-parameter behaviour
   that the new section supersedes.

### Choice
Alternative 2. The pagination section restates 100 explicitly as the *default*
and describes the only clamp it wants — "if it exceeds available rows, return
all" — which would be a redundant thing to say if a 100-row ceiling already
made large `_size` values unobservable. A ceiling would also make `_offset`
useless past row 100 for reassembling a dataset.

### Risk: 12
Most likely author reading if different: `_size` is clamped to 100 so the
earlier guarantee holds unconditionally.

---

## T19. `_sort_desc` "wins" when the losing parameter is itself invalid

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. "Wins" is pure precedence: when `_sort_desc` is present, `_sort` is never
   looked at, so `?_sort=&_sort_desc=name` and `?_sort=nope&_sort_desc=name`
   are 200s sorted descending by `name`.
2. Both parameters are validated whenever present, and only the *ordering*
   is decided by precedence, so an empty or unknown `_sort` is a 400 even when
   a valid `_sort_desc` accompanies it.

### Choice
Alternative 1. "Wins" reads as selection, and the natural implementation is a
single `if _sort_desc is not None: ... elif _sort is not None: ...` chain that
validates only the branch it takes. The validation sentence sits under the
description of what each parameter does, i.e. it constrains the column that is
actually being sorted on.

### Risk: 35
Most likely author reading if different: each parameter is parsed and
validated independently before precedence is applied, so an invalid `_sort`
is a 400 regardless of `_sort_desc`.

---

## T20. Ordering between values of different types in one column

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.
> Sorting is stable and applied before pagination.

### Alternatives
1. Compare the stored values directly with Python's `<`, which raises
   `TypeError` on a column mixing numbers and strings (a 500).
2. Coerce everything to `str` before comparing, so `10` sorts before `9`.
3. Order by type class first — numbers before strings, numbers compared
   numerically, strings compared by Unicode code point — so a mixed column has
   a total order and a purely numeric column sorts numerically.

### Choice
Alternative 3. The type-inference section deliberately turns numeric cells
into JSON numbers, so a numeric column must sort numerically (`2 < 10`), which
rules out (2); and a 500 on a ragged real-world column (3) would contradict
the error table, which lists no server-error condition for sorting. Putting
numbers before strings mirrors SQLite's type ordering, which is what the
`_sort`/`_sort_desc`/`_shape` parameter vocabulary is borrowed from. Empty
cells stay strings and therefore sort first among the strings.

### Risk: 25
Most likely author reading if different: a plain `key=lambda r: r[i]` that
happens to work because every fixture column is type-homogeneous — which
agrees with this choice on exactly those inputs — and otherwise a `str()` key,
which differs whenever a numeric column has more than one digit width.

---

## T21. `_sort=rowid`

### Spec Text
> `_shape=objects`: ... includes `rowid` ... `rowid` is not in `columns`.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. `rowid` is a sortable pseudo-column (as it is in Datasette), so
   `?_sort=rowid` is a 200 in source order.
2. The set of known columns is exactly `columns`, and the spec goes out of its
   way to say `rowid` is not in it, so `?_sort=rowid` is an unknown column ->
   400.

### Choice
Alternative 2. The spec defines the sortable namespace as "columns" and
separately states that `rowid` is not one of them; the natural implementation
is `if column not in columns: 400`, checked against the same list the response
returns. Sorting by `rowid` is also a no-op, since source order is already the
default.

### Risk: 30
Most likely author reading if different: `rowid` is accepted as a sort key
because the implementation carries it alongside the real columns internally.

---

## T22. An unknown dataset id combined with an invalid control parameter

### Spec Text
> If `<id>` is unknown, return `HTTP 404`.
> | `_size` not a positive integer | 400 |

### Alternatives
1. Resolve the dataset first: `GET /datasets/nope?_size=0` is a 404.
2. Validate the request's own parameters first: the same request is a 400.

### Choice
Alternative 1 (404). The handler cannot validate `_sort` at all without the
dataset's column list, so the lookup has to come first for at least one of
the documented 400s; doing the lookup first uniformly keeps the ordering
consistent, and "unknown id" is the more fundamental failure — there is no
resource for the controls to apply to.

### Risk: 20
Most likely author reading if different: cheap parameter validation runs
before the store lookup, yielding 400.

---

## T23. `_rowid=hide` when the shape has no `rowid`

### Spec Text
> `_rowid=hide` removes `rowid`.
> Each toggle is valid only with value `hide`; any other value is `HTTP 400`.

### Alternatives
1. `?_shape=lists&_rowid=hide` is a 400, because `rowid` is not part of the
   `lists` shape and asking to hide it is incoherent.
2. It is a valid no-op 200: the value is `hide`, which is the only validity
   rule the spec states, and there is simply nothing to remove.

### Choice
Alternative 2. The stated rule is about the *value*, not about compatibility
with `_shape`, and the error table's row is "invalid `_rowid`/`_total` value"
— a check on the value alone. `lists` is also the default shape, so making
`_rowid=hide` conditional on `_shape=objects` would turn the most obvious
"hide the rowid" request into an error.

### Risk: 10
Most likely author reading if different: `_rowid` is rejected unless
`_shape=objects`.

---

## T24. What counts as a "repeated" control parameter

### Spec Text
> Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
> `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`.

### Alternatives
1. Only *conflicting* repeats are errors; `?_size=5&_size=5` is harmless and
   returns 200.
2. Any second occurrence is an error regardless of value, including identical
   values and including an empty second occurrence (`?_size=5&_size=`).

### Choice
Alternative 2. "Any repeated control parameter" is unconditional, and the
natural implementation is `len(request.args.getlist(name)) > 1`, which never
compares values. Only the seven listed names are checked; repeating an
undocumented parameter is ignored.

### Risk: 8
Most likely author reading if different: duplicates are de-duplicated and only
differing values are rejected.

---

## T25. Comparing `exact`/`contains` against cells that were coerced to numbers

### Spec Text
> - `exact`: case-sensitive string equality.
> - `contains`: case-sensitive substring.

### Alternatives
1. Only cells that are still Python `str` can match a string comparator; a
   numeric cell never matches `exact`/`contains`.
2. Render the stored value as text first (`str(value)`) and compare that, so
   `age__exact=30` matches the row whose `age` cell became the JSON number
   `30`.
3. Coerce the *filter* value to the cell's type instead, so `age__exact=30`
   compares `30 == 30` numerically and `age__exact=30.0` also matches.

### Choice
Alternative 2. Type inference is applied at ingest, not at query time, so
under (1) `exact` would be unusable on every numeric column — the caller has
no way to express "the cell that prints as 30". The comparator is defined as
*string* equality, which rules out (3): `30.0` and `30` are different strings
and must stay different. `str()` on the stored value is also the shortest
implementation that makes both comparators total over mixed columns.

### Risk: 22
Most likely author reading if different: filtering runs over the raw CSV text
before type inference, which agrees with this choice except where `str()` of
an inferred number differs from the source token (`007` -> `7`, `1.50` ->
`1.5`, `1e3` -> `1000.0`).

---

## T26. A column name that itself contains `__`

### Spec Text
> `<column>__<comparator>=<value>`

### Alternatives
1. Split on the *first* `__`, so `a__b__exact` filters the column `a` with the
   comparator `b__exact` (invalid -> 400).
2. Split on the *last* `__`, so `a__b__exact` filters the column `a__b` with
   the comparator `exact`.

### Choice
Alternative 2 (`rpartition("__")`). The comparator is a closed four-word
vocabulary and none of the words contain `__`, while column names come from an
arbitrary CSV header and can contain anything. Splitting from the right is the
only rule that can address every column; splitting from the left makes columns
named `a__b` permanently unfilterable while gaining nothing.

### Risk: 18
Most likely author reading if different: `key.split("__")` with a length check,
which rejects `a__b__exact` as an invalid comparator (400).

---

## T27. Which error wins for `nosuch__nosuch=1`

### Spec Text
> | Invalid comparator (`exact|contains|less|greater`) | 400 |
> | Unknown filter column | 400 |

### Alternatives
1. Validate the column first, so an unknown column reports "unknown column"
   even when the comparator is also bogus.
2. Validate the comparator first, matching the order of the error table.

### Choice
Alternative 2. The comparator is what decides whether the key is a filter at
all — without a recognised comparator there is no `<column>` to look up, since
the split point is only meaningful once the suffix is known to be a
comparator. The error table also lists invalid comparator above unknown
column. Both conditions are 400 with a free-form message, so the distinction
is only observable through the message text.

### Risk: 25
Most likely author reading if different: the column is resolved first, so the
message names the column rather than the comparator. Both are 400, so this
only matters if the hidden tests assert on message content.

---

## T28. Params with a single `_` and no `__`, e.g. `?foo_bar=1`

### Spec Text
> Control params (names beginning with `_`) are not filters.
> Params without `_` and without `__` are ignored as filters.

### Alternatives
1. Read literally: the ignore rule covers only params containing neither an
   underscore nor a double underscore, so `foo_bar=1` (which contains `_`) is
   *not* ignored and must be an error.
2. Read the sentence as the summary of the two structural rules above it: a
   param that does not *begin with* `_` (control) and does not *contain* `__`
   (filter) is neither, and is ignored. `foo_bar=1` is ignored.

### Choice
Alternative 2. Under (1) there is no error-table row that `foo_bar=1` could
map to — the table only covers bad comparators, bad columns, duplicates and
timeouts — so a literal reading has no defined behaviour to produce. Read as a
summary, the two conditions "`_`" and "`__`" are shorthand for the two
preceding rules (leading `_` = control, embedded `__` = filter), and every
other param falls through as ignored. The existing controls section already
ignores unrecognised parameters.

### Risk: 15
Most likely author reading if different: any param containing `_` in a
non-leading position is treated as a malformed filter and rejected with 400.

---

## T29. What makes a "duplicate filter key"

### Spec Text
> Duplicate filter keys are invalid (`HTTP 400`).

### Alternatives
1. The same *column* twice under any comparator: `?a__less=9&a__greater=1` is
   a duplicate and a 400.
2. The same full query-parameter *key* twice: `?a__less=9&a__less=8` is a 400,
   but two different comparators on one column are fine and are ANDed.
3. Only conflicting values count; `?a__less=9&a__less=9` is accepted.

### Choice
Alternative 2. The spec says "duplicate filter **keys**", and the key is
`<column>__<comparator>`, not the column. Reading (1) would make a bounded
range (`a__greater=1&a__less=9`) impossible to express, which directly
contradicts "multiple filters are ANDed" — a range is the canonical reason to
AND two filters. (3) is excluded by the same reasoning as the repeated
control parameters in T24: the check is `len(getlist(key)) > 1`, which never
compares values.

### Risk: 12
Most likely author reading if different: duplicates are keyed on the column
alone, so a two-sided range returns 400.

---

## T30. What counts as a "non-numeric" value for `less`/`greater`

### Spec Text
> - `less`: numeric strict less (`float` parse on stored and filter values).
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.
> Rows with non-numeric stored values are not matched for numeric comparators.

### Alternatives
1. "Numeric" means whatever Python's `float()` accepts: `nan`, `inf`,
   `1_0` and surrounding whitespace all parse, so `?a__less=nan` is a valid
   filter that happens to match nothing.
2. A strict ASCII decimal grammar (the one the type-inference section uses),
   so `nan`, `inf` and `1_0` are non-numeric filter values and return 400.

### Choice
Alternative 1. The spec names the operation explicitly — "`float` parse on
stored and filter values" — rather than referring back to the inference
grammar, and it applies the same phrase to both sides. Using one
`try: float(x)` helper for both keeps the two halves of the sentence
symmetrical: the filter side raises 400 on failure, the stored side simply
fails to match. `nan` then parses but compares false against everything, which
is the correct IEEE behaviour for a strict comparison.

### Risk: 25
Most likely author reading if different: the same ASCII decimal regex used for
type inference, making `?a__less=nan` and `?a__less=inf` a 400 instead of an
empty result set.

---

## T31. Whether `rowid` is a filterable column

### Spec Text
> Column matching is exact and case-sensitive.
> | Unknown filter column | 400 |

### Alternatives
1. `rowid` is filterable (`?rowid__greater=3`), since `_shape=objects` exposes
   it as a field.
2. `rowid` is not a column: it is not in `columns`, so `rowid__greater=3` is
   an unknown filter column and returns 400.

### Choice
Alternative 2, consistent with T21's ruling for `_sort=rowid`. The parsing
section states that `rowid` is not in `columns`, and "unknown filter column"
is naturally implemented as `column not in columns`. Treating the synthetic
`rowid` as filterable would also make it filterable under `_shape=lists`,
where it is not part of the response at all.

### Risk: 10
Most likely author reading if different: `rowid` is special-cased as a
filterable pseudo-column.

---

## T32. What "query timeout" measures and what the budget is

### Spec Text
> Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. There is a fixed wall-clock budget for the filter/sort/paginate pipeline;
   exceeding it aborts with 400.
2. The caller supplies the budget through a parameter (e.g. `_timeout`),
   which the spec never names.
3. The timeout covers the whole request including the earlier `/convert`
   fetch.

### Choice
Alternative 1: a module-level `QUERY_TIMEOUT` (seconds, default 5.0) checked
against the same `time.perf_counter()` start that `query_ms` uses, tested
while filtering, again after sorting, and once before the response is built.
(3) is impossible because `/datasets/<id>` never fetches — the data is already
in memory — and the fetch failure modes are already covered by the 404 rows.
(2) invents a control parameter the spec does not list among the controls.
The constant is read from the module namespace at call time, so a test can
lower it with `monkeypatch.setattr`.

### Risk: 55
Most likely author reading if different: the same idea but a different hook
name or unit (e.g. `QUERY_TIMEOUT_MS`, `TIMEOUT_SECONDS`, or a per-request
`_timeout` parameter). Any hidden test that forces a timeout has to reach into
the implementation to do it, and the exact name it reaches for is unguessable;
the condition is unreachable through the HTTP surface alone at any realistic
dataset size.

---

## T33. Precedence between filter errors and control-parameter errors

### Spec Text
> Control params (names beginning with `_`) are not filters.
> | Invalid comparator | 400 | ... | Duplicate filter key | 400 |

### Alternatives
1. Filters are validated before controls, so `?_size=0&bad__exact=1` reports
   the filter problem.
2. Controls are validated before filters, so the same request reports the
   `_size` problem.

### Choice
Alternative 2. Both are 400, so only the message differs. Controls come first
because the spec introduces filtering as an addition to an endpoint whose
control parameters were already specified, and because `_sort` validation
already needs the column list that filter validation also needs — keeping the
existing control block intact and appending filter parsing after it is the
smaller, more likely change. Ordering *within* the filter set follows
query-string order, with the duplicate-key scan running across all
filter-shaped keys before any single key is validated.

### Risk: 22
Most likely author reading if different: filters parsed first, since they are
the subject of the new section.

---

## T34. A param that begins with `_` and also contains `__`

### Spec Text
> Control params (names beginning with `_`) are not filters.

### Alternatives
1. `?_notacontrol__exact=x` is a filter whose column is `_notacontrol`,
   because it has the `<column>__<comparator>` shape.
2. It is a control param by the leading `_`, therefore not a filter; being an
   unrecognised control, it is ignored.

### Choice
Alternative 2. The rule is stated as an unconditional property of the name
("names beginning with `_`"), with no exception for names that also contain
`__`, and it is stated *before* the filter grammar so it takes precedence.
A CSV column literally named `_x` is consequently unfilterable, which the
spec accepts by reserving the whole `_` namespace.

### Risk: 8
Most likely author reading if different: the `__` shape is tested first, so a
leading-underscore column stays filterable.

---

## T35. An empty filter value (`?name__exact=`)

### Spec Text
> `<column>__<comparator>=<value>`
> Empty values or unknown columns return `HTTP 400`.   (`_sort`, earlier section)

### Alternatives
1. Empty filter values are a 400, by analogy with the `_sort` rule.
2. Empty is a legitimate value: `name__exact=` selects rows whose cell is the
   empty string, and `name__contains=` matches every row (empty substring).
   Only `less`/`greater` reject it, because `float("")` fails.

### Choice
Alternative 2. The `_sort` empty-value rule is about a *column name*, where
empty is meaningless; here the empty string is a real cell value that ragged
CSV rows genuinely contain, and the filtering section lists no empty-value
error row. Rejecting it would leave no way to select blank cells.

### Risk: 20
Most likely author reading if different: empty filter values are rejected with
400 for every comparator.

### Note (consequence for `?__exact=x`)
A key with an empty column name begins with `_`, so under this choice it is an
ignored control param rather than an "unknown filter column" 400. The
alternative reading makes it a 400 with an empty column name.
