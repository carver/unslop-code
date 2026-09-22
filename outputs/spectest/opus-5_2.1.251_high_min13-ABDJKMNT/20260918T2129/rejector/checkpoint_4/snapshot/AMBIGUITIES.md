# Ambiguities

Spec-reading decisions taken while implementing `rejector.py`.
Entries T1-T18 come from Part 1, T19-T34 from Part 2, T35-T50 from Part 3,
and T51 onwards from Part 4 (agentic generation and completions mode).
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

### Update (Part 4)

Part 4's agentic example extracts `"2730000"` from
`"The total revenue for Q1 and Q2 is $2,730,000."`, so the author's number
extractor reads comma-grouped figures and reports them without the commas.
`extracted_answer` is therefore no longer the literal matched text for that
one case; see [T78].

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

---

## T19: Whether `tasks` appears in the summary for single-task configs

### Spec Text

> "The stdout summary now includes a `tasks` object keyed by executed task
> name"
>
> "Existing behavior from Part 1 is unchanged unless stated here."
>
> "if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format; the task name is `task.name`"

### Alternatives

1. `tasks` is emitted only for multi-task (`defaults`/`tasks`) configs; a
   Part 1 `task` config prints exactly the Part 1 summary keys.
2. `tasks` is always emitted, keyed by `task.name` for single-task configs
   (which is why the spec bothers to define that name).

### Choice

Reading 1. "Existing behavior from Part 1 is unchanged unless stated here"
is an explicit, global rule, and the whole *Summary And Scheduling* section
is written about multi-task runs. Part 1's summary contract is therefore
preserved byte-for-byte for `task:` configs, and `task.name` is still used
for `--task` selection.

### Risk: 35

A single summary builder that always adds `tasks` is the cheaper
implementation, so the author may emit `tasks` for single-task configs too
(keyed by `task.name`). Observable on any Part 1 config run under Part 2.

---

## T20: Generation parameters for the judge request

### Spec Text

> "the judge request is a separate API call through the same server"
>
> "if `evaluation.model` is omitted, use the task's model"

### Alternatives

1. The judge call reuses the task's `generation` values (`temperature`,
   `max_tokens`) and only the model may differ.
2. The judge call is forced to be deterministic: `temperature: 0`.
3. The judge call uses provider defaults and sends neither field.

### Choice

Reading 1. `model` is the only parameter the spec says can differ, and the
judge request is described as an ordinary call "through the same server",
so the same request shape is the conservative reading.

### Risk: 30

Only observable by inspecting the judge request payload. A `temperature: 0`
judge is a common design choice, so an author whose fixture asserts on the
judge payload may expect `0.0` when the task samples at `0.7`.

---

## T21: The JSON type of `judge_score`

### Spec Text

> "if the judge returns `"8"`, then `judge_score` is `8`"
>
> "`first_number`: extract the first integer or decimal in the response"

### Alternatives

1. Emit an integer when the extracted number is integral and a float
   otherwise (`8` stays `8`, `8.5` stays `8.5`).
2. Always emit a float (`8.0`).
3. Emit the extracted string (`"8"`).

### Choice

Reading 1. The spec shows the bare integer `8`, and `first_number` also
admits decimals, so an integral score is written as an integer and a
decimal score keeps its fractional part.

### Risk: 25

An author who does `float(extracted)` unconditionally serialises `8.0`,
which is not equal to `8` under a strict JSON comparison (though it is under
Python's `==`).

---

## T22: Where `judge_meta` sits when a row has several attempts

### Spec Text

> "`meta` includes a `judge_meta` object with the judge request's token
> usage, latency, model, and finish reason"

### Alternatives

1. `judge_meta` is nested inside the attempt meta it belongs to. Part 1
   already makes `meta` a list for multi-attempt rejection rows, so each
   element carries its own `judge_meta`.
2. A single `judge_meta` sits beside the attempt list, describing only the
   final judge call.
3. Only the last attempt's meta carries `judge_meta`.

### Choice

Reading 1. Part 1 fixed `meta` as "one object per attempt, list when there
is more than one"; a judge call belongs to exactly one attempt, so pairing
them keeps the existing structure intact. For the common single-attempt case
this is identical to every other reading: `meta.judge_meta`.

### Risk: 30

Diverges only for a `rejection` + `llm_judge` row that needs more than one
attempt. The author may well have kept a single top-level `judge_meta`.

---

## T23: `extracted_answer` for `llm_judge` and `script`

### Spec Text

> "`result.extracted_answer` is the extracted comparison value, or `null`
> when there is no evaluation or no output" (Part 1)
>
> "`threshold: 7`, `extract: "first_number"`" under `llm_judge`

### Alternatives

1. For `llm_judge`, `extracted_answer` is the value `extract` pulled out of
   the *judge* response (the score as text); for `script`, there is nothing
   to extract, so it is `null`.
2. For `llm_judge`, `extracted_answer` is extracted from the *generated*
   response; for `script`, likewise.
3. `extracted_answer` is `null` for both new types.

### Choice

Reading 1. Under `llm_judge` the configured `extract` is unambiguously
applied to the judge output — that is how the score is obtained — so the
extracted comparison value for that row is the score text. `script` has no
`extract` key at all and compares an exit code, so nothing was extracted.

### Risk: 45

Three plausible readings and the spec never states one. A `script` fixture
asserting `extracted_answer` equals the whole response (Part 1's default
`extract: full`, see T4) is the most likely alternative.

---

## T24: Whether `judge_score` appears for non-judge tasks

### Spec Text

> "`result` includes `judge_score`"

### Alternatives

1. `judge_score` is present only in rows produced by an `llm_judge` task.
2. `judge_score` is always present, `null` outside `llm_judge` tasks.

### Choice

Reading 1. The sentence sits inside the `llm_judge` rule list, so it
describes that evaluation type's output, and Part 1's row schema is
otherwise unchanged (see the global "unchanged unless stated" rule).

### Risk: 20

An author who added the key to the shared row builder would emit
`"judge_score": null` on every row, which breaks an exact-shape assertion
but not a targeted one.

---

## T25: Whether the judge (or script) runs once per rejection attempt

### Spec Text

> "`rejection`: generate up to `n` times, stop at the first response that
> passes evaluation" (Part 1)
>
> "judge calls count toward throughput, `total_api_calls`, and per-task API
> call totals"

### Alternatives

1. Every rejection attempt is evaluated, so a judge call (or script run)
   happens per attempt and `total_api_calls` grows by two per attempt.
2. Only the last attempt is judged.

### Choice

Reading 1 — `llm_judge` and `script` are evaluation types, and rejection is
defined in terms of "the first response that passes evaluation", so the
evaluation must run on each attempt.

### Risk: 10

Reading 2 cannot implement rejection at all; the only real uncertainty is
whether the author allows `rejection` with these types.

---

## T26: How aggressively `letter` scans for a choice

### Spec Text

> "`letter`: extract the first uppercase answer choice `A` through `D`;
> accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
>
> "If the model returns `"The answer is B) Paris"`, `letter` extracts `"B"`"

