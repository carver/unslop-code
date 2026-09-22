# Ambiguities

Spec: Part 1 — single task, schemes `greedy` / `sample` / `rejection`.
Each entry records a place where the spec admits more than one conforming
behavior, the reading chosen, and the risk that the author's reference
implementation reads it differently.

## T1. `meta` shape for a rejection row that passes on the first attempt

### Spec Text
> `meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt

### Alternatives
1. Shape follows the *attempt count*: a rejection row that passed on attempt 1
   emits a single metadata object (not a list); only rows with 2+ attempts emit
   a list.
2. Shape follows the *scheme*: every `rejection` row emits a list, of length 1
   when it passed immediately.

### Choice
Alternative 1. The sentence keys the singular form to "one-attempt rows", not
to the scheme, and keys the list form to "multiple attempts". The rejection
example in the spec that shows a list has 5 attempts, which is consistent with
both readings, so the defining clause is "one-attempt rows".

### Risk: 30
Author's likely different reading: always emit a list for `scheme: rejection`,
since that falls out of a `metas = []` accumulator that is never unwrapped.

## T2. `meta` for a row that fails after exhausting HTTP retries

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 total requests. After
> the third failure, treat that row as failed, emit `null` output for it, count
> it as failed in the summary, and continue.

### Alternatives
1. `meta` is `null` — no successful API response exists, so there is no
   metadata object to emit.
2. `meta` is a metadata object with `null` token/finish_reason fields and a
   real `latency_ms`.
3. `meta` is a list of one entry per failed HTTP attempt.

### Choice
Alternative 1. Every documented `meta` field (`prompt_tokens`,
`completion_tokens`, `finish_reason`, ...) is sourced from a response body that
never arrived; the spec only mandates `output: null` here, and `null` metadata
is the natural companion. For a rejection row that produced some successful
responses before the hard failure, the successful attempts' metadata is kept
(so `meta` is those entries, per T1's shape rule) rather than discarded.

### Risk: 45
Author's likely different reading: a metadata object with `null`/`0` token
fields, so that `meta` is never `null` and downstream readers can always index
it.

## T3. Does a hard HTTP failure abort a rejection row or advance to the next attempt?

### Spec Text
> After the third failure, treat that row as failed, emit `null` output for it,
> count it as failed in the summary, and continue.

### Alternatives
1. The row is abandoned immediately: no further rejection attempts are made,
   output is `null`, `passed` is `false`. "continue" means continue with the
   *other rows*.
2. The failed attempt is skipped and the remaining rejection attempts still
   run, so the row can still pass.

### Choice
Alternative 1. The sentence says "treat that row as failed" and "emit `null`
output for it" — both are row-level verdicts, not attempt-level ones. Reading 2
would contradict "emit `null` output" whenever a later attempt passed.

### Risk: 35
Author's likely different reading: keep attempting the remaining `n` budget,
treating the errored attempt as just another non-passing attempt.

## T4. `result.attempts` for a row that hit a hard HTTP failure

### Spec Text
> `result.attempts` is the number of logical generation attempts for that row:
> `1` for `greedy` and `sample`, `1..n` for `rejection`
>
> Retry requests count toward `total_api_calls`, but for `greedy` and `sample`
> rows they do not increase the logical `result.attempts` count.

### Alternatives
1. The attempt that died counts as a logical attempt: greedy/sample failures
   report `attempts: 1`; a rejection row that failed on its k-th attempt
   reports `attempts: k`.
2. Only attempts that produced a usable response count, so a greedy hard
   failure reports `attempts: 0`.

### Choice
Alternative 1. The spec fixes greedy/sample at exactly `1` with no failure
carve-out, and pins the rejection range at `1..n`; `0` is outside both ranges.

### Risk: 20
Author's likely different reading: `attempts: 0` when no response was ever
obtained.

## T5. What `rpm` means for pacing

### Spec Text
> Use the configured `rpm` as the server's approximate request capacity and keep
> enough work in flight to avoid an obviously sequential pipeline. Target at
> least 80% of the configured `rpm`.

### Alternatives
1. `rpm` sizes the concurrency window (requests kept in flight); no wall-clock
   throttle is applied, so measured `throughput_rpm` may exceed `rpm` when the
   server is faster than advertised.
2. `rpm` is a hard client-side rate limit enforced with a token bucket, capping
   measured throughput at `rpm`.

### Choice
Alternative 1. The spec calls `rpm` "the server's approximate request capacity"
(a property of the server, not a client budget), states the API "does not return
rate-limit errors", and sets only a *lower* bound (80%) on achieved throughput.
A hard client-side cap can only make the lower bound harder to reach. In-flight
work is capped at `max(8, rpm)` requests, bounded by the remaining work.

### Risk: 15
Author's likely different reading: a token-bucket limiter at exactly `rpm`, with
tests asserting `throughput_rpm <= rpm * 1.1`.

## T6. Default `temperature`, and whether `sample`/`rejection` may omit it

### Spec Text
> `sample`: `temperature` must be `> 0`
>
> ```yaml
>   generation:
>     scheme: "greedy"
>     temperature: 0.0
> ```

### Alternatives
1. `temperature` defaults to `0.0` (the value shown in the canonical config), so
   a `sample`/`rejection` config that omits it is invalid and exits `1`.
2. `temperature` defaults to something positive (e.g. `1.0`, the OpenAI
   default), so omitting it is valid for `sample`/`rejection`.

### Choice
Alternative 1. The only default visible anywhere in the spec is `0.0`, and the
validation rule is stated as an unconditional "must be `> 0`", which is only
meaningful as a check if the omitted case can fail it.

### Risk: 35
Author's likely different reading: default `1.0` for `sample`/`rejection` so the
scheme works without extra config.

## T7. `last_number`: sign, decimals, and thousands separators

### Spec Text
> `last_number`: use the last integer or decimal in the response

### Alternatives
1. Match `-?\d+(?:\.\d+)?`, allowing a leading minus, after removing thousands
   separators between digits (so `1,000` yields `1000`).
2. Match unsigned `\d+(?:\.\d+)?` only, treating `-` as punctuation and leaving
   commas as number terminators (so `1,000` yields `000`).

### Choice
Alternative 1. "integer" includes negative integers, and a grouped numeral like
`1,000` is a single number to any reader; yielding `000` is clearly not "the
last number" of the text.

### Risk: 40
Author's likely different reading: a bare `-?\d+\.?\d*` (or unsigned)
`re.findall` with no comma handling, making `1,000` extract as `000`.

## T8. `exact_match` comparison: string or numeric

### Spec Text
> `exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row

