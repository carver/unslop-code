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

### Resolved by the Pagination spec (2026-09-19)
The later spec names the override: `_size` (positive integer, default `100`). The
invented `?limit=` parameter has been removed; `limit` is now an unrecognised
parameter and is ignored. See T17 for what counts as a valid `_size`.

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

## T13: Where `rowid` starts counting

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number). `rowid` is not in `columns`.

### Alternatives
1. `rowid` numbers the data rows: the first data row is `1`.
2. `rowid` numbers the physical lines of the file: the header is line `1`, so the
   first data row is `2`.
3. `rowid` numbers the rows of the returned page, restarting at `1` per request.

### Choice
Alternative 1 — `rowid` is the 1-based index of the row among the dataset's rows,
assigned before sorting and pagination. "1-based" is there to rule out a
zero-based index, and "source-file" to rule out alternative 3 (a row keeps its id
however it is sorted or paged). The earlier spec calls `columns` a header *row*,
but the dataset's rows are the data rows, and numbering them from one is what
`enumerate(rows, 1)` gives.

### Risk: 30
The exposed assertion is `rows[0]["rowid"]`: `1` here, `2` under alternative 2.
The author most likely prefers this reading, but a fixture written as "row 2 of
the file" would flip it.

## T14: Validating the sort parameter that loses

### Spec Text
> If both are present, `_sort_desc` wins.
> Empty values or unknown columns return `HTTP 400`.

### Alternatives
1. Both parameters are validated whenever present, so `_sort=nope&_sort_desc=name`
   is a 400.
2. Only the parameter that takes effect is validated, so the same request sorts
   descending by `name` and returns 200.

### Choice
Alternative 2. "Wins" reads as a precedence rule that selects one column and
discards the other, which is what a branch of the form "use `_sort_desc` if
present, else `_sort`" does; the validation sentence then applies to the column
actually being sorted on. Repeats are still rejected for both parameters, since
that rule is stated separately and unconditionally.

### Risk: 30
Only a deliberate "invalid loser" fixture separates the readings. The author most
likely validates just the winner, but a stricter implementation that validates
every present sort parameter would return 400 there.

## T15: Ordering a column that mixes numbers and text

### Spec Text
> `_sort=<column>` sorts ascending by `<column>`.

### Alternatives
1. Compare values natively, which raises on `3 < "zed"` and would have to surface
   as a 500 or a 400.
2. Order by type first — numbers before text — then by value within each type.
3. Compare everything as its string form, so `10` sorts before `2`.

### Choice
Alternative 2: a sort key of `(0, value)` for numbers and `(1, value)` for text.
Type inference means one column can legitimately hold both (a numeric column with
a `n/a` cell), and the spec gives sorting no failure mode other than an empty or
unknown column, so an ordinary mixed column must still produce a 200.

### Risk: 35
Ordinary single-type columns agree under every reading. The author most likely
also groups numbers before text, but a fixture mixing types could expect text
first, or string-wise comparison of everything.

## T16: What "stable" means for a descending sort

### Spec Text
> Sorting is stable and applied before pagination.

### Alternatives
1. Descending is `sort(reverse=True)`: tied rows keep their source order.
2. Descending is an ascending sort followed by reversing the whole list, which
   also reverses tied rows.

### Choice
Alternative 1. Stability is the property that equal keys keep their input order,
and the spec states it for sorting as a whole rather than for the ascending case
only; `reverse=True` is the spelling that preserves it.

### Risk: 20
Only a descending fixture with tied keys distinguishes them. The author most
likely uses `reverse=True` as well, since that is the obvious one-liner.

## T17: Which integer spellings `_size` and `_offset` accept

### Spec Text
> `_size` (positive integer, default `100`) ... `_offset` (non-negative integer,
> default `0`) ... Invalid `_size`/`_offset` -> `HTTP 400`.

### Alternatives
1. Accept anything `int()` parses, which also allows `" 5 "`, `"+5"` and `"1_0"`.
2. Accept an optional sign followed by digits and nothing else, then apply the
   range check.
3. Accept digits only, so `"-1"` is rejected as malformed rather than as
   out of range.

### Choice
Alternative 2, reusing the integer grammar the value-typing code already applies
to cells: `_size=+5` is 5, `_size=-1` and `_size=0` are 400 for being out of
range, and `_size=`, `_size=abc`, `_size=1.5`, `_size=1_0` are 400 for not being
integers. Every reading rejects the same inputs; they differ only in which ones.

### Risk: 20
`_size=+5` is the exposed input: accepted here and under alternative 1, rejected
under a `str.isdigit()` implementation. The author most likely uses `int()` in a
`try`, which agrees except on `" 5 "` and `"1_0"`.

## T18: An invalid control parameter on an unknown dataset id

### Spec Text
> If `<id>` is unknown, return `HTTP 404`.
> | `_size` not a positive integer | 400 |

### Alternatives
1. Resolve the dataset first, so `/datasets/nope?_size=0` is 404.
2. Validate the query string first, so the same request is 400.

### Choice
Alternative 1. The dataset is the addressed resource and the control parameters
describe how to render it; validating `_sort` also requires the column list,
which only exists once the dataset is resolved.

### Risk: 25
Only a fixture combining a bad id with a bad parameter separates them. The author
most likely looks the dataset up first too, for the same reason.

## T19: `_rowid=hide` when the shape has no `rowid`

### Spec Text
> `_rowid=hide` removes `rowid`.
> Each toggle is valid only with value `hide`; any other value is `HTTP 400`.

### Alternatives
1. `_rowid=hide` is accepted in `lists` shape and does nothing, since there is no
   `rowid` to remove.
2. `_rowid=hide` with `_shape=lists` is a 400 as a contradictory request.

### Choice
Alternative 1. The error table lists exactly one failure for the toggles — a
value other than `hide` — so a valid value cannot be an error, and "removes
`rowid`" is satisfied trivially by a response that never had one.

### Risk: 10
Alternative 2 requires inventing an error condition the table does not list.

## T20: A control parameter repeated with the same value

### Spec Text
> Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
> `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`.

### Alternatives
1. Any second occurrence is a 400, even `?_size=5&_size=5`.
2. Only conflicting repeats are a 400; identical values collapse.

