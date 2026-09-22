# Ambiguities

Numbered record of spec under-specification, the alternatives considered, the
interpretation implemented, and the risk that the spec author's own
implementation (and therefore the hidden tests) reads it differently.

---

## T1: `meta` shape for a rejection row that succeeds on its first attempt

### Spec Text
> `meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt

### Alternatives
1. Shape is decided by the *actual* number of attempts made: a rejection row
   that passes on attempt 1 emits a single object (not a list of one).
2. Shape is decided by the *scheme*: any `rejection` row emits a list, even a
   one-element list, so consumers never have to branch on type.

### Choice
Alternative 1. The prose keys the shape to "one-attempt rows", not to
"greedy and sample rows", and it contrasts with "rejection sampling with
multiple attempts" — which would be a strange qualifier if every rejection
row were a list. A rejection row that passes immediately is a one-attempt
row, so it gets a single object.

### Risk: 20
Author's likely alternative: always emit a list for `scheme: rejection`
regardless of attempt count.

---

## T2: `meta` (and `result`) for a row whose API calls all failed with 5xx

### Spec Text
> After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue.

### Alternatives
1. `meta` is `null` — there is no successful response, so there is no
   metadata to report.
2. `meta` is an object with `model` set and every measured field `null`.
3. `meta` is a list of the failed HTTP attempts, each with an `error` field.

### Choice
Alternative 1, generalised by the same rule used elsewhere: `meta` is built
from the *successful* responses for the row — zero of them gives `null`, one
gives an object, more than one gives a list. This keeps a rejection row that
fails on attempt 3 after two evaluated responses reporting the two metas it
actually has. The row gets `output: null`,
`result.extracted_answer: null`, `result.attempts` = the number of logical
attempts started (so `1` for greedy/sample), and `result.passed: false`
(see also T5).

### Risk: 45
Author's likely alternative: a `meta` object of nulls (alternative 2) so the
per-row shape is uniform for one-attempt rows.

---

## T3: how many HTTP calls a single request makes before it is abandoned

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 times. After the
> third failure, treat that row as failed

### Alternatives
1. Three HTTP calls in total: the original plus two retries; the third
   failure is the third call, exactly as the second sentence says.
2. Four HTTP calls in total: the original plus three retries, taking "retry
   it up to 3 times" literally; then "the third failure" loosely means the
   third retry's failure.

### Choice
Alternative 1 — a maximum of 3 HTTP calls per logical request. The second
sentence puts a hard number on the failure that ends the row ("the third
failure"), and that is only self-consistent with three total calls. Reading
sentence one as the common loose "retry up to 3 times" = "try up to 3 times"
requires less charity than assuming the author miscounted in sentence two.
This is directly observable through `total_api_calls`.

### Risk: 40
Author's likely alternative: 4 total calls (1 initial + 3 retries), making
`total_api_calls` 4 per permanently-failing row.

---

## T4: a rejection attempt whose HTTP calls are exhausted

### Spec Text
> `rejection`: ... make up to `n` attempts and keep the first passing
> response
>
> After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue.

### Alternatives
1. The whole row fails immediately: stop making attempts, emit `null`
   output, and move on.
2. The exhausted attempt is treated as a non-passing attempt and the loop
   continues to the next of the `n` attempts.

### Choice
Alternative 1. The retry text says to treat *that row* as failed, not that
attempt, and it is the only statement in the spec about what an exhausted
request does. `result.attempts` then reports the number of logical attempts
started, counting the one that died.

### Risk: 35
Author's likely alternative: continue to the next rejection attempt, so a
row can still pass after one attempt exhausted its retries.

---

## T5: `result.passed` for an API-failed row when no evaluation is configured

### Spec Text
> if `evaluation` is omitted for `greedy` or `sample`, `result.passed` must
> be `null`
>
> `failed`: rows where `result.passed` is `false` or `output` is `null`

### Alternatives
1. `passed: false` on any row that produced no output, evaluation or not —
   the row is a failure and the summary counts it as one.
2. `passed: null` when no evaluation is configured, honouring the "must be
   `null`" rule literally; the row is still counted as failed via the
   `output is null` clause.

### Choice
Alternative 1. The API-contract section says to "treat that row as failed",
and the summary's `failed` clause already anticipates rows whose `passed` is
`false` *or* whose `output` is `null` — the second clause exists for the
`null`-output case, so either choice counts correctly, but `false` reads as
the more direct statement of "this row failed". The "must be `null`" rule is
stated as a consequence of evaluation being omitted, i.e. about rows that
were actually evaluated.

### Risk: 30
Author's likely alternative: `passed: null` for a failed row when no
evaluation is configured, since the validation rule is phrased as a MUST.

---

## T6: `temperature` omitted from `generation`

### Spec Text
> `sample`: `temperature` must be `> 0`
>
> `rejection`: `temperature` must be `> 0`

### Alternatives
1. A missing `temperature` defaults to `0.0`, so `sample`/`rejection` with
   no temperature is an invalid configuration (exit 1).
2. A missing `temperature` defaults to the OpenAI default `1.0`, so
   `sample`/`rejection` are valid without one.

### Choice
Alternative 1. The greedy example in the spec omits `temperature` and
relies on it being forced to `0.0`, which shows `0.0` is the natural
baseline; the validation rule then fires for the sampling schemes, which is
the behaviour the "must be `> 0`" wording is there to produce.

### Risk: 25
Author's likely alternative: default `temperature` to `1.0` for
`sample`/`rejection` and accept the config.

---

## T7: defaults for config fields the spec never marks required

### Spec Text
> ```yaml
> task:
>   name: "gsm8k_solve"
>   api_url: "http://localhost:8000"
>   ...
> ```
> Invalid configuration exits with code `1` and a descriptive message on
> stderr.

### Alternatives
1. Only `api_url`, `model`, and `prompt.user` are structurally required;
   everything else defaults (`max_tokens` 512, `n` 1, `rpm` 60,
   `temperature` 0.0, `scheme` "greedy", `output_field` "output",
   `prompt.system` omitted → no system message, `name` unused).
2. Every key shown in the config shape is required and its absence is a
   configuration error.

### Choice
Alternative 1. The spec's own greedy example omits `temperature` and `n`
from `generation`, proving the shape block is illustrative rather than a
required-key list. Defaults are taken from the values shown in that block
(512 / 1). Being permissive here only risks accepting a config the author
would reject; being strict risks rejecting the spec's own example.

### Risk: 20
Author's likely alternative: requiring `output_field` (and possibly
`prompt.system`) explicitly, erroring when absent.

---

## T8: default `extract` method

### Spec Text
> `exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row

