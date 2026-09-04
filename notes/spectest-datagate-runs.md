# Spectest run ledger (datagate, Opus 5, Claude Code 2.1.251, thinking high)

Every run under `outputs/spectest/`, what changed, and how it ended. Scores are all hidden
tests passed / total at each checkpoint (regressions included), from each checkpoint's
`evaluation.json`. Per-checkpoint tables: `bin/summarize <run_dir>`.

| version | run dir (under outputs/spectest/) | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 42/50, 111/122, 160/174, 211/233, 249/276, 326/353, 377/405 | complete (dev6 sweep); 28 misses, nothing recovered once missed: 8 at ckpt 1 (v3's six plus two whitespace-preservation tests), rowid trio, 3 whitespace tests at ckpt 3, the 8 charset tests at ckpt 4, `force` variants at ckpt 5, mixed-numeric at ckpt 7 |
| v1 | `opus-5_…_spectest/20260831T1136` | first spec-test prompt | 44/50 | ckpt 1 only |
| v2 | `…spectest-v2/20260831T1519` | testing section tweaks | 44/50 | ckpt 1 only; agent pkill self-match |
| v3 | `…spectest-v3/20260831T1647` | | 44/50, 113/122, 165/174, 216/233, 254/276, 331/353, 382/405 | complete (ckpts 2-7 added 2026-09-02 via `bin/scb-extend`); 23 misses: the 6 from ckpt 1 carried all the way, rowid trio, 8 charset tests at ckpt 4, `force` variants at ckpt 5, one mixed-numeric test at ckpt 7 |
| v4 | `…spectest-v4/20260831T2022` | tester as a sub-agent judged on breadth | 50/50, 119/122 | stopped after ckpt 2; **checkpoint dirs 1-2 deleted 2026-09-02** (see below), scores survive in checkpoint_results.jsonl |
| v4 rerun | `…spectest-v4/20260902T1617` | same v4 prompt, fresh run from ckpt 1 (agent config now has the bg-wait env) | 48/50, 120/122, 172/174, 227/233, 265/276, 342/353, 392/405 | complete; 13 misses: latin-1 autodetect + trailing-empty-line at ckpt 1 carried throughout, 4 spreadsheet invalid-charset tests at ckpt 4, `force` variants at ckpt 5, enrich cache-disabled + force-removes-metadata at ckpt 7. Rowid trio PASSED (only unpatched run to do so). Ckpt 7 cost $89 / 1042 steps: the agent polled a foreground full-suite run with 720 `echo ok` calls |
| v5 | `…spectest-v5/20260831T2310` | AMBIGUITIES.md procedure | 49/50, 66/122, 170/174, 224/233 | rate-limited after ckpt 4; ckpt 2 was a zero-implementation checkpoint (print-mode killed the bg tester) |
| v6 | `…spectest-v6/20260901T0618` | bg-task ceiling env, "at least one test asserts the chosen reading" | 50/50, 119/122 | killed mid-ckpt 3 to fix the turn-ending rule |
| v7 | `…spectest-v7/20260901T0726` | numbered entries, foreground-wait rule | 49/50, 118/122, 170/174, 224/233, 262/276, 339/353, 391/405 | complete; 14 misses, all five spec sentences |
| v8 disambiguated | `…spectest-v8-disambiguated/20260902T0555` | v8 prompt (tester validates tests only) + `problems/datagate-clarified.patch` | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete; first strict solve |
| just-solve-disambiguated | `…just-solve-disambiguated/20260902T2225` | benchmark's own prompt + `problems/datagate-clarified.patch` | 49/50, 121/122, 172/174, 231/233, 274/276, 345/353, 397/405 | complete 2026-09-03; 8 misses, none on a patched sentence: header/time whitespace at ckpt 1, header no-trim at ckpt 3, six trimmed/case-insensitive `cache_enabled` values at ckpt 6. $15 and 55 min for the whole run |
| v8A disambiguated | `…spectest-v8A-disambiguated/20260902T2341` | v8 prompt minus library research and minus the tester sub-agent (`spectest-v8A-no-libs-no-subagent.jinja`) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-03; second strict solve, at $30 and 118 min vs v8-disambiguated's $69 and 295 min; quality means within noise of v8-disambiguated (erosion 0.121 vs 0.120, ast-grep 0.043 vs 0.059) |
| v8B disambiguated | `…spectest-v8B-disambiguated/20260903T0159` | v8 prompt minus library research, tester sub-agent kept (`spectest-v8B-no-libs.jinja`) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 352/353, 403/405 | complete 2026-09-03; 2 misses: whitespace-only CACHE_ENABLED must fail startup (ckpt 5 test, regressed at ckpt 6 when trimming was added) and duplicate enrich params yes-then-no at ckpt 7. $66 and 270 min: the sub-agent doubles cost and time over v8A for a worse score; best quality means of the three (erosion 0.095, ast-grep 0.034) |
| min0 disambiguated | `…spectest-min0-disambiguated/20260903T0756` | just-solve plus one sentence, "Before implementing, write tests from the spec, quoting it" (`spectest-min0-tests-first-handsoff.jinja`) + spec patch | 48/50, 120/122, 169/174, 228/233, 271/276, 348/353, 400/405 | complete 2026-09-03; 5 misses, all whitespace: header/time whitespace and general whitespace at ckpt 1, exact-value match, header no-trim and numeric-like cells at ckpt 3. Held the six `cache_enabled` tests just-solve lost. Two earlier attempts died on API overload |
| min2 disambiguated | `…spectest-min2-disambiguated/20260903T0918` | min1 plus the two "critically" rules: errors only where the spec quotably demands them, never narrow a generator or test (`spectest-min2-strict-errors.jinja`) + spec patch | 42/50, 114/122, 163/174, 219/233, 262/276, 339/353, 390/405 | complete 2026-09-03; 15 misses. One ckpt-1 decision, "no delimiter means non-tabular" (a 400 the spec never asks for), rejects every single-column fixture: latin-1 pair, url ids, negative values, single-column core, and the three CSV charset tests at ckpt 4. Plus the five whitespace tests min0 lost, and one at ckpt 7. The rules bind tests; with no single-column test written, the implementation invented the error anyway |
| min3 disambiguated | `…spectest-min3-disambiguated/20260903T1057` | min2 plus hypothesis tests per phrase and the generator floor (`spectest-min3-hypothesis.jinja`) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 347/353, 399/405 | complete 2026-09-03; strict through ckpt 5, first rung to clear the whitespace and single-column classes. 6 misses, the trimmed/re-cased `CACHE_ENABLED` values: one parser that trims, called with trim=False for `CACHE_ENABLED` alone, keeping ckpt 5's "strict" over ckpt 6's "trimmed" |
| min4 disambiguated | `…spectest-min4-disambiguated/20260903T1328` | min3 plus the AMBIGUITIES.md procedure (`spectest-min4-ambiguities.jinja`, 312 words) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-04; third strict solve, at $43 and 3.5 h. Its registry entry T48 took min3's no-trim reading at ckpt 5, then the annotate-when-resolved step reopened it at ckpt 6 and applied "trimmed" to `CACHE_ENABLED`, the reading min3 never revisited |
| min2b disambiguated | `…spectest-min2b-disambiguated/20260903T1704` | min3 minus the two "critically" rules: tests-first, hypothesis, generator floor, keep spec tests (`spectest-min2b-generator-floor.jinja`, chunks ABCJK) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 347/353, 399/405 | complete 2026-09-04; identical to min3 at every checkpoint, same six trimmed `CACHE_ENABLED` misses. The flipped cell of the 2x2: the generator floor is the correctness rung, the two rules add nothing to the score |
| just-solve-disambiguated, repeat | `…just-solve-disambiguated/20260903T1857` | same config as the first run | 48/50, 120/122, 169/174, 228/233, 271/276, 348/353, 400/405 | complete 2026-09-04; 5 misses, all whitespace (the ckpt-1 pair and the ckpt-3 trio), identical to min0's first run. Against the first just-solve run (397): +3 more whitespace misses, the six `cache_enabled` parsing tests recovered. Noise band on the plain prompt: a handful of whitespace tests, plus one six-test cluster that flips |
| min3 disambiguated, repeat | `…spectest-min3-disambiguated/20260903T2011` | same config as the first min3 run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-04; 0 misses, 7/7 strict, $29, 139 min. Same no-trim reading of `CACHE_ENABLED` at ckpt 5 as the first run (its docstring says "no surrounding whitespace"), but at ckpt 6 it deleted the custom parser and routed the flag through the shared trimming `parse_bool`, where the first run kept a `trim=False` exception. The six-test cluster flips between runs on the same prompt |
| min0 disambiguated, repeat | `…spectest-min0-disambiguated/20260903T2251` | same config as the first min0 run | 48/50, 120/122, 169/174, 215/233, 258/276, 335/353, 386/405 | complete 2026-09-04; 19 misses, 0/7 strict, $25, 93 min. The first run's five whitespace tests, identical. Plus 14 upload tests from one keep-alive bug: at ckpt 4 the agent wrote its own HTTP server and multipart parser (the first run used Flask) and cached the request body on the handler object, which the stdlib server reuses for every request on a connection, so each POST after the first read a stale body. 13 at ckpt 4 carried as regressions, one more at ckpt 7 |
| min4-ABCHJK | `…min4-ABCHJK-disambiguated/20260904T0042` | min2b plus H alone, "annotate the entry instead of removing it" (`min4-ABCHJK.jinja`, 157 words) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-04; 0 misses, 7/7 strict, $30, 129 min. The one sentence made the agent keep a 74-entry AMBIGUITIES.md nobody asked for; its A69 took the no-trim reading of `CACHE_ENABLED` at ckpt 5 and was annotated RESOLVED at ckpt 6, whitespace now stripped. Quality: cloned 0.246 and verbosity 0.349 from `test_zz_stress_tmp.py`, a 1319-line copy of the filtering tests with max_examples 4000, left behind at ckpt 3 |
| min4-ABCFGHJK | `…min4-ABCFGHJK-disambiguated/20260904T0311` | min2b plus F, G, H: choose an interpretation, record it in AMBIGUITIES.md, annotate when resolved (`min4-ABCFGHJK.jinja`, 245 words) + spec patch | 44/50, 116/122, 168/174, 224/233, 267/276, 344/353, 394/405 | complete 2026-09-04; 11 misses, 0/7 strict, $31, 128 min. All eleven from one ckpt-1 choice, registry entry T6: a file with no inferable delimiter is "non-tabular", a 400 the spec never asks for, and the entry says in so many words that a genuinely single-column CSV is rejected. min2's cascade test for test (six at ckpt 1, the three CSV charset tests at ckpt 4) plus two single-column tests at ckpt 7. The cache flag entry was annotated and trimmed at ckpt 6 as in min4 |

On hidden tests, v4 through v7 are flat within
the latin-1 noise (ckpt 1: 50, 49, 50, 49 of 50; ckpt 2: 119, cut, 119, 118 of 122), and
every miss is the rowid trio or the latin-1 test. The prompt iterations bought process
reliability and registry quality, not score; the ceiling was the spec. Continuing v4 or
v6 would be comparable (the process bugs decide whether a checkpoint finishes, not what
the agent decides, and a cut checkpoint is visible in the artifacts), but is expected to
reproduce v7's 14 misses at ~$65. If the flat line must be drawn from data, continue v4
only, after adding `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS: "0"` to the run dir's saved
config so the v5 zero-implementation failure cannot recur.

## Test failure summaries

### just-solve

Test failures:

  - Eight at checkpoint 1: v3's six plus two whitespace-preservation tests.
  - The rowid trio at checkpoint 2.
  - Three whitespace tests at checkpoint 3: exact value match, header no-trim, and numeric-looking cells in
    string filters.
  - The same eight charset tests at checkpoint 4 that v3 lost.
  - The five force variants at checkpoint 5.
  - Nothing at checkpoint 6, and the mixed-numeric column test at checkpoint 7.

  Set against v3's 23, the spec-test prompt bought back only the five whitespace tests, two at checkpoint 1
  and three at checkpoint 3. Everything else in the control's miss list is also in v3's. And the four things
  v7 recovered beyond that, the extra checkpoint 1 tests and the checkpoint 4 charset block, came later in
  the prompt series, which is what the fresh v4 run should now locate.

### v3

Two iso solves and four core solves, no strict solve.
Cost as reported by Claude Code was $40.92 for the seven checkpoints, and the six added today took under three hours of wall time.

Where the 23 misses come from:

  - Six checkpoint 1 tests carried the whole way: the latin-1 pair, single-column CSV, URL-derived ids, and
    negative values.
  - The rowid trio at checkpoint 2.
  - Eight charset tests at checkpoint 4 for upload, convert, spreadsheet, and export.
  - The five force variants at checkpoint 5.
  - One mixed-numeric column type test at checkpoint 7.

Against v7's 14 misses, v3 loses nine more, and all nine are in the first four checkpoints: four extra at
checkpoint 1 and the eight charset tests at checkpoint 4, minus overlaps with v7's own set. Checkpoints 3,
5, 6, and 7 track v7 exactly on their own tests. So for the talk, v3 is not flat with v4 through v7. It
sits below them, and the gap is concentrated in charset handling.


### v4 rerun (unpatched spec)

392/405, three iso solves, all seven core solves. $170 as reported by Claude Code, half of
it in checkpoint 7 (1042 steps: the agent polled a foreground test run with 720 `echo ok`
calls, the v7 turn-ending rule biting).

  - Two at checkpoint 1, carried throughout: latin-1 autodetect and the trailing empty line.
  - Nothing at checkpoints 2 and 3. The rowid trio passed, the only unpatched run to do so.
  - Four at checkpoint 4: invalid `charset` on a spreadsheet upload or convert must be ignored,
    for `.xls` and `.xlsx`. The CSV half of the charset block passed.
  - The five `force` variants at checkpoint 5.
  - Nothing at checkpoint 6. Two at checkpoint 7: enrich with cache disabled, and force
    removing metadata.

One better than v7's 391. The v4 prompt sits on the same plateau as v7; the v5 to v7
machinery did not move the score.

### just-solve-disambiguated (patched spec), two runs

First run 397/405, repeat 400/405. $15 and $18, under an hour each. All five patched
sentences held in both runs: latin-1, rowid, both charset blocks, `force`.

  - First run: header/time whitespace at checkpoint 1; header no-trim at checkpoint 3; six
    trimmed and re-cased `cache_enabled` values at checkpoint 6.
  - Repeat: the whitespace pair at checkpoint 1; the whitespace trio at checkpoint 3;
    nothing else. The `cache_enabled` cluster held.

The patch alone recovers 20 of the control's 28 misses. What is left is whitespace
handling and one lenient-parsing cluster that flips between runs. Erosion 0.535 then
0.306 with the same prompt, which is the noise scale for quality comparisons.

### v8A (no libraries, no tester sub-agent; patched spec)

405/405, every checkpoint strict. $30 and 118 minutes against v8's $69 and 295. Erosion
0.121 against v8's 0.120. Dropping library research and the sub-agent lost nothing on
score or quality and cut cost and time by more than half.

### v8B (no libraries, sub-agent kept; patched spec)

403/405, strict through checkpoint 5. $66 and 270 minutes: the sub-agent is the expensive
half of v8.

  - A checkpoint 5 test regressed at checkpoint 6: whitespace-only `CACHE_ENABLED` must fail
    startup. The agent trimmed, got an empty token, and folded it into its T72 choice that
    an empty value means unset.
  - One at checkpoint 7: duplicate `enrich` given as yes then no must keep enrichment off.
    Registry entry T104 declared the mixed case unresolved and asserted both branches; the
    implementation fell through to Werkzeug's first-occurrence lookup.

Both on unpatched sentences. Full compilation with registry entries and a judge pass in
`v8B-disambiguated-misses.md`; patch candidates in `problems/datagate-clarified-2.patch`
and `configs/prompts/v8-choice-must-decide.patch`, both unapplied.

### The min ladder (patched spec)

Per-run rows are in the table; the section at the end has the comparison table, the miss
matrix, and the reading. Failure sets in brief:

  - min0 (400): the whitespace pair at checkpoint 1 and the trio at checkpoint 3. Identical
    to the just-solve repeat.
  - min2 (390): fifteen. Nine from one checkpoint 1 decision, "no delimiter means
    non-tabular", a 400 the spec never asks for, which rejects every single-column fixture:
    the latin-1 pair, url ids, negative values, the single-column core test, and the three
    CSV charset tests at checkpoint 4. Plus min0's five whitespace tests and the
    mixed-numeric test at checkpoint 7.
  - min3 (399): strict through checkpoint 5. Six at checkpoint 6, the trimmed `CACHE_ENABLED`
    values: one parser that trims, called with `trim=False` for `CACHE_ENABLED` alone,
    keeping checkpoint 5's "strict" over checkpoint 6's "trimmed".
  - min2b (399): identical to min3 at every checkpoint, same six.
  - min4 (405): strict. Same no-trim reading as min3 at checkpoint 5 (registry entry T48),
    reopened by the annotate-when-resolved step at checkpoint 6.
  - min3 repeat (405): strict. Same no-trim reading at checkpoint 5; at checkpoint 6 the
    agent folded `CACHE_ENABLED` into the shared trimming parser instead of keeping an
    exception for it. On this prompt the cluster is a coin flip.
  - min0 repeat (386): the same five whitespace tests as the first run, plus fourteen
    upload tests from one bug. At checkpoint 4 the agent replaced Flask with its own
    `http.server` handler and multipart parser, and cached the request body on the handler
    object. The stdlib server keeps one handler per keep-alive connection, so every POST
    after the first on a connection parsed the previous body against its own boundary
    ("no boundary delimiter found"), and the unread body leaked into the next request line
    (a 501 for method `garbagePOST`). Never noticed; its own tests open a fresh connection.
  - min4-ABCHJK (405): strict. Same no-trim reading at checkpoint 5, recorded as registry
    entry A69 in an AMBIGUITIES.md the prompt never asks for; the "annotate the entry"
    sentence implied one. At checkpoint 6 A69 was annotated RESOLVED and the parser strips.
    No test misses; the quality miss is a stray 1319-line stress copy of the filtering
    tests (`test_zz_stress_tmp.py`, max_examples 4000) that survives from checkpoint 3.
  - min4-ABCFGHJK (394): min2's single-column cascade, nine by checkpoint 4 and two more at
    checkpoint 7 (mixed numeric column type, duplicate enrich params), every one a 400 for
    "source is not tabular content". Registry entry T6 weighed three readings and chose
    the strictest knowing the cost. The cache flag fork closed at checkpoint 6 as in min4.

## Did the v8 testing hints help, or was it the zombie fix?

Both, and they are separable in the transcripts. Minutes the tester sub-agent spent
running or polling pytest, and the parent likewise, from `agent/stdout.jsonl`:

| ckpt | v7 tester | v8-d tester | v7 parent | v8-d parent | v7 wall | v8-d wall |
|---|---|---|---|---|---|---|
| 1 | 3.5 | 1.7 | 10.0 | 11.3 | 41 | 36 |
| 2 | 6.3 | 1.1 | 5.0 | 2.6 | 25 | 24 |
| 3 | 13.7 | 1.0 | 10.4 | 4.3 | 55 | 28 |
| 4 | 16.3 | 3.4 | 13.8 | 4.2 | 66 | 39 |
| 5 | | 1.5 | | 3.3 | 66 | 87 (65-min laptop suspend inside) |
| 6 | | 3.4 | | 8.8 | 179 (1 h waiting on a zombie) | 43 |
| 7 | | 2.5 | | 14.9 | 57 | 38 |

The tester line is the prompt: tester test-running time fell four to ten fold at
checkpoints 3 and 4 with nothing else different at that stage. The checkpoint 6 outlier is
the harness: v7's parent waited an hour on `tail --pid` of a zombie pytest, which the
container init fix removes. A clean split would be one run of the v7 prompt on the
disambiguated spec under the patched harness (`spectest-v7-disambiguated`).

## Experiments worth running soon, with what each isolates

Next:
- **The method on a second problem.** The reusable thing is registry → blind judge → patch
  the sentences the model reads one way and the tests the other, not the datagate patch
  itself. xjq is the obvious candidate, as a matched difficulty of "Easy"

Soon:
- **v8-disambiguated, second run.** Run-to-run noise: the latin-1 test has flipped between
  runs before. Needed before leaning on "strict" in public.
- **Stop encouraging libraries** Now that tests are passing, we could do a v9.
  In this version we would remove any special encouragement to use libraries at implementation time.
  Then we could see the impact on the code quality metrics and see if the spec change is worth the tokens.

In a later phase:
- **v7 prompt on the disambiguated spec.** Isolates the v8 prompt's effect on time and cost.
- **Spec lint.** The judge already answers "which sentences does this model read
  differently from its own tester?" for any spec before implementation. Sentences where
  votes split or where the tester's choice is unanimous-but-untested are the lint output.

## Harness patches that exist (all in `patches/`, all applied in the checkout)

stream-parser string message; stop-after-checkpoint; agent death detection + prompt
context variables; resume invalidates infra-failed checkpoints; container init + timeout
kills inside the container; retry keeps every attempt's transcript (added 2026-09-04:
the min4-ABCHJK ckpt-1 agent pkill-self-matched, the `--continue` retry's stdout replaced
the first attempt's, and only the copied Claude session file under
`agent/workspace/projects/` still had the whole conversation). One known bug not yet
patched: `retry()` resets the usage tracker, so a checkpoint that timed out and continued
under-reports its cost (v7 ckpt 6 recorded $3 of roughly $15). Candidates for upstream
PRs, along with documenting `SCBENCH_PROBLEMS_PATH` for running against a modified
problem copy.

