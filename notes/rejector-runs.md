# Spectest run ledger (rejector, Opus 5, Claude Code 2.1.251, thinking high)

Every rejector run under `outputs/spectest/`, what changed, and how it ended, in the shape of
`spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; rejector has five
checkpoints and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`.
The control is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 20/21, 33/34, 48/50, 64/67, 73/79 | complete (dev6 sweep); 6 misses, 0/5 strict, $36. Quality: erosion 0.559, verbosity 0.220, ast 0.185, cloned 0.037 |
| just-solve on v0, repeat | `…just-solve/20260915T1046` | benchmark's own prompt on the unpatched spec, a per-problem run; the second just-solve v0 replicate (the first is the dev6 control) | 20/21, 33/34, 49/50, 65/67, 76/79 | complete 2026-09-15; 3 misses, all the control's (retry exhaustion at 1, agentic max iterations at 4, dry run at 5); the control's first-number extraction, invalid ICL file and TPM gate passed. Three above the control, level with min12's best. 0/5 strict, $34 (per checkpoint 3, 4, 5, 11, 10), 144 min, the longest rejector run. Quality: erosion 0.716, verbosity 0.276, ast 0.242, cloned 0.044 |
| anti-slop | `…anti_slop/20260920T0031` | the benchmark's upstream anti_slop prompt as shipped (the paper's Anti-Slop arm; chunk T is its rule list), on v0; first of two | 20/21, 32/34, 47/50, 63/67, 73/79 | complete 2026-09-20; 6 misses: three every opus-5 run shares (max retries at 1, agentic max iterations at 4, dry run at 5), two the control also missed (invalid icl file at 3, tpm gate at 5), one of its own (backward-compat single task at 2); 0/5 strict, $39, 91 min. Quality: erosion 0.012, verbosity 0.159, ast 0.100, cloned 0.020; final checkpoint, implementation only (42% of LOC): ast 0.175, erosion 0.000, cloned 0.000 |
| anti-slop, repeat | `…anti_slop/20260920T2017` | same config as the first run; second of two | 21/21, 34/34, 48/50, 64/67, 74/79 | complete 2026-09-20; 5 misses, three shared with the first run (the ICL error's wording, max_iterations `passed`, the dry run's rounded minutes), all three answered by v1; new: test_costs (money rounded to cents, v1's patch 07) and test_icl_round_robin_strategy (setups handed out b, a, b, a); the first run's retries, single-task summary and TPM gate passed; 2/5 strict, $32, 105 min, overlapped by the specpatch channel, so the minutes are not comparable. Quality: erosion 0.068, verbosity 0.151, ast 0.111, cloned 0.004; final checkpoint, implementation only (45% of LOC): ast 0.164, erosion 0.000, cloned 0.004 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T1923` | the 468-word min11 subset (twice strict on datagate v2); first of two | 21/21, 33/34, 47/50, 64/67, 74/79 | complete 2026-09-08; 5 misses, four shared with the control (invalid ICL file failing before any request, agentic max iterations, the TPM gate, dry run) and one its own (backward compatibility of a single-task config, from checkpoint 2); the control's two others (API failure after max retries, first-number extraction) passed. 1/5 strict, $37 (per checkpoint 7, 6, 5, 7, 11), 361 min of wall clock of which about four hours was a laptop suspend during checkpoint 1. 101 registry entries all scored, Risk 0-55 (top: extracted_answer for script and llm_judge 55, tool definitions in a completions prompt 55; the single-task summary shape 45). Quality: erosion 0.209, verbosity 0.242, ast 0.111, cloned 0.095 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260908T0648` | same config as the first run | 20/21, 33/34, 49/50, 65/67, 76/79 | complete 2026-09-08; 3 misses: retry exhaustion from checkpoint 1 (the control's miss, which the first run passed), agentic max iterations, dry run; the first run's single-task compatibility, invalid ICL file and TPM gate all passed. 0/5 strict, $30 (per checkpoint 4, 6, 6, 7, 8), 108 min. 114 registry entries all scored, Risk 0-55 (top: tool definitions in a completions prompt 55, multi-turn mistral 50). Quality: erosion 0.210, verbosity 0.197, ast 0.121, cloned 0.070 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260914T2312` | the 444-word no-F prompt on v0, for the six-problem quality-uplift comparison; first of two | 21/21, 32/34, 49/50, 65/67, 75/79 | complete 2026-09-15; 4 misses: first-number extraction (checkpoint 2, back at 5), agentic max iterations, dry run, and the single-task backward-compatibility case min11 also lost; the control's retry exhaustion, invalid ICL file and TPM gate passed. Two above the control, the best rejector score. 1/5 strict (checkpoint 1), $28 (per checkpoint 4, 5, 5, 6, 8), 92 min. 110 entries all scored, Risk 0-45 (tool definitions rendered into the prompt 45; 5xx retry count, meta for an all-failed row 40). Quality: erosion 0.192, verbosity 0.239, ast 0.114, cloned 0.118 |
| min12-ABDJKMN, repeat | `…min12-ABDJKMN/20260915T0516` | same config as the first run | 21/21, 33/34, 49/50, 66/67, 76/79 | complete 2026-09-15; 3 misses: the single-task backward-compatibility case from checkpoint 2 (both min12 runs and both min11 runs), dry run and the TPM gate at checkpoint 5; the first run's first-number extraction and agentic max iterations passed. Three above the control, the best rejector score. 1/5 strict, $28 (per checkpoint 4, 5, 5, 6, 8), 113 min. 100 entries all scored, Risk 10-55 (tool definitions in a completions prompt 55; cost rounding, a permanently failing agentic request 45). Quality: erosion 0.151, verbosity 0.265, ast 0.114, cloned 0.149 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T2129` | min12-ABDJKMN plus chunk T, upstream's anti-slop rules as the whole Implement section; one sample run for the ast question | 20/21, 33/34, 49/50, 64/67, 74/79 | complete 2026-09-18; 5 misses: dry run and the TPM gate (the control's, and both min12 runs'); retries from checkpoint 1, where the run made four HTTP calls and the test wants three and a null output (its own T2, Risk 45, named the author's reading); agentic max iterations (`passed` is null, the test wants false; the first min12 run missed it too); costs, 0.011 against a 0.01 ceiling. First-number extraction failed at checkpoint 4 only. The backward-compat single-task case passed; both min12 runs missed it. 0/5 strict, $33, 107 min. 104 entries all scored, Risk 10-55. Quality: erosion 0.028, verbosity 0.214, ast 0.074, cloned 0.104; implementation only, ast 0.188 against min12's 0.339 and 0.344, erosion 0.172 against 0.608 and 0.539 |
| min13-ABDJKMNT, repeat | `…min13-ABDJKMNT/20260919T1228` | same config as the first run; second of two | 20/21, 31/34, 46/50, 62/67, 73/79 | complete 2026-09-19; 6 misses: three shared with the first run (max retries at 1, agentic max iterations at 4, dry run at 5) and three of its own (backward-compat single task and llm judge pass at 2, invalid icl file at 3); the first run's own three (first-number extract, costs, tpm gate) passed; 0/5 strict, $34, 114 min. Quality: erosion 0.019, verbosity 0.127, ast 0.075, cloned 0.031; final checkpoint, implementation only (35% of LOC): ast 0.170, erosion 0.102, cloned 0.021 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T2129` | min12 plus chunk T, the upstream anti-slop rule list (d902f32); second of the min13 pair, after mvvault | 20/21, 33/34, 49/50, 64/67, 74/79 | complete 2026-09-18; 6 misses: five that at least one other opus-5 run missed (max-retries at 1, first-number extract at 2, agentic max iterations at 4, dry run and tpm gate at 5) plus test_costs at 5, which no other run missed. 0/5 strict, $33, 107 min. Quality: erosion 0.028, verbosity 0.214, ast 0.074, cloned 0.104 |
| min13-ABDJKMNT on v1 (halted at the last checkpoint) | `…min13-ABDJKMNT-specv1/20260920T1926` | min13 on spec v1 (eight sentences) under bin/scb-strict in the specpatch channel; first of two | 21/21, 34/34, 50/50, 67/67, 78/79 | complete 2026-09-20 (the halt came after checkpoint 5, the last); 1 miss, test_tpm_gate, by the 10-second timeout: the limiter sleeps until the window slides and no reply wakes it; every other test passes, the best rejector run of any prompt (best before: 76); 4/5 strict, $33, 95 min, overlapped by the main queue, so the minutes are not comparable. Quality: erosion 0.018, verbosity 0.178, ast 0.070, cloned 0.080; final checkpoint, implementation only (33% of LOC): ast 0.192, erosion 0.030, cloned 0.022 |
| min13-ABDJKMNT on v1, repeat (halted at the last checkpoint) | `…min13-ABDJKMNT-specv1/20260920T2113` | same config as the first run, under bin/scb-strict in the specpatch channel; second of two | 21/21, 34/34, 50/50, 67/67, 78/79 | complete 2026-09-20; 1 miss, test_tpm_gate again by the 10-second timeout, the same missed wake-up (`rejlib/ratelimit.py:107`, `await asyncio.sleep(wait)`); every other test passes; 4/5 strict, $40, 119 min, overlapped by the main queue, so the minutes are not comparable. Quality: erosion 0.046, verbosity 0.141, ast 0.064, cloned 0.033; final checkpoint, implementation only (32% of LOC): ast 0.116, erosion 0.026, cloned 0.019 |
| anti-slop on v1 | `…anti_slop-specv1/20260921T1502` | the upstream anti_slop prompt on spec v1, a baseline for the grid's patched cell; first of two | 21/21, 34/34, 49/50, 67/67, 77/79 | complete 2026-09-21; 3 misses, named and not traced (a baseline): test_first_number_extract at checkpoint 3 (the reply-order race patch `03` narrows and cannot close; 14 pass, 2 fail before this run), test_costs (`3.0 == 1.0`, a different failure from the cents rounding patch `07` settles) and test_tpm_gate (the timeout every prompt has hit); the other six v1 sentences held; 3/5 strict, $32, 84 min. Quality: erosion 0.111, verbosity 0.139, ast 0.106, cloned 0.023; final checkpoint, implementation only (46% of LOC): ast 0.176, erosion 0.088, cloned 0.023 |
| anti-slop on v1, repeat | `…anti_slop-specv1/20260921T1637` | same config as the first run; second of two | 21/21, 34/34, 50/50, 67/67, 78/79 | complete 2026-09-21; 1 miss, test_tpm_gate (the timeout; 8 pass, 9 fail over all runs now), the same as min13's only miss on v1 twice; all eight v1 sentences held; 4/5 strict, $33, 103 min. Quality: erosion 0.097, verbosity 0.193, ast 0.140, cloned 0.017; final checkpoint, implementation only (58% of LOC): ast 0.199, erosion 0.070, cloned 0.021 |
| just-solve on v1 | `…just-solve-specv1/20260921T1830` | benchmark's own prompt on spec v1, a baseline for the grid's patched cell; first of two | 21/21, 34/34, 50/50, 67/67, 79/79 | complete 2026-09-21; 0 misses, the first 79/79 on rejector under any prompt; test_tpm_gate passed (9 pass, 9 fail over all runs); 5/5 strict, $32, 115 min. Quality: erosion 0.830, verbosity 0.287, ast 0.216, cloned 0.070; final checkpoint, implementation only (51% of LOC): ast 0.354, erosion 0.714, cloned 0.048 |
| just-solve on v1, repeat | `…just-solve-specv1/20260921T2034` | same config as the first run; second of two | 21/21, 33/34, 50/50, 67/67, 78/79 | complete 2026-09-21; 2 misses, named and not traced (a baseline): test_first_number_extract at checkpoint 2 (the reply-order race patch `03` narrows and cannot close) and test_tpm_gate (the timeout; 9 pass, 10 fail over all runs); the other six v1 sentences held; 3/5 strict, $26, 122 min. Quality: erosion 0.534, verbosity 0.160, ast 0.108, cloned 0.039; final checkpoint, implementation only (50% of LOC): ast 0.202, erosion 0.673, cloned 0.070 |
| min12-ABDJKMN on v1 | `…min12-ABDJKMN-specv1/20260922T0514` | min12 on spec v1, the one patched pair the dev grid was missing; first of two | 21/21, 33/34, 50/50, 67/67, 79/79 | complete 2026-09-22; 1 miss, test_first_number_extract at checkpoint 2 only (passed at 3, 4 and 5): the reply-order race that patch `03`'s sentence narrows and cannot close; no registry entry asks about pairing order (T37 and T47 are about scheduling and round_robin); test_tpm_gate passed; all eight sentences held; 4/5 strict, $34, 166 min. Quality: erosion 0.198, verbosity 0.188, ast 0.109, cloned 0.076; final checkpoint, implementation only (28% of LOC): ast 0.305, erosion 0.629, cloned 0.031 |
| min12-ABDJKMN on v1, repeat | `…min12-ABDJKMN-specv1/20260922T0809` | same config as the first run; second of two | 21/21, 34/34, 50/50, 67/67, 78/79 | complete 2026-09-22; 1 miss, test_tpm_gate by timeout (T96, Risk 30, chose the tests' reading, so the missed wake-up again: a bug, not a reading; 10 pass, 11 fail over all runs); all eight sentences held; 4/5 strict, $32, 126 min. Quality: erosion 0.185, verbosity 0.241, ast 0.089, cloned 0.150; final checkpoint, implementation only (25% of LOC): ast 0.335, erosion 0.605, cloned 0.057 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 73/79: six misses, one per checkpoint from 1 on: retry exhaustion, first-number
    extraction, the invalid ICL file, agentic max iterations, then the TPM gate and dry run
    at checkpoint 5.

### just-solve on v0, repeat (2026-09-15)

  - 76/79, three above the control and level with min12's repeat, on three of the control's
    six. Cell: 73 and 76 against min12's 75 and 76; the score gap on rejector is inside the
    bare prompt's own spread. Erosion 0.559 and 0.716 against 0.192 and 0.151.

### just-solve on v1 (2026-09-21)

  - 79/79, strict at all five checkpoints: the first perfect run on rejector under any prompt,
    from 73 and 76 on v0, above min13's 78 and 78 and anti-slop's 77 and 78 on v1, all of which
    lost test_tpm_gate. A baseline, so nothing traced. It wrote tests, 49% of 3762 lines; $32
    and 115 min. Implementation only: erosion 0.714, ast 0.354, cloned 0.048, the usual
    just-solve figures. First of two.
  - repeat (78): the pair is 79 and 78 against 73 and 76 on v0, min13's 78 and 78 and
    anti-slop's 77 and 78. Two misses, the race and the tpm timeout, both seen under every
    prompt. Not traced. $26 and 122 min. Implementation only: erosion 0.673, ast 0.202,
    cloned 0.070; the mean of the two runs is 0.694, 0.278, 0.059. That closes the v1 cell:
    just-solve 79 and 78, anti-slop 77 and 78, min13 78 and 78, the three prompts within
    one test of each other on a spec whose eight sentences all held.

### anti-slop (the upstream anti_slop prompt, 2026-09-20)

  - 73/79, on just-solve's 73 and 76, min12's 75 and 76 and min13's 74 and 73: the usual
    families plus one of its own. 1813 implementation lines and 2534 of tests (just-solve
    2778 and 2388, min12 1995 and 5412, min13 1995 and 4000 per run); $39 and 91 min, more
    than any other prompt's mean here. Implementation only: erosion 0.000 (just-solve 0.709,
    min12 0.573, min13 0.136), ast 0.175 (0.334, 0.342, 0.178), cloned 0.000 (0.062, 0.041,
    0.020). The one dev problem where min13 kept some implementation erosion, and the rule
    list alone has none. First of two.
  - repeat (74): one above the first run with half the misses swapped, three shared of five.
    Four of its five are sentences v1 now carries (patches 04, 05, 06, 07); test_costs fails as
    min13's did, `0.011 <= 0.01`, money rounded to the example's cents, so that reading has
    now cost three runs of fourteen. The fifth is its own: test_icl_round_robin_strategy wants
    setups a, b, a, b across a row's attempts and got b, a, b, a (12 pass, 2 fail over all
    runs). Its `icl.choose(attempts)` indexes by an attempt counter that starts at 0, so the
    offset comes from somewhere else in the attempt loop; not traced. The TPM
    gate passed this time. Pair 73 and 74 against just-solve's 73 and 76, min12's 75 and 76,
    min13's 74 and 73. Implementation only over the pair: erosion 0.000, ast 0.170, cloned
    0.002 on 1865 lines per run against just-solve's 0.709, 0.334, 0.062 on 2778. $32 and 105
    min.
  - on v1 (77): from 73 and 74 on v0, one under min13's 78 and 78. A baseline, so the three
    misses are named and not traced: test_first_number_extract (the reply-order race, patch
    `03`'s sentence held in min13's pair and not here), test_costs (`assert 3.0 == 1.0`, not
    the cents rounding that patch `07` settles and this run got right) and test_tpm_gate (the
    timeout that has now cost eight runs across every prompt). It wrote tests this time, 54%
    of 2848 lines; $32 and 84 min. Implementation only: erosion 0.088, ast 0.176, cloned
    0.023. First of two.
  - on v1, repeat (78): the pair is 77 and 78 against 73 and 74 on v0 and min13's 78 and 78.
    One miss, test_tpm_gate, min13's only v1 miss too, so on v1 the two prompts are level.
    Not traced. 42% of 3220 lines are tests; $33 and 103 min. Implementation only: erosion
    0.070, ast 0.199, cloned 0.021; the mean of the two runs is 0.079, 0.188, 0.022.