### Alternatives
1. `extract` defaults to `full` (the whole response text) when omitted.
2. `extract` is required whenever `type: exact_match` is used.
3. `extract` defaults to `last_number`, matching the spec's GSM8K framing.

### Choice
Alternative 1. `full` is the identity extraction and the only default that
cannot silently change the comparison value; the validation-rules list names
exactly which keys each evaluation type requires and `extract` is not among
them, so its absence must not be an error.

### Risk: 25
Author's likely alternative: also `full`, but a strict author could require
`extract` for `exact_match`.

---

## T9: how `exact_match` compares the extracted value

### Spec Text
> `exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row

### Alternatives
1. Whitespace-stripped string equality against `str(answer_field value)`.
2. Numeric-aware equality, so `"8.0"` matches `"8"` and `"1,000"` matches
   `"1000"`.
3. Raw, unstripped string equality.

### Choice
Alternative 1. "Exact match" argues against value-normalising heuristics,
and stripping is needed because `extract: full` and `last_line` routinely
carry trailing newlines/spaces that no author intends to be significant.
Non-string `answer_field` values are stringified (`8` → `"8"`).

### Risk: 30
Author's likely alternative: numeric normalisation for `last_number`
extraction so `8.0` and `8` compare equal.

---

## T10: what counts as "the last integer or decimal"

### Spec Text
> `last_number`: use the last integer or decimal in the response

### Alternatives
1. `-?\d+(?:\.\d+)?` — signs included, thousands separators not; `"#### -4"`
   extracts `"-4"`, `"1,000"` extracts `"000"`.
2. Unsigned `\d+(?:\.\d+)?`, so `"-4"` extracts `"4"`.
3. A comma-aware pattern that strips separators, so `"1,000"` → `"1000"`.

### Choice
Alternative 1. A leading minus is part of the number being read, and the
spec says "integer or decimal" with no mention of grouping separators, so
comma handling would be an invention. When the response contains no number
at all the extracted value is `null` and the comparison fails.

### Risk: 25
Author's likely alternative: an unsigned pattern, differing only on
negative answers.

---

## T11: `result.extracted_answer` for `contains` and `regex` evaluations

### Spec Text
> `result.extracted_answer` is the extracted comparison value, or `null`
> when there is no evaluation or no output

### Alternatives
1. The configured `extract` method (defaulting to `full`) is applied for
   every evaluation type, so `contains`/`regex` rows report the whole
   response text by default.
2. `extracted_answer` is `null` for `contains` and `regex`, since neither
   type is described in terms of extraction.
3. For `regex`, report the first capture group (or whole match) and `null`
   when the pattern does not match.

### Choice
Alternative 1. The field is defined as "the extracted comparison value" and
its `null` cases are enumerated as *no evaluation* and *no output* — a
`contains` row has both an evaluation and an output, so it should not be
`null`. Applying `extract` uniformly also keeps `extract` meaningful next to
any type, and with the `full` default the reported value is exactly the text
the comparison ran against.

### Risk: 45
Author's likely alternative: `extracted_answer: null` for `contains` and
`regex` rows.

---

## T12: when row-level input validation happens, and whether a missing
`answer_field` is fatal

### Spec Text
> If a placeholder references a missing field, exit with code `1` and print
> an error to stderr naming the row index and missing field.
>
> Every row must contain all fields referenced by the prompt templates. When
> the configured evaluation uses `answer_field`, each row must also contain
> that field.

### Alternatives
1. All rows are validated up front, before any HTTP request; the first
   offending row exits 1 and no output file is written. A missing
   `answer_field` is fatal in the same way as a missing template field.
2. Validation happens lazily per row while processing, so earlier rows have
   already been sent (and possibly written) before the exit.
3. Only template placeholders are fatal; a missing `answer_field` merely
   makes that row fail evaluation.

### Choice
Alternative 1. Exit code 1 is documented as "configuration or input error",
which is a pre-flight category, and spending API budget on a run that is
going to abort is plainly not intended. "Must also contain that field" is
the same normative language used for template fields, so it gets the same
treatment. The stderr message names both the row index and the field:
`error: row 0: missing field 'question'`.

### Risk: 35
Author's likely alternative: treating a missing `answer_field` as a failing
evaluation rather than a fatal input error.

---

## T13: `--temperature` combined with `scheme: greedy`

### Spec Text
> `greedy`: force `temperature` to `0.0`; `n` is ignored

### Alternatives
1. Silently force `0.0`, discarding any config or `--temperature` value.
2. Error out when an explicit non-zero temperature is combined with greedy.

### Choice
Alternative 1. "Force" describes a coercion, not a validation, and it sits
beside "`n` is ignored" — the other clause on the same line is explicitly
about quietly disregarding a value.

### Risk: 20
Author's likely alternative: same coercion; a strict author might reject the
combination.

---

## T14: failures that are not HTTP 5xx

### Spec Text
> If a request receives an HTTP `5xx`, retry it up to 3 times.

### Alternatives
1. Only 5xx is retried. Connection errors and timeouts are treated as 5xx
   (the request never produced a response, so it is retried); 4xx and
   unparseable/malformed success bodies are not retried and fail the row
   immediately.
2. Retry everything that is not a well-formed 2xx.
3. Retry nothing but 5xx, including letting connection errors crash the run.

### Choice
Alternative 1. Transport failures are indistinguishable from a 5xx to the
caller and retrying them is the obviously intended behaviour, while a 4xx is
a deterministic client error that no retry can fix. A run is never allowed
to crash: every non-retryable failure becomes a `null`-output row.

### Risk: 30
Author's likely alternative: retrying any non-200 response, which changes
`total_api_calls` on a 4xx fixture.

---

## T15: empty input file

### Spec Text
> `total`: input row count
>
> `elapsed_seconds`: wall-clock time from first request to last response

### Alternatives
1. Zero rows is a valid run: write an empty output file, print a summary of
   all zeros (`elapsed_seconds: 0.0`, `throughput_rpm: 0.0`), exit 0.
2. An empty input file is an input error, exit 1.

### Choice
Alternative 1. Nothing in the spec forbids zero rows, and "input row count"
has a well-defined value of `0`. There are no requests, so the elapsed
window is empty and both time-derived fields are reported as `0.0` rather
than dividing by zero.

### Risk: 15
Author's likely alternative: same; a strict author might reject an empty
input as an input error.

---

## T16: placeholder substitution mechanics

### Spec Text
> `prompt.system` and `prompt.user` use `{field}` placeholders resolved from
> each input row.

### Alternatives
1. A regex substitution of `{name}` tokens, leaving any other brace text
   untouched and stringifying values (`json.dumps` for dict/list values).
2. Python `str.format(**row)`, which additionally consumes `{{`/`}}` escapes
   and supports `{a[b]}` / `{a.b}` / `{a!r:>10}` syntax, and raises on
   unbalanced braces.

### Choice
Alternative 1. The spec describes only a flat `{field}` lookup against the
row, and a prompt that legitimately contains JSON braces (very common for
this kind of tool) must not blow up or be silently mangled. Behaviour is
identical to `str.format` for every input the spec describes.

### Risk: 15
Author's likely alternative: plain `str.format`, differing only on prompts
containing literal braces.

---

## T17: whether a retry bumps `result.attempts` for rejection rows

### Spec Text
> Retry requests count toward `total_api_calls`, but for `greedy` and
> `sample` rows they do not increase the logical `result.attempts` count.

### Alternatives
1. Retries never increase `result.attempts` in any scheme; a retried call is
   part of the same logical attempt. The greedy/sample clause is an
   illustration of the general rule, made explicit because those rows must
   always report `1`.
2. For rejection, a retry does consume one of the `n` logical attempts,
   since the spec restricts its carve-out to greedy and sample.

### Choice
Alternative 1. `result.attempts` is defined as "the number of logical
generation attempts" and bounded by `1..n`; letting retries consume that
budget would both contradict "logical" and make a row's attempt count depend
on server flakiness rather than on evaluation outcomes.

### Risk: 25
Author's likely alternative: same; the risk is that the carve-out's wording
was deliberate and rejection retries do increment.

---

# Part 2

## T18: how deeply `defaults` and a task are merged

### Spec Text
> - `defaults` provides shared values; each task overrides `defaults`
> - nested sections such as `prompt`, `generation`, and `evaluation` are merged
>   per task using the Part 1 structure

### Alternatives
1. A one-level-deep merge: top-level keys are replaced by the task's value,
   except that a mapping value (`prompt`, `generation`, `evaluation`, or any
   other mapping) is merged key by key with the default mapping.
2. A fully recursive deep merge at every nesting depth (matters only for
   `evaluation.judge_prompt`, the one third-level mapping in the spec).
3. Whole-section replacement: a task that defines `generation` drops every
   default `generation` key.

### Choice
Alternative 1. "Merged" rules out alternative 3, and the Part 1 structure is
exactly two levels deep, so one level of mapping merge covers every section
the spec names. `judge_prompt` is treated as a value of the `evaluation`
mapping, so a task that sets `judge_prompt` supplies both of its keys — which
is how the spec's own example writes it.

### Risk: 10
Author's likely alternative: a recursive deep merge, which differs only when
`defaults` and a task both set `evaluation.judge_prompt`.

---

## T19: a config containing both `task` and `tasks`

### Spec Text
> if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format; the task name is `task.name`

### Alternatives
1. `task` wins unconditionally: the presence of a top-level `task` key selects
   the Part 1 format and `tasks` is ignored.
2. It is a configuration error to supply both.
3. `tasks` wins when it is present.

### Choice
Alternative 1. The rule is written as a test on the presence of `task` ("if
the config still uses a top-level `task` key"), with no exception for a config
that also has `tasks`, and the word "still" frames it as a compatibility
branch taken before anything else is considered.

### Risk: 10
Author's likely alternative: same; an author who validates strictly might
reject the combination.

---

## T20: Part 1 CLI overrides in a multi-task run

### Spec Text
> New flags:
> - `--task <name>` ...
> - `--eval-model <string>` ...
>
> Existing behavior from Part 1 is unchanged unless stated here.

### Alternatives
1. `--model`, `--api-url`, `--rpm`, `--scheme`, `--temperature`, `--n` and
   `--max-tokens` still apply, and apply to every selected task.
2. They apply only to single-task configs and are rejected (or ignored) for
   multi-task configs.

### Choice
Alternative 1. Part 1 defines those flags as overrides of the config values,
and Part 2 removes nothing; a global flag with several tasks in play most
naturally overrides the value each task would otherwise have resolved,
exactly as `--eval-model` is defined to do "for all selected `llm_judge`
tasks".

### Risk: 20
Author's likely alternative: same; the observable difference would only be an
author who ignores these flags outside single-task configs.

---

## T21: whether unselected tasks are validated

### Spec Text
> when `--task` is present, require input only for selected tasks and ignore
> unselected tasks for validation and execution

### Alternatives
1. "Validation" covers the whole task: an unselected task is never built or
   checked, so a malformed unselected task cannot fail the run.
2. "Validation" covers only input-file validation; the config block of every
   task is still validated, so a malformed unselected task exits 1.

### Choice
Alternative 1. The sentence separates "require input only for selected tasks"
from "ignore unselected tasks for validation and execution"; if the second
clause only repeated the first it would say nothing. Skipping unselected
tasks entirely also matches the practical point of `--task`: re-running one
task from a config whose other tasks may not be ready.

### Risk: 25
Author's likely alternative: validate every task in the config regardless of
selection, so a broken unselected task exits 1.

---

## T22: `--task` against a single-task config

### Spec Text
> - `--task <name>`: repeatable; run only the selected task or tasks
> - if the config still uses a top-level `task` key ... the task name is
>   `task.name`

### Alternatives
1. `--task` works for single-task configs: it selects when the name equals
   `task.name`, and exits 1 for any other name (including when `task.name` is
   absent).
2. `--task` is rejected for single-task configs.
3. `--task` is ignored for single-task configs.

### Choice
Alternative 1. The spec bothers to define the single-task name as `task.name`,
which only matters if names of Part 1 configs are addressable; treating
selection uniformly then needs no special case.

### Risk: 30
Author's likely alternative: `--task` is simply ignored for single-task
configs, so a mismatched name still runs the task instead of exiting 1.

---

## T23: does a single-task config's summary carry a `tasks` object?

### Spec Text
> The stdout summary now includes a `tasks` object keyed by executed task
> name

### Alternatives
1. Always: single-task runs report one entry, keyed by `task.name` (falling
   back to `"task"` when the Part 1 config omits `name`).
2. Only multi-task configs get a `tasks` object; single-task summaries keep
   their exact Part 1 shape.

### Choice
Alternative 1. The sentence is unconditional and sits beside the rule that
names a single-task config's task, and the natural implementation normalises
both config formats into the same list of tasks before summarising. Part 1's
own keys are all still present, so nothing documented is lost.

### Risk: 35
Author's likely alternative: omit `tasks` for single-task configs, keeping the
Part 1 summary byte-identical.

---

## T24: a selected task whose input file has no rows

### Spec Text
> include only tasks that actually ran

### Alternatives
1. A selected task with an empty input "ran": it gets a `tasks` entry of
   zeros and an empty output file.
2. A task with zero rows made no requests, so it is omitted from `tasks` and
   writes no file.

### Choice
Alternative 1. "Actually ran" is there to exclude tasks removed by `--task`,
not to filter on request count; the task was selected, its input was read and
its (empty) output file was written, so reporting zeros is the consistent
result. It also matches Part 1's treatment of an empty input as a valid run
(see T15).

### Risk: 15
Author's likely alternative: same; an author keying `tasks` off requests made
would drop the entry.

---

## T25: what counts as a `letter`

### Spec Text
> `letter`: extract the first uppercase answer choice `A` through `D`; accept
> forms such as `A`, `(A)`, `A)`, or `Answer: A`

### Alternatives
1. The first standalone uppercase `A`-`D`, i.e. one not adjacent to another
   letter: `(?<![A-Za-z])([A-D])(?![A-Za-z])`. `"Answer: C"` gives `C`
   because the `A` of "Answer" is followed by a letter.
2. The first `[A-D]` anywhere in the text, so `"Answer: C"` gives `A`.
3. Word-boundary matching `\b[A-D]\b`, which behaves identically to
   alternative 1 on every example in the spec.
4. Case-insensitive matching, so `"the answer is b"` gives `B`.

### Choice
Alternative 1. The spec's own accepted form `Answer: A` proves that a
standalone letter must win over the capital inside a word — otherwise the
extraction of `"Answer: C"` would be `"A"`, which no author intends. The word
"uppercase" rules out alternative 4, so a lowercase reply extracts nothing.

### Risk: 20
Author's likely alternative: `\b[A-D]\b` (same answers on the documented
forms) or a case-insensitive variant that also accepts lowercase replies.

---

## T26: `first_number`'s sign, and the JSON type of `judge_score`

### Spec Text
> `first_number`: extract the first integer or decimal in the response
>
> if the judge returns `"8"`, then `judge_score` is `8`

### Alternatives
1. `-?\d+(?:\.\d+)?`, matching Part 1's `last_number` (see T10); the score is
   emitted as a JSON integer when the matched text has no decimal point and
   as a float otherwise (`"8"` -> `8`, `"8.5"` -> `8.5`).
2. An unsigned pattern, so `"-4"` extracts `"4"`.
3. `judge_score` is always a float (`8.0`), or always the raw string `"8"`.

### Choice
Alternative 1. The two extract methods should read numbers the same way, and
the spec's example shows `judge_score` as the bare integer `8`, not `8.0` and
not `"8"`, so an integral score is emitted as an int.

### Risk: 20
Author's likely alternative: a float `judge_score` (`8.0`), which compares
equal to `8` in Python but not in a strict JSON fixture.

---

## T27: a judge reply with no number in it

### Spec Text
> score `>= threshold` passes
>
> `result` includes `judge_score`

### Alternatives
1. No number extracted means no score: `judge_score` is `null`, the
   comparison cannot succeed, and the row fails.
2. Treat an unparseable judge reply as a score of `0`.
3. Treat it as a failed evaluation call and abort the row with `output: null`.

### Choice
Alternative 1. `judge_score` is the extracted score, and there is none; the
row still has a generated response, so its `output` is kept and only the
evaluation fails. A fabricated `0` would be indistinguishable from a real
score of `0`.

### Risk: 20
Author's likely alternative: same, with `judge_score: 0` the main competing
reading.

---

## T28: `result.extracted_answer` for `script` rows

### Spec Text
> `result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output
>
> exit code equal to `success_exit_code` means pass

