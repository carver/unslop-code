"""Spec conformance tests for signatures, references, search, names, stubs."""

import json
import os
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

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_sith(self, *args):
        return subprocess.run(
            [PY, SITH] + [str(a) for a in args], capture_output=True
        )

    def load(self, key, *args):
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        raw = proc.stdout.decode()
        self.assertTrue(raw.endswith("\n"), "output must be newline terminated")
        self.assertNotIn(", ", raw.split('"description"')[0])
        data = json.loads(raw)
        self.assertEqual(list(data.keys()), [key])
        return data[key]

    def signatures(self, path, line, col, project=None):
        args = ["signatures", path, line, col]
        if project:
            args += ["--project", project]
        found = self.load("signatures", *args)
        for item in found:
            self.assertEqual(
                sorted(item.keys()),
                ["description", "docstring", "index", "name", "params"],
            )
        return found

    def references(self, path, line, col, scope=None, project=None):
        args = ["references", path, line, col]
        if scope:
            args += ["--scope", scope]
        if project:
            args += ["--project", project]
        found = self.load("references", *args)
        for item in found:
            self.assertEqual(
                sorted(item.keys()),
                ["column", "is_definition", "line", "module_path"],
            )
        return found

    def tuples(self, references):
        return [
            (r["module_path"], r["line"], r["column"], r["is_definition"])
            for r in references
        ]

    def search(self, query, project=None):
        args = ["search", query]
        if project:
            args += ["--project", project]
        found = self.load("definitions", *args)
        for item in found:
            self.assertEqual(
                sorted(item.keys()),
                [
                    "column",
                    "description",
                    "full_name",
                    "line",
                    "module_path",
                    "name",
                    "type",
                ],
            )
        return found

    def names(self, path, all_scopes=False, project=None):
        args = ["names", path]
        if all_scopes:
            args.append("--all-scopes")
        if project:
            args += ["--project", project]
        found = self.load("definitions", *args)
        for item in found:
            self.assertEqual(
                sorted(item.keys()),
                [
                    "column",
                    "description",
                    "docstring",
                    "full_name",
                    "is_definition",
                    "line",
                    "module_path",
                    "name",
                    "type",
                ],
            )
            self.assertTrue(item["is_definition"])
        return found

    def definitions(self, command, path, line, col, project=None):
        args = [command, path, line, col]
        if project:
            args += ["--project", project]
        return self.load("definitions", *args)


