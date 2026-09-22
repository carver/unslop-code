# Ambiguities

Numbered record of under-specified points in the spec, the reading chosen, and the
risk that the spec author's own implementation (and hidden tests) read it differently.

---

## T1. What counts as a valid line when the file ends with a newline

### Spec Text
> If the position is out of range (line exceeds file length, or column exceeds line length), exit 1.

### Alternatives
1. Lines are `text.splitlines()`. A file `"x = 1\n"` has exactly 1 line, so line 2 is out of range.
2. Lines are `text.split("\n")`. A file `"x = 1\n"` has 2 lines, the second being the empty
   line after the final newline, so line 2 col 0 is a valid cursor position.

### Choice
`text.split("\n")` (interpretation 2), with a trailing `\r` stripped from each line for CRLF
files. Editors place a real cursor position on the empty line after a trailing newline, and a
completion tool is invoked from an editor; refusing to complete at the very position where a
user most often types a new statement would make the tool useless for the most common case.
`col` is valid when `0 <= col <= len(line)` (a cursor may sit at end-of-line).

### Risk: 30
Author most likely prefers: same `col <= len(line)` rule but `splitlines()`, making line 2 of
`"x = 1\n"` an error.

---

## T2. Cursor position in an empty file

### Spec Text
> If the position is out of range (line exceeds file length, or column exceeds line length), exit 1.

### Alternatives
1. An empty file has zero lines, so `1 0` is out of range → exit 1.
2. An empty file has one empty line, so `1 0` is valid and returns keywords + builtins.

### Choice
Interpretation 2, which falls out of the `split("\n")` decision in T1 (`"".split("\n") == [""]`).
Completing in an empty buffer is a normal editor operation and should yield builtins/keywords.

### Risk: 25
Author most likely prefers: exit 1 for an empty file if they used `splitlines()`.

---

## T3. Is a name visible on the very line that defines it?

### Spec Text
> A `def` or `class` statement makes its name visible from the line of the `def`/`class` keyword.
> An assignment makes the name visible from the line of the assignment.

### Alternatives
1. Visible from that line inclusive (`binding_line <= cursor_line`).
2. Visible from the *next* line (`binding_line < cursor_line`), since the name is not actually
   bound until the statement finishes executing.

### Choice
Inclusive (`binding_line <= cursor_line`). "visible **from** the line of the keyword" reads as
inclusive, and it is the simpler comparison to implement.

### Risk: 15
Author most likely prefers: the same inclusive comparison.

---

## T4. Are enclosing-scope names also filtered by cursor position?

### Spec Text
> A name is visible only if it is defined **before** the cursor position in the source (for the
> local and global scopes).

### Alternatives
1. The parenthetical is exhaustive: only local and global bindings get the positional filter;
   enclosing function scopes contribute all their names regardless of line.
2. The positional filter applies to every non-builtin scope.

### Choice
Interpretation 1, read literally: enclosing (closure) scopes are not filtered. The spec goes out
of its way to name exactly which scopes are filtered, so the omission looks deliberate — and a
closure's free variables are genuinely usable regardless of textual order.

### Risk: 25
Author most likely prefers: filtering every scope by line with one shared comparison.

---

## T5. Class-body names inside a method

### Spec Text
> 2. **Enclosing scopes** — names from enclosing functions (for nested functions/closures).

### Alternatives
1. Python semantics: a class body is *not* an enclosing scope for its methods, so class-level
   names are not bare-name-visible inside a method.
2. Treat the class body as an ordinary enclosing scope, so class attributes appear as bare names
   inside methods.

### Choice
Interpretation 1. The spec says enclosing scopes are "names from enclosing **functions**", which
matches Python's actual scoping rule. Class-level names remain reachable via `self.` / `Cls.`.

### Risk: 30
Author most likely prefers: same, but an implementation that simply walks every ancestor scope
would leak class-body names into methods.

---

## T6. Description of an imported name whose object is a function or class

### Spec Text
> For imports: `module name`.
> For imported names (from import statements), the `type` reflects the imported object's actual
> kind if inferable (e.g., `function`, `class`, `module`). If not inferable, use `statement`.

### Alternatives
1. Every import-bound name gets `description = "module <name>"`; only `type` varies by kind.
2. Description tracks the inferred kind: `from os import getcwd` → `def getcwd(...)`,
   `from x import SomeClass` → `class SomeClass`, and `module <name>` only for real modules.

### Choice
Interpretation 2. In the spec's own example output, `description` is strictly derived from
`type` (`function` → `def print(...)`, `class` → `class property`), which strongly suggests a
single `describe(kind, name)` helper. The `module name` table row then covers the `import os`
case. Names bound by an import that cannot be resolved keep `type = "statement"` and
`description = "module <name>"`, preserving the table row for the un-inferable case.

### Risk: 45
Author most likely prefers: `description = "module <name>"` for every import-bound name,
regardless of the inferred `type`.

---

## T7. Are private/dunder attributes returned for classes, instances and literals?

### Spec Text
> **Modules** — if `foo` is an imported module, return the module's public names. A name is
> public if it does not start with `_`.

### Alternatives
1. The public-only filter is stated only for modules, so classes, instances and literals return
   everything `dir()`-visible, dunders included.
2. The public-only rule is a global policy for all attribute completion.

### Choice
Interpretation 1. The filter is introduced as a property of the *module* bullet, and the ordering
section defines explicit ranks for private and dunder names — ranks that would be dead code if
underscore names were never emitted (name completion of builtins also produces dunders, but the
private rank in particular is most natural for attributes).

### Risk: 35
Author most likely prefers: same for classes/instances defined in the file (their `_x` members
are user-written), but may strip dunders from literal receivers like `"abc".`.

---

## T8. Do builtins contribute dunder names to name completion?

### Spec Text
> 4. **Builtin scope** — builtin names provided by Python's `builtins` module.

### Alternatives
1. Everything in `dir(builtins)`, including `__import__`, `__name__`, `__debug__`.
2. Only public builtins.

### Choice
Interpretation 1 — `dir(builtins)` verbatim. The spec says "builtin names provided by Python's
`builtins` module" with no filter, and it separately defines a sort rank for dunder names.

### Risk: 30
Author most likely prefers: same, but a `__`-prefix test on the empty-prefix case would change
the result set for unfiltered name completion.

---

## T9. Which keywords

### Spec Text
> When in a name-completion context, also include Python keywords as completions.

### Alternatives
1. `keyword.kwlist` (hard keywords, including `True`/`False`/`None`).
2. `keyword.kwlist + keyword.softkwlist` (adds `_`, `case`, `match`, `type`).

### Choice
`keyword.kwlist` only. Soft keywords are ordinary identifiers outside of their statement context,
and suggesting `_` as a keyword would be noise.

### Risk: 20
Author most likely prefers: `keyword.kwlist`.

---

## T10. Description of a function parameter

