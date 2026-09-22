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

### Annotation (CSS/text-extraction spec)
The output is unchanged, but the mechanism moved: dropping whitespace at parse
time made `--text-all` run words together across element boundaries
(`<h1>A</h1><p>B</p>` gave `AB`), so the document is now parsed exactly as
written and the whitespace-only text is dropped from a copy of the node just
before serialization. Extracted text therefore keeps the spacing of the source
while pretty-printed nodes are still re-indented from scratch. See [T15].

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

### Resolved
The file-input addition settles the `INFILE` half: it "takes precedence over
stdin when both are present", so the argument is now read rather than ignored,
and extra positionals after it are the ones that are dropped (see T32). The
unknown-option half stands: `-f`/`-c` are now real options, and anything else
is still argparse's usage error.

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

## T9. Granularity of `--text` and `--text-all`

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements, one per element.

> `--text-all`: descendant text extraction from matched elements, one per element.

> Multi-match text output joins lines with `\n`.

### Alternatives
1. "One per element" is literal: each matched element contributes exactly one
   line, so an element's several text nodes are concatenated before the strip /
   collapse step. `<p>Hello <b>World</b>!</p>` yields `Hello !` for `--text` and
   `Hello World!` for `--text-all`.
2. The flags rewrite the query into a text-node selection (`/text()`,
   `//text()`), so each text node is its own line: `Hello` / `!` for `--text`.

### Choice
Alternative 1. The spec says "one per element" for both flags, and contrasts
that with `selector ::text`, which it describes as "one text node per line" —
a distinction that only exists if the flags aggregate per element. Descendant
extraction uses the XPath string-value of the element (every text node in the
subtree, excluding comments and processing instructions).

### Risk: 15
The author may implement both flags as query rewriting, which would split
mixed content across lines.

## T10. Joining an element's direct text nodes

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements, one per element.

### Alternatives
1. Concatenate the element's child text nodes as they appear in the document
   (`"".join`), which reproduces the source characters minus the child markup:
   `<p>a<b>x</b>c</p>` gives `ac`.
2. Join them with a space so that removed child markup still separates words:
   `a c`.

### Choice
Alternative 1. It is the XPath string-value restricted to child text nodes, and
the two only differ when no whitespace sits next to the removed child — in
`<p>Hello <b>World</b>!</p>` both produce `Hello !` after collapsing.

### Risk: 20
If the author joins with a separator, a fixture with markup directly between
two words expects `a c`.

## T11. Granularity of `selector::text`

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. `::text` is a selector translation in both modes: the query becomes a
   text-node selection, so every direct text node is its own line. `p::text` on
   `<p>Hello <b>W</b>!</p>` gives `Hello` then `!`.
2. `selector::text` means the same thing `--text` means, one joined line per
   element: `Hello !`.

