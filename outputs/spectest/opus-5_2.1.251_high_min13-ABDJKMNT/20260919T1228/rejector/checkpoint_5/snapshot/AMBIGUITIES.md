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

### Resolved by checkpoint 4
The agentic worked example extracts `"2730000"` from
`"The total revenue for Q1 and Q2 is $2,730,000."` and passes, so grouped
digits are one number and the separators are dropped. The pattern is now
`-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?`, matching
interpretation 3 with the commas stripped from the extracted value; the sign
handling of interpretation 1 is unchanged.

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

## T20: Whether a single-task (Part 1) config's summary carries `tasks`

### Spec Text
> The stdout summary now includes a `tasks` object keyed by executed task name
> if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format; the task name is `task.name`

### Alternatives
1. Every run prints `tasks`, including Part 1 single-task configs, keyed by
   `task.name`.
2. `tasks` appears only for `defaults`/`tasks` multi-task configs, so a Part 1
   config's summary keeps exactly its Part 1 keys.

### Choice
Interpretation 1. The spec bothers to define the name of a single-task config
(`task.name`), and the only two places a task name is used in Part 2 are task
selection and the `tasks` summary object; a single-task run writes one output
file, so the name would otherwise be inert. One code path for both config
shapes also follows from "the summary now includes".

### Risk: 35
The author may have kept the Part 1 summary untouched for `task:` configs, in
which case a Part 1 fixture asserting the exact summary key set would fail
here. That is the most likely alternative.

## T21: Which keys a per-task summary object has

### Spec Text
> ```json
>     "gsm8k": {
>       "total": 100,
>       "passed": 85,
>       "failed": 15,
>       "total_api_calls": 142
>     },
> ```

### Alternatives
1. Exactly the four documented keys per task.
2. The full top-level shape per task, adding `total_prompt_tokens`,
   `total_completion_tokens`, `elapsed_seconds` and `throughput_rpm`.

### Choice
Interpretation 1: the four keys shown, nothing else. Per-task elapsed time is
meaningless when tasks interleave, and the example is explicit.

### Risk: 15
Only an author who reused the whole summary builder per task would add token
totals; an exact-key assertion is the likely fixture and it matches the example.

## T22: `result.extracted_answer` for `script` and `llm_judge`

### Spec Text
> `result` includes `judge_score`
> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output   (Part 1)

### Alternatives
1. `null` for both: a script's verdict is an exit code, and the judge's number
   is reported as `judge_score`.
2. `llm_judge` reports the string extracted from the *judge's* response (e.g.
   `"8"`) as `extracted_answer`, duplicating `judge_score`.
3. `script` reports the whole response (the `full` default).

### Choice
Interpretation 1. `extracted_answer` describes something pulled out of the
generated response; neither new mode extracts anything from it, and Part 2
introduces `judge_score` precisely because the judge's value needed a home.

### Risk: 40
An author whose evaluator returns a uniform `(passed, extracted)` pair would
naturally leak the judge's extracted string into `extracted_answer`; that is
the most likely alternative for `llm_judge`.

## T23: `judge_score` and `judge_meta` on non-`llm_judge` tasks

### Spec Text
> `result` includes `judge_score`
> `meta` includes a `judge_meta` object with the judge request's token usage,
> latency, model, and finish reason

### Alternatives
1. Both keys exist only for `llm_judge` tasks; other tasks keep the Part 1
   shapes exactly.
2. Both keys are always present, `null` when no judge ran.

### Choice
Interpretation 1. The rules sit inside the `llm_judge` section and Part 1's
row shape is otherwise unchanged, so an `exact_match` row gains nothing.

### Risk: 20
An author building one result dict for all types might always emit
`judge_score: null`; a Part 1 fixture asserting the exact `result` keys argues
against that.

## T24: Sampling settings for the judge request

### Spec Text
> the judge request is a separate API call through the same server
> if `evaluation.model` is omitted, use the task's model

### Alternatives
1. Judge calls are deterministic: `temperature` 0.0, `max_tokens` from the
   task's generation settings.
2. Judge calls reuse the task's generation temperature (e.g. 0.8 for a
   rejection task).

### Choice
Interpretation 1. Only the model is said to carry over, and a scorer asked for
"only a single integer" wants a deterministic decode; reusing a rejection
temperature would make the same response score differently across attempts.

### Risk: 30
A test asserting the judge payload's `temperature` equals the task's would
prefer interpretation 2, which is what an author reusing one request builder
would get.

## T25: Where `judge_meta` sits for a multi-attempt (rejection) row

### Spec Text
> `meta` includes a `judge_meta` object with the judge request's token usage,
> latency, model, and finish reason
> for rejection sampling with multiple attempts it [`meta`] is a list with one
> metadata object per attempt   (Part 1)

### Alternatives
1. Each attempt's metadata object carries the `judge_meta` of the judge call
   that scored that attempt.
2. A single `judge_meta` is attached beside the list, or only the final
   attempt's judge call is reported.

### Choice
Interpretation 1: every judged attempt has exactly one judge call, so the
judge metadata belongs next to the attempt that produced it. `meta` stays a
list of per-attempt objects as in Part 1.

### Risk: 25
The spec only shows the greedy case; an author who records the last judge call
once would differ on a rejection + `llm_judge` row.

## T26: Whether unselected tasks are validated at all

### Spec Text
> when `--task` is present, require input only for selected tasks and ignore
> unselected tasks for validation and execution

### Alternatives
1. Unselected tasks are skipped entirely: their config blocks are never
   validated, so a broken unselected task cannot fail a selected run.
2. Only *input* requirements are relaxed; every task in the file is still
   config-validated up front.

### Choice
Interpretation 1, reading "ignore unselected tasks for validation" literally.
Task configs are therefore built lazily, per selected task.

### Risk: 30
The sentence lives under "Input handling", so the author may well validate the
whole config file first and only relax the input-file requirement — a config
with a broken unselected task would then exit 1 for them.

## T27: How `defaults` and a task's settings are merged

### Spec Text
> `defaults` provides shared values; each task overrides `defaults`
> nested sections such as `prompt`, `generation`, and `evaluation` are merged
> per task using the Part 1 structure

### Alternatives
1. Recursive merge: mappings at any depth merge key by key, scalars and lists
   from the task win.
2. One level only: `defaults.generation` and the task's `generation` merge, but
   deeper mappings (e.g. `evaluation.judge_prompt`) replace wholesale.

### Choice
Interpretation 1. "Nested sections ... are merged" is stated generally, and a
recursive merge agrees with the one-level reading for every documented config;
they differ only for a `judge_prompt` split across `defaults` and a task.

### Risk: 15
The readings coincide on any config shaped like the examples.

## T28: Scope of the Part 1 override flags in a multi-task run

### Spec Text
> New flags:
> - `--task <name>`: repeatable; run only the selected task or tasks
> - `--eval-model <string>`: override the judge model for all selected
>   `llm_judge` tasks

### Alternatives
1. The Part 1 overrides (`--model`, `--api-url`, `--rpm`, `--max-tokens`,
   `--scheme`, `--temperature`, `--n`) apply to every selected task, the way
   `--eval-model` explicitly does.
2. They are rejected, or only apply to single-task configs.

### Choice
Interpretation 1. `--eval-model` is described as applying to all selected
tasks, and nothing marks the Part 1 flags as single-task only; a global
`--model` override is the obvious analogue.

### Risk: 10
`--model` and `--api-url` overrides against a multi-task config are the
natural fixtures and behave identically under this reading.

## T29: `--eval-model` against tasks that are not `llm_judge`

### Spec Text
> `--eval-model <string>`: override the judge model for all selected
> `llm_judge` tasks

### Alternatives
1. It only touches `llm_judge` tasks; other selected tasks are untouched and
   the flag is not an error when none of them judge.
2. Passing it with no `llm_judge` task selected is a usage error.

### Choice
Interpretation 1, which is what the sentence says; a mixed run (`gsm8k` plus
`review`) must still work with one `--eval-model`.

### Risk: 5

## T30: The output directory when it does not exist

### Spec Text
> for multi-task configs, `--output` must be a directory
> write `<output_dir>/<task_name>.jsonl`

### Alternatives
1. Create the directory (including parents) when the run is about to write,
   and reject a path that exists as a file.
2. Require it to exist already and exit 1 otherwise.

