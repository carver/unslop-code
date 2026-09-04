# Can a blind judge rank ambiguities by risk? (2026-09-04)

Question: given a registry entry (spec quote, question, the readings taken), can a model
assign a risk number that puts the ambiguities the hidden tests reject above the ones
every run gets right? If so, a confidence line in the registry is worth adding, and a
reviewer reads the top of the list instead of all of it.

Method: the 126 questions recorded by two or more of seven registry runs (see
`stdlib-fallback-tally.md` for the clustering). Four judge agents, each given the spec
(`problems/datagate/checkpoint_*.md`) and the packets, forbidden the tests, the run
outputs and the notes. Choices were shuffled and stripped of run names, and the judges
were told that how many choices share a reading is an artefact. Each question got: the
distinct readings, a probability per reading that the tests accept it, a risk (chance a
careful implementer lands on a rejected reading), and a bet. Outcomes come from the
tally: six questions where a run chose against the tests ("flip"), 96 the tests reach
and every run got right ("ok"), 24 no test reaches. Table: `ambiguity-risk-judge.tsv`.

| risk | flip | ok | untested |
|---|---|---|---|
| 0-19 | 1 | 83 | 19 |
| 20-39 | 5 | 12 | 5 |
| 40-59 | 0 | 1 | 0 |

Every flip sits at risk 18 or above. That threshold flags 27 of 126 questions: the six
flips, 16 tested-ok, five untested. The cross-run disagreement proxy from the tally
flags 38 and catches five of six. So the judge is the better triage: a fifth of the
registry, nothing known missed. Its risk numbers never exceed 40, which is honest given
that most entries are fine, and the top of the false-positive list (distinct-count
semantics, column type labels, numeric grammar, ragged rows) is exactly the set of
enrichment and parsing questions a spec author would want to look at anyway.

Bets: right on five flips (drop blank lines, trim the cache flag, a single delimiter
reading, repeated enrich turns enrichment off, the non-tabular row rule) and wrong on
one. On the single-column file the judge rated the risk highest in its batch, then bet
on the 400, reasoning that "non-tabular content" must be reachable and that a
`csv.Sniffer`-based reference would raise. Same wrong turn as ABCFGHJK and min2, made
with the same confidence. Risk ranking and picking the right side are different skills;
the first is what a confidence score needs.

What this supports. A registry line "Risk: NN% that the hidden tests take another
reading", with the number meant as a triage rank, not a probability to be trusted
alone. Calibration target for later problems: every rejected reading above the
threshold, under a quarter of entries flagged. Two open questions before wiring it into
a prompt: whether the implementing agent, rating its own choice mid-run, ranks as well
as a judge that saw seven runs' readings side by side, and whether asking for the
number changes the choices (it may make the agent hedge toward permissive readings).
The cheap next step is to ask the judge again with one run's choice only, no
alternatives from other runs, and see if the ranking holds.

## Second pass: one run's entry at a time (2026-09-04 17:00Z)

Same 126 questions, same rules, but each judge saw a single run's entry, picked at
random: its spec quote, its own alternatives, its one choice. This is the view an
implementing agent has when rating its own entry. Table: `ambiguity-risk-judge-solo.tsv`.

| risk | flip | ok | untested |
|---|---|---|---|
| 0-19 | 2 | 83 | 20 |
| 20-39 | 4 | 12 | 3 |
| 40-59 | 0 | 1 | 1 |

The big coin flips still rank at the top: single-column 35, non-tabular 30, cache flag
28, delimiter inference 20. The two rare ones sink: blank lines to 15, repeated enrich
to 10. Capturing all six now needs risk 10 or above, which flags 78 of 126; the first
pass captured all six at 27. Rank correlation between the two passes is 0.67, and 17 of
the top 27 overlap. On repeated enrich the judge saw v8B's wrong choice and gave it 90.

