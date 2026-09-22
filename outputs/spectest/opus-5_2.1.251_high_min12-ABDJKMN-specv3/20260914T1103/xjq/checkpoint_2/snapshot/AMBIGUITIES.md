# Ambiguities

Numbered record of under-specified points in the spec, the interpretations
considered, the reading chosen for this implementation, and the risk that the
spec's author's own implementation (and therefore the hidden tests) reads it
differently.

---

## T1. What `[OPTIONS]` means

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. The CLI must accept some concrete set of flags (e.g. `--raw`, `--pretty`,
   `--html`), which the spec simply forgot to enumerate.
2. `[OPTIONS]` is only usage-line boilerplate: the tool needs no behavioural
   flags, just the standard `-h/--help` that any argument parser provides.

### Choice
Interpretation 2. No behaviour in the "Behavior"/"Output"/"Errors" sections is
conditional on a flag, so there is no flag whose semantics could be tested.
`argparse` is used, which yields `-h/--help` for free and keeps the exact usage
string `xjq.py [OPTIONS] QUERY [INFILE]` shape. Unknown options are rejected by
argparse (exit code 2), which no spec clause covers.

### Risk: 10
Author's most likely alternative reading: an unspecified flag such as `--html`
or `-f/--file` exists and is exercised by a hidden test.

---

## T2. How tolerant the parser must be ("XML/HTML") vs. the hard requirement to fail on malformed XML

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. Always parse in recovering mode (`XMLParser(recover=True)` or an HTML
   parser), erroring only when nothing at all can be recovered. HTML-ish input
   such as `<br>` or `<meta>` then works, but classic malformed XML
   (`<a><b></a>`) is silently repaired and never triggers the exit-1 path.
2. Always parse strictly as XML. Every malformed document errors, but real HTML
   with void elements cannot be queried at all, contradicting "XML/HTML".
3. Strict XML first; only if the document *looks like HTML* (an
   `<!DOCTYPE html>` or an `<html ...>` tag) fall back to lxml's HTML parser.
   Anything else that fails strict parsing is a malformed-XML error.