### Spec Text
> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`, `keyword`. |

### Alternatives
1. `"param"`.
2. `"param <name>"`.
3. `"statement"`, or `"instance of <annotation>"` when annotated.

### Choice
`"param"` — the description table never mentions parameters, and the other unspecified fallback
in the table is the bare word `statement`, so the bare kind word is the consistent choice.

### Risk: 55
Author most likely prefers: `"param <name>"` (mirroring the `module name` template row).

---

## T11. Names that start with `__` but do not end with `__`

### Spec Text
> 2. **Private names** (start with `_` but not `__`) ...
> 3. **Dunder names** (start with `__` and end with `__`) ...

### Alternatives
1. `__mangled` belongs to neither group; give it its own placement.
2. `__mangled` is private (rank 2), since only true dunders are rank 3.

### Choice
Interpretation 2: rank = dunder if it starts *and* ends with `__`, else private if it starts with
`_`, else public. This is total and keeps the two stated groups exactly as described for every
name the spec actually characterises.

### Risk: 20
Author most likely prefers: the same three-way `if/elif/else` ladder.

---

## T12. `complete` under fuzzy matching

### Spec Text
> `complete` ... The text that would be inserted — the name with the already-typed prefix removed.
> When prefix matching is case-insensitive, removal is by character count: the first `len(prefix)`
> characters of the matched name are stripped regardless of case.

### Alternatives
1. The char-count rule is universal, so fuzzy matches also strip the first `len(prefix)` chars.
2. Fuzzy matches strip nothing (the whole name is the insertion).

### Choice
Interpretation 1. Fuzzy matching is explicitly "also case-insensitive", and the stripping rule is
stated for case-insensitive matching, so the same character-count rule applies.

### Risk: 25
Author most likely prefers: the same `name[len(prefix):]` for every match.

---

## T13. `self.` inside a method

### Spec Text
> **Instances** — if `foo` is an instance (from `foo = MyClass()`), return the same attributes as
> the class plus any attributes assigned in `__init__` via `self.name = ...`.

### Alternatives
1. Only names bound by `x = MyClass()` are instances; `self` is just a parameter and resolves to
   nothing.
2. `self` (the first parameter of a method) resolves to an instance of the enclosing class.

### Choice
Interpretation 2. `self.` completion is the single most common attribute completion in real code,
and the spec's own instance rule is phrased in terms of `self.name = ...` assignments, implying
the tool understands `self`.

### Risk: 15
Author most likely prefers: the same.

---

## T14. Assignment of a lambda

### Spec Text
> For assignments: `instance of <type>` if the right-hand side is a literal, a constructor call,
> or otherwise resolvable to a known type; otherwise `statement`.

### Alternatives
1. `f = lambda: 1` → `type: instance`, `description: instance of function`.
2. `f = lambda: 1` → `type: function`, `description: def f(...)`.

### Choice
Interpretation 1. The assignment rule is stated as one rule for all assignments, and a lambda's
"known type" is `function`; treating it as a `def` would require an exception the spec never makes.

### Risk: 40
Author most likely prefers: `function` / `def f(...)`, since a completion UI normally shows a
lambda binding as callable.

---

## T15. `<type>` naming for singletons and constructor calls

### Spec Text
> `instance of <type>`

### Alternatives
1. `type(value).__name__` — `x = None` → `instance of NoneType`, `x = True` → `instance of bool`.
2. Source-level spelling — `x = None` → `instance of None`.

### Choice
`type(value).__name__`, and for a constructor call the callee's name (`x = MyClass()` →
`instance of MyClass`). This is what "instance of \<type\>" literally asks for.

### Risk: 25
Author most likely prefers: the same, though `None` could plausibly be reported as
`instance of None` or fall through to `statement`.

> **Annotated after the `infer`/`goto` spec:** that spec calls the singleton a *builtin type*
> named `None` (`builtins.<name>`), so definition objects spell it `None` while `complete`
> descriptions keep `NoneType`.  See [T33](#t33-spelling-of-the-none-type-in-definitions).

---

## T16. Bindings that are neither def/class/import/assignment

### Spec Text
> **Local scope** — names assigned or defined in the immediately enclosing function/method.

### Alternatives
1. Only `=` assignments and def/class/import bind names.
2. Every binding form binds: `for` targets, `with ... as`, `except ... as`, comprehension
   targets, walrus, `match` captures, augmented and annotated assignment.

### Choice
Interpretation 2 — all binding forms are "names assigned". Their `type`/`description` is
`statement` unless a type is inferable (annotated assignment uses the annotation, walrus and
augmented assignment use their RHS). `for i in ...` reports `statement`, since inferring an
element type from an iterable is well beyond what the spec describes.

### Risk: 35
Author most likely prefers: same for `for`/`with`/`except`, but may omit comprehension targets
(which have their own scope in Python 3) or report annotated targets differently.

---

## T17. What survives a syntax error

### Spec Text
> Python syntax errors in the source file: **do not** exit with an error. Parse as much as
> possible and provide completions based on what was successfully parsed.

### Alternatives
1. Truncate at the first error and use only what precedes it.
2. Repair iteratively — neutralise each offending line (replace it with `pass`, then blank it)
   and re-parse, so code both before *and* after the broken line is analysed.

### Choice
Interpretation 2, capped at 100 repair rounds. "Parse as much as possible" is maximal, not
prefix-only; in an editor the broken line is usually the line being typed, and the definitions
below it are still real.

### Risk: 40
Author most likely prefers: a comparable line-neutralising repair, but any difference in repair
strategy changes which names survive for a file broken in the middle.

---

## T18. A name defined in more than one scope

### Spec Text
> Visible names come from these sources, checked in order:

### Alternatives
1. One entry per name; the nearest scope wins ("checked in order").
2. One entry per (name, scope) pair, so a shadowed global appears twice.

### Choice
Interpretation 1: de-duplicate by name, first scope in the stated order wins. Duplicate names in
a completion list would be a bug in any editor UI.

### Risk: 15
Author most likely prefers: the same.

---

## T19. Which names a star import brings in

### Spec Text
> `from os import *` makes all public names from `os` visible.

### Alternatives
1. Honour `__all__` when the module defines it, else all non-underscore names.
2. Always all non-underscore names.

### Choice
Interpretation 1 — Python's actual `import *` semantics, and the spec describes the feature by
naming the Python behaviour rather than defining a new one. For local project modules the names
are gathered statically (top-level bindings) rather than by importing, so the file is not executed.

### Risk: 20
Author most likely prefers: the same for installed packages; local-module handling (static parse
vs. real import) could differ on modules with side effects or dynamic `__all__`.

---

## T20. Receiver that cannot be resolved

### Spec Text
> When the cursor follows a `.`, return attributes of the value before the dot.

### Alternatives
1. Unresolvable receiver → exit 1.
2. Unresolvable receiver → success with an empty `completions` array.

### Choice
Interpretation 2. The spec says "On success, exit **0** (even with zero completions)", and it
reserves exit 1 for file/position errors. An unknown receiver is a normal editing situation.

### Risk: 10
Author most likely prefers: the same.

---

## T21. Which methods contribute instance attributes

### Spec Text
> plus any attributes assigned in `__init__` via `self.name = ...`

### Alternatives
1. Only `__init__` (including an inherited `__init__` from a same-file base class).
2. Any method that assigns to `self`.

### Choice
Interpretation 1, read literally — `__init__` only, but resolved through the same-file base
classes that also provide inherited attributes.

### Risk: 25
Author most likely prefers: `__init__` only; whether an inherited `__init__` is scanned is the
part most likely to differ.

---

## T22. Class receivers and `__init__` attributes

### Spec Text
> **Classes** — ... return its methods and class attributes (including inherited ones from base
> classes defined in the same file).

### Alternatives
1. `MyClass.` excludes `self.x` attributes (they are on instances only).
2. `MyClass.` includes them, since the spec only spells out the difference in the instance bullet.

### Choice
Interpretation 1. The instance bullet says "the same attributes as the class **plus** ...", which
only makes sense if the class form lacks them.

### Risk: 20
Author most likely prefers: the same.

---

## T23. Receivers more complex than a bare name

### Spec Text
> return attributes of the value before the dot

### Alternatives
1. Only a single identifier or literal is supported as a receiver.
2. Dotted chains (`os.path.`), call results (`MyClass().`) and literal chains are resolved too.

### Choice
Interpretation 2, on a best-effort basis: the receiver text is scanned backwards (identifiers,
dots, balanced brackets, string literals), parsed as an expression and resolved recursively.
Anything that does not resolve yields zero completions (T20).

### Risk: 15
Author most likely prefers: at least dotted module chains; deeper forms are unlikely to be tested.

---

## T24. Cursor inside a string literal or comment

### Spec Text
> The prefix is determined by scanning backwards from the cursor to the start of the current
> identifier.

### Alternatives
1. Detect strings/comments and return nothing there.
2. Apply the same textual rule everywhere; a word inside a comment is just a prefix.

### Choice
Interpretation 2. The spec defines the context purely in terms of a backwards textual scan and
never mentions strings or comments.

### Risk: 30
Author most likely prefers: the same purely textual rule (a string/comment check would have been
worth a sentence), but a tokenizer-based implementation would suppress completions there.

---

## T25. Scope of the cursor when it sits below the last parsed statement

### Spec Text
> **Local scope** — names assigned or defined in the immediately enclosing function/method.

### Alternatives
1. Use the AST node ranges only: a cursor on a blank line after a function's last statement is at
   module scope.
2. Extend a function/class body through following blank lines and more-indented lines, so a
   cursor indented inside the body is still local.

### Choice
Interpretation 2, using the cursor column as the indent when the cursor line is blank. Completing
on a fresh indented line inside a function is the canonical use of such a tool; the AST's
`end_lineno` stops at the last statement and would misclassify it.

### Risk: 25
Author most likely prefers: an indentation-based rule as well, since the pure-AST reading breaks
the most obvious test fixture ("cursor on a new line inside a function").

---

## T26. Where keywords sort under fuzzy matching, and argument handling

### Spec Text
> 4. **Keywords** — sorted alphabetically after all names.

### Alternatives
1. Keywords always occupy the last rank, regardless of match mode or score.
2. Fuzzy matching introduces a relevance score that reorders groups.

### Choice
Interpretation 1: the four ranks are absolute; fuzzy changes only *which* items match, never the
ordering. The spec describes no scoring. Relatedly, the CLI accepts exactly the documented
argument shape — an unknown subcommand, a missing argument, a non-integer line/col or an extra
positional exits 1 with a message on STDERR.

### Risk: 10
Author most likely prefers: the same.

---

## T27. `None`, `True` and `False` are both keywords and `builtins` members

### Spec Text
> 4. **Builtin scope** — builtin names provided by Python's `builtins` module.
> When in a name-completion context, also include Python keywords as completions.

### Alternatives
1. Emit them once, as keywords (`type: "keyword"`, sorted into the keyword group).
2. Emit them once, as builtins (`type: "instance"`, `description: "instance of NoneType"`).
3. Emit them twice, once per source.

### Choice
Interpretation 1 — the keyword entry wins and the builtin entry for the same name is dropped.
In Python 3 these *are* keywords (they cannot be rebound), and duplicate entries in a completion
list would be a defect; making the keyword set exactly `keyword.kwlist` is also the most
predictable contract.

### Risk: 35
Author most likely prefers: keeping the builtin entry if their implementation seeds the result
dict with names first and appends keywords with an "already present" check.

---

## T28. Multiple assignments to the same name in one scope

### Spec Text
> For assignments: `instance of <type>` ... otherwise `statement`.

### Alternatives
1. The last binding at or before the cursor decides the reported type.
2. The first binding decides.

### Choice
The last binding at or before the cursor, except that a binding with no inferable value (e.g. an
augmented assignment or a `for` target) falls back to the most recent binding that *is*
resolvable. The latest assignment is what a reader of the code sees at the cursor; the fallback
keeps `x = 5` informative after a later `x += 1`.

### Risk: 30
Author most likely prefers: plain "last binding wins", with no fallback.

---

## T29. What counts as "a name" under the cursor

### Spec Text
> If the cursor is not on a name, exit 1.

### Alternatives
1. Any run of identifier characters counts, including keywords (`return`, `if`) and number
   literals (`42`); resolution then fails and returns an empty array.
2. Only a Python identifier that is not a keyword counts; anything else exits 1.
3. Identifiers *and* literals count, because the "Literals" rule says `infer` returns the
   builtin type of a literal.

### Choice
Interpretation 2, with `None`/`True`/`False` treated as names (they are spelled as
identifiers and do resolve to builtin values).  The cursor is "on a name" when the identifier
run covering it starts with a letter or `_`, is not a keyword, and does not fall inside a
string literal or comment.  The "Literals" rule is about how an *inferred value* is rendered
(`module_path` empty, `line`/`column` 0), not about parking the cursor on the literal itself;
the hard rule in the subcommand section governs cursor handling.

### Risk: 35
Author most likely prefers: the same for whitespace and operators, but may well return an
empty array (exit 0) rather than exit 1 when the cursor sits on a keyword or on a number.

---

## T30. Column 0 in the worked example vs. the column rule in the table

### Spec Text
> `{"name":"Calculator","type":"class", ... "line":7,"column":0, ...}`
>
> | `column` | int | 0-based column of the name identifier in the definition. ... For
> `class Bar:` this is the column of `B` in `Bar`. |

### Alternatives
1. The example wins: `column` is the column of the `class`/`def` keyword (0 for a top-level
   class), i.e. the statement's own column.
2. The table wins: `column` is the column of the identifier, so `class Calculator:` at the top
   level reports 6.

### Choice
Interpretation 2.  The table row is the normative description of the field and goes out of its
way to say "not the column of the `def` keyword"; nobody writes that sentence unless the
identifier column is intended.  The example object is most plausibly stale output kept from an
earlier revision (its `line: 7` does not match any file shown in the spec either).

### Risk: 30
Author most likely prefers: the table reading as well - but if the example is verbatim output
of their implementation, every class/def fixture would expect the keyword column instead.

---

## T31. Description of an assignment

### Spec Text
> For assignments: the right-hand expression or statement.

### Alternatives
1. The right-hand expression alone (`count = 10` -> `10`).
2. The whole statement (`count = 10` -> `count = 10`).

### Choice
Interpretation 1 when the binding has a right-hand expression, and the statement text when it
does not (`for item in items:`, `except E as e:`, `x: int`).  The sentence names the RHS first
and offers "or statement" as the fallback; the neighbouring row spells out "the import
*statement* text" when it wants a whole statement, so the contrast is deliberate.

### Risk: 40
Author most likely prefers: the full statement text (`count = 10`), which is what a
Jedi-shaped implementation reports for a statement definition.

---

## T32. `type`, `full_name` and description of an import binding

### Spec Text
> `goto` returns where the name at the cursor is assigned or defined (`def`, `class`,
> assignment, or import binding).
> For imports: the import statement text.

### Alternatives
1. The binding is a name of the *importing* module: `full_name` is `main.greet`, and `type`
   comes from whatever the import resolves to (`function`, `module`, ...).
2. `full_name` is the imported object's own qualified name (`helper.greet`).
3. `type` is `statement`, since an import binding is a statement.

### Choice
Interpretation 1.  `goto` deliberately stops at the import binding in the current file, so the
definition object describes a name of *this* module, and the table's rule "for top-level names:
`module.name`" then fixes `full_name` as `<this module>.<bound name>`.  `type` still describes
what the name refers to, which is what makes `import os` report `module`.  The description is
`ast.unparse` of the import statement, so spacing is normalised.

### Risk: 45
Author most likely prefers: `full_name` taken from the import target (`helper.greet`), since
that is the name the import actually refers to.

---

## T33. Spelling of the None type in definitions

### Spec Text
> For builtin types (including None, int, str, etc.), definitions use type "instance" and
> full_name "builtins.<name>" ...

### Alternatives
1. `name` is `NoneType` -> `builtins.NoneType`, `instance of NoneType` (the real class name).
2. `name` is `None` -> `builtins.None`, `instance of None` (the source spelling, and the one
   the spec itself uses when it enumerates the builtin types).

### Choice
Interpretation 2 for definition objects.  The spec lists the type as `None` next to `int` and
`str`, i.e. it uses value spelling rather than class spelling, and `builtins.None` is the form
a Jedi-shaped tool reports.  `complete` keeps `instance of NoneType` (see [T15](#t15-type-naming-for-singletons-and-constructor-calls))
because that command's own spec asked for `instance of <type>`.

### Risk: 35
Author most likely prefers: the same, unless their implementation derives every builtin name
from `type(value).__name__`, in which case `builtins.NoneType` appears everywhere.

---

## T34. How far `infer` follows an import

### Spec Text
> `goto` returns where the name at the cursor is assigned or defined ... or import binding.
> `infer` returns what the name at the cursor evaluates to after static propagation through
> assignments and calls.

### Alternatives
1. Both stop at the import binding.
2. `goto` stops at the import binding; `infer` follows the import into the other module and
   reports the `def`/`class`/assignment there.

### Choice
Interpretation 2 - it is the only reading under which the two commands differ for imported
names, and "import binding" is named only in the `goto` bullet.  So `infer` on an imported
`greet` reports `helper.py`, while `goto` reports the `from helper import greet` line.

### Risk: 20
Author most likely prefers: the same.

---

## T35. `goto` on an attribute assigned in `__init__`

### Spec Text
> `goto` answers where the identifier is defined/assigned at the cursor.
> Infer attributes from instance state when resolvable.

### Alternatives
1. Report the `self.x = ...` assignment inside `__init__` (line/column of `x` in `self.x`).
2. Report the class itself.
3. Report nothing, since `x` is not a module-level or class-level name.

### Choice
Interpretation 1, with `type` `statement`, `full_name` `module.Class.attr`, and the right-hand
expression as the description.  That assignment *is* where the attribute is defined, and it is
the location an editor's "go to definition" is expected to jump to.  Class-body attributes
(including dataclass fields) report their class-body binding instead.

### Risk: 25
Author most likely prefers: the same; the runner-up is reporting the enclosing class.

---

## T36. Cursor inside a string literal or a comment

### Spec Text
> If the cursor is not on a name, exit 1.

### Alternatives
1. The word under the cursor is still a run of identifier characters, so treat it as a name and
   try to resolve it (returning an empty array).
2. Text inside a string or a comment is not a name: exit 1.

### Choice
Interpretation 2.  A word inside `"hello"` or after a `#` is not a name in the Python grammar,
and reporting a definition for it would be plainly wrong.  String and comment spans are found
with `tokenize`, so a partially broken file still gets whatever spans were tokenised.

