"""Spec section: the `names` subcommand."""
import json

from conftest import names_in_file, run_raw, write_tree


def nnames(entries):
    return [e["name"] for e in entries]


BASE = (
    "import os\n"
    "from sys import argv\n"
    "\n"
    "TOP = 1\n"
    "\n"
    "\n"
    "def fn(param):\n"
    "    local = param\n"
    "    return local\n"
    "\n"
    "\n"
    "class Cls:\n"
    "    attr = 2\n"
    "\n"
    "    def meth(self):\n"
    "        inner = 3\n"
    "        return inner\n"
)


# --- Phrase: "python sith.py names <file>" — exits 0 with a `names` array.
def test_names_command_exists(tmp_path):
    entries = names_in_file(tmp_path, {"m.py": "x = 1\n"}, "m.py")
    assert nnames(entries) == ["x"]


# --- Phrase: "Default: only module-level names (top-level functions, classes,
#     assignments, imports)."
def test_module_level_only(tmp_path):
    entries = names_in_file(tmp_path, {"m.py": BASE}, "m.py")
    assert nnames(entries) == ["os", "argv", "TOP", "fn", "Cls"]


# --- Phrase: "Each entry has the definition fields plus `is_definition`
#     (always `true` for this command)."
def test_entry_fields(tmp_path):
    entries = names_in_file(tmp_path, {"m.py": BASE}, "m.py")
    assert set(entries[0]) == {"name", "type", "full_name", "module_path",
                               "line", "column", "description", "docstring",
                               "is_definition"}
    assert all(e["is_definition"] is True for e in entries)


# --- Phrase: "Each entry has the definition fields ..." (values match `goto`)
def test_entry_values(tmp_path):
    entries = names_in_file(tmp_path, {"m.py": BASE}, "m.py")
    by_name = {e["name"]: e for e in entries}
    assert by_name["fn"]["type"] == "function"
    assert by_name["fn"]["full_name"] == "m.fn"
    assert by_name["fn"]["description"] == "def fn(param)"
    assert by_name["fn"]["module_path"] == "m.py"
    assert (by_name["fn"]["line"], by_name["fn"]["column"]) == (7, 4)
    assert by_name["Cls"]["type"] == "class"


# --- Phrase: "`names` includes top-level imports as module-level names"
def test_imports_included(tmp_path):
    entries = names_in_file(tmp_path, {"m.py": "import os\n"}, "m.py")
    assert nnames(entries) == ["os"]


# --- Phrase: "--all-scopes: include names from all scopes (locals inside
#     functions, class attributes, nested defs)."
def test_all_scopes(tmp_path):
    entries = names_in_file(tmp_path, {"m.py": BASE}, "m.py", all_scopes=True)
    got = nnames(entries)
    for expected in ("os", "argv", "TOP", "fn", "param", "local", "Cls",
                     "attr", "meth", "self", "inner"):
        assert expected in got, (expected, got)


# --- Phrase: "--all-scopes: ... nested defs"
def test_all_scopes_nested_defs(tmp_path):
    code = "def outer():\n    def inner():\n        pass\n    return inner\n"
    entries = names_in_file(tmp_path, {"m.py": code}, "m.py", all_scopes=True)
    assert nnames(entries) == ["outer", "inner"]


# --- Phrase: "--all-scopes: ... class attributes"
def test_all_scopes_class_attributes(tmp_path):
    code = "class C:\n    a = 1\n    b = 2\n"
    entries = names_in_file(tmp_path, {"m.py": code}, "m.py", all_scopes=True)
    assert nnames(entries) == ["C", "a", "b"]


# --- Phrase: "Sort by `(line, column)` ascending."
def test_sorted_by_line_then_column(tmp_path):
    code = "b = 1\na = 2\nc, d = 3, 4\n"
    entries = names_in_file(tmp_path, {"m.py": code}, "m.py")
    assert [(e["line"], e["column"]) for e in entries] == \
        [(1, 0), (2, 0), (3, 0), (3, 3)]
    assert nnames(entries) == ["b", "a", "c", "d"]


# --- Phrase: "List names defined in a file." (no names is an empty array)
def test_empty_file(tmp_path):
    assert names_in_file(tmp_path, {"m.py": "print(1)\n"}, "m.py") == []


# --- Phrase: `names` accepts `--project <dir>`.
def test_names_project_flag(tmp_path):
    write_tree(tmp_path, {"pkg/__init__.py": "",
                          "pkg/lib.py": "value = 1\n"})
    proc = run_raw("names", str(tmp_path / "pkg" / "lib.py"),
                   "--project", str(tmp_path), cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    entries = json.loads(proc.stdout)["names"]
    assert entries[0]["module_path"] == "pkg/lib.py"
    assert entries[0]["full_name"] == "pkg.lib.value"


# --- Phrase: "List names defined in a file." (a missing file is an error)
def test_names_missing_file(tmp_path):
    proc = run_raw("names", str(tmp_path / "nope.py"), cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""