Quality scoring, checked 2026-09-04: `scb-check` 0.1.3 runs on the whole snapshot,
tests included (datagate: one source module, conftest, and eight test files). Its
`exclude` list comes from a `scb-check.toml` or `pyproject.toml` found by walking up
from the harness's working directory, not the snapshot's, so nothing the agent writes
into the workspace changes what gets scored, and neither would a prompt rule about
ruff's exclude. Skipping tests would take a config at this repo's root and would apply
to every run scored here, control included.

## v4 lost its checkpoints 1 and 2 (2026-09-02 20:56Z)

A `scb run --resume` on the v4 run dir deleted `checkpoint_1` and `checkpoint_2` before
running anything. Cause: the Ctrl-C'd resume on 2026-09-01 05:23 rewrote `run_info.yaml`
with every checkpoint it had not itself run marked `skipped`; the next resume trusts those
states, invalidates the checkpoints, and `rmtree`s their directories. What survives: the
two rows in the run dir's `checkpoint_results.jsonl` (scores, tokens, cost, code metrics),
`result.json`, and the aborted checkpoint 3 workspace (code after checkpoint 2 plus partial
checkpoint 3 work) in `outputs/aborted/spectest-v4-20260831T2022-checkpoint_3`. Agent
transcripts, snapshots, per-test evaluations and diffs for checkpoints 1-2 are gone from
the mount. `bin/scb-extend` now repairs `run_info.yaml` before every resume, and v3's
checkpoint 1 was tarred to `outputs/backups/` before its extension started.

