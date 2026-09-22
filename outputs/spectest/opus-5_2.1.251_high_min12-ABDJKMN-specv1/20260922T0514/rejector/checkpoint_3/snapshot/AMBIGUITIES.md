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

---

# Part 3 — ICL setups and multiple solutions per input

Entries T44 onward cover the ICL / `num_solutions` extension. Earlier entries
are unchanged by this part unless annotated.

## T44. Default `icl.strategy` when omitted

### Spec Text
> `icl.strategy` is one of `fixed`, `random`, or `round_robin`

### Alternatives
1. `strategy` is optional and defaults to `fixed` (always the first setup).
2. `strategy` is required whenever `icl` is present; omitting it is a config
   error with exit code 1.
3. It defaults to `round_robin`, so that multiple declared setups are all used.

### Choice
Alternative 1. Every other optional key in this spec family has a stated
default and the spec never marks `strategy` required (unlike `name` and
`examples`/`file`, which it does mark). `fixed` is the degenerate, least
surprising behaviour and matches the single-setup file example, which declares
`strategy: "fixed"` explicitly but would be meaningless otherwise.

### Risk: 25
Author's likely different reading: `round_robin` as the default, so that a
config listing several setups exercises them without extra keys.

## T45. `icl.k` larger than the number of examples in the selected setup

### Spec Text
> `icl.k` defaults to all examples in the selected setup
>
> if `k` is smaller than the number of examples in the setup, use the first
> `k`

### Alternatives
1. `k` is a cap: a setup with fewer examples than `k` contributes all of its
   examples and the run proceeds.
2. It is a config error — the run terminates with exit code 1.

### Choice
Alternative 1. The spec only defines behaviour for `k` smaller than the example
count and for `k` absent (all examples); a cap is the single rule that covers
both (`examples[:k]`) and it lets setups of differing sizes share one `k`.
Erroring would be a new failure mode the spec never mentions.

### Risk: 15
Author's likely different reading: same (`examples[:k]` slicing falls out of
the obvious implementation).

## T46. `prompt.user` when ICL is configured, and example inputs that do not fit it

### Spec Text
> each example's `input` is rendered with the task's `prompt.user` template

### Alternatives
1. ICL requires `prompt.user`, and every example `input` must supply the fields
   the template references; violations terminate the run with exit code 1
   before any API requests are sent (matching the ICL file validation rule).
2. A missing field renders as empty text, or the example turn is skipped.
3. The failure surfaces at request time, after some API calls have been made.

### Choice
Alternative 1. The spec already insists that malformed ICL data "must terminate
the run with exit code 1 before any API requests are sent"; an example that
cannot be rendered is the same class of defect, and Part 1 already terminates a
run whose *rows* miss a template field. Validating at config-build time keeps
"before any API requests" true.

### Risk: 35
Author's likely different reading: a `KeyError`-style crash at request time, or
a silently empty substitution, since the author's validation pass may only
check the JSONL shape.

## T47. Does `round_robin` cycle per input row or globally across the run?

### Spec Text
> `round_robin`: cycle through setups in order across attempts
>
> Round-robin order with setups `[A, B, C]`: attempt 1 uses `A` ... attempt 4
> uses `A`

### Alternatives
1. The cycle is per input row: every row starts at the first setup, and
   "attempt 1/2/3..." are that row's attempts.
2. One global counter shared by every row (and, in a multi-task config, every
   task).

### Choice
Alternative 1. The spec numbers attempts within a row everywhere else
(`result.attempts` is "the total number of generation attempts for the row"),
and rows are processed concurrently, so a global counter would make the setup
assigned to a given row nondeterministic and untestable. Per-row cycling makes
the documented `[A, B, C, A, B]` sequence reproducible.

### Risk: 20
Author's likely different reading: a single process-wide counter, which is
indistinguishable from per-row cycling on a one-row fixture — the most likely
fixture — so the readings mostly agree where it is tested.

## T48. `greedy` without ICL when `num_solutions > 1`

### Spec Text
> `greedy` with ICL: generate at temperature `0` once per selected setup and
> stop when `num_solutions` solutions are collected or all setups are
> exhausted; because the same setup is deterministic, the maximum number of
> produced solutions is the number of available setups

### Alternatives
1. The same cap logic with exactly one "setup" (the plain prompt): one attempt,
   at most one solution, `output` a one-item list.
2. `num_solutions` identical requests are issued anyway.
3. It is a config error.

