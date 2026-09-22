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

---

## T7 (annotation, file-input spec)

Resolved and reversed by the current spec: `INFILE` is no longer "accepted but not
used". It is now opened, it takes precedence over stdin, and a missing or unreadable
path is an error with exit code `1`. The T7 choice (never stat or open the path) is
retired; the fixtures that asserted a nonexistent / unreadable / directory `INFILE`
was harmless are replaced by the error-path fixtures for the new rule. See T30-T34.

---

## T6 (annotation, file-input spec)

Further filled in: the `[OPTIONS]` slot now also contains `-f`/`--first` and
`-c`/`--compact`. Unknown flags are still rejected by `argparse`; the new rule that
"additional positional args are ignored" is deliberately read as applying to
positionals only (see T33).

---

## T26 — What "first result" is for a mixed node/string result set

### Spec Text
> `-f`, `--first`: return only first result.
> `--first` applies across text, attribute, and XML-node results.

### Context
An XPath union such as `//a/text() | //b` returns a single document-ordered list that
mixes strings and elements. The earlier spec's output rule is branch-based: if *any*
element is present the whole result is rendered as XML (first node only), otherwise
everything is rendered as text lines.

### Alternatives
1. `--first` truncates the raw XPath result list to its first item, and the existing
   branch rule is then applied to that one-item list. For a union whose first
   document-ordered item is a text node, `--first` therefore prints that text, while
   the same query without `--first` prints the first *element*.
2. `--first` leaves branch selection alone and only limits the chosen branch's output:
   the union still routes to the XML branch, and `--first` merely reaffirms
   "first node".

### Choice
Alternative 1. "return only first result" describes an operation on the result
sequence, not on a particular rendering branch, and the single natural implementation
of that sentence is a `result[:1]` slice applied before rendering. It is also the only
reading under which the clause "applies across text, attribute, and XML-node results"
is doing work: one truncation covers all three kinds because it happens before the
kinds are distinguished.

### Risk: 30
Author most likely prefers: the same `result[:1]` truncation; the residual risk is a
mixed-union fixture (text node ordered before an element) where a branch-preserving
implementation would still print the element.

---

## T27 — Whether `--first` changes anything for XML-node results

### Spec Text
> `--first` applies across text, attribute, and XML-node results.

Earlier spec, unrevoked:
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. The earlier "output only the first node" rule still holds, so `--first` is
   observably a no-op for pure node-set results; the new clause exists to say that
   `--first` is not rejected or ignored there, not to change node output.
2. Mentioning XML-node results implies the default changed: without `--first` all
   matched nodes are now serialized, and `--first` is what restores the one-node
   output.

### Choice
Alternative 1. The current spec adds flags and file input; it does not restate or
withdraw the earlier XML-node output rule, and a silent reversal of an explicit
earlier sentence is a much larger change than this spec announces. Reading the clause
as "no result kind is exempt from `--first`" keeps both specs true at once.

### Risk: 25
Author most likely prefers: node output stays first-only by default (same as chosen);
the risk is a fixture asserting that plain `//a` over a multi-match document now emits
every node.

---

## T28 — What "no added pretty-print formatting" removes

### Spec Text
> `--compact` affects XML serialization only:
> compact XML output has no added pretty-print formatting.

### Context
Pretty-printing here is a two-step pipeline: whitespace-only text and tails are first
dropped from the selected subtree so the serializer can re-indent it from column zero,
and the serializer is then run with `pretty_print=True`.

### Alternatives
1. Compact turns off the whole pipeline: the subtree's own text nodes are left exactly
   as they were in the source, and the serializer adds no indentation or line breaks.
   `<book>` selected from an indented document therefore still contains the source's
   newlines and leading spaces.
2. Compact keeps the whitespace-stripping step but disables the serializer's
   indentation, producing genuinely single-line output such as
   `<book id="b1"><title>XPath Basics</title></book>`.

### Choice
Alternative 1. The spec's qualifier is "no *added* pretty-print formatting", which
describes withholding formatting rather than deleting formatting the document already
had. Alternative 2 would discard real character data (whitespace between elements is
still text) on the strength of a flag the spec describes as a serialization-only
concern. The two readings coincide exactly for JSON-derived input, which is the case
the spec chose to call out, so nothing in the prose pushes toward the destructive
reading.

