"""`goto --follow-imports`, and the import statement it falls back to."""

WIDGET = 'class Widget:\n    """A widget."""\n\n\ndef build():\n    return Widget()\n'


# Spec: "Without `--follow-imports` (default), `goto` on an imported name returns the
#        `import` statement itself"
def test_goto_stops_at_the_import_statement_by_default(goto):
    source = "from helpers import Widget\n\nw = Wid|get()\n"
    definition = goto(source, files={"helpers.py": WIDGET}).only
    assert (definition["module_path"], definition["line"]) == ("sample.py", 1)


# Spec: "With `--follow-imports`, `goto` follows the import chain and returns the actual
#        definition in the source module"
def test_follow_imports_reaches_the_source_module(goto):
    source = "from helpers import Widget\n\nw = Wid|get()\n"
    definition = goto(source, files={"helpers.py": WIDGET}, follow_imports=True).only
    assert (definition["module_path"], definition["line"], definition["column"]) == (
        "helpers.py",
        1,
        6,
    )
    assert definition["type"] == "class"


# Spec: "--follow-imports follows the import chain to the final definition."
def test_follow_imports_walks_a_chain(goto):
    files = {"middle.py": "from base import Widget\n", "base.py": WIDGET}
    source = "from middle import Widget\n\nw = Wid|get()\n"
    definition = goto(source, files=files, follow_imports=True).only
    assert (definition["module_path"], definition["line"]) == ("base.py", 1)


# Spec: following from the import statement itself, not only from a later use.
def test_follow_imports_from_the_import_line(goto):
    source = "from helpers import Wid|get\n"
    definition = goto(source, files={"helpers.py": WIDGET}, follow_imports=True).only
    assert definition["module_path"] == "helpers.py"


# Spec: "If the import chain leads to a module that cannot be found (e.g., third-party or
#        stdlib), return the import statement as a fallback."
def test_unresolvable_module_falls_back_to_the_import_statement(goto):
    source = "from nowhere_at_all import thing\n\nthi|ng\n"
    definition = goto(source, follow_imports=True).only
    assert (definition["module_path"], definition["line"]) == ("sample.py", 1)


# Spec: "... (e.g., third-party or stdlib) ..."
def test_stdlib_import_falls_back_to_the_import_statement(goto):
    definition = goto("from os import getcwd\n\ngetc|wd()\n", follow_imports=True).only
    assert (definition["module_path"], definition["line"]) == ("sample.py", 1)


# Spec: "With `--follow-imports`, if the terminal target cannot be resolved, return the
#        import site in the current file as the fallback definition."
def test_missing_name_in_a_real_module_falls_back(goto):
    source = "from helpers import absent\n\nabs|ent\n"
    definition = goto(source, files={"helpers.py": WIDGET}, follow_imports=True).only
    assert (definition["module_path"], definition["line"]) == ("sample.py", 1)


# Spec: `--follow-imports` on a plain `import` lands on the module itself.
def test_follow_imports_on_a_module_name(goto):
    definition = goto("import helpers\nhelp|ers\n", files={"helpers.py": WIDGET},
                      follow_imports=True).only
    assert definition["module_path"] == "helpers.py"
    assert definition["type"] == "module"


# Spec: the flag changes nothing for names defined in the file itself.
def test_follow_imports_leaves_local_definitions_alone(goto):
    source = "def helper():\n    pass\n\nhel|per()\n"
    definition = goto(source, follow_imports=True).only
    assert (definition["module_path"], definition["line"]) == ("sample.py", 1)


# Spec: aliased imports are followed to the original definition.
def test_follow_imports_through_an_alias(goto):
    source = "from helpers import Widget as W\n\nW|()\n"
    definition = goto(source, files={"helpers.py": WIDGET}, follow_imports=True).only
    assert (definition["name"], definition["module_path"]) == ("Widget", "helpers.py")