### Choice
Alternative 1. "Any repeated control parameter" is about the number of
occurrences, not about whether they agree, and the rule is easier to rely on when
it does not depend on the values.

### Risk: 10
The author most likely checks `len(getlist(name)) > 1`, which is this reading.

## T21: `_offset` past the end of the dataset

### Spec Text
> `_offset` (non-negative integer, default `0`) skips that many rows before
> returning.

### Alternatives
1. Return 200 with an empty `rows` and the unchanged `total`.
2. Return 404, treating the page as missing.
3. Return 400, treating the offset as out of range.

### Choice
Alternative 1. The error table lists only "not a non-negative integer" for
`_offset`, so a well-formed offset cannot fail; skipping every row simply leaves
nothing, and `total` still reports the count before pagination.

### Risk: 5
Nothing in the spec supports an error here, and the same is implied by `_size`
exceeding the available rows being explicitly harmless.

## T22: A source column literally named `rowid`

### Spec Text
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file
> row number). `rowid` is not in `columns`.

### Alternatives
1. The injected row number wins; the CSV column's value is unreachable in
   `objects` shape (it is still reachable in `lists` shape and in `columns`).
2. The CSV column wins, so `rowid` holds the cell value.

### Choice
Alternative 1. The spec defines `rowid` in an `objects` row as the source row
number, so the key must mean that regardless of the header; `columns` still lists
the source column, which is what "`rowid` is not in `columns`" describes as the
only special-casing.

### Risk: 15
A CSV with a `rowid` header is an unlikely fixture. An implementation that builds
the dict from the columns and then inserts `rowid` agrees with this choice; one
that spreads the columns over a `{"rowid": n}` base does not.

## T23: What `exact` and `contains` compare against

### Spec Text
> `exact`: case-sensitive string equality.
> `contains`: case-sensitive substring.

### Alternatives
1. Compare against the stored value rendered as text (`str(cell)`), so the typed
   `10` filters as `"10"` and `2.5` as `"2.5"`.
2. Keep the original CSV text of every cell alongside the typed value and compare
   against that, so `1e3` and `.5` still match their source spelling.
3. Only ever match text cells, so a numeric column can never satisfy `exact`.

### Choice
Alternative 1. The dataset holds typed values (`inference.py` turns numeric cells
into JSON numbers), and the spec describes string comparison without carving out
numeric columns, so the stored value is rendered and compared. `score__exact=10`
therefore matches the number `10`.

### Risk: 35
The readings differ whenever a number's source spelling differs from its rendered
form (`1e3` → `1000.0`, `.5` → `0.5`, `2.50` → `2.5`). The author most likely also
stringifies the stored value; a fixture using round numbers agrees either way, but
one filtering `exact` on a value like `2.50` would prefer the raw-text reading.

## T24: Where the key splits when a column name contains `__`

### Spec Text
> `<column>__<comparator>=<value>`

### Alternatives
1. Split at the *last* `__`, so a column may contain the separator and the trailing
   segment is always the comparator.
2. Split at the *first* `__`, so `a__b__exact` filters column `a` with comparator
   `b__exact` (invalid).

### Choice
Alternative 1. The comparator is drawn from a closed four-name set while column
names come from arbitrary CSV headers, so the fixed part belongs at the end; this
also keeps a header like `first__name` filterable.

### Risk: 15
Only a fixture with `__` inside a header name distinguishes them, and both readings
return 400 for `a__b__nonsense`. A `split("__")`-based implementation that rejects
more than two segments would differ on a column that contains the separator.

## T25: Which stored values count as non-numeric

### Spec Text
> Rows with non-numeric stored values are not matched for numeric comparators.
> `less`: numeric strict less (`float` parse on stored and filter values).

### Alternatives
1. "Non-numeric" means the `float` parse of the stored value fails; anything
   `float()` accepts compares.
2. "Non-numeric" means the cell was not typed as a number at ingestion, so text
   that Python would still parse (`nan`, `inf`, `1_0`) never matches.

### Choice
Alternative 1, because the spec names the `float` parse as the rule for stored
values. In practice the two agree for every cell typed by `inference.py`; they part
only on text cells whose spelling Python accepts but the stricter ingestion grammar
rejects.

### Risk: 10
Both readings exclude ordinary text like `n/a`, which is the natural fixture. Only a
CSV containing `inf` or `nan` in a numeric filter's column would tell them apart.

## T26: Which filter values count as numeric

### Spec Text
> For `less`/`greater`, non-numeric filter values return `HTTP 400`.

### Alternatives
1. Accept exactly what `float()` accepts, including `nan`, `inf`, `1_0` and padded
   whitespace.
2. Accept only the stricter decimal grammar used to type CSV cells, so `nan`, `inf`
   and `1_0` are `HTTP 400`.

### Choice
Alternative 1, matching the spec's own "`float` parse" wording for filter values.
`score__less=abc` and `score__less=` are 400; `score__less=nan` is accepted and
matches nothing, since every comparison with NaN is false.

### Risk: 20
Ordinary fixtures (`abc`, empty, `1,5`) are 400 under both readings. An author who
reuses their cell-typing regex for filter values would return 400 for `nan`/`inf`.

## T27: Parameters that start with `_` but look like filters

### Spec Text
> Control params (names beginning with `_`) are not filters.
> Params without `_` and without `__` are ignored as filters.

### Alternatives
1. Any name beginning with `_` is excluded from filtering, even `_note__exact`,
   and an unrecognised one is simply ignored (200).
2. Only the seven documented controls are excluded, so `_note__exact` is a filter
   on a column named `_note` and 400s as unknown.

### Choice
Alternative 1. The spec defines control params by their leading underscore rather
than by a list, and the existing service already ignores unrecognised parameters.

### Risk: 10
This needs a fixture that invents an underscore parameter with a comparator suffix.
A `key.startswith("_")` guard — the obvious implementation — agrees with this choice.

## T28: An empty column name or an empty comparator

### Spec Text
> `<column>__<comparator>=<value>`
> | Invalid comparator (`exact|contains|less|greater`) | 400 | ... |
> | Unknown filter column | 400 | ... |

### Alternatives
1. `__exact=x` begins with `_`, so the control-param rule takes it out of filtering
   and it is ignored (200); `name__=x` has an empty comparator and is 400.
