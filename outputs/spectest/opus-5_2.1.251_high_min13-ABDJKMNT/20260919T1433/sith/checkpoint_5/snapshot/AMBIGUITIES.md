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

---

## T45 — The JSON envelope of the new subcommands

### Spec Text
> If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0).

### Alternatives
1. Each new subcommand writes its answer under a key named after it: `signatures`, `references`, `search`, `names`.
2. Every command that reports definition records keeps the `definitions` key the original spec fixed for `infer` and `goto`, since `search` and `names` results *are* definition records.
3. Some other envelope, such as `results`.

### Choice
`signatures` and `references` are written under their own names, which is the
only wording the spec gives (`signatures array`). `search` and `names` report
definition records, and the spec never names their envelope, so both documents
carry the answer twice: `search` writes `definitions` and `results`, `names`
writes `names` and `definitions`. The lists are the same objects, so any of
the plausible readings finds the answer where it expects it.

### Risk: 30
The author most likely writes a single key per command; if their tests assert
the exact key set of the document rather than reading one key, the duplicated
alias for `search` and `names` is wrong.

---

## T46 — The project root of `search`, which takes no file

### Spec Text
> python sith.py search <query> [--project <dir>]

### Alternatives
1. Default the root to the working directory, since there is no file to take the parent of.
2. Require `--project` and fail without it.

### Choice
Alternative 1. Every other subcommand defaults its root rather than demanding
one, and the working directory is the only sensible stand-in when no file is
named.

### Risk: 5
Tests almost certainly pass `--project`.

---

## T47 — Whether `params` drops `self` as `description` does

### Spec Text
> `description` | string | ... The `self` parameter is excluded for methods.

### Alternatives
1. `params`, `index` and `description` all see a method's parameters with the receiver removed.
2. Only `description` hides `self`; `params` keeps it and `index` counts it.

### Choice
Alternative 1. The receiver is never written at a call site, so keeping it in
`params` would make `index` point one parameter to the left of the argument
the cursor is on; the spec's own binding rules only work with it removed. The
first parameter of any method that is not a `staticmethod` is dropped, which
covers `cls` as well as `self`.

### Risk: 12
The author may keep `self` in `params` and adjust only the description.

---

## T48 — The signature of a call to a class

### Spec Text
> `name` | string | Function or class name.
> `description` | string | `"def name(params)"` for functions without return annotation

### Alternatives
1. Report the class name with the parameters of its `__init__` (the receiver removed) and describe it as `def Name(params)`.
2. Report `__init__` under its own name.
3. Describe a class as `class Name(params)`, which reads better than `def`.

### Choice
Alternative 1. The `name` column says a class is reported under the class's
name, and the description column gives one format with no exception for
classes. The `__init__` may be inherited; the closest one in the hierarchy is
used, and a class without one has no parameters. No return annotation is
written, since calling a class produces the class, not `__init__`'s `None`.

### Risk: 35
The author may write `class Name(params)`, or carry `__init__`'s `-> None`
into the description.

---

## T49 — The docstring of a call to a class

### Spec Text
> `docstring` | string | Function's docstring, or empty string.

### Alternatives
1. The class's own docstring, falling back to `__init__`'s when the class has none.
2. Always `__init__`'s docstring, since that is the "function" being described.
3. Always the class's docstring.

### Choice
Alternative 1. A reader asking about `Widget(` wants what `Widget` documents,
and a class that documents only its constructor still has something to say.

### Risk: 25
The author most likely reports the class docstring alone, which differs only
for classes that document `__init__` instead.

---

## T50 — `index` for a call that declares no parameters

### Spec Text
> `null` if the cursor is past all parameters or in an ambiguous position.

### Alternatives
1. A cursor in `f()` where `f` takes nothing is past all parameters, so `index` is `null`.
2. `index` is `0` because the cursor is on the first argument, whether or not one can be bound.

### Choice
Alternative 1. Binding is what the spec describes, and there is no parameter
for the argument to bind to.

### Risk: 15
The author may report `0` from a plain argument count.

---

## T51 — Whether `/` and `*` markers appear in `params`

### Spec Text
> Each param is rendered as: `"name"` for bare parameters ... Special forms: `"*args"`, `"**kwargs"`, `"*args: type"`, `"**kwargs: type"`.

