# The five sentences

Where the datagate spec and its hidden tests disagree, and what it took to fix each one.

Published page: https://claude.ai/code/artifact/f4e7d4b9-fe2c-4b56-821d-4cbc96e8449d (source `report/five-sentences.html`; republish that file to update it).

## Summary

The v7 run of the spectest prompt on datagate (Opus 5, Claude Code 2.1.251, 7 checkpoints, 405 hidden tests at the end) had zero process failures and solved checkpoints 3, 6 and 7 in isolation. It lost 14 tests. Every one of the 14 traces to a single sentence in the spec that the model reads one way and the test author meant the other way, and the tester wrote each of those readings down in its ambiguity registry before a line of implementation existed.

| # | sentence (checkpoint) | tests lost | fix |
|---|---|---|---|
| T22 | "detect encoding from content" (1) | 1, at every checkpoint | name the fallback: unambiguous detection, else latin-1 |
| T27 | "1-based source-file row number" (2) | 4 | "starting at the header" |
| T63 | "`charset` applies only to text CSV sources" (4) | 2 | "applies and validates only for" |
| T56 | `/upload` lists no parameters (4) | 2 | "and `charset` query parameter" |
| T74 | "Any additional `force` value is HTTP 400" (5) | 5 | delete "additional" |

Three pieces of evidence sit behind each section. The tester's registry entry, verbatim, shows the reading was a considered choice, not an oversight. A blind judge, 5360 fresh judgments across eight prompt variants, shows the same model makes the same choice every time from the spec alone: 195 of 200 on these five entries. And the patched run shows the reworded sentences flip the outcome: all seven checkpoints strict, 405 of 405 at the end, where v7 had no strict checkpoint at all.

Sources: `outputs/spectest/opus-5_2.1.251_high_spectest-v7/20260901T0726` (the run and its registry), `notes/ambiguity-judge.md` (the judge), `problems/datagate-clarified.patch` (the fix), `outputs/spectest/opus-5_2.1.251_high_spectest-v8-disambiguated/20260902T0555` (the patched run).

## T22: Encoding detection

Checkpoint 1. 1 test, failed at every one of 7 checkpoints.

**The sentence.** `charset` | no | Character encoding for decoding CSV bytes. **If omitted, detect encoding from content.**

**In context.**

```markdown
### Ingestion: `GET /convert`

| Parameter | Required | Description |
| --------- | -------- | ----------- |
| `source`  | yes      | URL of the remote CSV file |
| `charset` | no       | Character encoding for decoding CSV bytes. If omitted, detect encoding from content. |

Errors:

| Condition | Status |
| --- | --- |
| Unsupported or malformed `charset` | 400 |
| Non-tabular content | 400 |

### CSV Parsing

- If `/convert` receives `charset`, use it to decode bytes. Otherwise detect encoding.
```

**What the tester recorded**, verbatim from AMBIGUITIES.md:

    ## T22 — How far must "detect encoding from content" go?

    **Spec Text**
    > `charset` | no | ... If omitted, detect encoding from content.
    > If `/convert` receives `charset`, use it to decode bytes. Otherwise detect
    > encoding.

    **Alternatives**
    1. Detection must recover the exact original text for *any* encoding, including
       8-bit codepages (latin-1, cp1252, cp1250, koi8-r, ...).
    2. Detection must recover the exact text for self-describing byte streams
       (UTF-8, UTF-8+BOM, UTF-16/32 with BOM); for 8-bit codepages, which are not
       distinguishable in principle, only ingestion and structural correctness are
       required — that is what `charset` exists for.

    **Choice** — (2). Reading (1) is not achievable by any implementation: measured
    in this environment, both `charset_normalizer` and `chardet` identify a 36-row
    French CSV encoded as latin-1 *and* the same document encoded as cp1252 as
    `cp1250` — the byte sequences are genuinely ambiguous. SPEC pairs "detect" with
    an explicit `charset` override precisely for this case. Tests therefore assert
    exact round-trips for self-describing encodings, and for 8-bit codepages assert
    only that the file ingests with the right columns/row count and preserved ASCII
    skeleton — plus that an explicit `charset` does give an exact round trip.
    *Tests:* `test_06_csv_parsing.py::test_detection_on_larger_8bit_document`,
    `::test_8bit_document_round_trips_with_explicit_charset`,
    `::test_detects_utf8_with_bom`, `::test_detects_utf16_with_bom`,
    `test_08_properties.py::test_prop_encoding_detection_round_trips`,
    `test_09_comparison.py::test_agrees_with_charset_detectors`.

    ---

    # Ambiguities found during implementation

