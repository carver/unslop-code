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
