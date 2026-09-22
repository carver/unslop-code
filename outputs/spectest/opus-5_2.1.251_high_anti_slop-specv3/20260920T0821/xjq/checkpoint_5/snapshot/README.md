# xjq

Query an XML or JSON document with an XPath 1.0 expression or a CSS selector.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Usage

    python xjq.py [OPTIONS] QUERY [INFILE]

`QUERY` is an XPath 1.0 expression, or a CSS selector with `--css`. The
document is read from `INFILE`, or from stdin when no file is named; any further
positional arguments are ignored. Exit code is `0` on success (including zero
matches) and `1` for an invalid query or unusable input.

    python xjq.py '//book/@id' catalog.xml           # one value per line
    cat catalog.xml | python xjq.py '//book[@id="2"]' # pretty-printed element

Text, attribute and scalar results are stripped, have internal whitespace runs
collapsed to single spaces, and are joined one per line. When the query matches
elements only, the first match is pretty-printed as XML.

## Input file

`INFILE` is read as UTF-8 text and takes precedence over stdin when both are
present; a leading byte order mark is allowed and dropped. The format of a file
is detected exactly as stdin's is, so a `.json` file is converted and queried
like any other JSON input. A file that is missing, unreadable or not valid UTF-8
is reported on stderr with exit code `1`.

## JSON input

The input format is detected from the document itself: a top-level JSON object
or array is converted to XML and then queried like any other document, and
anything else is parsed as XML. A top-level JSON primitive — a bare string,
number, boolean or null — is not JSON input and falls through to the XML
parser.

    echo '{"book": [{"id": 1}, {"id": 2}]}' | python xjq.py '//id/text()'

The conversion wraps the document in `<root>`: an object's keys become direct
children of `<root>`, in their original order and with their case preserved,
and an array's entries each become an `<item>`. Primitives become element text,
with booleans spelled `true` and `false`, null left empty, and numbers written
in their shortest form (`1.0` prints as `1`, `1.50` as `1.5`).

Every element except `<root>` records where it came from in a `type` attribute,
one of `str`, `int`, `float`, `bool`, `dict`, `list` or `null`, so a query can
tell `"1"` from `1` or find every empty value with `//*[@type="null"]`.

    $ echo '{"n": 1.50, "tags": ["x"], "gap": null}' | python xjq.py '/root'
    <root>
      <n type="float">1.5</n>
      <tags type="list">
        <item type="str">x</item>
      </tags>
      <gap type="null"></gap>
    </root>

A JSON key that is not a valid XML element name — one containing a space, or
starting with a digit — cannot become a tag, so the document is rejected with
exit code `1`.

## XPath unions

Paths joined with `|` are matched as one query, and their matches are returned
in document order without duplicates.

    cat catalog.xml | python xjq.py '//book/@id | //title/text()'

The text flags apply across the whole union. Because its paths read parts of one
document rather than separate matches, `--text-all` concatenates the descendant
text of every match into a single normalized line — or of just the first match
when `-f` / `--first` is given as well. A union in which one path already
extracts text, with `text()`, leaves the flags a no-op for all of them.

A union that matched elements alongside attributes or text has no single layout
to print, so all of its matches are written as text.

In `--css` mode a `|` is read as CSS, where it separates a namespace from a tag
name rather than joining selectors. A query names no namespaces, so such a
selector is reported on stderr with exit code `1`, as any other unsupported CSS
is.

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

## Output flags

`-f` / `--first` keeps only the first result, whether the query matched text,
attributes or elements, and prints nothing when it matched none.

    python xjq.py --first '//book/@id' catalog.xml   # just 1

`-j` / `--json` exports matched elements as a JSON array of
`{tag name: text}` objects, using each element's immediate text and leaving out
the text of its children. It applies to element matches only: a result that is
already text — from `text()`, an attribute, or a scalar function — prints as it
normally would, as does every query in `--css` mode. The text flags outrank it,
and `-f` / `--first` exports the first element as a one-entry array.

    $ python xjq.py --json '//title' catalog.xml
    [
      {
        "title": "The Great Book"
      },
      {
        "title": "Second"
      }
    ]

`-c` / `--compact` serializes matched elements without the added pretty-print
indentation and line breaks, and lays out a `--json` export without leading
whitespace. It leaves text and attribute results alone, and applies to
JSON-derived documents just the same.

    $ python xjq.py --compact '//book[@id="2"]' catalog.xml
    <book id="2"><title>Second</title></book>
    $ echo '{"b": 1, "a": 2}' | python xjq.py --compact '/root'
    <root><b type="int">1</b><a type="int">2</a></root>

## Layout

| File | Responsibility |
| --- | --- |
| `xjq.py` | CLI: argument parsing, wiring, error reporting, exit codes |
| `document.py` | Reading the input, detecting its format, parsing it into a tree |
| `json_xml.py` | Converting a JSON document into the XML tree to query |
| `query.py` | Evaluating the XPath expression |
| `css.py` | Translating CSS selectors, and `::text`, into XPath |
| `text.py` | Extracting and normalizing text from matched elements |
| `render.py` | Formatting results for stdout |
| `json_export.py` | Exporting matched elements as JSON |
| `errors.py` | Exceptions for the user-facing failure modes |
| `test_xjq.py` | End-to-end tests: `.venv/bin/python -m unittest test_xjq.py` |
