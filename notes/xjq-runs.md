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
