# Ambiguities

Numbered record of under-specified points in the spec, the readings considered,
and the interpretation this implementation commits to.

---

## T1 — "XML/HTML" parsing vs. mandatory error on malformed XML

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

> Malformed/empty XML input: stderr message, exit code `1`; message should reference `xml`/`parse`.

### Alternatives
1. **XML parser only** (`lxml.etree.XMLParser(recover=False)`): any input that is not
   well-formed XML is an error. `XML/HTML` is read as loose prose for "markup".
2. **XML first, HTML fallback**: try a strict XML parse; on failure re-parse with
   `lxml.etree.HTMLParser`, which recovers almost anything. Only inputs that even the
   HTML parser rejects (empty input) produce an error.
3. **HTML parser only**: maximal tolerance, but `lxml`'s HTML parser lower-cases tag
   and attribute names, which destroys case-sensitive element matching.

### Choice
Alternative 1 — strict XML parsing only. Two clauses of the spec point here: the
explicit demand for *case-sensitive element matching* (the distinguishing property of
the XML parser; the HTML parser folds `<Book>` to `<book>`), and the explicit
requirement that malformed input exit `1`. Under alternative 2 a classic malformed
sample such as `<root><child></root>` would be silently recovered and exit `0`,
contradicting the Errors section. Alternative 3 is ruled out outright by
case-sensitivity. Well-formed XHTML/HTML still parses fine through the XML parser, so
the "HTML" half of the prose remains served for the inputs where it can be.

### Risk: 20
Author most likely prefers: strict XML only (same as chosen); the residual risk is an
implementation that falls back to the HTML parser and whose malformed-input fixture is
something the HTML parser also rejects (e.g. empty input or raw `&` garbage).

---

## T2 — Results that are empty after stripping

### Spec Text
> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline. No trailing newline.

### Alternatives
1. **Keep every result**, including ones that reduce to the empty string, so a
   whitespace-only text node contributes an empty line to the joined output.
2. **Drop results that are empty after normalization**, so only non-empty lines appear.

### Choice
Alternative 1 — no filtering. The spec describes a straight pipeline of
strip → collapse → join with no mention of discarding anything, and the only place it
sanctions writing nothing at all is the separate "No-match" clause (an empty result
set). A conforming implementation that filtered would need a rule the prose never
states. Note that the pretty-print path (T5) normalizes the tree copy it serializes,
but the queried tree itself is untouched, so `text()` results keep their original
node set.

### Risk: 40
Author most likely prefers: dropping empties — an author who parsed with
`remove_blank_text=True`, or who added a `if s` guard after seeing blank lines from
`//*/text()` on an indented document, would produce no empty lines.

---

## T3 — Serialization of non-node-set XPath results (numbers, booleans)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.

> Text/attribute results: strip each result, collapse internal whitespace runs to single spaces, then join results with each on a newline.

### Alternatives
1. **XPath 1.0 `string()` semantics**: booleans render as `true`/`false`; a number
   whose value is integral renders without a fractional part (`count(//a)` → `3`).
2. **Python `str()` semantics**: `True`/`False` and `3.0`.
3. Treat non-node-set results as unsupported and error.

### Choice
Alternative 1. The spec pins the language to XPath 1.0, whose own string-conversion
rules are the only ones it names; `3.0` and `True` are Python artifacts, not XPath
1.0 lexical forms. `count(...)` is the overwhelmingly common non-node-set query, and
`3` is what an XPath user expects. Alternative 3 is excluded because such queries
"execute successfully" and so must exit `0`.

### Risk: 30
Author most likely prefers: `3` for counts (agreeing), but plain Python `str()` for
booleans, giving `True`/`False`.

---

## T4 — Distinguishing "text/attribute results" from "XML node results"

### Spec Text
> Text/attribute results: strip each result …
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

### Alternatives
1. **Per-result-set decision on node kind**: if the result set contains any element
   (or comment / processing-instruction) node, take the XML branch and emit only the
   first such node; otherwise take the text branch.
2. **Per-item decision**: serialize element items as XML and normalize string items,
   interleaving both in one output.
