#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence engine.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]

Prints a compact JSON object with a "completions" array to STDOUT.
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
import re
import sys
import types

MAX_DEPTH = 12
OPEN_FOR = {")": "(", "]": "[", "}": "{"}
STRING_PREFIX_CHARS = set("rbfuRBFU")


def is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


# ---------------------------------------------------------------------------
# Values -- the result of statically evaluating an expression
# ---------------------------------------------------------------------------


class Value:
    """Base class for statically inferred values."""


class UnknownValue(Value):
    def __repr__(self):  # pragma: no cover - debugging helper
        return "Unknown"


UNKNOWN = UnknownValue()


class RuntimeValue(Value):
    """A real Python object obtained by importing something."""

    __slots__ = ("obj",)

    def __init__(self, obj):
        self.obj = obj


class RuntimeInstanceValue(Value):
    """An instance of a real Python class (the object itself is unknown)."""

    __slots__ = ("cls",)

    def __init__(self, cls):
        self.cls = cls


class ClassValue(Value):
    """A class defined in the analysed file."""

    __slots__ = ("scope",)

    def __init__(self, scope):
        self.scope = scope


class InstanceValue(Value):
    """An instance of a class defined in the analysed file."""

    __slots__ = ("scope",)

    def __init__(self, scope):
        self.scope = scope


class FunctionValue(Value):
    """A function defined in the analysed file."""

    __slots__ = ("node",)

    def __init__(self, node):
        self.node = node


class StaticModuleValue(Value):
    """A local module that could not be imported but could be parsed."""

    __slots__ = ("analyzer", "name")

    def __init__(self, analyzer, name):
        self.analyzer = analyzer
        self.name = name


# ---------------------------------------------------------------------------
# Runtime object inspection helpers
# ---------------------------------------------------------------------------

_ROUTINE_TYPES = tuple(
    t
    for t in (
        getattr(types, "WrapperDescriptorType", None),
        getattr(types, "MethodWrapperType", None),
        getattr(types, "MethodDescriptorType", None),
        getattr(types, "ClassMethodDescriptorType", None),
        getattr(types, "BuiltinFunctionType", None),
        getattr(types, "FunctionType", None),
    )
    if t is not None
)


def obj_kind(obj) -> str:
    """Classify a real Python object into a completion type."""
    try:
        if inspect.ismodule(obj):
            return "module"
        if inspect.isclass(obj):
            return "class"
        if inspect.isroutine(obj) or isinstance(obj, _ROUTINE_TYPES):
            return "function"
    except Exception:
        return "instance"
    return "instance"


def type_name(obj) -> str:
    try:
        return type(obj).__name__
    except Exception:
        return "object"


def describe(ctype: str, name: str, tname: str = "object") -> str:
    if ctype == "function":
        return "def %s(...)" % name
    if ctype == "class":
        return "class %s" % name
    if ctype == "module":
        return "module %s" % name
    if ctype == "instance":
        return "instance of %s" % tname
    if ctype == "param":
        return "param"
    if ctype == "keyword":
        return name
    return "statement"


def runtime_entry(name: str, obj) -> tuple:
    kind = obj_kind(obj)
    return (name, kind, describe(kind, name, type_name(obj)))


def value_type_and_desc(value: Value, name: str) -> tuple:
    """Map an inferred value onto (completion type, description)."""
    if isinstance(value, RuntimeValue):
        obj = value.obj
        kind = obj_kind(obj)
        return kind, describe(kind, name, type_name(obj))
    if isinstance(value, RuntimeInstanceValue):
        cls_name = getattr(value.cls, "__name__", "object")
        return "instance", describe("instance", name, cls_name)
    if isinstance(value, ClassValue):
        return "class", describe("class", name)
    if isinstance(value, InstanceValue):
        return "instance", describe("instance", name, value.scope.node.name)
    if isinstance(value, FunctionValue):
        return "function", describe("function", name)
    if isinstance(value, StaticModuleValue):
        return "module", describe("module", name)
    return "statement", "statement"


# ---------------------------------------------------------------------------
# Import machinery (safe-ish: never lets imported code write to our stdout)
# ---------------------------------------------------------------------------


class Importer:
    def __init__(self, directory: str):
        self.directory = directory
        self._cache = {}
        self._static_cache = {}
        if directory and directory not in sys.path:
            sys.path.insert(0, directory)

    def import_module(self, name: str):
        if not name:
            return None
        if name in self._cache:
            return self._cache[name]
        mod = None
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                mod = importlib.import_module(name)
        except BaseException:
            mod = None
        if mod is not None and "." not in name:
            # A module of the same name sitting next to the analysed file wins
            # over one that was already imported by this process.
            local = self.local_file(name)
            if local is not None:
                origin = getattr(mod, "__file__", None)
                if origin is None or os.path.abspath(origin) != os.path.abspath(local):
                    mod = None
        self._cache[name] = mod
        return mod

    def local_file(self, name: str):
        """Path of a local single-file module living next to the target file."""
        if not self.directory or "." in name:
            return None
        candidate = os.path.join(self.directory, name + ".py")
        if os.path.isfile(candidate):
            return candidate
        pkg = os.path.join(self.directory, name, "__init__.py")
        if os.path.isfile(pkg):
            return pkg
        return None

    def static_module(self, name: str):
        """Parse a local module without executing it."""
        if name in self._static_cache:
            return self._static_cache[name]
        path = self.local_file(name)
        result = None
        if path:
            try:
                with open(path, "rb") as fh:
                    text = fh.read().decode("utf-8")
                lines = normalize(text).split("\n")
                tree = tolerant_parse(lines, 0)
                result = Analyzer(tree, path, lines, self)
            except Exception:
                result = None
        self._static_cache[name] = result
        return result


