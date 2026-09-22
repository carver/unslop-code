"""Spec section: New Subcommands / Output Format."""
import json

from conftest import (CURSOR, goto_at, goto_raw, infer_at, infer_raw, one,
                      run_raw)

C = CURSOR

EXAMPLE = (
    "import os\n"
    "\n"
    "\n"
    "def helper(a, b=2):\n"
    '    """Add things."""\n'
    "    return a\n"
    "\n"
    "\n"
    "class Calculator:\n"
    "    pass\n"
)

FIELDS = {"name", "type", "full_name", "module_path", "line", "column",
          "description", "docstring"}


# --- Phrase: "python sith.py infer <file> <line> <col>"
#     Context: the subcommand exists and takes file/line/col.
def test_infer_subcommand_exists(tmp_path):
    defs = infer_at(tmp_path, EXAMPLE + "Calc" + C + "ulator\n")
    assert defs


# --- Phrase: "python sith.py goto <file> <line> <col>"
#     Context: the subcommand exists and takes file/line/col.
def test_goto_subcommand_exists(tmp_path):
    defs = goto_at(tmp_path, EXAMPLE + "Calc" + C + "ulator\n")
    assert defs


# --- Phrase: "Output is a JSON object with a `definitions` array." (infer)
def test_infer_output_is_object_with_definitions(tmp_path):
    proc = infer_raw(tmp_path, EXAMPLE + "helpe" + C + "r\n")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.endswith("\n")
    data = json.loads(proc.stdout)
    assert list(data) == ["definitions"]
    assert isinstance(data["definitions"], list)


# --- Phrase: "Output is a JSON object with a `definitions` array." (goto)
def test_goto_output_is_object_with_definitions(tmp_path):
    proc = goto_raw(tmp_path, EXAMPLE + "helpe" + C + "r\n")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert list(data) == ["definitions"]
    assert isinstance(data["definitions"], list)


# --- Phrase: "Each definition object has: name/type/full_name/module_path/
#     line/column/description/docstring"
#     Context: the exact field set of the spec's own example.
def test_definition_field_set(tmp_path):
    d = one(goto_at(tmp_path, EXAMPLE + "Calculato" + C + "r\n"))
    assert set(d) == FIELDS


# --- Phrase: the spec's worked example object for a class definition.
#     Context: `{"name":"Calculator","type":"class","full_name":"example.Calculator",
#     "module_path":"example.py","line":7,"column":0,"description":"class Calculator",
#     "docstring":""}`
def test_example_shape(tmp_path):
    code = (
        "import os\n"
        "\n"
        "\n"
        "def helper():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class Calculator:\n"
        "    pass\n"
        "\n"
        "\n"
        "c = Calculato" + C + "r()\n"
    )
    d = one(goto_at(tmp_path, code))
    assert d == {
        "name": "Calculator",
        "type": "class",
        "full_name": "example.Calculator",
        "module_path": "example.py",
        "line": 8,
        "column": 6,
        "description": "class Calculator",
        "docstring": "",
    }


# --- Phrase: "`name` | string | The identifier name."
def test_name_field_is_identifier(tmp_path):
    d = one(goto_at(tmp_path, EXAMPLE + "helpe" + C + "r\n"))
    assert d["name"] == "helper"


# --- Phrase: "`type` | One of: module, class, function, instance, statement, param."
#     Context: every definition kind we can produce uses one of those words.
def test_type_vocabulary(tmp_path):
    allowed = {"module", "class", "function", "instance", "statement", "param"}
    code = (
        "import os\n"
        "x = 1\n"
        "\n"
        "\n"
        "def f(p):\n"
        "    return p\n"
        "\n"
        "\n"
        "class K:\n"
        "    pass\n"
        "\n"
        "\n"
        "k = K()\n"
    )
    for target in ("os", "x", "f", "K", "k"):
        for runner in (goto_at, infer_at):
            defs = runner(tmp_path, code + target[:-1] + C + target[-1] + "\n")
            for d in defs:
                assert d["type"] in allowed, d


# --- Phrase: "For top-level names: `module.name`."
def test_full_name_top_level(tmp_path):
    d = one(goto_at(tmp_path, EXAMPLE + "helpe" + C + "r\n"))
    assert d["full_name"] == "example.helper"


# --- Phrase: "For nested: `module.Class.method`."
def test_full_name_nested_method(tmp_path):
    code = (
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a\n"
        "\n"
        "\n"
        "c = Calculator()\n"
        "c.ad" + C + "d\n"
    )
    d = one(goto_at(tmp_path, code))
    assert d["full_name"] == "example.Calculator.add"


