"""Spec section: Flow-Sensitive Type Narrowing."""
from conftest import CURSOR, complete_at, has, infer_at, one, dnames

C = CURSOR

ANIMALS = (
    "class Dog:\n"
    "    def bark(self):\n"
    "        return 1\n"
    "\n"
    "\n"
    "class Cat:\n"
    "    def meow(self):\n"
    "        return 2\n"
    "\n"
    "\n"
)


# --- Phrase: "isinstance(x, SomeClass) — x is SomeClass inside the if body."
#     Context: infer of the narrowed name.
def test_isinstance_narrowing_infer(tmp_path):
    code = ANIMALS + (
        "def handle(animal):\n"
        "    if isinstance(animal, Dog):\n"
        "        return anima" + C + "l\n"
    )
    d = one(infer_at(tmp_path, code))
    assert (d["name"], d["type"], d["line"]) == ("Dog", "instance", 1)


# --- Phrase: "This narrowing applies to both infer ... and complete (shows
#     attributes of the narrowed type for attribute completion)."
def test_isinstance_narrowing_complete(tmp_path):
    code = ANIMALS + (
        "def handle(animal):\n"
        "    if isinstance(animal, Dog):\n"
        "        animal." + C + "\n"
    )
    data = complete_at(tmp_path, code)
    assert has(data, "bark")
    assert not has(data, "meow")


# --- Phrase: "When the cursor is inside an isinstance branch, narrow the type
#     accordingly"
#     Context: narrowing overrides an otherwise known (wider) assignment.
def test_isinstance_narrowing_overrides_assignment(tmp_path):
    code = ANIMALS + (
        "flag = True\n"
        "if flag:\n"
        "    pet = Dog()\n"
        "else:\n"
        "    pet = Cat()\n"
        "if isinstance(pet, Cat):\n"
        "    pe" + C + "t\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["Cat"]


# --- Phrase: "When the cursor is inside an isinstance branch"
#     Context: narrowing only applies inside the branch body, not after it.
def test_no_narrowing_outside_branch(tmp_path):
    code = ANIMALS + (
        "def handle(animal):\n"
        "    if isinstance(animal, Dog):\n"
        "        pass\n"
        "    return anima" + C + "l\n"
    )
    assert infer_at(tmp_path, code) == []


# --- Phrase: "isinstance(x, SomeClass)"
#     Context: the narrowing test is part of an `and` chain.
def test_isinstance_narrowing_in_and_chain(tmp_path):
    code = ANIMALS + (
        "def handle(animal, flag):\n"
        "    if flag and isinstance(animal, Cat):\n"
        "        animal." + C + "\n"
    )
    assert has(complete_at(tmp_path, code), "meow")


# --- Phrase: "isinstance(x, SomeClass)"
#     Context: nested if statements narrow different names.
def test_isinstance_narrowing_nested(tmp_path):
    code = ANIMALS + (
        "def handle(a, b):\n"
        "    if isinstance(a, Dog):\n"
        "        if isinstance(b, Cat):\n"
        "            return " + C + "b\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["Cat"]


# --- Phrase: "### `is None`"
#     Context: inside `if x is None:` the name is the None singleton.
def test_is_none_narrowing(tmp_path):
    code = (
        "def handle(value):\n"
        "    if value is None:\n"
        "        return valu" + C + "e\n"
    )
    d = one(infer_at(tmp_path, code))
    assert d["full_name"] == "builtins.None"


# --- Phrase: "### `is None`"
#     Context: `is not None` removes None from a union (T38).
def test_is_not_none_narrowing(tmp_path):
    code = (
        "class Widget:\n"
        "    def draw(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "flag = True\n"
        "if flag:\n"
        "    thing = None\n"
        "else:\n"
        "    thing = Widget()\n"
        "if thing is not None:\n"
        "    thin" + C + "g\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["Widget"]


# --- Phrase: "### `is None`"
#     Context: the `else` branch of `if x is None:` excludes None.
def test_is_none_else_branch(tmp_path):
    code = (
        "class Widget:\n"
        "    def draw(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "flag = True\n"
        "if flag:\n"
        "    thing = None\n"
        "else:\n"
        "    thing = Widget()\n"
        "if thing is None:\n"
        "    pass\n"
        "else:\n"
        "    thin" + C + "g\n"
    )
    assert dnames(infer_at(tmp_path, code)) == ["Widget"]


# --- Phrase: "### `is None`"
#     Context: completion inside `is not None` drops the None attributes.
def test_is_not_none_completion(tmp_path):
    code = (
        "class Widget:\n"
        "    def draw(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "flag = True\n"
        "if flag:\n"
        "    thing = None\n"
        "else:\n"
        "    thing = Widget()\n"
        "if thing is not None:\n"
        "    thing." + C + "\n"
    )
    assert has(complete_at(tmp_path, code), "draw")
