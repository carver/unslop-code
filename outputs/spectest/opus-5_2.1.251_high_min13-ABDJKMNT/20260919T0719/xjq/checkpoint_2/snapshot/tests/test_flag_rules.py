"""Spec section: Flag Rules.

Precedence between `--text` and `--text-all`, and when either becomes a no-op.
"""

from conftest import CSS_DOC, DOC, NESTED_DOC


# Phrase: "If both `--text` and `--text-all` are present, `--text-all` wins."
def test_text_all_wins_over_text(xjq):
    both = xjq("--css", "--text", "--text-all", "p", stdin=CSS_DOC)
    assert both.stdout == xjq("--css", "--text-all", "p", stdin=CSS_DOC).stdout
    assert both.stdout == "Hello\nbold\nworld\nSecond\n"


# Phrase: "If both `--text` and `--text-all` are present, `--text-all` wins."
# The order the flags are written in does not change the winner.
def test_text_all_wins_regardless_of_flag_order(xjq):
    first = xjq("--css", "--text-all", "-t", "p", stdin=CSS_DOC)
    second = xjq("--css", "-t", "--text-all", "p", stdin=CSS_DOC)
    assert first.stdout == second.stdout == "Hello\nbold\nworld\nSecond\n"


# Phrase: "If query already extracts text (`text()` ...), `--text` and
#          `--text-all` are no-op modifiers."
def test_flags_are_no_ops_for_an_xpath_text_query(xjq):
    plain = xjq("//title/text()", stdin=DOC).stdout
    assert xjq("--text", "//title/text()", stdin=DOC).stdout == plain
    assert xjq("--text-all", "//title/text()", stdin=DOC).stdout == plain
    assert plain == "Dune\nLe Petit Prince\n"


# Phrase: "If query already extracts text (... `::text`), `--text` and
#          `--text-all` are no-op modifiers." -- direct mode is preserved.
def test_flags_do_not_override_direct_text_pseudo_element(xjq):
    plain = xjq("--css", "p::text", stdin=CSS_DOC).stdout
    assert xjq("--css", "--text-all", "p::text", stdin=CSS_DOC).stdout == plain
    assert plain == "Hello\nworld\nSecond\n"


# Phrase: "... `--text` and `--text-all` are no-op modifiers."
# Descendant mode is preserved against `--text` too.
def test_flags_do_not_override_descendant_text_pseudo_element(xjq):
    plain = xjq("--css", "section ::text", stdin=NESTED_DOC).stdout
    assert xjq("--css", "-t", "section ::text", stdin=NESTED_DOC).stdout == plain
    assert plain == "outer\ninner\ntail\n"


# Phrase: "... are no-op modifiers." -- nothing to extract from an attribute
# result either, so the flags leave it alone.
def test_flags_are_no_ops_for_attribute_results(xjq):
    plain = xjq("//book/@id", stdin=DOC).stdout
    assert xjq("--text", "//book/@id", stdin=DOC).stdout == plain
    assert xjq("--text-all", "//book/@id", stdin=DOC).stdout == plain


# Phrase: "... are no-op modifiers." -- scalar results are untouched.
def test_flags_are_no_ops_for_scalar_results(xjq):
    assert xjq("--text", "count(//book)", stdin=DOC).stdout == "2\n"
    assert xjq("--text-all", "count(//book)", stdin=DOC).stdout == "2\n"
