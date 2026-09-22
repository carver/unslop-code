# Ambiguities

Numbered record of spec passages that admit more than one conforming
implementation, the reading chosen for `datagate`, and the risk that the spec
author's own implementation reads them differently.

## T1. Derivation of `<id>`

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. A content-addressed hash of the exact `source` string (sha256, md5, ...),
   truncated to some length.
2. An incrementing counter kept alongside a `source -> id` map, so ids are
   `1`, `2`, ... but still stable per source.
3. A hash of the *normalised* URL, so `http://h/a.csv` and `http://h/a.csv?`
   or a differing-case host collapse onto one id.

### Choice
`sha256(source_bytes).hexdigest()[:16]` over the raw query-parameter string, no
normalisation. The spec says "the same `source` URL *string*", which points at
the literal string as the key, and a pure hash needs no shared state, so the id
is stable across restarts and across processes. Requests that differ only in URL
spelling therefore get different ids, which the literal reading demands.

### Risk: 8
The author most likely asserts only that two `/convert` calls agree with each
other (and that the id is a path-safe token), not a specific digest, so any
deterministic function passes. Residual risk is a fixture asserting a literal
id string, or asserting that two spellings of the same URL share an id.

### Annotation (Export, Upload, and Multi-Format Support)
Still open for `/convert`. That spec adds a *second* identity basis - uploaded
file bytes - without saying whether the two share a keyspace; see [T34].

### Annotation (Configuration, Size Limits, and Access Control)
Reinforced. Datasets now persist across restarts, so a purely content-addressed
id is what lets a restarted process find the file a previous one wrote; an
incrementing counter (alternative 2) would have to persist its map as well.

## T2. When the source is fetched

### Spec Text
> | Source unreachable or remote HTTP error | 404 |
> | Non-tabular content | 400 |
> The endpoint returns stored rows and columns, in source order.

### Alternatives
1. `/convert` fetches, parses and stores eagerly; `/datasets/<id>` only reads
   what was stored.
2. `/convert` records the URL and defers fetching to the first dataset query.

### Choice
Eager. `/convert` is the endpoint that must report unreachable sources (404) and
non-tabular content (400), which is only possible if it has already fetched and
parsed; and `/datasets/<id>` is described as returning "stored" rows.

### Risk: 3
Both the error table and the word "stored" force this reading.

## T3. What counts as an integer or a decimal

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Naive coercion: try `int(cell)`, then `float(cell)`, else text. This accepts
   `007` -> `7`, `1e5` -> `100000.0`, ` 42 ` -> `42`, and also `nan`/`inf`,
   which are not representable in strict JSON.
2. Strict, JSON-number-shaped matching: reject leading zeros (so a zip code
   `01234` and an id `007` stay text), reject `nan`/`inf`.
3. Locale-ish coercion that also strips thousands separators or currency
   (`1,234`, `$5.00`) into numbers.

### Choice
Alternative 1, minus the non-finite literals: a signed digit string becomes an
`int`, a signed decimal/scientific literal becomes a `float`, detection runs on
the whitespace-stripped cell, and `nan`/`inf`/`infinity` stay text because they
cannot be emitted as valid JSON. Leading zeros are therefore converted
(`007` -> `7`). This matches what both the stdlib (`int()`/`float()`) and pandas
do, which is what an implementation is most likely built on; alternative 3 is
excluded because `1,234` collides with the comma delimiter and no separator
convention is specified.

### Risk: 22
Most likely divergence: the author preserves leading-zero cells such as `007`
or `01234` as text (or, less likely, emits `NaN` for a literal `nan`).

## T4. Empty cells

### Spec Text
> "rows": [ ["<val1>", "<val2>", "..."], ["..."] ]
> - Strings remain text.

### Alternatives
1. An empty field stays the empty string `""`.
2. An empty field becomes JSON `null` (the pandas/`NaN` route).

### Choice
`""`. The spec's only categories are text, numbers, and time-like text; it never
mentions a null/missing value, and an empty CSV field is literally a zero-length
string, so keeping it as text adds no concept the spec does not have.

### Risk: 25
Most likely divergence: an implementation built on pandas turns blanks into
`NaN` and serialises them as `null`.

## T5. Time-like values

### Spec Text
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. The rule is a no-op safeguard: values containing `:` never parse as numbers
   anyway, so plain numeric inference already keeps them as text.
2. The rule implies an explicit time detector that also normalises or
   specially tags such values.
3. The rule extends to anything date/time-like (`2024-01-01`, `Jan 3`), which
   must be blocked from a date parser.

### Choice
Alternative 1, extended defensively to dates: no date/time parsing happens at
all, so `08:30`, `9:15`, `12:00`, `2024-01-01` and every other non-numeric cell
stay exactly as they appear in the source. The spec asks only that these values
"remain text", and any normalisation would contradict "remain".

### Risk: 4
The requested observable behaviour (text in, identical text out) is the same
under every reading; only an implementation that reformats times would differ,
and the spec's wording forbids that.

## T6. Meaning of "unsupported or malformed charset", and an empty `charset=`

### Spec Text
> | Unsupported or malformed `charset` | 400 |
> `charset` | no | Character encoding for decoding CSV bytes. If omitted, detect
> encoding from content.

### Alternatives
1. Only the *name* is validated (`utf-99` -> 400); a valid codec that fails on
   the actual bytes is handled some other way (replacement characters, or 400
   as "non-tabular").
2. Both an unknown codec name and a decode failure under a known codec are 400,
   the first being "unsupported" and the second "malformed" for this content.
3. `charset=` (present but empty) is itself malformed -> 400, versus being
   treated as if omitted -> detect.

### Choice
Unknown codec name -> 400, and a strict decode failure under a known codec ->
400 as well (2); the charset name is validated *before* the source is fetched,
so a bad charset beats an unreachable source. An empty `charset=` is treated as
omitted and triggers detection, since the natural implementation reads the
parameter and branches on truthiness.

### Risk: 30
Most likely divergence: the author decodes with `errors="replace"` (or
`errors="ignore"`) so a mismatched-but-known codec yields a 200 with mangled
text instead of a 400.

## T7. What makes a URL "invalid"

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Syntactic only: anything `urlparse` survives is valid, so `ftp://h/f.csv`
   and `file:///etc/passwd` are "valid" and fail later as unreachable (404).
2. Scheme-restricted: only `http`/`https` with a non-empty host are valid; a
   missing scheme (`example.com/a.csv`), an unknown scheme, or a hostless URL
   is a 400.

### Choice
Alternative 2. `/convert` fetches over HTTP, so a URL it structurally cannot
fetch is invalid input (400) rather than an unreachable remote (404); this also
keeps `file://` from turning the service into a local-file reader.

### Risk: 18
Most likely divergence: the author accepts any parseable URL and lets the HTTP
client fail, returning 404 for `ftp://...` or a bare `example.com/a.csv`.

## T8. What makes content "non-tabular"

### Spec Text
> | Non-tabular content | 400 |
> - Delimiter must be inferred from input; minimum supported delimiters are
>   `,`, `;`, and `\t`.
> - A valid file requires at least one header row and one data row.

### Alternatives
1. Structural: content is tabular only if a delimiter can be inferred (i.e. at
   least two columns) and there are >= 2 non-empty rows. A single-column file,
   prose, HTML or JSON all fail.
2. Lenient: a single-column file is a one-column table, so prose with two lines
   converts successfully, and only a header-only file is rejected.
3. Content-type driven: reject unless the remote sends `text/csv` or similar.

### Choice
Alternative 1, plus an early rejection of documents whose first non-space
character is `<`, `{` or `[` (HTML/XML/JSON), which otherwise might sniff as
delimited if they happen to contain commas. Content-type is deliberately
ignored, because CSV is commonly served as `text/plain` or
`application/octet-stream` and the spec never mentions headers. Under the
lenient reading a plain prose file would convert successfully, which would leave
the "non-tabular" row of the error table unreachable.

