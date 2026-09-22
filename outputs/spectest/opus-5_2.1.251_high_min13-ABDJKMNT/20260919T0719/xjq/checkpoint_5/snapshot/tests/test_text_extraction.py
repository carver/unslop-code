"""Spec section: Text Extraction.

How extracted text is joined and normalized, for both `::text` queries and the
`--text` / `--text-all` flags.
"""

from conftest import CSS_DOC


# Phrase: "Multi-match text output joins lines with `\n`."
def test_multiple_matches_join_with_newlines(xjq):
    doc = "<r><v>one</v><v>two</v><v>three</v></r>"
    assert xjq("--css", "v::text", stdin=doc).stdout == "one\ntwo\nthree\n"


# Phrase: "Multi-match text output joins lines with `\n`." (via the flags)
def test_flag_driven_multi_match_joins_with_newlines(xjq):
    doc = "<r><v>one</v><v>two</v></r>"
    assert xjq("--css", "--text", "v", stdin=doc).stdout == "one\ntwo\n"
    assert xjq("--text-all", "//v", stdin=doc).stdout == "one\ntwo\n"


# Phrase: "Multi-match text output joins lines with `\n`."
# A single match is a single line, so the join adds no separator of its own.
def test_single_match_is_one_line(xjq):
    assert xjq("--css", "span::text", stdin=CSS_DOC).stdout == "Span text\n"


# Phrase: "Strip each result"
def test_each_result_is_stripped(xjq):
    doc = "<r><v>  padded  </v><v>\n\ttabbed\n</v></r>"
    assert xjq("--css", "v::text", stdin=doc).stdout == "padded\ntabbed\n"


# Phrase: "collapse internal whitespace runs to single spaces"
def test_internal_whitespace_runs_collapse(xjq):
    doc = "<r><v>one   two\t\tthree</v></r>"
    assert xjq("--css", "v::text", stdin=doc).stdout == "one two three\n"


# Phrase: "collapse internal whitespace runs to single spaces"
# Newlines inside one text node become spaces rather than extra lines.
def test_internal_newlines_collapse_to_spaces(xjq):
    doc = "<r><v>first\n   second\n   third</v></r>"
    assert xjq("--css", "--text", "v", stdin=doc).stdout == "first second third\n"


# Phrase: "Strip each result and collapse internal whitespace runs ..."
# Normalization is per text node, so descendant extraction strips each line.
def test_descendant_results_are_normalized_individually(xjq):
    doc = "<r><v>  outer   one  <b>  bold  </b>  tail  </v></r>"
    assert xjq("--css", "v ::text", stdin=doc).stdout == "outer one\nbold\ntail\n"


# Phrase: "Strip each result ..." applied through `--text-all`.
def test_flag_driven_extraction_is_normalized(xjq):
    doc = "<r><v>  spaced   out  </v></r>"
    assert xjq("--text-all", "//r", stdin=doc).stdout == "spaced out\n"
