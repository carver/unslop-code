"""CLI surface: invocation form, positional arguments, and input source."""

from conftest import BOOKS


# Spec: "Implement executable `xjq.py`" / "`python xjq.py [OPTIONS] QUERY [INFILE]`"
def test_runs_as_a_script_with_a_query_argument(run_xjq):
    result = run_xjq("//title/text()", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLes Miserables"


# Spec: "Implement executable `xjq.py`" -- the file carries a shebang and the
# executable bit so it can be run directly as well.
def test_file_is_executable():
    import os
    import stat

    from conftest import XJQ

    mode = os.stat(XJQ).st_mode
    assert mode & stat.S_IXUSR
    assert XJQ.read_text().startswith("#!")


# Spec: "`QUERY`: XPath expression." -- the query is required.
def test_missing_query_is_a_usage_error(run_xjq):
    result = run_xjq(stdin=BOOKS)
    assert result.returncode != 0
    assert result.stderr != ""


# Spec: "`INFILE`: accepted positional argument but not used."
def test_infile_is_accepted(run_xjq, tmp_path):
    infile = tmp_path / "ignored.xml"
    infile.write_text("<other><title>Ignored</title></other>")
    result = run_xjq("//title/text()", str(infile), stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLes Miserables"


# Spec: "`INFILE`: accepted positional argument but not used." -- a path that
# does not exist is still accepted, because it is never opened.
def test_nonexistent_infile_is_ignored(run_xjq):
    result = run_xjq("//title/text()", "/no/such/file.xml", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Dune\nLes Miserables"


# Spec: "Input source: stdin."
def test_input_is_read_from_stdin(run_xjq):
    result = run_xjq("//greeting/text()", stdin="<greeting>hello</greeting>")
    assert result.stdout == "hello"


# Spec: "`python xjq.py [OPTIONS] QUERY [INFILE]`" -- options exist as a group;
# the only documented one is argparse's help.
def test_help_option(run_xjq):
    result = run_xjq("--help")
    assert result.returncode == 0
    assert "QUERY" in result.stdout.upper()
