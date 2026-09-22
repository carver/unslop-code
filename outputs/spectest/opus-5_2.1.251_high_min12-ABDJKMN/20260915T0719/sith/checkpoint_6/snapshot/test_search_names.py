"""Tests for the `search` and `names` subcommands, one section per spec phrase."""

import json

import pytest

from conftest import (file_names, make_project, names_raw, run_raw, search,
                      search_raw)

DEF_FIELDS = {"name", "type", "full_name", "module_path", "line", "column",
              "description"}


def labels(results):
    return [(r["module_path"], r["name"]) for r in results]


# =====================================================================
# `search` -- CLI surface
# =====================================================================

# Spec: "python sith.py search <query> [--project <dir>]"
def test_cli_accepts_search_subcommand(tmp_path):
    r = search_raw(tmp_path, {"main.py": "def calc():\n    pass\n"}, "calc")
    assert r.returncode == 0, r.stderr
    assert "results" in json.loads(r.stdout)


# Spec: "python sith.py search <query> [--project <dir>]"
# Context: the command takes no line/column arguments.
def test_search_rejects_extra_positionals(tmp_path):
    make_project(tmp_path, {"main.py": "def calc():\n    pass\n"})
    r = run_raw(["search", "calc", "1", "2", "--project", str(tmp_path)])
    assert r.returncode == 1


