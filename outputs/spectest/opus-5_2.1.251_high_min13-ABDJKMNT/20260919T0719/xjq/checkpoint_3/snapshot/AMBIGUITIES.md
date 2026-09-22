# Ambiguities

Interpretation decisions taken while implementing the "XPath Querying of XML
from Stdin", "CSS Selectors and Text Extraction" and "JSON Input and
Auto-Detection" specs. Each entry quotes the spec, lists the readings that
would change observable behaviour, and records the chosen reading.

## T1: What `[OPTIONS]` contains

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. The placeholder is generic CLI grammar and the tool defines no flags of its
   own beyond the `-h/--help` that an argument parser provides.
2. The tool is meant to expose extra switches (e.g. `--pretty`, `--html`,
   `--raw`) that the spec simply never enumerates.

### Choice
Reading 1. No behaviour anywhere else in the spec is conditional on a flag, so
there is nothing for an option to toggle. `-h/--help` is supported and exits 0;
any other flag is a usage error from `argparse` (exit 2, message on stderr).

### Risk: 15
The author most likely also ships only `--help`; if they added flags, a test
could invoke one this implementation rejects.

### Resolved
The "CSS Selectors and Text Extraction" spec settles this: `[OPTIONS]` is now
`--css`, `-t`/`--text` and `--text-all`. Reading 2 was correct in spirit, and
those three flags plus `-h/--help` are the whole set; anything else is still an
`argparse` usage error.

## T2: "XML/HTML" parsing strictness

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

and

> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Parse strictly as XML. HTML-shaped input works only when it is also
   well-formed XML; anything else is the documented parse error.
2. Parse as XML and, on failure, retry with a lenient HTML recovery parser, so
   tag-soup input still evaluates.

### Choice
Reading 1. A recovering HTML parser accepts essentially every byte string,
which would make the "malformed XML input exits 1" requirement unreachable —
`<library><book></library>` would silently recover instead of failing. The
explicit demand for *case-sensitive* element matching also points at the XML
parser, since lxml's HTML parser lower-cases tag names. "XML/HTML" is read as
"XML, including XHTML-shaped documents".

### Risk: 30
The author most likely parses strictly as XML too, but if they do fall back to
an HTML parser for inputs that look like HTML documents, a tag-soup fixture
would be expected to succeed here rather than exit 1.

## T3: Rendering non-node-set results

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs
> to single spaces, then join results with each on a newline.

and

> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. Numbers and booleans are converted with the XPath 1.0 `string()` rules, so
   `count(//book)` prints `2` and `1 > 0` prints `true`.
2. They are converted with Python's `str()`, so the same queries print `2.0`
   and `True`.

### Choice
Reading 1. The spec pins evaluation to XPath 1.0, whose string conversion
renders integral numbers without a fractional part and booleans in lowercase.
`2.0`/`True` are artefacts of the host language, not of the query language the
spec names.

### Risk: 40
The author most likely formats results with a bare `str()` on whatever lxml
returns, which would make `count(//book)` print `2.0` and a comparison print
`True`.

## T4: Results that normalize to the empty string

### Spec Text
> Text/attribute results: strip each result ...
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Drop results that are empty after normalization, so whitespace-only text
   nodes contribute nothing (and a query matching only such nodes prints
   nothing at all).
2. Keep them, emitting one blank line per whitespace-only node.

### Choice
Reading 1. Indented documents put a whitespace-only text node between every
pair of elements; keeping them turns `//text()` into a column of blank lines,
which contradicts the spirit of "strip, collapse, join" and of the silent
no-match rule.

### Risk: 35
The author may normalize and join without filtering, in which case
`/library/text()` over an indented document is expected to emit blank lines.

## T5: What "pretty-print" means for serialized nodes

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Re-indent the matched node, so compact input such as `<a><b>x</b></a>`
   comes out on multiple indented lines.
2. Serialize with lxml's `pretty_print=True` only, which preserves whatever
   whitespace the source document already had and therefore leaves compact
   input compact.

