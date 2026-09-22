# Ambiguities

Numbered record of places where the spec admits more than one conforming
implementation. Each entry quotes the spec, lists the readings, states the
choice made in `rejector.py`, and scores the risk that the spec author's own
implementation (and therefore the hidden tests) reads it differently.

---

## T1 — How many HTTP calls a 5xx row makes before it is given up on

### Spec Text

> If a request receives an HTTP `5xx`, retry it up to 3 times. After the
> third failure, treat that row as failed, emit `null` output for it, count it
> as failed in the summary, and continue.

### Alternatives

1. **3 total HTTP calls** — the initial call plus 2 retries; the third failure
   is the third call, which matches "after the third failure" literally.
2. **4 total HTTP calls** — the initial call plus 3 retries, which matches
   "retry it up to 3 times" literally. Under this reading "the third failure"
   means the third *retry's* failure.

The two sentences cannot both be literally true, and the difference is
directly observable in `total_api_calls`.

### Choice

3 total HTTP calls per logical attempt (initial + 2 retries). The second
sentence describes observable behaviour ("after the third failure, treat that
row as failed") and reads like a description of the author's actual loop —
`for attempt in range(3)` is the most common way this gets written, and an
author whose loop issued four calls would more naturally have written "after
the fourth failure" or "after the third retry".

### Risk: 40

The author most likely prefers: 4 total calls (initial attempt + 3 retries),
taking "retry up to 3 times" as normative.

---

## T2 — `meta` shape for a rejection row that finishes in a single attempt

### Spec Text

> `meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt

### Alternatives

1. **Shape keyed on attempt count** — any row with exactly one attempt gets a
   bare object, including a rejection row that passes on its first attempt.
2. **Shape keyed on scheme** — every rejection row gets a list (of length 1 when
   it passes immediately); greedy/sample get an object.

### Choice

Shape keyed on attempt count: `len(metas) == 1` emits a bare object, otherwise
a list. The sentence's subject is "one-attempt rows", not "greedy and sample
rows", and the clause "with multiple attempts" is only meaningful as a
restriction if single-attempt rejection rows behave differently.

### Risk: 35

The author most likely prefers: always a list for `scheme: rejection`,
regardless of how many attempts were used.

---

## T3 — `meta` for a row whose API calls all failed

### Spec Text

> After the third failure, treat that row as failed, emit `null` output for it

and

> ```json
> "meta": {"model": "gpt-4", "prompt_tokens": 45, ... "finish_reason": "stop"}
> ```

### Alternatives

1. **`meta: null`** — there is no successful response, so there is no metadata.
2. **A metadata object with null-valued fields** — keep the key shape stable and
   report `model` plus the measured `latency_ms`, with token fields and
   `finish_reason` set to `null`.
3. Omit the `meta` key entirely.

### Choice

Option 2: a metadata object is emitted for every *logical* attempt, with
`model` and `latency_ms` populated and `prompt_tokens`, `completion_tokens`,
`total_tokens`, `finish_reason` set to `null`. This keeps `meta` shape-stable
and keeps the meta list aligned 1:1 with `result.attempts` for rejection rows
(where an attempt may fail after a successful earlier attempt). Option 3 is
rejected because the per-row shape in the spec always shows a `meta` key.

### Risk: 40

The author most likely prefers: `"meta": null` for a row with no successful
API response.

---

## T4 — Default `extract` method when `evaluation.extract` is omitted

### Spec Text

> ```yaml
>   evaluation:
>     type: "exact_match"
>     answer_field: "answer"
>     extract: "last_number"
> ```

> Extract methods:
> - `last_number` ... - `last_line` ... - `full`: use the entire response text

### Alternatives

1. Default `full` — the identity extraction, so omitting `extract` changes
   nothing about the response text.
2. Default `last_number` — the value used in every example config.
3. Treat a missing `extract` as a configuration error for `exact_match`.

### Choice

Default `full`. The validation rules list exactly what is required
(`answer_field` for `exact_match`/`contains`, `pattern` for `regex`) and do not
mention `extract`, so it must be optional; the only sensible default for an
optional transform is the identity one. It also makes `contains` and `regex`
operate on "response text" exactly as the spec describes them (see T5).

### Risk: 25

The author most likely prefers: `full` as well, but a `last_number` default is
plausible given every example uses it.

---

## T5 — Whether `extract` is applied before `contains` and `regex` evaluation

### Spec Text

> - `contains`: response text must contain the `answer_field` value as a
>   substring
> - `regex`: response text must match the configured `pattern`

> `result.extracted_answer` is the extracted comparison value

### Alternatives

1. **Uniform pipeline** — always run the configured extraction, then apply the
   evaluation type to the extracted value. With the default `extract: full`
   this is identical to matching against the raw response text.
2. **Type-specific** — `extract` only affects `exact_match`; `contains` and
   `regex` always see the raw response text.

### Choice

Uniform pipeline. `result.extracted_answer` is described as "the extracted
comparison value" for all evaluation types, which implies one extraction step
feeding all comparisons. With the `full` default (T4) this reproduces the
spec's wording for `contains`/`regex` verbatim; the readings only diverge when
a config pairs a non-`full` `extract` with `contains`/`regex`.

### Risk: 20

The author most likely prefers: the same uniform pipeline; divergence only
shows up on a config that mixes `extract: last_number` with `contains`.

---

## T6 — `extracted_answer` for a `regex` evaluation

### Spec Text

> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output

### Alternatives

1. The extracted value fed into the match (the whole response under the default
   `extract: full`).
2. The text the regex matched (group 0, or group 1 when the pattern has one).
3. `null`, since `regex` has no notion of an answer.

### Choice

Option 1 — the value that was fed to the comparison, identical to the other
evaluation types. "The extracted comparison value" names the output of the
extract step, not the output of the match.

### Risk: 35

The author most likely prefers: the matched substring (group 0/1) for `regex`.

---

## T7 — Default `temperature`, and whether `sample`/`rejection` must set it

### Spec Text

> - `sample`: `temperature` must be `> 0`; `n` is ignored
> - `rejection`: `temperature` must be `> 0`

### Alternatives

1. Default `temperature` to `0.0`; a `sample`/`rejection` config that omits it
   therefore fails validation with exit code 1.
2. Default `temperature` to `1.0` (OpenAI's default) for `sample`/`rejection`,
   so omitting it is legal.

### Choice

Option 1. The config shape documents `temperature: 0.0` as the value present in
the file, and the "must be `> 0`" rule exists precisely to reject configs that
left it at the default. Scheme-dependent defaults are not mentioned anywhere.

### Risk: 30

The author most likely prefers: option 1, but a `1.0` default for
non-greedy schemes would make an omitted temperature legal instead of an error.

---

## T8 — `--temperature` on the CLI combined with `scheme: greedy`

### Spec Text

> - `greedy`: force `temperature` to `0.0`; `n` is ignored

> Optional overrides replace the corresponding config values when provided:
> `--temperature <float>`

### Alternatives

1. The greedy forcing rule wins: `0.0` is sent even if `--temperature 0.7` was
   passed.
2. An explicit CLI override wins over the scheme rule.

### Choice

Option 1. Overrides "replace the corresponding config values"; the greedy rule
is applied to the merged config afterwards, and "force" is unconditional.

### Risk: 15

The author most likely prefers: option 1 as well.

---

## T9 — What `exact_match` compares

### Spec Text

> - `exact_match`: extract an answer from the response and compare it to the
>   configured `answer_field` from the input row

### Alternatives

1. Whitespace-stripped string equality, with the row value coerced with `str()`
   (so an integer `8` in the row matches an extracted `"8"`).
2. Byte-exact string equality with no stripping.
3. Numeric-aware comparison (`8` == `8.0` == `8.00`).

### Choice

Option 1. "Exact match" rules out numeric normalisation, but the extract
methods (`last_line`, `full`) routinely carry surrounding whitespace, so
stripping both sides is what makes the documented pipeline usable. Coercing the
row value with `str()` keeps JSON numbers usable as answers.

### Risk: 25

The author most likely prefers: option 1; a fixture with answer `8.0` and
response `8` would expose option 3.

---

## T10 — What counts as "the last integer or decimal"

### Spec Text

> - `last_number`: use the last integer or decimal in the response

### Alternatives

1. `-?\d+(?:\.\d+)?` — signed integers and decimals, no thousands separators.
2. Unsigned only (`\d+(?:\.\d+)?`), so `-5` extracts as `5`.
3. Also accept thousands separators (`1,234`) and/or a trailing decimal point.

### Choice

Option 1, returning the matched text verbatim (so `8` stays `"8"` and `8.50`
stays `"8.50"`, never renormalised through `float`). A leading `-` is part of
the number in ordinary usage; comma grouping is not mentioned by the spec and
conflicts with list-like output such as `1,234` meaning two numbers.

### Risk: 20

The author most likely prefers: option 1, with comma handling the most likely
extra (`re.sub(",", "", text)` before matching) if their fixtures use GSM8K
style answers such as `18,000`.

---

## T11 — When missing template fields are detected

### Spec Text

> If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field.

### Alternatives

1. Pre-flight: validate every row before issuing any request, so nothing is
   sent and no output file is produced.
2. Lazy: fail at the moment the offending row is rendered, after earlier rows
   have already been requested and possibly written.

### Choice

Pre-flight validation of all rows (template fields first, then `answer_field`
presence). The spec's Input section states the requirement as a property of the
file ("Every row must contain all fields referenced by the prompt templates"),
and exiting `1` mid-flight would leave a partially written output file whose
contents the spec never describes. The reported index is the first offending
row in file order.

### Risk: 20

The author most likely prefers: pre-flight as well; a lazy implementation would
differ in whether `results.jsonl` exists after the failure and in which row
index is reported when several rows are bad.

---

## T12 — A row missing the evaluation `answer_field`

### Spec Text

> When the configured evaluation uses `answer_field`, each row must also contain
> that field.

### Alternatives

1. Exit code 1 with a stderr message, like a missing template field.
2. Process the row and mark it failed.

### Choice

Option 1 — exit 1 before any request, with a message naming the row index and
the missing field. It is stated as a hard requirement on the input, and exit
code 1 is documented as covering "input error".

### Risk: 15

The author most likely prefers: option 1.

---

## T13 — Missing `output_field`

### Spec Text

> ```yaml
>   output_field: "solution"
> ```

### Alternatives

1. Required; a config without it exits 1.
2. Optional with default key `"output"`.

### Choice

Option 2, default `"output"`. The Validation rules section enumerates the
configuration errors the tool must detect and `output_field` is not among them,
so rejecting a config for it would invent a rule.

### Risk: 20

The author most likely prefers: option 2 (or never tests a config that omits
it).

---

## T14 — Whether rejection attempts may run in parallel

### Spec Text

> - `rejection`: `temperature` must be `> 0`; make up to `n` attempts and keep
>   the first passing response

### Alternatives

1. Sequential attempts within a row: stop as soon as one passes, so a row that
   passes on attempt 2 of 5 costs 2 API calls.
2. Speculative: fire all `n` at once and keep the first passing one, costing
   `n` calls always.

### Choice

Sequential. "Up to `n` attempts" and the worked example ("the first two
responses fail evaluation and the third passes ... records `attempts: 3`" with
three metadata entries) both require that later attempts are not made once one
passes. Cross-row concurrency supplies the throughput instead.

### Risk: 10

The author most likely prefers: sequential.

---

## T15 — A retry-exhausted API failure part-way through rejection sampling

### Spec Text

> After the third failure, treat that row as failed, emit `null` output for it,
> count it as failed in the summary, and continue.

### Alternatives

1. The row fails immediately: remaining rejection attempts are abandoned,
   `output` is `null`, `passed` is `false`, and `attempts` counts the failed
   attempt.
2. The failed attempt is consumed like a non-passing sample and the row
   continues with its remaining attempts.

### Choice

Option 1. The sentence says "treat that **row** as failed ... and continue",
where "continue" refers to processing the remaining rows, not the remaining
attempts. A row that fails this way still records the attempts it spent, so a
failure on the second of five attempts yields `attempts: 2`.

### Risk: 35

The author most likely prefers: option 1, but consuming the attempt and
continuing (option 2) is a natural fall-out of a loop that treats "no passing
response" uniformly.

---

## T16 — `output` for a greedy/sample row whose evaluation fails

### Spec Text

> `output` is an object with one key named by `output_field`; if all attempts
> fail, `output` is `null`

> `failed`: rows where `result.passed` is `false` or `output` is `null`

### Alternatives

1. "All attempts fail" means rejection exhaustion only; a greedy/sample row
   keeps its response text with `passed: false`.
2. Any failing evaluation nulls the output.

### Choice

Option 1. The summary rule distinguishes "`result.passed` is `false`" from
"`output` is `null`", which is only meaningful if a row can have a non-null
output with `passed: false`. The `null` output shape is introduced only in the
rejection bullet and the rejection example.

### Risk: 8

The author most likely prefers: option 1.

---

## T17 — Empty input file

### Spec Text

> `total`: input row count

### Alternatives

1. Success: empty output file, summary with `total: 0` and zeroed counters.
2. Input error, exit 1.

### Choice

Option 1, with `elapsed_seconds: 0.0` and `throughput_rpm: 0.0` (no division by
zero). Nothing in the spec makes an empty file invalid. Blank lines inside a
JSONL file are skipped; a line that is not valid JSON is an input error (exit 1).

### Risk: 15

The author most likely prefers: option 1.

---

## T18 — Extraction that finds nothing

### Spec Text

> - `last_number`: use the last integer or decimal in the response
> - `last_line`: use the last non-empty line

### Alternatives

1. `extracted_answer: null` and `passed: false` when the response contains no
   number / no non-empty line.
2. Empty string `""` as the extracted value.

### Choice

Option 1. `null` is already the spec's "there is no comparison value" signal
for `extracted_answer`, and an empty string would spuriously satisfy a
`contains` check against an empty answer.

### Risk: 20

The author most likely prefers: `null`, though `""` falls out of a
`re.findall(...)[-1] if matches else ""` style implementation.

---

## T19 — Optional `prompt.system`

### Spec Text

> ```json
> "messages": [
>   {"role": "system", "content": "<rendered system prompt>"},
>   {"role": "user", "content": "<rendered user prompt>"}
> ]
> ```

### Alternatives

1. `system` is optional; when absent the request carries only the user message.
2. Both keys are required.
3. Absent `system` is sent as an empty-content system message.

### Choice

Option 1 for `system`, and `prompt.user` required (a task with no user prompt
has nothing to send). Sending a system message with empty content is a
different wire payload than sending none, and omitting the key is the more
conservative of the two.

### Risk: 20

The author most likely prefers: option 1; their fixtures almost certainly
always set both, making this untested.

---

## T20 — Turning `rpm` into a concurrency level

### Spec Text

> Use the configured `rpm` as the server's approximate request capacity and keep
> enough work in flight to avoid an obviously sequential pipeline. Target at
> least 80% of the configured `rpm`.

### Alternatives

1. Keep up to `rpm` requests in flight (capped for sanity), with no client-side
   pacing — the server queues, so extra in-flight work only ever helps.
2. Pace outgoing requests to exactly `rpm` with a token bucket, which caps
   throughput at 100% of `rpm` and risks landing just under the 80% bar.

### Choice

Option 1: `concurrency = min(max(rpm, 4), 64)`, further capped by the number of
pending rows. The spec states the server "does not return rate-limit errors"
and queues internally, so the only stated target is a lower bound on
throughput. 64 bounds thread usage without ever being the binding constraint in
a test sized around a modest `rpm`.

### Risk: 10

The author most likely prefers: any saturating strategy; only a test asserting
an *upper* bound on `throughput_rpm` would distinguish them.

---

## T21 — Exit code for malformed command lines

### Spec Text

> Exit codes:
> - `0`: success
> - `1`: configuration or input error

### Alternatives

1. Map argparse usage errors (unknown flag, missing required flag, non-integer
   `--rpm`) to exit code 1, since only 0 and 1 are documented.
2. Leave argparse's default exit code 2.

### Choice

Option 1. The spec documents a closed set of exit codes and a bad `--rpm` value
is a configuration error in substance.

### Risk: 10

The author most likely prefers: option 1, or never tests it (argparse's
default 2 is what an un-customised implementation emits).

---

## T22 — Which calls contribute to the token totals

### Spec Text

> `total_api_calls`: all HTTP requests, including retries and rejection attempts

(no corresponding rule for `total_prompt_tokens` / `total_completion_tokens`)

### Alternatives

1. Sum `usage` over every successful HTTP response, including rejection
   attempts that were discarded and retried calls that eventually succeeded.
2. Sum only over the responses that were kept as `output`.

### Choice

Option 1. The tokens were really spent, and the summary is a cost report
alongside `total_api_calls`, which is explicitly all-inclusive. A failed 5xx
call contributes nothing because it carries no `usage`.

### Risk: 12

The author most likely prefers: option 1.

---

## T23 — Non-5xx failures

### Spec Text

> If a request receives an HTTP `5xx`, retry it up to 3 times.

### Alternatives

1. Only 5xx is retried. A 4xx fails the row immediately (one API call), and
   transport-level errors (connection refused, timeout) are treated as
   retryable like 5xx.
2. Retry every error.
3. Treat a 4xx as a fatal, exit-1 condition.

### Choice

Option 1. The retry rule is explicitly conditioned on 5xx, and a 4xx is a
deterministic client error that a retry cannot fix; exit 1 is reserved for
configuration and input errors, so a 4xx degrades the row instead of the run.
Transport errors have no HTTP status at all and are treated as the transient
class they belong to.

### Risk: 15

The author most likely prefers: option 1; a blanket "retry any exception"
implementation would differ on 4xx call counts.

---

## T24 — Whether `throughput_rpm` is computed from the rounded `elapsed_seconds`

### Spec Text

> - `elapsed_seconds`: wall-clock time from first request to last response,
>   rounded to 1 decimal place
> - `throughput_rpm`: `total_api_calls / elapsed_seconds * 60`, rounded to
>   1 decimal place

### Alternatives

1. Compute from the **rounded** `elapsed_seconds`, so the two reported numbers
   satisfy the stated formula exactly.
2. Compute from the raw elapsed time and round only the final result, in which
   case `throughput_rpm` can disagree with the printed `elapsed_seconds` by
   tens of percent on short runs (0.12 s printed as `0.1`).

### Choice

Option 1. The formula is written in terms of `elapsed_seconds`, which the spec
has just defined as the rounded value, and self-consistency is the only
property a test can actually assert about wall-clock-dependent numbers. One
exception: when the run is so short that `elapsed_seconds` rounds to `0.0`, the
raw elapsed time is used as the divisor rather than reporting a throughput of
`0.0` for a run that plainly made calls (and `0.0` if no call was made at all,
so there is never a division by zero).

### Risk: 25

The author most likely prefers: option 1 if they assert the identity between
the two fields; a raw-time implementation is common but untestable except
through loose bounds.
