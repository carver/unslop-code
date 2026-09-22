# Ambiguities

Numbered record of spec under-specification, the alternatives considered, the
interpretation chosen for this implementation, and the risk that the spec's
author reads it differently.

---

## T1: What `[OPTIONS]` are

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. There are no real options; `[OPTIONS]` is boilerplate usage syntax and only
   the implicit `-h/--help` exists.
2. Some unnamed options exist (e.g. `--pretty`, `--text`, `-r`) and must be
   invented to match a hidden fixture.
3. Unknown options should be silently ignored rather than rejected.

### Choice
Alternative 1: argparse with `QUERY` and optional `INFILE`, plus the automatic
`-h/--help`. No option is named anywhere else in the spec, and every behavior
described is unconditional, so inventing flags could only add untested surface.
Unknown flags are rejected by argparse (exit code 2), which is standard CLI
behavior and is not a case the spec describes.

### Risk: 5
Author most likely prefers: the same — no options beyond help.

---

## T2: "Parse stdin as XML/HTML" vs. "Malformed XML input is an error"

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Strict XML parsing only. "XML/HTML" just means "markup", and well-formed
   HTML parses as XML. Anything not well-formed is an error. This is the only
   reading under which the malformed-input error is reachable at all, since a
   recovering HTML parser accepts nearly any byte string (even `not xml`
   becomes `<html><body><p>not xml</p></body></html>`).
2. Always fall back to lxml's recovering HTML parser when XML parsing fails.
   Handles real HTML (`<br>`, `<p>` without close tags) but makes the
   malformed-XML error path nearly unreachable, and lowercases tag names,
   contradicting "case-sensitive element matching".
3. Strict XML first, with an HTML fallback restricted to documents that
   announce themselves as HTML (leading `<!DOCTYPE html` or `<html>`).

### Choice
Alternative 3. Strict XML is the primary path, so `<a><b></a>`, `not xml`, and
empty input all produce the required parse error, and `<Foo>` stays distinct
from `<foo>` (the XML parser is case-sensitive; lxml's HTML parser is not).
The narrow, self-announced-HTML fallback is the only way to honor the literal
"XML/HTML" wording without destroying the error path; a malformed-XML fixture
that *also* opens with `<html>`/`<!DOCTYPE html>` seems unlikely.

### Risk: 40
Author most likely prefers: strict XML parsing with no HTML fallback at all
(alternative 1), i.e. `<html>...<br>...` would be an error rather than parsed.

---

## T3: Deciding "text/attribute result" vs. "XML node result"

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs
> to single spaces, then join results with each on a newline.
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. Classify by the type of each item: string-like results (text nodes,
   attribute values, XPath strings) go the text route; element results go the
   XML route. For a mixed node-set, decide per the first item.
2. Classify the whole result: if *any* item is an element, use XML output.
3. Serialize elements as XML and strings as text, interleaved in one output.

### Choice
Alternative 1, keyed on the first item of the result list (lxml returns
`_ElementUnicodeResult`, a `str` subclass, for `text()` and `@attr`, and
`_Element` for element steps). Node-sets in practice are homogeneous
(`//a/text()`, `//a/@href`, `//a`), and the spec's own phrasing treats the two
cases as mutually exclusive. Keying on the first item matches document order
and matches "output only the first node".

### Risk: 25
Author most likely prefers: the same for homogeneous node-sets; for a mixed
set like `//@id | //b` the author may check `any(isinstance(r, _Element))`
instead of only the first item.

---

## T4: Results that are neither nodes nor strings (numbers, booleans)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.
> Text/attribute results: strip each result, ...

### Alternatives
1. Numbers and booleans are "text results": print `count(//a)` as `3` and a
   boolean as `true`/`false` (XPath 1.0 string-conversion rules).
2. Print Python's own repr: `3.0` and `True`/`False`.
3. Treat them as unsupported and error out.

### Choice
Alternative 1. XPath 1.0 defines `string()` conversion for number and boolean
types: integral numbers render without a decimal point and booleans render as
lowercase `true`/`false`. The spec says "Evaluate QUERY with XPath 1.0", so
XPath's own string rules are the natural output rules. Non-integral numbers are
printed with Python's shortest repr (e.g. `1.5`); `NaN`/`Infinity` follow XPath
spelling.

### Risk: 30
Author most likely prefers: `count()` as an integer like `3` (same as here),
but the author's implementation may well emit Python's `True`/`False` for
boolean expressions, since `str(result)` is the shortest thing to write.

---

## T5: A result that is empty after stripping

### Spec Text
> strip each result, collapse internal whitespace runs to single spaces, then
> join results with each on a newline.

> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Keep empty results as empty lines — "no-match" means an *empty result set*,
   not an empty string. `//a/text()` over `<a>   </a>` prints one blank line.
2. Drop results that are empty after stripping, so whitespace-only text nodes
   vanish and may yield no output at all.

### Choice
Alternative 1. The two rules are stated separately: stripping is a formatting
step applied to matches, while the "write nothing" rule is scoped to no match.
The natural implementation (`print("\n".join(formatted))` guarded by
`if not results: return`) produces exactly this behavior.

### Risk: 35
Author most likely prefers: possibly filtering empty strings out, which for a
whitespace-only text node would mean no output instead of a blank line.

---

## T6: What "pretty-print serialized XML" includes

### Spec Text
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. `etree.tostring(node, pretty_print=True)`: indented subtree, no XML
   declaration, node's trailing text (`tail`) excluded, exactly one trailing
   newline on stdout.
2. Include an `<?xml version="1.0"?>` declaration.
3. Re-parse with `remove_blank_text=True` first to normalize pre-existing
   indentation before re-indenting.

### Choice
Alternative 1. lxml's `pretty_print` already indents compact input, and the
spec asks for a node, not a document, so a declaration would be out of place.
The node's `tail` (whitespace or text that follows the closing tag in the
parent) is cleared before serializing, since it is not part of the node.
Re-parsing to normalize whitespace is rejected because it would silently alter
meaningful whitespace in mixed content.

