"""Definitions that live in another file of the project."""

HELPERS = (
    "class Widget:\n"
    '    """A widget."""\n'
    "\n"
    "    def resize(self):\n"
    "        return 1\n"
    "\n"
    "\n"
    "def build():\n"
    "    return Widget()\n"
)


# Spec: "`module_path` | string | File path where the name is defined, relative to the
#        project root."
def test_infer_points_at_the_defining_file(infer):
    source = "from helpers import Widget\nw = Widget()\n|w\n"
    definition = infer(source, files={"helpers.py": HELPERS}).only
    assert definition["module_path"] == "helpers.py"
    assert definition["full_name"] == "helpers.Widget"
    assert definition["line"] == 1
    assert definition["docstring"] == "A widget."


# Spec: "infer returns what the name at the cursor evaluates to after static
#        propagation through assignments and calls."
def test_return_type_from_another_module(infer):
    source = "import helpers\nw = helpers.build()\n|w\n"
    definition = infer(source, files={"helpers.py": HELPERS}).only
    assert definition["name"] == "Widget"
    assert definition["type"] == "instance"
    assert definition["module_path"] == "helpers.py"


# Spec: attribute completion uses inferred types, across modules too.
def test_attribute_completion_across_modules(complete, workdir):
    (workdir / "helpers.py").write_text(HELPERS, encoding="utf-8")
    names = complete("import helpers\nw = helpers.build()\nw.|\n").names
    assert "resize" in names


# Spec: "goto returns where the name at the cursor is assigned or defined."
def test_goto_a_module_attribute(goto):
    source = "import helpers\nhelpers.Wid|get\n"
    definition = goto(source, files={"helpers.py": HELPERS}).only
    assert (definition["module_path"], definition["line"], definition["column"]) == (
        "helpers.py",
        1,
        6,
    )