### Choice
Interpretation 3. It is the only reading that satisfies both sentences at once:
well-formed XML and HTML documents are both queryable, while a broken XML
fragment (mismatched/unclosed tags, plain text, empty input) still produces the
required `xml`/`parse` error and exit code 1. Case sensitivity is preserved on
the XML path (lxml's `XMLParser` never folds case), which is what the
"case-sensitive element matching" clause is guarding: an HTML parser would
lowercase `<Book>` and break `//Book`. The HTML fallback only engages for
documents that are unambiguously HTML, where tag names are conventionally
lowercase anyway.

### Risk: 30
Author's most likely alternative reading: strict XML parsing only
(interpretation 2), with HTML "support" meaning nothing more than that
well-formed XHTML happens to parse.

---

## T3. Serializing a non-element XPath result that is a number

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.

> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. Print `str()` of the Python value lxml returns. XPath 1.0 numbers are
   doubles, so `count(//item)` yields the float `3.0` and prints `3.0`.
2. Print the XPath 1.0 *string-value* of the number, which renders an integral
   double without a fractional part: `3`.

### Choice
Interpretation 2. The spec pins evaluation to XPath 1.0, whose `string()`
conversion of a number is defined to omit the decimal point and trailing zeros
for integral values, and every comparable CLI (`xmllint --xpath`, `xidel`)
prints `3`. Non-integral numbers are printed with `repr`-style formatting
(`1.5`), and `NaN`/infinities as `NaN`/`Infinity`/`-Infinity` per XPath 1.0.

### Risk: 40
Author's most likely alternative reading: a bare `str(result)` on lxml's float,
printing `3.0` for `count(...)`.

---

## T4. Serializing a boolean XPath result

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

> Exit code `0` on successful execution, including zero matches.

### Alternatives
1. `str(True)` → `True` / `False` (whatever Python prints).
2. XPath 1.0 string-value of a boolean → `true` / `false`.
3. Treat a false boolean as "no match" and print nothing.

### Choice
Interpretation 2, for the same reason as T3: the spec names XPath 1.0 as the
evaluation semantics, and its string conversion of booleans is lowercase
`true`/`false`. Interpretation 3 is rejected because a boolean result is a
successful evaluation, not an empty node-set — `false()` is an answer, not an
absence.

### Risk: 45
Author's most likely alternative reading: Python's `str()`, printing
`True`/`False`.

---

## T5. Results that are empty after stripping and collapsing

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline. No trailing newline.

> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Keep every result positionally, so a whitespace-only text node (very common:
   `//root/text()` over an indented document) contributes an empty line to the
   output.
2. Drop results that are empty after cleaning, so only substantive text is
   printed and a query matching nothing but indentation prints nothing.

### Choice
Interpretation 2. "strip each result, collapse internal whitespace runs" is
plainly aimed at making indentation noise disappear; emitting the blank lines
that survive that cleaning would defeat it, and the surrounding rules (no
trailing newline, nothing at all on no match) show the spec is optimizing for
clean, greppable output.

### Risk: 30
Author's most likely alternative reading: a straight
`"\n".join(clean(r) for r in results)` that preserves blank lines for
whitespace-only nodes.

---

## T6. Trailing newline on XML node output

### Spec Text
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

> Text/attribute results: ... No trailing newline.

### Alternatives
1. "No trailing newline" is scoped to the text/attribute bullet; XML output
   keeps the trailing newline that pretty-printing naturally produces.
2. "No trailing newline" is the tool's general output discipline and applies to
   XML output too.

### Choice
Interpretation 2 — stdout ends exactly at the closing `>` of the serialized
node. This is safe under the comparison style either implementation invites
(`stdout.strip() == expected`), and it keeps a single consistent rule for every
output form.

### Risk: 20
Author's most likely alternative reading: `print(etree.tostring(node,
pretty_print=True).decode())`, which leaves a trailing newline (possibly two).

---

## T7. How "pretty-print" re-indents a node that already carries whitespace

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Serialize verbatim with `pretty_print=True`, which is a no-op whenever the
   source document already has text nodes between elements — the output keeps
   the input's original (possibly ugly or single-line) formatting.
2. Normalize whitespace-only text first (`etree.indent`, or
   `remove_blank_text=True` at parse time) so the result is genuinely
   re-indented with a fixed indent regardless of the input's formatting.

### Choice
Interpretation 2, with a two-space indent, applied to a copy of the node so the
source tree is untouched. "Pretty-print" is a promise about the *output*, and
interpretation 1 breaks that promise on the most common input of all: XML that
arrives on one line. Only whitespace-only text/tails are rewritten, so mixed
content (`<p>a <b>b</b> c</p>`) is preserved exactly. The node's tail text is
excluded from the serialization.

### Risk: 25
Author's most likely alternative reading: plain `tostring(node,
pretty_print=True)` with no re-indentation, which for an already-indented input
document is byte-identical to this choice, and differs only for single-line
input.

---

## T8. A result list mixing element nodes and strings

### Spec Text
> Text/attribute results: ... join results with each on a newline.

> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. Decide per result: pretty-print elements, clean strings, and interleave them.
2. Decide once for the whole result set, from its first member: if it is a node,
   take the "XML node results" branch (first node only); otherwise take the
   text branch.

### Choice
Interpretation 2. The spec presents the two output modes as mutually exclusive
branches keyed on the kind of result, and the "output only the first node" rule
already establishes that a node-set is summarized rather than enumerated. Mixed
sets only arise from unusual unions like `//a | //b/text()`.

### Risk: 15
Author's most likely alternative reading: per-result dispatch
(interpretation 1), which agrees with this choice on every homogeneous result
set and differs only on union queries.

---

## T9. Whether `INFILE` is validated

### Spec Text
> `INFILE`: accepted positional argument but not used.
> Input source: stdin.

### Alternatives
1. Accept the argument and ignore it entirely — a nonexistent path is fine.
2. Accept it, but still stat/open it and error if it is unreadable.

### Choice
Interpretation 1. "not used" is explicit and unqualified; opening a file the
spec says is unused would introduce an error mode no clause in "Errors"
describes.

### Risk: 5
Author's most likely alternative reading: identical; the only divergence would
be a hidden test asserting an error for a missing INFILE, which "not used"
contradicts.

---

## T10. Comment and processing-instruction results

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Only elements count as "XML node results"; comments/PIs fall to the text
   branch and print their string value.
2. Any serializable node (element, comment, PI) takes the XML branch.

### Choice
Interpretation 2. `comment()` and `processing-instruction()` are node tests in
XPath 1.0 and lxml returns real node objects for them; serializing them keeps
`<!-- ... -->` and `<?target ...?>` intact, which is what "serialized XML"
means for those node types.

### Risk: 20
Author's most likely alternative reading: an `isinstance(r, etree._Element)`
check, which excludes comments/PIs (they are `_Comment`/`_ProcessingInstruction`
— both *are* `_Element` subclasses in lxml, so this actually agrees) but a
tag-based check like `hasattr(r, "tag") and isinstance(r.tag, str)` would route
them to the text branch.

---

## T11. Line granularity of `selector::text` (direct mode)

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

> `-t`, `--text`: direct text extraction from matched elements, one per element.

