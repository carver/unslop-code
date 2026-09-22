"""Spec section: `mvault` Entry Points / `mvault` Global Commands."""
import os
import subprocess
import sys

from conftest import MVAULT, REPO_ROOT


# --- Phrase: "Entry file | `mvault.py` | Required implementation target"
def test_entry_file_exists_at_repo_root():
    assert os.path.isfile(MVAULT)


# --- Phrase: "Console command | `python mvault.py <subcommand> [args...]` |
#     Full CLI behavior" (context: the module must be runnable as a script)
def test_module_runs_as_a_script(run):
    result = run("--help")
    assert result.returncode == 0, result


# --- Phrase: "`python mvault.py --help` | stdout | `0` | Usage text with
#     available subcommands"
def test_help_exits_zero(run):
    result = run("--help")
    assert result.returncode == 0, result


def test_help_writes_usage_text_to_stdout(run):
    result = run("--help")
    assert "usage" in result.stdout.lower(), result
    assert result.stdout.strip(), result


def test_help_lists_available_subcommands(run):
    result = run("--help")
    assert "init" in result.stdout, result
    assert "sync" in result.stdout, result


def test_help_writes_nothing_to_stderr(run):
    result = run("--help")
    assert result.stderr == "", result


# --- Phrase: "`python mvault.py` | stderr | non-zero | Usage text"
#     (context: `mvault` Global Commands + Error Handling "No subcommand")
def test_no_subcommand_exits_non_zero(run):
    result = run()
    assert result.returncode != 0, result


def test_no_subcommand_writes_usage_text_to_stderr(run):
    result = run()
    assert "usage" in result.stderr.lower(), result


def test_no_subcommand_writes_no_usage_to_stdout(run):
    result = run()
    assert "usage" not in result.stdout.lower(), result


# --- Phrase: "Full CLI behavior" (context: an unknown subcommand is not part
#     of the required surface and must not succeed silently)
def test_unknown_subcommand_fails(run):
    result = run("bogus")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result


# --- Phrase: "Console command | `python mvault.py <subcommand> [args...]`"
#     (context: argument arity for the two documented subcommands)
def test_init_requires_name_and_url(run):
    assert run("init").returncode != 0
    assert run("init", "vault").returncode != 0


def test_sync_requires_name(run):
    assert run("sync").returncode != 0
