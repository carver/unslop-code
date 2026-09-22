"""Spec conformance tests for sith.py."""

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
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_sith(self, *args):
        proc = subprocess.run(
            [PY, SITH] + [str(a) for a in args], capture_output=True
        )
        return proc

    def complete(self, path, line, col, fuzzy=False):
        args = ["complete", path, line, col]
        if fuzzy:
            args.append("--fuzzy")
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        raw = proc.stdout.decode()
        self.assertTrue(raw.endswith("\n"), "output must be newline terminated")
        self.assertNotIn(" ", raw.split('"description"')[0].split('"complete"')[0])
        data = json.loads(raw)
        self.assertEqual(list(data.keys()), ["completions"])
        return data["completions"]

    def names(self, *a, **k):
        return [c["name"] for c in self.complete(*a, **k)]

    def by_name(self, completions):
        return {c["name"]: c for c in completions}


class TestOutputFormat(Base):
    def test_compact_json_and_fields(self):
        path = self.write("a.py", "p\n")
        proc = self.run_sith("complete", path, 1, 1)
        raw = proc.stdout.decode()
        self.assertTrue(raw.startswith('{"completions":[{"name":'))
        self.assertTrue(raw.endswith("}]}\n"))
        first = json.loads(raw)["completions"][0]
        self.assertEqual(
            sorted(first.keys()), ["complete", "description", "name", "type"]
        )

    def test_zero_completions_is_success(self):
        path = self.write("a.py", "zzzzzznotathing\n")
        proc = self.run_sith("complete", path, 1, 15)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode(), '{"completions":[]}\n')

    def test_example_from_spec(self):
        path = self.write("a.py", "p\n")
        got = self.by_name(self.complete(path, 1, 1))
        self.assertEqual(
            got["print"],
            {
                "name": "print",
                "complete": "rint",
                "type": "function",
                "description": "def print(...)",
            },
        )
        self.assertEqual(
            got["property"],
            {
                "name": "property",
                "complete": "roperty",
                "type": "class",
                "description": "class property",
            },
        )


