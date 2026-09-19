# Do the tests carry the quality scores?

2026-09-10. scb-check scores every Python file in the snapshot, tests included (`--include-all`
only keeps ignore directives from hiding hits; the walker excludes venvs and caches, never
tests). Erosion is the share of cyclomatic-complexity mass in high-CC functions; verbosity is
clone, ast-grep and trivial-wrapper lines over total LOC. Test files add many low-CC functions
and long clone runs, so they move both. Re-scored with the test files deleted (one checkpoint
each, scb-check 0.1.3):

| snapshot | files | LOC | erosion | verbosity | ast% | cloned% |
|---|---|---|---|---|---|---|
| file_merger ckpt 4, just-solve control (dev6 0354) | full | 4042 | 0.700 | 0.225 | 0.191 | 0.039 |
| | implementation only | 3308 | 0.713 | 0.272 | 0.231 | 0.047 |
| file_merger ckpt 4, min12-ABDJKMN v0 (0739) | full | 5624 | 0.172 | 0.240 | 0.099 | 0.134 |
| | implementation only | 1892 | 0.429 | 0.330 | 0.292 | 0.046 |
| xjq ckpt 5, just-solve control (no test files) | both | 556 | 0.461 | 0.272 | 0.257 | 0.000 |
| xjq ckpt 5, min12-ABDJKMN v0 (0650) | full | 2390 | 0.062 | 0.374 | 0.038 | 0.331 |
| | implementation only | 440 | 0.290 | 0.236 | 0.205 | 0.018 |

Reading: erosion is diluted two to five times by the tests, but the implementation alone is
still well below the control (0.43 vs 0.71, 0.29 vs 0.46), on a third to half as much code.
Verbosity is not improved by the prompt: implementation-only it is level with or worse than
the control (0.33 vs 0.27 on file_merger), and the tests push it either way (down on
file_merger, up on xjq, where a third of the test lines are clones). The tests hold most of
the cloned lines in both runs. Test files were picked by name (`test*`, `conftest.py`, a
`tests` directory), one checkpoint per problem.

## Implementation against tests, all six problems (2026-09-18)

`bin/quality-split` copies the implementation files and the test files of a snapshot into two
trees and runs scb-check 0.1.3 on each, and on the whole snapshot. Final checkpoint of every
dev-set v0 run, opus-5, the two runs of a cell pooled (flagged lines over LOC; erosion is
high-complexity mass over total mass). The `all` columns match notes/results.md.

| name | prompt | runs | impl LOC | test LOC | test share | ast impl / test / all | erosion impl / test / all | cloned impl / test / all |
|---|---|---|---|---|---|---|---|---|
| datagate | just-solve | 2 | 2510 | 2337 | 48% | 0.357 / 0.452 / 0.403 | 0.388 / 0.933 / 0.721 | 0.045 / 0.058 / 0.051 |
| file_merger | just-solve | 2 | 5411 | 734 | 12% | 0.279 / 0.011 / 0.247 | 0.725 / 0.502 / 0.717 | 0.041 / 0.000 / 0.036 |
| mvvault | just-solve | 2 | 3967 | 2111 | 35% | 0.338 / 0.032 / 0.232 | 0.456 / 0.848 / 0.556 | 0.032 / 0.080 / 0.048 |
| rejector | just-solve | 2 | 5556 | 4775 | 46% | 0.334 / 0.040 / 0.198 | 0.709 / 0.616 / 0.680 | 0.062 / 0.036 / 0.050 |
| sith | just-solve | 2 | 11636 | 3206 | 22% | 0.309 / 0.007 / 0.243 | 0.672 / 0.050 / 0.650 | 0.046 / 0.090 / 0.055 |
| xjq | just-solve | 2 | 1094 | 0 | 0% | 0.203 / - / 0.203 | 0.427 / - / 0.427 | 0.015 / - / 0.015 |
| ALL | just-solve | 12 | 30174 | 13163 | 30% | 0.312 / 0.102 / 0.248 | 0.639 / 0.745 / 0.660 | 0.045 / 0.058 / 0.049 |
| datagate | min12-ABDJKMN | 2 | 1953 | 7119 | 78% | 0.252 / 0.029 / 0.077 | 0.120 / 0.000 / 0.029 | 0.017 / 0.164 / 0.133 |
| file_merger | min12-ABDJKMN | 2 | 3520 | 6960 | 66% | 0.288 / 0.003 / 0.099 | 0.479 / 0.004 / 0.209 | 0.049 / 0.188 / 0.142 |
| mvvault | min12-ABDJKMN | 2 | 3301 | 11221 | 77% | 0.216 / 0.021 / 0.065 | 0.171 / 0.024 / 0.061 | 0.032 / 0.139 / 0.114 |
| rejector | min12-ABDJKMN | 2 | 3991 | 10823 | 73% | 0.342 / 0.034 / 0.117 | 0.573 / 0.034 / 0.218 | 0.041 / 0.136 / 0.111 |
| sith | min12-ABDJKMN | 2 | 8639 | 9961 | 54% | 0.251 / 0.007 / 0.120 | 0.580 / 0.005 / 0.376 | 0.031 / 0.321 / 0.188 |
| xjq | min12-ABDJKMN | 2 | 814 | 3559 | 81% | 0.149 / 0.003 / 0.030 | 0.234 / 0.000 / 0.049 | 0.010 / 0.399 / 0.327 |
| ALL | min12-ABDJKMN | 12 | 22218 | 49643 | 69% | 0.264 / 0.018 / 0.094 | 0.481 / 0.015 / 0.207 | 0.034 / 0.204 / 0.152 |

