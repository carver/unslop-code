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
  Implementation against implementation: human 0.44, min12 0.48, just-solve 0.64. min12 is
  level with the human code, not under it; the whole-snapshot 0.21 against 0.31 is its tests.
- **ast% does not reproduce.** Our whole-repo mean is 0.063 against the paper's 0.10, and single
  repos differ both ways (django 0.041 against 0.113, click 0.059 against 0.163, tqdm 0.102
  against 0.071), so the paper's table used another rule set or version. With one tool version
  on both sides, min12's whole-snapshot 0.094 is above the human 0.063, and in implementation
  files it is 2.1 times the human share (0.264 against 0.124; just-solve 0.312, 2.5 times).
  The uplift page's human ast-grep bar still uses the paper's 0.10.
- **Clones.** min12's implementation is less cloned than human code (0.034 against 0.079); its
  tests are 1.8 times as cloned as human tests (0.204 against 0.113).
- Caveat: the human figures are means of per-repository values, as the paper reports them;
  ours pool the twelve runs of a prompt. Final checkpoint only.

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