### min12-ABDJKMN (without F)

  - first run (75): two above the control and one above min11's pair. Three control misses
    passed (retries, invalid ICL file, TPM gate); the single-task backward-compatibility case
    fails from checkpoint 2 as it did for min11. Erosion 0.192 against the control's 0.559.
    First of two.
  - repeat (76): three misses, one better. Backward-compat single-task holds across all four
    min runs, the checkpoint-5 pair (dry run, TPM gate) is the control's. Pair: 75 and 76
    against the control's 73; erosion 0.192 and 0.151 against 0.559.
  - on v1 (79 at the final checkpoint, 33/34 at checkpoint 2): from 75 and 76 on v0, level
    with just-solve's 79 and 78, min13's 78 and 78 and anti-slop's 77 and 78. The one miss
    is the reply-order race at checkpoint 2, which passed at every later checkpoint: `'7.5'
    == '8'`, the first row's reply taken by the second. Patch `03` puts "send requests in
    input order" in checkpoint 1 and the run's registry never questioned it; the race is in
    the mock, not the reading (rejector-misses.md, reading 3). test_tpm_gate passed, which
    min13 lost in both v1 runs. 166 min, the longest v1 run; $34. Implementation only (28%
    of lines): erosion 0.629, ast 0.305, cloned 0.031. First of two.
  - repeat (78): the pair is 79 and 78 against 75 and 76 on v0. One miss, test_tpm_gate by
    timeout; its registry (T96, Risk 30) chose the tests' reading and the limiter slept past the
    reply anyway, the missed wake-up every failing run shares. $32 and 126 min. Implementation
    only: erosion 0.605, ast 0.335, cloned 0.057; the mean of the two runs is 0.617, 0.320, 0.044.
    The dev grid's last patched pair; rejector v1 reads just-solve 79 and 78, anti-slop 77 and
    78, min12 79 and 78, min13 78 and 78.

