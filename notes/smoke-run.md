# Step 5 smoke run: file_backup (2026-08-29)

Run dir: `outputs/smoke/sonnet-4.6_2.1.44_high_just-solve/20260829T1810/`
Config: `configs/runs/smoke-file_backup.yaml` (claude_code 2.1.44, claude-sonnet-4-6,
thinking high = MAX_THINKING_TOKENS 31999 + CLAUDE_CODE_EFFORT_LEVEL high, just-solve,
docker-python3.12-uv, pass_policy any, step_limit 100, cost_limit 20, timeout 3600).
Auth: subscription (setup-token). Checked while running: container base env and the
`claude` process env (/proc/<pid>/environ) had no ANTHROPIC_API_KEY and no sk-ant-api string.

## Per checkpoint

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

Test groups per checkpoint (passed/total):

| ckpt | core | functionality | error | regression |
|---|---|---|---|---|
| 1 | 1/1 | 23/27 | 4/4 | 0/0 |
| 2 | 1/1 | 9/17 | 0/0 | 28/32 |
| 3 | 1/1 | 11/17 | 0/0 | 38/50 |
| 4 | 1/1 | 16/20 | 0/0 | 50/68 |

Strict and isolated solve require every test in scope to pass; the agent
passed the single core test at every checkpoint but never all functionality
tests, so strict = iso = 0/4 and core = 4/4.

## Agent behaviour

- init payload every checkpoint: model claude-sonnet-4-6, apiKeySource none,
  claude_code_version 2.1.44, plugins [], mcp_servers [].
- Thinking blocks per checkpoint: 24, 13, 16, 13. Effort high is in effect.
- Checkpoints 2-4 used the Task tool once each, and those sub-agent calls ran
  on claude-haiku-4-5-20251001 (Claude Code's default for Explore-type
  sub-agents). Same harness behaviour as the leaderboard; noted because it is
  why the Claude-Code-reported cost differs slightly from a Sonnet-only
  recomputation.
- Checkpoint 1 wrote to the 5-minute prompt cache; checkpoints 2-4 wrote to
  the 1-hour cache (`ephemeral_1h_input_tokens`), which is priced 2x per
  cache-write token. Claude Code decides this, not us.
- No error payloads, empty stderr, no rate-limit or retry messages.

## Cost and budget

- Claude Code reported $3.06 total, $0.77/ckpt (list_$ from token counts at
  Sonnet 5-minute-cache prices: $2.82, $0.71/ckpt).
- Leaderboard mean is $1.96/ckpt over all 196 checkpoints of mixed
  difficulty; file_backup is Easy with 4 checkpoints, so 0.4x the mean is
  plausible rather than a misconfiguration. Thinking, version and model are
  confirmed from the transcript; the dev6 run (which includes Medium/Hard
  problems) is the real test of the per-checkpoint cost.
- Subscription usage: 5-hour window 8% -> 11% for 4 checkpoints
  (~0.75 points/ckpt at this cost level); 7-day window 2% -> 2%.
- Wall time 22.4 min, 5.6 min/ckpt.

## Quality metrics

Computed with scb-check 0.1.3 via `bin/scbcheck` (per checkpoint) and
`slop-code metrics static` (aggregate; it only stores these in result.json).
Means: erosion 0.778 (leaderboard 0.741), verbosity 0.066 (0.316),
ast-grep flagged 0.045 (0.298), cloned 0.014 (0.093).

Caveat: the leaderboard was published with repo v0.3 (2026-04-21). Since then
the metrics code moved to scb-check for composites and pinned 0.1.3 while
removing legacy quality rules (commits 3bf49df, 8e3a8b6). Unless the
leaderboard numbers were recomputed with the same scb-check release, its
erosion/verbosity/ast/cloned columns are not on the same scale as ours. Solve
rates and cost are unaffected.

## Issues hit

- `uvx` missing on the host: static metrics silently produced no composite
  scores on the first pass. Fixed with a shim (see credential-setup.md).
- `slop-code metrics static` does not write per-checkpoint scb-check values
  into checkpoint_results.jsonl, only the aggregate into result.json; hence
  `bin/scbcheck`.