### Risk: 20
Author most likely prefers: the same for comments; an implementation that only looks at
identifier characters would return an empty array instead of exiting 1.

---

## T37. `infer` / `goto` in a file with syntax errors

### Spec Text
> (from the `complete` spec) Python syntax errors in the source file: **do not** exit with an
> error.  Parse as much as possible.

### Alternatives
1. The tolerance rule was written for `complete` only; `infer`/`goto` may fail on a broken file.
2. The same tolerant parse feeds all three subcommands.

### Choice
Interpretation 2 - the repaired parse is a property of the analyser, not of one subcommand, and
an editor calls `infer` on exactly the same half-typed buffers.  Definitions on both sides of a
broken line still resolve; a name that lives *inside* the broken region resolves only if it
survives the repair.

### Risk: 15
Author most likely prefers: the same.

---

## T38. The empty `### is None` section

### Spec Text
> ### `is None`

(The section has no body.)

### Alternatives
1. Do nothing: only `isinstance` narrows.
2. `if x is None:` narrows `x` to `None` in the body; `if x is not None:` removes `None` from
   the possible types in the body.
3. The above plus the inverse in the matching `else` branch.

### Choice
Interpretation 3.  The heading sits under "Flow-Sensitive Type Narrowing" beside the
`isinstance` heading, so the intent is clearly that `is None` narrows too; the `else` branch of
`if x is None:` is the classic reason to write the test at all, and handling it costs nothing
when a name's type is unknown.  `isinstance` narrowing is likewise inverted in the `else`
branch (the class is removed from the union), and both apply to `and`-chained tests.

