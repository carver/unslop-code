# Ambiguities

Numbered record of places where the spec admits more than one conforming
behavior, the interpretation chosen for this implementation, and the risk that
the spec author's own implementation reads it differently.

---

## T1 — Which `[OPTIONS]` exist

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. No options at all beyond the automatic `-h/--help`; the `[OPTIONS]` slot is
   purely a usage-line convention.
2. Invent conventional options (e.g. `--pretty`, `--raw`, `-t/--text`) to make
   the slot meaningful.

### Choice
Alternative 1. The spec never names a single option, and every behavior it
describes (text vs. XML output, error handling) is selected automatically from
the query result, not from a flag. Inventing flags would add untested surface
and could shadow a real flag name with different semantics.

### Risk: 10
The author most likely also ships only `-h/--help`; a hidden test that passes an
undocumented flag is improbable.

### Annotation (resolved)
The "CSS Selectors and Text Extraction" spec names the options directly:
`--css`, `-t`/`--text`, and `--text-all`. The `[OPTIONS]` slot is no longer
empty, and the guess that `-t/--text` might mean text extraction turned out to
be right. `-h/--help` remains alongside them.

---

## T2 — "Parse stdin as XML/HTML": strict XML vs. HTML recovery

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

and

> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Strict XML parsing only. Well-formed HTML (XHTML-shaped) parses fine as XML,
   which is what "XML/HTML" covers; anything not well-formed is an error.
2. Try XML first, then fall back to a recovering HTML parser.

### Choice
Alternative 1. The two clauses constrain each other: an HTML fallback recovers
from almost any malformed input (`<a><b></a>`, stray `<`, unclosed tags), which
would make the mandated "malformed XML → exit 1" path nearly unreachable. An
HTML parser also lowercases tag names, directly contradicting "case-sensitive
element matching" in the same sentence. Strict XML is the only reading that
satisfies both requirements simultaneously.

### Risk: 25
The author may have wired an HTML fallback for inputs that fail XML parsing
while still erroring on empty input; such a build would accept `<a><b></a>`
instead of exiting 1.

---

## T3 — Non-node-set XPath results (`count()`, `string()`, `boolean()`)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.
> Text/attribute results: strip each result, collapse internal whitespace runs
> to single spaces, then join results with each on a newline.

### Alternatives
1. Convert numbers/booleans using XPath 1.0 string-conversion rules, so
   `count(//item)` prints `3` and `boolean(//x)` prints `true`/`false`.
2. Use Python's `str()` on the raw lxml return value, printing `3.0` and
   `True`/`False`.

### Choice
Alternative 1. The spec names XPath 1.0 as the evaluation semantics, and XPath
1.0 `string()` of the number 3 is `"3"`, of true is `"true"`. Printing `3.0` for
a count is an artifact of lxml returning a Python float, not a property of the
query language the spec cites.

### Risk: 45
The output section only enumerates "text/attribute" and "XML node" results, so
the author may not have special-cased scalars at all; their implementation most
likely prints `3.0` and `True` via a bare `str()`.

---

## T4 — Trailing newline after output

### Spec Text
> ... then join results with each on a newline.

### Alternatives
1. Emit each result on its own line, i.e. a terminating newline after the last
   result (`print()` semantics).
2. Join strictly with `\n` separators and emit no trailing newline.

### Choice
Alternative 1. "each on a newline" describes line-oriented output, and a
trailing newline is the POSIX convention for text on stdout, which matters for
piping into `wc -l`, `grep`, etc.

### Risk: 15
A test comparing raw stdout byte-for-byte against `"a\nb"` would fail; most
fixtures strip or splitlines, so this rarely bites.

---

## T5 — Results that are empty after stripping

### Spec Text
> strip each result, collapse internal whitespace runs to single spaces, then
> join results with each on a newline.

### Alternatives
1. Keep every result positionally, so a whitespace-only text node becomes an
   empty line.
2. Drop results that strip down to the empty string.

### Choice
Alternative 1. The spec describes a straight map-then-join: strip, collapse,
join. It never mentions filtering, and dropping entries would silently change
the result count relative to the node set that XPath returned.

### Risk: 35
Whitespace-only text nodes are common in indented documents (`//root/text()`),
and an author who eyeballed that output may well have added a filter to avoid
blank lines.

### Annotation (widened)
`::text` and `--text-all` make this far more visible, because descendant text
extraction over an indented document yields a whitespace-only node between
every pair of child elements. The same "no filtering was specified" reading is
kept; T19 records the widened exposure and its own risk.

---

## T6 — Deciding between "text result" and "XML node result"

### Spec Text
> Text/attribute results: ...
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. Classify by the type of the results: element (and comment/PI) nodes take the
   XML path, everything else (lxml smart strings from `text()`/`@attr`, plus
   scalars) takes the text path. For a mixed union, the first item decides.
2. Classify by the query's syntactic shape (e.g. trailing `/text()` or `/@x`).

### Choice
Alternative 1. Result-type dispatch is what the prose describes — it speaks of
"text/attribute results" and "XML node results", i.e. properties of what came
back, not of how the query was spelled. Syntactic classification breaks on
`//node()`, `string(...)`, and unions.

