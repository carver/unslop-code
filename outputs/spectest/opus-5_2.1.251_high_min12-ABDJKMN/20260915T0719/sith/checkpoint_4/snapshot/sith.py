#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
    python sith.py infer <file> <line> <col> [--project <dir>]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
    python sith.py signatures <file> <line> <col> [--project <dir>]
    python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
    python sith.py search <query> [--project <dir>]
    python sith.py names <file> [--all-scopes] [--project <dir>]

Parses a Python source file statically, works out which names are visible at the
requested cursor position (or which attributes a receiver expression exposes) and
prints ranked completions as compact JSON on stdout.

The tool operates on a project, not a single file: imports are resolved against
the project root (`--project`, else the directory holding <file>) and then the
modules of the target runtime, so `infer`, `goto` and `complete` all reach across
files.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import importlib
import inspect
import json
import keyword
import os
import re
import sys

MISSING = object()

# Call-site parameter inference: on unless explicitly switched off (T70).
DYNAMIC = [True]


def join_module(modname, name):
    """`pkg` + `mod` -> `pkg.mod`; `.` + `mod` -> `.mod`."""
    if modname.endswith("."):
        return modname + name
    return "%s.%s" % (modname, name)

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def is_ident_char(ch):
    return ch.isalnum() or ch == "_"


def line_indent(text):
    n = 0
    for ch in text:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 8
        else:
            break
    return n


def describe(kind, name, typename=None):
    """Description of a completion, derived from its resolved kind (see AMBIGUITIES T1)."""
    if kind == "module":
        return "module %s" % name
    if kind == "class":
        return "class %s" % name
    if kind == "function":
        return "def %s(...)" % name
    if kind == "instance":
        return "instance of %s" % (typename or "object")
    if kind == "param":
        return "param %s" % name
    if kind == "keyword":
        return name
    return "statement"


# ---------------------------------------------------------------------------
# definitions (the `infer` / `goto` payload)
# ---------------------------------------------------------------------------

# Project root: definitions report `module_path` relative to it (T23).
ROOT = [os.getcwd()]


def set_root(path):
    ROOT[0] = os.path.abspath(path)


def rel_to_root(path):
    """Path of a definition's file relative to the project root (T23)."""
    if not path:
        return ""
    path = os.path.abspath(path)
    root = ROOT[0]
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return path
    if rel.startswith(".." + os.sep) or rel == "..":
        return path
    return rel.replace(os.sep, "/")


def within_root(path):
    """Is `path` the project root or inside it?"""
    if not path:
        return False
    path = os.path.abspath(path)
    root = ROOT[0]
    return path == root or path.startswith(root + os.sep)


def dotted_rel(path):
    """Dotted name of a file/directory relative to the project root, or None."""
    path = os.path.abspath(path or "")
    if not within_root(path):
        return None
    rel = os.path.relpath(path, ROOT[0])
    if rel in (".", ""):
        return ""
    parts = rel.replace(os.sep, "/").split("/")
    if parts[-1].endswith(".pyi"):
        parts[-1] = parts[-1][:-4]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(p for p in parts if p)


def module_name_for(path):
    """Qualified module name of a file, computed from the project root (spec)."""
    dotted = dotted_rel(path)
    if dotted:
        return dotted
    base = os.path.basename(path or "")
    if base.endswith(".pyi"):
        base = base[:-4]
    elif base.endswith(".py"):
        base = base[:-3]
    return base


def new_defn(name, kind, full_name, module_path, line, column, description,
             docstring=""):
    return {
        "name": name,
        "type": kind,
        "full_name": full_name,
        "module_path": module_path,
        "line": line,
        "column": column,
        "description": description,
        "docstring": docstring,
    }


def defn_description(kind, name, params=None, typename=None):
    """Description of a *definition* (see the spec's field table)."""
    if kind == "module":
        return "module %s" % name
    if kind == "class":
        return "class %s" % name
    if kind == "function":
        return "def %s(%s)" % (name, params if params is not None else "")
    if kind == "instance":
        return "instance of %s" % (typename or name)
    if kind == "param":
        return "param %s" % name
    return "statement"


def builtin_defn(name, kind="instance", params=None):
    """Definition for a builtin: no file, no position (spec: builtin types)."""
    return new_defn(name, kind, "builtins.%s" % name, "", 0, 0,
                    defn_description(kind, name, params=params, typename=name), "")


NONE_DEFN = builtin_defn("None")


def _live_signature(obj):
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return "..."
    text = str(sig)
    cut = text.rfind(") ->")
    if cut >= 0:
        text = text[:cut + 1]
    return text.strip()[1:-1]


def compute_live_defn(obj, kind, name):
    """Definition dict for a live Python object (module, class, function, type)."""
    try:
        modname = getattr(obj, "__module__", "") or ""
        qualname = getattr(obj, "__qualname__", None) or name
        if kind == "module":
            full = getattr(obj, "__name__", name) or name
        elif modname:
            full = "%s.%s" % (modname, qualname)
        else:
            full = qualname
        if name == "None":
            full = "builtins.None"
        path = ""
        line = 0
        column = 0
        docstring = ""
        try:
            path = inspect.getsourcefile(obj) or ""
        except Exception:
            path = ""
        if path and kind != "module":
            try:
                srclines, start = inspect.getsourcelines(obj)
                line = start or 1
                header = srclines[0] if srclines else ""
                pos = header.find(name)
                column = pos if pos >= 0 else 0
            except Exception:
                line, column = 0, 0
        if path:
            try:
                docstring = inspect.getdoc(obj) or ""
            except Exception:
                docstring = ""
        params = _live_signature(obj) if kind == "function" else None
        return new_defn(name, kind, full, rel_to_root(path), line, column,
                        defn_description(kind, name, params=params, typename=name),
                        docstring)
    except Exception:
        return builtin_defn(name, kind)


def live_defn(obj, kind, name):
    """Lazy wrapper: computing live definitions eagerly would slow completion."""
    return lambda: compute_live_defn(obj, kind, name)


def resolve_defn(d):
    if d is None or isinstance(d, dict):
        return d
    try:
        return d()
    except Exception:
        return None


def defn_sort_key(d):
    return (d.get("module_path", ""), d.get("line", 0), d.get("column", 0),
            d.get("name", ""))


def dedupe_defns(defns):
    out = []
    seen = set()
    for d in defns:
        if d is None:
            continue
        key = (d["name"], d["type"], d["full_name"], d["module_path"],
               d["line"], d["column"], d["description"])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return sorted(out, key=defn_sort_key)


def is_project_defn(d):
    """Does this definition live in a file inside the project root?"""
    if not d:
        return False
    path = d.get("module_path") or ""
    return bool(path) and not os.path.isabs(path)


def as_instance_defn(d, typename=None):
    """Turn a class definition into the definition of *an instance* of it."""
    if d is None:
        return None
    out = dict(d)
    out["type"] = "instance"
    out["description"] = "instance of %s" % (typename or d.get("name") or "object")
    return out


class Value:
    """What a name/expression resolves to: a completion kind plus an attribute source."""

    __slots__ = ("kind", "typename", "recv", "defn")

    def __init__(self, kind, typename=None, recv=None, defn=None):
        self.kind = kind
        self.typename = typename
        self.recv = recv
        self.defn = defn          # definition dict for `infer` (None when unknown)


UNKNOWN = Value("statement")


def value_from_obj(name, obj):
    """Classify a live Python object (T19)."""
    try:
        if inspect.ismodule(obj):
            mname = getattr(obj, "__name__", name)
            return Value("module", mname, PyRecv(obj), live_defn(obj, "module", mname))
        if inspect.isclass(obj):
            cname = getattr(obj, "__name__", name)
            return Value("class", cname, PyRecv(obj), live_defn(obj, "class", cname))
        if callable(obj):
            fname = getattr(obj, "__name__", name) or name
            return Value("function", None, FuncObjRecv(obj),
                         live_defn(obj, "function", fname))
        return instance_value_of_type(type(obj))
    except Exception:
        return UNKNOWN


def instance_value_of_type(tp):
    """A Value standing for *an instance of* the live type `tp` (T24)."""
    try:
        tname = tp.__name__
    except Exception:
        return UNKNOWN
    # `complete` keeps Python's own type name (NoneType); definitions call the
    # None type "None", the name the spec uses for it (T26).
    dname = "None" if tp is type(None) else tname
    return Value("instance", tname, PyRecv(tp), live_defn(tp, "instance", dname))


def builtin_instance(tp):
    return instance_value_of_type(tp)


def none_value():
    return instance_value_of_type(type(None))


def is_none_value(val):
    return (val is not None and val.kind == "instance"
            and val.typename in ("None", "NoneType"))


def constant_value(const):
    if const is None:
        return none_value()
    if const is Ellipsis:
        return UNKNOWN
    return instance_value_of_type(type(const))


def docstring_of(node):
    try:
        return ast.get_docstring(node) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# receivers -- things that can produce attributes
# ---------------------------------------------------------------------------


class Receiver:
    def attributes(self):
        return []

    def get_value(self, name):
        return None

    def get_values(self, name):
        """All possible values of an attribute (union); used by `infer`."""
        val = self.get_value(name)
        return [val] if val is not None else []

    def get_bindings(self, name):
        """Source bindings for an attribute (union); used by `goto`."""
        return []

    def sig_bindings(self, name):
        """Bindings `signatures` should consider (overload-aware); see T73."""
        return self.get_bindings(name)

    def call(self):
        vals = self.call_multi()
        return vals[0] if vals else None

    def call_multi(self):
        return []


class PyRecv(Receiver):
    """Attributes of a live object: a module, a class, or an instance."""

    def __init__(self, obj):
        self.obj = obj

    def _target(self):
        if inspect.ismodule(self.obj) or inspect.isclass(self.obj):
            return self.obj
        return type(self.obj)

    def attributes(self):
        target = self._target()
        try:
            raw = dir(target)
        except Exception:
            return []
        public_only = inspect.ismodule(target)
        out = []
        for n in raw:
            if public_only and n.startswith("_"):
                continue
            try:
                obj = getattr(target, n)
            except Exception:
                out.append((n, UNKNOWN))
                continue
            out.append((n, value_from_obj(n, obj)))
        return out

    def get_value(self, name):
        target = self._target()
        obj = getattr(target, name, MISSING)
        if obj is MISSING and inspect.ismodule(target):
            full = "%s.%s" % (getattr(target, "__name__", ""), name)
            sub = safe_import(full)
            if sub is not None:
                return value_from_obj(name, sub)
        if obj is MISSING:
            return None
        return value_from_obj(name, obj)

    def call_multi(self):
        if inspect.isclass(self.obj):
            return [instance_value_of_type(self.obj)]
        return []


class FuncRecv(Receiver):
    """A function defined in analysed source: calling it yields its return type."""

    def __init__(self, analyzer, node):
        self.analyzer = analyzer
        self.node = node

    def call_multi(self):
        return self.analyzer.return_values(self.node)


class FuncObjRecv(Receiver):
    """A live callable: exposes no completions, but its annotation can be called."""

    def __init__(self, obj):
        self.obj = obj

    def call_multi(self):
        # Live functions stay un-inferable: the spec infers return types from
        # `return` statements in analysed source only (T16 keeps `statement`).
        return []


