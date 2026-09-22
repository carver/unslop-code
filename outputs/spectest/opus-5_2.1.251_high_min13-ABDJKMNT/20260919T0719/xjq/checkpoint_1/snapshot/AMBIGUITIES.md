# Ambiguities

Interpretation decisions taken while implementing the "XPath Querying of XML
from Stdin" spec. Each entry quotes the spec, lists the readings that would
change observable behaviour, and records the chosen reading.

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
