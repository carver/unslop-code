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