### Alternatives
1. Compare stripped strings, with a numeric fallback: if both sides parse as
   numbers, compare numerically (so `8.0` matches `8`).
2. Strict stripped-string equality only.

### Choice
Alternative 1. `exact_match` is paired with `last_number` extraction in the
spec's own example, where the extracted text is a numeral; a pure string compare
makes formatting differences ( `8` vs `8.0`, `1000` vs `1,000` ) fail an
otherwise correct answer. The fallback only ever turns `false` into `true` for
numerically equal values.

### Risk: 30
Author's likely different reading: plain `extracted == str(row[answer_field])`
after `.strip()`, with a fixture asserting `8.0` vs `8` is a failure.

## T9. `result.extracted_answer` for `contains` and `regex` evaluations

### Spec Text
> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output

### Alternatives
1. The configured `extract` method (defaulting to `full`) is applied to the
   response for every evaluation type, so `contains`/`regex` rows report that
   value.
2. `contains` reports the matched substring and `regex` reports the regex match
   (group 1 if the pattern has a group, else group 0); `null` when no match.
3. `null` for `contains`/`regex`, since only `exact_match` "extracts".

### Choice
Alternative 1. The spec explicitly limits `null` to "no evaluation or no
output", which rules out 3, and it defines `extract` as a property of the
evaluation block generally rather than of `exact_match` specifically. A single
`extracted = extract(response, method)` computed before the type switch is the
straightforward implementation.

### Risk: 40
Author's likely different reading: for `regex`, `extracted_answer` is the text
the pattern matched.

## T10. `regex` matching mode

### Spec Text
> `regex`: response text must match the configured `pattern`

### Alternatives
1. `re.search` — the pattern must occur somewhere in the response.
2. `re.match` / `re.fullmatch` — anchored at the start / over the whole text.

