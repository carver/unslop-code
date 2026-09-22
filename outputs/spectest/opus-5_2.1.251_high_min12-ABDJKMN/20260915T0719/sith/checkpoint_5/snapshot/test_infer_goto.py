"""Tests for the `infer` / `goto` spec, one section per spec phrase."""

import json

import pytest

from conftest import (defs, goto, infer, one, raw, run_defs, split_cursor,
                      typenames, write)


# =====================================================================
# New subcommands -- CLI surface
# =====================================================================

# Spec: "python sith.py infer <file> <line> <col>"
def test_cli_accepts_infer_subcommand(tmp_path):
    r = raw(tmp_path, "x = 1\n<|>x\n", "infer")
    assert r.returncode == 0, r.stderr
    assert "definitions" in json.loads(r.stdout)


# Spec: "python sith.py goto <file> <line> <col>"
def test_cli_accepts_goto_subcommand(tmp_path):
    r = raw(tmp_path, "x = 1\n<|>x\n", "goto")
    assert r.returncode == 0, r.stderr
    assert "definitions" in json.loads(r.stdout)


# Spec: infer -- "Output is a JSON object with a `"definitions"` array."
def test_infer_output_is_object_with_definitions_array(tmp_path):
    r = raw(tmp_path, "x = 1\n<|>x\n", "infer")
    payload = json.loads(r.stdout)
    assert isinstance(payload, dict) and isinstance(payload["definitions"], list)


# Spec: goto -- "Output is a JSON object with a `"definitions"` array."
def test_goto_output_is_object_with_definitions_array(tmp_path):
    r = raw(tmp_path, "x = 1\n<|>x\n", "goto")
    payload = json.loads(r.stdout)
    assert isinstance(payload, dict) and isinstance(payload["definitions"], list)


# Spec: the sample output is compact JSON (as for `complete`).
def test_definition_output_is_compact_and_newline_terminated(tmp_path):
    r = raw(tmp_path, "x = 1\n<|>x\n", "infer")
    assert r.stdout.endswith("\n")
    assert ", " not in r.stdout and '": ' not in r.stdout


# Spec: infer -- "If the cursor is not on a name, exit 1."
def test_infer_not_on_a_name_exits_one(tmp_path):
    r = raw(tmp_path, "x = 1 <|>\n", "infer")
    assert r.returncode == 1
    assert r.stderr.strip()


# Spec: goto -- "If the cursor is not on a name, exit 1."
def test_goto_not_on_a_name_exits_one(tmp_path):
    r = raw(tmp_path, "x = 1 <|>\n", "goto")
    assert r.returncode == 1


# Spec: "If the cursor is not on a name, exit 1."
# Context: an operator/punctuation column is not a name (T36).
def test_cursor_on_operator_exits_one(tmp_path):
    r = raw(tmp_path, "x = 1\ny =<|> 2\n", "goto")
    assert r.returncode == 1


# Spec: "If the cursor is not on a name, exit 1."
# Context: a keyword is not a name (T36).
def test_cursor_on_keyword_exits_one(tmp_path):
    r = raw(tmp_path, "if<|> True:\n    pass\n", "infer")
    assert r.returncode == 1


# Spec: "If the cursor is not on a name, exit 1."
# Context: a numeric literal is not a name (T36).
def test_cursor_on_number_exits_one(tmp_path):
    r = raw(tmp_path, "x = 12<|>3\n", "infer")
    assert r.returncode == 1


# Spec: "If the name cannot be resolved, return an empty array (exit 0)." (infer)
def test_infer_unresolvable_name_is_empty_array(tmp_path):
    r = raw(tmp_path, "def f(q):\n    return q<|>\n", "infer")
    assert r.returncode == 0
    assert json.loads(r.stdout)["definitions"] == []


# Spec: "If no definition is found, return an empty array (exit 0)." (goto)
def test_goto_unknown_name_is_empty_array(tmp_path):
    r = raw(tmp_path, "nosuch<|>name\n", "goto")
    assert r.returncode == 0
    assert json.loads(r.stdout)["definitions"] == []


# Spec: the cursor rules of the tool (1-based line, 0-based col) still apply.
def test_out_of_range_position_exits_one(tmp_path):
    r = raw(tmp_path, "x = 1\n<|>x\n", "infer")
    assert r.returncode == 0
    p = write(tmp_path, "x = 1\n")
    assert run_defs("infer", p, 9, 0).returncode == 1
    assert run_defs("goto", p, 1, 99).returncode == 1


# =====================================================================
# Output format -- fields
# =====================================================================

