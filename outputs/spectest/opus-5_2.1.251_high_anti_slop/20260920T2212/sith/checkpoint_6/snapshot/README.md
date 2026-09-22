# sith

A static code intelligence tool for Python: it parses a project, works out
which names are visible at a cursor position, what they refer to and where they
came from.

```
python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
python sith.py infer <file> <line> <col> [--project <dir>]
python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
python sith.py signatures <file> <line> <col> [--project <dir>]
python sith.py context <file> <line> <col> [--project <dir>]
python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
python sith.py search <query> [--project <dir>]
python sith.py names <file> [--all-scopes] [--project <dir>]
python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>
                                [--diff] [--project <dir>]
python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name>
                                [--diff] [--project <dir>]
python sith.py errors <file>
python sith.py env list
python sith.py env find-virtualenvs [--path <dir>]
python sith.py env info [<executable>]
python sith.py project init [<dir>] [--environment <executable>]
                            [--sys-path <path>[,<path>...]]
                            [--added-sys-path <path>[,<path>...]]
```

Every command takes zero or more `--setting key=value` flags, and `complete`,
`infer`, `goto` and `signatures` take `--interpreter [--namespaces <file>]`.

`<line>` is 1-based, `<col>` is 0-based.  `--project` is the root the analysed
file belongs to: it is where modules are searched for and what qualified names
are measured from.  Without it the root is the directory holding `<file>`, so
a file is still analysable on its own, and for `search`, which names no file
at all, the root is the working directory.  A single compact JSON object is
written to stdout -- unless `--diff` asks a refactoring for a diff, which is
plain text -- and anything that makes the request impossible (missing file,
undecodable bytes, a cursor outside the file, a cursor that is not on a name)
is reported on stderr with exit status 1.  Syntax errors in the analysed file
are not failures — broken lines are repaired in place and analysis continues
from whatever parsed.

`complete` answers "what could I type here", `goto` answers "where was this
name written down", and `infer` answers "what does this name evaluate to".
`signatures` answers "what does this call take", `context` "what am I inside",
`references` "where else is this used", and `search` and `names` "what is
there".  Each writes one array under a key of its own: `completions`,
`definitions`, `signatures`, `context`, `references`, `results` and `names`.
`errors` answers "what does not parse", and `rename`, `inline`,
`extract-variable` and `extract-function` change the code rather than describe
it: they report the files they would write, and write none of them.

`goto` and `infer` both return a `definitions` array:

```json
{"definitions":[{"name":"Calculator","type":"class","full_name":"example.Calculator",
  "module_path":"example.py","line":7,"column":6,"description":"class Calculator",
  "docstring":""}]}
```

`column` is the column of the identifier itself, so it points at the `C` of
`class Calculator`.  `module_path` is relative to the project root and always
written with forward slashes.  Names that come from outside the project
— builtins and installed packages — have nowhere to point, so they report an
empty path at line and column zero.  A name that could be several things, such
as one assigned in both arms of an `if`, reports one definition per
possibility, ordered by path, line and column.

## Signatures

`signatures` reports the call whose argument list the cursor is inside, which
does not have to be finished: the call is read from the text, so `f(` answers
as readily as `f(1, 2)`.  A cursor outside any call is not a failure, it simply
has nothing to report.

```json
{"signatures":[{"name":"greet","params":["name: str","greeting: str='hi'","**extra"],
  "index":1,"description":"def greet(name: str, greeting: str='hi', **extra) -> str",
  "docstring":"Say hello."}]}
```

A parameter is rendered as it was declared -- `name`, `name: type`,
`name=default`, `name: type=default`, `*args`, `**kwargs` -- and the `self` of
a method is left out, of the parameters and of the description alike.  `index`
is the parameter the argument being typed binds to, following Python's own
rules: positional arguments fill the positional parameters left to right, a
keyword argument picks the parameter of that name, and anything left over
lands in `*args` or `**kwargs`.  When no parameter can take the argument,
`index` is `null`.

A call reports more than one signature when the name resolves to more than one
function, and when the function is written as a series of `@overload`
declarations.  They are ordered by path and line.  Calling a class reports its
`__init__` under the class' own name.

## Scope context

`context` reports the classes and functions the cursor is written inside, as
`{"name", "type", "line", "column"}`, ordered from the outermost scope inwards:

