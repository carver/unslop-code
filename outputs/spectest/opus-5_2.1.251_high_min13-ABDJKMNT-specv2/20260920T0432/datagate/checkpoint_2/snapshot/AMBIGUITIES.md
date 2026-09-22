# Ambiguities

Numbered record of spec under-specification, the interpretation chosen, and the
risk that the spec author's own implementation reads it differently.

## T1: Derivation of the dataset id

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.
> Same `source` URL always maps to the same dataset id.

### Alternatives
1. Hash the exact `source` query-parameter string (e.g. sha256, truncated).
2. Normalise the URL first (lowercase host, strip default port, sort the query
   string, drop a trailing `/`) and hash that, so `http://H/a.csv` and
   `http://h/a.csv` share one id.
3. Allocate a sequential counter or random uuid per distinct URL string, kept in
   a map.

### Choice
Alternative 1: `sha256(source_string).hexdigest()[:16]`, keyed on the exact
string as received. The spec says "the same `source` URL string", which points
at string identity rather than URL equivalence, and a pure function of the
string also satisfies "always maps to the same dataset id" across restarts.
The concrete id scheme is unobservable: a conforming test can only assert that
two calls agree and that the endpoint has the `/datasets/<id>` shape.

### Risk: 5
Author most likely prefers: a hash of the raw string too (md5/sha1/sha256, any
truncation) — only a test asserting a literal id value could tell the difference.

## T2: A well-formed charset name whose codec cannot decode the bytes

### Spec Text
> | Unsupported or malformed `charset` | 400 |

### Alternatives
1. Only an unknown/ill-formed codec *name* is a 400; a real codec that hits
   undecodable bytes falls back to lenient decoding (`errors="replace"`) and the
   request succeeds.
2. Decode strictly: both an unknown codec name (`LookupError`) and a
   `UnicodeDecodeError` produce 400.

### Choice
Alternative 2. Reading "malformed" as covering the charset/content pair is the
only reading under which a caller-supplied-but-wrong `charset` is reported at
all, and a strict `decode()` wrapped in one `except (LookupError,
UnicodeDecodeError)` is the natural implementation of that table row. Silently
replacing bytes would hand back mojibake under `"ok": true`.

### Risk: 35
Author most likely prefers: same strict behaviour, but a fixture that feeds
latin-1 bytes with `charset=utf-8` and expects a lenient `200` would flip this.

## T3: "detect unambiguous encoding from content, else latin-1"

### Spec Text
> `charset` ... If omitted, detect unambiguous encoding from content, else latin-1.

### Alternatives
1. Run a statistical detector (chardet / charset-normalizer) and use its best
   guess whenever confidence is high, else latin-1.
2. Only accept detections that cannot be anything else: a BOM, or bytes that
   decode cleanly as UTF-8; everything else is latin-1 (which never fails).

### Choice
Alternative 2. "Unambiguous" is doing real work in that sentence — a detector's
top guess between cp1252/latin-1/iso-8859-15 is precisely an *ambiguous*
detection, and the spec's own fallback is latin-1, the encoding those guesses
disagree about. BOM- and UTF-8-based detection is also deterministic, which
"Type inference is deterministic / no dependence on locale" asks for.

### Risk: 15
Author most likely prefers: the same UTF-8-then-latin-1 ladder; divergence only
shows on a cp1252-specific fixture (smart quotes, en dash) decoded by a detector.

## T4: Which literals become JSON numbers

### Spec Text
> - Integers/decimals are JSON numbers.
> - Time-like values (for example `08:30`, `9:15`, `12:00`) remain text.

### Alternatives
1. Naive `int(v)` / `float(v)` in a try/except: this also converts Python-only
   spellings such as `1_000`, `nan`, `inf`, `  42  `.
2. Regex-gated conversion: optional sign, digits, optional fraction, optional
   exponent — `007` → `7`, but `1_000`, `nan`, `inf`, `1,5`, `08:30` stay text.

### Choice
Alternative 2, with surrounding whitespace stripped before the test. `nan`/`inf`
are not representable in JSON, and `1_000` parsing as 1000 is an artefact of
Python's literal grammar rather than anything a CSV author means. Leading zeros
(`007` → `7`) are kept converting, because a bare digit string is an integer by
the spec's own sentence and the carve-out named is only time-like values.

### Risk: 25
Author most likely prefers: naive `int()`/`float()` — a `007` or `00123` zip-code
fixture expecting the text form is the most likely way this diverges.

## T5: "Default row limit is 100"

### Spec Text
> `rows` returns at most 100 items (or all rows if fewer).
> Default row limit is 100.

### Alternatives
1. 100 is a hard cap; `/datasets/<id>` takes no parameters.
2. 100 is the *default* of an optional `limit` query parameter, which callers
   may raise or lower.

### Choice
Alternative 2, implemented so the documented behaviour is untouched: with no
`limit` (or an unparseable/non-positive one) the response holds at most 100
rows. The word "default" only means something if the limit is overridable, and
honouring an explicit `limit` cannot break a test that never sends one.

