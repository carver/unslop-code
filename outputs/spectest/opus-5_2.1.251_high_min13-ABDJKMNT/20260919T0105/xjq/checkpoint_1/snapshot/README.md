# xjq — XPath querying of XML from stdin

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

Reads an XML document from stdin, evaluates `QUERY` as XPath 1.0 against it,
and prints the result. `INFILE` is accepted for call-site compatibility and is
never read.

- Text and attribute results are stripped, whitespace-collapsed, and printed
  one per line.
- Element results are pretty-printed XML; when several match, only the first is
  printed.
- No matches means no output, exit `0`.
- A bad expression or unparseable input writes a message to stderr and exits `1`.

## Layout

| Path | Role |
| --- | --- |
| `xjq.py` | CLI entry point: argument parsing, wiring, exit codes |
| `xjq_core/parsing.py` | stdin bytes → strict, case-sensitive XML tree |
| `xjq_core/query.py` | XPath 1.0 evaluation |
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
