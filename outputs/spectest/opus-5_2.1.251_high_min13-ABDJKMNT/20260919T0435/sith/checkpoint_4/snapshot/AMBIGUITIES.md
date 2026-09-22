# Ambiguities

Interpretation decisions taken while implementing `sith.py`. Each entry quotes the
spec, lists the readings that would produce different observable behaviour, records
the choice, and estimates the chance the spec author's own implementation differs.

---

## T1. Visibility on the defining line itself

### Spec Text
> "A `def` or `class` statement makes its name visible from the line of the `def`/`class`
> keyword. An assignment makes the name visible from the line of the assignment."

### Alternatives
1. `definition_line <= cursor_line` — the name is visible *on* its own line.
2. `definition_line < cursor_line` — the name only becomes visible on the following line.

### Choice
(1). "visible **from** the line of the `def`" reads as inclusive of that line, and it is
the behaviour an editor needs: while typing `def helpe|` you want `helper` offered as
soon as the statement exists. Applied identically to assignments.

### Risk: 5
Author most likely prefers: the same inclusive comparison.

---

## T2. Description for parameters

### Spec Text
> "| `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`,
> `param`, `keyword`. |"
> "| `description` | string | A short description. For functions: `def name(...)`. For
> classes: `class Name`. For imports: `module name`. ... For keywords: the keyword itself. |"

### Alternatives
1. `param <name>`, mirroring `module <name>` / `class <Name>`.
2. The literal word `parameter`.
3. `statement`, reusing the catch-all.
4. `instance of <annotation>` when the parameter is annotated.

### Choice
(1) `param <name>`. The description table is a per-kind lookup and every other kind
formats as `<kind-word> <name>`; `param` is listed as a first-class `type`, so it
almost certainly has its own matching description rather than falling through to the
assignment fallback.

### Risk: 45
Author most likely prefers: `parameter` as a bare constant word.

---

## T3. Description of a `from ... import` whose object cannot be inferred

### Spec Text
> "For imports: `module name`."
> "For imported names (from import statements), the `type` reflects the imported object's
> actual kind if inferable (e.g., `function`, `class`, `module`). If not inferable, use
> `statement`."

### Alternatives
1. Description follows the resolved `type`: an import resolved to a function is described
   `def name(...)`, an unresolvable one is described `statement`.
2. Description is always `module <name>` for any import statement, independent of `type`.

### Choice
(1). The description table is keyed by kind, and the import paragraph explicitly says an
imported name's kind *is* `function`/`class`/`module`; a name typed `function` described
as `module x` would contradict the "For functions" row. `import os` still yields
`module os` because `os` genuinely is a module.

### Risk: 40
Author most likely prefers: `module <name>` for every import node, since the description
is easiest to emit at the point the `Import`/`ImportFrom` node is visited.

---

## T4. `True` / `False` / `None` appear as both builtins and keywords

### Spec Text
> "**Builtin scope** — builtin names provided by Python's `builtins` module."
> "When in a name-completion context, also include Python keywords as completions."
> "4. **Keywords** — sorted alphabetically after all names."

### Alternatives
1. Emit both entries: `True` as a builtin name (group 1) and `True` as a keyword (group 4).
2. Suppress the keyword entry when a name of the same spelling is already present.
3. Suppress the builtin entry for names that are keywords.

### Choice
(1). `dir(builtins)` contains `True`/`False`/`None` and `keyword.kwlist` contains them
too; the spec describes names and keywords as separate, separately-sorted groups and
never mentions de-duplication between them. Shadowing de-duplication *is* applied within
the LEGB name chain, where the spec does say scopes are "checked in order".

### Risk: 30
Author most likely prefers: the same duplicated output (naive concatenation).

---

## T5. Which attributes a builtin type exposes

### Spec Text
> "**Literals** — string/list/dict/set literals expose attributes appropriate to their
> inferred builtin type."
> "**Modules** — ... return the module's public names. A name is public if it does not
> start with `_`."

### Alternatives
1. Everything in `dir(str)`, dunders included; the public/private/dunder ordering groups
   then separate them.
2. Public names only, applying the module rule to every receiver.

### Choice
(1). The `_`-prefix filter is stated only for modules, and the ordering section defines a
dedicated dunder group that would otherwise be nearly unreachable. `dir(type)` is also
the obvious implementation of "attributes appropriate to their inferred builtin type".

### Risk: 30
Author most likely prefers: the same unfiltered `dir()`.

---

## T6. Soft keywords

### Spec Text
> "also include Python keywords as completions."

### Alternatives
1. `keyword.kwlist` only (35 hard keywords).
2. `keyword.kwlist + keyword.softkwlist` (adds `_`, `case`, `match`, `type`).

### Choice
(1). "Python keywords" without qualification is `keyword.kwlist`; soft keywords are
context-dependent identifiers and adding `_` in particular would pollute the private
group of every result.

### Risk: 20
Author most likely prefers: `kwlist` alone.

---

## T7. Class bodies in the lookup chain

### Spec Text
> "2. **Enclosing scopes** — names from enclosing functions (for nested functions/closures)."

### Alternatives
1. Follow Python semantics: a class body is not in the lookup chain of methods defined
   inside it, so `class_attr` is not a bare-name completion inside `def method(self)`.
2. Treat every syntactic ancestor as an enclosing scope, so class attributes leak into
   method bodies.

### Choice
(1). The spec says "enclosing **functions**", which matches Python's actual rule. A class
body is still used as the *local* scope when the cursor sits directly in it.

### Risk: 25
Author most likely prefers: (2), if their scope walk is purely syntactic.

---

## T8. Description of an aliased import

### Spec Text
> "For imports: `module name`."

### Alternatives
1. `module <bound name>` — `import numpy as np` yields `module np`.
2. `module <source module>` — yields `module numpy`.

### Choice
(1). Every other description in the table interpolates the completion's own `name` field
(`def name(...)`, `class Name`), so `name` here is the bound name that the user would
actually insert.

### Risk: 30
Author most likely prefers: the bound name as well, but `alias.name` is equally easy to
reach for when visiting the node.

---

## T9. Position filtering in enclosing (non-global) function scopes

### Spec Text
> "A name is visible only if it is defined **before** the cursor position in the source
> (for the local and global scopes)."

### Alternatives
1. Filter only the immediately enclosing scope and the module scope; intermediate
   function scopes contribute all of their names regardless of line.
