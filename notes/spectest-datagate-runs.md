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
| min4-ABCHJK, repeat | `…min4-ABCHJK-disambiguated/20260904T0608` | same config as the first ABCHJK run | 49/50, 121/122, 173/174, 232/233, 275/276, 352/353, 404/405 | complete 2026-09-04; 1 miss, 0/7 strict, $32, 191 min. A trailing blank line kept as a data row of empty strings, chosen at ckpt 1 (registry entry A11: "no source line silently lost") and never revisited; the first run dropped it "matching normal CSV trailing-newline behaviour". Cache flag annotated and trimmed at ckpt 6 as in every run with H. No stray stress file this time: erosion 0.076, verbosity 0.133, ast 0.044, cloned 0.075 |
| min4 disambiguated, repeat | `…spectest-min4-disambiguated/20260904T0939` | same config as the first min4 run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-05; 0 misses, 7/7 strict, $50, 492 min of which about 180 were the host laptop suspended mid-ckpt 2. Registry entry T48 (same number as the first run) took the no-trim reading at ckpt 5 and was marked Superseded at ckpt 6. The first prompt on the ladder to strict-solve twice. Quality better than the first run: erosion 0.076 against 0.167, ast 0.048 against 0.080 |
| v8A disambiguated, repeat | `…spectest-v8A-disambiguated/20260904T1814` | same config as the first v8A run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-05; 0 misses, 7/7 strict, $37, 136 min. Second twice-strict prompt after min4, at 690 words. Cache flag fork closed at ckpt 6. Quality: erosion 0.088 against 0.121, verbosity 0.129 against 0.157 |
| v8B disambiguated, repeat (killed) | `…spectest-v8B-disambiguated/20260904T2053` | same config as the first v8B run | 50/50, 122/122, 174/174, 233/233, 276/276 | stopped 2026-09-05 06:30Z at the user's request during checkpoint 6, strict through 5 as the first run was; left partial, not a completed run |
| v8 disambiguated, repeat (killed) | `…spectest-v8-disambiguated/20260904T2327` | same config as the first v8 run | (none) | stopped 2026-09-05 07:00Z at the user's request during checkpoint 1, with `bin/queue kill`; no checkpoint completed |
| v9 disambiguated | `…spectest-v9-disambiguated/20260904T2335` | v8A plus a Differs score in every registry entry (`spectest-v9.jinja`, 735 words) + spec patch | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-05; 0 misses, 7/7 strict, $32, 111 min. 96 registry entries, every one scored; Differs spread 0 to 45 with 29 at 25 or above, the single-column question at 45 (chose accept, named the 400 as the author's likely reading) and the cache flag at 30 with the author's `.strip().lower()` written out one checkpoint before the spec said "trimmed". Quality: erosion 0.119, verbosity 0.172, ast 0.079, cloned 0.088 |
| v9 disambiguated, repeat | `…spectest-v9-disambiguated/20260905T0804` | same config as the first v9 run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 404/405 | complete 2026-09-05; 1 miss, 6/7 strict, $32, 102 min. `test_duplicate_enrich_params_do_not_enable_metadata[yes-then-no]`, the v8B miss: first value wins, so `enrich=yes&enrich=no` enables enrichment. Registry entry T94 chose that reading, scored it Differs 20 and named the exact failing case as the residual risk ("a getlist-based author would keep enrichment off"). 110 entries all scored, 0 to 45; 20 is the median, 64 entries at or above it. Quality: erosion 0.103, verbosity 0.142, ast 0.072, cloned 0.062 |
| v9 disambiguated, Fable 5.1 | `…fable-5-1_2.1.251_high_spectest-v9-disambiguated/20260905T1055` | v9 prompt on spec v1 with model fable-5-1 and the Fable agent config | 44/50, 116/122, 168/174, 224/233, 267/276, 344/353, 394/405 | complete 2026-09-05; 11 misses, 0/7 strict, $13, 139 min. The single-column cascade, test for test the same eleven as ABCFGHJK: entry T5 chose the 400 on the Sniffer argument and scored it Differs 30, naming the accepted single-column file as the risk. Cache flag closed at ckpt 6. 67 registry entries all scored, 0 to 50. Quality: erosion 0.158, verbosity 0.188, ast 0.070, cloned 0.104 |
| v9 on spec v2 | `…spectest-v9-specv2/20260905T1336` | v9 prompt on spec v2 (v1 plus "a single, exact `enrich=yes`" and "Delimiter ... if present") | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-05; 0 misses, 7/7 strict, $40, 118 min. First run on v2. Registry entry T92 on the enrich sentence: "a single is what excludes the repeat", Differs 12 (the v1 runs put this question at 20 and 30); the delimiter entry T14 "handles the one-column case the spec never excludes". 98 entries all scored. Quality: erosion 0.175, verbosity 0.138, ast 0.062, cloned 0.070 |
| v9 on spec v2, repeat | `…spectest-v9-specv2/20260905T1556` | same config as the first v2 run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $46, 140 min. v9 on v2 is twice strict. Enrich entry T94 at Differs 10. 102 entries all scored. Quality better than the first v2 run: erosion 0.098 against 0.175, ast 0.045 against 0.062, cloned 0.055 against 0.070 |
| min9-ABDEFHJKMNOPR on v2 | `…min9-ABDEFHJKMNOPR-specv2/20260905T1837` | v9 minus the test-writing extras (C, G, I, Q) and minus assert-the-choice (L) and implementation-time entries (S): min4's rules in v9 form plus pkill and pipe hygiene, the tester-speed pair and the Differs procedure (558 words), spec v2 | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $29, 101 min. Cheaper and faster than both v9 runs on v2 ($40, $46). 98 registry entries. Quality: erosion 0.133, verbosity 0.163, ast 0.077, cloned 0.056. Repeat queued |
| min9-ABCDEFGHIJKMNOPQR on v2 | `…min9-ABCDEFGHIJKMNOPQR-specv2/20260905T2039` | v9 minus assert-the-choice (L) and implementation-time entries (S), 690 words, spec v2 | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $35, 140 min. The middle rung of the v9 ladder, strict like the lean rung below it and v9 above it. Quality: erosion 0.064, verbosity 0.151, ast 0.060, cloned 0.063 |
| min9-DEFJKOP on v2 | `…min9-DEFJKOP-specv2/20260905T2323` | ABCHJK's rules in v9 form plus the full registry procedure with Differs (tests per phrase, hypothesis, generator floor, choose and record, annotate, code until pass, keep spec tests; 391 words), spec v2 | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $22, 131 min. The cheapest strict run on any spec. 93 registry entries. Quality: erosion 0.048, verbosity 0.140, ast 0.074, cloned 0.061. Repeat queued as job 34 |
| min9-ABDEFHJKMNOPR on v2, repeat | `…min9-ABDEFHJKMNOPR-specv2/20260906T0155` | same config as the first lean run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $25, 100 min. The lean rung is twice strict on v2. 92 entries all scored. Quality: erosion 0.049, verbosity 0.126, ast 0.053, cloned 0.061 |
| min9-ABDEFJKMNOP on v2 | `…min9-ABDEFJKMNOP-specv2/20260906T0356` | the lean rung minus H (quotable errors) and R (never narrow), 495 words; first of two | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $23, 75 min. 109 entries all scored, Differs 0-55 (top: query-timeout mechanism 55, mixed-type sort 45; enrich 8; blank-line/one-column 20). Quality: erosion 0.117, verbosity 0.194, ast 0.088, cloned 0.098 |
| min9-ABDEFJKMNOP on v2, repeat | `…min9-ABDEFJKMNOP-specv2/20260906T0535` | same config as the first run | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $25, 83 min. ABDEFJKMNOP is twice strict on v2 at 495 words. 114 entries all scored, Differs 0-45 (top: STORAGE_DIR default 45, repeated force 40; exact enrich=yes 15, enrich downgrade on re-ingest 35). Quality: erosion 0.097, verbosity 0.212, ast 0.088, cloned 0.105 |
| min9-ABDEFJKMNO on v2 | `…min9-ABDEFJKMNO-specv2/20260906T0720` | ABDEFJKMNOP minus P (do not change the spec or its tests), 483 words; first of two | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete 2026-09-06; 0 misses, 7/7 strict, $23, 80 min. 96 entries all scored, Differs 0-40 (top: ragged rows 40, spreadsheet cell to JSON 40; exact enrich=yes 15, enrich downgrade on re-ingest 30). Quality: erosion 0.069, verbosity 0.145, ast 0.053, cloned 0.080, the best of the chain |

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
  - min4-ABCHJK repeat (404): one miss, `test_trailing_empty_line_excluded`, planted at
    checkpoint 1 and carried through all seven. Entry A11 read a blank line as a record to
    keep; the first run read it as CSV convention to drop. The only earlier failure of that
    test was v4 on the unpatched spec. The cache flag fork closed at checkpoint 6 again.
  - min4 repeat (405): strict again, no misses. Same no-trim reading at checkpoint 5,
    entry marked Superseded at checkpoint 6 by the configuration section. Both parsing
    coin flips, single column and the trailing blank line, went the tests' way.
  - v8A repeat (405): strict again, no misses, every checkpoint matching the first run.
  - v9 (405): strict, no misses, v8A's pace and cost. The new Differs section appeared on all
    96 entries with a spread of values; both parsing coin flips and the cache flag went the
    tests' way, each with the divergent reading named beside the choice.
  - v9 repeat (404): one miss at checkpoint 7, repeated enrich params. Entry T94 took
    first-value-wins, scored it 20, and wrote the losing case out in its Differs line. The
    cache flag and both parsing coin flips went the tests' way again.
  - v9 on Fable 5.1 (394): the single-column cascade, identical to ABCFGHJK's eleven. Entry T5
    took the 400 with the Sniffer argument and a Differs of 30 naming the losing case. Nothing
    else missed; the cache flag closed at checkpoint 6.
  - v9 on spec v2 (405): strict. The two v2 sentences each show up in the registry as a closed
    question: repeated enrich at Differs 12, the one-column file handled in the delimiter entry.
  - v9 on spec v2, repeat (405): strict again, no misses. Twice strict on v2.
  - min9-ABDEFHJKMNOPR on v2 (405): strict, no misses, at 558 words and $29.
  - min9-ABCDEFGHIJKMNOPQR on v2 (405): strict, no misses.
  - min9-DEFJKOP on v2 (405): strict, no misses, at 391 words and $22.
  - min9-ABDEFHJKMNOPR on v2, repeat (405): strict again. Twice strict at 558 words.
  - min9-ABDEFJKMNOP on v2 (405): strict, no misses, at 495 words and $23. First of two.
  - min9-ABDEFJKMNOP on v2, repeat (405): strict again. Twice strict at 495 words.
  - min9-ABDEFJKMNO on v2 (405): strict, no misses, at 483 words and $23. First of two.

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

## Spec versions (2026-09-05)

Specs are versioned in `specs/` (`specs/README.md`): v0 the cache, v1 the five-sentence patch
every "disambiguated" run read, v2 = v1 plus "Only a single, exact `enrich=yes` enables
enrichment", which six of six blind judges read as any repetition keeps enrichment off. The
results table's spec column now says v0/v1/v2, taken from each run's catalog record, so the v1
rows above stay comparable and no run's spec changes under it. New runs are named -specvN.
v2 also carries "Delimiter must be inferred from input, if present" (2026-09-05 19:20Z): six of six
blind judges read a delimiter-free header-plus-row file as a one-column table and kept a one-line
JSON body at 400; all six would also accept delimiter-free prose, which no test checks. Queued on v2
behind the Fable v9 run: two Opus v9 runs, then min9 ABDEFHJKMNOPR, ABCDEFGHIJKMNOPQR and DEFJKOP
(ABCHJK's rules plus the registry procedure, 391 words).

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
(ABCHJK, min4, v8A, v8) plus v8B. Three single-chunk drops from ABCHJK (ABCHK, ACHJK,
ABCHJ; prompts and configs are in `configs/`) were queued behind them and removed at 16:30Z
once the ABCHJK rerun lost a test at checkpoint 1: the user wants drops taken only from a
prompt that strict-solves twice.
Added 2026-09-05 06:30Z behind the v8 rerun: two runs of v9 (v8A plus the Differs score in
every registry entry, `spectest-v9.jinja`; chunks in `min9-chunks/`).
The v8B and v8 reruns were stopped by request. Queued 2026-09-05 07:10Z behind the v9 pair,
optimistically: two nested min9 subsets, ABDEFHJKMNOPR (min4's rules in v9 form plus the
environment and tester-speed rules and the Differs procedure, 558 words) and
ABCDEFGHIJKMNOPQR (plus the test-writing extras, 690 words); v9 is the latter plus L and S.
Inserted 2026-09-05 07:40Z between the two v9 runs, to use Fable credits before the usage
reset: Fable 5.1 just-solve on xjq, file_merger, mvvault, rejector and sith (configs
`dev6-fable51-<problem>.yaml`, output under `outputs/dev6-fable51/`); their ledger is
`notes/dev6-fable5.md`'s successor, not this file.
Added 2026-09-05 11:50Z after sith and before the second Opus v9 run: Fable 5.1 on v9 with the
patched datagate spec (`spectest-v9-disambiguated-datagate-fable51.yaml`, the Fable agent config).
15:10Z: the window reserve in `bin/scb-extend` had never used a run's own costs (reset-time
jitter broke the before/after pairing), so every run reserved 30 points; fixed, and a fresh run
now seeds from the last three runs of its problem (datagate about 6). The sith Fable run was
paused asleep before checkpoint 5 and re-queued as a resume, so the second Opus v9 run could use
the 17 points left in the window instead of waiting 90 minutes for the reset.
18:20Z: the two min9 subsets came off the queue again; the spec may get a second patch first,
and shrinking waits for a twice-strict parent on whatever spec is current. Their configs stay.

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
and two more at checkpoint 7 with the same 400, one a single-column fixture (mixed numeric column) and one
the duplicate-enrich test, whose fixture has two columns. Registry entry T6 lists three
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

Amendment 2026-09-04 16:45Z, after the ABCHJK repeat: 404/405, 0/7 strict, $32, 191 min
(first run 405, $30, 129 min). One miss from one checkpoint 1 choice, a trailing blank
line kept as a row of empty strings; every other checkpoint matched the first run test
for test, and the annotate sentence closed the cache flag fork for the fourth run out of
four that carried it. So ABCHJK is not a stable strict solve: the blank-line question is
a third coin flip on the ladder, after the single-column reading and the cache flag, and
it flipped once in fourteen patched runs. Quality without the stray stress copy is the
best on the ladder: erosion 0.076, cloned 0.075. Per the user's rule the three
single-chunk drops came off the queue; shrinking starts from a prompt that strict-solves
twice, and none has yet.

Amendment 2026-09-05 01:20Z, after the min4 repeat: 405/405, 7/7 strict, $50. Wall clock
492 min, about 180 of them with the host suspended during checkpoint 2, so read it as
roughly five hours. min4 is the first prompt to strict-solve twice, and under the rule
that shrinking starts from a twice-strict prompt, it is the first eligible one. The
annotate step has now reopened the cache flag entry in five of five runs that carried
it. The two parsing coin flips did not fire here, which says nothing about min4 in
particular: single-column has flipped in 2 of 8 registry-keeping runs and the blank
line in 1 of 15 patched runs, so two clean min4 runs are consistent with the same odds.
Quality: erosion 0.076 against the first run's 0.167 and ast-grep 0.048 against 0.080,
the same direction as the ABCHJK repeat, so the first-run quality numbers on the ladder
were the noisy ones.

Amendment 2026-09-05 04:00Z, after the v8A repeat: 405/405, 7/7 strict, $37, 136 min
(first run $30, 120 min). v8A is the second prompt to strict-solve twice, and the cheaper
one: min4's two runs cost $43 and $50 and took about three and five hours; v8A's cost
$30 and $37 at two hours each. v8A carries 690 words to min4's 312, and the ledger's
earlier reading that the extra words buy efficiency and code shape rather than tests
now has two runs behind it: erosion 0.088 and 0.121 against min4's 0.076 and 0.167,
the same band, at a third less wall clock. Twice-strict prompts: min4, v8A. Once-strict
with a failed repeat: ABCHJK. Pending: v8B (403 first time), v8.

Amendment 2026-09-05 09:00Z, after v9's first run: 405/405, 7/7 strict, $32, 111 min, the
cheapest strict run so far. v9 is v8A plus a Differs section in every registry entry: a 0
to 100 chance that the spec author's own implementation and hidden test prefer a different
reading, with that reading named (`ambiguity-risk-judge.md`, fourth pass, has the wording's
provenance). The run produced 96 entries, all scored, spread 0 to 45 with 29 at 25 or
above. The three questions that flip on other prompts all went the tests' way and all
carry the divergent reading in the entry: non-tabular content at 45 ("author most likely
rejects anything from which no delimiter could be inferred"), the cache flag at 30 with
`os.environ.get(...).strip().lower()` written out at checkpoint 5, a checkpoint before the
spec added "trimmed", and blank lines at 15. Whether the score changes choices or only
annotates them is not decidable from one run; v8A also went 405 twice without it. What it
adds for certain is a ranked review list written during the run. Quality moved the wrong
way against v8A's repeat (erosion 0.119 against 0.088, ast-grep 0.079 against 0.040), inside
the run-to-run band seen on every other prompt. Second run is job 19, after the Fable set.

Amendment 2026-09-05 17:15Z, after v9's repeat: 404/405, 6/7 strict, $32, 102 min. The
miss is the fourth known flip, repeated enrich params (v8B lost it too): `enrich=yes&enrich=no`
must leave enrichment off, and the run took first-value-wins. So v9 is once strict, once
404, like ABCHJK, and the twice-strict prompts stay min4 and v8A. The Differs line's first
live calibration point: entry T94 scored the choice 20 and named the failing case exactly,
"a repeated enrich=yes&enrich=no, where a getlist-based author would keep enrichment off".
Right diagnosis, middling number: 20 is this run's median, 64 of 110 entries sit at or
above it, and the top of the list (45: charset on non-text sources, distinct-count) held
questions no test reaches. That matches the single-view judge pass, where the rare flips
sank while the wording-level coin flips stayed on top. The named reading is the actionable
half; the number ranks the wording's ambiguity more than the author's idiosyncrasy. Under
the twice-strict rule the queued min9 subsets have no eligible parent yet; the user chose
to keep them queued, last.

Amendment 2026-09-05 20:45Z, after v9 on Fable 5.1 (spec v1): 394/405, 0/7 strict, $13,
139 min. Fable took the single-column 400 at checkpoint 1 with the same Sniffer argument as
min2 and ABCFGHJK, lost the same eleven tests, and nothing else. So the reading is a model-
independent coin flip on the v1 sentence, now 3 of 12 registry runs, and the Differs line
flagged it at 30 with the losing case named, as it did on the Opus run that took it. Cost
$13 against Opus's $32 on the same prompt. This is the last run on v1; problems/ is now a
symlink to specs/v1/problems, and the queue continues on v2, whose delimiter sentence is
aimed at exactly this reading.

Amendment 2026-09-05 23:00Z, first run on spec v2 (v9 prompt): 405/405, 7/7 strict, $40, 118
min. Both v2 sentences read as intended by the agent that had to implement them. The enrich
entry, T92, says "'a single' is what excludes the repeat" and scores the question 12, where
the two v1 runs of the same prompt scored it 30 and 20 and one of them took the wrong side.
The delimiter entry, T14, handles the one-column file as a case the spec no longer leaves
open. Cost is up, $40 against $32 for the v1 runs, inside the run-to-run band. Second v2 run
is job 28, then the three min9 subsets on v2.

Amendment 2026-09-06 01:45Z, second run on spec v2: 405/405, 7/7 strict, $46, 140 min. v9 on
v2 is the third twice-strict prompt after min4 and v8A, and the first on v2. Across the two
runs the enrich question sat at Differs 12 and 10, against 30 and 20 on v1, which is the
score behaving as a review flag should when a sentence closes. Costs $40 and $46 against $32
and $32 on v1, the same prompt: worth watching across the subsets but inside what one prompt
has shown between runs. The min9 subsets now run against a twice-strict parent on the same
spec, which is the condition the shrink rule asked for.

Amendment 2026-09-06 03:45Z, first min9 subset on v2: ABDEFHJKMNOPR, 558 words, 405/405, 7/7
strict, $29, 101 min. This is v9 with six chunks removed: the four test-writing extras (finish
condition, e2e, phrase interactions, disposable tests) and the two ambiguity add-ons
(assert-the-choice, implementation-time entries). One run says none of the six is needed for
score on v2, at a third less cost than the parent. Under the shrink rule it counts after a
repeat, which is queued behind the other two subsets.
Queued after it at the user's request (2026-09-06 04:45Z): min9-DEFJKO on v2 (DEFJKOP without
"do not change the spec or the tests", 379 words, to price that rule), a DEFJKOP repeat, and
DEFJKOP on xjq (spec v0, its first problem beyond datagate; runs only if DEFJKOP is strict twice).
Replaced 2026-09-06 10:15Z at the user's request (the super-minimal sets cut the tester-speed
rules, which the user wants kept): the DEFJKO, DEFJKOP-repeat and DEFJKOP-xjq jobs came off unrun,
and the chain is now ABDEFJKMNOP on v2 twice (the lean rung minus quotable-errors and never-narrow,
495 words), then if twice strict ABDEFJKMNO twice (minus keep-spec-tests, 483 words), then if
twice strict ABDEFJKMNO on xjq (spec v0).