class TestNameCompletion(Base):
    SRC = (
        "import os\n"                      # 1
        "GLOBAL_A = 1\n"                   # 2
        "\n"                               # 3
        "def outer(param_a, param_b=2):\n" # 4
        "    local_a = 1\n"                # 5
        "\n"                               # 6
        "    def inner(deep):\n"           # 7
        "        inner_v = 2\n"            # 8
        "        \n"                       # 9
        "    local_b = 3\n"                # 10
        "\n"                               # 11
        "GLOBAL_B = 2\n"                   # 12
    )

    def test_local_enclosing_global_builtin(self):
        path = self.write("a.py", self.SRC)
        names = set(self.names(path, 9, 8))
        for expected in (
            "inner_v", "deep", "local_a", "local_b", "param_a",
            "outer", "inner", "GLOBAL_A", "os", "print",
        ):
            self.assertIn(expected, names)
        self.assertNotIn("GLOBAL_B", names)  # defined after the cursor

    def test_module_level_visibility_is_positional(self):
        path = self.write("a.py", self.SRC)
        names = set(self.names(path, 3, 0))
        self.assertIn("GLOBAL_A", names)
        self.assertNotIn("GLOBAL_B", names)
        self.assertNotIn("outer", names)
        self.assertNotIn("local_a", names)

    def test_def_visible_from_its_own_line(self):
        path = self.write("a.py", "def foo():\n    pass\nfo\n")
        self.assertIn("foo", self.names(path, 3, 2))
        self.assertIn("foo", self.names(path, 1, 10))

    def test_prefix_is_case_insensitive_and_complete_is_char_count(self):
        path = self.write("a.py", "PR\n")
        got = self.by_name(self.complete(path, 1, 2))
        self.assertIn("print", got)
        self.assertEqual(got["print"]["complete"], "int")

    def test_prefix_scans_backwards_only(self):
        path = self.write("a.py", "prinXYZ\n")
        got = self.by_name(self.complete(path, 1, 3))
        self.assertEqual(got["print"]["complete"], "nt")

    def test_types_and_descriptions(self):
        src = (
            "import os\n"
            "from os import getcwd\n"
            "count = 5\n"
            "text = 'hi'\n"
            "stuff = [1]\n"
            "unknown = getcwd()\n"
            "class Thing:\n"
            "    pass\n"
            "obj = Thing()\n"
            "def fn(arg):\n"
            "    ar\n"
        )
        path = self.write("a.py", src)
        got = self.by_name(self.complete(path, 11, 6))
        self.assertEqual(got["arg"]["type"], "param")
        got = self.by_name(self.complete(path, 11, 4))
        self.assertEqual((got["os"]["type"], got["os"]["description"]), ("module", "module os"))
        self.assertEqual(got["getcwd"]["type"], "function")
        self.assertEqual(got["getcwd"]["description"], "def getcwd(...)")
        self.assertEqual(got["count"]["description"], "instance of int")
        self.assertEqual(got["text"]["description"], "instance of str")
        self.assertEqual(got["stuff"]["description"], "instance of list")
        self.assertEqual(got["unknown"]["type"], "statement")
        self.assertEqual(got["unknown"]["description"], "statement")
        self.assertEqual((got["Thing"]["type"], got["Thing"]["description"]), ("class", "class Thing"))
        self.assertEqual((got["obj"]["type"], got["obj"]["description"]), ("instance", "instance of Thing"))
        self.assertEqual((got["fn"]["type"], got["fn"]["description"]), ("function", "def fn(...)"))

    def test_empty_prefix_returns_names_and_keywords(self):
        path = self.write("a.py", "value = 1\n\n")
        comps = self.complete(path, 2, 0)
        names = {c["name"] for c in comps}
        self.assertIn("value", names)
        self.assertIn("print", names)
        self.assertIn("lambda", names)


class TestOrdering(Base):
    def test_group_order(self):
        src = "zeta = 1\n_priv = 2\n__dun__ = 3\nAlpha = 4\n\n"
        path = self.write("a.py", src)
        comps = self.complete(path, 5, 0)

        def group(c):
            n = c["name"]
            if c["type"] == "keyword":
                return 3
            if n.startswith("__") and n.endswith("__"):
                return 2
            if n.startswith("_"):
                return 1
            return 0

        groups = [group(c) for c in comps]
        self.assertEqual(groups, sorted(groups))
        for g in range(4):
            sub = [c["name"].lower() for c in comps if group(c) == g]
            self.assertEqual(sub, sorted(sub))
        self.assertIn("Alpha", [c["name"] for c in comps])
        idx = {c["name"]: i for i, c in enumerate(comps)}
        self.assertLess(idx["zeta"], idx["_priv"])
        self.assertLess(idx["_priv"], idx["__dun__"])
        self.assertLess(idx["__dun__"], idx["while"])


