"""Spec: New Subcommands / `names`."""


def listed(result):
    return [(item["name"], item["line"], item["column"]) for item in result.entries]


MODULE = (
    "import os\n"
    "LIMIT = 5\n"
    "\n"
    "def run(step):\n"
    "    local = 1\n"
    "\n"
    "class Widget:\n"
    "    size = 2\n"
)


# Spec: "List names defined in a file." / "Default: only module-level names
# (top-level functions, classes, assignments, imports)."
def test_module_level_names(names):
    result = names(MODULE)
    assert result.code == 0
    assert listed(result) == [("os", 1, 7), ("LIMIT", 2, 0), ("run", 4, 4), ("Widget", 7, 6)]


# Spec: "`names` includes top-level imports as module-level names"
def test_imports_are_module_level_names(names):
    result = names("from json import dumps as writer\n")
    assert listed(result) == [("writer", 1, 26)]


# Spec: "`--all-scopes`: include names from all scopes (locals inside
# functions, class attributes, nested defs)."
def test_all_scopes_includes_locals_and_members(names):
    result = names(MODULE, all_scopes=True)
    assert listed(result) == [
        ("os", 1, 7),
        ("LIMIT", 2, 0),
        ("run", 4, 4),
        ("step", 4, 8),
        ("local", 5, 4),
        ("Widget", 7, 6),
        ("size", 8, 4),
    ]


def test_all_scopes_includes_nested_definitions(names):
    source = "def outer():\n    def inner():\n        pass\n"
    assert [name for name, _, _ in listed(names(source, all_scopes=True))] == ["outer", "inner"]


def test_nested_definitions_are_hidden_by_default(names):
    source = "def outer():\n    def inner():\n        pass\n"
    assert [name for name, _, _ in listed(names(source))] == ["outer"]


# Spec: "Each entry has the definition fields plus `is_definition` (always
# `true` for this command)."
def test_entry_fields(names):
    result = names('def run():\n    """Doc."""\n')
    assert result.entries[0] == {
        "name": "run",
        "type": "function",
        "full_name": "module_under_test.run",
        "module_path": "module_under_test.py",
        "line": 1,
        "column": 4,
        "description": "def run()",
        "docstring": "Doc.",
        "is_definition": True,
    }


# Spec: "Sort by `(line, column)` ascending."
def test_names_are_sorted_by_position(names):
    result = names("second = 1\nfirst = 2\n")
    assert listed(result) == [("second", 1, 0), ("first", 2, 0)]
