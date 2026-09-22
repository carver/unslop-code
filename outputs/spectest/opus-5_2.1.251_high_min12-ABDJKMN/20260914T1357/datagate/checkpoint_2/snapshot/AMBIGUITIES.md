# Ambiguities

Numbered record of spec under-specification, the interpretation chosen, and the
risk that the spec author's own implementation reads it differently.

---

## T1 — Derivation and format of the dataset id

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. Cryptographic digest of the exact URL string (sha256/md5), hex, possibly truncated.
2. A UUIDv5 over the URL.
3. A URL-safe base64 of the digest.
4. A sequential counter, memoised per URL (stable within a process only).

### Choice
`sha256(source_url_string.encode("utf-8")).hexdigest()[:16]`. It is a pure
function of the URL string, so it is stable across processes and restarts
(which alternative 4 is not), and it is opaque and URL-safe.

### Risk: 5
The author most likely also hashes the URL string; any test can only
reasonably assert the endpoint is stable and reusable, which holds for every
alternative. A test pinning a literal id string would need our exact digest
length — the most likely different reading is a full-length `sha256` hexdigest.

---

## T2 — Numeric-looking values with leading zeros (`007`, `01234`)

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.

### Alternatives
1. Convert to a number (`007` → `7`), losing the zero padding.
2. Keep as text, because the padding is significant (zip codes, ids, phone numbers).

### Choice
Convert to a number. The spec lists exactly one carve-out from numeric coercion
(time-like values); had zero-padding been a second carve-out, the spec would
likely have named it alongside. The obvious implementation (`int(value)` with a
fallback to text) produces `7`.

### Risk: 30
Author most likely prefers: same (plain `int()`/`float()` coercion → `7`); the
plausible divergence is an implementation that preserves leading zeros as text.

---

## T3 — Formatted numbers: `1,234`, `$5.00`, `50%`, `(12)`

### Spec Text
> - Integers/decimals are JSON numbers.
> No dependence on clock/locale/timezone beyond `query_ms`.

### Alternatives
1. Strip grouping separators / currency / percent signs and emit a number.
2. Only bare integer/decimal literals become numbers; anything else is text.

### Choice
Option 2. Interpreting `1,234` requires a locale decision (`1,234` is 1234 in
en-US and 1.234 in de-DE), and the spec forbids locale dependence.

### Risk: 10
Author most likely prefers: same (bare literals only).

---

## T4 — Surrounding whitespace in fields (` 5 `, ` name `)

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> `columns` and each row follow source column order.

### Alternatives
1. Emit fields verbatim, so ` 5 ` stays text and ` ada ` keeps its spaces.
2. Strip surrounding whitespace from every field and header, then infer type.
3. Strip only for type inference, but emit the unstripped string when it stays text.

### Choice
Option 2 — strip headers and values, then infer. `int(" 5 ")` succeeds in
Python, so the natural implementation already treats padded numbers as numbers;
applying the same normalisation to text keeps the rule uniform, and delimiter
sniffing on `a, b, c` otherwise yields headers with stray spaces.

### Risk: 20
Author most likely prefers: same for values adjacent to a delimiter-space
(`a, b`), but an implementation that never strips would keep `" b"` verbatim.

---

## T5 — Empty cells

### Spec Text
> - Strings remain text.
> ```json
> "rows": [["<val1>", "<val2>", "..."]]
> ```

### Alternatives
1. Empty string `""` (a zero-length text value).
2. JSON `null` (a missing value, as pandas/NaN-based implementations produce).

### Choice
`""`. The CSV reader yields `""`, the spec's row shape shows only string/number
values and never mentions nulls, and `""` round-trips as text.

### Risk: 25
Author most likely prefers: same, unless their implementation goes through
pandas, where a blank cell becomes `NaN` and serialises as `null`.

---

## T6 — Boolean-looking values (`true`, `False`, `yes`)

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.

### Alternatives
1. Coerce to JSON `true`/`false`.
2. Leave as text — the spec's type list has only text and numbers.

### Choice
Option 2. The spec enumerates exactly two output types plus the time-like
carve-out; booleans are not mentioned, so they fall under "strings remain text".

### Risk: 20
Author most likely prefers: same; a pandas-based implementation would infer a
real boolean dtype for a column of `true`/`false` and emit JSON booleans.