### Alternatives
1. One line per *text node*: `p::text` over `<p>a <b>b</b> c</p>` has two direct
   text nodes (`"a "` and `" c"`) and prints two lines, `a` and `c`. This is the
   natural reading if `::text` is implemented as XPath `<sel>/text()`.
2. One line per *matched element*: the element's direct text nodes are
   concatenated first, so `<p>a <b>b</b> c</p>` prints the single line `a c`.

### Choice
Interpretation 2. The spec attaches the parenthetical "(one text node per line)"
only to the *descendant* form; contrasting it with the bare "returns direct
text" is only meaningful if the direct form is not per-text-node. The `--text`
bullet independently pins direct extraction to "one per element", and the two
spellings of the same operation should agree — `--css -t 'p'` and
`--css 'p::text'` must not disagree about line counts.

### Risk: 35
Author's most likely alternative reading: `::text` compiled to XPath
`<sel>/text()` and printed per text node, so `p::text` over mixed content
yields two lines.

---

## T12. What "all descendant text nodes" means for `selector ::text`

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. Literal CSS: `p ::text` parses as `p *::text`, i.e. the *direct* text of
   every descendant *element* of `p` — one line per descendant element, and
   `p`'s own text nodes excluded.
2. Every text node in the matched element's subtree, `.//text()`, including
   `p`'s own direct text children — one line per text node.

### Choice
Interpretation 2. The spec says "all descendant text nodes", not "descendant
elements' text", and the parenthetical "(one text node per line)" only makes
sense if the unit being emitted is a text node. Reading 1 also produces the
surprising result that `p ::text` loses text that `p::text` keeps, whereas
reading 2 makes the descendant form a strict superset of the direct form. The
matched element's own text children are included: they are text nodes in its
subtree, and `.//text()` (XPath `descendant-or-self::node()/child::text()`) is
the obvious implementation. The element's *tail* text is not included.

### Risk: 40
Author's most likely alternative reading: the same `.//text()` set but
excluding the matched element's own direct text nodes (a strict "descendant,
not self" reading), which differs on `<p>own<b>child</b></p>`.

---

## T13. Comma-separated branches where only *some* carry `::text`

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.

> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. Only direct-vs-descendant conflicts are errors. `title::text, author` is
   legal, and the implementation has to decide what to do with a result set
   that is half text and half elements.
2. "all selectors use the same `::text` mode" is read with three modes —
   direct, descendant, and none — so any disagreement, including
   `title::text, author`, is the invalid case.