2. `__exact=x` is a filter on the empty column name and is 400 as an unknown column.

### Choice
Alternative 1. "Names beginning with `_`" is a purely syntactic rule, and `__exact`
begins with `_`; nothing after that rule reaches the filter parser. An empty
comparator is a different case: `name__` does not begin with `_`, so it is a filter
whose comparator is not one of the four.

### Risk: 10
`__exact=x` is an odd fixture; the ordering of the underscore guard before the split
is what decides it, and that ordering is the natural one to write.

## T29: An empty value for `exact` or `contains`

### Spec Text
> `<column>__<comparator>=<value>`
> | Comparator target not numeric (`__less`/`__greater`) | 400 | ... |

### Alternatives
1. An empty value is a legal filter: `note__exact=` keeps rows whose cell is empty,
   and `note__contains=` keeps every row.
2. An empty value is malformed and 400s for every comparator.

### Choice
Alternative 1. The error table makes an empty value a failure only for the numeric
comparators, where it cannot be parsed as a float; for string comparators the empty
string is a perfectly good operand, and CSV cells may themselves be empty.

### Risk: 15
An author who guards on "value is falsy" before dispatching would 400 instead. The
error table's explicit numeric-only wording is the stronger signal.

## T30: What counts as a duplicate filter key

### Spec Text
> Duplicate filter keys are invalid (`HTTP 400`).

### Alternatives
1. The key is the whole parameter name, so `name__exact` twice is 400 while
   `name__exact` plus `name__contains` is a legal pair of ANDed filters.
2. The key is the column, so any two filters on one column are 400.

### Choice
Alternative 1. The spec says "filter keys", and the filter key is the parameter
name given in `<column>__<comparator>` form; the ANDing rule then makes two
comparators on one column the natural way to express a range.

### Risk: 10
Reading 2 would make `score__greater=1&score__less=8` an error, which contradicts
"Multiple filters are ANDed" for the most obvious use of AND.

## T31: How long a query may run before it times out

### Spec Text
> Query timeout returns `HTTP 400`.
> | Query timeout | 400 | `{"ok": false, "error": "<message>"}` |

### Alternatives
1. A wall-clock budget for the whole dataset query, checked while scanning rows.
2. A budget for filtering alone.
3. A per-request override (`_timeout=`), which the spec never lists.

### Choice
Alternative 1, with the budget as `timing.QUERY_TIMEOUT_SECONDS` (5 seconds). The
spec gives no number and no parameter, so the timeout is a property of the service;
checking it during the row scan and again after sorting means a query aborts
wherever it spends its time, and no in-memory dataset of realistic size reaches it.

### Risk: 25
Any specific duration is invented. A test can only exercise this by shrinking the
budget, which requires knowing the knob's name; an author whose timeout lives on a
differently named constant (or who only checks it inside the filter loop) would
disagree about which requests can time out at all.

## T32: The exact `Content-Type` of an export response

### Spec Text
> `GET /datasets/<id>/export` returns CSV bytes with:
>
> - `Content-Type: text/csv`

### Alternatives
1. Emit exactly `text/csv`, with no parameters.
2. Emit `text/csv; charset=utf-8`, which is what Flask appends to any text
   response by default and what a browser benefits from.

### Choice
Alternative 1: the header is set to the literal `text/csv`. The spec quotes the
header value in full, and a bare `text/csv` satisfies an equality assertion, a
`startswith` assertion and an `in` assertion alike, while the `; charset=utf-8`
form only satisfies the latter two.

### Risk: 5
The author's fixture most likely checks `startswith("text/csv")` or membership,
which both readings pass. Only an exact-equality assertion separates them, and
that assertion favours this choice.

## T33: Whether `/export` paginates by default

### Spec Text
> The CSV uses source column order and applies the same filters, sort, and
> pagination as `/datasets/<id>`.

### Alternatives
1. Export is a download of the *whole* filtered result, and `_size`/`_offset`
   only narrow it when explicitly given.
2. Export is exactly the page `/datasets/<id>` would have returned, so the
   default `_size=100` caps an unparameterised export at 100 rows.

### Choice
Alternative 2. "The same ... pagination as `/datasets/<id>`" names the whole
pagination behaviour of that endpoint, defaults included, and the natural
implementation reuses one `parse_controls` call for both routes. A reading where
the default silently differs between the two endpoints would make "the same"
false for the commonest request of all, the one with no parameters.

### Risk: 25
A fixture with more than 100 rows and no `_size` is the only way to see the
difference. An author who thinks of export as "download the dataset" would have
written the unbounded reading; the author most likely shares this endpoint's
control parsing, and therefore this choice.

## T34: Invalid `_shape`, `_rowid` or `_total` on `/export`

### Spec Text
> `_shape`, `_rowid`, and `_total` do not affect CSV output.

### Alternatives
1. The three parameters are ignored outright on `/export`, so `_shape=banana`
   is accepted there even though `/datasets/<id>` rejects it.
2. They are still validated exactly as on `/datasets/<id>` — an illegal value is
   `HTTP 400` — but a legal value changes nothing about the bytes.

### Choice
Alternative 2. The sentence constrains the *output*, not the validation, and
`/export` sharing one control parser with `/datasets/<id>` is both the simpler
implementation and the more coherent contract: a parameter never means one thing
on one route and nothing on its sibling.

### Risk: 20
A fixture sending `_shape=objects` to `/export` passes either way; only an
illegal value distinguishes them. The author most likely reuses the shared
parser and so also returns 400.

## T35: Whether the exported CSV carries a header row

### Spec Text
> The CSV uses source column order ...
> - export columns follow source column order.

### Alternatives
1. Data rows only, since the endpoint is described as returning the same rows
   `/datasets/<id>` would.
2. A header row of the source column names, then the data rows.

### Choice
Alternative 2. "Export columns follow source column order" is only observable in
the bytes if the column names are in the bytes, and a CSV download without a
header would not round-trip through `/convert`.

### Risk: 3
Effectively settled by the determinism clause; a headerless export would make
that clause untestable.

## T36: How an uploaded dataset's id is derived

### Spec Text
> Re-uploading the same file bytes yields the same dataset id.

