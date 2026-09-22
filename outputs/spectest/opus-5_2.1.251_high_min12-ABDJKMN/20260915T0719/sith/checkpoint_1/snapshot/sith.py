#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]

Parses a Python source file statically, works out which names are visible at the
requested cursor position (or which attributes a receiver expression exposes) and
prints ranked completions as compact JSON on stdout.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import importlib
import inspect
import json
import keyword
import os
import sys

MISSING = object()
MAX_LOCAL_MODULE_DEPTH = 3

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


class Value:
    """What a name/expression resolves to: a completion kind plus an attribute source."""

    __slots__ = ("kind", "typename", "recv")

    def __init__(self, kind, typename=None, recv=None):
        self.kind = kind
        self.typename = typename
        self.recv = recv


UNKNOWN = Value("statement")


def value_from_obj(name, obj):
    """Classify a live Python object (T19)."""
    try:
        if inspect.ismodule(obj):
            return Value("module", getattr(obj, "__name__", name), PyRecv(obj))
        if inspect.isclass(obj):
            return Value("class", getattr(obj, "__name__", name), PyRecv(obj))
        if callable(obj):
            return Value("function")
        return Value("instance", type(obj).__name__, PyRecv(type(obj)))
    except Exception:
        return UNKNOWN


# ---------------------------------------------------------------------------
# receivers -- things that can produce attributes
# ---------------------------------------------------------------------------


class Receiver:
    def attributes(self):
        return []

    def get_value(self, name):
        return None

    def call(self):
        return None


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

    def call(self):
        if inspect.isclass(self.obj):
            return Value("instance", self.obj.__name__, PyRecv(self.obj))
        return None


class StaticModuleRecv(Receiver):
    """Attributes of a local project module, analysed without executing it (T11)."""

    def __init__(self, analyzer):
        self.analyzer = analyzer

    def attributes(self):
        out = []
        for name, blist in self.analyzer.module.bindings.items():
            if name.startswith("_"):
                continue
            out.append((name, self.analyzer.value_of(blist[-1])))
        return out

    def get_value(self, name):
        blist = self.analyzer.module.bindings.get(name)
        if not blist:
            return None
        return self.analyzer.value_of(blist[-1])


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

    def call(self):
        if not self.instance:
            return Value("instance", self.node.name,
                         ClassRecv(self.analyzer, self.node, True))
        return None


def safe_import(modname):
    try:
        return importlib.import_module(modname)
    except BaseException:
        return None


# ---------------------------------------------------------------------------
# scopes / bindings
# ---------------------------------------------------------------------------


