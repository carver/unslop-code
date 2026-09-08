# Spectest run ledger (file_merger, Opus 5, Claude Code 2.1.251, thinking high)

Every file_merger run under `outputs/spectest/`, what changed, and how it ended, in the shape
of `spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; file_merger has four
checkpoints and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`.
The control is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 46/46, 69/86, 87/104, 116/147 | complete (dev6 sweep); 31 misses, 1/4 strict, $26. Quality: erosion 0.684, verbosity 0.196, ast 0.169, cloned 0.025 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T0941` | the 468-word min11 subset (twice strict on datagate v2); first of two | 46/46, 75/86, 93/104, 130/147 | complete 2026-09-07; 17 misses, 11 shared with the control (checkpoint 2: consensus type tie, cross-file type inference, five-file and four-format merges, loose JSONL nulls; checkpoint 4: five nested core cases and the unquoted map-lookup error), six its own (the TSV family: empty fields, gzip, whitespace values, unicode, plus auto_mix_union and consensus_inference); the control's twenty parquet misses all passed. 1/4 strict, $29 (per checkpoint 6, 8, 4, 11), 427 min of wall clock of which 314 was a laptop suspend (about 113 active). 78 registry entries all scored, Risk 0-55 (top: keep-string sort position 55, exit-code taxonomy 55, "majority of files" for consensus 55; TSV literal-tab detection 45). Quality: erosion 0.185, verbosity 0.215, ast 0.096, cloned 0.115 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260908T0504` | same config as the first run | 46/46, 75/86, 93/104, 131/147 | complete 2026-09-08; 16 misses, the first run's set minus one (the partition-by-map-value nested core case passed); 1/4 strict, $28 (per checkpoint 5, 9, 5, 9), 98 min. 64 registry entries all scored, Risk 0-55 (top: authoritative precedence order 55, consensus support and majority 50). Quality: erosion 0.243, verbosity 0.214, ast 0.069, cloned 0.133 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 116/147: 31 misses. Twenty are parquet handling from checkpoint 2 on (priority, precision,
    integers, nulls, unicode, the nested-schema cases at checkpoint 4); the rest are the
    mixed-format type-inference cases and the nested core cases it shares with min11.

### min11-ABDFJKMN

  - first run (130): fourteen tests better than the control. Parquet is solved outright.
    What remains is two families: the mixed-format inference questions (consensus ties,
    cross-file inference, four- and five-file merges), which the registry scored high (what
    "majority of files support" means, Risk 55), and a TSV family of its own (empty fields,
    gzip, whitespace values, unicode), with literal-tab detection at Risk 45. The nested core
    cases at checkpoint 4 are shared with the control.
  - repeat (131): the first run's misses test for test, minus one nested core case. The
    mixed-format inference and TSV families are stable readings for this prompt, and the
    registry scores the consensus question at 50 both times. Pair: 130 and 131 against the
    control's 116, $29 and $28.
