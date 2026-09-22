# The 2x2 uplift grid (2026-09-14/15)

Two effects, measured in both orders: the prompt (benchmark's just-solve against
min12-ABDJKMN, the 444-word no-F subset) and the spec patch (v0 against the version that
first went 100%: datagate v2, xjq v3, file_merger v7; v6 until 2026-09-21, when v7's pairs
landed and replaced it on the page). Two complete opus-5 runs per cell,
jobs 149-169; the F-clause prompt (min12-ABDFJKMN) does not count anywhere. Numbers from
`notes/results.md`; per-run detail in each problem's ledger. Score is the cell mean;
erosion / ast% are the cell means of the quality scores (lower is better); $ is cc_$ per run.

## Score

| problem | just-solve v0 | min12 v0 | min12 patched | just-solve patched |
|---|---|---|---|---|
| datagate (v2) | 377, 380 | 381, 376 | 400, 400 | 400, 392 |
| xjq (v3) | 160, 160 | 160, 161 | 167, 167 | 167, 167 |
| file_merger (v7) | 116, 138 | 139, 139 | 146, 144 | 147, 144 |
| mvvault (v1) | 221, 214 | 220, 223 | 224, 227 | 226, 223 |
| rejector (v1) | 73, 76 | 75, 76 | | 79, 78 |
| sith | 191, 194 | 205, 204 | | |

## Quality (erosion / ast%) and cost

| problem | just-solve v0 | min12 v0 | min12 patched | just-solve patched |
|---|---|---|---|---|
| datagate | 0.597 / 0.323, $12 | 0.037 / 0.087, $20 | 0.124 / 0.089, $19 | 0.643 / 0.477, $13 |
| xjq | 0.376 / 0.184, $5 | 0.031 / 0.032, $10 | 0.043 / 0.028, $11 | 0.410 / 0.196, $6 |
| file_merger | 0.718 / 0.221, $19 | 0.199 / 0.100, $22 | 0.216 / 0.069, $22 | 0.552 / 0.153, $17 |
| mvvault | 0.520 / 0.265, $14 | 0.060 / 0.078, $27 | 0.069 / 0.087, $28 | 0.333 / 0.355, $15 |
| rejector | 0.637 / 0.214, $35 | 0.172 / 0.114, $28 | | 0.682 / 0.162, $29 |
| sith | 0.626 / 0.274, $51 | 0.375 / 0.136, $39 | | |

## Two more arms (2026-09-20)

anti-slop is the benchmark's upstream `anti_slop` prompt as shipped, the paper's Anti-Slop arm.
min13-ABDJKMNT is min12 with that prompt's rule list appended as chunk T; the page calls it
spectest+antislop. Both have two runs per cell since 2026-09-21, when anti-slop's second pass
(jobs 241 to 246) and its patched pairs landed. file_merger's grid version is v7 since the same
day: all four prompts have a pair there (jobs 253 to 260). On v6 the pairs were just-solve 142 and
145, min12 147 and 147, min13 147 and 145; anti-slop never ran on v6.

| problem | anti-slop v0 | min13 v0 | min13 patched |
|---|---|---|---|
| datagate (v2) | 379, 381 | 383, 385 | 393, 401 |
| xjq (v3) | 155, 155 | 162, 162 | 167, 167 |
| file_merger (v7) | 138, 139 | 127, 127 | 147, 147 |
| mvvault (v1) | 213, 213 | 215, 216 | 227, 225 |
| rejector (v1) | 73, 74 | 73, 74 | 78, 78 |
| sith | 189, 202 | 195, 211 | |

anti-slop patched: datagate v2 393 and 396, xjq v3 167 and 167, file_merger v7 146 and 147, mvvault v1 222
and 224, rejector v1 77 and 78. min12 has no patched runs on rejector (not queued; usage was tight).

Erosion / ast% and cost, as above:

