# Ambiguities

Numbered record of places where the spec admits more than one conforming
implementation, the reading chosen here, and the risk that the spec author's
own implementation reads it differently.

## T1: `rpm` as capacity target vs. client-side rate limit

### Spec Text
> "The API server queues requests internally and spends time processing each
> request. It does not return rate-limit errors." ...
> "Use the configured `rpm` as the server's approximate request capacity and
> keep enough work in flight to avoid an obviously sequential pipeline. Target
> at least 80% of the configured `rpm`."

### Alternatives
1. `rpm` is a client-side throttle: pace outgoing requests so no more than
   `rpm` requests are issued per minute.
2. `rpm` describes the *server's* capacity, so the client just keeps enough
   requests in flight to saturate it and never throttles.

### Choice
Interpretation 2. The spec explicitly says the server does not return
rate-limit errors and frames `rpm` as "the server's approximate request
capacity"; a client-side throttle set exactly at capacity would make the 80%
target hard to hit whenever any request is slow. Concurrency is sized at
`clamp(rpm, 1, 256)` in-flight requests, which saturates a server of that
capacity for any per-request latency up to a minute.

### Risk: 20
Author most likely alternative: a token-bucket pacer at `rpm` combined with
concurrency, which would still pass a "throughput >= 0.8 * rpm" check.

## T2: `meta` for a row with no successful API response

### Spec Text
> "After the third failure, treat that row as failed, emit `null` output for
> it, count it as failed in the summary, and continue." ...
> "`meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt"

### Alternatives
1. `meta` is `null` when no call produced a response.
2. `meta` is a metadata object whose token/latency fields are zero or `null`.
3. `meta` is an empty list.

