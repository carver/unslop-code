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

`drafts/` holds patches that were proposed and not adopted as written.
