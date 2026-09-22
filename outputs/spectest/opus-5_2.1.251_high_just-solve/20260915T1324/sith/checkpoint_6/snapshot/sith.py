#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence engine.

Usage:
    python sith.py complete   <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer      <file> <line> <col> [--project <dir>]
    python sith.py goto       <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--project <dir>]
    python sith.py context    <file> <line> <col> [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project]
                              [--project <dir>]
    python sith.py search     <query> [--project <dir>]
    python sith.py names      <file> [--all-scopes] [--project <dir>]
    python sith.py rename     <file> <line> <col> --new-name <name> [--diff]
                              [--project <dir>]
    python sith.py inline     <file> <line> <col> [--diff] [--project <dir>]
    python sith.py extract-variable <file> <line> <col> --until <line>:<col>
                              --name <name> [--diff] [--project <dir>]
    python sith.py extract-function <file> <line> <col> --until <line>:<col>
                              --name <name> [--diff] [--project <dir>]
    python sith.py errors     <file>
    python sith.py env        list | find-virtualenvs [--path <dir>]
                              | info [<executable>]
    python sith.py project    init [<dir>] [--environment <executable>]
                              [--sys-path <p>[,<p>...]]
                              [--added-sys-path <p>[,<p>...]]

`complete` prints a compact JSON object with a "completions" array; `infer`,
`goto`, `search` and `names` print one with a "definitions" array;
`signatures` a "signatures" array, `references` a "references" array and
`context` a "context" array. `errors` prints an "errors" array and `env` an
"environments" array. The four refactorings print a
"changed_files"/"renames" object, or a plain unified diff with `--diff`.

`complete`, `infer`, `goto` and `signatures` also take `--interpreter`
with `--namespaces <file>`: static analysis keeps its priority and the live
namespaces of a REPL session answer whatever it could not resolve. Every
command takes `--setting <key>=<value>`, and reads `.sith/project.json` from
the project root.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import copy
import difflib
import importlib
import inspect
import io
import json
import keyword
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import textwrap
import tokenize
import types

MAX_DEPTH = 12
OPEN_FOR = {")": "(", "]": "[", "}": "{"}
STRING_PREFIX_CHARS = set("rbfuRBFU")


# ---------------------------------------------------------------------------
# Settings and project configuration
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "case_insensitive": True,
    "dynamic_params": True,
    "smart_sys_path": True,
    "add_bracket": False,
}

# The settings in force for this run, and the ones `--setting` spelled out.
SETTINGS = dict(DEFAULT_SETTINGS)
EXPLICIT_SETTINGS = set()

CONFIG_DIR = ".sith"
CONFIG_NAME = "project.json"


def default_config():
    """The project configuration of a project that has none."""
    return {
        "environment_path": "",
        "sys_path": [],
        "added_sys_path": [],
        "smart_sys_path": True,
    }


# The project configuration in force for this run.
CONFIG = default_config()


def config_file(root):
    """Where the project configuration of `root` lives."""
    if not root:
        return ""
    return os.path.join(os.path.abspath(root), CONFIG_DIR, CONFIG_NAME)


def read_project_config(root):
    """`<root>/.sith/project.json`, merged over the defaults."""
    config = default_config()
    path = config_file(root)
    if not path or not os.path.isfile(path):
        return config
    try:
        with open(path, "rb") as fh:
            raw = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return config
    if not isinstance(raw, dict):
        return config
    environment = raw.get("environment_path", "")
    config["environment_path"] = environment if isinstance(environment, str) else ""
    for key in ("sys_path", "added_sys_path"):
        value = raw.get(key)
        if isinstance(value, (list, tuple)):
            config[key] = [entry for entry in value if isinstance(entry, str)]
    smart = raw.get("smart_sys_path")
    if isinstance(smart, bool):
        config["smart_sys_path"] = smart
    return config


def use_project_config(root):
    """Load the project configuration; `--setting` still wins over it."""
    global CONFIG
    CONFIG = read_project_config(root)
    if "smart_sys_path" not in EXPLICIT_SETTINGS:
        SETTINGS["smart_sys_path"] = CONFIG["smart_sys_path"]
    return CONFIG


def _absolute_paths(root, paths):
    """Configured paths, resolved against the project root."""
    out = []
    for entry in paths or []:
        if not entry:
            continue
        if os.path.isabs(entry):
            out.append(os.path.abspath(entry))
        else:
            out.append(os.path.abspath(os.path.join(root or os.getcwd(), entry)))
    return out


# How far below the project root a package is still added to the search path.
PACKAGE_DEPTH = 5

# Directories a project never imports from.
UNIMPORTED_DIRS = frozenset(
    {"__pycache__", "node_modules", "site-packages", ".git", ".sith"}
)


def package_directories(root, depth=PACKAGE_DEPTH):
    """The directories below `root` that hold an `__init__.py`."""
    if not root or depth <= 0 or not os.path.isdir(root):
        return []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []
    found = []
    for entry in entries:
        if entry.startswith(".") or entry in UNIMPORTED_DIRS:
            continue
        directory = os.path.join(root, entry)
        if not os.path.isdir(directory):
            continue
        if os.path.isfile(os.path.join(directory, "__init__.py")):
            found.append(directory)
        found += package_directories(directory, depth - 1)
    return found


def smart_search_paths(root):
    """What `smart_sys_path` adds on its own: the root and its packages."""
    if not root:
        return []
    return [root] + package_directories(root)


def search_paths_for(root):
    """The directories imports are resolved against, honouring the config."""
    root = os.path.abspath(root) if root else ""
    explicit = _absolute_paths(root, CONFIG.get("sys_path"))
    if explicit:
        paths = list(explicit)
    elif SETTINGS.get("smart_sys_path", True):
        paths = smart_search_paths(root)
    else:
        paths = []
    paths += _absolute_paths(root, CONFIG.get("added_sys_path"))
    out = []
    for path in paths:
        if path not in out:
            out.append(path)
    return out


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


def decorator_names(node):
    """Bare names of the decorators applied to a `def` or `class`."""
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

# Project-wide stub packages live here, mypy style.
STUB_DIR = "stubs"

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

    def __init__(self, root: str, search_paths=None):
        self.root = os.path.abspath(root) if root else ""
        if search_paths is None:
            search_paths = search_paths_for(self.root)
        self.search_paths = [path for path in search_paths if path]
        self._static = {}
        self._loading = set()
        self._runtime = {}
        self._stubs = {}

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

    def search_relative_path(self, path):
        """`path` relative to the first search path holding it, or None."""
        if not path:
            return None
        absolute = os.path.abspath(path)
        for base in self.search_paths:
            try:
                relative = os.path.relpath(absolute, base)
            except ValueError:
                continue
            if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                continue
            if os.path.isabs(relative):
                continue
            return posix_path(relative)
        return None

    def module_name(self, path):
        """Dotted name of the module stored at `path`."""
        if not path:
            return ""
        relative = self.relative_path(path)
        if relative is None:
            relative = self.search_relative_path(path)
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
        for root in self.search_paths:
            found = self._locate_in(root, dotted)
            if found is not None:
                return found
        return None

    @staticmethod
    def _locate_in(root, dotted):
        """`locate` restricted to a single search path."""
        if not root or not os.path.isdir(root):
            return None
        parts = [part for part in dotted.split(".") if part] if dotted else []
        base = root
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
        return ("namespace", root)

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
            # A module that exists only as a type stub is still resolvable.
            stub = self.stub_module(dotted)
            self._static[dotted] = stub
            return stub
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

    # -- stub files --------------------------------------------------------

    def locate_stub(self, dotted):
        """Path of the `.pyi` stub describing `dotted`, or None.

        An inline stub sitting next to the module wins over the project-wide
        `stubs/` directory.
        """
        if not self.root or not dotted:
            return None
        parts = [part for part in dotted.split(".") if part]
        if not parts:
            return None
        located = self.locate(dotted)
        if located is not None and located[0] == "file" and located[1].endswith(".py"):
            inline = located[1][:-3] + ".pyi"
            if os.path.isfile(inline):
                return inline
        base = os.path.join(self.root, STUB_DIR, *parts)
        candidate = base + ".pyi"
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(base, "__init__.pyi")
        if os.path.isfile(candidate):
            return candidate
        return None

    def stub_module(self, dotted):
        """Analyzer for the stub of `dotted`, parsed but never executed."""
        if dotted in self._stubs:
            return self._stubs[dotted]
        self._stubs[dotted] = None  # placeholder: breaks recursion
        path = self.locate_stub(dotted)
        analyzer = None
        if path is not None:
            try:
                analyzer = self.parse(path, dotted)
            except Exception:
                analyzer = None
        self._stubs[dotted] = analyzer
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
        names = []
        seen = set()
        for root in self.search_paths:
            for name in directory_modules(root):
                if name not in seen:
                    seen.add(name)
                    names.append(name)
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
            stubbed = stub_param_values(self, depth)
            if stubbed:
                return stubbed
            return analyzer.dynamic_param_values(self, depth)
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
# Stub files -- type information taken from `.pyi` files
# ---------------------------------------------------------------------------


def scope_name_path(scope):
    """Dotted names leading from the module down to `scope`, or None."""
    parts = []
    current = scope
    while current is not None and current.kind != "module":
        if current.kind not in ("function", "class"):
            return None
        name = getattr(current.node, "name", None)
        if not isinstance(name, str):
            return None
        parts.append(name)
        current = current.parent
    parts.reverse()
    return parts


def scopes_named(analyzer, parts):
    """Every scope in `analyzer` reached by the name path `parts`."""
    if analyzer is None:
        return []
    current = [analyzer.module_scope]
    for part in parts:
        following = []
        for scope in current:
            for child in scope.children:
                if child.kind in ("function", "class"):
                    if getattr(child.node, "name", None) == part:
                        following.append(child)
        if not following:
            return []
        current = following
    return current


def stub_scopes_of(scope):
    """Scopes in the stub file that describe `scope`."""
    if scope is None:
        return []
    analyzer = scope.analyzer
    if analyzer is None or analyzer.is_stub:
        return []
    stub = analyzer.stub
    if stub is None:
        return []
    parts = scope_name_path(scope)
    if not parts:
        return []
    return scopes_named(stub, parts)


def source_scopes_of(scope):
    """Scopes of the runtime module that a stub scope describes."""
    analyzer = scope.analyzer if scope is not None else None
    if analyzer is None or not analyzer.is_stub or not analyzer.module_name:
        return []
    source = analyzer.project.static_module(analyzer.module_name)
    if source is None or source is analyzer or source.is_stub:
        return []
    parts = scope_name_path(scope)
    if not parts:
        return []
    return scopes_named(source, parts)


def stub_binding_values(binding, depth=0):
    """Values of a stub binding that carries type information."""
    if binding is None or binding.btype in ("function", "class"):
        return []
    owner = binding.scope.analyzer if binding.scope is not None else None
    if owner is None:
        return []
    return binding.get_values(owner, depth)


def stub_function_scopes(func):
    """Stub scopes describing the function value `func`."""
    scope = func.scope
    node = func.node
    if scope is None or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    if scope.node is not node:
        return []
    return [s for s in stub_scopes_of(scope) if s.kind == "function"]


def stub_return_values(func, depth=0):
    """Return types a stub declares for `func`."""
    out = []
    for scope in stub_function_scopes(func):
        annotation = getattr(scope.node, "returns", None)
        if annotation is None:
            continue
        owner = scope.analyzer
        if owner is None:
            continue
        out += owner.values_from_annotation(
            annotation, scope.parent or owner.module_scope, depth + 1
        )
    return dedupe_values(out)


def arg_named(node, name):
    """The `ast.arg` called `name` in a function definition, or None."""
    args = getattr(node, "args", None)
    if args is None:
        return None
    candidates = list(getattr(args, "posonlyargs", []) or []) + list(args.args or [])
    candidates += list(args.kwonlyargs or [])
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            candidates.append(extra)
    for arg in candidates:
        if arg.arg == name:
            return arg
    return None


