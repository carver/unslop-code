# Ambiguities

Numbered record of under-specified points in the spec, the interpretation chosen,
and the risk that the spec author's own implementation reads them differently.

---

## T1 — "XML/HTML" input vs. hard error on malformed input

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. Parse strictly as XML (well-formedness enforced). "XML/HTML" just means "markup
   input" — HTML documents that happen to be well-formed XML (XHTML-ish) parse fine.
2. Try XML, and on failure fall back to a forgiving HTML parser (`lxml.etree.HTMLParser`
   or `recover=True`). Then almost nothing is "malformed" except empty input.

### Choice
Alternative 1: a strict, non-recovering XML parser. It is the only reading that keeps
both other requirements true at once: an HTML/recovering parser lower-cases element
names (destroying "case-sensitive element matching") and would swallow malformed input
that the Errors section requires to exit `1`.

### Risk: 25
Most likely alternative preferred by the author: an HTML fallback for non-well-formed
input, with only empty/unparseable-by-both input erroring.

---

## T2 — Which results count as "XML node results" vs "Text/attribute results"

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. Element (and comment/PI) nodes → XML mode; strings (from `text()`, `@attr`,
   `string()`, `name()`, …), numbers and booleans → text mode.
2. Only decide by whether the XPath returned a nodeset at all, serializing text nodes
   too (e.g. as `<text/>`-ish or raw), which XPath cannot really express.

### Choice
Alternative 1, dispatching on the type of the results: `lxml` returns `_Element` for
element/comment/PI nodes and (smart) `str` for text nodes and attribute values, which
maps exactly onto the spec's two named categories.

### Risk: 5
Most likely alternative preferred by the author: identical; this is the natural `lxml`
type split.

---

## T3 — Mixed result sets (elements *and* strings from one query)

### Spec Text
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. If the first result in document order is an element, use XML mode (print that
   element); otherwise text mode.
2. If *any* result is an element, use XML mode.
3. Emit each result in its own mode, interleaved.

### Choice
Alternative 1. `//a | //b/text()` is exotic; taking the mode from the first result keeps
the two output modes mutually exclusive (as the spec presents them) and makes the
"first node" rule literally about the first matched node.

### Risk: 10
Most likely alternative preferred by the author: unspecified/untested; if tested, "any
element ⇒ XML mode".

---

## T4 — Formatting of numeric XPath results (`count(...)`, `1+1`)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.

### Alternatives
1. Format per XPath 1.0 `string(number)`: integral values without a decimal point →
   `count(//item)` prints `3`.
2. Pass the Python `float` through `str()` → `3.0`.

### Choice
Alternative 1. XPath 1.0 defines the string value of the number 3 as `"3"`, and a
hand-written fixture for `count(//item)` reads `3`. The `.0` is a Python artifact, not
an XPath one.

### Risk: 40
Most likely alternative preferred by the author: `str(float)` giving `3.0`, if their
implementation stringifies results generically before stripping.

---

## T5 — Formatting of boolean XPath results (`//a and //b`, `true()`)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. XPath 1.0 lexical form: `true` / `false`.
2. Python `str(bool)`: `True` / `False`.

### Choice
Alternative 1, for the same reason as T4: XPath 1.0's own string conversion.

### Risk: 45
Most likely alternative preferred by the author: `True`/`False` from a generic
`str()` of the result.

---

## T6 — Results that are empty after stripping

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Keep them: a whitespace-only text node or `id=""` attribute is a match, so it
   contributes an (empty) line.
2. Drop empty results entirely, so a query matching only blank text prints nothing.

### Choice
Alternative 1. The spec's pipeline is strip → collapse → join with no filtering step,
and "write nothing" is scoped to *no-match*, not to matches whose value is empty.

### Risk: 30
Most likely alternative preferred by the author: skipping blank results, since many
implementations guard with `if not value: continue`.

---

## T7 — Exact pretty-print layout for XML node results

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Re-indent the subtree (2-space indent per level, one element per line) and serialize
   without XML declaration and without the node's tail text.
2. Serialize with `pretty_print=True` only, which in `lxml` leaves already-present
   whitespace untouched and therefore often produces no indentation at all.
3. Include an XML declaration and/or the trailing tail text.

### Choice
Alternative 1: `etree.indent(copy, space="  ")` then `tostring(pretty_print=True,
with_tail=False)`. That is the only option that actually pretty-prints input which
arrived on a single line, which is what "pretty-print" asks for. Mixed content (an
element with non-whitespace text) is left alone so no text is invented or lost.

### Risk: 35
Most likely alternative preferred by the author: plain `tostring(pretty_print=True)`
with `lxml`'s default 2-space indent — identical output for compact input parsed with
`remove_blank_text=True`, but differing on input that already contains newlines/indent.

---

## T8 — Namespaced documents

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

### Alternatives
1. Plain XPath 1.0 semantics: an unprefixed name matches only no-namespace elements,
   so `//book` finds nothing in a document with a default namespace (exit `0`, no output).
2. Strip namespaces from the tree, or auto-register the document's prefixes, so
   unprefixed queries match namespaced elements.

### Choice
Alternative 1. The spec asks for XPath 1.0 and says nothing about namespace
convenience; silently rewriting the document would be a surprising deviation. Explicit
prefixes are still usable via `local-name()`.

### Risk: 15
Most likely alternative preferred by the author: identical (default `lxml` behaviour).

---

