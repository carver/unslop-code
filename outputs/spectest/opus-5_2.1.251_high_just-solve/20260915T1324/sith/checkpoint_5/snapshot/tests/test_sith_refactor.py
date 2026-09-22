"""Spec conformance tests for rename, inline, extract-* and errors."""

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

    def ok(self, *args):
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        return proc.stdout.decode()

    def refactor(self, *args):
        raw = self.ok(*args)
        self.assertTrue(raw.endswith("\n"))
        data = json.loads(raw)
        self.assertEqual(sorted(data.keys()), ["changed_files", "renames"])
        return data

    def refused(self, *args):
        proc = self.run_sith(*args)
        self.assertEqual(proc.returncode, 1, proc.stdout.decode())
        self.assertEqual(proc.stdout.decode(), "", "no partial edits on failure")
        return proc.stderr.decode()

    def errors(self, path):
        raw = self.ok("errors", path)
        data = json.loads(raw)
        self.assertEqual(list(data.keys()), ["errors"])
        return data["errors"]


class TestRename(Base):
    def test_renames_definition_and_references(self):
        path = self.write("a.py", "def greet(n):\n    return n\n\n\ngreet(1)\n")
        data = self.refactor("rename", path, 1, 4, "--new-name", "hello")
        self.assertEqual(data["renames"], {})
        self.assertEqual(
            data["changed_files"],
            {"a.py": "def hello(n):\n    return n\n\n\nhello(1)\n"},
        )

    def test_renames_across_files(self):
        self.write("a.py", "def greet():\n    pass\n")
        self.write("b.py", "from a import greet\n\ngreet()\n")
        path = os.path.join(self.dir, "a.py")
        data = self.refactor(
            "rename", path, 1, 4, "--new-name", "hello", "--project", self.dir
        )
        self.assertEqual(
            data["changed_files"],
            {
                "a.py": "def hello():\n    pass\n",
                "b.py": "from a import hello\n\nhello()\n",
            },
        )

    def test_only_changed_files_are_listed(self):
        self.write("other.py", "def untouched():\n    pass\n")
        path = self.write("a.py", "def greet():\n    pass\n\n\ngreet()\n")
        data = self.refactor(
            "rename", path, 1, 4, "--new-name", "hello", "--project", self.dir
        )
        self.assertEqual(list(data["changed_files"]), ["a.py"])

    def test_same_spelling_elsewhere_is_left_alone(self):
        path = self.write(
            "a.py",
            "def one():\n    val = 1\n    return val\n\n\n"
            "def two():\n    val = 2\n    return val\n",
        )
        data = self.refactor("rename", path, 2, 4, "--new-name", "amount")
        new = data["changed_files"]["a.py"]
        self.assertIn("    amount = 1\n    return amount\n", new)
        self.assertIn("    val = 2\n    return val\n", new)

    def test_attribute_rename(self):
        path = self.write(
            "a.py",
            "class C:\n"
            "    def __init__(self):\n"
            "        self.count = 0\n"
            "\n"
            "    def bump(self):\n"
            "        return self.count\n",
        )
        data = self.refactor("rename", path, 3, 13, "--new-name", "total")
        new = data["changed_files"]["a.py"]
        self.assertIn("self.total = 0", new)
        self.assertIn("return self.total", new)

    def test_diff_output_is_plain_text(self):
        path = self.write("a.py", "x = 1\nprint(x)\n")
        raw = self.ok("rename", path, 1, 0, "--new-name", "y", "--diff")
        self.assertTrue(raw.startswith("---"))
        self.assertIn("@@", raw)
        self.assertIn("-x = 1\n", raw)
        self.assertIn("+y = 1\n", raw)
        with self.assertRaises(ValueError):
            json.loads(raw)

    def test_invalid_new_name(self):
        path = self.write("a.py", "x = 1\nprint(x)\n")
        self.refused("rename", path, 1, 0, "--new-name", "9bad")
        self.refused("rename", path, 1, 0, "--new-name", "class")
        self.refused("rename", path, 1, 0, "--new-name", "a b")

    def test_cursor_not_on_a_name(self):
        path = self.write("a.py", "x = 1\n")
        self.refused("rename", path, 1, 4, "--new-name", "y")

    def test_collision_is_refused(self):
        path = self.write("a.py", "def f():\n    a = 1\n    b = 2\n    return a + b\n")
        message = self.refused("rename", path, 2, 4, "--new-name", "b")
        self.assertIn("b", message)

    def test_module_rename_moves_the_file(self):
        self.write("foo.py", "VALUE = 1\n")
        path = self.write("main.py", "import foo\n\nprint(foo.VALUE)\n")
        data = self.refactor(
            "rename", path, 1, 7, "--new-name", "bar", "--project", self.dir
        )
        self.assertEqual(data["renames"], {"foo.py": "bar.py"})
        self.assertEqual(
            data["changed_files"], {"main.py": "import bar\n\nprint(bar.VALUE)\n"}
        )

    def test_module_rename_from_a_usage(self):
        self.write("foo.py", "VALUE = 1\n")
        path = self.write("main.py", "import foo\n\nprint(foo.VALUE)\n")
        data = self.refactor(
            "rename", path, 3, 6, "--new-name", "bar", "--project", self.dir
        )
        self.assertEqual(data["renames"], {"foo.py": "bar.py"})

    def test_package_rename_moves_the_directory(self):
        self.write(os.path.join("pkg", "__init__.py"), "X = 1\n")
        self.write(os.path.join("pkg", "util.py"), "def helper():\n    pass\n")
        path = self.write(
            "app.py", "import pkg\nfrom pkg.util import helper\n\nprint(pkg.X)\n"
        )
        data = self.refactor(
            "rename", path, 1, 8, "--new-name", "core", "--project", self.dir
        )
        self.assertEqual(data["renames"], {"pkg": "core"})
        self.assertEqual(
            data["changed_files"],
            {"app.py": "import core\nfrom core.util import helper\n\nprint(core.X)\n"},
        )

    def test_submodule_rename(self):
        self.write(os.path.join("pkg", "__init__.py"), "")
        self.write(os.path.join("pkg", "util.py"), "def helper():\n    pass\n")
        path = self.write(
            "app.py", "from pkg import util\n\nprint(util.helper())\n"
        )
        data = self.refactor(
            "rename", path, 1, 17, "--new-name", "tools", "--project", self.dir
        )
        self.assertEqual(data["renames"], {"pkg/util.py": "pkg/tools.py"})
        self.assertEqual(
            data["changed_files"],
            {"app.py": "from pkg import tools\n\nprint(tools.helper())\n"},
        )