### Risk: 25
Most likely divergence: the author accepts single-column files as tabular (and
detects non-tabular content only via a failed delimiter sniff on a fixture such
as an HTML page).

### Annotation (Export, Upload, and Multi-Format Support)
Still open for CSV. That spec states the tabular test for a worksheet as
"header + at least one data row" with no column-count clause, which is evidence
for the lenient reading - but it is stated only of spreadsheets, where a single
column is not evidence of a failed delimiter sniff, so the CSV rule above is
unchanged. The spreadsheet side is recorded separately in [T44].

## T9. Repeated `/convert` for a source already stored

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Always re-fetch and overwrite the stored table; the id is what is stable.
2. Return the cached endpoint immediately without re-fetching.

### Choice
Re-fetch (1). The spec pins the *endpoint*, not the payload, and a gateway that
never refreshes would serve permanently stale data; a failing re-fetch reports
the usual 404/400 error rather than silently serving the old table.

### Risk: 20
Most likely divergence: the author short-circuits on a cache hit, so a second
`/convert` for a source that has since gone offline still returns 200.

## T10. Ragged rows

### Spec Text
> `columns` and each row follow source column order.

### Alternatives
1. Pad short rows with `""` and truncate over-long rows to the header width, so
   every row lines up with `columns`.
2. Emit rows exactly as parsed, with varying lengths.
3. Reject the file as non-tabular.

### Choice
Rectangular output (1). `columns` is the row schema, so aligning rows to it is
what makes positional access meaningful; rejection is too harsh given the spec
lists only header/data-row presence as a validity condition.

### Risk: 30
Most likely divergence: a `csv`-module implementation stores rows verbatim and
returns them ragged (or a pandas one pads with `null`; see T4).

## T11. Row limit as a parameter

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> - Default row limit is 100.

### Alternatives
1. 100 is fixed and any `limit` parameter is ignored.
2. "Default" implies an overridable `limit` query parameter on
   `/datasets/<id>`.

### Choice
Support an optional `?limit=` (positive integer, invalid values -> 400) that
defaults to 100. The word "default" only makes sense against something that can
override it, and a client that never passes `limit` is unaffected either way.

### Risk: 12
Most likely divergence: the author hard-codes 100 and ignores `limit`; that only
shows up if a hidden test passes `limit` and expects exactly 100 rows back.

### Resolved by the pagination spec
The later spec names the override `_size` ("positive integer, default `100`"),
which confirms the overridable reading and supplies the real spelling. `_size`
is now the documented parameter; `limit` is kept as a deprecated alias with the
same validation so earlier clients keep working, and `_size` wins when both are
given. `limit` is not a control parameter, so the repeat rule does not cover it.

## T12. Delimiter inference among candidates

### Spec Text
> Delimiter must be inferred from input; minimum supported delimiters are `,`,
> `;`, and `\t`.

### Alternatives
1. `csv.Sniffer().sniff(sample, delimiters=",;\t")`.
2. Custom scoring: for each candidate, parse the whole document and prefer the
   delimiter yielding the most row-to-row consistent field count, breaking ties
   by column count then by candidate order.
3. Also accept further delimiters such as `|`, since the three are only a
   *minimum*.

### Choice
Custom scoring (2) over exactly `,`, `;`, `\t`, tie-broken in that order.
`csv.Sniffer` is heuristic and can pick a character inside quoted text;
consistency scoring is deterministic, which the spec demands. Extra delimiters
are not accepted: `|`-separated input has no comma/semicolon/tab structure and
so is reported as non-tabular.

### Risk: 20
Most likely divergence: the author accepts `|` (or whatever `csv.Sniffer`
returns) and answers 200 for a pipe-separated fixture where this returns 400.