### Choice
Interpretation 2. The support clause is phrased positively ("supported *when*
all selectors use the same mode"), which makes disagreement the unsupported
case in general; the following sentence names the direct/descendant conflict as
the obvious instance rather than as the only one. It is also the only reading
with a defined output: reading 1 would have to silently pick text or XML for a
mixed result set, and the existing Output rules give no basis for choosing.

### Risk: 35
Author's most likely alternative reading: only direct-vs-descendant is checked,
and `title::text, author` is accepted, falling back to whichever output branch
the first result happens to select.

---

## T14. How `--text-all` joins a subtree's text nodes

### Spec Text
> `--text-all`: descendant text extraction from matched elements, one per
> element.

> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. Concatenate the subtree's text nodes with no separator — the XPath 1.0
   string-value of the element — then strip and collapse.
2. Join the text nodes with a single space (or a newline) before collapsing, so
   adjacent elements never run together.

### Choice
Interpretation 1. "descendant text extraction ... one per element" describes
the element's text content, and the standard meaning of an element's text
content in both XPath (`string(.)`) and lxml (`"".join(el.itertext())`) is bare
concatenation. For indented documents the two readings agree, because the
indentation whitespace between children survives concatenation and then
collapses to the single space that reading 2 would have inserted. They differ
only for markup with no whitespace between children, e.g. `<b>a</b><b>c</b>`,
where this choice yields `ac`.

### Risk: 20
Author's most likely alternative reading: `" ".join(...)`, yielding `a c` for
whitespace-free sibling markup.

---

## T15. Whether CSS node output prints every match or only the first

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

> [earlier spec] XML node results: pretty-print serialized XML; when multiple
> XML nodes match, output only the first node.

### Alternatives
1. CSS mode reuses the established XML-node output rule verbatim, so a CSS
   selector matching many elements prints only the first.
2. "XML node output" in CSS mode means all matches, serialized one after
   another — CSS selectors routinely match many elements, and the text bullets
   right above it are explicitly multi-match.

### Choice
Interpretation 1. The sentence says "return XML node output", naming the
already-defined output mode rather than redefining it; the first-node rule is
part of that definition and nothing here overrides it. The multi-match
behaviour the spec does want from CSS mode is supplied by `::text`/`--text`,
which is precisely why those exist.

### Risk: 25
Author's most likely alternative reading: every matched node serialized, joined
by newlines.

---

## T16. Which CSS dialect/translator applies, and case sensitivity of CSS names

### Spec Text
> `--css`: interpret `QUERY` as CSS selector.

> [earlier spec] Parse stdin as XML/HTML using case-sensitive element matching.

### Alternatives
1. Always translate with an HTML-flavoured translator, which lower-cases
   element names in the selector and enables HTML-only pseudo-classes. `--css
   'Book'` would then match `<book>` but never `<Book>`.
2. Always translate generically (XML rules): element names keep their case, and
   HTML-only pseudo-classes such as `:checked` are rejected.
3. Pick the translator from how the document actually parsed: generic for the
   XML path, HTML for the HTML-parser fallback.

### Choice
Interpretation 3. The earlier "case-sensitive element matching" requirement
must keep holding for XML documents, which rules out 1; but for a document that
only parsed because it is HTML, HTML selector semantics are what a user typing
CSS expects, which 2 would deny. Since the HTML fallback only engages for
documents announcing themselves as HTML (see T2), tag case is already
normalised there and nothing is lost.

### Risk: 20
Author's most likely alternative reading: one translator unconditionally —
most likely `cssselect.GenericTranslator` (interpretation 2), which differs
only for HTML documents queried with uppercase names or HTML-only
pseudo-classes.

---

## T17. Extracted text that is empty after stripping and collapsing

### Spec Text
> Strip each result and collapse internal whitespace runs to single spaces.

> Multi-match text output joins lines with `\n`.

### Alternatives
1. Keep one line per matched element/text node regardless, so
   `--css 'book::text'` over an indented document prints a blank line for each
   `<book>` whose direct text is only indentation.
2. Drop results that are empty after cleaning, as already chosen for XPath text
   results in T5.

### Choice
Interpretation 2, for continuity with T5 — the cleaning rule is worded
identically to the earlier Output rule, so it should behave identically. It
also matters much more here: `::text` and `--text-all` are aimed squarely at
indented documents, where reading 1 would emit a blank line for nearly every
container element and swamp the real output.

### Risk: 30
Author's most likely alternative reading: positional output that keeps blank
lines, so the number of printed lines always equals the number of matches.

---

## T18. How "query already extracts text" is detected

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Syntactic: test the raw QUERY string for the substrings `text()` / `::text`.
   `//a[contains(text(),'x')]` then counts as "already extracts text", so `-t`
   is suppressed and the matched `<a>` element is printed as XML.
2. Structural: the flags only transform *element* results, so any query whose
   result is already strings (`text()` steps, `@attr`, `string(...)`, `::text`)
   is untouched by construction.

### Choice
Interpretation 2. The clause explains *why* the flags are no-ops — the query
"already extracts text" — rather than prescribing a string search, and reading 2
delivers that outcome for every query the spec names while also covering
attribute and `string()` results, which are text too and which reading 1 would
re-process into nothing (elements is what extraction needs). The two readings
agree on every query that genuinely extracts text; they differ only when
`text()` appears inside a predicate of an element-returning query.

### Risk: 25
Author's most likely alternative reading: the literal substring test, so
`-t "//a[contains(text(),'x')]"` prints XML rather than the element's text.

---

## T19. Where `::text` may appear in a selector

### Spec Text
> Define custom `::text` pseudo-element:
> `selector::text` returns direct text;

### Alternatives
1. `::text` is accepted anywhere a pseudo-element token parses and is simply
   detected wherever it occurs (e.g. `title::text > author`).
2. `::text` is only meaningful at the very end of a selector-list branch;
   anything else is an invalid CSS selector (exit code `1`).

### Choice
Interpretation 2. The spec always writes it as a suffix on a complete selector,
and real CSS forbids anything after a pseudo-element, so `a::text > b` is not a
valid selector under any reading. Rejecting it reuses the "Invalid CSS
selector" rule rather than inventing an unstated behaviour.

### Risk: 15
Author's most likely alternative reading: identical rejection, but arrived at
by letting the CSS parser reject the selector for its own reasons (which yields
the same exit code and a different message).

---

## T20. A bare `::text` with no selector before it

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. A missing selector is an invalid CSS selector, exit code `1`.
2. The universal selector is implied, so `::text` means `*::text` (direct text
   of every element) and ` ::text` means `* ::text`.

### Choice
Interpretation 2. CSS itself treats an omitted type selector as `*`, and the
two spec lines are written as `selector` + pseudo-element with no statement
that `selector` is mandatory. The result is still well defined under both
modes, so there is no reason to fail.

### Risk: 30
Author's most likely alternative reading: an empty base selector is passed
straight to the CSS parser and rejected, giving exit code `1`.
