#!/usr/bin/env python3
"""sith -- a small static Python code-intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project DIR]
    python sith.py infer <file> <line> <col> [--project DIR]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project DIR]
    python sith.py signatures <file> <line> <col> [--project DIR]
    python sith.py references <file> <line> <col> [--scope file|project]
                              [--project DIR]
    python sith.py search <query> [--project DIR]
    python sith.py names <file> [--all-scopes] [--project DIR]

Parses a Python project (tolerating syntax errors) and answers questions
about the cursor position, printing a compact JSON object on stdout:

  complete    ranked completions visible at the cursor
  infer       what the name at the cursor evaluates to
  goto        where the name at the cursor was defined or assigned
  signatures  the signature(s) of the call the cursor sits in
  references  every occurrence of the symbol under the cursor
  search      project-wide search for definitions whose name matches
  names       the names a file defines

`infer`, `goto`, `search` and `names` print {"definitions": [...]}; `infer`,
`goto` and `references` exit 1 when the cursor is not on a name.

Type information is read from a `.pyi` stub when one sits next to the module
or under `<project>/stubs/`; `goto` still points at the real source.  Where a
function has neither annotations nor a stub, parameter types are inferred from
its call sites in the same file (`--no-dynamic-params` turns that off).

Imports are resolved against the project root -- `--project DIR` when given,
otherwise the directory holding <file>.  Modules are looked for in the project
root first and in the standard library second; anything else is unresolvable.
`goto --follow-imports` chases import chains to the definition in the module
they come from, falling back to the import statement itself when the chain
leaves the project.
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
import re
import sys
import tokenize
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


def none_val():
    return Val('instance', 'NoneType', pytype=type(None))


def dedup_vals(vals):
    """Remove duplicate / useless values, preserving order."""
    out = []
    seen = set()
    for v in vals or []:
        if v is None or v.kind == 'unknown':
            continue
        key = val_key(v)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def val_key(v):
    if v is None:
        return ('none',)
    node = id(v.node) if v.node is not None else None
    owner = id(v.owner) if v.owner is not None else None
    obj = None
    if v.node is None:
        try:
            obj = id(v.obj) if v.obj is not None else None
        except Exception:
            obj = None
    return (v.kind, v.name, node, owner, obj,
            getattr(v.pytype, '__name__', None), v.modname)


class Definition(object):
    """A binding of a name, with (lazily inferred) values."""

    def __init__(self, name, kind=None, description=None, lineno=0, val=None,
                 vals=None, thunk=None, col=0, node=None, owner=None,
                 qual='', doc='', gkind=None, gdesc=None):
        self.name = name
        self._kind = kind
        self._description = description
        self.lineno = lineno
        self.col = col
        self.node = node            # AST node of the binding
        self.owner = owner          # Analysis owning `node`
        self.qual = qual            # dotted prefix of the enclosing scope
        self.doc = doc
        self._gkind = gkind
        self._gdesc = gdesc
        self._thunk = thunk
        self.import_ref = None      # (owner, module, level, name|None)
        self.is_stub = False        # binding that only exists in a stub
        if vals is None and val is not None:
            vals = [val]
        self._vals = vals
        self._busy = False
        self.flowpath = ()

    # -- values ------------------------------------------------------------

    @property
    def vals(self):
        if self._vals is None:
            if self._thunk is None:
                return []
            if self._busy:
                return []
            self._busy = True
            try:
                computed = dedup_vals(self._thunk())
            except Exception:
                computed = []
            finally:
                self._busy = False
            self._vals = computed
        return self._vals

    def set_vals(self, vals):
        self._vals = list(vals)
        self._thunk = None

    @property
    def val(self):
        for v in self.vals:
            if v is not None and v.kind != 'unknown':
                return v
        return UNKNOWN

    @val.setter
    def val(self, value):
        self.set_vals([value])

    # -- display -----------------------------------------------------------

    @property
    def kind(self):
        if self._kind is not None:
            return self._kind
        return describe_val(self.val, self.name)[0]

    @property
    def description(self):
        if self._description is not None:
            return self._description
        return describe_val(self.val, self.name)[1]

    @property
    def goto_kind(self):
        return self._gkind if self._gkind is not None else self.kind

    @property
    def goto_description(self):
        return self._gdesc if self._gdesc is not None else self.description

    @property
    def full_name(self):
        parts = []
        if self.owner is not None:
            parts.append(module_name_of(self.owner))
        if self.qual:
            parts.append(self.qual)
        parts.append(self.name)
        return '.'.join([p for p in parts if p])


def join_qual(prefix, name):
    return (prefix + '.' + name) if prefix else name


def safe_docstring(node):
    try:
        return ast.get_docstring(node, clean=True) or ''
    except Exception:
        return ''


def unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return ''


def func_description(node):
    """`def name(params)` for a FunctionDef node."""
    try:
        params = unparse(node.args)
    except Exception:
        params = ''
    return 'def %s(%s)' % (node.name, params)


def decorator_names(node):
    out = set()
    for d in getattr(node, 'decorator_list', []) or []:
        target = d.func if isinstance(d, ast.Call) else d
        dotted = dotted_name(target)
        if dotted:
            out.add(dotted)
            out.add(dotted.split('.')[-1])
    return out


def dotted_name(node):
    """Dotted source name of a Name/Attribute expression, else None."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return '.'.join(reversed(parts))


def instance_of(val):
    """Turn a class value into an instance value."""
    if val is None:
        return None
    if val.kind == 'class':
        return Val('instance', val.name, node=val.node, owner=val.owner,
                   pytype=val.obj if inspect.isclass(val.obj) else None)
    if val.kind == 'instance':
        return val
    return None


def reachability(defpath, curpath):
    """'reachable' | 'unsure' | 'unreachable' for a binding vs the cursor."""
    cur = dict(curpath or ())
    definite = True
    for nid, branch in defpath or ():
        if nid in cur:
            if cur[nid] != branch:
                return 'unreachable'
        else:
            definite = False
    return 'reachable' if definite else 'unsure'


def reachable_defs(defs, cur_flow=()):
    """Filter bindings to those reachable from *cur_flow* (latest first stop)."""
    out = []
    for d in sorted(defs, key=lambda d: (d.lineno, d.col), reverse=True):
        state = reachability(d.flowpath, cur_flow)
        if state == 'unreachable':
            continue
        out.append(d)
        if state == 'reachable':
            break
    out.reverse()
    return out


def flow_of(narrow):
    if not narrow:
        return ()
    return narrow.get('*flow*', ())


def builtin_def(name):
    if not hasattr(builtins, name):
        return None
    try:
        obj = getattr(builtins, name)
    except Exception:
        return None
    return Definition(name, lineno=0, val=val_from_obj(obj, name))


def param_defaults(args):
    """Map id(arg node) -> default value node."""
    out = {}
    try:
        positional = list(getattr(args, 'posonlyargs', []) or []) + \
            list(args.args or [])
        defaults = list(args.defaults or [])
        if defaults:
            for p, d in zip(positional[len(positional) - len(defaults):],
                            defaults):
                if d is not None:
                    out[id(p)] = d
        for p, d in zip(args.kwonlyargs or [], args.kw_defaults or []):
            if d is not None:
                out[id(p)] = d
    except Exception:
        return out
    return out


def collect_returns(fnode):
    """(return nodes, yield nodes) directly inside *fnode*."""
    returns = []
    yields = []
    stack = list(getattr(fnode, 'body', []) or [])
    while stack:
        n = stack.pop(0)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                          ast.ClassDef)):
            continue
        if isinstance(n, ast.Return):
            returns.append(n)
        if isinstance(n, (ast.Yield, ast.YieldFrom)):
            yields.append(n)
        stack = list(ast.iter_child_nodes(n)) + stack
    returns.sort(key=lambda n: (n.lineno, n.col_offset))
    return returns, yields


TYPING_ALIASES = {
    'List': list, 'Dict': dict, 'Set': set, 'FrozenSet': frozenset,
    'Tuple': tuple, 'Text': str, 'DefaultDict': dict, 'OrderedDict': dict,
    'Sequence': list, 'MutableSequence': list, 'Mapping': dict,
    'MutableMapping': dict,
}


_NUMERIC = (bool, int, float, complex)


def binop_type(a, b, op):
    """Result type of `a <op> b` for simple builtin operand types."""
    try:
        if a is b:
            if a is bool and not isinstance(op, (ast.BitAnd, ast.BitOr,
                                                 ast.BitXor)):
                return int
            if a in (int, float, complex, str, bytes, list, tuple, set, dict):
                if a is dict and not isinstance(op, ast.BitOr):
                    return None
                return a
            return None
        if a in _NUMERIC and b in _NUMERIC:
            for t in (complex, float, int):
                if a is t or b is t:
                    return t
            return int
        if isinstance(op, ast.Mult):
            if a in (str, bytes, list, tuple) and b in (int, bool):
                return a
            if b in (str, bytes, list, tuple) and a in (int, bool):
                return b
        if isinstance(op, ast.Mod) and a in (str, bytes):
            return a
    except Exception:
        return None
    return None



# --------------------------------------------------------------------------
# scopes
# --------------------------------------------------------------------------

class Scope(object):
    def __init__(self, kind, node, parent, start, end, qualname=''):
        self.kind = kind            # module|function|class|lambda
        self.node = node
        self.qualname = qualname    # dotted path of this scope inside its module
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
_namespace_cache = {}

PROJECT_ROOT = [None]

try:
    STDLIB_NAMES = frozenset(sys.stdlib_module_names)
except Exception:                                        # pragma: no cover
    STDLIB_NAMES = frozenset(getattr(sys, 'builtin_module_names', ()))


def set_project_root(path):
    PROJECT_ROOT[0] = os.path.abspath(path) if path else None


def project_root():
    return PROJECT_ROOT[0] or os.getcwd()


def posix_path(path):
    """Paths in the output always use forward slashes."""
    return path.replace(os.sep, '/') if path else ''


def rel_module_path(path):
    """File path relative to the project root (or absolute when outside)."""
    if not path:
        return ''
    path = os.path.abspath(path)
    root = project_root()
    try:
        rel = os.path.relpath(path, root)
    except Exception:
        return posix_path(path)
    if rel.startswith('..') or os.path.isabs(rel):
        return posix_path(path)
    return posix_path(rel)


def _strip_py(name):
    for ext in ('.py', '.pyi'):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def module_dotted_name(path):
    """Dotted module name of *path*, computed from the project root."""
    if not path:
        return ''
    path = os.path.abspath(path)
    root = project_root()
    try:
        rel = os.path.relpath(path, root)
    except Exception:
        rel = None
    if rel is None or rel.startswith('..') or os.path.isabs(rel):
        return _strip_py(os.path.basename(path))
    parts = [p for p in rel.replace(os.sep, '/').split('/') if p and p != '.']
    if not parts:
        return ''
    if path.endswith('.pyi') and len(parts) > 1 and parts[0] == STUB_DIRNAME:
        parts = parts[1:]           # `stubs/foo.pyi` stands in for `foo`
    parts[-1] = _strip_py(parts[-1])
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def module_name_of(analysis):
    """Dotted module name of an analysed file, based at the project root."""
    return module_dotted_name(getattr(analysis, 'path', None))


def is_within(root, path):
    root = os.path.abspath(root)
    path = os.path.abspath(path)
    return path == root or path.startswith(root + os.sep)


def find_project_module(base, dotted):
    """Locate *dotted* under *base*.

    Returns the path of a module file, of a package `__init__.py`, or of a
    namespace-package directory -- or None when nothing matches.
    """
    parts = [p for p in dotted.split('.') if p]
    if not parts:
        return None
    cur = base
    for i, part in enumerate(parts):
        last = (i == len(parts) - 1)
        pkgdir = os.path.join(cur, part)
        init = os.path.join(pkgdir, '__init__.py')
        modfile = os.path.join(cur, part + '.py')
        if last:
            if os.path.isfile(init):
                return init
            if os.path.isfile(modfile):
                return modfile
            if os.path.isdir(pkgdir):
                return pkgdir
            return None
        if os.path.isdir(pkgdir):
            cur = pkgdir
        else:
            return None
    return None


# --------------------------------------------------------------------------
# stub files (.pyi)
# --------------------------------------------------------------------------

STUB_DIRNAME = 'stubs'

DYNAMIC_PARAMS = [True]


def find_stub_path(path):
    """The `.pyi` stub describing the module at *path*, or None.

    Looked for next to the module first, then under `<root>/stubs/`.
    """
    if not path or not path.endswith('.py'):
        return None
    inline = path[:-3] + '.pyi'
    if os.path.isfile(inline):
        return inline
    dotted = module_dotted_name(path)
    if not dotted:
        return None
    return find_stub_module(dotted)


def find_stub_module(dotted):
    """`<root>/stubs/<dotted>.pyi` (or its package `__init__.pyi`), or None."""
    parts = [p for p in (dotted or '').split('.') if p]
    if not parts:
        return None
    stubs = os.path.join(project_root(), STUB_DIRNAME)
    if not os.path.isdir(stubs):
        return None
    cand = os.path.join(stubs, *parts) + '.pyi'
    if os.path.isfile(cand):
        return cand
    cand = os.path.join(os.path.join(stubs, *parts), '__init__.pyi')
    if os.path.isfile(cand):
        return cand
    return None


def find_arg(fnode, name):
    """The `ast.arg` called *name* of a function node, or None."""
    a = getattr(fnode, 'args', None)
    if a is None:
        return None
    everything = list(getattr(a, 'posonlyargs', []) or []) + \
        list(a.args or []) + list(a.kwonlyargs or [])
    if a.vararg is not None:
        everything.append(a.vararg)
    if a.kwarg is not None:
        everything.append(a.kwarg)
    for p in everything:
        if p.arg == name:
            return p
    return None