def module_public_entries(mod) -> list:
    """Public attributes of a real module."""
    entries = []
    seen = set()
    names = []
    try:
        exported = getattr(mod, "__all__", None)
    except Exception:
        exported = None
    if isinstance(exported, (list, tuple)):
        for n in exported:
            if isinstance(n, str):
                names.append(n)
    try:
        names.extend(dir(mod))
    except Exception:
        pass
    for name in names:
        if not isinstance(name, str) or name.startswith("_") or name in seen:
            continue
        seen.add(name)
        try:
            obj = getattr(mod, name)
        except Exception:
            entries.append((name, "statement", "statement"))
            continue
        entries.append(runtime_entry(name, obj))
    return entries


def runtime_all_entries(owner) -> list:
    """Every attribute of a real (non-module) object."""
    entries = []
    try:
        names = dir(owner)
    except Exception:
        return entries
    for name in names:
        if not isinstance(name, str):
            continue
        try:
            obj = getattr(owner, name)
        except Exception:
            entries.append((name, "statement", "statement"))
            continue
        entries.append(runtime_entry(name, obj))
    return entries


# ---------------------------------------------------------------------------
# Scopes and bindings
# ---------------------------------------------------------------------------


class Binding:
    __slots__ = (
        "name",
        "lineno",
        "btype",
        "node",
        "value_node",
        "annotation",
        "imp",
        "scope",
        "target_scope",
        "special",
        "_value",
        "_resolving",
    )

    def __init__(
        self,
        name,
        lineno,
        btype,
        node=None,
        value_node=None,
        annotation=None,
        imp=None,
        scope=None,
        target_scope=None,
        special=None,
    ):
        self.name = name
        self.lineno = lineno
        self.btype = btype
        self.node = node
        self.value_node = value_node
        self.annotation = annotation
        self.imp = imp
        self.scope = scope
        self.target_scope = target_scope
        self.special = special
        self._value = None
        self._resolving = False

    @property
    def is_param(self):
        return self.btype == "param"

    def get_value(self, analyzer, depth=0):
        if self._value is not None:
            return self._value
        if self._resolving or depth > MAX_DEPTH:
            return UNKNOWN
        self._resolving = True
        try:
            value = self._compute(analyzer, depth)
        except Exception:
            value = UNKNOWN
        finally:
            self._resolving = False
        self._value = value
        return value

    def _compute(self, analyzer, depth):
        if self.btype == "function":
            return FunctionValue(self.node)
        if self.btype == "class":
            return ClassValue(self.target_scope)
        if self.btype == "import":
            return analyzer.resolve_import(self.imp)
        if self.btype == "param":
            if self.special == "self" and self.target_scope is not None:
                return InstanceValue(self.target_scope)
            if self.special == "cls" and self.target_scope is not None:
                return ClassValue(self.target_scope)
            if self.annotation is not None:
                return analyzer.value_from_annotation(self.annotation, self.scope, depth + 1)
            return UNKNOWN
        if self.value_node is not None:
            return analyzer.resolve(self.value_node, self.scope, self.lineno, depth + 1)
        if self.annotation is not None:
            return analyzer.value_from_annotation(self.annotation, self.scope, depth + 1)
        return UNKNOWN

    def completion(self, analyzer):
        """Return (type, description) for this binding."""
        if self.btype == "function":
            return "function", describe("function", self.name)
        if self.btype == "class":
            return "class", describe("class", self.name)
        if self.btype == "param":
            return "param", describe("param", self.name)
        if self.btype == "import" and self.imp is not None and self.imp[0] == "module":
            return "module", describe("module", self.name)
        value = self.get_value(analyzer)
        return value_type_and_desc(value, self.name)


class Scope:
    def __init__(self, kind, node, parent):
        self.kind = kind  # module | function | class | lambda | comp
        self.node = node
        self.parent = parent
        self.children = []
        self.bindings = []
        if parent is not None:
            parent.children.append(self)

    def add(self, binding):
        binding.scope = self
        self.bindings.append(binding)

    @property
    def lineno(self):
        if self.kind == "module":
            return 0
        return getattr(self.node, "lineno", 0) or 0

    @property
    def end_lineno(self):
        if self.kind == "module":
            end = 0
            for stmt in getattr(self.node, "body", []):
                end = max(end, getattr(stmt, "end_lineno", None) or getattr(stmt, "lineno", 0) or 0)
            return end
        return getattr(self.node, "end_lineno", None) or self.lineno

    @property
    def body_indent(self):
        if self.kind == "module":
            return 0
        body = getattr(self.node, "body", None)
        if isinstance(body, list) and body:
            return getattr(body[0], "col_offset", 0) or 0
        return (getattr(self.node, "col_offset", 0) or 0) + 4

    def contains(self, line, col=None):
        if self.kind == "module":
            return True
        if col is None:
            return self.lineno <= line <= self.end_lineno
        start_col = getattr(self.node, "col_offset", 0) or 0
        end_col = getattr(self.node, "end_col_offset", None)
        if end_col is None:
            return self.lineno <= line <= self.end_lineno
        return (self.lineno, start_col) <= (line, col) <= (self.end_lineno, end_col)


