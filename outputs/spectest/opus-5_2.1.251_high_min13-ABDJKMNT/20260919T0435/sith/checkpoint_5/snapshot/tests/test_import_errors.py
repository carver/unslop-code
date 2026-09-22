"""Circular imports, missing modules, and unparsable imported files."""


# Spec: "Circular imports: do not infinite-loop."
def test_circular_import_terminates(infer):
    files = {
        "left.py": "from right import Right\n\n\nclass Left:\n    pass\n",
        "right.py": "from left import Left\n\n\nclass Right:\n    pass\n",
    }
    result = infer("from left import Left\nx = Left()\n|x\n", files=files)
    assert result.returncode == 0
    assert result.only["module_path"] == "left.py"


# Spec: "If module A imports B and B imports A, resolve what is available at the point of
#        the circular reference and move on."
def test_circular_import_still_resolves_what_exists(complete):
    files = {
        "left.py": "from right import helper\n\n\ndef left_thing():\n    pass\n",
        "right.py": "from left import left_thing\n\n\ndef helper():\n    pass\n",
    }
    names = set(complete("from left import *\n|\n", files=files).names)
    assert {"left_thing", "helper"} <= names


# Spec: "Names not yet defined at the point of circular import are simply not visible."
def test_circular_self_reference_is_empty(infer):
    files = {"loop.py": "from loop import thing\n"}
    assert infer("from loop import thing\n|thing\n", files=files).definitions == []


# Spec: "Import of nonexistent module: not an error -- return empty results for that
#        module's names."
def test_missing_module_is_not_an_error(infer):
    result = infer("import nowhere_at_all\n|nowhere_at_all\n")
    assert result.returncode == 0
    assert result.definitions == []


def test_missing_submodule_is_not_an_error(complete):
    files = {"pkg/__init__.py": ""}
    result = complete("from pkg.absent import thing\nthing.|\n", files=files)
    assert result.returncode == 0
    assert result.completions == []


# Spec: "Syntax errors in imported files: parse as much as possible (same tolerance as
#        the main file)."
def test_syntax_error_in_an_imported_file(complete):
    broken = "def good():\n    pass\nthis is not python(((\nclass Widget:\n    pass\n"
    result = complete("import broken\nbroken.|\n", files={"broken.py": broken})
    assert result.returncode == 0
    assert {"good", "Widget"} <= set(result.names)


# Spec: "Syntax errors in imported files: parse as much as possible."
def test_goto_into_a_file_with_a_syntax_error(goto):
    broken = "!!!\nclass Widget:\n    pass\n"
    source = "from broken import Widget\nWid|get\n"
    definition = goto(source, files={"broken.py": broken}, follow_imports=True).only
    assert (definition["module_path"], definition["line"]) == ("broken.py", 2)
