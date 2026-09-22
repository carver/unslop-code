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
