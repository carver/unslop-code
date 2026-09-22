"""Spec: New Subcommands and Output Format (shared by `infer` and `goto`)."""

import json

import pytest

from conftest import run_query


# Spec: "python sith.py infer <file> <line> <col>" and
# "python sith.py goto <file> <line> <col>".
@pytest.mark.parametrize("command", ["infer", "goto"])
def test_subcommands_are_accepted(write, command):
    path = write("value = 1\n")
    assert run_query(command, path, 1, 0).code == 0


# Spec: "Output is a JSON object with a `definitions` array."
@pytest.mark.parametrize("command", ["infer", "goto"])
def test_output_is_single_object_with_definitions_array(write, command):
    payload = json.loads(run_query(command, write("value = 1\n"), 1, 0).stdout)
    assert list(payload) == ["definitions"]
    assert isinstance(payload["definitions"], list)


# Spec: the sample payload is compact JSON, matching the `complete` format.
@pytest.mark.parametrize("command", ["infer", "goto"])
def test_output_is_compact_and_newline_terminated(write, command):
    result = run_query(command, write("value = 1\n"), 1, 0)
    assert result.stdout.endswith("\n")
    assert result.stdout.rstrip("\n") == json.dumps(result.data, separators=(",", ":"))


# Spec: "If the cursor is not on a name, exit 1."
@pytest.mark.parametrize("command", ["infer", "goto"])
def test_cursor_not_on_a_name_exits_one(write, command):
    path = write("value = 1 + 2\n")
    assert run_query(command, path, 1, 10).code == 1


# Spec: "If the cursor is not on a name, exit 1." - a keyword is not a name.
@pytest.mark.parametrize("command", ["infer", "goto"])
def test_cursor_on_a_keyword_exits_one(write, command):
    path = write("class Calculator:\n    pass\n")
    assert run_query(command, path, 1, 2).code == 1


# Spec: "If the name cannot be resolved, return an empty array (exit 0)."
def test_unresolved_name_returns_empty_array(infer):
    result = infer("def user(given):\n    giv$en\n")
    assert result.code == 0
    assert result.definitions == []


# Spec: "If no definition is found, return an empty array (exit 0)."
def test_goto_without_a_definition_returns_empty_array(goto):
    result = goto("def user():\n    undefine$d_name\n")
    assert result.code == 0
    assert result.definitions == []


# Spec: the exact shape of a definition object.
def test_definition_has_the_documented_fields(goto):
    definition = goto("class Calculator:\n    pass\ncalculat$or = 1\n").only
    assert list(definition) == [
        "name", "type", "full_name", "module_path",
        "line", "column", "description", "docstring",
    ]


# Spec: the worked example - infer on an instantiation names the class.
def test_example_payload(tmp_path):
    path = tmp_path / "example.py"
    path.write_text("\n" * 6 + "class Calculator:\n    pass\n\n\ncalc = Calculator()\n")
    result = run_query("infer", path, 11, 1)
    assert result.definitions == [
        {
            "name": "Calculator",
            "type": "instance",
            "full_name": "example.Calculator",
            "module_path": "example.py",
            "line": 7,
            "column": 6,
            "description": "instance of Calculator",
            "docstring": "",
        }
    ]


# Spec: "`name` | string | The identifier name."
def test_name_is_the_identifier(goto):
    assert goto("def compute():\n    pass\ncomput$e()\n").only["name"] == "compute"


# Spec: type `module` for an imported module.
def test_type_module(goto):
    assert goto("import os\no$s.getcwd()\n").only["type"] == "module"


# Spec: type `class` for a class definition.
def test_type_class(goto):
    assert goto("class Widget:\n    pass\nWidge$t\n").only["type"] == "class"


# Spec: type `function` for a function definition.
def test_type_function(goto):
    assert goto("def build():\n    pass\nbuil$d\n").only["type"] == "function"


# Spec: type `instance` for a name holding an instance.
def test_type_instance(goto):
    source = "class Widget:\n    pass\nwidget = Widget()\nwidge$t\n"
    assert goto(source).only["type"] == "instance"


# Spec: type `param` for a parameter.
def test_type_param(goto):
    assert goto("def build(size):\n    siz$e\n").only["type"] == "param"


# Spec: type `statement` when the bound value is not inferable.
def test_type_statement(goto):
    source = "def outside():\n    pass\nfor item in outside():\n    ite$m\n"
    assert goto(source).only["type"] == "statement"


# Spec: "`full_name` ... For top-level names: `module.name`. Module name is the
# filename without `.py`."
def test_full_name_of_a_top_level_name(goto):
    definition = goto("class Widget:\n    pass\nWidge$t\n", name="example.py").only
    assert definition["full_name"] == "example.Widget"


