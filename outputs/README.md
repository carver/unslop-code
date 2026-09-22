# Committed runs

outputs/ is gitignored. The runs here are force-added: the 88 Opus 5 runs that
`bin/grid` draws on the six dev problems, for the prompts just-solve, anti_slop,
min12-ABDJKMN and min13-ABDJKMNT, at spec v0 and at each problem's patched
spec. Run directories on older spec versions and partial runs are not
committed. A fresh clone gives the same `bin/grid` table as the original
checkout.

## Harness

Every run used [SprocketLab/slop-code-bench](https://github.com/SprocketLab/slop-code-bench)
at `06b5c0687d4c05ee502e9696a4d0c22fc1eec5e0` plus the source patches in
`patches/`. `python3 install.py` clones that commit into `harness/`, applies
the patches and builds the venv `bin/scb` runs. The pin is `HARNESS_COMMIT` in
install.py, and the README lists the patches.

Two exceptions, both from before install.py built the checkout:

- Until 2026-09-10 runs read the development clone at `slop-code-bench/`. Its
  reflog shows HEAD at 06b5c06 from the clone on 2026-08-29 through
  2026-09-10, so the base commit is the same.
- `dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` had only the
  stream-parser patch (notes/dev6-opus5.md). The other five did not exist yet.
  Every other run started after all six were committed.

Each run used Claude Code 2.1.251 with thinking high, as the directory names say.

## Files not committed

Agent transcripts (`agent/stdout.jsonl`, `agent/workspace/`) are not
committed. Three kinds of files the harness writes are left out too:

- `quality_analysis/symbols.jsonl`. `bin/scb metrics static <run dir>` rebuilds
  it byte for byte. It also rewrites the committed `files.jsonl` and
  `overall_quality.json`. In the two runs tested it marked no file as the
  entry file, so run it on a copy.
- `diff.json`. `bin/scb utils repopulate-diffs <run dir>` diffs each snapshot
  against the one before it. The originals used another base, so the rebuilt
  files differ from them.
- `evaluation/`, the hidden-test reports. `bin/scb eval <run dir>` reruns the
  tests in Docker. The committed `checkpoint_results.jsonl` and
  `evaluation.json` hold the scores the runs got. A rerun can differ: rejector's
  mock server has a race at checkpoint 2.

Before force-adding another run, redact the OAuth token in its `infer.log`.
The harness's docker exec debug line writes it unmasked.