### Risk: 15
Author most likely prefers: a hard `[:100]` slice — divergence needs a fixture
that actually passes `limit`.

### Update (pagination increment)
Resolved by the current spec: the overridable limit is spelled `_size`
(positive integer, default `100`), and an invalid value is a 400 rather than a
silent fallback. The invented `limit` parameter was dropped; it is now just an
unrecognised query parameter and is ignored.

## T6: What counts as "non-tabular content"

### Spec Text
> | Non-tabular content | 400 |
> Delimiter must be inferred from input, if present; minimum supported
> delimiters are `,`, `;`, and `\t`.
> A valid file requires at least one header row and one data row.

### Alternatives
1. Anything that yields a header line plus one more line is tabular; a body with
   no delimiter at all is a valid single-column dataset ("if present").
2. Tabular means a delimiter was actually inferred: no `,`/`;`/`\t` structure
   (prose, HTML, a JSON document, binary) is a 400.

### Choice
Alternative 2, plus an explicit rejection of bodies that begin with `<`, `{` or
`[`, or that contain NUL bytes. `csv.Sniffer(delimiters=",;\t")` — the obvious
implementation of the delimiter sentence — raises "Could not determine
delimiter" on undelimited text, which makes 400 the natural outcome there; and a
"non-tabular" fixture is far more likely to be an HTML error page or JSON blob
than a legitimate one-column CSV.

### Risk: 35
Author most likely prefers: the same delimiter-required rule; a single-column
CSV fixture expected to convert successfully would flip this.

## T7: Rows whose field count differs from the header

### Spec Text
> The endpoint returns stored rows and columns, in source order.
> `columns` and each row follow source column order.

### Alternatives
1. Pad short rows with empty strings and drop fields past the header width, so
   every row is rectangular.
2. Keep rows exactly as parsed, with ragged lengths.
3. Reject the file as non-tabular.

### Choice
Alternative 1. The response shape pairs one `columns` list with row lists, so a
client indexes rows by column position; ragged rows would silently misalign, and
rejecting the whole file over one short line is harsher than the spec's error
table suggests (it lists no such condition).

### Risk: 30
Author most likely prefers: rectangular padding via `csv.DictReader`-style
`restval`; an implementation that preserves ragged rows verbatim would differ on
any jagged fixture.

## T8: Re-converting a `source` that is already stored

### Spec Text
> `/convert` returns the same endpoint for the same `source` URL string.

### Alternatives
1. Short-circuit: if the id is already known, return the endpoint without
   re-fetching.
2. Always fetch, parse and overwrite the stored dataset under the same id.

### Choice
Alternative 2. The sentence constrains the *endpoint*, not the freshness of the
data, and a second call carrying a different `charset` must be able to correct
the stored decoding. It also keeps `/convert`'s error table honest: a source
that has since broken still reports 404 rather than a stale success.

### Risk: 10
Author most likely prefers: also re-fetching; a cache-first implementation only
differs on a fixture that changes the remote body or charset between calls.

## T9: Which URLs are "invalid" (400) versus "unreachable" (404)

### Spec Text
> | Invalid URL | 400 |
> | Source unreachable or remote HTTP error | 404 |

### Alternatives
1. Syntactic check only: anything `urlparse` accepts is valid, so `file:///etc/
   passwd` or `ftp://host/x` proceeds to the fetch and fails as unreachable.
2. Valid means a fetchable http/https URL with a host: any other scheme, or a
   missing scheme/host, is a 400 before any network call.

### Choice
Alternative 2. `/convert` is defined over "URL of the remote CSV file" served
over HTTP (its failure mode is "remote HTTP error"), so a non-HTTP scheme is a
caller mistake, not an unreachable host — and it keeps the server from reading
local files. A bare `not-a-url` also lands in 400 under both readings.

### Risk: 15
Author most likely prefers: the same scheme+host validation; a fixture using a
non-http scheme and expecting 404 is the divergence.

## T10: Known route, wrong method

### Spec Text
> All errors are JSON; unknown routes return `HTTP 404`.

### Alternatives
1. `POST /convert` is not an "unknown route": answer 405 with the JSON envelope.
2. Anything that is not one of the two documented GET routes is unknown: 404.

### Choice
Alternative 1. The sentence's subject is the route, and `/convert` exists; 405
with `{"ok": false, "error": ...}` satisfies "all errors are JSON" while keeping
the more informative status. CORS headers and the envelope are applied to every
error status regardless.

### Risk: 15
Author most likely prefers: 405 as well (Flask's default status for the case) —
a fixture asserting 404 for `POST /convert` would flip this.

## T11: What `rowid` counts

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number, starting at the header).

### Alternatives
1. The header is row 1, so the first data row is `rowid` 2 and data row *i*
   (0-based) is *i* + 2.
