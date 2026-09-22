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


# Spec: "`python xjq.py [OPTIONS] QUERY [INFILE]`"
# Context: a second positional is accepted by the parser and names the
# document to read.
def test_infile_positional_is_accepted(run_xjq, tmp_path):
    source = tmp_path / "doc.xml"
    source.write_text(DOC)
    result = run_xjq("//item/text()", str(source))
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: supersedes the base spec's "accepted ... but not used"; the file is
# now read in preference to stdin. See AMBIGUITIES.md T10.
def test_infile_is_read_in_preference_to_stdin(run_xjq, tmp_path):
    source = tmp_path / "doc.xml"
    source.write_text("<root><item>from-file</item></root>")
    result = run_xjq("//item/text()", str(source), stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["from-file"]


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: a nonexistent path is an error even though stdin holds a document.
def test_nonexistent_infile_is_an_error(run_xjq):
    result = run_xjq("//item/text()", "/no/such/file.xml", stdin=DOC)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Spec: "Input source: stdin." + "`INFILE` takes precedence over stdin"
# Context: with no INFILE, the document still comes from standard input.
def test_input_comes_from_stdin_without_infile(run_xjq):
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
# describes, and INFILE still follows it.
def test_flags_precede_the_positionals(run_xjq, tmp_path):
    source = tmp_path / "doc.xml"
    source.write_text(DOC)
    result = run_xjq("--css", "-t", "item", str(source))
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "## CLI Additions" — `-f`/`--first`, `-c`/`--compact`
# Context: two more flags join the OPTIONS slot, in both spellings.
def test_first_and_compact_flags_are_documented(run_xjq):
    help_text = run_xjq("--help").stdout
    assert "--first" in help_text
    assert "--compact" in help_text
    assert "-f" in help_text
    assert "-c" in help_text


# Spec: "`-f`, `--first`"
# Context: the short and long spellings mean the same thing.
def test_first_flag_spellings_agree(run_xjq):
    assert run_xjq("-f", "//item/text()", stdin=DOC).lines == ["alpha"]
    assert run_xjq("--first", "//item/text()", stdin=DOC).lines == ["alpha"]


# Spec: "`-c`, `--compact`"
# Context: the short and long spellings mean the same thing.
def test_compact_flag_spellings_agree(run_xjq):
    doc = "<r><a>\n  <b>1</b>\n</a></r>"
    assert run_xjq("-c", "//b", stdin=doc).stdout == run_xjq(
        "--compact", "//b", stdin=doc
    ).stdout
