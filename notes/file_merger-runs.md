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
| min12-ABDEFJKMN on v1 (halted) | `…min12-ABDEFJKMN-specv1/20260909T1515` | min12-ABDEFJKMN (with E) on spec v1 under bin/scb-strict | 46/46, 84/86, halted | halted 2026-09-09 after checkpoint 2: two misses, authoritative_strategy and authoritative_interleaved, tests every earlier run passed. Both merge a CSV of ints with a JSONL of floats under the default strategy and expect `float`; this run's registry T26 (Risk 55) read v1's "JSONL does not outrank CSV" as CSV outranking JSONL (ranks parquet 3, csv 2, jsonl 1, the highest rank with an opinion wins), so CSV's `100` fixed `int` and the JSONL floats were nulled. The TSV, escape and map-key sentences were not reached by a failing test; the nine CRLF cases all passed |
| min12-ABDJKMN on v2 (halted) | `…min12-ABDJKMN-specv2/20260909T1609` | min12-ABDJKMN on spec v2 under bin/scb-strict | 46/46, 84/86, halted | halted 2026-09-09 after checkpoint 2 on the same two authoritative tests as the v1 run before it: "JSONL does not outrank CSV" read as CSV outranking JSONL, two of two. Checkpoint 1 clean, so v2's inference sentence held its first toss; the nine TSV cases passed again |
| min12-ABDJKMN on v3 (halted) | `…min12-ABDJKMN-specv3/20260910T0934` | min12-ABDJKMN on spec v3 under bin/scb-strict | 46/46, 86/86, 104/104, 146/147 | halted 2026-09-10 after checkpoint 4 on test_error_cases[errors/alias_cycle]: the alias file `{"a": "b", "b": "a"}` with a schema that uses only `int` must exit 2 at load; the snapshot detects a cycle only while resolving a type that uses it, so an unused cycle passes and it exits 0. First run through checkpoints 1-3 strict: v3's "JSONL ranks equal to CSV" held both authoritative tests, the CRLF and inference sentences held again. Not in the registry (T52 covers alias order, Risk 20); the v0 run passed it. $23, 77 min |
| min12-ABDJKMN on v4 (halted) | `…min12-ABDJKMN-specv4/20260910T1126` | min12-ABDJKMN on spec v4 under bin/scb-strict | 46/46, 86/86, 104/104, 146/147 | halted 2026-09-10 after checkpoint 4 on test_core_cases[correct_partition_nested/partition_by_map_value]: `--partition-by 'attrs["region"]'` must write `out/attrs["region"]=east/`; the snapshot percent-encodes the column name too, `out/attrs%5B%22region%22%5D=east/`, so the expected files are missing. alias_cycle passed: v4's sentence held one for one. A 2-of-4 coin before v4; three runs registered the question (v0 min12 T44 Risk 15, min11-first T47, this run T46 Risk 10) and every one that chose "both halves" failed; min11-repeat and v3 encoded the value only and passed. Checkpoint 3's "Apply percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`" sits under the `<col>=<val>` segment and does not say value only. $21, 73 min |
| min12-ABDJKMN on v5 (clone, halted) | `…min12-ABDJKMN-specv5/20260910T1126` | the v4 run forked after checkpoint 2 (bin/fork-run), checkpoints 3 and 4 re-run on spec v5 | 46/46, 86/86, 104/104, 146/147 | checkpoints 1-2 are the v4 run's; 3 strict on v5 (partition sentence exercised at 4: partition_by_map_value passed, one for one); halted after 4 on test_error_cases[errors/map_lookup_no_quotes]: `--key attrs[country]` (no quotes) must fail; the snapshot accepts an unquoted bracket key as a map lookup (registry T58 "uniform steps", Risk 25) and exits 0. v3 and v4 rejected it (exit 2 and 3; the harness checks only non-zero). $20 for the two checkpoints, 39 min |
| min12-ABDJKMN on v6 (fork, strict) | `…min12-ABDJKMN-specv6/20260910T1126` | the v5 clone forked after checkpoint 3 (bin/fork-run), checkpoint 4 re-run on spec v6 | 46/46, 86/86, 104/104, 147/147 | checkpoints 1-2 are the v4 run's, 3 the v5 clone's, 4 on v6: map_lookup_no_quotes passed ("quotes are required" one for one) and nothing regressed. First 147/147 on file_merger, assembled from three spec versions; not yet one fresh run. $21 ladder total, 27 min for checkpoint 4 |
| min12-ABDJKMN on v6, fresh (strict) | `…min12-ABDJKMN-specv6/20260910T1510` | min12-ABDJKMN on spec v6 under bin/scb-strict, a fresh run from checkpoint 1; first of two | 46/46, 86/86, 104/104, 147/147 | complete 2026-09-10, 0 misses: the first fresh full strict run on file_merger, on the eight-patch v6 spec. Every sentence of v1-v6 held in one run. $22, 73 min |
| just-solve on v6 | `…just-solve-specv6/20260910T1709` | the bare benchmark prompt on the eight-patch spec v6; first of two (checkpoints 1-3 before the harness outage, 4 after it, on the harness checkout) | 45/46, 84/86, 102/104, 142/147 | complete 2026-09-11; 5 misses against the v0 control's 31: bool_nonstandard_strict (ckpt 1, `1`/`true` mixed column), tsv_whitespace_values (ckpt 2), and at checkpoint 4 correct_aliases case1 and case2 plus nested_type_alias_with_parquet. The control's 17 checkpoint-2 misses (parquet, TSV, mixed inference) are gone; only two checkpoint-4 misses are shared with it. $18, 73 min |

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
Changed 2026-09-09 22:20Z at the user's request: every pending job removed (the 21 stashed
backfill runs of ABDJKMN and ABDEFJKMN across dev6); job 135 runs on. The user found T3's
argument compelling and asked for a draft that ties inference to the casting rules rather than
restating the bool case: `specs/drafts/file_merger-05-infer-by-cast-rules.patch`, their call.

