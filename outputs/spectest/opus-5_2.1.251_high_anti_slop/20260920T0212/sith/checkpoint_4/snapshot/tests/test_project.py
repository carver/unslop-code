"""End-to-end checks of the `references`, `search` and `names` commands."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''"""Example module."""

import os


class Calculator:
    """Adds things up."""

    def __init__(self, start=0):
        self.total = start

    def add(self, amount):
        self.total = self.total + amount
        return self.total


def build():
    return Calculator()


calc = Calculator()
total = 0
'''

CLIENT = """from sample import Calculator

mine = Calculator()
total = mine.add(1)
"""


def run(command, *arguments):
    """Invoke the CLI and return (exit code, parsed payload, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", command, *[str(item) for item in arguments]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, payload, result.stderr


class ProjectTest(unittest.TestCase):
    """Fixtures are written to a temporary project shared by all tests."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._directory.name)
        cls.sample = cls.write("sample.py", SAMPLE)
        cls.client = cls.write("client.py", CLIENT)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    @classmethod
    def write(cls, name, text):
        path = cls.workspace / name
        path.write_text(text)
        return path

    def payload(self, command, key, *arguments):
        code, found, error = run(command, *arguments, "--project", self.workspace)
        self.assertEqual(code, 0, error)
        return found[key]

    def references(self, path, line, column, *flags):
        found = self.payload("references", "references", path, line, column, *flags)
        return [(item["module_path"], item["line"], item["column"], item["is_definition"])
                for item in found]

    def test_references_in_a_file_cover_the_definition_and_its_uses(self):
        self.assertEqual(
            self.references(self.sample, 6, 6),
            [("sample.py", 6, 6, True), ("sample.py", 18, 11, False), ("sample.py", 21, 7, False)],
        )

    def test_references_across_the_project_follow_imports(self):
        self.assertEqual(
            self.references(self.sample, 6, 6, "--scope", "project"),
            [
                ("client.py", 1, 19, True),
                ("client.py", 3, 7, False),
                ("sample.py", 6, 6, True),
                ("sample.py", 18, 11, False),
                ("sample.py", 21, 7, False),
            ],
        )

    def test_a_same_spelling_name_of_another_scope_is_left_out(self):
        attribute = self.references(self.sample, 10, 13, "--scope", "project")
        self.assertEqual(
            attribute,
            [
                ("sample.py", 10, 13, True),
                ("sample.py", 13, 13, True),
                ("sample.py", 13, 26, False),
                ("sample.py", 14, 20, False),
            ],
        )
        self.assertEqual(self.references(self.sample, 22, 0), [("sample.py", 22, 0, True)])

    def test_search_ranks_exact_matches_before_prefixes_and_substrings(self):
        self.write("extra.py", "def recalculate():\n    pass\n\n\nclass CalcBox:\n    pass\n")
        found = self.payload("search", "definitions", "calc")
        self.assertEqual(
            [(item["name"], item["module_path"], item["line"]) for item in found],
            [
                ("calc", "sample.py", 21),
                ("CalcBox", "extra.py", 5),
                ("Calculator", "sample.py", 6),
                ("recalculate", "extra.py", 1),
            ],
        )
        self.assertNotIn("docstring", found[0])

    def test_search_skips_the_names_bound_inside_function_bodies(self):
        self.write("locals.py", "def outer():\n    hidden = 1\n    return hidden\n")
        found = self.payload("search", "definitions", "hidden")
        self.assertEqual(found, [])

    def test_names_lists_module_level_definitions_in_source_order(self):
        found = self.payload("names", "definitions", self.sample)
        self.assertEqual(
            [(item["name"], item["line"]) for item in found],
            [("os", 3), ("Calculator", 6), ("build", 17), ("calc", 21), ("total", 22)],
        )
        self.assertTrue(all(item["is_definition"] for item in found))

    def test_all_scopes_adds_the_names_of_methods_and_their_parameters(self):
        found = self.payload("names", "definitions", self.sample, "--all-scopes")
        names = [item["name"] for item in found]
        self.assertEqual(names[:5], ["os", "Calculator", "__init__", "self", "start"])
        self.assertIn("amount", names)

    def test_a_position_holding_no_name_fails(self):
        code, _, error = run("references", self.sample, 1, 2, "--project", self.workspace)
        self.assertEqual(code, 1)
        self.assertTrue(error.strip())


if __name__ == "__main__":
    unittest.main()