class TestSignatures(Base):
    SRC = (
        "def greet(name, greeting='hi', *extra, loud: bool=False, **opts):\n"  # 1
        '    """Say hello."""\n'                                              # 2
        "    return greeting\n"                                               # 3
        "\n"                                                                  # 4
        "\n"                                                                  # 5
        "class Calculator:\n"                                                 # 6
        '    """A calculator."""\n'                                           # 7
        "\n"                                                                  # 8
        "    def __init__(self, value: int=0):\n"                             # 9
        "        self.value = value\n"                                        # 10
        "\n"                                                                  # 11
        "    def add(self, x: int, y: int=1) -> int:\n"                       # 12
        '        """Add numbers."""\n'                                        # 13
        "        return x + y\n"                                              # 14
        "\n"                                                                  # 15
        "\n"                                                                  # 16
        "c = Calculator(3)\n"                                                 # 17
        "c.add(1, 2)\n"                                                       # 18
        "greet('bob')\n"                                                      # 19
    )

    def test_params_rendering_and_docstring(self):
        path = self.write("a.py", self.SRC)
        got = self.signatures(path, 19, 6)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "greet")
        self.assertEqual(
            got[0]["params"],
            ["name", "greeting='hi'", "*extra", "loud: bool=False", "**opts"],
        )
        self.assertEqual(
            got[0]["description"],
            "def greet(name, greeting='hi', *extra, loud: bool=False, **opts)",
        )
        self.assertEqual(got[0]["docstring"], "Say hello.")
        self.assertEqual(got[0]["index"], 0)

    def test_self_excluded_and_return_annotation(self):
        path = self.write("a.py", self.SRC)
        got = self.signatures(path, 18, 6)
        self.assertEqual(got[0]["params"], ["x: int", "y: int=1"])
        self.assertEqual(got[0]["description"], "def add(x: int, y: int=1) -> int")
        self.assertEqual(got[0]["index"], 0)
        self.assertEqual(self.signatures(path, 18, 9)[0]["index"], 1)

    def test_class_signature_uses_init(self):
        path = self.write("a.py", self.SRC)
        got = self.signatures(path, 17, 15)
        self.assertEqual(got[0]["name"], "Calculator")
        self.assertEqual(got[0]["params"], ["value: int=0"])
        self.assertEqual(got[0]["index"], 0)

    def test_index_binding(self):
        src = (
            "def f(a, b, c=1):\n"
            "    pass\n"
            "def g(a, *args, **kw):\n"
            "    pass\n"
            "def h():\n"
            "    pass\n"
            "f(1, 2, 3)\n"       # 7
            "f(1, 2, 3, 4)\n"    # 8
            "f(c=9)\n"           # 9
            "g(1, 2, 3)\n"       # 10
            "g(1, zz=2)\n"       # 11
            "h()\n"              # 12
        )
        path = self.write("b.py", src)
        self.assertEqual(self.signatures(path, 7, 5)[0]["index"], 1)
        self.assertEqual(self.signatures(path, 8, 11)[0]["index"], None)
        self.assertEqual(self.signatures(path, 9, 5)[0]["index"], 2)
        self.assertEqual(self.signatures(path, 10, 8)[0]["index"], 1)
        self.assertEqual(self.signatures(path, 11, 8)[0]["index"], 2)
        self.assertEqual(self.signatures(path, 12, 2)[0]["index"], None)

    def test_outside_a_call_is_empty(self):
        path = self.write("a.py", self.SRC)
        self.assertEqual(self.signatures(path, 1, 1), [])
        self.assertEqual(self.signatures(path, 19, 12), [])

    def test_unclosed_call(self):
        path = self.write("a.py", "def f(a, b):\n    pass\n\nf(\n")
        got = self.signatures(path, 4, 2)
        self.assertEqual((got[0]["name"], got[0]["index"]), ("f", 0))

    def test_overloads_sorted(self):
        src = (
            "from typing import overload\n"
            "@overload\n"
            "def conv(x: int) -> int: ...\n"
            "@overload\n"
            "def conv(x: str) -> str: ...\n"
            "def conv(x):\n"
            "    return x\n"
            "conv(1)\n"
        )
        path = self.write("o.py", src)
        got = self.signatures(path, 8, 5)
        self.assertEqual([s["params"] for s in got], [["x: int"], ["x: str"]])

    def test_nested_call(self):
        src = "def outer(a, b):\n    pass\ndef inner(z):\n    pass\nouter(inner(1), 2)\n"
        path = self.write("n.py", src)
        self.assertEqual(self.signatures(path, 5, 12)[0]["name"], "inner")
        self.assertEqual(self.signatures(path, 5, 16)[0]["index"], 1)


class TestReferences(Base):
    LIB = (
        "VALUE = 1\n"                                  # 1
        "\n"                                           # 2
        "def helper(x):\n"                             # 3
        "    return x + VALUE\n"                       # 4
        "\n"                                           # 5
        "class Calculator:\n"                          # 6
        "    def __init__(self):\n"                    # 7
        "        self.total = 0\n"                     # 8
        "\n"                                           # 9
        "    def add(self, n):\n"                      # 10
        "        self.total = self.total + n\n"        # 11
        "        return self.total\n"                  # 12
    )
    APP = (
        "from lib import helper, Calculator\n"  # 1
        "\n"                                    # 2
        "def main():\n"                         # 3
        "    helper(1)\n"                       # 4
        "    c = Calculator()\n"                # 5
        "    return c.add(2)\n"                 # 6
    )

    def project(self):
        self.write("lib.py", self.LIB)
        self.write("app.py", self.APP)
        return self.dir

    def test_file_scope_is_the_default(self):
        self.project()
        got = self.references(os.path.join(self.dir, "app.py"), 4, 4)
        self.assertEqual(
            self.tuples(got), [("app.py", 1, 16, True), ("app.py", 4, 4, False)]
        )

    def test_project_scope(self):
        self.project()
        got = self.references(
            os.path.join(self.dir, "lib.py"), 3, 4, scope="project"
        )
        self.assertEqual(
            self.tuples(got),
            [
                ("app.py", 1, 16, True),
                ("app.py", 4, 4, False),
                ("lib.py", 3, 4, True),
            ],
        )

    def test_unrelated_same_name_is_ignored(self):
        self.write("lib.py", self.LIB)
        self.write("other.py", "def helper(y):\n    return y\nhelper(2)\n")
        got = self.references(
            os.path.join(self.dir, "other.py"), 1, 4, scope="project"
        )
        self.assertEqual(
            self.tuples(got), [("other.py", 1, 4, True), ("other.py", 3, 0, False)]
        )

    def test_attribute_references(self):
        self.project()
        got = self.references(os.path.join(self.dir, "lib.py"), 8, 13)
        self.assertEqual(
            self.tuples(got),
            [
                ("lib.py", 8, 13, True),
                ("lib.py", 11, 13, True),
                ("lib.py", 11, 26, False),
                ("lib.py", 12, 20, False),
            ],
        )

    def test_local_variable(self):
        path = self.write("v.py", "def f():\n    x = 1\n    return x\n")
        got = self.references(path, 2, 4)
        self.assertEqual(self.tuples(got), [("v.py", 2, 4, True), ("v.py", 3, 11, False)])

    def test_not_a_name_fails(self):
        path = self.write("v.py", "x = 1\n")
        proc = self.run_sith("references", path, 1, 2)
        self.assertEqual(proc.returncode, 1)


