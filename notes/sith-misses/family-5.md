# Family 5: sith checkpoint 6 (environments, projects, interpreter mode)

Runs: 1 = dev6-opus5 just-solve 20260830T0354, 2 = just-solve 20260915T1324, 3 = anti_slop 20260920T0212, 4 = min12 20260915T0053, 5 = min12 20260915T0719, 6 = min13 20260919T0435, 7 = min13 20260919T1433. Registry runs are 4 to 7 plus the two min11 runs (20260908T0219, 20260908T0846). Registry entries below are copied by script from each run's `sith/checkpoint_6/snapshot/AMBIGUITIES.md`, so they are verbatim. Counts come from `bin/test-history` over all 13 sith runs (one run never reached checkpoint 6).

Paths: spec `~/.cache/scbench/problems/sith/checkpoint_6.md`, tests `~/.cache/scbench/problems/sith/tests/test_checkpoint_6.py`, reference `~/.cache/scbench/problems/sith/solutions/checkpoint_6/sith.py`.

Summary table

| # | Sentence | Tests | Class | pass/fail |
|---|----------|-------|-------|-----------|
| A | none. The spec never says how to probe an executable, and the fake python only answers the reference's three invocation forms | 5 env list / env info tests | upstream | 0/12 each |
| A2 | same fake, sidestepped by listing on layout alone | 2 find-virtualenvs tests | upstream (passes are luck of a fallback) | 3/9 each |
| B | checkpoint_6.md:34, "`type` is the namespace type string" applied to `attributes` | test_runtime_attribute_completion_from_namespaces | reading | 2/10 |
| C | checkpoint_6.md:115, "directories containing `__init__.py`" | test_setting_smart_sys_path_changes_resolution | reading | 5/7 |
| D | checkpoint_6.md:89, "Additional field vs `env list`" (envelope of `env info`) | test_env_info_default_executable_includes_sys_path | taste | 9/3 |
| E | checkpoint_6.md:119 plus :112 (`string or null`) | test_project_init_merges_only_passed_fields | process (agent normalises null) | 7/5 |
| F | none, `full_name` of a runtime definition is unstated | test_interpreter_goto_uses_first_namespace_match_wins | taste, one run | 9/3 |

---

## A. How an executable is probed (5 tests, fail in all 7 runs, 0 pass / 12 fail everywhere)

Tests: `test_env_list_includes_fake_envs`, `test_env_list_sort_order_descending_version`, `test_env_list_dedupes_symlinked_fake_executables`, `test_env_list_equal_versions_sort_by_executable_path`, `test_env_info_with_explicit_executable`.

This is not a reading. The fixture is a stub that pattern-matches the reference solution's own command lines.

### 1. Spec

The spec says nothing about how to learn `version`, `is_virtualenv`, `prefix` or `sys_path`. Nearest sentences:

- checkpoint_6.md:62 `` | `version` | string | Python version string (e.g., `"3.11.6"`). | ``
- checkpoint_6.md:63 `` | `is_virtualenv` | bool | `true` if the environment is a virtualenv/venv. | ``
- checkpoint_6.md:96 `If the executable is not found or not a valid Python, exit 1.`

### 2. Fixture, test, reference

Fixture, test_checkpoint_6.py:19-60 (`_make_fake_python`). It writes a python script with shebang `#!/usr/bin/env python3` that dispatches on substrings of `argv`:

```python
if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print(f"Python {VERSION}")
    raise SystemExit(0)

if len(sys.argv) > 2 and sys.argv[1] == "-c":
    code = sys.argv[2]
    if "sys.prefix != sys.base_prefix" in code:
        print("True" if IS_VENV else "False")
    elif "sys.prefix" in code and "sys.path" in code:
        print(json.dumps({"prefix": PREFIX, "sys_path": SYS_PATH}))
    elif "sys.prefix" in code:
        print(PREFIX)
    elif "sys.path" in code:
        print(json.dumps(SYS_PATH))
    elif "sys.version" in code:
        print(VERSION)
    else:
        print("")
    raise SystemExit(0)

print(f"Python {VERSION}")
```

The tests put fakes named `python3.10` / `python3.11` / `python3.12` / `python` in a tmp `bin/` prepended to `PATH` (lines 155-176, 534-558, 714-739, 743-781) or pass the fake to `env info` (179-196), then assert on `version`, `prefix`, `is_virtualenv`, count and order.

Reference, sith.py:5105-5159. Three separate invocations that line up one to one with the fake's branches:

- 5106 `_run_command_capture([str(executable), "--version"])`, parsed by `re.search(r"Python\s+(\d+\.\d+(?:\.\d+)?)", text)` (5070)
- 5115-5121 `-c "import sys; print(sys.prefix != sys.base_prefix)"`, compared to the string `"True"` (5124)
- 5136-5145 `-c "import json,sys; print(json.dumps({'prefix': sys.prefix, 'sys_path': list(sys.path)}))"`

Discovery is every executable file on `PATH` whose name starts with `python` (5176-5201), resolved, deduped, sorted (5162-5173).

### 3. What the runs did

All nine opus runs I opened (1 to 7 and both min11) probe with ONE `-c` script that prints version, prefix, base_prefix and sys.path as JSON. Locations: run 1 sith.py:6127-6135 and 6202; run 2 sith.py:6195-6204 and 6296; run 3 sithlib/environments.py:17 and 103; run 4 sith.py:4826 and 4840; run 5 sith.py:4571-4576 and 4594; run 6 sithlib/environments.py:28-32 and 88-91; run 7 sithlib/environments.py:23-29 and 81-85; min11 sith.py:4220/4236 and 4415/4434.

Any such script contains both `sys.prefix` and `sys.path`, so the fake takes its second branch and answers `{"prefix": ..., "sys_path": ...}` with no version. I rebuilt the fixture's fake in the scratchpad (`f5fake/mk.py`) and sent it each form:

```
ref --version  rc=0 stdout='Python 3.12.9'
ref venv       rc=0 stdout='True'
ref info       rc=0 stdout='{"prefix": "/tmp/fakevenv", "sys_path": ["/tmp/fakevenv/lib"]}'
run6 PROBE     rc=0 stdout='{"prefix": "/tmp/fakevenv", "sys_path": ["/tmp/fakevenv/lib"]}'
run7 PROBE     rc=0 stdout='{"prefix": "/tmp/fakevenv", "sys_path": ["/tmp/fakevenv/lib"]}'
version only   rc=0 stdout='3.12.9'
platform       rc=0 stdout=''
```