## Spec v2 (2026-09-09)

v1 plus `05-infer-by-cast-rules.patch`, the user's "Inference recognises values by the casting
rules below" under the checkpoint-1 inference bullets, answering registry T3's reading that the
`1`/`0` rule governs casting only. Queued 22:35Z at the user's request behind job 135:
min12-ABDJKMN on v2 under bin/scb-strict (job 136), the same plan: halt at the first non-strict
checkpoint; strict through all four, run a second; twice strict, run just-solve on v2.
Halted 23:09Z after checkpoint 2: 84/86, the two authoritative-strategy tests. v1's second
sentence over-corrected: "JSONL does not outrank CSV" was read as CSV outranking JSONL, and
the reference's reading (Parquet alone is typed; JSONL and CSV/TSV are inferred peers whose
`int` and `float` join to `float`) is the one both tests and cross_file_type_inference want.
The nine TSV cases passed at checkpoint 2, so the CRLF sentence did its work. Job 136
(ABDJKMN on v2, which carries the same sentence) is on checkpoint 1.
Halted 23:45Z after checkpoint 2: 84/86, the same two authoritative tests, two of two runs on
that sentence. The queue is empty; the authoritative wording waits on the user.

## Spec v3 (2026-09-10)

v2 with patch 02 reworded to the user's draft, "JSONL ranks equal to CSV" (8aba62e).
Queued 16:34Z: min12-ABDJKMN on v3 under bin/scb-strict (job 137), alone, the queue
otherwise empty; the same plan, halt at the first non-strict checkpoint.
Halted 17:56Z after checkpoint 4: 46/46, 86/86, 104/104, 146/147. Checkpoints 1 to 3 strict
for the first time on this problem: both authoritative tests passed, so the reworded sentence
is one for one, and the CRLF, backslash-quote and casting-rule sentences held again. The one
miss is errors/alias_cycle at checkpoint 4: the alias file is `{"a": "b", "b": "a"}` and the
schema declares `id` as `int`, so no type ever names either alias; the test wants exit 2 at
load, the snapshot resolves aliases lazily and exits 0. The spec's words: "May refer to
built-ins or other aliases (resolve transitively; detect cycles → error 2)". The registry's
T52 (Risk 20) is about resolution order, not when the cycle check runs; the run's own tests
cover the cycle only through a schema that uses it. The v0 run of this prompt passed the case.
The queue is empty; a second v3 run and the just-solve on v3 wait on the user.

