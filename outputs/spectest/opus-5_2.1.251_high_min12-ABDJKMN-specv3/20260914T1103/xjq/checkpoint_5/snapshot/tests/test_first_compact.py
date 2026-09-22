"""Spec sections: CLI Additions (`-f/--first`, `-c/--compact`) and Output
Rules (from "File Input, First-Result, and Compact Output").

Each test section quotes the minimal spec phrase it covers.
"""
import pytest


NUMS = "<a><b>one</b><b>two</b><b>three</b></a>"
ATTRS = '<a><b v="x1"/><b v="x2"/><b v="x3"/></a>'
ONELINE = "<a><b id='1'><c>deep</c></b><b id='2'/></a>"


# --- Phrase: "`-f`, `--first`: return only first result." -----------------
# Context: both spellings exist and mean the same thing.

def test_first_long_flag(xjq):
    r = xjq("--first", "//b/text()", stdin=NUMS)
    assert r.returncode == 0
    assert r.stdout == "one"


def test_first_short_flag(xjq):
    r = xjq("-f", "//b/text()", stdin=NUMS)
    assert r.returncode == 0
    assert r.stdout == "one"


def test_first_short_and_long_agree(xjq):
    short = xjq("-f", "//b/text()", stdin=NUMS)
    long = xjq("--first", "//b/text()", stdin=NUMS)
    assert short.stdout == long.stdout
    assert short.returncode == long.returncode == 0


def test_first_flag_may_follow_the_query(xjq):
    r = xjq("//b/text()", "--first", stdin=NUMS)
    assert r.returncode == 0
    assert r.stdout == "one"


def test_without_first_all_results_are_printed(xjq):
    r = xjq("//b/text()", stdin=NUMS)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["one", "two", "three"]


def test_first_output_is_a_single_line(xjq):
    r = xjq("--first", "//b/text()", stdin=NUMS)
    assert r.stdout.splitlines() == ["one"]
    assert "\n" not in r.stdout


def test_first_on_a_single_result_is_unchanged(xjq):
    r = xjq("--first", "//b/text()", stdin="<a><b>only</b></a>")
    assert r.returncode == 0
    assert r.stdout == "only"


# --- Phrase: "`--first` applies across text, attribute, and XML-node
#             results." (text) --------------------------------------------

