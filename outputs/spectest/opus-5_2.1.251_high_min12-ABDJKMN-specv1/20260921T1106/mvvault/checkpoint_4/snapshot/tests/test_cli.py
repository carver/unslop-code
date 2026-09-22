"""Spec section: `mvault` Entry Points / Global Commands / Error Handling."""
import os
import re

from conftest import MVAULT


# Phrase: "Entry file | `mvault.py` | Required implementation target"
def test_entry_file_exists():
    assert os.path.isfile(MVAULT)


# Phrase: "Console command | `python mvault.py <subcommand> [args...]` |
#          Full CLI behavior"
# Context: the module is invoked as a script; a known subcommand runs.
def test_console_command_runs_subcommand(run, tmp_path):
    result = run("init", "vault", "http://example.invalid/feed.json")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "vault" / "catalog.json").is_file()


# Phrase: "`python mvault.py --help` | stdout | `0` |
#          Usage text with available subcommands"
def test_help_goes_to_stdout_with_exit_zero(run):
    result = run("--help")
    assert result.returncode == 0
    assert result.stdout.strip()
    assert re.search(r"usage", result.stdout, re.IGNORECASE)


# Phrase: "Usage text with available subcommands"
# Context: both subcommands defined by the spec must be discoverable.
def test_help_lists_available_subcommands(run):
    result = run("--help")
    assert "init" in result.stdout
    assert "sync" in result.stdout


# Phrase: "`python mvault.py` | stderr | non-zero | Usage text"
def test_no_subcommand_writes_usage_to_stderr_and_fails(run):
    result = run()
    assert result.returncode != 0
    assert re.search(r"usage", result.stderr, re.IGNORECASE)
    assert result.stdout == ""


# Phrase: "No subcommand | stderr | non-zero | Usage text"
# Context: the usage text on the error path also names the subcommands.
def test_no_subcommand_usage_mentions_subcommands(run):
    result = run()
    assert "init" in result.stderr and "sync" in result.stderr
