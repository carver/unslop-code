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


# -- projects: imports across files ----------------------------------------

PACKAGE = {
    "app.py": '''\
from pkg import Engine
from pkg.core import build, SPEED
from pkg.deep.leaf import sprout
import pkg.core
import space.free
import os

motor = Engine(3)
made = build()
grown = sprout()
''',
    "pkg/__init__.py": '''\
"""The pkg package."""

from .core import Engine

__all__ = ["Engine", "TITLE"]

TITLE = "pkg"
HIDDEN = "no"
''',
    "pkg/core.py": '''\
SPEED = 88


class Engine:
    """Runs things."""

    def __init__(self, power):
        self.power = power

    def start(self):
        return self.power


def build():
    return Engine(10)
''',
    "pkg/deep/__init__.py": "",
    "pkg/deep/leaf.py": '''\
from ..core import Engine
from .... import escapee


def sprout():
    return Engine(1)
''',
    "space/free.py": 'NAME = "namespace"\n',
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for name, text in PACKAGE.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def located(project: Path, text: str, needle: str, offset: int = 0) -> tuple[int, int]:
    return position(PACKAGE[text], needle, offset)


def found(command: str, path: Path, line: int, column: int, *flags: str) -> list[dict]:
    """Run ``command`` against ``path`` with the project rooted where it lives.

    Every file of the sample sits under the same root, however deeply nested,
    which is what ``--project`` is for.
    """
    root = next(parent for parent in path.parents if (parent / "app.py").is_file())
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), command, str(path), str(line), str(column),
         "--project", str(root), *flags],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)[
        "completions" if command == "complete" else "definitions"]


def test_goto_an_imported_name_stops_at_the_import_by_default(project):
    line, column = located(project, "app.py", "from pkg import Engine", len("from pkg import E"))
    reported = found("goto", project / "app.py", line, column)
    assert (reported[0]["module_path"], reported[0]["description"]) == (
        "app.py", "from pkg import Engine")


def test_follow_imports_crosses_the_re_export_chain(project):
    line, column = located(project, "app.py", "from pkg import Engine", len("from pkg import E"))
    reported = found("goto", project / "app.py", line, column, "--follow-imports")
    assert (reported[0]["module_path"], reported[0]["full_name"]) == (
        "pkg/core.py", "pkg.core.Engine")
    assert reported[0]["line"] == position(PACKAGE["pkg/core.py"], "class Engine")[0]


def test_follow_imports_lands_on_an_imported_assignment(project):
    line, column = located(project, "app.py", "import build, SPEED", len("import build, S"))
    reported = found("goto", project / "app.py", line, column, "--follow-imports")
    assert (reported[0]["module_path"], reported[0]["description"]) == ("pkg/core.py", "SPEED = 88")


def test_follow_imports_falls_back_for_the_standard_library(project):
    line, column = located(project, "app.py", "import os", len("import o"))
    reported = found("goto", project / "app.py", line, column, "--follow-imports")
    assert (reported[0]["module_path"], reported[0]["description"]) == ("app.py", "import os")


def test_infer_crosses_files_through_a_package(project):
    line, column = located(project, "app.py", "motor = ", 1)
    assert typed(found("infer", project / "app.py", line, column)) == [("Engine", "instance")]


def test_infer_crosses_a_relative_import(project):
    line, column = located(project, "app.py", "grown = ", 1)
    reported = found("infer", project / "app.py", line, column)
    assert [(item["name"], item["module_path"]) for item in reported] == [
        ("Engine", "pkg/core.py")]


def test_module_paths_use_forward_slashes(project):
    line, column = located(project, "app.py", "made = ", 1)
    assert found("infer", project / "app.py", line, column)[0]["module_path"] == "pkg/core.py"


def test_a_relative_import_above_the_root_resolves_to_nothing(project):
    line, column = located(project, "pkg/deep/leaf.py", "import escapee", len("import e"))
    path = project / "pkg" / "deep" / "leaf.py"
    assert found("infer", path, line, column) == []
    assert found("goto", path, line, column, "--follow-imports")[0]["module_path"] == \
        "pkg/deep/leaf.py"


def test_without_a_project_root_a_relative_import_is_unresolvable(project):
    """The default root is the file's own directory, which ``..`` reaches above."""
    line, column = located(project, "pkg/deep/leaf.py", "from ..core import Engine",
                           len("from ..core import E"))
    assert definitions("infer", project / "pkg" / "deep" / "leaf.py", line, column) == []


def test_attribute_completion_reaches_into_another_module(project):
    path = project / "probe.py"
    path.write_text("from pkg.core import build\nmade = build()\nmade.\n")
    assert names(found("complete", path, 3, len("made."))) == ["power", "start", "__init__"]


def test_a_submodule_is_an_attribute_of_its_package(project):
    path = project / "probe.py"
    path.write_text("import pkg.core\npkg.core.\n")
    assert names(found("complete", path, 2, len("pkg.core."))) == ["build", "Engine", "SPEED"]


def test_a_namespace_package_needs_no_init(project):
    path = project / "probe.py"
    path.write_text("import space.free\nspace.free.\n")
    assert names(found("complete", path, 2, len("space.free."))) == ["NAME"]


def test_a_third_party_module_is_unresolvable(project):
    path = project / "probe.py"
    path.write_text("import pytest\npytest\n")
    assert found("infer", path, 2, 3) == []


def test_circular_imports_terminate(project):
    (project / "left.py").write_text("from right import gamma\n\ndelta = 1\n")
    (project / "right.py").write_text("from left import delta\n\ngamma = 2\n")
    reported = found("goto", project / "left.py", 1, len("from right import g"),
                     "--follow-imports")
    assert (reported[0]["module_path"], reported[0]["description"]) == ("right.py", "gamma = 2")


def test_a_star_import_obeys_dunder_all(project):
    path = project / "probe.py"
    path.write_text("from pkg import *\n\n")
    offered = names(found("complete", path, 2, 0))
    assert "Engine" in offered and "TITLE" in offered and "HIDDEN" not in offered


