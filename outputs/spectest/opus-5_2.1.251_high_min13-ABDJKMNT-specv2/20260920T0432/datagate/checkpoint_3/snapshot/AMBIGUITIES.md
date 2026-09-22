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

### Update (filtering increment)
Confirmed by "Params without `_` and without `__` are ignored as filters": a
parameter that is neither a control nor a filter — `limit` among them — is
silently ignored rather than rejected.

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

## T17: How `exact`/`contains` see cells that were typed as numbers

### Spec Text
> `exact`: case-sensitive string equality.
> `contains`: case-sensitive substring.

### Alternatives
1. String comparators only ever match cells still held as text; a numeric cell
   can never satisfy `exact`/`contains`.
2. Compare against the stored cell rendered as text (`str(cell)`), so
   `age__exact=36` matches the row whose `age` is the number `36`.
3. Keep the original source spelling of every cell alongside the typed value and
   compare against that, so `n__exact=1e3` matches a cell written `1e3` even
   though it is stored as `1000.0`.

### Choice
Alternative 2. "String equality" describes how the comparison is made, not which
cells are eligible, and a filter language where `age__exact=36` silently matches
nothing would be a trap. Rendering the typed value keeps one representation of
the dataset in memory and agrees with what the response shows the client, which
is the value a caller copies into a filter. Cells whose source spelling is lost
by typing (`+5` → `5`, `1e3` → `1000.0`, `36.0` → `36.0`) therefore match their
rendered form, not their original one.

### Risk: 25
Author most likely prefers: the same `str(cell)` rendering — a fixture filtering
`exact` on an exponent- or plus-signed source spelling would flip this.

## T18: Which parameter names are filters at all

### Spec Text
> Control params (names beginning with `_`) are not filters.
> Params without `_` and without `__` are ignored as filters.

### Alternatives
1. A name is a filter when it contains `__`, unless it begins with `_`; anything
   else is ignored. `_age__less=40` is an (unknown) control and ignored, and
   `age_less=40` is ignored because it carries no separator.
2. Only the documented control names are exempt, so `_age__less=40` is a filter
   on a column named `_age` and 400s as an unknown column.
3. Read "without `_`" strictly: any name containing an underscore anywhere and
   lacking `__` is an error rather than ignored, so `age_less=40` is a 400.

### Choice
Alternative 1. The spec defines the control namespace by prefix — "names
beginning with `_`" — so the prefix, not a list of known control names, decides
what is not a filter; unknown controls were already ignored in earlier
increments. The ignore rule then reads as its contrapositive: a filter needs the
`__` separator, and a name that has neither marker is simply not addressed to
this feature. Nothing in the error table covers "param that is neither a control
nor a filter", which confirms it is silence rather than a 400.

### Risk: 20
Author most likely prefers: the same prefix-then-separator test; an
implementation that strips only known control names would 400 on
`?_age__less=40`.

## T19: Splitting `<column>__<comparator>` when the column contains `__`

### Spec Text
> `<column>__<comparator>=<value>`

### Alternatives
1. Split on the last `__` (`rpartition`): `first__name__exact` filters the
   column `first__name`, and `first__name` alone asks for a comparator called
   `name` (invalid comparator, 400).
2. Split on the first `__` (`partition`): `first__name__exact` filters a column
   `first` with comparator `name__exact` (invalid comparator, 400).
3. Require exactly two segments (`name.split("__")`), making any name with two
   separators a 400 outright.

### Choice
Alternative 1. The comparator is the fixed, closed part of the grammar and the
column name is the free part, so the rightmost separator is the one that is
unambiguously the grammar's; a header really containing `__` stays filterable.
All three readings reject the same names with the same status, so they differ
only on a dataset whose header carries the separator.

### Risk: 30
Author most likely prefers: `split("__")` with a two-segment requirement, which
would 400 on `first__name__exact`; every reading agrees on ordinary headers.

## T20: What makes a value "non-numeric" for `less`/`greater`

### Spec Text
> `less`: numeric strict less (`float` parse on stored and filter values).
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.
> Rows with non-numeric stored values are not matched for numeric comparators.

### Alternatives
1. "Numeric" is exactly what Python's `float()` accepts, as the spec's
   parenthesis says: surrounding whitespace, `1e3`, `1_000`, `nan` and `inf` all
   parse, and only a `ValueError` is a 400 (or, for a stored cell, a non-match).
2. Restrict to finite decimal literals, rejecting `nan`/`inf`/underscored
   spellings as non-numeric — matching the stricter typing rule that keeps such
   cells as text in the dataset.

