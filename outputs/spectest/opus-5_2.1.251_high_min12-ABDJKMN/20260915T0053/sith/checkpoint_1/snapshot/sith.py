#!/usr/bin/env python3
"""sith - a small static Python code-intelligence CLI.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]

Analyses a Python source file statically and prints ranked completions for the
given cursor position as compact JSON on STDOUT.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import importlib
import inspect
import io
import json
import keyword
import os
import sys
import types

IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
KEYWORDS = list(keyword.kwlist)
MAX_REPAIRS = 100
MAX_DEPTH = 10


class CliError(Exception):
    """Fatal, user-facing error: message to STDERR, exit 1."""


# ---------------------------------------------------------------------------
# Values
#
# A "value" is whatever a static expression resolves to.  Five flavours:
#   ObjValue          a real, live Python object (module / class / function / ...)
#   TypeInstance      an instance of a real class, without an actual object
#   StaticModule      a project file parsed as a module (never executed)
#   AstClass          a class defined in a parsed file
#   AstFunction       a function defined in a parsed file
#   AstInstance       an instance of an AstClass
# ---------------------------------------------------------------------------


class Value:
    __slots__ = ()


class ObjValue(Value):
    __slots__ = ("obj",)

    def __init__(self, obj):
        self.obj = obj


class TypeInstance(Value):
    __slots__ = ("cls",)

    def __init__(self, cls):
        self.cls = cls


class StaticModule(Value):
    __slots__ = ("analysis",)

    def __init__(self, analysis):
        self.analysis = analysis


class AstClass(Value):
    __slots__ = ("analysis", "node")

    def __init__(self, analysis, node):
        self.analysis = analysis
        self.node = node


class AstFunction(Value):
    __slots__ = ("analysis", "node")

    def __init__(self, analysis, node):
        self.analysis = analysis
        self.node = node


class AstInstance(Value):
    __slots__ = ("cls",)

    def __init__(self, cls):
        self.cls = cls


def kind_of_obj(obj):
    """Map a live object onto one of the spec's `type` values."""
    if isinstance(obj, types.ModuleType):
        return "module"
    if isinstance(obj, type):
        return "class"
    if inspect.isroutine(obj) or isinstance(
        obj,
        (
            types.WrapperDescriptorType,
            types.MethodWrapperType,
            types.MethodDescriptorType,
            types.ClassMethodDescriptorType,
        ),
    ):
        return "function"
    return "instance"


def describe_value(name, value):
    """Return (type, description) for a resolved value bound to `name`."""
    if value is None:
        return "statement", "statement"
    if isinstance(value, ObjValue):
        kind = kind_of_obj(value.obj)
        if kind == "module":
            return "module", "module " + name
        if kind == "class":
            return "class", "class " + name
        if kind == "function":
            return "function", "def " + name + "(...)"
        return "instance", "instance of " + type(value.obj).__name__
    if isinstance(value, TypeInstance):
        return "instance", "instance of " + value.cls.__name__
    if isinstance(value, StaticModule):
        return "module", "module " + name
    if isinstance(value, AstClass):
        return "class", "class " + name
    if isinstance(value, AstFunction):
        return "function", "def " + name + "(...)"
    if isinstance(value, AstInstance):
        return "instance", "instance of " + value.cls.node.name
    return "statement", "statement"


# ---------------------------------------------------------------------------
# Bindings and scopes
# ---------------------------------------------------------------------------


class Binding:
    __slots__ = ("name", "form", "lineno", "node", "value_node", "annotation",
                 "imp", "scope", "first_param")

    def __init__(self, name, form, lineno, scope, node=None, value_node=None,
                 annotation=None, imp=None, first_param=False):
        self.name = name
        self.form = form              # def|class|param|import|assign
        self.lineno = lineno
        self.scope = scope
        self.node = node
        self.value_node = value_node
        self.annotation = annotation
        self.imp = imp                # (module, attr, level) for imports
        self.first_param = first_param


