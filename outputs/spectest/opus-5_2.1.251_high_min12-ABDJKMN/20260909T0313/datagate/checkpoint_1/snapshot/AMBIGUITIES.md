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
