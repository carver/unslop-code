# sith

A static code intelligence tool for Python: it parses a source file, works out
which names are visible at a cursor position, and ranks them as completions.

```
python sith.py complete <file> <line> <col> [--fuzzy]
```

`<line>` is 1-based, `<col>` is 0-based.  A single compact JSON object is
written to stdout; anything that makes the request impossible (missing file,
undecodable bytes, a cursor outside the file) is reported on stderr with exit
status 1.  Syntax errors in the analysed file are not failures — broken lines
are repaired in place and completion continues from whatever parsed.

## Layout

| Module | Responsibility |
|--------|----------------|
| `sith.py` | Argument parsing and JSON output. |
| `sithlib/source.py` | Loading the file and reading what the cursor is typing. |
| `sithlib/parsing.py` | Syntax-error tolerant parsing. |
| `sithlib/scopes.py` | The scope tree and its visibility rules. |
| `sithlib/builder.py` | Recording every name a module body binds. |
| `sithlib/values.py` | What a name refers to and which attributes it exposes. |
| `sithlib/inference.py` | The value an expression evaluates to. |
| `sithlib/project.py` | Resolving module names to source files or real imports. |
| `sithlib/results.py` | Prefix matching and result ordering. |
| `sithlib/engine.py` | One completion request, end to end. |

Modules that live next to the analysed file are parsed rather than imported,
so project code is never executed; installed packages fall back to a real
import.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
