# Blind judge over the v7 ambiguity registry

Run 2026-09-02, `bin/judge-ambiguities`, results in `outputs/judge/v7/`. Judge: Opus 5 through Claude Code print mode on the subscription. Each of the 134 entries in the v7 run's final AMBIGUITIES.md was judged 5 times under each of 8 prompt variants, 5360 judgments, $69 list price. The judge saw the cumulative spec up to the entry's checkpoint, the quoted spec text and the candidate readings, shuffled per sample. It never saw the tester's choice, rationale, tests or code. Calls were batched, up to 15 entries of one checkpoint per call in a random partition per variant and sample.

## Question

When the v7 tester chose a reading the hidden tests later contradicted, was that a coin flip a fresh look could land differently, a reasoning error a prompt hint could fix, or the model's settled prior? Five entries cost all 14 of v7's misses: T22 (encoding detection), T27 (rowid counts the header), T56 (charset on upload), T63 (charset ignored for spreadsheets), T74 (a force value is 400).

## Answer

Settled prior. On four of the five entries every one of 40 blind judgments picked the tester's reading; on the fifth, rowid, 35 of 40 did. No prompt variant moved any of them. Alternatives were shuffled and the judge picked list position 1 about half the time, so there is no position effect to explain the tester's habit of choosing its second-listed reading: it lists its preferred reading second.

| variant | agrees with tester | hidden reading on the 5 | picked position 1 |
|---|---|---|---|
| choose | 615/650 (95%) | 0/25 | 310/670 |
| choose+both | 619/650 (95%) | 1/25 | 305/670 |
| choose+impl | 611/650 (94%) | 1/25 | 297/670 |
| choose+both+impl | 611/650 (94%) | 0/25 | 335/670 |
| rule | 616/650 (95%) | 1/25 | 299/670 |
| rule+both | 615/650 (95%) | 0/25 | 313/670 |
| rule+impl | 601/650 (92%) | 1/25 | 353/670 |
| rule+both+impl | 610/650 (94%) | 1/25 | 305/670 |

The variants: `choose` asks for a reading number; `rule` asks the judge to write the intended rule first, then map it. `both` adds "the readings may not be exclusive; all of them together is a reading". `impl` adds "how hard a reading is to implement is the implementer's problem, judge the text only".

## The five families

| entry | tester | hidden | votes (all 40) | a rule the judge wrote |
|---|---|---|---|---|
| T22 How far must "detect encoding from content" go? | 2 | 1 | 2: 40 | Detection must be exact for self-describing streams (UTF-8, BOM-marked UTF-16/32); for indistinguishable 8-bit codepages only successful ingestion and structure |
| T27 Does `rowid` count the header row? | 2 | 1 | 2: 35, 1: 5 | `rowid` numbers data rows in source order starting at 1, ignoring the header line. |
| T56 `charset` for uploads | 2 | 1 | 2: 40 | `charset` is a `/convert` query parameter only; uploads are always decoded by detection and any `charset` part in the multipart body is just an ignored field. |
| T63 An unusable `charset` together with a spreadsheet source | 2 | 1 | 2: 40 | An unsupported or malformed `charset` value is rejected with 400 regardless of the source's actual format. |
| T74 "Any additional `force` value": a second parameter, or any value at all? | 2 | 1 | 2: 40 | Exactly one occurrence of `force` (with or without a value) is allowed; a second occurrence is HTTP 400. |

T74 is the clearest: the hidden tests reject a value-bearing `force`, and 40 of 40 judgments, including the 20 told that readings might both hold, still read "any additional force value" as "a second occurrence". The `impl` hint, aimed at the tester's "reading 1 is unimplementable" argument, changed nothing, because the judge does not reach for that argument in the first place; it simply reads the sentence the same way.

## Where the judge and the tester part ways

Overall agreement is 91%. The entries below are where a fresh reading differs from the in-context one. None of them cost a hidden test (the hidden suite either agrees with the tester there or does not cover it), but they are the places where the tester's choice is least stable.

| entry | tester | votes | title |
|---|---|---|---|
| I2 | 2 | 1: 40 | A *supported* charset that decodes into non-tabular content |
| T85 | 2 | 3: 36, 2: 4 | What does "trimmed" trim? |
| I7 | 2 | 1: 32, 2: 8 | What is the implementation-defined default `STORAGE_DIR`? |
| T36 | 1 | 2: 31, 1: 9 | What is the "stored value" that `exact`/`contains` compare against? |
| T96 | 2 | 1: 24, 2: 16 | Does "check every request" include a CORS preflight? |
| T50 | 2 | 1: 24, 2: 16 | `_shape` / `_rowid` / `_total` with an *invalid* value on `/export` |
| T44 | 2 | 3: 21, 2: 19 | Which error is reported when several things are wrong at once? |
| I6 | 2 | 2: 22, 1: 18 | A `multipart/*` request that is not `multipart/form-data` |
| T58 | 2 | 2: 24, 1: 16 | `multipart/*` that is not `multipart/form-data` |

Four entries (T9, T19, T21, T59) have no numbered choice in the registry (the tester wrote "both satisfy the spec" or similar) and are excluded from agreement counts.

## What this means for the next experiment

- Prompt-level heuristics for ambiguity resolution are not the lever. Two of the three we had in mind were tested here and moved nothing; the third, writing the rule before choosing, also moved nothing.
- A blind second opinion from the same model family would not have caught any of the five. A judge only helps where votes split, and the five did not split.
- The spec patch is the remaining lever for these 14 tests, and it is also the honest finding: the sentences read one way to the model and another way to the test author, consistently. The five proposed edits are in the 2026-09-02 chat and should go into a patched copy of the datagate specs for a fresh run.
- The 13 entries in the table above are candidates for the same treatment if a later run's hidden tests turn out to disagree with the tester there.

## Method notes

- Single-entry calls were tried first (`outputs/judge/v7-single-calls/`, 71 judgments) and abandoned: Claude Code print mode does not cache a custom system prompt between processes, so each call re-sent the spec at full price. Those 71 agree with the batched results.
- Two batched calls returned bare JSON objects without the array and were lost to the parser, then re-judged with a tolerant parser; the errored rows remain in `judgments.jsonl` and are skipped by `summarize`.
- Reproduce: `bin/judge-ambiguities run <v7 run dir> --out <dir>`; `bin/judge-ambiguities summarize <dir>`.
