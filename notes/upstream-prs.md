# Upstream PR candidates

What we have found in the benchmark that belongs upstream, with the evidence and what is
blocking each. Two upstream repos: the harness, `SprocketLab/slop-code-bench` (our checkout
in `slop-code-bench/`, with `patches/` applied), and the problem set,
`gabeorlanski/scb-problems` (cached at `~/.cache/scbench/problems`, v1.0 commit 4d38d30;
patches in `patches/scb-problems/`, applied to the cache by `install.py`).

## Problem set: last checkpoints that drop the earlier tests

Some checkpoints set `include_prior_tests: false`, so their score never runs the earlier
checkpoints' tests and a run carrying misses looks strict for free. The upstream README
says tests for checkpoint N assume all prior checkpoints still pass. For each such
checkpoint we evaluated the upstream reference solution (`solutions/checkpoint_N`) with the
flag on (`bin/scb eval-snapshot` against a patched copy, 2026-09-08). Where the reference
passes every earlier test the flag is an omission; where it fails some, either the flag is
deliberate or the reference solution is wrong, and a PR needs the author's answer first.

| problem | checkpoints with the flag off | reference solution with prior tests on | status |
|---|---|---|---|
| mvvault | 6 (of 6) | 185/185 regression, own tests 42/42 | **ready**: `patches/scb-problems/mvvault-checkpoint-6-prior-tests.patch`, evidence in its preamble; applied to our cache, and every mvvault run's checkpoint 6 re-scored with `bin/reeval` (see `notes/mvvault-runs.md`) |
| l2m | 2, 3, 4, 5 (of 5) | ckpt 2 52/52; ckpts 3-5 each fail the same five checkpoint-1 tests: `test_list_convert[enum_in_itemize, itemize_in_enum, enum_in_itemize_start, formatting_comments, itemize_in_started_enum]` | blocked: checkpoint 3 changes nested-list conversion, so the checkpoint-1 expectations may be superseded on purpose; ask upstream whether those five should be updated or the flag is intended |
| meshctl | 6, 7, 8 (of 8) | each fails one checkpoint-1 test, `test_runtime_zero_version`, everything else passes (266/267, 306/307, 348/349) | blocked on one test: probably a superseded expectation about a zero runtime version; worth asking, since 8 checkpoints of regressions are otherwise clean |
| dynamic_config_service_api | 3, 4 (of 4) | ckpt 4: core 81/81 but regression 113/169, the failures being numbered stateful sequences from the earlier files (create, list, activate, resolve); ckpt 3: core 12/12, functionality 34/34, error 30/30, regression 41/93, the same shape | deliberate: the test files assume a fresh server, so running them together breaks the sequences; not a config omission |
| execution_server | 6 (of 6) | own tests 34/34, regression 62/221: numbered sequence tests from the earlier files fail (continue-on-error hit/miss and the like) | deliberate: like dynamic_config, the earlier files are stateful sequences against one server; nothing to file |
| metric_transform_lang | 5 (of 5) | own tests 26/26, regression 74/274: the reference solution fails 200 earlier tests across every checkpoint-1 to -4 file (cli format, core, errors, expressions, windows) | deliberate: checkpoint 5 redefines the language, so the earlier tests no longer apply; nothing to file |

