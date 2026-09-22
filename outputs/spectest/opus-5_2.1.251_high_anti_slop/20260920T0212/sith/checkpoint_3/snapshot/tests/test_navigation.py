"""End-to-end checks of the `infer` and `goto` commands against small fixtures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''"""Example module."""

import os
from dataclasses import dataclass


class Calculator:
    """Adds things up."""

    def __init__(self, start=0):
        self.total = start

    def add(self, amount):
        self.total = self.total + amount
        return self.total


@dataclass(frozen=True)
class Point:
    x: int
    label: str


def build(flag):
    if flag:
        return Calculator()
    return Point(1, "origin")


def shout():
    print("hi")


calc = Calculator()
total = calc.add(2)
made = build(True)
quiet = shout()
greeting = "hello"
'''


def run(command, path, line, column):
    """Invoke the CLI and return (exit code, parsed definitions, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", command, str(path), str(line), str(column)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)["definitions"] if result.stdout.strip() else None
    return result.returncode, payload, result.stderr


class NavigationTest(unittest.TestCase):
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

    def definitions(self, command, path, line, column):
        code, found, error = run(command, path, line, column)
        self.assertEqual(code, 0, error)
        return found

    def summary(self, command, path, line, column):
        """The (name, type, full_name, line) of each definition found."""
        return [
            (item["name"], item["type"], item["full_name"], item["line"])
            for item in self.definitions(command, path, line, column)
        ]

    def test_instantiation_infers_an_instance_of_the_class(self):
        self.assertEqual(
            self.definitions("infer", self.sample, 34, 1),
            [
                {
                    "name": "Calculator",
                    "type": "instance",
                    "full_name": "sample.Calculator",
                    "module_path": "sample.py",
                    "line": 7,
                    "column": 6,
                    "description": "instance of Calculator",
                    "docstring": "Adds things up.",
                }
            ],
        )

    def test_goto_reports_the_assignment_rather_than_the_class(self):
        self.assertEqual(
            self.definitions("goto", self.sample, 34, 0),
            [
                {
                    "name": "calc",
                    "type": "statement",
                    "full_name": "sample.calc",
                    "module_path": "sample.py",
                    "line": 34,
                    "column": 0,
                    "description": "Calculator()",
                    "docstring": "",
                }
            ],
        )

    def test_bare_function_name_resolves_the_same_way_for_both_commands(self):
        expected = [("build", "function", "sample.build", 24)]
        self.assertEqual(self.summary("goto", self.sample, 36, 8), expected)
        self.assertEqual(self.summary("infer", self.sample, 36, 8), expected)

    def test_literals_infer_to_builtin_types_without_a_location(self):
        self.assertEqual(
            self.definitions("infer", self.sample, 38, 0),
            [
                {
                    "name": "str",
                    "type": "instance",
                    "full_name": "builtins.str",
                    "module_path": "",
                    "line": 0,
                    "column": 0,
                    "description": "instance of str",
                    "docstring": "",
                }
            ],
        )

    def test_return_types_follow_the_body_of_the_called_function(self):
        self.assertEqual(
            self.summary("infer", self.sample, 35, 2),
            [("int", "instance", "builtins.int", 0)],
        )

    def test_several_return_paths_give_several_definitions(self):
        self.assertEqual(
            self.summary("infer", self.sample, 36, 1),
            [
                ("Calculator", "instance", "sample.Calculator", 7),
                ("Point", "instance", "sample.Point", 19),
            ],
        )

    def test_a_function_without_a_return_statement_returns_none(self):
        self.assertEqual(
            self.summary("infer", self.sample, 37, 2),
            [("None", "instance", "builtins.None", 0)],
        )

    def test_attribute_access_reads_instance_state(self):
        path = self.write("attribute.py", SAMPLE + "held = calc.total\n")
        self.assertEqual(
            self.summary("infer", path, 39, 13),
            [("int", "instance", "builtins.int", 0)],
        )
        self.assertEqual(
            self.summary("goto", path, 39, 13),
            [("total", "statement", "attribute.Calculator.total", 11)],
        )

    def test_dataclass_fields_are_instance_attributes(self):
        path = self.write("fields.py", SAMPLE + "spot = Point(1, 'here')\nname = spot.label\n")
        self.assertEqual(
            self.summary("infer", path, 40, 14),
            [("str", "instance", "builtins.str", 0)],
        )
        self.assertEqual(
            self.summary("goto", path, 40, 14),
            [("label", "statement", "fields.Point.label", 21)],
        )

    def test_dataclass_is_recognised_however_it_is_imported(self):
        source = (
            "import dataclasses\n"
            "\n"
            "@dataclasses.dataclass\n"
            "class Row:\n"
            "    count: int\n"
            "\n"
            "row = Row(1)\n"
            "seen = row.count\n"
        )
        path = self.write("aliased.py", source)
        self.assertEqual(
            self.summary("infer", path, 8, 12),
            [("int", "instance", "builtins.int", 0)],
        )

    def test_isinstance_narrows_the_type_inside_the_branch(self):
        source = (
            "from sample import Calculator\n"
            "\n"
            "def handle(thing):\n"
            "    if isinstance(thing, Calculator):\n"
            "        print(thing)\n"
            "    return thing\n"
        )
        path = self.write("narrow.py", source)
        self.assertEqual(
            self.summary("infer", path, 5, 15),
            [("Calculator", "instance", "sample.Calculator", 7)],
        )
        self.assertEqual(self.summary("infer", path, 6, 12), [])

    def test_is_none_narrows_both_branches(self):
        source = (
            "from sample import Calculator\n"
            "\n"
            "def handle(thing=None):\n"
            "    if thing is None:\n"
            "        print(thing)\n"
            "    else:\n"
            "        print(thing)\n"
        )
        path = self.write("optional.py", source)
        self.assertEqual(
            self.summary("infer", path, 5, 15),
            [("None", "instance", "builtins.None", 0)],
        )
        self.assertEqual(self.summary("infer", path, 7, 15), [])

    def test_imported_names_go_to_the_import_and_infer_across_files(self):
        source = "from sample import Calculator\n\nmine = Calculator()\n"
        path = self.write("client.py", source)
        self.assertEqual(
            self.summary("goto", path, 3, 8),
            [("Calculator", "class", "client.Calculator", 1)],
        )
        self.assertEqual(
            self.summary("infer", path, 3, 8),
            [("Calculator", "class", "sample.Calculator", 7)],
        )

    def test_conditional_assignments_report_every_definition_in_order(self):
        source = (
            "if True:\n"
            "    shared = 1\n"
            "else:\n"
            "    shared = 'text'\n"
            "print(shared)\n"
        )
        path = self.write("branches.py", source)
        self.assertEqual(
            [(item["line"], item["column"]) for item in self.definitions("goto", path, 5, 7)],
            [(2, 4), (4, 4)],
        )
        self.assertEqual(
            self.summary("infer", path, 5, 7),
            [("int", "instance", "builtins.int", 0), ("str", "instance", "builtins.str", 0)],
        )

    def test_definition_columns_point_at_the_identifier(self):
        self.assertEqual(
            [(item["line"], item["column"]) for item in self.definitions("goto", self.sample, 36, 8)],
            [(24, 4)],
        )

    def test_unresolvable_names_report_nothing_and_succeed(self):
        path = self.write("unknown.py", "print(mystery)\n")
        for command in ("infer", "goto"):
            self.assertEqual(self.definitions(command, path, 1, 8), [])

    def test_positions_that_hold_no_name_fail(self):
        for command in ("infer", "goto"):
            for arguments in [(self.sample, 7, 2), (self.sample, 34, 5), ("absent.py", 1, 0)]:
                code, _, error = run(command, *arguments)
                self.assertEqual(code, 1)
                self.assertTrue(error.strip())


if __name__ == "__main__":
    unittest.main()
