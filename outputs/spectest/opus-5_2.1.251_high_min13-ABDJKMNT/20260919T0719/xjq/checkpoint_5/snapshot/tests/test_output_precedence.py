"""Spec section: Output Precedence.

`--text-all` beats `--text`, which beats `--json`, which beats the default
auto-formatting -- and `--json` steps aside for results that are already text
and for CSS mode.
"""

import json

from conftest import CSS_DOC, DOC, EXPORT_DOC


# Phrase: "When multiple output flags are present: 1. `--text-all`"
def test_text_all_outranks_text_and_json(xjq):
    result = xjq("--json", "--text", "--text-all", "//book[1]", stdin=DOC)
    assert result.stdout == xjq("--text-all", "//book[1]", stdin=DOC).stdout
    assert result.stdout == "Dune\nFrank Herbert\n"


# Phrase: "2. `--text`" -- ranked above `--json`.
def test_text_outranks_json(xjq):
    result = xjq("--json", "--text", "//title", stdin=DOC)
    assert result.stdout == "Dune\nLe Petit Prince\n"


# Phrase: "3. `--json`" -- ranked above the default auto-format behavior.
def test_json_outranks_default_auto_format(xjq):
    default = xjq("//title", stdin=DOC).stdout
    exported = xjq("--json", "//title", stdin=DOC).stdout
    assert default.startswith("<title>")
    assert json.loads(exported) == [{"title": "Dune"}, {"title": "Le Petit Prince"}]


# Phrase: "4. default auto-format behavior" -- without `--json` a node set is
# still serialized as XML.
def test_default_auto_format_applies_without_json(xjq):
    assert xjq("--first", "//item", stdin=EXPORT_DOC).stdout == "<item>Alpha</item>\n"


# Phrase: "`--json` has no effect when results are already auto-detected as
#          text (e.g., text()/attribute outputs)."
def test_json_is_a_no_op_for_text_node_results(xjq):
    plain = xjq("//title/text()", stdin=DOC).stdout
    assert xjq("--json", "//title/text()", stdin=DOC).stdout == plain
    assert plain == "Dune\nLe Petit Prince\n"


# Phrase: "... already auto-detected as text (e.g., text()/attribute outputs)."
def test_json_is_a_no_op_for_attribute_results(xjq):
    plain = xjq("//book/@id", stdin=DOC).stdout
    assert xjq("-j", "//book/@id", stdin=DOC).stdout == plain
    assert plain == "b1\nb2\n"


# Phrase: "... already auto-detected as text ..." -- scalars are text too.
def test_json_is_a_no_op_for_scalar_results(xjq):
    assert xjq("-j", "count(//book)", stdin=DOC).stdout == "2\n"
    assert xjq("-j", "string(//title)", stdin=DOC).stdout == "Dune\n"


# Phrase: "In `--css` mode, `--json` has no effect and output follows the
#          normal CSS rules for the query."
def test_json_is_a_no_op_in_css_mode(xjq):
    plain = xjq("--css", "span", stdin=CSS_DOC).stdout
    assert xjq("--css", "--json", "span", stdin=CSS_DOC).stdout == plain
    assert plain == "<span>Span text</span>\n"


# Phrase: "In `--css` mode, `--json` has no effect and output follows the
#          normal CSS rules for the query." -- including `::text` queries.
def test_json_does_not_disturb_css_text_queries(xjq):
    plain = xjq("--css", "p::text", stdin=CSS_DOC).stdout
    assert xjq("--css", "-j", "p::text", stdin=CSS_DOC).stdout == plain
    assert plain == "Hello\nworld\nSecond\n"


# Phrase: "In `--css` mode, `--json` has no effect" -- the text flags keep
# outranking it there as well.
def test_css_text_flag_still_outranks_json(xjq):
    assert xjq("--css", "-j", "--text", "p", stdin=CSS_DOC).stdout == "Hello\nworld\nSecond\n"
