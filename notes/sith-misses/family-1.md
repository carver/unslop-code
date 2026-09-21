# Family 1: sith hidden-test misses, sentence by sentence

Runs: 1 dev6-opus5 just-solve 0830T0354, 2 just-solve 0915T1324, 3 anti_slop 0920T0212, 4 min12 0915T0053, 5 min12 0915T0719, 6 min13 0919T0435, 7 min13 0919T1433. Registry runs also include min11-a (0908T0219) and min11-b (0908T0846).

Paths: spec and tests under `~/.cache/scbench/problems/sith/`. "Ref" is `solutions/checkpoint_N/sith.py`.

How I checked: read each test, the spec, the ref code; grepped the pytest output in every run's `evaluation/stdout.txt`; ran the ref and the agents' snapshots by hand on the test fixtures from a scratch directory (`PYTHONDONTWRITEBYTECODE=1`, nothing written into the run folders). Registry entries were cut out by script, not retyped. Entries end with a `---` separator in most files; I kept it where the file had it.

Summary table

| # | Sentence | Tests | Class | History (pass/fail/not reached) |
|---|----------|-------|-------|------|
| S1 | ckpt2:18 "If the name cannot be resolved, return an empty array" applied to a bare parameter | `test_infer_is_not_none_narrowing_excludes_none` | reading (the test name points at the wrong sentence) | 0/12/1 |
| S2 | ckpt3:100 "Names not yet defined at the point of circular import are simply not visible." | `test_circular_import_hides_name_not_yet_defined` | reading; the test's answer also disagrees with real import order from `main.py` | 0/12/1 |
| S3 | ckpt1:88-89, no description given for `param` | `test_complete_function_param_is_visible_with_param_metadata` | taste (unstated string, coin flip) | 7/5/1 |
| N1 | ckpt1:37 local scope, comprehension targets | `test_complete_comprehension_var_not_visible_outside` | taste, one run only | 11/1/1 |
| N2 | ckpt1:51 module public names | `test_complete_module_attribute_respects_all` | process (run 3 regression at ckpt2) | 11/1/1 |
| N3 | ckpt2:117 union completion, which duplicate survives | `test_complete_union_dedupe_keeps_single_candidate` | taste / noise | 8/4/1 |
| N4 | ckpt3:72,75 `from X import` on a package | two submodule completion tests | taste, run 1 only | 11/1/1 each |
| N5 | ckpt1:91 imported name's `type` | `test_goto_import_site_has_import_description_and_type` | process (run 1 bug against existing words) | 10/2/1 |

---

## S1. `infer` on a bare parameter (ckpt2) — fails in all 7

### 1. Spec lines

`checkpoint_2.md:18`

> If the cursor is not on a name, exit 1. If the name cannot be resolved, return an empty array (exit 0).

`checkpoint_2.md:45` lists `param` as a definition `type`, and `checkpoint_2.md:110` is the heading `### \`is None\`` with no body. The spec never says what `infer` returns for a parameter.

The test name says "is not None narrowing", but narrowing is not what fails. The sentence in play is line 18: does "cannot be resolved" cover a parameter, which is bound but has no known value?

### 2. What the test asserts

`tests/test_checkpoint_2.py:496-507`

```python
result = run_infer(entrypoint_argv, tmp_path,
    ("def f(x):\n    if x is not None:\n        return x|\n"))
assert result.returncode == 0, result.stderr
definitions = _defs(parse_json_result(result))
assert isinstance(definitions, list)
assert definitions          # non-empty, nothing else checked
```

`x` is an unannotated parameter, so there is no union for `is not None` to trim. The test passes only if `infer` on a parameter returns something.

Ref, `solutions/checkpoint_2/sith.py:1172-1173`:

```python
if symbol.type == "param":
    return [ResolvedValue(kind="param", name=symbol.name, symbol=symbol, scope=scope)]
```

and `:1440-1445` drops only `builtin None` values under `exclude_none`, so the param survives. Ref output on the fixture (run by hand):

```
{"definitions":[{"name":"x","type":"param","full_name":"main.f.x","module_path":"main.py","line":1,"column":0,"description":"param x","docstring":""}]}
```