### min13-ABDJKMNT (min12 plus the anti-slop list)

  - 74/79, one to two below the min12 pair (75, 76) and inside the just-solve pair (73, 76).
    Five of its six misses are shared with other runs; test_costs at checkpoint 5 is new.
    Erosion 0.028 against min12's 0.192 and 0.151, ast 0.074 against 0.114; $33 and 107 min
    against min12's $28 and 103. With mvvault (215 against 220, 223) the pair reads: chunk T
    takes erosion down another 4x to 6x, score flat to slightly down, cost about the same.

### min13-ABDJKMNT (min12-ABDJKMN plus the anti-slop chunk)

  - one run (74): one and two below the min12 pair, one above the control. Dry run and the TPM
    gate are shared with every run. Retries is a reading the registry scored at 45 and lost: four
    HTTP calls for "retry up to 3 times" where the tests count three. Agentic max iterations
    leaves `passed` null, as the first min12 run did. Costs is new: 0.011 against the test's
    0.01. Backward-compat single-task passed, which both min12 runs missed.
  - the question the run was for: implementation-only ast is 0.188, against 0.339 and 0.344 for
    the two min12 runs and 0.334 for just-solve, which min12 had not moved at all. Erosion
    0.172 against 0.608 and 0.539. The whole-function rules carry it, as on mvvault:
    `defensive-isinstance-raise-heavy` and `defensive-try-soup-function` at zero,
    `function-with-many-type-guards` and `defensive-function-isinstance-heavy` at less than half.
    What rose is `defensive-validator-function` and `defensive-fstring-raise-heavy`, zero in
    min12: the type checks that stayed sit in validators. 25 files against one. One run.

  - repeat (73): one below the first run, with half the misses swapped: three shared, three
    new, the first run's three own misses passed. Pair: 74 and 73 against min12's 75 and 76
    and just-solve's 73 and 76, inside the v0 spread. Implementation only over the pair:
    erosion 0.136 against min12's 0.573, ast 0.178 against 0.342, cloned 0.020 against 0.041,
    on the same 1995 implementation lines per run. $34 and 114 min against min12's $28 and
    103; the one dev problem where min13 costs more than min12.