- **ast-grep is mostly dilution.** The whole-snapshot share falls 62% under min12 (0.248 to
  0.094); in implementation files it falls 15% (0.312 to 0.264). min12 writes 3.8 times the
  test LOC (69% of its lines against 30%), and test lines rarely match a rule under either
  prompt. Implementation only, datagate, mvvault, sith and xjq improve by a fifth to a third;
  file_merger and rejector do not move.
- **Fewer flagged lines all the same.** min12 writes 26% less implementation (22k LOC against
  30k), so its flagged implementation lines fall 38% (9412 to 5870).
- **Erosion has the same shape with more left over.** Down 69% over the whole snapshot (0.660
  to 0.207), 25% in implementation files (0.639 to 0.481). datagate, mvvault and xjq halve or
  better; file_merger drops a third; rejector and sith move 15% to 20%.
- **The tests differ in kind.** just-solve's test files erode worse than its implementation
  (0.745): a few long test functions. min12's are near zero (0.015): many small ones. So min12's
  tests pull erosion down twice, by adding low-complexity mass and by having no high-complexity
  functions of their own.
- **Clones are the tests.** Implementation cloned% falls under min12 (0.045 to 0.034). Its
  tests are 0.204 cloned against just-solve's 0.058, which is the whole rise.
- **Test ast%.** just-solve's 0.102 is one datagate run where two whole-function rules
  (`defensive-try-soup-function`, `defensive-except-exception-heavy`) cover most of a test
  file; its other problems sit at 0.007 to 0.040, min12's at 0.003 to 0.034. scb-check's human
  report also lists about 2000 `section-banner-comment` hits in min12's tests (comment rules
  like `# ---- helpers ----`). They do not reach the score: all of min12's tests hold 901 flagged LOC.

## The same split on human repositories (2026-09-18)

The paper's human reference (arXiv 2603.24755v1, Table 7) is 48 repositories at HEAD "with
documentation and generated code excluded". Tests are not excluded, and its LOC column only
fits whole repositories (requests 11k, flask 18k). To check, `bin/quality-split --tree` ran
on shallow clones of the Major tier (over 10k stars) at their 2026-09-18 HEADs: 27 of the 28,
because Ciphey is now Rust and has no Python left. The whole tier took about 25 minutes of
scb-check 0.1.3, airflow's 1.1M LOC about six of them. `docs/` and `doc/` are skipped; the
result is report/human-split.json, which the uplift page reads for its human row.