### Choice
Alternative 1. The parenthetical "one text node per line" is attached to the
descendant form because that form is the surprising one, not because the direct
form aggregates; and the natural CSS implementation compiles both modes down to
one XPath text-node expression (`/text()` and `/descendant-or-self::*/text()`,
as Scrapy's `::text` does), leaving per-element aggregation to the flags.

### Risk: 40
If the author treats `--text` and `selector::text` as the same operation —
which the "no-op modifiers" rule hints at — `p::text` on mixed content is
expected to be the single line `Hello !`.

## T12. Whether `selector ::text` includes the matched element's own text

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. "Descendant text nodes" means every text node in the matched element's
   subtree, including its own child text nodes: `div ::text` on
   `<div>Hello <b>W</b></div>` gives `Hello` and `W`.
2. Strict CSS reading: the space is a descendant combinator, so `::text` applies
   to the *descendant elements* only, and the `div`'s own `Hello` is excluded.

### Choice
Alternative 1, matching Scrapy — the established implementation of a `::text`
pseudo-element — which compiles `div ::text` to
`descendant-or-self::div/descendant-or-self::*/text()`. "All descendant text
nodes" of an element reads as the whole subtree, and alternative 2 would make
`--text-all` (the same idea, per element) and `sel ::text` disagree on content
rather than only on line breaking.

### Risk: 20
A strict CSS translation would drop the matched element's own text.

## T13. A `::text` part beside a plain part in a comma-separated selector

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.

> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. A part without `::text` is a third mode; `h1::text, p` is therefore not "the
   same mode" and is rejected with exit code `1`.
2. Only direct-vs-descendant mixing is an error, and `h1::text, p` runs, mixing
   text lines and element nodes in one result.

### Choice
Alternative 1. The supporting condition is stated positively — comma lists are
supported "when all selectors use the same `::text` mode" — and a run mixing
text output with XML node output has no defined rendering, since the two
bullets prescribe different output shapes.

### Risk: 25
The author's check may compare only the two text modes, letting
`h1::text, p` through as a node query with an extra text match.

## T14. Multiple matches in CSS node mode

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

### Alternatives
1. CSS node output is the same output path as XPath node output, so the base
   rule "when multiple XML nodes match, output only the first node" still
   applies.
2. CSS mode prints every matched node.

### Choice
Alternative 1. This bullet describes which output shape CSS mode uses, not a
new multiplicity rule, and nothing in the addition revokes the first-node rule.

### Risk: 15
An author who wired CSS through a separate renderer might print all matches.

## T15. Results that are empty after stripping

### Spec Text
> Strip each result and collapse internal whitespace runs to single spaces.

> Multi-match text output joins lines with `\n`.

### Alternatives
1. Drop results that collapse to the empty string, so the indentation between
   an indented document's elements does not appear as blank lines among the
   real text of a `sel ::text` query, and an element with no direct text
   contributes no line to `--text`.
2. Keep them, emitting one empty line per empty result.

### Choice
Alternative 1. The whitespace-only text nodes of an indented document are
layout, not content; keeping them would make `div ::text` output alternate
between blank and real lines, which no reading of "one text node per line"
seems to intend. This also matches what a parser configured with
`remove_blank_text` would produce, which is the other common way to reach the
same output.

### Risk: 30
If the author emits a line per match unconditionally, a `--text` query over
elements that have no direct text expects blank lines rather than no output.

## T16. Detecting "the query already extracts text"

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Decide from the results: extraction applies to element nodes only, so a
   result that is already a string (a text node, an attribute, or a scalar)
   passes through untouched. Any query that extracts text is therefore
   automatically a no-op, including `string()`, `@attr`, and `normalize-space()`.
2. Scan the query text for `text()` or `::text` and skip extraction if found.

### Choice
Alternative 1. The spec's parenthetical lists the two ways a query extracts
text rather than prescribing a syntactic test, and classifying by result type
gets `//book/@id -t` right (already text) without special-casing.

### Risk: 10
Divergence needs a query that mentions `text()` yet returns elements, such as
`//p[text()]`, where a syntactic test would suppress extraction.

## T17. Pseudo-elements other than `::text`

### Spec Text
> Define custom `::text` pseudo-element

> Invalid CSS selector: stderr message, exit code `1`.

### Alternatives
1. `::text` is the only pseudo-element with a meaning here; `p::before` has no
   translation and is reported as an invalid selector, exit code `1`.
2. Ignore unknown pseudo-elements and match the elements they are attached to.

### Choice
Alternative 1. A selector that cannot be translated is not a selector this
tool accepts, and silently dropping `::before` would print element nodes for a
query that asked for something else.

### Risk: 10
Both readings agree unless a fixture uses a pseudo-element the spec never
mentions.

## T18. What "fails JSON detection" means, and whose error is reported

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.

> Input that fails JSON detection is parsed as XML/HTML.

### Alternatives
1. Detection is one `json.loads` of the whole input: if it yields a `dict` or a
   `list`, the input is JSON; anything else (a primitive, a syntax error, bytes
   that are not UTF-8) is handed to the XML parser, so malformed JSON is
   reported with the XML parse error.
2. Sniff the first non-whitespace character: `{` or `[` commits the input to
   JSON, and a later JSON syntax error is reported as a JSON error rather than
   falling back.

### Choice
Alternative 1. The spec names exactly one fallback rule -- "input that fails
JSON detection is parsed as XML/HTML" -- and gives no JSON-syntax error at all,
while it does spell out a JSON-specific error for invalid keys. If a syntax
error were meant to be reported as JSON, the spec would have had to say so
alongside the key rule.

### Risk: 25
The author may commit on the first character, so `{"a": }` would produce a
message mentioning `json` rather than the XML parser's "start tag expected".
Both readings still exit `1` with something on stderr, so only assertions on the
message text diverge.

## T19. The element name for entries of a nested array

### Spec Text
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.

> Object keys become element tag names (case preserved).

### Alternatives
1. Every array entry, at any depth, becomes an `<item>` element -- the rule is
   stated for the top level because that is where the enclosing element is
   `<root>` rather than a key.
2. `<item>` is special to the top level, and a nested array names its entries
   some other way (after the owning key, or positionally).

### Choice
Alternative 1. Nothing else in the contract could name a nested entry: array
entries have no keys, and the `list` type exists precisely so a nested array is
an element with children of its own. Uniform `<item>` is also what a recursive
converter falls out of naturally.

### Risk: 10
Alternative 2 needs a naming rule the spec never gives.

## T20. The `type` of a whole number written with a fraction

### Spec Text
> Every converted element except `<root>` carries `type` in: `str`, `int`, `float`, `bool`, `dict`, `list`, `null`.

> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`

### Alternatives
1. The type follows the JSON literal's form as Python's `json` module parses it:
   `1` is `int`, `1.0` and `1.50` are `float`, even though all three render as
   text that looks integral.
2. The type follows the rendered text: because `1.0` renders as `"1"`, it is
   reported as `int`, and `float` is reserved for values with a fractional part
   in their output.

### Choice
Alternative 1. The seven type names are exactly Python's type names with `None`
mapped to `null`, which points at `type(value).__name__` over a parsed
`json.loads` result; that yields `float` for `1.0`. The text rule is about
rendering only, and the spec keeps the two concerns in separate bullets.

### Risk: 15
An author who derived the type from the rendered string would expect
`{"n": 1.0}` to carry `type="int"`.

## T21. Float rendering outside the range the examples cover

### Spec Text
> numbers as minimal string form, null as empty (no self-closing tags).
> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

### Alternatives
1. Integral floats render through `int`, and the rest through `repr`, which is
   the shortest string that round-trips. All four examples match, and
   `0.00012` stays in positional notation; magnitudes beyond Python's repr
   threshold switch to exponent (`1e-05`), and a huge integral float expands to
   its full digit string.
2. Format with `%g`, which also matches all four examples but rounds to six
   significant digits, so `3.14159265` would render as `3.14159`.
3. Use `decimal.Decimal(str(value)).normalize()`, which keeps positional
   notation further out but spells large values with `E+`.

### Choice
Alternative 1. "Minimal string form" reads as the shortest spelling that still
denotes the same number, which is exactly `repr`; `%g` discards precision, and
the spec's `0.00012` example is chosen right at the point where `repr` stops
padding, suggesting `repr` is the reference behaviour.

### Risk: 20
Fixtures probably stay near the given examples, where every candidate agrees.
If one strays, the author most likely uses plain `repr` too, so the likeliest
divergence is a tiny value like `1e-05` that the author expected to stay
positional.

## T22. Which key strings count as valid XML element names

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1` (include terms like
> `json`/`key`/`invalid`).

### Alternatives
1. The XML 1.0 `Name` production minus the colon: letters (including non-ASCII
   ones), `_`, then digits, `-`, and `.` after the first character. A key such
   as `a:b` is rejected because it asks for a namespace prefix the converter
   cannot declare -- which is also what lxml does when building the element.
2. The full `Name` production including the colon, so `a:b` is accepted and
   whatever serializer is used has to cope with the bare prefix.
3. An ASCII-only approximation, which would also reject keys like `Ünicode`.

### Choice
Alternative 1. It is the rule the builder itself enforces (lxml raises
`Invalid tag name 'a:b'`), so accepting a colon would mean promising a name the
converter cannot produce. Non-ASCII letters are kept because XML names allow
them and rejecting them would surprise any non-English document.

### Risk: 20
The author most likely validates with the same library, making colon keys
invalid there too; a hand-rolled ASCII regex would instead reject `Ünicode`,
which is the likelier point of divergence.

## T23. How far "no self-closing tags" reaches

### Spec Text
> Primitive values map to element text:
> booleans as `true`/`false`, numbers as minimal string form, null as empty (no self-closing tags).

### Alternatives
1. The rule is about the serialized form of any empty converted element, so an
   empty string, an empty object, and an empty array all render as
   `<a type="str"></a>`, `<a type="dict"></a>`, `<a type="list"></a>` -- no
   `<a/>` anywhere.
2. The parenthetical is scoped to `null` only, and other empty values may
   self-close.

### Choice
Alternative 1. The parenthetical explains how an element with no content is
written at all, and there is no reason the same emptiness would be spelled two
different ways depending on which type produced it. Emitting text (even empty)
for every childless element gives one consistent form.

### Risk: 15
Both readings agree on the only case the spec names; they differ only if a
fixture serializes an empty string, object, or array.

## T24. An invalid key aborts rather than falling back to XML

### Spec Text
> Input that fails JSON detection is parsed as XML/HTML.

> JSON keys that are not valid XML element names are invalid input and must produce stderr output with exit code `1`.

### Alternatives
1. Detection and conversion are separate stages: detection only asks whether the
   input is a JSON object or array, and a bad key found while converting is a
   hard error naming `json`/`key`/`invalid`.
2. A bad key counts as "failing JSON detection", so the input is retried as XML
   and the reported failure is the XML parse error.

### Choice
Alternative 1. The spec demands an error mentioning `json`/`key`/`invalid`,
which the XML fallback could never produce -- the two bullets would contradict
each other under alternative 2.

### Risk: 5

## T25. Duplicate keys in one JSON object

### Spec Text
> Preserve JSON key order in converted XML.

### Alternatives
1. Parse into an ordinary `dict`, so a repeated key keeps the last value and
   contributes one element, at the position of the first occurrence.
2. Preserve the raw member sequence (`object_pairs_hook`), so a repeated key
   contributes one element per occurrence.

### Choice
Alternative 1. Plain `json.loads` already preserves member order in Python, so
the order requirement needs no hook; a converter only reaches for
`object_pairs_hook` when duplicates are a deliberate feature, and the spec never
mentions them.

### Risk: 20
If the author did reach for the hook (to make ordering explicit), duplicates
would emit two elements instead of one.

## T26. Whether `--first` picks the first match or the first printed line

### Spec Text
> `-f`, `--first`: return only first result.

> `--first` applies across text, attribute, and XML-node results.

### Alternatives
1. Truncate after rendering: `--first` keeps the first line that would have been
   written. Because results that collapse to the empty string are dropped
   (see T15), the first *visible* line is what survives, so `-f` on
   `div ::text` over an indented document yields the first real text rather
   than the layout whitespace that precedes it.
2. Truncate before rendering: slice the XPath result to its first item and
   render that. A first item that is whitespace-only then prints nothing even
   though the query matched.

### Choice
Alternative 1. "Return only first result" describes what the user sees, and the
neighbouring bullet says `--first` with *no matches* is what stays silent —
implying that a query which does match produces a line. Alternative 2 would let
a matching query fall silent, which reads as the case the spec singled out as
the no-match behaviour.

### Risk: 35
The author most likely writes `nodes = nodes[:1]` right after evaluation, in
which case a fixture whose first text node is layout whitespace expects empty
output.

## T27. Whether `--first` changes anything for XML-node results

### Spec Text
> `--first` applies across text, attribute, and XML-node results.

> (earlier spec) when multiple XML nodes match, output only the first node.

### Alternatives
1. The first-node rule for XML output still holds unconditionally, so `--first`
   is a no-op on node results and the bullet just says the flag is harmless
   there.
2. The addition retroactively relaxes the base rule: node output now prints
   every matching node, and `--first` is what narrows it to one.

### Choice
Alternative 1. The addition never revokes the earlier bullet, and revoking it
silently through a sentence about a new flag would be a strange way to change
default output. `//book -f` and `//book` therefore print the same first node.

### Risk: 20
If the author took the opportunity to make node output multi-node by default,
`//book` without `-f` would print both books.

## T28. What "no added pretty-print formatting" does to the source's own layout

### Spec Text
> `--compact` affects XML serialization only:
> compact XML output has no added pretty-print formatting.

### Alternatives
1. Compact means a single line: the whitespace-only text between sibling
   elements is layout that serialization owns (the same whitespace T4 drops
   before re-indenting), so `<a>\n  <b>x</b>\n</a>` compacts to
   `<a><b>x</b></a>`. Mixed content — text that carries characters — is
   untouched.
2. Compact means only `pretty_print=False`: whitespace present in the source is
   echoed back, so an indented input serializes exactly as it was written and
   only input that had no whitespace comes out on one line.

### Choice
Alternative 1. The flag is named "compact output mode", and under alternative 2
it would do nothing at all for the common case of an indented XML file, which
would make the JSON bullet ("for JSON-derived input, `--compact` still applies")
the only case where it had any effect. The natural implementation — parse with
blank text removed, then serialize with pretty-printing switched off — also
yields a single line.

### Risk: 30
An author who keeps source whitespace and merely flips `pretty_print` would
expect `<a>\n  <b>x</b>\n</a>` back verbatim for indented input.

## T29. Trailing newline after compact XML output

### Spec Text
> compact XML output has no added pretty-print formatting.

> (earlier spec) No trailing newline.

### Alternatives
1. XML output keeps the single trailing newline it has in pretty-print mode
   (see T3); "no added pretty-print formatting" is about indentation between
   elements, not about the line the payload ends on.
2. A trailing newline counts as added formatting, so compact output ends
   immediately after `</tag>`.

### Choice
Alternative 1, for consistency with T3: compact changes how the node is laid
out internally, not how the payload is terminated. A shell user still gets a
prompt on its own line.

### Risk: 25
If the author emits compact XML with `sys.stdout.write(tostring(...))` and no
newline, an exact-match assertion expects the payload to end at `>`.

## T30. Which input sources accept a UTF-8 BOM, and what an undecodable file is

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.

> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. Read the bullet literally: the BOM rule and the UTF-8 decode are properties
   of file input. Stdin keeps being handed to the parsers as raw bytes, where
   lxml handles a BOM itself but JSON detection does not. A file whose bytes
   are not UTF-8 cannot be decoded, and so is "unreadable": stderr, exit `1`.
2. Route both sources through the same decode, so a BOM on stdin is stripped
   too and non-UTF-8 stdin is an error as well.

### Choice
Alternative 1. The bullet names `INFILE` specifically and sits in a list of
file-input rules, so extending it to stdin would be inventing behaviour the
spec did not ask for. Treating an undecodable file as unreadable keeps the one
error path the spec gives for files, rather than inventing an encoding error.

### Risk: 15
The author may have unified the two sources behind one reader, in which case a
BOM-prefixed JSON document on stdin is expected to work; the divergence is
limited to JSON-on-stdin, since lxml strips a BOM from XML bytes either way.

## T31. Whether `INFILE` of `-` means stdin

### Spec Text
> `INFILE` takes precedence over stdin when both are present.

### Alternatives
1. `-` is an ordinary path. The spec describes exactly one way to select stdin
   — omitting `INFILE` — and says nothing about a conventional dash, so `-` is
   opened, fails, and exits `1`.
2. Follow the widespread convention in which `-` names standard input.

### Choice
Alternative 1. The spec's own precedence rule already covers "read stdin
instead", and adding a magic filename would make `xjq.py q -` behave
differently from every other value of `INFILE`.

### Risk: 15
An author who reached for the convention would expect `-` to read stdin
successfully. (`-` also risks being taken for an option by some parsers, which
argparse does not do.)

## T32. Whether the ignored extra positionals may look like paths

### Spec Text
> Additional positional args after `QUERY [INFILE]` are ignored.

### Alternatives
1. Ignored means never inspected: they are collected and dropped, so a
   nonexistent path or a directory among them changes nothing.
2. Ignored means "not used as input", but they are still validated somehow.

### Choice
Alternative 1 — there is nothing to validate them against. `xjq.py q real.xml
/no/such/file` reads `real.xml` and exits `0`.

### Risk: 5
Both readings agree except in the unlikely case that an author validates
arguments it has already declared unused.

## T33. Whether "immediate text" includes text that follows a child element

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

> Use immediate text only (exclude descendant text from child elements).

### Alternatives
1. Immediate text is every text node that is a direct child of the element, so
   `<p>Hello <b>World</b>!</p>` exports `"Hello !"`: the `!` belongs to `<p>`,
   not to `<b>`, even though it is written after `</b>`.
2. Immediate text is only the text before the first child element (lxml's
   `.text`), so the same element exports `"Hello"` and the trailing `!` is lost.

### Choice
Alternative 1. The exclusion the spec names is "descendant text from child
elements", and `!` is not a child element's text; it is the parent's. This also
keeps the export consistent with `--text`, which the earlier spec defines as
direct text extraction and which already joins an element's own text nodes
(AMBIGUITIES T10).

### Risk: 45
The author most likely writes `element.text or ""`, in which case a mixed-content
fixture expects only the text that precedes the first child.

## T34. Whether exported JSON values are stripped and whitespace-collapsed

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. Normalize each value the way every other text result is normalized: strip the
   ends and collapse internal whitespace runs to single spaces. An element whose
   only immediate text is the source's indentation exports `""`.
2. Export the raw characters, so `//book` over an indented document exports
   `"\n    "` and a value keeps its source line breaks.

### Choice
Alternative 1. The spec's normalization rule ("strip each result, collapse
internal whitespace runs") is the document-wide treatment of extracted text, and
the JSON section changes only the container, not what counts as an element's
text. Raw layout whitespace as a JSON value would also make the export depend on
the source's indentation.

### Risk: 35
The author may strip only (no internal collapse), which differs for an element
whose immediate text spans lines; or export raw text, which differs for every
indented container element.

## T35. Trailing newline after JSON output

### Spec Text
> Default JSON formatting: 2-space indent.

### Alternatives
1. End the JSON payload with a newline, as XML node output does.
2. Write the JSON with no trailing newline, as text results do.

### Choice
Alternative 1. JSON export is a whole-document rendering like the XML node
output it replaces, and the natural implementation (`print(json.dumps(...))`)
ends with a newline.

### Risk: 30
If the author writes the payload with `sys.stdout.write`, an exact-string
assertion on the export would expect no trailing newline.

## T36. What "zero-indent JSON layout" means under `--compact`

### Spec Text
> With `--compact`, produce zero-indent JSON layout (no leading whitespace).

### Alternatives
1. `json.dumps(..., indent=0)`: one token per line, with no leading whitespace on
   any line.
2. A single line with no whitespace at all (`json.dumps(..., separators=(",",":"))`),
   which also has no leading whitespace.

### Choice
Alternative 1. "Zero-indent" names an indent width rather than the absence of
line breaks, and the parenthetical "(no leading whitespace)" describes exactly
what an indent of `0` produces; a single-line rendering would more naturally be
called "one line" or "no whitespace".

### Risk: 30
The author may have implemented compact as a single-line dump, in which case a
fixture expects `[{"title": "Dune"}]` on one line.

## T37. `--json` when the query matches nothing

### Spec Text
> `-j`, `--json`: JSON export mode for XML element results.

> (earlier spec) No-match output: write nothing to stdout/stderr.

### Alternatives
1. Write nothing: with no element results there is nothing to export, and the
   no-match rule still governs.
2. Write an empty array `[]`, since the export shape is always an array.

### Choice
Alternative 1. The no-match bullet is unconditional in the earlier spec, and
JSON mode is described as applying to "XML element results" — with none, the
mode has nothing to act on and output falls back to the empty payload.

### Risk: 30
If the author's code builds the list first and dumps it unconditionally, a
no-match fixture expects `[]`.

## T38. Non-ASCII characters in exported JSON

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. Use the JSON library default, escaping non-ASCII as `\uXXXX`.
2. Emit the characters as UTF-8, matching how the rest of the tool writes
   document text.

### Choice
Alternative 1. The plainest implementation is `json.dumps(...)` with its default
`ensure_ascii=True`, and escaped output is still exactly the same JSON value.

### Risk: 20
Only an exact-string assertion over non-ASCII text can tell the two apart; if the
author passed `ensure_ascii=False`, such a fixture expects literal characters.

## T39. How a query is recognized as a union

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Decide from the query text: an expression containing a `|` operator outside
   string literals is a union, and only then does `--text-all` concatenate.
2. Decide from the results: concatenate whenever `--text-all` matches more than
   one node, union or not.

### Choice
Alternative 1. The earlier spec fixes `--text-all` as "one per element" for
ordinary queries, and the tests for `//h1` depend on that; only the union bullet
overrides it, so the override has to be tied to the query being a union.

### Risk: 20
Divergence needs a `|` in an unusual position (inside a predicate, or inside a
string literal), where a cruder or finer detector than this one disagrees.

## T40. What separates the concatenated text of union matches

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Join the matches' descendant text with a space (or any whitespace, which
   normalization then collapses to one space), so `//title | //author` yields
   `Dune Frank Herbert Les Miserables Victor Hugo`.
