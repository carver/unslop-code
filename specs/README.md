# Spec versions

The benchmark's own specs are v0, read from the slop-code cache (`~/.cache/scbench/problems`).
Every later version is a folder here holding unified diffs against v0, applied in filename
order, and each folder is self-contained: v2 carries v1's patch plus its own. `bin/spec-patch
<problem> <vN>` builds `specs/vN/problems/<problem>/` (not tracked) and a run selects it with
`SCBENCH_PROBLEMS_PATH=$PWD/specs/vN/problems`, which `bin/run-config --spec vN` writes into
the config and `bin/queue add` reads back. Results report the version each run read from its
own catalog record (`problem_catalog.json`), so a run's spec never changes under it.

| version | contents |
|---|---|
| v0 | the cached benchmark spec |
| v1 | `01-datagate-clarified.patch`: the five sentences from the 2026-09-02 blind-judge review (latin-1 detection, rowid, charset on uploads, charset on spreadsheets, `force` values). Runs made before this folder existed were named `-disambiguated` and read the same copy at `problems/`. |
| v2 | v1 plus `02-datagate-enrich-single.patch`, "Only a single, exact `enrich=yes` enables enrichment." (six of six blind judges: any repetition keeps enrichment off), and `03-datagate-delimiter-if-present.patch`, "Delimiter must be inferred from input, if present" (six of six: a delimiter-free header-plus-row file is a one-column table, a one-line JSON body still 400). Both 2026-09-05. |

`drafts/` holds patches that were proposed and not adopted as written.
