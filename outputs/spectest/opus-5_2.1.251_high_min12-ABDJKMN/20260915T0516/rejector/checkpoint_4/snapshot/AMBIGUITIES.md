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

### Part 3 annotation
Still open, but now narrower. Part 3 makes `meta` unconditionally a list in
the new list format ("`meta` is a list with one entry per attempt"), and keeps
"the Part 1 output format" only for rows with `num_solutions == 1` and no ICL.
So this entry now decides the shape of legacy rows alone. The new format's
unconditional list is mild evidence for the author's alternative, but it is
also exactly what the Part 3 rules say changes about the output, so it does
not settle Part 1's wording.

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

### Part 3 annotation
Unresolved, and now scoped to legacy rows; see T51 for the same question in
the Part 3 list format, which is answered the same way (no metadata entry for
an attempt that never returned a response).

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

### Part 4 annotation: resolved in favour of alternative 3
Checkpoint 4's agentic output example pairs
`"answer": "The total revenue for Q1 and Q2 is $2,730,000."` with
`"extracted_answer": "2730000"` and `"passed": true`. Under alternative 1
that text extracts `"000"` and the row fails, so the author's `last_number`
must read thousands separators as part of the number. The implementation now
matches `-?\d+(?:,\d{3})*(?:\.\d+)?` and strips the separators from the
extracted value, for `first_number` as well; the sign stays included, which
this example does not contradict. Residual risk (~15) is that separators are
stripped from the whole response before matching rather than only inside a
grouped number, which differs on text like `"8, 9"` (`"9"` here, `"89"`
there).

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

### Part 3 annotation
Resolved in favour of alternative 1. Part 3 defines `result.attempts` as "the
total number of generation attempts for the row" -- generations, not HTTP
calls -- with no greedy/sample carve-out, and gives `rejection` its own
separate budget (`max_attempts`) counted in the same units. Risk lowered to 10
for the Part 3 formats; the Part 1 legacy path keeps the same behavior.

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
## T43: the default `icl.strategy`

### Spec Text
> - `icl.strategy` is one of `fixed`, `random`, or `round_robin`

### Alternatives
1. `strategy` is optional and defaults to `fixed` — the deterministic choice,
   and the only one that behaves identically for a single setup.
2. `strategy` is required whenever `icl` is present, so omitting it exits 1.
3. It defaults to `round_robin`, on the grounds that declaring several setups
   implies wanting to use them all.

### Choice
Alternative 1. Every other optional ICL key in this part is given a default in
prose (`k` "defaults to all examples"), and the rules list only says which
values are legal, not that a value must be supplied. `fixed` is the default
that makes a one-setup config behave the same under any reading, and it keeps
runs reproducible unless the config opts into randomness.

### Risk: 25
Author's likely alternative: `round_robin`, so that a multi-setup config with
no `strategy` spreads attempts across setups.

---
## T44: which setup `greedy` uses with ICL when `num_solutions == 1`

### Spec Text
> - for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
>   strategy and instead walks setups in declared order, at most once per setup

### Alternatives
1. The override is scoped exactly as written: with `num_solutions == 1`,
   greedy selects its single setup with the configured strategy, so `random`
   really does pick a random setup for the one attempt.
2. Greedy always walks the declared order, so a single-solution greedy run
   always uses the first setup regardless of strategy.

### Choice
Alternative 1. The clause names `num_solutions > 1` explicitly, and the reason
for the override — "because the same setup is deterministic" you cannot
manufacture extra outputs — simply does not arise for one solution. The two
readings differ only for `strategy: random`; `fixed` and `round_robin` both
select the first setup on attempt 1 either way.

### Risk: 30
Author's likely alternative: greedy always walks the declared order, making a
single-solution greedy ICL run always use the first setup.

---
## T45: whether `round_robin` cycles per row or across the whole run

### Spec Text
> - `round_robin`: cycle through setups in order across attempts
>
> Round-robin order with setups `[A, B, C]`: attempt 1 uses `A` ... attempt 4
> uses `A`

### Alternatives
1. The cycle restarts for every input row, so each row's attempt 1 uses the
   first setup.
2. One global counter runs across the whole task, so row 2's first attempt
   continues where row 1 stopped.

### Choice
Alternative 1. "Attempt 1 ... attempt 5" is the vocabulary of a single row —
`result.attempts` is a per-row count — so the example describes one row's
sequence. A global counter would also be non-deterministic here, since rows
are processed concurrently and would race for positions in the cycle; a
per-row cycle is the only reading that produces a reproducible output file.

### Risk: 15
Author's likely alternative: a single counter shared by every row of the task
(deterministic only if rows are processed strictly in order).

---
## T46: whether evaluation gates inclusion for `greedy` with ICL

### Spec Text
> - `greedy` with ICL: generate at temperature `0` once per selected setup and
>   stop when `num_solutions` solutions are collected or all setups are
>   exhausted
> - `sample` with ICL: ... evaluation does not gate whether a solution is
>   included

### Alternatives
1. Greedy behaves like `sample`: every attempt that returns a response is
   emitted, and evaluation is only recorded (`evaluation_passed`), never used
   to drop an output.
2. Greedy behaves like `rejection`: only attempts that pass evaluation are
   "collected" as solutions, so a failing setup contributes nothing to
   `output`.

