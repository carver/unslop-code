"""End-to-end checks of the `signatures` command against small fixtures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''class Calculator:
    """Adds things up."""

    def __init__(self, start=0):
        self.total = start

    def add(self, amount, *, loud=False):
        """Add an amount."""
        return self.total + amount

    @staticmethod
    def zero():
        return 0


def build(flag, label="x", *extra, **options):
    """Make one."""
    return flag


def typed(count: int, name: str = "x") -> bool:
    return True
'''


def run(path, line, column, *flags):
    """Invoke the CLI and return (exit code, parsed signatures, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", "signatures", str(path), str(line), str(column), *flags],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)["signatures"] if result.stdout.strip() else None
    return result.returncode, payload, result.stderr


class SignatureTest(unittest.TestCase):
    """Fixtures are written to a temporary directory shared by all tests."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._directory.name)
        cls.write("sample.py", SAMPLE)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    @classmethod
    def write(cls, name, text):
        path = cls.workspace / name
        path.write_text(text)
        return path

    def at(self, source, line, column, *flags):
        """The signatures where a cursor sits in a file importing the sample."""
        path = self.write("cursor.py", source)
        code, found, error = run(path, line, column, *flags)
        self.assertEqual(code, 0, error)
        return found

    def test_a_call_reports_its_parameters_and_the_current_one(self):
        source = "from sample import build\nbuild(True, "
        self.assertEqual(
            self.at(source, 2, 12),
            [
                {
                    "name": "build",
                    "params": ["flag", "label='x'", "*extra", "**options"],
                    "index": 1,
                    "description": "def build(flag, label='x', *extra, **options)",
                    "docstring": "Make one.",
                }
            ],
        )

    def test_annotations_and_return_types_are_rendered_without_spaces(self):
        source = "from sample import typed\ntyped("
        signature = self.at(source, 2, 6)[0]
        self.assertEqual(signature["params"], ["count: int", "name: str='x'"])
        self.assertEqual(signature["description"], "def typed(count: int, name: str='x') -> bool")

    def test_a_method_call_hides_the_receiver(self):
        source = "from sample import Calculator\nCalculator().add("
        signature = self.at(source, 2, 17)[0]
        self.assertEqual(signature["name"], "add")
        self.assertEqual(signature["params"], ["amount", "loud=False"])
        self.assertEqual(signature["index"], 0)

    def test_a_static_method_keeps_every_parameter(self):
        source = "from sample import Calculator\nCalculator.zero("
        self.assertEqual(self.at(source, 2, 16)[0]["params"], [])

    def test_a_class_is_called_through_its_initialiser(self):
        source = "from sample import Calculator\nCalculator("
        self.assertEqual(
            self.at(source, 2, 11),
            [
                {
                    "name": "Calculator",
                    "params": ["start=0"],
                    "index": 0,
                    "description": "def Calculator(start=0)",
                    "docstring": "Adds things up.",
                }
            ],
        )

    def test_keyword_arguments_point_at_the_parameter_they_name(self):
        source = "from sample import Calculator\nCalculator().add(1, loud="
        self.assertEqual(self.at(source, 2, 25)[0]["index"], 1)

    def test_extra_arguments_land_on_the_collecting_parameter(self):
        source = "from sample import build\nbuild(1, 2, 3, 4, "
        self.assertEqual(self.at(source, 2, 18)[0]["index"], 2)

    def test_an_unknown_keyword_lands_on_the_double_starred_parameter(self):
        source = "from sample import build\nbuild(1, mystery="
        self.assertEqual(self.at(source, 2, 17)[0]["index"], 3)

    def test_a_call_that_takes_no_more_arguments_has_no_current_parameter(self):
        source = "from sample import Calculator\nCalculator().add(1, 2, 3"
        self.assertEqual(self.at(source, 2, 24)[0]["index"], None)

    def test_nested_calls_report_the_innermost_one(self):
        source = "from sample import Calculator, build\nbuild(Calculator("
        self.assertEqual(self.at(source, 2, 17)[0]["name"], "Calculator")

    def test_commas_inside_strings_and_brackets_do_not_move_the_parameter(self):
        source = 'from sample import build\nbuild("a, b", [1, 2], '
        self.assertEqual(self.at(source, 2, 22)[0]["index"], 2)

    def test_a_cursor_outside_any_call_reports_nothing(self):
        self.assertEqual(self.at("from sample import build\nvalue = 1\n", 2, 9), [])

    def test_a_definition_being_typed_is_not_a_call(self):
        self.assertEqual(self.at("def build(", 1, 10), [])

    def test_imported_objects_report_the_signature_they_expose(self):
        signature = self.at("import json\njson.dumps(value, ", 2, 18)[0]
        self.assertEqual(signature["name"], "dumps")
        self.assertEqual(signature["params"][0], "obj")
        self.assertEqual(signature["index"], None)

    def test_out_of_range_positions_fail(self):
        code, _, error = run(self.workspace / "sample.py", 900, 0)
        self.assertEqual(code, 1)
        self.assertTrue(error.strip())


if __name__ == "__main__":
    unittest.main()
