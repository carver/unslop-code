# Opus 5 dev6 baseline (2026-08-30)

Run dir: `outputs/dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354`
Config: claude_code 2.1.251 (current CLI), claude-opus-5, thinking high, just-solve,
docker-python3.12-uv, step_limit 0 (no turn cap), timeout 7200, net_cost_limit 60/problem.
Subscription auth verified (apiKeySource none; no ANTHROPIC_* in the claude process env,
checked live). One benchmark patch applied first:
patches/claude-code-stream-parser-string-message.patch.

## Headline vs the Sonnet 4.6 dev6 control (same 6 problems, 33 checkpoints)

| metric | Sonnet 4.6 (capped, 2.1.44) | Opus 5 (uncapped, 2.1.251) |
|---|---|---|
| Strict solve | 6.1% (2/33) | 12.1% (4/33) |
| Isolated solve | 9.1% (3/33) | 24.2% (8/33) |
| Core solve | 48.5% (16/33) | 63.6% (21/33) |
| $/ckpt (Claude Code) | 1.78 | 4.41 |
| $/ckpt at Sonnet prices | 1.60 | 2.45 (i.e. ~1.5x the tokens, 2.5x the dollars) |
| min/ckpt | 11.0 | 15.4 |
| erosion | 0.798 | 0.589 |
| verbosity | 0.484 | 0.306 |
| ast-grep flagged | 0.417 | 0.270 |
| cloned | 0.088 | 0.030 |
| 7-day window points | 8 | ~9 |

Per problem (strict/iso/core of n, cost):

| problem | diff | Sonnet | Opus 5 |
|---|---|---|---|
| datagate | Easy | 0/1/5 of 7, $3.83 | 0/1/4 of 7, $14.48 |
| file_merger | Medium | 0/0/1 of 4, $6.15 | 1/2/2 of 4, $25.82 |
| mvvault | Medium | 0/0/3 of 6, $7.93 | 1/2/6 of 6, $11.82 |
| rejector | Hard | 1/1/3 of 5, $11.67 | 0/1/2 of 5, $35.55 |
| sith | Hard | 0/0/1 of 6, $26.31 | 1/1/3 of 6, $51.77 |
| xjq | Easy | 1/1/3 of 5, $2.93 | 1/1/4 of 5, $6.13 |

## Confounds - this is NOT a clean model-only comparison

1. Turn cap: Sonnet ran with `--max-turns 100` and hit it on 4 checkpoints
   (rejector 5, sith 1/3/4); Opus ran uncapped and spent up to $18/136 steps
   on single checkpoints. Some of Opus's lift on sith is plausibly cap
   removal, not the model.
2. CLI version: Sonnet on 2.1.44 (1 bundled skill), Opus on 2.1.251
   (17 bundled skills incl. code-review/simplify/verify, auto-memory
   enabled in the container). Harness behaviour differs.
3. Single run each; strict/iso counts are single-digit events.

A Sonnet 4.6 re-run on the new config (uncapped, 2.1.251) is the clean
control if the model-vs-model number matters.

## Reading of the results

- Isolated solve went 9.1% -> 24.2%: the direction the experiment cares
  about, but 3/33 vs 8/33 alone is within noise (Fisher two-sided p ~ 0.19).
  Combined with core +5 and strict +2 and uniformly better quality scores,
  the lift is probably real; its size is not pinned down.
- Quality: Opus's erosion 0.589 / verbosity 0.306 / cloned 0.030 beat
  Sonnet's on every column, and its final sith snapshot passed 191/228 tests
  vs Sonnet's 115/228.
- datagate is the counterexample: Opus lost core 4/7 vs 5/7 because one
  over-strict delimiter heuristic at checkpoint 1 (rejects single-column
  CSVs; `_score()` in its datagate.py) 400s six tests forever after. The
  regression mechanism is model-independent.
- rejector is the other loss (0/1/2 vs 1/1/3): worth the same
  bin/failures dig before drawing conclusions.

## Budget notes

- $145.56 list-price (Claude Code accounting) for 33 checkpoints; ~9 points
  of the 7-day window. Weekly accounting tracks tokens more than dollars:
  Sonnet's $58.81 also cost ~8 points. An Opus full-36 run extrapolates to
  ~$860 list but roughly the same ~55 weekly points as a Sonnet run.
- net_cost_limit 60/problem nearly bound on sith ($51.77); raise to ~100
  for Opus-class runs.

## Incidents during the run (all documented in credential-setup.md)

1. Benchmark parser crash on 2.1.251 stream payloads (patched).
2. A host-side `uv run` rebuilt `slop-code-bench/.venv` mid-run and killed
   the worker (BrokenProcessPool); benchmark commands now use a
   sandbox-local venv via UV_PROJECT_ENVIRONMENT.
3. Killed checkpoints get recorded as clean completions; two truncated
   mvvault checkpoints were deleted before resuming.
4. file_merger's four rows carry `state: unknown` in checkpoint_results.jsonl
   because its stale run_info.yaml (from the crashed first attempt) was set
   aside; pass rates and costs are correct.
