# sith

A static Python code-intelligence CLI.

```
python sith.py complete <file> <line> <col> [--fuzzy]
```

Prints a compact, newline-terminated JSON object with a `completions` array to STDOUT
and exits 0; on file/position errors it prints a message to STDERR and exits 1.
Syntax errors in the analysed file are repaired line by line instead of failing.

## Layout

- `sith.py` — the tool (standard library only).
- `tests/` — spec-derived tests, one section per spec phrase.
- `AMBIGUITIES.md` — under-specified points, the reading chosen, and its risk.
- `requirements.txt` — test/lint dependencies (`python -m venv venv && venv/bin/pip install -r requirements.txt`).

Run the tests with `venv/bin/python -m pytest tests`.