### Choice
Alternative 1. Responses are free-form multi-line model output, so an anchored
match would be unusable for the stated purpose; `search` also subsumes anchored
patterns that the config writes with explicit `^`/`$`.

### Risk: 20
Author's likely different reading: `re.match`, anchoring at the start of the
response.

## T11. When prompt/answer field validation happens

### Spec Text
> If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field.

### Alternatives
1. All rows are validated up front, before any API request is issued; the
   lowest-indexed offending row is reported and no output file is written.
2. Rows are validated lazily as they are processed, so some requests are sent
   (and possibly a partial output file written) before the exit.

### Choice
Alternative 1. Exit code `1` is defined as "configuration or input error", i.e.
a pre-flight class of failure, and the spec's example reports row `0` with no
mention of partial results. Up-front validation also makes the reported row
index deterministic under concurrency.

### Risk: 15
Author's likely different reading: same up-front validation; a lazy
implementation would report a nondeterministic row under concurrency.

## T12. Non-5xx HTTP error responses

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 total requests.

### Alternatives
1. Only `5xx` is retried; a `4xx` fails the row immediately (one API call).
2. Every non-2xx is retried up to 3 times.

### Choice
Alternative 1. The retry rule names `5xx` specifically; `4xx` responses are
client errors that will not change on replay.

### Risk: 25
Author's likely different reading: retry any non-2xx status, making a `4xx` row
cost 3 API calls.

## T13. `result.passed` for a hard-failed row when no evaluation is configured

### Spec Text
> if `evaluation` is omitted for `greedy` or `sample`, `result.passed` must be
> `null`
>
> `failed`: rows where `result.passed` is `false` or `output` is `null`

### Alternatives
1. `passed` stays `null` (the rule is unconditional); the row is still counted
   as failed in the summary via the `output is null` clause.
2. `passed` becomes `false` because the row failed.

### Choice
Alternative 1. The "must be `null`" rule has no exception for failures, and the
summary's `failed` definition explicitly includes an `output is null` clause,
which would be redundant if failures always set `passed: false`.

### Risk: 30
Author's likely different reading: `passed: false` on any hard failure,
regardless of evaluation configuration.

## T14. Exit code for CLI usage errors (missing/invalid flags)

### Spec Text
> Exit codes:
> - `0`: success
> - `1`: configuration or input error

### Alternatives
1. Usage errors exit `1`, since the spec enumerates only `0` and `1`.
2. Usage errors exit `2`, argparse's default.

### Choice
Alternative 1. The spec presents an exhaustive two-value exit-code contract, and
a missing `--config` is a configuration error by any reading. `argparse`'s
`error()` is overridden to exit `1`.

### Risk: 25
Author's likely different reading: plain argparse, exiting `2` on usage errors
(a test asserting "non-zero" passes under either).

## T15. Required config keys and their defaults

### Spec Text
> ```yaml
> task:
>   name: "gsm8k_solve"
>   api_url: "http://localhost:8000"
>   model: "gpt-4"
>   rpm: 60
> ```
> Invalid configuration exits with code `1` and a descriptive message on stderr.

### Alternatives
1. `api_url`, `model`, `prompt` (with at least `user`) and `output_field` are
   required (unless supplied by a CLI override); `rpm` defaults to `60`,
   `max_tokens` to `512`, `n` to `1`, `scheme` to `greedy`, `extract` to `full`,
   and `prompt.system` is optional (the system message is then omitted).
2. Everything defaults, so a nearly empty config still runs.

### Choice
Alternative 1. Values that cannot be invented (where to send the request, which
model, what to ask, what to name the output key) are required; values with a
canonical value in the spec's own example or an obvious identity default get
that default. The greedy example config omits `temperature` and `n`, so those
must default.

### Risk: 30
Author's likely different reading: a looser required set (e.g. `output_field`
defaulting to `"output"`), or `rpm`/`max_tokens` also required.

## T16. Rejection attempts: sequential or issued in parallel

### Spec Text
> `rejection`: `temperature` must be `> 0`; make up to `n` attempts and keep the
> first passing response

### Alternatives
1. Attempts for a row run sequentially, stopping at the first pass, so a row
   that passes on attempt 2 costs exactly 2 API calls.