Other ref probes (run by hand): `def f(x: int): return x|` also gives the `param` definition, the annotation is ignored. `y = f(1)` where `f` returns its parameter gives the same `param x`. `x = unknown(); x|` gives `[]`. So the ref rule is narrow: a parameter infers to itself; it is not a general "fall back to goto". (`column: 0` for the parameter looks like a ref quirk; no test checks it.)

Sibling tests that agree with agents: `test_infer_none_narrowing_in_if_branch` (`:356`, wants `None` inside `if x is None:`) and `test_infer_unresolved_name_returns_empty_array` (`:579`, `missing|` gives `[]`). In the hidden tests "cannot be resolved" is only ever a name bound nowhere.

### 3. What the runs printed

All nine opus-5 runs (1-7 and both min11): `assert []`, i.e. `{"definitions":[]}`. By hand, snapshots of runs 1, 5, 6, 7 also print `{"definitions":[]}` for `def f(x):\n    return x|` with no `if` at all. The narrowing code is irrelevant; every run treats a parameter of unknown value as unresolved. No run passes.

### 4. History

`bin/test-history`: 0 pass, 12 fail, 1 not reached (sonnet-4.6, fable-5, fable-5-1 fail too).

### 5. Registry

Only run 5 registered the real sentence (T35), and chose the losing side with Risk 30. Runs 4, 6, 7, min11-a, min11-b are unregistered for it; their closest entry is the empty `is None` section, where all six chose the both-directions narrowing the tests agree with (the `is None` sibling test passes). So those Choices match the tests and still fail, because the miss is elsewhere. Run 4's T45 touches parameters (default values) but not the bare case. Run 7 T32 and min11-b T41 cover unresolvable `return` values and both pick "empty array", the same reading that loses here (not quoted; checked by reading them).

#### Run 4, checkpoint_2 registry, entry T38

````markdown
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
````

#### Run 4, checkpoint_2 registry, entry T45

````markdown
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
````

#### Run 5, checkpoint_2 registry, entry T30

````markdown
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
````

#### Run 5, checkpoint_2 registry, entry T35

````markdown
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
````

#### Run 6, checkpoint_2 registry, entry T34

````markdown
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
````

#### Run 7, checkpoint_2 registry, entry T26

````markdown
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
````

#### Run min11-a (0219), checkpoint_2 registry, entry T24

````markdown
## T24 — The empty `is None` section

### Spec Text
> ### `is None`

(The heading is followed by no rules; the section immediately ends.)

### Alternatives
1. `is None` is a narrowing form parallel to the `isinstance` one directly above it:
   inside `if x is None:` the name is `None`; inside `if x is not None:` (and the `else`
   of `is None`) the `None` possibility is removed from the union.
2. Only the positive direction is specified: `if x is None:` narrows to `None`, and
   `is not None` does nothing.
3. The heading is a placeholder for a feature that is not implemented, so no narrowing
   happens for `is None` at all.

### Choice
Alternative 1. The heading sits inside "Flow-Sensitive Type Narrowing" immediately after
the `isinstance` subsection, so it announces a second narrowing form; the only useful
reading of an `is None` test is that it splits a union into "is None" and "is not None"
halves. Implementing both directions is the behaviour a user of the feature expects, and
it degrades gracefully: when a name has no known union, `is not None` removes nothing.

### Risk: 40
Author's most likely alternate reading: only `if x is None:` narrows (to `None`), with
`is not None` and the `else` branch left alone (Alternative 2).

---
````

#### Run min11-b (0846), checkpoint_2 registry, entry T35

````markdown
## T35. The empty `is None` section

### Spec Text
> ### `is None`

### Alternatives
1. Symmetric with `isinstance`: inside `if x is None:` the name is the builtin `None`; inside `if x is not None:` (and in the `else` of `is None`) the `None` member is dropped from the name's possible types.
2. Only the positive form narrows to `None`, with no negative narrowing.
3. Nothing at all: the heading is a leftover and `is None` has no effect.

