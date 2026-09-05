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
| file_merger | Medium | 1/2/2 of 4, 25.82 | 1/2/2 of 4, 21.44 | | |
| mvvault | Medium | 1/2/6 of 6, 11.82 | 0/1/4 of 6, 17.61 | | |
| rejector | Hard | 0/1/2 of 5, 35.55 | 1/1/1 of 5, 32.23 | | |
| sith | Hard | 1/1/3 of 6, 51.77 | 1/1/3 of 6, 80.97 | | |

## Notes per problem

- xjq: identical to Fable 5 at every checkpoint, 23/23, 50/51, 94/96, 120/122, 164/167,
  with the same three failing tests (whitespace-only text to empty output, an empty JSON
  string preserving its element, redundant text extraction over mixed pipe paths), at a
  fifth of the cost and twelve minutes of agent time. Quality better on every metric:
  erosion 0.532 against 0.684, verbosity 0.364 against 0.487, ast-grep 0.346 against 0.466.