## Spec v4 (2026-09-10)

v3 plus `06-alias-cycle-at-load.patch`: the user's "detect cycles proactively → error 2" in place
of "detect cycles → error 2". Judged with the v0 min12-ABDJKMN run's T55 ("eagerly or only when
used") against the v4 build, ten samples each of choose and rule: 20 of 20 for the eager reading,
every rule line saying a cycle errors even if no schema column references it ($1.31,
`outputs/judge/file_merger-v4`). Queued: min12-ABDJKMN on v4 under bin/scb-strict, the same plan.
Halted 19:44Z after checkpoint 4: 46/46, 86/86, 104/104, 146/147. alias_cycle passed, so the v4
sentence is one for one and checkpoints 1 to 3 are strict a second time. The miss is
correct_partition_nested/partition_by_map_value: `--partition-by 'attrs["region"]'` must write
`out/attrs["region"]=east/part-00000.csv`; the snapshot percent-encodes the column name along with
the value (`out/attrs%5B%22region%22%5D=east/`), so the harness reads the expected files as empty.
The rule is checkpoint 3's "Apply percent-encoding of UTF-8 bytes for characters outside
`[A-Za-z0-9._-]`", a sub-bullet of the `<col1>=<val1>/...` segment line, silent on whether the
column name is encoded; the reference's encode_partition_value encodes the value only, and the
name only differs at checkpoint 4, where a field path carries brackets and quotes. History: the v0
min12-ABDJKMN run registered the question (T44 "Is the partition column name percent-encoded, or
only the value?", Risk 15, chose the name too) and failed; min11-ABDFJKMN's first run failed the
same way (T47, "applied to the column-name half of the segment as well"); this run's T46 (Risk 10)
chose both halves too, noting "encoding of the name half is untested in all likelihood". The
min11 repeat and the v3 run encoded the value only and passed. Three registered, three failed;
two silent, two passed. The queue is empty; the sentence waits on the user.

## Spec v5 (2026-09-10)

v4 plus `07-partition-encode-value-only.patch`: checkpoint 3's percent-encoding bullet now opens
"Values use percent-encoding" instead of "Apply percent-encoding", the user's one-word edit of
the draft. No judge run, the user's call: the evidence was three registered readings that all
went the wrong way. Queued: min12-ABDJKMN on v5 under bin/scb-strict (job 139, 20:45Z); killed two minutes in at the
user's request and its run directory deleted, nothing scored.
Continuation 20:49Z at the user's request, the xjq v3 trick: the v4 run
(`…min12-ABDJKMN-specv4/20260910T1126`) cloned to `…min12-ABDJKMN-specv5/20260910T1126` with
checkpoints 3 and 4 removed, config and catalog record pointed at v5, the two rows dropped from
checkpoint_results.jsonl and from run_info.yaml's summary; the resume preview kept checkpoints 1
and 2 and deleted nothing. Checkpoint 3 is v5's changed spec, so the clone stops there
(`bin/queue resume <dir> 3`, job 140); checkpoint 4 is queued only if 3 is strict. Checkpoints 1
and 2 of this run are the v4 run's, spec-identical under v5.
Checkpoint 3 on v5, 21:04Z: 104/104, strict (job 140, 15 min). Checkpoint 4 queued on the same
clone (job 141). `bin/fork-run` (a5f6c8b) now does the clone.
Checkpoint 4 on v5, 21:28Z: 146/147. partition_by_map_value passed, so the value-only sentence is
one for one; alias_cycle and the authoritative tests held. The miss is errors/map_lookup_no_quotes:
`--key attrs[country]`, a bracket key without double quotes, must fail (the fixture says exit 2,
"ERR 2 invalid key path syntax", but the harness's error cases assert only a non-zero exit). The
snapshot's tokenizer takes any bracket content as a key, its registry T58 choosing "uniform steps"
over a "strict grammar" at Risk 25 and naming the unquoted spelling as the likely divergence.
The spec's words are v1's own patch 04, "map lookups with bracketed, double-quoted string keys",
and "Map lookups with `["key"]` read value by exact key": the canonical spelling, never that
other spellings are errors. History: min11 both runs and v0 min12 failed the case (before patch
04); v3 (exit 2) and v4 (exit 3) rejected it. Not a full strict run, so no repeat queued; the
sentence waits on the user.

## Spec v6 (2026-09-10)

v5 plus `08-map-key-unquoted-is-error.patch`: the map-lookup bullet at checkpoint 4 ends
"; quotes are required", the user's wording (8ac4cb5), no judge run. Only checkpoint 4 changes,
so the v5 clone is forked after checkpoint 3 with `bin/fork-run … --spec v6 --keep 3 --queue`:
checkpoints 1-2 are the v4 run's, 3 the v5 clone's, 4 re-run on v6.
Checkpoint 4 on v6, 22:10Z: 147/147 (job 142, 27 min). map_lookup_no_quotes passed, so the
quotes sentence is one for one, and every other checkpoint-4 case held. That is the first
147/147 on file_merger, but stitched: checkpoints 1-2 ran on v4, 3 on v5, 4 on v6 (the three
specs differ only at the checkpoints re-run after each change). Queued 22:11Z at the user's
standing instruction: a fresh full run of min12-ABDJKMN on v6 under bin/scb-strict (job 143),
the first of the two the twice bar needs.
Fresh run on v6, 22:11Z to 23:28Z (job 143): 46/46, 86/86, 104/104, 147/147, all four strict,
$22, 73 min. The first fresh full strict run on file_merger; the stitched fork had shown it once
across three spec versions, this is once in one run. v6 is strict once by the user's bar; queued
23:30Z under the standing plan: a second fresh run of the same config under bin/scb-strict
(job 144). Twice, and just-solve on v6 is next.
The repeat (job 144) was killed at 00:05Z 2026-09-11 on checkpoint 2 at the user's request and
its directory deleted: they count the v6 fork (147/147 across v4, v5, v6) and the fresh run
(147/147) as the two, so v6 is strict twice by their call and file_merger closes as a spec
question. Queued 00:09Z: the just-solve pair on v6 (jobs 145 and 146, `bin/queue add`, not
strict), the control for the spec's effect on the bare prompt.
Both just-solve jobs died 01:11Z 2026-09-11 on `No such option: --stop-after-checkpoint`: at
01:00Z the harness clone in `slop-code-bench/` was reset on the host onto a new branch
("fix: support Claude v2.1.2xx and higher"), which dropped the six applied source patches, so
scb no longer knows the flag. Job 145 had run three checkpoints on the patched harness first
(`…just-solve-specv6/20260910T1709`: 45/46, 84/86, 102/104, misses bool_nonstandard_strict from
checkpoint 1 and tsv_whitespace_values from checkpoint 2) and halted at the checkpoint-4
preview (exit 5); job 146 never started a checkpoint (exit 4). The run dir stays for a
`bin/queue resume` once the harness carries the patches again; 146 needs re-queueing.
Recovered 02:06Z 2026-09-11: runs now read a pinned, patched checkout at `harness/` built by
`python3 install.py` (48dc994), so the development clone can move freely. Job 147 resumes the
partial just-solve run at checkpoint 4; job 148 is the second just-solve run, queued behind it.

## just-solve on v6 (2026-09-11)

The spec's effect on the bare prompt. First run (job 145 for checkpoints 1-3, job 147 for
checkpoint 4 after the harness outage): 45/46, 84/86, 102/104, 142/147, $18, 73 min, against the
v0 control's 116/147. Five misses: bool_nonstandard_strict at checkpoint 1 (a column of `1` and
`true` must infer bool; v2's casting-rule sentence did not settle it for this prompt),
tsv_whitespace_values at checkpoint 2, and three alias cases at checkpoint 4 (correct_aliases
case1 and case2, nested_type_alias_with_parquet). None of the control's seventeen checkpoint-2
misses recur; two of its checkpoint-4 misses do. So the spec alone moves just-solve from 116 to
142, and the min12 prompt on the same spec takes the last five.