### Choice
Alternative 1. The heading sits under "Flow-Sensitive Type Narrowing" beside `isinstance` narrowing, whose paragraph describes both what the branch proves and where it applies; the only reading that gives the heading content is the standard one, and dropping `None` in the negative branch is the half of it that actually helps completion (`if x is not None: x.` should offer the non-`None` type's attributes).

### Risk: 45
The section is empty, so any behaviour is defensible; an author who wrote the heading and then ran out of time may have implemented only the positive branch, or nothing.

---
````

### 6. Classification

Reading. Line 18's "cannot be resolved" reads two ways: "the name is bound nowhere" (tests, ref) or "nothing is known about its value" (every agent; run 5 wrote it down). The spec half-supports the tests, since `param` is a listed output `type` for `infer`, but says nothing more. The test's own name is misleading: it suggests a narrowing check, and a failing agent reading the name would look in the wrong place. The sibling tests (`is None` branch, unbound name) pass in all nine opus runs; only sonnet-4.6 fails them.

### 7. Candidate sentences (checkpoint_2.md, the checkpoint that writes `infer`)

A. Add to the `infer` section after line 18:

> A parameter whose value is unknown resolves to the parameter itself: `infer` returns its `param` definition, the same object `goto` returns.

B. Shorter, in the Clarifications list (line 119 on):

> - `infer` on a function parameter returns the parameter's own definition (`type` `param`).

Over-correction to avoid: "when inference fails, `infer` returns what `goto` returns". The ref returns `[]` for `x = unknown(); x|` (checked by hand), and a general fallback would change that. I did not check whether a hidden test pins the `[]` case for assignments, so treat that as a guess about risk. Also do not mention annotations; the ref ignores them at ckpt2 and agents that use them pass today.

---

## S2. Names hidden by a circular import (ckpt3) — fails in all 7

### 1. Spec line

`checkpoint_3.md:100`

> - Circular imports: do not infinite-loop. If module A imports B and B imports A, resolve what is available at the point of the circular reference and move on. Names not yet defined at the point of circular import are simply not visible.

### 2. What the test asserts

`tests/test_checkpoint_3.py:652-669`

```python
write_files(tmp_path, {
    "a.py": "from b import early\nlate = 1\n",
    "b.py": "from a import late\nearly = 2\n",
})
result = run_project_infer(entrypoint_argv, tmp_path, "main.py",
                           "from b import late\nlate|\n")
assert result.returncode == 0, result.stderr
assert _defs(result) == []
```

Ref, `solutions/checkpoint_3/sith.py:1512-1518` inside `_resolve_importfrom_values`:

```python
for target_symbol in target_symbols:
    if _module_depends_on_module_before_line(
        target_analysis, analysis.module_name, target_symbol.line,
    ):
        continue
```

with the helper at `:1406-1436`: it walks the target module's top-level statements above the binding's line and returns True if any `import`/`from` there names the importing module. So the ref rule is pairwise and textual: when X does `from T import n`, `n` is hidden if T imports X on a line above the line that binds `n` in T. No entry point, no execution order.

On the fixture: `main` takes `late` from `b`; `b.late` is `from a import late`; in `a`, `late = 1` is on line 2 and `from b import early` is on line 1, so `a.late` is hidden from `b`, and `main` gets `[]`.

Ref probes by hand on the same three files: `from a import late` in main gives `int` (main is not in the cycle). `from a import early` in main gives `[]` (`b.early` sits below `b`'s import of `a`). Real Python on `main.py` raises `ImportError: cannot import name 'early' from 'b'`, so nothing in this fixture runs.

The sibling `test_circular_import_returns_available_symbol_type` (`:632`, `from a import x` where `x = 1` is below `a`'s import of `b`, main outside the cycle) wants `int` and passes in all nine opus runs.

### 3. What the runs printed

All nine opus-5 runs printed the same thing:

```
assert [{'name': 'int', 'type': 'instance', 'full_name': 'builtins.int', 'module_path': '', 'line': 0, 'column': 0, 'description': 'instance of int', 'docstring': ''}] == []
```

(run 7 adds the builtin `int` docstring). Every agent parses each module whole and stops the loop with a re-entrancy guard (run 6 `sithlib/resolve.py:58,150` `_active` set; run 1 `sith.py:640` cache sentinel; run 7 `sithlib/project.py:41` one analysis per file). Under that model `a.late` is an ordinary top-level name, so `b.late` resolves to `int`. No run passes.

Note on the test: a faithful execution-order walk from `main.py` would also give `int`. main starts `b`; `b` line 1 starts `a`; `a` line 1 re-enters the half-built `b` and `early` is missing (hidden); `a` goes on to `late = 1`; control returns to `b`, where `a.late` now exists. The test's `[]` only follows if `a` is taken to have started first, or under the ref's order-free pairwise rule. So an agent that modelled import order exactly as the sentence suggests would still fail.

### 4. History

`bin/test-history`: 0 pass, 12 fail, 1 not reached.

### 5. Registry

Registered in runs 4 and 6. Runs 5, 7, min11-a, min11-b: unregistered (no entry mentions "circular" or "cycl" in their checkpoint_3 or checkpoint_6 registries; the one hit in min11-a is T11's "the rule is circular", unrelated). Run 4 named the test's fixture almost exactly in its Risk and chose the other side: missed. Run 6 never listed the hidden reading as an alternative: missed.

#### Run 4, checkpoint_3 registry, entry T64

````markdown
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
````

#### Run 6, checkpoint_3 registry, entry T50

````markdown
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
````

### 6. Classification

Reading, with a caveat against the test. The sentence's "at the point of the circular reference" reads as (a) where resolution re-enters a module already being resolved (all agents: cut the loop, everything else in the file is visible) or (b) a line position in the imported module (tests, ref: names bound below that module's import of the importer are hidden). Run 4 saw both and picked (a) because "the tool never executes code". The caveat: the fixture's expected `[]` does not follow from real import order starting at `main.py`, only from the ref's pairwise rule, so a sentence that merely says "model execution order" will not reach it.

### 7. Candidate sentences (checkpoint_3.md, replacing the last sentence of line 100)

A.

> When module B imports a name from module A, and A itself imports B on a line above the line that binds that name, the name is not visible to B (A had not defined it yet when it turned to B). Names A binds above that import resolve normally.

B. Shorter, with the fixture shape as the example:

> A name that A binds below its own `import` of B is not visible to B, whichever file the query starts from: with `a.py` = `from b import early` / `late = 1` and `b.py` = `from a import late`, `b.late` resolves to nothing.

B's example is the hidden fixture nearly word for word; prefer A, or rename the modules and names, if the patch must not teach to the test.

Over-correction to avoid: hiding every name in a module that takes part in a cycle, or hiding names from importers outside the cycle. `test_circular_import_returns_available_symbol_type` needs `from a import x` in `main.py` to give `int` although `x = 1` sits below `a`'s import of `b`; the rule applies only to the two modules that import each other. "Whichever file the query starts from" matters: wording that invites an execution walk from the queried file yields `int` here.

---

## S3. Description of a parameter in `complete` (ckpt1) — fails in 2, 3, 4

### 1. Spec lines

`checkpoint_1.md:88-89`

> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`, `keyword`. |
> | `description` | string | A short description. For functions: `def name(...)`. For classes: `class Name`. For imports: `module name`. For assignments: `instance of <type>` if the right-hand side is a literal, a constructor call, or otherwise resolvable to a known type; otherwise `statement`. For keywords: the keyword itself. |

The spec says nothing about a parameter's description. `param` is a `type` with no description row.

### 2. What the test asserts

`tests/test_checkpoint_1.py:486-498`

```python
result = run_complete(entrypoint_argv, tmp_path, ("def greet(name):\n    na|\n"))
item = find_completion(payload, "name")
assert item["type"] == "param"
assert item["description"] == "param name"
```

Ref, `solutions/checkpoint_1/sith.py:143`: `description=f"param {arg}",`.

### 3. What the runs printed

Snapshots run by hand on the fixture, matching the pytest lines:

| run | result | description |
|-----|--------|-------------|
| 1 | pass | `param name` |
| 2 | FAIL | `param` |
| 3 | FAIL | `param` |
| 4 | FAIL | `param` |
| 5 | pass | `param name` |
| 6 | pass | `param name` |
| 7 | pass | `param name` |
| min11-a | pass | `param name` |
| min11-b | FAIL | `param` |

pytest in each failing run: `AssertionError: assert 'param' == 'param name'`. All runs get `type` right. Runs 2, 3, 4 and min11-b keep failing it as a regression in checkpoints 2-6 (checked in each `evaluation/stdout.txt`).

### 4. History

`bin/test-history`: 7 pass, 5 fail, 1 not reached. Opus-5 alone: 5 pass, 4 fail.

### 5. Registry

Every registry run registered it at checkpoint 1, with Risk 45-60. Runs 5, 6, 7, min11-a chose `param <name>`: matched. Runs 4 and min11-b chose bare `param`: missed, and both named `param <name>` as the author's likely preference. Run 4 then added T46 at checkpoint 2, choosing `param <name>` for `infer`/`goto` definitions while keeping bare `param` in `complete`, and said in its Risk that "only one of the two can match". min11-a's checkpoint-2 T30 keeps `param <name>` for both commands.

#### Run 4, checkpoint_1 registry, entry T10

````markdown
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
````

#### Run 4, checkpoint_2 registry, entry T46

````markdown
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
````

#### Run 5, checkpoint_1 registry, entry T2

````markdown
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
````

#### Run 6, checkpoint_1 registry, entry T2

````markdown
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
````

#### Run 7, checkpoint_1 registry, entry T8

````markdown
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
````

#### Run min11-a (0219), checkpoint_1 registry, entry T3

````markdown
## T3 — `description` for parameters

### Spec Text
> `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`, `keyword`.

### Alternatives
1. `param <name>`, following the `module <name>` / `class <Name>` shape.
2. The literal string `param`.
3. `statement` (the catch-all description).
4. `instance of <annotation>` when annotated.

### Choice
Alternative 1: `param <name>`. Every other description in the spec that is not a fixed
word embeds the name (`module name`, `class Name`, `def name(...)`), so `param name` is
the consistent extension. Parameters are never annotated-dependent in the spec.

### Risk: 60
Author's most likely alternate reading: the bare word `param` (Alternative 2), since the
spec never shows a parameter description at all.

---
````

#### Run min11-a (0219), checkpoint_2 registry, entry T30

````markdown
## T30 — `description` for a parameter definition

### Spec Text
> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`. |

> | `description` | string | Short description. For functions: `def name(params)`. For classes: `class Name`. For instances: `instance of <ClassName>`. For assignments: the right-hand expression or statement. For imports: the import statement text. |

### Alternatives
1. `param <name>` — the form this tool already uses for parameters in `complete`.
2. The whole `def` header, since the parameter is defined by the signature.
3. The parameter's source text including annotation and default (`alpha: int = 3`).

### Choice
Alternative 1. `param` is a documented `type` but the description table has no row for
it, so the nearest fixed point is the description this same tool already emits for
parameters in completions; keeping the two commands consistent is better than inventing
a third form.

### Risk: 30
Author's most likely alternate reading: the parameter's own source text, annotation and
default included (Alternative 3).

---
````

#### Run min11-b (0846), checkpoint_1 registry, entry T6

````markdown
## T6. Description text for a parameter

### Spec Text
> | `type` | string | One of: `module`, `class`, `function`, `instance`, `statement`, `param`, `keyword`. |
> | `description` | string | A short description. For functions: `def name(...)`. For classes: `class Name`. For imports: `module name`. …

### Alternatives
1. `"param"` — mirroring the `statement` type whose description is the bare word `statement`.
2. `"param name"` — mirroring `module name`.
3. `"parameter"`, or the annotation when present (`instance of int`).

### Choice
Alternative 1, except when the parameter carries a resolvable annotation, in which case it is treated as a known type and described `instance of <type>` (the type field stays `param`). The `statement` type's description is the type word itself, so `param` follows the same shape.

### Risk: 55
Genuinely unspecified — the description column never mentions parameters at all. `"param name"` is an equally natural authoring choice, as is emitting `param` even for annotated parameters.

---
````

### 6. Classification

Taste. No sentence is being read two ways; the spec is silent and the authors assume `param <name>`. The agents see the gap every time (six of six registries, Risk 45-60) and split between two defensible strings: 5 of 9 opus runs land on the hidden one. The registry did not help run 4 or min11-b; both wrote down the right answer as "author most likely prefers" and then chose the other. Arm does not predict it: just-solve passes once and fails once, min12 the same.

### 7. Candidate sentence (checkpoint_1.md:89, inside the description cell)

A. Insert after "For imports: `module name`.":

> For parameters: `param name`.

B. Same, with the placeholder style used elsewhere in the row: "For parameters: `param <name>`."

Over-correction to avoid: none of substance; keep it to `complete`'s table. Checkpoint 2's table (line 50) has the same gap for `infer`/`goto`; the ref prints `param x` there too (S1 output), but no test in this family checks it, so I would not patch it on this evidence.

---

## Singles

### N1. ckpt1 `test_complete_comprehension_var_not_visible_outside` — run 4 only (11 pass, 1 fail, 1 not reached)

Test (`test_checkpoint_1.py:183`): `vals = [x for x in range(3)]\nx|` must not offer `x`. Run 4 printed `assert 'x' not in ['x']`. Spec line `checkpoint_1.md:37`: "**Local scope** — names assigned or defined in the immediately enclosing function/method." Run 4 registered it (checkpoint_1 T16, "Bindings that are neither def/class/import/assignment", Risk 35), chose "every binding form binds", comprehension targets included, and wrote in its Risk that the author "may omit comprehension targets (which have their own scope in Python 3)". Runs 5, 6, 7 have no entry mentioning comprehensions and pass; min11-b has T17 "Comprehension and lambda scopes" and passes. Taste (Python 3 scoping assumed), one run against eleven: not worth a sentence.

### N2. ckpt1 `test_complete_module_attribute_respects_all` — run 3 only (11/1/1)

Test (`:620`): `mod.py` = `__all__ = ['public']\npublic = 1\n_hidden = 2`; `import mod\nmod.|` must offer `public` and not `_hidden`. Run 3 passes it at checkpoint 1 and fails it from checkpoint 2 on: `assert '_hidden' not in ['public', '_hidden', '__all__']`. By hand, run 3's checkpoint_2 snapshot lists `_hidden` for a local module even with no `__all__`, while its checkpoint_1 snapshot lists only `public`. `checkpoint_1.md:51` already says "return the module's public names. A name is public if it does not start with `_`." Process: the checkpoint-2 rewrite dropped the underscore filter for local modules (I did not trace the exact line). Not a reading.

### N3. ckpt2 `test_complete_union_dedupe_keeps_single_candidate` — run 3 only of the seven (8/4/1; also fails in sonnet-4.6, fable-5, min11-b)

Test (`test_checkpoint_2.py:653`): `A.common` is a method, `B.common = 1`, `x` is `A() | B()`; `x.co|` must give one `common` whose `type` is `function` or `statement`. Run 3 printed `assert 'instance' in {'statement', 'function'}`: it kept B's entry (`instance`, `instance of int`). Runs 1, 2, 4-7 and the ref keep A's (`function`, `def common(...)`). By hand, every opus run types `B.common` alone as `instance`, so passing depends only on the first possible type winning the duplicate. `checkpoint_2.md:117` ("completions include attributes from **all** possible types") says nothing about duplicates. Taste with a noise-like flip rate; a fix would be "when two types share an attribute name, keep the one from the type that comes first", in checkpoint_2.md. I did not search the registries for it properly (my pattern was too loose), so registry status is unknown.

### N4. ckpt3 `test_from_import_completion_includes_package_submodules` and `test_relative_from_import_completion_includes_sibling_modules` — run 1 only (11/1/1 each)

Tests (`test_checkpoint_3.py:209, 231`): package `pkg/` with empty `__init__.py` and `helper.py`; `from pkg import he|` and, from `pkg/main.py`, `from . import he|` must offer `helper`. Run 1 printed `assert 'helper' in []` for both; by hand its snapshot returns `{"completions":[]}` where run 6 returns `helper` as a `module`. `checkpoint_3.md:72,75` say "`from X import ...` suggests names inside module `X`" and never mention submodules of a package. One sentence, two tests. Taste (Python's import semantics assumed), run 1 only; every later run gets it. Noise for patching purposes. Run 1 has no registry.

### N5. ckpt3 `test_goto_import_site_has_import_description_and_type` — run 1 only of the seven (10/2/1; sonnet-4.6 fails too)

Test (`:615`): `from shapes import Circle|`, `goto` without `--follow-imports` must return the import site with `"from shapes import Circle"` in the description and `type == "class"`. Run 1 printed `assert 'module' == 'class'`; by hand it returns the right import site with `"type":"module"`. `checkpoint_1.md:91` already says an imported name's `type` "reflects the imported object's actual kind if inferable", and run 6 prints `class`. Process: run 1's bug against words the spec has (the words are in checkpoint 1's completion table, not repeated in checkpoint 3's `goto` section, which is the only excuse). `checkpoint_3.md:49` also ends in a colon with its example missing.
