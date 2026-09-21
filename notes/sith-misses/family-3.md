# Family 3: sith checkpoint 4, goto-with-stubs and dataclass signatures

Runs: 1 = dev6 just-solve 20260830T0354, 2 = just-solve 20260915T1324, 3 = anti_slop 20260920T0212,
4 = min12 20260915T0053, 5 = min12 20260915T0719, 6 = min13 20260919T0435, 7 = min13 20260919T1433,
M1 = min11 20260908T0219, M2 = min11 20260908T0846. Registry entries are copied by script from
`sith/checkpoint_4/snapshot/AMBIGUITIES.md` and indented four spaces; nothing inside them is edited.

Spec paths are `~/.cache/scbench/problems/sith/`. "Checked by running" means I ran the snapshot's
`sith.py` by hand on a copy of the test fixture in the scratchpad (`f3fix/`), outside the harness.

---

## Sentence A: default `goto` from a call site of an imported name

Tests: `test_goto_prefers_py_source_when_stub_exists`, `test_goto_uses_stub_when_definition_only_in_stub`.
Both fail for one cause, and the cause is not stubs. The `.pyi` placement in the fixtures is
exactly what the spec describes (`util.pyi` beside `util.py`; `stubs/only_stub.pyi` under the project
root; no `-stubs` package). The tests call `goto` without `--follow-imports`, with the cursor on a
call site one line below the import, and expect the answer in the other file.

### 1. Spec lines

The checkpoint 4 agent sees only these (checkpoint_4.md):

- :111 `If a stub exists, type information (function signatures, return types, class attributes) comes from the stub. The runtime `.py` file is still used for `goto` (source navigation).`
- :117 `- `goto` still navigates to the `.py` source (not the stub), unless the definition only exists in the stub.`

checkpoint_4.md never mentions `--follow-imports` (checked: no hit in the spec or in run 6's
checkpoint 4 `prompt.txt`). The rule the agents' code follows was set one checkpoint earlier
(checkpoint_3.md):

- :49 `Without `--follow-imports` (default), `goto` on an imported name returns the `import` statement itself:`
- :51 `With `--follow-imports`, `goto` follows the import chain and returns the actual definition in the source module:`

Both lines end in a colon with nothing after it; an example seems to have been stripped from the spec.

The sentence read two ways is checkpoint_3.md:49, "`goto` on an imported name". The hidden tests
read "on an imported name" as "cursor on the name inside the import statement". Every agent read it
as "cursor on any occurrence of a name that an import bound". checkpoint_4.md:117 then reads, to the
test, as "default `goto` from a call site lands in `util.py`", and to the agent as "when `goto` does
cross into the module, prefer `.py` over `.pyi`".

### 2. What the tests assert, and the reference

`tests/test_checkpoint_4.py:486-504`:

    write_files(tmp_path, {"util.py": "def work():\n    return 1\n",
                           "util.pyi": "def work() -> int: ...\n"})
    result = run_goto(entrypoint_argv, tmp_path, "main.py", "from util import work\nwork|()\n")
    assert definitions[0]["module_path"] == "util.py"

`tests/test_checkpoint_4.py:508-525`:

    write_files(tmp_path, {"stubs/only_stub.pyi": "def marker() -> int: ...\n"})
    result = run_goto(entrypoint_argv, tmp_path, "main.py", "from only_stub import marker\nmarker|()\n")
    assert any(d["module_path"].endswith("only_stub.pyi") for d in definitions)

`run_goto` (`test_checkpoint_4.py:110-129`) runs `goto <root>/main.py 2 <col> --project <root>` with
`cwd=root`. No `--follow-imports`. The cursor is line 2, column 4 or 6 (just past the name, on `(`).

Reference, `solutions/checkpoint_4/sith.py:3706`:

    should_follow = follow_imports or line != symbol.line

So the reference follows a `from` import by default whenever the cursor is not on the import's own
line. That line is new in checkpoint 4. `solutions/checkpoint_3/sith.py:2841` has plain
`if follow_imports:`. Checked by running: the checkpoint 3 reference answers `main.py` for both
fixtures; the checkpoint 4 reference answers `util.py` and `stubs/only_stub.pyi`, and still answers
`main.py` with the cursor on the import line (1:21). Stub lookup in the reference is
`sith.py:1277-1287` and `:1394-1418` (adjacent `.pyi`, then `stubs/foo.pyi`, then `stubs/foo/__init__.pyi`).

