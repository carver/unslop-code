"""Text extraction flags and their interaction with the query.

Spec sections: "## Text Extraction", "## Flag Rules", and the `-t`/`--text`
and `--text-all` entries under "## CLI Additions".
"""

MIXED = "<r><div>Hello <b>World</b>!</div></r>"
INDENTED = "<r>\n  <a>x</a>\n  <a>y</a>\n</r>"


# Spec: "`-t`, `--text`: direct text extraction from matched elements."
# Context: the short flag turns an element match into its own text.
def test_short_text_flag_extracts_direct_text(run_xjq):
    result = run_xjq("-t", "//div", stdin="<r><div>plain</div></r>")
    assert result.returncode == 0
    assert result.stdout == "plain\n"


# Spec: "`-t`, `--text`: direct text extraction from matched elements."
# Context: the long spelling behaves identically.
def test_long_text_flag_extracts_direct_text(run_xjq):
    result = run_xjq("--text", "//div", stdin="<r><div>plain</div></r>")
    assert result.stdout == "plain\n"


# Spec: "`-t`, `--text`: direct text extraction from matched elements."
# Context: text owned by a child element is not direct text.
def test_text_flag_excludes_descendant_text(run_xjq):
    result = run_xjq("-t", "//div", stdin=MIXED)
    assert "World" not in result.stdout
    assert result.lines == ["Hello", "!"]


# Spec: "`--text-all`: descendant text extraction from matched elements."
# Context: descendant extraction picks up the match's own text and every
# descendant's, in document order.
def test_text_all_flag_extracts_descendant_text(run_xjq):
    result = run_xjq("--text-all", "//div", stdin=MIXED)
    assert result.returncode == 0
    assert result.lines == ["Hello", "World", "!"]


# Spec: "`-t`, `--text` ..." / "`--text-all` ..."
# Context: the flags apply to XPath queries too, not only to `--css`.
# See AMBIGUITIES.md T16.
def test_text_flags_apply_to_xpath_queries(run_xjq):
    doc = "<r><a id='1'>one</a><a id='2'>two</a></r>"
    result = run_xjq("-t", "//a[@id='2']", stdin=doc)
    assert result.stdout == "two\n"


# Spec: "`-t`, `--text` ..." combined with "`--css`: interpret `QUERY` as CSS
#        selector."
# Context: the flags are the CSS equivalent of writing `::text`.
def test_text_flag_with_css_selector(run_xjq):
    assert run_xjq("--css", "-t", "div", stdin=MIXED).lines == ["Hello", "!"]
    assert run_xjq("--css", "--text-all", "div", stdin=MIXED).lines == [
        "Hello",
        "World",
        "!",
    ]


# Spec: "`-t`, `--text`: direct text extraction from matched elements."
# Context: an element with no text of its own contributes nothing, and a query
# with no matches stays a silent success.
def test_text_flag_with_nothing_to_extract(run_xjq):
    assert run_xjq("-t", "//a", stdin="<r><a><b>y</b></a></r>").stdout == ""
    assert run_xjq("-t", "//missing", stdin="<r><a>x</a></r>").returncode == 0


# Spec: "Multi-match text output joins lines with `\\n`."
# Context: every matched element contributes its text, one result per line.
def test_multi_match_text_joins_with_newlines(run_xjq):
    doc = "<r><a>one</a><a>two</a><a>three</a></r>"
    result = run_xjq("-t", "//a", stdin=doc)
    assert result.stdout == "one\ntwo\nthree\n"


# Spec: "Multi-match text output joins lines with `\\n`."
# Context: the same holds for a `::text` query in CSS mode.
def test_multi_match_css_text_joins_with_newlines(run_xjq):
    doc = "<r><a>one</a><a>two</a></r>"
    assert run_xjq("--css", "a::text", stdin=doc).stdout == "one\ntwo\n"


# Spec: "Strip each result and collapse internal whitespace runs to single
#        spaces."
# Context: surrounding whitespace is removed from an extracted text node.
def test_extracted_text_is_stripped(run_xjq):
    result = run_xjq("-t", "//a", stdin="<r><a>   padded   </a></r>")
    assert result.stdout == "padded\n"