# ---------------------------------------------------------------------------
# Tolerant parsing
# ---------------------------------------------------------------------------


def leading_ws(text: str) -> str:
    out = []
    for ch in text:
        if ch in " \t":
            out.append(ch)
        else:
            break
    return "".join(out)


CLOSE_FOR = {"(": ")", "[": "]", "{": "}"}


def _pending_closers(text):
    """Closing characters needed to balance brackets/quotes on one line."""
    stack = []
    quote = None
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if quote is not None:
            if ch == "\\":
                index += 2
                continue
            if text.startswith(quote, index):
                index += len(quote)
                quote = None
                continue
            index += 1
            continue
        if ch == "#":
            break
        if ch in "\"'":
            if text.startswith(ch * 3, index):
                quote = ch * 3
                index += 3
            else:
                quote = ch
                index += 1
            continue
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if stack and CLOSE_FOR[stack[-1]] == ch:
                stack.pop()
        index += 1
    out = quote or ""
    for opener in reversed(stack):
        out += CLOSE_FOR[opener]
    return out


def _previous_indent(lines, index):
    """Indentation of the closest non-blank line before `index` (0-based)."""
    scan = index - 1
    while scan >= 0:
        if lines[scan].strip():
            return leading_ws(lines[scan])
        scan -= 1
    return ""


def _repair_line(original, exc, prev_indent):
    """Best-effort repair of a line the parser choked on."""
    stripped = original.strip()
    indent = leading_ws(original)
    message = str(getattr(exc, "msg", "") or "")
    lowered = message.lower()
    if "never closed" in lowered or "unterminated" in lowered or "unexpected eof" in lowered:
        closers = _pending_closers(original)
        if closers:
            return original + closers
    if stripped and "indent" in lowered and indent != prev_indent:
        return prev_indent + stripped
    if not stripped:
        return original
    match = re.match(r"^(async\s+)?def\s+([A-Za-z_]\w*)", stripped)
    if match:
        prefix = "async " if match.group(1) else ""
        return indent + prefix + "def " + match.group(2) + "():"
    match = re.match(r"^class\s+([A-Za-z_]\w*)", stripped)
    if match:
        return indent + "class " + match.group(1) + ":"
    match = re.match(r"^(if|elif|while)\b", stripped)
    if match:
        return indent + match.group(1) + " True:"
    if re.match(r"^except\b", stripped):
        return indent + "except Exception:"
    if re.match(r"^(else|try|finally)\b", stripped):
        return indent + re.match(r"^(else|try|finally)", stripped).group(1) + ":"
    if re.match(r"^(for|with|async)\b", stripped) or stripped.endswith(":"):
        return indent + "if True:"
    return indent + "pass"


def _try_parse(lines, limit=200):
    work = list(lines)
    attempts = {}
    for _ in range(limit):
        try:
            return ast.parse("\n".join(work))
        except SyntaxError as exc:
            if not work:
                return None
            lineno = getattr(exc, "lineno", None)
            if lineno is None:
                return None
            if lineno < 1:
                lineno = 1
            if lineno > len(work):
                lineno = len(work)
            index = lineno - 1
            original = work[index]
            stage = attempts.get(lineno, 0)
            while stage <= 4:
                if stage == 0:
                    replacement = _repair_line(original, exc, _previous_indent(work, index))
                elif stage == 1:
                    replacement = leading_ws(original) + "pass"
                elif stage == 2:
                    replacement = ""
                elif stage == 3:
                    replacement = "pass"
                else:
                    replacement = None
                    break
                if replacement != original:
                    break
                stage += 1
            attempts[lineno] = stage + 1
            if replacement is None or stage > 4:
                return None
            work[index] = replacement
        except Exception:
            return None
    return None


def tolerant_parse(lines, cursor_line):
    tree = _try_parse(lines)
    if tree is not None:
        return tree
    if 1 <= cursor_line <= len(lines):
        head = list(lines[:cursor_line])
        head[cursor_line - 1] = leading_ws(head[cursor_line - 1]) + "pass"
        tree = _try_parse(head)
        if tree is not None:
            return tree
        tree = _try_parse(lines[: cursor_line - 1])
        if tree is not None:
            return tree
    return ast.Module(body=[], type_ignores=[])


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------
# Analyzer -- builds scopes and resolves values
# ---------------------------------------------------------------------------

_LITERAL_TYPES = {
    ast.List: list,
    ast.ListComp: list,
    ast.Tuple: tuple,
    ast.Set: set,
    ast.SetComp: set,
    ast.Dict: dict,
    ast.DictComp: dict,
    ast.JoinedStr: str,
}


