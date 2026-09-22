# AMBIGUITIES

Numbered record of under-specified points in the `datagate` spec, the reading chosen,
and the risk that the spec author's own implementation (and hidden tests) read it differently.

---

## T1 — How the dataset id is derived from the source URL

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. A hash of the exact `source` string (e.g. sha256 hex, truncated).
2. A monotonically increasing counter memoised per URL (`ds1`, `ds2`, ...) — stable within
   one process run but not across runs.
3. A URL-safe encoding of the URL itself (base64/quoted URL).

### Choice
`sha256(source_string_utf8).hexdigest()[:16]`. The spec only constrains the *mapping* to be a
function of the exact URL string, never the id's format, so any pure function of the string
satisfies every stated property. A truncated sha256 is opaque, stable across process restarts,
and URL-safe. Tests can only reasonably assert "same URL → same endpoint, different URL →
different endpoint", which this satisfies. Note the spec says "the same `source` URL *string*",
so no URL normalisation (no case folding, no trailing-slash or query-order canonicalisation) is
applied: two strings that differ textually may map to different ids.

### Risk: 5
Author most likely prefers: some other opaque hash/id format, but any test asserting a literal id
value would be testing an unspecified detail, so equality/stability assertions should pass either way.

---

## T2 — What counts as an "Invalid URL" (400) versus "unreachable" (404)

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Only syntactically broken strings are invalid (`"not a url"`, `"http://"`, `""`); any
   parseable URL with a scheme + host is "valid" and a failure to fetch it is 404.
2. Additionally restrict the scheme to `http`/`https`: `file:///etc/passwd`, `ftp://h/f.csv`,
   `javascript:...` are 400 Invalid URL.
3. Treat non-http schemes as fetchable (actually opening `file://`) and 404 when missing.

### Choice
Alternative 2. `source` is documented as "URL of the *remote* CSV file" and the error table
pairs "unreachable or remote HTTP error" with network retrieval, which implies HTTP(S)
retrieval semantics. A URL that this service can never retrieve over HTTP is best reported as
an invalid *input*, not as a missing *remote resource* — and it also avoids turning `/convert`
into a local-file/SSRF read primitive. A URL is valid iff it parses, has scheme in
{http, https}, and has a non-empty host.

### Risk: 25
Author most likely prefers: the same 400 for non-http schemes, but a host-less URL such as
`http:///x.csv` or a bare `example.com/x.csv` could be classified as 404 (attempted fetch failure)
in their implementation.

---

## T3 — Numeric coercion: which strings become JSON numbers

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Naive `int(v)` then `float(v)`: accepts `007` → 7, `1e5` → 100000.0, `nan`/`inf`,
   `+5`, underscores (`1_000` is a valid Python int literal!).
2. A strict decimal regex: optional sign, digits, optional single `.`-fraction — rejecting
   `nan`, `inf`, `1_000`, and hex; accepting `007` → 7.
3. Same as 2 but also keeping leading-zero values (`007`, `01234`) as text on the grounds that
   they are identifiers (zip codes, product codes) whose zeros must survive.

### Choice
Alternative 2, plus scientific notation (`1e5`, `2.5E-3`) accepted as decimals. Rationale:
`float("nan")`/`float("inf")` produce values that are **not valid JSON**, so a conforming
implementation cannot be using bare `float()` without a guard; `1_000` and `0x1f` are Python
literal quirks that no reader of the spec would call "integers/decimals". Leading zeros are
still coerced (`007` → 7) because the spec's rule is a purely lexical one — "integers/decimals
are JSON numbers" — and `007` *is* an integer literal; carving out an identifier exception is a
heuristic the spec never mentions. Thousands separators (`1,234`) are never numbers (they are
also delimiter-ambiguous), currency (`$5`) and percentages (`50%`) stay text, and surrounding
whitespace is stripped before the test.

### Risk: 35
Author most likely prefers: preserving leading-zero strings such as `007`/`01234` as text
(Alternative 3), since zip-code-style columns are the classic fixture for this rule.

---

## T4 — Representation of empty cells

### Spec Text
> ```json
> "rows": [ ["<val1>", "<val2>", "..."] ]
> ```
> - Strings remain text.

### Alternatives
1. Empty string `""`.
2. JSON `null`.

### Choice
`""`. The CSV reader yields an empty string for an empty field, an empty field is a (degenerate)
string, and the spec's "Strings remain text" rule has no null case anywhere in the document. The
row shape in the example contains only strings and numbers.

### Risk: 20
Author most likely prefers: `null` for empty cells, if their implementation routes values through
a "parse or None" helper.

---

## T5 — Time-like values, and whether other date/time forms are covered

### Spec Text
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Only `HH:MM`-shaped values are protected, and the rule is really a warning against
   datetime coercion.
2. Dates (`2024-01-05`), datetimes and durations must also remain text.

### Choice
Both, via the general rule "anything that is not a plain integer/decimal literal stays text".
No date/time parsing is performed at all, so `08:30`, `9:15`, `12:00`, `2024-01-05`,
`2024-01-05T08:30:00Z` and `1:2:3` all round-trip as their exact source text. This satisfies the
stated examples and cannot over-coerce. Note `08:30` is *not* a decimal literal, so the leading
zero is preserved here regardless of the T3 choice.

### Risk: 3
Author most likely prefers: the same behaviour; the only divergence would be an implementation
that rewrites time text (e.g. `9:15` → `09:15`), which the word "remain" rules out.

---

## T6 — Whether the row limit is configurable via a query parameter

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> - Default row limit is 100.

### Alternatives
1. 100 is a hard cap; no parameter exists.
2. The word "Default" implies an override, most naturally `?limit=N` on `/datasets/<id>`.

### Choice
Support an optional `limit` query parameter (positive integer; a non-numeric or <1 value is a
400 error; values above the row count simply return all rows), defaulting to 100. The word
"Default" is otherwise meaningless, and the documented behaviour ("at most 100") is exactly
preserved when the parameter is absent — which is the only case the spec's examples exercise.

### Risk: 15
Author most likely prefers: the same `?limit=`; an implementation with a hard 100 cap would still
pass every no-parameter test, so divergence only shows if a hidden test sends `limit` explicitly
and expects it ignored.

### Resolved (Pagination, Sorting, and Response Controls)
> `_size` (positive integer, default `100`) limits returned rows.

The later spec section names the override parameter: it is `_size`, not `limit`, and it comes with
an `_offset` companion. The choice above is superseded — `limit` is no longer a control parameter
and is now treated as an ordinary unknown query parameter (ignored), because the spec's control
vocabulary is the underscore-prefixed set and nothing in it mentions `limit`. The "default 100"
behaviour is unchanged. Keeping `limit` as a second, undocumented alias would make
`?limit=abc` a 400 where the author's implementation almost certainly returns 200.

---

## T7 — What makes content "non-tabular" (400)

### Spec Text
> | Non-tabular content | 400 |
> - A valid file requires at least one header row and one data row.

### Alternatives
1. Only the row-count rule matters: <2 non-empty lines → 400, everything else is tabular.
2. Also reject content that is structurally another format (HTML page, JSON document, binary),
   even when it happens to span ≥2 lines.
3. Also reject single-column files (no delimiter present at all).

### Choice
Alternatives 1 + 2. A file must yield ≥1 header row and ≥1 data row after parsing, and content
that is recognisably HTML/XML (starts with `<`), JSON (starts with `{`/`[` and parses as JSON),
or binary (contains NUL bytes / is mostly non-printable) is rejected as non-tabular — a fetched
HTML error page is the archetypal "non-tabular content" case and it is usually multi-line, so the
row-count rule alone would not catch it. Single-column files are **accepted**: the spec says the
delimiter is inferred "if present", explicitly contemplating input with no delimiter.

### Risk: 30
Author most likely prefers: the same for HTML and empty/1-line input; the likeliest divergence is
single-column input, which an author checking "sniffer found no delimiter → non-tabular" would
reject with 400 where this implementation returns a 1-column dataset.

---

## T8 — Charset that is a real codec but fails to decode the bytes

### Spec Text
> | Unsupported or malformed `charset` | 400 |
> If `/convert` receives `charset`, use it to decode bytes.

### Alternatives
1. 400 covers only unknown/garbage codec names (`charset=klingon`, `charset=`); a decode failure
   with a real codec is repaired by replacing undecodable bytes.
2. 400 covers both: an unknown codec name *and* a real codec that raises `UnicodeDecodeError`
   on this content (e.g. `charset=utf-8` against Latin-1 bytes).

### Choice
Alternative 2, strict decoding. "malformed" most naturally reads as "does not apply to this
payload", the client explicitly asked for that decoding, and silently emitting replacement
characters (U+FFFD) would put corrupt values in the dataset with a `200 ok`. A caller who wants
lenient behaviour can simply omit `charset` and get the detection path (which falls back to
latin-1 and therefore never fails).

### Risk: 30
Author most likely prefers: decoding with `errors="replace"` and returning 200, reserving 400 for
`LookupError` on the codec name alone.

---

## T9 — "detect unambiguous encoding from content, else latin-1"

### Spec Text
> If omitted, detect unambiguous encoding from content, else latin-1.

### Alternatives
1. Use a statistical detector (`chardet`/`charset-normalizer`) and accept its guess when
   confidence is high.
2. Deterministic rules only: a BOM is unambiguous; otherwise a successful strict UTF-8 decode is
   unambiguous (UTF-8 multi-byte sequences are self-validating); otherwise latin-1.

### Choice
Alternative 2. The Determinism section forbids fuzzy, version-dependent behaviour, and a
statistical detector's answer can change with library version. Order: UTF-8/UTF-16/UTF-32 BOM →
that codec (BOM stripped); else strict UTF-8 → utf-8 (pure ASCII is a subset, so ASCII files
decode as utf-8 identically); else latin-1, which never fails. This is exactly "unambiguous,
else latin-1".

### Risk: 15
Author most likely prefers: the same UTF-8-then-latin-1 ladder; a detector-based implementation
would only differ on content where a detector confidently picks cp1252/utf-16-without-BOM.

---

## T10 — Delimiter inference algorithm

### Spec Text
> Delimiter must be inferred from input, if present; minimum supported delimiters are `,`, `;`,
> and `\t`.

### Alternatives
1. `csv.Sniffer().sniff(sample, delimiters=",;\t")`, with a fallback when it raises.
2. Explicit scoring: for each candidate, parse the sample with the `csv` module and prefer the
   candidate that yields the most columns with a consistent count across lines.

### Choice
Alternative 2, with ties broken in the fixed order `,`, `;`, `\t`. `csv.Sniffer` is heuristic,
raises on perfectly reasonable input (e.g. single-column files), and its behaviour has shifted
between CPython versions — a poor fit for the Determinism section. Scoring with the real `csv`
parser correctly ignores delimiter characters that appear *inside quoted fields*. If no candidate
yields ≥2 consistent columns, the file is treated as single-column (delimiter `,`), per T7.

### Risk: 20
Author most likely prefers: `csv.Sniffer`. Divergence appears on adversarial input — e.g. a
comma-delimited file whose text fields contain unquoted semicolons — where the two approaches can
pick different delimiters.

---

## T11 — Ragged rows (field count ≠ header count)

### Spec Text
> The endpoint returns stored rows and columns, in source order.
> `columns` and each row follow source column order.

### Alternatives
1. Normalise every row to `len(columns)`: pad short rows with `""`, truncate extra fields.
2. Emit rows exactly as parsed, so row lengths vary.
3. Reject ragged files as non-tabular (400).

### Choice
Alternative 1. The response contract pairs `columns` with positional `rows`, which is only
coherent if every row has the column count; padding/truncating keeps the positional mapping
intact and preserves source order. Rejecting outright (3) is too strict — the spec's only
validity rule is "one header row and one data row".

