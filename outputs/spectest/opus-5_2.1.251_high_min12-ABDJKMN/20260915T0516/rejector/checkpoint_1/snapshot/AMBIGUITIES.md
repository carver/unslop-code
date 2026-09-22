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
