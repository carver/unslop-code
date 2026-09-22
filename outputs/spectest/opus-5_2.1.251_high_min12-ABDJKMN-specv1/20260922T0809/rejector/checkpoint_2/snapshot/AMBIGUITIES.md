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

---

# Part 2

Entries T20 onward cover the multi-task spec. No Part 1 entry is resolved by
Part 2: the Part 2 text repeats none of T1-T19's open points ("Existing
behavior from Part 1 is unchanged unless stated here"), so all of them stand
as written.

---

## T20: How `defaults` and a task entry are merged

### Spec Text
> - `defaults` provides shared values; each task overrides `defaults`
> - nested sections such as `prompt`, `generation`, and `evaluation` are merged
>   per task using the Part 1 structure

### Alternatives
1. Recursive merge: for every key whose value is a mapping on both sides, merge
   recursively; otherwise the task's value replaces the default's. This also
   merges `evaluation.judge_prompt` key-by-key.
2. Two-level merge: top-level keys replace, except the named nested sections
   (`prompt`, `generation`, `evaluation`) which are merged one level deep, so a
   task's `judge_prompt` replaces the default's wholesale.
3. Flat merge: a task's `generation` replaces `defaults.generation` entirely,
   which would drop `max_tokens: 512` from the spec's own example.

### Choice
Alternative 1. Alternative 3 is ruled out by the example config, where
`defaults.generation.max_tokens` must survive every task's own `generation`
block. Between 1 and 2 the observable difference is only a nested
`judge_prompt`/`prompt` partially specified on both sides; recursion is the
smaller, more uniform rule and matches "merged ... using the Part 1 structure".

### Risk: 20
The author most likely prefers: the same recursive merge; a fixture that puts
`judge_prompt.system` in `defaults` and only `judge_prompt.user` in the task
would be the one to tell alternatives 1 and 2 apart.

---

## T21: What `letter` actually matches

### Spec Text
> `letter`: extract the first uppercase answer choice `A` through `D`; accept
> forms such as `A`, `(A)`, `A)`, or `Answer: A`

> If the model returns `"The answer is B) Paris"`, `letter` extracts `"B"` and
> the row passes.

### Alternatives
1. Scan for the first `A`-`D` that is not adjacent to another ASCII letter,
   i.e. `(?<![A-Za-z])([A-D])(?![A-Za-z])`. All four listed forms match, and
   words like `BAD`, `CAB` or `Berlin` cannot contribute a letter.
2. Try the decorated forms first in priority order (`Answer: X`, `(X)`, `X)`)
   and only fall back to a bare standalone letter if none is present. On
   `"A) London  ... the answer is B"` this still yields `A`; it differs from 1
   only when a bare letter precedes a decorated one, e.g.
   `"A quick guess. Answer: C"` -> `C` instead of `A`.
3. First `[A-D]` character anywhere, regardless of context (so `"Berlin"`
   yields `B`).

### Choice
Alternative 1. The spec says "the *first* ... answer choice", which is a
position rule, not a priority rule, so alternative 2 contradicts it whenever
the two disagree. Alternative 3 is ruled out by any response containing an
ordinary capitalised word such as `"Answer"` itself (the `A` of `Answer:` is
followed by `n`, so alternative 1 correctly skips it and takes the `A` after
the colon).

### Risk: 30
The author most likely prefers: a regex such as `\b([A-D])\b`, which agrees
with this choice on every example in the spec but differs on punctuation-hugging
input such as `"...is B."` inside a longer word boundary edge case, and on
responses whose prose starts with a bare `"A "`.

---

## T22: What `first_number` counts as a number

### Spec Text
> `first_number`: extract the first integer or decimal in the response

### Alternatives
1. The same literal grammar as Part 1's `last_number` (`-?\d+(?:\.\d+)?`), taken
   from the front instead of the back.
2. A digits-only, sign-less grammar, on the theory that judge scores are never
   negative.
3. A comma- and leading-dot-tolerant grammar.

### Choice
Alternative 1. `first_number` and `last_number` are described with the same
words ("integer or decimal"), so they should share one scanner; only the index
into the match list differs. This keeps T6's reasoning intact.

### Risk: 20
The author most likely prefers: the same shared regex. The visible difference is
a judge reply like `"-3"` or `"Score: 8/10"` (both readings give `8` there) or a
reply beginning with a date such as `"2024: score 8"`, where both readings agree
too - so the readings rarely diverge.