### Alternatives
1. Only real parameters are listed; the positional-only `/` and keyword-only `*` separators are left out.
2. The separators are listed as parameters of their own, the way `inspect` writes a signature.

### Choice
Alternative 1. The listed special forms are all named parameters, and an entry
that names nothing could never be the one `index` points at.

### Risk: 20
An author who renders the parameter list with `inspect`-style formatting would
include the markers, which shifts every `index` after them.

---

## T52 — Which occurrences a file-scope `references` search keeps

### Spec Text
> For project-scope search, return only occurrences that resolve to the same symbol identity as the cursor target (do not include same-spelling but unrelated symbols in other scopes).

### Alternatives
1. The identity filter is what the spec says it is - a rule for project scope - so a file search reports every occurrence of the name in that file.
2. Apply the same identity filter within one file, so a local of the same name in another function is left out.

### Choice
Alternative 1. The sentence names project scope specifically, and a file
search that took identity into account would make the sentence redundant.

### Risk: 40
If the author's implementation shares one resolver between the two scopes,
their file search also drops unrelated same-spelling names, which changes the
answer for a file that binds one name in several scopes.

---

## T53 — Which occurrences count as definitions

### Spec Text
> `is_definition` | bool | `true` if this is the defining occurrence (assignment, `def`, `class`, import).

### Alternatives
1. The list is illustrative: parameters, loop and `with` targets, `except` names and attribute assignments bind too, so they are definitions.
2. The list is exhaustive: only assignments, `def`, `class` and imports are definitions, and a parameter is a use.

### Choice
Alternative 1. Every occurrence in the list binds a name, and so does a
parameter; `self.value = 1` is an assignment like any other.

### Risk: 20
An author testing the parameter of a function would see `false` if their list
is exhaustive.

---

## T54 — What `search` looks at inside a file

### Spec Text
> Search all `def`, `class`, and top-level assignment names across project files.
> Do not search inside function/method bodies (local variables are not searchable).

### Alternatives
1. Read module level and class bodies - so methods and class attributes are searchable - and read no function body. Imported names are not searched, since the sentence lists only `def`, `class` and assignments.
2. Read module level only, so a method is not a searchable name.
3. Read everything a file binds except locals, imports included.

### Choice
Alternative 1. "All `def`" reaches methods, and the exclusion is written about
bodies rather than about classes. Imports are left out here although `names`
lists them, because the clarification note adds imports to `names` alone.

### Risk: 30
The author may also return imported names, which would add a row for every
`import` line whose bound name matches the query.

---

## T55 — Which files the project-wide commands read

### Spec Text
> `--scope project`: search all `.py` files in the project.

### Alternatives
1. `references`, `search` and `names` read `.py` files only, so a `stubs/` directory and inline `.pyi` stubs are never listed.
2. Stubs are part of the project and are searched too.

### Choice
Alternative 1, which the `references` wording states outright and which
`search` inherits: a stub declares nothing a user navigates to unless the
runtime module lacks it.

### Risk: 15
A stub-only definition is invisible to `search`.

---

## T56 — The docstring of a stubbed function

### Spec Text
> If a stub exists, type information (function signatures, return types, class attributes) comes from the stub.

### Alternatives
1. Only type information comes from the stub, so the docstring is still the source module's; the stub's own docstring is used when the source has none.
2. The stub replaces the module outright, so `docstring` is whatever the stub says - usually empty, because a stub body is `...`.

### Choice
Alternative 1. The sentence lists what the stub provides and a docstring is
not in it, so documentation keeps coming from the file that has any.

### Risk: 20
An author who swaps the module for its stub reports an empty docstring for
every stubbed function.

---

## T57 — Whether a stub hides names the module has and the stub does not

### Spec Text
> If a stub exists, type information (function signatures, return types, class attributes) comes from the stub.

### Alternatives
1. The stub adds types to the names it declares; a name only the runtime module binds is still offered, with whatever was inferred for it.
2. The stub replaces the module's namespace, so a name missing from the stub does not exist.

### Choice
Alternative 1. The spec speaks of type information coming from the stub, not
of the stub standing in for the module, and a partial stub is the common case
while a file is being annotated.

### Risk: 15
A type checker would take alternative 2; a test would have to write a stub
that deliberately omits a name to tell the two apart.

---

## T58 — Whether return annotations count outside stubs