2. Filter every scope by line.

### Choice
(1), reading the parenthetical as an exhaustive list. This also matches closure
semantics: a nested function body runs after its enclosing function has finished binding
its locals.

### Risk: 10
Author most likely prefers: the same, given the parenthetical is explicit.

---

## T10. Line count of a file, and empty files

### Spec Text
> "If the position is out of range (line exceeds file length, or column exceeds line
> length), exit 1."

### Alternatives
1. Line count is `len(text.splitlines())`, with an empty file treated as one empty line,
   so `1 0` is valid on an empty file and the position after a file's trailing newline is
   out of range.
2. A trailing newline starts a further addressable (empty) line.

### Choice
(1). `splitlines()` is the natural measure of "file length"; special-casing the empty file
to one empty line keeps `sith.py complete empty.py 1 0` answerable, which is what an
editor asks for when a new buffer is opened.

### Risk: 25
Author most likely prefers: `splitlines()` too, but may exit 1 on a completely empty file.

---

## T11. `self` inside a method

### Spec Text
> "**Instances** — if `foo` is an instance (from `foo = MyClass()`), return the same
> attributes as the class plus any attributes assigned in `__init__` via `self.name = ...`."

### Alternatives
1. `self` in a method body resolves to an instance of the enclosing class, so `self.`
   completes instance attributes.
2. `self` is only a parameter with no inferable type, so `self.` yields nothing.

### Choice
(1). It is the single most common attribute completion in real editing, and the spec's own
instance rule (class attributes plus `__init__` assignments) is exactly what it needs.
`self` keeps `type: param` as a bare-name completion.

### Risk: 15
Author most likely prefers: (1); (2) would make their own `__init__` self-attribute
collection hard to exercise.

### Update (type inference and navigation spec)
Confirmed. `isinstance` narrowing is specified for `infer` as well as `complete`, and
"infer attributes from instance state" only means anything if `self` is the instance.

---

## T12. Names starting with `__` but not ending with `__`

### Spec Text
> "2. **Private names** (start with `_` but not `__`) ... 3. **Dunder names** (start with
> `__` and end with `__`)"

### Alternatives
1. `__mangled` (no trailing underscores) joins the private group.
2. It forms a fourth, unspecified group.

### Choice
(1). The three name groups are presented as a partition of all names; the private group's
parenthetical is describing the common case rather than excluding `__mangled` into
nowhere.

### Risk: 12
Author most likely prefers: (1), typically via an `if name.startswith('_')` fallthrough.

---

## T13. `complete` under fuzzy matching

### Spec Text
> "`complete` ... The text that would be inserted — the name with the already-typed prefix
> removed. ... When prefix matching is case-insensitive, removal is by character count: the
> first `len(prefix)` characters of the matched name are stripped regardless of case."

### Alternatives
1. The character-count rule applies to fuzzy matches too: query `abg` against
   `alpha_beta_gamma` gives `ha_beta_gamma`.
2. Under fuzzy matching nothing is stripped, so `complete` equals `name`.

### Choice
(1). The rule is stated as an unconditional mechanical operation on `len(prefix)`, and a
single shared code path for both modes is the natural implementation.

### Risk: 30
Author most likely prefers: (1), but (2) is defensible since stripping is meaningless for
a non-contiguous match.

---

## T14. Inherited attributes from bases that are not in the file

### Spec Text
> "**Classes** — if `foo` is a class, return its methods and class attributes (including
> inherited ones from base classes defined in the same file)."

### Alternatives
1. Only in-file bases contribute; `object`'s dunders are not added to a plain
   `class Widget:`.
2. `object`'s methods are always included.

### Choice
(1), following the parenthetical literally. Imported bases and `object` are not traversed.

### Risk: 15
Author most likely prefers: (1); the parenthetical is explicit.

---

## T15. How much survives a syntax error

### Spec Text
> "Python syntax errors in the source file: **do not** exit with an error. Parse as much as
> possible and provide completions based on what was successfully parsed."

### Alternatives
1. Replace each unparsable line with an indentation-preserving `pass` and re-parse, so
   surrounding block structure (and every other binding in the file) survives.
2. Parse only the longest prefix of the file that is syntactically valid, discarding
   everything after the first error.
3. Parse each top-level block independently and keep the ones that parse.

### Choice
(1), with (3) as a last-resort fallback. The cursor line itself is stubbed first, because
the line being typed (`value = os.`) is the usual cause of the error and blanking it would
otherwise empty the function body it sits in. "as much as possible" favours recovering
bindings on both sides of the broken line, which (2) cannot do.

### Risk: 40
Author most likely prefers: (2), truncating at the error — simplest to write, and it loses
every name defined after the broken line.

---

## T16. Column equal to the line length

### Spec Text
> "`<col>` is 0-based (number of characters before the cursor on that line)." / "column
> exceeds line length"

### Alternatives
1. `col == len(line)` is valid (the cursor sits at end of line).
2. `col` must be strictly less than the line length.

### Choice
(1). "exceeds" means strictly greater, and completing at end of line is the overwhelmingly
common request.

### Risk: 5
Author most likely prefers: the same.

---

## T17. Which names a star import and a module receiver expose

### Spec Text
> "`from os import *` makes all public names from `os` visible."
> "if `foo` is an imported module, return the module's public names. A name is public if it
> does not start with `_`."

### Alternatives
1. `dir(module)` filtered to names not starting with `_`, for both star imports and
   attribute completion.