2. "1-based" applies to the data rows, so the first data row is `rowid` 1 — the
   parenthetical merely says counting includes the header line.
3. The true physical line number in the downloaded file, so blank lines and
   embedded newlines inside quoted fields shift later rowids.

### Choice
Alternative 1, counted over parsed records: `rowid = index + 2`. "Starting at
the header" only adds information under this reading — if data rows were
numbered from 1 the header would be irrelevant to the count. Physical line
numbers are not reconstructible from the stored rows (the parser already drops
records that hold no content), and the two agree on every well-formed CSV.

### Risk: 20
Author most likely prefers: the same header-is-row-1 numbering; a fixture whose
first data row expects `rowid` 1 would flip this.

## T12: A bad `_sort` when `_sort_desc` also present

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. `_sort_desc` takes precedence outright: the losing `_sort` is never looked
   at, so `?_sort=nope&_sort_desc=name` sorts descending by `name` and returns
   200.
2. Every sort parameter present is validated first, so a bad `_sort` is a 400
   even when `_sort_desc` would have won.

### Choice
Alternative 1. "Wins" describes which parameter selects the ordering, and the
natural implementation reads `_sort_desc` first and only falls back to `_sort`
when it is absent — an ignored parameter has no value to reject. The validation
sentence then applies to whichever parameter actually chose the order.

### Risk: 35
Author most likely prefers: the same precedence-first reading; an
implementation that validates both parameters up front returns 400 for
`?_sort=nope&_sort_desc=name`.

## T13: Sorting a column that mixes numbers and text

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.

### Alternatives
1. Compare cells directly, which raises `TypeError` between `int` and `str` and
   turns the request into a 500.
2. Compare everything as text (`str(cell)`), so `10` precedes `3`.
3. Order by type first — numbers ascending, then text ascending — so each group
   is sorted the way its own type implies.

### Choice
Alternative 3. Type coercion happens at parse time, so a column of numbers with
one stray label is a normal outcome of ingestion rather than a client error, and
a documented sort must still return rows. Numbers keep numeric order (`3` before
`10`), which is the point of having coerced them, and text keeps its own order.

### Risk: 30
Author most likely prefers: a key that stringifies mixed cells; note the three
readings only differ on a fixture that actually mixes types in the sort column —
a column of one type sorts identically under all of them.

## T14: How strictly `_size`/`_offset` are parsed

### Spec Text
> `_size` (positive integer, default `100`) ... `_offset` (non-negative
> integer, default `0`) ... Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. `int(value)` in a try/except: this also accepts `+5`, surrounding
   whitespace, and non-ASCII digits such as `٣`.
2. A strict ASCII digit string (`[0-9]+`) plus the range check, so `+5`, ` 5`,
   `5.0` and `٣` are all 400.

### Choice
Alternative 2. The parameters are spelled as plain counts in the spec, and an
HTTP query parameter is text the client wrote deliberately; accepting Python's
wider integer grammar would make `_size=٣` and `_size=+5` behave differently
from every other malformed value the table sends to 400.

### Risk: 15
Author most likely prefers: a bare `int()` conversion — divergence needs a
fixture using `+5`, padded whitespace or non-ASCII digits, since `abc`, ``,
`1.5`, `-1` and `0` are 400 under both readings.

## T15: `_rowid=hide` when the shape has no `rowid`

### Spec Text
> `_rowid=hide` removes `rowid`.
> Each toggle is valid only with value `hide`; any other value is `HTTP 400`.

### Alternatives
1. `_rowid=hide` under `_shape=lists` is a no-op: the value is still validated,
   but there is nothing to remove and the response is 200.
2. Combining `_rowid` with a shape that has no `rowid` is a client error (400).

### Choice
Alternative 1. The error table lists exactly one `_rowid` failure — an invalid
*value* — and says nothing about combinations, so a well-formed toggle cannot be
an error. It also lets a client send `_rowid=hide` unconditionally regardless of
the shape it asks for.

### Risk: 20
Author most likely prefers: the same no-op; an implementation that rejects the
combination would 400 on `?_rowid=hide` with the default shape.

## T16: Is `rowid` sortable?

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`. ... unknown columns return
> `HTTP 400`.
> `rowid` is not in `columns`.

### Alternatives
1. `rowid` is a sortable pseudo-column, since it is a value the response can
   carry.
2. Sortable columns are exactly the source columns; `_sort=rowid` is an unknown
   column (400) unless the header really contains `rowid`.

### Choice
Alternative 2. The spec states outright that `rowid` is not in `columns`, and
`_sort` is defined over columns; sorting by `rowid` would also be a no-op
ascending, since stored order is already source order. A header that genuinely
contains a `rowid` column is treated as any other column — it sorts, and under
`_shape=objects` its value occupies the `rowid` key.

### Risk: 25
Author most likely prefers: the same rejection; an implementation that special-
cases `rowid` as sortable returns 200 for `?_sort=rowid`.
