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


# Spec: "`INFILE` takes precedence over stdin when both are present." -- this
# supersedes the original "accepted positional argument but not used"; see
# tests/test_file_input.py for the file-input rules.
def test_infile_is_read_in_preference_to_stdin(run_xjq, tmp_path):
    infile = tmp_path / "used.xml"
    infile.write_text("<other><title>Used</title></other>")
    result = run_xjq("//title/text()", str(infile), stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Used"


# Spec: "Missing/unreadable file: stderr message, exit code `1`." -- a path that
# does not exist is no longer ignored.
def test_nonexistent_infile_is_an_error(run_xjq):
    result = run_xjq("//title/text()", "/no/such/file.xml", stdin=BOOKS)
    assert result.returncode == 1
    assert result.stderr != ""


# Spec: "Input source: stdin." -- stdin is the source when no INFILE is given.
def test_input_is_read_from_stdin(run_xjq):
    result = run_xjq("//greeting/text()", stdin="<greeting>hello</greeting>")
    assert result.stdout == "hello"


# Spec: "`python xjq.py [OPTIONS] QUERY [INFILE]`" -- options exist as a group;
# the only documented one is argparse's help.
def test_help_option(run_xjq):
    result = run_xjq("--help")
    assert result.returncode == 0
    assert "QUERY" in result.stdout.upper()
