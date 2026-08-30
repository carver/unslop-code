# SlopCodeBench baseline reproduction (Phase 0)

Control run of the unmodified benchmark against the leaderboard row
"Sonnet 4.6 / Claude Code 2.1.44 / thinking high", on a Claude Max 20x
subscription. No skills, prompts, CLAUDE.md files or harness changes were
added to the agent's workspace. The only change to how the benchmark runs is
the credential path (subscription OAuth token instead of an API key), and
that needed no code edits in the benchmark repo.

## Manifest

| field | value |
|---|---|
| slop-code-bench commit | 06b5c0687d4c05ee502e9696a4d0c22fc1eec5e0 (main, 2026-08-04, "Forgot sonnet 5"; 12 commits after tag v0.3) |
| scb-problems | v1.0, commit 4d38d300059667d57e43c31969bc455f5c338b52, 36 problems / 196 checkpoints |
| agent | claude_code, version 2.1.44 (npm @anthropic-ai/claude-code@2.1.44), image slop-code:claude_code-2.1.44-python3.12 |
| model string | claude-sonnet-4-6 (catalog name sonnet-4.6, provider claude_code_oauth) |
| thinking | high (MAX_THINKING_TOKENS=31999, CLAUDE_CODE_EFFORT_LEVEL=high, alwaysThinkingEnabled) |
| prompt | configs/prompts/just-solve.jinja (unmodified) |
| environment | configs/environments/docker-python3.12-uv.yaml (unmodified) |
| agent config | configs/agents/claude_code-2.1.44.yaml: repo default plus version 2.1.44, timeout 3600 s/ckpt, cost_limit 20 $/ckpt, step_limit 100 (repo default; see "Turn cap" below) |
| pass_policy | any (run default); solve rates below use the eval's all-tests definitions |
| auth mode | subscription: CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`, injected by the existing `claude_code_oauth` provider; `apiKeySource: none` in every transcript; no ANTHROPIC_API_KEY in any container or claude process env (checked live during both runs) |
| credential change | none in the benchmark repo; wrapper `bin/scb` + run configs with `model.provider: claude_code_oauth` (notes/credential-setup.md) |
| host fixes | `uvx` shim at ~/.local/bin/uvx (uv 0.9.26 shipped without it); needed by `slop-code metrics static` |
| dates | smoke 2026-08-29 18:10-18:34 PDT; dev6 2026-08-29 19:10 to 2026-08-30 01:14 PDT |
| runs | smoke: outputs/smoke/sonnet-4.6_2.1.44_high_just-solve/20260829T1810 (file_backup); dev6: outputs/dev6/sonnet-4.6_2.1.44_high_just-solve/20260829T1910 |
| total tokens (dev6) | input 9,056; output 1,282,985; cache read 84,204,034; cache write 2,186,494 (87.7M total) |
| total tokens (smoke) | input 536; output 83,742; cache read 2,758,267; cache write 196,383 (3.0M) |
| cost at list price | dev6 $58.81 as reported by Claude Code ($52.73 recomputed at Sonnet 5-minute-cache prices); smoke $3.06 |
| subscription usage | dev6: 7-day window 2% -> 10%; 5-hour window peaked at 35% (during sith), reset twice mid-run. Smoke: 5-hour 8% -> 11% |
| substitutions | none. Sonnet 4.6 is available on the subscription |
| scb-check | 0.1.3 (repo pin) for erosion / verbosity / ast-grep / cloned |
| seed | slop-code default 42; problem split seed 20260829 |
| config change after this run | 2026-08-30: agent config now has `step_limit: 0` (no turn cap), `timeout: 7200`, `net_cost_limit: 60`; the dev6 run above used `step_limit: 100`, `timeout: 3600`, `net_cost_limit: 0` (saved verbatim in the run dir's config.yaml). Future control and treatment runs use the new file, so the run above is a capped reference, not seed 1 of the noise estimate |

## Headline comparison (dev6 subset vs. leaderboard 36-problem aggregate)

| metric | dev6 (6 problems, 33 ckpts) | leaderboard (36 problems, 196 ckpts) | paper v2 Table 1 |
|---|---|---|---|
| Strict solve | 6.06% (2/33) | 7.14% (14/196) | 7.1 |
| Isolated solve | 9.09% (3/33) | 16.84% (33/196) | 16.8 |
| Core solve | 48.48% (16/33) | 56.12% (110/196) | 57.7 |
| $/checkpoint | 1.78 (std 1.74) | 1.96 | 1.96 +/- 1.97 |
| min/checkpoint | 11.0 | n/a | 14.2 +/- 14.2 |
| Erosion | 0.798 | 0.741 | 0.75 +/- 0.20 |
| Verbosity | 0.484 | 0.316 | 0.44 +/- 0.19 |
| % AST-grep flagged | 0.417 | 0.298 | n/a |
| % Cloned | 0.088 | 0.093 | n/a |

Subset caveat: no per-problem leaderboard results are published (checked the
snorkel.ai and scbench.ai payloads, the problems site, and the paper's Tables
1 and 8; see notes/leaderboard-reference.md), so the right-hand columns are
36-problem aggregates and the left is a 6-problem sample. With n = 33, a
binomial 95% interval around the leaderboard's 16.8% iso rate is roughly
4% to 30%, and around 56.1% core it is roughly 39% to 73%. Every solve-rate
difference above sits inside those intervals. Cost per checkpoint lands
within 10% of the leaderboard, and the difficulty-weighted extrapolation of
this run to 196 checkpoints ($367, below) is within 5% of the paper's net
$383.83 for the same row.

Quality caveat: the leaderboard's verbosity (0.316) disagrees with the
paper's own value for the same row (0.44), and the repo switched its
composite metrics to scb-check after the v0.3 release the paper used. Our
0.484 verbosity is close to the paper's 0.44 and far from the leaderboard's
0.316; erosion is close to both. Treat erosion as comparable and verbosity /
ast-grep as "same ballpark, unknown scale" until the leaderboard's scb-check
release is known.

## Per-problem results (dev6)

| problem | difficulty | ckpts | strict | iso | core | cost $ | $/ckpt | min/ckpt | steps/ckpt | turn-capped ckpts |
|---|---|---|---|---|---|---|---|---|---|---|
| datagate | Easy | 7 | 0 | 1 | 5 | 3.83 | 0.55 | 4.3 | 19 | 0 |
| file_merger | Medium | 4 | 0 | 0 | 1 | 6.15 | 1.54 | 11.4 | 35 | 0 |
| mvvault | Medium | 6 | 0 | 0 | 3 | 7.93 | 1.32 | 8.9 | 31 | 0 |
| rejector | Hard | 5 | 1 | 1 | 3 | 11.67 | 2.33 | 14.9 | 37 | 1 |
| sith | Hard | 6 | 0 | 0 | 1 | 26.31 | 4.38 | 22.4 | 89 | 3 |
| xjq | Easy | 5 | 1 | 1 | 3 | 2.93 | 0.59 | 5.0 | 19 | 0 |
| all | 2E/2M/2H | 33 | 2 | 3 | 16 | 58.81 | 1.78 | 11.0 | 39 | 4 |

Mean $/checkpoint by difficulty: Easy 0.56, Medium 1.41, Hard 3.45.

## Per-checkpoint results (dev6)

Columns: strict / iso / core = solved under that definition; core_pr = core
pass rate; cc_$ = cost as reported by Claude Code; list_$ = recomputed from
tokens at Sonnet list price; erosion / verbosity / ast% / cloned% from
scb-check 0.1.3 on the checkpoint snapshot.

problem | ckpt | state | strict | iso | core | core_pr | steps | in | out | cache_r | cache_w | cc_$ | list_$ | elapsed_s | erosion | verbosity | ast% | cloned%
---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---
datagate | 1 | ran | n | n | Y | 1.00 | 13 | 106 | 43 | 312918 | 13451 | 0.14 | 0.15 | 144 | 0.807 | 0.503 | 0.466 | 0.000
datagate | 2 | ran | n | n | n | 0.78 | 13 | 90 | 9793 | 311045 | 18600 | 0.36 | 0.31 | 172 | 0.887 | 0.408 | 0.383 | 0.000
datagate | 3 | ran | n | n | Y | 1.00 | 18 | 114 | 13096 | 435115 | 22565 | 0.46 | 0.41 | 200 | 0.946 | 0.765 | 0.746 | 0.031
datagate | 4 | ran | n | n | n | 0.92 | 24 | 162 | 23816 | 953077 | 42122 | 0.86 | 0.80 | 378 | 0.869 | 0.497 | 0.472 | 0.000
datagate | 5 | ran | n | n | Y | 1.00 | 26 | 138 | 9453 | 584782 | 24968 | 0.54 | 0.41 | 216 | 0.864 | 0.482 | 0.459 | 0.000
datagate | 6 | ran | n | Y | Y | 1.00 | 20 | 82 | 26620 | 450479 | 51419 | 0.83 | 0.73 | 422 | 0.835 | 0.465 | 0.444 | 0.025
datagate | 7 | ran | n | n | Y | 1.00 | 21 | 146 | 13302 | 768385 | 35468 | 0.64 | 0.56 | 282 | 0.861 | 0.449 | 0.429 | 0.023
file_merger | 1 | ran | n | n | n | 0.89 | 31 | 250 | 48182 | 1676591 | 55285 | 1.48 | 1.43 | 783 | 0.602 | 0.256 | 0.208 | 0.060
file_merger | 2 | ran | n | n | n | 0.91 | 27 | 186 | 40470 | 1589283 | 72454 | 1.45 | 1.36 | 649 | 0.687 | 0.420 | 0.380 | 0.091
file_merger | 3 | ran | n | n | Y | 1.00 | 44 | 338 | 25009 | 2472658 | 54854 | 1.40 | 1.32 | 431 | 0.696 | 0.409 | 0.371 | 0.097
file_merger | 4 | ran | n | n | n | 0.58 | 39 | 138 | 52842 | 1309210 | 85396 | 1.82 | 1.51 | 873 | 0.742 | 0.462 | 0.422 | 0.104
mvvault | 1 | ran | n | n | n | 0.75 | 19 | 154 | 26150 | 740074 | 33957 | 0.76 | 0.74 | 411 | 0.802 | 0.307 | 0.268 | 0.000
mvvault | 2 | ran | n | n | n | 0.80 | 11 | 90 | 25067 | 466081 | 42732 | 0.70 | 0.68 | 358 | 0.703 | 0.613 | 0.560 | 0.117
mvvault | 3 | ran | n | n | Y | 1.00 | 51 | 410 | 53622 | 4447473 | 92322 | 2.52 | 2.49 | 885 | 0.578 | 0.451 | 0.360 | 0.131
mvvault | 4 | ran | n | n | n | 0.91 | 37 | 250 | 36461 | 1786319 | 59359 | 1.45 | 1.31 | 600 | 0.604 | 0.374 | 0.279 | 0.122
mvvault | 5 | ran | n | n | Y | 1.00 | 29 | 178 | 21459 | 1262093 | 56977 | 1.05 | 0.91 | 375 | 0.614 | 0.357 | 0.267 | 0.120
mvvault | 6 | ran | n | n | Y | 1.00 | 40 | 266 | 33285 | 1851503 | 59457 | 1.44 | 1.28 | 562 | 0.709 | 0.539 | 0.473 | 0.162
rejector | 1 | ran | Y | Y | Y | 1.00 | 17 | 82 | 29250 | 457969 | 43738 | 1.00 | 0.74 | 446 | 0.403 | 0.279 | 0.183 | 0.094
rejector | 2 | ran | n | n | n | 0.80 | 28 | 178 | 44367 | 1511421 | 71936 | 1.48 | 1.39 | 723 | 0.728 | 0.340 | 0.218 | 0.121
rejector | 3 | ran | n | n | Y | 1.00 | 16 | 106 | 36368 | 779445 | 74135 | 1.15 | 1.06 | 549 | 0.867 | 0.373 | 0.221 | 0.184
rejector | 4 | ran | n | n | n | 0.90 | 23 | 170 | 49450 | 1956168 | 108819 | 1.84 | 1.74 | 734 | 0.871 | 0.347 | 0.230 | 0.147
rejector | 5 | ran | n | n | Y | 1.00 | 103 | 804 | 120385 | 9366888 | 189341 | 6.19 | 5.33 | 2017 | 0.865 | 0.295 | 0.188 | 0.136
sith | 1 | ran | n | n | Y | 1.00 | 116 | 802 | 61462 | 7258889 | 98390 | 4.13 | 3.47 | 1192 | 0.769 | 0.464 | 0.420 | 0.090
sith | 2 | ran | n | n | n | 0.00 | 72 | 554 | 85279 | 7526113 | 127634 | 4.16 | 4.02 | 1348 | 0.879 | 0.595 | 0.477 | 0.194
sith | 3 | ran | n | n | n | 0.33 | 107 | 804 | 101369 | 11125068 | 164247 | 6.52 | 5.48 | 2025 | 0.869 | 0.564 | 0.460 | 0.181
sith | 4 | ran | n | n | n | 0.64 | 107 | 804 | 107498 | 10322335 | 175572 | 6.17 | 5.37 | 1788 | 0.874 | 0.487 | 0.377 | 0.172
sith | 5 | ran | n | n | n | 0.14 | 62 | 458 | 63742 | 4542364 | 88879 | 2.85 | 2.65 | 1021 | 0.870 | 0.476 | 0.347 | 0.184
sith | 6 | ran | n | n | n | 0.71 | 71 | 514 | 39780 | 4813737 | 82437 | 2.48 | 2.35 | 699 | 0.866 | 0.511 | 0.397 | 0.187
xjq | 1 | ran | Y | Y | Y | 1.00 | 15 | 122 | 11971 | 400055 | 16295 | 0.37 | 0.36 | 206 | 0.995 | 0.940 | 0.916 | 0.000
xjq | 2 | ran | n | n | n | 0.92 | 20 | 130 | 21320 | 568874 | 28280 | 0.64 | 0.60 | 359 | 0.943 | 0.698 | 0.687 | 0.000
xjq | 3 | ran | n | n | Y | 1.00 | 14 | 114 | 13550 | 452619 | 23575 | 0.44 | 0.43 | 227 | 0.895 | 0.564 | 0.504 | 0.045
xjq | 4 | ran | n | n | Y | 1.00 | 21 | 130 | 14117 | 570162 | 27253 | 0.54 | 0.49 | 251 | 0.923 | 0.624 | 0.572 | 0.039
xjq | 5 | ran | n | n | n | 0.89 | 26 | 186 | 24407 | 1134841 | 44577 | 0.94 | 0.87 | 471 | 0.901 | 0.651 | 0.594 | 0.060

checkpoints: 33  strict 2/33 = 6.06%  iso 3/33 = 9.09%  core 16/33 = 48.48%
tokens: in 9,056 out 1,282,985 cache_read 84,204,034 cache_write 2,186,494
cost as reported by Claude Code (cc_$): $58.81 total, $1.78/ckpt   (leaderboard $1.96/ckpt)
cost at Sonnet list price from token counts (list_$): $52.73 total, $1.60/ckpt
wall time: 363.3 min total, 11.0 min/ckpt; steps/ckpt 38.8
erosion mean 0.798 (target 0.741)  verbosity mean 0.484 (target 0.316)  ast-grep mean 0.417 (target 0.298)  cloned mean 0.088 (target 0.093)

## Smoke run (file_backup, holdout problem, 4 checkpoints)

problem | ckpt | state | strict | iso | core | core_pr | steps | in | out | cache_r | cache_w | cc_$ | list_$ | elapsed_s | erosion | verbosity | ast% | cloned%
---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---
file_backup | 1 | ran | n | n | Y | 1.00 | 24 | 194 | 21735 | 921082 | 47322 | 0.80 | 0.78 | 356 | 0.604 | 0.069 | 0.060 | 0.000
file_backup | 2 | ran | n | n | Y | 1.00 | 14 | 106 | 22616 | 568844 | 60711 | 0.78 | 0.74 | 357 | 0.813 | 0.047 | 0.041 | 0.000
file_backup | 3 | ran | n | n | Y | 1.00 | 20 | 130 | 16795 | 710056 | 39067 | 0.73 | 0.61 | 308 | 0.838 | 0.073 | 0.035 | 0.032
file_backup | 4 | ran | n | n | Y | 1.00 | 17 | 106 | 22596 | 558285 | 49283 | 0.75 | 0.69 | 322 | 0.857 | 0.073 | 0.044 | 0.025

checkpoints: 4  strict 0/4 = 0.00%  iso 0/4 = 0.00%  core 4/4 = 100.00%
tokens: in 536 out 83,742 cache_read 2,758,267 cache_write 196,383
cost as reported by Claude Code (cc_$): $3.06 total, $0.77/ckpt   (leaderboard $1.96/ckpt)
cost at Sonnet list price from token counts (list_$): $2.82 total, $0.71/ckpt
wall time: 22.4 min total, 5.6 min/ckpt; steps/ckpt 18.8
erosion mean 0.778 (target 0.741)  verbosity mean 0.066 (target 0.316)  ast-grep mean 0.045 (target 0.298)  cloned mean 0.014 (target 0.093)

Test groups: core 1/1 at every checkpoint; functionality 23/27, 9/17, 11/17,
16/20; regression 28/32, 38/50, 50/68 from checkpoint 2 on. Full write-up in
notes/smoke-run.md.

## Things that looked wrong or surprising

1. Turn cap bound on 4 of 33 checkpoints (rejector 5, sith 1, 3, 4): result
   subtype `error_max_turns`, num_turns 101. The repo default
   `step_limit: 100` becomes `--max-turns 100`, but the paper's setup says "no
   turn or cost cap" with a two-hour wall clock. All four were Hard problems
   and each cost $4-6.5 and 20-34 minutes before the cap. The cap lowers cost
   and may lower solve rates relative to the leaderboard on exactly the
   problems where iso/core solves are rarest. The snapshot at the cap was
   still evaluated (three of the four count as core-solved).
2. Agent killed its own harness (datagate checkpoint 1). The agent ran
   `pkill -f "datagate.py start"`. The harness passes the entire prompt as an
   argv of the `claude` process, so the pattern matched Claude Code itself:
   the tool result was "Exit code 144" and the transcript ends with no result
   payload. The runner treated it as a normal end and evaluated the snapshot
   (48/50, core solved, $0.14, 2.4 min). Same harness as the leaderboard, so
   this hazard exists there too; worth remembering when a checkpoint looks
   suspiciously cheap.
3. `uvx` missing on the host silently dropped erosion/verbosity from the
   first run's report ("No such file or directory: 'uvx'" as a warning).
   Fixed with a shim; `bin/scbcheck` writes per-checkpoint reports because
   `metrics static` keeps them only in the aggregate result.json.
4. Haiku sub-agent calls: 26 of 37 checkpoints across both runs include
   `claude-haiku-4-5-20251001` messages (Task tool sub-agents). That is
   Claude Code 2.1.44's own behaviour and part of the leaderboard's cost too;
   it is the main reason Claude Code's reported cost exceeds a Sonnet-only
   recomputation by about 10%.
5. Prompt cache: Claude Code used the 1-hour cache tier for most checkpoints
   (priced 2x per cache-write token). Also its own choice.
6. No rate-limit hits, retries, timeouts, Docker failures or eval
   normalization failures in either run: zero error/warning-level lines in
   run_agent.log apart from the uvx warning, empty stderr on every checkpoint.
7. Holdout hygiene: file_backup fell into the holdout split but was used for
   the smoke run as instructed. Its spec text was not read or summarized;
   the agent's transcript and snapshot exist under outputs/smoke.
8. The leaderboard's quality columns are on an unstated scb-check release
   (see the quality caveat above).

## Extrapolation: full 36-problem run and 3 seeds

Difficulty-weighted from dev6 per-checkpoint means (Easy 67 ckpts, Medium
57, Hard 72 in the v1.0 set):

| quantity | 1 seed (196 ckpts) | 3 seeds |
|---|---|---|
| cost at list price | ~$367 (naive 196/33 scaling: $349; paper net $ for this row: $383.83) | ~$1,100 |
| tokens | ~550M (98% cache reads) | ~1.65B |
| wall time, 1 worker | ~37 h | ~112 h |
| wall time, 2 workers | ~19 h | ~56 h |
| 7-day window (Max 20x) | ~50 points (dev6 used 8 points for $58.81, so ~0.14 points per list-price dollar) | ~150 points, i.e. at least two weekly windows; one seed per week is the comfortable cadence, two per week leaves no headroom for anything else |
| 5-hour window | 1 worker peaked at 35% on a Hard problem; a sequential full run should stay under ~40% per window. 2 workers roughly doubles that, still under 100% but with little margin during Hard stretches | same per window |

Removing the turn cap (recommended below) raises Hard-problem cost; the
capped checkpoints were already the most expensive, so budget an extra
10-20% on top of the numbers above.

## Recommendation

The baseline reproduced well enough to proceed, with two fixes first.

What matched: cost per checkpoint ($1.78 vs $1.96), the extrapolated net
cost ($367 vs $383.83), erosion (0.80 vs 0.74), cloned % (0.088 vs 0.093),
the shape of the results (core solves common, strict solves rare, regressions
accumulating from checkpoint 2 on), model, version, thinking and prompt all
confirmed from transcripts, and subscription auth with zero API-key exposure.
Solve rates are lower than the leaderboard (iso 9.1% vs 16.8%, core 48.5% vs
56.1%) but inside what 33 checkpoints can resolve.

Fix before building anything:

1. Lift the turn cap to match the published setup: `step_limit: 0` (no
   `--max-turns`) and rely on the per-checkpoint `timeout` (raise it to 7200
   to mirror the paper's two-hour limit). Keep `cost_limit: 20` as the
   rate-limit guard. 12% of checkpoints hit the cap, all on Hard problems,
   which is where a skills intervention would most plausibly move iso/core.
2. Measure run-to-run noise on the control before measuring any treatment.
   With strict at 2/33 and iso at 3/33, a skills effect on those columns is
   not measurable on the dev set at all; core (16/33) and the quality scores
   are the only dev-set signals with enough events. Two more dev6 control
   seeds (~$59, ~6 h, ~8 weekly points each) give a variance estimate; the
   holdout (30 problems, 163 checkpoints) is where strict/iso can be judged,
   at ~$310 and ~31 h per seed.

Also worth deciding now: whether to re-draw the split so file_backup lands
in dev (it is already burned), and whether the primary outcome for the
skills experiment is core solve + erosion/verbosity rather than strict.
