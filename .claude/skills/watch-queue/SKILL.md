---
name: watch-queue
description: Follow the run queue job by job: arm a wait, recap the run on wake, ledger it, arm the next.
disable-model-invocation: true
---

# Watch the queue

Input: pueue up (`~/.local/bin/pueued -d` if `bin/queue` fails loudly) and the id of the running
job (`bin/queue`). Output: every finished run recapped to the user and, for a dev problem,
ledgered and committed, with the next job's wait armed. The loop runs until the queue is empty
or the user stops it.

## 1. Arm

`bin/queue wait <id> 2>&1 | tail -4` in a background Bash call. Its wake-up ends with
`run_dir=<path>`; take the run dir from there, never from `ls | tail -1`. Done when the call
is backgrounded. Until it wakes, other work is fine; polling the job is not.

## 2. Recap

On wake: `bin/run-recap <run_dir>`. It prints the ledger row with WHAT CHANGED and CAUSES left
open, the failure summary, the miss matrix against the problem's other runs at the same spec,
and for a v0 run the implementation-only quality table across prompts. Done when it has printed.

## 3. Ledger

Which set the problem is in (`split.json`) decides:

- dev: insert the row after the problem's latest row in `notes/<problem>-runs.md` (datagate:
  `notes/spectest-datagate-runs.md`) and a failure-summary entry in its `## Test failure
  summaries`, with WHAT CHANGED and CAUSES filled from the matrix (which misses every run
  shares, which one prompt owns, which are new to any run). `bin/lint`, then commit the ledger
  alone. Done when the commit exists.
- test: results only. No ledger, no transcript or spec reading. `bin/results --write` refreshes
  the table on disk and stays uncommitted until the batch's one results commit. Done when
  refreshed.

## 4. Report

To the user, in one message: score against the problem's pairs, strict count, cost, minutes,
whole-snapshot erosion, ast% and cloned%, and always the implementation-only erosion, ast%,
cloned% and lines per run. Done when the table has both scopes.

## 5. Next

`bin/queue` for the running job's id; back to step 1. A trigger named in memory (a page
rebuild, a republish) fires on the wake of its last job.

## Traps

- Every Bash result through `tail`, `cut -c1-N` or `jq`: pueue's table and pytest's `E` lines are
  thousands of characters wide. `cd` into a snapshot before grepping it, so paths stay short.
- The grid has one patched version per problem, and it flips when the first just-solve run on the
  new version lands. Do not rebuild or republish while a version's pairs are half in; rebuild when
  the last pair lands, then fix the hand-written version mentions (`notes/uplift-grid.md`,
  `README.md`, `report/spec-patches.html`).
- The pre-commit hook lints the whole tree, other sessions' untracked files included. A commit
  blocked by someone else's file waits; never `--no-verify`, never edit their file.
- A one-run miss is not noise until the run's registry says so (`/spec-ambiguity-review`).

## When it stops

- Usage halt: `scb-extend` pauses the queue on a usage limit; `bin/usage` shows the windows,
  `pueue start` after the reset.
- A job to cut short: `bin/queue kill <id> --delete-run` when nothing in it is worth keeping,
  `bin/queue kill <id>` then `bin/queue resume <run_dir>` to continue from its next checkpoint.
- A second channel: `bin/queue add --group <name> <config>` runs a job beside the main queue (one
  per channel, a pueue group made on first use, running at once). Arm one `bin/queue wait` per
  running job, one background call each. `bin/queue` lists the channels under `[name]` headings;
  `pueue pause -g <name>` and `pueue start -g <name>` hold and release one. A run whose
  `window_usage.jsonl` has `shared` readings overlapped another channel: say so beside its
  minutes, which are not comparable.
- Order changes: `bin/queue add --next <config>` puts a job first; `bin/queue add --before <id>
  <config>` puts it right before a queued job; `bin/queue move <id> before <other>` reorders by
  rewriting priorities. `resume` takes `--next` and `--before` too.