def test_follow_imports_crosses_a_star_import(project):
    path = project / "probe.py"
    path.write_text("from pkg import *\nTITLE\n")
    reported = found("goto", path, 2, 2, "--follow-imports")
    assert (reported[0]["module_path"], reported[0]["description"]) == (
        "pkg/__init__.py", 'TITLE = "pkg"')


# -- import context completion ---------------------------------------------

def offers(project: Path, text: str) -> list[str]:
    """The names completed at the end of ``text``, written as a probe file."""
    path = project / "probe.py"
    path.write_text(text + "\n")
    return names(found("complete", path, 1, len(text)))


def test_import_offers_top_level_modules(project):
    offered = offers(project, "import ")
    assert {"pkg", "space", "app", "os"} <= set(offered)


def test_import_filters_by_prefix(project):
    offered = offers(project, "import sp")
    assert "space" in offered and "pkg" not in offered


def test_a_dotted_import_offers_the_modules_of_a_package(project):
    assert offers(project, "import pkg.") == ["core", "deep"]


def test_from_import_offers_the_names_of_a_module(project):
    assert offers(project, "from pkg.core import ") == ["build", "Engine", "SPEED"]


def test_from_import_offers_the_names_of_a_submodule(project):
    # The names leaf imported are public names of leaf, so they re-export.
    assert offers(project, "from pkg.deep.leaf import ") == ["Engine", "escapee", "sprout"]


def test_from_import_obeys_dunder_all(project):
    assert set(offers(project, "from pkg import ")) == {"core", "deep", "Engine", "TITLE"}


def test_from_import_hides_private_names(project):
    (project / "quiet.py").write_text("_hidden = 1\nshown = 2\n")
    assert offers(project, "from quiet import ") == ["shown"]


def test_from_import_continues_after_a_comma(project):
    assert offers(project, "from pkg.core import build as b, S") == ["SPEED"]


def test_a_relative_import_offers_the_modules_beside_it(project):
    path = project / "pkg" / "probe.py"
    path.write_text("from . import \n")
    assert {"core", "deep", "Engine", "TITLE"} <= set(
        names(found("complete", path, 1, len("from . import "))))


def test_an_unknown_module_offers_nothing(project):
    assert offers(project, "from nowhere import ") == []


def test_import_completion_never_reads_the_line_as_an_attribute(project):
    assert "upper" not in offers(project, "import pkg.")


# -- signatures ------------------------------------------------------------

LIBRARY = '''\
"""A sample library."""


def greet(name: str, greeting: str = "hi", *rest: int, loud: bool = False, **extra) -> str:
    """Say hello."""
    return greeting


def plain(first, second=2):
    return first


class Calculator:
    """Adds things up."""

    def __init__(self, start: int = 0):
        self.total = start

    def add(self, value: int) -> int:
        return self.total + value
'''


@pytest.fixture
def library(tmp_path: Path) -> Path:
    (tmp_path / "lib.py").write_text(LIBRARY)
    return tmp_path


def calling(root: Path, body: str) -> list[dict]:
    """``signatures`` with the cursor at the ``|`` marker of ``body``."""
    text = body.replace("|", "")
    path = root / "call.py"
    path.write_text(text)
    line, column = position(body.replace("|", "\0"), "\0")
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), "signatures", str(path), str(line), str(column),
         "--project", str(root)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["signatures"]


def test_signature_renders_every_parameter_form(library):
    reported, = calling(library, "from lib import greet\ngreet(|")
    assert reported["params"] == ["name: str", "greeting: str='hi'", "*rest: int",
                                  "loud: bool=False", "**extra"]
    assert reported["name"] == "greet"
    assert reported["description"] == (
        "def greet(name: str, greeting: str='hi', *rest: int, loud: bool=False, "
        "**extra) -> str")
    assert reported["docstring"] == "Say hello."


def test_bare_parameters_and_defaults_render_without_annotations(library):
    reported, = calling(library, "from lib import plain\nplain(|")
    assert reported["params"] == ["first", "second=2"]
    assert reported["description"] == "def plain(first, second=2)"


def test_index_follows_the_positional_arguments(library):
    assert calling(library, "from lib import plain\nplain(|")[0]["index"] == 0
    assert calling(library, "from lib import plain\nplain(1, |")[0]["index"] == 1


def test_index_of_a_keyword_argument_is_its_parameter(library):
    reported, = calling(library, "from lib import greet\ngreet('x', loud=|True)")
    assert reported["index"] == 3


def test_extra_positional_arguments_land_in_star_args(library):
    reported, = calling(library, "from lib import greet\ngreet('a', 'b', 'c'|)")
    assert reported["index"] == 2  # *rest


def test_an_unknown_keyword_lands_in_star_star_kwargs(library):
    reported, = calling(library, "from lib import greet\ngreet(other=|1)")
    assert reported["index"] == 4  # **extra


def test_index_is_null_when_no_parameter_can_take_the_argument(library):
    assert calling(library, "from lib import plain\nplain(1, 2, 3|)")[0]["index"] is None
    assert calling(library, "from lib import plain\nplain(nope=|1)")[0]["index"] is None


def test_a_class_reports_its_constructor_under_its_own_name(library):
    reported, = calling(library, "from lib import Calculator\nCalculator(|")
    assert (reported["name"], reported["params"]) == ("Calculator", ["start: int=0"])
    assert reported["description"] == "def Calculator(start: int=0)"
    assert reported["docstring"] == "Adds things up."


def test_a_method_signature_leaves_out_self(library):
    reported, = calling(library, "from lib import Calculator\nCalculator().add(|")
    assert (reported["params"], reported["description"]) == (
        ["value: int"], "def add(value: int) -> int")


def test_no_signatures_outside_a_call(library):
    assert calling(library, "from lib import plain\nplain|") == []
    assert calling(library, "from lib import plain\nplain(1)|") == []


def test_a_parameter_list_is_not_a_call(library):
    assert calling(library, "def local(|") == []


def test_signatures_span_lines_and_ignore_commas_in_comments(library):
    reported, = calling(library, "from lib import plain\nplain(\n    1,\n    # one, two\n    |\n)")
    assert reported["index"] == 1


