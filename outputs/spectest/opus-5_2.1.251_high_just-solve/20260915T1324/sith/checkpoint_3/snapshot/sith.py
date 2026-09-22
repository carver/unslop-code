#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence engine.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer    <file> <line> <col> [--project <dir>]
    python sith.py goto     <file> <line> <col> [--follow-imports] [--project <dir>]

`complete` prints a compact JSON object with a "completions" array; `infer`
and `goto` print one with a "definitions" array.
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

    __slots__ = ("node", "scope")

    def __init__(self, node, scope=None):
        self.node = node
        self.scope = scope


class StaticModuleValue(Value):
    """A project module: parsed statically, never executed."""

    __slots__ = ("analyzer", "name")

    def __init__(self, analyzer, name):
        self.analyzer = analyzer
        self.name = name


NONE_INSTANCE = RuntimeInstanceValue(type(None))


def value_key(value):
    """Hashable identity for a value, used to de-duplicate unions."""
    if isinstance(value, RuntimeValue):
        obj = value.obj
        try:
            return ("runtime", id(obj))
        except Exception:  # pragma: no cover - defensive
            return ("runtime", 0)
    if isinstance(value, RuntimeInstanceValue):
        return ("runtime-instance", id(value.cls))
    if isinstance(value, ClassValue):
        return ("class", id(value.scope))
    if isinstance(value, InstanceValue):
        return ("instance", id(value.scope))
    if isinstance(value, FunctionValue):
        return ("function", id(value.node))
    if isinstance(value, StaticModuleValue):
        return ("module", id(value.analyzer))
    return ("unknown",)


def dedupe_values(values):
    out = []
    seen = set()
    for value in values:
        if value is None or isinstance(value, UnknownValue):
            continue
        key = value_key(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _iter_returns(node):
    """`return` statements belonging to `node`, skipping nested scopes."""
    stack = list(getattr(node, "body", []))
    out = []
    while stack:
        current = stack.pop(0)
        if isinstance(current, _NESTED_SCOPES):
            continue
        if isinstance(current, ast.Return):
            out.append(current)
            continue
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.stmt):
                stack.append(child)
    out.sort(key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))
    return out


def _has_yield(node):
    stack = list(getattr(node, "body", []))
    while stack:
        current = stack.pop()
        if isinstance(current, _NESTED_SCOPES):
            continue
        if isinstance(current, (ast.Yield, ast.YieldFrom)):
            return True
        stack.extend(ast.iter_child_nodes(current))
    return False


def _node_contains(node, line, col):
    start = getattr(node, "lineno", None)
    if start is None:
        return False
    end = getattr(node, "end_lineno", None) or start
    return start <= line <= end


def _body_span(body):
    if not body:
        return None
    start = getattr(body[0], "lineno", 0) or 0
    end = start
    for stmt in body:
        end = max(end, getattr(stmt, "end_lineno", None) or getattr(stmt, "lineno", 0) or 0)
    return (start, end)


def _flatten_test(test, positive):
    """Split `a and b` / `not a` into atomic (test, positive) pairs."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and positive:
        out = []
        for sub in test.values:
            out.extend(_flatten_test(sub, True))
        return out
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) and not positive:
        out = []
        for sub in test.values:
            out.extend(_flatten_test(sub, False))
        return out
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _flatten_test(test.operand, not positive)
    return [(test, positive)]


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
# The project -- module search, parsing and import resolution
# ---------------------------------------------------------------------------

STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ()) or ())

# Importing these has visible side effects, so they are never executed.
UNSAFE_MODULES = frozenset({"antigravity", "this", "idlelib", "turtledemo"})


def join_module(base: str, name: str) -> str:
    return base + "." + name if base else name


def posix_path(path: str) -> str:
    """Paths are always reported with forward slashes."""
    return path.replace(os.sep, "/").replace("\\", "/")


def _is_module_file(entry: str) -> bool:
    return (
        entry.endswith(".py")
        and entry != "__init__.py"
        and entry[:-3].isidentifier()
    )


def _is_package_dir(entry: str) -> bool:
    return entry.isidentifier() and not entry.startswith(".")


def _holds_python(path: str, depth: int = 1) -> bool:
    """True when `path` looks like a namespace package."""
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return False
    for entry in entries:
        full = os.path.join(path, entry)
        if os.path.isfile(full) and _is_module_file(entry):
            return True
        if depth > 0 and os.path.isdir(full) and _is_package_dir(entry):
            if os.path.isfile(os.path.join(full, "__init__.py")):
                return True
            if _holds_python(full, depth - 1):
                return True
    return False


def directory_modules(path: str) -> list:
    """Importable module and package names living directly inside `path`."""
    names = []
    seen = set()
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return names
    for entry in entries:
        full = os.path.join(path, entry)
        if os.path.isfile(full) and _is_module_file(entry):
            name = entry[:-3]
        elif os.path.isdir(full) and _is_package_dir(entry):
            if not os.path.isfile(os.path.join(full, "__init__.py")):
                if not _holds_python(full):
                    continue
            name = entry
        else:
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def module_entries(names) -> list:
    return [(name, "module", describe("module", name)) for name in names]


class Project:
    """Everything the tool is allowed to resolve imports against."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root) if root else ""
        self._static = {}
        self._loading = set()
        self._runtime = {}

    # -- paths and names ---------------------------------------------------

    def relative_path(self, path):
        """`path` relative to the project root, or None when outside it."""
        if not path or not self.root:
            return None
        absolute = os.path.abspath(path)
        try:
            relative = os.path.relpath(absolute, self.root)
        except ValueError:
            return None
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            return None
        if os.path.isabs(relative):
            return None
        return posix_path(relative)

    def module_name(self, path):
        """Dotted name of the module stored at `path`."""
        if not path:
            return ""
        relative = self.relative_path(path)
        if relative is None:
            absolute = os.path.abspath(path)
            base = os.path.basename(absolute)
            if base.endswith(".py"):
                base = base[:-3]
            if base == "__init__":
                return os.path.basename(os.path.dirname(absolute))
            return base
        if relative.endswith(".py"):
            relative = relative[:-3]
        parts = [part for part in relative.split("/") if part and part != "."]
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    # -- module search -----------------------------------------------------

    def locate(self, dotted):
        """("file", path) or ("namespace", dir) for a module in the project."""
        if not self.root or not os.path.isdir(self.root):
            return None
        parts = [part for part in dotted.split(".") if part] if dotted else []
        base = self.root
        for index, part in enumerate(parts):
            directory = os.path.join(base, part)
            if index < len(parts) - 1:
                if not os.path.isdir(directory):
                    return None
                base = directory
                continue
            init = os.path.join(directory, "__init__.py")
            if os.path.isfile(init):
                return ("file", init)
            module = directory + ".py"
            if os.path.isfile(module):
                return ("file", module)
            if os.path.isdir(directory):
                return ("namespace", directory)
            return None
        return ("namespace", self.root)

    def package_directory(self, dotted):
        """Directory holding the submodules of `dotted`, or None."""
        located = self.locate(dotted)
        if located is None:
            return None
        kind, path = located
        if kind == "namespace":
            return path
        if os.path.basename(path) == "__init__.py":
            return os.path.dirname(path)
        return None

    def static_module(self, dotted):
        """Analyzer for a project module, parsed but never executed."""
        if dotted in self._static:
            return self._static[dotted]
        if dotted in self._loading:
            # Circular import: only what is already bound is visible.
            return None
        located = self.locate(dotted)
        if located is None:
            self._static[dotted] = None
            return None
        kind, path = located
        self._loading.add(dotted)
        try:
            if kind == "namespace":
                analyzer = Analyzer(
                    ast.Module(body=[], type_ignores=[]), path, [], self, dotted
                )
            else:
                analyzer = self.parse(path, dotted)
        except Exception:
            analyzer = None
        finally:
            self._loading.discard(dotted)
        self._static[dotted] = analyzer
        return analyzer

    def adopt(self, analyzer):
        """Reuse the analyser of the file under the cursor for imports of it."""
        name = analyzer.module_name
        located = self.locate(name)
        if located is None or not analyzer.path:
            return
        if os.path.abspath(located[1]) == os.path.abspath(analyzer.path):
            self._static.setdefault(name, analyzer)

    def parse(self, path, dotted=None):
        """Parse a file into an Analyzer, tolerating syntax errors."""
        try:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            return None
        lines = normalize(text).split("\n")
        tree = tolerant_parse(lines, 0)
        if dotted is None:
            dotted = self.module_name(path)
        return Analyzer(tree, path, lines, self, dotted)

    def is_stdlib(self, dotted):
        top = dotted.split(".")[0] if dotted else ""
        if not top or top not in STDLIB_MODULES or top in UNSAFE_MODULES:
            return False
        # A project module of the same name shadows the standard library.
        return self.locate(top) is None

    def runtime_module(self, dotted):
        """Import a standard-library module, muting anything it prints."""
        if not self.is_stdlib(dotted):
            return None
        if dotted in self._runtime:
            return self._runtime[dotted]
        mod = None
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                mod = importlib.import_module(dotted)
        except BaseException:
            mod = None
        self._runtime[dotted] = mod
        return mod

    def resolve(self, dotted):
        """Value of an absolute module name: project first, then stdlib."""
        if dotted is None:
            return None
        analyzer = self.static_module(dotted)
        if analyzer is not None:
            return StaticModuleValue(analyzer, dotted)
        mod = self.runtime_module(dotted)
        if mod is not None:
            return RuntimeValue(mod)
        return None

    # -- completion sources ------------------------------------------------

    def top_level_entries(self):
        """Modules and packages a bare `import ...` could name."""
        names = directory_modules(self.root) if self.root else []
        seen = set(names)
        for name in sorted(STDLIB_MODULES):
            if name not in seen:
                seen.add(name)
                names.append(name)
        return module_entries(names)

    def submodule_names(self, dotted):
        directory = self.package_directory(dotted)
        if directory is not None:
            return directory_modules(directory)
        mod = self.runtime_module(dotted)
        paths = getattr(mod, "__path__", None) if mod is not None else None
        if not paths:
            return []
        names = set()
        try:
            for info in pkgutil.iter_modules(list(paths)):
                if info.name.isidentifier():
                    names.add(info.name)
        except Exception:
            return []
        return sorted(names)

    def submodule_entries(self, dotted):
        return module_entries(self.submodule_names(dotted))

    def import_entries(self, dotted):
        """Names offered by `from <dotted> import ...`."""
        value = self.resolve(dotted)
        if value is None:
            return []
        if isinstance(value, StaticModuleValue):
            entries = list(value.analyzer.exported_entries())
        else:
            entries = runtime_exported_entries(value.obj)
        seen = {entry[0] for entry in entries}
        for entry in self.submodule_entries(dotted):
            if entry[0] not in seen:
                seen.add(entry[0])
                entries.append(entry)
        return entries