| mean of 27 repos | impl | tests | whole repo |
|---|---|---|---|
| ast% | 0.124 | 0.019 | 0.063 |
| erosion | 0.444 | 0.164 | 0.309 |
| cloned% | 0.079 | 0.113 | 0.100 |

- **Humans are diluted the same way.** Tests are 58% of their lines (43% to 76%), between
  just-solve's 30% and min12's 69%. Human test code scores like min12's on ast% (0.019 against
  0.018) and erodes more (0.164 against 0.015).
- **Erosion reproduces the paper.** Whole-repo mean 0.309 against the paper's 0.31, and the
  per-repo values agree to a few hundredths (django 0.290 and 0.285, salt 0.542 and 0.555).
  Implementation against implementation: human 0.44, min12 0.36, just-solve 0.56, each the
  mean of per-problem (or per-repository) values at the final checkpoint. min12 stays under
  the human code without its tests, by less: 0.16 against 0.31 on whole snapshots. The pooled
  ALL row above says 0.48 because pooling weighs by size and sith is 8.6k of min12's 22k
  implementation LOC at 0.58; do not set a pooled figure beside the human mean.
- **ast% does not reproduce.** Our whole-repo mean is 0.063 against the paper's 0.10, and single
  repos differ both ways (django 0.041 against 0.113, click 0.059 against 0.163, tqdm 0.102
  against 0.071), so the paper's table used another rule set or version. With one tool version
  on both sides, min12's whole-snapshot 0.094 is above the human 0.063, and in implementation
  files it is about twice the human share (0.250 against 0.124 as a mean of problems, 0.264 pooled;
  just-solve 0.303).
  The uplift page's human bars are this rerun (bin/grid reads report/human-split.json), with a
  switch for implementation files only; the paper's 0.10 is named on the page, not drawn.
- **Clones.** min12's implementation is less cloned than human code (0.034 against 0.079); its
  tests are 1.8 times as cloned as human tests (0.204 against 0.113).
- Caveat: the human figures are means of per-repository values, as the paper reports them. The
  ALL rows of the dev-set table pool the twelve runs of a prompt, which weighs problems by
  size; the uplift page's table takes the mean of the six per-problem rows instead (ast-grep
  0.303 to 0.250 implementation only, erosion 0.563 to 0.360). Final checkpoint only.