### Alternatives
1. Hash the uploaded bytes, so identity is content-addressed and the filename,
   the field name (`file` vs `attachment`) and the multipart framing are all
   irrelevant.
2. Hash the bytes together with the filename, so `a.csv` and `b.csv` holding
   identical content are distinct datasets.
3. Reuse the URL-derived id scheme by synthesising a pseudo-URL from the
   filename, which would make re-uploading the same bytes under a new name a
   new dataset.

### Choice
Alternative 1: a truncated SHA-256 of the raw request part, matching the digest
scheme `/convert` uses for its URL (AMBIGUITIES T1). The spec conditions
identity on "the same file bytes" and mentions nothing else, so nothing else
enters the digest.

### Risk: 8
The stated requirement is satisfied by all three readings only when the filename
is held constant; a fixture that re-uploads the same bytes under a different
name would separate them. The author most likely hashes content alone.

## T37: A multipart body carrying both `file` and `attachment`

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`.

### Alternatives
1. Ambiguous request — `HTTP 400`.
2. `file` wins; `attachment` is ignored.
3. `attachment` wins.

### Choice
Alternative 2. The spec names `file` first and frames the pair as an inclusive
"or" of accepted spellings rather than a mutually exclusive choice; only the
absence of *both* is called out as an error, so the presence of both is not one.

### Risk: 12
Most implementations look the two fields up in the order the spec lists them,
which is this choice. An author who wrote a strict "exactly one" check would
return 400.

## T38: The 415/400 boundary for a bad upload

### Spec Text
> - non-multipart request: `HTTP 415`
> - malformed multipart or missing both `file` and `attachment`: `HTTP 400`

### Alternatives
1. 415 is decided purely by the request's media type: anything whose
   `Content-Type` is not `multipart/form-data` (including a missing one) is 415,
   and every failure after that point is 400.
2. 415 also covers a request that declares `multipart/form-data` but whose body
   cannot be parsed at all, since the payload is then not really multipart.

### Choice
Alternative 1. The spec lists "malformed multipart" under 400 explicitly, which
only makes sense if the media type alone decides 415. So the media type is
checked before the body is touched: a request with no `Content-Type`, a JSON
body, or a urlencoded form is 415, and a `multipart/form-data` request with a
missing boundary or a truncated body is 400.

### Risk: 5
The spec text separates these two cases itself; little room for divergence.

## T39: How the ingested format is recognised

### Spec Text
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
> ...
> Unrecognized format: `HTTP 400`.

### Alternatives
1. By the filename extension of the upload, or the path suffix of the `source`
   URL — the spec names the formats by their extensions.
2. By the `Content-Type` the origin server sent, or the multipart part's
   declared type.
3. By the leading bytes of the payload: the ZIP signature for `.xlsx`, the OLE2
   compound-document signature for `.xls`, and text otherwise.

### Choice
Alternative 3, content sniffing. A `source` URL need not end in any extension
(query strings, redirects and content-serving endpoints are normal), the origin
server's `Content-Type` is frequently `application/octet-stream`, and a test
client posting bytes will not always attach a truthful filename. Sniffing is the
only signal guaranteed to be present in every one of those cases, and it agrees
with the extension whenever the extension is honest.

### Risk: 15
A fixture serving a real workbook, however it is named, is classified correctly
by all three readings. They diverge only for a mislabelled file — a CSV named
`.xlsx`, say. The author most likely sniffs too, since extensions are absent
from the `/convert` contract entirely.

## T40: `charset` supplied for a spreadsheet source

### Spec Text
> `charset` applies only to text CSV sources.

### Alternatives
1. `charset` alongside an `.xls`/`.xlsx` source is a contradiction — `HTTP 400`.
2. `charset` is ignored for workbook sources; the request succeeds.

### Choice
Alternative 2. "Applies only to" describes where the parameter has an effect,
not where it is legal; the sentence exists to say that a workbook's text is not
decoded with the caller's codec, and turning a harmless parameter into an error
would need to have been stated as one under Error Handling, where it is not.

### Risk: 20
A fixture that converts a workbook while passing `charset=utf-8` separates the
readings. The author most likely ignores the parameter, since the CSV decode
step is simply never reached on the workbook path.

## T41: A worksheet only one column wide

### Spec Text
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. Apply the CSV rule, under which a table needs at least two columns because a
   single column means no delimiter was found (AMBIGUITIES T3).
2. Require only what this sentence requires — a header row and one data row —
   so a one-column sheet is a valid one-column dataset.

### Choice
Alternative 2. The two-column rule for CSV exists solely as evidence that
delimiter inference worked; a worksheet has explicit cell boundaries, so a
single column is unambiguous rather than suspicious. The spec spells out the
spreadsheet requirement in full here and says nothing about a column minimum.

### Risk: 25
Only a deliberately one-column workbook fixture separates the readings. An
author who funnels the worksheet grid through the same validator as parsed CSV
records would reject it, which is the likelier alternative.

## T42: Trailing empty rows and columns in a worksheet

### Spec Text
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.
> ...
> - spreadsheet columns preserve source order.

### Alternatives
1. Take the sheet's declared extent verbatim, so a workbook whose used range was
   widened by stray formatting gains empty trailing columns and blank rows.
2. Trim wholly-empty trailing rows and columns, then treat what remains as the
   table.

### Choice
Alternative 2. Spreadsheet formats routinely report a used range larger than the
data — a cleared cell keeps its row alive — and a phantom column would show up
as an unnamed header in every response and export. Trimming is confined to
*trailing* emptiness so that interior blank cells, which are real data, survive.

### Risk: 30
Fixtures written cell-by-cell through a library rarely exhibit the padding, so
the readings usually agree. They diverge on a sheet whose last row is blank, and
on whether a sheet padded to emptiness counts as non-tabular; the author most
likely reads the declared extent and lets empty trailing rows through as rows.

## T43: Integer cells read from `.xls`

### Spec Text
> - Integers/decimals are JSON numbers.
> ...
> `/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.

### Alternatives
1. Pass the library's value through as-is. The `.xls` format stores every number
   as a double, so the cell `36` arrives as `36.0` and serialises as `36.0`,
   while the same cell in a `.csv` or `.xlsx` yields `36`.
