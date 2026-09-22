# Ambiguities

Interpretation decisions taken while implementing the spec. Each entry quotes the
spec, lists the readings that would produce different observable behaviour, states
the choice, and rates the chance the spec author's reference implementation reads
it differently.

## T1. What `rpm` controls: pacing, concurrency, or both

### Spec Text

> The API server queues requests internally and spends time processing each
> request. It does not return rate-limit errors. A sequential client will
> leave capacity idle; your tool should keep enough requests in flight to
> use the configured request budget effectively.

> Use the configured `rpm` as the server's approximate request capacity and
> keep enough work in flight to avoid an obviously sequential pipeline.
> Target at least 80% of the configured `rpm`.

### Alternatives

1. `rpm` is a client-side rate limit: pace requests evenly at `rpm` (one every
   `60/rpm` seconds). Throughput then tops out at slightly under `rpm`, and on a
   short run the trailing request latency can drag the measured
   `throughput_rpm` below the 80% target.
2. `rpm` only sizes concurrency: never pace, keep up to ~`rpm` requests in
   flight, and let the server's queue be the only limiter. Measured throughput
   equals whatever the server can do, possibly well above `rpm`.
3. Both: a token bucket that refills at `rpm`/minute but starts full (burst
   capacity `rpm`), combined with an in-flight cap derived from `rpm`.

### Choice

Option 3. A burst-capable token bucket (`capacity = rpm`, refill `rpm/60` per
second) plus an in-flight cap of `clamp(rpm, 8, 256)`. Short runs go out as a
burst, so the 80% target is met with headroom; long runs settle at the
configured budget instead of hammering a server whose stated capacity is `rpm`.
Because the spec says the server does not return rate-limit errors, exceeding
the budget is never an error — the bucket exists only to keep sustained load
near the documented capacity.

### Risk: 30

The author most likely just sizes an asyncio semaphore/worker pool from `rpm`
with no pacing at all (option 2); observable difference is only on runs long
enough to drain the bucket.

## T2. Whether HTTP retries inflate `result.attempts` for rejection rows

### Spec Text

> Retry requests count toward `total_api_calls`, but for `greedy` and `sample`
> rows they do not increase the logical `result.attempts` count.

### Alternatives

1. The greedy/sample carve-out is a clarification of a general rule: retries
   never increase logical attempts, rejection included.
2. Naming only greedy and sample implies rejection is different, i.e. a retried
   HTTP request does bump `attempts` for rejection rows.

### Choice

Option 1. `result.attempts` is defined as "the number of logical generation
attempts", and `1..n` for rejection is bounded by the configured `n`; letting
retries push `attempts` past `n` would contradict that bound.

### Risk: 20

The author's code almost certainly increments an attempt counter in the
rejection loop, which is retry-agnostic, so both readings coincide.

## T3. `meta` for a row whose attempts all failed at the HTTP level

### Spec Text

> After the third failure, treat that row as failed, emit `null` output for it,
> count it as failed in the summary, and continue.

> `meta` is a single metadata object for one-attempt rows

### Alternatives

1. `meta` is `null` — there is no successful response to describe.
2. `meta` keeps its documented shape with zeroed/`null` fields, so consumers can
   rely on the key's type.
3. `meta` gains an extra `error` key describing the failure.

### Choice

Option 2: a metadata object with the configured `model`, `0` token counts,
measured `latency_ms` for the failed call chain, and `finish_reason: null`. No
extra keys are added, so a strict shape comparison against the documented six
fields still succeeds.

### Risk: 45

Plausibly the author emits `meta: null` (option 1) for a row with no response;
a fixture that asserts the whole failed row object would then differ.

## T4. `result.extracted_answer` for `contains` and `regex` evaluations

### Spec Text

> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output

> - `contains`: response text must contain the `answer_field` value as a
>   substring
> - `regex`: response text must match the configured `pattern`

### Alternatives

1. Extraction is a single uniform step driven by `evaluation.extract` regardless
   of `type`, so `extracted_answer` is `extract(response)` for every type
   (whole response text when `extract` defaults to `full`).
2. `extracted_answer` is `null` for `contains`/`regex`, since neither compares an
   extracted value.
3. Type-specific: for `regex` the matched substring (or first capture group), for
   `contains` the matched `answer_field` value.

### Choice

Option 1. `extract` is configured once per evaluation and is not documented as
`exact_match`-only, and the spec makes `extracted_answer` `null` only for "no
evaluation or no output" — implying a non-null value whenever an evaluation ran
against a response.

### Risk: 45

For `regex` the author may well report the matched text (option 3) or `null`
(option 2); `exact_match` behaviour is unaffected either way.

## T5. What counts as "the last integer or decimal"

### Spec Text

> - `last_number`: use the last integer or decimal in the response

### Alternatives

1. A minimal scan such as `-?\d+\.?\d*`, which also swallows a sentence-final
   period ("the answer is 8." -> `8.`) and splits thousands separators
   ("1,234" -> `234`).
2. A stricter number grammar: optional sign, optional `,` thousands groups,
   optional fractional part, with separators stripped ("1,234" -> `1234`,
   "8." -> `8`).

### Choice

Option 2, with `-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?|-?\.\d+` and
commas removed from the result. Grouped digits are one number in ordinary
prose, and a trailing sentence period is not part of a decimal.

### Risk: 40

If the author used the naive regex (option 1), any fixture containing a
comma-grouped number or a number at the end of a sentence diverges. Their most
likely reading is the naive `-?\d+\.?\d*` scan.

## T6. How `exact_match` compares extracted text to `answer_field`

### Spec Text

> - `exact_match`: extract an answer from the response and compare it to the
>   configured `answer_field` from the input row

### Alternatives

1. String equality after stripping whitespace: `"8.0" != "8"`.
2. Numeric equality when both sides parse as numbers, string equality otherwise:
   `"8.0" == "8"`.

### Choice

Option 2. Paired with `last_number` extraction the compared values are numbers,
and a model writing `8.0` for an answer of `8` is an exact match in the sense the
spec's gsm8k example implies. Non-numeric values still compare as stripped
strings.

### Risk: 35

A reference implementation doing a bare `==` on strings (option 1) is very
plausible; it differs only when the two sides are numerically equal but
textually different.

## T7. Default `extract` method when `evaluation.extract` is absent

### Spec Text

> ```yaml
>   evaluation:
>     type: "exact_match"
>     answer_field: "answer"
>     extract: "last_number"
> ```

> - `exact_match` and `contains` require `answer_field`
> - `regex` requires `pattern` and does not require `answer_field`

### Alternatives

1. `extract` is required for `exact_match` (invalid config otherwise).
2. `extract` defaults to `full`.

### Choice

Option 2, default `full`. The validation rules list exactly which keys are
required and `extract` is not among them, so an absent `extract` must not be a
config error.

### Risk: 15