| repo | impl LOC | test LOC | test share | ast impl / test / all | erosion impl / test / all | cloned impl / test / all |
|---|---|---|---|---|---|---|
| tqdm | 3273 | 2490 | 43% | 0.173 / 0.008 / 0.102 | 0.582 / 0.381 / 0.492 | 0.038 / 0.050 / 0.048 |
| requests | 3594 | 3980 | 53% | 0.136 / 0.013 / 0.071 | 0.431 / 0.018 / 0.240 | 0.038 / 0.044 / 0.042 |
| flask | 4336 | 6005 | 58% | 0.120 / 0.027 / 0.066 | 0.264 / 0.225 / 0.238 | 0.061 / 0.052 / 0.056 |
| thefuck | 4598 | 5988 | 57% | 0.050 / 0.002 / 0.023 | 0.013 / 0.016 / 0.014 | 0.073 / 0.088 / 0.081 |
| httpx | 5773 | 6442 | 53% | 0.099 / 0.034 / 0.065 | 0.233 / 0.207 / 0.217 | 0.161 / 0.171 / 0.166 |
| uvicorn | 5946 | 6785 | 53% | 0.151 / 0.019 / 0.081 | 0.488 / 0.089 / 0.281 | 0.108 / 0.120 / 0.114 |
| cli | 7339 | 6052 | 45% | 0.072 / 0.021 / 0.049 | 0.294 / 0.045 / 0.191 | 0.012 / 0.067 / 0.037 |
| jinja | 8456 | 6281 | 43% | 0.102 / 0.007 / 0.062 | 0.378 / 0.077 / 0.266 | 0.036 / 0.281 / 0.140 |
| click | 7144 | 11460 | 62% | 0.117 / 0.023 / 0.059 | 0.424 / 0.146 / 0.276 | 0.061 / 0.043 / 0.051 |
| locust | 10050 | 14116 | 58% | 0.153 / 0.012 / 0.070 | 0.579 / 0.103 / 0.429 | 0.065 / 0.125 / 0.101 |
| poetry | 17034 | 37352 | 69% | 0.131 / 0.013 / 0.050 | 0.624 / 0.195 / 0.383 | 0.028 / 0.088 / 0.070 |
| mitmproxy | 38530 | 29274 | 43% | 0.121 / 0.023 / 0.079 | 0.402 / 0.321 / 0.365 | 0.072 / 0.063 / 0.068 |
| scrapy | 22274 | 46073 | 67% | 0.088 / 0.018 / 0.041 | 0.149 / 0.170 / 0.164 | 0.038 / 0.143 / 0.109 |
| pytest | 25727 | 45051 | 64% | 0.133 / 0.015 / 0.058 | 0.358 / 0.144 / 0.240 | 0.036 / 0.142 / 0.104 |
| aiohttp | 20281 | 52798 | 72% | 0.127 / 0.015 / 0.046 | 0.522 / 0.128 / 0.245 | 0.070 / 0.166 / 0.140 |
| celery | 29408 | 47393 | 62% | 0.125 / 0.023 / 0.062 | 0.385 / 0.127 / 0.241 | 0.036 / 0.112 / 0.084 |
| fastapi | 21599 | 68695 | 76% | 0.073 / 0.006 / 0.022 | 0.521 / 0.049 / 0.203 | 0.258 / 0.246 / 0.250 |
| pydantic | 37909 | 86725 | 70% | 0.124 / 0.022 / 0.053 | 0.561 / 0.140 / 0.280 | 0.078 / 0.090 / 0.086 |
| ansible | 78068 | 75245 | 49% | 0.214 / 0.072 / 0.144 | 0.660 / 0.453 / 0.586 | 0.067 / 0.081 / 0.077 |
| great_expectations | 118886 | 115209 | 49% | 0.113 / 0.020 / 0.067 | 0.387 / 0.148 / 0.277 | 0.122 / 0.118 / 0.120 |
| scikit-learn | 123601 | 122144 | 50% | 0.082 / 0.013 / 0.048 | 0.550 / 0.253 / 0.416 | 0.067 / 0.038 / 0.053 |
| statsmodels | 126783 | 156101 | 55% | 0.094 / 0.012 / 0.049 | 0.508 / 0.224 / 0.420 | 0.073 / 0.070 / 0.071 |
| scipy | 130169 | 174503 | 57% | 0.131 / 0.018 / 0.066 | 0.608 / 0.173 / 0.443 | 0.080 / 0.089 / 0.086 |
| django | 111351 | 284381 | 72% | 0.127 / 0.007 / 0.041 | 0.476 / 0.030 / 0.290 | 0.078 / 0.130 / 0.116 |
| sqlalchemy | 130003 | 316961 | 71% | 0.116 / 0.016 / 0.045 | 0.504 / 0.187 / 0.335 | 0.099 / 0.129 / 0.121 |
| salt | 296898 | 337105 | 53% | 0.277 / 0.037 / 0.149 | 0.701 / 0.239 / 0.542 | 0.151 / 0.192 / 0.173 |
| airflow | 439812 | 678718 | 61% | 0.094 / 0.010 / 0.043 | 0.394 / 0.137 / 0.261 | 0.121 / 0.126 / 0.125 |

## Code pairs page (2026-09-18)

`report/quality-examples.html` (`python3 report/quality_examples.py`, manifest
`report/quality-examples.json`) shows one hand-picked pair per measure plus one cloned-test
blowup, all chosen to show min12 at its best. They came from 21 candidates, six per measure:
three picked for the bad just-solve code before looking at min12's side, three picked for
the contrast. What the bad-first candidates showed, implementation files only:

- ast-grep: none came out clean. xjq's JSON type ladder is line for line the same (12 hits
  on both sides), mvvault's source validation 9 to 6, sith's expression inference 32 to 6,
  and the other sith run has the same job at 27.