2. Honour `__all__` when the module defines one (Python's real star-import rule), falling
   back to the `_` filter.

### Choice
(1). The spec defines "public" exactly once, mechanically, as "does not start with `_`",
and reuses the word for both cases. Applying that single definition uniformly means
`from os import *` also exposes e.g. `sys`, which `os.__all__` omits.

### Risk: 30
Author most likely prefers: (1) for attribute completion; `__all__` is more plausible for
the star-import path specifically.

### Update (cross-file spec)
Settled, and split in two. "A name is public if: the module defines `__all__`: use exactly
those names. Otherwise: all names that do not start with `_`." now governs star imports, so
(2) is the rule there. Attribute completion on a module keeps the `_` filter of (1); see
[T42].

---

## T18. Instance attributes from methods other than `__init__`

### Spec Text
> "plus any attributes assigned in `__init__` via `self.name = ...`"

### Alternatives
1. Only `__init__` is scanned.
2. Every method is scanned for `self.x = ...`.

### Choice
(1), verbatim. `__init__` is also scanned on in-file base classes, since the instance
rule says an instance shows "the same attributes as the class", and class attributes are
explicitly inherited.

### Risk: 18
Author most likely prefers: (1) for the method restriction; inheriting `__init__`
attributes from bases is the less certain half.

### Update (type inference and navigation spec)
Still open, and now also covers where `goto` lands for an attribute; see T33.

---

## T19. Receiver expressions more complex than a dotted name

### Spec Text
> "When the cursor follows a `.`, return attributes of the value before the dot."

### Alternatives
1. Scan backwards over a general atom: dotted names, call results `f().`, subscripts
   `a[0].`, and literals `'abc'.`, `[1].`, `{}.`.
2. Scan backwards over dotted identifiers only, so `'abc'.` and `f().` yield nothing.

### Choice
(1). The spec explicitly requires literal receivers (`'abc'.upper`), which already forces
the scan past a non-identifier atom; handling calls and subscripts with the same bracket
matcher costs nothing and makes `MyClass().` behave like `MyClass()` assigned to a name.

### Risk: 20
Author most likely prefers: (1), as literals are called out in the spec.

---

## T20. Assignments whose right-hand side is a class, module or function

### Spec Text
> "For assignments: `instance of <type>` if the right-hand side is a literal, a constructor
> call, or otherwise resolvable to a known type; otherwise `statement`."

### Alternatives
1. The alias adopts the kind of what it names: `Alias = MyClass` is `class Alias`,
   `m = os` is `module m`, `f = print` is `def f(...)`.
2. Everything resolvable becomes an instance: `Alias = MyClass` is `instance of type`.
3. Only literals and constructor calls resolve; aliases are `statement`.

### Choice
(1). The `instance of` wording is about values whose *type* is known; a name bound to a
class is a class, and reporting `class Alias` keeps `type` and `description` consistent
with the rest of the table. Aliases of instances (`second = first`) still report
`instance of str`, which is what "otherwise resolvable to a known type" asks for.

### Risk: 35
Author most likely prefers: (3), leaving non-literal, non-call right-hand sides as
`statement`.

---

## T21. What `(params)` means in a function's description

### Spec Text
> "`description` | string | Short description. For functions: `def name(params)`."

### Alternatives
1. The real parameter list, written as in the source: `def add(self, x)`.
2. The literal placeholder used by the earlier completion spec: `def add(...)`.

### Choice
(1). The earlier spec wrote `def name(...)` verbatim where it meant a placeholder; this
table says `params` instead, which reads as the parameters themselves. Parameters are
unparsed from the signature, so defaults and annotations appear as written.

### Risk: 35
Author most likely prefers: (2), keeping one description format for completions and
definitions.

---

## T22. Description of an assignment

### Spec Text
> "For assignments: the right-hand expression or statement."

### Alternatives
1. The right-hand side alone: `total = 1 + 2` is described as `1 + 2`.
2. The whole statement: `total = 1 + 2`.
3. The right-hand side when there is one, the statement otherwise.

### Choice
(3), which is how the sentence reads with "or" separating the two cases: an assignment
with a value describes that value, while a binding with no right-hand side (a `for`
target, a `with` target, an `except ... as`, a bare annotation) falls back to the text of
the statement that binds it.

### Risk: 45
Author most likely prefers: (2), the whole statement text for every assignment.

---

## T23. The `type` of a `goto` result that lands on an assignment

### Spec Text
> "`goto` returns where the name at the cursor is assigned or defined (`def`, `class`,
> assignment, or import binding)."
> "`type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`."

### Alternatives
1. An assignment is a `statement`, whatever its right-hand side evaluates to.
2. The assignment reports the kind its value infers to, so `c = Calculator()` is
   `instance`, matching what completion says about the same name.

### Choice
(1). `goto` answers about the binding, not the value; `infer` is the command that reports
the value. Reserving `statement` for assignments also explains why the type list contains
it at all, and keeps `goto` and `infer` on a name usefully different.

### Risk: 30
Author most likely prefers: (2), reusing the inferred kind everywhere a name is described.

---

## T24. A cursor resting on a literal

### Spec Text
> "If the cursor is not on a name, exit 1."
> "### Literals — For literals, `infer` returns a definition pointing to the builtin type
> with `module_path` set to empty string and `line`/`column` set to 0."

### Alternatives
1. A literal is a legal cursor target: `infer` reports its builtin type and `goto`
   returns an empty array, both exiting 0.
2. A literal is "not a name", so both commands exit 1, and the Literals rule only ever
   applies through a name bound to a literal.

### Choice
(1). The Literals rule is stated as its own inference rule rather than as part of the
Assignments rule, which only makes a difference when the cursor is on the literal itself.
A literal is written where it stands, so it has no definition site and `goto` reports
nothing rather than failing.

### Risk: 25
Author most likely prefers: (2), treating anything that is not an identifier as a miss.

---

## T25. A cursor resting on a keyword

### Spec Text
> "Returns what the name at the cursor position evaluates to." / "If the cursor is not on
> a name, exit 1."

### Alternatives
1. Every keyword fails, including `None`, `True` and `False`.
2. Keywords fail, except the three that are values in their own right.

### Choice
(2). `None` is named in the builtin rule as something a definition can point at, which it
could never be if a cursor could not rest on it. Statement keywords such as `if` and `def`
name nothing and fail.

### Risk: 20
Author most likely prefers: (2) as well; the uncertainty is whether `True`/`False` were
considered at all.

---

## T26. What `None` is called in a definition

### Spec Text
> "For builtin types (including None, int, str, etc.), definitions use type `instance` and
> full_name `builtins.<name>`."

### Alternatives
1. `name` is `None` and `full_name` is `builtins.None`.
2. The runtime type name is used: `NoneType` and `builtins.NoneType`.

### Choice
(1). The spec lists `None` alongside `int` and `str` as one of the builtin type *names*,
so the name it gives is the one to print. The same spelling is used for the completion
description of a name bound to `None`.

### Risk: 25
Author most likely prefers: (1); an implementation reading `type(value).__name__` would
land on (2) instead.

---

## T27. The docstring of a builtin definition

### Spec Text
> "`docstring` | string | The docstring of the definition, or empty string if none."
> "For builtin types ... `module_path` set to empty string and `line`/`column` set to 0."

