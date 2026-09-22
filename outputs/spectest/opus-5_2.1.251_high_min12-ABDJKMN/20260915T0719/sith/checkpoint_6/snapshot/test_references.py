"""Tests for the `references` subcommand, one section per spec phrase."""

import json

import pytest

from conftest import (make_project, positions, prefs, prun, refs, refs_raw,
                      run_raw, split_cursor, write)


# =====================================================================
# CLI surface
# =====================================================================

# Spec: "python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]"
def test_cli_accepts_references_subcommand(tmp_path):
    r = refs_raw(tmp_path, "x = 1\nprint(<|>x)\n")
    assert r.returncode == 0, r.stderr
    assert "references" in json.loads(r.stdout)


# Spec: the payload is a JSON array under the "references" key (T53).
def test_references_payload_is_an_array(tmp_path):
    r = refs_raw(tmp_path, "x = 1\nprint(<|>x)\n")
    assert isinstance(json.loads(r.stdout)["references"], list)


# Spec: the output is compact JSON, as for the other subcommands.
def test_references_output_is_compact_and_newline_terminated(tmp_path):
    r = refs_raw(tmp_path, "x = 1\nprint(<|>x)\n")
    assert r.stdout.endswith("\n")
    assert ", " not in r.stdout and '": ' not in r.stdout


# Spec: "[--scope file|project]" -- an invalid scope is rejected.
def test_invalid_scope_is_an_error(tmp_path):
    r = refs_raw(tmp_path, "x = 1\n<|>x\n", extra=["--scope", "galaxy"])
    assert r.returncode == 1
    assert r.stderr.strip()


# Spec: "Find all locations where the name at the cursor is referenced" (T60).
def test_cursor_not_on_a_name_exits_one(tmp_path):
    r = refs_raw(tmp_path, "x = 1 <|>\n")
    assert r.returncode == 1
    assert r.stderr.strip()


# =====================================================================
# Fields
# =====================================================================

