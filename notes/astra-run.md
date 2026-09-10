# Astra comparison — 2026-09-07

Status (2026-09-08): runtime ready; Astra model-access smoke test passed. Full benchmark awaits the exact user-requested `min11-ABDFJKMN` prompt. No solve-rate or quality claim yet.

## Primary comparison

| setting | Astra run | reference |
|---|---|---|
| problem | datagate, seven checkpoints | same |
| spec | v2 | same |
| prompt | min9-DEFJKOP, unchanged | same |
| model | gpt-6-astra | opus-5 |
| agent | Codex 0.153.4 | Claude Code 2.1.251 |
| reasoning | high | high |
| per-attempt timeout | 86400 seconds | 86400 seconds |
| retries | 10 | 10 |
| turn cap | none | none |
| checkpoint cost cap | disabled | configured but not enforced for Claude Code |
| problem cost cap | disabled for subscription comparison | reference configured at $100 |
| target final tests | 405/405 | 405/405 |
| target strict | 7/7 | 7/7 |
| target erosion / verbosity | <= .048 / <= .140 | .048 / .140 |
| target AST fraction / cloned fraction | <= .074 / <= .061 | .074 / .061 |

A quality win requires all four means to meet their targets with seven scored checkpoints. Report tradeoffs if only some improve. This is one matched development-problem run, not a holdout solve-rate estimate. Fable's best documented Datagate row uses a different prompt and spec (v1 spectest-v9, 394/405, 0/7); it is contextual, not a matched control.

The model ID and price metadata were checked against [official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-6-astra). Authentication uses the existing Codex subscription file, with API key environment variables removed. Cost outputs are estimates, not subscription charges; cumulative token accounting can make prompt-tier estimates imprecise, so cost is not a win criterion.

## Restored dependencies

- Harness: `slop-code-bench/`, commit `06b5c0687d4c05ee502e9696a4d0c22fc1eec5e0`.
- Catalog source: `outputs/astra-setup/scb-problems/`; only six dev directories checked out from `4d38d300059667d57e43c31969bc455f5c338b52`. The clone's HEAD is newer; the explicit checkout commit above is the source of the working files.
- Built Datagate v2: `specs/v2/problems/datagate/`, original three v2 patches.
- Six original harness patches applied in README order, plus `patches/codex-root-auth-ownership.patch` (dummy-credential regression check passes).
- Python 3.12.14 and the harness's frozen uv lock, no development group. Runtime environment: `outputs/astra-setup/harness-venv`.
- Docker socket: `/tmp/unslop-docker.sock`. Use fuse-overlayfs in this nested container; plain overlay2 failed and vfs exhausted the 8 GB root disk.
- The original run artifacts were not included, so the reference values come from the tracked `notes/results.md` rather than independently recomputed snapshots.

## Launch and artifacts

From the repository root:

```bash
bin/scb-astra run --config configs/runs/min9-DEFJKOP-specv2-datagate-astra.yaml --no-live-progress
```

The dry run succeeded and selected all seven checkpoints. `bin/scb-astra` is the subscription-only wrapper for this model; do not use `bin/scb-extend`, which polls Claude's usage API. Astra runs sequentially through the harness. The solver receives the unchanged prompt and isolated workspace, not the audit notes or hidden tests.

Setup logs are under `outputs/astra-setup/`; actual run directories are under `outputs/spectest/gpt-6-astra_0.153.4_high_min9-DEFJKOP-specv2/`. `notes/results.md` is intentionally preserved while the new-model aggregator and provenance issues in the audit remain unresolved.

Attempt 1 (`20260907T174514`) failed during base-image construction with `BuildError: no space left on device`. No model checkpoint was reached. Its log is `outputs/astra-setup/run-attempt1-image-space.log`. The failed cache was removed from this task's private Docker daemon and the daemon switched to fuse-overlayfs; the benchmark configuration is unchanged.

## Resumption — 2026-09-08

The user changed the requested prompt/reference to `min11-ABDFJKMN`. Do not launch a new min9 run. The exact min11 template/chunk set is not present locally; awaiting its contents or an accessible location. The private GitHub fetch failed because this environment has no Git credentials. The prior primary-comparison table above records the superseded plan, not the current requested comparison.