2. All `n` attempts are launched at once and the first passing one is kept,
   costing `n` calls per row.

### Choice
Alternative 1. "up to `n` attempts" and the `1..n` range for `result.attempts`
both imply attempts are not spent once one passes; reading 2 would always report
`attempts: n`. Concurrency is obtained across rows instead.

### Risk: 10
Author's likely different reading: same sequential-per-row behavior.

## T17. `elapsed_seconds` / `throughput_rpm` when there are no API calls

### Spec Text
> `elapsed_seconds`: wall-clock time from first request to last response,
> rounded to 1 decimal place
>
> `throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to 1
> decimal place

### Alternatives
1. With zero requests (empty input), both are `0.0`; `throughput_rpm` is also
   `0.0` when the elapsed window rounds to zero, to avoid dividing by zero. The
   division uses the unrounded elapsed time.
2. Emit `null`, or divide by the rounded value.

### Choice
Alternative 1. `0.0` keeps the summary's types stable, and using the unrounded
elapsed time is the more accurate reading of the formula (the rounding
instruction attaches to the reported field).

### Risk: 20
Author's likely different reading: `throughput_rpm` computed from the rounded
`elapsed_seconds`, which differs on short runs.

---

Spec: Part 2 — multi-task configs, `letter` / `first_number` extraction, and
the `script` and `llm_judge` evaluation types. Entries T18 onward.

## T18. What counts as "the first uppercase answer choice A through D"

### Spec Text
> `letter`: extract the first uppercase answer choice `A` through `D`; accept
> forms such as `A`, `(A)`, `A)`, or `Answer: A`

### Alternatives
1. Only a *standalone* `A`-`D` counts: scan for `\b[A-D]\b`, so a capitalised
   word like `Berlin` or the `A` in `Answer:` is skipped and `"Berlin is
   wrong; the answer is B"` extracts `"B"`.
2. Any uppercase `A`-`D` character counts: a bare `re.search(r"[A-D]")`, so
   `"Berlin is wrong..."` extracts `"B"` from `Berlin` (same answer here, but
   `"Choose D or A"` after a word like `Correct` would differ) and
   `"Answer: C"` extracts `"A"` from `Answer`.

### Choice
Alternative 1. The spec lists `Answer: A` as an accepted *form*, which only
resolves to `A` under a word-boundary scan — reading 2 would extract the `A`
of `Answer` for every such response regardless of the real choice, making the
listed form meaningless. `(A)` and `A)` also both work under reading 1.

### Risk: 35
Author's likely different reading: a bare `re.search(r"[A-D]")` over the
response, which happens to produce the right letter for `Answer: A` and for the
spec's own `"The answer is B) Paris"` fixture and so can survive untested.

## T19. Number syntax for `first_number` (and its relation to `last_number`)

### Spec Text
> `first_number`: extract the first integer or decimal in the response

### Alternatives
1. Use exactly the Part 1 `last_number` scanner (see T7) — `-?\d+(?:\.\d+)?`
   after collapsing digit-group commas — and take the first match instead of
   the last.
2. Use a different, narrower scanner for `first_number` (for example unsigned
   integers only, since judge scores are 1-10).