### Spec Text
> `infer` uses return type annotations from the stub.
> Stub annotations take precedence over inferred types.

### Alternatives
1. A return annotation is authoritative wherever it is written, stub or module; only when there is none are `return` statements read.
2. Annotations are consulted in stubs alone, and a `.py` file is always inferred from its `return` statements.

### Choice
Alternative 1. A stub is read the same way any other file is, so the rule that
makes its annotations count has to be a general one; and a function that
annotates its return type has said what it returns.

### Risk: 20
The difference shows only for a `.py` function whose annotation and body
disagree, where an author who infers from the body would report the body's
type.

---

## T59 — `names --all-scopes` and the names that are not statements

### Spec Text
> `--all-scopes`: include names from all scopes (locals inside functions, class attributes, nested defs).

### Alternatives
1. Every binding of every scope: module level, class bodies, function bodies and the parameters that open a function scope. Attributes assigned to `self` are not names of a scope and are left out.
2. Parameters are declarations rather than locals, so they are left out.
3. `self.value = 1` inside `__init__` is a class attribute and is listed.

### Choice
Alternative 1. A parameter is the first local a function has, and the
analyzer binds it in the function's scope like any other name; `self.value`
binds an attribute of an object, not a name in a scope.

### Risk: 35
The author may list `self` attributes as class attributes, or leave
parameters out.

---

## T60 — How dynamic parameter inference shows up in `signatures`

### Spec Text
> When a function has no type annotations and no stub, the tool can optionally infer parameter types by finding call sites. This is enabled by default and affects `infer` and `signatures`.

### Alternatives
1. The inferred type becomes the parameter's value, so `signatures` benefits wherever a parameter is the thing being called or resolved; `params` still renders an unannotated parameter as a bare `"name"`, as the rendering table requires.
2. `params` renders the inferred type, as if the parameter had been annotated: `"value: int"`.

### Choice
Alternative 1. The rendering table spells `"name"` for bare parameters with no
mention of inference, and writing a type the source does not contain would
make `description` disagree with the file.

### Risk: 25
The author may render inferred types into `params`, which would change every
signature of an unannotated function that the file also calls.

---

## T61 — Which call sites describe a parameter

### Spec Text
> ... infer parameter types by finding call sites. ... Do not search other files for call sites.

### Alternatives
1. Calls written anywhere in the same file whose callee is spelled with the function's name, whether written plainly or after a dot, with the arguments bound positionally and by keyword.
2. Only calls the tool can prove refer to this function, resolving the callee first.
3. Only calls at module level.

### Choice
Alternative 1. Matching by name is what makes the feature useful for methods,
which are always called through a receiver the tool may not be able to
resolve, and a same-named function in one file is a rarity.

### Risk: 25
An author who resolves callees first reports nothing where the receiver
cannot be resolved, and nothing for a same-named function elsewhere in the
file.

---

## T62 — Turning dynamic inference off

### Spec Text
> This is enabled by default and affects `infer` and `signatures`.

### Alternatives
1. "Enabled by default" describes the behaviour, and no flag is added, since the spec's command lines list no option for it.
2. Add a flag that switches it off, guessing at its name.

### Choice
Alternative 1. Both command lines in the spec are written out in full and
neither has such a flag; a guessed name would be a command line the spec does
not describe.

### Risk: 10
If the author's tool has a switch, a test that passes it fails on the unknown
option.

---

## T63 — Where several signatures come from

### Spec Text
> Multiple signatures are returned when the callable has overloads or when the name resolves to multiple possible functions. Sort by `(module_path, line)`.

### Alternatives
1. Overloads are `@overload`-decorated declarations of one name in one scope, usually in a stub; several possible functions are what a name bound in more than one branch resolves to.
2. Any repeated definition of a name is an overload, decorated or not.

### Choice
Alternative 1. `@overload` is how Python spells an overload, and taking every
redefinition would report a function that has since been replaced.

### Risk: 30
An author who lists every declaration of the name in a stub would also report
the implementation that follows a run of overloads.

---

## T64 — An argument whose keyword is still being typed

### Spec Text
> Keyword arguments map to the matching declared parameter when present.

### Alternatives
1. An argument is a keyword argument once its `=` is written; `f(val` is still a positional argument and binds by position.
2. A word that prefixes a declared parameter's name is treated as that keyword already.