def runtime_exported_entries(mod) -> list:
    """Names `from <mod> import ...` exposes: `__all__`, else public names."""
    try:
        raw = getattr(mod, "__all__", None)
    except Exception:
        raw = None
    if isinstance(raw, (list, tuple, set)):
        names = [name for name in raw if isinstance(name, str)]
    else:
        try:
            names = [name for name in dir(mod) if not name.startswith("_")]
        except Exception:
            names = []
    entries = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        try:
            obj = getattr(mod, name)
        except Exception:
            entries.append((name, "statement", "statement"))
            continue
        entries.append(runtime_entry(name, obj))
    return entries


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


def runtime_return_values(obj) -> list:
    """Return values of a real callable, taken from its annotation."""
    try:
        signature = inspect.signature(obj)
    except Exception:
        return []
    annotation = signature.return_annotation
    if annotation is inspect.Signature.empty:
        return []
    if annotation is None or annotation is type(None):
        return [NONE_INSTANCE]
    if inspect.isclass(annotation):
        return [RuntimeInstanceValue(annotation)]
    return []


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
        "path",
        "_value",
        "_values",
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
        path=(),
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
        self.path = path
        self._value = None
        self._values = None
        self._resolving = False

    @property
    def is_param(self):
        return self.btype == "param"

    def get_value(self, analyzer, depth=0):
        values = self.get_values(analyzer, depth)
        return values[0] if values else UNKNOWN

    def get_values(self, analyzer, depth=0):
        if self._values is not None:
            return self._values
        if self._resolving or depth > MAX_DEPTH:
            return []
        self._resolving = True
        try:
            values = self._compute(analyzer, depth)
        except Exception:
            values = []
        finally:
            self._resolving = False
        values = [v for v in values if not isinstance(v, UnknownValue)]
        self._values = values
        return values

    def _compute(self, analyzer, depth):
        if self.btype == "function":
            return [FunctionValue(self.node, self.target_scope)]
        if self.btype == "class":
            return [ClassValue(self.target_scope)]
        if self.btype == "import":
            return [analyzer.resolve_import(self.imp)]
        if self.btype == "param":
            if self.special == "self" and self.target_scope is not None:
                return [InstanceValue(self.target_scope)]
            if self.special == "cls" and self.target_scope is not None:
                return [ClassValue(self.target_scope)]
            if self.annotation is not None:
                return analyzer.values_from_annotation(
                    self.annotation, self.scope, depth + 1
                )
            return []
        values = []
        if self.value_node is not None:
            values = analyzer.resolve_all(
                self.value_node, self.scope, self.lineno, depth + 1
            )
        if not values and self.annotation is not None:
            values = analyzer.values_from_annotation(
                self.annotation, self.scope, depth + 1
            )
        return values

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


def _is_prefix(short, long):
    return len(short) <= len(long) and tuple(long[: len(short)]) == tuple(short)


def live_bindings(bindings):
    """Drop bindings that a later, unconditional rebinding overwrites."""
    live = []
    for binding in bindings:
        live = [b for b in live if not _is_prefix(binding.path, b.path)]
        live.append(binding)
    return live