def merged_stub_def(pydef, stubdef):
    """A binding located in the source but typed by the stub."""
    d = Definition(pydef.name, lineno=pydef.lineno, col=pydef.col,
                   node=pydef.node, owner=pydef.owner, qual=pydef.qual,
                   doc=pydef.doc or stubdef.doc,
                   gkind=pydef._gkind, gdesc=pydef._gdesc,
                   thunk=(lambda s=stubdef: list(s.vals)))
    d._kind = pydef._kind
    d._description = pydef._description
    d.flowpath = pydef.flowpath
    d.import_ref = pydef.import_ref
    return d


def _is_func_node(node):
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def overlay_scope(pyscope, stubscope, pya, stuba):
    """Fold the declarations of a stub scope into the matching real scope."""
    for name, slist in stubscope.defs.items():
        if not slist:
            continue
        sdef = slist[-1]
        plist = pyscope.defs.get(name)
        if not plist:
            for sd in slist:
                sd.is_stub = True
            pyscope.defs[name] = list(slist)
            continue
        pdef = plist[-1]
        if isinstance(sdef.node, ast.ClassDef) and \
                isinstance(pdef.node, ast.ClassDef):
            pya.stub_map[id(pdef.node)] = (sdef.node, stuba)
            ps = pya.class_scopes.get(pdef.node)
            ss = stuba.class_scopes.get(sdef.node)
            if ps is not None and ss is not None:
                overlay_scope(ps, ss, pya, stuba)
            continue
        if _is_func_node(sdef.node) and _is_func_node(pdef.node):
            for pd in plist:
                if _is_func_node(pd.node):
                    pya.stub_map[id(pd.node)] = (sdef.node, stuba)
            continue
        if sdef.node is None:
            continue
        pyscope.defs[name] = plist[:-1] + [merged_stub_def(pdef, sdef)]


def analyze_path(path):
    path = os.path.abspath(path)
    if path in _analysis_cache:
        return _analysis_cache[path]
    _analysis_cache[path] = None            # recursion guard
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
        src = data.decode('utf-8', 'replace')
        if src.startswith('\ufeff'):
            src = src[1:]
        src = src.replace('\r\n', '\n').replace('\r', '\n')
        analysis = Analysis(src, path)
    except Exception:
        analysis = None
    _analysis_cache[path] = analysis
    return analysis


def namespace_analysis(dirpath):
    """A stand-in Analysis for a namespace package (a directory)."""
    dirpath = os.path.abspath(dirpath)
    a = _namespace_cache.get(dirpath)
    if a is None:
        try:
            a = Analysis('', dirpath)
        except Exception:
            return None
        a.dirpath = dirpath
        a.is_namespace = True
        _namespace_cache[dirpath] = a
    return a


def analyze_module_path(path):
    """Analysis for a module file or a namespace-package directory."""
    if not path:
        return None
    if os.path.isdir(path):
        return namespace_analysis(path)
    return analyze_path(path)


def _import_real(dotted):
    """Look up a standard-library module in the running interpreter."""
    if not dotted:
        return None
    if dotted.split('.')[0] not in STDLIB_NAMES:
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


def relative_base(base_dir, level):
    """Directory a relative import of *level* dots is anchored at."""
    base = os.path.abspath(base_dir or project_root())
    for _ in range(max(level - 1, 0)):
        parent = os.path.dirname(base)
        if parent == base:
            return None
        base = parent
    if not is_within(project_root(), base):
        return None                 # climbed above the project root
    return base


def resolve_module(base_dir, dotted, level=0):
    """Return an Analysis (project file) or a real module object, or None."""
    if level:
        base = relative_base(base_dir, level)
        if base is None:
            return None
        if not dotted:
            init = os.path.join(base, '__init__.py')
            if os.path.isfile(init):
                return analyze_path(init)
            return namespace_analysis(base)
        found = find_project_module(base, dotted)
        return analyze_module_path(found) if found else None
    if not dotted:
        return None
    found = find_project_module(project_root(), dotted)
    if found is not None:
        return analyze_module_path(found)
    found = find_stub_module(dotted)
    if found is not None:
        return analyze_module_path(found)
    return _import_real(dotted)


def materialize(val):
    """Resolve a lazy module Val to an Analysis / real module."""
    if val is None or val.kind != 'module':
        return None
    if val.obj is None and not val._resolved and val.modname:
        val._resolved = True
        base = val.owner.dirpath if val.owner is not None else project_root()
        val.obj = resolve_module(base, val.modname, val.level)
    return val.obj


# --------------------------------------------------------------------------
# module contents
# --------------------------------------------------------------------------

def _string_seq(node):
    """The list of string constants in a List/Tuple/Set literal, else None."""
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    out = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
    return out


def module_all_names(target):
    """`__all__` of a module, or None when it does not define one."""
    if target is None:
        return None
    if isinstance(target, Analysis):
        result = None
        try:
            for st in getattr(target.tree, 'body', []) or []:
                if isinstance(st, ast.Assign):
                    targets, value = st.targets, st.value
                elif isinstance(st, (ast.AnnAssign, ast.AugAssign)):
                    targets, value = [st.target], st.value
                else:
                    continue
                if not any(isinstance(t, ast.Name) and t.id == '__all__'
                           for t in targets):
                    continue
                names = _string_seq(value)
                if names is None:
                    continue
                if isinstance(st, ast.AugAssign):
                    result = (result or []) + names
                else:
                    result = list(names)
        except Exception:
            return result
        return result
    try:
        names = getattr(target, '__all__', None)
    except Exception:
        return None
    if names is None:
        return None
    try:
        return [n for n in names if isinstance(n, str)]
    except Exception:
        return None


def module_export_names(target):
    """[(name, Val)] for the names a module exports (`__all__` aware)."""
    out = []
    if target is None:
        return out
    allnames = module_all_names(target)
    if isinstance(target, Analysis):
        defs = target.module_scope.defs
        if allnames is not None:
            for name in allnames:
                lst = defs.get(name)
                if lst:
                    out.append((name, lst[-1].val))
            return out
        for name, lst in defs.items():
            if not name.startswith('_'):
                out.append((name, lst[-1].val))
        return out
    if allnames is not None:
        for name in allnames:
            try:
                obj = getattr(target, name)
            except Exception:
                continue
            out.append((name, val_from_obj(obj, name)))
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


def module_export_items(target):
    """{name: (type, description)} for `from <module> import ...`."""
    out = {}
    for name, val in module_export_names(target):
        out[name] = describe_val(val, name)
    return out


def module_submodule(target, attr):
    """Resolve `<target>.<attr>` as a submodule, or None."""
    if isinstance(target, Analysis):
        dotted = module_name_of(target)
        if not dotted:
            return None
        return resolve_module(target.dirpath, dotted + '.' + attr, 0)
    return None


def _has_python_files(dirpath):
    try:
        for entry in os.listdir(dirpath):
            if entry.endswith('.py'):
                return True
            sub = os.path.join(dirpath, entry)
            if os.path.isdir(sub) and \
                    os.path.isfile(os.path.join(sub, '__init__.py')):
                return True
    except Exception:
        return False
    return False


def dir_module_names(dirpath):
    """Importable module / package names directly inside *dirpath*."""
    out = []
    try:
        entries = sorted(os.listdir(dirpath))
    except Exception:
        return out
    seen = set()
    for entry in entries:
        full = os.path.join(dirpath, entry)
        if os.path.isfile(full) and entry.endswith('.py'):
            name = entry[:-3]
            if name == '__init__' or not name.isidentifier():
                continue
        elif os.path.isdir(full):
            name = entry
            if not name.isidentifier() or name == '__pycache__':
                continue
            if not os.path.isfile(os.path.join(full, '__init__.py')) and \
                    not _has_python_files(full):
                continue
        else:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def top_level_module_items():
    """{name: (type, description)} for `import <cursor>`."""
    items = {}
    for name in dir_module_names(project_root()):
        items[name] = ('module', 'module %s' % name)
    for name in STDLIB_NAMES:
        items.setdefault(name, ('module', 'module %s' % name))
    return items


