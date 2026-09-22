"""Turning a parsed module into a scope tree of lazily resolved definitions."""

from __future__ import annotations

import ast
from typing import Callable, Iterator, TYPE_CHECKING

from .inference import infer, instantiate
from .scopes import Definition, Scope
from .values import (
    UNKNOWN,
    Param,
    SourceClass,
    SourceFunction,
    SourceInstance,
    Value,
)

if TYPE_CHECKING:
    from .project import Project


class ScopeBuilder:
    """Walks a module body and records every name it binds.

    Nothing is resolved here: each definition carries a callable that produces
    its value on demand, so imports are only performed for names that a
    completion actually asks about.
    """

    def __init__(self, project: "Project") -> None:
        self.project = project

    def build(self, tree: ast.Module, last_line: int) -> Scope:
        module = Scope("module", 1, last_line)
        self._body(module, tree.body, last_line)
        return module

    def _body(self, scope: Scope, body: list[ast.stmt], limit: int,
              owner: SourceClass | None = None) -> None:
        """Record the bindings of a statement list belonging to ``scope``."""
        for statement, boundary in zip(body, _boundaries(body, limit)):
            self._statement(scope, statement, boundary, owner)
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._implicit(scope, statement)

    def _statement(self, scope: Scope, node: ast.stmt, boundary: int,
                   owner: SourceClass | None) -> None:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                self._function(scope, node, boundary, owner)
            case ast.ClassDef():
                self._class(scope, node, boundary)
            case ast.Import(names=aliases):
                self._import(scope, node.lineno, aliases)
            case ast.ImportFrom(names=aliases, module=module, level=level):
                self._import_from(scope, node.lineno, aliases, module or "", level)
            case ast.Assign(targets=targets, value=value):
                for target in targets:
                    self._bind(scope, target, lambda: infer(value, scope))
            case ast.AnnAssign(target=target, value=value, annotation=annotation):
                self._bind(scope, target, self._annotated(scope, value, annotation))
            case ast.AugAssign(target=target):
                self._bind(scope, target, lambda: UNKNOWN)
            case ast.For(target=target) | ast.AsyncFor(target=target):
                self._bind(scope, target, lambda: UNKNOWN)
                self._body(scope, node.body + node.orelse, boundary, owner)
            case ast.While() | ast.If():
                self._body(scope, node.body + node.orelse, boundary, owner)
            case ast.With(items=items) | ast.AsyncWith(items=items):
                for item in items:
                    if item.optional_vars is not None:
                        self._bind(scope, item.optional_vars,
                                   lambda item=item: infer(item.context_expr, scope))
                self._body(scope, node.body, boundary, owner)
            case ast.Try(handlers=handlers):
                for handler in handlers:
                    if handler.name:
                        scope.definitions.append(
                            Definition(handler.name, handler.lineno, lambda: UNKNOWN))
                    self._body(scope, handler.body, boundary, owner)
                self._body(scope, node.body + node.orelse + node.finalbody, boundary, owner)
            case ast.Match(cases=cases):
                for case in cases:
                    self._body(scope, case.body, boundary, owner)

    # -- definitions -------------------------------------------------------

    def _function(self, scope: Scope, node: ast.FunctionDef | ast.AsyncFunctionDef,
                  boundary: int, owner: SourceClass | None) -> None:
        scope.definitions.append(
            Definition(node.name, node.lineno, lambda: SourceFunction(node.name)))
        inner = scope.child("function", node.body[0].lineno, boundary)
        receiver = _receiver(owner, node)
        for position, argument in enumerate(_arguments(node.args)):
            inner.definitions.append(Definition(
                argument.arg, node.lineno,
                self._parameter(inner, argument, receiver if position == 0 else None)))
        if owner is not None and node.name == "__init__":
            owner.self_attributes.extend(self._self_attributes(node, inner))
        self._body(inner, node.body, boundary)

    def _class(self, scope: Scope, node: ast.ClassDef, boundary: int) -> None:
        inner = scope.child("class", node.body[0].lineno, boundary)
        value = SourceClass(
            name=node.name,
            scope=inner,
            bases=lambda: [infer(base, scope) for base in node.bases],
            self_attributes=[],
        )
        scope.definitions.append(Definition(node.name, node.lineno, lambda: value))
        self._body(inner, node.body, boundary, owner=value)

    def _import(self, scope: Scope, line: int, aliases: list[ast.alias]) -> None:
        for alias in aliases:
            bound = alias.asname or alias.name.split(".")[0]
            dotted = alias.name if alias.asname else bound
            scope.definitions.append(Definition(
                bound, line, lambda dotted=dotted: self.project.module(dotted) or UNKNOWN))

    def _import_from(self, scope: Scope, line: int, aliases: list[ast.alias],
                     module: str, level: int) -> None:
        for alias in aliases:
            if alias.name == "*":
                self._star(scope, line, module, level)
                continue
            scope.definitions.append(Definition(
                alias.asname or alias.name, line,
                lambda name=alias.name: self._imported(module, level, name)))

    def _star(self, scope: Scope, line: int, module: str, level: int) -> None:
        """Expand ``from x import *`` into one definition per exported name."""
        container = self.project.module(module, level)
        if container is None:
            return
        for symbol in container.attributes():
            scope.definitions.append(Definition(symbol.name, line, lambda symbol=symbol: symbol.value))

    # -- resolvers ---------------------------------------------------------

    def _imported(self, module: str, level: int, name: str) -> Value:
        """Resolve ``name`` as an attribute of ``module``, then as a submodule."""
        container = self.project.module(module, level) if module else None
        attribute = container.attribute(name) if container is not None else None
        submodule = ".".join(part for part in (module, name) if part)
        return attribute or self.project.module(submodule, level) or UNKNOWN

    def _parameter(self, scope: Scope, argument: ast.arg,
                   receiver: Value | None) -> Callable[[], Value]:
        if receiver is not None:
            return lambda: Param(receiver)
        annotation = argument.annotation
        if annotation is None:
            return lambda: Param()
        return lambda: Param(instantiate(infer(annotation, scope)))

    def _annotated(self, scope: Scope, value: ast.expr | None,
                   annotation: ast.expr) -> Callable[[], Value]:
        if value is not None:
            return lambda: infer(value, scope)
        return lambda: instantiate(infer(annotation, scope))

    def _self_attributes(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                         scope: Scope) -> Iterator[Definition]:
        """``self.x = ...`` assignments made by ``__init__``."""
        parameters = _arguments(node.args)
        if not parameters:
            return
        receiver = parameters[0].arg
        for target, value in _assignments(node):
            match target:
                case ast.Attribute(value=ast.Name(id=name), attr=attribute) if name == receiver:
                    yield Definition(attribute, target.lineno,
                                     lambda value=value: infer(value, scope))

    # -- targets -----------------------------------------------------------

    def _bind(self, scope: Scope, target: ast.expr, resolver: Callable[[], Value]) -> None:
        """Record the names bound by an assignment target."""
        match target:
            case ast.Name(id=name):
                scope.definitions.append(Definition(name, target.lineno, resolver))
            case ast.Tuple(elts=elements) | ast.List(elts=elements):
                for element in elements:
                    self._bind(scope, element, lambda: UNKNOWN)
            case ast.Starred(value=inner):
                self._bind(scope, inner, lambda: UNKNOWN)

    def _implicit(self, scope: Scope, statement: ast.stmt) -> None:
        """Bindings hidden inside expressions: walrus, comprehensions, patterns."""
        for node in _expressions(statement):
            match node:
                case ast.NamedExpr(target=target, value=value):
                    self._bind(scope, target, lambda: infer(value, scope))
                case ast.comprehension(target=target):
                    self._bind(scope, target, lambda: UNKNOWN)
                case ast.MatchAs(name=str() as name) | ast.MatchStar(name=str() as name):
                    scope.definitions.append(Definition(name, statement.lineno, lambda: UNKNOWN))