### Choice
Reading 1, with two-space indentation (lxml's own default). The spec calls the
output pretty-printed unconditionally, and reading 2 silently produces
non-pretty output for the most common inline test fixture. For an input that is
already indented two spaces per level, both readings agree.

### Risk: 45
If the author calls `tostring(..., pretty_print=True)` on a normally parsed
tree, a fixture with four-space indentation would be expected to round-trip
with its original indentation rather than be re-indented to two spaces.

## T6: Trailing newline

### Spec Text
> ... then join results with each on a newline.

### Alternatives
1. Terminate the final line too, i.e. the stream ends with `\n`.
2. Emit a strict separator-join with no trailing newline.

### Choice
Reading 1. "Each on a newline" describes line-oriented output, and line-
oriented Unix output is newline-terminated; `print()` is also the path of least
resistance in any implementation.

### Risk: 20
The author would have to have used `sys.stdout.write` with a bare `join` for
reading 2 to hold.

## T7: Node sets mixing elements and non-elements

### Spec Text
> Text/attribute results: ...
> XML node results: pretty-print serialized XML; when multiple XML nodes
> match, output only the first node.

### Alternatives
1. The first result decides the mode: an element first result means XML
   serialization (first node only), anything else means text rendering.
2. Partition the results and render each kind in its own way.

### Choice
Reading 1. The spec describes two mutually exclusive output shapes rather than
a mixture, and "output only the first node" already shows that extra results
are discarded in the XML case.

### Risk: 20
A union query mixing elements and attributes is an unusual fixture; if the
author scans for the first element instead of inspecting the first result, an
attribute-then-element union would still print XML there but text here.

## T8: Empty-string scalar results

### Spec Text
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. `string(//missing)` yields `""`, which after normalization is empty and is
   therefore treated as a no-match: nothing is written.
2. It is one result that happens to be empty, so a single blank line is
   written.

### Choice
Reading 1, consistent with T4: nothing printable means nothing printed.

### Risk: 30
An implementation that prints `"\n".join(results)` unconditionally emits a
lone newline here.

## T9: Precedence when both the input and the query are bad

### Spec Text
> Invalid XPath: stderr message, exit code `1` ...
> Malformed/empty XML input: stderr message, exit code `1` ...

### Alternatives
1. Report the parse failure, since the document must be parsed before the
   query can be evaluated.
2. Validate the query first and report the XPath failure.

### Choice
Reading 1. Both paths exit 1, so only the message text differs, and parsing is
the natural first stage of the pipeline.

### Risk: 10
Only reachable if a fixture supplies malformed XML *and* an invalid query while
asserting on the message keyword.

## T10: What "direct text" means for `::text` / `--text`

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

and

> `-t`, `--text`: direct text extraction from matched elements.

### Alternatives
1. Direct text is the element's direct child text nodes, each one a result of
   its own, so `<p>Hello <b>bold</b> world</p>` yields the two lines `Hello`
   and `world`.
2. Direct text is those same nodes concatenated into one result per element, so
   the same element yields the single line `Hello world`.
3. Direct text is only the text before the first child element (lxml's
   `element.text`), so the same element yields just `Hello`.

### Choice
Reading 1. The `selector::text` / `selector ::text` pair is lifted from
Scrapy, where `::text` translates to the XPath step `/text()` and the
descendant form to `descendant-or-self::text()` — both producing one result per
text node. The Text Extraction section then says to "strip each result", which
only has a per-node meaning if results *are* text nodes, and the existing
renderer already puts one stripped result per line. The parenthetical on the
descendant form reads as a warning that one element can explode into many
lines, not as the only place where per-node results occur.

### Risk: 30
If the author joins each element's direct text instead, a mixed-content fixture
such as `<p>Hello <b>bold</b> world</p>` is expected to print `Hello world` on
one line rather than `Hello` and `world` on two.

## T11: Whether CSS node output is still limited to the first node

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

and, from the previous spec:

> XML node results: pretty-print serialized XML; when multiple XML nodes
> match, output only the first node.

### Alternatives
1. CSS mode feeds the same XML node renderer as XPath mode, so the first
   matching element is printed and the rest discarded.
2. CSS mode is a new output path that prints every matching element.

### Choice
Reading 1. The bullet names the existing "XML node output" rather than
describing a new one, and nothing in this spec repeals the first-node rule. A
CSS selector is also far more likely than an XPath to match many elements, so
printing them all would be the bigger behavioural change to leave implicit.

### Risk: 35
The author may well serialize every match in CSS mode, in which case
`--css p` over a document with two paragraphs is expected to print both.

## T12: How "query already extracts text" is detected

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Decide from the result: text extraction only applies to a node set of
   elements, so a query that yields text nodes, attributes or a scalar is left
   untouched whatever the flags say.
2. Decide from the query string: search it for the literal `text()` or
   `::text` and skip extraction when either appears.

### Choice
Reading 1. It is what the sentence describes in every case that matters, and it
does not misfire on a query that merely *mentions* `text()` in a predicate:
`--text '//p[text()="x"]'` still extracts text from the matched `<p>` elements
under reading 1, but would silently print the elements as XML under reading 2.

### Risk: 15
Only separates the two readings when a query uses `text()` somewhere other than
its final step; the author's likeliest fixture (`--text '//p/text()'`) behaves
identically either way.

## T13: Comma lists that mix `::text` with plain selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. `p::text, span` is invalid too: "all selectors use the same `::text` mode"
   is not satisfied when one selector has no `::text` mode at all.
2. Only direct-vs-descendant is rejected; a selector without `::text` inherits
   the mode of the ones that have it.

### Choice
Reading 1, which also falls out of the obvious implementation — collect each
selector's mode into a set and reject anything but a single entry, with "no
`::text`" being one of the values.

### Risk: 25
An author who compares only the two `::text` modes and ignores plain selectors
would let `p::text, span` through, extracting direct text from both.

## T14: Whether the text flags work outside CSS mode

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements.
> `--text-all`: descendant text extraction from matched elements.

### Alternatives
1. The flags are general output modifiers and apply to XPath queries as well,
   so `-t '//p'` prints the paragraphs' text.
2. They are CSS companions and only mean anything alongside `--css`.

### Choice
Reading 1. The CLI section lists the three flags independently and neither text
flag is described in terms of `--css`; the Flag Rules section likewise talks
about `text()` — an XPath construct — when explaining when the flags go quiet.

### Risk: 10
Reading 2 would require the author to reject or ignore `-t` without `--css`,
which nothing in the spec asks for.

## T15: Whitespace-only text nodes in descendant extraction

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

and

> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. A node that is empty after stripping contributes nothing, so an indented
   document does not produce a run of blank lines.
2. Every descendant text node produces a line, blank ones included.

### Choice
Reading 1, the same rule already applied to `//text()` in T4 — the two spec
sections prescribe identical normalization, so they should not disagree.

### Risk: 35
Inherited from T4: an author who joins the normalized results without filtering
expects `--css 'div ::text'` over an indented document to emit blank lines
between the real ones.

## T16: Whether descendant extraction includes the element's own text

### Spec Text
> `selector ::text` returns all descendant text nodes

### Alternatives
1. Every text node in the element's subtree, the element's own direct children
   included (`descendant-or-self::text()`).
2. Only text nodes strictly below a child element, excluding the direct ones
   that `::text` would have returned.

### Choice
Reading 1. "All descendant text nodes" is the whole subtree, and reading 2
would make `--text-all` lose text that plain `--text` keeps, so no single flag
would give the full text of a mixed-content element.

### Risk: 15
Reading 2 is an unnatural implementation; the risk is that a fixture pins the
exact line list for a mixed-content element and the author's `.//text()`
happens to be anchored differently.

## T17: What an invalid CSS selector message says

### Spec Text
> Invalid CSS selector: stderr message, exit code `1`.

### Alternatives
1. The message should name the failing stage the way the XPath and XML errors
   do, even though this spec — unlike the previous one — names no keyword.
2. Any non-empty stderr satisfies the requirement.

### Choice
Reading 1. The message mentions both `css` and `selector`, together with the
offending selector text, so a test grepping for either word passes.

### Risk: 15
Only bites if the author greps for a word this message omits, such as
`invalid`, which is in fact present, or the pseudo-element name.

## T18: Result order for comma-separated selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.

### Alternatives
1. One selector list, so matches come back in document order regardless of the
   order the selectors were written in.
2. Each selector is evaluated in turn and its matches appended, so
   `span, p` lists the spans before the paragraphs.

### Choice
Reading 1. A CSS selector list denotes a single set of elements, and
translating the list to one XPath union is what any CSS-to-XPath library does.

### Risk: 12
Only observable when the written order disagrees with document order; the
author would have to loop over the selectors themselves to get reading 2.

## T19: Tag name for array entries below the top level

### Spec Text
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.

and

> Every converted element except `<root>` carries `type` in:
> `str`, `int`, `float`, `bool`, `dict`, `list`, `null`.

### Alternatives
1. `<item>` is the tag for every array entry at any depth, so
   `{"xs": [1, 2]}` becomes `<xs type="list"><item type="int">1</item>...`.
2. Only a top-level array's entries are named `<item>`; a nested array names
   its entries after something else, such as the key that holds the array.

### Choice
Reading 1. The `type` list includes `list` as a value an ordinary element can
carry, so nested arrays are clearly expected, and the spec gives no second
naming rule for them. Reusing `<item>` everywhere is also the only scheme that
works for an array nested directly inside another array, which has no key to
borrow a name from.

### Risk: 10
Reading 2 would require a naming rule the spec never states; the author almost
certainly emits `<item>` at every depth.

## T20: The `type` of a JSON number written with a fractional part

### Spec Text
> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

and

> Every converted element except `<root>` carries `type` in:
> `str`, `int`, `float`, `bool`, `dict`, `list`, `null`.

### Alternatives
1. `type` names the decoded JSON number's kind, so `1` is `int` and `1.0` is
   `float` even though both render as the text `1`.
2. `type` follows the rendered text, so `1.0` — which prints as `1` — is
   reported as `int`, and `float` is reserved for numbers that keep a
   fractional part.

### Choice
Reading 1. The attribute describes the value, not its rendering; the seven
names are `str`/`int`/`float`/`bool`/`dict`/`list` plus `null`, which are
exactly Python's own type names with `NoneType` renamed, so the natural
implementation reads the type of the decoded value rather than of its text.

### Risk: 15
The author most likely reports `float` for `1.0` as well; reading 2 would only
show up if they normalized integral floats to `int` before choosing the type.

## T21: What happens to input that looks like JSON but does not parse

### Spec Text
> Input that fails JSON detection is parsed as XML/HTML.

### Alternatives
1. Detection is one attempt to decode the whole input as a JSON object or
   array. Anything that fails — a truncated object, trailing garbage, a
   top-level primitive — is handed to the XML parser, so the error the user
   sees is the `xml`/`parse` one.
2. Detection sniffs the first non-space byte for `{` or `[` and, once it has
   committed, reports a JSON syntax error for input that does not decode.

### Choice
Reading 1. The spec makes failed detection fall back to XML without carving
out an exception for input that merely starts like JSON, and it names only one
JSON-specific error — the invalid-key one.

### Risk: 20
Both readings exit 1; they differ only in the message, and only for input such
as `{"a": }`. An author who sniffs the first character would expect a JSON
syntax message there.

## T22: Minimal string form for numbers outside plain decimal range

### Spec Text
> numbers as minimal string form.
> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

### Alternatives
1. Minimal form is Python's shortest round-trip repr, with an integral float
   collapsed to its integer form. `1e-7` therefore prints as `1e-07` and
   `1e30` as its full 31-digit integer expansion.
2. Minimal form is always positional decimal, so `1e-7` prints as
   `0.0000001` and exponent notation never appears.

### Choice
Reading 1. `0.00012` is already exactly what `repr` produces (Python switches
to exponent notation only below `1e-4`), and `1.0 -> "1"` is the one deviation
the spec spells out. Reimplementing decimal expansion would be a rule the spec
never hints at.

### Risk: 30
All four worked examples agree under both readings. If the author keeps `repr`
without collapsing integral floats to `int`, a large magnitude such as `1e30`
prints as `1e+30` there and as `1000000000000000019884624838656` here.

## T23: Which keys count as invalid XML element names

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1`.

### Alternatives
1. The XML `Name` production without the colon: a key must start with a
   letter or `_` and may then contain letters, digits, `-`, `.` and the
   combining ranges. `""`, `"a b"`, `"1a"` and `"a:b"` are all invalid.
2. The full `Name` production, which does allow `:`, so `"a:b"` is accepted
   and becomes a prefixed element name.

### Choice
Reading 1. A colon in an XML element name introduces a namespace prefix, and a
JSON key carries no declaration to bind one; lxml rejects such a tag outright.
Treating `a:b` as invalid input is both the stricter and the buildable reading.

### Risk: 15
Any implementation that builds the tree with lxml gets reading 1 for free, so
reading 2 would take deliberate namespace work.

## T24: Empty objects and arrays

### Spec Text
> Auto-detect stdin as JSON object/array
> Wrap converted documents in `<root>`.

### Alternatives
1. `{}` and `[]` are objects and arrays like any other, so both convert to an
   empty `<root/>` that a query can match.
2. They carry no content and are rejected, falling back to XML parsing and
   thus to a parse error.

### Choice
Reading 1. The detection rule is about the top-level JSON kind, not about
whether the document has members, and an empty `<root/>` is a perfectly good
document for a query that finds nothing in it.

### Risk: 8
Rejecting an empty object would need an extra check the spec never asks for.

## T25: Duplicate keys in one JSON object

### Spec Text
> Preserve JSON key order in converted XML.

### Alternatives
1. Decode with the standard JSON rules, where a later duplicate replaces the
   earlier one, so `{"a": 1, "a": 2}` yields a single `<a type="int">2</a>`.
2. Keep every pair, so the same input yields two `<a>` elements.

### Choice
Reading 1. Python dictionaries have preserved insertion order since 3.7, so
"preserve key order" needs no special decoding hook, and a plain decode is what
any implementation reaches for first.

### Risk: 20
An author who reached for `object_pairs_hook` in order to guarantee key order
would keep both pairs and expect two elements.

## T26: Serialization of an element with no text

### Spec Text
> Primitive values map to element text: ... null as empty.

### Alternatives
1. `null` leaves the element without text, so it serializes self-closing as
   `<k type="null"/>`, while an empty JSON string is text that happens to be
   empty and serializes as `<k type="str"></k>`.
2. Both are written as the empty string, so both serialize the same way.

### Choice
Reading 1. "null as empty" says the element has no text to show; an empty
string is a `str` value that was already empty, and lxml distinguishes the two
in output without any extra effort.

### Risk: 25
Only observable when a fixture serializes a `null` or `""` element. An author
who assigns `""` for both gets `<k type="null"></k>`.
