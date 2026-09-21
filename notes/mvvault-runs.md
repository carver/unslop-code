# Spectest run ledger (mvvault, Opus 5, Claude Code 2.1.251, thinking high)

Every mvvault run under `outputs/spectest/`, what changed, and how it ended, in the shape of
`spectest-datagate-runs.md`. Scores are all hidden tests passed / total at each checkpoint
(regressions included), from each checkpoint's `evaluation.json`; mvvault has six
checkpoints and reads the cached spec (v0). Per-checkpoint tables: `bin/summarize <run_dir>`.
The control is the dev6 sweep's just-solve run (`notes/dev6-opus5.md`).

Checkpoint 6 scores here include the earlier checkpoints' tests (227 in all). Upstream's
config runs only checkpoint 6's own 42 there, an omission patched in our cache since
2026-09-08 (`notes/upstream-prs.md`); the control's checkpoint 6 was re-scored on its
existing snapshot with `bin/reeval`, and every later run scores it that way natively.

| version | run dir | what changed | ckpt scores | ended |
|---|---|---|---|---|
| just-solve control | `../dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354` | benchmark's own prompt | 35/37, 64/67, 110/115, 149/155, 179/185, 221/227 | complete (dev6 sweep; checkpoint 6 re-scored 2026-09-08, upstream config gave 42/42); 6 misses, 0/6 strict, $12. Quality: erosion 0.472, verbosity 0.318, ast 0.243, cloned 0.044 |
| just-solve on v0, repeat | `…just-solve/20260915T0940` | benchmark's own prompt on the unpatched spec, a per-problem run; the second just-solve v0 replicate (the first is the dev6 control) | 35/37, 60/67, 106/115, 144/155, 174/185, 214/227 | complete 2026-09-15; 13 misses: the control's six plus a v1 auto-migration block of four at checkpoint 2 (re-migration artifacts, derived source, backup bytes, existing entry update), sync links at 4, and the two detail-route error cases at 5. Seven below the control. 0/6 strict, $15 (per checkpoint 1, 2, 2, 4, 2, 4), 52 min. Quality: erosion 0.569, verbosity 0.332, ast 0.287, cloned 0.045 |
| anti-slop | `…anti_slop/20260919T2330` | the benchmark's upstream anti_slop prompt as shipped (the paper's Anti-Slop arm; chunk T is its rule list), on v0; first of two | 35/37, 60/67, 106/115, 142/155, 172/185, 213/227 | complete 2026-09-20; 14 misses: five every opus-5 run shares, five more of the just-solve repeat's (the v1 auto-migration block at 2, sync links at 4), and four of its own (missing vault route and the two serve-named cases at 4, post create at 6); 0/6 strict, $15, 44 min. Quality: erosion 0.000, verbosity 0.315, ast 0.222, cloned 0.005; final checkpoint, implementation only (100% of LOC): ast 0.134, erosion 0.000, cloned 0.018 |
| anti-slop, repeat | `…anti_slop/20260920T1908` | same config as the first run; second of two | 35/37, 60/67, 106/115, 144/155, 172/185, 213/227 | complete 2026-09-20; 14 misses, 12 of them the first run's; it imports `requests` again, so the seven-test v1 block fell again; the nonexistent-vault redirect pair at 5 is new and the first run's serve-named pair passed; no tests written again; 0/6 strict, $19, 51 min, overlapped by the specpatch channel, so the minutes are not comparable. Quality: erosion 0.000, verbosity 0.318, ast 0.213, cloned 0.028; final checkpoint, implementation only (100% of LOC): ast 0.146, erosion 0.000, cloned 0.028 |
| min11-ABDFJKMN | `…min11-ABDFJKMN/20260907T1659` | the 468-word min11 subset (twice strict on datagate v2); first of two | 35/37, 65/67, 112/115, 150/155, 180/185, 222/227 | complete 2026-09-08; 5 misses, four shared with the control (the two checkpoint-1 sync rejections, missing tracked field and wrong field type; skip-downloaded candidate; serve on a custom address) and one its own (the missing-vault route error from checkpoint 4); the control's two sync-v1 misses passed. 0/6 strict, $36 (per checkpoint 4, 6, 6, 8, 5, 6), 152 min of agent time; checkpoint 4 hit the spurious infra flag (two collection passes failed in a network blip, evaluation complete at 150/155; flag cleared by hand, backup beside it) and the run resumed from 5 as job 89. 80 registry entries all scored, Risk 0-55 (top: digest output shape 55, a static field whose source value changes 45; a source response missing a category 35). Quality: erosion 0.059, verbosity 0.179, ast 0.067, cloned 0.083 |
| min12-ABDJKMN | `…min12-ABDJKMN/20260914T2119` | the 444-word no-F prompt on v0, for the six-problem quality-uplift comparison; first of two | 35/37, 64/67, 111/115, 150/155, 180/185, 220/227 | complete 2026-09-15; 7 misses: five of the control's six (the two checkpoint-1 sync rejections, sync-v1 new entries in v3 shape, skip-downloaded candidate, serve on a custom address; the sync-v1 download URL passed) plus the test_migration_atomic pair at checkpoint 6, new (a 302 where the test expects 500 on a bad catalog). One below the control. 0/6 strict, $29 (per checkpoint 2, 4, 5, 7, 5, 5), 98 min. 80 entries, 78 scored, Risk 0-55 (digest layout 55, digest trailing line 50, media extension from Content-Type 45). Quality: erosion 0.046, verbosity 0.214, ast 0.080, cloned 0.111 |
| min12-ABDJKMN, repeat | `…min12-ABDJKMN/20260915T0327` | same config as the first run | 35/37, 65/67, 112/115, 151/155, 181/185, 223/227 | complete 2026-09-15; 4 misses, all the control's (the two checkpoint-1 sync rejections, skip-downloaded candidate, serve on a custom address); the first run's v3-shape and migration-atomic misses passed. Two above the control, one above min11, the best mvvault score. 0/6 strict, $24 (per checkpoint 2, 3, 4, 7, 4, 4), 95 min. Quality: erosion 0.074, verbosity 0.172, ast 0.076, cloned 0.082 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T1850` | min12-ABDJKMN plus chunk T, upstream's anti-slop rules as the whole Implement section; one sample run for the ast question | 35/37, 60/67, 106/115, 144/155, 174/185, 215/227 | complete 2026-09-18; 12 misses. Seven are one cause: the run fetched with `requests`, and the hidden tests reroute the v1 source URL by patching `urllib.request.urlopen`, so every v1-vault sync tried the real media.example.com (five at checkpoint 2, v1 download URL at 3, sync links at 4). Three are the ones every opus-5 run shares. Two more that min12-ABDJKMN passed but other runs have missed the same way: the missing-vault redirect carries `?missing=missing` (fable-5 just-solve, the 2026-09-07 min11 run), and the post page shows 1:30 where the test looks for 90 (both fable just-solve runs). 0/6 strict, $33, 140 min. Quality: erosion 0.007, verbosity 0.159, ast 0.048, cloned 0.075; implementation only, ast 0.132 against min12's 0.235 and 0.199 |
| min13-ABDJKMNT, repeat | `…min13-ABDJKMNT/20260919T1041` | same config as the first run; second of two | 35/37, 60/67, 106/115, 145/155, 175/185, 216/227 | complete 2026-09-19; 11 misses: the first run's twelve minus missing vault route at checkpoint 4, which passed; the two new-to-any-run misses of the first run (post create at 6) shrink to one; 0/6 strict, $24, 88 min. Quality: erosion 0.000, verbosity 0.135, ast 0.048, cloned 0.049; final checkpoint, implementation only (26% of LOC): ast 0.119, erosion 0.000, cloned 0.009 |
| min13-ABDJKMNT | `…min13-ABDJKMNT/20260918T1850` | min12 plus chunk T, the upstream anti-slop rule list (d902f32); first of the min13 pair, rejector next | 35/37, 60/67, 106/115, 144/155, 174/185, 215/227 | complete 2026-09-18; 12 misses: ten shared with the just-solve repeat (the checkpoint-1 pair, the five-test v1 auto-migration block at 2, skip-downloaded and download URL at 3, sync links at 4) plus two no other run missed (missing vault route at 4, post create at 6); serve custom addr passed, which every other opus-5 run missed. 0/6 strict, $33, 140 min. Quality: erosion 0.007, verbosity 0.159, ast 0.048, cloned 0.075 |
| min13-ABDJKMNT on v1 (strict) | `…min13-ABDJKMNT-specv1/20260920T1529` | min13 on spec v1 (six sentences) under bin/scb-strict, in the specpatch channel beside the main queue; first of two | 37/37, 67/67, 115/115, 155/155, 185/185, 227/227 | complete 2026-09-20; no misses, strict on every checkpoint, the first strict mvvault run of any prompt (best before: 223); urllib for every request; 6/6 strict, $25, 93 min, overlapped by main-queue jobs throughout, so the minutes are not comparable. Quality: erosion 0.000, verbosity 0.144, ast 0.038, cloned 0.067; final checkpoint, implementation only (27% of LOC): ast 0.103, erosion 0.000, cloned 0.007 |
| min13-ABDJKMNT on v1, repeat (halted at the last checkpoint) | `…min13-ABDJKMNT-specv1/20260920T1737` | same config as the first run, under bin/scb-strict in the specpatch channel; second of two | 37/37, 67/67, 115/115, 155/155, 185/185, 225/227 | complete 2026-09-20 (the halt came after checkpoint 6, the last); 2 misses, test_migration_atomic for a v1 and a v2 catalog: an annotation POST to a vault whose legacy entry lacks `width` answers 303 where the test wants 500; 5/6 strict, $28, 93 min, overlapped by the main queue, so the minutes are not comparable. Quality: erosion 0.000, verbosity 0.146, ast 0.058, cloned 0.056; final checkpoint, implementation only (28% of LOC): ast 0.154, erosion 0.000, cloned 0.007 |

## Test failure summaries

### just-solve control (dev6 sweep)

  - 221/227: the two checkpoint-1 sync rejections (a source entry missing a tracked field,
    one with a wrong field type), two sync-v1 cases (new entries in v3 shape, download URL),
    skip-downloaded candidate, serve on a custom address. Under upstream's config the last
    checkpoint hid all six.

### just-solve on v0, repeat (2026-09-15)

  - 214/227, seven below the control: the control's six plus a checkpoint-2 v1 auto-migration
    block of four, sync links and the detail-route error pair. Cell: 221 and 214 against
    min12's 220 and 223; erosion 0.472 and 0.569 against 0.046 and 0.074.

### anti-slop (the upstream anti_slop prompt, 2026-09-20)

  - 213/227, one under the just-solve repeat (214) and below min12's 220 and 223 and min13's
    215 and 216: the repeat's miss set plus four of its own at the serve and create routes.
    No tests at all and 1219 implementation lines (just-solve 1984, min12 1650, min13 1260
    per run); $15 and 44 min. Implementation only: erosion 0.000 (just-solve 0.456, min12
    0.171, min13 0.019), ast 0.134 (0.338, 0.216, 0.126), cloned 0.018 (0.032, 0.032, 0.012).
    Fourth problem where the rule list alone zeroes erosion; here it also lands the lowest
    score of the four prompts. First of two.
  - repeat (213): the same score on 12 shared misses of 14. `requests` again, so anti-slop is
    two for two on the client the tests cannot reroute, as min13 was; v1's urllib sentence is
    aimed at exactly this. Swapped: the nonexistent-vault redirect pair at checkpoint 5 lost,
    the serve-named pair won back. Pair 213 and 213 against min12's 220 and 223, min13's 215
    and 216, just-solve's 221 and 214. No tests in either run. Implementation only over the
    pair: erosion 0.000, ast 0.140, cloned 0.023 on 1322 lines per run against just-solve's
    0.456, 0.338, 0.032 on 1984. $19 and 51 min.

### min12-ABDJKMN (without F)

  - first run (220): one below the control. Five of its six misses are the control's; the
    download-URL case passed; the two migration-atomic cases at checkpoint 6 are new, a 302
    redirect where the test wants a 500. Erosion 0.046 against the control's 0.472. First of two.
  - repeat (223): the four misses every opus-5 run shares and nothing else; the first run's
    three extras (v3-shape, the migration pair) passed. Pair: 220 and 223 against the control's
    221; erosion 0.046 and 0.074 against 0.472. On mvvault the prompt is quality, not score.

### min13-ABDJKMNT (min12 plus the anti-slop list)

  - 215/227, six below the min12 pair (220, 223) and level with the just-solve repeat (214).
    Its miss set is the repeat's minus serve custom addr and the detail-route pair, plus two
    no other run missed: missing vault route at checkpoint 4 and post create at 6. Erosion
    0.007, the lowest of any mvvault run (min12 0.046 and 0.074); ast 0.048 against 0.078.
    $33 and 140 min against min12's $27 and 96. One run: whether the score is chunk T or
    noise needs the rejector run and a repeat.

### min13-ABDJKMNT (min12-ABDJKMN plus the anti-slop chunk)

  - one run (215): eight below the min12 repeat, and seven of the eight are not about the spec.
    The implementation imported `requests`; both min12 runs used urllib. The just-solve repeat (214)
    and the sonnet-4.6 control lost the same seven tests the same way; see `notes/upstream-prs.md`. The tests' `legacy_source_env`
    fixture reroutes `https://media.example.com/channel/…` by patching `urllib.request.urlopen`
    through a sitecustomize, so with `requests` each v1-vault sync went to the real host and exited 1.
    Counting those as passes gives 222, level with min12's 220 and 223.
  - the other two are misses against the min12 pair, not new ones: `test_missing_vault_route` got
    `/?missing=missing` where the test wants the bare root, as fable-5's just-solve run and the
    min11 run of 2026-09-07 (`…/20260907T1659`) did; `test_post_create` looks for `90` on a page
    that prints `1:30`, as both fable just-solve runs' pages did. Found with `bin/miss-signatures`,
    which matches the redirect by signature; the post-page failures differ in page text, so that
    one took a grep.
  - the question the run was for: implementation-only ast is 0.132, against 0.235 and 0.199 for
    the two min12 runs and 0.338 for just-solve. Implementation erosion 0.036 against 0.218 and
    0.125. The implementation is 1457 lines against 1590 and 1711. One run.

  - repeat (216): the first run's misses minus missing vault route, so one better. Pair: 215
    and 216 against min12's 220 and 223 and just-solve's 221 and 214; the ten shared misses
    are the just-solve repeat's set, so min13 sits at the bare prompt's weaker toss on this
    problem. Implementation only over the pair: erosion 0.019 against min12's 0.171, ast 0.126
    against 0.216, cloned 0.012 against 0.032, on 1260 implementation lines per run against
    1650. $24 and 88 min against min12's $27 and 96.

