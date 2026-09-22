#!/usr/bin/env python3
"""sith - a small static Python code-intelligence CLI.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]

Analyses a Python source file statically.  `complete` prints ranked completions
for the cursor position; `infer` prints what the name under the cursor evaluates
to; `goto` prints where it was defined.  Output is compact JSON on STDOUT.
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
import pkgutil
import re
import sys
import tokenize
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
    __slots__ = ("analysis", "package_dir")

    def __init__(self, analysis, package_dir=None):
        self.analysis = analysis
        self.package_dir = package_dir      # dir, when this is a `__init__.py`


class NamespacePackage(Value):
    """A project directory without `__init__.py`, used as a package."""

    __slots__ = ("project", "path", "dotted")

    def __init__(self, project, path, dotted):
        self.project = project
        self.path = path
        self.dotted = dotted


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
    if isinstance(value, (StaticModule, NamespacePackage)):
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
                 "imp", "scope", "first_param", "default")

    def __init__(self, name, form, lineno, scope, node=None, value_node=None,
                 annotation=None, imp=None, first_param=False, default=None):
        self.name = name
        self.form = form              # def|class|param|import|assign
        self.lineno = lineno
        self.scope = scope
        self.node = node
        self.value_node = value_node
        self.annotation = annotation
        self.imp = imp                # (module, attr, level) for imports
        self.first_param = first_param
        self.default = default          # default expression of a parameter


class Scope:
    __slots__ = ("kind", "node", "parent", "children", "bindings",
                 "star_imports", "lineno", "end_lineno", "indent", "_ext",
                 "_flow")

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
        self._flow = None

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


def _defaults_of(node):
    """id(arg) -> default expression, for the parameters that have one."""
    a = node.args
    positional = list(getattr(a, "posonlyargs", [])) + list(a.args)
    out = {}
    offset = len(positional) - len(a.defaults)
    for i, arg in enumerate(positional):
        if i >= offset:
            out[id(arg)] = a.defaults[i - offset]
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        if default is not None:
            out[id(arg)] = default
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
        defaults = _defaults_of(node)
        for i, arg in enumerate(_args_of(node)):
            self.bind(arg.arg, "param", node.lineno, node=arg,
                      annotation=arg.annotation, first_param=(i == 0),
                      default=defaults.get(id(arg)))
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
        defaults = _defaults_of(node)
        for i, arg in enumerate(_args_of(node)):
            self.bind(arg.arg, "param", node.lineno, node=arg,
                      first_param=(i == 0), default=defaults.get(id(arg)))
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
                self.bind(alias.asname, "import", node.lineno, node=node,
                          imp=(alias.name, None, 0))
            else:
                root = alias.name.split(".")[0]
                self.bind(root, "import", node.lineno, node=node,
                          imp=(root, None, 0))

    def visit_ImportFrom(self, node):
        module = node.module or ""
        level = node.level or 0
        for alias in node.names:
            if alias.name == "*":
                self.cur.star_imports.append((node.lineno, module, level))
                continue
            bound = alias.asname or alias.name
            self.bind(bound, "import", node.lineno, node=node,
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
        self.scope.node = self.tree
        self._package = _MISSING_PKG
        self._all = _MISSING_PKG

    @property
    def package(self):
        """Dotted parts of the package this file lives in, or None."""
        if self._package is _MISSING_PKG:
            self._package = self.project.package_of(self.path)
        return self._package

    def resolve_import(self, module, level=0):
        """Resolve an import written in *this* file to a module value."""
        return self.project.resolve_module(module, level, self.package)


_MISSING_PKG = object()


def _dir_entries(dirpath):
    """Importable module / package names directly inside `dirpath`."""
    out = []
    try:
        entries = sorted(os.listdir(dirpath))
    except OSError:
        return out
    for name in entries:
        full = os.path.join(dirpath, name)
        if os.path.isdir(full):
            if name.isidentifier() and name != "__pycache__":
                out.append(name)
        elif name.endswith(".py") and name != "__init__.py":
            base = name[:-3]
            if base.isidentifier():
                out.append(base)
    seen = set()
    unique = []
    for name in out:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


class Project:
    """Resolves module names to values, preferring project files (never run).

    The project root is the `--project` directory, or the directory holding the
    analysed file.  Search order is: project root, then the standard library.
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.base_dir = self.root
        self._modules = {}
        self._files = {}

    # -- paths -------------------------------------------------------------
    def _relative(self, path):
        """POSIX-ish path parts of `path` below the root, or None."""
        try:
            rel = os.path.relpath(os.path.abspath(path), self.root)
        except ValueError:
            return None
        if rel == os.pardir or rel.startswith(os.pardir + os.sep) or \
                os.path.isabs(rel):
            return None
        return [p for p in rel.replace(os.sep, "/").split("/")
                if p and p != "."]

    def parts_of(self, path):
        """Dotted parts naming the module stored at `path`, or None."""
        parts = self._relative(path)
        if parts is None:
            return None
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        elif parts[-1].endswith(".py"):
            parts = parts[:-1] + [parts[-1][:-3]]
        return parts

    def package_of(self, path):
        """Dotted parts of the package containing `path`, or None if outside."""
        parts = self._relative(path)
        if parts is None:
            return None
        return parts[:-1]

    # -- local files ------------------------------------------------------
    def _candidate(self, parts):
        """(kind, path) for the dotted `parts` below the root, else None."""
        if not parts or any(not p.isidentifier() for p in parts):
            return None
        head = os.path.join(self.root, *parts[:-1]) if len(parts) > 1 \
            else self.root
        last = parts[-1]
        init = os.path.join(head, last, "__init__.py")
        if os.path.isfile(init):
            return ("package", init)
        module = os.path.join(head, last + ".py")
        if os.path.isfile(module):
            return ("module", module)
        directory = os.path.join(head, last)
        if os.path.isdir(directory):
            return ("namespace", directory)
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
    def module_for_parts(self, parts):
        """The project module named by absolute dotted `parts`, or None."""
        key = tuple(parts)
        if key in self._modules:
            return self._modules[key]
        self._modules[key] = None
        value = None
        if not parts:
            value = NamespacePackage(self, self.root, "")
        else:
            found = self._candidate(list(parts))
            if found is not None:
                kind, path = found
                if kind == "namespace":
                    value = NamespacePackage(self, path, ".".join(parts))
                else:
                    analysis = self.analyse_file(path)
                    if analysis is not None:
                        value = StaticModule(
                            analysis,
                            os.path.dirname(path) if kind == "package" else None)
        self._modules[key] = value
        return value

    def resolve_module(self, dotted, level=0, package=None):
        """Resolve an import to a module value.

        `level` is the number of leading dots; `package` is the dotted package
        of the importing file (needed only for relative imports).
        """
        parts = [p for p in (dotted or "").split(".") if p]
        if level:
            if package is None:
                return None
            climb = level - 1
            if climb > len(package):
                return None            # above the project root: unresolvable
            base = list(package[:len(package) - climb]) if climb else list(package)
            return self.module_for_parts(base + parts)
        if not parts:
            return None
        local = self.module_for_parts(parts)
        if local is not None:
            return local
        return self.stdlib_module(parts)

    def stdlib_module(self, parts):
        key = ("<stdlib>",) + tuple(parts)
        if key in self._modules:
            return self._modules[key]
        self._modules[key] = None
        value = None
        names = getattr(sys, "stdlib_module_names", None)
        if names is None or parts[0] in names:
            mod = self._import(".".join(parts))
            if mod is not None:
                value = ObjValue(mod)
        self._modules[key] = value
        return value

    def top_level_names(self):
        """Every name `import <name>` could name, project first then stdlib."""
        out = list(_dir_entries(self.root))
        seen = set(out)
        for name in sorted(getattr(sys, "stdlib_module_names", ()) or ()):
            if name not in seen and name.isidentifier():
                seen.add(name)
                out.append(name)
        return out

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


