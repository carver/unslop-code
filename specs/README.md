# Spec versions

Versions are per problem. The benchmark's own spec of a problem is its v0, read from the
slop-code cache (`~/.cache/scbench/problems`). Every later version is a folder
`specs/<problem>/vN/` holding unified diffs against v0 (paths `a/<problem>/checkpoint_N.md`),
applied in filename order, and each folder is self-contained: v2 carries v1's patch plus its
own. `bin/spec-patch <problem> <vN>` builds `specs/<problem>/vN/problems/<problem>/` (not
tracked) and a run selects it with `SCBENCH_PROBLEMS_PATH=$PWD/specs/<problem>/vN/problems`,
which `bin/run-config --problem <problem> --spec vN` writes into the config and `bin/queue add`
reads back. Results report the version each run read from its own catalog record
(`problem_catalog.json`), so a run's spec never changes under it. A version number means
something only for its problem: datagate v2 and xjq v1 are unrelated.

Until 2026-09-09 versions were global folders `specs/vN/` carrying every problem's patches;
only datagate had any. `specs/v1` and `specs/v2` are symlinks to `datagate/v1` and
`datagate/v2` so the run directories, catalog records and configs written against the old
paths still resolve.

| problem | version | contents |
|---|---|---|
| datagate | v1 | `01-datagate-clarified.patch`: the five sentences from the 2026-09-02 blind-judge review (latin-1 detection, rowid, charset on uploads, charset on spreadsheets, `force` values). Runs made before the folder existed were named `-disambiguated` and read the same copy at `problems/`. |
| datagate | v2 | v1 plus `02-datagate-enrich-single.patch`, "Only a single, exact `enrich=yes` enables enrichment." (six of six blind judges: any repetition keeps enrichment off), and `03-datagate-delimiter-if-present.patch`, "Delimiter must be inferred from input, if present" (six of six: a delimiter-free header-plus-row file is a one-column table, a one-line JSON body still 400). Both 2026-09-05. |
| xjq | v1 | `01-text-flags-per-element.patch`: `--text` and `--text-all` bullets end ", one per element" (blind judges 37 of 40 for the tests' reading, from 26 of 40 unpatched; five of xjq's seven misses); `02-no-trailing-newline.patch`: "No trailing newline." after the output rule (judges 1 of 40; the user's call to try it; the other two misses). 2026-09-09, `notes/xjq-misses.md`. |
| file_merger | v1 | `01-tsv-crlf.patch` (TSV accepts CRLF), `02-authoritative-typed-sources.patch` ("JSONL does not outrank CSV"), `03-csv-backslash-quote.patch` (CSV accepts `\"`), `04-map-key-quoted.patch` (map keys are double-quoted). 2026-09-09. |
| file_merger | v2 | v1 plus `05-infer-by-cast-rules.patch`, "Inference recognises values by the casting rules below". 2026-09-09. |
| file_merger | v3 | v2 with 02 reworded: "JSONL ranks equal to CSV". Both strict runs on v1 and v2 read "does not outrank" as CSV outranking JSONL and halted at checkpoint 2. 2026-09-10. |
| file_merger | v4 | v3 plus `06-alias-cycle-at-load.patch`, "detect cycles proactively → error 2" (the user's wording; ten of ten blind judges, choose and rule variants: an unused cycle exits 2, `outputs/judge/file_merger-v4`). 2026-09-10. |
| file_merger | v5 | v4 plus `07-partition-encode-value-only.patch`, checkpoint 3: "Values use percent-encoding of UTF-8 bytes..." in place of "Apply percent-encoding..." (the user's wording, no judge run: the three runs that registered the question all encoded the column name too and failed at checkpoint 4). 2026-09-10. |
| file_merger | v6 | v5 plus `08-map-key-unquoted-is-error.patch`, checkpoint 4: "Map lookups with `["key"]` read value by exact key; quotes are required" (the user's wording, no judge run). 2026-09-10. |
| file_merger | v7 | v6 plus `09-timestamp-keeps-fraction.patch`, checkpoint 1: "`timestamp` normalized to UTC with `Z` (e.g., `2024-07-01T12:00:00Z`), keeping fractional seconds" (the user's wording, no judge run). A rare coin, not a shared reading: one opus run of 21 dropped the fraction, min13-ABDJKMNT on v6, 145/147. 2026-09-20. |
| mvvault | v1 | Six sentences from `notes/mvvault-misses.md`, the user's wording, no judge run: `01` the fetch-failure message includes `Source metadata fetch failure`; `02` the source request is "made with `urllib.request`" (the tests reroute only `urllib.request.urlopen`); `03` "A file matches if the name contains entry `id`, apart from partial downloads" (checkpoint 3; the spec says it at checkpoint 4); `04` "the browser URL uses this host as given" (kept though `0.0.0.0` is the worse program: the benchmark's mistake, not the agent's); `05` entries `sync` creates carry `annotations` as `[]`; `07` a rendered annotation shows "each `timecode` as raw seconds". Draft `06` (a missing vault redirects to the bare `/`) was dropped: the spec already says "Redirect to `/`". 2026-09-20. |
| mvvault | v2 | v1 plus `08-listing-entry-is-li.patch`, checkpoint 4: "Each `<li>` entry includes a link to `/catalog/<name>/<category>/<id>`" (the user's wording, no judge run). The tests find a listed entry by its link's enclosing `<li>`, which the spec never named; the Opus 5.5 min13 run on v1 rendered a `<table>` and failed all three listing tests. 2026-09-23. |
| rejector | v1 | Eight sentences from `notes/rejector-misses.md`, the user's wording (e81b2a7), no judge run: `01` "retry it up to 3 total requests" (reworded before any run, 0fbd0e3); `02` a single-task config's summary "keeps its previous keys and has no `tasks` object"; `03` "Send requests in input order", checkpoint 5's own rule moved to checkpoint 1 (the mock serves replies first come, first served, so the test stays a race); `04` "malformed line errors include `not valid JSON`"; `05` `result.passed` is `null` "except when `max_iterations` was reached, where it is `false`" (the test contradicted the spec); `06` the dry run's minutes "prefer precision over rounding" and `07` costs "to at least four decimal places" (the examples print one and two decimals); `08` under `llm_judge`, `extracted_answer` is the text `extract` took from the judge's reply. Not patched: `test_tpm_gate`, a missed wake-up in the agent's limiter. 2026-09-20. |
| rejector | v2 | v1 plus `09-first-number-extract-pairs-by-prompt.patch`, a **test patch**: no spec text changes. `test_first_number_extract` (checkpoint 2) served its two replies first come, first served to two concurrent rows, so the rows' arrival order decided the score (20 pass, 2 fail); it now pairs each reply to its row's prompt through conftest's `prompt_response_handler`. The reference solution passes 34/34 at checkpoint 2 and 79/79 at 5; with the two rows swapped, the v1 test fails and the v2 test passes. 2026-09-23. |

**Test patches.** A patch whose every target is under the problem's `tests/` fixes a hidden test
rather than adding a spec sentence (`is_test_patch` in `bin/patch-risk`). It rides in the same
version folder as the spec patches, so a version number mixes both kinds of change; `bin/patch-risk`
and the spec-patches page skip it, and `patch-tests.json` has no entry for it. The only one so far
is rejector v2's `09`. **TODO: before building the next test patch, give tests their own versioning**
(a test version per problem, recorded in each run beside its spec version), so a score change can be
put on the spec or on the tests.

`drafts/` holds patches that were proposed and not adopted as written.

Two files describe the patches for `bin/patch-risk` and the spec-patches page. `patch-tests.json` names
the hidden tests each patch answers (per hunk where a patch has several), from the patch headers and
`notes/critical-ambiguities.md`; its `_same` lists a sentence that repeats another's reading, so the two
count as one bug. `patch-entries.json` records, for each run that read a line unpatched and
failed those tests, which entry of its registry asked the line's question, or null when none did. Those
picks were made by reading the entries (2026-09-21, Sonnet agents per problem, both the runs that failed the
tests and the ones that passed; the failing side's every Choice then read by hand);
a new patch or run shows up under `bin/patch-risk <problem> --candidates` until its pick is recorded.