def test_overloads_are_all_reported(tmp_path):
    (tmp_path / "over.py").write_text(
        "from typing import overload\n\n\n"
        "@overload\ndef parse(value: int) -> int: ...\n"
        "@overload\ndef parse(value: str) -> str: ...\n"
        "def parse(value):\n    return value\n")
    reported = calling(tmp_path, "from over import parse\nparse(|")
    assert [entry["description"] for entry in reported] == [
        "def parse(value: int) -> int", "def parse(value: str) -> str", "def parse(value)"]


def test_a_builtin_reports_its_inspected_signature(tmp_path):
    reported, = calling(tmp_path, "sorted(|")
    assert reported["params"][0] == "iterable"


# -- references ------------------------------------------------------------

@pytest.fixture
def uses(tmp_path: Path) -> Path:
    (tmp_path / "core.py").write_text(
        "TOTAL = 1\n\n\ndef helper(value):\n    return value\n")
    (tmp_path / "app.py").write_text(
        "from core import helper\n\nresult = helper(2)\nprint(helper)\n\n\n"
        "def other():\n    helper = 5\n    return helper\n")
    (tmp_path / "rival.py").write_text("def helper():\n    return 0\n")
    return tmp_path


def referenced(root: Path, name: str, line: int, column: int, *flags: str) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), "references", str(root / name),
         str(line), str(column), "--project", str(root), *flags],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["references"]


def places(reported: list[dict]) -> list[tuple[str, int, int]]:
    return [(item["module_path"], item["line"], item["column"]) for item in reported]


def test_file_scope_reports_every_occurrence_of_the_name(uses):
    reported = referenced(uses, "app.py", 3, 9)
    assert places(reported) == [("app.py", 1, 17), ("app.py", 3, 9), ("app.py", 4, 6),
                                ("app.py", 8, 4), ("app.py", 9, 11)]
    assert [item["is_definition"] for item in reported] == [True, False, False, True, False]


def test_file_scope_is_the_default(uses):
    assert referenced(uses, "app.py", 3, 9) == referenced(uses, "app.py", 3, 9, "--scope", "file")


def test_project_scope_crosses_files_and_includes_the_definition(uses):
    reported = referenced(uses, "core.py", 4, 4, "--scope", "project")
    assert places(reported) == [("app.py", 1, 17), ("app.py", 3, 9), ("app.py", 4, 6),
                                ("core.py", 4, 4)]
    assert reported[-1]["is_definition"] is True


def test_project_scope_leaves_out_unrelated_names_of_the_same_spelling(uses):
    reported = referenced(uses, "app.py", 3, 9, "--scope", "project")
    assert "rival.py" not in {item["module_path"] for item in reported}
    assert ("app.py", 8, 4) not in places(reported)  # the local in other()


# -- search ----------------------------------------------------------------

def searched(root: Path, query: str) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), "search", query, "--project", str(root)],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["results"]


@pytest.fixture
def searchable(tmp_path: Path) -> Path:
    (tmp_path / "calc.py").write_text(
        "import os\n\nCALC_LIMIT = 10\n\n\n"
        "class Calculator:\n    step = 1\n\n"
        "    def recalculate(self):\n        inner_calc = 1\n        return inner_calc\n")
    (tmp_path / "other.py").write_text("calc = 1\n")
    return tmp_path


def test_search_matches_a_case_insensitive_substring(searchable):
    assert [item["name"] for item in searched(searchable, "calc")] == [
        "calc", "CALC_LIMIT", "Calculator", "recalculate"]


def test_search_ranks_exact_then_prefix_then_substring(searchable):
    ranked = [item["name"] for item in searched(searchable, "calculat")]
    assert ranked == ["Calculator", "recalculate"]


def test_search_reports_definition_fields_without_a_docstring(searchable):
    entry, = [item for item in searched(searchable, "Calculator") if item["name"] == "Calculator"]
    assert entry == {"name": "Calculator", "type": "class", "full_name": "calc.Calculator",
                     "module_path": "calc.py", "line": 6, "column": 6,
                     "description": "class Calculator"}


def test_search_skips_locals_and_imports(searchable):
    assert searched(searchable, "inner_calc") == []
    assert searched(searchable, "os") == []


def test_search_finds_class_level_assignments(searchable):
    assert [item["full_name"] for item in searched(searchable, "step")] == ["calc.Calculator.step"]


# -- names -----------------------------------------------------------------

def listed(path: Path, *flags: str) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), "names", str(path), *flags],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["names"]


@pytest.fixture
def listing(tmp_path: Path) -> Path:
    path = tmp_path / "m.py"
    path.write_text("import os\nfrom os import path\n\nTOP = 1\n\n\n"
                    "def outer(count):\n    local = 2\n\n"
                    "    def nested():\n        return local\n    return nested\n\n\n"
                    "class Holder:\n    field = 3\n")
    return path


def test_names_lists_module_level_bindings_including_imports(listing):
    assert [item["name"] for item in listed(listing)] == ["os", "path", "TOP", "outer", "Holder"]


def test_names_are_definitions_carrying_the_definition_fields(listing):
    entry = listed(listing)[2]
    assert entry["is_definition"] is True
    assert (entry["name"], entry["type"], entry["line"], entry["column"]) == (
        "TOP", "statement", 4, 0)


def test_all_scopes_adds_locals_parameters_and_nested_definitions(listing):
    everything = [item["name"] for item in listed(listing, "--all-scopes")]
    assert everything == ["os", "path", "TOP", "outer", "count", "local", "nested",
                          "Holder", "field"]


def test_names_are_ordered_by_position(listing):
    reported = listed(listing, "--all-scopes")
    assert reported == sorted(reported, key=lambda item: (item["line"], item["column"]))


# -- stub files ------------------------------------------------------------

VENDOR = '''\
def build(config):
    """Build it."""
    return config


class Widget:
    def __init__(self, size):
        self.size = size

    def resize(self, factor):
        return self
'''