class Scope:
    __slots__ = ("kind", "node", "parent", "children", "bindings",
                 "star_imports", "lineno", "end_lineno", "indent", "_ext")

    def __init__(self, kind, node, parent):
        self.kind = kind              # module|function|class|lambda
        self.node = node
        self.parent = parent
        self.children = []
        self.bindings = []
        self.star_imports = []        # list of (lineno, module, level)
        if parent is not None:
            parent.children.append(self)
        self.lineno = getattr(node, "lineno", 0) if node is not None else 0
        self.end_lineno = getattr(node, "end_lineno", 0) if node is not None else 0
        self.indent = getattr(node, "col_offset", -1) if node is not None else -1
        self._ext = None

    def extended_end(self, lines):
        """End line of the block, extended through blank / deeper-indented lines.

        The AST's end_lineno stops at the last complete statement; an editor
        cursor is usually below that, on a fresh indented line.
        """
        if self._ext is not None:
            return self._ext
        n = len(lines)
        ln = self.end_lineno + 1
        while ln <= n:
            text = lines[ln - 1]
            if not text.strip():
                ln += 1
                continue
            indent = len(text) - len(text.lstrip())
            if indent > self.indent:
                ln += 1
                continue
            break
        self._ext = max(self.end_lineno, ln - 1)
        return self._ext

    def contains(self, line, indent, lines):
        if self.kind == "module":
            return True
        if self.kind == "lambda":
            return self.lineno <= line <= self.end_lineno
        if line <= self.lineno:
            return False
        if line <= self.end_lineno:
            return True
        if line <= self.extended_end(lines) and indent > self.indent:
            return True
        return False


def _args_of(node):
    a = node.args
    out = list(getattr(a, "posonlyargs", [])) + list(a.args)
    if a.vararg:
        out.append(a.vararg)
    out.extend(a.kwonlyargs)
    if a.kwarg:
        out.append(a.kwarg)
    return out


class ScopeBuilder(ast.NodeVisitor):
    """Builds the scope tree and records every name binding with its line."""

    def __init__(self):
        self.module = Scope("module", None, None)
        self.stack = [self.module]

    @property
    def cur(self):
        return self.stack[-1]

    def bind(self, name, form, lineno, **kw):
        if not name:
            return
        self.cur.bindings.append(Binding(name, form, lineno, self.cur, **kw))

    # -- functions / classes / lambdas ------------------------------------
    def _function(self, node):
        self.bind(node.name, "def", node.lineno, node=node)
        for dec in node.decorator_list:
            self.visit(dec)
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)
        scope = Scope("function", node, self.cur)
        self.stack.append(scope)
        for i, arg in enumerate(_args_of(node)):
            self.bind(arg.arg, "param", node.lineno, node=arg,
                      annotation=arg.annotation, first_param=(i == 0))
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node):
        self.bind(node.name, "class", node.lineno, node=node)
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        scope = Scope("class", node, self.cur)
        self.stack.append(scope)
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    def visit_Lambda(self, node):
        for d in node.args.defaults:
            self.visit(d)
        scope = Scope("lambda", node, self.cur)
        self.stack.append(scope)
        for i, arg in enumerate(_args_of(node)):
            self.bind(arg.arg, "param", node.lineno, node=arg, first_param=(i == 0))
        self.visit(node.body)
        self.stack.pop()

    # -- assignment-ish binding forms -------------------------------------
    def _target(self, target, value_node, lineno, annotation=None):
        if isinstance(target, ast.Name):
            self.bind(target.id, "assign", lineno, node=target,
                      value_node=value_node, annotation=annotation)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._target(elt, None, lineno)
        elif isinstance(target, ast.Starred):
            self._target(target.value, None, lineno)

    def visit_Assign(self, node):
        for t in node.targets:
            self._target(t, node.value, node.lineno)
        self.visit(node.value)

    def visit_AnnAssign(self, node):
        self._target(node.target, node.value, node.lineno,
                     annotation=node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node):
        self._target(node.target, None, node.lineno)
        self.visit(node.value)

    def visit_NamedExpr(self, node):
        self._target(node.target, node.value, node.lineno)
        self.visit(node.value)

    def _for(self, node):
        self._target(node.target, None, node.lineno)
        self.visit(node.iter)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    visit_For = _for
    visit_AsyncFor = _for

    def _with(self, node):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._target(item.optional_vars, None, node.lineno)
        for stmt in node.body:
            self.visit(stmt)

    visit_With = _with
    visit_AsyncWith = _with

    def visit_ExceptHandler(self, node):
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self.bind(node.name, "assign", node.lineno)
        for stmt in node.body:
            self.visit(stmt)

    def _comp(self, node):
        for gen in node.generators:
            self._target(gen.target, None, getattr(node, "lineno", 0))
        self.generic_visit(node)

    visit_ListComp = _comp
    visit_SetComp = _comp
    visit_DictComp = _comp
    visit_GeneratorExp = _comp

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                self.bind(alias.asname, "import", node.lineno,
                          imp=(alias.name, None, 0))
            else:
                root = alias.name.split(".")[0]
                self.bind(root, "import", node.lineno, imp=(root, None, 0))

    def visit_ImportFrom(self, node):
        module = node.module or ""
        level = node.level or 0
        for alias in node.names:
            if alias.name == "*":
                self.cur.star_imports.append((node.lineno, module, level))
                continue
            bound = alias.asname or alias.name
            self.bind(bound, "import", node.lineno,
                      imp=(module, alias.name, level))

    def visit_Match(self, node):
        self.visit(node.subject)
        for case in node.cases:
            self._pattern(case.pattern, node.lineno)
            if case.guard is not None:
                self.visit(case.guard)
            for stmt in case.body:
                self.visit(stmt)

    def _pattern(self, pat, lineno):
        for sub in ast.walk(pat):
            name = getattr(sub, "name", None)
            if isinstance(name, str):
                self.bind(name, "assign", getattr(sub, "lineno", lineno))
            rest = getattr(sub, "rest", None)
            if isinstance(rest, str):
                self.bind(rest, "assign", getattr(sub, "lineno", lineno))