class TestAttributes(Base):
    def test_module_public_only(self):
        path = self.write("a.py", "import os\nos.\n")
        comps = self.complete(path, 2, 3)
        names = [c["name"] for c in comps]
        self.assertIn("getcwd", names)
        self.assertIn("path", names)
        self.assertFalse([n for n in names if n.startswith("_")])
        got = self.by_name(comps)
        self.assertEqual(got["path"]["type"], "module")
        self.assertEqual(got["getcwd"]["type"], "function")

    def test_module_prefix_filter(self):
        path = self.write("a.py", "import os\nos.getcw\n")
        self.assertEqual(
            self.complete(path, 2, 8),
            [
                {"name": "getcwd", "complete": "d", "type": "function", "description": "def getcwd(...)"},
                {"name": "getcwdb", "complete": "db", "type": "function", "description": "def getcwdb(...)"},
            ],
        )

    def test_class_and_instance(self):
        src = (
            "class Animal:\n"
            "    kind = 'generic'\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "        self.legs = 4\n"
            "    def speak(self):\n"
            "        return 1\n"
            "\n"
            "class Dog(Animal):\n"
            "    def fetch(self):\n"
            "        pass\n"
            "\n"
            "d = Dog('rex')\n"
            "d.\n"
            "Dog.\n"
        )
        path = self.write("a.py", src)
        inst = set(self.names(path, 14, 2))
        self.assertEqual(inst, {"fetch", "speak", "kind", "name", "legs", "__init__"})
        cls = set(self.names(path, 15, 4))
        self.assertEqual(cls, {"fetch", "speak", "kind", "__init__"})
        got = self.by_name(self.complete(path, 14, 2))
        self.assertEqual(got["legs"]["description"], "instance of int")
        self.assertEqual(got["kind"]["description"], "instance of str")
        self.assertEqual(got["speak"]["type"], "function")

    def test_self_inside_method(self):
        src = (
            "class Base:\n"
            "    def __init__(self):\n"
            "        self.base_attr = []\n"
            "    def helper(self):\n"
            "        pass\n"
            "class Child(Base):\n"
            "    def run(self):\n"
            "        self.\n"
        )
        path = self.write("a.py", src)
        self.assertEqual(
            set(self.names(path, 8, 13)),
            {"run", "helper", "base_attr", "__init__"},
        )

    def test_literals(self):
        path = self.write("a.py", "'abc'.\n[1].\n{'a':1}.\n{1,2}.\n")
        self.assertIn("upper", self.names(path, 1, 6))
        self.assertIn("append", self.names(path, 2, 4))
        self.assertIn("keys", self.names(path, 3, 8))
        self.assertIn("union", self.names(path, 4, 6))

    def test_inferred_literal_variable(self):
        path = self.write("a.py", "text = 'abc'\ntext.up\n")
        self.assertEqual(self.names(path, 2, 7), ["upper"])

    def test_no_keywords_after_dot(self):
        path = self.write("a.py", "import os\nos.\n")
        types = {c["type"] for c in self.complete(path, 2, 3)}
        self.assertNotIn("keyword", types)
        path2 = self.write("b.py", "import os\nos.i\n")
        self.assertNotIn("if", self.names(path2, 2, 4))
        self.assertNotIn("import", self.names(path2, 2, 4))

    def test_chained_attributes(self):
        path = self.write("a.py", "import os\nos.path.jo\n")
        self.assertEqual(self.names(path, 2, 10), ["join"])

    def test_empty_prefix_after_dot_returns_all(self):
        path = self.write("a.py", "x = {}\nx.\n")
        names = self.names(path, 2, 2)
        self.assertIn("keys", names)
        self.assertIn("__len__", names)
        for c in self.complete(path, 2, 2):
            self.assertEqual(c["complete"], c["name"])


class TestKeywords(Base):
    def test_keyword_entry(self):
        path = self.write("a.py", "wh\n")
        self.assertEqual(
            self.complete(path, 1, 2),
            [{"name": "while", "complete": "ile", "type": "keyword", "description": "while"}],
        )

    def test_all_keywords_present(self):
        import keyword

        path = self.write("a.py", "\n")
        names = self.names(path, 1, 0)
        for kw in keyword.kwlist:
            self.assertIn(kw, names)