### Alternatives
1. `null`: a script evaluation extracts nothing from the response, it runs a
   command.
2. The whole response text, by applying the default `extract` uniformly as
   Part 1 does for `contains`/`regex` (T11).
3. The command's exit code, or its stdout.

### Choice
Alternative 1. A `script` evaluation has no "comparison value" at all — the
verdict comes from an exit code — and the spec explicitly forbids reporting
the command's output. Alternative 3 is ruled out by that same rule.

### Risk: 25
Author's likely alternative: the full response text, if their implementation
runs the shared extract step before dispatching on evaluation type.

---

## T29: `judge_score` on rows that are not judged

### Spec Text
> `result` includes `judge_score`

### Alternatives
1. The key exists only for `llm_judge` tasks; other tasks keep the Part 1
   `result` shape.
2. Every row carries `judge_score`, `null` when there was no judge.

### Choice
Alternative 1. The sentence sits inside the `llm_judge` rules, and Part 1's
`result` shape is otherwise unchanged. The same reasoning applies to
`meta.judge_meta`, which appears only on judged rows (and is `null` there when
the judge call itself never answered).

### Risk: 25
Author's likely alternative: always emit `judge_score: null` so every row has
the same keys.

---

## T30: where `judge_meta` goes when a row has several attempts

### Spec Text
> `meta` includes a `judge_meta` object with the judge request's token usage,
> latency, model, and finish reason