2. Concatenate with no separator at all, yielding `DuneFrank Herbert...`.

### Choice
Alternative 1. "One normalized output string" implies normalization is the last
step, which is only meaningful if the joined parts carry separating whitespace;
and running words together would make the mode useless for the documents it is
meant for.

### Risk: 35
An author who wrote `"".join(...)` before normalizing expects the run-together
spelling whenever two matches' text meets without surrounding whitespace.

## T41. Whether `--text` also concatenates across union matches

### Spec Text
> `--text` and `--text-all` apply across union queries.

> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Only `--text-all` concatenates; `--text` keeps the ordinary one-line-per-match
   layout, and the first bullet only says both flags remain effective for unions.
2. Both flags concatenate into a single string.

### Choice
Alternative 1. The concatenation bullet names `--text-all` alone, right after a
bullet that mentions both flags — naming one of two in the very next sentence
reads as deliberate.

### Risk: 25
If the author's union path is shared by both flags, `-t "//title | //author"` is
expected on one line.

## T42. Detecting a union sub-path that "already performs text extraction"

### Spec Text
> If any union sub-path already performs text extraction, text flags are treated
> as no-op query modifiers.

### Alternatives
1. Decide from the results: a union that yields any string result (a text node,
   an attribute) already extracts text, so the text flags are dropped and the
   result is formatted by the default rules.