# Spec: "| `module_path` | string | File path relative to project root. |"
def test_module_path_is_relative_to_the_project_root(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/main.py": "val = 1\nprint(<|>val)\n"}
    out = prefs(tmp_path, files, project=True)
    assert set(r["module_path"] for r in out) == {"pkg/main.py"}


# Spec: "| `line` | int | 1-based line number. |"
# Spec: "| `column` | int | 0-based column. |"
def test_line_is_one_based_and_column_zero_based(tmp_path):
    out = refs(tmp_path, "val = 1\nprint(<|>val)\n")
    assert (2, 6) in [(r["line"], r["column"]) for r in out]
    assert (1, 0) in [(r["line"], r["column"]) for r in out]


# Spec: "| `is_definition` | bool | `true` if this is the defining occurrence (assignment, ...) |"
def test_is_definition_for_an_assignment(tmp_path):
    out = refs(tmp_path, "val = 1\nprint(<|>val)\n")
    flags = {(r["line"], r["is_definition"]) for r in out}
    assert (1, True) in flags and (2, False) in flags


# Spec: "`true` if this is the defining occurrence (assignment, `def`, `class`, import)."
def test_is_definition_for_a_def(tmp_path):
    out = refs(tmp_path, "def helper():\n    pass\nhelper<|>()\n")
    assert [(r["line"], r["is_definition"]) for r in out] == [(1, True), (3, False)]


# Spec: "`true` if this is the defining occurrence (assignment, `def`, `class`, import)."
def test_is_definition_for_a_class(tmp_path):
    out = refs(tmp_path, "class Thing:\n    pass\nThing<|>()\n")
    assert [(r["line"], r["is_definition"]) for r in out] == [(1, True), (3, False)]


# Spec: "`true` if this is the defining occurrence (assignment, `def`, `class`, import)." (T74)
def test_is_definition_for_an_import(tmp_path):
    files = {"lib.py": "def foo():\n    pass\n",
             "main.py": "from lib import foo\nfo<|>o()\n"}
    out = prefs(tmp_path, files, extra=["--scope", "project"], project=True)
    by_pos = {(r["module_path"], r["line"]): r["is_definition"] for r in out}
    assert by_pos[("main.py", 1)] is True
    assert by_pos[("main.py", 2)] is False
    assert by_pos[("lib.py", 1)] is True


# Spec: "`is_definition` | bool" -- every entry carries exactly the four fields.
def test_reference_entry_fields(tmp_path):
    out = refs(tmp_path, "val = 1\n<|>val\n")
    for r in out:
        assert set(r) == {"module_path", "line", "column", "is_definition"}
        assert isinstance(r["is_definition"], bool)


# =====================================================================
# "Find all locations where the name at the cursor is referenced (used or defined)"
# =====================================================================

# Spec: "Find all locations where the name at the cursor is referenced (used or defined)."
def test_all_uses_are_found(tmp_path):
    src = ("val = 1\n"
           "print(val)\n"
           "print(v<|>al)\n")
    assert positions(refs(tmp_path, src)) == [
        ("main.py", 1, 0), ("main.py", 2, 6), ("main.py", 3, 6)]


# Spec: "references output always includes the definition occurrence when one is found"
def test_definition_is_included_when_cursor_is_on_a_use(tmp_path):
    out = refs(tmp_path, "def helper():\n    pass\nhel<|>per()\n")
    assert (1, True) in [(r["line"], r["is_definition"]) for r in out]


# Spec: "Find all locations where the name at the cursor is referenced (used or defined)."
# Context: the cursor may sit on the definition itself.
def test_cursor_on_the_definition(tmp_path):
    src = ("def hel<|>per():\n"
           "    pass\n"
           "helper()\n")
    assert positions(refs(tmp_path, src)) == [("main.py", 1, 4), ("main.py", 3, 0)]


# Spec: "Find all locations where the name at the cursor is referenced (used or defined)."
# Context: a reassignment is another occurrence of the same variable (T61).
def test_reassignment_is_an_occurrence(tmp_path):
    src = ("x = 1\n"
           "print(<|>x)\n"
           "x = 2\n"
           "print(x)\n")
    assert positions(refs(tmp_path, src)) == [
        ("main.py", 1, 0), ("main.py", 2, 6), ("main.py", 3, 0), ("main.py", 4, 6)]


# Spec: "Find all locations where the name at the cursor is referenced (used or defined)."
# Context: a parameter and its uses.
def test_parameter_references(tmp_path):
    src = ("def f(alpha):\n"
           "    return al<|>pha + alpha\n")
    assert positions(refs(tmp_path, src)) == [
        ("main.py", 1, 6), ("main.py", 2, 11), ("main.py", 2, 19)]


# Spec: "Sort results by `(module_path, line, column)` ascending."
def test_results_are_sorted(tmp_path):
    src = ("x = 1\n"
           "y = x + x\n"
           "z = <|>x\n")
    got = positions(refs(tmp_path, src))
    assert got == sorted(got)


# Spec: "Sort results by `(module_path, line, column)` ascending."
# Context: two occurrences on one line sort by column.
def test_same_line_sorts_by_column(tmp_path):
    out = refs(tmp_path, "x = 1\nprint(x, <|>x)\n")
    assert positions(out) == [("main.py", 1, 0), ("main.py", 2, 6), ("main.py", 2, 9)]


# Spec: "Find all locations where the name at the cursor is referenced".
# Context: duplicates are not reported twice.
def test_no_duplicate_positions(tmp_path):
    out = refs(tmp_path, "def f():\n    pass\nf()\n<|>f()\n")
    assert len(positions(out)) == len(set(positions(out)))


# =====================================================================
# Scope control
# =====================================================================

# Spec: "`--scope file` (default): search only within the target file."
def test_default_scope_is_file(tmp_path):
    files = {"lib.py": "def foo():\n    pass\n",
             "main.py": "from lib import foo\nf<|>oo()\n"}
    out = prefs(tmp_path, files, project=True)
    assert set(r["module_path"] for r in out) == {"main.py"}


# Spec: "`--scope file` (default): search only within the target file."
def test_explicit_file_scope(tmp_path):
    files = {"lib.py": "def foo():\n    pass\n",
             "main.py": "from lib import foo\nf<|>oo()\n"}
    out = prefs(tmp_path, files, extra=["--scope", "file"], project=True)
    assert set(r["module_path"] for r in out) == {"main.py"}


# Spec: "`--scope project`: search all `.py` files in the project."
def test_project_scope_crosses_files(tmp_path):
    files = {"lib.py": "def foo():\n    pass\n",
             "main.py": "from lib import foo\nf<|>oo()\n",
             "other.py": "from lib import foo\nfoo()\n"}
    out = prefs(tmp_path, files, extra=["--scope", "project"], project=True)
    assert positions(out) == [
        ("lib.py", 1, 4),
        ("main.py", 1, 16), ("main.py", 2, 0),
        ("other.py", 1, 16), ("other.py", 2, 0)]


# Spec: "For project-scope search, return only occurrences that resolve to the same
#        symbol identity as the cursor target (do not include same-spelling but
#        unrelated symbols in other scopes)."
def test_project_scope_excludes_unrelated_same_spelling(tmp_path):
    files = {"lib.py": "def foo():\n    pass\n",
             "main.py": "from lib import foo\nf<|>oo()\n",
             "other.py": "def foo():\n    pass\nfoo()\n"}
    out = prefs(tmp_path, files, extra=["--scope", "project"], project=True)
    assert "other.py" not in set(r["module_path"] for r in out)


# Spec: "(do not include same-spelling but unrelated symbols in other scopes)" (T59)
# Context: the same rule inside one file.
def test_unrelated_local_with_the_same_name_is_excluded(tmp_path):
    src = ("def a(x):\n"
           "    return <|>x\n"
           "def b(x):\n"
           "    return x\n")
    assert positions(refs(tmp_path, src)) == [("main.py", 1, 6), ("main.py", 2, 11)]


# Spec: "(do not include same-spelling but unrelated symbols in other scopes)"
# Context: a local shadowing a global is a different symbol.
def test_local_shadowing_a_global_is_a_different_symbol(tmp_path):
    src = ("count = 1\n"
           "def f():\n"
           "    count = 2\n"
           "    return count\n"
           "print(<|>count)\n")
    assert positions(refs(tmp_path, src)) == [("main.py", 1, 0), ("main.py", 5, 6)]


# Spec: "`--scope project`: search all `.py` files in the project."
# Context: files inside packages are searched too.
def test_project_scope_searches_subpackages(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/lib.py": "def foo():\n    pass\n",
             "pkg/use.py": "from pkg.lib import foo\nfoo()\n",
             "main.py": "from pkg.lib import foo\nf<|>oo()\n"}
    out = prefs(tmp_path, files, extra=["--scope", "project"], project=True)
    assert ("pkg/use.py", 2, 0) in positions(out)


# =====================================================================
# Attribute references (T62)
# =====================================================================

# Spec: "Find all locations where the name at the cursor is referenced (used or defined)."
# Context: a method and its call sites.
def test_method_references(tmp_path):
    src = ("class Thing:\n"
           "    def run(self):\n"
           "        pass\n"
           "t = Thing()\n"
           "t.r<|>un()\n")
    out = refs(tmp_path, src)
    assert positions(out) == [("main.py", 2, 8), ("main.py", 5, 2)]
    assert [r["is_definition"] for r in out] == [True, False]


# Spec: "(do not include same-spelling but unrelated symbols in other scopes)"
# Context: an attribute of an unrelated class is a different symbol.
def test_attribute_of_another_class_is_excluded(tmp_path):
    src = ("class A:\n"
           "    def run(self):\n"
           "        pass\n"
           "class B:\n"
           "    def run(self):\n"
           "        pass\n"
           "a = A()\n"
           "b = B()\n"
           "a.r<|>un()\n"
           "b.run()\n")
    assert positions(refs(tmp_path, src)) == [("main.py", 2, 8), ("main.py", 9, 2)]


# Spec: "Find all locations where the name at the cursor is referenced (used or defined)."
# Context: an instance attribute assigned in __init__.
def test_instance_attribute_references(tmp_path):
    src = ("class Thing:\n"
           "    def __init__(self):\n"
           "        self.size = 1\n"
           "    def grow(self):\n"
           "        self.si<|>ze += 1\n")
    out = refs(tmp_path, src)
    assert ("main.py", 3, 13) in positions(out)
    assert ("main.py", 5, 13) in positions(out)
