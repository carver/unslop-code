# Fable 5 dev6 baseline (2026-08-31)

Run dir: `outputs/dev6-fable5/fable-5_2.1.251_high_just-solve/20260830T1602`
Config: claude_code 2.1.251, claude-fable-5, thinking high, just-solve, no turn cap,
timeout 7200, net_cost_limit 200/problem. Subscription auth verified (apiKeySource
none; no ANTHROPIC_* in the claude process env). Same parser patch as the Opus run.
Run was paused twice at problem boundaries to ride out the 5-hour window (before
sith and before xjq); auto-resumed at the resets; the interrupted partial
checkpoints were deleted before each resume, so no truncated results are counted.

## Three models, same six problems, 33 checkpoints

| metric | Sonnet 4.6 (capped, 2.1.44) | Opus 5 | Fable 5 |
|---|---|---|---|
| Strict solve | 6.1% (2) | 12.1% (4) | 12.1% (4) |
| Isolated solve | 9.1% (3) | 24.2% (8) | 27.3% (9) |
| Core solve | 48.5% (16) | 63.6% (21) | 57.6% (19) |
| Mean test pass rate | 0.863 | 0.928 | 0.946 |
| $/ckpt (Claude Code) | 1.78 | 4.41 | 5.31 |
| $/ckpt at Sonnet prices | 1.60 | 2.45 | 1.45 |
| steps/ckpt | 38.8 | 38.5 | 19.9 |
| min/ckpt | 11.0 | 15.4 | 9.9 |
| erosion | 0.798 | 0.589 | 0.699 |
| verbosity | 0.484 | 0.306 | 0.312 |
| ast-grep flagged | 0.417 | 0.270 | 0.268 |
| cloned | 0.088 | 0.030 | 0.043 |
| 7-day window points | ~8 | ~9 | ~22 |

Per problem (strict/iso/core of n, $):

| problem | diff | Sonnet | Opus 5 | Fable 5 |
|---|---|---|---|---|
| datagate | Easy | 0/1/5 of 7, 3.83 | 0/1/4 of 7, 14.48 | 0/2/4 of 7, 15.43 |
| file_merger | Medium | 0/0/1 of 4, 6.15 | 1/2/2 of 4, 25.82 | 1/2/2 of 4, 21.44 |
| mvvault | Medium | 0/0/3 of 6, 7.93 | 1/2/6 of 6, 11.82 | 0/1/4 of 6, 17.61 |
| rejector | Hard | 1/1/3 of 5, 11.67 | 0/1/2 of 5, 35.55 | 1/1/1 of 5, 32.23 |
| sith | Hard | 0/0/1 of 6, 26.31 | 1/1/3 of 6, 51.77 | 1/1/3 of 6, 80.97 |
| xjq | Easy | 1/1/3 of 5, 2.93 | 1/1/4 of 5, 6.13 | 1/2/5 of 5, 7.43 |

## Reading

- Fable has the best isolated rate (27.3%) and mean test pass rate (0.946), with
  half the steps of the other two and the fastest wall clock. Its raw token use
  is the LOWEST of the three (a Sonnet-price recompute of its tokens is
  $1.45/ckpt vs Sonnet's own $1.60); the $5.31/ckpt is purely list price
  ($10/$50 per M vs $3/$15).
- The strict/iso gap is wide open on every model (Fable: 9 iso, 4 strict).
  Whatever skill closes regressions has headroom on all three.
- Fable's best-of-three final snapshots on the two Hard problems (sith 204/228,
  rejector's strict ckpt 1) coexist with the same failure signature as Opus:
  a small number of early misreadings carried forward (mvvault ckpt 6 missed
  strict by one test; rejector core 1/5 despite high pass rates).
- Rate-limit accounting is NOT token-only after all: Fable's ~22 weekly points
  for fewer tokens than Sonnet's ~8-point run implies a per-model weighting
  (roughly 3x for Fable). A full-36 Fable seed extrapolates to ~$1,040 list
  and ~130 weekly points: more than a weekly window comfortably allows
  alongside anything else. Dev-set-sized Fable experiments are fine; full
  holdout seeds on Fable need a dedicated week or a different plan.
- 5-hour windows cap Fable throughput at roughly 4h of benchmark work per
  window; the pause/auto-resume pattern (stop at a problem boundary, delete
  any partial checkpoint, resume after reset) worked twice without losing data.

Amendment 2026-09-08: mvvault's checkpoint 6 re-scored with the earlier checkpoints' tests
included. Upstream's config runs only checkpoint 6's own 42 tests there (an omission; the
reference solution passes all 185 earlier ones, see `notes/upstream-prs.md`), which made the
last checkpoint "strict" for every model while the misses carried from earlier checkpoints
were never run. Corrected checkpoint-6 totals, by `bin/reeval` on the existing snapshots
(the upstream-config evaluation is kept beside each as `before-prior-tests`): Opus 5
221/227, Fable 5.1 220/227, Fable 5 213/227, Sonnet 4.6 206/227. Each model's mvvault strict
count drops from 1 to 0 of 6; `notes/results.md` is regenerated from the corrected rows.
