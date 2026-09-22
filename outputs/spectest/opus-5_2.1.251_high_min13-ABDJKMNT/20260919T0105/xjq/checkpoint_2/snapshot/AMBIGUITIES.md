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
