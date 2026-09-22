"""Every field of a definition object, as listed in the output format table."""

EXAMPLE = (
    "import os\n"
    "\n"
    "\n"
    "def helper(a, b):\n"
    '    """Helps."""\n'
    "    return a\n"
    "\n"
    "\n"
    "class Calculator:\n"
    "    def add(self, x):\n"
    "        return x\n"
)


# Spec: the documented example object for a class definition.
def test_class_definition_object(goto):
    definition = goto(EXAMPLE + "c = Calc|ulator\n", name="example.py").only
    assert definition == {
        "name": "Calculator",
        "type": "class",
        "full_name": "example.Calculator",
        "module_path": "example.py",
        "line": 9,
        "column": 6,
        "description": "class Calculator",
        "docstring": "",
    }


# Spec: "`full_name` ... For nested: `module.Class.method`."
def test_nested_full_name(goto):
    definition = goto(EXAMPLE + "Calculator.a|dd\n", name="example.py").only
    assert definition["full_name"] == "example.Calculator.add"


# Spec: "Module name is the filename without `.py`."
def test_module_name_comes_from_the_filename(goto):
    definition = goto("def helper():\n    pass\nhel|per\n", name="widgets.py").only
    assert definition["full_name"] == "widgets.helper"


# Spec: "`module_path` ... relative to the project root. When `--project` is not
#        available, the project root is the directory containing `<file>`."
def test_module_path_is_relative_to_the_file_directory(goto):
    definition = goto(EXAMPLE + "hel|per\n", name="example.py").only
    assert definition["module_path"] == "example.py"


def test_module_path_of_another_project_file(goto):
    result = goto(
        "from helpers import Widget\nWid|get\n",
        files={"helpers.py": "class Widget:\n    pass\n"},
    )
    assert [d["module_path"] for d in result.definitions] == ["sample.py"]


# Spec: "`line` | int | 1-based line number of the definition."
def test_line_is_one_based(goto):
    assert goto(EXAMPLE + "hel|per\n", name="example.py").only["line"] == 4


# Spec: "For `def foo():` this is the column of `f` in `foo`, not the column of the
#        `def` keyword."
def test_column_of_a_function_name(goto):
    definition = goto("def helper():\n    pass\nhel|per\n").only
    assert definition["column"] == 4


def test_column_of_a_method_name(goto):
    definition = goto(EXAMPLE + "Calculator.a|dd\n", name="example.py").only
    assert (definition["line"], definition["column"]) == (10, 8)


# Spec: "For `class Bar:` this is the column of `B` in `Bar`."
def test_column_of_a_class_name(goto):
    assert goto("class Bar:\n    pass\nB|ar\n").only["column"] == 6


# Spec: "`description` ... For functions: `def name(params)`."
def test_function_description_lists_parameters(goto):
    assert goto(EXAMPLE + "hel|per\n", name="example.py").only["description"] == (
        "def helper(a, b)"
    )


# Spec: "For classes: `class Name`."
def test_class_description(goto):
    assert goto("class Bar:\n    pass\nB|ar\n").only["description"] == "class Bar"


# Spec: "For instances: `instance of <ClassName>`."
def test_instance_description(infer):
    source = "class Bar:\n    pass\nvalue = Bar()\nval|ue\n"
    definition = infer(source).only
    assert definition["type"] == "instance"
    assert definition["description"] == "instance of Bar"


# Spec: "For assignments: the right-hand expression or statement."
def test_assignment_description_is_the_right_hand_side(goto):
    assert goto("total = 1 + 2\ntot|al\n").only["description"] == "1 + 2"


# Spec: "For imports: the import statement text."
def test_import_description_is_the_statement(goto):
    assert goto("import os\n|os\n").only["description"] == "import os"


def test_from_import_description_is_the_statement(goto):
    assert goto("from os import getcwd\ngetc|wd\n").only["description"] == (
        "from os import getcwd"
    )


# Spec: "`docstring` | string | The docstring of the definition, or empty string if none."
def test_docstring_of_a_function(goto):
    assert goto(EXAMPLE + "hel|per\n", name="example.py").only["docstring"] == "Helps."


def test_docstring_of_a_class(goto):
    source = 'class Bar:\n    """A bar."""\n\n    pass\nB|ar\n'
    assert goto(source).only["docstring"] == "A bar."


def test_missing_docstring_is_empty(goto):
    assert goto("def helper():\n    pass\nhel|per\n").only["docstring"] == ""


# Spec: "`type` | string | One of: `module`, `class`, `function`, `instance`,
#        `statement`, `param`."
def test_types_are_from_the_documented_set(goto):
    source = (
        "import os\n"
        "\n"
        "def fn(arg):\n"
        "    local = 1\n"
        "    return arg, local\n"
        "\n"
        "class Klass:\n"
        "    pass\n"
    )
    cases = {
        (9, 1): "module",
        (3, 5): "function",
        (7, 7): "class",
        (4, 5): "statement",
    }
    for (line, col), expected in cases.items():
        assert goto(source + "os\nfn\nKlass\n", line=line, col=col).only["type"] == expected


def test_param_type(goto):
    source = "def fn(arg):\n    return a|rg\n"
    definition = goto(source).only
    assert definition["type"] == "param"
    assert (definition["line"], definition["column"]) == (1, 7)


# Spec: "Sort by `(module_path, line, column)` ascending."
def test_multiple_definitions_are_sorted(goto):
    source = (
        "if flag:\n"
        "    value = 'text'\n"
        "else:\n"
        "    value = 2\n"
        "print(val|ue)\n"
    )
    positions = [(d["module_path"], d["line"], d["column"]) for d in goto(source).definitions]
    assert positions == sorted(positions)
    assert len(positions) == 2