def test_first_applies_to_text_results(xjq, books):
    r = xjq("--first", "//title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_first_still_strips_and_collapses(xjq):
    doc = "<a><b>  lots   of\n  space  </b><b>second</b></a>"
    r = xjq("--first", "//b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "lots of space"


def test_first_applies_to_text_extraction_flag(xjq, books):
    r = xjq("--first", "--text", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_first_applies_to_text_all_flag(xjq, page):
    r = xjq("--first", "--text-all", "//div", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["First Hello bold world"]


def test_first_applies_to_css_text_pseudo(xjq, books):
    r = xjq("--first", "--css", "title::text", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


# T30: in per-text-node mode one element yields several lines; --first keeps
# exactly one of them.
def test_first_applies_to_css_descendant_text_pseudo(xjq, page):
    r = xjq("--first", "--css", "div ::text", stdin=page)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["First"]


# --- Phrase: "`--first` applies across text, attribute, and XML-node
#             results." (attribute) ---------------------------------------

def test_first_applies_to_attribute_results(xjq):
    r = xjq("--first", "//b/@v", stdin=ATTRS)
    assert r.returncode == 0
    assert r.stdout == "x1"


def test_first_applies_to_attribute_results_on_books(xjq, books):
    r = xjq("--first", "//book/@id", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "b1"


def test_without_first_all_attributes_are_printed(xjq):
    r = xjq("//b/@v", stdin=ATTRS)
    assert r.stdout.splitlines() == ["x1", "x2", "x3"]


# --- Phrase: "`--first` applies across text, attribute, and XML-node
#             results." (XML nodes) ---------------------------------------
# T29: node output was already first-only, so --first is consistent with it.

def test_first_applies_to_xml_node_results(xjq, books):
    r = xjq("--first", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() == "<title>Dune</title>"


def test_first_node_output_has_exactly_one_element(xjq, books):
    r = xjq("--first", "//title", stdin=books)
    assert r.stdout.count("<title>") == 1
    assert "Neuromancer" not in r.stdout


def test_first_applies_to_css_node_results(xjq, books):
    r = xjq("--first", "--css", "title", stdin=books)
    assert r.returncode == 0
    assert r.stdout.strip() == "<title>Dune</title>"


def test_first_node_output_matches_default_node_output(xjq, books):
    with_flag = xjq("--first", "//title", stdin=books)
    without = xjq("//title", stdin=books)
    assert with_flag.stdout == without.stdout


# --- Phrase: "`--first` with no matches remains silent (no output)." ------
# Context: an empty node-set plus the flag; nothing on stdout, no error.

def test_first_with_no_matches_is_silent(xjq, books):
    r = xjq("--first", "//nothing/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_first_with_no_matching_nodes_is_silent(xjq, books):
    r = xjq("--first", "//nothing", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_first_with_no_matching_attributes_is_silent(xjq, books):
    r = xjq("--first", "//@missing", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_first_with_no_css_matches_is_silent(xjq, books):
    r = xjq("--first", "--css", "nothing", stdin=books)
    assert r.returncode == 0
    assert r.stdout == ""


def test_first_with_no_matches_writes_nothing_to_stderr(xjq, books):
    r = xjq("--first", "//nothing/text()", stdin=books)
    assert r.stderr == ""


# T30: matches that clean to empty are dropped before --first takes one, so a
# blank first match does not silence a real later one.
def test_first_skips_results_that_are_empty_after_cleaning(xjq):
    doc = "<a><b>   </b><b>real</b></a>"
    r = xjq("--first", "//b/text()", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "real"


# --- Phrase: "`-c`, `--compact`: compact output mode." --------------------
# Context: both spellings exist and mean the same thing.

def test_compact_long_flag(xjq):
    r = xjq("--compact", "/a", stdin=ONELINE)
    assert r.returncode == 0
    assert r.stdout == '<a><b id="1"><c>deep</c></b><b id="2"/></a>'


def test_compact_short_flag(xjq):
    r = xjq("-c", "/a", stdin=ONELINE)
    assert r.returncode == 0
    assert r.stdout == '<a><b id="1"><c>deep</c></b><b id="2"/></a>'


def test_compact_short_and_long_agree(xjq):
    short = xjq("-c", "/a", stdin=ONELINE)
    long = xjq("--compact", "/a", stdin=ONELINE)
    assert short.stdout == long.stdout


# --- Phrase: "compact XML output has no added pretty-print formatting." ---
# Context: the pretty path re-indents; the compact path adds nothing.

def test_default_output_is_pretty_printed(xjq):
    r = xjq("/a", stdin=ONELINE)
    assert r.returncode == 0
    assert "\n" in r.stdout


def test_compact_output_of_single_line_input_stays_one_line(xjq):
    r = xjq("--compact", "/a", stdin=ONELINE)
    assert "\n" not in r.stdout


def test_compact_adds_no_indentation(xjq):
    r = xjq("--compact", "/a", stdin="<a><b><c>x</c></b></a>")
    assert r.stdout == "<a><b><c>x</c></b></a>"


# T32: no trailing newline, like every other output form.
def test_compact_output_has_no_trailing_newline(xjq):
    r = xjq("--compact", "/a", stdin=ONELINE)
    assert not r.stdout.endswith("\n")
    assert r.stdout.endswith(">")


# T31: whitespace already in the document is content, not added formatting.
def test_compact_preserves_existing_document_whitespace(xjq):
    doc = "<a>\n  <b>1</b>\n</a>"
    r = xjq("--compact", "/a", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == "<a>\n  <b>1</b>\n</a>"


def test_compact_preserves_mixed_content(xjq, mixed):
    r = xjq("--compact", "//p", stdin=mixed)
    assert r.returncode == 0
    assert r.stdout == "<p>Hello <b>bold</b> world</p>"


def test_compact_node_output_still_first_only(xjq, books):
    r = xjq("--compact", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_compact_works_in_css_mode(xjq, books):
    r = xjq("--compact", "--css", "book", stdin=books)
    assert r.returncode == 0
    assert r.stdout.startswith('<book id="b1"')
    assert r.stdout.endswith("</book>")


# --- Phrase: "`--compact` affects XML serialization only" -----------------
# Context: text and attribute output is byte-identical with and without it.

def test_compact_does_not_change_text_output(xjq, books):
    plain = xjq("//title/text()", stdin=books)
    compact = xjq("--compact", "//title/text()", stdin=books)
    assert compact.stdout == plain.stdout
    assert compact.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


def test_compact_does_not_change_attribute_output(xjq, books):
    plain = xjq("//book/@id", stdin=books)
    compact = xjq("--compact", "//book/@id", stdin=books)
    assert compact.stdout == plain.stdout


def test_compact_does_not_change_extracted_text(xjq, books):
    plain = xjq("--text", "//title", stdin=books)
    compact = xjq("--compact", "--text", "//title", stdin=books)
    assert compact.stdout == plain.stdout


def test_compact_does_not_change_scalar_results(xjq, books):
    plain = xjq("count(//book)", stdin=books)
    compact = xjq("--compact", "count(//book)", stdin=books)
    assert compact.stdout == plain.stdout


# --- Phrase: "For JSON-derived input, `--compact` still applies to
#             resulting XML output." --------------------------------------
# Context: a synthesized tree is not exempt from the flag.

def test_compact_applies_to_json_derived_nodes(xjq):
    r = xjq("--compact", "/root", stdin='{"a": 1}')
    assert r.returncode == 0
    assert r.stdout == '<root><a type="int">1</a></root>'


def test_json_derived_node_is_pretty_printed_without_compact(xjq):
    r = xjq("/root", stdin='{"a": 1}')
    assert r.returncode == 0
    assert "\n" in r.stdout


def test_compact_applies_to_nested_json(xjq):
    doc = '{"user": {"name": "ada", "tags": ["x", "y"]}}'
    r = xjq("--compact", "/root/user", stdin=doc)
    assert r.returncode == 0
    assert r.stdout == (
        '<user type="dict"><name type="str">ada</name>'
        '<tags type="list"><item type="str">x</item>'
        '<item type="str">y</item></tags></user>'
    )


def test_compact_json_array_input(xjq):
    r = xjq("--compact", "/root", stdin="[1, 2]")
    assert r.returncode == 0
    assert r.stdout == (
        '<root><item type="int">1</item><item type="int">2</item></root>'
    )


# T37: --compact leaves JSON-derived text output alone.
def test_compact_does_not_change_json_derived_text(xjq):
    doc = '{"a": "x", "b": "y"}'
    plain = xjq("/root/*/text()", stdin=doc)
    compact = xjq("--compact", "/root/*/text()", stdin=doc)
    assert compact.stdout == plain.stdout
    assert compact.stdout.splitlines() == ["x", "y"]


# --- Phrase: combining the two new flags ----------------------------------
# Context: nothing in the spec makes them exclusive.

def test_first_and_compact_together(xjq, books):
    r = xjq("--first", "--compact", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_first_and_compact_short_flags_together(xjq, books):
    r = xjq("-f", "-c", "//title", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_first_and_compact_with_infile(xjq, tmp_path, books):
    path = tmp_path / "books.xml"
    path.write_text(books, encoding="utf-8")
    r = xjq("-f", "-c", "//title", str(path), stdin="")
    assert r.returncode == 0
    assert r.stdout == "<title>Dune</title>"


def test_new_flags_appear_in_help(xjq):
    r = xjq("--help", stdin="")
    assert r.returncode == 0
    for token in ("-f", "--first", "-c", "--compact"):
        assert token in r.stdout