# Spec: "Strip each result and collapse internal whitespace runs to single
#        spaces."
# Context: newlines and tabs inside a value collapse to one space.
def test_extracted_text_whitespace_collapses(run_xjq):
    doc = "<r><a>first\n\t  second   third</a></r>"
    assert run_xjq("--css", "a::text", stdin=doc).stdout == "first second third\n"


# Spec: "Strip each result and collapse internal whitespace runs to single
#        spaces."
# Context: a text node that is nothing but whitespace strips down to a blank
# line and keeps its place. See AMBIGUITIES.md T19.
def test_whitespace_only_text_nodes_are_kept(run_xjq):
    result = run_xjq("--text-all", "//r", stdin=INDENTED)
    assert result.returncode == 0
    assert result.lines == ["", "x", "", "y", ""]


# Spec: "If both `--text` and `--text-all` are present, `--text-all` wins."
# Context: descendant extraction is used regardless of the flag order.
def test_text_all_wins_over_text(run_xjq):
    assert run_xjq("-t", "--text-all", "//div", stdin=MIXED).lines == [
        "Hello",
        "World",
        "!",
    ]
    assert run_xjq("--text-all", "-t", "//div", stdin=MIXED).lines == [
        "Hello",
        "World",
        "!",
    ]


# Spec: "If query already extracts text (`text()` ...), `--text` and
#        `--text-all` are no-op modifiers."
# Context: an XPath query ending in `text()` is unaffected by either flag.
def test_flags_are_no_ops_for_text_queries(run_xjq):
    doc = "<r><a>one</a><a>two</a></r>"
    plain = run_xjq("//a/text()", stdin=doc).stdout
    assert plain == "one\ntwo\n"
    assert run_xjq("-t", "//a/text()", stdin=doc).stdout == plain
    assert run_xjq("--text-all", "//a/text()", stdin=doc).stdout == plain


# Spec: "If query already extracts text (... `::text`), `--text` and
#        `--text-all` are no-op modifiers."
# Context: a `::text` query keeps its own mode; `--text-all` does not upgrade a
# direct `::text` query to descendant extraction.
def test_flags_are_no_ops_for_css_text_queries(run_xjq):
    assert run_xjq("--css", "-t", "div::text", stdin=MIXED).lines == ["Hello", "!"]
    assert run_xjq("--css", "--text-all", "div::text", stdin=MIXED).lines == [
        "Hello",
        "!",
    ]
    assert run_xjq("--css", "-t", "div ::text", stdin=MIXED).lines == [
        "Hello",
        "World",
        "!",
    ]


# Spec: "If query already extracts text (`text()` or `::text`) ..."
# Context: the rule is about what the query returns, so a query that merely
# mentions `text()` in a predicate still returns elements and is still
# extracted. See AMBIGUITIES.md T15.
def test_text_in_a_predicate_is_not_already_extracted(run_xjq):
    doc = "<r><a>keep</a><a>drop</a></r>"
    result = run_xjq("-t", "//a[text()='keep']", stdin=doc)
    assert result.stdout == "keep\n"


# Spec: "... direct text extraction from matched elements."
# Context: results that are not elements have no text to extract and pass
# through untouched. See AMBIGUITIES.md T18.
def test_flags_leave_attribute_results_alone(run_xjq):
    doc = "<r><a id='1'/><a id='2'/></r>"
    assert run_xjq("-t", "//a/@id", stdin=doc).lines == ["1", "2"]
    assert run_xjq("--text-all", "//a/@id", stdin=doc).lines == ["1", "2"]


# Spec: "`--css`: interpret `QUERY` as CSS selector." + "Invalid CSS selector:
#        stderr message, exit code `1`."
# Context: the text flags do not rescue an unparseable selector.
def test_text_flag_does_not_mask_a_css_error(run_xjq):
    result = run_xjq("--css", "-t", "div >", stdin="<r><div>x</div></r>")
    assert result.returncode == 1
    assert "css" in result.stderr.lower()
