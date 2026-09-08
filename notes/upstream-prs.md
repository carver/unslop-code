# Upstream PR candidates

What we have found in the benchmark that belongs upstream, with the evidence and what is
blocking each. Two upstream repos: the harness, `SprocketLab/slop-code-bench` (our checkout
in `slop-code-bench/`, with `patches/` applied), and the problem set,
`gabeorlanski/scb-problems` (cached at `~/.cache/scbench/problems`, v1.0 commit 4d38d30;
patches in `patches/scb-problems/`, applied to the cache by `install.py`).

## Problem set: last checkpoints that drop the earlier tests

Some checkpoints set `include_prior_tests: false`, so their score never runs the earlier
checkpoints' tests and a run carrying misses looks strict for free. The upstream README
says tests for checkpoint N assume all prior checkpoints still pass. For each such
checkpoint we evaluated the upstream reference solution (`solutions/checkpoint_N`) with the
flag on (`bin/scb eval-snapshot` against a patched copy, 2026-09-08). Where the reference
passes every earlier test the flag is an omission; where it fails some, either the flag is
deliberate or the reference solution is wrong, and a PR needs the author's answer first.

| problem | checkpoints with the flag off | reference solution with prior tests on | status |
|---|---|---|---|
| mvvault | 6 (of 6) | 185/185 regression, own tests 42/42 | **ready**: `patches/scb-problems/mvvault-checkpoint-6-prior-tests.patch`, evidence in its preamble; applied to our cache, and every mvvault run's checkpoint 6 re-scored with `bin/reeval` (see `notes/mvvault-runs.md`) |
| l2m | 2, 3, 4, 5 (of 5) | ckpt 2 52/52; ckpts 3-5 each fail the same five checkpoint-1 tests: `test_list_convert[enum_in_itemize, itemize_in_enum, enum_in_itemize_start, formatting_comments, itemize_in_started_enum]` | blocked: checkpoint 3 changes nested-list conversion, so the checkpoint-1 expectations may be superseded on purpose; ask upstream whether those five should be updated or the flag is intended |
| meshctl | 6, 7, 8 (of 8) | each fails one checkpoint-1 test, `test_runtime_zero_version`, everything else passes (266/267, 306/307, 348/349) | blocked on one test: probably a superseded expectation about a zero runtime version; worth asking, since 8 checkpoints of regressions are otherwise clean |
| dynamic_config_service_api | 3, 4 (of 4) | ckpt 4: core 81/81 but regression 113/169, the failures being numbered stateful sequences from the earlier files (create, list, activate, resolve); ckpt 3: core 12/12, functionality 34/34, error 30/30, regression 41/93, the same shape | deliberate: the test files assume a fresh server, so running them together breaks the sequences; not a config omission |
| execution_server | 6 (of 6) | pending | pending |
| metric_transform_lang | 5 (of 5) | own tests 26/26, regression 74/274: the reference solution fails 200 earlier tests across every checkpoint-1 to -4 file (cli format, core, errors, expressions, windows) | deliberate: checkpoint 5 redefines the language, so the earlier tests no longer apply; nothing to file |

Raw outputs of the check: scratchpad `check-prior.log` and `priorfix-<problem>-<n>/eval/`
of the session that ran it (2026-09-08); rerun with the loop in that session's
`check-prior.sh` (copy the problem, flip the flag, `bin/scb eval-snapshot` the reference
solution as that checkpoint). Worth folding into a `bin/` tool if the pending three come
back clean.

## Harness: patches we carry (all in `patches/`, applied to the checkout)

Listed in `README.md` with what each fixes: stream-parser string message; stop-after-
checkpoint; agent death detection and prompt context variables; resume invalidates
infra-failed checkpoints; container init and timeout kill; retry keeps every attempt's
transcript. Each is PR-shaped as it stands. Two more findings without a patch yet:

- `retry()` resets the usage tracker, so a checkpoint that timed out and continued
  under-reports its cost (v7 datagate ckpt 6 recorded $3 of roughly $15).
- A collection pass that fails (uv exit 2 during a network blip) marks the checkpoint
  `infrastructure_failure` even when the test run that follows collects and scores every
  test; we clear the flag by hand when the evaluation is complete (just-solve v2 ckpt 4,
  min11 mvvault ckpt 4, both 2026-09-07/08). A better rule: infra failure only when the
  final run's collected count falls short.
- `SCBENCH_PROBLEMS_PATH` (a flat directory of problems that overrides the cache) is
  undocumented upstream; we depend on it for spec versions.

## Agent config

Monitor events never reach a `claude -p` session, so an agent that arms Monitor polls with
no-op turns ($103 checkpoint, `notes/xjq-runs.md`). Our fix is `disallowed_tools: [Monitor]`
in the agent config; upstream could default it. Related: `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`
is what keeps background sub-agents alive past the parent's turn (README of the agent config).
