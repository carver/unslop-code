# Ambiguities

Numbered record of under-specified points in the spec, the interpretation chosen,
and the risk that the spec author's own implementation reads them differently.

---

## T1 — "XML/HTML" input vs. hard error on malformed input

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. Parse strictly as XML (well-formedness enforced). "XML/HTML" just means "markup
   input" — HTML documents that happen to be well-formed XML (XHTML-ish) parse fine.
2. Try XML, and on failure fall back to a forgiving HTML parser (`lxml.etree.HTMLParser`
   or `recover=True`). Then almost nothing is "malformed" except empty input.

### Choice
Alternative 1: a strict, non-recovering XML parser. It is the only reading that keeps
both other requirements true at once: an HTML/recovering parser lower-cases element
names (destroying "case-sensitive element matching") and would swallow malformed input
that the Errors section requires to exit `1`.

### Risk: 25
Most likely alternative preferred by the author: an HTML fallback for non-well-formed
input, with only empty/unparseable-by-both input erroring.

---

## T2 — Which results count as "XML node results" vs "Text/attribute results"

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. Element (and comment/PI) nodes → XML mode; strings (from `text()`, `@attr`,
   `string()`, `name()`, …), numbers and booleans → text mode.
2. Only decide by whether the XPath returned a nodeset at all, serializing text nodes
   too (e.g. as `<text/>`-ish or raw), which XPath cannot really express.

### Choice
Alternative 1, dispatching on the type of the results: `lxml` returns `_Element` for
element/comment/PI nodes and (smart) `str` for text nodes and attribute values, which
maps exactly onto the spec's two named categories.

### Risk: 5
Most likely alternative preferred by the author: identical; this is the natural `lxml`
type split.

---

## T3 — Mixed result sets (elements *and* strings from one query)

### Spec Text
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. If the first result in document order is an element, use XML mode (print that
   element); otherwise text mode.
2. If *any* result is an element, use XML mode.
3. Emit each result in its own mode, interleaved.

### Choice
Alternative 1. `//a | //b/text()` is exotic; taking the mode from the first result keeps
the two output modes mutually exclusive (as the spec presents them) and makes the
"first node" rule literally about the first matched node.

### Risk: 10
Most likely alternative preferred by the author: unspecified/untested; if tested, "any
element ⇒ XML mode".

---

## T4 — Formatting of numeric XPath results (`count(...)`, `1+1`)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.

### Alternatives
1. Format per XPath 1.0 `string(number)`: integral values without a decimal point →
   `count(//item)` prints `3`.
2. Pass the Python `float` through `str()` → `3.0`.

### Choice
Alternative 1. XPath 1.0 defines the string value of the number 3 as `"3"`, and a
hand-written fixture for `count(//item)` reads `3`. The `.0` is a Python artifact, not
an XPath one.

### Risk: 40
Most likely alternative preferred by the author: `str(float)` giving `3.0`, if their
implementation stringifies results generically before stripping.

---

## T5 — Formatting of boolean XPath results (`//a and //b`, `true()`)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. XPath 1.0 lexical form: `true` / `false`.
2. Python `str(bool)`: `True` / `False`.

### Choice
Alternative 1, for the same reason as T4: XPath 1.0's own string conversion.

### Risk: 45
Most likely alternative preferred by the author: `True`/`False` from a generic
`str()` of the result.

---

## T6 — Results that are empty after stripping

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Keep them: a whitespace-only text node or `id=""` attribute is a match, so it
   contributes an (empty) line.
2. Drop empty results entirely, so a query matching only blank text prints nothing.

### Choice
Alternative 1. The spec's pipeline is strip → collapse → join with no filtering step,
and "write nothing" is scoped to *no-match*, not to matches whose value is empty.

### Risk: 30
Most likely alternative preferred by the author: skipping blank results, since many
implementations guard with `if not value: continue`.

---

## T7 — Exact pretty-print layout for XML node results

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Re-indent the subtree (2-space indent per level, one element per line) and serialize
   without XML declaration and without the node's tail text.
2. Serialize with `pretty_print=True` only, which in `lxml` leaves already-present
   whitespace untouched and therefore often produces no indentation at all.
3. Include an XML declaration and/or the trailing tail text.

### Choice
Alternative 1: `etree.indent(copy, space="  ")` then `tostring(pretty_print=True,
with_tail=False)`. That is the only option that actually pretty-prints input which
arrived on a single line, which is what "pretty-print" asks for. Mixed content (an
element with non-whitespace text) is left alone so no text is invented or lost.

### Risk: 35
Most likely alternative preferred by the author: plain `tostring(pretty_print=True)`
with `lxml`'s default 2-space indent — identical output for compact input parsed with
`remove_blank_text=True`, but differing on input that already contains newlines/indent.

