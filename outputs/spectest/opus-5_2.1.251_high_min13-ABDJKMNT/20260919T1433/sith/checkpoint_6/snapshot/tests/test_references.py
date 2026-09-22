"""Spec: New Subcommands / `references`."""


def places(result):
    """Each reference as a ``(module_path, line, column, is_definition)`` tuple."""
    return [
        (item["module_path"], item["line"], item["column"], item["is_definition"])
        for item in result.references
    ]


# Spec: "Find all locations where the name at the cursor is referenced (used or
# defined)."
def test_uses_and_definition_are_reported(references):
    result = references("def helper():\n    pass\n\nhelper()\nhel$per()\n")
    assert result.code == 0
    assert places(result) == [
        ("module_under_test.py", 1, 4, True),
        ("module_under_test.py", 4, 0, False),
        ("module_under_test.py", 5, 0, False),
    ]


# Spec: "`module_path` | string | File path relative to project root."
def test_module_path_is_relative_to_the_project_root(references):
    result = references(
        "import helper\nhelper.value$\n",
        extra={"pkg/helper.py": "value = 1\n"},
        name="pkg/main.py",
        project=".",
    )
    assert {item["module_path"] for item in result.references} == {"pkg/main.py"}


# Spec: "`is_definition` | bool | `true` if this is the defining occurrence
# (assignment, `def`, `class`, import)."
def test_assignment_is_a_definition(references):
    result = references("value = 1\nprint(val$ue)\n")
    assert places(result) == [
        ("module_under_test.py", 1, 0, True),
        ("module_under_test.py", 2, 6, False),
    ]


def test_class_and_import_definitions(references):
    result = references("import json\njson$\n")
    assert places(result) == [
        ("module_under_test.py", 1, 7, True),
        ("module_under_test.py", 2, 0, False),
    ]


# Spec: "`--scope file` (default): search only within the target file."
def test_file_scope_is_the_default(references):
    result = references(
        "def helper():\n    pass\n\nhel$per()\n",
        extra={"other.py": "from module_under_test import helper\nhelper()\n"},
    )
    assert {item["module_path"] for item in result.references} == {"module_under_test.py"}


def test_file_scope_can_be_asked_for(references):
    result = references(
        "def helper():\n    pass\n\nhel$per()\n",
        scope="file",
        extra={"other.py": "from module_under_test import helper\nhelper()\n"},
    )
    assert len(result.references) == 2


# Spec: "`--scope project`: search all `.py` files in the project."
def test_project_scope_reaches_other_files(references):
    result = references(
        "from other import helper\nhel$per()\n",
        scope="project",
        extra={"other.py": "def helper():\n    pass\n"},
    )
    assert places(result) == [
        ("module_under_test.py", 1, 18, True),
        ("module_under_test.py", 2, 0, False),
        ("other.py", 1, 4, True),
    ]


# Spec: "For project-scope search, return only occurrences that resolve to the
# same symbol identity as the cursor target (do not include same-spelling but
# unrelated symbols in other scopes)."
def test_unrelated_symbols_are_left_out_of_project_scope(references):
    result = references(
        "from other import value\nprint(val$ue)\n",
        scope="project",
        extra={"other.py": "value = 1\n\ndef shadow():\n    value = 2\n    return value\n"},
    )
    assert places(result) == [
        ("module_under_test.py", 1, 18, True),
        ("module_under_test.py", 2, 6, False),
        ("other.py", 1, 0, True),
    ]


# Spec: "Sort results by `(module_path, line, column)` ascending."
def test_results_are_sorted_by_position(references):
    result = references("def helper():\n    pass\n\nhelper(hel$per)\n")
    assert places(result) == [
        ("module_under_test.py", 1, 4, True),
        ("module_under_test.py", 4, 0, False),
        ("module_under_test.py", 4, 7, False),
    ]


# Spec: "`references` output always includes the definition occurrence when one
# is found"
def test_definition_is_included_when_the_cursor_is_on_a_use(references):
    result = references("class Widget:\n    pass\n\nWid$get()\n")
    assert (("module_under_test.py", 1, 6, True)) in places(result)


def test_definition_is_included_when_the_cursor_is_on_the_definition(references):
    result = references("class Wid$get:\n    pass\n\nWidget()\n")
    assert places(result) == [
        ("module_under_test.py", 1, 6, True),
        ("module_under_test.py", 4, 0, False),
    ]
