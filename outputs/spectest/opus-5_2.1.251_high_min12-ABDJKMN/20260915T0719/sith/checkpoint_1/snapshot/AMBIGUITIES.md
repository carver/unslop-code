# Ambiguities

Numbered record of under-specified points in the spec, the interpretation chosen,
and the estimated risk that the spec author's own implementation differs.

---

## T1. Description of names bound by `from X import name`

### Spec Text
> | `description` | string | A short description. For functions: `def name(...)`. For classes: `class Name`. For imports: `module name`. For assignments: `instance of <type>` if the right-hand side is a literal, a constructor call, or otherwise resolvable to a known type; otherwise `statement`. For keywords: the keyword itself. |

> For imported names (from import statements), the `type` reflects the imported object's actual kind if inferable (e.g., `function`, `class`, `module`). If not inferable, use `statement`.

### Alternatives
1. `description` is a pure function of the resolved `type`: `module` → `module name`, `class` → `class Name`, `function` → `def name(...)`, `instance` → `instance of T`, `statement` → `statement`. Under this reading "For imports: `module name`" is just the `module` row of that mapping, so `from os import getcwd` → `def getcwd(...)`.
2. Every name bound by an `import`/`from ... import` statement literally gets `module <bound name>`, so `from os import getcwd` → type `function`, description `module getcwd`.

### Choice
Alternative 1. The listed description forms map one-to-one onto the `type` enum
(`module`/`class`/`function`/`instance`/`statement`/`keyword`), which strongly suggests a single
`describe(type, name)` helper in the reference implementation. It would also be incoherent to
report `type: "function"` for `getcwd` while describing it as a module.

### Risk: 25
The author most likely prefers: description derived from the inferred kind (same as this choice); the
residual risk is that their code special-cases every import-bound name to `module <name>`.

---

## T2. Description for parameters