### Alternatives

1. Match any standalone uppercase `A`-`D` — one not glued to other word
   characters — taking the first. `(A)`, `A)`, `A.`, `Answer: A` and a bare
   `A` all qualify.
2. Only match the explicitly listed decorated forms (`(A)`, `A)`,
   `Answer: A`), falling back to a bare letter only if none matched.
3. Match the first `A`-`D` character anywhere, including inside words.

### Choice

Reading 1. "accept forms such as" is an illustrative list, not an
enumeration, and a word-boundary scan accepts every listed form with one
rule. Reading 3 is rejected because `"The Answer"` would yield `A` from
inside a word, contradicting the worked example intent.

### Risk: 35

The spec's own example, `"The answer is B) Paris"`, passes under readings 1
and 2 alike. They differ on text like `"A clear choice is C"` (reading 1
gives `A`, a decorated-forms-first reading gives `C`), which is exactly the
kind of fixture an author who wrote a priority-ordered regex would include.

---

## T27: What `first_number` accepts

### Spec Text

> "`first_number`: extract the first integer or decimal in the response"

### Alternatives

1. Same number grammar as Part 1's `last_number`, taken from the front:
   optional leading `-`, digits, optional `.` fraction.
2. Unsigned only, since scores are positive.

### Choice

Reading 1 — symmetry with `last_number` is the obvious implementation, and
the spec uses the same words ("integer or decimal") for both.

### Risk: 15

Differs only on a response whose first number is negative, which is an
unlikely fixture for a 1-10 judge score.

---

## T28: Shell-escaping the response inside a script command

### Spec Text

> "if a row field such as `{test_code}` expands to text that itself contains
> `{__response__}`, substitute `__response__` before executing the command"
>
> "run the rendered command in a shell"

### Alternatives

1. Substitute the raw response text verbatim, exactly as with any other
   placeholder. The config author is responsible for the quoting in
   `command_template` / `test_code`.
2. Shell-quote the response before substitution.

### Choice

Reading 1. The spec's example, `echo '{__response__}' | grep -q 'good code'`,
supplies its own surrounding single quotes — which would be doubled up and
broken by automatic quoting. Substitution is plain text replacement.

### Risk: 20

Only observable with a response containing shell metacharacters, where
reading 1 can produce a command that fails to parse (a non-zero exit, hence
a failed row).

---

## T29: How `defaults` merges into a task

### Spec Text

> "`defaults` provides shared values; each task overrides `defaults`"
>
> "nested sections such as `prompt`, `generation`, and `evaluation` are
> merged per task using the Part 1 structure"

### Alternatives

1. Recursive merge: any mapping value is merged key-by-key at every depth,
   non-mapping values are replaced outright.
2. Two-level merge only: top-level keys replace, except the named sections
   `prompt`/`generation`/`evaluation`, which merge one level deep.

### Choice

Reading 1 — a general recursive merge. On the structures the config format
actually admits (`prompt`, `generation`, `evaluation`, and `judge_prompt`
inside `evaluation`) it agrees with reading 2 everywhere except a
`defaults.evaluation.judge_prompt`, where merging is clearly the friendlier
behaviour.

### Risk: 15

The two readings only diverge for a nested `judge_prompt` supplied partly by
`defaults` and partly by a task.

---

## T30: An `--input` mapping naming an unknown or unselected task

### Spec Text

> "when `--task` is present, require input only for selected tasks and
> ignore unselected tasks for validation and execution"

### Alternatives

1. `--input <name>=<path>` for a task that is not in the config is an error
   (exit 1); a mapping for a task that exists but was not selected by
   `--task` is ignored, since unselected tasks are "ignored for validation".
2. Any unrecognised mapping key is an error.
3. All unrecognised mapping keys are silently ignored.

### Choice

Reading 1. A name absent from the config is a typo the user wants reported,
while the spec explicitly says unselected tasks are ignored — including the
input they would otherwise have needed.

### Risk: 25

An author who validates mappings against the *selected* set alone would
reject a leftover `--input mmlu=...` on a `--task gsm8k` run.

---

## T31: Creating the multi-task output directory

### Spec Text

> "for multi-task configs, `--output` must be a directory"
>
> "write `<output_dir>/<task_name>.jsonl`"

### Alternatives

1. Create the directory (and parents) if it does not exist; error only if
   the path exists as a non-directory.
2. Require the directory to already exist and error otherwise.

### Choice

Reading 1. Part 1 creates the output file rather than demanding it exist,
and every example in the spec passes `results/` without first creating it.

### Risk: 20

An author who validates with `Path(out).is_dir()` would exit 1 on a fresh
`results/`, but their own examples suggest otherwise.

---

## T32: `--eval-model` when a selected task is not `llm_judge`

### Spec Text

> "`--eval-model <string>`: override the judge model for all selected
> `llm_judge` tasks"

### Alternatives

1. Apply it to every selected `llm_judge` task and ignore it elsewhere; a
   run with no judge task accepts the flag and does nothing.
2. Error when no selected task uses `llm_judge`.

### Choice

Reading 1 — the flag is scoped to "`llm_judge` tasks" by its own wording, so
tasks of other types simply have nothing to override.

### Risk: 10

Erroring on an inapplicable override would be unusual for this CLI, which
accepts every other override unconditionally.

---

## T33: `--task` against a single-task config

### Spec Text

> "`--task <name>`: repeatable; run only the selected task or tasks"
>
> "if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format; the task name is `task.name`"

### Alternatives

1. `--task` is honoured: a name equal to `task.name` runs the task, any
   other name is an error (exit 1).