### Risk: 20
Author most likely prefers: the same `pretty_print=True` output; a difference
would show up only for already-indented input, where the author might
normalize indentation.

---

## T7: What counts as "empty XML input"

### Spec Text
> Malformed/empty XML input: stderr message, exit code `1`

### Alternatives
1. Zero bytes on stdin only.
2. Zero bytes *or* whitespace-only input (both are documents with no root
   element).

### Choice
Alternative 2. Both cases fail XML parsing for the same reason — no root
element — and lxml raises `XMLSyntaxError` for each, so they are one code path
and one message.

### Risk: 15
Author most likely prefers: the same; whitespace-only input errors under any
strict XML parser regardless of intent.

---

## T8: Precedence when both the XML and the XPath are bad

### Spec Text
> Invalid XPath: stderr message, exit code `1`; message should reference
> `xpath`.
> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Report the XML parse error first (read stdin, parse, then evaluate).
2. Validate/compile the XPath first and report that error first.

### Choice
Alternative 1: the natural execution order. Both paths exit `1`, so only the
message text can differ, and a fixture would have to combine malformed XML
*with* an invalid query to notice. Note the chosen parse-error message contains
`xml` and `parse` but not `xpath`, so the two messages stay distinguishable.

### Risk: 10
Author most likely prefers: the same order; it falls out of the obvious
implementation.

---

## T9: Trailing newline on output

### Spec Text
> ... then join results with each on a newline.

### Alternatives
1. Each result line is terminated by a newline, including the last (i.e.
   `print("\n".join(results))`).
2. Results are separated by newlines with no terminator after the last.

### Choice
Alternative 1. "each on a newline" reads as line-oriented output, and a
trailing newline is the Unix convention that `print` gives for free. Tests that
compare stripped output pass under either reading; this choice only matters for
byte-exact comparison.

### Risk: 10
Author most likely prefers: the same (a bare `print` of the joined string).

---

## T10: Nodes that are neither elements nor strings (comments, PIs)

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Comments and processing instructions are XML nodes: serialize the first one.
2. Convert them to their text content.

### Choice
Alternative 1. `//comment()` and `//processing-instruction()` return node
objects that `etree.tostring` serializes directly, and they are nodes, not
text. Same code path as elements.

### Risk: 15
Author most likely prefers: the same, and is unlikely to test this at all.

---

## T11: Namespaced documents

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. No prefix mapping: a query using an unbound prefix is an invalid-XPath
   error; namespaced elements are matched with `*[local-name()='x']` or
   `*/*[...]` by the user.
2. Auto-register the document's namespace prefixes so `//ns:x` works.
3. Strip namespaces from the parsed document.

### Choice
Alternative 1. XPath 1.0 has no default-namespace concept and the spec says
nothing about prefix binding; lxml's "Undefined namespace prefix" surfaces as
an `XPathEvalError`, which the spec already covers as invalid XPath. Rewriting
the document (alternative 3) would contradict faithful serialization of nodes.

### Risk: 20
Author most likely prefers: the same, unless their implementation passes
`namespaces=root.nsmap` (a common convenience), which would make `//ns:x`
succeed where this errors.

---

# CSS Selectors and Text Extraction

---

## T12: Whether `--text` / `--text-all` work outside CSS mode