class TestInline(Base):
    def test_inlines_and_deletes_the_definition(self):
        path = self.write("a.py", "n = 5\nprint(n + 1)\n")
        data = self.refactor("inline", path, 1, 0)
        self.assertEqual(data["changed_files"], {"a.py": "print(5 + 1)\n"})
        self.assertEqual(data["renames"], {})

    def test_parenthesises_only_when_precedence_needs_it(self):
        path = self.write("a.py", "a = b + c\nr = a * 2\ns = a\nt = f(a)\n")
        data = self.refactor("inline", path, 1, 0)
        self.assertEqual(
            data["changed_files"],
            {"a.py": "r = (b + c) * 2\ns = b + c\nt = f(b + c)\n"},
        )

    def test_unary_and_power_and_attribute(self):
        path = self.write("a.py", "a = b + c\nr = -a\ns = a ** 2\nt = a.x\n")
        data = self.refactor("inline", path, 1, 0)
        self.assertEqual(
            data["changed_files"],
            {"a.py": "r = -(b + c)\ns = (b + c) ** 2\nt = (b + c).x\n"},
        )

    def test_tuple_value_is_bracketed_inside_a_call(self):
        path = self.write("a.py", "p = 1, 2\nq = list(p)\n")
        data = self.refactor("inline", path, 1, 0)
        self.assertEqual(data["changed_files"], {"a.py": "q = list((1, 2))\n"})

    def test_function_definition_is_refused(self):
        path = self.write("a.py", "def f():\n    pass\n\n\nf()\n")
        message = self.refused("inline", path, 1, 4)
        self.assertIn("cannot inline a function/class definition", message)

    def test_class_definition_is_refused(self):
        path = self.write("a.py", "class C:\n    pass\n\n\nC()\n")
        message = self.refused("inline", path, 1, 6)
        self.assertIn("cannot inline a function/class definition", message)

    def test_unused_name_is_refused(self):
        path = self.write("a.py", "u = 1\n")
        message = self.refused("inline", path, 1, 0)
        self.assertIn("name has no references to inline", message)

    def test_diff_output(self):
        path = self.write("a.py", "n = 5\nprint(n)\n")
        raw = self.ok("inline", path, 1, 0, "--diff")
        self.assertTrue(raw.startswith("---"))
        self.assertIn("-n = 5\n", raw)
        self.assertIn("+print(5)\n", raw)


class TestExtractVariable(Base):
    def test_extracts_a_subexpression(self):
        path = self.write("a.py", "def f(w):\n    r = compute(w * 2) + 1\n")
        data = self.refactor(
            "extract-variable", path, 2, 16, "--until", "2:21", "--name", "doubled"
        )
        self.assertEqual(
            data["changed_files"],
            {"a.py": "def f(w):\n    doubled = w * 2\n    r = compute(doubled) + 1\n"},
        )

    def test_insertion_keeps_the_statement_indentation(self):
        path = self.write("a.py", "if True:\n    x = 1 + 2\n")
        data = self.refactor(
            "extract-variable", path, 2, 8, "--until", "2:13", "--name", "total"
        )
        self.assertEqual(
            data["changed_files"], {"a.py": "if True:\n    total = 1 + 2\n    x = total\n"}
        )

    def test_partial_expression_is_refused(self):
        path = self.write("a.py", "r = compute(1 * 2) + 1\n")
        message = self.refused(
            "extract-variable", path, 1, 4, "--until", "1:15", "--name", "got"
        )
        self.assertIn("selection is not a complete expression", message)

    def test_invalid_name(self):
        path = self.write("a.py", "r = 1 + 2\n")
        self.refused(
            "extract-variable", path, 1, 4, "--until", "1:9", "--name", "9bad"
        )