### Risk: 10
Type-based dispatch is the natural lxml implementation; only an exotic mixed
union like `//a|//b/text()` could distinguish the readings.

### Annotation (extended)
The CSS/text spec keeps this dispatch and leans on it: "In CSS mode without
text extraction, return XML node output" versus text output once `::text` or a
text flag is in play. Both still reduce to "did the evaluation yield elements
or strings?". See T15 for how the no-op flag rule falls out of the same
dispatch.

---

## T7 — What "pretty-print" means for an already-indented document

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Serialize with lxml's `pretty_print=True`, which preserves the whitespace
   already present in the source and only adds indentation where a node carries
   none.
2. Re-parse the subtree with blank-text removal first, forcing uniform two-space
   indentation regardless of the source formatting.

### Choice
Alternative 1. "Pretty-print serialized XML" maps directly onto the standard
`tostring(..., pretty_print=True)` call. Re-indenting would also rewrite
significant whitespace in mixed content. The node's tail text is excluded and
the result is stripped so no stray source indentation leaks out.

### Risk: 25
For a nested element selected out of an indented document, option 1 keeps the
source's original (deeper) indentation while option 2 normalizes it; if the
author normalized, the inner lines differ.

---

## T8 — Precedence when both the input and the query are bad

### Spec Text
> Invalid XPath: stderr message, exit code `1`; message should reference
> `xpath`.
> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Read and parse stdin first, so malformed input reports the XML error even if
   the query is also invalid.
2. Compile the query first, so an invalid expression reports the XPath error
   even when stdin is unparseable.

### Choice
Alternative 1. The spec lists the pipeline as parse → evaluate, and the data
must be read before any evaluation can happen. Both orders exit 1, so only the
message text differs.

### Risk: 30
An author who compiles the `XPath` object up front (a common lxml pattern)
would report the xpath error first for this combined input.

---

## T9 — Empty vs. whitespace-only stdin

### Spec Text
> Malformed/empty XML input: stderr message, exit code `1`

### Alternatives
1. Treat input that is empty or contains only whitespace as "empty".
2. Treat only a zero-byte stream as "empty" and let whitespace-only input fall
   through to the parser (which reports it as malformed anyway).

### Choice
Alternative 1. Both end at the same observable place — exit 1 with a message
naming `xml`/`parse` — so the explicit empty check just gives a clearer message
for a whitespace-only stream.

### Risk: 5
Indistinguishable from the outside: the exit code and the required keywords in
the message are identical under both readings.

---

## T10 — The unused `INFILE` argument

### Spec Text
> `INFILE`: accepted positional argument but not used.
> Input source: stdin.

### Alternatives
1. Accept `INFILE` and ignore it entirely — never open it, never check that it
   exists — always reading stdin.
2. Accept it, validate that it exists, but still read stdin.

### Choice
Alternative 1. "Accepted positional argument but not used" is unambiguous about
the file never being touched; validating it would invent a failure mode the
spec does not define.

### Risk: 5
Only a test passing a nonexistent INFILE and expecting a failure would
distinguish these, which would contradict the spec's own wording.

