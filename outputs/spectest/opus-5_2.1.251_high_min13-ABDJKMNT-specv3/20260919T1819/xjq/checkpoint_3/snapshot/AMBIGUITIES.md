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

## T11 — What "direct text" of an element is

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements, one per element.
> `selector::text` returns direct text;

### Alternatives
1. Every text node that is an immediate child of the element, concatenated:
   for `<div>Hello <b>World</b>!</div>` that is `"Hello "` + `"!"` → `Hello !`.
2. Only the element's leading text (lxml's `element.text`), i.e. `Hello`.
3. The direct text nodes joined with a space rather than concatenated.

### Choice
Alternative 1. "Direct text" is the natural counterpart of XPath's `text()`,
which selects *all* immediate text-node children, and "one per element" says the
whole element collapses to a single line — dropping the text that follows an
inline child would silently lose content. Concatenation (not space-joining)
keeps the document's own spacing, which the strip/collapse rule then normalizes.

### Risk: 35
The author may have written `element.text or ""`, which yields only the leading
chunk; the difference shows up only for mixed content with text after a child.

## T12 — How many nodes CSS mode prints without text extraction

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

### Alternatives
1. Reuse the existing XML node output rule verbatim, including "when multiple
   XML nodes match, output only the first node".
2. Print every matched element, since CSS selectors are naturally multi-match
   and the sentence does not repeat the first-node restriction.

### Choice
Alternative 1. The sentence points at the already-defined "XML node output"
behavior rather than describing a new one; the phrases that *do* change for the
new modes (multi-match joining) are spelled out under Text Extraction, and no
such wording appears for node output.

### Risk: 30
The author may print all matches in CSS mode; their fixture for `--css "li"` on
a multi-item list would then contain every element.

## T13 — Comma lists that mix `::text` with a plain selector

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. Treat "no `::text`" as a third mode: `a::text, b` is a mode mismatch and
   fails the same way (stderr, exit `1`).
2. Allow it, e.g. by letting the plain selector fall back to node output or by
   applying the `::text` mode of the other selectors to it.

### Choice
Alternative 1. "when all selectors use the same `::text` mode" is a requirement
on the whole list, and a query that would have to emit serialized XML on one
line and text on the next has no defined output format.

### Risk: 20
The author may only compare the two text modes with each other and let a plain
selector through into whatever branch the first selector chose.

## T14 — Text flags against results that are not elements

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements, one per element.
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Extract from element results only; attribute, string, number and boolean
   results pass through untouched. The `text()`/`::text` no-op rule then falls
   out of the same code path, since those queries return strings already.
2. Detect `text()`/`::text` in the query string and otherwise treat any result
   as extractable, converting attributes via `string()`.

### Choice
Alternative 1: the flags say "from matched elements", so anything that is not an
element is nothing to extract from. This also makes `-t //a/text()` and
`-t "count(//a)"` no-ops without string-matching the query text.

### Risk: 20
An author who implements the no-op rule as a literal substring check on the
query would treat `-t //a/@id` as an extraction request and could error or
produce different output there.

## T15 — Elements whose extracted text is empty

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements, one per element.
> Multi-match text output joins lines with `\n`.

### Alternatives
1. Emit one line per matched element even when that line is empty, so line
   count matches element count.
2. Drop results that are empty after stripping.

### Choice
Alternative 1, consistent with T8: "one per element" is a positional promise,
and dropping lines would make the output unusable for correlating with matches.

### Risk: 30
An author filtering falsy strings would print nothing for `-t` over a list whose
elements hold only child elements.

## T16 — Whether `--text`/`--text-all` work in XPath mode

### Spec Text
> ## CLI Additions
> `-t`, `--text`: direct text extraction from matched elements, one per element.
> If query already extracts text (`text()` or `::text`), ... no-op modifiers.

### Alternatives
1. The flags are global: they apply to element results from XPath queries as
   well as from CSS queries.
2. They are only meaningful together with `--css`.

### Choice
Alternative 1. They are listed as CLI additions, not under "CSS Query Mode",
and the no-op rule names `text()` — an XPath construct — which only makes sense
if the flags can accompany an XPath query in the first place.

### Risk: 12
An implementation that wires text extraction into the CSS branch only would
ignore `-t //Item` and print just the first serialized element.

