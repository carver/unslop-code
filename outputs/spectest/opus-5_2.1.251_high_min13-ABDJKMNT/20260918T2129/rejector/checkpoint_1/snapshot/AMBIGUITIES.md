# Ambiguities

Spec-reading decisions taken while implementing `rejector.py` Part 1.
Each entry quotes the spec, lists the readings a conforming implementation
could take, and records the choice made plus the risk that the spec author's
own implementation reads it differently.

---

## T1: How `rpm` maps to in-flight requests

### Spec Text

> "The API server queues requests internally and spends time processing each
> request. It does not return rate-limit errors. A sequential client will
> leave capacity idle; your tool should keep enough requests in flight to
> use the configured request budget effectively."
>
> "Use the configured `rpm` as the server's approximate request capacity and
> keep enough work in flight to avoid an obviously sequential pipeline.
> Target at least 80% of the configured `rpm`."

### Alternatives

1. Treat `rpm` as a client-side rate limit: pace departures at `rpm/60`
   requests per second (token bucket), with unbounded concurrency.
2. Treat `rpm` as a concurrency budget: allow up to a fixed number of
   simultaneous requests derived from `rpm`, and never delay a request that
   has a free slot.
3. Fixed concurrency independent of `rpm` (e.g. always 16 workers).

### Choice

Reading 2, with the in-flight cap set to `rpm` requests (clamped to a sane
ceiling). The server is described as the thing that queues and paces work,
and it "does not return rate-limit errors", so client-side throttling can
only lose throughput. Concurrency equal to `rpm` saturates any server whose
per-request latency is under a minute, which is what the 80% target needs.
Request departures are never artificially delayed.

### Risk: 20

The author most likely also caps concurrency rather than pacing, but may
derive a smaller worker count (e.g. `rpm/60 * expected_latency`) — only
observable through timing, which hidden tests can realistically only assert
as a lower bound on throughput.

---

## T2: How many HTTP requests "retry up to 3 times" allows

### Spec Text

> "If a request receives an HTTP `5xx`, retry it up to 3 times. After the
> third failure, treat that row as failed, emit `null` output for it, count
> it as failed in the summary, and continue."

### Alternatives

1. 1 initial request + 3 retries = 4 HTTP calls before giving up. "Retry it
   up to 3 times" is literal; "the third failure" means the third retry's
   failure.
2. 3 HTTP calls total (1 initial + 2 retries). "After the third failure"
   counts failures from the initial request.

### Choice

Reading 1 — four HTTP calls for a permanently failing request. "Retry it up
to 3 times" is the operative rule and states a retry count; the following
sentence describes when to stop, and reads naturally as the third retry.
This also matches the common `max_retries=3` convention.

### Risk: 45

Directly observable in `total_api_calls` for an always-5xx fixture. The
author may well have implemented `for attempt in range(3)`, giving 3 calls.

---

## T3: `temperature` when the config omits it under `sample`/`rejection`

### Spec Text

> "`sample`: `temperature` must be `> 0`; `n` is ignored"
>
> "`rejection`: `temperature` must be `> 0`"

### Alternatives

1. Missing `temperature` defaults to `0.0` (the value shown in the sample
   config), so `sample`/`rejection` without it fail validation with exit 1.
2. Missing `temperature` defaults to something `> 0` (e.g. `1.0`), so the
   config is valid.

### Choice

Reading 1. The config example pins `temperature: 0.0` as the baseline, and
"must be > 0" reads as a validation rule over the effective value rather
than over an explicitly-provided one. Omitting it under `sample` is
therefore a configuration error naming `temperature`.

### Risk: 35

If the author defaults to `1.0` for non-greedy schemes, a fixture with
`scheme: sample` and no `temperature` would be expected to succeed; the
author most likely prefers erroring, but a `1.0` default is a plausible
convenience.

---

## T4: `extracted_answer` for `contains` and `regex`, and the default `extract`

### Spec Text

> "`result.extracted_answer` is the extracted comparison value, or `null`
> when there is no evaluation or no output"
>
> "`contains`: response text must contain the `answer_field` value as a
> substring" / "`regex`: response text must match the configured `pattern`"
>
> "`full`: use the entire response text"

### Alternatives

1. `extracted_answer` is always `extract(response)` using the configured
   method, defaulting to `full` — so `contains`/`regex` rows report the whole
   response (or whatever `extract` selects), while the pass/fail test still
   runs against the full response text as specified.
2. `extracted_answer` is `null` for `contains` and `regex`, because those
   types do not "extract an answer".
3. `extracted_answer` is the matched substring (the `answer_field` value for
   `contains`, the regex match for `regex`).

### Choice

Reading 1. `extract` is configured on `evaluation` generally, not on
`exact_match` specifically, and `full` exists precisely as the "no real
extraction" method, which makes it the natural default and the natural
result for the other types. Pass/fail for `contains`/`regex` still uses the
full response text, exactly as worded.

### Risk: 40

`exact_match` behaviour is unaffected. If the author returns `null` or the
regex match group for `contains`/`regex`, an assertion on
`extracted_answer` for those types would differ; the matched-text reading is
the most likely alternative for `regex`.