VENDOR_STUB = '''\
class Widget:
    size: int
    def __init__(self, size: int) -> None: ...
    def resize(self, factor: float) -> Widget: ...

def build(config: str) -> Widget: ...
'''


@pytest.fixture
def stubbed(tmp_path: Path) -> Path:
    (tmp_path / "vendor.py").write_text(VENDOR)
    (tmp_path / "vendor.pyi").write_text(VENDOR_STUB)
    (tmp_path / "main.py").write_text("import vendor\n\nmade = vendor.build('x')\n")
    return tmp_path


def asked(root: Path, command: str, name: str, line: int, column: int, key: str) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), command, str(root / name),
         str(line), str(column), "--project", str(root)],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)[key]


def test_a_stub_supplies_the_parameter_annotations(stubbed):
    reported, = asked(stubbed, "signatures", "main.py", 3, 20, "signatures")
    assert reported["description"] == "def build(config: str) -> Widget"


def test_a_stub_supplies_the_return_type(stubbed):
    reported, = asked(stubbed, "infer", "main.py", 3, 1, "definitions")
    assert reported["description"] == "instance of Widget"


def test_a_stubbed_type_still_points_at_the_source(stubbed):
    reported, = asked(stubbed, "infer", "main.py", 3, 1, "definitions")
    assert (reported["module_path"], reported["line"]) == ("vendor.py", 6)


def test_goto_lands_in_the_source_and_not_in_the_stub(stubbed):
    reported, = asked(stubbed, "goto", "main.py", 3, 15, "definitions")
    assert (reported["module_path"], reported["line"]) == ("vendor.py", 1)
    assert reported["docstring"] == "Build it."


