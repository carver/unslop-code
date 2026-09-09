# Spectest run ledger (file_merger, Opus 5, Claude Code 2.1.251, thinking high)

Every file_merger run under `outputs/spectest/`, what changed, and how it ended, in the shape
of `spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; file_merger has four
checkpoints and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`.
The control is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 46/46, 69/86, 87/104, 116/147 | complete (dev6 sweep); 31 misses, 1/4 strict, $26. Quality: erosion 0.684, verbosity 0.196, ast 0.169, cloned 0.025 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T0941` | the 468-word min11 subset (twice strict on datagate v2); first of two | 46/46, 75/86, 93/104, 130/147 | complete 2026-09-07; 17 misses, 11 shared with the control (checkpoint 2: consensus type tie, cross-file type inference, five-file and four-format merges, loose JSONL nulls; checkpoint 4: five nested core cases and the unquoted map-lookup error), six its own (the TSV family: empty fields, gzip, whitespace values, unicode, plus auto_mix_union and consensus_inference); the control's twenty parquet misses all passed. 1/4 strict, $29 (per checkpoint 6, 8, 4, 11), 427 min of wall clock of which 314 was a laptop suspend (about 113 active). 78 registry entries all scored, Risk 0-55 (top: keep-string sort position 55, exit-code taxonomy 55, "majority of files" for consensus 55; TSV literal-tab detection 45). Quality: erosion 0.185, verbosity 0.215, ast 0.096, cloned 0.115 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260908T0504` | same config as the first run | 46/46, 75/86, 93/104, 131/147 | complete 2026-09-08; 16 misses, the first run's set minus one (the partition-by-map-value nested core case passed); 1/4 strict, $28 (per checkpoint 5, 9, 5, 9), 98 min. 64 registry entries all scored, Risk 0-55 (top: authoritative precedence order 55, consensus support and majority 50). Quality: erosion 0.243, verbosity 0.214, ast 0.069, cloned 0.133 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260909T0739` | min12-ABDFJKMN minus F (generator floor), 444 words; first of two | 46/46, 84/86, 102/104, 139/147 | complete 2026-09-09; 8 misses, all shared with the ABDFJKMN runs (cross-file type inference, loose JSONL nulls, the four nested core cases, the partition-by-map-value case, the unquoted map-lookup error); the nine checkpoint-2 misses the ABDFJKMN pair carried, the whole TSV family and the mixed-format merges, passed. 1/4 strict, $23 (per checkpoint 15, 25, 13, 22 min), 75 min. 68 registry entries all scored, Risk 0-45 (bool cell representation 45). Quality: erosion 0.189, verbosity 0.270, ast 0.115, cloned 0.148 |
| min12-ABDJKMN on v1 (halted) | `…min12-ABDJKMN-specv1/20260909T1429` | min12-ABDJKMN on spec v1 under bin/scb-strict; first attempt | 45/46, halted | halted 2026-09-09 after checkpoint 1 by the strict driver: one miss, cross_family_coercion, a checkpoint-1 test every earlier file_merger run passed. A column holding `1` in one file and `true` in another must infer `bool` (the priority list puts `bool` above `int`); this run's registry T3 at Risk 35 chose "`1`/`0` does not make a column `bool`", so the two files conflicted and the column fell to string. A checkpoint-1 coin, not one of v1's four sentences, none of which is in play before checkpoint 2 except the CSV escape rule. Cost $5, 18 min |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 116/147: 31 misses. Twenty are parquet handling from checkpoint 2 on (priority, precision,
    integers, nulls, unicode, the nested-schema cases at checkpoint 4); the rest are the
    mixed-format type-inference cases and the nested core cases it shares with min11.

### min12-ABDJKMN (without F)

  - first run (139): the best file_merger score, eight above the ABDFJKMN pair and 23 above
    the control. Nine checkpoint-2 tests the ABDFJKMN runs missed twice each passed here, the
    TSV family and the mixed-format merges among them; nothing new was lost. One run, so it
    may be a good toss rather than F's absence; the repeat (job 111, paused) decides.

### min11-ABDFJKMN

  - first run (130): fourteen tests better than the control. Parquet is solved outright.
    What remains is two families: the mixed-format inference questions (consensus ties,
    cross-file inference, four- and five-file merges), which the registry scored high (what
    "majority of files support" means, Risk 55), and a TSV family of its own (empty fields,
    gzip, whitespace values, unicode), with literal-tab detection at Risk 45. The nested core
    cases at checkpoint 4 are shared with the control.
  - repeat (131): the first run's misses test for test, minus one nested core case. The
    mixed-format inference and TSV families are stable readings for this prompt, and the
    registry scores the consensus question at 50 both times. Pair: 130 and 131 against the
    control's 116, $29 and $28.

## Spec v1 (2026-09-09)

`notes/file_merger-misses.md` puts the min11-ABDFJKMN repeat's sixteen misses under four
sentences; the user's wording of each is in `specs/file_merger/v1/` (0b22ff3): TSV lines may
end in `\r\n`; "JSONL does not outrank CSV" under the authoritative strategy; backslash-escaped
quotes are accepted in CSV; map keys in field paths are double-quoted. Started 20:55Z at the
user's request, alone with the 21 backfill jobs stashed: min12-ABDJKMN on v1 under
`bin/scb-strict` (job 134), which halts at the first checkpoint that is not strict. The user's
rules: strict all the way, run a second; twice strict, run just-solve on v1.
Halted 21:45Z after checkpoint 1: 45/46, cross_family_coercion (`1` and `true` across two
files must infer `bool`; the run's registry T3 chose the other reading at Risk 35). None of
v1's sentences had been exercised yet; the halt is the strict driver doing its job on a
checkpoint-1 coin. Nothing queued after it; the 21 backfill jobs stay stashed.
Retried 2026-09-09 22:05Z at the user's request with a prompt that writes more tests:
min12-ABDEFJKMN (E back in) on v1 under bin/scb-strict, job 135, alone. The halted run's
registry T3 had quoted both spec lines in play, the priority list and "`bool` includes `1`/`0`
along with standard values", and still chose "a `0`/`1` column stays `int`" on a blast-radius
argument; so the spec was not short of words there and no patch was drafted for it.