---

## T7 — `NaN`, `Infinity`, `-inf`

### Spec Text
> - Integers/decimals are JSON numbers.
> All errors are JSON

### Alternatives
1. `float("nan")`/`float("inf")` succeed in Python, so emit them as numbers
   (producing the non-standard JSON tokens `NaN`/`Infinity`).
2. Treat them as text, since they are not integers or decimals and are not
   representable in standard JSON.

### Choice
Option 2 — keep them as text so every response is valid JSON.

### Risk: 10
Author most likely prefers: same.

---

## T8 — Scientific notation (`1e5`, `2.5E-3`)

### Spec Text
> - Integers/decimals are JSON numbers.

### Alternatives
1. Number (`1e5` → `100000.0`), since it is a decimal literal.
2. Text, since it is neither a plain integer nor a plain decimal.

### Choice
Option 1 — `float()` accepts it, and it is unambiguously a decimal value with no
locale sensitivity.

### Risk: 20
Author most likely prefers: same (a `float()` fallback accepts it); a
regex-restricted implementation would keep it as text.

---

## T9 — Rows with more/fewer fields than the header

### Spec Text
> `columns` and each row follow source column order.
> A valid file requires at least one header row and one data row.

### Alternatives
1. Reject the whole file as non-tabular (400).
2. Pad short rows with `""` and truncate extra fields, so every row has
   `len(columns)` values.
3. Emit ragged rows exactly as parsed.

### Choice
Option 2. The spec never calls ragged rows an error condition, and a rectangular
result is what "each row follows source column order" implies for consumers.

### Risk: 30
Author most likely prefers: same rectangularisation, but a pandas-based
implementation raises `ParserError` on long rows → 400, and a naive `csv.reader`
implementation would emit ragged rows.

---

## T10 — Duplicate or empty header names

### Spec Text
> "columns": ["<col1>", "<col2>", "..."]

### Alternatives
1. Emit header labels verbatim, duplicates and all.
2. De-duplicate (`a`, `a.1`) or synthesise names for blank headers.

### Choice
Option 1 — verbatim. Columns are returned "in source order", and the spec gives
no renaming rule; renaming would surprise a caller diffing against the source.

### Risk: 20
Author most likely prefers: same; a pandas-based implementation renames
duplicates to `a.1` and blanks to `Unnamed: 2`.

---

## T11 — Single-column input (no delimiter present)

### Spec Text
> Delimiter must be inferred from input; minimum supported delimiters are `,`,
> `;`, and `\t`.
> | Non-tabular content | 400 |

### Alternatives
1. Accept it as a one-column table (delimiter irrelevant).
2. Reject with 400: no delimiter can be inferred, so the content is not tabular.

### Choice
Option 2. Accepting it means any multi-line plain-text document (prose, a log
file, an HTML page) parses as a valid one-column dataset, which would make the
"non-tabular content → 400" rule nearly unreachable. `csv.Sniffer` — the natural
tool for "infer the delimiter" — also fails on delimiter-free input.

### Risk: 25
Author most likely prefers: same rejection; the divergence is an implementation
that falls back to a comma default and accepts a one-column file.

---

## T12 — Supplied `charset` cannot decode the bytes

### Spec Text
> | Unsupported or malformed `charset` | 400 |
> If `/convert` receives `charset`, use it to decode bytes.

### Alternatives
1. 400 — the charset is wrong for this content, which is the charset error row.
2. Decode with `errors="replace"` and succeed with mojibake.
3. 400 only for unknown codec names; fall back to detection when decoding fails.

### Choice
Option 1, strict decoding. `codecs.lookup()` failures and `UnicodeDecodeError`
both mean "the charset you gave me does not work", and 400 is the only status
the spec offers for a charset problem.

### Risk: 20
Author most likely prefers: same; a lenient implementation using
`errors="replace"` would return 200.

---

## T13 — Row limit override on `/datasets/<id>`

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. The cap is fixed at 100 and no override exists ("default" is just prose).
2. A `limit` query parameter overrides it; 100 is the default.

### Choice
Option 2: `?limit=N` (positive integer) overrides, absent/invalid values fall
back to 100. Calling 100 the *default* implies something can change it, and
supporting the parameter is invisible to a client that never sends it.