Amendment 2026-09-06 06:30Z, the middle v9 rung on v2: ABCDEFGHIJKMNOPQR, 690 words, 405/405,
7/7 strict, $35, 140 min. All three rungs of the v9 ladder are now strict on v2 on one run
each: lean (558 words, $29), middle (690, $35), v9 (735, $40 and $46). The six removable
chunks add nothing to score, and the ladder's quality numbers do not move with the rungs:
erosion 0.133, 0.064, 0.098 across lean, middle and v9's repeat, the same band every prompt
shows between its own runs. Next: DEFJKOP at 391 words, then the lean repeat.

Amendment 2026-09-06 09:00Z, DEFJKOP on v2: 391 words, 405/405, 7/7 strict, $22, 131 min,
the cheapest strict run on any spec and the shortest strict prompt that keeps the registry.
It is ABCHJK, which went 405 then 404 on v1, with the registry procedure and Differs added
and run on v2. Four rungs of the v9 ladder are now strict once each on v2, from 391 to 735
words, and the six chunks between DEFJKOP and the lean rung (pkill and pipe hygiene, the
quotable-error and never-narrow rules, the tester-speed pair) add nothing to score either.
Erosion 0.048 is the best on v2. Its repeat (job 34) decides whether it counts, and the xjq
run behind it (job 35) waits on that.

