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