class Analyzer:
    def __init__(self, tree, path, lines, importer=None):
        self.tree = tree
        self.path = path
        self.lines = lines
        self.directory = os.path.dirname(os.path.abspath(path)) if path else ""
        self.importer = importer or Importer(self.directory)
        self.module_scope = Scope("module", tree, None)
        for stmt in getattr(tree, "body", []):
            self._stmt(stmt, self.module_scope)

    # -- scope construction ------------------------------------------------

    def _bind(self, scope, name, lineno, btype, **kw):
        if not isinstance(name, str) or not name:
            return
        scope.add(Binding(name, lineno, btype, **kw))

    def _bind_target(self, target, scope, lineno, value_node=None, annotation=None):
        if isinstance(target, ast.Name):
            self._bind(
                scope,
                target.id,
                lineno,
                "assign",
                node=target,
                value_node=value_node,
                annotation=annotation,
            )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._bind_target(elt, scope, lineno, None)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, scope, lineno, None)

    def _params(self, args, scope, self_kind=None, class_scope=None):
        node = scope.node
        lineno = getattr(node, "lineno", 0)
        ordered = []
        ordered.extend(getattr(args, "posonlyargs", []) or [])
        ordered.extend(args.args or [])
        if args.vararg is not None:
            ordered.append(args.vararg)
        ordered.extend(args.kwonlyargs or [])
        if args.kwarg is not None:
            ordered.append(args.kwarg)
        for index, arg in enumerate(ordered):
            special = None
            target_scope = None
            if index == 0 and self_kind is not None and arg is not args.vararg and arg is not args.kwarg:
                special = self_kind
                target_scope = class_scope
            self._bind(
                scope,
                arg.arg,
                getattr(arg, "lineno", lineno),
                "param",
                node=arg,
                annotation=getattr(arg, "annotation", None),
                special=special,
                target_scope=target_scope,
            )

    def _decorator_names(self, node):
        names = set()
        for dec in getattr(node, "decorator_list", []) or []:
            cur = dec
            if isinstance(cur, ast.Call):
                cur = cur.func
            if isinstance(cur, ast.Name):
                names.add(cur.id)
            elif isinstance(cur, ast.Attribute):
                names.add(cur.attr)
        return names

    def _stmt(self, node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._bind(scope, node.name, node.lineno, "function", node=node)
            fscope = Scope("function", node, scope)
            self_kind = None
            class_scope = None
            if scope.kind == "class":
                decorators = self._decorator_names(node)
                if "staticmethod" in decorators:
                    self_kind = None
                elif "classmethod" in decorators:
                    self_kind = "cls"
                    class_scope = scope
                else:
                    self_kind = "self"
                    class_scope = scope
            self._params(node.args, fscope, self_kind, class_scope)
            for dec in node.decorator_list or []:
                self._expr(dec, scope)
            for default in list(node.args.defaults or []) + [d for d in (node.args.kw_defaults or []) if d]:
                self._expr(default, scope)
            for sub in node.body:
                self._stmt(sub, fscope)
            return

        if isinstance(node, ast.ClassDef):
            cscope = Scope("class", node, scope)
            self._bind(scope, node.name, node.lineno, "class", node=node, target_scope=cscope)
            for base in node.bases:
                self._expr(base, scope)
            for dec in node.decorator_list or []:
                self._expr(dec, scope)
            for sub in node.body:
                self._stmt(sub, cscope)
            return

        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._bind_target(target, scope, node.lineno, node.value)
            self._expr(node.value, scope)
            return

        if isinstance(node, ast.AnnAssign):
            self._bind_target(node.target, scope, node.lineno, node.value, node.annotation)
            if node.value is not None:
                self._expr(node.value, scope)
            return

        if isinstance(node, ast.AugAssign):
            self._bind_target(node.target, scope, node.lineno, node.value)
            self._expr(node.value, scope)
            return

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._import(node, scope)
            return

        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._bind_target(node.target, scope, node.lineno, None)
            self._expr(node.iter, scope)
            for sub in list(node.body) + list(node.orelse):
                self._stmt(sub, scope)
            return

        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self._expr(item.context_expr, scope)
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, scope, node.lineno, item.context_expr)
            for sub in node.body:
                self._stmt(sub, scope)
            return

        if isinstance(node, (ast.If, ast.While)):
            self._expr(node.test, scope)
            for sub in list(node.body) + list(node.orelse):
                self._stmt(sub, scope)
            return

        if isinstance(node, ast.Try) or node.__class__.__name__ == "TryStar":
            for sub in list(node.body) + list(node.orelse) + list(node.finalbody):
                self._stmt(sub, scope)
            for handler in node.handlers:
                if handler.name:
                    fake = None
                    if handler.type is not None:
                        fake = ast.Call(func=handler.type, args=[], keywords=[])
                        ast.copy_location(fake, handler)
                    self._bind(
                        scope,
                        handler.name,
                        handler.lineno,
                        "assign",
                        value_node=fake,
                    )
                if handler.type is not None:
                    self._expr(handler.type, scope)
                for sub in handler.body:
                    self._stmt(sub, scope)
            return

        if isinstance(node, (ast.Global, ast.Nonlocal, ast.Pass, ast.Break, ast.Continue)):
            return

        if node.__class__.__name__ == "Match":
            self._expr(node.subject, scope)
            for case in node.cases:
                self._pattern(getattr(case, "pattern", None), scope)
                if getattr(case, "guard", None) is not None:
                    self._expr(case.guard, scope)
                for sub in case.body:
                    self._stmt(sub, scope)
            return

        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._stmt(child, scope)
            elif isinstance(child, ast.expr):
                self._expr(child, scope)

    def _pattern(self, pattern, scope):
        if pattern is None:
            return
        name = getattr(pattern, "name", None)
        if isinstance(name, str):
            self._bind(scope, name, getattr(pattern, "lineno", 0), "assign")
        rest = getattr(pattern, "rest", None)
        if isinstance(rest, str):
            self._bind(scope, rest, getattr(pattern, "lineno", 0), "assign")
        for child in ast.iter_child_nodes(pattern):
            if isinstance(child, ast.expr):
                continue
            self._pattern(child, scope)

    def _import(self, node, scope):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self._bind(
                        scope,
                        alias.asname,
                        node.lineno,
                        "import",
                        imp=("module", alias.name),
                    )
                else:
                    top = alias.name.split(".")[0]
                    self._bind(scope, top, node.lineno, "import", imp=("module", top))
            return

        module = node.module or ""
        level = getattr(node, "level", 0) or 0
        for alias in node.names:
            if alias.name == "*":
                for name, ctype, desc in self.star_import_entries(module, level):
                    self._bind(
                        scope,
                        name,
                        node.lineno,
                        "import",
                        imp=("star", module, level, name),
                    )
                continue
            bound = alias.asname or alias.name
            self._bind(
                scope,
                bound,
                node.lineno,
                "import",
                imp=("from", module, level, alias.name),
            )

    # -- expressions -------------------------------------------------------

    def _expr(self, node, scope):
        if node is None:
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            cscope = Scope("comp", node, scope)
            for index, gen in enumerate(node.generators):
                self._bind_target(gen.target, cscope, getattr(gen.target, "lineno", node.lineno), None)
                self._expr(gen.iter, scope if index == 0 else cscope)
                for cond in gen.ifs:
                    self._expr(cond, cscope)
            if isinstance(node, ast.DictComp):
                self._expr(node.key, cscope)
                self._expr(node.value, cscope)
            else:
                self._expr(node.elt, cscope)
            return
        if isinstance(node, ast.Lambda):
            lscope = Scope("lambda", node, scope)
            self._params(node.args, lscope)
            for default in list(node.args.defaults or []) + [d for d in (node.args.kw_defaults or []) if d]:
                self._expr(default, scope)
            self._expr(node.body, lscope)
            return
        if isinstance(node, ast.NamedExpr):
            if isinstance(node.target, ast.Name):
                self._bind(
                    scope,
                    node.target.id,
                    node.lineno,
                    "assign",
                    value_node=node.value,
                )
            self._expr(node.value, scope)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self._expr(child, scope)

    # -- scope lookup ------------------------------------------------------

    def scope_for(self, line, col):
        ast_scope = self._descend(self.module_scope, line, col)
        indent_scope = self._indent_scope(line, col)
        if indent_scope is None:
            return ast_scope
        if self._is_within(indent_scope, ast_scope):
            return indent_scope
        return ast_scope

    def _indent_scope(self, line, col):
        """Scope implied by the indentation of the cursor."""
        prev = self._previous_code_line(line)
        if prev is None:
            return None
        scope = self._descend(self.module_scope, prev)
        indent = self._effective_indent(line, col)
        while scope is not self.module_scope and indent < scope.body_indent:
            scope = scope.parent
        return scope

    @staticmethod
    def _is_within(scope, ancestor):
        current = scope
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False

    def _descend(self, scope, line, col=None):
        for child in scope.children:
            if child.contains(line, col):
                return self._descend(child, line, col)
        return scope

    def _previous_code_line(self, line):
        index = min(line, len(self.lines)) - 1
        while index >= 0:
            if index + 1 < line:
                text = self.lines[index].strip()
                if text and not text.startswith("#"):
                    return index + 1
            index -= 1
        return None

    def _effective_indent(self, line, col):
        if 1 <= line <= len(self.lines):
            text = self.lines[line - 1]
            before = text[:col]
            if before.strip():
                return len(text) - len(text.lstrip())
        return col

    def visible_bindings(self, line, col, scope=None):
        """Ordered mapping name -> Binding visible at the cursor."""
        scope = scope or self.scope_for(line, col)
        result = {}
        current = scope
        innermost = True
        limited = True
        while current is not None:
            if current.kind == "class" and not innermost:
                current = current.parent
                innermost = False
                continue
            apply_limit = limited or current.kind == "module"
            local = {}
            for binding in current.bindings:
                if apply_limit and not binding.is_param and binding.lineno > line:
                    continue
                local[binding.name] = binding
            for name, binding in local.items():
                result.setdefault(name, binding)
            if current.kind in ("function", "lambda"):
                limited = False
            innermost = False
            current = current.parent
        return result

    # -- imports -----------------------------------------------------------

    def resolve_import(self, imp):
        if not imp:
            return UNKNOWN
        kind = imp[0]
        if kind == "module":
            name = imp[1]
            mod = self.importer.import_module(name)
            if mod is not None:
                return RuntimeValue(mod)
            static = self.importer.static_module(name.split(".")[0])
            if static is not None:
                return StaticModuleValue(static, name)
            return UNKNOWN
        if kind in ("from", "star"):
            module, level, attr = imp[1], imp[2], imp[3]
            base = self._resolve_from_module(module, level)
            if base is None:
                if level and not module:
                    mod = self.importer.import_module(attr)
                    if mod is not None:
                        return RuntimeValue(mod)
                    static = self.importer.static_module(attr)
                    if static is not None:
                        return StaticModuleValue(static, attr)
                return UNKNOWN
            if isinstance(base, StaticModuleValue):
                binding = base.analyzer.module_scope_binding(attr)
                if binding is not None:
                    return binding.get_value(base.analyzer)
                return UNKNOWN
            mod = base.obj
            try:
                if hasattr(mod, attr):
                    return RuntimeValue(getattr(mod, attr))
            except Exception:
                return UNKNOWN
            sub = self.importer.import_module(
                (getattr(mod, "__name__", "") + "." + attr).lstrip(".")
            )
            if sub is not None:
                return RuntimeValue(sub)
            return UNKNOWN
        return UNKNOWN

    def module_scope_binding(self, name):
        found = None
        for binding in self.module_scope.bindings:
            if binding.name == name:
                found = binding
        return found

    def _resolve_from_module(self, module, level):
        if level:
            if not module:
                return None
            mod = self.importer.import_module(module)
            if mod is not None:
                return RuntimeValue(mod)
            static = self.importer.static_module(module.split(".")[0])
            if static is not None:
                return StaticModuleValue(static, module)
            return None
        mod = self.importer.import_module(module)
        if mod is not None:
            return RuntimeValue(mod)
        static = self.importer.static_module(module.split(".")[0])
        if static is not None:
            return StaticModuleValue(static, module)
        return None

    def star_import_entries(self, module, level):
        base = self._resolve_from_module(module, level)
        if base is None:
            return []
        if isinstance(base, StaticModuleValue):
            return base.analyzer.public_module_entries()
        return module_public_entries(base.obj)

    def public_module_entries(self):
        entries = []
        seen = set()
        for binding in reversed(self.module_scope.bindings):
            if binding.name.startswith("_") or binding.name in seen:
                continue
            seen.add(binding.name)
            ctype, desc = binding.completion(self)
            entries.append((binding.name, ctype, desc))
        return entries

    # -- value resolution --------------------------------------------------

    def value_from_annotation(self, node, scope, depth=0):
        if depth > MAX_DEPTH or node is None:
            return UNKNOWN
        line = getattr(node, "lineno", 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval").body
            except Exception:
                return UNKNOWN
        if isinstance(node, ast.Subscript):
            node = node.value
        value = self.resolve(node, scope, line + 1, depth + 1)
        if isinstance(value, ClassValue):
            return InstanceValue(value.scope)
        if isinstance(value, RuntimeValue) and inspect.isclass(value.obj):
            return RuntimeInstanceValue(value.obj)
        return UNKNOWN

    def resolve(self, node, scope, line, depth=0):
        if node is None or depth > MAX_DEPTH:
            return UNKNOWN
        try:
            return self._resolve(node, scope, line, depth)
        except Exception:
            return UNKNOWN

    def _resolve(self, node, scope, line, depth):
        for cls, py_type in _LITERAL_TYPES.items():
            if isinstance(node, cls):
                return RuntimeInstanceValue(py_type)
        if isinstance(node, ast.Constant):
            return RuntimeInstanceValue(type(node.value))
        if isinstance(node, ast.Name):
            bindings = self.visible_bindings(line, 0, scope)
            binding = bindings.get(node.id)
            if binding is not None:
                return binding.get_value(self, depth)
            if hasattr(builtins, node.id):
                return RuntimeValue(getattr(builtins, node.id))
            return UNKNOWN
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value, scope, line, depth + 1)
            return self.attribute_value(base, node.attr, depth)
        if isinstance(node, ast.Call):
            func = self.resolve(node.func, scope, line, depth + 1)
            if isinstance(func, ClassValue):
                return InstanceValue(func.scope)
            if isinstance(func, RuntimeValue) and inspect.isclass(func.obj):
                return RuntimeInstanceValue(func.obj)
            return UNKNOWN
        if isinstance(node, ast.IfExp):
            value = self.resolve(node.body, scope, line, depth + 1)
            if not isinstance(value, UnknownValue):
                return value
            return self.resolve(node.orelse, scope, line, depth + 1)
        if isinstance(node, ast.Await):
            return UNKNOWN
        if isinstance(node, ast.Lambda):
            return FunctionValue(node)
        if isinstance(node, ast.Compare):
            return RuntimeInstanceValue(bool)
        return UNKNOWN

    def attribute_value(self, base, attr, depth=0):
        """Value of `base.attr`."""
        if isinstance(base, (RuntimeValue, RuntimeInstanceValue)):
            owner = base.obj if isinstance(base, RuntimeValue) else base.cls
            try:
                if hasattr(owner, attr):
                    return RuntimeValue(getattr(owner, attr))
            except Exception:
                return UNKNOWN
            if inspect.ismodule(owner):
                sub = self.importer.import_module(
                    (getattr(owner, "__name__", "") + "." + attr).lstrip(".")
                )
                if sub is not None:
                    return RuntimeValue(sub)
            return UNKNOWN
        if isinstance(base, StaticModuleValue):
            binding = base.analyzer.module_scope_binding(attr)
            if binding is not None:
                return binding.get_value(base.analyzer)
            return UNKNOWN
        if isinstance(base, (ClassValue, InstanceValue)):
            is_instance = isinstance(base, InstanceValue)
            for _owner, binding in self._class_bindings(base.scope, is_instance):
                if binding.name == attr:
                    return binding.get_value(self, depth)
        return UNKNOWN

    # -- class attribute collection ---------------------------------------

    def _class_mro(self, scope, seen=None):
        if seen is None:
            seen = set()
        if id(scope) in seen:
            return []
        seen.add(id(scope))
        order = [scope]
        for base in getattr(scope.node, "bases", []) or []:
            value = self.resolve(base, scope.parent, getattr(scope.node, "lineno", 1) + 1)
            if isinstance(value, ClassValue):
                order.extend(self._class_mro(value.scope, seen))
        return order

    def _self_attr_bindings(self, class_scope):
        """Bindings created by `self.x = ...` inside __init__."""
        init = None
        for binding in class_scope.bindings:
            if binding.name == "__init__" and binding.btype == "function":
                init = binding
        if init is None or init.node is None:
            return []
        init_scope = None
        for child in class_scope.children:
            if child.node is init.node:
                init_scope = child
        args = init.node.args
        positional = (getattr(args, "posonlyargs", []) or []) + (args.args or [])
        if not positional:
            return []
        self_name = positional[0].arg
        found = {}
        order = []
        for node in ast.walk(init.node):
            targets = []
            value = None
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
                value = node.value
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                targets = [node.target]
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                targets = [i.optional_vars for i in node.items if i.optional_vars is not None]
            for target in targets:
                for attr_node in self._iter_self_attrs(target, self_name):
                    binding = Binding(
                        attr_node.attr,
                        getattr(attr_node, "lineno", 0),
                        "assign",
                        value_node=value if len(targets) == 1 else None,
                        scope=init_scope or class_scope,
                    )
                    if attr_node.attr not in found:
                        order.append(binding)
                        found[attr_node.attr] = binding
        return order

    def _iter_self_attrs(self, target, self_name):
        if isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Name) and target.value.id == self_name:
                yield target
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                yield from self._iter_self_attrs(elt, self_name)
        elif isinstance(target, ast.Starred):
            yield from self._iter_self_attrs(target.value, self_name)

    def _class_bindings(self, class_scope, is_instance):
        """Yield (owner_scope, binding) pairs, nearest definition first."""
        pairs = []
        for scope in self._class_mro(class_scope):
            if is_instance:
                for binding in self._self_attr_bindings(scope):
                    pairs.append((scope, binding))
            local = {}
            for binding in scope.bindings:
                local[binding.name] = binding
            for binding in local.values():
                pairs.append((scope, binding))
        return pairs

    def class_entries(self, class_scope, is_instance):
        entries = []
        seen = set()
        for _owner, binding in self._class_bindings(class_scope, is_instance):
            if binding.name in seen:
                continue
            seen.add(binding.name)
            ctype, desc = binding.completion(self)
            entries.append((binding.name, ctype, desc))
        return entries

    # -- attribute entries for a value ------------------------------------

    def attributes_of(self, value):
        if isinstance(value, RuntimeValue):
            obj = value.obj
            if inspect.ismodule(obj):
                return module_public_entries(obj)
            return runtime_all_entries(obj)
        if isinstance(value, RuntimeInstanceValue):
            return runtime_all_entries(value.cls)
        if isinstance(value, StaticModuleValue):
            return value.analyzer.public_module_entries()
        if isinstance(value, ClassValue):
            return self.class_entries(value.scope, False)
        if isinstance(value, InstanceValue):
            return self.class_entries(value.scope, True)
        return []

    # -- name completion ---------------------------------------------------

    def name_entries(self, line, col):
        entries = []
        seen = set()
        for name, binding in self.visible_bindings(line, col).items():
            if name in seen:
                continue
            seen.add(name)
            ctype, desc = binding.completion(self)
            entries.append((name, ctype, desc))
        for name in dir(builtins):
            if name in seen:
                continue
            seen.add(name)
            try:
                obj = getattr(builtins, name)
            except Exception:
                entries.append((name, "statement", "statement"))
                continue
            entries.append(runtime_entry(name, obj))
        return entries