# ---------------------------------------------------------------------------
# Tolerant parsing
# ---------------------------------------------------------------------------


def _render(lines, patch):
    out = []
    for i, line in enumerate(lines):
        kind = patch.get(i)
        if kind is None:
            out.append(line)
        elif kind == "append_pass":
            out.append(line.rstrip() + " pass")
        elif kind == "pass_same":
            indent = len(line) - len(line.lstrip())
            out.append(" " * indent + "pass")
        else:                                   # "blank"
            out.append("")
    return out


def tolerant_parse(text):
    """Parse `text`, repairing syntax errors while keeping line numbers stable.

    A block header with a missing body gets a ` pass` appended; any other
    offending line is replaced by an equally indented `pass` and then blanked.
    Everything that still parses is kept, so definitions on both sides of a
    broken line survive.
    """
    try:
        return ast.parse(text)
    except SyntaxError:
        pass
    except (ValueError, RecursionError, MemoryError):
        return ast.parse("")

    lines = text.split("\n")
    patch = {}
    for _ in range(MAX_REPAIRS):
        rendered = _render(lines, patch)
        try:
            return ast.parse("\n".join(rendered))
        except SyntaxError as exc:
            ln = (exc.lineno or 1) - 1
            if ln < 0 or ln >= len(lines):
                ln = len(lines) - 1
            if ln < 0:
                break
            if "expected an indented block" in str(exc.msg or "").lower():
                header = _find_header(rendered, patch, ln)
                if header is not None:
                    patch[header] = "append_pass"
                    continue
            if not _escalate(patch, ln):
                break
        except (ValueError, RecursionError, MemoryError):
            break
    return ast.parse("")


def _find_header(rendered, patch, ln):
    """Nearest unpatched block header at or just above line index `ln`."""
    seen = 0
    for i in range(ln, -1, -1):
        text = rendered[i]
        if not text.strip():
            continue
        if patch.get(i) is None and text.rstrip().endswith(":"):
            return i
        seen += 1
        if seen >= 3:
            break
    return None


def _escalate(patch, ln):
    """Advance the repair applied to line `ln`; False when nothing is left."""
    order = {None: "pass_same", "append_pass": "pass_same", "pass_same": "blank"}
    cur = patch.get(ln)
    if cur in order:
        patch[ln] = order[cur]
        return True
    for j in range(ln - 1, -1, -1):
        if patch.get(j) in order:
            patch[j] = order[patch.get(j)]
            return True
    return False


# ---------------------------------------------------------------------------
# Per-file analysis and the project (directory) around it
# ---------------------------------------------------------------------------


class Analysis:
    def __init__(self, project, path, text):
        self.project = project
        self.path = path
        self.text = text
        self.lines = text.split("\n")
        self.tree = tolerant_parse(text)
        builder = ScopeBuilder()
        builder.visit(self.tree)
        self.scope = builder.module


