# Ambiguities

Interpretation decisions taken while implementing the spec. Each entry quotes
the spec, lists the readings a conforming implementation could take, records
the choice made, and estimates the chance the spec author's own
implementation tests a different reading.

---

## T1 — `complete` text under `--fuzzy`

### Spec Text
> `complete` | string | The text that would be inserted — the name with the already-typed prefix removed. If no prefix, equals `name`. When prefix matching is case-insensitive, removal is by character count: the first `len(prefix)` characters of the matched name are stripped regardless of case.

### Alternatives
1. Strip the first `len(prefix)` characters in every mode, including fuzzy.
2. Under fuzzy matching return the whole `name` (nothing contiguous was typed, so nothing can be "removed").
3. Strip up to and including the last character the fuzzy match consumed.

### Choice
Alternative 1. The spec states the removal rule as a plain character count and
never re-states it for fuzzy mode, so the same arithmetic applies there. For
`--fuzzy` with prefix `pnt`, `print` yields `complete` of `nt`.

### Risk: 30
The author most likely also strips `len(prefix)` characters, but returning the
full `name` for fuzzy hits is a defensible alternative their editor client
might need.

---

## T2 — Whether a definition is visible on its own line

### Spec Text
> A name is visible only if it is defined **before** the cursor position in the source (for the local and global scopes). A `def` or `class` statement makes its name visible from the line of the `def`/`class` keyword. An assignment makes the name visible from the line of the assignment.

### Alternatives
1. Visible when `definition_line <= cursor_line` ("from the line of" includes that line).
2. Visible only when `definition_line < cursor_line` (strictly before the cursor).
3. Compare full `(line, col)` positions rather than lines.

### Choice
Alternative 1. "Visible **from** the line of the `def`" reads as inclusive, and
the spec describes visibility in whole lines rather than positions, so line
comparison is used throughout.

### Risk: 15
The author may compare strictly, which would hide `value` while completing on
`value = <cursor>`.

---

## T3 — `True`, `False` and `None` are both builtins and keywords

### Spec Text
> **Builtin scope** — builtin names provided by Python's `builtins` module.
> When in a name-completion context, also include Python keywords as completions.

### Alternatives
1. Emit the name once, from the builtin scope; suppress the duplicate keyword.
2. Emit both entries (one in the name groups, one in the keyword group).
3. Emit the name once, but let the keyword entry win.

### Choice
Alternative 1. Two completions with the same `name` in one response would be
a defect in an editor's popup, and the name scopes are listed first in the
spec's resolution order.

### Risk: 45
The author may simply concatenate names and keywords, producing both entries,
or classify `None` as a keyword because it cannot be rebound.

---

## T4 — Description of a name pulled in by `from X import name`

### Spec Text
> For imports: `module name`.
> For imported names (from import statements), the `type` reflects the imported object's actual kind if inferable (e.g., `function`, `class`, `module`).

### Alternatives
1. The description follows the resolved kind, exactly as the `type` does — `from os.path import join` gives type `function` and description `def join(...)`.
2. Every name bound by an import statement is described as `module <name>`, even when its type is `function` or `class`.

### Choice
Alternative 1. `type` and `description` describe the same thing in every other
row of the table, so `module name` reads as the description of a module
binding (`import os`) rather than of import statements in general.

### Risk: 35
The author may key the description off the statement rather than the resolved
object, giving `module join`.

---

## T5 — Names starting with `__` but not ending with `__`

### Spec Text
> 2. **Private names** (start with `_` but not `__`) — sorted alphabetically, case-insensitive.
> 3. **Dunder names** (start with `__` and end with `__`) — sorted alphabetically, case-insensitive.

### Alternatives
1. Treat `__mangled` as private (group 2) — the dunder test fails, so it falls back to the private group.
2. Treat it as a dunder (group 3), since it starts with `__`.
3. Give it a group of its own between private and dunder.

### Choice
Alternative 1. Checking dunder first and falling through to a plain `_` prefix
test is the natural implementation of these three bullets, and it leaves no
name ungrouped.

### Risk: 15
An implementation that tests `startswith("__")` before `endswith("__")` would
sort `__mangled` with the dunders.

