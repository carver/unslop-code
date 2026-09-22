# AMBIGUITIES

Interpretation decisions taken while implementing the `datagate` spec.

---

## T1. How the dataset id is derived from the source URL

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. Hash the exact `source` query-parameter string (byte-for-byte), so
   `http://h/a.csv` and `http://h/a.csv?` are different datasets.
2. Normalise the URL first (lower-case host, drop default port, strip trailing
   `/`, sort query parameters) and hash the normalised form.
3. Use a monotonically increasing counter plus a URL → id side table.

### Choice
Alternative 1: `sha256(source_string)` truncated to 16 hex characters. The spec
says "the same `source` URL **string**", which points at the literal parameter
value rather than a canonicalised URL. A counter would still satisfy the
"same URL, same id" rule but makes ids depend on server history, which the
Determinism section argues against.

### Risk: 10
Most likely author preference if different: the same string-keyed hash with a
different digest/length (invisible to any test that does not hard-code an id).

---

## T2. How encoding is "detected" when `charset` is omitted

### Spec Text
> `charset` ... If omitted, detect unambiguous encoding from content, else latin-1.

### Alternatives
1. BOM sniffing, then a strict UTF-8 decode attempt; fall back to latin-1.
2. A statistical detector (`chardet` / `charset_normalizer`), which may return
   `windows-1252`, `MacRoman`, `Shift_JIS`, ... for non-UTF-8 bytes.
3. Always latin-1 unless a BOM is present.

### Choice
Alternative 1. "Unambiguous" fits self-validating encodings: a BOM is explicit,
and a successful strict UTF-8 decode is statistically conclusive, while every
byte string is valid latin-1 so it can only ever be the fallback. Statistical
guesses are the opposite of unambiguous and are not deterministic across
library versions, which the Determinism section forbids.

### Risk: 20
Most likely author preference if different: `charset_normalizer` best-guess,
which would decode windows-1252 fixtures with smart quotes differently.

---

## T3. Which cell values become JSON numbers

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Strict regex: optional sign, digits, optional fractional part, optional
   exponent. `007` → `7`, `nan`/`inf`/`1_0`/`0x10` → text, `1,234` → text.
2. Naive `int()` then `float()` in a try/except, which additionally accepts
   `nan`, `inf`, `1_0`, and surrounding underscores.
3. Locale/currency aware parsing (`$1,234.50` → `1234.5`).

### Choice
Alternative 1. It covers exactly the "integers/decimals" wording, keeps
identifiers such as `08:30` and `12:00` as text, and never produces `NaN` or
`Infinity`, which are not valid JSON. Leading zeros are still converted
(`007` → `7`) because that is what any int/float based implementation does.

### Risk: 25
Most likely author preference if different: plain `int()`/`float()`
try/except, which would turn a literal `nan` or `inf` cell into a number.

---

## T4. What counts as "non-tabular content"

### Spec Text
> | Non-tabular content | 400 |
> Delimiter must be inferred from input, if present ...
> A valid file requires at least one header row and one data row.

### Alternatives
1. Reject only when the structural rules fail: empty body, binary (NUL bytes),
   an obvious markup/JSON payload, or fewer than two non-empty rows. A
   single-column file with a header and a data row is accepted.
2. Additionally require that one of the supported delimiters actually occurs,
   so any single-column file is rejected as non-tabular.
3. Trust the remote `Content-Type` only.

### Choice
Alternative 1, with the remote `Content-Type` used as an extra signal (an
`text/html` or `application/json` response is rejected without parsing).
"Delimiter must be inferred from input, **if present**" implies a delimiter may
legitimately be absent, so a one-column CSV is still a table.

### Risk: 35
Most likely author preference if different: requiring a delimiter to be
present, so a one-column CSV would return 400 instead of 200.

---

## T5. Rows whose field count differs from the header

### Spec Text
> `columns` and each row follow source column order.

### Alternatives
1. Pad short rows with empty strings and truncate long rows to the header width.
2. Keep ragged rows exactly as parsed, so row lengths vary.
3. Treat any ragged row as non-tabular and return 400.

### Choice
Alternative 1. It keeps every row aligned with `columns`, which is what a
consumer indexing `rows[i][j]` by column position needs, and it is the
behaviour of the common CSV → records conversions. Rejecting the whole file for
one short line is harsher than anything the spec asks for.

### Risk: 30
Most likely author preference if different: emitting the ragged rows verbatim.

---

## T6. Units and precision of `query_ms`

### Spec Text
> `"query_ms": 3.2` ... `query_ms` is present and non-negative.

### Alternatives
1. Milliseconds as a float measuring the time spent serving the query, rounded
   to 3 decimals.
2. Milliseconds as an integer.
3. Time spent on the original ingestion, stored with the dataset.

### Choice
Alternative 1. The sample value `3.2` is fractional, and "query_ms" names the
query request, not ingestion.

### Risk: 5
Most likely author preference if different: a different rounding precision,
which only matters to a test asserting an exact value (impossible for a timer).

---

## T7. `charset` is a real encoding but the bytes do not decode with it

### Spec Text
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. 400 — an encoding that cannot decode the payload is unusable.
2. 200 with `errors="replace"` (or `errors="ignore"`), treating the table as
   successfully ingested with replacement characters.
3. 404, folding it into "source unreachable".

### Choice
Alternative 1. "Malformed" most naturally covers the whole
charset-plus-payload combination failing, and a table full of U+FFFD is a
silent data corruption the caller asked to be told about.

### Risk: 25
Most likely author preference if different: decoding with `errors="replace"`
and returning 200.

---