# Spec: the definition object has exactly these fields: name, type, full_name,
#       module_path, line, column, description, docstring.
def test_definition_has_exactly_the_documented_fields(tmp_path):
    d = one(goto(tmp_path, "class Calculator:\n    pass\n\n\nCalcul<|>ator\n"))
    assert set(d) == {"name", "type", "full_name", "module_path", "line",
                      "column", "description", "docstring"}


# Spec: the worked example in the Output Format section.
def test_output_format_example(tmp_path):
    src = ("import os\n\n\ndef unused():\n    pass\n\n"
           "class Calculator:\n    pass\n\n\nCalcul<|>ator\n")
    d = one(goto(tmp_path, src, name="example.py"))
    assert d == {"name": "Calculator", "type": "class",
                 "full_name": "example.Calculator", "module_path": "example.py",
                 "line": 7, "column": 6, "description": "class Calculator",
                 "docstring": ""}


# Spec: "`name` | string | The identifier name."
def test_name_field_is_the_identifier(tmp_path):
    d = one(goto(tmp_path, "def helper():\n    pass\n\n\nhelp<|>er()\n"))
    assert d["name"] == "helper"


# Spec: "`type` ... One of: module, class, function, instance, statement, param."
@pytest.mark.parametrize("src,expected", [
    ("import os\no<|>s\n", "module"),
    ("class K:\n    pass\n\n\nK<|>\n", "class"),
    ("def f():\n    pass\n\n\nf<|>\n", "function"),
    ("x = 1\nx<|>\n", "statement"),
    ("def f(a):\n    return a<|>\n", "param"),
])
def test_type_field_values(tmp_path, src, expected):
    assert one(goto(tmp_path, src))["type"] == expected


# Spec: "`type` ... instance" -- an instantiation infers to an instance.
def test_type_instance(tmp_path):
    src = "class K:\n    pass\n\n\nk = K()\nk<|>\n"
    assert one(infer(tmp_path, src))["type"] == "instance"


# Spec: "`full_name` ... For top-level names: `module.name`."
def test_full_name_top_level(tmp_path):
    d = one(goto(tmp_path, "def helper():\n    pass\n\n\nhelp<|>er\n"))
    assert d["full_name"] == "main.helper"


# Spec: "`full_name` ... For nested: `module.Class.method`."
def test_full_name_nested_method(tmp_path):
    src = "class Calculator:\n    def add(self):\n        pass\n\n\nCalculator.a<|>dd\n"
    d = one(goto(tmp_path, src))
    assert d["full_name"] == "main.Calculator.add"


# Spec: "Module name is the filename without `.py`."
def test_full_name_uses_filename_as_module_name(tmp_path):
    d = one(goto(tmp_path, "class K:\n    pass\n\n\nK<|>\n", name="thing.py"))
    assert d["full_name"] == "thing.K"


# Spec: "`module_path` | string | File path where the name is defined,
#        relative to the project root."
def test_module_path_is_relative_to_project_root(tmp_path):
    d = one(goto(tmp_path, "class K:\n    pass\n\n\nK<|>\n", name="thing.py"))
    assert d["module_path"] == "thing.py"