The second image-build attempt also stopped before model execution: MinIO download failed with curl exit 6 (DNS resolution). Docker has been restarted on the same fuse-overlayfs store and the original base image is being built independently of any prompt. Codex reports a ChatGPT login; the 87 existing tests still pass.

The base image rebuild succeeded on 2026-09-08: `sha256:16cd5579f6f5bbdeb6acdb1c2c1064c40e2b93f60d2a469b78369136eec6dd1a`. The obsolete task-created vfs store was removed; the active fuse-overlayfs store was preserved. Building the Codex 0.153.4 image and verifying model access are independent of the missing min11 prompt.

Codex image `slop-code:codex-0.153.4-python3.12` built successfully. The isolated Astra smoke test exited 0 and returned exactly `READY`, with a `turn.completed` event. Logs: `outputs/astra-setup/astra-smoke-status.txt` and `outputs/astra-setup/astra-smoke-20260908.jsonl`. This validates model access only; no benchmark checkpoint has run.

## Current experiment — 2026-09-09

User selected min12-ABDFJKMN and then Sol as implementing model. Current run: `outputs/spectest/gpt-5.6-sol_0.153.4_high_min12-ABDFJKMN-specv2/20260909T045443`. Launch: `bin/scb-sol run --config configs/runs/min12-ABDFJKMN-specv2-datagate-sol.yaml --no-live-progress`. Log: `outputs/astra-setup/min12-sol-run.log`. Exact prompt preserved. Matched Opus reference: 405/405 tests, 7/7 strict; erosion .047, verbosity .165, AST .072, cloned .074 (two-run means). Provenance and hashes saved to the run's comparison-manifest.json.

The previous min11 Astra run (20260908T081305) is invalid for scoring: root-owned workspace blocked the agent and evaluator; subsequent retry hit subscription usage limits. No valid benchmark result was produced. The earlier READY smoke only tested authentication.

Root ownership fix: `patches/root-workspace-ownership.patch` honors HUID/HGID for the initial empty workspace, consistent with snapshot extraction. Sol wrapper sets HUID/HGID=1000 matching the image agent and evaluator, and adds uvx to PATH for pinned scb-check 0.1.3 scoring. Actual container write/Python execution probe passes; Sol subscription smoke returns READY; 99 repository tests pass. Existing root credential-copy patch remains applied.

Host updates became visible after `mount -o remount /workspace`; dropping kernel caches alone did not work.

## Sol/min12 completed

Run `20260909T045443` finished 2026-09-09 06:16 UTC, approximately 81 minutes wall time. All seven evaluations report infrastructure_failure=false. Final score 402/405; strict checkpoints 5/7. Checkpoints 1–5 pass fully. Three checkpoint-6 functionality failures concerning empty/inactive allowlists persist as regressions in checkpoint 7. Core tests pass at every checkpoint.

Checkpoint-mean quality: erosion 0.282724 versus Opus 0.047; verbosity 0.192960 versus 0.165; cloned fraction 0.044713 versus 0.074. Lower is better. AST flagged fraction 0.141241 versus Opus 0.072. Recovered with the repository summarize.load_rows path and pinned scb-check 0.1.3 on unchanged snapshots; the raw harness JSONL omits this derived field. The initial status report overlooked that postprocessing path. Sol does not match the reference's strict solve rate or erosion/verbosity, but has lower cloning. This is one Sol run against two-run Opus means.

Estimated model list-price cost $10.5828 (subscription authentication, not an actual charge). Source: run checkpoint_results.jsonl and evaluation.json files. Preserve failed cases and snapshots unchanged for diagnosis; no post-evaluation solver fixes included in this score.

AST reporting correction: the harness metric adapter extracts erosion, verbosity and cloning but omits ast_grep_flagged_loc / total_loc. bin/summarize supplies ast_grep_pct separately; bin/results uses that loader. Recovered all seven full scb-check reports and saved quality-comparison.json in the Sol run directory. No model rerun or implementation changes were needed.

## Remaining dev6 run launched

Sol high / unchanged min12-ABDFJKMN on file_merger (4 checkpoints), mvvault (6), rejector (5), sith (6), xjq (5), sequentially. Original v0 catalog specs/configs verified byte-for-byte against 4d38d300059667d57e43c31969bc455f5c338b52. Run: `outputs/spectest/gpt-5.6-sol_0.153.4_high_min12-ABDFJKMN-specv0-dev5/20260909T105122`. Log: `outputs/astra-setup/min12-sol-dev5-run.log`. Launcher: `bin/run-sol-dev5`. Uses explicit catalog override, independent of the host-modified Datagate specs symlinks. Provenance saved in comparison-manifest.json.

