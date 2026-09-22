"""Spec section: `mvault` Entry Points / Global Commands / Required Public Surface."""

from pathlib import Path


# Phrase: "Entry file | `mvault.py` | Required implementation target"
def test_entry_file_exists():
    assert (Path(__file__).resolve().parents[1] / "mvault.py").is_file()


# Phrase: "Console command | `python mvault.py <subcommand> [args...]` | Full CLI behavior"
def test_console_command_runs_subcommand(run_cli, tmp_path):
    result = run_cli("init", "demo", "http://example.test/feed.json")
    assert result.returncode == 0
    assert (tmp_path / "demo" / "catalog.json").is_file()


# Phrase: "`python mvault.py --help` | stdout | `0` | Usage text with available subcommands"
def test_help_exits_zero_with_usage_on_stdout(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    assert result.stderr == ""


# Phrase: "Usage text with available subcommands"
def test_help_lists_subcommands(run_cli):
    result = run_cli("--help")
    assert "init" in result.stdout
    assert "sync" in result.stdout


# Phrase: "`python mvault.py` | stderr | non-zero | Usage text"
def test_no_subcommand_is_usage_error(run_cli):
    result = run_cli()
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
    assert result.stdout == ""


# Phrase: "No subcommand | stderr | non-zero | Usage text" (unknown subcommand, see AMBIGUITIES T12)
def test_unknown_subcommand_is_usage_error(run_cli):
    result = run_cli("frobnicate")
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