### Choice
Alternative 1. The two methods are described with the same words ("integer or
decimal"), so they should share one scanner; the only stated difference is
which match is kept.

### Risk: 15
Author's likely different reading: the same shared scanner, but without T7's
comma handling.

## T20. `result.extracted_answer` for a `script` evaluation

### Spec Text
> `script` evaluation: ... exit code equal to `success_exit_code` means pass;
> any other exit code means fail
>
> (Part 1) `result.extracted_answer` is the extracted comparison value, or
> `null` when there is no evaluation or no output

### Alternatives
1. The configured `extract` method (defaulting to `full`) is applied to the
   generated response, exactly as for `contains`/`regex` under T9, so a script
   row reports the response text.
2. `null`, because a script evaluation extracts nothing from the response.
3. The command's stdout.

### Choice
Alternative 1, for consistency with T9: `extracted = extract(response, method)`
is computed once before the evaluation-type switch. Reading 3 is excluded
outright — the spec says command output must not appear in the JSONL.

### Risk: 45
Author's likely different reading: `null` for script rows, since nothing is
"extracted" and the script block has no `extract` key in any example.

## T21. Default for `evaluation.success_exit_code`

### Spec Text
> ```yaml
> evaluation:
>   type: "script"
>   command_template: "python3 -c \"{test_code}\""
>   success_exit_code: 0
> ```

### Alternatives
1. `success_exit_code` is optional and defaults to `0`; only `command_template`
   is required.
2. Both keys are required and omitting `success_exit_code` exits `1`.

### Choice
Alternative 1. `0` is the only value shown anywhere in the spec and is the
universal shell success convention, so it is the natural default; requiring it
adds a failure mode the spec never describes.

### Risk: 20
Author's likely different reading: `success_exit_code` required, so a config
omitting it is a configuration error.

## T22. A judge API call that fails outright

### Spec Text
> the judge request is a separate API call through the same server
>
> (Part 1) After the third failure, treat that row as failed, emit `null`
> output for it, count it as failed in the summary, and continue.

### Alternatives
1. The row's *evaluation* fails: `passed` is `false`, `judge_score` is `null`,
   `judge_meta` is `null`, but the generated `output` is kept, since the
   generation itself succeeded.
2. The whole row fails as if generation had failed: `output` becomes `null`.
3. The run aborts with exit code `1`.

### Choice
Alternative 1. The judge call belongs to the evaluation stage, not the
generation stage; discarding a response that was produced successfully would
lose data the spec asks to be written. Exit `1` is reserved for configuration
and input errors. The judge request reuses the Part 1 retry rules (5xx retried
up to 3 total requests).

### Risk: 40
Author's likely different reading: a failed judge call nulls the whole row like
any other failed API call.

## T23. A judge reply the `extract` method finds no score in

### Spec Text
> `result` includes `judge_score`, and `result.extracted_answer` is the text
> `extract` took from the judge's reply (`"8"` for a score of `8`)
>
> score `>= threshold` passes

### Alternatives
1. `judge_score` is `null`, `extracted_answer` is `null`, and the row fails —
   there is no score, so it cannot reach the threshold.
2. The row passes by default, or `judge_score` becomes `0`.

### Choice
Alternative 1. `extracted_answer` is defined as "the text `extract` took", and
`extract` took nothing; a comparison against `threshold` is impossible, and an
unscored response is not evidence of quality.

### Risk: 20
Author's likely different reading: `judge_score` coerced to `0`, which also
fails the row but reports `0` instead of `null`.

## T24. Whether judge tokens count in the summary token totals

### Spec Text
> judge calls count toward throughput, `total_api_calls`, and per-task API call
> totals, and may be interleaved with other work
>
> (Part 1) `total_prompt_tokens` / `total_completion_tokens`: summed across all
> API responses

### Alternatives
1. Judge responses are API responses, so their tokens are summed into
   `total_prompt_tokens` / `total_completion_tokens` like any other.
2. Only generation tokens are summed, since the Part 2 sentence lists
   `total_api_calls` but not the token totals.

### Choice
Alternative 1. Part 1 defines the token totals as "summed across all API
responses", and Part 2 states the judge request *is* an API call through the
same server. The Part 2 sentence is about what judge calls are *not* exempt
from, not an exhaustive list.

### Risk: 30
Author's likely different reading: token totals cover generation only, since
the judge-counting sentence deliberately enumerates three things and stops.

## T25. Is `judge_score` present on rows that were not judged?

### Spec Text
> `result` includes `judge_score`, and `result.extracted_answer` is the text
> `extract` took from the judge's reply

### Alternatives
1. `judge_score` appears only in `result` for `llm_judge` tasks; other tasks
   keep the Part 1 three-key `result` shape.
2. Every row carries `judge_score`, `null` when no judge ran.

### Choice
Alternative 1. The sentence sits inside the `llm_judge` rules, and Part 1's
"existing behavior is unchanged unless stated here" keeps the `result` shape of
`exact_match` / `contains` / `regex` / `script` rows as it was.

### Risk: 35
Author's likely different reading: a fixed `result` shape with `judge_score`
always present (and `null` off the judge path), which falls out of building the
dict in one place.

## T26. Where `judge_meta` goes when `meta` is a list

### Spec Text
> `meta` includes a `judge_meta` object with the judge request's token usage,
> latency, model, and finish reason
>
> (Part 1) `meta` is a single metadata object for one-attempt rows; for
> rejection sampling with multiple attempts it is a list with one metadata
> object per attempt

### Alternatives
1. `judge_meta` is a key *inside* each per-attempt metadata object, because
   each rejection attempt is judged by its own judge call.
2. Only the final (kept) attempt's metadata carries `judge_meta`.
3. `judge_meta` is hoisted to a separate top-level key next to `meta`.

### Choice
Alternative 1. The spec says "`meta` includes a `judge_meta` object", which
places it inside the metadata object; with one judge call per attempt, pairing
each judge call with the attempt it graded is the only lossless arrangement.
Reading 3 is excluded because the spec's row shape has exactly four top-level
keys.

### Risk: 40
Author's likely different reading: `judge_meta` attached only to the last
attempt's entry, or emitted once for the row.

## T27. Is `threshold` required for `llm_judge`?

### Spec Text
> `threshold: 7`
>
> score `>= threshold` passes

### Alternatives
1. `judge_prompt` and `threshold` are both required; omitting either exits `1`.
2. `threshold` defaults to some value (e.g. `1`, or half the scale).

### Choice
Alternative 1. There is no scale defined anywhere in the spec — the 1-10 range
lives only inside an example judge system prompt — so no default threshold can
be invented, and the pass rule is unusable without one.

### Risk: 15
Author's likely different reading: same requirement.

## T28. Multi-task configs and the shape of `--input`

### Spec Text
> for multi-task configs, explicit `--input <task=path>` and `--input-dir` are
> alternative modes; do not combine them
>
> for single-task configs, `--input <path>` without `=` still behaves as in
> Part 1

### Alternatives
1. A multi-task run requires exactly one of the two modes: supplying neither,
   supplying both, or supplying a bare `--input <path>` with no `=` is a
   configuration error (exit `1`). A `task=path` whose task is not in the
   config is also an error.
2. Supplying neither is allowed and simply runs nothing; a bare path is
   accepted and applied to every task.

### Choice
Alternative 1. "do not combine them" is a prohibition, which only has force as
an error; and the spec's careful carve-out of bare `--input <path>` "for
single-task configs" implies it is not meaningful for multi-task configs. A run
with no input at all has no defined source for any task.

### Risk: 30
Author's likely different reading: combining the two modes is merged silently
rather than rejected (only a "do not" in prose, not an explicit error rule).

## T29. `--input-dir` naming a directory that does not exist

### Spec Text
> `--input-dir` looks for `<task_name>.jsonl`

### Alternatives
1. A missing directory — or a missing `<task_name>.jsonl` for a selected task —
   is an input error: exit `1` with a message on stderr.
2. A missing per-task file silently skips that task.

### Choice
Alternative 1. Part 1 already exits `1` for a missing input file, and Part 2
only relaxes the requirement for *unselected* tasks; silently skipping a
selected task would produce a summary that quietly omits requested work.

### Risk: 15
Author's likely different reading: same.

## T30. `--task` naming a task the config does not define

### Spec Text
> `--task <name>`: repeatable; run only the selected task or tasks

### Alternatives
1. Exit `1` naming the unknown task.
2. Ignore it and run the intersection (possibly nothing).

### Choice
Alternative 1. Selecting a task that does not exist is a user mistake with no
sensible execution; silently running nothing would print an empty `tasks`
object and exit `0`.

### Risk: 20
Author's likely different reading: silently ignore unknown names, which falls
out of a set intersection.

## T31. Does `--task` also suppress *config* validation of unselected tasks?

### Spec Text
> when `--task` is present, require input only for selected tasks and ignore
> unselected tasks for validation and execution

### Alternatives
1. "validation" covers both input validation and per-task config validation, so
   a broken unselected task block does not fail the run.
2. "validation" means row/input validation only; every task block in the file
   is still config-checked.

### Choice
Alternative 1. The sentence says "ignore unselected tasks for validation",
without restricting which validation; a selective run should not be blocked by
a task it was told not to run. Structural errors in the file itself (not a
mapping, unparsable YAML) are still fatal.

### Risk: 30
Author's likely different reading: all task blocks are built and validated up
front, and only input presence is relaxed.

## T32. `--output` directory that does not exist yet

### Spec Text
> for multi-task configs, `--output` must be a directory
> write `<output_dir>/<task_name>.jsonl`

### Alternatives
1. Create the directory (including parents) if it is absent; if the path exists
   and is not a directory, exit `1`.
2. Require it to exist already and exit `1` otherwise.

### Choice
Alternative 1. Part 1's `--output <path>` is "created or overwritten", so
creating the output location is the established behavior; "must be a directory"
reads as a constraint on the path's kind, not on its prior existence.

### Risk: 25
Author's likely different reading: the directory must already exist (a bare
`open()` inside it then fails), or the tool creates it with `exist_ok=True`
either way — the visible difference is only in the absent-directory case.

