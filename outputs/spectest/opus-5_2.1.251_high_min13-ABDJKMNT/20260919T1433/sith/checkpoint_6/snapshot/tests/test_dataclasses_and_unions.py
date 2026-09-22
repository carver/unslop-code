"""Spec: Dataclass Fields and the Completion Enhancements."""

POINT = (
    "@dataclass\n"
    "class Point:\n"
    "    x: int\n"
    "    label: str\n"
    "    def move(self):\n"
    "        pass\n"
)


# Spec: "Classes decorated with `@dataclasses.dataclass` expose their annotated
# fields as instance attributes for completion and inference."
# "- Dataclass instance attribute completion includes annotated fields."
def test_dataclass_fields_complete_on_an_instance(complete):
    source = "from dataclasses import dataclass\n" + POINT + "point = Point(1, 'a')\npoint.$\n"
    names = complete(source).names
    assert {"x", "label", "move"} <= set(names)


# Spec: dataclass fields are inferred from their annotations.
def test_dataclass_field_type_is_inferred(infer):
    source = "from dataclasses import dataclass\n" + POINT + "point = Point(1, 'a')\npoint.$x\n"
    assert infer(source).only["full_name"] == "builtins.int"


def test_dataclass_field_of_a_class_type(infer):
    source = (
        "from dataclasses import dataclass\n"
        "class Engine:\n"
        "    pass\n"
        "@dataclass\n"
        "class Car:\n"
        "    engine: Engine\n"
        "car = Car(Engine())\n"
        "car.engin$e\n"
    )
    definition = infer(source).only
    assert (definition["name"], definition["type"]) == ("Engine", "instance")


# Spec: "`@dataclass` is recognized regardless of import form
# (`import dataclasses`, ...)".
def test_dataclass_via_module_attribute_decorator(complete):
    source = (
        "import dataclasses\n"
        "@dataclasses.dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "point = Point(1)\n"
        "point.$\n"
    )
    assert "x" in complete(source).names


# Spec: "... `from dataclasses import dataclass`, or aliased forms."
def test_dataclass_via_aliased_import(complete):
    source = (
        "from dataclasses import dataclass as record\n"
        "@record\n"
        "class Point:\n"
        "    x: int\n"
        "point = Point(1)\n"
        "point.$\n"
    )
    assert "x" in complete(source).names


# Spec: "`@dataclass(frozen=True)` does not affect inference behavior."
def test_frozen_dataclass(complete, infer):
    source = (
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True)\n"
        "class Point:\n"
        "    x: int\n"
        "point = Point(1)\n"
        "point.$\n"
    )
    assert "x" in complete(source).names
    assert infer(source.replace("point.$", "point.$x")).only["full_name"] == "builtins.int"


# Spec: "Attribute completion after `.` uses inferred types. If
# `x = Calculator()`, then `x.` shows `Calculator` instance attributes."
def test_attribute_completion_uses_inferred_types(complete):
    source = (
        "class Calculator:\n"
        "    def __init__(self):\n"
        "        self.total = 0\n"
        "    def add(self, value):\n"
        "        pass\n"
        "x = Calculator()\n"
        "x.$\n"
    )
    assert {"total", "add"} <= set(complete(source).names)


# Spec: attribute completion follows a function's inferred return type.
def test_attribute_completion_through_a_call(complete):
    source = (
        "class Calculator:\n"
        "    def add(self, value):\n"
        "        pass\n"
        "def build():\n"
        "    return Calculator()\n"
        "build().$\n"
    )
    assert "add" in complete(source).names


# Spec: "When a name has multiple possible types (union), completions include
# attributes from **all** possible types."
def test_union_completion_includes_every_type(complete):
    source = (
        "class Duck:\n"
        "    def quack(self):\n"
        "        pass\n"
        "class Dog:\n"
        "    def bark(self):\n"
        "        pass\n"
        "def handle(flag):\n"
        "    if flag:\n"
        "        animal = Duck()\n"
        "    else:\n"
        "        animal = Dog()\n"
        "    animal.$\n"
    )
    names = complete(source).names
    assert {"quack", "bark"} <= set(names)


# Spec: "For unresolved branches, return all reachable possibilities."
def test_union_from_multiple_return_paths_completes(complete):
    source = (
        "class Duck:\n"
        "    def quack(self):\n"
        "        pass\n"
        "class Dog:\n"
        "    def bark(self):\n"
        "        pass\n"
        "def pick(flag):\n"
        "    if flag:\n"
        "        return Duck()\n"
        "    return Dog()\n"
        "animal = pick(True)\n"
        "animal.$\n"
    )
    assert {"quack", "bark"} <= set(complete(source).names)
