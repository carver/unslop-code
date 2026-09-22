"""`names`: the names one file defines."""


def listed(result):
    return [(d["name"], d["line"], d["column"]) for d in result.definitions]


# "List names defined in a file."  "Default: only module-level names
#  (top-level functions, classes, assignments, imports)."
def test_module_level_names(names):
    result = names(
        """
import os

LIMIT = 10

def run():
    pass

class Box:
    pass
"""
    )
    assert [d["name"] for d in result.definitions] == ["os", "LIMIT", "run", "Box"]


# "`names` includes top-level imports as module-level names"
def test_imports_are_listed(names):
    result = names("from json import dumps\n")
    assert [d["name"] for d in result.definitions] == ["dumps"]


# "Each entry has the definition fields plus `is_definition` (always `true` for
#  this command)."
def test_entries_carry_definition_fields(names):
    result = names('def run(a):\n    """Doc."""\n')
    assert result.definitions[0] == {
        "name": "run",
        "type": "function",
        "full_name": "sample.run",
        "module_path": "sample.py",
        "line": 1,
        "column": 4,
        "description": "def run(a)",
        "docstring": "Doc.",
        "is_definition": True,
    }


# "Default: only module-level names"
def test_locals_are_hidden_by_default(names):
    result = names("def run():\n    inner = 1\n    return inner\n")
    assert [d["name"] for d in result.definitions] == ["run"]


# "`--all-scopes`: include names from all scopes (locals inside functions,
#  class attributes, nested defs)."
def test_all_scopes_includes_locals(names):
    result = names("def run():\n    inner = 1\n    return inner\n", all_scopes=True)
    assert [d["name"] for d in result.definitions] == ["run", "inner"]


def test_all_scopes_includes_class_attributes(names):
    result = names("class Box:\n    size = 1\n", all_scopes=True)
    assert [d["name"] for d in result.definitions] == ["Box", "size"]


def test_all_scopes_includes_nested_defs(names):
    result = names("def outer():\n    def inner():\n        pass\n", all_scopes=True)
    assert [d["name"] for d in result.definitions] == ["outer", "inner"]


# "Sort by `(line, column)` ascending."
def test_sorted_by_position(names):
    result = names("b = 1\na = 2\n")
    assert listed(result) == [("b", 1, 0), ("a", 2, 0)]


def test_two_names_on_one_line_sort_by_column(names):
    result = names("import os, sys\n")
    assert listed(result) == [("os", 1, 7), ("sys", 1, 11)]
