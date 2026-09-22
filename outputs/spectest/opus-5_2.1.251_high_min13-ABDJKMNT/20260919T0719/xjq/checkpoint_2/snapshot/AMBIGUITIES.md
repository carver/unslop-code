# Ambiguities

Interpretation decisions taken while implementing the "XPath Querying of XML
from Stdin" and "CSS Selectors and Text Extraction" specs. Each entry quotes
the spec, lists the readings that would change observable behaviour, and
records the chosen reading.

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