Run 7 writes `sys.prefix!=sys.base_prefix` without spaces, so even the first branch does not match. With spaces the fake would print `True`, which is not JSON either.

Pytest output per run:

- `test_env_info_with_explicit_executable`: runs 1, 2, 4, 5, 6 exit 1 with "not a python environment" / "not a Python executable" / "not a valid Python executable" / "not a Python interpreter". Runs 3 and 7 crash with `KeyError: 'version'` (run 3 environments.py:91 `_record`, run 7 environments.py:92 `interrogate`). They index the parsed dict without checking it.
- the four `env list` tests: runs 1, 2, 4, 5, 6 and both min11 exit 0 with zero fake entries (`assert 0 >= 2`, `assert 0 == 1` with `[].count`). Runs 3 and 7 crash with the same `KeyError: 'version'`, so the whole command fails.

So the environment suspicion is half right. The container is fine (the fake ran and answered, rc 0). The fake is what is narrow. No run ever reached the sort or dedupe assertions, so those four tests have never measured sorting or deduping in any of the 12 runs.

Not checked: whether the reference solution passes these tests end to end in the evaluation container. I only confirmed that the fake answers the reference's three command lines.

### 4. Counts

All five tests: 0 pass, 12 fail, 1 not reached. That includes sonnet-4.6, fable-5 and fable-5-1 just-solve runs.

### 5. Registry

Unregistered in all six registries. No entry mentions `--version` or the form of the probe (grep for `--version` finds nothing in any of them). The closest entries register the neighbouring question "what if the interpreter is a stub that cannot answer":

**min11 20260908T0846, T95.** Closest of all. Names the one-liner probe as Alternative 1 and never doubts its form. Choice misses the tests for `env list` and `env info` (fake dropped) and hits them for `find-virtualenvs` (kept with version "").

> ## T95. Probing an executable, and what makes it a virtualenv
>
> ### Spec Text
> > | `version` | string | Python version string (e.g., `"3.11.6"`). |
> > | `is_virtualenv` | bool | `true` if the environment is a virtualenv/venv. |
>
> ### Alternatives
> 1. Run the candidate (`-c` one-liner) to read `sys.version_info`, `sys.prefix`, `sys.base_prefix` and `sys.path`; `is_virtualenv` is `sys.prefix != sys.base_prefix`, or the presence of a `pyvenv.cfg` beside the `bin/` directory.
> 2. Guess the version from the file name (`python3.11` -> `3.11`) and never execute anything.
> 3. Run it, and treat a probe failure as fatal.
>
> ### Choice
> Alternative 1. `"3.11.6"` has a patch component, which a file name never carries, so the interpreter must actually be asked. `pyvenv.cfg` is accepted as a second witness because a virtualenv's `bin/python` is normally a symlink to the base interpreter, and a stripped-down or fake environment (the kind a test builds) may not report a distinct `sys.prefix`. A candidate that cannot be probed is dropped from `env list` (it is not an installation) but kept by `find-virtualenvs`, where the directory layout already identifies it, with `version` `""`.
>
> ### Risk: 35
> An author who filters `find-virtualenvs` strictly on a successful probe would omit an unprobeable fake venv that this implementation still reports.
>
> ---
**run 5 (min12 20260915T0719), T101.** Picks the single probe. Misses.

> ## T101. The `version` string's shape
>
> ### Spec Text
> > | `version` | string | Python version string (e.g., `"3.11.6"`). |
>
> ### Alternatives
> 1. `major.minor.micro`, exactly as the example.
> 2. The full `sys.version` banner, or `major.minor`.
>
> ### Choice
> Alternative 1: `"%d.%d.%d" % sys.version_info[:3]`, obtained by running the candidate interpreter.
>
> ### Risk: 10
> The author most likely prefers: `major.minor.micro` (this choice).
>
> ---
**run 5 (min12 20260915T0719), T102.** This is the entry that makes run 5 pass A2. It predicts a mocked tree. It does not help `env list` or `env info`.

> ## T102. A virtualenv whose `bin/python` cannot be executed
>
> ### Spec Text
> > 1. The directory specified by `--path` (if given) — look for `bin/python` (Unix) or `Scripts/python.exe` (Windows) inside immediate subdirectories.
>
> ### Alternatives
> 1. The structural test is what defines a virtualenv here: any immediate subdirectory containing
>    `bin/python` is reported, with `version` taken from `pyvenv.cfg` if possible, else from running
>    the executable, else `""`.
> 2. Only executables that answer as a real Python are reported; a stub `bin/python` is skipped.
>
> ### Choice
> Alternative 1. The spec gives a purely structural rule for this command (unlike `env info`, which is
> explicitly allowed to exit 1 on "not a valid Python"), and a fixture that mocks up a virtualenv tree
> should still find it.
>
> ### Risk: 40
> The author most likely prefers: report whatever has the right layout (this choice); an implementation
> that insists on a working interpreter would return nothing for mocked trees.
>
> ---
**run 7 (min13 20260919T1433), T95.** Predicts a stub `bin/python`, but the fallback needs a `pyvenv.cfg` the fixture never writes, and the `KeyError` fires before the fallback anyway. Misses.

> ## T95 — A virtualenv whose interpreter cannot be run
>
> ### Spec Text
> > | `version` | string | Python version string (e.g., `"3.11.6"`). |
> > | `is_virtualenv` | bool | `true` if the environment is a virtualenv/venv. |
>
> ### Alternatives
> 1. Run the interpreter to read its version and prefix; when it cannot be run, fall back to the `pyvenv.cfg` that makes the directory a virtualenv, which records the version.
> 2. Report only interpreters that run, so a directory whose `bin/python` is a stub is not a virtualenv at all.
> 3. Never run anything: read `pyvenv.cfg` alone.
>
> ### Choice
> Alternative 1. Running the interpreter is the only way to learn `sys.path` and
> `sys.prefix`, which `env info` needs; `pyvenv.cfg` keeps a fixture virtualenv
> whose interpreter is a stub out of nobody's way. `env info` still fails for an
> interpreter that cannot be run, as the spec requires.
>
> ### Risk: 30
> If the author always executes the interpreter, a fixture virtualenv built
> without a working `bin/python` is missing from their answer, and `version`
> comes from the interpreter rather than from the config file.
>
> ---
**run 4 (min12 20260915T0053), T116.** Says everything the scan finds is reported as a virtualenv, but the code (sith.py:4888-4890) drops any candidate whose probe fails. Misses.