2. `--task` is ignored for single-task configs.
3. `--task` is rejected for single-task configs.

### Choice

Reading 1. The spec defines the name of a single-task config for some
purpose, and selection is the only feature that consumes task names outside
the multi-task file layout.

### Risk: 30

Only observable if a fixture passes `--task` with a Part 1 config. An author
may simply ignore the flag there, in which case a mismatched name still
exits 0.

---

## T34: The default `success_exit_code`

### Spec Text

> "`success_exit_code: 0`"
>
> "exit code equal to `success_exit_code` means pass; any other exit code
> means fail"

### Alternatives

1. `success_exit_code` defaults to `0` when omitted.
2. `success_exit_code` is required for `script` evaluations.

### Choice

Reading 1 — `0` is the universal shell success code and is the value shown
in both examples, so treating it as the default cannot surprise anyone.

### Risk: 10

Only diverges on a `script` config that omits the key, where reading 2 would
exit 1.

---

## T35: The default `icl.strategy`

### Spec Text

> "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
>
> "`fixed`: always use the first setup"

### Alternatives

1. `strategy` is required whenever `icl` is configured.
2. It defaults to `fixed`, the degenerate strategy that ignores every setup
   after the first.
3. It defaults to `round_robin`, so that declaring several setups without a
   strategy still exercises all of them.

### Choice

Reading 2. `k` is explicitly optional, and nothing marks `strategy` as
required, so rejecting a config without it would be harsher than the spec
asks. Of the three values `fixed` is the one that needs no extra state and is
listed first, which is the conventional default.

### Risk: 25

The author most likely also defaults to `fixed`; the alternative they might
prefer is `round_robin`, which only shows up on a multi-setup config that
omits `strategy` and makes more than one attempt.

---

## T36: Whether `random` and `round_robin` state spans rows

### Spec Text

> "`random`: choose a setup independently for each attempt"
>
> "`round_robin`: cycle through setups in order across attempts"
>
> "Round-robin order with setups `[A, B, C]`: attempt 1 uses `A` ... attempt
> 5 uses `B`"

### Alternatives

1. One rotation per input row: attempt numbering restarts for every row.
2. One rotation for the whole task: attempt numbering is global, so the setup
   a row sees depends on how many attempts other rows made first.

### Choice

Reading 1. Rows are processed concurrently, so a shared counter would make a
row's prompts depend on scheduling order and the output file would not be
reproducible. The worked example numbers attempts from 1, which is the
per-row attempt counter already reported as `result.attempts`.

### Risk: 20

The author most likely also keeps the cycle per row; a sequential reference
implementation with a task-level counter would differ on any multi-row
fixture with more than one setup.

---

## T37: `generation.n` once `max_attempts` governs rejection

### Spec Text

> ```yaml
> generation:
>   scheme: "rejection"
>   temperature: 0.7
>   n: 5
>   max_attempts: 15
> num_solutions: 5
> ```
>
> "legacy compatibility: when `num_solutions == 1` and no ICL is configured,
> keep the Part 1 rejection behavior (`generation.n` logical attempts) and do
> not apply `max_attempts`"

### Alternatives

1. Outside the legacy case `n` is ignored entirely; `max_attempts` is the
   only attempt budget.
2. `n` still caps attempts, so the effective budget is `min(n, max_attempts)`.
3. `n` becomes the OpenAI `n` request parameter, asking the server for `n`
   choices per call.

### Choice

Reading 1. The legacy sentence draws the line explicitly: `n` is Part 1's
budget, `max_attempts` is this part's, and each applies on its own side of
the line. The example config carries both `n: 5` and `max_attempts: 15`, and
a `min()` of the two would make `max_attempts: 15` dead configuration.

### Risk: 30

The author most likely also ignores `n`; if they instead intended
`min(n, max_attempts)`, a rejection run with `n: 5`, `max_attempts: 15` and
no passes would make 5 attempts instead of 15.

---

## T38: `greedy` without ICL when `num_solutions > 1`

### Spec Text

> "`greedy` with ICL: generate at temperature `0` once per selected setup and
> stop when `num_solutions` solutions are collected or all setups are
> exhausted; because the same setup is deterministic, the maximum number of
> produced solutions is the number of available setups"
>
> "do not retry the same greedy setup to manufacture additional outputs"

### Alternatives

1. One attempt, one solution: without ICL there is exactly one prompt, and
   repeating it is the retry the spec forbids.
2. `num_solutions` attempts anyway, emitting identical solutions.

### Choice

Reading 1, treating "no ICL" as a single anonymous setup. The spec's stated
reason for the cap is determinism, which holds just as strongly when there
are no setups at all, and it names manufacturing duplicate outputs as the
thing to avoid.

### Risk: 25

The author most likely also emits one solution; a loop that simply runs
`num_solutions` times regardless of scheme would emit duplicates and report
`attempts: num_solutions` instead of `attempts: 1`.

---

## T39: Which keys the list-format `result` carries

### Spec Text

> ```json
> "result": {
>   "passed": 2,
>   "failed": 5,
>   "attempts": 7
> }
> ```

### Alternatives

1. Exactly the three keys shown; `extracted_answer` and `judge_score` are
   Part 1 fields of the single-solution format only.
2. Keep `extracted_answer` (and `judge_score` for judges) alongside them,
   describing the last or the first solution.

### Choice

Reading 1. `passed` changes meaning from a boolean to a count in this format,
so the object was redefined rather than extended, and a single
`extracted_answer` cannot describe a list of solutions.

### Risk: 20

The author most likely emits the three documented keys; a test asserting the
whole `result` object would fail if they also carried `extracted_answer`
through.

---

## T40: A row that collects no solutions

### Spec Text

> "`rejection` with ICL: keep generating and evaluating until
> `num_solutions` passing solutions have been collected or `max_attempts` is
> exhausted"
>
> "write only those two passing outputs"

### Alternatives

1. `output` is an empty list `[]`.
2. `output` is `null`, echoing Part 1's failed-row shape.

### Choice

Reading 1. In this format `output` is "a list of objects", and the natural
list of zero passing solutions is the empty one; `result.passed: 0` already
records the failure, and keeping the type stable makes the file easier to
consume.

### Risk: 15

The author most likely also writes `[]`; a fixture where every rejection
attempt fails would distinguish the two.

---

## T41: Attempts whose API call never returns a completion

### Spec Text

