# Ambiguities

Numbered record of under-specified points in the Part 1 spec, the reading I
chose, and the risk that the spec author's own implementation (and therefore
the hidden tests) reads it differently.

---

## T1: `meta` for a row whose API call fails after all retries

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 total requests. After the
> third failure, treat that row as failed, emit `null` output for it, count it
> as failed in the summary, and continue.

> `meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt

### Alternatives
1. `meta` is `null` — there is no completed API call, so there is no metadata.
2. `meta` is an object with the model filled in and token/finish fields set to
   `null`/`0` plus the measured latency.
3. `meta` is an object carrying an `error` key describing the HTTP failure.

### Choice
`null`. The spec defines every `meta` field in terms of a returned completion
(`prompt_tokens`, `finish_reason`, ...). With no completion there is nothing to
fill them with, and the natural implementation builds `meta` from a response
object it never received. Alternative 3 invents keys the spec never lists.

### Risk: 40
The author most likely prefers: `meta` as a stub object containing at least
`{"model": ..., "finish_reason": null}` rather than `null`.

---

## T2: `meta` shape for a rejection row that passes on the first attempt

### Spec Text
> `meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt

### Alternatives
1. Shape follows the *attempt count*: one attempt -> bare object, even under the
   `rejection` scheme.
2. Shape follows the *scheme*: `rejection` always emits a list (of length 1 when
   it passes immediately), `greedy`/`sample` always emit an object.

### Choice
Alternative 1. The sentence conditions on "one-attempt rows" and on "rejection
sampling with multiple attempts", not on the configured scheme; a rejection row
that succeeds immediately is literally a one-attempt row.

### Risk: 35
The author most likely prefers: always a list for `scheme: rejection`, since
`metas if len(metas) > 1 else metas[0]` and `metas if scheme == "rejection"` are
both one-liners and the latter is easier to consume downstream.

---

## T3: `result.extracted_answer` for `contains` and `regex` evaluations

### Spec Text
> `contains`: response text must contain the `answer_field` value as a substring
> `regex`: response text must match the configured `pattern`
> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output

### Alternatives
1. Always apply the configured `extract` method (defaulting to `full`) and
   report its result, whatever the evaluation type is.
2. Report `null` for `contains`/`regex`, since neither evaluation extracts
   anything: only `exact_match` is described in terms of extraction.
3. For `regex`, report the matched text (or capture group 1); for `contains`,
   report the matched substring.

### Choice
Alternative 1. `extract` is documented as a property of `evaluation` in general,
not of `exact_match`, and "the extracted comparison value" reads as "whatever
the extract step produced". This also keeps one code path for all three types.

### Risk: 45
The author most likely prefers: alternative 3 for `regex` (report the match /
group 1), which is the intuitive thing to surface for a pattern evaluation.

---

## T4: What "match" means for `regex`

### Spec Text
> `regex`: response text must match the configured `pattern`

### Alternatives
1. `re.search` — the pattern occurs anywhere in the response.
2. `re.match` — the pattern matches at the start of the response.
3. `re.fullmatch` — the pattern matches the entire response.

### Choice
`re.search`. Model responses are multi-line prose, and a "the answer must look
like this" pattern is almost always meant to be found inside the response rather
than anchored to it; anchoring is available to the config author via `^`/`$`.