### Choice
Alternative 1. The spec's stated reason for the greedy cap is determinism —
"do not retry the same greedy setup to manufacture additional outputs" — and a
no-ICL greedy task is exactly one deterministic prompt, so the cap is one.
Reading 2 would spend `num_solutions` API calls to produce duplicate text the
spec explicitly calls manufactured.

### Risk: 40
Author's likely different reading: `num_solutions` independent requests, if the
author's code branches only on scheme (`greedy` falling through to the generic
"one request per solution" loop) rather than on ICL presence.

## T49. Does `generation.n` still bound rejection attempts once `max_attempts` applies?

### Spec Text
> ```yaml
> generation: {scheme: "rejection", temperature: 0.7, n: 5, max_attempts: 15}
> num_solutions: 5
> ```
> `max_attempts` applies to rejection sampling in this part
>
> if `max_attempts` is omitted for rejection, default it to `3 * num_solutions`

### Alternatives
1. In the new mode `max_attempts` is the only attempt bound; `n` is ignored.
2. The bound is `min(n, max_attempts)`, keeping Part 1's `n` in force.
3. The bound is `n * max_attempts`.

### Choice
Alternative 1. The spec's own example sets `n: 5` alongside `max_attempts: 15`
and then describes the loop purely in terms of `max_attempts` ("until
`num_solutions` passing solutions have been collected or `max_attempts` is
exhausted"); under reading 2 the example could never exceed 5 attempts, making
`max_attempts: 15` dead config. The default `3 * num_solutions` also ignores
`n` entirely.

### Risk: 15
Author's likely different reading: same; `n` is retained only for the legacy
single-solution path the spec carves out.

## T50. Key set of `result` in the list output format

### Spec Text
> ```json
> "result": {"passed": 2, "failed": 5, "attempts": 7}
> ```

### Alternatives
1. Exactly these three keys: `extracted_answer` (Part 1) and `judge_score`
   (Part 2) are dropped in list format, because a row now has many extracted
   answers and no single one to report.
2. The example is abbreviated and `extracted_answer` / `judge_score` are still
   emitted, scalar-valued for the last attempt.
3. They are emitted as lists, one entry per attempt.

### Choice
Alternative 1. This example redefines `result` wholesale — `passed` changes
type from boolean to integer and `failed` is new — so it reads as a
specification of the object, not an addition to it. A single scalar
`extracted_answer` for a seven-attempt row has no defensible value.

### Risk: 35
Author's likely different reading: `extracted_answer` retained (carried from
the last attempt) because the author's row builder adds it unconditionally;
`judge_score` likewise for `llm_judge` tasks.

## T51. A hard HTTP failure inside a multi-solution row

### Spec Text
> `rejection` with ICL: keep generating and evaluating until `num_solutions`
> passing solutions have been collected or `max_attempts` is exhausted
>
> (Part 1) After the third failure, treat that row as failed, emit `null`
> output for it, count it as failed in the summary, and continue.

### Alternatives
1. The dead attempt is counted in `result.attempts`, contributes a metadata
   entry with `null` response fields, produces no output item, and the row
   keeps going until its budget is spent.
2. The whole row is abandoned as in Part 1 (T3), discarding solutions already
   collected and emitting `output: null`.
3. The attempt is skipped silently: no metadata entry, not counted in
   `attempts`.

### Choice
Alternative 1. Part 1's rule exists because a one-attempt row has nothing else
to report; here the row explicitly has a multi-attempt budget and the spec's
partial-result example shows a row writing "only those two passing outputs"
rather than `null`. "`meta` is a list with one entry per attempt" forces an
entry for the dead attempt, so its response-derived fields are `null`.

### Risk: 45
Author's likely different reading: no metadata entry at all for a request that
never returned (so `meta` is shorter than `attempts`), since the author's
accumulator probably appends only on success.

## T52. Do per-task summary `passed` / `failed` count rows or solutions?

### Spec Text
> ```json
> "gsm8k": {"total": 100, "total_solutions": 450,
>           "avg_solutions_per_input": 4.5, "total_api_calls": 850}
> ```
> Per-task summary fields **gain**: ...

### Alternatives
1. `passed` / `failed` keep their Part 2 meaning — a count of input rows, where
   a row counts as passed if it produced at least one passing solution — and
   the new keys are added alongside.
2. They are dropped, because the example omits them.
3. They are re-defined to count solutions, mirroring `result.passed`.

