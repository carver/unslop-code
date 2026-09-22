"""Turning a parsed module into a scope tree of lazily resolved bindings."""

from __future__ import annotations

import ast
from typing import Callable, Iterator, TYPE_CHECKING

from .cursor import name_column
from .definitions import Definition
from .inference import infer, instantiate
from .narrowing import narrowings
from .scopes import Binding, Scope
from .values import (
    NONE,
    UNKNOWN,
    Lazy,
    Param,
    SourceClass,
    SourceFunction,
    SourceInstance,
    Value,
    union,
)

if TYPE_CHECKING:
    from .project import ModuleInfo, Project


class ScopeBuilder:
    """Walks a module body and records every name it binds.

    Nothing is resolved here: each binding carries a callable that produces its
    value on demand, so imports are only performed for names that a request
    actually asks about.
    """

    def __init__(self, project: "Project", module: "ModuleInfo") -> None:
        self.project = project
        self.module = module

    def build(self, tree: ast.Module, last_line: int) -> Scope:
        scope = Scope("module", self.module.name, 1, last_line)
        self._body(scope, tree.body, last_line)
        return scope

    def _body(self, scope: Scope, body: list[ast.stmt], limit: int,
              owner: SourceClass | None = None, conditional: bool = False) -> None:
        """Record the bindings of a statement list belonging to ``scope``."""
        for statement, boundary in zip(body, _boundaries(body, limit)):
            self._statement(scope, statement, boundary, owner, conditional)
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._implicit(scope, statement, conditional)

    def _statement(self, scope: Scope, node: ast.stmt, boundary: int,
                   owner: SourceClass | None, conditional: bool) -> None:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                self._function(scope, node, boundary, owner, conditional)
            case ast.ClassDef():
                self._class(scope, node, boundary, conditional)
            case ast.Import():
                self._import(scope, node, conditional)
            case ast.ImportFrom(module=module, level=level):
                self._import_from(scope, node, module or "", level, conditional)
            case ast.Assign(targets=targets, value=value):
                for target in targets:
                    self._bind(scope, target, node,
                               lambda: infer(value, scope, node.lineno), conditional)
            case ast.AnnAssign(target=target, value=value, annotation=annotation):
                self._bind(scope, target, node,
                           self._annotated(scope, node, value, annotation), conditional)
            case ast.AugAssign(target=target):
                self._bind(scope, target, node, lambda: UNKNOWN, conditional)
            case ast.For(target=target) | ast.AsyncFor(target=target):
                self._bind(scope, target, node, lambda: UNKNOWN, conditional)
                self._body(scope, node.body + node.orelse, boundary, owner, True)
            case ast.While():
                self._body(scope, node.body + node.orelse, boundary, owner, True)
            case ast.If():
                self._branches(scope, node, boundary, owner)
            case ast.With(items=items) | ast.AsyncWith(items=items):
                for item in items:
                    if item.optional_vars is not None:
                        self._bind(scope, item.optional_vars, node,
                                   lambda item=item: infer(item.context_expr, scope, node.lineno),
                                   conditional)
                self._body(scope, node.body, boundary, owner, conditional)
            case ast.Try(handlers=handlers):
                for handler in handlers:
                    if handler.name:
                        site = self._site(scope, handler.name, "statement", handler.lineno,
                                          handler.col_offset, self._describe(handler))
                        scope.bindings.append(Binding(handler.name, site, lambda: UNKNOWN, True))
                    self._body(scope, handler.body, boundary, owner, True)
                self._body(scope, node.body + node.orelse + node.finalbody, boundary,
                           owner, conditional)
            case ast.Match(cases=cases):
                for case in cases:
                    self._body(scope, case.body, boundary, owner, True)

    # -- definitions -------------------------------------------------------

    def _function(self, scope: Scope, node: ast.FunctionDef | ast.AsyncFunctionDef,
                  boundary: int, owner: SourceClass | None, conditional: bool) -> None:
        site = self._site(scope, node.name, "function", node.lineno, name_column(node),
                          f"def {node.name}({ast.unparse(node.args)})",
                          ast.get_docstring(node) or "")
        inner = scope.child("function", node.name, node.lineno, boundary)
        value = SourceFunction(site, Lazy(lambda: self._returns(node, inner)))
        scope.bindings.append(Binding(node.name, site, lambda: value, conditional))
        receiver = _receiver(owner, node)
        for position, argument in enumerate(_arguments(node.args)):
            inner.bindings.append(
                self._param(inner, argument, receiver if position == 0 else None))
        if owner is not None and node.name == "__init__":
            owner.self_attributes.extend(self._self_attributes(node, inner, scope))
        self._body(inner, node.body, boundary)

    def _class(self, scope: Scope, node: ast.ClassDef, boundary: int, conditional: bool) -> None:
        site = self._site(scope, node.name, "class", node.lineno, name_column(node),
                          f"class {node.name}", ast.get_docstring(node) or "")
        inner = scope.child("class", node.name, node.lineno, boundary)
        value = SourceClass(
            site=site,
            scope=inner,
            bases=lambda: [infer(base, scope, node.lineno) for base in node.bases],
            self_attributes=[],
        )
        scope.bindings.append(Binding(node.name, site, lambda: value, conditional))
        self._body(inner, node.body, boundary, owner=value)

    def _branches(self, scope: Scope, node: ast.If, boundary: int,
                  owner: SourceClass | None) -> None:
        """Both arms of an ``if``, each narrowed by what its test proves."""
        divide = _first_line(node.orelse[0]) - 1 if node.orelse else boundary
        scope.narrowings += narrowings(node.test, scope, node.body[0].lineno, divide, True)
        self._body(scope, node.body, divide, owner, True)
        if node.orelse:
            scope.narrowings += narrowings(node.test, scope, node.orelse[0].lineno,
                                           boundary, False)
            self._body(scope, node.orelse, boundary, owner, True)

    def _import(self, scope: Scope, node: ast.Import, conditional: bool) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            dotted = alias.name if alias.asname else bound
            site = self._site(scope, bound, "module", alias.lineno, name_column(alias),
                              self._describe(node))
            scope.bindings.append(Binding(
                bound, site,
                lambda dotted=dotted: self.project.module(dotted) or UNKNOWN, conditional))

    def _import_from(self, scope: Scope, node: ast.ImportFrom, module: str, level: int,
                     conditional: bool) -> None:
        for alias in node.names:
            if alias.name == "*":
                self._star(scope, node, module, level, conditional)
                continue
            bound = alias.asname or alias.name
            site = self._site(scope, bound, "", alias.lineno, name_column(alias),
                              self._describe(node))
            scope.bindings.append(Binding(
                bound, site, lambda name=alias.name: self._imported(module, level, name),
                conditional))

    def _star(self, scope: Scope, node: ast.ImportFrom, module: str, level: int,
              conditional: bool) -> None:
        """Expand ``from x import *`` into one binding per exported name."""
        container = self.project.module(module, level)
        if container is None:
            return
        for symbol in container.attributes():
            site = self._site(scope, symbol.name, "", node.lineno, node.col_offset,
                              self._describe(node))
            scope.bindings.append(Binding(
                symbol.name, site, lambda symbol=symbol: symbol.value, conditional))

    # -- resolvers ---------------------------------------------------------

    def _imported(self, module: str, level: int, name: str) -> Value:
        """Resolve ``name`` as an attribute of ``module``, then as a submodule."""
        container = self.project.module(module, level) if module else None
        attribute = container.attribute(name) if container is not None else None
        submodule = ".".join(part for part in (module, name) if part)
        return attribute or self.project.module(submodule, level) or UNKNOWN

    def _param(self, scope: Scope, argument: ast.arg, receiver: Value | None) -> Binding:
        site = self._site(scope, argument.arg, "param", argument.lineno, argument.col_offset,
                          f"param {ast.unparse(argument)}")
        return Binding(argument.arg, site, self._parameter(scope, argument, receiver))

    def _parameter(self, scope: Scope, argument: ast.arg,
                   receiver: Value | None) -> Callable[[], Value]:
        if receiver is not None:
            return lambda: Param(receiver)
        annotation = argument.annotation
        if annotation is None:
            return lambda: Param()
        return lambda: Param(instantiate(infer(annotation, scope, argument.lineno)))

    def _annotated(self, scope: Scope, node: ast.AnnAssign, value: ast.expr | None,
                   annotation: ast.expr) -> Callable[[], Value]:
        if value is not None:
            return lambda: infer(value, scope, node.lineno)
        return lambda: instantiate(infer(annotation, scope, node.lineno))

    def _returns(self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope) -> Value:
        """What calling the function yields: its annotation, else its returns.

        A function that never returns a value -- no ``return`` at all, or a
        bare one -- yields ``None``.
        """
        if node.returns is not None:
            return instantiate(infer(node.returns, scope, node.lineno))
        returned = [infer(statement.value, scope, statement.lineno) if statement.value else NONE
                    for statement in _return_statements(node)]
        return union(returned) if returned else NONE

    def _self_attributes(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                         scope: Scope, owner: Scope) -> Iterator[Binding]:
        """``self.x = ...`` assignments made by ``__init__``.

        The bindings belong to the class, so they are qualified by ``owner``,
        the class body scope, while their values are read in the method.
        """
        parameters = _arguments(node.args)
        if not parameters:
            return
        receiver = parameters[0].arg
        for statement, target, value in _assignments(node):
            match target:
                case ast.Attribute(value=ast.Name(id=name), attr=attribute) if name == receiver:
                    site = self._site(owner, attribute, "statement", target.lineno,
                                      target.end_col_offset - len(attribute),
                                      self._describe(statement))
                    yield Binding(attribute, site,
                                  lambda value=value: infer(value, scope, value.lineno))

    # -- targets -----------------------------------------------------------

    def _bind(self, scope: Scope, target: ast.expr, statement: ast.stmt,
              resolver: Callable[[], Value], conditional: bool) -> None:
        """Record the names bound by an assignment target."""
        match target:
            case ast.Name(id=name):
                site = self._site(scope, name, "statement", target.lineno, target.col_offset,
                                  self._describe(statement))
                scope.bindings.append(Binding(name, site, resolver, conditional))
            case ast.Tuple(elts=elements) | ast.List(elts=elements):
                for element in elements:
                    self._bind(scope, element, statement, lambda: UNKNOWN, conditional)
            case ast.Starred(value=inner):
                self._bind(scope, inner, statement, lambda: UNKNOWN, conditional)

    def _implicit(self, scope: Scope, statement: ast.stmt, conditional: bool) -> None:
        """Bindings hidden inside expressions: walrus, comprehensions, patterns."""
        for node in _expressions(statement):
            match node:
                case ast.NamedExpr(target=target, value=value):
                    self._bind(scope, target, statement,
                               lambda: infer(value, scope, statement.lineno), conditional)
                case ast.comprehension(target=target):
                    self._bind(scope, target, statement, lambda: UNKNOWN, conditional)
                case ast.MatchAs(name=str() as name) | ast.MatchStar(name=str() as name):
                    site = self._site(scope, name, "statement", statement.lineno,
                                      statement.col_offset, self._describe(statement))
                    scope.bindings.append(Binding(name, site, lambda: UNKNOWN, conditional))

    # -- reporting ---------------------------------------------------------

    def _site(self, scope: Scope, name: str, kind: str, line: int, column: int,
              description: str, docstring: str = "") -> Definition:
        """Where a name is written down, as ``goto`` reports it.

        An empty ``kind`` defers to the value the name turns out to hold, which
        is how an imported name reports what it imported.
        """
        return Definition(name, kind, f"{scope.qualified}.{name}", self.module.path,
                          line, column, description, docstring)

    def _describe(self, node: ast.stmt) -> str:
        """The statement as written, with its line breaks and padding collapsed."""
        segment = ast.get_source_segment(self.module.text, node) or ast.unparse(node)
        return " ".join(segment.split())


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


def _assignments(node: ast.AST) -> Iterator[tuple[ast.stmt, ast.expr, ast.expr]]:
    """Every ``(statement, target, value)`` assigned anywhere inside ``node``."""
    for statement in ast.walk(node):
        match statement:
            case ast.Assign(targets=targets, value=value):
                yield from ((statement, target, value) for target in targets)
            case ast.AnnAssign(target=target, value=ast.expr() as value):
                yield statement, target, value


def _return_statements(node: ast.AST) -> Iterator[ast.Return]:
    """``return`` statements owned by a function, not by one nested in it."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, ast.Return):
            yield child
        yield from _return_statements(child)


def _expressions(node: ast.AST) -> Iterator[ast.AST]:
    """Expression nodes owned by ``node``, not descending into nested statements."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            continue
        yield child
        yield from _expressions(child)