class TestFuzzy(Base):
    def test_subsequence(self):
        path = self.write("a.py", "def alpha_beta_gamma():\n    pass\nabg\n")
        self.assertEqual(self.names(path, 3, 3, fuzzy=True), ["alpha_beta_gamma"])
        self.assertEqual(self.names(path, 3, 3, fuzzy=False), [])

    def test_fuzzy_is_case_insensitive(self):
        path = self.write("a.py", "def AlphaBeta():\n    pass\nab\n")
        self.assertIn("AlphaBeta", self.names(path, 3, 2, fuzzy=True))

    def test_fuzzy_attributes(self):
        path = self.write("a.py", "import os\nos.gcwd\n")
        self.assertEqual(self.names(path, 2, 7, fuzzy=True), ["getcwd", "getcwdb"])

    def test_fuzzy_order_preserved(self):
        path = self.write("a.py", "def ba():\n    pass\ndef ab():\n    pass\nab\n")
        self.assertEqual(self.names(path, 5, 2, fuzzy=True)[:2], ["ab", "abs"])


class TestStarImports(Base):
    def test_star_from_stdlib(self):
        path = self.write("a.py", "from os import *\ngetcw\n")
        self.assertIn("getcwd", self.names(path, 2, 5))

    def test_star_from_local_module(self):
        self.write("mylib.py", "CONST = 1\ndef mylib_func():\n    pass\nclass MyThing:\n    pass\n_hidden = 2\n")
        path = self.write("a.py", "from mylib import *\nMy\n")
        comps = self.by_name(self.complete(path, 2, 2))
        self.assertIn("MyThing", comps)
        self.assertEqual(comps["MyThing"]["type"], "class")
        names = self.names(path, 2, 0)
        self.assertIn("mylib_func", names)
        self.assertIn("CONST", names)
        self.assertNotIn("_hidden", names)

    def test_import_local_module_attributes(self):
        self.write("mylib.py", "def mylib_func():\n    pass\n")
        path = self.write("a.py", "import mylib\nmylib.\n")
        self.assertIn("mylib_func", self.names(path, 2, 6))


class TestErrors(Base):
    def assert_fails(self, *args):
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stderr.decode().strip())
        self.assertEqual(proc.stdout.decode(), "")

    def test_missing_file(self):
        self.assert_fails("complete", os.path.join(self.dir, "nope.py"), 1, 0)

    def test_directory(self):
        self.assert_fails("complete", self.dir, 1, 0)

    def test_not_utf8(self):
        path = os.path.join(self.dir, "bad.py")
        with open(path, "wb") as fh:
            fh.write(b"x = '\xff\xfe'\n")
        self.assert_fails("complete", path, 1, 0)

    def test_line_out_of_range(self):
        path = self.write("a.py", "x = 1\n")
        self.assert_fails("complete", path, 50, 0)

    def test_col_out_of_range(self):
        path = self.write("a.py", "x = 1\n")
        self.assert_fails("complete", path, 1, 50)

    def test_col_at_end_of_line_is_valid(self):
        path = self.write("a.py", "x = 1\n")
        self.complete(path, 1, 5)


class TestSyntaxTolerance(Base):
    def test_broken_file_still_completes(self):
        src = (
            "def good_one():\n"
            "    pass\n"
            "\n"
            "this is not python !!!\n"
            "\n"
            "def good_two():\n"
            "    pass\n"
            "\n"
            "good_\n"
        )
        path = self.write("a.py", src)
        self.assertEqual(self.names(path, 9, 5), ["good_one", "good_two"])

    def test_incomplete_attribute_line(self):
        path = self.write("a.py", "import os\n\ndef f():\n    value = 1\n    os.\n")
        self.assertIn("getcwd", self.names(path, 5, 7))

    def test_incomplete_def(self):
        path = self.write("a.py", "def broken(:\n    inner_value = 1\n    inner_\n")
        self.assertEqual(self.names(path, 3, 10), ["inner_value"])

    def test_unclosed_bracket(self):
        path = self.write("a.py", "data = [1, 2\nname = 'x'\nna\n")
        self.assertIn("name", self.names(path, 3, 2))

    def test_empty_file(self):
        path = self.write("a.py", "")
        self.assertIn("print", self.names(path, 1, 0))