### Alternatives
1. A builtin definition is a stub record: no path, no position, and no docstring.
2. The builtin type's own `__doc__` is reported, so `infer` on `42` carries the text of
   `int.__doc__`.

### Choice
(1). The spec defines the builtin record field by field and every field it names is
emptied; carrying a large C docstring into a record that has no location would be the odd
one out. Definitions that do have a source location (including instances of in-file
classes) report the docstring of the class they point at.

### Risk: 35
Author most likely prefers: (2), since `inspect.getdoc` is free once the type is known.

---

## T28. `full_name` of names that are not module-level

### Spec Text
> "`full_name` | string | Dot-separated qualified name. For top-level names:
> `module.name`. For nested: `module.Class.method`."

### Alternatives
1. Every name is qualified by the scopes around it, so a local variable of `helper` is
   `module.helper.value` and a parameter is `module.helper.arg`.
2. Only names reachable from outside get a qualified name; locals and parameters report
   an empty string.

### Choice
(1). The field is documented without exceptions, and `module.Class.method` shows the
qualification is by enclosing scope. An attribute assigned onto `self` is qualified by its
class rather than by the method it is assigned in, since that is where it lives.

### Risk: 40
Author most likely prefers: (2), which is what a Jedi-shaped implementation reports for a
name that has no importable path.

---

## T29. Whether `goto` follows an import

### Spec Text
> "`goto` returns where the name at the cursor is assigned or defined (`def`, `class`,
> assignment, or import binding)."

### Alternatives
1. `goto` stops at the import binding: the import statement in the file being analysed.
2. `goto` follows the import through to the `def` or `class` in the other module.

### Choice
(1). "import binding" is listed as one of the things `goto` lands on, next to `def` and
`class`, so the binding itself is a destination. `infer` is the command that reaches the
other module.

### Risk: 30
Author most likely prefers: (1); (2) is the reading if "import binding" was meant as the
thing being followed rather than the destination.

### Update (cross-file spec)
Settled: both readings are now commands of their own. "Without `--follow-imports`
(default), `goto` on an imported name returns the `import` statement itself", which is (1),
and `--follow-imports` asks for (2).

---

## T30. Return annotations

### Spec Text
> "Infer a function's return type by analyzing its `return` statements."
> "If a function has no `return` statement or only bare `return`, the return type is `None`."

### Alternatives
1. Only `return` statements are read; a `-> Widget` annotation is ignored.
2. The annotation wins when present, and return statements are the fallback.

### Choice
(1), verbatim. The two sentences together leave no room for an annotated function with no
`return` to be anything but `None`, and an annotated function that does return something
reaches the same answer either way.

### Risk: 25
Author most likely prefers: (2) for stub-like functions whose body is `...`.

> **Since the stub spec:** partly settled. "`infer` uses return type annotations from the
> stub" makes an annotation authoritative when it is written in a `.pyi`, which is now
> implemented. A `-> T` written in the `.py` itself is still not mentioned, so the choice
> above stands for that case.

---

## T31. Which assignments a name can still resolve to

### Spec Text
> "Multiple definitions are returned when a name could resolve to more than one thing
> (e.g., conditional assignments)."
> "For unresolved branches, return all reachable possibilities."

### Alternatives
1. Every assignment of the name in the scope is returned.
2. Only the last assignment before the cursor is returned.
3. Assignments in sibling branches are all returned, while an assignment that runs
   unconditionally replaces everything written above it.

### Choice
(3). The spec calls out *conditional* assignments as the reason for more than one answer,
which means an ordinary reassignment is not one: `x = 1` followed by `x = 2` leaves only
the second reachable, while `if`/`else` arms leave both.

### Risk: 35
Author most likely prefers: (1), which needs no flow analysis and still satisfies the
"conditional assignments" example.

---

## T32. How `@dataclass` is recognised

### Spec Text
> "Classes decorated with `@dataclasses.dataclass` expose their annotated fields as
> instance attributes for completion and inference."
> "`@dataclass` is recognized regardless of import form."

### Alternatives
1. Annotated class-body fields are instance attributes of any class, so a dataclass needs
   no special handling and every import form works by construction.
2. Fields are only exposed for classes whose decorator resolves to `dataclasses.dataclass`,
   and a plain class hides its bare annotations.

### Choice
(1). Every behaviour the spec lists for dataclasses -- fields as instance attributes, the
field's annotated type, `frozen=True` changing nothing, any import form -- already holds
for annotated class attributes in general, and a decorator check could only ever take
attributes *away* from plain classes, which nothing in the spec asks for.

### Risk: 12
Author most likely prefers: (1); (2) would only show up on a plain class with a bare
annotation and no assignment.

---

## T33. Which methods contribute instance state

### Spec Text
> "Infer attributes from instance state when resolvable."

### Alternatives
1. Only `self.x = ...` in `__init__`, as the earlier spec spelled out (see T11, T18).
2. `self.x = ...` in any method.

### Choice
(1). The new wording is about inference rather than about which methods are scanned, and
the earlier spec was explicit, so the earlier restriction stands.

### Risk: 20
Author most likely prefers: (1), unchanged from the completion spec.

---

## T34. `is None` narrowing, which the spec leaves blank

### Spec Text
> "### `is None`"

(The section has a heading and no body.)

### Alternatives
1. No `is None` behaviour at all, the heading being a leftover.
2. `if x is None:` narrows `x` to `None` inside the body, and nothing else.
3. As (2), plus `is not None` removing `None` from the possibilities, and the `else` arm
   of each form narrowing the other way.

### Choice
(3). The heading sits under "Flow-Sensitive Type Narrowing" beside `isinstance`, so the
same shape of answer is expected, and a `None` check is only worth narrowing at all
because of the branch where the value is *not* `None`. Narrowing is recognised on `if`
statements; `assert` and `while` are not treated as guards.

### Risk: 40
Author most likely prefers: (2), narrowing only the positive `is None` branch.

---

## T35. Whether completions adopt the definition description format

### Spec Text
> "`description` | string | Short description. For functions: `def name(params)`."
> (earlier spec) "For functions: `def name(...)`."

### Alternatives
1. The table describes definition objects only; completions keep `def name(...)`.
2. Both surfaces switch to the parameter list.

### Choice
(1). The table is introduced as the output format of `infer` and `goto`, and the
completion spec it does not mention is still in force with its own wording.

### Risk: 30
Author most likely prefers: (1); (2) is what a single shared description helper would
produce.