### min11-ABDFJKMN

  - first run (74): one better than the control, with a different shape. Retries and number
    extraction passed; the single-task backward-compatibility test failed from checkpoint 2,
    and the registry had the question (T27, whether the `tasks` summary also appears for
    single-task configs, Risk 45) and chose against the tests. The four late misses are the
    control's.
  - repeat (76): the best rejector score so far, with only two misses in common with the
    first run (agentic max iterations, dry run). The retry-exhaustion test flipped the other
    way this time, and three of the first run's misses passed. rejector's misses move between
    runs of the same prompt; the pair is 74 and 76 against the control's 73, $37 and $30.

## Spec v1 (2026-09-20)

Eight sentences, the user's wording (e81b2a7), no judge run. The misses they answer are grouped
in `notes/rejector-misses.md`; each patch's preamble carries its evidence.

  - `01`, checkpoint 1: "retry it up to 3 total requests", where six runs of nine made four calls.
    The first committed wording, "retry it until the 3rd time", was replaced before any run
    (0fbd0e3), so the folder is still v1.
  - `02`, checkpoint 2: a single-task config's summary "keeps its previous keys and has no
    `tasks` object".
  - `03`, checkpoint 1: "Send requests in input order: concurrent execution must not cause a later
    input row to consume the response intended for an earlier row", checkpoint 5's own words,
    three checkpoints early. It narrows a race in test_first_number_extract and cannot close it.
  - `04`, checkpoint 3: "malformed line errors include `not valid JSON`".
  - `05`, checkpoint 4: on the omitted-evaluation bullet, `result.passed` is `null` "except when
    `max_iterations` was reached, where it is `false`". The test contradicted the spec.
  - `06`, checkpoint 5: the dry run's minutes "prefer precision over rounding" (the draft said "at
    least four decimal places"); 0 of 9 runs passed test_dry_run.
  - `07`, checkpoint 5: costs "to at least four decimal places".
  - `08`, checkpoint 2: under `llm_judge`, `result.extracted_answer` is the text `extract` took
    from the judge's reply.
  - Not patched: test_tpm_gate (4 of 9 pass), a missed wake-up in the limiter, the agent's bug.