No checkpoint 3 test puts the cursor on a call site: every `run_project_goto` call in
`test_checkpoint_3.py` (lines 134, 150, 429, 619, 727, 744) has the cursor inside the `from ... import`
statement. These two checkpoint 4 tests are the only `goto` calls on a usage line anywhere in
checkpoints 3-6 (checkpoint 5 and 6 tests have no `run_goto`). So the usage-site behaviour is tested
only here, under a stub-named test.

### 3. What the runs printed

pytest output, identical in all nine runs (1-7, M1, M2):

    test_goto_prefers_py_source_when_stub_exists - AssertionError: assert 'main.py' == 'util.py'
    test_goto_uses_stub_when_definition_only_in_stub - assert False

Exit code 0 everywhere, a non-empty list everywhere; the path is `main.py`, the import statement.
Run 6 printed (checked by running):

    {"definitions":[{"name":"work","type":"function","full_name":"main.work","module_path":"main.py","line":1,"column":17,"description":"from util import work","docstring":""}]}

Checked by running each snapshot with `--follow-imports` added:

| run | util fixture | only_stub fixture |
|---|---|---|
| 1, 2, 3, 4, 7, M1, M2 | `util.py` | `stubs/only_stub.pyi` |
| 5, 6 | `util.py` | `main.py` (falls back to the import) |

So seven of nine snapshots have the stub behaviour the tests are named for and lose both tests only
on the default-follow question. Runs 5 and 6 carry a second, hidden gap: a module that exists only as
`stubs/only_stub.pyi` does not resolve. That gap is against words checkpoint_4.md already has (:109
plus :117 "unless the definition only exists in the stub") and would surface as a process miss if
sentence A were fixed.

No run passes, so there is no passing behaviour to compare.

### 4. History

`bin/test-history sith`: both tests 0 pass, 12 fail, 1 not reached. The fails include sonnet-4.6,
fable-5 and fable-5-1 just-solve runs, so no model has read it the tests' way.

### 5. Registry entries

Five of the six registry runs registered "does `goto` follow an import" at checkpoint 2 (run 4 folded the decision into T32 and T34); all six chose "stop at the
import binding", and the five marked it confirmed when checkpoint_3.md:49 arrived. No run listed the tests'
reading (follow from a usage line, stop only on the import line) as an alternative. All six Choices
miss the tests' reading. The checkpoint 4 stub entries (goto lands in `.py`, stub-only fallback)
match the tests' intent but never touch the default-follow question.

**Run 4**: no "does goto follow" entry of its own; the decision sits inside T32 and T34. T58 quotes
checkpoint_3.md:49 but asks about the module part. T79 and T81 cover checkpoint_4.md:117 and match the tests.

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

**Run 5**: T29 is the entry; its Alternative 2 is "follow", rejected. T45 quotes line 49. No entry on
checkpoint_4.md:117; closest are T66 and T67 (T67's Choice says a stub-only module is reachable
through `goto`, yet the snapshot does not resolve one).

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

**Run 6**: T29 (missed), T45, and T65 on line 117 (Risk 10; matches the tests' intent, but the
snapshot does not resolve a stub-only module in `stubs/`).

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

**Run 7**: T28 (missed), T40. No entry on checkpoint_4.md:117; closest are T55 and T57.

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