2. Render a float with no fractional part as an integer, so `36` is `36` in all
   three formats.

### Choice
Alternative 2. The spec gives one type-inference contract and then lists three
interchangeable source formats; a value that changes type with the container
would break that. `.xls` cannot distinguish `36` from `36.0` at all, so the
integer rendering is the only one that can ever match a caller's expectation.

### Risk: 30
Any `.xls` fixture with a whole number exposes this. An author who hands the
xlrd cell value straight to the JSON encoder would emit `36.0`, which is the
likeliest alternative.

## T44: An empty first sheet in front of a populated one

### Spec Text
> Only the first worksheet is ingested.
> The first sheet must be tabular (header + at least one data row) or `HTTP 400`.

### Alternatives
1. Fall through to the first sheet that *is* tabular, treating empty leading
   sheets as absent.
2. Reject the workbook with `HTTP 400`; the first sheet is the only candidate,
   whatever the rest of the workbook holds.

### Choice
Alternative 2, which is what the two sentences say when read together: the first
sheet is the one ingested, and it must be tabular or the request fails. A
fallback would also make ingestion depend on sheet contents in a way "only the
first worksheet" was written to rule out.

### Risk: 5
The spec is close to explicit here.

## T45: What "unrecognized format" rejects, and how

### Spec Text
> Unrecognized format: `HTTP 400`.

### Alternatives
1. Only formats that are positively identified as unsupported (PDF, images,
   archives) are rejected; anything else is attempted as CSV.
2. Anything that is not valid UTF-8 text, or that contains NUL bytes, is
   rejected as binary before parsing is attempted.

### Choice
Alternative 1. A payload that is neither a workbook nor a recognised binary
format is handed to the CSV reader, which already answers `HTTP 400` for content
that is not a table — so unrecognised input yields 400 either way, and the
lenient route additionally preserves the UTF-16 sources that the `charset`
contract requires, whose bytes are full of NULs.

### Risk: 10
Both readings produce 400 for every unsupported payload; only the error message
differs, and a ZIP or OLE2 file that is not a workbook is rejected explicitly
under this choice.

## T46: Non-file multipart parts named `file` or `attachment`

### Spec Text
> `POST /upload` accepts multipart form with field `file` or `attachment`.

### Alternatives
1. Only a part with a `filename` (a true file part) counts; a plain text field
   of that name is "missing the file field" — `HTTP 400`.
2. Either spelling counts, since the spec says "field", not "file part"; a
   value-only part is read as UTF-8 bytes.

### Choice
Alternative 2. The spec calls them fields, and the distinction between a
multipart part with and without a `filename` parameter is a detail of the
encoder, not something a caller sending CSV text would think to control.

### Risk: 10
Test clients almost always attach a filename, in which case both readings agree.
The author most likely reads the file-parts collection only, which would reject
the value-only form.

## T47: The dataset that `/export` names in its filename

### Spec Text
> - `Content-Disposition: attachment; filename="<dataset-id>.csv"`

### Alternatives
1. The dataset id exactly as it appears in the request path.
2. The id plus some rendering of the active query (filters, sort, page), so that
   two different exports of one dataset download under different names.

### Choice
Alternative 1: the literal path segment, unmodified and unquoted beyond the
surrounding double quotes. The spec gives the header as a fixed template with a
single substitution.

### Risk: 2
The header is quoted verbatim in the spec.

## T48: Whether `charset` takes part in the cache key

### Spec Text
> With caching enabled, repeated `/convert` requests for the same source URL can
> return the cached dataset id without re-downloading.

### Alternatives
1. The cache is keyed on the `source` URL alone, so a later request naming a
   different (or invalid) `charset` is still a hit and never decodes anything.
2. The cache is keyed on `(source, charset)`, so changing `charset` misses the
   cache and re-ingests under the same dataset id.
3. Keyed on `source`, but `charset` is still validated up front, so a hit with
   `charset=klingon-9` is `HTTP 400`.

### Choice
Alternative 1. The spec names the source URL as the thing that repeats, and the
dataset id is derived from the source URL alone ([[T1]]), so a hit can be decided
before any byte is fetched. `charset` only exists to decode a download, and on a
hit there is no download to decode.

### Risk: 30
A request that re-converts a cached source with a deliberately broken `charset`
is the exposed input: 200 here, 400 under alternative 3. The author most likely
also short-circuits on the source alone, since `charset` is consumed inside the
decoder rather than validated at the route.

## T49: `CACHE_ENABLED` unset versus set to an empty string

### Spec Text
> `/convert` caches results by default.
> `CACHE_ENABLED` accepts strict case-insensitive values:
> Invalid values fail startup.

### Alternatives
1. Unset means enabled; an empty value is not in either vocabulary, so it is
   invalid and fails startup.
2. Unset and empty are both "not configured", so both mean enabled.

### Choice
Alternative 1. "Invalid values fail startup" admits no empty-string exemption,
and an empty assignment is far more likely to be a broken deployment script than
a deliberate request for the default.

### Risk: 15
`CACHE_ENABLED=` is the exposed input. The author most likely reads the variable
with a default (`os.environ.get(..., "true")`), which also treats an explicit
empty value as invalid and agrees with this choice.

## T50: Surrounding whitespace in a `CACHE_ENABLED` value

### Spec Text
> `CACHE_ENABLED` accepts strict case-insensitive values:

### Alternatives
1. "Strict" means exactly the listed spellings modulo case; `" true"` and
   `"true "` fail startup.
2. The value is stripped before matching, since trailing whitespace in an env
   file is an accident rather than an intent.

### Choice
Alternative 1. The spec grants exactly one normalisation — case folding — and
calls the vocabulary strict; extending that to whitespace invents a second.

### Risk: 25
`CACHE_ENABLED="true "` is the exposed input. The author most likely writes
`raw.strip().lower()` out of habit, which would accept it.

### Resolved by a later spec revision
> Boolean values are strict: `1/true/yes/on` or `0/false/no/off` (case-insensitive, trimmed).

The configuration section settles this against the choice above: booleans are
trimmed before matching, so `" true"` and `"on\n"` are accepted. The
implementation and its tests now follow alternative 2 for every boolean setting,
`CACHE_ENABLED` included. An empty or whitespace-only value still fails startup,
since trimming it leaves nothing in the vocabulary (see T49).