2. Scan each sub-path for `text()` (or an attribute step) and drop the flags on a
   syntactic match.

### Choice
Alternative 1, which is the same result-based test the earlier spec's "query
already extracts text" bullet gets (AMBIGUITIES T16). It also makes this bullet
agree with the neighbouring one: a union whose sub-paths disagree about type is
written as text results either way.

### Risk: 25
A union such as `//p[text()] | //div`, which mentions `text()` but returns only
elements, extracts descendant text here and would be a no-op under a syntactic
test.

## T43. How an element renders when a mixed union is "written as text results"

### Spec Text
> A union with mixed result types is written as text results.

### Alternatives
1. Each element contributes its descendant text (its XPath string-value),
   normalized, on its own line, beside the string results.
2. Each element contributes only its direct text, so an element wrapping other
   elements contributes an empty line that is then dropped.
3. Elements are still serialized as XML and only the strings are lines.

### Choice
Alternative 1. "Written as text results" says the whole result goes down the
text path, so every member needs a text rendering; the string-value is XPath's
own answer for "the text of this node" and loses nothing from the match.

### Risk: 35
The author may use direct text (their `--text` helper) for the element members,
which differs whenever a matched element has element children.

## T44. `--json` on a union of elements

### Spec Text
> `-j`, `--json`: JSON export mode for XML element results.

