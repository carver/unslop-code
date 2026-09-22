"""Flow-sensitive narrowing inside `isinstance` and `is None` branches."""

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


# Spec: "`isinstance(x, SomeClass)` -- `x` is `SomeClass` inside the `if` body." /
#       "This narrowing applies to both `infer` (returns the narrowed type) ..."
def test_isinstance_narrows_infer(infer):
    source = TWO_CLASSES + (
        "def use(value):\n"
        "    if isinstance(value, Calculator):\n"
        "        val|ue\n"
    )
    definition = infer(source).only
    assert definition["name"] == "Calculator"
    assert definition["type"] == "instance"


# Spec: "... and `complete` (shows attributes of the narrowed type for attribute
#        completion)."
def test_isinstance_narrows_completion(complete):
    source = TWO_CLASSES + (
        "def use(value):\n"
        "    if isinstance(value, Printer):\n"
        "        value.|\n"
    )
    names = complete(source).names
    assert "emit" in names
    assert "add" not in names


# Spec: narrowing applies only inside the `if` body.
def test_no_narrowing_outside_the_branch(infer):
    source = TWO_CLASSES + (
        "def use(value):\n"
        "    if isinstance(value, Calculator):\n"
        "        pass\n"
        "    val|ue\n"
    )
    assert infer(source).definitions == []


# Spec: isinstance narrowing overrides an assigned type.
def test_isinstance_narrows_a_union(infer):
    source = TWO_CLASSES + (
        "def use(flag):\n"
        "    if flag:\n"
        "        value = Calculator()\n"
        "    else:\n"
        "        value = Printer()\n"
        "    if isinstance(value, Printer):\n"
        "        val|ue\n"
    )
    assert infer(source).definition_names == ["Printer"]


# Spec: "`isinstance(x, SomeClass)`" with a tuple of classes.
def test_isinstance_with_a_tuple(infer):
    source = TWO_CLASSES + (
        "def use(value):\n"
        "    if isinstance(value, (Calculator, Printer)):\n"
        "        val|ue\n"
    )
    assert sorted(infer(source).definition_names) == ["Calculator", "Printer"]


# Spec: "### `is None`"
def test_is_none_narrows_to_none(infer):
    source = (
        "def use(value):\n"
        "    if value is None:\n"
        "        val|ue\n"
    )
    assert infer(source).only["full_name"] == "builtins.None"


def test_is_not_none_drops_none(infer):
    source = TWO_CLASSES + (
        "def use(flag):\n"
        "    value = None\n"
        "    if flag:\n"
        "        value = Calculator()\n"
        "    if value is not None:\n"
        "        val|ue\n"
    )
    assert infer(source).definition_names == ["Calculator"]


def test_else_of_is_none_drops_none(infer):
    source = TWO_CLASSES + (
        "def use(flag):\n"
        "    value = None\n"
        "    if flag:\n"
        "        value = Calculator()\n"
        "    if value is None:\n"
        "        pass\n"
        "    else:\n"
        "        val|ue\n"
    )
    assert infer(source).definition_names == ["Calculator"]


# Spec: narrowing is per name; other names are untouched.
def test_narrowing_only_affects_the_tested_name(infer):
    source = TWO_CLASSES + (
        "def use(value, other):\n"
        "    if isinstance(value, Calculator):\n"
        "        oth|er\n"
    )
    assert infer(source).definitions == []