### Risk: 25
Author most likely prefers: padding short rows the same way, but *keeping* surplus fields
(a plain `csv.reader` pass-through) rather than truncating them.

---

## T12 — Repeat `/convert` on a URL whose content has changed

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Cache: the first conversion wins; later calls return the endpoint without re-fetching.
2. Re-fetch every time and overwrite the stored dataset (id unchanged).

### Choice
Alternative 2. The spec pins the *endpoint*, not the payload, and `/convert` is described as
ingestion — a caller re-invoking it is asking for a refresh. Re-fetching also means the documented
error statuses (404 unreachable, 400 non-tabular) keep applying on every call rather than being
masked by a cache.

### Risk: 10
Author most likely prefers: the same; a caching implementation differs only under a test that
serves changed content for one URL twice.

### Resolved by the "Caching and Cache Controls" section
Superseded. The spec now states that "`/convert` caches results by default" and that repeated
requests for the same URL "can return the cached dataset id without re-downloading", which is
Alternative 1. Alternative 2 survives only as the `CACHE_ENABLED=0` mode and as the per-request
`force` bypass. The implementation was changed accordingly; see [[T63]] for the strength given to
"can", and [[T60]]/[[T61]] for the `force` flag.

---

## T13 — Wrong HTTP method on a known path

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `405 Method Not Allowed` with the JSON error envelope.
2. `404` — treating "not a GET route" as an unknown route.

### Choice
405 with the JSON envelope. The spec defines both endpoints as `GET` and says nothing about
other methods; 405 is the correct HTTP semantic for a known path with an unsupported method,
and the "unknown routes → 404" sentence is about *paths*. Either way the response is JSON with
`"ok": false`, which is the part the spec actually mandates.

### Risk: 25
Author most likely prefers: 405 as well, but a minimal implementation that routes only GET could
return 404 (or Flask's default HTML 405) for `POST /convert`.

---

## T14 — Which CORS headers, and on which responses

### Spec Text
> Include CORS headers for browser access.

### Alternatives
1. `Access-Control-Allow-Origin: *` on success responses only.
2. On every response including errors, plus `Access-Control-Allow-Methods`/`-Headers` and an
   `OPTIONS` preflight handler.

### Choice
Alternative 2 — `Access-Control-Allow-Origin: *` on all responses (2xx, 4xx, and preflight),
with `Allow-Methods: GET, OPTIONS` and `Allow-Headers: *`. "For browser access" means a browser
must be able to read the response; a JS client that cannot read the error body would be unable to
surface the documented error messages. Credentials are not supported, so `*` is safe.

### Risk: 8
Author most likely prefers: the same; the only likely gap is missing CORS headers on error
responses.

---

## T15 — Duplicate or blank header names

### Spec Text
> `"columns": ["<col1>", "<col2>", "..."]`

### Alternatives
1. Pass header cells through verbatim, duplicates and blanks included.
2. De-duplicate/rename (`a`, `a_2`) or synthesise names for blanks (`column_3`).

### Choice
Verbatim (whitespace-stripped only). `columns` is described as the source header in source order;
renaming would break the "source order"/round-trip expectation, and `rows` are positional lists,
not objects, so duplicate names are harmless.

### Risk: 12
Author most likely prefers: the same pass-through; a `DictReader`-based implementation would
collapse duplicate columns.

---

## T16 — Precedence when several error conditions hold at once

### Spec Text
> | Missing `source` | 400 | ... | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Validate in table order: missing `source` → invalid URL → charset → fetch → parse.
2. Fetch first, then validate charset.

### Choice
Table order (Alternative 1): cheap, purely local input validation (presence, URL shape, codec
name) runs before any network I/O, so e.g. `?source=<unreachable>&charset=bogus` is a 400, not a
404. This matches the table's own ordering and avoids a network round-trip for input that can
never succeed.

### Risk: 18
Author most likely prefers: the same, though an implementation that decodes only after fetching
would return 404 for the combined unreachable-URL + bad-charset case.

### Annotation (multi-format spec)
Narrowed by the later rule "`charset` applies and validates only for text CSV sources": charset is
now resolved after the bytes are classified, so a bad `charset` no longer rejects an `.xls`/`.xlsx`
source. The precedence above still holds when the format never becomes known — a bad `charset`
with an unreachable `source` is still a 400. See T47.

---

## T17 — Blank lines, trailing newline, and BOM in the header

### Spec Text
> A valid file requires at least one header row and one data row.

### Alternatives
1. Count raw lines, so a trailing newline or an interior blank line becomes a row (possibly `[""]`).
2. Skip wholly empty rows before applying the rule and before storing.

### Choice
Alternative 2: rows that are entirely empty (no fields, or every field blank after stripping) are
dropped during parsing, so a trailing newline does not create a phantom row and a header +
blank line + data row is valid with one data row. A UTF-8 BOM is stripped from the first header
cell so `columns[0]` is not `"﻿id"`.

### Risk: 12
Author most likely prefers: the same for the trailing newline (near-universal), with possible
divergence on an interior blank line inside the data.

---

## T18 — `query_ms` semantics

### Spec Text
> `"query_ms": 3.2` ... `query_ms` is present and non-negative.

### Alternatives
1. Time spent serving this `/datasets/<id>` request (query + serialisation).
2. Time spent ingesting the source at `/convert`.

### Choice
Alternative 1 — a JSON float, measured with a monotonic clock from the start of the dataset
lookup to just before serialisation, rounded to 3 decimals. The field lives in the dataset-query
response and is named for the query. A monotonic clock keeps it independent of wall-clock/timezone,
which the Determinism section requires ("No dependence on clock/locale/timezone beyond `query_ms`").

### Risk: 5
Author most likely prefers: the same; tests can only reasonably assert presence, numeric type, and
non-negativity.

---

## T19 — `charset` supplied as an empty string

### Spec Text
> | Parameter | Required | ... | `charset` | no | ... If omitted, detect ... |

### Alternatives
1. `?charset=` (present but empty) is equivalent to omitting it → detection path.
2. Empty is a malformed charset → 400.

### Choice
Alternative 2 (400). An empty codec name is not a codec; `codecs.lookup("")` raises, so
"unsupported or malformed `charset`" applies literally. Sending `charset=` is an explicit request
for an unnameable encoding, most often a client bug worth surfacing rather than silently ignoring.

### Risk: 35
Author most likely prefers: treating a falsy/empty query value as absent (a very common
`request.args.get("charset")`-then-`if charset:` shape), i.e. 200 via the detection path.

---

## T20 — Where `total` sits, and which responses carry it

### Spec Text
> Responses include integer `total` for the row count before pagination.

### Alternatives
1. `total` is a top-level key of the `GET /datasets/<id>` success envelope, alongside
   `ok`/`columns`/`rows`/`query_ms`.
2. `total` is nested (e.g. under a `meta` object) or accompanied by siblings such as
   `next_url`/`truncated`.
3. "Responses" includes `/convert` and error responses too.

### Choice
Alternative 1: a single top-level `"total": <int>` on dataset-query success responses only. The
section is titled "Pagination, Sorting, and Response Controls" and scoped in its first line to
`GET /datasets/<id>`; `/convert` returns only `{"ok", "endpoint"}` and has no rows to count. Error
responses stay exactly `{"ok": false, "error": ...}` because the error table spells that body out
verbatim, leaving no room for a `total`. `total` is the count of stored data rows — it ignores
`_size`, `_offset` and sorting alike ("before pagination"), and the header row is not a data row so
it is not counted.

### Risk: 5
Author most likely prefers: the same top-level integer key.

---

## T21 — What exactly counts as a valid `_size`/`_offset` literal

### Spec Text
> `_size` (positive integer, default `100`) ... `_offset` (non-negative integer, default `0`) ...
> Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Python's `int()` with `try/except`: accepts `"+5"`, `" 5 "`, and the Python-literal quirks
   `"1_0"` (→ 10) and unicode digits; rejects `"5.0"`, `"1e3"`, `""`.
2. A strict decimal-integer regex `^[+-]?[0-9]+$` after stripping whitespace.
3. Lenient coercion: accept `"5.0"` / `"1e3"` by going through `float()`, or truncate a decimal.
4. Treat an empty value (`?_size=`) as absent and fall back to the default.

### Choice
Alternative 2 (which agrees with 1 on everything a test is likely to send, and additionally rejects
the `1_0`/unicode-digit quirks). `"5.0"`, `"1e3"`, `"3px"`, `"1,000"` and `"0x10"` are not integers
and are 400s; `_size=0` and any negative `_size` are 400 (it must be *positive*); `_offset=0` is
valid and negatives are 400. An empty value is a 400 rather than a fallback to the default
(Alternative 4): the parameter is present, and the empty string is not an integer — the same
reading applied to empty `_sort`, which the spec itself makes an explicit 400.

### Risk: 20
Author most likely prefers: the same for every non-numeric and out-of-range case; the likeliest
divergence is `?_size=` (present but empty), which an `if raw:`-guarded implementation would
silently treat as the default and answer 200.

---

## T22 — `_offset` at or beyond the row count

### Spec Text
> `_offset` (non-negative integer, default `0`) skips that many rows before returning.
> If it exceeds available rows, return all.

### Alternatives
1. An offset past the end returns `rows: []` with `total` still the full count (HTTP 200).
2. An offset past the end is a 400 (out of range), by analogy with "invalid `_offset`".
3. The "if it exceeds available rows, return all" clause applies to `_offset` too, clamping the
   offset so the last page is returned.

### Choice
Alternative 1. The "return all" sentence sits in the `_size` paragraph and is about `_size`; the
only `_offset` errors the table names are "not a non-negative integer", and 5 is a perfectly good
non-negative integer over a 3-row dataset. Slicing past the end of a list yielding an empty page is
the universal behaviour of every pagination API, and it keeps `total` meaningful as the signal that
the client has walked off the end.

### Risk: 8
Author most likely prefers: the same empty page (`rows[offset:offset+size]` falls out of the
natural implementation).

---

## T23 — Ordering across mixed cell types, and descending stability

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`. ... Sorting is stable and applied before
> pagination.

### Alternatives
1. Sort the raw coerced values directly (`sorted(rows, key=row[i])`), which raises `TypeError`
   when a column mixes numbers and text — a 500.
2. A total ordering with a type rank: numbers first (numerically), then text (lexicographically),
   with empty cells as the lowest text.
3. Stringify everything and compare as text, so `100` sorts before `9`.
4. Descending implemented as "sort ascending, then reverse the list", which inverts the order of
   tied rows.

### Choice
Alternative 2, with descending implemented as `reverse=True` (not a post-hoc list reversal). A
numeric column must sort numerically — `[2, 9, 10, 100]`, not `[10, 100, 2, 9]` — which rules out
3, and an unsortable column must not become a 500, which rules out 1. "Sorting is stable" is stated
unconditionally, so it must hold for `_sort_desc` as well: rows tied on the key keep their source
order in both directions, which is exactly `sorted(..., reverse=True)` and not `sorted(...)[::-1]`.

### Risk: 30
Author most likely prefers: the same numeric-then-text ordering for homogeneous columns (the only
kind a fixture is likely to sort); the real divergence risks are a mixed-type column (their
implementation may 500, or may stringify) and tie order under `_sort_desc` if they reverse the
sorted list.

---

## T24 — How a sort column name is matched

### Spec Text
> `_sort=<column>` ... Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. Exact, case-sensitive string equality against the entries of `columns`.
2. Case-insensitive and/or whitespace-tolerant matching.
3. Also accept a positional column index (`_sort=0`).

### Choice
Alternative 1. `columns` is the verbatim source header (see T15) and the spec gives no matching
rule beyond "unknown columns", so the only defensible reading is membership in that list —
`_sort=NAME` against a `name` column is an unknown column and a 400. When the header repeats a
name, the first matching column wins.

### Risk: 10
Author most likely prefers: the same `if col not in columns: 400` check.

---

## T25 — Validating `_sort` when `_sort_desc` overrides it

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. Validate every sort parameter that is present, even the losing one:
   `?_sort=bogus&_sort_desc=name` → 400.
2. Pick the winner first and validate only that one: `?_sort=bogus&_sort_desc=name` → 200,
   sorted descending by `name`.

### Choice
Alternative 1. The 400 rule is written about `_sort`/`_sort_desc` as a pair and the error table
lists "`_sort`/`_sort_desc` unknown column" without qualification, so a bad column name is an
invalid request regardless of which parameter it rode in on. "`_sort_desc` wins" reads as a
tie-break about *ordering*, not a licence to ignore a malformed sibling — silently discarding a
misspelled `_sort` would hide a client bug.

### Risk: 40
Author most likely prefers: Alternative 2 — an implementation that computes
`col = args.get("_sort_desc") or args.get("_sort")` before validating never looks at the loser.

---

## T26 — `_rowid=hide` when there is no `rowid` to hide

### Spec Text
> `_shape=lists` (default): `rows` is arrays.
> `_rowid=hide` removes `rowid`.

### Alternatives
1. `_rowid=hide` is a no-op in the `lists` shape (200), since rows are arrays and never carry a
   rowid.
2. `_rowid` is only meaningful with `_shape=objects`, so combining it with `lists` is a 400.
3. `lists` rows should carry a leading rowid element unless hidden.

### Choice
Alternative 1. The spec attaches `rowid` exclusively to the `objects` shape ("`rows` is objects
**and includes** `rowid`"), so a `lists` response has nothing to remove and the toggle simply has
no effect; the error table lists only "invalid `_rowid`/`_total` **value**" as a 400, never an
invalid combination. Alternative 3 is ruled out by `rowid` not being in `columns`, which would
otherwise misalign every row from its columns. The *value* is still validated in both shapes, so
`?_shape=lists&_rowid=show` is a 400.

### Risk: 12
Author most likely prefers: the same no-op; a validate-value-then-apply implementation gets this
for free.

---

## T27 — Scope of the "repeated control parameter" rule, and object-row collisions

### Spec Text
> Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`, `_sort_desc`, `_rowid`,
> `_total`) is `HTTP 400`.
> `_shape=objects`: `rows` is objects and includes `rowid` ...