> ## T116. Deciding `is_virtualenv`, and whether `find-virtualenvs` filters on it
>
> ### Spec Text
> > | `is_virtualenv` | bool | `true` if the environment is a virtualenv/venv. |
> > Output: same format as `env list`, but only virtualenvs.
>
> ### Alternatives
> 1. `is_virtualenv` is `sys.prefix != sys.base_prefix`, and `find-virtualenvs` drops anything for
>    which that is false.
> 2. The venv-shaped location itself is the evidence: anything found at `<dir>/bin/python` (or
>    `<dir>/Scripts/python.exe`) is reported as a virtualenv.
>
> ### Choice
> A union of both: `is_virtualenv` is true when `sys.prefix != sys.base_prefix` **or** a
> `pyvenv.cfg` sits beside the `bin/` directory, and everything discovered by the virtualenv scan
> is reported with `is_virtualenv: true`.  "Only virtualenvs" then describes the search locations
> rather than a post-filter, so a hand-built environment in `~/.virtualenvs/` is not silently
> dropped from the command whose whole job is to list it.
>
> ### Risk: 35
> Author most likely prefers: the prefix comparison alone, with a filter — identical behaviour on a
> real `python -m venv` fixture, different only for a hand-made directory.
>
> ---
**run 6 (min13 20260919T0435), T108.** Requires the candidate to report itself as a virtualenv. Misses.

> ## T108. Which subdirectories `find-virtualenvs` accepts
>
> ### Spec Text
> > "look for `bin/python` (Unix) or `Scripts/python.exe` (Windows) inside immediate
> > subdirectories"
> > "Output: same format as `env list`, but only virtualenvs."
>
> ### Alternatives
> 1. A candidate must hold the interpreter *and* report itself as a virtualenv; a directory
>    with a `bin/python` that is a plain installation is dropped.
> 2. Anything holding `bin/python` is listed, `is_virtualenv` merely describing it.
>
> ### Choice
> (1). "Only virtualenvs" is a filter on the output, so a candidate that turns out not to be
> one does not belong in it. The standard locations are searched in the documented order --
> `--path`, `~/.virtualenvs`, then `.venv`/`venv` of the working directory and the project
> root -- and a directory that holds no interpreter at all is simply not a candidate.
>
> ### Risk: 20
> Author most likely prefers: (1).
min11 20260908T0219 has no probe entry. Its nearest are T106 (which installations `env list` looks for) and T107 (dedup of a venv symlink), neither about probing.

### 6. Classification

upstream. The fixture encodes the reference's implementation detail (three command lines, matched by substring) and the spec gives an implementer no way to know it. A real CPython answers every run's probe correctly. 0 of 12 runs across four models pass, which is what a broken fixture looks like and not what a contested sentence looks like. Secondary process note for runs 3 and 7: the `KeyError` crash is their own bug (unchecked dict from an untrusted subprocess), and it turns a dropped entry into a failed command.

### 7. If you patch the spec anyway

A spec sentence can work around the fixture, but it has to leak the probe forms. Candidate for checkpoint_6.md, after line 65:

> Read `version` from the output of `<executable> --version` (`Python X.Y.Z`). Decide `is_virtualenv` by running `<executable> -c "import sys; print(sys.prefix != sys.base_prefix)"` and checking for `True`.

and after line 94:

> Read `prefix` and `sys_path` with one more `-c` call that prints only those two values as JSON.

Over-correction to avoid: do not say "run each query separately" in general terms. The fake matches substrings, so an agent that obeys the general rule but writes `sys.prefix!=sys.base_prefix` or reads `sys.base_prefix` in the prefix call still lands in the wrong branch. The better fix is upstream: make the fake a real interpreter wrapper (exec the real python with patched `sys` values), or have it answer a combined probe.

---

## A2. find-virtualenvs on the same fake (fail in 1, 2, 3, 4, 6, 7; pass in 5)

Tests: `test_env_find_virtualenvs_scans_default_locations` (938-952), `test_env_find_virtualenvs_with_path_finds_immediate_subdirs` (257-276).

### 1. Spec

- checkpoint_6.md:75 `` 1. The directory specified by `--path` (if given) — look for `bin/python` (Unix) or `Scripts/python.exe` (Windows) inside immediate subdirectories. ``
- checkpoint_6.md:77 `` 3. `.venv/` and `venv/` in the current directory and project root. ``
- checkpoint_6.md:79 `` Output: same format as `env list`, but only virtualenvs. ``

### 2. Test and reference

Both tests build the same fake (`is_virtualenv=True`) at `<tmp>/.venv/bin/python` or `<tmp>/envs/a_env/bin/python` and assert only `any(item["executable"] == str(fake) for item in envs)`. Version and `is_virtualenv` are not asserted. Reference sith.py:5238-5268 probes each candidate with the two-call probe and keeps it only if `is_virtualenv` is true (5261).

### 3. What the runs did

Same root cause as A. Runs 1, 2, 4, 6 and min11 0219 return an empty list (`assert False` on the `any`). Runs 3 and 7 crash with `KeyError: 'version'`.

What run 5 did (sith.py:4644-4657 and 4689-4717): `find_virtualenvs` calls `env_record(exe, virtualenv=True)` for every directory that has `bin/python`, without requiring the probe to succeed. `probe_python` returns None on the fake (4600, no `version` key), `venv_config` finds no `pyvenv.cfg`, so the record is `{"executable": <fake>, "version": "", "is_virtualenv": true}`. The test only checks `executable`, so it passes with an empty version. min11 0846 passes the same way (its T95, quoted above, keeps unprobeable candidates "with `version` `""`"). fable-5-1 also passes; I did not open its code.

So run 5 did not read the probe better. It guessed that tests mock the tree and stopped requiring an answer.

### 4. Counts

Both tests: 3 pass, 9 fail, 1 not reached. Passes: fable-5-1 just-solve 20260905T0532, min11 20260908T0846, min12 20260915T0719 (run 5).

### 5. Registry