3. Decide from the query's syntax (does it end in `text()` / `@attr`).

### Choice
Alternative 1. The spec frames the two output modes as alternatives for a whole
invocation ("when multiple XML nodes match, output only the first node" is a
result-set-wide rule), so the branch is chosen once per run. Mixed node-sets are only
producible with a union such as `//a | //b/text()`; routing those to the XML branch
keeps the "only the first node" rule intact. Alternative 3 is brittle (`string(//a)`,
`name(//a)`, `//a/@*` all defeat it).

### Risk: 15
Author most likely prefers: the same whole-result-set branch; disagreement would only
show on a union query mixing nodes and strings, which is an unlikely fixture.

---

## T5 — What "pretty-print" means, and its trailing newline

### Spec Text
> XML node results: pretty-print serialized XML; when multiple XML nodes match, output only the first node.

> … join results with each on a newline. No trailing newline.

### Alternatives
1. **Naive `etree.tostring(node, pretty_print=True)`**: `lxml` only re-indents where a
   node has no existing text/tail, so a node taken from an already-indented source
   document is re-emitted with the source's original (now dangling) indentation rather
   than a fresh, correct one.
2. **Normalize then pretty-print**: serialize a deep copy whose whitespace-only text
   and tail nodes have been dropped, so the output is genuinely re-indented from
   column zero regardless of how the input was formatted.
3. Emit the node exactly as it appeared in the source.

### Choice
Alternative 2, with exactly one trailing newline. The spec asks for *pretty-print*,
and alternative 1 demonstrably fails to pretty-print the most common case (an element
selected out of an indented document keeps the parent's indentation on its closing
tag). Normalizing a copy achieves the stated goal without disturbing the tree that
`text()` queries run against (see T2). The "No trailing newline" sentence sits inside
the text/attribute bullet, so it is read as scoped to that bullet; a serialized XML
document conventionally ends in a newline, and `pretty_print=True` emits one.

### Risk: 35
Author most likely prefers: the naive `pretty_print=True` of alternative 1, with the
source document's residual indentation baked into their expected fixture.

---

## T6 — `[OPTIONS]` with no options defined

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. Accept only the implicit `-h`/`--help`, and reject any other flag.
2. Silently ignore any unrecognized flag, treating `[OPTIONS]` as a forward-compatible
   placeholder.

### Choice
Alternative 1 (standard `argparse` behaviour). The spec defines no option anywhere, so
there is nothing to honour; rejecting unknown flags is the conventional CLI contract
and keeps a mistyped flag from being silently swallowed as a query.

### Risk: 10
Author most likely prefers: the same `argparse` default; the only divergence would be
the exit code for a bad flag (`2` from argparse vs. `1`), which the spec never
mentions.

### Annotation (CSS/text spec)
Partially resolved: the follow-up spec fills the `[OPTIONS]` slot with `--css`,
`-t`/`--text` and `--text-all`. The choice itself stands — flags outside that set
(plus `-h`/`--help`) are still rejected by `argparse`.

---

## T7 — Whether `INFILE` must exist

### Spec Text
> `INFILE`: accepted positional argument but not used.
> Input source: stdin.

### Alternatives
1. Accept the argument and ignore it entirely — never stat, open, or validate it.
2. Accept it but validate that it exists, erroring otherwise.

### Choice
Alternative 1. "accepted … but not used" is explicit: the argument is parsed and
discarded, and input comes from stdin regardless. Validating a path the program never
reads would invent an error mode the spec does not list.

### Risk: 5
Author most likely prefers: the same — the wording is about as unambiguous as the spec
gets, so this entry exists only to record that a nonexistent `INFILE` is not an error.

---

## T2 (annotation, CSS/text spec)

The follow-up spec restates the rule as "Strip each result and collapse internal
whitespace runs to single spaces" and still names no filtering step, so the T1-era
choice (keep results that normalize to the empty string) is carried forward
unchanged. It now bites harder: `selector ::text` on an indented document yields a
whitespace-only text node for every bit of inter-tag indentation, so those become
blank lines. See T14, which records that consequence separately.

---

## T8 — Granularity of `selector::text` (per text node vs per element)