class Project:
    """Resolves module names to values, preferring local files (parsed, never run)."""

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self._modules = {}
        self._files = {}

    # -- local files ------------------------------------------------------
    def _local_path(self, dotted):
        if not dotted:
            return None
        parts = dotted.split(".")
        if any(not p.isidentifier() for p in parts):
            return None
        base = os.path.join(self.base_dir, *parts)
        if os.path.isfile(base + ".py"):
            return base + ".py"
        init = os.path.join(base, "__init__.py")
        if os.path.isfile(init):
            return init
        return None

    def analyse_file(self, path):
        key = os.path.abspath(path)
        if key in self._files:
            return self._files[key]
        self._files[key] = None          # guards import cycles
        try:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        analysis = Analysis(self, path, text)
        self._files[key] = analysis
        return analysis

    # -- module resolution -------------------------------------------------
    def resolve_module(self, dotted, level=0):
        key = (dotted, level)
        if key in self._modules:
            return self._modules[key]
        self._modules[key] = None
        value = self._resolve_module_uncached(dotted, level)
        self._modules[key] = value
        return value

    def _resolve_module_uncached(self, dotted, level):
        local = self._local_path(dotted)
        if local is not None:
            analysis = self.analyse_file(local)
            if analysis is not None:
                return StaticModule(analysis)
        if level:
            return None
        if not dotted:
            return None
        mod = self._import(dotted)
        if mod is not None:
            return ObjValue(mod)
        return None

    @staticmethod
    def _import(dotted):
        if not all(p.isidentifier() for p in dotted.split(".")):
            return None
        if dotted in sys.modules:
            return sys.modules[dotted]
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink):
                return importlib.import_module(dotted)
        except BaseException:
            return None


# ---------------------------------------------------------------------------
# Attribute access on values
# ---------------------------------------------------------------------------


_MISSING = object()


def _getattr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except BaseException:
        return default


def class_mro(value):
    """Same-file MRO for an AstClass, as a list of AstClass values."""
    out = []
    seen = set()

    def walk(cv, depth):
        if depth > MAX_DEPTH or id(cv.node) in seen:
            return
        seen.add(id(cv.node))
        out.append(cv)
        analysis = cv.analysis
        for base in cv.node.bases:
            bv = resolve_expr(base, analysis.scope, 10 ** 9, analysis)
            if isinstance(bv, AstClass):
                walk(bv, depth + 1)

    walk(value, 0)
    return out


def class_body_bindings(cv):
    """Name -> (binding, owner AstClass) across the same-file MRO."""
    found = {}
    for owner in class_mro(cv):
        scope = scope_for_node(owner.analysis.scope, owner.node)
        if scope is None:
            continue
        for b in scope.bindings:
            if b.name not in found:
                found[b.name] = (b, owner)
    return found


def scope_for_node(root, node):
    stack = [root]
    while stack:
        s = stack.pop()
        if s.node is node:
            return s
        stack.extend(s.children)
    return None


def init_attributes(cv):
    """`self.x = ...` assignments in __init__ across the same-file MRO."""
    found = {}
    for owner in class_mro(cv):
        init = None
        for stmt in owner.node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    stmt.name == "__init__":
                init = stmt
                break
        if init is None:
            continue
        args = _args_of(init)
        if not args:
            continue
        selfname = args[0].arg
        for sub in ast.walk(init):
            targets = []
            value = None
            if isinstance(sub, ast.Assign):
                targets = sub.targets
                value = sub.value
            elif isinstance(sub, ast.AnnAssign):
                targets = [sub.target]
                value = sub.value
            elif isinstance(sub, ast.AugAssign):
                targets = [sub.target]
            for t in targets:
                for name_node in _flatten_target(t):
                    if isinstance(name_node, ast.Attribute) and \
                            isinstance(name_node.value, ast.Name) and \
                            name_node.value.id == selfname:
                        if name_node.attr not in found:
                            found[name_node.attr] = (
                                value if len(targets) == 1 and
                                not isinstance(t, (ast.Tuple, ast.List)) else None,
                                owner,
                            )
    return found


def _flatten_target(t):
    if isinstance(t, (ast.Tuple, ast.List)):
        out = []
        for e in t.elts:
            out.extend(_flatten_target(e))
        return out
    if isinstance(t, ast.Starred):
        return _flatten_target(t.value)
    return [t]