## T51: What "any additional `force` value" rejects

### Spec Text
> `force` is a presence flag. If present once, it forces re-ingestion and
> replaces the cached dataset.
> Any additional `force` value is `HTTP 400`.

### Alternatives
1. "Additional" counts occurrences: one `force` is fine whatever it carries
   (`force`, `force=`, `force=0`, `force=whatever`), and a second occurrence is
   `HTTP 400`.
2. "Additional" means any value beyond bare presence: `?force` is fine and
   `?force=1` is `HTTP 400`.

### Choice
Alternative 1. "If present *once*" makes the count the thing being measured, and
it matches how this service already treats every repeated query parameter. A
presence flag is by definition indifferent to the value it carries, which rules
out reading the value itself as the error.

### Risk: 20
`?force=1` is the exposed input: accepted here, rejected under alternative 2.
The author most likely counts occurrences with `getlist`, since that is the same
check the control parameters already use.

## T52: `force` repeated while caching is disabled

### Spec Text
> If caching is disabled, `force` has no additional effect.
> Any additional `force` value is `HTTP 400`.

### Alternatives
1. The duplicate check is request validation and runs regardless, so
   `?force&force` is `HTTP 400` whether caching is on or off.
2. `force` is ignored entirely when caching is off, so a repeat is ignored too
   and the request succeeds.

### Choice
Alternative 1. "No additional effect" is about behaviour — a re-ingestion
already happens on every request — not about whether the parameter is still
parsed. A malformed request should not become well-formed because of a server
side setting the caller cannot see.

### Risk: 20
`CACHE_ENABLED=0` with `?force&force` is the exposed input. The author most
likely validates in the route before consulting the setting, which agrees.

## T53: How "fail startup" surfaces

### Spec Text
> Invalid values fail startup.

### Alternatives
1. Building the application raises, so both the CLI and any embedding test see
   the failure at construction time.
2. Only the CLI checks, exiting non-zero before the server binds.
3. The service starts and falls back to the default.

### Choice
Alternative 1, with the CLI turning the raised error into a non-zero exit and a
one-line stderr message. Checking at construction makes "startup" mean the same
thing however the app is launched, and alternative 3 contradicts "fail".

### Risk: 15
Both alternative 1 and 2 give a non-zero exit from `datagate.py start`. They
differ only for a test that builds the app in-process, which the author most
likely also does.

## T54: Whether `/upload` is affected by caching or `force`

### Spec Text
> `/convert` caches results by default.
> `force` is a presence flag.

### Alternatives
1. Caching and `force` belong to `/convert` only: an upload already carries its
   bytes, so it always parses and stores them.
2. `/upload` is content-addressed, so a repeated upload should also short-circuit
   when caching is enabled, and honour `force`.

### Choice
Alternative 1. Every sentence in this section names `/convert`, and the cost the
cache exists to avoid — re-downloading — does not exist for an upload. `force`
is therefore not a recognised parameter on `/upload`, including its repeat rule.

### Risk: 20
A repeated upload of identical bytes is indistinguishable under both readings
(same id, same parse), so only a duplicated `force` on `/upload` separates them.
The author most likely also scopes both to `/convert`.

## T55: Whether a cache hit is marked in the response

### Spec Text
> Cache responses are identical to fresh parse responses.

### Alternatives
1. Byte-for-byte the same envelope: `{"ok": true, "endpoint": "/datasets/<id>"}`
   with status 200 and no added field or header.
2. The same shape plus a cache indicator, such as `"cached": true` or a
   `X-Cache` header, on the grounds that "identical" only covers the id.

### Choice
Alternative 1. "Identical" is the strongest word available and the sentence
exists precisely to forbid a caller from telling the two apart.

### Risk: 5
The spec states the requirement directly.

## T56: Which end of the precedence list wins

### Spec Text
> Service configuration sources, in order of precedence:
> 1. Built-in defaults
> 2. `DATAGATE_CONFIG` file
> 3. Direct environment variables

### Alternatives
1. The list ascends: later sources override earlier ones, so a direct
   environment variable beats the config file, which beats the default.
2. The list descends, as "in order of precedence" often means in prose: the
   built-in defaults would win over everything.

### Choice
Alternative 1. Reading 2 makes the other two sources unreachable — a service
whose defaults outrank its own config file cannot be configured at all — so the
list can only be ascending.

### Risk: 2
Exposed by setting a key in both the file and the environment. Any working
implementation resolves this the same way.

## T57: What the config file counts as a comment or a blank line

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values, blank/comment
> lines ignored.

### Alternatives
1. `#` in the first non-whitespace position starts a comment line; a line that is
   empty or all whitespace is blank. `#` later in a line is part of the value.
2. Also strip trailing `#` comments from a value line.
3. Accept `;` as well as `#`, in the manner of INI files.

### Choice
Alternative 1. "Comment lines" names whole lines, not trailing fragments, and
stripping inline `#` would corrupt values that legitimately contain one. `#` is
the only comment marker used by the `KEY=VALUE` env-file convention this format
copies.

### Risk: 12
Exposed by `MAX_SOURCE_SIZE=100 # bytes`, which is 100 under alternative 2 and a
startup failure here. The author most likely also ignores whole lines only, but
a fixture with a trailing comment would separate us.

## T58: Keys in the config file that are not settings

### Spec Text
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. Unknown keys are ignored: "invalid config" means a malformed line or an
   unusable value for a known setting.
2. Unknown keys are themselves invalid config and fail startup.

### Choice
Alternative 1. A `DATAGATE_CONFIG` file is a deployment artefact that commonly
carries neighbouring variables, and the settings table defines the keys the
service reads rather than the keys the file may contain. Failing on an unknown
key would make the file unusable as a shared environment file.

### Risk: 25
Exposed by a config file carrying a stray key. The author most likely also
ignores unknown keys — reading a dict of values and looking up the five it knows
is the shorter implementation — but a strict fixture is easy to imagine.

## T59: The same key twice in the config file

### Spec Text
> The config file is `KEY=VALUE` lines

