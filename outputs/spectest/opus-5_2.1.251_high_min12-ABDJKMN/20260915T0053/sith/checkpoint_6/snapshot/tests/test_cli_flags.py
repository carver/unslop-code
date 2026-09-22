"""Spec section: CLI surface of `--project` and `--follow-imports`."""
import json

from conftest import CURSOR, run_cmd, run_raw, write_tree

C = CURSOR


# --- Phrase: "All commands now accept an optional `--project <dir>` flag."
#     Context: the flag may appear before the positional arguments.
def test_project_flag_before_positionals(tmp_path):
    write_tree(tmp_path, {"main.py": "x = 1\n"})
    proc = run_raw("infer", "--project", str(tmp_path), str(tmp_path / "main.py"),
                   1, 0, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["definitions"][0]["name"] == "int"


# --- Phrase: "`--project <dir>`"
#     Context: `--project=<dir>` spelling is accepted as well.
def test_project_flag_equals_spelling(tmp_path):
    write_tree(tmp_path, {"main.py": "x = 1\n"})
    proc = run_raw("infer", str(tmp_path / "main.py"), 1, 0,
                   "--project=%s" % tmp_path, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr


# --- Phrase: "`--project <dir>`"
#     Context: a missing value for the flag is a usage error.
def test_project_flag_without_value_errors(tmp_path):
    write_tree(tmp_path, {"main.py": "x = 1\n"})
    proc = run_raw("infer", str(tmp_path / "main.py"), 1, 0, "--project",
                   cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("sith:")


# --- Phrase: "`--project <dir>`" - the dir is a project root
#     Context: pointing at a directory that does not exist is an error.
def test_project_dir_must_exist(tmp_path):
    write_tree(tmp_path, {"main.py": "x = 1\n"})
    proc = run_cmd("infer", tmp_path / "main.py", 1, 0,
                   project=tmp_path / "nowhere", cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stderr.startswith("sith:")


# --- Phrase: "python sith.py goto <file> <line> <col> [--follow-imports]"
#     Context: `--follow-imports` is accepted by `goto`.
def test_follow_imports_flag_accepted(tmp_path):
    write_tree(tmp_path, {"main.py": "x = 1\nx\n"})
    proc = run_cmd("goto", tmp_path / "main.py", 2, 0, follow=True,
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr


# --- Phrase: "All commands now accept an optional `--project <dir>` flag."
#     Context: `--project` combines with `--fuzzy` and `--follow-imports`.
def test_flags_combine(tmp_path):
    write_tree(tmp_path, {"helper.py": "def greet():\n    pass\n",
                          "main.py": "from helper import greet\ngreet\n"})
    proc = run_cmd("goto", tmp_path / "main.py", 2, 0, project=tmp_path,
                   follow=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)["definitions"][0]
    assert got["module_path"] == "helper.py"

    proc = run_cmd("complete", tmp_path / "main.py", 2, 5, project=tmp_path,
                   fuzzy=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr


# --- Phrase: "unknown command / usage"
#     Context: an unrecognised flag is still a usage error.
def test_unknown_flag_errors(tmp_path):
    write_tree(tmp_path, {"main.py": "x = 1\n"})
    proc = run_raw("infer", str(tmp_path / "main.py"), 1, 0, "--nope",
                   cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stderr.startswith("sith:")