---

## T36. Calls to functions that return nothing

### Spec Text
> "If a function has no `return` statement or only bare `return`, the return type is `None`."
> (earlier spec) "For assignments: `instance of <type>` if the right-hand side is ...
> resolvable to a known type; otherwise `statement`."

### Alternatives
1. `value = maker()` where `maker` returns nothing is now `instance of None`: the call is
   resolvable, so the earlier "otherwise" no longer applies.
2. Completions keep calling it a `statement`, and the `None` return type only shows up
   through `infer`.

### Choice
(1). Return-type inference is listed under the type inference rules that completion draws
on, so a call whose type is known is a known type wherever it is reported.

### Risk: 40
Author most likely prefers: (1) if the two specs were reconciled, (2) if the completion
fixtures were left untouched.

---

## T37. The position of a module definition

### Spec Text
> "`line` | int | 1-based line number of the definition." / "`column` | int | 0-based
> column of the name identifier in the definition."

### Alternatives
1. A module has no defining identifier, so it reports line 0 and column 0, like a builtin.
2. A module reports line 1, column 0, the start of its file.

### Choice
(1). The column is defined as the column *of the name identifier*, and a module has none;
0/0 is the position the spec already uses for definitions without one.

### Risk: 15
Author most likely prefers: (1), though (2) is a natural fallback if positions are taken
from the file rather than from a name.

---

## T38. `goto` on a name the file never binds

### Spec Text
> "Returns the location(s) where the name at the cursor was defined."
> "If no definition is found, return an empty array (exit 0)."

### Alternatives
1. A builtin such as `print` still has a definition, reported as the builtin record.
2. Nothing in the file binds it, so the array is empty.

### Choice
(1). `goto` falls back to whatever the name resolves to when no binding in the file
introduces it, which keeps `goto` and `infer` in agreement for names that are only ever
defined elsewhere. Names that resolve to nothing at all still return an empty array.

### Risk: 20
Author most likely prefers: (1), the same record `infer` returns.

---

## T39. Whether a module outside the project and outside the stdlib resolves

### Spec Text
> "**Module search order:** 1. Project root -- scan for `.py` files and packages ...
> 2. Standard library -- recognize stdlib modules available in the target runtime.
> 3. If a module cannot be found, treat it as unresolvable"

### Alternatives
1. The search order is exhaustive: an installed third-party package is in neither place,
   so `import requests` is unresolvable.
2. Anything importable in the running interpreter resolves, the two entries being only
   the order in which the search is made.

### Choice
(1). The list has exactly two entries and a third clause that catches everything else, and
the `--follow-imports` fallback names "third-party or stdlib" as modules that "cannot be
found". A third-party import therefore yields no completions and no definitions.

### Risk: 30
Author most likely prefers: (2), if their implementation reaches the stdlib by importing
the name and never checks that the module actually belongs to the stdlib.

---

## T40. Whether `--follow-imports` lands inside the standard library

### Spec Text
> "If the import chain leads to a module that cannot be found (e.g., third-party or
> stdlib), return the import statement as a fallback."

### Alternatives
1. `goto --follow-imports` never leaves the project: an imported stdlib name answers with
   the import statement, even though the stdlib module has readable source.
2. A stdlib module written in Python has a definition to land on, so the fallback is only
   for compiled and missing modules.

### Choice
(1), which the parenthetical states outright: stdlib is listed beside third-party as a
module the chain cannot reach. Only project modules are followed into.

### Risk: 15
Author most likely prefers: (1); (2) would need source lookup the spec never asks for.

---

## T41. What `import |` offers

### Spec Text
> "`import |` suggests top-level module/package names."

### Alternatives
1. Only the modules and packages sitting in the project root.
2. The project root's modules and the standard library's, which is the whole search path
   an `import` statement is resolved against.

### Choice
(2). The module search order makes the stdlib part of what `import` can name, so a
completion list that omitted it would not describe what the statement can resolve to.

### Risk: 40
Author most likely prefers: (1) if the completion is built by listing the project
directory, which is the shorter implementation and the one the phrase "top-level" hints at.

---

## T42. Whether `__all__` governs attribute completion on a module

### Spec Text
> "In `from X import ...` completion, exported names come from `__all__` when it exists;
> otherwise use names that do not start with `_`."

### Alternatives
1. `__all__` is about exporting, so it governs `import *` and `from X import` completion,
   while `X.|` keeps offering every public attribute the module has.
2. One notion of "the names of a module" serves all three, so `__all__` also trims `X.|`.

### Choice
(1). The clarification scopes `__all__` to `from X import` completion, and the earlier
spec had already fixed module attribute completion as the names not starting with `_`.
`os.__all__` lists `_exit`, so the two rules are observably different.

### Risk: 30
Author most likely prefers: (2) if a single `public_names(module)` helper backs every
listing.

---

## T43. What `from <package> import |` offers

### Spec Text
> "`from X import |` suggests names inside module `X`."

### Alternatives
1. Only the names bound in the package's `__init__.py`.
2. Those names plus the package's submodules, which `from X import Y` can also name.

### Choice
(2). `from pkg import tools` is a legal import of a submodule, so a completion list that
left `tools` out would be missing an answer the statement accepts.

### Risk: 25
Author most likely prefers: (2), since resolving `from X import Y` already has to fall
back to the submodule; (1) is the reading if completion reads only the module body.

---

## T44. Where a relative import is anchored

### Spec Text
> "If the relative import goes above the project root, it is unresolvable."

### Alternatives
1. The project root is the anchor: one dot is the directory holding the importing file,
   each further dot climbs one directory, and only leaving the root is unresolvable. A
   module at the root may write `from . import helpers`, and `pkg/app.py` may write
   `from ..helpers import Widget`.
2. Python's own rule: a dot count greater than the depth of the importing module's package
   is "beyond top-level package", so both examples above are errors.

### Choice
(1). The spec words the failure as leaving the *project root*, not as leaving a top-level
package, and the root is what the rest of the section resolves against. Climbing to the
root is therefore still inside the project.

### Risk: 45
Author most likely prefers: (2) for `pkg/app.py` writing `from ..x import y`, which real
Python rejects and which is the natural fixture for an "above the root" test.

---

## T45. `goto` on a name imported from a module that cannot be found

### Spec Text
> "If a module cannot be found, treat it as unresolvable -- `infer` and `goto` return
> empty results"
> "Without `--follow-imports` (default), `goto` on an imported name returns the `import`
> statement itself"

