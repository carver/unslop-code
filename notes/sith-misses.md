# sith: the v0 misses, by sentence (2026-09-20)

Step 1 and the first half of step 2 of `/solve-one-problem`, from seven opus-5 runs on the
unpatched spec (just-solve 191 and 194, anti-slop 189, min12 205 and 204, min13 195 and 211, of
228) plus the two min11 runs where a registry helps. Fifty tests fail somewhere. Counts are
`bin/test-history` over all twelve complete sith runs, the sonnet and fable ones included. No
patch is written; the pitch goes to the user first. The five reader reports with every
registry entry in full are in `notes/sith-misses/family-1.md` to `family-5.md`. Registry
entries below are copied from the runs' `AMBIGUITIES.md`, not retyped, and cut to the sections
that matter (a `[...]` marks a cut inside one). The reader reports are sub-agent output, kept
as evidence and not edited. Run 6 is min13's first
run (`…min13-ABDJKMNT/20260919T0435`), run 7 its repeat (`…/20260919T1433`), run 4 and run 5
the min12 pair.

Fourteen tests fail in all seven runs. Seven of them are not readings at all: a fake
interpreter that answers only the reference's own command lines (five) and a fixture whose
expected output changes what the function returns (two).

## Readings

1. **`search` answers under `results`, `names` under `names`.** Ten tests, checkpoint 4, one
   block: fails in both just-solve runs, anti-slop and run 6, passes in runs 4, 5, 7. names 8
   pass, 4 fail; search 7 pass, 5 fail. checkpoint_4.md never names either key.
   checkpoint_1.md:14 and checkpoint_2.md:16 each have the sentence ("Output is a JSON object
   with a `"definitions"` array"); checkpoint 4 dropped it, and its nearest words pull three
   ways: :71 "Returns definitions (not usages)", :73 "Each result has the same fields as a
   definition object", :91 "Each entry has the definition fields". The test helper turns a
   missing key into `[]`, so every content assertion fails on an empty list. Reference
   `sith.py:2794` `{"results": results}`, `:2799` `{"names": names}`. Runs 5 and 7 pass by
   printing the list under two keys. Run 6 named the hidden key and chose against it:

   ```
   ## T52. The JSON key `names` answers under

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
   ```

   Run 7's T45 (Risk 30): "`search` writes `definitions` and `results`, `names` writes `names`
   and `definitions`. The lists are the same objects, so any of the plausible readings finds
   the answer where it expects it."

2. **`--until N:0` means up to the end of line N-1.** Six extract-function tests, checkpoint
   5: 3 pass 9 fail (two), 4 pass 8 fail (three), 8 pass 4 fail (param order).
   checkpoint_5.md:82 "Extract the code from `<line>:<col>` to `--until <line>:<col>` into a
   new function." and :85 "The selection must span one or more complete statements (full
   lines). If it spans a partial statement, exit 1." Every fixture sends `2 0 --until N:0`
   with line N the first line not selected. The reference treats both ends as half-open
   character offsets (`sith.py:4462`). Runs 1 and 6 swallow line N (the `return`), so nothing
   comes back from the helper; runs 2, 3, 5 exit 1 on a half-selected line N; runs 4 and 7
   read it the editor's way. Run 6's snapshot given `--until 4:21` prints the expected text
   exactly, so addressing is its only miss here. The tests compare substrings, so layout
   (both min13 runs' top Risk, 55) is never measured. Run 7, the one entry on the right
   question, against run 6:

   ```
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
   ```

   ```
   ## T88. Whether the columns of an `extract-function` selection are checked

   ### Alternatives
   1. Only the lines matter; the columns are ignored, since the selection is defined in terms
      of full lines.
   2. The columns must also land exactly on the start and end of the statement run.

   ### Choice
   (1). "(full lines)" says what the unit is. An editor selecting whole lines puts the end
   column at 0 of the next line or at the end of the last one, and neither is the statement's
   own end column, so checking columns would refuse the ordinary case.

   ### Risk: 20
   Author most likely prefers: (1).
   ```

3. **`infer` on a parameter returns the parameter.** `test_infer_is_not_none_narrowing_excludes_none`,
   checkpoint 2, 0 pass 12 fail. The name misleads: the fixture is `def f(x):` / `if x is not
   None:` / `return x|` with `x` unannotated, and the test asserts only a non-empty list.
   checkpoint_2.md:18 "If the name cannot be resolved, return an empty array (exit 0)."
   Reference `sith.py:1172`: a `param` symbol resolves to itself, printed as `"type":"param",
   "description":"param x"`. All nine opus runs print `[]`, with or without the `if`. The
   tests' "cannot be resolved" is a name bound nowhere; the agents' is a name whose value is
   unknown. Only run 5 wrote the sentence down:

   ```
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
   ```

4. **A namespace attribute completes with its owner's type.**
   `test_runtime_attribute_completion_from_namespaces`, checkpoint 6, 2 pass 10 fail (run 6 and
   fable-5 pass). checkpoint_6.md:34 "For namespace-derived results, `description` is exactly
   `"{type} (runtime)"` and `type` is the namespace type string." Namespace `df` of type
   `DataFrame` with attributes `groupby, merge, head`; the test wants `groupby` as `type
   "DataFrame"`, `"DataFrame (runtime)"`. Reference `sith.py:1520-1543` reuses the owner's
   type. Everyone else prints `instance`. All six registries carry it at Risk 45 to 55. Run 6
   (passes) and run 7 (fails) on the same two quoted lines:

   ```
   ## T97. What type a namespace attribute completes as
   ### Choice
   (1). The rule about `{type} (runtime)` is written as covering every namespace-derived
   result, and the file gives no type for an attribute of its own; taking the owner's keeps
   the stated invariant literally true.
   ### Risk: 45
   ```

   ```
   ## T100 — The attributes a namespace only names
   ### Choice
   Alternative 1. The completion vocabulary has no "unknown" kind, and an
   attribute reached through a namespace is as much a runtime result as the name
   that owns it, so it keeps the `"{type} (runtime)"` shape with the only type
   that fits an unclassified value.
   ### Risk: 55
   This is the least constrained corner of the spec: the author may equally well
   use the owner's type or an empty description, and any fixture that completes
   after a dot on a namespace object tests it.
   ```

5. **`references` on a name bound nowhere is empty.** `test_references_unresolved_name_returns_empty`,
   checkpoint 4, 3 pass 9 fail. File `unknown`, `--scope project`, wants `[]`. checkpoint_4.md
   is silent; the "cannot be resolved, return an empty array" sentence is checkpoint_2.md:18,
   which the checkpoint-4 agent never sees, and :133 "always includes the definition occurrence
   when one is found" leans the other way. Failing runs list the use at 1:0. The three passes
   fall out of intersecting empty identity sets; none of them decided it. Run 4's T85 did, the
   other way: "Reporting an empty array for a name the user can plainly see twice in the file
   is worse than reporting both" (Risk 25).

6. **`smart_sys_path` puts every `__init__.py` directory on the path.**
   `test_setting_smart_sys_path_changes_resolution`, checkpoint 6, 5 pass 7 fail (run 1, run 5,
   both min11 among the fails). checkpoint_6.md:115 "When true, automatically add the project
   root and directories containing `__init__.py` to sys.path." The test wants `import helper`
   to find `extras/helper.py`. The literal reading passes; the agents that fail talked
   themselves out of it because a package directory on `sys.path` is wrong Python. Run 7 took
   the sentence at its word and bet the author had not (T105, Risk 40: "The author most likely
   adds the project root and the parent of the topmost package only").

7. **Default `goto` on a use of an imported name lands in the other file.** The two stub
   tests, checkpoint 4, 0 pass 12 fail. They are not about stubs. Fixture `from util import
   work` / `work|()`, no `--follow-imports`, wants `module_path == "util.py"`; every run
   answers `main.py`, the import statement, as checkpoint_3.md:49 tells it to ("Without
   `--follow-imports` (default), `goto` on an imported name returns the `import` statement
   itself"). The checkpoint-4 reference adds `should_follow = follow_imports or line !=
   symbol.line` (`sith.py:3706`); the checkpoint-3 reference has plain `if follow_imports:`,
   and checkpoint_4.md never mentions the flag. No other test in checkpoints 3 to 6 puts a
   `goto` cursor on a use line. With `--follow-imports` added by hand, seven of nine snapshots
   give the expected path (runs 5 and 6 cannot resolve a module that exists only as
   `stubs/only_stub.pyi`, a bug this miss hides). The hidden test contradicts the spec as
   written. Every registry settled the question at checkpoint 2 and marked it confirmed at 3,
   run 6's T29: "Settled: both readings are now commands of their own."

8. **A circular import hides names by line, pairwise.**
   `test_circular_import_hides_name_not_yet_defined`, checkpoint 3, 0 pass 12 fail.
   checkpoint_3.md:100 "Names not yet defined at the point of circular import are simply not
   visible." `a.py` = `from b import early` / `late = 1`; `b.py` = `from a import late` /
   `early = 2`; `main.py` = `from b import late`; wants `[]`. The reference hides a name of A
   from B when A imports B above the line that binds it (`sith.py:1406-1436`), whichever file
   the query starts from. Every run prints `int`. So would a faithful execution walk from
   `main.py`, and real Python raises `ImportError` on the fixture. Run 4 predicted the fixture
   and chose the other side:

   ```
   ## T64. What a circular import makes visible
   ### Choice
   Interpretation 2. The tool never executes code, so there is no "point of execution" to cut at —
   the cut the spec asks for is the one that keeps resolution terminating, which a per-chain visit
   set and a depth cap provide. [...]
   ### Risk: 35
   Author most likely prefers: the same for termination; a fixture built to test "not yet defined"
   visibility — importing a name defined below the circular import line — would expect an empty
   result where this implementation resolves it.
   ```

## Taste

9. **A parameter's completion description is `param <name>`.** checkpoint 1, 7 pass 5 fail
   (runs 2, 3, 4 of the seven). checkpoint_1.md:89 gives a description for functions, classes,
   imports, assignments and keywords, none for `param`. Reference `f"param {arg}"`. Every
   registry flagged it at Risk 45 to 60, the top entry of most runs; run 4 (T10) chose bare
   `param` while naming `param <name>` as the author's likely pick.
10. **`signatures` on a `@dataclass` call lists the annotated fields.** Two tests, checkpoint
    4, 2 pass 10 fail. checkpoint_4.md has no dataclass word; the only one is checkpoint_2.md:93,
    unseen at 4. Runs look up `__init__`, find none, print `params: []`. Unregistered in all
    six; run 2 added it unprompted. The reference has no `__init__` path at all, so a plain
    class gets `[]` from it, the mirror image of the agents.
11. **`env info` prints a bare object.** checkpoint 6, 9 pass 3 fail (run 3, run 6, min11's
    first). The spec names no envelope for any `env` command; the tests want `{"environments":
    [...]}` for lists and a flat record for `env info`. Run 6's T92 chose `{"environment":
    {...}}` and said where it would miss: "`env info` is where a different key (or a bare
    object) is most likely, since the spec never names one."

## Not the spec (upstream)

- **The fake interpreter answers only the reference's three command lines.** Five `env list`
  and `env info` tests, 0 pass 12 fail, and the two `find-virtualenvs` tests, 3 pass 9 fail.
  `_make_fake_python` (test_checkpoint_6.py:19-60) dispatches on substrings of `argv`:
  `--version`, `"sys.prefix != sys.base_prefix" in code`, then `"sys.prefix" in code and
  "sys.path" in code`. The reference makes exactly those three calls (`sith.py:5106-5145`).
  All nine opus runs send one `-c` probe for everything; it contains both words, so the fake
  answers `{"prefix", "sys_path"}` with no version and the run drops the interpreter (runs 3
  and 7 crash on `KeyError: 'version'`, their own bug). A real CPython answers every run's
  probe. No run has ever reached the sort or dedupe assertions. Run 5 passes
  `find-virtualenvs` by listing any `bin/python` with `version: ""`, against
  checkpoint_6.md:62. Not checked: that the reference passes these in the container.
- **`extract-variable` on `a + <<b - a>> * t`.** Two tests, 0 pass 12 fail. `a + b - a * t`
  parses as `(a + b) - (a * t)`; no node is `b - a`, and the expected `delta = b - a` /
  `return a + delta * t` returns 2.0 where the original returned 3.5 (a=1, b=3, t=0.5). The
  reference accepts any selection whose text parses alone (`sith.py:4326`). Every run matches
  AST nodes and exits 1 with the spec's own message, checkpoint_5.md:67. Unregistered
  everywhere. The fixture likely lost a pair of parentheses.

## Process

- **Aliased import left behind by `rename`.** `test_rename_updates_alias_backed_…`, 3 pass 9
  fail (passes in the two just-solve runs). `from shapes import Circle as Shape`; renaming
  `Circle` rewrites `shapes.py` only and leaves `main.py` importing a name that is gone.
  checkpoint_5.md:27 already says "All references found via the same logic as `references
  --scope project` are renamed." The runs' `references` never offers the `Circle` token of an
  aliased import (run 6 `references.py:83` matches `binding.name == name`, and the binding is
  `Shape`). Unregistered in all six: nobody chose this. Systematic enough that a sentence
  might still pay.
- `project init` rewrites a stored `null` to `""` (7 pass 5 fail; runs 1, 2, 5), against
  checkpoint_6.md:119. Run 4's aug-assign bug emits `def sum_values(total, data)`. Run 4
  accepts a selection that reaches past a `for` body. Run 3 validates names with
  `isidentifier()` alone, so `for` and `class` pass.

## Singles

Comprehension variable scope (run 4, a registered choice), `__all__` on a module attribute
and union dedupe (run 3), the two submodule completions and the import-site `type` (run 1),
interpreter `goto` `full_name` (run 2). One run each; noise until they recur.
