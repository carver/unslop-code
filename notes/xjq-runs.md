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