def test_a_stub_supplies_attribute_types_for_completion(stubbed):
    (stubbed / "probe.py").write_text("import vendor\n\nmade = vendor.build('x')\nmade.size.\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), "complete", str(stubbed / "probe.py"),
         "4", "10", "--project", str(stubbed)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    offered = [item["name"] for item in json.loads(result.stdout)["completions"]]
    assert "bit_length" in offered  # size is an int, which only the stub says


def test_a_stub_in_the_stubs_directory_is_found(tmp_path):
    (tmp_path / "service.py").write_text("def fetch(url):\n    return None\n")
    (tmp_path / "stubs").mkdir()
    (tmp_path / "stubs" / "service.pyi").write_text(
        "def fetch(url: str) -> bytes: ...\ndef extra(flag: bool) -> None: ...\n")
    reported, = calling(tmp_path, "import service\nservice.fetch(|")
    assert reported["description"] == "def fetch(url: str) -> bytes"


def test_a_definition_only_the_stub_has_is_reported_from_the_stub(tmp_path):
    (tmp_path / "service.py").write_text("def fetch(url):\n    return None\n")
    (tmp_path / "stubs").mkdir()
    (tmp_path / "stubs" / "service.pyi").write_text("def extra(flag: bool) -> None: ...\n")
    (tmp_path / "use.py").write_text("import service\n\nservice.extra(True)\n")
    reported, = asked(tmp_path, "goto", "use.py", 3, 10, "definitions")
    assert reported["module_path"] == "stubs/service.pyi"


# -- parameter types inferred from call sites ------------------------------

def test_an_unannotated_parameter_takes_the_type_its_callers_pass(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def twice(value):\n    return value\n\n\ntwice('hello')\n")
    reported, = definitions("infer", path, 2, 11)
    assert reported["description"] == "instance of str"


def test_a_method_parameter_takes_the_type_its_callers_pass(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("class Box:\n    def put(self, item):\n        return item\n\n\n"
                    "Box().put(3)\n")
    reported, = definitions("infer", path, 3, 15)
    assert reported["description"] == "instance of int"


def test_call_sites_in_other_files_are_not_searched(tmp_path):
    (tmp_path / "caller.py").write_text("from lonely import only_here\n\nonly_here(1.5)\n")
    path = tmp_path / "lonely.py"
    path.write_text("def only_here(thing):\n    return thing\n")
    assert definitions("infer", path, 2, 12) == []


def test_an_inferred_parameter_resolves_the_call_it_is_used_for(tmp_path):
    reported, = calling(tmp_path, "def target(alpha: int) -> bool:\n    return True\n\n\n"
                                  "def run(action):\n    action(|\n\n\nrun(target)\n")
    assert reported["description"] == "def target(alpha: int) -> bool"


def test_an_annotation_still_wins_over_the_call_sites(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def twice(value: int):\n    return value\n\n\ntwice('hello')\n")
    reported, = definitions("infer", path, 2, 11)
    assert reported["description"] == "instance of int"


# -- refactoring -----------------------------------------------------------

def refactor(root: Path, command: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "sith.py"), command, *arguments, "--project", str(root)],
        capture_output=True, text=True, cwd=ROOT)


def changed(root: Path, command: str, *arguments: str) -> dict:
    result = refactor(root, command, *arguments)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def refused(root: Path, command: str, *arguments: str) -> str:
    result = refactor(root, command, *arguments)
    assert result.returncode == 1 and not result.stdout
    return result.stderr


@pytest.fixture
def renamable(tmp_path: Path) -> Path:
    (tmp_path / "core.py").write_text(
        "TOTAL = 1\n\n\ndef helper(value):\n    return value\n")
    (tmp_path / "app.py").write_text(
        "from core import helper\n\nresult = helper(2)\n\n\ndef other():\n"
        "    helper = 5\n    return helper\n")
    (tmp_path / "rival.py").write_text("def helper():\n    return 0\n")
    return tmp_path


def test_rename_reaches_every_file_that_uses_the_name(renamable):
    reported = changed(renamable, "rename", str(renamable / "core.py"), "4", "4",
                       "--new-name", "assist")
    assert reported["changed_files"] == {
        "app.py": "from core import assist\n\nresult = assist(2)\n\n\ndef other():\n"
                  "    helper = 5\n    return helper\n",
        "core.py": "TOTAL = 1\n\n\ndef assist(value):\n    return value\n"}
    assert reported["renames"] == {}


def test_rename_leaves_out_files_it_did_not_change(renamable):
    reported = changed(renamable, "rename", str(renamable / "core.py"), "4", "4",
                       "--new-name", "assist")
    assert "rival.py" not in reported["changed_files"]


def test_rename_a_local_stays_in_its_own_scope(renamable):
    reported = changed(renamable, "rename", str(renamable / "app.py"), "7", "4",
                       "--new-name", "count")
    assert reported["changed_files"] == {
        "app.py": "from core import helper\n\nresult = helper(2)\n\n\ndef other():\n"
                  "    count = 5\n    return count\n"}


def test_rename_writes_a_unified_diff(renamable):
    result = refactor(renamable, "rename", str(renamable / "core.py"), "1", "0",
                      "--new-name", "COUNT", "--diff")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("--- a/core.py\n+++ b/core.py\n@@ -1,4 +1,4 @@\n"
                             "-TOTAL = 1\n+COUNT = 1\n \n \n def helper(value):\n")


def test_rename_refuses_a_name_that_is_not_an_identifier(renamable):
    assert "identifier" in refused(renamable, "rename", str(renamable / "core.py"), "4", "4",
                                   "--new-name", "not a name")


def test_rename_refuses_a_keyword(renamable):
    assert "identifier" in refused(renamable, "rename", str(renamable / "core.py"), "4", "4",
                                   "--new-name", "class")


def test_rename_refuses_a_cursor_that_is_not_on_a_name(renamable):
    assert refused(renamable, "rename", str(renamable / "core.py"), "2", "0", "--new-name", "x")


def test_rename_refuses_a_name_already_in_scope(renamable):
    message = refused(renamable, "rename", str(renamable / "core.py"), "4", "4",
                      "--new-name", "TOTAL")
    assert "already defined" in message and "core.py:1" in message


@pytest.fixture
def packaged(tmp_path: Path) -> Path:
    (tmp_path / "helpers.py").write_text("def shout(text):\n    return text.upper()\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from .core import run\n")
    (tmp_path / "pkg" / "core.py").write_text("def run():\n    return 1\n")
    (tmp_path / "main.py").write_text(
        "import helpers\nfrom helpers import shout\nfrom pkg.core import run\n"
        "import pkg.core\n\nprint(helpers.shout('a'), shout('b'), run(), pkg.core.run())\n")
    return tmp_path


def test_renaming_a_module_moves_its_file_and_its_imports(packaged):
    reported = changed(packaged, "rename", str(packaged / "main.py"), "1", "8",
                       "--new-name", "speech")
    assert reported["renames"] == {"helpers.py": "speech.py"}
    assert reported["changed_files"]["main.py"].startswith(
        "import speech\nfrom speech import shout\n")
    assert "speech.shout('a')" in reported["changed_files"]["main.py"]


def test_renaming_a_module_leaves_its_unchanged_content_alone(packaged):
    reported = changed(packaged, "rename", str(packaged / "main.py"), "1", "8",
                       "--new-name", "speech")
    assert "speech.py" not in reported["changed_files"]


def test_renaming_a_package_moves_the_directory(packaged):
    reported = changed(packaged, "rename", str(packaged / "main.py"), "3", "5",
                       "--new-name", "bundle")
    assert reported["renames"] == {"pkg": "bundle"}
    assert "from bundle.core import run\nimport bundle.core\n" in \
        reported["changed_files"]["main.py"]


def test_renaming_a_submodule_follows_the_cursor_to_the_component_it_is_on(packaged):
    reported = changed(packaged, "rename", str(packaged / "main.py"), "3", "9",
                       "--new-name", "engine")
    assert reported["renames"] == {"pkg/core.py": "pkg/engine.py"}
    assert "from pkg.engine import run" in reported["changed_files"]["main.py"]
    assert reported["changed_files"]["pkg/__init__.py"] == "from .engine import run\n"


def test_renaming_a_module_refuses_a_name_already_taken(packaged):
    assert "already exists" in refused(packaged, "rename", str(packaged / "main.py"), "1", "8",
                                       "--new-name", "pkg")


def test_a_module_outside_the_project_cannot_be_renamed(packaged):
    (packaged / "stdlib.py").write_text("import os\n\nprint(os.sep)\n")
    assert "not a module of the project" in refused(
        packaged, "rename", str(packaged / "stdlib.py"), "1", "8", "--new-name", "oz")


@pytest.fixture
def inlinable(tmp_path: Path) -> Path:
    path = tmp_path / "m.py"
    path.write_text("def compute(a, b):\n    total = a + b\n    doubled = total * 2\n"
                    "    return doubled + total\n\n\nunused = 5\n\n\ndef helper():\n"
                    "    return 1\n")
    return tmp_path


def test_inline_substitutes_the_value_and_drops_the_assignment(inlinable):
    reported = changed(inlinable, "inline", str(inlinable / "m.py"), "2", "4")
    assert reported["changed_files"]["m.py"] == (
        "def compute(a, b):\n    doubled = (a + b) * 2\n    return doubled + (a + b)\n"
        "\n\nunused = 5\n\n\ndef helper():\n    return 1\n")


def test_inline_leaves_out_brackets_a_statement_does_not_need(tmp_path):
    (tmp_path / "m.py").write_text("limit = 10\n\nprint(limit)\n")
    reported = changed(tmp_path, "inline", str(tmp_path / "m.py"), "1", "0")
    assert reported["changed_files"]["m.py"] == "\nprint(10)\n"


def test_inline_brackets_a_bare_tuple(tmp_path):
    (tmp_path / "m.py").write_text("pair = 1, 2\n\nprint(pair)\n")
    reported = changed(tmp_path, "inline", str(tmp_path / "m.py"), "1", "0")
    assert reported["changed_files"]["m.py"] == "\nprint((1, 2))\n"


def test_inline_refuses_a_function(inlinable):
    assert refused(inlinable, "inline", str(inlinable / "m.py"), "10", "4") == \
        "cannot inline a function/class definition\n"


def test_inline_refuses_a_name_nothing_reads(inlinable):
    assert refused(inlinable, "inline", str(inlinable / "m.py"), "7", "0") == \
        "name has no references to inline\n"


def test_inline_writes_a_unified_diff(inlinable):
    result = refactor(inlinable, "inline", str(inlinable / "m.py"), "2", "4", "--diff")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("--- a/m.py\n+++ b/m.py\n@@ ")
    assert "-    total = a + b\n" in result.stdout


@pytest.fixture
def selectable(tmp_path: Path) -> Path:
    path = tmp_path / "s.py"
    path.write_text("def report(items):\n    prefix = 'n='\n    total = 0\n"
                    "    for item in items:\n        total += item\n"
                    "    average = total / len(items)\n"
                    "    return prefix + str(total) + str(average)\n")
    return tmp_path


def test_extract_variable_names_the_expression_above_its_statement(selectable):
    reported = changed(selectable, "extract-variable", str(selectable / "s.py"), "6", "14",
                       "--until", "6:32", "--name", "count")
    assert reported["changed_files"]["s.py"].splitlines()[5:7] == [
        "    count = total / len(items)", "    average = count"]


def test_extract_variable_refuses_half_an_expression(selectable):
    assert refused(selectable, "extract-variable", str(selectable / "s.py"), "6", "14",
                   "--until", "6:22", "--name", "count") == \
        "selection is not a complete expression\n"


def test_extract_variable_refuses_a_name_that_is_not_an_identifier(selectable):
    assert "identifier" in refused(selectable, "extract-variable", str(selectable / "s.py"),
                                   "6", "14", "--until", "6:32", "--name", "1count")


def test_extract_function_passes_in_what_it_reads_and_returns_what_is_read_after(selectable):
    reported = changed(selectable, "extract-function", str(selectable / "s.py"), "3", "0",
                       "--until", "6:32", "--name", "summarise")
    assert reported["changed_files"]["s.py"] == (
        "def summarise(items):\n    total = 0\n    for item in items:\n"
        "        total += item\n    average = total / len(items)\n"
        "    return total, average\n\n\ndef report(items):\n    prefix = 'n='\n"
        "    total, average = summarise(items)\n"
        "    return prefix + str(total) + str(average)\n")


def test_extract_function_returns_a_single_value_bare(selectable):
    reported = changed(selectable, "extract-function", str(selectable / "s.py"), "4", "0",
                       "--until", "5:21", "--name", "accumulate")
    assert "    return total\n" in reported["changed_files"]["s.py"]
    assert "    total = accumulate(items, total)\n" in reported["changed_files"]["s.py"]


def test_extract_function_sits_where_the_method_it_came_from_sits(tmp_path):
    (tmp_path / "c.py").write_text(
        "class Report:\n    def render(self, rows):\n        header = 'id'\n"
        "        body = ','.join(rows)\n        return header + body\n")
    reported = changed(tmp_path, "extract-function", str(tmp_path / "c.py"), "4", "0",
                       "--until", "4:29", "--name", "compose")
    assert reported["changed_files"]["c.py"] == (
        "class Report:\n    def compose(rows):\n        body = ','.join(rows)\n"
        "        return body\n\n    def render(self, rows):\n        header = 'id'\n"
        "        body = compose(rows)\n        return header + body\n")


def test_extract_function_at_module_level_stands_where_the_statements_did(tmp_path):
    (tmp_path / "g.py").write_text(
        "LIMIT = 4\ndata = [1, 2]\n\nscaled = [value * LIMIT for value in data]\n\n"
        "print(scaled)\n")
    reported = changed(tmp_path, "extract-function", str(tmp_path / "g.py"), "4", "0",
                       "--until", "4:42", "--name", "prepare")
    assert reported["changed_files"]["g.py"] == (
        "LIMIT = 4\ndata = [1, 2]\n\ndef prepare(LIMIT, data):\n"
        "    scaled = [value * LIMIT for value in data]\n    return scaled\n\n\n"
        "scaled = prepare(LIMIT, data)\n\nprint(scaled)\n")


def test_extract_function_refuses_half_a_statement(selectable):
    assert refused(selectable, "extract-function", str(selectable / "s.py"), "4", "0",
                   "--until", "4:12", "--name", "part")


# -- syntax errors ---------------------------------------------------------

def reported_errors(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "sith.py"), "errors", str(path)],
                          capture_output=True, text=True, cwd=ROOT)