class NavBase(Base):
    FIELDS = [
        "column",
        "description",
        "docstring",
        "full_name",
        "line",
        "module_path",
        "name",
        "type",
    ]

    def navigate(self, command, path, line, col, project=None):
        args = [command, path, line, col]
        if project:
            args += ["--project", project]
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        raw = proc.stdout.decode()
        self.assertTrue(raw.endswith("\n"), "output must be newline terminated")
        data = json.loads(raw)
        self.assertEqual(list(data.keys()), ["definitions"])
        for item in data["definitions"]:
            self.assertEqual(sorted(item.keys()), self.FIELDS)
        return data["definitions"]

    def goto(self, path, line, col, project=None):
        return self.navigate("goto", path, line, col, project)

    def infer(self, path, line, col, project=None):
        return self.navigate("infer", path, line, col, project)

    def one(self, definitions):
        self.assertEqual(len(definitions), 1, definitions)
        return definitions[0]


class TestDefinitionOutput(NavBase):
    SRC = (
        "import os\n"                     # 1
        "\n"                              # 2
        "\n"                              # 3
        "def helper(value):\n"            # 4
        "    return value\n"              # 5
        "\n"                              # 6
        "\n"                              # 7
        "class Calculator:\n"             # 8
        "    def add(self, a):\n"         # 9
        "        return a\n"              # 10
        "\n"                              # 11
        "\n"                              # 12
        "calc = Calculator()\n"           # 13
    )

    def test_compact_json(self):
        path = self.write("example.py", self.SRC)
        proc = self.run_sith("goto", path, 13, 8)
        raw = proc.stdout.decode()
        self.assertTrue(raw.startswith('{"definitions":[{"name":'))
        self.assertTrue(raw.endswith("}]}\n"))

    def test_spec_example_shape(self):
        path = self.write("example.py", self.SRC)
        self.assertEqual(
            self.one(self.goto(path, 13, 8)),
            {
                "name": "Calculator",
                "type": "class",
                "full_name": "example.Calculator",
                "module_path": "example.py",
                "line": 8,
                "column": 6,
                "description": "class Calculator",
                "docstring": "",
            },
        )

    def test_columns_point_at_the_identifier(self):
        path = self.write("example.py", self.SRC)
        self.assertEqual(self.one(self.goto(path, 5, 12))["column"], 11)  # param
        self.assertEqual(self.one(self.goto(path, 4, 5))["column"], 4)  # def name
        self.assertEqual(self.one(self.goto(path, 9, 9))["column"], 8)  # method

    def test_nested_full_name(self):
        path = self.write("example.py", self.SRC)
        got = self.one(self.goto(path, 9, 9))
        self.assertEqual(got["full_name"], "example.Calculator.add")
        self.assertEqual(got["description"], "def add(self, a)")

    def test_docstrings(self):
        src = (
            "class Thing:\n"
            '    """Doc for Thing."""\n'
            "    def go(self):\n"
            '        """Doc for go."""\n'
            "        return 1\n"
            "t = Thing()\n"
        )
        path = self.write("a.py", src)
        self.assertEqual(self.one(self.goto(path, 6, 6))["docstring"], "Doc for Thing.")
        self.assertEqual(self.one(self.goto(path, 3, 9))["docstring"], "Doc for go.")


