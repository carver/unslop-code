# sith

A static code intelligence tool for Python: it parses a source file, works out
which names are visible at a cursor position, what they refer to and where they
came from.

```
python sith.py complete <file> <line> <col> [--fuzzy]
python sith.py infer <file> <line> <col>
python sith.py goto <file> <line> <col>
```

`<line>` is 1-based, `<col>` is 0-based.  A single compact JSON object is
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
`class Calculator`.  `module_path` is relative to the project root, which is the
directory the analysed file lives in.  Names that come from outside the project
— builtins and installed packages — have nowhere to point, so they report an
empty path at line and column zero.  A name that could be several things, such
as one assigned in both arms of an `if`, reports one definition per
possibility, ordered by path, line and column.

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
| `sithlib/project.py` | Resolving module names to source files or real imports. |
| `sithlib/results.py` | Prefix matching and result ordering. |
| `sithlib/engine.py` | One request, end to end. |

Modules that live next to the analysed file are parsed rather than imported,
so project code is never executed; installed packages fall back to a real
import.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