### Alternatives
1. The import statement is still a definition of the name, so plain `goto` answers with
   it; the empty results are for the module's *attributes*, which have nowhere to live.
2. Nothing about the module resolves, so `goto` on the imported name is empty too.

### Choice
(1). The default `goto` never consults the imported module at all, so whether it exists
cannot change the answer, and `--follow-imports` explicitly falls back to the same record.

### Risk: 20
Author most likely prefers: (1); (2) would make the default `goto` depend on a search it
does not otherwise perform.

---

## T46. What `--follow-imports` lands on for `import <module>`

### Spec Text
> "With `--follow-imports`, `goto` follows the import chain and returns the actual
> definition in the source module"

### Alternatives
1. The definition of a module is the module itself: the record points at its file with no
   identifier position, so line 0 and column 0 (as T37 already settled for modules).
2. It points at line 1, column 0 of the file.
3. A module name has no "definition in the source module", so the import statement stands.

### Choice
(1). `infer` on the same cursor already answers with the module record, and following the
import should not produce a different kind of answer than the one the module has.

### Risk: 35
Author most likely prefers: (2) if the follow step reports the head of the target file
rather than reusing the module record.

---

## T47. A package and a module with the same name in the root

### Spec Text
> "Project root -- scan for `.py` files and packages (directories containing
> `__init__.py`)."

### Alternatives
1. `pkg/__init__.py` wins over `pkg.py`, as it does in CPython.
2. The `.py` file wins, following the order the sentence lists them in.

### Choice
(1). The sentence describes what is scanned, not a precedence, and matching CPython is
what a reader checking the tool against a real interpreter would expect.

### Risk: 10
Author most likely prefers: (1); the collision is unlikely to be tested at all.

---

## T48. Completion after a dotted module prefix

### Spec Text
> "`import |` suggests top-level module/package names."

### Alternatives
1. Only the bare `import |` position completes; `import pkg.to|` gets nothing, or gets
   top-level names filtered by the literal prefix `pkg.to`.
2. A dotted prefix completes the submodules of the package already named.

### Choice
(2). The spec only spells out the top-level case, and a dotted prefix is the same question
asked one level down; answering it cannot contradict a rule the spec states.

### Risk: 15
Author most likely prefers: (2), but a test is unlikely either way.

---

## T49. `module_path` of a definition that lives outside the project

### Spec Text
> "`module_path` | string | File path where the name is defined, relative to the project
> root."
> "All paths in output fields ... use forward-slash separators (POSIX convention)."

### Alternatives
1. A stdlib definition keeps its absolute file path, slash-separated, since it has no
   sensible path relative to the root.
2. It is written relative to the root anyway, with `../..` climbing out of the project.

### Choice
(1). A path made of `..` segments says nothing useful about a file that is not in the
project; the absolute path at least names it. Paths inside the project stay relative.

### Risk: 25
Author most likely prefers: (1), though a `relpath` call applied unconditionally would
produce (2).

---

## T50. What a name caught in a circular import resolves to

### Spec Text
> "Circular imports: do not infinite-loop. If module A imports B and B imports A, resolve
> what is available at the point of the circular reference and move on. Names not yet
> defined at the point of circular import are simply not visible."

### Alternatives
1. The cycle is cut at the point it closes: the binding being re-entered yields nothing,
   while every other name of both modules still resolves normally.
2. The whole import is abandoned once a cycle is detected, so neither module contributes.

### Choice
(1). "resolve what is available ... and move on" asks for as much as can be had, and only
the re-entered name is the one that is "not yet defined".

### Risk: 20
Author most likely prefers: (1), which is also what a visited-set guard produces naturally.

---

## T51. The JSON key `search` answers under

### Spec Text
> "`python sith.py search <query> [--project <dir>]`"
> "Each result has the same fields as a definition object (from `infer`/`goto`), minus
> `docstring`."

### Alternatives
1. `{"definitions": [...]}`, the envelope `infer` and `goto` already use for definition
   records.
2. `{"results": [...]}` or `{"matches": [...]}`, named after the command rather than the
   record.

### Choice
(1). Every envelope so far is named after the kind of record it carries, not after the
subcommand -- `goto` answers under `definitions` rather than under `goto` -- and the spec
describes a search result as a definition object with one field removed.

### Risk: 30
Author most likely prefers: `definitions`, for the same reason.

---

## T52. The JSON key `names` answers under

### Spec Text
> "`python sith.py names <file> [--all-scopes] [--project <dir>]`"
> "Each entry has the definition fields plus `is_definition` (always `true` for this
> command)."

### Alternatives
1. `{"definitions": [...]}`, since the entries are definition records.
2. `{"names": [...]}`, echoing the subcommand, which here happens to also describe the
   records.

### Choice
(1), for consistency with every other command: the key names the record type. `names` is
the one subcommand whose own name is also a plausible record name, but breaking the rule
for it alone would be odd.

### Risk: 40
Author most likely prefers: `names`, because the command is called `names` and the
temptation to mirror it is strong.

---

## T53. Whether `self` is dropped from `params` as well as from `description`

### Spec Text
> "| `description` | string | ... The `self` parameter is excluded for methods. |"

### Alternatives
1. `self` is dropped from `params`, from `description`, and therefore from what `index`
   counts.
2. `self` is dropped only from the rendered `description`, while `params` still lists it.

### Choice
(1). The exclusion is written on the `description` row only because that is where the
parameter list is spelled out in prose, but `index` is "the parameter the cursor is
currently on" and a caller never passes `self`; keeping it in `params` would make the
first argument of `obj.method(|)` report index 1.

### Risk: 15
Author most likely prefers: (1), since any index arithmetic has to skip `self` anyway.

---

## T54. The positional-only `/` and keyword-only `*` markers

### Spec Text
> "Each param is rendered as: `\"name\"` for bare parameters, ... Special forms:
> `\"*args\"`, `\"**kwargs\"`, `\"*args: type\"`, `\"**kwargs: type\"`."

### Alternatives
1. The markers are not parameters and never appear in `params`.
2. They appear as their own `"/"` and `"*"` entries, the way `inspect` renders a
   signature.

### Choice
(1). The table enumerates the renderings exhaustively and neither marker is among them;
they also name nothing, so `index` could never point at one.

### Risk: 20
Author most likely prefers: (1), the simpler rendering.