### Spec Text
> Define custom `::text` pseudo-element:
> `selector::text` returns direct text;
> `selector ::text` returns all descendant text nodes (one text node per line).

> `-t`, `--text`: direct text extraction from matched elements, one per element.

### Alternatives
1. **`::text` is sugar for the XPath `/text()` step**: `p::text` selects the direct
   text *nodes* of each match, so `<p>Hello <b>b</b> world</p>` yields two lines
   (`Hello`, `world`). The `--text` flag is a different thing: it emits one line per
   *element*, so the same document yields one line (`Hello world`).
2. **`::text` and `--text` are the same operation**: both concatenate an element's
   direct text into a single line per element.
3. `::text` per text node *and* `--text` per text node (making them identical the
   other way round).

### Choice
Alternative 1. The spec attaches "one per element" only to the two flags and
"one text node per line" only to `::text`; the two phrasings are deliberately
different, which is only meaningful if the granularities differ. It also matches the
existing XPath behaviour this tool already has — `//p/text()` prints one line per
text node — and the flag-rules bullet explicitly groups `text()` and `::text`
together as "the query already extracts text", implying `::text` *is* `/text()`.
The descendant form is likewise `descendant-or-self::*/text()`, a node-set of text
nodes, which is exactly what "one text node per line" describes. Under this reading
`--text` on a `::text` query is a genuine no-op (nothing but strings comes back),
which is the fourth bullet of Flag Rules.

### Risk: 30
Author most likely prefers: the same (`::text` → `/text()`); the residual risk is an
author who joined a match's direct text nodes into one line for `selector::text` so
that `p::text` and `-t p` agree, and whose mixed-content fixture then expects a
single `Hello world` line.

---

## T9 — What "direct text" means for `--text`

### Spec Text
> `-t`, `--text`: direct text extraction from matched elements, one per element.

### Alternatives
1. **Concatenate every direct text-node child**: `element.text` plus the `tail` of
   each child element, i.e. `string-join(el/text())`. For
   `<p>Hello <b>b</b> world</p>` this is `Hello  world` → normalized `Hello world`.
2. **`element.text` only** — the text before the first child element. Same document
   gives `Hello`.

### Choice
Alternative 1. "Direct text" is the text belonging directly to the element, which in
the XML data model is the whole `el/text()` node-set, not just its first member;
alternative 2 silently drops content for any mixed-content element and has no basis
in the prose. It also keeps `--text` consistent with `::text` (T8): the same nodes,
merely joined instead of split.

### Risk: 25
Author most likely prefers: the same concatenation; the risk is an lxml
implementation that reached for the convenient `el.text` attribute and wrote its
fixture around `Hello`.

---

## T10 — Comma-separated query mixing `::text` with a plain selector

### Spec Text
> Comma-separated selectors are supported for `::text` queries when all
> selectors use the same `::text` mode.
> Mixing direct and descendant `::text` modes in one comma-separated CSS query
> is invalid (stderr message, exit code `1`).

### Alternatives
1. **Any mode mismatch is invalid**, counting "no `::text` at all" as its own mode:
   `a::text, b` is an error, as is `a::text, b ::text`.
2. **Only direct-vs-descendant is invalid**, literally as the second sentence says:
   `a::text, b` is accepted and produces a node-set mixing text strings and elements.

### Choice
Alternative 1. The permissive sentence is the operative rule — commas are supported
"when all selectors use the same `::text` mode" — and a selector with no `::text` is
not using the same `::text` mode as one that has it. The natural implementation
(collect the mode of each comma-separated selector into a set, reject a set with more
than one member) produces exactly this, and the second sentence then reads as calling
out the salient instance rather than the only one. Alternative 2 also forces an
answer to "what does a mixed string/element result print", which the spec never
addresses.

### Risk: 30
Author most likely prefers: the same one-set check; the risk is an implementation
that guards literally with `if 'direct' in modes and 'descendant' in modes` and has a
fixture where `a::text, b` succeeds.

---

## T11 — Are `--text` / `--text-all` limited to CSS mode?