| problem | anti-slop v0 | min13 v0 | min13 patched |
|---|---|---|---|
| datagate | 0.000 / 0.066, $13 | 0.000 / 0.053, $18 | 0.003 / 0.053, $20 |
| xjq | 0.000 / 0.138, $5 | 0.000 / 0.016, $11 | 0.016 / 0.025, $9 |
| file_merger | 0.012 / 0.060, $19 | 0.021 / 0.036, $22 | 0.003 / 0.032, $26 |
| mvvault | 0.000 / 0.217, $17 | 0.004 / 0.048, $29 | 0.000 / 0.048, $26 |
| rejector | 0.040 / 0.106, $36 | 0.024 / 0.074, $33 | 0.032 / 0.067, $36 |
| sith | 0.013 / 0.053, $43 | 0.001 / 0.036, $46 | |

- **anti-slop removes erosion and buys little correctness.** Over six problems at v0, two runs
  each, erosion goes from just-solve's 0.58 to 0.011, and hidden tests failed from 8.3% to 7.8%
  (the one-run figure was 8.4%; sith's repeat, 202 after 189, moved it). ast-grep falls less
  far, 0.25 to 0.11, and barely moves on mvvault (0.217). It writes the least code, 62% of
  just-solve's lines, and is the fastest arm at 67 minutes against 80, for $22 against $23. With
  the test files left out: erosion 0.004, ast-grep 0.137, cloned 0.009 on 1371 implementation
  lines per run against just-solve's 2515. The second pass repeated the first closely: xjq 155
  and 155 on the same twelve misses, mvvault 213 and 213, datagate 379 and 381; sith is the wide
  one. Its minutes from 2026-09-20 on overlap the specpatch channel in places.
- **min13 keeps min12's tests and takes anti-slop's erosion.** Erosion 0.008 against min12's
  0.15, ast-grep 0.04 against 0.09, which is the lowest of the four arms, and cloned lines stay
  at min12's level (0.15 against 0.17) because the clones are in the tests. With the test files
  left out the gap to min12 is wider, not narrower: erosion 0.021 against 0.328, ast-grep 0.117
  against 0.264, cloned 0.013 against 0.028, on 1468 lines against 1852. The 2026-09-18 split
  put most of min12's gain down to its test files (implementation erosion 0.53 to 0.33,
  ast-grep 0.30 to 0.26); chunk T cleans the implementation itself. On the patched
  specs the same holds, erosion 0.030 and ast-grep 0.086 against min12's 0.358 and 0.195 (over the
  three problems patched before mvvault v1; not recomputed with it).
- **min13 gives some score back at v0.** 7.5% of hidden tests failed against min12's 5.5% and
  just-solve's 8.3%. The loss is file_merger's checkpoint-2 TSV and mixed-format family, twelve
  tests in both runs (127, 127 against 139, 139), and about six on mvvault; datagate gains five
  and sith is level. On the patched specs it turns round: over the five patched problems
  (mvvault v1 and rejector v1 joined on 2026-09-21) 0.7% failed against just-solve's 1.0% and
  anti-slop's 1.3%, and min12's 0.8% over its four; the prompts inside two thirds of a point of
  each other. mvvault v1 is 227 and 225 for min13, 224 and 227 for min12, 226 and 223 for
  just-solve, 222 and 224 for anti-slop; rejector v1 is 78 and 78 for min13, 79 and 78 for
  just-solve, 77 and 78 for anti-slop.
  xjq is 167 for every run of every prompt; file_merger v7 is 147 and 147 for min13 against
  min12's 146 and 144; datagate 393 and 401 against 400 and 400. On v6 min13 had 147 and 145,
  the sub-second question (registry T8) that v7's sentence settled, and min12 147 and 147; its
  two v7 misses are a regression and an unpatched reading (the object key `list`), so the
  ordering between the prompts on patched specs is within noise
  (`notes/solve-rate-min13-vs-antislop.md`). Causes per run are in each problem's ledger.
- **min13 is the dearest arm at v0**, $27 and 97 minutes against min12's $24 and 87, most of it
  on sith (184 minutes) and mvvault (114). On the five patched specs it is $24 and 74 minutes against
  just-solve's $16 and 61; min12 is $20 and 72 over its four.

