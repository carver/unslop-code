"""Spec section: Environment Commands (`env list`, `env find-virtualenvs`,
`env info`)."""
import json
import os
import sys

from conftest import (PY, env_info, env_list, env_virtualenvs, fake_venv,
                      run_json, run_raw, write_config)


def _versions(rows):
    return [tuple(int(p) for p in r["version"].split(".")) for r in rows]


# --- Phrase: "python sith.py env list" / "Find and list available Python
#     installations on the system."
def test_env_list_finds_at_least_one_python(tmp_path):
    rows = env_list(cwd=str(tmp_path))
    assert isinstance(rows, list)
    assert rows, "expected at least the running interpreter"


# --- Phrase: the `executable`, `version` and `is_virtualenv` fields.
def test_env_list_row_shape(tmp_path):
    for row in env_list(cwd=str(tmp_path)):
        assert set(row) == {"executable", "version", "is_virtualenv"}
        assert isinstance(row["executable"], str)
        assert isinstance(row["version"], str)
        assert isinstance(row["is_virtualenv"], bool)


# --- Phrase: `executable` — "Absolute path to the Python executable."
def test_env_list_executables_are_absolute_and_runnable(tmp_path):
    for row in env_list(cwd=str(tmp_path)):
        assert os.path.isabs(row["executable"]), row
        assert os.path.exists(row["executable"]), row


# --- Phrase: `version` — "Python version string (e.g., "3.11.6")."
def test_env_list_version_is_dotted_triple(tmp_path):
    for row in env_list(cwd=str(tmp_path)):
        parts = row["version"].split(".")
        assert len(parts) == 3, row
        assert all(p.isdigit() for p in parts), row


# --- Phrase: "Sort environments by version descending (newest first)."
def test_env_list_sorted_by_version_descending(tmp_path):
    versions = _versions(env_list(cwd=str(tmp_path)))
    assert versions == sorted(versions, reverse=True)


# --- Phrase: "For equal versions, sort by executable path ascending."
def test_env_list_ties_broken_by_executable_path(tmp_path):
    rows = env_list(cwd=str(tmp_path))
    keys = [(tuple(-int(p) for p in r["version"].split(".")), r["executable"])
            for r in rows]
    assert keys == sorted(keys)


# --- Phrase: "Deduplicate by resolved executable path (follow symlinks)."
def test_env_list_has_no_duplicates(tmp_path):
    rows = env_list(cwd=str(tmp_path))
    paths = [r["executable"] for r in rows]
    assert len(paths) == len(set(paths))
    # two names for one interpreter collapse into a single row
    keys = [(os.path.realpath(r["executable"]), r["is_virtualenv"])
            for r in rows]
    non_venv = [k for k, v in keys if not v]
    assert len(non_venv) == len(set(non_venv))


# --- Phrase: "python sith.py env find-virtualenvs [--path <dir>]" — the
#     directory given by `--path`, looking for `bin/python` inside immediate
#     subdirectories.
def test_find_virtualenvs_with_explicit_path(tmp_path):
    root = tmp_path / "envs"
    root.mkdir()
    venv = fake_venv(root, "myenv")
    rows = env_virtualenvs(str(tmp_path), "--path", str(root))
    paths = [r["executable"] for r in rows]
    assert str(venv / "bin" / "python") in paths


# --- Phrase: only *immediate* subdirectories of `--path` are searched.
def test_find_virtualenvs_does_not_recurse(tmp_path):
    root = tmp_path / "envs"
    (root / "deep").mkdir(parents=True)
    buried = fake_venv(root / "deep", "nested")
    rows = env_virtualenvs(str(tmp_path), "--path", str(root))
    paths = [r["executable"] for r in rows]
    assert str(buried / "bin" / "python") not in paths


# --- Phrase: "`.venv/` and `venv/` in the current directory and project root."
def test_find_virtualenvs_finds_dot_venv_in_cwd(tmp_path):
    venv = fake_venv(tmp_path, ".venv")
    paths = [r["executable"] for r in env_virtualenvs(str(tmp_path))]
    assert str(venv / "bin" / "python") in paths


def test_find_virtualenvs_finds_venv_in_cwd(tmp_path):
    venv = fake_venv(tmp_path, "venv")
    paths = [r["executable"] for r in env_virtualenvs(str(tmp_path))]
    assert str(venv / "bin" / "python") in paths


