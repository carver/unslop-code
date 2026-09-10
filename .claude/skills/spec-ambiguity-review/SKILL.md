---
name: spec-ambiguity-review
description: Turn a run's hidden-test misses into a minimal spec patch, verified by blind judges, then a strict rerun.
disable-model-invocation: true
---

# Spec ambiguity review

Input: a completed spectest run on one problem, with an AMBIGUITIES.md registry in its
snapshots and hidden-test misses. Output: a new version folder for the problem, `specs/<problem>/vN/` (see `specs/README.md`), a few
reworded sentences that flip the model's reading to the hidden tests' reading, and a
strict run against the patched spec. datagate is the worked example:
`notes/critical-ambiguities.md`, `notes/ambiguity-judge.md`, `specs/datagate/v1/01-datagate-clarified.patch`;
xjq (`notes/xjq-runs.md`, four sentences over three versions) and file_merger (`notes/file_merger-misses.md`)
are the later ones.

## 1. Compile the misses

    bin/miss-report <run_dir> --out notes/<problem>-misses.md

One section per distinct failing hidden test: docstring, assertions, spec lines near
the test's words, candidate registry entries by word overlap. The candidates are hints.
For every failing test, read the test, the spec section, and the registry until you can
name the one sentence the test and the tester read differently, and the reading the test
takes. When misses smell of parsing, read the fixture's bytes too: file_merger's TSV fixtures
end lines in `\r\n` and its CSV fixtures escape quotes with backslashes, against the spec's
own words, and nine misses were one such byte. Group tests by sentence. Done when every failing test is under exactly one
sentence, or is marked "process" (a crashed or cut checkpoint, visible in the run's
artifacts) or "noise" (flips between runs, like a detector on a tiny sample).

## 2. Propose the patch

Make the next version folder, `specs/<problem>/vN/`, by copying the current version's patches
and adding `NN-<slug>.patch`, a unified diff against the cached problem
(`~/.cache/scbench/problems/<problem>`), paths `a/<problem>/checkpoint_N.md`. One hunk
per sentence, the smallest wording that nudges toward the hidden reading, matching what the
reference solution in `solutions/` does. Header comment lists sentence, entry id, tests.
Done when `bin/spec-patch <problem> vN` applies the folder and prints the changed lines. Never edit
an older version's folder: runs already made against it must stay comparable.

Two things the wording must respect. State a relation positively: "JSONL and CSV are inferred
peers" was read as intended, while "JSONL does not outrank CSV" was read as CSV outranking
JSONL, two runs of two (file_merger v1). And put the sentence in the checkpoint whose agent
writes the behaviour: a checkpoint's prompt carries only that checkpoint's spec, so a sentence
added to checkpoint 1 is invisible to the agent at checkpoint 5 (xjq v3 needed a checkpoint-5
copy of its rule).

Pause and succinctly summarize the proposed changes for me to approve. We might discuss in several rounds. Then when I approve all patches, continue.

## 3. Judge, edit, repeat

    SCBENCH_PROBLEMS_PATH=$PWD/specs/<problem>/vN/problems bin/judge-ambiguities run <run_dir> \
      --out outputs/judge/<problem>-vN --spec-patch specs/<problem>/vN/01-....patch --spec-patch specs/<problem>/vN/02-....patch \
      --entries T7,T9 --variants choose,rule --samples 10 --batch 5
    bin/judge-ambiguities summarize outputs/judge/<problem>-vN --hidden '{"T7": [1], "T9": [2]}'

Judges see the patched spec and the patched quote, never the tester's choice. Read the
rule-first answers, not only the vote: a vote can pass while every rule reads the words
the wrong way (datagate T56 "and charset" read as a form field), and a vote can fail while
every rule is right because the registry's alternatives no longer describe the patched
sentence (datagate T22). After each edit to the patch, rerun `bin/spec-patch <problem> vN` and judge
again into a fresh `--out`. Done when each sentence's rules describe the hidden reading in
10 of 10, with the smallest wording that gets there.

## 3b. Panel a candidate sentence before it goes in

Six blind judge sub-agents, each given a scratch copy of the spec with the candidate line in
place, the fixtures' shape as a question ("a body of the two lines `name` and `a`"), and the
candidate readings in a per-judge shuffled order with a key file; judges may read the spec and
nothing under outputs/, notes/ or tests. Map answers through the keys and require unanimity; a
split means the wording still leans on the reader. The two v2 sentences went in this way
(`specs/README.md`). The judge's `why` line should quote the spec words that decided it.

## 4. Rerun strict

    bin/run-config --prompt <best generalized prompt> --problem <problem> --spec vN
    bin/queue add-strict configs/runs/<name>.yaml     # then bin/queue solo <id> if other jobs must wait

One checkpoint per scb invocation; halts on the first checkpoint with any failing test.
Done when the driver prints DONE, or halted with the failing tests, which go back to step 1.
A sentence whose checkpoint is late can be tried for a few dollars first:
`bin/fork-run <last_run_dir> --spec vN --keep <k>` copies the run with checkpoints 1..k kept
and pointed at vN (k is the last checkpoint whose spec vN leaves unchanged), then
`bin/queue resume <copy> <k+1>` runs checkpoint k+1 alone; queue k+2 once it is strict
(xjq v3 2026-09-09 by hand, file_merger v5 2026-09-10).

## Reference

- Judge cost is about a cent per judgment batched; single-entry calls cost ten times
  that because Claude Code print mode does not cache a custom system prompt.
- Step 3 judge runs finish in minutes: run them in the foreground. A full-registry pass
  (all entries, all variants) takes about 40 minutes: `nohup` it, then watch with a poll
  loop that ends itself on the script's final `done:` line, such as
  `until grep -q '^done:' <log>; do sleep 60; done; tail -1 <log>`. A `tail -F`
  monitor never ends on its own and outlives the job.
- Alternatives are shuffled per sample; the datagate tester listed its favourite reading
  second in 102 of 130 entries, which is not a position effect.
- Read files the user just edited on the host only after `refresh-mount`.