### Spec Text
> ## CLI Additions
> - `--css`: interpret `QUERY` as CSS selector.
> - `-t`, `--text`: direct text extraction from matched elements, one per element.
> - `--text-all`: descendant text extraction from matched elements, one per element.

> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. **The flags apply in either query mode.** `xjq.py -t '//book'` extracts the direct
   text of every matched `book`.
2. **The flags only mean something with `--css`**, and are ignored (or rejected)
   without it.

### Choice
Alternative 1. The three flags are listed as peers under "CLI Additions" with no
dependency stated between them, and the Flag Rules bullet names `text()` — an XPath
construct, impossible in CSS mode — as a query that makes them no-ops, which only
makes sense if they are reachable from XPath mode. Nothing in the spec makes `--css`
a precondition.

### Risk: 15
Author most likely prefers: the same; a `--text`-without-`--css` fixture is plausible
precisely because the `text()` clause invites it.

---

## T12 — Does "output only the first node" survive into CSS mode?

### Spec Text
> In CSS mode without text extraction, return XML node output with
> pretty-print serialization.

Prior spec:
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. **CSS node output is the same output mode as XPath node output**, so the
   first-node-only rule applies: `--css 'a'` on three `a`s prints one.
2. **CSS mode prints every matched node**, pretty-printed and concatenated, because
   this bullet re-specifies node output for CSS and omits the first-node rule.

### Choice
Alternative 1. The sentence says "return *XML node output*" — a reference to the
already-defined output mode, not a redefinition of it; the only thing it adds is that
CSS mode does not invent a new serialization. If the author wanted all nodes here
they would have had to say so, since that reverses an explicit earlier rule, and the
result would be the oddity of `--css 'a'` and `'//a'` printing different amounts.
Users who want every match have `--text`/`--text-all`.

### Risk: 30
Author most likely prefers: the same single-node output; the risk is an author who
treated CSS mode as the "modern" path and emitted all matched nodes.

---

## T13 — How `--text` / `--text-all` become no-ops

### Spec Text
> If query already extracts text (`text()` or `::text`), `--text` and
> `--text-all` are no-op modifiers.

### Alternatives
1. **Decide from the results**: text extraction is applied to element results only;
   anything already a string, number or boolean passes straight through. A query that
   returns no elements is therefore automatically unaffected by the flags.
2. **Decide from the query text**: scan `QUERY` for the substrings `text()` or
   `::text` and disable the flags when found.

### Choice
Alternative 1. It implements the stated rule without a substring heuristic, and it
extends sensibly to the cases the sentence does not enumerate — `//book/@id -t`,
`count(//a) -t`, `string(//a) -t` — none of which have anything to extract text
*from*. Alternative 2 both over-fires (a query such as `//a[contains(text(),'x')]`
returns elements yet contains `text()`) and under-fires (`//a/@id`).

### Risk: 10
Author most likely prefers: the same result-driven behaviour, since the observable
output agrees on every input except the `//a[contains(text(),'x')]` shape, where this
choice extracts text and the substring heuristic would print a node.

---

## T14 — Blank lines from whitespace-only descendant text nodes

### Spec Text
> `selector ::text` returns all descendant text nodes (one text node per line).

> Strip each result and collapse internal whitespace runs to single spaces.

### Alternatives
1. **Emit every text node**, so the indentation between child elements of a
   pretty-printed document contributes lines that are empty after stripping.
2. **Skip text nodes that are empty after stripping**, so only substantive text
   appears.

### Choice
Alternative 1, consistent with T2. "All descendant text nodes … one text node per
line" is unqualified, and the transformation named for each result is strip + collapse
with no discard step. Filtering would be an unstated third rule.

### Risk: 45
Author most likely prefers: filtering. `div ::text` over indented markup is the
headline use case for this feature, blank lines make it visibly useless, and
`[t for t in texts if t.strip()]` is the reflex fix — this is the entry in this file
most likely to be wrong.

---

## T15 — Selectors CSS accepts but this tool cannot evaluate

### Spec Text
> Invalid CSS selector: stderr message, exit code `1`.