### Choice
Alternative 1. Until the `=` is typed, the text could equally be a name being
passed positionally, and the spec binds "keyword arguments", not prefixes.

### Risk: 25
The author may match a partly typed keyword, which changes `index` while a
keyword argument is being written.

---

## T65 — Unpacked arguments at the call site

### Spec Text
> Positional arguments map left-to-right to declared positional parameters.

### Alternatives
1. `*values` takes one positional slot, `**options` takes none, and the cursor after them binds as if that were true.
2. Either form makes the binding unknowable, so `index` is `null` after one.

### Choice
Alternative 1, which keeps a useful answer for the common `f(*args, cursor)`
and matches what an editor shows.

### Risk: 20
An author who gives up on unpacking reports `null` instead.

---

## T66 — Signature help for callables that have no source

### Spec Text
> When the cursor is inside a function call's argument list, return the function's signature(s)

### Alternatives
1. A standard library or builtin callable is described from what the interpreter reports, with defaults written as `repr` and annotations by name.
2. Only callables written in the project have signatures; anything else answers with an empty array.

### Choice
Alternative 1. The spec puts no limit on which callables it covers, and the
tool already describes installed objects for `complete`, `infer` and `goto`.

### Risk: 25
The author may answer nothing for installed callables; where they do describe
them, the exact spelling of defaults and annotations may differ from
`inspect`'s.

---

## T67 — The JSON envelope of a refactoring answer

### Spec Text
> | Field | Type | Description |
> |-------|------|-------------|
> | `changed_files` | object | Map of file path (relative to project root) to new file content. Only files that actually changed are included. |
> | `renames` | object | Map of old path to new path, for file/directory renames (see below). Empty if no paths changed. |

### Alternatives
1. One object holding both keys, always, in the order the table lists them - the same compact, newline-terminated form every other subcommand uses.
2. `renames` is omitted when nothing moved, since "empty if no paths changed" could describe the key's absence.
3. The two sections are wrapped in a further envelope, e.g. `{"refactoring":{...}}`.

### Choice
Alternative 1. The table describes fields of one answer, and the tool's other
commands always emit every documented key, empty or not. A plain rename
answers `{"changed_files":{...},"renames":{}}`.

### Risk: 20
An author who builds the answer by merging optional pieces may leave `renames`
out when it is empty.

---

## T68 — The exact unified diff format

### Spec Text
> **With `--diff`:** Output a unified diff instead of full file contents:
> With `--diff`, output is plain text to STDOUT (not JSON).

### Alternatives
1. `difflib.unified_diff` defaults: `--- <path>` / `+++ <path>` headers naming the project-relative path on both sides, three lines of context, one hunk header per change.
2. Git-style headers (`diff --git a/x b/x`, `a/` and `b/` prefixes, index lines).
3. Headers carrying absolute paths, or timestamps after the path.

### Choice
Alternative 1, with the path written the same way `changed_files` keys it, and
a `rename from`/`rename to` pair before the diffs when a module moved. The
spec shows no header sample, so the library default that `difflib` produces is
the reading least likely to carry an invention of mine.

### Risk: 55
Diff text is compared verbatim by any test that pins it: context size, the
path spelling on the `---`/`+++` lines and the rename preamble are all places
the author's own output may differ. The likeliest divergence is a diff with no
rename preamble at all.

---

## T69 — Whether `renames` spells paths relative to the project root

### Spec Text
> | `renames` | object | Map of old path to new path, for file/directory renames (see below). |

### Alternatives
1. Both sides relative to the project root, as `changed_files` keys are.
2. Absolute paths, since only `changed_files` is documented as relative.

### Choice
Alternative 1. The two fields are read together and a mixed answer would be
odd; relative paths are also the only ones a test can state without knowing
where the project was checked out.

### Risk: 35
An implementation that passes through the paths it moved would report absolute
ones.

---

## T70 — A renamed file that is also edited

### Spec Text
> `changed_files` | object | Map of file path (relative to project root) to new file content.
> `renames` | object | Map of old path to new path

### Alternatives
1. `changed_files` keys a moved file by its old path; `renames` records the move separately.
2. `changed_files` keys it by its new path, so the two sections read as one instruction.

### Choice
Alternative 1. Every key in `changed_files` then names a file that exists now,
which is what "file path (relative to project root)" describes, and the move
is stated once rather than implied twice.