### Choice
Interpretation 1: `--output results/` in the spec's own example is an ordinary
"put results here" argument, and Part 1 creates its output file rather than
demanding it exist. Creation happens after validation so a failed run leaves
nothing behind (T14).

### Risk: 20
An author who only checks `output.is_dir()` would exit 1 for a fresh path;
fixtures that pass `tmp_path/"results"` uncreated would then expect failure.

## T31: What `letter` matches

### Spec Text
> `letter`: extract the first uppercase answer choice `A` through `D`; accept
> forms such as `A`, `(A)`, `A)`, or `Answer: A`

### Alternatives
1. The first standalone `A`-`D` (regex `\b[A-D]\b`), so `"The answer is B)
   Paris"` yields `B` and the `A` inside `Answer` is not a candidate.
2. The first `A`-`D` character anywhere, which would extract `A` from
   `"Answer: B"`.
3. Only a letter in one of the four listed shapes, with an anchored
   alternation.

### Choice
Interpretation 1. A word-boundary match accepts every listed form (`A`, `(A)`,
`A)`, `Answer: A`) and the example `"The answer is B) Paris"` → `B`, while
refusing letters embedded in words. Lowercase is not matched, and `E` and
beyond are out of range, both as stated.

### Risk: 25
An author using an alternation of the four literal forms would differ on prose
like `"B is correct"`; one scanning raw characters would differ on `"Answer:
B"`. Both readings agree on the spec's own example; the most likely
alternative is a looser scan anchored on the four literal forms.

## T32: Sign handling in `first_number`

### Spec Text
> `first_number`: extract the first integer or decimal in the response

### Alternatives
1. Same pattern as `last_number`: `-?\d+(?:\.\d+)?`, so `-3` extracts as `-3`.
2. Unsigned, so `-3` extracts as `3`.

### Choice
Interpretation 1, for consistency with T4 and `last_number`, which this method
mirrors word for word.

### Risk: 15
Judge scores and MMLU answers are non-negative, so the readings rarely differ.

## T33: `extract` for `llm_judge` when omitted

### Spec Text
> ```yaml
> evaluation:
>   type: "llm_judge"
>   ...
>   extract: "first_number"
> ```
> Extract methods: ... default `full`   (Part 1)

### Alternatives
1. `llm_judge` defaults to `first_number`, since a threshold comparison needs
   a number out of the judge's reply.
2. The Part 1 default `full` applies, so an omitted `extract` only works when
   the judge replies with a bare number.

### Choice
Interpretation 1. Both readings score `"8"` identically; the default only
matters for a chattier judge, where `first_number` is the intent of a scoring
prompt.

### Risk: 20
Every documented `llm_judge` config sets `extract` explicitly, so this is
unlikely to be probed; an author with one shared default would use `full`.

## T34: A judge call that fails or returns no number

### Spec Text
> score `>= threshold` passes
> `result` includes `judge_score`

### Alternatives
1. No usable score means the row fails: `passed: false`, `judge_score: null`,
   and `judge_meta: null` when the call itself never succeeded.
2. The row's `passed` stays `null`, or the run aborts.

### Choice
Interpretation 1, matching Part 1's treatment of an unusable response (a row
with nothing to compare fails rather than erroring).

### Risk: 20
The generated response still exists, so an author might keep the output and
report `passed: false` — which is what this does — but differ by writing
`judge_score: 0`.

## T35: Requiring `threshold` and `command_template`

### Spec Text
> ```yaml
> evaluation:
>   type: "script"
>   command_template: "python3 -c \"{test_code}\""
>   success_exit_code: 0
> ```
> `threshold: 7`

### Alternatives
1. `command_template` and `threshold` are required for their types (exit 1
   when missing); `success_exit_code` defaults to `0`.
2. All three are required, or `threshold` defaults to some value.

### Choice
Interpretation 1: a script evaluation has nothing to run without a command and
a judge has nothing to compare against without a threshold, while `0` is the
documented and only sensible default exit code for "the script passed".

### Risk: 20
An author may also require `success_exit_code` explicitly; every example sets
it, so the default is rarely exercised.

## T36: `--input <task>=<path>` against a single-task config

### Spec Text
> for single-task configs, `--input <path>` without `=` still behaves as in
> Part 1

### Alternatives
1. A single-task config also accepts `name=path` when `name` is the task's
   name; anything else is treated as a plain path.
2. `=` is never interpreted for single-task configs, so `gsm8k=math.jsonl` is
   a (missing) file name.

### Choice
Interpretation 1. "Without `=`" implies the `=` form is at least meaningful,
and a path that happens to contain `=` still resolves because the prefix must
match the configured task name.

### Risk: 15
Both readings agree on the documented single-task invocation.

## T37: Row fields required by `command_template` and `judge_prompt`

### Spec Text
> `command_template` may reference row fields and `__response__`
> `judge_prompt` uses the same template rules as normal prompts
> If a placeholder references a missing field, exit with code `1`   (Part 1)

### Alternatives
1. Placeholders in `command_template` and the judge prompt are validated
   against every row up front, exactly like prompt placeholders.
2. Only `prompt` placeholders are validated; a missing `{criteria}` surfaces
   later, mid-run.

### Choice
Interpretation 1. The judge prompt "uses the same template rules as normal
prompts", and failing fast beats discovering the gap after paying for
generations.

### Risk: 25
An author who validates only the prompt block would instead fail the affected
row (or crash) during the run.

## T38: The default `icl.strategy`

### Spec Text
> `icl.strategy` is one of `fixed`, `random`, or `round_robin`
> - `fixed`: always use the first setup

### Alternatives
1. `strategy` is optional and defaults to `fixed`.
2. `strategy` is required whenever `icl.setups` is present.
3. It defaults to `round_robin`, so that several setups are all exercised.

### Choice
Interpretation 1. The YAML examples show `strategy` alongside `k`, which the
spec explicitly calls optional ("`icl.k` defaults to..."), and `fixed` is the
degenerate behaviour that also matches a single-setup block, which is the only
sensible reading when one setup is declared without a strategy.

### Risk: 15
An author could require the key; a fixture omitting `strategy` would then be
expected to exit 1.

## T39: The default `num_solutions`

### Spec Text
> legacy compatibility: when `num_solutions == 1` and no ICL is configured,
> keep the Part 1 rejection behavior

### Alternatives
1. `num_solutions` defaults to 1, which is exactly the legacy case.
2. It defaults to `generation.n` for rejection tasks.

### Choice
Interpretation 1. Part 1 and Part 2 configs have no `num_solutions` key and
must keep working, which is only true if the default is 1.

### Risk: 3
Interpretation 2 would break every earlier fixture, so it is very unlikely.

## T40: What `generation.n` means once `max_attempts` applies

### Spec Text
> ```yaml
>     generation:
>       scheme: "rejection"
>       temperature: 0.7
>       n: 5
>       max_attempts: 15
> ```
> `max_attempts` applies to rejection sampling in this part

### Alternatives
1. Outside the legacy path, `n` is ignored: `max_attempts` alone bounds the
   attempts and `num_solutions` alone says how many passes to collect.
2. `n` still caps attempts, so the effective budget is `min(n, max_attempts)`.
3. `n` becomes the number of solutions to collect when `num_solutions` is
   absent.

### Choice
Interpretation 1. The spec names only `max_attempts` and `num_solutions` when
describing the new schemes, and keeps `n` alive solely through the legacy
sentence. In the sample config `n: 5` equals `num_solutions: 5` and
`max_attempts: 15` equals `3 * num_solutions`, so `n` carries no information
the other two keys do not.

### Risk: 25
An author who wrote the loop as "at most `n` batches" would cut a
`max_attempts: 15`, `n: 5` fixture off after 5 attempts.

## T41: `greedy` with `num_solutions > 1` and no ICL

### Spec Text
> - `greedy` with ICL: generate at temperature `0` once per selected setup and
>   stop when `num_solutions` solutions are collected or all setups are
>   exhausted; because the same setup is deterministic, the maximum number of
>   produced solutions is the number of available setups

### Alternatives
1. Without ICL there is a single (empty) setup, so greedy makes one attempt
   and emits one solution regardless of `num_solutions`.
2. Greedy repeats the identical request `num_solutions` times and emits
   `num_solutions` identical solutions.