---

## T23: Generation parameters for the judge request

### Spec Text
> - the judge request is a separate API call through the same server
> - if `evaluation.model` is omitted, use the task's model

### Alternatives
1. The judge call is deterministic: `temperature: 0.0`, `n: 1`, and the task's
   `max_tokens`.
2. The judge call reuses the task's whole `generation` block, so a
   `rejection` task with `temperature: 0.7` also samples its judge.
3. The judge call uses provider defaults and sends neither `temperature` nor
   `max_tokens`.

### Choice
Alternative 1. The spec fixes only the model for the judge, and the point of a
judge is a stable score; sampling the judge at the task's rejection temperature
would make `threshold` comparisons noisy. `max_tokens` still has to come from
somewhere, and the task's value is the only configured number available.

### Risk: 40
The author most likely prefers: alternative 2 - passing the task's existing
generation kwargs straight through is the shortest code path, and a test that
asserts the judge request body's `temperature` would expose the difference.

---

## T24: Where `judge_meta` goes when `meta` is a list

### Spec Text
> - `meta` includes a `judge_meta` object with the judge request's token usage,
>   latency, model, and finish reason

### Alternatives
1. Each attempt is judged, and each attempt's metadata object carries its own
   `judge_meta`. With `rejection` and three attempts, `meta` is a list of three
   objects, each with a `judge_meta`.
2. `judge_meta` is hoisted to a single value alongside the list (which would
   require `meta` to stop being a list and become
   `{"attempts": [...], "judge_meta": {...}}`, changing the Part 1 shape).
3. Only the final (kept) attempt carries a `judge_meta`.

### Choice
Alternative 1. Part 1 fixes `meta` as an object per attempt or a list of such
objects, and Part 2 says only that `meta` "includes" `judge_meta` - the
least-disruptive reading puts it inside the per-attempt object it belongs to.
Alternative 2 would silently break Part 1's documented `meta` shape.

### Risk: 30
The author most likely prefers: alternative 1 for the single-attempt case (which
is what their example shows); alternative 3 is the plausible divergence for
rejection tasks if their implementation judges lazily or records one judge call
per row.

---

## T25: `judge_score` type, and a judge reply with no score

### Spec Text
> - `result` includes `judge_score`, and `result.extracted_answer` is the text
>   `extract` took from the judge's reply (`"8"` for a score of `8`)
> - score `>= threshold` passes

### Alternatives
1. `judge_score` is a number: `int` when the extracted text is integral
   (`"8"` -> `8`), `float` otherwise (`"8.5"` -> `8.5`). If nothing numeric can
   be extracted, or the judge call fails, `judge_score` is `null` and the row
   fails.
2. `judge_score` is the raw string (`"8"`), and the comparison parses it each
   time.
3. An unscoreable judge reply is an error that aborts the run.

### Choice
Alternative 1. The spec contrasts `judge_score` `8` with `extracted_answer`
`"8"` in the same sentence - the quotes on one and not the other are the whole
point of the example - so `judge_score` is numeric. A judge that answers
`"unclear"` is the same class of event as a row whose evaluation simply fails,
and Part 1's rule is "fail that row and continue", never abort.

### Risk: 30
The author most likely prefers: numeric `judge_score` as well; the divergence is
the unscoreable reply, where an author may emit `judge_score: 0` (from a
`float(x or 0)` fallback) instead of `null`.

---

## T26: Is `judge_score` present on non-judge rows?

### Spec Text
> - `result` includes `judge_score`

### Alternatives
1. `judge_score` appears only in rows of an `llm_judge` task.
2. `judge_score` is always present in `result`, and is `null` for every other
   evaluation type, keeping one uniform row schema.

### Choice
Alternative 1. The sentence sits inside the `llm_judge` rule list and describes
what that mode adds; Part 1 already fixed `result` to exactly
`passed`/`extracted_answer`/`attempts`, and "Existing behavior from Part 1 is
unchanged unless stated here" keeps that shape for the other modes.

### Risk: 20
The author most likely prefers: the same, though a uniform schema with
`judge_score: null` everywhere is a common implementation shortcut; a test
asserting `"judge_score" not in row["result"]` for an `exact_match` task is what
would tell them apart.

---

## T27: `result.extracted_answer` for `script` evaluation

