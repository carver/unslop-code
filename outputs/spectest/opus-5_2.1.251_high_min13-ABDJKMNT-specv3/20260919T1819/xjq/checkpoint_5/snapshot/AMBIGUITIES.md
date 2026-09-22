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

## T28 — Whether `--first` changes the default for XML-node results

### Spec Text
> `--first` applies across text, attribute, and XML-node results.

against the earlier, unretracted rule

> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. The earlier rule still stands: XML-node output is first-only with or without
   the flag, so `--first` is a no-op there and the phrase only promises the flag
   is accepted for every result kind.
2. This addition relaxes the earlier rule: node results now print every match by
   default, and `--first` is what narrows them to one.

### Choice
Alternative 1. The new section adds flags and file input; it does not restate or
withdraw the XML-node rule, and reading it as a silent relaxation would break
every fixture written against the earlier spec. Listing all three result kinds
reads as "the flag is not text-only", which is worth saying even where it is
already the behavior.

### Risk: 25
An author who revised the tool to print all matching nodes would have a fixture
where `//Item` prints both elements and only `-f //Item` prints one; the phrase
naming XML nodes is the one hint pointing that way.

## T29 — Where `--first` is applied relative to text extraction

### Spec Text
> `-f`, `--first`: return only first result.
> `--first` applies across text, attribute, and XML-node results.

### Alternatives
1. Truncate the rendered results: whatever would be the first output line is
   kept, so with `--css 'div ::text'` the first descendant text node wins.
2. Truncate the matched nodes before text extraction: the first matched element
   is kept, and all of its text nodes are printed.

### Choice
Alternative 1. "Return only first result" is phrased about results, which the
Output Rules section measures in printed results, not in matched elements; and
it is the reading that makes `-f` mean "one line of output" for every mode.
The two agree everywhere except `selector ::text`, the only mode where one
element yields several results.

### Risk: 20
An author who slices the node set right after evaluation would print every text
node of the first matching element instead.

## T30 — `--first` against a scalar result

### Spec Text
> `-f`, `--first`: return only first result.

### Alternatives
1. A scalar from `count()`, `string()` or `boolean()` is a single result, so the
   flag changes nothing and the value is still printed.
2. Scalars are not results in the node-set sense, so `--first` suppresses them.

### Choice
Alternative 1. Suppressing output that a plain run prints would make `--first`
subtractive rather than limiting, which no wording suggests; the natural
implementation slices a list and leaves non-lists alone.

### Risk: 8
Only an implementation that refuses to render scalars under the flag would
differ, and nothing in the spec hints at one.

## T31 — File bytes that are not valid UTF-8

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. A decode failure makes the file unreadable: stderr message, exit code `1`.
2. Fall back to another encoding, or hand the raw bytes to the XML parser so an
   `encoding="latin-1"` declaration can be honoured.

### Choice
Alternative 1. The spec names exactly one decoding, and a file whose bytes are
not that encoding cannot be read as the text the tool was told to read;
grouping it with "unreadable" keeps the single documented failure mode. Stdin
is untouched by this rule and still reaches the parser as bytes (see T34).

### Risk: 15
An author who passes the file's bytes straight to their parser after a BOM check
would accept a declared non-UTF-8 document instead of exiting `1`.

## T32 — Whether compact output may self-close empty elements

### Spec Text
> compact XML output has no added pretty-print formatting.
> For JSON-derived input, `--compact` still applies to resulting XML output.

against

> null as empty (no self-closing tags)

### Alternatives
1. Compact only removes the indentation and line breaks that pretty-printing
   adds; a converted `null` still serializes as `<v type="null"></v>`.
2. Compact is the shortest possible serialization, so empty elements collapse to
   `<v type="null"/>`.

### Choice
Alternative 1. The phrase limits compact to "no added pretty-print formatting",
and the JSON contract's no-self-closing rule is about the element's content
model, not its layout -- an empty-text element serializes with both tags under
either flag. Note this concerns converted JSON elements; an element that was
self-closing in the XML source stays self-closing in both modes.

### Risk: 10
Only an author who serializes converted documents through a different code path
under `--compact` would emit `<v type="null"/>`.

## T33 — Extra arguments that look like options

### Spec Text
> Additional positional args after `QUERY [INFILE]` are ignored.

### Alternatives
1. Only surplus positionals are ignored; an unrecognized `--flag` is still a
   usage error.
2. Everything after `INFILE` is ignored, options included.

### Choice
Alternative 1. The phrase says "positional args", and argument parsers reject
unknown options by construction -- ignoring them would take deliberate extra
work and would silently swallow a mistyped `--compact`.

### Risk: 12
An author parsing `argv` by hand, or using `parse_known_args`, would accept a
trailing unknown option instead of exiting with a usage error.

## T34 — Whether the UTF-8/BOM rule also governs stdin

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.

### Alternatives
1. The rule is about file input only. Stdin keeps reaching the parser as raw
   bytes, so an XML encoding declaration is still honoured there.
2. Both sources are decoded the same way, so a BOM on stdin is stripped too.