Queued in the `specpatch` channel as jobs 267 and 268 and removed the same hour, before either
started, at the user's call: `01`'s wording is to change first, and with no run made against it
the folder stays v1. Nothing ran and no run directory exists. Expect test_tpm_gate to fail under
bin/scb-strict whatever the sentences say, so the run may need the plain driver.

Queued 2026-09-20 with the new `01`: min13-ABDJKMNT on v1 under bin/scb-strict in the `specpatch`
channel, and its repeat `--after` it. Behind the repeat, in the main queue ahead of the test-set
batch: anti-slop on v1 twice and just-solve on v1 twice, each `--after` the repeat, so they start
only if both strict runs are strict. test_tpm_gate is at checkpoint 5, the last, and is the
agent's bug (4 of 9 pass), so a halt there is expected; the point of the first run is to see that
the TPM gate is the only miss left. The baselines are then re-queued by hand.

First run on v1 (job 267, 2026-09-20): 78/79, strict through checkpoint 4, from 73 and 74 on v0.
The one miss is the one expected. test_tpm_gate times out: `taskrunner/limits.py:124` ends its
wait in `await asyncio.sleep(wait)` with nothing to wake it when a reply frees room, the same
missed wake-up as the failing v0 runs, and the registry again read the spec the tests' way (T66,
Risk 25, the reservation is replaced by the actual usage). Jobs 268 to 272 (the strict repeat and
the anti-slop and just-solve pairs, each `--after`) failed unrun as designed. Sentence by
sentence, from the registry (79 entries):

  - `01` held: test_api_failure_after_max_retries passes and no entry asks how many calls a
    failing request gets, the Risk 40 to 45 question of every v0 run.
  - `02`, `03`, `04`, `05` held and drew no entry. test_first_number_extract passed; `03` cannot
    close that race, so one pass proves little.
  - `06` held: test_dry_run passes, the first pass by any run; the only dry-run entry left is
    about summing across tasks (T76).
  - `07` held: T67, Risk 30, reads "at least four" as a floor and reports more.
  - `08` held: the remaining `extracted_answer` entries are about `contains`, `regex` and
    `script`, not the judge.

