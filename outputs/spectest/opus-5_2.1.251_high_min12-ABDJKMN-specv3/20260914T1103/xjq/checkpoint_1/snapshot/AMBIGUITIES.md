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
