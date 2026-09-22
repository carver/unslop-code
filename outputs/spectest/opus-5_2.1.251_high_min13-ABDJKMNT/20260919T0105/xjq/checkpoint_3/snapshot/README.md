# xjq — XPath and CSS querying of XML or JSON from stdin

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

Reads a document from stdin, evaluates `QUERY` against it, and prints the
result. Stdin may be XML/HTML or JSON; the two are told apart automatically.
`INFILE` is accepted for call-site compatibility and is never read.

## Options

| Flag | Effect |
| --- | --- |
| `--css` | interpret `QUERY` as a CSS selector instead of XPath 1.0 |
| `-t`, `--text` | extract the direct text of each matched element |
| `--text-all` | extract the descendant text of each matched element |

`--text-all` wins when both text flags are given. Both are no-ops when the
query already returns text, as `//a/text()` and `div::text` do.

## Output

- Text and attribute results are stripped, whitespace-collapsed, and printed
  one per line.
- Element results are pretty-printed XML; when several match, only the first is
  printed.
- No matches means no output, exit `0`.
- A bad expression, a bad selector, or unparseable input writes a message to
  stderr and exits `1`.

## JSON input

Stdin that decodes to a JSON object or array is converted to XML before the
query runs, so the same XPath and CSS machinery works on it. Top-level JSON
primitives are not JSON input for this purpose; they, and anything that fails
to decode, go to the XML parser.

```
$ echo '{"user": {"name": "ada", "ids": [1, 2]}}' | python xjq.py //name/text()
ada
```

The converted document is wrapped in `<root>`, which carries no attributes.
Below it:

- object keys become element tag names, case and order preserved;
- array entries become `<item>` elements;
- every element records its JSON kind in `type`, one of `str`, `int`, `float`,
  `bool`, `dict`, `list`, `null`;
- primitives become element text — booleans as `true`/`false`, numbers in their
  minimal form (`1.0` → `1`, `1.50` → `1.5`), null as no text at all.

A key that is not a valid XML element name is invalid input: a message on
stderr and exit `1`.

## CSS mode

`--css` adds a custom `::text` pseudo-element:

```
div.post::text     # the direct text nodes of each matched element
div.post ::text    # every descendant text node, one per line
```

Comma-separated selectors are supported, including for `::text` queries, as
long as every selector agrees on one `::text` mode; mixing the direct and
descendant forms is an error.

## Layout

| Path | Role |
| --- | --- |
| `xjq.py` | CLI entry point: argument parsing, wiring, exit codes |
| `xjq_core/parsing.py` | stdin bytes → strict, case-sensitive XML tree |
| `xjq_core/json_input.py` | JSON detection and the JSON-to-XML conversion |
| `xjq_core/css.py` | CSS selector (and `::text`) → XPath expression |
| `xjq_core/query.py` | XPath 1.0 evaluation |
| `xjq_core/extraction.py` | element results → their text nodes, for the text flags |
| `xjq_core/rendering.py` | results → printable text or pretty-printed XML |
| `xjq_core/errors.py` | failure types carrying the user-facing messages |
| `tests/` | spec-phrase-by-phrase tests driving the CLI as a subprocess |

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
was chosen.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