### Alternatives
1. `judge_meta` is a key of the per-attempt metadata object, so a rejection
   row whose `meta` is a list carries one `judge_meta` inside each attempt —
   every attempt was judged separately.
2. Only the final attempt's judge call is reported, as a single `judge_meta`.
3. `meta` becomes an object `{"attempts": [...], "judge_meta": ...}`.

### Choice
Alternative 1. Rejection sampling judges every candidate, so there is one
judge call per attempt and the metadata belongs with the attempt that produced
it; "`meta` includes a `judge_meta` object" then holds for each metadata
object. Alternative 3 would restructure `meta`, which Part 2 does not mention.

### Risk: 30
Author's likely alternative: a single `judge_meta` for the last (kept) judge
call, with earlier attempts' judge metadata dropped.

---

## T31: when `command_template` and `judge_prompt` placeholders are checked

### Spec Text
> `command_template` may reference row fields and `__response__`
>
> `judge_prompt` uses the same template rules as normal prompts
>
> If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field. (Part 1)

### Alternatives
1. Row fields referenced by `command_template` and `judge_prompt` are
   validated up front, with the prompt templates, so a missing field exits 1
   before any request is sent.
2. They are only rendered after a response exists, so a missing field fails
   that row (or exits 1 mid-run, after part of the budget is spent).