### Spec Text
> ```yaml
> evaluation:
>   type: "script"
>   command_template: "python3 -c \"{test_code}\""
>   success_exit_code: 0
> ```
> - capture command stdout and stderr, but do not include them in the JSONL
>   output

### Alternatives
1. `null` - a script evaluation extracts nothing from the response, and the one
   thing the command does produce (its output) is explicitly excluded from the
   JSONL.
2. Apply the configured `extract` (defaulting to `full`) to the generated
   response anyway, so `extracted_answer` is the whole response text.
3. The command's stdout.

### Choice
Alternative 1. Alternative 3 is directly forbidden by the "do not include them"
rule. Between 1 and 2, `script` configs in the spec carry no `extract` key at
all, and echoing the full response back into `extracted_answer` duplicates
`output` for no purpose; `null` matches Part 1's "`null` when there is no
evaluation or no output" spirit.

### Risk: 30
The author most likely prefers: alternative 2, if their evaluation pipeline
always runs the extract step before dispatching on `type` - with the default
`extract: full` that yields the whole response text.

---

## T28: Quoting of `__response__` inside the rendered shell command

### Spec Text
> - if a row field such as `{test_code}` expands to text that itself contains
>   `{__response__}`, substitute `__response__` before executing the command
> - run the rendered command in a shell

> ```json
> {"problem": "write good code", "test_code": "echo '{__response__}' | grep -q 'good code'"}
> ```

### Alternatives
1. Plain textual substitution, no shell quoting: the response text is spliced in
   verbatim wherever the placeholder sat.
2. Shell-quote the response (`shlex.quote`) before splicing.

### Choice
Alternative 1. The spec's own example wraps the placeholder in single quotes
inside the row field (`echo '{__response__}'`), which is exactly what a config
author does when substitution is raw; `shlex.quote` would turn that into
`echo ''response''` and break the documented example. Substitution is two-pass:
row fields (and a direct `{__response__}`) are expanded first, then any
`{__response__}` that appeared *inside* an expanded field is replaced.

### Risk: 15
The author most likely prefers: raw substitution too - their example only works
that way.

---

## T29: A failed `script`/`llm_judge` evaluation still emits the response

### Spec Text
> - exit code equal to `success_exit_code` means pass; any other exit code means
>   fail
> - command timeout is 10 seconds; timeout is a failed evaluation

### Alternatives
1. The row behaves like any other failing evaluation under Part 1 rules: for
   `greedy`/`sample` the generated text is still written to `output`, with
   `"passed": false`; only `rejection` exhaustion writes `output: null`.
2. A failing script sets `output: null` because the candidate was rejected.

### Choice
Alternative 1. Part 1 already separates "the API call produced no text"
(`output: null`) from "the evaluation said no" (`passed: false` with the text
retained), and Part 2 changes only how the verdict is computed.

### Risk: 15
The author most likely prefers: the same; this is the Part 1 code path reused.

---

## T30: A selected task with no input file

### Spec Text
> - `--input-dir` looks for `<task_name>.jsonl`
> - when `--task` is present, require input only for selected tasks and ignore
>   unselected tasks for validation and execution

### Alternatives
1. Input is required for every selected task: a missing `<task>.jsonl` under
   `--input-dir`, or a task with no `--input name=path` entry, is a fatal input
   error (exit 1) before anything runs.
2. Tasks without an input file are silently skipped and simply do not appear in
   the summary's `tasks` object.

### Choice
Alternative 1. "require input only for selected tasks" says input *is* required
for the selected ones - the sentence exists to relax the requirement for
unselected tasks, which only makes sense if the baseline is mandatory. Failing
up front also matches T8.

### Risk: 25
The author most likely prefers: the same for explicit `--input` mappings; the
divergence is `--input-dir`, where "looks for `<task_name>.jsonl`" could be read
as best-effort discovery that skips absent files.

---

## T31: Mode conflicts in input selection

### Spec Text
> - for multi-task configs, explicit `--input <task=path>` and `--input-dir` are
>   alternative modes; do not combine them

### Alternatives
1. Passing both `--input` and `--input-dir` on a multi-task config is a fatal
   error (exit 1); so is passing neither; so is `--input <path>` with no `=`
   against a multi-task config, and an `--input name=path` whose `name` is not a
   task in the config.
2. One mode silently wins (for example `--input` entries override directory
   discovery) and a bare `--input <path>` is ignored.