**What the hidden tests expect.** A six-byte latin-1 file decodes to the exact text without a `charset` hint. The reference solution has no detector at all: it tries UTF-8 with BOM, UTF-8, cp1252, then latin-1, and the first that decodes wins.

- `test_checkpoint_1.py::test_autodetect_latin1`: source bytes are `"name\ncafé\n".encode("iso-8859-1")`, no `charset`; expects `rows == [["café"]]`

**What got built.** The tester measured that charset-normalizer and chardet cannot tell latin-1 from cp1252 from cp1250 and concluded exact round-trips were unachievable for 8-bit codepages, so the tests only asserted structural correctness there. The implementation handed the bytes to charset-normalizer, which decoded the sample as an Arabic codepage: `cafﻠ`.

**The fix.** If omitted, **detect unambiguous encoding from content, else latin-1.**

**Evidence.** Blind judge: the vote stayed 0/20 because neither registry alternative describes a fallback ladder, but all ten rule-first answers described exactly that ladder. Patched run: checkpoint 1 went 50/50, the first time in the series.

## T27: Which row is row 1

Checkpoint 2. 4 tests.

**The sentence.** `_shape=objects`: `rows` is objects and includes `rowid` (**1-based source-file row number**). `rowid` is not in `columns`.

**In context.**

```markdown
### Response shape

`_shape=lists` (default): `rows` is arrays.

`_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file row number). `rowid` is not in `columns`.

### Visibility toggles

`_rowid=hide` removes `rowid`.
```

**What the tester recorded**, verbatim from AMBIGUITIES.md:

    ## T27 — Does `rowid` count the header row?

    **Spec Text**
    > `_shape=objects`: `rows` is objects and includes `rowid` (1-based
    > source-file row number).

    **Alternatives**
    1. The header is line 1 of the source file, so the first data row is `rowid` 2.
    2. `rowid` numbers the *data* rows: the first data row is `rowid` 1.

    **Choice** — (2). "1-based" only says the count starts at one, and a dataset
    holds data rows, not the header (which SPEC reports separately as `columns`).
    The parallel implementation named by this API surface (datasette) uses SQLite's
    `rowid`, which is 1 for the first inserted data row. Reading (1) would also
    make `rowid` unusable as an index into `rows`.
    *Tests:* `test_10_pagination_sorting_shape.py::test_rowid_is_the_one_based_source_row_number`,
    `::test_rowid_on_the_smallest_table_is_one`,
    `::test_rowid_follows_the_source_row_through_offset`,
    `test_11_control_properties.py::test_prop_objects_shape`,
    `::test_prop_rowid_tracks_the_source_row_under_pagination`.

**What the hidden tests expect.** The header line is row 1 of the source file, so the first data row is 2. `rowid` is a line number, not an index into `rows`.

- `test_checkpoint_2.py::test_shape_objects_includes_rowid`: first object row has `rowid == 2` and `name == "Alice"`
- `test_checkpoint_2.py::test_rowid_sequential_all_rows`: rowids over the whole dataset are `[2, 3, 4, 5, 6]`
- `test_checkpoint_2.py::test_rowid_ignores_sort`: sorted by `age`, page size 2: Bob keeps `rowid 3`, Diana keeps `rowid 5`
- `test_checkpoint_4.py::test_spreadsheet_query_controls`: an `.xlsx` dataset queried with `_shape=objects` returns `{"rowid": 2, ...}` for its first data row

**What got built.** The tester read "1-based" as "the count starts at one" and "row" as "data row", citing SQLite's `rowid` (1 for the first inserted row) and the point that reading 1 makes `rowid` unusable as an index into `rows`. Every data row came out one too low, at every checkpoint from 2 onward, and again through the spreadsheet path at checkpoint 4.

**The fix.** `rowid` (1-based source-file row number, **starting at the header**).

**Evidence.** Blind judge: 35 of 40 chose the data-row reading on the original sentence; 20 of 20 chose the header reading on the patched one. Patched run: checkpoints 2 and 4 both strict.

## T63: A bad charset on a spreadsheet

Checkpoint 4. 2 tests.

**The sentence.** **`charset` applies only to text CSV sources.**

**In context.**

```markdown
### Multi-Format Ingestion

`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`.
Only the first worksheet is ingested.
The first sheet must be tabular (header + at least one data row) or `HTTP 400`.
`charset` applies only to text CSV sources.
Unrecognized format: `HTTP 400`.

