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

---

## T23. Project root, and `module_path` for files outside it

### Spec Text
> | `module_path` | string | File path where the name is defined, relative to the project root. When `--project` is not available, the project root is the directory containing `<file>`. |

### Alternatives
1. Always `os.path.relpath(definition_file, root)`, so a stdlib definition becomes something like `../../../usr/lib/python3.12/os.py`.
2. Relative path when the definition lives under the project root, absolute path otherwise.
3. Only ever the bare filename (basename), losing sub-package structure.

### Choice
Alternative 2, plus an (undocumented, optional) `--project <dir>` flag since the spec speaks of
`--project` as something that may or may not be "available". Project-local definitions -- the only
ones a portable test can assert on -- are reported as `lib.py` / `pkg/mod.py` either way; a
`../../..` chain up into the interpreter's install directory is not a meaningful "path relative to
the project root", and an absolute path is the more useful answer there.

### Risk: 20
The author most likely prefers: the same relative path for project files (identical behaviour);
residual risk is only in what a *stdlib* definition reports, which is machine-specific and unlikely
to be asserted.

### Resolved by the current spec
Confirmed: `--project <dir>` is now an official flag on all commands, with the same default ("the
directory containing `<file>`") this entry assumed. The current spec adds that the root is also
"the base for computing module qualified names" (T47) and that output paths always use forward
slashes -- both now implemented; the absolute-path fallback for definitions outside the root is
still this entry's own choice.

---

## T24. `type` of a builtin *class* named directly

### Spec Text
> For builtin types (including None, int, str, etc.), definitions use type "instance" and full_name "builtins.<name>" with module_path set to empty string and line/column set to 0.

> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`. |

### Alternatives
1. The sentence describes how *values* of builtin type are reported (`x = 5` → `int`, type `instance`); a name that refers to the builtin class itself (`infer` on `str` in `str(5)`) is still a `class`, and a builtin function (`len`) is still a `function`.
2. Every definition that comes from `builtins` gets type `instance`, including `str` and `len`.

### Choice
Alternative 1. The sentence sits in the paragraph about how inferred *types* are rendered, and the
`type` enum exists precisely to distinguish a class from an instance of it; reading it as "all
builtins are instances" would make `infer` on `str` claim `str` is an instance of something.

### Risk: 35
The author most likely prefers: this reading for literals (the common fixture); the residual risk is
a fixture that puts the cursor directly on a builtin class name such as `str` or `dict`.

---

## T25. `docstring` of builtin definitions

### Spec Text
> | `docstring` | string | The docstring of the definition, or empty string if none. |

> For builtin types ... with `module_path` set to empty string and line/column set to 0.

### Alternatives
1. Builtin definitions are synthesised placeholders, so their docstring is `""` (like their path and position).
2. `inspect.getdoc(int)` is used, so the definition carries CPython's real `int` docstring (`"int([x]) -> integer..."`).

### Choice
Alternative 1. The spec hard-codes *every* other positional field of a builtin definition to a
placeholder (`""`, `0`, `0`), which reads like a small synthesised record rather than live
introspection; a docstring that varies with the CPython version would also make the author's own
fixtures fragile.

### Risk: 35
The author most likely prefers: `""` as here; the residual risk is an implementation that builds the
record with `getattr(builtins, name)` and calls `inspect.getdoc` on it.

---

## T26. The name of the `None` type

### Spec Text
> For builtin types (including None, int, str, etc.), definitions use type "instance" and full_name "builtins.<name>"

> If a function has no `return` statement or only bare `return`, the return type is `None`.

### Alternatives
1. The None type is called `None`: `name` `"None"`, `full_name` `"builtins.None"`, description `instance of None`.
2. Python's own name is used: `name` `"NoneType"`, `full_name` `"builtins.NoneType"`.

### Choice
Alternative 1 for `infer`/`goto` definitions -- the spec lists "None" (not "NoneType") alongside
`int` and `str` as a builtin type name, and says the return type "is `None`". The pre-existing
`complete` behaviour is left untouched (`var = None` still completes with description
`instance of NoneType`, which is what `type(None).__name__` yields), so this spec's addition does
not change the earlier contract.

### Risk: 40
The author most likely prefers: `"None"` in the new definition payloads (as chosen); the residual
risk is an implementation that uses `type(v).__name__` uniformly and therefore reports `NoneType`
in `infer` output too.

---

## T27. Which bindings are "reachable" when a name is assigned more than once

### Spec Text
> Multiple definitions are returned when a name could resolve to more than one thing (e.g., conditional assignments).

> For unresolved branches, return all reachable possibilities.

### Alternatives
1. Only the textually last binding before the cursor is returned (the `complete` rule), so conditional assignments would collapse to the `else` branch -- contradicts the spec.
2. Every binding before the cursor is returned, so `x = 1` followed by `x = 2` reports both.
3. Branch-aware: a later binding cancels an earlier one only when it is guaranteed to run whenever the earlier one did -- i.e. it sits on the same branch or on an enclosing one. Sibling branches (`if`/`else`, several `return`s) all survive.

### Choice
Alternative 3. It is the only reading that satisfies both quoted sentences at once: conditional
assignments yield several definitions, while a plain rebinding (`x = 1; x = 2`) yields the one value
the name actually has -- the same intuition the "follow assignment chains" rule encodes.

### Risk: 30
The author most likely prefers: branch-aware liveness as chosen; the most likely divergence is a
simpler implementation that returns *all* bindings before the cursor, which would add `int` to a
`x = 1` / `x = 'text'` rebinding case.

---

## T28. `description` of an assignment

### Spec Text
> | `description` | string | Short description. ... For assignments: the right-hand expression or statement.

### Alternatives
1. The source text of the right-hand side only: `x = 1 + 2` → `1 + 2`, `c = Calculator()` → `Calculator()`. "or statement" covers bindings with no right-hand side (`x: int`, `for x in ...`, `with ... as x`).
2. The whole assignment statement, jedi-style: `x = 1 + 2` → `x = 1 + 2`.

### Choice
Alternative 1. The field is explicitly "the right-hand *expression*", which is a strictly narrower
phrase than "the statement"; the trailing "or statement" then covers the cases where there is no
right-hand expression to show.

### Risk: 45
The author most likely prefers: possibly the full statement text (`x = 1 + 2`), which is what jedi's
`Name.description` produces for a statement and which the words "or statement" could be read to
allow for every assignment.

---

## T29. `type` and `description` of an import binding under `goto`

### Spec Text
> - `goto` returns where the name at the cursor is assigned or defined (`def`, `class`, assignment, or import binding).

> | `description` | ... For imports: the import statement text. |

### Alternatives
1. `goto` on an imported name stops at the import statement (line/column of the bound name there), describes it with the import statement's source text, and takes its `type` from whatever the import resolves to (`module`, `class`, `function`, `instance`), falling back to `statement`.
2. `goto` follows the import into the other file and returns the real definition -- but then "import binding" in the list above would be redundant, and no definition could ever have "the import statement text" as its description.
3. As 1, but `type` is always `module` (or always `statement`).

### Choice
Alternative 1: it is the only reading in which both quoted sentences do work. `infer` is what follows
the import through to the class/function in the other file, which is exactly the `goto`/`infer`
division of labour the Clarifications section draws.

### Risk: 40
The author most likely prefers: the import-statement location as chosen; the likeliest divergence is
the `type` value -- a flat `module` for every `import ...` binding regardless of what was imported.

### Resolved by the current spec
Confirmed: "Without `--follow-imports` (default), `goto` on an imported name returns the `import`
statement itself". Following the import into the other file is now the opt-in `--follow-imports`
behaviour (see T40, T45, T46, T51). The choice above stands unchanged for the default form; only the
residual risk about the `type` value remains open.

---

## T30. Flow narrowing: extent, and the empty `is None` section

### Spec Text
> ### `isinstance` narrowing
> When the cursor is inside an `isinstance` branch, narrow the type accordingly:
> - `isinstance(x, SomeClass)` — `x` is `SomeClass` inside the `if` body.

> ### `is None`

*(the `is None` section is empty in the spec)*

### Alternatives
1. Narrow only inside the `if` body of a literal `isinstance(x, C)` test; leave `is None` unimplemented.
2. Narrow symmetrically: `if x is None:` makes `x` the `None` type in the body and removes `None` from the union in the `else`; `if x is not None:` is the mirror image. Treat the `else` of an `isinstance` as removing that class from a union, honour `not`/`and`, tuples of classes, `while`, and `assert isinstance(...)`.

### Choice
Alternative 2. The empty heading still announces `is None` as a narrowing form the tool is expected
to support, and the only sensible content for it is the standard optional-narrowing rule. The extra
forms (`else` branches, `not`, tuple second argument) fall out of the same small predicate walker and
never fire unless the source actually contains such a test.

### Risk: 35
The author most likely prefers: `x` narrowed to `None` inside `if x is None:` and to the non-None
part of the union inside `if x is not None:` (as chosen); residual risk is in the extras -- an author
implementation that does nothing at all in the `else` branch of a narrowing `if`.

---

## T31. `infer` with the cursor on the function name of a call

### Spec Text
> `infer` returns what the name at the cursor evaluates to after static propagation through assignments and calls.

> For bare function names, both commands may resolve to the same function definition object.

### Alternatives
1. The name `make` in `v = make()` evaluates to the *function* `make`; the call's result is observed by inferring `v`. "Propagation through calls" describes how a value reaches `v`, not what the callee's own name means.
2. The cursor on `make` in `make()` reports the function's *return type*.

### Choice
Alternative 1. The spec says the commands answer for "the name at the cursor", and the sentence
about bare function names only makes sense if `infer` on a function name yields the function
definition. Return types are still fully exercised through the assignment (`v = make()` → `infer v`).

### Risk: 30
The author most likely prefers: the function itself (as chosen); the residual risk is an
implementation that infers the enclosing call expression whenever the cursor is on its callee.

---

## T32. `line`/`column` of a module definition

### Spec Text
> | `line` | int | 1-based line number of the definition. |
> | `column` | int | 0-based column of the name identifier in the definition. |

### Alternatives
1. A module has no defining identifier, so both are the placeholder `0` -- the same convention the spec fixes for builtins.
2. A module's definition is its file, which starts at line 1, column 0.

### Choice
Alternative 1. A module name never appears as an identifier inside the file it names, so there is no
"column of the name identifier" to report; `0`/`0` is the placeholder the spec already uses for
definitions without a position.

### Risk: 45
The author most likely prefers: `line: 1, column: 0` if their implementation reuses the module's
start position rather than a placeholder. Only reachable by putting the cursor on a module name, so
it is unlikely to be the subject of a fixture either way.

---

## T33. Functions with a return annotation but no `return` statement

### Spec Text
> Infer a function's return type by analyzing its `return` statements.

> If a function has no `return` statement or only bare `return`, the return type is `None`.

### Alternatives
1. The rule is absolute: no `return` statement means `None`, even for `def f() -> int: ...`.
2. `return` statements win when present; a `-> T` annotation is consulted only when the body yields nothing (no returns at all, or none of them resolvable).

### Choice
Alternative 2. The spec's rule is written against ordinary function bodies, and an explicit
annotation is a stronger, author-supplied statement of the return type than an empty body is; it
also only ever fires where reading (1) would report nothing useful.

### Risk: 25
The author most likely prefers: `None` for an annotated body-less function, if their implementation
implements the quoted sentence literally and ignores annotations.

---

## T34. `full_name` of names that are neither top-level nor class members

### Spec Text
> | `full_name` | string | Dot-separated qualified name. For top-level names: `module.name`. For nested: `module.Class.method`. |

### Alternatives
1. The rule generalises: every enclosing `def`/`class` contributes a segment, so a local of `f` is `main.f.x`, a parameter is `main.f.a`, and an attribute assigned in `__init__` is `main.Class.attr` (the method name is skipped -- the attribute belongs to the class, not to `__init__`).
2. Locals and parameters have no qualified name and report just `module.name`, or an empty string.

### Choice
Alternative 1: `full_name` is typed `string` with no "may be empty" note, and the two examples given
(top-level, nested) are plainly instances of one "join the enclosing scope names" rule.

### Risk: 25
The author most likely prefers: the same chain; the residual risk is `main.Calculator.__init__.value`
(keeping the method segment) for attributes bound via `self.value = ...`.

---

## T35. `infer` on a name with no inferable type

### Spec Text
> If the name cannot be resolved, return an empty array (exit 0).

### Alternatives
1. A parameter with no annotation, no narrowing and no `self` meaning is "not resolvable": `infer` returns `[]`, while `goto` still returns its `param` definition.
2. `infer` falls back to returning the binding itself (a `param` or `statement` definition) so the array is never empty when the name is known.

### Choice
Alternative 1. `infer` is defined as "what the name evaluates to"; when nothing is known about the
value there is no type definition to point at, and the spec provides the empty array for exactly that
case. `type: "param"` still appears in output -- via `goto`.

### Risk: 30
The author most likely prefers: the empty array (as chosen); the residual risk is an implementation
that mirrors `goto` whenever inference fails.

---

## T36. What counts as "on a name"

### Spec Text
> If the cursor is not on a name, exit 1.

### Alternatives
1. The cursor is on a name when the identifier run around it is non-empty -- including at either end of it (`|foo`, `fo|o`, `foo|`) -- and that run is not a keyword and does not start with a digit. `None`/`True`/`False` count as names. Identifier-looking text inside a string or comment is a "name" that simply resolves to nothing (empty array, exit 0).
2. Only a cursor strictly inside the identifier counts; the position just past its last character is a miss.
3. Any position inside a string or comment exits 1.

### Choice
Alternative 1. Editors put the caret *after* the word being examined, so the end-inclusive rule is
the one that matches how the command would be used, and it matches this tool's existing `complete`
prefix scan (which also reads the identifier ending at the cursor). Text in a comment or string is
not distinguishable from a name by the cursor rules the spec gives, and answering "no definition"
there is gentler than failing.

### Risk: 25
The author most likely prefers: the same end-inclusive identifier rule; the likeliest divergence is
exiting 1 for a cursor inside a comment or string literal.

---

## T37. Whether annotated class fields are exposed only for dataclasses

### Spec Text
> Classes decorated with `@dataclasses.dataclass` expose their annotated fields as instance attributes for completion and inference.

> `@dataclass` is recognized regardless of import form (`import dataclasses`, `from dataclasses import dataclass`, or aliased forms).

### Alternatives
1. Annotated class-body fields (`x: int`) are exposed as instance attributes for *every* class; the dataclass paragraph is then a statement about the case that matters, and "regardless of import form" is satisfied trivially because the decorator is never inspected.
2. The fields are exposed only when the decorator is recognised as `dataclasses.dataclass`, so a plain class with `x: int` in its body exposes nothing.

### Choice
Alternative 1. The spec's emphasis is that the decorator's *spelling* must never change the answer,
and the surest way to honour that (aliases, `@dataclass()`, `@dataclass(frozen=True)`, re-exports) is
not to condition on the decorator at all. An annotated class-body name is a real attribute of
instances of that class in any case.

### Risk: 15
The author most likely prefers: the same observable behaviour on dataclasses; a divergence needs a
fixture asserting that a *non*-dataclass with annotated fields exposes nothing.

---

## T38. `name` of an inferred instance definition

### Spec Text
> ```json
> {"definitions":[{"name":"Calculator","type":"class","full_name":"example.Calculator", ...
> ```

> | `name` | string | The identifier name. |

### Alternatives
1. An inferred definition names the *thing it points at*: `c = Calculator()` then `infer c` → `name: "Calculator"`, and `x = 5` then `infer x` → `name: "int"`.
2. It echoes the identifier under the cursor: `name: "c"` / `name: "x"`.

### Choice
Alternative 1. Every other field of an inferred definition (`full_name`, `module_path`, `line`) is
taken from the class or builtin being pointed at, and the spec's own builtin rule fixes
`full_name: "builtins.int"` -- a record whose `name` were `"x"` but whose `full_name` were
`builtins.int` would be incoherent.

### Risk: 10
The author most likely prefers: the pointed-at name, as chosen.

---

## T39. Third-party modules: resolvable, or only project + stdlib?

### Spec Text
> **Module search order:**
> 1. Project root — scan for `.py` files and packages (directories containing `__init__.py`).
> 2. Standard library — recognize stdlib modules available in the target runtime.
> 3. If a module cannot be found, treat it as unresolvable

> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib), return the import statement as a fallback.

### Alternatives
1. The list is exhaustive: only project files and the standard library resolve, so an installed
   third-party package (`pytest`, say) is unresolvable even though the runtime can import it.
2. Step 2 means "whatever the target runtime can import", which incidentally includes installed
   third-party distributions; only genuinely missing modules hit step 3.

### Choice
Alternative 2. "Available in the target runtime" describes a live-import probe rather than a
hard-coded stdlib list, and the goto fallback sentence groups third-party *with* stdlib as things
that "cannot be found" for the purpose of jumping to a definition -- i.e. the distinction the spec
actually draws is project / not-project, not stdlib / not-stdlib. Resolving installed packages can
only add information; refusing to would make `infer` on a third-party name silently empty.

### Risk: 25
The author most likely prefers: the same for stdlib (identical behaviour there); the divergence
shows only for an installed non-stdlib module, where their implementation may gate on
`sys.stdlib_module_names` and return nothing.

---

## T40. Does `--follow-imports` follow into stdlib / installed modules?

### Spec Text
> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib), return the import statement as a fallback.

> With `--follow-imports`, if the terminal target cannot be resolved, return the import site in the current file as the fallback definition.

### Alternatives
1. `--follow-imports` only ever lands inside the project; anything outside it (stdlib, installed
   packages) falls back to the import statement in the current file -- even for pure-Python stdlib
   modules whose source file `inspect` could point at.
2. Follow wherever a source file exists, so `from collections import OrderedDict` jumps into
   `.../lib/python3.12/collections/__init__.py` and only C-implemented objects fall back.

### Choice
Alternative 1. The spec names stdlib explicitly as a case that "cannot be found", and a definition
outside the project has no meaningful `module_path` ("relative to the project root"), so reporting
the import site keeps every `--follow-imports` answer inside the project.

### Risk: 20
The author most likely prefers: the import-statement fallback as chosen; residual risk is an
implementation that reuses its existing live-object definition path for pure-Python stdlib targets.

---

## T41. What `import |` lists

### Spec Text
> - `import ...` suggests top-level module/package names.
> - `import |` suggests top-level module/package names.

### Alternatives
1. Project-root modules and packages only.
2. Project-root modules and packages, plus the standard library module names of the target runtime.
3. Everything importable anywhere on `sys.path`, including installed third-party distributions.

### Choice
Alternative 2: it mirrors the documented module search order (project root, then standard library),
so the names offered are exactly the names that would resolve if typed. Walking all of `sys.path`
would make the list depend on the test machine's site-packages.

### Risk: 30
The author most likely prefers: project modules plus stdlib as chosen; the likeliest divergence is a
project-only list, which a fixture asserting an exact set (rather than membership) would expose.

---

## T42. Submodules as importable names of a package

### Spec Text
> - `from X import |` suggests names inside module `X`.

> In `from X import ...` completion, exported names come from `__all__` when it exists; otherwise use names that do not start with `_`.

### Alternatives
1. "Names inside `X`" means only the names bound in `X`'s module body (`__init__.py` for a package).
2. It also includes `X`'s submodules, since `from pkg import mod` is a legal import of a submodule
   that no name in `__init__.py` provides.

### Choice
Alternative 2 (and, symmetrically, submodules show up as attributes of a package receiver, so
`pkg.<TAB>` lists them). A completion list that omits `mod` would fail to suggest an import that the
tool itself resolves. When `__all__` exists it still wins: only those names are offered.

### Risk: 25
The author most likely prefers: submodules included for packages; the divergence would be an
implementation that only reads the package's `__init__.py` bindings.

---

## T43. Does `__all__` apply to runtime (stdlib) modules as well?

### Spec Text
> A name is public if:
> - The module defines `__all__`: use exactly those names.
> - Otherwise: all names that do not start with `_`.

### Alternatives
1. The rule is about "a module" in general, so `from os import *` exposes exactly `os.__all__` --
   which includes `_exit`, an underscore name that is nevertheless exported.
2. `__all__` is only honoured for statically analysed project modules; runtime modules keep the
   simple "no leading underscore" filter, so `_exit` stays hidden.

### Choice
Alternative 1. The spec states one rule for public names and orders `__all__` ahead of the
underscore heuristic without restricting it to project files; `os.__all__` genuinely exports
`_exit`. (This supersedes the earlier round's assertion that `from os import *` hides `_exit`; the
test in `test_sith.py` is annotated accordingly.)

### Risk: 30
The author most likely prefers: `__all__` honoured everywhere as chosen; the divergence is an
implementation that applies `__all__` only where it parses source and uses `dir()` filtering for
live modules, in which case `_exit` is absent.

---

## T44. `__all__` entries that the module does not define

### Spec Text
> - The module defines `__all__`: use exactly those names.

### Alternatives
1. Take `__all__` literally: every listed name is exported, even one with no binding in the module
   (it completes, but `infer` on it yields nothing).
2. Intersect `__all__` with the names actually defined, dropping the rest.

### Choice
Alternative 1 -- "exactly those names" is unconditional, and a name listed in `__all__` but produced
dynamically (or lost to a tolerated syntax error) is still the module's declared interface.

### Risk: 20
The author most likely prefers: the literal list as chosen; an implementation that resolves each
name first and skips misses would differ only on a deliberately broken `__all__`.

---

## T45. Default `goto` on a name imported from an unresolvable module

### Spec Text
> 3. If a module cannot be found, treat it as unresolvable — `infer` and `goto` return empty results, completions return nothing for that module's attributes.

> Without `--follow-imports` (default), `goto` on an imported name returns the `import` statement itself

### Alternatives
1. The two rules cover different questions: default `goto` always reports the import site (it never
   needed to resolve the module at all), while "empty results" describes what resolving *through*
   the module yields -- attribute goto, and the followed target.
2. An unresolvable module poisons the binding: `goto x` on `from nope import x` returns `[]`.

### Choice
Alternative 1. The `--follow-imports` section says explicitly that an unfindable module still
returns "the import statement as a fallback"; returning `[]` for the weaker, non-following form
while the following form returns a location would be backwards. `infer` does return `[]`, and so
does goto on `nope.attr`.

### Risk: 25
The author most likely prefers: the import statement as chosen; the divergence would be an
implementation that resolves the module eagerly and yields nothing when it fails.

---

## T46. `--follow-imports` on a module name

### Spec Text
> With `--follow-imports`, `goto` follows the import chain and returns the actual definition in the source module

### Alternatives
1. `goto` on `lib` in `import lib` reports the *module* `lib.py` itself (`type: "module"`,
   `module_path: "lib.py"`, line/column `0`, per T32).
2. It keeps reporting the import statement, since a module has no "definition".

### Choice
Alternative 1: the module file is the thing the import chain leads to, and reporting it is what
makes `--follow-imports` useful for `import x` as well as `from x import y`. The position stays the
`0`/`0` placeholder fixed by T32.

### Risk: 35
The author most likely prefers: the module file as chosen, but with `line: 1, column: 0` if their
module definitions use the file's start position instead of the placeholder.

---

## T47. Qualified names of modules below the project root

### Spec Text
> The project root determines:
> - The base for computing module qualified names.

### Alternatives
1. A module's name is its dotted path from the project root: `pkg/sub/mod.py` → `pkg.sub.mod`, and a
   package's `__init__.py` → `pkg`; `full_name` of a class in it is `pkg.sub.mod.Thing`.
2. The previous round's rule survives: the module name is the bare filename stem (`mod`), and only
   `module_path` reflects the directory structure.

### Choice
Alternative 1 -- this bullet is the only new thing the spec says about qualified names, and the bare
stem would not need a project root to compute. `name` of a module definition stays the bound
identifier (`mod`), not the dotted form.

### Risk: 15
The author most likely prefers: dotted module names as chosen; a stem-only implementation would
differ on `full_name` for names defined inside packages.

---

## T48. Shape of import-statement completion contexts

### Spec Text
> Completion now handles import statements:
> - `import ...` suggests top-level module/package names.
> - `from X import ...` suggests names inside module `X`.

> Import completions use the same ordering rules (public → private → dunder) and prefix matching as name completions.

### Alternatives
1. Only the four literal shapes listed are special-cased; anything else in an import line falls back
   to ordinary name completion (locals, builtins, keywords).
2. The whole import statement is an import context: comma-separated lists (`from lib import a, b|`),
   parenthesised lists, relative module references (`from .mod import |`), dotted module completion
   (`import pkg.|`), and `from X|` all complete against modules/exports, while positions where no
   module name can go (after `as`, after `*`) complete nothing. Keywords and builtins never appear.

### Choice
Alternative 2. The listed shapes are examples of a context, not an enumeration of supported
syntax, and offering local variables or the keyword `class` after `import` would be plainly wrong.
`--fuzzy` keeps working, since the spec says prefix matching behaves "as name completions".

### Risk: 15
The author most likely prefers: the same handling for the listed shapes (where fixtures will
concentrate); divergence is likely only on the exotic positions -- `as` clauses, `import a, b|`.

---

## T49. Does `__all__` restrict *attribute* completion on a module?

### Spec Text
> Attribute completion now works for imported names

> In `from X import ...` completion, exported names come from `__all__` when it exists; otherwise use names that do not start with `_`.

### Alternatives
1. `__all__` is scoped to what the spec names it for -- star imports and `from X import ...`
   completion. `mod.<TAB>` keeps the previous round's rule: every non-underscore module-level name
   (plus, for a package, its submodules).
2. `__all__` filters every view of the module, including attribute access.

### Choice
Alternative 1. The clarification attaches `__all__` to `from X import` completion specifically, and
attribute access in Python is not limited by `__all__`, so a module that exports a curated subset
would otherwise lose completions for names it genuinely has.

### Risk: 20
The author most likely prefers: unrestricted attribute completion as chosen; the divergence needs a
fixture with an `__all__` narrower than the module's public names, queried through `mod.<TAB>`.

---

## T50. What counts as a namespace package

### Spec Text
> The same import rules apply to regular packages and namespace packages.

### Alternatives
1. Any directory under the search path whose name is an identifier acts as a namespace package
   (this is what CPython does), so `data/` with a `loader.py` inside makes `data.loader` importable.
2. Only directories that contain at least one `.py` file (or nested package) count, to avoid
   treating incidental folders as packages.

### Choice
Alternative 1: it is the actual import-system rule the spec defers to, and it keeps resolution
consistent with what a `python -c "import data.loader"` in the project root would do.
`__pycache__` and non-identifier names are still skipped.

### Risk: 20
The author most likely prefers: the CPython rule as chosen; a divergence would show up as extra
entries in `import |` completion for projects with non-code directories.

---

## T51. `--follow-imports` and attribute `goto`

### Spec Text
> `--follow-imports` follows the import chain to the final definition.

### Alternatives
1. The flag affects any `goto` whose target turns out to be an import binding, including attribute
   goto: `mid.Thing` where `mid.py` does `from base import Thing` lands in `base.py`.
2. The flag only applies when the cursor is on a plain name.

### Choice
Alternative 1 -- the flag is described in terms of the import chain, not the cursor's syntactic
shape, and stopping at a re-export line would contradict "the final definition".

### Risk: 15
The author most likely prefers: following in both cases as chosen; without the flag both forms
already behave identically, so only a re-export fixture through an attribute would tell them apart.

---

## T52. Where the `--follow-imports` fallback points when the chain dead-ends further away

### Spec Text
> With `--follow-imports`, if the terminal target cannot be resolved, return the import site in the current file as the fallback definition.

> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib), return the import statement as a fallback.

### Alternatives
1. The fallback is always the import statement in the file under the cursor, however many hops the
   chain managed before failing: `main.py: from relib import getcwd` where `relib.py` does
   `from os import getcwd` reports `main.py` line 1.
2. The fallback is the last import statement the chain reached -- `relib.py` line 1 -- since that is
   the nearest thing to a definition the tool actually found.

### Choice
Alternative 1, which is what "the import site in the current file" says. A hop that is itself an
unfollowable import therefore contributes nothing, and the chain as a whole fails back to the
cursor's own file; a hop that resolves to a real binding (a `def`, `class` or assignment) is
returned as usual.

### Risk: 30
The author most likely prefers: the current file as chosen (the clarification is explicit); the
divergence would be an implementation that returns the deepest import statement it reached, which
only differs for chains of two or more hops ending outside the project.

---

## T53. The JSON key each new subcommand prints its payload under

### Spec Text
> ### `signatures`
> If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0).

> ### `references`
> ### `search`
> Each result has the same fields as a definition object (from `infer`/`goto`), minus `docstring`.

> ### `names`
> Each entry has the definition fields plus `is_definition` (always `true` for this command).

### Alternatives
1. Each command names its array after itself: `{"signatures": [...]}`, `{"references": [...]}`,
   `{"results": [...]}`, `{"names": [...]}`.
2. Since `search`/`names` emit definition objects, they reuse the existing `{"definitions": [...]}`
   envelope of `infer`/`goto`.
3. A uniform `{"results": [...]}` for all four.

### Choice
Alternative 1 for the primary key: the spec only ever names one array outright ("an empty
signatures array"), and naming the payload after the subcommand is the pattern `complete` →
`completions` and `infer`/`goto` → `definitions` already establish. Because `search` has no
noun of its own, `results` is used (the spec's own word: "Each result has ...").
To stay compatible with the second reading at zero cost, `search` and `names` *also* emit a
`definitions` alias holding the identical list, so a consumer reading either key works.

### Risk: 30
The author most likely prefers: `{"signatures"/"references"/"results"/"names": [...]}` (the same
primary keys chosen here); the residual risk is a test asserting the exact key *set* of the
`search`/`names` payloads, which the alias would break.

---

## T54. Whether `params` excludes `self`, or only `description` does

### Spec Text
> | `description` | string | `"def name(params)"` for functions without return annotation, or `"def name(params) -> ReturnType"` when the function has a return type annotation. The `self` parameter is excluded for methods. |

### Alternatives
1. The exclusion applies to the whole signature object: `params` omits `self` and `index` is an
   offset into that trimmed list.
2. The exclusion is literally a property of the `description` string only; `params` still starts
   with `"self"` and `index` counts it.

### Choice
Alternative 1. `index` is documented as "0-based index of the parameter the cursor is currently
on" -- i.e. an index into `params` -- and at a bound-method call site `obj.m(<|>)` the cursor is on
the first *user-supplied* argument. If `params` kept `self`, `index` would have to be 1 there,
which no signature-help UI wants. Keeping `params` and `description` derived from the same trimmed
list is also the only way they stay consistent. `cls` on a `classmethod` is trimmed the same way,
since it is bound identically.

### Risk: 20
The author most likely prefers: `self` trimmed from `params`, `index` and `description` alike (this
choice); the residual risk is that `cls` is kept because the spec names only `self`.

---

## T55. The `/` and `*` marker "parameters"

### Spec Text
> | `params` | array of string | Parameter representations. Each param is rendered as: `"name"` for bare parameters ... Special forms: `"*args"`, `"**kwargs"`, `"*args: type"`, `"**kwargs: type"`. |

### Alternatives
1. Only real parameters appear; the positional-only marker `/` and the bare keyword-only marker `*`
   are dropped, so `def f(a, /, b, *, c)` renders `["a", "b", "c"]`.
2. They are rendered as the literal strings `"/"` and `"*"`, mirroring `inspect.signature`.

### Choice
Alternative 1. The table enumerates the renderings exhaustively ("Each param is rendered as ...",
plus a closed list of "Special forms") and neither marker is among them; `index` is also documented
as the index of "the parameter the cursor is currently on", which a marker can never be.

### Risk: 25
The author most likely prefers: dropping the markers (this choice); the residual risk is an
implementation that formats via `str(inspect.signature(...))`-style logic and keeps them.

---

## T56. `signatures` on a class (constructor call)

### Spec Text
> | `name` | string | Function or class name. |

### Alternatives
1. A call whose callee is a class yields one signature: the class name, `__init__`'s parameters
   minus `self`, and `description` `"def Name(params)"`.
2. Classes yield nothing (only functions have signatures).
3. The description uses a different lead-in for classes, e.g. `"class Name(params)"`.

### Choice
Alternative 1: `name` is explicitly allowed to be a "class name", so a constructor call must produce
a signature, and the `description` row offers only the `def ...` form, so that form is used with the
class's own name. The docstring reported is the class docstring when it has one, otherwise
`__init__`'s -- that is the string a user hovering over `Thing(` wants. A class without an
`__init__` (including one inheriting it) yields an empty parameter list unless a base defines one.

### Risk: 40
The author most likely prefers: class name + `__init__` params, `description` `"def Name(params)"`
(this choice); the residual risk sits in the docstring source, where `__init__.__doc__` is an
equally natural pick.

---

## T57. `index` when the current argument is a `*` / `**` unpacking

### Spec Text
> `index` follows Python-style call binding at the cursor position ... `null` if the cursor is past all parameters or in an ambiguous position.

### Alternatives
1. `f(*rest, <|>)` / `f(**kw<|>)`: the cursor is in an "ambiguous position" (an unpacking binds an
   unknown number of parameters), so `index` is `null`.
2. `*rest` counts as exactly one positional argument and `**kw` as a `**kwargs` match.

### Choice
Alternative 1. "in an ambiguous position" has no other obvious referent in the spec, and an
unpacking really does make the binding unknowable statically. A positional argument that *follows*
a `*` unpacking is treated as ambiguous for the same reason.

### Risk: 35
The author most likely prefers: `null` for the unpacking itself (this choice); the residual risk is
an implementation that just counts commas and so reports a concrete index.

---

## T58. Where "inside a call's argument list" begins and ends

### Spec Text
> When the cursor is inside a function call's argument list ... If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0).

### Alternatives
1. "Inside the parentheses" is decided by bracket balance in the text before the cursor: the cursor
   is inside the innermost call `(` that is still open. A cursor on the callee (`f<|>(x)`) or after
   the closing paren (`f(x)<|>`) is outside.
2. Only a cursor directly inside the *innermost* bracket of any kind counts, so `f([1, <|>])` (inside
   a list display inside the argument list) is "not inside a call's parentheses".
3. Any cursor anywhere within the call expression's source range counts, callee included.

### Choice
Alternative 1, with the refinement that non-call brackets are skipped outwards: the innermost still
open `(` whose preceding text forms a callable expression is the call. So `f([1, <|>])` reports `f`
with `index` 0 (the bracketed comma is not a top-level argument separator), `g(f(<|>))` reports `f`,
and `x = [<|>]` reports nothing. This is what every editor's signature help does and the only
reading under which nested calls behave sensibly.

### Risk: 30
The author most likely prefers: innermost open `(` with a callee (this choice); the residual risk is
a stricter implementation that bails out as soon as any other bracket is open.

---

## T59. Whether `--scope file` also filters by symbol identity

### Spec Text
> - `--scope file` (default): search only within the target file.
> - `--scope project`: search all `.py` files in the project.
>
> For project-scope search, return only occurrences that resolve to the same symbol identity as the cursor target (do not include same-spelling but unrelated symbols in other scopes).

### Alternatives
1. Identity filtering is the behaviour of `references` generally; the sentence singles out project
   scope only because that is where same-spelling collisions are most visible. `def a(x): return x`
   / `def b(x): return x` with the cursor on `a`'s `x` yields the two occurrences in `a`.
2. File scope is a plain same-spelling scan, and identity resolution kicks in only when
   `--scope project` is passed -- so the example above yields all four `x` occurrences.

### Alternatives (cont.)
Reading 2 makes the default scope report locals of unrelated functions, which contradicts the
parenthetical "do not include same-spelling but unrelated symbols in other scopes" as a statement of
intent rather than of scope-specific mechanics.

### Choice
Alternative 1: one resolution path for both scopes, differing only in the set of files walked.

### Risk: 35
The author most likely prefers: identity filtering in both scopes (this choice); the residual risk
is a deliberately cheap file-scope implementation that matches on spelling alone.

---

## T60. Exit status of `references` when the cursor is not on a name

### Spec Text
> Find all locations where the name at the cursor is referenced (used or defined).

### Alternatives
1. Same as `infer`/`goto`: "If the cursor is not on a name, exit 1."
2. Same as `signatures`: an empty array and exit 0.

### Choice
Alternative 1. `references` is, like `infer`/`goto`, defined in terms of "the name at the cursor",
so the absence of a name is the same error condition; `signatures` got an explicit exit-0 carve-out
precisely because it is *not* defined that way.

### Risk: 30
The author most likely prefers: exit 1 (this choice); the residual risk is a uniform "new commands
never fail" policy returning an empty array.

---

## T61. What identifies "the same symbol" across positions and files

### Spec Text
> return only occurrences that resolve to the same symbol identity as the cursor target

### Alternatives
1. Identity = the (file, scope, name) the occurrence binds to, followed through imports to the
   origin. Rebinding a module global (`x = 1` ... `x = 2`) does not split it into two symbols.
2. Identity = the single definition site (`module_path`, `line`, `column`) that `goto` would report
   at that position. Under this reading `x = 2` later in the file is a *different* symbol from `x =
   1`, since a cursor on the later use resolves only to the later assignment.

### Choice
Alternative 1. "Find all locations where the name at the cursor is referenced (used or defined)"
plainly wants every occurrence of the one variable, and reading 2 would make `references` on a
reassigned variable silently drop half of its own occurrences. Import bindings contribute both their
local (file, scope, name) and the origin's, so a name imported into several modules links them all.

### Risk: 20
The author most likely prefers: scope-based identity (this choice); the residual risk is an
implementation built directly on top of `goto` and therefore definition-site based.

---

## T62. Attribute references

### Spec Text
> Find all locations where the name at the cursor is referenced (used or defined).

### Alternatives
1. A cursor on `obj.attr` reports occurrences of the *attribute* `attr` -- other accesses whose
   receiver resolves to the same class, `self.attr` assignments, and the `def`/assignment in the
   class body -- and never plain variables spelled `attr`.
2. Attribute occurrences are matched on spelling alone, so any `.attr` anywhere matches.
3. Attributes are out of scope; only bare names are supported.

### Choice
Alternative 1, with a fallback to spelling-only matching when the receiver cannot be resolved (an
unresolvable receiver otherwise yields no references at all, which is strictly less useful). This is
the same identity rule as for bare names, just reached through the receiver's class.

### Risk: 35
The author most likely prefers: attribute support with class-based identity (this choice); the
residual risk is spelling-only attribute matching.

---

## T63. What `search` counts as a searchable name

### Spec Text
> - Search all `def`, `class`, and top-level assignment names across project files.
> - Do not search inside function/method bodies (local variables are not searchable).

### Alternatives
1. Module-level `def`/`class`/assignments, plus everything in *class* bodies (methods, nested
   classes, class attributes) -- the second bullet excludes function bodies specifically, which
   implies class bodies are included. Imported names are not "def, class, or assignment" names and
   are excluded.
2. Module level only: a method is not a "top-level" name either.
3. As 1, but imports are included too (a `from x import y` does bind a module-level name).

### Choice
Alternative 1. The exclusion bullet names "function/method bodies" only, which would be a strange
thing to write if class bodies were already out; and `search` is meant to find `Calculator` *and*
`recalculate`, i.e. a method. Imports are excluded because the bullet lists exactly three
constructs and an import is none of them -- and because `names` separately and explicitly *does*
include imports, a distinction that is only meaningful if `search` does not.

### Risk: 30
The author most likely prefers: module level + class bodies, no imports (this choice); the residual
risk is that their scanner walks every binding it has and so includes imports.

---

## T64. `--all-scopes` and `self.x` attributes

### Spec Text
> - `--all-scopes`: include names from all scopes (locals inside functions, class attributes, nested defs).

### Alternatives
1. "Class attributes" means names bound in the class body; `self.x = ...` inside `__init__` is a
   local statement about an attribute, not a name in a scope, and is not listed.
2. `self.x = ...` targets are listed too, since they are how instance attributes are usually created.

### Choice
Alternative 1. The parenthetical lists *scopes* ("locals inside functions, class attributes, nested
defs"), and `names` is documented as listing "names defined in a file" with a `column` -- a dotted
attribute target is not a name binding in any scope. Function locals already cover the statement
itself.

### Risk: 30
The author most likely prefers: class-body names only (this choice); the residual risk is that their
`--all-scopes` walk reuses the same instance-attribute collection that powers `complete`.

---

## T65. Repeated bindings in `names`

### Spec Text
> List names defined in a file. ... Sort by `(line, column)` ascending.

### Alternatives
1. Every binding occurrence is an entry, so `x = 1` / `x = 2` yields two entries. Sorting by line
   and column only makes sense if several entries can share a name.
2. One entry per distinct name (the last, or the first, binding).

### Choice
Alternative 1: the command lists definitions, and both assignments define `x`. `is_definition` being
"always `true` for this command" also reads like "every entry is a definition site".

### Risk: 25
The author most likely prefers: one entry per binding occurrence (this choice); the residual risk is
a dict-keyed implementation that collapses duplicates.

---

## T66. Whether a stub replaces or augments the module's names

### Spec Text
> If a stub exists, type information (function signatures, return types, class attributes) comes from the stub. The runtime `.py` file is still used for `goto` (source navigation).
> - `complete` uses type annotations from the stub for attribute completion.

### Alternatives
1. The stub supplies *types*, not the name list: completing `mod.` lists the union of the stub's and
   the runtime module's names, with the stub winning wherever both define a name.
2. The stub fully replaces the module: only names declared in the stub are visible.

### Choice
Alternative 1. The spec is careful to say what comes from the stub -- "type information (function
signatures, return types, class attributes)" -- and separately that `goto` still uses the `.py`
file, which only makes sense if `.py` definitions remain first-class. A partial stub (the common
real-world case) would otherwise hide most of a module.

### Risk: 35
The author most likely prefers: union with stub precedence (this choice); the residual risk is a
"stub shadows the module entirely" implementation, which is how a type checker treats stubs.

---

## T67. Whether `.pyi` files are themselves searched by `search` / `references`

### Spec Text
> - `--scope project`: search all `.py` files in the project.
> - Search all `def`, `class`, and top-level assignment names across project files.

### Alternatives
1. Only `.py` files are walked; stubs are type metadata, not project source. `references` says
   `.py` outright, and `search` is read the same way for consistency.
2. `.pyi` files are walked too, so stub-only declarations are searchable and referenceable.

### Choice
Alternative 1. `references` states `.py` explicitly, and having `search` disagree with it about what
"the project" contains would be surprising. A stub-only module is still reachable through `goto`
(where the spec does call it out), just not enumerated.

### Risk: 20
The author most likely prefers: `.py` only (this choice); the residual risk is a glob over `*.py*`
or a "stub-only definitions are still findable" refinement.

---

## T68. Stub lookup for modules inside packages

### Spec Text
> For a module `foo`, the tool looks for type stubs in this order:
> 1. `foo.pyi` adjacent to `foo.py` (inline stub).
> 2. A `stubs/` directory in the project root: `stubs/foo.pyi` or `stubs/foo/__init__.pyi`.

### Alternatives
1. `foo` is the module's dotted name, so `pkg/mod.py` looks for `pkg/mod.pyi`, then
   `stubs/pkg/mod.pyi`, then `stubs/pkg/mod/__init__.pyi`. A package's `pkg/__init__.py` looks for
   `pkg/__init__.pyi`, then `stubs/pkg.pyi`, then `stubs/pkg/__init__.pyi`.
2. `foo` is the bare file stem, so `pkg/mod.py` would look for `stubs/mod.pyi`.

### Choice
Alternative 1: the two `stubs/` spellings the spec gives are exactly the module-vs-package pair that
a dotted name produces, and flattening `pkg.mod` to `mod` in a shared `stubs/` directory would make
collisions between same-named modules unavoidable.

### Risk: 15
The author most likely prefers: dotted-path lookup under `stubs/` (this choice).

---

## T69. What "affects `signatures`" means for dynamic parameter inference

### Spec Text
> When a function has no type annotations and no stub, the tool can optionally infer parameter types by finding call sites. This is enabled by default and affects `infer` and `signatures`. Do not search other files for call sites.

### Alternatives
1. Inference gives unannotated parameters a *type*, which `infer` reports directly and which
   `signatures` benefits from indirectly: inside `def outer(thing): thing.method(<|>)`, knowing from
   `outer(Widget())` that `thing` is a `Widget` is what lets `signatures` find `method` at all. The
   rendered `params` strings stay purely syntactic.
2. Inferred types are spliced into the rendered parameters, so `def f(x)` called as `f(1)` renders
   `["x: int"]`.

### Choice
Alternative 1. The `params` table defines the renderings as a closed syntactic mapping -- `"name"`
for bare parameters, `"name: type"` for *annotated* ones -- so an unannotated parameter must render
bare or that table is self-contradictory. Reading 1 also explains the sentence without breaking
anything, since parameter types are exactly what callable resolution needs.

### Risk: 40
The author most likely prefers: inference feeds resolution, renderings stay syntactic (this choice);
the residual risk is that their `signatures` does show inferred annotations, in which case a
fixture like `def f(x): ...` / `f(1)` would expect `["x: int"]`.

---

## T70. The switch that turns dynamic parameter inference off

### Spec Text
> This is enabled by default and affects `infer` and `signatures`.

### Alternatives
1. "Enabled by default" implies an opt-out flag, but the spec never names one, and neither the
   `infer` nor the `signatures` usage line lists one -- so no flag is required and the behaviour is
   simply always on.
2. Some specific flag spelling (`--no-dynamic`, `--no-dynamic-params`, ...) must be accepted.

### Choice
Behaviour follows alternative 1 (always on, matching the documented usage lines), but because an
unknown `--` option is a hard error in this tool, the plausible opt-out spellings `--no-dynamic`,
`--no-dynamic-params`, `--no-call-sites` and `--no-infer-params` are accepted and do disable it.
That way a test exercising either the default or an opt-out flag behaves sensibly.

### Risk: 15
The author most likely prefers: always on, no flag (the behaviour chosen here).

---

## T71. Default project root for `search`

### Spec Text
> python sith.py search <query> [--project <dir>]

### Alternatives
1. `--project` defaults to the current working directory -- there is no `<file>` argument to take a
   directory from, and every other command's default ("the directory holding `<file>`") is
   unavailable.
2. It is required for `search`.

### Choice
Alternative 1: the flag is written as optional, so it must have a default, and the process's own
directory is the only sensible one.

### Risk: 10
The author most likely prefers: cwd (this choice).

---

## T72. `index` for a keyword argument written as a bare prefix

### Spec Text
> - Keyword arguments map to the matching declared parameter when present.
> - Unknown keyword arguments map to `**kwargs` when available, otherwise `index` is `null`.

### Alternatives
1. A segment counts as a keyword argument only once `=` has been typed (`f(ke<|>)` is still a
   positional argument being typed, `f(key=<|>)` is the keyword `key`).
2. A bare identifier that prefixes a parameter name is treated as that keyword already.

### Choice
Alternative 1. The binding rules quoted are Python's, and in Python `f(ke)` *is* a positional
argument; nothing in the text hints at prefix matching, which would also make `f(x<|>)` ambiguous
with a variable named `x`.

### Risk: 10
The author most likely prefers: `=` required (this choice).

---

## T73. Which callables produce more than one signature

### Spec Text
> Multiple signatures are returned when the callable has overloads or when the name resolves to multiple possible functions. Sort by `(module_path, line)`.

### Alternatives
1. "Overloads" means `@overload`-decorated `def`s (in a stub or in source): all of them are
   reported even though a plain later `def` would shadow an earlier one. "Multiple possible
   functions" means a name bound differently on different branches, or an attribute found on
   several types of a union receiver.
2. Every `def` of the same name is reported, `@overload` or not.

### Choice
Alternative 1. `@overload` is the only thing in Python the word "overloads" can mean, and it is
precisely the case where the normal "last binding wins" rule must be suspended; unrelated
re-definitions are genuinely shadowed and reporting the dead one would be wrong.

### Risk: 25
The author most likely prefers: `@overload` plus union/branch resolution (this choice); the residual
risk is an implementation that reports every same-named `def` in the scope.

---

## T74. `is_definition` for import statements

### Spec Text
> | `is_definition` | bool | `true` if this is the defining occurrence (assignment, `def`, `class`, import). |

### Alternatives
1. The occurrence of the bound name in an `import` line is a definition (the spec lists "import"
   outright), so `from mod import foo` marks `foo` at its column with `is_definition: true`, and the
   real `def foo` in `mod.py` is a definition as well -- a symbol can have several.
2. Only one occurrence in the whole result set may be flagged.

### Choice
Alternative 1: the field is documented per-occurrence, and "import" is explicitly one of the
defining forms, so an imported-and-defined symbol legitimately has two flagged occurrences.

### Risk: 15
The author most likely prefers: per-occurrence flag, imports included (this choice).

### Amendment to T73
When `@overload` declarations are found for a callable, the untyped implementation `def` that
follows them is *not* reported: an editor showing three signatures for a two-way overload would be
wrong, and the implementation is not a callable shape any caller is allowed to rely on. Overloads
therefore replace, rather than join, the shadowing definition. Residual risk on this point alone is
about 30: an implementation that simply unions "all live bindings plus every `@overload`" would
report three.

### Amendment to T58
A `(` that opens a `def` or `class` header is never a call: `def f(<|>)` and `class Kid(<|>Base)`
return an empty array rather than the signature of whatever `f`/`Kid` happens to name elsewhere.
The spec's wording is "inside a function *call*'s argument list", and reporting a class's own
constructor while the cursor is in its base list would be plainly wrong.
