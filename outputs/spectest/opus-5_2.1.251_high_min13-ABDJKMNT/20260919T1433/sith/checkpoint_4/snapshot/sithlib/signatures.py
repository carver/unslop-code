"""Signature help: what the call under the cursor takes, and where it is.

The callable is resolved the way any other expression is; what this module
adds is how a declared parameter list is written out and which of those
parameters the argument under the cursor binds to.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from .analysis import CLASS_SCOPE, FUNCTION_NODES, SourceClass, SourceFunction
from .calls import CallSite, call_at
from .context import cursor_indent, parse_expression
from .definitions import docstring_of, document
from .narrowing import narrowed_lookup
from .runtime import RuntimeValue, Union, Value, runtime_names, source_position
from .source import Source
from .stubs import Stubbed

POSITIONAL, KEYWORD, VARARG, KWARG = "positional", "keyword", "vararg", "kwarg"
OVERLOAD = "overload"
STATICMETHOD = "staticmethod"
INIT = "__init__"

RUNTIME_KINDS = {
    inspect.Parameter.VAR_POSITIONAL: VARARG,
    inspect.Parameter.VAR_KEYWORD: KWARG,
    inspect.Parameter.KEYWORD_ONLY: KEYWORD,
}
STARS = {VARARG: "*", KWARG: "**"}


@dataclass(frozen=True)
class Parameter:
    """One declared parameter, as written and as called."""

    name: str
    written: str
    kind: str = POSITIONAL


@dataclass(frozen=True)
class Signature:
    """One way a callable can be called."""

    name: str
    parameters: Tuple[Parameter, ...]
    returns: str
    """The return annotation as written, empty when there is none."""
    docstring: str
    origin: Tuple[str, int]
    """Module path and line the signature was declared at, for ordering."""

    @property
    def description(self) -> str:
        written = ", ".join(parameter.written for parameter in self.parameters)
        return f"def {self.name}({written})" + (f" -> {self.returns}" if self.returns else "")

    def record(self, call: CallSite) -> Dict:
        """The JSON fields of this signature, answering a cursor in a call."""
        return {
            "name": self.name,
            "params": [parameter.written for parameter in self.parameters],
            "index": bound_index(self.parameters, call),
            "description": self.description,
            "docstring": self.docstring,
        }


def signatures(source: Source, project, line: int, col: int) -> str:
    """Signature help for a cursor inside a call, as a JSON document."""
    call = call_at(source, line, col)
    found = _called_signatures(source, project, call, line, col) if call is not None else []
    return document(signatures=[
        signature.record(call) for signature in sorted(found, key=lambda found: found.origin)
    ])


def _called_signatures(source, project, call: CallSite, line: int, col: int) -> List[Signature]:
    """The signatures of whatever the written callee resolves to."""
    expression = parse_expression(call.callee)
    if expression is None:
        return []
    indent = cursor_indent(source.line_at(line, col), col)
    analyzer = project.analyzer_for(source)
    lookup = narrowed_lookup(analyzer, analyzer.visible(line, indent), line, indent)
    return signatures_of(analyzer.resolve(expression, lookup))


def signatures_of(value: Optional[Value]) -> List[Signature]:
    """Every signature a value can be called with."""
    reader = SIGNATURE_READERS.get(type(value))
    return reader(value) if reader is not None else []


# --------------------------------------------------------------------------
# Signatures of the values a callee can resolve to
# --------------------------------------------------------------------------


def _function_signatures(value: SourceFunction) -> List[Signature]:
    """A source function: its overloads when it declares any, else itself."""
    declared = _overloads(value) or [value.node]
    return [_declared_signature(value.analyzer, node) for node in declared]


def _class_signatures(value: SourceClass) -> List[Signature]:
    """A class is called through the ``__init__`` it or a base declares."""
    constructor = next(
        (
            symbol.value for symbol in value.members()
            if symbol.name == INIT and isinstance(symbol.value, SourceFunction)
        ),
        None,
    )
    parameters = _parameters(constructor.node.args, receiver=True) if constructor else ()
    docstring = docstring_of(value.node) or (
        docstring_of(constructor.node) if constructor else ""
    )
    return [Signature(
        name=value.node.name,
        parameters=parameters,
        returns="",
        docstring=docstring,
        origin=(value.analyzer.module_path, value.node.lineno),
    )]


def _stubbed_signatures(value: Stubbed) -> List[Signature]:
    """Stub signatures, described by the docstring the source module keeps."""
    written = [signature.docstring for signature in signatures_of(value.source)]
    return [
        signature if signature.docstring else _documented(signature, written)
        for signature in signatures_of(value.typed)
    ]


def _union_signatures(value: Union) -> List[Signature]:
    return [signature for option in value.options for signature in signatures_of(option)]


def _runtime_signatures(value: RuntimeValue) -> List[Signature]:
    """An installed function or class, read through the interpreter."""
    described = _introspected(value.obj)
    if described is None:
        return []
    name, _ = runtime_names(value.obj)
    line, path = source_position(value.obj)
    return [Signature(
        name=name,
        parameters=tuple(_runtime_parameter(parameter) for parameter in described.parameters.values()),
        returns=_annotation(described.return_annotation),
        docstring=inspect.getdoc(value.obj) or "",
        origin=(path, line),
    )]


SIGNATURE_READERS = {
    SourceFunction: _function_signatures,
    SourceClass: _class_signatures,
    Stubbed: _stubbed_signatures,
    Union: _union_signatures,
    RuntimeValue: _runtime_signatures,
}


def _documented(signature: Signature, written: List[str]) -> Signature:
    """A stub signature carrying the first docstring the source module has."""
    return replace(signature, docstring=next((found for found in written if found), ""))


def _overloads(value: SourceFunction) -> List[ast.AST]:
    """Every `@overload` declaration of a function's name in its own scope."""
    scope = value.analyzer.scope_of(value.node).parent
    return [
        symbol.node
        for symbol in value.analyzer.bindings(scope)
        if symbol.name == value.node.name and _is_overload(symbol.node)
    ]