### Risk: 40
Author most likely prefers: the positive-branch half only (`if x is None:` -> `None`,
`if x is not None:` -> the non-None types), with nothing happening in `else` branches.

---

## T39. `full_name` of a name that is not top-level

### Spec Text
> Dot-separated qualified name.  For top-level names: `module.name`.  For nested:
> `module.Class.method`.

### Alternatives
1. Only classes contribute a component, so a local variable in a function is `module.local`.
2. Every enclosing scope contributes, so a local in `outer()` is `module.outer.local` and a
   parameter is `module.use.height`.
3. Locals and parameters have no qualified name (empty string).

### Choice
Interpretation 2 - the rule is stated as a *qualified* name, and `module.Class.method` is just
the two-level case of "join the enclosing scopes".  Dropping function scopes would make two
different locals share one `full_name`.

### Risk: 35
Author most likely prefers: the same for methods; locals and parameters are the uncertain part
and could come back as `module.name` or empty.

---

## T40. `module_path` and module name below the project root

### Spec Text
> `module_path` ... File path where the name is defined, relative to the project root.
> Module name is the filename without `.py`.

### Alternatives
1. `pkg/mod.py` -> `module_path` `pkg/mod.py`, module name `mod`.
2. `pkg/mod.py` -> `module_path` `pkg/mod.py`, module name `pkg.mod` (the dotted path from the
   project root, with `__init__.py` naming its package).

### Choice
Interpretation 2.  "The filename without `.py`" describes the flat case the spec's example
uses; for a file in a package the dotted path is what keeps `full_name` unique and matches the
way the module would be imported.  Definitions outside the project root (standard library)
report their absolute path and their own `__name__`, since a `../../..` relative path would be
useless.

### Risk: 30
Author most likely prefers: the same, unless their implementation literally applies
"filename without .py", which yields `mod.thing` for `pkg/mod.py`.

---

## T41. `type` of a `goto` result for an assignment