class TestGoto(NavBase):
    def test_assignment(self):
        path = self.write("a.py", "value = 41\nvalue\n")
        got = self.one(self.goto(path, 2, 2))
        self.assertEqual((got["name"], got["line"], got["column"]), ("value", 1, 0))
        self.assertEqual(got["description"], "41")

    def test_import_binding(self):
        path = self.write("a.py", "import os\nfrom os import getcwd\nos\ngetcwd\n")
        mod = self.one(self.goto(path, 3, 1))
        self.assertEqual((mod["line"], mod["column"], mod["type"]), (1, 7, "module"))
        self.assertEqual(mod["description"], "import os")
        fn = self.one(self.goto(path, 4, 3))
        self.assertEqual((fn["line"], fn["column"]), (2, 15))
        self.assertEqual(fn["description"], "from os import getcwd")

    def test_aliased_import_column(self):
        path = self.write("a.py", "import os.path as p\np\n")
        self.assertEqual(self.one(self.goto(path, 2, 1))["column"], 18)

    def test_self_attribute(self):
        src = (
            "class Thing:\n"
            "    def __init__(self):\n"
            "        self.total = 0\n"
            "    def show(self):\n"
            "        return self.total\n"
        )
        path = self.write("a.py", src)
        got = self.one(self.goto(path, 5, 24))
        self.assertEqual((got["name"], got["line"], got["column"]), ("total", 3, 13))
        self.assertEqual(got["full_name"], "a.Thing.total")

    def test_method_through_instance(self):
        src = (
            "class Thing:\n"
            "    def go(self):\n"
            "        return 1\n"
            "t = Thing()\n"
            "t.go\n"
        )
        path = self.write("a.py", src)
        got = self.one(self.goto(path, 5, 3))
        self.assertEqual((got["name"], got["type"], got["line"]), ("go", "function", 2))

    def test_conditional_assignments_return_both_sorted(self):
        src = (
            "import random\n"
            "if random.random():\n"
            "    thing = 1\n"
            "else:\n"
            "    thing = 'x'\n"
            "thing\n"
        )
        path = self.write("a.py", src)
        got = self.goto(path, 6, 3)
        self.assertEqual([d["line"] for d in got], [3, 5])
        self.assertEqual([d["description"] for d in got], ["1", "'x'"])

    def test_rebinding_keeps_only_the_live_definition(self):
        path = self.write("a.py", "thing = 1\nthing = 'x'\nthing\n")
        self.assertEqual([d["line"] for d in self.goto(path, 3, 3)], [2])

    def test_unknown_name_is_empty(self):
        path = self.write("a.py", "nowhere\n")
        self.assertEqual(self.goto(path, 1, 3), [])

    def test_cursor_on_definition_itself(self):
        path = self.write("a.py", "def foo():\n    pass\n")
        self.assertEqual(self.one(self.goto(path, 1, 5))["line"], 1)


class TestInfer(NavBase):
    def builtin(self, definitions, name):
        got = self.one(definitions)
        self.assertEqual(
            got,
            {
                "name": name,
                "type": "instance",
                "full_name": "builtins." + name,
                "module_path": "",
                "line": 0,
                "column": 0,
                "description": "instance of " + name,
                "docstring": "",
            },
        )

    def test_literals(self):
        path = self.write("a.py", "x = 42\ny = 'hi'\nz = [1]\nw = None\n")
        self.builtin(self.infer(path, 1, 5), "int")
        self.builtin(self.infer(path, 2, 6), "str")
        self.builtin(self.infer(path, 1, 0), "int")
        self.builtin(self.infer(path, 2, 0), "str")
        self.builtin(self.infer(path, 3, 0), "list")
        self.builtin(self.infer(path, 4, 0), "None")

    def test_assignment_chain(self):
        path = self.write("a.py", "a = 1\nb = a\nc = b\nc\n")
        self.builtin(self.infer(path, 4, 1), "int")

    def test_class_instantiation(self):
        src = "class Thing:\n    pass\nt = Thing()\nt\n"
        path = self.write("a.py", src)
        got = self.one(self.infer(path, 4, 1))
        self.assertEqual(got["type"], "instance")
        self.assertEqual(got["name"], "Thing")
        self.assertEqual(got["description"], "instance of Thing")
        self.assertEqual((got["line"], got["column"]), (1, 6))

    def test_function_return_type(self):
        src = "def make():\n    return 'x'\nvalue = make()\nvalue\n"
        path = self.write("a.py", src)
        self.builtin(self.infer(path, 4, 1), "str")

    def test_multiple_return_paths(self):
        src = (
            "def pick(flag):\n"
            "    if flag:\n"
            "        return 1\n"
            "    return 'x'\n"
            "value = pick(1)\n"
            "value\n"
        )
        path = self.write("a.py", src)
        names = sorted(d["name"] for d in self.infer(path, 6, 1))
        self.assertEqual(names, ["int", "str"])

    def test_no_return_is_none(self):
        src = "def nop():\n    pass\ndef bare():\n    return\na = nop()\nb = bare()\n"
        path = self.write("a.py", src)
        self.builtin(self.infer(path, 5, 0), "None")
        self.builtin(self.infer(path, 6, 0), "None")

    def test_attribute_from_instance_state(self):
        src = (
            "class Thing:\n"
            "    def __init__(self):\n"
            "        self.label = 'x'\n"
            "t = Thing()\n"
            "t.label\n"
        )
        path = self.write("a.py", src)
        self.builtin(self.infer(path, 5, 7), "str")

    def test_bare_function_name(self):
        path = self.write("a.py", "def foo(a):\n    return 1\nfoo\n")
        got = self.one(self.infer(path, 3, 2))
        self.assertEqual(got["type"], "function")
        self.assertEqual(got["description"], "def foo(a)")
        self.assertEqual(got, self.one(self.goto(path, 3, 2)))

    def test_unresolved_is_empty(self):
        path = self.write("a.py", "def f(x):\n    return x\n")
        self.assertEqual(self.infer(path, 2, 12), [])