### Spec Text
> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`, `keyword`. |

### Alternatives
1. `param <name>` (mirrors the `module <name>` form).
2. `statement` (the generic fallback).
3. `param` alone, or `instance of <annotation>` when annotated.

### Choice
`param <name>`. The description table never mentions parameters, and the `module name` /
`class Name` forms show the house style of "kind + name". A bare `statement` would throw away the
one thing that is known about the symbol.

### Risk: 55
The author most likely prefers: `param <name>`, but `parameter` / `param` / `statement` are all
plausible strings from an implementation that never thought hard about this row.

---

## T3. Whether a definition is visible on its own line

### Spec Text
> A name is visible only if it is defined **before** the cursor position in the source (for the local and global scopes). A `def` or `class` statement makes its name visible from the line of the `def`/`class` keyword. An assignment makes the name visible from the line of the assignment.

### Alternatives
1. Visible when `definition_line <= cursor_line` (inclusive — "from the line of").
2. Visible only when `definition_line < cursor_line` (strictly "before the cursor position").

### Choice
Inclusive (`<=`). "makes its name visible **from** the line of" reads as starting at that line, and
it makes recursive references (`def f(): ... f`) and self-referential assignments behave sanely.
Column position within the line is not considered.

### Risk: 15
The author most likely prefers: inclusive comparison, as written.

---

## T4. Line count of a file that ends with a newline / is empty

### Spec Text
> If the position is out of range (line exceeds file length, or column exceeds line length), exit 1.

### Alternatives
1. `text.splitlines()` — a trailing `\n` does not create an extra empty line; an empty file has zero lines, so every position errors.
2. `text.split("\n")` — a trailing `\n` yields a final empty line (editor-like), and an empty file has one empty line at line 1 col 0.

### Choice
`splitlines()`. It is the idiomatic one-liner for "the lines of the file", and "line exceeds file
length" most naturally means "greater than the number of lines of text".

### Risk: 35
The author most likely prefers: `splitlines()`; the residual risk is a test that completes on the
phantom empty line just past a trailing newline (or in an empty file), which this choice rejects
with exit 1.

---

## T5. Which keywords are offered

### Spec Text
> When in a name-completion context, also include Python keywords as completions.

### Alternatives
1. `keyword.kwlist` (35 hard keywords, including `True`/`False`/`None`).
2. `keyword.kwlist + keyword.softkwlist` (adds `_`, `case`, `match`, `type`).

### Choice
`keyword.kwlist` only. Soft keywords are ordinary identifiers outside of their syntactic context and
would pollute every completion list with `_`.

### Risk: 20
The author most likely prefers: `keyword.kwlist`.

---

## T6. `True`/`False`/`None` appearing twice

### Spec Text
> Name completion with an empty prefix returns all currently visible names plus keywords, then applies the ordering rules in this spec.

### Alternatives
1. Emit both the builtin-scope entry (`type: instance`) and the keyword entry (`type: keyword`) — names and keywords are separate, independently ordered groups.
2. De-duplicate by name, keeping one of them.

### Choice
Emit both. The ordering rules place keywords in their own trailing group, which implies keywords are
appended as a distinct list rather than merged into the name table; `dir(builtins)` genuinely
contains `True`, `False` and `None`.

### Risk: 40
The author most likely prefers: both entries present (keywords appended after names), but an
implementation that merges everything into one dict would emit only one.

---

## T7. The `complete` field under `--fuzzy`

### Spec Text
> `complete` … The text that would be inserted — the name with the already-typed prefix removed. … When prefix matching is case-insensitive, removal is by character count: the first `len(prefix)` characters of the matched name are stripped regardless of case.

### Alternatives
1. Strip `len(prefix)` leading characters for fuzzy matches too (`isnt` → `isinstance` → `stance`).
2. Return the whole name for fuzzy matches, since the typed characters are not a real prefix.
3. Strip up to the last matched character position.

### Choice
Strip `len(prefix)` characters. The spec defines `complete` by character count, with no fuzzy-mode
exception, and this keeps the field trivially computable in both modes.

### Risk: 35
The author most likely prefers: character-count stripping (same as this choice); the main
alternative is returning the full name in fuzzy mode.

---

## T8. Class bodies as scopes

### Spec Text
> 1. **Local scope** — names assigned or defined in the immediately enclosing function/method.
> 2. **Enclosing scopes** — names from enclosing functions (for nested functions/closures).

### Alternatives
1. Python semantics: a class body is its own scope; when the cursor is directly in a class body those names are local, but they are *not* visible from inside its methods.
2. Treat class bodies as transparent, so a method sees the class-level names as if they were enclosing-function names.

### Choice
Python semantics (alternative 1). The spec names "functions" for enclosing scopes, which matches
CPython's rule that class scopes are skipped in the closure chain, and a tool that suggested
class-level names as bare names inside a method would suggest code that raises `NameError`.

### Risk: 30
The author most likely prefers: class scope skipped for methods (this choice); a simpler
"walk all enclosing blocks" implementation would include them.

---

## T9. Which methods contribute instance attributes

### Spec Text
> **Instances** — if `foo` is an instance (from `foo = MyClass()`), return the same attributes as the class plus any attributes assigned in `__init__` via `self.name = ...`.

### Alternatives
1. Only `__init__` (of the class and of its in-file base classes).
2. `self.x = ...` assignments in *any* method.

### Choice
Only `__init__`, exactly as written, but including the `__init__` of in-file base classes since the
spec already requires inherited class attributes.

### Risk: 20
The author most likely prefers: `__init__` only.

---

## T10. Underscore filtering for non-module receivers

### Spec Text
> **Modules** — if `foo` is an imported module, return the module's public names. A name is public if it does not start with `_`.

### Alternatives
1. The public filter applies only to modules; class/instance/literal receivers return every attribute, dunders included (the ordering rules have a dedicated dunder group, so dunders are expected to appear somewhere).
2. Filter `_`-prefixed names for every receiver.

### Choice
Alternative 1 — the "public" rule is stated only in the module bullet, and the existence of the
private/dunder ordering groups only makes sense if such names can be returned.

### Risk: 20
The author most likely prefers: filtering only modules (this choice).

---

## T11. Resolving local modules for `import` / star-import

### Spec Text
> `import os` makes `os` visible as a module. `from os import *` makes all public names from `os` visible. Star imports resolve both installed packages and local project modules (files in the same directory).

### Alternatives
1. Local project modules are analysed statically (parse the sibling `.py` file and take its module-level bindings whose names do not start with `_`); installed packages are imported and `dir()`ed.
2. Everything is imported with `importlib` after putting the file's directory on `sys.path`, executing local project code.
3. `__all__` is honoured when present.

### Choice
Alternative 1: sibling `.py` files (and `pkg/__init__.py`) are parsed, never executed; installed
modules are imported. `__all__` is ignored — the spec defines public purely as "does not start with
`_`".

### Risk: 25
The author most likely prefers: static analysis for local files and `dir()` for installed modules;
divergence would show up on a local module that re-exports imported names or defines `__all__`.

---

## T12. Variables holding builtin values as attribute receivers

### Spec Text
> **Literals** — string/list/dict/set literals expose attributes appropriate to their inferred builtin type.

### Alternatives
1. Any expression whose type is inferred to a builtin type exposes `dir(type)` — including a variable assigned a literal (`s = "hi"` then `s.`).
2. Only syntactic literals immediately before the dot get this treatment.

### Choice
Alternative 1. The "Instances" bullet already generalises assignment-inferred receivers, and the
description rule `instance of <type>` shows that literal-assigned variables carry an inferred type,
which would be pointless if it could not be used for attribute completion.

### Risk: 15
The author most likely prefers: inferred builtin types work through variables too.

---

## T13. Receivers that cannot be resolved

### Spec Text
> When the cursor follows a `.`, return attributes of the value before the dot.
> On success, exit **0** (even with zero completions).

### Alternatives
1. Unresolvable receiver (unknown function result, parameter with no annotation, garbage before the dot) → empty completion list, exit 0.
2. Treat it as an error (exit 1), or fall back to name completion.

### Choice
Empty list with exit 0. "Zero completions" is explicitly a success case, and falling back to bare
names after a dot would suggest syntactically invalid code (and keywords, which are banned there).

### Risk: 10
The author most likely prefers: empty list, exit 0.

---

## T14. Cursor inside a comment or string literal

### Spec Text
> When the cursor is in a position where a bare name is expected (not after a `.`), return all names visible at the scope.

### Alternatives
1. No special handling — the text before the cursor is scanned as if it were code, so a comment like `# pri` still yields name completions.
2. Detect comments/strings and return nothing.