> "`result.attempts` is the total number of generation attempts for the row"
>
> "`meta` is a list with one entry per attempt"
>
> "`result.failed` is the number of attempts that produced no output"

### Alternatives

1. A request that fails after its retries still counts in `result.attempts`
   but contributes no metadata entry, since there is no response to describe.
2. It is not counted as an attempt at all.
3. It contributes a placeholder metadata entry with null token counts.

### Choice

Reading 1. Part 1 already reports a failed row's attempt count without a
metadata object for the failed call, and the sentence about attempts "that
produced no output" only makes sense if such attempts are counted. The one
casualty is that `meta` is shorter than `attempts` on those rows, which is
unavoidable without inventing metadata.

### Risk: 30

The author most likely also counts the attempt; the observable difference is
confined to runs where the fake API returns 4xx/5xx, and a strict reading of
"one entry per attempt" would favour reading 3.

---

## T42: `result.failed` when `sample` keeps failing solutions

### Spec Text

> "`sample` with ICL: ... evaluation does not gate whether a solution is
> included"
>
> "`result.passed` is the count of passing solutions"
>
> "`result.failed` is the count of failed attempts"
>
> "report `passed: 2`, `failed: 8`, and `attempts: 10`"

### Alternatives

1. `failed == attempts - passed` in every scheme, so a sampled solution that
   is emitted but fails evaluation counts as a failed attempt.
2. `failed` counts only attempts that produced no output, so a sample run
   where everything is emitted reports `failed: 0` regardless of evaluation.

### Choice

Reading 1. Both worked examples satisfy `passed + failed == attempts`
(`2 + 5 == 7` and `2 + 8 == 10`), and an attempt that was judged and rejected
is a failed attempt even when its text is still written out.

### Risk: 20

The author most likely also subtracts; a `sample` fixture with a mixed
pass/fail responder is where the readings diverge.

---

## T43: Where the solution counters appear in the summary

### Spec Text

> "Per-task summary fields gain:"
>
> ```json
> {"tasks": {"gsm8k": {"total": 100, "total_solutions": 450,
> "avg_solutions_per_input": 4.5, "total_api_calls": 850}}}
> ```

### Alternatives

1. `total_solutions` and `avg_solutions_per_input` are added to every
   per-task entry, always, and the top-level summary keeps its Part 1 keys.
2. They are added per task only when that task is in the multi-solution
   format.
3. They are added to the top-level summary as well, so single-task configs
   report them too.

### Choice

Reading 1. The heading scopes the change to per-task fields, and a summary
whose keys depend on the scheme would be awkward to consume; a single-solution
task simply reports one solution per successful row.
`avg_solutions_per_input` is rounded to two decimals, which reproduces the
documented `4.5` exactly.

### Risk: 35

The author most likely adds them unconditionally per task, but may well also
surface them at the top level — a single-task run with `num_solutions > 1` is
the fixture that would show it, and their Part 2 top-level key set would then
differ from mine.

---

## T44: Row-level `passed`/`failed` for multi-solution rows

### Spec Text

> "passed: rows where `result.passed` is true" (Part 1)
>
> "`result.passed` is the count of passing solutions"

### Alternatives

1. A row counts as passed when at least one solution passed
   (`result.passed > 0`).
2. A row counts as passed only when it collected the full `num_solutions`.
3. The summary counts solutions rather than rows once the list format is in
   use.

### Choice

Reading 1. `total` still counts input rows, so `passed` and `failed` must
partition the same set; "at least one passing solution" is the direct
translation of Part 1's truthiness test now that `result.passed` is a count,
and the solution totals live in the new fields.

### Risk: 25

The author most likely also treats a non-zero count as a passed row; a
partial rejection result (2 of 5 solutions) is what separates readings 1
and 2.

---

## T45: A setup that resolves to zero examples

### Spec Text

> "each setup has a `name` and exactly one of `examples` or `file`"
>
> "file-backed setups must be valid JSONL where each non-empty line has
> `{"input": <object>, "output": <string>}`"

### Alternatives

1. An empty `examples: []` or an example file with no example lines is a
   configuration error.
2. It is accepted, and that setup simply sends the prompt with no ICL turns.

### Choice

Reading 1. A setup exists to supply demonstrations; an empty one is far more
likely a wrong path or a truncated file than a deliberate zero-shot control,
and failing at load time is cheaper than discovering it in the output.

### Risk: 20

The author most likely does not special-case it, in which case an empty
file-backed setup would run as a plain prompt instead of exiting 1.

---

## T46: Example inputs that the user template cannot render

### Spec Text

> "each example's `input` is rendered with the task's `prompt.user` template"

### Alternatives

1. Validate at load time that every example input carries the fields the
   template references, and exit 1 when one is missing.
2. Discover it at render time, which crashes mid-run.
3. Render the missing placeholder as an empty string.

### Choice

Reading 1. The spec already insists that malformed example data terminates
the run before any API request; an example that cannot be rendered is the
same class of problem, and reporting it as a configuration error keeps exit
code 1 with a message on stderr.

### Risk: 15

Only observable on a deliberately mismatched example; reading 3 would let
such a config run to completion.

---

## T47: `--icl-k` and `--icl-strategy` on a task without ICL

### Spec Text