- erosion: three of six barely move (xjq `main` CC 25 to 25, rejector's JSON Schema
  validator 48 to 43, sith narrowing 36 to 32); the others roughly halve and stay over 10.
- clones: datagate's repeated-parameter check is pasted three times on both sides; the
  clean pairs all replace copies with a shared helper or a table.
- The two min12 runs of a problem often disagree on the same job, and two of the clean
  contrast pairs were clean partly because min12's code does less.
- Cloned tests: one-assert tests that a parametrize would collapse (23 copies in xjq, 15 in
  sith), and in rejector a 19-line helper pasted into five test files beside a shared
  conftest.

## The anti-slop chunk moves the implementation (min13, 2026-09-18)

min13-ABDJKMNT is min12-ABDJKMN plus chunk T: the code-quality bullets of upstream's
`anti_slop.jinja`, word for word, as the whole Implement section (`configs/prompts/min13-chunks/`).
Nothing in it mentions tests. One run each on mvvault and rejector, opus-5, spec v0, to ask
whether ast% falls on the implementation files alone. It does, on both. Final checkpoint,
`bin/quality-split`, implementation files only:

| problem | prompt | impl LOC | test share | ast impl | erosion impl | cloned impl | score |
|---|---|---|---|---|---|---|---|
| mvvault | just-solve, 2 runs pooled | 3967 | 35% | 0.338 | 0.456 | 0.032 | 221, 214 |
| mvvault | min12-ABDJKMN, first | 1590 | 79% | 0.235 | 0.218 | 0.034 | 220 |
| mvvault | min12-ABDJKMN, repeat | 1711 | 75% | 0.199 | 0.125 | 0.029 | 223 |
| mvvault | min13-ABDJKMNT | 1457 | 73% | 0.132 | 0.036 | 0.014 | 215 |
| rejector | just-solve, 2 runs pooled | 5556 | 46% | 0.334 | 0.709 | 0.062 | 73, 76 |
| rejector | min12-ABDJKMN, first | 1862 | 73% | 0.339 | 0.608 | 0.030 | 75 |
| rejector | min12-ABDJKMN, repeat | 2129 | 73% | 0.344 | 0.539 | 0.051 | 76 |
| rejector | min13-ABDJKMNT | 1845 | 68% | 0.188 | 0.172 | 0.019 | 74 |

Reading:

- This is not dilution. The test share is a little lower than min12's on both problems, and
  the number is the implementation's own. On rejector min12 had left implementation ast where
  just-solve had it (0.34 against 0.334); min13 takes it to 0.188. The two min12 runs there are
  0.005 apart, so one min13 run sits far outside what we have seen a seed do.
- On mvvault min12 already beat just-solve; min13 is below both min12 runs by more than they
  differ from each other (0.132 against 0.199 and 0.235).
- Implementation erosion fell with it, 0.17 to 0.04 on mvvault and 0.57 to 0.17 on rejector,
  though nothing in chunk T names complexity except "heavy nesting" and "if/else ladders".
- The implementation did not shrink much (mvvault 1457 lines against 1590 and 1711, rejector
  1845 against 1862 and 2129), so ast% fell because fewer lines are flagged, not because the
  denominator moved.
- Score: level. mvvault's 215 is 222 without the seven tests any `requests` solution loses
  (`notes/upstream-prs.md`); rejector's 74 is one and two below the min12 pair, on a retry-count
  reading its registry scored at Risk 45 and a cost rounding.

### Which rules stopped firing

`bin/ast-rules --prompts min12-ABDJKMN,min13-ABDJKMNT --problem mvvault` (and `rejector`):
flagged lines per 1000 LOC, implementation files only, final checkpoint. Lines and LOC are
counted as scb-check counts them (no blanks, comments or docstrings), so the first row is ast%
times 1000 and the tool's union of all rules reproduces it: exactly for all four min12 runs,
within 3 for the two min13 runs. A line under two rules counts in both rows.

