"""The read-only `env` discovery commands."""
import os
import shutil
import subprocess
import sys

from conftest import run_cli

VERSION_FIELDS = {"executable", "version", "is_virtualenv"}


def versions(result):
    return [tuple(int(p) for p in e["version"].split(".")) for e in result.environments]


def make_virtualenv(path, copies=False):
    """A real virtualenv; `copies` gives it an interpreter of its own to resolve to."""
    flags = ["--copies"] if copies else []
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", *flags, str(path)],
        check=True, capture_output=True,
    )
    return path


# "python sith.py env list" / "Find and list available Python installations on the system."
def test_env_list_succeeds_and_finds_something(workdir):
    result = run_cli("env", "list", cwd=workdir)
    assert result.returncode == 0, result.stderr
    assert result.environments != []


# "| `executable` | string | Absolute path to the Python executable. |"
# "| `version` | string | Python version string (e.g., `\"3.11.6\"`). |"
# "| `is_virtualenv` | bool | `true` if the environment is a virtualenv/venv. |"
def test_env_list_field_set(workdir):
    for environment in run_cli("env", "list", cwd=workdir).environments:
        assert set(environment) == VERSION_FIELDS
        assert os.path.isabs(environment["executable"])
        assert environment["version"].split(".")[0].isdigit()
        assert isinstance(environment["is_virtualenv"], bool)


# "Sort environments by version descending (newest first)."
def test_env_list_is_sorted_by_version_descending(workdir):
    found = versions(run_cli("env", "list", cwd=workdir))
    assert found == sorted(found, reverse=True)


# "For equal versions, sort by executable path ascending."
def test_equal_versions_sort_by_executable_path(workdir):
    make_virtualenv(workdir / "venv", copies=True)
    make_virtualenv(workdir / ".venv", copies=True)
    result = run_cli("env", "list", cwd=workdir)
    paths = [e["executable"] for e in result.environments if e["version"] == _version()]
    assert paths == sorted(paths)


def _version():
    return ".".join(str(part) for part in sys.version_info[:3])


# "Deduplicate by resolved executable path (follow symlinks)."
def test_env_list_has_no_duplicate_installations(workdir):
    found = run_cli("env", "list", cwd=workdir).environments
    resolved = [os.path.realpath(e["executable"]) for e in found]
    assert len(set(resolved)) == len(resolved)


# "python sith.py env find-virtualenvs [--path <dir>]"
# "1. The directory specified by `--path` (if given) -- look for `bin/python` (Unix)
#     ... inside immediate subdirectories."
def test_find_virtualenvs_searches_the_given_path(workdir, tmp_path):
    made = make_virtualenv(tmp_path / "pool" / "project-env")
    result = run_cli("env", "find-virtualenvs", "--path", str(tmp_path / "pool"), cwd=workdir)
    assert result.returncode == 0, result.stderr
    found = [os.path.realpath(e["executable"]) for e in result.environments]
    assert os.path.realpath(made / "bin" / "python") in found


def test_find_virtualenvs_ignores_subdirectories_without_an_interpreter(workdir, tmp_path):
    (tmp_path / "pool" / "not-an-env").mkdir(parents=True)
    result = run_cli("env", "find-virtualenvs", "--path", str(tmp_path / "pool"), cwd=workdir)
    assert [e for e in result.environments if "not-an-env" in e["executable"]] == []


# "3. `.venv/` and `venv/` in the current directory and project root."
def test_find_virtualenvs_finds_dot_venv_in_the_current_directory(workdir):
    make_virtualenv(workdir / ".venv")
    found = run_cli("env", "find-virtualenvs", cwd=workdir).environments
    assert [e for e in found if str(workdir) in e["executable"]] != []


def test_find_virtualenvs_finds_venv_in_the_current_directory(workdir):
    make_virtualenv(workdir / "venv")
    found = run_cli("env", "find-virtualenvs", cwd=workdir).environments
    assert [e for e in found if os.path.join(str(workdir), "venv") in e["executable"]] != []


# "Output: same format as `env list`, but only virtualenvs."
def test_find_virtualenvs_reports_only_virtualenvs(workdir):
    make_virtualenv(workdir / ".venv")
    found = run_cli("env", "find-virtualenvs", cwd=workdir).environments
    assert found != []
    for environment in found:
        assert set(environment) == VERSION_FIELDS
        assert environment["is_virtualenv"] is True


# "python sith.py env info [<executable>]" / "Show details about a specific Python
#  environment."
def test_env_info_reports_the_named_executable(workdir, virtualenv):
    executable = str(virtualenv / "bin" / "python")
    payload = run_cli("env", "info", executable, cwd=workdir).payload
    assert payload["environment"]["executable"] == executable
    assert payload["environment"]["is_virtualenv"] is True


# "Additional field vs `env list`: | `prefix` | string | `sys.prefix` of the
#  environment. | `sys_path` | array of string | The environment's `sys.path`. |"
def test_env_info_adds_prefix_and_sys_path(workdir, virtualenv):
    environment = run_cli(
        "env", "info", str(virtualenv / "bin" / "python"), cwd=workdir
    ).payload["environment"]
    assert set(environment) == VERSION_FIELDS | {"prefix", "sys_path"}
    assert environment["prefix"] == str(virtualenv)
    assert isinstance(environment["sys_path"], list)
    assert all(isinstance(entry, str) for entry in environment["sys_path"])


# "If `<executable>` is omitted, use the system default (`python3`)."
def test_env_info_defaults_to_the_system_python(workdir):
    result = run_cli("env", "info", cwd=workdir)
    assert result.returncode == 0, result.stderr
    assert result.payload["environment"]["executable"] == shutil.which("python3")


# "If the executable is not found or not a valid Python, exit 1."
def test_env_info_on_a_missing_executable_exits_one(workdir):
    result = run_cli("env", "info", str(workdir / "no-such-python"), cwd=workdir)
    assert result.returncode == 1
    assert result.stderr.strip() != ""


def test_env_info_on_a_file_that_is_not_python_exits_one(workdir):
    impostor = workdir / "python"
    impostor.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    impostor.chmod(0o755)
    assert run_cli("env", "info", str(impostor), cwd=workdir).returncode == 1


# "`env` subcommands are read-only discovery commands; only `project init` writes
#  project configuration."
def test_env_commands_write_nothing(workdir):
    run_cli("env", "list", cwd=workdir)
    run_cli("env", "find-virtualenvs", cwd=workdir)
    run_cli("env", "info", cwd=workdir)
    assert list(workdir.iterdir()) == []