## T9 — What `[OPTIONS]` are, and the `INFILE` argument

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`
> `INFILE`: accepted positional argument but not used.

### Alternatives
1. No functional options beyond `-h/--help`; `INFILE` is parsed and discarded, never
   opened, never validated — a non-existent path is fine.
2. `INFILE` is read when present, with stdin as fallback.

### Choice
Alternative 1 — the spec says INFILE is "not used" and "Input source: stdin",
unconditionally. The argument exists only so the invocation is accepted.

### Risk: 5
Most likely alternative preferred by the author: identical.

> **Update (CSS/text spec):** partially resolved. `[OPTIONS]` is now populated by
> `--css`, `-t`/`--text` and `--text-all`. The `INFILE` half of this entry stands
> unchanged: it is still accepted and still never read.

> **Update (file/first/compact spec):** fully resolved, and the choice above is
> reversed by the new spec. "`INFILE` takes precedence over stdin when both are
> present" makes alternative 2 the rule: `INFILE` is opened and read when given,
> stdin is the fallback. `[OPTIONS]` also gains `-f`/`--first` and `-c`/`--compact`.
> See [[T27]] for how the precedence is implemented and [[T28]] for the extra
> positional arguments.

---

## T10 — Trailing newline on output

### Spec Text
> then join results with each on a newline

### Alternatives
1. Each result line is terminated by `\n`, so output ends with a newline.
2. Results are joined by `\n` with no trailing newline.

### Choice
Alternative 1 (i.e. `print` semantics) — "each on a newline" reads as line-oriented
output, and it is what a `print()`-based implementation produces. Tests compare
stripped output so both readings agree on content.

### Risk: 15
Most likely alternative preferred by the author: identical; a bare `"\n".join(...)`
passed to `print()` also yields a trailing newline.

> **Update (CSS/text spec):** re-raised but not resolved by "Multi-match text output
> joins lines with `\n`". That wording describes the separator between lines, not
> whether the last line is terminated; the choice above (always terminate) is kept,
> and it is what `print("\n".join(...))` produces.

---

## T11 — Do `--text` / `--text-all` work outside CSS mode?

### Spec Text
> - `--css`: interpret `QUERY` as CSS selector.
> - `-t`, `--text`: direct text extraction from matched elements.
> - `--text-all`: descendant text extraction from matched elements.

> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. `--text`/`--text-all` are general post-processors: they apply to whatever
   elements the query matched, in XPath mode as well as CSS mode.
2. They are only meaningful together with `--css`, and are ignored (or an error)
   for an XPath `QUERY`.

### Choice
Alternative 1. The three flags are listed as peers under "CLI Additions", not
nested under CSS Query Mode, and the Flag Rules explicitly name the XPath form
`text()` as one of the things that makes them a no-op — which only matters if
they are otherwise live in XPath mode. So `xjq.py -t '//title'` is the same as
`xjq.py '//title/text()'`.

### Risk: 15
Most likely alternative preferred by the author: identical; the `text()` mention
in Flag Rules is hard to explain under any other reading.

---

## T12 — What "direct text" is, and whether multiple text nodes are one result or many

### Spec Text
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

### Alternatives
1. `::text` is XPath `/text()` on the matched element: each *direct child text
   node* is its own result/line. For `<p>a<b>x</b>c</p>`, `p::text` gives two
   lines, `a` and `c`.
2. Direct text is the concatenation of the element's direct child text nodes into
   one result: a single line `a c` (or `ac`).
3. Direct text means "the element's text content" (i.e. all descendant text),
   making `::text` and ` ::text` differ only in line splitting.

### Choice
Alternative 1. The two forms are the CSS spelling of `/text()` and
`//text()`; this is also exactly what `cssselect`'s parse tree yields
(`selector::text` -> `.../text()`, `selector ::text` ->
`.../descendant-or-self::*/text()`), and it is the established `::text`
convention (Scrapy). The parenthetical "one text node per line" describes the
shared line-per-text-node rule; there is no wording anywhere that asks for
concatenation. `--text` / `--text-all` are implemented as the same two XPath
steps applied to matched elements.

### Risk: 25
Most likely alternative preferred by the author: #2 — concatenating an element's
direct child text nodes into a single line per matched element, if their
implementation reaches for `"".join(el.xpath("text()"))`.

---

## T13 — How "query already extracts text" is detected

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. Detect by *result type*: text extraction is applied only to element results,
   so a query that already returned strings (text nodes, attributes, `string()`,
   numbers, booleans) is untouched and the flags are automatically no-ops.
2. Detect by *query text*: if the literal substring `text()` or `::text` occurs
   anywhere in `QUERY`, suppress the flags.

### Choice
Alternative 1. It satisfies the stated rule for every query that really extracts
text, needs no fragile string matching, and does the sensible thing for a query
that merely *mentions* `text()` in a predicate: `-t '//item[text()="a"]'`
matches elements, so `-t` still extracts their text. Reading #2 would print the
XML node there, which contradicts "direct text extraction from matched
elements". Non-element results (attributes, comments, PIs, numbers, booleans)
pass through unchanged.

### Risk: 25
Most likely alternative preferred by the author: #2, a substring check on the
query; it differs only for queries that use `text()` inside a predicate while
returning elements.

---

## T14 — CSS node output when several elements match

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

Round-1 spec, referenced by the term "XML node output":
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. "XML node output" is a pointer to the existing XML-node rule in full,
   including "output only the first node".
