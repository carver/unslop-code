#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]

Parses a Python source file (tolerating syntax errors), works out which
names are visible at the requested cursor position and prints ranked
completions as a compact JSON object on stdout.
"""

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

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

KEYWORDS = sorted(keyword.kwlist)
_KEYWORD_SET = set(KEYWORDS)


def is_ident_char(ch):
    return ch.isalnum() or ch == '_'


def end_line_of(node):
    return getattr(node, 'end_lineno', None) or getattr(node, 'lineno', 0)


def name_group(name):
    """0 = public, 1 = private, 2 = dunder."""
    if name.startswith('__') and name.endswith('__'):
        return 2
    if name.startswith('_'):
        return 1
    return 0


# --------------------------------------------------------------------------
# tolerant parsing
# --------------------------------------------------------------------------

def _empty_module():
    mod = ast.parse('')
    return mod


def tolerant_parse(source):
    """Parse *source*, repairing syntax errors as best we can."""
    try:
        return ast.parse(source)
    except SyntaxError:
        pass
    except Exception:
        return _empty_module()

    lines = source.split('\n')
    cur = list(lines)
    blanked = set()
    for _ in range(200):
        try:
            return ast.parse('\n'.join(cur))
        except SyntaxError as exc:
            ln = getattr(exc, 'lineno', None)
            if not ln or ln < 1 or ln > len(cur):
                break
            if ln in blanked:
                # already tried this line; give up on incremental repair
                break
            blanked.add(ln)
            orig = cur[ln - 1]
            indent = orig[:len(orig) - len(orig.lstrip())]
            repl = indent + 'pass'
            if repl == orig:
                repl = ''
            cur[ln - 1] = repl
        except Exception:
            break

    # Fallback: progressively truncate the file from the end.
    for end in range(len(lines), 0, -1):
        chunk = lines[:end]
        try:
            return ast.parse('\n'.join(chunk))
        except SyntaxError:
            continue
        except Exception:
            break
    return _empty_module()


# --------------------------------------------------------------------------
# values / definitions
# --------------------------------------------------------------------------

class Val(object):
    """A very small abstract value used for type inference."""

    __slots__ = ('kind', 'name', 'obj', 'node', 'owner', 'pytype',
                 'modname', 'level', '_resolved')

    def __init__(self, kind='unknown', name=None, obj=None, node=None,
                 owner=None, pytype=None, modname=None, level=0):
        self.kind = kind          # module|class|instance|function|unknown
        self.name = name          # display name
        self.obj = obj            # real python object OR Analysis (module)
        self.node = node          # ast ClassDef / FunctionDef in a file
        self.owner = owner        # Analysis that owns `node`
        self.pytype = pytype      # real type, for instances of real types
        self.modname = modname    # dotted module name, resolved lazily
        self.level = level        # relative-import level
        self._resolved = False


UNKNOWN = Val('unknown')


def val_from_obj(obj, name=None):
    try:
        if inspect.ismodule(obj):
            return Val('module', getattr(obj, '__name__', name) or name, obj=obj)
        if inspect.isclass(obj):
            return Val('class', getattr(obj, '__name__', name) or name, obj=obj)
        if inspect.isroutine(obj):
            return Val('function', name, obj=obj)
        return Val('instance', type(obj).__name__, obj=obj, pytype=type(obj))
    except Exception:
        return Val('unknown')


def describe_val(val, name):
    """Return (type, description) for a binding called *name* holding *val*."""
    if val is None:
        return 'statement', 'statement'
    if val.kind == 'module':
        return 'module', 'module %s' % name
    if val.kind == 'class':
        return 'class', 'class %s' % name
    if val.kind == 'function':
        return 'function', 'def %s(...)' % name
    if val.kind == 'instance':
        tname = val.name or (val.pytype.__name__ if val.pytype else None)
        if not tname:
            return 'statement', 'statement'
        return 'instance', 'instance of %s' % tname
    return 'statement', 'statement'


class Definition(object):
    __slots__ = ('name', 'kind', 'description', 'lineno', 'val')

    def __init__(self, name, kind, description, lineno, val=None):
        self.name = name
        self.kind = kind
        self.description = description
        self.lineno = lineno
        self.val = val if val is not None else UNKNOWN


def make_def(name, lineno, val):
    kind, desc = describe_val(val, name)
    return Definition(name, kind, desc, lineno, val)


# --------------------------------------------------------------------------
# scopes
# --------------------------------------------------------------------------

class Scope(object):
    def __init__(self, kind, node, parent, start, end):
        self.kind = kind            # module|function|class|lambda
        self.node = node
        self.parent = parent
        self.children = []
        self.defs = {}              # name -> [Definition, ...] in source order
        self.start = start
        self.end = end

    def add(self, definition):
        self.defs.setdefault(definition.name, []).append(definition)

    def lookup_local(self, name, line=None):
        lst = self.defs.get(name)
        if not lst:
            return None
        if line is None:
            return lst[-1]
        best = None
        for d in lst:
            if d.lineno <= line:
                best = d
        return best

    @property
    def col_offset(self):
        return getattr(self.node, 'col_offset', -1)


# --------------------------------------------------------------------------
# module resolution
# --------------------------------------------------------------------------

_module_cache = {}
_analysis_cache = {}


def _find_local_module(base_dir, dotted):
    parts = [p for p in dotted.split('.') if p]
    if not parts:
        return None
    path = base_dir
    for i, part in enumerate(parts):
        last = (i == len(parts) - 1)
        cand_pkg = os.path.join(path, part, '__init__.py')
        cand_mod = os.path.join(path, part + '.py')
        if last:
            if os.path.isfile(cand_mod):
                return cand_mod
            if os.path.isfile(cand_pkg):
                return cand_pkg
            return None
        if os.path.isdir(os.path.join(path, part)):
            path = os.path.join(path, part)
        else:
            return None
    return None


def analyze_path(path):
    path = os.path.abspath(path)
    if path in _analysis_cache:
        return _analysis_cache[path]
    _analysis_cache[path] = None            # recursion guard
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
        src = data.decode('utf-8', 'replace')
        src = src.replace('\r\n', '\n').replace('\r', '\n')
        analysis = Analysis(src, path)
    except Exception:
        analysis = None
    _analysis_cache[path] = analysis
    return analysis


def _import_real(dotted):
    if not dotted:
        return None
    if dotted in _module_cache:
        return _module_cache[dotted]
    mod = None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            mod = importlib.import_module(dotted)
    except BaseException:
        mod = None
    _module_cache[dotted] = mod
    return mod


def resolve_module(base_dir, dotted, level=0):
    """Return an Analysis (local file) or a real module object, or None."""
    if level:
        base = base_dir
        for _ in range(level - 1):
            base = os.path.dirname(base)
        if not dotted:
            return None
        local = _find_local_module(base, dotted)
        if local:
            return analyze_path(local)
        return None
    if not dotted:
        return None
    local = _find_local_module(base_dir, dotted)
    if local:
        return analyze_path(local)
    return _import_real(dotted)


def materialize(val):
    """Resolve a lazy module Val to an Analysis / real module."""
    if val is None or val.kind != 'module':
        return None
    if val.obj is None and not val._resolved and val.modname:
        val._resolved = True
        base = val.owner.dirpath if val.owner is not None else os.getcwd()
        val.obj = resolve_module(base, val.modname, val.level)
    return val.obj


# --------------------------------------------------------------------------
# the analyzer
# --------------------------------------------------------------------------

class Analysis(object):
    def __init__(self, source, path=None):
        self.source = source
        self.path = path
        if path:
            self.dirpath = os.path.dirname(os.path.abspath(path)) or os.getcwd()
        else:
            self.dirpath = os.getcwd()
        self.lines = source.split('\n')
        self.tree = tolerant_parse(source)
        self.class_scopes = {}
        self.func_scopes = {}
        self.module_scope = Scope('module', self.tree, None, 1, 10 ** 9)
        try:
            self._body(getattr(self.tree, 'body', []), self.module_scope)
        except Exception:
            pass

    # -- scope construction ------------------------------------------------

    def _body(self, stmts, scope):
        for st in stmts or []:
            try:
                self._stmt(st, scope)
            except Exception:
                pass

    def _stmt(self, node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            val = Val('function', node.name, node=node, owner=self)
            scope.add(Definition(node.name, 'function',
                                 'def %s(...)' % node.name, node.lineno, val))
            self._function(node, scope)
            return
        if isinstance(node, ast.ClassDef):
            val = Val('class', node.name, node=node, owner=self)
            scope.add(Definition(node.name, 'class',
                                 'class %s' % node.name, node.lineno, val))
            self._class(node, scope)
            return
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                self._bind_target(tgt, node.value, scope, node.lineno)
            self._walrus(node.value, scope)
            return
        if isinstance(node, ast.AnnAssign):
            self._bind_target(node.target, node.value, scope, node.lineno,
                              annotation=node.annotation)
            self._walrus(node.value, scope)
            return
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                existing = scope.lookup_local(node.target.id)
                val = existing.val if existing else UNKNOWN
                scope.add(make_def(node.target.id, node.lineno, val))
            self._walrus(node.value, scope)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._bind_target(node.target, None, scope, node.lineno)
            self._walrus(node.iter, scope)
            self._body(node.body, scope)
            self._body(node.orelse, scope)
            return
        if isinstance(node, (ast.While, ast.If)):
            self._walrus(node.test, scope)
            self._body(node.body, scope)
            self._body(node.orelse, scope)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, item.context_expr,
                                      scope, node.lineno)
                self._walrus(item.context_expr, scope)
            self._body(node.body, scope)
            return
        if isinstance(node, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
            self._body(node.body, scope)
            for h in node.handlers:
                if h.name:
                    scope.add(make_def(h.name, h.lineno,
                                       self._exc_val(h.type, scope)))
                self._body(h.body, scope)
            self._body(node.orelse, scope)
            self._body(node.finalbody, scope)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound, dotted = alias.asname, alias.name
                else:
                    bound = alias.name.split('.')[0]
                    dotted = bound
                val = Val('module', bound, modname=dotted, owner=self)
                scope.add(Definition(bound, 'module', 'module %s' % bound,
                                     node.lineno, val))
            return
        if isinstance(node, ast.ImportFrom):
            self._import_from(node, scope)
            return
        if hasattr(ast, 'Match') and isinstance(node, ast.Match):
            self._walrus(node.subject, scope)
            for case in node.cases:
                for nm in self._pattern_names(case.pattern):
                    scope.add(make_def(nm, node.lineno, UNKNOWN))
                self._body(case.body, scope)
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return
        # anything else: just look for walrus assignments
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._stmt(child, scope)
            else:
                self._walrus(child, scope)

    def _exc_val(self, type_node, scope):
        v = self._infer(type_node, scope)
        if v.kind == 'class':
            inst = Val('instance', v.name, obj=None, node=v.node,
                       owner=v.owner, pytype=v.obj if inspect.isclass(v.obj) else None)
            return inst
        return UNKNOWN

    def _pattern_names(self, pat):
        out = []
        try:
            for n in ast.walk(pat):
                nm = getattr(n, 'name', None)
                if isinstance(nm, str):
                    out.append(nm)
                if isinstance(n, ast.MatchStar) and n.name:
                    out.append(n.name)
        except Exception:
            pass
        return out

    def _walrus(self, node, scope):
        if node is None:
            return
        stack = [node]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.NamedExpr):
                if isinstance(cur.target, ast.Name):
                    scope.add(make_def(cur.target.id, cur.lineno,
                                       self._infer(cur.value, scope)))
            if isinstance(cur, (ast.Lambda, ast.FunctionDef,
                                ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for ch in ast.iter_child_nodes(cur):
                if not isinstance(ch, ast.stmt):
                    stack.append(ch)

    def _import_from(self, node, scope):
        modname = node.module or ''
        level = getattr(node, 'level', 0) or 0
        target = None
        star = False
        for alias in node.names:
            if alias.name == '*':
                star = True
        if star:
            target = resolve_module(self.dirpath, modname, level)
            for name, val in module_public_vals(target):
                scope.add(make_def(name, node.lineno, val))
            return
        target = resolve_module(self.dirpath, modname, level)
        for alias in node.names:
            bound = alias.asname or alias.name
            val = self._from_import_val(target, alias.name, modname, level)
            kind, desc = describe_val(val, bound)
            scope.add(Definition(bound, kind, desc, node.lineno, val))

    def _from_import_val(self, target, attr, modname, level):
        if target is not None:
            v = attr_of_module(target, attr)
            if v is not None and v.kind != 'unknown':
                return v
        # maybe it is a submodule: from pkg import sub
        dotted = (modname + '.' + attr) if modname else attr
        sub = resolve_module(self.dirpath, dotted, level)
        if sub is not None:
            return Val('module', attr, obj=sub, owner=self)
        return UNKNOWN

    def _function(self, node, parent):
        s = Scope('function', node, parent, node.lineno, end_line_of(node))
        parent.children.append(s)
        self.func_scopes[node] = s
        a = node.args
        params = []
        params.extend(getattr(a, 'posonlyargs', []) or [])
        params.extend(a.args or [])
        if a.vararg:
            params.append(a.vararg)
        params.extend(a.kwonlyargs or [])
        if a.kwarg:
            params.append(a.kwarg)
        for p in params:
            val = self._from_annotation(getattr(p, 'annotation', None), parent)
            s.add(Definition(p.arg, 'param', 'param %s' % p.arg,
                             node.lineno, val))
        self._body(node.body, s)
        return s

    def _class(self, node, parent):
        s = Scope('class', node, parent, node.lineno, end_line_of(node))
        parent.children.append(s)
        self.class_scopes[node] = s
        self._body(node.body, s)
        # give `self` / `cls` a useful type inside methods
        for st in node.body:
            if not isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decos = set()
            for d in st.decorator_list:
                if isinstance(d, ast.Name):
                    decos.add(d.id)
                elif isinstance(d, ast.Attribute):
                    decos.add(d.attr)
            if 'staticmethod' in decos:
                continue
            fs = self.func_scopes.get(st)
            if fs is None:
                continue
            args = list(getattr(st.args, 'posonlyargs', []) or []) + list(st.args.args or [])
            if not args:
                continue
            first = args[0].arg
            lst = fs.defs.get(first)
            if not lst:
                continue
            kind = 'class' if 'classmethod' in decos else 'instance'
            lst[0].val = Val(kind, node.name, node=node, owner=self)
        return s

    def _bind_target(self, target, value, scope, lineno, annotation=None):
        if isinstance(target, ast.Name):
            val = self._infer(value, scope) if value is not None else UNKNOWN
            if annotation is not None:
                av = self._from_annotation(annotation, scope)
                if av.kind != 'unknown':
                    val = av
            scope.add(make_def(target.id, lineno, val))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._bind_target(elt, None, scope, lineno)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, None, scope, lineno)

    # -- name lookup -------------------------------------------------------

    def _lookup(self, scope, name, line=None):
        s = scope
        while s is not None:
            d = s.lookup_local(name, line if s is scope else None)
            if d is None:
                d = s.lookup_local(name)
            if d is not None:
                return d
            s = s.parent
        obj = getattr(builtins, name, None)
        if obj is not None or hasattr(builtins, name):
            return Definition(name, *describe_val(val_from_obj(obj, name), name),
                              lineno=0, val=val_from_obj(obj, name))
        return None

    # -- inference ---------------------------------------------------------

    def _from_annotation(self, node, scope):
        if node is None:
            return UNKNOWN
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode='eval').body
            except Exception:
                return UNKNOWN
        if isinstance(node, ast.Subscript):
            node = node.value
        v = self._infer(node, scope)
        if v.kind == 'class':
            return Val('instance', v.name, node=v.node, owner=v.owner,
                       pytype=v.obj if inspect.isclass(v.obj) else None)
        if v.kind == 'module':
            return v
        return UNKNOWN

    def _infer(self, node, scope, line=None):
        try:
            return self._infer_inner(node, scope, line)
        except Exception:
            return UNKNOWN

    def _infer_inner(self, node, scope, line=None):
        if node is None:
            return UNKNOWN
        if isinstance(node, ast.Constant):
            v = node.value
            return Val('instance', type(v).__name__, pytype=type(v))
        if isinstance(node, ast.JoinedStr):
            return Val('instance', 'str', pytype=str)
        if isinstance(node, (ast.List, ast.ListComp)):
            return Val('instance', 'list', pytype=list)
        if isinstance(node, ast.Tuple):
            return Val('instance', 'tuple', pytype=tuple)
        if isinstance(node, (ast.Set, ast.SetComp)):
            return Val('instance', 'set', pytype=set)
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return Val('instance', 'dict', pytype=dict)
        if isinstance(node, ast.GeneratorExp):
            return Val('instance', 'generator', pytype=types.GeneratorType)
        if isinstance(node, ast.Lambda):
            return Val('function', '<lambda>', node=node, owner=self)
        if isinstance(node, ast.NamedExpr):
            return self._infer(node.value, scope, line)
        if isinstance(node, ast.IfExp):
            v = self._infer(node.body, scope, line)
            if v.kind != 'unknown':
                return v
            return self._infer(node.orelse, scope, line)
        if isinstance(node, ast.Name):
            d = self._lookup(scope, node.id, line)
            return d.val if d is not None else UNKNOWN
        if isinstance(node, ast.Attribute):
            base = self._infer(node.value, scope, line)
            v = attr_val(base, node.attr)
            return v if v is not None else UNKNOWN
        if isinstance(node, ast.Call):
            fv = self._infer(node.func, scope, line)
            if fv.kind == 'class':
                return Val('instance', fv.name, node=fv.node, owner=fv.owner,
                           pytype=fv.obj if inspect.isclass(fv.obj) else None)
            if fv.kind == 'function':
                if fv.node is not None and isinstance(
                        fv.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = fv.owner or self
                    ret = getattr(fv.node, 'returns', None)
                    if ret is not None:
                        return owner._from_annotation(ret, owner.module_scope)
                elif fv.obj is not None:
                    try:
                        ann = getattr(fv.obj, '__annotations__', {}) or {}
                        rt = ann.get('return')
                        if inspect.isclass(rt):
                            return Val('instance', rt.__name__, pytype=rt)
                    except Exception:
                        pass
            return UNKNOWN
        if isinstance(node, ast.Await):
            return UNKNOWN
        if isinstance(node, ast.Compare):
            return Val('instance', 'bool', pytype=bool)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return Val('instance', 'bool', pytype=bool)
        return UNKNOWN


# --------------------------------------------------------------------------
# attribute resolution
# --------------------------------------------------------------------------

def module_public_vals(target):
    """Yield (name, Val) pairs for the public names of a module."""
    out = []
    if target is None:
        return out
    if isinstance(target, Analysis):
        for name, lst in target.module_scope.defs.items():
            if name.startswith('_'):
                continue
            out.append((name, lst[-1].val))
        return out
    try:
        names = dir(target)
    except Exception:
        return out
    for name in names:
        if name.startswith('_'):
            continue
        try:
            obj = getattr(target, name)
        except Exception:
            continue
        out.append((name, val_from_obj(obj, name)))
    return out


def attr_of_module(target, attr):
    if target is None:
        return None
    if isinstance(target, Analysis):
        d = target.module_scope.lookup_local(attr)
        return d.val if d is not None else None
    try:
        obj = getattr(target, attr)
    except Exception:
        return None
    return val_from_obj(obj, attr)


def attr_val(val, attr):
    """Resolve `val.attr` to another Val."""
    if val is None or val.kind == 'unknown':
        return UNKNOWN
    if val.kind == 'module':
        target = materialize(val)
        v = attr_of_module(target, attr)
        return v if v is not None else UNKNOWN
    if val.kind in ('class', 'instance') and val.node is not None and val.owner is not None:
        members = class_members(val.node, val.owner,
                                include_instance=(val.kind == 'instance'))
        d = members.get(attr)
        return d.val if d is not None else UNKNOWN
    real = None
    if val.kind == 'class':
        real = val.obj
    elif val.kind == 'instance':
        real = val.pytype
    elif val.kind == 'function':
        real = val.obj if val.obj is not None else types.FunctionType
    if real is not None:
        try:
            obj = getattr(real, attr)
        except Exception:
            return UNKNOWN
        return val_from_obj(obj, attr)
    return UNKNOWN


def _class_bases(node, owner):
    """Yield (ClassDef, Analysis) for bases defined in an analysable file."""
    scope = owner.class_scopes.get(node)
    lookup_scope = scope.parent if scope is not None else owner.module_scope
    for base in node.bases:
        try:
            v = owner._infer(base, lookup_scope)
        except Exception:
            continue
        if v.kind == 'class' and v.node is not None and v.owner is not None:
            yield v.node, v.owner


def class_members(node, owner, include_instance=False, _seen=None):
    """Return {name: Definition} for a file-defined class."""
    if _seen is None:
        _seen = set()
    key = (id(owner), id(node))
    if key in _seen:
        return {}
    _seen.add(key)

    members = {}
    scope = owner.class_scopes.get(node)
    if scope is not None:
        for name, lst in scope.defs.items():
            members[name] = lst[-1]

    for base_node, base_owner in _class_bases(node, owner):
        inherited = class_members(base_node, base_owner,
                                  include_instance=include_instance,
                                  _seen=_seen)
        for name, d in inherited.items():
            members.setdefault(name, d)

    if include_instance:
        for name, d in instance_attrs(node, owner, set()).items():
            members.setdefault(name, d)
    return members


def instance_attrs(node, owner, seen):
    """`self.x = ...` assignments inside __init__ (own + inherited)."""
    key = (id(owner), id(node))
    if key in seen:
        return {}
    seen.add(key)
    out = {}
    for st in node.body:
        if not isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if st.name != '__init__':
            continue
        args = list(getattr(st.args, 'posonlyargs', []) or []) + list(st.args.args or [])
        if not args:
            continue
        selfname = args[0].arg
        fscope = owner.func_scopes.get(st, owner.module_scope)
        _collect_self_attrs(st.body, selfname, fscope, owner, out)
    for base_node, base_owner in _class_bases(node, owner):
        for name, d in instance_attrs(base_node, base_owner, seen).items():
            out.setdefault(name, d)
    return out


def _collect_self_attrs(stmts, selfname, fscope, owner, out):
    for st in stmts or []:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(st, ast.Assign):
            for tgt in st.targets:
                _self_target(tgt, st.value, selfname, fscope, owner, out, st.lineno)
        elif isinstance(st, ast.AnnAssign):
            _self_target(st.target, st.value, selfname, fscope, owner, out, st.lineno)
        elif isinstance(st, ast.AugAssign):
            _self_target(st.target, None, selfname, fscope, owner, out, st.lineno)
        for field in ('body', 'orelse', 'finalbody'):
            sub = getattr(st, field, None)
            if isinstance(sub, list):
                _collect_self_attrs(sub, selfname, fscope, owner, out)
        for h in getattr(st, 'handlers', []) or []:
            _collect_self_attrs(h.body, selfname, fscope, owner, out)


def _self_target(tgt, value, selfname, fscope, owner, out, lineno):
    if isinstance(tgt, (ast.Tuple, ast.List)):
        for elt in tgt.elts:
            _self_target(elt, None, selfname, fscope, owner, out, lineno)
        return
    if not isinstance(tgt, ast.Attribute):
        return
    if not (isinstance(tgt.value, ast.Name) and tgt.value.id == selfname):
        return
    val = owner._infer(value, fscope) if value is not None else UNKNOWN
    out[tgt.attr] = make_def(tgt.attr, lineno, val)


def attributes_for(val):
    """Return {name: (type, description)} for attribute completion."""
    result = {}
    if val is None or val.kind == 'unknown':
        return result

    if val.kind == 'module':
        target = materialize(val)
        for name, v in module_public_vals(target):
            result[name] = describe_val(v, name)
        return result

    if val.kind in ('class', 'instance') and val.node is not None and val.owner is not None:
        members = class_members(val.node, val.owner,
                                include_instance=(val.kind == 'instance'))
        for name, d in members.items():
            result[name] = (d.kind, d.description)
        return result

    real = None
    if val.kind == 'class':
        real = val.obj
    elif val.kind == 'instance':
        real = val.pytype if val.pytype is not None else (
            type(val.obj) if val.obj is not None else None)
    elif val.kind == 'function':
        real = val.obj if val.obj is not None else types.FunctionType

    if real is None:
        return result
    try:
        names = dir(real)
    except Exception:
        return result
    for name in names:
        try:
            obj = getattr(real, name)
        except Exception:
            result[name] = ('statement', 'statement')
            continue
        result[name] = describe_val(val_from_obj(obj, name), name)
    return result


# --------------------------------------------------------------------------
# cursor context
# --------------------------------------------------------------------------

def read_prefix(text, col):
    i = col
    while i > 0 and is_ident_char(text[i - 1]):
        i -= 1
    return text[i:col], i


def scan_receiver(text, end):
    """Scan backwards from *end* (exclusive) collecting an expression."""
    i = end
    while i > 0 and text[i - 1] in ' \t':
        i -= 1
    stop = i
    depth = 0
    while i > 0:
        c = text[i - 1]
        if c in ')]}':
            depth += 1
            i -= 1
        elif c in '([{':
            if depth == 0:
                break
            depth -= 1
            i -= 1
        elif c in '"\'':
            quote = c
            k = i - 2
            found = -1
            while k >= 0:
                if text[k] == quote and (k == 0 or text[k - 1] != '\\'):
                    found = k
                    break
                k -= 1
            if found < 0:
                break
            i = found
            while i > 0 and text[i - 1].isalpha():
                i -= 1
        elif is_ident_char(c) or c == '.':
            i -= 1
        elif depth > 0:
            i -= 1
        elif c in ' \t' and depth == 0:
            # allow whitespace only inside brackets
            break
        else:
            break
    return text[i:stop]


def analyze_cursor(text, col):
    """Return (mode, prefix, receiver_text)."""
    prefix, start = read_prefix(text, col)
    j = start
    while j > 0 and text[j - 1] in ' \t':
        j -= 1
    if j > 0 and text[j - 1] == '.':
        recv = scan_receiver(text, j - 1)
        return 'attr', prefix, recv
    return 'name', prefix, None


# --------------------------------------------------------------------------
# matching / ordering
# --------------------------------------------------------------------------

def matches(name, prefix, fuzzy):
    if not prefix:
        return True
    n = name.lower()
    p = prefix.lower()
    if not fuzzy:
        return n.startswith(p)
    pos = 0
    for ch in p:
        pos = n.find(ch, pos)
        if pos < 0:
            return False
        pos += 1
    return True


def make_item(name, kind, description, prefix):
    return {
        'name': name,
        'complete': name[len(prefix):],
        'type': kind,
        'description': description,
    }


def order(items):
    return sorted(items, key=lambda it: (name_group(it['name']),
                                         it['name'].lower(), it['name']))


# --------------------------------------------------------------------------
# completion driver
# --------------------------------------------------------------------------

class Completer(object):
    def __init__(self, analysis, lines):
        self.a = analysis
        self.lines = lines

    # -- scope selection ---------------------------------------------------

    def scope_at(self, line, col):
        text = self.lines[line - 1] if 0 <= line - 1 < len(self.lines) else ''
        if text[:col].strip() == '':
            cur_indent = col
        else:
            cur_indent = len(text) - len(text.lstrip())
        best = self.a.module_scope
        stack = [(self.a.module_scope, 0)]
        best_depth = 0
        while stack:
            scope, depth = stack.pop()
            for child in scope.children:
                if self._contains(child, line, cur_indent):
                    if depth + 1 >= best_depth:
                        best = child
                        best_depth = depth + 1
                    stack.append((child, depth + 1))
        return best

    def _contains(self, scope, line, cur_indent):
        if scope.start <= line <= scope.end:
            return True
        if line <= scope.end:
            return False
        col_off = scope.col_offset
        if col_off < 0 or cur_indent <= col_off:
            return False
        for idx in range(scope.end, min(line - 1, len(self.lines))):
            t = self.lines[idx]
            s = t.strip()
            if not s or s.startswith('#'):
                continue
            ind = len(t) - len(t.lstrip())
            if ind <= col_off:
                return False
        return True

    # -- visible names -----------------------------------------------------

    def visible(self, line, col):
        scope = self.scope_at(line, col)
        result = {}

        # comprehension targets around the cursor
        for name, d in self._comprehension_names(scope, line).items():
            result.setdefault(name, d)

        chain = []
        s = scope
        while s is not None:
            chain.append(s)
            s = s.parent
        for idx, s in enumerate(chain):
            if s.kind == 'class' and idx != 0:
                continue
            positional = (idx == 0) or (s.kind == 'module')
            for name, lst in s.defs.items():
                if name in result:
                    continue
                if positional:
                    d = None
                    for cand in lst:
                        if cand.lineno <= line:
                            d = cand
                    if d is None:
                        continue
                else:
                    d = lst[-1]
                result[name] = d

        for name in dir(builtins):
            if name in result or name in _KEYWORD_SET:
                continue
            try:
                obj = getattr(builtins, name)
            except Exception:
                continue
            kind, desc = describe_val(val_from_obj(obj, name), name)
            result[name] = Definition(name, kind, desc, 0)
        return result

    def _comprehension_names(self, scope, line):
        out = {}
        node = scope.node
        try:
            for n in ast.walk(node):
                if not isinstance(n, (ast.ListComp, ast.SetComp,
                                      ast.DictComp, ast.GeneratorExp)):
                    continue
                if not (getattr(n, 'lineno', 0) <= line <= end_line_of(n)):
                    continue
                for gen in n.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            out[t.id] = Definition(t.id, 'statement',
                                                   'statement', n.lineno)
        except Exception:
            pass
        return out

    # -- entry point -------------------------------------------------------

    def complete(self, line, col, fuzzy):
        text = self.lines[line - 1]
        mode, prefix, recv = analyze_cursor(text, col)
        if mode == 'attr':
            return self._attr_completions(line, col, prefix, recv, fuzzy)
        return self._name_completions(line, col, prefix, fuzzy)

    def _name_completions(self, line, col, prefix, fuzzy):
        names = self.visible(line, col)
        items = []
        for name, d in names.items():
            if matches(name, prefix, fuzzy):
                items.append(make_item(name, d.kind, d.description, prefix))
        items = order(items)
        kw = [make_item(k, 'keyword', k, prefix)
              for k in KEYWORDS if matches(k, prefix, fuzzy)]
        kw.sort(key=lambda it: (it['name'].lower(), it['name']))
        return items + kw

    def _attr_completions(self, line, col, prefix, recv, fuzzy):
        if not recv or not recv.strip():
            return []
        val = self._resolve_receiver(recv, line, col)
        attrs = attributes_for(val)
        items = []
        for name, (kind, desc) in attrs.items():
            if matches(name, prefix, fuzzy):
                items.append(make_item(name, kind, desc, prefix))
        return order(items)

    def _resolve_receiver(self, recv, line, col):
        expr = None
        text = recv.strip()
        for candidate in (text, text.rstrip('.')):
            if not candidate:
                continue
            try:
                expr = ast.parse(candidate, mode='eval').body
                break
            except SyntaxError:
                expr = None
            except Exception:
                expr = None
        if expr is None:
            return UNKNOWN
        scope = self.scope_at(line, col)
        return self.a._infer(expr, scope, line)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def die(msg):
    sys.stderr.write('sith: %s\n' % msg)
    sys.exit(1)


def main(argv):
    args = argv[1:]
    fuzzy = False
    positional = []
    for a in args:
        if a == '--fuzzy':
            fuzzy = True
        elif a == '--':
            continue
        elif a.startswith('--'):
            die('unknown option: %s' % a)
        else:
            positional.append(a)

    if not positional:
        die('usage: sith.py complete <file> <line> <col> [--fuzzy]')
    command = positional[0]
    if command != 'complete':
        die('unknown command: %s' % command)
    if len(positional) != 4:
        die('usage: sith.py complete <file> <line> <col> [--fuzzy]')

    path = positional[1]
    try:
        line = int(positional[2])
        col = int(positional[3])
    except ValueError:
        die('line and column must be integers')

    if not os.path.exists(path):
        die('no such file: %s' % path)
    if not os.path.isfile(path):
        die('not a regular file: %s' % path)
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError as exc:
        die('cannot read %s: %s' % (path, exc))

    try:
        source = raw.decode('utf-8')
    except UnicodeDecodeError:
        die('file is not valid UTF-8: %s' % path)

    if source.startswith('﻿'):
        source = source[1:]
    source = source.replace('\r\n', '\n').replace('\r', '\n')
    lines = source.split('\n')

    if line < 1 or line > len(lines):
        die('line out of range: %d' % line)
    if col < 0 or col > len(lines[line - 1]):
        die('column out of range: %d' % col)

    completions = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            analysis = Analysis(source, path)
            completer = Completer(analysis, lines)
            completions = completer.complete(line, col, fuzzy)
    except Exception:
        try:
            with contextlib.redirect_stdout(buf):
                completions = _fallback(lines, line, col, fuzzy)
        except Exception:
            completions = []

    out = json.dumps({'completions': completions}, separators=(',', ':'))
    sys.stdout.write(out + '\n')
    return 0


def _fallback(lines, line, col, fuzzy):
    text = lines[line - 1]
    mode, prefix, _recv = analyze_cursor(text, col)
    if mode == 'attr':
        return []
    items = []
    for name in dir(builtins):
        if name in _KEYWORD_SET or not matches(name, prefix, fuzzy):
            continue
        try:
            obj = getattr(builtins, name)
        except Exception:
            continue
        kind, desc = describe_val(val_from_obj(obj, name), name)
        items.append(make_item(name, kind, desc, prefix))
    items = order(items)
    kw = [make_item(k, 'keyword', k, prefix)
          for k in KEYWORDS if matches(k, prefix, fuzzy)]
    kw.sort(key=lambda it: (it['name'].lower(), it['name']))
    return items + kw


if __name__ == '__main__':
    sys.exit(main(sys.argv))