# ---------------------------------------------------------------------------
# Module exports: submodules, `__all__`, star-import visibility
# ---------------------------------------------------------------------------


def package_dir_of(value):
    """Directory backing a package value, or None for a plain module."""
    if isinstance(value, NamespacePackage):
        return value.path
    if isinstance(value, StaticModule):
        return value.package_dir
    return None


def submodule_names(value):
    """Importable submodule names of a package value."""
    directory = package_dir_of(value)
    if directory is not None:
        return _dir_entries(directory)
    if isinstance(value, ObjValue):
        paths = _getattr(value.obj, "__path__", None)
        if paths is None:
            return []
        out = []
        try:
            for info in pkgutil.iter_modules(list(paths)):
                if info.name.isidentifier():
                    out.append(info.name)
        except BaseException:
            return []
        return out
    return []


def package_submodule(value, name):
    """`value.name` when `value` is a package and `name` one of its modules."""
    if not name.isidentifier():
        return None
    project = None
    parts = None
    if isinstance(value, NamespacePackage):
        project = value.project
        parts = [p for p in value.dotted.split(".") if p]
    elif isinstance(value, StaticModule) and value.package_dir is not None:
        project = value.analysis.project
        parts = project.parts_of(value.analysis.path)
    if project is None or parts is None:
        return None
    return project.module_for_parts(parts + [name])


def _string_list(node):
    """The literal list/tuple/set of strings `node` is, else None."""
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    out = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
        else:
            return None
    return out


def static_all(analysis):
    """The module's `__all__` as a list of names, or None when it has none."""
    if analysis._all is not _MISSING_PKG:
        return analysis._all
    names = None
    for node in analysis.tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__"
                   for t in targets):
            continue
        listed = _string_list(value)
        if listed is None:
            continue
        if isinstance(node, ast.AugAssign) and names is not None:
            names = names + [n for n in listed if n not in names]
        else:
            names = listed
    analysis._all = names
    return names


def module_all(value):
    """`__all__` of any module value, or None."""
    if isinstance(value, StaticModule):
        return static_all(value.analysis)
    if isinstance(value, ObjValue):
        listed = _getattr(value.obj, "__all__", None)
        if isinstance(listed, (list, tuple)):
            return [n for n in listed if isinstance(n, str)]
    return None


def star_visible(value, name):
    """Would `from <value> import *` make `name` visible?"""
    if value is None:
        return False
    listed = module_all(value)
    if listed is not None:
        return name in listed
    return not name.startswith("_")