### Choice
Interpretation 1. The spec only defines greedy's multi-solution behaviour in
terms of setups, caps it at the number of setups because "the same setup is
deterministic", and tells implementations not to "retry the same greedy setup
to manufacture additional outputs". With no ICL there is exactly one prompt,
so the same reasoning caps the row at one solution.

### Risk: 30
An author whose loop is "for i in range(num_solutions)" with a setup chooser
that returns `None` would emit `num_solutions` duplicate outputs.

## T42: Whether evaluation gates which solutions are emitted

### Spec Text
> - `sample` with ICL: make one sampled generation per requested solution using
>   the chosen ICL strategy; evaluation does not gate whether a solution is
>   included
> - `greedy` with ICL: ... stop when `num_solutions` solutions are collected

### Alternatives
1. Only `rejection` gates: greedy and sample emit every attempt that produced
   text, whether or not it passed, and `result.passed` merely counts the
   passing ones.
2. Greedy also drops failing attempts, since it speaks of "solutions
   collected"; the non-gating sentence is attached to `sample` only.

### Choice
Interpretation 1. Rejection is the only scheme the spec describes as
"generating and evaluating until ... passing solutions have been collected";
greedy and sample are described purely in terms of how many requests to make.
Dropping a greedy output would also lose the `icl_setup` record the greedy
examples emphasise.

### Risk: 20
An author who shares one "collect" helper across schemes might filter greedy
outputs by `passed` as well.

## T43: Which keys `result` carries in list format

### Spec Text
> ```json
>   "result": {
>     "passed": 2,
>     "failed": 5,
>     "attempts": 7
>   },
> ```

### Alternatives
1. Exactly `passed`, `failed`, `attempts`; `extracted_answer` and
   `judge_score` are Part 1 fields of the single-solution shape and disappear.
2. `extracted_answer` (and `judge_score` for judged tasks) is kept, holding
   the value from the first or last solution.
3. The per-solution objects in `output` gain `extracted_answer`.

### Choice
Interpretation 1. The example is a complete `result` object for a row with
seven attempts, and neither field has a meaningful single value once several
solutions are kept.

### Risk: 25
An author reusing one row builder might leave `extracted_answer: null` in
place.

## T44: `meta` entries for attempts whose API call failed

### Spec Text
> `meta` is a list with one entry per attempt
> each metadata entry includes `icl_setup` and `evaluation_passed`

### Alternatives
1. Only attempts that got a response contribute an entry, as in Part 1 where a
   failed row's `meta` is `null`; the list can be shorter than `attempts`.
2. Every attempt contributes an entry, synthesising nulls for model, tokens
   and latency when the call never succeeded.

### Choice
Interpretation 1. Every documented metadata field (`model`, token counts,
`latency_ms`, `finish_reason`) comes from a response, and Part 1 already
reports no metadata for an attempt that produced none. `attempts` still counts
the failed attempt, so the count is not lost.

### Risk: 35
"One entry per attempt" is explicit, so an author who pads the list would
expect `len(meta) == result.attempts` on an always-failing fixture.

## T45: Whether a failed API attempt ends a rejection row

### Spec Text
> `rejection` with ICL: keep generating and evaluating until `num_solutions`
> passing solutions have been collected or `max_attempts` is exhausted

### Alternatives
1. A failed call is one spent attempt; the row keeps going until it collects
   enough passes or exhausts `max_attempts`.
2. A failed call ends the row immediately, as Part 1's rejection loop does.

### Choice
Interpretation 1. The new loop has exactly two documented stopping conditions,
and abandoning a five-solution row because of one transient failure would
contradict "keep generating".

### Risk: 25
An author who extended the Part 1 loop in place may have kept its early return
on a failed call.

## T46: Whether `round_robin` cycles per row or across the whole task

### Spec Text
> Round-robin order with setups `[A, B, C]`:
> - attempt 1 uses `A`
> - attempt 2 uses `B`

### Alternatives
1. The cycle is per input row: every row starts at the first setup.
2. The cycle is shared by the whole task, so a row's first attempt continues
   where the previous row left off.

### Choice
Interpretation 1. Rows are processed concurrently, so a shared cursor would
make each row's setups depend on scheduling order and could not be asserted;
per-row cycling reproduces the documented attempt sequence for every row.

### Risk: 12
A sequential implementation might share one counter, but its own tests could
only assert that on a single-row fixture, where both readings agree.

## T47: Where `max_attempts` is configured

### Spec Text
> ```yaml
>     generation:
>       scheme: "rejection"
>       temperature: 0.7
>       n: 5
>       max_attempts: 15
>     num_solutions: 5
> ```

### Alternatives
1. `max_attempts` lives inside `generation`, and `num_solutions` beside it at
   task level, exactly as the example indents them.
2. Either key is accepted at either level.

### Choice
Interpretation 1, following the example's indentation literally.

### Risk: 8
A lenient implementation would also read a task-level `max_attempts`; a
fixture written that way would fail here.

## T48: Whether the new summary fields appear for legacy tasks

### Spec Text
> Per-task summary fields gain:
> ```json
> {"tasks": {"gsm8k": {"total": 100, "total_solutions": 450,
>  "avg_solutions_per_input": 4.5, "total_api_calls": 850}}}
> ```

### Alternatives
1. Every task reports `total_solutions` and `avg_solutions_per_input`; a
   single-solution task simply reports one solution per answered row.
2. The fields only appear for tasks that use the list output format.

### Choice
Interpretation 1. The sentence is unconditional, unlike the output-format rule
which spells out when the shape changes, and per-task counts are built in one
place for every task.

### Risk: 20
An author who branched the summary on the same "list format" predicate would
omit the fields for a Part 1 style task.

## T49: How `avg_solutions_per_input` is computed

### Spec Text
> "total": 100,
> "total_solutions": 450,
> "avg_solutions_per_input": 4.5,

### Alternatives
1. `total_solutions / total`, rounded to two decimals, and `0.0` when the task
   has no rows.
2. The unrounded float, so a 1/3 ratio prints as 0.3333333333333333.
3. The average over rows that produced at least one solution.

### Choice
Interpretation 1. The example divides emitted solutions by input rows, and the
summary already rounds `elapsed_seconds` and `throughput_rpm` rather than
printing raw floats.

### Risk: 20
An author who does not round would report more digits for a fixture whose
ratio is not exact; the integer/zero cases agree either way.

## T50: A row where every attempt produced nothing

### Spec Text
> `output` becomes a list of objects
> `result.failed` is the count of failed attempts

### Alternatives
1. `output` is an empty list and `meta` an empty list; the row still reports
   its attempts.
2. `output` is `null`, mirroring Part 1's failed row.

### Choice
Interpretation 1. In list format `output` is described as a list without
exception, and an empty list is the honest rendering of "no solutions".

### Risk: 20
An author reusing Part 1's "null when nothing came back" branch would write
`null` instead.

## T51: `--icl-strategy` and `--icl-k` against a task with no ICL

### Spec Text
> New flags:
> - `--icl-strategy <fixed|random|round_robin>`
> - `--icl-k <int>`
> CLI flags override config values

### Alternatives
1. They override values inside an existing `icl` block and are ignored by
   tasks that configure no ICL.
2. They configure ICL on their own, which cannot work because setups can only
   come from the config, so the run should fail.

### Choice
Interpretation 1. The flags name `icl.strategy` and `icl.k`; with no setups
there is nothing to select from, and failing an otherwise valid run because a
flag was passed for a sibling task would be surprising in a multi-task run.

### Risk: 10
An author might error on the flag when no `icl` block exists.

## T52: An ICL example the prompt template cannot render

### Spec Text
> each example's `input` is rendered with the task's `prompt.user` template
> malformed lines or missing keys must terminate the run with exit code 1
> before any API requests are sent

### Alternatives
1. Rendering happens while the config is validated, so an example whose
   `input` lacks a template field exits 1 before any request.
2. Rendering happens per attempt, so the failure surfaces mid-run.

### Choice
Interpretation 1. The spec already insists that broken example data stops the
run before any API request, and Part 1 validates prompt placeholders up front
for the same reason.

### Risk: 20
An author who renders lazily would crash or fail the row mid-run instead of
exiting 1 cleanly.

## T53: What `passed` counts per task once a row has several solutions

### Spec Text
> "tasks": {"gsm8k": {"total": 100, ...}}
> `result.passed` is the count of passing solutions

