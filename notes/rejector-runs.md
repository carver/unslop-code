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
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T1923` | the 468-word min11 subset (twice strict on datagate v2); first of two | 21/21, 33/34, 47/50, 64/67, 74/79 | complete 2026-09-08; 5 misses, four shared with the control (invalid ICL file failing before any request, agentic max iterations, the TPM gate, dry run) and one its own (backward compatibility of a single-task config, from checkpoint 2); the control's two others (API failure after max retries, first-number extraction) passed. 1/5 strict, $37 (per checkpoint 7, 6, 5, 7, 11), 361 min of wall clock of which about four hours was a laptop suspend during checkpoint 1. 101 registry entries all scored, Risk 0-55 (top: extracted_answer for script and llm_judge 55, tool definitions in a completions prompt 55; the single-task summary shape 45). Quality: erosion 0.209, verbosity 0.242, ast 0.111, cloned 0.095 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260908T0648` | same config as the first run | 20/21, 33/34, 49/50, 65/67, 76/79 | complete 2026-09-08; 3 misses: retry exhaustion from checkpoint 1 (the control's miss, which the first run passed), agentic max iterations, dry run; the first run's single-task compatibility, invalid ICL file and TPM gate all passed. 0/5 strict, $30 (per checkpoint 4, 6, 6, 7, 8), 108 min. 114 registry entries all scored, Risk 0-55 (top: tool definitions in a completions prompt 55, multi-turn mistral 50). Quality: erosion 0.210, verbosity 0.197, ast 0.121, cloned 0.070 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260914T2312` | the 444-word no-F prompt on v0, for the six-problem quality-uplift comparison; first of two | 21/21, 32/34, 49/50, 65/67, 75/79 | complete 2026-09-15; 4 misses: first-number extraction (checkpoint 2, back at 5), agentic max iterations, dry run, and the single-task backward-compatibility case min11 also lost; the control's retry exhaustion, invalid ICL file and TPM gate passed. Two above the control, the best rejector score. 1/5 strict (checkpoint 1), $28 (per checkpoint 4, 5, 5, 6, 8), 92 min. 110 entries all scored, Risk 0-45 (tool definitions rendered into the prompt 45; 5xx retry count, meta for an all-failed row 40). Quality: erosion 0.192, verbosity 0.239, ast 0.114, cloned 0.118 |
| min12-ABDJKMN, repeat | `…min12-ABDJKMN/20260915T0516` | same config as the first run | 21/21, 33/34, 49/50, 66/67, 76/79 | complete 2026-09-15; 3 misses: the single-task backward-compatibility case from checkpoint 2 (both min12 runs and both min11 runs), dry run and the TPM gate at checkpoint 5; the first run's first-number extraction and agentic max iterations passed. Three above the control, the best rejector score. 1/5 strict, $28 (per checkpoint 4, 5, 5, 6, 8), 113 min. 100 entries all scored, Risk 10-55 (tool definitions in a completions prompt 55; cost rounding, a permanently failing agentic request 45). Quality: erosion 0.151, verbosity 0.265, ast 0.114, cloned 0.149 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T2129` | min12 plus chunk T, the upstream anti-slop rule list (d902f32); second of the min13 pair, after mvvault | 20/21, 33/34, 49/50, 64/67, 74/79 | complete 2026-09-18; 6 misses: five that at least one other opus-5 run missed (max-retries at 1, first-number extract at 2, agentic max iterations at 4, dry run and tpm gate at 5) plus test_costs at 5, which no other run missed. 0/5 strict, $33, 107 min. Quality: erosion 0.028, verbosity 0.214, ast 0.074, cloned 0.104 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 73/79: six misses, one per checkpoint from 1 on: retry exhaustion, first-number
    extraction, the invalid ICL file, agentic max iterations, then the TPM gate and dry run
    at checkpoint 5.

### just-solve on v0, repeat (2026-09-15)

  - 76/79, three above the control and level with min12's repeat, on three of the control's
    six. Cell: 73 and 76 against min12's 75 and 76; the score gap on rejector is inside the
    bare prompt's own spread. Erosion 0.559 and 0.716 against 0.192 and 0.151.

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