## Minimal-prompt ladder on the patched spec (2026-09-03, first runs)

Rungs are `configs/prompts/spectest-min*.jinja`, each adding one rule set to the one below
(`spectest-min-ladder-changes.md`); every run is against `problems/datagate-clarified.patch`.
Table and matrix from `bin/compare-runs`. Repeats and min2b are in the
amendments below; as of 2026-09-04 13:00Z the queue holds reruns of every one-run 405
(ABCHJK, min4, v8A, v8) plus v8B, then three single-chunk drops from ABCHJK: ABCHK (no J),
ACHJK (no B), ABCHJ (no K, to price that rule).

run | scores | strict | cc_$ | erosion | verbosity | ast% | cloned%
---|---|---|---|---|---|---|---
just-solve | 49/50 121/122 172/174 231/233 274/276 345/353 397/405 | 0/7 | 15.33 | 0.535 | 0.244 | 0.176 | 0.067
min0 | 48/50 120/122 169/174 228/233 271/276 348/353 400/405 | 0/7 | 18.02 | 0.236 | 0.200 | 0.102 | 0.080
min2 | 42/50 114/122 163/174 219/233 262/276 339/353 390/405 | 0/7 | 22.19 | 0.048 | 0.174 | 0.068 | 0.098
min3 | 50/50 122/122 174/174 233/233 276/276 347/353 399/405 | 5/7 | 33.98 | 0.151 | 0.160 | 0.062 | 0.065
min4 | 50/50 122/122 174/174 233/233 276/276 353/353 405/405 | 7/7 | 43.46 | 0.167 | 0.157 | 0.080 | 0.068
v8A | 50/50 122/122 174/174 233/233 276/276 353/353 405/405 | 7/7 | 29.52 | 0.121 | 0.157 | 0.043 | 0.073

