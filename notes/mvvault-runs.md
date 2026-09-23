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
| anti-slop on v1 | `…anti_slop-specv1/20260921T0531` | the upstream anti_slop prompt on spec v1, a baseline for the grid's patched cell; first of two | 37/37, 67/67, 115/115, 154/155, 180/185, 222/227 | complete 2026-09-21; 5 misses: the missing-vault redirect carries `?missing=`, the reading draft 06 would have settled (one test at 4), the nonexistent-vault landing page lacks "not found" on the detail and static routes (two at 5), and a literal `../..` in a static route is redirected, 303, where the tests want 403 or 404 (two at 5); urllib throughout, so the seven-test v1 block passed; test_migration_atomic passed; 3/6 strict, $22, 94 min. Quality: erosion 0.018, verbosity 0.176, ast 0.080, cloned 0.031; final checkpoint, implementation only (39% of LOC): ast 0.142, erosion 0.036, cloned 0.000 |
| anti-slop on v1, repeat | `…anti_slop-specv1/20260921T0719` | same config as the first run; second of two | 37/37, 67/67, 115/115, 154/155, 182/185, 224/227 | complete 2026-09-21; 3 misses, all on the missing-vault redirect: `?missing=` in the Location (one test at 4) and a landing notice that reads "No vault named 'x' here." where the tests look for the words "not found" (two at 5); the first run's two path-traversal misses passed; urllib throughout; test_migration_atomic passed; 3/6 strict, $25, 90 min. Quality: erosion 0.000, verbosity 0.182, ast 0.099, cloned 0.014; final checkpoint, implementation only (50% of LOC): ast 0.138, erosion 0.000, cloned 0.010 |
| just-solve on v1 | `…just-solve-specv1/20260921T0904` | benchmark's own prompt on spec v1, a baseline for the grid's patched cell; first of two | 37/37, 66/67, 114/115, 154/155, 184/185, 226/227 | complete 2026-09-21; 1 miss, test_sync_v2_absent_entry_gets_removed_true_after_migration from checkpoint 2 on: the run gives the migration and the sync that triggered it one timestamp, so the sync's `true` overwrites the migration's `false` and the history reads [True] where the test wants [False, True]; the agent's bug, new to opus-5 (15 pass, 1 fail before, the fail sonnet's just-solve); urllib throughout; the missing-vault redirect and test_migration_atomic passed; no tests written; 1/6 strict, $16, 49 min. Quality: erosion 0.378, verbosity 0.382, ast 0.352, cloned 0.026; final checkpoint, implementation only (100% of LOC): ast 0.271, erosion 0.247, cloned 0.037 |
| just-solve on v1, repeat | `…just-solve-specv1/20260921T1008` | same config as the first run; second of two | 37/37, 67/67, 113/115, 153/155, 181/185, 223/227 | complete 2026-09-21; 4 misses, none traced (a baseline): the two digest grouping tests from checkpoint 3 (test_digest_v1_entries_group, test_digest_v2_groups) and the two literal `../..` path-traversal cases at checkpoint 5, the same failure as anti-slop's first v1 run; the first run's one miss passed; test_migration_atomic passed; 2/6 strict, $14, 44 min. Quality: erosion 0.289, verbosity 0.402, ast 0.359, cloned 0.036; final checkpoint, implementation only (100% of LOC): ast 0.278, erosion 0.306, cloned 0.037 |
| min12-ABDJKMN on v1 | `…min12-ABDJKMN-specv1/20260921T1106` | min12 on spec v1, for the grid's patched cell and the user's question whether min12 misses test_migration_atomic more or less than min13; first of two | 37/37, 67/67, 115/115, 154/155, 184/185, 224/227 | complete 2026-09-21; 3 misses, both readings the registry carries: test_missing_vault_route (T46, Risk 35, chose `/?missing=<name>` and wrote that a test asserting the bare `/` would fail; dropped draft `06`) and test_migration_atomic x2 (T15, Risk 40, "missing fields tolerated", so an entry without `width` migrates and the viewer answers 302 where the test wants 500); all six v1 sentences held; 3/6 strict, $25, 89 min. Quality: erosion 0.075, verbosity 0.200, ast 0.098, cloned 0.066; final checkpoint, implementation only (26% of LOC): ast 0.235, erosion 0.102, cloned 0.048 |
| min12-ABDJKMN on v1, repeat | `…min12-ABDJKMN-specv1/20260921T1251` | same config as the first run; second of two | 37/37, 67/67, 115/115, 155/155, 185/185, 227/227 | complete 2026-09-21; 0 misses; it asked the first run's two questions and chose the tests' side both times (T16, Risk 35, strict on malformed entry data; T42, Risk 25, a bare `/` with the name kept on the server); test_migration_atomic passed; 6/6 strict, $31, 114 min. Quality: erosion 0.063, verbosity 0.208, ast 0.077, cloned 0.108; final checkpoint, implementation only (22% of LOC): ast 0.227, erosion 0.215, cloned 0.040 |
| opus-5-5 min13-ABDJKMNT-specv1 | `…opus-5-5_2.1.280_high_min13-ABDJKMNT-specv1/20260923T0834` | the min13 v1 config on Opus 5.5 under Claude Code 2.1.280 (agent and model both changed); first of two | 37/37, 67/67, 115/115, 152/155, 182/185, 222/227 | complete 2026-09-23; 5 misses: three listing tests at 4 (the page lists entries in a `<table>`, the tests look for each entry's `<li>`) and test_migration_atomic's two cases at 6 (a reading: T18 chose the structural check, so an entry missing `width` migrates and redirects); 3/6 strict, $13, 64 min. Quality: erosion 0.020, verbosity 0.115, ast 0.047, cloned 0.032; final checkpoint, implementation only (25% of LOC): ast 0.109, erosion 0.066, cloned 0.015 |

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

### just-solve on v1 (2026-09-21)

  - 226/227, from 221 and 214 on v0, and the highest of the six just-solve runs on this problem
    (sonnet 206, fable 213 and 220). `urllib.request` at every request site, as v1 asks. It also
    sent the missing vault to a bare `/` and wrote "not found" on the landing page, the two
    places anti-slop lost on v1, with no v1 sentence about either. The one miss is its own: migration and the sync that triggers it
    share a timestamp, so `removed` reads [True] and not [False, True]. No tests and 3254
    implementation lines; $16 and 49 min. Implementation only: erosion 0.247, ast 0.271,
    cloned 0.037. First of two.
  - repeat (223): pair 226 and 223 against 221 and 214 on v0. Four misses, none shared with the
    first run: the two digest grouping tests at checkpoint 3 and the two literal `../..`
    path-traversal cases at checkpoint 5, which anti-slop's first v1 run also lost. Not traced;
    these runs only set the baseline. test_migration_atomic passed. No tests and 3460
    implementation lines; $14 and 44 min. Implementation only: erosion 0.306, ast 0.278, cloned
    0.037; the mean of the two runs is 0.277, 0.275, 0.037.

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
  - on v1 (224): from 220 and 223 on v0, level with anti-slop's 222 and 224 and under min13's 227
    and 225. Three misses and both are choices its registry made knowingly. T46, Risk 35, sent
    the missing vault to `/?missing=<name>` while noting that "a test asserting `Location == "/"`
    exactly would fail against the query string". T15, Risk 40, read "malformed v1 or v2 entry
    data" as wrong types only, "with missing fields tolerated", so test_migration_atomic's entry
    without `width` is migrated and redirected (302) where the test wants 500. $25 and 89 min.
    Implementation only (26% of lines): erosion 0.102, ast 0.235, cloned 0.048. First of two.
  - on v1, repeat (227): strict at all six checkpoints, so the pair is 224 and 227 against 220
    and 223 on v0, min13's 227 and 225, anti-slop's 222 and 224 and just-solve's 226 and 223.
    Same two questions, the other answers: T16, Risk 35, took the schema tables as the definition
    of well-formed, and T42, Risk 25, read "Redirect to `/`" as no query string and kept the
    name on the server. $31 and 114 min, the dearest run on v1. Implementation only (22% of
    lines): erosion 0.215, ast 0.227, cloned 0.040; the mean of the two runs is 0.159, 0.231, 0.044.

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

anti-slop on v1, first run (job 273, 2026-09-21): 222/227, from 213 and 213 on v0. Patch `02`
did what it was for: `urllib.request.urlopen` at both request sites and the seven-test v1 block
passed, where both v0 runs imported `requests` and lost it. It wrote tests this time (39% of
lines are implementation; the v0 runs wrote none). test_migration_atomic passed. The five misses:

  - test_missing_vault_route: the redirect goes to `/?missing=missing`. This is draft `06`, the
    one sentence dropped from v1 because the spec already says "Redirect to `/`". anti-slop has
    now taken the query-string road three runs of three; min13 took it once of four.
  - the nonexistent-vault pair at checkpoint 5 (detail and static routes): the landing page the
    redirect reaches does not say "not found". 13 pass, 2 fail before this run; anti-slop's v0
    repeat lost the same pair. Probably the same choice seen from the other side: the notice
    rides on a query parameter those routes do not set. Not traced further.
  - two path-traversal cases with a literal `../..`: 303 where the tests want 403 or 404. New:
    15 pass, 0 fail before this run for the encoded spelling of the same test. The path
    normalises to another vault's route and is handled as a missing vault. The agent's bug.

Three of the five sit on the missing-vault redirect, so draft `06` is worth a second look if
anti-slop's repeat does the same.

anti-slop on v1, repeat (job 274, 2026-09-21): 224/227, pair 222 and 224 against 213 and 213 on
v0 and min13's 227 and 225. Its three misses are one place in the spec, checkpoint_4.md:110,
"Redirect to `/`; landing page shows vault-not-found indication", read against the tests twice
over:

  - the Location carries `?missing=<name>` (test_missing_vault_route wants the bare root): four
    anti-slop runs of four now, min13 one of four. This is dropped draft `06`.
  - the notice itself. `pages.landing` prints "No vault named 'x' here."; test_missing_vault_route
    and the checkpoint-5 pair assert the words "not found" in the page (tests/test_checkpoint_4.py:450,
    test_checkpoint_5.py:608). "vault-not-found indication" names a condition, and the tests want
    it as a phrase, the same kind of miss as patch `01`'s "Source metadata fetch failure". The
    first run's checkpoint-5 pair was this too, not the query parameter as guessed in its entry
    above: its wording is "vault x does not exist".

So draft `06` comes back stronger than it left: "Redirect to `/` with no query string; the landing
page says the vault was `not found`". Pitched to the user and declined (2026-09-21): the spec
says "Redirect to `/`", an author may mean `/` literally without having to insist on it, and a
run that adds a query string has made the wrong call; that failure comes first and eclipses the
wording check. `06` stays out and v1 stands; these are the agent's misses. test_migration_atomic: passed in both anti-slop runs.

just-solve on v1, first run (job 275, 2026-09-21): 226/227, from 221 and 214 on v0. One miss,
test_sync_v2_absent_entry_gets_removed_true_after_migration, failing from checkpoint 2 to 6:
`removed` comes back as [True] where the test wants [False, True]. Traced in the snapshot:
`apply_migration_stamp` and `mark_removed` are handed the same stamp, "so migration and the
operation that triggered it agree on one timestamp" in the code's own words. Both writes land on
one key and the sync's `true` replaces the migration's `false`. checkpoint_2.md:164 asks for a
"single history entry with value `false`" from migration, and the sync's transition comes after
it, so this is the agent's bug and no reading of the spec. 15 pass, 1 fail before this run; the
one earlier fail is sonnet's just-solve, with the same assertion. The missing-vault redirect
passed (bare `/`, "not found" on the page) and so did test_migration_atomic. urllib throughout,
no tests written.

just-solve on v1, repeat (job 276, 2026-09-21): 223/227, pair 226 and 223 against 221 and 214 on
v0. A baseline, so the misses are named and not traced: test_digest_v1_entries_group and
test_digest_v2_groups from checkpoint 3 on, and the two literal `../..` path-traversal cases at
checkpoint 5 that anti-slop's first v1 run also failed. test_migration_atomic passed, so it has
passed in all four baseline runs on v1. The just-solve pair is in; min12's pair (277, 278) is next.

min12 on v1, first run (job 277, 2026-09-21): 224/227, from 220 and 223 on v0. All six v1 sentences
held. The three misses are two readings, and the run's registry has both:

  - test_missing_vault_route: T46, Risk 35, "What the vault-not-found redirect carries". It chose
    `/?missing=<name>` with a cookie fallback, reasoning that a test client keeps no cookies, and
    its Risk line names the assertion that then failed: "a test asserting `Location == "/"` exactly
    would fail against the query string". This is dropped draft `06`, declined twice; min12 joins
    anti-slop (four of four) and min13 (one of four) on the query-string road. Not re-pitched.
  - test_migration_atomic, both cases: T15, Risk 40, "What counts as 'malformed v1 or v2 entry
    data'" (checkpoint_2.md:158). It chose type validation "with missing fields tolerated (a v1
    entry lacking `preview` is migrated without it rather than rejected) ... not inventing a
    presence requirement the migration tables never state". The test's entry lacks `width` and
    wants HTTP 500; the run migrates it and redirects, 302. Its Risk text bet the other way, that
    the author is looser still. This is a reading, where min13's repeat on v1 was a bug: that run
    chose the strict side (T20, T68) and its viewer skipped the check.