### Risk: 15
Author most likely prefers: same parameter name; divergence would be a
different name (`rows`, `n`), a hard 100 cap even with `limit`, or a 400 on a
malformed `limit` (we ignore it and use 100).

### Annotation (resolved by the pagination spec)
The later spec names the override `_size` ("positive integer, default `100`")
and makes an invalid value a `400`, which settles alternative 2 under a
different parameter name. `_size` is now the specified control; the legacy
`limit` parameter is kept as a fallback used only when `_size` is absent, and
keeps its lenient "ignore garbage" behaviour. See [T21].

---

## T14 — Date-like and datetime-like values (`2024-01-15`, `2024-01-15T08:30`)

### Spec Text
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Only clock-time values stay text; other temporal values are unspecified.
2. All temporal values stay text (they are neither integers nor decimals).

### Choice
Option 2 — no date parsing anywhere. Nothing in the spec asks for date objects,
and JSON has no date type, so dates can only be text.

### Risk: 10
Author most likely prefers: same.

---

## T15 — Non-HTTP(S) URL schemes (`ftp://`, `file:///etc/passwd`)

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |
> `source` … URL of the remote CSV file

### Alternatives
1. 400 — only `http`/`https` are valid for "the URL of a remote CSV file".
2. 404 — the fetch fails, so it lands in the unreachable bucket.

### Choice
Option 1: validate the scheme (and the presence of a host) before fetching, and
reject anything that is not `http`/`https` with 400. This also prevents
`file://` from reading local files.

### Risk: 25
Author most likely prefers: same for obviously malformed URLs; an implementation
that hands everything to `requests` and catches `RequestException` would return
404 for `ftp://`/`file://` (`InvalidSchema` is a `RequestException`).

---

## T16 — Re-converting an already known `source`

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Serve from cache: skip the refetch and return the stored endpoint.
2. Refetch, revalidate and replace the stored snapshot; the endpoint is
   unchanged because the id derives from the URL.

### Choice
Option 2. The endpoint requirement is satisfied either way, and refetching keeps
`/convert` meaningful as a re-ingest and keeps error reporting honest (a source
that has since broken reports the error rather than silently returning 200).

### Risk: 10
Author most likely prefers: same (no cache-skipping logic); a caching
implementation would differ only when the remote content changes between calls.

---

## T17 — Wrong HTTP method on a known route (`POST /convert`)

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. 405 Method Not Allowed, JSON body.
2. 404, treating "not a GET route" as an unknown route.

### Choice
Option 1 — 405 with the JSON error envelope. The spec's 404 rule is about
unknown *routes*; `/convert` exists. Both readings keep the body JSON, which is
the requirement actually stated.

### Risk: 15
Author most likely prefers: same (framework default is 405); a catch-all
404 handler would return 404.

---

## T18 — Detecting "non-tabular content"

### Spec Text
> | Non-tabular content | 400 |

### Alternatives
1. Trust the remote `Content-Type` header.
2. Sniff the bytes/text (HTML, JSON, binary, no inferable delimiter).
3. Only fail when the CSV parser finds fewer than two rows.

### Choice
Option 2, ignoring `Content-Type` entirely: reject binary payloads (NUL bytes,
known magic numbers), payloads whose text starts as HTML/XML/JSON, payloads with
no inferable delimiter, and payloads without both a header row and a data row.
Remote servers routinely serve CSV as `text/plain` or
`application/octet-stream`, so the header is not reliable.

### Risk: 20
Author most likely prefers: a content-sniffing rule as well, but their exact
frontier differs — e.g. accepting an HTML page that happens to contain commas,
or rejecting on `Content-Type: text/html` alone.

---

## T19 — Storage scope of rows beyond the limit

### Spec Text
> The endpoint returns stored rows and columns, in source order.
> `rows` returns at most 100 items (or all rows if fewer).

### Alternatives
1. Store only the first 100 rows at convert time.
2. Store the whole file; apply the 100-row limit at query time.