Reading: seeing several runs' readings side by side is worth a lot even when the judge
is told to ignore how many chose each; the spread of readings is itself the signal. A
self-rated risk line will catch the questions a prompt rule could also catch (the ones
where the spec's wording clearly leaves two readings) and will miss the one-in-fourteen
slips, where the agent is confident and wrong. It is a triage aid for a reviewer, not
a fix for reliability.

## Third pass: the question that matters, spec defects (2026-09-04 18:00Z)

The first two passes scored implementer risk: will a careful reader pick a reading the
tests reject. That mixes two things. The one worth a confidence line is narrower: did
the test author assert a reading the spec text does not support, so that the spec
needs a sentence. The five patched sentences are that class, and `ambiguity-judge.md`
showed a "which reading wins" judge cannot find them (40 of 40 blind judgments agreed
with the tester on four of the five). This pass asks a different question of the
wording itself.

Data: v7's registry, 126 entries recorded against the unpatched spec, the run whose
misses produced the patch. Four judges, each with the unpatched spec (reversed from
`problems/datagate-clarified.patch` into scratch) and a batch of entries with the
quoted sentence, the tester's alternatives and its choice. Barred from the patched
spec, the tests, outputs and notes. Score: "probability the hidden tests assert a
reading a careful reader would not predict from this text", plus the most likely such
reading. Table: `ambiguity-defect-judge-v7.tsv`.

| defect | patched | other |
|---|---|---|
| 0-19 | 0 | 80 |
| 20-39 | 5 | 32 |
| 40-59 | 0 | 9 |

| family | score | rank of 126 | judge's "hidden reading" |
|---|---|---|---|
| encoding detection depth (T22) | 35 | 13 | latin-1 fixtures round-trip with no charset given |
| any force value (T74) | 35 | 15 | force with any value is 400, a presence flag takes none |
| charset on uploads (T56) | 30 | 23 | /upload honours charset like /convert |
| bad charset with a spreadsheet (T63) | 28 | 26 | a malformed charset is ignored for a spreadsheet source |
| rowid counts the header (T27) | 25 | 32 | first data row is rowid 2, the header is line 1 |

Every one of the five is in the top quarter, and the hidden-reading column is the
patch: all five match what `datagate-clarified.patch` later added, written by a judge
that saw neither the tests nor the patch. The threshold that captures all five is
defect 25, which flags 35 of 126, thirty of them not patched. Four of those thirty are
sentences that later flipped on the patched spec for implementer-side reasons: the
single-column 400 (T15, scored 40), cell whitespace trimming (T11, 40), the cache flag's
whitespace (T72, 40) and repeated enrich (T107, 30). So the score ranks "sentences that
will cause trouble", tester-side or implementer-side, and the top quarter of a registry
is where both kinds live.

What this supports, concretely. A `Defect: NN%` line per entry, defined as the chance
the hidden tests assert a reading the text does not support, with the divergent reading
named beside it. Calibration on datagate: everything patched sits at 25 or above, and a
reviewer reads 35 entries instead of 126. The named divergent reading is a draft patch
sentence. For the next problem the loop becomes registry, defect judge over the top
quarter, then patch the sentences whose named reading the tests confirm, instead of
waiting for a run to fail on each.

## Fourth pass: the agreed wording, the author's tested preference (2026-09-04 21:00Z)

Same v7 entries, same unpatched spec, same blindness. The score is now `differs`: "the
probability that the spec's author, who wrote the hidden tests against their own
implementation, has a preference on this point that a hidden test checks and that
differs from the choice recorded here", with the judge told to reason about the
author's implementation and fixtures rather than the prose, and to name the differing
preference. Table: `ambiguity-defect-judge-v7-author.tsv`.

| differs | patched | other |
|---|---|---|
| 0-19 | 1 | 101 |
| 20-39 | 3 | 18 |
| 40-59 | 1 | 1 |

| family | differs | rank of 125 | third pass |
|---|---|---|---|
| rowid counts the header (T27) | 40 | 2 | 25, rank 32 |
| encoding detection depth (T22) | 30 | 7 | 35, rank 13 |
| charset on uploads (T56) | 25 | 14 | 30, rank 23 |
| any force value (T74) | 20 | 20 | 35, rank 15 |
| bad charset with a spreadsheet (T63) | 10 | 59 | 28, rank 26 |

Sharper at the top, one dropped. Four of the five are now in the top 20 of 125, and
101 entries sit under 20, so the flagged set at a threshold of 20 is 23 entries, 18
percent of the registry, against 35 at the third pass's threshold of 25. The spreadsheet
charset family fell to 10: the judge named the patched preference exactly, "invalid
charset is ignored when the source is a spreadsheet", and then judged that the author
would not write a fixture for it. Capturing all five under this wording needs a
threshold of 10, which flags 65. Rank correlation with the third pass is 0.78. One
entry (T95) was skipped by its judge; it is not one of the five.

The named preferences match the patch on all five again, and the top of the unpatched
list is the same set as before: numeric grammar (T10, 45), distinct-count semantics,
lexicographic sort, extension-based format detection, and the three sentences that
later flipped on the patched spec, the single-column 400 (T15, 30), the cache flag's
whitespace (T72, 30) and padded numeric cells (T11, 20).

Reading. Conditioning on "a hidden test checks it" is the right definition and it buys
a tighter list, but it makes the judge guess at fixture coverage, and that guess is the
one thing it cannot know. The miss is exactly a coverage guess gone wrong. For triage
the two passes are complementary: the third pass's ceiling of 25 caught everything at
28 percent; this wording's ceiling of 20 catches four of five at 18 percent. The
registry line should use this wording, since it is the one an agent can answer about
its own choice, and the review threshold should be set knowing that a low number can
mean "the author agrees" or "the author never tested it", and only the first is safe.