### Choice
Alternative 1. The spec names the mechanism (`float` parse) rather than a grammar,
so a `try: float(...) except ValueError` is the literal implementation of the
sentence; keeping it literal also makes the stored and filter sides use the same
test, as the same parenthesis demands. Consequences are benign: a `nan` bound
compares false against every row, so it matches nothing, and a stored cell that
typing left as text but `float` accepts (`1_000`) participates numerically while
still rendering as text.

### Risk: 15
Author most likely prefers: the same bare `float()` attempt — a fixture asserting
`?x__less=nan` is a 400, or that a `1_000` cell never matches, would flip this.

## T21: What counts as a "duplicate filter key"

### Spec Text
> Duplicate filter keys are invalid (`HTTP 400`).

### Alternatives
1. The key is the whole parameter name: `age__less=40&age__less=50` is a
   duplicate, while `age__greater=30&age__less=45` is two distinct filters that
   AND together.
2. The key is the column: any column filtered twice is a 400, so a range query
   is impossible.

### Choice
Alternative 1. "Filter key" is the parameter name the previous section defines,
and the spec states in the same list that multiple filters are ANDed — a rule
with no purpose if a second condition on one column were illegal. Identical
repeated values are rejected too: the spec makes repetition itself the fault, as
it already does for repeated control parameters.

### Risk: 20
Author most likely prefers: the same per-name rule; an implementation keying on
the column would 400 on `?age__greater=30&age__less=45`.

## T22: The query timeout

### Spec Text
> Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. A wall-clock budget for the whole read, checked while the rows are scanned,
   raising the 400 envelope when the budget is spent.
2. A limit on the work requested rather than on time (a row or filter cap),
   reported as a timeout.
3. Nothing to implement: with an in-memory store no read can time out, so the
   row is unreachable.

### Choice
Alternative 1. The condition is named after time, so time is what it measures;
an in-memory scan is bounded only by dataset size and filter count, which the
client controls, so a budget is the honest guard. The spec gives no number, so
the budget is a single module constant (`QUERY_BUDGET_SECONDS`, 5s) rather than
a tunable parameter, and it is checked during the row scan — the one stage whose
cost grows with the request.

### Risk: 8
Author most likely prefers: the same time budget with some other duration; the
value is unobservable for datasets a test can build, so only a fixture that
forces a timeout could disagree.

## T23: Is `rowid` filterable?

### Spec Text
> | Unknown filter column | 400 |
> Column matching is exact and case-sensitive.
> `rowid` is not in `columns`.

### Alternatives
1. `rowid` is a filterable pseudo-column, since the response can carry it.
2. Filterable columns are exactly the source columns, so `rowid__greater=2` is an
   unknown column (400) unless the header really has a `rowid` column.

### Choice
Alternative 2, consistently with [T16] for `_sort`: the spec says outright that
`rowid` is not in `columns`, and filters are defined over columns. One column
namespace serves sorting and filtering, so a caller cannot sort by a name it may
filter on, or the reverse.

### Risk: 20
Author most likely prefers: the same rejection; an implementation exposing
`rowid` as a pseudo-column returns 200 for `?rowid__greater=2`.

## T24: Do rowids follow filtering?

### Spec Text
> Filtering precedes sorting.
> `total` counts filtered rows before pagination.

### Alternatives
1. `rowid` stays the row's position in the source file, so a filtered response
   can begin at `rowid` 7 and skip numbers.
2. Rowids are assigned after filtering, numbering the surviving rows 2, 3, 4 …

### Choice
Alternative 1. `rowid` was defined as the row's source line ([T11]); it
identifies a row rather than describing a response, so it cannot depend on which
filters a request happened to send. It is also what makes a filtered row
traceable back to the CSV.

### Risk: 12
Author most likely prefers: the same source numbering, since filtering is applied
to already-numbered rows in the obvious implementation.

## T25: Is the comparator case-sensitive?

### Spec Text
> | Invalid comparator (`exact|contains|less|greater`) | 400 |
> Column matching is exact and case-sensitive.

### Alternatives
1. Comparators match exactly, so `age__LESS=40` is an invalid comparator (400).
2. Comparators are matched case-insensitively; only column names are declared
   case-sensitive.

### Choice
Alternative 1. The four comparators are given in lower case as a closed set, and
the spec's only relaxation elsewhere is toward strictness, never away from it. A
case-folding comparator lookup would also have to decide what to do with a
column whose name differs from another only in case, which the spec settles in
the opposite direction.

### Risk: 8
Author most likely prefers: the same exact match on the comparator word.
