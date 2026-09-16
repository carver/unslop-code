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
- **The page**: `report/uplift-grid.html`, built by `python3 report/uplift_grid.py` from
  `bin/grid --json`; three headline bars, five 2x2 squares averaged over the patched
  problems, then per-problem dumbbells for every figure. The erosion headline carries a
  human reference: the paper's Major tier (10k+ stars, 115 repos) at HEAD, erosion 0.37,
  Table 2 of arXiv 2603.24755v2. Table 2 has no ast-grep column, so that chart has none.
- **datagate's residual five** are the whitespace-preservation tests, left as a benchmark
  failure by decision (see the datagate diary, 2026-09-14): the spec never mentions
  whitespace, and two of the four v2 runs registered stripping as their choice anyway.
