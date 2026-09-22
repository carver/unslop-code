"""End-to-end checks of the refactoring commands and of `errors`."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''"""Example module."""


class Calculator:
    """Adds things up."""

    def __init__(self, start=0):
        self.total = start

    def add(self, amount):
        return self.total + amount


def build():
    return Calculator()
'''

CLIENT = """import sample
from sample import Calculator

mine = Calculator()
maker = sample.build()
"""

LOCALS = """def compute(items):
    factor = 2 + 3
    scaled = [item * factor for item in items]
    return sum(scaled) / factor


def report(rows):
    total = 0
    count = 0
    for row in rows:
        total = total + row
        count = count + 1
    average = total / count
    return average


unused = 7
"""


class RefactoringTest(unittest.TestCase):
    """Each test refactors a fresh copy of the fixtures in a temporary project."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self._directory.name)
        self.write("sample.py", SAMPLE)
        self.write("client.py", CLIENT)
        self.write("locals.py", LOCALS)

    def tearDown(self):
        self._directory.cleanup()

    def write(self, name, text):
        path = self.workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_command(self, command, *arguments):
        """Invoke the CLI on the temporary project and return (code, stdout, stderr)."""
        scoped = [] if command == "errors" else ["--project", str(self.workspace)]
        result = subprocess.run(
            [sys.executable, "sith.py", command, *[str(item) for item in arguments], *scoped],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def refactor(self, command, *arguments):
        """The payload of a refactoring that is expected to succeed."""
        code, output, error = self.run_command(command, *arguments)
        self.assertEqual(code, 0, error)
        return json.loads(output)

    def rejects(self, command, *arguments):
        """The message a refactoring that is expected to fail prints."""
        code, output, error = self.run_command(command, *arguments)
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        return error

    # rename -----------------------------------------------------------

    def test_rename_rewrites_the_definition_and_every_project_reference(self):
        found = self.refactor("rename", self.workspace / "sample.py", 4, 6,
                              "--new-name", "Adder")
        self.assertEqual(found["renames"], {})
        self.assertIn("class Adder:", found["changed_files"]["sample.py"])
        self.assertIn("return Adder()", found["changed_files"]["sample.py"])
        self.assertIn("from sample import Adder", found["changed_files"]["client.py"])

    def test_rename_leaves_the_files_it_does_not_touch_out(self):
        found = self.refactor("rename", self.workspace / "locals.py", 2, 4,
                              "--new-name", "weight")
        self.assertEqual(list(found["changed_files"]), ["locals.py"])
        self.assertIn("    weight = 2 + 3", found["changed_files"]["locals.py"])

    def test_rename_reports_a_unified_diff_instead_of_contents(self):
        code, output, error = self.run_command(
            "rename", self.workspace / "locals.py", 2, 4, "--new-name", "weight", "--diff")
        self.assertEqual(code, 0, error)
        self.assertIn("--- a/locals.py", output)
        self.assertIn("-    factor = 2 + 3", output)
        self.assertIn("+    weight = 2 + 3", output)

    def test_rename_refuses_an_invalid_name_a_literal_and_a_collision(self):
        sample = self.workspace / "sample.py"
        self.assertIn("identifier",
                      self.rejects("rename", sample, 4, 6, "--new-name", "9lives"))
        self.assertIn("no name", self.rejects("rename", sample, 1, 2, "--new-name", "Adder"))
        self.assertIn("already defined",
                      self.rejects("rename", sample, 4, 6, "--new-name", "build"))

    def test_renaming_a_module_moves_its_file_and_rewrites_the_imports(self):
        found = self.refactor("rename", self.workspace / "client.py", 1, 8,
                              "--new-name", "models")
        self.assertEqual(found["renames"], {"sample.py": "models.py"})
        rewritten = found["changed_files"]["client.py"]
        self.assertIn("import models", rewritten)
        self.assertIn("from models import Calculator", rewritten)
        self.assertIn("maker = models.build()", rewritten)

    def test_renaming_a_package_moves_its_directory(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/tools.py", "def helper():\n    return 1\n")
        self.write("uses.py", "from pkg.tools import helper\n\nvalue = helper()\n")
        found = self.refactor("rename", self.workspace / "uses.py", 1, 5,
                              "--new-name", "core")
        self.assertEqual(found["renames"], {"pkg": "core"})
        self.assertIn("from core.tools import helper", found["changed_files"]["uses.py"])

    def test_renaming_a_module_onto_an_existing_file_fails(self):
        self.assertIn("already exists",
                      self.rejects("rename", self.workspace / "client.py", 1, 8,
                                   "--new-name", "locals"))

    # inline -----------------------------------------------------------

    def test_inline_replaces_the_references_and_drops_the_assignment(self):
        found = self.refactor("inline", self.workspace / "locals.py", 2, 4)
        rewritten = found["changed_files"]["locals.py"]
        self.assertNotIn("factor", rewritten)
        self.assertIn("    scaled = [item * (2 + 3) for item in items]", rewritten)

    def test_inline_parenthesizes_only_where_precedence_demands_it(self):
        self.write("values.py", "base = 2 + 3\nwhole = base\nhalf = base / 2\n")
        rewritten = self.refactor("inline", self.workspace / "values.py", 1, 0)
        self.assertEqual(
            rewritten["changed_files"]["values.py"],
            "whole = 2 + 3\nhalf = (2 + 3) / 2\n",
        )

    def test_inline_refuses_definitions_and_names_nothing_uses(self):
        self.assertIn("function/class definition",
                      self.rejects("inline", self.workspace / "locals.py", 1, 4))
        self.assertIn("no references",
                      self.rejects("inline", self.workspace / "locals.py", 17, 0))

    # extract-variable -------------------------------------------------

    def test_extract_variable_names_the_expression_above_its_statement(self):
        found = self.refactor("extract-variable", self.workspace / "sample.py", 11, 15,
                              "--until", "11:34", "--name", "raised")
        self.assertIn("        raised = self.total + amount\n        return raised",
                      found["changed_files"]["sample.py"])

    def test_extract_variable_refuses_a_partial_expression_and_a_bad_name(self):
        sample = self.workspace / "sample.py"
        self.assertIn("complete expression",
                      self.rejects("extract-variable", sample, 11, 15,
                                   "--until", "11:26", "--name", "raised"))
        self.assertIn("identifier",
                      self.rejects("extract-variable", sample, 11, 15,
                                   "--until", "11:34", "--name", "not-a-name"))

    # extract-function -------------------------------------------------

    def test_extract_function_passes_what_it_reads_and_returns_what_is_used_later(self):
        found = self.refactor("extract-function", self.workspace / "locals.py", 10, 4,
                              "--until", "12:25", "--name", "accumulate")
        self.assertIn(
            "def accumulate(rows, total, count):\n"
            "    for row in rows:\n"
            "        total = total + row\n"
            "        count = count + 1\n"
            "    return total, count\n",
            found["changed_files"]["locals.py"],
        )
        self.assertIn("    total, count = accumulate(rows, total, count)\n",
                      found["changed_files"]["locals.py"])

    def test_extract_function_at_module_level_takes_the_names_it_reads(self):
        self.write("script.py", "data = [1, 2]\nscaled = [item * 2 for item in data]\n"
                                "print(scaled)\n")
        found = self.refactor("extract-function", self.workspace / "script.py", 2, 0,
                              "--until", "2:37", "--name", "scale")
        self.assertIn("def scale(data):\n"
                      "    scaled = [item * 2 for item in data]\n"
                      "    return scaled\n", found["changed_files"]["script.py"])
        self.assertIn("scaled = scale(data)\n", found["changed_files"]["script.py"])

    def test_extract_function_refuses_a_selection_cutting_a_statement(self):
        self.assertIn("complete run of statements",
                      self.rejects("extract-function", self.workspace / "locals.py", 10, 4,
                                   "--until", "12:20", "--name", "accumulate"))

    # errors -----------------------------------------------------------

    def test_errors_reports_nothing_for_a_file_that_parses(self):
        code, output, error = self.run_command("errors", self.workspace / "sample.py")
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output), {"errors": []})

    def test_errors_reports_where_the_parser_gave_up(self):
        broken = self.write("broken.py", "def broken(:\n    return 1\n")
        code, output, _ = self.run_command("errors", broken)
        self.assertEqual(code, 0)
        found = json.loads(output)["errors"][0]
        self.assertEqual((found["line"], found["column"]), (1, 11))
        self.assertTrue(found["message"])

    def test_errors_fails_when_the_file_is_missing(self):
        code, _, error = self.run_command("errors", self.workspace / "nowhere.py")
        self.assertEqual(code, 1)
        self.assertIn("not a regular file", error)


if __name__ == "__main__":
    unittest.main()