def get_attribute(value, name, depth=0):
    if value is None or depth > MAX_DEPTH:
        return None
    if isinstance(value, ObjValue):
        got = _getattr(value.obj, name, _MISSING)
        return None if got is _MISSING else ObjValue(got)
    if isinstance(value, TypeInstance):
        got = _getattr(value.cls, name, _MISSING)
        return None if got is _MISSING else ObjValue(got)
    if isinstance(value, StaticModule):
        scope = value.analysis.scope
        b = _pick_binding(scope, name, 10 ** 9)
        if b is None:
            for _, mod, level in scope.star_imports:
                sub = value.analysis.project.resolve_module(mod, level)
                got = get_attribute(sub, name, depth + 1)
                if got is not None:
                    return got
            return None
        return value_of_binding(b, value.analysis, depth + 1)
    if isinstance(value, AstClass):
        entry = class_body_bindings(value).get(name)
        if entry is None:
            return None
        b, owner = entry
        return value_of_binding(b, owner.analysis, depth + 1)
    if isinstance(value, AstInstance):
        entry = init_attributes(value.cls).get(name)
        if entry is not None:
            value_node, owner = entry
            if value_node is None:
                return None
            return resolve_expr(value_node,
                                scope_for_node(owner.analysis.scope, owner.node)
                                or owner.analysis.scope,
                                10 ** 9, owner.analysis, depth + 1)
        return get_attribute(value.cls, name, depth + 1)
    if isinstance(value, AstFunction):
        got = _getattr(types.FunctionType, name, _MISSING)
        return None if got is _MISSING else ObjValue(got)
    return None


def list_attributes(value):
    """Return [(name, type, description)] for every attribute of `value`."""
    out = []
    if value is None:
        return out
    if isinstance(value, ObjValue):
        obj = value.obj
        public_only = isinstance(obj, types.ModuleType)
        for name in _safe_dir(obj):
            if public_only and name.startswith("_"):
                continue
            out.append(_describe_real(obj, name))
        return out
    if isinstance(value, TypeInstance):
        for name in _safe_dir(value.cls):
            out.append(_describe_real(value.cls, name))
        return out
    if isinstance(value, AstFunction):
        for name in _safe_dir(types.FunctionType):
            out.append(_describe_real(types.FunctionType, name))
        return out
    if isinstance(value, StaticModule):
        analysis = value.analysis
        seen = set()
        for b in analysis.scope.bindings:
            if b.name.startswith("_") or b.name in seen:
                continue
            seen.add(b.name)
            v = value_of_binding(b, analysis, 1)
            typ, desc = _describe_binding(b, v)
            out.append((b.name, typ, desc))
        for _, mod, level in analysis.scope.star_imports:
            sub = analysis.project.resolve_module(mod, level)
            for item in list_attributes(sub):
                if item[0] not in seen:
                    seen.add(item[0])
                    out.append(item)
        return out
    if isinstance(value, AstClass):
        for name, (b, owner) in class_body_bindings(value).items():
            v = value_of_binding(b, owner.analysis, 1)
            typ, desc = _describe_binding(b, v)
            out.append((name, typ, desc))
        return out
    if isinstance(value, AstInstance):
        out = list_attributes(value.cls)
        have = {n for n, _, _ in out}
        for name, (value_node, owner) in init_attributes(value.cls).items():
            if name in have:
                continue
            v = None
            if value_node is not None:
                scope = scope_for_node(owner.analysis.scope, owner.node) \
                    or owner.analysis.scope
                v = resolve_expr(value_node, scope, 10 ** 9, owner.analysis, 1)
            typ, desc = describe_value(name, v)
            out.append((name, typ, desc))
        return out
    return out


def _safe_dir(obj):
    try:
        return list(dir(obj))
    except BaseException:
        return []


def _describe_real(owner, name):
    got = _getattr(owner, name)
    typ, desc = describe_value(name, ObjValue(got))
    return (name, typ, desc)


# ---------------------------------------------------------------------------
# Static expression resolution
# ---------------------------------------------------------------------------


