"""Behaviour pinned by the choices recorded in AMBIGUITIES.md."""

import keyword


# T1: `complete` strips len(prefix) characters under --fuzzy too.
def test_fuzzy_complete_strips_by_character_count(complete):
    item = complete("alphabet = 1\nabt$\n", fuzzy=True).by_name("alphabet")
    assert item["complete"] == "habet"


# T2: a definition is visible on its own line.
def test_assignment_visible_on_its_own_line(complete):
    source = "value = 1\nvalue = value$\n"
    assert "value" in complete(source).names


# T3: True/False/None are offered once, as names rather than keywords.
def test_keyword_builtins_are_not_duplicated(complete):
    items = [item for item in complete("Non$\n").items if item["name"] == "None"]
    assert len(items) == 1
    assert items[0]["type"] != "keyword"


# T5: `__mangled` sorts with the private names.
def test_leading_dunder_without_trailing_dunder_is_private(complete):
    source = "__mangled = 1\n_private = 2\n__dunder__ = 3\nzeta = 4\n$\n"
    names = complete(source).names
    assert names.index("zeta") < names.index("__mangled") < names.index("__dunder__")


# T7: attribute results keep dunder names.
def test_attribute_results_include_dunders(complete):
    names = complete("'text'.$\n").names
    assert "__len__" in names
    assert names[-1].startswith("__")


# T8: parameters are described as `param <name>`.
def test_parameter_description(complete):
    item = complete("def helper(argument):\n    argu$\n").by_name("argument")
    assert item["description"] == "param argument"


# T9: the empty line after a trailing newline is a valid position.
def test_position_after_trailing_newline(write):
    from conftest import run

    path = write("value = 1\n")
    result = run(path, 2, 0)
    assert result.code == 0
    assert "value" in result.names


def test_empty_file_offers_builtins_and_keywords(write):
    from conftest import run

    path = write("")
    result = run(path, 1, 0)
    assert result.code == 0
    assert "print" in result.names


# T10: indentation decides whether a trailing blank line is inside a body.
def test_unindented_blank_line_is_module_level(complete):
    source = "def user():\n    inner_value = 1\n$\n"
    assert "inner_value" not in complete(source).names


# T11: loop and `with` targets are statements.
def test_loop_target_is_a_statement(complete):
    source = "for item in [1, 2]:\n    ite$\n"
    item = complete(source).by_name("item")
    assert item["type"] == "statement"
    assert item["description"] == "statement"


def test_with_target_is_visible(complete):
    source = "with open('f') as handle:\n    hand$\n"
    assert complete(source).by_name("handle")["type"] == "statement"


def test_except_target_is_visible(complete):
    source = "try:\n    pass\nexcept ValueError as error:\n    err$\n"
    assert complete(source).by_name("error")["type"] == "statement"


# T13: builtin dunder names are offered.
def test_builtin_dunders_are_offered(complete):
    assert "__import__" in complete("$\n").names


# T14: `cls` in a classmethod is the class itself.
def test_classmethod_receiver_is_the_class(complete):
    source = (
        "class Widget:\n"
        "    registry = []\n"
        "    @classmethod\n"
        "    def build(cls):\n"
        "        cls.$\n"
    )
    assert "registry" in complete(source).names


def test_staticmethod_first_parameter_is_unresolved(complete):
    source = (
        "class Widget:\n"
        "    registry = []\n"
        "    @staticmethod\n"
        "    def build(value):\n"
        "        value.$\n"
    )
    assert complete(source).items == []


# T15: a local module is resolved without being imported.
def test_local_module_is_not_executed(complete, tmp_path):
    helper = (
        "from pathlib import Path\n"
        "Path('side_effect.txt').write_text('executed')\n"
        "def local_function():\n"
        "    pass\n"
    )
    result = complete(
        "import helper_module\nhelper_module.$\n", extra={"helper_module.py": helper}
    )
    assert "local_function" in result.names
    assert not (tmp_path / "side_effect.txt").exists()


# T17: the nearest preceding binding wins.
def test_latest_binding_before_the_cursor_wins(complete):
    source = "value = 1\nvalue = 'text'\nval$\n"
    assert complete(source).by_name("value")["description"] == "instance of str"


def test_later_rebinding_does_not_hide_the_name(complete):
    source = "value = 1\nval$\nvalue = 'text'\n"
    assert complete(source).by_name("value")["description"] == "instance of int"


# T3: suppression only affects the three keywords that are also builtins.
def test_keyword_list_is_otherwise_complete(complete):
    names = set(complete("$\n").names)
    assert set(keyword.kwlist) <= names


