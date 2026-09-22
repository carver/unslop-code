"""End-to-end checks of interpreter mode: static analysis over a live namespace."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUFFER = '''GREETING = "hi"


def helper():
    return 1


value = unknown_call()
count
frame = df
df.
'''

NAMESPACES = [
    {
        "df": {"type": "DataFrame", "value": "   a\n0  1", "module": "pandas",
               "attributes": ["head", "columns"]},
        "GREETING": {"type": "int", "value": "7"},
        "value": {"type": "Series", "module": "pandas"},
    },
    {
        "df": {"type": "str", "value": "shadowed"},
        "count": {"type": "int", "value": "3"},
    },
]


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


class InterpreterTest(unittest.TestCase):
    """The buffer and the namespaces describing the session are shared fixtures."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        workspace = Path(cls._directory.name)
        cls.buffer = workspace / "buffer.py"
        cls.buffer.write_text(BUFFER, encoding="utf-8")
        cls.namespaces = workspace / "namespaces.json"
        cls.namespaces.write_text(json.dumps(NAMESPACES), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    def interpreted(self, command, line, column, *extra):
        """Run a command in interpreter mode and return its payload."""
        code, payload, error = run(command, self.buffer, line, column, "--interpreter",
                                   "--namespaces", self.namespaces, *extra)
        self.assertEqual(code, 0, error)
        return payload

    def test_a_name_only_the_session_holds_is_inferred_from_the_namespace(self):
        definitions = self.interpreted("infer", 9, 2)["definitions"]
        self.assertEqual(
            [(item["name"], item["type"], item["description"], item["docstring"])
             for item in definitions],
            [("count", "int", "int (runtime)", "3")],
        )

    def test_goto_reports_the_same_record_for_a_runtime_name(self):
        self.assertEqual(
            self.interpreted("goto", 9, 2)["definitions"],
            self.interpreted("infer", 9, 2)["definitions"],
        )

    def test_the_first_namespace_holding_a_name_wins(self):
        definitions = self.interpreted("infer", 10, 9)["definitions"]
        self.assertEqual(
            [(item["type"], item["full_name"], item["description"]) for item in definitions],
            [("DataFrame", "pandas.df", "DataFrame (runtime)")],
        )

    def test_static_analysis_has_priority_over_the_namespace(self):
        definitions = self.interpreted("infer", 1, 3)["definitions"]
        self.assertEqual([item["description"] for item in definitions], ["instance of str"])

    def test_a_value_the_source_cannot_explain_falls_back_to_the_namespace(self):
        definitions = self.interpreted("infer", 8, 2)["definitions"]
        self.assertEqual([item["description"] for item in definitions], ["Series (runtime)"])

    def test_completion_merges_the_names_of_both(self):
        offered = {item["name"]: item
                   for item in self.interpreted("complete", 9, 2)["completions"]}
        self.assertEqual(
            (offered["count"]["type"], offered["count"]["description"],
             offered["count"]["complete"]),
            ("int", "int (runtime)", "unt"),
        )
        self.assertIn("compile", offered)

    def test_attributes_of_a_runtime_value_are_offered(self):
        offered = self.interpreted("complete", 11, 3)["completions"]
        self.assertEqual([item["name"] for item in offered], ["columns", "head"])
        self.assertEqual({item["description"] for item in offered}, {"instance (runtime)"})

    def test_the_flag_alone_leaves_the_tool_in_normal_mode(self):
        code, payload, error = run("complete", self.buffer, 9, 2, "--interpreter")
        self.assertEqual(code, 0, error)
        _, plain, _ = run("complete", self.buffer, 9, 2)
        self.assertEqual(payload, plain)
        self.assertNotIn("count", [item["name"] for item in payload["completions"]])

    def test_namespaces_without_interpreter_mode_fail(self):
        code, _, error = run("infer", self.buffer, 9, 2, "--namespaces", self.namespaces)
        self.assertEqual(code, 1)
        self.assertIn("--interpreter", error)

    def test_an_unreadable_namespaces_file_fails(self):
        broken = Path(self._directory.name) / "broken.json"
        broken.write_text("{}", encoding="utf-8")
        for path in (broken, Path(self._directory.name) / "absent.json"):
            code, _, error = run("infer", self.buffer, 9, 2, "--interpreter",
                                 "--namespaces", path)
            self.assertEqual(code, 1)
            self.assertTrue(error.strip())


if __name__ == "__main__":
    unittest.main()
