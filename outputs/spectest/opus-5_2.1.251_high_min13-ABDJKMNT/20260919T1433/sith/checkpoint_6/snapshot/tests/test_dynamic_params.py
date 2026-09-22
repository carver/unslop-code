"""Spec: Dynamic Parameter Inference."""


# Spec: "When a function has no type annotations and no stub, the tool can
# optionally infer parameter types by finding call sites. This is enabled by
# default and affects `infer` ..."
def test_parameter_type_comes_from_a_call_site(infer):
    result = infer("def apply(value):\n    val$ue\n\napply(3)\n")
    assert (result.only["name"], result.only["type"]) == ("int", "instance")


def test_call_sites_are_unioned(infer):
    source = "def apply(value):\n    val$ue\n\napply(3)\napply('text')\n"
    assert {item["name"] for item in infer(source).definitions} == {"int", "str"}


def test_keyword_call_sites_are_used(infer):
    result = infer("def apply(first, second):\n    sec$ond\n\napply(1, second='text')\n")
    assert result.only["name"] == "str"


# Spec: "... and `signatures`."
def test_signatures_of_a_parameter_called_in_the_body(signatures):
    source = (
        "def run(callback):\n"
        "    callback($)\n"
        "\n"
        "def target(alpha, beta):\n"
        "    pass\n"
        "\n"
        "run(target)\n"
    )
    result = signatures(source)
    assert [item["params"] for item in result.signatures] == [["alpha", "beta"]]


# Spec: "When a function has no type annotations ..." (an annotation wins)
def test_annotation_wins_over_call_sites(infer):
    result = infer("def apply(value: str):\n    val$ue\n\napply(3)\n")
    assert result.only["name"] == "str"


# Spec: "Do not search other files for call sites."
def test_call_sites_in_other_files_are_ignored(infer):
    result = infer(
        "def apply(value):\n    val$ue\n",
        extra={"other.py": "from module_under_test import apply\n\napply(3)\n"},
    )
    assert result.definitions == []
