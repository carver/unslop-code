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

## Harness: patches we carry (all in `patches/`, applied to the checkout)

Listed in `README.md` with what each fixes: stream-parser string message; stop-after-
checkpoint; agent death detection and prompt context variables; resume invalidates
infra-failed checkpoints; container init and timeout kill; retry keeps every attempt's
transcript. Each is PR-shaped as it stands. Two have branches in `slop-code-bench/`:

- Stream-parser string message. Branch `claude-2.1.2xx-compatibility` has the fix and a
  test. Claude Code 2.1.251 streams a `system` / `permission_denied` event when its safety
  check blocks a Bash command such as `cd /tmp/x && rm -rf *`, and that event's `message` is
  a string. Three saved lines show it: dev6-opus5 file_merger ckpt 4 and sith ckpt 4,
  dev6-fable51 file_merger ckpt 2. Replaying one through unpatched `_run()` gives the
  2026-08-30 traceback. The 2.1.44 CLI has no such event.
- A crashed checkpoint's `stdout.jsonl`. Branch `claude-code-stdout-keeps-stream`, off main.
  Upstream writes the file from `final_result`, which only a finished `_run()` sets and
  nothing clears, so a checkpoint whose `_run()` raises saves the previous checkpoint's
  stdout and stderr. That is how the string-message cause stayed hidden for 12 days. The
  branch keeps each stdout line as `_run()` parses it, so a crash leaves its partial stream
  and a retry appends to the attempt before it. It does the stdout half of the
  retry-transcript patch; once it lands, that patch only needs to cover stderr.

Findings without a patch yet:

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