## T33. How deep the `defaults` merge goes

### Spec Text
> `defaults` provides shared values; each task overrides `defaults`
>
> nested sections such as `prompt`, `generation`, and `evaluation` are merged
> per task using the Part 1 structure

### Alternatives
1. Recursive merge: mappings are merged at every depth (so a `defaults`
   `evaluation.judge_prompt.system` survives a task that only sets
   `judge_prompt.user`), and any non-mapping value replaces wholesale.
2. Two-level merge only: top-level keys merge, the named nested sections merge
   one level, and anything deeper is replaced wholesale.

### Choice
Alternative 1. "such as" marks the list of sections as illustrative rather than
exhaustive, and a uniform recursive merge is both the simplest rule to state
and the one that keeps deeper structures (`judge_prompt`) behaving like the
sections around them.

### Risk: 25
Author's likely different reading: a one-level-deep merge over a fixed set of
section names, which differs only for configs that split `judge_prompt` across
`defaults` and a task.

## T34. Generation parameters for the judge request

### Spec Text
> the judge request is a separate API call through the same server
>
> if `evaluation.model` is omitted, use the task's model

### Alternatives
1. The judge call is deterministic: `temperature` `0.0`, `max_tokens` from the
   task's generation settings, and the judge model.
2. The judge call reuses the task's generation settings verbatim, including a
   sampling `temperature` such as `0.7`.