ckpt | test | 1 | 2 | 3 | 4 | 5 | 6
---|---|---|---|---|---|---|---
1 | TestCore::test_autodetect_latin1 | . | . | x | . | . | .
1 | TestCore::test_charset_latin1 | . | . | x | . | . | .
1 | TestCore::test_single_column_csv | . | . | x | . | . | .
1 | TestFunctionality::test_different_urls_different_ids | . | . | x | . | . | .
1 | TestFunctionality::test_id_from_url_not_charset | . | . | x | . | . | .
1 | TestFunctionality::test_negative_values_as_numbers | . | . | x | . | . | .
1 | TestFunctionality::test_preserves_header_and_time_whitespace | x | x | x | . | . | .
1 | TestFunctionality::test_preserves_whitespace | . | x | x | . | . | .
3 | TestFunctionality::test_exact_whitespace_value_match | . | x | x | . | . | .
3 | TestFunctionality::test_header_no_trim | x | x | x | . | . | .
3 | TestFunctionality::test_numeric_like_cells_preserve_whitespace_for_string_filters | . | x | x | . | . | .
4 | TestCore::test_convert_csv_charset_honored | . | . | x | . | . | .
4 | TestCore::test_upload_csv_charset_honored | . | . | x | . | . | .
4 | TestFunctionality::test_export_charset_upload | . | . | x | . | . | .
6 | TestFunctionality::test_trimmed_cache_enabled_false_values[ FALSE ] | x | . | . | x | . | .
6 | TestFunctionality::test_trimmed_cache_enabled_false_values[ No ] | x | . | . | x | . | .
6 | TestFunctionality::test_trimmed_cache_enabled_false_values[ OfF ] | x | . | . | x | . | .
6 | TestFunctionality::test_trimmed_cache_enabled_true_values[ On ] | x | . | . | x | . | .
6 | TestFunctionality::test_trimmed_cache_enabled_true_values[ TRUE ] | x | . | . | x | . | .
6 | TestFunctionality::test_trimmed_cache_enabled_true_values[ YeS ] | x | . | . | x | . | .
7 | TestFunctionality::test_mixed_numeric_column_type | . | . | x | . | . | .