Only observable for an `exact_match` config that omits `extract`.

## T8. A rejection attempt that exhausts its HTTP retries

### Spec Text

> `rejection`: `temperature` must be `> 0`; make up to `n` attempts and keep
> the first passing response; if all attempts fail, output `null` with
> `"passed": false`

### Alternatives

1. The HTTP failure aborts the row immediately: `attempts` is however many
   attempts had been made, remaining attempts are skipped.
2. It is simply a non-passing attempt: record its metadata and continue with the
   remaining attempts, up to `n`.

### Choice

Option 2. "Make up to `n` attempts and keep the first passing response" treats a
failed attempt as a reason to try again, and a transient 5xx is the case most
worth retrying.

### Risk: 30

An implementation that propagates the API failure out of the rejection loop
(option 1) would report fewer `attempts` and fewer `total_api_calls` for that
row.

## T9. Whether `throughput_rpm` uses rounded or raw `elapsed_seconds`

### Spec Text

> - `elapsed_seconds`: wall-clock time from first request to last response,
>   rounded to 1 decimal place
> - `throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to
>   1 decimal place

### Alternatives

1. Compute from the raw elapsed time, then round the quotient.
2. Compute from the already-rounded `elapsed_seconds` so the two reported
   numbers are exactly consistent.

### Choice

Option 1 (raw elapsed, round once at the end); rounding inputs before dividing
compounds error. When no request was ever sent, `elapsed_seconds` and
`throughput_rpm` are both `0.0` rather than a division error.

### Risk: 15

Differences show up only in the last decimal place, and only for runs short
enough for the rounding of elapsed to matter.

## T10. When missing prompt fields are detected

### Spec Text

> If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field.

> If a prompt template references `{question}` and row `0` is
> `{"text": "hello"}`, exit with code `1` and print an error to stderr naming
> row `0` and missing field `question`.

### Alternatives

1. Validate every row up front and exit before any API traffic or output file is
   created.
2. Discover the problem lazily while processing, after earlier rows have already
   been sent and possibly written.

### Choice

Option 1: all rows (prompt placeholders and, when configured, `answer_field`)
are validated before the first request; the run exits 1 naming the lowest
offending row index and leaves no output file behind. This is grouped with
config errors, matching "configuration or input error" for exit code 1.

### Risk: 25

The author may validate lazily, in which case a partially written output file
could exist after the failure; the stderr message and exit code agree either
way.

## T11. `temperature` absent under `sample`/`rejection`

### Spec Text

> - `sample`: `temperature` must be `> 0`; `n` is ignored
> - `rejection`: `temperature` must be `> 0`

### Alternatives

1. Missing `temperature` defaults to `0.0` (as in the spec's config shape), so
   `sample`/`rejection` without an explicit temperature is a config error.
2. Missing `temperature` defaults to an API-style `1.0`, which satisfies `> 0`.

### Choice

Option 1. The documented config shape shows `temperature: 0.0`, so `0.0` is the
natural default, and the requirement then fails loudly instead of silently
picking a sampling temperature the user never asked for.

### Risk: 30

If the author defaults to `1.0`, a `sample` config without `temperature` runs
successfully there and exits 1 here.

## T12. Which config keys are required

### Spec Text

> Invalid configuration exits with code `1` and a descriptive message on
> stderr.

### Alternatives

1. Every key shown in the config shape is required.
2. Only keys without a sensible default are required; the rest default.

### Choice

Option 2. Required: `task`, `api_url`, `model`, `prompt.user`, `output_field`.
Defaulted: `rpm` (60), `prompt.system` (omitted), `generation.scheme`
(`greedy`), `temperature` (0.0), `max_tokens` (512), `n` (1), `name` (unused).
`output_field` stays required because the output row's shape is unspecifiable
without it. Validation failures that the spec enumerates explicitly are all
still errors.

### Risk: 25

The author's loader may be stricter (e.g. requiring `rpm` or `generation`) or
looser (defaulting `output_field` to something like `output`).

## T13. Failures other than HTTP 5xx

### Spec Text

> If a request receives an HTTP `5xx`, retry it up to 3 total requests.

### Alternatives

1. Only 5xx is retried; every other failure (4xx, connect error, timeout,
   unparseable body) fails the row on the first occurrence.
2. Transport-level failures are morally 5xx and share the 3-request budget;
   4xx and malformed bodies are not retried.

### Choice

Option 2. A dropped connection or timeout is the same transient condition a 5xx
signals, so it retries; a 4xx or a response without `choices` is deterministic
and fails the row immediately (`output: null`, counted failed).

### Risk: 25

Only reachable in tests that inject transport errors or 4xx, which the spec
never describes.

## T14. `meta` shape for a rejection row that passed on its first attempt

### Spec Text

> `meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt

### Alternatives

1. Literal reading: one attempt means a single object, even under `rejection`.
2. Scheme-driven: `rejection` always emits a list, length 1 when it passed
   immediately.

### Choice

Option 1, the literal reading: the list appears only when there are 2+ attempts.

### Risk: 25

An implementation that collects metadata into a list per rejection row and
writes it unconditionally (option 2) is easy to write; a single-attempt
rejection fixture would then expect `[{...}]`.

## T15. `meta.latency_ms` when a call was retried

### Spec Text

> `meta.latency_ms` is wall-clock latency for that API call

### Alternatives

1. Latency of the final (successful) HTTP request only.
2. Total time across the retried requests for that logical attempt.

### Choice

Option 1 — "that API call" is the call whose response the metadata describes.
For a row that failed after three 5xx responses, the reported latency is the
span of the whole failed chain, since no single call succeeded.

### Risk: 20

Only observable when a retry actually happens.

## T16. `prompt.system` omitted

### Spec Text

> ```json
>   "messages": [
>     {"role": "system", "content": "<rendered system prompt>"},
>     {"role": "user", "content": "<rendered user prompt>"}
>   ]
> ```

### Alternatives

1. Always send two messages; an absent system prompt becomes `""`.
2. Send only the user message when no system prompt is configured.

### Choice

Option 2 — an empty system message is not something the user configured.

### Risk: 15

Only observable for a config without `prompt.system`, which every example has.

## T17. Placeholder substitution mechanics

### Spec Text

> `prompt.system` and `prompt.user` use `{field}` placeholders resolved from
> each input row.

### Alternatives

1. `str.format(**row)`, which also interprets `{{`/`}}` escapes, `{a.b}`
   attribute access and `{x:>10}` format specs, and raises on stray braces.
2. A regex substitution of `{name}` occurrences with `str(value)`, leaving any
   other brace text alone.

### Choice

Option 2. Prompts routinely contain literal braces (JSON, code) and the spec
only promises `{field}` resolution; regex substitution cannot fail on unrelated
braces and makes "missing field" detection exact. Non-string values are
rendered with `str()` (`json`-style for nested containers is not implied).

### Risk: 15