# --- Phrase: "Module name is the filename without `.py`."
def test_full_name_uses_filename(tmp_path):
    code = "def thing():\n    return 1\n\n\nthin" + C + "g\n"
    d = one(goto_at(tmp_path, code, name="widget.py"))
    assert d["full_name"] == "widget.thing"
    assert d["module_path"] == "widget.py"


# --- Phrase: "module_path | File path where the name is defined, relative to the
#     project root.  When --project is not available, the project root is the
#     directory containing <file>."
#     Context: definition living in a sibling file.
def test_module_path_is_relative_to_containing_directory(tmp_path):
    code = "from helper import greet\n\n\nx = gree" + C + "t()\n"
    defs = infer_at(tmp_path, code,
                    extra={"helper.py": "def greet():\n    return 1\n"})
    d = one(defs)
    assert d["module_path"] == "helper.py"
    assert d["full_name"] == "helper.greet"


# --- Phrase: "`line` | int | 1-based line number of the definition."
def test_line_is_one_based(tmp_path):
    code = "x = 1\ny = 2\n\n\ndef target():\n    return 1\n\n\ntarge" + C + "t\n"
    d = one(goto_at(tmp_path, code))
    assert d["line"] == 5


# --- Phrase: "For `def foo():` this is the column of `f` in `foo`, not the column
#     of the `def` keyword."
def test_column_of_function_name(tmp_path):
    code = (
        "class K:\n"
        "    def method(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "K.metho" + C + "d\n"
    )
    d = one(goto_at(tmp_path, code))
    assert d["line"] == 2
    assert d["column"] == 8          # column of `m` in `method`


# --- Phrase: "For `class Bar:` this is the column of `B` in `Bar`."
def test_column_of_class_name(tmp_path):
    code = "class Bar:\n    pass\n\n\nBa" + C + "r\n"
    d = one(goto_at(tmp_path, code))
    assert d["column"] == 6


# --- Phrase: "column | 0-based column of the name identifier in the definition."
#     Context: a plain assignment target.
def test_column_of_assignment_target(tmp_path):
    code = "value = 3\n\n\nprint(valu" + C + "e)\n"
    d = one(goto_at(tmp_path, code))
    assert (d["line"], d["column"]) == (1, 0)


# --- Phrase: "description | For functions: `def name(params)`."
def test_description_function(tmp_path):
    code = "def add(a, b=2):\n    return a\n\n\nad" + C + "d\n"
    d = one(goto_at(tmp_path, code))
    assert d["description"] == "def add(a, b=2)"


# --- Phrase: "For classes: `class Name`."
def test_description_class(tmp_path):
    code = "class Widget:\n    pass\n\n\nWidge" + C + "t\n"
    assert one(goto_at(tmp_path, code))["description"] == "class Widget"


# --- Phrase: "For instances: `instance of <ClassName>`."
def test_description_instance(tmp_path):
    code = "class Widget:\n    pass\n\n\nw = Widget()\n" + "w" + C + "\n"
    d = one(infer_at(tmp_path, code))
    assert d["description"] == "instance of Widget"
    assert d["type"] == "instance"


# --- Phrase: "For assignments: the right-hand expression or statement." (T31)
def test_description_assignment(tmp_path):
    code = "total = 1 + 2\n\n\nprint(tota" + C + "l)\n"
    d = one(goto_at(tmp_path, code))
    assert d["description"] == "1 + 2"
    assert d["type"] == "statement"


# --- Phrase: "For imports: the import statement text." (T32)
def test_description_import(tmp_path):
    code = "from helper import greet\n\n\ngree" + C + "t\n"
    d = one(goto_at(tmp_path, code,
                    extra={"helper.py": "def greet():\n    return 1\n"}))
    assert d["description"] == "from helper import greet"


# --- Phrase: "For imports: the import statement text."
#     Context: a plain `import x` binding.
def test_description_plain_import(tmp_path):
    code = "import os\n\n\no" + C + "s\n"
    d = one(goto_at(tmp_path, code))
    assert d["description"] == "import os"
    assert d["line"] == 1
    assert d["column"] == 7


# --- Phrase: "docstring | The docstring of the definition, or empty string if none."
def test_docstring_present(tmp_path):
    code = (
        "def greet():\n"
        '    """Say hello."""\n'
        "    return 1\n"
        "\n"
        "\n"
        "gree" + C + "t\n"
    )
    assert one(goto_at(tmp_path, code))["docstring"] == "Say hello."


# --- Phrase: "...or empty string if none."
def test_docstring_absent_is_empty_string(tmp_path):
    code = "class Bare:\n    pass\n\n\nBar" + C + "e\n"
    assert one(goto_at(tmp_path, code))["docstring"] == ""