### Choice
Alternative 1. The spec attaches gating to exactly one scheme — rejection,
described as collecting "`num_solutions` passing solutions" — and spells out
non-gating for sample. Greedy's own bullet says "stop when `num_solutions`
solutions are collected or all setups are exhausted", and since each setup may
be used at most once, the sentence needs no notion of rejection at all. The
"Greedy cap" example ("if there are two setups and `num_solutions: 5`, produce
at most two solutions") also reads as a structural cap, not an evaluated one.

### Risk: 30
Author's likely alternative: greedy keeps only evaluation-passing responses,
so a two-setup run where one setup fails emits a single output.

---
## T47: `greedy` without ICL when `num_solutions > 1`

### Spec Text
> Scheme behavior when `num_solutions > 1`:
> - `greedy` with ICL: ...
> - `sample` with ICL: ...
> - `sample` without ICL: ...
> - `rejection` with ICL: ...
> - `rejection` without ICL: ...
>
> - do not retry the same greedy setup to manufacture additional outputs

### Alternatives
1. The combination is simply capped at one: greedy without ICL has exactly one
   prompt, that prompt is deterministic, so the row makes one attempt and
   emits one solution (in the list format, because `num_solutions > 1`).
2. Make `num_solutions` identical requests and emit `num_solutions` identical
   solutions.
3. Reject the combination at config time with exit 1.

### Choice
Alternative 1. The scheme list deliberately omits "greedy without ICL", and
the only guidance available — "do not retry the same greedy setup to
manufacture additional outputs" — says exactly what to do when a deterministic
prompt has already been used: stop. Reading the no-ICL case as a single setup
("no setup") makes the greedy bullet apply unchanged, with a cap of one.

### Risk: 35
Author's likely alternative: `num_solutions` identical sampled-at-zero
requests, producing `num_solutions` duplicate outputs and that many API calls.

---
## T48: what `result.failed` counts when outputs are not gated by evaluation

### Spec Text
> - `result.passed` is the count of passing solutions
> - `result.failed` is the count of failed attempts
> - `result.attempts` is the total number of generation attempts for the row

### Alternatives
1. `failed` is `attempts - passed`: an attempt is "failed" when it did not
   produce a passing solution, whether it failed evaluation, or never returned
   a response at all.
2. `failed` counts only attempts that produced no usable output at all (HTTP
   exhaustion), so for `sample` — where evaluation does not gate — `passed +
   failed` need not equal `attempts`.

### Choice
Alternative 1. Both worked examples satisfy `passed + failed == attempts`
(`2 + 5 = 7` in the output example, `2 + 8 = 10` in the rejection example),
and the no-evaluation rule is written the same way ("`result.passed` is the
number of emitted outputs, `result.failed` is the number of attempts that
produced no output") — again a partition of the attempts. So `failed` is
always the complement of `passed` within `attempts`, which means a `sample`
row can emit five outputs while reporting `passed: 3, failed: 2`.

### Risk: 35
Author's likely alternative: for non-gated schemes, `failed` counts only
attempts with no output, so a five-solution sample row reports
`passed: 3, failed: 0`.

---
## T49: `output` for a row that collected no solutions

### Spec Text
> - `output` becomes a list of objects, each containing the task's
>   `output_field` plus `icl_setup`
>
> Rejection partial result: ... write only those two passing outputs

### Alternatives
1. An empty list `[]` — the field's type is now "list", so zero solutions is
   the empty list.
2. `null`, preserving the Part 1 convention that a row with nothing to show
   has `output: null`.

### Choice
Alternative 1. "`output` becomes a list of objects" is unconditional for the
list format, and a consumer that iterates `row["output"]` should not have to
branch on `None`. The Part 1 `null` convention is explicitly tied to the Part 1
format, which this row is not using.

### Risk: 30
Author's likely alternative: `null`, carried over from the Part 1 exhaustion
rule.

---
## T50: which keys `result` carries in the list format

### Spec Text
> ```json
> "result": {
>   "passed": 2,
>   "failed": 5,
>   "attempts": 7
> }
> ```

### Alternatives
1. Exactly these three keys: `extracted_answer` (and the Part 2 `judge_score`)
   disappear, because they describe a single kept response and there is no
   longer a single kept response.
2. Keep `extracted_answer`/`judge_score` alongside them, taken from the last
   (or first) collected solution.
3. Move `extracted_answer` into each `output` item.

### Choice
Alternative 1. The spec prints the whole `result` object for the new format
and lists only three keys, then documents exactly those three. It likewise
prints a whole `output` item and says it contains "the task's `output_field`
plus `icl_setup`" — two keys — which rules out alternative 3.

### Risk: 25
Author's likely alternative: `extracted_answer` retained for compatibility
with the Part 1 result block.

---
## T51: a generation attempt whose HTTP calls are all exhausted

### Spec Text
> - `meta` is a list with one entry per attempt
> - each metadata entry includes `icl_setup` and `evaluation_passed`

### Alternatives
1. `meta` gets an entry only for attempts that actually returned a response,
   so a 5xx-exhausted attempt still increments `result.attempts` and
   `result.failed` but adds no metadata object.
2. Every attempt gets an entry, with `model`/`icl_setup` filled in and the
   measured fields (`prompt_tokens`, `latency_ms`, `finish_reason`, ...) null.

### Choice
Alternative 1, consistent with T2 in Part 1: metadata is built from responses,
and there is no response to describe. "One entry per attempt" is the shape
statement for the normal case — it is what distinguishes the list format from
Part 1's single object — not a promise to invent metadata for a request that
never completed. `result.attempts` remains the authoritative attempt count.

### Risk: 40
Author's likely alternative: a placeholder entry per attempt with null
measurements, keeping `len(meta) == result.attempts` an invariant.

---
## T52: `passed`/`failed` in the per-task summary for list-format tasks

### Spec Text
> ```json
> "gsm8k": {"total": 100, "total_solutions": 450,
>           "avg_solutions_per_input": 4.5, "total_api_calls": 850}
> ```
> (Part 2) the summary ... `"gsm8k": {"total": 100, "passed": 85,
> "failed": 15, "total_api_calls": 142}`

### Alternatives
1. `passed`/`failed` stay row counts, as in Part 2: a row counts as passed
   when it collected at least one passing solution (`result.passed > 0`),
   otherwise failed. The new fields are additive, as "fields gain" says.
2. `passed`/`failed` become solution counts, summing `result.passed` and
   `result.failed` over rows.
3. `passed`/`failed` are dropped in the list format, since the example block
   does not show them.

### Choice
Alternative 1. "Per-task summary fields gain:" announces additions, not
replacements, so the Part 2 keys survive with their Part 2 meaning, and the
printed block is an abbreviation showing only what is new. Solution totals
already have their own field (`total_solutions`), so re-using `passed` for
them would make the block self-contradictory.

### Risk: 40
Author's likely alternative: `passed`/`failed` summed over `result.passed` /
`result.failed`, i.e. solution counts rather than row counts.

---
## T53: `avg_solutions_per_input` rounding, scope of the new fields, and legacy rows

### Spec Text
> Per-task summary fields gain:
> ```json
> {"tasks": {"gsm8k": {"total": 100, "total_solutions": 450,
>  "avg_solutions_per_input": 4.5, "total_api_calls": 850}}}
> ```

### Alternatives
1. The new keys appear on every per-task block and also on the top-level
   summary (which is the same aggregate over all tasks), `total_solutions`
   counts emitted outputs — one for a Part 1-format row with non-null output,
   zero for a null one — and the average is rounded to two decimals.
2. They appear only inside `tasks`, leaving the top-level summary exactly as
   Part 2 left it.
3. `total_solutions` counts attempts, or counts `result.passed`.

### Choice
Alternative 1 for `total_solutions` (the number of solutions actually written
for the row is the number of items in `output`, which is also what makes
`avg_solutions_per_input` the "solutions per input" the name promises) and for
rounding (two decimals reproduces the example's `4.5` and keeps ratios such as
7/3 readable). The fields are emitted at the top level too because every other
per-task count in the summary also has a top-level aggregate, and an extra key
is harmless to a consumer that ignores it.

### Risk: 30
Author's likely alternative: the two fields inside `tasks` blocks only, with
an unrounded float average.

---
## T54: validating `icl.k`

### Spec Text
> - `icl.k` defaults to all examples in the selected setup
> - if `k` is smaller than the number of examples in the setup, use the first
>   `k`

### Alternatives
1. `k` must be an integer `>= 1`; `k` larger than the setup's example count is
   fine and simply uses them all; `k <= 1`-violations (0, negative,
   non-integer) exit 1.
2. Any integer is accepted and `k <= 0` yields a setup with no examples.
3. `k` greater than the available examples is itself an error.

### Choice
Alternative 1. The rule only describes `k` smaller than the example count, so
a larger `k` cannot be an error — "defaults to all examples" shows that using
every example is a normal outcome. A non-positive `k` has no sensible reading
("use the first 0 examples" is just "no ICL"), and this project validates
other numeric knobs (`n >= 1`, `max_tokens > 0`) the same way.

### Risk: 30
Author's likely alternative: no validation at all, so `k: 0` silently produces
an ICL setup with no example turns.

---
## T55: an `icl` block with no usable setups

### Spec Text
> - each setup has a `name` and exactly one of `examples` or `file`

### Alternatives
1. `icl.setups` must be present and a non-empty list; an empty list, a missing
   key, or a setup that has neither (or both) of `examples`/`file` exits 1.
2. An `icl` block with no setups is treated as "ICL not configured" and the
   row falls back to the Part 1 output format.

### Choice
Alternative 1. "Each setup has a `name` and exactly one of ..." is a hard
requirement, and every other structural violation in this project exits 1
before any request is sent; a config that asks for ICL and supplies none is a
mistake, not a silent no-op. Treating it as unconfigured would also change the
output format, which is the more surprising failure mode.

### Risk: 20
Author's likely alternative: tolerate an empty `setups` list as "no ICL".

---
## T56: `--icl-k` / `--icl-strategy` for a task with no ICL block

### Spec Text
> New flags:
> - `--num-solutions <int>`
> - `--icl-strategy <fixed|random|round_robin>`
> - `--icl-k <int>`
>
> - CLI flags override config values

### Alternatives
1. They override the corresponding `icl` values where ICL exists and are
   ignored for tasks with no `icl` block — they cannot conjure examples.
2. They are an error when no task defines ICL.

### Choice
Alternative 1. The flags are overrides for config values, and in a multi-task
run one task may use ICL while another does not, so erroring would make the
flags unusable exactly where they are most useful. A task with no setups has
nothing for `k` or `strategy` to select between, so ignoring them keeps that
task's Part 1 behavior intact.

### Risk: 10
Author's likely alternative: the same, with the flags stored but unused.

---
## T57: an ICL example whose `input` lacks a field the prompt template needs

### Spec Text
> - each example's `input` is rendered with the task's `prompt.user` template

### Alternatives
1. It is a fatal error, reported before any request is sent, because the
   example turn cannot be rendered.
2. The missing placeholder is left in the rendered text verbatim.
3. The example is silently dropped.

### Choice
Alternative 1. Part 1 already makes a missing placeholder field a fatal error
for input rows; an ICL example is rendered with the same template and the same
substitution rules, so it fails the same way. Doing it at load time also
satisfies the neighbouring requirement that bad ICL data "terminate the run
with exit code 1 before any API requests are sent".

### Risk: 25
Author's likely alternative: no check at all — `str.format`-style rendering
that happens to leave or blank out the placeholder without failing.

---
## T58: whether `sample` tops up attempts that returned no response

### Spec Text
> - `sample` with ICL: make one sampled generation per requested solution
> - `sample` without ICL: make `num_solutions` independent sampled requests

### Alternatives
1. Exactly `num_solutions` attempts, full stop: an attempt whose HTTP calls
   are exhausted simply yields one fewer solution.
2. Keep issuing requests until `num_solutions` solutions exist.

### Choice
Alternative 1. Both bullets count *requests*, not results ("one sampled
generation per requested solution", "`num_solutions` independent sampled
requests"), and only `rejection` is given a retry budget (`max_attempts`) —
which would be pointless if every scheme retried until satisfied.

### Risk: 15
Author's likely alternative: the same; retrying would need an attempt cap the
spec never defines for `sample`.

---
## T59: `generation.n` for rejection outside legacy mode

### Spec Text
> - `max_attempts` applies to rejection sampling in this part
> - if `max_attempts` is omitted for rejection, default it to
>   `3 * num_solutions`
> - legacy compatibility: when `num_solutions == 1` and no ICL is configured,
>   keep the Part 1 rejection behavior (`generation.n` logical attempts) and do
>   not apply `max_attempts`

### Alternatives
1. The two budgets are mutually exclusive: in legacy mode `n` is the attempt
   budget and `max_attempts` is ignored even when set; otherwise
   `max_attempts` (explicit, or `3 * num_solutions`) is the budget and `n` is
   ignored even when set.
2. Outside legacy mode the budget is `min(n, max_attempts)`, so a configured
   `n` still caps attempts.

### Choice
Alternative 1, which is what the legacy sentence says in both directions: it
has to name `n` as the legacy budget and to disapply `max_attempts` precisely
because the non-legacy path uses `max_attempts` instead. The spec's own
multiple-solutions example sets both `n: 5` and `max_attempts: 15` with
`num_solutions: 5`; under alternative 2 the `15` could never be reached.

### Risk: 15
Author's likely alternative: the same; `n` retained only as a per-request
parameter with no effect on the attempt count.

---
## T60: whether judge calls count as attempts

### Spec Text
> - `result.attempts` is the total number of generation attempts for the row
> - `total_api_calls`

### Alternatives
1. Only generation requests count towards `result.attempts` and
   `max_attempts`; an `llm_judge` evaluation request is an evaluation, and is
   counted only in `total_api_calls`.
2. Every HTTP request counts against the attempt budget.

### Choice
Alternative 1. The field is defined as "generation attempts", and a judge call
is made *after* a generation to evaluate it; charging it to the same budget
would halve the effective number of rejection attempts for judged tasks.
`total_api_calls` stays a count of HTTP calls, as in Parts 1 and 2.

### Risk: 10
Author's likely alternative: the same.

---
## T61: how `icl` merges from `defaults` into a task

### Spec Text
> - `num_solutions` may be set in `defaults` or per task

### Alternatives
1. `icl` merges like every other nested section (T18): one level deep, so a
   task that sets `icl.k` keeps the defaults' `icl.setups`.
2. A task that mentions `icl` at all replaces the defaults' block wholesale.

### Choice
Alternative 1, for consistency with the Part 2 merge rule already implemented
for `prompt`, `generation`, and `evaluation`; `icl` is a nested section of the
same kind. The spec only pins `num_solutions` (a scalar, so merge depth does
not matter for it), leaving the section to the general rule.

### Risk: 15
Author's likely alternative: the same; whole-section replacement would
contradict the Part 2 merge rule.

---
## T62: the default and validation of `max_iterations`

### Spec Text
> ```yaml
>     generation:
>       scheme: "agentic"
>       max_iterations: 10
> ```

### Alternatives
1. `max_iterations` is optional and defaults to the value used throughout the
   spec's examples, `10`; it must be an integer >= 1.
2. `max_iterations` is required for `scheme: agentic` and a task that omits
   it is a config error.
3. It defaults to some other number (1, or unbounded).

### Choice
Alternative 1. Every other generation key in this project has a default
(`temperature`, `max_tokens`, `n`, `max_attempts`), and the spec never lists
`max_iterations` among the required keys; `10` is the only number the spec
associates with it. An unbounded default is unusable — the loop would never
terminate against a model that always calls a tool.

### Risk: 25
Author's likely alternative: required for agentic tasks, so a missing value
raises a config error rather than running ten iterations.

---
## T63: what "`max_iterations` is reached" counts

### Spec Text
> 3. If the response contains `tool_calls`, execute every tool call, append
>    the assistant tool-call message and the tool result messages to the
>    conversation, increment the iteration count, and continue.
> 5. If `max_iterations` is reached first, output `null` and use
>    `finish_reason: "max_iterations"`.

### Alternatives
1. `max_iterations` caps the number of API requests in the loop: the run
   makes at most `max_iterations` requests, and if the last one still asks
   for tools the loop stops with `output: null`. `result.iterations` then
   equals `max_iterations`.
2. It caps the number of *tool-calling* rounds, so a run may make
   `max_iterations + 1` requests — the last one being a final-answer request
   made after the budget is spent.
3. The tools of the final over-budget round are not executed.

### Choice
Alternative 1. `result.iterations` is defined as "the number of API requests
in the loop", and the iteration count is incremented per response containing
tool calls, so the counter and the budget are in the same units: requests.
Under alternative 2 a `max_iterations: 1` task could never fail at all, which
makes the limit meaningless. Tool calls in the last response are still
executed and recorded, since step 3 executes before the limit is re-checked.

### Risk: 30
Author's likely alternative: the same request cap; the closest competing
reading is one extra final request after the limit.

---
## T64: the wire format of tool definitions in a chat request

### Spec Text
> Send an API request. In chat mode, include the task's tool definitions in
> the request body.

### Alternatives
1. The OpenAI `tools` array: `[{"type": "function", "function": {"name":
   ..., "description": ..., "parameters": ...}}]`, the shape that pairs with
   the `tool_calls` response the spec quotes.
2. The task's own YAML shape, minus `handler`, sent as `tools`.
3. The legacy `functions` field.

### Choice
Alternative 1. The spec pins the response side to "the normal OpenAI shape",
and an OpenAI-compatible server only emits `tool_calls` for requests that use
the matching `tools` schema. `handler` is local execution configuration and
is never sent.

### Risk: 20
Author's likely alternative: the same wrapped shape; a flat list is the only
plausible variant, and a test would have to assert on the request body to see
the difference.

---
## T65: the shape of the messages appended for a tool round

### Spec Text
> execute every tool call, append the assistant tool-call message and the
> tool result messages to the conversation

### Alternatives
1. The assistant message is appended exactly as the API returned it, and each
   result becomes `{"role": "tool", "tool_call_id": <id>, "name": <tool>,
   "content": <result>}` — the OpenAI convention.
2. Results are appended as `user` messages describing the tool output.
3. One `tool` message carrying every result of the round.

### Choice
Alternative 1, one `tool` message per call (the spec says "the tool result
messages", plural, for a round that may hold several calls). Echoing the
assistant message verbatim keeps `tool_call_id` links intact, which an
OpenAI-compatible server requires.

### Risk: 20
Author's likely alternative: the same, possibly without the redundant `name`
key on the tool message.

---
## T66: which argument `static_map` looks up

### Spec Text
> `static_map`: look up the first required parameter in `mapping`; if absent,
> return `default`, which defaults to `"NOT_FOUND"`

### Alternatives
1. "First required parameter" is the first entry of the tool's
   `parameters.required` list; its value in the parsed arguments is the
   mapping key. "If absent" means the key is not in `mapping`.
2. It is the first key of `parameters.properties`, in declaration order.
3. It is the first key of the arguments object the model actually sent.

### Choice
Alternative 1, with 2 and then 3 as fallbacks when a tool declares no
`required` list. The phrase names `required` directly, and the spec's example
tool declares exactly one required parameter, so all three readings agree
there. "If absent" is read as "absent from `mapping`" because that is what
`default` exists for; a call that omits the parameter entirely also falls
back to `default`.

### Risk: 15
Author's likely alternative: the same; the readings only diverge for tools
with several parameters.

---
## T67: how a `script` handler builds and runs its command

### Spec Text
> `script`: run `command` with the value of `arg_field` as a single
> command-line argument, capture stdout, and return it; on timeout or
> non-zero exit, return `"ERROR: <stderr or timeout message>"`
> ```yaml
> handler:
>   type: "script"
>   command: "python3 -c"
>   arg_field: "code"
> ```

### Alternatives
1. `command` is split into argv words (`["python3", "-c"]`) and the argument
   is appended as one more argv entry, executed without a shell. Stdout is
   returned stripped of surrounding whitespace.
2. The command and the argument are concatenated into a shell string, so the
   argument is re-split and re-expanded by the shell.
3. As 1, but stdout is returned byte-for-byte including the trailing newline.

### Choice
Alternative 1. "As a single command-line argument" is precisely the guarantee
a shell would break: `python3 -c` with a code argument containing spaces,
quotes or pipes only works when the argument is passed as one argv entry.
Stdout is stripped because a tool result is fed back into a prompt, where a
trailing newline is noise; `print(2 + 40)` returning `"42"` also matches how
the spec writes handler results (`"142"`, `"1250000"`).

### Risk: 30
Author's likely alternative: the same argv execution but returning stdout
unstripped, so results carry a trailing `"\n"`.

### Timeout
The spec gives no timeout length. This implementation reuses the Part 2
`script` evaluation timeout (10 seconds) and accepts an optional `timeout`
key in the handler block; the timeout message is
`"ERROR: command timed out after 10 seconds"`.

---
## T68: bad tool calls — unknown names and unparsable arguments

### Spec Text
> parse `function.arguments` as JSON before invoking the handler

### Alternatives
1. A call naming a tool the task did not declare, and a call whose arguments
   are not valid JSON, both stay inside the loop: the call is recorded with
   an `"ERROR: ..."` result (unknown tool) or with empty parsed arguments
   (bad JSON), and the loop continues.
2. Either case aborts the row with `output: null`.
3. Either case is skipped silently and not recorded in `result.tool_calls`.

### Choice
Alternative 1. The spec has no error path for a malformed model response, and
`result.tool_calls` "records every tool call in execution order", so dropping
one would lose information. Feeding the error back as the tool result lets
the model recover, which is the point of the loop. Unparsable arguments
become `{}`, which the handlers already handle (`static_map` returns its
default, `echo` returns `"{}"`).

### Risk: 40
Author's likely alternative: unparsable arguments are recorded as an
`"ERROR: ..."` result too, rather than being run as an empty argument object.

---
## T69: how many loops an agentic row runs, and what `attempts` counts

### Spec Text
> `agentic` also works with ICL and `num_solutions`; each solution is an
> independent loop
> in that list format, `result.attempts` is the number of loops started for
> the row, not the number of API requests across those loops

### Alternatives
1. An agentic row starts exactly `num_solutions` loops (one in the legacy
   single-solution format), whatever the loops produce. `max_attempts` and
   the rejection-sampling top-up rules do not apply to `agentic`.
2. Failed loops are retried up to `max_attempts` (defaulting to
   `3 * num_solutions`), as rejection sampling does.

### Choice
Alternative 1. The spec's worked example — `num_solutions: 2`, two successful
loops, `attempts: 2` — is consistent with both, but the spec never mentions
`max_attempts` for agentic, and "each solution is an independent loop" sets
loops equal to solutions. `agentic` is its own scheme, not a variant of
`rejection`, so its output is not evaluation-gated either: a loop that
produces final text emits an output item whether or not it passes.

### Risk: 35
Author's likely alternative: agentic loops are topped up like `sample`
attempts, so a row with a failing loop starts another one.

---
## T70: which fields a list-format `meta` entry carries

### Spec Text
> in that list format, per-loop agentic metadata lives in each `meta` entry:
> keep checkpoint 3's `icl_setup` / `evaluation_passed` fields and also
> record that loop's aggregated `total_prompt_tokens`,
> `total_completion_tokens`, `total_tokens`, `latency_ms`, `finish_reason`,
> and `iterations_detail`

### Alternatives
1. The entry holds exactly the eight enumerated fields, and this
   implementation additionally records the loop's `iterations` and
   `tool_calls` — which the list format's `result` has no room for, and which
   would otherwise be lost.
2. Exactly the eight enumerated fields, with per-loop tool calls discarded.
3. The checkpoint 3 entry (including `model` and the per-request
   `prompt_tokens`/`completion_tokens`) plus the aggregates.

### Choice
Alternative 1. The sentence enumerates what must be present, not what may
not be; dropping the record of which tools a loop called would make the list
format strictly less informative than the single-loop format for no stated
reason. The per-request token fields are deliberately not kept, because the
aggregates and `iterations_detail` supersede them — that is what "also
record that loop's aggregated ..." replaces.

### Risk: 35
Author's likely alternative: exactly the eight enumerated fields, so a test
comparing the full key set of a `meta` entry would see two extra keys.

---
## T71: an agentic loop whose API request fails permanently

### Spec Text
> If `max_iterations` is reached first, output `null` and use
> `finish_reason: "max_iterations"`.
> After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue. *(Part 1)*

### Alternatives
1. The loop stops at the failed request: `output` is `null`, the iterations
   already completed keep their metadata and tool-call records, and
   `meta.finish_reason` is `null` — it is neither a final text response nor
   the iteration limit. A loop whose very first request fails reports
   `meta: null`, as in Part 1.
2. The whole row is dropped to `meta: null` regardless of how many
   iterations succeeded.
3. `meta.finish_reason` is `"error"`.

### Choice
Alternative 1. Part 1 already fixes the failure behavior (null output,
counted as failed) and T2 already fixes metadata as "built from the
successful responses". The spec defines only two values for
`finish_reason`, so inventing a third string would be a guess; `null` says
"the loop did not end either of the two defined ways".

### Risk: 45
Author's likely alternative: `"error"` (or the string `"failed"`) as the
aggregate `finish_reason` for a loop killed by a failed request.

---
## T72: `meta.latency_ms` versus the per-iteration latencies

### Spec Text
> `meta.latency_ms` is total wall-clock time for the loop
> `meta.iterations_detail` records per-iteration token usage, latency, and
> finish reason

### Alternatives
1. `latency_ms` is measured across the whole loop, so it includes tool
   execution and retry backoff and is >= the sum of the per-iteration
   latencies.
2. It is the sum of the per-iteration request latencies.

### Choice
Alternative 1, which is what "total wall-clock time for the loop" says; the
example's `1200` also exceeds the `300 + 400 + 500` of its iterations only if
tool time counts, and matches it exactly if it does not — so the numbers do
not settle it, but the prose does. A test can only tell the two apart when
tool execution is slow.

### Risk: 20
Author's likely alternative: the sum of iteration latencies, which the
example's arithmetic also fits.

---
## T73: the default `chat_template`

### Spec Text
> ```yaml
> defaults:
>   api_type: "completions"
>   chat_template: "llama3"
> ```
> `--chat-template <chatml|llama3|mistral|zephyr>`

### Alternatives
1. `chat_template` is optional and defaults to `chatml`, the first template
   the spec lists and the most generic of the four.
2. It is required whenever `api_type` is `completions`.
3. It defaults to `llama3`, the value in the config example.

### Choice
Alternative 1. Every config key in this project has a default, and `chatml`
leads both the CLI's choice list and the built-in template list. Choosing
`llama3` because the example happens to use it would read the example as a
default; the example is a config, not a fallback.

### Risk: 40
Author's likely alternative: requiring `chat_template` for completions mode,
so a task that omits it is a config error.

---
## T74: the exact text each built-in template ends with

### Spec Text
> ```text
> <|im_start|>system
> {system_content}<|im_end|>
> <|im_start|>user
> {user_content}<|im_end|>
> <|im_start|>assistant
> ```

### Alternatives
1. The rendered prompt ends with the generation marker plus the line break
   implied by the template block: `"<|im_start|>assistant\n"` for chatml,
   `"<|start_header_id|>assistant<|end_header_id|>\n\n"` for llama3 (the
   blank line that follows every other header in that template),
   `"<|assistant|>\n"` for zephyr, and `"[/INST]"` for mistral (whose marker
   is mid-line).
2. The prompt ends exactly at the last visible character of the fenced
   block, so llama3 ends with `<|end_header_id|>` and chatml with
   `assistant`, with no trailing whitespace at all.

### Choice
Alternative 1. It is what each model's real chat template emits, and it is
what the fenced blocks say: the marker is on its own line in chatml, llama3
and zephyr, and every llama3 header in the block is followed by a blank
line. Reading the fence's final newline as "not part of the template" would
also delete the newline chatml and zephyr clearly need.

### Risk: 35
Author's likely alternative: llama3 ending at `<|end_header_id|>` with no
trailing `\n\n`, if the template was transcribed from the fence verbatim.

---
## T75: templates with no system message

### Spec Text
> `{system_content}` ... `{user_content}`
> built-in templates must handle multi-turn conversations by repeating the
> correct role markers for every message

### Alternatives
1. Templates are per-message: a task with no `prompt.system` renders no
   system block at all (no marker, no empty content).
2. The system block is always emitted, with empty content.

### Choice
Alternative 1. Once the templates are defined per message — which multi-turn
support forces — a missing system message simply contributes nothing. An
empty `<|im_start|>system\n<|im_end|>` block is text the model was never
meant to see, and it would confuse a mistral prompt (`[INST] \n\n...`)
especially.

### Risk: 20
Author's likely alternative: the same; emitting an empty system block is hard
to justify.

---
## T76: mistral's system placement and the tool role in every template

### Spec Text
> ```text
> [INST] {system_content}
>
> {user_content} [/INST]
> ```
> execute those calls and feed the results back into the next prompt
> iteration using the template's tool-role formatting

### Alternatives
1. The renderer is generic over roles: chatml/llama3/zephyr emit their role
   marker with the literal role name `tool`
   (`<|im_start|>tool`, `<|start_header_id|>tool<|end_header_id|>`,
   `<|tool|>`). Mistral has no role markers, so a tool result becomes the
   content of the next `[INST] ... [/INST]` block, and the system prompt
   leads the first instruction block, exactly as the spec's block shows.
2. Each template uses its model's official tool convention — llama 3.1's
   `ipython` role, mistral's `[TOOL_RESULTS] ... [/TOOL_RESULTS]`.
3. Tool results are rendered as user turns in every template.

### Choice
Alternative 1. "The template's tool-role formatting" describes a renderer
that formats whatever role a message carries, which is also the only way the
same four templates can support multi-turn conversations without per-role
special cases. Model-specific tool syntaxes (`ipython`, `[TOOL_RESULTS]`)
appear nowhere in the spec and would have to be invented per template.

### Risk: 40
Author's likely alternative: the same generic role marker for the three
marker templates; mistral's handling of tool results is the least
predictable part.

---
## T77: how tool definitions are rendered into a completions prompt

### Spec Text
> tool definitions are rendered into the prompt instead of being sent as a
> native `tools` field

### Alternatives
1. A tool block is appended to the system message (or added as one when the
   task has no system prompt): a short instruction plus one JSON object per
   tool (`name`, `description`, `parameters` — never `handler`), and a
   description of the `<tool_call>` reply format the spec defines.
2. The block is appended to the final user message instead.
3. Only the tool names are listed.

### Choice
Alternative 1. The spec fixes the reply format but not the prompt text, so
the only testable requirements are that the tools appear in the prompt, that
the `<tool_call>` format is explained, and that local `handler` config is
never leaked to the model. Putting it in the system turn is where an
instruction of that kind belongs and keeps the rendered user turn identical
to chat mode.

### Risk: 55
Author's likely alternative: the same idea with different wording — any test
asserting on the exact preamble text will differ, so only structural
assertions (tool names present, no `tools` field) can match.

---
## T78: parsing `<tool_call>` blocks out of completion text

### Spec Text
> parse tool calls from response text blocks of the form:
> ```text
> <tool_call>
> {"name": "lookup", "arguments": {"key": "revenue_q1"}}
> </tool_call>
> ```

### Alternatives
1. Every `<tool_call>...</tool_call>` block in the text is a call, in order;
   surrounding prose is ignored; a response with at least one parsable block
   is a tool-calling iteration, never a final answer. `arguments` may be a
   JSON object (as shown) or a JSON string, and blocks whose JSON does not
   parse are skipped.
2. Only a response consisting solely of tool-call blocks counts; text plus a
   block is a final answer.
3. Only the first block is executed.

### Choice
Alternative 1. The chat-mode rule "if one model response contains multiple
tool calls, execute and record all of them" is about the loop, not about a
transport, so completions mode inherits it. Models routinely prefix a call
with a sentence of reasoning, and treating that as a final answer would
strand the loop.

### Risk: 30
Author's likely alternative: the same; the likeliest divergence is a stricter
parser that requires the block to be the whole response.

---
## T79: which transport judge and evaluation requests use

### Spec Text
> When `api_type` is `"completions"`, send requests to
> `{api_url}/v1/completions`

### Alternatives
1. Every request the task makes — generation, agentic iterations, and
   `llm_judge` evaluation calls — uses the task's `api_type` and
   `chat_template`.
2. Judge calls always use the chat endpoint, since the judge prompt is
   defined as a system/user message pair.

### Choice
Alternative 1. `api_type` is a property of the task's API, not of one request
kind; a server that only serves `/v1/completions` cannot answer a judge call
sent to `/v1/chat/completions`. The judge's system/user messages render
through the same template as any other conversation.

### Risk: 20
Author's likely alternative: the same.

---
## T80: evaluation and `result.passed` for a loop with no final text

### Spec Text
> if `max_iterations` is hit, evaluation fails because output is `null`
> when evaluation is omitted for a single-solution agentic row, keep the part
> 1 rule: `result.passed` is `null`

### Alternatives
1. With an evaluation configured, a null output gives
   `passed: false, extracted_answer: null`. With no evaluation configured, a
   row that produced output reports `passed: null`, and a row that produced
   none reports `passed: false` — Part 1's rule for a row that failed.
2. `passed` is `null` for every row of a task with no evaluation, including
   rows that produced nothing.

### Choice
Alternative 1. Part 1 distinguishes "nothing to judge" (`null`) from "this
row failed" (`false`), and a max-iterations row is the second kind: the spec
calls it a failure and the summary has to count it as one. `passed: null`
would make the row count as passed in the summary.

### Risk: 30
Author's likely alternative: `passed: null` whenever no evaluation is
configured, with the summary counting the row by whether `output` is null.

---
## T81: `temperature` and `n` for `agentic`

### Spec Text
> ```yaml
>     generation:
>       scheme: "agentic"
>       max_iterations: 10
>       temperature: 0.0
> ```

### Alternatives
1. `agentic` places no constraint on `temperature` (the example runs at
   `0.0`) and ignores `n`, since the loop issues one request at a time.
2. `agentic` forces `temperature` to `0.0` the way `greedy` does.
3. `agentic` requires `temperature > 0` the way `sample` does.

### Choice
Alternative 1. The example sets `0.0` explicitly, which rules out the
`sample`-style requirement; forcing `0.0` would silently discard a configured
temperature, and nothing in the spec says agentic runs are deterministic.

### Risk: 10
Author's likely alternative: the same.

---
## T82: how `tools` merges from `defaults` into a task

### Spec Text
> Per-task override:
> ```yaml
> tasks:
>   gsm8k:
>     api_type: "completions"
> ```

### Alternatives
1. `tools` is a list, so the Part 2 merge rule (one level deep, per key,
   mappings only) replaces it wholesale when a task declares its own; scalar
   keys `api_type`, `chat_template` and `num_solutions` override normally.
2. Lists concatenate, so a task's tools are added to the defaults' tools.

### Choice
Alternative 1, which is the merge rule already implemented for every
non-mapping value (T18). Concatenating would make it impossible for a task to
drop a tool it inherits.

### Risk: 10
Author's likely alternative: the same.

---
## T83: which ICL setup an agentic loop uses

### Spec Text
> `agentic` also works with ICL and `num_solutions`; each solution is an
> independent loop

### Alternatives
1. Loop `i` picks its setup exactly as attempt `i` does for `sample`: by the
   configured strategy (`fixed`, `random`, `round_robin`), evaluated per row.
2. Agentic borrows the `greedy` + ICL special case (T44/T47), where
   `num_solutions > 1` walks the declared setups once each.

### Choice
Alternative 1. The `greedy` special case exists because a deterministic
prompt cannot produce a second distinct solution, so repeating a setup is
pointless. An agentic loop is not deterministic in that sense — it depends on
which tools the model calls — so the ordinary strategy applies, and
`round_robin` over two setups with `num_solutions: 2` visits both anyway.

### Risk: 20
Author's likely alternative: the same for `round_robin`/`random`; the
readings differ only for `fixed` with `num_solutions > 1`.

---
