"""Spec section: `--first`.

Returning only the first result, across every kind of result the tool renders.
"""

from conftest import CSS_DOC, DOC, JSON_OBJECT


# Phrase: "`-f`, `--first`: return only first result."
def test_first_returns_only_the_first_result(xjq):
    assert xjq("--first", "//title/text()", stdin=DOC).stdout == "Dune\n"


# Phrase: "`-f`, `--first`: return only first result."
# The short spelling is the same flag.
def test_short_first_flag(xjq):
    assert xjq("-f", "//title/text()", stdin=DOC).stdout == "Dune\n"


# Phrase: "`-f`, `--first`: return only first result."
# Without the flag every result is still printed.
def test_without_first_all_results_are_printed(xjq):
    assert xjq("//title/text()", stdin=DOC).stdout == "Dune\nLe Petit Prince\n"


# Phrase: "`--first` applies across text ... results."
def test_first_applies_to_text_results(xjq):
    assert xjq("-f", "//author/text()", stdin=DOC).stdout == "Frank Herbert\n"


# Phrase: "`--first` applies across ... attribute ... results."
def test_first_applies_to_attribute_results(xjq):
    assert xjq("-f", "//book/@id", stdin=DOC).stdout == "b1\n"


# Phrase: "`--first` applies across ... attribute ... results."
def test_first_attribute_result_is_in_document_order(xjq):
    assert xjq("-f", "//book/@lang", stdin=DOC).stdout == "en\n"


# Phrase: "`--first` applies across ... XML-node results."
def test_first_applies_to_xml_node_results(xjq):
    out = xjq("-f", "//book", stdin=DOC).stdout
    assert out.startswith('<book id="b1"')
    assert "Dune" in out
    assert "Le Petit Prince" not in out


# Phrase: "`--first` applies across text, attribute, and XML-node results."
# Text extracted from matched elements is truncated just like any other text.
def test_first_applies_to_extracted_text(xjq):
    assert xjq("-f", "--css", "p::text", stdin=CSS_DOC).stdout == "Hello\n"


# Phrase: "`--first` applies across text ... results."
# JSON-derived documents are no exception.
def test_first_applies_to_json_derived_results(xjq):
    assert xjq("-f", "/root/tags/item/text()", stdin=JSON_OBJECT).stdout == "scifi\n"


# Phrase: "`--first` with no matches remains silent (no output)."
def test_first_with_no_matches_is_silent(xjq):
    result = xjq("-f", "//nonexistent", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Phrase: "`--first` with no matches remains silent (no output)."
# The same holds for an attribute query that matches nothing.
def test_first_with_no_attribute_matches_is_silent(xjq):
    result = xjq("--first", "//book/@missing", stdin=DOC)
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.returncode == 0


# Phrase: "`--first` ..." -- a single result is unaffected by the flag.
def test_first_leaves_a_single_result_alone(xjq):
    assert xjq("-f", "//book[@lang='fr']/title/text()", stdin=DOC).stdout == (
        "Le Petit Prince\n"
    )


# Phrase: "`--first` ..." -- a scalar result is one result already.
def test_first_leaves_a_scalar_result_alone(xjq):
    assert xjq("-f", "count(//book)", stdin=DOC).stdout == "2\n"
