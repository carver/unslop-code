# What the leaderboard and paper pin down for the target row

Sources read 2026-08-29: https://snorkel.ai/leaderboard/slopcode-bench/ (embedded
JSON), https://scbench.ai/leaderboard (Next.js payload), arXiv 2603.24755v2
(HTML, 2026-05-07).

## Target row (identical on both leaderboard pages)

```json
{"model": "Sonnet 4.6", "thinking": "High", "agent": "Claude Code", "agentVersion": "2.1.44",
 "pct_problems_solved": 0, "pct_checkpoints_solved": 7.142857,
 "pct_checkpoints_iso_solved": 16.836735, "pct_checkpoints_core_solved": 56.122449,
 "cost_per_checkpoint": 1.958314, "erosion_mean": 0.741448, "verbosity_mean": 0.316333,
 "violation_pct_mean": 0.297997, "clone_pct_mean": 0.092606, "rank": 13}
```

7.142857% of 196 = 14 strict-solved checkpoints; 16.836735% = 33 iso; 56.122449% = 110 core.
`violation_pct_mean` is the "% AST-Grep" column; `clone_pct_mean` is "% Cloned".

## Paper (v2) facts that matter for reproduction

- Table 7: Sonnet 4.6, Claude Code 2.1.44, reasoning high. Section C.3: just-solve
  is "the minimal baseline used for all primary evaluations".
- Setup paragraph: "Each checkpoint runs in a fresh Docker container as a non-root
  user; only the working directory persists between checkpoints." "Each run has a
  two-hour wall-clock limit, no turn or cost cap."
- Table 1 Sonnet 4.6 row: strict 7.1, iso 16.8, core 57.7, partial 27.8,
  $/ckpt 1.96 +/- 1.97, net $383.83, 14.2 +/- 14.2 min/ckpt, erosion 0.75 +/- 0.20,
  verbosity 0.44 +/- 0.19.
- Table 1 caption: solve rates use a fixed 196-checkpoint denominator, missing
  checkpoints count as unsolved; other metrics only over ran checkpoints; the row is
  the model's best just-solve run.

## Differences to keep in mind

1. Turn cap. Our agent config keeps the repo default `step_limit: 100`
   (`--max-turns 100`) and adds `timeout: 3600` per checkpoint, because the plan
   asked for hard caps. The paper ran with no turn cap and a 2 h wall-clock limit.
   If any checkpoint ends at exactly 100 steps or with a max-turns result, the cap
   bound and the checkpoint is not comparable. Checked in the report.
2. Quality scale. Paper v2 reports verbosity 0.44 for this row; the leaderboard
   reports 0.316 and core 56.1 vs the paper's 57.7. So the leaderboard was
   recomputed after the paper, presumably with the scb-check-based metrics that
   landed in the repo after v0.3 (commits 3bf49df, 8e3a8b6, scb-check 0.1.3). We
   compute with scb-check 0.1.3, which is the closest available match, but the
   exact release used for the leaderboard is not stated anywhere I could find.
3. Per-problem numbers. None published: the leaderboard payloads carry only
   per-run aggregates, scbench.ai/problems carries problem descriptions, and the
   paper has no per-problem table. A 6-problem subset therefore has no exact
   leaderboard counterpart; the comparison is subset-vs-36 with the caveat stated.
4. scbench.ai/problems lists file_backup as "medium" (v0.2 metadata); the v1.0
   catalog config says Easy. Cosmetic, but note the site is not the source of truth.

## Published page

The report is also an artifact: https://claude.ai/code/artifact/d4db605f-59b1-4a23-aa50-6ae72dc36dc1
(private until shared). Regenerate with `python3 report/build.py` (reads the latest
outputs/dev6 run and report/template.html, writes report/scbench-baseline.html) and republish
to the same URL.