With the TPM gate the only miss, the condition the user set for the baselines, the rest was
re-queued 2026-09-20 without dependencies: the strict repeat (job 279, specpatch channel; the
strict driver runs all five checkpoints, since the TPM gate is in the last) and, in the main
queue ahead of the test-set batch, anti-slop on v1 twice (280, 281) and just-solve on v1 twice
(282, 283). No min12 pair on rejector.

Repeat on v1 (job 279, 2026-09-20): 78/79 again, the same single miss for the same reason, so the
pair is 78 and 78 against 74 and 73 on v0, and the eight sentences are two for two. The TPM gate
is now 0 for 2 under min13 on v1 and 4 of 9 over the v0 runs: both v1 limiters sleep out the
window, and both registries chose "replaced by the actual usage" (T66; T71, Risk 30). Two entries
of this run's registry (92 entries) are worth keeping:

  - T20, "What 'send requests in input order' constrains", Risk 20, is patch `03` read back to
    us. It dispatches rows in input order and says why that cannot be more: "with several
    connections opening at once, TCP setup alone can let row 1's request land before row 0's,
    which is true of any concurrent client including one built to this spec", and a fixture that
    wants arrival order "would be satisfied only by a client that effectively serialises sending
    - which contradicts the throughput requirement". That is the race in test_first_number_extract,
    named by the tester; it passed in both v1 runs all the same.
  - T85, "Rounding of the dry-run estimates", Risk 40, shows `06`'s looser wording leaving a
    question open while still landing right: it quotes "prefer precision over rounding", rounds
    token totals once to whole numbers, keeps six decimals of cost and does not round
    `est_time_minutes`. test_dry_run passed.