class Scope:
    def __init__(self, kind, node, parent, analyzer=None):
        self.kind = kind  # module | function | class | lambda | comp
        self.node = node
        self.parent = parent
        self.children = []
        self.bindings = []
        self.analyzer = analyzer if analyzer is not None else (
            parent.analyzer if parent is not None else None
        )
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
    def __init__(self, tree, path, lines, project=None, module_name=None):
        self.tree = tree
        self.path = path
        self.lines = lines
        self.directory = os.path.dirname(os.path.abspath(path)) if path else ""
        self.project = project if project is not None else Project(self.directory)
        self.module_name = (
            module_name if module_name is not None else self.project.module_name(path)
        )
        self.is_package = bool(path) and (
            os.path.basename(path) == "__init__.py" or os.path.isdir(path)
        )
        self._path = ()
        self._narrow = None
        self._call_stack = set()
        self._condition_cache = {}
        self.statement_lines = {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.stmt) and getattr(node, "lineno", None)
        }
        self.module_scope = Scope("module", tree, None, analyzer=self)
        for stmt in getattr(tree, "body", []):
            self._stmt(stmt, self.module_scope)

    # -- scope construction ------------------------------------------------

    def _bind(self, scope, name, lineno, btype, **kw):
        if not isinstance(name, str) or not name:
            return
        kw.setdefault("path", self._path)
        scope.add(Binding(name, lineno, btype, **kw))

    @contextlib.contextmanager
    def _branch(self, node, index):
        saved = self._path
        self._path = saved + ((id(node), index),)
        try:
            yield
        finally:
            self._path = saved

    def _body(self, stmts, scope, node=None, index=None):
        if node is None:
            for sub in stmts:
                self._stmt(sub, scope)
            return
        with self._branch(node, index):
            for sub in stmts:
                self._stmt(sub, scope)

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
            fscope = Scope("function", node, scope)
            self._bind(
                scope, node.name, node.lineno, "function", node=node, target_scope=fscope
            )
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
            saved = self._path
            self._path = ()
            try:
                for sub in node.body:
                    self._stmt(sub, fscope)
            finally:
                self._path = saved
            return

        if isinstance(node, ast.ClassDef):
            cscope = Scope("class", node, scope)
            self._bind(scope, node.name, node.lineno, "class", node=node, target_scope=cscope)
            for base in node.bases:
                self._expr(base, scope)
            for dec in node.decorator_list or []:
                self._expr(dec, scope)
            saved = self._path
            self._path = ()
            try:
                for sub in node.body:
                    self._stmt(sub, cscope)
            finally:
                self._path = saved
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
            self._expr(node.iter, scope)
            with self._branch(node, 0):
                self._bind_target(node.target, scope, node.lineno, None)
                for sub in node.body:
                    self._stmt(sub, scope)
            self._body(node.orelse, scope, node, 1)
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
            self._body(node.body, scope, node, 0)
            self._body(node.orelse, scope, node, 1)
            return

        if isinstance(node, ast.Try) or node.__class__.__name__ == "TryStar":
            self._body(node.body, scope, node, 0)
            self._body(node.orelse, scope, node, 1)
            for index, handler in enumerate(node.handlers):
                with self._branch(node, 2 + index):
                    self._handler(handler, scope)
            for sub in node.finalbody:
                self._stmt(sub, scope)
            return

        if isinstance(node, (ast.Global, ast.Nonlocal, ast.Pass, ast.Break, ast.Continue)):
            return

        if node.__class__.__name__ == "Match":
            self._expr(node.subject, scope)
            for index, case in enumerate(node.cases):
                with self._branch(node, index):
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

    def _handler(self, handler, scope):
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
                        node=alias,
                        imp=("module", alias.name),
                    )
                else:
                    top = alias.name.split(".")[0]
                    self._bind(
                        scope,
                        top,
                        node.lineno,
                        "import",
                        node=alias,
                        imp=("module", top),
                    )
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
                node=alias,
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
        return {
            name: bindings[-1]
            for name, bindings in self.visible_binding_lists(line, col, scope).items()
        }

    def visible_binding_lists(self, line, col, scope=None):
        """Ordered mapping name -> live Bindings visible at the cursor."""
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
                local.setdefault(binding.name, []).append(binding)
            for name, bindings in local.items():
                result.setdefault(name, live_bindings(bindings))
            if current.kind in ("function", "lambda"):
                limited = False
            innermost = False
            current = current.parent
        return result

    def visible_binding_list(self, name, line, col, scope=None):
        return self.visible_binding_lists(line, col, scope).get(name, [])

    def name_bindings(self, name, line, col, scope=None):
        """Bindings for `name` at the cursor, including forward globals."""
        scope = scope or self.scope_for(line, col)
        bindings = self.visible_binding_list(name, line, col, scope)
        if bindings or not self._inside_function(scope):
            return bindings
        # A global referenced from inside a function body may well be defined
        # further down the module: it only has to exist when the call happens.
        return live_bindings(
            [b for b in self.module_scope.bindings if b.name == name]
        )

    @staticmethod
    def _inside_function(scope):
        current = scope
        while current is not None:
            if current.kind in ("function", "lambda", "comp"):
                return True
            current = current.parent
        return False

    def definition_binding_at(self, name, line, col):
        """Binding for a `def`/`class` whose own name sits under the cursor."""
        found = []

        def walk(scope):
            for child in scope.children:
                node = child.node
                if (
                    child.kind in ("function", "class")
                    and getattr(node, "name", None) == name
                    and getattr(node, "lineno", None) == line
                ):
                    text = _source_line(self.lines, line)
                    start = _name_column(text, name, getattr(node, "col_offset", 0) or 0)
                    if start <= col <= start + len(name):
                        for binding in scope.bindings:
                            if binding.node is node:
                                found.append(binding)
                walk(child)

        walk(self.module_scope)
        return found

    # -- imports -----------------------------------------------------------

    @property
    def package_parts(self):
        """Dotted parts of the package this module lives in."""
        parts = [part for part in self.module_name.split(".") if part]
        if self.is_package:
            return parts
        return parts[:-1]

    def absolute_module(self, module, level):
        """Absolute name of an imported module, or None if unresolvable.

        An empty string names the project root itself, which is what a
        relative import from a module sitting directly in the root reaches.
        """
        if not level:
            return module or None
        parts = list(self.package_parts)
        climb = level - 1
        if climb > len(parts):
            return None  # above the project root
        if climb:
            parts = parts[: len(parts) - climb]
        if module:
            parts.extend(part for part in module.split(".") if part)
        return ".".join(parts)

    def import_module_value(self, module, level):
        """Value of the module an import statement names."""
        return self.project.resolve(self.absolute_module(module, level))

    def module_attribute(self, base, attr):
        """`base.attr` where `base` is a module: a name in it or a submodule."""
        if isinstance(base, StaticModuleValue):
            binding = base.analyzer.module_scope_binding(attr)
            if binding is not None:
                return binding.get_value(base.analyzer)
            return self.project.resolve(join_module(base.name, attr))
        if isinstance(base, RuntimeValue):
            mod = base.obj
            try:
                if hasattr(mod, attr):
                    return RuntimeValue(getattr(mod, attr))
            except Exception:
                return None
            sub = self.project.runtime_module(
                join_module(getattr(mod, "__name__", ""), attr)
            )
            if sub is not None:
                return RuntimeValue(sub)
        return None

    def resolve_import(self, imp):
        if not imp:
            return UNKNOWN
        kind = imp[0]
        if kind == "module":
            value = self.project.resolve(imp[1])
            return value if value is not None else UNKNOWN
        if kind in ("from", "star"):
            module, level, attr = imp[1], imp[2], imp[3]
            base = self.import_module_value(module, level)
            if base is None:
                return UNKNOWN
            value = self.module_attribute(base, attr)
            return value if value is not None else UNKNOWN
        return UNKNOWN

    def module_scope_binding(self, name):
        found = None
        for binding in self.module_scope.bindings:
            if binding.name == name:
                found = binding
        return found

    def star_import_entries(self, module, level):
        base = self.import_module_value(module, level)
        if base is None:
            return []
        if isinstance(base, StaticModuleValue):
            return base.analyzer.exported_entries()
        return runtime_exported_entries(base.obj)

    def dunder_all(self):
        """Names listed in a literal `__all__`, or None when there is none."""
        names = []
        found = False
        for binding in self.module_scope.bindings:
            if binding.name != "__all__" or binding.value_node is None:
                continue
            try:
                value = ast.literal_eval(binding.value_node)
            except Exception:
                continue
            if isinstance(value, (list, tuple, set)):
                found = True
                names.extend(item for item in value if isinstance(item, str))
        return names if found else None

    def exported_entries(self):
        """Public names of this module: `__all__`, else non-underscore names."""
        exported = self.dunder_all()
        if exported is None:
            return self.public_module_entries()
        entries = []
        seen = set()
        for name in exported:
            if name in seen:
                continue
            seen.add(name)
            binding = self.module_scope_binding(name)
            if binding is not None:
                ctype, desc = binding.completion(self)
            elif self.project.resolve(join_module(self.module_name, name)) is not None:
                ctype, desc = "module", describe("module", name)
            else:
                ctype, desc = "statement", "statement"
            entries.append((name, ctype, desc))
        return entries

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

    def values_from_annotation(self, node, scope, depth=0):
        if depth > MAX_DEPTH or node is None:
            return []
        line = getattr(node, "lineno", 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval").body
            except Exception:
                return []
        if isinstance(node, ast.Constant) and node.value is None:
            return [NONE_INSTANCE]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            out = self.values_from_annotation(node.left, scope, depth + 1)
            out += self.values_from_annotation(node.right, scope, depth + 1)
            return dedupe_values(out)
        if isinstance(node, ast.Subscript):
            head = node.value
            head_name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
            if head_name in ("Optional", "Union"):
                items = node.slice
                elts = items.elts if isinstance(items, ast.Tuple) else [items]
                out = []
                for elt in elts:
                    out += self.values_from_annotation(elt, scope, depth + 1)
                if head_name == "Optional":
                    out.append(NONE_INSTANCE)
                return dedupe_values(out)
            node = head
        out = []
        for value in self.resolve_all(node, scope, line + 1, depth + 1):
            if isinstance(value, ClassValue):
                out.append(InstanceValue(value.scope))
            elif isinstance(value, RuntimeValue) and inspect.isclass(value.obj):
                out.append(RuntimeInstanceValue(value.obj))
        return dedupe_values(out)

    def resolve_all(self, node, scope, line, depth=0):
        if node is None or depth > MAX_DEPTH:
            return []
        try:
            values = self._resolve_all(node, scope, line, depth)
        except Exception:
            return []
        return dedupe_values(values)

    def _resolve_all(self, node, scope, line, depth):
        for cls, py_type in _LITERAL_TYPES.items():
            if isinstance(node, cls):
                return [RuntimeInstanceValue(py_type)]
        if isinstance(node, ast.Constant):
            return [RuntimeInstanceValue(type(node.value))]
        if isinstance(node, ast.Name):
            return self.infer_name(node.id, scope, line, depth)
        if isinstance(node, ast.Attribute):
            out = []
            for base in self.resolve_all(node.value, scope, line, depth + 1):
                out += self.attribute_values(base, node.attr, depth)
            return out
        if isinstance(node, ast.Call):
            out = []
            for func in self.resolve_all(node.func, scope, line, depth + 1):
                out += self.call_values(func, node, scope, line, depth)
            return out
        if isinstance(node, ast.IfExp):
            out = self.resolve_all(node.body, scope, line, depth + 1)
            out += self.resolve_all(node.orelse, scope, line, depth + 1)
            return out
        if isinstance(node, ast.Await):
            return self.resolve_all(node.value, scope, line, depth + 1)
        if isinstance(node, ast.Lambda):
            return [FunctionValue(node, self.scope_of_node(node))]
        if isinstance(node, ast.Compare):
            return [RuntimeInstanceValue(bool)]
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.Or):
                out = []
                for value in node.values:
                    out += self.resolve_all(value, scope, line, depth + 1)
                return out
            return self.resolve_all(node.values[-1], scope, line, depth + 1)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return [RuntimeInstanceValue(bool)]
            return self.resolve_all(node.operand, scope, line, depth + 1)
        if isinstance(node, ast.NamedExpr):
            return self.resolve_all(node.value, scope, line, depth + 1)
        if isinstance(node, ast.BinOp):
            left = self.resolve_all(node.left, scope, line, depth + 1)
            right = self.resolve_all(node.right, scope, line, depth + 1)
            if len(left) == 1 and len(right) == 1:
                if value_key(left[0]) == value_key(right[0]):
                    return left
            if left and isinstance(left[0], RuntimeInstanceValue):
                if left[0].cls in (str, list, tuple, set, dict):
                    return [left[0]]
            return []
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return []
        return []

    def infer_name(self, name, scope, line, depth=0):
        """Values of a bare name, honouring any narrowing in force."""
        narrowed = self._narrowed_values(name, scope, depth)
        if narrowed is not None:
            return narrowed
        return self._name_values(name, scope, line, depth)

    def _name_values(self, name, scope, line, depth):
        out = []
        for binding in self.name_bindings(name, line, 0, scope):
            out += binding.get_values(self, depth)
        if out:
            return out
        if hasattr(builtins, name):
            return [RuntimeValue(getattr(builtins, name))]
        return []

    def scope_of_node(self, node):
        found = []

        def walk(scope):
            if scope.node is node:
                found.append(scope)
                return True
            for child in scope.children:
                if walk(child):
                    return True
            return False

        walk(self.module_scope)
        return found[0] if found else None

    # -- calls -------------------------------------------------------------

    def call_values(self, func, node=None, scope=None, line=1, depth=0):
        if isinstance(func, ClassValue):
            return [InstanceValue(func.scope)]
        if isinstance(func, FunctionValue):
            return self.function_return_values(func, depth)
        if isinstance(func, RuntimeValue):
            obj = func.obj
            if inspect.isclass(obj):
                return [RuntimeInstanceValue(obj)]
            return runtime_return_values(obj)
        return []

    def function_return_values(self, func, depth=0):
        node = func.node
        fscope = func.scope
        if isinstance(node, ast.Lambda):
            if fscope is None:
                return []
            owner = fscope.analyzer or self
            return owner.resolve_all(
                node.body, fscope, getattr(node, "lineno", 1), depth + 1
            )
        owner = (fscope.analyzer if fscope is not None and fscope.analyzer else self)
        key = id(node)
        if key in owner._call_stack or depth > MAX_DEPTH:
            return []
        owner._call_stack.add(key)
        try:
            if _has_yield(node):
                return [RuntimeInstanceValue(types.GeneratorType)]
            out = []
            saw_return = False
            for stmt in _iter_returns(node):
                saw_return = True
                if stmt.value is None:
                    out.append(NONE_INSTANCE)
                    continue
                target = fscope if fscope is not None else owner.module_scope
                out += owner.resolve_all(
                    stmt.value, target, getattr(stmt, "lineno", 1), depth + 1
                )
            if not out:
                annotation = getattr(node, "returns", None)
                if annotation is not None and not saw_return:
                    scope = fscope.parent if fscope is not None else owner.module_scope
                    out = owner.values_from_annotation(
                        annotation, scope or owner.module_scope, depth + 1
                    )
                if not out:
                    out = [NONE_INSTANCE]
            return dedupe_values(out)
        finally:
            owner._call_stack.discard(key)

    # -- flow-sensitive narrowing -----------------------------------------

    def set_narrow_context(self, line, col, scope):
        self._narrow = None if line is None else (line, col, scope)

    def _narrowed_values(self, name, scope, depth):
        if self._narrow is None:
            return None
        line, col, target = self._narrow
        if target is not None and scope is not target:
            return None
        conditions = self._conditions_at(line, col)
        if not conditions:
            return None
        current = None
        for test, positive in conditions:
            current = self._apply_condition(
                name, test, positive, current, scope, line, depth
            )
        return current

    def _conditions_at(self, line, col):
        """(test, positive) for every `if` branch enclosing the cursor."""
        cached = self._condition_cache.get((line, col))
        if cached is not None:
            return cached
        out = []

        def visit(nodes):
            for node in nodes:
                if isinstance(node, ast.If):
                    branch = self._if_branch(node, line, col)
                    if branch == "body":
                        out.append((node.test, True))
                        visit(node.body)
                        continue
                    if branch == "orelse":
                        out.append((node.test, False))
                        visit(node.orelse)
                        continue
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.stmt) and _node_contains(child, line, col):
                        visit([child])

        visit(getattr(self.tree, "body", []))
        self._condition_cache[(line, col)] = out
        return out

    def _if_branch(self, node, line, col):
        """Whether the cursor sits in the `if` body, its `else`, or neither."""
        body = _body_span(node.body)
        if body is None:
            return None
        orelse = _body_span(node.orelse)
        if body[0] <= line <= body[1]:
            return "body"
        if orelse is not None:
            if orelse[0] <= line <= orelse[1]:
                return "orelse"
            if body[1] < line < orelse[0]:
                return "body" if self._extends_block(line, col, node.body[0]) else None
            if line > orelse[1]:
                return (
                    "orelse" if self._extends_block(line, col, node.orelse[0]) else None
                )
            return None
        if line > body[1] and self._extends_block(line, col, node.body[0]):
            return "body"
        return None

    def _extends_block(self, line, col, first):
        """True for a cursor on a blank line still indented inside a block."""
        if line in self.statement_lines:
            return False
        indent = getattr(first, "col_offset", 0) or 0
        if indent <= 0:
            return False
        return self._effective_indent(line, col) >= indent

    def _apply_condition(self, name, test, positive, current, scope, line, depth):
        for sub, flag in _flatten_test(test, positive):
            current = self._apply_atom(name, sub, flag, current, scope, line, depth)
        return current

    def _apply_atom(self, name, test, positive, current, scope, line, depth):
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "isinstance"
            and len(test.args) == 2
            and isinstance(test.args[0], ast.Name)
            and test.args[0].id == name
        ):
            classes = []
            targets = test.args[1]
            elts = targets.elts if isinstance(targets, ast.Tuple) else [targets]
            for elt in elts:
                classes += self.values_from_annotation(elt, scope, depth + 1)
            classes = dedupe_values(classes)
            if not classes:
                return current
            if positive:
                return classes
            base = current if current is not None else self._name_values(
                name, scope, line, depth
            )
            drop = {value_key(c) for c in classes}
            kept = [v for v in base if value_key(v) not in drop]
            return kept
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left, op, right = test.left, test.ops[0], test.comparators[0]
            if (
                isinstance(left, ast.Name)
                and left.id == name
                and isinstance(right, ast.Constant)
                and right.value is None
                and isinstance(op, (ast.Is, ast.IsNot))
            ):
                is_none = isinstance(op, ast.Is) == bool(positive)
                if is_none:
                    return [NONE_INSTANCE]
                base = current if current is not None else self._name_values(
                    name, scope, line, depth
                )
                none_key = value_key(NONE_INSTANCE)
                return [v for v in base if value_key(v) != none_key]
        return current

    def attribute_bindings(self, base, attr):
        """Bindings that define `base.attr`, nearest definition first."""
        if isinstance(base, StaticModuleValue):
            binding = base.analyzer.module_scope_binding(attr)
            return [binding] if binding is not None else []
        if isinstance(base, (ClassValue, InstanceValue)):
            owner = base.scope.analyzer or self
            is_instance = isinstance(base, InstanceValue)
            for _owner, binding in owner._class_bindings(base.scope, is_instance):
                if binding.name == attr:
                    return [binding]
        return []

    def attribute_values(self, base, attr, depth=0):
        """Possible values of `base.attr`."""
        if isinstance(base, (RuntimeValue, RuntimeInstanceValue)):
            owner = base.obj if isinstance(base, RuntimeValue) else base.cls
            try:
                if hasattr(owner, attr):
                    return [RuntimeValue(getattr(owner, attr))]
            except Exception:
                return []
            if inspect.ismodule(owner):
                sub = self.project.runtime_module(
                    join_module(getattr(owner, "__name__", ""), attr)
                )
                if sub is not None:
                    return [RuntimeValue(sub)]
            return []
        if isinstance(base, StaticModuleValue):
            binding = base.analyzer.module_scope_binding(attr)
            if binding is not None:
                return binding.get_values(base.analyzer, depth)
            sub = self.project.resolve(join_module(base.name, attr))
            return [sub] if sub is not None else []
        if isinstance(base, (ClassValue, InstanceValue)):
            is_instance = isinstance(base, InstanceValue)
            owner = base.scope.analyzer or self
            out = []
            for _owner, binding in owner._class_bindings(base.scope, is_instance):
                if binding.name == attr:
                    out += binding.get_values(owner, depth)
            return out
        return []

    # -- class attribute collection ---------------------------------------

    def _class_mro(self, scope, seen=None):
        if seen is None:
            seen = set()
        if id(scope) in seen:
            return []
        seen.add(id(scope))
        order = [scope]
        for base in getattr(scope.node, "bases", []) or []:
            line = getattr(scope.node, "lineno", 1) + 1
            for value in self.resolve_all(base, scope.parent, line):
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
                        node=attr_node,
                        value_node=value if len(targets) == 1 else None,
                        scope=init_scope or class_scope,
                        target_scope=class_scope,
                        special="attribute",
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

    def attributes_of_values(self, values):
        """Union of the attributes of every possible value."""
        entries = []
        seen = set()
        for value in values:
            for entry in self.attributes_of(value):
                if entry[0] in seen:
                    continue
                seen.add(entry[0])
                entries.append(entry)
        return entries

    def attributes_of(self, value):
        if isinstance(value, RuntimeValue):
            obj = value.obj
            if inspect.ismodule(obj):
                return self._with_submodules(
                    module_public_entries(obj), getattr(obj, "__name__", "")
                )
            return runtime_all_entries(obj)
        if isinstance(value, RuntimeInstanceValue):
            return runtime_all_entries(value.cls)
        if isinstance(value, StaticModuleValue):
            return self._with_submodules(
                value.analyzer.public_module_entries(), value.name
            )
        if isinstance(value, ClassValue):
            return self.class_entries(value.scope, False)
        if isinstance(value, InstanceValue):
            return self.class_entries(value.scope, True)
        return []

    def _with_submodules(self, entries, dotted):
        """Append the submodules of a package to its own attributes."""
        if not dotted:
            return entries
        out = list(entries)
        seen = {entry[0] for entry in out}
        for entry in self.project.submodule_entries(dotted):
            if entry[0] in seen or entry[0].startswith("_"):
                continue
            seen.add(entry[0])
            out.append(entry)
        return out

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
# Definitions -- the payload of `goto` and `infer`
# ---------------------------------------------------------------------------


