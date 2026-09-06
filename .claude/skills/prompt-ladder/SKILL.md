---
name: prompt-ladder
description: Smallest prompt that strict-solves a patched spec, and where code quality drops off.
disable-model-invocation: true
---

# Prompt ladder

Input: a problem with a spec version built by `bin/spec-patch <problem> <vN>` (`specs/README.md`),
and a strict solve of the full generalized prompt on it. Output: in the problem's ledger, a
rung table and miss matrix from `bin/compare-runs`, naming two minima: the lowest rung that
strict-solves, and the lowest rung whose code quality matches the full prompt. Every run
here is launched with `SCBENCH_PROBLEMS_PATH=$PWD/specs/<vN>/problems`, which `bin/run-config --spec <vN>`
puts in the launch line.

## 1. Flip

Just-solve on the patched spec:

    bin/run-config --prompt just-solve --problem <problem> --spec <vN>

Done when all checkpoints have an evaluation. If every checkpoint is strict, the ladder has
one rung: queue a repeat for noise and go to step 4.

## 2. Climb

The rungs are `configs/prompts/spectest-min*.jinja`, cumulative: each adds one rule set to
the one below (tests first; error strictness and never-narrow; hypothesis with the generator
floor; the ambiguity registry). Generate a config per rung with `bin/run-config --spec <vN>`
and queue them lowest first. Run every rung rather than stopping at the first strict one:
the higher rungs are the quality curve. When a miss needs a rule no rung carries, add a
new rung above the one that failed instead of editing an existing rung, so earlier results
stay comparable. Done when every rung has all checkpoints.

Below the rung level, chunk sets hold a prompt one rule per lettered file, and
`bin/build-prompt [--set NAME] LETTERS` writes `NAME-LETTERS.jinja` from any subset, so a single
rule can be added or removed at a time (`--list` for the index; each set's README says which
chunks presuppose others). `min4-chunks/` is the original ladder; `min9-chunks/` is v9, the
current top prompt (v8A plus a Differs score per registry entry), whose skeleton keeps section
headers when rules are dropped. On spec v2 every v9 rung from DEFJKOP (391 words, $22) up was
strict on its first run; the user's rules for the search: shrink only from a prompt that is
strict twice on the current spec, repeat any strict subset before it counts, and keep the
tester-speed chunks (M, N) in any minimal prompt.

## 3. Noise

Repeat the lowest strict rung and the just-solve flip once each. A test that flips between
repeats is noise and cannot be a rung's win. Done when both repeats are complete.

## 4. Report

    bin/compare-runs <flip runs> <rung runs> <full-prompt run> --md

into the ledger. Name the strict minimum (lowest rung strict in both its runs) and the
quality minimum (lowest rung with erosion and ast-grep within noise of the full prompt).
Where they differ, say which matrix rows the rungs between them flip. Done when the
ledger has the table, the matrix, and both minima named.

## After every run, before anything else

    bin/ledger-row <run_dir>

gives the table row and the failure-summary entry for `notes/<problem>-runs.md`. Fill in
what changed and the cause of each miss (the checkpoint's `evaluation/stdout.txt`,
`bin/miss-report`, `bin/askrun`), put the row in the run table and the entry under "Test
failure summaries", and for a ladder run refresh the ladder section with
`bin/compare-runs <runs...> --md`. Commit. Done when all three are in the ledger; a run
whose ledger entry is missing is a run that did not happen for the next session.

## Reference

- datagate: just-solve on the patched spec missed 8 of 405, all whitespace preservation
  and lenient value parsing; the full prompt minus libraries and sub-agent (v8A) solved 405
  at $30 and two hours, half of v8's cost, with the same erosion. Ledger:
  `notes/spectest-datagate-runs.md`.
- A just-solve rung costs about $15 and an hour on datagate; v8A about $30 and two hours.
- The v7 turn-ending rule ("a background command is killed five seconds after the turn
  ends") once cost $89 in one checkpoint: the agent kept its turn alive with 720 no-op
  commands while a foreground test run finished. Rungs without a sub-agent do not need it.
