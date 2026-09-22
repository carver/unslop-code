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
## T25 — How `defaults` merges into each task

### Spec Text

> - `defaults` provides shared values; each task overrides `defaults`
> - nested sections such as `prompt`, `generation`, and `evaluation` are merged
>   per task using the Part 1 structure

### Alternatives

1. Recursive merge at every depth: `defaults` and the task are merged key by
   key, and any mapping present in both (including `evaluation.judge_prompt`)
   is merged again rather than replaced.
2. Merge only the three named sections one level deep, replacing anything
   deeper wholesale.
3. Replace whole sections: a task that sets `generation.scheme` loses
   `defaults.generation.max_tokens`.

### Choice

Option 1. The spec's own example relies on merging (`defaults.generation` has
only `max_tokens`, every task's `generation` has only the scheme/temperature),
which rules out option 3, and "such as" makes the list of merged sections
open-ended rather than exhaustive — so the merge is applied uniformly at every
depth instead of being special-cased to three names.

### Risk: 15

The author most likely prefers: option 1 or option 2, which agree on every
config in the spec; they differ only when `defaults` and a task both set a
sub-mapping of `evaluation` such as `judge_prompt`.

---

## T26 — A config that contains both `task` and `tasks`

### Spec Text

> - if the config still uses a top-level `task` key, treat it as the Part 1
>   single-task format; the task name is `task.name`

### Alternatives

1. `task` wins: the presence of a top-level `task` key selects the Part 1
   format and `tasks`/`defaults` are ignored.
2. Reject the config as ambiguous.
3. `tasks` wins when both are present.

### Choice

Option 1. The rule is written as a test on the presence of the `task` key
("if the config still uses a top-level `task` key"), not as a test on the
absence of `tasks`, so presence alone decides the format.

### Risk: 10

The author most likely prefers: option 1; this is a malformed config nobody is
likely to write a fixture for.

---

## T27 — A single-task config with no `task.name`

### Spec Text

> - if the config still uses a top-level `task` key, treat it as the Part 1
>   single-task format; the task name is `task.name`

(Part 1 does not make `task.name` a required field.)

### Alternatives

1. Fall back to a fixed name (`"task"`) when `task.name` is absent, so the
   summary's `tasks` object always has a usable key.
2. Make `name` required as soon as a name is needed, failing the run.
3. Key the summary entry on `null`.

### Choice

Option 1. Part 1 accepted configs without a `name`, and "Existing behavior
from Part 1 is unchanged unless stated here" — refusing such a config now
would be a new failure mode. A fixed placeholder keeps the summary well formed
and JSON-serialisable.

### Risk: 25

The author most likely prefers: option 3 (a `null` key is what a naive
`task.get("name")` produces), though their fixtures very likely always set a
name, in which case nothing distinguishes the readings.

---

## T28 — What `letter` matches

### Spec Text

> - `letter`: extract the first uppercase answer choice `A` through `D`; accept
>   forms such as `A`, `(A)`, `A)`, or `Answer: A`

### Alternatives

1. The first standalone `A`-`D`, i.e. one not glued to other word characters
   (`\b[A-D]\b`). `Answer: A` yields `A` from the label's argument, not from
   the `A` that starts "Answer".
2. The first `A`-`D` character anywhere in the response, embedded letters
   included.

### Choice

Option 1. "Answer choice" means the letter is standing in for a choice, and
the listed forms are exactly the ways a choice letter appears surrounded by
punctuation or whitespace. Option 2 agrees with every example in the spec only
by accident (`Answer` begins with `A`, and the MMLU example's `B` is the first
uppercase A-D character anyway), but it misreads ordinary responses such as
`Definitely the choice is C` as `D`.

### Risk: 30

The author most likely prefers: option 2 — a bare `re.search(r"[A-D]", text)`
is the shortest implementation and passes both of the spec's own examples; the
readings diverge only when a capitalised word containing A-D precedes the real
choice.

---

## T29 — `first_number` on signs and decimals

### Spec Text

> - `first_number`: extract the first integer or decimal in the response

### Alternatives

1. Reuse Part 1's number pattern (`-?\d+(?:\.\d+)?`), so a leading minus sign
   belongs to the number and `first_number` is the mirror image of
   `last_number`.
2. Match unsigned numbers only.

### Choice

Option 1. The two methods name the same notion of "number" and differ only in
which match is taken, so they share one pattern; anything else would make
`first_number` and `last_number` disagree on the same response.

### Risk: 15

The author most likely prefers: option 1. The readings only diverge on a
negative number, which a 1-10 judge score never produces.

