# Committed runs

outputs/ is gitignored. The runs here are force-added by `bin/add-run`: the 88
Opus 5 runs that `bin/grid` draws on the six dev problems, for the prompts
just-solve, anti_slop, min12-ABDJKMN and min13-ABDJKMNT, at spec v0 and at each
problem's patched spec. Run directories on older spec versions and partial runs
are not committed. A fresh clone gives the same `bin/grid` table as the original
checkout.

## Adding or removing runs

```
bin/grid --runs | xargs bin/add-run     # the runs the grid draws
bin/add-run <run dir>...                # any others
bin/add-run --remove <run dir>...       # untrack; the files stay on disk
```

`bin/add-run` refuses partial runs and runs still being written. It redacts
Claude tokens, writes the diff metadata, and stages an allowlist of files, which
lives in the script. It then scans the staged files with gitleaks, rebuilds every
diff from a clean copy, and commits. Runs made since 2026-09-22 carry
`harness_provenance.jsonl`, one line per start or resume naming the harness build.
The runs below predate it.

## Harness

Every run used [SprocketLab/slop-code-bench](https://github.com/SprocketLab/slop-code-bench)
at `06b5c0687d4c05ee502e9696a4d0c22fc1eec5e0` plus the first six source
patches install.py applies. The last two, exec-log-masks-secrets and
run-records-harness-provenance, came on 2026-09-22, after every run here.
`python3 install.py` clones that commit into `harness/`, applies the patches
and builds the venv `bin/scb` runs. The pin is `HARNESS_COMMIT` in install.py,
and the README lists the patches.

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
committed, and neither are bytecode caches. Three kinds of files the harness writes are left out too:

- `quality_analysis/symbols.jsonl`. `bin/scb metrics static <run dir>` rebuilds
  it byte for byte. It also rewrites the committed `files.jsonl` and
  `overall_quality.json`. In the two runs tested it marked no file as the
  entry file, so run it on a copy.
- `diff.json`. `bin/diffs rebuild <run dir>` writes it back byte for byte from
  the snapshots and the committed `diff_meta.json`. The meta file holds what
  the snapshots can't give: the harness's archive checksums and times, the file
  order, and the base. A checkpoint that starts a resumed session diffs
  against an empty workspace, not the previous snapshot. `bin/scb-strict` runs
  every checkpoint as its own `--resume`, so that is every checkpoint after the
  first. The 2026-08-30 run ran in one process, except that file_merger
  resumed at checkpoint 2. The harness's own `utils repopulate-diffs` always
  uses the previous snapshot, so its output differs.
- `evaluation/`, the hidden-test reports. `bin/scb eval-snapshot` reruns one
  checkpoint's tests in Docker, the way `bin/reeval` calls it; set
  `SCBENCH_PROBLEMS_PATH` to the run's spec (its `problem_catalog.json` names
  it). Rebuilt on 2026-09-22 from the committed snapshots, xjq checkpoint 2
  (v0), datagate checkpoint 4 (v2) and sith checkpoint 5 (v0) gave the same
  outcome for every test and the same counts in `evaluation.json`. The pytest
  output differs only in timings, temporary paths and object addresses, so no
  rebuild is byte for byte. A rerun can differ on rejector, whose mock server
  has a race at checkpoint 2.

Runs made before 2026-09-22 have the OAuth token in `infer.log`, from the
harness's docker exec debug line. `bin/add-run` redacts it, and
`patches/exec-log-masks-secrets.patch` stops newer runs from writing it.