## T13. Wrong HTTP method on a known route

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` is a method error -> 405, JSON body.
2. Only GET routes exist, so anything else is an unknown route -> 404.

### Choice
405 with the JSON error envelope. The route itself is known, so 404 ("unknown
route") would be inaccurate; the spec's binding requirement is that the body is
JSON rather than Flask's HTML error page.

### Risk: 20
Most likely divergence: the author maps every non-200 outcome outside the tables
to 404, or leaves the default HTML 405 in place untested.

## T14. Scope of the CORS headers

### Spec Text
> Include CORS headers for browser access.

### Alternatives
1. `Access-Control-Allow-Origin: *` on every response, plus preflight support.
2. Echo the request `Origin` and allow credentials.

### Choice
Wildcard origin on every response, success and error alike, with `OPTIONS`
preflight answered for the allowed methods/headers. No credentials are involved
in a read-only public gateway, and `*` is what "for browser access" needs.

### Risk: 8
Most likely divergence: a test asserting the header only on success responses
would still pass; a test expecting an echoed `Origin` would not.

## T15. Precision and meaning of `query_ms`

### Spec Text
> "query_ms": 3.2
> - `query_ms` is present and non-negative.

### Alternatives
1. Wall-clock milliseconds spent serving that dataset query, rounded.
2. Milliseconds spent on the original conversion, stored and replayed.

### Choice
Time spent serving the query itself, measured with a monotonic clock and rounded
to 3 decimals, so it is a non-negative float (possibly `0.0` for a tiny table).

### Risk: 5
The field name and the "no dependence on clock ... beyond `query_ms`" clause
both point at per-query timing; only its precision is unconstrained.

## T16. Where `rowid` numbering starts

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number).

### Alternatives
1. `rowid` counts data rows: the first data row is `1`, so it is the row's index
   in the stored table plus one.
2. `rowid` counts *file lines*: the header occupies line 1, so the first data
   row is `2`.
3. `rowid` is the position within the returned page, so it restarts at `1` on
   every request and changes under sorting.

### Choice
Alternative 1: `enumerate(table.rows, start=1)`, assigned before sorting and
carried with the row, so a paginated or sorted response shows the original
numbers (e.g. `_offset=5` starts at `rowid` 6, and a descending sort lists the
last row's `rowid` first). "1-based" reads most naturally as "the first row of
data is 1" - under alternative 2 the first value would be 2, which is an odd
thing to call 1-based - and "source-file row number" rules out alternative 3 by
tying the number to the source position rather than the response position.

### Risk: 30
Most likely divergence: the author counts the header line, so the first data row
carries `rowid` 2.

## T17. Ordering a column that mixes numbers and text

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.

### Alternatives
1. SQL-like ordering: numbers sort as numbers and before all text, text sorts
   lexicographically after them (SQLite's `NULL < number < text` rule, minus
   nulls).
2. Compare everything as strings, so `10` precedes `2`.
3. Compare the inferred Python values directly, which raises `TypeError` on a
   mixed column and would have to become a 500.

### Choice
Alternative 1, with empty cells ordering as the empty string, i.e. first among
the text values. Numeric columns must compare numerically (alternative 2 would
make `_sort` useless on the numbers the converter goes out of its way to infer),
and alternative 3 cannot be the behaviour of a working implementation. Ordering
numbers before text follows SQLite, which is what a Datasette-shaped gateway
would inherit.

### Risk: 35
Most likely divergence: the author sorts with a string key (`str(value)`), or
places text before numbers; both show up on any fixture whose sort column mixes
types or holds blanks.

## T18. Unknown column in the losing sort parameter

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. Validate every sort parameter that is present, so
   `?_sort=bogus&_sort_desc=name` is a 400.
2. Resolve the winner first and validate only it, so the same request sorts
   descending by `name` and returns 200.

### Choice
Alternative 1. The validation sentence is unconditional - it is about the
parameter values the client sent, not about the one that ends up being used -
and reporting a typo'd column name beats silently ignoring it.

### Risk: 30
Most likely divergence: the author writes
`column = args.get("_sort_desc") or args.get("_sort")` and validates only that,
returning 200 for a request where the losing parameter names a bad column.

## T19. `rowid` under the `lists` shape

### Spec Text
> `_shape=lists` (default): `rows` is arrays.
> `_rowid=hide` removes `rowid`.

### Alternatives
1. `rowid` exists only in the `objects` shape; with `lists`, `_rowid=hide` is
   accepted and does nothing.
2. `lists` rows also carry the rowid as a leading array element, which
   `_rowid=hide` strips.
3. `_rowid` is meaningful only with `_shape=objects`, so sending it with `lists`
   is a 400.

### Choice
Alternative 1. Only the `objects` bullet mentions `rowid`, and a leading rowid
element would contradict "`rowid` is not in `columns`" by making rows wider than
the column list. The toggle stays valid (and inert) with `lists`, because the
spec makes its validity depend on the *value*, not on the shape.

### Risk: 12
Most likely divergence: a fixture that expects `lists` rows to be prefixed with
the rowid, or a 400 for `_shape=lists&_rowid=hide`.

## T20. Accepted spellings for `_size` and `_offset`

### Spec Text
> `_size` (positive integer, default `100`)
> `_offset` (non-negative integer, default `0`)
> Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Strict digits: the value must match `[0-9]+` and satisfy the bound, so `+5`,
   ` 5 `, `5.0`, `1e2` and `0x10` are all 400.
2. Permissive `int(value)`, which additionally accepts `+5`, `-0`, surrounding
   whitespace and underscores (`1_0`).
3. Permissive `float`-then-truncate, which also accepts `5.0` and `1e2`.

### Choice
Strict digits (1), the same rule the pre-existing `limit` parameter already
used. A control parameter is either the integer the spec describes or it is
invalid; accepting `5.9` and silently flooring it invents behaviour the spec
never mentions. An empty value is likewise a 400, since it is not an integer.

### Risk: 25
Most likely divergence: the author uses a `try: int(value)` guard, so `+5` and
`" 5"` return 200 where this returns 400. (`-1`, `0` for `_size`, `abc` and `""`
are 400 either way, which is what a fixture is most likely to test.)

## T21. Sorting by `rowid`

### Spec Text
> `rowid` is not in `columns`.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. `_sort=rowid` is a 400: the sortable names are exactly the table's columns,
   and the spec says `rowid` is not one of them.
2. `rowid` is sortable as a pseudo-column (Datasette allows it), even though it
   is not listed in `columns`.

### Choice
Alternative 1. The only vocabulary of column names the response publishes is
`columns`, and the spec explicitly places `rowid` outside it; sorting by it is
also a no-op for ascending order, since `rowid` order *is* source order.

### Risk: 20
Most likely divergence: the author validates against the columns plus `rowid`
(or builds rows as dicts including `rowid` and checks membership in those keys),
so `?_shape=objects&_sort_desc=rowid` reverses the table instead of failing.

## T22. `_offset` past the end of the table

### Spec Text
> `_offset` (non-negative integer, default `0`) skips that many rows before
> returning.
> If it exceeds available rows, return all.

### Alternatives
1. An offset beyond the row count is a successful empty page: `rows: []`, with
   `total` still reporting every row.
2. It is a client error (400) or a 404, because the page does not exist.

### Choice
Alternative 1. The error table lists only "not a non-negative integer" as the
`_offset` failure, so a well-formed offset cannot fail; slicing past the end
yielding nothing is also what the "if it exceeds available rows" leniency shown
for `_size` implies for the pair.

### Risk: 8
Most likely divergence: none plausible; only an implementation that clamps the
offset to the last page would differ.

## T23. Case sensitivity of control values

### Spec Text
> `_shape=lists` (default) ... `_shape=objects`
> Each toggle is valid only with value `hide`; any other value is `HTTP 400`.

### Alternatives
1. Values are compared exactly, so `_shape=Objects` and `_rowid=HIDE` are 400.
2. Values are lower-cased (and/or trimmed) before comparison.

### Choice
Exact comparison. The spec quotes the literal tokens and calls anything else an
error; "any other value is `HTTP 400`" is about as explicit as a whitelist gets.

### Risk: 12
Most likely divergence: the author writes `value.lower()` out of habit, making
`_shape=LISTS` a 200.

## T24. Scope of the `total` field

### Spec Text
> `GET /datasets/<id>` accepts control parameters ...
> Responses include integer `total` for the row count before pagination.

### Alternatives
1. `total` belongs to dataset responses only; `/convert` keeps returning
   `{"ok": true, "endpoint": ...}`.
2. Every successful response, `/convert` included, grows a `total`.

### Choice
Alternative 1. The sentence sits under a heading that scopes the whole document
to `GET /datasets/<id>`, and "before pagination" is meaningless for `/convert`,
which returns no rows.

### Risk: 6
Most likely divergence: none plausible; a `/convert` fixture asserting an exact
key set would agree with this reading.

### Refined by the filtering spec
"`total` counts filtered rows before pagination" narrows the count from every
stored row to every row that survives filtering. The scope chosen here is
unchanged: `total` stays a dataset-response field, and `/convert` still returns
only `ok` and `endpoint`.

## T25. Comparing type-inferred stored values as text

### Spec Text
> - `exact`: case-sensitive string equality.
> - `contains`: case-sensitive substring.

### Alternatives
1. Compare `str(stored)` against the filter value, so the integer cell `36`
   matches `age__exact=36` and the float cell `3.5` matches `price__exact=3.5`.
2. Restrict `exact`/`contains` to cells that are still strings, so numeric
   columns never match a text comparator.
3. Coerce both sides to numbers when both parse, making `age__exact=36.0` match
   the stored `36`.

### Choice
Alternative 1. Type inference is an internal storage decision made at convert
time; a client writing `age__exact=36` is quoting the text it saw in the source
file, and the spec calls these comparators "string" comparators without carving
out numeric columns. Round-tripping through `str()` reproduces every integer
cell exactly, and decimals in their canonical Python spelling.

### Risk: 20
Most likely divergence: the author keeps the source text alongside the parsed
value, so a cell written `1e3` (stored `1000.0`, rendered `"1000.0"` here)
matches `n__exact=1e3` there.

## T26. Splitting `<column>__<comparator>` when the column name contains `__`

### Spec Text
> `<column>__<comparator>=<value>`

### Alternatives
1. Split at the *last* `__`: the comparator is the suffix, so a column literally
   named `a__b` is filterable as `a__b__exact=x`.
2. Split at the *first* `__`, making `a__b__exact` a filter on column `a` with
   the comparator `b__exact`, which is then an invalid comparator (400).

### Choice
Alternative 1. The comparator vocabulary is a closed set of four names with no
`__` in them, so the last separator is the only one that can introduce it;
splitting there is also the only reading under which a column whose own name
contains `__` remains reachable.

### Risk: 15
Most likely divergence: the author writes `key.split("__", 1)`. Both readings
return 400 for every key whose column name has no `__`, so this only shows up in
a fixture with a `__` column name.

## T27. What triggers the query timeout

### Spec Text
> - Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. An internal wall-clock budget for the whole dataset query, checked while rows
   are scanned, with no client-facing knob.
2. A client-supplied limit (`_timeout`, Datasette's `_timelimit`) that sets the
   budget per request.
3. No timeout at all beyond the fetch timeout that `/convert` already has.

### Choice
Alternative 1. The spec lists the timeout under dataset *query* errors, next to
filtering costs, and it introduces no parameter for it anywhere - so the budget
belongs to the server, not to the query string. `datagate_core/timing.py` holds
the budget as a module constant so a test can shorten it.

### Risk: 35
Most likely divergence: the author accepts a per-request `_timeout` (or
`_timelimit`) parameter, so `?_timeout=0` is a 400 there and an ignored unknown
control here (T28).

## T28. Control parameters that name no known control

### Spec Text
> Control params (names beginning with `_`) are not filters.

### Alternatives
1. Any `_`-prefixed name is excluded from filtering and otherwise ignored, so
   `?_bogus=1` and `?_size__exact=3` are successful no-ops.
2. An unrecognised `_`-prefixed name is a client error, on the grounds that the
   client clearly meant a control and misspelled it.

### Choice
Alternative 1. The sentence's only job is to keep `_`-names out of the filter
namespace, and the error table lists no "unknown control" row - while it does
list "unknown filter column", showing the author enumerates the failures they
want. Ignoring unknown controls is also what Datasette does.

### Risk: 15
Most likely divergence: the author validates the control namespace too, making
`?_bogus=1` a 400.

## T29. Empty filter values

### Spec Text
> `<column>__<comparator>=<value>`
> - `exact`: case-sensitive string equality.

### Alternatives
1. An empty value is a legitimate filter: `name__exact=` keeps rows whose cell
   is the empty string, and `name__contains=` keeps every row, since `""` is a
   substring of everything.
2. An empty value is a 400, the way an empty `_sort=` is.

### Choice
Alternative 1. The error table names four specific filter failures and an empty
value is none of them; empty cells are real, storable values (T4), so a query
for them is meaningful. `__less=`/`__greater=` still fail, because the empty
string is not numeric.

### Risk: 25
Most likely divergence: the author guards with `if not value: return 400` by
analogy with the sort parameters, making `name__exact=` a 400.

## T30. What makes two filter keys "duplicates"

### Spec Text
> - Duplicate filter keys are invalid (`HTTP 400`).

### Alternatives
1. The same full key repeated: `age__less=5&age__less=9` is a 400, while
   `age__greater=30&age__less=40` is a legal two-filter AND on one column.
2. The same *column* repeated under any comparator, which would also reject the
   range query above.

### Choice
Alternative 1. The spec says "filter key", and the key is the whole
`<column>__<comparator>` token; reading it as "column" would contradict
"Multiple filters are ANDed", whose most useful case is exactly a two-sided
range on one column.

### Risk: 10
Most likely divergence: the author collapses `request.args` to a plain dict
early, silently keeping the first or last value instead of failing - which would
make `age__less=5&age__less=9` a 200.

## T31. Which filter values count as numeric

### Spec Text
> - `less`: numeric strict less (`float` parse on stored and filter values).
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.

### Alternatives
1. Exactly what Python's `float()` accepts: `5`, `-2.5`, `1e3`, `" 5 "`, and the
   specials `inf`/`nan`.
2. A stricter decimal grammar that rejects the specials and surrounding
   whitespace.

### Choice
Alternative 1. The spec names the parse function - "`float` parse on stored and
filter values" - rather than describing a grammar, so `float()` succeeding *is*
the definition of numeric. `nan` parses and then matches nothing, which is the
correct IEEE answer rather than a special case.

### Risk: 12
Most likely divergence: the author rejects `inf`/`nan` explicitly, or parses
with a regex, making `n__less=inf` a 400 instead of a match-all.

## T32. `rowid` as a filter column

### Spec Text
> - Unknown filter column | 400
> - Column matching is exact and case-sensitive.

### Alternatives
1. The filterable names are exactly the table's `columns`, so `rowid__less=3` is
   an unknown column (400), matching the sorting rule chosen in T21.
2. `rowid` filters as a pseudo-column, since `_shape=objects` rows expose it.

### Choice
Alternative 1, for the same reason as T21: `columns` is the only column
vocabulary the response publishes, and `rowid` is deliberately outside it. One
rule for sorting and filtering also keeps "unknown column" meaning one thing.

### Risk: 20
Most likely divergence: the author filters over object-shaped rows that carry
`rowid`, so `rowid__greater=2` succeeds there.

## T33. A filter key with no column name (`__exact=...`)

### Spec Text
> Control params (names beginning with `_`) are not filters.
> | Unknown filter column | 400 |

### Alternatives
1. `_`-prefixion is checked first, so `?__exact=ada` is a control-namespace name,
   is not a filter, and is ignored (200).
2. The `__` separator is checked first, making the column name the empty string
   and therefore an unknown column (400).

### Choice
Alternative 1. The spec states the control-namespace rule as an unconditional
property of a *name*, before it says anything about how filter keys are parsed,
and `__exact` does begin with `_`. It also matches the natural loop order -
`if key.startswith("_"): continue` ahead of the `__` split.

### Risk: 20
Most likely divergence: the author splits on `__` first and validates the empty
column, making `?__exact=ada` a 400.

## T34. What an uploaded dataset's id is derived from

### Spec Text
> Re-uploading the same file bytes yields the same dataset id.

### Alternatives
1. The id is a hash of the uploaded bytes, so the file name, the field name
   (`file` vs `attachment`) and the upload order are all irrelevant.
2. The id is a hash of the bytes *and* the submitted file name, so the same
   table uploaded as `q1.csv` and `q1-copy.csv` gets two ids.
3. Uploads share `/convert`'s keyspace by being hashed under a synthetic source
   string such as `upload:<sha256>`.

### Choice
Alternative 1, with the same `sha256(...)[:16]` used for source URLs in T1 but
applied to the raw bytes. The spec names "the same file bytes" as the whole
condition, and says nothing about names, so anything else in the key would
falsify it for a renamed re-upload. Alternative 3 is the same function with an
extra prefix and buys nothing observable.

### Risk: 10
Most likely divergence: the author's digest is over a prefixed or otherwise
decorated string, which only shows up if a fixture asserts a literal id - or a
fixture asserts that `/convert` of a URL serving those exact bytes lands on the
same id as uploading them, which this reading deliberately does not do.

## T35. How the source format is recognised

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> Unrecognized format: `HTTP 400`.

### Alternatives
1. Sniff the leading bytes: `PK\x03\x04` is an `.xlsx` (ZIP) container, the OLE2
   signature `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1` is an `.xls`, anything else is
   read as text CSV.
2. Trust the file name: the `.xls`/`.xlsx` suffix of the upload's filename or of
   the `source` URL path selects the reader.
3. Trust the declared media type (`Content-Type` of the fetched response, or of
   the multipart part).

### Choice
Alternative 1. The spec writes the formats as extensions only because that is
how people name them; it never says the name decides. Sniffing is the only rule
that works for all four combinations the spec demands - a `source` URL with no
extension at all, a download whose server sends `application/octet-stream`, a
multipart part with a misleading filename, and an upload with no filename -
whereas alternatives 2 and 3 have to fall back to sniffing for those anyway.
It also gives "unrecognized format" a precise meaning: bytes that announce a
container we cannot read, or that do not decode into a delimited table.

### Risk: 18
Most likely divergence: the author dispatches on the filename/URL extension, so
a `.xlsx` workbook served from a URL ending `.csv` is a 400 for them and a 200
here (or vice versa: a CSV named `.xlsx` is a 400 for them, a 200 here).

## T36. `charset` supplied alongside a spreadsheet source

### Spec Text
> `charset` applies only to text CSV sources.
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. `charset` is looked at only on the CSV path, so a workbook source ignores it
   entirely - including an unusable value such as `charset=utf-99`, which is
   never validated and therefore never 400s.
2. `charset` is always validated as an encoding name, and only its *application*
   is skipped for workbooks, so `charset=utf-99` is a 400 whatever the format.

### Choice
Alternative 1. "Applies only to text CSV sources" is a statement about the whole
parameter, not about one step of handling it, and the earlier 400 arises from
decoding, which a workbook never does. This also keeps the rule cheap to state:
for `.xls`/`.xlsx` the parameter has no effect at all.

### Risk: 30
Most likely divergence: the author validates the charset name up front - before
looking at the bytes - so `/convert?source=<xlsx>&charset=utf-99` is a 400 for
them and a 200 here.

## T37. Whether `/export` paginates by default

### Spec Text
> The CSV uses source column order and applies the same filters, sort, and
> pagination as `/datasets/<id>`.

### Alternatives
1. Pagination carries over whole, defaults included: with no `_size` given, an
   export contains at most the default 100 rows.
2. Only *explicit* pagination carries over; with no `_size` the export is the
   full filtered, sorted table, since a truncated download is a surprising thing
   to hand a user.

### Choice
Alternative 1. The spec says the export applies the same pagination as the JSON
endpoint, and the default page size is part of that pagination, not an
adjustment layered on top of it - a reading under which `?_size=100` and no
`_size` at all would disagree, despite both denoting the same page. Clients that
want everything can ask for it with `_size`.

### Risk: 22
Most likely divergence: the author streams the whole result set when `_size` is
absent, so exporting a 130-row dataset gives them 131 lines and 101 here.

## T38. Invalid `_shape`, `_rowid` or `_total` values on `/export`

### Spec Text
> `_shape`, `_rowid`, and `_total` do not affect CSV output.

### Alternatives
1. They are parsed and validated exactly as on `/datasets/<id>` - so
   `?_shape=nonsense` is still a 400 - and only their *effect* is dropped.
2. Export ignores the three names outright, so any value, valid or not, passes
   and returns CSV.

### Choice
Alternative 1. The spec's claim is about the CSV output, and a 400 is not CSV
output; meanwhile the sentence before it ties export to the same query handling
as `/datasets/<id>`, where those values are validated. One query parser for both
routes also means `_size`, `_sort` and filter errors keep behaving identically,
which the "same filters, sort, and pagination" sentence demands anyway.

### Risk: 25
Most likely divergence: the author builds the export by calling the JSON
endpoint's row pipeline with only the pagination/sort/filter arguments and never
looks at the three presentation names, so `?_shape=nonsense` returns 200 CSV.

## T39. Whether the exported CSV carries a header row

### Spec Text
> The CSV uses source column order.
> - export columns follow source column order.

### Alternatives
1. The first line is the column names in source order, then the data rows - the
   export is a CSV round-trip of the source table.
2. Data rows only, with column order implied but not written out.

### Choice
Alternative 1. Talking about "export columns" at all only makes sense if the
columns appear somewhere in the output, and a `.csv` download without a header
is not something the dataset's own `columns` list could be recovered from.

### Risk: 5
Both spec sentences point the same way; the residual risk is a fixture that
counts lines against a headerless export.

## T40. The exact `Content-Type` of the export response

### Spec Text
> - `Content-Type: text/csv`

### Alternatives
1. The header is exactly `text/csv`.
2. The header is `text/csv; charset=utf-8` - what a framework adds by default
   once a text mimetype is named.

### Choice
Alternative 1, set explicitly rather than left to Flask's mimetype default. The
spec writes the header value out in full, and the bare form satisfies both an
exact-equality assertion and the `startswith`/`in` checks an author writes when
they are unsure which form their own stack produces.

### Risk: 12
Most likely divergence: the author's response carries the charset suffix and a
fixture asserts that exact string, which the bare form would fail.

## T41. Turning spreadsheet cells into values

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> Formula/computed-cell behavior is not required.

### Alternatives
1. Render every cell to the text a spreadsheet would show - blanks as `""`,
   whole numbers without a `.0` tail - and then run the same type inference the
   CSV path uses, so the two formats produce identical tables for identical data.
2. Pass the reader's native Python objects straight through, so `.xlsx` yields
   `36` where `.xls` yields `36.0` (the BIFF format stores every number as a
   double) and blank cells become `null`.
3. Keep spreadsheet-only types as rich values: dates as ISO strings, booleans as
   JSON `true`/`false`.

### Choice
Alternative 1. The spec gives one set of typing rules for datasets and never
carves out a second one for workbooks, so `/datasets/<id>` should not be able to
tell how a table arrived; alternative 2 makes the same file disagree with itself
across the two Excel formats. Cached values are read in preference to formula
text, which is the most useful behaviour where none is required.

### Risk: 28
Most likely divergence: the author is on pandas' `read_excel`, so blank cells
arrive as `null` rather than `""` (the T4 divergence again) and an integer
column containing a blank comes back as floats.

## T42. Both `file` and `attachment` present in one upload

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`.

