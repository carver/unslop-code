# Ambiguities

Spec-reading decisions taken while implementing `rejector.py`.
Entries T1-T18 come from Part 1, T19-T34 from Part 2, and T35 onwards from
Part 3.
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