### Alternatives
1. The last assignment wins, as in a shell env file.
2. A repeat is invalid config and fails startup, matching how this service
   rejects every repeated query parameter.

### Choice
Alternative 1. Lines are read into a mapping in order, which is what every
`KEY=VALUE` file format does; the repeated-parameter rule elsewhere in the spec
governs a caller's request, not an operator's own file.

### Risk: 20
Exposed only by a file that assigns a key twice. The author most likely builds a
dict as they parse, which gives last-wins without deciding anything.

## T60: A config line with no `=`

### Spec Text
> The config file is `KEY=VALUE` lines, with commas for list values, blank/comment
> lines ignored.
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. A non-blank, non-comment line without `=` is invalid config: startup fails.
2. It is skipped like a blank line.

### Choice
Alternative 1. The format admits exactly three kinds of line — assignment, blank
and comment — so a fourth kind is the plainest example of "invalid config".
Silently skipping an operator's typo hides it.

### Risk: 18
Exposed by a garbage line in the file. The author most likely also raises, since
"invalid config" needs some input to refer to and a malformed line is the
obvious one. An empty key (`=1`) is rejected here for the same reason.

## T61: What `MAX_SOURCE_SIZE` accepts

### Spec Text
> | `MAX_SOURCE_SIZE` | integer bytes | unset |

### Alternatives
1. An optionally signed decimal integer, rejecting negatives: `0` is a valid
   limit that admits only empty payloads, and `-1`, `1.5`, `10MB`, `1_000` and
   `""` all fail startup.
2. Anything `int()` parses, so `-1` becomes a (never satisfiable) limit and
   `" 10 "`/`1_000` are accepted.
3. An empty value means "unset" rather than a failure.

### Choice
Alternative 1, with surrounding whitespace trimmed as the spec does for
booleans. A byte count cannot be negative, and a size suffix or a decimal point
is an operator error worth failing on rather than silently reinterpreting.

### Risk: 30
Exposed by `MAX_SOURCE_SIZE=-1` and by `MAX_SOURCE_SIZE=`. The author most
likely writes `int(raw)` without a sign check, which would accept `-1` as a
limit that rejects everything rather than failing startup.

## T62: Which bytes the limit is measured against

### Spec Text
> Enforced for `/convert` and `/upload`:
> - file size `= limit` accepted.
> - file size `> limit` => `HTTP 400` with standard envelope.

### Alternatives
1. The length of the payload actually obtained: the downloaded body for
   `/convert`, and the bytes of the `file`/`attachment` part for `/upload`.
2. For `/convert`, the origin's `Content-Length` header, checked before the body
   is read so an oversized download is never pulled.
3. For `/upload`, the whole request body including multipart framing.

### Choice
Alternative 1. "File size" is a property of the file, not of a header an origin
may omit or misreport, and the multipart envelope is transport rather than file.
The check therefore runs on the same bytes the parser would see, immediately
before parsing, on both routes.

### Risk: 15
Exposed by an upload whose part is at the limit but whose full request body is
over it, and by an origin that lies about `Content-Length`. The author most
likely also measures the payload, since both routes then share one check.

## T63: Whether a cache hit is size-checked

### Spec Text
> Enforced for `/convert` and `/upload`

### Alternatives
1. The limit guards ingestion: a `/convert` that answers from the stored dataset
   downloads nothing, so there is no file to measure and the request succeeds.
2. Every `/convert` is checked, so lowering the limit and restarting must make a
   previously cached oversized source start failing.

### Choice
Alternative 1. The limit is expressed in terms of file size, and a cache hit has
no file in hand; re-downloading one purely to reject it would undo the point of
the cache. With `CACHE_ENABLED=0` every request re-downloads and so is checked.

### Risk: 20
Exposed only by converting a source under one limit and then querying it under a
lower one within the same storage directory. The author most likely also checks
after the fetch, which agrees, but a fixture that lowers the limit across a
restart would separate us.

## T64: An `ORIGIN_ALLOWLIST` that parses to nothing

### Spec Text
> | `ORIGIN_ALLOWLIST` | list of domain suffixes | unset |
> No allowlist means all requests pass.

### Alternatives
1. An unset variable, an empty value and a value of only commas and whitespace
   all mean "no allowlist", so every request passes.
2. An empty value configures an allowlist with no members, which nothing can
   match, so every request is 403.

### Choice
Alternative 1. Splitting on commas and dropping blank entries is the natural
list parse, and `ORIGIN_ALLOWLIST=` reads as "not configured" rather than as
"deny everything" — a service that locks itself out on an empty assignment is
not what the default column describes. Entries are trimmed and any leading dot
is dropped, so `.example.com` and `example.com` behave alike.

### Risk: 22
Exposed by `ORIGIN_ALLOWLIST=`. The author most likely also treats a falsy list
as absent, since `if allowlist:` is the same guard as "if configured".

## T65: Which requests the allowlist guards

### Spec Text
> If configured, check every request before routing

### Alternatives
1. Literally every request: unknown paths, `/datasets/<id>`, `/export`, and
   `OPTIONS` preflights are all checked before the route is chosen, so a bad
   `Referer` is 403 even for a URL that would have been 404.
2. Only the ingestion routes, since those are the ones that reach out.
3. Every request except CORS preflights, which browsers send without a
   `Referer`.

### Choice
Alternative 1. "Every request before routing" says both which requests (all of
them) and when (ahead of route selection, so 403 outranks 404). Carving out
preflights would be a rule the spec does not state.

### Risk: 30
Exposed by an `OPTIONS` preflight with no `Referer`, which is 403 here, and by a
404 path with a bad `Referer`. The author most likely installs one
before-request hook with no method exemption, which agrees, but a preflight
carve-out is a plausible alternative if their CORS tests run under an allowlist.

## T66: A `Referer` that is present but has no hostname

### Spec Text
> 1. Require `Referer`.
> 2. Parse hostname.
> 3. Accept only hostnames matching any allowed suffix ...
> 4. Otherwise return `HTTP 403`.

### Alternatives
1. An empty header counts as missing, and a header that yields no hostname —
   `not-a-url`, `example.com/path` with no scheme, `https:///x` — fails step 3
   and is 403.
2. A bare `example.com` should be read as the hostname, since the intent is
   obvious.