class TestExtractFunction(Base):
    def test_parameters_and_single_return(self):
        path = self.write(
            "a.py",
            "def main():\n    a = 1\n    b = 2\n    total = a + b\n    print(total)\n",
        )
        data = self.refactor(
            "extract-function", path, 4, 4, "--until", "4:17", "--name", "add"
        )
        new = data["changed_files"]["a.py"]
        self.assertIn("def add(a, b):\n    total = a + b\n    return total\n", new)
        self.assertIn("    total = add(a, b)\n", new)
        self.assertLess(new.index("def add"), new.index("def main"))

    def test_multiple_returns_are_tuple_unpacked(self):
        path = self.write(
            "a.py", "def main(n):\n    lo = n - 1\n    hi = n + 1\n    return lo + hi\n"
        )
        data = self.refactor(
            "extract-function", path, 2, 4, "--until", "3:14", "--name", "bounds"
        )
        new = data["changed_files"]["a.py"]
        self.assertIn("def bounds(n):", new)
        self.assertIn("    return lo, hi\n", new)
        self.assertIn("    lo, hi = bounds(n)\n", new)

    def test_no_return_value(self):
        path = self.write(
            "a.py", 'def main():\n    name = "x"\n    print(name)\n'
        )
        data = self.refactor(
            "extract-function", path, 3, 4, "--until", "3:15", "--name", "show"
        )
        new = data["changed_files"]["a.py"]
        self.assertIn("def show(name):\n    print(name)\n", new)
        self.assertNotIn("return", new)
        self.assertIn("    show(name)\n", new)

    def test_module_level_insertion(self):
        path = self.write("a.py", "a = 1\nb = 2\ntotal = a + b\nprint(total)\n")
        data = self.refactor(
            "extract-function", path, 3, 0, "--until", "3:13", "--name", "add"
        )
        new = data["changed_files"]["a.py"]
        self.assertTrue(
            new.startswith("a = 1\nb = 2\ndef add(a, b):\n    total = a + b\n")
        )
        self.assertIn("total = add(a, b)\n", new)

    def test_module_level_name_becomes_a_parameter(self):
        path = self.write("a.py", "SCALE = 3\n\n\ndef run(n):\n    out = n * SCALE\n    return out\n")
        data = self.refactor(
            "extract-function", path, 5, 4, "--until", "5:19", "--name", "scaled"
        )
        new = data["changed_files"]["a.py"]
        self.assertIn("def scaled(n, SCALE):", new)
        self.assertIn("    out = scaled(n, SCALE)\n", new)

    def test_method_extraction_sits_beside_the_method(self):
        path = self.write(
            "a.py",
            "class C:\n"
            "    def run(self, n):\n"
            "        acc = 0\n"
            "        for i in range(n):\n"
            "            acc += i\n"
            "        return acc\n",
        )
        data = self.refactor(
            "extract-function", path, 4, 8, "--until", "5:20", "--name", "loop"
        )
        new = data["changed_files"]["a.py"]
        self.assertIn("    def loop(n, acc):\n", new)
        self.assertIn("        return acc\n", new)
        self.assertIn("        acc = loop(n, acc)\n", new)
        self.assertLess(new.index("def loop"), new.index("def run"))

    def test_partial_statement_is_refused(self):
        path = self.write("a.py", "def main(n):\n    lo = n - 1\n    return lo\n")
        self.refused(
            "extract-function", path, 2, 9, "--until", "2:14", "--name", "bounds"
        )

    def test_invalid_name(self):
        path = self.write("a.py", "a = 1\n")
        self.refused(
            "extract-function", path, 1, 0, "--until", "1:5", "--name", "9bad"
        )


class TestErrors(Base):
    def test_clean_file(self):
        path = self.write("a.py", "x = 1\n")
        proc = self.run_sith("errors", path)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode(), '{"errors":[]}\n')

    def test_syntax_error_record(self):
        path = self.write("a.py", "def f():\nreturn 1\n")
        found = self.errors(path)
        self.assertEqual(len(found), 1)
        self.assertEqual(
            sorted(found[0]),
            ["column", "line", "message", "until_column", "until_line"],
        )
        self.assertEqual(found[0]["line"], 2)
        self.assertEqual(found[0]["column"], 0)
        self.assertIsInstance(found[0]["message"], str)
        self.assertTrue(found[0]["message"])

    def test_syntax_error_still_exits_zero(self):
        path = self.write("a.py", "x = (\n")
        proc = self.run_sith("errors", path)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(json.loads(proc.stdout.decode())["errors"]), 1)

    def test_missing_file_exits_one(self):
        proc = self.run_sith("errors", os.path.join(self.dir, "nope.py"))
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stderr.decode().strip())


if __name__ == "__main__":
    unittest.main()