# --- Phrase: "The docstring of the definition" for classes.
def test_class_docstring(tmp_path):
    code = (
        "class Calculator:\n"
        '    """A calculator."""\n'
        "    pass\n"
        "\n"
        "\n"
        "Calculato" + C + "r\n"
    )
    assert one(goto_at(tmp_path, code))["docstring"] == "A calculator."


# --- Phrase: "For builtin types (including None, int, str, etc.), definitions use
#     type "instance" and full_name "builtins.<name>" with module_path set to empty
#     string and line/column set to 0."
def test_builtin_instance_shape(tmp_path):
    d = one(infer_at(tmp_path, "x = 5\n" + "x" + C + "\n"))
    assert d["type"] == "instance"
    assert d["full_name"] == "builtins.int"
    assert d["module_path"] == ""
    assert d["line"] == 0
    assert d["column"] == 0
    assert d["name"] == "int"


# --- Phrase: "(including None, int, str, etc.)" (T33: spelling of the None type)
def test_builtin_none(tmp_path):
    d = one(infer_at(tmp_path, "x = None\n" + "x" + C + "\n"))
    assert d["full_name"] == "builtins.None"
    assert d["name"] == "None"
    assert d["type"] == "instance"
    assert (d["line"], d["column"], d["module_path"]) == (0, 0, "")


# --- Phrase: "For builtin types ... str"
def test_builtin_str(tmp_path):
    d = one(infer_at(tmp_path, "x = 'hi'\n" + "x" + C + "\n"))
    assert d["full_name"] == "builtins.str"


# --- Phrase: "Multiple definitions are returned when a name could resolve to more
#     than one thing (e.g., conditional assignments)."
def test_multiple_definitions_conditional_assignment(tmp_path):
    code = (
        "flag = True\n"
        "if flag:\n"
        "    value = 1\n"
        "else:\n"
        "    value = 'text'\n"
        "print(valu" + C + "e)\n"
    )
    defs = infer_at(tmp_path, code)
    assert [d["full_name"] for d in defs] == ["builtins.int", "builtins.str"]


# --- Phrase: "Sort by (module_path, line, column) ascending."
def test_sort_order(tmp_path):
    code = (
        "class Beta:\n"
        "    pass\n"
        "\n"
        "\n"
        "class Alpha:\n"
        "    pass\n"
        "\n"
        "\n"
        "flag = True\n"
        "if flag:\n"
        "    thing = Alpha()\n"
        "else:\n"
        "    thing = Beta()\n"
        "thin" + C + "g\n"
    )
    defs = infer_at(tmp_path, code)
    keys = [(d["module_path"], d["line"], d["column"]) for d in defs]
    assert keys == sorted(keys)
    assert [d["name"] for d in defs] == ["Beta", "Alpha"]


# --- Phrase: "Sort by (module_path, line, column) ascending."
#     Context: definitions coming from two different files.
def test_sort_order_across_files(tmp_path):
    code = (
        "from a_mod import one\n"
        "from b_mod import two\n"
        "flag = True\n"
        "if flag:\n"
        "    picked = one\n"
        "else:\n"
        "    picked = two\n"
        "picke" + C + "d\n"
    )
    defs = infer_at(tmp_path, code, extra={
        "a_mod.py": "def one():\n    return 1\n",
        "b_mod.py": "def two():\n    return 2\n",
    })
    keys = [(d["module_path"], d["line"], d["column"]) for d in defs]
    assert keys == sorted(keys)
    assert [d["module_path"] for d in defs] == ["a_mod.py", "b_mod.py"]


# --- Phrase: "Output is a JSON object" — compact framing, exit 0.
def test_output_is_compact_json(tmp_path):
    proc = infer_raw(tmp_path, "x = 1\n" + "x" + C + "\n")
    assert proc.returncode == 0
    assert ", " not in proc.stdout
    assert '": ' not in proc.stdout


# --- Phrase: subcommand argument handling.
#     Context: a missing argument is a usage error, not a crash.
def test_missing_arguments(tmp_path):
    src = tmp_path / "example.py"
    src.write_text("x = 1\n", encoding="utf-8")
    proc = run_raw("infer", str(src), 1)
    assert proc.returncode == 1
    assert proc.stderr.strip()
    assert proc.stdout == ""


# --- Phrase: subcommand argument handling.
#     Context: a non-existent file is an error.
def test_missing_file(tmp_path):
    proc = run_raw("goto", str(tmp_path / "nope.py"), 1, 0)
    assert proc.returncode == 1
    assert proc.stdout == ""