# --- Phrase: ".venv/ and venv/ in ... the project root."
def test_find_virtualenvs_finds_venv_in_project_root(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    venv = fake_venv(proj, ".venv")
    other = tmp_path / "elsewhere"
    other.mkdir()
    rows = run_json("env", "find-virtualenvs", "--project", str(proj),
                    cwd=str(other))["environments"]
    assert str(venv / "bin" / "python") in [r["executable"] for r in rows]


# --- Phrase: "Output: same format as `env list`, but only virtualenvs."
def test_find_virtualenvs_row_shape_and_flag(tmp_path):
    root = tmp_path / "envs"
    root.mkdir()
    fake_venv(root, "one")
    rows = env_virtualenvs(str(tmp_path), "--path", str(root))
    assert rows
    for row in rows:
        assert set(row) == {"executable", "version", "is_virtualenv"}
        assert row["is_virtualenv"] is True


# --- Phrase: "Sort environments by version descending" holds here too.
def test_find_virtualenvs_is_sorted(tmp_path):
    root = tmp_path / "envs"
    root.mkdir()
    fake_venv(root, "bbb")
    fake_venv(root, "aaa")
    rows = env_virtualenvs(str(tmp_path), "--path", str(root))
    keys = [(tuple(-int(p) for p in r["version"].split(".")), r["executable"])
            for r in rows]
    assert keys == sorted(keys)
    assert len(rows) >= 2


# --- Phrase: a directory without `bin/python` is not a virtualenv.
def test_find_virtualenvs_skips_plain_directories(tmp_path):
    root = tmp_path / "envs"
    (root / "notanenv").mkdir(parents=True)
    rows = env_virtualenvs(str(tmp_path), "--path", str(root))
    assert all("notanenv" not in r["executable"] for r in rows)


# --- Phrase: "python sith.py env info [<executable>]" — details about a
#     specific environment.
def test_env_info_for_an_explicit_executable(tmp_path):
    data = env_info(PY, cwd=str(tmp_path))
    assert data["executable"] == PY or os.path.samefile(data["executable"], PY)
    assert data["version"] == "%d.%d.%d" % sys.version_info[:3]


# --- Phrase: "Additional field vs `env list`: `prefix` — sys.prefix of the
#     environment; `sys_path` — the environment's sys.path."
def test_env_info_fields(tmp_path):
    data = env_info(PY, cwd=str(tmp_path))
    assert set(data) == {"executable", "version", "is_virtualenv", "prefix",
                         "sys_path"}
    assert isinstance(data["sys_path"], list)
    assert all(isinstance(p, str) for p in data["sys_path"])
    assert data["prefix"] == sys.prefix


# --- Phrase: "If `<executable>` is omitted, use the system default
#     (`python3`)."
def test_env_info_defaults_to_python3(tmp_path):
    data = env_info(cwd=str(tmp_path))
    assert data["executable"].endswith("python3") or \
        os.path.basename(data["executable"]).startswith("python")
    assert data["version"].count(".") == 2


# --- Phrase: "If the executable is not found or not a valid Python, exit 1."
def test_env_info_missing_executable(tmp_path):
    proc = run_raw("env", "info", str(tmp_path / "nope"), cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip()


def test_env_info_not_a_python(tmp_path):
    bogus = tmp_path / "fake"
    bogus.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    os.chmod(str(bogus), 0o755)
    proc = run_raw("env", "info", str(bogus), cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: `is_virtualenv` — "true if the environment is a virtualenv/venv."
def test_env_info_reports_virtualenv(tmp_path):
    venv = fake_venv(tmp_path, ".venv")
    data = env_info(str(venv / "bin" / "python"), cwd=str(tmp_path))
    assert data["is_virtualenv"] is True
    assert data["prefix"] == str(venv)


def test_env_info_reports_non_virtualenv(tmp_path):
    data = env_info(PY, cwd=str(tmp_path))
    assert isinstance(data["is_virtualenv"], bool)


# --- Phrase: "`env` subcommands are read-only discovery commands" — they never
#     write a project configuration.
def test_env_commands_write_nothing(tmp_path):
    env_list(cwd=str(tmp_path))
    env_virtualenvs(str(tmp_path))
    env_info(PY, cwd=str(tmp_path))
    assert not (tmp_path / ".sith").exists()


# --- Phrase: an unknown `env` subcommand is a usage error.
def test_unknown_env_subcommand(tmp_path):
    proc = run_raw("env", "bogus", cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_env_requires_a_subcommand(tmp_path):
    proc = run_raw("env", cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: output framing — one compact newline-terminated JSON object.
def test_env_output_framing(tmp_path):
    proc = run_raw("env", "list", cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.endswith("\n")
    assert proc.stdout.count("\n") == 1
    assert ", " not in proc.stdout
    json.loads(proc.stdout)


# --- Phrase: "`environment_path` selects which Python executable to use when a
#     command consults project environment metadata."
def test_env_info_uses_the_project_environment(tmp_path):
    venv = fake_venv(tmp_path, ".venv")
    write_config(tmp_path, {"environment_path": str(venv / "bin" / "python")})
    data = env_info(cwd=str(tmp_path))
    assert data["executable"] == str(venv / "bin" / "python")
    assert data["prefix"] == str(venv)


# --- Phrase: "If null or empty string, use the system default."
def test_env_info_empty_environment_path_falls_back(tmp_path):
    write_config(tmp_path, {"environment_path": ""})
    data = env_info(cwd=str(tmp_path))
    assert os.path.basename(data["executable"]).startswith("python")
