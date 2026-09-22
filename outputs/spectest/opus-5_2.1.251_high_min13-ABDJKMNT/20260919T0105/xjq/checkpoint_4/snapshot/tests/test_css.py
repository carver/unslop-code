"""CSS selector query mode.

Spec section: "## CSS Query Mode", plus the `--css` entry under
"## CLI Additions".
"""

import textwrap

MIXED = "<r><div>Hello <b>World</b>!</div></r>"


# Spec: "`--css`: interpret `QUERY` as CSS selector."
# Context: with the flag, a bare tag name selects elements anywhere in the
# document the way a CSS selector does.
def test_css_flag_selects_by_tag_name(run_xjq):
    result = run_xjq("--css", "item", stdin="<r><wrap><item>x</item></wrap></r>")
    assert result.returncode == 0
    assert result.stdout.strip() == "<item>x</item>"


# Spec: "`--css`: interpret `QUERY` as CSS selector."
# Context: class, id, attribute and descendant syntax are all CSS, not XPath.
def test_css_flag_supports_css_syntax(run_xjq):
    doc = "<r><p class='hit'>a</p><p id='two'>b</p><q href='u'>c</q></r>"
    assert run_xjq("--css", "p.hit", stdin=doc).stdout.strip() == '<p class="hit">a</p>'
    assert run_xjq("--css", "#two", stdin=doc).stdout.strip() == '<p id="two">b</p>'
    assert run_xjq("--css", "q[href]", stdin=doc).stdout.strip() == '<q href="u">c</q>'
    assert run_xjq("--css", "r p", stdin=doc).stdout.strip() == '<p class="hit">a</p>'


# Spec: "`--css`: interpret `QUERY` as CSS selector."
# Context: without the flag the same argument is still an XPath expression, so
# CSS-only syntax is rejected as a bad XPath.
def test_css_syntax_without_the_flag_stays_xpath(run_xjq):
    result = run_xjq(".item", stdin="<r><item>x</item></r>")
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "`--css`: interpret `QUERY` as CSS selector."
# Context: element matching stays case sensitive in CSS mode, as the base spec
# requires of the tool as a whole.
def test_css_element_matching_is_case_sensitive(run_xjq):
    doc = "<Root><Item>x</Item></Root>"
    assert run_xjq("--css", "Item", stdin=doc).stdout.strip() == "<Item>x</Item>"
    assert run_xjq("--css", "item", stdin=doc).stdout == ""


# Spec: "`selector::text` returns direct text"
# Context: the custom pseudo-element extracts the matched element's own text.
def test_direct_text_pseudo_element(run_xjq):
    result = run_xjq("--css", "div::text", stdin="<r><div>plain</div></r>")
    assert result.returncode == 0
    assert result.stdout == "plain\n"


# Spec: "`selector::text` returns direct text"
# Context: text held by a child element is not direct text of the match.
def test_direct_text_excludes_child_text(run_xjq):
    result = run_xjq("--css", "div::text", stdin=MIXED)
    assert result.returncode == 0
    assert "World" not in result.stdout


# Spec: "`selector::text` returns direct text"
# Context: the direct text nodes on either side of a child element are each a
# result of their own. See AMBIGUITIES.md T12.
def test_direct_text_yields_one_line_per_text_node(run_xjq):
    result = run_xjq("--css", "div::text", stdin=MIXED)
    assert result.lines == ["Hello", "!"]


# Spec: "`selector ::text` returns all descendant text nodes
#        (one text node per line)"
# Context: the space before `::text` switches to descendant extraction, which
# includes the element's own text and every descendant's.
def test_descendant_text_pseudo_element(run_xjq):
    result = run_xjq("--css", "div ::text", stdin=MIXED)
    assert result.returncode == 0
    assert result.lines == ["Hello", "World", "!"]


# Spec: "`selector ::text` returns all descendant text nodes
#        (one text node per line)"
# Context: text several levels down is still reached.
def test_descendant_text_reaches_deep_nodes(run_xjq):
    doc = "<r><div><p><em>deep</em></p></div></r>"
    result = run_xjq("--css", "div ::text", stdin=doc)
    assert result.stdout == "deep\n"


# Spec: "`selector::text` ... `selector ::text` ..."
# Context: the two modes differ only by the whitespace, and disagree whenever a
# match has element children.
def test_direct_and_descendant_modes_differ(run_xjq):
    doc = "<r><div>own<b>child</b></div></r>"
    assert run_xjq("--css", "div::text", stdin=doc).lines == ["own"]
    assert run_xjq("--css", "div ::text", stdin=doc).lines == ["own", "child"]