# ---------------------------------------------------------------------------
# Cursor context analysis
# ---------------------------------------------------------------------------


def match_string_start(text, index):
    quote = text[index]
    if index >= 2 and text[index - 1] == quote and text[index - 2] == quote:
        found = text.rfind(quote * 3, 0, index - 2)
        if found == -1:
            return None
        return found
    pos = index - 1
    while pos >= 0:
        ch = text[pos]
        if ch == "\n":
            return None
        if ch == quote:
            backslashes = 0
            scan = pos - 1
            while scan >= 0 and text[scan] == "\\":
                backslashes += 1
                scan -= 1
            if backslashes % 2 == 0:
                return pos
        pos -= 1
    return None


def match_bracket_start(text, index):
    close = text[index]
    open_char = OPEN_FOR[close]
    depth = 0
    pos = index
    while pos >= 0:
        ch = text[pos]
        if ch in "\"'":
            start = match_string_start(text, pos)
            if start is None:
                return None
            pos = start - 1
            continue
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            depth -= 1
            if depth == 0:
                if ch != open_char:
                    return None
                return pos
        pos -= 1
    return None


def skip_ws_back(text, pos, cross_lines=True):
    while pos >= 0:
        ch = text[pos]
        if ch in " \t":
            pos -= 1
        elif ch == "\n" and pos >= 1 and text[pos - 1] == "\\":
            pos -= 2  # explicit line continuation
        elif cross_lines and ch == "\n":
            pos -= 1
        else:
            break
    return pos