(checkpoint 1, still in force)  | Unsupported or malformed `charset` | 400 |
```

**What the tester recorded**, verbatim from AMBIGUITIES.md:

    ## T63 — An unusable `charset` together with a spreadsheet source

    **Spec Text**
    > `charset` applies only to text CSV sources.
    > (earlier section) | Unsupported or malformed `charset` | 400 |

    **Alternatives**
    1. Since the charset "applies only to text CSV sources", it is not looked at for
       a spreadsheet, so `charset=not-a-charset` with an `.xlsx` source succeeds.
    2. The earlier error row is unconditional: an unusable `charset` value is a bad
       request whatever the source turns out to be; the new sentence is about the
       *effect* of a usable charset, not about validating the parameter.

    **Choice** — (2). The error table entry is written about the parameter, not
    about the source, and it is reached before the source is even fetched; that also
    keeps the error deterministic for a URL whose content is unknown. The
    complementary half — a *valid* charset must not change a spreadsheet's parse —
    is asserted directly.
    *Tests:* `test_18_multiformat.py::test_malformed_charset_is_still_400_for_a_spreadsheet`,
    `::test_charset_does_not_change_a_spreadsheet`, `::test_charset_does_not_break_an_xls`,
    `test_19_export_upload_properties.py::test_prop_charset_does_not_change_a_spreadsheet`.

**What the hidden tests expect.** For a spreadsheet the parameter is neither used nor looked at. An unusable value is not an error, because nothing tries to decode with it.

- `test_checkpoint_4.py::test_convert_spreadsheet_invalid_charset_ignored[xls]`: `/convert?charset=bad-charset-name` on an `.xls` source succeeds and the rows come back
- `test_checkpoint_4.py::test_convert_spreadsheet_invalid_charset_ignored[xlsx]`: same, `.xlsx`

**What got built.** The tester read the checkpoint-1 error row as unconditional: a malformed `charset` is a bad request whatever the source turns out to be, validated before the source is even fetched. The implementation returned 400.

**The fix.** `charset` applies **and validates** only for text CSV sources.

**Evidence.** Blind judge: 40 of 40 chose the validate-first reading on the original. "Elsewhere, ignore it" moved it to 13 of 20; "Elsewhere, drop it" fell back to 5 of 20, with the judge explaining that dropping a value is not the same as not checking it. "applies and validates only for" went 20 of 20, then 6 of 6 after a preposition change. Patched run: checkpoint 4 strict.

## T56: Charset on upload

Checkpoint 4. 2 tests.

**The sentence.** **`POST /upload` accepts multipart form with field `file` or `attachment`.** (and, from the next section, `charset` applies only to text CSV sources.)

**In context.**

```markdown
### File Upload

`POST /upload` accepts multipart form with field `file` or `attachment`.

Re-uploading the same file bytes yields the same dataset id.

Upload status:

- non-multipart request: `HTTP 415`
- malformed multipart or missing both `file` and `attachment`: `HTTP 400`
```

**What the tester recorded**, verbatim from AMBIGUITIES.md:

    ## T56 — `charset` for uploads

    **Spec Text**
    > `charset` applies only to text CSV sources.
    > (earlier section) `charset` | no | ... If omitted, detect encoding from
    > content.

    **Alternatives**
    1. `/upload` must accept a `charset` (query parameter or form field) with the
       same meaning it has on `/convert`.
    2. SPEC gives `/upload` no parameters at all, so an upload is always decoded by
       detection; an extra `charset` field, if sent, is simply an unrelated form
       field.

    **Choice** — (2), for what is *asserted*. The upload section defines exactly two
    field names and no parameters. Tests therefore assert that detection works for
    uploads (self-describing encodings round-trip exactly; 8-bit codepages ingest
    structurally, as in T22) and that an extra `charset` field never breaks the
    upload — so an implementation that additionally honours it still passes.
    *Tests:* `test_17_upload.py::test_upload_detects_encoding`,
    `::test_upload_of_utf8_bom_csv`,
    `::test_upload_of_latin1_csv_is_structurally_correct`,
    `::test_upload_ignores_unrelated_extra_fields`.

**What the hidden tests expect.** `/upload` honours the same `charset` query parameter as `/convert`. The reference solution reads it from the query string on both routes.

- `test_checkpoint_4.py::test_upload_csv_charset_honored`: `POST /upload?charset=iso-8859-1` with a latin-1 file; expects `rows == [["café"]]`
- `test_checkpoint_4.py::test_export_charset_upload`: same upload, then `/export`; expects `[["name"], ["café"]]` as UTF-8 CSV

**What got built.** The tester noted the upload section names two form fields and no parameters, and chose to assert only that detection works for uploads and that an extra field never breaks one. The implementation never looked for `charset` on `/upload`, and a latin-1 upload came out mangled, on ingest and again on export.

**The fix.** `POST /upload` accepts multipart form with field `file` or `attachment`, **and `charset` query parameter**.

**Evidence.** Blind judge: 40 of 40 chose the no-parameters reading on the original. An early patch, "and `charset`", won the vote 20 of 20 but every rule-first answer read it as a third multipart field; "and `charset` query parameter" won 20 of 20 with every answer saying query parameter. Patched run: checkpoint 4 strict.

## T74: A force with a value

Checkpoint 5. 5 tests.

**The sentence.** `force` is a presence flag. If present once, it forces re-ingestion and replaces the cached dataset. **Any additional `force` value is `HTTP 400`.**

**In context.**

```markdown
### Per-request bypass

