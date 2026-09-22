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