### Choice
Alternative 1. The sentence names `INFILE`, and it sits in a section about the
new file source; decoding stdin as UTF-8 as well would reject documents that
declare another encoding, which no earlier rule allows to regress. The two
readings agree on a BOM anyway: `json.loads` and the XML parser both accept one
in front of byte input, so BOM-prefixed stdin works either way.

### Risk: 12
An author who decodes both sources into one string would reject a UTF-16 stdin
document that this reading still parses.

## T35 — `-` as `INFILE`

### Spec Text
> `INFILE` takes precedence over stdin when both are present.
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. `-` is an ordinary path: no file of that name exists, so it is an unreadable
   file and exits `1`.
2. `-` is the conventional spelling for "read stdin".

### Choice
Alternative 1. The spec gives the stdin fallback a spelling already -- omit
`INFILE` -- and says nothing about a special path, so adding one would invent
behavior. A missing `./-` follows the stated error rule.

### Risk: 20
An author reaching for `argparse.FileType` or `fileinput` gets the `-` shortcut
for free and may have a fixture piping a document with `-` as the path.

## T36 — Whether `--json` exports every match or only the first

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> With `--first`, still return a JSON array containing one exported element.

### Alternatives
1. `--json` exports every matched element; `--first` narrows the array to one
   entry.
2. `--json` follows the default element rule (only the first match is ever
   written), so `--first` changes nothing and the array always holds one entry.

### Choice
Alternative 1. Calling out `--first` as the case that yields "one exported
element" only carries information if the flagless case can yield more, and an
"array of objects" that never holds more than one object would be a strange
contract to spell out.

### Risk: 10
An author who bolted JSON onto an existing "serialize the first node" branch
would emit a one-entry array either way.

## T37 — What counts as `immediate_text_content`

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> Use immediate text only (exclude descendant text from child elements).

### Alternatives
1. Every text node that is a direct child of the element, concatenated: for
   `<a>x<b>Y</b>z</a>` that is `"xz"`.
2. Only the leading text before the first child (lxml's `.text`, a DOM's
   `firstChild.data`): `"x"`.

### Choice
Alternative 1. "Immediate text" names a relationship -- text that belongs to the
element itself rather than to a child -- and the trailing `z` qualifies as much
as the leading `x`; the parenthetical excludes only *descendant* text. It also
keeps `--json` consistent with `--text`, which already concatenates the direct
text nodes of a match.

### Risk: 25
An author writing `{el.tag: el.text or ""}` gets reading 2, which differs
whenever a child element is followed by text.

## T38 — Whether exported JSON values are whitespace-normalized

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. Normalize each value the way every other text result is normalized: strip it
   and collapse internal whitespace runs to single spaces.
2. Export the raw text exactly as it stands in the document, newlines and
   indentation included.

### Choice
Alternative 1. The tool's output contract normalizes text results everywhere
else, and a container element whose only direct text is the source indentation
exports as `""` rather than `"\n    "`, which is what a JSON consumer of a
`{tag: text}` map expects.

### Risk: 25
An author who dumps the raw text would differ on any element whose direct text
carries source whitespace -- though a parser that drops blank text (T2) hides
most of that difference.

## T39 — What "zero-indent JSON layout" means under `--compact`

### Spec Text
> With `--compact`, produce zero-indent JSON layout (no leading whitespace).

### Alternatives
1. `json.dumps(..., indent=0)`: one token per line, no line ever indented.
2. The single-line `json.dumps(...)` default, with no newlines at all.

### Choice
Alternative 1. "Zero-indent" describes an indentation level of zero rather than
the absence of layout, and the gloss "no leading whitespace" only needs saying
if lines still exist to be indented; a single-line dump would have been called
compact or minified instead.

### Risk: 25
An author who reads `--compact` as "everything on one line", matching how the
flag already collapses XML output, would emit `[{"a": "x"}]`.

## T40 — Escaping of non-ASCII text in JSON export

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. Leave `json.dumps` at its default `ensure_ascii=True`, so `café` exports as
   `"café"`.
2. Emit the characters themselves with `ensure_ascii=False`.

### Choice
Alternative 1, the library default: the spec says nothing, both forms are the
same JSON value, and an implementation that simply calls `json.dumps` with an
indent gets the escaped form.

### Risk: 20
An author who passes `ensure_ascii=False` to keep the output readable alongside
the tool's UTF-8 text output would print the literal characters.

## T41 — `--json` when the query matches nothing

### Spec Text
> `-j`, `--json`: JSON export mode for XML element results.
> Export shape: JSON array of objects

### Alternatives
1. Print nothing, following the established rule that a query with no matches
   produces no output.
2. Print `[]`, so that JSON mode always emits a parseable document.

### Choice
Alternative 1. Silence on an empty result is already the tool's behavior, and
there are no "XML element results" to export; JSON mode is described as a way of
formatting element results, not as a guarantee that stdout parses as JSON.

### Risk: 30
An author who serializes the (possibly empty) match list unconditionally prints
`[]`.