def submodule_items(target):
    """{name: (type, description)} for the submodules of a package."""
    items = {}
    dirs = []
    if isinstance(target, Analysis):
        path = target.path or ''
        if path and os.path.isdir(path):
            dirs.append(path)
        elif path and os.path.basename(path) == '__init__.py':
            dirs.append(os.path.dirname(path))
    elif target is not None:
        try:
            dirs.extend([d for d in (getattr(target, '__path__', None) or [])
                         if isinstance(d, str)])
        except Exception:
            pass
    for d in dirs:
        for name in dir_module_names(d):
            items.setdefault(name, ('module', 'module %s' % name))
    return items


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
        self._flow = []
        self._ret_busy = set()
        self._dataclass_cache = {}
        self._dyn_busy = set()
        self.stub = None            # Analysis of the matching .pyi, if any
        self.stub_map = {}          # id(py node) -> (stub node, stub Analysis)
        try:
            self.docstring = ast.get_docstring(self.tree) or ''
        except Exception:
            self.docstring = ''
        self.module_scope = Scope('module', self.tree, None, 1, 10 ** 9, '')
        try:
            self._body(getattr(self.tree, 'body', []), self.module_scope)
        except Exception:
            pass
        try:
            self._link_stub()
        except Exception:
            pass

    # -- stub files --------------------------------------------------------

    def _link_stub(self):
        """Attach the `.pyi` stub matching this module, when there is one."""
        path = self.path
        if not path or not path.endswith('.py'):
            return
        stub_path = find_stub_path(path)
        if not stub_path:
            return
        stub = analyze_path(stub_path)
        if stub is None or stub is self:
            return
        self.stub = stub
        overlay_scope(self.module_scope, stub.module_scope, self, stub)

    def stub_node(self, node):
        """The stub counterpart of a class / function node, or None."""
        return self.stub_map.get(id(node))

    def scope_containing(self, lineno):
        """Innermost scope whose line range covers *lineno*."""
        best = self.module_scope
        best_depth = 0
        stack = [(self.module_scope, 0)]
        while stack:
            scope, depth = stack.pop()
            for child in scope.children:
                if child.start <= lineno <= child.end:
                    if depth + 1 >= best_depth:
                        best = child
                        best_depth = depth + 1
                    stack.append((child, depth + 1))
        return best

    # -- source helpers ----------------------------------------------------

    def line_text(self, lineno):
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1]
        return ''

    def node_src(self, node):
        """Source text of *node*, whitespace collapsed."""
        if node is None:
            return ''
        try:
            lineno = node.lineno
            end = getattr(node, 'end_lineno', None) or lineno
            c0 = node.col_offset
            c1 = getattr(node, 'end_col_offset', None)
        except Exception:
            return ''
        if lineno == end:
            text = self.line_text(lineno)
            txt = text[c0:c1] if c1 is not None else text[c0:]
        else:
            parts = [self.line_text(lineno)[c0:]]
            for ln in range(lineno + 1, end):
                parts.append(self.line_text(ln))
            last = self.line_text(end)
            parts.append(last[:c1] if c1 is not None else last)
            txt = ' '.join(p.strip() for p in parts)
        return re.sub(r'\s+', ' ', txt).strip()

    def ident_col(self, lineno, name, after=0):
        """Column of identifier *name* on *lineno*, searching from *after*."""
        text = self.line_text(lineno)
        try:
            for m in re.finditer(r'(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])'
                                 % re.escape(name), text):
                if m.start() >= after:
                    return m.start()
        except Exception:
            pass
        idx = text.find(name, after)
        return idx if idx >= 0 else max(after, 0)

    def def_name_col(self, node):
        """Column of the identifier of a def/class statement."""
        try:
            col = node.col_offset
            skip = 6 if isinstance(node, ast.ClassDef) else 4
            return self.ident_col(node.lineno, node.name, col + skip - 1)
        except Exception:
            return 0

    # -- scope construction ------------------------------------------------

    def _add(self, scope, definition):
        definition.flowpath = tuple(self._flow)
        scope.add(definition)
        return definition

    def _flow_body(self, stmts, scope, node, branch):
        self._flow.append((id(node), branch))
        try:
            self._body(stmts, scope)
        finally:
            self._flow.pop()

    def _body(self, stmts, scope):
        for st in stmts or []:
            try:
                self._stmt(st, scope)
            except Exception:
                pass

    def _stmt(self, node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            val = Val('function', node.name, node=node, owner=self)
            self._add(scope, Definition(
                node.name, 'function', 'def %s(...)' % node.name, node.lineno,
                val=val, col=self.def_name_col(node), node=node, owner=self,
                qual=scope.qualname, doc=safe_docstring(node),
                gdesc=func_description(node)))
            self._function(node, scope)
            return
        if isinstance(node, ast.ClassDef):
            val = Val('class', node.name, node=node, owner=self)
            self._add(scope, Definition(
                node.name, 'class', 'class %s' % node.name, node.lineno,
                val=val, col=self.def_name_col(node), node=node, owner=self,
                qual=scope.qualname, doc=safe_docstring(node),
                gdesc='class %s' % node.name))
            self._class(node, scope)
            return
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                self._bind_target(tgt, node.value, scope, node.lineno,
                                  stmt=node)
            self._walrus(node.value, scope)
            return
        if isinstance(node, ast.AnnAssign):
            self._bind_target(node.target, node.value, scope, node.lineno,
                              annotation=node.annotation, stmt=node)
            self._walrus(node.value, scope)
            return
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                existing = scope.lookup_local(node.target.id)
                vals = list(existing.vals) if existing else []
                self._add(scope, Definition(
                    node.target.id, lineno=node.lineno, vals=vals,
                    col=node.target.col_offset, node=node, owner=self,
                    qual=scope.qualname, gkind='statement',
                    gdesc=self.node_src(node)))
            self._walrus(node.value, scope)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._bind_target(node.target, None, scope, node.lineno,
                              stmt=node, gdesc=self.node_src(node.iter),
                              iter_node=node.iter)
            self._walrus(node.iter, scope)
            self._flow_body(node.body, scope, node, 'body')
            self._flow_body(node.orelse, scope, node, 'else')
            return
        if isinstance(node, ast.While):
            self._walrus(node.test, scope)
            self._flow_body(node.body, scope, node, 'body')
            self._flow_body(node.orelse, scope, node, 'else')
            return
        if isinstance(node, ast.If):
            self._walrus(node.test, scope)
            self._flow_body(node.body, scope, node, 'body')
            self._flow_body(node.orelse, scope, node, 'else')
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, item.context_expr,
                                      scope, node.lineno, stmt=node,
                                      gdesc=self.node_src(item.context_expr))
                self._walrus(item.context_expr, scope)
            self._body(node.body, scope)
            return
        if isinstance(node, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
            self._flow_body(node.body, scope, node, 'try')
            for i, h in enumerate(node.handlers):
                self._flow.append((id(node), 'except%d' % i))
                try:
                    if h.name:
                        self._add(scope, Definition(
                            h.name, lineno=h.lineno,
                            thunk=(lambda t=h.type, s=scope:
                                   self._exc_vals(t, s)),
                            col=self.ident_col(h.lineno, h.name, h.col_offset),
                            node=h, owner=self, qual=scope.qualname,
                            gkind='statement',
                            gdesc=self.node_src(h.type) or 'except'))
                    self._body(h.body, scope)
                finally:
                    self._flow.pop()
            self._flow_body(node.orelse, scope, node, 'else')
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
                d = Definition(
                    bound, 'module', 'module %s' % bound, node.lineno,
                    val=val, col=self._alias_col(node, alias, bound),
                    node=node, owner=self, qual=scope.qualname,
                    gkind='module', gdesc=self.node_src(node))
                d.import_ref = (self, dotted, 0, None)
                self._add(scope, d)
            return
        if isinstance(node, ast.ImportFrom):
            self._import_from(node, scope)
            return
        if hasattr(ast, 'Match') and isinstance(node, ast.Match):
            self._walrus(node.subject, scope)
            for i, case in enumerate(node.cases):
                self._flow.append((id(node), 'case%d' % i))
                try:
                    for nm in self._pattern_names(case.pattern):
                        self._add(scope, Definition(
                            nm, lineno=node.lineno, node=node, owner=self,
                            qual=scope.qualname, gkind='statement',
                            col=self.ident_col(node.lineno, nm),
                            gdesc=self.node_src(node.subject)))
                    self._body(case.body, scope)
                finally:
                    self._flow.pop()
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return
        # anything else: just look for walrus assignments
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._stmt(child, scope)
            else:
                self._walrus(child, scope)

    def _alias_col(self, node, alias, bound):
        lineno = getattr(alias, 'lineno', None) or node.lineno
        col = getattr(alias, 'col_offset', 0) or 0
        return self.ident_col(lineno, bound, col)

    def _exc_vals(self, type_node, scope):
        out = []
        for v in self._infer_multi(type_node, scope):
            inst = instance_of(v)
            if inst is not None:
                out.append(inst)
        return out

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
                    self._add(scope, Definition(
                        cur.target.id, lineno=cur.lineno,
                        thunk=(lambda v=cur.value, s=scope:
                               self._infer_multi(v, s)),
                        col=cur.target.col_offset, node=cur, owner=self,
                        qual=scope.qualname, gkind='statement',
                        gdesc=self.node_src(cur.value)))
            if isinstance(cur, (ast.Lambda, ast.FunctionDef,
                                ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for ch in ast.iter_child_nodes(cur):
                if not isinstance(ch, ast.stmt):
                    stack.append(ch)

    def _import_from(self, node, scope):
        modname = node.module or ''
        level = getattr(node, 'level', 0) or 0
        star = False
        for alias in node.names:
            if alias.name == '*':
                star = True
        if star:
            target = resolve_module(self.dirpath, modname, level)
            for name, val in module_export_names(target):
                d = Definition(
                    name, lineno=node.lineno, val=val, node=node, owner=self,
                    qual=scope.qualname, col=node.col_offset, gkind='module',
                    gdesc=self.node_src(node))
                d.import_ref = (self, modname, level, name)
                self._add(scope, d)
            return
        for alias in node.names:
            bound = alias.asname or alias.name
            d = Definition(
                bound, lineno=node.lineno,
                thunk=(lambda a=alias.name, m=modname, lv=level:
                       [self._from_import_val(a, m, lv)]),
                col=self._alias_col(node, alias, bound), node=node, owner=self,
                qual=scope.qualname, gkind='module',
                gdesc=self.node_src(node))
            d.import_ref = (self, modname, level, alias.name)
            self._add(scope, d)

    def _from_import_val(self, attr, modname, level):
        target = resolve_module(self.dirpath, modname, level)
        if target is not None:
            v = attr_of_module(target, attr)
            if v is not None and v.kind != 'unknown':
                return v
        # maybe it is a submodule: from pkg import sub
        sub = module_submodule(target, attr) if target is not None else None
        if sub is None:
            dotted = (modname + '.' + attr) if modname else attr
            sub = resolve_module(self.dirpath, dotted, level)
        if sub is not None:
            return Val('module', attr, obj=sub, owner=self)
        return UNKNOWN

    def _function(self, node, parent):
        qual = join_qual(parent.qualname, node.name)
        s = Scope('function', node, parent, node.lineno, end_line_of(node),
                  qual)
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
        defaults = param_defaults(a)
        for p in params:
            d = Definition(
                p.arg, 'param', 'param %s' % p.arg,
                getattr(p, 'lineno', node.lineno),
                thunk=(lambda p=p, sc=parent, dflt=defaults.get(id(p)),
                       fn=node: self._param_vals(p, dflt, sc, fn)),
                col=getattr(p, 'col_offset', 0), node=p, owner=self,
                qual=qual, gkind='param', gdesc='param %s' % p.arg)
            self._add(s, d)
        self._body(node.body, s)
        return s

    def _param_vals(self, p, default, scope, fnode=None):
        vals = self._annotation_vals(getattr(p, 'annotation', None), scope)
        if vals:
            return vals
        if fnode is not None:
            vals = self._stub_param_vals(fnode, p.arg)
            if vals:
                return vals
        if fnode is not None and DYNAMIC_PARAMS[0]:
            vals = self._dynamic_param_vals(fnode, p.arg)
            if vals:
                if default is not None:
                    vals = vals + self._infer_multi(default, scope)
                return dedup_vals(vals)
        if default is not None:
            return self._infer_multi(default, scope)
        return []

    def _stub_param_vals(self, fnode, pname):
        """Type of parameter *pname* as declared by the module stub."""
        pair = self.stub_map.get(id(fnode))
        if not pair:
            return []
        snode, sowner = pair
        sp = find_arg(snode, pname)
        if sp is None or getattr(sp, 'annotation', None) is None:
            return []
        sscope = sowner.func_scopes.get(snode)
        sscope = (sscope.parent if sscope is not None
                  else None) or sowner.module_scope
        return sowner._annotation_vals(sp.annotation, sscope)

    # -- dynamic parameter inference ---------------------------------------

    def _dynamic_param_vals(self, fnode, pname):
        """Infer a parameter type from call sites inside this file."""
        key = id(fnode)
        if key in self._dyn_busy:
            return []
        self._dyn_busy.add(key)
        try:
            return dedup_vals(self._collect_call_arg_vals(fnode, pname))
        except Exception:
            return []
        finally:
            self._dyn_busy.discard(key)

    def _collect_call_arg_vals(self, fnode, pname):
        a = fnode.args
        positional = list(getattr(a, 'posonlyargs', []) or []) + \
            list(a.args or [])
        if self.is_method(fnode) and positional:
            positional = positional[1:]
        index = None
        for i, p in enumerate(positional):
            if p.arg == pname:
                index = i
                break
        known = set(p.arg for p in positional)
        known.update(p.arg for p in (a.kwonlyargs or []))
        if index is None and pname not in known:
            return []
        out = []
        for call in self._calls_to(fnode):
            scope = self.scope_containing(getattr(call, 'lineno', 1))
            if index is not None:
                for i, arg in enumerate(call.args):
                    if isinstance(arg, ast.Starred):
                        break
                    if i == index:
                        out.extend(self._infer_multi(arg, scope))
                        break
            for kw in call.keywords or []:
                if kw.arg == pname:
                    out.extend(self._infer_multi(kw.value, scope))
        return out

    def _calls_to(self, fnode):
        """Calls in this file that invoke *fnode* (best effort)."""
        name = getattr(fnode, 'name', None)
        if not name:
            return []
        method = self.is_method(fnode)
        owner_class = None
        if method:
            scope = self.func_scopes.get(fnode)
            if scope is not None and scope.parent is not None:
                owner_class = scope.parent.node
        targets = []
        if name == '__init__' and owner_class is not None:
            targets.append(getattr(owner_class, 'name', None))
        out = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr != name:
                    continue
            elif isinstance(func, ast.Name):
                if func.id != name and func.id not in targets:
                    continue
            else:
                continue
            scope = self.scope_containing(getattr(node, 'lineno', 1))
            try:
                vals = self._infer_multi(func, scope)
            except Exception:
                vals = []
            ok = False
            for v in vals:
                if v.node is fnode:
                    ok = True
                    break
                if owner_class is not None and v.node is owner_class \
                        and name == '__init__':
                    ok = True
                    break
            if ok:
                out.append(node)
        return out

    def _class(self, node, parent):
        qual = join_qual(parent.qualname, node.name)
        s = Scope('class', node, parent, node.lineno, end_line_of(node), qual)
        parent.children.append(s)
        self.class_scopes[node] = s
        self._body(node.body, s)
        # give `self` / `cls` a useful type inside methods
        for st in node.body:
            if not isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decos = decorator_names(st)
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
            lst[0].set_vals([Val(kind, node.name, node=node, owner=self)])
        return s

    def _bind_target(self, target, value, scope, lineno, annotation=None,
                     stmt=None, gdesc=None, index=None, iter_node=None):
        if isinstance(target, ast.Name):
            if iter_node is not None:
                thunk = (lambda it=iter_node, s=scope:
                         self._iter_element_vals(it, s))
            else:
                thunk = (lambda v=value, a=annotation, s=scope, i=index:
                         self._binding_vals(v, a, s, i))
            if gdesc is None:
                gdesc = (self.node_src(value) if value is not None
                         else self.node_src(stmt))
            self._add(scope, Definition(
                target.id, lineno=getattr(target, 'lineno', lineno),
                thunk=thunk, col=getattr(target, 'col_offset', 0),
                node=stmt if stmt is not None else target, owner=self,
                qual=scope.qualname, gkind='statement', gdesc=gdesc))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for i, elt in enumerate(target.elts):
                self._bind_target(elt, value, scope, lineno, stmt=stmt,
                                  gdesc=gdesc, index=i)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, value, scope, lineno, stmt=stmt,
                              gdesc=gdesc)

    def _binding_vals(self, value, annotation, scope, index=None):
        if annotation is not None:
            av = self._annotation_vals(annotation, scope)
            if av:
                return av
        if value is None:
            return []
        if index is not None:
            if isinstance(value, (ast.Tuple, ast.List)) and index < len(value.elts):
                return self._infer_multi(value.elts[index], scope)
            return []
        return self._infer_multi(value, scope)

    def _iter_element_vals(self, iternode, scope):
        if iternode is None:
            return []
        if isinstance(iternode, (ast.List, ast.Set, ast.Tuple)):
            out = []
            for e in iternode.elts:
                out.extend(self._infer_multi(e, scope))
            return out
        if (isinstance(iternode, ast.Call)
                and isinstance(iternode.func, ast.Name)
                and iternode.func.id == 'range'):
            return [Val('instance', 'int', pytype=int)]
        for v in self._infer_multi(iternode, scope):
            if v.kind == 'instance' and v.pytype is str:
                return [Val('instance', 'str', pytype=str)]
        return []

    # -- name lookup -------------------------------------------------------

    def _scope_defs(self, scope, name, line=None, cur_flow=()):
        lst = scope.defs.get(name)
        if not lst:
            return None
        cands = lst
        if line is not None:
            cands = [d for d in lst if d.lineno <= line]
            if not cands:
                return None
        return reachable_defs(cands, cur_flow) or None

    def lookup_defs(self, scope, name, line=None, cur_flow=()):
        s = scope
        while s is not None:
            use_line = line if s is scope else None
            ds = self._scope_defs(s, name, use_line, cur_flow)
            if ds is None and use_line is not None:
                ds = self._scope_defs(s, name, None, cur_flow)
            if ds:
                return ds
            s = s.parent
        b = builtin_def(name)
        return [b] if b is not None else []

    # -- inference ---------------------------------------------------------

    def _annotation_vals(self, node, scope):
        """Values described by an annotation (an instance of the type)."""
        if node is None:
            return []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode='eval').body
            except Exception:
                return []
        if isinstance(node, ast.Subscript):
            base = node.value
            name = dotted_name(base)
            short = name.split('.')[-1] if name else ''
            if short in ('Optional', 'Union'):
                out = []
                sl = node.slice
                elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
                for e in elts:
                    out.extend(self._annotation_vals(e, scope))
                if short == 'Optional':
                    out.append(none_val())
                return dedup_vals(out)
            node = base
        name = dotted_name(node) if isinstance(node, (ast.Name,
                                                      ast.Attribute)) else None
        if name:
            alias = TYPING_ALIASES.get(name.split('.')[-1])
            if alias is not None:
                return [Val('instance', alias.__name__, pytype=alias)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return dedup_vals(self._annotation_vals(node.left, scope)
                              + self._annotation_vals(node.right, scope))
        if isinstance(node, ast.Constant) and node.value is None:
            return [none_val()]
        out = []
        for v in self._infer_multi(node, scope):
            if v.kind == 'class':
                out.append(instance_of(v))
            elif v.kind == 'module':
                out.append(v)
        return dedup_vals(out)

    def _infer(self, node, scope, line=None):
        vals = self._infer_multi(node, scope, line)
        return vals[0] if vals else UNKNOWN

    def _infer_multi(self, node, scope, line=None, narrow=None):
        try:
            return dedup_vals(self._infer_nodes(node, scope, line, narrow))
        except Exception:
            return []

    def _infer_nodes(self, node, scope, line=None, narrow=None):
        if node is None:
            return []
        if isinstance(node, ast.Constant):
            v = node.value
            if v is None:
                return [none_val()]
            if v is Ellipsis:
                return [Val('instance', 'ellipsis', pytype=type(Ellipsis))]
            return [Val('instance', type(v).__name__, pytype=type(v))]
        if isinstance(node, ast.JoinedStr):
            return [Val('instance', 'str', pytype=str)]
        if isinstance(node, (ast.List, ast.ListComp)):
            return [Val('instance', 'list', pytype=list)]
        if isinstance(node, ast.Tuple):
            return [Val('instance', 'tuple', pytype=tuple)]
        if isinstance(node, (ast.Set, ast.SetComp)):
            return [Val('instance', 'set', pytype=set)]
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return [Val('instance', 'dict', pytype=dict)]
        if isinstance(node, ast.GeneratorExp):
            return [Val('instance', 'generator', pytype=types.GeneratorType)]
        if isinstance(node, ast.Lambda):
            return [Val('function', '<lambda>', node=node, owner=self)]
        if isinstance(node, ast.NamedExpr):
            return self._infer_nodes(node.value, scope, line, narrow)
        if isinstance(node, ast.IfExp):
            return (self._infer_nodes(node.body, scope, line, narrow)
                    + self._infer_nodes(node.orelse, scope, line, narrow))
        if isinstance(node, ast.BoolOp):
            out = []
            for v in node.values:
                out.extend(self._infer_nodes(v, scope, line, narrow))
            return out
        if isinstance(node, ast.Name):
            if narrow and node.id in narrow:
                return list(narrow[node.id])
            out = []
            for d in self.lookup_defs(scope, node.id, line,
                                      cur_flow=flow_of(narrow)):
                out.extend(d.vals)
            return out
        if isinstance(node, ast.Attribute):
            out = []
            for base in self._infer_nodes(node.value, scope, line, narrow):
                out.extend(attr_vals(base, node.attr))
            return out
        if isinstance(node, ast.Call):
            argvals = self._call_args(node, scope, line, narrow)
            out = []
            for fv in self._infer_nodes(node.func, scope, line, narrow):
                out.extend(call_vals(fv, argvals))
            return out
        if isinstance(node, ast.Await):
            return []
        if isinstance(node, ast.Compare):
            return [Val('instance', 'bool', pytype=bool)]
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return [Val('instance', 'bool', pytype=bool)]
            return self._infer_nodes(node.operand, scope, line, narrow)
        if isinstance(node, ast.BinOp):
            return self._binop_vals(node, scope, line, narrow)
        if isinstance(node, ast.Subscript):
            return []
        if isinstance(node, ast.Starred):
            return []
        return []

    def _call_args(self, node, scope, line, narrow):
        pos = []
        kw = {}
        try:
            for a in node.args:
                if isinstance(a, ast.Starred):
                    pos.append([])
                else:
                    pos.append(self._infer_multi(a, scope, line, narrow))
            for k in node.keywords or []:
                if k.arg:
                    kw[k.arg] = self._infer_multi(k.value, scope, line, narrow)
        except Exception:
            pass
        return (pos, kw)

    def is_method(self, fnode):
        scope = self.func_scopes.get(fnode)
        if scope is None or scope.parent is None:
            return False
        if scope.parent.kind != 'class':
            return False
        return 'staticmethod' not in decorator_names(fnode)

    def _binop_vals(self, node, scope, line, narrow):
        left = self._infer_nodes(node.left, scope, line, narrow)
        right = self._infer_nodes(node.right, scope, line, narrow)
        lt = [v.pytype for v in left if v.kind == 'instance' and v.pytype]
        rt = [v.pytype for v in right if v.kind == 'instance' and v.pytype]
        if not lt or not rt:
            return []
        out = []
        for a in lt:
            for b in rt:
                t = binop_type(a, b, node.op)
                if t is not None:
                    out.append(Val('instance', t.__name__, pytype=t))
        return out

    # -- return types ------------------------------------------------------

    def function_return_vals(self, fnode, argvals=None):
        key = id(fnode)
        if key in self._ret_busy:
            return []
        self._ret_busy.add(key)
        try:
            scope = self.func_scopes.get(fnode)
            if scope is None:
                return []
            pair = self.stub_map.get(id(fnode))
            if pair:
                snode, sowner = pair
                sann = getattr(snode, 'returns', None)
                if sann is not None:
                    sscope = sowner.func_scopes.get(snode)
                    sscope = (sscope.parent if sscope is not None
                              else None) or sowner.module_scope
                    svals = sowner._annotation_vals(sann, sscope)
                    if svals:
                        return svals
            ret_ann = getattr(fnode, 'returns', None)
            if ret_ann is not None:
                vals = self._annotation_vals(ret_ann, scope.parent or
                                             self.module_scope)
                if vals:
                    return vals
            returns, yields = collect_returns(fnode)
            if yields:
                return [Val('instance', 'generator',
                            pytype=types.GeneratorType)]
            if not returns:
                return [none_val()]
            env = self._param_env(fnode, argvals)
            out = []
            for r in returns:
                if r.value is None:
                    out.append(none_val())
                else:
                    out.extend(self._infer_multi(r.value, scope, None, env))
            return dedup_vals(out)
        except Exception:
            return []
        finally:
            self._ret_busy.discard(key)

    def _param_env(self, fnode, argvals):
        """Bind call arguments to parameter names for return inference."""
        if not argvals:
            return None
        env = {}
        try:
            pos, kw = argvals
            a = fnode.args
            params = list(getattr(a, 'posonlyargs', []) or []) + \
                list(a.args or [])
            if self.is_method(fnode) and params:
                params = params[1:]
            for p, vs in zip(params, pos):
                if vs:
                    env[p.arg] = list(vs)
            names = set(p.arg for p in params) | \
                set(p.arg for p in (a.kwonlyargs or []))
            for name, vs in (kw or {}).items():
                if vs and name in names:
                    env[name] = list(vs)
        except Exception:
            return None
        return env or None

    # -- dataclasses -------------------------------------------------------

    def is_dataclass(self, node):
        key = id(node)
        if key in self._dataclass_cache:
            return self._dataclass_cache[key]
        self._dataclass_cache[key] = False
        found = False
        try:
            for deco in getattr(node, 'decorator_list', []) or []:
                target = deco.func if isinstance(deco, ast.Call) else deco
                dotted = dotted_name(target)
                if not dotted:
                    continue
                if dotted.split('.')[-1] == 'dataclass':
                    found = True
                    break
                root = dotted.split('.')[0]
                d = self.module_scope.lookup_local(root)
                if d is not None and isinstance(d.node, ast.ImportFrom):
                    for alias in d.node.names:
                        if (alias.asname or alias.name) == root and \
                                alias.name == 'dataclass':
                            found = True
                            break
                if found:
                    break
        except Exception:
            found = False
        self._dataclass_cache[key] = found
        return found

    def comprehension_def(self, scope, name, line):
        """Binding of a comprehension target *name* around *line*."""
        node = getattr(scope, 'node', None)
        if node is None:
            return None
        comps = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        try:
            for n in ast.walk(node):
                if not isinstance(n, comps):
                    continue
                if not (n.lineno <= line <= end_line_of(n)):
                    continue
                for gen in n.generators:
                    for t in ast.walk(gen.target):
                        if not isinstance(t, ast.Name) or t.id != name:
                            continue
                        return Definition(
                            name, lineno=t.lineno, col=t.col_offset,
                            node=n, owner=self, qual=scope.qualname,
                            gkind='statement',
                            gdesc=self.node_src(gen.iter),
                            thunk=(lambda it=gen.iter, s=scope:
                                   self._iter_element_vals(it, s)))
        except Exception:
            return None
        return None

    # -- flow --------------------------------------------------------------

    def flow_context(self, line):
        """Return (flowpath, [(test_node, positive), ...]) at *line*."""
        path = []
        tests = []
        try:
            self._walk_flow(getattr(self.tree, 'body', []), line, path, tests)
        except Exception:
            pass
        return tuple(path), tests

    def _in_block(self, stmts, line):
        if not stmts:
            return False
        try:
            first = min(s.lineno for s in stmts)
            last = max(end_line_of(s) for s in stmts)
        except Exception:
            return False
        if first <= line <= last:
            return True
        if line <= last:
            return False
        indent = min(getattr(s, 'col_offset', 0) for s in stmts)
        for idx in range(last, min(line - 1, len(self.lines))):
            t = self.lines[idx]
            s = t.strip()
            if not s or s.startswith('#'):
                continue
            if len(t) - len(t.lstrip()) < indent:
                return False
        if 0 <= line - 1 < len(self.lines):
            t = self.lines[line - 1]
            if t.strip() and len(t) - len(t.lstrip()) < indent:
                return False
        return True

    def _walk_flow(self, stmts, line, path, tests):
        for st in stmts or []:
            if isinstance(st, ast.Assert) and end_line_of(st) < line:
                tests.append((st.test, True))
            if not self._spans(st, line):
                continue
            if isinstance(st, (ast.If, ast.While)):
                if self._in_block(st.body, line):
                    path.append((id(st), 'body'))
                    tests.append((st.test, True))
                    self._walk_flow(st.body, line, path, tests)
                elif self._in_block(st.orelse, line):
                    path.append((id(st), 'else'))
                    tests.append((st.test, False))
                    self._walk_flow(st.orelse, line, path, tests)
                continue
            if isinstance(st, (ast.For, ast.AsyncFor)):
                if self._in_block(st.body, line):
                    path.append((id(st), 'body'))
                    self._walk_flow(st.body, line, path, tests)
                elif self._in_block(st.orelse, line):
                    path.append((id(st), 'else'))
                    self._walk_flow(st.orelse, line, path, tests)
                continue
            if isinstance(st, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
                if self._in_block(st.body, line):
                    path.append((id(st), 'try'))
                    self._walk_flow(st.body, line, path, tests)
                    continue
                done = False
                for i, h in enumerate(st.handlers):
                    if self._in_block(h.body, line):
                        path.append((id(st), 'except%d' % i))
                        self._walk_flow(h.body, line, path, tests)
                        done = True
                        break
                if done:
                    continue
                if self._in_block(st.orelse, line):
                    path.append((id(st), 'else'))
                    self._walk_flow(st.orelse, line, path, tests)
                elif self._in_block(st.finalbody, line):
                    self._walk_flow(st.finalbody, line, path, tests)
                continue
            for field in ('body', 'orelse', 'finalbody'):
                sub = getattr(st, field, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    if self._in_block(sub, line):
                        self._walk_flow(sub, line, path, tests)
            for h in getattr(st, 'handlers', []) or []:
                if self._in_block(h.body, line):
                    self._walk_flow(h.body, line, path, tests)
            for case in getattr(st, 'cases', []) or []:
                if self._in_block(case.body, line):
                    self._walk_flow(case.body, line, path, tests)

    def _spans(self, st, line):
        try:
            if st.lineno <= line <= end_line_of(st):
                return True
        except Exception:
            return False
        for field in ('body', 'orelse', 'finalbody'):
            sub = getattr(st, field, None)
            if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                if self._in_block(sub, line):
                    return True
        for h in getattr(st, 'handlers', []) or []:
            if self._in_block(h.body, line):
                return True
        return False

    # -- narrowing ---------------------------------------------------------

    def narrow_at(self, scope, line):
        """Type narrowing in effect at *line*: {name: [Val, ...]}."""
        flowpath, tests = self.flow_context(line)
        narrow = {}
        narrow['*flow*'] = flowpath
        for test, positive in tests:
            try:
                self._apply_test(test, positive, scope, line, narrow)
            except Exception:
                pass
        return narrow

    def _apply_test(self, test, positive, scope, line, narrow):
        if test is None:
            return
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            self._apply_test(test.operand, not positive, scope, line, narrow)
            return
        if isinstance(test, ast.BoolOp):
            conj = isinstance(test.op, ast.And)
            if (conj and positive) or (not conj and not positive):
                for v in test.values:
                    self._apply_test(v, positive, scope, line, narrow)
            return
        if isinstance(test, ast.Call):
            fname = dotted_name(test.func)
            if fname and fname.split('.')[-1] == 'isinstance' \
                    and len(test.args) == 2 \
                    and isinstance(test.args[0], ast.Name):
                name = test.args[0].id
                classes = []
                arg = test.args[1]
                elts = arg.elts if isinstance(arg, (ast.Tuple, ast.List)) else [arg]
                for e in elts:
                    for v in self._infer_multi(e, scope, line):
                        inst = instance_of(v)
                        if inst is not None:
                            classes.append(inst)
                classes = dedup_vals(classes)
                if not classes:
                    return
                if positive:
                    narrow[name] = classes
                else:
                    cur = self._current_vals(name, scope, line, narrow)
                    keys = set(val_key(c) for c in classes)
                    rest = [v for v in cur if val_key(v) not in keys]
                    if rest:
                        narrow[name] = rest
            return
        if isinstance(test, ast.Compare) and len(test.ops) == 1 \
                and isinstance(test.left, ast.Name) \
                and isinstance(test.comparators[0], ast.Constant) \
                and test.comparators[0].value is None:
            name = test.left.id
            op = test.ops[0]
            if isinstance(op, ast.Is):
                is_none = positive
            elif isinstance(op, ast.IsNot):
                is_none = not positive
            else:
                return
            if is_none:
                narrow[name] = [none_val()]
            else:
                cur = self._current_vals(name, scope, line, narrow)
                rest = [v for v in cur if v.pytype is not type(None)]
                if rest:
                    narrow[name] = rest
            return

    def _current_vals(self, name, scope, line, narrow):
        if name in narrow:
            return list(narrow[name])
        out = []
        for d in self.lookup_defs(scope, name, line, flow_of(narrow)):
            out.extend(d.vals)
        return dedup_vals(out)


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


def attr_vals(val, attr):
    """Resolve `val.attr` to a list of Vals."""
    if val is None or val.kind == 'unknown':
        return []
    if val.kind == 'module':
        target = materialize(val)
        if isinstance(target, Analysis):
            d = target.module_scope.lookup_local(attr)
            if d is not None:
                return list(d.vals)
            sub = module_submodule(target, attr)
            if sub is not None:
                return [Val('module', attr, obj=sub)]
            return []
        v = attr_of_module(target, attr)
        return [v] if v is not None and v.kind != 'unknown' else []
    if val.kind in ('class', 'instance') and val.node is not None \
            and val.owner is not None:
        members = class_member_defs(val.node, val.owner,
                                    include_instance=(val.kind == 'instance'))
        defs = members.get(attr)
        if not defs:
            return []
        vals = []
        for d in defs:
            vals.extend(d.vals)
        out = []
        for v in dedup_vals(vals):
            if val.kind == 'instance' and v.kind == 'function' \
                    and v.node is not None and v.owner is not None \
                    and 'property' in decorator_names(v.node):
                out.extend(v.owner.function_return_vals(v.node))
            else:
                out.append(v)
        return dedup_vals(out)
    real = None
    if val.kind == 'class':
        real = val.obj
    elif val.kind == 'instance':
        real = val.pytype if val.pytype is not None else (
            type(val.obj) if val.obj is not None else None)
    elif val.kind == 'function':
        real = val.obj if val.obj is not None else types.FunctionType
    if real is not None:
        try:
            obj = getattr(real, attr)
        except Exception:
            return []
        v = val_from_obj(obj, attr)
        return [v] if v.kind != 'unknown' else []
    return []


def attr_defs(val, attr):
    """Definitions of the member `attr` of *val* (for goto)."""
    if val is None or val.kind == 'unknown':
        return []
    if val.kind == 'module':
        target = materialize(val)
        if isinstance(target, Analysis):
            d = target.module_scope.lookup_local(attr)
            if d is not None:
                return [d]
            sub = module_submodule(target, attr)
            if sub is not None:
                return [Definition(attr, 'module', 'module %s' % attr, 0,
                                   val=Val('module', attr, obj=sub))]
            return []
        if target is not None:
            try:
                obj = getattr(target, attr)
            except Exception:
                return []
            return [real_def(obj, attr)]
        return []
    if val.kind in ('class', 'instance') and val.node is not None \
            and val.owner is not None:
        members = class_member_defs(val.node, val.owner,
                                    include_instance=(val.kind == 'instance'))
        return list(members.get(attr) or [])
    real = None
    if val.kind == 'class':
        real = val.obj
    elif val.kind == 'instance':
        real = val.pytype if val.pytype is not None else (
            type(val.obj) if val.obj is not None else None)
    if real is not None:
        try:
            obj = getattr(real, attr)
        except Exception:
            return []
        return [real_def(obj, attr)]
    return []


def call_vals(fv, argvals=None):
    """Values produced by calling *fv*."""
    if fv is None or fv.kind == 'unknown':
        return []
    if fv.kind == 'class':
        inst = instance_of(fv)
        return [inst] if inst is not None else []
    if fv.kind == 'function':
        if fv.node is not None and isinstance(
                fv.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = fv.owner
            if owner is not None:
                return owner.function_return_vals(fv.node, argvals)
            return []
        if isinstance(fv.node, ast.Lambda) and fv.owner is not None:
            scope = fv.owner.func_scopes.get(fv.node, fv.owner.module_scope)
            return fv.owner._infer_multi(fv.node.body, scope)
        if fv.obj is not None:
            try:
                ann = getattr(fv.obj, '__annotations__', {}) or {}
                rt = ann.get('return')
                if inspect.isclass(rt):
                    return [Val('instance', rt.__name__, pytype=rt)]
            except Exception:
                pass
        return []
    if fv.kind == 'instance':
        for v in attr_vals(fv, '__call__'):
            if v.kind == 'function' and v.node is not None:
                return v.owner.function_return_vals(v.node)
    return []


def real_def(obj, name):
    """A Definition wrapping a real (imported) python object."""
    v = val_from_obj(obj, name)
    kind, desc = describe_val(v, name)
    return Definition(name, kind, desc, 0, val=v)


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


def class_member_defs(node, owner, include_instance=False, _seen=None):
    """Return {name: [Definition, ...]} for a file-defined class."""
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
            keep = reachable_defs(lst)
            if keep:
                members[name] = keep

    for base_node, base_owner in _class_bases(node, owner):
        inherited = class_member_defs(base_node, base_owner,
                                      include_instance=include_instance,
                                      _seen=_seen)
        for name, lst in inherited.items():
            members.setdefault(name, lst)

    if include_instance:
        for name, lst in instance_attr_defs(node, owner, set()).items():
            cur = members.get(name)
            if cur is None:
                members[name] = lst
            elif lst and all(getattr(d, 'is_stub', False) for d in cur):
                # the stub declares the attribute, the source assigns it:
                # keep the source location but use the declared type
                members[name] = [merged_stub_def(lst[-1], cur[-1])]
    return members


def class_members(node, owner, include_instance=False, _seen=None):
    """Return {name: Definition} for a file-defined class."""
    out = {}
    for name, lst in class_member_defs(node, owner, include_instance,
                                       _seen).items():
        if lst:
            out[name] = lst[-1]
    return out


def instance_attr_defs(node, owner, seen):
    """{name: [Definition, ...]} for `self.x = ...` assignments."""
    key = (id(owner), id(node))
    if key in seen:
        return {}
    seen.add(key)
    out = {}
    scope = owner.class_scopes.get(node)
    qual = scope.qualname if scope is not None else node.name
    methods = [st for st in node.body
               if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))
               and st.name == '__init__']
    for st in methods:
        if 'staticmethod' in decorator_names(st):
            continue
        args = list(getattr(st.args, 'posonlyargs', []) or []) + list(st.args.args or [])
        if not args:
            continue
        selfname = args[0].arg
        fscope = owner.func_scopes.get(st, owner.module_scope)
        _collect_self_attrs(st.body, selfname, fscope, owner, out, qual)
    for name, lst in list(out.items()):
        out[name] = reachable_defs(lst)
    if owner.is_dataclass(node) and scope is not None:
        # annotated dataclass fields are instance attributes
        for st in node.body:
            if not isinstance(st, ast.AnnAssign):
                continue
            if not isinstance(st.target, ast.Name):
                continue
            defs = scope.defs.get(st.target.id)
            if defs:
                out.setdefault(st.target.id, reachable_defs(defs))
    for base_node, base_owner in _class_bases(node, owner):
        for name, lst in instance_attr_defs(base_node, base_owner,
                                            seen).items():
            out.setdefault(name, lst)
    return out


def _collect_self_attrs(stmts, selfname, fscope, owner, out, qual, flow=()):
    for st in stmts or []:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(st, ast.Assign):
            for tgt in st.targets:
                _self_target(tgt, st.value, selfname, fscope, owner, out, st,
                             qual, flow=flow)
        elif isinstance(st, ast.AnnAssign):
            _self_target(st.target, st.value, selfname, fscope, owner, out, st,
                         qual, annotation=st.annotation, flow=flow)
        elif isinstance(st, ast.AugAssign):
            _self_target(st.target, None, selfname, fscope, owner, out, st,
                         qual, flow=flow)
        elif isinstance(st, (ast.For, ast.AsyncFor)):
            _self_target(st.target, None, selfname, fscope, owner, out, st,
                         qual, flow=flow)
        branchy = isinstance(st, (ast.If, ast.While, ast.For, ast.AsyncFor,
                                  ast.Try, getattr(ast, 'TryStar', ast.Try)))
        for field, branch in (('body', 'body'), ('orelse', 'else'),
                              ('finalbody', None)):
            sub = getattr(st, field, None)
            if isinstance(sub, list):
                sub_flow = flow
                if branchy and branch is not None:
                    sub_flow = flow + ((id(st), branch),)
                _collect_self_attrs(sub, selfname, fscope, owner, out, qual,
                                    sub_flow)
        for i, h in enumerate(getattr(st, 'handlers', []) or []):
            _collect_self_attrs(h.body, selfname, fscope, owner, out, qual,
                                flow + ((id(st), 'except%d' % i),))


def _self_target(tgt, value, selfname, fscope, owner, out, stmt, qual,
                 annotation=None, flow=()):
    if isinstance(tgt, (ast.Tuple, ast.List)):
        for elt in tgt.elts:
            _self_target(elt, None, selfname, fscope, owner, out, stmt, qual,
                         flow=flow)
        return
    if not isinstance(tgt, ast.Attribute):
        return
    if not (isinstance(tgt.value, ast.Name) and tgt.value.id == selfname):
        return
    lineno = getattr(tgt, 'lineno', stmt.lineno)
    end_line = getattr(tgt, 'end_lineno', lineno) or lineno
    end_col = getattr(tgt, 'end_col_offset', None)
    if end_col is not None:
        col = max(end_col - len(tgt.attr), 0)
    else:
        col = owner.ident_col(end_line, tgt.attr, tgt.col_offset)
    thunk = (lambda v=value, a=annotation, s=fscope:
             owner._binding_vals(v, a, s))
    gdesc = (owner.node_src(value) if value is not None
             else owner.node_src(stmt))
    d = Definition(
        tgt.attr, lineno=end_line, thunk=thunk, col=col, node=stmt,
        owner=owner, qual=qual, gkind='statement', gdesc=gdesc)
    d.flowpath = flow
    out.setdefault(tgt.attr, []).append(d)


def attributes_for_vals(vals):
    """Union of the attributes of every value in *vals*."""
    result = {}
    for v in vals or []:
        try:
            for name, entry in attributes_for(v).items():
                result.setdefault(name, entry)
        except Exception:
            continue
    return result


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
# import context
# --------------------------------------------------------------------------

_FROM_IMPORT_RE = re.compile(r'^\s*from\s+([.\w]*)\s+import\s+(.*)$', re.S)
_FROM_RE = re.compile(r'^\s*from\s+([.\w]*)$', re.S)
_IMPORT_RE = re.compile(r'^\s*import\s+(.*)$', re.S)
_SEGMENT_RE = re.compile(r'^[.\w]*$')


def looks_like_import(text):
    return bool(_FROM_IMPORT_RE.match(text) or _IMPORT_RE.match(text)
                or _FROM_RE.match(text))


def paren_depth(text):
    depth = 0
    for ch in text:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
    return depth


def logical_import_prefix(lines, line, col):
    """The (possibly continued) logical line up to the cursor, if an import."""
    text = lines[line - 1][:col] if 0 <= line - 1 < len(lines) else ''
    if looks_like_import(text):
        return text
    acc = text
    idx = line - 1
    while idx >= 1 and (line - idx) <= 40:
        prev = lines[idx - 1]
        stripped = prev.rstrip()
        cont = stripped.endswith('\\')
        if cont:
            acc = stripped[:-1] + acc       # explicit line joining
        else:
            acc = prev + ' ' + acc
        if (cont or paren_depth(acc) > 0) and looks_like_import(acc):
            return acc
        if not cont and paren_depth(acc) <= 0:
            return None
        idx -= 1
    return None


def split_dotted_spec(spec):
    """('...pkg.sub.pre') -> (level, 'pkg.sub', 'pre')."""
    level = 0
    i = 0
    while i < len(spec) and spec[i] == '.':
        level += 1
        i += 1
    rest = spec[i:]
    if '.' in rest:
        pkg, _, prefix = rest.rpartition('.')
    else:
        pkg, prefix = '', rest
    return level, pkg, prefix


def _last_import_segment(text):
    """The chunk of an import list the cursor is in, or None."""
    seg = text
    for sep in (',', '(', ')'):
        if sep in seg:
            seg = seg.rsplit(sep, 1)[1]
    seg = seg.strip()
    if not _SEGMENT_RE.match(seg):
        return None
    return seg


def import_context_at(lines, line, col):
    """Describe the import statement the cursor sits in, or None."""
    text = logical_import_prefix(lines, line, col)
    if text is None:
        return None
    m = _FROM_IMPORT_RE.match(text)
    if m:
        seg = _last_import_segment(m.group(2))
        if seg is None or '.' in seg:
            return {'kind': 'none'}
        spec = m.group(1)
        level, _pkg, _pre = split_dotted_spec(spec)
        return {'kind': 'from', 'level': level,
                'module': spec.lstrip('.'), 'prefix': seg}
    m = _IMPORT_RE.match(text)
    if m:
        seg = _last_import_segment(m.group(1))
        if seg is None:
            return {'kind': 'none'}
        level, pkg, prefix = split_dotted_spec(seg)
        if level:
            return {'kind': 'none'}
        return {'kind': 'module', 'level': 0, 'pkg': pkg, 'prefix': prefix}
    m = _FROM_RE.match(text)
    if m:
        level, pkg, prefix = split_dotted_spec(m.group(1))
        return {'kind': 'module', 'level': level, 'pkg': pkg,
                'prefix': prefix}
    return None


def import_completion_items(analysis, ctx):
    """{name: (type, description)} suggested inside an import statement."""
    kind = ctx.get('kind')
    base = getattr(analysis, 'dirpath', None) or project_root()
    if kind == 'module':
        level, pkg = ctx['level'], ctx['pkg']
        if not level and not pkg:
            return top_level_module_items()
        target = resolve_module(base, pkg, level)
        if target is None:
            return {}
        return submodule_items(target)
    if kind == 'from':
        target = resolve_module(base, ctx['module'], ctx['level'])
        if target is None:
            return {}
        return module_export_items(target)
    return {}


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
        ctx = import_context_at(self.lines, line, col)
        if ctx is not None:
            return self._import_completions(ctx, fuzzy)
        mode, prefix, recv = analyze_cursor(text, col)
        if mode == 'attr':
            return self._attr_completions(line, col, prefix, recv, fuzzy)
        return self._name_completions(line, col, prefix, fuzzy)

    def _import_completions(self, ctx, fuzzy):
        prefix = ctx.get('prefix', '')
        items = []
        for name, (kind, desc) in import_completion_items(self.a, ctx).items():
            if matches(name, prefix, fuzzy):
                items.append(make_item(name, kind, desc, prefix))
        return order(items)

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
        vals = self._resolve_receiver_vals(recv, line, col)
        attrs = attributes_for_vals(vals)
        items = []
        for name, (kind, desc) in attrs.items():
            if matches(name, prefix, fuzzy):
                items.append(make_item(name, kind, desc, prefix))
        return order(items)

    def _receiver_expr(self, recv):
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
        return expr

    def _resolve_receiver_vals(self, recv, line, col):
        expr = self._receiver_expr(recv)
        if expr is None:
            return []
        scope = self.scope_at(line, col)
        narrow = self.a.narrow_at(scope, line)
        return self.a._infer_multi(expr, scope, line, narrow)

    def _resolve_receiver(self, recv, line, col):
        vals = self._resolve_receiver_vals(recv, line, col)
        return vals[0] if vals else UNKNOWN


# --------------------------------------------------------------------------
# definition objects (infer / goto output)
# --------------------------------------------------------------------------

def def_entry(name, kind, full_name, module_path, line, column,
              description, docstring):
    return {
        'name': name or '',
        'type': kind or 'statement',
        'full_name': full_name or '',
        'module_path': module_path or '',
        'line': int(line or 0),
        'column': int(column or 0),
        'description': description or '',
        'docstring': docstring or '',
    }


def builtin_entry(name, kind='instance'):
    desc = 'instance of %s' % name
    if kind == 'class':
        desc = 'class %s' % name
    elif kind == 'function':
        desc = 'def %s(...)' % name
    elif kind == 'module':
        desc = 'module %s' % name
    return def_entry(name, kind, 'builtins.%s' % name, '', 0, 0, desc, '')


def node_qualname(node, owner):
    """Dotted name of a class/function node inside its module."""
    scope = None
    if isinstance(node, ast.ClassDef):
        scope = owner.class_scopes.get(node)
    else:
        scope = owner.func_scopes.get(node)
    if scope is not None and scope.qualname:
        return scope.qualname
    return getattr(node, 'name', '') or ''


def node_full_name(node, owner):
    mod = module_name_of(owner)
    qual = node_qualname(node, owner)
    return '.'.join([p for p in (mod, qual) if p])


def class_entry(node, owner, kind='class'):
    name = node.name
    desc = ('class %s' % name) if kind == 'class' else ('instance of %s' % name)
    return def_entry(name, kind, node_full_name(node, owner),
                     rel_module_path(owner.path), node.lineno,
                     owner.def_name_col(node), desc, safe_docstring(node))


def function_entry(node, owner):
    return def_entry(node.name, 'function', node_full_name(node, owner),
                     rel_module_path(owner.path), node.lineno,
                     owner.def_name_col(node), func_description(node),
                     safe_docstring(node))


def module_entry(target, fallback_name=''):
    if isinstance(target, Analysis):
        full = module_name_of(target) or fallback_name
        short = full.split('.')[-1] if full else fallback_name
        return def_entry(short, 'module', full, rel_module_path(target.path),
                         0, 0, 'module %s' % short, target.docstring)
    if target is not None:
        name = getattr(target, '__name__', fallback_name) or fallback_name
        short = name.split('.')[-1]
        path = getattr(target, '__file__', '') or ''
        doc = ''
        try:
            doc = inspect.getdoc(target) or ''
        except Exception:
            doc = ''
        return def_entry(short, 'module', name,
                         rel_module_path(path) if path else '', 0, 0,
                         'module %s' % short, doc)
    return None


def real_entry(obj, name, kind=None):
    """Definition entry for a real (imported) python object."""
    v = val_from_obj(obj, name)
    if kind is None:
        kind = describe_val(v, name)[0]
    modname = ''
    try:
        modname = getattr(obj, '__module__', '') or ''
    except Exception:
        modname = ''
    qualname = ''
    try:
        qualname = getattr(obj, '__qualname__', '') or ''
    except Exception:
        qualname = ''
    if not qualname:
        qualname = getattr(obj, '__name__', '') or name
    display = qualname.split('.')[-1] or name
    if modname in ('builtins', '') and kind != 'module':
        if kind == 'instance':
            return builtin_entry(display, 'instance')
        return def_entry(display, kind, 'builtins.%s' % display, '', 0, 0,
                         real_description(obj, display, kind), '')
    full = '.'.join([p for p in (modname, qualname) if p])
    path = ''
    line = 0
    col = 0
    try:
        f = inspect.getsourcefile(obj)
        if f:
            path = rel_module_path(f)
    except Exception:
        path = ''
    try:
        _src, lineno = inspect.getsourcelines(obj)
        line = lineno or 0
    except Exception:
        line = 0
    doc = ''
    try:
        doc = inspect.getdoc(obj) or ''
    except Exception:
        doc = ''
    return def_entry(display, kind, full, path, line, col,
                     real_description(obj, display, kind), doc)


def real_description(obj, name, kind):
    if kind == 'class':
        return 'class %s' % name
    if kind == 'module':
        return 'module %s' % name
    if kind == 'function':
        try:
            return 'def %s%s' % (name, inspect.signature(obj))
        except Exception:
            return 'def %s(...)' % name
    if kind == 'instance':
        try:
            return 'instance of %s' % type(obj).__name__
        except Exception:
            return 'instance of %s' % name
    return name


def val_entry(val):
    """Definition entry describing the value *val*."""
    if val is None or val.kind == 'unknown':
        return None
    if val.kind == 'module':
        target = materialize(val)
        entry = module_entry(target, val.name or val.modname or '')
        if entry is not None:
            return entry
        name = (val.name or val.modname or '').split('.')[-1]
        if not name:
            return None
        return def_entry(name, 'module', val.modname or name, '', 0, 0,
                         'module %s' % name, '')
    if val.kind == 'class':
        if val.node is not None and val.owner is not None:
            return class_entry(val.node, val.owner, 'class')
        if val.obj is not None:
            return real_entry(val.obj, val.name or '', 'class')
        return None
    if val.kind == 'function':
        if val.node is not None and val.owner is not None:
            if isinstance(val.node, ast.Lambda):
                return def_entry('<lambda>', 'function',
                                 join_qual(module_name_of(val.owner),
                                           '<lambda>'),
                                 rel_module_path(val.owner.path),
                                 val.node.lineno, val.node.col_offset,
                                 'def <lambda>(%s)' % unparse(val.node.args),
                                 '')
            return function_entry(val.node, val.owner)
        if val.obj is not None:
            return real_entry(val.obj, val.name or '', 'function')
        return None
    if val.kind == 'instance':
        if val.node is not None and val.owner is not None:
            return class_entry(val.node, val.owner, 'instance')
        pytype = val.pytype
        name = val.name or (pytype.__name__ if pytype is not None else '')
        if pytype is type(None) or name == 'NoneType':
            return builtin_entry('None', 'instance')
        if pytype is not None:
            mod = getattr(pytype, '__module__', '') or ''
            if mod == 'builtins':
                return builtin_entry(pytype.__name__, 'instance')
            return real_entry(pytype, name, 'instance')
        if name:
            return builtin_entry(name, 'instance')
        return None
    return None


def binding_entry(d):
    """Definition entry describing the binding *d* (goto)."""
    if d is None:
        return None
    if d.owner is None or d.node is None:
        # builtin / real object binding
        val = d.val
        entry = val_entry(val)
        if entry is not None:
            return entry
        return None
    kind = d.goto_kind
    if kind not in ('module', 'class', 'function', 'instance', 'statement',
                    'param'):
        kind = 'statement'
    return def_entry(d.name, kind, d.full_name, rel_module_path(d.owner.path),
                     d.lineno, d.col, d.goto_description, d.doc)


def follow_import_entries(d, seen=None, depth=0):
    """Entries an import binding ultimately points at.

    Returns None when *d* is not an import binding, [] when the chain cannot
    be resolved (the caller then falls back to the import statement itself).
    """
    ref = getattr(d, 'import_ref', None)
    if ref is None:
        return None
    if depth > 32:
        return []
    if seen is None:
        seen = set()
    owner, modname, level, attr = ref
    base = getattr(owner, 'dirpath', None) or project_root()
    target = resolve_module(base, modname, level)
    if attr is None:
        if isinstance(target, Analysis):
            entry = module_entry(target, d.name)
            return [entry] if entry is not None else []
        return []
    if isinstance(target, Analysis):
        lst = target.module_scope.defs.get(attr)
        if lst:
            out = []
            for sub in reachable_defs(lst):
                key = (id(sub.owner), sub.name, sub.lineno, sub.col)
                if key in seen:
                    continue
                seen.add(key)
                nested = follow_import_entries(sub, seen, depth + 1)
                if nested is None:
                    entry = binding_entry(sub)
                    if entry is not None:
                        out.append(entry)
                else:
                    out.extend(nested)
            if out:
                return out
    if target is None or isinstance(target, Analysis):
        sub_mod = (module_submodule(target, attr)
                   if target is not None else None)
        if sub_mod is None:
            dotted = (modname + '.' + attr) if modname else attr
            sub_mod = resolve_module(base, dotted, level)
        if isinstance(sub_mod, Analysis):
            entry = module_entry(sub_mod, attr)
            return [entry] if entry is not None else []
    return []


def goto_entries(defs, follow):
    """Entries for a goto query, optionally following import chains."""
    entries = []
    for d in defs:
        if follow:
            followed = follow_import_entries(d)
            if followed:
                entries.extend(followed)
                continue
        entries.append(binding_entry(d))
    return entries


def sort_entries(entries):
    out = []
    seen = set()
    for e in entries:
        if e is None:
            continue
        key = (e['name'], e['type'], e['full_name'], e['module_path'],
               e['line'], e['column'])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    out.sort(key=lambda e: (e['module_path'], e['line'], e['column'],
                            e['name']))
    return out


# --------------------------------------------------------------------------
# infer / goto
# --------------------------------------------------------------------------

_CONSTANT_NAMES = {'None': None, 'True': True, 'False': False}


def name_token_at(source, lines, line, col):
    """Return (name, start_col, end_col) for the name under the cursor."""
    found = None
    lexed = False
    try:
        readline = io.StringIO(source).readline
        for tok in tokenize.generate_tokens(readline):
            if tok.start[0] > line:
                break
            if tok.type != tokenize.NAME:
                continue
            if tok.start[0] == line and tok.start[1] <= col <= tok.end[1]:
                found = (tok.string, tok.start[1], tok.end[1])
                break
        lexed = True
    except Exception:
        lexed = found is not None
    if found is None and not lexed:
        text = lines[line - 1] if 0 <= line - 1 < len(lines) else ''
        start = col
        while start > 0 and is_ident_char(text[start - 1]):
            start -= 1
        end = col
        while end < len(text) and is_ident_char(text[end]):
            end += 1
        if start < end and not text[start].isdigit():
            found = (text[start:end], start, end)
    if found is None:
        return None
    name = found[0]
    if not name or not (name[0].isalpha() or name[0] == '_'):
        return None
    if name in _KEYWORD_SET and name not in _CONSTANT_NAMES:
        return None
    return found


def dot_before(text, start):
    """Index of the `.` immediately preceding position *start*, else -1."""
    j = start
    while j > 0 and text[j - 1] in ' \t':
        j -= 1
    if j > 0 and text[j - 1] == '.':
        if j >= 2 and text[j - 2] == '.':
            return -1
        return j - 1
    return -1


def import_module_ref(analysis, lines, line, name, start):
    """Module referenced by the cursor inside an import statement."""
    text = lines[line - 1] if 0 <= line - 1 < len(lines) else ''
    for node in ast.walk(analysis.tree):
        if isinstance(node, ast.ImportFrom):
            if node.lineno != line or not node.module:
                continue
            idx = text.find(node.module)
            if idx < 0:
                continue
            if not (idx <= start < idx + len(node.module)):
                continue
            dotted = node.module[:start - idx + len(name)]
            return resolve_module(analysis.dirpath, dotted,
                                  getattr(node, 'level', 0) or 0)
        if isinstance(node, ast.Import):
            if node.lineno != line:
                continue
            for alias in node.names:
                if '.' not in alias.name:
                    continue
                idx = text.find(alias.name)
                if idx < 0:
                    continue
                if not (idx <= start < idx + len(alias.name)):
                    continue
                if start == idx:
                    continue        # first component: normal binding
                dotted = alias.name[:start - idx + len(name)]
                return resolve_module(analysis.dirpath, dotted, 0)
    return None


class Query(object):
    """Resolves the name under a cursor to definitions."""

    def __init__(self, analysis, lines, follow=False):
        self.a = analysis
        self.lines = lines
        self.follow = follow
        self.completer = Completer(analysis, lines)

    def run(self, line, col, mode):
        self.mode = mode
        text = self.lines[line - 1] if 0 <= line - 1 < len(self.lines) else ''
        tok = name_token_at(self.a.source, self.lines, line, col)
        if tok is None:
            return None
        name, start, _end = tok

        if name in _CONSTANT_NAMES:
            value = _CONSTANT_NAMES[name]
            if value is None:
                return [builtin_entry('None', 'instance')]
            return [builtin_entry('bool', 'instance')]

        target = import_module_ref(self.a, self.lines, line, name, start)
        if target is not None:
            entry = module_entry(target, name)
            return [entry] if entry is not None else []

        dot = dot_before(text, start)
        if dot >= 0:
            return self._attribute(line, col, name, dot)

        scope = self.completer.scope_at(line, col)
        narrow = self.a.narrow_at(scope, line)
        if mode == 'infer' and name in narrow:
            return [val_entry(v) for v in narrow[name]]
        defs = self.a.lookup_defs(scope, name, line, flow_of(narrow))
        if not defs:
            comp = self.a.comprehension_def(scope, name, line)
            if comp is not None:
                defs = [comp]
        if mode == 'infer':
            vals = []
            for d in defs:
                vals.extend(d.vals)
            return [val_entry(v) for v in dedup_vals(vals)]
        return goto_entries(defs, self.follow)

    def _attribute(self, line, col, name, dot):
        text = self.lines[line - 1]
        recv = scan_receiver(text, dot)
        if not recv or not recv.strip():
            return []
        expr = self.completer._receiver_expr(recv)
        if expr is None:
            return []
        scope = self.completer.scope_at(line, col)
        narrow = self.a.narrow_at(scope, line)
        bases = self.a._infer_multi(expr, scope, line, narrow)
        entries = []
        if self.mode == 'infer':
            vals = []
            for base in bases:
                vals.extend(attr_vals(base, name))
            for v in dedup_vals(vals):
                entries.append(val_entry(v))
        else:
            for base in bases:
                entries.extend(goto_entries(attr_defs(base, name),
                                            self.follow))
        return entries


def run_query(analysis, lines, line, col, mode, follow=False):
    q = Query(analysis, lines, follow)
    q.mode = mode
    return q.run(line, col, mode)


# --------------------------------------------------------------------------
# call context (signature help)
# --------------------------------------------------------------------------

def offset_of(lines, line, col):
    """Absolute offset of (1-based *line*, 0-based *col*) in the source."""
    off = 0
    for i in range(min(line - 1, len(lines))):
        off += len(lines[i]) + 1
    return off + col


def _skip_string(text, i, limit):
    """Index just past the string literal starting at *i*."""
    quote = text[i]
    triple = text[i:i + 3]
    if triple in ('"""', "'''"):
        i += 3
        while i < limit:
            if text[i] == '\\':
                i += 2
                continue
            if text.startswith(triple, i):
                return i + 3
            i += 1
        return limit
    i += 1
    while i < limit:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == quote:
            return i + 1
        if c == '\n':
            return i
        i += 1
    return limit


def bracket_stack(text, limit):
    """Brackets still open at offset *limit*, as [(char, index), ...]."""
    stack = []
    i = 0
    while i < limit:
        ch = text[i]
        if ch == '#':
            nl = text.find('\n', i)
            i = limit if nl < 0 else nl
            continue
        if ch in '"\'':
            i = _skip_string(text, i, limit)
            continue
        if ch in '([{':
            stack.append((ch, i))
        elif ch in ')]}':
            if stack:
                stack.pop()
        i += 1
    return stack


_DECL_KEYWORDS = ('def', 'class', 'lambda')


def call_at(source, lines, line, col):
    """(callable text, index of its `(`) for the call the cursor sits in."""
    limit = min(offset_of(lines, line, col), len(source))
    for ch, pos in reversed(bracket_stack(source, limit)):
        if ch != '(':
            continue
        recv = scan_receiver(source, pos)
        if not recv.strip():
            continue
        stop = pos
        while stop > 0 and source[stop - 1] in ' \t':
            stop -= 1
        start = stop - len(recv)
        j = start
        while j > 0 and source[j - 1] in ' \t':
            j -= 1
        k = j
        while k > 0 and is_ident_char(source[k - 1]):
            k -= 1
        if source[k:j] in _DECL_KEYWORDS:
            continue            # `def f(` / `class C(` declare, they don't call
        return recv.strip(), pos
    return None


def split_call_args(text):
    """Split a call's argument source on its top-level commas."""
    segments = []
    depth = 0
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '#':
            nl = text.find('\n', i)
            i = n if nl < 0 else nl
            continue
        if ch in '"\'':
            i = _skip_string(text, i, n)
            continue
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ',' and depth == 0:
            segments.append(text[start:i])
            start = i + 1
        i += 1
    segments.append(text[start:])
    return segments


_KWARG_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*=(?!=)')


def call_cursor_slot(argtext):
    """(positional index, keyword name, ambiguous) for the argument typed."""
    segments = split_call_args(argtext)
    positional = 0
    for seg in segments[:-1]:
        if _KWARG_RE.match(seg):
            continue
        positional += 1
    current = segments[-1]
    m = _KWARG_RE.match(current)
    if m:
        return positional, m.group(1), False
    if current.strip().startswith('*'):
        return positional, None, True
    return positional, None, False


# --------------------------------------------------------------------------
# signatures
# --------------------------------------------------------------------------

def render_arg(arg, default=None, star=''):
    """`name`, `name: type`, `name=default`, `name: type=default`, `*args`."""
    text = star + arg.arg
    annotation = getattr(arg, 'annotation', None)
    if annotation is not None:
        rendered = unparse(annotation)
        if rendered:
            text += ': ' + rendered
    if default is not None:
        text += '=' + unparse(default)
    return text


def node_signature_params(fnode, skip_self):
    """[(text, name, kind)] for the parameters of a function node."""
    args = fnode.args
    defaults = param_defaults(args)
    out = []
    positional = list(getattr(args, 'posonlyargs', []) or []) + \
        list(args.args or [])
    if skip_self and positional:
        positional = positional[1:]
    for p in positional:
        out.append((render_arg(p, defaults.get(id(p))), p.arg, 'pos'))
    if args.vararg is not None:
        out.append((render_arg(args.vararg, None, '*'), args.vararg.arg,
                    'vararg'))
    for p in args.kwonlyargs or []:
        out.append((render_arg(p, defaults.get(id(p))), p.arg, 'kwonly'))
    if args.kwarg is not None:
        out.append((render_arg(args.kwarg, None, '**'), args.kwarg.arg,
                    'kwarg'))
    return out


def signature_index(params, positional, kwname, ambiguous):
    """Index of the parameter the cursor binds to, or None."""
    if ambiguous:
        return None
    if kwname is not None:
        for i, (_t, name, kind) in enumerate(params):
            if kind in ('pos', 'kwonly') and name == kwname:
                return i
        for i, (_t, _n, kind) in enumerate(params):
            if kind == 'kwarg':
                return i
        return None
    slots = [i for i, (_t, _n, kind) in enumerate(params) if kind == 'pos']
    if positional < len(slots):
        return slots[positional]
    for i, (_t, _n, kind) in enumerate(params):
        if kind == 'vararg':
            return i
    return None


def sig_entry(name, params, description, docstring, index):
    return {
        'name': name or '',
        'params': [p[0] for p in params],
        'index': index,
        'description': description or '',
        'docstring': docstring or '',
    }


def _sig_source(kind, name, node=None, owner=None, obj=None, doc=None):
    return {'kind': kind, 'name': name, 'node': node, 'owner': owner,
            'obj': obj, 'doc': doc}


def stub_target(node, owner):
    """Redirect a function / class node to its stub declaration."""
    if owner is None or node is None:
        return node, owner
    pair = owner.stub_map.get(id(node))
    if pair:
        return pair[0], pair[1]
    return node, owner


def overload_group(fnode, owner):
    """Sibling `@overload` declarations of *fnode*, or None."""
    if owner is None or not _is_func_node(fnode):
        return None
    scope = owner.func_scopes.get(fnode)
    parent = scope.parent if scope is not None else None
    if parent is None:
        return None
    bindings = parent.defs.get(fnode.name) or []
    group = []
    for d in bindings:
        if _is_func_node(d.node) and 'overload' in decorator_names(d.node):
            if d.node not in group:
                group.append(d.node)
    if len(group) > 1 or (len(group) == 1 and group[0] is not fnode):
        return group
    return None


def _class_init(node, owner):
    """(node, owner) of the `__init__` a class would use, or None."""
    try:
        members = class_member_defs(node, owner)
    except Exception:
        return None
    for attr in ('__init__', '__new__'):
        for d in members.get(attr) or []:
            if _is_func_node(d.node) and d.owner is not None:
                return d.node, d.owner
    return None


def val_signature_sources(val, depth=0):
    """Callables described by *val*, as signature sources."""
    out = []
    if val is None or depth > 3:
        return out
    if val.kind == 'function':
        if val.node is not None and val.owner is not None:
            if isinstance(val.node, ast.Lambda):
                out.append(_sig_source('lambda', val.name or '<lambda>',
                                       val.node, val.owner, doc=''))
                return out
            node, owner = stub_target(val.node, val.owner)
            for n in (overload_group(node, owner) or [node]):
                out.append(_sig_source('func', n.name, n, owner))
            return out
        if val.obj is not None:
            out.append(_sig_source(
                'real', val.name or getattr(val.obj, '__name__', '') or '',
                obj=val.obj))
        return out
    if val.kind == 'class':
        if val.node is not None and val.owner is not None:
            init = _class_init(val.node, val.owner)
            doc = safe_docstring(val.node)
            if init is None:
                out.append(_sig_source('empty', val.node.name, val.node,
                                       val.owner, doc=doc))
                return out
            inode, iowner = stub_target(init[0], init[1])
            for n in (overload_group(inode, iowner) or [inode]):
                out.append(_sig_source('init', val.node.name, n, iowner,
                                       doc=doc or safe_docstring(n)))
            return out
        if val.obj is not None:
            out.append(_sig_source('real', val.name or
                                   getattr(val.obj, '__name__', '') or '',
                                   obj=val.obj))
        return out
    if val.kind == 'instance':
        for v in attr_vals(val, '__call__'):
            out.extend(val_signature_sources(v, depth + 1))
        return out
    return out


def _annotation_text(annotation):
    if annotation is inspect.Signature.empty:
        return ''
    if isinstance(annotation, str):
        return annotation
    if inspect.isclass(annotation):
        return getattr(annotation, '__name__', str(annotation))
    try:
        return str(annotation).replace('typing.', '')
    except Exception:
        return ''


def real_signature(obj, name, positional, kwname, ambiguous):
    try:
        sig = inspect.signature(obj)
    except Exception:
        return None
    params = []
    for p in sig.parameters.values():
        star = ''
        kind = 'pos'
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            star, kind = '*', 'vararg'
        elif p.kind is inspect.Parameter.VAR_KEYWORD:
            star, kind = '**', 'kwarg'
        elif p.kind is inspect.Parameter.KEYWORD_ONLY:
            kind = 'kwonly'
        text = star + p.name
        if p.annotation is not inspect.Parameter.empty:
            rendered = _annotation_text(p.annotation)
            if rendered:
                text += ': ' + rendered
        if p.default is not inspect.Parameter.empty:
            text += '=' + repr(p.default)
        params.append((text, p.name, kind))
    description = 'def %s(%s)' % (name, ', '.join(p[0] for p in params))
    rendered = _annotation_text(sig.return_annotation)
    if rendered:
        description += ' -> ' + rendered
    doc = ''
    try:
        doc = inspect.getdoc(obj) or ''
    except Exception:
        doc = ''
    path = ''
    lineno = 0
    try:
        f = inspect.getsourcefile(obj)
        if f:
            path = rel_module_path(f)
        lineno = inspect.getsourcelines(obj)[1] or 0
    except Exception:
        pass
    entry = sig_entry(name, params, description, doc,
                      signature_index(params, positional, kwname, ambiguous))
    return (path, lineno), entry


def build_signature(source, positional, kwname, ambiguous):
    kind = source['kind']
    if kind == 'real':
        return real_signature(source['obj'], source['name'], positional,
                              kwname, ambiguous)
    node = source['node']
    owner = source['owner']
    if node is None:
        return None
    if kind == 'empty':
        params = []
        description = 'def %s()' % source['name']
    else:
        if kind == 'init':
            skip_self = True
        elif kind == 'lambda':
            skip_self = False
        else:
            skip_self = bool(owner is not None and owner.is_method(node))
        params = node_signature_params(node, skip_self)
        description = 'def %s(%s)' % (source['name'],
                                      ', '.join(p[0] for p in params))
        returns = getattr(node, 'returns', None)
        if kind not in ('init',) and returns is not None:
            rendered = unparse(returns)
            if rendered:
                description += ' -> ' + rendered
    doc = source.get('doc')
    if doc is None:
        doc = safe_docstring(node)
    key = (rel_module_path(owner.path) if owner is not None else '',
           getattr(node, 'lineno', 0) or 0)
    return key, sig_entry(source['name'], params, description, doc,
                          signature_index(params, positional, kwname,
                                          ambiguous))


def parse_expression(text):
    for candidate in (text.strip(), text.strip().rstrip('.')):
        if not candidate:
            continue
        try:
            return ast.parse(candidate, mode='eval').body
        except Exception:
            continue
    return None


def find_signatures(analysis, lines, line, col):
    context = call_at(analysis.source, lines, line, col)
    if context is None:
        return []
    text, pos = context
    limit = min(offset_of(lines, line, col), len(analysis.source))
    positional, kwname, ambiguous = call_cursor_slot(
        analysis.source[pos + 1:limit])
    expr = parse_expression(text)
    if expr is None:
        return []
    completer = Completer(analysis, lines)
    scope = completer.scope_at(line, col)
    narrow = analysis.narrow_at(scope, line)
    vals = analysis._infer_multi(expr, scope, line, narrow)
    sources = []
    for v in dedup_vals(vals):
        try:
            sources.extend(val_signature_sources(v))
        except Exception:
            continue
    results = []
    seen = set()
    for source in sources:
        try:
            built = build_signature(source, positional, kwname, ambiguous)
        except Exception:
            built = None
        if built is None:
            continue
        key, entry = built
        dedup = (entry['name'], tuple(entry['params']), entry['description'])
        if dedup in seen:
            continue
        seen.add(dedup)
        results.append((key, entry))
    results.sort(key=lambda pair: pair[0])
    return [entry for _key, entry in results]


# --------------------------------------------------------------------------
# project files
# --------------------------------------------------------------------------

SKIP_DIRS = frozenset((
    '__pycache__', 'node_modules', 'site-packages', '.git', '.hg', '.svn',
    '.tox', '.mypy_cache', '.pytest_cache', '.venv', 'venv',
))


def project_python_files():
    """Every `.py` file under the project root, in a stable order."""
    root = project_root()
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not d.startswith('.'))
        for name in sorted(filenames):
            if name.endswith('.py'):
                out.append(os.path.join(dirpath, name))
    return out


# --------------------------------------------------------------------------
# references
# --------------------------------------------------------------------------

def _def_key(d):
    entry = binding_entry(d)
    if entry is None:
        return None
    return ('def', entry['module_path'], entry['line'], entry['column'],
            entry['name'])


def _scope_key(path, scope, name):
    return ('scope', path, scope.kind, scope.start, scope.col_offset,
            scope.qualname, name)


def _module_scope_key(target, name):
    return ('scope', rel_module_path(target.path), 'module', 1, -1, '', name)


def symbol_identity(analysis, lines, line, col):
    """Keys identifying the symbol referenced at (line, col), or None."""
    tok = name_token_at(analysis.source, lines, line, col)
    if tok is None:
        return None
    name, start, _end = tok
    text = lines[line - 1] if 0 <= line - 1 < len(lines) else ''
    completer = Completer(analysis, lines)
    keys = set()
    dot = dot_before(text, start)
    if dot >= 0:
        recv = scan_receiver(text, dot)
        expr = parse_expression(recv) if recv.strip() else None
        if expr is None:
            return None
        scope = completer.scope_at(line, col)
        narrow = analysis.narrow_at(scope, line)
        for base in analysis._infer_multi(expr, scope, line, narrow):
            if base.kind in ('class', 'instance') and base.node is not None \
                    and base.owner is not None:
                keys.add(('member', rel_module_path(base.owner.path),
                          base.node.lineno, name))
            elif base.kind == 'module':
                target = materialize(base)
                if isinstance(target, Analysis):
                    keys.add(_module_scope_key(target, name))
            for d in attr_defs(base, name):
                key = _def_key(d)
                if key is not None:
                    keys.add(key)
        return keys or None

    scope = completer.scope_at(line, col)
    narrow = analysis.narrow_at(scope, line)
    path = rel_module_path(analysis.path)
    s = scope
    while s is not None:
        if name in s.defs:
            keys.add(_scope_key(path, s, name))
            break
        s = s.parent
    defs = analysis.lookup_defs(scope, name, line, flow_of(narrow))
    if not defs:
        comp = analysis.comprehension_def(scope, name, line)
        if comp is not None:
            defs = [comp]
    for d in defs:
        key = _def_key(d)
        if key is not None:
            keys.add(key)
        if d.owner is not None and d.owner is not analysis:
            keys.add(_module_scope_key(d.owner, name))
        try:
            followed = follow_import_entries(d)
        except Exception:
            followed = None
        for e in followed or []:
            keys.add(('def', e['module_path'], e['line'], e['column'],
                      e['name']))
    if not keys:
        keys.add(('name', path, name))
    return keys


def name_occurrences(analysis, name):
    """[(line, column, is_definition)] for every mention of *name*."""
    found = {}

    def add(line, col, isdef):
        if not line or line < 1 or col is None or col < 0:
            return
        key = (line, col)
        found[key] = found.get(key, False) or bool(isdef)

    for node in ast.walk(analysis.tree):
        if isinstance(node, ast.Name):
            if node.id == name:
                add(node.lineno, node.col_offset,
                    not isinstance(node.ctx, ast.Load))
        elif isinstance(node, ast.Attribute):
            if node.attr == name:
                end_line = getattr(node, 'end_lineno', None) or node.lineno
                end_col = getattr(node, 'end_col_offset', None)
                if end_col is not None:
                    col = end_col - len(name)
                else:
                    col = analysis.ident_col(end_line, name, node.col_offset)
                add(end_line, col, not isinstance(node.ctx, ast.Load))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            if node.name == name:
                add(node.lineno, analysis.def_name_col(node), True)
        elif isinstance(node, ast.arg):
            if node.arg == name:
                add(node.lineno, node.col_offset, True)
        elif isinstance(node, ast.ExceptHandler):
            if node.name == name:
                add(node.lineno,
                    analysis.ident_col(node.lineno, name, node.col_offset),
                    True)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound = alias.asname or alias.name.split('.')[0]
                if bound == name:
                    add(getattr(alias, 'lineno', None) or node.lineno,
                        analysis._alias_col(node, alias, bound), True)
    return sorted((line, col, found[(line, col)]) for (line, col) in found)


def find_references(analysis, lines, line, col, scope_mode):
    target = symbol_identity(analysis, lines, line, col)
    if target is None:
        return None
    tok = name_token_at(analysis.source, lines, line, col)
    if tok is None:
        return None
    name = tok[0]
    sources = [analysis]
    if scope_mode == 'project':
        here = os.path.abspath(analysis.path) if analysis.path else None
        for path in project_python_files():
            if here is not None and os.path.abspath(path) == here:
                continue
            other = analyze_path(path)
            if other is not None and other is not analysis:
                sources.append(other)
    results = []
    seen = set()
    for a in sources:
        if not a.path or name not in (a.source or ''):
            continue
        for (ln, cl, isdef) in name_occurrences(a, name):
            try:
                identity = symbol_identity(a, a.lines, ln, cl)
            except Exception:
                identity = None
            if not identity or identity.isdisjoint(target):
                continue
            module_path = rel_module_path(a.path)
            key = (module_path, ln, cl)
            if key in seen:
                continue
            seen.add(key)
            results.append({'module_path': module_path, 'line': ln,
                            'column': cl, 'is_definition': bool(isdef)})
    results.sort(key=lambda r: (r['module_path'], r['line'], r['column']))
    return results


# --------------------------------------------------------------------------
# project-wide search / file names
# --------------------------------------------------------------------------

def searchable_defs(analysis):
    """Definitions of a module that are visible to `search`."""
    out = []
    stack = [analysis.module_scope]
    while stack:
        scope = stack.pop()
        for _name, bindings in scope.defs.items():
            for d in bindings:
                if d.import_ref is not None or getattr(d, 'is_stub', False):
                    continue
                if d.node is None or d.owner is None:
                    continue
                if isinstance(d.node, (ast.Import, ast.ImportFrom)):
                    continue
                out.append(d)
        for child in scope.children:
            if child.kind == 'class':
                stack.append(child)
    return out


def search_rank(name, query):
    lowered = name.lower()
    q = query.lower()
    if lowered == q:
        return 0
    if lowered.startswith(q):
        return 1
    if q in lowered:
        return 2
    return None


def search_project(query):
    results = []
    seen = set()
    for path in project_python_files():
        analysis = analyze_path(path)
        if analysis is None:
            continue
        for d in searchable_defs(analysis):
            rank = search_rank(d.name, query)
            if rank is None:
                continue
            entry = binding_entry(d)
            if entry is None:
                continue
            entry.pop('docstring', None)
            key = (entry['module_path'], entry['line'], entry['column'],
                   entry['name'], entry['type'])
            if key in seen:
                continue
            seen.add(key)
            results.append((rank, entry['module_path'], entry['line'],
                            entry['column'], entry['name'], entry))
    results.sort(key=lambda r: r[:5])
    return [r[5] for r in results]


def file_names(analysis, all_scopes):
    scopes = [analysis.module_scope]
    if all_scopes:
        stack = [analysis.module_scope]
        while stack:
            scope = stack.pop()
            for child in scope.children:
                scopes.append(child)
                stack.append(child)
    entries = []
    seen = set()
    for scope in scopes:
        for _name, bindings in scope.defs.items():
            for d in bindings:
                if getattr(d, 'is_stub', False):
                    continue
                entry = binding_entry(d)
                if entry is None:
                    continue
                entry['is_definition'] = True
                key = (entry['line'], entry['column'], entry['name'],
                       entry['type'])
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)
    entries.sort(key=lambda e: (e['line'], e['column'], e['name']))
    return entries


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def die(msg):
    sys.stderr.write('sith: %s\n' % msg)
    sys.exit(1)


USAGE = ('usage: sith.py complete|infer|goto|signatures|references '
         '<file> <line> <col> [--fuzzy] [--follow-imports] '
         '[--scope file|project] [--project DIR]\n'
         '       sith.py search <query> [--project DIR]\n'
         '       sith.py names <file> [--all-scopes] [--project DIR]')

CURSOR_COMMANDS = ('complete', 'infer', 'goto', 'signatures', 'references')
COMMANDS = CURSOR_COMMANDS + ('search', 'names')


def main(argv):
    args = argv[1:]
    fuzzy = False
    follow = False
    project = None
    all_scopes = False
    scope_mode = 'file'
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--fuzzy':
            fuzzy = True
        elif a == '--follow-imports':
            follow = True
        elif a == '--all-scopes':
            all_scopes = True
        elif a == '--dynamic-params':
            DYNAMIC_PARAMS[0] = True
        elif a in ('--no-dynamic-params', '--no-dynamic-param-inference'):
            DYNAMIC_PARAMS[0] = False
        elif a == '--':
            pass
        elif a.startswith('--project='):
            project = a.split('=', 1)[1]
        elif a == '--project':
            i += 1
            if i >= len(args):
                die('--project requires a directory')
            project = args[i]
        elif a.startswith('--scope='):
            scope_mode = a.split('=', 1)[1]
        elif a == '--scope':
            i += 1
            if i >= len(args):
                die('--scope requires file or project')
            scope_mode = args[i]
        elif a.startswith('--'):
            die('unknown option: %s' % a)
        else:
            positional.append(a)
        i += 1

    if not positional:
        die(USAGE)
    command = positional[0]
    if command not in COMMANDS:
        die('unknown command: %s' % command)
    if scope_mode not in ('file', 'project'):
        die('--scope must be file or project')

    if command == 'search':
        if len(positional) != 2:
            die(USAGE)
        query = positional[1]
        if project:
            if not os.path.isdir(project):
                die('no such directory: %s' % project)
            set_project_root(project)
        else:
            set_project_root(os.getcwd())
        return _run_search(query)

    if command == 'names':
        if len(positional) != 2:
            die(USAGE)
    elif len(positional) != 4:
        die(USAGE)

    path = positional[1]
    line = col = 0
    if command in CURSOR_COMMANDS:
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

    if command in CURSOR_COMMANDS:
        if line < 1 or line > len(lines):
            die('line out of range: %d' % line)
        if col < 0 or col > len(lines[line - 1]):
            die('column out of range: %d' % col)

    if project:
        if not os.path.isdir(project):
            die('no such directory: %s' % project)
        set_project_root(project)
    else:
        set_project_root(os.path.dirname(os.path.abspath(path)) or os.getcwd())

    if command == 'complete':
        return _run_complete(source, path, lines, line, col, fuzzy)
    if command == 'signatures':
        return _run_signatures(source, path, lines, line, col)
    if command == 'references':
        return _run_references(source, path, lines, line, col, scope_mode)
    if command == 'names':
        return _run_names(source, path, all_scopes)
    return _run_definitions(source, path, lines, line, col, command, follow)


def emit(payload):
    sys.stdout.write(json.dumps(payload, separators=(',', ':')) + '\n')


def main_analysis(source, path):
    """Analysis of the file under the cursor, shared with import lookups."""
    analysis = Analysis(source, path)
    if path:
        _analysis_cache[os.path.abspath(path)] = analysis
    return analysis


def _run_complete(source, path, lines, line, col, fuzzy):
    completions = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            analysis = main_analysis(source, path)
            completer = Completer(analysis, lines)
            completions = completer.complete(line, col, fuzzy)
    except Exception:
        try:
            with contextlib.redirect_stdout(buf):
                completions = _fallback(lines, line, col, fuzzy)
        except Exception:
            completions = []

    emit({'completions': completions})
    return 0


def _run_signatures(source, path, lines, line, col):
    signatures = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            analysis = main_analysis(source, path)
            signatures = find_signatures(analysis, lines, line, col)
    except Exception:
        signatures = []
    emit({'signatures': signatures})
    return 0


def _run_references(source, path, lines, line, col, scope_mode):
    references = None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            analysis = main_analysis(source, path)
            references = find_references(analysis, lines, line, col,
                                         scope_mode)
    except Exception:
        references = None
        try:
            with contextlib.redirect_stdout(buf):
                if name_token_at(source, lines, line, col) is not None:
                    references = []
        except Exception:
            references = None
    if references is None:
        sys.stderr.write('sith: no name at %d:%d\n' % (line, col))
        return 1
    emit({'references': references})
    return 0


def _run_search(query):
    results = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            results = search_project(query)
    except Exception:
        results = []
    emit({'definitions': results})
    return 0


def _run_names(source, path, all_scopes):
    entries = []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            analysis = main_analysis(source, path)
            entries = file_names(analysis, all_scopes)
    except Exception:
        entries = []
    emit({'definitions': entries})
    return 0


def _run_definitions(source, path, lines, line, col, command, follow=False):
    entries = None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            analysis = main_analysis(source, path)
            entries = run_query(analysis, lines, line, col, command, follow)
    except Exception:
        entries = None
        try:
            with contextlib.redirect_stdout(buf):
                if name_token_at(source, lines, line, col) is not None:
                    entries = []
        except Exception:
            entries = None

    if entries is None:
        sys.stderr.write('sith: no name at %d:%d\n' % (line, col))
        return 1

    emit({'definitions': sort_entries(entries)})
    return 0


def _fallback(lines, line, col, fuzzy):
    text = lines[line - 1]
    if import_context_at(lines, line, col) is not None:
        return []
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
