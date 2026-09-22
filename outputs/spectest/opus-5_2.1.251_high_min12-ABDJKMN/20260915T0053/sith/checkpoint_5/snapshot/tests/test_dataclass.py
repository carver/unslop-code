"""Spec section: Type Inference Rules / Dataclass Fields."""
from conftest import CURSOR, complete_at, entry, has, infer_at, one

C = CURSOR

BASE = (
    "from dataclasses import dataclass\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class Point:\n"
    "    x: int\n"
    "    y: str = 'origin'\n"
)


# --- Phrase: "Classes decorated with @dataclasses.dataclass expose their annotated
#     fields as instance attributes for completion and inference."
#     Context: completion on an instance.
def test_dataclass_fields_complete_on_instance(tmp_path):
    data = complete_at(tmp_path, BASE + "p = Point(1)\np." + C + "\n")
    assert has(data, "x")
    assert has(data, "y")


# --- Phrase: "Dataclass instance attribute completion includes annotated fields."
def test_dataclass_field_completion_entry(tmp_path):
    data = complete_at(tmp_path, BASE + "p = Point(1)\np.x" + C + "\n")
    assert entry(data, "x")["type"] == "instance"


# --- Phrase: "... expose their annotated fields as instance attributes for
#     ... inference."
def test_dataclass_field_inference(tmp_path):
    defs = infer_at(tmp_path, BASE + "p = Point(1)\np." + "x" + C + "\n")
    assert one(defs)["full_name"] == "builtins.int"


# --- Phrase: "... annotated fields ..." (a field with a default)
def test_dataclass_field_with_default(tmp_path):
    defs = infer_at(tmp_path, BASE + "p = Point(1)\np." + "y" + C + "\n")
    assert one(defs)["full_name"] == "builtins.str"


# --- Phrase: "@dataclass(frozen=True) does not affect inference behavior."
def test_frozen_dataclass(tmp_path):
    code = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass(frozen=True)\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "\n"
        "p = Point(1)\n"
    )
    assert one(infer_at(tmp_path, code + "p.x" + C + "\n"))["full_name"] == \
        "builtins.int"
    data = complete_at(tmp_path, code + "p." + C + "\n")
    assert has(data, "x")


# --- Phrase: "@dataclass is recognized regardless of import form
#     (`import dataclasses` ...)"
def test_dataclass_module_import_form(tmp_path):
    code = (
        "import dataclasses\n"
        "\n"
        "\n"
        "@dataclasses.dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "\n"
        "p = Point(1)\n"
    )
    assert one(infer_at(tmp_path, code + "p.x" + C + "\n"))["full_name"] == \
        "builtins.int"
    assert has(complete_at(tmp_path, code + "p." + C + "\n"), "x")


# --- Phrase: "... (`from dataclasses import dataclass` ...)"
def test_dataclass_from_import_form(tmp_path):
    assert has(complete_at(tmp_path, BASE + "p = Point(1)\np." + C + "\n"), "x")


# --- Phrase: "... or aliased forms)."
def test_dataclass_aliased_form(tmp_path):
    code = (
        "from dataclasses import dataclass as dc\n"
        "\n"
        "\n"
        "@dc\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "\n"
        "p = Point(1)\n"
    )
    assert one(infer_at(tmp_path, code + "p.x" + C + "\n"))["full_name"] == \
        "builtins.int"
    assert has(complete_at(tmp_path, code + "p." + C + "\n"), "x")


# --- Phrase: "... aliased forms" with an aliased module import.
def test_dataclass_aliased_module_form(tmp_path):
    code = (
        "import dataclasses as dcs\n"
        "\n"
        "\n"
        "@dcs.dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "\n"
        "p = Point(1)\n"
    )
    assert has(complete_at(tmp_path, code + "p." + C + "\n"), "x")


# --- Phrase: "Dataclass fields are instance attributes for completion and inference."
#     Context: a field holding another dataclass instance.
def test_dataclass_field_of_class_type(tmp_path):
    code = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "class Engine:\n"
        "    def start(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Car:\n"
        "    engine: Engine\n"
        "\n"
        "\n"
        "car = Car(Engine())\n"
    )
    d = one(infer_at(tmp_path, code + "car.engin" + C + "e\n"))
    assert (d["name"], d["type"]) == ("Engine", "instance")
    assert has(complete_at(tmp_path, code + "car.engine." + C + "\n"), "start")


# --- Phrase: "Dataclass fields are instance attributes"
#     Context: goto on a field lands on the annotation line.
def test_goto_dataclass_field(tmp_path):
    from conftest import goto_at
    d = one(goto_at(tmp_path, BASE + "p = Point(1)\np.x" + C + "\n"))
    assert (d["name"], d["line"], d["column"]) == ("x", 6, 4)
    assert d["full_name"] == "example.Point.x"