**M1 (min11 0219)**: T32 (missed), T64 and T66 on the stub lines.

    ## T32 — Does `goto` follow an import to the other file?

    ### Spec Text
    > `goto` returns where the name at the cursor is assigned or defined (`def`, `class`, assignment, or import binding).

    > `infer` returns what the name at the cursor evaluates to after static propagation through assignments and calls.

    ### Alternatives
    1. `goto` stops at the import binding in the file under the cursor; `infer` is the
       command that crosses into the defining module.
    2. `goto` follows the import and reports the `class`/`def` in the other file.

    ### Choice
    Alternative 1. The spec lists "import binding" as one of the things `goto` reports,
    alongside `def`, `class` and assignment — an import binding is only a distinct answer if
    the command stops there. The contrast with `infer` ("after static propagation") is the
    same split.

    ### Risk: 25
    Author's most likely alternate reading: `goto` follows imports through to the original
    definition, making the "import binding" case apply only to unresolvable imports
    (Alternative 2).

    ### Resolved by the import spec
    Both readings turn out to be right, selected by a flag: "Without `--follow-imports`
    (default), `goto` on an imported name returns the `import` statement itself" — the
    original choice — "With `--follow-imports`, `goto` follows the import chain and returns
    the actual definition in the source module." The default is unchanged.

    ## T64 — Where `infer` points for a stub-typed definition

    ### Spec Text
    > If a stub exists, type information (function signatures, return types, class attributes) comes from the stub. The runtime `.py` file is still used for `goto` (source navigation).

    > `goto` still navigates to the `.py` source (not the stub), unless the definition only exists in the stub.

    ### Alternatives
    1. Only `goto` is pinned to the `.py`. `infer` on a bare function name reports the value
       it resolves to, which is the stub's declaration (`module_path` of the `.pyi`).
    2. `infer` is pinned to the `.py` too, and only the *type* fields come from the stub.

    ### Choice
    Alternative 1. The spec pins exactly one command ("The runtime `.py` file is still used
    for `goto`"), and `infer` reports the resolved value, which under a stub *is* the stubbed
    declaration. Everything a caller reads off `infer` for a call expression (the return
    type) is unaffected either way.

    ### Risk: 45
    Author's most likely alternate reading: every reported location outside `search`/`names`
    prefers the `.py` file, so `infer` on a stubbed function names `foo.py`.

    ## T66 — Stubs for modules the project does not contain

    ### Spec Text
    > For a module `foo`, the tool looks for type stubs in this order: 1. `foo.pyi` adjacent to `foo.py` (inline stub). 2. A `stubs/` directory in the project root: `stubs/foo.pyi` or `stubs/foo/__init__.pyi`.

    ### Alternatives
    1. "a module `foo`" is any module the tool resolves, so `stubs/os.pyi` supplies the types
       for `import os` even though the project has no `os.py`.
    2. Stubs only apply to project modules that have a `.py` file.

    ### Choice
    Alternative 1. The `stubs/` directory is described without reference to a runtime file,
    and a stub directory whose entries could only shadow project files would duplicate the
    inline-stub rule. A stub is consulted first and used as the module when no `.py` exists.

    ### Risk: 25
    Author's most likely alternate reading: stubs are consulted only for modules that also
    have project source (Alternative 2).

**M2 (min11 0846)**: T37 (missed), T54, T74 on the stub-only module.

    ## T37. Does `goto` follow an import to the original definition?

    ### Spec Text
    > `goto` returns where the name at the cursor is assigned or defined (`def`, `class`, assignment, or import binding).
    > For imports: the import statement text.

    ### Alternatives
    1. `goto` stops at the import binding in the file being analysed; `infer` follows through to the class or function in the other module.
    2. `goto` follows the import and reports the definition in the imported module.

    ### Choice
    Alternative 1. "or import binding" lists the import itself as a possible answer, and the description column defines "the import statement text" for imports -- a definition object that could never be produced if `goto` always jumped past the import.

    ### Risk: 20
    Editors usually jump through imports, so an author optimising for the editor experience may have followed them; but then the "import binding" and import-description clauses would be dead text.

    ### Resolved by the current spec
    > Without `--follow-imports` (default), `goto` on an imported name
    > returns the `import` statement itself.

    Alternative 1 was right: plain `goto` stops at the import binding,
    and the new `--follow-imports` flag asks for alternative 2.

    ## T54. What "`infer` and `goto` return empty results" means for the import statement itself

    ### Spec Text
    > If a module cannot be found, treat it as unresolvable — `infer` and `goto` return empty results, completions return nothing for that module's attributes.
    > Without `--follow-imports` (default), `goto` on an imported name returns the `import` statement itself

    ### Alternatives
    1. Both commands return `[]` for every name that came from the unresolvable module, including the imported name itself.
    2. `infer` returns `[]` (there is no type to report, and no file to point at), while `goto` still reports the import statement, because that binding is a fact about the current file and needs no resolution.

    ### Choice
    Alternative 2. The two sentences can only both hold if "empty results" is about what the *other module* would have supplied — its attributes, its definitions — and not about the local binding, which the `goto` rule describes unconditionally. `import nosuch` therefore gives `goto` the import line and `infer` nothing.

    ### Risk: 40
    The author most likely returns `[]` from `goto` too when the module cannot be found, reading the sentence as covering both commands literally.

    ## T74. A stub with no `.py` beside it

    ### Spec Text
    > `goto` still navigates to the `.py` source (not the stub), unless the definition only exists in the stub.

    ### Alternatives
    1. A module that exists only as `foo.pyi` is importable: it supplies both types and, for lack of anything else, `goto` targets.
    2. Only modules with a real `.py` exist; a lone `.pyi` is invisible.

    ### Choice
    Alternative 1. The quoted clause already accepts that a definition may exist only in the stub and says `goto` should land there; a whole module existing only in the stub is the same situation one level up, and typeshed-style `stubs/` trees routinely have no runtime source in the project at all.

    ### Risk: 25
    The author may have wired stub discovery strictly as an overlay on a located `.py`, making a stub-only module unresolvable.

### 6. Classification

Reading, with the hidden test on the weak side. The plain words of checkpoint_3.md:49 cover any
occurrence of an imported name, the checkpoint 3 reference implements them that way, and the
checkpoint 4 reference quietly narrows the rule to "cursor on the import line" with no checkpoint 4
sentence announcing it. 0 of 12 runs across four models pass. I would call it a hidden test that
contradicts the spec as written; "reading" is the kindest label, and it is the label to use if the
spec is going to be patched rather than the test reported upstream.

Runs 5 and 6 additionally have a process bug (stub-only module in `stubs/` unresolved) masked by this miss.

### 7. Candidate sentences

The checkpoint 4 agent does not see checkpoint_3.md, so a checkpoint 3 fix alone relies on the
checkpoint 3 agent building the narrower rule. Two candidates:

a. checkpoint_3.md:49, replace with:
   `Without `--follow-imports` (default), `goto` with the cursor inside an `import` statement returns that statement itself. From any other line, `goto` on a name bound by `from X import name` returns the definition in `X`, falling back to the import statement when `X` cannot be resolved.`

b. checkpoint_4.md:117, replace with:
   `- `goto` on a use of an imported name (for example the call `work()` after `from util import work`) lands on the `.py` definition, not the stub and not the import statement, with or without `--follow-imports`; when the definition only exists in the stub, it lands on the `.pyi`.`

(a) is the smaller nudge and keeps checkpoint 3's own tests green, since they all sit on the import
line. (b) is what the checkpoint 4 agent will actually read. My guess is that (b) alone is enough for
these two tests; I have not run it.

Over-correction to avoid: "goto always follows imports". The checkpoint 3 tests
`test_goto_default_on_import_symbol_returns_import_site` and
`test_goto_import_site_has_import_description_and_type` need the import line to answer with
`main.py`, and the reference follows only `from` imports (`symbol.detail.startswith("importfrom:")`,
sith.py:3696), not `import X`.

---

## Sentence B: `signatures` on a call of a `@dataclass` class

Tests: `test_signatures_dataclass_constructor_includes_annotated_fields`,
`test_signatures_dataclass_constructor_with_qualified_decorator`.

### 1. Spec lines

checkpoint_4.md says nothing about dataclasses, and nothing about what a class call reports beyond
one table cell. Nearest lines:

- :16 `When the cursor is inside a function call's argument list, return the function's signature(s) with an indication of which parameter the cursor is currently on.`
- :20 `| `name` | string | Function or class name. |`

The only dataclass text is two checkpoints back, unseen by the checkpoint 4 agent (checkpoint_2.md):

- :93 `Classes decorated with `@dataclasses.dataclass` expose their annotated fields as instance attributes for completion and inference.`
- :97 `- `@dataclass` is recognized regardless of import form (`import dataclasses`, `from dataclasses import dataclass`, or aliased forms).`

### 2. What the tests assert, and the reference

`tests/test_checkpoint_4.py:198-221`:

    "from dataclasses import dataclass\n\n@dataclass\nclass Point:\n    x: float\n    y: float = 0.0\n\nPoint(|)\n"
    assert len(signatures) >= 1
    assert "x: float" in params
    assert "y: float=0.0" in params

`tests/test_checkpoint_4.py:224-247`: the same with `import dataclasses`, `@dataclasses.dataclass`,
`class Item: name: str; amount: int = 1`, expecting `"name: str"` and `"amount: int=1"`.

Reference: `solutions/checkpoint_4/sith.py:3210-3215` sends every class value to
`_signature_for_dataclass_constructor` (:3078-3102), which returns `None` unless
`_is_dataclass_class` (:2943-2947, decorator base name `dataclass`), and builds params from the
class body's `AnnAssign` statements in `_dataclass_param_specs` (:2983-3006), skipping
`field(init=False)`. The reference has no `__init__` path at all: a plain class with an `__init__`
gets no signature from it (checked by running: `Box(|)` on a class with `__init__(self, a, b=1)` prints `{"signatures":[]}`), and no checkpoint 4 hidden test calls a non-dataclass class. So the reference covers dataclass calls and nothing else, the mirror image
of the agents.

### 3. What the runs printed

pytest, identical in runs 1, 3, 4, 5, 6, 7, M1, M2:

    AssertionError: assert 'x: float' in []
    AssertionError: assert 'name: str' in []

Checked by running, all eight print the same record:

    {"signatures":[{"name":"Point","params":[],"index":null,"description":"def Point()","docstring":""}]}

They look up `__init__` through the class and its bases, find none, and report an empty parameter
list. Exit 0, one signature, right name; only the params are empty.

Run 2 printed:

    {"signatures":[{"name":"Point","params":["x: float","y: float=0.0"],"index":0,"description":"def Point(x: float, y: float=0.0)","docstring":""}]}

Run 2's `sith.py:3885-3913` has `dataclass_params`, called at :3979 when a class has no `__init__`:
it walks the MRO, takes annotated names in order, skips `ClassVar`, and appends `=<default>`. Its
checkpoint 2 and 3 snapshots contain no occurrence of "dataclass" (grep count 0), so this was added
during checkpoint 4. The transcript shows the agent grepping `dataclass` in `sith.py` late in the
session (stdout.jsonl line 134), finding nothing, then patching the function in (line 139). The
final message says "Classes use `__init__` (including inherited and `@dataclass`-synthesised
fields)". No reasoning about why is visible in the transcript; from the files it reads as an
unprompted edge case, not a response to any spec sentence.