```json
{"context":[{"name":"Shop","type":"class","line":4,"column":6},
  {"name":"sell","type":"function","line":7,"column":8}]}
```

`type` is `class` or `function`, `line` is where the definition is written and
`column` is where its name starts.  A cursor at module level is inside nothing
and reports an empty array.

## References, search and listings

`references` reports every place a name is written, as
`{"module_path", "line", "column", "is_definition"}`, ordered by path, line and
column.  Within one file -- the default -- every occurrence of the name counts,
whichever scope it belongs to.  `--scope project` reads every `.py` file of the
project and keeps only the occurrences that resolve to the same symbol as the
one under the cursor, so a local of the same spelling in another function, or
an unrelated function of the same name in another module, stays out.

`search` looks for a name anywhere in the project: a case insensitive substring
match, ranked exact first, then prefix, then anywhere, and by path and line
within each group.  It reports definitions -- the same fields as `goto`, minus
the docstring -- and only the ones worth finding from outside: the `def`s,
`class`es and assignments a module and its classes write down.  A local
variable is not searchable, and an imported name is reported where it was
defined rather than where it was imported.

`names` lists what one file defines, as definitions carrying `is_definition`,
ordered by line and column.  Module level names -- including the ones imports
bring in -- are the default; `--all-scopes` adds the parameters, locals, nested
definitions and class attributes of every scope the file holds.

## Refactoring

`rename`, `inline`, `extract-variable` and `extract-function` rewrite code
instead of reporting on it.  Nothing is written to disk: each reports what the
project would look like afterwards, either as whole files

```json
{"changed_files":{"app.py":"from core import assist\n\nresult = assist(2)\n"},
 "renames":{}}
```

or, with `--diff`, as a unified diff on stdout and no JSON at all:

```
--- a/core.py
+++ b/core.py
@@ -1,4 +1,4 @@
-TOTAL = 1
+COUNT = 1
```

`changed_files` holds only the files whose content actually changed, keyed by
the path they end up at.  `renames` maps an old path to a new one, for the file
and directory moves that renaming a module makes; it is empty otherwise.  A
refactoring that cannot be made -- a new name that is not an identifier or is
already taken, a cursor that is not on a name, a selection that is not a
complete piece of code -- writes nothing at all and fails with exit status 1.

`rename` renames the name under the cursor and every reference `references
--scope project` would find, so an unrelated name of the same spelling stays as
it is.  A cursor on a module renames the module: `foo.py` becomes
`<new name>.py`, a package directory is moved whole, and the imports that name
it -- `import foo`, `from foo import x`, `from pkg import foo`, and the
relative forms of each -- are restated to match.

`inline` replaces every reference to a variable with the expression it was
assigned and deletes the assignment.  The expression is bracketed wherever its
new surroundings would otherwise regroup it, so `total = a + b` inlined into
`total * 2` gives `(a + b) * 2`.  Only a plain `x = <expr>` can be inlined, and
only when something reads it.

`extract-variable` takes the expression between the cursor and `--until` and
assigns it to `--name` on the line above the statement it was written in, at
that statement's indentation.  The selection has to be exactly one expression.

`extract-function` takes the statements between the cursor and `--until` --
whole ones, whole lines -- and moves them into a function named `--name`,
called where they stood.  The names the selection reads but does not set become
its parameters, in the order it first reads them, and the names it sets that
are read below it become what it returns: one bare, several as a tuple the call
site unpacks in the same order.  The function is written immediately above the
function or class the statements came out of and indented to sit beside it, or
immediately above the statements themselves when they were at module level --
where reading a module level name still makes it a parameter rather than
leaving it to be found as a global.

## Interpreter mode

`--interpreter` says the file is being written against a live session -- a
REPL, a notebook -- whose namespaces `--namespaces` describes.  The file is
a JSON array of namespaces, each an object mapping a name to what it holds:

```json
[{"frame": {"type": "DataFrame", "value": "<DataFrame 3x2>", "module": "pandas",
            "attributes": ["head", "shape"]},
  "total": {"type": "int", "value": "42"}}]
```

Only `type` is required; `value` is the string representation of the object,
which is reported as the docstring, `module` is where the value came from,
`name` is what the value is called when that differs from the key it is bound
under, and `attributes` are the attributes a class or module is known to have.

