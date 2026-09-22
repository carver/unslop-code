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
