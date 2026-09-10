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
