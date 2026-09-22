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


# Phrase: "python xjq.py [OPTIONS] QUERY [INFILE]"
# Superseded: INFILE is now read, and takes precedence over stdin (see
# tests/test_input_source.py).
def test_infile_positional_is_read(xjq, tmp_path):
    infile = tmp_path / "other.xml"
    infile.write_text("<other><title>From file</title></other>")
    result = xjq("//title/text()", str(infile), stdin=DOC)
    assert result.returncode == 0
    assert result.stdout == "From file\n"


# Phrase: "Input source: stdin." -- still the source when no INFILE is given.
def test_input_is_read_from_stdin_without_an_infile(xjq):
    result = xjq("//b/text()", stdin="<a><b>from-stdin</b></a>")
    assert result.stdout == "from-stdin\n"


# Phrase: "[OPTIONS]" -- help is available and does not consume the query.
def test_help_option_exits_zero(xjq):
    result = xjq("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