### Alternatives
1. **One error class**: syntactically malformed selectors (`div >`, `a[`), unknown
   pseudo-elements (`::before`), and pseudo-classes with no XPath equivalent
   (`:hover`) all report an invalid-CSS error and exit `1`.
2. Distinguish "syntax error" from "unsupported but well-formed", with only the
   former exiting `1` and the latter, say, matching nothing and exiting `0`.

### Choice
Alternative 1. The spec lists exactly one CSS failure mode, and every one of these
inputs is a `QUERY` the tool cannot turn into a result — silently succeeding with no
output would hide a user error. `cssselect` already raises a single `SelectorError`
base class over both cases, so this is also the path of least resistance.

### Risk: 15
Author most likely prefers: the same catch-all `except SelectorError` → exit `1`.

---

## T16 — CSS matching semantics: XML or HTML flavour

### Spec Text
> `--css`: interpret `QUERY` as CSS selector.

Prior spec:
> Parse stdin as XML/HTML using case-sensitive element matching.

### Alternatives
1. **`cssselect.GenericTranslator` (XML flavour)**: element names match
   case-sensitively, `.cls` is a whitespace-token test on `@class`, `#id` is a test on
   `@id`.
2. **`cssselect.HTMLTranslator`**: case-insensitive element and attribute-value
   handling, HTML-specific `:checked`/`:link` support.

### Choice
Alternative 1. The document is parsed with the case-sensitive XML parser (T1), so a
case-insensitive selector translator would be able to name elements the parser keeps
distinct — `DIV` matching `<div>` while `//DIV` does not. `GenericTranslator` keeps
`--css` and XPath mode consistent with each other and with the standing
case-sensitivity requirement.

### Risk: 15
Author most likely prefers: the same `GenericTranslator`, being both `cssselect`'s
default and the only one consistent with case-sensitive parsing.

---

## T17 — How JSON is "auto-detected"

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.

> Input that fails JSON detection is parsed as XML/HTML.

### Alternatives
1. **Prefix sniff**: strip leading whitespace, and if the first byte is `{` or `[`,
   commit to JSON — a parse failure from that point on is a *JSON* error.
2. **Trial decode of the whole document**: run `json.loads` on all of stdin; treat the
   input as JSON only if it decodes completely *and* yields a `dict` or `list`.
   Anything else (decode failure, trailing junk, non-UTF-8 bytes, primitive result)
   falls through to the XML parser.

### Choice
Alternative 2. The spec frames detection as a test the input either passes or fails,
and says failure routes to XML/HTML — not to a JSON error. Under alternative 1,
`{"a": 1,}` would be a JSON syntax error; under the chosen reading it "fails JSON
detection" and is reported as an XML parse failure, which is what the sentence
literally prescribes. This also makes the primitive rule fall out of the same test
rather than needing a separate branch. Non-UTF-8 bytes are treated as a detection
failure too, so an ISO-8859-1 XML document with an encoding declaration still parses.

### Risk: 12
Author most likely prefers: the same whole-document trial decode (`json.loads` in a
`try`), with the residual risk being a fixture like `{"a": 1,}` whose stderr is
expected to mention `json` rather than `xml`.

---

## T18 — Tag name for entries of *nested* arrays

### Spec Text
> For top-level arrays: each entry becomes an `<item>` child of `<root>`.

### Alternatives
1. `<item>` is specific to the top level; a nested array's entries are named some
   other way — e.g. repeating the owning key (`{"tags":["x"]}` → `<tags><tags>x</tags>`)
   or indexed tags (`<item0>`).
2. `<item>` is the universal name for an array entry at any depth, and the top-level
   sentence is just the only place the spec had to spell out the parent.

### Choice
Alternative 2. The `type` vocabulary includes `list`, so nested lists are clearly
expected to exist as elements, and the spec gives no second naming rule for them.
Reusing the owning key would also make `<tags type="list"><tags type="str">` — an
element and its child sharing a tag — which reads as an accident, not a design.

### Risk: 8
Author most likely prefers: `<item>` at every depth (same as chosen).

---

## T19 — Whether `int` and `float` follow the JSON literal's spelling