def scan_receiver(text, end):
    """Source of the expression that ends right before index `end`."""
    pos = skip_ws_back(text, end - 1, cross_lines=False)
    start = None
    guard = 0
    while pos >= 0 and guard < 200:
        guard += 1
        ch = text[pos]
        if ch in ")]}":
            open_index = match_bracket_start(text, pos)
            if open_index is None:
                break
            start = open_index
            pos = skip_ws_back(text, open_index - 1, cross_lines=False)
            if pos >= 0 and (is_ident_char(text[pos]) or text[pos] in ")]}"):
                continue
            if pos >= 0 and text[pos] == ".":
                pos = skip_ws_back(text, pos - 1, cross_lines=False)
                continue
            break
        if is_ident_char(ch):
            scan = pos
            while scan >= 0 and is_ident_char(text[scan]):
                scan -= 1
            start = scan + 1
            pos = skip_ws_back(text, scan, cross_lines=False)
            if pos >= 0 and text[pos] == "." and not (pos >= 1 and text[pos - 1] == "."):
                pos = skip_ws_back(text, pos - 1, cross_lines=False)
                continue
            break
        if ch in "\"'":
            string_start = match_string_start(text, pos)
            if string_start is None:
                break
            start = string_start
            scan = string_start - 1
            prefix_start = scan + 1
            count = 0
            while scan >= 0 and text[scan] in STRING_PREFIX_CHARS and count < 3:
                prefix_start = scan
                scan -= 1
                count += 1
            if prefix_start < string_start and (scan < 0 or not is_ident_char(text[scan])):
                start = prefix_start
            break
        break
    if start is None:
        return None
    return text[start:end]


