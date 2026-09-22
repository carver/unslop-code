"""Parsing, evaluation, and exit-code behaviour."""

from conftest import BOOKS


# Spec: "Parse stdin as XML/HTML using case-sensitive element matching."
def test_element_matching_is_case_sensitive(run_xjq):
    doc = "<Root><Item>upper</Item><item>lower</item></Root>"
    assert run_xjq("//Item/text()", stdin=doc).stdout == "upper"
    assert run_xjq("//item/text()", stdin=doc).stdout == "lower"


# Spec: "Parse stdin as XML/HTML using case-sensitive element matching." --
# element names keep their original case when serialized, i.e. the input is not
# run through a tag-lowercasing HTML parser.
def test_case_is_preserved_in_serialized_output(run_xjq):
    result = run_xjq("//CamelCase", stdin="<Doc><CamelCase>x</CamelCase></Doc>")
    assert "<CamelCase>" in result.stdout
    assert "<camelcase>" not in result.stdout


# Spec: "Parse stdin as XML/HTML ..." -- HTML markup that is well-formed parses
# and queries like any other document.
def test_html_document_is_queryable(run_xjq):
    html = "<html><body><p class='intro'>Hi</p><p>Bye</p></body></html>"
    assert run_xjq("//p/text()", stdin=html).stdout == "Hi\nBye"
    assert run_xjq("//p/@class", stdin=html).stdout == "intro"


# Spec: "Parse stdin as XML/HTML ..." -- an encoding declaration in the document
# is honoured rather than rejected.
def test_encoding_declaration_is_honoured(run_xjq):
    doc = '<?xml version="1.0" encoding="utf-8"?><r><t>café</t></r>'
    assert run_xjq("//t/text()", stdin=doc).stdout == "café"


# Spec: "Evaluate `QUERY` with XPath 1.0." -- element selection.
def test_evaluates_element_paths(run_xjq):
    result = run_xjq("/library/book/author/text()", stdin=BOOKS)
    assert result.stdout == "Frank Herbert\nVictor Hugo"


# Spec: "Evaluate `QUERY` with XPath 1.0." -- predicates and attribute tests.
def test_evaluates_predicates(run_xjq):
    result = run_xjq("//book[@lang='fr']/title/text()", stdin=BOOKS)
    assert result.stdout == "Les Miserables"


# Spec: "Evaluate `QUERY` with XPath 1.0." -- positional predicates are
# 1-indexed.
def test_evaluates_positional_predicates(run_xjq):
    assert run_xjq("//book[1]/title/text()", stdin=BOOKS).stdout == "Dune"
    assert run_xjq("//book[2]/@id", stdin=BOOKS).stdout == "b2"


# Spec: "Evaluate `QUERY` with XPath 1.0." -- core function library.
def test_evaluates_xpath_functions(run_xjq):
    assert run_xjq("count(//book)", stdin=BOOKS).stdout == "2"
    assert run_xjq("string(//book[1]/title)", stdin=BOOKS).stdout == "Dune"
    assert run_xjq("//title[contains(., 'Dune')]/text()", stdin=BOOKS).stdout == "Dune"


# Spec: "Evaluate `QUERY` with XPath 1.0." -- XPath 2.0-only constructs are not
# available, so they are rejected as invalid expressions.
def test_xpath_2_constructs_are_rejected(run_xjq):
    result = run_xjq("for $b in //book return $b", stdin=BOOKS)
    assert result.returncode == 1


# Spec: "Exit code `0` on successful execution, including zero matches."
def test_exit_zero_on_match(run_xjq):
    assert run_xjq("//book/@id", stdin=BOOKS).returncode == 0


# Spec: "Exit code `0` on successful execution, including zero matches."
def test_exit_zero_on_zero_matches(run_xjq):
    assert run_xjq("//nonexistent", stdin=BOOKS).returncode == 0
    assert run_xjq("//book[@lang='de']/title/text()", stdin=BOOKS).returncode == 0