Static analysis keeps its priority: a namespace is only consulted for a name
the source cannot account for, and the namespaces themselves are searched in
order, so the first one holding a name is the one that answers.  Completion
offers the names of both, and a name from a namespace reports the type the
namespace gave it and a description of `"<type> (runtime)"`, which is what
`infer` and `goto` report for it too:

```json
{"definitions":[{"name":"frame","type":"DataFrame","full_name":"pandas.frame",
  "module_path":"","line":0,"column":0,"description":"DataFrame (runtime)",
  "docstring":"<DataFrame 3x2>"}]}
```

`--interpreter` without `--namespaces` is normal analysis; `--namespaces`
without `--interpreter` is a mistake and fails with exit status 1.

## Environments

`env` reports the Python installations of the machine, each as
`{"executable", "version", "is_virtualenv"}`, newest version first and, within
one version, by path.  Two paths leading to the same interpreter of the same
prefix are one environment and reported once.

`env list` finds the interpreters on `PATH` and the virtualenvs of the standard
places; `env find-virtualenvs` reports only virtualenvs, looking inside the
subdirectories of `--path`, inside `~/.virtualenvs`, and at `.venv` and `venv`
of the working directory.  `env info` describes one environment -- the one
named, else the one the project configures, else `python3` -- and adds its
`prefix` and its `sys_path`:

```json
{"executable":"/usr/bin/python3","version":"3.11.6","is_virtualenv":false,
 "prefix":"/usr","sys_path":["","/usr/lib/python311.zip"]}
```

An executable that is missing, or that is not a Python at all, fails with exit
status 1.

## Project configuration

`project init` writes `<dir>/.sith/project.json`, creating the directory and
merging what it is given into whatever the file already says:

```json
{"environment_path":"","sys_path":[],"added_sys_path":["lib"],"smart_sys_path":true}
```

`environment_path` is the interpreter the project belongs to, which `env info`
describes when it is asked about no other; an empty value means the system
one.  The rest says where an import is looked for.  `smart_sys_path`, on by
default, searches the project root and every directory an `__init__.py` makes
a package, so a module inside a package is importable under its own name;
`sys_path` replaces that detection with the paths it lists, and
`added_sys_path` is searched after either, which is what makes a module the
project keeps off the root -- in a `lib/` directory, say -- importable.  A
relative path is read from the project root.

Every command reads the configuration of the root it is working in, which is
`--project` or the directory holding the analysed file.  Nothing else about a
configured environment is executed: project code is still only ever parsed.

## Settings

`--setting key=value` overrides one default, and may be repeated.  A setting
given on the command line beats one the project configures, which beats the
default.

| Setting | Default | What it does |
|---------|---------|--------------|
| `case_insensitive` | `true` | Match a completion prefix without regard to case. |
| `dynamic_params` | `true` | Type an unannotated parameter from the calls to it. |
| `smart_sys_path` | `true` | Detect the import roots of the project. |
| `add_bracket` | `false` | End the `complete` of a function or class with `(`. |

A setting that is not one of these, or a value that is neither `true` nor
`false`, fails with exit status 1.

## Syntax errors

`errors` reports what the parser rejected, as `{"line", "column", "until_line",
"until_column", "message"}`:

```json
{"errors":[{"line":1,"column":11,"until_line":1,"until_column":12,
  "message":"invalid syntax"}]}
```

A broken line is repaired the way every other command repairs it and the parse
carries on, so a file with several broken lines reports several errors, ordered
by position.  A file that parses reports `{"errors":[]}`.  Finding an error is
not a failure -- the array is the answer, and only a file that cannot be read
at all is reported on stderr with exit status 1.

## Stub files

A `.pyi` stub is where a project says what an unannotated or dynamic module
really looks like.  For a module `foo` the stub is `foo.pyi` beside `foo.py`,
or failing that `stubs/foo.pyi` or `stubs/foo/__init__.pyi` under the project
root.

When there is one, the types come from the stub and the positions from the
implementation: `signatures` reads the stub's parameter annotations, `infer`
its return annotations and `complete` its attribute annotations, while `goto`
still lands on the `.py` line that writes the name.  A stub annotation beats an
inferred type.  A name the stub declares and the implementation does not has
only the stub to point at, so that is what it reports.

## Parameters typed by their callers