### Alternatives
1. `file` is looked for first and wins; `attachment` is the fallback spelling.
2. Supplying both is ambiguous and therefore a 400.
3. Both are ingested, producing two datasets.

### Choice
Alternative 1. The spec lists two accepted names for one thing and gives an
error table that does not mention the both-present case, so it is not an error;
the natural implementation checks the names in the order they are written.

### Risk: 15
Most likely divergence: the author iterates the parts as they arrive rather than
in a fixed name order, so a body whose `attachment` part comes first ingests
that one.

## T43. An upload field sent as a plain form value

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`.
> malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. The part is taken whether or not it declares a filename, so a `file` part
   holding raw CSV text is accepted and read as UTF-8 bytes.
2. Only parts with a `filename` (which is what a framework routes into its
   "files" collection) count; a plain-valued `file` part is a missing field, 400.

### Choice
Alternative 1. The spec's condition is stated as a *field name* being present,
not as an upload having a filename, and it goes on to identify a dataset by
"file bytes" - which a plain-valued part has just as much as a named one.
Accepting both spellings cannot turn a would-be 400 into a wrong 200, because a
`file` field that holds something untabular still fails the tabular check.

### Risk: 12
Most likely divergence: the author reads only the request's file collection, so
a plain-valued `file` field is a 400 for them and a 200 here.

## T44. A single-column first worksheet

### Spec Text
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. The stated test is the whole test: a header row plus one or more data rows is
   tabular, however many columns it has, so a one-column sheet is accepted.
2. A table needs at least two columns, mirroring the CSV path, where a document
   no candidate delimiter splits into more than one column is non-tabular.

### Choice
Alternative 1. The spec spells the spreadsheet condition out in full and it
mentions rows only. The CSV two-column rule exists because a single column there
means *no delimiter was found*, which is evidence the file is not delimited at
all; a worksheet has explicit cells, so a single column carries no such doubt.

### Risk: 22
Most likely divergence: the author shares one tabular-shape check between the
CSV and spreadsheet paths, making a one-column sheet a 400.

## T45. What an exported cell shows

### Spec Text
> semantically-correct CSV is required; exact newline/quoting is not.
> The CSV uses source column order.

### Alternatives
1. Export writes the stored, type-inferred value, so a cell the ingest step read
   as the number `7` exports as `7` even if the source file said `007`.
2. Export writes the original source text, keeping `007`, trailing zeros and
   surrounding whitespace byte-for-byte.

### Choice
Alternative 1. The dataset the export serves is the parsed one - the spec has
export applying the same filters, sort and pagination to those rows - and
nothing in the store keeps the pre-inference text. Round-tripping a dataset
through `/export` and back through `/upload` therefore reaches a fixed point,
which alternative 2 could not promise either, since it would still have to
re-quote.

### Risk: 18
Most likely divergence: the author exports from a frame that retained the raw
strings, so zero-padded and whitespace-padded cells come back unchanged.

## T46. `charset` on `/upload`

### Spec Text
> `charset` applies only to text CSV sources.
> `GET /convert?source=<url>[&charset=<encoding>]`

### Alternatives
1. `/upload` honours a `charset` given in its query string, because an uploaded
   CSV is a text CSV source like any other.
2. `charset` belongs to `/convert` alone; an upload is always decoded by
   detection, and a `charset` on `/upload` is silently ignored.

### Choice
Alternative 1. The sentence introducing `charset` in this section is about
*sources*, not about one route, and the section's whole point is that the two
ingestion routes accept the same formats on the same terms. Honouring it costs
one parameter lookup and leaves alternative 2's behaviour intact for every
request that omits it.

### Risk: 20
Most likely divergence: the author's `/upload` never reads `charset`, so an
upload of latin-1 bytes with `?charset=latin-1` is detected-decoded for them
(and, if they also validate the name, `?charset=utf-99` stays a 200 rather than
becoming the 400 it is here).

## T47. `multipart/form-data` with no boundary

### Spec Text
> - non-multipart request: `HTTP 415`
> - malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. The media type alone decides "multipart": a `multipart/form-data` header with
   no `boundary` parameter is multipart, and unparseable, so it is malformed -
   400.
2. A multipart body that cannot even be split into parts was never really a
   multipart request - 415.

### Choice
Alternative 1. The 415 rule is about the *request type* the client declared, and
this client declared multipart; everything that goes wrong after that point is
the 400 branch, which the spec words broadly enough ("malformed multipart") to
cover a missing boundary. Splitting on the media type alone also keeps the two
statuses decidable from the headers, before any body is read.

### Risk: 20
Most likely divergence: the author lets the framework's parser decide and it
raises an unsupported-media-type error for a boundary-less body, giving 415.

## T48. Where `CACHE_ENABLED` is read from

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:
> Invalid values fail startup.

### Alternatives
1. An environment variable read when the process starts.
2. A command line option on `datagate start` (`--cache-enabled`).
3. A request-time query parameter or a config file key.

### Choice
An environment variable, read once in `create_app()`. The spec spells the name
in `SCREAMING_SNAKE_CASE`, which is the environment's convention and not the
convention of this CLI's options (`--port`, `--address`), and it ties the value
to *startup* rather than to a request. Reading it while the app is built is what
makes an invalid value abort the process before it listens.

### Risk: 6
Most likely divergence: the author also accepts a CLI flag, in which case an
environment-only implementation still satisfies any environment-based fixture.

### Annotation (Configuration, Size Limits, and Access Control)
Superseded in part. `CACHE_ENABLED` is now one of five settings, and this spec
names two sources for all of them - the `DATAGATE_CONFIG` file and the
environment - with the environment winning. The environment reading above still
holds; the config file is now a second place the same key may come from.

## T49. What "fail startup" means

### Spec Text
> Invalid values fail startup.

### Alternatives
1. Raise, print a message, and exit non-zero without binding the port.
2. Log a warning and fall back to the default (caching enabled).
3. Exit zero but serve nothing.

### Choice
Alternative 1: `cache_enabled()` raises `ConfigurationError`, `create_app()`
propagates it, and the CLI turns it into `SystemExit` with a message naming
`CACHE_ENABLED`. "Fail" excludes a silent fallback, and a non-zero exit is the
only way a supervisor can see the failure.

### Risk: 5
Any check that starts the server with a bad value and observes that it never
answers - or that `create_app()` raises - passes under this reading. Residual
risk is a fixture asserting one specific exit code (say `2`) or message text.

## T50. `CACHE_ENABLED` values that are close to legal

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:
> - true: `1`, `true`, `yes`, `on`
> - false: `0`, `false`, `no`, `off`

### Alternatives
1. Strict membership after lower-casing only: `" true"`, `"true "` and `""` are
   invalid and fail startup.
2. Lenient: strip surrounding whitespace first, so `" true"` is true.
3. Treat an empty or whitespace value as "unset", falling back to the default.

### Choice
Alternative 1. The spec says *strict*, and names case-insensitivity as the one
liberty taken; adding whitespace tolerance would be a second liberty it does not
grant. An empty string is a value that was set, and it is not in either list, so
it fails startup - only an absent variable takes the default.

### Risk: 18
Most likely divergence: the author writes `os.environ.get(...).strip().lower()`,
making `" true"` valid, or defaults on an empty string rather than failing.

### Annotation (Configuration, Size Limits, and Access Control)
Resolved against this entry's choice. "Boolean values are strict: `1/true/yes/on`
or `0/false/no/off` (case-insensitive, trimmed)" adds trimming, so `" true"` is
now true and alternative 2 is the reading `datagate` implements. An empty or
all-whitespace value trims to `""`, which is in neither list and still fails
startup.

## T51. Whether a `force` value can switch the flag off

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.

### Alternatives
1. Presence alone decides: `force`, `force=`, `force=1` and `force=0` all force
   re-ingestion, because the value is never read.
2. The value is parsed like `CACHE_ENABLED`, so `force=0`/`force=false` leaves
   the cache in use (and, possibly, an unparseable value is a 400).

### Choice
Alternative 1. "Presence flag" is exactly the term for a parameter whose value
carries no meaning, and the spec gives `force` no value vocabulary of its own
while giving `CACHE_ENABLED` an explicit one - the contrast is deliberate.

### Risk: 20
Most likely divergence: the author reuses the boolean parser for `force`, so
`?force=0` returns the cached dataset instead of re-ingesting.

## T52. Whether `force` applies outside `/convert`

### Spec Text
> `/convert` caches results by default.
> ### Per-request bypass
> `force` is a presence flag.

### Alternatives
1. `force` is a `/convert` parameter; `/upload` and `/datasets/<id>` ignore it
   like any other unknown parameter.
2. `force` is a global control, so repeating it anywhere is a 400.

### Choice
Alternative 1. The whole section is scoped to `/convert` - it is the endpoint
that caches - and `/upload` has nothing to bypass, since it re-parses the bytes
the request itself carried and replaces the stored dataset every time.

### Risk: 12
Most likely divergence: the author validates `force` in shared request-parsing
code, so a repeated `force` on `/upload` is a 400 there too.

## T53. Repeated `force` while caching is disabled

### Spec Text
> Any additional `force` value is `HTTP 400`.
> If caching is disabled, `force` has no additional effect.

### Alternatives
1. The 400 is request validation and fires regardless of `CACHE_ENABLED`; "no
   additional effect" only means a single `force` changes nothing, because the
   request re-ingests anyway.
2. With caching disabled `force` is inert entirely, so even a repeated `force`
   is accepted and the request succeeds.

### Choice
Alternative 1. A malformed request is malformed whatever the server's cache
setting, and reading the sentence the other way would make the response to a
fixed request depend on a deployment setting the client cannot see. "No
*additional* effect" is about behaviour, not about validation.

### Risk: 22
Most likely divergence: the author short-circuits the whole `force` branch when
caching is off, so `?force&force` returns 200 there.

## T54. Whether `charset` takes part in the cache key

### Spec Text
> repeated `/convert` requests for the same source URL can return the cached
> dataset id without re-downloading.

### Alternatives
1. The cache is keyed by the `source` URL string alone, so a request that adds
   or changes `charset` still hits the cache and the new charset is ignored.
2. The key is `(source, charset)`, so changing `charset` re-ingests.

### Choice
Alternative 1. The spec keys the cache on "the same source URL", and the dataset
id is derived from that string alone (T1); a `(source, charset)` key would make
one id hold two different parses, with no rule for which one a later request
sees. A client that wants the new charset applied has `force` for exactly that.

### Risk: 25
Most likely divergence: the author re-ingests when `charset` differs from the
cached request's, so `?source=X&charset=latin-1` after a plain `?source=X`
re-parses.

## T55. How long a cached dataset lives

### Spec Text
> `/convert` caches results by default.

### Alternatives
1. The cache is the dataset store itself: entries live as long as the process
   and never expire.
2. Entries carry a TTL, or the cache is bounded and evicts.
3. The cache is persisted to disk, surviving restarts.

### Choice
Alternative 1. The spec gives no expiry, no size bound and no store location,
and it equates a cache hit with "the cached dataset id" - the same in-process
dataset `/datasets/<id>` already serves. A dataset that survived a restart would
also have to outlive the store, which nothing in the spec describes.

### Risk: 7
Most likely divergence: the author adds a TTL and a fixture ages past it, which
no in-process cache without expiry could pass.

### Annotation (Configuration, Size Limits, and Access Control)
Superseded. "Persisted datasets must survive restart when the same directory is
reused" makes alternative 3 the spec's own reading: the store lives in
`STORAGE_DIR` on disk, so a `/convert` cache hit can outlive the process. The
"no TTL, no eviction" half of the choice is untouched - this spec adds no expiry.

## T56. What a failed re-ingestion leaves behind

### Spec Text
> - Re-ingestion failures keep existing error codes and envelope.
> - Forced re-ingestion failure keeps prior dataset queryable.

### Alternatives
1. The stored dataset is replaced only after a fetch and parse both succeed, so
   a failure is invisible to `/datasets/<id>`.
2. The entry is evicted first and re-filled, so a failure leaves a 404 behind.

### Choice
Alternative 1 - "keeps prior dataset queryable" states the outcome directly, and
ingesting before storing is what produces it. The failure itself is raised by
the same fetch/parse code as a first ingestion, which is how the existing status
codes (404 unreachable, 400 non-tabular or bad charset) and the `{"ok": false,
"error": ...}` envelope stay unchanged.

### Risk: 3
Both bullets point the same way.

## T57. Which end of the precedence list wins

### Spec Text
> Service configuration sources, in order of precedence:
>
> 1. Built-in defaults
> 2. `DATAGATE_CONFIG` file
> 3. Direct environment variables

### Alternatives
1. Ascending: each source overrides the one above it, so a direct environment
   variable beats the config file, which beats the built-in default.
2. Descending, the way "order of precedence" is often written elsewhere: item 1
   is the highest, so built-in defaults would override everything.

### Choice
Alternative 1. Reading it descending makes built-in defaults unoverridable,
which would leave the other two sources with no effect at all and contradict
the settings table's "Default" column. Ascending is the only reading under
which all three sources do something.

### Risk: 4
Only a deliberately perverse implementation reads this the other way.

## T58. The exact grammar of a config file line

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values,
> blank/comment lines ignored.

### Alternatives
1. Split each line on its *first* `=`; trim whitespace around key and value;
   a line whose first non-space character is `#` is a comment; a non-blank,
   non-comment line with no `=` is invalid config and fails startup.