## T8. What makes a URL "invalid"

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Require an `http`/`https` scheme and a non-empty host; everything else
   (`not-a-url`, `htp:/x`, `file:///etc/passwd`, `ftp://h/a.csv`) is 400.
2. Only reject strings that have no scheme or no host, and let `requests` fail
   on exotic schemes, which would report them as 404.
3. Accept anything and map every failure to 404.

### Choice
Alternative 1. Alternative 3 contradicts the table (400 would be unreachable),
and restricting to http/https also keeps the fetcher from reading local files
through `file://`.

### Risk: 25
Most likely author preference if different: `ftp://`/`file://` sources
surfacing as 404 rather than 400.

---

## T9. Which remote responses count as a "remote HTTP error"

### Spec Text
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Any status `>= 400` (404, 403, 500, ...), plus connection/timeout/DNS
   failures. Redirects are followed first.
2. Only 4xx, with 5xx surfacing as 502/500.
3. Anything other than exactly 200.

### Choice
Alternative 1. The spec collapses every remote failure into one row, and
following redirects is the default behaviour of any HTTP client the author
would have used.

### Risk: 15
Most likely author preference if different: treating a 3xx that is not followed
as an error too.

---

## T10. Converting the same source twice

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Re-fetch the source every time and overwrite the stored dataset, always
   returning the same endpoint.
2. Serve the cached dataset without a second network request.
3. Return an error/conflict on the second conversion.

### Choice
Alternative 1. The spec pins the *endpoint* to the URL, not the payload, and a
second call with a different `charset` clearly has to change what is stored.
Re-fetching keeps the dataset current and keeps the two parameters meaningful.

### Risk: 20
Most likely author preference if different: caching, so the source is fetched
only once per URL.

---

## T11. Whether the row limit is adjustable

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. A fixed limit of 100 with no override.
2. "Default" implies an override: accept an optional `limit` query parameter,
   defaulting to 100.
3. An override plus `offset` paging.

### Choice
Alternative 2, with unusable values (non-numeric, zero, negative) falling back
to 100 rather than erroring. Calling 100 a *default* only makes sense if it can
be overridden, and a caller who never sends `limit` sees exactly the fixed
behaviour of alternative 1.

### Risk: 20
Most likely author preference if different: a hard-coded 100 that ignores
`limit` entirely.

---

## T12. Surrounding whitespace in cells

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.

### Alternatives
1. Trim whitespace only to decide the type; emit text cells exactly as they
   appear in the source (` 42 ` → `42`, ` x ` → `" x "`).
2. Strip every cell, so text values lose their padding too.
3. Strip nothing, so ` 42 ` stays text.

### Choice
Alternative 1. It matches an `int()`/`float()` based implementation (both of
which ignore surrounding whitespace) while leaving text content untouched, as
"strings remain text" asks.

### Risk: 20
Most likely author preference if different: stripping text cells as well.

---

## T13. Header cell handling

### Spec Text
> ```json
> "columns": ["<col1>", "<col2>", "..."]
> ```

### Alternatives
1. Header cells are always strings, trimmed, with a leading BOM removed;
   duplicate and empty names are preserved as they appear.
2. Apply type inference to the header too, so a numeric header becomes a number.
3. De-duplicate or auto-name empty headers (`col_2`, `Unnamed: 2`).

### Choice
Alternative 1. The response schema types `columns` as strings, and renaming
columns would break "columns ... follow source column order" as a faithful echo
of the header row.

### Risk: 15
Most likely author preference if different: leaving the BOM or the surrounding
whitespace on the first column name.

---

## T14. Empty cells

### Spec Text
> - Strings remain text.

### Alternatives
1. An empty cell is the empty string `""`.
2. An empty cell is JSON `null`.

### Choice
Alternative 1. `null` is not one of the three documented value kinds, and an
empty CSV field is textually empty rather than absent.

### Risk: 15
Most likely author preference if different: `null` for empty cells.

---

## T15. Wrong HTTP method on a known route

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` → 405 (JSON envelope), since the route exists.
2. `POST /convert` → 404, treating "route" as method + path.

### Choice
Alternative 1. The spec constrains *unknown* routes; `/convert` is known, and
405 is the standard (and framework-default) answer for a method mismatch. The
error body still uses the `{"ok": false, "error": ...}` envelope.

### Risk: 15
Most likely author preference if different: 404 for any request that does not
match a documented method + path pair.

---

## T16. The delimiter candidate set

### Spec Text
> minimum supported delimiters are `,`, `;`, and `\t`.

### Alternatives
1. Exactly `,`, `;`, `\t`.
2. Those three plus `|` (explicitly allowed by "minimum supported").
3. Full `csv.Sniffer` auto-detection over any punctuation, which can pick `:`
   or `.` for files of times or decimals.

### Choice
Alternative 2. "Minimum" invites a superset, `|` is a conventional CSV
delimiter, and a closed candidate list avoids `csv.Sniffer` choosing `:` for a
column of `08:30` style values — which would contradict the type-handling rule.

### Risk: 10
Most likely author preference if different: only the three listed delimiters,
so a pipe-separated file would be read as a single column.

---

## T17. Which CORS headers to send

### Spec Text
> Include CORS headers for browser access.

### Alternatives
1. `Access-Control-Allow-Origin: *` plus allowed methods/headers on every
   response, including errors.
2. Only echo the request `Origin`, with credentials support.
3. Only on successful responses.

### Choice
Alternative 1. The API is read-only and unauthenticated, so a wildcard origin
is the useful reading of "browser access"; a browser also needs the headers on
error responses to read the status.

### Risk: 8
Most likely author preference if different: origin echoing instead of `*`.
