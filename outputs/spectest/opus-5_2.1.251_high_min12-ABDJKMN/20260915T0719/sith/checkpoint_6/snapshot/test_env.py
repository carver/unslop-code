"""`env list` / `env find-virtualenvs` / `env info` -- spec: "Environment Commands".

Ambient Python installations differ from machine to machine, so these tests pin
down the shape and the ordering rules rather than a fixed inventory.  See
AMBIGUITIES.md T98-T105.
"""

import json
import os
import sys

import pytest

from conftest import env_json, env_raw, fake_venv, run_raw


def version_key(text):
    parts = []
    for chunk in (text or "").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def entries(payload):
    return payload["environments"]


# =====================================================================
# "python sith.py env list" / "Find and list available Python installations
#  on the system."
# =====================================================================

def test_env_list_exits_zero_and_emits_environments():
    r = env_raw(["list"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    payload = json.loads(r.stdout)
    assert isinstance(payload["environments"], list)


def test_env_list_finds_at_least_one_installation():
    assert len(entries(env_json(["list"]))) >= 1


# "| `executable` | string | Absolute path to the Python executable. |"
def test_every_executable_is_an_absolute_path():
    for env in entries(env_json(["list"])):
        assert os.path.isabs(env["executable"]), env


def test_every_executable_exists_on_disk():
    for env in entries(env_json(["list"])):
        assert os.path.exists(env["executable"]), env


# "| `version` | string | Python version string (e.g., "3.11.6"). |" (T101)
def test_version_is_a_dotted_numeric_string():
    for env in entries(env_json(["list"])):
        assert isinstance(env["version"], str)
        assert version_key(env["version"])[0] >= 2, env


# "| `is_virtualenv` | bool | `true` if the environment is a virtualenv/venv. |"
def test_is_virtualenv_is_a_boolean():
    for env in entries(env_json(["list"])):
        assert isinstance(env["is_virtualenv"], bool), env


def test_entries_carry_exactly_the_documented_fields():
    for env in entries(env_json(["list"])):
        assert set(env) == {"executable", "version", "is_virtualenv"}


# "Sort environments by version descending (newest first)."
def test_sorted_by_version_descending():
    got = [version_key(e["version"]) for e in entries(env_json(["list"]))]
    assert got == sorted(got, reverse=True)


# "For equal versions, sort by executable path ascending."
def test_equal_versions_sort_by_executable_ascending():
    envs = entries(env_json(["list"]))
    keys = [(version_key(e["version"]), e["executable"]) for e in envs]
    for before, after in zip(keys, keys[1:]):
        if before[0] == after[0]:
            assert before[1] <= after[1]


# "Deduplicate by resolved executable path (follow symlinks)." (T99)
def test_no_duplicate_entries():
    paths = [e["executable"] for e in entries(env_json(["list"]))]
    assert len(paths) == len(set(paths))


def test_no_two_entries_share_a_resolved_path_unless_a_virtualenv():
    seen = {}
    for env in entries(env_json(["list"])):
        if env["is_virtualenv"]:
            continue
        real = os.path.realpath(env["executable"])
        assert real not in seen, (real, env, seen.get(real))
        seen[real] = env


# T98: the interpreter running the tool is itself an available installation.
def test_the_running_interpreter_is_listed():
    paths = {os.path.realpath(e["executable"])
             for e in entries(env_json(["list"]))}
    assert os.path.realpath(sys.executable) in paths


# =====================================================================
# "python sith.py env find-virtualenvs [--path <dir>]"
# =====================================================================

# "1. The directory specified by `--path` (if given) -- look for `bin/python`
#     (Unix) ... inside immediate subdirectories."
def test_find_virtualenvs_finds_venvs_under_path(tmp_path):
    exe = fake_venv(tmp_path, "myenv")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs", "--path", str(tmp_path)]))]
    assert str(exe) in found


def test_find_virtualenvs_finds_several(tmp_path):
    a = fake_venv(tmp_path, "aenv", version="3.10.0")
    b = fake_venv(tmp_path, "benv", version="3.12.1")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs", "--path", str(tmp_path)]))]
    assert str(a) in found and str(b) in found


# "Output: same format as `env list`, but only virtualenvs."
def test_found_entries_are_all_flagged_as_virtualenvs(tmp_path):
    fake_venv(tmp_path, "myenv")
    for env in entries(env_json(["find-virtualenvs", "--path", str(tmp_path)])):
        assert env["is_virtualenv"] is True


def test_found_entries_use_the_env_list_fields(tmp_path):
    fake_venv(tmp_path, "myenv")
    for env in entries(env_json(["find-virtualenvs", "--path", str(tmp_path)])):
        assert set(env) == {"executable", "version", "is_virtualenv"}


def test_found_entries_are_sorted_by_version_descending(tmp_path):
    fake_venv(tmp_path, "aenv", version="3.9.7")
    fake_venv(tmp_path, "benv", version="3.12.1")
    got = [version_key(e["version"]) for e in entries(
        env_json(["find-virtualenvs", "--path", str(tmp_path)]))]
    assert got == sorted(got, reverse=True)


# T102: the layout is what makes it a virtualenv; the version comes from
# pyvenv.cfg when the executable cannot answer for itself.
def test_version_is_read_from_pyvenv_cfg(tmp_path):
    exe = fake_venv(tmp_path, "myenv", version="3.11.6")
    found = entries(env_json(["find-virtualenvs", "--path", str(tmp_path)]))
    mine = [e for e in found if e["executable"] == str(exe)]
    assert mine and mine[0]["version"] == "3.11.6"


def test_directories_without_bin_python_are_ignored(tmp_path):
    (tmp_path / "not_an_env").mkdir()
    (tmp_path / "not_an_env" / "bin").mkdir()
    fake_venv(tmp_path, "real_env")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs", "--path", str(tmp_path)]))]
    assert not any("not_an_env" in p for p in found)


def test_only_immediate_subdirectories_are_searched(tmp_path):
    deep = tmp_path / "outer" / "inner"
    deep.mkdir(parents=True)
    fake_venv(deep, "nested")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs", "--path", str(tmp_path)]))]
    assert not any("nested" in p for p in found)


def test_missing_path_directory_is_not_fatal(tmp_path):
    r = env_raw(["find-virtualenvs", "--path", str(tmp_path / "nope")])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# "2. `~/.virtualenvs/` ... 3. `.venv/` and `venv/` in the current directory
#  and project root."  Without --path the command still works and reports only
#  virtualenvs.
def test_find_virtualenvs_without_path_reports_only_virtualenvs():
    for env in entries(env_json(["find-virtualenvs"])):
        assert env["is_virtualenv"] is True


def test_dot_venv_in_the_current_directory_is_found(tmp_path):
    exe = fake_venv(tmp_path, ".venv")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs"], cwd=str(tmp_path)))]
    assert str(exe) in found


def test_plain_venv_in_the_current_directory_is_found(tmp_path):
    exe = fake_venv(tmp_path, "venv")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs"], cwd=str(tmp_path)))]
    assert str(exe) in found


def test_dot_venv_in_the_project_root_is_found(tmp_path):
    exe = fake_venv(tmp_path, ".venv")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs", "--project", str(tmp_path)]))]
    assert str(exe) in found


def test_a_venv_is_reported_once_even_when_two_sources_find_it(tmp_path):
    exe = fake_venv(tmp_path, ".venv")
    found = [e["executable"] for e in entries(
        env_json(["find-virtualenvs", "--path", str(tmp_path),
                  "--project", str(tmp_path)], cwd=str(tmp_path)))]
    assert found.count(str(exe)) == 1


# =====================================================================
# "python sith.py env info [<executable>]"
# =====================================================================

def test_env_info_of_an_explicit_executable():
    payload = env_json(["info", sys.executable])
    assert payload["version"] == "%d.%d.%d" % sys.version_info[:3]


def test_env_info_reports_the_prefix():
    payload = env_json(["info", sys.executable])
    assert payload["prefix"] == sys.prefix


# "| `sys_path` | array of string | The environment's `sys.path`. |"
def test_env_info_reports_sys_path():
    payload = env_json(["info", sys.executable])
    assert isinstance(payload["sys_path"], list)
    assert all(isinstance(p, str) for p in payload["sys_path"])
    assert len(payload["sys_path"]) >= 1


# "Additional field vs `env list`" -- so the `env list` fields are there too.
def test_env_info_carries_the_env_list_fields():
    payload = env_json(["info", sys.executable])
    assert os.path.isabs(payload["executable"])
    assert isinstance(payload["is_virtualenv"], bool)


def test_env_info_flags_a_virtualenv():
    payload = env_json(["info", sys.executable])
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    assert payload["is_virtualenv"] is in_venv


# "If `<executable>` is omitted, use the system default (`python3`)." (T104)
def test_env_info_without_an_argument_works():
    payload = env_json(["info"])
    assert payload["version"]
    assert os.path.isabs(payload["executable"])


# T105: a bare name is resolved on PATH.
def test_env_info_accepts_a_bare_command_name():
    r = env_raw(["info", "python3"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# "If the executable is not found or not a valid Python, exit 1."
def test_env_info_of_a_missing_executable_exits_1(tmp_path):
    r = env_raw(["info", str(tmp_path / "no_such_python")])
    assert r.returncode == 1
    assert r.stderr.strip()


def test_env_info_of_a_non_python_exits_1(tmp_path):
    bogus = tmp_path / "python"
    bogus.write_text("#!/bin/sh\necho not python\n", encoding="utf-8")
    bogus.chmod(0o755)
    r = env_raw(["info", str(bogus)])
    assert r.returncode == 1


def test_env_info_of_a_missing_executable_prints_nothing(tmp_path):
    r = env_raw(["info", str(tmp_path / "no_such_python")])
    assert r.stdout.strip() == ""


# =====================================================================
# "`env` subcommands are read-only discovery commands"
# =====================================================================

def test_env_commands_do_not_write_project_config(tmp_path):
    fake_venv(tmp_path, ".venv")
    env_raw(["list"], cwd=str(tmp_path))
    env_raw(["find-virtualenvs", "--path", str(tmp_path)], cwd=str(tmp_path))
    env_raw(["info"], cwd=str(tmp_path))
    assert not (tmp_path / ".sith").exists()


def test_unknown_env_subcommand_exits_1():
    r = env_raw(["frobnicate"])
    assert r.returncode == 1


def test_env_without_a_subcommand_exits_1():
    r = run_raw(["env"])
    assert r.returncode == 1