---

## T5: Default `max_tokens`

### Spec Text

> ```json
> {"model": "<model>", "messages": [...], "temperature": 0.0, "max_tokens": 512}
> ```
>
> config: `max_tokens: 512`

### Alternatives

1. `max_tokens` defaults to `512` (the value used throughout the spec) and is
   always present in the request body.
2. `max_tokens` is omitted from the request body when the config omits it.

### Choice

Reading 1. The documented request body always carries `max_tokens`, and
`512` is the only default the spec ever shows.

### Risk: 20

Only observable if a fixture omits `max_tokens` and asserts on the outgoing
body; the author may send no key at all in that case.

---

## T6: `meta` shape for a rejection row that passes on its first attempt

### Spec Text

> "`meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt"

### Alternatives

1. Shape follows the actual attempt count: a rejection row with
   `attempts: 1` gets a bare object.
2. Shape follows the scheme: every rejection row gets a list, even with one
   attempt.

### Choice

Reading 1 — the sentence conditions on "one-attempt rows" and "multiple
attempts", not on the scheme.

### Risk: 25

A rejection fixture whose first attempt passes is a natural test to write,
and an implementation that always builds a list for rejection would emit
`[{...}]` there.

---

## T7: `meta` for a row with no successful API response

### Spec Text

> "After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue."
>
> "`meta` is a single metadata object for one-attempt rows"

### Alternatives

1. `meta` is `null` — there is no completion, so no usage, finish reason, or
   model to report.
2. `meta` is an object with `null`/zero fields (e.g. `model` populated,
   tokens `0`, `finish_reason: null`).
3. `meta` is an object carrying error information.

### Choice

Reading 1. The spec defines `meta` entirely in terms of a returned
completion, and pairs `null` output with the absence of a result; a `null`
meta is the consistent signal that nothing came back.

### Risk: 40

An always-5xx fixture is very likely tested. The author may prefer a
skeleton object with the model name and a measured `latency_ms`, which would
differ from `null`.

---

## T8: How `exact_match` compares the extracted value

### Spec Text

> "`exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row"
>
> "`last_number`: use the last integer or decimal in the response"

### Alternatives

1. Plain string equality after stripping surrounding whitespace.
2. String equality, falling back to numeric equality when both sides parse
   as numbers (so `8` matches `8.0`, and thousands separators in the row
   value do not defeat a match).
3. Always numeric comparison when `extract: last_number`.

### Choice

Reading 2. String equality is the primary test, which keeps `exact_match`
exact for text answers; the numeric fallback only ever turns a "no" into a
"yes" for values that denote the same number, which is what a `last_number`
extractor is for. `extracted_answer` always reports the literal extracted
text, not a normalised form.

### Risk: 20

Divergence needs a fixture where the row answer and the extracted text are
numerically equal but textually different (`8` vs `8.0`, `1,000` vs `1000`).
If the author compares strings only, such a case would be expected to fail.

---

## T9: Errors that are not HTTP 5xx

### Spec Text

> "If a request receives an HTTP `5xx`, retry it up to 3 times."

### Alternatives

1. Retry only 5xx; 4xx and malformed responses fail the row immediately;
   transport errors (connection reset, timeout) follow the same retry policy
   as 5xx since they are transient in the same way.
2. Retry everything that is not a 2xx.
3. Retry nothing but 5xx, including treating timeouts as immediate failures.

### Choice

Reading 1. A 4xx is a client-side mistake that retrying cannot fix, so the
row fails at once; connection errors and timeouts are transient transport
failures and get the 5xx retry budget.

### Risk: 25

The spec only ever describes a 5xx server, so hidden tests may not probe
this at all. If they do, a 4xx fixture asserting one HTTP call is the likely
shape — which matches this choice.

---

## T10: When row-level validation happens

### Spec Text

> "If a placeholder references a missing field, exit with code `1` and print
> an error to stderr naming the row index and missing field."
>
> "`--output <path>`: JSONL output file, created or overwritten"

### Alternatives

1. Validate every row up front; exit 1 before issuing any request, and leave
   the output file untouched.
2. Stream rows, failing partway through after some requests have been sent
   and possibly after partial output was written.

### Choice

Reading 1. Exiting `1` is classed as a "configuration or input error"
alongside unreadable configs, which are detected before any work; failing
fast also avoids spending API calls on a run that cannot complete. The
lowest-index offending row is reported.

### Risk: 15

Observable only via side effects (whether the output file exists, whether
any request was made) after a bad-row fixture; asserting the exit code and
stderr text works either way.

---

## T11: Exit code for CLI usage errors

### Spec Text

> "Exit codes: `0`: success, `1`: configuration or input error"

### Alternatives

1. Missing/invalid flags exit `1`, since the spec names only `0` and `1`.
2. Missing/invalid flags exit `2`, argparse's default for usage errors.

### Choice

Reading 1 — the spec enumerates its exit codes exhaustively, and a missing
`--config` is a configuration error by any reading.

### Risk: 30

If the author used stock `argparse`, a missing-flag fixture would expect
`2`. Tests here only assert "not 0" for that case.

