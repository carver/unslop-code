# sith

A static Python code-intelligence CLI.

```
python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
python sith.py infer <file> <line> <col> [--project <dir>]
python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
python sith.py signatures <file> <line> <col> [--project <dir>]
python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
python sith.py search <query> [--project <dir>]
python sith.py names <file> [--all-scopes] [--project <dir>]
python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name> [--diff] [--project <dir>]
python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name> [--diff] [--project <dir>]
python sith.py errors <file>
python sith.py context <file> <line> <col> [--project <dir>]
python sith.py env list
python sith.py env find-virtualenvs [--path <dir>]
python sith.py env info [<executable>]
python sith.py project init [<dir>] [--environment <exe>] [--sys-path <p>[,<p>...]] [--added-sys-path <p>[,<p>...]]
```

Every command also accepts `--setting key=value` (zero or more), and the four analysis
commands accept `--interpreter` with `--namespaces <file>`.

`complete` prints a compact, newline-terminated JSON object with a `completions` array.
`infer` (what does this name evaluate to?) and `goto` (where was it defined?) print a JSON
object with a `definitions` array, sorted by `(module_path, line, column)`.

All three exit 0 on success and print a message to STDERR with exit 1 on file or position
errors; `infer`/`goto` also exit 1 when the cursor is not on a name.  A name that resolves to
nothing is an empty array, not an error.  Syntax errors in the analysed file are repaired line
by line instead of failing.

Inference covers literals, assignment chains, calls (including a function's `return`
statements), class instantiation, instance and dataclass attributes, unions from conditional
branches, and `isinstance` / `is None` narrowing.

`signatures` prints a `signatures` array for the call the cursor sits inside — the callable's
name, its rendered parameters, the 0-based `index` of the parameter being typed (`null` when
the cursor is past them all), a `description` and the docstring — sorted by `(module_path,
line)`, with one entry per overload or per possible callable, and empty when the cursor is not
inside a call.  `references` prints a `references` array of `(module_path, line, column,
is_definition)` for every occurrence of the name under the cursor that resolves to the same
symbol, over the one file by default and over every project `.py` with `--scope project`.
`search` prints a `results` array of definitions whose name contains `<query>`
(case-insensitive), ranked exact, then prefix, then substring; function bodies are not indexed.
`names` prints a `names` array of what one file defines — module level by default, every scope
with `--all-scopes`.

`context` prints a `context` array of the scopes enclosing the cursor — `(name, type, line,
column)` per entry, outermost first, empty at module level.

## Interpreter mode

`complete`, `infer`, `goto` and `signatures` take `--interpreter --namespaces <file>`, where the
file is a JSON array of namespaces (each a map of name to `{type, value?, module?, name?,
attributes?}`).  Static analysis keeps priority: a namespace is consulted only for a symbol
static analysis cannot resolve, and the namespaces are searched in order with the first match
winning.  Runtime results carry the namespace's `type` string and the description
`"<type> (runtime)"`.  `--interpreter` alone behaves exactly like normal mode; `--namespaces`
without `--interpreter` is an error.

## Environments and project configuration

`env list` reports every Python installation it can find — `(executable, version,
is_virtualenv)`, newest version first, ties broken by path, de-duplicated across symlinks.
`env find-virtualenvs [--path <dir>]` restricts the search to virtualenv locations: the
immediate subdirectories of `--path`, `~/.virtualenvs/`, and `.venv/` / `venv/` in the current
directory and the project root.  `env info [<executable>]` adds `prefix` and `sys_path` for one
environment, defaulting to the project's configured interpreter and then to `python3`.

`project init [<dir>]` writes `<dir>/.sith/project.json`, merging `--environment`, `--sys-path`
and `--added-sys-path` into whatever is already there.  Every command reads that file from the
project root: `sys_path` replaces the auto-detected import roots, `added_sys_path` appends to
them, and `smart_sys_path` (default true) controls whether the project root and the directories
holding an `__init__.py` are added at all.

## Settings

`--setting key=value` overrides `case_insensitive` (true), `dynamic_params` (true),
`smart_sys_path` (true) and `add_bracket` (false); values are `true`/`false`, case-insensitive,
and an unknown key or value exits 1.  A `--setting` beats the project config, which beats these
defaults.

## Refactoring

`rename`, `inline`, `extract-variable` and `extract-function` transform code instead of
describing it.  Each prints `changed_files` — a map of project-relative path to the file's new
content, holding only the files whose content really changed — together with `renames`, the map
of old path to new path for a module or package that moved.  With `--diff` the output is plain
unified-diff text on STDOUT instead, one `--- a/<path>` / `+++ b/<path>` pair per changed file.

`rename` rewrites every occurrence `references --scope project` finds.  With the cursor on a
module name it moves the file (`foo.py` to `<new>.py`) or the package directory and rewrites
every import that names it.  `inline` replaces a simple `x = <expr>` variable with its value,
parenthesising it wherever precedence demands, and deletes the assignment.  `extract-variable`
lifts the expression spanning `<line>:<col>` to `--until <line>:<col>` into a new assignment on
the line above the enclosing statement.  `extract-function` lifts whole statements into a new
function placed before the enclosing definition, passing the variables they read as parameters
and returning the ones still used afterwards.

A refactoring that cannot be done safely — an invalid new name, a cursor that is not on a name, a
selection that cuts an expression or statement in half, a new name that collides in the same
scope, a `def`/`class` or an unused name given to `inline` — exits 1 with a message on STDERR and
prints nothing at all on STDOUT.

`errors` prints an `errors` array of `(line, column, until_line, until_column, message)` for the
file's syntax errors, exiting 0 whether or not any were found; only a file that cannot be read at
all is exit 1.  Every other command repairs syntax errors line by line instead of reporting them.

## Stubs

A `.pyi` stub supplies type information for the module beside it: `foo.pyi` next to `foo.py`
first, then `stubs/foo.pyi` and `stubs/foo/__init__.pyi` below the project root.  Stub
annotations beat inferred types for `infer`, `signatures` and attribute `complete`, while
`goto` keeps navigating to the `.py` source — except for a name only the stub declares.

Parameters with neither an annotation nor a stub are inferred from the call sites in their own
file; other files are never scanned for call sites.

## Projects

The tool analyses a project, not a lone file.  The project root is `--project <dir>` when given
and the directory holding `<file>` otherwise; it is where modules are looked up and the base for
`module_path` and dotted `full_name`s (always with `/` separators).

Imports resolve against the project root first — `.py` files, packages and namespace package
directories, absolute and relative — and then against the standard library.  Anything else is
unresolvable: `infer` and attribute completion return nothing, and `goto` falls back to the
import statement.  Star imports bring in `__all__` when the module defines one and every
non-underscore name otherwise.

`goto` stops at the import statement by default; `--follow-imports` chases the chain — through
re-exports, package `__init__.py` files and star imports — to the definition in the source
module, falling back to the import site when the chain leaves the project.  `complete` knows
import statements too: `import |` offers module names, `from X import |` offers `X`'s exported
names.

## Layout

- `sith.py` — the tool (standard library only).
- `tests/` — spec-derived tests, one section per spec phrase.
- `AMBIGUITIES.md` — under-specified points, the reading chosen, and its risk.
- `requirements.txt` — test/lint dependencies (`python -m venv .venv && .venv/bin/pip install -r requirements.txt`).

Run the tests with `.venv/bin/python -m pytest tests`.
