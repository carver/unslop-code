"""End-to-end checks of `.pyi` stubs and of parameters typed from call sites."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SHAPES = '''class Box:
    """A box."""

    def __init__(self, width):
        self.width = width

    def grow(self, amount):
        return self


def label(box, prefix):
    return prefix
'''

SHAPES_STUB = """class Box:
    width: int
    def __init__(self, width: int) -> None: ...
    def grow(self, amount: float) -> Box: ...

def label(box: Box, prefix: str) -> str: ...
"""


def run(command, *arguments):
    """Invoke the CLI and return (exit code, parsed payload, stderr)."""
    result = subprocess.run(
        [sys.executable, "sith.py", command, *[str(item) for item in arguments]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, payload, result.stderr


class StubTest(unittest.TestCase):
    """Fixtures are written to a temporary project shared by all tests."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._directory.name)
        cls.shapes = cls.write("shapes.py", SHAPES)
        cls.write("shapes.pyi", SHAPES_STUB)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    @classmethod
    def write(cls, name, text):
        path = cls.workspace / name
        (cls.workspace / name).parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def payload(self, command, key, path, *arguments):
        code, found, error = run(command, path, *arguments, "--project", self.workspace)
        self.assertEqual(code, 0, error)
        return found[key]

    def summary(self, command, path, line, column, *flags):
        """The (name, module_path, line) of each definition found."""
        found = self.payload(command, "definitions", path, line, column, *flags)
        return [(item["name"], item["module_path"], item["line"]) for item in found]

    def test_signatures_come_from_the_stub_beside_the_source(self):
        path = self.write("call.py", "from shapes import label\nlabel(")
        self.assertEqual(
            self.payload("signatures", "signatures", path, 2, 6),
            [
                {
                    "name": "label",
                    "params": ["box: Box", "prefix: str"],
                    "index": 0,
                    "description": "def label(box: Box, prefix: str) -> str",
                    "docstring": "",
                }
            ],
        )

    def test_a_stub_borrows_the_docstring_of_the_source_it_types(self):
        path = self.write("doc.py", "from shapes import Box\nBox(")
        self.assertEqual(
            self.payload("signatures", "signatures", path, 2, 4)[0]["docstring"], "A box."
        )

    def test_return_types_come_from_the_stub(self):
        path = self.write("returns.py", "from shapes import Box, label\n"
                                        "name = label(Box(1), 'a')\n"
                                        "grown = Box(1).grow(2)\n")
        self.assertEqual(self.summary("infer", path, 2, 1), [("str", "", 0)])
        self.assertEqual(self.summary("infer", path, 3, 2), [("Box", "shapes.py", 1)])

    def test_attribute_types_come_from_the_stub_but_lead_to_the_source(self):
        path = self.write("attribute.py", "from shapes import Box\nseen = Box(1).width\n")
        self.assertEqual(self.summary("infer", path, 2, 15), [("int", "", 0)])
        self.assertEqual(self.summary("goto", path, 2, 15), [("width", "shapes.py", 5)])

    def test_goto_reaches_the_source_rather_than_the_stub(self):
        path = self.write("goto.py", "from shapes import label\nlabel(None, 'a')\n")
        self.assertEqual(
            self.summary("goto", path, 2, 2, "--follow-imports"), [("label", "shapes.py", 11)]
        )

    def test_a_stubs_directory_types_a_module_of_its_own_name(self):
        self.write("widget.py", "def render(node):\n    return node\n")
        self.write("stubs/widget.pyi", "def render(node: int) -> bytes: ...\n")
        path = self.write("widgets.py", "import widget\n\ndrawn = widget.render(1)\n")
        self.assertEqual(self.summary("infer", path, 3, 1), [("bytes", "", 0)])

    def test_a_module_the_stubs_hold_alone_is_read_from_its_stub(self):
        self.write("stubs/webclient.pyi", "class Response:\n"
                                          "    status: int\n"
                                          "\n"
                                          "def fetch(url: str) -> Response: ...\n")
        path = self.write("fetcher.py", "from webclient import fetch\n"
                                        "answer = fetch('http://x')\n"
                                        "code = answer.status\n")
        self.assertEqual(
            self.summary("infer", path, 2, 1), [("Response", "stubs/webclient.pyi", 1)]
        )
        self.assertEqual(self.summary("infer", path, 3, 1), [("int", "", 0)])

    def test_overloads_are_reported_as_several_signatures(self):
        self.write("pick.py", "def pick(value):\n    return value\n")
        self.write("stubs/pick.pyi", "def pick(value: int) -> int: ...\n"
                                     "def pick(value: str) -> str: ...\n")
        path = self.write("picking.py", "from pick import pick\npick(")
        self.assertEqual(
            [item["description"] for item in self.payload("signatures", "signatures", path, 2, 5)],
            ["def pick(value: int) -> int", "def pick(value: str) -> str"],
        )

    def test_an_unannotated_parameter_is_typed_from_its_call_sites(self):
        source = "def greet(person, times):\n    return person\n\n\ngreet('ana', 3)\n"
        path = self.write("dynamic.py", source)
        self.assertEqual(self.summary("infer", path, 2, 12), [("str", "", 0)])
        self.assertEqual(self.summary("infer", path, 1, 19), [("int", "", 0)])

    def test_a_method_call_site_skips_the_receiver_argument(self):
        source = ("class Engine:\n"
                  "    def start(self, mode):\n"
                  "        return mode\n"
                  "\n"
                  "\n"
                  "Engine().start('fast')\n")
        path = self.write("method.py", source)
        self.assertEqual(self.summary("infer", path, 3, 16), [("str", "", 0)])

    def test_call_sites_are_ignored_when_dynamic_inference_is_off(self):
        source = "def greet(person):\n    return person\n\n\ngreet('ana')\n"
        path = self.write("static.py", source)
        self.assertEqual(self.summary("infer", path, 2, 12, "--no-dynamic"), [])

    def test_a_stub_annotation_wins_over_the_value_a_call_site_passes(self):
        self.write("counter.py", "def count(value):\n    return value\n")
        self.write("counter.pyi", "def count(value: str) -> str: ...\n")
        path = self.write("counting.py", "import counter\n\nseen = counter.count(1)\n")
        self.assertEqual(
            self.summary("infer", self.workspace / "counter.py", 2, 12), [("str", "", 0)]
        )
        self.assertEqual(self.summary("infer", path, 3, 1), [("str", "", 0)])


if __name__ == "__main__":
    unittest.main()