### Risk: 25
An author who applies renames before edits would key the new path.

---

## T71 — What counts as a collision

### Spec Text
> If the new name would collide with an existing name in scope, exit 1 with a descriptive message.

### Alternatives
1. A collision is another binding of the new name in the same scope as the binding being renamed, wherever in that scope it is written.
2. Only a binding visible at the cursor position counts, so a name defined further down the file does not collide.
3. Any name visible at the cursor collides, builtins and enclosing scopes included.

### Choice
Alternative 1. "In scope" reads as the scope the renamed binding lives in, and
a rename that collides with a later definition in the same scope breaks the
file just as badly as one that collides with an earlier definition. Shadowing
a builtin or an outer name stays legal, as it is in Python.

### Risk: 40
The author may well check only what is visible at the cursor, or may check the
whole lookup chain and refuse renames this tool allows.

---

## T72 — Renaming to a Python keyword

### Spec Text
> `--new-name` must be a valid Python identifier. If not, exit 1.

### Alternatives
1. `class`, `if` and friends are rejected: they are keywords, and code renamed to one does not parse.
2. They are accepted, since `str.isidentifier()` is true for them.

### Choice
Alternative 1. The point of the check is that the result is still Python, and
a keyword fails that.

### Risk: 20
An author who wrote the check as a bare `isidentifier()` accepts keywords.

---

## T73 — "on the module's own definition"

