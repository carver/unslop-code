# Would "do what the standard library does" have helped? (2026-09-04)

Offline check of a candidate prompt rule, "where the spec is silent and no reading is
clearly intended, do what the Python standard library does", against the ambiguity
registries of seven datagate runs (min4, ABCHJK and its rerun, ABCFGHJK, v8, v8A, v8B:
609 entries, clustered into 166 questions, 126 of them recorded by two or more runs).
For each shared question: what the runs chose, what the stdlib does (verified with a
one-liner where it exists), what the hidden tests enforce, and the rule's effect. The
per-question table is `stdlib-fallback-tally.tsv`.

| effect | questions | meaning |
|---|---|---|
| none | 98 | stdlib has no opinion, or no test reaches the question |
| neutral | 20 | stdlib agrees with the tests and every run already chose that |
| fix | 5 | a run chose against the tests and the stdlib reading matches them |
| break | 3 | the stdlib reading contradicts the tests |

The five fixes are three questions. The cache flag's whitespace (two slugs):
`configparser` strips values on read and `getboolean` rejects an empty or blank one,
which is what checkpoints 5 and 6 demand together; min3's six misses and v8B's sit
here. Single-column files (two slugs): `csv.reader` and `DictReader` read one column
fine, which is ABCFGHJK's eleven misses. Blank lines: `DictReader` skips them, which
is the ABCHJK rerun's miss.

The three breaks are questions every run got right without the rule. `urlopen` accepts
`file:` and `ftp:` sources where the tests want 400. `csv.Sniffer` raises "could not
determine delimiter" on a single-column file, the exact reading behind ABCFGHJK's
cascade, so the single-column question sits on both lists depending on which csv
function the agent reaches for. `configparser.read()` silently ignores a missing
file where the tests want startup to fail.

Reading: as worded, the rule is a wash. Its fixes and breaks are the same size, the
largest fix is also a break, and nine of the twenty neutral questions are ones the
runs already agree on. The stdlib is a reliable tie-breaker for CSV parsing details
(blank lines, whitespace, one column via `DictReader`) and an unreliable one for
anything about validation strictness, where the tests consistently want the stricter
reading and the stdlib is permissive. Two places the rule would point against a
choice every run made, on questions no test reaches: the `utf-8` codec keeps a BOM in
the first header (only `utf-8-sig` strips it), and `int()` accepts `1_000`, `nan` and
`+5` where the runs reject them.

Side finding from the pass: ABCFGHJK's checkpoint 7 miss on
`test_duplicate_enrich_params_do_not_enable_metadata[yes-then-no]` has a two-column
fixture, so it is not a single-column file; it got the same non-tabular 400 anyway.