> "New flags: `--num-solutions <int>`, `--icl-strategy <fixed|random|
> round_robin>`, `--icl-k <int>`"
>
> "CLI flags override config values"

### Alternatives

1. The ICL flags override the corresponding `icl` values only on tasks that
   declare setups, and are inert elsewhere.
2. Passing them without an `icl` section is an error.
3. They synthesise an `icl` section, which then fails validation for having
   no setups.

### Choice

Reading 1, matching how `--eval-model` already behaves for non-judge tasks.
In a multi-task run only some tasks may configure ICL, and a global flag
should not make the run unlaunchable because of the others.

### Risk: 10

Erroring would only be visible to someone passing a flag that has nothing to
act on.

---

## T48: `k` larger than the setup

### Spec Text

> "`icl.k` defaults to all examples in the selected setup"
>
> "if `k` is smaller than the number of examples in the setup, use the first
> `k`"

### Alternatives

1. `k` caps the examples used, so a larger `k` simply uses all of them.
2. A `k` larger than some setup's example count is a configuration error.

### Choice

Reading 1. The spec only defines behaviour for `k` smaller than the setup and
describes `k` as a count of examples to use; with setups of differing sizes,
erroring would make a single shared `k` unusable.

### Risk: 10

Reading 2 would only differ on a config whose `k` exceeds a setup's size.

---

## T49: Whether ICL examples also precede judge prompts

### Spec Text

> "ICL examples are inserted between the system message and the final user
> message as alternating user and assistant turns"
>
> "each example's `input` is rendered with the task's `prompt.user` template"

### Alternatives

1. Examples are part of the generation prompt only; `llm_judge` calls are
   unchanged.
2. Examples precede the judge's user message too.

### Choice

Reading 1. The examples are rendered with the task's own `prompt.user`
template and demonstrate the task, not the scoring; feeding them to a judge
that expects a rendered `judge_prompt` would be incoherent.

### Risk: 10

Only visible on an `llm_judge` task that also configures ICL.

---

## T50: `greedy` with ICL and `num_solutions == 1`

### Spec Text

> "for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
> strategy and instead walks setups in declared order, at most once per setup"

### Alternatives

1. With `num_solutions == 1` the configured strategy applies as usual, so a
   `random` setup may be chosen for the single attempt.
2. Greedy always walks setups in declared order, making the single attempt
   always use the first setup.

### Choice

Reading 1. The override is stated with an explicit `num_solutions > 1`
condition, and a single greedy attempt has no duplicate-output problem to
avoid, so there is no reason to discard the strategy.

### Risk: 15

The author most likely also honours the strategy here; the readings only
differ for a greedy, single-solution task using `random` or `round_robin`,
where reading 2 would always pick the first setup.

---

## T51: How tool definitions are shaped in a chat request

### Spec Text

> "Send an API request. In chat mode, include the task's tool definitions in
> the request body."
>
> "For chat mode, tool calls use the normal OpenAI shape"

### Alternatives

1. The OpenAI request shape: `tools: [{"type": "function", "function":
   {name, description, parameters}}]`.
2. The config's own shape, passed through: `tools: [{name, description,
   parameters}]` (minus `handler`).

### Choice

Reading 1. The spec anchors the response side to "the normal OpenAI shape",
and the request side of that same API wraps every declaration in
`{"type": "function", "function": {...}}`; a server that accepts tool calls
in the OpenAI shape expects the definitions in it too.

### Risk: 30

The author may forward the config entries verbatim, which is the shorter
implementation and is what a fixture asserting
`payload["tools"][0]["name"] == "lookup"` would expect.

---

## T52: Whether the last iteration's tool calls still run

### Spec Text

> "If the response contains `tool_calls`, execute every tool call, append the
> assistant tool-call message and the tool result messages to the
> conversation, increment the iteration count, and continue."
>
> "If `max_iterations` is reached first, output `null` and use
> `finish_reason: "max_iterations"`."

### Alternatives

1. Execution comes before the budget check, as the numbered steps read: the
   tool calls of the final allowed request are executed and recorded, and
   only then does the loop stop.
2. The budget is checked as soon as the final request returns, so its tool
   calls are discarded and `result.tool_calls` ends one round short.

### Choice

Reading 1. Step 3 executes, then increments, then continues; the limit is
only consulted at the "continue", so the final response is handled like any
other. It also keeps `tool_calls` a faithful record of what the tools
actually did.

### Risk: 30

Only visible in a max-iterations fixture that inspects `result.tool_calls`.
The author may stop as soon as the counter hits the cap, leaving the last
response's calls unrecorded.

---

## T53: The default `max_iterations`

### Spec Text

> "generation: scheme: "agentic" / max_iterations: 10"

### Alternatives

1. `max_iterations` is required for agentic tasks.
2. It defaults to the value used throughout the spec, `10`.
3. It defaults to something else (1, or unbounded).

### Choice

Reading 2. Every other generation key has a default, an unbounded tool loop
against a live API is not a sane fallback, and `10` is the only number the
spec ever shows.

### Risk: 25

An agentic config that omits `max_iterations` is the only way to tell. The
author most likely also defaults to 10, but may reject the config instead.

---

## T54: Which keys the aggregated agentic `meta` carries

### Spec Text

> ```json
> "meta": {
>   "total_prompt_tokens": 850, "total_completion_tokens": 120,
>   "total_tokens": 970, "latency_ms": 1200, "finish_reason": "stop",
>   "iterations_detail": [...]
> }
> ```

### Alternatives

1. Exactly the six keys shown; the per-iteration entries likewise carry
   exactly the five keys shown.
2. The Part 1 `meta.model` key is kept as well, since every earlier row
   format carries it.

### Choice

Reading 1. The example is a whole `meta` object rather than an excerpt, and
the list of rules that follows enumerates its contents without mentioning
`model`. A model name that is constant for the task is also the least
useful thing to repeat once per iteration.

### Risk: 25

A fixture comparing the whole `meta` object, or its key set, would fail if
the author kept `model`; a fixture reading single fields never notices.

---

## T55: `meta.finish_reason` when the final response did not stop cleanly

### Spec Text

> "`meta.finish_reason` is `"stop"` for a final text response and
> `"max_iterations"` when the iteration limit is hit"

### Alternatives

1. Report the finish reason the final response carried, which is `"stop"`
   in the ordinary case but `"length"` for a truncated answer.
2. Hard-code `"stop"` for every run that ended with text.

### Choice

Reading 1. The sentence contrasts a real API finish reason with the
loop-level one the pipeline invents; propagating keeps the truncation signal
that `finish_reason` exists to carry, and it still prints `"stop"` for every
normal run.

### Risk: 30

A fixture whose last response reports `"length"` separates the readings. If
the author literally writes `"stop"`, their expected value is `"stop"`.

---

## T56: Whether a rendered template ends with a newline

### Spec Text

> ```text
> <|im_start|>system
> {system_content}<|im_end|>
> <|im_start|>user
> {user_content}<|im_end|>
> <|im_start|>assistant
> ```

### Alternatives

1. Each template block is the literal text of the prompt, trailing newline
   included, so a rendered `chatml` prompt ends `<|im_start|>assistant\n`.
2. The final newline belongs to the code fence, not the template, so the
   prompt ends `<|im_start|>assistant`.

### Choice

Reading 1, applied uniformly to all four templates. The blocks read as file
contents, and the real-world `chatml`, `llama3` and `zephyr` generation
prompts all place a newline after the marker that opens the assistant turn.

### Risk: 35

A fixture comparing the whole prompt string separates the readings. The
`mistral` block is the weakest case for this choice: `[/INST]` is normally
followed directly by the answer, so the author may emit no trailing newline
there, or none anywhere.

---

## T57: The default `chat_template`

### Spec Text

> "defaults: api_type: "completions" / chat_template: "llama3""
>
> "this checkpoint evaluates only the four built-in templates above"

### Alternatives

1. `chat_template` is required whenever `api_type` is `completions`.
2. It defaults to `chatml`.

### Choice

Reading 2, with `chatml` as the default. The config example always pairs the
two keys, so the default is rarely observable; `chatml` is the most generic
of the four and the one an OpenAI-compatible server is likeliest to accept.

### Risk: 25

Only a completions config that omits `chat_template` can tell. The author
may instead reject that config as incomplete.

---

## T58: A conversation with no system message

### Spec Text

> "<|im_start|>system\n{system_content}<|im_end|>"
>
> "`prompt.system` is optional" (Part 1)

### Alternatives

1. The system block is omitted entirely when the task declares no system
   prompt.
2. The block is rendered with empty content.

### Choice

Reading 1. A template is built from the messages that exist; an empty system
turn is noise that some servers treat as a real instruction.

### Risk: 20

Needs a completions task without `prompt.system`. The author may render the
skeleton with an empty slot, since a naive `TEMPLATE.format(...)` does.

---

## T59: How `mistral` renders more than one turn

### Spec Text

> ```text
> [INST] {system_content}
>
> {user_content} [/INST]
> ```
>
> "built-in templates must handle multi-turn conversations by repeating the
> correct role markers for every message"

### Alternatives

1. The system prompt opens the first instruction block only; later user
   turns are bare `[INST] ... [/INST]` blocks, and an assistant turn is its
   own text closed with `</s>`.
2. The system prompt is repeated in every instruction block.
3. Assistant turns are wrapped in markers of their own.

### Choice

Reading 1. It matches Mistral's real prompt format, and it is the only
reading under which the single-turn rendering in the spec is the special
case of the general one.

### Risk: 40

Mistral is the one built-in template with no assistant marker, so every
implementation invents something here. The author most likely also repeats
only `[INST]`, but the separator around `</s>` (a space, a newline, or
nothing) is a coin toss.

---

## T60: The "tool-role formatting" of each template

### Spec Text

> "execute those calls and feed the results back into the next prompt
> iteration using the template's tool-role formatting"

### Alternatives

1. Treat `tool` as one more role: `<|im_start|>tool`, `<|tool|>` and
   `<|start_header_id|>tool<|end_header_id|>` for the three marker-based
   templates, and `[TOOL_RESULTS] ... [/TOOL_RESULTS]` for `mistral`.
2. Feed results back as user turns, since only the four documented roles
   have markers.
3. Use each model family's real tool role (`ipython` for llama3,
   `[TOOL_RESULTS]` for mistral, a user turn elsewhere).

### Choice

Reading 1. "The template's tool-role formatting" names a tool role, and the
templates are defined by repeating a marker per role, so the tool result is
just another message with `role: "tool"`.

### Risk: 45

Unspecified beyond that phrase. A fixture asserting the next prompt contains
the tool result will pass under any reading; one asserting the exact markers
may expect llama3's `ipython` role or a user turn.

---

## T61: How tool definitions are rendered into a completions prompt

### Spec Text

> "tool definitions are rendered into the prompt instead of being sent as a
> native `tools` field"

### Alternatives

1. Append a tools section to the system message: the JSON declarations plus
   an instruction describing the `<tool_call>` block the loop parses back.
2. Prepend a separate system turn holding the same text.
3. Some fixed prose wording specific to the author's implementation.

### Choice

Reading 1, keeping the task's own system prompt first. The model has to be
told both what exists and how to ask for it, and the `<tool_call>` syntax is
the only call format this checkpoint accepts.

### Risk: 55

The wording of the block is not specified at all, so any fixture comparing
the rendered prompt exactly will differ. Tests that only check the tool name
and `<tool_call>` appear in the prompt pass either way; the author's own
block is most likely a JSON list of the definitions under a short heading.

---

## T62: `static_map` when the tool declares no required parameter

### Spec Text

> "`static_map`: look up the first required parameter in `mapping`; if
> absent, return `default`, which defaults to `"NOT_FOUND"`"

### Alternatives

1. Fall back to the first argument the model actually supplied.
2. Treat a tool with no `required` list as a config error.
3. Always return the default.

### Choice

Reading 1. `parameters.required` merely names which argument carries the
key; when it is missing, the single argument the model sent is unambiguously
that key. Rejecting the config would fail tasks whose JSON schema is loose
but whose behaviour is well defined.

### Risk: 20

Needs a `static_map` tool whose `parameters` omit `required`. The author may
raise a config error there instead.

---

## T63: Whether script stdout is trimmed

### Spec Text

> "`script`: run `command` with the value of `arg_field` as a single
> command-line argument, capture stdout, and return it"

### Alternatives

1. Return stdout with surrounding whitespace stripped, so `print(42)` yields
   `"42"`.
2. Return stdout byte for byte, so the same call yields `"42\n"`.

### Choice

Reading 1. The result is a string spliced into a conversation and recorded
in `result.tool_calls`, where a trailing newline is an artefact of `print`
rather than part of the answer; the `static_map` and `echo` handlers both
return clean values too.

### Risk: 35

A fixture that runs `python3 -c "print(...)"` and compares the recorded
result separates the readings; `"42\n"` is what an untrimmed implementation
records.

---

## T64: The text of a script handler's error result

### Spec Text

> "on timeout or non-zero exit, return `"ERROR: <stderr or timeout message>"`"

### Alternatives

1. `"ERROR: "` followed by the process's stderr, stripped, for a non-zero
   exit; `"ERROR: timed out after <n>s"` for a timeout.
2. Include the exit code, or the command, in the message.
3. A fixed string such as `"ERROR: timeout"`.

### Choice

Reading 1. The spec fixes the `ERROR: ` prefix and says the remainder is the
stderr or a timeout message, so stderr is passed through unchanged and the
timeout wording states what happened and when.

### Risk: 40

The prefix is safe; the timeout wording is invented, so a fixture comparing
the whole timeout string will differ. A fixture asserting the result starts
with `ERROR: ` passes either way.

---

## T65: A tool call naming a tool the task does not declare

### Spec Text

> "If the response contains `tool_calls`, execute every tool call"

### Alternatives

1. Record an `ERROR: unknown tool '<name>'` result and carry on, so the
   model can recover on the next iteration.
2. Abort the loop and emit `null` for the row.
3. Skip the call silently.

### Choice

Reading 1. A tool result is how this loop reports anything back to the
model, and the `script` handler already reports its failures as `ERROR: `
strings rather than ending the run.

### Risk: 30

Unspecified. A hidden test would have to script a hallucinated tool name;
the author may well let the lookup raise and fail the row.

---

## T66: Whether the list format keeps `iterations` and `tool_calls`

### Spec Text

> "in that list format, `result.attempts` is the number of loops started for
> the row, not the number of API requests across those loops"
>
> "in that list format, per-loop agentic metadata lives in each `meta` entry:
> keep checkpoint 3's `icl_setup` / `evaluation_passed` fields and also
> record that loop's aggregated `total_prompt_tokens`,
> `total_completion_tokens`, `total_tokens`, `latency_ms`, `finish_reason`,
> and `iterations_detail`"

### Alternatives

1. The list format keeps checkpoint 3's `result` exactly - `passed`,
   `failed`, `attempts` - and each `meta` entry carries exactly the fields
   enumerated above, so per-loop `iterations` and `tool_calls` are not
   emitted.
2. Each `meta` entry also records that loop's `iterations` and `tool_calls`,
   since dropping the tool trace loses information the single-solution
   format keeps.

### Choice

Reading 1. The spec enumerates both objects in full for this format and
mentions neither key; the enumeration reads like a description of an
implementation whose `result` holds the counters and whose per-loop metadata
object is exactly the aggregated one.

### Risk: 30

If the author's loop metadata object happens to include its own
`tool_calls`, a fixture checking the tool trace of a `num_solutions: 2` run
would fail here.

---

## T67: Metadata for a loop that produced no output

### Spec Text

> "each emitted output item represents one completed agentic loop"
>
> "`result.failed` is the number of loops that produced no output"

### Alternatives

1. A loop that hits `max_iterations` still contributes a `meta` entry - it
   made real requests and spent real tokens - but contributes no output
   item, so the two lists can differ in length.
2. Such a loop contributes nothing at all, keeping `meta` aligned with
   `output`.

### Choice

Reading 1. Checkpoint 3 already emits one `meta` entry per attempt and only
keeps outputs that survive, so the lists were never required to match, and
`meta.finish_reason: "max_iterations"` is the only place a wasted loop is
visible.

### Risk: 35

A fixture that counts `meta` entries after a max-iterations loop separates
the readings; an implementation that appends metadata only alongside an
output would report fewer entries.

---

## T68: `result.passed` when a max-iterations row has no evaluation

### Spec Text

> "if `max_iterations` is hit, evaluation fails because output is `null`"
>
> "when evaluation is omitted for a single-solution agentic row, keep the
> part 1 rule: `result.passed` is `null`"

### Alternatives

1. `passed` is `null` whenever the task configures no evaluation, including
   a row that hit the iteration cap; `false` only when an evaluation exists
   and had nothing to judge.
2. `passed` is `false` for a max-iterations row regardless, because the row
   failed.

### Choice

Reading 1. The "evaluation fails" sentence is about what an evaluation does
with a `null` output; with no evaluation configured there is no verdict to
report, which is exactly the Part 1 rule the next bullet preserves.

### Risk: 25

Needs an agentic task with no `evaluation` that also hits its cap. The row
counts as failed in the summary either way, since it produced no output.

---

## T69: Temperature validation for the agentic scheme

### Spec Text

> "generation: scheme: "agentic" / max_iterations: 10 / temperature: 0.0"

### Alternatives

1. `agentic` accepts any temperature, including the `0.0` the example uses,
   and passes it through unchanged.
2. `agentic` is forced to `0.0` like `greedy`.
3. `agentic` requires a positive temperature like `sample`.

### Choice

Reading 1. The example configures `0.0` explicitly, which rules out the
`sample` rule; nothing suggests a tool loop must decode greedily, so a
configured temperature is sent as written.

### Risk: 10

Readings 1 and 2 differ only for an agentic task configuring a positive
temperature, and reading 3 is excluded by the example itself.

---

## T70: Whether an agentic task must declare tools

### Spec Text

> "Agentic tasks let the model call tools in a loop before producing a final
> answer."

### Alternatives

1. `tools` is optional; an agentic task without tools simply answers on its
   first iteration.
2. `tools` is required, by analogy with `evaluation` being required for the
   rejection scheme.

### Choice

Reading 1. The spec states no requirement, and the loop is well defined
without tools - step 4 fires immediately. Rejection's requirement is spelled
out in its own checkpoint; this one is not.

### Risk: 15

Only an agentic config with no `tools` key separates the readings.

---

## T71: Which ICL setup an agentic loop uses

### Spec Text

> "`agentic` also works with ICL and `num_solutions`; each solution is an
> independent loop"
>
> "for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
> strategy and instead walks setups in declared order" (Part 3)

### Alternatives

1. Agentic follows the configured `icl.strategy`, like `sample` and
   `rejection` do.
2. Agentic walks the setups in declared order, like `greedy`, because an
   agentic task also tends to decode at temperature 0.

### Choice

Reading 1. The declared-order override is written for `greedy` by name;
agentic runs vary by tool results as well as by setup, so repeated loops are
not guaranteed to be identical the way greedy re-decodes are.

### Risk: 25

Needs an agentic task with several setups and `num_solutions > 1`. If the
author keys the override on "temperature 0" rather than on the scheme name,
the setups would be walked in order instead.

---

## T72: The shape of a tool result message in a chat conversation

### Spec Text

> "append the assistant tool-call message and the tool result messages to
> the conversation"

### Alternatives

1. The OpenAI shape: `{"role": "tool", "tool_call_id": <id>, "content":
   <result>}`, with the assistant message appended exactly as received.
2. The same, plus a `name` field naming the tool.
3. A user message carrying the result.

### Choice

Reading 1. The spec ties the chat side to "the normal OpenAI shape", where
`tool_call_id` is the required link back to the call and `name` is a
deprecated leftover.

### Risk: 15

Only a fixture that inspects the follow-up request's message objects can
tell, and `content` is the field it would most likely read.

---

## T73: A loop whose request never comes back

### Spec Text

> "If a request receives an HTTP `5xx`, retry it up to 3 times. After the
> third failure, treat that row as failed, emit `null` output for it" (Part 1)
>
> "`meta.finish_reason` is `"stop"` ... and `"max_iterations"` when the
> iteration limit is hit"

### Alternatives

1. The loop stops with `output: null` and `finish_reason: "error"`, which is
   neither of the two documented values because neither applies.
2. Report `"max_iterations"`, reusing the only failure value named.
3. Report `null`.

### Choice

Reading 1. Part 1's rule already says an exhausted retry budget fails the
row with a `null` output; calling that `"max_iterations"` would misreport
why the loop ended when the budget was never reached.

### Risk: 30

Needs a 5xx fixture on an agentic task. The author may well reuse
`"max_iterations"` or leave the last response's reason in place.

---

## T74: Tool arguments that are not valid JSON

### Spec Text

> "parse `function.arguments` as JSON before invoking the handler"

### Alternatives

1. Treat unparseable arguments as an empty argument object, so the handler
   still runs and returns its default.
2. Let the parse error fail the row.
3. Let it fail the whole run.

### Choice

Reading 1. A malformed argument string is a model mistake like any other, and
the loop's way of reporting those to the model is a tool result; one bad
response should not take the row, or the run, down with it.

### Risk: 20

Needs a fixture with deliberately broken `arguments`. Any of the three is
defensible, but a crash is the least likely intended behaviour.

---

## T75: Which fields a completions request carries

### Spec Text

> "completions requests send `prompt`, `temperature`, `max_tokens`, and
> `model`"
>
> "tool definitions are rendered into the prompt instead of being sent as a
> native `tools` field"

### Alternatives

1. Exactly those four fields, in every mode including agentic.
2. The four fields plus a `stop` list derived from the template's markers.

### Choice

Reading 1. The spec lists the fields and the request example shows exactly
those four; a `stop` list would be an invention, and the tool sentence
confirms nothing else rides along in agentic mode.

### Risk: 15

A fixture comparing the payload's key set would catch an extra field; one
reading individual fields would not.

---

## T76: Summary token totals for agentic rows

### Spec Text

> "each API request inside the loop counts separately toward request totals"
>
> "`total_prompt_tokens`, `total_completion_tokens`, `total_api_calls`" (the
> Part 1 summary)

### Alternatives

1. The summary sums every iteration of every loop, so an agentic run's
   totals match the sum of its rows' `meta.total_*` values.
2. Only the final iteration of each loop counts.

### Choice

Reading 1. The request totals are explicitly per-request, and a summary that
under-counted the tokens a tool loop actually spent would be misleading.

### Risk: 20

Needs a fixture comparing summary tokens against a scripted multi-iteration
run.

---

## T77: A timeout for the `script` handler

### Spec Text

> "on timeout or non-zero exit, return `"ERROR: <stderr or timeout
> message>"`"