A parameter with no annotation and no stub is typed by the calls the module
makes to its own function: `twice("hello")` a few lines below `def twice(value)`
is what says `value` is a `str`, which `infer` reports and completion offers
attributes for.  Only the file being analysed is read -- how another module
calls a function says nothing about how this one should be read.  The rendered
signature still shows the parameter as it was written, since an inferred type
is not an annotation; it reaches `signatures` the other way round, by resolving
a parameter that holds a function to the function it holds.

## Imports

A module name is looked for in the project root first, where it is parsed
rather than imported so that project code is never executed, and then in the
standard library, which is imported for real.  Anything else — a third party
package, a module that does not exist — is unresolvable: it contributes no
completions and no definitions, which is not an error.  Directories count as
packages whether or not they hold an `__init__.py`, and a relative import
counts the dots from the package its module sits in; one that reaches above
the project root is unresolvable too.  Two modules that import each other do
not send the tool in circles: whatever is not built yet is simply not visible.

`from x import *` brings in the public names of `x`, which are the ones
`__all__` lists when the module declares one and every name not starting with
an underscore when it does not.  The same rule decides what a
`from x import ...` completion offers.

`goto` reports the `import` statement that brought a name into the file being
analysed.  `--follow-imports` chases the chain instead, through as many
re-exports as it takes, and reports where the name was really written; an
import leading out of the project has nothing to point at, so the import
statement stands in for it.

Completion reads an unfinished import too: `import ` and `from ` offer the
modules of the project followed by those of the standard library, `import pkg.`
offers what the package holds, and `from pkg.core import ` offers the names
inside that module.

## What is inferred

Literals, assignment chains, class instantiation, attribute access and the
annotated fields of a dataclass all resolve to the type they produce.  A call
resolves to what the function returns: its return annotation if it has one,
otherwise the union of the values its `return` statements produce, and `None`
when it never returns a value.  Inside a branch guarded by `isinstance(x, C)`
or `x is None`, the guarded name takes the type the test proves, for both
inference and attribute completion.

## Layout

| Module | Responsibility |
|--------|----------------|
| `sith.py` | Argument parsing and JSON output. |
| `sithlib/source.py` | Loading the file and reading what the cursor is typing. |
| `sithlib/cursor.py` | The name a cursor sits on, and where a definition writes its name. |
| `sithlib/parsing.py` | Syntax-error tolerant parsing. |
| `sithlib/scopes.py` | The scope tree, its visibility rules and its bindings. |
| `sithlib/builder.py` | Recording every name a module body binds. |
| `sithlib/values.py` | What a name refers to and which attributes it exposes. |
| `sithlib/inference.py` | The value an expression evaluates to. |
| `sithlib/narrowing.py` | The types a branch test proves about the names it guards. |
| `sithlib/definitions.py` | The records `infer` and `goto` report. |
| `sithlib/signatures.py` | What a callable declares and which parameter a call is on. |
| `sithlib/calls.py` | Finding the call whose argument list a cursor sits in. |
| `sithlib/callsites.py` | Typing an unannotated parameter from its callers. |
| `sithlib/references.py` | Where a name leads and where else it is written. |
| `sithlib/renaming.py` | Spelling a symbol anew wherever the project writes it. |
| `sithlib/moves.py` | Renaming a module: its file, its directory and its imports. |
| `sithlib/inlining.py` | Replacing a variable with the expression it holds. |
| `sithlib/extraction.py` | Pulling a selection out into a variable or a function. |
| `sithlib/precedence.py` | Where a substituted expression needs brackets. |
| `sithlib/trees.py` | The nodes a selected region of a file covers. |
| `sithlib/edits.py` | Applying edits and reporting them as files or as a diff. |
| `sithlib/diagnostics.py` | The syntax errors a file holds. |
| `sithlib/symbols.py` | Listing and searching the names a project defines. |
| `sithlib/stubs.py` | Type information read from `.pyi` files. |
| `sithlib/imports.py` | What an import statement names and what a module exports. |
| `sithlib/project.py` | Resolving module names to source files or real imports. |
| `sithlib/config.py` | What `.sith/project.json` declares about a project. |
| `sithlib/options.py` | The settings, configuration and namespaces of a request. |
| `sithlib/namespaces.py` | The live namespaces interpreter mode falls back to. |
| `sithlib/environments.py` | Finding and describing Python installations. |
| `sithlib/contexts.py` | The scopes a cursor is written inside. |
| `sithlib/results.py` | Prefix matching and result ordering. |
| `sithlib/engine.py` | One request, end to end. |

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
