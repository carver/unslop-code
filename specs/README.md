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

`drafts/` holds patches that were proposed and not adopted as written, or not yet decided:
`xjq-01-text-flags-per-element.patch` and `xjq-02-no-trailing-newline.patch` are the
2026-09-09 xjq review's two sentences, pending the user's call (`notes/xjq-misses.md`).