### 4. History

`bin/test-history sith`: both tests 2 pass, 10 fail, 1 not reached. The passes are run 2 and
fable-5-1 just-solve 20260905T0532 (not inspected).

### 5. Registry entries

Unregistered in all six registry runs: no entry asks what a call of a class without `__init__`
reports when a decorator generates one. The closest entry in each run is "what a call of a class
reports". All six chose "class name plus `__init__`'s parameters", which matches the tests for the
record shape but misses them on dataclasses; run 5's T56 and run 7's T48 state the miss outright
("A class without an `__init__` ... yields an empty parameter list", "a class without one has no
parameters"). The dataclass entries that do exist (run 5 T37, run 6 T32, M1 T35) are about
checkpoint 2's attribute completion, not signatures; runs 4, 7 and M2 have no dataclass entry.

**Run 4 T66**

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

**Run 5 T56**

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

**Run 6 T55**

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

**Run 7 T48**

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

**M1 T54**

    ## T54 — What a call to a class reports

    ### Spec Text
    > `name` | string | Function or class name.

    > `description` | string | `"def name(params)"` ...

    > `docstring` | string | Function's docstring, or empty string.

    ### Alternatives
    1. A class call reports the class's own name, the parameters of `__init__` without
       `self`, `description` `"def <ClassName>(params)"`, and `__init__`'s docstring, falling
       back to the class docstring.
    2. It reports `__init__` as the name (`"__init__"`, `"def __init__(params)"`).
    3. It reports `"class <ClassName>"` as the description.

    ### Choice
    Alternative 1. "Function or class name" only makes sense if a class call is reported
    under the class's name, and the `description` row admits exactly two shapes, both
    starting with `def`. The docstring a caller wants is the constructor's; a class whose
    `__init__` has none falls back to the class docstring, which is where Python itself puts
    constructor documentation.

    ### Risk: 40
    Author's most likely alternate reading: the class name with the *class* docstring
    (rather than `__init__`'s) as `docstring`.

**M2 T62**

    ## T62. What `signatures` returns for a call to a class

    ### Spec Text
    > | `name` | string | Function or class name. |

    ### Alternatives
    1. Report the `__init__` parameters (minus `self`) under the class's own name, with `description` `"def Cls(params)"`.
    2. Report the class with an empty parameter list, since a `ClassDef` has no `args`.
    3. Report `__init__` under the name `__init__`.

    ### Choice
    Alternative 1. `name` explicitly admits a class, and the only useful signature for `Cls(|)` is the constructor's; the `description` template the spec gives is the `"def ..."` one, so the class name is substituted into it. `__init__` is inherited from base classes when the class does not define one.

    ### Risk: 30
    The author may render a class's description as `"class Cls(params)"`, or may name the entry `__init__`.

### 6. Classification

Taste. No sentence in checkpoint_4.md is being read two ways; the spec is silent and the authors
assume Python's own rule that `@dataclass` generates an `__init__` from the annotated fields. An
agent that knows Python could get there unaided (run 2 did), so part of this is the agent not
thinking of the case, but nothing the checkpoint 4 agent can see points at it. The second test's
qualified decorator adds no separate difficulty: every failing run fails both tests the same way.

### 7. Candidate sentence

Not a reading, so strictly no replacement is owed. If one is wanted, checkpoint_4.md, after the
`signatures` field table (after :24):

   `A call of a class reports the constructor's parameters under the class's name. For a `@dataclass` class (any import form) the parameters are its annotated fields in order, rendered like any other parameter, e.g. `"x: float"`, `"y: float=0.0"`.`

Over-correction to avoid: "annotated class attributes are constructor parameters" without the
dataclass condition, which would give every plain class with annotations a fake signature. Also
avoid spelling out `field(init=False)` or `ClassVar`; the tests do not reach them.
