# Ambiguities

Numbered record of spec under-specification, the interpretation chosen, and the
risk that the spec author's own implementation reads it differently.

## T1. Strict XML parsing vs. lenient HTML recovery

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. Parse strictly as XML (lxml `XMLParser`), which keeps element-name case and
   rejects anything not well-formed. Plain HTML that is not well-formed XML
   (`<br>`, unclosed `<p>`) fails with the parse error.
2. Parse as XML and, on failure, retry with a recovering/HTML parser. Nearly all
   input then parses, so "malformed XML" can only be reported for input that
   yields no element at all (e.g. empty, or plain text).

### Choice
Alternative 1 — a strict XML parse. The spec devotes a dedicated bullet to
malformed input producing exit code `1`, which only has teeth if recovery is
off; and the explicit call-out of "case-sensitive element matching" is exactly
what distinguishes lxml's XML parser from its HTML parser (the latter
lowercases tag names). "XML/HTML" is read as "XML, including HTML/XHTML
documents that are well-formed".

### Risk: 30
The author may parse with `recover=True` (or an HTML fallback), in which case a
fixture like `<a><b></a>` is expected to succeed rather than exit `1`.

## T2. What counts as an "XML node result" vs. a "text/attribute result"

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline. No trailing newline.

> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. Classify per result item: element (and comment/PI) nodes serialize as XML,
   string results (from `text()`, `@attr`, `string()`) go through the
   strip/collapse/join path. A mixed node-set (`//a | //b/text()`) is treated as
   XML because it contains at least one element.
2. Classify by the type of the whole XPath result only, treating any node-set as
   XML and only `string()`/`count()`-style scalars as text — which would
   serialize `//a/text()` results as XML text nodes.

### Choice
Alternative 1. lxml returns attribute and `text()` hits as strings, so the
"text/attribute" bullet maps precisely onto string items, and the "XML node"
bullet onto element items. Scalar XPath results (`count()`, `string()`,
`boolean()`) are formatted as text using XPath 1.0 string conversion
(`3`, not `3.0`; `true`/`false`).

### Risk: 20
A mixed node-set, or a boolean/number result, may be rendered differently by the
author; most likely divergence is a number printed as `3.0`.

## T3. Trailing newline after pretty-printed XML

### Spec Text
> XML node results: pretty-print serialized XML

> No trailing newline.

### Alternatives
1. "No trailing newline" governs only the text/attribute bullet it appears in;
   XML output ends with a single newline, as lxml's `pretty_print` produces.
2. The no-trailing-newline rule is global, so XML output is also emitted with
   its final newline stripped.

### Choice
Alternative 1. The sentence sits inside the text/attribute bullet, and the
natural implementation writes lxml's pretty-printed string straight out, which
already terminates in exactly one newline.

### Risk: 25
If the author strips the whole payload before writing, an exact-match assertion
on XML output would expect no trailing newline.

## T4. Whether pretty-printing re-indents already-indented input

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Drop whitespace-only text nodes at parse time (`remove_blank_text=True`) so
   the selected node is re-indented from scratch with a uniform two-space
   indent, independent of the source layout.
2. Keep source whitespace, so `pretty_print` only adds indentation where the
   document had none; a node lifted out of an indented document keeps the
   original (now inconsistent) leading indentation of its children.

### Choice
Alternative 1: `<a>\n  <b>x</b>\n</a>` rather than `<a>\n    <b>x</b>\n  </a>`.
"Pretty-print" promises canonical formatting, and mixed content (elements with
real text) is left untouched by `remove_blank_text`, so text results are
unaffected except for whitespace-only `text()` nodes, which would collapse to
empty strings anyway.

### Risk: 35
The author most likely calls `tostring(..., pretty_print=True)` on a plainly
parsed tree, so an expectation captured from an indented fixture would carry the
source indentation.

## T5. Serialized node includes its tail text

### Spec Text
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. Serialize the node alone (`with_tail=False`).
2. Use lxml's default, which appends the node's tail text (the whitespace or
   text following the closing tag in the source document).

### Choice
Alternative 1. "Output only the first node" means the node, not trailing sibling
text; a tail would also add stray blank lines to the output.

### Risk: 10
Only observable as trailing whitespace, which most assertions normalize away.

## T6. Namespaced documents

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. Standard XPath 1.0 semantics: an unprefixed name matches only elements with
   no namespace, so `//p` misses an XHTML document's `<p>` elements.
2. Strip namespaces from the parsed tree so unprefixed queries match everything.

### Choice
Alternative 1. The spec names XPath 1.0 explicitly and says nothing about
rewriting the document; silently discarding namespaces would break `local-name()`
and `namespace-uri()` queries a conforming XPath 1.0 engine must support.

### Risk: 15
If the author tests an XHTML/namespaced fixture with a bare `//tag` query, they
would need namespace stripping to get a match.

## T7. Unknown options and the unused INFILE argument

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

> `INFILE`: accepted positional argument but not used.

### Alternatives
1. `[OPTIONS]` is a placeholder; the only options are argparse's `-h/--help`,
   and an unrecognized flag is a usage error (argparse's exit code `2`).
2. Silently ignore unknown options too, since the spec names none.

### Choice
Alternative 1. No option is specified anywhere in the spec, so there is nothing
to implement beyond help; standard argparse behaviour is the least surprising.
`INFILE` is accepted and ignored — input always comes from stdin.

### Risk: 10
A test for an unknown flag (unlikely, since none are specified) might expect
exit `1` rather than argparse's `2`.

## T8. A query that returns an empty string

### Spec Text
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Only an empty node-set is "no match"; `string(//missing)` returns the empty
   string, which prints as an empty payload — indistinguishable in practice.
2. Treat any empty payload as a no-match and suppress everything.

### Choice
The two coincide on stdout: both write nothing. Empty results never produce a
lone newline, because the join happens only over the results actually present.

### Risk: 5
Divergence would only appear if the author emits a newline per result item.
