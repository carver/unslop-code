"""Spec section: the `search` subcommand."""
import json

from conftest import search_in, run_raw, write_tree


def rnames(results):
    return [r["name"] for r in results]


# --- Phrase: "python sith.py search <query>" — exits 0 with a results array.
def test_search_command_exists(tmp_path):
    results = search_in(tmp_path, {"a.py": "def helper():\n    pass\n"},
                        "helper")
    assert rnames(results) == ["helper"]


# --- Phrase: "Each result has the same fields as a definition object (from
#     `infer`/`goto`), minus `docstring`."
def test_result_fields(tmp_path):
    results = search_in(tmp_path, {"a.py": "def helper(x):\n    pass\n"},
                        "helper")
    assert set(results[0]) == {"name", "type", "full_name", "module_path",
                               "line", "column", "description"}
    assert results[0]["type"] == "function"
    assert results[0]["full_name"] == "a.helper"
    assert results[0]["description"] == "def helper(x)"
    assert (results[0]["module_path"], results[0]["line"],
            results[0]["column"]) == ("a.py", 1, 4)


# --- Phrase: "Match is by substring, case-insensitive: query `calc` matches
#     `Calculator`, `recalculate`."
def test_substring_case_insensitive(tmp_path):
    files = {"a.py": "class Calculator:\n    pass\n\n\n"
                     "def recalculate():\n    pass\n"}
    assert sorted(rnames(search_in(tmp_path, files, "calc"))) == \
        ["Calculator", "recalculate"]


# --- Phrase: "Search all `def`, `class`, and top-level assignment names across
#     project files."
def test_finds_defs_classes_and_assignments(tmp_path):
    files = {
        "a.py": "TOTAL_X = 1\n\n\ndef total_y():\n    pass\n\n\n"
                "class TotalZ:\n    pass\n",
    }
    assert sorted(rnames(search_in(tmp_path, files, "total"))) == \
        ["TOTAL_X", "TotalZ", "total_y"]


# --- Phrase: "... across project files."
def test_across_project_files(tmp_path):
    files = {
        "one.py": "def sample_one():\n    pass\n",
        "two.py": "def sample_two():\n    pass\n",
    }
    assert rnames(search_in(tmp_path, files, "sample")) == \
        ["sample_one", "sample_two"]


# --- Phrase: "Do not search inside function/method bodies (local variables are
#     not searchable)."
def test_locals_not_searchable(tmp_path):
    files = {"a.py": "def outer():\n    marker_local = 1\n"
                     "    def marker_nested():\n        pass\n"
                     "    return marker_local\n"}
    assert rnames(search_in(tmp_path, files, "marker")) == []


# --- Phrase: "Returns definitions (not usages)."
def test_usages_not_returned(tmp_path):
    files = {"a.py": "def widget():\n    pass\n\n\nwidget()\nwidget()\n"}
    results = search_in(tmp_path, files, "widget")
    assert [(r["line"], r["column"]) for r in results] == [(1, 4)]


# --- Phrase: methods are `def`s and are searchable.
def test_methods_are_searchable(tmp_path):
    files = {"a.py": "class Holder:\n    def fetch(self):\n        pass\n"}
    results = search_in(tmp_path, files, "fetch")
    assert rnames(results) == ["fetch"]
    assert results[0]["full_name"] == "a.Holder.fetch"


# --- Phrase: "Sort by: exact match first, then prefix match, then substring
#     match."
def test_rank_exact_prefix_substring(tmp_path):
    files = {"a.py": "def xcalcx():\n    pass\n\n\n"
                     "def calcify():\n    pass\n\n\n"
                     "def calc():\n    pass\n"}
    assert rnames(search_in(tmp_path, files, "calc")) == \
        ["calc", "calcify", "xcalcx"]


# --- Phrase: "... exact match first ..." (case-insensitive exactness)
def test_exact_match_is_case_insensitive(tmp_path):
    files = {"a.py": "def calculate():\n    pass\n\n\n"
                     "class CALC:\n    pass\n"}
    assert rnames(search_in(tmp_path, files, "calc")) == \
        ["CALC", "calculate"]


# --- Phrase: "Within each group, sort by `(module_path, line)`."
def test_within_group_sorted_by_path_then_line(tmp_path):
    files = {
        "zeta.py": "def calcz():\n    pass\n",
        "alpha.py": "def calca2():\n    pass\n\n\ndef calca1():\n    pass\n",
    }
    results = search_in(tmp_path, files, "calc")
    assert [(r["module_path"], r["line"]) for r in results] == \
        [("alpha.py", 1), ("alpha.py", 5), ("zeta.py", 1)]


# --- Phrase: "Search for names matching `<query>`" — no match is an empty
#     array, not an error.
def test_no_match_is_empty(tmp_path):
    assert search_in(tmp_path, {"a.py": "x = 1\n"}, "nothinghere") == []


# --- Phrase: `search` accepts `--project <dir>`; `module_path` is relative to
#     the project root.
def test_search_project_flag(tmp_path):
    write_tree(tmp_path, {"pkg/__init__.py": "",
                          "pkg/lib.py": "def gadget():\n    pass\n"})
    proc = run_raw("search", "gadget", "--project", str(tmp_path),
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    results = json.loads(proc.stdout)["results"]
    assert results[0]["module_path"] == "pkg/lib.py"
    assert results[0]["full_name"] == "pkg.lib.gadget"
