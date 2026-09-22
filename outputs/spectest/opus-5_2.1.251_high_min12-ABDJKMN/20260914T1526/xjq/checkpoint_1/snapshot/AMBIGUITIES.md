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