def _name_column(text, name, start=0):
    """Column of the identifier `name` in `text`, searching from `start`."""
    if not name:
        return start
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
    match = re.search(pattern, text[start:])
    if match is None:
        return start
    return start + match.start()


def _source_line(lines, lineno):
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1]
    return ""


def _unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _params_of(node):
    args = getattr(node, "args", None)
    if args is None:
        return "..."
    return _unparse(args)


def _docstring_of(node):
    try:
        text = ast.get_docstring(node)
    except Exception:
        text = None
    return text or ""


def _runtime_name(obj):
    name = getattr(obj, "__name__", None)
    if not isinstance(name, str) or not name:
        name = type(obj).__name__
    if name == "NoneType":
        name = "None"
    return name


def _runtime_full_name(obj, name):
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None) or name
    if inspect.ismodule(obj):
        return getattr(obj, "__name__", name)
    if not isinstance(module, str) or not module:
        module = "builtins"
    if name == "None":
        return "builtins.None"
    return module + "." + qualname


def _runtime_source(obj):
    """(path, line, column) of a real object, or None."""
    try:
        path = inspect.getsourcefile(obj)
    except Exception:
        path = None
    if not path or not os.path.isfile(path):
        return None
    try:
        source_lines, lineno = inspect.findsource(obj)
    except Exception:
        return None
    if lineno is None:
        return None
    if inspect.ismodule(obj):
        return (path, 0, 0)
    text = source_lines[lineno] if 0 <= lineno < len(source_lines) else ""
    name = getattr(obj, "__name__", "") or ""
    return (path, lineno + 1, _name_column(text, name))


