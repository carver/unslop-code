"""Spec conformance tests for interpreter mode, environments and settings."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITH = os.path.join(ROOT, "sith.py")
PY = sys.executable


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def write_namespaces(self, *namespaces):
        return self.write("ns.json", json.dumps(list(namespaces)))

    def run_sith(self, *args, **kwargs):
        return subprocess.run(
            [PY, SITH] + [str(a) for a in args],
            capture_output=True,
            cwd=kwargs.get("cwd"),
        )

    def json_of(self, *args, **kwargs):
        proc = self.run_sith(*args, **kwargs)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        raw = proc.stdout.decode()
        self.assertTrue(raw.endswith("\n"), "output must be newline terminated")
        return json.loads(raw)

    def by_name(self, records):
        return {record["name"]: record for record in records}


# ---------------------------------------------------------------------------
# Interpreter mode
# ---------------------------------------------------------------------------


class TestInterpreterCompletion(Base):
    def test_namespace_names_are_merged_in(self):
        path = self.write("a.py", "def local_fn():\n    pass\n\nva\n")
        ns = self.write_namespaces({"value": {"type": "int", "value": "42"}})
        data = self.json_of(
            "complete", path, 4, 2, "--interpreter", "--namespaces", ns
        )
        got = self.by_name(data["completions"])
        self.assertEqual(
            got["value"],
            {
                "name": "value",
                "complete": "lue",
                "type": "int",
                "description": "int (runtime)",
            },
        )

    def test_static_analysis_has_priority(self):
        path = self.write("a.py", "def thing():\n    pass\n\nthing\n")
        ns = self.write_namespaces({"thing": {"type": "int"}})
        data = self.json_of(
            "complete", path, 4, 5, "--interpreter", "--namespaces", ns
        )
        got = self.by_name(data["completions"])["thing"]
        self.assertEqual(got["type"], "function")
        self.assertEqual(got["description"], "def thing(...)")

    def test_first_namespace_wins(self):
        path = self.write("a.py", "runtime_only\n")
        ns = self.write_namespaces(
            {"runtime_only": {"type": "int"}}, {"runtime_only": {"type": "str"}}
        )
        data = self.json_of(
            "complete", path, 1, 12, "--interpreter", "--namespaces", ns
        )
        got = self.by_name(data["completions"])["runtime_only"]
        self.assertEqual(got["type"], "int")
        self.assertEqual(got["description"], "int (runtime)")

    def test_attribute_fallback_uses_attributes(self):
        path = self.write("a.py", "np.ar\n")
        ns = self.write_namespaces(
            {"np": {"type": "module", "module": "numpy", "attributes": ["array"]}}
        )
        data = self.json_of(
            "complete", path, 1, 5, "--interpreter", "--namespaces", ns
        )
        self.assertEqual([c["name"] for c in data["completions"]], ["array"])

    def test_without_namespaces_behaves_normally(self):
        path = self.write("a.py", "p\n")
        plain = self.json_of("complete", path, 1, 1)
        interpreted = self.json_of("complete", path, 1, 1, "--interpreter")
        self.assertEqual(plain, interpreted)

    def test_namespaces_without_interpreter_fails(self):
        path = self.write("a.py", "p\n")
        ns = self.write_namespaces({"p": {"type": "int"}})
        proc = self.run_sith("complete", path, 1, 1, "--namespaces", ns)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stderr.decode().strip())
        self.assertEqual(proc.stdout.decode(), "")

    def test_missing_namespaces_file_fails(self):
        path = self.write("a.py", "p\n")
        proc = self.run_sith(
            "complete", path, 1, 1, "--interpreter", "--namespaces", "nope.json"
        )
        self.assertEqual(proc.returncode, 1)


class TestInterpreterNavigation(Base):
    def setUp(self):
        Base.setUp(self)
        self.path = self.write("a.py", "runtime_only\n")
        self.ns = self.write_namespaces(
            {
                "runtime_only": {
                    "type": "int",
                    "value": "42",
                    "module": "__main__",
                    "name": "runtime_only",
                }
            },
            {"runtime_only": {"type": "str"}},
        )

    def definitions(self, command):
        data = self.json_of(
            command, self.path, 1, 4, "--interpreter", "--namespaces", self.ns
        )
        return data["definitions"]

    def test_infer_falls_back_to_the_namespace(self):
        found = self.definitions("infer")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "runtime_only")
        self.assertEqual(found[0]["type"], "int")
        self.assertEqual(found[0]["description"], "int (runtime)")
        self.assertEqual(found[0]["full_name"], "__main__.runtime_only")

    def test_goto_falls_back_to_the_namespace(self):
        found = self.definitions("goto")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["type"], "int")
        self.assertEqual(found[0]["description"], "int (runtime)")

    def test_static_definitions_win(self):
        path = self.write("b.py", "value = 1\nvalue\n")
        ns = self.write_namespaces({"value": {"type": "str"}})
        data = self.json_of(
            "goto", path, 2, 2, "--interpreter", "--namespaces", ns
        )
        self.assertEqual(data["definitions"][0]["line"], 1)
        self.assertEqual(data["definitions"][0]["module_path"], "b.py")

    def test_signatures_fall_back_to_the_namespace(self):
        path = self.write("c.py", "helper(\n")
        ns = self.write_namespaces(
            {"helper": {"type": "function", "value": "<function helper>"}}
        )
        data = self.json_of(
            "signatures", path, 1, 7, "--interpreter", "--namespaces", ns
        )
        self.assertEqual(len(data["signatures"]), 1)
        record = data["signatures"][0]
        self.assertEqual(record["name"], "helper")
        self.assertEqual(record["description"], "function (runtime)")

    def test_static_signatures_win(self):
        path = self.write("d.py", "def add(x, y=1):\n    return x\nadd(\n")
        ns = self.write_namespaces({"add": {"type": "function"}})
        data = self.json_of(
            "signatures", path, 3, 4, "--interpreter", "--namespaces", ns
        )
        self.assertEqual(data["signatures"][0]["params"], ["x", "y=1"])


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


class TestContext(Base):
    SOURCE = (
        "class Outer:\n"
        "    def method(self):\n"
        "        def inner():\n"
        "            value = 1\n"
        "            return value\n"
        "        return inner\n"
        "\n"
        "top = 1\n"
    )

    def context(self, line, col):
        path = self.write("a.py", self.SOURCE)
        return self.json_of("context", path, line, col)["context"]

    def test_module_level_is_empty(self):
        self.assertEqual(self.context(8, 0), [])

    def test_outermost_to_innermost(self):
        self.assertEqual(
            self.context(4, 20),
            [
                {"name": "Outer", "type": "class", "line": 1, "column": 0},
                {"name": "method", "type": "function", "line": 2, "column": 4},
                {"name": "inner", "type": "function", "line": 3, "column": 8},
            ],
        )

    def test_method_body(self):
        self.assertEqual(
            [entry["name"] for entry in self.context(6, 8)], ["Outer", "method"]
        )

    def test_only_key_is_context(self):
        path = self.write("a.py", self.SOURCE)
        data = self.json_of("context", path, 8, 0)
        self.assertEqual(list(data.keys()), ["context"])


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


def version_key(version):
    return tuple(int(part) for part in version.split(".") if part.isdigit())


class TestEnvironments(Base):
    def test_list_fields_and_order(self):
        data = self.json_of("env", "list")
        environments = data["environments"]
        self.assertTrue(environments)
        seen = []
        for record in environments:
            self.assertEqual(
                sorted(record.keys()), ["executable", "is_virtualenv", "version"]
            )
            self.assertTrue(os.path.isabs(record["executable"]))
            self.assertIsInstance(record["is_virtualenv"], bool)
            self.assertTrue(record["version"])
            seen.append(record)
        keys = [(version_key(r["version"]), r["executable"]) for r in seen]
        expected = sorted(keys, key=lambda item: (tuple(-p for p in item[0]), item[1]))
        self.assertEqual(keys, expected)

    def test_list_is_deduplicated(self):
        environments = self.json_of("env", "list")["environments"]
        resolved = [os.path.realpath(r["executable"]) for r in environments]
        self.assertEqual(len(resolved), len(set(resolved)))

    def test_find_virtualenvs_in_a_directory(self):
        folder = os.path.join(self.dir, "envs", "myenv", "bin")
        os.makedirs(folder)
        link = os.path.join(folder, "python")
        os.symlink(os.path.realpath(sys.executable), link)
        data = self.json_of(
            "env", "find-virtualenvs", "--path", os.path.join(self.dir, "envs")
        )
        found = [r for r in data["environments"] if r["executable"] == link]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["is_virtualenv"])
        self.assertTrue(found[0]["version"])

    def test_find_virtualenvs_without_a_path(self):
        data = self.json_of("env", "find-virtualenvs", cwd=self.dir)
        self.assertEqual(data["environments"], [])

    def test_info_of_the_running_interpreter(self):
        data = self.json_of("env", "info", sys.executable)
        record = data.get("environment", data)
        self.assertEqual(
            record["version"], ".".join(str(p) for p in sys.version_info[:3])
        )
        self.assertEqual(record["prefix"].replace("\\", "/"), sys.prefix.replace("\\", "/"))
        self.assertTrue(record["sys_path"])
        self.assertIsInstance(record["is_virtualenv"], bool)

    def test_info_defaults_to_python3(self):
        data = self.json_of("env", "info")
        record = data.get("environment", data)
        self.assertTrue(record["executable"])
        self.assertTrue(record["version"])

    def test_info_uses_the_configured_environment(self):
        self.json_of("project", "init", self.dir, "--environment", sys.executable)
        data = self.json_of("env", "info", "--project", self.dir)
        record = data.get("environment", data)
        self.assertEqual(
            os.path.realpath(record["executable"]),
            os.path.realpath(sys.executable),
        )

    def test_info_of_a_bad_executable_fails(self):
        proc = self.run_sith("env", "info", os.path.join(self.dir, "nope"))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.decode(), "")

    def test_unknown_env_command_fails(self):
        self.assertEqual(self.run_sith("env", "nope").returncode, 1)


# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------


class TestProjectConfig(Base):
    def config(self):
        with open(os.path.join(self.dir, ".sith", "project.json")) as fh:
            return json.load(fh)

    def test_init_writes_the_defaults(self):
        self.json_of("project", "init", self.dir)
        self.assertEqual(
            self.config(),
            {
                "environment_path": "",
                "sys_path": [],
                "added_sys_path": [],
                "smart_sys_path": True,
            },
        )

    def test_init_in_the_current_directory(self):
        self.json_of("project", "init", cwd=self.dir)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, ".sith", "project.json")))

    def test_init_records_the_flags(self):
        self.json_of(
            "project",
            "init",
            self.dir,
            "--environment",
            "/usr/bin/python3",
            "--sys-path",
            "one,two",
            "--added-sys-path",
            "three",
        )
        self.assertEqual(
            self.config(),
            {
                "environment_path": "/usr/bin/python3",
                "sys_path": ["one", "two"],
                "added_sys_path": ["three"],
                "smart_sys_path": True,
            },
        )

    def test_init_merges_into_an_existing_config(self):
        self.json_of("project", "init", self.dir, "--sys-path", "one")
        self.json_of("project", "init", self.dir, "--environment", "python3.11")
        self.assertEqual(self.config()["sys_path"], ["one"])
        self.assertEqual(self.config()["environment_path"], "python3.11")

    def test_added_sys_path_makes_a_module_importable(self):
        self.write("libs/helper.py", "def greet(name):\n    return name\n")
        path = self.write("main.py", "import helper\nhelper.greet\n")
        empty = self.json_of("goto", path, 2, 8)
        self.assertEqual(empty["definitions"], [])
        self.json_of("project", "init", self.dir, "--added-sys-path", "libs")
        found = self.json_of("goto", path, 2, 8)["definitions"]
        self.assertEqual(found[0]["name"], "greet")
        self.assertEqual(found[0]["line"], 1)

    def test_sys_path_replaces_the_project_root(self):
        self.write("libs/helper.py", "def greet():\n    pass\n")
        self.write("mod.py", "def top():\n    pass\n")
        path = self.write("main.py", "import mod\nmod.top\n")
        self.json_of("project", "init", self.dir, "--sys-path", "libs")
        self.assertEqual(self.json_of("goto", path, 2, 5)["definitions"], [])

    def test_smart_sys_path_false_drops_auto_detection(self):
        self.write("mod.py", "def top():\n    pass\n")
        path = self.write("main.py", "import mod\nmod.top\n")
        self.assertTrue(self.json_of("goto", path, 2, 5)["definitions"])
        data = self.json_of(
            "goto", path, 2, 5, "--setting", "smart_sys_path=false"
        )
        self.assertEqual(data["definitions"], [])

    def test_setting_overrides_the_project_config(self):
        self.write("mod.py", "def top():\n    pass\n")
        path = self.write("main.py", "import mod\nmod.top\n")
        self.json_of("project", "init", self.dir, "--setting", "smart_sys_path=false")
        self.assertEqual(self.config()["smart_sys_path"], False)
        self.assertEqual(self.json_of("goto", path, 2, 5)["definitions"], [])
        data = self.json_of("goto", path, 2, 5, "--setting", "smart_sys_path=true")
        self.assertTrue(data["definitions"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings(Base):
    def test_add_bracket(self):
        path = self.write("a.py", "def thing():\n    pass\n\nthi\n")
        data = self.json_of("complete", path, 4, 3, "--setting", "add_bracket=true")
        got = self.by_name(data["completions"])["thing"]
        self.assertEqual(got["complete"], "ng(")
        self.assertEqual(got["name"], "thing")

    def test_add_bracket_defaults_to_false(self):
        path = self.write("a.py", "def thing():\n    pass\n\nthi\n")
        data = self.json_of("complete", path, 4, 3)
        self.assertEqual(self.by_name(data["completions"])["thing"]["complete"], "ng")

    def test_case_insensitive_default(self):
        path = self.write("a.py", "Value = 1\nval\n")
        data = self.json_of("complete", path, 2, 3)
        self.assertIn("Value", [c["name"] for c in data["completions"]])

    def test_case_sensitive_matching(self):
        path = self.write("a.py", "Value = 1\nval\n")
        data = self.json_of(
            "complete", path, 2, 3, "--setting", "case_insensitive=false"
        )
        self.assertNotIn("Value", [c["name"] for c in data["completions"]])

    def test_dynamic_params(self):
        path = self.write("a.py", 'def f(a):\n    a\n\nf("hi")\n')
        self.assertTrue(self.json_of("infer", path, 2, 4)["definitions"])
        data = self.json_of("infer", path, 2, 4, "--setting", "dynamic_params=false")
        self.assertEqual(data["definitions"], [])

    def test_case_insensitive_accepts_upper_case_values(self):
        path = self.write("a.py", "Value = 1\nval\n")
        data = self.json_of(
            "complete", path, 2, 3, "--setting", "case_insensitive=FALSE"
        )
        self.assertEqual(data["completions"], [])

    def test_unknown_setting_fails(self):
        path = self.write("a.py", "p\n")
        proc = self.run_sith("complete", path, 1, 1, "--setting", "nope=true")
        self.assertEqual(proc.returncode, 1)

    def test_invalid_value_fails(self):
        path = self.write("a.py", "p\n")
        proc = self.run_sith("complete", path, 1, 1, "--setting", "add_bracket=maybe")
        self.assertEqual(proc.returncode, 1)

    def test_settings_are_accepted_by_every_command(self):
        path = self.write("a.py", "value = 1\n")
        for args in (
            ("names", path),
            ("errors", path),
            ("search", "value", "--project", self.dir),
            ("context", path, 1, 0),
            ("env", "list"),
        ):
            proc = self.run_sith(*(args + ("--setting", "case_insensitive=true")))
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())


if __name__ == "__main__":
    unittest.main()