### Choice
Option 2. The limit is described as a property of the *response* ("`rows`
returns at most 100"), and "stored rows" is the full dataset.

### Risk: 5
Author most likely prefers: same; observable only through a `limit` override
(T13).

### Annotation (confirmed by the pagination spec)
Confirmed: `total` is "the row count before pagination" and `_offset` can skip
past the first 100 rows, so the whole file must be stored and the page taken at
query time.

---

## T20 — `query_ms` units and precision

### Spec Text
> "query_ms": 3.2
> `query_ms` is present and non-negative.

### Alternatives
1. Milliseconds as a float (rounded to a few decimals).
2. Milliseconds as an integer.

### Choice
Float milliseconds, rounded to 3 decimals, measuring the time spent building the
query response. The example value `3.2` is fractional.

### Risk: 5
Author most likely prefers: same; any test can only check presence and
non-negativity.

---

## T21 — `_size` and the legacy `limit` parameter

### Spec Text
> `_size` (positive integer, default `100`) limits returned rows.

### Alternatives
1. `_size` replaces the earlier `limit` override entirely; `limit` becomes an
   ordinary ignored query parameter.
2. `_size` is the specified control, and `limit` (T13) keeps working when
   `_size` is absent.

### Choice
Option 2. The new spec never mentions `limit`, so it neither requires nor
forbids it; keeping it is invisible to any client that only sends `_size`, and
it preserves behaviour an earlier spec section implied. `_size` wins whenever
both are present, and only `_size` is subject to the `400` rule — a malformed
`limit` still falls back to 100 (T13).

### Risk: 25
Author most likely prefers: `limit` no longer recognised at all, so
`?limit=5` on a 120-row dataset returns the default 100 rows.

---

## T22 — What "1-based source-file row number" counts

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number).

### Alternatives
1. `rowid` is the 1-based index of the row among the *data* rows, so the first
   data row is `1`.
2. `rowid` is the physical line number in the source file, so the header is
   line 1 and the first data row is `2`.

### Choice
Option 1. "1-based" is precisely the clarification you add when numbering rows
you already hold (`enumerate(rows, start=1)`); under option 2 the natural
wording would be "line number". Physical line numbers are also not recoverable
after CSV parsing (quoted fields may span lines, blank lines are dropped), so
option 2 would be ill-defined for real CSV. `rowid` identifies the source row,
so it travels with the row through sorting and pagination.

### Risk: 30
Author most likely prefers: same (`enumerate(..., 1)` over data rows);
divergence would be header-inclusive numbering where the first data row is `2`.

---

## T23 — Sort order across mixed value types and empty cells

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.
> Sorting is stable and applied before pagination.

### Alternatives
1. Compare values with Python's native ordering (raises `TypeError` for a
   column holding both numbers and text — a 500).
2. Compare everything as text (`str(value)`), so `9` sorts after `100`.
3. Rank by type first, SQLite-style: empty/null < numbers (numerically) <
   text (by code point).

### Choice
Option 3. A column that mixes inferred numbers with text is normal here (type
inference is per cell), so ordering must be total and must never 500. Numbers
must compare numerically for `_sort` to be useful on a numeric column, and
grouping empties at the ascending end mirrors SQL `NULL`s-first ordering that
this dataset-endpoint style is modelled on. Descending is the exact reverse
(empties last) and remains stable for ties.

### Risk: 35
Author most likely prefers: a type-ranked key like this one for numbers-vs-text
columns; the likeliest divergence is where empty cells land (treated as ordinary
empty text, i.e. still first ascending but tied with other text) or a plain
`str()` comparison that puts `100` before `9`.

---

## T24 — Is `_sort` validated when `_sort_desc` also wins?

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. Both parameters are validated; `?_sort=bogus&_sort_desc=name` is a `400`.
2. Only the winning parameter is looked at; a losing `_sort` is ignored
   entirely, so `?_sort=bogus&_sort_desc=name` is a `200` sorted descending.

### Choice
Option 2. "`_sort_desc` wins" reads as *`_sort` does not apply*, and the
natural implementation resolves the winner first
(`if _sort_desc: ... elif _sort: ...`) and only then validates it. A parameter
with no effect on the response should not be able to reject the request.

### Risk: 35
Author most likely prefers: option 1 if their code validates every parameter it
parses before resolving precedence, making `?_sort=bogus&_sort_desc=name` a 400.

---

## T25 — `_rowid=hide` when the shape has no `rowid`

### Spec Text
> `_rowid=hide` removes `rowid`.
> Each toggle is valid only with value `hide`; any other value is `HTTP 400`.

### Alternatives
1. `_rowid=hide` is only meaningful with `_shape=objects`; sending it with the
   default `lists` shape is an error.