2. The same, but a malformed line is skipped rather than fatal.
3. Shell-like: also strip matching quotes around the value, honour `export`
   prefixes, and support `;` comments.

### Choice
Alternative 1. Splitting on the first `=` is what lets a value contain one,
which matters for `STORAGE_DIR` and for URLs; `#` is the comment marker this
format is universally written with. A line that is neither blank nor a comment
nor `KEY=VALUE` is not something the spec describes, and "Invalid config ...
at startup returns an error and exits" is the spec's own instruction for input
it cannot read, so it is fatal rather than skipped. Values are trimmed and kept
literal - no quote stripping, since the spec never mentions quoting.

### Risk: 20
Most likely divergence: the author tolerates malformed lines by skipping them,
or strips surrounding quotes from values so `STORAGE_DIR="/tmp/x"` works.

## T59. `DATAGATE_CONFIG` naming a file that cannot be read

### Spec Text
> 2. `DATAGATE_CONFIG` file
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. `DATAGATE_CONFIG` unset means "no file" and is fine; set but missing, or
   set but unreadable, is a read failure and exits.
2. A missing file is also fine - treated as an empty config - and only a
   permission or I/O error counts as a read failure.
3. `DATAGATE_CONFIG` set to the empty string names a file and fails too.

### Choice
Alternative 1, with an empty `DATAGATE_CONFIG` treated as unset. "Read failure"
is listed as a startup error, and asking for a config file that is not there is
the most common way reading one fails; silently ignoring it would let a typo in
a deployment path disable every setting without a word. An unset or empty
variable, by contrast, expresses no intent to read anything.