### Choice
Alternative 1. "do not combine them" is a prohibition, and the only way a CLI
enforces a prohibition is by refusing. A bare path cannot be attributed to a
task, and a mapping naming a non-existent task is a typo the user wants to hear
about. A mapping naming a *known but unselected* task is not an error - the spec
says to ignore unselected tasks - so it is dropped silently.

### Risk: 20
The author most likely prefers: erroring on the combination; the residual risk
is the unselected-task mapping, which an author may also reject outright.

---

## T32: What `--output` must already be for a multi-task run

### Spec Text
> - for multi-task configs, `--output` must be a directory
> - write `<output_dir>/<task_name>.jsonl`

### Alternatives
1. The directory is created if missing (including parents); if the path exists
   and is not a directory, exit 1.
2. The directory must already exist, and a missing one is an error.

### Choice
Alternative 1. Part 1's `--output <path>` is documented as "created or
overwritten" and the Part 1 implementation already makes parent directories, so
creating the output directory is the consistent behaviour. A path that exists as
a regular file genuinely cannot satisfy "must be a directory".

### Risk: 15
The author most likely prefers: the same, since `os.makedirs(..., exist_ok=True)`
is the obvious one-liner.

---

## T33: Does the multi-task summary keep Part 1's token totals?

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
> - for single-task configs, the stdout summary keeps its previous keys and has
>   no `tasks` object

### Alternatives
1. The multi-task summary is Part 1's summary (including
   `total_prompt_tokens` and `total_completion_tokens`, aggregated across
   tasks) plus a `tasks` object; the JSON block above is abridged.
2. The multi-task summary is exactly the six keys shown plus `tasks`, and the
   token totals are dropped.

### Choice
Alternative 1. "Existing behavior from Part 1 is unchanged unless stated here",
and the only stated summary change is the addition of `tasks`. The bullet about
single-task configs exists to say they gain *nothing*, not that multi-task
configs lose the token keys.

### Risk: 30
The author most likely prefers: the same superset; but their example was
presumably pasted from a real run, and a real run that printed no token keys
would mean alternative 2.

---

## T34: The key set of each per-task summary object

### Spec Text
> ```json
> "gsm8k": {
>   "total": 100,
>   "passed": 85,
>   "failed": 15,
>   "total_api_calls": 142
> }
> ```
> - per-task `total_api_calls` includes judge calls

### Alternatives
1. Exactly the four keys shown.
2. Also per-task token totals, elapsed and throughput, mirroring the top level.

### Choice
Alternative 1. Unlike the top-level object (which Part 1 already defined), the
per-task object is introduced here and the spec shows it in full with no
ellipsis; the accompanying bullet clarifies exactly one of those four keys,
which reads like a complete enumeration.

### Risk: 25
The author most likely prefers: the four keys; a test asserting the exact key
set, or asserting per-task token totals, would decide it.

---

## T35: Scope of the Part 1 override flags in multi-task mode

### Spec Text
> New flags:
> - `--task <name>`: repeatable; run only the selected task or tasks
> - `--eval-model <string>`: override the judge model for all selected
>   `llm_judge` tasks

### Alternatives
1. Part 1's overrides (`--api-url`, `--model`, `--rpm`, `--max-tokens`,
   `--scheme`, `--temperature`, `--n`) apply to every executed task, as if they
   had been written into `defaults` with highest precedence.
2. They are rejected for multi-task configs because they are ambiguous.

### Choice
Alternative 1. The spec lists only two *new* flags and says existing behaviour is
unchanged; the natural place for a global override in a `defaults`/`tasks` config
is on top of `defaults`. `--eval-model`'s own wording ("for all selected ...
tasks") shows the intended scope for a global override.

### Risk: 25
The author most likely prefers: the same; the visible divergence is a
multi-task run with `--scheme greedy`, where alternative 2 would exit 1.

---

## T36: `--eval-model` with no `llm_judge` task selected

### Spec Text
> - `--eval-model <string>`: override the judge model for all selected
>   `llm_judge` tasks

### Alternatives
1. It is a no-op: tasks that are not `llm_judge` ignore it, and a run with no
   judge tasks at all succeeds.
2. It is an error when nothing would use it.

### Choice
Alternative 1. "for all selected `llm_judge` tasks" already restricts the scope;
a flag that applies to a filtered set is conventionally silent when the set is
empty.