---

## T55. What a call of a class reports

### Spec Text
> "| `name` | string | Function or class name. |"
> "| `description` | string | `\"def name(params)\"` ... |"

### Alternatives
1. The class's own name, the parameters of `__init__` without `self`, and no return type.
2. The name `__init__`, with the method's own signature.
3. As (1), but keeping `__init__`'s `-> None` annotation in the description.

### Choice
(1). `name` is explicitly allowed to be a class name, which only makes sense when calling
a class reports the constructor under the class's name; a constructor's `-> None` is
noise that describes the call badly, since `Box(...)` evaluates to a `Box`.

### Risk: 40
Author most likely prefers: (1), but may well keep `-> None` when a stub annotates
`__init__`, since the annotation is simply copied.

---

## T56. Which bracket decides the call when brackets nest

### Spec Text
> "When the cursor is inside a function call's argument list ..."
> "If the cursor is not inside a call's parentheses, return an empty signatures array."

### Alternatives
1. The innermost enclosing *call* wins: a display or grouping bracket written inside an
   argument keeps the enclosing call, with the argument position that argument started at.
2. The innermost bracket of any kind decides, so `f([1, |])` is inside a list and reports
   nothing.

### Choice
(1). An editor showing signature help does not drop it the moment a list literal is typed
as an argument, and "not inside a call's parentheses" reads as being outside every call
rather than as being inside something else as well.

### Risk: 30
Author most likely prefers: (1) for nested calls -- which both readings agree on -- and
possibly (2) for displays, where the argument index is arguable.

---

## T57. Whether inferred parameter types are rendered in `params`

### Spec Text
> "When a function has no type annotations and no stub, the tool can optionally infer
> parameter types by finding call sites. This is enabled by default and affects `infer`
> and `signatures`."
> "`\"name: type\"` for annotated parameters"

### Alternatives
1. `params` shows only what the source or the stub writes; dynamic inference changes what
   `infer` answers about a parameter and nothing that `signatures` prints.
2. An inferred type is rendered as though it had been annotated, so `def f(x)` called as
   `f(1)` shows `["x: int"]`.

### Choice
(1). The rendering table ties `"name: type"` to *annotated* parameters, and a call site is
not an annotation; a parameter inferred as two different types at two call sites also has
no single rendering. The mention of `signatures` is read as naming the commands that
consult parameter types at all.

### Risk: 40
Author most likely prefers: (2) -- the sentence goes out of its way to name `signatures`,
and rendering the inferred type is the only observable effect it could have.

---

## T58. Whether file-scope `references` filters by symbol identity

### Spec Text
> "`--scope file` (default): search only within the target file."
> "For project-scope search, return only occurrences that resolve to the same symbol
> identity as the cursor target (do not include same-spelling but unrelated symbols in
> other scopes)."

### Alternatives
1. Identity filtering applies to both scopes: two unrelated locals named `value` in two
   functions of one file are not references to each other.
2. Identity filtering applies only across files; within the target file every occurrence
   of the spelling is returned.

### Choice
(1). The parenthesis says "unrelated symbols in *other scopes*", and the scopes of one
file are other scopes just as much as those of another file. A find-references that
answered with every same-spelled local in the file would be wrong in the ordinary case of
a loop variable named `i`.

### Risk: 40
Author most likely prefers: (2) for file scope, since a within-file scan by spelling is
the cheap implementation and the identity rule is written under the project bullet.

---

## T59. Whether attribute accesses count as references

### Spec Text
> "Find all locations where the name at the cursor is referenced (used or defined)."

### Alternatives
1. Bare names and attribute accesses both count, an attribute matching when it resolves
   to the same definition.
2. Only bare names count.

### Choice
(1). `self.size` is where the name `size` is used, and a references command that could not
answer for an attribute would be unusable on methods and instance state.

### Risk: 25
Author most likely prefers: (1); the risk is over which attributes their resolver manages
to match, not over the principle.

---

## T60. Whether `search` returns imported names

### Spec Text
> "Search all `def`, `class`, and top-level assignment names across project files."
> "`names` includes top-level imports as module-level names"

### Alternatives
1. Imports are not searched: only `def`, `class` and assignments.
2. Imports are searched too, as they are listed by `names`.

### Choice
(1). The list of searched forms is explicit and does not mention imports, and the
clarification adds imports specifically to `names` -- which would be pointless if `search`
already included them.

### Risk: 25
Author most likely prefers: (1), given they wrote the two rules separately.

---

## T61. What "top-level assignment" leaves out

### Spec Text
> "Search all `def`, `class`, and top-level assignment names across project files."
> "Do not search inside function/method bodies (local variables are not searchable)."

### Alternatives
1. Everything outside a function body is searched: module level plus class bodies, so
   methods and class attributes are found.
2. Only module level is searched, so a method is not findable by name.

### Choice
(1). The exclusion names function and method *bodies*, which would have nothing to exclude
if class bodies were already out; and a project-wide symbol search that cannot find a
method would not be worth having. `full_name` is what distinguishes `tools.Box.pack` from
a module-level `pack`.

### Risk: 30
Author most likely prefers: (1), reading "top-level" as "not inside a function".

---

## T62. What `--all-scopes` counts as a name

### Spec Text
> "`--all-scopes`: include names from all scopes (locals inside functions, class
> attributes, nested defs)."

### Alternatives
1. Every name a scope binds: locals, parameters, class-body attributes, nested `def`s and
   `class`es, and imports written inside a function.
2. As (1) plus the attributes a method assigns onto `self`, which belong to no scope.
3. Locals only, with parameters left out as declarations rather than names.

### Choice
(1). Parameters are bound in the function's scope exactly as its locals are, and "names
from all scopes" is a statement about scopes; `self.size` is written in a method but is
not a name of that method's scope, so it stays out.

### Risk: 45
Author most likely prefers: (2) -- "class attributes" could well have been written with
`self.size` in mind rather than class-body assignments.

---

## T63. Whether a name bound twice is listed twice

### Spec Text
> "List names defined in a file."
> "Sort by `(line, column)` ascending."

### Alternatives
1. One entry per binding, so `x = 1` followed by `x = 2` gives two entries.
2. One entry per name, keeping the last binding.

### Choice
(1). The entries carry a position and are sorted by it, which only makes sense if an entry
is a place rather than a name; `is_definition` being "always true" says the same thing --
each entry is one defining occurrence.

