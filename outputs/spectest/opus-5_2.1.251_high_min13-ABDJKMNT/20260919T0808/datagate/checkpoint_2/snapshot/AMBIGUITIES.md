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