### Choice
Alternative 1. "The same template rules as normal prompts" pulls the judge
prompt under Part 1's missing-field rule, and the command template is
described in the same terms; Part 1 treats that rule as a pre-flight input
error (T12), and a row that can never be evaluated should not consume API
calls first.

### Risk: 30
Author's likely alternative: render lazily, so the run proceeds and only the
affected row fails (or the process exits 1 after some rows were written).

---

## T32: how `__response__` is spliced into a shell command

### Spec Text
> ```json
> {"problem": "write good code", "test_code": "echo '{__response__}' | grep -q 'good code'"}
> ```
> then the rendered shell command uses the generated response text in place of
> `__response__`

### Alternatives
1. Raw textual substitution: the response text is inserted verbatim, and any
   quoting is whatever the template author wrote.
2. Shell-escape the response before substituting (e.g. `shlex.quote`).

### Choice
Alternative 1. The example wraps the placeholder in single quotes itself,
which is only necessary — and only correct — if the substitution is raw;
escaping would insert a second layer of quotes and break that example.

### Risk: 10
Author's likely alternative: same; escaping would contradict the spec's own
example.

---

## T33: a judge call that never succeeds

### Spec Text
> the judge request is a separate API call through the same server
>
> After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue. (Part 1)

### Alternatives
1. The generation succeeded, so the row keeps its `output`; only the
   evaluation is lost: `judge_score: null`, `judge_meta: null`,
   `passed: false`. The failed judge attempts still count as API calls.
