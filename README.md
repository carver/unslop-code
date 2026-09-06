# unslop-code-bench

Working towards solving the excellent SlopCodeBench.

Making a lot of progress (in Opus 5) with general prompt improvements.
Also finding some specs in the benchmark that are legitimately ambiguous.

Start here:

- `baseline-report.md` — the Sonnet 4.6 reproduction vs the leaderboard, with manifest.
  Published page: https://claude.ai/code/artifact/d4db605f-59b1-4a23-aa50-6ae72dc36dc1
  (regenerate with `python3 report/build.py`, then republish).
- `notes/` — credential plumbing and incident log (`credential-setup.md`), control
  isolation audit, spec-delivery mechanism, per-run comparisons
  (`dev6-opus5.md`, `dev6-fable5.md`), leaderboard/paper reference, compiled results.
- `split.json` / `problems.csv` — dev/holdout split (seed 20260829). Never read holdout
  specs or re-run file_backup outside the holdout eval.

Running things (always through the wrapper; it enforces subscription-only auth
and the sandbox-local venv):

    bin/scb run --config configs/runs/<name>.yaml --no-live-progress
    bin/scb run --resume <run_dir>           # after any interruption
    bin/usage                                # 5h/7d rate-limit windows
    bin/scb-extend <run_dir> <problem> <n>    # resume a stopped run one checkpoint at a time, waiting out the 5h window
    bin/summarize <run_dir> [--md]           # per-checkpoint table; runs scb-check on snapshots as needed
    bin/failures [run_a [run_b]] [problem]   # failing tests, one run or side by side
    bin/askrun <checkpoint_dir> [question]   # resume that checkpoint's Claude session
                                             # for post-run Q&A (no args = interactive)
    bin/miss-report <run_dir>                # failing hidden tests with assertions, spec lines,
                                             # candidate AMBIGUITIES entries
    bin/judge-ambiguities run|summarize ...  # blind judges over a registry, optionally against
                                             # a spec patch
    bin/spec-patch <problem> <vN>            # build spec version vN (specs/vN/*.patch over the
                                             # cache) into specs/vN/problems/, see specs/README.md
    bin/scb-strict <config> <problem> <n>    # one checkpoint per invocation, halt on any miss
    bin/run-config --prompt P --problem X    # write a run config for one prompt on one problem
                                             # (--spec vN reads specs/vN/problems; default v0)
    bin/compare-runs <run_dir>...            # runs side by side: scores, cost, quality, miss matrix
    bin/registry-scores <run_dir> [--grep X] # a run's AMBIGUITIES.md Differs scores: spread, top entries,
                                             # the Choice and Differs text of matching entries
    bin/queue-watch                          # event stream for a Monitor: checkpoint results, halts, DONE
                                             # lines and job status changes across the whole queue
    bin/ledger-row <run_dir>                 # after every run: the ledger row and failure summary to fill in
    bin/results [--write]                    # every complete run, one row per problem/prompt/spec -> notes/results.md
    bin/queue add configs/runs/<name>.yaml   # enqueue a run (one at a time); bin/queue = status
    bin/build-prompt BEG                     # configs/prompts/min4-BEG.jinja from the chunks in
                                             # configs/prompts/min4-chunks/ (--list for the index)

Queueing runs: one at a time, never in parallel (the 5h window and per-checkpoint window
accounting both break). `bin/queue add configs/runs/<name>.yaml` enqueues a run behind
whatever is queued; `bin/queue` shows status, `bin/queue log <id>` a job's output,
`bin/queue kill <id>` stops one and cleans up after it: a queued job is removed; a running
one is killed along with the slop-code worker that outlives it and the agent container it
leaves behind, with the queue paused meanwhile and resumed after. `bin/queue add --next <config>`
puts a job ahead of everything queued, `bin/queue move <id> before <id>` reorders queued jobs (pueue
renumbers the two it swaps, so read the printed order rather than remembering ids), and
`bin/queue resume <run_dir>` continues a run stopped between checkpoints. The
queue is pueue, installed by `install.py`, one task at a time, persistent across shells and
sessions. The driver underneath (`bin/scb-extend`) waits out the 5h window and API
overloads, dry-runs every resume, and tars finished checkpoints to `outputs/backups/`.

Project skills (`.claude/skills/`, all user-invoked) tie those together:

    /solve-one-problem       one dev problem, start to finish: baseline pair, spec patch,
                             prompt ladder, report; stops before the next problem
    /spec-ambiguity-review   a run's hidden-test misses -> a minimal spec patch, verified
                             by blind judges, then a strict rerun
    /prompt-ladder           smallest prompt that strict-solves a patched spec, and where
                             code quality drops off

The benchmark clone in `slop-code-bench/` carries six source patches; after
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
- `patches/resume-invalidate-infra-failed-checkpoints.patch` — `--resume`
  re-runs a checkpoint whose evaluation recorded `infrastructure_failure`
  (an offline pypi fetch scored a checkpoint 0 while marking it ran).
- `patches/container-init-and-timeout-kill.patch` — the agent container runs
  with an init process so finished orphans are reaped (with `sleep infinity`
  as PID 1 they stayed zombies, and an agent waiting on one with `tail --pid`
  waited for an hour), and a checkpoint timeout now kills the command inside
  the container the moment it fires. Before, the harness only killed its
  `docker exec` client, which does not propagate, and then waited for the
  command to end on its own: a silent command was never stopped, and a
  claude process outlived its timeout and raced its own `--continue` retry
  for the workspace (v7 datagate ckpt6, 2026-09-02).
- `patches/retry-keeps-every-attempt-transcript.patch` — when a claude process
  dies mid-checkpoint and the harness retries it with `--continue`, the
  checkpoint's `stdout.jsonl` and `stderr.log` now hold every attempt in order.
  Before, the retry's output replaced the first attempt's, so the transcript
  of the work before the crash survived only in the copied Claude session
  file under `agent/workspace/projects/` (min4-ABCHJK datagate ckpt1,
  2026-09-04).

`outputs/` holds the three dev6 baseline runs. The setup-token lives at
`~/.config/scbench/claude-oauth-token` (mint a new one with `bin/setup-token-wizard`).