def test_a_clean_file_reports_no_errors(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n\n\ndef f():\n    return x\n")
    result = reported_errors(tmp_path / "m.py")
    assert result.returncode == 0 and json.loads(result.stdout) == {"errors": []}


def test_a_broken_line_is_reported_with_its_region(tmp_path):
    (tmp_path / "m.py").write_text("def broken(:\n    return 1\n")
    result = reported_errors(tmp_path / "m.py")
    assert result.returncode == 0, result.stderr
    error, = json.loads(result.stdout)["errors"]
    assert (error["line"], error["until_line"]) == (1, 1)
    assert error["column"] == 11 and error["until_column"] == 12
    assert error["message"]


def test_every_broken_line_is_reported(tmp_path):
    (tmp_path / "m.py").write_text("x = (1\ny = 2\nz ==== 3\n")
    found = json.loads(reported_errors(tmp_path / "m.py").stdout)["errors"]
    assert [error["line"] for error in found] == [1, 3]


def test_errors_still_fails_on_a_missing_file(tmp_path):
    result = reported_errors(tmp_path / "absent.py")
    assert result.returncode == 1 and result.stderr.strip()


def test_renaming_an_imported_name_is_not_a_module_rename(packaged):
    reported = changed(packaged, "rename", str(packaged / "main.py"), "2", "20",
                       "--new-name", "yell")
    assert reported["renames"] == {}
    assert reported["changed_files"]["helpers.py"].startswith("def yell(text):")


def test_renaming_an_imported_module_is_a_module_rename(packaged):
    reported = changed(packaged, "rename", str(packaged / "main.py"), "3", "9",
                       "--new-name", "engine")
    assert reported["renames"] == {"pkg/core.py": "pkg/engine.py"}


# -- interpreter mode ------------------------------------------------------

NAMESPACES = [
    {"frame": {"type": "DataFrame", "value": "<DataFrame 3x2>", "module": "pandas",
               "attributes": ["head", "shape"]},
     "total": {"type": "int", "value": "42"},
     "load": {"type": "function", "value": "<function load>", "module": "tools",
              "name": "loader"}},
    {"total": {"type": "str", "value": "shadowed"},
     "extra": {"type": "list", "value": "[1, 2]"}},
]


def sith(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "sith.py"), *arguments],
                          capture_output=True, text=True, cwd=str(cwd or ROOT))