2. The row is failed wholesale, with `output` set back to `null`.

### Choice
Alternative 1. Part 1's rule is about the request that generates a row's
output; discarding a perfectly good generation because the judge was
unavailable would lose work the spec never says to discard. The row is still
counted as failed in the summary either way.

### Risk: 20
Author's likely alternative: `output: null` for the whole row, applying the
Part 1 failure rule to any exhausted request.

---

## T34: generation settings for the judge request

### Spec Text
> the judge request is a separate API call through the same server
>
> if `evaluation.model` is omitted, use the task's model

### Alternatives
1. The judge call reuses the task's resolved generation settings
   (`temperature`, `max_tokens`), changing only the model.
2. The judge call is always deterministic (`temperature: 0.0`).
3. The judge call sends no sampling parameters at all.

### Choice
Alternative 1. The only judge-specific knobs the spec defines are the prompt
and the model; keeping everything else identical is the smallest reading of
"a separate API call", and the payload shape stays the one Part 1 defines.

### Risk: 25
Author's likely alternative: force `temperature: 0.0` for judge calls, which
differs on a `rejection` task's judge payload.

---

## T35: `--eval-model` versus `evaluation.model`

### Spec Text
> `--eval-model <string>`: override the judge model for all selected
> `llm_judge` tasks