### Risk: 25
Most likely divergence: the author treats a missing path as "no config" and
only fails on a genuine I/O error, so a fixture pointing at a nonexistent file
expects a working server rather than an exit.

## T60. Settings given an empty value

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> | `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |

### Alternatives
1. An empty (or all-whitespace) value means "unset", falling back to the
   default: no size limit, no allowlist, default storage directory.
2. An empty value is invalid for every setting and fails startup.
3. Empty means unset for the two settings whose default *is* "unset", and is
   invalid for the ones with a concrete default.

### Choice
Alternative 1 for `MAX_SOURCE_SIZE`, `ORIGIN_ALLOWLIST` and `STORAGE_DIR`, and
alternative 2 for the two booleans. "Unset" is a value the spec gives those
settings, and an empty string is the only way a config file or an environment
variable can spell it, so `ORIGIN_ALLOWLIST=` is how a deployment turns an
inherited allowlist back off. The booleans are different because the spec makes
them *strict*: `""` is in neither list, so it fails startup (see [T50]).
An `ORIGIN_ALLOWLIST` of only commas and spaces yields no entries, which is the
same as unset.

### Risk: 30
Most likely divergence: the author never special-cases the empty string and
lets `MAX_SOURCE_SIZE=` raise on `int("")`, making it a startup failure.

## T61. Keys the settings table does not list

### Spec Text
> The config file is `KEY=VALUE` lines ...
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. Unknown keys are ignored, so the file may carry unrelated deployment
   variables.
2. Unknown keys are invalid config and fail startup.

### Choice
Alternative 1. "Invalid config" most naturally covers a value datagate cannot
read for a setting it owns, not the mere presence of a key it has no opinion
about; and the same file is the kind of thing a deployment shares between
processes. Ignoring them also keeps a future setting from bricking an older
binary.

### Risk: 15
Most likely divergence: the author validates the key set and exits on anything
unrecognised, so a fixture with a stray key expects a startup failure.

## T62. Which integers `MAX_SOURCE_SIZE` accepts

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> - file size `= limit` accepted.
> - file size `> limit` => `HTTP 400` with standard envelope.

### Alternatives
1. A non-negative decimal integer; `0` is a real limit that rejects every
   non-empty body; anything else (negative, fractional, `1kb`, `1_000`) is
   invalid config and fails startup.
2. `0` means "no limit", reusing zero as a sentinel for unset.
3. Human-readable suffixes (`10MB`, `1k`) are parsed too.

### Choice
Alternative 1. The type column says "integer bytes", not a size expression, so
no suffixes; and the spec gives exactly one way to mean "no max" - leaving the
setting unset - so reading `0` as a second way would contradict the rule that
`> limit` is rejected. A negative byte count is not a size any file can be
compared against, so it is invalid rather than silently clamped.

### Risk: 22
Most likely divergence: the author writes a bare `int(value)`, which accepts
`-1` and `+10` and treats a negative limit as "reject everything"; a fixture
using `0` to mean "unlimited" is the other way this parts company.

## T63. What the size limit measures

### Spec Text
> Enforced for `/convert` and `/upload`:
> - file size `= limit` accepted.

### Alternatives
1. The byte length of the body datagate actually has: the downloaded response
   content for `/convert`, the uploaded part's bytes for `/upload`. Checked
   after retrieval and before parsing.
2. The `Content-Length` the origin advertises, so an oversized download is
   refused without being read.
3. The size of the parsed dataset (row count, or the JSON it serialises to).

### Choice
Alternative 1. "File size" is the size of the file being ingested, and the one
measurement both routes can make identically is the length of the bytes in
hand - `/upload` has no `Content-Length` for the part, and an origin's header
may be absent or wrong. Checking between retrieval and parsing is what makes an
oversized source a 400 rather than a parse error, and it is the same byte string
`/upload` derives its dataset id from.

### Risk: 12
Most likely divergence: the author streams and aborts on the advertised
`Content-Length`, which differs only for an origin that lies about it.

## T64. Whether a `/convert` cache hit is size-checked

### Spec Text
> Enforced for `/convert` and `/upload`
> `/convert` caches results by default.

### Alternatives
1. The check applies to bytes that were fetched, so a cache hit - which fetches
   nothing - is answered from the store without a size check.
2. The size of the originally stored source is remembered and re-checked on
   every `/convert`, so lowering the limit and restarting makes previously
   stored datasets unreachable through `/convert`.

### Choice
Alternative 1. The limit is on the *source*, and a cache hit has no source in
hand to measure; re-deriving a size from a stored dataset would measure the
parsed table rather than the file. This also keeps the cache's whole point
intact - a hit answers without touching the network.

### Risk: 20
Most likely divergence: the author's fixture lowers the limit between two
`/convert` calls for one URL and expects the second to be rejected. A fixture
that instead uses a fresh URL per limit cannot tell the readings apart.

## T65. Domain-boundary rules for an allowed suffix

### Spec Text
> 3. Accept only hostnames matching any allowed suffix case-insensitively with
>    domain-boundary rules.

### Alternatives
1. A hostname matches suffix `s` when it equals `s` or ends with `"." + s`, both
   compared lower-cased. `evilexample.com` therefore fails against
   `example.com`, and `a.b.example.com` passes.
2. Plain string suffix matching, so `evilexample.com` passes - which is exactly
   what "domain-boundary rules" exists to forbid.
3. Only exact equality, so no subdomain ever passes - which would make "suffix"
   the wrong word.

### Choice
Alternative 1: it is the standard meaning of a domain-suffix match and the only
one under which both "suffix" and "domain-boundary" do work. An entry written
with a leading dot (`.example.com`) or a trailing dot is normalised before
comparison, and a hostname's trailing root dot is dropped, so the same rule
covers the spellings a deployment is likely to use. A port or userinfo in the
`Referer` never reaches the comparison, because step 2 parses a *hostname*.

### Risk: 15
Most likely divergence: the author accepts an allowlist entry that is a full
origin (`https://example.com`) or a `host:port`, which this reading treats as a
suffix no hostname can match.

