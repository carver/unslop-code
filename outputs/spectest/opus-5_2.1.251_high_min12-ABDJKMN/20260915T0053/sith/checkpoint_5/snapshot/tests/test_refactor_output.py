"""Spec section: the shared output rules of the refactoring commands."""
import json

import pytest

from conftest import (CURSOR, rename_raw, rename_in, inline_raw,
                      extract_var_raw, extract_fn_raw, changed, run_raw)

C = CURSOR


def _is_json(text):
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


# --- Phrase: "For `--diff`, stdout is unified diff text only (no JSON
#     envelope)."
def test_diff_is_not_json(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    proc = rename_raw(tmp_path, files, "total", diff=True)
    assert proc.returncode == 0, proc.stderr
    assert not _is_json(proc.stdout)


# --- Phrase: "With `--diff`: Output a unified diff instead of full file
#     contents".
def test_diff_shows_removed_and_added_lines(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    out = rename_raw(tmp_path, files, "total", diff=True).stdout
    assert "-value = 1" in out
    assert "+total = 1" in out
    assert "-print(value)" in out
    assert "+print(total)" in out


def test_diff_has_unified_headers(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    out = rename_raw(tmp_path, files, "total", diff=True).stdout
    lines = out.splitlines()
    assert lines[0].startswith("--- ")
    assert lines[1].startswith("+++ ")
    assert "example.py" in lines[0] and "example.py" in lines[1]
    assert any(ln.startswith("@@") for ln in lines)


def test_diff_covers_every_changed_file(tmp_path):
    files = {
        "lib.py": "def hel" + C + "per():\n    return 1\n",
        "main.py": "from lib import helper\n\nprint(helper())\n",
    }
    out = rename_raw(tmp_path, files, "worker", diff=True).stdout
    assert out.count("--- ") == 2
    assert "lib.py" in out and "main.py" in out


# --- Phrase: "All refactoring commands that accept `--diff` (`rename`,
#     `inline`, `extract-variable`, `extract-function`) use the same plain-text
#     unified diff format."
def test_every_command_uses_the_same_diff_format(tmp_path):
    outs = []
    outs.append(rename_raw(
        tmp_path / "a", {"example.py": "val" + C + "ue = 1\nprint(value)\n"},
        "total", diff=True).stdout)
    outs.append(inline_raw(
        tmp_path / "b", {"example.py": "x" + C + " = 1\nprint(x)\n"},
        diff=True).stdout)
    outs.append(extract_var_raw(
        tmp_path / "c", {"example.py": "value = " + C + "1 + 2\n"},
        "1:13", "total", diff=True).stdout)
    outs.append(extract_fn_raw(
        tmp_path / "d",
        {"example.py": "def outer():\n    a = 1\n    " + C + "b = a + 1\n"
                       "    return b\n"},
        "3:13", "compute", diff=True).stdout)
    for out in outs:
        lines = out.splitlines()
        assert lines[0].startswith("--- "), out
        assert lines[1].startswith("+++ "), out
        assert any(ln.startswith("@@") for ln in lines), out
        assert not _is_json(out)


# --- Phrase: "`changed_files` must include only files whose content actually
#     changed."
def test_changed_files_excludes_untouched_files(tmp_path):
    files = {
        "example.py": "val" + C + "ue = 1\nprint(value)\n",
        "unrelated.py": "value = 99\n",
        "empty.py": "",
    }
    data = rename_in(tmp_path, files, "total")
    assert list(changed(data)) == ["example.py"]


# --- Phrase: "Validation failures (`invalid name`, `cursor not on name`,
#     invalid selection) exit 1 and must not emit partial edit output."
def test_invalid_name_emits_nothing(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    proc = rename_raw(tmp_path, files, "1bad")
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_cursor_not_on_name_emits_nothing(tmp_path):
    files = {"example.py": "value = 1\n" + C + "\n"}
    proc = rename_raw(tmp_path, files, "total")
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_invalid_selection_emits_nothing(tmp_path):
    files = {"example.py": "value = " + C + "foo(1) + 2\n"}
    proc = extract_var_raw(tmp_path, files, "1:13", "call")
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_invalid_name_wins_over_a_bad_cursor(tmp_path):
    files = {"example.py": "value = " + C + "1\n"}
    proc = rename_raw(tmp_path, files, "1bad")
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: "Parenthesis insertion for `inline` is required whenever dropping
#     parentheses would change operator precedence in the transformed code."
@pytest.mark.parametrize("value,use,want", [
    ("a + b", "total * 2", "(a + b) * 2"),
    ("a * b", "total + 2", "a * b + 2"),
    ("a or b", "total and c", "(a or b) and c"),
    ("a ** b", "total ** c", "(a ** b) ** c"),
    ("not a", "total or b", "not a or b"),
    ("a + b", "total[0]", "(a + b)[0]"),
    ("a + b", "total(1)", "(a + b)(1)"),
    ("lambda: 1", "total()", "(lambda: 1)()"),
])
def test_inline_parenthesises_only_when_needed(tmp_path, value, use, want):
    code = "tot" + C + "al = %s\nresult = %s\n" % (value, use)
    proc = inline_raw(tmp_path, {"example.py": code})
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert changed(data)["example.py"] == "result = %s\n" % want


# --- Phrase: the position arguments are validated like every other cursor
#     command (T106).
def test_out_of_range_line_exits_1(tmp_path):
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")
    proc = run_raw("rename", str(tmp_path / "example.py"), 99, 0,
                   "--new-name", "y", cwd=str(tmp_path))
    assert proc.returncode == 1


def test_out_of_range_column_exits_1(tmp_path):
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")
    proc = run_raw("rename", str(tmp_path / "example.py"), 1, 99,
                   "--new-name", "y", cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: the JSON envelope is one compact newline-terminated object.
def test_json_output_framing(tmp_path):
    files = {"example.py": "val" + C + "ue = 1\nprint(value)\n"}
    proc = rename_raw(tmp_path, files, "total")
    assert proc.stdout.endswith("}\n")
    assert proc.stdout.count("\n") == 1


# --- Phrase: unknown subcommands and missing required options are usage
#     errors.
def test_rename_requires_new_name(tmp_path):
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")
    proc = run_raw("rename", str(tmp_path / "example.py"), 1, 0,
                   cwd=str(tmp_path))
    assert proc.returncode == 1


def test_extract_requires_until(tmp_path):
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")
    proc = run_raw("extract-variable", str(tmp_path / "example.py"), 1, 4,
                   "--name", "y", cwd=str(tmp_path))
    assert proc.returncode == 1


def test_bad_until_format(tmp_path):
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")
    proc = run_raw("extract-variable", str(tmp_path / "example.py"), 1, 4,
                   "--until", "nonsense", "--name", "y", cwd=str(tmp_path))
    assert proc.returncode == 1