### Alternatives
1. The summary keeps counting rows: a row is passed when it produced at least
   one passing solution, failed otherwise.
2. The summary counts solutions, so `passed` sums `result.passed` over rows.

### Choice
Interpretation 1. Part 2 defines `total`/`passed`/`failed` as row counts that
must sum to `total`, and the new `total_solutions` field exists precisely
because solutions are counted separately.

### Risk: 25
An author could let `passed` follow the solution counts, which would make
`passed + failed` exceed `total`.

## T54: `icl.k` outside the number of available examples

### Spec Text
> `icl.k` defaults to all examples in the selected setup
> if `k` is smaller than the number of examples in the setup, use the first `k`

### Alternatives
1. A `k` larger than the setup silently uses every example; `k` must be a
   positive integer.
2. A `k` larger than the setup is a configuration error.

### Choice
Interpretation 1. The spec only defines behaviour for `k` smaller than the
setup, and the default is "all examples", so clamping is the natural reading;
setups of different sizes can then share one `k`.

### Risk: 10
An author validating `k` against each setup would exit 1 for the oversized
case.

## T55: `icl` blocks and `defaults`

### Spec Text
> `num_solutions` may be set in `defaults` or per task    (Part 3)
> nested sections such as `prompt`, `generation`, and `evaluation` are merged
> per task    (Part 2)

### Alternatives
1. `icl` is merged like any other nested section: a task's `setups` list
   replaces the default list wholesale, while sibling keys such as `k` and
   `strategy` are inherited.
2. `icl` may only be declared per task.

### Choice
Interpretation 1. Part 2's merge is generic over nested mappings, and Part 3
gives no reason to exempt `icl`; list values replace rather than concatenate,
as everywhere else in the merge.

### Risk: 15
An author might append default setups to the task's, or forbid `icl` in
`defaults` altogether.

## T56: Strictness of the example JSONL file

### Spec Text
> file-backed setups must be valid JSONL where each non-empty line has
> `{"input": <object>, "output": <string>}`; malformed lines or missing keys
> must terminate the run with exit code 1 before any API requests are sent

### Alternatives
1. Blank lines are skipped; every other line must parse and must carry an
   object `input` and a string `output`, and a missing file is likewise an
   exit-1 configuration error. Lines beyond `k` are validated too.
2. Only the first `k` lines are validated, since the rest are never used.

### Choice
Interpretation 1. The rule is stated about the file, not about the examples
actually used, and "each non-empty line" makes blank lines explicitly legal.

### Risk: 10
An author who truncates before validating would accept a file whose tail is
malformed.

## T57: `greedy` with ICL and `num_solutions == 1`

### Spec Text
> for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
> strategy and instead walks setups in declared order, at most once per setup

### Alternatives
1. With `num_solutions == 1`, greedy follows the configured strategy like any
   other scheme, so `random` really does pick a random setup.
2. Greedy always takes the first declared setup, whatever the strategy.

### Choice
Interpretation 1. The override is scoped explicitly to `num_solutions > 1`;
outside it the general strategy rules apply.

### Risk: 15
The two readings only differ for `random` (and for `round_robin` they agree on
the first attempt), so a fixture would have to test `random` to notice.

## T58: `generation.temperature` for the `agentic` scheme

### Spec Text
> ```yaml
>     generation:
>       scheme: "agentic"
>       max_iterations: 10
>       temperature: 0.0
> ```

### Alternatives
1. `agentic` behaves like `greedy` for temperature: the value is optional and
   defaults to `0.0`, and `0.0` is legal. A value above zero is sent as
   configured, since an agentic task may also want sampling.
2. `agentic` is a sampling scheme like `sample`/`rejection`, so a temperature
   is required and must be `> 0` -- which would make the spec's own example
   invalid.
3. `agentic` forces `0.0` the way `greedy` does, ignoring any other value.

### Choice
Interpretation 1. The example configures `temperature: 0.0`, so the earlier
"must be > 0" rule cannot apply to this scheme; nothing says the value is
overridden either, so a configured temperature is passed through.

### Risk: 20
An author who reused the greedy branch would force `0.0` and ignore a
configured `0.7`.

## T59: The default `max_iterations`

### Spec Text
> ```yaml
>       max_iterations: 10
> ```
> If `max_iterations` is reached first, output `null` and use
> `finish_reason: "max_iterations"`.

### Alternatives
1. `max_iterations` defaults to `10`, the value the spec's example uses.
2. `max_iterations` is required for `agentic` tasks, so omitting it exits 1.
3. Some other default (unbounded, 5, ...).

### Choice
Interpretation 1. The only number the spec ever names is `10`, and a missing
bound would let a looping model run forever.

### Risk: 25
An author who made the key required would expect exit code 1 from a task that
omits it.

## T60: What "the first required parameter" means

### Spec Text
> `static_map`: look up the first required parameter in `mapping`; if absent,
> return `default`, which defaults to `"NOT_FOUND"`

### Alternatives
1. The first entry of the tool's `parameters.required` list; with no such
   list, the first declared property.
2. The first key of the arguments object the model sent.
3. The first declared property, whether or not it is required.

### Choice
Interpretation 1. "Required parameter" names the schema's `required` list, and
falling back to the first property keeps a tool with no `required` list
usable. The argument's value -- not its name -- is the lookup key.

### Risk: 15
The readings only diverge for tools whose `required` list is absent or does not
lead with the mapped key; the natural fixture has one required parameter.

## T61: The `script` handler's timeout and its error text

### Spec Text
> `script`: run `command` with the value of `arg_field` as a single
> command-line argument, capture stdout, and return it; on timeout or
> non-zero exit, return `"ERROR: <stderr or timeout message>"`

### Alternatives
1. Reuse the 10s timeout the `script` evaluation already uses, and report
   `"ERROR: command timed out after 10s"`.
2. Some other bound (30s, 60s, none) and other wording.

### Choice
Interpretation 1. The spec sets no number here, and the pipeline already
defines 10s as how long a task-supplied command may run. The exact timeout
wording is unconstrained beyond the `ERROR: ` prefix.

### Risk: 30
The prefix is specified and the message is not, so a fixture that asserts the
whole string would only match by luck; the author most likely asserts
`startswith("ERROR:")`.

## T62: Whether script stdout is stripped

### Spec Text
> run `command` with the value of `arg_field` as a single command-line
> argument, capture stdout, and return it

### Alternatives
1. Return `stdout` with surrounding whitespace stripped, so
   `python3 -c "print(6 * 7)"` yields `"42"`.
2. Return stdout verbatim, so the same call yields `"42\n"`.

### Choice
Interpretation 1. The result is fed back to the model as a tool message and
compared in test fixtures as a value; a trailing newline from `print` is an
artefact of the command, not part of the answer.

### Risk: 35
A verbatim implementation is equally defensible, and the natural fixture
(`print(...)`) is exactly where the two differ.

## T63: Tool calls in the iteration that hits `max_iterations`

### Spec Text
> 3. If the response contains `tool_calls`, execute every tool call, append
>    the assistant tool-call message and the tool result messages to the
>    conversation, increment the iteration count, and continue.
> 5. If `max_iterations` is reached first, output `null` and use
>    `finish_reason: "max_iterations"`.

### Alternatives
1. The limit bounds the number of API requests. The last request's tool calls
   are executed and recorded (step 3 runs before the limit is re-checked), so
   a run capped at 3 makes 3 requests, reports `iterations: 3`, and records
   the calls of all three.
2. The last response's tool calls are discarded, because the loop stops as
   soon as the limit is known to be reached.

### Choice
Interpretation 1. The spec orders execution before the limit check, and
`result.iterations` is defined as "the number of API requests in the loop",
which the request count matches exactly.

### Risk: 30
`iterations` agrees under both readings; only the trailing `tool_calls`
entries differ, and an author who checks the limit first would drop them.

## T64: `meta.finish_reason` when the final response says something else

### Spec Text
> `meta.finish_reason` is `"stop"` for a final text response and
> `"max_iterations"` when the iteration limit is hit

### Alternatives
1. The two literal values are the whole vocabulary: a loop that ends with
   final text reports `"stop"` even if the API said `"length"`. The API's own
   value survives in `iterations_detail`.
2. Pass the last response's `finish_reason` through, so a truncated final
   answer reports `"length"`.

