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
python sith.py env        list
python sith.py env        find-virtualenvs [--path <dir>]
python sith.py env        info [<executable>]
python sith.py project    init [<dir>] [--environment <executable>]
                          [--sys-path <path>[,<path>...]]
                          [--added-sys-path <path>[,<path>...]]
```

* `<line>` is 1-based, `<col>` is 0-based.
* Output is a single compact, newline-terminated JSON object on STDOUT.
* Exit code is `0` on success (even with zero results) and `1` on error,
  with a message on STDERR.
* `--project` sets the project root: the directory imports are resolved
  against, that `module_path` is reported relative to and that qualified
  names are computed from. It defaults to the directory containing `<file>`.
* All paths in the output use forward slashes, whatever the host OS.
* `complete`, `infer`, `goto` and `signatures` additionally take
  `--interpreter` with `--namespaces <file>` (see *Interpreter mode*).
* Every command takes any number of `--setting <key>=<value>` flags (see
  *Settings*) and reads `.sith/project.json` from the project root (see
  *Project configuration*).

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

### `context`

```sh
$ python sith.py context example.py 9 8
{"context":[{"name":"Calculator","type":"class","line":7,"column":0},{"name":"add","type":"function","line":8,"column":4}]}
```

`context` prints a `"context"` array describing the scopes the cursor sits
inside, ordered from the outermost non-module scope inwards. Each entry has
the scope's `name`, its `type` (`class` or `function`), the 1-based `line` and
the 0-based `column` of its definition. A cursor at module level prints an
empty array.

### Refactorings

```sh
$ python sith.py rename example.py 7 6 --new-name Machine
{"changed_files":{"example.py":"class Machine:\n    pass\n"},"renames":{}}

$ python sith.py rename example.py 7 6 --new-name Machine --diff
--- a/example.py
+++ b/example.py
@@ -1,2 +1,2 @@
-class Calculator:
+class Machine:
     pass
