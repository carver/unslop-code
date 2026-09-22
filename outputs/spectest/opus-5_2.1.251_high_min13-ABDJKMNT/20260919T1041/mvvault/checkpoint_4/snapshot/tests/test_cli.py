"""`mvault` Entry Points and Global Commands."""

import json
import sys
from pathlib import Path

MVAULT = Path(__file__).resolve().parent.parent / "mvault.py"


# Spec: Entry file | `mvault.py` | Required implementation target
def test_entry_file_exists():
    assert MVAULT.is_file()


# Spec: Console command | `python mvault.py <subcommand> [args...]` | Full CLI behavior
def test_console_command_runs_subcommands(run_cli, tmp_path):
    result = run_cli("init", "vault", "http://example.invalid/feed.json")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "vault" / "catalog.json").is_file()


# Spec: `python mvault.py --help` | stdout | `0` | Usage text with available subcommands
def test_help_goes_to_stdout_with_exit_zero(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0
    assert result.stdout.strip()


# Spec: `python mvault.py --help` ... Usage text with available subcommands
def test_help_lists_subcommands(run_cli):
    result = run_cli("--help")
    assert "usage" in result.stdout.lower()
    assert "init" in result.stdout
    assert "sync" in result.stdout


# Spec: `python mvault.py` | stderr | non-zero | Usage text
def test_no_subcommand_writes_usage_to_stderr(run_cli):
    result = run_cli()
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
    assert result.stdout == ""


# Spec: `python mvault.py` ... Usage text (no side effects without a subcommand)
def test_no_subcommand_creates_nothing(run_cli, tmp_path):
    run_cli()
    assert list(tmp_path.iterdir()) == []