Same entries as A. Run 5 T102 (Risk 40) and min11 0846 T95 (Risk 35) chose "layout is enough" and pass. Run 4 T116 wrote the same intent but its code drops unprobed candidates, fails. Run 6 T108 and run 7 T95 chose "must answer as a virtualenv" (run 7 with a `pyvenv.cfg` fallback), fail. Run 6 T108 is the reference's actual reading (sith.py:5261), and it still fails, because of the fake.

### 6. Classification

upstream, same defect as A. The three passes are a side effect of a fallback that reports an empty `version`, which contradicts checkpoint_6.md:62. I would not patch the spec toward run 5's behaviour. It passes the test by being less correct than the reference.

### 7. Patch

The A patch fixes these two as well. Over-correction to avoid: "list any directory with `bin/python`" would pass these tests and then disagree with the reference's `is_virtualenv` filter.

---

## B. The type of a namespace attribute completion (fails in 1, 2, 3, 4, 5, 7; passes in 6)

Test: `test_runtime_attribute_completion_from_namespaces` (381-411).

### 1. Spec

- checkpoint_6.md:34 `` For completion, names from both static analysis and namespaces are merged. For namespace-derived results, `description` is exactly `"{type} (runtime)"` and `type` is the namespace type string. ``
- checkpoint_6.md:24 `` | `attributes` | array of string | Optional. Known attributes for classes/modules. | ``

Line 34 is the sentence. It does not say whose type string an attribute carries.

### 2. Test and reference

Namespace `[{"df": {"type": "DataFrame", "module": "pandas", "attributes": ["groupby", "merge", "head"]}}]`, source `result = df.gr|`. Asserts `groupby` is offered, `groupby_item["type"] == "DataFrame"`, `groupby_item["description"] == "DataFrame (runtime)"`. Reference sith.py:1520-1543 (`_runtime_attribute_completions`): `runtime_type = str(data.get("type", "statement"))`, then each attribute gets `type=runtime_type, description=f"{runtime_type} (runtime)"`. The attribute takes its owner's type.

### 3. What the runs printed

Runs 1, 2, 3, 4, 5, 7 and both min11: `AssertionError: assert 'instance' == 'DataFrame'`. All offer `groupby`; all give it `type: "instance"`. Run 6 gives the owner's type and passes.

### 4. Counts

2 pass, 10 fail, 1 not reached. Passes: fable-5 just-solve 20260830T1602 and run 6.

### 5. Registry

Registered in all six registry runs, Risk 45 to 55, and five of six named the hidden reading as the author's likely alternative and still chose against it.

**run 4 (min12 20260915T0053), T122.** Choice `instance`. Missed.

> ## T122. Completion types for a runtime value's `attributes`
>
> ### Spec Text
> > | `attributes` | array of string | Optional. Known attributes for classes/modules. |
>
> ### Alternatives
> 1. Each attribute completes with a neutral type, since the namespace gives names only.
> 2. Each attribute inherits the owner's `type` string (`module`, `class`, ...).
> 3. `attributes` never reaches completion at all.
>
> ### Choice
> Interpretation 1: attribute completions are `{"type": "instance", "description":
> "instance (runtime)"}`, keeping the `"{type} (runtime)"` shape the spec fixes for every
> namespace-derived result.  Listing an attribute as a `module` because its owner is one (2) would
> state something the namespace never claimed, and (3) would leave the field with no effect.  They
> only appear when static analysis resolves the receiver to nothing, as the fallback rule requires.
>
> ### Risk: 55
> Author most likely prefers: possibly the owner's type string echoed onto each attribute, or an
> empty `type`; the field's completion output is the least specified corner of interpreter mode.
>
> ---
**run 5 (min12 20260915T0719), T94.** Choice `instance`. Missed.

> ## T94. Namespace `attributes` in attribute completion, and the type they get
>
> ### Spec Text
> > | `attributes` | array of string | Optional. Known attributes for classes/modules. |
>
> ### Alternatives
> 1. `attributes` feed attribute completion (and `infer`/`goto` on `runtime_name.attr`) when the
>    receiver itself can only be resolved from a namespace. Each attribute has no type of its own, so
>    it is reported as `type: "instance"`, `description: "instance (runtime)"`.
> 2. Same, but attributes are reported with the *owner's* type string, e.g. `module (runtime)`.
> 3. `attributes` are informational only and never produce completions.
>
> ### Choice
> Alternative 1. The field would be pointless if it never surfaced, and attribute completion after a
> runtime-only object is the headline use of a REPL namespace. `instance` is the tool's existing word
> for "a runtime value of some type", and reusing the owner's type would claim, falsely, that
> `numpy.array` is itself a module.
>
> ### Risk: 55
> The author most likely prefers: attributes do produce completions; the exact `type` they carry is the
> coin-flip, with `instance` and the owner's type string the two plausible answers.
>
> ---
**run 6 (min13 20260919T0435), T97.** Choice owner's type. Matched. The only entry that quotes line 34 next to the `attributes` row and reads line 34 as covering attributes.

> ## T97. What type a namespace attribute completes as
>
> ### Spec Text
> > "| `attributes` | array of string | Optional. Known attributes for classes/modules. |"
> > "For namespace-derived results, `description` is exactly `\"{type} (runtime)\"` and
> > `type` is the namespace type string."
>
> ### Alternatives
> 1. An attribute carries the type of the value that owns it: `np.array` completes as
>    `module` with `"module (runtime)"`, because that is the only namespace type string in
>    sight.
> 2. An attribute is an unknown value, so it completes as `instance` with
>    `"instance (runtime)"`.
> 3. Attributes are not completions at all and only matter to `infer`.
>
> ### Choice
> (1). The rule about `{type} (runtime)` is written as covering every namespace-derived
> result, and the file gives no type for an attribute of its own; taking the owner's keeps
> the stated invariant literally true.
>
> ### Risk: 45
> Author most likely prefers: (1) if the description rule was implemented once and reused,
> (2) if attributes were given a record of their own.
>
> ---
**run 7 (min13 20260919T1433), T100.** Choice `instance`. Missed, though it quotes line 34 too.

