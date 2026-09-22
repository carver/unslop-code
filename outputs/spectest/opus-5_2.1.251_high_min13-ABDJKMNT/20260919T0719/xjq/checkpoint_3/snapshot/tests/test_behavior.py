"""Spec section: Behavior.

Parsing of stdin, XPath 1.0 evaluation, and the exit code contract.
"""

from conftest import DOC, HTMLISH_DOC, MIXED_CASE_DOC


# Phrase: "Parse stdin as XML/HTML"
def test_parses_an_xml_document_from_stdin(xjq):
    result = xjq("//author/text()", stdin=DOC)
    assert result.returncode == 0
    assert result.stdout == "Frank Herbert\nAntoine de Saint-Exupery\n"


# Phrase: "Parse stdin as XML/HTML"
def test_parses_an_html_shaped_document(xjq):
    result = xjq("//a/@href", stdin=HTMLISH_DOC)
    assert result.returncode == 0
    assert result.stdout == "/one\n/two\n"


# Phrase: "using case-sensitive element matching"
def test_element_matching_is_case_sensitive(xjq):
    lower = xjq("//item/text()", stdin=MIXED_CASE_DOC)
    upper = xjq("//Item/text()", stdin=MIXED_CASE_DOC)
    assert lower.stdout == "lower\n"
    assert upper.stdout == "upper\n"


# Phrase: "using case-sensitive element matching"
# A query whose case does not match any element yields no output.
def test_wrong_case_query_matches_nothing(xjq):
    result = xjq("//ITEM/text()", stdin=MIXED_CASE_DOC)
    assert result.returncode == 0
    assert result.stdout == ""


# Phrase: "using case-sensitive element matching" (attributes too)
def test_attribute_matching_is_case_sensitive(xjq):
    doc = '<r><n Id="upper" id="lower"/></r>'
    assert xjq("//n/@id", stdin=doc).stdout == "lower\n"
    assert xjq("//n/@Id", stdin=doc).stdout == "upper\n"


# Phrase: "Evaluate QUERY with XPath 1.0." -- predicates
def test_evaluates_predicate_expressions(xjq):
    result = xjq("//book[@lang='fr']/title/text()", stdin=DOC)
    assert result.stdout == "Le Petit Prince\n"


# Phrase: "Evaluate QUERY with XPath 1.0." -- positional predicates are 1-based
def test_evaluates_positional_predicates(xjq):
    result = xjq("//book[1]/title/text()", stdin=DOC)
    assert result.stdout == "Dune\n"


# Phrase: "Evaluate QUERY with XPath 1.0." -- core function library
def test_evaluates_string_functions(xjq):
    result = xjq("string(//book[2]/@id)", stdin=DOC)
    assert result.stdout == "b2\n"


# Phrase: "Evaluate QUERY with XPath 1.0." -- axes
def test_evaluates_axes(xjq):
    result = xjq("//title[1]/following-sibling::author/text()", stdin=DOC)
    assert result.stdout == "Frank Herbert\nAntoine de Saint-Exupery\n"


# Phrase: "Evaluate QUERY with XPath 1.0."
# XPath 2.0+ constructs are not available and are reported as query errors.
def test_xpath_2_constructs_are_rejected(xjq):
    result = xjq("//book/title/lower-case(text())", stdin=DOC)
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Phrase: "Exit code 0 on successful execution"
def test_exit_code_zero_on_success(xjq):
    assert xjq("//book/@id", stdin=DOC).returncode == 0


# Phrase: "Exit code 0 on successful execution, including zero matches."
def test_exit_code_zero_when_nothing_matches(xjq):
    result = xjq("//missing", stdin=DOC)
    assert result.returncode == 0


# Phrase: "Exit code 0 ... including zero matches." (text nodes too)
def test_exit_code_zero_when_no_text_matches(xjq):
    result = xjq("//missing/text()", stdin=DOC)
    assert result.returncode == 0