The question gets asked. The three other registries read for it carry the same line at Risk 30 to
40 (min12 on v0: T15 at 30 and T14 at 40; min13's first v1 run: T19 at 30) and all three chose
strict; this run is the only one of the four to choose tolerant. On the user's question:
min12 has now missed test_migration_atomic in two runs of three (v0 first run through a cause not
read, this one through T15) and min13 in one of four (a bug). History: 15 pass, 4 fail.

min12 on v1, repeat (job 278, 2026-09-21): 227/227, all six checkpoints strict. The pair is 224 and
227. The run asked both of the first run's questions and chose the tests' side: T16, Risk 35, "How
strict 'malformed v1 or v2 entry data' is", strict because "the schema table is the definition of
well-formed"; T42, Risk 25, a bare `/` because "the spec says 'Redirect to `/`' without a query
string", with the vault's name kept on the server for the next landing render.
test_migration_atomic passed, so min12 stands at two misses in four runs and min13 at one in four.
That closes the v1 cell for all four prompts: just-solve 226 and 223, anti-slop 222 and 224, min12
224 and 227, min13 227 and 225. The grid rebuild that was waiting on this run is due.

min13 on v1 under Opus 5.5 (job 287, 2026-09-23, Claude Code 2.1.280): 222/227, 3/6 strict, $13 and
64 min, against the Opus 5 pair's 227 and 225. Two causes:
  - three checkpoint-4 listing tests (test_v1_downloaded_mark, test_v3_downloaded_mark,
    test_v3_removed_mark): the listing is a `<table>` with one `<tr>` per entry, and the tests' `_entry_row`
    wants the entry link inside an `<li>` ("Missing list item for …"). The spec's listing rules
    (checkpoint_4.md:63) name no markup, and no registry entry asks. Among the logged runs only
    the sonnet-4.6 control (just-solve v0) failed these three tests the same way. An unwritten test
    assumption, not a reading the spec offers; a candidate for notes/upstream-prs.md, not pitched.
  - test_migration_atomic, both cases: T18, Risk 25, "What counts as malformed v1/v2 data". It lists
    strict (every schema field present) and chooses structural, the v3 loader's checks, so the
    entry without `width` migrates and the POST redirects (303) where the test wants 500. Its Risk
    text names the alternative: "The author may also check the types of `width`/`height`". A
    reading, the tolerant side, as min12's first v1 run chose (T15). History (bin/test-history):
    16 pass, 5 fail for the v1 case, 15 and 6 for the v2 case.
Implementation only: ast 0.109, erosion 0.066, cloned 0.015 (Opus 5 pair: ast 0.103 and 0.154,
erosion 0.000 both). Agent and model both changed, so no model effect can be read off one run.