## H-only Datagate experiment

User requested min12-ABDFHJKMN; L excluded. Fresh Sol high run from checkpoint 1, same seven Datagate v2 specs as baseline (verified after normal harness rendering), prompt differs by exact H chunk only. Run `outputs/spectest/gpt-5.6-sol_0.153.4_high_min12-ABDFHJKMN-specv2/20260909T111528`; log `outputs/astra-setup/min12-sol-h-run.log`; launcher `bin/run-sol-datagate-h`. No diagnosis or repaired implementation supplied to solver. Dev5 job continues independently. Compare allowlist interpretation, full strict score and all four quality metrics; single-run variation and post-hoc hypothesis selection must be disclosed.

## Queue without usage tracking

User selected queue scheduling without usage polling. bin/queue now selects scb-sol/scb-astra for supported codex_auth configs and sets SCB_USAGE_TRACKING=0; scb-extend honors the launcher for fresh/resumed checkpoints and bypasses usage calls. Existing Claude behavior is preserved. Queue command arguments are shell-quoted. Pueue 4.0.4 installed locally. Existing detached benchmark runs remain in place; future queue jobs should be one problem per config. No predictive quota-reset waiting is available for Codex yet.

## Usage interruption recovery — 2026-09-09

Confirmed Codex usage-limit errors in both Datagate H checkpoint 4 and file_merger checkpoint 4, and startup failures in the other four dev5 problems. Rollout metadata identifies a 300-minute primary window; completed checkpoints 1–3 in both progressing problems have no agent or infrastructure error. No stale benchmark processes or containers remained. Sol access smoke passed after reset.

Archived both complete pre-resume run directories under outputs/backups/usage-interruption-20260909/, including failed attempts. Queue resume now supports --problem for the multi-problem dev5 run; scb-extend limits each resume to the named problem and backup filenames include the problem to avoid collisions. 105 repository tests pass.

User requested all runs sequentially. Pueue default parallelism explicitly set to 1. Jobs 1–6: Datagate H (resume checkpoint 4), file_merger (resume checkpoint 4), mvvault, rejector, sith, xjq (checkpoint 1). Usage polling remains disabled as requested. Harness resume invalidates errored attempts; its dry-run guard protects completed checkpoints before each actual resume.

## Second usage recovery — 2026-09-09 21:20 UTC

Mvvault checkpoint 4 and subsequent startup attempts hit Codex usage limits (retry after 21:04). Datagate H and file_merger are complete. Sandbox daemons had stopped; restarted Docker with the existing fuse-overlayfs store and Pueue initially paused. Sol access smoke passes. Archived dev5 artifacts and original queue state under outputs/backups/usage-interruption-20260909T2117.

Correction to previous queue isolation: upstream --problem merges on resume rather than filtering. Added patches/resume-only-problem.patch: SCB_RESUME_ONLY_PROBLEM filters execution while preserving the saved full problem list. scb-extend sets it for its target. Dry-run checks now show exactly one intended problem each and no completed checkpoint deletions. 105 repository tests pass. Requeued remaining jobs without overwriting old logs, sequential concurrency 1: mvvault checkpoint 4, rejector checkpoint 1, sith checkpoint 1, xjq checkpoint 1. Usage polling remains disabled.

## Usage recovery — 2026-09-10

Confirmed quota errors: rejector checkpoint 2, sith checkpoint 1, xjq checkpoint 1. Error advised retry after Sep 10 02:16. Mvvault finished. Sol access smoke passes. Archived original artifacts under outputs/backups/usage-interruption-20260910; checked all three resume previews preserve completed checkpoints. Restarted jobs 7–9 as new queue tasks, sequential concurrency 1, keeping historical logs.

Reactive quota guard added to scb-extend: on an errored checkpoint with explicit Codex error/turn.failed usage-limit event, pause queue scheduling and exit 6 before driver retry or the next job. No utilization polling or inferred reset time; manual restart after replenishment remains necessary. Failed checkpoint artifacts remain available. 109 repository tests pass.
