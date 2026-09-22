"""End-to-end checks of import resolution across the files of a project."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

APP = """from pkg import Dog
from pkg.models import make_dog
from helpers import shout
import os
from flask import Flask

mine = Dog("fido")
noise = mine.bark()
made = make_dog()
loud = shout("hey")
"""

HELPERS = '''"""Helpers."""

__all__ = ["shout", "_kept"]


def shout(text):
    return text.upper()


def hidden():
    return 1


def _kept():
    return 2
'''

MODELS = '''"""Models."""


class Dog:
    """A dog."""

    def __init__(self, name):
        self.name = name

    def bark(self):
        return "woof"


def make_dog():
    return Dog("rex")
'''

PACKAGE = '''"""The pkg package."""

from .models import Dog

LABEL = "pkg"
'''

SIBLING = """from .models import Dog
from .deep.inner import deepest

pup = Dog("spot")
count = deepest()
"""

BROKEN = """def oops(:
    pass


def fine():
    return 1
"""


def run(command, path, line, column, *flags):
    """Invoke the CLI and return (exit code, parsed payload, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", command, str(path), str(line), str(column), *flags],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, payload, result.stderr


class ProjectTest(unittest.TestCase):
    """A package layout shared by every test, written once to a temporary root."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls._directory.name)
        cls.app = cls.write("app.py", APP)
        cls.write("helpers.py", HELPERS)
        cls.write("pkg/__init__.py", PACKAGE)
        cls.write("pkg/models.py", MODELS)
        cls.write("pkg/sibling.py", SIBLING)
        cls.write("pkg/deep/__init__.py", '"""Deep."""\n')
        cls.write("pkg/deep/inner.py", "def deepest():\n    return 42\n")
        cls.write("ns/tools.py", 'def gadget():\n    return "widget"\n')
        cls.write("broken.py", BROKEN)
        cls.write("cycle_a.py", "from cycle_b import later\n\nALPHA = 1\n\n\ndef make():\n"
                                "    return later()\n")
        cls.write("cycle_b.py", "from cycle_a import ALPHA\n\n\ndef later():\n    return ALPHA\n")

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    @classmethod
    def write(cls, name, text):
        path = cls.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def definitions(self, command, path, line, column, *flags):
        code, payload, error = run(command, path, line, column, *flags)
        self.assertEqual(code, 0, error)
        return payload["definitions"]

    def summary(self, command, path, line, column, *flags):
        """The (name, type, full_name, module_path, line) of each definition."""
        return [
            (item["name"], item["type"], item["full_name"], item["module_path"], item["line"])
            for item in self.definitions(command, path, line, column, *flags)
        ]

    def names(self, path, line, column, *flags):
        code, payload, error = run("complete", path, line, column, *flags)
        self.assertEqual(code, 0, error)
        return [item["name"] for item in payload["completions"]]

    # Project root --------------------------------------------------------

    def test_the_project_root_defaults_to_the_directory_of_the_file(self):
        self.assertEqual(
            self.summary("infer", self.root / "pkg/sibling.py", 4, 6),
            [("Dog", "class", "models.Dog", "models.py", 4)],
        )

    def test_the_project_flag_qualifies_names_from_the_given_root(self):
        self.assertEqual(
            self.summary("infer", self.root / "pkg/sibling.py", 4, 6, "--project", str(self.root)),
            [("Dog", "class", "pkg.models.Dog", "pkg/models.py", 4)],
        )

    def test_a_project_root_that_is_not_a_directory_fails(self):
        code, _, error = run("infer", self.app, 7, 7, "--project", str(self.root / "absent"))
        self.assertEqual(code, 1)
        self.assertIn("not a project directory", error)

    # goto ----------------------------------------------------------------

    def test_goto_reports_the_import_statement_by_default(self):
        self.assertEqual(
            self.summary("goto", self.app, 7, 7),
            [("Dog", "class", "app.Dog", "app.py", 1)],
        )

    def test_following_imports_walks_the_chain_to_the_definition(self):
        self.assertEqual(
            self.summary("goto", self.app, 7, 7, "--follow-imports"),
            [("Dog", "class", "pkg.models.Dog", "pkg/models.py", 4)],
        )

    def test_following_imports_reaches_a_function_in_another_module(self):
        self.assertEqual(
            self.summary("goto", self.app, 9, 7, "--follow-imports"),
            [("make_dog", "function", "pkg.models.make_dog", "pkg/models.py", 14)],
        )

    def test_following_imports_works_from_the_import_statement_itself(self):
        self.assertEqual(
            self.summary("goto", self.app, 1, 16, "--follow-imports"),
            [("Dog", "class", "pkg.models.Dog", "pkg/models.py", 4)],
        )

    def test_following_imports_leaves_other_bindings_alone(self):
        self.assertEqual(
            self.summary("goto", self.app, 7, 0, "--follow-imports"),
            [("mine", "statement", "app.mine", "app.py", 7)],
        )

    def test_a_module_outside_the_project_falls_back_to_the_import(self):
        for line, column in [(4, 7), (5, 18)]:
            self.assertEqual(
                [item["line"] for item in
                 self.definitions("goto", self.app, line, column, "--follow-imports")],
                [line],
            )

    # infer ---------------------------------------------------------------

    def test_infer_follows_imports_across_files(self):
        self.assertEqual(
            self.summary("infer", self.app, 9, 7),
            [("make_dog", "function", "pkg.models.make_dog", "pkg/models.py", 14)],
        )

    def test_infer_reads_return_types_out_of_another_module(self):
        self.assertEqual(
            self.summary("infer", self.app, 9, 0),
            [("Dog", "instance", "pkg.models.Dog", "pkg/models.py", 4)],
        )

    def test_infer_reaches_methods_of_an_imported_class(self):
        self.assertEqual(
            self.summary("infer", self.app, 8, 0),
            [("str", "instance", "builtins.str", "", 0)],
        )

    def test_an_unknown_module_infers_to_nothing(self):
        self.assertEqual(self.definitions("infer", self.app, 5, 18), [])

    # Relative imports ----------------------------------------------------

    def test_relative_imports_resolve_inside_the_package(self):
        path = self.root / "pkg/sibling.py"
        self.assertEqual(
            self.summary("goto", path, 1, 20, "--follow-imports", "--project", str(self.root)),
            [("Dog", "class", "pkg.models.Dog", "pkg/models.py", 4)],
        )
        self.assertEqual(
            self.summary("infer", path, 5, 0, "--project", str(self.root)),
            [("int", "instance", "builtins.int", "", 0)],
        )

    def test_relative_imports_above_the_project_root_resolve_to_nothing(self):
        path = self.write("escape.py", "from ..other import thing\n\nvalue = thing()\n")
        self.assertEqual(self.definitions("infer", path, 3, 8), [])
        self.assertEqual(
            self.summary("goto", path, 3, 8, "--follow-imports"),
            [("thing", "statement", "escape.thing", "escape.py", 1)],
        )

    # Star imports --------------------------------------------------------

    def test_star_imports_bring_in_exactly_the_names_of_dunder_all(self):
        path = self.write("stars.py", "from helpers import *\n\n")
        visible = self.names(path, 2, 0)
        self.assertIn("shout", visible)
        self.assertIn("_kept", visible)
        self.assertNotIn("hidden", visible)

    def test_star_imports_without_dunder_all_bring_in_public_names(self):
        path = self.write("starred_public.py", "from pkg.deep.inner import *\n\n")
        self.assertIn("deepest", self.names(path, 2, 0))

    def test_a_star_imported_name_resolves_to_its_own_module(self):
        path = self.write("starred_goto.py", "from helpers import *\n\nshout('x')\n")
        self.assertEqual(
            self.summary("goto", path, 3, 0),
            [("shout", "function", "helpers.shout", "helpers.py", 6)],
        )

    # Import completion ---------------------------------------------------

    def test_import_completion_offers_top_level_modules_and_packages(self):
        path = self.write("typing_import.py", "import ")
        offered = self.names(path, 1, 7)
        self.assertLessEqual({"app", "helpers", "pkg", "ns", "os"}, set(offered))

    def test_import_completion_matches_the_typed_prefix(self):
        path = self.write("typing_prefix.py", "import help")
        self.assertEqual(self.names(path, 1, 11), ["helpers"])

    def test_import_completion_offers_the_names_inside_a_module(self):
        path = self.write("typing_from.py", "from pkg.models import ")
        self.assertEqual(self.names(path, 1, 23), ["Dog", "make_dog"])

    def test_import_completion_offers_the_names_inside_a_package(self):
        path = self.write("typing_pkg.py", "from pkg import ")
        self.assertEqual(self.names(path, 1, 16), ["deep", "Dog", "LABEL", "models", "sibling"])

    def test_import_completion_offers_the_names_inside_a_submodule(self):
        path = self.write("typing_deep.py", "from pkg.deep.inner import ")
        self.assertEqual(self.names(path, 1, 27), ["deepest"])

    def test_import_completion_follows_dunder_all_and_orders_private_last(self):
        path = self.write("typing_all.py", "from helpers import ")
        self.assertEqual(self.names(path, 1, 20), ["shout", "_kept"])

    def test_import_completion_offers_the_submodules_of_a_package(self):
        path = self.write("typing_sub.py", "import pkg.")
        self.assertEqual(self.names(path, 1, 11), ["deep", "models", "sibling"])

    def test_import_completion_offers_siblings_of_a_relative_import(self):
        path = self.write("pkg/deep/typing_relative.py", "from .. import ")
        offered = self.names(path, 1, 15, "--project", str(self.root))
        self.assertLessEqual({"deep", "models", "sibling", "Dog", "LABEL"}, set(offered))

    def test_import_completion_of_an_unknown_module_offers_nothing(self):
        path = self.write("typing_unknown.py", "from nosuchthing import ")
        self.assertEqual(self.names(path, 1, 24), [])

    def test_import_completion_reaches_the_standard_library(self):
        path = self.write("typing_stdlib.py", "from os import getcw")
        self.assertEqual(self.names(path, 1, 19), ["getcwd", "getcwdb"])

    # Cross-file attributes -----------------------------------------------

    def test_attribute_completion_works_on_an_imported_class(self):
        path = self.write("attributes.py", "from pkg.models import Dog\n\npet = Dog('a')\npet.\n")
        self.assertEqual(self.names(path, 4, 4), ["bark", "name", "__init__"])

    def test_attribute_completion_works_on_an_imported_module(self):
        path = self.write("module_attributes.py", "import pkg\npkg.\n")
        offered = self.names(path, 2, 4)
        self.assertLessEqual({"Dog", "LABEL", "models", "deep"}, set(offered))

    def test_a_submodule_is_reachable_through_the_package_that_holds_it(self):
        path = self.write("dotted.py", "import pkg.deep.inner\n\nn = pkg.deep.inner.deepest()\n")
        self.assertEqual(
            self.summary("goto", path, 3, 21),
            [("deepest", "function", "pkg.deep.inner.deepest", "pkg/deep/inner.py", 1)],
        )

    # Namespace packages --------------------------------------------------

    def test_namespace_packages_resolve_like_regular_ones(self):
        path = self.write("uses_ns.py", "from ns.tools import gadget\n\nnoise = gadget()\n")
        self.assertEqual(
            self.summary("goto", path, 3, 9, "--follow-imports"),
            [("gadget", "function", "ns.tools.gadget", "ns/tools.py", 1)],
        )
        self.assertEqual(
            self.summary("infer", path, 3, 0),
            [("str", "instance", "builtins.str", "", 0)],
        )

    def test_a_namespace_package_offers_the_modules_it_holds(self):
        path = self.write("typing_ns.py", "from ns import ")
        self.assertEqual(self.names(path, 1, 15), ["tools"])

    # Tolerance -----------------------------------------------------------

    def test_circular_imports_resolve_what_is_available(self):
        self.assertEqual(
            self.summary("goto", self.root / "cycle_a.py", 7, 12, "--follow-imports"),
            [("later", "function", "cycle_b.later", "cycle_b.py", 4)],
        )
        self.assertEqual(
            self.summary("infer", self.root / "cycle_b.py", 5, 12),
            [("int", "instance", "builtins.int", "", 0)],
        )

    def test_a_syntax_error_in_an_imported_file_is_tolerated(self):
        path = self.write("uses_broken.py", "from broken import fine\n\nn = fine()\n")
        self.assertEqual(
            self.summary("goto", path, 3, 5, "--follow-imports"),
            [("fine", "function", "broken.fine", "broken.py", 5)],
        )

    def test_module_paths_use_forward_slashes(self):
        found = self.definitions("goto", self.app, 7, 7, "--follow-imports")
        self.assertEqual([item["module_path"] for item in found], ["pkg/models.py"])


if __name__ == "__main__":
    unittest.main()
