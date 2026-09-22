"""Reading and rendering the parameters a function declares.

A parameter is written the way the source writes it -- annotation after a
colon, default after an equals sign -- and it also carries how a caller may
pass it, which is what decides the parameter the cursor is currently on.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

#: How an argument can reach a parameter.
POSITIONAL, KEYWORD_ONLY, VARARG, KWARG = range(4)


@dataclass(frozen=True)
class Parameter:
    """One declared parameter, as written and as it can be passed."""

    name: str
    text: str
    kind: int


@dataclass(frozen=True)
class Argument:
    """Which argument of a call the cursor sits in."""

    position: int = 0
    keyword: str | None = None


def declared(args: ast.arguments) -> list[ast.arg]:
    """Every parameter of a signature, in declaration order."""
    optional = [args.vararg, args.kwarg]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *[a for a in optional if a]]


def positional_index(args: ast.arguments, name: str) -> int | None:
    """Where a parameter sits among those a caller may pass positionally."""
    positional = [arg.arg for arg in [*args.posonlyargs, *args.args]]
    return positional.index(name) if name in positional else None


def annotation(args: ast.arguments, name: str) -> ast.expr | None:
    """The annotation a signature gives one of its parameters."""
    return next((arg.annotation for arg in declared(args) if arg.arg == name), None)


def parameters(args: ast.arguments) -> list[Parameter]:
    """The parameter list of a signature, rendered in source order."""
    positional = [*args.posonlyargs, *args.args]
    found = [
        Parameter(arg.arg, _text(arg, default), POSITIONAL)
        for arg, default in zip(positional, _aligned(positional, args.defaults))
    ]
    if args.vararg:
        found.append(Parameter(args.vararg.arg, _text(args.vararg, None, "*"), VARARG))
    found += [
        Parameter(arg.arg, _text(arg, default), KEYWORD_ONLY)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults)
    ]
    if args.kwarg:
        found.append(Parameter(args.kwarg.arg, _text(args.kwarg, None, "**"), KWARG))
    return found


def index_of(parameters: tuple[Parameter, ...], argument: Argument) -> int | None:
    """The parameter an argument binds to, the way a call binds it.

    A name that no parameter answers to falls to `**kwargs`, and an argument
    past the last positional parameter falls to `*args`; without those there is
    no parameter to point at.
    """
    if argument.keyword is not None:
        named = _first(parameters, lambda p: p.name == argument.keyword and p.kind != VARARG)
        return named if named is not None else _first(parameters, _is(KWARG))
    positional = [parameter for parameter in parameters if parameter.kind == POSITIONAL]
    if argument.position < len(positional):
        return argument.position
    return _first(parameters, _is(VARARG))


def _is(kind: int):
    return lambda parameter: parameter.kind == kind


def _first(parameters, accepts) -> int | None:
    return next((index for index, p in enumerate(parameters) if accepts(p)), None)


def _aligned(positional: list[ast.arg], defaults: list[ast.expr]) -> list[ast.expr | None]:
    """Defaults line up with the end of the positional parameters."""
    return [None] * (len(positional) - len(defaults)) + list(defaults)


def _text(arg: ast.arg, default: ast.expr | None, stars: str = "") -> str:
    annotated = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
    value = f"={ast.unparse(default)}" if default is not None else ""
    return f"{stars}{arg.arg}{annotated}{value}"