def stub_param_values(binding, depth=0):
    """Type of a parameter as declared by the module's stub."""
    scope = binding.scope
    if scope is None or scope.kind != "function":
        return []
    out = []
    for stub_scope in stub_scopes_of(scope):
        arg = arg_named(stub_scope.node, binding.name)
        annotation = getattr(arg, "annotation", None) if arg is not None else None
        if annotation is None:
            continue
        owner = stub_scope.analyzer
        if owner is None:
            continue
        out += owner.values_from_annotation(annotation, stub_scope, depth + 1)
    return dedupe_values(out)


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
        self.is_stub = bool(path) and str(path).endswith(".pyi")
        self._stub = False  # sentinel: not looked up yet
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
        return decorator_names(node)

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

    # -- stubs -------------------------------------------------------------

    @property
    def stub(self):
        """Analyzer of the `.pyi` stub describing this module, or None."""
        if self._stub is False:
            self._stub = None
            if not self.is_stub and self.module_name:
                candidate = self.project.stub_module(self.module_name)
                if candidate is not None and candidate is not self:
                    other = candidate.path or ""
                    mine = self.path or ""
                    if not other or not mine or (
                        os.path.abspath(other) != os.path.abspath(mine)
                    ):
                        self._stub = candidate
        return self._stub

    def stub_module_binding(self, name):
        """Module-level binding of `name` in this module's stub, or None."""
        stub = self.stub
        if stub is None:
            return None
        for binding in reversed(stub.module_scope.bindings):
            if binding.name == name:
                return binding
        return None

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
            stubbed = stub_binding_values(base.analyzer.stub_module_binding(attr))
            if stubbed:
                return stubbed[0]
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
        if found is None:
            # A name that only the stub knows about still has a definition.
            return self.stub_module_binding(name)
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
        stub = self.stub
        owners = ([stub] if stub is not None else []) + [self]
        for owner in owners:
            for binding in reversed(owner.module_scope.bindings):
                if binding.name.startswith("_") or binding.name in seen:
                    continue
                seen.add(binding.name)
                ctype, desc = binding.completion(owner)
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
        stubbed = stub_return_values(func, depth)
        if stubbed:
            return stubbed
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

    # -- dynamic parameter inference --------------------------------------

    def call_sites(self, node, name):
        """(call, scope, bound) for every call of `name` in this file."""
        out = []
        for call in ast.walk(self.tree):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if isinstance(func, ast.Name) and func.id == name:
                bound = False
            elif isinstance(func, ast.Attribute) and func.attr == name:
                bound = True
            else:
                continue
            line = getattr(call, "lineno", 1) or 1
            col = getattr(func, "col_offset", 0) or 0
            scope = self.scope_for(line, col)
            try:
                values = self.resolve_all(func, scope, line, MAX_DEPTH - 3)
            except Exception:
                values = []
            functions = [v for v in values if isinstance(v, FunctionValue)]
            if functions and not any(v.node is node for v in functions):
                continue
            out.append((call, scope, bound))
        return out

    def dynamic_param_values(self, binding, depth=0):
        """Parameter types guessed from the call sites in the same file.

        Only this file is searched: a call in another module says nothing
        about what the editor is looking at right now.
        """
        if not SETTINGS.get("dynamic_params", True):
            return []
        scope = binding.scope
        if scope is None or scope.kind != "function" or depth > MAX_DEPTH - 4:
            return []
        node = scope.node
        name = getattr(node, "name", None)
        args = getattr(node, "args", None)
        if not isinstance(name, str) or args is None:
            return []
        owner = scope.analyzer or self
        positional = [
            arg.arg
            for arg in list(getattr(args, "posonlyargs", []) or []) + list(args.args or [])
        ]
        keyword_only = [arg.arg for arg in (args.kwonlyargs or [])]
        if binding.name not in positional and binding.name not in keyword_only:
            return []
        method = scope.parent is not None and scope.parent.kind == "class"
        static = "staticmethod" in decorator_names(node)
        out = []
        for call, call_scope, bound in owner.call_sites(node, name):
            line = getattr(call, "lineno", 1) or 1
            shift = 1 if (method and not static and bound) else 0
            if binding.name in positional:
                index = positional.index(binding.name) - shift
                if 0 <= index < len(call.args):
                    argument = call.args[index]
                    if not isinstance(argument, ast.Starred):
                        out += owner.resolve_all(argument, call_scope, line, depth + 1)
            for keyword_node in call.keywords or []:
                if keyword_node.arg == binding.name:
                    out += owner.resolve_all(
                        keyword_node.value, call_scope, line, depth + 1
                    )
        return dedupe_values(out)

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
            # The runtime source is preferred for navigation, the stub last.
            related = (
                source_scopes_of(base.scope)
                + [base.scope]
                + stub_scopes_of(base.scope)
            )
            for scope in related:
                sowner = scope.analyzer or owner
                for _owner, binding in sowner._class_bindings(scope, is_instance):
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
            stubbed = stub_binding_values(
                base.analyzer.stub_module_binding(attr), depth
            )
            if stubbed:
                return stubbed
            binding = base.analyzer.module_scope_binding(attr)
            if binding is not None:
                return binding.get_values(base.analyzer, depth)
            sub = self.project.resolve(join_module(base.name, attr))
            return [sub] if sub is not None else []
        if isinstance(base, (ClassValue, InstanceValue)):
            is_instance = isinstance(base, InstanceValue)
            owner = base.scope.analyzer or self
            for sscope in stub_scopes_of(base.scope):
                sowner = sscope.analyzer or owner
                for _owner, binding in sowner._class_bindings(sscope, is_instance):
                    if binding.name == attr:
                        values = binding.get_values(sowner, depth)
                        if values:
                            return values
            out = []
            for _owner, binding in owner._class_bindings(base.scope, is_instance):
                if binding.name == attr:
                    out += binding.get_values(owner, depth)
            if out:
                return out
            for scope in source_scopes_of(base.scope):
                sowner = scope.analyzer or owner
                for _owner, binding in sowner._class_bindings(scope, is_instance):
                    if binding.name == attr:
                        values = binding.get_values(sowner, depth)
                        if values:
                            return values
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
        pairs = []
        related = (
            stub_scopes_of(class_scope)
            + [class_scope]
            + source_scopes_of(class_scope)
        )
        for scope in related:
            owner = scope.analyzer or self
            pairs += [
                (owner, binding)
                for _owner, binding in owner._class_bindings(scope, is_instance)
            ]
        for owner, binding in pairs:
            if binding.name in seen:
                continue
            seen.add(binding.name)
            ctype, desc = binding.completion(owner)
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
    if SETTINGS.get("case_insensitive", True):
        lname = name.lower()
        lprefix = prefix.lower()
    else:
        lname = name
        lprefix = prefix
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
        text = name[cut:]
        if SETTINGS.get("add_bracket") and ctype in ("function", "class"):
            text += "("
        out.append(
            {
                "name": name,
                "complete": text,
                "type": ctype,
                "description": desc,
            }
        )
    out.sort(key=sort_key)
    return out


# ---------------------------------------------------------------------------
# Interpreter mode -- live namespaces used as a fallback
# ---------------------------------------------------------------------------

# Namespace types a call can sensibly be made on.
CALLABLE_NS_TYPES = frozenset(
    {
        "function",
        "builtin_function_or_method",
        "method",
        "method-wrapper",
        "classmethod",
        "staticmethod",
        "lambda",
        "class",
        "type",
    }
)


def ns_type(descriptor):
    """The Python type name a namespace entry claims to have."""
    value = (descriptor or {}).get("type")
    return value if isinstance(value, str) and value else "instance"


def ns_description(descriptor):
    """Runtime values describe themselves as `<type> (runtime)`."""
    return "%s (runtime)" % ns_type(descriptor)


def _namespace_descriptor(value):
    """Normalise one namespace entry into a plain descriptor."""
    if isinstance(value, dict):
        descriptor = {}
        for key in ("type", "value", "module", "name"):
            item = value.get(key)
            if isinstance(item, str):
                descriptor[key] = item
            elif item is not None and key == "value":
                descriptor[key] = str(item)
        attributes = value.get("attributes")
        if isinstance(attributes, (list, tuple)):
            descriptor["attributes"] = [
                item for item in attributes if isinstance(item, str)
            ]
        return descriptor
    if isinstance(value, str):
        return {"type": value}
    return {}


class Namespaces:
    """The namespaces of a live interpreter session, searched in order."""

    def __init__(self, maps=()):
        self.maps = [dict(mapping) for mapping in maps]

    def __bool__(self):
        return any(self.maps)

    def lookup(self, name):
        """The descriptor of `name` in the first namespace holding it."""
        if not isinstance(name, str):
            return None
        for mapping in self.maps:
            if name in mapping:
                return mapping[name]
        return None

    def items(self):
        """Every (name, descriptor) pair; the first namespace wins."""
        out = []
        seen = set()
        for mapping in self.maps:
            for name in mapping:
                if name in seen:
                    continue
                seen.add(name)
                out.append((name, mapping[name]))
        return out

    def entries(self):
        """Completion entries for every name a namespace knows."""
        return [
            (name, ns_type(descriptor), ns_description(descriptor))
            for name, descriptor in self.items()
        ]

    def attributes(self, name):
        """The known attributes of a runtime value."""
        descriptor = self.lookup(name)
        if descriptor is None:
            return []
        return list(descriptor.get("attributes") or [])


