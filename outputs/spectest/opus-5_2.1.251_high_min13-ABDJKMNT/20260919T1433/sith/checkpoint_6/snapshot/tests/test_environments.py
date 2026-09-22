"""Spec: Environment Commands."""

import json
import sys
from pathlib import Path

from conftest import run_command, write_virtualenv

CURRENT = ".".join(str(part) for part in sys.version_info[:3])


def environments(*arguments, flags=(), home=None, cwd=None):
    """The `environments` array of an `env` subcommand."""
    result = run_command("env", *arguments, flags=flags, home=home, cwd=cwd)
    assert result.code == 0, result.stderr
    return result.data["environments"]


def executables(*arguments, **options):
    """The executable paths an `env` subcommand reports."""
    return [item["executable"] for item in environments(*arguments, **options)]


# Spec: "python sith.py env list" - "Find and list available Python
# installations on the system."
def test_env_list_reports_installations():
    listed = environments("list")
    assert listed
    assert all(Path(item["executable"]).is_absolute() for item in listed)


# Spec: "`executable` | string | Absolute path to the Python executable."
# "`version` | string | Python version string (e.g., `"3.11.6"`)."
# "`is_virtualenv` | bool | `true` if the environment is a virtualenv/venv."
def test_env_list_fields():
    item = environments("list")[0]
    assert list(item) == ["executable", "version", "is_virtualenv"]
    assert isinstance(item["is_virtualenv"], bool)
    assert item["version"].split(".")[0].isdigit()


# Spec: "Sort environments by version descending (newest first)."
def test_env_list_is_sorted_by_version_descending():
    versions = [
        tuple(int(part) for part in item["version"].split(".") if part.isdigit())
        for item in environments("list")
    ]
    assert versions == sorted(versions, reverse=True)


# Spec: "For equal versions, sort by executable path ascending."
def test_equal_versions_are_sorted_by_path():
    listed = environments("list")
    keyed = [(item["version"], item["executable"]) for item in listed]
    for earlier, later in zip(keyed, keyed[1:]):
        if earlier[0] == later[0]:
            assert earlier[1] < later[1]


# Spec: "Deduplicate by resolved executable path (follow symlinks)."
def test_environments_are_deduplicated_by_resolved_path():
    resolved = [str(Path(item["executable"]).resolve()) for item in environments("list")]
    assert len(resolved) == len(set(resolved))


# Spec: "python sith.py env find-virtualenvs [--path <dir>]" - "The directory
# specified by `--path` (if given) - look for `bin/python` (Unix) ... inside
# immediate subdirectories."
def test_find_virtualenvs_searches_immediate_subdirectories(tmp_path):
    write_virtualenv(tmp_path / "envs" / "alpha")
    found = executables("find-virtualenvs", flags=["--path", str(tmp_path / "envs")])
    assert str(tmp_path / "envs" / "alpha" / "bin" / "python") in found


def test_a_subdirectory_without_an_interpreter_is_not_a_virtualenv(tmp_path):
    (tmp_path / "envs" / "plain").mkdir(parents=True)
    found = executables("find-virtualenvs", flags=["--path", str(tmp_path / "envs")])
    assert not any(str(tmp_path) in path for path in found)


def test_find_virtualenvs_does_not_descend_past_immediate_subdirectories(tmp_path):
    write_virtualenv(tmp_path / "envs" / "deep" / "alpha")
    found = executables("find-virtualenvs", flags=["--path", str(tmp_path / "envs")])
    assert str(tmp_path / "envs" / "deep" / "alpha" / "bin" / "python") not in found


# Spec: "Output: same format as `env list`, but only virtualenvs."
def test_found_virtualenvs_use_the_env_list_format(tmp_path):
    write_virtualenv(tmp_path / "envs" / "alpha")
    wanted = str(tmp_path / "envs" / "alpha" / "bin" / "python")
    found = environments("find-virtualenvs", flags=["--path", str(tmp_path / "envs")])
    item = next(item for item in found if item["executable"] == wanted)
    assert list(item) == ["executable", "version", "is_virtualenv"]
    assert item["is_virtualenv"] is True
    assert item["version"] == CURRENT