class TestDataclasses(NavBase):
    SRC = (
        "import dataclasses\n"
        "from dataclasses import dataclass as dc\n"
        "\n"
        "\n"
        "@dataclasses.dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "    y: str = 'a'\n"
        "\n"
        "\n"
        "@dc(frozen=True)\n"
        "class Frozen:\n"
        "    p: Point\n"
        "\n"
        "\n"
        "point = Point(1)\n"
        "frozen = Frozen(point)\n"
        "point.\n"
        "point.x\n"
        "frozen.p\n"
    )

    def test_fields_complete_on_instance(self):
        path = self.write("a.py", self.SRC)
        self.assertEqual(set(self.names(path, 18, 6)), {"x", "y"})

    def test_field_inference(self):
        path = self.write("a.py", self.SRC)
        self.assertEqual(self.one(self.infer(path, 19, 7))["name"], "int")

    def test_frozen_dataclass_field(self):
        path = self.write("a.py", self.SRC)
        got = self.one(self.infer(path, 20, 8))
        self.assertEqual((got["name"], got["type"]), ("Point", "instance"))


class TestNarrowing(NavBase):
    SRC = (
        "class Dog:\n"                    # 1
        "    def bark(self):\n"           # 2
        "        return 1\n"              # 3
        "class Cat:\n"                    # 4
        "    def meow(self):\n"           # 5
        "        return 1\n"              # 6
        "def pick(flag):\n"               # 7
        "    if flag:\n"                  # 8
        "        return Dog()\n"          # 9
        "    return Cat()\n"              # 10
        "def use(flag):\n"                # 11
        "    animal = pick(flag)\n"       # 12
        "    if isinstance(animal, Dog):\n"  # 13
        "        animal\n"                # 14
        "        animal.\n"               # 15
        "    animal\n"                    # 16
    )

    def test_isinstance_narrows_infer(self):
        path = self.write("a.py", self.SRC)
        got = self.one(self.infer(path, 14, 12))
        self.assertEqual(got["name"], "Dog")
        self.assertEqual(
            sorted(d["name"] for d in self.infer(path, 16, 8)), ["Cat", "Dog"]
        )

    def test_isinstance_narrows_completion(self):
        path = self.write("a.py", self.SRC)
        self.assertEqual(self.names(path, 15, 15), ["bark"])

    def test_union_completion_shows_every_type(self):
        path = self.write("a.py", self.SRC + "    animal.\n")
        self.assertEqual(set(self.names(path, 17, 11)), {"bark", "meow"})

    def test_is_none_narrowing(self):
        src = (
            "def maybe(flag):\n"
            "    if flag:\n"
            "        return 'x'\n"
            "    return None\n"
            "value = maybe(1)\n"
            "if value is None:\n"
            "    value\n"
            "else:\n"
            "    value\n"
        )
        path = self.write("a.py", src)
        self.assertEqual(self.one(self.infer(path, 7, 6))["name"], "None")
        self.assertEqual(self.one(self.infer(path, 9, 6))["name"], "str")
        self.assertEqual(
            sorted(d["name"] for d in self.infer(path, 5, 2)), ["None", "str"]
        )


