# xjq — XPath and CSS querying of XML from stdin

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

Reads an XML document from stdin, evaluates `QUERY` against it, and prints the
result. `INFILE` is accepted for call-site compatibility and is never read.

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