### Spec Text
> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`. |

### Alternatives
1. `statement` - the binding is an assignment statement.
2. The type of the value assigned (`instance` for `x = Calculator()`).

### Choice
Interpretation 1.  `infer` already answers "what is it", so `goto` answering "where is it bound"
with `statement` is what gives the `statement` member of the enum a purpose; under
interpretation 2 nothing would ever be a `statement`.

### Risk: 20
Author most likely prefers: the same.

---

## T42. `docstring` of a synthesized builtin definition

### Spec Text
> `docstring` | The docstring of the definition, or empty string if none.
> For builtin types ... module_path set to empty string and line/column set to 0.

### Alternatives
1. `""` - the builtin definition is synthesized, and the spec already strips it of location.
2. The real docstring of the builtin class (`int.__doc__`).

### Choice
Interpretation 1 for builtin *type* definitions (`int`, `str`, `None` ...): they are built by
hand from a name, not looked up, and `"docstring": ""` matches the way `module_path`/`line`
are blanked out.  Live objects that are genuinely resolved by name (`len`, an imported stdlib
class) do report their real docstring, and an instance of a class defined in the project
reports that class's docstring.

### Risk: 40
Author most likely prefers: the same for `None`, but an implementation that reaches for
`getattr(builtins, name).__doc__` would fill in `int`'s docstring.

---

## T43. `line` and `column` of a module definition

### Spec Text
> `line` | int | 1-based line number of the definition.

### Alternatives
1. A module has no definition site: `line` 0, `column` 0.
2. A module starts at its first line: `line` 1, `column` 0.

### Choice
Interpretation 1.  `line` is documented as the line *of the definition*, and a module has none;
0 is the same "no location" marker the spec already uses for builtins, which keeps the sort key
meaningful.

### Risk: 35
Author most likely prefers: `line: 1`, if their implementation points module definitions at the
top of the file.

---

## T44. Which bindings stay alive at the cursor

### Spec Text
> Multiple definitions are returned when a name could resolve to more than one thing (e.g.,
> conditional assignments).
> For unresolved branches, return all reachable possibilities.

### Alternatives
1. Every binding before the cursor is returned (so `x = 1` then `x = 2` returns both).
2. Only the last binding is returned (so conditional assignments lose one branch).
3. A binding shadows an earlier one only when it runs unconditionally relative to it: the
   branch path of each binding is compared, and alternatives in sibling branches both survive.

### Choice
Interpretation 3.  It is the only one that satisfies both sentences: `if/else` assignments are
both "reachable possibilities", while a later unconditional `x = 'text'` really does overwrite
whatever a preceding branch stored.  A binding inside a branch does *not* kill an earlier
unconditional one, so `x = 1` followed by `if c: x = 's'` reports both.

### Risk: 30
Author most likely prefers: the same for the `if/else` fixture in the spec; a simpler
implementation that returns every binding before the cursor would differ on
"assign, then reassign".

---

## T45. Expressions the inference rules do not mention

### Spec Text
> `infer` returns what the name at the cursor evaluates to after static propagation through
> assignments and calls.

### Alternatives
1. Only literals, names, calls and attributes are inferred; anything else is unresolved.
2. Also infer the obvious cases: `a + b` when one side is a known builtin scalar, comparisons
   (`bool`), `a if c else b` and `a or b` (the union of both sides), and a parameter's type
   from its default value.

### Choice
Interpretation 2.  "Static propagation" is open-ended, and without it a textbook function such
as `def greet(name): return "hi " + name` would infer nothing at all.  Where both operands of a
binary operation are unknown the result stays unresolved, so nothing is invented out of thin
air.

### Risk: 25
Author most likely prefers: the same for `a if c else b`; parameter defaults and `"hi " + name`
are the parts most likely to come back empty in a stricter implementation.

---

## T46. Description of a parameter definition

### Spec Text
> `description` | string | Short description.  For functions: `def name(params)`.  For classes:
> `class Name`.  For instances: `instance of <ClassName>`.  For assignments: ...  For imports: ...

### Alternatives
1. `param <name>` (mirroring `def <name>(...)`).
2. The bare word `param`.
3. The parameter's source text, including any annotation and default.

### Choice
Interpretation 1 for definition objects.  The table gives a `<kind> <name>` template for every
row it does specify, and `param height` is what a definition-oriented tool reports.
`complete` keeps the bare `param` chosen in [T10](#t10-description-of-a-function-parameter),
since that command's table row was the one under discussion there.

### Risk: 45
Author most likely prefers: `param <name>` here too, but a shared description helper would make
both commands agree, and only one of the two can match.

---

## T47. `goto` on a builtin name

### Spec Text
> If no definition is found, return an empty array (exit 0).
> For builtin types ... definitions use type "instance" and full_name "builtins.<name>" ...

### Alternatives
1. A builtin has no source location, so `goto` returns an empty array.
2. `goto` returns the same location-less definition object `infer` does (`module_path` `""`,
   `line`/`column` 0), with the builtin's own kind (`function` for `len`, `class` for `int`).

### Choice
Interpretation 2.  The spec explicitly defines what a builtin definition object looks like, and
`len` *is* defined - just not in a file the tool can point at.  Returning the object is strictly
more informative, and the empty-array rule is reserved for names that resolve to nothing.

### Risk: 30
Author most likely prefers: the same; an implementation that only emits definitions it can give
a file for would return an empty array.

---

## T48. A `--project` directory that does not exist

### Spec Text
> All commands now accept an optional `--project <dir>` flag. When provided, the project root
> is `<dir>`.

### Alternatives
1. Exit 1 with a message on STDERR, like any other bad path argument.
2. Accept it silently: an empty root simply resolves no modules, so every import becomes
   unresolvable and the command still exits 0.

### Choice
Interpretation 1. The original spec reserves exit 1 for "file or position errors", and a
project root that is not a directory is a file error of exactly that kind. Silently analysing
against a root that cannot exist would report "unresolvable" for imports that are in fact
perfectly resolvable, which is a worse failure than a clear message. A `--project` with no
value, and any unrecognised `--flag`, are usage errors for the same reason.

### Risk: 35
Author most likely prefers: the same, but an implementation that just stores the string and
lets `os.path.isfile` checks fail would exit 0 with empty results.

---

## T49. Are installed third-party packages resolvable?

### Spec Text
> **Module search order:**
> 1. Project root — scan for `.py` files and packages (directories containing `__init__.py`).
> 2. Standard library — recognize stdlib modules available in the target runtime.
> 3. If a module cannot be found, treat it as unresolvable ...
> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib),
> return the import statement as a fallback.

### Alternatives
1. The two-entry search path is exhaustive: anything that is neither a project file nor a
   stdlib module is unresolvable, including installed site-packages distributions.
2. Site-packages are importable at runtime, so resolve them too and treat the numbered list as
   a priority order rather than a whitelist.

### Choice
Interpretation 1. The list is written as *the* search order with a numbered fallthrough to
"unresolvable", and the `--follow-imports` paragraph names "third-party" alongside "stdlib" as
things that "cannot be found". Stdlib membership is tested with `sys.stdlib_module_names`, so
`import pyflakes` (installed in this venv) resolves to nothing while `import json` resolves.

### Risk: 40
Author most likely prefers: the same for `goto`, but an implementation that simply calls
`importlib.import_module` for the non-project case would resolve third-party packages for
`infer` and completion, differing on any fixture that imports an installed distribution.

---

## T50. `goto` on an unresolvable import: empty, or the import statement?

### Spec Text
> If a module cannot be found, treat it as unresolvable — `infer` and `goto` return empty
> results, completions return nothing for that module's attributes.
> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib),
> return the import statement as a fallback.
> With `--follow-imports`, if the terminal target cannot be resolved, return the import site in
> the current file as the fallback definition.

### Alternatives
1. The search-order bullet wins: `goto` on a name imported from a missing module is empty.
2. The `goto`-specific rules win: `goto` on a *bound* name always has somewhere to point — the
   import statement — whether or not the module resolves. The "empty results" bullet then
   covers the cases where nothing in the current file is bound, e.g. `goto` on `missing.attr`.

### Choice
Interpretation 2. The fallback is stated twice, once in the `goto` section and once in the
Clarifications, both times without an exception for "module not found"; and it is the only
reading under which plain `goto` and `goto --follow-imports` agree on a stdlib import, which
the spec's own example requires. So `goto` on `thing` in `from nope import thing` reports the
import line, while `goto` on `nope.thing` reports nothing. `infer` stays empty in both cases.

### Risk: 30
Author most likely prefers: the same for `--follow-imports`; an implementation that checks
resolvability first could return an empty array for the plain-`goto` case.

---

## T51. Does `--follow-imports` walk into the standard library's own source?

### Spec Text
> With `--follow-imports`, `goto` follows the import chain and returns the actual definition in
> the source module.
> If the import chain leads to a module that cannot be found (e.g., third-party or stdlib),
> return the import statement as a fallback.

### Alternatives
1. "Cannot be found" means "has no file at all" (a C builtin like `sys`), so `from os import
   getcwd --follow-imports` should land in the real `os.py`.
2. "Cannot be found" means "not found by the module search", i.e. not a project file. Every
   stdlib target therefore falls back to the import statement, exactly as the parenthetical says.

### Choice
Interpretation 2. The spec puts "stdlib" in the same breath as "third-party" as an example of
a module that cannot be found, which only makes sense if *following* is a project-file
operation. It also keeps the output stable: a follow that landed in
`/usr/lib/python3.13/os.py` would emit an absolute, machine-specific `module_path` that no
fixture could assert on.

### Risk: 25
Author most likely prefers: the same; the runner-up is following into stdlib source, which a
Jedi-backed implementation would do by default.

---

## T52. Where the `--follow-imports` fallback points on a broken chain

### Spec Text
> With `--follow-imports`, if the terminal target cannot be resolved, return the import site in
> the current file as the fallback definition.

### Alternatives
1. The import site *in the current file* — the statement under the cursor's own module, however
   many hops the chain managed before dying.
2. The last import site the chain reached, i.e. the deepest module whose import could not be
   followed further.

### Choice
Interpretation 1, which is what the clarification literally says. For `main.py` →
`mid.py` → `os`, `goto --follow-imports` on the name in `main.py` reports `main.py`'s own
import line, not `mid.py`'s. Attribute `goto` (`mid.target`) is different: there the "current
file" for the lookup is `mid.py`, so an unfollowable re-export reports `mid.py`'s import line —
the same thing plain `goto` reports for that cursor.

### Risk: 30
Author most likely prefers: the same for the name case; an implementation that returns whatever
the recursion last produced would report the deepest import site.

---

## T53. Which names `from X import |` offers

### Spec Text
> `from X import ...` suggests names inside module `X`.
> Import completions use the same ordering rules (public → private → dunder) and prefix
> matching as name completions.
> In `from X import ...` completion, exported names come from `__all__` when it exists;
> otherwise use names that do not start with `_`.

### Alternatives
1. Offer exactly the exported set — `__all__`, else non-underscore names. The ordering rule is
   then only exercised by an `__all__` that itself lists private or dunder names.
2. Offer every top-level name (private ones included, since `from x import _helper` is legal),
   and let the public → private → dunder ordering do the sorting the spec mentions.

### Choice
Interpretation 1. The Clarifications section states the filter outright, and a clarification
that narrow is there precisely to settle this question; the ordering sentence is then about
*how to sort whatever is offered*, which still matters for an `__all__` like
`['alpha', '_priv', '__magic__']`. Attribute completion (`mod.<TAB>`) is unaffected and keeps
showing non-underscore attributes regardless of `__all__`, because attribute access is not
restricted by `__all__`.

### Risk: 30
Author most likely prefers: the same; the clearest divergence is a fixture that types
`from x import _|` and expects the private name back.

---

## T54. What `import |` lists

### Spec Text
> `import ...` suggests top-level module/package names.
> **Module search order:** 1. Project root ... 2. Standard library ...

### Alternatives
1. Project root entries only — the spec's new material is about projects.
2. Everything `import` could actually name: project root entries *and* stdlib top-level module
   names, in that order of preference.

### Choice
Interpretation 2. The search order says a bare module name is looked up in the project and then
in the stdlib, so both are legitimate answers to "what could follow `import`"; offering only
project files would make `import js|` complete to nothing even though `import json` works.
Names are de-duplicated with the project winning, matching the resolution order.

### Risk: 25
Author most likely prefers: the same; an implementation that only scanned the project root
would return a strictly smaller list, which a fixture asserting `"json" in names` would catch.

---

## T55. Import positions the spec does not enumerate

### Spec Text
> - `import |` suggests top-level module/package names.
> - `from X import |` suggests names inside module `X`.
> - `from X.Y import |` suggests names inside submodule `X.Y`.

### Alternatives
1. Only those three shapes are import contexts; anything else falls back to ordinary name
   completion.
2. Treat the whole import statement as an import context, deriving the rest by analogy:
   `from X|` completes module names, `import X.|` completes submodules of `X`, `from .|`
   completes within the current package, a name after a comma behaves like the first name, and
   a cursor after `as` or on `*` yields nothing.

### Choice
Interpretation 2. The listed shapes are examples of one rule — "completion now handles import
statements" — and returning builtins and keywords in the middle of `from |` would be plainly
wrong for an editor. Parenthesised and backslash-continued import lists are joined into one
logical line, so `from x import (\n    na|` still completes names from `x`.

### Risk: 35
Author most likely prefers: the same for `from X|` and commas; `import X.|` and the empty
result after `as` are the likeliest places to differ (an implementation keyed only on the three
listed shapes would fall through to ordinary name completion there).

---

## T56. `module_path` of a namespace package

### Spec Text
> The same import rules apply to regular packages and namespace packages.
> `module_path` ... File path where the name is defined, relative to the project root.

### Alternatives
1. The directory itself (`ns`), since that is where the "module" lives.
2. The empty string, as for builtins, because a namespace package has no file.

### Choice
Interpretation 1. A regular package reports `pkg/__init__.py`, and the nearest equivalent for a
namespace package is the directory that stands in for it; an editor can still open it. `line`
and `column` are 0, matching the way a module definition is reported ([T43](#t43-line-and-column-of-a-module-definition)).

### Risk: 45
Author most likely prefers: unclear — `""` is just as defensible, and an implementation that
only ever produced `__init__.py` paths might not emit a definition for a bare namespace package
at all.

---

## T57. Submodules as attributes of a package that never imports them

### Spec Text
> Project root — scan for `.py` files and packages (directories containing `__init__.py`).
> `from X import ...` suggests names inside module `X`.

### Alternatives
1. Static view: `pkg.mod` and `from pkg import mod` resolve whenever `pkg/mod.py` exists, even
   if `pkg/__init__.py` never imports it.
2. Runtime view: a submodule is an attribute of its package only after something imports it, so
   `from pkg import mod` resolves only when `__init__.py` imports `mod`.

### Choice
Interpretation 1. "Scan for `.py` files and packages" describes a filesystem scan, not an
execution, and `from pkg import mod` is legal Python whether or not `__init__.py` mentions it;
an editor that refused to resolve it would be wrong on ordinary code. When the package defines
`__all__`, `from pkg import |` still lists exactly `__all__` ([T53](#t53-which-names-from-x-import--offers)),
so submodules outside it are not offered.

### Risk: 20
Author most likely prefers: the same.

---

## T58. `goto` on the module part of `from X import y`

### Spec Text
> Without `--follow-imports` (default), `goto` on an imported name returns the `import`
> statement itself.

### Alternatives
1. `X` is part of the import statement too, so `goto` on it returns that statement, and only
   `--follow-imports` opens `X`'s file.
2. `X` is not a *name bound by* the statement, it is a reference to a module; `goto` on it
   points at the module's file under both modes.

### Choice
Interpretation 2, unchanged from the previous revision's behaviour. The rule is about "an
imported name", i.e. the name the statement binds (`y`); the module reference resolves to the
module itself, and jumping to the import line the cursor is already on would be a no-op.
`import X` is different: there `X` *is* the bound name, so plain `goto` reports the statement.

### Risk: 35
Author most likely prefers: the same; an implementation that maps every cursor inside an import
statement to that statement's binding would report the import line for `X` as well.

---

## T59. "rename maps" in the Path Convention section

### Spec Text
> All paths in output fields (`module_path`, file paths in rename maps, etc.) use forward-slash
> separators (POSIX convention) regardless of the host operating system.

### Alternatives
1. A `rename` command is implied and should be built.
2. The sentence is a generic statement of the path convention, and "rename maps" refers to
   output the tool does not (yet) produce; only the fields that exist are affected.

### Choice
Interpretation 2. Nothing else in this or the previous spec mentions renaming: there is no
command, no output shape, and no behaviour described for it. Inventing a command from a
parenthetical would be a much bigger leap than reading the clause as boilerplate. Every path
the tool emits — `module_path` in `infer`/`goto`, including the absolute paths used for
definitions outside the project root — now uses forward slashes.

### Risk: 10
Author most likely prefers: the same; the clause reads as carried over from a shared style
note.

---

## T60. `--follow-imports` on `infer` and `complete`

### Spec Text
> ```
> python sith.py goto <file> <line> <col> [--follow-imports]
> ```

### Alternatives
1. The flag belongs to `goto` alone; passing it to another command is a usage error.
2. Accept it everywhere and ignore it where it has no meaning — `infer` already follows imports
   by definition, and completion has no import-site fallback to suppress.

### Choice
Interpretation 2. Rejecting a harmless flag would only trip up an editor that passes a fixed
argument list, and the spec never says the flag is rejected elsewhere — it just documents it on
the line where it does something. `--project` is documented for all three commands and behaves
identically everywhere.

### Risk: 15
Author most likely prefers: the same; a strict `argparse` subparser setup would error instead.

---

## T61. Relative imports in a file that sits at the project root

### Spec Text
> If the relative import goes above the project root, it is unresolvable.

### Alternatives
1. A file directly under the root is in the root "package", so `from . import helper` resolves
   `helper.py` next to it and only `..` goes above the root.
2. The root is not a package (it usually has no `__init__.py`), so any relative import from a
   file directly beneath it is unresolvable.

### Choice
Interpretation 1. The spec draws the line at "above the project root", which puts the root
itself inside bounds, and the namespace-package clarification says a directory without
`__init__.py` is still a package. So one dot stays at the root and two dots are unresolvable —
the level count is compared against the importing file's depth below the root.

### Risk: 30
Author most likely prefers: the same; an implementation that requires an `__init__.py` to form
a package would make one dot unresolvable at the root too.

---

## T62. Whether `__all__` also filters attribute access

### Spec Text
> A name is public if: The module defines `__all__`: use exactly those names.

### Alternatives
1. `__all__` governs star imports and `from X import |` completion only; `mod.anything` still
   resolves, because `__all__` has no effect on attribute access in Python either.
2. `__all__` defines the module's whole public surface, so `mod.<TAB>` is filtered by it as well.

### Choice
Interpretation 1. The `__all__` rule appears under "Star Imports", defining which names become
*visible in the importing module*, and is repeated in the Clarifications for `from X import`
completion — both name-import contexts. Attribute completion keeps its existing rule of hiding
underscore-prefixed names, which is what Python's own `dir()`-shaped tooling does.

### Risk: 25
Author most likely prefers: the same; an implementation with a single "public names of a
module" helper would apply `__all__` to attribute completion too.

---

## T63. `pkg/` and `pkg.py` both present

### Spec Text
> Project root — scan for `.py` files and packages (directories containing `__init__.py`).

### Alternatives
1. The order of the sentence is the order of the scan: `.py` file first, package second.
2. CPython's own order: a package (`pkg/__init__.py`) shadows a module (`pkg.py`), and a
   namespace directory loses to both.

### Choice
Interpretation 2. The sentence enumerates what is scanned, not a precedence, and matching the
interpreter's real precedence is the only choice that agrees with what the user's code will do
at runtime. So package > module > namespace directory.

### Risk: 20
Author most likely prefers: the same; this only matters for a fixture that deliberately creates
both, which would most likely be written to assert the CPython behaviour.

---

## T64. What a circular import makes visible

### Spec Text
> Circular imports: do not infinite-loop. If module A imports B and B imports A, resolve what is
> available at the point of the circular reference and move on. Names not yet defined at the
> point of circular import are simply not visible.

### Alternatives
1. Model execution order: when resolving through the cycle, only the names textually above the
   `import` statement in the partially-executed module are visible.
2. Model the file as a whole: every module is parsed statically, so all of its top-level names
   are visible; the cycle is broken by a visit set rather than by an execution point.

### Choice
Interpretation 2. The tool never executes code, so there is no "point of execution" to cut at —
the cut the spec asks for is the one that keeps resolution terminating, which a per-chain visit
set and a depth cap provide. The practical difference is narrow: interpretation 1 would hide a
name defined below the `import` line in the other module, which static tools (and the previous
revision's visibility rule, [T3](#t3-is-a-name-visible-on-the-very-line-that-defines-it)) do not do.

### Risk: 35
Author most likely prefers: the same for termination; a fixture built to test "not yet defined"
visibility — importing a name defined below the circular import line — would expect an empty
result where this implementation resolves it.

---

## T65. The JSON key each new subcommand prints under

### Spec Text
> ### `signatures`
> ... return the function's signature(s) ...
> ### `references`
> ... Find all locations where the name at the cursor is referenced ...
> ### `search`
> ... Returns definitions (not usages).
> ### `names`
> ... List names defined in a file.

### Alternatives
1. Every command gets a key named after itself: `signatures`, `references`, `search`, `names`.
2. Commands that return definition objects reuse the existing `definitions` key, so `search`
   and `names` print `{"definitions": [...]}`.
3. The command-shaped key for the three noun commands, and a generic `results` for `search`,
   whose name is a verb.

### Choice
Interpretation 3. The existing tool names the array after *what it contains*
(`completions`, `definitions`), and the spec's headings give three of the new commands a
plural noun that is already the right container name. `search` is the odd one out — a
`{"search": [...]}` key reads wrong and the spec never calls its rows "searches" — so its rows
go under `results`, which is what the spec calls them ("Each result has the same fields ...").
`search` rows are *not* full definition objects (no `docstring`), so reusing `definitions`
would be misleading.

### Risk: 45
Author most likely prefers: the same for `signatures`/`references`/`names`; for `search` a
coin-flip between `results` and `definitions`.

---

## T66. What a `signatures` entry looks like for a class

### Spec Text
> | `name` | string | Function or class name. |
> | `description` | string | `"def name(params)"` ... The `self` parameter is excluded for
> methods. |

### Alternatives
1. `C(|)` reports `__init__`: `name` is `"__init__"`, params include `self`.
2. `C(|)` reports the class: `name` is the class name, `params` are `__init__`'s minus `self`,
   `description` is `"def C(params)"`, `docstring` is the class docstring.

### Choice
Interpretation 2. The `name` row says "Function *or class* name", which only makes sense if a
class callable reports the class; and the `self`-exclusion note exists precisely because the
parameters shown come from a method (`__init__`) while the name shown does not. The docstring
falls back to `__init__`'s when the class has none.

### Risk: 20
Author most likely prefers: the same; the fallback of `docstring` to `__init__`'s when the
class has no docstring is the part most likely to differ (they may return `""`).

---

## T67. Is `self` dropped from `params` too, or only from `description`?

### Spec Text
> `description` ... The `self` parameter is excluded for methods.

### Alternatives
1. Only the rendered `description` drops `self`; `params` still lists it, and `index` counts it.
2. `self` is dropped from the signature entirely, so `params`, `index` and `description` all
   agree.

### Choice
Interpretation 2. A `params`/`description` pair that disagreed would be unusable, and `index`
is defined as "0-based index of the parameter the cursor is currently on" — for `obj.m(|)` the
cursor is on the first *real* parameter, which must be index 0. The note lives in the
`description` row only because that is the row where the rendering is spelled out.

### Risk: 15
Author most likely prefers: the same. The residual risk is `cls` on a `classmethod`, which
this implementation also drops (the spec names only `self`).

---

## T68. Positional-only `/` and keyword-only `*` markers

### Spec Text
> Special forms: `"*args"`, `"**kwargs"`, `"*args: type"`, `"**kwargs: type"`.

### Alternatives
1. `params` and `description` also carry the bare `*` and `/` separators that Python uses to
   mark keyword-only and positional-only parameters.
2. Only real parameters appear; `*` and `/` are dropped.

### Choice
Interpretation 2. The spec enumerates the special forms exhaustively and every one of them is
a named parameter; a bare `*` has no `name`, no `type` and no `index`, so it cannot be "a
parameter representation". `index` also stays consistent with `params` this way.

### Risk: 30
Author most likely prefers: the same for `params`; a `description` built by the usual
"render a signature" helper would very likely include `*` and `/`, so a fixture with
keyword-only parameters could disagree on `description`.

---

## T69. `index` when the call has no arguments typed yet

### Spec Text
> `index` | int or null | 0-based index of the parameter the cursor is currently on. `null` if
> the cursor is past all parameters or in an ambiguous position.

### Alternatives
1. With the cursor at `f(|)` nothing has been typed, so there is no parameter yet: `null`.
2. The cursor is on the first parameter slot, so `0` — unless the function declares no
   parameters at all, in which case `null`.

### Choice
Interpretation 2. Signature help exists to highlight the parameter you are about to type, and
`f(|)` is exactly the moment the first parameter matters. `null` is reserved for "past all
parameters", which an empty parameter list is.

### Risk: 10
Author most likely prefers: the same; highlighting parameter 0 on an empty argument list is
what every editor does.

---

## T70. Does dynamic parameter inference change the rendered `params` strings?

### Spec Text
> When a function has no type annotations and no stub, the tool can optionally infer parameter
> types by finding call sites. This is enabled by default and affects `infer` and `signatures`.

and

> Each param is rendered as: `"name"` for bare parameters, `"name: type"` for annotated
> parameters ...

### Alternatives
1. An inferred parameter type is rendered like an annotation, so a bare `a` becomes `"a: int"`
   once a call site passes an `int`.
2. `params` is rendered from the source text of the declaration only. Dynamic inference feeds
   the *values* the tool reasons about — what `infer` reports for a parameter name, and what a
   call on a parameter resolves to — which is how it "affects" `signatures` indirectly.

### Choice
Interpretation 2. The rendering table is written in terms of what is *written* in the
declaration ("bare parameters", "annotated parameters", "parameters with defaults") and is
exhaustive about spacing, which only makes sense for source-derived text. Interpretation 1
would also make the same function render differently depending on unrelated call sites
elsewhere in the file, which no signature-help UI does.

### Risk: 40
Author most likely prefers: the same, but this is the least-pinned sentence in the spec; if
their implementation renders inferred types, every bare-parameter fixture with a call site in
the file disagrees.

---

## T71. An incomplete keyword name as the argument under the cursor

### Spec Text
> - Keyword arguments map to the matching declared parameter when present.
> - Unknown keyword arguments map to `**kwargs` when available, otherwise `index` is `null`.

### Alternatives
1. Only a complete `name=` counts as a keyword argument; a bare word is always positional.
2. A bare word in the last argument slot is also matched against the not-yet-used parameter
   names by prefix, once the positional reading has run out of parameters.

### Choice
Interpretation 2, but only as a fallback. `f(1, 2, b|)` against `def f(a, b)` has no third
positional slot, so the positional reading yields `null`; reading the half-typed `b` as the
start of `b=` recovers index 1, which is what the user is actually typing. When a positional
slot is available it always wins, so the common cases are unaffected.

### Risk: 25
Author most likely prefers: the same (this is the classic signature-help behaviour), though a
strict reading of the two bullets gives `null`.

---

## T72. What "the same symbol identity" means

### Spec Text
> For project-scope search, return only occurrences that resolve to the same symbol identity as
> the cursor target (do not include same-spelling but unrelated symbols in other scopes).

### Alternatives
1. Identity is the defining binding: two occurrences match when following each of them to a
   definition (through imports) lands on the same source location.
2. Identity is the fully-qualified dotted name.
3. Identity is nominal — anything spelled the same in a reachable scope.

### Choice
Interpretation 1. It is the only reading that distinguishes a local `x` in one function from a
local `x` in another (same qualified name is not available for locals, and same spelling is
explicitly excluded). Occurrences are matched by intersecting the `goto --follow-imports`
result sets, so an `import` alias, the imported name and the original `def` all share one
identity. The same rule is applied for `--scope file`, so file scope is simply project scope
restricted to one file.

### Risk: 30
Author most likely prefers: the same for project scope. For `--scope file` the spec only says
"search only within the target file", so an author whose file-scope path is a plain name scan
would also report unrelated same-spelling locals.

---

## T73. Is a parameter a "defining occurrence"?

### Spec Text
> `is_definition` | bool | `true` if this is the defining occurrence (assignment, `def`,
> `class`, import).

### Alternatives
1. The list is exhaustive: a parameter in a `def` header is a reference, not a definition.
2. The list is illustrative of "where the name is introduced"; a parameter introduces a name,
   so it is a definition.

### Choice
Interpretation 2. `references` on a parameter must report the header occurrence, and the
Clarifications say "`references` output always includes the definition occurrence when one is
found" — for a parameter the header *is* that occurrence, so it has to carry
`is_definition: true`. `for` targets, `with ... as` and `except ... as` are treated the same
way (they are assignments).

### Risk: 20
Author most likely prefers: the same; a `Name.ctx is Store` / `is a param` test is the natural
implementation.

---

## T74. Are attribute occurrences (`obj.name`) references?

### Spec Text
> Find all locations where the name at the cursor is referenced (used or defined).

### Alternatives
1. Only plain names count; `obj.method` is an attribute access, not an occurrence of `method`.
2. Attribute occurrences count when they resolve to the same definition, which is how a method
   or a `self.x` field is actually referenced.

### Choice
Interpretation 2. `references` on a method's `def` line is useless if the call sites
`obj.method()` are not reported, and the identity rule (T72) already keeps unrelated
same-named attributes out. Attribute occurrences whose `goto` does not reach the cursor's
definition are dropped.

### Risk: 25
Author most likely prefers: the same; the risk is that a resolution failure on an attribute
silently drops a call site they include.

---

## T75. What `search` indexes: class attributes and imports

### Spec Text
> - Search all `def`, `class`, and top-level assignment names across project files.
> - Do not search inside function/method bodies (local variables are not searchable).

### Alternatives
1. "top-level" is literal: only module-level assignments; class bodies contribute their `def`s
   and nested `class`es but not their attribute assignments.
2. "top-level" means "not inside a function", which is the exclusion the second bullet states;
   class-body assignments are therefore included.

### Choice
Interpretation 2. The two bullets read as one rule — walk the file, descend into class bodies,
stop at function bodies — and the only exclusion the spec actually names is function/method
bodies. Imports are *not* included: the spec lists `def`, `class` and assignments, and names
imports explicitly only in the `names` clarification, so leaving them out is the deliberate
difference between the two commands.

### Risk: 35
Author most likely prefers: including class attributes as here; the likelier disagreement is
imports, where an implementation that reuses the `names` collector would include them.

---

## T76. The `type` and `description` of a `search` hit

### Spec Text
> Each result has the same fields as a definition object (from `infer`/`goto`), minus
> `docstring`.

### Alternatives
1. Re-derive the fields for a "search" context.
2. Reuse exactly what `goto` would print for that definition, then delete `docstring`.

### Choice
Interpretation 2, literally. A module-level `TOTAL = 10` therefore has `type` `"statement"` and
`description` `"10"`, a `def` has `"function"` / `"def name(params)"`, a `class` has `"class"` /
`"class Name"` — the same objects the existing commands already produce and the existing tests
already pin.

### Risk: 10
Author most likely prefers: the same; "the same fields as a definition object" is explicit.

---

## T77. Which bindings `names` counts as module level

### Spec Text
> Default: only module-level names (top-level functions, classes, assignments, imports).
> `--all-scopes`: include names from all scopes (locals inside functions, class attributes,
> nested defs).

### Alternatives
1. Only statements physically at indentation zero.
2. Every binding whose scope is the module scope — which includes names bound inside a
   module-level `if`, `try` or `for`, since Python has no block scope.

### Choice
Interpretation 2. "Module-level" is a scope, not a column; a `def` inside `if TYPE_CHECKING:`
binds a module-level name and the rest of the tool already treats it that way. Parameters are
included under `--all-scopes` (they are names defined in the file, and the spec's "locals
inside functions" is exactly where they live).

### Risk: 20
Author most likely prefers: the same for the scope question; parameters under `--all-scopes`
are the part most likely to differ.

---

## T78. `--all-scopes` and `self.x` attributes

### Spec Text
> `--all-scopes`: include names from all scopes (locals inside functions, class attributes,
> nested defs).

### Alternatives
1. `self.x = 1` in `__init__` defines an attribute of the class, so it is a name in the file.
2. Only real scope bindings are listed; `self.x` is an attribute assignment, and its `self` is
   already listed as a parameter and `x` is not a name in any scope.

### Choice
Interpretation 2. The spec's three examples are all lexical scopes ("locals inside functions,
class attributes, nested defs"), and "class attributes" is naturally read as the class body's
own assignments, which *are* scope bindings. Adding synthesized attribute rows would also give
entries whose `line`/`column` point into a method body while claiming class ownership.

### Risk: 25
Author most likely prefers: the same; a jedi-shaped implementation would also omit them.

---

## T79. Where `goto` lands when a name exists in both the stub and the source

### Spec Text
> `goto` still navigates to the `.py` source (not the stub), unless the definition only exists
> in the stub.

### Alternatives
1. Only the `.py` location is returned.
2. Both are returned, `.py` first.

### Choice
Interpretation 1, and "only exists in the stub" is decided per *name*: if the runtime module
binds the name, `goto` reports the runtime binding and the stub is not consulted; if it does
not, the stub binding is reported. The same mapping is applied to `infer`'s definition objects
— a value whose type came from the stub still reports the `.py` file, line and column, because
that is where the thing is defined.

### Risk: 20
Author most likely prefers: the same; the residual risk is `infer`, where an implementation
that does not map back would print the `.pyi` path.

---

## T80. Does a stub hide names the `.py` defines but the stub omits?

### Spec Text
> If a stub exists, type information (function signatures, return types, class attributes)
> comes from the stub.

### Alternatives
1. The stub replaces the module's surface: a name absent from the stub is invisible.
2. The stub overlays the module: a name the stub declares is taken from the stub, a name only
   the source defines still resolves from the source.

### Choice
Interpretation 2. The sentence scopes the stub's authority to *type information*, and the next
section says "Stub annotations take precedence over inferred types" — precedence, not
replacement. An overlay also keeps `goto` working for source-only helpers, which
interpretation 1 would break.

### Risk: 30
Author most likely prefers: the same; a fixture with a deliberately incomplete stub would be
the one to disagree.

---

## T81. Which stub file wins, and whether a stub can stand alone

### Spec Text
> 1. `foo.pyi` adjacent to `foo.py` (inline stub).
> 2. A `stubs/` directory in the project root: `stubs/foo.pyi` or `stubs/foo/__init__.pyi`.

### Alternatives
1. The list is a strict search order and a stub is only ever an *overlay* on a real module, so
   `stubs/foo.pyi` with no `foo.py` resolves to nothing.
2. Strict search order, and a stub with no runtime module still resolves as the module `foo` —
   otherwise "unless the definition only exists in the stub" could never happen for a whole
   module.

### Choice
Interpretation 2. The order is taken literally (adjacent beats `stubs/`, and within `stubs/`
the flat `foo.pyi` beats the package `foo/__init__.pyi`), and a stub-only module resolves,
with `goto` landing in the `.pyi` because there is nowhere else to land.

### Risk: 25
Author most likely prefers: the same order; whether a stub-only module resolves at all is the
uncertain half.

---

## T82. `signatures` on something that is not a plain `def`

### Spec Text
> When the cursor is inside a function call's argument list, return the function's signature(s)

### Alternatives
1. Only project functions and classes get signatures; builtins and standard-library callables
   return an empty array.
2. Live callables are described too, from their runtime signature.

### Choice
Interpretation 2 where the runtime can tell us (`inspect.signature`), because `open(|)` and
`print(|)` are the most common places a user asks for signature help and the rest of the tool
already resolves builtins. Callables `inspect` refuses to introspect yield nothing rather than
an error, and an instance with `__call__` is not treated as a signature source.

A `lambda` is likewise not a signature source: it has no name to put in the `name` field and
the spec's `description` template starts with `def`.

### Risk: 35
Author most likely prefers: probably the same for builtins, but the exact `params` rendering of
a C-level signature (positional-only markers, `*args`) is very likely to differ.

---

## T83. `--scope` with an unknown value

### Spec Text
> `references <file> <line> <col> [--scope file|project] [--project <dir>]`

### Alternatives
1. Anything other than `file` or `project` is an error (exit 1).
2. Unknown values silently fall back to the default.

### Choice
Interpretation 1, matching how the existing CLI treats an unknown option: bad input is a
message on STDERR and exit 1, not a silent guess.

### Risk: 10
Author most likely prefers: the same.

---

## T84. Which files "all `.py` files in the project" means

### Spec Text
> `--scope project`: search all `.py` files in the project.

### Alternatives
1. Literally every `.py` file below the root.
2. Every `.py` file below the root except the conventional non-source directories.

### Choice
Interpretation 2: the walk skips `__pycache__` and dot-directories (`.git`, `.venv`, ...). They
hold no project source, and descending into a virtualenv would make project-scope search
unusable. `.pyi` stubs are not searched — the spec says `.py`.

### Risk: 15
Author most likely prefers: the same; a fixture will not contain either kind of directory.

---

## T85. `references` on a name that resolves to nothing

### Spec Text
> Find all locations where the name at the cursor is referenced (used or defined).

### Alternatives
1. An unresolvable name has no identity, so nothing matches and the result is empty.
2. An unresolvable name matches the other unresolvable occurrences of the same spelling in the
   searched files, which is the best available answer.

### Choice
Interpretation 2. Reporting an empty array for a name the user can plainly see twice in the
file is worse than reporting both, and the identity rule still keeps *resolvable* same-spelling
symbols out.

### Risk: 25
Author most likely prefers: the same; `references` on an undefined name is an unlikely fixture
either way.

---

## T86. Call sites used for dynamic parameter inference

### Spec Text
> the tool can optionally infer parameter types by finding call sites ... Do not search other
> files for call sites.

### Alternatives
1. Only unambiguous call sites count (the called expression must resolve back to this exact
   function).
2. Every call in the file whose callee is spelled like the function counts.

### Choice
Interpretation 2, with the obvious adjustments: an attribute call `obj.m(...)` on a method
skips the `self` slot, keyword arguments are matched by name, and `*args`/`**kwargs` call sites
are ignored. Full resolution of every callee would recurse through the inference engine it is
feeding. Inferred types are unioned with the parameter's default, so `def f(a=1)` called as
`f("x")` reports both.

### Risk: 35
Author most likely prefers: the same shape; whether the default is unioned in or replaced is
the likely disagreement.

---

## T87. The project root for `search`, which takes no file

### Spec Text
> `python sith.py search <query> [--project <dir>]`

### Alternatives
1. Without `--project` there is no root and the command is an error.
2. Without `--project` the root is the current working directory.

### Choice
Interpretation 2. Every other command derives the root from its file argument; `search` has no
file, so the only thing left is where the tool was invoked. Making the flag mandatory would
contradict the spec's own `[--project <dir>]` brackets.

### Risk: 5
Author most likely prefers: the same.

---

## T88. Sorting `search` hits that share a name and a line

### Spec Text
> Within each group, sort by `(module_path, line)`.

### Alternatives
1. `(module_path, line)` exactly, leaving ties in collection order.
2. `(module_path, line, column)`, so `a = b = 1` on one line is still deterministic.

### Choice
Interpretation 2. The spec's key is a prefix of this one, so every ordering the spec pins is
preserved; adding `column` only settles ties the spec leaves open, and matches how the existing
`definitions` output already breaks them.

### Risk: 5
Author most likely prefers: the same, or an unspecified order for the tie.