class Binding:
    __slots__ = ("name", "lineno", "res", "scope", "_value", "_busy")

    def __init__(self, name, lineno, res, scope=None):
        self.name = name
        self.lineno = lineno
        self.res = res          # descriptor resolved lazily into a Value
        self.scope = scope
        self._value = None
        self._busy = False


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
    def __init__(self, tree, lines, filepath, depth=0):
        self.lines = lines
        self.depth = depth
        self.filepath = os.path.abspath(filepath)
        self.dirname = os.path.dirname(self.filepath)
        self.class_scopes = {}
        self.func_scopes = {}
        self._module_cache = {}
        self._class_attr_cache = {}
        nlines = max(1, len(lines))
        self.module = Scope("module", tree, None, 1, nlines)
        self.module.ext_end = nlines
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

    def _build_body(self, body, scope):
        for st in body or []:
            try:
                self._build_stmt(st, scope)
            except Exception:
                continue

    def _build_stmt(self, st, scope):
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.add(Binding(st.name, st.lineno, ("func", st), scope))
            child = self._new_scope("function", st, scope)
            self.func_scopes[st] = child
            for i, arg in enumerate(self._arg_nodes(st.args)):
                child.add(Binding(arg.arg, st.lineno,
                                  ("param", arg.annotation, scope, st, i), child))
            self._build_body(st.body, child)
        elif isinstance(st, ast.ClassDef):
            scope.add(Binding(st.name, st.lineno, ("class", st), scope))
            child = self._new_scope("class", st, scope)
            self.class_scopes[st] = child
            self._build_body(st.body, child)
        elif isinstance(st, ast.Assign):
            for tgt in st.targets:
                self._bind_target(tgt, st.value, st.lineno, scope)
            self._walk_walrus(st.value, scope)
        elif isinstance(st, ast.AnnAssign):
            if isinstance(st.target, ast.Name):
                if st.value is not None:
                    res = ("expr", st.value, scope)
                else:
                    res = ("annotation", st.annotation, scope)
                scope.add(Binding(st.target.id, st.lineno, res, scope))
        elif isinstance(st, ast.AugAssign):
            if isinstance(st.target, ast.Name):
                scope.add(Binding(st.target.id, st.lineno, ("unknown",), scope))
        elif isinstance(st, ast.Import):
            for al in st.names:
                if al.asname:
                    scope.add(Binding(al.asname, st.lineno, ("mod", al.name), scope))
                else:
                    top = al.name.split(".")[0]
                    scope.add(Binding(top, st.lineno, ("mod", top), scope))
        elif isinstance(st, ast.ImportFrom):
            self._build_import_from(st, scope)
        elif isinstance(st, (ast.For, ast.AsyncFor)):
            self._bind_target(st.target, None, st.lineno, scope)
            self._build_body(st.body, scope)
            self._build_body(st.orelse, scope)
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, None, st.lineno, scope)
            self._build_body(st.body, scope)
        elif isinstance(st, (ast.If, ast.While)):
            self._walk_walrus(st.test, scope)
            self._build_body(st.body, scope)
            self._build_body(st.orelse, scope)
        elif isinstance(st, ast.Try) or st.__class__.__name__ == "TryStar":
            self._build_body(st.body, scope)
            for handler in st.handlers:
                if handler.name:
                    scope.add(Binding(handler.name, handler.lineno, ("unknown",), scope))
                self._build_body(handler.body, scope)
            self._build_body(st.orelse, scope)
            self._build_body(st.finalbody, scope)
        elif isinstance(st, ast.Expr):
            self._walk_walrus(st.value, scope)

    def _arg_nodes(self, args):
        out = list(getattr(args, "posonlyargs", [])) + list(args.args)
        if args.vararg:
            out.append(args.vararg)
        out += list(args.kwonlyargs)
        if args.kwarg:
            out.append(args.kwarg)
        return out

    def _walk_walrus(self, node, scope):
        if node is None:
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                scope.add(Binding(sub.target.id, sub.lineno, ("expr", sub.value, scope), scope))

    def _bind_target(self, tgt, value, lineno, scope):
        if isinstance(tgt, ast.Name):
            res = ("expr", value, scope) if value is not None else ("unknown",)
            scope.add(Binding(tgt.id, lineno, res, scope))
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            elts = tgt.elts
            vals = None
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(elts):
                vals = value.elts
            for i, el in enumerate(elts):
                self._bind_target(el, vals[i] if vals else None, lineno, scope)
        elif isinstance(tgt, ast.Starred):
            self._bind_target(tgt.value, None, lineno, scope)

    def _build_import_from(self, st, scope):
        modname = "." * (st.level or 0) + (st.module or "")
        for al in st.names:
            if al.name == "*":
                recv = self.resolve_module(modname)
                if recv is None:
                    continue
                for name, val in recv.attributes():
                    if name.startswith("_"):
                        continue
                    scope.add(Binding(name, st.lineno, ("value", val), scope))
            else:
                scope.add(Binding(al.asname or al.name, st.lineno,
                                  ("from", modname, al.name), scope))

    # -- module resolution -------------------------------------------------

    def resolve_module(self, modname):
        if modname in self._module_cache:
            return self._module_cache[modname]
        self._module_cache[modname] = None
        recv = self._resolve_module_uncached(modname)
        self._module_cache[modname] = recv
        return recv

    def _resolve_module_uncached(self, modname):
        if not modname:
            return None
        base = self.dirname
        rel = modname.lstrip(".")
        if modname.startswith("."):
            up = len(modname) - len(modname.lstrip(".")) - 1
            for _ in range(up):
                base = os.path.dirname(base)
            if not rel:
                return None
        local = self._local_module(base, rel)
        if local is not None:
            return local
        if modname.startswith("."):
            return None
        mod = safe_import(modname)
        if mod is not None:
            return PyRecv(mod)
        return None

    def _local_module(self, base, dotted):
        if self.depth >= MAX_LOCAL_MODULE_DEPTH:
            return None
        parts = dotted.split(".")
        candidates = [os.path.join(base, *parts) + ".py",
                      os.path.join(base, *parts, "__init__.py")]
        for path in candidates:
            if not os.path.isfile(path):
                continue
            if os.path.abspath(path) == self.filepath:
                return StaticModuleRecv(self)
            try:
                with open(path, "rb") as fh:
                    text = fh.read().decode("utf-8")
            except Exception:
                return None
            tree, lines = robust_parse(text)
            try:
                sub = Analyzer(tree, lines, path, depth=self.depth + 1)
            except Exception:
                return None
            return StaticModuleRecv(sub)
        return None

    # -- values ------------------------------------------------------------

    def value_of(self, binding):
        if binding._value is not None:
            return binding._value
        if binding._busy:
            return UNKNOWN
        binding._busy = True
        try:
            val = self._compute_value(binding)
        except Exception:
            val = UNKNOWN
        finally:
            binding._busy = False
        binding._value = val
        return val

    def _compute_value(self, binding):
        res = binding.res
        tag = res[0]
        if tag == "func":
            return Value("function")
        if tag == "class":
            return Value("class", res[1].name, ClassRecv(self, res[1]))
        if tag == "param":
            recv = None
            if res[1] is not None:
                ann = self.resolve_expr(res[2], res[1])
                if ann is not None and ann.kind == "class":
                    recv = ann.recv
            if recv is None and len(res) > 4 and res[4] == 0:
                recv = self._implicit_self_recv(res[3], res[2])
            return Value("param", None, recv)
        if tag == "mod":
            return Value("module", res[1], self.resolve_module(res[1]))
        if tag == "value":
            return res[1]
        if tag == "expr":
            val = self.resolve_expr(res[2], res[1])
            return val if val is not None else UNKNOWN
        if tag == "annotation":
            ann = self.resolve_expr(res[2], res[1])
            if ann is not None and ann.kind == "class":
                return Value("instance", ann.typename, ann.recv)
            return UNKNOWN
        if tag == "from":
            return self._from_import_value(res[1], res[2])
        return UNKNOWN

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

    def _from_import_value(self, modname, name):
        recv = self.resolve_module(modname)
        if recv is None:
            return UNKNOWN
        val = recv.get_value(name)
        if val is None and not modname.startswith("."):
            sub = self.resolve_module(modname + "." + name)
            if sub is not None:
                return Value("module", name, sub)
        return val if val is not None else UNKNOWN

    # -- expressions -------------------------------------------------------

    def resolve_expr(self, scope, node, line=None):
        """Resolve an expression to a Value (or None when nothing is known)."""
        if node is None:
            return None
        try:
            return self._resolve_expr(scope, node, line)
        except Exception:
            return None

    def _resolve_expr(self, scope, node, line=None):
        if isinstance(node, ast.Name):
            binding = self.lookup(scope, node.id, line)
            if binding is not None:
                return self.value_of(binding)
            obj = getattr(_builtins, node.id, MISSING)
            if obj is not MISSING:
                return value_from_obj(node.id, obj)
            return None
        if isinstance(node, ast.Attribute):
            base = self._resolve_expr(scope, node.value, line)
            if base is None or base.recv is None:
                return None
            return base.recv.get_value(node.attr)
        if isinstance(node, ast.Call):
            func = self._resolve_expr(scope, node.func, line)
            if func is None or func.recv is None:
                return None
            return func.recv.call()
        if isinstance(node, ast.Constant):
            t = type(node.value)
            return Value("instance", t.__name__, PyRecv(t))
        if isinstance(node, ast.JoinedStr):
            return Value("instance", "str", PyRecv(str))
        if isinstance(node, (ast.List, ast.ListComp)):
            return Value("instance", "list", PyRecv(list))
        if isinstance(node, ast.Tuple):
            return Value("instance", "tuple", PyRecv(tuple))
        if isinstance(node, (ast.Set, ast.SetComp)):
            return Value("instance", "set", PyRecv(set))
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return Value("instance", "dict", PyRecv(dict))
        if isinstance(node, ast.Lambda):
            return Value("function")
        if isinstance(node, ast.NamedExpr):
            return self._resolve_expr(scope, node.value, line)
        return None

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
        for cls in self.linearize(classdef):
            scope = self.class_scopes.get(cls)
            if scope is not None:
                for name, blist in scope.bindings.items():
                    if name not in out:
                        out[name] = self.value_of(blist[-1])
            if instance:
                for name, val in self.init_attrs(cls).items():
                    if name not in out:
                        out[name] = val
        return out

    def init_attrs(self, classdef):
        """`self.x = ...` assignments in the class's own __init__ (T9)."""
        out = {}
        for st in classdef.body:
            if not isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if st.name != "__init__":
                continue
            args = self._arg_nodes(st.args)
            selfname = args[0].arg if args else "self"
            scope = self.func_scopes.get(st, self.module)
            for sub in ast.walk(st):
                targets = []
                if isinstance(sub, ast.Assign):
                    targets = sub.targets
                    value = sub.value
                elif isinstance(sub, ast.AnnAssign):
                    targets = [sub.target]
                    value = sub.value
                else:
                    continue
                for tgt in targets:
                    if (isinstance(tgt, ast.Attribute)
                            and isinstance(tgt.value, ast.Name)
                            and tgt.value.id == selfname):
                        val = self.resolve_expr(scope, value) if value is not None else None
                        out.setdefault(tgt.attr, val if val is not None else UNKNOWN)
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
    val = analyzer.resolve_expr(scope, node, line)
    if val is None or val.recv is None:
        return []
    items = []
    seen = set()
    for name, attr in val.recv.attributes():
        if name in seen:
            continue
        seen.add(name)
        if not matches(name, prefix, fuzzy):
            continue
        attr = attr or UNKNOWN
        items.append(make_item(name, attr.kind, attr.typename, prefix))
    return items