def value_of_binding(binding, analysis, depth=0):
    if depth > MAX_DEPTH:
        return None
    form = binding.form
    if form == "def":
        return AstFunction(analysis, binding.node)
    if form == "class":
        return AstClass(analysis, binding.node)
    if form == "import":
        module, attr, level = binding.imp
        if attr is None:
            return analysis.project.resolve_module(module, level)
        base = analysis.project.resolve_module(module, level)
        got = get_attribute(base, attr, depth + 1) if base is not None else None
        if got is not None:
            return got
        full = (module + "." + attr) if module else attr
        return analysis.project.resolve_module(full, level)
    if form == "param":
        if binding.annotation is not None:
            ann = resolve_expr(binding.annotation, binding.scope, 10 ** 9,
                               analysis, depth + 1)
            return _instantiate(ann)
        if binding.first_param and binding.scope.parent is not None and \
                binding.scope.parent.kind == "class":
            return AstInstance(AstClass(analysis, binding.scope.parent.node))
        return None
    # assignments and other binding forms
    if binding.value_node is not None:
        v = resolve_expr(binding.value_node, binding.scope, 10 ** 9, analysis,
                         depth + 1)
        if v is not None:
            return v
    if binding.annotation is not None:
        ann = resolve_expr(binding.annotation, binding.scope, 10 ** 9, analysis,
                           depth + 1)
        return _instantiate(ann)
    return None


def _instantiate(value):
    """Turn a class value into an instance value (used for annotations)."""
    if isinstance(value, AstClass):
        return AstInstance(value)
    if isinstance(value, ObjValue) and isinstance(value.obj, type):
        return TypeInstance(value.obj)
    return None


_LITERAL_TYPES = {
    ast.List: list,
    ast.ListComp: list,
    ast.Dict: dict,
    ast.DictComp: dict,
    ast.Set: set,
    ast.SetComp: set,
    ast.Tuple: tuple,
    ast.JoinedStr: str,
    ast.GeneratorExp: types.GeneratorType,
    ast.Lambda: types.FunctionType,
}


def resolve_expr(node, scope, line, analysis, depth=0):
    """Resolve an expression node to a Value, or None."""
    if node is None or depth > MAX_DEPTH:
        return None
    if isinstance(node, ast.Constant):
        return TypeInstance(type(node.value))
    for cls, pytype in _LITERAL_TYPES.items():
        if isinstance(node, cls):
            return TypeInstance(pytype)
    if isinstance(node, ast.Name):
        b = _lookup(scope, node.id, line)
        if b is None:
            obj = _getattr(builtins, node.id, _MISSING)
            if obj is not _MISSING:
                return ObjValue(obj)
            return _star_lookup(analysis, node.id, line, depth)
        return value_of_binding(b, analysis, depth + 1)
    if isinstance(node, ast.Attribute):
        base = resolve_expr(node.value, scope, line, analysis, depth + 1)
        return get_attribute(base, node.attr, depth + 1)
    if isinstance(node, ast.Call):
        func = resolve_expr(node.func, scope, line, analysis, depth + 1)
        made = _instantiate(func)
        if made is not None:
            return made
        return None
    if isinstance(node, ast.Await):
        return None
    if isinstance(node, ast.IfExp):
        return resolve_expr(node.body, scope, line, analysis, depth + 1)
    return None


def _star_lookup(analysis, name, line, depth):
    scope = analysis.scope
    for lineno, module, level in scope.star_imports:
        if lineno > line:
            continue
        mod = analysis.project.resolve_module(module, level)
        got = get_attribute(mod, name, depth + 1)
        if got is not None:
            return got
    return None


def _pick_binding(scope, name, line):
    """Best binding for `name` in `scope` at or before `line`."""
    candidates = [b for b in scope.bindings
                  if b.name == name and (b.form == "param" or b.lineno <= line)]
    if not candidates:
        return None
    last = candidates[-1]
    if last.form in ("def", "class", "import", "param") or \
            last.value_node is not None or last.annotation is not None:
        return last
    for b in reversed(candidates[:-1]):
        if b.form in ("def", "class", "import", "param") or \
                b.value_node is not None or b.annotation is not None:
            return b
    return last


def _lookup(scope, name, line):
    s = scope
    first = True
    while s is not None:
        if first or s.kind != "class":
            b = _pick_binding(s, name, line if (first or s.kind == "module")
                              else 10 ** 9)
            if b is not None:
                return b
        s = s.parent
        first = False
    return None


# ---------------------------------------------------------------------------
# Cursor analysis
# ---------------------------------------------------------------------------


def find_prefix(text_before):
    i = len(text_before)
    while i > 0 and text_before[i - 1] in IDENT_CHARS:
        i -= 1
    return text_before[i:], text_before[:i]


