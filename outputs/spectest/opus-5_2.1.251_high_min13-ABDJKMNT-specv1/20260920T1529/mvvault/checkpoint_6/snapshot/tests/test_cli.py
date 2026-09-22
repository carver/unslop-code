"""Spec section: `mvault` Entry Points / `mvault` Global Commands."""

from conftest import run_cli


# Entry Points: "Console command | `python mvault.py <subcommand> [args...]` |
# Full CLI behavior" and "Entry file | `mvault.py` | Required implementation
# target".
def test_entry_file_is_runnable_as_a_script(tmp_path, source):
    result = run_cli("init", "demo", source.url, cwd=tmp_path)
    assert result.returncode == 0, result.stderr


# Global Commands: "`python mvault.py --help` | stdout | `0` | Usage text with
# available subcommands".
def test_help_exits_zero(tmp_path):
    assert run_cli("--help", cwd=tmp_path).returncode == 0


# Global Commands: "--help ... Output Stream | stdout".
def test_help_writes_usage_to_stdout(tmp_path):
    result = run_cli("--help", cwd=tmp_path)
    assert "usage" in result.stdout.lower()
    assert result.stderr == ""


# Global Commands: "--help ... Usage text with available subcommands" — both
# documented subcommands are listed.
def test_help_lists_available_subcommands(tmp_path):
    stdout = run_cli("--help", cwd=tmp_path).stdout
    assert "init" in stdout
    assert "sync" in stdout


# Global Commands: "`python mvault.py` | stderr | non-zero | Usage text".
def test_no_subcommand_exits_non_zero(tmp_path):
    assert run_cli(cwd=tmp_path).returncode != 0


# Global Commands: "`python mvault.py` | stderr ... | Usage text" — the usage
# text goes to stderr, not stdout.
def test_no_subcommand_writes_usage_to_stderr(tmp_path):
    result = run_cli(cwd=tmp_path)
    assert "usage" in result.stderr.lower()
    assert result.stdout == ""