### Choice
Alternative 1. The spec overrides only the model for the judge and says nothing
about sampling; a grader that is itself sampled at high temperature makes the
pass/fail verdict non-reproducible, which defeats the purpose of a threshold.

### Risk: 35
Author's likely different reading: reuse the task's payload builder unchanged
(so `temperature` is whatever the generation block says) and swap only the
model.

## T35. Do multi-task summaries keep the Part 1 token totals?

### Spec Text
> ```json
> {
>   "total": 200, "passed": 170, "failed": 30, "total_api_calls": 350,
>   "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
>   "tasks": { ... }
> }
> ```
> The stdout summary now includes a `tasks` object keyed by executed task name

### Alternatives
1. The summary is the Part 1 object plus `tasks`, so
   `total_prompt_tokens` / `total_completion_tokens` are still emitted; the
   example above is abbreviated.
2. The example is the exact key set, so the token totals are dropped for
   multi-task runs.

### Choice
Alternative 1. "Existing behavior from Part 1 is unchanged unless stated here",
and the change is stated as an addition ("now includes"), not a replacement.
Dropping two keys for multi-task runs only would be a silent, unstated removal.

### Risk: 35
Author's likely different reading: the multi-task summary is exactly the keys
shown in the example, with a test asserting the full key set.

## T36. Key set of each per-task summary object

### Spec Text
> ```json
> "gsm8k": { "total": 100, "passed": 85, "failed": 15, "total_api_calls": 142 }
> ```

### Alternatives
1. Exactly these four keys per task.
2. Also per-task token totals, elapsed time and throughput, mirroring the
   top-level object.

### Choice
Alternative 1. Unlike the top-level object, the per-task object is introduced
*by* this example — there is no prior definition for it to extend — so the
example is the definition.

### Risk: 20
Author's likely different reading: token totals included per task as well.

## T37. Scheduling across concurrent tasks

### Spec Text
> requests from different tasks may run concurrently and may be interleaved
>
> (Part 1) Use the configured `rpm` as the server's approximate request
> capacity ... Target at least 80% of the configured `rpm`.