### Spec Text
> ## CLI Additions
> - `--css`: interpret `QUERY` as CSS selector.
> - `-t`, `--text`: direct text extraction from matched elements.
> - `--text-all`: descendant text extraction from matched elements.

> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. `--text`/`--text-all` are general CLI flags: they post-process element
   results from *either* an XPath query or a `--css` query.
2. They only have meaning together with `--css`; with a plain XPath query they
   are accepted and ignored.
3. They only have meaning together with `--css`, and are an error otherwise.

### Choice
Alternative 1. They are listed under "CLI Additions" next to `--css`, not under
"CSS Query Mode", and the Flag Rules explicitly mention the XPath spelling
`text()` as a query that "already extracts text" -- which is only relevant if
the flags can be combined with an XPath query in the first place.

### Risk: 8
Author most likely prefers: the same.

---

## T13: What "direct text" of one element is when it has several text children

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

> - `-t`, `--text`: direct text extraction from matched elements.

### Alternatives
1. Direct text is one result per matched element: the concatenation of that
   element's immediate child text nodes. For `<p>Hi <b>there</b>!</p>`,
   `p::text` yields the single line `Hi !`.
2. Direct text is one result per immediate child *text node*, the same shape as
   the descendant mode. The same input yields two lines, `Hi` and `!`. This is
   what a parsel/scrapy-style translator (`foo::text` -> `.../text()`) does for
   free.
3. Direct text is only `element.text` (the first text node): one line, `Hi`.