1: just-solve
2: min0
3: min2
4: min3
5: min4
6: v8A

Words per prompt: just-solve 60, min0 71, min2 160, min3 190, min4 312, v8A 690.

What one run of each says, to be checked against the repeats:

- **Strict minimum: min4.** The AMBIGUITIES.md procedure is the first rung with all seven
  checkpoints strict. min3, one rule set below it, lost only the six trimmed
  `CACHE_ENABLED` values at checkpoint 6. Both took the same no-trim reading of "strict"
  at checkpoint 5; min4's registry entry T48 was reopened by the annotate-when-resolved
  step at checkpoint 6 and applied "trimmed" to `CACHE_ENABLED`, while min3's reading
  lived only as a `trim=False` argument that nothing asked it to revisit.
- **Quality minimum: min2.** Erosion 0.048 is the lowest of any datagate run, and every
  rung from min2 up is far below just-solve's 0.535. Code quality arrived two rungs before
  correctness did; the two "critically" rules moved it more than anything above them.
- **The generator floor is the correctness rung.** min3 is the first rung with no
  whitespace or single-column misses, the two classes every lower rung lost.
- **min2 is a warning about rules without reach.** Its nine-test cluster came from one
  checkpoint 1 decision, "no delimiter means non-tabular", a 400 the spec never asks for.
  The error-strictness and never-narrow rules bind tests, and no test reached a
  single-column file, so the implementation invented the error unhindered.
