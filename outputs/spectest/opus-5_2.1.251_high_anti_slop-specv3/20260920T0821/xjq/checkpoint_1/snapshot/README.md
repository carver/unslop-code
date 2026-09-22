# xjq

Query an XML document read from stdin with an XPath 1.0 expression.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Usage

    python xjq.py [OPTIONS] QUERY [INFILE]

`QUERY` is an XPath 1.0 expression. `INFILE` is accepted but ignored — the
document is always read from stdin. Exit code is `0` on success (including
zero matches) and `1` for an invalid expression or unparseable input.

    cat catalog.xml | python xjq.py '//book/@id'      # one value per line
    cat catalog.xml | python xjq.py '//book[@id="2"]' # pretty-printed element

Text, attribute and scalar results are stripped, have internal whitespace runs
collapsed to single spaces, and are joined one per line. When the query matches
elements, the first match is pretty-printed as XML.

## Layout

| File | Responsibility |
| --- | --- |
| `xjq.py` | CLI: argument parsing, wiring, error reporting, exit codes |
| `document.py` | Parsing stdin into a case-sensitive XML tree |
| `query.py` | Evaluating the XPath expression |
| `render.py` | Formatting results for stdout |
| `errors.py` | Exceptions for the two user-facing failure modes |
| `test_xjq.py` | End-to-end tests: `.venv/bin/python -m unittest test_xjq.py` |
