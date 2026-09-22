"""End to end checks of the behaviour the spec pins down."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SOURCE = '''\
import os
from helpers import shout
from helpers import *

TOTAL = 42


class Animal:
    kingdom = "animalia"

    def __init__(self, name):
        self.name = name
        self.legs = 4

    def speak(self):
        return "..."


class Dog(Animal):
    def __init__(self, name):
        super().__init__(name)
        self.breed = "mutt"


rex = Dog("rex")


def outer(count):
    label = "x"

    def inner(depth):
        early = 1

        later = 2
    return inner


AFTER = 9
'''

HELPERS = '''\
VERSION = "1.0"
_SECRET = "hidden"


def shout(text):
    return text.upper()
'''


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "helpers.py").write_text(HELPERS)
    path = tmp_path / "demo.py"
    path.write_text(SOURCE)
    return path


def run(path: Path, line: int, column: int, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), "complete",
         str(path), str(line), str(column), *flags],
        capture_output=True, text=True, cwd=ROOT)


def complete(path: Path, line: int, column: int, *flags: str) -> list[dict[str, str]]:
    result = run(path, line, column, *flags)
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("}\n")
    return json.loads(result.stdout)["completions"]


def names(completions: list[dict[str, str]]) -> list[str]:
    return [completion["name"] for completion in completions]


def entry(completions: list[dict[str, str]], name: str) -> dict[str, str]:
    return next(completion for completion in completions if completion["name"] == name)


# -- names and scopes ------------------------------------------------------

def test_local_names_before_the_cursor_only(workspace):
    visible = names(complete(workspace, 32, 8))
    assert "early" in visible and "later" not in visible


def test_enclosing_and_global_scopes(workspace):
    visible = names(complete(workspace, 32, 8))
    assert {"depth", "count", "label", "TOTAL", "os", "print"} <= set(visible)
    assert "AFTER" not in visible  # defined below the cursor


def test_prefix_filters_and_is_stripped_from_the_insertion(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("printer = 1\nprin\n")
    completions = complete(path, 2, 4)
    assert names(completions) == ["print", "printer"]
    assert [c["complete"] for c in completions] == ["t", "ter"]


def test_empty_prefix_returns_every_visible_name(workspace):
    offered = names(complete(workspace, 25, 0))
    assert {"rex", "Animal", "Dog", "TOTAL", "os", "shout", "print", "class"} <= set(offered)


def test_prefix_match_is_case_insensitive(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("TOTAL = 1\ntot\n")
    assert entry(complete(path, 2, 3), "TOTAL")["complete"] == "AL"


def test_fuzzy_matches_subsequences(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def alpha_beta_gamma():\n    pass\n\n\nabg\n")
    assert complete(path, 5, 3) == []
    assert names(complete(path, 5, 3, "--fuzzy")) == ["alpha_beta_gamma"]


def test_keywords_are_offered_and_sorted_last(workspace):
    completions = complete(workspace, 25, 0)
    keywords = [index for index, c in enumerate(completions) if c["type"] == "keyword"]
    assert keywords and min(keywords) > max(set(range(len(completions))) - set(keywords))
    assert entry(completions, "return")["description"] == "return"


def test_ordering_groups_public_private_then_dunder(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("__z__ = 1\n_y = 2\nx = 3\n\n")
    ordered = names(complete(path, 4, 0))
    assert ordered.index("x") < ordered.index("_y") < ordered.index("__z__")


# -- attributes ------------------------------------------------------------

def test_module_attributes_are_public_only(workspace):
    path = workspace.with_name("probe.py")
    path.write_text("import helpers\nhelpers.\n")
    offered = names(complete(path, 2, 8))
    assert offered == ["shout", "VERSION"]


def test_instance_attributes_include_init_and_inherited(workspace):
    path = workspace.with_name("probe.py")
    path.write_text(SOURCE + "rex.\n")
    offered = names(complete(path, len(SOURCE.splitlines()) + 1, 4))
    assert {"breed", "name", "legs", "kingdom", "speak"} <= set(offered)


def test_class_attributes_exclude_instance_only_names(workspace):
    path = workspace.with_name("probe.py")
    path.write_text(SOURCE + "Animal.\n")
    offered = names(complete(path, len(SOURCE.splitlines()) + 1, 7))
    assert "kingdom" in offered and "speak" in offered
    assert "legs" not in offered


def test_self_resolves_to_the_enclosing_class(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("class Box:\n    def __init__(self):\n        self.size = 1\n\n"
                    "    def grow(self):\n        self.\n")
    assert names(complete(path, 6, 13)) == ["grow", "size", "__init__"]


def test_literal_attributes(tmp_path):
    path = tmp_path / "m.py"
    path.write_text('"hello".upp\n')
    assert names(complete(path, 1, 11)) == ["upper"]


def test_chained_module_attribute(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("import os\nos.path.jo\n")
    assert names(complete(path, 2, 10)) == ["join"]


def test_attributes_never_include_keywords(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("import os\nos.\n")
    assert all(c["type"] != "keyword" for c in complete(path, 2, 3))


def test_star_import_exposes_public_names(workspace):
    offered = names(complete(workspace, 25, 0))
    assert "VERSION" in offered and "_SECRET" not in offered


def test_imported_names_report_their_kind(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("from os.path import join\nfrom collections import OrderedDict\nimport os\n\n")
    completions = complete(path, 4, 0)
    assert entry(completions, "join")["type"] == "function"
    assert entry(completions, "OrderedDict")["type"] == "class"
    assert entry(completions, "os") == {
        "name": "os", "complete": "os", "type": "module", "description": "module os"}


# -- tolerance and failure modes ------------------------------------------

def test_syntax_errors_still_complete(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def broken(:\n    pass\n\nVALUE = 10\n\nclass Thing\n    pass\n\nVALU\n")
    assert "VALUE" in names(complete(path, 9, 4))


def test_missing_file_fails(tmp_path):
    result = run(tmp_path / "absent.py", 1, 0)
    assert result.returncode == 1 and result.stderr.strip()


def test_directory_fails(tmp_path):
    assert run(tmp_path, 1, 0).returncode == 1


def test_non_utf8_fails(tmp_path):
    path = tmp_path / "m.py"
    path.write_bytes(b"\xff\xfe\x00bad")
    assert run(path, 1, 0).returncode == 1


@pytest.mark.parametrize("line,column", [(99, 0), (1, 99), (0, 0)])
def test_position_out_of_range_fails(tmp_path, line, column):
    path = tmp_path / "m.py"
    path.write_text("x = 1\n")
    assert run(path, line, column).returncode == 1


def test_no_matches_still_succeeds(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("import os\nos.zzzzz\n")
    result = run(path, 2, 8)
    assert result.returncode == 0 and result.stdout == '{"completions":[]}\n'


# -- definitions: infer and goto -------------------------------------------

DEFS = '''\
"""Definitions sample."""

from dataclasses import dataclass

import helpers


class Calculator:
    """Adds things."""

    def __init__(self, start):
        self.total = start

    def add(self, value):
        return self.total


@dataclass
class Point:
    x: int
    y: str = "up"


def make(flag):
    if flag:
        return Calculator(0)
    return Point(1)


def nothing():
    pass


def narrow(thing, maybe):
    if isinstance(thing, Point):
        thing
        thing.x
    if maybe is None:
        maybe


calc = Calculator(0)
count = 5
label = "hi"
made = make(True)
empty = nothing()
alias = calc
if count:
    choice = Calculator(0)
else:
    choice = Point(2)
choice
calc.add
'''


@pytest.fixture
def defs(tmp_path: Path) -> Path:
    (tmp_path / "helpers.py").write_text(HELPERS)
    path = tmp_path / "defs.py"
    path.write_text(DEFS)
    return path


def position(text: str, needle: str, offset: int = 0) -> tuple[int, int]:
    """The 1-based line and 0-based column ``offset`` characters into ``needle``."""
    index = text.index(needle) + offset
    return text.count("\n", 0, index) + 1, index - text.rfind("\n", 0, index) - 1


def ask(command: str, path: Path, line: int, column: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), command, str(path), str(line), str(column)],
        capture_output=True, text=True, cwd=ROOT)


def definitions(command: str, path: Path, line: int, column: int) -> list[dict]:
    result = ask(command, path, line, column)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["definitions"]


def typed(found: list[dict]) -> list[tuple[str, str]]:
    return [(item["name"], item["type"]) for item in found]


def probe(defs: Path, suffix: str) -> tuple[Path, int]:
    """A copy of the sample with ``suffix`` appended, and the line it starts on."""
    path = defs.with_name("probe.py")
    path.write_text(DEFS + suffix)
    return path, len(DEFS.splitlines()) + 1


def test_goto_reports_every_field_of_a_class(defs):
    line, column = position(DEFS, "calc = Calculator(0)", len("calc = C"))
    assert definitions("goto", defs, line, column) == [{
        "name": "Calculator", "type": "class", "full_name": "defs.Calculator",
        "module_path": "defs.py", "line": position(DEFS, "class Calculator")[0],
        "column": len("class "), "description": "class Calculator",
        "docstring": "Adds things."}]


def test_goto_reports_the_assignment_that_binds_the_name(defs):
    line, column = position(DEFS, "alias = calc")
    assert definitions("goto", defs, line, column + 2) == [{
        "name": "alias", "type": "statement", "full_name": "defs.alias",
        "module_path": "defs.py", "line": line, "column": column,
        "description": "alias = calc", "docstring": ""}]


def test_infer_follows_assignment_chains_to_an_instance(defs):
    line, column = position(DEFS, "alias = calc")
    found = definitions("infer", defs, line, column + 2)
    assert typed(found) == [("Calculator", "instance")]
    assert found[0]["description"] == "instance of Calculator"
    assert found[0]["line"] == position(DEFS, "class Calculator")[0]


def test_infer_reports_literals_as_placeless_builtins(defs):
    line, column = position(DEFS, "label = ", 2)
    found = definitions("infer", defs, line, column)
    assert typed(found) == [("str", "instance")]
    assert found[0]["full_name"] == "builtins.str"
    assert (found[0]["module_path"], found[0]["line"], found[0]["column"]) == ("", 0, 0)


def test_infer_a_function_return_type(defs):
    line, column = position(DEFS, "made = make(True)", 1)
    assert typed(definitions("infer", defs, line, column)) == [
        ("Calculator", "instance"), ("Point", "instance")]


def test_a_function_without_a_return_yields_none(defs):
    line, column = position(DEFS, "empty = nothing()", 1)
    found = definitions("infer", defs, line, column)
    assert typed(found) == [("None", "instance")]
    assert found[0]["full_name"] == "builtins.None"


def test_conditional_assignments_report_every_possibility(defs):
    line, column = position(DEFS, "choice\n", 1)
    assert typed(definitions("infer", defs, line, column)) == [
        ("Calculator", "instance"), ("Point", "instance")]
    assert [item["description"] for item in definitions("goto", defs, line, column)] == [
        "choice = Calculator(0)", "choice = Point(2)"]


def test_definitions_are_sorted_by_location(defs):
    line, column = position(DEFS, "choice\n", 1)
    found = definitions("goto", defs, line, column)
    keys = [(item["module_path"], item["line"], item["column"]) for item in found]
    assert keys == sorted(keys)


def test_goto_an_attribute_lands_on_its_definition(defs):
    line, column = position(DEFS, "calc.add", len("calc.a"))
    found = definitions("goto", defs, line, column)
    assert found[0]["full_name"] == "defs.Calculator.add"
    assert found[0]["description"] == "def add(self, value)"
    assert found[0]["type"] == "function"


def test_goto_an_attribute_assigned_on_self(defs):
    path, line = probe(defs, "calc.total\n")
    found = definitions("goto", path, line, len("calc.t"))
    assert found[0]["full_name"] == "probe.Calculator.total"
    assert found[0]["description"] == "self.total = start"


def test_infer_an_attribute_of_an_instance(defs):
    line, column = position(DEFS, "thing.x", len("thing."))
    assert typed(definitions("infer", defs, line, column)) == [("int", "instance")]


def test_goto_an_imported_name_reports_the_import_statement(defs):
    line, column = position(DEFS, "import helpers", len("import h"))
    found = definitions("goto", defs, line, column)
    assert (found[0]["type"], found[0]["description"]) == ("module", "import helpers")
    assert found[0]["module_path"] == "defs.py"


def test_infer_an_imported_name_crosses_into_its_module(defs):
    path = defs.with_name("probe.py")
    path.write_text("from helpers import shout\nshout\n")
    assert definitions("infer", path, 2, 2) == [{
        "name": "shout", "type": "function", "full_name": "helpers.shout",
        "module_path": "helpers.py", "line": position(HELPERS, "def shout")[0],
        "column": len("def "), "description": "def shout(text)", "docstring": ""}]


def test_goto_a_definition_and_a_parameter(defs):
    line, column = position(DEFS, "def make(flag)", len("def m"))
    assert typed(definitions("goto", defs, line, column)) == [("make", "function")]
    line, column = position(DEFS, "def make(flag)", len("def make(f"))
    found = definitions("goto", defs, line, column)
    assert typed(found) == [("flag", "param")]
    assert found[0]["full_name"] == "defs.make.flag"


def test_a_bare_function_name_infers_to_its_own_definition(defs):
    line, column = position(DEFS, "def nothing", len("def n"))
    assert definitions("infer", defs, line, column) == definitions("goto", defs, line, column)


# -- narrowing -------------------------------------------------------------

def test_isinstance_narrows_the_type_inside_the_branch(defs):
    line, column = position(DEFS, "thing\n", 1)
    assert typed(definitions("infer", defs, line, column)) == [("Point", "instance")]


def test_isinstance_narrows_attribute_completion(defs):
    line, column = position(DEFS, "thing.x", len("thing."))
    assert names(complete(defs, line, column)) == ["x", "y"]


def test_is_none_narrows_the_type_inside_the_branch(defs):
    line, column = position(DEFS, "maybe\n", 1)
    assert typed(definitions("infer", defs, line, column)) == [("None", "instance")]


def test_completion_merges_the_attributes_of_every_possible_type(defs):
    path, line = probe(defs, "choice.\n")
    assert {"total", "add", "x", "y"} <= set(names(complete(path, line, len("choice."))))


# -- dataclasses -----------------------------------------------------------

DATACLASSES = '''\
import dataclasses
from dataclasses import dataclass as record


@dataclasses.dataclass(frozen=True)
class Frozen:
    depth: float


@record
class Aliased:
    tag: str


frozen = Frozen(1.0)
aliased = Aliased("x")
'''


def test_dataclass_fields_are_instance_attributes(tmp_path):
    path = tmp_path / "data.py"
    path.write_text(DATACLASSES + "frozen.\n")
    assert names(complete(path, len(DATACLASSES.splitlines()) + 1, len("frozen."))) == ["depth"]


def test_dataclass_fields_infer_from_their_annotation(tmp_path):
    path = tmp_path / "data.py"
    path.write_text(DATACLASSES + "aliased.tag\n")
    line = len(DATACLASSES.splitlines()) + 1
    assert typed(definitions("infer", path, line, len("aliased.t"))) == [("str", "instance")]


# -- failure modes ---------------------------------------------------------

@pytest.mark.parametrize("command", ["infer", "goto"])
def test_a_cursor_that_is_not_on_a_name_fails(defs, command):
    line, column = position(DEFS, "count = 5", len("count "))
    result = ask(command, defs, line, column)
    assert result.returncode == 1 and result.stderr.strip()


@pytest.mark.parametrize("command", ["infer", "goto"])
def test_an_unresolved_name_returns_nothing(tmp_path, command):
    path = tmp_path / "m.py"
    path.write_text("missing\n")
    result = ask(command, path, 1, 3)
    assert result.returncode == 0 and result.stdout == '{"definitions":[]}\n'


@pytest.mark.parametrize("command", ["infer", "goto"])
def test_a_position_out_of_range_fails(defs, command):
    assert ask(command, defs, 999, 0).returncode == 1
