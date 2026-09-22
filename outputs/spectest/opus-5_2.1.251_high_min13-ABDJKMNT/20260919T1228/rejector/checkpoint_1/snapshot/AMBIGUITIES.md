# Ambiguities

Numbered record of spec under-specification, the interpretation chosen, and
the estimated chance the spec author's own implementation differs.

## T1: How many HTTP calls a 5xx-failing request gets

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 times. After the
> third failure, treat that row as failed, emit `null` output for it, count it
> as failed in the summary, and continue.

### Alternatives
1. 1 initial call + 3 retries = 4 HTTP calls per logical attempt. "Retry up
   to 3 times" is taken literally; "the third failure" is the third retry.
2. 3 HTTP calls total (1 initial + 2 retries), so that "the third failure"
   counts failures including the first one.

### Choice
Interpretation 1: 4 HTTP calls maximum per logical attempt. "Retry it up to
3 times" is the operative, unambiguous instruction; "after the third failure"
reads naturally as the third failed retry ("three strikes"). `total_api_calls`
therefore counts 4 for a row whose server always returns 500.

### Risk: 45
The author may well have written `for attempt in range(3)` and asserted
`total_api_calls == 3` for an always-500 fixture.

## T2: `extracted_answer` for `contains` and `regex` evaluations

### Spec Text
> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output
> - `contains`: response text must contain the `answer_field` value as a
>   substring
> - `regex`: response text must match the configured `pattern`

### Alternatives
1. Always apply the configured `extract` method (default `full`) and report
   its result, even though `contains`/`regex` match against the raw response
   text.
2. Report `null` for `contains`/`regex` since neither performs an extraction.
3. For `regex`, report the matched substring (or group 1).

### Choice
Interpretation 1. `extract` is defined as a property of `evaluation`, not of
`exact_match`, and the field is described unconditionally as "the extracted
comparison value". With no `extract` key the method defaults to `full`, so a
`contains` row reports the whole response text.

### Risk: 40
The author may report the regex match object's text for `regex`, or `null`
for both; `null` for non-`exact_match` types is the most likely alternative.

## T3: Comparison semantics for `exact_match`

### Spec Text
> `exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row

### Alternatives
1. String comparison of the stripped extracted text against `str(answer)`.
2. Numeric comparison when both sides parse as numbers, so `"5.0"` matches
   `"5"` and `"1,000"` matches `"1000"`.

### Choice
Interpretation 1: `str(extracted).strip() == str(expected).strip()`. The spec
says "exact match" and never mentions numeric normalization; the worked
examples (`"8"` vs `8`, `"5"` vs `5`) agree under both readings.

### Risk: 30
A GSM8K-flavoured reference implementation might normalize commas or compare
floats; the most likely alternative is float-equality when both sides parse.

## T4: What `last_number` matches

### Spec Text
> `last_number`: use the last integer or decimal in the response

### Alternatives
1. `-?\d+(?:\.\d+)?` — signed integers and decimals, no thousands separators.
2. Unsigned `\d+(?:\.\d+)?`, so `-5` extracts as `5`.
3. Comma-aware, so `1,000` extracts as `1000` or `1,000`.

### Choice
Interpretation 1. A leading minus is part of "an integer" in ordinary usage,
while comma grouping is a formatting convention the spec never mentions.

### Risk: 25
Most fixtures use plain positive integers where all readings agree; the likely
alternative is an unsigned pattern that drops the sign.

## T5: `meta` for a row whose API calls all failed

### Spec Text
> After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue.
> `meta` is a single metadata object for one-attempt rows

### Alternatives
1. `"meta": null` — there is no successful call to describe.
2. A metadata object with `model` filled in and token/latency fields null.
3. An object carrying an `error` field.

### Choice
Interpretation 1. Metadata fields are all derived from a response that never
arrived, and `output: null` already establishes `null` as this spec's marker
for "nothing to report".

### Risk: 35
The author may still emit a partial object (model plus nulls, or zeros) for
shape consistency.

## T6: `temperature` omitted for `sample` / `rejection`

### Spec Text
> - `sample`: `temperature` must be `> 0`; `n` is ignored
> - `rejection`: `temperature` must be `> 0`

### Alternatives
1. A missing `temperature` is a configuration error (exit 1).
2. A missing `temperature` defaults to something > 0 (e.g. 1.0) and passes.

### Choice
Interpretation 1. "Must be > 0" is phrased as a validation rule on a value the
config is expected to carry, and the config shape lists `temperature`
explicitly, so an absent value has nothing to validate.

### Risk: 30
If the author defaults `temperature` to 1.0 before validating, a `sample`
config without a temperature would succeed in their implementation.

## T7: Matching semantics for `regex`

### Spec Text
> `regex`: response text must match the configured `pattern`

### Alternatives
1. `re.search` — pattern found anywhere in the response.
2. `re.match` — anchored at the start.
3. `re.fullmatch` — must match the whole response.

### Choice
Interpretation 1 (`re.search`). Evaluating model output is a "does the
response contain this shape" check, and anchored readings would make patterns
such as `#### \d+` useless against multi-line responses.