- **min4 is not v8A.** Same score, but $43 against $30, three and a half hours against
  two, and worse erosion and ast-grep. The 380 words v8A carries beyond min4 buy
  efficiency and code shape, not tests.
- **Every miss on the ladder is one of three things:** whitespace preservation (rows for
  checkpoints 1 and 3), the single-column rejection cascade (min2 only), or the
  `CACHE_ENABLED` trimming boundary between checkpoints 5 and 6. None is on a patched
  sentence.

Amendment 2026-09-04 02:00Z, after min2b (ABCJK, the floor without the two rules):
399/405 with the same six misses as min3, checkpoint for checkpoint, at $24 and 93 min.
So the 2x2 is settled on the score axis: the generator floor is the correctness rung and
the two "critically" rules add nothing to the score. The quality axis is not what the
first reading said: min2b's erosion is 0.034, below min2's 0.048 and far below min3's
0.151, with no error-strictness or never-narrow rule in the prompt. Erosion on the ladder
is min0 0.236, min2 0.048, min2b 0.034, min3 0.151, min4 0.167, v8A 0.121; it does not
move monotonically with any rule, and the two lowest values come from the two shortest
rule sets above min0. Treat erosion differences among the rungs as run-to-run noise until
the repeats say otherwise; the one solid quality claim is the gap between just-solve
(0.535) and every tests-first rung (0.03 to 0.24).