def _match_close(text, idx):
    """Index of the opener matching the closing bracket at `idx`, else None."""
    pairs = {")": "(", "]": "[", "}": "{"}
    closers = set(pairs)
    openers = set(pairs.values())
    depth = 0
    i = idx
    while i >= 0:
        ch = text[i]
        if ch in "\"'":
            j = _match_string(text, i)
            if j is None:
                return None
            i = j - 1
            continue
        if ch in closers:
            depth += 1
        elif ch in openers:
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return None


def _match_string(text, idx):
    """Index of the opening quote for the string ending at `idx`, else None."""
    quote = text[idx]
    i = idx - 1
    while i >= 0:
        if text[i] == quote and (i == 0 or text[i - 1] != "\\"):
            while i > 0 and text[i - 1] in "rbfuRBFU":
                i -= 1
            return i
        i -= 1
    return None


def scan_receiver(text):
    """Extract the receiver expression ending at the end of `text`."""
    end = len(text)
    i = end
    while True:
        if i == 0:
            break
        ch = text[i - 1]
        if ch in ")]}":
            j = _match_close(text, i - 1)
            if j is None:
                return None
            i = j
            continue
        if ch in "\"'":
            j = _match_string(text, i - 1)
            if j is None:
                return None
            i = j
            break
        if ch in IDENT_CHARS:
            while i > 0 and text[i - 1] in IDENT_CHARS:
                i -= 1
            if i > 0 and text[i - 1] == ".":
                i -= 1
                continue
            break
        break
    expr = text[i:end].strip()
    return expr or None


def analyse_cursor(line_text, col):
    """Return (prefix, is_attribute, receiver_text)."""
    before = line_text[:col]
    prefix, rest = find_prefix(before)
    if rest.endswith("."):
        return prefix, True, scan_receiver(rest[:-1])
    return prefix, False, None


# ---------------------------------------------------------------------------
# Name collection
# ---------------------------------------------------------------------------


def find_target_scope(module_scope, line, indent, lines):
    scope = module_scope
    while True:
        nxt = None
        for child in scope.children:
            if child.contains(line, indent, lines):
                nxt = child
                break
        if nxt is None:
            return scope
        scope = nxt


def _describe_binding(binding, value):
    if binding.form == "param":
        return "param", "param"
    if binding.form == "import":
        if value is None:
            return "statement", "module " + binding.name
        return describe_value(binding.name, value)
    return describe_value(binding.name, value)


def collect_names(analysis, scope, line):
    """Visible (name, type, description) triples, nearest scope first."""
    out = []
    seen = set()

    def add(name, typ, desc):
        if name in seen:
            return
        seen.add(name)
        out.append((name, typ, desc))

    chain = []
    s = scope
    while s is not None:
        chain.append(s)
        s = s.parent

    for i, sc in enumerate(chain):
        if i > 0 and sc.kind == "class":
            continue                      # class bodies are not enclosing scopes
        limit = line if (i == 0 or sc.kind == "module") else 10 ** 9
        names = []
        for b in sc.bindings:
            if b.name not in names:
                names.append(b.name)
        for name in names:
            b = _pick_binding(sc, name, limit)
            if b is None:
                continue
            value = value_of_binding(b, analysis)
            typ, desc = _describe_binding(b, value)
            add(name, typ, desc)
        for lineno, module, level in sc.star_imports:
            if lineno > limit:
                continue
            mod = analysis.project.resolve_module(module, level)
            for name, typ, desc in star_names(mod):
                add(name, typ, desc)

    for name in dir(builtins):
        obj = _getattr(builtins, name)
        typ, desc = describe_value(name, ObjValue(obj))
        add(name, typ, desc)
    return out


def star_names(mod):
    """Public names a `from mod import *` brings in."""
    if mod is None:
        return []
    if isinstance(mod, ObjValue):
        obj = mod.obj
        exported = getattr(obj, "__all__", None)
        if isinstance(exported, (list, tuple)):
            names = [n for n in exported if isinstance(n, str)]
        else:
            names = [n for n in _safe_dir(obj) if not n.startswith("_")]
        out = []
        for name in names:
            if _getattr(obj, name, _MISSING) is _MISSING:
                continue
            out.append(_describe_real(obj, name))
        return out
    if isinstance(mod, StaticModule):
        return list_attributes(mod)
    return []