### Spec Text
> **Module renames:** If the cursor is on a module name (in an import or on the module's own definition), the file or directory is renamed

### Alternatives
1. The cursor is on a name that stands for the module: the alias of an import, or a use of that binding such as the `foo` of `foo.bar()`.
2. The cursor is anywhere in the module's own file, which is where a module is "defined" - so `rename foo.py 1 0` renames `foo.py`.
3. Both.

### Choice
Alternative 1. Every other command in the tool starts from a name under the
cursor, and reading "definition" as "the position `goto` reports for the
module" would make a cursor on a comment or an operator mean a rename rather
than the error the same spec demands for a cursor that is not on a name.

### Risk: 30
An author who took reading 2 would rename the file for a cursor at the top of
it; that is the most likely difference, and it is only reachable by a fixture
that puts the cursor outside any name.

---

## T74 — A cursor inside the dotted path of an import

### Spec Text
> If the cursor is on a module name (in an import ...)

### Alternatives
1. The path after `from` and each segment of `import a.b.c` are module names under the cursor, even though no name node covers them; the segment the cursor sits on is the module renamed.
2. Only names the parser binds count, so `from foo import x` with the cursor on `foo` is "not on a name" and exits 1.

### Choice
Alternative 1. `from foo import x` is the commonest way a module name is
written, and the spec calls out imports as the place to find one. Renaming
`pack` in `import pack.inner` moves the package; renaming `inner` moves the
module.

### Risk: 25
An implementation built strictly on its own name-lookup would refuse the
`from`-path cursor.

---

## T75 — How far `inline` looks for references

### Spec Text
> Inline a variable — replace all references with the variable's value and delete the definition.

### Alternatives
1. "All references" is the project-wide search `rename` uses.
2. Only the file the definition is in.

### Choice
Alternative 1. The same phrase describes `rename`'s scope two sections
earlier, and leaving a reference in another file would break that file.

### Risk: 25
An author who scopes inlining to one file gets the same answer for the usual
fixture (a local variable) and a different one for a module-level name another
file imports.

---

## T76 — A name written more than once, or imported elsewhere

### Spec Text
> The name must be a simple assignment (`x = <expr>`).

### Alternatives
1. Exactly one binding may exist: a second assignment, or an `import` of the name in another file, makes the value at a use ambiguous, so the command exits 1.
2. The binding nearest the cursor wins and every use is rewritten with it.

### Choice
Alternative 1. "The name must be a simple assignment" is a statement about the
whole name, not about one of its bindings; rewriting a use that a later
assignment reaches would change what the program computes.

### Risk: 30
An author who only inspects the binding under the cursor would accept these
and rewrite with the value they found.

---

## T77 — The text an inlined value is written with

### Spec Text
> replace all references with the variable's value

### Alternatives
1. The value exactly as the source writes it, spacing and all.
2. The value re-printed from the syntax tree, which normalises spacing and quotes.

### Choice
Alternative 1. Refactoring output is code the user keeps, and rewriting
`a  +  b` as `a + b` is a change the command was not asked to make.

### Risk: 20
An author unparsing the tree differs only where the source is written
unusually.

---

## T78 — Which inlined values get parentheses

### Spec Text
> Wrap the inlined expression in parentheses when needed to preserve evaluation order:
> Parenthesis insertion for `inline` is required whenever dropping parentheses would change operator precedence in the transformed code.

### Alternatives
1. Precedence is compared: the value is wrapped only where the expression it lands in binds tighter than the value does, so `x = a + b` used in `x * 2` is wrapped but the same value used in `x + 2` is not.
2. Any value that is not a single atom is wrapped, wherever it lands.
3. Values are wrapped only in the arithmetic cases, leaving `.attr`, subscripts and calls unwrapped.

### Choice
Alternative 1, which is what "whenever dropping parentheses would change
operator precedence" says: parentheses appear exactly where removing them
would regroup the code. A bare tuple is always wrapped, since its commas would
otherwise join the list, call or assignment it lands in.

### Risk: 35
Alternative 2 is much easier to implement and produces `(a + b) + 2` where
this tool produces `a + b + 2`; that is the likeliest disagreement, and it
shows up in any fixture where the value would have needed no brackets.

---

## T79 — What "delete the definition" removes

### Spec Text
> replace all references with the variable's value and delete the definition.

### Alternatives
1. The whole line or lines the assignment occupies, leaving the lines around it untouched.
2. The assignment's own span, leaving the blank line behind.
3. The lines plus any blank line that followed them.

### Choice
Alternative 1. A deleted statement should leave no empty line where it was,
and nothing in the spec asks for the blank lines around it to be tidied.

### Risk: 25
An author working on the syntax tree may also swallow a following blank line.

---

## T80 — Where the cursor may sit for `inline`

### Spec Text
> python sith.py inline <file> <line> <col>

### Alternatives
1. Either the definition or any reference: both name the variable being inlined.
2. The definition only.

### Choice
Alternative 1. The command is described by the name at the cursor, exactly as
`rename` is, and an editor user inlines from wherever they are reading.

### Risk: 15
A definition-only implementation errors where this one succeeds.

---

## T81 — Which occurrence `extract-variable` replaces

### Spec Text
> The original expression is replaced with the variable name.

### Alternatives
1. The selected occurrence alone.
2. Every occurrence of an equal expression in the same scope.

### Choice
Alternative 1. "The original expression" is the one the selection names; the
spec never mentions searching for others.

### Risk: 20
Some editors extract all equal occurrences, and an author copying that
behaviour would rewrite more lines.

---

## T82 — A selection that includes the brackets around an expression

### Spec Text
> The selection must span a complete expression. If the selection cuts across an expression boundary (e.g., selects half a function call), exit 1 with `"selection is not a complete expression"`.

### Alternatives
1. Balanced brackets and spaces around the expression are part of the selection and are replaced with it, so selecting `(value)` extracts `value`.
2. Only an exact span counts; a selection including the brackets exits 1.

### Choice
Alternative 1: `(value)` is still "a complete expression", and an editor
selection made by eye often takes the brackets with it. An unbalanced bracket
is a cut boundary and still exits 1.

### Risk: 25
A strict span comparison would reject the bracketed selection.

---

## T83 — How the extracted function is spaced

### Spec Text
> The new function is inserted immediately before the function/class containing the selection, at the same indentation level as the enclosing function.

### Alternatives
1. The function, then one blank line, then the definition it was inserted before.
2. Two blank lines between them, as PEP 8 asks for at module level.
3. No blank line at all - "immediately before" taken literally.

### Choice
Alternative 1. It reads as the same rule at every indentation level, unlike
two blank lines, and unlike reading 3 it leaves output that looks like written
Python.

### Risk: 55
Blank lines are pure formatting, they are pinned by any fixture comparing file
contents, and two blank lines at module level is just as defensible as one.

---

## T84 — Which outside names become parameters

### Spec Text
> **Parameter detection:** Variables read in the selected statements but defined outside the selection become function parameters, ordered by first appearance in the selected code.
> The parameter-detection rule still applies at module level: if the selected statements read a module-level name defined outside the selection, that name becomes a parameter to the extracted function rather than staying an implicit global in the extracted body.

### Alternatives
1. Variables only: a name the selection reads becomes a parameter when its binding outside is an assignment, a loop target, a `with` target or a parameter - not when it is a function, a class or an import.
2. Every outside binding becomes a parameter, so calling a helper defined above passes that helper in.
3. Only names local to the enclosing function become parameters, and module-level names are left global - which the second paragraph rules out.

### Choice
Alternative 1. Both paragraphs say "variables", and a module that imports `os`
and calls its own helpers would otherwise extract into a function taking `os`
and every helper it calls, which no editor does.

### Risk: 40
The author's wording is emphatic about module-level names, so an
implementation that passes in any outside binding - imports and functions
included - is a real possibility.

---

## T85 — What "source order" orders the return values by

### Spec Text
> If multiple: return a tuple in source order and update the call site to tuple-unpack in the same order.

### Alternatives
1. The order the names are first assigned in the selected statements.
2. Alphabetical order, or the order they are read after the selection.

### Choice
Alternative 1: "source order" is the order the selected source writes them in,
which is also the order the parameter rule uses.

### Risk: 15
Little room to differ; only a fixture assigning in one order and reading back
in another would tell them apart.

---

## T86 — Extracting code that awaits

### Spec Text
> Extract the code from `<line>:<col>` to `--until <line>:<col>` into a new function.

### Alternatives
1. A block that awaits becomes an `async def`, and the call site awaits it.
2. A plain `def` is always written, which does not parse when the block awaits.

### Choice
Alternative 1. The extracted code has to keep working, and `await` outside a
coroutine is a syntax error.

### Risk: 15
Only reachable through an async fixture, which the spec never mentions.

---

## T87 — Whole-line selections written as `--until <next line>:0`

### Spec Text
> The selection must span one or more complete statements (full lines).

### Alternatives
1. A selection ending at column 0 of the following line is the editor's way of writing "up to the end of the previous line", and is read that way.
2. It is taken literally, so the statement on the following line is half-selected and the command exits 1.

### Choice
Alternative 1. Editors produce that range whenever whole lines are selected,
and the parenthesis in the spec - "(full lines)" - points at exactly that
gesture.

### Risk: 30
A literal reading would exit 1 where this tool extracts.

---

## T88 — How many syntax errors `errors` reports

### Spec Text
> Report syntax errors in the file.
> If the file has no syntax errors, return `{"errors":[]}` and exit 0.

### Alternatives
1. The array holds the error the parser stops at, so a broken file reports one error.
2. The parser is restarted past each error so that several are reported, as an error-recovering parser would.

### Choice
Alternative 1. Python's parser reports one error and stops; everything after
it is guesswork, and a recovered parse invents cascading errors - an
unindented replacement line leads to "unexpected indent" on the next - that
the file's author never wrote.

### Risk: 45
An author whose parser recovers (as editor-oriented parsers do) would report
every error it found, and a fixture with two broken lines would then expect
two entries.

---

## T89 — Converting the parser's positions

### Spec Text
> | `line` | int | 1-based start line. |
> | `column` | int | 0-based start column. |
> | `until_line` | int | 1-based end line. |
> | `until_column` | int | 0-based end column. |

### Alternatives
1. The parser's 1-based column offsets become 0-based by subtracting one, and an end the parser leaves open (it reports 0, or -1) collapses onto the start column.
2. The parser's numbers are passed through, leaving columns 1-based.
3. The end position is extended to the end of the line when the parser gives none.

### Choice
Alternative 1, which is the convention the rest of the tool already reports
positions in, and it never produces an end before the start.

### Risk: 35
The open-ended cases - an unclosed bracket, an unexpected indent - are where
implementations differ; the author may well report the end of the line there.

---

## T90 — The text of an error message

### Spec Text
> | `message` | string | Error description from the parser. |

### Alternatives
1. The parser's message alone, e.g. `invalid syntax` or `expected an indented block after function definition on line 1`.
2. The message with its exception class, e.g. `SyntaxError: invalid syntax`.
3. The whole formatted traceback line, source excerpt included.

### Choice
Alternative 1: "description from the parser" is the description, not the
rendering of the exception around it.

### Risk: 30
An author who calls `str(error)` would include the `(file, line N)` suffix,
and one who prefixes the class name is just as plausible.