# Spec: "When `--project` is not available, the project root is the directory
#        containing `<file>`." Context: a name imported from a sibling module.
def test_module_path_of_another_file_in_the_project(tmp_path):
    (tmp_path / "lib.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    d = one(infer(tmp_path, "from lib import Thing\nThi<|>ng\n"))
    assert d["module_path"] == "lib.py"
    assert d["full_name"] == "lib.Thing"


# Spec: "`line` | int | 1-based line number of the definition."
def test_line_is_one_based(tmp_path):
    d = one(goto(tmp_path, "x = 1\ny = 2\nz = 3\nz<|>\n"))
    assert d["line"] == 3


# Spec: "`column` ... For `def foo():` this is the column of `f` in `foo`,
#        not the column of the `def` keyword."
def test_column_of_def_is_the_name_not_the_keyword(tmp_path):
    d = one(goto(tmp_path, "def foo():\n    pass\n\n\nfo<|>o\n"))
    assert (d["line"], d["column"]) == (1, 4)


# Spec: "For `class Bar:` this is the column of `B` in `Bar`."
def test_column_of_class_is_the_name(tmp_path):
    d = one(goto(tmp_path, "class Bar:\n    pass\n\n\nB<|>ar\n"))
    assert (d["line"], d["column"]) == (1, 6)


# Spec: "`column` | int | 0-based column of the name identifier in the definition."
# Context: an indented method definition.
def test_column_of_indented_method(tmp_path):
    src = "class Bar:\n    def meth(self):\n        pass\n\n\nBar.me<|>th\n"
    d = one(goto(tmp_path, src))
    assert (d["line"], d["column"]) == (2, 8)


# Spec: "`column` ... 0-based column of the name identifier" -- assignment target.
def test_column_of_assignment_target(tmp_path):
    d = one(goto(tmp_path, "def f():\n    value = 1\n    val<|>ue\n"))
    assert (d["line"], d["column"]) == (2, 4)


# Spec: "`description` ... For functions: `def name(params)`."
def test_description_of_function(tmp_path):
    d = one(goto(tmp_path, "def add(a, b):\n    return a\n\n\nad<|>d\n"))
    assert d["description"] == "def add(a, b)"


# Spec: "For functions: `def name(params)`." Context: no parameters.
def test_description_of_function_without_params(tmp_path):
    d = one(goto(tmp_path, "def go():\n    pass\n\n\ng<|>o\n"))
    assert d["description"] == "def go()"


# Spec: "For classes: `class Name`."
def test_description_of_class(tmp_path):
    d = one(goto(tmp_path, "class Widget:\n    pass\n\n\nWid<|>get\n"))
    assert d["description"] == "class Widget"


# Spec: "For instances: `instance of <ClassName>`."
def test_description_of_instance(tmp_path):
    src = "class Widget:\n    pass\n\n\nw = Widget()\nw<|>\n"
    assert one(infer(tmp_path, src))["description"] == "instance of Widget"


# Spec: "For assignments: the right-hand expression or statement." (T28)
def test_description_of_assignment_is_the_right_hand_side(tmp_path):
    d = one(goto(tmp_path, "total = 1 + 2\ntot<|>al\n"))
    assert d["description"] == "1 + 2"


# Spec: "For imports: the import statement text." (T29)
def test_description_of_import(tmp_path):
    d = one(goto(tmp_path, "import os\no<|>s\n"))
    assert d["description"] == "import os"


# Spec: "For imports: the import statement text." Context: from-import.
def test_description_of_from_import(tmp_path):
    (tmp_path / "lib.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    d = one(goto(tmp_path, "from lib import Thing\nThi<|>ng\n"))
    assert d["description"] == "from lib import Thing"


# Spec: "`docstring` | string | The docstring of the definition."
def test_docstring_of_function(tmp_path):
    src = 'def f():\n    """Does a thing."""\n    pass\n\n\nf<|>\n'
    assert one(goto(tmp_path, src))["docstring"] == "Does a thing."


# Spec: "`docstring` ... The docstring of the definition." Context: class.
def test_docstring_of_class(tmp_path):
    src = 'class K:\n    """A K."""\n\n\nK<|>\n'
    assert one(goto(tmp_path, src))["docstring"] == "A K."


# Spec: "`docstring` ... or empty string if none."
def test_docstring_empty_when_absent(tmp_path):
    assert one(goto(tmp_path, "def f():\n    pass\n\n\nf<|>\n"))["docstring"] == ""


# Spec: "For builtin types (including None, int, str, etc.), definitions use
#        type "instance" and full_name "builtins.<name>" with module_path set to
#        empty string and line/column set to 0."
@pytest.mark.parametrize("literal,tname", [
    ("1", "int"), ("1.5", "float"), ("'s'", "str"), ("b'x'", "bytes"),
    ("True", "bool"), ("[1]", "list"), ("(1, 2)", "tuple"), ("{'a': 1}", "dict"),
])
def test_builtin_definition_shape(tmp_path, literal, tname):
    d = one(infer(tmp_path, "x = %s\nx<|>\n" % literal))
    assert d == {"name": tname, "type": "instance",
                 "full_name": "builtins.%s" % tname, "module_path": "",
                 "line": 0, "column": 0,
                 "description": "instance of %s" % tname, "docstring": ""}


# Spec: "For builtin types (including None, ...)" (T26)
def test_builtin_none_definition(tmp_path):
    d = one(infer(tmp_path, "x = None\nx<|>\n"))
    assert d["type"] == "instance"
    assert d["full_name"] == "builtins.None"
    assert (d["module_path"], d["line"], d["column"]) == ("", 0, 0)


# Spec: "Multiple definitions are returned when a name could resolve to more
#        than one thing (e.g., conditional assignments)."
def test_conditional_assignment_returns_multiple_definitions(tmp_path):
    src = ("def f(flag):\n"
           "    if flag:\n"
           "        x = 1\n"
           "    else:\n"
           "        x = 'text'\n"
           "    return x<|>\n")
    assert typenames(infer(tmp_path, src)) == ["int", "str"]


# Spec: "Multiple definitions are returned ..." -- goto sees both branches too.
def test_conditional_assignment_goto_returns_both_lines(tmp_path):
    src = ("def f(flag):\n"
           "    if flag:\n"
           "        x = 1\n"
           "    else:\n"
           "        x = 'text'\n"
           "    return x<|>\n")
    assert [d["line"] for d in goto(tmp_path, src)] == [3, 5]


# Spec: "Sort by `(module_path, line, column)` ascending."
def test_definitions_are_sorted_by_path_line_column(tmp_path):
    src = ("def f(flag):\n"
           "    if flag:\n"
           "        x = 1\n"
           "    elif flag is None:\n"
           "        x = 'text'\n"
           "    else:\n"
           "        x = 2.5\n"
           "    return x<|>\n")
    found = goto(tmp_path, src)
    keys = [(d["module_path"], d["line"], d["column"]) for d in found]
    assert keys == sorted(keys)


# Spec: "Sort by `(module_path, line, column)` ascending." Context: two files.
def test_definitions_from_two_files_are_sorted_by_path(tmp_path):
    (tmp_path / "alib.py").write_text("class A:\n    pass\n", encoding="utf-8")
    src = ("from alib import A\n\n\nclass B:\n    pass\n\n\n"
           "def pick(flag):\n"
           "    if flag:\n"
           "        v = A()\n"
           "    else:\n"
           "        v = B()\n"
           "    return v<|>\n")
    found = infer(tmp_path, src)
    keys = [(d["module_path"], d["line"], d["column"]) for d in found]
    assert keys == sorted(keys)
    assert [d["name"] for d in found] == ["A", "B"]


# =====================================================================
# goto vs infer
# =====================================================================

# Spec: "`goto` returns where the name at the cursor is assigned or defined
#        (`def`, `class`, assignment, or import binding)."
def test_goto_finds_assignment(tmp_path):
    d = one(goto(tmp_path, "value = 10\nprint(val<|>ue)\n"))
    assert (d["line"], d["column"], d["type"]) == (1, 0, "statement")


# Spec: "`goto` returns where the name ... is assigned or defined (`def` ...)"
def test_goto_finds_def(tmp_path):
    d = one(goto(tmp_path, "def run():\n    pass\n\n\nru<|>n()\n"))
    assert (d["line"], d["type"]) == (1, "function")


# Spec: "`goto` returns where the name ... is assigned or defined (... `class` ...)"
def test_goto_finds_class(tmp_path):
    d = one(goto(tmp_path, "class K:\n    pass\n\n\nK<|>()\n"))
    assert (d["line"], d["type"]) == (1, "class")


# Spec: "`goto` returns where the name ... is assigned or defined
#        (... or import binding)." Context: goto stops at the import statement.
def test_goto_finds_import_binding(tmp_path):
    (tmp_path / "lib.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    d = one(goto(tmp_path, "from lib import Thing\n\n\nt = Thi<|>ng()\n"))
    assert (d["module_path"], d["line"]) == ("main.py", 1)


# Spec: "`infer` returns what the name at the cursor evaluates to after static
#        propagation through assignments and calls."
def test_infer_follows_import_to_the_real_definition(tmp_path):
    (tmp_path / "lib.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    d = one(infer(tmp_path, "from lib import Thing\n\n\nt = Thi<|>ng()\n"))
    assert (d["module_path"], d["line"], d["type"]) == ("lib.py", 1, "class")


# Spec: "For bare function names, both commands may resolve to the same
#        function definition object."
def test_bare_function_name_infer_and_goto_agree(tmp_path):
    src = "def compute():\n    return 1\n\n\ncomp<|>ute\n"
    assert one(infer(tmp_path, src)) == one(goto(tmp_path, src))


# =====================================================================
# Type inference rules -- literals
# =====================================================================

# Spec: "For literals, `infer` returns a definition pointing to the builtin type
#        with `module_path` set to empty string and `line`/`column` set to 0."
def test_literal_infers_to_builtin_type(tmp_path):
    d = one(infer(tmp_path, "label = 'hello'\nlab<|>el\n"))
    assert d["name"] == "str" and d["module_path"] == "" and d["line"] == 0


# Spec: "For literals, `infer` returns a definition pointing to the builtin type"
# Context: goto still points at the assignment, not the builtin type.
def test_goto_on_literal_assignment_points_at_the_assignment(tmp_path):
    d = one(goto(tmp_path, "label = 'hello'\nlab<|>el\n"))
    assert (d["name"], d["line"], d["module_path"]) == ("label", 1, "main.py")


# =====================================================================
# Type inference rules -- assignments
# =====================================================================

# Spec: "Assignments -- Follow assignment chains."
def test_assignment_chain(tmp_path):
    src = "a = 5\nb = a\nc = b\nc<|>\n"
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# Spec: "Follow assignment chains." Context: chained through a class instance.
def test_assignment_chain_of_instances(tmp_path):
    src = "class K:\n    pass\n\n\na = K()\nb = a\nb<|>\n"
    d = one(infer(tmp_path, src))
    assert (d["name"], d["type"]) == ("K", "instance")


# Spec: "Follow assignment chains." Context: rebinding wins over the older value.
def test_reassignment_replaces_earlier_value(tmp_path):
    src = "x = 1\nx = 'text'\nx<|>\n"
    assert typenames(infer(tmp_path, src)) == ["str"]


# =====================================================================
# Type inference rules -- function return types
# =====================================================================

# Spec: "Infer a function's return type by analyzing its `return` statements."
def test_return_type_from_return_statement(tmp_path):
    src = "def make():\n    return 42\n\n\nv = make()\nv<|>\n"
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# Spec: "Infer a function's return type by analyzing its `return` statements."
# Context: returning an instance of a class.
def test_return_type_is_an_instance(tmp_path):
    src = ("class Widget:\n    pass\n\n\n"
           "def build():\n    return Widget()\n\n\nw = build()\nw<|>\n")
    d = one(infer(tmp_path, src))
    assert (d["name"], d["type"], d["line"]) == ("Widget", "instance", 1)


# Spec: "If a function has multiple return paths with different types,
#        return all possible types."
def test_multiple_return_paths_return_all_types(tmp_path):
    src = ("def maybe(flag):\n"
           "    if flag:\n"
           "        return 1\n"
           "    return 'text'\n\n\n"
           "v = maybe(True)\nv<|>\n")
    assert typenames(infer(tmp_path, src)) == ["int", "str"]


# Spec: "If a function has no `return` statement ... the return type is `None`."
def test_no_return_statement_infers_none(tmp_path):
    src = "def shout():\n    print('hi')\n\n\nv = shout()\nv<|>\n"
    d = one(infer(tmp_path, src))
    assert d["full_name"] == "builtins.None" and d["type"] == "instance"


# Spec: "If a function has ... only bare `return`, the return type is `None`."
def test_bare_return_infers_none(tmp_path):
    src = "def stop():\n    return\n\n\nv = stop()\nv<|>\n"
    assert one(infer(tmp_path, src))["full_name"] == "builtins.None"


# Spec: "If a function has multiple return paths with different types, return
#        all possible types." Context: a bare return next to a value return.
def test_bare_return_and_value_return_are_both_reported(tmp_path):
    src = ("def maybe(flag):\n"
           "    if flag:\n"
           "        return 1\n"
           "    return\n\n\n"
           "v = maybe(True)\nv<|>\n")
    assert typenames(infer(tmp_path, src)) == ["None", "int"]


# Spec: "Infer a function's return type by analyzing its `return` statements."
# Context: a method called on an instance.
def test_method_return_type(tmp_path):
    src = ("class Calculator:\n"
           "    def add(self, n):\n"
           "        return 0\n\n\n"
           "c = Calculator()\n"
           "r = c.add(1)\n"
           "r<|>\n")
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# =====================================================================
# Type inference rules -- class instantiation
# =====================================================================

# Spec: "Class Instantiation -- `infer` returns the class definition with
#        `type` set to `"instance"`."
def test_instantiation_returns_class_definition_as_instance(tmp_path):
    src = ("class Calculator:\n"
           '    """Adds."""\n\n\n'
           "c = Calculator()\n"
           "c<|>\n")
    d = one(infer(tmp_path, src))
    assert d["name"] == "Calculator"
    assert d["type"] == "instance"
    assert d["line"] == 1 and d["column"] == 6
    assert d["full_name"] == "main.Calculator"
    assert d["description"] == "instance of Calculator"
    assert d["docstring"] == "Adds."


# Spec: "`infer` returns the class definition with `type` set to `"instance"`."
# Context: the class name itself still infers to the class.
def test_class_name_infers_to_the_class(tmp_path):
    src = "class Calculator:\n    pass\n\n\nCalcul<|>ator\n"
    assert one(infer(tmp_path, src))["type"] == "class"


# =====================================================================
# Type inference rules -- attribute access
# =====================================================================

# Spec: "Attribute Access -- Infer attributes from instance state when resolvable."
def test_infer_instance_attribute(tmp_path):
    src = ("class Calculator:\n"
           "    def __init__(self):\n"
           "        self.value = 0\n\n\n"
           "c = Calculator()\n"
           "c.val<|>ue\n")
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# Spec: "Infer attributes from instance state when resolvable."
# Context: goto on the attribute lands on the `self.x = ...` assignment.
def test_goto_instance_attribute(tmp_path):
    src = ("class Calculator:\n"
           "    def __init__(self):\n"
           "        self.value = 0\n\n\n"
           "c = Calculator()\n"
           "c.val<|>ue\n")
    d = one(goto(tmp_path, src))
    assert (d["name"], d["line"], d["column"]) == ("value", 3, 13)
    assert d["full_name"] == "main.Calculator.value"


# Spec: "Infer attributes from instance state when resolvable."
# Context: a method attribute of an instance.
def test_goto_method_through_instance(tmp_path):
    src = ("class Calculator:\n"
           "    def add(self, n):\n"
           "        return n\n\n\n"
           "c = Calculator()\n"
           "c.a<|>dd\n")
    d = one(goto(tmp_path, src))
    assert (d["type"], d["line"], d["full_name"]) == \
        ("function", 2, "main.Calculator.add")


# Spec: "Infer attributes from instance state when resolvable."
# Context: `self.x` inside a method of the same class.
def test_infer_self_attribute_inside_method(tmp_path):
    src = ("class Calculator:\n"
           "    def __init__(self):\n"
           "        self.value = 0\n\n"
           "    def get(self):\n"
           "        return self.val<|>ue\n")
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# Spec: "Infer attributes from instance state when resolvable."
# Context: attributes of a module.
def test_goto_module_attribute(tmp_path):
    (tmp_path / "lib.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    d = one(goto(tmp_path, "import lib\nlib.g<|>o()\n"))
    assert (d["module_path"], d["line"], d["type"]) == ("lib.py", 1, "function")


# =====================================================================
# Type inference rules -- dataclass fields
# =====================================================================

# Spec: "Classes decorated with `@dataclasses.dataclass` expose their annotated
#        fields as instance attributes for ... inference."
def test_dataclass_field_inference(tmp_path):
    src = ("import dataclasses\n\n\n"
           "@dataclasses.dataclass\n"
           "class Point:\n"
           "    x: int\n"
           "    y: str\n\n\n"
           "p = Point(1, 'a')\n"
           "p.<|>x\n")
    assert one(infer(tmp_path, src, extra=()))["full_name"] == "builtins.int"


# Spec: "Dataclass instance attribute completion includes annotated fields."
def test_dataclass_field_completion(tmp_path, helpers):
    src = ("from dataclasses import dataclass\n\n\n"
           "@dataclass\n"
           "class Point:\n"
           "    x: int\n"
           "    y: str\n\n\n"
           "p = Point(1, 'a')\n"
           "p.<|>\n")
    names = helpers.names(helpers.complete(tmp_path, src))
    assert "x" in names and "y" in names


# Spec: "`@dataclass(frozen=True)` does not affect inference behavior."
def test_frozen_dataclass_behaves_the_same(tmp_path):
    src = ("from dataclasses import dataclass\n\n\n"
           "@dataclass(frozen=True)\n"
           "class Point:\n"
           "    x: int\n\n\n"
           "p = Point(1)\n"
           "p.x<|>\n")
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# Spec: "`@dataclass` is recognized regardless of import form
#        (`import dataclasses`, `from dataclasses import dataclass`, or aliased)."
@pytest.mark.parametrize("header,decorator", [
    ("import dataclasses", "@dataclasses.dataclass"),
    ("from dataclasses import dataclass", "@dataclass"),
    ("from dataclasses import dataclass as dc", "@dc"),
    ("import dataclasses as dcs", "@dcs.dataclass"),
])
def test_dataclass_import_forms(tmp_path, header, decorator):
    src = ("%s\n\n\n%s\nclass Point:\n    x: int\n\n\n"
           "p = Point(1)\n"
           "p.x<|>\n") % (header, decorator)
    assert one(infer(tmp_path, src))["full_name"] == "builtins.int"


# Spec: "Dataclass fields are instance attributes for completion and inference."
# Context: goto on a field lands on the annotation line.
def test_goto_dataclass_field(tmp_path):
    src = ("from dataclasses import dataclass\n\n\n"
           "@dataclass\n"
           "class Point:\n"
           "    x: int\n\n\n"
           "p = Point(1)\n"
           "p.<|>x\n")
    d = one(goto(tmp_path, src))
    assert (d["line"], d["column"], d["full_name"]) == (6, 4, "main.Point.x")


# =====================================================================
# Flow-sensitive type narrowing
# =====================================================================

# Spec: "isinstance(x, SomeClass) -- `x` is `SomeClass` inside the `if` body."
def test_isinstance_narrowing_for_infer(tmp_path):
    src = ("class Dog:\n"
           "    pass\n\n\n"
           "def act(pet):\n"
           "    if isinstance(pet, Dog):\n"
           "        return pe<|>t\n")
    d = one(infer(tmp_path, src))
    assert (d["name"], d["type"], d["line"]) == ("Dog", "instance", 1)


# Spec: "This narrowing applies to ... `complete` (shows attributes of the
#        narrowed type for attribute completion)."
def test_isinstance_narrowing_for_complete(tmp_path, helpers):
    src = ("class Dog:\n"
           "    def bark(self):\n"
           "        pass\n\n\n"
           "def act(pet):\n"
           "    if isinstance(pet, Dog):\n"
           "        pet.<|>\n")
    assert "bark" in helpers.names(helpers.complete(tmp_path, src))


# Spec: "When the cursor is inside an `isinstance` branch, narrow the type
#        accordingly." Context: outside the branch there is no narrowing (T30).
def test_no_narrowing_outside_the_branch(tmp_path):
    src = ("class Dog:\n"
           "    pass\n\n\n"
           "def act(pet):\n"
           "    if isinstance(pet, Dog):\n"
           "        pass\n"
           "    return pe<|>t\n")
    assert infer(tmp_path, src) == []


# Spec: "isinstance narrowing ... narrow the type accordingly"
# Context: narrowing a name that already has a union type.
def test_isinstance_narrows_a_union(tmp_path):
    src = ("class Dog:\n    pass\n\n\n"
           "class Cat:\n    pass\n\n\n"
           "def act(flag):\n"
           "    if flag:\n"
           "        pet = Dog()\n"
           "    else:\n"
           "        pet = Cat()\n"
           "    if isinstance(pet, Cat):\n"
           "        return pe<|>t\n")
    assert typenames(infer(tmp_path, src)) == ["Cat"]


# Spec: "### `is None`" (empty section -- T30)
# Context: inside `if x is None:` the name is None.
def test_is_none_narrowing(tmp_path):
    src = ("def act(flag):\n"
           "    value = 1\n"
           "    if flag:\n"
           "        value = None\n"
           "    if value is None:\n"
           "        return val<|>ue\n")
    assert typenames(infer(tmp_path, src)) == ["None"]


# Spec: "### `is None`" (T30) -- `is not None` removes None from the union.
def test_is_not_none_narrowing(tmp_path):
    src = ("def act(flag):\n"
           "    value = 1\n"
           "    if flag:\n"
           "        value = None\n"
           "    if value is not None:\n"
           "        return val<|>ue\n")
    assert typenames(infer(tmp_path, src)) == ["int"]


# Spec: "### `is None`" (T30) -- the else branch of `is None` excludes None.
def test_else_branch_of_is_none(tmp_path):
    src = ("def act(flag):\n"
           "    value = 1\n"
           "    if flag:\n"
           "        value = None\n"
           "    if value is None:\n"
           "        pass\n"
           "    else:\n"
           "        return val<|>ue\n")
    assert typenames(infer(tmp_path, src)) == ["int"]


# =====================================================================
# Completion enhancements
# =====================================================================

# Spec: "Attribute completion after `.` uses inferred types. If
#        `x = Calculator()`, then `x.` shows `Calculator` instance attributes."
def test_attribute_completion_uses_inferred_type(tmp_path, helpers):
    src = ("class Calculator:\n"
           "    def __init__(self):\n"
           "        self.value = 0\n\n"
           "    def add(self, n):\n"
           "        return n\n\n\n"
           "x = Calculator()\n"
           "x.<|>\n")
    names = helpers.names(helpers.complete(tmp_path, src))
    assert "value" in names and "add" in names


# Spec: "When a name has multiple possible types (union), completions include
#        attributes from **all** possible types."
def test_union_completion_includes_all_types(tmp_path, helpers):
    src = ("class Dog:\n"
           "    def bark(self):\n"
           "        pass\n\n\n"
           "class Cat:\n"
           "    def meow(self):\n"
           "        pass\n\n\n"
           "def pick(flag):\n"
           "    if flag:\n"
           "        pet = Dog()\n"
           "    else:\n"
           "        pet = Cat()\n"
           "    pet.<|>\n")
    names = helpers.names(helpers.complete(tmp_path, src))
    assert "bark" in names and "meow" in names


# Spec: "When a name has multiple possible types (union), completions include
#        attributes from all possible types." Context: a union of return types.
def test_union_from_return_values_in_completion(tmp_path, helpers):
    src = ("class Dog:\n"
           "    def bark(self):\n"
           "        pass\n\n\n"
           "class Cat:\n"
           "    def meow(self):\n"
           "        pass\n\n\n"
           "def pick(flag):\n"
           "    if flag:\n"
           "        return Dog()\n"
           "    return Cat()\n\n\n"
           "pet = pick(True)\n"
           "pet.<|>\n")
    names = helpers.names(helpers.complete(tmp_path, src))
    assert "bark" in names and "meow" in names


# =====================================================================
# Clarifications
# =====================================================================

# Spec: "`goto` answers where the identifier is defined/assigned at the cursor."
def test_goto_on_the_definition_itself(tmp_path):
    d = one(goto(tmp_path, "def fo<|>o():\n    pass\n"))
    assert (d["name"], d["line"], d["column"]) == ("foo", 1, 4)


# Spec: "`infer` answers what value/type that identifier evaluates to at the cursor."
def test_infer_on_a_parameter_with_no_information(tmp_path):
    assert infer(tmp_path, "def f(a<|>):\n    pass\n") == []


# Spec: "`goto` answers where the identifier is defined/assigned at the cursor."
# Context: a parameter is defined by its `def` line.
def test_goto_on_a_parameter(tmp_path):
    d = one(goto(tmp_path, "def f(alpha):\n    return alp<|>ha\n"))
    assert (d["name"], d["type"], d["line"], d["column"]) == \
        ("alpha", "param", 1, 6)


# Spec: "For unresolved branches, return all reachable possibilities."
def test_unresolved_branches_return_all_possibilities(tmp_path):
    src = ("def f(flag):\n"
           "    x = 1\n"
           "    if flag:\n"
           "        x = 'text'\n"
           "    return x<|>\n")
    assert typenames(infer(tmp_path, src)) == ["int", "str"]


# Spec: "For unresolved branches, return all reachable possibilities."
# Context: a later unconditional assignment replaces the earlier branches.
def test_unconditional_rebinding_ends_the_branches(tmp_path):
    src = ("def f(flag):\n"
           "    if flag:\n"
           "        x = 1\n"
           "    else:\n"
           "        x = 'text'\n"
           "    x = 2.5\n"
           "    return x<|>\n")
    assert typenames(infer(tmp_path, src)) == ["float"]


# Spec: "isinstance(x, SomeClass) — `x` is `SomeClass` inside the `if` body."
# Context: a tuple of classes narrows to the union of them.
def test_isinstance_with_a_tuple_of_classes(tmp_path):
    src = ("class A:\n    pass\n\n\n"
           "class B:\n    pass\n\n\n"
           "def f(v):\n"
           "    if isinstance(v, (A, B)):\n"
           "        return <|>v\n")
    assert typenames(infer(tmp_path, src)) == ["A", "B"]


# Spec: "When the cursor is inside an `isinstance` branch, narrow the type
#        accordingly." Context: an `elif` branch (T30).
def test_isinstance_narrowing_in_an_elif(tmp_path):
    src = ("class A:\n    pass\n\n\n"
           "class B:\n    pass\n\n\n"
           "def f(v):\n"
           "    if isinstance(v, A):\n"
           "        pass\n"
           "    elif isinstance(v, B):\n"
           "        return <|>v\n")
    assert typenames(infer(tmp_path, src)) == ["B"]


# Spec: "Flow-Sensitive Type Narrowing" (T30) -- an assertion narrows the rest
# of the function it sits in.
def test_assert_isinstance_narrowing(tmp_path):
    src = ("class A:\n"
           "    pass\n\n\n"
           "def f(v):\n"
           "    assert isinstance(v, A)\n"
           "    return <|>v\n")
    assert typenames(infer(tmp_path, src)) == ["A"]


# Spec: "If no definition is found, return an empty array (exit 0)."
# Context: an attribute of something that cannot be resolved.
def test_attribute_of_unknown_receiver_is_empty(tmp_path):
    r = raw(tmp_path, "def f(q):\n    return q.na<|>me\n", "goto")
    assert r.returncode == 0
    assert json.loads(r.stdout)["definitions"] == []


# Spec: "`infer` returns what the name at the cursor evaluates to after static
#        propagation through assignments and calls." Context: the callee name of
#        a call evaluates to the function itself (T31).
def test_infer_on_the_callee_of_a_call(tmp_path):
    src = "def make():\n    return 1\n\n\nv = ma<|>ke()\n"
    d = one(infer(tmp_path, src))
    assert (d["type"], d["line"]) == ("function", 1)


# Spec: "`column` ... For `def foo():` this is the column of `f` in `foo`, not
#        the column of the `def` keyword." Context: a name that also occurs
#        inside the keyword itself.
def test_column_of_name_that_hides_in_the_keyword(tmp_path):
    d = one(goto(tmp_path, "def ef():\n    pass\n\n\ne<|>f()\n"))
    assert (d["line"], d["column"]) == (1, 4)


# Spec: "`type` ... One of: module, class, function, instance, statement, param."
# Context: every type the tool can emit is one of the six.
def test_every_emitted_type_is_in_the_enum(tmp_path):
    allowed = {"module", "class", "function", "instance", "statement", "param"}
    sources = [
        "import os\no<|>s\n",
        "class K:\n    pass\n\n\nK<|>\n",
        "def f():\n    pass\n\n\nf<|>\n",
        "x = 1\nx<|>\n",
        "def f(a):\n    return a<|>\n",
        "class K:\n    pass\n\n\nk = K()\nk<|>\n",
    ]
    for src in sources:
        for command in ("infer", "goto"):
            for d in defs(tmp_path, src, command):
                assert d["type"] in allowed, (src, d)
