# xjq

Evaluate an XPath 1.0 expression or a CSS selector against a document read from
stdin. The document is XML, or JSON that is converted to XML first.

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

`QUERY` is the XPath expression, or a CSS selector under `--css`. `INFILE` is
accepted for compatibility but never read — the document always comes from
stdin.

## Options

| Option | Effect |
| --- | --- |
| `--css` | interpret `QUERY` as a CSS selector |
| `-t`, `--text` | print the direct text of each matched element |
| `--text-all` | print the descendant text of each matched element |

`--text-all` beats `--text` when both are given. Both are no-ops for a query
that already yields text, such as `//title/text()` or `p::text`.

## Output

- Text, attribute and scalar results are stripped, their internal whitespace
  collapsed, and printed one per line.
- A node set of elements is pretty-printed as XML, first node only.
- No matches means no output and exit code 0.
- A bad query, unparseable input or an unusable JSON key exits 1 with a message
  on stderr.

## JSON input

A top-level JSON object or array on stdin is detected without a flag and
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
| `xjq_core/document.py` | Parsing stdin into a document element |
| `xjq_core/json_input.py` | JSON detection and conversion to XML |
| `xjq_core/css.py` | CSS-to-XPath translation, including `::text` |
| `xjq_core/query.py` | XPath 1.0 evaluation |
| `xjq_core/text.py` | Direct and descendant text extraction |
| `xjq_core/render.py` | Rendering results as text or pretty-printed XML |
| `xjq_core/errors.py` | Errors that map to exit code 1 |

Interpretation decisions are recorded in `AMBIGUITIES.md`.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
