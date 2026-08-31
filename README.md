# unslop-code-bench

Testing whether skills injected into a Claude Code agent's workspace improve
SlopCodeBench results. Phase 0 (baselines) is done; no skills exist yet.

Start here:

- `baseline-report.md` — the Sonnet 4.6 reproduction vs the leaderboard, with manifest.
  Published page: https://claude.ai/code/artifact/d4db605f-59b1-4a23-aa50-6ae72dc36dc1
  (regenerate with `python3 report/build.py`, then republish).
- `notes/` — credential plumbing and incident log (`credential-setup.md`), control
  isolation audit, spec-delivery mechanism, per-run comparisons
  (`dev6-opus5.md`, `dev6-fable5.md`), leaderboard/paper reference.
- `split.json` / `problems.csv` — dev/holdout split (seed 20260829). Never read holdout
  specs or re-run file_backup outside the holdout eval.

Running things (always through the wrapper; it enforces subscription-only auth
and the sandbox-local venv):

    bin/scb run --config configs/runs/<name>.yaml --no-live-progress
    bin/scb run --resume <run_dir>           # after any interruption
    bin/usage                                # 5h/7d rate-limit windows
    bin/summarize <run_dir> [--md]           # per-checkpoint table (needs bin/scbcheck first)
    bin/scbcheck <run_dir>                   # per-checkpoint scb-check quality reports
    bin/failures [run_a [run_b]] [problem]   # failing tests, one run or side by side
    bin/askrun <checkpoint_dir> [question]   # resume that checkpoint's Claude session
                                             # for post-run Q&A (no args = interactive)

The benchmark clone in `slop-code-bench/` carries three source patches; after
any pull, re-apply them in this order:

- `patches/claude-code-stream-parser-string-message.patch`
- `patches/stop-after-checkpoint.patch` — adds `--stop-after-checkpoint N` to
  `scb run` (works with `--resume`), for advancing a run one checkpoint at a time
  in the same run dir.
- `patches/agent-death-detection-and-prompt-context.patch` — a claude process
  that ends without a result payload (killed mid-checkpoint) now fails the
  checkpoint loudly instead of being scored as a completion, and `--resume`
  re-runs it. Also gives prompt templates `checkpoint_name`,
  `checkpoint_number`, `agent_type`, `agent_version`, and `model_name`, rendered
  identically at run and resume-validation time.

`outputs/` holds the three dev6 baseline runs. The setup-token lives at
`~/.config/scbench/claude-oauth-token` (mint a new one with `bin/setup-token-wizard`).