### Choice
Interpretation 1. The sentence defines the field by outcome, not by echo, and
`iterations_detail` already carries the per-request reasons.

### Risk: 20
The two agree on every fixture whose final response says `"stop"`, which is
what a mock naturally returns.

## T65: What `meta.latency_ms` measures

### Spec Text
> `meta.latency_ms` is total wall-clock time for the loop

### Alternatives
1. Wall-clock time from the start of the loop to its end, so it also covers
   tool execution and any waiting for a request slot.
2. The sum of the per-iteration latencies.

### Choice
Interpretation 1, which is what "wall-clock time for the loop" says. It is
therefore always at least the sum of the iteration latencies.

### Risk: 10
A fixture can only tell the two apart by making tool execution or queuing
slow; both satisfy a "greater than one request" assertion.

## T66: Which keys a list-format `meta` entry carries

### Spec Text
> in that list format, per-loop agentic metadata lives in each `meta` entry:
> keep checkpoint 3's `icl_setup` / `evaluation_passed` fields and also record
> that loop's aggregated `total_prompt_tokens`, `total_completion_tokens`,
> `total_tokens`, `latency_ms`, `finish_reason`, and `iterations_detail`

### Alternatives
1. Exactly those eight keys. The per-request keys of checkpoint 3 (`model`,
   `prompt_tokens`, ...) are replaced by the aggregates, and `iterations` and
   `tool_calls` do not appear.
2. Also carry `iterations` and `tool_calls` per loop, since the single-row
   format records them.
3. Keep checkpoint 3's per-request keys alongside the aggregates.

### Choice
Interpretation 1. The sentence enumerates what to record and names neither
`iterations` nor `tool_calls`; the aggregates are the loop-level answer to the
per-request fields they replace.

### Risk: 30
Only a fixture that compares the entry's whole key set notices; an author who
reused one metadata builder for both formats would include the extra keys.

## T67: `result` in the agentic list format

### Spec Text
> `result.passed` is `2`, `result.failed` is `0`, and `result.attempts` is `2`

### Alternatives
1. `result` keeps exactly checkpoint 3's three keys; `iterations` and
   `tool_calls` are single-row-format fields only.
2. `result` also aggregates `iterations` and `tool_calls` across the loops.

### Choice
Interpretation 1. The worked example lists the three keys, and per-loop data
belongs to the per-loop `meta` entries rather than to a row-level total.

### Risk: 25
An author may have summed `iterations` across loops into `result`.

## T68: The exact tail of each built-in template

### Spec Text
> ```text
> <|im_start|>system
> {system_content}<|im_end|>
> <|im_start|>user
> {user_content}<|im_end|>
> <|im_start|>assistant
> ```

### Alternatives
1. Each template ends with the marker that opens the assistant's turn plus the
   separator the real format uses: `<|im_start|>assistant\n` for chatml,
   `<|start_header_id|>assistant<|end_header_id|>\n\n` for llama3,
   `<|assistant|>\n` for zephyr, and `[/INST]` with nothing after it for
   mistral.
2. The rendered string ends exactly at the last visible character, with no
   trailing newline at all.
3. Every template ends with a single `\n`, reading the code fence literally.

### Choice
Interpretation 1. The blocks are the well-known chat formats, whose generation
prompts end with the separator that follows the role header -- one newline
after `<|im_start|>assistant`, a blank line after llama3's header, which is
also how the spec's own block separates each header from its content.

### Risk: 40
This is a whole-string comparison on generated text, so any disagreement shows
up; an author transcribing the fence literally would emit one `\n` everywhere,
llama3 included.

## T69: The `mistral` template beyond one system and one user turn

### Spec Text
> ```text
> [INST] {system_content}
>
> {user_content} [/INST]
> ```
> built-in templates must handle multi-turn conversations by repeating the
> correct role markers for every message

### Alternatives
1. The system text joins the first instruction block; each later user (or
   tool) turn opens its own `[INST] ... [/INST]`, and an assistant turn is
   ` {content}</s>` between them.
2. Repeat the system text in every instruction block.
3. Render assistant turns with an explicit marker of their own.

### Choice
Interpretation 1, which is Mistral's own convention and the only reading under
which the two-message case reduces to the block the spec prints.

### Risk: 35
Mistral has no system or tool markers to "repeat", so multi-turn rendering is
the least constrained of the four templates.

## T70: Tool-role formatting in the built-in templates

### Spec Text
> execute those calls and feed the results back into the next prompt
> iteration using the template's tool-role formatting

### Alternatives
1. Render a tool result as an ordinary turn whose role name is `tool`:
   `<|im_start|>tool`, `<|tool|>`, `<|start_header_id|>tool<|end_header_id|>`,
   and a fresh `[INST] ... [/INST]` for mistral.
2. Use each format's own convention for tool output, e.g. llama3's `ipython`
   header.
3. Wrap the result in `<tool_response>` tags inside a user turn.

### Choice
Interpretation 1. The spec calls it "the template's tool-role formatting", so
the role marker is the template's and the role is `tool`; none of the four
blocks it prints mentions a special tool role.

### Risk: 40
The prompt text is directly assertable, and an author following llama3's real
tool convention would emit `ipython` instead.

## T71: How tool definitions are rendered into a completions prompt

### Spec Text
> tool definitions are rendered into the prompt instead of being sent as a
> native `tools` field

### Alternatives
1. Append a tools section to the system message: the JSON function schema of
   every tool, plus the `<tool_call>` block format the model should answer in.
2. Emit the section as a separate system (or user) turn.
3. Render a prose description of each tool rather than its JSON schema.

### Choice
Interpretation 1. The tool JSON is exactly what the chat endpoint receives, so
reusing it keeps the two modes describing the same thing, and the system turn
is where instructions about the conversation belong. The spec fixes the
`<tool_call>` shape the model replies with, so that shape is documented in the
prompt.

### Risk: 45
The wording of this section is entirely unconstrained; only assertions about
tool names and descriptions appearing in the prompt can be expected to agree.

## T72: The default `chat_template`

### Spec Text
> ```yaml
> defaults:
>   api_type: "completions"
>   chat_template: "llama3"
> ```

### Alternatives
1. `chat_template` defaults to `chatml` when a completions task does not name
   one.
2. `chat_template` is required whenever `api_type` is `completions`.

### Choice
Interpretation 1. Nothing marks the key as required, and `chatml` is the first
template the spec lists and the most generic of the four.

### Risk: 20
An author who made the pair required would exit 1 where this implementation
renders ChatML.

## T73: Which calls `api_type` applies to

### Spec Text
> When `api_type` is `"completions"`, send requests to
> `{api_url}/v1/completions` with a rendered prompt string instead of a
> messages array.

### Alternatives
1. `api_type` is a property of the task's endpoint, so its `llm_judge` calls
   use the same endpoint and template as its generation calls.
2. Judge calls stay on the chat endpoint.

### Choice
Interpretation 1. The setting is described for the task, not for one kind of
call, and a server that serves completions is the same server the judge model
runs on.

### Risk: 15
Only a config combining `api_type: completions` with `llm_judge` notices.

## T74: Whether an agentic `meta` keeps the `model` field

### Spec Text
> ```json
>   "meta": {
>     "total_prompt_tokens": 850,
>     "total_completion_tokens": 120,
>     "total_tokens": 970,
>     "latency_ms": 1200,
>     "finish_reason": "stop",
>     "iterations_detail": [...]
>   }
> ```

### Alternatives
1. The agentic `meta` is exactly the six documented keys, and each
   `iterations_detail` entry is exactly the five documented keys; the `model`
   field of the earlier per-request metadata is not repeated.
2. Keep `model` alongside them, since earlier checkpoints record it on every
   metadata object.

### Choice
Interpretation 1. Both objects are printed in full in the spec, and neither
shows `model`.

### Risk: 25
An author who built the agentic metadata by extending the existing per-request
object would still carry `model`.

## T75: A request inside the loop that fails permanently

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 times. After the
> third failure, treat that row as failed, emit `null` output for it
> (part 1)

### Alternatives
1. The loop stops, the row's output is `null`, evaluation fails as for any
   unusable output, and `meta.finish_reason` is `"error"` -- neither of the
   two documented reasons applies, and the run did not reach its iteration
   limit.