2. `_rowid=hide` is always accepted and is simply a no-op when no `rowid` is
   being emitted.

### Choice
Option 2. The only stated validity rule for the toggle is its *value*, and the
error table lists exactly one `_rowid` condition ("invalid `_rowid`/`_total`
value"). Removing something that is not there is not an error.

### Risk: 15
Author most likely prefers: same; divergence would be a 400 for
`?_shape=lists&_rowid=hide`.

---

## T26 — Repeats of parameters that are not control parameters

### Spec Text
> Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
> `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`.

### Alternatives
1. Any repeated query parameter is a 400.
2. Only the seven listed control parameters are checked; other repeated
   parameters are ignored as before.

### Choice
Option 2 — the rule enumerates the parameters it applies to, and unknown query
parameters have no meaning to this endpoint at all.

### Risk: 10
Author most likely prefers: same; divergence would be a blanket rejection of any
repeated parameter.

---

## T27 — Unknown dataset id together with invalid controls

### Spec Text
> `GET /datasets/<id>` accepts control parameters ...
> | control parameter repeated | 400 |

### Alternatives
1. Validate controls first: `/datasets/nope?_size=0` is a 400.
2. Resolve the dataset first: `/datasets/nope?_size=0` is a 404.

### Choice
Option 2. The id is part of the resource path, and the control parameters are
described as controls *on a dataset*; a request naming no dataset cannot be
answered regardless of its parameters.

### Risk: 15
Author most likely prefers: same (route-level lookup precedes query parsing);
divergence would be a 400 when both faults are present.

---

## T28 — Accepted integer syntax for `_size`/`_offset`

### Spec Text
> `_size` (positive integer, default `100`) ... `_offset` (non-negative
> integer, default `0`) ... Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Anything Python's `int()` accepts: `" 5 "`, `+5`, `007`, and Unicode digits
   such as `١٢`.
2. ASCII digits with an optional sign only: `+5` and `007` accepted, padded
   whitespace and Unicode digits rejected.
3. Bare ASCII digits only: `+5` rejected as well.

### Choice
Option 2, matching the ASCII-only, locale-independent numeric handling used for
type inference elsewhere in this service. `1.5`, `1e3`, `""` and `0` for `_size`
are rejected. No upper bound is imposed on `_size` — the spec caps it only by
"if it exceeds available rows, return all".

### Risk: 20
Author most likely prefers: option 1 (a bare `int(value)` in a `try/except`),
which differs only on exotic inputs — padded whitespace and non-ASCII digits,
which we reject and they would accept.

---

## T29 — Position of `rowid` inside an object row

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` ...

### Alternatives
1. `rowid` first, before the column keys.
2. `rowid` last.

### Choice
Option 1 — it reads as an identifier for the row, and the phrasing lists it
ahead of the data. JSON object key order is not semantic, so this is only
visible to a byte-level comparison of the response.

### Risk: 5
Author most likely prefers: same; any reasonable test compares parsed objects.

---

## T30 — Object rows when column names repeat or are empty

### Spec Text
> `_shape=objects`: `rows` is objects ... `rowid` is not in `columns`.

### Alternatives
1. Reject such datasets, or rename the duplicates for the objects shape.
2. Build the object by zipping columns with values, so a duplicate name keeps
   the last value and an empty name becomes the `""` key.

### Choice
Option 2. `columns` keeps reporting the header verbatim (T10); the objects
shape is just a re-keying of the same row, and inventing names would contradict
`columns`. Collapsing is inherent to a JSON object.

### Risk: 20
Author most likely prefers: same zip-based construction; divergence would be
disambiguated keys such as `name_2`.

---

## T31 — Sorting by `rowid`

### Spec Text
> `_sort=<column>` ... Empty values or unknown columns return `HTTP 400`.
> `rowid` is not in `columns`.

### Alternatives
1. `_sort=rowid` is allowed (it is a real, if virtual, field).
2. `_sort=rowid` is an unknown column and returns `400`.

### Choice
Option 2. Sorting is defined over `<column>`, and the spec says explicitly that
`rowid` is not in `columns`. Source order is already the default anyway.

### Risk: 20
Author most likely prefers: same; divergence would be a service that keeps rows
in a table with a real `rowid` and lets it be sorted on.