class TestSearch(Base):
    def project(self):
        self.write("z.py", "calc = 1\ndef calculate(): pass\nclass Calculator: pass\n")
        self.write("pkg/other.py", "CALC = 2\ndef recalculate(): pass\n")
        return self.dir

    def test_ranking_and_fields(self):
        root = self.project()
        got = self.search("calc", root)
        self.assertEqual(
            [(d["name"], d["module_path"], d["line"]) for d in got],
            [
                ("CALC", "pkg/other.py", 1),
                ("calc", "z.py", 1),
                ("calculate", "z.py", 2),
                ("Calculator", "z.py", 3),
                ("recalculate", "pkg/other.py", 2),
            ],
        )
        self.assertEqual(got[3]["type"], "class")
        self.assertEqual(got[3]["full_name"], "z.Calculator")

    def test_locals_are_not_searchable(self):
        root = self.dir
        self.write("z.py", "def outer():\n    inner_thing = 1\n    return inner_thing\n")
        self.assertEqual(self.search("inner_thing", root), [])

    def test_methods_are_searchable(self):
        root = self.dir
        self.write("z.py", "class C:\n    attr = 1\n    def meth(self):\n        loc = 2\n")
        got = [d["name"] for d in self.search("t", root)]
        self.assertIn("attr", got)
        self.assertIn("meth", got)
        self.assertNotIn("loc", got)

    def test_no_match(self):
        self.write("z.py", "x = 1\n")
        self.assertEqual(self.search("zzzz", self.dir), [])


class TestNames(Base):
    SRC = (
        "import os\n"            # 1
        "GLOBAL = 1\n"           # 2
        "\n"                     # 3
        "def f(a):\n"            # 4
        "    local = a\n"        # 5
        "    return local\n"     # 6
        "\n"                     # 7
        "class C:\n"             # 8
        "    attr = 2\n"         # 9
        "\n"                     # 10
        "    def m(self):\n"     # 11
        "        pass\n"         # 12
    )

    def test_module_level_only(self):
        path = self.write("a.py", self.SRC)
        got = self.names(path)
        self.assertEqual(
            [(d["name"], d["line"]) for d in got],
            [("os", 1), ("GLOBAL", 2), ("f", 4), ("C", 8)],
        )

    def test_all_scopes(self):
        path = self.write("a.py", self.SRC)
        got = [d["name"] for d in self.names(path, all_scopes=True)]
        for expected in ("os", "GLOBAL", "f", "a", "local", "C", "attr", "m"):
            self.assertIn(expected, got)

    def test_sorted_by_position(self):
        path = self.write("a.py", self.SRC)
        got = self.names(path, all_scopes=True)
        keys = [(d["line"], d["column"]) for d in got]
        self.assertEqual(keys, sorted(keys))