> ## T100 — The attributes a namespace only names
>
> ### Spec Text
> > | `attributes` | array of string | Optional. Known attributes for classes/modules. |
> > For namespace-derived results, `description` is exactly `"{type} (runtime)"` and `type` is the namespace type string.
>
> ### Alternatives
> 1. An attribute has no type of its own, so it is completed as an instance: `type` of `"instance"` and `description` of `"instance (runtime)"`.
> 2. The attribute inherits the owner's type string, so a module's attributes are described as `"module (runtime)"`.
> 3. Attributes are completed with the plain vocabulary of static completions (`statement`, `instance of ...`), since the "runtime" description rule is written about names, not attributes.
>
> ### Choice
> Alternative 1. The completion vocabulary has no "unknown" kind, and an
> attribute reached through a namespace is as much a runtime result as the name
> that owns it, so it keeps the `"{type} (runtime)"` shape with the only type
> that fits an unclassified value.
>
> ### Risk: 55
> This is the least constrained corner of the spec: the author may equally well
> use the owner's type or an empty description, and any fixture that completes
> after a dot on a namespace object tests it.
>
> ---
**min11 20260908T0219, T102.** Choice `instance`. Missed.

> ## T102 — What `attributes` does, and the `type` of the entries it produces
>
> ### Spec Text
> > `attributes` | array of string | Optional. Known attributes for classes/modules.
>
> ### Alternatives
> 1. Attribute completion on a runtime-only receiver returns one entry per listed
>    attribute; since the file says nothing about their kinds, each is reported as
>    `type` = `instance`, `description` = `"instance (runtime)"`.
> 2. The attributes inherit the owner's `type` string.
> 3. `attributes` is declarative only and never produces completions.
>
> ### Choice
> Alternative 1. The field would be pointless if it produced nothing, and `x.<TAB>` on a
> runtime-only name is exactly the case where "static analysis cannot resolve a symbol".
> `instance` is the tool's existing type for a value of unknown provenance, and it keeps
> the `"{type} (runtime)"` rule self-consistent. `goto` on such an attribute reports the
> same record.
>
> ### Risk: 55
> Author's most likely alternate reading: the attribute entries carry the owner's type
> string (Alternative 2).
>
> ---
**min11 20260908T0846, T98.** Choice `instance`. Missed.

> ## T98. The type of a namespace `attributes` entry
>
> ### Spec Text
> > | `attributes` | array of string | Optional. Known attributes for classes/modules. |
> > For namespace-derived results, `description` is exactly `"{type} (runtime)"` and `type` is the namespace type string.
>
> ### Alternatives
> 1. Attributes complete as `type` `"instance"`, description `"instance (runtime)"` — the attribute's own type is unknown, and `instance` is this tool's word for "some value".
> 2. Attributes inherit the owner's type string (`module (runtime)` for every attribute of a module).
> 3. Attributes are not offered at all; the field is display-only.
>
> ### Choice
> Alternative 1. The rule "`description` is `{type} (runtime)`" needs *a* type for each row, and the only honest one for a bare attribute string is "a value" — `instance`, which is the type this tool already gives to values it can only describe loosely. (2) says visibly wrong things ("`module (runtime)`" about a function), and (3) makes the field pointless.
>
> ### Risk: 55
> An author is at least as likely to have echoed the owner's type string; the description text is what a test would assert.
>
> ---
### 6. Classification

reading. One sentence (line 34), two readings, and the agents saw both. The agents' argument against the hidden reading is sound Python ("`module (runtime)` about a function" is false), which is why they keep choosing `instance`. The hidden reading follows from implementing the description rule once and reusing it.

### 7. Replacement sentence, checkpoint_6.md:34

> For namespace-derived results, including each name listed in an entry's `attributes`, `description` is exactly `"{type} (runtime)"` and `type` is that entry's `type` string.

Shorter alternative, appended to the `attributes` row at line 24:

> Optional. Known attributes for classes/modules. Each completes with its owner's `type`.

Over-correction to avoid: do not say "attributes inherit the owner's record". Agents would then copy `module`, `value` and `full_name` onto attributes, and `infer`/`goto` on `df.groupby` has tests of its own that I did not check.

---

## C. What smart_sys_path adds (fails in 1, 5; brief turned out to be a clear sentence)

Test: `test_setting_smart_sys_path_changes_resolution` (1066-1095).

### 1. Spec

- checkpoint_6.md:115 `` | `smart_sys_path` | bool | true | When true, automatically add the project root and directories containing `__init__.py` to sys.path. | ``

### 2. Test and reference

Files `extras/__init__.py`, `extras/helper.py` (`VALUE = 1`), `main2.py` = `import helper` / `helper.VA|`. With `--setting smart_sys_path=false`, `VALUE` must be absent. With `=true`, `VALUE` must be offered. So `extras/` itself, the directory that contains `__init__.py`, is an import root, and a packaged module imports by its bare name. Reference sith.py:1367-1371: `for init_file in project_root.rglob("__init__.py"): discovered.append(init_file.parent.resolve())`.

### 3. What the runs printed

Runs 1, 5 and both min11: `assert 'VALUE' in []`, stdout `{"completions":[]}` for the `smart_sys_path=true` call. Run 1 (sith.py:777-799) adds the root plus `package_roots_of(CURRENT_FILE...)`, the jedi rule, which does not reach `extras/` from `main2.py`. Run 5 adds the root only. Runs 2, 3, 4, 6, 7 pass. Runs 4, 6 and 7 registered the literal reading (every `__init__.py` directory); I did not open the code of runs 2 and 3.

### 4. Counts

5 pass, 7 fail, 1 not reached. Fails: sonnet-4.6, fable-5, fable-5-1, both min11, run 1, run 5.

### 5. Registry

Registered in all six. The Choice predicts the outcome in all six: literal reading passes (4, 6, 7), root-only fails (5, both min11).

**run 4 (min12 20260915T0053), T118.** Choice literal. Matched.

> ## T118. What `smart_sys_path` auto-detects
>
> ### Spec Text
> > `smart_sys_path` | bool | true | When true, automatically add the project root and directories
> > containing `__init__.py` to sys.path.
>
> ### Alternatives
> 1. Literally: the project root plus every directory below it that contains an `__init__.py`.
> 2. The jedi reading: the project root plus the first ancestor of the analysed file that does
>    *not* contain an `__init__.py` (so a script inside a package can still import its siblings).
>
> ### Choice
> Interpretation 1, which is what the sentence says.  Existing resolution is unaffected because the
> project root is searched first and the extra roots only ever add resolutions that were previously
> impossible; the walk skips dot-directories and `__pycache__` and stops at depth 4 so that a large
> tree cannot turn every command into a filesystem crawl.
>
> ### Risk: 40
> Author most likely prefers: the same literal reading; the risk is concentrated in a fixture where
> a package's inner module must *not* be importable by its bare name.
>
> ---
**run 5 (min12 20260915T0719), T110.** Choice root only. Missed.

