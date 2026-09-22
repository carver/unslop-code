# sith

A static Python code-intelligence CLI.

```
python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
python sith.py infer <file> <line> <col> [--project <dir>]
python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
```

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