2. Report `"max_iterations"` anyway, as the only non-`stop` reason named.
3. Report the row with no metadata at all, as part 1 does for a failed call.

### Choice
Interpretation 1, with one refinement: a loop whose *first* request fails has
no per-iteration data at all, so it keeps part 1's `meta: null` (see T44).
Later failures leave the iterations that did complete.

### Risk: 30
The spec names only `"stop"` and `"max_iterations"`, so an author who exhausted
that vocabulary would report one of them, most likely `"error"`-free
`"max_iterations"`.

## T76: Whether an agentic task must declare tools

### Spec Text
> Agentic tasks let the model call tools in a loop before producing a final
> answer.

### Alternatives
1. `tools` is optional: an agentic task with no tools is simply a loop that
   ends on its first response.
2. `tools` is required for `scheme: agentic`, so omitting it exits 1.

### Choice
Interpretation 1. The spec lists no required keys for the block, and a
tool-less agentic task still has well-defined behaviour.

### Risk: 10
A fixture would have to configure an agentic task with no tools at all.

## T77: A tool call naming a tool the task does not declare

### Spec Text
> execute every tool call ... each recorded tool call stores `iteration`,
> `tool`, parsed `args`, and the handler `result`

### Alternatives
1. Record the call with `result: "ERROR: unknown tool 'x'"` and feed that back,
   so the model can recover -- the same shape the `script` handler uses for
   its failures.
2. Skip the call entirely and record nothing.
3. Fail the row.

### Choice
Interpretation 1. Every call is recorded, and the `ERROR: ` convention already
exists for a handler that cannot produce a value.

### Risk: 20
The message text is unconstrained; only a fixture with a deliberately unknown
tool name compares it.

## T78: How `num_solutions` and ICL bound an agentic row

### Spec Text
> `agentic` also works with ICL and `num_solutions`; each solution is an
> independent loop

### Alternatives
1. An agentic row starts exactly `num_solutions` loops, and the configured ICL
   strategy picks a setup for each -- the `sample` budget, without rejection's
   retry gate or greedy's one-pass walk over setups.
2. Agentic borrows rejection's budget, retrying until `num_solutions` loops
   pass evaluation.
3. Agentic walks the declared setups once, as greedy does.

### Choice
Interpretation 1. The worked example has `num_solutions: 2` producing exactly
two loops and `result.attempts` of `2`, with no mention of retries; the
rejection and greedy rules are stated for those schemes.

### Risk: 15
The example pins the counts for the passing case; the readings only diverge
once a loop fails.

## T79: The messages appended after a tool-calling response

### Spec Text
> append the assistant tool-call message and the tool result messages to the
> conversation

### Alternatives
1. Append the assistant message exactly as the API returned it, then one
   `{"role": "tool", "tool_call_id": <id>, "content": <result>}` message per
   call -- the OpenAI convention. In completions mode the assistant turn is
   the response text, and the tool turns are rendered by the template.
2. Fold all results into a single tool message.
3. Use the older `{"role": "function", "name": ...}` shape.

### Choice
Interpretation 1. The spec quotes the "normal OpenAI shape" for tool calls, so
the replies follow the same convention, one message per call.

### Risk: 20
A fixture that inspects the second request's `messages` sees the difference;
the one-message-per-call convention is what OpenAI-compatible servers require.

## T80: Where `rpm` is configured and what its absence means

### Spec Text
> ```yaml
> defaults:
>   rate_limits:
>     rpm: 100
> ```
> - continue to enforce RPM, now using a sliding 60-second window
> - if `rpm` is omitted, RPM limiting is disabled for that task

### Alternatives
1. `rate_limits.rpm` is the new home for the setting, the Part 1 top-level
   `rpm` key is still honoured as a fallback, and a task that gives neither
   runs with RPM limiting off -- replacing Part 1's default of `60`.
2. Keep Part 1's default of `60` when the key is missing, reading "omitted" as
   "explicitly set to null".
3. Read only `rate_limits.rpm` and ignore a top-level `rpm`, breaking Part 1
   configs.

### Choice
Interpretation 1. The rule is stated unconditionally, so an absent `rpm` is an
absent limit; keeping the top-level key working costs nothing and leaves every
earlier config running as before.

### Risk: 20
The author might drop the top-level `rpm` key entirely; a fixture that sets
`rpm:` at the task level and expects it ignored would see the difference.

## T81: The default `max_concurrent`

### Spec Text
> - `max_concurrent` is a hard cap on in-flight requests independent of RPM and
>   TPM

### Alternatives
1. When `max_concurrent` is not configured, keep Part 2's in-flight rule: up
   to `rpm` requests (capped at 256), or 256 when RPM limiting is off.
2. Default to `10`, the value shown in the example config.
3. Leave concurrency unbounded.

### Choice
Interpretation 1. "Existing behavior from earlier parts is unchanged unless
stated here", and the spec states only what a configured `max_concurrent`
does, so the earlier fan-out rule stands when the key is absent.

### Risk: 25
If the author's implementation hard-codes a default of 10, a throughput
fixture against a wide server would pace differently.

## T82: Converting a word count into tokens

### Spec Text
> - before sending a request, estimate prompt tokens by counting words in the
>   rendered messages using `1 token ~= 0.75 words`, rounded up

### Alternatives
1. `tokens = ceil(words / 0.75)`, i.e. one token buys 0.75 of a word, so a
   prompt needs more tokens than it has words.
2. `tokens = ceil(words * 0.75)`.

### Choice
Interpretation 1. The dry-run section estimates the same quantity as
`average prompt word count * 1.33`, and `1 / 0.75 = 1.333...`, so the two
sections only agree under this reading.

### Risk: 10
The two sections pin each other; only a test that inspects an internal
estimate for a tiny prompt could distinguish them.

## T83: What text the prompt estimate counts

### Spec Text
> - estimate prompt tokens by counting words in the rendered messages

### Alternatives
1. Concatenate the `content` of every message that will be sent -- system, ICL
   turns, the row's user turn, and any tool-result turns already in an agentic
   conversation -- and count whitespace-separated words. In completions mode,
   count the rendered prompt string instead.
2. Count only the user message.
3. Count the serialised JSON payload, including role names and tool schemas.

### Choice
Interpretation 1. "The rendered messages" is the whole conversation about to be
sent, and word counting is described as a text measure, so the roles and the
JSON scaffolding are not words of the prompt.

### Risk: 25
The estimate only reaches an observable place through TPM pacing, where a
difference of a few words per request rarely changes the schedule; a unit-level
fixture over the estimator would see it.

## T84: Whether recorded usage replaces the reservation

### Spec Text
> - reserve against `estimated_prompt_tokens + max_tokens` before dispatch
> - after the response arrives, record actual `prompt_tokens + completion_tokens`
>   from the API response in the TPM window

### Alternatives
1. The reservation is a placeholder: when the response arrives its entry is
   rewritten to the actual total, so one request contributes its real usage to
   the window exactly once.
2. The reservation stays and the actual usage is appended on top, so each
   request charges the window roughly twice.
3. The reservation is dropped on completion and the actual usage is added with
   a fresh timestamp.

### Choice
Interpretation 1. A reservation exists to hold space for an unknown number;
once the number is known it is the same request's cost, not an extra one.
Keeping the original timestamp is covered by T85.

### Risk: 35
An implementation that simply appends both entries paces at roughly half the
configured TPM; a fixture that counts requests admitted inside one window would
diverge.

## T85: The timestamp an actual-usage record carries

### Spec Text
> - after the response arrives, record actual `prompt_tokens + completion_tokens`
>   from the API response in the TPM window

### Alternatives
1. Keep the reservation's timestamp -- the moment the request was dispatched.
2. Stamp the record with the moment the response arrived, so a slow request's
   tokens linger in the window for longer.

### Choice
Interpretation 1. The window is a sliding budget over requests sent, and the
reservation already occupies a slot at dispatch time; rewriting its amount in
place is the smallest change consistent with "record ... in the TPM window".

### Risk: 20
Only requests slower than a meaningful fraction of 60 seconds separate the two
readings.

## T86: A request larger than the whole TPM budget

### Spec Text
> - when `tpm` is configured, also enforce a sliding 60-second token budget

### Alternatives
1. If the window is empty and the request still does not fit, send it anyway --
   waiting could never help.
2. Block forever (or fail the row) because the budget can never accommodate it.