Diverges only for templates using `str.format` extras or stray braces.

## T18. Blank and malformed lines in the JSONL input

### Spec Text

> The input file is JSONL with one object per line.

### Alternatives

1. Any line that is not a JSON object is an input error (exit 1), blank lines
   included.
2. Whitespace-only lines are skipped; a non-object or unparseable line is an
   input error naming the line.

### Choice

Option 2. Trailing newlines are ubiquitous in JSONL, so blank lines are ignored
and do not become rows; anything else that is not a JSON object exits 1.

### Risk: 20

An author who counts blank lines as rows would report a different `total`.

## T19. Source of `meta.model`

### Spec Text

> ```json
>   "meta": {
>     "model": "gpt-4",
> ```

### Alternatives

1. The configured/overridden model name.
2. The `model` field echoed by the API response.

### Choice

Option 1, the configured model: it is always present (including on failed rows)
and matches the example, where config and response agree.

### Risk: 10

Differs only against a server that echoes a different model name.

## T20. What "send requests in input order" constrains

### Spec Text

> Send requests in input order: concurrent execution must not cause a later
> input row to consume the response intended for an earlier row.

### Alternatives

1. Only the row/response pairing and the output ordering are constrained; rows
   are dispatched in input order but the order requests *arrive* at the server
   is not guaranteed.
2. The server must observe requests in exactly input order.

### Choice

Option 1. Rows are dispatched in input order (tasks are created in order and each
takes its rate-limiter token through a FIFO lock), results are written in input
order, and each row keeps its own response. Exact arrival order is not
guaranteed: with several connections opening at once, TCP setup alone can let
row 1's request land before row 0's, which is true of any concurrent client
including one built to this spec.

### Risk: 20

If the author's fixture asserts the server's received order equals input order,
it would be satisfied only by a client that effectively serialises sending -
which contradicts the throughput requirement - so their test most likely checks
pairing, as here. Some strict-order fixtures could still diverge on a run with
many rows in flight.

## T21. `result.passed` for a failed API row when no evaluation is configured

### Spec Text

> - if `evaluation` is omitted for `greedy` or `sample`,
>   `result.passed` must be `null`

> After the third failure, treat that row as failed, emit `null` output for it,
> count it as failed in the summary, and continue.

> - `failed`: rows where `result.passed` is `false` or `output` is `null`

### Alternatives

1. `passed` stays `null` whenever no evaluation is configured, API failure
   included. The row is still counted failed, because its `output` is `null`.
2. An API failure forces `passed: false` regardless of configuration, since the
   row "failed".

### Choice

Option 1. "Must be null" is stated unconditionally for greedy/sample without
evaluation, and the summary's `failed` rule already catches the row through
`output: null`, so nothing is lost. With an evaluation configured, a row whose
attempts all failed does report `passed: false`, matching the rejection example.

### Risk: 30

Summary counts are identical either way; only the row's `passed` field differs.
The author may well set `false` on any API failure (option 2).

## T22. How deeply `defaults` and a task body are merged

### Spec Text

> - `defaults` provides shared values; each task overrides `defaults`
> - nested sections such as `prompt`, `generation`, and `evaluation` are merged
>   per task using the Part 1 structure

### Alternatives

1. One level of nesting is merged: `prompt`, `generation` and `evaluation` are
   merged key by key, but anything deeper (`evaluation.judge_prompt`) is
   replaced wholesale by the task's value.
2. Mappings are merged recursively at every depth, so a task that sets only
   `evaluation.judge_prompt.user` keeps a `judge_prompt.system` from `defaults`.

### Choice

Option 2, a recursive merge of mappings. "nested sections such as" reads as an
illustration rather than an exhaustive list, and the recursive rule reproduces
option 1 exactly for every config that does not nest below a section.

### Risk: 15

The author most likely merges only the named sections one level deep; the two
readings differ only for a config whose `defaults` reach into `judge_prompt`.

## T23. Order of `__response__` and row-field substitution in a command

### Spec Text

> - `command_template` may reference row fields and `__response__`
> - if a row field such as `{test_code}` expands to text that itself contains
>   `{__response__}`, substitute `__response__` before executing the command

### Alternatives

1. One pass substituting row fields and `__response__` together, then a second
   pass that substitutes only `__response__` in whatever the first pass
   produced - including text the response itself contributed.
2. Row fields expand first, leaving `{__response__}` untouched; a second pass
   then substitutes `__response__` everywhere, so response text is inserted last
   and is never rescanned.

### Choice

Option 2. Both satisfy the stated rule, but only option 2 guarantees that a
generated response containing the literal text `{__response__}` or `{answer}`
is passed to the shell as written instead of being substituted again.

### Risk: 10

A fixture would have to put placeholder-looking text inside the model's own
response for the readings to diverge.

## T24. What counts as an answer choice for `letter`

### Spec Text

> - `letter`: extract the first uppercase answer choice `A` through `D`; accept
>   forms such as `A`, `(A)`, `A)`, or `Answer: A`

### Alternatives

1. The first `A`-`D` character anywhere in the response, even inside a word -
   so "Because..." extracts `B`.
2. The first `A`-`D` that stands alone, i.e. is not surrounded by other letters,
   so punctuation and whitespace delimit it but "Because" does not match.

### Choice

Option 2 (`(?<![A-Za-z])[A-D](?![A-Za-z])`). All four accepted forms match, and
the spec's own example - "The answer is B) Paris" - needs the `A` of "answer"
to be skipped, which only a boundary-aware reading guarantees.

### Risk: 25

The author may well scan for the first bare `[A-D]` with a simpler pattern that
also fires inside capitalised words; prose like "Definitely B" would then yield
`D` where this implementation yields `B`.

## T25. Sampling parameters for the judge request

### Spec Text

> - the judge request is a separate API call through the same server
> - if `evaluation.model` is omitted, use the task's model

### Alternatives

1. The judge call reuses the task's `generation` block verbatim, including a
   `temperature` of 0.7 or 0.8 for a rejection task.
2. The judge call reuses `max_tokens` but scores at `temperature: 0`, since a
   judge is asked for a verdict rather than for a sample.

### Choice

Option 2. The spec gives the judge its own prompt, model and extract method but
no generation block, and scoring is meant to be reproducible. The spec's own
`review` task is `greedy`, so both readings send the same request for it.

### Risk: 30

The author most likely reuses the task's `temperature` for the judge call; a
fixture asserting the judge request body of a `rejection` task would differ.

## T26. Where `judge_meta` goes for a multi-attempt row

### Spec Text

> - `meta` includes a `judge_meta` object with the judge request's token usage,
>   latency, model, and finish reason

> `meta` is a single metadata object for one-attempt rows, a list per attempt
> otherwise

### Alternatives

1. One `judge_meta` per row, describing the judge call that decided the row, and
   for a rejection row placed on the kept attempt only.
