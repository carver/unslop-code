"""Spec section: CLI.

Covers the invocation contract: `python xjq.py [OPTIONS] QUERY [INFILE]`.
"""

from conftest import DOC


# Phrase: "Implement executable `xjq.py`" / "python xjq.py [OPTIONS] QUERY [INFILE]"
def test_script_is_invocable_with_a_single_query_argument(xjq):
    result = xjq("//title/text()", stdin=DOC)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLe Petit Prince\n"


# Phrase: "QUERY: XPath expression." (required positional)
def test_missing_query_is_a_usage_error(xjq):
    result = xjq(stdin=DOC)
    assert result.returncode != 0
    assert result.stderr != ""


# Phrase: "INFILE: accepted positional argument but not used."
def test_infile_positional_is_accepted(xjq, tmp_path):
    infile = tmp_path / "other.xml"
    infile.write_text("<other><title>Ignored</title></other>")
    result = xjq("//title/text()", str(infile), stdin=DOC)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLe Petit Prince\n"


# Phrase: "INFILE: accepted positional argument but not used."
# A non-existent INFILE is still accepted because it is never opened.
def test_nonexistent_infile_is_ignored(xjq):
    result = xjq("//title/text()", "/nonexistent/path.xml", stdin=DOC)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLe Petit Prince\n"


# Phrase: "Input source: stdin."
def test_input_is_read_from_stdin_not_from_infile(xjq, tmp_path):
    infile = tmp_path / "decoy.xml"
    infile.write_text("<library><book><title>Decoy</title></book></library>")
    result = xjq("//b/text()", str(infile), stdin="<a><b>from-stdin</b></a>")
    assert result.stdout == "from-stdin\n"
    assert "Decoy" not in result.stdout


# Phrase: "[OPTIONS]" -- help is available and does not consume the query.
def test_help_option_exits_zero(xjq):
    result = xjq("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
