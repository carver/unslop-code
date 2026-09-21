# family-2: sith checkpoint 4, names/search block and references-unresolved

Runs: 1 dev6-opus5 just-solve 20260830T0354, 2 just-solve 20260915T1324, 3 anti_slop 20260920T0212, 4 min12 20260915T0053, 5 min12 20260915T0719, 6 min13 20260919T0435, 7 min13 20260919T1433. min11a = min11 20260908T0219, min11b = min11 20260908T0846.
Spec = ~/.cache/scbench/problems/sith/checkpoint_4.md. Tests = ~/.cache/scbench/problems/sith/tests/test_checkpoint_4.py. Reference = ~/.cache/scbench/problems/sith/solutions/checkpoint_4/sith.py.
Registry entries below are copied by script from each run's sith/checkpoint_4/snapshot/AMBIGUITIES.md, not retyped. No entry in any of the six registries has a Differs section (grep for "Differs" over all six cp4 registries returns nothing).

---

## Sentence A: the top-level JSON key of `search` and `names` (10 tests)

Tests: test_names_all_scopes_includes_local_and_nested, test_names_default_includes_imports, test_names_default_only_returns_module_scope, test_names_default_preserves_repeated_top_level_bindings, test_names_is_definition_always_true, test_names_sorted_by_line_column, test_search_across_multiple_files, test_search_excludes_local_variables, test_search_matches_case_insensitive_query, test_search_sorts_exact_before_prefix_before_substring.

The one choice is the envelope key. The hidden tests read `search` output under `"results"` and `names` output under `"names"`. Runs 1, 2, 3, 6 print both under `"definitions"`. Exit code, single-line JSON and the helper's parsing are fine in every run.

### 1. Spec

The spec has no sentence that names either key. Nearest sentences, checkpoint_4.md:

- :71 `Search for names matching `<query>` across the project. Returns definitions (not usages).`
- :73 `Each result has the same fields as a definition object (from `infer`/`goto`), minus `docstring`.`
- :89 `List names defined in a file.`
- :91 `Each entry has the definition fields plus `is_definition` (always `true` for this command).`
- :34 `If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0).` This is the only place cp4 names an array at all, and every run got `signatures` and `references` right.

Earlier checkpoints do state the key, which the cp4 agent cannot see except through its own code:

- checkpoint_1.md:14 `Output is JSON to STDOUT — a single JSON object with a `"completions"` array.`
- checkpoint_2.md:16 `... Output is a JSON object with a `"definitions"` array.` (same sentence at :26 for `goto`)

cp4 dropped that sentence for all four new commands. Lines 71 and 73 pull in opposite directions: "Returns definitions" and "definition object" point at `definitions`, "Each result" points at `results`.

### 2. Test and reference

Helper, test_checkpoint_4.py:154-157:

```python
def _field(payload: dict, field: str) -> list[dict]:
    value = payload.get(field, [])
    assert isinstance(value, list)
    return value
```

A missing key becomes `[]` without error. So a wrong key fails every test that expects content and passes every test that expects absence. test_search_excludes_imported_names and test_search_no_results_returns_empty_array pass 12/12 for that reason, including in the runs that answer under `definitions`. They prove nothing in those runs.

Two fixtures, the rest follow the same shape:

```python
# test_search_sorts_exact_before_prefix_before_substring (:287)
"main.py": "calc = 1\ndef calculator():\n    return 1\n\ndef recalcify():\n    return 2\n"
results = _field(parse_json_result(result), "results")
names = [r["name"] for r in results]
assert names[0] == "calc"

# test_names_default_only_returns_module_scope (:334)
"main.py": "top = 1\ndef outer():\n    inner_local = 2\n    return inner_local\n"
names = [item["name"] for item in _field(parse_json_result(result), "names")]
assert "top" in names
```

Reference, solutions/checkpoint_4/sith.py:

- :2793-2795 `def _format_search_output(results)`: `payload = {"results": results}`
- :2798-2800 `def _format_names_output(names)`: `payload = {"names": names}`
- :2778-2779 `definitions` stays for infer/goto, :2783-2790 `signatures` and `references`.

### 3. What each run printed

Pytest does not show stdout for these tests, only the emptied list, so the keys come from each run's code.