| rule | mvvault min13 | min12 a | min12 b | rejector min13 | min12 a | min12 b |
|---|---|---|---|---|---|---|
| scb-check ast | 132 | 235 | 199 | 188 | 339 | 344 |
| function-with-many-type-guards | 78 | 57 | 80 | 99 | 196 | 187 |
| defensive-function-isinstance-heavy | 0 | 0 | 33 | 17 | 125 | 94 |
| defensive-isinstance-raise-heavy | 0 | 18 | 21 | 0 | 64 | 93 |
| defensive-validator-returnmix | 0 | 36 | 8 | 5 | 49 | 42 |
| defensive-except-exception-heavy | 0 | 27 | 30 | 0 | 25 | 0 |
| defensive-try-soup-function | 0 | 36 | 0 | 0 | 0 | 26 |
| isinstance-guard-raise | 20 | 16 | 23 | 22 | 24 | 29 |
| defensive-validator-function | 70 | 0 | 0 | 96 | 0 | 0 |
| defensive-fstring-raise-heavy | 20 | 0 | 0 | 62 | 0 | 0 |
| rules under 5 (mvvault) or 15 (rejector) everywhere, summed | 14 | 37 | 30 | 76 | 110 | 96 |

- The drop is the whole-function rules. Each flags every line of a function it judges
  defensive (broad excepts, try blocks stacked in one function, isinstance-then-raise runs,
  validators that mix return types), so a handful of hits is a lot of lines. They go to zero
  or near it on both problems. That is the first gotcha in chunk T, "extra defensive checks or
  try/catch blocks that are abnormal".
- The raw code agrees. mvvault: 25 `try:` against 38 and 32, one broad `except` against 11
  and 11, 20 `isinstance(` against 39 and 65. rejector: 12 `try:` against 25 and 36, 48
  `isinstance(` against 71 and 102.
- The single inline type check (`isinstance-guard-raise`) did not move. What is left of the
  type checking moved into dedicated validator functions, which trip two rules min12 never
  hit: `defensive-validator-function` and `defensive-fstring-raise-heavy`. On mvvault those
  validators are in `legacy.py` and `source.py`, the malformed v1/v2 entry and source-response
  checks the spec's error rows ask for. So part of what remains may be a floor the spec sets,
  and part is ast-grep naming the same checks differently once they are gathered in one place.
  On rejector `function-with-many-type-guards` halved; on mvvault it did not move.
- The long tail shrank too: the many small rules sum to 14 against 37 and 30 on mvvault, 76
  against 110 and 96 on rejector.
- Comments are not in it. `section-banner-comment` fires 22 to 30 times in three of the four
  min12 runs' implementations and never in min13's, and comment lines fell (rejector 5 against 80 and 88; mvvault
  50 against 90 and 62) while mvvault's docstrings rose from about 80 to about 130. So
  "documented appropriately" and "extra comments a human wouldn't add" both landed, but a
  comment is not a line of code to scb-check: those hits add nothing to ast%, and their going
  away is none of the drop. An earlier reading of this run, by hit count, credited the banners
  with the checkpoint-1 gap. By lines it is the same whole-function rules as at the end:
  mvvault checkpoint 1 is 227 against 323 and 384, with except-exception-heavy (0 against 61
  and 83), isinstance-raise-heavy, try-soup and validator-returnmix at zero and
  function-isinstance-heavy halved.
- Layout changed completely: a package of 27 files (mvvault) and 25 (rejector), none long,
  where every min12 and just-solve run wrote one file of 2300 to 3500 lines. "Group functions
  into files" did that.

Open: one run per problem, two problems, both on the dev side. The twice bar needs a second
run of each. Whether the validator floor is spec-driven would show on a problem with few error
rows. Which of chunk T's bullets does the work is untested; T is one chunk, and splitting it
(file grouping, the defensive gotcha, the comment gotcha) would let the subset search answer.
Runs: `…min13-ABDJKMNT/20260918T1850` (mvvault) and `…/20260918T2129` (rejector); ledger rows in
`notes/mvvault-runs.md` and `notes/rejector-runs.md`.
