"""CLI surface: argument shape and input source.

Spec section: "## CLI"
"""

import subprocess
import sys

from conftest import XJQ

DOC = "<root><item>alpha</item><item>beta</item></root>"


# Spec: "Implement executable `xjq.py`" / "`python xjq.py [OPTIONS] QUERY [INFILE]`"
# Context: the program is invoked as a script with the query as the first
# positional argument.
def test_invoked_as_script_with_query(run_xjq):
    result = run_xjq("//item/text()", stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "`QUERY`: XPath expression."
# Context: the single required positional is the expression to evaluate.
def test_query_is_required(run_xjq):
    completed = subprocess.run(
        [sys.executable, str(XJQ)],
        input=DOC.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode != 0
    assert completed.stderr != b""


# Spec: "`INFILE`: accepted positional argument but not used."
# Context: a second positional is tolerated by the parser.
def test_infile_positional_is_accepted(run_xjq):
    result = run_xjq("//item/text()", "ignored.xml", stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "`INFILE`: ... but not used." + "Input source: stdin."
# Context: the named file must never be read, even when it exists and holds
# different XML; stdin still supplies the document. See AMBIGUITIES.md T10.
def test_infile_is_never_read(run_xjq, tmp_path):
    decoy = tmp_path / "decoy.xml"
    decoy.write_text("<root><item>from-file</item></root>")
    result = run_xjq("//item/text()", str(decoy), stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "`INFILE`: accepted positional argument but not used."
# Context: a nonexistent path is not an error, because it is never opened.
def test_nonexistent_infile_is_not_an_error(run_xjq):
    result = run_xjq("//item/text()", "/no/such/file.xml", stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "Input source: stdin."
# Context: the document always comes from the standard input stream.
def test_input_comes_from_stdin(run_xjq):
    result = run_xjq("/root/item[2]/text()", stdin=DOC)
    assert result.returncode == 0
    assert result.stdout.strip() == "beta"


# Spec: "`python xjq.py [OPTIONS] QUERY [INFILE]`"
# Context: the OPTIONS slot exposes only the standard help flag.
# See AMBIGUITIES.md T1.
def test_help_flag_is_available(run_xjq):
    result = run_xjq("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


# Spec: "## CLI Additions" — `--css`, `-t`/`--text`, `--text-all`
# Context: the OPTIONS slot now carries three documented flags.
# See AMBIGUITIES.md T1.
def test_added_flags_are_documented(run_xjq):
    help_text = run_xjq("--help").stdout
    assert "--css" in help_text
    assert "--text-all" in help_text
    assert "-t" in help_text


# Spec: "## CLI Additions"
# Context: the flags come before the positional query, as `[OPTIONS] QUERY`
# describes, and INFILE still follows it unread.
def test_flags_precede_the_positionals(run_xjq):
    result = run_xjq("--css", "-t", "item", "ignored.xml", stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]
