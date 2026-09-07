# Spectest run ledger (xjq, Opus 5, Claude Code 2.1.251, thinking high)

Every xjq run under `outputs/spectest/`, what changed, and how it ended, in the shape of
`spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; xjq has five checkpoints
and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`. The control
is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 23/23, 48/51, 92/96, 117/122, 160/167 | complete (dev6 sweep); 7 misses, 1/5 strict, $6. Quality: erosion 0.366, verbosity 0.253, ast 0.238, cloned 0.000 |
| v11 | `…spectest-v11/20260907T0137` | full v11 (`spectest-v11.jinja`); first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; 7 misses, six shared with the control (the `--text-all` family: joining multiple elements with newlines, deeply nested whitespace, `::text` first-match-only, `first` with `--text-all`, the empty-string JSON element) plus whitespace-only element as empty output; the control's mixed-pipe-path miss passed. 1/5 strict, $73, 137 min. 49 registry entries all scored, Risk 0-45 (top: non-node-set results 45, mixed `::text` comma lists 40, "immediate text content" 40; whitespace-only text results 25). Quality: erosion 0.080, verbosity 0.228, ast 0.050, cloned 0.156 |
| v11, repeat | `…spectest-v11/20260907T0401` | same config as the first run | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; the first run's seven misses, test for test, at every checkpoint; 1/5 strict, $134 (per checkpoint $2, 21, 3, 103, 4), 165 min. 53 registry entries all scored, Risk 0-45 (top: pretty-print 45, whitespace-only text results 45, exported text normalisation 40). Quality: erosion 0.051, verbosity 0.287, ast 0.059, cloned 0.206 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T0654` | the 468-word min11 subset (twice strict on datagate v2); first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; the v11 runs' seven misses, test for test; 1/5 strict, $14 (per checkpoint 2, 3, 2, 3, 3), 69 min; checkpoints 3-5 ran with Monitor disallowed. 51 registry entries all scored, Risk 0-45 (top: non-node XPath results 45, whitespace-only descendant text nodes 45). Quality: erosion 0.050, verbosity 0.355, ast 0.067, cloned 0.283 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 160/167: seven misses, six of them the `--text-all` text-joining family from checkpoint
    2 on, plus the mixed-pipe-path redundant extraction at checkpoint 5.

### v11

  - first run (160): the same total as the control with a different seventh miss: the
    whitespace-only element (expected empty output) instead of the mixed pipe paths. Every
    other miss is the control's. The registry names the family (T5 whitespace-only text
    results at Risk 25, T11 one result per element or per text node at 30) and chose against
    the tests each time. Twelve times the control's cost.
  - repeat (160): the same seven misses at the same checkpoints, so the family is settled
    for v11 on xjq, and the registry again scored it (whitespace-only text results at Risk 45
    this time). $134, twenty-two times the control: checkpoints 2 and 4 carry most of it.

### min11-ABDFJKMN

  - first run (160): the same seven misses as both full-v11 runs and six of the control's,
    at a tenth of v11's price ($14 against $73 and $134). The text-joining family is a
    reading the prompt does not move; the registry names it every time (whitespace-only
    descendant text nodes, Risk 45) and chooses against the tests.

## Why v11's checkpoint 4 cost $103 (2026-09-07 14:30Z)

The repeat's checkpoint 4 (`…spectest-v11/20260907T0401/xjq/checkpoint_4`) ran 80 min and
1,479 assistant turns, 1,372 of them a polling loop. At 12:47Z, tests validated and the
implementation reviewed, the agent launched its full suite as four `nohup` pytest shards
writing to /tmp, armed the Monitor tool on a `pgrep` wait for them, and was told "you will be
notified on each event, keep working, do not poll or sleep". No Monitor event ever reached the
session (zero in the transcript, for either of the two monitors it armed), so with nothing else
to do it ran `true` 1,020 times, each call a full turn over a 130k to 244k context, saying
"Waiting." between them. At 13:21Z it read the shard files itself, fixed one stale test,
re-ran the CSS shard, armed a second monitor and polled again until 13:36Z. The loop is 96%
of the checkpoint's 264M input tokens; every checkpoint outside it in both v11 xjq runs, and
every min11 datagate checkpoint, has zero `true` calls. The first run's $39 checkpoint 4 was
plain length (569 turns), not a loop. Background Bash completions do get delivered in the
harness's print-mode session (the "Validate property tests" task notified), Monitor events do
not; the agent config's `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` (set so background
sub-agents survive the parent's turn ending) is the likely reason and is unverified. The
per-checkpoint `cost_limit: 20` is documented as not enforced for the claude_code agent, and
`net_cost_limit: 100` is checked only between checkpoints, so nothing capped it. Fix on the
table: `disallowed_tools: [Monitor]` in `configs/agents/claude_code-2.1.251.yaml` (the
harness passes it as `--disallowedTools`), so the agent waits with a blocking command
instead.
Applied 2026-09-07 14:15Z at the user's request: `disallowed_tools: [Monitor]` in
`configs/agents/claude_code-2.1.251.yaml`, and the same line added by hand to job 84's saved
`config.yaml` (`…min11-ABDFJKMN/20260907T0654`, the min11 xjq run then on checkpoint 2), since a
resume reads the agent block embedded in the run config rather than the agents file. Job 85 and
everything after start fresh and pick it up from the file.