def _is_overload(node: Optional[ast.AST]) -> bool:
    if not isinstance(node, FUNCTION_NODES):
        return False
    return any(_decorator_name(decorator) == OVERLOAD for decorator in node.decorator_list)


def _decorator_name(node: ast.expr) -> str:
    """The name a decorator is written with, ignoring what it is applied to."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


# --------------------------------------------------------------------------
# Declared parameters, as the spec writes them
# --------------------------------------------------------------------------


def _declared_signature(analyzer, node: ast.AST) -> Signature:
    """The signature a `def` statement declares."""
    return Signature(
        name=node.name,
        parameters=_parameters(node.args, receiver=_is_method(analyzer, node)),
        returns=ast.unparse(node.returns) if node.returns is not None else "",
        docstring=docstring_of(node),
        origin=(analyzer.module_path, node.lineno),
    )


def _is_method(analyzer, node: ast.AST) -> bool:
    """Whether a function takes a receiver its callers never write."""
    scope = analyzer.scope_of(node)
    if scope.parent is None or scope.parent.kind != CLASS_SCOPE:
        return False
    return not any(
        _decorator_name(decorator) == STATICMETHOD for decorator in node.decorator_list
    )


def _parameters(arguments: ast.arguments, receiver: bool) -> Tuple[Parameter, ...]:
    """The declared parameters of a function, the receiver left out."""
    positional = arguments.posonlyargs + arguments.args
    defaults = _defaults(arguments, positional)
    declared = [
        Parameter(argument.arg, _written(argument, defaults.get(argument.arg)))
        for argument in (positional[1:] if receiver else positional)
    ]
    declared += _starred(arguments.vararg, VARARG)
    declared += [
        Parameter(argument.arg, _written(argument, defaults.get(argument.arg)), KEYWORD)
        for argument in arguments.kwonlyargs
    ]
    return tuple(declared + _starred(arguments.kwarg, KWARG))


def _defaults(arguments: ast.arguments, positional: List[ast.arg]) -> Dict[str, ast.expr]:
    """The default value declared for each parameter that has one."""
    given = dict(zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults))
    given.update(zip(arguments.kwonlyargs, arguments.kw_defaults))
    return {argument.arg: default for argument, default in given.items() if default is not None}


def _starred(argument: Optional[ast.arg], kind: str) -> List[Parameter]:
    """The `*args` or `**kwargs` parameter, when one is declared."""
    if argument is None:
        return []
    return [Parameter(argument.arg, _written(argument, None, STARS[kind]), kind)]


def _written(argument: ast.arg, default: Optional[ast.expr], star: str = "") -> str:
    """One parameter, spelled the way the spec spells it."""
    written = f"{star}{argument.arg}"
    if argument.annotation is not None:
        written += f": {ast.unparse(argument.annotation)}"
    if default is not None:
        written += f"={ast.unparse(default)}"
    return written


# --------------------------------------------------------------------------
# Which parameter the cursor is on
# --------------------------------------------------------------------------


def bound_index(parameters: Tuple[Parameter, ...], call: CallSite) -> Optional[int]:
    """The parameter the argument under the cursor binds to, as Python binds it.

    A keyword argument names its parameter; a positional one takes the next
    free slot. An argument the declaration has no room for lands in `*args`
    or `**kwargs` when they are declared, and nowhere when they are not.
    """
    if call.keyword is not None:
        named = _index_of(parameters, lambda parameter: parameter.name == call.keyword)
        return named if named is not None else _index_of_kind(parameters, KWARG)
    slots = [index for index, parameter in enumerate(parameters) if parameter.kind == POSITIONAL]
    if call.rank < len(slots):
        return slots[call.rank]
    return _index_of_kind(parameters, VARARG)


def _index_of_kind(parameters: Tuple[Parameter, ...], kind: str) -> Optional[int]:
    return _index_of(parameters, lambda parameter: parameter.kind == kind)


def _index_of(parameters: Tuple[Parameter, ...], wanted) -> Optional[int]:
    return next(
        (index for index, parameter in enumerate(parameters) if wanted(parameter)), None
    )


# --------------------------------------------------------------------------
# Signatures of installed callables
# --------------------------------------------------------------------------


def _introspected(obj) -> Optional[inspect.Signature]:
    """The signature the interpreter reports, if it can report one."""
    try:
        return inspect.signature(obj)
    except (TypeError, ValueError):
        return None


def _runtime_parameter(parameter: inspect.Parameter) -> Parameter:
    kind = RUNTIME_KINDS.get(parameter.kind, POSITIONAL)
    written = f"{STARS.get(kind, '')}{parameter.name}{_annotated(parameter)}"
    if parameter.default is not inspect.Parameter.empty:
        written += f"={parameter.default!r}"
    return Parameter(parameter.name, written, kind)


def _annotated(parameter: inspect.Parameter) -> str:
    annotation = _annotation(parameter.annotation)
    return f": {annotation}" if annotation else ""


def _annotation(annotation) -> str:
    """How an annotation read from the interpreter is written out."""
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", str(annotation))
