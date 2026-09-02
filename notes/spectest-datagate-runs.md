# Spectest run ledger (datagate, Opus 5, Claude Code 2.1.251, thinking high)

Every run under `outputs/spectest/`, what changed, and how it ended. Scores are all hidden
tests passed / total at each checkpoint (regressions included), from each checkpoint's
`evaluation.json`. Per-checkpoint tables: `bin/summarize <run_dir>`.

| version | run dir (under outputs/spectest/) | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 42/50, 111/122, 160/174, 211/233, 249/276, 326/353, 377/405 | complete (dev6 sweep); 28 misses, nothing recovered once missed: 8 at ckpt 1 (v3's six plus two whitespace-preservation tests), rowid trio, 3 whitespace tests at ckpt 3, the 8 charset tests at ckpt 4, `force` variants at ckpt 5, mixed-numeric at ckpt 7 |
| v1 | `opus-5_…_spectest/20260831T1136` | first spec-test prompt | 44/50 | ckpt 1 only |
| v2 | `…spectest-v2/20260831T1519` | testing section tweaks | 44/50 | ckpt 1 only; agent pkill self-match |
| v3 | `…spectest-v3/20260831T1647` | | 44/50, 113/122, 165/174, 216/233, 254/276, 331/353, 382/405 | complete (ckpts 2-7 added 2026-09-02 via `bin/scb-extend`); 23 misses: the 6 from ckpt 1 carried all the way, rowid trio, 8 charset tests at ckpt 4, `force` variants at ckpt 5, one mixed-numeric test at ckpt 7 |
| v4 | `…spectest-v4/20260831T2022` | tester as a sub-agent judged on breadth | 50/50, 119/122 | stopped after ckpt 2; **checkpoint dirs 1-2 deleted 2026-09-02** (see below), scores survive in checkpoint_results.jsonl |
| v5 | `…spectest-v5/20260831T2310` | AMBIGUITIES.md procedure | 49/50, 66/122, 170/174, 224/233 | rate-limited after ckpt 4; ckpt 2 was a zero-implementation checkpoint (print-mode killed the bg tester) |
| v6 | `…spectest-v6/20260901T0618` | bg-task ceiling env, "at least one test asserts the chosen reading" | 50/50, 119/122 | killed mid-ckpt 3 to fix the turn-ending rule |
| v7 | `…spectest-v7/20260901T0726` | numbered entries, foreground-wait rule | 49/50, 118/122, 170/174, 224/233, 262/276, 339/353, 391/405 | complete; 14 misses, all five spec sentences |
| v8 disambiguated | `…spectest-v8-disambiguated/20260902T0555` | v8 prompt (tester validates tests only) + `problems/datagate-clarified.patch` | 50/50, 122/122, 174/174, 233/233, 276/276, 353/353, 405/405 | complete; first strict solve |

Only v7 and v8-disambiguated are complete. On hidden tests, v4 through v7 are flat within
the latin-1 noise (ckpt 1: 50, 49, 50, 49 of 50; ckpt 2: 119, cut, 119, 118 of 122), and
every miss is the rowid trio or the latin-1 test. The prompt iterations bought process
reliability and registry quality, not score; the ceiling was the spec. Continuing v4 or
v6 would be comparable (the process bugs decide whether a checkpoint finishes, not what
the agent decides, and a cut checkpoint is visible in the artifacts), but is expected to
reproduce v7's 14 misses at ~$65. If the flat line must be drawn from data, continue v4
only, after adding `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS: "0"` to the run dir's saved
config so the v5 zero-implementation failure cannot recur.

## Did the v8 testing hints help, or was it the zombie fix?

Both, and they are separable in the transcripts. Minutes the tester sub-agent spent
running or polling pytest, and the parent likewise, from `agent/stdout.jsonl`:

| ckpt | v7 tester | v8-d tester | v7 parent | v8-d parent | v7 wall | v8-d wall |
|---|---|---|---|---|---|---|
| 1 | 3.5 | 1.7 | 10.0 | 11.3 | 41 | 36 |
| 2 | 6.3 | 1.1 | 5.0 | 2.6 | 25 | 24 |
| 3 | 13.7 | 1.0 | 10.4 | 4.3 | 55 | 28 |
| 4 | 16.3 | 3.4 | 13.8 | 4.2 | 66 | 39 |
| 5 | | 1.5 | | 3.3 | 66 | 87 (65-min laptop suspend inside) |
| 6 | | 3.4 | | 8.8 | 179 (1 h waiting on a zombie) | 43 |
| 7 | | 2.5 | | 14.9 | 57 | 38 |

The tester line is the prompt: tester test-running time fell four to ten fold at
checkpoints 3 and 4 with nothing else different at that stage. The checkpoint 6 outlier is
the harness: v7's parent waited an hour on `tail --pid` of a zombie pytest, which the
container init fix removes. A clean split would be one run of the v7 prompt on the
disambiguated spec under the patched harness (`spectest-v7-disambiguated`).

## Experiments worth running soon, with what each isolates

Next:
- **The method on a second problem.** The reusable thing is registry → blind judge → patch
  the sentences the model reads one way and the tests the other, not the datagate patch
  itself. xjq is the obvious candidate, as a matched difficulty of "Easy"

Soon:
- **v8-disambiguated, second run.** Run-to-run noise: the latin-1 test has flipped between
  runs before. Needed before leaning on "strict" in public.
- **Stop encouraging libraries** Now that tests are passing, we could do a v9.
  In this version we would remove any special encouragement to use libraries at implementation time.
  Then we could see the impact on the code quality metrics and see if the spec change is worth the tokens.

In a later phase:
- **v7 prompt on the disambiguated spec.** Isolates the v8 prompt's effect on time and cost.
- **Spec lint.** The judge already answers "which sentences does this model read
  differently from its own tester?" for any spec before implementation. Sentences where
  votes split or where the tester's choice is unanimous-but-untested are the lint output.

## Harness patches that exist (all in `patches/`, all applied in the checkout)

stream-parser string message; stop-after-checkpoint; agent death detection + prompt
context variables; resume invalidates infra-failed checkpoints; container init + timeout
kills inside the container. One known bug not yet patched: `retry()` resets the usage
tracker, so a checkpoint that timed out and continued under-reports its cost (v7 ckpt 6
recorded $3 of roughly $15). Candidates for upstream PRs, along with documenting
`SCBENCH_PROBLEMS_PATH` for running against a modified problem copy.

## v4 lost its checkpoints 1 and 2 (2026-09-02 20:56Z)

A `scb run --resume` on the v4 run dir deleted `checkpoint_1` and `checkpoint_2` before
running anything. Cause: the Ctrl-C'd resume on 2026-09-01 05:23 rewrote `run_info.yaml`
with every checkpoint it had not itself run marked `skipped`; the next resume trusts those
states, invalidates the checkpoints, and `rmtree`s their directories. What survives: the
two rows in the run dir's `checkpoint_results.jsonl` (scores, tokens, cost, code metrics),
`result.json`, and the aborted checkpoint 3 workspace (code after checkpoint 2 plus partial
checkpoint 3 work) in `outputs/aborted/spectest-v4-20260831T2022-checkpoint_3`. Agent
transcripts, snapshots, per-test evaluations and diffs for checkpoints 1-2 are gone from
the mount. `bin/scb-extend` now repairs `run_info.yaml` before every resume, and v3's
checkpoint 1 was tarred to `outputs/backups/` before its extension started.
