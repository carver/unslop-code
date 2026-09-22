"""Spec: Stub File Support."""

HELPER = "def compute(value):\n    return str(value)\n"
STUB = "def compute(value: int) -> str: ...\n"


def only_signature(result):
    assert len(result.signatures) == 1, result.signatures
    return result.signatures[0]


# Spec: "For a module `foo`, the tool looks for type stubs in this order:
# 1. `foo.pyi` adjacent to `foo.py` (inline stub)."
def test_inline_stub_beside_the_module(signatures):
    result = signatures(
        "import helper\nhelper.compute($)\n",
        extra={"helper.py": HELPER, "helper.pyi": STUB},
    )
    assert only_signature(result)["params"] == ["value: int"]


# Spec: "2. A `stubs/` directory in the project root: `stubs/foo.pyi`"
def test_stub_in_the_stubs_directory(signatures):
    result = signatures(
        "import helper\nhelper.compute($)\n",
        extra={"helper.py": HELPER, "stubs/helper.pyi": STUB},
    )
    assert only_signature(result)["params"] == ["value: int"]


# Spec: "... or `stubs/foo/__init__.pyi`."
def test_stub_package_in_the_stubs_directory(signatures):
    result = signatures(
        "import helper\nhelper.compute($)\n",
        extra={"helper.py": HELPER, "stubs/helper/__init__.pyi": STUB},
    )
    assert only_signature(result)["params"] == ["value: int"]


# Spec: "the tool looks for type stubs in this order" (the inline stub first)
def test_inline_stub_wins_over_the_stubs_directory(signatures):
    result = signatures(
        "import helper\nhelper.compute($)\n",
        extra={
            "helper.py": HELPER,
            "helper.pyi": STUB,
            "stubs/helper.pyi": "def compute(value: bytes) -> str: ...\n",
        },
    )
    assert only_signature(result)["params"] == ["value: int"]


# Spec: "`signatures` uses parameter annotations from the stub."
def test_signatures_use_stub_annotations(signatures):
    result = signatures(
        "from helper import compute\ncompute($)\n",
        extra={"helper.py": HELPER, "helper.pyi": STUB},
    )
    signature = only_signature(result)
    assert signature["description"] == "def compute(value: int) -> str"
    assert signature["index"] == 0


# Spec: "`infer` uses return type annotations from the stub."
def test_infer_uses_stub_return_type(infer):
    result = infer(
        "import helper\nanswer = helper.compute(1)\nans$wer\n",
        extra={"helper.py": HELPER, "helper.pyi": "def compute(value: int) -> bytes: ...\n"},
    )
    assert (result.only["name"], result.only["type"]) == ("bytes", "instance")


# Spec: "`complete` uses type annotations from the stub for attribute completion."
def test_complete_uses_stub_annotations(complete):
    result = complete(
        "import helper\nwidget = helper.Widget()\nwidget.si$\n",
        extra={
            "helper.py": "class Widget:\n    def __init__(self):\n        self.size = None\n",
            "helper.pyi": "class Widget:\n    size: int\n",
        },
    )
    assert result.by_name("size")["description"] == "instance of int"


# Spec: "Stub annotations take precedence over inferred types."
def test_stub_annotations_beat_inference(infer):
    result = infer(
        "import helper\nwidget = helper.Widget()\nwidget.si$ze\n",
        extra={
            "helper.py": "class Widget:\n    def __init__(self):\n        self.size = None\n",
            "helper.pyi": "class Widget:\n    size: int\n",
        },
    )
    assert result.only["name"] == "int"


# Spec: "The runtime `.py` file is still used for `goto` (source navigation)."
def test_goto_navigates_to_the_runtime_source(goto):
    result = goto(
        "import helper\nhelper.comp$ute\n",
        extra={"helper.py": HELPER, "helper.pyi": STUB},
    )
    assert (result.only["module_path"], result.only["line"]) == ("helper.py", 1)


# Spec: "`goto` still navigates to the `.py` source (not the stub), unless the
# definition only exists in the stub."
def test_goto_reaches_a_definition_that_only_exists_in_the_stub(goto):
    result = goto(
        "import helper\nhelper.LIM$IT\n",
        extra={"helper.py": HELPER, "helper.pyi": STUB + "LIMIT: int\n"},
    )
    assert (result.only["module_path"], result.only["line"]) == ("helper.pyi", 2)


# Spec: "Multiple signatures are returned when the callable has overloads"
def test_stub_overloads_give_several_signatures(signatures):
    stub = (
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def compute(value: int) -> str: ...\n"
        "@overload\n"
        "def compute(value: bytes) -> str: ...\n"
    )
    result = signatures(
        "import helper\nhelper.compute($)\n",
        extra={"helper.py": HELPER, "helper.pyi": stub},
    )
    assert [item["params"] for item in result.signatures] == [["value: int"], ["value: bytes"]]
