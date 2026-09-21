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
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T1923` | the 468-word min11 subset (twice strict on datagate v2); first of two | 21/21, 33/34, 47/50, 64/67, 74/79 | complete 2026-09-08; 5 misses, four shared with the control (invalid ICL file failing before any request, agentic max iterations, the TPM gate, dry run) and one its own (backward compatibility of a single-task config, from checkpoint 2); the control's two others (API failure after max retries, first-number extraction) passed. 1/5 strict, $37 (per checkpoint 7, 6, 5, 7, 11), 361 min of wall clock of which about four hours was a laptop suspend during checkpoint 1. 101 registry entries all scored, Risk 0-55 (top: extracted_answer for script and llm_judge 55, tool definitions in a completions prompt 55; the single-task summary shape 45). Quality: erosion 0.209, verbosity 0.242, ast 0.111, cloned 0.095 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260908T0648` | same config as the first run | 20/21, 33/34, 49/50, 65/67, 76/79 | complete 2026-09-08; 3 misses: retry exhaustion from checkpoint 1 (the control's miss, which the first run passed), agentic max iterations, dry run; the first run's single-task compatibility, invalid ICL file and TPM gate all passed. 0/5 strict, $30 (per checkpoint 4, 6, 6, 7, 8), 108 min. 114 registry entries all scored, Risk 0-55 (top: tool definitions in a completions prompt 55, multi-turn mistral 50). Quality: erosion 0.210, verbosity 0.197, ast 0.121, cloned 0.070 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260914T2312` | the 444-word no-F prompt on v0, for the six-problem quality-uplift comparison; first of two | 21/21, 32/34, 49/50, 65/67, 75/79 | complete 2026-09-15; 4 misses: first-number extraction (checkpoint 2, back at 5), agentic max iterations, dry run, and the single-task backward-compatibility case min11 also lost; the control's retry exhaustion, invalid ICL file and TPM gate passed. Two above the control, the best rejector score. 1/5 strict (checkpoint 1), $28 (per checkpoint 4, 5, 5, 6, 8), 92 min. 110 entries all scored, Risk 0-45 (tool definitions rendered into the prompt 45; 5xx retry count, meta for an all-failed row 40). Quality: erosion 0.192, verbosity 0.239, ast 0.114, cloned 0.118 |
| min12-ABDJKMN, repeat | `…min12-ABDJKMN/20260915T0516` | same config as the first run | 21/21, 33/34, 49/50, 66/67, 76/79 | complete 2026-09-15; 3 misses: the single-task backward-compatibility case from checkpoint 2 (both min12 runs and both min11 runs), dry run and the TPM gate at checkpoint 5; the first run's first-number extraction and agentic max iterations passed. Three above the control, the best rejector score. 1/5 strict, $28 (per checkpoint 4, 5, 5, 6, 8), 113 min. 100 entries all scored, Risk 10-55 (tool definitions in a completions prompt 55; cost rounding, a permanently failing agentic request 45). Quality: erosion 0.151, verbosity 0.265, ast 0.114, cloned 0.149 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T2129` | min12-ABDJKMN plus chunk T, upstream's anti-slop rules as the whole Implement section; one sample run for the ast question | 20/21, 33/34, 49/50, 64/67, 74/79 | complete 2026-09-18; 5 misses: dry run and the TPM gate (the control's, and both min12 runs'); retries from checkpoint 1, where the run made four HTTP calls and the test wants three and a null output (its own T2, Risk 45, named the author's reading); agentic max iterations (`passed` is null, the test wants false; the first min12 run missed it too); costs, 0.011 against a 0.01 ceiling. First-number extraction failed at checkpoint 4 only. The backward-compat single-task case passed; both min12 runs missed it. 0/5 strict, $33, 107 min. 104 entries all scored, Risk 10-55. Quality: erosion 0.028, verbosity 0.214, ast 0.074, cloned 0.104; implementation only, ast 0.188 against min12's 0.339 and 0.344, erosion 0.172 against 0.608 and 0.539 |
| min13-ABDJKMNT, repeat | `…min13-ABDJKMNT/20260919T1228` | same config as the first run; second of two | 20/21, 31/34, 46/50, 62/67, 73/79 | complete 2026-09-19; 6 misses: three shared with the first run (max retries at 1, agentic max iterations at 4, dry run at 5) and three of its own (backward-compat single task and llm judge pass at 2, invalid icl file at 3); the first run's own three (first-number extract, costs, tpm gate) passed; 0/5 strict, $34, 114 min. Quality: erosion 0.019, verbosity 0.127, ast 0.075, cloned 0.031; final checkpoint, implementation only (35% of LOC): ast 0.170, erosion 0.102, cloned 0.021 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T2129` | min12 plus chunk T, the upstream anti-slop rule list (d902f32); second of the min13 pair, after mvvault | 20/21, 33/34, 49/50, 64/67, 74/79 | complete 2026-09-18; 6 misses: five that at least one other opus-5 run missed (max-retries at 1, first-number extract at 2, agentic max iterations at 4, dry run and tpm gate at 5) plus test_costs at 5, which no other run missed. 0/5 strict, $33, 107 min. Quality: erosion 0.028, verbosity 0.214, ast 0.074, cloned 0.104 |
| min13-ABDJKMNT on v1 (halted at the last checkpoint) | `…min13-ABDJKMNT-specv1/20260920T1926` | min13 on spec v1 (eight sentences) under bin/scb-strict in the specpatch channel; first of two | 21/21, 34/34, 50/50, 67/67, 78/79 | complete 2026-09-20 (the halt came after checkpoint 5, the last); 1 miss, test_tpm_gate, by the 10-second timeout: the limiter sleeps until the window slides and no reply wakes it; every other test passes, the best rejector run of any prompt (best before: 76); 4/5 strict, $33, 95 min, overlapped by the main queue, so the minutes are not comparable. Quality: erosion 0.018, verbosity 0.178, ast 0.070, cloned 0.080; final checkpoint, implementation only (33% of LOC): ast 0.192, erosion 0.030, cloned 0.022 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 73/79: six misses, one per checkpoint from 1 on: retry exhaustion, first-number
    extraction, the invalid ICL file, agentic max iterations, then the TPM gate and dry run
    at checkpoint 5.