def analyze_context(text):
    """Return (kind, prefix, receiver_source) for the text before the cursor."""
    pos = len(text)
    scan = pos
    while scan > 0 and is_ident_char(text[scan - 1]):
        scan -= 1
    prefix = text[scan:pos]
    before = skip_ws_back(text, scan - 1, cross_lines=False)
    if before >= 0 and text[before] == ".":
        if before >= 1 and text[before - 1] == ".":
            return "name", prefix, None
        receiver = scan_receiver(text, before)
        return "attr", prefix, receiver
    return "name", prefix, None


# ---------------------------------------------------------------------------
# Matching and ordering
# ---------------------------------------------------------------------------


def matches(name, prefix, fuzzy):
    if not prefix:
        return True
    lname = name.lower()
    lprefix = prefix.lower()
    if not fuzzy:
        return lname.startswith(lprefix)
    index = 0
    for ch in lname:
        if ch == lprefix[index]:
            index += 1
            if index == len(lprefix):
                return True
    return False


def sort_key(item):
    name = item["name"]
    if item["type"] == "keyword":
        group = 3
    elif name.startswith("__") and name.endswith("__"):
        group = 2
    elif name.startswith("_"):
        group = 1
    else:
        group = 0
    return (group, name.lower(), name)


def build_completions(entries, prefix, fuzzy):
    seen = set()
    out = []
    cut = len(prefix)
    for name, ctype, desc in entries:
        if name in seen:
            continue
        seen.add(name)
        if not matches(name, prefix, fuzzy):
            continue
        out.append(
            {
                "name": name,
                "complete": name[cut:],
                "type": ctype,
                "description": desc,
            }
        )
    out.sort(key=sort_key)
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def fail(message):
    sys.stderr.write(str(message).rstrip("\n") + "\n")
    raise SystemExit(1)


