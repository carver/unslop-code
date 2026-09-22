"""Spec: `mvault` Entry Points / Global Commands / Required Public Surface."""
import os

from conftest import MVAULT


# Spec: "| Entry file | `mvault.py` | Required implementation target |"
def test_entry_file_mvault_py_exists():
    assert os.path.isfile(MVAULT)


# Spec: "| Console command | `python mvault.py <subcommand> [args...]` | Full CLI
# behavior |" and "`mvault` Required Public Surface | CLI | Required".
# Context: the CLI is the required surface; a known subcommand must be accepted.
def test_console_command_accepts_subcommand(run, tmp_path):
    res = run("init", "vault", "http://example.invalid/s.json")
    assert res.returncode == 0, res
    assert (tmp_path / "vault").is_dir()


# Spec: "| `python mvault.py --help` | stdout | `0` | Usage text with available
# subcommands |"  -- exit code.
def test_help_exit_code_zero(run):
    assert run("--help").returncode == 0


# Spec: "--help | stdout" -- the usage text goes to stdout, not stderr.
def test_help_goes_to_stdout(run):
    res = run("--help")
    assert "usage" in res.stdout.lower()
    assert res.stderr == ""


# Spec: "--help ... Usage text with available subcommands"
def test_help_lists_available_subcommands(run):
    out = run("--help").stdout
    assert "init" in out
    assert "sync" in out


# Spec: "| `python mvault.py` | stderr | non-zero | Usage text |" -- exit code.
def test_no_subcommand_exit_code_non_zero(run):
    assert run().returncode != 0


# Spec: "`python mvault.py` | stderr | ... | Usage text" -- stream and content.
def test_no_subcommand_usage_text_on_stderr(run):
    res = run()
    assert "usage" in res.stderr.lower()
    assert res.stdout == ""


# Spec: "No subcommand | stderr | non-zero | Usage text" (Error Handling table).
def test_no_subcommand_error_handling_row(run):
    res = run()
    assert res.returncode != 0
    assert "usage" in res.stderr.lower()
