"""Spec section: the `references` subcommand."""
import json

from conftest import CURSOR, refs_at, refs_raw, refs_in, places, run_raw

C = CURSOR


# --- Phrase: "python sith.py references <file> <line> <col>" — exits 0 with a
#     `references` array.
def test_references_command_exists(tmp_path):
    proc = refs_raw(tmp_path, "x = 1\nprint(" + C + "x)\n")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) == {"references"}


# --- Phrase: "Find all locations where the name at the cursor is referenced
#     (used or defined)."
def test_references_finds_uses_and_definition(tmp_path):
    code = (
        "count = 1\n"
        "count = count + 1\n"
        "print(cou" + C + "nt)\n"
    )
    assert places(refs_at(tmp_path, code)) == [
        ("example.py", 1, 0),
        ("example.py", 2, 0),
        ("example.py", 2, 8),
        ("example.py", 3, 6),
    ]


# --- Phrase: fields — "module_path | string | File path relative to project
#     root."
def test_reference_fields(tmp_path):
    refs = refs_at(tmp_path, "x = 1\nprint(" + C + "x)\n")
    assert set(refs[0]) == {"module_path", "line", "column", "is_definition"}
    assert refs[0]["module_path"] == "example.py"


# --- Phrase: "line | int | 1-based line number." and
#     "column | int | 0-based column."
def test_reference_line_and_column(tmp_path):
    code = "value = 1\nprint(val" + C + "ue)\n"
    refs = refs_at(tmp_path, code)
    assert (refs[-1]["line"], refs[-1]["column"]) == (2, 6)


# --- Phrase: "is_definition | bool | `true` if this is the defining occurrence
#     (assignment, ...)"
def test_is_definition_assignment(tmp_path):
    refs = refs_at(tmp_path, "value = 1\nprint(val" + C + "ue)\n")
    assert [r["is_definition"] for r in refs] == [True, False]


# --- Phrase: "... `def` ..."
def test_is_definition_def(tmp_path):
    code = "def helper():\n    return 1\n\n\nhelp" + C + "er()\n"
    refs = refs_at(tmp_path, code)
    assert places(refs) == [("example.py", 1, 4), ("example.py", 5, 0)]
    assert [r["is_definition"] for r in refs] == [True, False]


# --- Phrase: "... `class` ..."
def test_is_definition_class(tmp_path):
    code = "class Thing:\n    pass\n\n\nThi" + C + "ng()\n"
    refs = refs_at(tmp_path, code)
    assert places(refs) == [("example.py", 1, 6), ("example.py", 5, 0)]
    assert [r["is_definition"] for r in refs] == [True, False]


# --- Phrase: "... import)."
def test_is_definition_import(tmp_path):
    code = "import os\nprint(o" + C + "s)\n"
    refs = refs_at(tmp_path, code)
    assert places(refs) == [("example.py", 1, 7), ("example.py", 2, 6)]
    assert [r["is_definition"] for r in refs] == [True, False]


# --- Phrase: a parameter's header occurrence is its defining occurrence.
def test_parameter_definition_and_uses(tmp_path):
    code = (
        "def f(item):\n"
        "    return it" + C + "em\n"
    )
    refs = refs_at(tmp_path, code)
    assert places(refs) == [("example.py", 1, 6), ("example.py", 2, 11)]
    assert [r["is_definition"] for r in refs] == [True, False]


# --- Phrase: "--scope file (default): search only within the target file."
def test_scope_file_is_the_default(tmp_path):
    files = {
        "other.py": "from main import shared\nprint(shared)\n",
        "main.py": "shared = 1\nprint(sha" + C + "red)\n",
    }
    assert places(refs_in(tmp_path, files)) == [
        ("main.py", 1, 0), ("main.py", 2, 6)]


# --- Phrase: "--scope file (default) ..." (explicit)
def test_scope_file_explicit(tmp_path):
    files = {
        "other.py": "from main import shared\nprint(shared)\n",
        "main.py": "shared = 1\nprint(sha" + C + "red)\n",
    }
    assert places(refs_in(tmp_path, files, scope="file")) == [
        ("main.py", 1, 0), ("main.py", 2, 6)]