2. CSS mode is a new output path that serializes *every* matched element.

### Choice
Alternative 1. The sentence names the existing output category rather than
redefining it, and only re-states the pretty-print half because that is the part
being promised for CSS. Keeping one rule for XML nodes also means
`--css 'item'` and `'//item'` agree.

### Risk: 30
Most likely alternative preferred by the author: #2 — printing all matched
nodes in CSS mode, on the theory that CSS selectors are collection-oriented.

> **Update (file/first/compact spec):** re-raised, not resolved. "`--first`
> applies across text, attribute, and XML-node results" can be read as implying
> that XML-node results are *not* first-only by default. The round-1 rule
> ("output only the first node") is explicit and is kept, so `--first` is a
> no-op for node results; see [[T34]].

---

## T15 — Text results that are empty after stripping (indentation whitespace)

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).
> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. Keep them. The pipeline is strip -> collapse -> join, with no filtering step,
   so a whitespace-only text node contributes an empty line. `div ::text` on an
   indented document yields blank lines between the real ones.
2. Drop results that are empty after stripping, so only non-blank text lines are
   printed.

### Choice
Alternative 1, for consistency with [[T6]] (the same strip/collapse pipeline in
round 1 was chosen to keep blank results) and because "all descendant text nodes
(one text node per line)" describes emitting every text node, not the non-blank
subset. Applying a filter here but not to an equivalent XPath `//text()` query
would make `--css 'div ::text'` and `'//div//text()'` disagree.

### Risk: 45
Most likely alternative preferred by the author: #2 — filtering out blank
results, which is the usual way `::text` extractors are written and is needed for
a clean fixture over a pretty-printed input document.

---

## T16 — Which cssselect translator (case sensitivity of CSS type selectors)

### Spec Text
> `--css`: interpret `QUERY` as CSS selector.

Round-1 spec:
> Parse stdin as XML/HTML using case-sensitive element matching.

### Alternatives
1. `cssselect.GenericTranslator` (XML semantics): type selectors are
   case-sensitive, so `--css 'Item'` matches `<Item>` and not `<item>`.
2. `cssselect.HTMLTranslator`: element names in the selector are lower-cased,
   plus HTML-specific `:checked`/`:link` handling.

### Choice
Alternative 1. The document is parsed as case-sensitive XML ([[T1]]), so a
lower-casing translator would make `--css` unable to reach any capitalised
element. `GenericTranslator` still handles `#id`, `.class`, attribute, `:nth-*`
and combinator selectors.

### Risk: 20
Most likely alternative preferred by the author: identical for lower-case
fixtures; `HTMLTranslator` only if they test a mixed-case document through
`--css`.

---

## T17 — Comma-separated selectors mixing `::text` with plain selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. There are three modes — direct `::text`, descendant ` ::text`, and no text
   extraction — and every comma-separated part must be in the same one. So
   `a::text, b` is invalid too.
2. Only direct-vs-descendant is checked; `a::text, b` is allowed and produces a
   mixed nodeset of strings and elements, resolved by the round-1 mixed-result
   rule ([[T3]]).

### Choice
Alternative 1. "all selectors use the same `::text` mode" is the general rule and
the following sentence is the concrete instance of breaking it; a query that is
half text and half nodes has no coherent output mode, which is exactly the
problem the rule exists to prevent. Both violations get the same stderr message
and exit code `1`.

### Risk: 35
Most likely alternative preferred by the author: #2 — validating only
direct-vs-descendant, because that is the case the spec spells out, and letting
`a::text, b` through to whatever their generic renderer does.

---

## T18 — Result order across comma-separated selectors

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.

### Alternatives
1. Document order over the union of all selectors (`a::text, b::text` is
   translated to one XPath union `... | ...`, which lxml returns in document
   order with duplicates removed).
2. Selector order: everything matched by the first selector, then the second.

### Choice
Alternative 1 — the standard CSS meaning of a selector list (a set of elements,
not a concatenation), and what `cssselect`'s own `css_to_xpath` produces by
joining the branches with `|`.

### Risk: 20
Most likely alternative preferred by the author: identical, since translating the
whole comma list through `cssselect` in one call is the path of least resistance.

---

## T19 — What "JSON detection" actually tests

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.

> Input that fails JSON detection is parsed as XML/HTML.

### Alternatives
1. Detection = a full `json.loads()` of the entire input that succeeds *and*
   yields a `dict` or `list`. Anything else (syntax error, trailing garbage,
   primitive result) is "failed detection" and goes to the XML parser.
2. Detection = a cheap sniff of the first non-whitespace byte (`{` or `[`). Once
   it looks like JSON, a JSON syntax error is a *JSON* error (stderr mentioning
   `json`, exit `1`) rather than a fallback to XML.

### Choice
Alternative 1. "Input that fails JSON detection is parsed as XML/HTML" only has
content if a malformed-but-JSON-shaped document can fail detection; under #2 such
input never reaches the XML parser. So `{oops}` is parsed as XML and produces the
round-1 XML parse error ([[T1]]), while `{"a":1}` is JSON. Empty containers `{}`
and `[]` parse to a `dict`/`list` and are therefore JSON (an empty `<root/>`),
not XML errors.

### Risk: 30
Most likely alternative preferred by the author: #2 for the *error message* —
sniffing `{`/`[` and reporting a json-flavoured error for `{oops}` instead of an
xml-flavoured one. The accept/reject decision is the same either way; only the
stderr wording and which term (`json` vs `xml`) appears differs.