### Risk: 10
The author most likely prefers: the same no-op.

---

## T37: `--task` naming something that is not in the config

### Spec Text
> - `--task <name>`: repeatable; run only the selected task or tasks

### Alternatives
1. Exit 1 with a message naming the unknown task.
2. Ignore it, running the tasks that do match (and everything if none match).

### Choice
Alternative 1. A misspelled `--task` under alternative 2 silently runs nothing
and prints an empty `tasks` object, which is the worst possible outcome for the
user; it is also an "input error" in the same class as a missing input file.

### Risk: 20
The author most likely prefers: the same, but a lenient set-intersection
implementation (`selected = [t for t in tasks if t in wanted]`) is easy to write
by accident.

---

## T38: Scheduling and timing across concurrent tasks

### Spec Text
> - requests from different tasks may run concurrently and may be interleaved
> - within each task's output file, row order must still match input order
> - judge calls count toward throughput, `total_api_calls`, and per-task API
>   call totals, and may be interleaved with other work

### Alternatives
1. All selected tasks are launched in one event loop and share the wall clock:
   `elapsed_seconds` runs from the first request of any task to the last
   response of any task, and each task keeps its own in-flight budget derived
   from its own effective `rpm`.
2. Tasks run one after another, and `elapsed_seconds` is the sum of their
   individual windows.
3. One global in-flight budget derived from `defaults.rpm` is shared by all
   tasks.

### Choice
Alternative 1. "may run concurrently and may be interleaved" only makes sense
for tasks sharing a loop, and `rpm` is a per-task config value (it can be
overridden per task), so the budget it implies is per-task. The global elapsed
window is the only one that makes the single top-level `throughput_rpm`
meaningful when tasks overlap.

### Risk: 15
The author most likely prefers: the same; alternative 3 is the plausible
divergence, and it is only observable as a throughput number, not as output
content.

---

## T39: Validating `judge_prompt` and `command_template` fields against rows

### Spec Text
> - `judge_prompt` uses the same template rules as normal prompts
> - `command_template` may reference row fields and `__response__`

> (Part 1) If a placeholder references a missing field, exit with code `1` and
> print an error to stderr naming the row index and missing field.

### Alternatives
1. Placeholders in `judge_prompt` and `command_template` are validated against
   every row up front, exactly like prompt placeholders; `__response__` is
   exempt because it is supplied at runtime.
2. Only `prompt.system`/`prompt.user` are validated; a missing field in a judge
   prompt or a command template surfaces later, or fails that row.

### Choice
Alternative 1. "the same template rules as normal prompts" pulls the whole Part 1
rule across, missing-field check included, and the alternative spends API budget
before discovering a typo. `{__response__}` is never a row field, so it is
excluded from the required-field set everywhere.

### Risk: 25
The author most likely prefers: the same for `judge_prompt` (the spec says so
explicitly); `command_template` is the weaker case, since its rules are listed
separately and never mention validation.

---

## T40: Single-task configs under the new input flags

### Spec Text
> - for single-task configs, `--input <path>` without `=` still behaves as in
>   Part 1
> - for single-task configs, `--output <path>` still writes a single file

### Alternatives
1. Single-task configs also accept `--input <name>=<path>` when `<name>` equals
   `task.name`, and accept `--input-dir` (looking for `<task.name>.jsonl`);
   giving more than one `--input` is an error.
2. Single-task configs accept only a bare `--input <path>`; anything else is an
   error.

### Choice
Alternative 1. The spec gives single-task configs a task name (`task.name`) for
exactly the purpose of naming them in the multi-task machinery, and being able
to point the same command line at either config shape is the useful behaviour. A
value containing `=` whose prefix is not the task name is still treated as a
plain path, so paths with `=` in them keep working.

### Risk: 20
The author most likely prefers: erroring on `--input-dir` with a single-task
config, since the input-handling rules are introduced "for multi-task configs".

---

## T41: A config with both `task` and `tasks`

### Spec Text
> - if the config still uses a top-level `task` key, treat it as the Part 1
>   single-task format; the task name is `task.name`

### Alternatives
1. `task` wins unconditionally; any `tasks`/`defaults` keys are ignored.
2. It is a conflicting config and exits 1.

### Choice
Alternative 1. The rule is stated without qualification - the presence of `task`
selects the format - so no extra error case is needed.

### Risk: 10
The author most likely prefers: the same precedence rule.