### Choice
Alternative 1. The spec says the fields "gain" new entries, which is an
addition, and `total` in the same example is still a row count (100 inputs,
450 solutions). Solution counts already have their own key, so redefining
`passed` would duplicate `total_solutions`. "At least one passing solution"
keeps `passed + failed == total`.

### Risk: 40
Author's likely different reading: `passed`/`failed` absent from the per-task
object (the example taken as the exact key set), or summing `result.passed`
across rows.

## T53. Does the top-level summary also gain the new fields?

### Spec Text
> Per-task summary fields gain: ... `total_solutions`,
> `avg_solutions_per_input`
>
> (Part 2) for single-task configs, the stdout summary keeps its previous keys
> and has no `tasks` object

### Alternatives
1. Only the per-task objects gain them; the top-level summary keeps its Part 1
   key set exactly.
2. The top-level summary gains aggregated `total_solutions` and
   `avg_solutions_per_input` too.

### Choice
Alternative 1. The heading scopes the change to "per-task summary fields", and
Part 2 explicitly froze the single-task summary's key set. A single-task
Part 1 style config therefore reports no solution counts at all, which is
consistent with it reporting no per-task object either.

### Risk: 30
Author's likely different reading: the top-level object gains the same two
keys, since it aggregates every other per-task number.

## T54. Numeric form of `avg_solutions_per_input`

### Spec Text
> `"avg_solutions_per_input": 4.5`

### Alternatives
1. A float rounded to 2 decimal places (matching how `elapsed_seconds` and
   `throughput_rpm` are rounded elsewhere).
2. The unrounded quotient.
3. `null` or `0` when the task has no rows.

### Choice
Alternative 1 for the value and `0.0` for an empty task. Both readings agree on
every quotient with a short decimal expansion — including the spec's 4.5 — and
rounding matches the surrounding summary style.

### Risk: 20
Author's likely different reading: the raw quotient, which differs only when a
test uses a ratio like 1/3.

## T55. Does evaluation gate `sample` *without* ICL?

### Spec Text
> `sample` with ICL: make one sampled generation per requested solution using
> the chosen ICL strategy; evaluation does not gate whether a solution is
> included
>
> `sample` without ICL: make `num_solutions` independent sampled requests

### Alternatives
1. Non-gating is a property of `sample`, not of ICL: every successful request
   becomes an output item in both cases.
2. The no-ICL bullet is silent, so evaluation gates there and only passing
   samples are emitted.

### Choice
Alternative 1. Part 1 already emits `sample` output regardless of the verdict,
and the second bullet describes the no-ICL case as "the same" apart from the
prompt. Gating `sample` only when ICL is absent would invert Part 1 behaviour
without saying so.

### Risk: 10
Author's likely different reading: same.

## T56. Does `max_attempts` bound `greedy` or `sample`?

### Spec Text
> `max_attempts` applies to rejection sampling in this part

### Alternatives
1. Only rejection consults `max_attempts`; greedy and sample are bounded by
   setup count and `num_solutions` respectively, even if `max_attempts` is set
   lower.
2. It is a global per-row request cap for every scheme.

### Choice
Alternative 1. The sentence names rejection specifically, and the greedy and
sample bullets state their own bounds without referring to `max_attempts`.

### Risk: 20
Author's likely different reading: a global cap applied in one place for all
schemes.

## T57. `icl` present but malformed (no `setups`, empty list, both `examples` and `file`)

### Spec Text
> each setup has a `name` and exactly one of `examples` or `file`

### Alternatives
1. All of these are config errors: exit code 1 before any request. An `icl`
   block with no setups, an empty `setups` list, a setup with neither or both
   of `examples`/`file`, a nameless setup, or a duplicate name.
2. An empty or absent `setups` list simply means "no ICL" and the run proceeds
   in the Part 1 format.

### Choice
Alternative 1 (except duplicate names, which are permitted — the spec never
says names are unique and `fixed`/`round_robin` do not need them to be).
"Exactly one of" is a stated requirement, and the file rules show the author
expects malformed ICL config to terminate the run rather than be ignored.

### Risk: 30
Author's likely different reading: an empty `setups` list treated as no ICL, or
`examples` silently winning when both keys are present.

## T58. `--icl-strategy` / `--icl-k` for a task with no `icl` block

### Spec Text
> New flags: `--num-solutions <int>`, `--icl-strategy <...>`, `--icl-k <int>`
>
> CLI flags override config values

### Alternatives
1. They override the corresponding `icl` keys only where an `icl` block exists;
   for a task without ICL they are inert and the task stays non-ICL.