## Reading

- **Correctness comes from the spec, not the prompt.** On the patched problems (five since rejector v1) the
  spec step moves every cell to or near the ceiling in both orders (datagate +20, xjq +7,
  file_merger +6 for min12 and +18 for just-solve on v7; just-solve gains the same on xjq). The
  prompt step at v0 is flat on datagate, xjq, mvvault and rejector, inside the bare
  prompt's own spread (file_merger's 116/138, mvvault's 221/214). sith is the exception:
  +13 both replicates, from the checkpoint-4 names and search families.
- **Quality comes from the prompt, not the spec.** Erosion drops by 4x to 12x on every
  problem at v0 (sith the least, 0.63 to 0.38), and the patched spec leaves just-solve's
  erosion where it was (datagate 0.60 to 0.64, xjq 0.38 to 0.41, file_merger 0.72 to 0.70).
  ast% follows erosion; verbosity is flat; cloned% rises under min12 (xjq 0.33 to 0.40 on a
  single 134 KB test module), the test-file dilution effect in `quality-test-dilution.md`.
- **Order does not matter for the endpoint.** min12 at the patched spec and just-solve at
  the patched spec reach the same score; only the quality differs, and that difference is
  the prompt's regardless of which step came first.
- **Cost and time.** min12 costs about 1.5x to 2x just-solve on the small problems and less
  on the large ones (rejector $28 against $35, sith $39 against $51), where the bare prompt's
  longer runs (144 and 164 min) are the expensive part. Averaged over six problems at v0:
  $24 against $23, 87 minutes against 80; on the patched specs $17 against $12 and 62 minutes
  against 47. Wall clock is the larger downside, and it includes waits on the 5-hour window.
- **ast-grep** follows erosion: 0.25 to 0.09 at v0 over six problems, 0.27 to 0.06 patched;
  the spec patch leaves just-solve's where it was (0.25 to 0.27).
- **As a share of just-solve, problem by problem.** Divide each problem's min12 value by its
  own just-solve value at v0 and average the six shares (`relative` in `bin/grid --json`).
  Erosion under min12 is 23% of just-solve's (-77%), from datagate's 6% to sith's 60%.
  ast-grep is 37% (-63%), from xjq's 18% to rejector's 53%. The human repositories, divided
  by the same six baselines, come to 56% and 27%, so on whole snapshots min12 lands under the
  10k-star repos on erosion and above them on ast-grep. This mean weighs every problem the
  same, so it differs from the ratio of the means above (0.15 / 0.58 is 25%).
- **Implementation files only (2026-09-18).** The page has a switch that rescores erosion
  and ast-grep with the test files left out, every checkpoint of every drawn run and the human
  repositories too (`bin/grid --json` carries it as `impl`). Over the six problems at v0:
  erosion 0.53 to 0.33 instead of 0.58 to 0.15, ast-grep 0.30 to 0.26 instead of 0.25 to 0.09;
  as shares of just-solve 57% and 89%, against the humans' 92% and 44%. Implementation only,
  min12's erosion also climbs along the run (0.27 to 0.36, just-solve 0.52 to 0.55), so the
  flat whole-snapshot line was its growing test suite. Background in
  `notes/quality-test-dilution.md`.
- **dev only, for now.** `bin/grid` reads the dev set of `split.json` unless told `--set test`
  or `--set all`. The test-set runs (jobs 170-199) are landing in the same outputs, and one
  of them has no min12 cell yet, which the page cannot draw.
- **The page**: `report/uplift-grid.html`, built by `python3 report/uplift_grid.py` from
  `bin/grid --json`; three headline bars, a second row with the two shares above (min12, its
  best-to-worst whisker, the human bar, just-solve as the 100% line), the Figure 5 overlay, five 2x2 squares averaged over
  the patched problems, then per-problem dumbbells for every figure. The erosion and ast-grep headlines
  carry a human reference: the paper's Major tier (over 10k stars), 27 of its 28 repos rescored
  at HEAD with scb-check 0.1.3 (`report/human-split.json`), erosion 0.31 and ast-grep 0.063,
  with a whisker from the lowest repo to the highest and a band for the middle half. Until
  2026-09-18 the bars were the paper's own Table 2 figures, 0.31 and 0.10; the rerun matches
  the first and not the second (another rule set), so the paper's 0.10 is named, not drawn.