Amendment 2026-09-04 06:00Z, after the min3 repeat: 405/405, 7/7 strict, $29, 139 min
(the first run: 399, 5/7, $34). Both runs read "strict case-insensitive" as no-whitespace
at checkpoint 5, with a lowercase-and-compare parser that never strips. Both then met
"trimmed" at checkpoint 6 with that parser to reconcile. The first kept the old reading for
`CACHE_ENABLED` alone through a `trim=False` argument; the repeat deleted the custom parser
and reused the shared one that trims. Nothing in the prompt decides between those, so the
six-test cluster is a coin flip on min3, and one run each no longer separates min4 from
min3 on the score axis. Strict minimum is now "min3 or min4"; a min4 repeat or the chunk
subsets in the queue have to settle it. Quality on the repeat: erosion 0.162 against
0.151, verbosity 0.164 against 0.160, ast-grep 0.090 against 0.062, cloned 0.067 against
0.065. Same-prompt erosion noise is about 0.01 here, against 0.23 on just-solve.

Amendment 2026-09-04 07:50Z, after the min0 repeat: 386/405, 0/7 strict, $25, 93 min
(the first run: 400, $18). The five whitespace misses are the same tests at the same
checkpoints, the third run in a row with exactly that set (both min0 runs and the
just-solve repeat), so trim-everything is the settled reading on the short prompts, not
noise. The other fourteen are a fourth miss class: the agent building infrastructure
itself and getting it wrong. At checkpoint 4 it dropped Flask for a hand-written
`http.server` handler and multipart parser, and cached the request body on the handler,
which the stdlib server reuses across a keep-alive connection. Thirteen upload tests
failed there and one more at checkpoint 7, all with the same stale-body message. The
first run used werkzeug's form parser and never had the problem. Two things follow. The
"every miss is one of three things" reading above is retired; a prompt with no rule
about libraries leaves the library choice to chance, and here that choice cost fourteen
tests, more than every whitespace rule on the ladder put together. And the
min0 rung now reads 386 or 400 on one run each, which is a wider band than any two runs
of a tests-first prompt. Quality on the repeat: erosion 0.172 against 0.236, verbosity
0.212 against 0.200, ast-grep 0.120 against 0.102, cloned 0.092 against 0.080.