2. They synthesise an `icl` block, which then fails validation for having no
   setups (exit 1).

### Choice
Alternative 1. A flag that "overrides config values" cannot invent setups —
there are no examples to draw on — and in a multi-task run the flags apply to
every selected task, so reading 2 would make `--icl-k` unusable whenever any
task lacks ICL.

### Risk: 15
Author's likely different reading: same.

## T59. Blank lines and trailing newlines in an ICL file

### Spec Text
> file-backed setups must be valid JSONL where each non-empty line has
> `{"input": <object>, "output": <string>}`

### Alternatives
1. Whitespace-only lines are skipped anywhere in the file; every other line
   must parse.
2. Only a trailing newline is tolerated.

### Choice
Alternative 1. "each non-empty line" states the rule directly, and it matches
how Part 1 already loads input JSONL.

### Risk: 5
Author's likely different reading: same.

## T60. `num_solutions` validation

### Spec Text
> `--num-solutions <int>` ... `num_solutions` may be set in `defaults` or per
> task

### Alternatives
1. Must be a positive integer; `0`, a negative value or a non-integer is a
   config error (exit 1), consistent with how `n`, `rpm` and `max_tokens` are
   validated.
2. `0` is allowed and produces rows with empty `output` lists.

### Choice
Alternative 1. Every other count in the config family is validated as a
positive integer, and `num_solutions: 0` has no described output shape.

### Risk: 20
Author's likely different reading: no validation at all, so `0` yields an empty
list rather than exit 1.

## T61. An explicit `max_attempts` on a legacy single-solution rejection task

### Spec Text
> legacy compatibility: when `num_solutions == 1` and no ICL is configured,
> keep the Part 1 rejection behavior (`generation.n` logical attempts) and do
> not apply `max_attempts`

### Alternatives
1. The carve-out is unconditional: even an explicitly configured
   `max_attempts` is ignored, and the row stops at the first pass within `n`
   attempts, in the Part 1 output format.
2. An explicit `max_attempts` opts the task into the new behaviour; only the
   `3 * num_solutions` default is suppressed.

### Choice
Alternative 1. "do not apply `max_attempts`" is absolute, and the conditions
given are only `num_solutions == 1` and no ICL. Reading 2 would also have to
decide the output format, which the spec ties to the same two conditions.

### Risk: 25
Author's likely different reading: an explicit `max_attempts` still caps the
row, since the author's attempt bound may be computed as
`min(n, max_attempts)` before the legacy check.

## T62. Do ICL examples appear in the `llm_judge` prompt?

### Spec Text
> ICL examples are inserted between the system message and the final user
> message as alternating user and assistant turns
>
> each example's `input` is rendered with the task's `prompt.user` template

### Alternatives
1. ICL shapes generation requests only; judge requests keep their Part 2
   two-message shape.
2. Judge requests also get the example turns.

### Choice
Alternative 1. The examples are rendered with `prompt.user` and paired with the
task's own outputs, which are answers to the task, not judgements of it;
injecting them into a judge prompt would model the wrong turn. `icl_setup` is
also recorded per generation attempt, not per judge call.

### Risk: 10
Author's likely different reading: same.

## T63. `result.failed` when evaluation is configured

### Spec Text
> `result.failed` is the count of failed attempts
>
> if `num_solutions: 5` and `max_attempts: 10` and only two attempts pass
> before the tenth attempt ... report `passed: 2`, `failed: 8`, and
> `attempts: 10`

### Alternatives
1. `failed == attempts - passed`: every attempt that did not yield a passing
   solution counts as failed, including attempts whose request died.
2. Only attempts that produced a response and failed evaluation count, so a
   row with a dead request has `passed + failed < attempts`.

### Choice
Alternative 1. The worked example has `passed + failed == attempts` exactly,
and it is the only arithmetic relation the spec pins down.

### Risk: 15
Author's likely different reading: same.

## T64. `total_solutions` for rows in the legacy (Part 1) output format

### Spec Text
> `total_solutions`, `avg_solutions_per_input`

### Alternatives
1. A legacy row counts as 1 solution when its `output` is non-`null` and 0 when
   it is `null`, so the fields are meaningful for every task.
2. The fields are emitted only for tasks using the list format.

### Choice
Alternative 1. The summary keys are described unconditionally, and a
single-solution task trivially has one solution per passing input; omitting the
keys for some tasks would make the per-task object's shape depend on the
scheme.

### Risk: 25
Author's likely different reading: the keys present only when ICL or
`num_solutions > 1` is configured for that task.