### Annotation (resolved)
The "File Input, First-Result, and Compact Output" spec reverses this: `INFILE`
"takes precedence over stdin when both are present", and a missing or
unreadable file is now an exit-1 error. The argument is read, so both
alternatives above are obsolete; see [T32](#t32) and [T33](#t33) for what the
new wording still leaves open.

---

## T11 — A single result that is the empty string

### Spec Text
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Suppress output whenever the joined text is empty, so `string(//missing)`
   (an XPath string result of `""`) writes nothing at all.
2. Treat "no match" as strictly "zero results" and print a bare newline for a
   single empty-string result.

### Choice
Alternative 1. Emitting a lone newline is indistinguishable to a user from a
match with an empty value, and the spec's "write nothing" clause reads as being
about there being nothing to show. Results that merely *include* blanks
alongside content still keep their blank lines (T5); only an entirely empty
rendering is suppressed.

### Risk: 30
An author whose code is `if results: print("\n".join(lines))` — keyed on the
result list rather than the rendered text — would print a single newline here.

## T12 — Granularity of "direct text": one line per text node or per element

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

and

> `-t`, `--text`: direct text extraction from matched elements.

### Alternatives
1. Both modes yield a node set of text nodes, one per line: direct is
   `element/text()` (the element's own child text nodes) and descendant is
   `element//text()`. For `<p>a<b>c</b>d</p>`, `p::text` gives two lines,
   `a` and `d`.
2. Direct text is one joined string per matched element (`"".join` of its child
   text nodes, or just `element.text`), while only the descendant form is
   per-node. For `<p>a<b>c</b>d</p>`, `p::text` gives the single line `ad`
   (or `a` if only `element.text` is taken).

### Choice
Alternative 1. `::text` is lifted from the parsel/Scrapy convention, where
`a::text` translates to `.../text()` and `a ::text` to
`.../descendant-or-self::text()`; both return node sets. The spec's own
asymmetric wording is better explained as the author clarifying the less
obvious case than as a deliberate change of shape, and a uniform node-set model
keeps `--text`/`--text-all` on the same rendering path as `text()` queries.

### Risk: 35
The parenthetical sits only on the descendant form, so the author may join each
element's direct text into a single line; on `<p>a<b>c</b>d</p>` their
`p::text` would print `ad` rather than `a` and `d`. Note both readings agree on
the common shapes — `<p>hello</p>` and `<div>Hello <b>World</b></div>` — so the
split only shows when text follows a child element.

---

## T13 — Comma lists that mix `::text` with plain selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. Treat "no `::text`" as a third mode: `a::text, b` disagrees just as
   `a::text, b ::text` does, so it is invalid too.
2. Reject only the literal direct-vs-descendant clash named in the prose, and
   let `a::text, b` through — applying the one `::text` mode present to the
   whole union, or returning a mix of text and elements.

### Choice
Alternative 1. The supporting clause is phrased as a requirement that *all*
selectors use the same mode, which a selector with no `::text` at all does not
satisfy. It is also the only reading with a defined output: the alternative has
to silently extend `::text` to a selector that never asked for it, or produce a
result set mixing text and elements that the output rules cannot render.

### Risk: 30
An implementation that tracks two booleans (`saw_direct`, `saw_descendant`) and
errors only when both are set would accept `a::text, b` and apply the direct
mode to both halves.

---

## T14 — How many nodes CSS element output prints

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

### Alternatives
1. Reuse the existing XML node rule unchanged, which prints only the first
   matching node.
2. Read "XML node output" in CSS mode as printing every match, since CSS
   selectors are usually multi-match and the sentence does not repeat the
   first-only restriction.

### Choice
Alternative 1. This spec adds a query syntax, not a new output format: it says
CSS element results take the XML node path, and the XML node path is already
defined as "when multiple XML nodes match, output only the first node". Having
`--css div` print every div while `//div` prints one would make the two query
languages disagree about output for no stated reason.

### Risk: 25
The sentence exists only to say what CSS mode returns, so an author who wrote a
separate CSS branch may well have serialized the whole match list there.

### Annotation (still open)
The "File Input, First-Result, and Compact Output" spec says `--first` "applies
across text, attribute, and XML-node results", which is the closest the specs
have come to revisiting how many nodes print by default. It does not settle it;
see [T30](#t30).

---

## T15 — What makes `--text`/`--text-all` a "no-op"

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Decide from the result type: text extraction rewrites elements into their
   text nodes and leaves everything else alone, so a query that already
   returned strings is untouched — the no-op is automatic.
2. Decide from the query text: scan for the substrings `text()` or `::text` and
   skip extraction when either occurs.

### Choice
Alternative 1. The spec's parenthetical names the two ways a query returns text
rather than defining a string match, and type dispatch is what the rest of the
tool already uses (T6). Substring scanning also gets `//a[text()='x']` wrong:
that query filters on text but *returns elements*, so it has not "already
extracted text" and `--text` should still apply.

### Risk: 15
The two agree everywhere except queries that mention `text()` without returning
it; an author who literally grepped the query string would print the element
`<a>x</a>` for `-t "//a[text()='x']"` where this build prints `x`.

---

## T16 — Whether the text flags work outside CSS mode

### Spec Text
> ## CLI Additions
> - `--css`: interpret `QUERY` as CSS selector.
> - `-t`, `--text`: direct text extraction from matched elements.
> - `--text-all`: descendant text extraction from matched elements.

### Alternatives
1. The flags are independent of `--css` and apply to whatever elements the
   query matched, XPath or CSS.
2. The flags only mean something alongside `--css`, mirroring `::text`.

### Choice
Alternative 1. All three are listed flatly as CLI additions with no dependency
between them, and the flag rules mention `text()` — an XPath construct — when
describing when the flags go quiet, which only makes sense if they can be
combined with an XPath query in the first place.

### Risk: 20
If the author only threaded the flags through the CSS branch, `-t //div` would
print the first `<div>` element instead of its text.

---

## T17 — Wording of the CSS failure messages

### Spec Text
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).
> Invalid CSS selector: stderr message, exit code `1`.

### Alternatives
1. Mirror the existing error style and name the subject, so both messages
   contain `css` (and `selector`), matching how XPath errors contain `xpath`.
2. Emit any message at all, since unlike the base spec's error section this one
   states no keyword requirement.

### Choice
Alternative 1. The base spec asks XPath errors to reference `xpath` and input
errors to reference `xml`/`parse`; a CSS error naming `css` is the consistent
extension, and it satisfies alternative 2 as well.

### Risk: 10
Only a fixture asserting on specific message text could disagree, and this spec
asks for none.

---

## T18 — Text flags against attribute and scalar results

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements.

### Alternatives
1. Extraction applies to elements only; attribute values, `text()` results and
   scalars such as `count(...)` pass through unchanged.
2. Anything other than an element is an error, or is coerced some other way.

### Choice
Alternative 1. The flag is defined as extraction "from matched elements", so a
result that is not an element has nothing to extract. Passing it through is
also what makes the no-op rule of T15 fall out for free, and the spec defines
no error for this combination.

### Risk: 15
`-t //a/@id` printing the attribute value is the only sensible behavior the
spec allows, but an author could have made the flags replace the result set
entirely and print nothing here.

---

## T19 — Whitespace-only text nodes under descendant extraction

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).
> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. Emit every text node the query matched, so the indentation between two child
   elements strips down to an empty line and is still printed (T5's rule,
   unchanged).
2. Drop text nodes that are empty after stripping, so descendant extraction
   over an indented document yields only the visible text.

### Choice
Alternative 1. The spec spells out the per-result transformation as strip and
collapse, with no filtering step, and "all descendant text nodes" is explicit
about the node set being complete. Filtering here would also contradict the
identical rule already applied to `text()` queries.

### Risk: 40
This is the reading most likely to differ in practice: `div ::text` over
pretty-printed HTML produces a blank line between every pair of children, and
an author who looked at that output probably added `if line:` before joining —
their build would print only the non-blank lines.

---

## T20 — Nesting below the top level

### Spec Text
> For top-level objects: keys become direct child elements.
>
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.

### Alternatives
1. The two rules are the general recursive rules, stated at the top level
   because that is where `<root>` makes them concrete: nested objects put their
   keys under their own element, nested arrays put `<item>` children under
   theirs.
2. The rules apply only to the top level, and nested containers use some other
   shape (repeated parent tags for arrays, as many XML-from-JSON converters do,
   so `{"n": [1, 2]}` becomes `<n>1</n><n>2</n>`).

### Choice
Alternative 1. The `type` list includes `dict` and `list`, so a nested container
is an element of its own carrying that type — which only makes sense if its
contents hang below it. Repeated-tag arrays would also destroy the `list` type
and make `[1, 2]` at the top level inconsistent with `[1, 2]` one level down.
Empty containers therefore convert to a childless element, and `{}`/`[]` at the
top level to a childless `<root/>`.

### Risk: 10
An author who wired repeated parent tags for nested arrays would render
`{"n": [1, 2]}` as two `<n>` elements instead of one `<n type="list">`.

---

## T21 — `int` vs. `float` when a float's text is integral

### Spec Text
> numbers as minimal string form […] `1.0 -> "1"`
>
> Every converted element except `<root>` carries `type` in:
> `str`, `int`, `float`, `bool`, `dict`, `list`, `null`.

### Alternatives
1. `type` records how the number was written in JSON — `1.0` is a float and
   keeps `type="float"` even though its text is `1`.
2. `type` records the rendered text — `1.0` renders as `1`, so it is reported
   as `type="int"`.

### Choice
Alternative 1. The two rules are independent: the text rule is about the
*minimal* form of a number, the type rule is about the JSON value's kind. A
JSON decoder distinguishes `1` from `1.0` naturally (Python yields `int` and
`float`), and deriving the type from the already-minimised text would make
`type="float"` unreachable for anything whose fractional part is zero.

### Risk: 25
An author who computed the type from the output string would emit
`type="int"` for `1.0`.

---

## T22 — "Minimal string form" for numbers outside the example range

### Spec Text
> numbers as minimal string form, null as empty.
> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

### Alternatives
1. Shortest round-tripping decimal (Python's `repr`), with an integral float
   written without its fractional part: `1e20 -> "100000000000000000000"`,
   `1e-7 -> "1e-07"`.
2. Always plain decimal notation, never exponential:
   `1e-7 -> "0.0000001"`.
3. Whatever `repr` gives, including `"1.0"` for `1.0`, with the examples read as
   informal.

### Choice
Alternative 1. It reproduces all four examples exactly — in particular
`0.00012`, which `repr` prints in plain notation and a naive `%g`-style format
would print as `0.00012` only by luck — while `1.0 -> "1"` forces the integral
special case. Alternative 3 contradicts the second example outright.

### Risk: 30
On inputs like `1e20` or `1e-7` the author's implementation may keep Python's
exponent form (`1e+20`) rather than expanding integral floats to full digits.

---

## T23 — How detection decides, and what a malformed `{…}` is

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.
>
> Input that fails JSON detection is parsed as XML/HTML.

### Alternatives
1. Detection is a full JSON decode: input that decodes to an object or array is
   JSON, and everything else — including `{"a":` , which *looks* like JSON but
   does not decode — falls through to the XML parser and fails there with the
   XML message.
2. A leading `{` or `[` commits the input to JSON, so malformed JSON is reported
   as a JSON error rather than an XML one.

### Choice
Alternative 1. "Fails JSON detection" reads as one test with one fallback, and a
sniff-then-commit design would need a JSON-specific error class the spec never
mentions, while the spec does spell out the XML/parse error path. A truncated
object therefore exits 1 with the existing `failed to parse xml input` message.

### Risk: 15
An author who sniffed the first character would report a JSON syntax error for
`{"a":` instead of an XML one; both exit 1, so only the message differs.

---

## T24 — Which keys count as "not valid XML element names"

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1`.

### Alternatives
1. The XML 1.0 `Name` production, minus the colon: letters, `_` and most
   non-ASCII letters may start a name; digits, `-`, `.` and combining marks may
   follow. `""`, `"1a"`, `"a b"`, `"-x"` and `"a:b"` are rejected; `"a-b"`,
   `"a.b"`, `"_a"`, `"xml"` and `"Ünicode"` are accepted.
2. Additionally reject names reserved by the XML spec — anything starting with
   `xml` in any case, and `xmlns`.
3. ASCII-only names, rejecting `"Ünicode"`.

### Choice
Alternative 1. It is exactly what an XML serialiser will accept: lxml raises
`ValueError` for precisely this set, so any key it admits produces a document
that actually exists, and any key it refuses is one the tool could not emit.
Colons are excluded because lxml reads them as namespace prefixes rather than
as part of the local name. The reserved `xml…` names are well-formed and every
mainstream serialiser writes them, so rejecting them would exceed the rule.

### Risk: 20
The author most likely also delegates to their serialiser; the likeliest
divergence is a stricter ASCII-only check that rejects non-ASCII keys.

---

## T25 — Precedence of the invalid-key error against other failures

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1`.

### Alternatives
1. Conversion is part of reading the input, so an invalid key is reported
   before the query is even compiled: a bad key plus a bad XPath reports the
   key.
2. The query is validated first, so a bad XPath wins.

### Choice
Alternative 1. The spec calls such keys "invalid input", which places them in
the same stage as malformed XML — and T8 already settled that input errors are
reported before query errors. Both paths exit 1, so only the message differs.

### Risk: 15
An author who compiles the expression before reading stdin would report the
XPath error for that combination.

---

## T26 — Non-standard JSON extensions and duplicate keys

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.

### Alternatives
1. Accept whatever the language's default JSON decoder accepts — which in
   Python includes the `NaN`, `Infinity` and `-Infinity` literals — and keep
   the decoder's last-wins rule for duplicate object keys.
2. Enforce strict RFC 8259: reject those literals so the input falls back to
   XML, and/or treat duplicate keys as an error or emit both.

### Choice
Alternative 1. The spec never mentions either case, and both implementations
will most plausibly be a plain `json.loads`/`JSON.parse` call, which resolves
them this way for free. `{"a": NaN}` therefore converts to `type="float"` with
the text `nan`, and `{"a": 1, "a": 2}` yields a single `<a>` holding `2`.

### Risk: 20
An author using a strict decoder would reject `NaN` and fall back to XML,
turning it into an exit-1 XML parse error.

---

## T27 — Whether `<item>` elements carry `type`

### Spec Text
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.
>
> Every converted element except `<root>` carries `type` in: […]

### Alternatives
1. "Every converted element except `<root>`" is literal, so `<item>` carries
   the type of the entry it holds.
2. `type` is tied to object keys, and `<item>` — whose name comes from the
   converter rather than the document — is left bare.

### Choice
Alternative 1. The exception list names `<root>` and nothing else, which only
reads as deliberate if the other converter-named element is included. It is
also the only way `[1, "a"]` stays self-describing.

### Risk: 5
A build that omitted `type` on `<item>` would contradict its own exception
clause.

---

## T28 — Where `--first` cuts when `--text`/`--text-all` is also given

### Spec Text
> `-f`, `--first`: return only first result.
>
> `--first` applies across text, attribute, and XML-node results.

### Alternatives
1. "Result" means one entry of the list that is about to be printed, so the cut
   happens last: `--text-all --first` on a document whose first match holds
   three text nodes prints one line.
2. "Result" means one query match, so the cut happens before extraction: the
   first matched element is kept and every text node it contains is printed,
   giving three lines for the same input.

### Choice
Alternative 1. The spec frames `--first` as an output rule, listed beside the
no-match rule under "## Output Rules", and describes it in terms of result
kinds — "text, attribute, and XML-node results" — which are categories of
printed output rather than categories of match. Slicing the final list is also
the only reading under which `--first` reliably means "one line of output",
which is what a flag named `--first` is reached for.

### Risk: 35
An author who slices the node list where the query runs, before the text flags
expand it, would print every text node of the first element instead.

---

## T29 — `INFILE` bytes that are not valid UTF-8

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.
>
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. A file that fails to decode is unreadable: report it with the file-input
   message and exit 1.
2. Decoding failures belong to the document, not the file, so they surface as
   the malformed-input error whose message references `xml`/`parse`.

### Choice
Alternative 1. The spec makes decoding part of reading the file — it is stated
as a property of `INFILE`, one bullet above the failure rule — so a byte
sequence that is not UTF-8 never becomes a document at all. Both readings exit
1, so only the message differs.

### Risk: 25
An author who decodes with a replacement-character policy, or who hands the raw
bytes to the XML parser after a failed decode, would report a parse error (or
for latin-1 XML, silently succeed with mojibake).

---

## T30 — Whether `--first` changes XML-node output

### Spec Text
> `--first` applies across text, attribute, and XML-node results.

and, from the base spec:

> when multiple XML nodes match, output only the first node

### Alternatives
1. XML-node output stays first-only always; `--first` is honoured uniformly but
   has nothing left to do for nodes. The bullet says the flag is not
   text-only.
2. This spec quietly lifts the base rule: without `--first` every matching node
   is serialized, and `--first` is what restores the single-node output.

### Choice
Alternative 1. The base rule is stated unconditionally and this spec does not
retract it; a spec that meant to reverse an earlier mandated behavior would say
so rather than imply it from a list of result kinds. Reading it as a reversal
also silently breaks every previously conforming single-node output.

### Risk: 25
Listing XML nodes among what `--first` "applies across" only earns its place if
the flag does something there, so an author may have switched the default to
serializing every match.

---

## T31 — What "no added pretty-print formatting" does to whitespace already in the source

### Spec Text
> `--compact` affects XML serialization only: compact XML output has no added
> pretty-print formatting.

### Alternatives
1. Suppress only the formatting the serializer would add: indentation and line
   breaks that were not in the document. Whitespace text nodes that the input
   actually contains are part of the element's content and survive.
2. Compact means single-line output: strip whitespace-only text nodes so that
   an indented source document also serializes onto one line.

### Choice
Alternative 1. "No *added* formatting" names the serializer's own output as the
thing being turned off, not the document's content. Deleting whitespace text
nodes would also change what the same document reports for `text()`, which the
sentence rules out by confining `--compact` to serialization.

### Risk: 15
An author who implemented compaction by stripping whitespace rather than by
disabling the pretty-printer would collapse an indented source element onto one
line.

---

## T32 — `-` as an `INFILE` name

### Spec Text
> `INFILE` takes precedence over stdin when both are present.

### Alternatives
1. `-` is an ordinary path. There is no such file, so it is the missing-file
   error.
2. `-` is the conventional Unix spelling of "read stdin", so it selects the
   stdin path instead of a file.

### Choice
Alternative 1. The spec gives exactly one way to reach stdin — omitting
`INFILE` — and never mentions a magic name. Inventing one would turn a genuine
missing-file case into silent success.

### Risk: 10
An author using a library that opens `-` as stdin by convention would read
stdin instead of failing.

---

## T33 — What the missing-file message says

### Spec Text
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. Any message, as long as it goes to stderr — name the path and the reason the
   operating system gave.
2. A message shaped to match the earlier error families, which the base spec
   required to contain `xml`/`parse`.

### Choice
Alternative 1. Unlike the malformed-input and bad-expression rules, this one
states no keyword requirement, so the message is free; naming the path and the
underlying reason is what makes it useful. The wording still contains the
words `read` and `file`, the terms this bullet itself uses.

### Risk: 10
Only a test asserting on specific words would separate these, and the spec
supplies none to assert on.

---

## T34 — A UTF-8 BOM on stdin

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.

### Alternatives
1. The BOM tolerance is a property of UTF-8 decoding generally, so a BOM is
   also accepted ahead of stdin's JSON or XML.
2. The allowance is scoped strictly to `INFILE`; a BOM on stdin is part of the
   document and may make it unparseable.

### Choice
Alternative 1. The sentence explains how UTF-8 text is decoded rather than
granting `INFILE` a privilege, and both streams feed the same detector and
parsers. Accepting it on one source and rejecting it on the other would make
`cat doc.xml | xjq …` and `xjq … doc.xml` disagree about the same bytes.

### Risk: 10
Both readings coincide in practice for most toolchains, since JSON decoders
that sniff an encoding and XML parsers both skip a leading BOM on their own.

---

## T35 — An `INFILE` that exists but is empty

### Spec Text
> Missing/unreadable file: stderr message, exit code `1`.

and, from the base spec:

> Malformed/empty XML input: stderr message, exit code `1`.

### Alternatives
1. The file is readable; it simply holds an empty document, so the existing
   malformed/empty-input error reports it.
2. An empty file counts as unreadable and takes the file-input error.

### Choice
Alternative 1. Reading succeeds — the bullet is about files that cannot be
opened or decoded — and the base spec already names empty input as its own
failure with a message referencing `xml`/`parse`. Keeping that mapping means
an empty file and an empty stdin report the same thing.

### Risk: 10
Both exit 1; only an assertion on the message would tell them apart, and the
base spec's keyword requirement points at this reading.

---

## T36 — What "zero-indent JSON layout" means

### Spec Text
> With `--compact`, produce zero-indent JSON layout (no leading whitespace).

### Alternatives
1. `json.dumps(..., indent=0)`: the same line structure as the default export
   with every line flush against the left margin.
2. Single-line JSON, as `json.dumps(...)` produces by default, optionally with
   the separator spaces squeezed out too.

### Choice
Alternative 1. "Zero-indent" names an indent width rather than the absence of
line breaks, and "no leading whitespace" describes lines — a one-line document
has no leading whitespace to speak of. It also mirrors what `--compact` already
does to XML: it drops the indentation the pretty-printer adds and nothing else.

### Risk: 25
If the author's exporter calls `json.dumps` with no `indent` at all, the whole
array lands on one line and every character of the expected output differs.

---

## T37 — Which text nodes "immediate text content" covers

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> Use immediate text only (exclude descendant text from child elements).

### Alternatives
1. Every text node that is a direct child of the element, concatenated — the
   same node set `--text` and `sel::text` already call direct text, which
   includes the text following a child element (`<d>a<b>x</b>c</d>` → `ac`).
2. Only the element's leading text (lxml's `.text`, Python's `.text` on a DOM
   node): `<d>a<b>x</b>c</d>` → `a`.

### Choice
Alternative 1. The tool already has a meaning for the element's own text —
`--text` — and the parenthetical only excludes text owned by *child* elements,
which is exactly the difference between direct and descendant text. Text after
a child is the element's own, not the child's.

### Risk: 30
A `.text`-only exporter is a one-liner and a natural thing to write; a fixture
with mixed content (text, child, more text) would separate the two readings.

---

## T38 — Whether exported text is normalized

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

and, from the base spec:

> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. The export carries the same normalized text the text output does: stripped,
   with internal whitespace runs collapsed.
2. The export carries the raw text verbatim, so an indented document exports
   `"\n  "` for an element whose only direct text is layout whitespace.

### Choice
Alternative 1. Normalization is the tool's standing rule for text results, and
the export is a text result in a different container. Raw text would also make
the common case — a pretty-printed document — export newline-and-space noise
for every container element.

### Risk: 30
An exporter built on `.text` without a normalize step is just as plausible; any
fixture with an indented document or padded element text would tell them apart.

---

## T39 — JSON export when nothing matches

### Spec Text
> `-j`, `--json`: JSON export mode for XML element results.

and, from the base spec:

> No matches: no output, exit code `0`.

### Alternatives
1. Stay silent, as every other no-match run does.
2. Print `[]`, since the contract promises a JSON array and an empty export is
   still a well-formed one.

### Choice
Alternative 1. The base spec's no-match rule is unconditional and this spec
does not carve out an exception; a consumer piping the output can tell empty
from absent by the exit code, which stays `0` either way.

### Risk: 30
An exporter that always serializes its list prints `[]` without anyone having
to decide, so the author's implementation may well emit it.

---

## T40 — Non-ASCII characters in the export

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. Escape non-ASCII as `\uXXXX`, the default of Python's `json` module.
2. Emit the characters as UTF-8, `ensure_ascii=False`.

### Choice
Alternative 1. Nothing in the spec asks for the non-default setting, and both
forms parse back to the same string, so the library default is the reading
least likely to surprise.

### Risk: 25
A tool that prints to a terminal reads better with `ensure_ascii=False`, and an
author who noticed the escapes would have turned them off.

---

## T41 — How union `--text-all` matches are joined

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Join the matches' descendant text with a single space, then normalize, so
   `//a|//b` over `<r><a>Hello</a><b>World</b></r>` gives `Hello World`.
2. Concatenate with nothing between the matches, giving `HelloWorld` for the
   same document.

### Choice
Alternative 1. Within one match the text nodes are concatenated directly, which
is what keeps mixed content readable (`Hello <b>World</b>!` → `Hello World!`),
but running separate matches together welds unrelated words into one token —
and "normalized output string" describes something meant to be read. A
space-separated join is also what the whitespace between elements in an
indented document would have produced anyway.

### Risk: 40
"Concatenate" is literally the empty-string join, and an implementation built
on XPath's `string()` semantics would produce `HelloWorld` for a document
without whitespace between the matched elements.

---

## T42 — Union `--text-all` over results that are not elements

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Concatenate whatever the union matched, so an attribute union such as
   `//a/@id|//b/@id` also collapses onto one line.
2. Restrict the rule to element matches and leave attribute results on their
   own lines, as the base spec's no-op rule for already-text results does.

### Choice
Alternative 1. The rule is stated in terms of union queries with `--text-all`
active, not in terms of what the matches are, and the string value of an
attribute is its value, so the concatenation is well defined for it.

### Risk: 20
An attribute union under `--text-all` is an unlikely fixture, and the two
readings agree on every element query.

---

## T43 — Recognising a sub-path that "already performs text extraction"

### Spec Text
> If any union sub-path already performs text extraction, text flags are
> treated as no-op query modifiers.

### Alternatives
1. Decide syntactically: split the query on its top-level `|` and look for a
   sub-path whose last step is `text()`, matching how the base spec describes
   the no-op rule (`text()` or `::text` in the query).
2. Decide from the results: if any matched value is already a string rather
   than an element, treat the flags as no-ops.

### Choice
Alternative 1. The spec talks about the sub-*path*, a property of the query,
and the base spec's companion rule is likewise about what the query says. It
also keeps an attribute sub-path (`//a/@id|//b`) out of the rule, which the
sentence limits to text extraction.

### Risk: 30
A results-driven implementation is the easier one to bolt on, and it differs
for `//a/@id|//b`, where it would leave `//b` unextracted.

---

## T44 — Rendering a union whose matches are part text, part elements

### Spec Text
> If any union sub-path already performs text extraction, text flags are
> treated as no-op query modifiers.

### Alternatives
1. Keep the base spec's auto-format rule as it stands: the first result decides
   the form, and an element that lands in line-oriented output contributes its
   normalized string value.
2. Serialize elements as XML inside the line output, or drop the values that do
   not match the chosen form.

### Choice
Alternative 1. The no-op rule sends the query back to the default auto-format
behavior, and that behavior already picks one form for the whole result set.
Printing a mix of serialized XML and text lines would fit no consumer, and
dropping matches silently loses data the query asked for.

### Risk: 30
`//a/text()|//b` is a corner the author may not have pinned down at all, and any
of the three renderings is defensible for it.

---

## T45 — How many elements the export contains

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

and, from the base spec:

> XML node output prints the first node only.

### Alternatives
1. Export every matched element; the base spec's first-node-only rule is about
   serializing XML, and `--first` would have nothing to narrow otherwise.
2. Export only the first match, keeping the element-output rule intact.

### Choice
Alternative 1. The contract names an array of objects, and the `--first` note —
"still return a JSON array containing one exported element" — only makes sense
if the array normally holds more.

### Risk: 15
The `--first` note reads as a narrowing of something wider, so a one-element
export in every case is hard to square with the spec.

---

## T46 — `--json` against a scalar result

### Spec Text
> `--json` has no effect when results are already auto-detected as text
> (e.g., text()/attribute outputs).

### Alternatives
1. Treat every non-element result the same way: a number from `count(...)` or a
   boolean from `boolean(...)` prints as it always did.
2. Wrap the scalar in the exported array somehow.

### Choice
Alternative 1. The flag is introduced as "JSON export mode for XML element
results"; a scalar has neither a tag name nor text content to export, and the
note's "already auto-detected as text" covers everything the line-oriented
output handles.

### Risk: 15
There is no sensible `{tag_name: text}` object for a number, so an author would
have to invent one.

---

## T47 — CSS `|` that the parser accepts but XPath cannot evaluate

### Spec Text
> In CSS mode, pass `|` through as CSS query text (no XPath union semantics).
> If the CSS engine rejects the selector, report a CSS selector error on stderr
> with exit code `1`.

### Alternatives
1. Report a CSS selector error for any failure of a CSS query, including
   `a|b`, which CSS reads as the namespace `a` — accepted by the selector
   parser, then rejected by the XPath engine as an undefined prefix.
2. Report a CSS error only when the selector parser itself refuses (`a | b`,
   `div|`), and let the namespace case surface as an XPath error.

### Choice
Alternative 1. In CSS mode the user never wrote XPath, so a message about an
XPath expression names something they cannot see or fix. The spec's sentence
also treats "rejects the selector" as the outcome for `|` in CSS mode generally,
and `a|b` is the spelling a union-minded user would actually type.

### Risk: 25
Both readings exit `1`; they differ only in whether stderr says `css` or
`xpath`, and an implementation that simply lets the evaluator's error through
would say `xpath`.

---

## T48 — Whether CSS comma selectors count as unions

### Spec Text
> Support XPath `|` union in XPath mode.
> ...
> In CSS mode, pass `|` through as CSS query text (no XPath union semantics).

### Alternatives
1. The union rules — including the `--text-all` concatenation — apply only to a
   `|` the user wrote in an XPath query. A CSS comma list keeps the existing
   one-line-per-text-node output even though it compiles to an XPath union
   internally.
2. Any query that becomes a union internally takes the union text rules.

### Choice
Alternative 1. The spec scopes union support to XPath mode and explicitly
denies `|` any union meaning in CSS mode; the internal translation is an
implementation detail the base spec's CSS rules already cover.

### Risk: 20
The concatenation rule would be easy to key off the compiled expression
instead, which would change `--css --text-all "a, b"` from two lines to one.

---

## T49 — Which node is "the first matched union node"

### Spec Text
> If `--first` is also active with union + `--text-all`, only the first matched
> union node contributes to the output.

### Alternatives
1. The first match in document order, which is the order an XPath union
   produces and the order `--first` already uses elsewhere.
2. The first match of the first sub-path as written, so `//c|//b` starts from a
   `<c>` even when a `<b>` comes earlier in the document.

### Choice
Alternative 1. XPath node-sets are unordered as a data type but every engine,
lxml included, hands them back in document order, and the base spec's `--first`
already means "first result". Sub-path order would require deliberately
regrouping the matches.

### Risk: 15
Getting reading 2 takes extra work, so an implementation is unlikely to land on
it by accident.

---

## T50 — `--first` with a union and `--text` (not `--text-all`)

### Spec Text
> If `--first` is also active with union + `--text-all`, only the first matched
> union node contributes to the output.

### Alternatives
1. The note is specific to `--text-all`; `--text` keeps the base spec's rule
   that `--first` cuts after extraction, so one text node survives.
2. `--first` cuts to the first matched node before extraction for any union, so
   `--text` prints all the direct text nodes of the first match.

### Choice
Alternative 1. The spec attaches the node-level cut to the concatenation rule,
which only `--text-all` triggers, and the base spec already fixed where
`--first` cuts for `--text` (see T28). Two matches' worth of nodes would
otherwise appear under a flag that promises one result.

### Risk: 25
An element whose direct text is a single node behaves identically under both,
so this only shows up in a fixture with mixed content in the first match.

---

## T51 — Whether a no-op text flag still outranks `--json`

### Spec Text
> When multiple output flags are present:
> 1. `--text-all` 2. `--text` 3. `--json` 4. default auto-format behavior

### Alternatives
1. Precedence goes by the flags present: `--text` on the command line keeps
   `--json` from taking effect even when the text flag is itself a no-op for
   the query.
2. Precedence goes by effect: a text flag that has been demoted to a no-op
   query modifier lets `--json` take over.

### Choice
Alternative 1. The list is introduced with "when multiple output flags are
present", which is a statement about the command line, not about what the
query happens to return.

### Risk: 15
The two differ only for a union that mixes a text sub-path with an element
sub-path under both `--text` and `--json`, which is a doubly unlikely fixture.