class TestCrossFile(NavBase):
    LIB = (
        '"""Library."""\n'
        "\n"
        "\n"
        "class Helper:\n"
        '    """A helper."""\n'
        "    def run(self):\n"
        "        return 3\n"
        "\n"
        "\n"
        "def make():\n"
        "    return Helper()\n"
    )

    def test_infer_follows_imports(self):
        self.write("mylib.py", self.LIB)
        path = self.write("a.py", "from mylib import Helper\nh = Helper()\nh\n")
        got = self.one(self.infer(path, 3, 1))
        self.assertEqual(got["module_path"], "mylib.py")
        self.assertEqual(got["full_name"], "mylib.Helper")
        self.assertEqual((got["line"], got["column"]), (4, 6))
        self.assertEqual(got["docstring"], "A helper.")

    def test_goto_stops_at_the_import(self):
        self.write("mylib.py", self.LIB)
        path = self.write("a.py", "from mylib import Helper\nh = Helper()\n")
        got = self.one(self.goto(path, 2, 6))
        self.assertEqual((got["module_path"], got["line"]), ("a.py", 1))

    def test_return_type_across_modules(self):
        self.write("mylib.py", self.LIB)
        path = self.write("a.py", "import mylib\nvalue = mylib.make()\nvalue\n")
        got = self.one(self.infer(path, 3, 1))
        self.assertEqual((got["name"], got["type"]), ("Helper", "instance"))
        self.assertEqual(got["module_path"], "mylib.py")

    def test_project_root_option(self):
        os.mkdir(os.path.join(self.dir, "pkg"))
        path = self.write(os.path.join("pkg", "mod.py"), "class T:\n    pass\nt = T()\n")
        got = self.one(self.goto(path, 3, 5, project=self.dir))
        self.assertEqual(got["module_path"], "pkg/mod.py")
        got = self.one(self.goto(path, 3, 5))
        self.assertEqual(got["module_path"], "mod.py")


class TestNavigationErrors(NavBase):
    def assert_fails(self, *args):
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stderr.decode().strip())
        self.assertEqual(proc.stdout.decode(), "")

    def test_not_on_a_name(self):
        path = self.write("a.py", "value = 1 + 2\n")
        self.assert_fails("goto", path, 1, 6)
        self.assert_fails("infer", path, 1, 6)

    def test_keyword_is_not_a_name(self):
        path = self.write("a.py", "def foo():\n    pass\n")
        self.assert_fails("goto", path, 1, 1)
        self.assert_fails("infer", path, 1, 1)

    def test_missing_file_and_ranges(self):
        path = self.write("a.py", "x = 1\n")
        self.assert_fails("goto", os.path.join(self.dir, "nope.py"), 1, 0)
        self.assert_fails("infer", path, 99, 0)
        self.assert_fails("goto", path, 1, 99)

    def test_empty_result_is_success(self):
        path = self.write("a.py", "missing_name\n")
        proc = self.run_sith("infer", path, 1, 3)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode(), '{"definitions":[]}\n')


if __name__ == "__main__":
    unittest.main(verbosity=2)
