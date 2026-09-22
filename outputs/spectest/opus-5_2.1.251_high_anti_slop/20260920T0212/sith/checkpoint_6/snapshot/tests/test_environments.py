"""End-to-end checks of the `env` commands against the interpreters present."""

import json
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


class EnvironmentTest(unittest.TestCase):
    """A virtualenv is built once, in a directory the searches are pointed at."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._directory.name)
        cls.virtualenv = cls.workspace / "envs" / "made"
        venv.EnvBuilder(with_pip=False).create(cls.virtualenv)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    def environments(self, *arguments):
        code, payload, error = run("env", *arguments)
        self.assertEqual(code, 0, error)
        return payload["environments"]

    def test_the_installations_found_are_described_and_unique(self):
        found = self.environments("list")
        self.assertTrue(found)
        for record in found:
            self.assertEqual(sorted(record), ["executable", "is_virtualenv", "version"])
            self.assertTrue(Path(record["executable"]).is_absolute())
            self.assertIsInstance(record["is_virtualenv"], bool)
        resolved = [str(Path(record["executable"]).resolve()) for record in found]
        self.assertEqual(len(resolved), len(set(resolved)))

    def test_installations_are_listed_newest_first(self):
        found = self.environments("list")
        ordered = sorted(
            found,
            key=lambda record: (tuple(-int(part) for part in record["version"].split(".")),
                                record["executable"]),
        )
        self.assertEqual(found, ordered)

    def test_a_virtualenv_is_found_where_it_was_made(self):
        found = self.environments("find-virtualenvs", "--path", self.workspace / "envs")
        made = [record for record in found
                if record["executable"] == str(self.virtualenv / "bin" / "python")]
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0]["is_virtualenv"])
        self.assertTrue(all(record["is_virtualenv"] for record in found))

    def test_a_directory_holding_no_interpreter_contributes_nothing(self):
        plain = self.workspace / "plain"
        (plain / "empty").mkdir(parents=True)
        found = self.environments("find-virtualenvs", "--path", plain)
        self.assertEqual([record for record in found
                          if str(plain) in record["executable"]], [])

    def test_one_environment_reports_its_prefix_and_import_path(self):
        code, payload, error = run("env", "info", self.virtualenv / "bin" / "python")
        self.assertEqual(code, 0, error)
        record = payload["environment"]
        self.assertEqual(record["prefix"], str(self.virtualenv))
        self.assertTrue(record["is_virtualenv"])
        self.assertTrue(any(str(self.virtualenv) in entry for entry in record["sys_path"]))

    def test_the_default_environment_is_described_without_an_executable(self):
        code, payload, error = run("env", "info")
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["environment"]["version"].count("."), 2)

    def test_the_project_file_chooses_the_environment(self):
        project = self.workspace / "project"
        project.mkdir()
        executable = str(self.virtualenv / "bin" / "python")
        self.assertEqual(run("project", "init", project, "--environment", executable)[0], 0)
        code, payload, error = run("env", "info", "--project", project)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["environment"]["executable"], executable)

    def test_an_executable_that_runs_no_python_fails(self):
        script = self.workspace / "not-python"
        script.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        script.chmod(0o755)
        code, _, error = run("env", "info", script)
        self.assertEqual(code, 1)
        self.assertIn("not a Python executable", error)


if __name__ == "__main__":
    unittest.main()
