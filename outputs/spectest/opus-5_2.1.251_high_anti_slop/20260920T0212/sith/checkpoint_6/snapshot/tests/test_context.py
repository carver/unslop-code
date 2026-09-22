"""End-to-end checks of the `context` command against nested scopes."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''"""Example module."""

TOTAL = 0


class Counter:
    step = 1

    def bump(self, amount):
        def rounded():
            return amount

        return rounded()


def free():
    return TOTAL
'''


def run(*arguments):
    """Invoke the CLI and return (exit code, parsed payload, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", *[str(item) for item in arguments]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, payload, result.stderr


class ContextTest(unittest.TestCase):
    """One fixture holding a class, a method and a function inside it."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.sample = Path(cls._directory.name) / "sample.py"
        cls.sample.write_text(SAMPLE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    def context(self, line, column):
        code, payload, error = run("context", self.sample, line, column)
        self.assertEqual(code, 0, error)
        return payload["context"]

    def test_module_level_code_sits_in_no_scope(self):
        self.assertEqual(self.context(3, 0), [])

    def test_a_class_body_reports_the_class(self):
        self.assertEqual(self.context(7, 4),
                         [{"name": "Counter", "type": "class", "line": 6, "column": 6}])

    def test_scopes_run_from_the_outermost_inwards(self):
        self.assertEqual(
            [(item["name"], item["type"]) for item in self.context(11, 12)],
            [("Counter", "class"), ("bump", "function"), ("rounded", "function")],
        )

    def test_each_scope_points_at_the_name_it_declares(self):
        self.assertEqual(
            [(item["line"], item["column"]) for item in self.context(13, 8)],
            [(6, 6), (9, 8)],
        )

    def test_a_function_of_the_module_is_the_only_scope(self):
        self.assertEqual(
            [item["name"] for item in self.context(17, 4)],
            ["free"],
        )

    def test_a_cursor_outside_the_file_fails(self):
        code, _, error = run("context", self.sample, 99, 0)
        self.assertEqual(code, 1)
        self.assertTrue(error.strip())


if __name__ == "__main__":
    unittest.main()