---

## T20 — "minimal string form" for numbers outside the given examples

### Spec Text
> numbers as minimal string form ... Examples: `1 -> "1"`, `1.0 -> "1"`,
> `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

### Alternatives
1. Integral floats collapse to the integer spelling (`str(int(v))`); every other
   float uses Python's shortest round-trip `repr`. Then `1e30 -> "1000000000000000019884624838656"`
   and `1e-7 -> "1e-07"`.
2. Keep Python's `repr` for exponent-range values (`1e30 -> "1e+30"`), only
   stripping a trailing `.0`.
3. Route through `decimal.Decimal(str(v)).normalize()` (`1e30 -> "1E+30"`).

### Choice
Alternative 1. All four spec examples are exactly "int if integral, else `repr`",
which is also the shortest implementation of that rule; nothing in the spec hints
at scientific notation, and "minimal" is used to explain the dropped trailing
zeros (`1.0`, `1.50`), not exponent formatting.

### Risk: 30
Most likely alternative preferred by the author: #2, if they wrote the rule as a
string operation on `repr(v)` rather than a numeric `is_integer()` test — but
only very large or very small magnitudes can tell the two apart, and the spec
examples do not go there.

---

## T21 — `type` for a JSON number written as `1.0`

### Spec Text
> Every converted element except `<root>` carries `type` in:
> `str`, `int`, `float`, `bool`, `dict`, `list`, `null`.

> `1.0 -> "1"`

### Alternatives
1. `type` comes from the JSON literal's form, i.e. Python's parsed type: `1.0`
   is a `float` even though its text is `1`.
2. `type` comes from the value: an integral number is `int` regardless of how it
   was written, so `1.0` gets `type="int"` and `float` only ever appears on
   non-integral numbers.

### Choice
Alternative 1. The seven type names are precisely Python's `type(v).__name__`
with `NoneType` renamed to `null`, which pins the mapping to the parsed object,
not to the rendered text. Text minimalisation and typing are stated as two
separate rules and so are free to disagree.

### Risk: 15
Most likely alternative preferred by the author: identical — `type(v).__name__`
is the obvious way to produce that exact vocabulary.

---

## T22 — Tag name for entries of a *nested* array

### Spec Text
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.

### Alternatives
1. `<item>` is the generic name for "an array entry", so a nested list's entries
   are `<item>` too.
2. The rule is scoped to top-level arrays only, and nested arrays need some
   other (unspecified) name, e.g. repeating the owning key.

### Choice
Alternative 1. #2 leaves nested arrays undefined, and the top-level rule is
naturally the base case of one recursive conversion function. `{"a":[1]}` becomes
`<a type="list"><item type="int">1</item></a>`.

### Risk: 10
Most likely alternative preferred by the author: identical; a single recursive
converter gives #1 for free.

---

## T23 — Which keys count as "not valid XML element names"

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1`.

### Alternatives
1. The XML 1.0 `Name` production as enforced by lxml when constructing an
   element: rejects `""`, `"1a"`, `"a b"`, and anything containing `:`; accepts
   `_x`, `a-b`, `a.b`, and non-ASCII letters like `é`.
2. A stricter ASCII regex such as `^[A-Za-z_][A-Za-z0-9_.-]*$`, which also
   rejects non-ASCII keys.
3. A looser rule that treats `a:b` as a legal (prefixed) name.

### Choice
Alternative 1 — "valid XML element name" is a defined term, and delegating to the
XML library is both the literal reading and the least code. Colons are rejected
because a bare prefixed name with no namespace binding is not usable.

### Risk: 30
Most likely alternative preferred by the author: #2, if they hand-wrote a regex;
that differs only on non-ASCII keys, which are otherwise perfectly ordinary JSON.

---

## T24 — Are nested keys validated, or only top-level ones?

### Spec Text
> JSON keys that are not valid XML element names are invalid input

### Alternatives
1. Every key in the document is validated during conversion, so `{"ok":{"bad key":1}}`
   fails even though the query may never touch it.
2. Only keys that actually become elements the query looks at, or only top-level
   keys, are validated.

### Choice
Alternative 1: "invalid input" is a property of the document, not of the query,
and conversion visits every key anyway.

### Risk: 5
Most likely alternative preferred by the author: identical.

---

## T25 — Duplicate keys in one JSON object

### Spec Text
> Preserve JSON key order in converted XML.

### Alternatives
1. Standard JSON-parser behaviour: the last occurrence wins and only one element
   is emitted, at the position of... the first occurrence's key slot (Python
   dicts keep the original insertion position when a key is reassigned).
2. Emit one element per occurrence, preserving both.

### Choice
Alternative 1 — the natural consequence of parsing with a normal JSON parser into
a dict, which is what "preserve JSON key order" presupposes (an ordered mapping).

### Risk: 15
Most likely alternative preferred by the author: identical, unless they used an
`object_pairs_hook`, which nothing in the spec asks for.

---

## T26 — "empty" text: no text node, or an empty text node?

### Spec Text
> Primitive values map to element text: ... null as empty.

### Alternatives
1. An empty rendering means the element simply has no text node:
   `{"a": null}` -> `<a type="null"/>` and `{"a": ""}` -> `<a type="str"/>`.
   `//a/text()` selects nothing for either.
