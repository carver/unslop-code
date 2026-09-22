"""Spec: `goto <file> <line> <col> [--follow-imports]`."""

THING = "class Thing:\n    pass\n"


# Spec: "Without `--follow-imports` (default), `goto` on an imported name
# returns the `import` statement itself".
def test_default_goto_returns_the_import_statement(goto):
    result = goto("from helper import Thing\nThin$g\n", extra={"helper.py": THING})
    assert (result.only["module_path"], result.only["line"]) == ("module_under_test.py", 1)


# Spec: "With `--follow-imports`, `goto` follows the import chain and returns
# the actual definition in the source module".
def test_follow_imports_reaches_the_source_definition(goto):
    result = goto(
        "from helper import Thing\nThin$g\n", extra={"helper.py": THING}, follow=True
    )
    assert result.only["module_path"] == "helper.py"
    assert (result.only["line"], result.only["column"]) == (1, 6)
    assert result.only["type"] == "class"


def test_follow_imports_reaches_an_assigned_name(goto):
    result = goto(
        "from helper import value\nvalu$e\n",
        extra={"helper.py": "value = 41\n"},
        follow=True,
    )
    assert (result.only["module_path"], result.only["line"]) == ("helper.py", 1)


def test_follow_imports_reaches_a_renamed_import(goto):
    result = goto(
        "from helper import Thing as Alias\nAlia$s\n",
        extra={"helper.py": THING},
        follow=True,
    )
    assert (result.only["module_path"], result.only["line"]) == ("helper.py", 1)


# Spec: "`--follow-imports` follows the import chain to the final definition."
def test_follow_imports_walks_a_chain_of_re_exports(goto):
    extra = {"base.py": THING, "middle.py": "from base import Thing\n"}
    result = goto(
        "from middle import Thing\nThin$g\n", extra=extra, follow=True
    )
    assert (result.only["module_path"], result.only["line"]) == ("base.py", 1)


def test_follow_imports_walks_through_a_star_import(goto):
    extra = {"base.py": THING, "middle.py": "from base import *\n"}
    result = goto("from middle import Thing\nThin$g\n", extra=extra, follow=True)
    assert result.only["module_path"] == "base.py"


def test_follow_imports_walks_through_a_relative_import(goto):
    extra = {
        "pkg/__init__.py": "",
        "pkg/base.py": THING,
        "pkg/middle.py": "from .base import Thing\n",
    }
    result = goto(
        "from pkg.middle import Thing\nThin$g\n", extra=extra, project=".", follow=True
    )
    assert result.only["module_path"] == "pkg/base.py"


# Spec: "With `--follow-imports`, `goto` follows the import chain" - a plain
# `import` names the module itself.
def test_follow_imports_on_a_module_binding(goto):
    result = goto("import helper\nhelpe$r\n", extra={"helper.py": THING}, follow=True)
    assert result.only["module_path"] == "helper.py"
    assert result.only["type"] == "module"


# Spec: "If the import chain leads to a module that cannot be found (e.g.,
# third-party or stdlib), return the import statement as a fallback."
def test_follow_imports_falls_back_for_the_standard_library(goto):
    result = goto("from os import getcwd\ngetcw$d\n", follow=True)
    assert (result.only["module_path"], result.only["line"]) == ("module_under_test.py", 1)
    assert result.only["column"] == 15


def test_follow_imports_falls_back_for_an_unknown_module(goto):
    result = goto("from no_such_module import Thing\nThin$g\n", follow=True)
    assert (result.only["module_path"], result.only["line"]) == ("module_under_test.py", 1)


# Spec: "if the terminal target cannot be resolved, return the import site in
# the current file as the fallback definition."
def test_follow_imports_falls_back_when_the_chain_breaks(goto):
    extra = {"middle.py": "from no_such_module import Thing\n"}
    result = goto("from middle import Thing\nThin$g\n", extra=extra, follow=True)
    assert (result.only["module_path"], result.only["line"]) == ("module_under_test.py", 1)


def test_follow_imports_falls_back_for_a_name_the_module_lacks(goto):
    result = goto(
        "from helper import missing\nmissin$g\n", extra={"helper.py": THING}, follow=True
    )
    assert (result.only["module_path"], result.only["line"]) == ("module_under_test.py", 1)


# Spec: `--follow-imports` only concerns imports; other names are unaffected.
def test_follow_imports_leaves_local_definitions_alone(goto):
    result = goto("def compute():\n    pass\ncomput$e()\n", follow=True)
    assert (result.only["module_path"], result.only["line"]) == ("module_under_test.py", 1)


# Spec: "Circular imports: do not infinite-loop."
def test_follow_imports_terminates_on_a_cycle(goto):
    extra = {
        "left.py": "from right import Thing\n",
        "right.py": "from left import Thing\n",
    }
    result = goto("from left import Thing\nThin$g\n", extra=extra, follow=True)
    assert result.code == 0


# Spec: "`--follow-imports` follows the import chain to the final definition"
# - reached through the module an attribute is read from.
def test_follow_imports_on_an_attribute_of_an_imported_module(goto):
    extra = {"base.py": THING, "middle.py": "from base import Thing\n"}
    result = goto("import middle\nmiddle.Thin$g\n", extra=extra, follow=True)
    assert result.only["module_path"] == "base.py"
