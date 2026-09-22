"""What a callable declares and which parameter a call is currently on.

A :class:`Signature` is built once -- when a ``def`` is recorded or a live
object is inspected -- and rendered on demand.  Binding an argument to a
parameter follows Python's own rules: positional arguments fill the positional
parameters left to right, a keyword argument picks the parameter of that name,
and whatever is left over lands in ``*args`` or ``**kwargs`` when the signature
declares them.
"""

from __future__ import annotations

import ast
import enum
import inspect
from dataclasses import dataclass


class Kind(enum.Enum):
    """How an argument may be supplied for a parameter."""

    POSITIONAL_ONLY = "positional only"
    POSITIONAL = "positional or keyword"
    KEYWORD_ONLY = "keyword only"
    VAR_POSITIONAL = "collects the extra positional arguments"
    VAR_KEYWORD = "collects the unknown keyword arguments"


_STARS = {Kind.VAR_POSITIONAL: "*", Kind.VAR_KEYWORD: "**"}
_POSITIONAL = (Kind.POSITIONAL_ONLY, Kind.POSITIONAL)
_NAMED = (Kind.POSITIONAL, Kind.KEYWORD_ONLY)
_RUNTIME_KINDS = {
    inspect.Parameter.POSITIONAL_ONLY: Kind.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD: Kind.POSITIONAL,
    inspect.Parameter.KEYWORD_ONLY: Kind.KEYWORD_ONLY,
    inspect.Parameter.VAR_POSITIONAL: Kind.VAR_POSITIONAL,
    inspect.Parameter.VAR_KEYWORD: Kind.VAR_KEYWORD,
}


@dataclass(frozen=True)
class Parameter:
    """One declared parameter, as it was written."""

    name: str
    kind: Kind
    annotation: str = ""
    default: str = ""

    def render(self) -> str:
        """``name``, ``name: type``, ``name=default`` or ``*args``, as declared."""
        text = _STARS.get(self.kind, "") + self.name
        if self.annotation:
            text = f"{text}: {self.annotation}"
        return f"{text}={self.default}" if self.default else text


@dataclass(frozen=True)
class Signature:
    """The parameters and result of one callable.

    ``module_path`` and ``line`` are where the signature was declared; they are
    not reported, they only order the several signatures a name can have.
    """

    name: str
    params: tuple[Parameter, ...] = ()
    returns: str = ""
    docstring: str = ""
    module_path: str = ""
    line: int = 0

    @property
    def description(self) -> str:
        rendered = ", ".join(param.render() for param in self.params)
        arrow = f" -> {self.returns}" if self.returns else ""
        return f"def {self.name}({rendered}){arrow}"

    def position(self, name: str) -> int:
        """Where ``name`` may be passed positionally; ``-1`` when it may not be."""
        positional = [param.name for param in self.params if param.kind in _POSITIONAL]
        return positional.index(name) if name in positional else -1

    def parameter(self, position: int, keyword: str | None) -> int | None:
        """Which parameter an argument binds to, or ``None`` when none can take it."""
        if keyword is not None:
            return next((index for index, param in enumerate(self.params)
                         if param.name == keyword and param.kind in _NAMED),
                        self._collector(Kind.VAR_KEYWORD))
        positional = [index for index, param in enumerate(self.params)
                      if param.kind in _POSITIONAL]
        if position < len(positional):
            return positional[position]
        return self._collector(Kind.VAR_POSITIONAL)

    def _collector(self, kind: Kind) -> int | None:
        return next((index for index, param in enumerate(self.params) if param.kind is kind), None)


@dataclass(frozen=True)
class SignatureHelp:
    """One signature reported against the call the cursor is writing."""

    signature: Signature
    index: int | None

    def as_dict(self) -> dict[str, object]:
        return {"name": self.signature.name,
                "params": [param.render() for param in self.signature.params],
                "index": self.index,
                "description": self.signature.description,
                "docstring": self.signature.docstring}


def from_function(node: ast.FunctionDef | ast.AsyncFunctionDef, module_path: str,
                  receiver: bool) -> Signature:
    """The signature a ``def`` declares; ``receiver`` drops its ``self`` or ``cls``."""
    params = declared(node.args)
    return Signature(node.name, params[1:] if receiver else params,
                     ast.unparse(node.returns) if node.returns else "",
                     ast.get_docstring(node) or "", module_path, node.lineno)


def from_lambda(node: ast.Lambda, module_path: str) -> Signature:
    """The signature of a lambda, which has no name of its own to report."""
    return Signature("<lambda>", declared(node.args), module_path=module_path, line=node.lineno)


def from_callable(obj: object, name: str) -> list[Signature]:
    """The signature of a live object, when it can be inspected at all."""
    try:
        found = inspect.signature(obj)
    except (TypeError, ValueError):
        # Plenty of builtins carry no introspectable signature; they have none.
        return []
    return [Signature(name, tuple(_live(param) for param in found.parameters.values()),
                      _annotation(found.return_annotation), inspect.getdoc(obj) or "")]


def declared(args: ast.arguments) -> tuple[Parameter, ...]:
    """The parameters ``args`` declares, in the order a call supplies them."""
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    params = [_parameter(argument,
                         Kind.POSITIONAL_ONLY if index < len(args.posonlyargs) else Kind.POSITIONAL,
                         default)
              for index, (argument, default) in enumerate(zip(positional, defaults))]
    if args.vararg is not None:
        params.append(_parameter(args.vararg, Kind.VAR_POSITIONAL, None))
    params += [_parameter(argument, Kind.KEYWORD_ONLY, default)
               for argument, default in zip(args.kwonlyargs, args.kw_defaults)]
    if args.kwarg is not None:
        params.append(_parameter(args.kwarg, Kind.VAR_KEYWORD, None))
    return tuple(params)


def _parameter(argument: ast.arg, kind: Kind, default: ast.expr | None) -> Parameter:
    return Parameter(argument.arg, kind,
                     ast.unparse(argument.annotation) if argument.annotation else "",
                     ast.unparse(default) if default is not None else "")


def _live(param: inspect.Parameter) -> Parameter:
    return Parameter(param.name, _RUNTIME_KINDS[param.kind], _annotation(param.annotation),
                     "" if param.default is inspect.Parameter.empty else repr(param.default))


def _annotation(annotation: object) -> str:
    """A runtime annotation as source text; an absent one reads as no annotation."""
    if annotation is inspect.Parameter.empty:
        return ""
    return inspect.formatannotation(annotation)