def load_namespaces(path):
    """Read the `--namespaces` file: a JSON array of namespace objects."""
    if not os.path.exists(path):
        fail("error: no such namespaces file: %s" % path)
    if not os.path.isfile(path):
        fail("error: not a regular file: %s" % path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        fail("error: cannot read %s: %s" % (path, exc))
    try:
        data = json.loads(raw)
    except ValueError as exc:
        fail("error: %s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, list):
        fail("error: %s must hold a JSON array of namespaces" % path)
    maps = []
    for item in data:
        if not isinstance(item, dict):
            fail("error: every namespace in %s must be a JSON object" % path)
        maps.append(
            {
                key: _namespace_descriptor(value)
                for key, value in item.items()
                if isinstance(key, str)
            }
        )
    return Namespaces(maps)


def namespace_full_name(name, descriptor):
    """The dotted name a runtime value is known by."""
    original = descriptor.get("name") or name
    module = descriptor.get("module") or ""
    if not module:
        return original
    if ns_type(descriptor) == "module":
        return module
    return module + "." + original


def namespace_definition(name, descriptor, full_name=None):
    """The `goto`/`infer` record describing a runtime value."""
    return {
        "name": name,
        "type": ns_type(descriptor),
        "full_name": (
            full_name if full_name is not None
            else namespace_full_name(name, descriptor)
        ),
        "module_path": "",
        "line": 0,
        "column": 0,
        "description": ns_description(descriptor),
        "docstring": descriptor.get("value") or "",
    }


def _receiver_name(receiver):
    """The plain name a receiver expression is, or None."""
    if not receiver:
        return None
    text = receiver.replace("\\\n", " ").strip()
    try:
        node = ast.parse(text, mode="eval").body
    except Exception:
        return None
    if isinstance(node, ast.Name):
        return node.id
    return None


def namespace_attribute_entries(namespaces, receiver):
    """Completion entries for the attributes of a runtime value."""
    name = _receiver_name(receiver)
    if name is None:
        return []
    attributes = namespaces.attributes(name)
    descriptor = {"type": "instance"}
    return [
        (attribute, ns_type(descriptor), ns_description(descriptor))
        for attribute in attributes
    ]


def namespace_definitions(namespaces, source, target):
    """The runtime fallback for `goto` and `infer`."""
    if not namespaces or target is None or target.kind != "name":
        return []
    _kind, _prefix, receiver = analyze_context(source[: target.offset])
    if _kind == "attr":
        owner = _receiver_name(receiver)
        if owner is None:
            return []
        descriptor = namespaces.lookup(owner)
        if descriptor is None or target.name not in (
            descriptor.get("attributes") or []
        ):
            return []
        full_name = namespace_full_name(owner, descriptor) + "." + target.name
        return [namespace_definition(target.name, {"type": "instance"}, full_name)]
    descriptor = namespaces.lookup(target.name)
    if descriptor is None:
        return []
    return [namespace_definition(target.name, descriptor)]


def namespace_signatures(namespaces, source, offset):
    """The runtime fallback for `signatures`."""
    if not namespaces:
        return []
    call = enclosing_call(source, offset)
    if call is None:
        return []
    opener, receiver = call
    name = _receiver_name(receiver)
    if name is None:
        return []
    descriptor = namespaces.lookup(name)
    if descriptor is None or ns_type(descriptor) not in CALLABLE_NS_TYPES:
        return []
    return [
        {
            "name": name,
            "params": [],
            "index": None,
            "description": ns_description(descriptor),
            "docstring": descriptor.get("value") or "",
        }
    ]


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


def complete(path, line, col, fuzzy, project=None, namespaces=None):
    source, lines, offset = load_source(path, line, col)
    root = project_root(path, project)
    try:
        completions = analyse(
            path, lines, source[:offset], line, col, fuzzy, root, namespaces
        )
    except BaseException:
        # Completion is best effort: never fail because of a weird source file.
        completions = []

    sys.stdout.write(json.dumps({"completions": completions}, separators=(",", ":")) + "\n")
    return 0


def analyse(path, lines, before, line, col, fuzzy, root=None, namespaces=None):
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
        if not entries and namespaces:
            # Static analysis knows nothing about this receiver: ask the
            # interpreter what it is holding.
            entries = namespace_attribute_entries(namespaces, receiver)
        return build_completions(entries, prefix, fuzzy)

    completions = build_completions(analyzer.name_entries(line, col), prefix, fuzzy)
    keywords = [(kw, "keyword", kw) for kw in keyword.kwlist]
    completions.extend(build_completions(keywords, prefix, fuzzy))
    if namespaces:
        taken = {item["name"] for item in completions}
        for item in build_completions(namespaces.entries(), prefix, fuzzy):
            if item["name"] in taken:
                continue
            taken.add(item["name"])
            completions.append(item)
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


def navigate(path, line, col, command, project=None, follow=False, namespaces=None):
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
    if not definitions and namespaces:
        # Nothing static to point at: fall back on the live namespaces.
        definitions = namespace_definitions(namespaces, source, target)
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


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


class ParamSpec:
    """One rendered parameter of a callable."""

    __slots__ = ("text", "name", "kind")

    def __init__(self, text, name, kind):
        self.text = text
        self.name = name
        self.kind = kind  # positional | vararg | keyword | kwarg


def _render_param(arg, default=None, prefix=""):
    text = prefix + arg.arg
    annotation = getattr(arg, "annotation", None)
    if annotation is not None:
        rendered = _unparse(annotation)
        if rendered:
            text += ": " + rendered
    if default is not None:
        rendered = _unparse(default)
        text += "=" + (rendered if rendered else "...")
    return text


def node_params(node, skip_self=False):
    """Rendered parameters of a `def` or `lambda`, in declaration order."""
    args = getattr(node, "args", None)
    if args is None:
        return []
    positional = list(getattr(args, "posonlyargs", []) or []) + list(args.args or [])
    defaults = list(args.defaults or [])
    first_default = len(positional) - len(defaults)
    out = []
    start = 1 if (skip_self and positional) else 0
    for index, arg in enumerate(positional):
        if index < start:
            continue
        default = defaults[index - first_default] if index >= first_default else None
        out.append(ParamSpec(_render_param(arg, default), arg.arg, "positional"))
    if args.vararg is not None:
        out.append(
            ParamSpec(
                _render_param(args.vararg, None, "*"), args.vararg.arg, "vararg"
            )
        )
    kw_defaults = list(args.kw_defaults or [])
    for index, arg in enumerate(args.kwonlyargs or []):
        default = kw_defaults[index] if index < len(kw_defaults) else None
        out.append(ParamSpec(_render_param(arg, default), arg.arg, "keyword"))
    if args.kwarg is not None:
        out.append(
            ParamSpec(_render_param(args.kwarg, None, "**"), args.kwarg.arg, "kwarg")
        )
    return out


def _runtime_annotation_text(annotation):
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, type):
        return getattr(annotation, "__name__", "") or str(annotation)
    text = str(annotation)
    if text.startswith("typing."):
        text = text[len("typing.") :]
    return text


def runtime_params(obj, skip_self=False):
    """(parameters, return annotation) of a real callable, or None."""
    try:
        signature = inspect.signature(obj)
    except Exception:
        return None
    out = []
    for param in signature.parameters.values():
        prefix = ""
        kind = "positional"
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            prefix, kind = "*", "vararg"
        elif param.kind == inspect.Parameter.VAR_KEYWORD:
            prefix, kind = "**", "kwarg"
        elif param.kind == inspect.Parameter.KEYWORD_ONLY:
            kind = "keyword"
        text = prefix + param.name
        annotation = _runtime_annotation_text(param.annotation)
        if annotation:
            text += ": " + annotation
        if param.default is not inspect.Parameter.empty:
            try:
                text += "=" + repr(param.default)
            except Exception:
                text += "=..."
        out.append(ParamSpec(text, param.name, kind))
    if skip_self and out and out[0].kind == "positional":
        if out[0].name in ("self", "cls"):
            out = out[1:]
    returns = _runtime_annotation_text(signature.return_annotation)
    if signature.return_annotation is inspect.Signature.empty:
        returns = ""
    return out, returns


def param_index(params, positional, keyword):
    """0-based index of the parameter the cursor is on, or None."""
    if keyword is not None:
        if keyword:
            for index, param in enumerate(params):
                if param.kind in ("positional", "keyword") and param.name == keyword:
                    return index
        for index, param in enumerate(params):
            if param.kind == "kwarg":
                return index
        return None
    slots = [index for index, param in enumerate(params) if param.kind == "positional"]
    if positional < len(slots):
        return slots[positional]
    for index, param in enumerate(params):
        if param.kind == "vararg":
            return index
    return None


def _is_overload(node):
    return "overload" in decorator_names(node)


def overload_scopes(scope):
    """`scope` alone, or every `@overload` sibling sharing its name."""
    parent = scope.parent
    name = getattr(scope.node, "name", None)
    if parent is None or name is None:
        return [scope]
    overloads = [
        child
        for child in parent.children
        if child.kind == "function"
        and getattr(child.node, "name", None) == name
        and _is_overload(child.node)
    ]
    return overloads or [scope]


def function_signature_scopes(func):
    """Scopes whose `def` describes the callable: stubs and overloads first."""
    scope = func.scope
    node = func.node
    if isinstance(node, ast.Lambda):
        return [scope] if scope is not None else []
    targets = stub_function_scopes(func)
    if not targets and scope is not None and scope.node is node:
        targets = [scope]
    out = []
    seen = set()
    for target in targets:
        for candidate in overload_scopes(target):
            key = id(candidate.node)
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
    return out


def class_init_scopes(class_scope, analyzer):
    """Function scopes of the `__init__` a class instantiation runs."""
    owner = class_scope.analyzer or analyzer
    for scope in owner._class_mro(class_scope):
        for source in stub_scopes_of(scope) + [scope]:
            found = [
                child
                for child in source.children
                if child.kind == "function"
                and getattr(child.node, "name", None) == "__init__"
            ]
            if found:
                out = []
                seen = set()
                for candidate in found:
                    for expanded in overload_scopes(candidate):
                        if id(expanded.node) in seen:
                            continue
                        seen.add(id(expanded.node))
                        out.append(expanded)
                return out
    return []


def dataclass_params(class_scope, analyzer):
    """Parameters of the `__init__` a `@dataclass` decorator generates."""
    if "dataclass" not in decorator_names(class_scope.node):
        return None
    owner = class_scope.analyzer or analyzer
    order = []
    found = {}
    for scope in reversed(owner._class_mro(class_scope)):
        source = (stub_scopes_of(scope) or [scope])[0]
        for stmt in getattr(source.node, "body", []) or []:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            name = stmt.target.id
            text = name
            annotation = _unparse(stmt.annotation)
            if annotation:
                if annotation.split("[")[0].split(".")[-1] == "ClassVar":
                    continue
                text += ": " + annotation
            if stmt.value is not None:
                text += "=" + (_unparse(stmt.value) or "...")
            param = ParamSpec(text, name, "positional")
            if name in found:
                order[found[name]] = param
            else:
                found[name] = len(order)
                order.append(param)
    return order


def _signature_record(name, params, description, docstring, index):
    return {
        "name": name,
        "params": [param.text for param in params],
        "index": index,
        "description": description,
        "docstring": docstring,
    }


def _is_method_scope(scope):
    if scope is None or scope.parent is None:
        return False
    if scope.parent.kind != "class":
        return False
    return "staticmethod" not in decorator_names(scope.node)


def _function_signature(scope, definer, skip_self, positional, keyword):
    node = scope.node
    name = getattr(node, "name", "<lambda>")
    params = node_params(node, skip_self=skip_self)
    description = "def %s(%s)" % (name, ", ".join(p.text for p in params))
    returns = getattr(node, "returns", None)
    if returns is not None:
        rendered = _unparse(returns)
        if rendered:
            description += " -> " + rendered
    owner = scope.analyzer
    record = _signature_record(
        name,
        params,
        description,
        _docstring_of(node),
        param_index(params, positional, keyword),
    )
    sort = (
        definer.module_path(owner.path if owner is not None else ""),
        getattr(node, "lineno", 0) or 0,
    )
    return sort, record


def value_signatures(value, analyzer, definer, on_class, positional, keyword):
    """Signature records for one possible value of the callee."""
    out = []
    if isinstance(value, FunctionValue):
        for scope in function_signature_scopes(value):
            skip_self = _is_method_scope(scope) and not on_class
            out.append(
                _function_signature(scope, definer, skip_self, positional, keyword)
            )
        return out
    if isinstance(value, ClassValue):
        class_scope = value.scope
        node = class_scope.node
        name = getattr(node, "name", "")
        owner = class_scope.analyzer or analyzer
        module_path = definer.module_path(owner.path if owner is not None else "")
        line = getattr(node, "lineno", 0) or 0
        inits = class_init_scopes(class_scope, analyzer)
        if not inits:
            params = dataclass_params(class_scope, analyzer) or []
            out.append(
                (
                    (module_path, line),
                    _signature_record(
                        name,
                        params,
                        "def %s(%s)" % (name, ", ".join(p.text for p in params)),
                        _docstring_of(node),
                        param_index(params, positional, keyword),
                    ),
                )
            )
            return out
        for scope in inits:
            params = node_params(scope.node, skip_self=True)
            docstring = _docstring_of(scope.node) or _docstring_of(node)
            out.append(
                (
                    (module_path, line),
                    _signature_record(
                        name,
                        params,
                        "def %s(%s)" % (name, ", ".join(p.text for p in params)),
                        docstring,
                        param_index(params, positional, keyword),
                    ),
                )
            )
        return out
    if isinstance(value, RuntimeValue):
        obj = value.obj
        if inspect.ismodule(obj):
            return out
        is_class = inspect.isclass(obj)
        if not is_class and not callable(obj):
            return out
        found = runtime_params(obj, skip_self=(not on_class and not is_class))
        if found is None:
            return out
        params, returns = found
        name = _runtime_name(obj)
        description = "def %s(%s)" % (name, ", ".join(p.text for p in params))
        if returns and not is_class:
            description += " -> " + returns
        try:
            docstring = inspect.getdoc(obj) or ""
        except Exception:
            docstring = ""
        module_path, line, _column = definer._runtime_location(obj)
        out.append(
            (
                (module_path, line),
                _signature_record(
                    name,
                    params,
                    description,
                    docstring,
                    param_index(params, positional, keyword),
                ),
            )
        )
    return out


def _skip_string_forward(text, index):
    """Index just past the string literal opening at `index`."""
    quote = text[index]
    if text.startswith(quote * 3, index):
        quote = quote * 3
    pos = index + len(quote)
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text.startswith(quote, pos):
            return pos + len(quote)
        if len(quote) == 1 and text[pos] == "\n":
            return pos
        pos += 1
    return len(text)


def split_arguments(text):
    """Top-level comma-separated pieces of an argument list."""
    segments = []
    start = 0
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch in "\"'":
            index = _skip_string_forward(text, index)
            continue
        if ch == "#":
            newline = text.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            segments.append(text[start:index])
            start = index + 1
        index += 1
    segments.append(text[start:])
    return segments


_KEYWORD_ARG_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=(?!=)")


def argument_position(text):
    """(positional arguments before the cursor, keyword being filled in)."""
    segments = split_arguments(text)
    current = segments[-1]
    positional = 0
    for segment in segments[:-1]:
        stripped = segment.strip()
        if not stripped:
            continue
        if _KEYWORD_ARG_RE.match(segment) or stripped.startswith("**"):
            continue
        positional += 1
    match = _KEYWORD_ARG_RE.match(current)
    if match is not None:
        return positional, match.group(1)
    if current.strip().startswith("**"):
        return positional, ""  # an unknown keyword: **kwargs, if there is one
    return positional, None


def bracket_stack(text, offset):
    """Indices of the brackets still open at `offset`, outermost first."""
    stack = []
    index = 0
    while index < offset:
        ch = text[index]
        if ch in "\"'":
            index = _skip_string_forward(text, index)
            continue
        if ch == "#":
            newline = text.find("\n", index)
            index = offset if newline < 0 else min(newline, offset)
            continue
        if ch == "\\" and index + 1 < len(text):
            index += 2
            continue
        if ch in "([{":
            stack.append(index)
        elif ch in ")]}":
            if stack:
                stack.pop()
        index += 1
    return stack


def _preceded_by(text, start, words):
    pos = skip_ws_back(text, start - 1)
    end = pos + 1
    while pos >= 0 and is_ident_char(text[pos]):
        pos -= 1
    return text[pos + 1 : end] in words


def enclosing_call(text, offset):
    """(index of the call's `(`, callee source) for the cursor, or None."""
    for opener in reversed(bracket_stack(text, offset)):
        if text[opener] != "(":
            continue
        receiver = scan_receiver(text, opener)
        if not receiver:
            continue
        start = opener - len(receiver)
        if _preceded_by(text, start, ("def", "class", "lambda")):
            continue
        return opener, receiver
    return None


def offset_position(text, index):
    """(1-based line, 0-based column) of `index` in `text`."""
    line = text.count("\n", 0, index) + 1
    start = text.rfind("\n", 0, index) + 1
    return line, index - start


def signatures(path, line, col, project=None, namespaces=None):
    source, lines, offset = load_source(path, line, col)
    root = project_root(path, project)
    try:
        found = _signatures(source, lines, path, line, col, offset, root)
    except BaseException:
        found = []
    if not found and namespaces:
        found = namespace_signatures(namespaces, source, offset)
    sys.stdout.write(
        json.dumps({"signatures": found}, separators=(",", ":")) + "\n"
    )
    return 0


def _signatures(source, lines, path, line, col, offset, root):
    call = enclosing_call(source, offset)
    if call is None:
        return []
    opener, receiver = call
    expression = receiver.replace("\\\n", " ").strip()
    try:
        node = ast.parse(expression, mode="eval").body
    except Exception:
        return []
    positional, keyword = argument_position(source[opener + 1 : offset])
    project = Project(root)
    tree = tolerant_parse(lines, line)
    analyzer = Analyzer(tree, path, lines, project)
    project.adopt(analyzer)
    definer = Definer(project)
    call_line, call_col = offset_position(source, opener)
    scope = analyzer.scope_for(call_line, call_col)
    analyzer.set_narrow_context(call_line, call_col, scope)
    try:
        values = analyzer.resolve_all(node, scope, call_line)
        on_class = False
        if isinstance(node, ast.Attribute):
            for base in analyzer.resolve_all(node.value, scope, call_line):
                if isinstance(base, ClassValue):
                    on_class = True
                elif isinstance(base, RuntimeValue) and inspect.isclass(base.obj):
                    on_class = True
                elif isinstance(base, StaticModuleValue):
                    on_class = True
                elif isinstance(base, RuntimeValue) and inspect.ismodule(base.obj):
                    on_class = True
    finally:
        analyzer.set_narrow_context(None, None, None)
    records = []
    seen = set()
    for value in dedupe_values(values):
        for sort, record in value_signatures(
            value, analyzer, definer, on_class, positional, keyword
        ):
            key = (sort, record["name"], tuple(record["params"]))
            if key in seen:
                continue
            seen.add(key)
            records.append((sort, record))
    records.sort(key=lambda item: item[0])
    return [record for _sort, record in records]


# ---------------------------------------------------------------------------
# Project files
# ---------------------------------------------------------------------------

SKIP_DIRS = frozenset(
    {"__pycache__", "node_modules", "site-packages", "venv", "env", "build", "dist"}
)


def project_files(root, suffix=".py"):
    """Every source file in the project, sorted, hidden directories aside."""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIRS and not name.startswith(".")
        )
        for filename in sorted(filenames):
            if filename.endswith(suffix):
                out.append(os.path.join(dirpath, filename))
    return out