Amendment 2026-09-06 11:00Z, the lean rung repeated: ABDEFHJKMNOPR on v2, 405/405, 7/7 strict.
Twice-strict prompts are now min4 (v1), v8A (v1), v9 (v2) and the 558-word lean rung (v2),
which is the shortest of them and the parent of the ABDEFJKMNOP chain now running.


Amendment 2026-09-06 12:45Z, first run of ABDEFJKMNOP on v2: 495 words, 405/405, 7/7 strict,
$23, 75 min, the fastest strict run so far. This is the lean rung minus quotable-errors (H)
and never-narrow (R). Nothing flipped against either lean run (`bin/failures` is empty at every
checkpoint). Its registry has 109 entries, the most yet; the enrich entry sits at Differs 8
(the spec's v2 sentence closes it) and the top score is the query-timeout mechanism at 55.
Quality stays in the usual band (erosion 0.117 between the lean rung's 0.133 and 0.049).
This run also wrote its scores as `**Differs** N` with no dash, which `bin/registry-scores`
did not parse until c3e52c0. Its repeat (job 34) is running; if both are strict, ABDEFJKMNO
(minus keep-spec-tests, 483 words) runs twice, then on xjq. Behind those, at the user's
request, just-solve on v2 twice (jobs 38-39), unconditional.

Amendment 2026-09-06 14:30Z, ABDEFJKMNOP repeated on v2: 405/405, 7/7 strict, $25, 83 min.
Twice strict at 495 words, the shortest twice-strict prompt, and $48 for the pair against the
lean rung's $54. Nothing flipped between its two runs. The registry grew to 114 entries, with
nine on enrichment alone; the exact-enrich sentence itself sits at Differs 15, and the open
enrichment question is whether re-ingesting without the flag downgrades a stored enriched
dataset (35). So quotable-errors (H) and never-narrow (R) are not needed for score on v2.
Under the chain rule, ABDEFJKMNO (minus keep-spec-tests, 483 words) now runs twice as jobs
35-36; if both are strict, job 37 takes it to xjq.

Amendment 2026-09-06 16:15Z, first run of ABDEFJKMNO on v2: 483 words, 405/405, 7/7 strict,
$23, 80 min. This is ABDEFJKMNOP without keep-spec-tests (P). Nothing flipped against either
ABDEFJKMNOP run. The spec never sits in the agent's workspace, so P could only ever have kept
the agent from weakening its own tests; on this run the quality numbers went the other way
(erosion 0.069, ast 0.053, both better than the parent's 0.117/0.097 and 0.088). Registry: 96
entries, the enrich-downgrade question again the open one (30). Its repeat (job 36) is
running; if strict, job 37 takes ABDEFJKMNO to xjq on spec v0.
Changed 2026-09-06 16:30Z at the user's request: the xjq job is now min10-ABDEFJKMNO (the same
letters cut from v10, 488 words) as job 38, followed by the full v10 on xjq as job 39, then the
two just-solve runs on v2 (40-41). The rule stays: job 38 comes off if job 36 is not strict.
Queued 2026-09-06 16:50Z at the user's request, behind the just-solve pair (40-41): v10 on the
other five dev6 problems (42-46: datagate on v2, then file_merger, mvvault, rejector, sith on
v0), min10-ABDEFJKMNO on the same five (47-51), then a second pass of both prompts over all six
problems, v10 first (52-57) and min10 after (58-63). Twenty-two runs; the queue should not run
dry before 2026-09-08. Non-datagate results go in notes/<problem>-runs.md and the results table.
Changed 2026-09-06 17:00Z at the user's request: every queued ABDEFJKMNO run came off (the
min10 xjq job and the ten across dev6); job 36, the min9 repeat, keeps running. Three min10
subsets on datagate v2 went to the head of the queue, in this order: ABDFJKMN (473 words, the
twice-strict ABDEFJKMNOP minus hypothesis E, keep-spec-tests P and code-until-pass O, with the
Risk wording), ABDEJKMN (460, minus generator-floor F instead of E), ABDJKMN (450, minus both).
The v10 runs across dev6 (42-46, then 52-57) and the just-solve pair stay behind them.
