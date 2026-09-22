"""Spec section: CLI.

Each test section quotes the minimal spec phrase it covers.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
XJQ = REPO_ROOT / "xjq.py"


# --- Phrase: "Implement executable `xjq.py`" -------------------------------
# Context: the program is a file named xjq.py at the project root.

def test_xjq_py_exists_at_project_root():
    assert XJQ.is_file()


# --- Phrase: "Implement executable `xjq.py`" (executable) ------------------
# Context: "executable" -> the file carries a shebang and the exec bit, so it
# can be invoked directly as well as through the interpreter.

def test_xjq_py_has_shebang():
    first_line = XJQ.read_text().splitlines()[0]
    assert first_line.startswith("#!")
    assert "python" in first_line


def test_xjq_py_has_executable_bit():
    assert os.access(XJQ, os.X_OK)


def test_xjq_py_runs_when_invoked_directly(books):
    # The shebang resolves `python3` from PATH, so the interpreter that holds
    # the dependencies (this test run's interpreter) is put in front of it.
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    completed = subprocess.run(
        [str(XJQ), "//title/text()"],
        input=books.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        env=env,
    )
    assert completed.returncode == 0
    assert completed.stdout.decode().splitlines()[0] == "Dune"


# --- Phrase: "`python xjq.py [OPTIONS] QUERY [INFILE]`" --------------------
# Context: invocation form. QUERY is a required positional.

def test_query_is_required(xjq):
    r = xjq(stdin="<a/>")
    assert r.returncode != 0
    assert r.stderr != ""


def test_runs_with_query_only(xjq, books):
    r = xjq("//title/text()", stdin=books)
    assert r.returncode == 0


# --- Phrase: "`QUERY`: XPath expression." ---------------------------------
# Context: the first positional is the XPath to evaluate.

def test_query_positional_is_the_evaluated_xpath(xjq, books):
    r = xjq("//author/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        "Frank Herbert",
        "Antoine de Saint-Exupery",
        "William Gibson",
    ]


def test_query_may_be_an_absolute_path(xjq, books):
    r = xjq("/library/book[1]/title/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "Dune"


def test_query_may_select_attributes(xjq, books):
    r = xjq("//book/@id", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["b1", "b2", "b3"]


# --- Phrase: "`INFILE`: accepted positional argument but not used." -------
# Context: a second positional is tolerated; input still comes from stdin.

def test_infile_positional_is_accepted(xjq, books):
    r = xjq("//title/text()", "some-file.xml", stdin=books)
    assert r.returncode == 0


def test_infile_is_ignored_input_still_read_from_stdin(xjq, books, tmp_path):
    decoy = tmp_path / "decoy.xml"
    decoy.write_text("<library><book><title>NOT THIS</title></book></library>")
    r = xjq("//title/text()", str(decoy), stdin=books)
    assert r.returncode == 0
    assert "NOT THIS" not in r.stdout
    assert r.stdout.splitlines() == ["Dune", "Le Petit Prince", "Neuromancer"]


def test_nonexistent_infile_is_not_an_error(xjq, books):
    # Ambiguity T9: "not used" is taken literally; the path is never opened.
    r = xjq("//title/text()", "/no/such/path/at/all.xml", stdin=books)
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "Dune"


# --- Phrase: "Input source: stdin." ---------------------------------------
# Context: the document under query arrives on standard input.

def test_reads_document_from_stdin(xjq):
    r = xjq("//msg/text()", stdin="<root><msg>from stdin</msg></root>")
    assert r.returncode == 0
    assert r.stdout == "from stdin"


def test_reads_stdin_even_with_no_infile_argument(xjq, books):
    r = xjq("//library/@name", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "City Central"


# --- Phrase: "[OPTIONS]" ---------------------------------------------------
# Context: ambiguity T1 - no behavioural flags are specified, but a usage/help
# option must exist and the usage line must name QUERY and INFILE.

def test_help_option_exits_zero_and_shows_usage(xjq):
    r = xjq("--help", stdin="")
    assert r.returncode == 0
    assert "QUERY" in r.stdout.upper()
    assert "INFILE" in r.stdout.upper()


def test_options_do_not_swallow_the_query(xjq, books):
    # A query starting with '/' must never be mistaken for an option.
    r = xjq("/library/book[2]/year/text()", stdin=books)
    assert r.returncode == 0
    assert r.stdout == "1943"