# T19: an assignment binding is described by its right-hand side.
def test_assignment_description_is_the_right_hand_side(goto):
    source = "class Calculator:\n    pass\ncalc = Calculator()\ncal$c\n"
    assert goto(source).only["description"] == "Calculator()"


# T19: a binding with no right-hand expression is described by its statement.
def test_binding_without_a_right_hand_side_is_described_by_its_statement(goto):
    source = "def outside():\n    pass\nfor item in outside():\n    ite$m\n"
    assert goto(source).only["description"] == "for item in outside():"


# T20: goto types an assignment by the value it holds.
def test_goto_types_an_assignment_by_its_value(goto):
    source = "class Calculator:\n    pass\ncalc = Calculator()\ncal$c\n"
    assert goto(source).only["type"] == "instance"


# T21: a literal under the cursor is not a name.
def test_cursor_on_a_literal_exits_one(infer):
    assert infer("text = 'hell$o'\n").code == 1


# T22: the builtin definition for None is named `None`.
def test_none_is_named_none(infer):
    definition = infer("value = None\nvalu$e\n").only
    assert (definition["name"], definition["full_name"]) == ("None", "builtins.None")


# T23: builtin definitions carry the real docstring of their type.
def test_builtin_definition_keeps_its_docstring(infer):
    assert "integer" in infer("count = 1\ncoun$t\n").only["docstring"]


# T24: a definition outside the project root keeps an absolute path, or none
# at all when the object has no source file.
def test_definition_outside_the_project_root_is_absolute(infer):
    definition = infer("import os\nos.pat$h.join\n").only
    assert definition["module_path"] == "" or definition["module_path"].startswith("/")


# T25: an unconditional rebinding hides everything before it.
def test_unconditional_rebinding_wins(infer):
    source = "value = 1\nvalue = 'text'\nvalu$e\n"
    assert [item["name"] for item in infer(source).definitions] == ["str"]


