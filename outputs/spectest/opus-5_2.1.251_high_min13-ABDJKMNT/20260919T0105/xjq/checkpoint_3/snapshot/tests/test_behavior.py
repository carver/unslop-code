"""Parsing and evaluation semantics.

Spec section: "## Behavior"
"""


# Spec: "Parse stdin as XML/HTML"
# Context: a plain XML document is parsed and queried.
def test_parses_xml_document(run_xjq):
    result = run_xjq("//name/text()", stdin="<doc><name>Ada</name></doc>")
    assert result.returncode == 0
    assert result.stdout.strip() == "Ada"


# Spec: "Parse stdin as XML/HTML"
# Context: an HTML-shaped document (well formed) is queried with HTML element
# names. See AMBIGUITIES.md T2.
def test_parses_html_shaped_document(run_xjq):
    html = "<html><body><p>hello</p><p>world</p></body></html>"
    result = run_xjq("//p/text()", stdin=html)
    assert result.returncode == 0
    assert result.lines == ["hello", "world"]


# Spec: "Parse stdin as XML/HTML"
# Context: an XML declaration and a non-ASCII payload survive parsing.
def test_respects_encoding_declaration(run_xjq):
    doc = '<?xml version="1.0" encoding="utf-8"?><d><t>café</t></d>'
    result = run_xjq("//t/text()", stdin=doc.encode("utf-8"))
    assert result.returncode == 0
    assert result.stdout.strip() == "café"


# Spec: "using case-sensitive element matching"
# Context: a query whose case differs from the document must not match.
def test_element_matching_is_case_sensitive(run_xjq):
    doc = "<Root><Item>x</Item></Root>"
    assert run_xjq("//item/text()", stdin=doc).stdout == ""
    assert run_xjq("//Item/text()", stdin=doc).stdout.strip() == "x"


# Spec: "using case-sensitive element matching"
# Context: mixed-case tag names in HTML-ish input keep their original case
# rather than being lowercased by an HTML parser.
def test_html_tag_case_is_preserved(run_xjq):
    doc = "<HTML><BODY><P>shout</P></BODY></HTML>"
    assert run_xjq("//P/text()", stdin=doc).stdout.strip() == "shout"
    assert run_xjq("//p/text()", stdin=doc).stdout == ""


# Spec: "using case-sensitive element matching"
# Context: attribute names are likewise matched case sensitively.
def test_attribute_matching_is_case_sensitive(run_xjq):
    doc = '<r><n Id="7"/></r>'
    assert run_xjq("//n/@Id", stdin=doc).stdout.strip() == "7"
    assert run_xjq("//n/@id", stdin=doc).stdout == ""


# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: core XPath 1.0 predicates and axes are supported.
def test_supports_predicates_and_axes(run_xjq):
    doc = "<r><a id='1'>one</a><a id='2'>two</a><b>three</b></r>"
    assert run_xjq("//a[@id='2']/text()", stdin=doc).stdout.strip() == "two"
    assert run_xjq("//b/preceding-sibling::a[1]/text()", stdin=doc).stdout.strip() == "two"


# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: XPath 1.0 string functions evaluate to text output.
def test_supports_string_functions(run_xjq):
    doc = "<r><a>hello world</a></r>"
    result = run_xjq("substring-before(//a/text(), ' ')", stdin=doc)
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: a numeric result is rendered with XPath 1.0 string conversion, so an
# integral number carries no ".0" suffix. See AMBIGUITIES.md T3.
def test_numeric_result_uses_xpath_string_conversion(run_xjq):
    doc = "<r><i/><i/><i/></r>"
    result = run_xjq("count(//i)", stdin=doc)
    assert result.returncode == 0
    assert result.stdout.strip() == "3"


# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: a boolean result uses XPath's lowercase spelling.
# See AMBIGUITIES.md T3.
def test_boolean_result_uses_xpath_spelling(run_xjq):
    doc = "<r><i/></r>"
    assert run_xjq("boolean(//i)", stdin=doc).stdout.strip() == "true"
    assert run_xjq("boolean(//z)", stdin=doc).stdout.strip() == "false"


# Spec: "Evaluate `QUERY` with XPath 1.0."
# Context: XPath 2.0-only constructs are not available in a 1.0 engine and are
# reported as invalid expressions.
def test_xpath_2_constructs_are_rejected(run_xjq):
    result = run_xjq("//a[matches(., 'x')]", stdin="<r><a>x</a></r>")
    assert result.returncode == 1


# Spec: "Exit code `0` on successful execution, including zero matches."
# Context: a query that matches nothing is still a success.
def test_zero_matches_exits_zero(run_xjq):
    result = run_xjq("//missing", stdin="<r><a>x</a></r>")
    assert result.returncode == 0


# Spec: "Exit code `0` on successful execution, including zero matches."
# Context: successful runs that do produce output also exit 0.
def test_successful_match_exits_zero(run_xjq):
    result = run_xjq("//a/text()", stdin="<r><a>x</a></r>")
    assert result.returncode == 0