class StaticModuleRecv(Receiver):
    """A project module (or package), analysed without executing it (T11).

    `analyzer` is the analysis of the module body (None for a namespace
    package); `pkgdir` is the directory when the module is a package, which is
    what makes its submodules visible as attributes (T42).
    """

    def __init__(self, analyzer, pkgdir=None, modname=None):
        self.analyzer = analyzer
        self.pkgdir = pkgdir
        if modname is None:
            if analyzer is not None:
                modname = analyzer.module_name
            else:
                modname = (dotted_rel(pkgdir) or
                           os.path.basename(pkgdir or ""))
        self.modname = modname

    # -- package structure -------------------------------------------------

    def submodules(self):
        """Names of the modules/packages directly inside this package."""
        if not self.pkgdir:
            return []
        return sorted(scan_module_dir(self.pkgdir))

    def submodule_recv(self, name):
        if not self.pkgdir:
            return None
        return find_project_module(self.pkgdir, name)

    def submodule_value(self, name):
        return static_module_value(self.submodule_recv(name), name)

    # -- names -------------------------------------------------------------

    def _module_bindings(self):
        if self.analyzer is None:
            return {}
        return self.analyzer.module.bindings

    # -- stubs -------------------------------------------------------------

    def stub(self):
        """The `.pyi` analysis backing this module's type information, if any."""
        if self.analyzer is None:
            return None
        return self.analyzer.stub()

    def _stub_bindings(self):
        st = self.stub()
        return st.module.bindings if st is not None else {}

    def dunder_all(self):
        """The module's `__all__` as a list of names, or None when absent."""
        blist = self._module_bindings().get("__all__")
        if not blist:
            return None
        for binding in reversed(blist):
            res = binding.res
            if res[0] != "expr" or res[1] is None:
                continue
            node = res[1]
            if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                continue
            out = []
            for el in node.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    out.append(el.value)
            return out
        return None

    def attributes(self):
        out = []
        seen = set()
        st = self.stub()
        # Stub first: its annotations win, but runtime-only names survive (T66).
        for name, blist in self._stub_bindings().items():
            if name.startswith("_"):
                continue
            seen.add(name)
            out.append((name, st.value_of(blist[-1])))
        for name, blist in self._module_bindings().items():
            if name.startswith("_") or name in seen:
                continue
            seen.add(name)
            out.append((name, self.analyzer.value_of(blist[-1])))
        for name in self.submodules():
            if name in seen or name.startswith("_"):
                continue
            seen.add(name)
            out.append((name, self.submodule_value(name)))
        return out

    def public_pairs(self):
        """(name, value) pairs a star import / `from X import ...` exposes."""
        exported = self.dunder_all()
        if exported is None:
            return self.attributes()
        out = []
        for name in exported:
            val = self.get_value(name)
            out.append((name, val if val is not None else UNKNOWN))
        return out

    def get_value(self, name):
        sblist = self._stub_bindings().get(name)
        if sblist:
            return self.stub().value_of(sblist[-1])
        blist = self._module_bindings().get(name)
        if blist:
            return self.analyzer.value_of(blist[-1])
        return self.submodule_value(name)

    def get_values(self, name):
        sblist = self._stub_bindings().get(name)
        if sblist:
            st = self.stub()
            out = []
            for b in live_bindings(sblist, None):
                out.extend(st.values_of(b))
            if out:
                return out
        out = []
        for b in self.get_bindings(name):
            out.extend(b.analyzer.values_of(b) if b.analyzer is not None
                       else self.analyzer.values_of(b))
        if out:
            return out
        val = self.submodule_value(name)
        return [val] if val is not None else []

    def get_bindings(self, name):
        blist = self._module_bindings().get(name)
        if not blist:
            # A name that exists only in the stub is still navigable (spec).
            blist = self._stub_bindings().get(name)
        if not blist:
            return []
        return live_bindings(blist, None)

    def sig_bindings(self, name):
        blist = self._stub_bindings().get(name) or self._module_bindings().get(name)
        if not blist:
            return []
        return with_overloads(blist, live_bindings(blist, None), None)

    # -- definitions -------------------------------------------------------

    def module_defn(self, bound_name=None):
        name = bound_name or (self.modname.split(".")[-1] if self.modname else "")
        if self.analyzer is not None:
            path = self.analyzer.rel_path
            doc = docstring_of(self.analyzer.tree)
        else:
            path = rel_to_root(self.pkgdir)
            doc = ""
        return new_defn(name, "module", self.modname or name, path, 0, 0,
                        "module %s" % name, doc)


class ClassRecv(Receiver):
    """Attributes of a class defined in an analysed file (optionally as an instance)."""

    def __init__(self, analyzer, node, instance=False):
        self.analyzer = analyzer
        self.node = node
        self.instance = instance

    def attributes(self):
        return list(self.analyzer.class_attrs(self.node, self.instance).items())

    def get_value(self, name):
        return self.analyzer.class_attrs(self.node, self.instance).get(name)

    def get_values(self, name):
        out = []
        for b in self.get_bindings(name):
            out.extend(b.analyzer.values_of(b))
        return out

    def get_bindings(self, name):
        return self.analyzer.class_attr_bindings(self.node, self.instance).get(name, [])

    def sig_bindings(self, name):
        binds = self.get_bindings(name)
        for cls in self.analyzer.linearize(self.node):
            scope = self.analyzer.class_scopes.get(cls)
            if scope is not None and name in scope.bindings:
                return with_overloads(scope.bindings[name], binds, None)
        return binds

    def call_multi(self):
        if not self.instance:
            return [self.analyzer.instance_value(self.node)]
        return []


def safe_import(modname):
    try:
        return importlib.import_module(modname)
    except BaseException:
        return None


# ---------------------------------------------------------------------------
# the project: module files, analysed once each
# ---------------------------------------------------------------------------

# abspath -> Analyzer. A module registers itself here *before* its body is
# walked, so a circular import sees whatever is defined so far instead of
# looping forever (spec: "do not infinite-loop").
MODULES = {}


def stub_path_for(path):
    """The `.pyi` giving type information for `path`, or None (spec: Stub Discovery).

    1. `foo.pyi` next to `foo.py`; 2. `stubs/foo.pyi` or `stubs/foo/__init__.pyi`
    under the project root, with `foo` spelled as the module's dotted path (T68).
    """
    if not path or path.endswith(".pyi"):
        return None
    base = path[:-3] if path.endswith(".py") else path
    inline = base + ".pyi"
    if os.path.isfile(inline):
        return inline
    dotted = dotted_rel(path)
    if dotted:
        parts = dotted.split(".")
        stubs = os.path.join(ROOT[0], "stubs")
        flat = os.path.join(stubs, *parts) + ".pyi"
        if os.path.isfile(flat):
            return flat
        pkg = os.path.join(os.path.join(stubs, *parts), "__init__.pyi")
        if os.path.isfile(pkg):
            return pkg
    return None


def decorator_names(node):
    """Bare names of a def/class's decorators (`foo`, `a.foo`, `foo(...)` -> `foo`)."""
    out = set()
    for dec in getattr(node, "decorator_list", []) or []:
        if isinstance(dec, ast.Call):
            dec = dec.func
        if isinstance(dec, ast.Name):
            out.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            out.add(dec.attr)
    return out


def is_overload(node):
    return "overload" in decorator_names(node)


def with_overloads(blist, live, line):
    """`@overload` declarations replace the implementation they shadow (T73)."""
    over = [b for b in blist
            if b.res[0] == "func" and is_overload(b.res[1])
            and (line is None or b.lineno <= line)]
    return over if over else live


def analyzer_for_path(path):
    """Analyse a project file once; None when it cannot be read."""
    path = os.path.abspath(path)
    if path in MODULES:
        return MODULES[path]
    MODULES[path] = None
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except Exception:
        return None
    try:
        tree, lines = robust_parse(text)
        analyzer = Analyzer(tree, lines, path)
    except Exception:
        return None
    MODULES[path] = analyzer
    return analyzer


def module_recv_for_file(path, pkgdir=None):
    analyzer = analyzer_for_path(path)
    if analyzer is None:
        return None
    return StaticModuleRecv(analyzer, pkgdir)


def scan_module_dir(dirpath):
    """Importable module/package names directly inside `dirpath`."""
    out = set()
    try:
        entries = os.listdir(dirpath)
    except OSError:
        return out
    for entry in entries:
        full = os.path.join(dirpath, entry)
        if entry.endswith(".py"):
            stem = entry[:-3]
            if stem != "__init__" and stem.isidentifier():
                out.add(stem)
        elif os.path.isdir(full) and entry.isidentifier() and entry != "__pycache__":
            out.add(entry)
    return out


def package_recv_for_dir(dirpath):
    """Receiver for a directory used as a package (regular or namespace)."""
    init = os.path.join(dirpath, "__init__.py")
    if os.path.isfile(init):
        return module_recv_for_file(init, dirpath)
    initi = os.path.join(dirpath, "__init__.pyi")
    if os.path.isfile(initi):
        return module_recv_for_file(initi, dirpath)
    if os.path.isdir(dirpath):
        return StaticModuleRecv(None, dirpath)
    return None


def find_project_module(base, dotted):
    """Resolve a dotted module name under `base` (a directory in the project)."""
    parts = [p for p in (dotted or "").split(".") if p]
    if not parts:
        return None
    cur = base
    recv = None
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        init = os.path.join(cur, part, "__init__.py")
        initi = os.path.join(cur, part, "__init__.pyi")
        pyfile = os.path.join(cur, part + ".py")
        pyifile = os.path.join(cur, part + ".pyi")
        pkgdir = os.path.join(cur, part)
        if os.path.isfile(init):
            recv = module_recv_for_file(init, pkgdir)
            cur = pkgdir
        elif os.path.isfile(pyfile):
            if not last:
                return None
            recv = module_recv_for_file(pyfile)
        elif os.path.isfile(initi):
            # A package that exists only as stubs.
            recv = module_recv_for_file(initi, pkgdir)
            cur = pkgdir
        elif os.path.isfile(pyifile):
            if not last:
                return None
            recv = module_recv_for_file(pyifile)
        elif os.path.isdir(pkgdir):
            # Namespace package: same rules as a regular package.
            recv = StaticModuleRecv(None, pkgdir)
            cur = pkgdir
        else:
            return None
        if recv is None:
            return None
    return recv


def static_module_value(recv, bound_name=None):
    if recv is None:
        return None
    return Value("module", recv.modname, recv, recv.module_defn(bound_name))


def public_pairs(recv):
    """(name, value) pairs a module exports: `__all__`, else non-underscore."""
    if recv is None:
        return []
    if isinstance(recv, StaticModuleRecv):
        return recv.public_pairs()
    if isinstance(recv, PyRecv) and inspect.ismodule(recv.obj):
        exported = getattr(recv.obj, "__all__", None)
        if isinstance(exported, (list, tuple)):
            out = []
            for name in exported:
                if not isinstance(name, str):
                    continue
                obj = getattr(recv.obj, name, MISSING)
                out.append((name, UNKNOWN if obj is MISSING
                            else value_from_obj(name, obj)))
            return out
    return recv.attributes()


# ---------------------------------------------------------------------------
# scopes / bindings
# ---------------------------------------------------------------------------


class Binding:
    __slots__ = ("name", "lineno", "res", "scope", "_value", "_values", "_busy",
                 "col", "stmt", "path", "analyzer", "owner")

    def __init__(self, name, lineno, res, scope=None, col=0, stmt=None, path=(),
                 analyzer=None, owner=None):
        self.name = name
        self.lineno = lineno
        self.res = res          # descriptor resolved lazily into a Value
        self.scope = scope
        self.col = col          # column of the identifier being bound
        self.stmt = stmt        # AST node the binding comes from (for goto)
        self.path = path        # branch path, for "which bindings are live"
        self.analyzer = analyzer
        self.owner = owner      # scope used to build the dotted full_name
        self._value = None
        self._values = None
        self._busy = False


def live_bindings(blist, line):
    """The bindings of a name that can still be in effect at `line` (T27).

    A later binding kills an earlier one only when it is guaranteed to run
    whenever the earlier one did -- i.e. when it sits on the same branch path
    or on an enclosing one.  Bindings in sibling branches all survive.
    """
    cands = [b for b in blist if line is None or b.lineno <= line]
    if not cands:
        return []
    out = []
    for i, b in enumerate(cands):
        killed = False
        for other in cands[i + 1:]:
            if other.lineno <= b.lineno and other is not b:
                continue
            if _path_covers(other.path, b.path):
                killed = True
                break
        if not killed:
            out.append(b)
    return out


def _path_covers(outer, inner):
    """True when `outer` is the same branch as `inner` or encloses it."""
    if len(outer) > len(inner):
        return False
    return tuple(outer) == tuple(inner[:len(outer)])


class Scope:
    def __init__(self, kind, node, parent, start, end, indent=0):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.start = start
        self.end = end
        self.ext_end = end
        self.indent = indent
        self.bindings = {}
        self.children = []
        if parent is not None:
            parent.children.append(self)

    def add(self, binding):
        self.bindings.setdefault(binding.name, []).append(binding)

    def contains(self, line, col):
        if self.kind == "module":
            return True
        if self.start <= line <= self.end:
            return True
        if self.end < line <= self.ext_end and col > self.indent:
            return True
        return False


# ---------------------------------------------------------------------------
# analyzer
# ---------------------------------------------------------------------------