---

## T12: Whether `throughput_rpm` uses rounded `elapsed_seconds`

### Spec Text

> "`elapsed_seconds`: wall-clock time from first request to last response,
> rounded to 1 decimal place"
>
> "`throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to 1
> decimal place"

### Alternatives

1. Compute throughput from the unrounded elapsed time, then round.
2. Compute throughput from the already-rounded `elapsed_seconds`.

### Choice

Reading 1 — rounding is presented as a reporting step for each field, and
compounding it would distort short runs.

### Risk: 10

The two differ by well under a percent for any run long enough to measure,
and timing-dependent values can only be asserted with tolerance.

---

## T13: A rejection attempt that exhausts its retry budget

### Spec Text

> "`rejection`: ... make up to `n` attempts and keep the first passing
> response; if all attempts fail, output `null` with `"passed": false`"
>
> "After the third failure, treat that row as failed, emit `null` output for
> it ... and continue."

### Alternatives

1. A hard HTTP failure fails the whole row immediately: stop attempting,
   `output: null`, `passed: false`, `attempts` counts the attempts made
   including the failed one.
2. A hard HTTP failure counts as one failed attempt and the loop continues
   to the next attempt, up to `n`.

### Choice

Reading 1. The retry rule is unconditional about what happens after the
budget is spent — "treat that row as failed ... and continue" refers to
continuing with other rows — so the row stops there.

### Risk: 35

Reading 2 is a defensible "attempt failed, try again" interpretation and
would change both `attempts` and `total_api_calls` for a rejection fixture
with an injected 5xx.

---

## T14: Summary values when nothing was requested

### Spec Text

> "`elapsed_seconds`: wall-clock time from first request to last response"
>
> "`throughput_rpm`: `total_api_calls / elapsed_seconds * 60`"

### Alternatives

1. With no requests (empty input), report `elapsed_seconds: 0.0` and
   `throughput_rpm: 0.0`.
2. Report the process wall-clock time and a `0.0` throughput.
3. Report `null` for both.

### Choice

Reading 1. With no first request and no last response the interval is empty,
and `0.0` keeps the summary numeric and division-safe.

### Risk: 20

An empty-input fixture is plausible; the author might emit the whole-run
wall clock instead, though the difference is a few milliseconds either way.

---

## T15: Whether `prompt.system` is required

### Spec Text

> "`prompt.system` and `prompt.user` use `{field}` placeholders resolved from
> each input row."
>
> ```json
> "messages": [{"role": "system", ...}, {"role": "user", ...}]
> ```

### Alternatives

1. `user` is required; `system` is optional and, when absent, no system
   message is sent.
2. Both are required; omitting `system` is a configuration error.
3. `system` defaults to an empty string and is always sent.

### Choice

Reading 1. Every example supplies both, so the spec never settles it; sending
an empty system message is worse than sending none, and a task with only a
user template is a reasonable configuration.

### Risk: 30

If the author requires both keys, a config missing `system` would be
expected to exit `1` rather than run.

---

## T16: Which task keys are required, and the default `rpm`

### Spec Text

> Config shape lists `name`, `api_url`, `model`, `rpm`, `prompt`,
> `generation`, `evaluation`, `output_field`.
>
> "Invalid configuration exits with code `1` and a descriptive message on
> stderr."

### Alternatives

1. Require `api_url`, `model`, `prompt` (with `user`), and `output_field`;
   treat `name` as informational, `rpm` as defaulting to `60`, and
   `generation` as defaulting to `greedy`.
2. Require every key that appears in the config shape.

### Choice

Reading 1. The spec marks only `evaluation` as explicitly optional, but the
worked greedy example already drops `generation.temperature` and
`generation.n`, showing that the shape is illustrative rather than a
required-key list. The keys retained as required are the ones with no
sensible default: where to send requests, which model, what to ask, and what
to call the output.

### Risk: 30

A fixture omitting `name` or `rpm` and expecting exit `1` would diverge. The
author most likely also defaults `rpm`, but may require `name`.

---

## T17: Blank lines in the JSONL input

### Spec Text

> "The input file is JSONL with one object per line."

### Alternatives

1. Skip blank/whitespace-only lines; they carry no object and do not count
   toward `total`.
2. Treat a blank line as a malformed row and exit `1`.

### Choice

Reading 1 — a trailing newline is ordinary in JSONL, and skipping empty
lines is the universal convention for the format.

### Risk: 15

Only diverges if the author strictly parses every line and a fixture
contains an interior blank line.

---

## T18: Where `meta.model` comes from

### Spec Text

> ```json
> "meta": {"model": "gpt-4", "prompt_tokens": 45, ...}
> ```
>
> The API response example carries no top-level `model` field.

### Alternatives

1. Report the configured (or `--model`-overridden) model.
2. Report the `model` echoed by the API response, falling back to the config.

### Choice

Reading 1. The response schema quoted in the spec has no `model` key at all,
so the config is the only guaranteed source, and every example shows the two
agreeing.

### Risk: 20

Diverges only if a fixture returns a response whose `model` differs from the
configured one, which is an odd thing for a server to do.
