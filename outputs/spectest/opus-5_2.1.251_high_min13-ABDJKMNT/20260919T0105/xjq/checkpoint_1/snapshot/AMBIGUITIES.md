# Ambiguities

Numbered record of places where the spec admits more than one conforming
behavior, the interpretation chosen for this implementation, and the risk that
the spec author's own implementation reads it differently.

---

## T1 — Which `[OPTIONS]` exist

### Spec Text
> `python xjq.py [OPTIONS] QUERY [INFILE]`

### Alternatives
1. No options at all beyond the automatic `-h/--help`; the `[OPTIONS]` slot is
   purely a usage-line convention.
2. Invent conventional options (e.g. `--pretty`, `--raw`, `-t/--text`) to make
   the slot meaningful.

### Choice
Alternative 1. The spec never names a single option, and every behavior it
describes (text vs. XML output, error handling) is selected automatically from
the query result, not from a flag. Inventing flags would add untested surface
and could shadow a real flag name with different semantics.

### Risk: 10
The author most likely also ships only `-h/--help`; a hidden test that passes an
undocumented flag is improbable.

---

## T2 — "Parse stdin as XML/HTML": strict XML vs. HTML recovery

### Spec Text
> Parse stdin as XML/HTML using case-sensitive element matching.

and

> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Strict XML parsing only. Well-formed HTML (XHTML-shaped) parses fine as XML,
   which is what "XML/HTML" covers; anything not well-formed is an error.
2. Try XML first, then fall back to a recovering HTML parser.

### Choice
Alternative 1. The two clauses constrain each other: an HTML fallback recovers
from almost any malformed input (`<a><b></a>`, stray `<`, unclosed tags), which
would make the mandated "malformed XML → exit 1" path nearly unreachable. An
HTML parser also lowercases tag names, directly contradicting "case-sensitive
element matching" in the same sentence. Strict XML is the only reading that
satisfies both requirements simultaneously.

### Risk: 25
The author may have wired an HTML fallback for inputs that fail XML parsing
while still erroring on empty input; such a build would accept `<a><b></a>`
instead of exiting 1.

---

## T3 — Non-node-set XPath results (`count()`, `string()`, `boolean()`)

### Spec Text
> Evaluate `QUERY` with XPath 1.0.
> Text/attribute results: strip each result, collapse internal whitespace runs
> to single spaces, then join results with each on a newline.

### Alternatives
1. Convert numbers/booleans using XPath 1.0 string-conversion rules, so
   `count(//item)` prints `3` and `boolean(//x)` prints `true`/`false`.
2. Use Python's `str()` on the raw lxml return value, printing `3.0` and
   `True`/`False`.

### Choice
Alternative 1. The spec names XPath 1.0 as the evaluation semantics, and XPath
1.0 `string()` of the number 3 is `"3"`, of true is `"true"`. Printing `3.0` for
a count is an artifact of lxml returning a Python float, not a property of the
query language the spec cites.

### Risk: 45
The output section only enumerates "text/attribute" and "XML node" results, so
the author may not have special-cased scalars at all; their implementation most
likely prints `3.0` and `True` via a bare `str()`.

---

## T4 — Trailing newline after output

### Spec Text
> ... then join results with each on a newline.

### Alternatives
1. Emit each result on its own line, i.e. a terminating newline after the last
   result (`print()` semantics).
2. Join strictly with `\n` separators and emit no trailing newline.

### Choice
Alternative 1. "each on a newline" describes line-oriented output, and a
trailing newline is the POSIX convention for text on stdout, which matters for
piping into `wc -l`, `grep`, etc.

### Risk: 15
A test comparing raw stdout byte-for-byte against `"a\nb"` would fail; most
fixtures strip or splitlines, so this rarely bites.

---

## T5 — Results that are empty after stripping

### Spec Text
> strip each result, collapse internal whitespace runs to single spaces, then
> join results with each on a newline.

### Alternatives
1. Keep every result positionally, so a whitespace-only text node becomes an
   empty line.
2. Drop results that strip down to the empty string.

### Choice
Alternative 1. The spec describes a straight map-then-join: strip, collapse,
join. It never mentions filtering, and dropping entries would silently change
the result count relative to the node set that XPath returned.

### Risk: 35
Whitespace-only text nodes are common in indented documents (`//root/text()`),
and an author who eyeballed that output may well have added a filter to avoid
blank lines.

---

## T6 — Deciding between "text result" and "XML node result"