Verdict (2026-09-08): mvvault is the only omission; the other five drop the earlier tests
because their reference solutions would fail them (superseded expectations on l2m and
meshctl, stateful test sequences on dynamic_config and execution_server, a redesign on
metric_transform). The mvvault PR stands alone. To repeat the check: copy the problem, flip
the flag, `bin/scb eval-snapshot` the reference solution as that checkpoint with
SCBENCH_PROBLEMS_PATH at the copy (the session's `check-prior.sh` loop, 2026-09-08).

## Problem set: xjq's reference prints lxml reprs for mixed result sets

`solutions/checkpoint_5/xjq.py` takes the XML branch only when every result is an element;
a set that mixes text nodes and elements (`//name/text()|//city`) goes down the text path,
where each item is `str()`-ed, so the element prints as `<Element city at 0x7f...>`. The
hidden test for it (test_redundant_text_extraction_mixed_pipe_paths, checkpoint 5) knows:
it regex-normalizes element addresses before comparing. Worth a PR that renders such items as
their string value and drops the normalization, or at least an issue; found 2026-09-09 while
drafting `specs/drafts/xjq-04-mixed-results-as-text.patch`.

## Problem set: file_merger's fixtures contradict the spec's own dialect words

Found by the 2026-09-09 review (`notes/file_merger-misses.md`). The checkpoint-2 TSV fixtures
are written by `csv.DictWriter`, so their lines end in `\r\n` while the spec says TSV has
`\n` line endings; nine hidden cases fail for any reader that takes the spec at its word and
strips `\n`. The checkpoint-4 CSV fixtures escape the quotes inside JSON cells with
backslashes (`"{\"name\":\"ok\"}"`) while the spec says escaping is by doubling; the
reference solution sniffs for `\"` and switches escape characters. Either the fixtures should
follow the spec (write TSV with `lineterminator="\n"`, write CSV by doubling) or the spec
should say what the fixtures do; our `specs/file_merger/v1` patches 01 and 03 take the second
road for our runs. Two PRs' worth, both small.

## Problem set: file_merger's `timestamp_microseconds` fixture tests nothing

Found 2026-09-20 while chasing a sub-second miss (`notes/file_merger-runs.md`, min13 on v6,
repeat). `tests/data/checkpoint_1/hidden/timestamp_microseconds.yaml` writes its CSV input and
its expected `output.csv` as single-quoted scalars spread over four lines. YAML folds those
line breaks into spaces, so both load as one line, `id,event_time 1,2024-… 2,… 3,…`: a header
and no rows. Every run we have passes it, 24 of 24, including one whose output drops the
microseconds (checked by running that snapshot on the intended rows: it prints
`2024-07-01T12:00:00Z` three times). The intended rows are the only place the suite would
test `.999999+00:00`. The fix is a block scalar (`content: |-`) on both strings, as
`checkpoint_4/hidden/nested_timestamp_microseconds.yaml` already has. One other fixture has
the same shape, `checkpoint_3/spec_errors/invalid_bytes_zero.yaml`, where only the exit code
is checked. A scan of every problem's fixtures in the cache found no others. One small PR.
Blocker: none; not opened yet.

## Problem set: mvvault's v1 tests only reroute `urllib.request.urlopen`

The spec fixes a v1 vault's source URL at `https://media.example.com/channel/<source_id>`, a
host that does not resolve, and says nothing about which HTTP client to use. The tests get a
v1 sync to the mock platform through `legacy_source_env` (`tests/conftest.py`): it writes a
`sitecustomize.py` that replaces `urllib.request.urlopen` with a wrapper that rewrites that
prefix to the mock's base URL, and puts it on `PYTHONPATH`. The reference solution calls
`urlopen`, so it passes. A solution that fetches with `requests` or `httpx`, or with urllib's
own `build_opener().open()`, never goes through the patch. It asks DNS for media.example.com
and exits 1.

Evidence: three of our mvvault runs fetched with `requests` alone, and each lost the same
seven tests to it and to nothing else: five at checkpoint 2
(`test_sync_v1_auto_migrates_and_fetches_via_derived_source`, `…_updates_existing_entry_after_auto_migration`,
`…_adds_new_entries_in_v3_shape`, `…_backup_preserves_original_v1_bytes`,
`test_sync_second_run_after_v1_auto_migration_has_no_re_migration_artifacts`),
`test_sync_v1_download_url` at 3 and `test_sync_links` at 4, each with
`HTTPSConnectionPool(host='media.example.com') … NameResolutionError` on stderr. The runs:
sonnet-4.6 just-solve (`dev6/…/20260829T1910`, 206/227), opus-5 just-solve
(`spectest/…just-solve/20260915T0940`, 214/227) and opus-5 min13-ABDJKMNT
(`…min13-ABDJKMNT/20260918T1850`, 215/227, found 2026-09-18). Add seven and they read 213,
221 and 222, level with the urllib runs of the same prompts. The 2026-09-15 ledger entry
listed the 214's misses without a cause. The fixture is used by about a dozen tests across
checkpoints 2, 3 and 4.

Fixes, smallest first: say in the spec that fetching uses the standard library's
`urllib.request`; or have the spec take the v1 base URL from an environment variable the
tests already set (`MVVAULT_LEGACY_SOURCE_BASE_URL`), which works for any client; or make the
patch cover `requests` and `httpx` too, which only moves the line. Not drafted; an issue
first, since the second fix changes the spec's contract. No patch in `patches/scb-problems/`,
and our runs are scored as the tests stand.

## Harness: patches we carry (all in `patches/`, applied to the checkout)

Listed in `README.md` with what each fixes: stream-parser string message; stop-after-
checkpoint; agent death detection and prompt context variables; resume invalidates
infra-failed checkpoints; container init and timeout kill; retry keeps every attempt's
transcript. Each is PR-shaped as it stands. Two have branches in `slop-code-bench/`:

- Stream-parser string message. **Landed upstream 2026-09-18**: #23 (`c2a53b4`) carries both
  commits from #35 (`8c58ef8` test, `9463b69` fix; the test class on main matches our branch
  line for line), #34 is closed, and we closed #35 as moot. Once the checkout moves to upstream
  main, `patches/claude-code-stream-parser-string-message.patch` can go. History: filed as
  issue #34 and draft PR #35 (2026-09-11, from the fork `robo-carver/slop-code-bench`, remote
  `fork`; the token has no push to SprocketLab). Branch `claude-2.1.2xx-compatibility` has the
  test first, then the fix. Claude Code 2.1.251 streams a `system` / `permission_denied` event
  when its safety check blocks a Bash command such as `cd /tmp/x && rm -rf *`, and that event's
  `message` is a string. Three saved lines show it: dev6-opus5 file_merger ckpt 4 and sith ckpt
  4, dev6-fable51 file_merger ckpt 2. Replaying one through unpatched `_run()` gives the
  2026-08-30 traceback. A live probe reproduces it on demand
  (`notes/evidence/permission-denied-probe-2026-09-10/`). Under the harness launch, the same
  prompt gets the event from 2.1.251, and unpatched `_run()` crashes on it. 2.1.44 streams no
  such event in bypassPermissions or default mode, and its `cli.js` has no such event type.
