# sith

A static Python code-intelligence CLI.

```
python sith.py complete <file> <line> <col> [--fuzzy]
python sith.py infer <file> <line> <col>
python sith.py goto <file> <line> <col>
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

## Layout

- `sith.py` — the tool (standard library only).
- `tests/` — spec-derived tests, one section per spec phrase.
- `AMBIGUITIES.md` — under-specified points, the reading chosen, and its risk.
- `requirements.txt` — test/lint dependencies (`python -m venv .venv && .venv/bin/pip install -r requirements.txt`).

Run the tests with `.venv/bin/python -m pytest tests`.