### Choice
Alternative 1. Step 2 is "parse hostname", and a URL parser returns nothing for
a string with no authority; step 4 then catches it. Both readings return 403
for a host outside the allowlist, so the difference is only whether a
scheme-less `Referer` naming an *allowed* host is let through, and inventing a
scheme for it would weaken the check.

### Risk: 18
Exposed by `Referer: example.com` under `ORIGIN_ALLOWLIST=example.com`. The
author most likely calls `urlparse(...).hostname`, which also yields nothing
here.

## T67: The domain-boundary rule for suffix matching

### Spec Text
> Accept only hostnames matching any allowed suffix case-insensitively with
> domain-boundary rules.

### Alternatives
1. A hostname matches suffix `S` when it equals `S` or ends with `.S`. So
   `example.com` and `app.example.com` match `example.com`, while
   `notexample.com` and `example.com.evil.net` do not.
2. Strict subdomains only: `example.com` itself would not match `example.com`.
3. Plain string suffix, no boundary: `notexample.com` would match.

### Choice
Alternative 1. That is what "domain-boundary rules" means — the match must fall
on a label boundary — and excluding the apex would make an allowlist entry that
cannot admit its own domain. The comparison lowercases both sides; the port is
not part of the hostname, and a trailing dot on the hostname is stripped before
comparing.

### Risk: 8
Exposed by `notexample.com`, which the spec's phrase exists to reject. The apex
case is the only real variable and reading 2 is hard to defend.

## T68: How the absolute endpoint URL is built

### Spec Text
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request host.

### Alternatives
1. `https://` + the request's `Host` header verbatim + `/datasets/<id>`, keeping
   any non-default port the caller addressed.
2. Strip the port, since `https://host:8001` is unlikely to be reachable.
3. Use the `X-Forwarded-Host` header when present, as behind a TLS terminator.

### Choice
Alternative 1. "Using request host" names the host the request arrived with, and
dropping the port would produce a URL pointing somewhere the caller never
contacted. Honouring a forwarding header is a proxy policy the spec does not
mention.

### Risk: 20
Exposed by a test client whose `Host` carries a port — Flask's test client sends
`localhost` with no port, so a fixture would have to set one deliberately. The
author most likely uses `request.host`, which keeps the port.

## T69: Whether `REQUIRE_TLS` also rejects plaintext requests

### Spec Text
> ### TLS-aware endpoint URLs
> `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request host.

### Alternatives
1. The setting only decides the shape of the endpoint the two ingestion routes
   report; an `http` request still succeeds.
2. The name is taken at face value: with `REQUIRE_TLS=true`, a request that did
   not arrive over TLS is rejected.

### Choice
Alternative 1. The section is titled "TLS-aware endpoint URLs" and describes a
URL form; the error table lists no status for a plaintext request, which it
would have to if reading 2 were meant.

### Risk: 15
Exposed by any plaintext request under `REQUIRE_TLS=true` — including every test
the author writes for the absolute URL, which must itself be plaintext to reach
the app. That makes reading 2 largely self-defeating.

## T70: The default `STORAGE_DIR`

### Spec Text
> | `STORAGE_DIR` | path | implementation-defined |

### Alternatives
1. A fixed directory relative to the working directory, `./datagate_data`.
2. A fresh temporary directory per process, so nothing survives a restart unless
   the operator names a directory.
3. A fixed path under the system temp directory or `$XDG_DATA_HOME`.

### Choice
Alternative 1. The spec calls the default implementation-defined, so only the
behaviour around it is testable: the directory is created if missing and reusing
it preserves datasets. A visible, stable, relative directory keeps that true for
the default as well, which a per-process temp directory would not.

### Risk: 5
The spec explicitly declines to fix this, so a test can only assert that some
directory is created and reused. Only a fixture asserting a literal default path
would separate us.

## T71: What "survive restart" covers

### Spec Text
> Create `STORAGE_DIR` if missing.
> Persisted datasets must survive restart when the same directory is reused.

### Alternatives
1. Every stored dataset is written to the directory as it is ingested, and a new
   process pointed at the same directory serves it from `/datasets/<id>` and
   treats it as a `/convert` cache hit.
2. Persistence covers `/datasets/<id>` lookups only; a `/convert` after a restart
   re-downloads even with caching enabled.
3. Only `/convert` datasets persist, uploads being transient.

### Choice
Alternative 1. A dataset is a dataset whichever route produced it, and the cache
is described as keyed on the source URL with no mention of process lifetime — a
restart that re-downloads everything would make the stored copy pointless.

### Risk: 18
Exposed by a `/convert` repeated after a restart with caching on: no download
here, one download under reading 2. The author most likely also checks the store
before fetching, since that is the existing cache path and it now reads
through to disk.

## T72: A `STORAGE_DIR` that cannot be used

### Spec Text
> Create `STORAGE_DIR` if missing.
> Invalid config or read failure at startup returns an error and exits.

### Alternatives
1. Failing to create the directory — the path exists as a file, or a parent is
   unwritable — is a startup failure, reported like any other bad config.
2. The service starts anyway and only fails when a dataset is stored.

### Choice
Alternative 1. Creation is specified as startup work, and "read failure at
startup returns an error and exits" sets the precedent that an unusable path is
fatal rather than deferred. Missing parent directories are created.

### Risk: 22
Exposed by pointing `STORAGE_DIR` at an existing regular file. The author most
likely calls `makedirs(..., exist_ok=True)` at startup and lets the `OSError`
escape, which fails there too — though as an `OSError` rather than a
configuration error, which only matters to a test asserting the exception type.

## T73: The order of the access and size checks

### Spec Text
> If configured, check every request before routing
> | Size exceeded | 400 | ... |
> | Referer not allowed | 403 | ... |

### Alternatives
1. The allowlist runs first, before routing, so an oversized upload from a
   disallowed origin is 403.
2. The size check runs first, since it is listed first in the error table.

### Choice
Alternative 1. "Before routing" fixes the order explicitly: the allowlist check
happens before the route that would measure the payload even exists. The error
table lists conditions, not a precedence.

### Risk: 8
Exposed only by a request that violates both rules at once. The spec's "before
routing" makes the ordering hard to read the other way.
