"""What a statement binds: the record every name lookup resolves to."""

import ast
import re
from dataclasses import dataclass

from .definitions import Definition

CLASS = "class"
FUNCTION = "function"
PARAM = "param"
IMPORT = "import"
ASSIGN = "assign"
TARGET = "target"
EXCEPT = "except"


@dataclass(frozen=True)
class Binding:
    """One name introduced by one statement, and where its identifier sits.

    `value` is the expression the name draws its value from when there is one:
    the right-hand side of an assignment, the default of a parameter, the
    context expression of a ``with`` item or the exception class of an
    ``except`` clause. Imports keep their alias there instead.
    """

    name: str
    kind: str
    node: ast.AST
    lineno: int
    column: int
    value: ast.expr = None
    annotation: ast.expr = None
    receiver: ast.ClassDef = None
    owner: ast.AST = None


@dataclass(frozen=True)
class Reference:
    """A binding together with the module whose scope tree holds it.

    `typed` is the stub declaration that types the same name, when a ``.pyi``
    file declares it: the binding says where the name lives, the stub says
    what it holds.
    """

    module: object
    binding: Binding
    typed: "Reference" = None

    def definition(self, kind):
        """The record printed for the place this binding sits."""
        binding = self.binding
        return Definition(
            name=binding.name,
            type=kind,
            full_name=self.module.qualified(binding.name, binding.owner),
            module_path=self.module.relative_path,
            line=binding.lineno,
            column=binding.column,
            description=describe(binding),
            docstring="",
        )


def describe(binding):
    """The source-level description shown for a definition of `binding`."""
    node = binding.node
    if binding.kind == CLASS:
        return f"class {node.name}"
    if binding.kind == FUNCTION:
        return signature(node)
    if binding.kind in (PARAM, IMPORT):
        return ast.unparse(node)
    if binding.value is not None:
        return ast.unparse(binding.value)
    if binding.annotation is not None:
        return f"{binding.name}: {ast.unparse(binding.annotation)}"
    return binding.name


def signature(node):
    """The ``def name(params)`` line of a function, without its body."""
    return f"def {node.name}({ast.unparse(node.args)})"


def identifier_column(lines, lineno, name, after=0):
    """Column of `name` on a source line, searching from column `after`.

    The name is matched on its own, so that a short name is not found inside a
    longer one written before it.
    """
    text = lines[lineno - 1] if lineno <= len(lines) else ""
    found = re.compile(rf"\b{re.escape(name)}\b").search(text, after)
    return found.start() if found is not None else after


def alias_column(lines, alias):
    """Column of the name an import alias binds.

    An ``as`` clause is searched past the module name it renames, so that the
    short name is not found inside the dotted one.
    """
    bound = alias.asname or alias.name.split(".")[0]
    after = alias.col_offset + (len(alias.name) if alias.asname else 0)
    return identifier_column(lines, alias.lineno, bound, after)