### Choice
Interpretation 1. Metadata is described as per-response data ("`latency_ms`
is wall-clock latency for that API call"); with no response there is nothing
to report, and `null` mirrors the `output: null` convention used for the same
failure. Rejection rows keep one metadata entry per attempt that produced a
response, so a row whose only attempts all 5xx'd out also yields `null`.

### Risk: 35
Author most likely alternative: an empty list for failed rejection rows and a
zero-filled object for failed greedy rows.

## T3: `result.passed` for an API-failed row when evaluation is configured

### Spec Text
> "`result.passed` is `true` for a passing evaluation, `false` for a failing
> evaluation, and `null` when no evaluation is configured"
> "`failed`: rows where `result.passed` is `false` or `output` is `null`"

### Alternatives
1. `false` — the row did not pass, matching the exhausted-rejection example
   which pairs `output: null` with `passed: false`.
2. `null` — no evaluation actually ran, so there is no verdict.

### Choice
Interpretation 1 when an `evaluation` block is configured, and `null` when it
is not (the "no evaluation configured" clause is unconditional). The
exhausted-rejection example in the spec shows `output: null` with
`passed: false`, so a failed greedy row is treated the same way.

### Risk: 25
Author most likely alternative: `null` for every row where no evaluation
could be run, relying on the `output is null` clause to mark it failed.

## T4: `extracted_answer` for `contains` and `regex` evaluations

### Spec Text
> "`contains`: response text must contain the `answer_field` value as a
> substring" / "`regex`: response text must match the configured `pattern`"
> "`result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output"

### Alternatives
1. Always apply the configured `extract` method (defaulting to `full`) and
   report its result, regardless of evaluation type.
2. Report `null` for `contains`/`regex`, since neither compares against an
   extracted value.
3. For `regex`, report the matched text (group 1 if the pattern has a group,
   else group 0).

### Choice
Interpretation 1. `extract` is configured on the `evaluation` block without
being restricted to `exact_match`, and a single "extract, then evaluate"
pipeline is the simplest implementation consistent with every stated rule.
The substring and pattern checks themselves still run against the full
response text as the spec requires.

### Risk: 35
Author most likely alternative: the regex match text for `regex`, which is
the intuitive "extracted answer" for a pattern evaluation.

## T5: comparison semantics for `exact_match`

### Spec Text
> "`exact_match`: extract an answer from the response and compare it to the
> configured `answer_field` from the input row"

### Alternatives
1. Exact string comparison of the two values after stripping surrounding
   whitespace (`answer_field` value stringified if not already a string).
2. Numeric-aware comparison so `"8"` matches `8.0` or `"8.00"`.
3. Byte-exact comparison with no stripping at all.

### Choice
Interpretation 1. "exact_match" names exact comparison, and the extractors
already return trimmed tokens; stringifying the row value keeps configs that
store answers as JSON numbers working, which the example
`{"answer": "8"}` / extracted `"8"` does not settle either way.

### Risk: 30
Author most likely alternative: numeric normalization for `last_number`
extraction, so `8` and `8.0` compare equal.

## T6: what counts as "the last integer or decimal"

### Spec Text
> "`last_number`: use the last integer or decimal in the response"

### Alternatives
1. `-?\d+(?:\.\d+)?` — optional sign, no thousands separators.
2. Digits only, sign dropped.
3. Comma-aware (`1,200` -> `1200`), as GSM8K answers often contain commas.

### Choice
Interpretation 1. It is the direct reading of "integer or decimal", keeps a
negative result negative, and avoids inventing separator normalization the
spec never mentions. A trailing sentence period is not consumed because the
fractional part requires digits after the dot.

### Risk: 30
Author most likely alternative: comma stripping so that `#### 1,200` extracts
`1200`.

## T7: whether rejection attempts may be issued in parallel

### Spec Text
> "`rejection`: `temperature` must be `> 0`; make up to `n` attempts and keep
> the first passing response"

### Alternatives
1. Attempts are sequential within a row: attempt `k+1` is only issued after
   attempt `k` fails evaluation.
2. All `n` attempts are issued speculatively in parallel and the first passing
   one is kept.

### Choice
Interpretation 1. "up to `n` attempts" and `attempts: 1..n` only make sense if
later attempts can be skipped, and speculative firing would inflate
`total_api_calls` and the `meta` list. Rows still run concurrently with each
other, so throughput is unaffected.

### Risk: 10
Author most likely alternative: none plausible; parallel speculation would
contradict the `attempts` accounting.

## T8: when missing prompt fields are detected

### Spec Text
> "If a placeholder references a missing field, exit with code `1` and print an
> error to stderr naming the row index and missing field."

### Alternatives
1. Pre-flight: validate every row before issuing any request, so the run
   aborts before touching the API.
2. Lazily: fail when the offending row is rendered, after earlier rows have
   already been sent (and possibly written).

### Choice
Interpretation 1. The Input section states as a precondition that "Every row
must contain all fields referenced by the prompt templates", which reads as a
whole-file precondition; pre-flight also makes the exit deterministic under
concurrency. The first offending row (lowest index) is the one reported.

### Risk: 15
Author most likely alternative: lazy detection, which only differs
observably in whether the output file is written and how many API calls
happen before exit.

## T9: a row missing the configured `answer_field`

### Spec Text
> "When the configured evaluation uses `answer_field`, each row must also
> contain that field."

### Alternatives
1. Input error: exit `1` with a message naming the row index and field, same
   as a missing prompt placeholder.
2. Row-level failure: evaluate as not passing and continue.

### Choice
Interpretation 1. It is stated as a hard requirement on the input in the same
paragraph as the prompt-field requirement, and "input error" is exactly what
exit code `1` covers.

### Risk: 30
Author most likely alternative: treating the missing answer as a failed
evaluation for that row and continuing the run.

## T10: defaults for omitted configuration keys

### Spec Text
> "`greedy`: force `temperature` to `0.0`; `n` is ignored" /
> "`sample`: `temperature` must be `> 0`" / config shape listing `rpm`,
> `max_tokens`, `n`, `extract`

### Alternatives
1. Every key in the config shape is mandatory.
2. Only the keys with no sensible default are mandatory
   (`api_url`, `model`, `prompt.user`, `output_field`), with
   `rpm: 60`, `max_tokens: 512`, `n: 1`, `extract: "full"`,
   `scheme: "greedy"` filled in, and a missing `temperature` treated as
   `0.0` (therefore an error for `sample`/`rejection`).

### Choice
Interpretation 2. The spec only ever names four validation failures
(missing `evaluation` for rejection, missing `answer_field`, missing
`pattern`, non-positive temperature for sampling schemes), so inventing extra
required keys would reject configs the spec never forbids. A missing
temperature under `sample`/`rejection` still fails the explicit
"must be `> 0`" rule rather than silently defaulting to `1.0`.

### Risk: 25
Author most likely alternative: defaulting a missing `temperature` to `1.0`
for `sample`/`rejection` instead of erroring.

## T11: `{field}` placeholder rendering

### Spec Text
> "`prompt.system` and `prompt.user` use `{field}` placeholders resolved from
> each input row."

### Alternatives
1. `str.format(**row)`, which also unescapes `{{`/`}}` and supports
   `{a.b}` / `{a[0]}` / format specs, and raises on any stray brace.
2. Regex substitution of `{identifier}` only, leaving every other brace
   literal.

### Choice
Interpretation 2. Prompts routinely contain literal braces (JSON examples,
LaTeX), and only the plain `{field}` form is documented; a regex substitution
never fails on unrelated braces while behaving identically on documented
inputs. Non-string row values are stringified with `str()`.

### Risk: 15
Author most likely alternative: `str.format`, which differs only on prompts
containing braces that are not simple field names.

## T12: `regex` evaluation match semantics

### Spec Text
> "`regex`: response text must match the configured `pattern`"

### Alternatives
1. `re.search` — the pattern must occur somewhere in the response.
2. `re.fullmatch` — the pattern must cover the entire response.
3. `re.match` — anchored at the start only.

### Choice
Interpretation 1. Evaluating a generated answer usually means looking for a
pattern inside free-form text (e.g. `####\s*\d+`), and `search` is the
behaviour a pattern author gets by default; anchoring remains available via
`^...$` in the pattern itself.

### Risk: 25
Author most likely alternative: `re.match`, which behaves identically for
patterns anchored at the start of the response.

## T13: `meta` shape for a rejection row with a single attempt

### Spec Text
> "`meta` is a single metadata object for one-attempt rows; for rejection
> sampling with multiple attempts it is a list with one metadata object per
> attempt"

### Alternatives
1. Shape follows the attempt count: one attempt -> object, even under
   `rejection`.
2. Shape follows the scheme: `rejection` always emits a list.

### Choice
Interpretation 1, which is the literal reading — "one-attempt rows" is a
statement about attempts, not about scheme, and the list is introduced only
"for rejection sampling with multiple attempts".

### Risk: 30
Author most likely alternative: always a list under `rejection`, since that
keeps the output schema stable per run.

## T14: exit code for CLI usage errors

### Spec Text
> "Exit codes: `0`: success, `1`: configuration or input error"

### Alternatives
1. Usage errors (missing `--config`, unknown subcommand) also exit `1`, since
   the spec names no other failure code.
2. argparse's default `2` for usage errors.

### Choice
Interpretation 1. The spec enumerates the tool's exit codes exhaustively and
a missing/unreadable flag is a configuration error in spirit.

### Risk: 20
Author most likely alternative: plain argparse, leaving usage errors at `2`.

## T15: non-5xx HTTP failures and transport errors

### Spec Text
> "If a request receives an HTTP `5xx`, retry it up to 3 total requests. After
> the third failure, treat that row as failed..."

### Alternatives
1. Only 5xx is retried; a 4xx or a malformed body fails the row immediately;
   connection errors and timeouts are retried like 5xx.
2. Everything that is not a 200 is retried.
3. A 4xx aborts the whole run with exit `1`.

### Choice
Interpretation 1. The retry rule is scoped to 5xx, and a 4xx is a
non-transient request error that retrying cannot fix; transport errors are
transient in exactly the way 5xx is, so they share its retry budget. Every
HTTP attempt, retried or not, counts toward `total_api_calls`.

### Risk: 20
Author most likely alternative: retrying any non-200 response with the same
budget.

## T16: empty input file

### Spec Text
> "`total`: input row count" / "`elapsed_seconds`: wall-clock time from first
> request to last response"

### Alternatives
1. Zero rows is valid: write an empty output file, print a zeroed summary,
   exit `0`.
2. Zero rows is an input error, exit `1`.

### Choice
Interpretation 1. Nothing in the spec forbids an empty input, and a zeroed
summary is well defined. With no API calls, `elapsed_seconds` and
`throughput_rpm` are both `0.0`.

### Risk: 10
Author most likely alternative: same behaviour with a non-zero
`elapsed_seconds` measured over the whole process.

## T17: `elapsed_seconds` window and rounding interaction

### Spec Text
> "`elapsed_seconds`: wall-clock time from first request to last response,
> rounded to 1 decimal place" / "`throughput_rpm`:
> `total_api_calls / elapsed_seconds * 60`, rounded to 1 decimal place"

### Alternatives
1. Throughput is computed from the unrounded elapsed time, then rounded.
2. Throughput is computed from the already-rounded `elapsed_seconds` so the
   two reported numbers are exactly consistent.

### Choice
Interpretation 1. Rounding is described as a presentation step on each field,
and computing from the raw duration is more accurate; the two agree to within
rounding for any run long enough to matter.

### Risk: 15
Author most likely alternative: dividing by the rounded value, which differs
only on very short runs.

## T18: how deeply `defaults` and a task body merge

### Spec Text
> "`defaults` provides shared values; each task overrides `defaults`"
> "nested sections such as `prompt`, `generation`, and `evaluation` are merged
> per task using the Part 1 structure"

### Alternatives
1. Recursive merge at every depth: any mapping present in both is merged
   key-by-key, so `defaults.evaluation.extract` survives a task that only sets
   `evaluation.answer_field`, and the same applies inside `judge_prompt`.
2. Section-level merge only: the named top-level sections (`prompt`,
   `generation`, `evaluation`) merge one level deep, and anything nested
   inside them (e.g. `judge_prompt`) is replaced wholesale.
3. Whole-section replacement: a task that defines `generation` discards
   `defaults.generation` entirely.

### Choice
Interpretation 1. "merged per task" with no stated depth limit, and "such as"
marks the three sections as examples rather than an exhaustive list; a single
recursive merge is also the only rule that makes `required Part 1 fields must
still come from either `defaults` or the task` work uniformly for nested
required fields like `prompt.user`.

### Risk: 20
Author most likely alternative: a one-level merge of the three named sections,
which differs only for configs that split `judge_prompt` across `defaults` and
a task.

## T19: task name for a single-task config with no `task.name`

### Spec Text
> "if the config still uses a top-level `task` key, treat it as the Part 1
> single-task format; the task name is `task.name`"

### Alternatives
1. `task.name` stays optional (Part 1 never required it); the run keys the
   task internally by a placeholder when it is absent.
2. `task.name` becomes required in Part 2.

### Choice
Interpretation 1. Part 1 made `name` optional and this part says existing
behavior is unchanged unless stated; the name is only observable for
single-task configs through `--task`, and a single-task run writes one output
file and no `tasks` summary object, so the placeholder never reaches output.

### Risk: 10
Author most likely alternative: requiring `name` once `--task` is given.

## T20: sampling parameters for the judge call

### Spec Text
> "the judge request is a separate API call through the same server" /
> "if `evaluation.model` is omitted, use the task's model"

### Alternatives
1. Judge at `temperature: 0.0` with the task's `max_tokens`, since a judge
   should be deterministic and only the model is said to be configurable.
2. Judge with the task's `generation.temperature`, reusing the whole
   generation config.
3. A separate judge `generation` block (not in the spec).

### Choice
Interpretation 1. Only `model` is described as inherited, and the judge's job
("respond with only a single integer") is a deterministic classification;
sampling a judge at the task's rejection temperature would make the same
response pass or fail at random.

### Risk: 35
Author most likely alternative: reusing the task's `generation.temperature`
for the judge call, which is observable in the request body.

## T21: where `judge_meta` lives for a multi-attempt row

### Spec Text
> "`meta` includes a `judge_meta` object with the judge request's token usage,
> latency, model, and finish reason"
> (Part 1) "for rejection sampling with multiple attempts it is a list with one
> metadata object per attempt"

### Alternatives
1. Each attempt is judged, so each entry of the `meta` list carries its own
   `judge_meta`.
2. Only the kept attempt's judge call is recorded, as a single `judge_meta`
   alongside the list.
3. A parallel top-level list of judge metas.

### Choice
Interpretation 1. Rejection sampling has to judge every attempt to know
whether it passes, so each attempt genuinely has a judge call, and attaching
it to that attempt's metadata object keeps the documented one-entry-per-attempt
shape.

### Risk: 30
Author most likely alternative: a single `judge_meta` for the decisive judge
call only.

## T22: whether judge tokens count in the summary token totals

### Spec Text
> "judge calls count toward throughput, `total_api_calls`, and per-task API
> call totals, and may be interleaved with other work"

### Alternatives
1. Judge calls are API calls, so their usage also lands in
   `total_prompt_tokens` / `total_completion_tokens`.
2. The enumeration is exhaustive: judge tokens are reported only inside
   `meta.judge_meta` and excluded from the summary token totals.

### Choice
Interpretation 1. Part 1 defines the token totals as sums over the run's API
calls and this part does not restate them; the sentence quoted above reads as
listing the counters that could plausibly have been scoped per-task, not as
carving tokens out.

### Risk: 45
Author most likely alternative: excluding judge tokens, if their implementation
sums only the generation metadata it keeps per attempt.

## T23: how `letter` finds the answer choice

### Spec Text
> "`letter`: extract the first uppercase answer choice `A` through `D`; accept
> forms such as `A`, `(A)`, `A)`, or `Answer: A`"

### Alternatives
1. The first standalone uppercase `A`-`D` in the response: a letter with no
   adjacent letter or digit, so `(A)`, `A)`, `Answer: A` and a bare `A` all
   match while `Alpha` and `ANSWER` do not.
2. Enumerate the listed forms as explicit patterns and try them in order,
   preferring an `Answer: X` marker over an earlier stray letter.
3. Any `A`-`D` character, including one inside a word.

### Choice
Interpretation 1. "first uppercase answer choice" is positional, and a
boundary rule covers every listed form with one pattern; option 3 would pick
the `A` out of "A capital city" and option 2 invents a priority order the spec
never states.

### Risk: 30
Author most likely alternative: a marker-first search (`Answer:\s*([A-D])`
before a bare letter), which differs when prose mentions another choice before
the final answer.

## T24: `extracted_answer` for `script` evaluation

### Spec Text
> "`result.extracted_answer` is the extracted comparison value, or `null` when
> there is no evaluation or no output" (Part 1) with no `extract` mentioned for
> `script`.

### Alternatives
1. Apply the configured `extract` (default `full`) to the response like every
   other evaluation type, so `extracted_answer` is the response text.
2. Report `null`, because a script evaluation compares nothing.

### Choice
Interpretation 1, for the same reason as T4: one "extract, then evaluate"
pipeline for every type, with `extract` defaulting to `full`.

### Risk: 40
Author most likely alternative: `null` for `script` rows, since the script's
exit code is the only comparison made.

## T25: a judge reply that carries no usable score

### Spec Text
> "score `>= threshold` passes" / "`result.extracted_answer` is the text
> `extract` took from the judge's reply"

### Alternatives
1. No number in the reply (or a failed judge call) is a failed evaluation:
   `passed: false`, `judge_score: null`.
2. It is a run-level error.
3. The row is treated as unevaluated (`passed: null`).

### Choice
Interpretation 1. A missing score cannot be `>= threshold`, and Part 1 already
treats "no usable response" as a row failure rather than a run failure. Under
rejection sampling the row simply moves to its next attempt.

### Risk: 20
Author most likely alternative: the same verdict with `judge_score: 0`.

## T26: the second `__response__` substitution pass for scripts

### Spec Text
> "if a row field such as `{test_code}` expands to text that itself contains
> `{__response__}`, substitute `__response__` before executing the command"

### Alternatives
1. Two passes: one pass substitutes row fields and `__response__` in the
   template, then a second pass substitutes only `{__response__}` in the
   result.
2. Repeat until no placeholder remains (full recursive expansion of row
   fields too).
3. Pre-expand row fields inside row fields before rendering the template.

### Choice
Interpretation 1. The spec names exactly one level of nesting and only for
`__response__`; two passes also means a response containing `{question}` is
never re-expanded, which keeps generated text from reaching into the row. The
response text is substituted verbatim, with no shell quoting added, because
the example's `echo '{__response__}'` supplies its own quotes.

### Risk: 20
Author most likely alternative: a fixed-point loop, which differs only when a
row field expands to another row field placeholder.

## T27: which keys a per-task summary object carries

### Spec Text
> ```json
> "gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_api_calls": 142}
> ```

### Alternatives
1. Exactly the four keys shown.
2. The full top-level key set per task (token totals, elapsed, throughput).

### Choice
Interpretation 1. The example is the only definition given, and per-task
`elapsed_seconds` would be ill-defined for interleaved tasks.

### Risk: 15
Author most likely alternative: also including per-task token totals.

## T28: `--input` entries for tasks that are not running

### Spec Text
> "when `--task` is present, require input only for selected tasks and ignore
> unselected tasks for validation and execution"

### Alternatives
1. An `--input name=path` for a task that exists but is not selected is
   ignored; a name the config does not define at all is a configuration error.
2. Any unused mapping is an error.
3. Every unknown name is ignored silently.

### Choice
Interpretation 1. "ignore unselected tasks for validation" covers the first
case explicitly, while a name that matches no task in the config is a typo the
user wants reported — it is the same class of error as `--task nope`.

### Risk: 25
Author most likely alternative: ignoring unknown `--input` names too, since
the selected tasks are what drives the lookup.

## T29: `--eval-model` against tasks without an `llm_judge` evaluation

### Spec Text
> "`--eval-model <string>`: override the judge model for all selected
> `llm_judge` tasks"

### Alternatives
1. It only touches `llm_judge` evaluations; other selected tasks are
   unaffected and the flag is not an error when no task uses a judge.
2. It is an error when no selected task has an `llm_judge` evaluation.

### Choice
Interpretation 1. The flag is scoped to `llm_judge` tasks by its own wording,
and a mixed config where only some tasks judge is exactly the case the flag
exists for.

### Risk: 10
Author most likely alternative: none plausible.

## T30: what `--output` may already be for a multi-task run

### Spec Text
> "for multi-task configs, `--output` must be a directory" / "write
> `<output_dir>/<task_name>.jsonl`"

### Alternatives
1. Create the directory (with parents) when it does not exist, and fail with
   exit `1` when the path exists as a regular file.
2. Require the directory to exist already.
3. Silently overwrite a file of that name.

### Choice
Interpretation 1. `--output results/` in the examples reads as "put results
here" rather than a precondition on the filesystem, and a path that is already
a file cannot satisfy "must be a directory", which makes it a configuration
error.

### Risk: 20
Author most likely alternative: requiring the directory to exist, which only
differs on a first run into a fresh path.

## T31: the input mode rules for a single-task config

### Spec Text
> "for multi-task configs, explicit `--input <task=path>` and `--input-dir` are
> alternative modes; do not combine them" / "for single-task configs,
> `--input <path>` without `=` still behaves as in Part 1"

### Alternatives
1. A single-task config also accepts `--input <name>=<path>` when the name
   matches, and `--input-dir` resolving to `<name>.jsonl`; more than one
   `--input` is an error.
2. A single-task config accepts only a bare `--input <path>`, and anything
   else is a configuration error.

### Choice
Interpretation 1. The quoted rule guarantees the Part 1 form keeps working
without forbidding the new forms, and accepting them costs nothing while
keeping one code path for both config shapes. A `name=path` whose name does
not match the task is still an error.

### Risk: 15
Author most likely alternative: rejecting `--input-dir` for single-task
configs.

## T32: the default `icl.strategy`

### Spec Text
> "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"

### Alternatives
1. Default to `fixed` when `strategy` is omitted.
2. Default to `round_robin`, the value used in the spec's first example.
3. Require `strategy` whenever `icl` is present.

### Choice
Interpretation 1. Both file-backed and inline examples appear in the spec with
an explicit strategy, so no example settles it, but `fixed` is the reading that
makes an omitted strategy behave like a task with a single setup: one prompt
shape, used for every attempt. Requiring the key would make the `k`-only
config of the second example invalid, which the spec never says.

### Risk: 25
Author most likely alternative: `round_robin`, which only differs once a config
declares more than one setup and omits `strategy`.

## T33: `greedy` without ICL and `num_solutions > 1`

### Spec Text
> "`greedy` with ICL: generate at temperature `0` once per selected setup and
> stop when `num_solutions` solutions are collected or all setups are
> exhausted; because the same setup is deterministic, the maximum number of
> produced solutions is the number of available setups"

### Alternatives
1. Make one attempt and emit at most one solution, since without setups there
   is nothing to vary and the quoted rule forbids repeating a deterministic
   prompt.
2. Make `num_solutions` identical requests and emit that many copies.
3. Reject the combination as a configuration error.

### Choice
Interpretation 1. The spec only defines `greedy` for the ICL case, and its
stated reason — a deterministic prompt cannot yield a second distinct solution
— applies with even more force when there are no setups at all. "Do not retry
the same greedy setup to manufacture additional outputs" reads as a general
prohibition. The row still uses the list output format, because
`num_solutions > 1`.

### Risk: 35
Author most likely alternative: `num_solutions` identical requests, which a
loop written for `sample` would produce if `greedy` fell through to it.

## T34: whether the strategy cursor is per row or per run

### Spec Text
> "`round_robin`: cycle through setups in order across attempts" / "attempt 1
> uses `A`, attempt 2 uses `B`, attempt 3 uses `C`, attempt 4 uses `A`"

### Alternatives
1. Each input row starts at the first setup and cycles across its own
   attempts.
2. One cursor is shared by every row of the task, so the setup a row starts
   from depends on how many attempts earlier rows spent.

### Choice
Interpretation 1. Rows are processed concurrently, so a shared cursor would
make the setup of a given attempt depend on scheduling and would not be
reproducible; "attempt 1 uses A" is stated without reference to which row, so
it must hold for every row.

### Risk: 20
Author most likely alternative: a task-wide cursor, which differs from this
choice for every row after the first.

## T35: which keys `result` carries in the list format

### Spec Text
> ```json
> "result": {"passed": 2, "failed": 5, "attempts": 7}
> ```
> "`result.passed` is the count of passing solutions"

### Alternatives
1. Exactly the three keys shown: `passed`, `failed`, `attempts`. Part 1's
   `extracted_answer` (and Part 2's `judge_score`) are dropped, because a row
   with several solutions has no single extracted answer.
2. Keep `extracted_answer` as well, holding the first or last solution's value.
3. Move `extracted_answer` into each `output` item.

### Choice
Interpretation 1. The example prints the whole `result` object, not an excerpt,
and the output items are described as "the task's `output_field` plus
`icl_setup`" — an exhaustive list that leaves no room for a per-solution
extracted answer either.

### Risk: 30
Author most likely alternative: keeping `extracted_answer` in `result` for
compatibility with their Part 1 record builder.

## T36: how per-task summary fields "gain" the new keys

### Spec Text
> "Per-task summary fields gain:"
> ```json
> {"tasks": {"gsm8k": {"total": 100, "total_solutions": 450,
>  "avg_solutions_per_input": 4.5, "total_api_calls": 850}}}
> ```

### Alternatives
1. Add `total_solutions` and `avg_solutions_per_input` to the Part 2 per-task
   object, which keeps `total`, `passed`, `failed` and `total_api_calls`, and
   do it for every run rather than only multi-solution ones.
2. Replace the per-task object with exactly the four keys shown, dropping
   `passed` and `failed`.
3. Add the two keys only when the task ran in the list format.

### Choice
Interpretation 1. "Gain" is addition, and the quoted block omits `passed` and
`failed` the same way it omits the top-level summary keys around it. Emitting
the new fields unconditionally keeps one summary shape: a Part 1 style task
simply reports one solution per answered row. The top-level summary is left
alone, since the spec attaches the new fields to per-task fields only.

### Risk: 25
Author most likely alternative: adding the fields only for multi-solution
tasks, which differs on every single-solution run's `tasks` object.

## T37: what counts as a solution in `total_solutions`

### Spec Text
> "total_solutions": 450, "avg_solutions_per_input": 4.5

### Alternatives
1. Count the solutions actually written to `output`, whatever the evaluation
   said about them.
2. Count only solutions whose evaluation passed.

### Choice
Interpretation 1. `avg_solutions_per_input` is described as solutions per
input, and the solutions an input has are the ones in its `output` list;
`result.passed` already reports the passing subset. For `rejection` the two
readings coincide, because only passing attempts are kept.

### Risk: 20
Author most likely alternative: counting passing solutions, which differs for
`sample` rows whose solutions fail evaluation.

## T38: metadata for an attempt that got no response

### Spec Text
> "`meta` is a list with one entry per attempt" / "`result.failed` is the
> number of attempts that produced no output"

### Alternatives
1. Emit metadata only for attempts that came back with a response, so an
   attempt whose requests all failed adds to `result.attempts` but not to
   `meta`.
2. Emit a placeholder entry with null token counts and `finish_reason` for
   such attempts.

### Choice
Interpretation 1. Part 1 already writes `meta: null` for a row whose only
attempt failed (T2), so there is no established shape for a metadata entry
without a completed call; inventing one here would contradict that. The
attempt is still visible in `result.attempts` and `result.failed`.

### Risk: 35
Author most likely alternative: one placeholder entry per failed attempt, so
that `len(meta) == result.attempts` always holds.

## T39: whether a failed evaluation withholds a non-rejection solution

### Spec Text
> "`sample` with ICL: make one sampled generation per requested solution using
> the chosen ICL strategy; evaluation does not gate whether a solution is
> included"

### Alternatives
1. Only `rejection` gates on evaluation; `greedy` and `sample` — with or
   without ICL — emit every response they receive, and a response that fails
   evaluation is emitted while counting toward `result.failed`.
2. Read the quoted sentence as specific to `sample` with ICL, and have the
   other non-rejection combinations drop failing responses.

### Choice
Interpretation 1. Part 1 already keeps a greedy or sampled response whatever
the evaluation says, and the quoted sentence restates that rule rather than
introducing one; `rejection` is the scheme the spec defines in terms of
collecting *passing* solutions.

### Risk: 15
Author most likely alternative: gating `sample` without ICL, which is the one
combination the sentence does not name.

## T40: `k` larger than the selected setup

### Spec Text
> "`icl.k` defaults to all examples in the selected setup" / "if `k` is smaller
> than the number of examples in the setup, use the first `k`"

### Alternatives
1. Send every example the setup has.
2. Treat it as a configuration error.

### Choice
Interpretation 1. The spec only constrains the `k`-smaller case and describes
`k` as a cap on demonstrations; with setups of different sizes behind one
`icl.k`, erroring would make mixed-size setups unusable.

### Risk: 10
Author most likely alternative: a configuration error, which differs only for
configs whose `k` exceeds a setup's example count.

## T41: an ICL example that the user template cannot render

### Spec Text
> "each example's `input` is rendered with the task's `prompt.user` template"

### Alternatives
1. Check every example against the template's placeholders at startup and exit
   1, as Part 1 does for input rows missing a field.
2. Render the placeholder away as an empty string or leave it literal.
3. Fail at request time, once the row is being generated.

### Choice
Interpretation 1. Part 1 already refuses to start when a row cannot fill the
template, and an example file is configuration, so the same failure at the
same time is the consistent reading; it also keeps the "before any API
requests are sent" guarantee that the neighbouring file rules demand.

### Risk: 25
Author most likely alternative: a run-time failure of just that row, leaving
other rows to run.

## T42: `--icl-strategy` and `--icl-k` without an `icl` block

### Spec Text
> "New flags: ... `--icl-strategy <fixed|random|round_robin>` / `--icl-k
> <int>`" / "CLI flags override config values"

### Alternatives
1. Ignore them for tasks that configure no ICL; they override values that do
   not exist.
2. Reject the run with exit 1.

### Choice
Interpretation 1. The flags are described as overrides of `icl.strategy` and
`icl.k`, and in a multi-task run only some tasks may configure ICL, so failing
the whole run would make the flags unusable exactly where they are most
convenient.

### Risk: 15
Author most likely alternative: an error, which differs only for runs that
pass an ICL flag to a task without ICL.

## T43: `generation.n` once a row is no longer a legacy row

### Spec Text
> "legacy compatibility: when `num_solutions == 1` and no ICL is configured,
> keep the Part 1 rejection behavior (`generation.n` logical attempts) and do
> not apply `max_attempts`"

### Alternatives
1. Outside the legacy case, `max_attempts` alone bounds rejection and `n` is
   ignored, even when both are configured.
2. Bound rejection by `min(n, max_attempts)`.

### Choice
Interpretation 1. The rule is stated as a swap: the legacy row uses `n` and
not `max_attempts`, so the new row uses `max_attempts` and not `n`. The
spec's own example config carries both `n: 5` and `max_attempts: 15` under
`num_solutions: 5`, which only makes sense if `n` is inert there.

### Risk: 15
Author most likely alternative: letting `n` cap attempts as well, which
differs for configs that set both.

## T44: a row in the list format that collects nothing

### Spec Text
> "write only those two passing outputs" / "`output` becomes a list of
> objects"

### Alternatives
1. Write an empty list, since `output` is a list in this format.
2. Write `null`, as Part 1 does for a row with no usable response.

### Choice
Interpretation 1. The format rule has no exception for the empty case, and a
reader of the file can treat `output` as a list for every row of a
multi-solution run; `result.passed: 0` already says nothing was collected.

### Risk: 20
Author most likely alternative: `null`, carried over from the Part 1 failed-row
shape.

## T45: whether a greedy ICL row follows the strategy when `num_solutions == 1`

### Spec Text
> "for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
> strategy and instead walks setups in declared order, at most once per setup"

### Alternatives
1. Take the condition literally: with `num_solutions == 1`, greedy follows the
   configured strategy, so `random` may pick any setup for the single attempt.
2. Always walk in declared order for greedy, making the single attempt use the
   first setup.

### Choice
Interpretation 1. The rule names `num_solutions > 1` explicitly, and for one
attempt the two readings differ only under `random` — where the whole point of
the strategy is to vary the setup.

### Risk: 10
Author most likely alternative: always using the first setup for greedy, which
differs only for a `random` single-solution greedy run.

## T46: rounding of `avg_solutions_per_input`

### Spec Text
> "avg_solutions_per_input": 4.5

### Alternatives
1. Round to two decimals, matching the rounding the summary already applies to
   `elapsed_seconds` and `throughput_rpm`.
2. Emit the full float.

### Choice
Interpretation 1. The example value is exact either way; two decimals keeps the
summary's existing habit of printing short numbers and avoids
`4.333333333333333` in a human-read report. A task with no rows reports `0.0`.

### Risk: 25
Author most likely alternative: the unrounded quotient, which differs whenever
solutions do not divide evenly by rows.

## T47: where each built-in template's trailing generation cue ends

### Spec Text
> `chatml`
> ```text
> <|im_start|>system
> {system_content}<|im_end|>
> <|im_start|>user
> {user_content}<|im_end|>
> <|im_start|>assistant
> ```
> ... `mistral`
> ```text
> [INST] {system_content}
>
> {user_content} [/INST]
> ```

### Alternatives
1. Each fenced block is the template verbatim including the newline that
   closes the last line, so `chatml` ends `...assistant\n`, `llama3` ends
   `...<|end_header_id|>\n`, and `mistral` ends `[/INST]\n`.
2. Each template ends the way the real chat format does: `chatml`
   `...assistant\n`, `llama3` `...<|end_header_id|>\n\n` (matching the blank
   line the block already puts after every other header), `mistral`
   `[/INST]` with no trailing newline, `zephyr` `<|assistant|>\n`.

### Choice
Interpretation 2. The `llama3` block writes a blank line after every
`<|end_header_id|>` it shows content for, so the generation cue plausibly
carries the same `\n\n`; and `mistral`'s block is a single line whose content
never starts on a new line, which makes a trailing newline after `[/INST]`
an artifact of the fence rather than part of the format. The two marker
templates that agree under either reading (`chatml`, `zephyr`) end with one
newline in both.

### Risk: 35
Author most likely alternative: the fenced blocks copied verbatim, giving
`llama3` a single trailing newline and `mistral` a trailing newline too.

## T48: how a tool result turn is rendered by each built-in template

### Spec Text
> "execute those calls and feed the results back into the next prompt
> iteration using the template's tool-role formatting"

### Alternatives
1. Render the tool turn with the message's own role name, so the marker
   templates emit `<|im_start|>tool`, `<|start_header_id|>tool<|end_header_id|>`
   and `<|tool|>`, with the handler's raw result as the content.
2. Use each model family's real tool role — llama3's `ipython`, Mistral's
   `[TOOL_RESULTS] ... [/TOOL_RESULTS]` — and wrap the content in a
   `<tool_response>` block mirroring `<tool_call>`.
3. Feed results back as an ordinary user turn, since only `<tool_call>` is
   specified.

### Choice
Interpretation 1. The spec names the marker templates by their role slots and
says to use "the template's tool-role formatting", which is what formatting a
`tool`-role message through the same per-message marker yields; it also keeps
the three marker templates uniform. `mistral` has no role markers at all, so
its tool results join the `[INST]` block alongside the user turns.

### Risk: 45
Author most likely alternative: the same `tool` role marker, but the content
wrapped in a `<tool_response>` block to pair with `<tool_call>`.

## T49: how tool definitions are rendered into a completions prompt

### Spec Text
> "tool definitions are rendered into the prompt instead of being sent as a
> native `tools` field"

### Alternatives
1. Append a tool section to the system turn: each tool's `{name, description,
   parameters}` as JSON, plus instructions describing the `<tool_call>` reply
   format.
2. Emit the definitions as a separate leading turn of their own.
3. Send the OpenAI `tools` array verbatim as JSON with no instructions.

### Choice
Interpretation 1. The system turn is where instructions live, and the model
cannot produce the `<tool_call>` blocks the spec says to parse unless the
prompt tells it that format; serialising the same `{name, description,
parameters}` object the chat endpoint receives keeps one definition for both
modes. A task with no system prompt gets one carrying just this block.

### Risk: 55
Author most likely alternative: the same content under a distinct
`<tools>...</tools>` section rather than folded into the system turn. The
exact wording is unspecified either way, so only tests that assert on tool
names and the `<tool_call>` format can be portable.

## T50: `last_number` over the grouped number in the agentic output example

### Spec Text
> ```json
> "output": {"answer": "The total revenue for Q1 and Q2 is $2,730,000."},
> "result": {"passed": true, "extracted_answer": "2730000", ...}
> ```
> with `extract: "last_number"` — and "Existing behavior from earlier parts is
> unchanged unless stated here."

### Alternatives
1. Part 1's `last_number` is unchanged, so `"$2,730,000."` yields `"000"` and
   the row fails; the example's `extracted_answer` is illustrative.
2. `last_number` strips thousands separators, so the example is literally
   reproducible and the row passes.

### Choice
Interpretation 1. This checkpoint states no change to extraction and opens by
saying earlier behavior is unchanged, and the surrounding example is visibly
hand-written (round token counts of 200/350/300 and latencies of
300/400/500ms), so its `extracted_answer` is prose rather than a run of the
author's implementation. Changing `last_number` would also silently alter
every earlier checkpoint's extraction.

### Risk: 40
Author most likely alternative: a number regex that accepts `\d{1,3}(,\d{3})*`
and strips the commas, making the documented example exact.

## T51: the default `chat_template` when none is configured

### Spec Text
> ```yaml
> defaults:
>   api_type: "completions"
>   chat_template: "llama3"
> ```

### Alternatives
1. `chat_template` defaults to one of the four built-ins — `chatml`, the most
   generic of them.
2. `chat_template` is required whenever `api_type` is `completions`.

### Choice
Interpretation 1. Every other optional key in the config has a documented
default rather than a conditional requirement, and `chatml` is the neutral
family-agnostic format; a run that forgets the key still produces a valid
prompt instead of an error.

### Risk: 20
Author most likely alternative: the same default. A hard requirement would
turn a plausible config into an exit-1, which no other key in the spec does.

## T52: the default `max_iterations`

### Spec Text
> ```yaml
> generation:
>   scheme: "agentic"
>   max_iterations: 10
> ```

### Alternatives
1. `max_iterations` defaults to `10`, the value the only example uses.
2. `max_iterations` is required for `agentic` tasks.
3. Some other default, such as `5`.

### Choice
Interpretation 1. The single worked example uses `10`, and an unbounded loop
is not an option given rule 5; taking the documented value as the default is
the reading that makes an omitted key behave like the spec's own task.

### Risk: 25
Author most likely alternative: requiring the key for `agentic` tasks, which
would exit 1 where this implementation runs with a bound of 10.

## T53: `temperature: 0.0` under the `agentic` scheme

### Spec Text
> ```yaml
> generation:
>   scheme: "agentic"
>   temperature: 0.0
> ```
> Part 1: "`temperature` must be > 0 for `sample` and `rejection`."

### Alternatives
1. `agentic` places no constraint on temperature, so `0.0` is valid and is
   also the default when the key is absent.
2. `agentic` inherits the positive-temperature rule of the other non-greedy
   schemes.

### Choice
Interpretation 1. The spec's own agentic task sets `temperature: 0.0`, so
rejecting it would make the documented example unloadable. The positive
requirement stays attached to `sample` and `rejection` alone.

### Risk: 5
Author most likely alternative: none plausible; the example pins this.

## T54: which endpoint an `llm_judge` call uses in completions mode

### Spec Text
> "When `api_type` is `\"completions\"`, send requests to
> `{api_url}/v1/completions` with a rendered prompt string instead of a
> messages array."

### Alternatives
1. `api_type` is a property of the task, so the judge call for that task also
   goes to `/v1/completions` through the same template.
2. The judge always uses the chat endpoint, since only generation is
   described as templated.

### Choice
Interpretation 1. `api_type` is configured beside `model` and `api_url` as a
property of the whole task rather than of one request kind, and a server
reached over `/v1/completions` is not guaranteed to serve
`/v1/chat/completions` at all; sending the judge somewhere else could make an
otherwise valid config unusable.

### Risk: 15
Author most likely alternative: judging always over the chat endpoint, which
would double the endpoints a completions-mode `llm_judge` run touches.

## T55: whether `result` keeps `iterations` and `tool_calls` in the list format

### Spec Text
> "in that list format, `result.attempts` is the number of loops started for
> the row, not the number of API requests across those loops" ... "in that
> list format, per-loop agentic metadata lives in each `meta` entry: keep
> checkpoint 3's `icl_setup` / `evaluation_passed` fields and also record
> that loop's aggregated `total_prompt_tokens`, `total_completion_tokens`,
> `total_tokens`, `latency_ms`, `finish_reason`, and `iterations_detail`"

### Alternatives
1. The enumeration is exhaustive: `result` keeps only checkpoint 3's
   `passed`/`failed`/`attempts`, and `iterations`/`tool_calls` are not
   recorded anywhere in the list format.
2. Each `meta` entry also carries that loop's `iterations` and `tool_calls`,
   since "per-loop agentic metadata lives in each `meta` entry".
3. `result` keeps `tool_calls` as a flat list across all loops.

### Choice
Interpretation 1. The sentence names exactly which fields move into `meta`,
and the only statement about `result` in the list format reaffirms the
checkpoint 3 keys; interpretation 3 would also lose which loop a call came
from. The single-solution format remains the only place `result.iterations`
and `result.tool_calls` appear.

### Risk: 35
Author most likely alternative: each `meta` entry additionally carrying that
loop's `tool_calls`, so the record does not drop the tool trace entirely.

## T56: whether a 5xx retry inside the loop counts as an iteration

### Spec Text
> "`result.iterations` is the number of API requests in the loop" ... "each
> API request inside the loop counts separately toward request totals"

### Alternatives
1. An iteration is one model turn; the Part 1 retry budget still applies
   within it, so three HTTP requests that end in one usable response are one
   iteration with one `iterations_detail` entry, while `total_api_calls`
   counts all three.
2. Every HTTP request, retries included, increments `iterations`.

### Choice
Interpretation 1. `iterations_detail` records "per-iteration token usage,
latency, and finish reason", which a failed 5xx request cannot supply, and
`max_iterations` is described as a bound on the tool-calling loop rather than
on transport retries. The separate sentence about request totals is satisfied
by the summary's `total_api_calls`, which counts every request.

### Risk: 20
Author most likely alternative: the same split, since a retried request has
no usage block to report.

## T57: an agentic loop whose request fails after every retry

### Spec Text
> "If `max_iterations` is reached first, output `null` and use
> `finish_reason: \"max_iterations\"`." (no rule for an exhausted retry
> budget inside the loop)

### Alternatives
1. The loop stops with no text; the row writes `output: null`, and `meta` is
   the aggregate over the iterations that did answer with
   `finish_reason: null` — or `null` outright when none did, matching T2.
2. Report `finish_reason: "max_iterations"` for any loop that produced no
   text.
3. Invent a third value such as `"error"`.

### Choice
Interpretation 1. The spec defines `finish_reason` as `"stop"` for a final
text response and `"max_iterations"` for the iteration limit, so a transport
failure is neither; `null` reuses Part 1's convention that an unanswered call
has nothing to report. `result.passed` then follows T3: `false` with an
evaluation configured, `null` without one, since the iteration limit was not
what ended the loop.

### Risk: 30
Author most likely alternative: collapsing every output-less loop to
`finish_reason: "max_iterations"`, which would also flip `result.passed` to
`false` for an unevaluated row.

## T58: whether `script` handler stdout is returned verbatim

### Spec Text
> "`script`: run `command` with the value of `arg_field` as a single
> command-line argument, capture stdout, and return it"

### Alternatives
1. Return stdout with surrounding whitespace stripped, so `python3 -c
   "print(4)"` answers `"4"`.
2. Return stdout byte for byte, so the same call answers `"4\n"`.

### Choice
Interpretation 1. The handler's result is both fed to the model and recorded
in `result.tool_calls`, and the `static_map` and `echo` handlers both return
values with no trailing newline; stripping keeps the three handler types
comparable and keeps a recorded result readable.

### Risk: 40
Author most likely alternative: `stdout.decode()` returned verbatim, so any
tool result from a `print` carries a trailing newline.

## T59: the `script` handler's timeout and its error text

### Spec Text
> "on timeout or non-zero exit, return `\"ERROR: <stderr or timeout
> message>\"`"

### Alternatives
1. Reuse Part 2's `script` evaluation timeout of 10s, overridable by a
   `timeout` key, and phrase the timeout message freely.
2. Leave the handler unbounded and only handle non-zero exits.

### Choice
Interpretation 1. The spec explicitly contemplates a timeout, so one has to
exist, and 10s is the only script timeout the project already documents. The
message text is not specified anywhere, so only the `ERROR: ` prefix is
treated as contractual.

### Risk: 10
Author most likely alternative: a different timeout value; the prefix is the
only part any test can portably assert.

## T60: an unknown tool name, or `function.arguments` that is not JSON

### Spec Text
> "parse `function.arguments` as JSON before invoking the handler" ...
> "execute every tool call ... and the tool result messages"

### Alternatives
1. Both stay inside the loop: an unrecognised name yields
   `"ERROR: unknown tool '<name>'"` as that call's result, and unparsable
   arguments become `{}` so the handler still runs.
2. Either condition aborts the row.
3. Skip the offending call and append no tool message for it.

### Choice
Interpretation 1. The spec says to execute and record *every* tool call, and
a chat API rejects a tool-call turn that is not followed by a result for each
`tool_call_id`; answering with an error string keeps the conversation valid
and lets the model recover, which is what the `static_map` default is for
too.

### Risk: 25
Author most likely alternative: skipping unknown tools entirely, which would
leave `result.tool_calls` shorter than the model's request.

## T61: how many loops an agentic row runs

### Spec Text
> "`agentic` also works with ICL and `num_solutions`; each solution is an
> independent loop" ... "if `num_solutions: 2` and both loops produce a final
> answer on their first API request ... `result.attempts` is `2`"

### Alternatives
1. An agentic row starts exactly `num_solutions` loops, like `sample`, and
   the ICL strategy picks each loop's setup.
2. Loops are retried until `num_solutions` of them succeed, like `rejection`.
3. With ICL, one loop per declared setup, like `greedy`.

### Choice
Interpretation 1. The example fixes two loops for `num_solutions: 2` and says
`attempts` counts loops started, not loops that succeeded — which rules out a
retry budget; and nothing ties the loop count to the number of ICL setups. A
loop that hits `max_iterations` therefore is not retried, and shows up in
`result.failed`.

### Risk: 10
Author most likely alternative: none plausible for the documented example;
the divergence would only show on a row where a loop fails.

## T62: `meta` entries for a list-format loop that emitted no output

### Spec Text
> "`result.failed` is the number of loops that produced no output" ... "`meta`
> is a list with two entries, one aggregated agentic metadata object per loop"

### Alternatives
1. One `meta` entry per loop that made at least one answered request,
   including loops that hit `max_iterations`, matching checkpoint 3's rule of
   one entry per attempt that got a response.
2. One entry only per loop that produced output, so `meta` lines up with the
   `output` list.

### Choice
Interpretation 1. The spec ties `meta` to loops rather than to emitted
outputs, and `finish_reason: "max_iterations"` has nowhere else to be
reported in the list format; checkpoint 3 already records metadata for
attempts that produced no solution.

### Risk: 30
Author most likely alternative: one `meta` entry per emitted output, so the
two lists stay index-aligned.

## T63: whether a non-agentic task sends its `tools` in chat mode

### Spec Text
> "Send an API request. In chat mode, include the task's tool definitions in
> the request body." (step 2 of the agentic loop)

### Alternatives
1. Only agentic requests carry `tools`; a `greedy`/`sample`/`rejection` task
   that declares `tools` sends none, since nothing would execute them.
2. Any task with a `tools` block sends them on every chat request.

### Choice
Interpretation 1. The instruction sits inside the agentic loop's numbered
steps, and only that loop can act on a `tool_calls` response — a
single-request scheme that advertised tools would read a tool-call reply as
final text with `content: null`.

### Risk: 15
Author most likely alternative: sending `tools` whenever the task declares
them, which differs only for a config that declares tools under another
scheme.