`force` is a presence flag. If present once, it forces re-ingestion and replaces the cached dataset.
Any additional `force` value is `HTTP 400`.

If caching is disabled, `force` has no additional effect.
```

**What the tester recorded**, verbatim from AMBIGUITIES.md:

    ## T74 — "Any additional `force` value": a second parameter, or any value at all?

    **Spec Text**
    > `force` is a presence flag. If present once, it forces re-ingestion and
    > replaces the cached dataset.
    > Any additional `force` value is `HTTP 400`.

    **Alternatives**
    1. "additional value" = a value beyond mere presence, i.e. `?force` is fine but
       `?force=1` is `HTTP 400`.
    2. "additional value" = an additional occurrence of the parameter, i.e. exactly
       one `force` (whatever its value, including none) is fine and
       `?force&force` / `?force=1&force=2` is `HTTP 400`.

    **Choice** — (2). "`force` is a **presence** flag" says the value is never
    examined, and "If present **once**" sets up the contrast that "additional"
    completes — once vs. more than once. Reading (1) also cannot be implemented
    coherently: a bare `?force` and `?force=` are the same thing to every standard
    query parser, so "presence without a value" is not a distinction the wire
    format reliably carries. This matches how the earlier section words its own
    repetition rule ("Any repeated control parameter ... is `HTTP 400`").
    Consequence deliberately asserted: `force=0` and `force=false` still force —
    the value is not read.
    *Tests:* `test_21_cache.py::test_force_any_single_value_forces` (bare, empty,
    `0`, `false`, `off`, arbitrary text),
    `::test_repeated_force_is_400`, `::test_repeated_force_error_response_has_no_endpoint`,
    `test_23_cache_properties.py::test_prop_any_single_force_value_forces`,
    `::test_prop_repeated_force_is_400`.

**What the hidden tests expect.** A bare `?force` forces. A `force` carrying any value is 400. A repeated `force` is also 400, and that half was never in doubt.

- `test_checkpoint_5.py::test_force_variants_trigger_refresh[true|1|yes|on]`: `/convert?force=true` (and `1`, `yes`, `on`) returns the 400 error envelope
- `test_checkpoint_5.py::test_arbitrary_force_triggers_refresh`: `/convert?force=ignored` returns the 400 error envelope

**What got built.** The tester read "additional value" as "a second occurrence", reasoning that a presence flag never examines its value and that reading 1 was unimplementable because `?force` and `?force=` look identical to a query parser. That last claim is false: the rule the tests want is "empty value forces, non-empty value is 400", which any parser can express. The tests then asserted that `0`, `false`, `off` and arbitrary text all force, and the implementation did exactly that.

**The fix.** Any **~~additional~~** `force` value is `HTTP 400`.

**Evidence.** Blind judge: 40 of 40 chose the second-occurrence reading on the original, including the 20 judgments told that both readings might hold at once and the 20 told that implementability was not their concern. Deleting one word flipped it to 20 of 20. Patched run: checkpoint 5 strict, 276/276.

## What this says about the benchmark

The hidden tests are the spec's real definition, and on these five points the written spec does not carry it. Three of the five are true forks a careful reader could take either way (rowid, spreadsheet charset, upload charset); two are sentences where the literal noun points at the intended reading but a plausible argument talks the reader out of it (force, encoding). In every case the tester found the fork, wrote it down, and argued for the wrong branch, and a blind re-reading by the same model picks the same branch. Prompt-level hints did not move it. One sentence did.