2. Each attempt that was judged carries its own `judge_meta` inside that
   attempt's metadata object.

### Choice

Option 2. Under rejection each attempt costs its own judge call, and attaching
each call's metadata to the attempt it scored keeps `meta` a faithful record of
the requests that were made. For one-attempt rows - the spec's example - both
readings produce the same object.

### Risk: 30

If the author records only the deciding judge call, a rejection row that needed
three attempts would carry one `judge_meta` where this implementation carries
three.

## T27. A judge reply that yields no number

### Spec Text

> - score `>= threshold` passes
> - `result` includes `judge_score`, and `result.extracted_answer` is the text
>   `extract` took from the judge's reply (`"8"` for a score of `8`)

### Alternatives

1. An unparseable or missing judge reply scores `0`, which then fails any
   positive threshold.
2. There is no score: `judge_score` is `null`, `passed` is `false`.

### Choice

Option 2, which also covers a judge call whose HTTP requests were exhausted.
A `judge_score` of `0` would claim the judge returned a verdict it never gave,
and the row fails either way.

### Risk: 25

The author may coerce a failed parse to `0`; `passed` agrees under both
readings, so only a fixture asserting `judge_score` itself would differ.

## T28. Whether `judge_score` appears on rows that are not judged

### Spec Text

> - `result` includes `judge_score`

### Alternatives

1. `judge_score` is part of the `result` shape for every row, `null` when the
   task does not use `llm_judge`.
2. Only rows of an `llm_judge` task carry the key.

### Choice

Option 2. The sentence sits in the `llm_judge` section, and Part 1 fixed the
`result` shape for the other evaluation types; adding a key to them would change
behaviour the spec says is unchanged.

### Risk: 20

An author who assembles one `result` dict for all types would emit
`judge_score: null` on every row.

## T29. Token totals in a multi-task summary

### Spec Text

> ```json
> {
>   "total": 200,
>   "passed": 170,
>   "failed": 30,
>   "total_api_calls": 350,
>   "elapsed_seconds": 45.2,
>   "throughput_rpm": 464.6,
>   "tasks": { ... }
> }
> ```

### Alternatives

1. The example is exhaustive: a multi-task summary drops Part 1's
   `total_prompt_tokens` and `total_completion_tokens`.
2. The example is abbreviated: the top level keeps every Part 1 key and gains
   `tasks`.

### Choice

Option 2. "Existing behavior from Part 1 is unchanged unless stated here", and
the spec states only that a `tasks` object is added. Per-task objects are kept
to the four keys the example shows.

### Risk: 25

If the author's multi-task summary is built by a separate code path that mirrors
the example literally, a strict key-set comparison would see two extra keys.

## T30. Whether `rpm` is a per-task or a run-wide budget

### Spec Text

> - requests from different tasks may run concurrently and may be interleaved

> ```yaml
> defaults:
>   rpm: 60
> ```

### Alternatives

1. `rpm` is a run-wide budget shared by every task, so three tasks at `rpm: 60`
   still issue 60 requests per minute in total.
2. `rpm` is a task setting like `model`, so each task paces itself and the run
   may issue `rpm` per selected task.

### Choice

Option 2. `rpm` sits beside `model` and `api_url` in `defaults` and may be
overridden per task, which only makes sense if it describes one task's budget;
a task's pacing then does not depend on which other tasks were selected.

### Risk: 30

The author may well construct one rate limiter for the whole run; a throughput
fixture over several tasks would then expect roughly `rpm` overall rather than
`rpm` per task.

## T31. Which CLI overrides reach which tasks

### Spec Text

> - `--eval-model <string>`: override the judge model for all selected
>   `llm_judge` tasks

### Alternatives

1. Part 1's `--model`, `--rpm`, `--scheme` and friends are meaningless for
   multi-task configs and should be rejected there.
2. They keep working and apply to every selected task, the way `--eval-model`
   applies to every selected judge task.

### Choice

Option 2. The spec lists `--task` and `--eval-model` as the only new flags and
changes nothing else about the existing ones; rejecting them would be new
behaviour the spec does not ask for.

### Risk: 15

Only a fixture that passes a Part 1 override to a multi-task config would show
the difference.

## T32. What "ignore unselected tasks for validation" covers

### Spec Text

> - when `--task` is present, require input only for selected tasks and ignore
>   unselected tasks for validation and execution

### Alternatives

1. Only input validation is relaxed; every task in the file is still checked for
   required config fields, so a broken unselected task fails the run.
2. Unselected tasks are skipped entirely: their bodies are never validated.

### Choice

Option 2, the broader reading of "ignore ... for validation". It behaves
identically for any config whose tasks are all well formed, and it lets a run
proceed while a sibling task in the same file is still being written.

### Risk: 20

The author probably parses every task up front and would reject a config with a
malformed unselected task.

## T33. `--input` forms for a single-task config

### Spec Text

> - for single-task configs, `--input <path>` without `=` still behaves as in
>   Part 1

### Alternatives

1. A single-task config also accepts `name=path`, splitting on the first `=`.
2. The whole `--input` value is the path for single-task configs, and giving
   `--input` more than once is an error.

### Choice

Option 2. Part 1 takes the argument as a path, and a path may legitimately
contain `=`; splitting it would corrupt such a path for a format the spec says
is unchanged.

### Risk: 20

The author may split on `=` regardless of config shape, which matters only for
a fixture that passes `task=path` - or a path containing `=` - to a single-task
config.

## T34. What `--output` must already be for a multi-task run

### Spec Text

> - for multi-task configs, `--output` must be a directory
> - write `<output_dir>/<task_name>.jsonl`

### Alternatives

1. The directory must already exist; a missing one is an error.
2. The directory is created when missing, and only an existing non-directory at
   that path is an error, reported before any request is sent.

### Choice

Option 2. Part 1 creates its output file rather than demanding it exist, so
creating the output directory is the consistent behaviour, and the example
`--output results/` reads as "put results here".

### Risk: 25

If the author requires an existing directory, a fixture that points `--output`
at a fresh path would expect exit code 1 where this implementation succeeds.

## T35. Task names that the config does not define

### Spec Text

> - `--task <name>`: repeatable; run only the selected task or tasks

> ```bash
> --input gsm8k=math.jsonl --input mmlu=qa.jsonl
> ```

### Alternatives

1. A `--task` or `--input` naming an unknown task is silently ignored.
2. It is a configuration error: exit 1 with a message naming the task.

### Choice

Option 2. A mistyped task name otherwise produces a run that quietly does less
than the user asked for - and for `--task` alone it could select nothing at all.
An `--input` entry for a task that exists but was not selected is still ignored,
as the selection rules require.

### Risk: 30

An implementation that intersects the requested names with the configured ones
would ignore the unknown name instead of failing.

## T36. `result.extracted_answer` for a `script` row

### Spec Text