> ## T110. What `smart_sys_path` and `added_sys_path` actually change
>
> ### Spec Text
> > | `smart_sys_path` | bool | true | When true, automatically add the project root and directories containing `__init__.py` to sys.path. |
> > - `smart_sys_path=false` disables auto-detected path additions; only explicitly configured paths participate in import resolution.
>
> ### Alternatives
> 1. The auto-detected search path is exactly the project root (what the tool already searches);
>    `added_sys_path` appends further roots after it; `sys_path` replaces it; `smart_sys_path=false`
>    removes it. Modules of the running runtime (`os`, `json`) stay importable regardless, since they
>    are not an "auto-detected path addition".
> 2. Auto-detection also adds every directory in the project that contains an `__init__.py`, making
>    `import submodule` work from inside a package by bare name.
> 3. `smart_sys_path=false` also cuts off the runtime's own modules, leaving only the configured paths.
>
> ### Choice
> Alternative 1. The project root is the tool's established import base, and reading 2 would change how
> *every* existing import resolves (a sibling module inside a package would become importable by its
> bare name), which the spec plainly does not intend to alter here — it is describing a switch, not a
> new resolution rule. Cutting off the standard library (reading 3) would make `smart_sys_path=false`
> useless for any real file.
>
> ### Risk: 40
> The author most likely prefers: the project root as the auto-detected entry (this choice); an
> implementation that literally adds every `__init__.py` directory would differ on imports written as
> bare sibling module names.
>
> ---
**run 6 (min13 20260919T0435), T95.** Choice literal. Matched.

> ## T95. What `smart_sys_path` detects
>
> ### Spec Text
> > "| `smart_sys_path` | bool | true | When true, automatically add the project root and
> > directories containing `__init__.py` to sys.path. |"
>
> ### Alternatives
> 1. The project root, plus every package directory under it, so a module written inside a
>    package is importable by its bare name too.
> 2. The project root only, reading the `__init__.py` clause as describing how the root
>    itself is found rather than what is added.
> 3. The root plus the directories above the file's own package chain, the way a running
>    interpreter would see them.
>
> ### Choice
> (1), which is what the sentence says. The additions come after the root, so a name the
> root explains is still explained by the root. They extend where an import is *resolved*
> only: `import <TAB>` still offers the modules of the project root, since a spec already
> implemented here says the completions of a bare `import` are the top-level ones.
>
> ### Risk: 35
> Author most likely prefers: (1); a fixture that imports `pkg.module` rather than `module`
> cannot tell the readings apart, so the difference only shows on a bare import of a
> packaged module.
>
> ---
**run 7 (min13 20260919T1433), T105.** Choice literal. Matched, while predicting the author would NOT do this.

> ## T105 — What `smart_sys_path` detects
>
> ### Spec Text
> > `smart_sys_path` | bool | true | When true, automatically add the project root and directories containing `__init__.py` to sys.path.
>
> ### Alternatives
> 1. Read literally: the project root, plus every directory of the project that holds an `__init__.py`, so a module inside a package can also be imported by its bare name.
> 2. The jedi-style reading: walk up from the file being analysed while each directory holds an `__init__.py`, and add the first directory that does not, which is the directory a package is imported from.
> 3. Only the project root; the `__init__.py` clause merely explains how packages are recognised.
>
> ### Choice
> Alternative 1. It is what the sentence says, and it agrees with the other two
> readings on the case every test will cover - a module beside the project root
> resolves by default - while also resolving `import helper` for a `helper.py`
> that sits inside a package.
>
> ### Risk: 40
> The author most likely adds the project root and the parent of the topmost
> package only, so `import helper` for `pkg/helper.py` would resolve here and
> not for them.
>
> ---
**min11 20260908T0219, T111.** Choice root only. Missed.

> ## T111 — What `smart_sys_path` auto-detects
>
> ### Spec Text
> > `smart_sys_path` | bool | true | When true, automatically add the project root and directories containing `__init__.py` to sys.path.
>
> ### Alternatives
> 1. Auto-detection means the project root only (which is what this tool has always
>    resolved imports against).
> 2. The project root plus every package directory found under it, so that a module
>    inside a package can be imported by its bare name.
>
> ### Choice
> Alternative 1. Adding package directories as import roots would change the meaning of
> existing, already-specified import resolution (bare `import sibling` from inside a
> package, and the contents of top-level `import <TAB>`), which the new spec gives no
> sign of intending. `smart_sys_path=false` still removes the root, which is the
> behaviour the spec actually pins ("only explicitly configured paths participate").
>
> ### Risk: 40
> Author's most likely alternate reading: package directories are added as well
> (Alternative 2).
>
> ---
**min11 20260908T0846, T104.** Choice root only. Missed.