### Alternatives
1. One shared in-flight budget for the whole run, sized (per T5) from the
   largest `rpm` among the selected tasks, with every task's rows scheduled
   onto the same event loop.
2. A separate budget per task, so total concurrency is the sum over tasks.
3. Tasks run one after another, with concurrency only inside a task.

### Choice
Alternative 1. `rpm` describes one shared server's capacity, so summing it per
task would overstate that capacity by the number of tasks. Reading 3 is
excluded by "may run concurrently and may be interleaved".

### Risk: 25
Author's likely different reading: per-task budgets that add up, since each
task carries its own `rpm` value.

## T38. `--task` against a single-task config

### Spec Text
> `--task <name>`: repeatable; run only the selected task or tasks
>
> if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format; the task name is `task.name`

### Alternatives
1. Accepted when the name matches `task.name` (that is what the second sentence
   establishes the name *for*); any other name exits `1`.
2. Always ignored for single-task configs.

### Choice
Alternative 1. The spec bothers to define the single-task config's task name,
which is only useful for `--task` selection and summary/reporting purposes.

### Risk: 25
Author's likely different reading: `--task` is ignored entirely in single-task
mode, so a mismatched name still runs the task.

## T39. JSON type of `judge_score`

### Spec Text
> if the judge returns `"8"`, then `judge_score` is `8`

### Alternatives
1. Numeric, integral when the extracted text is integral (`8`, not `8.0`) and
   a float when it is not (`8.5`).
2. Always a float (`8.0`).
3. The raw string (`"8"`).

### Choice
Alternative 1. The spec writes `8`, not `8.0` or `"8"`, and separately keeps the
string form in `extracted_answer` — so the two fields are meant to differ in
type.

### Risk: 20
Author's likely different reading: always `float`, giving `8.0` in the JSONL.

## T40. A config containing both `task` and `tasks`

### Spec Text
> if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format

### Alternatives
1. `task` wins: its presence alone selects single-task mode, whatever else is
   in the file.
2. Having both is a configuration error.

### Choice
Alternative 1. The rule is stated as an unconditional test on the presence of
`task`, with no exception for a file that also has `tasks`.

### Risk: 20
Author's likely different reading: rejecting the combination as ambiguous.

## T41. Which shell runs a `script` command

### Spec Text
> run the rendered command in a shell

### Alternatives
1. The platform's default shell via `/bin/sh -c` (Python's
   `create_subprocess_shell`), inheriting the environment and the current
   working directory.
2. `bash -c` specifically.

### Choice
Alternative 1. "a shell" names no particular one, and the standard library's
shell execution is the obvious implementation. The spec's own examples use
POSIX constructs (`|`, `grep -q`) that `/bin/sh` handles.

### Risk: 10
Author's likely different reading: `subprocess.run(..., shell=True)`, which is
the same `/bin/sh`.

## T42. Default `extract` for `llm_judge`

### Spec Text
> ```yaml
> evaluation:
>   type: "llm_judge"
>   ...
>   extract: "first_number"
> ```

### Alternatives
1. `extract` defaults to `first_number` for `llm_judge`, since the judge's
   reply must yield a number to compare against `threshold`.
2. `extract` keeps the Part 1 default of `full`, so a judge config that omits
   it scores `null` on any reply that is not bare digits.

### Choice
Alternative 1. Both spec examples of `llm_judge` use `first_number`, and `full`
would make the omitted case fail for essentially every realistic judge reply —
a default that never works is not a default.

### Risk: 30
Author's likely different reading: one global `extract` default of `full` for
every evaluation type, since Part 1 states it without qualification.

## T43. Are rows whose generation failed still judged?

### Spec Text
> `__response__` is the generated response text
>
> (Part 1) `result.extracted_answer` is the extracted comparison value, or
> `null` when there is no evaluation or no output

### Alternatives
1. No response means no judge call: the row is failed with `output: null`,
   `judge_score: null`, and no judge request is issued.
2. The judge is called anyway with an empty `__response__`.

### Choice
Alternative 1. There is no response text to substitute, and Part 1 already
settles such a row as failed with `null` output; spending an API call to grade
nothing would inflate `total_api_calls` for no verdict.

### Risk: 10
Author's likely different reading: same.
