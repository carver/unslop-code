"""End-to-end checks of the completion engine against small fixtures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''import os
from collections import OrderedDict

GREETING = "hello"


class Animal:
    kingdom = "animalia"

    def __init__(self, name):
        self.name = name

    def speak(self):
        return "..."


class Dog(Animal):
    def fetch(self, item):
        total = 1
        
        return item


pet = Dog("fido")
'''

UNION = """class Cat:
    def purr(self):
        return 1


class Fish:
    def swim(self):
        return 2


def pick(flag):
    if flag:
        return Cat()
    return Fish()


thing = pick(True)
thing.
"""

DATACLASS = """from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: int
    label: str

    def shift(self):
        return self


spot = Point(1, "here")
spot.
"""


def run(path, line, column, *flags):
    """Invoke the CLI and return (exit code, parsed completions, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", "complete", str(path), str(line), str(column), *flags],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)["completions"] if result.stdout.strip() else None
    return result.returncode, payload, result.stderr


class CompletionTest(unittest.TestCase):
    """Fixtures are written to a temporary directory shared by all tests."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._directory.name)
        cls.sample = cls.write("sample.py", SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    @classmethod
    def write(cls, name, text):
        path = cls.workspace / name
        path.write_text(text)
        return path

    def names(self, path, line, column, *flags):
        code, completions, error = run(path, line, column, *flags)
        self.assertEqual(code, 0, error)
        return [item["name"] for item in completions]

    def test_local_names_shadow_globals_and_hide_later_definitions(self):
        names = self.names(self.sample, 20, 8)
        self.assertIn("total", names)
        self.assertIn("item", names)
        self.assertIn("Animal", names)
        self.assertNotIn("pet", names)

    def test_keywords_join_name_completion_and_sort_last(self):
        names = self.names(self.sample, 20, 8)
        self.assertEqual(names[-1], "yield")
        self.assertIn("lambda", names)

    def test_prefix_is_case_insensitive_and_trimmed_from_complete(self):
        code, completions, error = run(self.sample, 24, 2)
        self.assertEqual(code, 0, error)
        matched = {item["name"]: item for item in completions}
        self.assertEqual(
            matched["pet"],
            {
                "name": "pet",
                "complete": "t",
                "type": "instance",
                "description": "instance of Dog",
            },
        )
        self.assertEqual(matched["PendingDeprecationWarning"]["complete"], "ndingDeprecationWarning")

    def test_fuzzy_matching_skips_characters(self):
        self.assertIn("OrderedDict", self.names(self.sample, 24, 0, "--fuzzy"))

    def test_instance_attributes_include_inherited_and_init_assignments(self):
        path = self.write("instance.py", SAMPLE + "pet.\n")
        self.assertEqual(
            self.names(path, 25, 4), ["fetch", "kingdom", "name", "speak", "__init__"]
        )

    def test_class_attributes_exclude_init_assignments(self):
        path = self.write("klass.py", SAMPLE + "Dog.\n")
        self.assertNotIn("name", self.names(path, 25, 4))

    def test_module_attributes_are_public_only(self):
        path = self.write("module.py", SAMPLE + "os.\n")
        names = self.names(path, 25, 3)
        self.assertIn("getcwd", names)
        self.assertFalse([name for name in names if name.startswith("_")])

    def test_literal_attributes_come_from_the_inferred_type(self):
        path = self.write("literal.py", '"text".up\n')
        self.assertEqual(self.names(path, 1, 9), ["upper"])

    def test_attribute_completion_omits_keywords(self):
        path = self.write("nokeyword.py", "values = []\nvalues.c\n")
        self.assertEqual(self.names(path, 2, 8), ["clear", "copy", "count"])

    def test_star_import_exposes_local_modules(self):
        self.write("project_helpers.py", "def gather():\n    pass\n")
        path = self.write("stars.py", "from project_helpers import *\ngath\n")
        self.assertEqual(self.names(path, 2, 4), ["gather"])

    def test_syntax_errors_still_produce_completions(self):
        path = self.write("broken.py", 'def oops(:\n    pass\nlabel = "x"\nlabel.tit\n')
        self.assertEqual(self.names(path, 4, 9), ["title"])

    def test_ordering_groups_public_private_and_dunder_names(self):
        path = self.write("ordering.py", "__wrapped__ = 1\n_hidden = 2\nvisible = 3\n\n")
        declared = {"visible", "_hidden", "__wrapped__", "while"}
        names = [name for name in self.names(path, 4, 0) if name in declared]
        self.assertEqual(names, ["visible", "_hidden", "__wrapped__", "while"])

    def test_attribute_completion_follows_inferred_return_types(self):
        path = self.write("union.py", UNION)
        self.assertEqual(self.names(path, 18, 6), ["purr", "swim"])

    def test_isinstance_narrowing_drives_attribute_completion(self):
        source = SAMPLE + "\n\ndef touch(thing):\n    if isinstance(thing, Dog):\n        thing.\n"
        path = self.write("narrowed.py", source)
        self.assertEqual(
            self.names(path, 29, 14), ["fetch", "kingdom", "name", "speak", "__init__"]
        )

    def test_dataclass_fields_complete_on_instances(self):
        path = self.write("point.py", DATACLASS)
        self.assertEqual(self.names(path, 14, 5), ["label", "shift", "x"])

    def test_out_of_range_and_missing_files_fail(self):
        for arguments in [(self.sample, 900, 0), (self.sample, 1, 900), ("absent.py", 1, 0)]:
            code, _, error = run(*arguments)
            self.assertEqual(code, 1)
            self.assertTrue(error.strip())


if __name__ == "__main__":
    unittest.main()
