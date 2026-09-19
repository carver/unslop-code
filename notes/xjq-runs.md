# Spectest run ledger (xjq, Opus 5, Claude Code 2.1.251, thinking high)

Every xjq run under `outputs/spectest/`, what changed, and how it ended, in the shape of
`spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; xjq has five checkpoints
and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`. The control
is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 23/23, 48/51, 92/96, 117/122, 160/167 | complete (dev6 sweep); 7 misses, 1/5 strict, $6. Quality: erosion 0.366, verbosity 0.253, ast 0.238, cloned 0.000 |
| just-solve on v0, repeat | `…just-solve/20260914T1248` | benchmark's own prompt on the unpatched spec, a per-problem run; the second just-solve v0 replicate for the 2x2 uplift grid (the first is the dev6 control) | 23/23, 48/51, 92/96, 117/122, 160/167 | complete 2026-09-14; 7 misses, the control's seven test for test (the text-all joining family from checkpoint 2 on, first_with_text_all at 4, first_match_only and the mixed-pipe-path extraction at 5); 1/5 strict, $4, 15 min. Quality: erosion 0.386, verbosity 0.170, ast 0.130, cloned 0.020 |
| v11 | `…spectest-v11/20260907T0137` | full v11 (`spectest-v11.jinja`); first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; 7 misses, six shared with the control (the `--text-all` family: joining multiple elements with newlines, deeply nested whitespace, `::text` first-match-only, `first` with `--text-all`, the empty-string JSON element) plus whitespace-only element as empty output; the control's mixed-pipe-path miss passed. 1/5 strict, $73, 137 min. 49 registry entries all scored, Risk 0-45 (top: non-node-set results 45, mixed `::text` comma lists 40, "immediate text content" 40; whitespace-only text results 25). Quality: erosion 0.080, verbosity 0.228, ast 0.050, cloned 0.156 |
| v11, repeat | `…spectest-v11/20260907T0401` | same config as the first run | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; the first run's seven misses, test for test, at every checkpoint; 1/5 strict, $134 (per checkpoint $2, 21, 3, 103, 4), 165 min. 53 registry entries all scored, Risk 0-45 (top: pretty-print 45, whitespace-only text results 45, exported text normalisation 40). Quality: erosion 0.051, verbosity 0.287, ast 0.059, cloned 0.206 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T0654` | the 468-word min11 subset (twice strict on datagate v2); first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; the v11 runs' seven misses, test for test; 1/5 strict, $14 (per checkpoint 2, 3, 2, 3, 3), 69 min; checkpoints 3-5 ran with Monitor disallowed. 51 registry entries all scored, Risk 0-45 (top: non-node XPath results 45, whitespace-only descendant text nodes 45). Quality: erosion 0.050, verbosity 0.355, ast 0.067, cloned 0.283 |
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260907T0810` | same config as the first run | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; the same seven misses; 1/5 strict, $17 (per checkpoint 2, 4, 3, 4, 3), 83 min, Monitor disallowed throughout. 60 registry entries all scored, Risk 0-45 (top: non-node-set results 45; whitespace-only text nodes 25; null vs empty text node 35). Quality: erosion 0.046, verbosity 0.322, ast 0.055, cloned 0.245 |
| min12-ABDFJKMN | `…min12-ABDFJKMN/20260908T2036` | min11-ABDFJKMN minus the intro's "with Red Green testing", 464 words; first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-09; the same seven misses as every xjq run; 1/5 strict, $13 (per checkpoint 9, 16, 15, 22, 21 min), 83 min. 63 registry entries all scored, Risk 0-45. Quality: erosion 0.030, verbosity 0.274, ast 0.053, cloned 0.216, each a little under the min11 pair |
| min12-ABDFJKMN, repeat | `…min12-ABDFJKMN/20260908T2212` | same config as the first run | 22/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-09; seven misses again but a different seven: the malformed-XML error case from checkpoint 1 (the first checkpoint-1 miss in ten xjq runs; registry T1, parse-as-HTML versus hard failure) carried to the end, while the whitespace-only element under `--text-all` passed; 0/5 strict, $15 (per checkpoint 9, 12, 12, 17, 22 min), 72 min. 63 registry entries all scored. Quality: erosion 0.030, verbosity 0.401, ast 0.025, cloned 0.360 |
| min12-ABDFJKMN on v1 | `…min12-ABDFJKMN-specv1/20260909T0430` | min12-ABDFJKMN on spec v1 (text flags one per element; no trailing newline); first of two | 23/23, 51/51, 95/96, 121/122, 166/167 | complete 2026-09-09; every one of the seven v0 misses passed; the one miss is the element half of the checkpoint-3 JSON empty-string test, which the old runs never reached: the empty string was serialized self-closing (`<key type="str"/>`) where the test wants an open-close pair, a reading no registry entry recorded this run. 2/5 strict, $13 (per checkpoint 11, 11, 9, 13, 14 min), 58 min. 57 registry entries all scored, Risk 0-45 (top: numeric XPath results 45; empty and whitespace-only text results 40). Quality: erosion 0.089, verbosity 0.312, ast 0.052, cloned 0.243 |
| min12-ABDFJKMN on v1, repeat | `…min12-ABDFJKMN-specv1/20260909T0533` | same config as the first run | 23/23, 51/51, 95/96, 121/122, 166/167 | complete 2026-09-09; the same single miss, the empty-string element serialized self-closing; 2/5 strict, $18 (per checkpoint 15, 13, 10, 14, 20 min), 72 min. 62 registry entries all scored, Risk 0-45. Quality: erosion 0.048, verbosity 0.276, ast 0.067, cloned 0.171 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260909T0650` | min12-ABDFJKMN minus F (generator floor), 444 words, on v0; first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-09; the seven v0 misses; 1/5 strict, $10 (per checkpoint 6, 9, 8, 10, 12 min), 45 min. No hypothesis in the snapshot, as in every ABDFJKMN run. Quality in the table below |
| min12-ABDJKMN on v0, repeat | `…min12-ABDJKMN/20260914T1526` | same config as the first run; the second min12 v0 replicate for the 2x2 uplift grid | 23/23, 48/51, 92/96, 117/122, 161/167 | complete 2026-09-14; 6 misses, the first run's seven minus test_text_all_on_whitespace_only_element_is_empty_output (the text-all joining family from checkpoint 2 on, empty-text JSON at 3, first_with_text_all at 4, first_match_only at 5); 1/5 strict, $9 (per checkpoint 1, 3, 2, 2, 2), 42 min. 53 entries all scored, Risk 0-40 (top: parse-as-XML/HTML vs malformed-is-error 40, direct text with several text children 40). Quality: erosion 0.020, verbosity 0.364, ast 0.019, cloned 0.331 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260919T0105` | min12 plus chunk T, the upstream anti-slop rule list (d902f32); first of two on v0 | 23/23, 48/51, 93/96, 118/122, 162/167 | complete 2026-09-19; 5 misses, all v0 families every earlier run shares (the two text-all joins at 2, the deeply nested whitespace case at 2, first-with-text-all at 4 and css first-match at 5); two of the seven usual v0 misses passed. 1/5 strict, $10, 37 min. Quality: erosion 0.000, verbosity 0.370, ast 0.012, cloned 0.353 |
| min13-ABDJKMNT on v0, repeat | `…min13-ABDJKMNT/20260919T0719` | same config as the first run; second of two | 23/23, 48/51, 93/96, 118/122, 162/167 | complete 2026-09-19; 5 misses, the same five as the first run (the two text-all joins and the deeply nested whitespace case at 2, first-with-text-all at 4, css first-match at 5); 1/5 strict, $12, 44 min. Quality: erosion 0.000, verbosity 0.341, ast 0.020, cloned 0.308; final checkpoint, implementation only (26% of LOC): ast 0.065, erosion 0.000, cloned 0.000 |
| min12-ABDFJKMN on v2 | `…min12-ABDFJKMN-specv2/20260909T0907` | min12-ABDFJKMN on spec v2 (v1 plus "null as empty (no self-closing tags)") | 23/23, 51/51, 96/96, 122/122, 166/167 | complete 2026-09-09; the v1 miss passed (empty string serialized open-close), and the one miss is new to the min runs: the mixed union `//name/text()\|//city` under `--text` must print the text node `Alice` first, and this run printed the element (registry T3, result sets mixing elements and strings, Risk 25: whole-result dispatch to the XML branch); the control missed the same test, every earlier min run passed it. 4/5 strict, $13 (per checkpoint 8, 11, 11, 16, 22 min), 67 min. Quality: erosion 0.048, verbosity 0.387, ast 0.044, cloned 0.319 |
| min12-ABDFJKMN on v3 (clone, checkpoint 5 only) | `…min12-ABDFJKMN-specv3/20260909T0907` | the v2 run's checkpoints 1-4 as they were, checkpoint 5 rerun against v3 (v2 plus "A union with mixed result types is written as text results." in checkpoint 5's union rules) | 23/23, 51/51, 96/96, 122/122, 167/167 | complete 2026-09-09; 0 misses, 5/5 strict; the rerun checkpoint cost $4 and 18 min ($14 and 64 min with the inherited four). The first strict xjq run, on a clone: the T3 registry entry (mixed result sets, Risk 25) still chose whole-result XML dispatch in its wording, but the union sentence carried the test. A full v3 run from checkpoint 1 is the honest confirmation |
| min12-ABDFJKMN on v3 | `…min12-ABDFJKMN-specv3/20260909T1123` | min12-ABDFJKMN on spec v3 from checkpoint 1 | 23/23, 51/51, 96/96, 122/122, 167/167 | complete 2026-09-09; 0 misses, 5/5 strict, $13 (per checkpoint 8, 18, 8, 16, 17 min), 67 min. The first strict xjq run from scratch; one of two. 60 registry entries, 56 scored, Risk 0-45 (top: non-node-set results 45; "scope of no self-closing tags" 32, the v2 sentence read as a question in its own right). Quality: erosion 0.020, verbosity 0.233, ast 0.031, cloned 0.191, the best xjq figures on record |
| just-solve on v3 | `…just-solve-specv3/20260909T1249` | benchmark's own prompt on spec v3; first of two | 23/23, 51/51, 96/96, 122/122, 167/167 | complete 2026-09-09; 0 misses, 5/5 strict, $6 (per checkpoint 2, 8, 3, 3, 3 min), 20 min. The bare prompt clears every one of the control's seven v0 misses on v3. Quality: erosion 0.321, verbosity 0.209, ast 0.178, cloned 0.000, the control's shape |
| just-solve on v3, repeat | `…just-solve-specv3/20260909T1314` | same config as the first run | 23/23, 51/51, 96/96, 122/122, 167/167 | complete 2026-09-09; 0 misses, 5/5 strict, $5 (per checkpoint 2, 6, 3, 3, 5 min), 19 min. just-solve is twice strict on xjq v3. Quality: erosion 0.498, verbosity 0.247, ast 0.213, cloned 0.000 |
| min12-ABDJKMN on v3 (strict) | `…min12-ABDJKMN-specv3/20260914T1103` | the 444-word no-F prompt on spec v3, strict, the min12 arm of the 2x2 uplift grid (jobs 149-158); first of two | 23/23, 51/51, 96/96, 122/122, 167/167 | complete 2026-09-14; 0 misses, 5/5 strict, $11 (per checkpoint 6, 10, 7, 11, 11 min), 46 min. Against the same prompt on v0: the seven text_all/first misses gone, nothing new. The first ABDJKMN run strict on xjq. 51 registry entries, 51 scored, Risk 0-45 (top: boolean XPath result 45; numeric XPath result and "all descendant text nodes" 40). Quality: erosion 0.060, verbosity 0.544, ast 0.044, cloned 0.489, the cloned and verbosity figures the worst on xjq (ABDFJKMN on v3: 0.254 and 0.309); four test files of 12-17 KB against a 21 KB xjq.py |
| min12-ABDJKMN on v3 (strict), repeat | `…min12-ABDJKMN-specv3/20260914T1744` | same config as the first run | 23/23, 51/51, 96/96, 122/122, 167/167 | complete 2026-09-14; 0 misses, 5/5 strict, $11 (per checkpoint 1, 3, 2, 2, 3), 54 min. min12-ABDJKMN is twice strict on xjq v3, the grid's min12 x v3 cell complete. 54 entries, 49 scored, Risk 0-45 (top: blank lines from whitespace-only text nodes 45, "no added pretty-print formatting" 45). Quality: erosion 0.026, verbosity 0.326, ast 0.012, cloned 0.306; one 134 KB test_xjq.py against a 21 KB xjq.py |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 160/167: seven misses, six of them the `--text-all` text-joining family from checkpoint
    2 on, plus the mixed-pipe-path redundant extraction at checkpoint 5.

