"""CLI surface shared by the refactoring commands."""
import json

from conftest import run_cli


# "For `--diff`, stdout is unified diff text only (no JSON envelope)."
def test_rename_diff_is_not_json(rename):
    stdout = rename("va|lue = 1\nprint(value)\n", new_name="total", diff=True).stdout
    assert "changed_files" not in stdout


# "All refactoring commands that accept `--diff` (`rename`, `inline`,
#  `extract-variable`, `extract-function`) use the same plain-text unified diff format."
def test_every_refactoring_diff_has_the_same_shape(rename, inline, extract_variable,
                                                   extract_function):
    outputs = [
        rename("va|lue = 1\nprint(value)\n", new_name="total", diff=True).stdout,
        inline("x| = 1\nprint(x)\n", diff=True).stdout,
        extract_variable("x = |a + b$\n", name="total", diff=True).stdout,
        extract_function("def f(a):\n    |print(a)$\n", name="show", diff=True).stdout,
    ]
    for stdout in outputs:
        lines = stdout.split("\n")
        assert lines[0].startswith("--- ")
        assert lines[1].startswith("+++ ")
        assert any(line.startswith("@@") for line in lines)
        assert stdout.endswith("\n")


# "Output is JSON to STDOUT ... Compact format: no extra whitespace."
def test_refactoring_json_is_compact(rename):
    stdout = rename("va|lue = 1\nprint(value)\n", new_name="total").stdout
    assert stdout.rstrip("\n") == json.dumps(json.loads(stdout), separators=(",", ":"))


def test_refactoring_json_ends_with_one_newline(rename):
    stdout = rename("va|lue = 1\nprint(value)\n", new_name="total").stdout
    assert stdout.endswith("\n")
    assert not stdout[:-1].endswith("\n")


# "`changed_files` must include only files whose content actually changed."
def test_a_rename_that_changes_nothing_reports_no_files(rename):
    files = {"other.py": "value = 2\n"}
    result = rename("va|lue = 1\n", files=files, new_name="total")
    assert list(result.changed_files) == ["sample.py"]


# "[--project <dir>]"
def test_project_defaults_to_the_files_own_directory(workdir):
    (workdir / "pkg").mkdir()
    (workdir / "pkg" / "mod.py").write_text("value = 1\nprint(value)\n", encoding="utf-8")
    result = run_cli("rename", str(workdir / "pkg" / "mod.py"), 1, 0, "--new-name", "total",
                     cwd=workdir)
    assert result.returncode == 0
    assert list(result.changed_files) == ["mod.py"]


# "python sith.py <command> ..." - an unknown command is a usage failure.
def test_an_unknown_command_fails():
    assert run_cli("refactor").returncode == 1


def test_a_malformed_until_is_rejected(workdir):
    (workdir / "a.py").write_text("x = a + b\n", encoding="utf-8")
    result = run_cli("extract-variable", str(workdir / "a.py"), 1, 4, "--until", "nine",
                     "--name", "t", cwd=workdir)
    assert result.returncode == 1
