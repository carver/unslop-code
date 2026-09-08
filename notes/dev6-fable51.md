# Fable 5.1 dev baseline, five problems (2026-09-05)

Just-solve on the five non-datagate dev problems, unpatched catalog specs, one run each,
queued between the two v9 runs to use Fable credits before a usage reset. Same agent
config as the Fable 5 baseline (claude_code 2.1.251, thinking high, timeout 7200,
net_cost_limit 200) with model `fable-5-1` (`configs/models/fable-5-1.yaml`, copied into
the slop-code registry). Configs `configs/runs/dev6-fable51-<problem>.yaml`; outputs under
`outputs/dev6-fable51/fable-5-1_2.1.251_high_just-solve/`. Cells read strict/isolated/core
checkpoints of N, then Claude Code's cost in dollars, as in `dev6-fable5.md`, whose Opus 5
and Fable 5 columns are copied here for comparison.

| problem | diff | Opus 5 | Fable 5 | Fable 5.1 | agent min |
|---|---|---|---|---|---|
| xjq | Easy | 1/1/4 of 5, 6.13 | 1/2/5 of 5, 7.43 | 1/2/5 of 5, 1.49 | 12 |
| file_merger | Medium | 1/2/2 of 4, 25.82 | 1/2/2 of 4, 21.44 | 0/1/2 of 4, 3.28 | 34 |
| mvvault | Medium | 1/2/6 of 6, 11.82 | 0/1/4 of 6, 17.61 | 0/2/5 of 6, 5.57 | 54 |
| rejector | Hard | 0/1/2 of 5, 35.55 | 1/1/1 of 5, 32.23 | 1/1/2 of 5, 8.48 | 87 |
| sith | Hard | 1/1/3 of 6, 51.77 | 1/1/3 of 6, 80.97 | 1/1/4 of 6, 20.14 | 167 |

## Totals over the five problems, 26 checkpoints

| | Opus 5 | Fable 5 | Fable 5.1 |
|---|---|---|---|
| strict checkpoints | 4 | 4 | 3 |
| isolated | 7 | 7 | 7 |
| core | 17 | 15 | 18 |
| Claude Code cost | $131 | $160 | $39 |

Fable 5.1 passes more tests than Fable 5 on four problems and is level on xjq; it has one
strict checkpoint fewer, the file_merger boolean case missed at checkpoint 1 and carried. It
costs a quarter of Fable 5 and less than a third of Opus 5 on the same problems, and its
quality metrics are better on four of five (rejector the exception). Fable 5.1 reads as
Fable 5 with the same spec readings, faster and cheaper; the misses it shares with Fable 5
are candidates for spec patches in the datagate sense.

## Notes per problem

- xjq: identical to Fable 5 at every checkpoint, 23/23, 50/51, 94/96, 120/122, 164/167,
  with the same three failing tests (whitespace-only text to empty output, an empty JSON
  string preserving its element, redundant text extraction over mixed pipe paths), at a
  fifth of the cost and twelve minutes of agent time. Quality better on every metric:
  erosion 0.532 against 0.684, verbosity 0.364 against 0.487, ast-grep 0.346 against 0.466.
- file_merger: more tests than Fable 5 at every checkpoint after the first, 45/46, 83/86,
  101/104, 138/147 against 46/46, 75/86, 93/104, 129/147, but one strict checkpoint fewer:
  a strict-mode error case (a nonstandard boolean accepted, exit 0 where the test wants a
  failure) missed at checkpoint 1 and carried through all four. At checkpoint 4 the nine
  misses are seven shared with Fable 5 plus that one and a map-lookup error case; Fable 5
  had eighteen. Cost $3.28 against $21.44. Quality a little better on every metric.
- mvvault: identical to Fable 5 through checkpoint 3 (the same two sync-validation error
  cases, then the same skip-downloaded-candidate miss), then ahead: 151/155 and 181/185
  against 150 and 172, passing the chart payload and media-view cases Fable 5 lost at
  checkpoint 5. The final checkpoint is a fresh 42-test suite where 5.1 lost 39/42 to Fable
  5's 41/42: both miss POST create, 5.1 also fails two atomic-migration error cases. No
  strict checkpoint for either; isolated 2 and core 5 of 6 against 1 and 4. Cost $5.57
  against $17.61. Erosion 0.222 against 0.739, the largest quality gap of the three so far.
- rejector: strict at checkpoint 1 like Fable 5, then one test behind it at every later
  checkpoint, 46/50, 62/67, 73/79 against 47, 64, 74. The extra misses are in-context
  learning (round-robin example strategy, an invalid ICL file that must fail before any API
  call) and the agentic max-iterations limit; Fable 5's own extra miss was the judge-pass
  case. Core 2 of 5 against 1. Cost $8.48 against $32.23, 87 minutes of agent time. The one
  problem so far where quality is worse: erosion 0.639 against 0.576, verbosity 0.410
  against 0.278.
- sith: strict at checkpoint 1 like Fable 5, then ahead at every checkpoint, 74/75, 106/108,
  139/146, 177/186, 210/228 against 73, 105, 138, 170, 204. The run was paused asleep before
  checkpoint 5 to let an Opus run use the window, and resumed with `bin/queue resume`; the
  resume added nothing to the record beyond a two-hour gap. Final misses 18 against 24, 13
  shared; 5.1's own are environment listing and sorting cases and an extract-variable pair.
  Core 4 of 6 against 3. Cost $20.14 against $80.97, 167 minutes of agent time. Erosion 0.757
  against 0.854.

Amendment 2026-09-08: mvvault's checkpoint 6 re-scored with the earlier checkpoints' tests
included. Upstream's config runs only checkpoint 6's own 42 tests there (an omission; the
reference solution passes all 185 earlier ones, see `notes/upstream-prs.md`), which made the
last checkpoint "strict" for every model while the misses carried from earlier checkpoints
were never run. Corrected checkpoint-6 totals, by `bin/reeval` on the existing snapshots
(the upstream-config evaluation is kept beside each as `before-prior-tests`): Opus 5
221/227, Fable 5.1 220/227, Fable 5 213/227, Sonnet 4.6 206/227. Each model's mvvault strict
count drops from 1 to 0 of 6; `notes/results.md` is regenerated from the corrected rows.