# Spec: "`.venv/` and `venv/` in the current directory and project root."
def test_dot_venv_in_the_project_root_is_found(tmp_path):
    write_virtualenv(tmp_path / ".venv")
    found = executables("find-virtualenvs", flags=["--project", str(tmp_path)])
    assert str(tmp_path / ".venv" / "bin" / "python") in found


def test_venv_in_the_project_root_is_found(tmp_path):
    write_virtualenv(tmp_path / "venv")
    found = executables("find-virtualenvs", flags=["--project", str(tmp_path)])
    assert str(tmp_path / "venv" / "bin" / "python") in found


# Spec: "`.venv/` and `venv/` in the current directory and project root."
def test_dot_venv_in_the_current_directory_is_found(tmp_path):
    write_virtualenv(tmp_path / ".venv")
    found = executables("find-virtualenvs", cwd=tmp_path)
    assert str(tmp_path / ".venv" / "bin" / "python") in found


# Spec: "`~/.virtualenvs/` (virtualenvwrapper convention)."
def test_the_virtualenvs_home_directory_is_searched(tmp_path):
    write_virtualenv(tmp_path / ".virtualenvs" / "wrapped")
    found = executables("find-virtualenvs", home=tmp_path)
    assert str(tmp_path / ".virtualenvs" / "wrapped" / "bin" / "python") in found


# Spec: "python sith.py env info [<executable>]" - "Show details about a
# specific Python environment."
def test_env_info_describes_a_named_executable():
    result = run_command("env", "info", sys.executable)
    assert result.code == 0
    assert result.data["executable"] == sys.executable
    assert result.data["version"] == CURRENT


# Spec: "`prefix` | string | `sys.prefix` of the environment."
# "`sys_path` | array of string | The environment's `sys.path`."
def test_env_info_adds_prefix_and_sys_path():
    payload = run_command("env", "info", sys.executable).data
    assert list(payload) == ["executable", "version", "is_virtualenv", "prefix", "sys_path"]
    assert payload["prefix"] == sys.prefix
    assert isinstance(payload["sys_path"], list)
    assert all(isinstance(entry, str) for entry in payload["sys_path"])


# Spec: "If `<executable>` is omitted, use the system default (`python3`)."
def test_env_info_defaults_to_the_system_python():
    payload = run_command("env", "info").data
    assert Path(payload["executable"]).name.startswith("python")
    assert payload["version"].split(".")[0].isdigit()


# Spec: "`is_virtualenv` | bool | `true` if the environment is a
# virtualenv/venv."
def test_env_info_marks_a_virtualenv(tmp_path):
    write_virtualenv(tmp_path / ".venv")
    payload = run_command("env", "info", tmp_path / ".venv" / "bin" / "python").data
    assert payload["is_virtualenv"] is True
    assert payload["prefix"] == str(tmp_path / ".venv")


# Spec: "If the executable is not found or not a valid Python, exit 1."
def test_a_missing_executable_exits_one(tmp_path):
    result = run_command("env", "info", tmp_path / "nowhere" / "python")
    assert result.code == 1
    assert result.stderr.strip()


def test_an_executable_that_is_not_python_exits_one(tmp_path):
    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    fake.chmod(0o755)
    result = run_command("env", "info", fake)
    assert result.code == 1


# Spec: "Output is JSON to STDOUT" - the `env` answers keep the shared format.
def test_env_output_is_compact_and_newline_terminated():
    result = run_command("env", "list")
    assert result.stdout.endswith("\n")
    assert result.stdout.rstrip("\n") == json.dumps(
        json.loads(result.stdout), separators=(",", ":")
    )
