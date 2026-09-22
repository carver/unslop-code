# sith

A static code intelligence tool for Python: it parses a project, works out
which names are visible at a cursor position, what they refer to and where they
came from.

```
python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
python sith.py infer <file> <line> <col> [--project <dir>]
python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
```

`<line>` is 1-based, `<col>` is 0-based.  `--project` is the root the analysed
file belongs to: it is where modules are searched for and what qualified names
are measured from.  Without it the root is the directory holding `<file>`, so
a file is still analysable on its own.  A single compact JSON object is
written to stdout; anything that makes the request impossible (missing file,
undecodable bytes, a cursor outside the file, a cursor that is not on a name)
is reported on stderr with exit status 1.  Syntax errors in the analysed file
are not failures — broken lines are repaired in place and analysis continues
from whatever parsed.

`complete` answers "what could I type here", `goto` answers "where was this
name written down", and `infer` answers "what does this name evaluate to".
The last two both return a `definitions` array:

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
| `sithlib/imports.py` | What an import statement names and what a module exports. |
| `sithlib/project.py` | Resolving module names to source files or real imports. |
| `sithlib/results.py` | Prefix matching and result ordering. |
| `sithlib/engine.py` | One request, end to end. |

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