## T42 — What separates the texts concatenated for a union under `--text-all`

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Separate each match's text with whitespace before normalizing, so
   `//a | //b` over `<r><a>alpha</a><b>beta</b></r>` gives `alpha beta`.
2. Concatenate the texts directly and let normalization only collapse whatever
   whitespace the document itself supplied, giving `alphabeta`.

### Choice
Alternative 1. The result is described as one *normalized* string -- the form
the tool uses for human-readable text output -- and gluing the last word of one
match to the first word of the next produces a token that appears in neither
match. Since this implementation drops blank text at parse time (T2), relying on
source whitespace to separate matches would fail far more often than it would in
a tree that kept it.

### Risk: 40
The author most likely joins with `""` and relies on the document's own
whitespace, which their fixture may well contain.

## T43 — Whether `--text` also collapses a union into one string

### Spec Text
> `--text` and `--text-all` apply across union queries.
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Only `--text-all` concatenates; `--text` keeps the normal one-result-per-match
   output, one per line.
2. Both flags collapse a union into a single string, the first sentence covering
   both and the second merely restating it for the descendant case.

### Choice
Alternative 1. The concatenation sentence names `--text-all` alone, right after a
sentence that names both flags, so the narrowing is deliberate; "apply across
union queries" says the flags reach every match, not that the matches merge.

### Risk: 25
An author who implemented one shared "union text" branch would collapse `--text`
output onto one line as well.

## T44 — How "a union sub-path already performs text extraction" is detected

### Spec Text
> If any union sub-path already performs text extraction, text flags are treated
> as no-op query modifiers.

### Alternatives
1. Detect it from the result: if any matched item is not an element, the query
   already produced text and the flags extract nothing.
2. Inspect the query string for sub-paths ending in `text()` (and perhaps `@attr`
   or `string()`), and disable the flags on that syntactic evidence.

### Choice
Alternative 1. It needs no XPath parser, and it agrees with the rule the spec
already states for the non-union case -- `--json` and the text flags have no
effect once results are "auto-detected as text" -- so one test on the result
covers both sentences. A sub-path whose text extraction produced no match at all
contributes nothing to distinguish the readings.

### Risk: 20
A syntactic check differs when a text-extracting sub-path matches nothing:
`//a | //b/text()` over a document with no `b` still disables the flags for the
author but not here.

## T45 — How elements are written when a union has mixed result types

### Spec Text
> A union with mixed result types is written as text results.

### Alternatives
1. Every item becomes a text result: an element contributes its string value
   (all descendant text), normalized and on its own line.
2. Only the non-element items are text; the elements are still serialized as
   XML, interleaved with them.

### Choice
Alternative 1. "Written as text results" names the output rule that applies to
the whole result -- strip, collapse, one per line -- and XPath's own
element-to-string conversion is its descendant text, so that is what an element
contributes to a text stream.

### Risk: 20
An author who serializes the element and normalizes the resulting markup would
print the tags as one of the text lines.

## T46 — Which node is "the first matched union node"

### Spec Text
> If `--first` is also active with union + `--text-all`, only the first matched
> union node contributes to the output.

### Alternatives
1. The first node of the union result in document order, which is what an XPath
   engine returns.
2. The first match of the leftmost sub-path, ordering the result by sub-path
   rather than by position.

### Choice
Alternative 1. XPath unions are unordered sets that every engine returns in
document order, and `--first` already means "the first result" elsewhere in the
tool; reading it as "first sub-path" would require re-ordering the result on
purpose.

### Risk: 20
A fixture written as `//late | //early` distinguishes the two, and an author who
evaluates each sub-path separately and chains the results would get reading 2.

## T47 — CSS `|` that `cssselect` accepts but XPath cannot evaluate

### Spec Text
> In CSS mode, pass `|` through as CSS query text (no XPath union semantics).
> If the CSS engine rejects the selector, report a CSS selector error on stderr
> with exit code `1`.

### Alternatives
1. Report a CSS selector error for any failure of a `--css` query, including one
   that only surfaces when the translated XPath is evaluated (`a|b` is a valid
   namespaced type selector, and translates to an XPath with an undeclared
   prefix).
2. Report only a translation failure as a CSS error and let an evaluation
   failure surface as an XPath error, since the CSS engine did accept it.

### Choice
Alternative 1. In CSS mode the user never wrote an XPath expression, so naming
one in the error would point at an implementation detail; the spec's intent is
that a `|` selector the CSS path cannot honour fails as a selector error with
exit `1`.

### Risk: 20
Both readings exit `1` and differ only in wording; an author whose translation
and evaluation are separate steps reports the XPath error for the unspaced
`a|b` form.

## T48 — Trailing newline after JSON output

### Spec Text
> Default JSON formatting: 2-space indent.

### Alternatives
1. JSON output follows the tool's existing rule that stdout never ends in a
   newline (T3).
2. JSON is a document format and ends with a newline.

### Choice
Alternative 1, for one uniform rule across every output mode; `json.dumps` does
not add a trailing newline of its own either.

### Risk: 15
An author who `print()`s the dump ends the output with a newline.
