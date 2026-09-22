# xjq — XPath and CSS querying of XML or JSON

```
python xjq.py [OPTIONS] QUERY [INFILE]
```

Reads a document, evaluates `QUERY` against it, and prints the result. The
document may be XML/HTML or JSON; the two are told apart automatically.

## Input

`INFILE` is read when it is named, and stdin otherwise — a file wins over
stdin when both are present. Any further positional arguments are ignored.

A file is decoded as UTF-8 and may start with a byte-order mark. One that is
missing, unreadable, or not UTF-8 gets a message on stderr and exit `1`.

## Options

| Flag | Effect |
| --- | --- |
| `--css` | interpret `QUERY` as a CSS selector instead of XPath 1.0 |
| `-t`, `--text` | extract the direct text of each matched element |
| `--text-all` | extract the descendant text of each matched element |
| `-j`, `--json` | export matched elements as JSON |
| `-f`, `--first` | print only the first result |
| `-c`, `--compact` | serialize XML without added pretty-print formatting |

When several of them ask for different output, `--text-all` wins, then
`--text`, then `--json`, and the automatic choice between text and XML has the
last word.

`--text-all` wins when both text flags are given. Both are no-ops when the
query already returns text, as `//a/text()` and `div::text` do.

`--first` cuts the results after any text extraction, so it always leaves one
line — or one element, which XML output was already limited to. No matches
stays silent.

`--compact` changes XML and JSON serialization only; text and attribute output
is unaffected. It suppresses the indentation the pretty-printer would add, and
leaves whitespace the document itself contains alone. JSON-derived documents,
which carry no whitespace of their own, therefore serialize onto one line.

## Output

- Text and attribute results are stripped, whitespace-collapsed, and printed
  one per line.
- Element results are pretty-printed XML; when several match, only the first is
  printed.
- No matches means no output, exit `0`.
- A bad expression, a bad selector, or unparseable input writes a message to
  stderr and exits `1`.

## JSON export

`--json` turns element results into a JSON array of one-key objects, each
mapping an element's tag name to its immediate text — the text the element
owns itself, with its children's left out and whitespace normalized.

```
$ echo '<feed><post>First</post><post>Second <b>half</b></post></feed>' |
      python xjq.py --json //post
[
  {
    "post": "First"
  },
  {
    "post": "Second"
  }
]
```

`--compact` writes the same array with every line flush left, and `--first`
narrows it to one object without unwrapping the array. The flag has nothing to
say about results that are already text: `text()` and attribute queries, scalar
results, and every query in `--css` mode print as they otherwise would.

## XPath union

XPath's `|` joins several paths into one query, and the matches come back in
document order:

```
$ echo '<r><a>Hello</a><b>World</b></r>' | python xjq.py --text-all '//a|//b'
Hello World
```

`--text` lists the matches' text a node per line as usual, but `--text-all`
over a union concatenates all of it into a single normalized line, which
`--first` narrows to the first matched node. A union whose own paths already
end in `text()` extracts its text itself, and the flags step aside.

In `--css` mode `|` is CSS's namespace separator rather than a union; the CSS
way to ask for two things is the comma list, `a, b`. A selector the CSS engine
cannot use is reported as a selector error with exit `1`.

## JSON input

Input that decodes to a JSON object or array is converted to XML before the
query runs, so the same XPath and CSS machinery works on it. Top-level JSON
primitives are not JSON input for this purpose; they, and anything that fails
to decode, go to the XML parser. Detection works the same way for a file as it
does for stdin, and follows the content rather than the file name.

```
$ echo '{"user": {"name": "ada", "ids": [1, 2]}}' | python xjq.py //name/text()
ada
$ python xjq.py --compact //ids user.json
<ids type="list"><item type="int">1</item><item type="int">2</item></ids>
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
| `xjq_core/source.py` | picking and reading INFILE or stdin |
| `xjq_core/parsing.py` | document bytes → strict, case-sensitive XML tree |
| `xjq_core/json_input.py` | JSON detection and the JSON-to-XML conversion |
| `xjq_core/css.py` | CSS selector (and `::text`) → XPath expression |
| `xjq_core/query.py` | XPath 1.0 evaluation |
| `xjq_core/union.py` | the top-level `\|` structure of an XPath query |
| `xjq_core/extraction.py` | element results → their text, for the text flags |
| `xjq_core/output.py` | which output form the flags ask for |
| `xjq_core/json_export.py` | element results → the JSON array `--json` prints |
| `xjq_core/rendering.py` | results → printable text or serialized XML |
| `xjq_core/errors.py` | failure types carrying the user-facing messages |
| `tests/` | spec-phrase-by-phrase tests driving the CLI as a subprocess |

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
was chosen.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
