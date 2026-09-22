"""The `signatures` command: what the call at the cursor is calling.

A signature is built from whatever declares the callable -- a stub, a set of
`@overload` declarations, or the `def` itself -- while its name and its place
in the output come from the source the reader would navigate to.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass

from . import calls, definitions, params, scopes
from .analysis import Analysis
from .params import Argument, Parameter
from .targets import ClassTarget, FunctionTarget, RuntimeTarget

INITIALIZER = "__init__"
SELF = "self"
OVERLOAD = "overload"

#: How `inspect` spells the parameter kinds that `params` counts with.
_RUNTIME_KINDS = {
    inspect.Parameter.POSITIONAL_ONLY: params.POSITIONAL,
    inspect.Parameter.POSITIONAL_OR_KEYWORD: params.POSITIONAL,
    inspect.Parameter.VAR_POSITIONAL: params.VARARG,
    inspect.Parameter.KEYWORD_ONLY: params.KEYWORD_ONLY,
    inspect.Parameter.VAR_KEYWORD: params.KWARG,
}
_RUNTIME_STARS = {params.VARARG: "*", params.KWARG: "**"}


@dataclass(frozen=True)
class Signature:
    """One callable the cursor could be calling."""

    name: str
    parameters: tuple[Parameter, ...]
    returns: str
    docstring: str
    #: `(module_path, line)` of the source it was declared in, which orders output.
    order: tuple[str, int]

    @property
    def description(self) -> str:
        rendered = ", ".join(parameter.text for parameter in self.parameters)
        arrow = f" -> {self.returns}" if self.returns else ""
        return f"def {self.name}({rendered}){arrow}"

    def as_dict(self, argument: Argument) -> dict:
        return {
            "name": self.name,
            "params": [parameter.text for parameter in self.parameters],
            "index": params.index_of(self.parameters, argument),
            "description": self.description,
            "docstring": self.docstring,
        }


def signatures(path: str, line: int, col: int, project: str | None = None) -> list[dict]:
    """The signatures of the call whose argument list holds the cursor."""
    analysis = Analysis.at(path, line, col, project)
    site = calls.call_at(analysis.source.lines, line, col)
    if site is None:
        return []
    found = [
        signature
        for target in analysis.resolver.source(site.callee, analysis.scope)
        for signature in _of(target)
    ]
    ordered = sorted(dict.fromkeys(found), key=lambda signature: signature.order)
    return [signature.as_dict(site.argument) for signature in ordered]


def _from_function(target: FunctionTarget) -> list[Signature]:
    """A call of a function or a bound method."""
    node, resolver = target.node, target.resolver
    return _declared(
        node,
        resolver,
        node.name,
        bound=_is_method(node, resolver),
        docstring=definitions.docstring_of(node),
    )


def _from_class(target: ClassTarget) -> list[Signature]:
    """A call of a class: the constructor's parameters under the class's name."""
    node, resolver = target.node, target.resolver
    docstring = definitions.docstring_of(node)
    order = (resolver.module.path, node.lineno)
    found = [
        signature
        for binding in resolver.class_members(node, INITIALIZER)
        for signature in _declared(
            binding.node, resolver, node.name, True, docstring, returns=False, order=order
        )
    ]
    return found or [Signature(node.name, (), "", docstring, order)]


def _from_runtime(target: RuntimeTarget) -> list[Signature]:
    """A call of a live object, read off whatever `inspect` can say about it."""
    try:
        signature = inspect.signature(target.obj)
    except (TypeError, ValueError):
        return []
    path, line = definitions.source_location(target.obj)
    return [
        Signature(
            name=target.name,
            parameters=tuple(_runtime_parameter(p) for p in signature.parameters.values()),
            returns=_runtime_annotation(signature.return_annotation),
            docstring=inspect.getdoc(target.obj) or "",
            order=(path, line),
        )
    ]


#: How each kind of target turns into the signatures of calling it.
_BUILDERS = {
    FunctionTarget: _from_function,
    ClassTarget: _from_class,
    RuntimeTarget: _from_runtime,
}


def _of(target) -> list[Signature]:
    builder = _BUILDERS.get(type(target))
    return builder(target) if builder else []


def _declared(node, resolver, name, bound, docstring, returns=True, order=None):
    """One signature per declaration of `node`: its stub's, its overloads', or its own."""
    place = order or (resolver.module.path, node.lineno)
    return [
        _signature(declaration, name, bound, docstring, place, returns)
        for declaration in _declarations(node, resolver)
    ]


def _declarations(node, resolver) -> list[ast.AST]:
    """What states the parameters: a stub outranks overloads, which outrank the `def`."""
    return resolver.stub_declarations(node) or _overloads(node, resolver) or [node]


def _signature(declaration, name, bound, docstring, order, returns) -> Signature:
    shown = params.parameters(declaration.args)
    if bound and shown and shown[0].name == SELF:
        shown = shown[1:]
    annotation = ast.unparse(declaration.returns) if returns and declaration.returns else ""
    return Signature(
        name=name,
        parameters=tuple(shown),
        returns=annotation,
        docstring=docstring or definitions.docstring_of(declaration),
        order=order,
    )


def _overloads(node, resolver) -> list[ast.AST]:
    """The `@overload` declarations standing beside an implementation."""
    scope = resolver.tree.scope_for(node)
    owner = scope.parent if scope is not None else None
    if owner is None:
        return []
    same = [b.node for b in owner.bindings if b.form == scopes.DEF and b.name == node.name]
    return [declaration for declaration in same if _is_overload(declaration)]


def _is_overload(node) -> bool:
    return any(_decorator_name(node) == OVERLOAD for node in node.decorator_list)


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _is_method(node, resolver) -> bool:
    scope = resolver.tree.scope_for(node)
    return scope is not None and scope.parent is not None and scope.parent.kind == "class"


def _runtime_parameter(parameter: inspect.Parameter) -> Parameter:
    kind = _RUNTIME_KINDS[parameter.kind]
    annotated = _runtime_annotation(parameter.annotation)
    default = "" if parameter.default is parameter.empty else f"={parameter.default!r}"
    stars = _RUNTIME_STARS.get(kind, "")
    text = f"{stars}{parameter.name}{f': {annotated}' if annotated else ''}{default}"
    return Parameter(parameter.name, text, kind)


def _runtime_annotation(annotation) -> str:
    return "" if annotation is inspect.Signature.empty else inspect.formatannotation(annotation)