### Risk: 25
The author most likely prefers: `re.search` as well; the main alternative risk
is `re.match` (Python's slightly more "default-looking" call).

---

## T5: Comparison rule for `exact_match`

### Spec Text
> `exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row

### Alternatives
1. Whitespace-stripped string equality of `str(extracted)` and
   `str(row[answer_field])`.
2. Numeric-aware comparison: if both sides parse as numbers, compare
   numerically, so `8` == `8.0` == `8.00`.
3. Normalise further (strip thousands separators, trailing `.0`, case).

### Choice
Alternative 1. "exact_match" names itself: the plainest implementation is a
string comparison, and the spec's own example (`answer: "5"`, extracted `"5"`)
shows strings on both sides. Numeric coercion would make `exact_match` behave
differently from its name on inputs like `"8.0"` vs `"8"`.

### Risk: 30
The author most likely prefers: string equality too, but a fixture with an
answer like `"1,000"` or a response ending in `8.0` would expose numeric
normalisation if their implementation has it.

---

## T6: What `last_number` counts as a number

### Spec Text
> `last_number`: use the last integer or decimal in the response

### Alternatives
1. `-?\d+(?:\.\d+)?` — optional sign, digits, optional fractional part; no
   thousands separators; `.5` is read as `5`.
2. Also accept leading-dot decimals (`.5`) and thousands separators
   (`1,000` -> `1000`).
3. Digits only, no sign (`-3` extracts as `3`).

### Choice
Alternative 1. "integer or decimal" covers `42` and `3.14`, and a leading minus
sign is part of the literal in every ordinary reading. I do not strip commas:
that is normalisation, not extraction, and it would silently change
`#### 1,000` into a different string than the input row's `"1,000"`.

### Risk: 35
The author most likely prefers: a comma-tolerant regex for GSM8K-style data
(their example task is `gsm8k_solve`), where `18,000` is common.

---

## T7: A hard API failure (3 failed requests) during rejection sampling

### Spec Text
> After the third failure, treat that row as failed, emit `null` output for it,
> count it as failed in the summary, and continue.

> `rejection`: ... make up to `n` attempts and keep the first passing response;
> if all attempts fail, output `null` with `"passed": false`

### Alternatives
1. The row is immediately failed: stop attempting, emit `null` output.
2. The dead attempt is consumed like a failing evaluation and sampling proceeds
   to the next attempt; the row only fails if every attempt is used up.

### Choice
Alternative 1. The retry paragraph says "treat that row as failed" without
carving out an exception for rejection, and "continue" in that sentence refers
to continuing with the remaining rows, not the remaining attempts.

### Risk: 30
The author most likely prefers: alternative 2 — a loop over `range(n)` that
`continue`s on a dead attempt is a very natural way to write rejection.

---

## T8: When the missing-field check runs, and whether the output file is written

### Spec Text
> If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field.

> `--output <path>`: JSONL output file, created or overwritten

### Alternatives
1. Validate every row up front, before any API request; exit `1` without
   creating or truncating the output file.
2. Stream rows and fail on the first bad one, after having already issued
   requests for earlier rows and possibly created the output file.

### Choice
Alternative 1. It is an "input error" (exit code 1) in the same class as a bad
config, and failing before spending API budget is the only behaviour that makes
the error message about "row index" useful. The output file is left untouched so
a failed run cannot be mistaken for a partial success.

### Risk: 20
The author most likely prefers: the same up-front validation; the residual risk
is a test asserting the output file exists (empty) after a row-validation error.

---

## T9: Failures that are not HTTP 5xx

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 total requests.

### Alternatives
1. Retry only 5xx; 4xx fails the row immediately; transport errors (connection
   reset, timeout) are retried on the same 3-request budget.
2. Retry anything that is not a 2xx, including 4xx.
3. Retry only 5xx; let transport errors crash the run.

### Choice
Alternative 1. A 4xx is a deterministic client error that will fail identically
on retry, while a dropped connection is exactly the transient condition the
retry rule exists for. Crashing the whole run on one dropped socket contradicts
"treat that row as failed ... and continue".

### Risk: 25
The author most likely prefers: the same split; a test that returns `400` and
expects exactly one API call would agree with this choice, one that counts three
would not.

---

## T10: Whether extracted values are whitespace-stripped

### Spec Text
> `full`: use the entire response text
> `last_line`: use the last non-empty line

### Alternatives
1. Strip surrounding whitespace from every extracted value, including `full`.
2. `full` returns the response text byte-for-byte, including a trailing newline.

### Choice
Alternative 1. `last_line` is already defined in terms of non-empty (i.e.
stripped) lines, so stripping is the house style of the extract step; and an
`exact_match` against a `full` extraction would essentially never pass if a
trailing newline were retained.

### Risk: 30
The author most likely prefers: `full` returning the raw text unchanged, since
"the entire response text" is a literal phrase and `content` often arrives
already trimmed in their fixtures (making both readings agree there).

---

## T11: Defaults for omitted config fields

### Spec Text
> ```yaml
> generation:
>   scheme: "greedy"
>   temperature: 0.0
>   max_tokens: 512
>   n: 1
> ```

### Alternatives
1. Every field shown in the config block is mandatory; omitting any is a
   config error.
2. Only the fields the spec names in validation rules are mandatory
   (`prompt.user`, `api_url`, `model`, `evaluation` for rejection, ...); the
   rest get defaults: `scheme: greedy`, `temperature: 0.0`, `max_tokens: 512`,
   `n: 1`, `rpm: 60`, `extract: full`, `output_field: output`,
   `prompt.system` optional (system message omitted when absent).

### Choice
Alternative 2. The spec's own greedy *example* config omits `temperature` and
`n` and is presented as valid, which rules out alternative 1; the listed
"Validation rules" section is then the authoritative list of what is required.
Defaults are taken from the values shown in the config template.

### Risk: 30
The author most likely prefers: the same permissive defaults, but may require
`output_field` (it has no obvious default) or may omit `max_tokens` from the
request body entirely when it is unset.

---

## T12: `result.passed` when the API call fails but an evaluation is configured

### Spec Text
> `result.passed` is `true` for a passing evaluation, `false` for a failing
> evaluation, and `null` when no evaluation is configured

### Alternatives
1. `false` — the row failed; the summary must count it as failed.
2. `null` — no evaluation ever ran, so there is no verdict.

### Choice
Alternative 1 when an evaluation is configured, `null` when none is. The
summary rule ("`failed`: rows where `result.passed` is `false` **or** `output`
is `null`") already counts the row as failed in both cases, so this choice is
only observable in the per-row record; `false` matches the rejection-exhaustion
example, which pairs `output: null` with `"passed": false`.

### Risk: 25
The author most likely prefers: `false` as well; the alternative shows up only
if their failure path short-circuits before the evaluation branch.

---

## T13: `latency_ms` type and rounding

### Spec Text
> `"latency_ms": 230`
> `meta.latency_ms` is wall-clock latency for that API call

### Alternatives
1. Integer milliseconds.
2. Float milliseconds (possibly rounded to 1-2 decimals).

### Choice
Integer, via `int(round(seconds * 1000))`. Both example rows show bare integers,
and `elapsed_seconds` is the only field the spec asks to round to a decimal
place.

### Risk: 15
The author most likely prefers: integers too; a test would have to assert the
exact type (`isinstance(x, int)`) to tell the readings apart.

---

## T14: How `rpm` controls concurrency

### Spec Text
> Use the configured `rpm` as the server's approximate request capacity and keep
> enough work in flight to avoid an obviously sequential pipeline. Target at
> least 80% of the configured `rpm`.

### Alternatives
1. Treat `rpm` as a *server* capacity hint only: never throttle client-side, cap
   in-flight requests at roughly `rpm` (bounded to a sane range) and let the
   server's queue set the pace.
2. Treat `rpm` as a *client* budget: admit at most `rpm` request starts per
   minute via a token bucket, which caps measured throughput at exactly `rpm`.

### Choice
Alternative 1, with an in-flight cap of `min(max(rpm, 4), 256)`. The spec says
the server "does not return rate-limit errors" and that `rpm` is "the server's
approximate request capacity", and it asks to *reach* 80% of `rpm` rather than
to stay under it. A client-side token bucket makes hitting 80% a coin flip on
small inputs because of the first-request-to-last-response measurement window.

### Risk: 20
The author most likely prefers: the same, since a throttled client cannot
reliably clear their own 80% bar.

---

## T15: Ordering guarantee for concurrent requests

### Spec Text
> Send requests in input order: concurrent execution must not cause a later
> input row to consume the response intended for an earlier row.

### Alternatives
1. Requests are *started* in input order (FIFO admission), each row keeps its own
   response, and output rows are written in input order. Completions may
   interleave.
2. Strict serialisation - a later row may not even start before an earlier row
   finishes (which would defeat the concurrency requirement).

### Choice
Alternative 1: tasks acquire the in-flight semaphore FIFO in row order, each
response is bound to the coroutine that issued it, and results are written by
index. Alternative 2 contradicts the "must issue requests concurrently"
requirement in the same section.

### Risk: 10
The author most likely prefers: alternative 1; the clause reads as a warning
against a shared response queue, not a serialisation demand.

---

## T16: Placeholder syntax and literal braces

### Spec Text
> `prompt.system` and `prompt.user` use `{field}` placeholders resolved from
> each input row.

### Alternatives
1. Regex substitution of `{identifier}` only; any other brace text (`{`, `{ }`,
   `{"json": 1}`) is passed through untouched.
2. `str.format_map(row)`, which additionally requires `{{`/`}}` escaping and
   supports `{a[0]}` / `{a.b}` / `{a!r:>10}` syntax.

### Choice
Alternative 1. It makes prompts containing literal JSON braces (very common in
these configs) safe, and it makes "missing field" detection exact rather than a
`KeyError`/`IndexError`/`ValueError` triage. Placeholder values are inserted via
`str(value)`, so non-string row fields render naturally.

### Risk: 20
The author most likely prefers: `str.format(**row)`, which behaves identically
on every prompt that contains no literal braces and no format specs - i.e. on
almost any fixture they would write.

---

## T17: `elapsed_seconds` / `throughput_rpm` when there are no API calls

### Spec Text
> `elapsed_seconds`: wall-clock time from first request to last response,
> rounded to 1 decimal place
> `throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to 1
> decimal place

### Alternatives
1. Report `0.0` for both when no request was ever issued (empty input file), and
   `0.0` throughput when the elapsed window rounds to zero.
2. Let the division raise / emit `null` or `Infinity`.

### Choice
Alternative 1. A summary object is still required on a successful run, and
`Infinity` is not representable in JSON. Throughput is computed from the
unrounded elapsed time to avoid a divide-by-zero on very fast runs, then
rounded.

### Risk: 15
The author most likely prefers: the same guard; the only visible difference is
which of `0.0`/`null` lands in the summary for an empty input.

---

## T18: `temperature` when the scheme is `greedy`

### Spec Text
> `greedy`: force `temperature` to `0.0`; `n` is ignored

### Alternatives
1. Silently override any configured or `--temperature` value with `0.0`.
2. Reject a config that pairs `greedy` with a non-zero temperature.

### Choice
Alternative 1. "force" describes an action taken on the value, not a constraint
to validate - contrast with `sample`, where the spec explicitly says temperature
"must be `> 0`" and validation is intended.

### Risk: 10
The author most likely prefers: the same silent forcing.

---

## T19: Exit code for CLI usage errors

### Spec Text
> Exit codes:
> - `0`: success
> - `1`: configuration or input error

### Alternatives
1. Usage errors (missing `--config`, no `run` subcommand, an unknown flag) also
   exit `1`, since the spec enumerates only two codes.
2. Usage errors keep argparse's default exit code `2`.

### Choice
Alternative 1: `ArgumentParser.error` is overridden to exit `1`. A missing
required flag *is* a configuration error in the plain sense, and the spec's
exit-code list reads as exhaustive.

### Risk: 35
The author most likely prefers: plain `argparse`, i.e. exit code `2`, because
overriding `error()` is a deliberate extra step most implementations skip. A
hidden test would have to exercise a malformed command line to tell.