| run | search key | names key | source | block result |
|---|---|---|---|---|
| 1 | definitions | definitions | sith.py:4389, :4402, :4426 (docstring :25 says so) | 10 fail |
| 2 | definitions | definitions | sith.py:4619, :4664 | 10 fail |
| 3 | definitions | definitions | sith.py:59-60 | 10 fail |
| 4 | results | names | sith.py:3898-3899 | pass |
| 5 | results + definitions alias | names + definitions alias | sith.py:3424, :3435 | pass |
| 6 | definitions | definitions | sith.py:83-84 | 10 fail |
| 7 | definitions + results | names + definitions | sithlib/listing.py:53, :35 | pass |
| min11a | definitions | names | sith.py:3238, :3245 | 4 search fail, 6 names pass |
| min11b | results | names | sith.py:3440-3441 | pass |

Failure lines are identical in runs 1, 2, 3, 6 (evaluation/stdout.txt): `IndexError: list index out of range` (search sorts), `assert 'top' in []`, `assert [] == [(1, 0), (2, 0)]`, `assert 'local_name' in []`, `assert 'target' in []`, `assert 'MixedCaseValue' in []`, `assert 'alpha.py' in set()`, `assert [] == ['first', 'second', 'third', 'Fourth']`, `assert 0 >= 3`, `assert 'os' in []`. Every one is an empty list from `_field`'s default. min11a shows only the four search lines.

Run 7 and run 5 pass by printing the list under two keys. Both registered that as a hedge. Run 4 and min11b picked the hidden keys outright. Run 6 considered `results` and `names` and chose against both.

The block carries forward as regressions. Run 6 fails the same 10 at cp4, cp5 and cp6 (10 `^FAILED` names/search lines in each evaluation/stdout.txt).

### 4. bin/test-history

- The six test_names_* tests: 8 pass, 4 fail, 1 not reached. Fails are runs 1, 2, 3, 6.
- The four test_search_* tests: 7 pass, 5 fail, 1 not reached. Fails are runs 1, 2, 3, 6 and min11a.
- Non-opus runs (sonnet-4.6, fable-5, fable-5-1 just-solve) all pass both groups. Every opus-5 run without a registry (1, 2, 3) fails.

### 5. Registry entries

Every registry run registered it.

**Run 6, T51. Choice missed (definitions).**

~~~~
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
~~~~

**Run 6, T52. Choice missed (definitions). Its Risk line names the hidden reading as the author's likely preference and the run still chose against it.**

~~~~
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
~~~~

**Run 7, T45. Choice matched by printing both keys.**

~~~~
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
~~~~

**Run 4, T65. Choice matched (results, names).**

~~~~
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
~~~~

**Run 5, T53. Choice matched, plus a `definitions` alias.**

~~~~
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
~~~~

**min11a, T51. Choice matched for `names`.**

~~~~
## T51 — The top-level JSON key of `signatures`, `references` and `names`

### Spec Text
> If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0).

> ### `references`
> Find all locations where the name at the cursor is referenced (used or defined).

> ### `names`
> List names defined in a file.

### Alternatives
1. Each new subcommand prints one object keyed by the command's own name:
   `{"signatures":[...]}`, `{"references":[...]}`, `{"names":[...]}`.
2. Every command reuses the existing `{"definitions":[...]}` envelope.
3. A neutral key such as `results` for all of them.