def _analyzer_for(project, path, cache):
    key = os.path.abspath(path)
    if key in cache:
        return cache[key]
    analyzer = None
    try:
        analyzer = project.parse(path)
    except Exception:
        analyzer = None
    if analyzer is not None:
        project.adopt(analyzer)
    cache[key] = analyzer
    return analyzer


# ---------------------------------------------------------------------------
# references
# ---------------------------------------------------------------------------


def scope_uid(scope):
    """Identity of a scope inside its own file."""
    if scope is None:
        return ("?",)
    if scope.kind == "module":
        return ("module",)
    node = scope.node
    return (
        scope.kind,
        getattr(node, "lineno", 0) or 0,
        getattr(node, "col_offset", 0) or 0,
    )


def follow_import_bindings(binding, analyzer, seen=None):
    """Bindings an import binding ultimately names, in other modules."""
    imp = binding.imp
    if not imp or imp[0] == "module":
        return []
    owner = analyzer
    if binding.scope is not None and binding.scope.analyzer is not None:
        owner = binding.scope.analyzer
    if seen is None:
        seen = set()
    key = (id(owner), binding.name, binding.lineno)
    if key in seen or len(seen) > MAX_DEPTH:
        return []
    seen.add(key)
    module, level, attr = imp[1], imp[2], imp[3]
    dotted = owner.absolute_module(module, level)
    if dotted is None:
        return []
    target = owner.project.static_module(dotted)
    if target is None:
        return []
    following = target.module_scope_binding(attr)
    if following is None:
        return []
    out = [(following, target)]
    if following.btype == "import":
        out += follow_import_bindings(following, target, seen)
    return out


def binding_keys(binding, analyzer, definer, seen=None):
    """Identity of the symbol a binding belongs to."""
    if seen is None:
        seen = set()
    if id(binding) in seen or len(seen) > MAX_DEPTH:
        return set()
    seen.add(id(binding))
    keys = set()
    scope = binding.scope
    owner = scope.analyzer if scope is not None and scope.analyzer else analyzer
    path = definer.module_path(owner.path if owner is not None else "")
    keys.add((path, scope_uid(scope), binding.name))
    imp = binding.imp
    if binding.btype == "import" and imp:
        if imp[0] == "module":
            dotted = imp[1]
            if dotted:
                keys.add(("<module>", dotted))
        else:
            for following, target in follow_import_bindings(binding, analyzer):
                keys |= binding_keys(following, target, definer, seen)
    return keys


def bindings_keys(bindings, analyzer, definer):
    keys = set()
    for binding in bindings:
        keys |= binding_keys(binding, analyzer, definer)
    return keys


def cursor_bindings(analyzer, source, lines, line, col, offset, name):
    """The bindings the name under the cursor refers to."""
    scope = analyzer.scope_for(line, col)
    kind, _prefix, receiver = analyze_context(source[:offset])
    analyzer.set_narrow_context(line, col, scope)
    try:
        if kind == "attr" and receiver:
            try:
                node = ast.parse(
                    receiver.replace("\\\n", " ").strip(), mode="eval"
                ).body
            except Exception:
                node = None
            if node is not None:
                out = []
                for base in analyzer.resolve_all(node, scope, line):
                    out += analyzer.attribute_bindings(base, name)
                if out:
                    return out
            return []
        own = analyzer.definition_binding_at(name, line, col)
        if own:
            return own
        return analyzer.name_bindings(name, line, col, scope)
    finally:
        analyzer.set_narrow_context(None, None, None)


def _alias_column(alias, name, text):
    asname = getattr(alias, "asname", None)
    start = getattr(alias, "col_offset", None)
    end = getattr(alias, "end_col_offset", None)
    if asname and asname == name and end is not None:
        return end - len(asname)
    if start is not None and (not asname or asname != name):
        return _name_column(text, name, start)
    return _name_column(text, name)