class TestStubs(Base):
    LIB = (
        "def build():\n"
        "    return 1\n"
        "\n"
        "CONFIG = None\n"
    )
    STUB = (
        "class Thing:\n"                            # 1
        "    name: str\n"                           # 2
        "    def go(self, times: int) -> bool: ...\n"  # 3
        "\n"                                        # 4
        "class Widget: ...\n"                       # 5
        "\n"                                        # 6
        "def build() -> Thing: ...\n"               # 7
        "\n"                                        # 8
        "CONFIG: Widget\n"                          # 9
    )

    def inline(self):
        self.write("lib.py", self.LIB)
        self.write("lib.pyi", self.STUB)

    def test_infer_uses_stub_return_type(self):
        self.inline()
        path = self.write("m.py", "from lib import build\nv = build()\n")
        got = self.definitions("infer", path, 2, 1)
        self.assertEqual(got[0]["name"], "Thing")
        self.assertEqual(got[0]["type"], "instance")

    def test_completion_uses_stub(self):
        self.inline()
        path = self.write("m.py", "import lib\nv = lib.build()\nv.\n")
        proc = self.run_sith("complete", path, 3, 2)
        names = [c["name"] for c in json.loads(proc.stdout.decode())["completions"]]
        self.assertIn("go", names)
        self.assertIn("name", names)

    def test_signatures_use_stub(self):
        self.inline()
        path = self.write("m.py", "import lib\nt = lib.build()\nt.go(1)\n")
        got = self.signatures(path, 3, 5)
        self.assertEqual(got[0]["params"], ["times: int"])
        self.assertEqual(got[0]["description"], "def go(times: int) -> bool")

    def test_goto_prefers_the_source(self):
        self.inline()
        path = self.write("m.py", "import lib\nlib.build\n")
        got = self.definitions("goto", path, 2, 5)
        self.assertEqual(got[0]["module_path"], "lib.py")

    def test_goto_falls_back_to_the_stub(self):
        self.inline()
        path = self.write("m.py", "import lib\nlib.Thing\n")
        got = self.definitions("goto", path, 2, 5)
        self.assertEqual(got[0]["module_path"], "lib.pyi")

    def test_stubs_directory(self):
        self.write("mod.py", "def pick(a, b):\n    return a\n")
        self.write("stubs/mod.pyi", "def pick(a: int, b: int) -> str: ...\n")
        path = self.write("m.py", "import mod\nmod.pick(1, 2)\n")
        got = self.signatures(path, 2, 9)
        self.assertEqual(got[0]["params"], ["a: int", "b: int"])
        inferred = self.definitions("infer", self.write("n.py", "import mod\nv = mod.pick(1, 2)\n"), 2, 1)
        self.assertEqual(inferred[0]["name"], "str")

    def test_stub_package(self):
        self.write("pkg/__init__.py", "def make():\n    return 1\n")
        self.write("stubs/pkg/__init__.pyi", "def make() -> str: ...\n")
        path = self.write("m.py", "import pkg\nv = pkg.make()\n")
        got = self.definitions("infer", path, 2, 1)
        self.assertEqual(got[0]["name"], "str")


class TestDynamicParams(Base):
    def test_infer_parameter_from_call_site(self):
        src = (
            "class Duck:\n"
            "    def quack(self):\n"
            "        return 1\n"
            "\n"
            "def use(bird):\n"
            "    return bird\n"
            "\n"
            "use(Duck())\n"
        )
        path = self.write("d.py", src)
        got = self.definitions("infer", path, 6, 12)
        self.assertEqual(got[0]["name"], "Duck")
        self.assertEqual(got[0]["type"], "instance")

    def test_signature_of_a_callback_parameter(self):
        src = (
            "def helper(a, b=2):\n"
            "    return a\n"
            "\n"
            "def run(cb):\n"
            "    cb(1)\n"
            "\n"
            "run(helper)\n"
        )
        path = self.write("c.py", src)
        got = self.signatures(path, 5, 7)
        self.assertEqual(got[0]["name"], "helper")
        self.assertEqual(got[0]["params"], ["a", "b=2"])

    def test_call_sites_in_other_files_are_ignored(self):
        self.write("caller.py", "from target import use\nuse(1)\n")
        path = self.write("target.py", "def use(value):\n    return value\n")
        got = self.definitions(
            "infer", path, 2, 11, project=self.dir
        )
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