### Risk: 25
Author most likely prefers: (1), which falls out of walking the bindings.

---

## T64. Where a stub is looked for, for a module inside a package

### Spec Text
> "For a module `foo`, the tool looks for type stubs in this order:
> 1. `foo.pyi` adjacent to `foo.py` (inline stub).
> 2. A `stubs/` directory in the project root: `stubs/foo.pyi` or `stubs/foo/__init__.pyi`."

### Alternatives
1. The dotted module name becomes a path under each root, so `pkg.tool` is
   `pkg/tool.pyi`, `pkg/tool/__init__.pyi`, `stubs/pkg/tool.pyi`,
   `stubs/pkg/tool/__init__.pyi`, in that order.
2. Only the last segment is used, so `pkg.tool` is stubbed by `stubs/tool.pyi`.

### Choice
(1). "adjacent to `foo.py`" means the module's own directory whatever that is, and the
`stubs/` tree is the same tree rooted elsewhere -- which is how every real stub directory
is laid out. The `__init__.pyi` form is offered beside the package too, not only under
`stubs/`, since a package's inline stub has nowhere else to live.

### Risk: 20
Author most likely prefers: (1).

---

## T65. `goto` on a name that both the stub and the source define

### Spec Text
> "`goto` still navigates to the `.py` source (not the stub), unless the definition only
> exists in the stub."

### Alternatives
1. The source answers whenever it binds the name at all; the stub answers only when the
   source has nothing.
2. Both are returned, the reader choosing.

### Choice
(1), verbatim: "unless the definition only exists in the stub" makes the stub a fallback
rather than an addition.

### Risk: 10
Author most likely prefers: (1).

---

## T66. How overloads are recognised

### Spec Text
> "Multiple signatures are returned when the callable has overloads or when the name
> resolves to multiple possible functions."

### Alternatives
1. The `@overload`-decorated declarations: a stub's if there is one, otherwise the
   source's, with the implementation `def` left out when overloads exist.
2. Every same-named `def` in the scope, implementation included.

### Choice
(1). `@typing.overload` is what "overloads" means in Python, and the implementation
signature is deliberately untyped -- reporting it beside the overloads would answer with
the one signature the author did not want shown.

### Risk: 35
Author most likely prefers: (1), but may also return the implementation as a further
signature since it is a `def` of the same name.

---

## T67. Whether `signatures` answers for callables outside the project

### Spec Text
> "When the cursor is inside a function call's argument list, return the function's
> signature(s)"

### Alternatives
1. Builtins and standard-library callables are introspected at runtime and answer like any
   other function.
2. Only functions and classes written in the project have signatures.

### Choice
(1). Nothing in the spec restricts the command to project code, `infer` and `complete`
already reach into imported modules, and `os.path.join(|)` is exactly the case signature
help exists for. Defaults are rendered with `repr`, annotations with the name the
annotation prints under.

### Risk: 35
Author most likely prefers: (1), with the risk sitting in how a runtime default is
spelled rather than in whether an answer comes back.

---

## T68. What `references` does when the cursor is not on a name

### Spec Text
> "Find all locations where the name at the cursor is referenced (used or defined)."

### Alternatives
1. No name at the cursor at all is an error (STDERR, exit 1), as it already is for `infer`
   and `goto`; a cursor resting on a literal answers with an empty array, as `goto` does.
2. Both cases answer with an empty array.
3. Both cases are errors.

### Choice
(1). The command takes the same cursor argument as `goto` and should fail and succeed in
the same places; a literal is a value that is written where it stands, so nothing refers
to it, while an unaddressable position is a bad request.

### Risk: 30
Author most likely prefers: (1) by reusing whatever their `goto` does.

---

## T69. Which call sites feed dynamic parameter inference

### Spec Text
> "the tool can optionally infer parameter types by finding call sites. This is enabled by
> default and affects `infer` and `signatures`. Do not search other files for call sites."

### Alternatives
1. Every call written in the same file whose callee is spelled with the function's name --
   `f(...)` for a function, `obj.method(...)` for a method, with `self` accounted for --
   contributing the argument in that parameter's position or under its keyword.
2. Only calls that provably resolve back to that same function.
3. Only calls written at module level.

### Choice
(1). Matching by the written name is what "finding call sites" in one file can mean
without a full call graph, and it is what makes the feature useful in the ordinary file
where a helper is called a few lines below its `def`.

### Risk: 30
Author most likely prefers: (1); (2) differs only when two same-named functions live in
one file.

---

## T70. The project root of `search`, which is given no file

### Spec Text
> "`python sith.py search <query> [--project <dir>]`"

### Alternatives
1. Without `--project` the root is the current working directory.
2. Without `--project` the command is an error, since there is no file to take a root from.

### Choice
(1). Every other command defaults the root to something already at hand; `search` has no
file argument, so the directory the tool was run in is the only candidate, and erroring
would make `--project` mandatory in all but name.

### Risk: 15
Author most likely prefers: (1).

---

## T71. Whether `index` is computed per signature

### Spec Text
> "| `index` | int or null | 0-based index of the parameter the cursor is currently on. |"
> "Multiple signatures are returned when the callable has overloads or when the name
> resolves to multiple possible functions."

### Alternatives
1. Each signature carries the index the cursor means for its own parameter list, so the
   same cursor is `null` for a one-parameter overload and `1` for a two-parameter one.
2. One index is computed once and repeated on every signature.

### Choice
(1). `index` sits inside the signature object rather than beside the array, and the rules
for it ("maps to `*args` when available") are stated in terms of one signature's declared
parameters.

### Risk: 10
Author most likely prefers: (1).

---

## T72. What counts as an exact match when ranking search results

### Spec Text
> "Match is by substring, case-insensitive: query `calc` matches `Calculator`,
> `recalculate`."
> "Sort by: exact match first, then prefix match, then substring match."
> "`search` matching is case-insensitive and uses exact/prefix/substring ranking before
> path/line tie-breaks."

### Alternatives
1. All three comparisons are case-insensitive, so `calc` ranks `Calc` as an exact match.
2. Matching is case-insensitive but ranking is case-sensitive, so only `calc` is exact.

### Choice
(1). The clarification puts "case-insensitive" and the ranking in one sentence, and a
ranking that suddenly minded case would make `CALC` find `calc` and then rank it below a
substring hit.

### Risk: 20
Author most likely prefers: (1).
