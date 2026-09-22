# xjq

Evaluate an XPath 1.0 query against an XML document read from stdin.

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

`QUERY` is the XPath expression. `INFILE` is accepted for compatibility but
never read — the document always comes from stdin.

- Text, attribute and scalar results are stripped, their internal whitespace
  collapsed, and printed one per line.
- A node set of elements is pretty-printed as XML, first node only.
- No matches means no output and exit code 0.
- A bad query or unparseable input exits 1 with a message on stderr.

## Layout

| Path | Role |
| --- | --- |
| `xjq.py` | CLI entry point: arguments, wiring, exit codes |
| `xjq_core/document.py` | Parsing stdin into a document element |
| `xjq_core/query.py` | XPath 1.0 evaluation |
| `xjq_core/render.py` | Rendering results as text or pretty-printed XML |
| `xjq_core/errors.py` | Errors that map to exit code 1 |

Interpretation decisions are recorded in `AMBIGUITIES.md`.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
