# Minimal-prompt ladder, rung by rung

What each rung adds to the one below it, generated from
`diff configs/prompts/spectest-min{N-1}-*.jinja configs/prompts/spectest-min{N}-*.jinja`.
Every hunk is listed; wording is paraphrased. The ladder climbs from the benchmark's own
just-solve prompt toward v8A (`spectest-v8A-no-libs-no-subagent.jinja`, the smallest prompt
known to strict-solve the patched datagate spec). Every rung runs against the patched
spec (`problems/datagate-clarified.patch`); scores are in `spectest-datagate-runs.md`, and
the full spectest lineage v1 to v8 is in `spectest-prompt-changes.md`.

## just-solve (`slop-code-bench/configs/prompts/just-solve.jinja`, the base)

"Implement a program that 100% solves the specification. That is all you need to do."
Then the virtualenv and `requirements.txt` block (on continuation checkpoints, keep the
same virtualenv and update the file), "Your task is:", and the spec.

## min0 (`spectest-min0-tests-first-handsoff.jinja`)

- Drops "That is all you need to do."
- Adds one sentence: before implementing, write tests from the spec, quoting it.

## min1 (`spectest-min1-tests-first.jinja`, not run)

- The one sentence becomes a procedure: before coding, split the spec into minimal logical
  phrases and give each phrase its own test section with the phrase quoted in a comment;
  then pass all tests.
- Adds: do not change the spec, or the tests written from the spec.

Skipped in the ladder run; the min0 to min2 jump covers it, and it is there to come back
to if that jump turns out to matter.

## min2 (`spectest-min2-strict-errors.jinja`)

- The two "critically" rules from v3 and v4, without the word: a test may expect an error
  only where the spec quotably requires one; and when a generated input makes a spec test
  fail, that is evidence the implementation misses the spec, so never narrow the
  generator or the test to avoid the input.
- Wording drift from min1's hand edit: "before coding" is back to "before implementing
  anything", and "then pass all tests" is back to "then code until the tests pass". Same
  meaning; min2 through min4 share this wording, min1 does not.

## min2b (`spectest-min2b-generator-floor.jinja`, the flipped cell)

min3 minus min2's two rules, so the generator floor is tested without them. Relative to
min1 it adds only the hypothesis pair below and carries min2's wording drift. Queued after
min4. Together with min0, min2 and min3 it completes a 2-by-2: rules or not, floor or not.

## min3 (`spectest-min3-hypothesis.jinja`)

- Adds hypothesis tests covering each phrase, if at all possible.
- The generator floor from v4: every generator must be able to produce the smallest
  inputs the spec doesn't quotably exclude, such as empty or one element. (v4 spelled the
  list out as "empty, one element, one row, one column"; the rung says "eg~ empty, one
  element, etc.")

## min4 (`spectest-min4-ambiguities.jinja`)

- The AMBIGUITIES.md procedure as v7 words it: when the spec is under-specified such that
  alternative interpretations would change a conforming implementation's behavior on
  some input, never ask; choose the reading that best fits the spec's intent; record a
  numbered entry from T1 with sections Spec Text, Alternatives, and Choice, quoting the
  spec source; annotate rather than delete an entry a later spec resolves.
- After choosing, at least one test asserts the chosen reading.

Not included: the v8 implementation-time entries (I1 numbering), and the tighter Choice
wording in `configs/prompts/v8-choice-must-decide.patch`, which is unapplied everywhere.

## What min4 still lacks against v8A

Everything else in v8A is either structure or harness housekeeping:

- The section headings and the four-step approach list; "fully implement the spec,
  without questions".
- Environment: `IN_PROGRESS` and `COMPLETED` marker files; the pgrep-then-kill rule; log
  long-lived processes to a file; the turn-ending rule (only a sub-agent can wake you, a
  background command dies five seconds after the turn ends, wait in the foreground).
- Testing: "do not consider implementation-time difficulty"; e2e tests, no mocks; the
  sub-notes rule for a phrase that affects other parts of the spec; the old-versus-new
  spec reconciliation rule; the tester-validation rules from v8 (validate the tests,
  never run the full suite to green), which without a sub-agent address the main agent.
- Implement: red/green as features are added; earlier checkpoints' unit tests are
  disposable and are the ones to change if they disagree with the spec; the I1 procedure
  for implementation-time ambiguities.
- Declare complete: touch `COMPLETED`, remove `IN_PROGRESS`.
