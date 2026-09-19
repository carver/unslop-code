# The 2x2 uplift grid (2026-09-14/15)

Two effects, measured in both orders: the prompt (benchmark's just-solve against
min12-ABDJKMN, the 444-word no-F subset) and the spec patch (v0 against the version that
first went 100%: datagate v2, xjq v3, file_merger v6). Two complete opus-5 runs per cell,
jobs 149-169; the F-clause prompt (min12-ABDFJKMN) does not count anywhere. Numbers from
`notes/results.md`; per-run detail in each problem's ledger. Score is the cell mean;
erosion / ast% are the cell means of the quality scores (lower is better); $ is cc_$ per run.

## Score

| problem | just-solve v0 | min12 v0 | min12 patched | just-solve patched |
|---|---|---|---|---|
| datagate (v2) | 377, 380 | 381, 376 | 400, 400 | 400, 392 |
| xjq (v3) | 160, 160 | 160, 161 | 167, 167 | 167, 167 |
| file_merger (v6) | 116, 138 | 139, 139 | 147, 147 | 142, 145 |
| mvvault | 221, 214 | 220, 223 | | |
| rejector | 73, 76 | 75, 76 | | |
| sith | 191, 194 | 205, 204 | | |

## Quality (erosion / ast%) and cost

| problem | just-solve v0 | min12 v0 | min12 patched | just-solve patched |
|---|---|---|---|---|
| datagate | 0.597 / 0.323, $12 | 0.037 / 0.087, $20 | 0.124 / 0.089, $19 | 0.643 / 0.477, $13 |
| xjq | 0.376 / 0.184, $5 | 0.031 / 0.032, $10 | 0.043 / 0.028, $11 | 0.410 / 0.196, $6 |
| file_merger | 0.718 / 0.221, $19 | 0.199 / 0.100, $22 | 0.258 / 0.069, $22 | 0.702 / 0.140, $16 |
| mvvault | 0.520 / 0.265, $14 | 0.060 / 0.078, $27 | | |
| rejector | 0.637 / 0.214, $35 | 0.172 / 0.114, $28 | | |
| sith | 0.626 / 0.274, $51 | 0.375 / 0.136, $39 | | |

## Reading

- **Correctness comes from the spec, not the prompt.** On the three patched problems the
  spec step moves every cell to or near the ceiling in both orders (datagate +20, xjq +7,
  file_merger +8 to +12 for min12; just-solve gains the same on xjq and file_merger). The
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
  min12 0.15 to 0.17. Implementation-only rescoring has no verbosity, since the split keeps only
  the ast-grep, clone and complexity counts; the verbosity row shows the paper's lines alone under
  the switch.
- **datagate's residual five** are the whitespace-preservation tests, left as a benchmark
  failure by decision (see the datagate diary, 2026-09-14): the spec never mentions
  whitespace, and two of the four v2 runs registered stripping as their choice anyway.
