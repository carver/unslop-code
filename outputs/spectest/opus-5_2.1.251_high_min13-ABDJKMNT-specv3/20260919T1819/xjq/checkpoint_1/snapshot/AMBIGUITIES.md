# Ambiguities

Interpretation decisions taken while implementing the `xjq.py` spec.

## T1 — Which parser handles "XML/HTML"

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

and

> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. Parse strictly as XML only. HTML-shaped input works when it is well-formed
   (XHTML-ish), and anything else is a parse error.
2. Try XML first, fall back to an HTML parser (or an error-recovering XML
   parser) so that tag soup such as `<ul><li>a<li>b</ul>` still queryable.

### Choice
Alternative 1: a strict `lxml.etree.XMLParser`. The "case-sensitive element
matching" requirement rules out lxml's HTML parser, which lowercases tag names,
and a recovering fallback would swallow exactly the malformed documents that the
Errors section requires to exit `1` (`<r><a></r>` is repaired silently by both
`HTMLParser` and `XMLParser(recover=True)`). Reading "XML/HTML" as "the document
may be HTML-shaped, but it is read as XML" is the only interpretation under which
both requirements hold at once.

### Risk: 25
The author may accept real tag soup via an HTML parser with case preserved (e.g.
`html5lib`/`BeautifulSoup` with XML-ish tree building), erroring only on empty or
completely non-markup input.

## T2 — Where the indentation of pretty-printed output comes from

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Re-indent the selected node from scratch (parse with `remove_blank_text=True`
   so lxml's `pretty_print` is free to lay the subtree out itself).
2. Serialize the node as it was written in the input, preserving the source
   whitespace; `pretty_print` then only affects nodes that had no text.

### Choice
Alternative 1. "Pretty-print" implies normalized, uniform indentation regardless
of how the input was formatted, and with lxml that only happens when the blank
text nodes of the source are dropped first. A side effect is that whitespace-only
text nodes are not selectable by `//text()`, which is consistent with the output
rules stripping every text result anyway.

### Risk: 30
The author most likely calls `etree.tostring(node, pretty_print=True)` on a tree
parsed without `remove_blank_text`, which echoes the source indentation for any
element that already contained whitespace.

## T3 — Trailing newline after an XML node result

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline. No trailing newline.
> XML node results: pretty-print serialized XML

### Alternatives
1. "No trailing newline" is a global output rule: strip the newline that
   `pretty_print` appends too.
2. It applies only to the text/attribute sentence, so the serialized XML keeps
   the trailing newline that the serializer emits.

### Choice
Alternative 1, for a uniform rule: stdout never ends with `\n`. Tests that
compare exact bytes for the text case would otherwise need a different rule per
branch, and a consumer that cares can add the newline.

### Risk: 35
The author may print the serializer output verbatim (`print(...)` or
`sys.stdout.write(tostring(...))`), leaving one trailing newline for XML results.
A fixture comparing stripped output hides the difference either way.

## T4 — Formatting of non node-set results

### Spec Text
> Evaluate `QUERY` with XPath 1.0.
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.

### Alternatives
1. Format numbers and booleans with XPath 1.0 `string()` semantics:
   `count(//a)` → `2`, `boolean(//a)` → `true`.
2. Use Python's own repr of the value lxml returns: `2.0` and `True`.

### Choice
Alternative 1. The output section only names text/attribute and node results, so
scalars fall through to "text"; since the query language is XPath 1.0, its own
number-to-string conversion (no decimal point for integral values, lowercase
booleans) is the most defensible reading, and `2` is what a user of an XPath tool
expects from `count()`.

### Risk: 40
The author's implementation most likely stringifies whatever lxml returns, giving
`2.0` and `True`.

## T5 — Node sets that mix elements with text or attribute nodes

### Spec Text
> Text/attribute results: ... XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. Classify the whole result by its first item: an element first means the XML
   branch, otherwise the text branch.
2. Classify per item, printing serialized XML for elements and normalized text
   for strings within one output.

### Choice
Alternative 1. The spec describes two whole-result modes, not a per-item mode,
and the "only the first node" rule already assumes a result that is uniformly
nodes. Unions such as `//a/@id | //a/text()` stay in the text branch.

### Risk: 15
The author could branch on "any element present", which differs only when a
union puts a string ahead of an element in document order.

## T6 — The `[OPTIONS]` placeholder

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. No options are defined beyond argparse's built-in `-h/--help`; the
   placeholder just documents standard CLI shape.
2. Invent options (e.g. `--pretty`, `--raw`, `-n`) to fill the placeholder.

### Choice
Alternative 1. The spec defines behavior for no flag at all, and inventing flags
would risk colliding with names the hidden tests use for something else. Unknown
options produce argparse's usage error (exit `2`), which the spec does not cover.

### Risk: 15
The author may define a flag the tests exercise; nothing in the prose hints at
which, so any guess is likelier to conflict than to match.

## T7 — Tail text of a serialized element

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Serialize the element only (`with_tail=False`).
2. Use lxml's default, which appends the text following the element's closing
   tag (its tail).

### Choice
Alternative 1. The result of the query is the node; the characters after its
closing tag belong to the parent, and including them produces output that is not
well-formed XML.

### Risk: 15
The author may call `etree.tostring(node, pretty_print=True)` without
`with_tail=False`, in which case `//a` on `<r><a>x</a>tail</r>` prints the tail.
Only reachable with a fixture that has mixed content.

## T8 — Results that normalize to the empty string

### Spec Text
> strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Keep empty results as empty lines; only an empty node set produces no output.
2. Drop results that are empty after stripping.

### Choice
Alternative 1: apply the stated transformation to every result and join. "No
match" is about an empty result set, not about empty strings. In practice the
case is rare because T2's parsing already removes whitespace-only text nodes.

### Risk: 25
An author who parses without `remove_blank_text` sees blank text nodes routinely
and may well filter them out; their fixture for `//text()` would then contain no
blank lines.

## T9 — Both the input and the query are invalid

### Spec Text
> Invalid XPath: stderr message, exit code `1`; message should reference `xpath`.
> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. Validate the input first, so a malformed document reports the XML error.
2. Validate the query first, so an invalid expression is reported even when the
   document is unusable.

### Choice
Alternative 1, the natural data-flow order: the document has to exist before an
expression can be evaluated against it. Exit code is `1` under either reading, so
only the message text differs.

### Risk: 10
An implementation that compiles the expression up front (`etree.XPath(query)`)
would report the xpath error instead.

## T10 — What counts as "invalid XPath"

### Spec Text
> Invalid XPath: stderr message, exit code `1`; message should reference `xpath`.

### Alternatives
1. Whatever the XPath engine rejects; expressions it tolerates as extensions
   (libxml2 accepts `///a`, for example) are valid and simply match nothing.
2. Strict XPath 1.0 grammar validation of the expression before evaluation.

### Choice
Alternative 1. Implementing a second grammar check ahead of the engine would be
inventing behavior the spec never asks for, and "successful execution, including
zero matches" covers expressions that parse but select nothing.

### Risk: 10
Only differs for expressions in the engine's tolerated grey zone; any
lxml/libxml2-based reference implementation behaves the same way.