def answered(*arguments: str, cwd: Path | None = None) -> dict:
    result = sith(*arguments, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def session(tmp_path: Path) -> Path:
    """A namespaces file describing what a REPL session already holds."""
    path = tmp_path / "namespaces.json"
    path.write_text(json.dumps(NAMESPACES))
    return path


def live(session: Path, command: str, path: Path, line: int, column: int) -> dict:
    return answered(command, str(path), str(line), str(column),
                    "--interpreter", "--namespaces", str(session))


def test_namespace_names_are_completed_as_runtime_values(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("fra\n")
    completion, = live(session, "complete", path, 1, 3)["completions"]
    assert completion == {"name": "frame", "complete": "me", "type": "DataFrame",
                          "description": "DataFrame (runtime)"}


def test_namespaces_and_static_names_are_merged(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("extract = 1\nex\n")
    offered = names(live(session, "complete", path, 2, 2)["completions"])
    assert {"extra", "extract"} <= set(offered)


def test_static_analysis_wins_over_a_namespace_of_the_same_name(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("total = 'written down'\ntotal\n")
    completion = entry(live(session, "complete", path, 2, 0)["completions"], "total")
    assert completion["description"] == "instance of str"
    assert [found["description"] for found in live(session, "infer", path, 2, 1)["definitions"]] \
        == ["instance of str"]


def test_the_first_namespace_holding_a_name_wins(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("total\n")
    found, = live(session, "infer", path, 1, 2)["definitions"]
    assert (found["type"], found["description"]) == ("int", "int (runtime)")


def test_a_runtime_value_is_inferred_with_every_field_it_declares(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("frame\n")
    assert live(session, "infer", path, 1, 2)["definitions"] == [{
        "name": "frame", "type": "DataFrame", "full_name": "pandas.frame",
        "module_path": "", "line": 0, "column": 0, "description": "DataFrame (runtime)",
        "docstring": "<DataFrame 3x2>"}]


def test_goto_falls_back_to_the_namespace_and_reports_the_original_name(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("load\n")
    found, = live(session, "goto", path, 1, 1)["definitions"]
    assert (found["name"], found["full_name"]) == ("loader", "tools.loader")
    assert found["description"] == "function (runtime)"


def test_the_attributes_of_a_runtime_value_are_completed(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("frame.\n")
    offered = live(session, "complete", path, 1, 6)["completions"]
    assert names(offered) == ["head", "shape"]
    assert offered[0]["description"] == "instance (runtime)"


def test_a_runtime_callable_reports_the_signature_it_can(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("load(\n")
    signature, = live(session, "signatures", path, 1, 5)["signatures"]
    assert (signature["name"], signature["params"], signature["index"]) == ("loader", [], None)


def test_interpreter_mode_without_namespaces_changes_nothing(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("frame\n")
    assert answered("infer", str(path), "1", "2", "--interpreter") == {"definitions": []}


def test_namespaces_without_interpreter_mode_fails(session, tmp_path):
    path = tmp_path / "m.py"
    path.write_text("frame\n")
    result = sith("infer", str(path), "1", "2", "--namespaces", str(session))
    assert result.returncode == 1 and result.stderr.strip()


def test_a_namespaces_file_that_is_not_a_list_of_objects_fails(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("frame\n")
    broken = tmp_path / "broken.json"
    broken.write_text('{"frame": {"type": "int"}}')
    assert sith("infer", str(path), "1", "2", "--interpreter",
                "--namespaces", str(broken)).returncode == 1


# -- scope context ---------------------------------------------------------

NESTED = '''\
import os


class Shop:
    """A shop."""

    def sell(self, item):
        def wrap(box):
            return box

        return wrap(item)


TOTAL = 1
'''


@pytest.fixture
def nested(tmp_path: Path) -> Path:
    path = tmp_path / "n.py"
    path.write_text(NESTED)
    return path


def test_context_is_ordered_from_the_outermost_scope_inwards(nested):
    assert answered("context", str(nested), "9", "19")["context"] == [
        {"name": "Shop", "type": "class", "line": 4, "column": 6},
        {"name": "sell", "type": "function", "line": 7, "column": 8},
        {"name": "wrap", "type": "function", "line": 8, "column": 12}]


def test_context_at_module_level_is_empty(nested):
    assert answered("context", str(nested), "14", "0")["context"] == []


def test_context_includes_the_scope_the_cursor_defines(nested):
    assert [found["name"] for found in answered("context", str(nested), "7", "8")["context"]] \
        == ["Shop", "sell"]


def test_context_still_rejects_a_cursor_outside_the_file(nested):
    assert sith("context", str(nested), "99", "0").returncode == 1


# -- settings --------------------------------------------------------------

def test_add_bracket_opens_the_call_a_callable_needs(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("class Box:\n    pass\n\n\ndef ship():\n    pass\n\n\nb\n")
    offered = answered("complete", str(path), "9", "1", "--setting", "add_bracket=true")
    assert [found["complete"] for found in offered["completions"] if found["name"] == "Box"] \
        == ["ox("]
    assert entry(offered["completions"], "bytes")["complete"] == "ytes("


def test_case_insensitive_matching_can_be_turned_off(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("TOTAL = 1\ntot\n")
    assert answered("complete", str(path), "2", "3")["completions"]
    assert answered("complete", str(path), "2", "3",
                    "--setting", "case_insensitive=false")["completions"] == []


def test_dynamic_params_can_be_turned_off(tmp_path):
    path = tmp_path / "m.py"
    path.write_text("def twice(value):\n    return value\n\n\ntwice('hello')\n")
    assert answered("infer", str(path), "2", "11")["definitions"]
    assert answered("infer", str(path), "2", "11",
                    "--setting", "dynamic_params=false")["definitions"] == []


@pytest.mark.parametrize("setting", ["nonsense=true", "add_bracket=maybe", "add_bracket"])
def test_an_unusable_setting_fails(tmp_path, setting):
    path = tmp_path / "m.py"
    path.write_text("x = 1\n")
    result = sith("complete", str(path), "1", "0", "--setting", setting)
    assert result.returncode == 1 and result.stderr.strip()


# -- environments ----------------------------------------------------------

def fake_virtualenv(directory: Path) -> Path:
    """A directory that a real interpreter reads as its own virtualenv."""
    interpreter = Path(sys.executable).resolve()
    (directory / "bin").mkdir(parents=True)
    (directory / "bin" / "python").symlink_to(interpreter)
    (directory / "pyvenv.cfg").write_text(f"home = {interpreter.parent}\n")
    return directory


def test_env_list_describes_each_installation_newest_first():
    found = answered("env", "list")["environments"]
    assert found and all(set(environment) == {"executable", "version", "is_virtualenv"}
                         for environment in found)
    versions = [tuple(int(part) for part in environment["version"].split("."))
                for environment in found]
    assert versions == sorted(versions, reverse=True)
    assert len(found) == len({environment["executable"] for environment in found})


def test_env_info_adds_the_prefix_and_search_path_of_an_environment():
    found = answered("env", "info", sys.executable)
    assert found["executable"] == sys.executable
    assert found["prefix"] and isinstance(found["sys_path"], list)


def test_env_info_falls_back_to_the_system_interpreter():
    assert answered("env", "info")["version"].startswith("3.")


def test_env_info_fails_on_something_that_is_not_python(tmp_path):
    impostor = tmp_path / "python"
    impostor.write_text("#!/bin/sh\necho not python\n")
    impostor.chmod(0o755)
    assert sith("env", "info", str(impostor)).returncode == 1


def test_find_virtualenvs_reports_only_virtualenvs(tmp_path):
    fake_virtualenv(tmp_path / "envs" / "work")
    (tmp_path / "envs" / "empty").mkdir()
    found = answered("env", "find-virtualenvs", "--path", str(tmp_path / "envs"))
    reported = [environment["executable"] for environment in found["environments"]]
    assert str(tmp_path / "envs" / "work" / "bin" / "python") in reported
    assert not any(str(tmp_path / "envs" / "empty") in executable for executable in reported)
    assert all(environment["is_virtualenv"] for environment in found["environments"])


def test_find_virtualenvs_looks_beside_the_working_directory(tmp_path):
    fake_virtualenv(tmp_path / ".venv")
    found = answered("env", "find-virtualenvs", cwd=tmp_path)["environments"]
    assert str(tmp_path / ".venv" / "bin" / "python") in \
        [environment["executable"] for environment in found]


# -- project configuration -------------------------------------------------

def configuration(root: Path) -> dict:
    return json.loads((root / ".sith" / "project.json").read_text())


def test_project_init_writes_the_defaults(tmp_path):
    reported = answered("project", "init", str(tmp_path))
    assert configuration(tmp_path) == {"environment_path": "", "sys_path": [],
                                       "added_sys_path": [], "smart_sys_path": True}
    assert reported["path"] == str(tmp_path / ".sith" / "project.json")


def test_project_init_defaults_to_the_working_directory(tmp_path):
    answered("project", "init", cwd=tmp_path)
    assert configuration(tmp_path)["smart_sys_path"] is True


def test_project_init_merges_into_what_is_already_configured(tmp_path):
    answered("project", "init", str(tmp_path), "--environment", "/usr/bin/python3")
    answered("project", "init", str(tmp_path), "--added-sys-path", "lib,extra")
    assert configuration(tmp_path) == {"environment_path": "/usr/bin/python3", "sys_path": [],
                                       "added_sys_path": ["lib", "extra"],
                                       "smart_sys_path": True}


@pytest.fixture
def layered(tmp_path: Path) -> Path:
    """A project whose modules only import each other through configured paths."""
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "helper.py").write_text("def shout(text):\n    return text\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("TOTAL = 1\n")
    (tmp_path / "main.py").write_text("import helper\nimport core\n\nhelper.shout('x')\n")
    return tmp_path


def imported(root: Path, line: int, column: int, *flags: str) -> list[str]:
    """Where the import on that line leads; the statement itself when nowhere."""
    found = answered("goto", str(root / "main.py"), str(line), str(column),
                     "--project", str(root), "--follow-imports", *flags)["definitions"]
    return [definition["module_path"] for definition in found]


def test_a_package_directory_is_searched_when_sys_path_is_smart(layered):
    assert imported(layered, 2, 7) == ["pkg/core.py"]


def test_smart_sys_path_can_be_turned_off(layered):
    assert imported(layered, 2, 7, "--setting", "smart_sys_path=false") == ["main.py"]


def test_added_sys_path_makes_a_module_importable(layered):
    assert imported(layered, 1, 7) == ["main.py"]
    answered("project", "init", str(layered), "--added-sys-path", "lib")
    assert imported(layered, 1, 7) == ["lib/helper.py"]


def test_sys_path_replaces_what_would_be_detected(layered):
    answered("project", "init", str(layered), "--sys-path", "lib")
    assert imported(layered, 1, 7) == ["lib/helper.py"]
    assert imported(layered, 2, 7) == ["main.py"]


def test_a_setting_overrides_what_the_project_configures(layered):
    answered("project", "init", str(layered), "--setting", "smart_sys_path=false")
    assert configuration(layered)["smart_sys_path"] is False
    assert imported(layered, 2, 7) == ["main.py"]
    assert imported(layered, 2, 7, "--setting", "smart_sys_path=true") == ["pkg/core.py"]
