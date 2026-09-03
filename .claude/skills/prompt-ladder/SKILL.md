---
name: prompt-ladder
description: Smallest prompt that strict-solves a patched spec, and where code quality drops off.
disable-model-invocation: true
---

# Prompt ladder

Input: a problem with `problems/<problem>-clarified.patch` materialized by `bin/spec-patch`,
and a strict solve of the full generalized prompt on it. Output: in the problem's ledger, a
rung table and miss matrix from `bin/compare-runs`, naming two minima: the lowest rung that
strict-solves, and the lowest rung whose code quality matches the full prompt. Every run
here is launched with `SCBENCH_PROBLEMS_PATH=$PWD/problems`, which `bin/run-config --patched`
puts in the launch line.

## 1. Flip

Just-solve on the patched spec:

    bin/run-config --prompt just-solve --problem <problem> --patched --name just-solve-disambiguated

Done when all checkpoints have an evaluation. If every checkpoint is strict, the ladder has
one rung: queue a repeat for noise and go to step 4.

## 2. Climb

The rungs are `configs/prompts/spectest-min*.jinja`, cumulative: each adds one rule set to
the one below (tests first; error strictness and never-narrow; hypothesis with the generator
floor; the ambiguity registry). Generate a config per rung with `bin/run-config --patched`
and queue them lowest first. Run every rung rather than stopping at the first strict one:
the higher rungs are the quality curve. When a miss needs a rule no rung carries, add a
new rung above the one that failed instead of editing an existing rung, so earlier results
stay comparable. Done when every rung has all checkpoints.

## 3. Noise

Repeat the lowest strict rung and the just-solve flip once each. A test that flips between
repeats is noise and cannot be a rung's win. Done when both repeats are complete.

## 4. Report

    bin/compare-runs <flip runs> <rung runs> <full-prompt run> --md

into the ledger. Name the strict minimum (lowest rung strict in both its runs) and the
quality minimum (lowest rung with erosion and ast-grep within noise of the full prompt).
Where they differ, say which matrix rows the rungs between them flip. Done when the
ledger has the table, the matrix, and both minima named.

## Reference

- datagate: just-solve on the patched spec missed 8 of 405, all whitespace preservation
  and lenient value parsing; the full prompt minus libraries and sub-agent (v8A) solved 405
  at $30 and two hours, half of v8's cost, with the same erosion. Ledger:
  `notes/spectest-datagate-runs.md`.
- A just-solve rung costs about $15 and an hour on datagate; v8A about $30 and two hours.
- The v7 turn-ending rule ("a background command is killed five seconds after the turn
  ends") once cost $89 in one checkpoint: the agent kept its turn alive with 720 no-op
  commands while a foreground test run finished. Rungs without a sub-agent do not need it.
