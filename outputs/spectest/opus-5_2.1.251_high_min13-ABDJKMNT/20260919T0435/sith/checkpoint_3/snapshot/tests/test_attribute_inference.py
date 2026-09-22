"""Attribute access and dataclass fields, for both inference and completion."""


# Spec: "Infer attributes from instance state when resolvable."
def test_infer_an_attribute_assigned_in_init(infer):
    source = (
        "class Calculator:\n"
        "    def __init__(self):\n"
        "        self.total = 0\n"
        "\n"
        "c = Calculator()\n"
        "c.tot|al\n"
    )
    assert infer(source).only["name"] == "int"


def test_infer_a_class_attribute(infer):
    source = "class Calculator:\n    name = 'calc'\n\nc = Calculator()\nc.na|me\n"
    assert infer(source).only["name"] == "str"


def test_infer_an_attribute_through_self(infer):
    source = (
        "class Calculator:\n"
        "    def __init__(self):\n"
        "        self.total = 0\n"
        "\n"
        "    def show(self):\n"
        "        return self.tot|al\n"
    )
    assert infer(source).only["name"] == "int"


def test_infer_a_method(infer):
    source = (
        "class Calculator:\n"
        "    def add(self, x):\n"
        "        return x\n"
        "\n"
        "c = Calculator()\n"
        "c.a|dd\n"
    )
    definition = infer(source).only
    assert definition["type"] == "function"
    assert definition["description"] == "def add(self, x)"


# Spec: "Attribute completion after `.` uses inferred types. If `x = Calculator()`,
#        then `x.` shows `Calculator` instance attributes."
def test_attribute_completion_uses_the_inferred_type(complete):
    source = (
        "class Calculator:\n"
        "    def __init__(self):\n"
        "        self.total = 0\n"
        "\n"
        "    def add(self, x):\n"
        "        return x\n"
        "\n"
        "c = Calculator()\n"
        "c.|\n"
    )
    names = complete(source).names
    assert "total" in names and "add" in names


DATACLASS = (
    "import dataclasses\n"
    "\n"
    "\n"
    "@dataclasses.dataclass\n"
    "class Point:\n"
    "    x: int\n"
    "    label: str\n"
)


# Spec: "Dataclass instance attribute completion includes annotated fields."
def test_dataclass_fields_complete_on_an_instance(complete):
    names = complete(DATACLASS + "p = Point(1, 'a')\np.|\n").names
    assert "x" in names and "label" in names


# Spec: "Classes decorated with `@dataclasses.dataclass` expose their annotated fields
#        as instance attributes for ... inference."
def test_dataclass_field_type_is_inferred(infer):
    assert infer(DATACLASS + "p = Point(1, 'a')\np.la|bel\n").only["name"] == "str"


# Spec: "`@dataclass(frozen=True)` does not affect inference behavior."
def test_frozen_dataclass(infer):
    source = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass(frozen=True)\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "p = Point(1)\n"
        "p.|x\n"
    )
    assert infer(source).only["name"] == "int"


# Spec: "`@dataclass` is recognized regardless of import form (`import dataclasses`,
#        `from dataclasses import dataclass`, or aliased forms)."
def test_aliased_dataclass_import(complete):
    source = (
        "from dataclasses import dataclass as record\n"
        "\n"
        "\n"
        "@record\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "p = Point(1)\n"
        "p.|\n"
    )
    assert "x" in complete(source).names


def test_aliased_dataclasses_module(infer):
    source = (
        "import dataclasses as dc\n"
        "\n"
        "\n"
        "@dc.dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "p = Point(1)\n"
        "p.|x\n"
    )
    assert infer(source).only["name"] == "int"


# Spec: "Dataclass fields are instance attributes for completion and inference."
def test_goto_a_dataclass_field(goto):
    definition = goto(DATACLASS + "p = Point(1, 'a')\np.la|bel\n").only
    assert (definition["line"], definition["column"]) == (7, 4)
    assert definition["full_name"] == "sample.Point.label"