---

## T30 — Row fields referenced only by `command_template` or `judge_prompt`

### Spec Text

> - `command_template` may reference row fields and `__response__`
> - `judge_prompt` uses the same template rules as normal prompts

(Part 1: "If a row is missing a field the template needs, exit 1 before any
requests are made.")

### Alternatives

1. Pre-flight them like prompt fields: a row missing `{test_code}` or
   `{criteria}` fails the run before any request is sent.
2. Only pre-flight the prompt templates, and let a missing field surface later
   (as a crash, an unsubstituted `{criteria}` literal, or a failed row).

### Choice

Option 1. "the same template rules as normal prompts" pulls the judge prompt
into Part 1's validation rule, and a script command is a template over the row
in exactly the same sense. Failing fast is also the only behaviour that keeps
Part 1's promise that a bad input file costs no API calls.

### Risk: 25

The author most likely prefers: option 2 for `command_template` (validation
written in Part 1 naturally covers only `prompt`), which differs from this
choice by exiting 0 with a failed row instead of exiting 1.

---

## T31 — Required versus defaulted fields in the new evaluation blocks

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

1. `command_template`, `judge_prompt` and `threshold` are required (a run
   cannot be defined without them); `success_exit_code` defaults to `0`;
   `evaluation.extract` defaults to `first_number` for `llm_judge`; and the
   judge score is compared numerically, so a decimal score works.
2. Everything shown in the example is required, including
   `success_exit_code` and `extract`.
3. Everything is optional with some implied default (e.g. `threshold` 0).

### Choice

Option 1. The spec states a rule for the omission of one field only
(`evaluation.model`), so the rest is judged by whether a sensible default
exists: `0` is the conventional success exit code and the only value the spec
ever shows, and `first_number` is the only extraction that makes sense of "a
single integer from 1 to 10". A missing `threshold` or `command_template` has
no defensible default, so it is a configuration error.

### Risk: 20

The author most likely prefers: option 1 for the required fields; the defaults
for `success_exit_code` and the judge's `extract` are the uncertain half, and
only matter for configs that omit them.

---

## T32 — Depth and order of `__response__` substitution in a command

### Spec Text

> - `command_template` may reference row fields and `__response__`
> - if a row field such as `{test_code}` expands to text that itself contains
>   `{__response__}`, substitute `__response__` before executing the command

### Alternatives

1. Two stages: render row fields and `__response__` over the template once,
   then replace any remaining literal `{__response__}` produced by that
   expansion. Text that the *response* introduces is never re-scanned, and no
   shell quoting or escaping is applied.
2. Render repeatedly to a fixed point, so placeholders introduced by a
   response are also expanded.
3. Shell-quote the response before substituting it.

### Choice

Option 1. The spec asks for exactly one extra substitution pass and names only
`__response__` as its subject. Re-scanning the model's output would let a
response inject row fields into the command, and quoting would break the
spec's own example, where `{__response__}` already sits inside `'...'`.

### Risk: 15

The author most likely prefers: option 1; option 2 differs only when a model
response itself contains `{...}` placeholders.

---

## T33 — `extracted_answer` for a `script` evaluation

### Spec Text

> ```yaml
> evaluation:
>   type: "script"
>   command_template: ...
>   success_exit_code: 0
> ```

(Part 1 output: `result.extracted_answer` — "the extracted answer".)

### Alternatives

1. `null`: a script evaluation has no extraction step, so there is no
   extracted answer to report.
2. The response run through `evaluation.extract` anyway, which with Part 1's
   default (`full`) means the whole response is duplicated into
   `extracted_answer`.

### Choice

Option 1. `script` evaluation never mentions `extract`, and the field is
documented as the answer the comparison used — a script compares an exit code,
not an answer. Echoing the entire response into `extracted_answer` would also
duplicate the output field for no stated reason.

### Risk: 30

The author most likely prefers: option 1, but an implementation that runs
extraction before dispatching on the evaluation type would emit the full
response instead.

---

## T34 — Generation settings for the judge call

### Spec Text

> - the judge request is a separate API call through the same server
> - if `evaluation.model` is omitted, use the task's model

### Alternatives

1. Send the judge call at temperature `0.0` with the task's `max_tokens`: only
   the model is inherited, and judging is deterministic.
2. Inherit the task's `temperature` too, so a `rejection` task at 0.8 also
   judges at 0.8.

### Choice

Option 1. The spec inherits exactly one generation setting — the model — and
says nothing about the sampling settings, which belong to the task's own
generation `scheme`. A judge is a measurement, so it should not vary run to
run; `max_tokens` is inherited because the request needs some limit and the
task's is the only one configured.

### Risk: 25

The author most likely prefers: option 2, if their judge call reuses the same
request builder as generation; the difference is visible only in the request
body a test server records.

---

## T35 — A judge call that fails or returns no number

### Spec Text

> - score `>= threshold` passes
> - `result` includes `judge_score`

### Alternatives

1. Treat it as a failed evaluation: `passed: false`, `judge_score: null`, and
   the generated output is still reported. Retries follow Part 1's 5xx rule,
   and the failed call still counts in `total_api_calls`.
2. Abort the row as if generation had failed, dropping the output.
3. Exit 1 for the whole run.

### Choice

Option 1. A judge that produces no score cannot clear the threshold, so the
row has not passed; but the generation call did succeed, and Part 1 keeps the
output of a row whose evaluation fails (T16). Making a flaky judge fatal to
the run contradicts Part 1's treatment of API failure as per-row data.

### Risk: 20

The author most likely prefers: option 1; option 2 differs by reporting
`output: null` for a judge outage.

---

## T36 — Where `judge_meta` lives when `meta` is a list

### Spec Text

> - `meta` includes a `judge_meta` object with the judge request's token usage,
>   latency, model, and finish reason

(Part 1: "meta is a single metadata object for one-attempt rows; for rejection
sampling it is a list, one entry per attempt.")

### Alternatives

1. `judge_meta` is a key of the per-attempt metadata object: with rejection
   sampling each attempt carries the metadata of the judge call that scored
   *that* attempt.
2. One `judge_meta` per row, alongside the list — which has no place to live,
   since the row's `meta` is the list itself.
3. Only the last judge call is recorded.

### Choice

Option 1. Every generation attempt under `llm_judge` is scored by its own
judge call, so the metadata pairs one-to-one with attempts; option 1 is the
only shape that keeps that pairing and still satisfies "`meta` includes a
`judge_meta` object" for the single-attempt case the spec illustrates.

### Risk: 30

The author most likely prefers: option 1 for greedy tasks (where all readings
coincide); a `rejection` + `llm_judge` fixture is where option 3 would differ.

---

## T37 — Scheduling rows across tasks

### Spec Text

> - requests from different tasks may run concurrently and may be interleaved
> - within each task's output file, row order must still match input order

### Alternatives

1. One shared worker pool for every selected task, fed round-robin across
   tasks, sized from the largest `rpm` among them (Part 1's T20 rule).
2. Run tasks strictly one after another; "may be interleaved" only permits
   concurrency, it does not require it.
3. One pool per task, each sized from that task's own `rpm`.

### Choice

Option 1. "may run concurrently and may be interleaved" describes a run that
mixes tasks, and a single pool is what makes `total_api_calls` and
`throughput_rpm` describe one run rather than a sum of runs. Round-robin
feeding makes the interleaving actually happen instead of leaving it to
scheduling luck. Per-task `rpm` values differing is unusual; taking the maximum
keeps the busiest task saturated.

### Risk: 10

The author most likely prefers: option 1 or 2 — both are conforming, and no
test can require interleaving without being flaky, so only loose properties
(ordering, totals) are observable.

---

## T38 — Whether the Part 1 token totals survive in the summary

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

> Existing behavior from Part 1 is unchanged unless stated here.

### Alternatives

1. Keep `total_prompt_tokens` and `total_completion_tokens` (judge calls
   included) and add `tasks`; the example above is an abridged illustration of
   the new key.
2. Treat the example as the complete summary and drop the token totals.

### Choice

Option 1. The section is titled "Summary And Scheduling" and its rules speak
only about `tasks`; dropping two documented Part 1 fields would be a change
"stated here", and it is not. The example also omits them in the same breath
as omitting the per-task token counts it never defines.

### Risk: 30

The author most likely prefers: option 1, but a summary built to match the
printed example verbatim would omit the token totals, and an exact-key
assertion would then disagree.

---

## T39 — `--task` ordering and unknown names

### Spec Text

> - `--task <name>`: repeatable; run only the selected task or tasks

### Alternatives

1. Selected tasks keep their config order (not the order of the flags), and a
   `--task` naming a task absent from the config is a configuration error.
2. Use the CLI order, and ignore unknown names silently.

### Choice

Option 1. `--task` selects from the config, so the config's order is the
run's; silently ignoring a misspelt task name would produce an empty or
partial run that looks successful.

### Risk: 8

The author most likely prefers: option 1. Ordering is only observable in JSON
key order, which tests normally compare as sets.

---

## T40 — `--input-dir` with a single-task config

### Spec Text

> - for multi-task configs, explicit `--input <task=path>` and `--input-dir`
>   are alternative modes; do not combine them
> - for single-task configs, `--input <path>` without `=` still behaves as in
>   Part 1

### Alternatives

1. `--input-dir` is a multi-task-only mode: with a Part 1 config it is a
   configuration error, and `--input` remains required.
2. Accept it for single-task configs too, looking for `<task.name>.jsonl`.

### Choice

Option 1. Every rule about `--input-dir` is scoped to multi-task configs, and
the single-task rule is stated in terms of `--input`. Guessing a filename from
a `name` that Part 1 did not even require would invent behaviour the spec
never describes.

### Risk: 20

The author most likely prefers: option 2 if their input resolution is shared
across both config shapes; the difference is exit 1 versus a normal run.

---

## T41 — `--input <task>=<path>` with a single-task config

### Spec Text

> - for single-task configs, `--input <path>` without `=` still behaves as in
>   Part 1

### Alternatives

1. Accept both: a bare path is Part 1's form, and `name=path` is accepted when
   `name` is the single task's name (anything else is treated as a path, since
   a path may legitimately contain `=`).
2. Reject any `=` for single-task configs.

### Choice

Option 1. The rule singles out the `without =` form as still working; it does
not forbid the mapping form, and accepting it makes the two config shapes
scriptable the same way. Falling back to "it is a path" preserves Part 1
behaviour for the odd filename containing `=`.

### Risk: 12

The author most likely prefers: option 1 or 2; a fixture passing `task=path`
to a Part 1 config is unlikely either way.

---

## T42 — A multi-task `--output` directory that does not exist

### Spec Text

> - for multi-task configs, `--output` must be a directory
> - write `<output_dir>/<task_name>.jsonl`

### Alternatives

1. Create the directory (and any missing parents) if it is absent; error only
   when the path exists and is not a directory.
2. Require it to exist already, erroring otherwise.

### Choice

Option 1. Part 1 creates its output file rather than demanding it exist, so
creating the directory is the same promise one level up; `results/` in the
spec's examples is an output location, not a prerequisite. A path that already
exists as a file is still an error, because overwriting it would violate "must
be a directory".

### Risk: 25

The author most likely prefers: option 1, but an implementation that simply
opens `<dir>/<task>.jsonl` would fail with an OS error (exit 1) on a missing
directory.

---

## T43 — Whether `tasks` appears for a Part 1 single-task config

### Spec Text

> The stdout summary now includes a `tasks` object keyed by executed task name

> - if the config still uses a top-level `task` key, treat it as the Part 1
>   single-task format; the task name is `task.name`

### Alternatives

1. Always: a single-task run reports one entry, keyed by `task.name`.
2. Only for multi-task configs, leaving the Part 1 summary byte-for-byte as it
   was.

### Choice

Option 1. The spec goes out of its way to define the task name for the Part 1
format, which is only useful if that name is used as a key somewhere — and the
summary is the only place a single-task run would use it. "The stdout summary
now includes a `tasks` object" is unconditional, and the change is stated here,
so it is not covered by "unchanged unless stated".

### Risk: 35

The author most likely prefers: option 1, but an implementation that branches
on config shape before building the summary would omit `tasks` for Part 1
configs, and a Part 1 regression test asserting the exact key set would then
fail against this choice.

---

## T44 — `judge_score` and `extracted_answer` for `llm_judge` rows

### Spec Text

> - `result` includes `judge_score`

### Alternatives

1. `judge_score` appears only on rows of an `llm_judge` task, and
   `extracted_answer` holds the text the judge's `extract` method pulled out of
   the judge response (`"8"`), with `judge_score` its numeric value (`8`).
2. `judge_score` appears on every row of every task, `null` outside
   `llm_judge`.
3. `extracted_answer` holds the generated response, or `null`, and only
   `judge_score` reports the judging.

### Choice

Option 1. The rule is stated under the `llm_judge` heading, so it describes
what that evaluation adds to `result`, not a new universal field — Part 1 rows
keep exactly the three keys Part 1 documents. `evaluation.extract` in an
`llm_judge` block can only be about the judge's reply, so its result is what
`extracted_answer` reports; the spec's own example pairs the string `"8"` with
the number `8`.

### Risk: 30

The author most likely prefers: option 1 for the `judge_score` scoping;
`extracted_answer` is the uncertain half — a `null` there (option 3) is just as
plausible as the judge's extracted text.

---