def _occurrences(analyzer, name):
    """Every mention of `name` in a file, as (line, column, definition, node)."""
    out = []
    for node in ast.walk(analyzer.tree):
        if isinstance(node, ast.Name) and node.id == name:
            out.append(
                (
                    getattr(node, "lineno", 0) or 0,
                    getattr(node, "col_offset", 0) or 0,
                    isinstance(node.ctx, (ast.Store, ast.Del)),
                    node,
                )
            )
        elif isinstance(node, ast.Attribute) and node.attr == name:
            end_line = getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)
            end_col = getattr(node, "end_col_offset", None)
            if end_col is None:
                continue
            out.append(
                (
                    end_line,
                    end_col - len(name),
                    isinstance(node.ctx, (ast.Store, ast.Del)),
                    node,
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name != name:
                continue
            line = getattr(node, "lineno", 0) or 0
            text = _source_line(analyzer.lines, line)
            column = _name_column(text, name, getattr(node, "col_offset", 0) or 0)
            out.append((line, column, True, node))
        elif isinstance(node, ast.arg) and node.arg == name:
            out.append(
                (
                    getattr(node, "lineno", 0) or 0,
                    getattr(node, "col_offset", 0) or 0,
                    True,
                    node,
                )
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            line = getattr(node, "lineno", 0) or 0
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound != name and alias.name != name:
                    continue
                alias_line = getattr(alias, "lineno", None) or line
                text = _source_line(analyzer.lines, alias_line)
                out.append(
                    (
                        alias_line,
                        _alias_column(alias, name, text),
                        True,
                        (node, alias),
                    )
                )
    return out


def _occurrence_keys(analyzer, definer, name, line, column, node):
    """Symbol identity of one occurrence."""
    if isinstance(node, tuple):  # an import alias
        statement, alias = node
        for binding in analyzer.module_scope.bindings + _all_bindings(analyzer):
            if (
                binding.btype == "import"
                and binding.name == name
                and binding.lineno == getattr(statement, "lineno", 0)
            ):
                return binding_keys(binding, analyzer, definer)
        if isinstance(statement, ast.ImportFrom) and alias.name == name:
            synthetic = Binding(
                name,
                getattr(statement, "lineno", 0) or 0,
                "import",
                imp=(
                    "from",
                    statement.module or "",
                    getattr(statement, "level", 0) or 0,
                    name,
                ),
                scope=analyzer.module_scope,
            )
            return binding_keys(synthetic, analyzer, definer)
        return set()
    scope = analyzer.scope_for(line, column)
    if isinstance(node, ast.Attribute):
        analyzer.set_narrow_context(line, column, scope)
        try:
            out = []
            for base in analyzer.resolve_all(node.value, scope, line):
                out += analyzer.attribute_bindings(base, name)
        finally:
            analyzer.set_narrow_context(None, None, None)
        return bindings_keys(out, analyzer, definer)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.arg)):
        for binding in _all_bindings(analyzer):
            if binding.node is node:
                return binding_keys(binding, analyzer, definer)
        return set()
    bindings = analyzer.name_bindings(name, line, column, scope)
    return bindings_keys(bindings, analyzer, definer)


def _all_bindings(analyzer):
    out = []

    def walk(scope):
        out.extend(scope.bindings)
        for child in scope.children:
            walk(child)

    walk(analyzer.module_scope)
    return out


def references(path, line, col, scope="file", project=None):
    source, lines, offset = load_source(path, line, col)
    target = cursor_target(source, lines, line, col, offset)
    if target is None:
        fail("error: no name at line %d column %d" % (line, col))
    root = project_root(path, project)
    try:
        found = _references(
            source, lines, path, line, col, offset, target, scope, root
        )
    except BaseException:
        found = []
    sys.stdout.write(
        json.dumps({"references": found}, separators=(",", ":")) + "\n"
    )
    return 0


def _references(source, lines, path, line, col, offset, target, mode, root):
    if target.kind != "name" or not target.name:
        return []
    name = target.name
    project = Project(root)
    definer = Definer(project)
    tree = tolerant_parse(lines, line)
    analyzer = Analyzer(tree, path, lines, project)
    project.adopt(analyzer)
    cache = {os.path.abspath(path): analyzer}
    bindings = cursor_bindings(analyzer, source, lines, line, col, offset, name)
    keys = bindings_keys(bindings, analyzer, definer)

    paths = [os.path.abspath(path)]
    if mode == "project":
        for candidate in project_files(root):
            absolute = os.path.abspath(candidate)
            if absolute not in paths:
                paths.append(absolute)

    found = {}
    for file_path in paths:
        owner = _analyzer_for(project, file_path, cache)
        if owner is None:
            continue
        module_path = definer.module_path(owner.path)
        for occ_line, occ_col, is_definition, node in _occurrences(owner, name):
            if occ_line <= 0:
                continue
            if keys:
                try:
                    occ_keys = _occurrence_keys(
                        owner, definer, name, occ_line, occ_col, node
                    )
                except Exception:
                    occ_keys = set()
                if not (occ_keys & keys):
                    continue
            elif file_path != os.path.abspath(path):
                continue
            key = (module_path, occ_line, occ_col)
            record = found.get(key)
            if record is None:
                found[key] = {
                    "module_path": module_path,
                    "line": occ_line,
                    "column": occ_col,
                    "is_definition": bool(is_definition),
                }
            elif is_definition:
                record["is_definition"] = True
    out = list(found.values())
    out.sort(key=lambda item: (item["module_path"], item["line"], item["column"]))
    return out


# ---------------------------------------------------------------------------
# search / names
# ---------------------------------------------------------------------------


def _searchable_bindings(analyzer):
    """Module-level and class-level definitions, never function locals."""
    out = []

    def walk(scope):
        for binding in scope.bindings:
            if binding.btype in ("function", "class", "assign"):
                out.append(binding)
        for child in scope.children:
            if child.kind == "class":
                walk(child)

    walk(analyzer.module_scope)
    return out


def _definition_record(definer, binding, analyzer, docstring=True, definition=False):
    record = definer.from_binding(binding, analyzer)
    if not docstring:
        record.pop("docstring", None)
    if definition:
        record["is_definition"] = True
    return record


def search(query, project=None):
    root = os.path.abspath(project) if project else os.getcwd()
    try:
        found = _search(query, root)
    except BaseException:
        found = []
    sys.stdout.write(
        json.dumps({"definitions": found}, separators=(",", ":")) + "\n"
    )
    return 0


def _search(query, root):
    project = Project(root)
    definer = Definer(project)
    cache = {}
    lowered = query.lower()
    ranked = []
    seen = set()
    for file_path in project_files(root):
        analyzer = _analyzer_for(project, file_path, cache)
        if analyzer is None:
            continue
        for binding in _searchable_bindings(analyzer):
            name = binding.name
            if lowered not in name.lower():
                continue
            record = _definition_record(definer, binding, analyzer, docstring=False)
            key = (record["module_path"], record["line"], record["column"], name)
            if key in seen:
                continue
            seen.add(key)
            lower = name.lower()
            if lower == lowered:
                rank = 0
            elif lower.startswith(lowered):
                rank = 1
            else:
                rank = 2
            ranked.append(((rank, record["module_path"], record["line"], record["column"]), record))
    ranked.sort(key=lambda item: item[0])
    return [record for _key, record in ranked]


def names(path, all_scopes=False, project=None):
    read_source(path)
    root = project_root(path, project)
    try:
        found = _names(path, all_scopes, root)
    except BaseException:
        found = []
    sys.stdout.write(
        json.dumps({"definitions": found}, separators=(",", ":")) + "\n"
    )
    return 0


def _names(path, all_scopes, root):
    project = Project(root)
    definer = Definer(project)
    analyzer = project.parse(path)
    if analyzer is None:
        return []
    project.adopt(analyzer)
    bindings = _all_bindings(analyzer) if all_scopes else list(
        analyzer.module_scope.bindings
    )
    out = []
    seen = set()
    for binding in bindings:
        record = _definition_record(
            definer, binding, analyzer, docstring=True, definition=True
        )
        key = (record["line"], record["column"], record["name"], record["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    out.sort(key=lambda item: (item["line"], item["column"]))
    return out


# ---------------------------------------------------------------------------
# Refactoring -- shared machinery
# ---------------------------------------------------------------------------


def valid_identifier(name):
    """True when `name` is something Python would accept as an identifier."""
    return bool(name) and name.isidentifier() and not keyword.iskeyword(name)


def rel_path(root, path):
    """`path` relative to the project root, forward-slashed."""
    absolute = os.path.abspath(path)
    if root:
        try:
            relative = os.path.relpath(absolute, root)
        except ValueError:
            relative = None
        if (
            relative is not None
            and relative != os.pardir
            and not relative.startswith(os.pardir + os.sep)
            and not os.path.isabs(relative)
        ):
            return posix_path(relative)
    return posix_path(absolute)


class SourceEdits:
    """Text replacements over one file, applied from the end backwards."""

    def __init__(self, path, source):
        self.path = path
        self.source = source
        self.lines = source.split("\n")
        self.starts = [0]
        index = source.find("\n")
        while index >= 0:
            self.starts.append(index + 1)
            index = source.find("\n", index + 1)
        self._edits = {}

    def offset(self, line, col):
        if line < 1 or line > len(self.lines):
            return None
        return self.starts[line - 1] + col

    def line_start(self, line):
        return self.offset(line, 0)

    def line_end(self, line):
        """Offset just past the newline that ends `line`."""
        if line >= len(self.lines):
            return len(self.source)
        return self.starts[line]

    def replace(self, start, end, text):
        self._edits.setdefault((start, end), text)

    def replace_word(self, line, col, old, new):
        """Replace `old` sitting at (line, col); False when it is not there."""
        start = self.offset(line, col)
        if start is None or self.source[start : start + len(old)] != old:
            return False
        self.replace(start, start + len(old), new)
        return True

    def dirty(self):
        return bool(self._edits)

    def result(self):
        out = self.source
        limit = None
        for (start, end), text in sorted(self._edits.items(), reverse=True):
            if limit is not None and end > limit:
                continue  # overlaps an edit already applied: keep the first
            out = out[:start] + text + out[end:]
            limit = start
        return out


def _mapped_path(relative, renames):
    """Where a file ends up once the rename map is applied."""
    if relative in renames:
        return renames[relative]
    for old, new in renames.items():
        if relative.startswith(old + "/"):
            return new + relative[len(old) :]
    return relative


def refactor_output(root, changes, renames, diff):
    """Print the edited files as JSON, or as a unified diff."""
    records = []
    for path in sorted(changes, key=lambda item: rel_path(root, item)):
        old, new = changes[path]
        if old == new:
            continue
        relative = rel_path(root, path)
        records.append((relative, _mapped_path(relative, renames), old, new))
    if diff:
        chunks = []
        for relative, moved, old, new in records:
            for piece in difflib.unified_diff(
                old.splitlines(True),
                new.splitlines(True),
                "a/" + relative,
                "b/" + moved,
            ):
                if not piece.endswith("\n"):
                    piece += "\n"
                chunks.append(piece)
        sys.stdout.write("".join(chunks))
        return 0
    payload = {
        "changed_files": {moved: new for _rel, moved, _old, new in records},
        "renames": renames,
    }
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0


def refactor_paths(root, path):
    """The file under the cursor first, then every other project file."""
    paths = [os.path.abspath(path)]
    for candidate in project_files(root):
        absolute = os.path.abspath(candidate)
        if absolute not in paths:
            paths.append(absolute)
    return paths


def refactor_analyzer(project, path, cache):
    """Analyzer over the exact bytes on disk -- no syntax-error repair."""
    key = os.path.abspath(path)
    if key in cache:
        return cache[key]
    analyzer = None
    try:
        with open(key, "rb") as fh:
            source = normalize(fh.read().decode("utf-8"))
        if source.startswith("\ufeff"):
            source = source[1:]
        analyzer = Analyzer(
            ast.parse(source),
            key,
            source.split("\n"),
            project,
            project.module_name(key),
        )
    except Exception:
        analyzer = None
    if analyzer is not None:
        project.adopt(analyzer)
    cache[key] = analyzer
    return analyzer


def analyzer_source(analyzer):
    return "\n".join(analyzer.lines)


def matching_occurrences(analyzer, definer, name, keys):
    """Mentions of `name` in one file that belong to the symbol `keys`."""
    out = []
    for occ_line, occ_col, _definition, node in _occurrences(analyzer, name):
        if occ_line <= 0:
            continue
        if keys:
            try:
                occ_keys = _occurrence_keys(
                    analyzer, definer, name, occ_line, occ_col, node
                )
            except Exception:
                occ_keys = set()
            if not (occ_keys & keys):
                continue
        out.append((occ_line, occ_col, node))
    out.sort(key=lambda item: (item[0], item[1]))
    return out


def _node_span(node):
    return (
        getattr(node, "lineno", 0) or 0,
        getattr(node, "col_offset", 0) or 0,
        getattr(node, "end_lineno", 0) or 0,
        getattr(node, "end_col_offset", 0) or 0,
    )


def _covers(outer, inner):
    """True when `outer`'s source span contains `inner`'s."""
    out = _node_span(outer)
    within = _node_span(inner)
    return out[:2] <= within[:2] and within[2:] <= out[2:]


def enclosing_statement(tree, node):
    """The innermost statement whose source span holds `node`."""
    best = None
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.stmt) or not _covers(candidate, node):
            continue
        if best is None or _covers(best, candidate):
            best = candidate
    return best


def node_offsets(starts, lines, node):
    """(start, end) absolute offsets of a node, or None."""
    line, col, end_line, end_col = _node_span(node)
    if not line or not end_line:
        return None
    if line > len(lines) or end_line > len(lines):
        return None
    return (starts[line - 1] + col, starts[end_line - 1] + end_col)


def position_offset(lines, line, col, clamp=False):
    """Offset of a (line, col) position, failing when it is out of range.

    `--until` is clamped instead: an editor happily reports a column past the
    end of a line and that still means "to the end of the line".
    """
    if line < 1:
        fail("error: line %d out of range (file has %d lines)" % (line, len(lines)))
    if line > len(lines):
        if not clamp:
            fail(
                "error: line %d out of range (file has %d lines)"
                % (line, len(lines))
            )
        line = len(lines)
    if col < 0 or col > len(lines[line - 1]):
        if not clamp:
            fail("error: column %d out of range for line %d" % (col, line))
        col = min(max(col, 0), len(lines[line - 1]))
    offset = 0
    for existing in lines[: line - 1]:
        offset += len(existing) + 1
    return offset + col, line, col


def parse_strict(source, path):
    """Parse a file that a refactoring is about to rewrite."""
    try:
        return ast.parse(source, path)
    except SyntaxError as exc:
        fail("error: %s has a syntax error: %s" % (path, exc.msg))


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def _occurrence_scope(analyzer, line, col, node):
    """The scope a mention lives in -- never the scope it opens itself."""
    scope = analyzer.scope_for(line, col)
    while scope is not None and scope.node is node:
        scope = scope.parent
    return scope


def check_rename_collision(name, new_name, bindings, occurrences):
    """Exit 1 when `new_name` is already taken where the rename lands."""
    owned = {id(binding) for binding in bindings}
    scopes = [binding.scope for binding in bindings if binding.scope is not None]
    for analyzer, found in occurrences:
        for occ_line, occ_col, node in found:
            if isinstance(node, ast.Attribute):
                continue  # attributes never clash with plain names
            scope = _occurrence_scope(analyzer, occ_line, occ_col, node)
            if scope is not None:
                scopes.append(scope)
    for scope in scopes:
        for binding in scope.bindings:
            if binding.name == new_name and id(binding) not in owned:
                fail(
                    "error: cannot rename %s to %s: %s is already defined in "
                    "this scope" % (name, new_name, new_name)
                )


def module_at_cursor(analyzer, line, col, name):
    """Absolute dotted name of the project module under the cursor, or None."""
    project = analyzer.project
    found = _import_module_at(analyzer, line, col)
    if found is not None:
        module, level, _column = found
        dotted = analyzer.absolute_module(module, level)
        if dotted and dotted.split(".")[-1] == name and project.locate(dotted):
            return dotted
    try:
        bindings = list(analyzer.definition_binding_at(name, line, col) or [])
        if not bindings:
            scope = analyzer.scope_for(line, col)
            bindings = analyzer.name_bindings(name, line, col, scope)
    except Exception:
        bindings = []
    for binding in bindings:
        imp = binding.imp
        if binding.btype != "import" or not imp:
            continue
        if imp[0] == "module":
            dotted = imp[1]
        elif imp[0] == "from":
            base = analyzer.absolute_module(imp[1], imp[2])
            dotted = join_module(base, imp[3]) if base is not None else None
        else:
            dotted = None
        if not dotted or dotted.split(".")[-1] != name:
            continue
        if project.locate(dotted):
            return dotted
    return None


def _component_offset(dotted, index):
    """Offset of component `index` inside a dotted name."""
    offset = 0
    for position, part in enumerate(dotted.split(".")):
        if position == index:
            return offset
        offset += len(part) + 1
    return None


def _attribute_chain(node):
    """The dotted names of a pure `a.b.c` chain, or None."""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return parts


def _binding_module(analyzer, binding):
    """Absolute module an import binding names, or None."""
    imp = binding.imp
    if binding.btype != "import" or not imp:
        return None
    if imp[0] == "module":
        return imp[1]
    if imp[0] == "from":
        base = analyzer.absolute_module(imp[1], imp[2])
        return join_module(base, imp[3]) if base is not None else None
    return None


def module_attribute_edits(analyzer, edits, dotted, new_name):
    """Rewrite `pkg.old` attribute chains that reach the renamed module."""
    old_part = dotted.split(".")[-1]
    for node in ast.walk(analyzer.tree):
        if not isinstance(node, ast.Attribute) or node.attr != old_part:
            continue
        chain = _attribute_chain(node)
        if chain is None or len(chain) < 2:
            continue
        line = getattr(node, "lineno", 0) or 0
        col = getattr(node, "col_offset", 0) or 0
        try:
            bindings = analyzer.name_bindings(
                chain[0], line, col, analyzer.scope_for(line, col)
            )
        except Exception:
            bindings = []
        for binding in bindings:
            base = _binding_module(analyzer, binding)
            if base is None:
                continue
            if join_module(base, ".".join(chain[1:])) != dotted:
                continue
            end_line = getattr(node, "end_lineno", 0) or line
            end_col = getattr(node, "end_col_offset", None)
            if end_col is None:
                break
            edits.replace_word(
                end_line, end_col - len(old_part), old_part, new_name
            )
            break


def module_import_edits(analyzer, definer, edits, dotted, new_name, index):
    """Rewrite every import of `dotted` in one file, and its uses."""
    parts = dotted.split(".")
    old_part = parts[index]
    rebound = []

    def rewrite(line, col, text, local):
        start = edits.offset(line, col)
        if start is None or edits.source[start : start + len(text)] != text:
            return False
        shift = _component_offset(text, local)
        if shift is None:
            return False
        at = start + shift
        if edits.source[at : at + len(old_part)] != old_part:
            return False
        edits.replace(at, at + len(old_part), new_name)
        return True

    for node in ast.walk(analyzer.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name or ""
                if target != dotted and not target.startswith(dotted + "."):
                    continue
                if not rewrite(alias.lineno, alias.col_offset, target, index):
                    continue
                if not alias.asname and index == 0:
                    rebound.append((alias, target.split(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            level = getattr(node, "level", 0) or 0
            absolute = analyzer.absolute_module(node.module or "", level)
            if absolute is None:
                continue
            text = _source_line(analyzer.lines, node.lineno)
            if absolute == dotted or absolute.startswith(dotted + "."):
                match = _FROM_MODULE_RE.match(text, getattr(node, "col_offset", 0) or 0)
                if match is not None:
                    written = match.group(1)
                    lead = 0
                    while lead < len(written) and written[lead] == ".":
                        lead += 1
                    rest = written[lead:]
                    local = index - (len(absolute.split(".")) - len(rest.split(".")))
                    if rest and 0 <= local:
                        rewrite(node.lineno, match.start(1) + lead, rest, local)
            for alias in node.names:
                if alias.name == "*":
                    continue
                full = join_module(absolute, alias.name)
                if full != dotted and not full.startswith(dotted + "."):
                    continue
                pieces = alias.name.split(".")
                local = index - (len(full.split(".")) - len(pieces))
                if not 0 <= local < len(pieces):
                    continue
                if not rewrite(alias.lineno, alias.col_offset, alias.name, local):
                    continue
                if not alias.asname and local == 0:
                    rebound.append((alias, pieces[0]))

    for alias, old_bound in rebound:
        binding = None
        for candidate in _all_bindings(analyzer):
            if candidate.btype == "import" and candidate.node is alias:
                binding = candidate
                break
        if binding is None:
            continue
        keys = binding_keys(binding, analyzer, definer)
        if not keys:
            continue
        for occ_line, occ_col, _node in matching_occurrences(
            analyzer, definer, old_bound, keys
        ):
            edits.replace_word(occ_line, occ_col, old_bound, new_name)


def rename_module(root, project, definer, cache, path, dotted, name, new_name, diff):
    """Rename a module or package, and every import that mentions it."""
    located = project.locate(dotted)
    if located is None:
        fail("error: cannot locate the module %s" % dotted)
    kind, target = located
    parts = dotted.split(".")
    if project.locate(".".join(parts[:-1] + [new_name])) is not None:
        fail(
            "error: cannot rename %s to %s: a module named %s already exists"
            % (name, new_name, new_name)
        )
    if kind == "namespace":
        old_fs, suffix = target, ""
    elif os.path.basename(target) == "__init__.py":
        old_fs, suffix = os.path.dirname(target), ""
    else:
        old_fs, suffix = target, ".py"
    new_fs = os.path.join(os.path.dirname(old_fs), new_name + suffix)
    if os.path.exists(new_fs):
        fail(
            "error: cannot rename %s to %s: %s already exists"
            % (name, new_name, rel_path(root, new_fs))
        )
    renames = {rel_path(root, old_fs): rel_path(root, new_fs)}
    changes = {}
    for file_path in refactor_paths(root, path):
        owner = refactor_analyzer(project, file_path, cache)
        if owner is None:
            continue
        source = analyzer_source(owner)
        edits = SourceEdits(owner.path, source)
        try:
            module_import_edits(
                owner, definer, edits, dotted, new_name, len(parts) - 1
            )
            module_attribute_edits(owner, edits, dotted, new_name)
        except Exception:
            continue
        if edits.dirty():
            changes[os.path.abspath(owner.path)] = (source, edits.result())
    return refactor_output(root, changes, renames, diff)


def rename(path, line, col, new_name, diff=False, project=None):
    if not valid_identifier(new_name):
        fail("error: %s is not a valid Python identifier" % new_name)
    source, lines, offset = load_source(path, line, col)
    target = cursor_target(source, lines, line, col, offset)
    if target is None or target.kind != "name" or not target.name:
        fail("error: no name at line %d column %d" % (line, col))
    name = target.name
    root = project_root(path, project)
    if name == new_name:
        return refactor_output(root, {}, {}, diff)
    owner_project = Project(root)
    definer = Definer(owner_project)
    cache = {}
    analyzer = refactor_analyzer(owner_project, path, cache)
    if analyzer is None:
        fail("error: cannot parse %s" % path)

    dotted = module_at_cursor(analyzer, line, col, name)
    if dotted is not None:
        return rename_module(
            root, owner_project, definer, cache, path, dotted, name, new_name, diff
        )

    bindings = cursor_bindings(analyzer, source, lines, line, col, offset, name)
    keys = bindings_keys(bindings, analyzer, definer)
    occurrences = []
    for file_path in refactor_paths(root, path):
        if not keys and file_path != os.path.abspath(path):
            continue
        owner = refactor_analyzer(owner_project, file_path, cache)
        if owner is None:
            continue
        found = matching_occurrences(owner, definer, name, keys)
        if found:
            occurrences.append((owner, found))
    if not occurrences:
        fail("error: nothing to rename at line %d column %d" % (line, col))
    check_rename_collision(name, new_name, bindings, occurrences)
    changes = {}
    for owner, found in occurrences:
        owner_source = analyzer_source(owner)
        edits = SourceEdits(owner.path, owner_source)
        for occ_line, occ_col, _node in found:
            edits.replace_word(occ_line, occ_col, name, new_name)
        changes[os.path.abspath(owner.path)] = (owner_source, edits.result())
    return refactor_output(root, changes, {}, diff)


# ---------------------------------------------------------------------------
# inline
# ---------------------------------------------------------------------------


def _substituted(statement, node, value_node):
    """A copy of `statement` with the mention at `node` replaced."""
    where = (node.lineno, node.col_offset, node.id)

    class Swap(ast.NodeTransformer):
        def visit_Name(self, current):
            if (current.lineno, current.col_offset, current.id) == where:
                return copy.deepcopy(value_node)
            return current

    return Swap().visit(copy.deepcopy(statement))


def _statement_dump(text):
    """Structure of one statement, parsed in a context that allows anything."""
    wrapped = "async def _sith_():\n" + textwrap.indent(text, "    ")
    try:
        tree = ast.parse(wrapped)
    except SyntaxError:
        return None
    body = tree.body[0].body
    if len(body) != 1:
        return None
    return ast.dump(body[0])


def needs_parentheses(analyzer, source, starts, node, value_node, value_text):
    """True when the inlined text changes meaning unless it is bracketed."""
    statement = enclosing_statement(analyzer.tree, node)
    if statement is None:
        return True
    span = node_offsets(starts, analyzer.lines, statement)
    here = node_offsets(starts, analyzer.lines, node)
    if span is None or here is None or here[0] < span[0] or here[1] > span[1]:
        return True
    segment = source[span[0] : span[1]]
    relative = here[0] - span[0]
    if segment[relative : relative + len(node.id)] != node.id:
        return True
    candidate = (
        segment[:relative] + value_text + segment[relative + len(node.id) :]
    )
    try:
        expected = ast.dump(_substituted(statement, node, value_node))
    except Exception:
        return True
    return _statement_dump(candidate) != expected


def _inline_definition(analyzer, bindings, name):
    """The assignment an inline rewrites, or exit 1 explaining why not."""
    for binding in bindings:
        if binding.btype in ("function", "class"):
            fail("error: cannot inline a function/class definition")
    chosen = None
    for binding in bindings:
        if binding.btype == "assign" and binding.value_node is not None:
            chosen = binding
    if chosen is None:
        fail("error: cannot inline %s: it is not a simple assignment" % name)
    statement = None
    for node in ast.walk(analyzer.tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if getattr(node, "value", None) is chosen.value_node:
            statement = node
            break
    if statement is None:
        fail("error: cannot inline %s: it is not a simple assignment" % name)
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    else:
        targets = [statement.target]
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        fail("error: cannot inline %s: it is not a simple assignment" % name)
    if targets[0].id != name:
        fail("error: cannot inline %s: it is not a simple assignment" % name)
    return chosen, statement


def inline(path, line, col, diff=False, project=None):
    source, lines, offset = load_source(path, line, col)
    target = cursor_target(source, lines, line, col, offset)
    if target is None or target.kind != "name" or not target.name:
        fail("error: no name at line %d column %d" % (line, col))
    name = target.name
    root = project_root(path, project)
    owner_project = Project(root)
    definer = Definer(owner_project)
    cache = {}
    analyzer = refactor_analyzer(owner_project, path, cache)
    if analyzer is None:
        fail("error: cannot parse %s" % path)
    bindings = cursor_bindings(analyzer, source, lines, line, col, offset, name)
    if not bindings:
        fail("error: cannot inline %s: it is not a simple assignment" % name)
    binding, statement = _inline_definition(analyzer, bindings, name)
    value_text = ast.get_source_segment(source, statement.value)
    if value_text is None:
        fail("error: cannot inline %s: its value is not readable" % name)
    value_text = value_text.strip()

    keys = bindings_keys(bindings, analyzer, definer)
    files = {os.path.abspath(path): (analyzer, [])}
    for file_path in refactor_paths(root, path):
        if not keys and file_path != os.path.abspath(path):
            continue
        owner = refactor_analyzer(owner_project, file_path, cache)
        if owner is None:
            continue
        found = [
            item
            for item in matching_occurrences(owner, definer, name, keys)
            if isinstance(item[2], ast.Name) and isinstance(item[2].ctx, ast.Load)
        ]
        if found:
            files.setdefault(os.path.abspath(owner.path), (owner, []))[1].extend(found)
    if not any(found for _owner, found in files.values()):
        fail("error: name has no references to inline")

    changes = {}
    for file_path, (owner, found) in files.items():
        owner_source = analyzer_source(owner)
        edits = SourceEdits(owner.path, owner_source)
        for occ_line, occ_col, node in found:
            text = value_text
            if needs_parentheses(
                owner, owner_source, edits.starts, node, statement.value, value_text
            ):
                text = "(" + value_text + ")"
            edits.replace_word(occ_line, occ_col, name, text)
        if file_path == os.path.abspath(path):
            start = edits.line_start(statement.lineno)
            end = edits.line_end(getattr(statement, "end_lineno", statement.lineno))
            edits.replace(start, end, "")
        changes[file_path] = (owner_source, edits.result())
    return refactor_output(root, changes, {}, diff)


# ---------------------------------------------------------------------------
# extract-variable
# ---------------------------------------------------------------------------


def _trim_span(source, start, end):
    if end < start:
        start, end = end, start
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return start, end


def extract_variable(
    path, line, col, until_line, until_col, new_name, diff=False, project=None
):
    if not valid_identifier(new_name):
        fail("error: %s is not a valid Python identifier" % new_name)
    source, lines, offset = load_source(path, line, col)
    end_offset, _line, _col = position_offset(lines, until_line, until_col, True)
    root = project_root(path, project)
    tree = parse_strict(source, path)
    edits = SourceEdits(path, source)
    start, end = _trim_span(source, offset, end_offset)
    if start >= end:
        fail("error: selection is not a complete expression")
    found = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr):
            continue
        span = node_offsets(edits.starts, lines, node)
        if span == (start, end):
            found = node
            break
    if found is None:
        fail("error: selection is not a complete expression")
    statement = enclosing_statement(tree, found)
    if statement is None:
        fail("error: selection is not a complete expression")
    indent = leading_ws(_source_line(lines, statement.lineno))
    where = edits.line_start(statement.lineno)
    edits.replace(
        where, where, "%s%s = %s\n" % (indent, new_name, source[start:end])
    )
    edits.replace(start, end, new_name)
    changes = {os.path.abspath(path): (source, edits.result())}
    return refactor_output(root, changes, {}, diff)


# ---------------------------------------------------------------------------
# extract-function
# ---------------------------------------------------------------------------

_SCOPE_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _binding_sites(holder):
    """(name, line) for every variable bound directly in one scope."""
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPE_NODES):
                continue
            if isinstance(child, ast.Name) and isinstance(
                child.ctx, (ast.Store, ast.Del)
            ):
                out.append((child.id, getattr(child, "lineno", 0) or 0))
            elif isinstance(child, ast.arg):
                out.append((child.arg, getattr(child, "lineno", 0) or 0))
            walk(child)

    walk(holder)
    return out


def _selection_events(statements):
    """Every read and write of a plain name inside the selection."""
    events = []
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name):
                read = isinstance(node.ctx, ast.Load)
                events.append(
                    (node.lineno, node.col_offset, 0 if read else 1, node.id,
                     "read" if read else "write")
                )
            elif isinstance(node, ast.arg):
                events.append(
                    (node.lineno, node.col_offset, 1, node.arg, "write")
                )
            elif isinstance(node, ast.AugAssign) and isinstance(
                node.target, ast.Name
            ):
                events.append(
                    (
                        node.target.lineno,
                        node.target.col_offset,
                        0,
                        node.target.id,
                        "read",
                    )
                )
    events.sort()
    return [(item[3], item[4]) for item in events]


def _read_after(holder, until_line):
    """Names still read once the selection is over."""
    out = set()
    for node in ast.walk(holder):
        if (getattr(node, "lineno", 0) or 0) <= until_line:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.add(node.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
    return out


def _statement_bodies(tree):
    """Every list of statements in the tree, with the node owning it."""
    out = []
    for node in ast.walk(tree):
        for _field, value in ast.iter_fields(node):
            if not isinstance(value, list) or not value:
                continue
            if all(isinstance(item, ast.stmt) for item in value):
                out.append((node, value))
    return out


def _selected_statements(tree, line, col, until_line, until_col):
    """The whole statements a selection covers, or exit 1."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        start = getattr(node, "lineno", 0) or 0
        end = getattr(node, "end_lineno", 0) or start
        if end < line or start > until_line:
            continue
        if start >= line and end <= until_line:
            continue
        if start <= line and end >= until_line:
            continue
        fail("error: selection does not span whole statements")
    best = None
    for _owner, body in _statement_bodies(tree):
        chosen = [
            item
            for item in body
            if (getattr(item, "lineno", 0) or 0) >= line
            and (getattr(item, "end_lineno", 0) or item.lineno) <= until_line
        ]
        if not chosen:
            continue
        if (chosen[0].lineno != line) or (
            (chosen[-1].end_lineno or chosen[-1].lineno) != until_line
        ):
            continue
        first = body.index(chosen[0])
        if body[first : first + len(chosen)] != chosen:
            continue
        if best is None or chosen[0].col_offset > best[0].col_offset:
            best = chosen
    if best is None:
        fail("error: selection does not span whole statements")
    if col > (best[0].col_offset or 0):
        fail("error: selection does not span whole statements")
    if until_col < (best[-1].end_col_offset or 0) - 1:
        fail("error: selection does not span whole statements")
    return best


def _shift_line(text, shift):
    if not text.strip() or shift == 0:
        return text
    if shift > 0:
        return " " * shift + text
    strip = 0
    while strip < -shift and strip < len(text) and text[strip] in " \t":
        strip += 1
    return text[strip:]


def extract_function(
    path, line, col, until_line, until_col, new_name, diff=False, project=None
):
    if not valid_identifier(new_name):
        fail("error: %s is not a valid Python identifier" % new_name)
    source, lines, _offset = load_source(path, line, col)
    _end, until_line, until_col = position_offset(
        lines, until_line, until_col, True
    )
    if until_line < line:
        fail("error: selection does not span whole statements")
    root = project_root(path, project)
    tree = parse_strict(source, path)
    chosen = _selected_statements(tree, line, col, until_line, until_col)

    holders = [tree]
    enclosing = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = getattr(node, "lineno", 0) or 0
        end = getattr(node, "end_lineno", 0) or start
        if start >= line or end < until_line:
            continue
        if not isinstance(node, ast.ClassDef):
            holders.append(node)
        if enclosing is None or node.col_offset > enclosing.col_offset:
            enclosing = node
    inner = holders[-1] if len(holders) > 1 else tree

    outside = set()
    for holder in holders:
        for bound, bound_line in _binding_sites(holder):
            if line <= bound_line <= until_line:
                continue
            outside.add(bound)

    params = []
    assigned = []
    first_seen = {}
    for bound, kind in _selection_events(chosen):
        if bound not in first_seen:
            first_seen[bound] = kind
            if kind == "read" and bound in outside:
                params.append(bound)
        if kind == "write" and bound not in assigned:
            assigned.append(bound)
    later = _read_after(inner, until_line)
    returns = [bound for bound in assigned if bound in later]

    base_col = chosen[0].col_offset or 0
    if enclosing is None:
        insert_line = line
        indent = " " * base_col
    else:
        starts = [getattr(enclosing, "lineno", 0) or 0]
        starts += [
            getattr(item, "lineno", 0) or 0
            for item in getattr(enclosing, "decorator_list", [])
            if getattr(item, "lineno", 0)
        ]
        insert_line = min(starts)
        indent = " " * (enclosing.col_offset or 0)
    body_indent = indent + "    "
    shift = len(body_indent) - base_col

    pieces = ["%sdef %s(%s):\n" % (indent, new_name, ", ".join(params))]
    for index in range(line, until_line + 1):
        pieces.append(_shift_line(lines[index - 1], shift) + "\n")
    if returns:
        pieces.append("%sreturn %s\n" % (body_indent, ", ".join(returns)))
    pieces.append("\n")
    function_text = "".join(pieces)

    call = "%s(%s)" % (new_name, ", ".join(params))
    if returns:
        call = "%s = %s" % (", ".join(returns), call)
    call_line = " " * base_col + call + "\n"

    edits = SourceEdits(path, source)
    start = edits.line_start(line)
    end = edits.line_end(until_line)
    if enclosing is None:
        edits.replace(start, end, function_text + call_line)
    else:
        where = edits.line_start(insert_line)
        edits.replace(where, where, function_text)
        edits.replace(start, end, call_line)
    changes = {os.path.abspath(path): (source, edits.result())}
    return refactor_output(root, changes, {}, diff)


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


def scope_context(scope):
    """The class and function scopes around `scope`, outermost first."""
    out = []
    current = scope
    while current is not None and current.kind != "module":
        if current.kind in ("class", "function"):
            node = current.node
            name = getattr(node, "name", None)
            if isinstance(name, str):
                out.append(
                    {
                        "name": name,
                        "type": current.kind,
                        "line": getattr(node, "lineno", 0) or 0,
                        "column": getattr(node, "col_offset", 0) or 0,
                    }
                )
        current = current.parent
    out.reverse()
    return out


def context(path, line, col, project=None):
    source, lines, offset = load_source(path, line, col)
    root = project_root(path, project)
    try:
        tree = tolerant_parse(lines, line)
        analyzer = Analyzer(tree, path, lines, Project(root))
        found = scope_context(analyzer.scope_for(line, col))
    except BaseException:
        found = []
    sys.stdout.write(json.dumps({"context": found}, separators=(",", ":")) + "\n")
    return 0


# ---------------------------------------------------------------------------
# Python environments
# ---------------------------------------------------------------------------

_PYTHON_INFO_CODE = (
    "import json,sys;"
    "print(json.dumps({"
    "'version':'.'.join(str(part) for part in sys.version_info[:3]),"
    "'prefix':sys.prefix,"
    "'base_prefix':getattr(sys,'base_prefix',sys.prefix),"
    "'real_prefix':getattr(sys,'real_prefix',''),"
    "'executable':sys.executable,"
    "'sys_path':[entry for entry in sys.path if entry]"
    "}))"
)

# Names a Python interpreter goes by, most canonical first.
PYTHON_NAMES = (
    ["python", "python3", "python2"]
    + ["python3.%d" % minor for minor in range(20, -1, -1)]
    + ["python2.7"]
)

EXTRA_BIN_DIRS = (
    "/usr/bin",
    "/usr/local/bin",
    "/bin",
    "/opt/homebrew/bin",
    "/opt/local/bin",
)

_INFO_CACHE = {}


def _resolved(path):
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except OSError:  # pragma: no cover - realpath rarely fails
        return os.path.normcase(os.path.abspath(path))


def _has_pyvenv_cfg(executable):
    """True when `executable` lives in a PEP 405 virtual environment."""
    directory = os.path.dirname(os.path.abspath(executable))
    for candidate in (directory, os.path.dirname(directory)):
        if candidate and os.path.isfile(os.path.join(candidate, "pyvenv.cfg")):
            return True
    return False


def _virtualenv_flag(executable, data):
    if data.get("real_prefix"):
        return True
    prefix = data.get("prefix") or ""
    base = data.get("base_prefix") or prefix
    if prefix and base and os.path.normcase(prefix) != os.path.normcase(base):
        return True
    return _has_pyvenv_cfg(executable)


def _current_python_info():
    return {
        "version": ".".join(str(part) for part in sys.version_info[:3]),
        "prefix": sys.prefix,
        "base_prefix": getattr(sys, "base_prefix", sys.prefix),
        "real_prefix": getattr(sys, "real_prefix", ""),
        "executable": sys.executable,
        "sys_path": [entry for entry in sys.path if entry],
    }


def python_info(executable):
    """Ask a Python executable about itself, or None when it is not one."""
    if not executable:
        return None
    path = os.path.abspath(executable)
    key = os.path.normcase(path)
    if key in _INFO_CACHE:
        return _INFO_CACHE[key]
    data = None
    if os.path.isfile(path):
        if key == os.path.normcase(os.path.abspath(sys.executable or "")):
            data = _current_python_info()
        else:
            data = _interrogate(path)
    info = None
    if isinstance(data, dict) and isinstance(data.get("version"), str):
        info = {
            "executable": posix_path(path),
            "version": data.get("version") or "",
            "is_virtualenv": _virtualenv_flag(path, data),
            "prefix": posix_path(data.get("prefix") or ""),
            "sys_path": [
                posix_path(entry)
                for entry in (data.get("sys_path") or [])
                if isinstance(entry, str) and entry
            ],
        }
    _INFO_CACHE[key] = info
    return info


def _interrogate(path):
    """Run `path -c ...` and read back the JSON it prints."""
    try:
        proc = subprocess.run(
            [path, "-c", _PYTHON_INFO_CODE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        data = json.loads(text.splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return data if isinstance(data, dict) else None


def version_key(version):
    """A comparable key for a dotted version string."""
    parts = [int(part) for part in re.findall(r"\d+", version or "")][:4]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def environment_record(info, virtualenv=False):
    return {
        "executable": info["executable"],
        "version": info["version"],
        "is_virtualenv": bool(info["is_virtualenv"] or virtualenv),
    }


def environment_records(executables, virtualenv=False):
    """One record per distinct Python executable, newest version first."""
    records = []
    seen = set()
    for executable in executables:
        key = _resolved(executable)
        if key in seen:
            continue
        info = python_info(executable)
        if info is None:
            continue
        seen.add(key)
        records.append(environment_record(info, virtualenv))
    records.sort(key=lambda record: record["executable"])
    records.sort(key=lambda record: version_key(record["version"]), reverse=True)
    return records


def _binary_directories():
    directories = []
    seen = set()
    entries = (os.environ.get("PATH") or "").split(os.pathsep)
    for entry in list(entries) + list(EXTRA_BIN_DIRS):
        if not entry:
            continue
        absolute = os.path.abspath(entry)
        if absolute in seen or not os.path.isdir(absolute):
            continue
        seen.add(absolute)
        directories.append(absolute)
    return directories


def _executable_names():
    if os.name == "nt":
        return [name + ".exe" for name in PYTHON_NAMES]
    return list(PYTHON_NAMES)


def system_executables():
    """Every Python executable reachable through PATH."""
    found = []
    seen = set()
    for directory in _binary_directories():
        for name in _executable_names():
            path = os.path.join(directory, name)
            if path in seen:
                continue
            seen.add(path)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                found.append(path)
    current = os.path.abspath(sys.executable) if sys.executable else ""
    if current and current not in seen and os.path.isfile(current):
        found.append(current)
    return found


def virtualenv_executable(directory):
    """The interpreter of the virtualenv at `directory`, or None."""
    if not directory or not os.path.isdir(directory):
        return None
    for parts in (
        ("bin", "python"),
        ("Scripts", "python.exe"),
        ("bin", "python3"),
        ("Scripts", "python3.exe"),
    ):
        path = os.path.join(directory, *parts)
        if os.path.isfile(path):
            return path
    return None


def _subdirectories(directory):
    if not directory or not os.path.isdir(directory):
        return []
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return []
    return [
        os.path.join(directory, entry)
        for entry in entries
        if os.path.isdir(os.path.join(directory, entry))
    ]


def virtualenv_directories(path=None, root=None):
    """Where a virtualenv is conventionally kept."""
    directories = []
    if path:
        directories.append(os.path.abspath(path))
        directories += _subdirectories(os.path.abspath(path))
    directories += _subdirectories(os.path.expanduser(os.path.join("~", ".virtualenvs")))
    bases = [os.getcwd()]
    if root:
        bases.append(os.path.abspath(root))
    for base in bases:
        for name in (".venv", "venv"):
            directories.append(os.path.join(base, name))
    out = []
    seen = set()
    for directory in directories:
        absolute = os.path.abspath(directory)
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
    return out


def _print(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def env_list():
    _print({"environments": environment_records(system_executables())})
    return 0


def env_find_virtualenvs(path=None, root=None):
    if path is not None and not os.path.isdir(path):
        fail("error: no such directory: %s" % path)
    executables = []
    for directory in virtualenv_directories(path, root):
        executable = virtualenv_executable(directory)
        if executable is not None:
            executables.append(executable)
    _print({"environments": environment_records(executables, virtualenv=True)})
    return 0


def which_python(name):
    """The executable `name` points at, or None."""
    if not name:
        return None
    if os.sep in name or (os.altsep and os.altsep in name) or os.path.isabs(name):
        path = os.path.abspath(os.path.expanduser(name))
        return path if os.path.isfile(path) else None
    found = shutil.which(name)
    return os.path.abspath(found) if found else None


def default_executable():
    """The interpreter a command uses when none was named."""
    configured = (CONFIG.get("environment_path") or "").strip()
    return configured or ""


def system_default_executable():
    """`python3`, or the closest thing this machine has to it."""
    for name in ("python3", "python"):
        found = which_python(name)
        if found is not None:
            return found
    return os.path.abspath(sys.executable) if sys.executable else None


def env_info(executable=None):
    target = executable or default_executable()
    if target:
        path = which_python(target)
    else:
        target = "python3"
        path = system_default_executable()
    if not path or not os.path.isfile(path):
        fail("error: no such Python executable: %s" % target)
    info = python_info(path)
    if info is None:
        fail("error: not a Python executable: %s" % target)
    record = environment_record(info)
    record["prefix"] = info["prefix"]
    record["sys_path"] = list(info["sys_path"])
    payload = dict(record)
    payload["environment"] = record
    payload["environments"] = [record]
    _print(payload)
    return 0


# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------


def project_init(directory=None, environment=None, sys_path=None, added_sys_path=None):
    """Write `<directory>/.sith/project.json`, merging into what is there."""
    root = os.path.abspath(directory or os.getcwd())
    if not os.path.isdir(root):
        fail("error: no such directory: %s" % (directory or root))
    config = read_project_config(root)
    if environment is not None:
        config["environment_path"] = environment
    if sys_path is not None:
        config["sys_path"] = list(sys_path)
    if added_sys_path is not None:
        config["added_sys_path"] = list(added_sys_path)
    if "smart_sys_path" in EXPLICIT_SETTINGS:
        config["smart_sys_path"] = SETTINGS["smart_sys_path"]
    ordered = {
        "environment_path": config["environment_path"],
        "sys_path": list(config["sys_path"]),
        "added_sys_path": list(config["added_sys_path"]),
        "smart_sys_path": bool(config["smart_sys_path"]),
    }
    path = config_file(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(ordered, indent=2) + "\n")
    except OSError as exc:
        fail("error: cannot write %s: %s" % (path, exc))
    _print(ordered)
    return 0


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


def _error_record(exc):
    line = getattr(exc, "lineno", None) or 1
    column = (getattr(exc, "offset", None) or 1) - 1
    end_line = getattr(exc, "end_lineno", None) or line
    end_column = getattr(exc, "end_offset", None)
    end_column = column + 1 if end_column is None else end_column - 1
    if column < 0:
        column = 0
    if end_line < line:
        end_line = line
    if end_line == line and end_column < column:
        end_column = column
    return {
        "line": line,
        "column": column,
        "until_line": end_line,
        "until_column": max(end_column, 0),
        "message": str(getattr(exc, "msg", None) or exc),
    }


def errors(path):
    text = read_source(path)
    source = normalize(text)
    if source.startswith("\ufeff"):
        source = source[1:]
    found = []
    try:
        ast.parse(source, path)
    except SyntaxError as exc:
        found.append(_error_record(exc))
    except ValueError as exc:
        found.append(
            {
                "line": 1,
                "column": 0,
                "until_line": 1,
                "until_column": 0,
                "message": str(exc),
            }
        )
    sys.stdout.write(json.dumps({"errors": found}, separators=(",", ":")) + "\n")
    return 0


USAGE = (
    "usage: sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]\n"
    "       sith.py infer <file> <line> <col> [--project <dir>]\n"
    "       sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]\n"
    "       sith.py signatures <file> <line> <col> [--project <dir>]\n"
    "       sith.py context <file> <line> <col> [--project <dir>]\n"
    "       sith.py references <file> <line> <col> [--scope file|project]"
    " [--project <dir>]\n"
    "       sith.py search <query> [--project <dir>]\n"
    "       sith.py names <file> [--all-scopes] [--project <dir>]\n"
    "       sith.py rename <file> <line> <col> --new-name <name> [--diff]"
    " [--project <dir>]\n"
    "       sith.py inline <file> <line> <col> [--diff] [--project <dir>]\n"
    "       sith.py extract-variable <file> <line> <col> --until <line>:<col>"
    " --name <name> [--diff] [--project <dir>]\n"
    "       sith.py extract-function <file> <line> <col> --until <line>:<col>"
    " --name <name> [--diff] [--project <dir>]\n"
    "       sith.py errors <file>\n"
    "       sith.py env list\n"
    "       sith.py env find-virtualenvs [--path <dir>]\n"
    "       sith.py env info [<executable>]\n"
    "       sith.py project init [<dir>] [--environment <executable>]"
    " [--sys-path <path>[,<path>...]] [--added-sys-path <path>[,<path>...]]\n"
    "\n"
    "       the analysis commands also take --interpreter [--namespaces <file>],"
    " and every command takes --setting <key>=<value>"
)

COMMANDS = {
    "complete": 3,
    "context": 3,
    "infer": 3,
    "goto": 3,
    "signatures": 3,
    "references": 3,
    "search": 1,
    "names": 1,
    "rename": 3,
    "inline": 3,
    "extract-variable": 3,
    "extract-function": 3,
    "errors": 1,
}

REFACTORINGS = ("rename", "inline", "extract-variable", "extract-function")
EXTRACTIONS = ("extract-variable", "extract-function")
# The commands interpreter mode applies to.
INTERPRETED = ("complete", "infer", "goto", "signatures")
ENV_COMMANDS = ("list", "find-virtualenvs", "info")
PROJECT_COMMANDS = ("init",)
BOOL_WORDS = {"true": True, "false": False}


def apply_setting(text):
    """Fold one `--setting key=value` into the settings in force."""
    if "=" not in text:
        fail("error: --setting must look like <key>=<value>")
    key, _, value = text.partition("=")
    key = key.strip()
    if key not in DEFAULT_SETTINGS:
        fail("error: unknown setting: %s" % key)
    parsed = BOOL_WORDS.get(value.strip().lower())
    if parsed is None:
        fail("error: %s must be true or false: %s" % (key, value))
    SETTINGS[key] = parsed
    EXPLICIT_SETTINGS.add(key)


def split_paths(text):
    """`--sys-path a,b` as a list of paths."""
    return [entry.strip() for entry in text.split(",") if entry.strip()]


class Options:
    """A tiny option reader shared by the sub-command parsers."""

    def __init__(self, args):
        self.args = list(args)
        self.index = 0
        self.positional = []

    def value_of(self, option):
        self.index += 1
        if self.index >= len(self.args):
            fail("error: %s requires a value" % option)
        return self.args[self.index]


def env_command(args):
    """`sith.py env list|find-virtualenvs|info`."""
    if not args:
        usage()
    sub = args[0]
    if sub not in ENV_COMMANDS:
        fail("error: unknown env command: %s" % sub)
    options = Options(args[1:])
    path = None
    project = None
    while options.index < len(options.args):
        arg = options.args[options.index]
        if arg == "--path" and sub == "find-virtualenvs":
            path = options.value_of(arg)
        elif arg.startswith("--path=") and sub == "find-virtualenvs":
            path = arg.split("=", 1)[1]
        elif arg == "--project":
            project = options.value_of(arg)
        elif arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        elif arg == "--setting":
            apply_setting(options.value_of(arg))
        elif arg.startswith("--setting="):
            apply_setting(arg.split("=", 1)[1])
        elif arg.startswith("-") and arg != "-":
            fail("error: unknown option: %s" % arg)
        else:
            options.positional.append(arg)
        options.index += 1
    if project is not None and not os.path.isdir(project):
        fail("error: no such project directory: %s" % project)
    root = os.path.abspath(project) if project else os.getcwd()
    use_project_config(root)
    if sub == "list":
        if options.positional:
            usage()
        return env_list()
    if sub == "find-virtualenvs":
        if options.positional:
            usage()
        return env_find_virtualenvs(path, root)
    if len(options.positional) > 1:
        usage()
    return env_info(options.positional[0] if options.positional else None)


def project_command(args):
    """`sith.py project init`."""
    if not args:
        usage()
    sub = args[0]
    if sub not in PROJECT_COMMANDS:
        fail("error: unknown project command: %s" % sub)
    options = Options(args[1:])
    environment = None
    sys_path = None
    added_sys_path = None
    while options.index < len(options.args):
        arg = options.args[options.index]
        if arg == "--environment":
            environment = options.value_of(arg)
        elif arg.startswith("--environment="):
            environment = arg.split("=", 1)[1]
        elif arg == "--sys-path":
            sys_path = (sys_path or []) + split_paths(options.value_of(arg))
        elif arg.startswith("--sys-path="):
            sys_path = (sys_path or []) + split_paths(arg.split("=", 1)[1])
        elif arg == "--added-sys-path":
            added_sys_path = (added_sys_path or []) + split_paths(options.value_of(arg))
        elif arg.startswith("--added-sys-path="):
            added_sys_path = (added_sys_path or []) + split_paths(arg.split("=", 1)[1])
        elif arg == "--setting":
            apply_setting(options.value_of(arg))
        elif arg.startswith("--setting="):
            apply_setting(arg.split("=", 1)[1])
        elif arg.startswith("-") and arg != "-":
            fail("error: unknown option: %s" % arg)
        else:
            options.positional.append(arg)
        options.index += 1
    if len(options.positional) > 1:
        usage()
    directory = options.positional[0] if options.positional else None
    return project_init(directory, environment, sys_path, added_sys_path)


def parse_until(text):
    """`--until <line>:<col>` as a pair of integers."""
    parts = text.split(":")
    if len(parts) != 2:
        fail("error: --until must look like <line>:<col>")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        fail("error: --until must look like <line>:<col>")

SCOPES = ("file", "project")


def usage():
    fail(USAGE)


def main(argv):
    args = list(argv[1:])
    if not args:
        usage()
    command = args.pop(0)
    if command == "env":
        return env_command(args)
    if command == "project":
        return project_command(args)
    if command not in COMMANDS:
        fail("error: unknown command: %s" % command)
    fuzzy = False
    interpreter = False
    namespaces_path = None
    follow = False
    all_scopes = False
    diff = False
    new_name = None
    until = None
    scope = "file"
    project = None
    positional = []
    index = 0

    def value_of(option):
        nonlocal index
        index += 1
        if index >= len(args):
            fail("error: %s requires a value" % option)
        return args[index]

    while index < len(args):
        arg = args[index]
        if arg == "--fuzzy" and command == "complete":
            fuzzy = True
        elif arg == "--follow-imports":
            follow = True
        elif arg == "--all-scopes" and command == "names":
            all_scopes = True
        elif arg == "--diff" and command in REFACTORINGS:
            diff = True
        elif arg == "--new-name" and command == "rename":
            new_name = value_of(arg)
        elif arg.startswith("--new-name=") and command == "rename":
            new_name = arg.split("=", 1)[1]
        elif arg == "--name" and command in EXTRACTIONS:
            new_name = value_of(arg)
        elif arg.startswith("--name=") and command in EXTRACTIONS:
            new_name = arg.split("=", 1)[1]
        elif arg == "--until" and command in EXTRACTIONS:
            until = parse_until(value_of(arg))
        elif arg.startswith("--until=") and command in EXTRACTIONS:
            until = parse_until(arg.split("=", 1)[1])
        elif arg == "--scope" and command == "references":
            scope = value_of(arg)
        elif arg.startswith("--scope=") and command == "references":
            scope = arg.split("=", 1)[1]
        elif arg == "--project":
            project = value_of(arg)
        elif arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        elif arg == "--interpreter" and command in INTERPRETED:
            interpreter = True
        elif arg == "--namespaces" and command in INTERPRETED:
            namespaces_path = value_of(arg)
        elif arg.startswith("--namespaces=") and command in INTERPRETED:
            namespaces_path = arg.split("=", 1)[1]
        elif arg == "--setting":
            apply_setting(value_of(arg))
        elif arg.startswith("--setting="):
            apply_setting(arg.split("=", 1)[1])
        elif arg.startswith("-") and arg != "-":
            fail("error: unknown option: %s" % arg)
        else:
            positional.append(arg)
        index += 1
    if len(positional) != COMMANDS[command]:
        usage()
    if scope not in SCOPES:
        fail("error: --scope must be file or project")
    if project is not None and not os.path.isdir(project):
        fail("error: no such project directory: %s" % project)
    if namespaces_path is not None and not interpreter:
        fail("error: --namespaces requires --interpreter")
    namespaces = None
    if interpreter and namespaces_path is not None:
        namespaces = load_namespaces(namespaces_path)
    if command == "search":
        root = os.path.abspath(project) if project else os.getcwd()
    else:
        root = project_root(positional[0], project)
    use_project_config(root)
    if command == "search":
        return search(positional[0], project)
    if command == "names":
        return names(positional[0], all_scopes, project)
    if command == "errors":
        return errors(positional[0])
    try:
        line = int(positional[1])
        col = int(positional[2])
    except ValueError:
        fail("error: line and column must be integers")
    if command == "rename":
        if new_name is None:
            fail("error: rename requires --new-name <name>")
        return rename(positional[0], line, col, new_name, diff, project)
    if command == "inline":
        return inline(positional[0], line, col, diff, project)
    if command in EXTRACTIONS:
        if new_name is None:
            fail("error: %s requires --name <name>" % command)
        if until is None:
            fail("error: %s requires --until <line>:<col>" % command)
        runner = extract_variable if command == "extract-variable" else extract_function
        return runner(
            positional[0], line, col, until[0], until[1], new_name, diff, project
        )
    if command == "complete":
        return complete(positional[0], line, col, fuzzy, project, namespaces)
    if command == "signatures":
        return signatures(positional[0], line, col, project, namespaces)
    if command == "references":
        return references(positional[0], line, col, scope, project)
    if command == "context":
        return context(positional[0], line, col, project)
    return navigate(positional[0], line, col, command, project, follow, namespaces)


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