---

## T6 — What "public names" of a module means

### Spec Text
> **Modules** — if `foo` is an imported module, return the module's public names. A name is public if it does not start with `_`.
> `from os import *` makes all public names from `os` visible.

### Alternatives
1. Use `dir(module)` filtered to names that do not start with `_`, for both attribute completion and star imports.
2. Honour `__all__` for star imports (as Python itself does) and use the underscore rule only for attribute completion.

### Choice
Alternative 1. The spec defines "public" once, in terms of the leading
underscore, and reuses the same word for star imports. `os` is then reported
as exporting a few names its `__all__` omits, such as `sys` and `abc`.

### Risk: 35
The author may have used `__all__` for star imports, in which case a fixture
asserting that `sys` is absent after `from os import *` would disagree.

### Resolved by the import spec
The star-import section now defines public as "the module defines `__all__`:
use exactly those names. Otherwise: all names that do not start with `_`", so
project modules honour `__all__`. See [T34](#t34--whether-__all__-governs-the-public-names-of-installed-modules)
for the part the spec still leaves open: whether the same rule applies to
modules read out of the running interpreter.

---

## T7 — Whether dunder attributes appear after a dot

### Spec Text
> **Literals** — string/list/dict/set literals expose attributes appropriate to their inferred builtin type.
> 3. **Dunder names** (start with `__` and end with `__`) — sorted alphabetically, case-insensitive.

### Alternatives
1. Return every attribute of the inferred type, dunders included — the ordering rules then have something to order.
2. Filter dunders and private names out of attribute results, as is done for modules.

### Choice
Alternative 1. The underscore filter is stated only for modules, and the
dunder ordering group would be unreachable for attribute completion if
everything underscored were dropped.

### Risk: 25
If the author filters underscores everywhere, `'text'.<cursor>` would return
roughly 47 names instead of 84.

---

## T8 — Description of a parameter

### Spec Text
> `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`, `keyword`.
> `description` | string | A short description. For functions: `def name(...)`. For classes: `class Name`. For imports: `module name`. For assignments: ... For keywords: the keyword itself.

### Alternatives
1. `param <name>`, mirroring `class Name` and `module name`.
2. The bare word `param`.
3. `statement`, reusing the fallback description.
4. `instance of <annotation>` when the parameter is annotated.

### Choice
Alternative 1. Every other kind whose description is specified is written as
the kind's keyword followed by the name, so `param given` keeps the table
self-consistent for the one kind it omits.

### Risk: 50
The description of `param` is simply not specified; the author's fixture could
equally hold `param`, `statement`, or the parameter name alone.

---

## T9 — Line count of a file that ends with a newline

### Spec Text
> If the position is out of range (line exceeds file length, or column exceeds line length), exit 1.

### Alternatives
1. Split on `\n`: `"x = 1\n"` has two lines, the second empty, so completing at line 2 column 0 succeeds. An empty file has one empty line.
2. Use `splitlines()`: `"x = 1\n"` has one line, and completing at line 2 fails; an empty file has no valid position at all.

### Choice
Alternative 1. Editors place the cursor on the empty line after a trailing
newline, and that position — the start of the next statement — is exactly
where completion is most useful.

### Risk: 30
The author may treat the position after the final newline as out of range,
and an empty file has no valid cursor position at all under that reading.

---

## T10 — Cursor below the last statement of a block

### Spec Text
> **Local scope** — names assigned or defined in the immediately enclosing function/method.

### Alternatives
1. A function body reaches past its last parsed statement, over blank or more deeply indented lines, so a cursor indented under the `def` is still local.
2. A function body ends at the last line the parser assigned to it; a cursor on the blank line after it is at module level.

### Choice
Alternative 1. The cursor is on a new, empty line for most of the time a user
is typing new code inside a function, and the spec's whole point is to return
the local names there. Indentation decides: a cursor at column 0 on that
blank line is module level.

### Risk: 15
An implementation that only compares against `end_lineno` would return no
local names on a trailing blank line.

---

## T11 — Types of loop, `with` and `except` targets

### Spec Text
> **Local scope** — names assigned or defined in the immediately enclosing function/method.
> For assignments: `instance of <type>` if the right-hand side is a literal, a constructor call, or otherwise resolvable to a known type; otherwise `statement`.

### Alternatives
1. `for`, `with` and `except ... as` bind their targets with type `statement`, since none of the listed right-hand-side forms applies.
2. Infer element types (`for item in [1, 2]` binds an `int`), context-manager return types, and exception classes.

### Choice
Alternative 1. The spec's resolvable right-hand sides are literals and
constructor calls; the element type of an iterable is neither, and inferring
it would require reasoning the spec never asks for.

### Risk: 25
`except ValueError as error` is the most likely fixture to disagree — the
exception class is written right there, so the author may report
`instance of ValueError`.

---

## T12 — Whether a method sees its class's attributes

### Spec Text
> 1. **Local scope** — names assigned or defined in the immediately enclosing function/method.
> 2. **Enclosing scopes** — names from enclosing functions (for nested functions/closures).

### Alternatives
1. Follow Python's own rule: a class body is skipped once left, so a method does not see the class's attributes as bare names. A cursor directly in a class body does see them as its local scope.
2. Treat a class body as an ordinary enclosing scope, so a method sees the class's attributes as bare names.

### Choice
Alternative 1. The spec names *functions* as the enclosing scopes, and
reporting class attributes as bare names inside a method would suggest code
that raises `NameError`.

### Risk: 25
An implementation that walks every parent scope uniformly — a natural
shortcut — would include class attributes inside methods.

---

## T13 — Which builtin names are offered

### Spec Text
> **Builtin scope** — builtin names provided by Python's `builtins` module.

### Alternatives
1. All of `dir(builtins)`, including `__import__`, `__name__` and `__debug__`.
2. Only the non-underscore names.

### Choice
Alternative 1. "Names provided by Python's `builtins` module" is the whole
module namespace, and the dunder ordering group exists to place these.

### Risk: 25
If the author filters, an empty-prefix completion at module level returns
about 11 fewer names and no dunder group.

---

## T14 — `self` inside a method

### Spec Text
> **Instances** — if `foo` is an instance (from `foo = MyClass()`), return the same attributes as the class plus any attributes assigned in `__init__` via `self.name = ...`.

### Alternatives
1. The first parameter of a method is an instance of the enclosing class, so `self.<cursor>` offers the class's members and its `__init__` attributes.
2. Only names bound by an assignment count as instances; `self` is a parameter of unknown type and completes to nothing.

### Choice
Alternative 1. `self.` is the most common attribute completion in real code,
and the spec's `self.name = ...` rule already assumes the tool knows what
`self` refers to. `cls` in a `classmethod` resolves to the class itself, and
a `staticmethod`'s first parameter stays unresolved.

### Risk: 10
Only wrong if the author deliberately returns nothing for `self.`.

---

## T15 — Resolving local project modules

### Spec Text
> Star imports resolve both installed packages and local project modules (files in the same directory).

### Alternatives
1. Parse a neighbouring `<name>.py` statically, never importing it, and apply this to `import x` and `from x import y` as well as to star imports.
2. Import local modules too (adding the directory to `sys.path`), so that runtime introspection can be used for them.
3. Resolve local modules only for star imports, leaving `import local_module` unresolved.

### Choice
Alternative 1. A completion tool must not execute the file being edited or
its neighbours, and the module rules elsewhere in the spec ("if `foo` is an
imported module, return the module's public names") are written without regard
to where the module came from.

### Risk: 20
Static parsing reports a local module's names with the kinds the source
implies; an importing implementation could report a few extra names that only
exist at runtime.

### Resolved by the import spec
Confirmed and widened: modules are now searched from the project root rather
than from the file's own directory, and the search order puts project files
ahead of the standard library.

---

## T16 — Attribute completion on a receiver that cannot be resolved

### Spec Text
> When the cursor follows a `.`, return attributes of the value before the dot.
> On success, exit **0** (even with zero completions).

### Alternatives
1. Return an empty completion list and exit 0.
2. Fall back to name completion when the receiver is unknown.
3. Treat it as an error and exit 1.

### Choice
Alternative 1. An unknown receiver has no attributes; the spec explicitly
anticipates a successful response with zero completions, and errors are
reserved for bad files and bad positions.

### Risk: 5

---

## T17 — A name bound more than once

### Spec Text
> An assignment makes the name visible from the line of the assignment.

### Alternatives
1. Use the last binding at or before the cursor, so the reported type follows the most recent assignment.
2. Use the first binding in the scope.

### Choice
Alternative 1. Later assignments rebind the name, so the nearest preceding
binding is the one the cursor can see.

### Risk: 10

---

## T18 — Inherited `__init__` attributes on an instance

### Spec Text
> **Instances** — ... return the same attributes as the class plus any attributes assigned in `__init__` via `self.name = ...`.
> (including inherited ones from base classes defined in the same file)

### Alternatives
1. Collect `self.name = ...` from the `__init__` of the class and of its same-file bases, matching the inheritance rule stated for class attributes.
2. Collect only from the class's own `__init__`.

### Choice
Alternative 1. Inheritance is explicitly in scope for class members, and an
instance of a subclass really does carry the attributes its base's `__init__`
sets.

### Risk: 15
The parenthetical about inheritance is attached to the class bullet, so the
author may have applied it only there.

---

## T19 — Description of an assignment binding returned by `goto`

### Spec Text
> `description` | string | Short description. For functions: `def name(params)`. For classes: `class Name`. For instances: `instance of <ClassName>`. For assignments: the right-hand expression or statement. For imports: the import statement text.

### Alternatives
1. The right-hand side only: `calc = Calculator()` is described as `Calculator()`.
2. The whole assignment statement: `calc = Calculator()`.
3. The source line verbatim, including indentation.

### Choice
Alternative 1. The row says "the right-hand expression", which names one side
of the assignment; the trailing "or statement" then covers bindings that have
no right-hand expression (`for`, `with`, `except ... as`), which are described
by their statement header instead.

### Risk: 45
The author most likely emits the whole statement text (`calc = Calculator()`),
which is what a jedi-style `get_code()` of the assignment node produces.

---

## T20 — `type` of an assignment binding returned by `goto`

### Spec Text
> `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`.
> - `goto` returns where the name at the cursor is assigned or defined (`def`, `class`, assignment, or import binding).

### Alternatives
1. The type of the value the binding holds, exactly as `complete` reports it: `calc = Calculator()` is an `instance`.
2. Always `statement` for an assignment, reserving the value types for `infer`.

### Choice
Alternative 1. This tool already types assignment bindings by their inferred
value for completion, and the spec reuses one type vocabulary across all three
subcommands. `statement` remains reachable for bindings whose value is
unknown (`x = unknown()`), and for `for`/`with`/`except` targets.

### Risk: 45
The author may report `statement` for every assignment target, keeping
`instance` exclusively for `infer` results.

---

## T21 — Cursor on a literal rather than an identifier

### Spec Text
> If the cursor is not on a name, exit 1.
> ### Literals
> For literals, `infer` returns a definition pointing to the builtin type with `module_path` set to empty string and `line`/`column` set to 0.

### Alternatives
1. Only identifiers count as names: `infer` with the cursor inside `"hello"` or on `42` exits 1. The literal rule is reached through a name bound to a literal (`x = "hello"`, cursor on `x`).
2. A literal under the cursor is inferable: `infer` returns `str`, while `goto` — which needs a binding — exits 1.
3. Both commands accept literals.

### Choice
Alternative 1. Both subcommands state the same precondition in the same words,
which reads as one shared "find the name at the cursor" step; a literal has no
name to look up, and the Literals rule is about what a name evaluates to.

### Risk: 25
If the author's implementation infers whatever expression sits under the
cursor, `infer` on `42` returns `builtins.int` instead of exiting 1.

---

## T22 — The builtin definition for `None`

### Spec Text
> For builtin types (including None, int, str, etc.), definitions use type "instance" and full_name "builtins.<name>" with module_path set to empty string and line/column set to 0.
> If a function has no `return` statement or only bare `return`, the return type is `None`.

### Alternatives
1. `name` is `None` and `full_name` is `builtins.None`, taking the spec's own spelling of the type.
2. `name` is `NoneType` and `full_name` is `builtins.NoneType`, naming the class of the value.
3. `full_name` is the bare `None`, since neither spelling exists in `builtins`.

### Choice
Alternative 1. The spec lists `None` among the builtin types by that name and
gives one formula for their `full_name`, so `None` is substituted into it even
though `builtins.None` is not an importable path.

### Risk: 30
An implementation that formats `type(value).__name__` reports `NoneType`.

---

## T23 — `docstring` of a builtin definition

### Spec Text
> `docstring` | string | The docstring of the definition, or empty string if none.
> For builtin types ... `module_path` set to empty string and `line`/`column` set to 0.

### Alternatives
1. Report the real docstring of the builtin type (`int.__doc__`, a paragraph of text).
2. Report an empty string, treating a builtin definition as a synthesised record with no source.

### Choice
Alternative 1. The `docstring` field is defined once for every definition, and
the builtin carve-out names exactly three fields it overrides; `docstring` is
not one of them.

### Risk: 35
If the author builds builtin definitions as fixed records, every field except
the name is blank or zero and `docstring` is `""`.

---

## T24 — `module_path` for definitions outside the project root

### Spec Text
> `module_path` | string | File path where the name is defined, relative to the project root. When `--project` is not available, the project root is the directory containing `<file>`.

### Alternatives
1. Paths under the root are relative (`helper.py`, `pkg/helper.py`); anything else — the standard library, site-packages — is reported as its absolute path, and objects with no source file (C builtins) as `""`.
2. Relativise everything, emitting `../../usr/lib/python3.12/posixpath.py` for standard library files.
3. Report the absolute path for every definition.

### Choice
Alternative 1. "Relative to the project root" only has meaning inside the
root; a chain of `..` segments is not a path anyone would display, and the
spec already uses `""` for definitions with no file.

### Risk: 30
The author's fixtures almost certainly live in the project root, where all
three readings agree; a fixture that inspects `os.getcwd` would disagree.
The path convention section now settles the separator: every emitted path is
written with forward slashes.
`full_name` follows the same split: a file under the root contributes its
dotted path without `.py` (`pkg.helper.Thing`), matching "the filename without
`.py`" for the flat case the spec describes.

---

## T25 — Which bindings a name still has after a branch

### Spec Text
> Multiple definitions are returned when a name could resolve to more than one thing (e.g., conditional assignments).
> For unresolved branches, return all reachable possibilities.

### Alternatives
1. Walk the bindings before the cursor backwards, keeping every conditional one and stopping at the first unconditional binding (inclusive). `x = 1` then `if c: x = "s"` yields both; `x = 1` then `x = "s"` yields only `str`.
2. Return every binding of the name before the cursor, conditional or not.
3. Return only the last binding, and treat `if`/`else` branches as a special case.

### Choice
Alternative 1. An unconditional assignment definitely overwrites what came
before it, so anything earlier is unreachable; a conditional one may not have
run, so the previous binding survives alongside it. This keeps the
"most recent binding wins" rule of the completion spec intact.

### Risk: 30
An implementation that simply collects every `if`/`else` branch target would
agree on the branch fixtures and disagree on `x = 1` followed by
`if c: x = "s"`, where it might return only `str`.

---

## T26 — What the empty `is None` section requires

### Spec Text
> ### `is None`
>
> (no body)

### Alternatives
1. Mirror the `isinstance` rule: inside `if x is None:` the name is `None`, and inside the `else` branch (or inside `if x is not None:`) the `None` possibility is removed from the name's possible types.
2. Narrow only the positive branch of `x is None`.
3. Do nothing — the section has no content to implement.

### Choice
Alternative 1. The heading sits under "Flow-Sensitive Type Narrowing" beside
`isinstance`, and the only narrowing an `is None` test can express is
"`None` here, not `None` there".

### Risk: 40
The section is empty, so any fixture the author wrote for it is a guess at
their own intent; the likeliest single test is the positive branch of
`if x is None:` alone.

---

## T27 — Rendering of `params` in a function description

### Spec Text
> For functions: `def name(params)`.

### Alternatives
1. Unparse the parameter list from the syntax tree: `def greet(name, greeting='hi')`.
2. Copy the source text between the parentheses verbatim, preserving the author's quotes and line breaks.
3. Emit the parameter names only, dropping defaults and annotations.

### Choice
Alternative 1. Unparsing is stable for signatures that wrap over several
lines, and keeps the description a single line as "short description"
requires.

### Risk: 25
A signature written as `def greet(name, greeting="hi")` is reported with
single quotes; an implementation that slices the source text keeps the double
quotes the author typed.

---

## T28 — Whether `goto` follows an import

### Spec Text
> - `goto` returns where the name at the cursor is assigned or defined (`def`, `class`, assignment, or import binding).
> - `infer` returns what the name at the cursor evaluates to after static propagation through assignments and calls.

### Alternatives
1. `goto` stops at the import binding in the file under the cursor; `infer` follows through to the class or function in the imported module.
2. Both follow the import to the original definition.

### Choice
Alternative 1. "Import binding" is listed as one of the places `goto`
answers with, which only distinguishes it from the imported definition itself.

### Risk: 15
An implementation that always resolves to the original definition would report
the imported module's file for `goto` as well.

### Resolved by the import spec
Confirmed: "Without `--follow-imports` (default), `goto` on an imported name
returns the `import` statement itself". The other reading is now reachable
through the new `--follow-imports` flag.

---

## T29 — `line` and `column` of a module definition

### Spec Text
> `line` | int | 1-based line number of the definition.
> `column` | int | 0-based column of the name identifier in the definition.

### Alternatives
1. A module is not defined at a position, so `line` and `column` are `0`, as they are for builtins.
2. A module starts at line 1, column 0.

### Choice
Alternative 1. Zero is the value the spec already uses for definitions that
have no position inside a file, and line 1 would point at whatever statement
happens to be first.

### Risk: 35
`line: 1` is an equally natural choice for a file-level definition.

---

## T30 — Description of an import binding whose target is a class or function

### Spec Text
> For imports: the import statement text.
> For imported names (from import statements), the `type` reflects the imported object's actual kind if inferable. *(completion spec, recorded as T4)*

### Alternatives
1. Any binding introduced by an `import`/`from ... import` statement is described by that statement's text, whatever kind the imported object turns out to be.
2. Only module bindings are described that way; an imported class keeps `class Thing`.

### Choice
Alternative 1. `goto` answers with the import binding itself, and the
statement text is what is written at that location. The `type` field still
reports the resolved kind, as T4 decided for completions.

### Risk: 30
The author may describe every definition purely from its `type`, giving
`class Thing` for `from helper import Thing`.

---

## T31 — Whether narrowing applies to `goto`

### Spec Text
> This narrowing applies to both `infer` (returns the narrowed type) and `complete` (shows attributes of the narrowed type for attribute completion).

### Alternatives
1. `goto` is unaffected: it still answers with the assignment or parameter that binds the name.
2. `goto` answers with the class named in the `isinstance` test.

### Choice
Alternative 1. The sentence lists the two subcommands narrowing applies to
and omits `goto`, whose answer is a binding site rather than a type.

### Risk: 10

---

## T32 — Return statements whose value cannot be resolved

### Spec Text
> Infer a function's return type by analyzing its `return` statements.
> If a function has multiple return paths with different types, return all possible types.

### Alternatives
1. Unresolvable returns contribute nothing: `return other(x)` where `other` is unknown drops out, and a function all of whose returns are unresolvable infers to nothing (empty array).
2. An unresolvable return makes the whole call unresolvable.
3. An unresolvable return contributes `None`.

### Choice
Alternative 1. "All possible types" is a union of what could be determined,
and the spec reserves `None` for functions that never return a value.

### Risk: 20
Returning the empty array for a function with one known and one unknown return
is the main place a stricter implementation would differ.

---

## T33 — Whether third-party modules resolve

### Spec Text
> **Module search order:**
> 1. Project root — scan for `.py` files and packages (directories containing `__init__.py`).
> 2. Standard library — recognize stdlib modules available in the target runtime.
> 3. If a module cannot be found, treat it as unresolvable

### Alternatives
1. Only project files and the standard library resolve; an installed third-party package is unresolvable, as the parenthetical "(e.g., third-party or stdlib)" of the `goto` section implies.
2. Anything the interpreter can import resolves, which quietly adds every installed distribution to step 2.

### Choice
Alternative 1. The search order lists exactly two places to look, and a module
is recognised as stdlib by `sys.stdlib_module_names`. This also keeps the tool
from importing packages that happen to sit next to the project.

### Risk: 25
The author most likely calls `importlib` without checking `sys.stdlib_module_names`,
in which case `import pytest` would offer that package's attributes rather
than nothing.

---

## T34 — Whether `__all__` governs the public names of installed modules

### Spec Text
> Makes all public names from `foo` visible in the importing module. A name is public if:
> - The module defines `__all__`: use exactly those names.
> - Otherwise: all names that do not start with `_`.

### Alternatives
1. Apply the `__all__` rule to project files only; a module read out of the running interpreter keeps the earlier definition of public (no leading underscore).
2. Apply the `__all__` rule everywhere, so `from os import *` exposes `os.__all__` — which contains `_exit` and omits `sys`.

### Choice
Alternative 1. `__all__` is read from the source of a project module, which is
the only kind of module the import section is written about; the earlier spec's
underscore rule for runtime modules is left standing. `from os import *` keeps
hiding `_exit`.

### Risk: 40
The author may read `__all__` off the imported module object as well, which
would make `_exit` visible and `sys` invisible after `from os import *`.

---

## T35 — `--follow-imports` on a module binding

### Spec Text
> With `--follow-imports`, `goto` follows the import chain and returns the actual definition in the source module

### Alternatives
1. `import helper` binds a module, so following it answers with the module itself (`helper.py`, line 0, column 0).
2. A module binding has no "definition in the source module", so the import statement stands as the answer.

### Choice
Alternative 1. The flag is described as following the chain to what the name
refers to, and a module is a definable thing elsewhere in the tool — `infer`
already reports module records with line and column zero.

### Risk: 30
The author may only follow `from X import name` bindings, leaving plain
`import X` at its import statement.

---

## T36 — Completing a module path outside the two listed forms

### Spec Text
> - `import |` suggests top-level module/package names.
> - `from X import |` suggests names inside module `X`.
> - `from X.Y import |` suggests names inside submodule `X.Y`.

### Alternatives
1. Also complete the module path itself where one is being typed: `from |` and `import pkg.|` offer module names (top-level and, after a dot, submodules of the package already typed).
2. Offer module names only immediately after `import`, and nothing at all after `from` or after a dot in a module path.

### Choice
Alternative 1. The three bullets describe the cursor positions the spec cares
about rather than forbidding the others, and a module path is the only thing
that can be typed at those positions.

### Risk: 15
The author may return nothing after a bare `from`; an extra suggestion list
there is only wrong if a fixture asserts emptiness.

---

## T37 — Whether a package's submodules are "names inside" it

### Spec Text
> - `from X import |` suggests names inside module `X`.
> - In `from X import ...` completion, exported names come from `__all__` when it exists; otherwise use names that do not start with `_`.

### Alternatives
1. A package offers the names bound in its `__init__.py` **and** the modules it contains, since `from pkg import inner` is a legal import of a submodule.
2. Only the names bound in `__init__.py` count, as those are the only ones the module body defines.

### Choice
Alternative 1. `from X import Y` resolves a submodule `Y` in Python whether or
not `__init__.py` mentions it, so a completion list that omits submodules
would not offer imports that work. `__all__`, when present, still wins.

### Risk: 30
The author may list only the bindings of `__init__.py`, which would differ for
a package whose `__init__.py` does not import its submodules.

---

## T38 — A relative import whose base is the project root

### Spec Text
> If the relative import goes above the project root, it is unresolvable.

### Alternatives
1. The project root behaves as a package: from `pkg/mod.py`, `from .. import other` resolves `other.py` at the root, and only a further level is "above" it.
2. Only levels inside a real package resolve, so `..` from a module one directory below the root fails as it would at runtime.

### Choice
Alternative 1. The spec gives the root, not the top-level package, as the
boundary, which only means something if the root itself can be the base of a
relative import.

### Risk: 20
An implementation that mirrors CPython's rules would reject `..` from a module
directly inside the root.

---

## T39 — `__all__` entries the module does not define

### Spec Text
> - The module defines `__all__`: use exactly those names.

### Alternatives
1. Offer every listed name, using the module's binding for it when there is one and an unresolved entry otherwise.
2. Offer only the listed names the module actually binds.

### Choice
Alternative 1. "Exactly those names" reads as the list itself; a name in
`__all__` is what the module claims to export even when the binding is made
somewhere the tool cannot see.

### Risk: 35
The author may intersect `__all__` with the bindings they found, which would
drop entries the module never defines.

---

## T40 — Empty results for an unresolvable module versus the import binding

### Spec Text
> 3. If a module cannot be found, treat it as unresolvable — `infer` and `goto` return empty results, completions return nothing for that module's attributes.
> Without `--follow-imports` (default), `goto` on an imported name returns the `import` statement itself

### Alternatives
1. "Empty results" covers the names reached *through* the missing module (its attributes, and the names imported from it are unresolved values); the binding the import statement makes in this file is still a place `goto` can answer with.
2. `goto` on a name bound by an unresolvable import returns nothing at all.

### Choice
Alternative 1. The default `goto` rule is stated without exception, and the
fallback rule for `--follow-imports` ("return the import statement as a
fallback") shows the import site is a valid answer for a module that cannot be
found.

### Risk: 20
The author may return `{"definitions": []}` for `goto` on the name bound by
`import no_such_module`.

---

## T41 — Which import site is the `--follow-imports` fallback

### Spec Text
> With `--follow-imports`, if the terminal target cannot be resolved, return the import site in the current file as the fallback definition.

### Alternatives
1. The import statement in the file under the cursor, however many hops were walked before the chain broke.
2. The last import statement reached — the hop in another module where the chain actually broke.

### Choice
Alternative 1, which the clarification states outright: "the import site in the
current file".

### Risk: 10
Following a broken chain back to its last hop is the more informative answer
and an implementation could report it instead.

---

## T42 — Which directories are namespace packages

### Spec Text
> The same import rules apply to regular packages and namespace packages.

### Alternatives
1. Any directory under the root whose name is an identifier is importable, except caches and hidden directories (`__pycache__`, names starting with `.`).
2. Every directory at all, cache directories included.
3. Only directories that contain at least one `.py` file somewhere inside them.

### Choice
Alternative 1. A namespace package is any directory a dotted name can reach,
but `__pycache__` and dot-directories are never written in an import statement
and would only pollute `import |` completions.

### Risk: 10

---

## T43 — How a package is reported as a definition

### Spec Text
> - Where to search for modules when resolving imports.
> - The base for computing module qualified names.

### Alternatives
1. A package is reported at its `__init__.py` (`module_path` = `pkg/__init__.py`) with `full_name` = `pkg`; a namespace package, having no file, is reported at its directory.
2. Report `module_path` as the directory `pkg` for both.
3. Keep `__init__` in the qualified name (`pkg.__init__`).

### Choice
Alternative 1. `module_path` is documented as the file a name is defined in,
and the file of a regular package is its `__init__.py`; the dotted name of that
file as a module is `pkg`, which is what any import writes.

### Risk: 20
The author may report the package directory as `module_path`.

---

## T44 — Following an import into the standard library

### Spec Text
> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib), return the import statement as a fallback.

### Alternatives
1. `--follow-imports` only ever lands in a project file; a chain ending in the standard library falls back to the import statement even though the interpreter could point at `os.py`.
2. Follow into the standard library's own source, since `inspect` can find it.

### Choice
Alternative 1, which the sentence names explicitly. `infer` still reports the
runtime definition of such a name; only `--follow-imports` falls back.

### Risk: 8
