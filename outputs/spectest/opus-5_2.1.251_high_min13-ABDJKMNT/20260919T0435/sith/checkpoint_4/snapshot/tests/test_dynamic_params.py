"""Inferring parameter types from the call sites in the same file."""


# "When a function has no type annotations and no stub, the tool can optionally
#  infer parameter types by finding call sites.  This is enabled by default and
#  affects `infer`"
def test_parameter_type_comes_from_a_call_site(infer):
    result = infer(
        """
def process(items):
    return ite|ms

process([1, 2])
"""
    )
    assert result.only["full_name"] == "builtins.list"


def test_keyword_argument_call_site(infer):
    result = infer(
        """
def process(items):
    return ite|ms

process(items='text')
"""
    )
    assert result.only["full_name"] == "builtins.str"


def test_method_call_site_skips_self(infer):
    result = infer(
        """
class Runner:
    def process(self, items):
        return ite|ms

Runner().process(42)
"""
    )
    assert result.only["full_name"] == "builtins.int"


# "When a function has no type annotations": an annotation still wins.
def test_annotation_wins_over_the_call_site(infer):
    result = infer(
        """
def process(items: str):
    return ite|ms

process([1, 2])
"""
    )
    assert result.only["full_name"] == "builtins.str"


# "and no stub"
def test_stub_wins_over_the_call_site(infer):
    result = infer(
        """
def process(items):
    return ite|ms

process([1, 2])
""",
        files={"sample.pyi": "def process(items: str) -> None: ...\n"},
    )
    assert result.only["full_name"] == "builtins.str"


# "Do not search other files for call sites."
def test_call_sites_in_other_files_are_ignored(infer):
    result = infer(
        "def process(items):\n    return ite|ms\n",
        name="tools.py",
        files={"caller.py": "from tools import process\n\nprocess([1, 2])\n"},
    )
    assert result.definitions == []


# Several call sites contribute several possible types.
def test_several_call_sites(infer):
    result = infer(
        """
def process(items):
    return ite|ms

process([1, 2])
process('text')
"""
    )
    assert {d["full_name"] for d in result.definitions} == {"builtins.list", "builtins.str"}