### Risk: 45
Author most likely prefers: alternative 2 — "compact" colloquially means one line, and
a single-line expected string is a much tidier fixture to write than one carrying the
source document's indentation.

---

## T29 — Whether compact output ends with a newline

### Spec Text
> compact XML output has no added pretty-print formatting.

### Alternatives
1. No trailing newline: the serialized element ends at its closing `>`.
2. A single trailing newline is still appended, since that is a line-terminator
   convention rather than pretty-printing.

### Choice
Alternative 1. lxml's trailing newline on a serialized element *is* produced by
`pretty_print=True`; turning pretty-printing off removes it along with the
indentation. Adding it back would be adding formatting that the compact mode is
defined by the absence of.

### Risk: 30
Author most likely prefers: no trailing newline (same as chosen), because it falls out
of `pretty_print=False`; a fixture that compares against a string ending in `\n` would
diverge.

---

## T30 — Decoding `INFILE` as UTF-8 when the document declares another encoding

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.

### Context
Stdin is deliberately handed to the parser as raw bytes so that
`<?xml version="1.0" encoding="ISO-8859-1"?>` is honoured. The file rule names a fixed
decoding instead.

### Alternatives
1. File input is decoded as UTF-8 (BOM-tolerant) and re-encoded to UTF-8 bytes for the
   parser, so the byte stream always matches UTF-8 and a conflicting encoding
   declaration is effectively overridden. Bytes that are not valid UTF-8 are a read
   failure: stderr message, exit `1`.
2. The file's bytes are passed through unchanged like stdin's, with the UTF-8 rule
   read as a mere statement of the expected encoding.

### Choice
Alternative 1. "Decode `INFILE` as UTF-8 text" is an instruction about how the file
becomes characters, and it is the only place either spec fixes an encoding, so it
should mean something observable. Treating undecodable bytes as an unreadable file
reuses the error path the same bullet list already defines rather than inventing a
third outcome, and the exit code is `1` under every reading anyway.

### Risk: 15
Author most likely prefers: the same UTF-8 decode; the divergence would be the stderr
wording for a non-UTF-8 file, or a fixture feeding a latin-1-declared file and
expecting it to be honoured.

---

## T31 — Whether `-` names stdin

### Spec Text
> `INFILE` takes precedence over stdin when both are present.

### Alternatives
1. `-` is an ordinary path. The tool tries to open a file literally named `-`, and
   normally fails with the missing-file error.
2. `-` is the conventional alias for stdin and switches the input source back.

### Choice
Alternative 1. The spec gives `INFILE` no special values, and its precedence rule is
stated as absolute; a `-` alias would be a second, unmentioned way to select stdin.
Silently reinterpreting a path is worse than reporting that it does not exist.

### Risk: 20
Author most likely prefers: `-` as a plain path (same as chosen); the risk is that
their `argparse`/`open` plumbing special-cases `-` out of habit.

---

## T32 — Whether the BOM allowance extends to stdin

### Spec Text
> Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed.

### Alternatives
1. Strip a leading UTF-8 BOM from both input sources. A BOM is already harmless for
   the XML parser, so the observable change is that BOM-prefixed JSON on stdin is now
   detected as JSON instead of failing as malformed XML.
2. Apply the allowance to file input only, since that is the bullet's subject.

### Choice
Alternative 1. The BOM clause reads as a leniency, and applying a leniency uniformly
cannot reject any input that alternative 2 accepts. The only behavioural difference is
BOM-prefixed JSON on stdin, where succeeding is plainly the friendlier outcome.

### Risk: 10
Author most likely prefers: file-only stripping, but a fixture that pipes a BOM plus
JSON into stdin and asserts failure is hard to imagine anyone writing.

---

## T33 — Scope of "additional positional args are ignored"

### Spec Text
> Additional positional args after `QUERY [INFILE]` are ignored.

### Alternatives
1. Only positionals are swallowed: a third, fourth, ... positional is accepted and
   discarded, while an unrecognized *option* is still an `argparse` error.
2. The tool becomes permissive about everything trailing, including unknown flags.

### Choice
Alternative 1. The sentence says "positional args", and the earlier spec's option
handling (T6) is untouched; quietly accepting a mistyped flag would let it be
swallowed instead of reported.

