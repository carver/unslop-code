# sith

A command-line Python code-intelligence tool. It parses Python source files
statically (never executing the file under analysis), resolves the names
visible at a cursor position and prints ranked completions as JSON.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # no third-party dependencies
```

## Usage

```sh
python sith.py complete   <file> <line> <col> [--fuzzy] [--project <dir>]
python sith.py infer      <file> <line> <col> [--project <dir>]
python sith.py goto       <file> <line> <col> [--follow-imports] [--project <dir>]
python sith.py signatures <file> <line> <col> [--project <dir>]
python sith.py references <file> <line> <col> [--scope file|project]
                          [--project <dir>]
python sith.py search     <query> [--project <dir>]
python sith.py names      <file> [--all-scopes] [--project <dir>]
```

* `<line>` is 1-based, `<col>` is 0-based.
* Output is a single compact, newline-terminated JSON object on STDOUT.
* Exit code is `0` on success (even with zero results) and `1` on error,
  with a message on STDERR.
* `--project` sets the project root: the directory imports are resolved
  against, that `module_path` is reported relative to and that qualified
  names are computed from. It defaults to the directory containing `<file>`.
* All paths in the output use forward slashes, whatever the host OS.

```sh
$ python sith.py complete example.py 12 6
{"completions":[{"name":"print","complete":"rint","type":"function","description":"def print(...)"}]}

$ python sith.py goto example.py 13 8
{"definitions":[{"name":"Calculator","type":"class","full_name":"example.Calculator","module_path":"example.py","line":7,"column":0,"description":"class Calculator","docstring":""}]}
```

### `signatures`, `references`, `search` and `names`

```sh
$ python sith.py signatures example.py 20 14
{"signatures":[{"name":"add","params":["x: int","y: int=1"],"index":1,"description":"def add(x: int, y: int=1) -> int","docstring":"Add numbers."}]}

$ python sith.py references example.py 7 6 --scope project
{"references":[{"module_path":"example.py","line":7,"column":6,"is_definition":true}]}
```

* `signatures` prints a `"signatures"` array describing the call the cursor
  sits inside: `name`, the rendered `params`, the 0-based `index` of the
  parameter under the cursor (`null` past the last one or when the position is
  ambiguous), a `description` and the `docstring`. Overloads -- and names that
  resolve to several functions -- yield one entry each, sorted by
  `(module_path, line)`. A cursor outside any call prints an empty array.
* `references` prints a `"references"` array of `module_path`, `line`,
  `column` and `is_definition`, sorted by `(module_path, line, column)`.
  `--scope file` (the default) looks in the file alone, `--scope project` in
  every `.py` file of the project; only occurrences of the *same* symbol are
  reported, never same-spelling names from unrelated scopes.
* `search` prints a `"definitions"` array of every `def`, `class` and
  top-level assignment whose name contains `<query>`, case-insensitively.
  Function bodies are not searched. Exact matches come first, then prefix
  matches, then the rest, each group ordered by `(module_path, line)`. The
  records are definition records without the `docstring`.
* `names` prints a `"definitions"` array of the names a file defines, each
  with an extra `is_definition` field, sorted by `(line, column)`. Only
  module-level names (including imports) are listed unless `--all-scopes`
  asks for every scope.

### Stub files

A `.pyi` stub next to a module -- or under a project-wide `stubs/` directory
(`stubs/foo.pyi`, `stubs/foo/__init__.pyi`) -- is the source of truth for type
information: parameter annotations feed `signatures`, return annotations feed
`infer`, and annotated attributes feed `complete`. Stub annotations beat
anything inference could work out. `goto` still lands on the runtime `.py`
source, unless the definition exists only in the stub.

### Dynamic parameter inference

A parameter with no annotation and no stub gets its type from the call sites
of its own function, in the file being analysed only. This drives both `infer`
and `signatures` (a callback parameter resolves to the function actually
passed in).

### `goto` and `infer`

Both print a `"definitions"` array; each entry has `name`, `type`
(`module`, `class`, `function`, `instance`, `statement` or `param`),
`full_name`, `module_path`, `line`, `column`, `description` and `docstring`.
Entries are sorted by `(module_path, line, column)`.

* `goto` answers *where the name under the cursor was bound* -- a `def`, a
  `class`, an assignment or an import binding. By default it stops at the
  `import` statement; `--follow-imports` walks the import chain (including
  re-exports) to the definition in the module it ultimately comes from, and
  falls back to the import statement when that module is not part of the
  project.
* `infer` answers *what that name evaluates to*: the class behind an instance,
  the return type of a call, the builtin type of a literal. Builtin types are
  reported with an empty `module_path` and `line`/`column` `0`.
* Both exit `1` when the cursor is not on a name, and return an empty array
  when nothing could be resolved.

## What it handles

* **Name completion** — locals, enclosing function scopes, module globals and
  builtins, honouring definition order, plus Python keywords.
* **Attribute completion** — modules, classes (with in-file inheritance),
  instances (including `self.x` attributes assigned in `__init__`), and
  literals such as strings, lists, dicts, sets and tuples.
* **Import completion** — `import <prefix>` offers top-level modules and
  packages (project first, then the standard library), `from X import
  <prefix>` offers the names `X` exports plus its submodules, and dotted and
  relative forms (`import x.y.<prefix>`, `from .x import <prefix>`) work too.
* **Prefix matching** — case-insensitive prefixes by default, case-insensitive
  subsequence matching with `--fuzzy`.
* **Broken code** — syntax errors are repaired heuristically so that code being
  edited still yields completions.
* **Type inference** — assignment chains, function return types (including
  several return paths at once), class instantiation, attribute access and
  `@dataclass` fields, across local modules.
* **Imports** — absolute and relative imports are resolved against the project
  root first (single-file modules, regular packages and namespace packages
  alike), then against the standard library; anything else is simply
  unresolvable and yields empty results. Project modules are parsed, never
  executed. `__all__` decides what a star import makes visible. Circular
  imports resolve to whatever is already bound and never loop.
* **Flow-sensitive narrowing** — inside an `isinstance(x, C)` branch `x` is a
  `C`; `x is None` / `x is not None` branches narrow a union accordingly. This
  drives both `infer` and attribute completion.
* **Unions** — a name with several possible types keeps all of them: `goto`
  and `infer` list every reachable definition and completion merges the
  attributes of all of them.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```
