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