def _boundaries(body: list[ast.stmt], limit: int) -> Iterator[int]:
    """The last line each statement may claim: up to the next sibling."""
    for index, statement in enumerate(body):
        following = body[index + 1] if index + 1 < len(body) else None
        yield limit if following is None else _first_line(following) - 1


def _first_line(statement: ast.stmt) -> int:
    decorators = getattr(statement, "decorator_list", [])
    return min([statement.lineno] + [decorator.lineno for decorator in decorators])


def _arguments(args: ast.arguments) -> list[ast.arg]:
    optional = [args.vararg, args.kwarg]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs,
            *[argument for argument in optional if argument is not None]]


def _receiver(owner: SourceClass | None,
              node: ast.FunctionDef | ast.AsyncFunctionDef) -> Value | None:
    """What the first parameter of a method is bound to, if anything."""
    decorators = {decorator.id for decorator in node.decorator_list
                  if isinstance(decorator, ast.Name)}
    if owner is None or "staticmethod" in decorators:
        return None
    return owner if "classmethod" in decorators else SourceInstance(owner)


def _assignments(node: ast.AST) -> Iterator[tuple[ast.expr, ast.expr]]:
    """Every ``(target, value)`` pair assigned anywhere inside ``node``."""
    for statement in ast.walk(node):
        match statement:
            case ast.Assign(targets=targets, value=value):
                yield from ((target, value) for target in targets)
            case ast.AnnAssign(target=target, value=ast.expr() as value):
                yield target, value


def _expressions(node: ast.AST) -> Iterator[ast.AST]:
    """Expression nodes owned by ``node``, not descending into nested statements."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            continue
        yield child
        yield from _expressions(child)
