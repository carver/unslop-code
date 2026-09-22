"""Spec section: Completion Enhancements."""
from conftest import CURSOR, complete_at, has, names

C = CURSOR

PAIR = (
    "class Alpha:\n"
    "    def only_alpha(self):\n"
    "        return 1\n"
    "\n"
    "\n"
    "class Beta:\n"
    "    def only_beta(self):\n"
    "        return 2\n"
    "\n"
    "\n"
)


# --- Phrase: "Attribute completion after `.` uses inferred types.  If
#     `x = Calculator()`, then `x.` shows Calculator instance attributes."
def test_attribute_completion_uses_inferred_type(tmp_path):
    code = (
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "\n"
        "    def __init__(self):\n"
        "        self.memory = 0\n"
        "\n"
        "\n"
        "x = Calculator()\n"
        "x." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "add")
    assert has(data, "memory")


# --- Phrase: "Attribute completion after `.` uses inferred types."
#     Context: the inferred type comes through a call chain.
def test_attribute_completion_through_call(tmp_path):
    code = (
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "\n"
        "\n"
        "def build():\n"
        "    return Calculator()\n"
        "\n"
        "\n"
        "x = build()\n"
        "x." + C + "\n"
    )
    assert has(complete_at(tmp_path, code), "add")


# --- Phrase: "Attribute completion after `.` uses inferred types."
#     Context: a literal's type drives completion.
def test_attribute_completion_on_literal_binding(tmp_path):
    data = complete_at(tmp_path, "text = 'hello'\ntext.upp" + C + "\n")
    assert has(data, "upper")


# --- Phrase: "When a name has multiple possible types (union), completions include
#     attributes from all possible types."
def test_union_completion(tmp_path):
    code = PAIR + (
        "flag = True\n"
        "if flag:\n"
        "    item = Alpha()\n"
        "else:\n"
        "    item = Beta()\n"
        "item." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "only_alpha")
    assert has(data, "only_beta")


# --- Phrase: "... completions include attributes from all possible types."
#     Context: union produced by a function with two return paths.
def test_union_completion_from_return_paths(tmp_path):
    code = PAIR + (
        "def build(flag):\n"
        "    if flag:\n"
        "        return Alpha()\n"
        "    return Beta()\n"
        "\n"
        "\n"
        "item = build(True)\n"
        "item." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "only_alpha")
    assert has(data, "only_beta")


# --- Phrase: "... completions include attributes from all possible types."
#     Context: duplicate attribute names appear once.
def test_union_completion_dedupes(tmp_path):
    code = (
        "class Alpha:\n"
        "    def shared(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Beta:\n"
        "    def shared(self):\n"
        "        return 2\n"
        "\n"
        "\n"
        "flag = True\n"
        "if flag:\n"
        "    item = Alpha()\n"
        "else:\n"
        "    item = Beta()\n"
        "item." + C + "\n"
    )
    assert names(complete_at(tmp_path, code)).count("shared") == 1