### Alternatives
1. Only the seven listed names are policed; other repeated query parameters (`?foo=1&foo=2`) are
   ignored, as are unknown parameters generally.
2. Any repeated query parameter is a 400.
3. A repeat is only an error when the two values differ.

### Choice
Alternative 1: the rule is explicitly enumerated ("control parameter (`_size`, ... `_total`)"), and
the spec never asks for unknown-parameter rejection anywhere. Repetition is an error even when the
values are identical (`?_size=2&_size=2`) — the spec says "repeated", not "conflicting" — and
`?_sort=x&_sort_desc=y` is two different parameters, not a repeat, since the spec explicitly
defines what happens when both are present. Relatedly, for `_shape=objects` each row is built by
zipping `columns` with the row values, so a duplicated header name keeps its last column and a
source column literally named `rowid` is overwritten by the synthesised rowid (the spec pins
`rowid`'s meaning but says nothing about the collision).

### Risk: 15
Author most likely prefers: the same enumerated check; the likeliest divergence is an
implementation that only rejects repeats with differing values.

---

## T28 — Unknown dataset id combined with an invalid control parameter

### Spec Text
> If `<id>` is unknown, return `HTTP 404`.
> Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Resolve the dataset first: `GET /datasets/<unknown>?_size=0` → 404.
2. Validate query parameters first: → 400.

### Choice
Alternative 1. The dataset is the resource being addressed, and a handler naturally looks it up
before interpreting the query that applies *to it* — `_sort` validation is not even possible until
the dataset's `columns` are known, so at least part of control validation must come second. Among
the 400s themselves, the order is: repeated parameters first (a cheap check over all seven names),
then the error table's own order — `_size`, `_offset`, `_shape`, `_rowid`/`_total`, then the sort
columns.

### Risk: 20
Author most likely prefers: the same 404-first ordering; the ordering *among* competing 400s is
the weaker part of this choice, since a hidden test sending two bad parameters at once would pin a
specific message.

---

## T29 — Splitting `<column>__<comparator>` when the key contains more than one `__`

### Spec Text
> `GET /datasets/<id>` accepts filter params in this form:
> ```
> <column>__<comparator>=<value>
> ```

### Alternatives
1. Split on the **last** `__` (`rsplit("__", 1)`): the column part may itself contain `__`, so
   `user__id__less=5` filters the column `user__id` with `less`.
2. Split on the **first** `__` (`split("__", 1)`): `user__id__less=5` is column `user`,
   comparator `id__less` → invalid comparator (400).
3. Reject any key with more than one `__` outright (400).

### Choice
Split on the last `__`. The comparator is always the final segment and is drawn from a closed
four-word vocabulary, while the column name is arbitrary text taken from the CSV header — so the
only split that can ever address a column containing `__` is the rightmost one. Under readings 2
and 3 such a column is permanently unfilterable, which the spec never hints at. For every key
whose column part does *not* exist, all three readings still produce 400, so they differ only on
headers that literally contain `__`.

### Risk: 20
Author most likely prefers: the same rightmost split; the residual risk is an implementation that
does `split("__", 1)` and a fixture with a `__`-containing header.

---

## T30 — What `exact`/`contains` compare against once a cell has been coerced to a number

### Spec Text
> - `exact`: case-sensitive string equality.
> - `contains`: case-sensitive substring.

### Alternatives
1. Stringify the stored value (`str(cell)`) and compare to the raw filter value, so numeric cells
   are filterable as text: `qty__exact=3` matches the stored integer `3`.
2. Only ever match cells that are stored as text; numeric cells never match a string comparator.
3. Compare against the *original* CSV text of the cell, kept alongside the coerced value, so
   `price__exact=3.50` matches a cell written `3.50` (stored as `3.5`).

### Choice
Reading 1: compare `str(stored)` against the filter value. The spec presents the four comparators
as one uniform mechanism over any column and nowhere restricts `exact`/`contains` to text columns;
reading 2 would make `exact` useless on the numeric columns the earlier spec sections went to some
length to produce. Reading 3 requires retaining a second copy of every cell, which nothing in the
spec asks for. The visible consequence is that number formatting is normalised before comparison:
a cell written `3.50` stringifies as `3.5`, and `1e3` as `1000.0`.

### Risk: 25
Author most likely prefers: the same `str(cell)` comparison; the residual risk is a fixture that
round-trips a differently-formatted numeric literal (`3.50`, `007`, `1e3`) through `exact`.

---

## T31 — Which message wins when a filter key is both an unknown column and an invalid comparator

### Spec Text
> | Invalid comparator (`exact|contains|less|greater`) | 400 | `{"ok": false, "error": "<message>"}` |
> | Unknown filter column | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. Validate the comparator first, so `nosuch__nope=1` reports an invalid comparator.
2. Validate the column first, so the same key reports an unknown column.

### Choice
Comparator first, matching the order of the rows in the spec's own error table. Both readings
return `400` with the same envelope shape and the message text is explicitly unspecified
(`"<message>"`), so this is observable only to a test that greps the message body.

### Risk: 5
Author most likely prefers: either order; a hidden test would have to assert on free-text message
content to distinguish them.

---

## T32 — Keys that begin with `_` *and* contain `__`

### Spec Text
> Control params (names beginning with `_`) are not filters.

### Alternatives
1. The `_` prefix wins unconditionally: `_sort__exact=name` is a control-shaped name, not a filter,
   and is ignored (no 400).
2. The `__` shape wins: `_sort__exact` is parsed as column `_sort` + comparator `exact`, giving an
   unknown-column 400.

### Choice
Reading 1. The spec states the exclusion flatly and without qualification — *names beginning with
`_`* are not filters — and states it before introducing any filter parsing, so the prefix test is
the outer gate. An unknown `_`-prefixed parameter is already ignored by the existing control
handling (see [[T27]]), and this keeps that behaviour uniform.

### Risk: 12
Author most likely prefers: the same prefix-first gate; the residual risk is an implementation that
tests for `__` before testing for the `_` prefix.

---

## T33 — `nan` / `inf` as a numeric filter value or stored value

### Spec Text
> - `less`: numeric strict less (`float` parse on stored and filter values).
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.
> Rows with non-numeric stored values are not matched for numeric comparators.

### Alternatives
1. Take "`float` parse" literally: whatever `float()` accepts is numeric, so `qty__less=nan` and
   `qty__less=inf` are valid filters (and `nan` simply matches nothing).
2. Accept only finite decimal literals, so `nan`/`inf` filter values are non-numeric → 400,
   consistent with the earlier ingestion rule that excludes them from numeric coercion.

### Choice
Reading 1, the literal one: the spec names the parse function (`float`) rather than a grammar, and
the phrase "non-numeric filter values" is most simply read as "values `float()` rejects". The
practical difference is tiny: `nan` compares false against everything, so only `inf`/`-inf` filter
values behave differently between the readings. Note this concerns only *filter* values — stored
cells never hold `nan`/`inf`, because ingestion keeps those literals as text (see [[T3]]), so they
are non-numeric stored values and are correctly not matched.

### Risk: 30
Author most likely prefers: reading 2, rejecting `nan`/`inf` as non-numeric filter values, if their
implementation reuses the ingestion-side numeric regex instead of calling `float()` directly.

---

## T34 — An empty column part or an empty comparator part

### Spec Text
> ```
> <column>__<comparator>=<value>
> ```
> | Invalid comparator (`exact|contains|less|greater`) | 400 |
> | Unknown filter column | 400 |

### Alternatives
1. `name__=x` has comparator `""` → invalid comparator (400). It is still a filter-shaped key
   because it contains `__`.
2. Treat a key with an empty part as not matching the filter form at all, and ignore it under
   "Params without `_` and without `__` are ignored".

### Choice
Reading 1 for the empty *comparator*: `name__=x` does contain `__`, so the "ignored" clause — which
is explicitly about params containing *no* `__` — does not reach it; it is a malformed filter rather
than a non-filter, and the error table already has a row for that defect. Silently ignoring a typo'd
filter would also return unfiltered rows, the least safe failure mode for this endpoint.

An empty *column* part cannot reach this rule at all: `__exact=x` necessarily begins with `_`, so
the control-prefix gate of [[T32]] claims it first and it is ignored rather than rejected. That
consequence is deliberate — it falls out of applying the two rules in the order the spec states
them — and it is the only point where the two entries interact.

### Risk: 15
Author most likely prefers: the same 400 for `name__=x`; the residual risk is an implementation that
requires both parts to be non-empty before classifying the key as a filter at all, or one that tests
for `__` before the `_` prefix and so 400s on `__exact=x`.

---

## T35 — What "query timeout" means, and how long it is

### Spec Text
> - Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. A wall-clock budget for evaluating one `GET /datasets/<id>` request, checked while scanning
   rows; exceeding it aborts with 400.
2. A budget covering only the filter-matching phase.
3. A hard cap on the number of rows scanned rather than on time.

### Choice
Reading 1: a deadline established when the request starts and checked as rows are scanned, filtered
and sorted, with a default budget of 5 seconds exposed as the Flask config key
`DATAGATE_QUERY_TIMEOUT` (seconds) so it is testable. The spec gives no duration, no configuration
parameter and no mechanism, and lists the timeout among *filter* behaviours, which implies the cost
being guarded is the per-row scan. The default is set far above anything the in-memory datasets of
this service can reach, so the branch never fires in normal operation — which is also why no hidden
fixture can plausibly depend on a particular duration.

### Risk: 35
Author most likely prefers: the same "never fires in practice" guard; the residual risk is that
their implementation exposes the budget through a different knob (a `_timeout` control param, an
environment variable, or a row-count cap) that a fixture pokes directly.

---

## T36 — What makes two filter keys "duplicates"

### Spec Text
> - Duplicate filter keys are invalid (`HTTP 400`).

### Alternatives
1. The same full key (column *and* comparator) appears more than once:
   `qty__less=5&qty__less=9` is a 400, while `qty__less=9&qty__greater=1` is a legal AND.
2. The same *column* appears more than once under any comparator, so `qty__less=9&qty__greater=1`
   is also a 400.

### Choice
Reading 1. The spec says duplicate filter *keys*, and the key is the whole `<column>__<comparator>`
string. Reading 2 would also contradict the neighbouring "Multiple filters are ANDed" — a bounded
range on one column is the canonical reason to AND two filters, and forbidding it would leave AND
with almost no use. Repeated *control* params remain governed by the existing rule (see [[T27]]).

### Risk: 10
Author most likely prefers: the same key-level reading, since a range query is the obvious use of
AND.

---

## T37 — Ordering between control-parameter errors and filter errors

### Spec Text
> | Invalid comparator ... | 400 |
> | Unknown filter column | 400 |

### Alternatives
1. Validate control params first, then filters.
2. Validate filters first, then control params.

### Choice
Controls first, extending the existing precedence chain (unknown dataset 404 before any parameter
validation, per [[T16]] and [[T28]]). Every candidate error here is a 400 with an unspecified
message, so the two readings differ only in message text when a request is malformed in both ways
at once.

### Risk: 3
Author most likely prefers: either order; only the message text can distinguish them.

## T38 — Whether the export CSV carries a header row

### Spec Text
> `GET /datasets/<id>/export` returns CSV bytes with: ... The CSV uses source column order

### Alternatives
1. The first line is a header row of the source column names; data rows follow.
2. Data rows only — "column order" constrains field order without implying a header line.

### Choice
Alternative 1. The export is the CSV form of a dataset that was itself ingested from a
header-bearing table, and "uses source column order" is a statement about the columns of that
CSV; a downloaded `<id>.csv` with no header would not round-trip back through `/convert`, which
requires "header + at least one data row". A header also makes the "columns follow source column
order" determinism rule observable in the bytes.

### Risk: 8
Author most likely prefers: the same (header + rows).

---

## T39 — Whether `/export` applies the default page size

### Spec Text
> The CSV uses source column order and applies the same filters, sort, and pagination as `/datasets/<id>`.

### Alternatives
1. "The same pagination" includes the same defaults: `_size` defaults to 100, so an unparameterised
   export of a 150-row dataset contains 100 rows.
2. Pagination params are honoured when given, but an export with no params dumps the whole dataset
   (an export is a download, so "all rows" is the useful default).

### Choice
Alternative 1. The sentence equates export's control handling with `/datasets/<id>`'s, and the
default page size is part of that endpoint's pagination, not a separate concept. Reusing one
control parser is also the only reading that keeps `_size`/`_offset` semantics literally "the
same"; a client wanting everything can pass `_size`.

### Risk: 30
Author most likely prefers: the same (shared control parsing), but an implementation that treats a
download as unpaginated-by-default would emit all 150 rows for a bare `/export`.

---

## T40 — Whether `_shape`/`_rowid`/`_total` are still *validated* on `/export`

### Spec Text
> `_shape`, `_rowid`, and `_total` do not affect CSV output.

### Alternatives
1. They are parsed and validated as on `/datasets/<id>` (so `_shape=bogus` is a 400) but have no
   effect on the bytes.
2. They are ignored entirely, so any value — valid or not — is accepted silently.

### Choice
Alternative 1. The sentence is about *output*, not about validation, and the natural
implementation shares one control parser between the two endpoints. Keeping validation means one
consistent contract: a request that would be rejected as JSON is rejected as CSV.

### Risk: 30
Author most likely prefers: the same if the parser is shared; an implementation that reads only
`_size`/`_offset`/`_sort*` in the export path would return 200 for `_shape=bogus`. Tests are far
more likely to probe `_shape=objects` (identical bytes either way) than a malformed value.

---

## T41 — Exact `Content-Type` of the export response

### Spec Text
> - `Content-Type: text/csv`

### Alternatives
1. Literally `text/csv`, with no parameters.
2. `text/csv; charset=utf-8` (what most frameworks append for a text type).

### Choice
Alternative 1: the header is set to exactly `text/csv`. The spec quotes the header value in full,
and a test asserting equality with the quoted string only passes for the bare form, while a test
that splits on `;` or uses `startswith` passes for both. The body is still UTF-8 encoded.

### Risk: 12
Author most likely prefers: the bare `text/csv`; a Flask implementation using
`mimetype="text/csv"` would emit `text/csv; charset=utf-8`, which only breaks a strict-equality
test in the other direction.

---

## T42 — Errors raised by `/export`

### Spec Text
> - all errors use the standard JSON envelope

### Alternatives
1. Export errors (unknown id, bad filter, bad control) answer with the JSON envelope and the usual
   status, i.e. the response is not CSV at all.
2. Errors are rendered as a CSV error line, since the endpoint's content type is CSV.

### Choice
Alternative 1. "All errors" is unqualified and the envelope is the service-wide contract; the
`Content-Type: text/csv`/`Content-Disposition` pair describes the *success* response. Unknown
dataset id stays 404, invalid filter/control stays 400, both as `{"ok": false, "error": ...}`.

### Risk: 5
Author most likely prefers: the same.

---

## T43 — What an uploaded dataset's id is derived from

### Spec Text
> Re-uploading the same file bytes yields the same dataset id.

### Alternatives
1. `sha256(file_bytes)[:16]` — identity is the bytes alone; filename, field name, and `charset`
   are irrelevant.
2. A hash of bytes *plus* filename and/or `charset`, so the same bytes decoded differently are
   different datasets.
3. A random/sequential id memoised per byte string.

### Choice
Alternative 1, matching the URL-keyed scheme of T1 (same construction, different key space). The
spec ties identity to "the same file bytes" and mentions nothing else; charset is a decoding
instruction, not part of the document's identity. A consequence: uploading identical bytes with a
different `charset` re-ingests and overwrites the same id, and the later upload's decoding wins.

### Risk: 15
Author most likely prefers: the same; an implementation that folded `charset` into the key would
diverge only on the (unlikely) same-bytes-different-charset fixture.

---

## T44 — Both `file` and `attachment` present

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`

### Alternatives
1. `file` wins; `attachment` is the fallback.
2. Sending both is ambiguous and a 400.
3. Both are ingested as two datasets.

### Choice
Alternative 1. "or" here names two accepted spellings of one field, not an exclusive-or
constraint; the error table makes only the *absence of both* an error, so presence of both cannot
be one. `file` is named first, so it is preferred.

### Risk: 12
Author most likely prefers: the same (`request.files.get("file") or request.files.get("attachment")`
is the idiomatic shape); a strict implementation could 400.

---

## T45 — What makes a request "non-multipart" (415)

### Spec Text
> - non-multipart request: `HTTP 415`
> - malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. Decided by the request's Content-Type: anything whose media type is not `multipart/form-data`
   (including a missing Content-Type, `application/json`, `text/csv`, and
   `application/x-www-form-urlencoded`) is 415; a `multipart/form-data` declaration that then
   fails to parse is "malformed multipart", 400.
2. Decided by whether any parts were actually parsed, so an unparseable multipart body is also 415.

### Choice
Alternative 1. The spec distinguishes "non-multipart" (415, wrong media type — exactly what 415
means) from "malformed multipart" (400, right media type, bad bytes), which only makes sense if
the media type header is what separates the two. A `multipart/form-data` header with no
`boundary` parameter is therefore 400, not 415: the type is right, the body cannot be parsed.

### Risk: 20
Author most likely prefers: the same; the boundary-less and empty-body cases are where an
implementation that inspects `request.files` first could answer 415 instead.

---

## T46 — A `file`/`attachment` part sent without a filename

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`
> - missing file field: `HTTP 400`

### Alternatives
1. Only true file parts (those with a `filename`) count; a same-named plain text part means the
   file field is missing → 400.
2. A plain text part named `file`/`attachment` is accepted, its value taken as the document.

### Choice
Alternative 2, as a superset of 1: the file parts are consulted first, and a plain form field of
the same name is accepted as a fallback (its text re-encoded as UTF-8). Real clients (`curl -F`,
`requests`' `files=`, the werkzeug test client) always send a filename, so this only widens what
succeeds and never turns a passing case into a failure. `charset` cannot be honoured faithfully
for such a part, since the server only sees the already-decoded text.

### Risk: 10
Author most likely prefers: accepting file parts only; the two readings differ only on a fixture
that deliberately posts the CSV as a non-file part, which would be 400 there and 200 here.

---

## T47 — When `charset` is validated, now that it "validates only for text CSV sources"

### Spec Text
> `charset` applies and validates only for text CSV sources.

### Alternatives
1. Validate `charset` eagerly, before the bytes are known (T16's "local validation first"), so a
   bad charset is a 400 even for an `.xlsx` source.
2. Validate lazily, after the bytes are in hand and the format is known: a bad charset is a 400
   only when the payload is text CSV. A source that could not be fetched at all then reports the
   fetch failure (404).
3. Lazy, but with the eager 400 preserved whenever the format never becomes known (fetch failed).

### Choice
Alternative 3. The new sentence is explicit that a spreadsheet must not be rejected for a charset
it does not use, which rules out 1. But T16's precedence rule — purely local, client-visible input
errors beat remote failures — is still the better answer when there is no format to classify, so a
bad `charset` with an unreachable `source` stays a 400. In short: charset errors are suppressed
only when the fetched bytes turn out to be a workbook.

### Risk: 25
Author most likely prefers: plain Alternative 2 (validate inside the CSV branch only), which would
return 404 rather than 400 for unreachable-source + bad-charset. See T16, whose choice this
entry narrows.

---

## T48 — How spreadsheet cells map to JSON values

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> Formula/computed-cell behavior is not required.

### Alternatives
1. Mirror the CSV type rules: numbers stay JSON numbers, text stays text, empty cells become `""`.
   Integral floats (`3.0`, which is how both `.xls` and many `.xlsx` cells store `3`) become `3`.
2. Stringify every cell and re-run the CSV coercion on the text.
3. Pass library values straight through (so `.xls` yields `3.0` where `.xlsx` yields `3`, and dates
   yield serial numbers).

### Choice
Alternative 1. The dataset shape must not depend on which workbook format the same table arrived
in, and `xlrd` reports every `.xls` number as a float while `openpyxl` reports integers as `int` —
so integral floats are narrowed to `int`, which is also what the CSV path produces for `3`.
Dates/times are emitted as ISO-8601 strings (a serial number would be meaningless), booleans as
JSON booleans, error cells and blanks as `""`. Formula cells use the workbook's cached value when
one exists and `""` otherwise, which the spec explicitly does not constrain.

### Risk: 45
Author most likely prefers: a plainer pass-through (Alternative 3), where an `.xls` fixture's
integer column comes back as `3.0` — a very common outcome of `xlrd`'s float-only number type.
Date handling is the other likely divergence.

---

## T49 — Sheet extent: blank rows, blank columns, and ragged rows

### Spec Text
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.
> spreadsheet columns preserve source order.

### Alternatives
1. Take the sheet's reported dimensions verbatim, so trailing empty rows become rows of `""` and
   trailing empty columns become unnamed columns.
2. Trim wholly-empty trailing rows and columns, use row 1 as the header, and pad/truncate data
   rows to the header width (the CSV path's ragged-row rule, T11).

### Choice
Alternative 2. Spreadsheet applications routinely leave formatted-but-empty cells that inflate the
used range, and reading those back as data rows would mean a workbook with one data row could
report dozens. Trimming also makes "header + at least one data row" test the table a human sees.
Interior blank rows are preserved (they are data, however empty), matching the CSV path, which only
drops wholly-blank lines... and, like the CSV path, a wholly-blank interior line is dropped too.

### Risk: 25
Author most likely prefers: the same trimming (it is what `openpyxl`'s `iter_rows` plus an
"all None" filter yields); differences would show on fixtures with interior blank rows.

---

## T50 — How the format is recognised

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`. ... Unrecognized format: `HTTP 400`.

### Alternatives
1. By content sniffing: the ZIP magic plus an `xl/` member means `.xlsx`, the OLE2 compound-file
   magic means `.xls`, anything else is treated as text CSV and must parse as a table.
2. By the filename extension (upload) or URL suffix / `Content-Type` (convert).

### Choice
Alternative 1. The spec writes the formats as extensions but never says the extension is
authoritative, and `/convert` sources frequently have no useful suffix (a generated download URL)
while uploads may arrive as `blob`. Sniffing also gives "unrecognized format" a precise meaning:
bytes that are neither a readable workbook nor decodable tabular text. A ZIP or OLE2 container that
is not a workbook is a 400 rather than being force-parsed as CSV.

### Risk: 15
Author most likely prefers: the same, possibly with the extension as a hint; a fixture named
`.xlsx` that actually holds CSV bytes would ingest here and 400 there (or vice versa).

---

## T51 — Which sheet is "the first worksheet"

### Spec Text
> Only the first worksheet is ingested.
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. Index 0 in the workbook's stored sheet order, whether or not it is hidden, and whether or not it
   is the sheet the file opens on.
2. The first *visible* sheet, or the active sheet.
3. The first sheet that happens to be tabular.

### Choice
Alternative 1. "First" is positional, and the second sentence settles it: if a non-tabular first
sheet were skipped in favour of a later one, it could never produce the 400 the spec demands.

### Risk: 10
Author most likely prefers: the same (`wb.worksheets[0]` / `sheet_by_index(0)`); hidden-first-sheet
fixtures are the only likely divergence.

---

## T52 — Column names taken from a spreadsheet header row

### Spec Text
> The first sheet must be tabular (header + at least one data row)
> spreadsheet columns preserve source order.

### Alternatives
1. Each header cell is rendered as its display text (numbers/dates stringified, `None` → `""`) and
   surrounding whitespace stripped, exactly as the CSV path treats header cells.
2. Header cells keep their native types, so a column could be named `2024` (a JSON number).

### Choice
Alternative 1. Column names are keys — they appear in `_shape=objects` objects and in filter keys
like `<column>__exact`, both of which are strings — so a numeric header must become `"2024"`.
An integral numeric header is rendered without a trailing `.0` for the same reason as T48.

### Risk: 20
Author most likely prefers: the same; the divergence is the exact spelling of a numeric or
date-valued header cell.

---

## T53 — How values are rendered back into export CSV text

### Spec Text
> semantically-correct CSV is required; exact newline/quoting is not.

### Alternatives
1. Render the *stored* (coerced) value: `3` → `3`, `4.5` → `4.5`, `""` → an empty field. Original
   spelling that the coercion discarded (`003`, `+7`, `1e3`) is not restored.
2. Keep each cell's original source text alongside the coerced value and export that instead.

### Choice
Alternative 1. The export is defined as an export *of the dataset* — the same rows the JSON
endpoint serves, under the same filters/sort/pagination — so its cells are the dataset's values.
Retaining shadow copies of the source text would also be unobservable everywhere else in the API.
Numbers are written with `str()`, which round-trips through the ingestion rules.

### Risk: 20
Author most likely prefers: the same; an implementation that streamed the original file's lines
would preserve `003` and would also not be able to apply filters/sort, which the spec requires.

---

## T54 — An export whose filter matches no rows

### Spec Text
> The CSV uses source column order and applies the same filters ... as `/datasets/<id>`.

### Alternatives
1. Header row only, 200.
2. Completely empty body, 200.
3. 404/400.

### Choice
Alternative 1. The columns are a property of the dataset, not of the page, so they are emitted
regardless; an empty result set is a normal outcome of a filter, never an error (the JSON endpoint
returns `rows: []` with `columns` intact).

### Risk: 10
Author most likely prefers: the same.

---

## T55 — Uploaded CSV text goes through the whole CSV pipeline

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> `charset` applies and validates only for text CSV sources.

### Alternatives
1. An uploaded CSV is decoded, delimiter-inferred, parsed and type-coerced exactly as a fetched one,
   sharing every rule (and every ambiguity resolution) with `/convert`.
2. Uploads are stricter or simpler — e.g. comma-only, no encoding detection.

### Choice
Alternative 1. The spec introduces `/upload` as another door onto the same ingestion ("`/convert`
and `/upload` accept ..."), listing only the transport differences (multipart, 415/400). Sharing
the pipeline is what makes "the same file" behave the same whichever door it comes through.

### Risk: 5
Author most likely prefers: the same.

---

## T56 — `/upload` with a valid multipart body but an empty file part

### Spec Text
> malformed multipart or missing both `file` and `attachment`: `HTTP 400`
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. The field is present, so this is not "missing"; the zero-byte document then fails ingestion as
   non-tabular/unrecognised — 400 either way.
2. An empty part counts as no part → 400.

### Choice
Alternative 1 (the status is 400 under both readings, only the message differs). Zero bytes decode
to empty text, which has no header row, so the tabular rule rejects it.

### Risk: 3
Author most likely prefers: the same status.

---

## T57 — Where `CACHE_ENABLED` is read from, and what "fail startup" means

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:
> Invalid values fail startup.

### Alternatives
1. `CACHE_ENABLED` is an environment variable read once when the process starts.
2. It is a CLI flag (`--cache-enabled`) alongside `--port`/`--address`.
3. It is a per-request query parameter re-read on every `/convert`.

### Choice
Alternative 1. The name is written in `SCREAMING_SNAKE_CASE` with no `--` prefix, unlike every
documented CLI flag, and the spec ties its validation to *startup* rather than to a request — an
environment variable is the only one of the three that is both process-wide and checkable before
the server binds. It is read exactly once, at startup: changing the variable in the environment of
a running process cannot change behaviour mid-flight. "Fail startup" is implemented as a clean
non-zero exit (no traceback) with a message naming `CACHE_ENABLED` on stderr, and nothing ever
listens on the port. Unset means enabled, because "`/convert` caches results by default".

### Risk: 12
Author most likely prefers: the same environment variable; the likeliest divergence is an
implementation that additionally accepts a CLI flag, which no test of the env var can detect.

---

## T58 — Whether "strict" leaves room for empty or whitespace-padded `CACHE_ENABLED`

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:
> - true: `1`, `true`, `yes`, `on`
> - false: `0`, `false`, `no`, `off`
> Invalid values fail startup.

### Alternatives
1. Strict means the *whole* value, after case folding, must be one of the eight literals:
   `CACHE_ENABLED=""`, `" true"`, `"true "`, `"2"`, `"t"`, `"enabled"` all fail startup.
2. Values are stripped of surrounding whitespace first, so `" true "` is accepted.
3. An empty value is treated like an unset variable (enabled), since the shell makes the two
   easy to confuse.

### Choice
Alternative 1. The spec says "strict" and then enumerates exactly eight spellings; the only
latitude it grants is case ("case-insensitive"). Extending that to whitespace or to an
empty-means-default rule is precisely the leniency the word "strict" rules out. So the rule is
`value.lower() in {...}`, and everything else — including `""` — fails startup. Only a genuinely
*absent* variable falls back to the default (see [[T57]]).

### Risk: 25
Author most likely prefers: the same for junk values such as `maybe`; the likeliest divergence is
an empty `CACHE_ENABLED=` being tolerated as "unset" rather than failing startup.

### Update — resolved by the configuration spec (2026-09-15)
The later "Configuration, Size Limits, and Access Control" section settles this:

> Boolean values are strict: `1/true/yes/on` or `0/false/no/off` (case-insensitive, trimmed).

Alternative 2 above is now the specified behaviour for the *padding* half of the question, so the
rule became `value.strip().lower() in {...}`: `" true"`, `"on "` and `"\ttrue\n"` are accepted
where this entry had them failing startup, and the tests asserting that were updated. The *empty*
half is unchanged and stands as chosen: `""` — and any whitespace-only value, which trims to `""`
— is still not one of the eight enumerated spellings, so it still fails startup. The same strict
rule now also governs `REQUIRE_TLS` (see [[T67]]).

---

## T59 — Whether a cache hit ignores `charset`, and whether `charset` is still validated

### Spec Text
> With caching enabled, repeated `/convert` requests for the same source URL can return the
> cached dataset id without re-downloading.

### Alternatives
1. The cache is keyed on the source URL alone. A later request for the same URL with a different
   (or invalid) `charset` is still a hit: nothing is re-parsed and `charset` is not re-validated.
2. The cache is keyed on `(source, charset)`, so changing `charset` misses the cache and
   re-ingests with the new codec.
3. Keyed on the URL alone, but `charset` is still validated on every request, so
   `?source=<cached>&charset=bogus` is a 400 even though nothing is decoded.

### Choice
Alternative 1. The spec names the key twice and both times it is the URL — "the same source URL",
"the same dataset id" — and the id itself is a pure function of the URL, so a per-charset entry
could not even have a distinct endpoint to return. `charset` only ever affects *decoding* (and by
[[T47]] is only validated once the bytes prove to be text CSV); a hit performs no decoding, so
there is nothing for it to apply to or to fail against. A caller who wants a different charset has
the documented lever for it: `force`.

### Risk: 30
Author most likely prefers: the same URL-only key; the likeliest divergence is `charset` still
being validated eagerly on a cache hit (Alternative 3), returning 400 where this implementation
returns the cached endpoint.

---

## T60 — `?force=` with an empty value: presence flag, or a value?

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and replaces the cached
> dataset.
> Any `force` value is `HTTP 400`.

### Alternatives
1. `?force` and `?force=` are both "presence": the value is empty, so no value was supplied, and
   both force re-ingestion.
2. `?force=` supplied a value (the empty string) and is therefore a 400; only bare `?force` is
   presence.

### Choice
Alternative 1. A bare `?force` and `?force=` are indistinguishable in every mainstream query
parser (both decode to the key mapped to `""`), so telling them apart requires deliberately
re-splitting the raw query string on `&` and hunting for `=` — work no reading of "presence flag"
demands. The rule implemented is therefore: `force` absent → no forcing; present with an empty
value → forcing; present with any non-empty value → 400.

### Risk: 35
Author most likely prefers: the same falsy-value check; the likeliest divergence is an
implementation that inspects the raw query string and 400s on `?force=`.

---

## T61 — `force` supplied more than once

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and replaces the cached
> dataset.

### Alternatives
1. "Once" is load-bearing: `?force&force` is a repeated request parameter and therefore `HTTP 400`,
   matching the spec's existing "any repeated control parameter is `HTTP 400`" rule.
2. "Once" merely means "a single occurrence is enough" (as opposed to needing a value), so
   repeating it is harmless and still forces.

### Choice
Alternative 1. Had repetition been irrelevant the sentence would read "if present"; the qualifier
"once" only does work if more than once is different. Treating the extra occurrence as an error
also matches how this spec has handled every other repeated request parameter (see [[T27]],
[[T36]]) — silently ignoring a duplicate is the one behaviour it has never chosen.

### Risk: 40
Author most likely prefers: repeated bare `force` still forcing re-ingestion with `HTTP 200`
(Alternative 2), since the obvious `"force" in request.args` implementation never counts
occurrences.

---

## T62 — Whether `force` *values* are still rejected when caching is disabled

### Spec Text
> Any `force` value is `HTTP 400`.
> If caching is disabled, `force` has no additional effect.

### Alternatives
1. `force` is validated identically in both modes: `?force=1` is a 400 whether or not caching is
   enabled. "No additional effect" is about the *forcing*, which is redundant when every request
   already re-ingests.
2. With caching disabled the parameter is inert altogether, so `?force=1` is simply ignored and
   returns 200.

### Choice
Alternative 1. "Any `force` value is `HTTP 400`" is stated unconditionally, one bullet above, as a
property of the request; the disabled-cache sentence speaks only of *effect*, and the effect a
valid `force` has is re-ingestion — which a disabled cache already performs for every request.
Malformedness of a request should not depend on server configuration.

### Risk: 18
Author most likely prefers: the same unconditional 400; the likeliest divergence is an
implementation that skips `force` parsing entirely on the disabled path.

---

## T63 — How long the cache lives, and whether failures are cached

### Spec Text
> `/convert` caches results by default.
> With caching enabled, repeated `/convert` requests for the same source URL **can** return the
> cached dataset id without re-downloading.

### Alternatives
1. "Can" is permissive: the implementation may re-download whenever it likes.
2. "Can" describes the guaranteed behaviour: with caching enabled and no `force`, a repeat for a
   URL already ingested in this process always answers from the store, with no TTL, no size cap
   and no negative caching (a failed ingestion stores nothing, so the next request retries).

### Choice
Alternative 2. A permissive reading would make the whole section untestable, and the distinction
the spec then draws — `CACHE_ENABLED=0` means "every request re-downloads", `force` means "this
request re-downloads" — is only meaningful if the default is "never re-download". The cache is the
in-memory dataset store, so it lives exactly as long as the process; the spec mentions no
expiry, no eviction and no persistence, so none is invented. Failures are not cached because the
spec only ever describes caching a *dataset id*, and there is no id when ingestion failed.

### Risk: 8
Author most likely prefers: the same; a TTL or an explicit cache size limit would have been
specified.

---

## T64 — Whether `force` and `CACHE_ENABLED` reach `/upload`

### Spec Text
> `/convert` caches results by default.
> `force` is a presence flag.

### Alternatives
1. Both are scoped to `/convert`, as the section's heading and every sentence in it say. `/upload`
   already holds the bytes, so there is nothing to re-download; it parses and stores every time,
   and a `force` parameter on it is just an unknown parameter (ignored, as unknown parameters have
   always been).
2. `/upload` also honours `force`, rejecting `?force=1` with a 400 for symmetry.

### Choice
Alternative 1. Every sentence in this section names `/convert`, and the behaviours it controls —
"re-downloading", "re-ingestion" of a *source URL* — have no counterpart for a request that
carries its own bytes. An upload is unconditionally ingested and stored regardless of
`CACHE_ENABLED`.

### Risk: 10
Author most likely prefers: the same `/convert`-only scope; a hidden test would have to post
`?force=1` to `/upload` to tell the readings apart.

---

## T65 — What `DATAGATE_CONFIG` is, and what "read failure" covers

### Spec Text
> Service configuration sources, in order of precedence:
> 1. Built-in defaults
> 2. `DATAGATE_CONFIG` file
> 3. Direct environment variables
>
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. `DATAGATE_CONFIG` is an environment variable holding the *path* of a config file. Unset means
   "no config file", which is not an error. Set-but-unreadable (missing file, a directory, a
   permission error, undecodable bytes) is a read failure and stops startup.
2. `DATAGATE_CONFIG` is a fixed file name in the working directory, and the env var is something
   else entirely.
3. `DATAGATE_CONFIG` holds the config *content* inline rather than a path.

### Choice
Alternative 1. The spec calls it "the `DATAGATE_CONFIG` file" and lists it *between* built-in
defaults and "direct environment variables" — so it is itself supplied by an environment variable,
and the adjective "direct" in source 3 exists precisely to distinguish the settings given straight
in the environment from the ones routed through this file. A file that was never requested cannot
fail to be read, so an unset `DATAGATE_CONFIG` simply contributes nothing; a *requested* file that
cannot be read is the "read failure" the spec names, and exits non-zero with a message before the
port is bound (the same failure mode [[T57]] established for a bad `CACHE_ENABLED`).

### Risk: 12
Author most likely prefers: the same; the likeliest divergence is tolerating a *missing* file
named by `DATAGATE_CONFIG` as "no config" instead of failing startup.

---

## T66 — Config file syntax: comments, whitespace, quoting, junk lines, unknown and repeated keys

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values, blank/comment lines ignored.
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. A minimal `.env`-style reader: strip each line; skip it when empty or starting with `#`; split
   on the *first* `=`; strip key and value; a line with no `=` is invalid config (startup
   failure); an unrecognised `KEY` is ignored; a repeated key is last-wins; quotes are literal
   characters, not quoting syntax; `#` after a value is part of the value.
2. The same, but an unrecognised `KEY` is also invalid config and fails startup.
3. Full shell/`.env` semantics: `export` prefixes, single/double quote stripping, inline `#`
   comments, backslash escapes.

### Choice
Alternative 1. The spec describes the format in one sentence — `KEY=VALUE` lines plus commas plus
ignorable blank/comment lines — which is the whole grammar; inventing quote stripping or escape
handling (3) would silently rewrite values the spec never said were quoted. A line that is neither
blank, nor a comment, nor `KEY=VALUE` matches nothing in that grammar, so it is "invalid config".
Unknown keys are ignored rather than fatal (2) because the spec's failure clause is about config
that is *invalid* — unparseable or a bad value for a named setting — and a forward-compatible or
commented-out-by-renaming key is neither; the settings table defines which keys are consumed, not
which keys may appear. `#` is taken as the comment marker (the overwhelmingly common one for
`KEY=VALUE` files), recognised only at the start of a stripped line, so a value may contain `#`.

### Risk: 35
Author most likely prefers: the same line grammar; the two likeliest divergences are treating an
unknown key as a startup failure, and ignoring junk lines instead of failing on them.

---

## T67 — How precedence is applied, and whether an empty env var counts as "set"

### Spec Text
> Service configuration sources, in order of precedence:
> 1. Built-in defaults
> 2. `DATAGATE_CONFIG` file
> 3. Direct environment variables

### Alternatives
1. Per-key layering: each setting is resolved independently, with a direct environment variable
   beating the config file's entry for that same key, which beats the default. A config file that
   sets only `REQUIRE_TLS` leaves the other four at their defaults.
2. Whole-source replacement: if any direct environment variable is present, the config file is
   discarded entirely.
3. Reverse precedence: the file wins over the environment (the list read as least-specific-last).

### Choice
Alternative 1. "In order of precedence" with defaults first is the standard layered-configuration
idiom, and it is the only reading under which built-in defaults are useful at all — a default is
by definition a per-key fallback. The list ascends: later sources override earlier ones, so the
environment is the final word. A variable that is *present but empty* counts as set and is
resolved by that setting's own value rules ([[T69]] for the integer, [[T58]] for booleans), which
is what lets an empty `ORIGIN_ALLOWLIST=` in the environment switch off an allowlist the file
turned on.

### Risk: 15
Author most likely prefers: the same per-key layering; the likeliest divergence is an empty
environment variable being skipped as if unset, leaving the file's value in force.

---

## T68 — The names of the "direct environment variables"

### Spec Text
> 3. Direct environment variables
> | `MAX_SOURCE_SIZE` | `ORIGIN_ALLOWLIST` | `REQUIRE_TLS` | `STORAGE_DIR` | `CACHE_ENABLED` |

### Alternatives
1. The bare setting names, exactly as the table spells them: `MAX_SOURCE_SIZE=...`,
   `ORIGIN_ALLOWLIST=...`, and so on.
2. Prefixed names, `DATAGATE_MAX_SOURCE_SIZE` etc., matching `DATAGATE_CONFIG`.
3. Both accepted, prefixed winning.

### Choice
Alternative 1. The table gives one name per setting and the spec uses those same names for the
config file's keys; nothing hints at a second spelling. Decisively, the previous spec section
already shipped `CACHE_ENABLED` as a bare environment variable ([[T57]]) and this table lists
`CACHE_ENABLED` unchanged, so the bare form must keep working — and it would be incoherent for one
row of the table to be bare and the other four prefixed. `DATAGATE_CONFIG` is prefixed because it
is not a setting in the table; it names the file.

### Risk: 20
Author most likely prefers: the same bare names; a hidden test setting a prefixed variable and
expecting it to take effect is the only way to tell the readings apart.

---

## T69 — Validating `MAX_SOURCE_SIZE`: negatives, zero, empty, units

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> unset limit means no max.

### Alternatives
1. The value must be a plain decimal integer literal, and must not be negative: `0` is a valid
   (if brutal) limit that rejects every non-empty file; `-1`, `1.5`, `10MB`, `1_000`, `0x10` and
   `abc` are invalid config and fail startup. An explicitly empty value means "unset".
2. An empty value is invalid config rather than "unset".
3. Negative values are accepted and behave like `0`, or like "unset".
4. Human-readable suffixes (`10MB`, `1k`) are accepted.

### Choice
Alternative 1. "integer bytes" rules out suffixes (4) and decimals; a byte count below zero has no
meaning, so a negative is a configuration mistake and the spec's "invalid config … exits" is the
honest response rather than silently reinterpreting it (3). `0` is kept legal because it is a
well-formed byte count and the size rule ("`= limit` accepted") still defines its behaviour
exactly. An empty value is read as "unset" — the same way an empty `ORIGIN_ALLOWLIST` yields no
allowlist — so that an environment variable can positively erase a limit set in the config file
(see [[T67]]); booleans stay stricter because the spec enumerates their eight legal spellings.
Underscore and hex forms are rejected even though Python's `int()` would accept them.

### Risk: 22
Author most likely prefers: the same for junk and suffixed values; the likeliest divergences are
an empty value failing startup instead of meaning "unset", and a bare `int(value)` quietly
accepting `-1` or `1_000`.

---

## T70 — What "file size" is measured on, and when the check runs

### Spec Text
> Enforced for `/convert` and `/upload`:
> - file size `= limit` accepted.
> - file size `> limit` => `HTTP 400` with standard envelope.

### Alternatives
1. The size of the source *file* itself: for `/convert`, the number of bytes actually downloaded
   from the source URL; for `/upload`, the number of bytes in the uploaded file part. Decompressed
   or parsed sizes are irrelevant, and so is the multipart envelope's overhead.
2. For `/upload`, the whole request body's `Content-Length` (multipart boundaries included).
3. For `/convert`, the remote `Content-Length` header, rejecting before downloading.

### Choice
Alternative 1. The spec says "file size", and the file is the thing being converted: the bytes the
source URL served, or the bytes of the uploaded part. Measuring the multipart envelope (2) would
make the effective limit depend on the client's boundary string and field name, so the same file
could pass from one client and fail from another. A remote `Content-Length` (3) is advisory and
often absent, so the downloaded length is what is checked — after the fetch, before parsing.
Because the check is on downloaded bytes, a `/convert` request answered from the cache without
re-downloading ([[T63]]) performs no size check at all; there is no new file to measure.

### Risk: 18
Author most likely prefers: the same measurement; the likeliest divergence is also rejecting a
cache hit whose stored payload exceeded a limit introduced later.

---

## T71 — "domain-boundary rules" for allowlist suffix matching

### Spec Text
> 3. Accept only hostnames matching any allowed suffix case-insensitively with domain-boundary
>    rules.

### Alternatives
1. A hostname matches suffix `S` when, lowercased, it either equals `S` or ends with `"." + S`.
   So `example.com` allows `example.com` and `app.example.com` but not `notexample.com`,
   `example.com.evil.net` or `example.co`. Configured entries may be written with a leading dot
   (`.example.com`) or a trailing dot; both are normalised away. Bare `str.endswith` (no boundary)
   is exactly what the phrase rules out.
2. Only strict sub-domains match; the apex `example.com` itself does not.
3. The entries are full hostnames, matched by equality only.

### Choice
Alternative 1. "Suffix … with domain-boundary rules" is the standard cookie/CORS-style rule: the
match must fall on a label boundary, which is what stops `notexample.com` from matching
`example.com`, while the suffix `example.com` is still a suffix of itself, so the apex is included
(2 would make the natural configuration `ORIGIN_ALLOWLIST=example.com` fail for
`https://example.com/` itself — clearly not the intent). Equality only (3) would make the word
"suffix" meaningless. The Referer's port and userinfo are not part of the hostname and are
ignored; an IP-address Referer only matches an identical entry, since it has no domain labels.

### Risk: 20
Author most likely prefers: the same equality-or-dot-suffix rule; the likeliest divergence is an
implementation that does not normalise a leading dot in a configured entry.

---

## T72 — Which requests the allowlist gates, and how it orders against other errors

### Spec Text
> If configured, check every request before routing:
> 1. Require `Referer`.

### Alternatives
1. Literally every request: the check runs before URL routing, so it also covers `/datasets/...`,
   `/export`, unknown paths (403 instead of 404), wrong methods (403 instead of 405) and `OPTIONS`
   preflights. It runs before size limits and before any parameter validation, so a disallowed
   Referer wins over every other error.
2. Only the ingestion endpoints `/convert` and `/upload` are gated.
3. Every request except CORS `OPTIONS` preflights, which browsers send *without* a `Referer` and
   which would otherwise make a browser client unusable.

### Choice
Alternative 1. "Check every request before routing" is about as explicit as the spec gets: "every
request" excludes no path and no method, and "before routing" fixes the check ahead of the point
where a path becomes a handler — which is also what makes the 403-over-404 ordering observable.
Exempting preflights (3) is a real-world improvement the spec did not ask for, and the section
names no endpoints, unlike the size-limit section immediately above it which names exactly two.

### Risk: 45
Author most likely prefers: gating only the routes their own tests exercise; the likeliest
divergence is an unknown path or an `OPTIONS` preflight answering 404/204 rather than 403.

---

## T73 — A `Referer` that is present but yields no hostname

### Spec Text
> 1. Require `Referer`.
> 2. Parse hostname.
> 4. Otherwise return `HTTP 403`.

### Alternatives
1. Anything that does not produce a hostname matching the allowlist is a 403: a missing header, an
   empty or whitespace-only header, and a header that parses to no host (`about:blank`,
   `example.com/page` with no scheme, `https:///path`) all land on step 4.
2. An unparseable `Referer` is a 400 (malformed request) rather than a 403.

### Choice
Alternative 1. Step 4 is written as the catch-all for steps 1–3 ("Otherwise"), and the error table
lists exactly two 403 conditions — missing `Referer` and "Referer not allowed" — with no 400 row
for a malformed one. A header that parses to no hostname cannot match any allowed suffix, so it is
simply not allowed. An empty header value is treated as missing, since `Referer: ` conveys no
origin at all.

### Risk: 8
Author most likely prefers: the same; both readings agree on the common cases and only differ on
the message text, which the spec leaves free.

---

## T74 — What `REQUIRE_TLS=true` changes, and how the absolute URL is built

### Spec Text
> `REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints.
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request host.

### Alternatives
1. `REQUIRE_TLS` only changes the shape of the `endpoint` string in the `/convert` and `/upload`
   replies: `"/datasets/<id>"` becomes `"https://<request Host header>/datasets/<id>"`, port
   included if the Host header carries one. Plain-HTTP requests are still served, and no other
   response (or redirect, or HSTS header) changes.
2. It additionally *requires* TLS: plaintext requests are refused or redirected.
3. The absolute URL is built from a configured public hostname rather than the request's `Host`.

### Choice
Alternative 1. The section is titled "TLS-aware endpoint **URLs**" and its two sentences describe
only what the endpoints "return"; a rejection rule would be a new error-table row, and the error
table added by this spec has none. "using request host" names the source of the authority
component explicitly, which rules out (3) and means the `Host` header verbatim — the only host the
server knows. The scheme is hard-coded `https://` exactly as written, regardless of the scheme the
request itself arrived on, which is the whole point of the setting: it advertises the TLS URL that
a terminating proxy in front of the service serves.

### Risk: 30
Author most likely prefers: the same endpoint rewriting; the likeliest divergences are stripping
the port from the host, or also rejecting plaintext requests.

---

## T75 — The default `STORAGE_DIR`, what is persisted, and what persistence does to the cache

### Spec Text
> | `STORAGE_DIR` | path | implementation-defined |
> Create `STORAGE_DIR` if missing.
> Persisted datasets must survive restart when the same directory is reused.

### Alternatives
1. Every ingested dataset — from `/convert` and from `/upload` alike — is written into
   `STORAGE_DIR` as a file named for its dataset id, and the directory is read back at startup, so
   ids stay queryable across a restart. Because the dataset store *is* the `/convert` cache
   ([[T63]]), a restart that reuses the directory also preserves cache hits: the source is not
   re-downloaded. The default directory is a fresh private temporary directory per process, so an
   unconfigured service keeps the per-process behaviour the caching section already specified.
2. The default is a fixed relative or home-directory path (`./datagate-storage`, `~/.datagate`),
   so even an unconfigured service persists across restarts.
3. Only uploads are persisted (a converted dataset can always be re-fetched from its URL).
4. Datasets persist and stay queryable, but `/convert` keeps a separate in-memory cache, so a
   restart re-downloads even though the id is still valid.

### Choice
Alternative 1. The spec says "persisted datasets", not "persisted uploads", so both ingestion
paths are covered (3). The default is left "implementation-defined" precisely so that the only
*guaranteed* behaviour is the conditional one the next sentence states — survival "when the same
directory is reused" — and a per-process temporary directory satisfies it while keeping every
previously specified guarantee intact, including "a fresh process re-downloads" when no directory
was configured; a fixed shared default (2) would silently change that older behaviour. Keeping one
store rather than a store plus a parallel cache (4) also keeps the guarantee the caching section
made that a cached reply is byte-identical to a fresh one.

### Risk: 38
Author most likely prefers: a fixed default path such as `./data` or `./storage`; that only
diverges on a test that restarts with no `STORAGE_DIR` set and still expects the dataset back,
which the spec's own "when the same directory is reused" wording argues against.

---

## T76 — Failures involving `STORAGE_DIR` itself

### Spec Text
> Create `STORAGE_DIR` if missing.
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. The directory is created at startup, parents included; if it cannot be created or is not a
   usable directory (a plain file sits at the path, a permission error, a parent that is a file),
   that is a startup failure — non-zero exit, nothing bound. Files already in the directory that
   are not readable dataset records are ignored rather than fatal.
2. Creation is lazy, on first write, so a bad path surfaces as a 500 on the first ingestion.
3. A corrupt dataset file in the directory is also a startup failure.

### Choice
Alternative 1. "Create `STORAGE_DIR` if missing" sits in the configuration section beside the
sentence about startup failures, so the creation happens while the configuration is being
established — eagerly, before serving. A path that cannot become a directory is exactly the
"invalid config" the spec refuses to run with. Unknown files in the directory are not config, and
the spec never says the service owns the directory exclusively, so they are skipped quietly (3).

### Risk: 10
Author most likely prefers: the same eager creation; the divergence would only show for a
deliberately unusable path.

---

## T77 — Whether the previous hard 64 MiB source cap survives "unset limit means no max"

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |
> unset limit means no max.

### Alternatives
1. "No max" is literal: with `MAX_SOURCE_SIZE` unset, no size ceiling of any kind applies, so the
   implementation's previous built-in 64 MiB download cap is removed.
2. The built-in cap stays as a safety net, since the spec is about a *configurable* limit.

### Choice
Alternative 1. "Unset limit means no max" is a flat statement about the service's behaviour, not
about one particular check, and a surviving 64 MiB cap would make it false. The earlier cap was
never specified — it was an implementation safety net — and the new setting is the spec's answer
to the same concern: an operator who wants a ceiling configures one.

### Risk: 12
Author most likely prefers: the same removal; neither reading is testable without a >64 MiB
fixture, which is why the risk is small rather than zero.

---

## T78 — What "all other states" of `enrich` do: silently off, or a 400?

### Spec Text
> Only a single, exact `enrich=yes` enables enrichment.
> All other states keep enrichment off.

### Alternatives
1. Any `enrich` that is not exactly one `yes` simply leaves enrichment off; the request
   otherwise succeeds normally.
2. A present-but-malformed `enrich` (`enrich=no`, `enrich=YES`, `enrich=1`, bare `enrich`)
   is an invalid parameter and gets the 400 that `force` gets for a bad value (T60/T61).

### Choice
Alternative 1. The spec spells out the consequence itself — "all other states *keep enrichment
off*" — which is a statement about the enrichment flag, not about the request's validity, and it
would be a strange way to describe a 400. It also contrasts deliberately with `force`, whose
section does talk about rejecting values. So `enrich=no`, `enrich=YES`, `enrich=Yes`,
`enrich=yes ` (trailing space), `enrich=` and a bare `enrich` all convert successfully with
enrichment off, and the success envelope is unchanged.

### Risk: 15
Author most likely prefers: the same silent-off reading; the residual risk is that a bare
`enrich` with no `=` is treated as an invalid parameter rather than as "not `yes`".

---

## T79 — `enrich` supplied more than once, including `enrich=yes&enrich=yes`

### Spec Text
> Only a **single**, exact `enrich=yes` enables enrichment.

### Alternatives
1. "Single" counts occurrences: two `enrich` parameters keep enrichment off even when both
   read `yes`.
2. "Single" only stresses the exact spelling; a repeated parameter is resolved the way the web
   framework resolves it (first or last wins), so `enrich=yes&enrich=yes` enriches.
3. Repetition is a 400, as it is for `force` (T61).

### Choice
Alternative 1. The word "single" is doing work next to "exact" — exact already covers the
spelling of the value, so "single" must be about how many times the parameter appears. Combined
with "all other states keep enrichment off" (T78), the natural implementation reads the whole
list of values and enriches only when it is exactly `["yes"]`.

### Risk: 40
Author most likely prefers: `enrich=yes&enrich=yes` (and `enrich=no&enrich=yes`) enriching,
because a one-line `request.args.get("enrich") == "yes"` sees only the first value and is the
shortest way to implement "exact `enrich=yes`".

---

## T80 — The `filetype` label for an enriched CSV dataset

### Spec Text
> `dataset_summary` with at least `filetype`, `row_count`, `column_count`
> For enriched spreadsheet datasets, add only `dataset_summary` with `filetype: "excel"`.

### Alternatives
1. `"csv"` — the lower-case counterpart of the one label the spec does pin down.
2. `"text"`, `"text/csv"`, or the remote `Content-Type`.

### Choice
Alternative 1. The spec names the format family for spreadsheets (`"excel"`, not `xlsx`/`xls`),
so the CSV branch is the other member of the same pair, and the section itself calls them "CSV
datasets". `"csv"` it is — lower case, matching `"excel"`. The label follows the sniffed
container (T50), not the URL suffix or the remote `Content-Type`, so a `.txt` URL serving CSV
bytes is `"csv"` and a `.csv` URL serving a workbook is `"excel"`.

### Risk: 10
Author most likely prefers: the same `"csv"`.

---

## T81 — How the four type labels `text`/`number`/`integer`/`float` are assigned

### Spec Text
> `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`
> Type labels: `text`, `number`, `integer`, `float`.

### Alternatives
1. `integer` when every non-missing value is a whole-number literal, `float` when every
   non-missing value is a decimal literal, `number` when the column mixes the two, `text`
   otherwise.
2. `number` for every numeric column, with `integer`/`float` never emitted (they would be
   documentation of the underlying JSON types only).
3. `integer`/`float` only, with `number` reserved for a column that is numeric but whose
   values do not fit either (impossible here).
4. `integer` when every value is whole *in value* (so `3.0` counts as an integer), `float`
   otherwise.

### Choice
Alternative 1. All four labels are listed as labels that appear, so a reading that never emits
one of them is worse than a reading that emits all four. Ingestion already types each cell as
`int`, `float` or `str` (T3), so the column label falls out of the set of Python types actually
stored: all `int` → `integer`, all `float` → `float`, a mix of the two → `number`, anything
containing a string → `text`. `number` is therefore the honest label for "numeric, but not
uniformly one kind". Note this keys off the *literal* as ingested: `3.0` is a float and makes a
column `float` (or `number` beside plain integers), because that is how the value is stored and
returned in `rows`.

### Risk: 55
Author most likely prefers: a mixed int/float column labelled `float` (the widening rule) with
`number` used for something else — most plausibly as the label for any numeric column in an
implementation where `integer`/`float` are only refinements.

---

## T82 — The `type` of a column whose cells are all missing

### Spec Text
> `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`

### Alternatives
1. `text` — the fallback label, since nothing proves the column numeric.
2. A fifth label such as `empty`/`unknown`/`null`, which the spec does not list.
3. `number`, treating "no counter-example" as numeric.

### Choice
Alternative 1. The spec fixes the label vocabulary to four values, so an all-missing column has
to land on one of them, and `text` is the only one that does not assert a numeric property the
data never demonstrates. It is also what falls out of "a column is numeric only if every
non-missing value is numeric" when the loop sees no numeric values at all.

### Risk: 35
Author most likely prefers: `text` as well, but an implementation that starts from "assume
numeric until a non-numeric value appears" would report `integer` or `number` for a column of
nothing but blanks.

---

## T83 — Whether `distinct_count` counts missing values

### Spec Text
> `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`

### Alternatives
1. Distinct over the non-missing values only; blanks are accounted for solely by
   `missing_count`.
2. Distinct over every cell, so a column with blanks gets one extra distinct value.

### Choice
Alternative 1. `distinct_count` and `missing_count` are presented as a pair, which reads as a
partition of the column: how many real values there are, and how many cells have none. Counting
the blank as a value would double-report it. This also matches the dataframe vocabulary the
field names borrow, where the distinct/unique count excludes nulls by default. Distinctness is
by stored value, so `1` and `1.0` are the same value while `1` and `"1"` cannot both occur in
one column anyway.

### Risk: 40
Author most likely prefers: a plain `len(set(column))` over all cells, which counts the empty
string as one more distinct value — the shortest implementation, and the one a fixture with a
blank cell would expose.

---

## T84 — What counts as "missing"

### Spec Text
> `column_details` keyed by column name with at least `type`, `distinct_count`, `missing_count`

### Alternatives
1. A cell is missing when its stored value is the empty string — which covers a truly empty
   field, a whitespace-only field (ingestion strips it, T3) and the padding added to a short
   row (T7).
2. Only a physically absent field counts; a whitespace-only cell is a value.
3. Textual null markers (`NULL`, `N/A`, `-`) count as missing too.

### Choice
Alternative 1. Ingestion has already decided what an absent cell looks like: every one of those
cases is stored as `""` and is returned as `""` in `rows`. Metadata that disagreed with the rows
it describes would be indefensible, and the spec gives no list of null markers, so inventing one
would make `missing_count` unpredictable.

### Risk: 20
Author most likely prefers: the same empty-string rule; the risk is concentrated in short rows
padded to the header width, which one could argue have no cell at all rather than a missing one.

---

## T85 — Whether an enriched spreadsheet's `dataset_summary` still carries the counts

### Spec Text
> For enriched spreadsheet datasets, add only `dataset_summary` with `filetype: "excel"`.

### Alternatives
1. "Only" contrasts with the CSV case's *two* fields: `column_details` is omitted, but
   `dataset_summary` keeps the same shape — `filetype`, `row_count`, `column_count`.
2. "Only ... with `filetype: "excel"`" is literal: the summary contains nothing but
   `filetype`.

### Choice
Alternative 1. The preceding paragraph defines `dataset_summary` as having *at least*
`filetype`, `row_count` and `column_count`; the spreadsheet sentence names the field's differing
value rather than redefining the field, and the word "only" sits next to the list of added
objects, not next to the list of summary keys. Row and column counts are also format-agnostic —
there is no reason the same table would report them from a `.csv` and hide them from a `.xlsx`.

### Risk: 20
Author most likely prefers: the same three keys; a test asserting `dataset_summary ==
{"filetype": "excel"}` exactly is the way this reading would fail.

---

## T86 — Whether the metadata describes the stored dataset or the current query

### Spec Text
> ### Enriched query output
> For enriched CSV datasets, add:
> - `dataset_summary` with at least `filetype`, `row_count`, `column_count`
> Re-ingestion recomputes metadata from current source bytes.

### Alternatives
1. The metadata is computed once at ingestion over the whole dataset and replayed on every
   query, so filters, `_size`, `_offset` and `_sort` never change it.
2. The metadata is computed per request over the rows the query actually returns, so
   `row_count` tracks the page and `distinct_count` the page's values.

### Choice
Alternative 1. "Re-ingestion recomputes metadata" says plainly that computing metadata is
something ingestion does, and the cache section treats the metadata as *stored state* that a
request can upgrade — per-request metadata would have no state to upgrade. The section also
promises `total` is unchanged, and `total` is the filtered count; a `row_count` that shadowed it
would make the two fields redundant. So `row_count` is the dataset's data-row count, never the
page size and never the filtered count.

### Risk: 12
Author most likely prefers: the same dataset-wide reading.

---

## T87 — Duplicate column names in `column_details`

### Spec Text
> `column_details` keyed by column name

### Alternatives
1. One entry per distinct name; when a header repeats a name, the later column's details
   overwrite the earlier one's.
2. One entry per distinct name, first occurrence wins.
3. Disambiguated keys (`qty`, `qty_2`), which the spec does not describe.

### Choice
Alternative 1. A JSON object keyed by column name cannot hold two entries for one name, and
building the object by walking the columns in order — the obvious implementation — leaves the
last writer in place. Inventing suffixed keys would break "keyed by column name". Duplicate
headers are already ingested as-is (each column keeps its position in `rows`), so only the
metadata collapses.

### Risk: 25
Author most likely prefers: the same last-wins collapse, since it is what a dict-comprehension
over the columns produces; first-wins is the plausible alternative.

---

## T88 — Re-ingestion *without* `enrich=yes` over an enriched dataset

### Spec Text
> - `enrich=yes` on a cached non-enriched dataset forces re-ingestion and upgrades stored state.
> - Requests without re-ingestion do not change stored enrichment state.
> - Re-ingestion recomputes metadata from current source bytes.

### Alternatives
1. Re-ingestion writes the state the *current* request asked for: a `force` refresh (or any
   request while `CACHE_ENABLED=false`) without `enrich=yes` re-stores the dataset
   non-enriched, and the dataset stops reporting metadata.
2. Enrichment is sticky: once a dataset is enriched, later re-ingestions keep recomputing the
   metadata even when the request does not ask for it, so state only ever moves upward.

### Choice
Alternative 1. The spec guards exactly one direction — "requests *without re-ingestion* do not
change stored enrichment state" — which would be pointless if no request could ever lower the
state; the qualifier only makes sense if requests *with* re-ingestion can. A re-ingestion is a
fresh ingestion of the source under this request's parameters, and this request did not ask for
enrichment. The one thing that must never silently downgrade is a *failed* enrichment (the error
section), which is different: there the stored record is left untouched entirely.

### Risk: 35
Author most likely prefers: sticky enrichment, if their store keeps the metadata alongside rows
and a plain refresh only replaces the rows.

---

## T89 — What "may use cache" permits for `enrich=yes` on an enriched dataset

### Spec Text
> - `enrich=yes` on a cached enriched dataset may use cache.

### Alternatives
1. It is an ordinary cache hit: no re-download, no recomputation, unchanged stored state — and
   `force` still overrides it, as it does for any cache hit.
2. "May" leaves it free, so re-downloading every time is equally conforming.

### Choice
Alternative 1. "May use cache" grants permission to skip the work, and the whole point of the
surrounding section is that only a *missing* enrichment forces the re-ingestion. Treating the
request as a normal hit is also what keeps `/convert` idempotent and keeps the origin hit count
flat, which is the behaviour the caching section already promises. `force` is orthogonal and
still re-ingests (storing an enriched record, since this request asked for enrichment).

### Risk: 8
Author most likely prefers: the same cache hit.

---

## T90 — "`enrich` applies only on `/convert`"

### Spec Text
> - `enrich` applies only on `/convert`.

### Alternatives
1. Other endpoints ignore the parameter completely: `/upload?enrich=yes` stores a
   non-enriched dataset, and `/datasets/<id>?enrich=yes` neither adds metadata to a
   non-enriched dataset nor hides it from an enriched one. No error anywhere.
2. `enrich` on another endpoint is an unknown/invalid parameter and gets a 400.
3. `/datasets/<id>?enrich=yes` turns the metadata on at query time.

### Choice
Alternative 1. "Applies only on `/convert`" says where the parameter has an effect, not that it
becomes poison elsewhere, and no error table lists it. The service already ignores parameters it
does not recognise on these routes, and `/datasets/<id>` renders whatever the stored record
holds — which is what makes the enriched output a property of ingestion rather than of the
query (T86). `/upload` therefore never produces metadata at all.

### Risk: 15
Author most likely prefers: the same inert reading; the plausible divergence is `/upload`
honouring `enrich=yes`, since it shares the ingestion pipeline.

---

## T91 — What an "enrichment failure" is, what status it returns, and what it leaves stored

### Spec Text
> Enrichment failures return standard JSON errors and must not downgrade to non-enriched storage.

### Alternatives
1. Any failure on an enriching `/convert` — the ordinary ingestion failures (invalid URL,
   unreachable source, oversized source, unrecognised format) plus any failure while computing
   the metadata — produces the usual `{"ok": false, "error": "..."}` envelope with the status
   the existing error table assigns, and writes nothing: a dataset already stored for that id
   keeps its rows *and* its enrichment state.
2. A metadata failure is non-fatal: store the dataset without metadata and still answer 200.
3. Enrichment failures get a new dedicated status code.

### Choice
Alternative 1. "Standard JSON errors" points at the envelope and status codes the spec already
defines rather than at anything new, and "must not downgrade to non-enriched storage" rules out
alternative 2 explicitly — a half-succeeded enrichment may not be silently written as a plain
dataset. Storing only after both the rows and the metadata are in hand gives exactly that: the
store is never the loser of a failed request, so a previously enriched dataset stays enriched
and queryable and a previously non-enriched one stays as it was. A metadata computation that
raised unexpectedly would surface as the standard 500 envelope.

### Risk: 20
Author most likely prefers: the same all-or-nothing write; the divergence would be an
implementation that clears the stored record before re-ingesting, leaving nothing behind on
failure.

---

## T92 — Whether enrichment state survives a restart over a reused `STORAGE_DIR`

### Spec Text
> - `enrich=yes` on a cached non-enriched dataset forces re-ingestion and upgrades stored state.
> - Requests without re-ingestion do not change stored enrichment state.

### Alternatives
1. Enrichment is part of the stored record, so a reused `STORAGE_DIR` serves the metadata after
   a restart, and a record written by an older build (no enrichment fields) simply counts as
   non-enriched — an `enrich=yes` then upgrades it.
2. Enrichment is process-local: a restart drops the metadata even though the rows survive.

### Choice
Alternative 1. The store *is* the cache (T75), and the spec calls enrichment "stored state" that
a later request can upgrade, so it belongs in the same record as the rows. Anything else would
make "`enrich=yes` on a cached enriched dataset may use cache" false for the first request after
a restart. Records lacking the fields are read as non-enriched rather than skipped, so an
existing store keeps working.

### Risk: 10
Author most likely prefers: the same persisted state.