## T66. How much "every request" covers

### Spec Text
> If configured, check every request before routing:
> 1. Require `Referer`.

### Alternatives
1. Literally every request the app receives - `/convert`, `/upload`,
   `/datasets/<id>`, `/export`, unknown paths and `OPTIONS` alike - so the
   allowlist is a gate in front of the router and a request without a good
   `Referer` is 403 even when its path does not exist.
2. Only the two ingestion routes, matching the size limit's stated scope.
3. Every route that exists, but unknown paths still 404 and CORS preflight
   `OPTIONS` requests are exempt, since browsers do not send `Referer` on them.

### Choice
Alternative 1. "Every request" and "before routing" are both explicit, and they
say the opposite of alternative 2 - which the spec could have written by naming
the routes, as the size-limit section does one heading earlier. Deciding before
routing also means the 403 does not leak which paths exist. The cost is that a
cross-origin preflight is refused while an allowlist is active; the spec chose
`Referer` knowing it, and nothing here carves out a method.

### Risk: 35
Most likely divergence: the author registers the check as a `before_request`
hook but lets Flask's automatic `OPTIONS` handling or its 404 run first, so a
fixture hitting an unknown path with no `Referer` expects 404, or a preflight
expects 200. This is the entry in this section most likely to be tested against
a different reading.