### Spec Text
> Every converted element except `<root>` carries `type` in:
> `str`, `int`, `float`, `bool`, `dict`, `list`, `null`.

> Examples: `1 -> "1"`, `1.0 -> "1"`, `1.50 -> "1.5"`

### Alternatives
1. **Type from the decoded Python value**: `1` decodes to `int` → `type="int"`;
   `1.0` and `1e2` decode to `float` → `type="float"`, even though both render as
   integral text.
2. **Type from the rendered text**: because `1.0` renders as `"1"`, call it `int`, so
   `type` always agrees with how the text looks.

### Alternatives note
The spec's own example pairs `1.0` with the text `"1"` but says nothing about its type.

### Choice
Alternative 1. `json.loads` already draws the int/float line exactly where JSON's
grammar does, and the `type` attribute is documented as the value's *type*, not a
description of its text. Under alternative 2 the `float` name would become nearly
unreachable for round numbers, and `2.0` and `2` would be indistinguishable.

### Risk: 18
Author most likely prefers: the decoded-value reading (same as chosen), since
`type(v).__name__` over `json.loads` output produces precisely the seven listed names;
residual risk is an implementation that normalizes integral floats to int first.

---

## T20 — "minimal string form" outside the four examples

### Spec Text
> numbers as minimal string form […] Examples: `1 -> "1"`, `1.0 -> "1"`,
> `1.50 -> "1.5"`, `0.00012 -> "0.00012"`.

### Alternatives
1. **`repr`, with integral floats truncated**: `str(int(v))` when the float is
   integral, otherwise Python's shortest round-tripping `repr`. Satisfies all four
   examples; keeps full precision (`1.23456789` → `"1.23456789"`); switches to
   exponent form only where `repr` does (`1e-07` → `"1e-07"`).
2. **`"%g"` formatting**: also satisfies all four examples verbatim, but rounds to six
   significant digits (`1.23456789` → `"1.23457"`) and goes exponential at 1e+06.
3. **`decimal`/`json`-literal preservation**: echo the source spelling minus redundant
   zeros, so `1e2` stays `"1e2"`.

### Choice
Alternative 1. All four examples are consistent with it, and it is the only candidate
that never loses information — "minimal" most plausibly means "shortest form that is
still the same number", which is exactly what `repr` computes. `0.00012` staying
decimal rather than becoming `1.2e-04` confirms that no fixed exponent threshold is
intended, which argues against `%g`.

### Risk: 30
Author most likely prefers: `repr` with integral-float truncation (same as chosen);
the real exposure is a high-precision or very large/small fixture (e.g. `1e20`,
`1e-7`, `1.23456789`) where a `%g`-based or exponent-avoiding implementation differs.

---

## T21 — Scope of "no self-closing tags"

### Spec Text
> null as empty (no self-closing tags).

### Alternatives
1. The parenthetical is a rule **about null only**: `<a type="null"></a>`, while other
   empty values (empty string, `{}`, `[]`) may serialize as `<a/>`.
2. The parenthetical states a **document-wide serialization property** that null is
   simply the most obvious case of: no converted element is ever self-closing.

### Choice
Alternative 2. The note exists because the natural serializer output for an empty
element *is* `<a/>`, and that reason applies identically to `""`, `{}` and `[]`. A
reader scraping the output would find it strange for `<a type="null"></a>` and
`<a type="str"/>` to coexist. Implemented by giving every childless element an empty
text node, which makes lxml emit a start/end pair.

### Risk: 15
Author most likely prefers: the document-wide reading (same as chosen); residual risk
is a fixture asserting `<a type="str"/>` for an empty string.

---

## T22 — Which keys count as "not valid XML element names"

### Spec Text
> JSON keys that are not valid XML element names are invalid input and must
> produce stderr output with exit code `1`

### Alternatives
1. **ASCII-only identifier rule**, e.g. `^[A-Za-z_][A-Za-z0-9_.\-]*$`: rejects `"café"`
   and `"a:b"`.
2. **The XML 1.0 `Name` production minus the colon**: accepts Unicode letters
   (`"café"`, `"añ"`) per the actual XML grammar, rejects `"a:b"` because a colon makes
   the name a namespace-qualified QName rather than a plain element name.