def export_items(value, depth=0):
    """(name, type, description) for every name `from <value> import ...` offers."""
    if value is None or depth > MAX_DEPTH:
        return []
    listed = module_all(value)
    allowed = None if listed is None else set(listed)

    def wanted(name):
        if allowed is not None:
            return name in allowed
        return not name.startswith("_")

    out = []
    seen = set()

    def add(item):
        if item[0] in seen or not wanted(item[0]):
            return
        seen.add(item[0])
        out.append(item)

    if isinstance(value, ObjValue):
        obj = value.obj
        for name in (listed if listed is not None else _safe_dir(obj)):
            if _getattr(obj, name, _MISSING) is _MISSING:
                continue
            add(_describe_real(obj, name))
        for name in submodule_names(value):
            add((name, "module", "module " + name))
        return out
    if isinstance(value, StaticModule):
        analysis = value.analysis
        for b in analysis.scope.bindings:
            if b.name in seen or not wanted(b.name):
                continue
            resolved = value_of_binding(b, analysis, 1)
            typ, desc = _describe_binding(b, resolved)
            add((b.name, typ, desc))
        for _, mod, level in analysis.scope.star_imports:
            sub = analysis.resolve_import(mod, level)
            for item in export_items(sub, depth + 1):
                add(item)
        for name in submodule_names(value):
            add((name, "module", "module " + name))
        return out
    if isinstance(value, NamespacePackage):
        for name in submodule_names(value):
            add((name, "module", "module " + name))
        return out
    return out


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
    """`self.x = ...` assignments in `__init__` across the same-file MRO.

    Maps an attribute name onto the list of places it is assigned:
    `(value_node, owner_class, init_node, attr_node)`.
    """
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
                simple = len(targets) == 1 and not isinstance(t, (ast.Tuple, ast.List))
                for name_node in _flatten_target(t):
                    if isinstance(name_node, ast.Attribute) and \
                            isinstance(name_node.value, ast.Name) and \
                            name_node.value.id == selfname:
                        found.setdefault(name_node.attr, []).append(
                            (value if simple else None, owner, init, name_node)
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
                sub = value.analysis.resolve_import(mod, level)
                if not star_visible(sub, name):
                    continue
                got = get_attribute(sub, name, depth + 1)
                if got is not None:
                    return got
            return package_submodule(value, name)
        return value_of_binding(b, value.analysis, depth + 1)
    if isinstance(value, NamespacePackage):
        return package_submodule(value, name)
    if isinstance(value, AstClass):
        entry = class_body_bindings(value).get(name)
        if entry is None:
            return None
        b, owner = entry
        return value_of_binding(b, owner.analysis, depth + 1)
    if isinstance(value, AstInstance):
        for got in attribute_values(value, name, depth + 1):
            return got
        return None
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
            sub = analysis.resolve_import(mod, level)
            for item in star_names(sub):
                if item[0] in seen:
                    continue
                seen.add(item[0])
                out.append(item)
        for name in submodule_names(value):
            if name not in seen:
                seen.add(name)
                out.append((name, "module", "module " + name))
        return out
    if isinstance(value, NamespacePackage):
        return [(n, "module", "module " + n) for n in submodule_names(value)]
    if isinstance(value, AstClass):
        for name, (b, owner) in class_body_bindings(value).items():
            v = value_of_binding(b, owner.analysis, 1)
            typ, desc = _describe_binding(b, v)
            out.append((name, typ, desc))
        return out
    if isinstance(value, AstInstance):
        out = list_attributes(value.cls)
        have = {n for n, _, _ in out}
        for name in init_attributes(value.cls):
            if name in have:
                continue
            vals = attribute_values(value, name, 1)
            v = vals[0] if vals else None
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
            return analysis.resolve_import(module, level)
        base = analysis.resolve_import(module, level)
        got = get_attribute(base, attr, depth + 1) if base is not None else None
        if got is not None:
            return got
        full = (module + "." + attr) if module else attr
        return analysis.resolve_import(full, level)
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
        mod = analysis.resolve_import(module, level)
        if not star_visible(mod, name):
            continue
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


# ---------------------------------------------------------------------------
# Import-statement completion context
# ---------------------------------------------------------------------------


_IMPORT_RE = re.compile(r"\s*import\s+(?P<rest>.*)$")
_FROM_RE = re.compile(r"\s*from\s+(?P<rest>.*)$")
_FROM_IMPORT_RE = re.compile(r"(?P<mod>[.\w]*?)\s+import\s+(?P<tail>.*)$")
_ALIAS_RE = re.compile(r"(?:^|[\s(,])as\b\s*\w*$")


def _split_level(text):
    """('pkg.mod', 2) for '..pkg.mod'."""
    level = 0
    while level < len(text) and text[level] == ".":
        level += 1
    return text[level:], level


def _last_segment(text):
    """The item being typed in a comma-separated import list."""
    seg = text.split(",")[-1]
    seg = seg.lstrip().lstrip("(").lstrip()
    return seg


def _bracket_depth(text):
    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth


def logical_before(lines, line, col):
    """Text left of the cursor, joined with the physical lines it continues."""
    acc = lines[line - 1][:col]
    idx = line - 2
    while idx >= 0 and line - idx < MAX_REPAIRS:
        previous = lines[idx].rstrip()
        continued = previous.endswith("\\")
        if continued:
            previous = previous[:-1]
        candidate = previous + " " + acc.lstrip()
        if not continued and _bracket_depth(candidate) <= 0:
            break
        acc = candidate
        idx -= 1
    return acc


def import_context(before):
    """('modules', head, level) / ('names', module, level) for the cursor.

    `before` is the text left of the cursor on its logical line.  Returns None
    when the cursor is not inside an import statement, and ('none', ...) when it
    is but nothing can be suggested there (an alias name, a `*`).
    """
    blank = ("none", "", 0)
    match = _IMPORT_RE.fullmatch(before)
    if match:
        seg = _last_segment(match.group("rest"))
        if _ALIAS_RE.search(seg) or not re.fullmatch(r"[\w.]*", seg):
            return blank
        head, _, _tail = seg.rpartition(".")
        return ("modules", head, 0)
    match = _FROM_RE.fullmatch(before)
    if not match:
        return None
    rest = match.group("rest")
    inner = _FROM_IMPORT_RE.fullmatch(rest)
    if inner:
        module, level = _split_level(inner.group("mod"))
        seg = _last_segment(inner.group("tail"))
        if _ALIAS_RE.search(seg) or not re.fullmatch(r"\w*", seg):
            return blank
        return ("names", module, level)
    if not re.fullmatch(r"[.\w]*", rest):
        return blank
    module, level = _split_level(rest)
    head, _, _tail = module.rpartition(".")
    return ("modules", head, level)


def import_items(analysis, context):
    """(name, type, description) triples for an import-statement cursor."""
    kind, module, level = context
    if kind == "none":
        return []
    if kind == "names":
        return export_items(analysis.resolve_import(module, level))
    if not module and not level:
        names = analysis.project.top_level_names()
    else:
        names = submodule_names(analysis.resolve_import(module, level))
    return [(name, "module", "module " + name) for name in names]


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
            mod = analysis.resolve_import(module, level)
            for name, typ, desc in star_names(mod):
                add(name, typ, desc)

    for name in dir(builtins):
        obj = _getattr(builtins, name)
        typ, desc = describe_value(name, ObjValue(obj))
        add(name, typ, desc)
    return out


def star_names(mod):
    """Public names a `from mod import *` brings in.

    `__all__` when the module defines one, otherwise every name that does not
    start with an underscore.
    """
    return export_items(mod)


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
# Flow paths
#
# Every binding carries the chain of conditional branches it sits in.  A later
# binding only shadows an earlier one when it runs unconditionally relative to
# it, so `if c: x = 1` / `else: x = 2` keeps both alive.
# ---------------------------------------------------------------------------


def flow_map(scope):
    """line number -> branch path, for the statements belonging to `scope`."""
    if scope._flow is not None:
        return scope._flow
    out = {}
    body = getattr(scope.node, "body", None)
    if isinstance(body, list):
        _flow_body(body, (), out)
    scope._flow = out
    return out


def _mark(out, first, last, path):
    if not first:
        return
    for ln in range(first, (last or first) + 1):
        out[ln] = path


def _flow_body(body, path, out):
    for stmt in body:
        _flow_stmt(stmt, path, out)


def _flow_stmt(stmt, path, out):
    if isinstance(stmt, ast.If):
        _mark(out, stmt.lineno, stmt.lineno, path)
        _flow_body(stmt.body, path + ((id(stmt), 0),), out)
        _flow_body(stmt.orelse, path + ((id(stmt), 1),), out)
        return
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        inner = path + ((id(stmt), 0),)
        _mark(out, stmt.lineno, stmt.lineno, inner)
        _flow_body(stmt.body, inner, out)
        _flow_body(stmt.orelse, path + ((id(stmt), 1),), out)
        return
    if isinstance(stmt, ast.Try) or stmt.__class__.__name__ == "TryStar":
        _flow_body(stmt.body, path + ((id(stmt), 0),), out)
        for i, handler in enumerate(stmt.handlers):
            branch = path + ((id(stmt), i + 1),)
            _mark(out, handler.lineno, handler.lineno, branch)
            _flow_body(handler.body, branch, out)
        _flow_body(stmt.orelse, path + ((id(stmt), 0),), out)
        _flow_body(stmt.finalbody, path, out)
        return
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        _mark(out, stmt.lineno, stmt.lineno, path)
        _flow_body(stmt.body, path, out)
        return
    if isinstance(stmt, ast.Match):
        _mark(out, stmt.lineno, stmt.lineno, path)
        for i, case in enumerate(stmt.cases):
            branch = path + ((id(stmt), i),)
            _mark(out, case.pattern.lineno, case.body[0].lineno - 1, branch)
            _flow_body(case.body, branch, out)
        return
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        _mark(out, stmt.lineno, stmt.lineno, path)
        return
    _mark(out, getattr(stmt, "lineno", 0), getattr(stmt, "end_lineno", 0), path)


def _is_prefix(short, long_):
    return len(short) <= len(long_) and tuple(long_[:len(short)]) == tuple(short)


def live_bindings(scope, name, line):
    """Bindings of `name` in `scope` that are still reachable at `line`."""
    cands = [b for b in scope.bindings
             if b.name == name and (b.form == "param" or b.lineno <= line)]
    if not cands:
        return []
    fmap = flow_map(scope)
    live = []
    for b in cands:
        path = () if b.form == "param" else fmap.get(b.lineno, ())
        live = [(p, x) for p, x in live if not _is_prefix(path, p)]
        live.append((path, b))
    return [b for _, b in live]


def lookup_all(scope, name, line):
    """(scope, bindings) for `name`, nearest enclosing scope that binds it."""
    s = scope
    first = True
    while s is not None:
        if first or s.kind != "class":
            limit = line if (first or s.kind == "module") else 10 ** 9
            found = live_bindings(s, name, limit)
            if found:
                return s, found
        s = s.parent
        first = False
    return None, []


# ---------------------------------------------------------------------------
# Multi-valued (union) resolution
# ---------------------------------------------------------------------------

NONE_TYPE = type(None)


def none_value():
    return TypeInstance(NONE_TYPE)


def is_none_value(value):
    return isinstance(value, TypeInstance) and value.cls is NONE_TYPE


def value_key(value):
    if isinstance(value, ObjValue):
        return ("obj", id(value.obj))
    if isinstance(value, TypeInstance):
        return ("type", value.cls)
    if isinstance(value, StaticModule):
        return ("module", id(value.analysis))
    if isinstance(value, AstClass):
        return ("class", id(value.node))
    if isinstance(value, AstFunction):
        return ("func", id(value.node))
    if isinstance(value, AstInstance):
        return ("instance", id(value.cls.node))
    return ("none", 0)


def dedupe_values(values):
    out = []
    seen = set()
    for v in values:
        if v is None:
            continue
        key = value_key(v)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def values_of_binding(binding, analysis, depth=0):
    """Every value `binding` may hold."""
    if depth > MAX_DEPTH:
        return []
    form = binding.form
    if form == "def":
        return [AstFunction(analysis, binding.node)]
    if form == "class":
        return [AstClass(analysis, binding.node)]
    if form == "import":
        got = value_of_binding(binding, analysis, depth)
        return [got] if got is not None else []
    if form == "param":
        if binding.annotation is not None:
            return _annotation_values(binding.annotation, binding.scope,
                                      analysis, depth)
        if binding.first_param and binding.scope.parent is not None and \
                binding.scope.parent.kind == "class":
            return [AstInstance(AstClass(analysis, binding.scope.parent.node))]
        if binding.default is not None:
            return resolve_values(binding.default, binding.scope, 10 ** 9,
                                  analysis, depth + 1)
        return []
    if binding.value_node is not None:
        vals = resolve_values(binding.value_node, binding.scope, 10 ** 9,
                              analysis, depth + 1)
        if vals:
            return vals
    if binding.annotation is not None:
        return _annotation_values(binding.annotation, binding.scope, analysis,
                                  depth)
    return []


def _annotation_values(node, scope, analysis, depth):
    out = []
    for ann in resolve_values(node, scope, 10 ** 9, analysis, depth + 1):
        made = _instantiate(ann)
        if made is not None:
            out.append(made)
    return dedupe_values(out)


_BIN_SAFE = (int, float, complex, str, bytes, list, tuple, set, dict)


def resolve_values(node, scope, line, analysis, depth=0, narrow=None):
    """Resolve an expression to every value it may take."""
    if node is None or depth > MAX_DEPTH:
        return []
    if isinstance(node, ast.Constant):
        return [TypeInstance(type(node.value))]
    for cls, pytype in _LITERAL_TYPES.items():
        if isinstance(node, cls):
            return [TypeInstance(pytype)]
    if isinstance(node, ast.Name):
        info = narrow.get(node.id) if narrow else None
        if info is not None and info.get("set") is not None:
            vals = list(info["set"])
        else:
            vals = _name_values(node.id, scope, line, analysis, depth)
        if info is not None:
            vals = [v for v in vals if not _narrow_excluded(v, info)]
        return vals
    if isinstance(node, ast.Attribute):
        out = []
        for base in resolve_values(node.value, scope, line, analysis,
                                   depth + 1, narrow):
            out.extend(attribute_values(base, node.attr, depth + 1))
        return dedupe_values(out)
    if isinstance(node, ast.Call):
        out = []
        for func in resolve_values(node.func, scope, line, analysis,
                                   depth + 1, narrow):
            out.extend(call_values(func, depth + 1))
        return dedupe_values(out)
    if isinstance(node, ast.IfExp):
        return dedupe_values(
            resolve_values(node.body, scope, line, analysis, depth + 1, narrow)
            + resolve_values(node.orelse, scope, line, analysis, depth + 1,
                             narrow))
    if isinstance(node, ast.BoolOp):
        out = []
        for part in node.values:
            out.extend(resolve_values(part, scope, line, analysis, depth + 1,
                                      narrow))
        return dedupe_values(out)
    if isinstance(node, ast.Compare):
        return [TypeInstance(bool)]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return [TypeInstance(bool)]
    if isinstance(node, ast.BinOp):
        left = resolve_values(node.left, scope, line, analysis, depth + 1, narrow)
        right = resolve_values(node.right, scope, line, analysis, depth + 1,
                               narrow)
        return _binop_values(left, right)
    if isinstance(node, ast.NamedExpr):
        return resolve_values(node.value, scope, line, analysis, depth + 1,
                              narrow)
    return []


def _binop_values(left, right):
    """Best-effort result type of a binary operation."""
    sides = [left, right]
    types = []
    for side in sides:
        if len(side) == 1 and isinstance(side[0], TypeInstance) and \
                side[0].cls in _BIN_SAFE:
            types.append(side[0].cls)
        elif side:
            return []
        else:
            types.append(None)
    first, second = types
    if first is None and second is None:
        return []
    if first is None or second is None:
        return [TypeInstance(first or second)]
    if first is second:
        return [TypeInstance(first)]
    if {first, second} == {int, float}:
        return [TypeInstance(float)]
    return []


def _name_values(name, scope, line, analysis, depth):
    owner, bindings = lookup_all(scope, name, line)
    if bindings:
        out = []
        for b in bindings:
            out.extend(values_of_binding(b, analysis, depth + 1))
        if out:
            return dedupe_values(out)
        # Nothing resolvable among the live bindings (`x += 1`, a `for` target
        # ...): fall back to the most recent binding that does resolve.
        others = [b for b in owner.bindings
                  if b.name == name and (b.form == "param" or b.lineno <= line)]
        for b in reversed(others):
            got = values_of_binding(b, analysis, depth + 1)
            if got:
                return dedupe_values(got)
        return []
    obj = _getattr(builtins, name, _MISSING)
    if obj is not _MISSING:
        return [ObjValue(obj)]
    got = _star_lookup(analysis, name, line, depth)
    return [got] if got is not None else []


def attribute_values(value, name, depth=0):
    """Every value `value.name` may take."""
    if value is None or depth > MAX_DEPTH:
        return []
    if isinstance(value, (ObjValue, TypeInstance, AstFunction,
                          NamespacePackage)):
        got = get_attribute(value, name, depth)
        return [got] if got is not None else []
    if isinstance(value, StaticModule):
        analysis = value.analysis
        out = []
        for b in live_bindings(analysis.scope, name, 10 ** 9):
            out.extend(values_of_binding(b, analysis, depth + 1))
        if not out:
            for _, module, level in analysis.scope.star_imports:
                sub = analysis.resolve_import(module, level)
                if not star_visible(sub, name):
                    continue
                out.extend(attribute_values(sub, name, depth + 1))
        if not out:
            got = package_submodule(value, name)
            if got is not None:
                out.append(got)
        return dedupe_values(out)
    if isinstance(value, AstClass):
        entry = class_body_bindings(value).get(name)
        if entry is None:
            return []
        binding, owner = entry
        return values_of_binding(binding, owner.analysis, depth + 1)
    if isinstance(value, AstInstance):
        out = []
        for value_node, owner, init, _attr in \
                init_attributes(value.cls).get(name, []):
            if value_node is None:
                continue
            scope = scope_for_node(owner.analysis.scope, init) \
                or owner.analysis.scope
            out.extend(resolve_values(value_node, scope, 10 ** 9,
                                      owner.analysis, depth + 1))
        out = dedupe_values(out)
        if out:
            return out
        return attribute_values(value.cls, name, depth + 1)
    return []


def call_values(func, depth=0):
    """Values produced by calling `func`."""
    if depth > MAX_DEPTH:
        return []
    if isinstance(func, AstClass):
        return [AstInstance(func)]
    if isinstance(func, ObjValue) and isinstance(func.obj, type):
        return [TypeInstance(func.obj)]
    if isinstance(func, AstFunction):
        return function_returns(func, depth)
    return []


def _return_nodes(node):
    """`return` statements belonging to `node`, skipping nested definitions."""
    out = []

    def walk(body):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            if isinstance(stmt, ast.Return):
                out.append(stmt)
            for field, value in ast.iter_fields(stmt):
                if isinstance(value, list) and value and \
                        isinstance(value[0], ast.stmt):
                    walk(value)
                elif isinstance(value, ast.excepthandler):
                    walk([value])
            for handler in getattr(stmt, "handlers", []):
                walk(handler.body)

    walk(node.body)
    return out


def function_returns(func, depth=0):
    """The return type(s) of an AST function."""
    if depth > MAX_DEPTH:
        return []
    node = func.node
    analysis = func.analysis
    scope = scope_for_node(analysis.scope, node) or analysis.scope
    returns = _return_nodes(node)
    if returns:
        out = []
        for stmt in returns:
            if stmt.value is None:
                out.append(none_value())
            else:
                out.extend(resolve_values(stmt.value, scope, 10 ** 9, analysis,
                                          depth + 1))
        return dedupe_values(out)
    annotated = getattr(node, "returns", None)
    if annotated is not None:
        got = _annotation_values(annotated, scope, analysis, depth)
        if got:
            return got
    return [none_value()]


# ---------------------------------------------------------------------------
# Flow-sensitive narrowing
# ---------------------------------------------------------------------------


def _covers(body, line):
    return bool(body) and body[0].lineno <= line <= (body[-1].end_lineno or
                                                     body[-1].lineno)


def narrowing_at(analysis, scope, line):
    """name -> narrowing info, for the `if` branches enclosing `line`."""
    conditions = []
    for node in ast.walk(analysis.tree):
        if not isinstance(node, (ast.If, ast.While)):
            continue
        if _covers(node.body, line):
            conditions.append((node.lineno, node.test, True))
        elif isinstance(node, ast.If) and _covers(node.orelse, line):
            conditions.append((node.lineno, node.test, False))
    conditions.sort(key=lambda item: item[0])
    out = {}
    for _, test, positive in conditions:
        _apply_condition(test, positive, out, scope, line, analysis)
    return out


def _slot(out, name):
    return out.setdefault(name, {"set": None, "exclude": [], "none": False})


def _apply_condition(test, positive, out, scope, line, analysis):
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        _apply_condition(test.operand, not positive, out, scope, line, analysis)
        return
    if isinstance(test, ast.BoolOp):
        both = (isinstance(test.op, ast.And) and positive) or \
               (isinstance(test.op, ast.Or) and not positive)
        if both:
            for part in test.values:
                _apply_condition(part, positive, out, scope, line, analysis)
        return
    if isinstance(test, ast.NamedExpr):
        _apply_condition(test.value, positive, out, scope, line, analysis)
        return
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and \
            test.func.id == "isinstance" and len(test.args) == 2 and \
            isinstance(test.args[0], ast.Name):
        name = test.args[0].id
        classes = _class_values(test.args[1], scope, line, analysis)
        if not classes:
            return
        slot = _slot(out, name)
        if positive:
            made = [v for v in (_instantiate(c) for c in classes) if v is not None]
            if made:
                slot["set"] = made
                slot["exclude"] = []
                slot["none"] = False
        else:
            slot["exclude"] = slot["exclude"] + classes
        return
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and \
            isinstance(test.left, ast.Name) and \
            isinstance(test.comparators[0], ast.Constant) and \
            test.comparators[0].value is None:
        op = test.ops[0]
        if isinstance(op, ast.Is):
            wants_none = positive
        elif isinstance(op, ast.IsNot):
            wants_none = not positive
        else:
            return
        slot = _slot(out, test.left.id)
        if wants_none:
            slot["set"] = [none_value()]
            slot["exclude"] = []
            slot["none"] = False
        else:
            slot["none"] = True
            if slot["set"] is not None:
                slot["set"] = [v for v in slot["set"] if not is_none_value(v)]
        return


def _class_values(node, scope, line, analysis):
    if isinstance(node, (ast.Tuple, ast.List)):
        out = []
        for elt in node.elts:
            out.extend(_class_values(elt, scope, line, analysis))
        return out
    out = []
    for value in resolve_values(node, scope, line, analysis):
        if isinstance(value, AstClass) or \
                (isinstance(value, ObjValue) and isinstance(value.obj, type)):
            out.append(value)
    return out


def _narrow_excluded(value, info):
    if info.get("none") and is_none_value(value):
        return True
    for cls in info.get("exclude", []):
        if isinstance(cls, AstClass) and isinstance(value, AstInstance) and \
                value.cls.node is cls.node:
            return True
        if isinstance(cls, ObjValue) and isinstance(value, TypeInstance) and \
                value.cls is cls.obj:
            return True
    return False


# ---------------------------------------------------------------------------
# Definition objects
# ---------------------------------------------------------------------------


def _rel_path(path, root):
    absolute = os.path.abspath(path)
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        return absolute
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return absolute.replace(os.sep, "/")
    return rel.replace(os.sep, "/")


def module_dotted(path, root):
    rel = _rel_path(path, root)
    if os.path.isabs(rel):
        return os.path.splitext(os.path.basename(rel))[0]
    parts = rel.split("/")
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(p for p in parts if p)


def make_def(name, typ, full_name, module_path, line, column, description,
             docstring):
    return {
        "name": name,
        "type": typ,
        "full_name": full_name,
        "module_path": module_path,
        "line": line,
        "column": column,
        "description": description,
        "docstring": docstring or "",
    }


def _scope_parts(scope):
    parts = []
    s = scope
    while s is not None and s.kind != "module":
        parts.append(getattr(s.node, "name", None) or "<lambda>")
        s = s.parent
    parts.reverse()
    return parts


def qualified(analysis, scope, name, root):
    parts = [module_dotted(analysis.path, root)] + _scope_parts(scope) + [name]
    return ".".join(p for p in parts if p)


def _ident_column(analysis, lineno, name, from_col=0):
    """Column of the identifier `name` on line `lineno`."""
    if lineno < 1 or lineno > len(analysis.lines):
        return max(from_col, 0)
    text = analysis.lines[lineno - 1]
    match = re.compile(r"\b" + re.escape(name) + r"\b").search(text,
                                                              max(from_col, 0))
    return match.start() if match else max(from_col, 0)


def _params_text(node):
    try:
        return ast.unparse(node.args)
    except Exception:
        return ", ".join(a.arg for a in _args_of(node))


def _expr_text(node):
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _line_text(analysis, lineno):
    if 1 <= lineno <= len(analysis.lines):
        return analysis.lines[lineno - 1].strip()
    return ""


def def_for_function(analysis, node, root):
    own = scope_for_node(analysis.scope, node)
    parent = own.parent if own is not None else analysis.scope
    return make_def(
        node.name, "function",
        qualified(analysis, parent, node.name, root),
        _rel_path(analysis.path, root), node.lineno,
        _ident_column(analysis, node.lineno, node.name, node.col_offset),
        "def %s(%s)" % (node.name, _params_text(node)),
        ast.get_docstring(node) or "")


def def_for_class(analysis, node, root, instance=False):
    own = scope_for_node(analysis.scope, node)
    parent = own.parent if own is not None else analysis.scope
    return make_def(
        node.name, "instance" if instance else "class",
        qualified(analysis, parent, node.name, root),
        _rel_path(analysis.path, root), node.lineno,
        _ident_column(analysis, node.lineno, node.name, node.col_offset),
        ("instance of " + node.name) if instance else ("class " + node.name),
        ast.get_docstring(node) or "")


def def_for_static_module(analysis, root):
    name = module_dotted(analysis.path, root)
    short = name.split(".")[-1] if name else ""
    return make_def(short, "module", name, _rel_path(analysis.path, root), 0, 0,
                    "module " + short, ast.get_docstring(analysis.tree) or "")


def def_for_namespace_package(value, root):
    short = value.dotted.split(".")[-1] if value.dotted else \
        os.path.basename(value.path.rstrip(os.sep))
    return make_def(short, "module", value.dotted or short,
                    _rel_path(value.path, root), 0, 0, "module " + short, "")


def _real_doc(obj):
    try:
        doc = inspect.getdoc(obj)
    except BaseException:
        doc = None
    return doc or ""


def _real_location(obj, root):
    """(module_path, line, column) of a live object's source, best effort."""
    try:
        source = inspect.getsourcefile(obj)
    except BaseException:
        source = None
    if not source or not os.path.isfile(source):
        return ("", 0, 0)
    path = _rel_path(source, root)
    if isinstance(obj, types.ModuleType):
        return (path, 0, 0)
    try:
        lines, start = inspect.getsourcelines(obj)
    except BaseException:
        return (path, 0, 0)
    name = _getattr(obj, "__name__", "") or ""
    pattern = re.compile(r"\b(?:def|class)\s+(" + re.escape(name) + r")\b")
    for offset, text in enumerate(lines[:10]):
        match = pattern.search(text)
        if match:
            return (path, (start or 1) + offset, match.start(1))
    return (path, start or 0, 0)


def _real_full_name(obj, fallback):
    name = _getattr(obj, "__qualname__", None) or \
        _getattr(obj, "__name__", None) or fallback
    module = _getattr(obj, "__module__", None) or ""
    if module and module != "__main__":
        return module + "." + name
    return name


def def_for_type_instance(cls, root):
    name = "None" if cls is NONE_TYPE else _getattr(cls, "__name__", "object")
    module = _getattr(cls, "__module__", "") or ""
    if cls is NONE_TYPE or module == "builtins":
        return make_def(name, "instance", "builtins." + name, "", 0, 0,
                        "instance of " + name, "")
    path, line, column = _real_location(cls, root)
    return make_def(name, "instance", _real_full_name(cls, name), path, line,
                    column, "instance of " + name, _real_doc(cls))


def def_for_obj(obj, root, name_hint=""):
    kind = kind_of_obj(obj)
    if kind == "module":
        full = _getattr(obj, "__name__", name_hint) or name_hint
        short = full.split(".")[-1]
        path, _, _ = _real_location(obj, root)
        return make_def(short, "module", full, path, 0, 0, "module " + short,
                        _real_doc(obj))
    if kind == "class":
        name = _getattr(obj, "__name__", name_hint) or name_hint
        path, line, column = _real_location(obj, root)
        return make_def(name, "class", _real_full_name(obj, name), path, line,
                        column, "class " + name, _real_doc(obj))
    if kind == "function":
        name = _getattr(obj, "__name__", name_hint) or name_hint
        path, line, column = _real_location(obj, root)
        try:
            params = str(inspect.signature(obj)).strip("()")
        except BaseException:
            params = "..."
        return make_def(name, "function", _real_full_name(obj, name), path,
                        line, column, "def %s(%s)" % (name, params),
                        _real_doc(obj))
    return def_for_type_instance(type(obj), root)


def def_for_value(value, root, name_hint=""):
    """The definition object describing a resolved value."""
    if value is None:
        return None
    if isinstance(value, AstFunction):
        return def_for_function(value.analysis, value.node, root)
    if isinstance(value, AstClass):
        return def_for_class(value.analysis, value.node, root)
    if isinstance(value, AstInstance):
        return def_for_class(value.cls.analysis, value.cls.node, root,
                             instance=True)
    if isinstance(value, StaticModule):
        return def_for_static_module(value.analysis, root)
    if isinstance(value, NamespacePackage):
        return def_for_namespace_package(value, root)
    if isinstance(value, TypeInstance):
        return def_for_type_instance(value.cls, root)
    if isinstance(value, ObjValue):
        return def_for_obj(value.obj, root, name_hint)
    return None


def defs_for_values(values, root, name_hint=""):
    out = []
    for value in values:
        got = def_for_value(value, root, name_hint)
        if got is not None:
            out.append(got)
    return out


def _value_kind(value):
    typ, _ = describe_value("", value)
    return typ


def def_from_binding(binding, analysis, root):
    """Where a name is bound - what `goto` reports."""
    form = binding.form
    if form == "def":
        return def_for_function(analysis, binding.node, root)
    if form == "class":
        return def_for_class(analysis, binding.node, root)
    path = _rel_path(analysis.path, root)
    full = qualified(analysis, binding.scope, binding.name, root)
    if form == "param":
        node = binding.node
        line = getattr(node, "lineno", binding.lineno)
        column = getattr(node, "col_offset", None)
        if column is None:
            column = _ident_column(analysis, line, binding.name)
        return make_def(binding.name, "param", full, path, line, column,
                        "param " + binding.name, "")
    if form == "import":
        node = binding.node
        line = getattr(node, "lineno", binding.lineno)
        column = _ident_column(analysis, line, binding.name,
                               getattr(node, "col_offset", 0))
        values = values_of_binding(binding, analysis)
        typ = _value_kind(values[0]) if values else "statement"
        text = _expr_text(node) if node is not None else ""
        return make_def(binding.name, typ, full, path, line, column,
                        text or _line_text(analysis, line), "")
    node = binding.node
    line = getattr(node, "lineno", binding.lineno)
    column = getattr(node, "col_offset", None)
    if column is None:
        column = _ident_column(analysis, line, binding.name)
    if binding.value_node is not None:
        description = _expr_text(binding.value_node)
    else:
        description = _line_text(analysis, line)
    return make_def(binding.name, "statement", full, path, line, column,
                    description, "")


def def_for_self_attribute(record, root):
    value_node, owner, _init, attr_node = record
    analysis = owner.analysis
    line = attr_node.lineno
    column = max(attr_node.end_col_offset - len(attr_node.attr), 0)
    own = scope_for_node(analysis.scope, owner.node)
    parts = [module_dotted(analysis.path, root)]
    parts += _scope_parts(own.parent) if own is not None else []
    parts += [owner.node.name, attr_node.attr]
    description = _expr_text(value_node) if value_node is not None \
        else _line_text(analysis, line)
    return make_def(attr_node.attr, "statement", ".".join(p for p in parts if p),
                    _rel_path(analysis.path, root), line, column, description,
                    "")


def _import_key(binding, analysis):
    return (os.path.abspath(analysis.path), binding.name, binding.lineno)


def follow_import(binding, analysis, root, depth=0, seen=None):
    """Definitions the import chain starting at `binding` finally reaches.

    Empty when the chain dead-ends (stdlib, third-party, missing module or
    missing name); the caller then falls back to the import site itself.
    """
    if binding.form != "import" or depth > MAX_DEPTH:
        return []
    key = _import_key(binding, analysis)
    seen = set(seen or ())
    if key in seen:                       # circular import: stop, do not loop
        return []
    seen.add(key)
    module, attr, level = binding.imp
    target = analysis.resolve_import(module, level)
    if attr is None:
        if isinstance(target, (StaticModule, NamespacePackage)):
            made = def_for_value(target, root, binding.name)
            return [made] if made is not None else []
        return []
    return follow_module_name(target, attr, root, depth + 1, seen)


def follow_module_name(target, name, root, depth=0, seen=None):
    """Where `name` is really defined inside module value `target`."""
    if target is None or depth > MAX_DEPTH:
        return []
    if isinstance(target, StaticModule):
        analysis = target.analysis
        out = []
        for b in live_bindings(analysis.scope, name, 10 ** 9):
            if b.form == "import":
                out.extend(follow_import(b, analysis, root, depth + 1, seen))
            else:
                out.append(def_from_binding(b, analysis, root))
        if out:
            return out
        for _, module, level in analysis.scope.star_imports:
            sub = analysis.resolve_import(module, level)
            if not star_visible(sub, name):
                continue
            got = follow_module_name(sub, name, root, depth + 1, seen)
            if got:
                return got
    got = package_submodule(target, name)
    if got is not None:
        made = def_for_value(got, root, name)
        return [made] if made is not None else []
    return []


def attribute_definitions(value, name, root, depth=0, follow=False):
    """Where `value.name` is defined - what `goto` reports for attributes."""
    if value is None or depth > MAX_DEPTH:
        return []
    if isinstance(value, StaticModule):
        analysis = value.analysis
        out = []
        for b in live_bindings(analysis.scope, name, 10 ** 9):
            chased = follow_import(b, analysis, root) if follow else []
            out.extend(chased or [def_from_binding(b, analysis, root)])
        if out:
            return out
        for _, module, level in analysis.scope.star_imports:
            sub = analysis.resolve_import(module, level)
            if not star_visible(sub, name):
                continue
            out.extend(attribute_definitions(sub, name, root, depth + 1,
                                             follow))
        if out:
            return out
        got = package_submodule(value, name)
        if got is not None:
            made = def_for_value(got, root, name)
            return [made] if made is not None else []
        return out
    if isinstance(value, AstClass):
        entry = class_body_bindings(value).get(name)
        if entry is None:
            return []
        binding, owner = entry
        return [def_from_binding(binding, owner.analysis, root)]
    if isinstance(value, AstInstance):
        records = init_attributes(value.cls).get(name, [])
        if records:
            return [def_for_self_attribute(r, root) for r in records]
        return attribute_definitions(value.cls, name, root, depth + 1, follow)
    got = get_attribute(value, name)
    if got is None:
        return []
    made = def_for_value(got, root, name)
    return [made] if made is not None else []


def finish_definitions(definitions):
    """De-duplicate and sort by (module_path, line, column) ascending."""
    out = []
    seen = set()
    for item in definitions:
        if item is None:
            continue
        key = (item["module_path"], item["line"], item["column"], item["name"],
               item["type"], item["full_name"], item["description"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    out.sort(key=lambda d: (d["module_path"], d["line"], d["column"]))
    return out


# ---------------------------------------------------------------------------
# Locating the name under the cursor
# ---------------------------------------------------------------------------


def token_at(line_text, col):
    """(token, start, end) for the identifier run covering `col`, else None."""
    start = col
    while start > 0 and line_text[start - 1] in IDENT_CHARS:
        start -= 1
    end = col
    while end < len(line_text) and line_text[end] in IDENT_CHARS:
        end += 1
    if start == end:
        return None
    return line_text[start:end], start, end


def literal_spans(text):
    """Source ranges covered by string literals and comments."""
    spans = []
    kinds = {tokenize.STRING, tokenize.COMMENT}
    for extra in ("FSTRING_MIDDLE", "FSTRING_START", "FSTRING_END"):
        if hasattr(tokenize, extra):
            kinds.add(getattr(tokenize, extra))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in kinds:
                spans.append((tok.start, tok.end))
    except BaseException:
        pass
    return spans


def inside_literal(spans, line, col):
    for start, end in spans:
        if start <= (line, col) < end:
            return True
    return False


def _def_name_column(lines, node):
    if node.lineno < 1 or node.lineno > len(lines):
        return None
    text = lines[node.lineno - 1]
    match = re.compile(r"\b" + re.escape(node.name) + r"\b").search(
        text, node.col_offset)
    return match.start() if match else None


def cursor_node(tree, lines, line, col, token):
    """(kind, node) for the identifier at (line, col), else (None, None)."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id == token and node.lineno == line and \
                    node.col_offset == col:
                hits.append(("name", node))
        elif isinstance(node, ast.Attribute):
            start = (node.end_col_offset or 0) - len(node.attr)
            if node.attr == token and node.end_lineno == line and start == col:
                hits.append(("attribute", node))
        elif isinstance(node, ast.arg):
            if node.arg == token and node.lineno == line and \
                    node.col_offset == col:
                hits.append(("arg", node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == token and node.lineno == line and \
                    _def_name_column(lines, node) == col:
                hits.append(("def", node))
        elif isinstance(node, ast.ClassDef):
            if node.name == token and node.lineno == line and \
                    _def_name_column(lines, node) == col:
                hits.append(("classdef", node))
        elif isinstance(node, ast.Constant):
            if node.value is None or node.value is True or node.value is False:
                if repr(node.value) == token and node.lineno == line and \
                        node.col_offset == col:
                    hits.append(("constant", node))
    if not hits:
        return None, None
    order = {"attribute": 0, "arg": 1, "def": 2, "classdef": 2, "constant": 3,
             "name": 4}
    hits.sort(key=lambda item: order.get(item[0], 9))
    return hits[0]


def binding_for_node(analysis, node):
    stack = [analysis.scope]
    while stack:
        scope = stack.pop()
        for b in scope.bindings:
            if b.node is node:
                return b
        stack.extend(scope.children)
    return None


def import_target(analysis, line, col, token):
    """Module value when the cursor sits on the module part of an import."""
    for node in ast.walk(analysis.tree):
        if isinstance(node, ast.ImportFrom):
            if node.lineno != line or not node.module:
                continue
            text = analysis.lines[line - 1]
            start = text.find(node.module)
            if start < 0 or not (start <= col < start + len(node.module)):
                continue
            dotted = node.module[:node.module.find(token, col - start)
                                 + len(token)]
            return analysis.resolve_import(dotted, node.level or 0)
        if isinstance(node, ast.Import):
            if node.lineno != line:
                continue
            text = analysis.lines[line - 1]
            for alias in node.names:
                if alias.asname:
                    continue
                start = text.find(alias.name)
                if start < 0 or not (start <= col < start + len(alias.name)):
                    continue
                dotted = alias.name[:alias.name.find(token, col - start)
                                    + len(token)]
                return analysis.resolve_import(dotted, 0)
    return None


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


def project_root(path, project):
    """The project root: `--project <dir>`, else the file's own directory."""
    if project is None:
        return os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(project):
        raise CliError("no such project directory: %s" % project)
    return os.path.abspath(project)


def make_analysis(path, text, lines, root):
    """Analyse `path` and register it with its project, so cycles reuse it."""
    project = Project(root)
    analysis = Analysis(project, path, text)
    analysis.lines = lines
    project._files[os.path.abspath(path)] = analysis
    return analysis


def complete(path, line, col, fuzzy, project=None):
    text = read_source(path)
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    if line < 1 or line > len(lines):
        raise CliError("line %d out of range (file has %d lines)"
                       % (line, len(lines)))
    line_text = lines[line - 1]
    if col < 0 or col > len(line_text):
        raise CliError("column %d out of range (line %d has %d characters)"
                       % (col, line, len(line_text)))

    root = project_root(path, project)
    prefix, is_attr, receiver = analyse_cursor(line_text, col)
    context = import_context(logical_before(lines, line, col))
    try:
        return _analyse(path, text, lines, line, col, prefix, is_attr, receiver,
                        fuzzy, root, context)
    except Exception:
        # Analysis must never turn an editable file into a hard error; fall back
        # to the scope-independent completions.
        if is_attr or context is not None:
            return []
        items = [(kw, "keyword", kw) for kw in KEYWORDS]
        for name in dir(builtins):
            if name in KEYWORDS:
                continue
            typ, desc = describe_value(name, ObjValue(_getattr(builtins, name)))
            items.append((name, typ, desc))
        return build_output(items, prefix, fuzzy)


def _analyse(path, text, lines, line, col, prefix, is_attr, receiver, fuzzy,
             root, context):
    analysis = make_analysis(path, text, lines, root)

    if context is not None:
        return build_output(import_items(analysis, context), prefix, fuzzy)

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
        narrow = narrowing_at(analysis, scope, line)
        items = []
        for value in resolve_values(expr, scope, line, analysis, 0, narrow):
            items.extend(list_attributes(value))
        return build_output(items, prefix, fuzzy)

    items = collect_names(analysis, scope, line)
    kws = [(kw, "keyword", kw) for kw in KEYWORDS]
    kw_names = {kw for kw in KEYWORDS}
    items = [it for it in items if it[0] not in kw_names]
    return build_output(kws + items, prefix, fuzzy)


def definitions_at(path, line, col, mode, follow=False, project=None):
    """`infer` / `goto` entry point; returns the sorted definition objects."""
    text = read_source(path)
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    if line < 1 or line > len(lines):
        raise CliError("line %d out of range (file has %d lines)"
                       % (line, len(lines)))
    line_text = lines[line - 1]
    if col < 0 or col > len(line_text):
        raise CliError("column %d out of range (line %d has %d characters)"
                       % (col, line, len(line_text)))

    found = token_at(line_text, col)
    if found is None:
        raise CliError("no name at line %d column %d" % (line, col))
    token, start, _end = found
    if not (token[0].isalpha() or token[0] == "_"):
        raise CliError("not a name at line %d column %d: %s"
                       % (line, col, token))
    if keyword.iskeyword(token) and token not in ("None", "True", "False"):
        raise CliError("%s is a keyword, not a name" % token)
    if inside_literal(literal_spans(text), line, start):
        raise CliError("no name at line %d column %d (string or comment)"
                       % (line, col))

    root = project_root(path, project)
    analysis = make_analysis(path, text, lines, root)
    try:
        items = cursor_definitions(analysis, root, line, start, token, mode,
                                   follow)
    except Exception:
        items = []
    return finish_definitions(items)


def cursor_definitions(analysis, root, line, col, token, mode, follow=False):
    lines = analysis.lines
    line_text = lines[line - 1]
    before = line_text[:col]
    indent = col if not before.strip() else \
        len(line_text) - len(line_text.lstrip())
    scope = find_target_scope(analysis.scope, line, indent, lines)
    narrow = narrowing_at(analysis, scope, line)
    kind, node = cursor_node(analysis.tree, lines, line, col, token)

    if kind == "attribute":
        bases = resolve_values(node.value, scope, line, analysis, 0, narrow)
        if mode == "goto":
            out = []
            for base in bases:
                out.extend(attribute_definitions(base, token, root, 0, follow))
            return out
        values = []
        for base in bases:
            values.extend(attribute_values(base, token))
        return defs_for_values(dedupe_values(values), root, token)

    if kind == "def":
        return [def_for_function(analysis, node, root)]
    if kind == "classdef":
        return [def_for_class(analysis, node, root)]
    if kind == "constant":
        return defs_for_values([TypeInstance(type(node.value))], root, token)

    if kind in ("arg", "name"):
        binding = binding_for_node(analysis, node)
        if binding is not None:
            if mode == "goto":
                chased = follow_import(binding, analysis, root) if follow else []
                return chased or [def_from_binding(binding, analysis, root)]
            return defs_for_values(values_of_binding(binding, analysis), root,
                                   token)

    if mode == "goto":
        _owner, bindings = lookup_all(scope, token, line)
        if bindings:
            out = []
            for b in bindings:
                chased = follow_import(b, analysis, root) if follow else []
                out.extend(chased or [def_from_binding(b, analysis, root)])
            return out
    else:
        name_node = ast.Name(id=token, ctx=ast.Load())
        name_node.lineno = name_node.end_lineno = line
        name_node.col_offset = col
        name_node.end_col_offset = col + len(token)
        values = resolve_values(name_node, scope, line, analysis, 0, narrow)
        if values:
            return defs_for_values(values, root, token)

    module_value = import_target(analysis, line, col, token)
    if module_value is not None:
        return defs_for_values([module_value], root, token)

    if mode == "goto":
        obj = _getattr(builtins, token, _MISSING)
        if obj is not _MISSING:
            return [def_for_obj(obj, root, token)]
        got = _star_lookup(analysis, token, line, 0)
        if got is not None:
            return defs_for_values([got], root, token)
    return []


USAGE = ("usage: sith.py complete <file> <line> <col> [--fuzzy] "
         "[--project <dir>]\n"
         "       sith.py infer <file> <line> <col> [--project <dir>]\n"
         "       sith.py goto <file> <line> <col> [--follow-imports] "
         "[--project <dir>]")


def parse_args(argv):
    args = []
    fuzzy = follow = False
    project = None
    i = 0
    while i < len(argv):
        item = argv[i]
        if item == "--fuzzy":
            fuzzy = True
        elif item == "--follow-imports":
            follow = True
        elif item == "--project":
            i += 1
            if i >= len(argv):
                raise CliError("--project requires a directory")
            project = argv[i]
        elif item.startswith("--project="):
            project = item.split("=", 1)[1]
            if not project:
                raise CliError("--project requires a directory")
        elif item.startswith("--"):
            raise CliError("unknown option: %s" % item)
        else:
            args.append(item)
        i += 1
    if not args:
        raise CliError(USAGE)
    command = args[0]
    if command not in ("complete", "infer", "goto"):
        raise CliError("unknown command: %s" % command)
    if len(args) != 4:
        raise CliError(USAGE)
    try:
        line = int(args[2])
        col = int(args[3])
    except ValueError:
        raise CliError("line and column must be integers")
    return command, args[1], line, col, fuzzy, follow, project


def main(argv):
    try:
        command, path, line, col, fuzzy, follow, project = parse_args(argv)
        if command == "complete":
            payload = {"completions": complete(path, line, col, fuzzy, project)}
        else:
            payload = {"definitions": definitions_at(path, line, col, command,
                                                     follow, project)}
    except CliError as exc:
        sys.stderr.write("sith: %s\n" % exc)
        return 1
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    sys.exit(main(sys.argv[1:]))