### Choice
Interpretation 1. A budget that deadlocks on a single oversized request would
make `tpm` smaller than `max_tokens` unusable, and the spec treats TPM as
pacing rather than as validation.

### Risk: 15
Only a config whose `tpm` is below `max_tokens` reaches this branch.

## T87: Whether the limiter is per task or per run

### Spec Text
> For multi-task configs, `defaults.rate_limits` is merged into each task the
> same way earlier checkpoints merged `prompt`, `generation`, and `evaluation`.

### Alternatives
1. Each task gets its own limiter, since each task carries its own resolved
   `rate_limits`; two tasks with `max_concurrent: 10` may have 20 requests in
   flight between them.
2. One limiter for the whole run, built from the merged defaults.

### Choice
Interpretation 1. The settings are per-task after merging -- per-task overrides
would otherwise have no coherent meaning -- and Part 2 already gave each task
its own request budget.

### Risk: 15
A multi-task fixture that watches peak concurrency at the server sees the
difference; per-task budgets follow from per-task overrides.

## T88: Which budget the run enforces and reports

### Spec Text
> - track prompt cost, completion cost, and total cost across all tasks
> - when `budget` is configured and the running total reaches or exceeds it:
>   stop sending new requests immediately

### Alternatives
1. Costs are accumulated for the whole run and compared against one budget; as
   every task inherits `defaults.cost`, that budget is normally the same number
   everywhere, and when tasks disagree the smallest configured budget binds and
   is what `cost.budget` reports.
2. Each task tracks and enforces its own budget, and the summary reports the
   sum of the budgets.
3. Each task enforces its own budget, and the summary reports the first one.

### Choice
Interpretation 1. The running total is explicitly "across all tasks", and the
summary has a single `budget` field, so the budget is a property of the run;
taking the minimum keeps a per-task override that lowers the budget meaningful.

### Risk: 30
Configs that set different budgets per task are the only ones that diverge; an
author enforcing per-task budgets would let a cheap task keep running.

## T89: What happens to rows the budget stopped

### Spec Text
> - when `budget` is configured and the running total reaches or exceeds it:
>   stop sending new requests immediately, let in-flight requests finish, write
>   completed results, print the summary, and exit `0`
> - budget exhaustion is not an error; partial output is valid

### Alternatives
1. Only rows that finished are written, in input order; a row that was still
   mid-flight when the budget ran out (for instance a rejection row with one
   attempt left) is dropped rather than half-written, and the summary counts
   the written rows.
2. Every input row is written, with `null` output and a failed result for the
   ones that never ran.
3. Unstarted rows are written as `null` but partially-processed rows are kept
   as far as they got.

### Choice
Interpretation 1. "Write completed results" names the finished rows only, and
resume relies on the output file holding complete rows in input order, so a
dropped row is simply picked up again on the next run.

### Risk: 35
An author who writes placeholder rows for the remainder would report
`total` equal to the input count; the summary counts are where this shows.

## T90: How costs are rounded in the summary

### Spec Text
> ```json
> {
>   "cost": {
>     "total": 12.45,
>     "prompt": 4.50,
>     "completion": 7.95,
> ```

### Alternatives
1. Report the accumulated float, cleaned of binary-float noise by rounding to
   six decimals, so small runs still show a non-zero cost.
2. Round to two decimals, matching the example's dollars-and-cents shape.
3. Report the raw float with no rounding at all.

### Choice
Interpretation 1. The example's values are all exact to two decimals anyway, so
it does not pin the rule, and a run of a few calls at `0.01`/`0.03` per 1k
tokens costs fractions of a cent -- rounding those to `0.0` would make the
field useless and would not match the budget arithmetic the spec describes.

### Risk: 35
The author may well have written `round(total, 2)`; a fixture asserting
`cost.total == 0.0` for a short run would then disagree with this reading.

## T91: `--budget` with no cost rates configured

### Spec Text
> - `--budget <float>`
> - if no cost configuration is present, omit the `cost` field from the summary

### Alternatives
1. `--budget` is itself cost configuration: the summary reports a `cost` block,
   the rates default to `0.0`, and the budget can never be reached.
2. The flag is ignored unless the config also sets rates, and the summary keeps
   no `cost` field.

### Choice
Interpretation 1. A CLI flag overrides config the same way `--rpm` does, and a
run that was asked about a budget should report on it.

### Risk: 25
The distinguishing fixture -- `--budget` with no `cost:` block -- is unusual,
but an author keying the summary field off the config file alone would omit it.

## T92: The `budget` fields when no budget is configured

### Spec Text
> ```json
> "budget": 50.0,
> "budget_remaining": 37.55,
> "budget_exceeded": false
> ```

### Alternatives
1. Always emit all six keys when cost tracking is on; `budget` and
   `budget_remaining` are `null` without a configured budget, and
   `budget_exceeded` is `false`.
2. Omit `budget`, `budget_remaining` and `budget_exceeded` when no budget is
   set, leaving `total`, `prompt` and `completion`.

### Choice
Interpretation 1. The summary shape is given as one object, and a stable set of
keys is easier to consume; `null` says "no budget" without dropping the field.

### Risk: 30
An author who builds the block conditionally would omit the keys, so a fixture
checking `"budget" not in summary["cost"]` would fail here.

## T93: `passed` when a schema validates and nothing else is configured

### Spec Text
> ```json
> "result": {
>   "passed": true,
>   "schema_valid": true
> }
> ```
> - for `greedy` and `sample`, schema failure sets `result.passed` to `false`

### Alternatives
1. With `output_schema` configured and no `evaluation`, schema validity *is*
   the verdict: `passed` mirrors `schema_valid` instead of staying `null`.
2. `passed` stays `null` without an `evaluation` block, even though the spec
   says schema failure sets it to `false`.

### Choice
Interpretation 1. The spec says failure sets `passed` to `false`, which only
makes sense if success sets it to `true`, and the example row shows exactly
that pair.

### Risk: 15
The `false` half is stated outright; only the success half is inferred.

## T94: What evaluation sees when a schema is configured

### Spec Text
> - if both schema validation and evaluation are configured, run schema
>   validation first and skip evaluation when schema validation fails

### Alternatives
1. Evaluation still runs over the raw response text, exactly as it does
   without a schema; only its ordering changes.
2. Evaluation runs over the parsed JSON -- for instance over the `output_field`
   member of the parsed object.