3. **Full `Name` production including the colon**: `"a:b"` is a valid XML `Name`, so
   accept it and let it become a (prefix-undeclared) QName.

### Choice
Alternative 2. The spec's test is "valid XML element name", so the XML grammar is the
authority, and that grammar admits Unicode letters. The colon is excluded because an
element name containing one is not usable without a namespace declaration — lxml
refuses `a:b` outright, so accepting it could only produce a crash or a silently
broken document. The implementation checks the `Name` regex and then confirms with
lxml, so anything the serializer cannot represent is reported as the spec's
`json`/`key`/`invalid` error rather than escaping as a traceback.

### Risk: 35
Author most likely prefers: rejecting `"a:b"` and `"a b"` (agreeing with this choice),
but an ASCII-only regex that additionally rejects non-ASCII letter keys such as
`"café"` is a very plausible implementation.

---

## T23 — Depth at which keys are validated

### Spec Text
> JSON keys that are not valid XML element names are invalid input

### Alternatives
1. Only **top-level** keys are validated, since the conversion rules are phrased
   around the top level; a nested bad key would need some other handling (skip,
   sanitize, or crash).
2. **Every** key at every depth is validated, and the first offender aborts the run.

### Choice
Alternative 2. "Invalid input" describes the document as a whole, and every key
becomes a tag name regardless of depth, so a nested `"bad key"` is exactly as
unrepresentable as a top-level one. Validation happens during conversion, so the run
aborts before any output is written.

### Risk: 6
Author most likely prefers: recursive validation (same as chosen).

---

## T24 — What error a top-level primitive produces

### Spec Text
> Top-level JSON primitives are not accepted as JSON input for this mode; they fall
> back to XML parsing.

### Alternatives
1. The fallback is real: `42` is handed to the XML parser, fails there, and the
   message is the existing XML parse error (`xml`/`parse`).
2. The tool recognizes the primitive and emits a JSON-flavoured rejection
   ("top-level primitives are not supported") while still exiting `1`.

### Choice
Alternative 1. The spec says these inputs *fall back to XML parsing* rather than that
they are rejected, so the observable behavior should be indistinguishable from any
other non-JSON input: exit `1` with the malformed-XML message from the earlier spec.
This keeps exactly one error path for "stdin is not a usable document".

### Risk: 20
Author most likely prefers: the XML parse error (same as chosen); residual risk is a
fixture asserting `json` appears in stderr for input like `42`.

---

## T25 — Whether the converted tree is a normal document for every query mode

### Spec Text
> Auto-detect stdin as JSON object/array or XML/HTML.

### Alternatives
1. JSON input is a distinct mode with its own output rules or restrictions (e.g. only
   XPath, no `--css`, no `--text`).
2. Detection only chooses how the tree is *built*; everything downstream — XPath 1.0,
   `--css`, `-t`/`--text-all`, first-node-only serialization, exit codes — behaves
   exactly as it does for XML input, and the synthetic `type` attributes are ordinary
   attributes that queries can see and select.

### Choice
Alternative 2. Detection is described purely as an input concern, and the JSON-to-XML
contract is specified as an XML document (tags, attributes, order) precisely so the
existing query and output machinery applies unchanged. Hiding `type` from queries
would require special-casing that the spec never hints at, and would make
`@type` — the one thing the contract talks about most — unobservable.

### Risk: 5
Author most likely prefers: uniform downstream behavior (same as chosen).

---

## T1 (annotation, JSON spec)

The JSON spec resolves the "XML/HTML" prose from the other direction than T1
anticipated: stdin is now auto-detected, and only input that *fails JSON detection*
reaches the XML parser. The T1 choice (strict `XMLParser(recover=False)`, no HTML
fallback) stands unchanged for that branch — malformed markup still exits `1` — but
the set of inputs reaching it has shrunk. One earlier test fixture is retired by this:
`{"json": true}` was listed as malformed-XML input and is now a valid JSON document;
it is replaced by `{"json": true,}`, which fails JSON detection and so is still an XML
parse error. See T17 and T24 for the detection and fallback readings.