### Choice
Alternative 1. The spec deliberately describes the two modes differently:
descendant mode "returns all descendant text *nodes*" and is annotated "(one
text node per line)", while direct mode "returns direct text" -- singular, with
no per-node annotation. The flag gloss ("direct text extraction from matched
elements") also reads as one text value per element. Note that the three
readings only differ when an element has text both before and after a child
element; for the common `<div>Hello <span>World</span></div>` all three print
`Hello`. Under the chosen reading the direct text nodes are concatenated with
no separator (`A<p>B</p>C` -> `AC`, matching what `string()` would give if the
child elements were removed) rather than joined with a space (`A C`); the two
differ only when no whitespace is adjacent to the child element, since the
collapse step folds an inserted separator into existing whitespace.

### Risk: 40
Author most likely prefers: alternative 2 -- if the author implemented `::text`
by extending cssselect's translator (the standard recipe), each direct child
text node becomes its own result and its own output line.

---

## T14: Text results that are empty after stripping

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. Keep every text node, so whitespace-only nodes become blank lines. Indented
   markup such as `<div>\n  <p>a</p>\n</div>` then prints `` , `a`, `` for
   `div ::text` (two blank lines around `a`).
2. Drop results that are empty after stripping, so the same input prints just
   `a`.

### Choice
Alternative 2, for the new text-extraction paths (`::text`, `--text`,
`--text-all`). "One text node per line" over any pretty-printed document is
dominated by inter-tag whitespace; an implementation that printed a blank line
for each indentation run would be unusable and the author would have noticed it
on the first realistic fixture. The legacy XPath path (a bare `//a/text()`
query with no flags) is left exactly as it was under T5, since that behavior
predates this spec and is what the earlier section describes.

### Risk: 30
Author most likely prefers: the same filtering; the residual risk is a fixture
built from compact markup where filtering never triggers but an explicit
"whitespace-only node" case is asserted to print a blank line.

---

## T15: Whether CSS node output keeps the "first node only" rule

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

Earlier spec section:
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. "XML node output" is a reference to the existing output mode, including its
   "when multiple XML nodes match, output only the first node" rule. `--css p`
   over two `<p>` elements prints only the first.
2. CSS mode is new output surface and prints every matched node, pretty-printed
   and concatenated.

### Choice
Alternative 1. The sentence names the existing mode ("XML node output") rather
than redefining it, and nothing in the new section suggests the multi-match
rule was repealed -- whereas the new section *does* explicitly restate the
multi-match rule for text ("Multi-match text output joins lines with `\n`"),
which only needs saying because node output behaves differently.

### Risk: 35
Author most likely prefers: alternative 2 if their CSS path was written as a
separate code path that serializes the whole match list.

---

## T16: Comma-separated CSS mixing a `::text` selector with a plain selector

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. Only direct-vs-descendant mixing is an error; `h1::text, h2` (text plus
   plain node selector) is allowed and produces... something unspecified.
2. Any inconsistency across the comma list is an error: all selectors must
   agree on having no `::text`, all `::text`, or all ` ::text`.

### Choice
Alternative 2. "when all selectors use the same `::text` mode" is a
requirement on the whole list, and having no `::text` at all is just a third
mode; a query that mixes a text selector with a node selector has no coherent
output (the two output modes are mutually exclusive), so the same error is the
only sensible result.

### Risk: 25
Author most likely prefers: the same error, though an implementation that
compares only the two *text* modes would instead fall through to node output
(or to text output) for `h1::text, h2`.

---

## T17: How "query already extracts text" is detected

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Syntactic: look for the substrings `text()` / `::text` in `QUERY` and skip
   extraction if present. Then `-t "//a[text()='x']"` is also a no-op and
   prints an XML node.
2. Structural: apply extraction only to element results. A query that yields
   strings (from `text()`, `@attr`, `string()`, or `::text`) has nothing to
   extract from, so the flags are automatically no-ops; `//a[text()='x']`
   yields elements and is still extracted.

### Choice
Alternative 2. The spec's condition is semantic -- "query already extracts
text" -- and `text()` inside a predicate does not extract anything; it filters.
Structural detection also makes the rule fall out of the implementation instead
of needing a fragile substring scan, and both readings agree on every query
whose *result* is text.

### Risk: 15
Author most likely prefers: the same for the ordinary cases; a difference shows
up only for a predicate that mentions `text()`, e.g. `-t "//p[text()]"`.

---

## T18: Case sensitivity of CSS element names

### Spec Text
> `--css`: interpret `QUERY` as CSS selector.

Earlier spec section:
> Parse stdin as XML/HTML using case-sensitive element matching.

### Alternatives
1. Translate with cssselect's `GenericTranslator` (XML semantics): `--css Item`
   matches `<Item>` but not `<item>`.
2. Translate with `HTMLTranslator`: element and attribute names are
   lower-cased, so `--css Item` matches `<item>`.

### Choice
Alternative 1. The document is parsed as XML with "case-sensitive element
matching", and a CSS front end that silently lower-cased names would contradict
that for exactly the documents the earlier rule is about.

### Risk: 20
Author most likely prefers: the same, unless they reached for lxml's
`cssselect()` element method, which defaults to HTML translation.

---

## T19: Pseudo-elements other than `::text`

### Spec Text
> Define custom `::text` pseudo-element
> Invalid CSS selector: stderr message, exit code `1`.

### Alternatives
1. `::text` is the only supported pseudo-element; `p::before`, `p::first-line`
   etc. are invalid CSS selectors here (exit 1).
2. Unknown pseudo-elements are ignored and the selector matches elements.

### Choice
Alternative 1. Only `::text` is defined, and cssselect's own translator rejects
every other pseudo-element, so "invalid CSS selector" is the natural outcome.
Silently ignoring `::before` would print element XML for a query the user
clearly did not mean.

### Risk: 10
Author most likely prefers: the same.

---

## T20: `::text` in a query without `--css`

### Spec Text
> ## CSS Query Mode
> - Define custom `::text` pseudo-element

> If query already extracts text (`text()` or `::text`), ...

### Alternatives
1. `::text` is only recognized in CSS mode. Without `--css` the query is an
   XPath expression, and `div::text` is an XPath syntax error -> exit 1.
2. The presence of `::text` implies CSS mode even without `--css`.

### Choice
Alternative 1. The pseudo-element is defined under "CSS Query Mode", and
`--css` is what selects the query language; auto-detecting the language from
the query text is not described anywhere. The Flag Rules mention `::text`
because the same rule covers both query languages, not because `::text` is an
XPath construct.

### Risk: 12
Author most likely prefers: the same.

---

## T21: Whether ` ::text` includes the matched element's own text nodes

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. Every text node in the subtree, including the matched element's immediate
   text children (they are descendants of it). `div ::text` over
   `<div>A<p>B</p></div>` prints `A` then `B`.
2. Only text under *descendant elements*, reading ` ` as the CSS descendant
   combinator applied to elements: prints only `B`.

### Choice
Alternative 1. "All descendant text nodes" is stated in terms of text nodes,
and a text node that is an immediate child is a descendant. This also matches
`--text-all` ("descendant text extraction from matched elements") and the
parsel behavior the syntax is borrowed from.

### Risk: 12
Author most likely prefers: the same.

---

## T22: `--text` applied to a query whose results are attributes or scalars

### Spec Text
> - `-t`, `--text`: direct text extraction from matched elements.

### Alternatives
1. No elements matched, nothing to extract: the flag is a no-op and the
   attribute/number/boolean results print as before.
2. An error, since the flag cannot be honored.

### Choice
Alternative 1, which is the same mechanism as T17: extraction only touches
element results. `-t //a/@href` prints the hrefs, `-t "count(//a)"` prints the
count. The spec never makes a flag fatal.

### Risk: 10
Author most likely prefers: the same.