def _runtime_signature(obj, name):
    try:
        rendered = str(inspect.signature(obj))
    except Exception:
        return "def %s(...)" % name
    return "def %s(%s)" % (name, rendered[1:-1].strip())


class Definer:
    """Builds the JSON definition records for `goto` and `infer`."""

    def __init__(self, project):
        self.project = project
        self.root = project.root

    # -- paths and qualified names ----------------------------------------

    def module_path(self, path):
        """Project-relative, forward-slashed path of a source file."""
        if not path:
            return ""
        relative = self.project.relative_path(path)
        if relative is None:
            return posix_path(os.path.abspath(path))
        return relative

    def module_name(self, path):
        return self.project.module_name(path)

    def qualified(self, scope, name):
        parts = []
        current = scope
        while current is not None and current.kind != "module":
            if current.kind in ("function", "class"):
                node_name = getattr(current.node, "name", None)
                if isinstance(node_name, str):
                    parts.append(node_name)
            current = current.parent
        parts.reverse()
        analyzer = scope.analyzer if scope is not None else None
        module = analyzer.module_name if analyzer is not None else ""
        if module:
            parts.insert(0, module)
        parts.append(name)
        return ".".join(p for p in parts if p)

    # -- record construction ----------------------------------------------

    @staticmethod
    def record(name, dtype, full_name, module_path, line, column, description, docstring):
        return {
            "name": name,
            "type": dtype,
            "full_name": full_name,
            "module_path": module_path,
            "line": line,
            "column": column,
            "description": description,
            "docstring": docstring,
        }

    # -- definitions for a binding (goto) ---------------------------------

    def from_binding(self, binding, analyzer):
        scope = binding.scope
        owner = (scope.analyzer if scope is not None and scope.analyzer else analyzer)
        lines = owner.lines if owner is not None else []
        path = owner.path if owner is not None else ""
        name = binding.name
        line = binding.lineno
        text = _source_line(lines, line)
        node = binding.node
        dtype = "statement"
        description = "statement"
        docstring = ""
        column = 0

        if binding.btype == "function" and node is not None:
            dtype = "function"
            description = "def %s(%s)" % (name, _params_of(node))
            docstring = _docstring_of(node)
            column = _name_column(text, name, getattr(node, "col_offset", 0) or 0)
        elif binding.btype == "class" and node is not None:
            dtype = "class"
            description = "class %s" % name
            docstring = _docstring_of(node)
            column = _name_column(text, name, getattr(node, "col_offset", 0) or 0)
        elif binding.btype == "param":
            dtype = "param"
            description = describe("param", name)
            column = getattr(node, "col_offset", 0) or 0
        elif binding.btype == "import":
            dtype, _desc = binding.completion(owner)
            if dtype not in ("module", "class", "function", "instance", "statement"):
                dtype = "module"
            description = text.strip() or "statement"
            column = self._import_column(binding, text)
        else:
            description = self._assignment_description(binding, text)
            column = self._target_column(binding, text)

        scope_for_name = binding.target_scope if binding.special == "attribute" else scope
        full_name = self.qualified(scope_for_name or scope, name)
        return self.record(
            name,
            dtype,
            full_name,
            self.module_path(path),
            line,
            column,
            description,
            docstring,
        )

    @staticmethod
    def _import_column(binding, text):
        node = binding.node
        if node is not None:
            asname = getattr(node, "asname", None)
            end = getattr(node, "end_col_offset", None)
            start = getattr(node, "col_offset", None)
            if asname and end is not None:
                return end - len(asname)
            if start is not None and not asname:
                return start
        return _name_column(text, binding.name)

    @staticmethod
    def _target_column(binding, text):
        node = binding.node
        if isinstance(node, ast.Attribute):
            end = getattr(node, "end_col_offset", None)
            if end is not None:
                return end - len(binding.name)
        if node is not None:
            column = getattr(node, "col_offset", None)
            if column is not None:
                return column
        return _name_column(text, binding.name)

    @staticmethod
    def _assignment_description(binding, text):
        if binding.value_node is not None:
            rendered = _unparse(binding.value_node)
            if rendered:
                return rendered
        if binding.annotation is not None:
            rendered = _unparse(binding.annotation)
            if rendered:
                return rendered
        stripped = text.strip()
        return stripped or "statement"

    # -- definitions for a value (infer) ----------------------------------

    def from_value(self, value, analyzer):
        if isinstance(value, (ClassValue, InstanceValue)):
            scope = value.scope
            if scope is None:
                return None
            instance = isinstance(value, InstanceValue)
            owner = scope.analyzer or analyzer
            node = scope.node
            name = getattr(node, "name", "")
            line = getattr(node, "lineno", 0) or 0
            text = _source_line(owner.lines if owner else [], line)
            column = _name_column(text, name, getattr(node, "col_offset", 0) or 0)
            dtype = "instance" if instance else "class"
            description = (
                "instance of %s" % name if instance else "class %s" % name
            )
            return self.record(
                name,
                dtype,
                self.qualified(scope.parent, name),
                self.module_path(owner.path if owner else ""),
                line,
                column,
                description,
                _docstring_of(node),
            )
        if isinstance(value, FunctionValue):
            node = value.node
            scope = value.scope
            owner = (scope.analyzer if scope is not None and scope.analyzer else analyzer)
            name = getattr(node, "name", "<lambda>")
            line = getattr(node, "lineno", 0) or 0
            text = _source_line(owner.lines if owner else [], line)
            column = _name_column(text, name, getattr(node, "col_offset", 0) or 0)
            parent = scope.parent if scope is not None else None
            return self.record(
                name,
                "function",
                self.qualified(parent if parent is not None else scope, name),
                self.module_path(owner.path if owner else ""),
                line,
                column,
                "def %s(%s)" % (name, _params_of(node)),
                _docstring_of(node),
            )
        if isinstance(value, StaticModuleValue):
            owner = value.analyzer
            full_name = value.name or owner.module_name
            name = full_name.split(".")[-1] if full_name else ""
            return self.record(
                name,
                "module",
                full_name,
                self.module_path(owner.path),
                0,
                0,
                describe("module", name),
                _docstring_of(owner.tree),
            )
        if isinstance(value, RuntimeInstanceValue):
            return self.from_runtime(value.cls, as_instance=True)
        if isinstance(value, RuntimeValue):
            return self.from_runtime(value.obj)
        return None

    def from_runtime(self, obj, as_instance=False):
        if as_instance:
            name = _runtime_name(obj)
            dtype = "instance"
            description = describe("instance", name, name)
        else:
            dtype = obj_kind(obj)
            if dtype == "instance":
                # A real value: report the class it is an instance of.
                return self.from_runtime(type(obj), as_instance=True)
            name = _runtime_name(obj)
            if dtype == "module":
                description = describe("module", name)
            elif dtype == "class":
                description = describe("class", name)
            else:
                description = _runtime_signature(obj, name)
        full_name = _runtime_full_name(obj, name)
        module_path, line, column = self._runtime_location(obj)
        docstring = ""
        if module_path:
            try:
                docstring = inspect.getdoc(obj) or ""
            except Exception:
                docstring = ""
        return self.record(
            name, dtype, full_name, module_path, line, column, description, docstring
        )

    def _runtime_location(self, obj):
        located = _runtime_source(obj)
        if located is None:
            return ("", 0, 0)
        path, line, column = located
        return (self.module_path(path), line, column)