### Choice
Alternative 1. The spec names the payload for `signatures` outright ("an empty
signatures array"), and the tool's established convention is a single key named after
what the command produces (`complete` -> `completions`, `infer`/`goto` ->
`definitions`). `references` and `names` follow the same pattern.

### Risk: 15
Author's most likely alternate reading: `references`/`names` reuse the `definitions`
key because their entries are definition objects (Alternative 2).
~~~~

**min11a, T52. Choice missed for `search` (definitions), at Risk 50.**

~~~~
## T52 — The top-level JSON key of `search`

### Spec Text
> Search for names matching `<query>` across the project. Returns definitions (not usages).

> Each result has the same fields as a definition object (from `infer`/`goto`), minus `docstring`.

### Alternatives
1. `{"definitions":[...]}`, because the entries are definition objects and the spec
   describes the command as returning definitions.
2. `{"results":[...]}`, following the spec's own noun ("Each result ...").
3. `{"search":[...]}`, the command-named key used by the other new subcommands.

### Choice
Alternative 1. The spec twice calls the payload "definitions" ("Returns definitions",
"the same fields as a definition object") and never names a `search` array the way it
names the "signatures array", so the existing `definitions` envelope is the closest fit.

### Risk: 50
Author's most likely alternate reading: `{"results":[...]}`, mirroring the spec's word
"result" (Alternative 2).
~~~~

**min11b, T59. Choice matched (results, names).**

~~~~
## T59. The top-level JSON key of each new subcommand

### Spec Text
> If the cursor is not inside a call's parentheses, return an empty signatures array (exit 0).

### Alternatives
1. Each command answers under a key named after what it returns: `signatures`, `references`, `names`, and — for `search`, whose command name is a verb — `results`.
2. `search` answers under `definitions`, because "Each result has the same fields as a definition object".
3. Every command answers under the literal subcommand word, so `search` answers under `search`.

### Choice
Alternative 1. The existing commands name the key after the payload (`complete` → `completions`, `infer`/`goto` → `definitions`), and the spec's own prose says "an empty **signatures** array", which fixes that key by name; `references` and `names` follow the same plural-noun pattern. `search` has no noun of its own in the spec, and the prose calls each entry "a result", so `results` is the reading that matches the established convention.

### Risk: 45
`search` is the weak point: the author may well have used `definitions`, since the spec describes the entries only in terms of definition objects.
~~~~

### 6. Classification: reading, caused by a missing sentence

cp1 and cp2 state the key in a sentence. cp4 omits it, and its nearest words ("Returns definitions", "Each result", "Each entry") support `definitions`, `results` and `names` about equally. This is not an agent bug. All six registry runs flagged it, with Risk from 15 to 50, and they split 4 to 2 on `search` and 5 to 1 on `names`. The two aliasing runs (5, 7) show the registry working as intended. Run 6 shows it failing: T52 predicted the author's key and chose the other one for consistency.

The hidden test is not against the spec. It asserts a key the spec never gives.

### 7. Replacement sentences (checkpoint_4.md)

Smallest, one per command, in the cp2 form:

- After :71, `Output is a JSON object with a `"results"` array.`
- After :89, `Output is a JSON object with a `"names"` array.`

For symmetry the same sentence could go under `signatures` (`"signatures"`) and `references` (`"references"`), though no run missed those.

Alternative, one line in Clarifications (:131-133): `Each new subcommand prints a JSON object with one array: `"signatures"`, `"references"`, `"results"` (for `search`) and `"names"`.`

Over-correction to avoid: a full example output line for `search` or `names`. It would also settle `type`, `description` and `full_name` of search hits, which other tests measure. Also avoid "exactly one key", which would turn the aliasing in runs 5 and 7 into a new question the tests do not ask.

---

## Sentence B: `references` on a name that resolves to nothing (1 test)

Test: test_references_unresolved_name_returns_empty. Fails in 1, 2, 4, 5, 6. Passes in 3, 7.

### 1. Spec

The spec does not say what `references` returns for an unresolved name. Nearest sentences, checkpoint_4.md:

- :46 `Find all locations where the name at the cursor is referenced (used or defined).`
- :59 `For project-scope search, return only occurrences that resolve to the same symbol identity as the cursor target (do not include same-spelling but unrelated symbols in other scopes).`
- :133 `` `references` output always includes the definition occurrence when one is found and is sorted by `(module_path, line, column)`. ``

The precedent lives in checkpoint_2.md, which the cp4 agent does not see: :18 `If the cursor is not on a name, exit 1. If the name cannot be resolved, return an empty array (exit 0).` and :28 `If no definition is found, return an empty array (exit 0).` cp4 has no such sentence for `references`.

The test runs with `--scope project`, so :59 is the sentence in play. The test reads "resolve to the same symbol identity as the cursor target" as: no identity at the cursor, so nothing matches. The failing agents read :46 literally, a use is a reference, and treat :59 as a filter that only applies when there is an identity to filter by. :133's "when one is found" allows output without a definition, which leans toward the agents.

### 2. Test and reference

test_checkpoint_4.py:992-1004:

```python
result = run_references(entrypoint_argv, tmp_path, "main.py", "unknown|\n", scope="project")
assert result.returncode == 0, result.stderr
assert _field(parse_json_result(result), "references") == []
```

The file is one line, `unknown`, with the cursor at column 7, just past the last letter.

Reference, sith.py:3305-3315:

```python
identifier = _identifier_at_cursor(current_line, col)
if identifier is None:
    sys.stdout.write(_format_references_output([]))
    return 0
...
bindings = _visible_name_bindings(scope_info, name, line)
if not bindings:
    sys.stdout.write(_format_references_output([]))
    return 0
```

`_visible_name_bindings` (:1201-1215) walks source scopes only. Reading the code, a builtin such as `print` would also give `[]` in either scope. I did not run the reference to confirm.

### 3. What each run printed

Every failing opus run, and min11a, fable-5 and fable-5-1, printed the same thing:

`assert [{'module_path': 'main.py', 'line': 1, 'column': 0, 'is_definition': False}] == []`

sonnet-4.6 failed differently: `AssertionError: Error: no identifier at cursor position`, exit 1. It rejected a cursor at the end of the name. That is a cursor-position miss, not this sentence.

Why the failing runs list the use:

- Run 6, sithlib/references.py:125-131, deliberate: `return not wanted or not reached or bool(wanted & reached)` with the docstring "A name that resolves to nothing -- a builtin, or something the project does not define -- has no identity to compare, so its spelling is all there is."
- Run 5, sith.py:3231 `if keys:` applies the identity filter only when the cursor has an identity, otherwise every spelling counts.
- Run 4 registered the choice (T85 below). I did not read runs 1, 2 or min11a for the mechanism.

Why the passing runs return `[]`:

- Run 7, sithlib/references.py:46 and :74: in project scope `wanted` is the cursor's identity set. For `unknown` it is empty, so `wanted & ...` is empty and nothing is yielded. In file scope `wanted` is `None` and the same file would list the use. The pass depends on the test using `--scope project`.
- Run 3, sithlib/references.py:59: `if _identity(...) & wanted`, empty for an unresolved cursor in both scopes.
- min11b, sith.py:3221: `if not wanted or not (here & wanted): continue`, project scope only. File scope (:3198-3202) lists every spelling.

None of the three passing runs wrote a comment or registry entry about unresolved names. Their `[]` falls out of set intersection. The passes look accidental, which is my inference from the code, not something the agents said.

The failure carries forward. Run 6 fails it at cp4, cp5 and cp6.

### 4. bin/test-history

3 pass, 9 fail, 1 not reached. Pass: run 3, run 7, min11b. Fail: sonnet-4.6 (different cause), runs 1, 2, 4, 5, 6, fable-5, fable-5-1, min11a.

### 5. Registry entries

**Run 4, T85. The only entry on it. Choice missed (lists same-spelling occurrences). It rated this Risk 25 and guessed the author agreed.**

~~~~
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
~~~~

Unregistered in runs 5, 6, 7, min11a, min11b. Closest entries, none of which covers an unresolved name:

- Run 5 T60 "Exit status of `references` when the cursor is not on a name" (chose exit 1).
- Run 6 T68 "What `references` does when the cursor is not on a name" (exit 1 for no name, `[]` for a literal) and T58 "Whether file-scope `references` filters by symbol identity". Run 6 made the unresolved-name decision in code (references.py:125-131) without registering it.
- Run 7 T52 "Which occurrences a file-scope `references` search keeps" (file scope by spelling, project scope by identity). That split is what makes run 7 pass under `--scope project`.
- min11a T57 "Whether file-scope `references` filters by symbol identity" and T59 "`references` and `signatures` when the cursor is not on a name".
- min11b T76 "`references` with the cursor not on a name". Its Risk line, "The author may have made all the new commands uniformly total, answering an empty array whenever nothing is found", comes nearest but concerns a cursor off any name.

### 6. Classification: reading, leaning taste

Test and agents split on :59 together with :46. Does a cursor target with no symbol identity match nothing, or does the identity filter fall away and leave spelling? The hidden reading is the cp2 convention ("cannot be resolved, return an empty array") carried to a new command without restating it, which is the taste part. Two agents (runs 4 and 6) chose the other side on purpose with a stated reason, and :133 "when one is found" gives them some cover. It is not an agent bug and not noise. The 3 passes are side effects of implementation, so the flip between runs 6 and 7 has no decision behind it on the passing side.

### 7. Replacement sentence (checkpoint_4.md)

After :46, in the cp2 form:

`If the name at the cursor cannot be resolved to a definition, return an empty `references` array (exit 0).`

Or folded into the Clarifications line :133: `` `references` returns an empty array when the name at the cursor has no definition; otherwise the output always includes the definition occurrence and is sorted by `(module_path, line, column)`. `` This also removes "when one is found", the phrase that supports the other reading.

Over-correction to avoid: saying what happens when the cursor is not on a name at all. Runs 5, 6, min11a and min11b all chose exit 1 there, the reference returns `[]` exit 0 (:3306-3308), and I did not check whether a hidden test covers it. Keep the new sentence to unresolved names. Also avoid naming builtins in it. The reference returns `[]` for them by my reading of the code, but no test I read asks.