### Alternatives
1. The flag wins over both `evaluation.model` and the task model.
2. The flag only supplies a default for tasks that omit `evaluation.model`.

### Choice
Alternative 1. "Override" is the same word Part 1 uses for CLI flags that beat
config values, and a flag that lost to the config could not do what it says
for "all selected `llm_judge` tasks".

### Risk: 10
Author's likely alternative: same.

---

## T36: how tasks are scheduled against each other

### Spec Text
> requests from different tasks may run concurrently and may be interleaved
>
> judge calls ... may be interleaved with other work

### Alternatives
1. Every selected task runs concurrently in one event loop, each task keeping
   its own rpm-derived concurrency limit; `elapsed_seconds` spans the whole
   run and `throughput_rpm` is total calls over that span.
2. Tasks run one after another; only rows within a task overlap.

### Choice
Alternative 1. "May run concurrently" is permission, not obligation, but the
summary reports a single elapsed window and throughput for the run, which only
makes sense as an overall figure; running tasks together is also the only way
to keep the server busy when one task is small. Per-task rpm is kept as the
per-task limit because Part 1 ties concurrency to a task's `rpm`.

### Risk: 15
Author's likely alternative: sequential tasks, which changes only
timing-derived numbers (`elapsed_seconds`, `throughput_rpm`), not row output.

---

## T37: a missing `--output` directory

### Spec Text
> for multi-task configs, `--output` must be a directory
>
> write `<output_dir>/<task_name>.jsonl`

### Alternatives
1. Create the directory (and parents) when it does not exist; exit 1 only
   when the path exists and is not a directory.
2. Require the directory to exist already and exit 1 otherwise.