# ---------------------------------------------------------------------------
# Matching, ordering, output
# ---------------------------------------------------------------------------


def matches(name, prefix, fuzzy):
    if not prefix:
        return True
    low = name.lower()
    pref = prefix.lower()
    if not fuzzy:
        return low.startswith(pref)
    it = iter(low)
    return all(ch in it for ch in pref)


def group_rank(name, typ):
    if typ == "keyword":
        return 3
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


def build_output(items, prefix, fuzzy):
    """items: iterable of (name, type, description)."""
    chosen = {}
    order = []
    for name, typ, desc in items:
        if name in chosen:
            continue
        if not matches(name, prefix, fuzzy):
            continue
        chosen[name] = (name, typ, desc)
        order.append(name)
    cut = len(prefix)
    rows = [chosen[n] for n in order]
    rows.sort(key=lambda r: (group_rank(r[0], r[1]), r[0].lower(), r[0]))
    return [
        {"name": n, "complete": n[cut:], "type": t, "description": d}
        for n, t, d in rows
    ]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def read_source(path):
    if not os.path.exists(path):
        raise CliError("no such file: %s" % path)
    if not os.path.isfile(path):
        raise CliError("not a regular file: %s" % path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise CliError("cannot read %s: %s" % (path, exc))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CliError("file is not valid UTF-8: %s" % path)


def complete(path, line, col, fuzzy):
    text = read_source(path)
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    if line < 1 or line > len(lines):
        raise CliError("line %d out of range (file has %d lines)"
                       % (line, len(lines)))
    line_text = lines[line - 1]
    if col < 0 or col > len(line_text):
        raise CliError("column %d out of range (line %d has %d characters)"
                       % (col, line, len(line_text)))

    prefix, is_attr, receiver = analyse_cursor(line_text, col)
    try:
        return _analyse(path, text, lines, line, col, prefix, is_attr, receiver,
                        fuzzy)
    except Exception:
        # Analysis must never turn an editable file into a hard error; fall back
        # to the scope-independent completions.
        if is_attr:
            return []
        items = [(kw, "keyword", kw) for kw in KEYWORDS]
        for name in dir(builtins):
            if name in KEYWORDS:
                continue
            typ, desc = describe_value(name, ObjValue(_getattr(builtins, name)))
            items.append((name, typ, desc))
        return build_output(items, prefix, fuzzy)


def _analyse(path, text, lines, line, col, prefix, is_attr, receiver, fuzzy):
    base_dir = os.path.dirname(os.path.abspath(path)) or "."
    project = Project(base_dir)
    analysis = Analysis(project, path, text)
    analysis.lines = lines

    line_text = lines[line - 1]
    before = line_text[:col]
    indent = col if not before.strip() else len(line_text) - len(line_text.lstrip())
    scope = find_target_scope(analysis.scope, line, indent, lines)

    if is_attr:
        if receiver is None:
            return []
        try:
            expr = ast.parse(receiver, mode="eval").body
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            return []
        value = resolve_expr(expr, scope, line, analysis)
        return build_output(list_attributes(value), prefix, fuzzy)

    items = collect_names(analysis, scope, line)
    kws = [(kw, "keyword", kw) for kw in KEYWORDS]
    kw_names = {kw for kw in KEYWORDS}
    items = [it for it in items if it[0] not in kw_names]
    return build_output(kws + items, prefix, fuzzy)


def parse_args(argv):
    args = [a for a in argv if a != "--fuzzy"]
    fuzzy = len(args) != len(argv)
    if not args:
        raise CliError("usage: sith.py complete <file> <line> <col> [--fuzzy]")
    if args[0] != "complete":
        raise CliError("unknown command: %s" % args[0])
    if len(args) != 4:
        raise CliError("usage: sith.py complete <file> <line> <col> [--fuzzy]")
    try:
        line = int(args[2])
        col = int(args[3])
    except ValueError:
        raise CliError("line and column must be integers")
    return args[1], line, col, fuzzy


def main(argv):
    try:
        path, line, col, fuzzy = parse_args(argv)
        completions = complete(path, line, col, fuzzy)
    except CliError as exc:
        sys.stderr.write("sith: %s\n" % exc)
        return 1
    sys.stdout.write(
        json.dumps({"completions": completions}, separators=(",", ":")) + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    sys.exit(main(sys.argv[1:]))