### just-solve on v0, repeat (2026-09-15)

  - 76/79, three above the control and level with min12's repeat, on three of the control's
    six. Cell: 73 and 76 against min12's 75 and 76; the score gap on rejector is inside the
    bare prompt's own spread. Erosion 0.559 and 0.716 against 0.192 and 0.151.

### anti-slop (the upstream anti_slop prompt, 2026-09-20)

  - 73/79, on just-solve's 73 and 76, min12's 75 and 76 and min13's 74 and 73: the usual
    families plus one of its own. 1813 implementation lines and 2534 of tests (just-solve
    2778 and 2388, min12 1995 and 5412, min13 1995 and 4000 per run); $39 and 91 min, more
    than any other prompt's mean here. Implementation only: erosion 0.000 (just-solve 0.709,
    min12 0.573, min13 0.136), ast 0.175 (0.334, 0.342, 0.178), cloned 0.000 (0.062, 0.041,
    0.020). The one dev problem where min13 kept some implementation erosion, and the rule
    list alone has none. First of two.

### min12-ABDJKMN (without F)

  - first run (75): two above the control and one above min11's pair. Three control misses
    passed (retries, invalid ICL file, TPM gate); the single-task backward-compatibility case
    fails from checkpoint 2 as it did for min11. Erosion 0.192 against the control's 0.559.
    First of two.
  - repeat (76): three misses, one better. Backward-compat single-task holds across all four
    min runs, the checkpoint-5 pair (dry run, TPM gate) is the control's. Pair: 75 and 76
    against the control's 73; erosion 0.192 and 0.151 against 0.559.

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