### Spec Text
> Text/attribute results: ...
> XML node results: pretty-print serialized XML; when multiple XML nodes match,
> output only the first node.

### Alternatives
1. Classify by the type of the results: element (and comment/PI) nodes take the
   XML path, everything else (lxml smart strings from `text()`/`@attr`, plus
   scalars) takes the text path. For a mixed union, the first item decides.
2. Classify by the query's syntactic shape (e.g. trailing `/text()` or `/@x`).

### Choice
Alternative 1. Result-type dispatch is what the prose describes — it speaks of
"text/attribute results" and "XML node results", i.e. properties of what came
back, not of how the query was spelled. Syntactic classification breaks on
`//node()`, `string(...)`, and unions.

### Risk: 10
Type-based dispatch is the natural lxml implementation; only an exotic mixed
union like `//a|//b/text()` could distinguish the readings.

---

## T7 — What "pretty-print" means for an already-indented document

### Spec Text
> XML node results: pretty-print serialized XML

### Alternatives
1. Serialize with lxml's `pretty_print=True`, which preserves the whitespace
   already present in the source and only adds indentation where a node carries
   none.
2. Re-parse the subtree with blank-text removal first, forcing uniform two-space
   indentation regardless of the source formatting.

### Choice
Alternative 1. "Pretty-print serialized XML" maps directly onto the standard
`tostring(..., pretty_print=True)` call. Re-indenting would also rewrite
significant whitespace in mixed content. The node's tail text is excluded and
the result is stripped so no stray source indentation leaks out.

### Risk: 25
For a nested element selected out of an indented document, option 1 keeps the
source's original (deeper) indentation while option 2 normalizes it; if the
author normalized, the inner lines differ.

---

## T8 — Precedence when both the input and the query are bad

### Spec Text
> Invalid XPath: stderr message, exit code `1`; message should reference
> `xpath`.
> Malformed/empty XML input: stderr message, exit code `1`; message should
> reference `xml`/`parse`.

### Alternatives
1. Read and parse stdin first, so malformed input reports the XML error even if
   the query is also invalid.
2. Compile the query first, so an invalid expression reports the XPath error
   even when stdin is unparseable.

### Choice
Alternative 1. The spec lists the pipeline as parse → evaluate, and the data
must be read before any evaluation can happen. Both orders exit 1, so only the
message text differs.

### Risk: 30
An author who compiles the `XPath` object up front (a common lxml pattern)
would report the xpath error first for this combined input.

---

## T9 — Empty vs. whitespace-only stdin

### Spec Text
> Malformed/empty XML input: stderr message, exit code `1`

### Alternatives
1. Treat input that is empty or contains only whitespace as "empty".
2. Treat only a zero-byte stream as "empty" and let whitespace-only input fall
   through to the parser (which reports it as malformed anyway).

### Choice
Alternative 1. Both end at the same observable place — exit 1 with a message
naming `xml`/`parse` — so the explicit empty check just gives a clearer message
for a whitespace-only stream.

### Risk: 5
Indistinguishable from the outside: the exit code and the required keywords in
the message are identical under both readings.

---

## T10 — The unused `INFILE` argument

### Spec Text
> `INFILE`: accepted positional argument but not used.
> Input source: stdin.

### Alternatives
1. Accept `INFILE` and ignore it entirely — never open it, never check that it
   exists — always reading stdin.
2. Accept it, validate that it exists, but still read stdin.

### Choice
Alternative 1. "Accepted positional argument but not used" is unambiguous about
the file never being touched; validating it would invent a failure mode the
spec does not define.

### Risk: 5
Only a test passing a nonexistent INFILE and expecting a failure would
distinguish these, which would contradict the spec's own wording.

---

## T11 — A single result that is the empty string

### Spec Text
> No-match output: write nothing to stdout/stderr.

### Alternatives
1. Suppress output whenever the joined text is empty, so `string(//missing)`
   (an XPath string result of `""`) writes nothing at all.
2. Treat "no match" as strictly "zero results" and print a bare newline for a
   single empty-string result.

### Choice
Alternative 1. Emitting a lone newline is indistinguishable to a user from a
match with an empty value, and the spec's "write nothing" clause reads as being
about there being nothing to show. Results that merely *include* blanks
alongside content still keep their blank lines (T5); only an entirely empty
rendering is suppressed.

### Risk: 30
An author whose code is `if results: print("\n".join(lines))` — keyed on the
result list rather than the rendered text — would print a single newline here.
