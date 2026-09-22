# xjq

Query an XML document read from stdin with an XPath 1.0 expression or a CSS
selector.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Usage

    python xjq.py [OPTIONS] QUERY [INFILE]

`QUERY` is an XPath 1.0 expression, or a CSS selector with `--css`. `INFILE` is
accepted but ignored — the document is always read from stdin. Exit code is `0`
on success (including zero matches) and `1` for an invalid query or unparseable
input.

    cat catalog.xml | python xjq.py '//book/@id'      # one value per line
    cat catalog.xml | python xjq.py '//book[@id="2"]' # pretty-printed element

Text, attribute and scalar results are stripped, have internal whitespace runs
collapsed to single spaces, and are joined one per line. When the query matches
elements, the first match is pretty-printed as XML.

## CSS selectors

`--css` reads `QUERY` as a CSS selector, matched case-sensitively like the rest
of the document. Matched elements are pretty-printed as XML, exactly as in
XPath mode.

    cat catalog.xml | python xjq.py --css 'book[id="2"] > title'

The `::text` pseudo-element extracts text instead. Written as a suffix it takes
the matched elements' own text; written as a descendant it takes every text node
below them, one per line.

    cat catalog.xml | python xjq.py --css 'title::text'  # direct text
    cat catalog.xml | python xjq.py --css 'book ::text'  # all descendant text

Comma-separated selectors are matched as a group, provided every one of them
uses the same `::text` mode; mixing the two is an error.

## Text extraction flags

`-t` / `--text` prints the direct text of each matched element and `--text-all`
its descendant text, one line per element either way. `--text-all` wins when
both are given, and both are ignored for a query that already extracts text
with `text()` or `::text`.

    cat catalog.xml | python xjq.py --text-all '//book'
    cat catalog.xml | python xjq.py --css --text-all 'book'

## Layout

| File | Responsibility |
| --- | --- |
| `xjq.py` | CLI: argument parsing, wiring, error reporting, exit codes |
| `document.py` | Parsing stdin into a case-sensitive XML tree |
| `query.py` | Evaluating the XPath expression |
| `css.py` | Translating CSS selectors, and `::text`, into XPath |
| `text.py` | Extracting text from matched elements |
| `render.py` | Formatting results for stdout |
| `errors.py` | Exceptions for the user-facing failure modes |
| `test_xjq.py` | End-to-end tests: `.venv/bin/python -m unittest test_xjq.py` |