### Risk: 8
Author most likely prefers: positional-only leniency (same as chosen), most likely via
an `argparse` `nargs="*"` catch-all.

---

## T34 — What counts as "unreadable", and what the message says

### Spec Text
> Missing/unreadable file: stderr message, exit code `1`.

### Alternatives
1. Every `OSError` from opening or reading the path is the same failure: a
   nonexistent path, a permission denial, and a directory all produce one message
   naming the path, and exit `1`.
2. Only `FileNotFoundError` and `PermissionError` qualify, with other cases
   (a directory, a dangling symlink) left to crash with a traceback.

### Choice
Alternative 1. "Missing/unreadable" is a two-word summary of "the tool could not get
bytes out of this path", and a traceback is never an acceptable rendering of a
user-supplied bad path. The message names the path so the failure is diagnosable, and
goes through the same `xjq.py: error: ...` channel as every other failure.

### Risk: 12
Author most likely prefers: the same catch-all; the residual risk is a fixture
asserting particular words in stderr rather than just non-empty output and exit `1`.

---

## T35 — Whether an empty `INFILE` reuses the empty-document error

### Spec Text
> Missing/unreadable file: stderr message, exit code `1`.

Earlier spec, unrevoked:
> Malformed/empty XML input: stderr message, exit code `1`.

### Alternatives
1. An existing but empty file is read successfully, then fails the empty-document
   check from the earlier spec.
2. An empty file counts as "unreadable" and takes the file-error path.

### Choice
Alternative 1. Opening and reading it succeeded, so the failure belongs to the
document, not to the file. Both paths exit `1` and write to stderr, so only the
message differs.

### Risk: 5
Author most likely prefers: exit `1` either way, which is the only thing a fixture is
likely to assert.

## T26 (annotation, json/union spec)

The "mixed node/string result set" case this entry had to guess at is now
governed by an explicit rule: *"A union with mixed result types is written as
text results."* The branch question is settled — a mixed union no longer routes
to the XML branch at all — which retires alternative 2 entirely. The `--first`
truncation chosen here is unchanged and still happens before rendering, so a
`--first` mixed union collapses to a single item and is rendered by whichever
kind survives. See T42 for what "written as text results" does to the element
members.

---

## T36 — What `--compact` "zero-indent JSON layout" produces

### Spec Text
> - Default JSON formatting: 2-space indent.
> - With `--compact`, produce zero-indent JSON layout (no leading whitespace).

### Alternatives
1. **`json.dumps(items, indent=0)`** — still one token per line, but every line
   starts at column zero: `[\n{\n"title": "x"\n}\n]`.
2. **Single-line JSON** — `json.dumps(items)`, i.e. `[{"title": "x"}]`, the usual
   meaning of "compact JSON".
3. **Single line with no spaces at all** — `separators=(",", ":")`.

### Choice
Alternative 1. The spec names the *indent* and only the indent: "2-space indent"
becomes "zero-indent", which is the same knob turned to `0`, and the parenthetical
"(no leading whitespace)" describes exactly what `indent=0` changes — the leading
whitespace on each line — rather than the line breaks. A one-line rendering would
have been described as "single line" or "no whitespace"; "layout" and "leading"
both point at a multi-line shape whose lines are flush left. It also matches how
`--compact` is specified for XML elsewhere in this tool: it strips added
formatting, it does not re-encode.

### Risk: 35
Author most likely prefers: `json.dumps(items, indent=0)` (same as chosen); the
live risk is an author who reached for the idiomatic `json.dumps(items)` one-liner
and wrote `[{"title": "x"}]` into the fixture.

---

## T37 — Whether JSON export output ends with a trailing newline

### Spec Text
> - Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> - Default JSON formatting: 2-space indent.

### Alternatives
1. **No trailing newline** — the exact `json.dumps` string is written to stdout.
2. **Trailing newline** — the output is `print`ed, so a `\n` terminates it (and
   plausibly only in the non-`--compact` case, mirroring how pretty-printed XML
   here ends with a newline while compact XML does not).