# T25: a conditional rebinding keeps the earlier possibility alive.
def test_conditional_rebinding_keeps_the_earlier_value(infer):
    source = (
        "def user(flag):\n"
        "    value = 1\n"
        "    if flag:\n"
        "        value = 'text'\n"
        "    valu$e\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["int", "str"]


# T26: `is None` narrows the negative branch by removing None.
def test_is_none_negative_branch_removes_none(infer):
    source = (
        "def user(flag):\n"
        "    value = 1 if flag else None\n"
        "    if value is not None:\n"
        "        valu$e\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["int"]


# T27: parameters are unparsed from the syntax tree.
def test_function_description_unparses_its_parameters(goto):
    source = 'def build(size, label="x", *rest, **options):\n    pass\nbuil$d\n'
    assert goto(source).only["description"] == "def build(size, label='x', *rest, **options)"


# T28: goto stops at the import binding, infer follows it.
def test_goto_stops_at_the_import_and_infer_follows(goto, infer):
    extra = {"helper.py": "class Thing:\n    pass\n"}
    source = "from helper import Thing\nThin$g\n"
    assert goto(source, extra=extra).only["module_path"] == "module_under_test.py"
    assert infer(source, extra=extra).only["module_path"] == "helper.py"


# T29: a module definition has no position.
def test_module_definition_has_no_position(infer):
    definition = infer("import helper\nhelpe$r\n", extra={"helper.py": "value = 1\n"}).only
    assert (definition["line"], definition["column"]) == (0, 0)


# T30: an import binding is described by its statement text whatever it binds.
def test_import_binding_description_is_the_statement(goto):
    result = goto(
        "from helper import Thing\nThin$g\n", extra={"helper.py": "class Thing:\n    pass\n"}
    )
    assert result.only["description"] == "from helper import Thing"
    assert result.only["type"] == "class"


# T31: narrowing does not move goto off the binding.
def test_goto_ignores_narrowing(goto):
    source = (
        "class Duck:\n"
        "    pass\n"
        "def handle(animal):\n"
        "    if isinstance(animal, Duck):\n"
        "        anima$l\n"
    )
    definition = goto(source).only
    assert (definition["type"], definition["line"]) == ("param", 3)


# T32: an unresolvable return path drops out of the union.
def test_unresolvable_return_path_is_dropped(infer):
    source = (
        "def pick(flag, other):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return other()\n"
        "value = pick(True, None)\n"
        "valu$e\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["int"]


# T67: a refactoring answers with both sections, even when one is empty.
def test_refactoring_answer_always_holds_both_sections(rename):
    result = rename("def hel$per():\n    pass\n", "worker")
    assert list(result.data) == ["changed_files", "renames"]
    assert result.renames == {}


# T69: renamed paths are spelled relative to the project root.
def test_renamed_paths_are_project_relative(rename):
    extra = {"pack/__init__.py": "", "pack/inner.py": "VALUE = 1\n"}
    result = rename("from pack.in$ner import VALUE\n", "core", extra=extra)
    assert result.renames == {"pack/inner.py": "pack/core.py"}


# T70: a moved file that is also edited is keyed by its old path.
def test_moved_file_is_keyed_by_its_old_path(rename):
    extra = {"pack/__init__.py": "from pack.inner import VALUE\n", "pack/inner.py": "VALUE = 1\n"}
    result = rename("import pac$k\n", "bundle", extra=extra)
    assert result.renames == {"pack": "bundle"}
    assert result.changed_files["pack/__init__.py"] == "from bundle.inner import VALUE\n"


# T71: a name defined later in the same scope still collides.
def test_later_definition_in_the_same_scope_collides(rename):
    assert rename("val$ue = 1\nprint(value)\nworker = 2\n", "worker").code == 1


# T71: shadowing a builtin is not a collision.
def test_shadowing_a_builtin_is_allowed(rename):
    assert rename("val$ue = 1\nprint(value)\n", "list").code == 0


# T72: a keyword is not an acceptable new name.
def test_keyword_is_rejected_as_a_new_name(rename):
    assert rename("val$ue = 1\nprint(value)\n", "class").code == 1


# T73: a cursor that is on no name is an error, not a rename of the file.
def test_cursor_on_a_comment_is_not_a_module_rename(rename):
    result = rename("# no$te\nvalue = 1\n", "tools")
    assert result.code == 1
    assert result.stdout == ""


# T74: the cursor may sit in the dotted path of an import.
def test_cursor_in_a_dotted_import_path_names_that_segment(rename):
    extra = {"pack/__init__.py": "", "pack/inner.py": "VALUE = 1\n"}
    result = rename("import pac$k.inner\n", "bundle", extra=extra)
    assert result.renames == {"pack": "bundle"}


# T76: a name assigned twice cannot be inlined.
def test_name_with_two_assignments_is_not_inlined(inline):
    result = inline("val$ue = 1\nvalue = 2\nprint(value)\n")
    assert result.code == 1
    assert result.stdout == ""


# T77: the value is written exactly as the source writes it.
def test_inlined_value_keeps_its_spacing(inline):
    result = inline("val$ue = a  +  b\nprint(value)\n")
    assert result.changed_files == {"module_under_test.py": "print(a  +  b)\n"}


# T78: brackets appear only where precedence would otherwise change.
def test_inline_adds_no_brackets_where_none_are_needed(inline):
    result = inline("val$ue = a * b\nprint(value * 2)\n")
    assert result.changed_files == {"module_under_test.py": "print(a * b * 2)\n"}


# T79: deleting the definition leaves no blank line behind.
def test_inline_leaves_no_blank_line(inline):
    result = inline("first = 1\nval$ue = 2\nlast = value\n")
    assert result.changed_files == {"module_under_test.py": "first = 1\nlast = 2\n"}


# T80: inlining may start from any reference to the name.
def test_inline_from_the_last_reference(inline):
    result = inline("value = 2\nfirst = value\nsecond = val$ue\n")
    assert result.changed_files == {"module_under_test.py": "first = 2\nsecond = 2\n"}


# T81: only the selected occurrence of an expression is extracted.
def test_extract_variable_leaves_equal_expressions_alone(extract_variable):
    source = "first = $compute(3)~\nsecond = compute(3)\n"
    assert extract_variable(source, "value").changed_files == {
        "module_under_test.py": "value = compute(3)\nfirst = value\nsecond = compute(3)\n"
    }


# T82: brackets around the selected expression are part of the selection.
def test_bracketed_selection_extracts_the_expression(extract_variable):
    result = extract_variable("result = $(compute(3))~ + 1\n", "value")
    assert result.changed_files == {
        "module_under_test.py": "value = compute(3)\nresult = value + 1\n"
    }


# T82: an unbalanced bracket is still a cut expression.
def test_unbalanced_selection_is_rejected(extract_variable):
    result = extract_variable("result = $(compute(3)~ + 1\n", "value")
    assert result.code == 1


# T84: an import read by the selection stays global instead of becoming a parameter.
def test_imported_name_is_not_a_parameter(extract_function):
    source = "import os\n\ndef run():\n$    print(os.sep)~\n"
    changed = extract_function(source, "show").changed_files["module_under_test.py"]
    assert "def show():" in changed


# T86: a block that awaits becomes an async function, awaited at the call site.
def test_awaiting_block_extracts_to_a_coroutine(extract_function):
    source = "async def run():\n    a = 1\n$    b = await fetch(a)~\n    return b\n"
    changed = extract_function(source, "grab").changed_files["module_under_test.py"]
    assert changed.startswith("async def grab(a):")
    assert "    b = await grab(a)\n" in changed


# T87: a selection ending at column 0 of the next line covers whole lines.
def test_selection_to_the_start_of_the_next_line(extract_function):
    source = "def run():\n    a = 1\n$    print(a)\n~"
    assert extract_function(source, "show").code == 0


# T88: the parser stops at the first error, so one error is reported.
def test_only_the_first_syntax_error_is_reported(errors):
    result = errors("x = = 1\ny = = 2\n")
    assert len(result.syntax_errors) == 1
    assert result.syntax_errors[0]["line"] == 1


# T89: an error the parser leaves open ends where it starts.
def test_open_ended_error_ends_at_its_start(errors):
    [error] = errors("y = (\n").syntax_errors
    assert error["until_column"] >= error["column"]


# T90: the message is the parser's own, with no exception class in front.
def test_message_carries_no_exception_class(errors):
    [error] = errors("x = = 1\n").syntax_errors
    assert error["message"] == "invalid syntax"


# T100: an attribute a namespace only names is completed as a runtime instance.
def test_namespace_attribute_is_a_runtime_instance(interpreter):
    namespaces = [{"tools": {"type": "module", "attributes": ["load"]}}]
    item = interpreter("complete", "tools.$\n", namespaces).by_name("load")
    assert (item["type"], item["description"]) == ("instance", "instance (runtime)")


# T101: `infer` does not answer for an attribute of a namespace value.
def test_no_runtime_definition_for_an_attribute(interpreter):
    namespaces = [{"tools": {"type": "module", "attributes": ["load"]}}]
    assert interpreter("infer", "tools.loa$d\n", namespaces).definitions == []


# T102: namespaces contribute no signatures.
def test_namespaces_contribute_no_signatures(interpreter):
    namespaces = [{"handler": {"type": "function"}}]
    assert interpreter("signatures", "handler($)\n", namespaces).signatures == []


# T103: `infer` falls back when a static binding holds an unknown value, while
# `goto` keeps the binding it found.
def test_infer_falls_back_for_an_unresolved_binding(interpreter):
    source = "value = unknown_call()\nvalu$e\n"
    assert interpreter("infer", source, [{"value": {"type": "int"}}]).only["type"] == "int"


def test_goto_keeps_the_static_binding_it_found(interpreter):
    source = "value = unknown_call()\nvalu$e\n"
    assert interpreter("goto", source, [{"value": {"type": "int"}}]).only["line"] == 1


# T107: runtime names are not offered where a module path is being written.
def test_namespace_names_are_not_module_completions(interpreter):
    result = interpreter("complete", "import $\n", [{"runtime_only": {"type": "module"}}])
    assert "runtime_only" not in result.names


def test_namespace_names_are_not_import_clause_completions(interpreter):
    namespaces = [{"runtime_only": {"type": "int"}}]
    result = interpreter(
        "complete", "from helper import $\n", namespaces,
        extra={"helper.py": "written = 1\n"},
    )
    assert result.names == ["written"]


# T110: a comprehension is not a named scope, so the function around it answers.
def test_a_comprehension_reports_the_function_around_it(tmp_path):
    from conftest import invoke, write_source

    source = "def run():\n    return [item$ for item in range(3)]\n"
    path, line, col = write_source(tmp_path, source)
    assert [item["name"] for item in invoke("context", path, line, col).data["context"]] == ["run"]


# T116: `add_bracket` reaches namespace-derived functions too.
def test_add_bracket_applies_to_a_runtime_function(interpreter):
    namespaces = [{"handler": {"type": "function"}}]
    result = interpreter("complete", "handl$\n", namespaces, flags=["--setting", "add_bracket=true"])
    assert result.by_name("handler")["complete"] == "er("


# T117: `smart_sys_path=false` leaves the project-wide commands reading files.
def test_search_still_reads_the_project_without_detected_paths(tmp_path):
    from conftest import run_command, write_files

    write_files(tmp_path, {"a.py": "value = 1\n"})
    result = run_command(
        "search", "value", project=tmp_path, flags=["--setting", "smart_sys_path=false"]
    )
    assert [item["name"] for item in result.definitions] == ["value"]
