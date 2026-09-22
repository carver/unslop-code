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
python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
python sith.py infer    <file> <line> <col> [--project <dir>]
python sith.py goto     <file> <line> <col> [--follow-imports] [--project <dir>]
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
