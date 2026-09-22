"""Names with more than one possible type, for completion and for inference."""

TWO_CLASSES = (
    "class Calculator:\n"
    "    def add(self):\n"
    "        pass\n"
    "\n"
    "\n"
    "class Printer:\n"
    "    def emit(self):\n"
    "        pass\n"
    "\n"
    "\n"
)


# Spec: "When a name has multiple possible types (union), completions include
#        attributes from **all** possible types."
def test_union_completion_merges_attributes(complete):
    source = TWO_CLASSES + (
        "if flag:\n"
        "    value = Calculator()\n"
        "else:\n"
        "    value = Printer()\n"
        "value.|\n"
    )
    names = complete(source).names
    assert "add" in names and "emit" in names


# Spec: "For unresolved branches, return all reachable possibilities."
def test_union_inference_returns_every_branch(infer):
    source = TWO_CLASSES + (
        "if flag:\n"
        "    value = Calculator()\n"
        "else:\n"
        "    value = Printer()\n"
        "val|ue\n"
    )
    assert sorted(infer(source).definition_names) == ["Calculator", "Printer"]


# Spec: "Multiple definitions are returned when a name could resolve to more than one
#        thing (e.g., conditional assignments)."
def test_union_through_a_function_return(complete):
    source = TWO_CLASSES + (
        "def make(flag):\n"
        "    if flag:\n"
        "        return Calculator()\n"
        "    return Printer()\n"
        "\n"
        "value = make(1)\n"
        "value.|\n"
    )
    names = complete(source).names
    assert "add" in names and "emit" in names


# Spec: "Follow assignment chains." -- a later unconditional assignment replaces the
#        earlier possibilities rather than joining them.
def test_sequential_reassignment_is_not_a_union(infer):
    source = TWO_CLASSES + (
        "value = Calculator()\n"
        "value = Printer()\n"
        "val|ue\n"
    )
    assert infer(source).definition_names == ["Printer"]


def test_conditional_assignment_after_an_unconditional_one(infer):
    source = TWO_CLASSES + (
        "value = Calculator()\n"
        "if flag:\n"
        "    value = Printer()\n"
        "val|ue\n"
    )
    assert sorted(infer(source).definition_names) == ["Calculator", "Printer"]


# Spec: "infer answers what value/type that identifier evaluates to at the cursor."
def test_inference_is_positional(infer):
    source = "value = 'text'\nvalue = 2\n"
    assert infer(source, line=1, col=0).only["name"] == "str"
    assert infer(source, line=2, col=0).only["name"] == "int"