anti-slop on v1, first run (job 280, 2026-09-21): 77/79, from 73 and 74 on v0. A baseline: the
misses are test_first_number_extract at checkpoint 3, test_costs (`3.0 == 1.0`, another failure
than the cents rounding) and test_tpm_gate. Six of the eight v1 sentences drew no miss. Not traced.

anti-slop on v1, repeat (job 281, 2026-09-21): 78/79, the pair 77 and 78 against min13's 78 and 78.
One miss, test_tpm_gate, the timeout min13 also lost twice on v1. All eight sentences held. On v1
anti-slop and min13 are level on this problem; the just-solve pair (282, 283) closes the cell.

just-solve on v1, first run (job 282, 2026-09-21): 79/79, every checkpoint strict, from 73 and 76
on v0. The first run of any prompt to pass test_tpm_gate on v1 (min13 and anti-slop lost it in
all four runs). A baseline, not traced. The repeat (283) is the last job in the queue.

just-solve on v1, repeat (job 283, 2026-09-21): 78/79, the pair 79 and 78. The misses are the
reply-order race at checkpoint 2 and test_tpm_gate, both the benchmark's regulars. A baseline, not
traced. The v1 cell is complete for all three prompts that ran it (min12 was not queued on
rejector): just-solve 79 and 78, anti-slop 77 and 78, min13 78 and 78. The queue is empty; the
test-set batch stays stashed.

min12 on v1, first run (job 284, 2026-09-22): 79/79 at the final checkpoint, from 75 and 76 on v0.
The one miss is test_first_number_extract at checkpoint 2, passing from checkpoint 3 on: the
mock's first-come reply order, which `03`'s sentence cannot fix (18 pass, 2 fail, and the fails
sit in different runs each time). No registry entry asks about reply pairing. test_tpm_gate
passed. The repeat (285) closes the last patched pair on the dev grid.

min12 on v1, repeat (job 285, 2026-09-22): 78/79, the pair 79 and 78. test_tpm_gate by timeout, the
registry choosing right (T96) and the code sleeping through the wake-up, as in every failing run
(rejector-misses.md, "Not the spec"). The v1 cell is complete for all four prompts.