# --- Phrase: "--scope project: search all `.py` files in the project."
def test_scope_project(tmp_path):
    files = {
        "other.py": "from main import shared\nprint(shared)\n",
        "main.py": "shared = 1\nprint(sha" + C + "red)\n",
    }
    assert places(refs_in(tmp_path, files, scope="project")) == [
        ("main.py", 1, 0),
        ("main.py", 2, 6),
        ("other.py", 1, 17),
        ("other.py", 2, 6),
    ]


# --- Phrase: "For project-scope search, return only occurrences that resolve
#     to the same symbol identity as the cursor target (do not include
#     same-spelling but unrelated symbols in other scopes)."
def test_project_scope_excludes_unrelated_same_spelling(tmp_path):
    files = {
        "other.py": "shared = 99\nprint(shared)\n",
        "main.py": "shared = 1\nprint(sha" + C + "red)\n",
    }
    got = places(refs_in(tmp_path, files, scope="project"))
    assert got == [("main.py", 1, 0), ("main.py", 2, 6)]


# --- Phrase: "... do not include same-spelling but unrelated symbols in other
#     scopes." (two locals in two functions of one file)
def test_file_scope_excludes_unrelated_local(tmp_path):
    code = (
        "def one():\n"
        "    total = 1\n"
        "    return tot" + C + "al\n"
        "\n"
        "\n"
        "def two():\n"
        "    total = 2\n"
        "    return total\n"
    )
    assert places(refs_at(tmp_path, code)) == [
        ("example.py", 2, 4), ("example.py", 3, 11)]


# --- Phrase: "Sort results by `(module_path, line, column)` ascending."
def test_sorted_by_module_line_column(tmp_path):
    files = {
        "zeta.py": "from main import v\nprint(v, v)\n",
        "alpha.py": "from main import v\nprint(v)\n",
        "main.py": "v = 1\nprint(" + C + "v)\n",
    }
    got = places(refs_in(tmp_path, files, scope="project"))
    assert got == sorted(got)
    assert got[0][0] == "alpha.py"


# --- Phrase: "references output always includes the definition occurrence when
#     one is found" (cursor already on the definition)
def test_cursor_on_the_definition(tmp_path):
    code = "def hel" + C + "per():\n    return 1\n\n\nhelper()\n"
    refs = refs_at(tmp_path, code)
    assert places(refs) == [("example.py", 1, 4), ("example.py", 5, 0)]
    assert refs[0]["is_definition"] is True


# --- Phrase: attribute occurrences of a method are references to it.
def test_method_references(tmp_path):
    code = (
        "class Box:\n"
        "    def put(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "b = Box()\n"
        "b.p" + C + "ut()\n"
    )
    assert places(refs_at(tmp_path, code)) == [
        ("example.py", 2, 8), ("example.py", 7, 2)]


# --- Phrase: "Find all locations where the name at the cursor is referenced"
#     (an import alias, its source and its uses share one identity)
def test_import_alias_identity(tmp_path):
    files = {
        "lib.py": "def work():\n    return 1\n",
        "main.py": "from lib import work as w\nw()\nwo" + C + "rk = 2\n",
    }
    got = places(refs_in(tmp_path, files, scope="project"))
    assert ("lib.py", 1, 4) not in got


# --- Phrase: `--project <dir>` is accepted.
def test_references_project_flag(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "lib.py").write_text("thing = 1\nprint(thing)\n")
    proc = run_raw("references", str(tmp_path / "pkg" / "lib.py"), 1, 0,
                   "--scope", "project", "--project", str(tmp_path),
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    refs = json.loads(proc.stdout)["references"]
    assert refs[0]["module_path"] == "pkg/lib.py"


# --- Phrase: "If the cursor is not on a name" — position errors behave like
#     the other cursor commands.
def test_references_not_on_a_name(tmp_path):
    proc = refs_raw(tmp_path, "x = 1\nx " + C + "\n")
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: an unknown `--scope` value is rejected.
def test_bad_scope_value(tmp_path):
    proc = refs_raw(tmp_path, "x = " + C + "1\n", scope="everything")
    assert proc.returncode == 1