class Analyzer:
    def __init__(self, tree, lines, filepath):
        self.lines = lines
        self.tree = tree
        self.filepath = os.path.abspath(filepath)
        self.dirname = os.path.dirname(self.filepath)
        self.module_name = module_name_for(self.filepath)
        self.rel_path = rel_to_root(self.filepath)
        self._init_attr_cache = {}
        self._class_binding_cache = {}
        self._stub = MISSING
        self._stub_node_cache = {}
        self._call_site_cache = {}
        self._dyn_busy = set()
        self._returns_busy = set()
        self.class_scopes = {}
        self.func_scopes = {}
        self._module_cache = {}
        self._class_attr_cache = {}
        nlines = max(1, len(lines))
        self.module = Scope("module", tree, None, 1, nlines)
        self.module.ext_end = nlines
        # Publish before walking the body: a module in an import cycle then sees
        # the names defined so far rather than recursing forever.
        MODULES[self.filepath] = self
        self._build_body(getattr(tree, "body", []), self.module)

    # -- construction ------------------------------------------------------

    def _new_scope(self, kind, node, parent):
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", None) or start
        indent = 0
        if 1 <= start <= len(self.lines):
            indent = line_indent(self.lines[start - 1])
        sc = Scope(kind, node, parent, start, end, indent)
        sc.ext_end = self._extended_end(end, indent)
        return sc

    def _extended_end(self, end, indent):
        j = end
        n = len(self.lines)
        while j < n:
            text = self.lines[j]
            if text.strip() == "" or line_indent(text) > indent:
                j += 1
            else:
                break
        return j

    def _build_body(self, body, scope, path=()):
        for st in body or []:
            try:
                self._build_stmt(st, scope, path)
            except Exception:
                continue

    def _branch(self, path, node, index):
        return tuple(path) + ((id(node), index),)

    def name_col(self, node, name):
        """Column of `name` on the header line of a def/class statement."""
        lineno = getattr(node, "lineno", 0)
        if 1 <= lineno <= len(self.lines):
            text = self.lines[lineno - 1]
            start = getattr(node, "col_offset", 0) or 0
            # Whole-word search, so `def ef()` does not find the "ef" in "def".
            match = re.search(r"\b%s\b" % re.escape(name), text[start:])
            if match is not None:
                return start + match.start()
            pos = text.find(name, start)
            if pos >= 0:
                return pos
        return getattr(node, "col_offset", 0) or 0

    def _bind(self, scope, name, lineno, res, col=0, stmt=None, path=()):
        scope.add(Binding(name, lineno, res, scope, col=col, stmt=stmt,
                          path=tuple(path), analyzer=self, owner=scope))

    def _build_stmt(self, st, scope, path=()):
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._bind(scope, st.name, st.lineno, ("func", st),
                       self.name_col(st, st.name), st, path)
            child = self._new_scope("function", st, scope)
            self.func_scopes[st] = child
            for i, arg in enumerate(self._arg_nodes(st.args)):
                child.add(Binding(arg.arg, st.lineno,
                                  ("param", arg.annotation, scope, st, i), child,
                                  col=getattr(arg, "col_offset", 0), stmt=arg,
                                  analyzer=self, owner=child))
            self._build_body(st.body, child)
        elif isinstance(st, ast.ClassDef):
            self._bind(scope, st.name, st.lineno, ("class", st),
                       self.name_col(st, st.name), st, path)
            child = self._new_scope("class", st, scope)
            self.class_scopes[st] = child
            self._build_body(st.body, child)
        elif isinstance(st, ast.Assign):
            for tgt in st.targets:
                self._bind_target(tgt, st.value, st.lineno, scope, path, st)
            self._walk_walrus(st.value, scope, path)
        elif isinstance(st, ast.AnnAssign):
            if isinstance(st.target, ast.Name):
                if st.value is not None:
                    res = ("expr", st.value, scope)
                else:
                    res = ("annotation", st.annotation, scope)
                self._bind(scope, st.target.id, st.lineno, res,
                           st.target.col_offset, st, path)
        elif isinstance(st, ast.AugAssign):
            if isinstance(st.target, ast.Name):
                self._bind(scope, st.target.id, st.lineno, ("unknown",),
                           st.target.col_offset, st, path)
        elif isinstance(st, ast.Import):
            for al in st.names:
                col = getattr(al, "col_offset", st.col_offset)
                if al.asname:
                    end = getattr(al, "end_col_offset", None)
                    if end is not None:
                        col = end - len(al.asname)
                    self._bind(scope, al.asname, st.lineno, ("mod", al.name),
                               col, st, path)
                else:
                    top = al.name.split(".")[0]
                    self._bind(scope, top, st.lineno, ("mod", top), col, st, path)
        elif isinstance(st, ast.ImportFrom):
            self._build_import_from(st, scope, path)
        elif isinstance(st, (ast.For, ast.AsyncFor)):
            body_path = self._branch(path, st, 0)
            self._bind_target(st.target, None, st.lineno, scope, body_path, st)
            self._build_body(st.body, scope, body_path)
            self._build_body(st.orelse, scope, self._branch(path, st, 1))
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, None, st.lineno,
                                      scope, path, st)
            self._build_body(st.body, scope, path)
        elif isinstance(st, (ast.If, ast.While)):
            self._walk_walrus(st.test, scope, path)
            self._build_body(st.body, scope, self._branch(path, st, 0))
            self._build_body(st.orelse, scope, self._branch(path, st, 1))
        elif isinstance(st, ast.Try) or st.__class__.__name__ == "TryStar":
            self._build_body(st.body, scope, self._branch(path, st, 0))
            for i, handler in enumerate(st.handlers):
                hpath = self._branch(path, st, 2 + i)
                if handler.name:
                    self._bind(scope, handler.name, handler.lineno, ("unknown",),
                               self.name_col(handler, handler.name), handler, hpath)
                self._build_body(handler.body, scope, hpath)
            self._build_body(st.orelse, scope, self._branch(path, st, 1))
            self._build_body(st.finalbody, scope, path)
        elif st.__class__.__name__ == "Match":
            self._walk_walrus(st.subject, scope, path)
            for i, case in enumerate(st.cases):
                self._build_body(case.body, scope, self._branch(path, st, i))
        elif isinstance(st, ast.Expr):
            self._walk_walrus(st.value, scope, path)

    def _arg_nodes(self, args):
        out = list(getattr(args, "posonlyargs", [])) + list(args.args)
        if args.vararg:
            out.append(args.vararg)
        out += list(args.kwonlyargs)
        if args.kwarg:
            out.append(args.kwarg)
        return out

    def _walk_walrus(self, node, scope, path=()):
        if node is None:
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                self._bind(scope, sub.target.id, sub.lineno,
                           ("expr", sub.value, scope), sub.target.col_offset,
                           sub, path)

    def _bind_target(self, tgt, value, lineno, scope, path=(), stmt=None):
        if isinstance(tgt, ast.Name):
            res = ("expr", value, scope) if value is not None else ("unknown",)
            self._bind(scope, tgt.id, lineno, res, tgt.col_offset, stmt, path)
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            elts = tgt.elts
            vals = None
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(elts):
                vals = value.elts
            for i, el in enumerate(elts):
                self._bind_target(el, vals[i] if vals else None, lineno, scope,
                                  path, stmt)
        elif isinstance(tgt, ast.Starred):
            self._bind_target(tgt.value, None, lineno, scope, path, stmt)

    def _build_import_from(self, st, scope, path=()):
        modname = "." * (st.level or 0) + (st.module or "")
        for al in st.names:
            if al.name == "*":
                recv = self.resolve_module(modname)
                if recv is None:
                    continue
                for name, val in public_pairs(recv):
                    self._bind(scope, name, st.lineno,
                               ("value", val if val is not None else UNKNOWN),
                               getattr(al, "col_offset", st.col_offset), st, path)
            else:
                bound = al.asname or al.name
                col = getattr(al, "col_offset", st.col_offset)
                if al.asname:
                    end = getattr(al, "end_col_offset", None)
                    if end is not None:
                        col = end - len(al.asname)
                self._bind(scope, bound, st.lineno, ("from", modname, al.name),
                           col, st, path)

    # -- stubs -------------------------------------------------------------

    def stub(self):
        """Analysis of this module's `.pyi` stub, or None."""
        if self._stub is MISSING:
            self._stub = None
            found = stub_path_for(self.filepath)
            if found:
                self._stub = analyzer_for_path(found)
        return self._stub

    def node_path(self, node):
        """Names leading from the module scope down to a def/class node."""
        scope = self.func_scopes.get(node) or self.class_scopes.get(node)
        if scope is None:
            return None
        parts = [getattr(node, "name", None)]
        sc = scope.parent
        while sc is not None and sc.kind != "module":
            parts.append(getattr(sc.node, "name", None))
            sc = sc.parent
        if any(p is None for p in parts):
            return None
        parts.reverse()
        return tuple(parts)

    def nodes_at_path(self, parts):
        """def/class nodes reachable at a dotted path inside this analysis."""
        scopes = [self.module]
        for i, name in enumerate(parts):
            found = []
            for sc in scopes:
                for b in sc.bindings.get(name, []):
                    if b.res[0] in ("func", "class"):
                        found.append(b.res[1])
            if not found:
                return []
            if i == len(parts) - 1:
                return found
            scopes = []
            for node in found:
                sub = self.class_scopes.get(node) or self.func_scopes.get(node)
                if sub is not None:
                    scopes.append(sub)
            if not scopes:
                return []
        return []

    def stub_nodes(self, node):
        """The stub's counterpart(s) of a def/class node (several when overloaded)."""
        key = id(node)
        if key in self._stub_node_cache:
            return self._stub_node_cache[key]
        self._stub_node_cache[key] = []
        stub = self.stub()
        out = []
        if stub is not None:
            parts = self.node_path(node)
            if parts:
                want = ast.ClassDef if isinstance(node, ast.ClassDef) else \
                    (ast.FunctionDef, ast.AsyncFunctionDef)
                out = [n for n in stub.nodes_at_path(parts) if isinstance(n, want)]
                over = [n for n in out if is_overload(n)]
                if over:
                    out = over
        self._stub_node_cache[key] = out
        return out

    # -- module resolution -------------------------------------------------

    def resolve_module(self, modname):
        if modname in self._module_cache:
            return self._module_cache[modname]
        self._module_cache[modname] = None
        recv = self._resolve_module_uncached(modname)
        self._module_cache[modname] = recv
        return recv

    def _resolve_module_uncached(self, modname):
        """Project root first, then the modules of the target runtime (spec)."""
        if not modname:
            return None
        if modname.startswith("."):
            return self._resolve_relative(modname)
        local = find_project_module(ROOT[0], modname)
        if local is not None:
            return local
        mod = safe_import(modname)
        if mod is not None:
            return PyRecv(mod)
        return None

    def _resolve_relative(self, modname):
        """`.mod` / `..pkg.mod`: relative to this file, never above the root."""
        level = len(modname) - len(modname.lstrip("."))
        rel = modname[level:]
        base = self.dirname
        for _ in range(level - 1):
            base = os.path.dirname(base)
        if not within_root(base):
            return None
        if not rel:
            return package_recv_for_dir(base)
        return find_project_module(base, rel)

    # -- values ------------------------------------------------------------

    def value_of(self, binding):
        vals = self.values_of(binding)
        return vals[0] if vals else UNKNOWN

    def values_of(self, binding):
        """All values a binding can hold (a union when branches disagree)."""
        if binding.analyzer is not None and binding.analyzer is not self:
            return binding.analyzer.values_of(binding)
        if binding._values is not None:
            return binding._values
        if binding._busy:
            return []
        binding._busy = True
        try:
            vals = self._compute_values(binding)
        except Exception:
            vals = []
        finally:
            binding._busy = False
        vals = [v for v in vals if v is not None]
        binding._values = vals
        return vals

    def _compute_values(self, binding):
        res = binding.res
        tag = res[0]
        if tag == "func":
            return [self.func_value(res[1])]
        if tag == "class":
            return [self.class_value(res[1])]
        if tag == "param":
            return self._param_values(binding, res)
        if tag == "mod":
            return [self.module_value(res[1], binding.name)]
        if tag == "value":
            return [res[1]]
        if tag == "expr":
            return self.resolve_multi(res[2], res[1])
        if tag == "annotation":
            return self.annotation_values(res[2], res[1])
        if tag == "from":
            return self._from_import_values(res[1], res[2], binding.name)
        return []

    def _param_values(self, binding, res):
        """A parameter: kind stays `param`, but it may still infer a type (T22)."""
        annotation, dscope = res[1], res[2]
        funcnode = res[3] if len(res) > 3 else None
        index = res[4] if len(res) > 4 else -1
        if annotation is not None:
            vals = self.annotation_values(dscope, annotation)
            if vals:
                return [Value("param", None, v.recv, v.defn) for v in vals]
        # Stub annotations take precedence over anything inferred (spec).
        if annotation is None and funcnode is not None:
            vals = self._stub_param_values(funcnode, binding.name)
            if vals:
                return [Value("param", None, v.recv, v.defn) for v in vals]
        if index == 0 and funcnode is not None:
            recv = self._implicit_self_recv(funcnode, dscope)
            if isinstance(recv, ClassRecv):
                inst = self.instance_value(recv.node) if recv.instance \
                    else self.class_value(recv.node)
                return [Value("param", None, recv, inst.defn)]
            if recv is not None:
                return [Value("param", None, recv, None)]
        if DYNAMIC[0] and annotation is None and funcnode is not None and index >= 0:
            vals = self._dynamic_param_values(funcnode, dscope, binding.name, index)
            if vals:
                return [Value("param", None, v.recv, v.defn) for v in vals]
        return [Value("param", None, None, None)]

    def _stub_param_values(self, funcnode, name):
        """The type a stub declares for one parameter of `funcnode`."""
        stub = self.stub()
        for node in self.stub_nodes(funcnode):
            for arg in stub._arg_nodes(node.args):
                if arg.arg != name or arg.annotation is None:
                    continue
                scope = stub.func_scopes.get(node)
                return stub.annotation_values(
                    scope.parent if scope is not None else stub.module,
                    arg.annotation)
        return []

    # -- call-site parameter inference (spec: Dynamic Parameter Inference) --

    def call_sites(self, funcnode):
        """Calls of `funcnode` in *this* file: [(Call node, called via attribute)]."""
        key = id(funcnode)
        cached = self._call_site_cache.get(key)
        if cached is not None:
            return cached
        self._call_site_cache[key] = []
        target = getattr(funcnode, "name", None)
        out = []
        if target:
            for node in ast.walk(self.tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name):
                    via_attr = False
                elif isinstance(func, ast.Attribute):
                    via_attr = True
                else:
                    continue
                if (func.id if not via_attr else func.attr) != target:
                    continue
                scope = self.scope_at(node.lineno, node.col_offset)
                for val in self.resolve_multi(scope, func, node.lineno):
                    if isinstance(val.recv, FuncRecv) and val.recv.node is funcnode:
                        out.append((node, via_attr))
                        break
        self._call_site_cache[key] = out
        return out

    def _dynamic_param_values(self, funcnode, dscope, name, index):
        """Types a parameter takes at the call sites found in this file."""
        key = (id(funcnode), name)
        if key in self._dyn_busy:
            return []
        self._dyn_busy.add(key)
        try:
            args = funcnode.args
            positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
            bound = (dscope is not None and dscope.kind == "class"
                     and "staticmethod" not in decorator_names(funcnode))
            out = []
            for call, via_attr in self.call_sites(funcnode):
                shift = 1 if (bound and via_attr) else 0
                arg = None
                for kw in call.keywords:
                    if kw.arg == name:
                        arg = kw.value
                if arg is None and index < len(positional):
                    slot = index - shift
                    if 0 <= slot < len(call.args) and not any(
                            isinstance(a, ast.Starred) for a in call.args[:slot + 1]):
                        arg = call.args[slot]
                if arg is None:
                    continue
                scope = self.scope_at(call.lineno, call.col_offset)
                out.extend(self.resolve_multi(scope, arg, call.lineno))
            return out
        except Exception:
            return []
        finally:
            self._dyn_busy.discard(key)

    def annotation_values(self, scope, node):
        """`x: T` -- the values an annotation stands for (instances of T)."""
        out = []
        for val in self.resolve_multi(scope, node):
            if val.kind == "class" and val.recv is not None:
                out.extend(val.recv.call_multi())
            elif val.kind == "instance":
                out.append(val)
        if not out and isinstance(node, ast.Constant) and node.value is None:
            out.append(none_value())
        return out

    def func_value(self, node):
        return Value("function", None, FuncRecv(self, node), self.func_defn(node))

    def class_value(self, node):
        return Value("class", node.name, ClassRecv(self, node, False),
                     self.class_defn(node))

    def instance_value(self, node):
        return Value("instance", node.name, ClassRecv(self, node, True),
                     as_instance_defn(self.class_defn(node), node.name))

    def module_value(self, modname, bound_name=None):
        recv = self.resolve_module(modname)
        name = bound_name or modname.split(".")[-1]
        return Value("module", modname, recv, self.module_defn(modname, recv, name))

    # -- definitions -------------------------------------------------------

    def qualname(self, scope, name):
        """Dotted name of `name` defined in `scope`: module.Class.method."""
        parts = []
        sc = scope
        while sc is not None and sc.kind != "module":
            own = getattr(sc.node, "name", None)
            if own:
                parts.append(own)
            sc = sc.parent
        parts.reverse()
        return ".".join([self.module_name] + parts + [name])

    def _params_text(self, node):
        try:
            return ast.unparse(node.args)
        except Exception:
            return "..."

    def func_defn(self, node):
        scope = self.func_scopes.get(node)
        parent = scope.parent if scope is not None else self.module
        return new_defn(node.name, "function", self.qualname(parent, node.name),
                        self.rel_path, node.lineno, self.name_col(node, node.name),
                        "def %s(%s)" % (node.name, self._params_text(node)),
                        docstring_of(node))

    def class_defn(self, node):
        scope = self.class_scopes.get(node)
        parent = scope.parent if scope is not None else self.module
        return new_defn(node.name, "class", self.qualname(parent, node.name),
                        self.rel_path, node.lineno, self.name_col(node, node.name),
                        "class %s" % node.name, docstring_of(node))

    def module_defn(self, modname, recv, bound_name=None):
        name = bound_name or modname.split(".")[-1]
        if isinstance(recv, StaticModuleRecv):
            return recv.module_defn(name)
        if isinstance(recv, PyRecv):
            return live_defn(recv.obj, "module", getattr(recv.obj, "__name__", name))
        # Unresolvable module: no definition to report (spec: empty results).
        return None

    def stmt_text(self, node):
        """Source text of a statement / expression, as written."""
        if node is None:
            return ""
        lineno = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if lineno is None:
            return ""
        if end is None or end == lineno:
            if 1 <= lineno <= len(self.lines):
                text = self.lines[lineno - 1]
                col = getattr(node, "col_offset", None)
                endcol = getattr(node, "end_col_offset", None)
                if col is not None and endcol is not None:
                    return text[col:endcol].strip()
                return text.strip()
            return ""
        chunk = []
        for i in range(lineno, min(end, len(self.lines)) + 1):
            chunk.append(self.lines[i - 1])
        return "\n".join(chunk).strip()

    def header_text(self, node):
        lineno = getattr(node, "lineno", 0)
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1].strip()
        return ""

    def binding_defn(self, binding):
        """Where a name is bound -- the answer to `goto`."""
        if binding.analyzer is not None and binding.analyzer is not self:
            return binding.analyzer.binding_defn(binding)
        res = binding.res
        tag = res[0]
        if tag == "func":
            return self.func_defn(res[1])
        if tag == "class":
            return self.class_defn(res[1])
        owner = binding.owner or self.module
        full = self.qualname(owner, binding.name)
        if tag == "param":
            return new_defn(binding.name, "param", full, self.rel_path,
                            binding.lineno, binding.col,
                            "param %s" % binding.name, "")
        if tag in ("mod", "from", "value"):
            kind = "statement"
            vals = self.values_of(binding)
            if vals and vals[0].kind in ("module", "class", "function", "instance"):
                kind = vals[0].kind
            return new_defn(binding.name, kind, full, self.rel_path,
                            binding.lineno, binding.col,
                            self.header_text(binding.stmt), "")
        description = "statement"
        if tag == "expr" and res[1] is not None:
            description = self.stmt_text(res[1]) or "statement"
        elif binding.stmt is not None:
            if isinstance(binding.stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                description = self.stmt_text(binding.stmt) or "statement"
            else:
                description = self.header_text(binding.stmt) or "statement"
        return new_defn(binding.name, "statement", full, self.rel_path,
                        binding.lineno, binding.col, description, "")

    def followed_defns(self, binding, seen=None):
        """Where an import binding ultimately points (`--follow-imports`).

        Returns [] when the chain leaves the project (stdlib, third-party) or
        dead-ends, which is the caller's cue to fall back to the import site.
        """
        if binding.analyzer is not None and binding.analyzer is not self:
            return binding.analyzer.followed_defns(binding, seen)
        if seen is None:
            seen = set()
        key = (self.filepath, binding.name, binding.lineno, binding.col)
        if key in seen:
            return []
        seen.add(key)
        res = binding.res
        tag = res[0]
        if tag == "mod":
            recv = self.resolve_module(res[1])
            if isinstance(recv, StaticModuleRecv):
                return [d for d in [recv.module_defn(binding.name)] if d]
            return []
        if tag == "from":
            return self._followed_from(res[1], res[2], binding.name, seen)
        if tag == "value":
            # A star-imported name: its value already carries the definition.
            d = resolve_defn(res[1].defn) if res[1] is not None else None
            return [d] if is_project_defn(d) else []
        return []

    def _followed_from(self, modname, name, bound_name, seen):
        recv = self.resolve_module(modname)
        if not isinstance(recv, StaticModuleRecv):
            return []
        out = []
        for b in recv.get_bindings(name):
            owner = b.analyzer or self
            if b.res[0] in ("mod", "from", "value"):
                # Another import: keep following. A dead end here fails the whole
                # chain, so the fallback is the import site in the *current* file.
                out.extend(owner.followed_defns(b, seen))
                continue
            d = owner.binding_defn(b)
            if d is not None:
                out.append(d)
        if out:
            return out
        sub_recv = self.resolve_module(join_module(modname, name))
        if isinstance(sub_recv, StaticModuleRecv):
            return [d for d in [sub_recv.module_defn(bound_name or name)] if d]
        return []

    def _implicit_self_recv(self, funcnode, defining_scope):
        """`self` / `cls` in a method refer to the enclosing class."""
        if defining_scope is None or defining_scope.kind != "class":
            return None
        classdef = defining_scope.node
        decorators = set()
        for dec in getattr(funcnode, "decorator_list", []):
            if isinstance(dec, ast.Name):
                decorators.add(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.add(dec.attr)
        if "staticmethod" in decorators:
            return None
        if "classmethod" in decorators:
            return ClassRecv(self, classdef, False)
        return ClassRecv(self, classdef, True)

    def _from_import_values(self, modname, name, bound_name=None):
        recv = self.resolve_module(modname)
        if recv is None:
            return []
        vals = recv.get_values(name)
        if vals:
            return vals
        sub = join_module(modname, name)
        if self.resolve_module(sub) is not None:
            return [self.module_value(sub, bound_name or name)]
        return []

    def _from_import_value(self, modname, name):
        vals = self._from_import_values(modname, name)
        return vals[0] if vals else UNKNOWN

    # -- return types ------------------------------------------------------

    def return_values(self, node):
        """Static return type(s) of a function: its `return` statements."""
        key = id(node)
        if key in self._returns_busy:
            return []
        self._returns_busy.add(key)
        try:
            stubbed = self._stub_return_values(node)
            if stubbed:
                return stubbed
            scope = self.func_scopes.get(node, self.module)
            returns = []
            self._collect_returns(node.body, returns)
            out = []
            for ret in returns:
                if ret.value is None:
                    out.append(none_value())
                else:
                    out.extend(self.resolve_multi(scope, ret.value))
            if not returns:
                ann = getattr(node, "returns", None)
                if ann is not None:
                    vals = self.annotation_values(scope.parent or self.module, ann)
                    if vals:
                        return vals
                return [none_value()]
            if not out:
                ann = getattr(node, "returns", None)
                if ann is not None:
                    out = self.annotation_values(scope.parent or self.module, ann)
            return out
        except Exception:
            return []
        finally:
            self._returns_busy.discard(key)

    def _stub_return_values(self, node):
        """Return types declared by the module's stub (they win over inference)."""
        stub = self.stub()
        out = []
        for snode in self.stub_nodes(node):
            ann = getattr(snode, "returns", None)
            if ann is None:
                continue
            scope = stub.func_scopes.get(snode)
            out.extend(stub.annotation_values(
                scope.parent if scope is not None else stub.module, ann))
        return out

    def _collect_returns(self, body, out):
        for st in body or []:
            if isinstance(st, ast.Return):
                out.append(st)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            else:
                for field in ("body", "orelse", "finalbody"):
                    self._collect_returns(getattr(st, field, None), out)
                for handler in getattr(st, "handlers", []) or []:
                    self._collect_returns(getattr(handler, "body", None), out)
                for case in getattr(st, "cases", []) or []:
                    self._collect_returns(getattr(case, "body", None), out)

    # -- expressions -------------------------------------------------------

    def resolve_expr(self, scope, node, line=None):
        """Resolve an expression to a Value (or None when nothing is known)."""
        vals = self.resolve_multi(scope, node, line)
        return vals[0] if vals else None

    def resolve_multi(self, scope, node, line=None):
        if node is None:
            return []
        try:
            vals = self._resolve_multi(scope, node, line)
        except Exception:
            return []
        return [v for v in (vals or []) if v is not None]

    def _resolve_multi(self, scope, node, line=None):
        if isinstance(node, ast.Name):
            return self.name_values(scope, node.id, line)
        if isinstance(node, ast.Attribute):
            out = []
            for base in self.resolve_multi(scope, node.value, line):
                if base.recv is None:
                    continue
                out.extend(base.recv.get_values(node.attr))
            return out
        if isinstance(node, ast.Call):
            out = []
            for func in self.resolve_multi(scope, node.func, line):
                if func.recv is None:
                    continue
                out.extend(func.recv.call_multi())
            return out
        if isinstance(node, ast.Constant):
            return [constant_value(node.value)]
        if isinstance(node, ast.JoinedStr):
            return [builtin_instance(str)]
        if isinstance(node, (ast.List, ast.ListComp)):
            return [builtin_instance(list)]
        if isinstance(node, ast.Tuple):
            return [builtin_instance(tuple)]
        if isinstance(node, (ast.Set, ast.SetComp)):
            return [builtin_instance(set)]
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return [builtin_instance(dict)]
        if isinstance(node, ast.GeneratorExp):
            return []
        if isinstance(node, ast.Lambda):
            return [Value("function")]
        if isinstance(node, ast.NamedExpr):
            return self.resolve_multi(scope, node.value, line)
        if isinstance(node, ast.IfExp):
            return (self.resolve_multi(scope, node.body, line)
                    + self.resolve_multi(scope, node.orelse, line))
        if isinstance(node, ast.BoolOp):
            out = []
            for value in node.values:
                out.extend(self.resolve_multi(scope, value, line))
            return out
        if isinstance(node, ast.Await):
            return self.resolve_multi(scope, node.value, line)
        if isinstance(node, ast.Compare):
            return [builtin_instance(bool)]
        return []

    def name_values(self, scope, name, line=None):
        """Values of a bare name at `line`, honouring flow narrowing (T30)."""
        bindings = self.lookup_all(scope, name, line)
        base = []
        for b in bindings:
            base.extend(self.values_of(b))
        if not bindings:
            obj = getattr(_builtins, name, MISSING)
            if obj is not MISSING:
                base = [value_from_obj(name, obj)]
        if line is not None:
            narrowed = self.narrow(scope, name, line, base)
            if narrowed is not None:
                return narrowed
        return base

    # -- flow narrowing ----------------------------------------------------

    def narrow(self, scope, name, line, base):
        constraints = self.constraints_for(scope, name, line)
        if not constraints:
            return None
        vals = list(base)
        for kind, payload, cscope in constraints:
            if kind == "isinstance":
                new = self._instances_of(cscope or scope, payload, None)
                if new:
                    vals = new
            elif kind == "not_isinstance":
                new = self._instances_of(cscope or scope, payload, None)
                names = set(v.typename for v in new)
                kept = [v for v in vals if v.typename not in names]
                if kept:
                    vals = kept
            elif kind == "is_none":
                vals = [none_value()]
            elif kind == "not_none":
                vals = [v for v in vals if not is_none_value(v)]
        return vals

    def _instances_of(self, scope, node, line):
        out = []
        if isinstance(node, (ast.Tuple, ast.List)):
            # isinstance(x, (A, B)) narrows to the union of A and B.
            for elt in node.elts:
                out.extend(self._instances_of(scope, elt, line))
            return out
        for val in self.resolve_multi(scope, node, line):
            if val.kind == "class" and val.recv is not None:
                out.extend(val.recv.call_multi())
            elif val.kind == "instance":
                out.append(val)
        return out

    def constraints_for(self, scope, name, line):
        """Narrowing facts about `name` that hold at `line`."""
        found = []
        for st in ast.walk(self.tree):
            if isinstance(st, ast.If):
                if _body_contains(st.body, line):
                    found.append((st.lineno, st.test, True))
                elif _body_contains(st.orelse, line):
                    found.append((st.lineno, st.test, False))
            elif isinstance(st, ast.While) and _body_contains(st.body, line):
                found.append((st.lineno, st.test, True))
            elif isinstance(st, ast.Assert) and st.lineno < line:
                # An assertion narrows the rest of the scope it sits in.
                if self.scope_at(st.lineno, st.col_offset) is scope:
                    found.append((st.lineno, st.test, True))
        out = []
        for _lineno, test, positive in sorted(found, key=lambda t: t[0]):
            for cname, kind, payload in narrow_conditions(test, positive):
                if cname == name:
                    out.append((kind, payload, scope))
        return out

    # -- lookups -----------------------------------------------------------

    def _pick(self, blist, line):
        if line is None:
            return blist[-1] if blist else None
        chosen = None
        for b in blist:
            if b.lineno <= line:
                chosen = b
        return chosen

    def lookup(self, scope, name, line=None):
        """Find the binding for `name` following the scope chain (T8, T17)."""
        sc = scope
        local = True
        while sc is not None:
            if sc.kind == "class" and not local:
                sc = sc.parent
                continue
            use_line = line if (local or sc.kind == "module") else None
            blist = sc.bindings.get(name)
            if blist:
                b = self._pick(blist, use_line)
                if b is not None:
                    return b
            local = False
            sc = sc.parent
        return None

    def lookup_all(self, scope, name, line=None):
        """Every binding of `name` that can be in effect at the cursor (T27)."""
        sc = scope
        local = True
        while sc is not None:
            if sc.kind == "class" and not local:
                sc = sc.parent
                continue
            use_line = line if (local or sc.kind == "module") else None
            blist = sc.bindings.get(name)
            if blist:
                live = live_bindings(blist, use_line)
                if live:
                    return live
            local = False
            sc = sc.parent
        return []

    def visible(self, scope, line):
        """All visible bindings at the cursor, nearest scope winning."""
        out = {}
        sc = scope
        local = True
        while sc is not None:
            if sc.kind == "class" and not local:
                sc = sc.parent
                continue
            use_line = line if (local or sc.kind == "module") else None
            for name, blist in sc.bindings.items():
                if name in out:
                    continue
                b = self._pick(blist, use_line)
                if b is not None:
                    out[name] = b
            local = False
            sc = sc.parent
        return out

    def scope_at(self, line, col):
        scope = self.module
        while True:
            for child in scope.children:
                if child.contains(line, col):
                    scope = child
                    break
            else:
                return scope

    # -- classes -----------------------------------------------------------

    def linearize(self, classdef, seen=None):
        if seen is None:
            seen = []
        if classdef in seen:
            return seen
        seen.append(classdef)
        scope = self.class_scopes.get(classdef)
        parent = scope.parent if scope is not None else self.module
        for base in classdef.bases:
            node = None
            if isinstance(base, ast.Name):
                b = self.lookup(parent, base.id)
                if b is not None and b.res[0] == "class":
                    node = b.res[1]
            if node is not None:
                self.linearize(node, seen)
        return seen

    def class_attrs(self, classdef, instance):
        key = (id(classdef), bool(instance))
        cached = self._class_attr_cache.get(key)
        if cached is not None:
            return cached
        out = {}
        self._class_attr_cache[key] = out
        for name, blist in self.class_attr_bindings(classdef, instance).items():
            if not blist:
                continue
            vals = []
            for b in blist:
                vals.extend(b.analyzer.values_of(b) if b.analyzer else self.values_of(b))
            out[name] = vals[0] if vals else UNKNOWN
        stub = self.stub()
        for snode in self.stub_nodes(classdef)[:1]:
            # Stub class attributes win over -- and add to -- the runtime ones.
            out.update(stub.class_attrs(snode, instance))
        return out

    def class_attr_bindings(self, classdef, instance):
        """name -> live bindings, walking the class's bases (and `__init__`)."""
        key = (id(classdef), bool(instance))
        cached = self._class_binding_cache.get(key)
        if cached is not None:
            return cached
        out = {}
        self._class_binding_cache[key] = out
        for cls in self.linearize(classdef):
            scope = self.class_scopes.get(cls)
            if scope is not None:
                for name, blist in scope.bindings.items():
                    if name not in out:
                        out[name] = live_bindings(blist, None) or [blist[-1]]
            if instance:
                for name, blist in self.init_attr_bindings(cls).items():
                    if name not in out:
                        out[name] = blist
        stub = self.stub()
        for snode in self.stub_nodes(classdef)[:1]:
            # `goto` prefers the runtime source; stub-only members still resolve.
            for name, blist in stub.class_attr_bindings(snode, instance).items():
                out.setdefault(name, blist)
        return out

    def init_attrs(self, classdef):
        out = {}
        for name, blist in self.init_attr_bindings(classdef).items():
            vals = []
            for b in blist:
                vals.extend(self.values_of(b))
            out[name] = vals[0] if vals else UNKNOWN
        return out

    def init_attr_bindings(self, classdef):
        """`self.x = ...` assignments in the class's own __init__ (T9)."""
        key = id(classdef)
        cached = self._init_attr_cache.get(key)
        if cached is not None:
            return cached
        out = {}
        self._init_attr_cache[key] = out
        owner = self.class_scopes.get(classdef, self.module)
        for st in classdef.body:
            if not isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if st.name != "__init__":
                continue
            args = self._arg_nodes(st.args)
            selfname = args[0].arg if args else "self"
            scope = self.func_scopes.get(st, self.module)
            collected = []
            self._collect_self_attrs(st.body, (), selfname, scope, collected)
            for tgt, value, stmt, path in collected:
                b = Binding(tgt.attr, stmt.lineno,
                            ("expr", value, scope) if value is not None else ("unknown",),
                            scope, col=_attr_col(tgt), stmt=stmt, path=path,
                            analyzer=self, owner=owner)
                out.setdefault(tgt.attr, []).append(b)
        for name, blist in list(out.items()):
            out[name] = live_bindings(blist, None) or blist
        return out

    def _collect_self_attrs(self, body, path, selfname, scope, out):
        for st in body or []:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            targets, value = [], None
            if isinstance(st, ast.Assign):
                targets, value = st.targets, st.value
            elif isinstance(st, ast.AnnAssign):
                targets, value = [st.target], st.value
                if value is None and st.annotation is not None:
                    value = None
            for tgt in targets:
                if (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == selfname):
                    out.append((tgt, value, st, path))
            if isinstance(st, ast.If):
                self._collect_self_attrs(st.body, path + ((id(st), 0),), selfname, scope, out)
                self._collect_self_attrs(st.orelse, path + ((id(st), 1),), selfname, scope, out)
            elif isinstance(st, (ast.For, ast.AsyncFor, ast.While)):
                self._collect_self_attrs(st.body, path + ((id(st), 0),), selfname, scope, out)
                self._collect_self_attrs(st.orelse, path + ((id(st), 1),), selfname, scope, out)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                self._collect_self_attrs(st.body, path, selfname, scope, out)
            elif isinstance(st, ast.Try) or st.__class__.__name__ == "TryStar":
                self._collect_self_attrs(st.body, path + ((id(st), 0),), selfname, scope, out)
                for i, handler in enumerate(st.handlers):
                    self._collect_self_attrs(handler.body, path + ((id(st), 2 + i),),
                                             selfname, scope, out)
                self._collect_self_attrs(st.orelse, path + ((id(st), 1),), selfname, scope, out)
                self._collect_self_attrs(st.finalbody, path, selfname, scope, out)


def _attr_col(node):
    end = getattr(node, "end_col_offset", None)
    if end is not None:
        return max(0, end - len(node.attr))
    return getattr(node, "col_offset", 0)


def _body_contains(body, line):
    if not body:
        return False
    start = getattr(body[0], "lineno", None)
    end = getattr(body[-1], "end_lineno", None) or getattr(body[-1], "lineno", None)
    if start is None or end is None:
        return False
    return start <= line <= end


def narrow_conditions(test, positive):
    """Facts a boolean test implies about names (isinstance / is None)."""
    out = []
    if test is None:
        return out
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return narrow_conditions(test.operand, not positive)
    if isinstance(test, ast.BoolOp):
        if (isinstance(test.op, ast.And) and positive) or \
           (isinstance(test.op, ast.Or) and not positive):
            for value in test.values:
                out.extend(narrow_conditions(value, positive))
        return out
    if isinstance(test, ast.Call):
        func = test.func
        fname = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        if fname == "isinstance" and len(test.args) == 2 \
                and isinstance(test.args[0], ast.Name):
            kind = "isinstance" if positive else "not_isinstance"
            out.append((test.args[0].id, kind, test.args[1]))
        return out
    if isinstance(test, ast.Compare) and len(test.ops) == 1 \
            and isinstance(test.left, ast.Name):
        op = test.ops[0]
        other = test.comparators[0]
        if isinstance(other, ast.Constant) and other.value is None:
            if isinstance(op, ast.Is):
                out.append((test.left.id, "is_none" if positive else "not_none", None))
            elif isinstance(op, ast.IsNot):
                out.append((test.left.id, "not_none" if positive else "is_none", None))
    return out


# ---------------------------------------------------------------------------
# tolerant parsing (T20)
# ---------------------------------------------------------------------------


BLOCK_HEADERS = ("def ", "async def ", "class ", "if ", "elif ", "else", "for ",
                 "async for ", "while ", "try", "except", "finally", "with ", "async with ")


def _is_block_header(stripped):
    return any(stripped == kw.strip() or stripped.startswith(kw) for kw in BLOCK_HEADERS)


def robust_parse(text):
    """Parse as much as possible: repair offending lines in place, keeping line numbers."""
    lines = text.split("\n")
    work = list(lines)
    attempts = {}
    for _ in range(300):
        try:
            return ast.parse("\n".join(work)), lines
        except SyntaxError as exc:
            idx = (exc.lineno or 1) - 1
            if idx >= len(work):
                idx = len(work) - 1
            if idx < 0:
                break
            stage = attempts.get(idx, 0)
            attempts[idx] = stage + 1
            raw = work[idx]
            stripped = raw.strip()
            if stage == 0 and _is_block_header(stripped) and not stripped.endswith(":"):
                work[idx] = raw.rstrip() + ":"
            elif stage <= 1:
                work[idx] = " " * line_indent(raw) + "pass"
            elif stage == 2:
                work[idx] = ""
            else:
                work = work[:idx]
                if not work:
                    break
        except Exception:
            break
    return ast.parse(""), lines


# ---------------------------------------------------------------------------
# cursor context
# ---------------------------------------------------------------------------


def scan_prefix(text, col):
    """Scan backwards from the cursor to the start of the current identifier."""
    i = col
    while i > 0 and is_ident_char(text[i - 1]):
        i -= 1
    return text[i:col], i


def scan_receiver(text):
    """Return the source of the atom (plus trailing chain) ending at `text`'s end."""
    i = len(text)
    while i > 0 and text[i - 1] in " \t":
        i -= 1
    end = i
    if i == 0:
        return None
    while True:
        ch = text[i - 1]
        if ch in ")]}":
            opener = {")": "(", "]": "[", "}": "{"}[ch]
            depth = 0
            j = i
            while j > 0:
                c = text[j - 1]
                if c in ")]}":
                    depth += 1
                elif c in "([{":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            if depth != 0 or j == 0 and text[0] not in "([{":
                return None
            if text[j - 1] != opener:
                return None
            i = j - 1
            if i > 0 and (is_ident_char(text[i - 1]) or text[i - 1] in ")]}\"'"):
                continue
        elif is_ident_char(ch):
            j = i
            while j > 0 and is_ident_char(text[j - 1]):
                j -= 1
            i = j
        elif ch in "'\"":
            quote = ch
            j = i - 1
            k = j
            found = False
            while k > 0:
                if text[k - 1] == quote and (k - 1 == 0 or text[k - 2] != "\\"):
                    found = True
                    break
                k -= 1
            if not found:
                return None
            i = k - 1
            while i > 0 and text[i - 1].isalpha():
                i -= 1
        else:
            break
        if i > 0 and text[i - 1] == ".":
            i -= 1
            continue
        break
    expr = text[i:end].strip()
    if not expr:
        return None
    return expr


FROM_IMPORT_RE = re.compile(r"^\s*from\s+(?P<mod>[.\w]*)\s+import\s+(?P<rest>.*)$")
FROM_RE = re.compile(r"^\s*from\s+(?P<mod>[.\w]*)$")
IMPORT_RE = re.compile(r"^\s*import\s+(?P<rest>.*)$")
IDENT_RE = re.compile(r"^\w*$")
DOTTED_RE = re.compile(r"^[.\w]*$")


def _module_ctx(dotted):
    """Completing a dotted module reference: its parent and the typed prefix."""
    head, dot, prefix = dotted.rpartition(".")
    if not dot:
        return ("modules", None, prefix)
    return ("submodules", head + dot if head == "" else head, prefix)


def import_context(head):
    """Classify the cursor inside an `import` statement, or None if not in one.

    ("modules", None, prefix)        -- top-level module/package names
    ("submodules", parent, prefix)   -- names inside package `parent`
    ("from", module, prefix)         -- names inside module `module`
    ("none", None, "")               -- an import statement with nothing to offer
    """
    match = FROM_IMPORT_RE.match(head)
    if match:
        rest = match.group("rest")
        seg = rest.split(",")[-1].lstrip("( \t")
        if not IDENT_RE.match(seg) or re.search(r"\bas\s", seg):
            return ("none", None, "")
        return ("from", match.group("mod"), seg)
    match = FROM_RE.match(head)
    if match:
        return _module_ctx(match.group("mod"))
    match = IMPORT_RE.match(head)
    if match:
        seg = match.group("rest").split(",")[-1].lstrip(" \t")
        if not DOTTED_RE.match(seg) or re.search(r"\bas\s", seg):
            return ("none", None, "")
        return _module_ctx(seg)
    return None


def cursor_context(line_text, col):
    """Return (kind, prefix, receiver_source) for the cursor."""
    prefix, start = scan_prefix(line_text, col)
    if start > 0 and line_text[start - 1] == ".":
        return "attr", prefix, scan_receiver(line_text[:start - 1])
    return "name", prefix, None


# ---------------------------------------------------------------------------
# matching / ordering / rendering
# ---------------------------------------------------------------------------


def matches(name, prefix, fuzzy):
    if not prefix:
        return True
    low_name = name.lower()
    low_prefix = prefix.lower()
    if not fuzzy:
        return low_name.startswith(low_prefix)
    pos = 0
    for ch in low_prefix:
        pos = low_name.find(ch, pos)
        if pos < 0:
            return False
        pos += 1
    return True


def name_group(name):
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


def make_item(name, kind, typename, prefix):
    return {
        "name": name,
        "complete": name[len(prefix):],
        "type": kind,
        "description": describe(kind, name, typename),
    }


def sort_items(items):
    return sorted(items, key=lambda it: (3 if it["type"] == "keyword" else name_group(it["name"]),
                                         it["name"].lower(), it["name"]))


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------


def name_completions(analyzer, scope, line, prefix, fuzzy):
    items = []
    seen = set()
    for name, binding in analyzer.visible(scope, line).items():
        seen.add(name)
        if not matches(name, prefix, fuzzy):
            continue
        val = analyzer.value_of(binding)
        items.append(make_item(name, val.kind, val.typename, prefix))
    for name in dir(_builtins):
        if name in seen:
            continue
        if not matches(name, prefix, fuzzy):
            continue
        val = value_from_obj(name, getattr(_builtins, name, None))
        items.append(make_item(name, val.kind, val.typename, prefix))
    for kw in keyword.kwlist:
        if matches(kw, prefix, fuzzy):
            items.append(make_item(kw, "keyword", None, prefix))
    return items


def attribute_completions(analyzer, scope, line, receiver_src, prefix, fuzzy):
    if not receiver_src:
        return []
    try:
        node = ast.parse(receiver_src, mode="eval").body
    except SyntaxError:
        return []
    vals = analyzer.resolve_multi(scope, node, line)
    items = []
    seen = set()
    # A union receiver contributes the attributes of every possible type.
    for val in vals:
        if val is None or val.recv is None:
            continue
        for name, attr in val.recv.attributes():
            if name in seen:
                continue
            seen.add(name)
            if not matches(name, prefix, fuzzy):
                continue
            attr = attr or UNKNOWN
            items.append(make_item(name, attr.kind, attr.typename, prefix))
    return items


def top_level_modules():
    """Module/package names importable at the top level: project root, then stdlib."""
    out = {}
    for name in sorted(scan_module_dir(ROOT[0])):
        out[name] = "module"
    for name in sorted(getattr(sys, "stdlib_module_names", ())):
        out.setdefault(name, "module")
    for name in sys.builtin_module_names:
        out.setdefault(name, "module")
    return out


def live_submodules(obj):
    """Submodules of a runtime module: on disk, plus already-bound module attrs."""
    names = set()
    paths = getattr(obj, "__path__", None)
    if paths:
        try:
            import pkgutil
            for info in pkgutil.iter_modules(list(paths)):
                names.add(info.name)
        except Exception:
            pass
    try:
        for name in dir(obj):
            if inspect.ismodule(getattr(obj, name, None)):
                names.add(name)
    except Exception:
        pass
    return names


def submodule_names(analyzer, dotted):
    recv = analyzer.resolve_module(dotted) if dotted else None
    if isinstance(recv, StaticModuleRecv):
        return set(recv.submodules())
    if isinstance(recv, PyRecv):
        return live_submodules(recv.obj)
    return set()


def import_completions(analyzer, context, prefix, fuzzy):
    """Completions inside an `import` / `from ... import ...` statement."""
    kind, target, _prefix = context
    items = []
    if kind == "none":
        return items
    if kind == "modules":
        for name, tp in top_level_modules().items():
            if matches(name, prefix, fuzzy):
                items.append(make_item(name, tp, None, prefix))
        return items
    if kind == "submodules":
        for name in submodule_names(analyzer, target):
            if matches(name, prefix, fuzzy):
                items.append(make_item(name, "module", None, prefix))
        return items
    # `from X import ...`: the names X exports (`__all__`, else non-underscore).
    recv = analyzer.resolve_module(target) if target else None
    if recv is None:
        return items
    seen = set()
    for name, val in public_pairs(recv):
        if name in seen:
            continue
        seen.add(name)
        if not matches(name, prefix, fuzzy):
            continue
        val = val or UNKNOWN
        items.append(make_item(name, val.kind, val.typename, prefix))
    for name in submodule_names(analyzer, target):
        if name in seen or not matches(name, prefix, fuzzy):
            continue
        seen.add(name)
        items.append(make_item(name, "module", None, prefix))
    return items


def compute(text, lines, path, line, col, fuzzy):
    line_text = lines[line - 1]
    icontext = import_context(line_text[:col])
    if icontext is not None:
        try:
            tree, _ = robust_parse(text)
            analyzer = Analyzer(tree, lines, path)
            items = import_completions(analyzer, icontext, icontext[2], fuzzy)
        except Exception:
            items = []
        return sort_items(items)
    kind, prefix, receiver_src = cursor_context(line_text, col)
    try:
        tree, _ = robust_parse(text)
        analyzer = Analyzer(tree, lines, path)
        scope = analyzer.scope_at(line, col)
        if kind == "attr":
            items = attribute_completions(analyzer, scope, line, receiver_src, prefix, fuzzy)
        else:
            items = name_completions(analyzer, scope, line, prefix, fuzzy)
    except Exception:
        # Never fail on an internal hiccup: fall back to builtins + keywords.
        if kind == "attr":
            items = []
        else:
            items = []
            for name in dir(_builtins):
                if matches(name, prefix, fuzzy):
                    val = value_from_obj(name, getattr(_builtins, name, None))
                    items.append(make_item(name, val.kind, val.typename, prefix))
            for kw in keyword.kwlist:
                if matches(kw, prefix, fuzzy):
                    items.append(make_item(kw, "keyword", None, prefix))
    return sort_items(items)


# ---------------------------------------------------------------------------
# infer / goto
# ---------------------------------------------------------------------------

VALUE_KEYWORDS = ("None", "True", "False")


def identifier_at(line_text, col):
    """The identifier run covering the cursor: (name, start, end) or None."""
    if col > len(line_text):
        return None
    start = col
    while start > 0 and is_ident_char(line_text[start - 1]):
        start -= 1
    end = col
    while end < len(line_text) and is_ident_char(line_text[end]):
        end += 1
    name = line_text[start:end]
    if not name or name[0].isdigit():
        return None
    if keyword.iskeyword(name) and name not in VALUE_KEYWORDS:
        return None
    return name, start, end


def cursor_target(lines, line, col):
    """What the cursor sits on: ("name"|"attr", name, receiver source)."""
    text = lines[line - 1]
    ident = identifier_at(text, col)
    if ident is None:
        return None
    name, start, _end = ident
    j = start - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    if j >= 0 and text[j] == "." and not (j > 0 and text[j - 1].isdigit()):
        return "attr", name, scan_receiver(text[:j])
    return "name", name, None


def value_defns(values):
    return [resolve_defn(v.defn) for v in values if v is not None]


def definitions(command, text, lines, path, line, col, follow=False):
    """Definitions for `infer` / `goto`; None means "cursor is not on a name"."""
    target = cursor_target(lines, line, col)
    if target is None:
        return None
    kind, name, receiver_src = target
    try:
        tree, _ = robust_parse(text)
        analyzer = Analyzer(tree, lines, path)
        scope = analyzer.scope_at(line, col)
    except Exception:
        return []
    try:
        if kind == "attr":
            found = _attr_definitions(analyzer, scope, line, receiver_src, name,
                                      command, follow)
        elif command == "goto":
            found = _goto_name(analyzer, scope, line, name, follow)
        else:
            found = value_defns(analyzer.name_values(scope, name, line))
    except Exception:
        found = []
    return dedupe_defns(_flatten(found))


def _goto_name(analyzer, scope, line, name, follow=False):
    bindings = analyzer.lookup_all(scope, name, line)
    if bindings:
        return [_binding_goto(analyzer, b, follow) for b in bindings]
    obj = getattr(_builtins, name, MISSING)
    if obj is not MISSING:
        return value_defns([value_from_obj(name, obj)])
    return []


def _binding_goto(analyzer, binding, follow):
    """`goto` for one binding: the import site, or what it points at (spec)."""
    owner = binding.analyzer or analyzer
    if follow:
        found = owner.followed_defns(binding)
        if found:
            return found[0] if len(found) == 1 else found
    return owner.binding_defn(binding)


def _flatten(found):
    out = []
    for item in found:
        if isinstance(item, list):
            out.extend(item)
        else:
            out.append(item)
    return out


def _attr_definitions(analyzer, scope, line, receiver_src, name, command,
                      follow=False):
    if not receiver_src:
        return []
    try:
        node = ast.parse(receiver_src, mode="eval").body
    except SyntaxError:
        return []
    bases = analyzer.resolve_multi(scope, node, line)
    if command == "goto":
        found = []
        for base in bases:
            if base.recv is None:
                continue
            for b in base.recv.get_bindings(name):
                found.append(_binding_goto(analyzer, b, follow))
        if found:
            return found
    values = []
    for base in bases:
        if base.recv is None:
            continue
        values.extend(base.recv.get_values(name))
    return value_defns(values)


# ---------------------------------------------------------------------------
# signatures
# ---------------------------------------------------------------------------


def unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "..."


def render_param(arg, default, star):
    """`name`, `name: type`, `name=default`, `name: type=default`, `*args`, `**kw`."""
    text = star + arg.arg
    if arg.annotation is not None:
        text += ": " + unparse(arg.annotation)
    if default is not None:
        text += "=" + unparse(default)
    return text


def param_specs(args):
    """(name, rendered text, kind) for every declared parameter, in order.

    The `/` and `*` markers are not parameters and are dropped (T55).
    """
    out = []
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    defaults = list(args.defaults)
    first_default = len(positional) - len(defaults)
    for i, arg in enumerate(positional):
        default = defaults[i - first_default] if i >= first_default else None
        out.append((arg.arg, render_param(arg, default, ""), "pos"))
    if args.vararg is not None:
        out.append((args.vararg.arg, render_param(args.vararg, None, "*"), "vararg"))
    for arg, default in zip(args.kwonlyargs, list(args.kw_defaults)):
        out.append((arg.arg, render_param(arg, default, ""), "kwonly"))
    if args.kwarg is not None:
        out.append((args.kwarg.arg, render_param(args.kwarg, None, "**"), "kwarg"))
    return out


def drops_first_param(owner, node):
    """Is `node` a method whose bound first parameter the spec excludes (T54)?"""
    scope = owner.func_scopes.get(node)
    if scope is None or scope.parent is None or scope.parent.kind != "class":
        return False
    if "staticmethod" in decorator_names(node):
        return False
    specs = param_specs(node.args)
    return bool(specs) and specs[0][2] == "pos" and specs[0][0] in ("self", "cls")


def make_signature(name, specs, returns, docstring, key):
    params = [text for _n, text, _k in specs]
    description = "def %s(%s)" % (name, ", ".join(params))
    if returns:
        description += " -> " + returns
    return {"name": name, "params": params, "index": None,
            "description": description, "docstring": docstring or "",
            "_specs": specs, "_key": key}


def signature_of_func(owner, node, name=None, key=None, doc=None):
    specs = param_specs(node.args)
    if drops_first_param(owner, node):
        specs = specs[1:]
    returns = unparse(node.returns) \
        if getattr(node, "returns", None) is not None else None
    if doc is None:
        doc = docstring_of(node)
    return make_signature(name or node.name, specs, returns, doc,
                          key or (owner.rel_path, getattr(node, "lineno", 0)))


def func_signatures(owner, node):
    """Signatures for a `def`, preferring the stub's parameter annotations."""
    stubs = owner.stub_nodes(node)
    if not stubs:
        return [signature_of_func(owner, node)]
    stub = owner.stub()
    doc = docstring_of(node)
    out = []
    for snode in stubs:
        if len(stubs) == 1:
            key = (owner.rel_path, getattr(node, "lineno", 0))
        else:
            key = (stub.rel_path, getattr(snode, "lineno", 0))
        out.append(signature_of_func(stub, snode, name=node.name, key=key,
                                     doc=docstring_of(snode) or doc))
    return out


def find_init(owner, classdef):
    """(analyzer, node) of the `__init__` a class calls, walking its bases."""
    for stub in owner.stub_nodes(classdef)[:1]:
        found = find_init(owner.stub(), stub)
        if found is not None:
            return found
    for binding in owner.class_attr_bindings(classdef, True).get("__init__", []):
        if binding.res[0] == "func":
            return (binding.analyzer or owner, binding.res[1])
    return None


def class_signatures(owner, classdef):
    """A constructor call reports the class name and `__init__`'s parameters (T56)."""
    doc = docstring_of(classdef)
    specs = []
    found = find_init(owner, classdef)
    if found is not None:
        _iowner, inode = found
        specs = param_specs(inode.args)
        if specs and specs[0][2] == "pos" and specs[0][0] in ("self", "cls"):
            specs = specs[1:]
        if not doc:
            doc = docstring_of(inode)
    return [make_signature(classdef.name, specs, None, doc,
                           (owner.rel_path, getattr(classdef, "lineno", 0)))]


def live_signatures(obj):
    """Best-effort signature of a callable from the target runtime."""
    name = getattr(obj, "__name__", None) or ""
    target = getattr(obj, "__init__", obj) if inspect.isclass(obj) else obj
    try:
        sig = inspect.signature(target)
    except (TypeError, ValueError):
        return []
    kinds = {inspect.Parameter.VAR_POSITIONAL: "vararg",
             inspect.Parameter.VAR_KEYWORD: "kwarg",
             inspect.Parameter.KEYWORD_ONLY: "kwonly"}
    specs = []
    for param in sig.parameters.values():
        star = "*" if param.kind == param.VAR_POSITIONAL else \
            ("**" if param.kind == param.VAR_KEYWORD else "")
        text = star + param.name
        if param.annotation is not param.empty:
            text += ": " + inspect.formatannotation(param.annotation)
        if param.default is not param.empty:
            text += "=" + repr(param.default)
        specs.append((param.name, text, kinds.get(param.kind, "pos")))
    if specs and specs[0][2] == "pos" and specs[0][0] in ("self", "cls"):
        specs = specs[1:]
    returns = None
    if not inspect.isclass(obj) and sig.return_annotation is not sig.empty:
        returns = inspect.formatannotation(sig.return_annotation)
    try:
        doc = inspect.getdoc(obj) or ""
    except Exception:
        doc = ""
    try:
        path = rel_to_root(inspect.getsourcefile(obj) or "")
        line = inspect.getsourcelines(obj)[1]
    except Exception:
        path, line = "", 0
    return [make_signature(name, specs, returns, doc, (path, line))]


def value_sources(val, out):
    """Callable sources a resolved Value stands for."""
    if val is None or val.kind not in ("function", "class"):
        return
    recv = val.recv
    if isinstance(recv, (FuncRecv, ClassRecv)):
        out.append(("py", recv.analyzer, recv.node))
    elif isinstance(recv, (FuncObjRecv, PyRecv)):
        out.append(("live", recv.obj, None))


def binding_sources(binding, out):
    owner = binding.analyzer
    if owner is not None and binding.res[0] in ("func", "class"):
        out.append(("py", owner, binding.res[1]))
        return
    for val in (owner.values_of(binding) if owner is not None else []):
        value_sources(val, out)


def scope_sig_bindings(analyzer, scope, name, line):
    """Bindings of a bare name, keeping every `@overload` declaration (T73)."""
    sc = scope
    local = True
    while sc is not None:
        if sc.kind == "class" and not local:
            sc = sc.parent
            continue
        blist = sc.bindings.get(name)
        if blist:
            use_line = line if (local or sc.kind == "module") else None
            live = live_bindings(blist, use_line)
            if live:
                return with_overloads(blist, live, use_line)
        local = False
        sc = sc.parent
    return []


def signature_sources(analyzer, scope, line, node):
    out = []
    if isinstance(node, ast.Name):
        bindings = scope_sig_bindings(analyzer, scope, node.id, line)
        if bindings:
            for binding in bindings:
                binding_sources(binding, out)
        else:
            obj = getattr(_builtins, node.id, MISSING)
            if obj is not MISSING:
                value_sources(value_from_obj(node.id, obj), out)
    elif isinstance(node, ast.Attribute):
        for base in analyzer.resolve_multi(scope, node.value, line):
            if base.recv is None:
                continue
            bindings = base.recv.sig_bindings(node.attr)
            if bindings:
                for binding in bindings:
                    binding_sources(binding, out)
            else:
                for val in base.recv.get_values(node.attr):
                    value_sources(val, out)
    else:
        for val in analyzer.resolve_multi(scope, node, line):
            value_sources(val, out)
    return out


def build_signatures(source):
    try:
        if source[0] == "live":
            return live_signatures(source[1])
        owner, node = source[1], source[2]
        if owner is None or node is None:
            return []
        if isinstance(node, ast.ClassDef):
            return class_signatures(owner, node)
        return func_signatures(owner, node)
    except Exception:
        return []


# -- locating the call the cursor sits in (T58) -----------------------------

OPENERS = "([{"
CLOSERS = ")]}"
TRIPLE_QUOTES = ('"' * 3, "'" * 3)


def skip_string(text, i):
    """Offset just past the string literal starting at `i`."""
    size = 3 if text[i:i + 3] in TRIPLE_QUOTES else 1
    quote = text[i:i + size]
    j = i + size
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j:j + size] == quote:
            return j + size
        j += 1
    return len(text)


def open_brackets(text, limit):
    """Brackets still open at `limit`, innermost last, as (char, offset) pairs."""
    stack = []
    i = 0
    end = min(limit, len(text))
    while i < end:
        ch = text[i]
        if ch == "#":
            nl = text.find("\n", i)
            i = end if nl < 0 else nl
            continue
        if ch in "\"'":
            i = skip_string(text, i)
            continue
        if ch in OPENERS:
            stack.append((ch, i))
        elif ch in CLOSERS and stack:
            stack.pop()
        i += 1
    return stack


DEF_HEADER_RE = re.compile(r"([A-Za-z_]\w*)\s*$")


def _is_definition_header(text, pos, callee):
    """`def f(` / `class C(` open a declaration, not a call."""
    head = text[:pos].rstrip()
    start = len(head) - len(callee)
    match = DEF_HEADER_RE.search(head[:start].rstrip())
    return match is not None and match.group(1) in ("def", "class")


def enclosing_call(text, offset):
    """(callee source, offset of its `(`) for the call the cursor is inside."""
    for ch, pos in reversed(open_brackets(text, offset)):
        if ch != "(":
            continue
        callee = scan_receiver(text[:pos])
        if callee and not _is_definition_header(text, pos, callee):
            return callee, pos
    return None, None


def split_arguments(text, open_pos, offset):
    """The call's argument text, split on the commas that separate arguments."""
    chunk = text[open_pos + 1:offset]
    segments = []
    current = []
    depth = 0
    i = 0
    while i < len(chunk):
        ch = chunk[i]
        if ch == "#":
            nl = chunk.find("\n", i)
            i = len(chunk) if nl < 0 else nl
            continue
        if ch in "\"'":
            j = skip_string(chunk, i)
            current.append(chunk[i:j])
            i = j
            continue
        if ch in OPENERS:
            depth += 1
        elif ch in CLOSERS:
            depth -= 1
        elif ch == "," and depth == 0:
            segments.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    segments.append("".join(current))
    return segments


KEYWORD_ARG_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=(?!=)")


def classify_argument(segment):
    stripped = segment.strip()
    if stripped.startswith("**"):
        return "dblstar", None
    if stripped.startswith("*"):
        return "star", None
    match = KEYWORD_ARG_RE.match(segment)
    if match:
        return "kw", match.group(1)
    return "pos", None


def parameter_index(specs, segments):
    """Python's call binding, applied at the cursor (spec: index detection)."""
    by_name = {}
    positional = []
    vararg = kwarg = None
    for i, (name, _text, kind) in enumerate(specs):
        if kind == "vararg":
            vararg = i
        elif kind == "kwarg":
            kwarg = i
        else:
            by_name.setdefault(name, i)
            if kind == "pos":
                positional.append(i)
    kind, name = classify_argument(segments[-1])
    if kind in ("star", "dblstar"):
        return None
    if kind == "kw":
        return by_name[name] if name in by_name else kwarg
    used = 0
    for segment in segments[:-1]:
        before, _name = classify_argument(segment)
        if before in ("star", "dblstar"):
            return None
        if before == "pos":
            used += 1
    if used < len(positional):
        return positional[used]
    return vararg


def line_start_offsets(text):
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def signatures(text, lines, path, line, col):
    offsets = line_start_offsets(text)
    if line - 1 >= len(offsets):
        return []
    offset = offsets[line - 1] + col
    callee, open_pos = enclosing_call(text, offset)
    if not callee:
        return []
    try:
        node = ast.parse(callee, mode="eval").body
    except SyntaxError:
        return []
    try:
        analyzer = analyzer_for_path(path)
        if analyzer is None:
            return []
        scope = analyzer.scope_at(line, col)
        sources = signature_sources(analyzer, scope, line, node)
    except Exception:
        return []
    found = []
    seen = set()
    for source in sources:
        for sig in build_signatures(source):
            key = (sig["_key"], tuple(sig["params"]), sig["name"])
            if key in seen:
                continue
            seen.add(key)
            found.append(sig)
    found.sort(key=lambda sig: sig["_key"])
    segments = split_arguments(text, open_pos, offset)
    return [{"name": sig["name"], "params": sig["params"],
             "index": parameter_index(sig["_specs"], segments),
             "description": sig["description"],
             "docstring": sig["docstring"]} for sig in found]


# ---------------------------------------------------------------------------
# references
# ---------------------------------------------------------------------------


def all_scopes(analyzer):
    out = []
    pending = [analyzer.module]
    while pending:
        scope = pending.pop()
        out.append(scope)
        pending.extend(scope.children)
    return out


def definition_map(analyzer):
    """(name, line, column) -> the bindings defined at that spot."""
    out = {}
    for scope in all_scopes(analyzer):
        for name, blist in scope.bindings.items():
            for binding in blist:
                out.setdefault((name, binding.lineno, binding.col), []).append(binding)
    for classdef in list(analyzer.class_scopes):
        try:
            attrs = analyzer.init_attr_bindings(classdef)
        except Exception:
            continue
        for name, blist in attrs.items():
            for binding in blist:
                out.setdefault((name, binding.lineno, binding.col), []).append(binding)
    return out


def binding_keys(binding, seen=None):
    """Identity of the symbol a binding belongs to, followed through imports (T61)."""
    if seen is None:
        seen = set()
    if id(binding) in seen:
        return set()
    seen.add(id(binding))
    owner = binding.analyzer
    keys = {(owner.filepath if owner is not None else "", id(binding.scope),
             binding.name)}
    if owner is None:
        return keys
    tag = binding.res[0]
    try:
        if tag == "mod":
            recv = owner.resolve_module(binding.res[1])
            if isinstance(recv, StaticModuleRecv) and recv.analyzer is not None:
                keys.add(("<module>", recv.analyzer.filepath, ""))
        elif tag == "from":
            recv = owner.resolve_module(binding.res[1])
            if recv is not None:
                for origin in recv.get_bindings(binding.res[2]):
                    keys |= binding_keys(origin, seen)
            sub = owner.resolve_module(join_module(binding.res[1], binding.res[2]))
            if isinstance(sub, StaticModuleRecv) and sub.analyzer is not None:
                keys.add(("<module>", sub.analyzer.filepath, ""))
        elif tag == "value":
            val = binding.res[1]
            defn = resolve_defn(val.defn) if val is not None else None
            if defn:
                keys.add(("<defn>", defn.get("module_path", ""),
                          "%s:%s" % (defn.get("line"), defn.get("column"))))
    except Exception:
        pass
    return keys


def bindings_keys(bindings):
    keys = set()
    for binding in bindings:
        keys |= binding_keys(binding)
    return keys


def name_occurrences(analyzer, name):
    """Every textual occurrence of `name` in a file: (line, column, node, tag)."""
    out = []
    for node in ast.walk(analyzer.tree):
        if isinstance(node, ast.Name):
            if node.id == name:
                out.append((node.lineno, node.col_offset, node, "name"))
        elif isinstance(node, ast.Attribute):
            if node.attr == name:
                out.append((node.lineno, _attr_col(node), node, "attr"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                out.append((node.lineno, analyzer.name_col(node, name), node, "def"))
        elif isinstance(node, ast.arg):
            if node.arg == name:
                out.append((node.lineno, node.col_offset, node, "arg"))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) != name:
                    continue
                col = getattr(alias, "col_offset", node.col_offset)
                if alias.asname:
                    end = getattr(alias, "end_col_offset", None)
                    if end is not None:
                        col = end - len(alias.asname)
                out.append((node.lineno, col, node, "import"))
    return out


def occurrence_keys(analyzer, defmap, name, line, col, node, tag):
    bindings = defmap.get((name, line, col))
    if bindings:
        return bindings_keys(bindings)
    try:
        scope = analyzer.scope_at(line, col)
        if tag == "attr":
            keys = set()
            for base in analyzer.resolve_multi(scope, node.value, line):
                if base.recv is None:
                    continue
                keys |= bindings_keys(base.recv.get_bindings(name))
            return keys
        return bindings_keys(analyzer.lookup_all(scope, name, line))
    except Exception:
        return set()


def cursor_symbol(analyzer, lines, line, col):
    """(name, identity keys, defining bindings) under the cursor, or None."""
    ident = identifier_at(lines[line - 1], col)
    if ident is None:
        return None
    name, start, _end = ident
    target = cursor_target(lines, line, col)
    tag = target[0] if target else "name"
    bindings = definition_map(analyzer).get((name, line, start), [])
    if bindings:
        return name, bindings_keys(bindings), bindings
    try:
        scope = analyzer.scope_at(line, col)
        if tag == "attr" and target[2]:
            node = ast.parse(target[2], mode="eval").body
            found = []
            for base in analyzer.resolve_multi(scope, node, line):
                if base.recv is not None:
                    found.extend(base.recv.get_bindings(name))
        else:
            found = analyzer.lookup_all(scope, name, line)
        return name, bindings_keys(found), found
    except Exception:
        return name, set(), []


def project_py_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d != "__pycache__" and not d.startswith("."))
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                out.append(os.path.join(dirpath, filename))
    return out


def references(path, lines, line, col, scope_kind):
    """All occurrences of the cursor's symbol; None when it is not on a name."""
    analyzer = analyzer_for_path(path)
    if analyzer is None or line - 1 >= len(lines):
        return None
    found = cursor_symbol(analyzer, lines, line, col)
    if found is None:
        return None
    name, keys, bindings = found
    target = os.path.abspath(path)
    if scope_kind == "project":
        files = [os.path.abspath(f) for f in project_py_files(ROOT[0])]
        if target not in files:
            files.append(target)
    else:
        files = [target]
    out = {}
    for filename in files:
        other = analyzer_for_path(filename)
        if other is None:
            continue
        defmap = definition_map(other)
        for oline, ocol, node, tag in name_occurrences(other, name):
            if keys:
                okeys = occurrence_keys(other, defmap, name, oline, ocol, node, tag)
                if not okeys & keys:
                    continue
            out[(other.rel_path, oline, ocol)] = bool(defmap.get((name, oline, ocol)))
    # The defining occurrence is always reported when it is in scope (spec).
    for binding in bindings:
        owner = binding.analyzer
        if owner is None or owner.filepath not in files:
            continue
        out[(owner.rel_path, binding.lineno, binding.col)] = True
    return [{"module_path": mp, "line": ln, "column": cl, "is_definition": flag}
            for (mp, ln, cl), flag in sorted(out.items())]


# ---------------------------------------------------------------------------
# search / names
# ---------------------------------------------------------------------------

IMPORT_TAGS = ("mod", "from", "value", "param")


def match_rank(name, query):
    """0 exact, 1 prefix, 2 substring, None when it does not match (spec)."""
    low = name.lower()
    if low == query:
        return 0
    if low.startswith(query):
        return 1
    if query in low:
        return 2
    return None


def searchable_scopes(analyzer):
    """Module scope plus class bodies -- never function bodies (T63)."""
    out = []
    pending = [analyzer.module]
    while pending:
        scope = pending.pop()
        out.append(scope)
        for child in scope.children:
            if child.kind == "class":
                pending.append(child)
    return out


def search(query):
    lowered = (query or "").lower()
    ranked = []
    for filename in project_py_files(ROOT[0]):
        analyzer = analyzer_for_path(filename)
        if analyzer is None:
            continue
        for scope in searchable_scopes(analyzer):
            for name, blist in scope.bindings.items():
                rank = match_rank(name, lowered)
                if rank is None:
                    continue
                for binding in blist:
                    if binding.res[0] in IMPORT_TAGS:
                        continue
                    try:
                        defn = analyzer.binding_defn(binding)
                    except Exception:
                        defn = None
                    if defn is None:
                        continue
                    defn = dict(defn)
                    defn.pop("docstring", None)
                    ranked.append((rank, defn["module_path"], defn["line"],
                                   defn["column"], defn["name"], defn))
    ranked.sort(key=lambda item: item[:5])
    return [item[5] for item in ranked]


def file_names(path, everything):
    analyzer = analyzer_for_path(path)
    if analyzer is None:
        return []
    scopes = all_scopes(analyzer) if everything else [analyzer.module]
    out = []
    for scope in scopes:
        for name, blist in scope.bindings.items():
            for binding in blist:
                try:
                    defn = analyzer.binding_defn(binding)
                except Exception:
                    defn = None
                if defn is None:
                    continue
                defn = dict(defn)
                defn["is_definition"] = True
                out.append(defn)
    out.sort(key=lambda d: (d["line"], d["column"], d["name"]))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def fail(message):
    sys.stderr.write("sith: %s\n" % message)
    raise SystemExit(1)


USAGE = ("usage: sith.py complete|infer|goto|signatures|references <file> <line> "
         "<col> [--fuzzy] [--follow-imports] [--scope file|project] "
         "[--project <dir>]\n"
         "       sith.py search <query> [--project <dir>]\n"
         "       sith.py names <file> [--all-scopes] [--project <dir>]")

CURSOR_COMMANDS = ("complete", "infer", "goto", "signatures", "references")
COMMANDS = CURSOR_COMMANDS + ("search", "names")

# The spec documents dynamic parameter inference as "enabled by default" but
# never names the switch; these spellings all turn it off (T70).
NO_DYNAMIC = ("--no-dynamic", "--no-dynamic-params", "--no-call-sites",
              "--no-infer-params")


def read_source(path):
    if not os.path.exists(path):
        fail("no such file: %s" % path)
    if not os.path.isfile(path):
        fail("not a regular file: %s" % path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        fail("cannot read %s: %s" % (path, exc))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("file is not valid UTF-8: %s" % path)


def main(argv):
    args = argv[1:]
    fuzzy = False
    follow = False
    all_scopes_flag = False
    project = None
    scope_kind = "file"
    positional = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--fuzzy":
            fuzzy = True
        elif arg == "--follow-imports":
            follow = True
        elif arg == "--all-scopes":
            all_scopes_flag = True
        elif arg in NO_DYNAMIC:
            DYNAMIC[0] = False
        elif arg == "--scope":
            i += 1
            if i >= len(args):
                fail("--scope requires file or project")
            scope_kind = args[i]
        elif arg.startswith("--scope="):
            scope_kind = arg.split("=", 1)[1]
        elif arg == "--project":
            i += 1
            if i >= len(args):
                fail("--project requires a directory")
            project = args[i]
        elif arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        elif arg.startswith("--"):
            fail("unknown option: %s" % arg)
        else:
            positional.append(arg)
        i += 1

    if not positional or positional[0] not in COMMANDS:
        fail(USAGE)
    command = positional[0]
    if scope_kind not in ("file", "project"):
        fail("--scope must be file or project")
    wanted = 4 if command in CURSOR_COMMANDS else 2
    if len(positional) != wanted:
        fail(USAGE)

    if project is not None and not os.path.isdir(project):
        fail("no such project directory: %s" % project)

    if command == "search":
        set_root(project if project is not None else os.getcwd())
        payload = search(positional[1])
        emit({"results": payload, "definitions": payload})
        return 0

    path = positional[1]
    text = read_source(path)
    # Project root: --project when given, else the directory holding <file>.
    set_root(project if project is not None
             else (os.path.dirname(os.path.abspath(path)) or "."))

    if command == "names":
        payload = file_names(path, all_scopes_flag)
        emit({"names": payload, "definitions": payload})
        return 0

    try:
        line = int(positional[2])
        col = int(positional[3])
    except ValueError:
        fail("line and col must be integers")
    lines = text.splitlines()
    if line < 1 or line > len(lines):
        fail("line out of range: %d" % line)
    if col < 0 or col > len(lines[line - 1]):
        fail("column out of range: %d" % col)

    if command == "complete":
        payload = {"completions": compute(text, lines, path, line, col, fuzzy)}
    elif command == "signatures":
        payload = {"signatures": signatures(text, lines, path, line, col)}
    elif command == "references":
        found = references(path, lines, line, col, scope_kind)
        if found is None:
            fail("cursor is not on a name")
        payload = {"references": found}
    else:
        found = definitions(command, text, lines, path, line, col, follow)
        if found is None:
            fail("cursor is not on a name")
        payload = {"definitions": found}
    emit(payload)
    return 0


def emit(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")

if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BrokenPipeError:  # pragma: no cover
        sys.exit(1)
