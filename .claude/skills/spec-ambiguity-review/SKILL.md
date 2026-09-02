---
name: spec-ambiguity-review
description: Turn a run's hidden-test misses into a minimal spec patch, verified by blind judges, then a strict rerun.
disable-model-invocation: true
---

# Spec ambiguity review

Input: a completed spectest run on one problem, with an AMBIGUITIES.md registry in its
snapshots and hidden-test misses. Output: `problems/<problem>-clarified.patch`, a few
reworded sentences that flip the model's reading to the hidden tests' reading, and a
strict run against the patched spec. datagate is the worked example:
`notes/critical-ambiguities.md`, `notes/ambiguity-judge.md`, `problems/datagate-clarified.patch`.

## 1. Compile the misses

    bin/miss-report <run_dir> --out notes/<problem>-misses.md

One section per distinct failing hidden test: docstring, assertions, spec lines near
the test's words, candidate registry entries by word overlap. The candidates are hints.
For every failing test, read the test, the spec section, and the registry until you can
name the one sentence the test and the tester read differently, and the reading the test
takes. Group tests by sentence. Done when every failing test is under exactly one
sentence, or is marked "process" (a crashed or cut checkpoint, visible in the run's
artifacts) or "noise" (flips between runs, like a detector on a tiny sample).

## 2. Propose the patch

Write `problems/<problem>-clarified.patch` as a unified diff against the cached problem
(`~/.cache/scbench/problems/<problem>`), paths `a/<problem>/checkpoint_N.md`. One hunk
per sentence, the smallest wording that states the hidden reading, matching what the
reference solution in `solutions/` does. Header comment lists sentence, entry id, tests.
Done when `bin/spec-patch <problem>` applies it and prints the changed lines.

## 3. Judge, edit, repeat

    SCBENCH_PROBLEMS_PATH=$PWD/problems bin/judge-ambiguities run <run_dir> \
      --out outputs/judge/<problem>-clarified --spec-patch problems/<problem>-clarified.patch \
      --entries T7,T9 --variants choose,rule --samples 10 --batch 5
    bin/judge-ambiguities summarize outputs/judge/<problem>-clarified --hidden '{"T7": [1], "T9": [2]}'

Judges see the patched spec and the patched quote, never the tester's choice. Read the
rule-first answers, not only the vote: a vote can pass while every rule reads the words
the wrong way (datagate T56 "and charset" read as a form field), and a vote can fail while
every rule is right because the registry's alternatives no longer describe the patched
sentence (datagate T22). After each edit to the patch, rerun `bin/spec-patch` and judge
again into a fresh `--out`. Done when each sentence's rules describe the hidden reading in
10 of 10, with the smallest wording that gets there.

## 4. Rerun strict

Copy `configs/runs/spectest-v8-disambiguated-datagate-opus5.yaml`, change the problem and
the save_template name, then

    SCBENCH_PROBLEMS_PATH=$PWD/problems bin/scb-strict configs/runs/<name>.yaml <problem> <n_checkpoints>

One checkpoint per scb invocation; halts on the first checkpoint with any failing test.
Done when the driver prints DONE, or halted with the failing tests, which go back to step 1.

## Reference

- Judge cost is about a cent per judgment batched; single-entry calls cost ten times
  that because Claude Code print mode does not cache a custom system prompt.
- Alternatives are shuffled per sample; the datagate tester listed its favourite reading
  second in 102 of 130 entries, which is not a position effect.
- Read files the user just edited on the host only after `refresh-mount`.
