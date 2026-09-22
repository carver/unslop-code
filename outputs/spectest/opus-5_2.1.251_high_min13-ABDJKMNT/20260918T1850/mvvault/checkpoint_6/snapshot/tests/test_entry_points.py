"""Spec sections: `mvault` Entry Points, `mvault` Global Commands."""

from conftest import MVAULT


# Spec: Entry file | `mvault.py` | Required implementation target
def test_entry_file_exists():
    assert MVAULT.is_file()


# Spec: Console command | `python mvault.py <subcommand> [args...]` | Full CLI behavior
def test_console_command_accepts_subcommand(run, tmp_path):
    result = run("init", "vault", "http://example.invalid/source.json")
    assert result.returncode == 0
    assert (tmp_path / "vault" / "catalog.json").is_file()


# Spec: `python mvault.py --help` | stdout | `0` | Usage text with available subcommands
def test_help_exits_zero_on_stdout(run):
    result = run("--help")
    assert result.returncode == 0
    assert result.stdout.strip()
    assert result.stderr == ""


# Spec: `python mvault.py --help` ... Usage text with available subcommands
def test_help_lists_subcommands(run):
    stdout = run("--help").stdout
    assert "usage" in stdout.lower()
    assert "init" in stdout
    assert "sync" in stdout
    assert "migrate" in stdout
    assert "digest" in stdout


# Spec: `python mvault.py` | stderr | non-zero | Usage text
def test_no_subcommand_is_usage_error(run):
    result = run()
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
    assert result.stdout == ""
