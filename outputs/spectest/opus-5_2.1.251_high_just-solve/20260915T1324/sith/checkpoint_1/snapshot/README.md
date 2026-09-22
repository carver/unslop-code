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
python sith.py complete <file> <line> <col> [--fuzzy]
```

* `<line>` is 1-based, `<col>` is 0-based.
* Output is a single compact, newline-terminated JSON object on STDOUT.
* Exit code is `0` on success (even with zero completions) and `1` on error,
  with a message on STDERR.

```sh
$ python sith.py complete example.py 12 6
{"completions":[{"name":"print","complete":"rint","type":"function","description":"def print(...)"}]}
```

## What it handles

* **Name completion** — locals, enclosing function scopes, module globals and
  builtins, honouring definition order, plus Python keywords.
* **Attribute completion** — modules, classes (with in-file inheritance),
  instances (including `self.x` attributes assigned in `__init__`), and
  literals such as strings, lists, dicts, sets and tuples.
* **Prefix matching** — case-insensitive prefixes by default, case-insensitive
  subsequence matching with `--fuzzy`.
* **Broken code** — syntax errors are repaired heuristically so that code being
  edited still yields completions.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```