```

`rename`, `inline`, `extract-variable` and `extract-function` all print the
same object: `changed_files` maps a project-relative path to that file's new
contents -- only files whose text really changed are listed -- and `renames`
maps an old path to a new one when the edit moves a file or a directory
(otherwise it is empty). `--diff` swaps the JSON for a plain-text unified
diff on STDOUT. A validation failure exits `1` with a message on STDERR and
prints nothing at all.

* `rename` renames the name under the cursor and every reference the
  `references --scope project` logic finds. On a module name -- in an import
  or wherever that module is bound -- the module's file is renamed too
  (`foo.py` to `<new_name>.py`, a package directory to `<new_name>/`) and
  every import mentioning it is rewritten. `--new-name` must be a valid
  Python identifier, the cursor must be on a name, and a new name that
  already exists in the scope the rename lands in is refused.
* `inline` replaces every reference to a variable with the assigned
  expression and deletes the assignment, bracketing the expression wherever
  dropping the brackets would change precedence. A `def` or `class` cannot be
  inlined, and neither can an unused name.
* `extract-variable` lifts the expression spanning the cursor to `--until`
  into a new assignment on the line above the statement holding it, at that
  statement's indentation. The selection has to be exactly one expression.
* `extract-function` moves the whole statements spanning the cursor to
  `--until` into a new function placed immediately before the enclosing
  function or class (before the first selected line at module level), at the
  same indentation. Names the selection reads but does not define become
  parameters, in order of first appearance; names it assigns and the code
  after it still reads become return values, as a tuple when there are
  several, unpacked at the call site.

### `errors`

```sh
$ python sith.py errors broken.py
{"errors":[{"line":2,"column":0,"until_line":2,"until_column":6,"message":"expected an indented block after function definition on line 1"}]}
```

`errors` prints an `"errors"` array of `line` (1-based), `column` (0-based),
`until_line`, `until_column` and the parser's `message`. A clean file prints
`{"errors":[]}`. Either way the exit code is `0`: only a tool failure, such
as a missing file, exits `1`.

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

## Interpreter mode

```sh
$ python sith.py complete session.py 3 2 --interpreter --namespaces ns.json
{"completions":[{"name":"df","complete":"f","type":"DataFrame","description":"DataFrame (runtime)"}]}
```

`--interpreter` turns on REPL-style analysis: `--namespaces <file>` hands the
tool the live namespaces of an interpreter session so that names only a
running process knows about still resolve.

The file holds a JSON array of namespace objects. Each key is a name and each
value describes the runtime value behind it:

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Python type name: `int`, `str`, `list`, `function`, `class`, `module`, ... |
| `value` | string | Optional. Printable form of the value; it becomes the `docstring`. |
| `module` | string | Optional. Module the value comes from; it feeds `full_name`. |
| `name` | string | Optional. Original name, when it differs from the key. |
| `attributes` | array of string | Optional. Known attributes of a class or module. |

* Static analysis keeps its priority; a namespace is consulted only for what
  it could not resolve.
* Namespaces are searched in order and the first match wins, for `complete`,
  `infer` and `goto` alike.
* `complete` merges the static names and the runtime ones; `infer`, `goto`
  and `signatures` fall back on the namespaces when nothing static matched.
* A namespace-derived result reports the namespace `type` as its `type` and
  exactly `"<type> (runtime)"` as its `description`.
* `--interpreter` on its own behaves exactly like normal mode. `--namespaces`
  without `--interpreter` exits `1`.

## Python environments

```sh
$ python sith.py env list
{"environments":[{"executable":"/usr/bin/python3","version":"3.13.5","is_virtualenv":false}]}
```

* `env list` finds the Python installations on the system: every interpreter
  reachable through `PATH` plus the one running the tool. Each record has the
  absolute `executable`, its `version` and `is_virtualenv`. Records are
  deduplicated by resolved path (symlinks followed) and sorted by version,
  newest first, then by executable.
* `env find-virtualenvs [--path <dir>]` prints the same records for
  virtualenvs only, looking inside `--path` and its immediate subdirectories,
  `~/.virtualenvs/`, and `.venv/` and `venv/` in the current directory and the
  project root.
* `env info [<executable>]` adds the environment's `prefix` and `sys_path` to
  that record, printing it at the top level and, for convenience, under an
  `"environment"` key and as a one-element `"environments"` array. Without an
  argument it uses the configured `environment_path`, falling back on the
  system default (`python3`). An executable that is missing or is not a
  Python exits `1`.

## Project configuration

```sh
$ python sith.py project init . --added-sys-path libs
{"environment_path":"","sys_path":[],"added_sys_path":["libs"],"smart_sys_path":true}
```

`project init [<dir>]` creates or updates `<dir>/.sith/project.json`,
creating `.sith/` when needed and merging the flags that were passed into
whatever the file already held.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `environment_path` | string or null | `""` | Python executable this project uses; empty means the system default. |
| `sys_path` | array of string | `[]` | Explicit import roots; they replace the auto-detected ones. |
| `added_sys_path` | array of string | `[]` | Extra import roots, appended after the others. |
| `smart_sys_path` | bool | `true` | Add the project root to the import roots automatically. |

Every command reads that file from the project root -- `--project`, or the
directory of the file being analysed. Relative paths in it are resolved
against the project root. `--environment <executable>`, `--sys-path` and
`--added-sys-path` take comma-separated lists; `smart_sys_path` is written by
passing `--setting smart_sys_path=<bool>` to `project init`.

## Settings

`--setting <key>=<value>` overrides one default, and may be repeated. A
`--setting` beats the project configuration, which beats the default. An
unknown key or a value that is not `true`/`false` exits `1`.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `case_insensitive` | bool | `true` | Case-insensitive completion matching. |
| `dynamic_params` | bool | `true` | Infer parameter types from call sites. |
| `smart_sys_path` | bool | `true` | Auto-detect the import roots. |
| `add_bracket` | bool | `false` | Append `(` to function and class completions in `complete`. |

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```
