# unslop-code-bench

Improving Code Quality against the excellent SlopCodeBench.

Using Opus 5 and a custom prompt, it's tempting to say that I have solved the quality issues.
I only had the credits to run against 6 of the problems so far, but will keep expanding whenever I have spare credits at the end of the week.

Interestingly, the correctness scores (Core, Isolated, Strict) didn't improve much at all.

I separately analyzed the specs of three problems, and came to the conclusion that the specs are legitimately ambiguous.
The prompts now how help identify these ambiguities, and I have applied minimal patches to get (almost) perfect strict solves.
Occasionally, Opus makes what I think is just a wrong call (actually only once so far).

## Findings so far (2026-09-15)

Two levers, measured in both orders on the six dev problems with Opus 5, two runs per cell
(`notes/uplift-grid.md`, `bin/grid` for the table, the published grid linked there):

- **Correctness comes from the spec.** Rewriting the ambiguous sentences (datagate v2, xjq v3,
  file_merger v6) takes hidden-test failures from 8% to under 2% for either prompt. The prompt
  alone barely moves them at v0: 8.3% to 5.5% over six problems, most of that on sith.
- **Code quality comes from the prompt.** The 444-word min12 prompt cuts the harness's erosion
  score from 0.58 to 0.15 averaged over six problems, and ast-grep smells from 0.25 to 0.09;
  the spec patch leaves both where they were.
- **Order does not matter.** Prompt-then-spec and spec-then-prompt land on the same score; the
  quality gap is the prompt's either way.
- **The price is time more than money.** Averaged over six problems at v0, min12 costs $24 a
  run to just-solve's $23 and takes 87 minutes to its 80; on the patched specs 62 minutes to
  47. Small problems pay 1.5x to 2x in both; the large ones pay less, where the bare prompt's
  long runs are the expense. The page: `report/uplift-grid.html` (`python3 report/uplift_grid.py`).
- **Erosion does not climb under min12.** The paper's Figure 5 has every prompt on every GPT
  model eroding further from the first checkpoint to the last, and says quality prompts do
  not slow that. On the same five phases Opus 5 just-solve goes 0.56 to 0.61 and min12 0.14 to
  0.16, flat within noise; the page draws both over the paper's lines (`notes/uplift-grid.md`).
- **One miss is Claude's, not the spec's.** datagate's remaining failures are five tests that
  expect header and cell whitespace kept verbatim. The spec never mentions whitespace; the
  agent trims it anyway, and when asked afterwards concedes the spec gives no licence. Left
  in as a benchmark failure (datagate diary, 2026-09-14).

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

    bin/scb sync v1.0                        # install the problem catalog (scb-problems release v1.0, commit
                                             # 4d38d30) into ~/.cache/scbench/problems; a bare `run` fetches
                                             # the latest release instead, which may not be v1.0. Then
                                             # `python3 install.py` for pueue and the patches
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
    bin/spec-patch <problem> <vN>            # build the problem's spec version vN (specs/<problem>/vN/*.patch
                                             # over the cache) into specs/<problem>/vN/problems/, see specs/README.md
    bin/scb-strict <config> <problem> <n>    # one checkpoint per invocation, halt on any miss
    bin/run-config --prompt P --problem X    # write a run config for one prompt on one problem
                                             # (--spec vN reads specs/<problem>/vN/problems; default v0)
    bin/compare-runs <run_dir>...            # runs side by side: scores, cost, quality, miss matrix
    bin/registry-scores <run_dir> [--grep X] # a run's AMBIGUITIES.md Differs scores: spread, top entries,
                                             # the Choice and Differs text of matching entries
    python3 -m pytest                        # the bin tools' tests; GitHub Actions runs them on every PR
    bin/fork-run <run_dir> --spec vN --keep k  # copy a run keeping checkpoints 1..k, pointed at spec vN;
                                             # --queue continues it with bin/queue resume-strict <copy>
    bin/queue resume-strict <run_dir>        # continue a run under bin/scb-strict: halt at the first non-strict checkpoint
    bin/test-history <problem> <test>        # pass, fail or not reached, in every run of the problem, oldest first
    bin/queue-watch                          # event stream for a Monitor: checkpoint results, halts, DONE
                                             # lines and job status changes across the whole queue
    bin/ledger-row <run_dir>                 # after every run: the ledger row and failure summary to fill in
    bin/reeval <run_dir> <problem> <ckpt> --tag T  # re-score one checkpoint under the current problem config; keeps the old evaluation as before-T
    bin/results [--write]                    # every complete run, one row per problem/prompt/spec -> notes/results.md
    bin/grid [--json]                        # the 2x2 uplift grid (just-solve vs min12, v0 vs patched), per problem
                                             # and averaged; fail%, quality, cost, all lower-is-better
    bin/queue wait <id>                      # block until a job ends, print its STRICT-RUN/EXTEND lines and run_dir;
                                             # run it in the background so the wake-up names the run directory
    bin/queue add configs/runs/<name>.yaml   # enqueue a run (one at a time); bin/queue = status
    bin/queue add-strict configs/runs/<name>.yaml  # enqueue it under bin/scb-strict: halts at the first non-strict checkpoint
    bin/queue solo <id>                      # run one queued job while the rest wait (stash, start, pause --wait, re-queue)
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

Runs use the harness checkout at `harness/`: a clone of slop-code-bench pinned to
`06b5c06` with six source patches applied, built with its venv by `python3 install.py`
(idempotent; re-run it after a sandbox recreate). `slop-code-bench/` is the development
clone for upstream work and carries no obligations; on 2026-09-11 a branch switch there
dropped the patches under a running queue, which is why runs read a checkout of their own.
The patches, in the order install.py applies them:

- `patches/claude-code-stream-parser-string-message.patch` — Claude Code 2.1.251
  streams a `permission_denied` event whose `message` is a string when its
  safety check blocks a Bash command; unpatched `_run()` crashes on it and fails
  the checkpoint. Upstream candidate on branch `claude-2.1.2xx-compatibility`.
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
- `patches/resume-only-problem.patch` — `scb run --resume` honours
  `SCB_RESUME_ONLY_PROBLEM=<problem>` and resumes that problem alone. Upstream's
  `--problem` merges into the run's saved list on resume, so a queue job for one
  problem of a multi-problem run would otherwise resume every problem.
  `bin/scb-extend` sets the variable for its child.

`patches/scb-problems/` holds patches for the upstream problem set
(gabeorlanski/scb-problems), not applied to the cache, each with its evidence as a
preamble: `mvvault-checkpoint-6-prior-tests.patch` turns the earlier checkpoints' tests
back on for mvvault's last checkpoint, which the reference solution passes 185/185.
Every upstream PR idea, with evidence and blockers, is in `notes/upstream-prs.md`.

`outputs/` holds the three dev6 baseline runs. The setup-token lives at
`~/.config/scbench/claude-oauth-token` (mint a new one with `bin/setup-token-wizard`).
