# Prompt chunks of v12

v12 is v11 with one edit: the task-directions list at the top says "Implement" instead of
"Implement with Red Green testing". That line lives in the skeleton, so this set is
`min11-chunks/` with the same letters, slugs and chunk text, only `SKELETON.jinja` changed;
every min11 subset has a min12 twin of the same name (`tests/test_build_prompt.py` pins
both). `spectest-v12.jinja` cut into one rule per file, for the same subset search the min4
chunks support. `bin/build-prompt --set min12 ABDFJKMN` writes
`configs/prompts/min12-ABDFJKMN.jinja`. `bin/build-prompt --set min12 --list` prints this
index from the files.

Layout is min9's. v9 has section headers, so a head-plus-tail split would lose a header
whenever its first rule was dropped. Here `SKELETON.jinja` holds the fixed structure (task
directions, the venv block, the IN_PROGRESS and COMPLETED markers, the section headers, the
spec slot) with one `<<section>>` slot per section, and every chunk is named
`<letter>-<section>-<slug>.txt`. A slot becomes its chosen chunks in letter order; an empty
slot disappears with its blank line, so the headers survive any subset. Letters run in
document order, so a built file reads like v12 with rules missing. All 19 chunks rebuild v12
apart from blank lines between rules that v12 runs together.

| letter | section | rule | min4 letter |
|---|---|---|---|
| A | environment | pgrep, never pkill; kill by PID | - |
| B | environment | long-lived processes log to a file, not a pipe | - |
| C | testing | finish when tests are written and validated; ignore implementation difficulty | - |
| D | testing | split the spec into phrases, one test section each | A |
| E | testing | hypothesis tests per phrase | B |
| F | testing | generator floor: smallest inputs the spec does not exclude, "empty, one element, etc." | C |
| G | testing | e2e tests, no mocks | - |
| H | testing | tests expect errors only where the spec quotably requires them | D |
| I | testing | phrase interactions: sub-notes, reconcile old and new spec | - |
| J | testing | ambiguity: never ask, choose; numbered AMBIGUITIES.md entry with Spec Text, Alternatives, Choice, Risk; the Risk definition | F + G, plus the v9 Differs rule |
| K | testing | annotate a resolved entry instead of removing it | H |
| L | testing | at least one test asserts the chosen reading | I |
| M | testing | run tests only to validate the tests themselves | - |
| N | testing | never run the full suite or long hypothesis runs at test time | - |
| O | implement | code until the tests pass | J |
| P | implement | do not change the spec or the tests written from it | K |
| Q | implement | red/green; earlier unit tests are disposable if they disagree with the spec | - |
| R | implement | a generated input that fails is evidence; never narrow the generator or test | E |
| S | implement | implementation-time ambiguities follow the same procedure, numbered from I1 | - |

Chunks that read as a sequence: K and L refer to "the entry" and "a choice", so they
expect J; S says "the same procedure" and expects J; F speaks of generators and expects E;
N complements M. Nothing enforces any of that. J is the whole ambiguity procedure in one
piece (choose, record, score), because the registry is instrumentation for our analysis
and goes in or out together. In v9 letters, min4's rule set is DEFHJKLOPR (v9's J carries
the Risk rule min4 never had, plus the rules with no min4 letter); ABCHJK is DEFKOP.