### Choice
Alternative 1. Every byte this tool writes is already produced by an explicit
`stdout.buffer.write` of an exactly-computed payload, with no newline appended by
the output layer; text results are joined with `\n` and deliberately not
terminated by one (the earlier spec's contract, locked in by T29 for `--compact`).
Adding a terminator for one new output mode would make JSON the only mode with a
different convention, and the spec says nothing that would justify it.

### Risk: 40
Author most likely prefers: a trailing newline, if their export path is a plain
`print(json.dumps(...))` — by far the most common way to write this — in which
case every JSON fixture ends with `\n`.

---

## T38 — Whether non-ASCII text is escaped in the exported JSON

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. **`ensure_ascii=True`** (the `json.dumps` default): `<a>café</a>` exports as
   `{"a": "café"}`.
2. **`ensure_ascii=False`**: the literal `{"a": "café"}`, UTF-8 encoded.

### Choice
Alternative 1. The spec fixes the *shape* of the export and the *indent*, and says
nothing about encoding, so the default serializer behaviour is what an
implementation gets for free; `ensure_ascii=False` is an opt-in that the prose
never asks for. Both forms decode to the same string, so this is only observable
in a byte-exact fixture.

### Risk: 25
Author most likely prefers: the same bare `json.dumps` default; the risk is an
author who passes `ensure_ascii=False` as a habit and has a non-ASCII fixture.

---

## T39 — What "immediate text content" is, and whether it is normalized

### Spec Text
> - Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> - Use immediate text only (exclude descendant text from child elements).

### Alternatives
1. **All direct text-node children, normalized**: `element.text` plus each child's
   `tail`, joined, then stripped with internal whitespace runs collapsed. For
   `<p>Hello <b>b</b> world</p>` this is `Hello world`; for a pretty-printed
   `<book>` whose content is only child elements it is `""`.
2. **All direct text-node children, raw**: the same concatenation with no
   stripping, so an indented `<book>` exports `"\n    \n    \n  "`.
3. **`element.text` only**, stripped: `Hello` for the mixed-content example.

### Choice
Alternative 1. The "immediate text" notion is the same one `--text` already uses
in this tool, and T9 settled that as the whole `el/text()` node-set rather than
just its first member — a child's tail is text belonging to the parent, not
"descendant text from child elements", which is precisely what the spec's
parenthetical excludes. Normalization follows the tool's standing rule that every
emitted result is stripped and whitespace-collapsed; without it the headline case
(exporting `//book` from an indented document) would produce JSON full of
indentation, which no reading of an "export" format wants.

### Risk: 25
Author most likely prefers: `(el.text or "").strip()` — alternative 3 — which
agrees with this choice on every leaf element and differs only on mixed content.

---

## T40 — `--json` when nothing matched

### Spec Text
> - Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> - `--json` has no effect when results are already auto-detected as text.

### Alternatives
1. **Empty output** — an empty result set has no elements to export, so the
   element branch is never entered and the existing "no results, write nothing"
   behaviour stands.
2. **`[]`** — the export shape is an array, so an empty match is the empty array.

### Choice
Alternative 1. The tool's output contract already begins with "an empty result
prints nothing", for text, attribute and node results alike, and `--json` is
introduced as a formatting mode *for XML element results* — with no element
results there is nothing for it to format. Printing `[]` would make `--json` the
only flag that turns a silent no-match into output.

### Risk: 40
Author most likely prefers: `[]`, if their implementation builds the list first
and serializes unconditionally (`json.dumps([export(e) for e in elements])`),
which is the natural shape and yields `[]` for free.

---

## T41 — Whether `--json` exports every match or only the first

### Spec Text
> - Export shape: JSON array of objects `{tag_name: immediate_text_content}`.
> - With `--first`, still return a JSON array containing one exported element.

Earlier spec, for the default node branch:
> when multiple XML nodes match, output only the first node.

### Alternatives
1. **All matched elements**, one object each; `--first` narrows it to one.
2. **Only the first element** even without `--first`, carrying the earlier
   node-output rule into JSON mode, which would make the `--first` bullet vacuous.

### Choice
Alternative 1. A "JSON array of objects" is plural by construction, and the
`--first` bullet only says something if the array is otherwise longer than one —
its point is that `--first` does not degrade the array into a bare object.

### Risk: 8
Author most likely prefers: the same; the residual risk is an implementation that
applies the first-node rule before the JSON branch.

---

## T42 — What "written as text results" does to the element members of a mixed union

### Spec Text
> A union with mixed result types is written as text results.

### Alternatives
1. **Each element contributes its descendant text** (its XPath string-value),
   normalized, one result per line — the same rendering `--text-all` would give.
2. **Each element contributes its direct text only** (the `--text` rendering).
3. **Each element contributes its serialized XML**, inlined among the text lines.

### Choice
Alternative 1. "Written as text results" says the whole result set is routed
through the text output branch, and the text of a node in XPath 1.0 is its
string-value — `string(.)`, every descendant text node joined. That is also the
only choice that makes the rule useful: `//a/text() | //b` then prints the text of
every match uniformly, which is evidently the point of overriding the
"first node wins" branch. Alternative 3 mixes two serializations in one stream and
alternative 2 silently drops content from any element with children.

### Risk: 35
Author most likely prefers: descendant/string-value text (same as chosen); the
plausible divergence is an implementation that reuses its `--text` helper here and
prints direct text only, which differs on any element with element children.

---

## T43 — How a union query is detected

### Spec Text
> - Support XPath `|` union in XPath mode.
> - For XPath union queries with active `--text-all`, concatenate descendant text
>   across all union matches into one normalized output string.

### Context
The concatenation rule is stated *for union queries only*, so an implementation
must decide, before rendering, whether `QUERY` is a union — `--text-all` over the
non-union `//book` still prints one line per element.

### Alternatives
1. **Split `QUERY` on top-level `|`**, ignoring pipes inside quotes, parentheses
   and predicates; a union is a query that splits into two or more parts.
2. **Substring test** — `"|" in query`.
3. **No detection**: treat every `--text-all` run as a concatenation, on the theory
   that the union clause is just where the author happened to describe it.

### Choice
Alternative 1. The spec attaches the rule to "union queries" explicitly and
contrasts them with the per-element behaviour defined earlier, so detection is
required; and a real top-level split is the only detection that does not
misclassify `//a[@x="p|q"]` or `//a[contains(., "|")]` as unions. Alternative 3
would silently rewrite the already-specified non-union `--text-all` output.

### Risk: 20
Author most likely prefers: a plain `"|" in query` check (alternative 2), which
agrees with this choice except on a pipe hidden inside a predicate or a string
literal — an unlikely fixture.

---

## T44 — What joins the concatenated union text

### Spec Text
> For XPath union queries with active `--text-all`, concatenate descendant text
> across all union matches into one normalized output string.

### Alternatives
1. **Join with a single space**, then normalize: `//title | //author` over the
   catalog gives `XPath Basics Ada XPath Avance Remy`.
2. **Join with nothing**, then normalize: `XPath BasicsAdaXPath AvanceRemy`.
3. **Join with a newline** — but that is "one output string" only in the trivial
   sense and is indistinguishable from the per-element behaviour it replaces.

### Choice
Alternative 1. The rule exists to replace the one-line-per-element default with a
single line, and the word "normalized" tells us the result is put through the
tool's strip-and-collapse pass — a pass that is only meaningful if the joined
parts are whitespace-separated in the first place. A bare `"".join` welds the last
word of one match onto the first word of the next, producing tokens that appear in
no source text; that is not a "normalized output string", it is a corrupted one.
Alternative 3 contradicts "one … string".

### Risk: 35
Author most likely prefers: space-joining (same as chosen); the risk is a literal
`"".join(...)` implementation whose fixture bakes in the welded form.

---

## T45 — Which union sub-paths count as "already performing text extraction"

### Spec Text
> If any union sub-path already performs text extraction, text flags are treated
> as no-op query modifiers.

### Alternatives
1. **A sub-path whose final step is a `text()` node test** (allowing trailing
   predicates and surrounding whitespace): `//a/text()`, `//a/text()[1]`.
2. **Any sub-path containing the substring `text()`**, which also catches
   `//a[contains(text(), "x")]` — a query that returns elements, not text.
3. **Result-driven**: any non-element in the union result means the flags are off.

### Choice
Alternative 1. "Performs text extraction" describes what the sub-path *returns*,
and a sub-path returns text exactly when its last step selects text nodes; a
`text()` call buried in a predicate is a filter, not an extraction, and T13
already rejected the substring heuristic for the same reason. Alternative 3 would
also disable the flags for `//a/@id | //b`, where attributes — not text
extraction — are the non-element members, and the spec's own `--text` bullet wants
the flags live across such unions.

### Risk: 25
Author most likely prefers: the substring test (alternative 2), which is the
one-liner the sentence invites; it differs only when `text()` appears inside a
predicate of a union sub-path.

---

## T46 — Whether `--text` also concatenates across a union

### Spec Text
> - `--text` and `--text-all` apply across union queries.
> - For XPath union queries with active `--text-all`, concatenate descendant text
>   across all union matches into one normalized output string.

### Alternatives
1. **Only `--text-all` concatenates.** `--text` keeps its defined one-line-per-
   element output across the union's matches.
2. **Both concatenate**, reading the second bullet as an example of a general
   union rule.

### Choice
Alternative 1. The two bullets are deliberately different: the first names both
flags and says only that they *apply* across a union; the second names only
`--text-all` and is the one that changes the output shape. Had concatenation been
intended for both, the second bullet would have reused the pairing of the first.

### Risk: 20
Author most likely prefers: the same split; the risk is an implementation with one
union branch that both flags fall into.

---

## T47 — A CSS selector with `|` that parses but cannot be evaluated

### Spec Text
> In CSS mode, pass `|` through as CSS query text (no XPath union semantics).
> If the CSS engine rejects the selector, report a CSS selector error on stderr
> with exit code `1`.

### Context
In CSS, `|` is the namespace separator. `a | b` (spaced) is a syntax error the
parser rejects outright, but `a|b` parses happily into "element `b` in namespace
prefix `a`" and only fails later, when the translated XPath is evaluated against a
document that has no such prefix.

### Alternatives
1. **Both failures are CSS selector errors**: a selector that cannot be carried
   through to a result reports the CSS error and exits `1`, whether it died in the
   parser, in the translator, or on evaluation of the translated expression.
2. **Only parser/translator failures are CSS errors**; `a|b` surfaces the
   underlying XPath engine complaint ("Undefined namespace prefix") instead.
3. `a|b` matches nothing and exits `0`.

### Choice
Alternative 1. The spec's sentence is written about exactly this bullet — the `|`
case — and demands a *CSS* selector error, so the user must not be shown an XPath
diagnostic for a query they wrote in CSS; in `--css` mode the XPath expression is
an internal artefact the user never typed. This also extends T15's single-error-
class decision: every CSS query the tool cannot turn into a result is one failure
mode. Alternative 3 hides a real user error behind silence.

### Risk: 30
Author most likely prefers: exit `1` from the parser for the spaced `a | b` (which
every reading agrees on) and, for the unspaced `a|b`, whatever their engine
happens to raise — quite possibly an XPath-worded message, or even a silent empty
result if their translator resolves unknown prefixes to no-match.

---

## T48 — What "already auto-detected as text" excludes from `--json`

### Spec Text
> `--json` has no effect when results are already auto-detected as text
> (e.g. text()/attribute outputs).

### Alternatives
1. **`--json` applies only when every result is an element.** Strings, numbers,
   booleans and attribute values are text; a result set containing any of them is
   a text result and `--json` is inert — which lines up with the union rule that
   a mixed result set "is written as text results".
2. **`--json` applies whenever at least one element is present**, exporting the
   element members and dropping the rest.

### Choice
Alternative 1. The precedence list puts `--json` above only the default
auto-format, and the note says the auto-detection wins whenever it lands on text.
The union section independently declares mixed result sets to be text results, so
a mixed set is "already auto-detected as text" by the spec's own words and
`--json` cannot reach it. Alternative 2 would also silently discard results, which
no bullet authorizes.

### Risk: 15
Author most likely prefers: the same all-elements gate; the risk is an
implementation that filters to elements first and exports whatever it finds.

---

## T49 — The exported `tag_name` for a namespaced element

### Spec Text
> Export shape: JSON array of objects `{tag_name: immediate_text_content}`.

### Alternatives
1. **`element.tag` verbatim**, which for a namespaced element is lxml's
   `{http://example.com/ns}title` Clark notation.
2. **The local name only**, `title`.

### Choice
Alternative 1. "Tag name" is the element's tag as the parser reports it, and
keeping the namespace makes the export lossless and unambiguous when two
namespaces share a local name. Stripping it would be an extra, unstated
transformation.

### Risk: 15
Author most likely prefers: the same verbatim tag, since it is what `el.tag`
gives for free; the risk is a fixture built on `QName(el).localname`.

---