### Risk: 20
`re.match` is the most likely alternative; fixtures that anchor with `^`/`.*`
behave identically under both.

## T8: A rejection attempt that exhausts its HTTP retries

### Spec Text
> `rejection`: ... make up to `n` attempts and keep the first passing
> response; if all attempts fail, output `null` with `"passed": false`
> After the third failure, treat that row as failed, emit `null` output for it

### Alternatives
1. A hard API failure ends the row immediately; `attempts` counts the failed
   attempt, `meta` is `null`.
2. The failed attempt is consumed and the loop continues to the next of `n`.

### Choice
Interpretation 1. "Treat that row as failed ... and continue" is about
continuing with other rows, and it is stated unconditionally for any request
that exhausts its retries.

### Risk: 30
An author whose rejection loop simply treats a failed call as a non-passing
attempt would keep sampling and could emit a passing row where this one fails.

## T9: Concurrency strategy for the `rpm` budget

### Spec Text
> Use the configured `rpm` as the server's approximate request capacity and
> keep enough work in flight to avoid an obviously sequential pipeline.
> Target at least 80% of the configured `rpm`.

### Alternatives
1. Cap in-flight requests (no client-side timing throttle) and let the server's
   internal queue set the pace.
2. Add a token bucket that releases at most `rpm` requests per minute.

### Choice
Interpretation 1, with the in-flight cap set to `rpm` (clamped to 256). The
server "queues requests internally" and "does not return rate-limit errors",
so client-side pacing can only lose throughput against an 80%-of-rpm target.

### Risk: 10
Throughput is asserted as a floor, so any saturating strategy passes; only a
test asserting the client never exceeds `rpm` would prefer a bucket.

## T10: An input row missing the evaluation `answer_field`

### Spec Text
> When the configured evaluation uses `answer_field`, each row must also
> contain that field.
> If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field.

### Alternatives
1. Missing `answer_field` is an input error: exit 1, same message style as a
   missing placeholder, before any request is sent.
2. Only prompt placeholders are validated; a missing answer field just makes
   the row fail evaluation.

### Choice
Interpretation 1. The spec states the requirement in the same paragraph as the
placeholder rule ("must"), and exit code 1 is documented for "input error".

### Risk: 25
The author may only validate templates, in which case such a row would be
processed and scored `passed: false` instead of aborting the run.

## T11: Exit code for CLI usage errors

### Spec Text
> Exit codes:
> - `0`: success
> - `1`: configuration or input error

### Alternatives
1. Missing/invalid flags exit 1 like any other configuration error.
2. Argparse's default exit code 2 for usage errors.

### Choice
Interpretation 1: the parser's error path is overridden to exit 1, since the
spec enumerates only two exit codes and a missing `--config` is a
configuration error.

### Risk: 20
If the author left argparse alone, a test invoking the tool with no flags
would expect 2.

## T12: Summary timings when no request is ever made

