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