> ## T104. What `smart_sys_path` actually adds
>
> ### Spec Text
> > | `smart_sys_path` | bool | true | When true, automatically add the project root and directories containing `__init__.py` to sys.path. |
> > `smart_sys_path=false` disables auto-detected path additions; only explicitly configured paths participate in import resolution.
>
> ### Alternatives
> 1. The auto-detected search path is the project root — the search path this tool has always used — and `smart_sys_path=false` removes it, leaving only `sys_path`/`added_sys_path`.
> 2. Also add, per analysed file, the directory above its package chain (jedi's actual "smart" rule), which would newly resolve sibling modules of files that sit in subdirectories of the root.
>
> ### Choice
> Alternative 1. The observable claims the spec makes are the ones about *disabling* it and about `added_sys_path` making "otherwise-unimportable" modules importable; adopting (2) would change the answers of the whole existing import-resolution section (a module in a subdirectory could suddenly import its siblings by bare name) with nothing in the spec asking for it. Directories with `__init__.py` are packages, which the root-based resolver already imports by dotted name.
>
> ### Risk: 30
> An author who literally walks the tree adding every `__init__.py` directory would resolve bare imports of modules nested inside packages.
>
> ---
### 6. Classification

reading. The hidden test takes line 115 at its word. The failing agents talked themselves out of the literal sentence because it is wrong Python (a package directory on `sys.path`) and because it would change earlier checkpoints' import behaviour.

### 7. Replacement sentence, checkpoint_6.md:115

> When true, automatically add the project root and every directory under it that contains an `__init__.py` to sys.path, so a module inside a package also resolves by its bare name (`import helper` finds `pkg/helper.py`).

Over-correction to avoid: do not add "and their parents" or mention jedi. The example in the sentence is enough. Keep "after the project root" out unless you check ordering tests; I did not.

---

## D. Envelope of `env info` (fails in 3, 6; brief)

Test: `test_env_info_default_executable_includes_sys_path` (955-962). Asserts `"sys_path" in payload` at the top level.

Spec: checkpoint_6.md:89 `` Additional field vs `env list`: ``. The spec never names an envelope for any `env` command. The tests want `{"environments": [...]}` for the list commands (line 168, `payload.get("environments", [])`) and a bare record for `env info`. Reference sith.py:5281 writes `json.dumps(info)` flat; 5218 writes `{"environments": entries}`.

Printed: runs 3, 6 and min11 0219 answer `{'environment': {'executable': '/workspace/.venv/bin/python3', 'version': '3.12.14', ..., 'sys_path': [...]}}`. The probe works on the real python, so only the wrapper fails it.

Counts: 9 pass, 3 fail, 1 not reached.

Registry: registered in all six. Run 6 T92 and min11 0219 T98 chose the `environment` wrapper and missed. Run 4 T112, run 7 T91, min11 0846 T93 chose flat and matched. Run 5 T100 emitted both (flat fields plus alias keys) and passed.

**run 6 (min13 20260919T0435), T92.** Choice `{"environment": {...}}`. Missed, and its Risk text says `env info` is where it would miss.

> ## T92. What the new commands wrap their payload in
>
> ### Spec Text
> > "python sith.py env list"
> > "| `executable` | string | Absolute path to the Python executable. |"
> > "Show details about a specific Python environment."
> > "Create or update a project configuration file at `<dir>/.sith/project.json`."
>
> ### Alternatives
> 1. `env list` and `env find-virtualenvs` answer `{"environments": [...]}`, `env info`
>    answers `{"environment": {...}}`, and `project init` answers `{"project": {...}}`.
> 2. `env info` answers a one-element `{"environments": [...]}`, so that "the same format"
>    really is the same shape.
> 3. The records are printed bare, without an envelope key.
>
> ### Choice
> (1). Every existing subcommand answers a single JSON object keyed by what it returns
> (`completions`, `definitions`, `signatures`, `errors`), and the spec names `context` the
> same way, so the envelope is the house style rather than an invention. `env info`
> describes one environment, so its key is singular and its payload an object.
>
> ### Risk: 45
> Author most likely prefers: (1) for the list commands; `env info` is where a different
> key (or a bare object) is most likely, since the spec never names one.
>
> ---
**min11 20260908T0219, T98.** Choice wrapper. Missed, names the bare object as the likely alternative.

> ## T98 — The payload shape of `env info`
>
> ### Spec Text
> > Show details about a specific Python environment. If `<executable>` is omitted, use the system default (`python3`).
> > Additional field vs `env list`: `prefix`, `sys_path`.
>
> ### Alternatives
> 1. `{"environment": {...}}` — one object under a singular wrapper key.
> 2. The environment object printed bare at the top level.
> 3. `{"environments": [ {...} ]}` — a one-element list, identical in shape to `env list`.
>
> ### Choice
> Alternative 1. The command describes a single environment ("Show details about a
> specific Python environment"), so a list would be misleading, and the tool never prints
> an unwrapped payload. "Additional field vs `env list`" describes the record's fields,
> not the envelope.
>
> ### Risk: 50
> Author's most likely alternate reading: the bare object at the top level, since the
> field table reads like the whole document (Alternative 2).
>
> ---
**run 4 (min12 20260915T0053), T112.** Choice flat. Matched.

> ## T112. The JSON envelope of the `env` commands
>
> ### Spec Text
> > ```
> > python sith.py env list
> > ```
> > Find and list available Python installations on the system.
>
> ### Alternatives
> 1. `env list` and `env find-virtualenvs` print `{"environments": [...]}`, matching the one-array
>    envelope every other command uses; `env info` prints the single environment object itself.
> 2. Both list commands print a bare JSON array.
> 3. `env info` is wrapped too, as `{"environment": {...}}`.
>
> ### Choice
> Interpretation 1.  Every existing command prints an object with exactly one key named after the
> thing it returns (`completions`, `definitions`, `signatures`, `results`, `names`, `errors`), so
> `environments` is the name this tool would give the array; a bare array would be the only
> non-object payload in the CLI.  `env info` returns *one* environment and the spec introduces its
> fields as "Additional field vs `env list`", i.e. the same record with two more keys — so the
> record is the payload.
>
> ### Risk: 40
> Author most likely prefers: `{"environments": [...]}` for the lists; `env info` could plausibly
> be wrapped in `{"environment": {...}}` instead of printed bare.
>
> ---
**run 5 (min12 20260915T0719), T100.** Choice both spellings. Passed.

> ## T100. Payload keys of the `env` and `project` subcommands
>
> ### Spec Text
> > ### `env list`
> > ### `env info`
> > ### `project init`
>
> ### Alternatives
> 1. `env list` / `env find-virtualenvs` → `{"environments": [...]}`, `env info` → the fields inline at
>    the top level, `project init` → the config fields inline.
> 2. Singular/plural variants (`{"pythons": ...}`, `{"virtualenvs": ...}`, `{"environment": {...}}`,
>    `{"config": {...}}`).
>
> ### Choice
> Alternative 1 as the primary spelling, with the plausible aliases emitted alongside
> (`virtualenvs` for `find-virtualenvs`, `environment` for `env info`, `config`/`path` for
> `project init`). The tool already ships hedged payloads (`search` emits both `results` and
> `definitions`), so an extra key costs nothing and a caller looking for either spelling finds it.
>
> ### Risk: 35
> The author most likely prefers: `{"environments": [...]}` for both list commands; the risk is a test
> that compares the whole `env info` / `project init` payload for exact equality, which the aliases
> would break.
>
> ### Note
> The `.sith/project.json` file itself is written with exactly the four documented keys (plus any
> unknown keys an existing file already had), since that file's content is specified.
>
> ---
**run 7 (min13 20260919T1433), T91.** Choice flat. Matched.

> ## T91 — The JSON envelope of the `env` answers
>
> ### Spec Text
> > ```
> > python sith.py env list
> > ```
> > Find and list available Python installations on the system.
> > | `executable` | string | Absolute path to the Python executable. |
>
> ### Alternatives
> 1. `env list` and `env find-virtualenvs` write their list under `environments`; `env info` writes the single environment's fields at the top level of the document.
> 2. Every `env` answer nests under a key: `{"environment": {...}}` for `env info`.
> 3. `env find-virtualenvs` uses a key of its own, such as `virtualenvs`.
>
> ### Choice
> Alternative 1. Every other command writes an object holding a named array, so
> the list of environments is named for what it holds; `find-virtualenvs` is
> specified as "same format as `env list`", which reads as the same envelope
> too. `env info` describes one environment, so its own fields are the document.
>
> ### Risk: 30
> An author who reuses one serialiser for all three would nest `env info` under
> a key as well, which moves every field one level down.
>
> ---
**min11 20260908T0846, T93.** Choice flat. Matched.

> ## T93. The JSON envelope of the new commands
>
> ### Spec Text
> > ```
> > python sith.py env list
> > ```
> > Find and list available Python installations on the system.
> > | Field | Type | Description |
> > |-------|------|-------------|
> > | `executable` | string | Absolute path to the Python executable. |
>
> ### Alternatives
> 1. `env list` / `env find-virtualenvs` print `{"environments": [...]}`, `env info` prints the single object's fields at the top level, `project init` prints the resulting config at the top level, and `context` prints `{"context": [...]}`.
> 2. Every command wraps its answer in a key: `{"environment": {...}}` for `env info`, `{"project": {...}}` for `project init`.
> 3. `env list` prints a bare JSON array.
>
> ### Choice
> Alternative 1. Every existing list-shaped command answers with one plural key (`completions`, `definitions`, `signatures`, `references`, `results`, `names`, `errors`), so `environments` is the house style, and the spec itself names the `context` array `context`. The commands that answer with *one* thing (the refactorings) put their fields at the top level of the envelope rather than nesting them, which is why `env info` and `project init` print a flat object.
>
> ### Risk: 45
> An author who wrapped the singular answers would read `data["environment"]["prefix"]`; the flat form is a coin-flip for `env info` in particular.
>
> ---
Classification: taste. The spec states no envelope at all, and the authors assume one: a plural key for lists, a bare object for one record. Every earlier sith command wraps its payload in a named key, which is what pulls agents toward `environment`.

Candidate sentences for checkpoint_6.md. After line 65: `Output: {"environments": [...]}.` After line 94: `` Output: one JSON object with these fields at the top level (the three `env list` fields plus the two above). `` Over-correction to avoid: do not write "no envelope" for the whole section, since the list commands do have one.

---

## E. project init keeps a stored null (fails in 1, 2, 5; brief)

Test: `test_project_init_merges_only_passed_fields` (279-306). Existing file has `"environment_path": null`; the call passes only `--sys-path src/`; asserts `merged["environment_path"] is None`.

Spec: checkpoint_6.md:119 `` If `project.json` already exists, merge the provided flags into the existing config (only overwrite fields that were explicitly passed). `` and :112 `` | `environment_path` | string or null | `""` | ... If null or empty string, use the system default. | ``

Reference sith.py:5311-5314: `raw.get("environment_path", defaults.environment_path)`, so a stored null survives.

Printed: runs 1, 2, 5 and min11 0219: `AssertionError: assert '' is None`. Run 5 sith.py:4827-4828: `env = cfg.get("environment_path", ""); cfg["environment_path"] = env if isinstance(env, str) else ""`. min11 0219 sith.py:338-343 does the same. They tidy null into the default on load, then write it back.

Counts: 7 pass, 5 fail, 1 not reached.

Registry: unregistered everywhere. Closest: run 7 T112 "What an existing configuration keeps" (Choice: keep what is there, passes), run 5 T108 (unreadable `project.json`), min11 0846 T107 (what "merge" means). None mentions null.

Classification: process. Line 112 allows null as a value and line 119 says untouched fields stay. Rewriting null to `""` overwrites a field nobody passed. It is a small agent bug against words the spec has. If you want a nudge anyway, append to line 119: `` A field that was not passed keeps its stored value exactly, including `null`. `` Over-correction to avoid: nothing about validation of the stored file; the reference resets non-list `sys_path` values (5329 on) and I did not check tests for that.

---

## F. full_name of a runtime definition (fails in 2 only; brief)

Test: `test_interpreter_goto_uses_first_namespace_match_wins` (868-908). Namespaces `[{"dup": {"type": "module", "module": "first_mod"}}, {"dup": {"type": "class", "module": "second_mod"}}]`; asserts a definition with `name == "dup"`, `type == "module"`, `full_name == "first_mod.dup"`, and none with `second_mod.dup`.

Spec: checkpoint_6.md:36 fixes `description` and `type` of a namespace-derived definition. Nothing fixes `full_name`. Nearest: :22 `` | `module` | string | Optional. Module the value originates from. | ``. Reference sith.py:1483-1487: `full_name = f"{module_name}.{name}"` when `module` is set, else `name`.

Run 2 (sith.py:3579-3587, `namespace_full_name`): `if ns_type(descriptor) == "module": return module`, so it answers `first_mod`. First-match order is right; only the `full_name` string differs. It is the more sensible answer for a module and the test rejects it.

Counts: 9 pass, 3 fail, 1 not reached (fails: sonnet-4.6, fable-5-1, run 2). I did not open the other two failing runs.

Registry: run 2 has none. The registry runs cover the unstated fields in run 4 T111, run 5 T93, run 6 T99, run 7 T99, min11 0219 T100, min11 0846 T96, and all six pass this test. Not quoted here since none of them missed.

Classification: taste (unstated field rule), and close to noise for opus, since only one of seven runs special-cased modules. Candidate sentence for checkpoint_6.md after line 36: `` Their `full_name` is `"{module}.{key}"` when `module` is given, otherwise the key; `module_path` is `""` and `line`/`column` are 0. `` The second half is a guess from the reference (1492-1494); I did not check which tests assert it.