def sort_definitions(definitions):
    out = []
    seen = set()
    for item in definitions:
        if item is None:
            continue
        key = (
            item["module_path"],
            item["line"],
            item["column"],
            item["name"],
            item["type"],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    out.sort(key=lambda d: (d["module_path"], d["line"], d["column"]))
    return out


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
# Import statement context
# ---------------------------------------------------------------------------


def _line_state(text, depth, quote):
    """Bracket depth and open string after scanning one physical line."""
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
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        index += 1
    if quote is not None and len(quote) == 1:
        quote = None  # a single-quoted string cannot span lines
    return depth, quote


def logical_line(before):
    """The logical line the cursor sits on, as a single spaced-out string."""
    lines = before.split("\n")
    depth = 0
    quote = None
    continued = False
    start = len(lines) - 1
    for index, text in enumerate(lines[:-1]):
        if depth == 0 and quote is None and not continued:
            start = index
        depth, quote = _line_state(text, depth, quote)
        continued = quote is None and text.rstrip().endswith("\\")
    if depth == 0 and quote is None and not continued:
        start = len(lines) - 1
    parts = [part.strip() for part in lines[start:-1]]
    parts.append(lines[-1].lstrip())  # trailing space matters to the cursor
    return " ".join(parts)


_FROM_IMPORT_RE = re.compile(r"^from\s+(\.*)\s*([\w.]*)\s+import\s+(.*)$", re.DOTALL)
_FROM_RE = re.compile(r"^from\s+(\.*)\s*([\w.]*)$", re.DOTALL)
_IMPORT_RE = re.compile(r"^import\s+(.*)$", re.DOTALL)
_DOTTED_RE = re.compile(r"^[\w.]*$")

NO_IMPORTS = ("nothing", "", 0)


def _dotted_base(text):
    """`a.b.` and `a.b.c` both complete names living inside `a.b`."""
    return text.rsplit(".", 1)[0] if "." in text else ""


def import_context(before):
    """(kind, module, level) when the cursor sits inside an import statement."""
    logical = logical_line(before).lstrip()
    if not logical.startswith(("from ", "from\t", "import ", "import\t")):
        return None

    match = _FROM_IMPORT_RE.match(logical)
    if match is not None:
        level = len(match.group(1))
        module = match.group(2)
        segment = re.split(r"[(),]", match.group(3))[-1].strip()
        if segment and not segment.isidentifier():
            return NO_IMPORTS  # an alias, or `*`
        if not module and not level:
            return NO_IMPORTS
        return ("names", module, level)

    match = _FROM_RE.match(logical)
    if match is not None:
        level = len(match.group(1))
        return ("module", _dotted_base(match.group(2)), level)

    match = _IMPORT_RE.match(logical)
    if match is not None:
        segment = match.group(1).rsplit(",", 1)[-1].strip()
        if not _DOTTED_RE.match(segment):
            return NO_IMPORTS  # an alias
        return ("module", _dotted_base(segment), 0)
    return None


def import_entries(analyzer, context):
    """Completion entries offered inside an import statement."""
    kind, module, level = context
    if kind == "nothing":
        return []
    if kind == "module":
        if not module and not level:
            return analyzer.project.top_level_entries()
        dotted = analyzer.absolute_module(module, level)
        if dotted is None:
            return []
        return analyzer.project.submodule_entries(dotted)
    dotted = analyzer.absolute_module(module, level)
    if dotted is None:
        return []
    return analyzer.project.import_entries(dotted)


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


def load_source(path, line, col):
    """Validate the cursor and return (source, lines, offset)."""
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
    return source, lines, offset


def complete(path, line, col, fuzzy, project=None):
    source, lines, offset = load_source(path, line, col)
    root = project_root(path, project)
    try:
        completions = analyse(path, lines, source[:offset], line, col, fuzzy, root)
    except BaseException:
        # Completion is best effort: never fail because of a weird source file.
        completions = []

    sys.stdout.write(json.dumps({"completions": completions}, separators=(",", ":")) + "\n")
    return 0


def analyse(path, lines, before, line, col, fuzzy, root=None):
    kind, prefix, receiver = analyze_context(before)
    tree = tolerant_parse(lines, line)
    project = Project(root or os.path.dirname(os.path.abspath(path)))
    analyzer = Analyzer(tree, path, lines, project)
    project.adopt(analyzer)

    context = import_context(before)
    if context is not None:
        return build_completions(import_entries(analyzer, context), prefix, fuzzy)

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
                analyzer.set_narrow_context(line, col, scope)
                values = analyzer.resolve_all(node, scope, line)
                analyzer.set_narrow_context(None, None, None)
                entries = analyzer.attributes_of_values(values)
        return build_completions(entries, prefix, fuzzy)

    completions = build_completions(analyzer.name_entries(line, col), prefix, fuzzy)
    keywords = [(kw, "keyword", kw) for kw in keyword.kwlist]
    completions.extend(build_completions(keywords, prefix, fuzzy))
    completions.sort(key=sort_key)
    return completions


# ---------------------------------------------------------------------------
# goto / infer
# ---------------------------------------------------------------------------

_LITERAL_KEYWORDS = {"None": type(None), "True": bool, "False": bool}


_CURSOR_TOKENS = {
    getattr(tokenize, name)
    for name in (
        "NAME",
        "NUMBER",
        "STRING",
        "FSTRING_START",
        "FSTRING_MIDDLE",
        "FSTRING_END",
    )
    if hasattr(tokenize, name)
}


def _token_contains(tok, line, col):
    (srow, scol), (erow, ecol) = tok.start, tok.end
    if line < srow or line > erow:
        return False
    if line == srow and col < scol:
        return False
    if line == erow and col > ecol:
        return False
    return True


def _string_type(text):
    try:
        value = ast.literal_eval(text)
    except Exception:
        return str
    return type(value)


class Target:
    """What the cursor sits on."""

    __slots__ = ("kind", "name", "cls", "offset")

    def __init__(self, kind, name=None, cls=None, offset=0):
        self.kind = kind  # "name" | "literal"
        self.name = name
        self.cls = cls
        self.offset = offset


def _target_from_word(word, start_offset):
    if not word:
        return None
    if word[0].isdigit():
        try:
            return Target("literal", cls=type(ast.literal_eval(word)))
        except Exception:
            return Target("literal", cls=int)
    if word in _LITERAL_KEYWORDS:
        return Target("literal", cls=_LITERAL_KEYWORDS[word])
    if keyword.iskeyword(word):
        return None
    return Target("name", name=word, offset=start_offset)


def cursor_target(source, lines, line, col, offset):
    """Identify the name or literal under the cursor, or None."""
    tokens = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            tokens.append(tok)
            if tok.start[0] > line + 1:
                break
    except Exception:
        pass

    best = None
    best_rank = -1
    for tok in tokens:
        if tok.type not in _CURSOR_TOKENS or not _token_contains(tok, line, col):
            continue
        strictly = not (
            (tok.start[0] == line and tok.start[1] == col)
            or (tok.end[0] == line and tok.end[1] == col)
        )
        if strictly:
            rank = 3
        elif tok.end[0] == line and tok.end[1] == col:
            rank = 2
        else:
            rank = 1
        if rank > best_rank:
            best, best_rank = tok, rank

    if best is not None:
        if best.type == tokenize.NAME:
            word = best.string
            start = offset - (col - best.start[1]) if best.start[0] == line else offset
            return _target_from_word(word, start)
        if best.type == tokenize.NUMBER:
            try:
                return Target("literal", cls=type(ast.literal_eval(best.string)))
            except Exception:
                return Target("literal", cls=int)
        if best.type == getattr(tokenize, "STRING", None):
            return Target("literal", cls=_string_type(best.string))
        return Target("literal", cls=str)

    text = lines[line - 1] if 1 <= line <= len(lines) else ""
    start = col
    while start > 0 and is_ident_char(text[start - 1]):
        start -= 1
    end = col
    while end < len(text) and is_ident_char(text[end]):
        end += 1
    if start == end:
        return None
    return _target_from_word(text[start:end], offset - (col - start))


def project_root(path, project=None):
    """The directory imports are resolved against."""
    if project:
        return os.path.abspath(project)
    return os.path.dirname(os.path.abspath(path))


def _module_definitions(definer, project, dotted):
    """The definition record of a project module, or []."""
    value = project.resolve(dotted)
    if isinstance(value, StaticModuleValue):
        record = definer.from_value(value, value.analyzer)
        return [record] if record is not None else []
    return []


def follow_import(binding, analyzer, definer, seen=None):
    """Definitions at the end of an import chain, or [] to fall back."""
    imp = binding.imp
    if not imp:
        return []
    owner = analyzer
    if binding.scope is not None and binding.scope.analyzer is not None:
        owner = binding.scope.analyzer
    if seen is None:
        seen = set()
    key = (id(owner), binding.name, binding.lineno)
    if key in seen or len(seen) > MAX_DEPTH:
        return []  # circular import chain
    seen.add(key)

    if imp[0] == "module":
        return _module_definitions(definer, owner.project, imp[1])

    module, level, attr = imp[1], imp[2], imp[3]
    dotted = owner.absolute_module(module, level)
    if dotted is None:
        return []
    target = owner.project.static_module(dotted)
    if target is None:
        # Not a project module (stdlib, third-party or missing).
        return []
    next_binding = target.module_scope_binding(attr)
    if next_binding is None:
        return _module_definitions(definer, owner.project, join_module(dotted, attr))
    if next_binding.btype == "import":
        followed = follow_import(next_binding, target, definer, seen)
        if followed:
            return followed
    return [definer.from_binding(next_binding, target)]


_FROM_MODULE_RE = re.compile(r"from\s+([.\w]*)")


def _module_component(text, span_start, dotted, col):
    """(module, level) for the dotted component the cursor sits on."""
    level = 0
    while level < len(dotted) and dotted[level] == ".":
        level += 1
    rest = dotted[level:]
    base = span_start + level
    if col < span_start or col > span_start + len(dotted):
        return None
    if not rest:
        return ("", level)
    parts = rest.split(".")
    offset = base
    taken = []
    for part in parts:
        taken.append(part)
        if col <= offset + len(part):
            return (".".join(taken), level)
        offset += len(part) + 1
    return (rest, level)


def _import_module_at(analyzer, line, col):
    """(module, level, column) when the cursor is on an import's module name."""
    text = _source_line(analyzer.lines, line)
    for node in ast.walk(analyzer.tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if getattr(node, "lineno", 0) != line:
            continue
        start = getattr(node, "col_offset", 0) or 0
        if isinstance(node, ast.ImportFrom):
            match = _FROM_MODULE_RE.match(text, start)
            if match is None:
                continue
            dotted = match.group(1)
            found = _module_component(text, match.start(1), dotted, col)
            if found is not None:
                return found + (match.start(1),)
            continue
        cursor = text.find("import", start)
        cursor = start if cursor < 0 else cursor + len("import")
        for alias in node.names:
            index = text.find(alias.name, cursor)
            if index < 0:
                continue
            cursor = index + len(alias.name)
            found = _module_component(text, index, alias.name, col)
            if found is not None:
                return found + (index,)
    return None


def module_part_definitions(analyzer, definer, line, col, name, follow, fallback=True):
    """Definitions for a cursor sitting on the module name of an import."""
    found = _import_module_at(analyzer, line, col)
    if found is None:
        return []
    module, level, column = found
    dotted = analyzer.absolute_module(module, level)
    if dotted is not None:
        records = _module_definitions(definer, analyzer.project, dotted)
        if records:
            return records
    if not fallback:
        return []
    text = _source_line(analyzer.lines, line)
    index = text.find(name, column)
    if index >= 0:
        column = index
    return [
        definer.record(
            name,
            "module",
            dotted or module or name,
            definer.module_path(analyzer.path),
            line,
            column,
            text.strip() or "statement",
            "",
        )
    ]


def navigate(path, line, col, command, project=None, follow=False):
    source, lines, offset = load_source(path, line, col)
    target = cursor_target(source, lines, line, col, offset)
    if target is None:
        fail("error: no name at line %d column %d" % (line, col))
    definer = Definer(Project(project_root(path, project)))
    try:
        definitions = _navigate(
            source, lines, path, line, col, command, target, definer, follow
        )
    except BaseException:
        definitions = []
    sys.stdout.write(
        json.dumps({"definitions": sort_definitions(definitions)}, separators=(",", ":"))
        + "\n"
    )
    return 0


def _navigate(source, lines, path, line, col, command, target, definer, follow=False):
    if target.kind == "literal":
        if command == "infer":
            return [definer.from_runtime(target.cls, as_instance=True)]
        return []

    tree = tolerant_parse(lines, line)
    analyzer = Analyzer(tree, path, lines, definer.project)
    definer.project.adopt(analyzer)
    scope = analyzer.scope_for(line, col)
    name = target.name
    kind, _prefix, receiver = analyze_context(source[: target.offset])

    def emit(binding, owner=analyzer):
        """The definition a binding points at, following imports if asked."""
        if follow and binding.btype == "import":
            followed = follow_import(binding, owner, definer)
            if followed:
                return followed
        return [definer.from_binding(binding, owner)]

    def emit_all(bindings, owner=analyzer):
        out = []
        for binding in bindings:
            out += emit(binding, owner)
        return out

    receiver_node = None
    if kind == "attr" and receiver:
        try:
            receiver_node = ast.parse(
                receiver.replace("\\\n", " ").strip(), mode="eval"
            ).body
        except Exception:
            receiver_node = None

    analyzer.set_narrow_context(line, col, scope)
    try:
        if receiver_node is not None:
            bases = analyzer.resolve_all(receiver_node, scope, line)
            if command == "infer":
                values = []
                for base in bases:
                    values += analyzer.attribute_values(base, name)
                return [definer.from_value(v, analyzer) for v in dedupe_values(values)]
            out = []
            for base in bases:
                bindings = analyzer.attribute_bindings(base, name)
                if bindings:
                    out += emit_all(bindings)
                    continue
                for value in analyzer.attribute_values(base, name):
                    out.append(definer.from_value(value, analyzer))
            if out:
                return out
            return module_part_definitions(analyzer, definer, line, col, name, follow)

        own = analyzer.definition_binding_at(name, line, col)
        if own:
            if command == "goto":
                return [definer.from_binding(b, analyzer) for b in own]
            values = []
            for binding in own:
                values += binding.get_values(analyzer, 0)
            return [definer.from_value(v, analyzer) for v in dedupe_values(values)]

        if command == "infer":
            values = analyzer.infer_name(name, scope, line)
            out = [definer.from_value(v, analyzer) for v in dedupe_values(values)]
            if out:
                return out
            return module_part_definitions(
                analyzer, definer, line, col, name, True, fallback=False
            )

        bindings = analyzer.name_bindings(name, line, col, scope)
        if bindings:
            return emit_all(bindings)
        if hasattr(builtins, name):
            return [definer.from_runtime(getattr(builtins, name))]
        return module_part_definitions(analyzer, definer, line, col, name, follow)
    finally:
        analyzer.set_narrow_context(None, None, None)


USAGE = (
    "usage: sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]\n"
    "       sith.py infer <file> <line> <col> [--project <dir>]\n"
    "       sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]"
)

COMMANDS = ("complete", "infer", "goto")


def usage():
    fail(USAGE)


def main(argv):
    args = list(argv[1:])
    if not args:
        usage()
    command = args.pop(0)
    if command not in COMMANDS:
        fail("error: unknown command: %s" % command)
    fuzzy = False
    follow = False
    project = None
    positional = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--fuzzy" and command == "complete":
            fuzzy = True
        elif arg == "--follow-imports":
            follow = True
        elif arg == "--project":
            index += 1
            if index >= len(args):
                fail("error: --project requires a directory")
            project = args[index]
        elif arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        elif arg.startswith("-") and arg != "-":
            fail("error: unknown option: %s" % arg)
        else:
            positional.append(arg)
        index += 1
    if len(positional) != 3:
        usage()
    try:
        line = int(positional[1])
        col = int(positional[2])
    except ValueError:
        fail("error: line and column must be integers")
    if project is not None and not os.path.isdir(project):
        fail("error: no such project directory: %s" % project)
    if command == "complete":
        return complete(positional[0], line, col, fuzzy, project)
    return navigate(positional[0], line, col, command, project, follow)


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