> Support XPath `|` union in XPath mode.

### Alternatives
1. A union that yields only elements is an element result like any other, so the
   export lists every matched element in document order.
2. JSON export is defined only for simple paths and a union falls back to the
   default node output.

### Choice
Alternative 1. Nothing in the JSON section restricts the query shape, and a union
of elements is exactly "XML element results".

### Risk: 15
Only an author who special-cased unions out of JSON mode would disagree.

## T45. A `|` selector the CSS engine accepts but XPath then rejects

### Spec Text
> In CSS mode, pass `|` through as CSS query text (no XPath union semantics).
> If the CSS engine rejects the selector, report a CSS selector error on stderr
> with exit code `1`.

### Alternatives
1. Any failure of a CSS-mode query is reported as a CSS selector error. `h1 | p`
   is rejected by the parser; `h1|h2` parses as a namespaced type selector and
   translates to XPath that names an undeclared prefix, and that failure is
   reported the same way.
2. Only parser rejections are CSS errors; a translated selector that XPath
   cannot evaluate is reported as an XPath error.

### Choice
Alternative 1. In CSS mode the user never wrote XPath, so an XPath diagnostic
would name a language they did not use; both failures mean "this selector does
not work", which is what the bullet asks to report. Exit code `1` either way.

### Risk: 25
The author may let the XPath error surface unchanged, so a fixture asserting the
message mentions `css` for `h1|h2` would fail — though a fixture that only
checks the exit code agrees with both.