# Spec: "Comma-separated selectors are supported for `::text` queries when all
#        selectors use the same `::text` mode."
# Context: two direct-mode selectors, results in document order.
def test_comma_separated_direct_text(run_xjq):
    doc = "<r><a>one</a><b>two</b></r>"
    result = run_xjq("--css", "a::text, b::text", stdin=doc)
    assert result.returncode == 0
    assert result.lines == ["one", "two"]


# Spec: "Comma-separated selectors are supported for `::text` queries when all
#        selectors use the same `::text` mode."
# Context: two descendant-mode selectors are equally fine.
def test_comma_separated_descendant_text(run_xjq):
    doc = "<r><a>one<i>deep</i></a><b>two</b></r>"
    result = run_xjq("--css", "a ::text, b ::text", stdin=doc)
    assert result.returncode == 0
    assert result.lines == ["one", "deep", "two"]


# Spec: "Comma-separated selectors are supported ..."
# Context: a comma list without any `::text` is an ordinary selector union.
def test_comma_separated_selectors_without_text(run_xjq):
    doc = "<r><b>bee</b><a>ay</a></r>"
    result = run_xjq("--css", "a, b", stdin=doc)
    assert result.returncode == 0
    assert result.stdout.strip() == "<b>bee</b>"


# Spec: "Mixing direct and descendant `::text` modes in one comma-separated CSS
#        query is invalid (stderr message, exit code `1`)."
# Context: one selector of each mode in the same query.
def test_mixed_text_modes_are_invalid(run_xjq):
    result = run_xjq("--css", "a::text, b ::text", stdin="<r><a>x</a><b>y</b></r>")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Spec: "Mixing direct and descendant `::text` modes ... is invalid"
# Context: the message names the query language that was rejected.
# See AMBIGUITIES.md T17.
def test_mixed_text_mode_message_references_css(run_xjq):
    result = run_xjq("--css", "a ::text, b::text", stdin="<r><a>x</a><b>y</b></r>")
    assert "css" in result.stderr.lower()


# Spec: "... when all selectors use the same `::text` mode."
# Context: a comma list where only some selectors carry `::text` does not have
# one shared mode either. See AMBIGUITIES.md T13.
def test_partial_text_mode_is_invalid(run_xjq):
    result = run_xjq("--css", "a::text, b", stdin="<r><a>x</a><b>y</b></r>")
    assert result.returncode == 1
    assert result.stderr != ""


# Spec: "In CSS mode without text extraction, return XML node output with
#        pretty-print serialization."
# Context: a match with children is serialized and indented, not flattened to
# its text.
def test_css_element_output_is_pretty_printed(run_xjq):
    result = run_xjq("--css", "a", stdin="<r><a><b>1</b><c>2</c></a></r>")
    expected = textwrap.dedent(
        """\
        <a>
          <b>1</b>
          <c>2</c>
        </a>"""
    )
    assert result.stdout.strip() == expected


# Spec: "In CSS mode without text extraction, return XML node output ..."
# Context: several matches follow the base spec's XML node rule and only the
# first is printed. See AMBIGUITIES.md T14.
def test_css_multiple_matches_output_first_node(run_xjq):
    doc = "<r><a>one</a><a>two</a><a>three</a></r>"
    result = run_xjq("--css", "a", stdin=doc)
    assert result.returncode == 0
    assert result.stdout.strip() == "<a>one</a>"


# Spec: "In CSS mode without text extraction, ..."
# Context: a CSS selector that matches nothing is still a success with no
# output, as in XPath mode.
def test_css_no_match_is_silent_success(run_xjq):
    result = run_xjq("--css", "missing", stdin="<r><a>x</a></r>")
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: a dangling combinator cannot be parsed as a selector.
def test_invalid_css_selector_exits_one(run_xjq):
    result = run_xjq("--css", "div >", stdin="<r><div>x</div></r>")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: the message names CSS. See AMBIGUITIES.md T17.
def test_invalid_css_message_references_css(run_xjq):
    result = run_xjq("--css", "div >", stdin="<r><div>x</div></r>")
    assert "css" in result.stderr.lower()


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: an XPath expression is not a CSS selector.
def test_xpath_under_css_flag_is_invalid(run_xjq):
    result = run_xjq("--css", "//div", stdin="<r><div>x</div></r>")
    assert result.returncode == 1
    assert "css" in result.stderr.lower()


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: `::text` is the only pseudo-element this tool defines; others are
# rejected rather than silently ignored.
def test_unknown_pseudo_element_is_invalid(run_xjq):
    result = run_xjq("--css", "div::before", stdin="<r><div>x</div></r>")
    assert result.returncode == 1
    assert "css" in result.stderr.lower()


# Spec: "Invalid CSS selector: stderr message, exit code `1`."
# Context: an empty selector has nothing to parse.
def test_empty_css_selector_is_invalid(run_xjq):
    result = run_xjq("--css", "", stdin="<r><div>x</div></r>")
    assert result.returncode == 1
    assert "css" in result.stderr.lower()
