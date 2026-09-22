"""`references`: every place a name is used or defined."""


# "Find all locations where the name at the cursor is referenced (used or
#  defined)."
def test_finds_uses_and_the_definition(references):
    result = references(
        """
total = 1
print(tot|al)
print(total)
"""
    )
    assert result.places == [("sample.py", 2, 0), ("sample.py", 3, 6), ("sample.py", 4, 6)]


# "| `is_definition` | bool | `true` if this is the defining occurrence
#  (assignment, `def`, `class`, import). |"
def test_assignment_is_a_definition(references):
    result = references("tot|al = 1\nprint(total)\n")
    assert [r["is_definition"] for r in result.references] == [True, False]


def test_def_is_a_definition(references):
    result = references("def hel|per():\n    pass\n\nhelper()\n")
    assert [r["is_definition"] for r in result.references] == [True, False]


def test_class_is_a_definition(references):
    result = references("class Bo|x:\n    pass\n\nBox()\n")
    assert [r["is_definition"] for r in result.references] == [True, False]


def test_import_is_a_definition(references):
    result = references(
        "import json\n\njs|on.dumps({})\n", files={"json.py": "def dumps(x):\n    pass\n"}
    )
    assert [r["is_definition"] for r in result.references] == [True, False]


# "| `line` | int | 1-based line number. |  | `column` | int | 0-based column. |"
def test_line_is_one_based_and_column_zero_based(references):
    result = references("value = 1\nresult = va|lue + value\n")
    assert ("sample.py", 2, 9) in result.places
    assert ("sample.py", 2, 17) in result.places


# "| `module_path` | string | File path relative to project root. |"
def test_module_path_is_relative_to_the_project_root(references):
    result = references(
        "from pkg.tool import run\n\nr|un()\n",
        name="pkg/main.py",
        files={"pkg/__init__.py": "", "pkg/tool.py": "def run():\n    pass\n"},
        project=".",
        scope="project",
    )
    assert ("pkg/tool.py", 1, 4) in result.places
    assert ("pkg/main.py", 3, 0) in result.places


# "`--scope file` (default): search only within the target file."
def test_file_scope_is_the_default(references):
    result = references(
        "from other import shared\n\nshar|ed()\n",
        files={"other.py": "def shared():\n    pass\n"},
    )
    assert {path for path, _, _ in result.places} == {"sample.py"}


# "`--scope project`: search all `.py` files in the project."
def test_project_scope_reaches_other_files(references):
    result = references(
        "from other import shared\n\nshar|ed()\n",
        files={"other.py": "def shared():\n    pass\n", "third.py": "from other import shared\n"},
        scope="project",
        project=".",
    )
    assert {path for path, _, _ in result.places} == {"sample.py", "other.py", "third.py"}


# "For project-scope search, return only occurrences that resolve to the same
#  symbol identity as the cursor target (do not include same-spelling but
#  unrelated symbols in other scopes)."
def test_unrelated_same_name_is_excluded(references):
    result = references(
        "from other import shared\n\nshar|ed()\n",
        files={"other.py": "def shared():\n    pass\n",
               "noise.py": "def shared():\n    pass\n\nshared()\n"},
        scope="project",
        project=".",
    )
    assert "noise.py" not in {path for path, _, _ in result.places}


def test_local_variables_of_other_functions_are_excluded(references):
    result = references(
        """
def first():
    value = 1
    return val|ue

def second():
    value = 2
    return value
"""
    )
    assert result.places == [("sample.py", 3, 4), ("sample.py", 4, 11)]


# "Sort results by `(module_path, line, column)` ascending."
def test_results_are_sorted(references):
    result = references(
        "from other import shared\n\nshar|ed()\nshared()\n",
        files={"other.py": "def shared():\n    pass\n"},
        scope="project",
        project=".",
    )
    assert result.places == sorted(result.places)


# "`references` output always includes the definition occurrence when one is
#  found"
def test_definition_is_always_present(references):
    result = references(
        "from other import shared\n\nshar|ed()\n",
        files={"other.py": "def shared():\n    pass\n"},
        scope="project",
        project=".",
    )
    assert ("other.py", 1, 4) in result.places


# A parameter is defined by its own `def` line and used in the body.
def test_parameter_and_its_uses(references):
    result = references("def f(val|ue):\n    return value\n")
    assert result.places == [("sample.py", 1, 6), ("sample.py", 2, 11)]
    assert [r["is_definition"] for r in result.references] == [True, False]


# An attribute is referenced wherever it is written on an instance.
def test_attribute_references(references):
    result = references(
        """
class Box:
    def __init__(self):
        self.size = 1

    def grow(self):
        self.si|ze += 1
"""
    )
    assert ("sample.py", 4, 13) in result.places
    assert ("sample.py", 7, 13) in result.places
