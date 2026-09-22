"""Spec section: `mvault` Entry Points / `mvault` Global Commands / Public Surface."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# Spec: | Entry file | `mvault.py` | Required implementation target |
def test_entry_file_mvault_py_exists():
    assert (REPO_ROOT / "mvault.py").is_file()


# Spec: | Console command | `python mvault.py <subcommand> [args...]` | Full CLI behavior |
# Context: the console command is the required public surface ("| CLI | Required |").
def test_console_command_runs_subcommands(run_cli, source, workdir):
    result = run_cli("init", "vault", source.url)
    assert result.returncode == 0, result.stderr
    assert (Path(workdir) / "vault" / "catalog.json").is_file()


# Spec: | `python mvault.py --help` | stdout | `0` | Usage text with available subcommands |
def test_help_exits_zero(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0


# Spec: ... | stdout | ... : help text goes to stdout, not stderr.
def test_help_writes_usage_to_stdout(run_cli):
    result = run_cli("--help")
    assert "usage" in result.stdout.lower()
    assert result.stderr == ""


# Spec: "Usage text with available subcommands"
def test_help_lists_available_subcommands(run_cli):
    result = run_cli("--help")
    assert "init" in result.stdout
    assert "sync" in result.stdout


# Spec: | `python mvault.py` | stderr | non-zero | Usage text |
def test_no_subcommand_exits_non_zero(run_cli):
    result = run_cli()
    assert result.returncode != 0


# Spec: | `python mvault.py` | stderr | ... | Usage text |
# Context: also the error table row "| No subcommand | stderr | non-zero | Usage text |".
def test_no_subcommand_writes_usage_to_stderr(run_cli):
    result = run_cli()
    assert "usage" in result.stderr.lower()
    assert result.stdout == ""


# Spec: | Source request | HTTP `GET` to vault `source` URL, made with `urllib.request` |
# Context: structural check that the required library is the one used.
def test_implementation_uses_urllib_request():
    src = (REPO_ROOT / "mvault.py").read_text(encoding="utf-8")
    assert "urllib.request" in src
    assert "requests" not in src.replace("urllib.request", "")


# Spec: Determinism | Locale | No locale-sensitive formatting anywhere |
def test_no_locale_sensitive_formatting_in_source():
    src = (REPO_ROOT / "mvault.py").read_text(encoding="utf-8")
    for banned in ("import locale", "strftime(\"%c", "%x", "%X", "setlocale"):
        assert banned not in src


# Spec: Determinism | Locale | ... (behavioral: output identical under a changed locale)
def test_output_identical_under_changed_locale(run_cli, source, workdir, helpers):
    import json
    import os
    import subprocess

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("a")]))
    assert run_cli("init", "vault", source.url).returncode == 0
    assert run_cli("sync", "vault").returncode == 0
    baseline = helpers.read_catalog(workdir)

    env = dict(os.environ, LC_ALL="C.UTF-8", LANG="C.UTF-8", TZ="UTC")
    assert run_cli("init", "vault2", source.url).returncode == 0
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "mvault.py"), "sync", "vault2"],
        cwd=str(workdir), capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    other = helpers.read_catalog(workdir, "vault2")

    def strip_history(cat):
        return [
            {k: (sorted(v.values(), key=repr) if isinstance(v, dict) else v) for k, v in e.items()}
            for e in cat["episodes"]
        ]

    assert strip_history(baseline) == strip_history(other)
    assert json.dumps(baseline["version"]) == json.dumps(other["version"])