# Spec: "For nested: `module.Class.method`."
def test_full_name_of_a_method(goto):
    source = (
        "class Widget:\n"
        "    def render(self):\n"
        "        pass\n"
        "Widget().rende$r()\n"
    )
    assert goto(source, name="example.py").only["full_name"] == "example.Widget.render"


# Spec: "`module_path` | string | File path where the name is defined, relative
# to the project root."
def test_module_path_is_relative_to_the_project_root(goto):
    definition = goto("class Widget:\n    pass\nWidge$t\n", name="example.py").only
    assert definition["module_path"] == "example.py"


# Spec: "the project root is the directory containing `<file>`" - a definition
# in a neighbouring module is named relative to that directory.
def test_module_path_of_another_project_file(infer):
    result = infer(
        "from helper import Thing\nThin$g\n",
        extra={"helper.py": "class Thing:\n    pass\n"},
    )
    assert result.only["module_path"] == "helper.py"
    assert result.only["full_name"] == "helper.Thing"


# Spec: "`line` | int | 1-based line number of the definition."
def test_line_is_one_based(goto):
    source = "\n\nclass Widget:\n    pass\nWidge$t\n"
    assert goto(source).only["line"] == 3


# Spec: "For `def foo():` this is the column of `f` in `foo`, not the column of
# the `def` keyword."
def test_column_of_a_function_name(goto):
    source = "class Widget:\n    def render(self):\n        pass\nWidget().rende$r()\n"
    assert goto(source).only["column"] == 8


# Spec: "For `class Bar:` this is the column of `B` in `Bar`."
def test_column_of_a_class_name(goto):
    assert goto("class Widget:\n    pass\nWidge$t\n").only["column"] == 6


# Spec: "`column` | int | 0-based column of the name identifier" - an assignment
# target sits at the column of its own name.
def test_column_of_an_assignment_target(goto):
    source = "def user():\n    value = 1\n    valu$e\n"
    assert goto(source).only["column"] == 4


# Spec: "`description` | ... For functions: `def name(params)`."
def test_description_of_a_function(goto):
    source = "def build(size, scale=2):\n    pass\nbuil$d\n"
    assert goto(source).only["description"] == "def build(size, scale=2)"


# Spec: "For classes: `class Name`."
def test_description_of_a_class(goto):
    assert goto("class Widget:\n    pass\nWidge$t\n").only["description"] == "class Widget"


# Spec: "For instances: `instance of <ClassName>`."
def test_description_of_an_instance(infer):
    source = "class Widget:\n    pass\nwidget = Widget()\nwidge$t\n"
    assert infer(source).only["description"] == "instance of Widget"


# Spec: "For imports: the import statement text."
def test_description_of_an_import(goto):
    assert goto("import os\no$s\n").only["description"] == "import os"


def test_description_of_a_from_import(goto):
    result = goto(
        "from helper import Thing\nThin$g\n",
        extra={"helper.py": "class Thing:\n    pass\n"},
    )
    assert result.only["description"] == "from helper import Thing"


# Spec: "`docstring` | string | The docstring of the definition."
def test_docstring_of_a_function(goto):
    source = 'def build():\n    """Build a thing."""\nbuil$d\n'
    assert goto(source).only["docstring"] == "Build a thing."


def test_docstring_of_a_class(infer):
    source = 'class Widget:\n    """A widget."""\nwidget = Widget()\nwidge$t\n'
    assert infer(source).only["docstring"] == "A widget."


# Spec: "or empty string if none."
def test_missing_docstring_is_empty(goto):
    assert goto("def build():\n    pass\nbuil$d\n").only["docstring"] == ""


# Spec: "For builtin types (including None, int, str, etc.), definitions use
# type `instance` and full_name `builtins.<name>` with module_path set to empty
# string and line/column set to 0."
def test_builtin_definition_fields(infer):
    definition = infer("count = 1\ncoun$t\n").only
    assert definition["name"] == "int"
    assert definition["type"] == "instance"
    assert definition["full_name"] == "builtins.int"
    assert definition["module_path"] == ""
    assert definition["line"] == 0
    assert definition["column"] == 0


# Spec: "Multiple definitions are returned when a name could resolve to more
# than one thing (e.g., conditional assignments)."
def test_conditional_assignments_return_multiple_definitions(infer):
    source = (
        "def pick(flag):\n"
        "    if flag:\n"
        "        value = 1\n"
        "    else:\n"
        "        value = 'text'\n"
        "    valu$e\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["int", "str"]


# Spec: "Sort by `(module_path, line, column)` ascending."
def test_definitions_are_sorted_by_position(goto):
    source = (
        "def pick(flag):\n"
        "    if flag:\n"
        "        value = Second()\n"
        "    else:\n"
        "        value = First()\n"
        "    valu$e\n"
    )
    positions = [(item["module_path"], item["line"], item["column"]) for item in goto(source).definitions]
    assert positions == sorted(positions)
    assert len(positions) == 2