### Choice
No special handling. The spec's only context test is "is there a `.` before the identifier", and the
tolerant-parsing requirement pushes towards a purely textual prefix/receiver scan.

### Risk: 25
The author most likely prefers: no special handling (a purely textual scan).

---

## T15. Ordering group of names like `__foo` (leading dunder, no trailing dunder)

### Spec Text
> 2. **Private names** (start with `_` but not `__`) … 3. **Dunder names** (start with `__` and end with `__`)

### Alternatives
1. Three-way classification evaluated as: dunder if `__…__`, else private if it starts with `_`, else public — so `__foo` lands in the private group.
2. `__foo` belongs to neither described group and is sorted into the public group (or last).

### Choice
Alternative 1: names are partitioned into exactly three groups, with the dunder test first and any
other leading underscore counting as private. A name-mangled `__foo` is conceptually "more private",
never public.

### Risk: 20
The author most likely prefers: `__foo` grouped with private names.

---

## T16. Type/description of a `lambda` assignment and of un-inferable calls

### Spec Text
> For assignments: `instance of <type>` if the right-hand side is a literal, a constructor call, or otherwise resolvable to a known type; otherwise `statement`.

### Alternatives
1. `f = lambda: 1` → type `function`, description `def f(...)`; `x = unknown_fn()` → type `statement`, description `statement`.
2. `f = lambda: 1` → `instance of function`.

### Choice
Alternative 1 — a lambda binding is a function in every other part of the tool's vocabulary, and a
call whose callee cannot be resolved to a class is exactly the "otherwise" case.

### Risk: 30
The author most likely prefers: `x = unknown_fn()` → `statement` (agreed); the lambda row is the
uncertain half, where `instance of function` is the competing answer.

---

## T17. Positional rule inside enclosing (closure) scopes

### Spec Text
> A name is visible only if it is defined **before** the cursor position in the source (for the local and global scopes).

### Alternatives
1. The parenthetical is exhaustive: names in enclosing *function* scopes are visible regardless of where they are defined relative to the cursor (a closure can legitimately reference a name bound later in the enclosing function).
2. Apply the positional rule everywhere.

### Choice
Alternative 1, taking "(for the local and global scopes)" as a deliberate exclusion of enclosing
scopes — which also matches Python's runtime semantics for closures.

### Risk: 20
The author most likely prefers: no positional filtering for enclosing scopes (this choice).

---