- A crashed checkpoint's `stdout.jsonl`. Filed as issue #36 and PR #37 (2026-09-18, marked
  ready for review the same day, from the fork, the same route as #34 / #35; #34 had promised
  it as a follow-up). Branch `claude-code-stdout-keeps-stream`, off main, has the test first
  (`a736cb8`), then the fix (`3d2ac94`); the single commit it was split from is kept locally as
  `backup/stdout-keeps-stream-single` (`c86baf6`). The issue text lives only on GitHub; the
  local draft was deleted once #36 was posted. Rebased 2026-09-18 onto upstream main `c2a53b4`
  (#23 had appended tests to the same file; both sets kept, 69 pass, the test commit alone
  still fails 2). Repro numbers, checked 2026-09-18 against upstream main (`06b5c06`):
  `TestStreamTranscriptArtifacts` fails 2 of 2 on main and on the test commit, and passes on
  the branch. No saved run shows the symptom any more (the first Opus 5 run directory is gone),
  so the unit test is the only evidence. Since 2026-09-18 the fix also keeps every attempt's
  stderr (`_stderr_lines`, filled from each finished process's result) and removes
  `final_result`, whose only remaining use was `stderr.log`; stderr from a process that crashes
  `_run()` mid-stream is still lost, because `stream_cli_command` only hands stderr over in the
  finished result. One behavior change the PR flags: a process that prints nothing to a stream
  now writes no file for it, where main writes an empty one. Issue #36 covers the stderr half
  too. Upstream writes the file from `final_result`, which only a finished `_run()` sets and
  nothing clears, so a checkpoint whose `_run()` raises saves the previous checkpoint's stdout
  and stderr. That is how the string-message cause stayed hidden for 12 days. The branch keeps
  each stdout line as `_run()` parses it, so a crash leaves its partial stream and a retry
  appends to the attempt before it. With the stderr half added it covers all of the
  retry-transcript patch, which can go once this lands.

Findings without a patch yet:

- The OAuth token lands in every `infer.log`. `_build_exec_command()`
  (`execution/docker_runtime/streaming.py`) logs "Built docker exec command" with the raw
  `args` list, and that list carries `--env CLAUDE_CODE_OAUTH_TOKEN=<token>` (and the same
  for any `type: env_var` provider). `mask_sensitive_values()` never sees it because the
  masking runs over env dicts, not argv. Verified 2026-09-17: 136 log files under
  `outputs/` hold the live token, one per checkpoint start, both on the container create
  path and on every exec. Nothing in git, since `outputs/` is ignored, but a shared run
  directory or a tarball ships the credential. File as an issue first, with the fix
  proposed: build a redacted copy of `args` for the log line, masking the value of any
  `--env KEY=VALUE` whose key `mask_sensitive_values` would mask (the same keyword list:
  token, key, secret, password, credential), and drop `verbose=True` on that line. The
  `containers.create(environment=...)` path has no log line of its own, so only the exec
  builder needs the copy. A test: build one exec command with a token in the env and
  assert the captured log record has no token in it.
- `retry()` resets the usage tracker, so a checkpoint that timed out and continued
  under-reports its cost (v7 datagate ckpt 6 recorded $3 of roughly $15).
- A collection pass that fails (uv exit 2 during a network blip) marks the checkpoint
  `infrastructure_failure` even when the test run that follows collects and scores every
  test; we clear the flag by hand when the evaluation is complete (just-solve v2 ckpt 4,
  min11 mvvault ckpt 4, both 2026-09-07/08). A better rule: infra failure only when the
  final run's collected count falls short.
- `SCBENCH_PROBLEMS_PATH` (a flat directory of problems that overrides the cache) is
  undocumented upstream; we depend on it for spec versions.

## Agent config

Monitor events never reach a `claude -p` session, so an agent that arms Monitor polls with
no-op turns ($103 checkpoint, `notes/xjq-runs.md`). Our fix is `disallowed_tools: [Monitor]`
in the agent config; upstream could default it. Related: `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`
is what keeps background sub-agents alive past the parent's turn (README of the agent config).

## Harness: CITATION.cff fails schema validation

`CITATION.cff` sets top-level `type: article`. CFF 1.2.0 allows only `software` or `dataset`
there, so `uvx cffconvert@2.0.0 --validate` in the checkout fails on `instance['type']: 'article'`.
Still so on upstream main c2a53b4 (2026-09-18); the line came in with 6e5a5e9 (2026-03-27). GitHub does show
its "Cite this repository" button for the repo, and we have not checked what the button
exports. The tools that validate first are the risk: cffconvert, and Zenodo when it reads the
file at release time. The fix keeps everything they wrote. Top level becomes `type: software`
with the repo URL, and the paper's fields (authors, title, arXiv URL, the Zenodo DOI if it is
the paper's) move under `preferred-citation:` with `type: article`, which is the CFF way to say
"cite the paper, not the code". Found 2026-09-19 while writing our own cff. Nothing blocks it:
a one-file PR via the fork, validated with cffconvert before and after.