---

## T8 — Namespaced documents

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. Plain XPath 1.0 semantics: an unprefixed name matches only no-namespace elements,
   so `//book` finds nothing in a document with a default namespace (exit `0`, no output).
2. Strip namespaces from the tree, or auto-register the document's prefixes, so
   unprefixed queries match namespaced elements.

### Choice
Alternative 1. The spec asks for XPath 1.0 and says nothing about namespace
convenience; silently rewriting the document would be a surprising deviation. Explicit
prefixes are still usable via `local-name()`.

### Risk: 15
Most likely alternative preferred by the author: identical (default `lxml` behaviour).

---

## T9 — What `[OPTIONS]` are, and the `INFILE` argument

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`
> `INFILE`: accepted positional argument but not used.

### Alternatives
1. No functional options beyond `-h/--help`; `INFILE` is parsed and discarded, never
   opened, never validated — a non-existent path is fine.
2. `INFILE` is read when present, with stdin as fallback.

### Choice
Alternative 1 — the spec says INFILE is "not used" and "Input source: stdin",
unconditionally. The argument exists only so the invocation is accepted.

### Risk: 5
Most likely alternative preferred by the author: identical.

> **Update (CSS/text spec):** partially resolved. `[OPTIONS]` is now populated by
> `--css`, `-t`/`--text` and `--text-all`. The `INFILE` half of this entry stands
> unchanged: it is still accepted and still never read.

---

## T10 — Trailing newline on output

### Spec Text
> then join results with each on a newline

### Alternatives
1. Each result line is terminated by `\n`, so output ends with a newline.
2. Results are joined by `\n` with no trailing newline.

### Choice
Alternative 1 (i.e. `print` semantics) — "each on a newline" reads as line-oriented
output, and it is what a `print()`-based implementation produces. Tests compare
stripped output so both readings agree on content.

### Risk: 15
Most likely alternative preferred by the author: identical; a bare `"\n".join(...)`
passed to `print()` also yields a trailing newline.

> **Update (CSS/text spec):** re-raised but not resolved by "Multi-match text output
> joins lines with `\n`". That wording describes the separator between lines, not
> whether the last line is terminated; the choice above (always terminate) is kept,
> and it is what `print("\n".join(...))` produces.

---

## T11 — Do `--text` / `--text-all` work outside CSS mode?

### Spec Text
> - `--css`: interpret `QUERY` as CSS selector.
> - `-t`, `--text`: direct text extraction from matched elements.
> - `--text-all`: descendant text extraction from matched elements.

> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. `--text`/`--text-all` are general post-processors: they apply to whatever
   elements the query matched, in XPath mode as well as CSS mode.
2. They are only meaningful together with `--css`, and are ignored (or an error)
   for an XPath `QUERY`.

### Choice
Alternative 1. The three flags are listed as peers under "CLI Additions", not
nested under CSS Query Mode, and the Flag Rules explicitly name the XPath form
`text()` as one of the things that makes them a no-op — which only matters if
they are otherwise live in XPath mode. So `xjq.py -t '//title'` is the same as
`xjq.py '//title/text()'`.

### Risk: 15
Most likely alternative preferred by the author: identical; the `text()` mention
in Flag Rules is hard to explain under any other reading.

---

## T12 — What "direct text" is, and whether multiple text nodes are one result or many

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. `::text` is XPath `/text()` on the matched element: each *direct child text
   node* is its own result/line. For `<p>a<b>x</b>c</p>`, `p::text` gives two
   lines, `a` and `c`.
2. Direct text is the concatenation of the element's direct child text nodes into
   one result: a single line `a c` (or `ac`).
3. Direct text means "the element's text content" (i.e. all descendant text),
   making `::text` and ` ::text` differ only in line splitting.

### Choice
Alternative 1. The two forms are the CSS spelling of `/text()` and
`//text()`; this is also exactly what `cssselect`'s parse tree yields
(`selector::text` -> `.../text()`, `selector ::text` ->
`.../descendant-or-self::*/text()`), and it is the established `::text`
convention (Scrapy). The parenthetical "one text node per line" describes the
shared line-per-text-node rule; there is no wording anywhere that asks for
concatenation. `--text` / `--text-all` are implemented as the same two XPath
steps applied to matched elements.

### Risk: 25
Most likely alternative preferred by the author: #2 — concatenating an element's
direct child text nodes into a single line per matched element, if their
implementation reaches for `"".join(el.xpath("text()"))`.

---

## T13 — How "query already extracts text" is detected

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Detect by *result type*: text extraction is applied only to element results,
   so a query that already returned strings (text nodes, attributes, `string()`,
   numbers, booleans) is untouched and the flags are automatically no-ops.