Amendment 2026-09-04 10:20Z, after min4-ABCHJK (min2b plus the one "annotate the entry
instead of removing it" sentence, 157 words): 405/405, 7/7 strict, $30, 129 min. min4 was
$43 and three and a half hours for the same score. The sentence did the work on its own.
With no registry rule in the prompt, the agent still kept a 74-entry AMBIGUITIES.md,
because "the entry" has to refer to something. Entry A69 took the usual no-trim reading of
"strict" at checkpoint 5, and at checkpoint 6 the agent annotated it RESOLVED against the
new "(case-insensitive, trimmed)" sentence and made the parser strip. That is the same
reopening min4's full procedure produced, from one rule instead of four. So the strict
minimum on the ladder is now this rung, one run each: the generator floor closes the
whitespace classes and the annotate sentence closes the cache flag fork that min3 flips
on. The rung has a quality problem of its own kind. Cloned 0.246 and verbosity 0.349
against 0.05 to 0.09 and 0.12 to 0.17 everywhere else, all from `test_zz_stress_tmp.py`,
a copy of the 1319-line filtering test file with `max_examples` raised from 25 to 4000,
made at checkpoint 3 for a stress pass and never deleted. Erosion 0.131 and ast-grep 0.105
are in the usual band. Job 4 (ABCFGHJK, the choose and registry rules added back) is the
control for whether asking for the registry buys anything the implied one does not.

Amendment 2026-09-04 12:45Z, after min4-ABCFGHJK (min2b plus choose, registry and
annotate; 245 words): 394/405, 0/7 strict, $31, 128 min. Every miss is min2's
single-column cascade: six at checkpoint 1, the three CSV charset tests at checkpoint 4,
and two more single-column fixtures at checkpoint 7. Registry entry T6 lists three
readings of "non-tabular content", picks "require evidence of a delimited table", and
states the cost: a genuinely single-column CSV is rejected. Three registry runs
deliberated that same question. min4 listed "require at least two columns" and rejected
it; ABCHJK wrote that a single-column file is tabular; this run chose the 400. min2 made
the same wrong call with no registry. So choose-and-record does not cause the cascade and
does not prevent it; it makes a coin flip legible that the spec's own "delimiter must be
inferred from input" leaves open. The cache flag fork did close at checkpoint 6, the third
run in a row where the annotate sentence reopened the no-trim entry. Quality is the best
on the ladder: erosion 0.057, verbosity 0.171, ast-grep 0.068, cloned 0.100.

Where the chunk search stands after four runs: ABCHJK (157 words) is the strict minimum
on one run, min3 flips the cache flag cluster, and the single-column reading is a coin
flip on every prompt without a rule that reaches it. The two runs that took the 400
both had D absent (min2 has D; so D is not the fix either). A spec sentence would close
it: `problems/datagate-clarified-2.patch` style, one line saying a single-column file is
tabular. Prompt-side, nothing on the ladder names the case, and a rule that does would
be datagate-specific.