### just-solve on v0, repeat (2026-09-14)

  - 160/167, the control's seven misses exactly, checkpoint for checkpoint: the v0 reading of
    `--text-all` is not a coin for the bare prompt. $4 and 15 min. Second replicate of the
    grid's just-solve x v0 cell.

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
  - repeat (160): the same seven, so xjq is settled for min11 too: 160/167 on all five prompted
    runs and the control. min11 pair $14 and $17 against v11's $73 and $134.

### min12-ABDFJKMN

  - first run (160): the seven misses again, $13 against min11's $14 and $17, 83 min against
    69 and 83, every quality column slightly under the min11 pair. On xjq the red/green line
    is inert too. First of two.
  - repeat (160): the same total by a different route; the malformed-XML case is the first
    checkpoint-1 miss on xjq, and one text-all case flipped to passing. Pair $13 and $15, 83 and
    72 min; ten xjq runs now, all 160.

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
Queued 2026-09-08 14:55Z at the user's request, at the end of the queue: two runs of
min12-ABDFJKMN on xjq (jobs 100-101; min11-ABDFJKMN minus the intro's "with Red Green
testing", 464 words). Compare with the min11 pair (160 and 160, $14 and $17).

### min12-ABDJKMN (without F)

  - first run (160): the seven v0 misses, $10 and 45 min, the cheapest and fastest xjq run.
    F had nothing to govern here either: no hypothesis in the snapshot. First of two.

### min12-ABDJKMN on spec v3

  - first run (167): strict, $11 and 46 min. The v3 sentences cleared the seven v0 misses for
    the no-F prompt as they did for ABDFJKMN and just-solve. Quality is the odd part: cloned
    0.489 and verbosity 0.544 against 0.254 and 0.309 for ABDFJKMN on the same spec; the test
    files are the bulk of the snapshot. First of two; the repeat is job 158.

### min12-ABDJKMN on v0, repeat (2026-09-14)

  - 161/167 against the first run's 160: the same v0 text-all reading, one test better
    (whitespace-only element). $9 and 42 min. Second replicate of the grid's min12 x v0 cell:
    160 and 161 against just-solve's 160 and 160, so on xjq v0 the prompt buys no correctness;
    cloned 0.331 and 0.322, verbosity 0.364 and 0.372, both above just-solve's.

  - repeat (167): strict again, $11 and 54 min. Twice strict; the no-F prompt closes xjq v3 as
    ABDFJKMN and just-solve did. Cloned 0.306 this time (0.489 first), still the test-file bulk:
    a single 134 KB test module.

### min13-ABDJKMNT on v0 (min12 plus the anti-slop list)

  - 162/167 against min12's 160 and 161 and just-solve's 160 and 160, so one to two tests up,
    inside the v0 spread; the five misses are the usual text-all readings. Erosion 0.000
    against min12's 0.031 and 0.020, ast 0.012 against 0.032; cloned 0.353 is the test-file
    dilution again. $10 and 37 min, the same as min12. First of two.

  - repeat (162): the same score and the same five misses as the first run, checkpoint for
    checkpoint. Pair: 162 and 162 against min12's 160 and 161 and just-solve's 160 and 160.
    Implementation only over the pair: erosion 0.000 against min12's 0.234, ast 0.053 against
    0.149, cloned 0.000 against 0.010, on 368 implementation lines per run against 407.
    $12 and 44 min. The tightest pair on any dev problem.

### just-solve on spec v3

  - first run (167): strict in 20 min for $6, against 160 on v0. The four sentences carry the
    bare prompt all the way; the min prompt's registry procedure was not what xjq needed once
    the spec said what the tests read. Quality stays the control's (erosion 0.321 against
    min12's 0.020): the sentences fixed the reading, not the code. First of two.
  - repeat (167): strict again, $5 and 19 min. Twice strict, the first prompt to be so on xjq.
    Erosion 0.498 this time, the bare prompt's usual band.

### min12-ABDFJKMN on spec v3 (checkpoint 5 rerun on the v2 clone)

  - 167/167. The mixed-union test passed with the checkpoint-5 sentence in view, and nothing
    else changed since checkpoints 1-4 are the v2 run's. Strict on xjq for the first time,
    with the caveat that a clone is one toss of one checkpoint; a full v3 run and a repeat
    are what the twice-strict rule wants.
  - full run (167): strict from checkpoint 1, $13, 67 min, with the best erosion xjq has
    shown (0.020). Four registry entries carry no score this time; the v2 sentence itself
    became an entry ("scope of no self-closing tags", Risk 32). Once strict; a repeat makes it twice.

### min12-ABDFJKMN on spec v2

  - first run (166): four strict checkpoints, the first on xjq. v2's sentence closed the
    empty-string miss; the one miss left is a checkpoint-5 coin (mixed union under `--text`,
    dispatched whole-result to XML) that the control also missed and eleven min runs passed.
    A repeat would most likely be strict; queue paused for the usage limit.

### min12-ABDFJKMN on spec v1

  - first run (166): the seven v0 misses all passed, sentence B's two included, although the
    judges never took B. The remaining miss is the element half of the JSON empty-string
    test (self-closing tag for an empty string), a checkpoint-3 conversion reading that sat
    behind the text half until v1 cleared it. First of two; strict is 167.
  - repeat (166): the same one miss, so v1 is settled at 166 and the self-closing tag is a
    stable reading, not a coin. Both v1 runs guard the text assignment with `if text:`, so an
    empty string leaves the element without a text node and lxml serializes it `<key
    type="str"/>`; the reference assigns the string unconditionally and lxml then writes
    `<key type="str"></key>` (null gets the same treatment there). Neither registry has an
    entry on it.

## Spec v1 (2026-09-09)

The review in `notes/xjq-misses.md` put every one of the seven standing misses under two
sentences. `specs/xjq/v1/`: the `--text` and `--text-all` bullets end ", one per element"
(five misses; blind judges 37 of 40 for the tests' reading against 26 of 40 unpatched) and the
checkpoint-1 output rule gains "No trailing newline." (two misses; judges 1 of 40, the user's
call to try it). Queued 11:25Z at the head of the queue: two runs of min12-ABDFJKMN on xjq v1
(jobs 115-116), against the v0 pairs at 160 (min11 $14/$17, min12 $13/$15). Strict would be
167/167.

Amendment 2026-09-09 12:40Z, min12-ABDFJKMN on xjq v1, first run: 166/167, 2/5 strict, $13,
58 min. Ten v0 runs sat at 160 with the same seven misses; on v1 every one of the seven
passed, the two under "No trailing newline." included, which the blind judges had given 1 of
40. The single miss is new to the ledger: `{"key": ""}` queried for the element must print
`<key type="str"></key>` and this run printed the self-closing form. The old runs failed the
same test on its text assertion first, so the element assertion was never scored. The repeat
(job 115) started 12:34Z.

Amendment 2026-09-09 13:55Z, min12-ABDFJKMN on xjq v1 repeated: 166/167, 2/5 strict, $18, 72
min. Two of two on v1 with one identical miss, so v1's two sentences did their work twice
over and the remaining reading is stable. The sentence: checkpoint 3, "Primitive values map to
element text: booleans as `true`/`false`, numbers as minimal string form, null as empty." It
says what null becomes and nothing about the empty string; the tests want `{"key": ""}` to
serialize as `<key type="str"></key>` (an element with empty text), and the agent's `if text:`
guard produces `<key type="str"/>`. The reference solution assigns the converted text
unconditionally, which gives the open-close form for both `""` and `null`. Candidate for a
v2, pending the user: name the empty string beside null and say the element keeps an empty
text node. The ABDJKMN sweep resumed with xjq (job 104) at 13:50Z.
Queued 2026-09-09 16:30Z at the user's request: `specs/xjq/v2/` = v1 plus
`03-empty-string-text.patch`, the user's wording "null as empty (no self-closing tags)" on the
checkpoint-3 primitive rule. One run of min12-ABDFJKMN on it (job 129), started alone while the
rest of the queue stays paused for the usage limit; the user's rule is to cancel it if
checkpoint 3 is not clean (the one v1 miss lives there). Note for the queue: `pueue start <id>`
resumes the whole group; job 106 (ABDJKMN on mvvault) started by mistake, was killed within a
minute (its stub run dir stays under outputs, ignored by results) and re-queued in place. To
start one job under a pause: stash the others, `pueue start`, `pueue pause --wait`, enqueue.

Amendment 2026-09-09 17:25Z, min12-ABDFJKMN on xjq v2: 166/167, 4/5 strict, $13, 67 min. The
user's "null as empty (no self-closing tags)" cleared the last v1 miss at checkpoint 3, and
checkpoints 1 to 4 are the first clean ones xjq has had. The single miss is a different test
from anything v1 or v2 touched: `--text` over `//name/text()|//city` should print `Alice`
first, and this run printed `<city>NYC</city>`, having dispatched a mixed node-set to the XML
branch as a whole (registry T3 at Risk 25). The control missed it too; every min run before
this one passed it, so it is a coin, not a gap the spec opened. xjq's three spec sentences
now cover its seven standing misses; a strict run needs one more toss. Nothing was queued
after this run: the queue stays paused for the user's usage limit.
Started 2026-09-09 18:20Z at the user's request, alone under the pause: `specs/xjq/v3/` = v2
plus `04-union-mixed-results-as-text.patch`, the user's "A union with mixed result types is
written as text results." in checkpoint 5's union rules, placed there because a checkpoint's
prompt carries only that checkpoint's spec. The run is a clone of the v2 run
(`…min12-ABDFJKMN-specv2/20260909T0907`) at `…min12-ABDFJKMN-specv3/20260909T0907` with its
checkpoint 5 removed, its config and catalog record pointed at v3, and the checkpoint-5 row
dropped from checkpoint_results.jsonl; the resume redoes checkpoint 5 only. Strict there is
167/167. The checkpoint-1 wording ("XML node results (exclusively)") stays an untracked draft.

Amendment 2026-09-09 18:25Z, xjq v3 on the v2 clone, checkpoint 5 only: 167/167. Three spec
versions, four sentences, and every hidden test on xjq passes once. The checkpoint-5 rerun
cost $4; the run dir carries the v2 run's first four checkpoints unchanged and is labelled
v3 in the results table because its catalog record was pointed at the v3 build. The queue
stays paused; a full v3 pair (about $30) is the next step when usage allows.

Amendment 2026-09-09 19:40Z, min12-ABDFJKMN on xjq v3, full run: 167/167, 5/5 strict, $13, 67
min. xjq is solved strictly from checkpoint 1 on a spec with four added sentences (v1: text
flags one per element, no trailing newline; v2: no self-closing tags; v3: a mixed union is
text output), at the same cost as the v0 runs that scored 160. Quality is the best xjq has
shown (erosion 0.020, verbosity 0.233). Under the twice-strict rule a repeat (about $13) is
what remains; not queued, the queue stays paused for the usage limit.
Started 2026-09-09 19:50Z at the user's request: just-solve on xjq v3, twice (jobs 132-133), the
control prompt against the clarified spec; the v0 control scored 160/167 with the same seven
misses the min prompts had. The 21 other queued jobs are stashed while these two run, so the
group is unpaused; they go back to Queued under a pause once 133 finishes.

Amendment 2026-09-09 20:20Z, just-solve on xjq v3: 167/167, 5/5 strict, $6, 20 min. The control
prompt, which scored 160 on v0 with the same seven misses as every min run, is strict on v3.
On xjq the whole gap was the spec: four sentences, and the bare prompt solves it at half the
min prompt's cost and a third of its time. What the min prompt still buys on xjq is code
quality (erosion 0.020 against 0.321). The repeat (job 133) started 20:15Z.

Amendment 2026-09-09 20:45Z, just-solve on xjq v3 repeated: 167/167, 5/5 strict, $5, 19 min.
The benchmark's own prompt is twice strict on xjq v3, the first prompt twice strict on this
problem; min12-ABDFJKMN is strict once (plus the clone). xjq is closed as a spec question:
four sentences, and every prompt tried on v3 passes every hidden test. The queue is paused
again with the 21 sweep jobs back in it.
