# Ambiguities

Numbered record of under-specified points in the `datagate` spec, the reading
chosen for this implementation, and the risk that the spec author's own
implementation (and therefore the hidden tests) reads it differently.

## T1: Derivation of the dataset id

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. Deterministic digest of the exact `source` string (e.g. truncated SHA-256).
2. Digest of a *normalised* URL (lowercased host, sorted query, stripped
   default port), so `http://H/x` and `http://h/x` share an id.
3. Sequential counter (`1`, `2`, ...) kept in a source→id map.

### Choice
A 16-hex-character truncated SHA-256 of the raw `source` string, exactly as it
arrived. The spec says "the same `source` URL *string*", which points at byte
equality of the parameter rather than URL-semantic equality, and a digest keeps
ids stable across process restarts, which a counter does not.

### Risk: 5
Tests almost certainly assert that two `/convert` calls agree and that the id is
opaque, not its literal value. The author most likely also hashes the raw string.

## T2: Which literals become JSON numbers

### Spec Text
> - Strings remain text.
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Anything Python's `int()`/`float()` accepts becomes a number — this also
   converts `"007"` → `7`, `"1_000"` → `1000`, `"nan"`, `"inf"`, and `" 12 "`.
2. A strict decimal grammar: optional sign, digits, optional fraction, optional
   exponent — so `"007"` → `7` but `"1_000"`, `"nan"`, `"inf"` stay text.
3. Conservative: anything with a leading zero (`"007"`, `"01234"` zip codes) or
   an exponent stays text, only plain integers/decimals convert.

### Choice
Alternative 2. A regex grammar (`[+-]?\d+` for integers, digits with a fraction
and/or exponent for decimals) applied to the whitespace-stripped cell. It keeps
`"007"` → `7`, matching a plain `int()` implementation on the ordinary cases,
while excluding `nan`/`inf` (which are not valid JSON) and Python-only spellings
like `1_000` that no CSV author intends as numbers.

### Risk: 35
Leading zeros are the exposed edge: an author who wrote a zip-code or
product-code fixture would expect `"01234"` to stay text. The author most likely
prefers plain `int()`/`float()` coercion, which agrees with this choice
everywhere except `1_000`, `nan`, and `inf`.

## T3: What counts as "non-tabular content"

### Spec Text
> | Non-tabular content | 400 |
>
> - Delimiter must be inferred from input; minimum supported delimiters are
>   `,`, `;`, and `\t`.
> - A valid file requires at least one header row and one data row.

### Alternatives
1. Only the stated structural rule: reject when fewer than two rows are present.
2. Structural rule plus a column rule: reject when no supported delimiter splits
   the header into two or more fields (a single-column body is not a table).
3. Content sniffing: reject only recognisable HTML/JSON payloads.

### Choice
Alternative 2, plus an explicit markup guard: payloads whose first non-blank
character is `<`, `{`, or `[` are rejected immediately, and otherwise the
inferred delimiter must yield at least two columns and the file at least two
rows. "Delimiter must be inferred from input" implies that failing to infer a
delimiter is itself the failure mode, and an HTML page or prose blob is exactly
the content that produces one column.

### Risk: 40
A single-column CSV (`name\nalice\nbob`) is the exposed input: under this choice
it is a 400, under alternative 1 it is a valid one-column dataset. The author
most likely also requires two or more columns, since that is what a
`csv.Sniffer`-based implementation does when it raises on an undetectable
delimiter — but a deliberate one-column fixture would flip the result.

## T4: A well-formed charset name whose bytes will not decode

### Spec Text
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. 400 only for a codec name Python does not know (`charset=klingon`).
2. 400 for an unknown codec *and* for a known codec that raises
   `UnicodeDecodeError` on the fetched bytes.
3. Unknown codec → 400; undecodable bytes → decode with replacement characters
   and return 200.

### Choice
Alternative 2. "Unsupported *or malformed*" reads as two distinct failures — an
unusable name and a name that cannot be applied — and silently substituting
replacement characters would produce a dataset whose values are wrong.

### Risk: 20
The author most likely wraps the whole decode step in one handler, which behaves
identically. The divergent reading is alternative 3 (lossy decode, 200).

## T5: Invalid URL (400) versus unreachable source (404)

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. "Invalid" means unparseable or missing a scheme/host; anything parseable is
   attempted and network failures become 404.
2. "Invalid" also covers non-HTTP schemes (`ftp://`, `file:///etc/passwd`),
   which are rejected at 400 without a request.
3. Non-HTTP schemes are attempted and fail as 404.