2. The text is literally the empty string, which in lxml creates an empty text
   node and serializes as `<a type="null"></a>` / `<a type="str"></a>`;
   `//a/text()` then yields one empty-string result (a blank line, see [[T15]]).

### Choice
Alternative 1, applied uniformly to `null` and to `""`. "null as empty" describes
the element's string value, which is `""` under either reading, and an element
with nothing in it is the more natural rendering of "empty"; it also keeps
`text()` queries from producing blank lines for values that have no text.

### Risk: 35
Most likely alternative preferred by the author: #2 for the empty string
specifically, since `element.text = value` is the direct way to set a string
value and only fails to be empty-node-free for `""`. The two readings agree on
`string(...)`, `@type` and every non-empty value; they differ only on `text()`
results and on `<a/>` vs `<a></a>` in serialized output.

---

## T27 — Is stdin still read when `INFILE` is present?

### Spec Text
> `INFILE` takes precedence over stdin when both are present.

### Alternatives
1. When `INFILE` is given it is the only input: stdin is never read, so its content
   is irrelevant even if it is malformed, huge, or an unclosed pipe.
2. Both are read and `INFILE` merely wins the tie (stdin drained first, then
   discarded), or stdin is used as a fallback when `INFILE` fails to parse.

### Choice
Alternative 1. "Takes precedence" describes selecting a source, not merging two;
draining stdin only to throw it away would hang on an open pipe with no benefit. A
file that exists but contains garbage is a parse error, not a reason to look at stdin.

### Risk: 5
Most likely alternative preferred by the author: identical — `data = open(infile).read()
if infile else sys.stdin.read()` is the obvious shape and never touches stdin.

---

## T28 — "Additional positional args are ignored" vs. unknown options

### Spec Text
> Additional positional args after `QUERY [INFILE]` are ignored.

### Alternatives
1. Only *positional* arguments beyond the second are ignored; unknown option flags
   (`--bogus`) remain an argparse usage error. Ignored positionals are never opened
   or validated, even if they name a missing file.
2. Everything after `QUERY [INFILE]` is ignored, flags included (argparse
   `REMAINDER`), so `xjq.py //a file --bogus` succeeds.