def read_source(path):
    if not os.path.exists(path):
        fail("error: no such file: %s" % path)
    if not os.path.isfile(path):
        fail("error: not a regular file: %s" % path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        fail("error: cannot read %s: %s" % (path, exc))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("error: %s is not valid UTF-8" % path)
    return text


def complete(path, line, col, fuzzy):
    text = read_source(path)
    source = normalize(text)
    if source.startswith("\ufeff"):
        source = source[1:]
    lines = source.split("\n")
    if line < 1 or line > len(lines):
        fail("error: line %d out of range (file has %d lines)" % (line, len(lines)))
    if col < 0 or col > len(lines[line - 1]):
        fail("error: column %d out of range for line %d" % (col, line))

    offset = 0
    for existing in lines[: line - 1]:
        offset += len(existing) + 1
    offset += col

    try:
        completions = analyse(path, lines, source[:offset], line, col, fuzzy)
    except BaseException:
        # Completion is best effort: never fail because of a weird source file.
        completions = []

    sys.stdout.write(json.dumps({"completions": completions}, separators=(",", ":")) + "\n")
    return 0


def analyse(path, lines, before, line, col, fuzzy):
    kind, prefix, receiver = analyze_context(before)
    tree = tolerant_parse(lines, line)
    analyzer = Analyzer(tree, path, lines)

    if kind == "attr":
        entries = []
        if receiver:
            expression = receiver.replace("\\\n", " ").strip()
            try:
                node = ast.parse(expression, mode="eval").body
            except Exception:
                node = None
            if node is not None:
                scope = analyzer.scope_for(line, col)
                entries = analyzer.attributes_of(analyzer.resolve(node, scope, line))
        return build_completions(entries, prefix, fuzzy)

    completions = build_completions(analyzer.name_entries(line, col), prefix, fuzzy)
    keywords = [(kw, "keyword", kw) for kw in keyword.kwlist]
    completions.extend(build_completions(keywords, prefix, fuzzy))
    completions.sort(key=sort_key)
    return completions


def usage():
    fail("usage: sith.py complete <file> <line> <col> [--fuzzy]")


def main(argv):
    args = list(argv[1:])
    if not args:
        usage()
    command = args.pop(0)
    if command != "complete":
        fail("error: unknown command: %s" % command)
    fuzzy = False
    positional = []
    for arg in args:
        if arg == "--fuzzy":
            fuzzy = True
        elif arg.startswith("-") and arg != "-":
            fail("error: unknown option: %s" % arg)
        else:
            positional.append(arg)
    if len(positional) != 3:
        usage()
    try:
        line = int(positional[1])
        col = int(positional[2])
    except ValueError:
        fail("error: line and column must be integers")
    return complete(positional[0], line, col, fuzzy)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            sys.exit(1)
    except BaseException as exc:  # pragma: no cover - last resort
        sys.stderr.write("error: %s\n" % exc)
        sys.exit(1)