### min11-ABDFJKMN

  - first run (222): one better than the control. The two sync rejections and two of the
    later misses are the control's; the sync-v1 pair passed; the missing-vault route error
    is new. Erosion 0.059 against the control's 0.472.

## Spec v1 (2026-09-20)

Six sentences, the user's wording (88f31a1), no judge run; the misses they answer are grouped in
`notes/mvvault-misses.md` and each patch's preamble carries its evidence.

  - `01`, checkpoint 1: the fetch-failure row's Required Detail becomes "Message includes `Source
    metadata fetch failure`". 0 of 11 runs passed the two tests it answers.
  - `02`, checkpoint 1: the source request is "made with `urllib.request`". Not a reading: the
    tests reroute the v1 source host by patching `urllib.request.urlopen`, and seven tests fell
    together in the four runs that imported `requests`. The draft's second row, in checkpoint 3's
    Download Rules, was cut; if a v1 run downloads with another client, try it.
  - `03`, checkpoint 3: "A file matches if the name contains entry `id`, apart from partial
    downloads". The spec says so itself, a checkpoint late (checkpoint_4.md:70).
  - `04`, checkpoint 4: "the browser URL uses this host as given". Kept although opening `0.0.0.0`
    is the worse program: the benchmark's mistake, so the agent should not pay for it.
  - `05`, checkpoint 2: entries `sync` creates are "Written in v3 shape, with `annotations` as `[]`".
  - `07`, checkpoint 6: a rendered annotation shows "each `timecode` as raw seconds".
  - Dropped: `06`, a missing vault redirects to `/` with no query string. The spec already says
    "Redirect to `/`"; the runs that failed it argued past those words.

First run: min13-ABDJKMNT under bin/scb-strict, in the `specpatch` channel beside the main queue
(`bin/queue add-strict --group specpatch`), so its minutes overlap other jobs and are not
comparable; its `window_usage.jsonl` marks the shared checkpoints. The registry is the thing to
read: whether the six sentences settle their questions, and whether `04` draws pushback.

First run on v1 (job 261, 2026-09-20): 227/227, all six checkpoints strict, from 215 and 216 on
v0. Sentence by sentence, from the run's registry (66 entries) and code:

  - `01` held: both rejection tests pass, and T11 reads the row as intended, "The row is named
    'Source metadata fetch failure' and says malformed entries are *included* in it".
  - `02` held with the checkpoint-3 row cut: `urllib.request.urlopen` at both request sites,
    metadata and downloads, and no `requests` import; the seven-test block passed. No entry
    questions it.
  - `03` held: test_skip_downloaded_candidate passes, and the question moved on, as file_merger's
    did: T28 "What counts as a partial-download artifact", Risk 25, quotes "apart from partial
    downloads" and asks only which suffixes count, choosing a family (`.part`, `.partial`, `.tmp`,
    `.download`, `.crdownload`). Untested either way.
  - `04` held with no pushback: no entry mentions the host, and the code has no special case for
    `0.0.0.0`.
  - `05` and `07` held; no entry questions either.

One strict run. The user's bar is twice: job 262 is the repeat, under bin/scb-strict in the
specpatch channel. Queued behind it at the user's call, each `--after 262` so none runs unless
the repeat is strict too: just-solve on v1 twice (263, 264) and anti-slop twice (265, 266),
plain `bin/queue add` in the main queue, after file_merger's v7 pairs and ahead of the test-set
batch. No min12 pair, the user's call (267 and 268 were queued and removed unrun), so on the
grid mvvault's patched cells are just-solve, anti-slop and spectest+antislop.

Repeat on v1 (job 262, 2026-09-20): 225/227, strict through checkpoint 5 and two misses at 6, so
v1 is strict once, not twice, and jobs 263 to 266 (the just-solve and anti-slop pairs, `--after
262`) failed unrun as designed. All six sentences held again. The two misses are one bug, not a
reading: test_migration_atomic posts an annotation to a v1 and a v2 vault whose one entry lacks
`width` and wants HTTP 500 with the catalog untouched (checkpoint_6.md:135, "Migration failure
during auto-migration | HTTP `500`"). The run's registry chose the strict side twice: T20,
Risk 30, "A legacy entry must satisfy its documented schema: the four static fields", and T68
keeps 500 for "failures raised while converting a catalog whose version was recognized". Its
viewer does not do what they say: `viewer/edits.py` `_migrated` calls `upgrade_catalog` and
answers 500 only if that raises, and the schema check lives in the loader the `migrate` command
runs afterwards, so the malformed entry is converted, annotated and redirected (303). The first
v1 run passed the pair; how its viewer path validates was not read. min12's first v0 run and two just-solve runs of other
models failed the same pair (10 pass, 3 fail before this run). The agent's bug, so no sentence
by the user's rule; if one is wanted, line 135 could name the case: "Migration failure during
auto-migration, malformed v1 or v2 entry data included".

Why the run's own tests did not catch it (read 2026-09-20). Its tests are written per spec phrase,
and the phrase "Migration failure during auto-migration | HTTP `500`" has two, in
`tests/test_annotation_errors.py`: a v1 catalog with no `source_id`, and an entry whose `views`
is the string "many". Both break the conversion itself, so `upgrade_catalog` raises and the
viewer answers 500. The hidden test's defect, a missing `width`, does not break the conversion:
run against the snapshot, `upgrade_catalog` succeeds on it, and on `width="wide"` too. Those
defects are caught only by the schema check in the loader, which the `migrate` command runs and
the viewer path does not. The phrase "Malformed v1 or v2 entry data" has its tests as well
(`tests/test_version_errors.py`: a non-epoch key, a non-ISO key, a mistyped static field, an
entry that is not an object), every one through `run_cli("migrate", …)`. So each phrase was tested
through the path its own checkpoint introduced, with defects that path rejects, and no test
carried checkpoint 2's malformed entries to checkpoint 6's route. The checkpoint-6 agent sees only
checkpoint 6's spec, where "migration failure" is not defined, and T68 defined it as a failure
"raised while converting". A phrase-per-test suite checks that each sentence holds somewhere; it
does not check that one rule holds on every path that reaches it.

Baselines on v1, queued 2026-09-20 at the user's call: the repeat's two misses are the agent's
mistake, so v1 stands as the patched spec. anti-slop twice (jobs 273, 274), just-solve twice (275,
276) and min12-ABDJKMN twice (277, 278), plain `bin/queue add` with no dependency, in the main
queue ahead of the test-set batch. The min12 pair is there for one question: whether it is more
or less likely than min13 to miss test_migration_atomic (min12's first v0 run missed it, its
repeat did not). Its runs also fill spectest's patched cell for mvvault on the grid.

