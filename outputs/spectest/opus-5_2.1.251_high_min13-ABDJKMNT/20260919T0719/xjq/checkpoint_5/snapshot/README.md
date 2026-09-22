# xjq

Evaluate an XPath 1.0 expression or a CSS selector against a document read from
a file or from stdin. The document is XML, or JSON that is converted to XML
first.

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

`QUERY` is the XPath expression, or a CSS selector under `--css`. `INFILE` is
the document to query; stdin is used when it is omitted, and anything written
after `INFILE` is ignored.

## Options

| Option | Effect |
| --- | --- |
| `-f`, `--first` | print only the first result |
| `-c`, `--compact` | serialize XML without added pretty-print formatting |
| `--css` | interpret `QUERY` as a CSS selector |
| `-t`, `--text` | print the direct text of each matched element |
| `--text-all` | print the descendant text of each matched element |
| `-j`, `--json` | export the matched elements as JSON |

When several of these ask for different output, the highest one wins:
`--text-all`, then `--text`, then `--json`, then the default formatting. The
text flags are no-ops for a query that already yields text, such as
`//title/text()` or `p::text`, and `--json` is a no-op for any result that is
already text and for the whole of `--css` mode.

## Output

- Text, attribute and scalar results are stripped, their internal whitespace
  collapsed, and printed one per line.
- A node set of elements is serialized as XML, first node only — pretty-printed
  by default, or as parsed under `--compact`, which changes nothing about text,
  attribute or scalar results.
- `--first` keeps only the first result of any kind, and stays silent when
  there are none.
- No matches means no output and exit code 0.
- A bad query, unreadable file, unparseable input or unusable JSON key exits 1
  with a message on stderr.

## JSON export

`--json` turns a node set of elements into an array of one-key objects, each
mapping an element's tag name to its own text. Text inside a child element is
that child's, not the parent's; the text around it is the parent's.

```
xjq.py --json '//title' < library.xml
```
```json
[
  {
    "title": "Dune"
  },
  {
    "title": "Le Petit Prince"
  }
]
```

`--compact` keeps the layout but indents by zero, and `--first` exports a
single element without unwrapping the array.

## XPath unions

`|` joins location paths, and the text flags reach every sub-path:

```
xjq.py --text-all '//h1 | //footer' < page.xml   # one normalized line
xjq.py --text     '//h1 | //footer' < page.xml   # one line per text node
```

`--text-all` across a union concatenates the matches into a single line, which
`--first` narrows to the first match in document order. A union in which one
sub-path already extracts text — `//h1/text() | //footer` — makes the text
flags no-ops, as it does for any other text query.

In `--css` mode `|` is CSS, where it separates a namespace prefix from a tag
name; a selector the CSS engine rejects exits 1 with a message on stderr.

## Input

The document comes from `INFILE` when one is given and from stdin otherwise. A
file is decoded as UTF-8 and may start with a BOM; a file that is missing or
cannot be read exits 1 with a message on stderr.

## JSON input

A top-level JSON object or array is detected without a flag and
converted to XML before the query runs. Anything else — including a top-level
JSON primitive such as `42` — is parsed as XML.

```
echo '{"title": "Dune", "tags": ["scifi"]}' | xjq.py /root
```
```xml
<root>
  <title type="str">Dune</title>
  <tags type="list">
    <item type="str">scifi</item>
  </tags>
</root>
```

- The document is wrapped in `<root>`, the only element without a `type`.
- Object keys become tag names with their case and order preserved; array
  entries become `<item>` elements.
- Every other element carries `type`: `str`, `int`, `float`, `bool`, `dict`,
  `list` or `null`.
- Primitives become element text — `true`/`false` for booleans, the minimal
  form for numbers (`1.50` is `1.5`), nothing at all for `null`.
- A key that is not a valid XML element name makes the input invalid: exit 1
  with a message on stderr.

## CSS selectors

`--css` translates the selector to XPath, matching element names
case-sensitively. It also understands `::text`, a pseudo-element of this tool's
own:

```
xjq.py --css 'p::text'   < page.xml   # direct text of every <p>
xjq.py --css 'p ::text'  < page.xml   # all text nodes below every <p>
```

Comma-separated selectors are supported as long as every selector in the list
uses the same `::text` mode; mixing modes exits 1.

## Layout

| Path | Role |
| --- | --- |
| `xjq.py` | CLI entry point: arguments, wiring, exit codes |
| `xjq_core/source.py` | Reading the document bytes from a file or stdin |
| `xjq_core/document.py` | Parsing those bytes into a document element |
| `xjq_core/json_input.py` | JSON detection and conversion to XML |
| `xjq_core/css.py` | CSS-to-XPath translation, including `::text` |
| `xjq_core/query.py` | XPath 1.0 evaluation |
| `xjq_core/union.py` | Recognizing a `\|` union and its sub-paths |
| `xjq_core/text.py` | Direct, descendant and immediate text extraction |
| `xjq_core/nodes.py` | Telling the kinds of node-set member apart |
| `xjq_core/render.py` | Rendering results as text or as pretty/compact XML |
| `xjq_core/export.py` | Rendering matched elements as JSON |
| `xjq_core/output.py` | Ranking the output flags and applying the winner |
| `xjq_core/errors.py` | Errors that map to exit code 1 |

Interpretation decisions are recorded in `AMBIGUITIES.md`.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