- **Page changes, 2026-09-20.** The along-the-run section keeps the paper's GPT 5.5 lines only,
  the strongest of its three models, as four cards two to a row (GPT 5.3 Codex and GPT 5.4 are
  still in `report/paper_figure5.py`). A new headline card gives test code as a share of all
  lines at the final checkpoint, which does not follow the implementation-only switch:
  just-solve 27%, anti-slop 31%, spectest 72%, spectest+antislop 67%, the human repositories
  58%. The implementation-against-tests table has a row for every prompt, a runs column, and
  line counts per run, so anti-slop's six runs compare with the others' twelve; its test share
  is now the mean of the per-problem shares, as the human one is of repositories. Cards that
  draw patched cells name a prompt that does not cover every patched problem yet.
- **Quality charts without just-solve, shares of the human mean (2026-09-20).** just-solve is
  off the erosion, ast-grep, cloned and verbosity charts (headline bars, the four along-the-run
  cards with the paper's Baseline line, the per-problem panels): at 0.58 erosion it set a scale
  on which the three quality prompts could not be told apart, and anti-slop is the stronger
  reference. It stays where it is the control: failed tests, the spec-against-prompt squares,
  cost, wall clock and code size. The three share cards now divide by the mean of the 27 human
  repositories (`human_relative` in `bin/grid --json`), the user's call over my first plan of
  dividing by anti-slop, which cannot work: anti-slop's erosion is 0.000 on four problems and
  its cloned lines 0.000 on xjq and 0.005 on mvvault. Whole snapshot, anti-slop, spectest,
  spectest+antislop, with anti-slop's second pass in (2026-09-21): erosion 3%, 47%, 3% of the
  human mean; ast-grep 169%, 144%, 69%; cloned lines 25%, 173%, 149%. Implementation only:
  erosion 1%, 74%, 5%; ast-grep 110%, 213%, 95%; cloned 11%, 35%, 16%. So spectest+antislop is
  the one prompt under the human mean on ast-grep in both scopes, and spectest alone is at twice
  the human implementation figure. On anti-slop's first runs alone the figures were erosion 1%
  and 0%, ast-grep 162% and 106%, cloned 28% and 8%. The implementation-against-tests table follows
  suit: no just-solve row, and its paragraphs set each prompt beside anti-slop in values, never
  as a ratio of a score, since anti-slop's implementation erosion is 0.000. Read that way the
  test dilution is plain: spectest's ast-grep equals anti-slop's over the whole snapshot (0.085
  against 0.086) and is twice it in implementation files (0.250 against 0.116), with 489
  flagged implementation lines per run against 157; spectest+antislop is level with anti-slop
  in implementation files (0.106, 161 lines) and half of it over the whole snapshot (0.041).
- **Why anti-slop beats the paper's GPT 5.5 Anti-Slop line (0.00 against 0.15 to 0.26), a cut by
  problem length (2026-09-20).** Not because Opus 5 writes cleaner code unprompted: its just-solve
  erodes more than the paper's GPT 5.5 Baseline (0.56 to 0.61 against 0.40 to 0.55). Erosion is a
  threshold score, the share of complexity mass in functions above cyclomatic complexity 10
  (`harness/src/slop_code/metrics/checkpoint/mass.py`), and the shipped prompt's rules (no god
  functions, heavy nesting, if/else ladders) aim at that line. Functions above CC 10, all
  checkpoints of the v0 runs: just-solve 11.4%, spectest 8.1%, spectest+antislop 0.7%,
  anti-slop 0.5%, with no pile-up under the line (0.6% of anti-slop's functions at CC 9 or 10,
  93% at 5 or under). If long problems were what made the paper's line climb, ours should climb
  on them too. They do not. Erosion by checkpoint under anti-slop: datagate, seven checkpoints,
  0.000 at every one; mvvault, six, 0.000 at every one; sith, six, 0.056 at the first and 0.000
  at the five after; xjq and file_merger 0.000 throughout; rejector, five, is the one that ends
  above where it started, 0.000 for three checkpoints, then 0.033 and 0.025. spectest+antislop
  has the same shape: 0.000 throughout on datagate and xjq, under 0.01 on mvvault and sith, and
  rejector again the one climber, 0.000 to 0.043. So length is not it, and the reading left is
  obedience to a rule list that maps onto a threshold. Not checked: the paper's agent and
  effort for GPT, whether its runs used the prompt as the repo ships it today, and its problem
  mix. anti-slop has two runs per problem since 2026-09-21; the rows above are its first runs.