## T17 — Result order for comma-separated `::text` selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.

### Alternatives
1. Document order across the whole list (the selectors are unioned, as CSS
   itself defines a selector list).
2. Selector order: everything matched by the first selector, then the second.

### Choice
Alternative 1. A CSS selector list denotes one set of elements, and both this
tool's XPath mode (`|` unions) and every CSS engine report that set in document
order.

### Risk: 20
An author looping over the split selectors and concatenating each one's results
would get selector order; a fixture like `b::text, a::text` over `<a>` before
`<b>` distinguishes them.

## T18 — `::text` outside CSS mode, and `::text` in the middle of a selector

### Spec Text
> Define custom `::text` pseudo-element
> `--css`: interpret `QUERY` as CSS selector.

### Alternatives
1. `::text` is only recognized in CSS mode, and only as the final pseudo-element
   of a selector; `//div::text` without `--css` is just invalid XPath, and
   `--css "a::text b"` is an invalid selector. Both exit `1`.
2. A `::text` anywhere in the query implies CSS mode.

### Choice
Alternative 1. `--css` is what selects the query language; making the presence
of a substring switch languages would be surprising and would misread valid
XPath axis syntax such as `child::text()`. A pseudo-*element* is by definition
the last component of a selector, so a trailing position is the only place it
can legally appear.

### Risk: 15
Both readings exit `1` on the same inputs; they differ only in the error
message, or if the author accepts `::text` without `--css`.

## T19 — Whitespace-only text nodes under `selector ::text`

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. The nodes that exist in the tree this tool parses — which, per T2, drops the
   blank text used purely for indentation, so `<ul>\n  <li>a</li>\n</ul>` yields
   one line, not three.
2. Every text node of the raw source, including indentation, which after the
   strip rule would appear as blank lines.

### Choice
Alternative 1. It follows from the parsing decision already made in T2 and is
the only reading where `div ::text` on an indented document is useful; blank
lines for indentation carry no information.

### Risk: 25
An author who parses without `remove_blank_text` and does not filter would emit
blank lines for indentation; one who parses that way *and* filters matches this
choice again, so the readings only diverge on indented mixed content.

## T20 — How JSON is detected

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.
> Input that fails JSON detection is parsed as XML/HTML.

### Alternatives
1. Detection *is* a full parse: decode stdin with a JSON parser and accept the
   result only when it is an object or an array. Anything else -- a syntax
   error, trailing garbage, a primitive -- is not JSON input.
2. Sniff the first non-space byte: `{` or `[` commits the input to JSON, so
   `{"a": ` (truncated) reports a *JSON* error instead of falling back.

### Choice
Alternative 1. "Input that fails JSON detection is parsed as XML/HTML" makes
the fallback unconditional, with no third outcome for input that looks like
JSON but does not parse; and the only error the spec defines for JSON input is
the invalid-key one, which implies a successful decode.

### Risk: 12
Both readings exit `1` on `{"a": `, so they differ only in the message text; an
author who sniffs first would say `json`/`parse` where this says `xml`.

## T21 — Tag name for entries of a nested array

### Spec Text
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.

### Alternatives
1. `<item>` names array entries at every depth; the sentence singles out the
   top level only because that is where the enclosing element is `<root>`
   rather than a key-named one.
2. Nested arrays use some other scheme, e.g. repeating the key of the array
   (`{"tags": ["a"]}` → `<tags><tags>a</tags></tags>`).

### Choice
Alternative 1. The `type` vocabulary includes `list` for non-top-level values,
so nested arrays plainly exist and need a tag; `<item>` is the only entry tag
the spec names, and reusing the key would collide with the rule that keys name
elements.

### Risk: 10
Repeating the key is a common JSON-to-XML idiom, but it contradicts the `list`
type carrying children of its own.

## T22 — Minimal string form beyond the given examples

### Spec Text
> numbers as minimal string form.
> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

### Alternatives
1. Python's own shortest round-tripping float repr, with integral floats
   collapsed to their integer form: `1e30 -> "1e+30"` is *not* produced, since
   `1e30` is integral and becomes `1000000000000000019884624838656`.
2. `%g`-style formatting, which yields `1e+30` but silently truncates to six
   significant digits (`0.000123456789 -> "0.000123457"`).
3. `repr` with a trailing `.0` stripped, which keeps `1e+30` as written.

