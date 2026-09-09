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
| min11-ABDFJKMN, repeat | `…min11-ABDFJKMN/20260907T0810` | same config as the first run | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-07; the same seven misses; 1/5 strict, $17 (per checkpoint 2, 4, 3, 4, 3), 83 min, Monitor disallowed throughout. 60 registry entries all scored, Risk 0-45 (top: non-node-set results 45; whitespace-only text nodes 25; null vs empty text node 35). Quality: erosion 0.046, verbosity 0.322, ast 0.055, cloned 0.245 |
| min12-ABDFJKMN | `…min12-ABDFJKMN/20260908T2036` | min11-ABDFJKMN minus the intro's "with Red Green testing", 464 words; first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-09; the same seven misses as every xjq run; 1/5 strict, $13 (per checkpoint 9, 16, 15, 22, 21 min), 83 min. 63 registry entries all scored, Risk 0-45. Quality: erosion 0.030, verbosity 0.274, ast 0.053, cloned 0.216, each a little under the min11 pair |
| min12-ABDFJKMN, repeat | `…min12-ABDFJKMN/20260908T2212` | same config as the first run | 22/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-09; seven misses again but a different seven: the malformed-XML error case from checkpoint 1 (the first checkpoint-1 miss in ten xjq runs; registry T1, parse-as-HTML versus hard failure) carried to the end, while the whitespace-only element under `--text-all` passed; 0/5 strict, $15 (per checkpoint 9, 12, 12, 17, 22 min), 72 min. 63 registry entries all scored. Quality: erosion 0.030, verbosity 0.401, ast 0.025, cloned 0.360 |
| min12-ABDFJKMN on v1 | `…min12-ABDFJKMN-specv1/20260909T0430` | min12-ABDFJKMN on spec v1 (text flags one per element; no trailing newline); first of two | 23/23, 51/51, 95/96, 121/122, 166/167 | complete 2026-09-09; every one of the seven v0 misses passed; the one miss is the element half of the checkpoint-3 JSON empty-string test, which the old runs never reached: the empty string was serialized self-closing (`<key type="str"/>`) where the test wants an open-close pair, a reading no registry entry recorded this run. 2/5 strict, $13 (per checkpoint 11, 11, 9, 13, 14 min), 58 min. 57 registry entries all scored, Risk 0-45 (top: numeric XPath results 45; empty and whitespace-only text results 40). Quality: erosion 0.089, verbosity 0.312, ast 0.052, cloned 0.243 |
| min12-ABDFJKMN on v1, repeat | `…min12-ABDFJKMN-specv1/20260909T0533` | same config as the first run | 23/23, 51/51, 95/96, 121/122, 166/167 | complete 2026-09-09; the same single miss, the empty-string element serialized self-closing; 2/5 strict, $18 (per checkpoint 15, 13, 10, 14, 20 min), 72 min. 62 registry entries all scored, Risk 0-45. Quality: erosion 0.048, verbosity 0.276, ast 0.067, cloned 0.171 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260909T0650` | min12-ABDFJKMN minus F (generator floor), 444 words, on v0; first of two | 23/23, 47/51, 91/96, 116/122, 160/167 | complete 2026-09-09; the seven v0 misses; 1/5 strict, $10 (per checkpoint 6, 9, 8, 10, 12 min), 45 min. No hypothesis in the snapshot, as in every ABDFJKMN run. Quality in the table below |

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
