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