### Spec Text
> `elapsed_seconds`: wall-clock time from first request to last response,
> rounded to 1 decimal place
> `throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to 1
> decimal place

### Alternatives
1. An empty input file yields `elapsed_seconds: 0.0` and `throughput_rpm: 0.0`.
2. The run is an error, or throughput is `null`.

### Choice
Interpretation 1: zero rows is a legal run that emits a summary of zeros and
exits 0; the division is guarded rather than raising.

### Risk: 15
An empty-input fixture is unlikely to be tested; `null` throughput is the main
alternative.

## T13: `result.passed` for an API-failed row with no evaluation configured

### Spec Text
> if `evaluation` is omitted for `greedy` or `sample`, `result.passed` must be
> `null`
> `failed`: rows where `result.passed` is `false` or `output` is `null`

### Alternatives
1. `passed` stays `null` even when the row produced no output; the summary
   counts it as failed via the `output is null` clause.
2. `passed` becomes `false` because the row failed.

### Choice
Interpretation 1. The "must be `null`" rule is unconditional for a config
without `evaluation`, and the summary rule is written precisely so that a
`null`-output row is still counted as failed.

### Risk: 25
The author may set `passed: false` on hard failures regardless of evaluation
config, which the summary's `or output is null` clause would make redundant.

## T14: Whether the output file is created when validation fails

### Spec Text
> `--output <path>`: JSONL result file, created or overwritten
> If a placeholder references a missing field, exit with code `1`

### Alternatives
1. Validation (config, input rows, templates) runs before the output file is
   touched, so a failing run leaves no file (and leaves an existing file
   intact).
2. The file is truncated up front and left empty on error.

### Choice
Interpretation 1: nothing is opened for writing until the run is known to be
viable. A truncated-but-untouched file is a worse artifact than none.

### Risk: 15
Only a test asserting the output file exists (and is empty) after an error
would prefer the alternative.

## T15: Defaults for omitted config values

### Spec Text
> ```yaml
> generation:
>   scheme: "greedy"
>   temperature: 0.0
>   max_tokens: 512
>   n: 1
> ```
> `output_field: "solution"`

### Alternatives
1. `scheme` defaults to `greedy`, `max_tokens` to 512, `n` to 1, `extract` to
   `full`, `rpm` to 60, and `prompt.system` is optional; `output_field`,
   `api_url` and `model` are required.
2. Every key shown in the config shape is required.

### Choice
Interpretation 1. The greedy example in the spec omits `temperature` and `n`
entirely, which proves those keys are optional; `output_field` has no sensible
default since the output key is named by it.

### Risk: 20
The author may default `output_field` to something like `"output"` rather than
erroring, or may require `max_tokens`.

## T16: Errors other than HTTP 5xx

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 times.

### Alternatives
1. Connection errors and timeouts are retried on the same budget as 5xx; 4xx
   responses and unparseable bodies fail the attempt immediately.
2. Only 5xx is retried; every other failure fails the attempt at once.

### Choice
Interpretation 1. A dropped connection is the same transient class of failure
as a 5xx, while a 4xx is a deterministic client error that retrying cannot fix.

### Risk: 15
Both readings agree on the fixtures the spec describes (5xx and success); a
test that rejects with a 400 and counts calls would distinguish them.

## T17: Which responses contribute to the token totals

### Spec Text
> ```json
> {
>   "total_prompt_tokens": 4500,
>   "total_completion_tokens": 12000,
>   "total_api_calls": 142,
> ```
> `total_api_calls`: all HTTP requests, including retries and rejection
> attempts

### Alternatives
1. Token totals sum the `usage` of every successful response, including
   rejection attempts that were discarded.
2. Token totals sum only the responses that became a row's `output`.

### Choice
Interpretation 1. The totals sit beside `total_api_calls`, which is explicitly
every request, and the summary reads as a cost/usage report — discarded
rejection samples cost tokens just the same.

### Risk: 15
An author summing only kept responses would report lower totals for rejection
runs; the counts agree for every greedy/sample run.

## T18: `prompt.system` when omitted

### Spec Text
> ```yaml
> prompt:
>   system: "Solve the math problem. Put your final answer after ####."
>   user: "{question}"
> ```

### Alternatives
1. `system` is optional; when absent only the user message is sent.
2. Both keys are required.

### Choice
Interpretation 1: `user` is required, `system` is optional and simply omitted
from `messages`. Sending an empty system message would change model behaviour
for no reason.

### Risk: 20
The author may require `system` (exit 1) or send `{"role": "system",
"content": ""}`; every documented config includes a system prompt.

## T19: Which `elapsed_seconds` the throughput formula divides by

### Spec Text
> `elapsed_seconds`: wall-clock time from first request to last response,
> rounded to 1 decimal place
> `throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to 1
> decimal place

### Alternatives
1. Divide by the reported (rounded) `elapsed_seconds`, so the two summary
   fields are exactly consistent with each other.
2. Divide by the raw unrounded elapsed time, so the rate is more precise but
   does not reproduce from the printed summary.

### Choice
Interpretation 1: the formula is written in terms of the field above it, so
`throughput_rpm` recomputes exactly from the printed summary. A run whose
elapsed time rounds to `0.0` falls back to the raw elapsed time rather than
reporting `0.0`, which would otherwise understate a very fast run.

### Risk: 20
The difference is under 1% for any run lasting more than a few seconds; an
author dividing by the raw value would differ noticeably only on sub-second
runs, where the likely preference is the raw-value reading.