### Choice
Interpretation 1. The evaluations are defined as operations on the response
text (extraction, substring, regex, a script's stdin), and the spec changes
only the order in which they run.

### Risk: 25
A fixture combining `output_schema` with `exact_match` on a JSON response is
the one that separates the readings.

## T95: The wording of `schema_error`

### Spec Text
> `result.schema_error` to a human-readable validation message
> ```json
> "schema_error": "Missing required field: explanation"
> ```

### Alternatives
1. Follow the example's wording for the required-field case and use the same
   voice for the rest: `Invalid JSON: ...`, `Expected type string at 'code',
   got integer`, `Value 5 is less than minimum 10`, and so on.
2. Emit a library-style message (`'explanation' is a required property`).

### Choice
Interpretation 1. The one message the spec shows is reproduced exactly; the
others follow its `Field: detail` shape.

### Risk: 35
Only the quoted message is pinned, so any fixture asserting on another
message's exact text is unlikely to match.

## T96: The scope of the JSON Schema subset

### Spec Text
> - support JSON Schema draft 7 rules for `type`, `required`, `properties`,
>   `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`, and
>   `pattern`

### Alternatives
1. Implement exactly those ten keywords with draft-7 semantics -- keywords only
   constrain values of the type they apply to, `integer` accepts a whole
   number, a JSON boolean is never an `integer` or a `number`, and any other
   keyword in the schema is ignored rather than rejected.
2. Treat an unsupported keyword as a config error.
3. Apply length and range checks across types (for instance `minLength` to a
   number's digits).

### Choice
Interpretation 1. Draft 7 defines each keyword as a no-op for values of the
wrong type, and the spec lists the supported keywords without saying anything
about rejecting others.

### Risk: 20
A schema mixing keyword and value types (`minLength` on a number) is the likely
divergence, and draft 7 answers it directly.

## T97: Schema results in the multi-solution shape

### Spec Text
> - for rejection sampling, schema failure is a failed attempt and may trigger
>   another try
> - on schema success, store the parsed JSON value in the per-row `output`
>   field instead of the raw response string

### Alternatives
1. A list-format row validates every attempt: a failing attempt is a failed
   attempt (so rejection retries and the `failed` count rises), and each
   emitted solution carries its parsed JSON under the task's `output_field`.
   The row's `result` gains no schema keys, because there is no single verdict
   for several solutions.
2. Add `schema_valid`/`schema_error` to the list-format `result`, reporting the
   last attempt.
3. Emit solutions with `null` content for attempts that failed validation.

### Choice
Interpretation 1. The row-level `schema_valid`/`schema_error` fields are
specified for "non-rejection rows", which are the single-solution shape; in the
list shape the per-attempt verdict already flows into `passed`/`failed`.

### Risk: 40
The spec never shows a list-format row with a schema, so an author who attaches
the schema keys to every row would produce a different `result` object.

## T98: Schema fields for a row that never got a response

### Spec Text
> - on schema failure for non-rejection rows, set `output` to `null`,
>   `result.schema_valid` to `false`, and `result.schema_error` to a
>   human-readable validation message

### Alternatives
1. A row whose request failed permanently reports `schema_valid: false` with no
   `schema_error`, since nothing was validated and nothing can be described.
2. Report `schema_valid: null` for such a row.
3. Report `schema_valid: false` with a message like "no response".

### Choice
Interpretation 1. `schema_valid` is a boolean field in the shown shape and no
output was produced, so `false` is accurate; inventing a validation message for
a response that never arrived would be misleading.

### Risk: 30
Only a fixture that fails the API and inspects the schema keys distinguishes
these.

## T99: Resume with an incomplete row in the middle of the file

### Spec Text
> - when a prior output row represents an incomplete multi-solution or rejection
>   result with fewer passing solutions than `num_solutions`, do not skip that
>   row; reprocess it from scratch

### Alternatives
1. The skip count is the number of *leading* complete rows: scan the existing
   output in order, stop at the first incomplete row, truncate the file there,
   and reprocess from that index. A row counts as complete when it holds at
   least `num_solutions` solutions -- which for the gated rejection scheme are
   exactly its passing ones -- and a Part 1 rejection row needs its one output
   to be non-null.
2. Keep every existing row and re-run only the incomplete ones, appending their
   new results at the end -- which breaks the input-order pairing.
3. Ignore the rule and always skip whatever the line count says.

### Choice
Interpretation 1. Resume is defined entirely by "the existing line count gives
the number of leading rows to skip", so the file has to stay a prefix of the
results; the only way to reprocess a row is to drop it and everything after it.

### Risk: 30
An author may only ever check the *last* line (the one an interruption would
have truncated), which agrees with this reading except when an earlier row is
incomplete.

## T100: Resume when the output already covers every input

### Spec Text
> - if `--resume` is set and the output file already exists, inspect the
>   existing output to determine how many input rows are already complete

### Alternatives
1. Skipping every row is a valid, successful run: no requests are made, the
   file is left alone, and the summary reports `total: 0` with
   `resumed_from` equal to the number of skipped rows.
2. Treat an already-complete output as an error.

### Choice
Interpretation 1. Resume is defined as a skip count, and "budget exhaustion is
not an error; partial output is valid" sets the tone for partial runs; a
finished run has nothing left to do.

### Risk: 10
Both readings agree except on whether the exit code is `0`, and nothing in the
spec makes a finished run an error.

## T101: `resumed_from` on runs that did not resume

### Spec Text
> - the summary covers only newly processed rows and includes `resumed_from`

### Alternatives
1. `resumed_from` appears only when `--resume` was passed (where it may still
   be `0` if the output did not exist), keeping every earlier summary shape
   byte-identical.
2. Always include `resumed_from`, defaulting to `0`.

### Choice
Interpretation 1. The field is introduced inside the resume rules, and "Existing
behavior from earlier parts is unchanged unless stated here" argues for leaving
non-resume summaries alone.

### Risk: 20
An author who always emits the key would break no earlier fixture either, so
this could go the other way.

## T102: Whether dry-run token estimates count retries

### Spec Text
> - estimate prompt tokens as `average prompt word count * 1.33`
> - estimate total tokens as estimated prompt tokens plus `max_tokens`
> - estimate time in minutes as `total_inputs * avg_attempts / rpm`

### Alternatives
1. The token and cost estimates are per input row -- `inputs * (prompt + max_tokens)`
   -- and `avg_attempts` only enters the time estimate, which is the only rule
   that mentions it.
2. Multiply the token estimate by `avg_attempts` too, so a rejection task's
   estimate reflects worst-case retries.

### Choice
Interpretation 1. The example's `est_completion_tokens` is exactly
`1000 * 512`, `inputs * max_tokens`, with no attempt multiplier, and the
`avg_attempts` factor is introduced only for the time estimate.

### Risk: 30
The example's scheme is not stated, so it may simply be a `greedy` task where
both readings agree; an author estimating worst-case spend would multiply.

## T103: `avg_attempts` for schemes the rule does not name

### Spec Text
> where `avg_attempts` is `1` for `greedy` and `sample` and `n` for rejection
> worst-case planning

### Alternatives
1. `greedy`, `sample` and `agentic` count `1`; `rejection` counts
   `generation.n`, the literal value the spec names. When RPM limiting is off
   there is no rate to divide by, so `est_time_minutes` is `0.0`.
2. Use `max_attempts` (`3 * num_solutions` by default) for rejection, which is
   the real worst case for a multi-solution row.
3. Use `max_iterations` for agentic loops.

### Choice
Interpretation 1. The rule names `n`, and Part 1's rejection scheme makes
exactly `n` attempts; agentic is not mentioned, and one loop per row is the
count its own rules give.

### Risk: 35
For a multi-solution rejection task `n` and `max_attempts` differ widely, and
an author writing "worst-case planning" may well have meant the attempt budget.

## T104: Rounding in the dry-run estimate

### Spec Text
> ```json
> "est_prompt_tokens": 45000,
> "est_cost": 20.31,
> "est_time_minutes": 9.3
> ```

### Alternatives
1. Token counts are integers (rounded), costs keep six decimals like the
   summary's cost block, and `est_time_minutes` is rounded to one decimal, as
   shown.
2. Round `est_cost` to two decimals, as the example prints it.

### Choice
Interpretation 1, for the same reason as T90: two-decimal dollars collapse to
`0.0` on the small fixtures a test suite actually runs, while the example's
values are exact either way.

### Risk: 30
Paired with T90 -- an author who rounds money to cents does it in both places.

## T105: The exact progress line

### Spec Text
> ```text
> [50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
> ```

### Alternatives
1. Reproduce the format literally: integer percent, `passed`/`failed` counts,
   observed rpm to one decimal, cost to two decimals, and an integer ETA in
   seconds derived from the rows still to do at the rate achieved so far. A
   final line is printed when the last row lands, so a finished run ends at
   `100%`.
2. Format the ETA as `m:ss` once it passes a minute.
3. Print only on the timer, never at completion.

### Choice
Interpretation 1. The example is the only specification of the format, so it is
copied field for field; "every 10% of total inputs" makes the last row a
reporting point in its own right.

### Risk: 40
Progress goes to stderr and is unlikely to be asserted character by character,
but ETA rounding and the final line are guesses.

## T106: Which run the progress fields describe

### Spec Text
> - include `passed` / `failed` counts only when evaluation is configured
> - include `$... spent` only when cost tracking is configured

### Alternatives
1. The progress line covers the whole run, so the fields appear when *any*
   selected task configures an evaluation (or a schema, which also produces a
   verdict) or cost rates.
2. Print one line per task, each with its own fields.

### Choice
Interpretation 1. The line's `[50/100]` counts inputs for the run, and the
summary aggregates tasks the same way.

### Risk: 20
Only a multi-task run where one task lacks an evaluation separates them.

## T107: What the new CLI flags override

### Spec Text
> - `--tpm <int>`
> - `--max-concurrent <int>`
> - `--budget <float>`

### Alternatives
1. Each flag applies to every selected task, overriding both `defaults` and any
   per-task value, exactly as `--rpm` and `--model` already do.
2. The flags only fill in values no task configured.

### Choice
Interpretation 1. Part 2 established that a CLI flag replaces the corresponding
config value for every task it runs.

### Risk: 10
The precedent is set by the existing flags.