### Alternatives

1. A fixed timeout, matching the ten seconds the `script` evaluation type
   already uses, with an optional `timeout` key on the handler to override
   it.
2. A fixed timeout with no way to configure it.

### Choice

Reading 1. The spec requires a timeout but names no duration; reusing the
existing script timeout keeps one number in the tool, and accepting an
explicit `timeout` costs nothing and makes the behaviour testable.

### Risk: 15

The extra key is additive: a config that never sets it behaves identically.
Only the default duration could differ, and only for a fixture that sleeps.

---

## T78: Comma-grouped numbers in `last_number` and `first_number`

### Spec Text

> "input": {"question": "What is the total revenue for Q1 and Q2?",
> "answer": "2730000"}, "output": {"answer": "The total revenue for Q1 and
> Q2 is $2,730,000."}, "result": {"passed": true, "extracted_answer":
> "2730000", ...}
>
> "`last_number`: use the last integer or decimal in the response" (Part 1)

### Alternatives

1. The number grammar includes thousands separators, and the extracted value
   is reported with them removed - so `$2,730,000.` yields `"2730000"`.
2. The grammar is plain digits, so the same text yields `"000"`, and the
   example's `extracted_answer` is an idealisation.

### Choice

Reading 1, which changes Part 1's extractor. The worked example is the only
place the spec shows `last_number` running on a formatted figure, and it
reports both the extraction and the pass; under reading 2 that row would
extract `"000"` and fail, so the example would be wrong about two of its own
fields. See the Part 4 update on [T8].

