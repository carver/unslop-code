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