2. Detect by *query text*: if the literal substring `text()` or `::text` occurs
   anywhere in `QUERY`, suppress the flags.

### Choice
Alternative 1. It satisfies the stated rule for every query that really extracts
text, needs no fragile string matching, and does the sensible thing for a query
that merely *mentions* `text()` in a predicate: `-t '//item[text()="a"]'`
matches elements, so `-t` still extracts their text. Reading #2 would print the
XML node there, which contradicts "direct text extraction from matched
elements". Non-element results (attributes, comments, PIs, numbers, booleans)
pass through unchanged.

### Risk: 25
Most likely alternative preferred by the author: #2, a substring check on the
query; it differs only for queries that use `text()` inside a predicate while
returning elements.

---

## T14 — CSS node output when several elements match

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

Round-1 spec, referenced by the term "XML node output":
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. "XML node output" is a pointer to the existing XML-node rule in full,
   including "output only the first node".
2. CSS mode is a new output path that serializes *every* matched element.

### Choice
Alternative 1. The sentence names the existing output category rather than
redefining it, and only re-states the pretty-print half because that is the part
being promised for CSS. Keeping one rule for XML nodes also means
`--css 'item'` and `'//item'` agree.

### Risk: 30
Most likely alternative preferred by the author: #2 — printing all matched
nodes in CSS mode, on the theory that CSS selectors are collection-oriented.

---

## T15 — Text results that are empty after stripping (indentation whitespace)

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).
> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. Keep them. The pipeline is strip -> collapse -> join, with no filtering step,
   so a whitespace-only text node contributes an empty line. `div ::text` on an
   indented document yields blank lines between the real ones.
2. Drop results that are empty after stripping, so only non-blank text lines are
   printed.

### Choice
Alternative 1, for consistency with [[T6]] (the same strip/collapse pipeline in
round 1 was chosen to keep blank results) and because "all descendant text nodes
(one text node per line)" describes emitting every text node, not the non-blank
subset. Applying a filter here but not to an equivalent XPath `//text()` query
would make `--css 'div ::text'` and `'//div//text()'` disagree.

### Risk: 45
Most likely alternative preferred by the author: #2 — filtering out blank
results, which is the usual way `::text` extractors are written and is needed for
a clean fixture over a pretty-printed input document.

---

## T16 — Which cssselect translator (case sensitivity of CSS type selectors)

### Spec Text
> `--css`: interpret `QUERY` as CSS selector.

Round-1 spec:
> Parse stdin as XML/HTML using case-sensitive element matching.

### Alternatives
1. `cssselect.GenericTranslator` (XML semantics): type selectors are
   case-sensitive, so `--css 'Item'` matches `<Item>` and not `<item>`.
2. `cssselect.HTMLTranslator`: element names in the selector are lower-cased,
   plus HTML-specific `:checked`/`:link` handling.

### Choice
Alternative 1. The document is parsed as case-sensitive XML ([[T1]]), so a
lower-casing translator would make `--css` unable to reach any capitalised
element. `GenericTranslator` still handles `#id`, `.class`, attribute, `:nth-*`
and combinator selectors.

### Risk: 20
Most likely alternative preferred by the author: identical for lower-case
fixtures; `HTMLTranslator` only if they test a mixed-case document through
`--css`.

---

## T17 — Comma-separated selectors mixing `::text` with plain selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. There are three modes — direct `::text`, descendant ` ::text`, and no text
   extraction — and every comma-separated part must be in the same one. So
   `a::text, b` is invalid too.
2. Only direct-vs-descendant is checked; `a::text, b` is allowed and produces a
   mixed nodeset of strings and elements, resolved by the round-1 mixed-result
   rule ([[T3]]).

### Choice
Alternative 1. "all selectors use the same `::text` mode" is the general rule and
the following sentence is the concrete instance of breaking it; a query that is
half text and half nodes has no coherent output mode, which is exactly the
problem the rule exists to prevent. Both violations get the same stderr message
and exit code `1`.

### Risk: 35
Most likely alternative preferred by the author: #2 — validating only
direct-vs-descendant, because that is the case the spec spells out, and letting
`a::text, b` through to whatever their generic renderer does.

---

## T18 — Result order across comma-separated selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.

### Alternatives
1. Document order over the union of all selectors (`a::text, b::text` is
   translated to one XPath union `... | ...`, which lxml returns in document
   order with duplicates removed).
2. Selector order: everything matched by the first selector, then the second.

### Choice
Alternative 1 — the standard CSS meaning of a selector list (a set of elements,
not a concatenation), and what `cssselect`'s own `css_to_xpath` produces by
joining the branches with `|`.

### Risk: 20
Most likely alternative preferred by the author: identical, since translating the
whole comma list through `cssselect` in one call is the path of least resistance.