## T67. A `Referer` with no parseable hostname

### Spec Text
> 1. Require `Referer`.
> 2. Parse hostname.
> 4. Otherwise return `HTTP 403`.

### Alternatives
1. A header that is present but yields no hostname - `""`, `about:blank`,
   `/page.html`, `example.com/x` with no scheme - is not a hostname that can
   match, so it falls through to step 4 and is 403.
2. Such a header is a malformed request and is 400.
3. A bare `example.com/x` is repaired by assuming `http://`, then matched.

### Choice
Alternative 1. Step 4 says "otherwise", which is the catch-all for anything that
did not match at step 3, and the error table gives only two 403 rows - missing
and not-allowed - with no row for a malformed one. Guessing a scheme (3) would
accept a `Referer` no browser sends.

### Risk: 10
Both failure modes are 403 under this reading, so only a fixture expecting 400
for a malformed `Referer` separates them.

## T68. Whether `REQUIRE_TLS` also refuses plaintext requests

### Spec Text
> ### TLS-aware endpoint URLs
> `REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints.
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request
> host.

### Alternatives
1. The setting only shapes the advertised endpoint URL; a plaintext request is
   still served, because the heading and both bullets talk about URLs and
   nothing else.
2. The name is taken at face value: an `http://` request is redirected or
   rejected (400/403/426) when `REQUIRE_TLS=true`.

### Choice
Alternative 1. The whole section is titled "TLS-aware endpoint URLs" and
describes one observable difference - relative versus absolute `https://`. The
error-handling table lists no status for a plaintext request, which it would
have to if rejection were part of the contract. A test client speaking HTTP to
the app is also the only way the absolute-URL behaviour can be observed at all.

### Risk: 12
Most likely divergence: the author also rejects or redirects plaintext, which
would make every `REQUIRE_TLS=true` fixture unreachable over a plain test
client - so most likely they did not.

## T69. Which host the absolute endpoint uses

### Spec Text
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request
> host.

### Alternatives
1. The `Host` header exactly as received, port and all:
   `https://<host header><path>`.
2. The host with any port stripped, since an `https` URL on a non-443 port is
   unusual.
3. `X-Forwarded-Host` when present, falling back to `Host`.

### Choice
Alternative 1. "Using request host" names the request's host, and rewriting it
would make the advertised URL point somewhere the client did not ask for.
Honouring a forwarding header (3) is a proxy policy the spec never mentions and
a header any client can forge. The path is the same `/datasets/<id>` the
relative form returns, so the two differ only by scheme and authority.

### Risk: 10
Most likely divergence: the author drops the port, which shows up only when a
fixture sets a `Host` carrying one.

## T70. The default `STORAGE_DIR`

### Spec Text
> | `STORAGE_DIR` | path | implementation-defined |
> Create `STORAGE_DIR` if missing.

### Alternatives
1. A fixed directory relative to the working directory, created on startup.
2. A temporary directory unique to each process, which would make persistence
   across restarts impossible by default.
3. A path under the user's home or `/var/lib`.

### Choice
`./datagate-data`, resolved against the working directory - alternative 1. The
spec explicitly hands this choice to the implementation, so the only real
constraint is the next sentence: datasets must survive a restart that reuses the
directory, which rules out alternative 2. A relative path under the working
directory needs no privileges and is the one location a second run of the same
command is guaranteed to reuse. A configured relative path is resolved the same
way, and its parents are created along with it.

### Risk: 5
The spec calls this implementation-defined, so a fixture can only test a
`STORAGE_DIR` it sets itself. Residual risk is a fixture asserting a particular
default path name.

## T71. What "persisted datasets survive restart" covers

### Spec Text
> Create `STORAGE_DIR` if missing.
> Persisted datasets must survive restart when the same directory is reused.

### Alternatives
1. Every stored dataset, from `/convert` and `/upload` alike, is written into
   `STORAGE_DIR` as it is saved and read back from there, so a restarted
   process serves `/datasets/<id>` for ids the previous process minted and
   answers `/convert` for those sources from cache without re-downloading.
2. Only `/convert` results persist, `/upload` staying in memory.
3. The directory holds the raw source bytes, re-parsed on each read.

### Choice
Alternative 1. The sentence says "datasets", not "converted datasets", and both
routes produce one through the same store; splitting them would make an
uploaded dataset's endpoint break across a restart for no stated reason. Each
dataset is one JSON file named for its id, holding the columns and the rows as
already-inferred values - so a reload reproduces the exact table the first parse
produced, which re-parsing raw bytes (3) would not guarantee. Because a cache
hit is "a dataset is already stored", persistence makes the `/convert` cache
outlive the process too.

### Risk: 18
Most likely divergence: the author keeps an in-memory index alongside the files
and treats the cache as process-local, so a fixture expects a restarted server
to re-download a source it can still serve from `/datasets/<id>`.

## T72. Which check answers first when more than one applies

### Spec Text
> If configured, check every request before routing:
> Enforced for `/convert` and `/upload`

### Alternatives
1. Allowlist first - it runs "before routing", so an oversized upload from a
   disallowed origin is 403, not 400.
2. Per-route checks first, so the size limit wins on the ingestion routes.

### Choice
Alternative 1, which the spec states directly: the allowlist check happens
before a request reaches a route at all, and the size limit is something a
route does once it has the bytes. Within a route, the size check precedes
parsing, so an oversized non-tabular file is 400 for being oversized.

### Risk: 8
Both are 4xx and a fixture has to combine two violations in one request to tell
them apart.
