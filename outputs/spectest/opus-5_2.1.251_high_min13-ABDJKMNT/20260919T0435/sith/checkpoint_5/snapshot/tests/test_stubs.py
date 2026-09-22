"""Type information taken from `.pyi` stub files."""

STUBBED = "def build(name: str, count: int = 1) -> str: ...\n"
RUNTIME = "def build(name, count=1):\n    return name\n"


# "1. `foo.pyi` adjacent to `foo.py` (inline stub)."
# "`signatures` uses parameter annotations from the stub."
def test_inline_stub_supplies_parameters(signatures):
    result = signatures(
        "from tools import build\n\nbuild(|)\n",
        files={"tools.py": RUNTIME, "tools.pyi": STUBBED},
    )
    assert result.signature["params"] == ["name: str", "count: int=1"]
    assert result.signature["description"] == "def build(name: str, count: int=1) -> str"


# "`infer` uses return type annotations from the stub."
def test_stub_supplies_the_return_type(infer):
    result = infer(
        "from tools import build\n\nvalue = build('x')\nva|lue\n",
        files={"tools.py": RUNTIME, "tools.pyi": STUBBED},
    )
    assert result.only["full_name"] == "builtins.str"


# "`complete` uses type annotations from the stub for attribute completion."
def test_stub_supplies_attribute_types(complete):
    result = complete(
        "from tools import Box\n\nBox().size.|\n",
        files={
            "tools.py": "class Box:\n    def __init__(self):\n        self.size = load()\n",
            "tools.pyi": "class Box:\n    size: int\n",
        },
    )
    assert "bit_length" in result.names


# "Stub annotations take precedence over inferred types."
def test_stub_outranks_the_assigned_value(infer):
    result = infer(
        "from tools import value\n\nva|lue\n",
        files={"tools.py": "value = 1\n", "tools.pyi": "value: str\n"},
    )
    assert result.only["full_name"] == "builtins.str"


# "`goto` still navigates to the `.py` source (not the stub)"
def test_goto_lands_on_the_runtime_source(goto):
    result = goto(
        "from tools import build\n\nbui|ld()\n",
        files={"tools.py": RUNTIME, "tools.pyi": STUBBED},
        follow_imports=True,
    )
    assert result.only["module_path"] == "tools.py"


# "unless the definition only exists in the stub."
def test_goto_falls_back_to_a_stub_only_definition(goto):
    result = goto(
        "from tools import extra\n\next|ra()\n",
        files={"tools.py": RUNTIME, "tools.pyi": STUBBED + "def extra() -> int: ...\n"},
        follow_imports=True,
    )
    assert result.only["module_path"] == "tools.pyi"


# "2. A `stubs/` directory in the project root: `stubs/foo.pyi`"
def test_stub_directory(signatures):
    result = signatures(
        "from tools import build\n\nbuild(|)\n",
        files={"tools.py": RUNTIME, "stubs/tools.pyi": STUBBED},
    )
    assert result.signature["params"] == ["name: str", "count: int=1"]


# "or `stubs/foo/__init__.pyi`."
def test_stub_directory_package(infer):
    result = infer(
        "import pkg\n\nvalue = pkg.build('x')\nva|lue\n",
        files={
            "pkg/__init__.py": RUNTIME,
            "stubs/pkg/__init__.pyi": STUBBED,
        },
    )
    assert result.only["full_name"] == "builtins.str"


# "1. `foo.pyi` adjacent to `foo.py` (inline stub)." before the `stubs/` directory.
def test_inline_stub_wins_over_the_stubs_directory(signatures):
    result = signatures(
        "from tools import build\n\nbuild(|)\n",
        files={
            "tools.py": RUNTIME,
            "tools.pyi": "def build(inline: int) -> str: ...\n",
            "stubs/tools.pyi": "def build(directory: bytes) -> str: ...\n",
        },
    )
    assert result.signature["params"] == ["inline: int"]


# "If a stub exists, type information ... comes from the stub." for the file
# under the cursor itself.
def test_the_analysed_file_can_have_its_own_stub(infer):
    result = infer(
        "def build(name):\n    return name\n\nvalue = build('x')\nva|lue\n",
        files={"sample.pyi": STUBBED},
    )
    assert result.only["full_name"] == "builtins.str"


# "Multiple signatures are returned when the callable has overloads" -- stubs
# are where overloads are usually written.
def test_overloads_declared_in_a_stub(signatures):
    result = signatures(
        "from tools import build\n\nbuild(|)\n",
        files={
            "tools.py": RUNTIME,
            "tools.pyi": (
                "from typing import overload\n\n"
                "@overload\ndef build(name: str) -> str: ...\n"
                "@overload\ndef build(name: int) -> bytes: ...\n"
            ),
        },
    )
    assert [s["params"] for s in result.signatures] == [["name: str"], ["name: int"]]
