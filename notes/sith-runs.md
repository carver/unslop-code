# Spectest run ledger (sith, Opus 5, Claude Code 2.1.251, thinking high)

Every sith run under `outputs/spectest/`, what changed, and how it ended, in the shape of
`spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; sith has six checkpoints
and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`. The
control is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 39/39, 74/75, 103/108, 126/146, 159/186, 191/228 | complete (dev6 sweep); 37 misses, 1/6 strict, $52. Quality: erosion 0.673, verbosity 0.399, ast 0.366, cloned 0.045 |
| just-solve on v0, repeat | `…just-solve/20260915T1324` | benchmark's own prompt on the unpatched spec, a per-problem run; the second just-solve v0 replicate (the first is the dev6 control) | 38/39, 73/75, 105/108, 130/146, 162/186, 194/228 | complete 2026-09-15; 34 misses, 31 the control's (the names and search families at checkpoint 4, the extract family at 5, the env block at 6) and three its own (parameter metadata completion at 1, extract param order at 5, interpreter goto first-namespace at 6); six of the control's 37 passed. Three above the control. 0/6 strict, $49 (per checkpoint 8, 10, 9, 8, 7, 7), 164 min, the most expensive run of the grid. Quality: erosion 0.579, verbosity 0.240, ast 0.181, cloned 0.057 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260908T0219` | the 468-word min11 subset (twice strict on datagate v2); first of two | 39/39, 74/75, 106/108, 135/146, 172/186, 202/228 | complete 2026-09-08; 26 misses, 23 shared with the control (the checkpoint-2 is-not-none narrowing, one checkpoint-3 case, nine from checkpoint 4, two from 5, ten of checkpoint 6's own core and functionality tests) and three its own (env-info default executable including sys.path, attribute completion preferring the static receiver, rename of alias-backed references); fourteen of the control's misses passed (three from checkpoint 3, six from 4, five from 5). 1/6 strict, $47 (per checkpoint 5, 8, 6, 10, 10, 7), 158 min. 123 registry entries all scored, Risk 0-60 (top: parameter `description` 60, how `--diff` shows a rename 55). Quality: erosion 0.304, verbosity 0.256, ast 0.111, cloned 0.134 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260908T0846` | same config as the first run | 38/39, 72/75, 104/108, 138/146, 169/186, 204/228 | complete 2026-09-08; 24 misses, 16 shared with the first run (one each from checkpoints 2 and 3, four from 4, three from 5, seven of checkpoint 6's own), eight its own (a parameter-metadata completion from checkpoint 1, one from 2, six from 5), while ten of the first run's passed (five checkpoint-4 regressions, five checkpoint-6 core cases). 0/6 strict, $49 (per checkpoint 6, 11, 8, 8, 8, 7), 209 min (checkpoint 5 alone 66). 115 registry entries all scored, Risk 10-55 (top: parameter description 55, namespace attributes type 55). Quality: erosion 0.401, verbosity 0.360, ast 0.082, cloned 0.275 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260915T0053` | the 444-word no-F prompt on v0, for the six-problem quality-uplift comparison; first of two | 37/39, 72/75, 104/108, 137/146, 171/186, 205/228 | complete 2026-09-15; 23 misses, 19 shared with the control (checkpoint 4's stub/goto, unresolved references, dataclass signatures; checkpoint 5's extract-function and extract-variable family; checkpoint 6's env find/list/info block) and four its own (the two checkpoint-1 completion-scope cases, partial-statement extract exit code, alias-backed rename); eighteen of the control's 37 passed, the names and search families at checkpoint 4 among them. Fourteen above the control, one above min11's best. 0/6 strict, $40 (per checkpoint 5, 8, 7, 7, 7, 7), 139 min. 130 entries all scored, Risk 0-55 (parameter description, runtime attribute completion types, interpreter-mode signatures 55). Quality: erosion 0.388, verbosity 0.308, ast 0.120, cloned 0.181 |
| min12-ABDJKMN, repeat | `…min12-ABDJKMN/20260915T0719` | same config as the first run | 39/39, 74/75, 106/108, 139/146, 170/186, 204/228 | complete 2026-09-15; 24 misses, 18 shared with the first run (checkpoint 4's stub/goto, unresolved references, dataclass signatures; the extract family and alias rename at 5; the env list/info block at 6). Its own six: four more extract-function cases at checkpoint 5 (module level, multiple returns x2, param order), project-init merge and smart-sys-path at 6; it held the first run's checkpoint-1 completion pair, the env find pair and the partial-statement exit code. Checkpoint 1 strict, the first sith run to be. Thirteen above the control. 1/6 strict, $37 (per checkpoint 5, 6, 5, 7, 7, 8), 133 min. 118 entries all scored, Risk 10-55 (namespace attribute completion, parameter description 55; extract-function layout 50). Quality: erosion 0.361, verbosity 0.363, ast 0.152, cloned 0.196 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260919T0435` | min12 plus chunk T, the upstream anti-slop rule list (d902f32), on v0; first of two | 39/39, 74/75, 106/108, 129/146, 161/186, 195/228 | complete 2026-09-19; 33 misses: the 14 every v0 run shares (checkpoint 5's extract family, env find and list at 6, dataclass signatures), the checkpoint-4 names and search family of ten that both min12 runs passed and both just-solve runs lost, seven more shared with one or two of the other runs, and one of its own. Checkpoint 1 strict, the first strict sith checkpoint for a spectest prompt since min11. 1/6 strict, $49, 154 min. Quality: erosion 0.002, verbosity 0.253, ast 0.044, cloned 0.152; implementation only erosion 0.000, ast 0.078, cloned 0.008 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 191/228: 37 misses. One from checkpoint 2, four from 3, fifteen from 4, seven from 5,
    ten of checkpoint 6's own; the widest gap of the six dev6 problems.

### just-solve on v0, repeat (2026-09-15)

  - 194/228, three above the control on the same shape: the checkpoint-4 names and search
    families and the checkpoint-5 extract family again. Cell: 191 and 194 against min12's 205
    and 204; the sith gap is the one that survives both replicates by a wide margin.
    Erosion 0.673 and 0.579 against 0.388 and 0.361.

### min12-ABDJKMN (without F)

  - first run (205): fourteen above the control and one above min11's pair, cheapest of the
    three prompts ($40). Checkpoint 4 is where it wins: the names and search families the
    control lost all passed. Four misses of its own, two of them checkpoint-1 completion scope
    (comprehension variable leaking, parameter metadata). Erosion 0.388 against the control's
    0.673. First of two.
  - repeat (204): one below the first run, the same shape as min11's pair: 18 shared misses,
    six moving (extract-function cases lost, completion scope and env find held). Pair: 205
    and 204 against the control's 191; erosion 0.388 and 0.361 against 0.673. Checkpoint 5's
    extract family is the sith miss class no v0 prompt clears.

### min13-ABDJKMNT (min12 plus the anti-slop list)

  - 195/228, between the min12 pair (205, 204) and the just-solve pair (191, 194). It kept
    min12's misses and re-lost the checkpoint-4 names and search family of ten that min12
    had won back from just-solve, so on sith the chunk T run scores like the bare prompt with
    min12's quality and better. Implementation only: erosion 0.000 against min12's 0.580, ast
    0.078 against 0.251, cloned 0.008 against 0.031, on 3295 implementation lines against
    min12's 4320 per run. $49 and 154 min against min12's $39 and 136, the most expensive
    min13 run so far. First of two.

### min11-ABDFJKMN

  - first run (202): eleven better than the control, and cheaper ($47 against $52). Every
    checkpoint from 3 on beat the control's, by three, nine, thirteen and eleven. The
    checkpoint-6 core and functionality misses are the control's ten; the three new ones are
    small (sys.path in env info, static receiver for attribute completion, alias-backed
    rename). Erosion 0.304 against 0.673.
  - repeat (204): two better than the first run and thirteen better than the control, by a
    different route: it lost one at checkpoint 1 and six at checkpoint 5 that the first run
    held, and passed ten the first run missed at checkpoints 4 and 6. Pair: 202 and 204
    against 191, $47 and $49; sith's misses move between runs of this prompt like rejector's.