### Choice
Alternative 1. Part 1 creates the output file when absent, so creating the
output directory is the same courtesy one level up; "must be a directory" is
about the kind of path, and the only way to violate it is to point at an
existing non-directory.

### Risk: 15
Author's likely alternative: same; a strict author would exit 1 for a missing
directory.

---

## T38: `--input-dir` with a single-task config

### Spec Text
> Input handling for multi-task configs: ... directory mode ...
>
> for single-task configs, `--input <path>` without `=` still behaves as in
> Part 1

### Alternatives
1. `--input-dir` also works for a single-task config, looking for
   `<task.name>.jsonl`.
2. `--input-dir` is rejected for single-task configs.

### Choice
Alternative 1. The input-handling rules are written for multi-task configs but
nothing forbids the directory mode elsewhere, and a single-task config has a
task name to look up. Accepting it can only add behaviour to a case the spec
leaves silent.

### Risk: 20
Author's likely alternative: exit 1 (or ignore `--input-dir`) for single-task
configs.

---

## T39: `--input name=path` with a single-task config

### Spec Text
> for single-task configs, `--input <path>` without `=` still behaves as in
> Part 1

### Alternatives
1. A value containing `=` is read as a mapping when the part before `=` is the
   config's task name, and as a literal path otherwise (paths may contain
   `=`).
2. Any `=` makes it a mapping, so `data=1.jsonl` is an error unless the task
   is called `data`.
3. `=` is never special for single-task configs; the whole value is a path.

### Choice
Alternative 1. The qualifier "without `=`" implies the author expects the
mapping form to be recognised for single-task configs too, while a path that
happens to contain `=` must keep working, since Part 1 placed no restriction
on it.

### Risk: 20
Author's likely alternative: alternative 3 — single-task configs never parse
the mapping form, so `gsm8k=math.jsonl` is treated as a (missing) file name
and exits 1.

---

## T40: the same task named twice by `--input`

### Spec Text
> `--input <task=path>`

### Alternatives
1. The last mapping for a task wins.
2. A duplicate mapping is a configuration error.

### Choice
Alternative 1. Repeated flags overriding earlier ones is the ordinary CLI
convention, and the spec calls out repeatability only for `--task`, so nothing
suggests duplicates deserve an error.

### Risk: 10
Author's likely alternative: same; an untested corner either way.

---

## T41: defaults and requirements for the new evaluation keys

### Spec Text
> ```yaml
> evaluation:
>   type: "script"
>   command_template: "python3 -c \"{test_code}\""
>   success_exit_code: 0
> ```
> ```yaml
> evaluation:
>   type: "llm_judge"
>   judge_prompt: ...
>   threshold: 7
>   extract: "first_number"
>   model: "gpt-4"
> ```

### Alternatives
1. `command_template` is required for `script` and `success_exit_code`
   defaults to `0`; `judge_prompt` (with a `user`) and `threshold` are
   required for `llm_judge`, while `model` and `extract` are optional.
2. Every key shown is required, so omitting `success_exit_code` exits 1.
3. `threshold` defaults to something (e.g. `1`) when omitted.

### Choice
Alternative 1. The spec explicitly makes `evaluation.model` optional, which
shows the block is not a required-key list; `0` is the only sensible default
for a success exit code and is the value shown. A missing `threshold`, by
contrast, has no defensible default — every score would pass or fail
arbitrarily — so it stays required.

### Risk: 15
Author's likely alternative: also defaulting `threshold`, or requiring
`success_exit_code` explicitly.

---

## T42: the default `extract` for `llm_judge`

### Spec Text
> - `extract`: one of `last_number`, `last_line`, `full` (Part 1)
>
> ```yaml
> evaluation:
>   type: "llm_judge"
>   ...
>   extract: "first_number"
> ```

### Alternatives
1. `extract` defaults to `first_number` for `llm_judge` (and stays `full` for
   every other type, per T8).
2. `extract` defaults to `full` for every type, so a judge reply of
   `"Score: 8"` yields no score unless `extract` is set.
3. `extract` is required for `llm_judge`.

### Choice
Alternative 1. A judge score has to be parsed as a number, and `full` can only
produce one when the judge answers with a bare digit string; defaulting to the
method the spec pairs with `llm_judge` in both of its examples keeps an
omitted `extract` useful instead of nearly always broken.

### Risk: 25
Author's likely alternative: keep `full` as the universal default and let the
number parse fail, or require `extract` for `llm_judge`.
