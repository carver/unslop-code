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