- **Erosion along the run, against the paper's Figure 5.** The v2 paper (arXiv 2603.24755v2)
  says erosion rises in 77% of agent trajectories, 0.026 per checkpoint, and that quality
  prompts lower the starting point "but do not slow the degradation" (its Figure 5, top row:
  every prompt on every GPT model climbs from Start to Final). Its five progress phases are
  Start (first checkpoint), Final (last) and the interior split into Early, Mid, Late; bin/grid
  applies the same phases to our v0 runs and pools each prompt's checkpoints per phase (twelve
  runs, six problems). Opus 5 just-solve: 0.56, 0.58, 0.55, 0.58, 0.61. min12: 0.14, 0.13,
  0.16, 0.13, 0.16. So just-solve climbs less than any paper model's Baseline (GPT 5.5 goes
  0.40 to 0.55) and min12 does not climb at all, which is the opposite of the paper's prompt
  finding. Per-run slopes agree: mean +0.006 per checkpoint for just-solve, +0.002 for min12,
  against the paper's 0.026. Caveats: two runs per problem, four to seven checkpoints, and the
  one problem with a clear min12 climb is rejector (0.09 to 0.22). The page draws the paper's
  nine lines from the figure's vector paths (`report/paper_figure5.py`) with our two on top,
  on one y axis; the paper's panels each have their own.
- **Cloned lines in the headline (added 2026-09-19).** At v0 over six problems: just-solve 0.04,
  min12 0.17, the rescored human repositories 0.10 (v1 Table 2 says 0.07). On the share scale min12
  is 843% of just-solve and the humans 376%, the one score where both sit above the bare prompt;
  the per-problem whisker runs from mvvault 216% to xjq 3283%. The implementation-only switch tells
  the story: min12's implementation clones are below just-solve's (0.034 against 0.046 pooled), the
  excess is all test files (notes/quality-test-dilution.md).
- **Verbosity, ast-grep and cloned lines along the run (added 2026-09-19).** Verbosity is the
  paper's Figure 5 bottom row (its share of lines flagged by ast-grep, the clone detector or the
  trivial-wrapper check), read out of the vector figure like erosion. Our v0 runs by phase, Start to
  Final: verbosity just-solve 0.26 to 0.30, min12 0.26 to 0.26, against paper Baseline climbs of
  0.00 to 0.09 and Anti-Slop of -0.02 to 0.07 across its three models; so on verbosity min12 sits
  on the paper's Baseline lines, not below them, because its test files are cloned. ast-grep (no
  paper figure): just-solve 0.23 to 0.26, min12 0.10 to 0.08. Cloned: just-solve 0.02 to 0.04,
  min12 0.15 to 0.17. Implementation only (the split cache keeps the verbosity line count since
  2026-09-19): just-solve 0.32 to 0.34, min12 0.30 to 0.28, so in the implementation the two
  prompts are close on verbosity and min12 does not climb; final-checkpoint means over six
  problems 0.33 against 0.30 at v0, 0.28 against 0.22 on the patched specs.
- **datagate's residual five** are the whitespace-preservation tests, left as a benchmark
  failure by decision (see the datagate diary, 2026-09-14): the spec never mentions
  whitespace, and two of the four v2 runs registered stripping as their choice anyway.
