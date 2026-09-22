"""End-to-end checks of `project init`, the project file and the settings flags."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LIBRARY = '''def helper(value):
    """Help."""
    return value
'''

CLIENT = """import lib_mod

result = lib_mod.helper(1)
"""

SAMPLE = """def rooted():
    return 1
"""

ROOTED_CLIENT = """import sample

value = sample.rooted()
"""


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


class ConfigurationTest(unittest.TestCase):
    """A project whose importable module sits outside its detected paths."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self._directory.name)
        (self.workspace / "extra").mkdir()
        (self.workspace / "extra" / "lib_mod.py").write_text(LIBRARY, encoding="utf-8")
        self.client = self.workspace / "client.py"
        self.client.write_text(CLIENT, encoding="utf-8")
        (self.workspace / "sample.py").write_text(SAMPLE, encoding="utf-8")
        self.rooted = self.workspace / "rooted.py"
        self.rooted.write_text(ROOTED_CLIENT, encoding="utf-8")

    def tearDown(self):
        self._directory.cleanup()

    def stored(self):
        """The project file as it was written to disk."""
        path = self.workspace / ".sith" / "project.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def resolved(self, path, line, column, *extra):
        """The full names `goto --follow-imports` reaches at a cursor."""
        code, payload, error = run("goto", path, line, column, "--follow-imports", *extra)
        self.assertEqual(code, 0, error)
        return [item["full_name"] for item in payload["definitions"]]

    def test_the_project_file_is_created_with_the_documented_defaults(self):
        code, payload, error = run("project", "init", self.workspace)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload, {"environment_path": "", "sys_path": [],
                                   "added_sys_path": [], "smart_sys_path": True})
        self.assertEqual(self.stored(), payload)

    def test_only_the_fields_that_were_passed_are_overwritten(self):
        run("project", "init", self.workspace, "--added-sys-path", "extra, more")
        run("project", "init", self.workspace, "--environment", "/usr/bin/python3")
        self.assertEqual(self.stored(), {"environment_path": "/usr/bin/python3",
                                         "sys_path": [], "added_sys_path": ["extra", "more"],
                                         "smart_sys_path": True})

    def test_added_paths_make_a_module_importable(self):
        self.assertEqual(self.resolved(self.client, 3, 18), [])
        run("project", "init", self.workspace, "--added-sys-path", "extra")
        self.assertEqual(self.resolved(self.client, 3, 18), ["extra.lib_mod.helper"])

    def test_an_explicit_path_replaces_the_detected_ones(self):
        run("project", "init", self.workspace, "--sys-path", str(self.workspace / "extra"))
        self.assertEqual(self.resolved(self.client, 3, 18), ["extra.lib_mod.helper"])
        self.assertEqual(self.resolved(self.rooted, 3, 16), [])

    def test_turning_off_detection_leaves_only_the_configured_paths(self):
        self.assertEqual(self.resolved(self.rooted, 3, 16), ["sample.rooted"])
        self.assertEqual(
            self.resolved(self.rooted, 3, 16, "--setting", "smart_sys_path=false"), [])

    def test_a_setting_flag_overrides_the_project_file(self):
        run("project", "init", self.workspace)
        path = self.workspace / ".sith" / "project.json"
        path.write_text(json.dumps({"smart_sys_path": False}), encoding="utf-8")
        self.assertEqual(self.resolved(self.rooted, 3, 16), [])
        self.assertEqual(
            self.resolved(self.rooted, 3, 16, "--setting", "smart_sys_path=true"),
            ["sample.rooted"],
        )

    def test_completion_matching_and_brackets_follow_their_settings(self):
        typed = self.workspace / "typed.py"
        typed.write_text("def Ready():\n    return 1\n\n\nrea\n", encoding="utf-8")
        offered = self.completions(typed, 5, 3)
        self.assertEqual([item["name"] for item in offered], ["Ready"])
        self.assertEqual(self.completions(typed, 5, 3, "--setting", "case_insensitive=false"), [])
        bracketed = self.completions(typed, 5, 3, "--setting", "add_bracket=true")
        self.assertEqual([item["complete"] for item in bracketed], ["dy("])

    def test_unknown_settings_and_values_fail(self):
        for flag in ("mystery=true", "add_bracket=perhaps", "add_bracket"):
            code, _, error = run("complete", self.client, 1, 0, "--setting", flag)
            self.assertEqual(code, 1)
            self.assertTrue(error.strip())

    def completions(self, path, line, column, *extra):
        code, payload, error = run("complete", path, line, column, *extra)
        self.assertEqual(code, 0, error)
        return payload["completions"]


if __name__ == "__main__":
    unittest.main()
