"""Spec: Flow-Sensitive Type Narrowing."""

CLASSES = (
    "class Duck:\n"
    "    def quack(self):\n"
    "        pass\n"
    "class Dog:\n"
    "    def bark(self):\n"
    "        pass\n"
)


# Spec: "`isinstance(x, SomeClass)` - `x` is `SomeClass` inside the `if` body."
# "This narrowing applies to both `infer` (returns the narrowed type) ..."
def test_isinstance_narrows_infer(infer):
    source = CLASSES + (
        "def handle(animal):\n"
        "    if isinstance(animal, Duck):\n"
        "        anima$l\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"], definition["line"]) == ("Duck", "instance", 1)


# Spec: "... and `complete` (shows attributes of the narrowed type for
# attribute completion)."
def test_isinstance_narrows_attribute_completion(complete):
    source = CLASSES + (
        "def handle(animal):\n"
        "    if isinstance(animal, Duck):\n"
        "        animal.$\n"
    )
    names = complete(source).names
    assert "quack" in names
    assert "bark" not in names


# Spec: "When the cursor is inside an `isinstance` branch" - code outside the
# branch is not narrowed.
def test_isinstance_does_not_narrow_outside_the_branch(infer):
    source = CLASSES + (
        "def handle(animal):\n"
        "    if isinstance(animal, Duck):\n"
        "        pass\n"
        "    anima$l\n"
    )
    assert infer(source).definitions == []


# Spec: narrowing applies to a name that already has a known type.
def test_isinstance_narrows_a_union(infer):
    source = CLASSES + (
        "def handle(flag):\n"
        "    if flag:\n"
        "        animal = Duck()\n"
        "    else:\n"
        "        animal = Dog()\n"
        "    if isinstance(animal, Dog):\n"
        "        anima$l\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["Dog"]


# Spec: an `isinstance` test joined by `and` still narrows.
def test_isinstance_inside_a_conjunction(infer):
    source = CLASSES + (
        "def handle(animal, flag):\n"
        "    if flag and isinstance(animal, Duck):\n"
        "        anima$l\n"
    )
    assert infer(source).only["name"] == "Duck"


# Spec: "### `is None`" - inside the branch the name is `None`.
def test_is_none_narrows_to_none(infer):
    source = (
        "def handle(flag):\n"
        "    value = 1 if flag else None\n"
        "    if value is None:\n"
        "        valu$e\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["None"]


# Spec: "### `is None`" - the other branch drops the `None` possibility.
def test_is_none_else_branch_drops_none(infer):
    source = (
        "def handle(flag):\n"
        "    if flag:\n"
        "        value = 1\n"
        "    else:\n"
        "        value = None\n"
        "    if value is None:\n"
        "        pass\n"
        "    else:\n"
        "        valu$e\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["int"]


# Spec: "### `is None`" - `is not None` narrows the positive branch.
def test_is_not_none_narrows(infer):
    source = CLASSES + (
        "def handle(flag):\n"
        "    if flag:\n"
        "        animal = Duck()\n"
        "    else:\n"
        "        animal = None\n"
        "    if animal is not None:\n"
        "        anima$l\n"
    )
    assert [item["name"] for item in infer(source).definitions] == ["Duck"]


def test_is_not_none_narrows_attribute_completion(complete):
    source = CLASSES + (
        "def handle(flag):\n"
        "    if flag:\n"
        "        animal = Duck()\n"
        "    else:\n"
        "        animal = None\n"
        "    if animal is not None:\n"
        "        animal.$\n"
    )
    assert "quack" in complete(source).names


# Spec: an `elif` branch narrows on its own test.
def test_elif_branch_narrows(infer):
    source = CLASSES + (
        "def handle(animal, flag):\n"
        "    if flag:\n"
        "        pass\n"
        "    elif isinstance(animal, Dog):\n"
        "        anima$l\n"
    )
    assert infer(source).only["name"] == "Dog"
