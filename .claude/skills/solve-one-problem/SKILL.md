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
launch: one run at a time, behind whatever is queued, with a monitor on the queue. The
driver underneath waits out the 5-hour window and API overloads on its own. After every
run, before anything else, the ledger ritual in `/prompt-ladder` ("After every run"):
`bin/ledger-row <run_dir>`, then the row, the failure-summary entry, and for ladder runs
the ladder section.

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

`/spec-ambiguity-review`, on the best-prompt run. Its output is
`problems/<problem>-clarified.patch` and a strict run of the best prompt on the patched
spec. Done when that run is strict, or its halt's misses have gone back through step 1.

## 3–5. Ladder and report

`/prompt-ladder`, on the patched spec. Done when the ledger names the minimum prompt for a
strict solve and the minimum for code quality.

Then `bin/results --write` regenerates `notes/results.md`, one row per problem, prompt and
spec across every complete run, so a rung's effect on score or erosion reads across
problems at a glance. It is generated, never edited; the reading goes in the ledger.

## Reference

- Current best generalized prompt: `configs/prompts/spectest-v8A-no-libs-no-subagent.jinja`.
  Update this line when a smaller prompt holds a strict solve on two problems.
- Ledger row: version, run dir, what changed, per-checkpoint scores, how it ended and
  which tests it missed, grouped by the sentence or behavior they share.
- `bin/summarize <run>` for one run; `bin/compare-runs` for several; `bin/failures a b`
  for two runs' failures with pytest output; `bin/askrun <checkpoint_dir> <question>` to ask
  the agent that ran a checkpoint why it read a sentence the way it did.
- Read files the user edited on the host only after `refresh-mount`.