### Choice
Alternative 1. All four examples are satisfied by "drop the fraction when the
value is integral, otherwise use the shortest string that round-trips", which
is exactly `str(int(v))` / `str(v)` in Python; `%g` fails the round-trip
property that `0.00012` illustrates.

### Risk: 15
Divergence needs a magnitude none of the examples reach; the author most likely
wrote the same `is_integer()` collapse, but may have stripped `.0` textually and
so kept exponential notation for huge integral floats.

## T23 — How far "no self-closing tags" reaches

### Spec Text
> null as empty (no self-closing tags).

### Alternatives
1. No converted element ever serializes self-closed: empty strings, empty
   objects and empty arrays get an explicit closing tag as well.
2. The rule is about `null` alone, leaving `""`, `{}` and `[]` to serialize as
   `<k type="str"/>`, `<k type="dict"/>`, `<k type="list"/>`.

### Choice
Alternative 1. The parenthetical explains how "empty" must look on output, and
every other empty element is empty for the same reason; emitting `<a></a>` for
`null` but `<b/>` for `""` would be an inconsistency the spec never asks for.

### Risk: 15
Setting `element.text = ""` is the one-line way to get this and it applies to
every leaf at once, so most implementations land here by construction; an author
who special-cased `null` would differ on `""`, `{}` and `[]`.

## T24 — `int` versus `float` for a value like `1.0`

### Spec Text
> Every converted element except `<root>` carries `type` in: `str`, `int`,
> `float`, `bool`, `dict`, `list`, `null`.
> Examples: `1 -> "1"`, `1.0 -> "1"`

### Alternatives
1. Lexical: `1.0` is written as a JSON float, so `type="float"` even though its
   text renders as `1`.
2. Numeric: `1.0` is integral, so `type="int"` and text `1`.

### Choice
Alternative 1. The example exists precisely to show that the *text* loses the
fraction; if the type followed the text there would be no distinction left to
draw, and JSON's own grammar separates the two spellings. This is also what a
`type(value).__name__` lookup over `json.loads` output gives for free.

### Risk: 15
An author normalizing numbers before typing them would report `int`; the two
readings agree on every number written without a `.` or exponent.

## T25 — Depth at which keys are validated

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1`.

### Alternatives
1. Every key in the document is validated, at any nesting depth.
2. Only top-level keys, since those are the ones the spec describes becoming
   elements.

### Choice
Alternative 1. Nested keys become element names by the same rule, so a nested
`"a b"` would otherwise have to produce an element whose name XML forbids --
which no serializer can emit.

### Risk: 8
Alternative 2 is not implementable without crashing later; any working
implementation validates wherever it creates an element.

## T26 — What makes a key an invalid XML element name

### Spec Text
> JSON keys that are not valid XML element names are invalid input

### Alternatives
1. The XML 1.0 `Name` production, minus the colon: `café` and `_x-1` are valid,
   while `my key`, `1st`, `a<b` and `ns:tag` are not.
2. An ASCII-only approximation such as `[A-Za-z_][A-Za-z0-9_.-]*`, which also
   rejects non-ASCII letters.
3. Full `Name` including the colon, accepting `ns:tag` as a prefixed name.

### Choice
Alternative 1. `Name` is the grammar the phrase points at, so restricting it to
ASCII would reject keys that XML permits. The colon is excluded because a
converted document declares no namespaces, and every XML toolchain (lxml
included) refuses to create an element with an undeclared prefix -- so `ns:tag`
is not a name this tool can use.

### Risk: 20
The author most likely delegates to their XML library's own name check, which
agrees on all of these; a hand-rolled ASCII regex would instead reject `café`.

## T27 — Duplicate keys in a JSON object

### Spec Text
> Object keys become element tag names (case preserved).
> Preserve JSON key order in converted XML.

### Alternatives
1. Standard JSON decoding semantics: the last occurrence wins and the object
   has one entry for the key.
2. Emit one element per occurrence, keeping both values.

### Choice
Alternative 1. "Preserve JSON key order" describes the order of an already
decoded object, and every mainstream JSON parser collapses duplicates that way;
retaining both would require bypassing the decoder deliberately.

### Risk: 10
Only an author using an `object_pairs_hook` would keep both, and nothing in the
spec suggests they do.