### Risk: 25

This alters behaviour the earlier checkpoints also test. If the author's
extractor is plain digits and their example was written by hand, a Part 1
fixture over a comma-formatted answer would expect `"000"`.

---

## T79: How many loops an agentic row starts

### Spec Text

> "`agentic` also works with ICL and `num_solutions`; each solution is an
> independent loop"
>
> "`result.attempts` is the number of loops started for the row"
>
> "if `num_solutions: 2` and both loops produce a final answer ...
> `result.attempts` is `2`"

### Alternatives

1. Exactly `num_solutions` loops, like the `sample` scheme's attempt budget:
   a loop that produces no output is not retried.
2. Loops continue until `num_solutions` outputs are collected, within some
   larger budget, the way rejection retries.

### Choice

Reading 1. The worked example equates attempts with `num_solutions`, and
`result.failed` counting "loops that produced no output" only makes sense if
a failed loop consumes its share of the budget rather than being retried.

### Risk: 15

Differs only when a loop fails in a `num_solutions > 1` run: reading 2 would
report more attempts and possibly more outputs.

---

## T80: Whether non-agentic chat requests carry tool definitions

### Spec Text

> "Send an API request. In chat mode, include the task's tool definitions in
> the request body." (step 2 of the agentic loop)

### Alternatives

1. Only the agentic loop sends `tools`; a task with another scheme that
   happens to declare tools sends none, and neither does a judge call.
2. Any task that declares tools sends them on every chat request.

### Choice

Reading 1. The instruction sits inside the agentic loop's numbered steps,
and tools are meaningless to a scheme that has no way to execute a tool call
or to a judge that is scoring finished text.

### Risk: 15

Needs a non-agentic task declaring `tools`, or an agentic task with an
`llm_judge` evaluation whose judge request is inspected.
