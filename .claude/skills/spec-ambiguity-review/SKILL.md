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

One section per distinct failing hidden test: docstring, assertions, the E lines of its failure,
spec lines near the test's words, candidate registry entries by word overlap. The candidates are hints.
For every failing test, read the test, the spec section, and the registry until you can
name the one sentence the test and the tester read differently, and the reading the test
takes. When misses smell of parsing, read the fixture's bytes too: file_merger's TSV fixtures
end lines in `\r\n` and its CSV fixtures escape quotes with backslashes, against the spec's
own words, and nine misses were one such byte. Group tests by sentence. Done when every failing test is under exactly one
sentence, or is marked "process" (a crashed or cut checkpoint, visible in the run's
artifacts) or "noise" (flips between runs, like a detector on a tiny sample).

### Before calling a miss anything

- **Noise needs the registry's word for it.** A test that failed in one run only is not noise until
  that run's registry has been read: `bin/registry-scores <run> --grep <words from the spec line>
  --full`. `bin/miss-report <run> --brief` (also in the recap) lists candidate entries per miss
  from the words of the test's name, source and failure output; it says where to start reading,
  the grep on the spec line's own words settles it. rejector's two "one-run" misses were both Risk 40 entries where the run chose the other
  side knowingly. A rare coin gets a sentence like any other reading.
- **Read the later checkpoints for the rule.** Three times the spec stated the hidden reading one
  to three checkpoints after it was first needed (mvvault's "filename contains entry `id`" at
  checkpoint 4 for a checkpoint-3 test; rejector's input-order rule at 5 for a test at 2). `grep`
  the key words across every `checkpoint_*.md`; the late wording is the best patch wording.
- **Say whose mistake it is**, in the pitch and in the patch preamble, because the user decides on
  it: the benchmark's (a rule stated late, a test against the spec's own sentence, a misleading
  example, a literal phrase the spec never gives, a test that wants the worse program) gets a
  sentence; the agent's (it embellished words the spec already has, or its code does not do what
  its own registry chose) gets none, however many runs do it. Do not re-pitch a sentence that only
  says the spec's own words louder.
- **A registry that chose the tests' way and still failed is a bug, not a reading.** Read the code
  path before drafting (rejector's TPM gate: every run chose "replace the reservation" and five
  slept out the window anyway). `bin/askrun` or the snapshot's own functions, run on the fixture's
  defect, settle it in minutes.
- **Load the fixture, do not read it.** mvvault's and file_merger's YAML fixtures fold multi-line
  quoted scalars into one line; a test that passes for every run, a wrong one included, is vacuous
  (`notes/upstream-prs.md`).
- **Quote entries verbatim** (`--full`). A composite "registry-style entry" hides what the run
  actually weighed; the user asked for the real ones every time.
- **Write the cause only after reading it.** Four ledger sentences this session named a cause that
  the code then contradicted. If it was not traced, the ledger says "not traced".

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

## 2b. Pitch, then wait

Before any patch: `bin/test-history <problem> <test>` for every miss, so the pitch says whether
it is a coin (some runs pass) or a shared reading, and which runs registered it (`bin/registry-scores
<run> --grep <word>` on each, with the entry id and Risk). The pitch carries the verbatim spec
line, a registry-style entry (alternatives, the tests' reading with the fixture and the reference's
code, why it is open), the runs' choices, and one or two candidate sentences with the
over-correction to avoid (v1's "JSONL does not outrank CSV" was read as CSV outranking JSONL).
Then stop. The user picks the wording, often shorter, and may skip the judges; draft the patch
into `specs/drafts/` uncommitted when asked ("draft it, I'll edit"), and read it back with
`refresh-mount` before building the folder, since they edit and commit it on the host.

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

### After the patched run

Read the new run's registry sentence by sentence, not only its score: does each patched line
still have an entry (the question survived), a new entry (the question moved on, usually to
something no fixture tests), or none (settled)? file_merger v7 and mvvault v1 both moved their
question on; rejector v1's tester named the race our sentence could not close (T20). Apply all
drafts in order to a scratch copy before handing them over: two hunks that touch neighbouring
lines reject each other (`patch -p1` per file, in filename order).

## 4. Rerun strict

    bin/run-config --prompt <best generalized prompt> --problem <problem> --spec vN
    bin/queue add-strict configs/runs/<name>.yaml     # then bin/queue solo <id> if other jobs must wait

One checkpoint per scb invocation; halts on the first checkpoint with any failing test.
Done when the driver prints DONE, or halted with the failing tests, which go back to step 1.
A sentence whose checkpoint is late can be tried for a few dollars first:
`bin/fork-run <last_run_dir> --spec vN --keep <k> --queue` copies the run with checkpoints
1..k kept and pointed at vN (k is the last checkpoint whose spec vN leaves unchanged) and
queues `bin/queue resume-strict <copy>`, which runs the rest one at a time and halts at the
first non-strict one (file_merger v5 and v6, 2026-09-10: a fork chain v4 -> v5 -> v6 reached
147/147 for the cost of three checkpoints). A stitched 147 is not a fresh run: the twice bar
still wants a full run from checkpoint 1 on the final version.

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