> ```yaml
> evaluation:
>   type: "script"
>   command_template: "python3 -c \"{test_code}\""
>   success_exit_code: 0
> ```

### Alternatives

1. `extracted_answer` is `null`: a script verdict comes from an exit code, and
   nothing was extracted.
2. `extracted_answer` is what `extract` takes from the response, exactly as it
   is for `contains` and `regex` rows, whose verdicts also ignore it.

### Choice

Option 2, following the Part 1 decision recorded in T4: `extract` describes the
response, and the field is filled in whenever a response exists.

### Risk: 30

The author may leave `extracted_answer` null for script rows, since the script
never looks at an extracted answer.

## T37. A `script` command that outlives its timeout

### Spec Text

> - command timeout is 10 seconds; timeout is a failed evaluation

### Alternatives

1. The timeout aborts the row or the run with an error.
2. The command is killed and the attempt is treated like any other failed
   evaluation, so a rejection task goes on to its next attempt.

### Choice

Option 2, stated by the spec. The process is killed and reaped so a timed-out
command cannot outlive the run.

### Risk: 10

The reading is explicit; only the fate of the child process is unstated.

## T38. Which fields the list-format `result` object carries

### Spec Text

> ```json
> "result": {
>   "passed": 2,
>   "failed": 5,
>   "attempts": 7
> }
> ```

> - `result.passed` is the count of passing solutions
> - `result.failed` is the count of failed attempts
> - `result.attempts` is the total number of generation attempts for the row

### Alternatives

1. The list format's `result` holds exactly the three documented counts:
   `extracted_answer` (and `judge_score` for judged tasks) disappear, because a
   row with several solutions has no single extracted answer.
2. Part 1's fields are additive: `result` keeps `extracted_answer` and
   `judge_score` alongside the counts, taken from the last kept solution, or as
   a list parallel to `output`.

### Choice

Option 1. The spec prints the whole `result` object for the new format and lists
exactly three rules for it, where Part 2 spelled out `extracted_answer` in the
same place. The per-solution facts that remain interesting - the setup and the
verdict - are already carried by `output` and `meta`.

### Risk: 25

The author may keep `extracted_answer` in `result` for judged or extracted
tasks, since dropping it loses information Part 1 rows had.

## T39. The default `icl.strategy`

### Spec Text

> - `icl.strategy` is one of `fixed`, `random`, or `round_robin`

### Alternatives

1. `strategy` is required whenever `icl` is present.
2. It is optional and defaults to `fixed`, the first listed value and the only
   one that needs no state.
3. It is optional and defaults to `round_robin`, which uses every setup.

### Choice

Option 2. `k` is explicitly optional, so the section is clearly meant to work
with only `setups` given, and a deterministic default matches the way the rest
of the spec defaults (`scheme: greedy`, `n: 1`) to the simplest behaviour.

### Risk: 15

The author could default to `round_robin` on the grounds that declaring several
setups implies wanting to use them all.

## T40. Whether the round-robin cursor is per row or per task

### Spec Text

> Round-robin order with setups `[A, B, C]`:
>
> - attempt 1 uses `A`
> - attempt 2 uses `B`
> ...
> - attempt 5 uses `B`

### Alternatives

1. The cursor is per input row: every row starts at the first setup, so the
   sequence above describes one row's attempts.
2. The cursor is shared by the whole task: row 2 continues where row 1 stopped,
   so a row's first attempt depends on how many attempts earlier rows made.

### Choice

Option 1. The example counts "attempts", which is a per-row quantity everywhere
else in the spec (`result.attempts`), and a shared cursor makes a row's prompts
depend on the concurrency schedule, which the spec otherwise takes care to keep
deterministic.

### Risk: 20

A task-wide counter is a plausible implementation, and with one row per test
fixture the two readings agree.

## T41. `greedy` with `num_solutions > 1` and no ICL

### Spec Text

> - `greedy` with ICL: generate at temperature `0` once per selected setup and
>   stop when `num_solutions` solutions are collected or all setups are
>   exhausted; because the same setup is deterministic, the maximum number of
>   produced solutions is the number of available setups

> - `sample` without ICL: make `num_solutions` independent sampled requests

### Alternatives

1. Greedy without ICL has exactly one prompt, so it makes one attempt and
   produces at most one solution, by the same determinism argument the spec uses
   to cap greedy at the number of setups.
2. Greedy mirrors `sample` without ICL and makes `num_solutions` identical
   requests, producing `num_solutions` identical solutions.

### Choice

Option 1. The spec gives a rule for `sample` without ICL but deliberately omits
one for greedy, and the reason it gives for the greedy cap - repeating a
deterministic prompt cannot yield anything new - applies with even more force
when there are no setups to vary.

### Risk: 35

The author may simply loop `num_solutions` times for every scheme and let greedy
emit duplicates; the row would then hold identical solutions instead of one.

## T42. What a list-format row contributes to the summary's `passed`

### Spec Text

> - `passed`: rows where `result.passed` is true

> - `result.passed` is the count of passing solutions

### Alternatives

1. A row counts as passed when `result.passed > 0`, i.e. it produced at least
   one passing solution.
2. A row counts as passed only when it collected every requested solution
   (`result.passed == num_solutions`).
3. The summary's `passed` becomes a solution count rather than a row count.

### Choice

Option 1. `total`, `passed` and `failed` have always partitioned input rows
(`passed + failed == total`), and the Part 1 rule "true" generalises most
naturally to "produced something that passed". Solution volume is reported
separately by `total_solutions`.

### Risk: 30

The author may treat a partial result as a failed row, or may not have revisited
the summary rule at all and left `result.passed` (an int) failing an `is True`
test, which would count every multi-solution row as failed.

## T43. Where `total_solutions` and `avg_solutions_per_input` appear

### Spec Text

> Per-task summary fields gain:
>
> ```json
> {
>   "tasks": {
>     "gsm8k": {
>       "total": 100,
>       "total_solutions": 450,
>       "avg_solutions_per_input": 4.5,
>       "total_api_calls": 850
>     }
>   }
> }
> ```

### Alternatives

1. Only the per-task entries gain the fields; the top-level summary keeps its
   Part 1 keys, so a single-task config's summary is unchanged.
2. The top-level summary gains them too, aggregated over every task that ran.

### Choice

Option 1, which is what the heading and the quoted shape say, and which keeps
the promise that "existing behavior from earlier parts is unchanged unless
stated here" for single-task runs.

### Risk: 35

If the author computes the counts in the function that builds both objects, the
fields appear at the top level as well.

## T44. `k` larger than the number of examples in a setup

### Spec Text

> - `icl.k` defaults to all examples in the selected setup
> - if `k` is smaller than the number of examples in the setup, use the first
>   `k`

### Alternatives

1. A `k` larger than the setup uses every example it has.
2. It is a configuration error, since the setup cannot supply `k`
   demonstrations.

### Choice