3. Extra positionals are an error (argparse's default).

### Choice
Alternative 1. The spec says "positional args", which distinguishes them from
options; `nargs="*"` on a trailing throwaway positional gives exactly that while
keeping flags parseable anywhere on the command line (so `xjq.py //a -f` still works,
which `REMAINDER` would break).

### Risk: 12
Most likely alternative preferred by the author: identical (`nargs="*"` or
`parse_known_args`); a `parse_known_args` implementation would also swallow
`--bogus`, which is the only visible difference.

---

## T29 — Does `-` as `INFILE` mean stdin?

### Spec Text
> `INFILE` takes precedence over stdin when both are present.
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. `-` is an ordinary path. There is almost never a file named `-`, so it is
   "missing": stderr message, exit `1`.
2. `-` is the conventional Unix spelling for stdin and is read from stdin.

### Choice
Alternative 1. The spec introduces no special filename, and it already has a rule
covering paths that cannot be opened. A conforming implementation built from the
prose (`open(infile)`) behaves this way without any extra code.

### Risk: 25
Most likely alternative preferred by the author: identical (a plain `open()`), but an
author who reached for `argparse.FileType()` or `fileinput` would get stdin instead.

---

## T30 — Where the UTF-8 BOM is stripped, and whether stdin gets the same treatment

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.
> Apply JSON auto-detection to file input: treat as JSON object/array when detected,
> otherwise parse as XML/HTML.

### Alternatives
1. Strip a leading BOM from the input before anything else, so both JSON detection
   and the XML parser see BOM-free content; apply the same stripping to stdin, since
   nothing in the spec makes stdin stricter than a file.
2. Strip it only for file input, leaving a BOM on stdin to reach the parsers as-is.
3. Do not strip: rely on `lxml` tolerating a BOM in bytes input (it does) and accept
   that JSON detection then fails on a BOM'd JSON file (`json.loads` rejects `\ufeff`).

### Choice
Alternative 1. "A UTF-8 BOM is allowed" has to mean it does not disturb the result,
and the JSON path is the one that actually breaks without stripping. Treating stdin
the same way is a strict superset: it only changes behaviour for input that would
otherwise have errored.

### Risk: 15
Most likely alternative preferred by the author: #2 — `open(path, encoding="utf-8-sig")`
for the file and raw bytes for stdin, which differs only for a BOM'd document on stdin.

---

## T31 — A file that is not valid UTF-8

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. Strict decoding: undecodable bytes make the file unreadable as UTF-8 text, so it
   takes the error path (stderr message, exit `1`).
2. Lenient decoding (`errors="replace"`/`"surrogateescape"`), so a Latin-1 document
   is queried with mojibake in place of the bad bytes.
3. Hand the raw bytes to `lxml`, letting an XML encoding declaration pick the codec.

### Choice
Alternative 1. The spec names UTF-8 as *the* decoding, and a decode failure is the
closest thing it describes to "unreadable"; failing loudly beats silently querying
corrupted text. XML content is still handed to `lxml` as UTF-8 bytes so that an
`encoding="UTF-8"` declaration is accepted.

### Risk: 30
Most likely alternative preferred by the author: identical if they call
`path.read_text(encoding="utf-8")` and catch broadly; #3 if they only ever pass bytes
to `lxml`, in which case a Latin-1 XML file with a matching declaration parses fine.

---

## T32 — Where `--first` sits relative to text extraction and normalization

### Spec Text
> `-f`, `--first`: return only first result.
> `--first` applies across text, attribute, and XML-node results.

### Alternatives
1. Last: truncate the final result list, so exactly one line is printed. With `-t -f
   '//a'`, the first *text node of the first element* is printed.
2. Early: truncate the matched node set before `--text`/`--text-all` expand it, so the
   first element's several text nodes all print.

### Choice
Alternative 1. "Return only first result" is about what is returned to the user, and
"applies across text, attribute, and XML-node results" names output categories, not
the raw node set. It also makes `--first` mean "at most one line of output" in every
mode, which is the only reading under which the flag is uniform.

### Risk: 35
Most likely alternative preferred by the author: identical for the common single
-text-node case; #2 if their implementation slices the node list right after the
query. The two differ only for an element with several direct text nodes.

---

## T33 — Exact compact serialization, and its trailing newline

### Spec Text
> `--compact` affects XML serialization only: compact XML output has no added
> pretty-print formatting.

### Alternatives
1. `tostring(node, with_tail=False)` with neither `etree.indent()` nor
   `pretty_print=True`: whitespace already in the source survives verbatim, nothing is
   added, no XML declaration, no tail text — and one `\n` is written after the node so
   the shell prompt starts on its own line.
2. The same, but with no trailing newline at all (raw serialization only).
3. "Compact" as *minifying*: strip existing inter-element whitespace so the node is
   always one line.

### Choice
Alternative 1. "No *added* pretty-print formatting" is the negation of the round-1
pretty-printing step, so the fix is to skip `indent()`/`pretty_print`, not to delete
whitespace the document really contains (#3 would edit the user's data). The trailing
newline matches [[T10]], where every other output mode is newline-terminated.

### Risk: 30
Most likely alternative preferred by the author: #2 — `sys.stdout.write(tostring(...))`
with no newline, if their compact branch bypasses the `print()` used elsewhere.
Tests that compare stripped output agree either way.

---

## T34 — Does `--first` change what XML-node results print by default?

### Spec Text
> `--first` applies across text, attribute, and XML-node results.

Round-1 spec:
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. The round-1 rule stands: node results are always first-only, so `--first` is a
   no-op for them and the new sentence just says the flag is not rejected or
   mis-applied there.
2. The new spec silently supersedes round 1: node results now print *every* matched
   node, and `--first` narrows them to one.

### Choice
Alternative 1. Round 1 states the first-node rule explicitly and this spec never
retracts it; a spec that meant to reverse an earlier rule would say so, especially in
a section titled "Output Rules". Keeping it also preserves every round-1 and round-2
fixture, which alternative 2 would break.

### Risk: 45
Most likely alternative preferred by the author: identical if their round-1 code is
untouched, but "`--first` applies across ... XML-node results" is hard to motivate
under alternative 1, so an author who added the flag by *removing* the old
first-node truncation would expect `//item` to print all three items and `-f //item`
to print one. See [[T14]] and [[T3]].

## T35 — Does `--json` export every matched element, or only the first?

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

> With `--first`, still return a JSON array containing one exported element.

Round-1 spec:
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. `--json` replaces the auto-format rule wholesale: every matched element is
   exported, so the array has one object per match.
2. The round-1 "only the first node" truncation still applies, and the array
   always holds exactly one object.

### Choice
Alternative 1. "array of objects" is plural, and the `--first` sentence ("still
return a JSON array containing one exported element") only earns its place if the
flag is what narrows the export to one — under alternative 2 `--first` would change
nothing and the sentence would be vacuous.

### Risk: 8
Most likely alternative preferred by the author: identical; the JSON contract is
written as a set-of-results export. See [[T34]] and [[T14]].

---

## T36 — What "immediate text content" is, exactly

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> Use immediate text only (exclude descendant text from child elements).

### Alternatives
1. Every text node that is a direct child of the element -- lxml's `el.xpath("text()")`,
   i.e. `el.text` plus each child's `tail` -- concatenated, then normalized (strip,
   collapse whitespace runs) the way every other text output of this tool is.
2. The same concatenation, but emitted raw (source whitespace and newlines kept
   inside the JSON string).
3. Only `el.text` -- the text before the first child element -- so
   `<div>one<span>two</span>three</div>` exports `"one"` and drops `"three"`.

### Choice
Alternative 1. "Immediate text", with the parenthetical excluding only *descendant*
text from child elements, describes the element's own text nodes; a child's tail is
text of the parent, not of the child, so it belongs. Normalizing matches the
round-1 text pipeline ("strip each result, collapse internal whitespace runs") and
keeps pretty-printed input from exporting `"\n  "` for every container element.

### Risk: 35
Most likely alternative preferred by the author: alternative 3 -- `el.text` alone,
with a `.strip()` -- since that is the one-liner most implementations reach for and
their fixtures are probably single-text-node elements where all three agree.

---

## T37 — "zero-indent JSON layout (no leading whitespace)" under `--compact`

### Spec Text
> Default JSON formatting: 2-space indent.
> With `--compact`, produce zero-indent JSON layout (no leading whitespace).

### Alternatives
1. `json.dumps(data, indent=0)`: still one token per line, but no indentation, so
   `[\n{\n"item": "a"\n}\n]`.
2. `json.dumps(data)` with default separators: the whole document on one line,
   `[{"item": "a"}]`.
3. `json.dumps(data, separators=(",", ":"))`: one line, no spaces at all.

### Choice
Alternative 1. The spec says *layout* and glosses it as "no leading whitespace",
not "one line" -- an author who meant a single line would have said so (as the
round-2 `--compact` rule for XML nodes does). `indent=0` is literally the
zero-indent spelling of the default `indent=2`, and it is the only reading under
which "no leading whitespace" is a meaningful description rather than a trivial
consequence.

### Risk: 25
Most likely alternative preferred by the author: alternative 2, if they read
`--compact` as "one line" by analogy with the XML-node compact rule.

---

## T38 — `--json` when the query matches nothing

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

Round-1 spec:
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Nothing is written: the round-1 no-match rule is unconditional and comes before
   any formatting decision.
2. An empty array `[]` is written, because the export contract promises an array.

### Choice
Alternative 1. The no-match rule is stated absolutely, and an implementation only
reaches the "are these results elements?" question once it has results -- with an
empty result set there is no element output to convert, so `--json` (which merely
reformats element output) has nothing to reformat.

### Risk: 35
Most likely alternative preferred by the author: `[]`, if their JSON branch is
selected by the flag rather than by the shape of the results.

---

## T39 — `--json` with comment/PI nodes, or a mix of nodes and strings

### Spec Text
> `-j`, `--json`: JSON export mode for XML element results.
> `--json` has no effect when results are already auto-detected as text
> (e.g., text()/attribute outputs).

### Alternatives
1. Decide the mode from the first result exactly as the round-1 auto-format does
   (see [[T3]]): first result an element/comment/PI ⇒ node output ⇒ JSON export,
   and within that export only real elements (string tag) become objects; comments
   and PIs, which have no tag name, are skipped.
2. Export comments/PIs too under some invented key (`"comment"`).
3. Export any element found anywhere in a mixed result set, even when the first
   result is a string.

### Choice
Alternative 1. The flag is scoped to "XML element results", and `{tag_name: ...}`
presupposes a tag name that only elements have. Reusing the existing first-result
dispatch keeps `--json` a pure reformatting of what would otherwise be node output.

### Risk: 20
Most likely alternative preferred by the author: untested; if tested, an
element-only filter like this one.

---

## T40 — How a query is recognized as a "union query"

### Spec Text
> Support XPath `|` union in XPath mode.
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Syntactic: in XPath mode, the query text contains a `|` outside of a quoted
   string literal. The special concatenation rule then applies to exactly those
   queries.
2. Semantic: parse the expression and check for a top-level union operator only, so
   `//a[b | c]` (a union inside a predicate) would not count.
3. Apply the concatenation rule to every `--text-all` query, union or not.

### Choice
A syntactic scan that splits at `|` outside string literals, predicates and
parentheses -- alternative 1, tightened with alternative 2's "top level only" so that
`//a[b|c]` is not mistaken for a union. `|` is XPath 1.0's only use of that character,
so a depth-aware scan and a real parse agree on every realistic query. Alternative 3
is excluded because the spec explicitly conditions the rule on "union queries", which
would otherwise not need naming.

### Risk: 15
Most likely alternative preferred by the author: `"|" in query`, a plain substring
test, which differs from this choice only for a `|` inside a string literal.

---

## T41 — How union + `--text-all` text is joined

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. True concatenation: join every descendant text node with the empty string, then
   normalize (strip, collapse whitespace runs). Source whitespace is what separates
   words, so `<p>a<b>b</b>c</p>` yields `abc` and
   `<p>Hello <b>World</b></p>` yields `Hello World`.
2. Join with a single space (or normalize each text node and join with a space), so
   the same inputs yield `a b c` and `Hello World`.

### Choice
Alternative 1. "Concatenate" is the operation named, and normalization is applied to
the *result* ("into one normalized output string"), which only makes sense as
strip+collapse over the concatenation. It is also the reading that reproduces the
document's own spacing rather than inventing separators.

### Risk: 35
Most likely alternative preferred by the author: a space-joined variant, which many
implementations use to avoid gluing words together across element boundaries; their
fixture is probably whitespace-separated, where both readings agree.

---

## T42 — What makes a union sub-path "already perform text extraction"

### Spec Text
> If any union sub-path already performs text extraction, text flags are treated as
> no-op query modifiers.

### Alternatives
1. Static: split the query on top-level `|` and look for a `text()` node test in any
   sub-path (`//a/text() | //b`), outside string literals.
2. Dynamic: run the query first and treat the flags as no-ops when any result is not
   an element (a string from `text()`/`@attr`).
3. Wider static test: also count `@attr` steps, `string()`, `normalize-space()` and
   friends as "text extraction".

### Choice
Alternative 1, read as "the sub-path *yields* text nodes": its last step is `text()`,
with predicates and string literals ignored, so `//a[text()="x"] | //b` (which filters
on text but returns elements) is not treated as text extraction. The sentence is about
the *query* ("sub-path"), not the results, and "text extraction" is the phrase this
spec family uses for `text()`/`::text`. The static test also stays stable when a
sub-path happens to match nothing, which the dynamic one does not.

### Risk: 25
Most likely alternative preferred by the author: alternative 2 -- checking result
types is the cheaper implementation, and it agrees with this choice on every union
whose text sub-path actually matches something.

---

## T43 — Which node is "the first matched union node"

### Spec Text
> If `--first` is also active with union + `--text-all`, only the first matched
> union node contributes to the output.

### Alternatives
1. The first result in document order -- what lxml returns first for a union, since
   it sorts and de-duplicates union results.
2. The first match of the textually first sub-path (`//b | //a` would take a `b`
   even if an `a` comes earlier in the document).

### Choice
Alternative 1. "First matched" is the same phrase round 2 uses for `--first`
generally, where it means first in document order, and every XPath engine hands back
a union as a document-ordered node-set.

### Risk: 20
Most likely alternative preferred by the author: identical; producing alternative 2
would take deliberate extra work.

---

## T44 — Does a no-op'd text flag hand control to `--json`?

### Spec Text
> 1. `--text-all`
> 2. `--text`
> 3. `--json`
> 4. default auto-format behavior

> If any union sub-path already performs text extraction, text flags are treated as
> no-op query modifiers.

### Alternatives
1. Precedence is decided by which flags are *present*: with `--text-all -j` on a
   union whose sub-path already extracts text, `--text-all` still wins the
   precedence contest, it simply does nothing, and `--json` stays inert.
2. Precedence is decided by which flags have an *effect*: a neutralized `--text-all`
   drops through to `--json`, which then exports the element sub-path's matches.

### Choice
Alternative 1. The precedence list is written over flags, not over outcomes, and the
same reading already governs the neighbouring sentence "`--json` has no effect when
results are already auto-detected as text" -- there too the higher rule wins by being
present.

### Risk: 25
Most likely alternative preferred by the author: untested combination; if tested,
alternative 1 for the same structural reason (their code almost certainly resolves
the text mode before it ever looks at `--json`).

---

## T45 — CSS mode selectors that cssselect accepts but XPath rejects

### Spec Text
> In CSS mode, pass `|` through as CSS query text (no XPath union semantics).
> If the CSS engine rejects the selector, report a CSS selector error on stderr
> with exit code `1`.

### Alternatives
1. Any failure to turn the CSS selector into a runnable query is reported as a CSS
   selector error. `div | span` is rejected by cssselect's parser, while `div|span`
   parses as the namespaced selector `span` in namespace `div` and is rejected later
   by lxml ("undefined namespace prefix"); both come out as a CSS selector error,
   exit `1`.
2. Only parser-level rejections are CSS selector errors; a translated-but-uncompilable
   selector keeps the generic "invalid xpath expression" wording (still exit `1`).

### Choice
Alternative 1. In `--css` mode the user never wrote XPath, so an XPath-flavoured
message would name something they cannot see; the spec's intent is that a `|`
selector the engine cannot honour is reported as a selector error. Exit code and
"nothing on stdout" are identical either way, so only the message text differs.

### Risk: 15
Most likely alternative preferred by the author: identical for `div | span` (the
natural fixture, rejected by the parser); the wording of the `div|span` case is
unlikely to be asserted beyond "css" or "selector" appearing in the message.

---

## T46 — Does the union concatenation rule extend to `--text`?

### Spec Text
> `--text` and `--text-all` apply across union queries.
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. Only `--text-all` concatenates. `--text` on a union keeps the round-1 behaviour:
   one normalized line per extracted text node, with `--first` trimming to the first
   line.
2. Both text flags concatenate into a single line when the query is a union.

### Choice
Alternative 1. The first sentence says both flags *work* across unions; the second
singles out `--text-all` for the concatenation. Naming one flag in a rule that could
have named both is deliberate.

### Risk: 20
Most likely alternative preferred by the author: identical; a shared code path for
both flags would have made the second sentence say "text flags".

---

## T47 — Non-ASCII characters in JSON export

### Spec Text
> Default JSON formatting: 2-space indent.

### Alternatives
1. Python's `json.dumps` default, `ensure_ascii=True`: `café` exports as
   `café`.
2. `ensure_ascii=False`: the literal UTF-8 characters are written.

### Choice
Alternative 1. The spec pins only the indent, so everything else is the default
formatting of the obvious serializer; `json.dumps(rows, indent=2)` is what an
implementation writes when the spec says "2-space indent".

### Risk: 20
Most likely alternative preferred by the author: identical (the library default);
non-ASCII element text is an unlikely fixture either way.


---

## T48 — How an element renders when the result set is dispatched to text output

### Spec Text
> If any union sub-path already performs text extraction, text flags are treated as
> no-op query modifiers.

Round-1 spec:
> Text/attribute results: strip each result, collapse internal whitespace runs to
> single spaces, then join results with each on a newline.

### Alternatives
1. Render the element as its XPath 1.0 string value -- the concatenation of its
   descendant text -- so `--text-all "//h1/text() | //em"` prints `Title` then
   `World`.
2. Serialize the element as XML on its line.
3. Skip elements entirely, printing only the string results.

### Choice
Alternative 1. This case only arises for a mixed result set, which round 1 dispatches
by its first result ([[T3]]); once the set is text output, XPath's own node-to-string
conversion is the string value. This round makes the case reachable on purpose -- a
union of a `text()` sub-path with an element sub-path -- so it needs an answer that is
not Python's `<Element p at 0x...>` repr, which no fixture could assert anyway.

### Risk: 30
Most likely alternative preferred by the author: alternative 2, if their mixed-set
handling serializes anything node-shaped; or a set-wide switch to XML-node output
(T3's alternative 2), which would print `<em>World</em>` alone.