## T18. Receiver expressions more complex than a bare name

### Spec Text
> When the cursor follows a `.`, return attributes of the value before the dot.

### Alternatives
1. Scan backwards over one *atom* (identifier, literal, bracketed group) plus any trailing `.name` / call / subscript chain, so `y = 1 + x.` resolves the receiver `x`.
2. Take the longest parseable suffix of the line, so `y = 1 + x.` resolves the receiver `1 + x`.

### Choice
Alternative 1: `.` binds to the nearest atom, which is what Python's grammar does. Calls in the chain
resolve when the callee is a known class (`MyClass().`), otherwise the receiver is unresolved.

### Risk: 30
The author most likely prefers: a backwards atom scan; implementations differ mostly on whether
chained calls (`foo().bar.`) resolve at all, which this one handles only for known classes.

---

## T19. Builtin names as attribute receivers, and `type` for builtin values

### Spec Text
> 4. **Builtin scope** — builtin names provided by Python's `builtins` module.

### Alternatives
1. Builtin names are classified like any other object: classes (`int`, `str`, `property`) → `class`, callables (`print`, `len`) → `function`, everything else (`True`, `None`, `__name__`) → `instance of <type>`; and they may serve as attribute receivers (`str.` → `dir(str)`).
2. Builtins are all reported as `statement`, or are not usable as receivers.

### Choice
Alternative 1 — the spec's example output shows `print` as `function` / `def print(...)` and
`property` as `class` / `class property`, i.e. real introspection of `builtins`.

### Risk: 10
The author most likely prefers: introspective classification (this choice).

---

## T20. Tolerant parsing strategy

### Spec Text
> Python syntax errors in the source file: **do not** exit with an error. Parse as much as possible and provide completions based on what was successfully parsed.

### Alternatives
1. Iteratively repair: replace each offending line with `pass` at the same indentation (preserving line numbers and block structure), re-parsing until it succeeds.
2. Truncate the file at the first error and parse the prefix.
3. Parse only the lines before the cursor.

### Choice
Alternative 1. It keeps line numbers aligned (the whole visibility model is line-based) and, unlike
truncation, keeps definitions that appear *after* a broken line — "parse as much as possible".
Receiver and prefix detection are textual, so a broken cursor line (`foo.`) still completes.

### Risk: 30
The author most likely prefers: some repair of the cursor/offending line; differences appear on files
with an error early on, where a truncating implementation would lose all later definitions.

---

## T21. `self` / `cls` as an attribute receiver

### Spec Text
> **Instances** — if `foo` is an instance (from `foo = MyClass()`), return the same attributes as the class plus any attributes assigned in `__init__` via `self.name = ...`.

### Alternatives
1. The receiver rules apply only to the named forms (imported modules, class names, `x = MyClass()`, literals), so `self.` inside a method resolves to nothing.
2. The first parameter of a method is implicitly an instance of the enclosing class (and of a classmethod's first parameter, the class itself), so `self.` completes the class's attributes.

### Choice
Alternative 2: `self.` completes instance attributes of the enclosing class, `cls.` (in a
`@classmethod`) completes class attributes, and the first parameter of a `@staticmethod` stays
unresolved. The spec's own instance rule is phrased in terms of `self.name = ...` assignments, so it
already models `self` as the enclosing instance; completing after `self.` is the single most common
request an editor makes of such a tool.

### Risk: 30
The author most likely prefers: `self.` resolving to the enclosing class (this choice); a minimal
implementation that only resolves the receiver forms listed in the spec would return an empty list.

---

## T22. Annotated parameters and variables as receivers

### Spec Text
> **Instances** — if `foo` is an instance (from `foo = MyClass()`), return the same attributes as the class

### Alternatives
1. Annotations are also a source of type information: `def use(t: Thing)` and `x: Thing` make `t`/`x` instances of `Thing`.
2. Only assignment of a constructor call creates an instance; annotations are ignored.

### Choice
Alternative 1 for attribute resolution, since it costs nothing and cannot produce a wrong receiver
when the annotation names a known class. Note the *type* of an annotated parameter stays `param`
(the spec's enum has a dedicated value for parameters) and the type of `x: Thing` (no value) is
`instance`.

### Risk: 40
The author most likely prefers: ignoring annotations entirely, which would give an empty completion
list after `t.` for an annotated parameter.