Option 1. The spec's own file example sets `k: 3` against a setup whose file is
shown with a single line, so over-large `k` is clearly expected to work.

### Risk: 5

## T45. `greedy` with ICL and `num_solutions == 1`

### Spec Text

> - for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
>   strategy and instead walks setups in declared order, at most once per setup

### Alternatives

1. The carve-out is conditioned on `num_solutions > 1`, so a single-solution
   greedy row picks its setup with the configured strategy - which matters only
   for `random`.
2. Greedy always walks the declared order, so a single-solution greedy row
   always uses the first setup.

### Choice

Option 1, reading the condition as written. `fixed` and `round_robin` pick the
first setup for a first attempt anyway, so the two readings differ only when
`random` is configured.

### Risk: 20

The author may implement the greedy walk without re-checking `num_solutions`,
making `random` ineffective for greedy.

## T46. Whether evaluation gates the solutions greedy collects

### Spec Text

> - `greedy` with ICL: generate at temperature `0` once per selected setup and
>   stop when `num_solutions` solutions are collected or all setups are
>   exhausted

> - `sample` with ICL: make one sampled generation per requested solution using
>   the chosen ICL strategy; evaluation does not gate whether a solution is
>   included

### Alternatives

1. A "solution" is any response the API produced: greedy keeps failing
   responses too, exactly as `sample` does, and only an attempt that produced no
   text (all retries exhausted) fails to count.
2. Greedy collects only passing responses, so a setup whose answer fails
   evaluation does not count towards `num_solutions` and the walk continues.

### Choice

Option 1. The spec says evaluation gates inclusion only for `rejection`, and it
makes the point explicitly for `sample`; nothing suggests greedy is stricter
than sampling. Evaluation still runs, so `meta.evaluation_passed` and
`result.passed` report the verdicts.

### Risk: 20

The author may count only passing greedy responses as collected solutions, which
changes the output list of a greedy ICL row whose answers fail.

## T47. `generation.n` once `num_solutions > 1`

### Spec Text

> - `max_attempts` applies to rejection sampling in this part
> - legacy compatibility: when `num_solutions == 1` and no ICL is configured,
>   keep the Part 1 rejection behavior (`generation.n` logical attempts) and do
>   not apply `max_attempts`

### Alternatives

1. `n` is a legacy-mode budget only: outside legacy mode `max_attempts` is the
   only cap, and a configured `n` is ignored.
2. Both caps apply, so attempts stop at `min(n, max_attempts)`.

### Choice

Option 1. The two sentences pair one budget with one mode, and the spec's own
example carries `n: 5` next to `max_attempts: 15` with `num_solutions: 5` - a
task that would stop after five attempts under option 2, making `max_attempts`
meaningless.

### Risk: 15

Option 2 would make the example config behave very differently, so the author
almost certainly ignores `n` here.

## T48. `max_attempts` for schemes other than rejection

### Spec Text

> - `max_attempts` applies to rejection sampling in this part

### Alternatives

1. `max_attempts` is accepted but unused by `greedy` and `sample`, whose attempt
   counts follow their own rules.
2. It caps every scheme, so a `sample` task with `num_solutions: 3` and
   `max_attempts: 1` makes one request.

### Choice

Option 1, stated by the spec: "applies to rejection sampling in this part".

### Risk: 10

The phrase is explicit; only an implementation that caps a shared attempt loop
would differ.

## T49. `rejection` with ICL and `num_solutions == 1`

### Spec Text

> - legacy compatibility: when `num_solutions == 1` and no ICL is configured,
>   keep the Part 1 rejection behavior (`generation.n` logical attempts) and do
>   not apply `max_attempts`

### Alternatives

1. Both conditions must hold: with ICL configured, a single-solution rejection
   task uses `max_attempts` (defaulting to `3 * 1 = 3`), not `n`.
2. `num_solutions == 1` alone is enough to keep Part 1 behaviour, and ICL only
   changes the prompt and the output shape.

### Choice

Option 1, reading the conjunction as written and consistently with the output
rule, which also switches format as soon as ICL is configured.

### Risk: 15

A task with `n: 5` and ICL would make five attempts under option 2 and three
under this choice.

## T50. Rounding `avg_solutions_per_input`

### Spec Text

> ```json
> "total_solutions": 450,
> "avg_solutions_per_input": 4.5,
> ```

### Alternatives

1. Round to two decimal places, as `4.5` shows and as `elapsed_seconds` and
   `throughput_rpm` are rounded (to one) elsewhere.
2. Emit the raw quotient, so a task averaging 7/3 solutions reports
   `2.3333333333333335`.

### Choice

Option 1 with two decimals: the summary's other derived numbers are all rounded,
and two places keep the value readable without losing a meaningful average. A
task with no rows reports `0.0`.

### Risk: 20

The author may divide without rounding, which differs only for averages that are
not exact to two places.

## T51. An ICL example that the user template cannot render

### Spec Text

> - each example's `input` is rendered with the task's `prompt.user` template

### Alternatives

1. A missing field is a configuration error, reported before any request is
   sent, like the per-row field check of Part 1.
2. It is left to fail at render time, aborting the run with a traceback.

### Choice

Option 1, mirroring the existing rule that rows missing a template field fail
before the first request. The message names the setup, the example index and the
missing field.

### Risk: 15

The author may not validate example inputs at all; the difference shows only on
a config whose examples do not match the template.

## T52. Setups with no examples, and repeated setup names

### Spec Text

> - each setup has a `name` and exactly one of `examples` or `file`
> - file-backed setups must be valid JSONL where each non-empty line has
>   `{"input": <object>, "output": <string>}`

### Alternatives

1. Only the stated rules are enforced: an empty `examples` list or a file of
   blank lines is a setup with no demonstrations, and two setups may share a
   name.
2. Empty setups and duplicate names are additional configuration errors.

### Choice

Option 1. The spec enumerates exactly which shapes terminate the run, and an
empty example file is vacuously "valid JSONL"; inventing further errors would
reject configs the spec accepts.

### Risk: 10

An author who rejects empty setups would exit 1 where this implementation runs a
zero-shot prompt.

## T53. `generation.temperature` under the `agentic` scheme

### Spec Text

> ```yaml
>     generation:
>       scheme: "agentic"
>       max_iterations: 10
>       temperature: 0.0
> ```

### Alternatives

1. `agentic` inherits the part 1 rule that a non-`greedy` scheme needs
   `temperature > 0`, so the spec's own example is a configuration error.
2. `agentic` is exempt: the configured temperature is sent as written, and
   `0.0` is legal.
3. `agentic` is forced to `0.0` like `greedy`, ignoring any configured value.

### Choice

Option 2. The spec's only agentic example configures `temperature: 0.0`, so the
`> 0` rule cannot apply, and nothing says agentic is deterministic the way
`greedy` is - `num_solutions > 1` with agentic only makes sense if a non-zero
temperature reaches the API.

### Risk: 10

