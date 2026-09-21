---
name: solve-one-problem
description: One dev problem through the spec-vs-prompt steps, up to the manual review gate.
disable-model-invocation: true
---

# Solve one problem

Input: a dev problem name (`split.json`). Output: the problem's ledger, `notes/<problem>-runs.md`,
with a row per run and a report naming what the spec patch bought and what the smallest
strict-solving prompt is. datagate is the worked example: `notes/spectest-datagate-runs.md`.
Stop after step 5; the user reviews before the next problem.

Every run goes through `bin/run-config` for the config and `bin/queue add <config>` for the
launch: one run at a time per channel, behind whatever is queued, with a wait armed on each running
job. Spec work goes in the side channel so it does not wait behind the main queue: `bin/queue
add-strict --group specpatch <config>`, its repeat with `--after <id>` (it runs only if the first
is strict), and the other prompts' pairs in the main queue `--after` the repeat. When a strict run
halts on a miss the user rules the agent's bug, the dependents have failed unrun: re-queue them
with plain `bin/queue add`. The
driver underneath waits out the 5-hour window and API overloads on its own. After every
run, before anything else, the ledger ritual in `/prompt-ladder` ("After every run"):
`bin/ledger-row <run_dir>`, then the row, the failure-summary entry, and for ladder runs
the ladder section.

A dev problem that already has v0 runs of several prompts needs no new baseline: the miss matrix
in `bin/run-recap <latest run>` covers every run at that spec, and `bin/test-history <problem>
<test>` says how often each miss happens. Write the grouped misses to `notes/<problem>-misses.md`,
draft one patch per sentence into `specs/drafts/<problem>-NN-<slug>.patch` UNCOMMITTED with the
evidence in its preamble, and stop: the user edits and commits them on the host, then the folder
`specs/<problem>/v1/` is built from what they kept (`git mv`, `bin/spec-patch`).

## 1. Baseline pair

The control is the problem's just-solve run in `outputs/dev6-opus5/`. Run the current best
generalized prompt (see Reference) on the unpatched spec, then

    bin/compare-runs <control> <best-prompt run>

Classify every test in the miss matrix: a **reading** (the tester and the hidden test read
one spec sentence differently), **process** (a crashed or cut checkpoint, a narrowed
generator, a polling loop; visible in the run's artifacts), **taste** (a reading the spec
authors assume without stating it, consistent across problems: errors only where the spec
asks for one, whitespace preserved unless told to trim), or **noise** (flips between runs).
A process miss is a defect in the generalized prompt: fix it in a new
`configs/prompts/spectest-v<N>.jinja`, record the change in
`notes/spectest-prompt-changes.md`, and rerun. A taste miss that recurs across problems is
also a generalized-prompt change, but one to propose and settle with the user before it is
written: it sets a reading for every problem after this one. Done when every remaining
miss is a reading or noise.

## 2. Spec patch

`/spec-ambiguity-review`, on the best-prompt run. Its output is a new spec version under
`specs/<problem>/vN/` and a strict run of the best prompt on it. Done when that run is strict, or its halt's misses have gone back through step 1.

## 3–5. Ladder and report

`/prompt-ladder`, on the patched spec. Done when the ledger names the minimum prompt for a
strict solve and the minimum for code quality.

Then `bin/results --write` regenerates `notes/results.md`, one row per problem, prompt and
spec across every complete run, so a rung's effect on score or erosion reads across
problems at a glance. It is generated, never edited; the reading goes in the ledger.

## Reference

- Current best generalized prompt: `min13-ABDJKMNT` (spectest plus the upstream anti-slop rule list), the
  prompt the user runs new specs with since 2026-09-20; `min12-ABDJKMN` is spectest without the rules.
  Update this line when the user's choice changes.
- Ledger row: version, run dir, what changed, per-checkpoint scores, how it ended and
  which tests it missed, grouped by the sentence or behavior they share.
- `bin/summarize <run>` for one run; `bin/compare-runs` for several; `bin/failures a b`
  for two runs' failures with pytest output; `bin/askrun <checkpoint_dir> <question>` to ask
  the agent that ran a checkpoint why it read a sentence the way it did.
- Read files the user edited on the host only after `refresh-mount`.
