# Spectest run ledger (mvvault, Opus 5, Claude Code 2.1.251, thinking high)

Every mvvault run under `outputs/spectest/`, what changed, and how it ended, in the shape of
`spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; mvvault has six
checkpoints and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`.
The control is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

Checkpoint 6 scores here include the earlier checkpoints' tests (227 in all). Upstream's
config runs only checkpoint 6's own 42 there, an omission patched in our cache since
2026-09-08 (`notes/upstream-prs.md`); the control's checkpoint 6 was re-scored on its
existing snapshot with `bin/reeval`, and every later run scores it that way natively.

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 35/37, 64/67, 110/115, 149/155, 179/185, 221/227 | complete (dev6 sweep; checkpoint 6 re-scored 2026-09-08, upstream config gave 42/42); 6 misses, 0/6 strict, $12. Quality: erosion 0.472, verbosity 0.318, ast 0.243, cloned 0.044 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T1659` | the 468-word min11 subset (twice strict on datagate v2); first of two | 35/37, 65/67, 112/115, 150/155, 180/185, 222/227 | complete 2026-09-08; 5 misses, four shared with the control (the two checkpoint-1 sync rejections, missing tracked field and wrong field type; skip-downloaded candidate; serve on a custom address) and one its own (the missing-vault route error from checkpoint 4); the control's two sync-v1 misses passed. 0/6 strict, $36 (per checkpoint 4, 6, 6, 8, 5, 6), 152 min of agent time; checkpoint 4 hit the spurious infra flag (two collection passes failed in a network blip, evaluation complete at 150/155; flag cleared by hand, backup beside it) and the run resumed from 5 as job 89. 80 registry entries all scored, Risk 0-55 (top: digest output shape 55, a static field whose source value changes 45; a source response missing a category 35). Quality: erosion 0.059, verbosity 0.179, ast 0.067, cloned 0.083 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 221/227: the two checkpoint-1 sync rejections (a source entry missing a tracked field,
    one with a wrong field type), two sync-v1 cases (new entries in v3 shape, download URL),
    skip-downloaded candidate, serve on a custom address. Under upstream's config the last
    checkpoint hid all six.

### min11-ABDFJKMN

  - first run (222): one better than the control. The two sync rejections and two of the
    later misses are the control's; the sync-v1 pair passed; the missing-vault route error
    is new. Erosion 0.059 against the control's 0.472.