An author who forces `0.0` differs only for an agentic task that asks for a
positive temperature.

## T54. The default `max_iterations`

### Spec Text

> - `max_iterations: 10`
> 5. If `max_iterations` is reached first, output `null` and use
>    `finish_reason: "max_iterations"`.

### Alternatives

1. `max_iterations` is required for an agentic task; omitting it is an error.
2. It defaults to the value used in the spec's example, `10`.
3. It defaults to something else (1, 3, unlimited).

### Choice

Option 2. The loop needs a bound for rule 5 to be implementable, and `10` is the
only number the spec ever associates with it. Making the key required would
reject configs the spec never says are invalid.

### Risk: 20

An author who requires the key exits 1 where this implementation runs with ten
iterations; one who defaults to a different number diverges only for a config
that omits it.

## T55. Whether `iterations_detail` entries carry the task's `model`

### Spec Text

> ```json
>     "iterations_detail": [
>       {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230, "latency_ms": 300, "finish_reason": "tool_calls"},
> ```

### Alternatives

1. Each entry holds exactly the five documented keys.
2. Each entry is the part 1 `meta` object, which also carries `model`, since it
   describes one API request just like a part 1 attempt.

### Choice

Option 1, and likewise the aggregated agentic `meta` holds exactly the six keys
the example shows. The example is written out in full twice and never mentions
`model`, so the documented shape is the specified one.

### Risk: 25

An author who reuses the part 1 per-attempt metadata builder would emit `model`
as well; that only matters to a test comparing the whole object.

## T56. Where a loop's `iterations` and `tool_calls` go in the list format

### Spec Text

> - in that list format, `result.attempts` is the number of loops started for
>   the row, not the number of API requests across those loops
> - in that list format, per-loop agentic metadata lives in each `meta` entry:
>   keep checkpoint 3's `icl_setup` / `evaluation_passed` fields and also record
>   that loop's aggregated `total_prompt_tokens`,
>   `total_completion_tokens`, `total_tokens`, `latency_ms`,
>   `finish_reason`, and `iterations_detail`

### Alternatives

1. The enumeration is exhaustive: the list format keeps checkpoint 3's
   `passed`/`failed`/`attempts` result and adds only the six listed metadata
   fields, so per-loop `iterations` and `tool_calls` are not written anywhere.
2. `iterations` and `tool_calls` are also added to each `meta` entry, since a
   list-format row otherwise loses information the single format records.
3. `result` grows list-valued `iterations`/`tool_calls` fields.

### Choice