def compute(text, lines, path, line, col, fuzzy):
    line_text = lines[line - 1]
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
# CLI
# ---------------------------------------------------------------------------


def fail(message):
    sys.stderr.write("sith: %s\n" % message)
    raise SystemExit(1)


def main(argv):
    args = argv[1:]
    fuzzy = False
    positional = []
    for arg in args:
        if arg == "--fuzzy":
            fuzzy = True
        elif arg.startswith("--"):
            fail("unknown option: %s" % arg)
        else:
            positional.append(arg)

    if len(positional) != 4 or positional[0] != "complete":
        fail("usage: sith.py complete <file> <line> <col> [--fuzzy]")

    path, line_s, col_s = positional[1], positional[2], positional[3]
    try:
        line = int(line_s)
        col = int(col_s)
    except ValueError:
        fail("line and col must be integers")

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
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("file is not valid UTF-8: %s" % path)

    lines = text.splitlines()
    if line < 1 or line > len(lines):
        fail("line out of range: %d" % line)
    if col < 0 or col > len(lines[line - 1]):
        fail("column out of range: %d" % col)

    completions = compute(text, lines, path, line, col, fuzzy)
    sys.stdout.write(json.dumps({"completions": completions}, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BrokenPipeError:  # pragma: no cover
        sys.exit(1)