### Choice
Alternative 2: the URL must parse, carry a host, and use the `http` or `https`
scheme; everything else is a 400 before any I/O. Fetching `file://` URLs from a
user-supplied parameter would also be an SSRF-flavoured footgun.

### Risk: 20
DNS failures and connection refusals are unambiguous 404s either way. The author
most likely prefers this reading too; the divergence is limited to a `ftp://` or
`file://` fixture, where they might expect 404.

## T6: Repeat `/convert` for an already-converted source

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Re-fetch and re-parse every time, overwriting the stored dataset; the id is
   stable because it is derived from the URL.
2. Short-circuit on a cache hit and return the endpoint without any network I/O.

### Choice
Alternative 1. The sentence constrains the *endpoint*, not the work done, and
re-fetching keeps the stored rows current and keeps error reporting honest — a
source that has started returning 500 correctly yields 404 on the second call.

### Risk: 15
Both readings agree on the documented assertion. A test that stops the origin
server and re-converts, expecting 200 from cache, would fail here; that fixture
seems unlikely.

## T7: "Default row limit is 100"

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. The limit is fixed at 100 and no override exists.
2. The word "default" implies an optional override, e.g. `?limit=N`.

### Choice
Support an optional `limit` query parameter (positive integer) that overrides the
default, and fall back to 100 when it is absent or unusable. The documented
behaviour — no parameter means 100 — holds either way, and an unrecognised
parameter is harmless to an implementation that ignores it.

### Risk: 10
Only a test asserting that `?limit=5` is an *error* would fail. The author most
likely has no override at all and simply ignores the parameter.

## T8: Rows whose field count differs from the header

### Spec Text
> `columns` and each row follow source column order.

### Alternatives
1. Pad short rows with empty strings and drop cells past the header width.
2. Keep ragged rows verbatim, so row lengths vary.
3. Reject the file as non-tabular.

### Choice
Alternative 1. A rectangular result is what a client indexing `rows[i][j]` by
column position needs, and the spec's row shape shows a fixed column order.

### Risk: 30
Ragged input is unlikely to be tested at all, but if it is, the author's
`csv.DictReader`-based implementation would also pad (with `None`, or with the
`restval`), and a `csv.reader`-based one would keep rows verbatim.

## T9: Wrong HTTP method on a known route

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` is a 405 (JSON envelope).
2. Only `GET` is routed, so any other method is an unknown route → 404.

### Choice
405 with the standard `{"ok": false, "error": ...}` body. The spec calls out
unknown *routes*, and `/convert` is a known route; 405 is the accurate status
and the envelope requirement is still met.

### Risk: 25
The author most likely also lets their framework emit 405, but a test asserting
"anything that is not a documented GET is 404" would prefer alternative 2.

## T10: Values that merely look numeric

### Spec Text
> Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Time-likeness needs an explicit rule (regex for `HH:MM`) before typing.
2. Time-like values fall out as text for free, because they fail the numeric
   grammar; no special case is needed, and the same applies to dates
   (`2026-09-19`), currency (`$5`), grouped numbers (`1,234`), and percentages.

### Choice
Alternative 2: a single numeric grammar decides, and everything it rejects stays
text. The spec's bullet is an illustration of the outcome rather than a separate
rule, and adding a dedicated time branch could only ever change behaviour for a
value the numeric grammar already refuses.

### Risk: 10
The observable behaviour is identical for every example the spec gives.

## T11: Header cells that are empty or duplicated

### Spec Text
> "columns": ["<col1>", "<col2>", "..."]

### Alternatives
1. Emit header cells verbatim, including `""` and repeats.
2. Synthesise names for blanks (`column_3`) and de-duplicate (`name_2`).

### Choice
Alternative 1. `columns` is described as a plain list of strings in source order,
and inventing names would break the "source column order" correspondence with
row positions.

### Risk: 15
A `DictReader`-based implementation would collapse duplicate headers, which is
the reading the author would most likely prefer if such a fixture exists.

## T12: How encoding is detected when `charset` is omitted

### Spec Text
> `charset` ... If omitted, detect encoding from content.

### Alternatives
1. Statistical detection (`charset-normalizer` / `chardet`).
2. Try UTF-8 first, fall back to a byte-preserving codec such as cp1252/latin-1.

### Choice
`charset-normalizer` for detection, with a UTF-8-then-latin-1 fallback when it
returns no candidate, and BOM stripping in both paths. Detection is what the
spec asks for literally, and latin-1 never fails, so detection always terminates.

### Risk: 15
Detectors disagree on short single-byte samples: a tiny cp1252 fixture with one
accented character could be detected as a different 8-bit codec and produce a
different character than the author's implementation yields. UTF-8 fixtures,
which are the common case, agree.
