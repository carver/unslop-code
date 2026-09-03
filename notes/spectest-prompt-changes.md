# Spectest prompt changes, version by version

What each prompt version changed relative to the one before it, generated from
`diff configs/prompts/spectest-v{N-1}.jinja configs/prompts/spectest-v{N}.jinja`
(v1 is `spectest.jinja`). Every hunk is listed; wording is paraphrased. Non-prompt
changes that shipped with a version (agent config, harness, spec) are listed under
"Outside the prompt". Scores per version are in `spectest-datagate-runs.md`.

## v1 (`spectest.jinja`)

Write all tests first, carefully, from the spec; then implement, preferring libraries.
In full:

- Approach in four steps: environment setup, tests from the spec, library research,
  red/green implementation. Do not ask questions.
- Environment: a virtualenv and a `requirements.txt`; on continuation checkpoints keep
  the same virtualenv and update the file.
- Testing: split the spec into minimal phrases and iterate; one test section per phrase
  with the phrase quoted in a comment; hypothesis tests per phrase generating data of all
  valid shapes; e2e tests with no mocks; test multiple usages in sequence rather than
  always from empty; add sub-notes and tests where a phrase affects other parts of the
  spec; when an old and a new spec are logically ambiguous, prefer a reading under which
  both hold, else merge preferring the new one.
- Research: use quality libraries for sub-problems; for a library that solves a parallel
  problem, consider a shim plus a hypothesis comparison test.
- Implement: code until tests pass; do not change the spec; red/green as libraries and
  features are added; unit tests from earlier checkpoints are disposable and are the
  ones to change if they disagree with the spec.

## v2

- Adds a fifth step, "Declare complete", and a section for it: touch a `COMPLETED` file
  and remove `IN_PROGRESS`.
- Environment: touch an `IN_PROGRESS` file at the start and delete any `COMPLETED` file.
- Environment: never `pkill`; `pgrep`, confirm exactly one match, kill that pid, because
  it is too easy to pkill your own Bash argv.
- Environment: long-lived processes log to a file or `/dev/null`, not an undrained pipe.
- Testing: "generate data of all valid shapes" becomes "don't limit the shape of input
  data unless the spec specifically calls for it".
- Testing: drops "test multiple usages in sequence rather than always starting from
  empty".
    Note: this caused *every* test to run against the same instance, not just some tests.
    That also caused issues with a long-running process writing out to a giant buffer, crashing if I recall correctly.
    I don't think it bought much, so dropped it.

## v3

- Implement: "do not change the spec" becomes "do not change the spec, or the tests
  written from the spec".
- Implement: new rule that a generated input which makes a spec test fail is evidence
  the implementation misses the spec; never narrow the generator or the test to dodge
  it. (Lesson from v2, whose agent set `n_min=2` on its header generator to silence its
  own single-column failures.)

## v4

- Testing: launch a sub-agent for the Testing section, judged on how broadly it tests,
  ignoring implementation difficulty; pass it the Testing section verbatim plus the
  full spec.
- Testing: the shape rule from v2 becomes a floor: every generator must be able to
  produce the smallest inputs the spec doesn't quotably exclude (empty, one element,
  one row, one column).
- Testing: a test may expect an error only where the spec specifically requires one,
  quotably.

## v5

- Testing: if the tester asks how to resolve an ambiguity, the parent must not decide
  for it and points it back at the AMBIGUITIES.md procedure.
- Testing: the AMBIGUITIES.md procedure. When the spec is under-specified such that
  alternative interpretations would change test outcomes, never ask; choose the reading
  that best fits the spec's intent and record an entry with the alternatives, the choice
  and why. When a later spec resolves an entry, annotate it rather than delete it.
- Implement: ambiguities found during implementation and not settled by the spec tests
  follow the same procedure.

## v6

- Environment: turn-ending rule. Only a background task notification can wake the agent
  after it ends its turn; ending the turn is fine while a task is verifiably running;
  never end the turn waiting on a file or other signal.
- Testing: a line addressed to the tester: its turn end is its final report, so it must
  not end its turn until the tests are written and run.
- Testing: the ambiguity gate changes from "would change test outcomes" to "would change
  the behavior of a conforming implementation on some input" (the old gate was circular
  for the tester, who writes the tests).
- Testing: the entry format is now required: sections Spec Text, Alternatives, Choice,
  always quoting the spec source.
- Typo fix in the sub-agent paragraph ("procediure").

Outside the prompt: the agent config sets `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, so
print mode no longer kills background sub-agents 600 s after the parent ends its turn
(v5 checkpoint 2 shipped zero implementation that way).

## v7

- Whole prompt reflowed to one sentence per line so later diffs read cleanly. The
  reflow carries no wording change in the pkill rule, the sub-agent paragraph, the
  tester line, the generator floor, the error rule, the sub-notes rule, the research
  section or the red/green paragraph.
- Environment: the turn-ending rule is rewritten for print mode's real wind-down. Only a
  running sub-agent can wake the agent; a background command is killed five seconds
  after the turn ends, so commands are waited on in the foreground; still never end the
  turn waiting on a file or signal.
- Testing: ambiguity entries are numbered, test-time entries starting at T1.
- Testing: after choosing a reading, at least one test must assert it.
- Implement: implementation-time entries are numbered starting at I1.
- Typo fixes: "intepret" to "interpret", "chose" to "choose".

## v8

Note: These are all testing performance improvements

- Testing: the tester's line changes from "written and run" to "written and validated".
- Testing: the tester runs tests only to validate the tests themselves (collection
  succeeds, helpers and generators work; on continuation checkpoints, each failure is
  because behavior is missing, not because the test is broken), in quick targeted runs.
- Testing: the tester never runs the full suite to completion or long hypothesis runs; a
  green suite is the implementer's job.

Outside the prompt: the container runs an init as PID 1 (`init=True`), so finished
orphans are reaped instead of lingering as zombies; v7's parent had waited an hour on
`tail --pid` of a zombie pytest at checkpoint 6.

## v8-disambiguated

No prompt change from v8. The spec is the cached datagate problem with
`problems/datagate-clarified.patch` applied, selected through `SCBENCH_PROBLEMS_PATH`.
Five sentences are reworded to the reading the hidden tests take: T22 encoding, T27
rowid, T56 upload charset, T63 spreadsheet charset, T74 force. v7 lost 14 tests to
exactly those five sentences. This is a spec-clarification experiment, not a benchmark
score.
The T{N} entries are found in the AMBIGUITIES.md output of the v7 run.