Option 1. The sentence enumerates the metadata fields explicitly and the example
run ("`meta` is a list with two entries, one aggregated agentic metadata object
per loop") re-states the same set; T38 already fixed the list-format `result` to
exactly three counts.

### Risk: 35

An author who builds the per-loop metadata by dumping their whole loop record
would include `iterations` and `tool_calls` in each `meta` entry - the most
likely divergence here.

## T57. `meta.finish_reason` when the final response did not stop cleanly

### Spec Text

> - `meta.finish_reason` is `"stop"` for a final text response and
>   `"max_iterations"` when the iteration limit is hit

### Alternatives

1. Literally `"stop"` whenever the loop ended with text, whatever the API
   reported for that request.
2. The last iteration's own `finish_reason`, which is `"stop"` in the normal
   case but `"length"` when the final answer was truncated.

### Choice

Option 2. Part 1 already passes the API's `finish_reason` through unchanged, and
`iterations_detail` records the per-request value anyway; rewriting a `"length"`
ending as `"stop"` would hide a truncated answer. The spec's sentence reads as a
description of the normal case rather than a mapping table.

### Risk: 20

An author who hard-codes `"stop"` differs only when the final request reports
something else.

## T58. An API request inside the loop that never succeeds

### Spec Text

> 3. If the response contains `tool_calls`, execute every tool call ...
> 4. If the response contains final text and no tool calls, stop and use that
>    text as the output.
> 5. If `max_iterations` is reached first, output `null` and use
>    `finish_reason: "max_iterations"`.

### Alternatives

1. A request whose retries are exhausted ends the loop with no output, and
   `meta.finish_reason` stays whatever that failed request reported (`null`).
2. The failed request is skipped and the loop retries from the same
   conversation until `max_iterations`.
3. The failure is reported as `"max_iterations"`.

### Choice

Option 1. Part 1 treats an exhausted request as a finished, failed attempt, and
the loop has nothing to append to the conversation after one. The row then looks
like any other row with no output: `output: null` and a failing evaluation, but
not the `"max_iterations"` label, which the spec ties specifically to the
iteration limit.

### Risk: 30

An author who labels every empty agentic output `"max_iterations"` would differ
on a row whose API requests all failed.

## T59. `static_map`'s key when `required` does not name one

### Spec Text

> - `static_map`: look up the first required parameter in `mapping`; if absent,
>   return `default`, which defaults to `"NOT_FOUND"`

### Alternatives

1. `parameters.required[0]` names the argument; a tool with no `required` entry
   is a configuration error.
2. `parameters.required[0]` names it when present, otherwise the first argument
   the model actually passed is used.
3. Always use the first argument the model passed.

### Choice

Option 2. `required[0]` is what the spec says, and falling back to the first
supplied argument keeps a tool whose schema omits `required` working instead of
inventing a config error the spec never lists. "if absent" is read as "the
looked-up value is not a key of `mapping`", which also covers the model omitting
the argument entirely.

### Risk: 15

Only a tool definition without a `required` list can distinguish these.

## T60. Trailing whitespace in a `script` handler's stdout

### Spec Text

> - `script`: run `command` with the value of `arg_field` as a single
>   command-line argument, capture stdout, and return it

### Alternatives

1. Return stdout verbatim, so `print(42)` yields `"42\n"`.
2. Return stdout with surrounding whitespace stripped, so it yields `"42"`.

### Choice

Option 2. The result is fed back to the model as a tool message and compared in
tests as a value; a trailing newline is an artefact of the subprocess, not part
of the answer. The sibling handlers (`echo`, `static_map`) both return clean
values, so stripping keeps them consistent.

### Risk: 30

An author who returns `stdout.decode()` unchanged would record `"42\n"` where
this implementation records `"42"`.

## T61. The `script` handler's timeout and its error text

### Spec Text

> on timeout or non-zero exit, return `"ERROR: <stderr or timeout message>"`

### Alternatives

1. Reuse the 10-second timeout the part 2 `script` evaluation already uses, and
   word the messages freely.
2. Pick a different timeout, or make it configurable through the handler.

### Choice

Option 1: a 10-second limit, `"ERROR: " + stderr` for a non-zero exit and
`"ERROR: timeout after 10s"` for a timeout. The spec gives no new number and the
tool already had one for running commands; the `<...>` placeholder shows the
message text itself is not fixed.

### Risk: 25

The exact timeout string is unspecified, so a test asserting on the author's
wording would fail; a test asserting the `"ERROR: "` prefix passes either way.

## T62. Tool calls the task cannot serve

### Spec Text

> - parse `function.arguments` as JSON before invoking the handler

### Alternatives

1. An unknown tool name or unparseable `arguments` aborts the row.
2. Both are recorded as ordinary tool calls whose `result` is an `ERROR: ...`
   string, and the loop continues so the model can recover.

### Choice

Option 2, matching the handler rules, where every documented failure (missing
key, failing script) is reported back to the model as a string rather than
ending the run. Unparseable arguments are recorded as `{}`.

### Risk: 30

The spec never says what a bad tool call does; an author who raises would
produce a row with no output where this one keeps looping.

## T63. Where each built-in template's generation prompt ends

### Spec Text

> `llama3`
>
> ```text
> <|begin_of_text|><|start_header_id|>system<|end_header_id|>
>
> {system_content}<|eot_id|><|start_header_id|>user<|end_header_id|>
>
> {user_content}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
> ```

### Alternatives

1. The fenced block is exact down to whitespace: every template ends with a
   single newline after the final role marker (`[/INST]\n` for mistral).
2. Each template ends the way that model family's own chat template ends:
   `<|im_start|>assistant\n`, `<|start_header_id|>assistant<|end_header_id|>\n\n`,
   `[/INST]` with nothing after it, and `<|assistant|>\n`.

### Choice

Option 2. Within the llama3 block every `<|end_header_id|>` is followed by a
blank line, so ending the generation prompt with a single newline would be
inconsistent with the template's own rule; the same reasoning makes mistral's
`[/INST]` terminal, since a fenced block always ends in a newline whether or not
the string does. These are also the strings a server actually expects.

### Risk: 40

An author who stored the fenced blocks verbatim would emit `...<|end_header_id|>\n`
for llama3 and `...[/INST]\n` for mistral - the reading most likely to differ,
and visible to any test that compares a rendered prompt exactly.

## T64. Mistral's system message and multi-turn shape

### Spec Text

> ```text
> [INST] {system_content}
>
> {user_content} [/INST]
> ```
>
> - built-in templates must handle multi-turn conversations by repeating the
>   correct role markers for every message

### Alternatives

1. The system text opens the first `[INST]` block, later user turns get their
   own `[INST] ... [/INST]`, and assistant turns are appended followed by
   `</s>` - the mistral convention the single-turn block is an instance of.
2. The system text is repeated in every `[INST]` block.
3. Mistral gets an invented `<<SYS>>` marker so system content has its own slot.

### Choice

Option 1. It reproduces the spec's block exactly for a one-turn conversation and
is the only reading where "repeating the correct role markers" has a meaning for
a format with no system marker.

### Risk: 30

Multi-turn mistral is the least constrained of the four templates; an author
who repeats the system block or separates it differently diverges on any ICL or
agentic conversation.

## T65. The tool-role formatting of each built-in template

### Spec Text

> - execute those calls and feed the results back into the next prompt
>   iteration using the template's tool-role formatting

### Alternatives

1. Each template gains a `tool` role that reuses its own role markers:
   `<|im_start|>tool`, `<|start_header_id|>tool<|end_header_id|>`, `<|tool|>`,
   and `[TOOL_RESULTS] ... [/TOOL_RESULTS]` for mistral.
2. Tool results are fed back as ordinary user turns, since none of the four
   blocks shows a tool marker.
3. Llama 3's `ipython` role name is used instead of `tool`.

### Choice

Option 1. The spec calls it "the template's tool-role formatting", which implies
the template has a tool role; deriving it from the same marker pattern as the
other roles is the only construction the four blocks actually support.

### Risk: 35

Nothing in the spec pins these strings down. A test that only checks the handler
result reaches the next prompt passes under any of the readings; one that
asserts the marker does not.

## T66. How tool definitions are rendered into a completions prompt

### Spec Text

> - tool definitions are rendered into the prompt instead of being sent as a
>   native `tools` field

### Alternatives

1. Append a tools section to the system message: each tool as a JSON object plus
   an instruction describing the `<tool_call>` block the model should emit.
2. Send the JSON tool array as a separate leading turn.
3. Render nothing beyond the names.

### Choice

Option 1. The spec fixes the response syntax the model must produce, so the
prompt has to state both the available tools and that syntax, and the system
message is where the task's own instructions already live - it survives ICL
turns being inserted after it.

### Risk: 30

The wording is free; a test can only reasonably check that the tool names,
descriptions and `<tool_call>` syntax reach the prompt and that no `tools` field
is sent, which holds for any of these.

## T67. Defaults for `api_type` and `chat_template`

### Spec Text

> ```yaml
> defaults:
>   api_type: "completions"
>   chat_template: "llama3"
> ```
>
> - `--api-type <chat|completions>`
> - `--chat-template <chatml|llama3|mistral|zephyr>`

### Alternatives

1. `api_type` defaults to `chat` (every earlier checkpoint's behaviour) and
   `chat_template` defaults to `chatml`, the first template listed.
2. `chat_template` is required whenever `api_type` is `completions`.

### Choice

Option 1. "Existing behavior from earlier parts is unchanged unless stated
here", so a config that mentions neither key must still send chat requests, and
a `completions` config without a template needs some default; `chatml` is the
first one the CLI lists and the most generic.

### Risk: 25

An author who requires `chat_template` in completions mode would exit 1 where
this implementation renders ChatML.

## T68. The shape of the tool result message in chat mode

### Spec Text

> - parse `function.arguments` as JSON before invoking the handler
> ```json
> {"id": "call_abc123", "type": "function", "function": {"name": "lookup", ...}}
> ```

### Alternatives

1. `{"role": "tool", "tool_call_id": <id>, "content": <result>}` - the current
   OpenAI shape.
2. The same plus `"name": <tool name>`, the older function-calling shape.
3. One combined tool message carrying every result of the iteration.

### Choice

Option 1. The spec calls the request/response shape "the normal OpenAI shape",
and "append ... the tool result messages" (plural) rules out combining them.

### Risk: 20

Adding `name` is harmless to a test that reads `content`, and only shows up in a
test comparing the whole message.

## T69. Whether the loops of one row overlap

### Spec Text

> - `agentic` also works with ICL and `num_solutions`; each solution is an
>   independent loop
> - a single agentic run may span many API requests, but other inputs must still
>   be able to make progress concurrently

### Alternatives

1. The loops of one row run one after another, as the earlier schemes run their
   attempts; concurrency is between rows.
2. All `num_solutions` loops of a row run concurrently.

### Choice

Option 1. The concurrency requirement is written about inputs ("other inputs",
"three input rows"), and part 2's schemes already sequence a row's attempts;
keeping that makes `icl_setup` assignment and output order deterministic.

### Risk: 15

Only observable as timing, or as request arrival order on a single-row run.
