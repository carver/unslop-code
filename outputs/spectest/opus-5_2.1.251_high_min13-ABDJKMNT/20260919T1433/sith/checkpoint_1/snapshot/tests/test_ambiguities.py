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
