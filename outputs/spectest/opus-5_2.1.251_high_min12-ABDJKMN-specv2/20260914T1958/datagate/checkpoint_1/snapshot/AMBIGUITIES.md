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