# Spec: "[--project <dir>]" -- without it the root is the working directory (T71).
def test_search_without_project_flag_uses_cwd(tmp_path):
    make_project(tmp_path, {"main.py": "def calc():\n    pass\n"})
    import subprocess
    import sys
    from conftest import SITH
    r = subprocess.run([sys.executable, SITH, "search", "calc"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert [d["name"] for d in json.loads(r.stdout)["results"]] == ["calc"]


# Spec: the output is compact JSON, as for the other subcommands.
def test_search_output_is_compact_and_newline_terminated(tmp_path):
    r = search_raw(tmp_path, {"main.py": "def calc():\n    pass\n"}, "calc")
    assert r.stdout.endswith("\n")
    assert ", " not in r.stdout and '": ' not in r.stdout


# =====================================================================
# `search` -- result shape
# =====================================================================

# Spec: "Each result has the same fields as a definition object (from `infer`/`goto`),
#        minus `docstring`."
def test_search_result_fields(tmp_path):
    out = search(tmp_path, {"main.py": 'def calc():\n    """Doc."""\n'}, "calc")
    assert set(out[0]) == DEF_FIELDS


# Spec: "Each result has the same fields as a definition object"
def test_search_result_values(tmp_path):
    out = search(tmp_path, {"main.py": "def calc(a, b):\n    pass\n"}, "calc")
    assert out[0]["name"] == "calc"
    assert out[0]["type"] == "function"
    assert out[0]["full_name"] == "main.calc"
    assert out[0]["module_path"] == "main.py"
    assert (out[0]["line"], out[0]["column"]) == (1, 4)
    assert out[0]["description"] == "def calc(a, b)"


# Spec: "Returns definitions (not usages)."
def test_search_returns_definitions_not_usages(tmp_path):
    files = {"main.py": "def calc():\n    pass\ncalc()\ncalc()\n"}
    assert len(search(tmp_path, files, "calc")) == 1


# =====================================================================
# `search` -- matching
# =====================================================================

# Spec: "Match is by substring, case-insensitive: query `calc` matches
#        `Calculator`, `recalculate`."
def test_substring_match_is_case_insensitive(tmp_path):
    files = {"main.py": ("class Calculator:\n"
                         "    pass\n"
                         "def recalculate():\n"
                         "    pass\n")}
    assert sorted(d["name"] for d in search(tmp_path, files, "calc")) == \
        ["Calculator", "recalculate"]


# Spec: "Match is by substring, case-insensitive"
# Context: an upper-case query matches a lower-case name.
def test_uppercase_query_matches(tmp_path):
    files = {"main.py": "def recalculate():\n    pass\n"}
    assert [d["name"] for d in search(tmp_path, files, "CALC")] == ["recalculate"]


# Spec: "Match is by substring" -- a non-matching query gives nothing.
def test_no_match_returns_empty(tmp_path):
    files = {"main.py": "def calc():\n    pass\n"}
    assert search(tmp_path, files, "zebra") == []


# Spec: "Search all `def`, `class`, and top-level assignment names across project files."
def test_search_finds_defs(tmp_path):
    files = {"main.py": "def thing():\n    pass\n"}
    assert [d["type"] for d in search(tmp_path, files, "thing")] == ["function"]


# Spec: "Search all `def`, `class`, and top-level assignment names across project files."
def test_search_finds_classes(tmp_path):
    files = {"main.py": "class Thing:\n    pass\n"}
    assert [d["type"] for d in search(tmp_path, files, "thing")] == ["class"]


# Spec: "Search all `def`, `class`, and top-level assignment names across project files."
def test_search_finds_top_level_assignments(tmp_path):
    files = {"main.py": "thing = 1\n"}
    assert [d["name"] for d in search(tmp_path, files, "thing")] == ["thing"]


# Spec: "Search all ... names across project files."
def test_search_spans_several_files(tmp_path):
    files = {"alpha.py": "def thing():\n    pass\n",
             "beta.py": "def thing():\n    pass\n"}
    assert labels(search(tmp_path, files, "thing")) == \
        [("alpha.py", "thing"), ("beta.py", "thing")]


# Spec: "Search all ... names across project files."
# Context: files inside packages are searched too.
def test_search_spans_subpackages(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/deep.py": "def thing():\n    pass\n"}
    assert labels(search(tmp_path, files, "thing")) == [("pkg/deep.py", "thing")]


# Spec: "Do not search inside function/method bodies (local variables are not searchable)."
def test_locals_are_not_searchable(tmp_path):
    files = {"main.py": "def outer():\n    thing = 1\n    return thing\n"}
    assert search(tmp_path, files, "thing") == []


# Spec: "Do not search inside function/method bodies (local variables are not searchable)."
# Context: a nested def is inside a function body.
def test_nested_defs_are_not_searchable(tmp_path):
    files = {"main.py": "def outer():\n    def thing():\n        pass\n"}
    assert search(tmp_path, files, "thing") == []


# Spec: "Search all `def`, `class`, and top-level assignment names" (T63)
# Context: class bodies are not function bodies, so methods are searchable.
def test_methods_are_searchable(tmp_path):
    files = {"main.py": "class Box:\n    def thing(self):\n        pass\n"}
    out = search(tmp_path, files, "thing")
    assert [(d["name"], d["full_name"]) for d in out] == [("thing", "main.Box.thing")]


# Spec: "Search all `def`, `class`, and top-level assignment names" (T63)
# Context: class attributes are searchable.
def test_class_attributes_are_searchable(tmp_path):
    files = {"main.py": "class Box:\n    thing = 1\n"}
    assert [d["name"] for d in search(tmp_path, files, "thing")] == ["thing"]


# Spec: "Search all `def`, `class`, and top-level assignment names" (T63)
# Context: imported names are none of the three.
def test_imports_are_not_searchable(tmp_path):
    files = {"lib.py": "def thing():\n    pass\n",
             "main.py": "from lib import thing\n"}
    assert labels(search(tmp_path, files, "thing")) == [("lib.py", "thing")]


# =====================================================================
# `search` -- ordering
# =====================================================================

# Spec: "Sort by: exact match first, then prefix match, then substring match."
def test_exact_prefix_substring_ordering(tmp_path):
    files = {"main.py": ("def recalc():\n"
                         "    pass\n"
                         "def calcify():\n"
                         "    pass\n"
                         "def calc():\n"
                         "    pass\n")}
    assert [d["name"] for d in search(tmp_path, files, "calc")] == \
        ["calc", "calcify", "recalc"]


# Spec: "exact match first" -- the comparison is case-insensitive too.
def test_exact_match_is_case_insensitive(tmp_path):
    files = {"main.py": "class CALC:\n    pass\ndef calcify():\n    pass\n"}
    assert [d["name"] for d in search(tmp_path, files, "calc")] == \
        ["CALC", "calcify"]


# Spec: "Within each group, sort by `(module_path, line)`."
def test_within_group_sorted_by_module_path_then_line(tmp_path):
    files = {"zeta.py": "def calcz():\n    pass\n",
             "alpha.py": "def calca():\n    pass\ndef calcb():\n    pass\n"}
    assert labels(search(tmp_path, files, "calc")) == [
        ("alpha.py", "calca"), ("alpha.py", "calcb"), ("zeta.py", "calcz")]


# Spec: "Sort by: exact match first, then prefix match, then substring match.
#        Within each group, sort by `(module_path, line)`."
def test_ranking_beats_path_ordering(tmp_path):
    files = {"zeta.py": "def calc():\n    pass\n",
             "alpha.py": "def recalc():\n    pass\n"}
    assert labels(search(tmp_path, files, "calc")) == [
        ("zeta.py", "calc"), ("alpha.py", "recalc")]


# =====================================================================
# `names` -- CLI surface
# =====================================================================

# Spec: "python sith.py names <file> [--all-scopes] [--project <dir>]"
def test_cli_accepts_names_subcommand(tmp_path):
    r = names_raw(tmp_path, {"main.py": "x = 1\n"})
    assert r.returncode == 0, r.stderr
    assert "names" in json.loads(r.stdout)


# Spec: "python sith.py names <file> [--all-scopes] [--project <dir>]"
# Context: the command takes no line/column arguments.
def test_names_rejects_extra_positionals(tmp_path):
    make_project(tmp_path, {"main.py": "x = 1\n"})
    r = run_raw(["names", str(tmp_path / "main.py"), "1"])
    assert r.returncode == 1


# Spec: "python sith.py names <file>" -- a missing file is an error.
def test_names_missing_file_is_an_error(tmp_path):
    r = run_raw(["names", str(tmp_path / "nope.py")])
    assert r.returncode == 1


# Spec: the output is compact JSON, as for the other subcommands.
def test_names_output_is_compact_and_newline_terminated(tmp_path):
    r = names_raw(tmp_path, {"main.py": "x = 1\n"})
    assert r.stdout.endswith("\n")
    assert ", " not in r.stdout and '": ' not in r.stdout


# =====================================================================
# `names` -- result shape
# =====================================================================

# Spec: "Each entry has the definition fields plus `is_definition`
#        (always `true` for this command)."
def test_names_entry_fields(tmp_path):
    out = file_names(tmp_path, {"main.py": 'def f():\n    """D."""\n'})
    assert set(out[0]) == DEF_FIELDS | {"docstring", "is_definition"}


# Spec: "`is_definition` (always `true` for this command)"
def test_names_is_definition_always_true(tmp_path):
    files = {"main.py": "import os\nx = 1\ndef f():\n    pass\nclass C:\n    pass\n"}
    out = file_names(tmp_path, files)
    assert all(d["is_definition"] is True for d in out)


# Spec: "Each entry has the definition fields"
def test_names_entry_values(tmp_path):
    out = file_names(tmp_path, {"main.py": 'def f(a):\n    """D."""\n'})
    assert out[0]["name"] == "f"
    assert out[0]["type"] == "function"
    assert out[0]["full_name"] == "main.f"
    assert out[0]["module_path"] == "main.py"
    assert (out[0]["line"], out[0]["column"]) == (1, 4)
    assert out[0]["description"] == "def f(a)"
    assert out[0]["docstring"] == "D."


# =====================================================================
# `names` -- scope control
# =====================================================================

# Spec: "Default: only module-level names (top-level functions, classes,
#        assignments, imports)."
def test_default_lists_module_level_names(tmp_path):
    files = {"main.py": ("import os\n"
                         "value = 1\n"
                         "def f():\n"
                         "    pass\n"
                         "class C:\n"
                         "    pass\n")}
    assert [d["name"] for d in file_names(tmp_path, files)] == \
        ["os", "value", "f", "C"]


# Spec: "`names` includes top-level imports as module-level names"
def test_from_imports_are_module_level_names(tmp_path):
    files = {"lib.py": "def foo():\n    pass\n",
             "main.py": "from lib import foo as bar\n"}
    out = file_names(tmp_path, files, "main.py")
    assert [(d["name"], d["line"], d["column"]) for d in out] == [("bar", 1, 23)]


# Spec: "Default: only module-level names"
def test_default_excludes_locals(tmp_path):
    files = {"main.py": "def f():\n    local = 1\n    return local\n"}
    assert [d["name"] for d in file_names(tmp_path, files)] == ["f"]


# Spec: "Default: only module-level names"
# Context: class bodies are not module level either.
def test_default_excludes_class_body_names(tmp_path):
    files = {"main.py": "class C:\n    attr = 1\n    def m(self):\n        pass\n"}
    assert [d["name"] for d in file_names(tmp_path, files)] == ["C"]


# Spec: "`--all-scopes`: include names from all scopes (locals inside functions,
#        class attributes, nested defs)."
def test_all_scopes_includes_locals(tmp_path):
    files = {"main.py": "def f():\n    local = 1\n"}
    out = file_names(tmp_path, files, extra=["--all-scopes"])
    assert [d["name"] for d in out] == ["f", "local"]


# Spec: "`--all-scopes`: include names from all scopes (... class attributes ...)"
def test_all_scopes_includes_class_attributes(tmp_path):
    files = {"main.py": "class C:\n    attr = 1\n    def m(self):\n        pass\n"}
    out = file_names(tmp_path, files, extra=["--all-scopes"])
    assert [d["name"] for d in out] == ["C", "attr", "m", "self"]


# Spec: "`--all-scopes`: include names from all scopes (... nested defs)."
def test_all_scopes_includes_nested_defs(tmp_path):
    files = {"main.py": "def outer():\n    def inner():\n        pass\n"}
    out = file_names(tmp_path, files, extra=["--all-scopes"])
    assert [d["name"] for d in out] == ["outer", "inner"]


# Spec: "`--all-scopes`: include names from all scopes"
# Context: parameters are names of the function scope.
def test_all_scopes_includes_parameters(tmp_path):
    files = {"main.py": "def f(a, b):\n    pass\n"}
    out = file_names(tmp_path, files, extra=["--all-scopes"])
    assert [d["name"] for d in out] == ["f", "a", "b"]


# =====================================================================
# `names` -- ordering
# =====================================================================

# Spec: "Sort by `(line, column)` ascending."
def test_names_sorted_by_line_then_column(tmp_path):
    files = {"main.py": "b = 1\na = 2\n"}
    out = file_names(tmp_path, files)
    assert [(d["line"], d["column"]) for d in out] == [(1, 0), (2, 0)]


# Spec: "Sort by `(line, column)` ascending."
def test_names_same_line_sorted_by_column(tmp_path):
    files = {"main.py": "x, y = 1, 2\n"}
    out = file_names(tmp_path, files)
    assert [(d["name"], d["column"]) for d in out] == [("x", 0), ("y", 3)]


# Spec: "List names defined in a file." Context: each binding is an entry (T65).
def test_repeated_assignments_are_separate_entries(tmp_path):
    files = {"main.py": "x = 1\nx = 2\n"}
    out = file_names(tmp_path, files)
    assert [(d["name"], d["line"]) for d in out] == [("x", 1), ("x", 2)]
