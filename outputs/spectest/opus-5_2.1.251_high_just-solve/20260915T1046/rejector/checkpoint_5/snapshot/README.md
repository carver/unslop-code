# rejector

A CLI that reads a YAML config plus JSONL input, calls an OpenAI-compatible
`/v1/chat/completions` (or `/v1/completions`) endpoint concurrently, and writes
one JSONL result per input row. A config holds either a single task (`task:`) or
several named tasks (`defaults:` + `tasks:`) that run together. Tasks may carry
in-context learning (ICL) setups, collect several solutions per input, and call
tools in an agentic loop.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python rejector.py run --config examples/task.yaml \
    --input examples/data.jsonl --output results.jsonl
```

Multiple named tasks:

```bash
# explicit mapping mode
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input gsm8k=examples/data/gsm8k.jsonl --input mmlu=examples/data/mmlu.jsonl \
    --output results/

# directory mode: looks for <task_name>.jsonl
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input-dir examples/data --output results/

# run a subset; inputs for unselected tasks are neither required nor read
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input-dir examples/data --output results/ --task gsm8k --task review
```

ICL setups and several solutions per input:

```bash
.venv/bin/python rejector.py run --config examples/icl.yaml \
    --input-dir examples/data --output results/ \
    --num-solutions 3 --icl-strategy round_robin --icl-k 2
```

Agentic tasks and `/v1/completions`:

```bash
.venv/bin/python rejector.py run --config examples/agentic.yaml \
    --input examples/agentic.jsonl --output results.jsonl

.venv/bin/python rejector.py run --config examples/task.yaml \
    --input examples/data.jsonl --output results.jsonl \
    --api-type completions --chat-template llama3
```

Token-aware scheduling, a cost budget, resuming and estimates:

```bash
# pace against both a request and a token budget
.venv/bin/python rejector.py run --config examples/scheduled.yaml \
    --input examples/data.jsonl --output results.jsonl \
    --tpm 20000 --max-concurrent 8 --budget 5.0 --progress

# what would this cost? (no API calls)
.venv/bin/python rejector.py run --config examples/scheduled.yaml \
    --input examples/data.jsonl --output results.jsonl --dry-run

# continue an interrupted run, appending to the same file
.venv/bin/python rejector.py run --config examples/scheduled.yaml \
    --input examples/data.jsonl --output results.jsonl --resume
```

Optional overrides (each replaces the corresponding config value, for every
selected task): `--api-url`, `--model`, `--rpm`, `--tpm`, `--max-concurrent`,
`--budget`, `--max-tokens`, `--scheme`, `--temperature`, `--n`,
`--num-solutions`, `--icl-strategy`, `--icl-k`, `--api-type`,
`--chat-template`, and `--eval-model` (the judge model of every selected
`llm_judge` task).

Run modes: `--dry-run` (estimate only), `--resume` (skip rows already in the
output file), `--progress` (progress lines on stderr).

Exit codes: `0` on success, `1` on any configuration or input error (message on stderr).
A spent budget is not an error: the run stops early and still exits `0`.

## Multi-task configs

`defaults` supplies shared values and each task overrides them; nested sections
(`prompt`, `generation`, `evaluation`, `judge_prompt`, `icl`) are merged key by
key, so
a task can override `generation.scheme` while inheriting `generation.max_tokens`.
Required fields may come from either side. The task name is the key in `tasks`.
A config with a top-level `task` key is the single-task format and behaves
exactly as before (its name is `task.name`).

`--input <task=path>` and `--input-dir` are alternative modes and cannot be
combined. `--output` must be a directory for multi-task configs; each executed
task writes `<output_dir>/<task_name>.jsonl`, in input order. Tasks run
concurrently and their requests interleave.

## Schemes

With `num_solutions: 1` and no `icl` section (the part 1/2 default):

| scheme | temperature | attempts |
|---|---|---|
| `greedy` | forced to `0.0` | 1 (`n` ignored) |
| `sample` | must be `> 0` | 1 (`n` ignored) |
| `rejection` | must be `> 0` | up to `n`, stops at the first response that passes evaluation |
| `agentic` | used as given | 1 loop of up to `max_iterations` API requests |

`evaluation` is required for `rejection`, optional otherwise; when it is omitted
`result.passed` is `null` and such rows count as passed in the summary as long as
the API call succeeded.

Evaluation types: `exact_match` and `contains` (both need `answer_field`),
`regex` (needs `pattern`), `script` and `llm_judge`. Extract methods:
`last_number`, `last_line`, `full` (default), `letter` and `first_number`.
`exact_match` compares the extracted value to the row's `answer_field`,
tolerating surrounding whitespace, thousands separators, `$`/`%` and a trailing
period, and comparing numerically when both sides are numeric.

`letter` picks the first standalone `A`-`D` (`A`, `(A)`, `A)`, `Answer: A`);
`first_number` picks the first integer or decimal.

### `script`

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

`command_template` may reference row fields and `__response__`; if a row field
expands to text that itself contains `{__response__}`, that is substituted too,
so a row can carry its own test snippet. The rendered command runs in a shell
(its own process group) and passes when its exit code equals `success_exit_code`.
stdout and stderr are captured but never written to the output. The command is
killed after 10 seconds, which counts as a failed evaluation.

### `llm_judge`

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7
  extract: "first_number"
  model: "gpt-4"          # optional; defaults to the task's model
```

The judge is a second call to the same server, made after the generation it
scores. The score is extracted with `extract` (default `first_number`) and the
row passes when `score >= threshold`. `result.judge_score` holds the score and
`meta.judge_meta` the judge call's tokens, latency, model and finish reason (one
per attempt for rejection rows). Judge calls count toward throughput,
`total_api_calls` and the task's `total_api_calls`, and interleave freely with
other work.


## In-context learning

A task may define named ICL setups; each one is a list of examples that are
replayed as alternating user/assistant turns between the system message and the
final user message. Example inputs are rendered with the task's `prompt.user`
template and example outputs are sent verbatim.

```yaml
tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem step by step. Final answer after ####."
      user: "{question}"
    icl:
      setups:
        - name: "chain_of_thought"
          examples:
            - input: {question: "What is 2+2?"}
              output: "Let me think step by step.\n2 + 2 = 4\n#### 4"
        - name: "detailed"
          file: "icl/gsm8k_detailed.jsonl"
      k: 2
      strategy: "round_robin"
```

Each setup has a `name` and exactly one of `examples` or `file`. A `file` path is
relative to the config file's directory and must be JSONL whose every non-empty
line is `{"input": <object>, "output": <string>}`; a malformed line ends the run
with exit code 1 before any request is sent. `k` (default: all of the setup's
examples) keeps the first `k` examples of whichever setup is selected.

`strategy` (default `fixed`) decides which setup an attempt uses:

| strategy | behaviour |
|---|---|
| `fixed` | always the first setup |
| `random` | chosen independently for each attempt |
| `round_robin` | cycles through the setups in order across a row's attempts |

`greedy` with ICL and `num_solutions > 1` ignores `strategy`: it walks the setups
in declared order, at most once each, so it can never produce more solutions than
there are setups.

## Multiple solutions

`num_solutions` (in `defaults` or per task, overridden by `--num-solutions`)
asks for several solutions per input row:

```yaml
tasks:
  gsm8k:
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
      max_attempts: 15
    num_solutions: 5
```

| scheme | with ICL | without ICL |
|---|---|---|
| `greedy` | one attempt per setup at temperature 0, until `num_solutions` are collected or the setups run out | a single attempt |
| `sample` | one sampled attempt per requested solution, using `strategy` | `num_solutions` independent sampled attempts |
| `rejection` | attempts until `num_solutions` pass or `max_attempts` is spent | the same, with the same prompt every attempt |
| `agentic` | one full tool-calling loop per requested solution, using `strategy` | `num_solutions` independent loops |

Evaluation only gates `rejection`: `greedy` and `sample` emit every generation
they get and record whether it passed. `max_attempts` applies to `rejection` and
defaults to `3 * num_solutions`.

When `num_solutions == 1` and no ICL is configured the part 1 behaviour is kept
exactly: `rejection` makes up to `generation.n` attempts, `max_attempts` is
ignored, and the row keeps the part 1 output shape.

## Agentic generation

`scheme: "agentic"` lets the model call tools in a loop before answering. The
task lists the tools; every handler runs locally in this process.

```yaml
tasks:
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools."
      user: "{question}"
    generation:
      scheme: "agentic"
      max_iterations: 10      # API requests per loop, default 10
      temperature: 0.0
      max_tokens: 512
    output_field: "answer"
    tools:
      - name: "lookup"
        description: "Look up a value in the database by key"
        parameters:           # JSON schema, sent verbatim as the tool's parameters
          type: "object"
          properties:
            key: {type: "string"}
          required: ["key"]
        handler:
          type: "static_map"
          mapping: {"employees": "142"}
          default: "KEY_NOT_FOUND"
```

Handlers:

| type | behaviour |
|---|---|
| `echo` | returns the parsed tool arguments as a JSON string |
| `static_map` | looks the first required parameter up in `mapping`, else `default` (itself defaulting to `"NOT_FOUND"`) |
| `script` | runs `command` with the `arg_field` value as one extra argv entry and returns stdout |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

A `script` handler that exits non-zero or runs longer than 10 seconds returns
`"ERROR: <stderr or timeout message>"` instead of stdout.

The loop builds the conversation (system prompt, optional ICL examples, user
prompt) and then, per iteration, sends one API request — in chat mode with the
tool definitions in the request body. A response with `tool_calls` has every
call executed (arguments are parsed as JSON first); the assistant tool-call
message and one `tool` message per result are appended and the loop continues.
A response with text and no tool calls ends the loop. Reaching
`max_iterations` first writes `output: null` and `finish_reason:
"max_iterations"`.

Every request in the loop counts separately toward `total_api_calls`, and rows
keep running concurrently: several rows' loops overlap in flight.

```json
{"input": {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"},
 "output": {"answer": "The total revenue for Q1 and Q2 is $2,730,000."},
 "result": {"passed": true, "extracted_answer": "2730000", "attempts": 1, "iterations": 3,
            "tool_calls": [{"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
                            "result": "1250000"}]},
 "meta": {"total_prompt_tokens": 850, "total_completion_tokens": 120, "total_tokens": 970,
          "latency_ms": 1200, "finish_reason": "stop",
          "iterations_detail": [{"prompt_tokens": 200, "completion_tokens": 30,
                                 "total_tokens": 230, "latency_ms": 300,
                                 "finish_reason": "tool_calls"}]}}
```

`result.iterations` is the number of API requests in the loop and
`result.tool_calls` lists every call in execution order. `meta.total_*` are
summed over the iterations, `meta.latency_ms` is the loop's wall-clock time and
`meta.iterations_detail` holds one entry per request. Evaluation sees the final
text only, so a `max_iterations` row fails; without an `evaluation` section
`result.passed` stays `null`.

`agentic` combines with ICL and `num_solutions`, where each solution is an
independent loop. The row then keeps the list output format: `result.attempts`
counts loops (not requests), `result.passed`/`result.failed` count as before,
and each `meta` entry carries that loop's `total_prompt_tokens`,
`total_completion_tokens`, `total_tokens`, `latency_ms`, `finish_reason`,
`iterations`, `tool_calls` and `iterations_detail` next to checkpoint 3's
`icl_setup` and `evaluation_passed`.

## Completions mode

`api_type: "completions"` (in `defaults`, per task, or via `--api-type`) sends
requests to `{api_url}/v1/completions` with the conversation rendered into a
single `prompt` string by `chat_template` (`--chat-template`, default
`chatml`):

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"

tasks:
  gsm8k:
    api_type: "completions"
    chat_template: "chatml"
```

The request carries `model`, `prompt`, `temperature` and `max_tokens`, and the
reply is read from `choices[0].text`. Built-in templates are `chatml`,
`llama3`, `mistral` and `zephyr`; each repeats its role markers for every
message, so ICL turns and agentic tool results render correctly (`mistral` has
no system role, so system text is folded into the first instruction block).
Judge calls of an `llm_judge` evaluation use the same endpoint and template.

In completions mode an agentic task renders its tool declarations into the
prompt instead of sending a `tools` field, and reads tool calls back out of the
response text:

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

Results are appended as `tool`-role turns and rendered with the template's tool
markers for the next iteration.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"<output_field>": "..."} , "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {...}}
```

With `output_schema` the value under `<output_field>` is the parsed JSON, and
`result` carries `schema_valid` (plus `schema_error` on failure). `--resume`
adds `resumed_from` to the summary and cost tracking adds the `cost` block.

`output` is `null` when every attempt fails; `meta` is a single object for
one-attempt rows and a list (one entry per logical attempt) for multi-attempt
rejection rows. `llm_judge` rows add `result.judge_score` and `meta.judge_meta`.

As soon as a task configures ICL or asks for more than one solution, that row
format changes: `output` becomes a list and `meta` always a list, one entry per
attempt.

```json
{"input": {"question": "What is 15 + 27?", "answer": "42"},
 "output": [{"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
            {"solution": "#### 42", "icl_setup": "direct"}],
 "result": {"passed": 2, "failed": 5, "attempts": 7},
 "meta": [{"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
           "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
           "icl_setup": "chain_of_thought", "evaluation_passed": true}]}
```

Each solution carries the task's `output_field` plus `icl_setup` (the setup that
produced it, or `null` without ICL). `result.passed` counts passing solutions,
`result.failed` counts failed attempts and `result.attempts` counts all
generation attempts for the row. Without an `evaluation` section every
`evaluation_passed` is `null`, `result.passed` is the number of emitted outputs
and `result.failed` the number of attempts that produced none.

A JSON summary is printed to stdout when the run finishes. For multi-task
configs it also carries a `tasks` object, keyed by the name of each task that
actually ran:

```json
{"total": 200, "passed": 170, "failed": 30, "total_api_calls": 350,
 "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
 "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
                     "avg_solutions_per_input": 4.5, "total_api_calls": 850}}}
```

Every per-task entry reports `total_solutions` and `avg_solutions_per_input`; a
row counts as passed when at least one of its solutions passed. The same two
fields appear at the top level when any task in the run emits multiple
solutions.

## Rate limits

```yaml
defaults:
  rate_limits:
    rpm: 100
    tpm: 50000
    max_concurrent: 10

tasks:
  code_gen:
    rate_limits:
      tpm: 30000      # overrides only tpm; rpm and max_concurrent are inherited
```

`rate_limits` merges from `defaults` into every task key by key, like `prompt`,
`generation` and `evaluation`. `--rpm`, `--tpm` and `--max-concurrent` override
the corresponding key for every selected task. A top-level `rpm:` (the part 1
spelling) still works and is equivalent to `rate_limits.rpm`.

| key | effect |
|---|---|
| `rpm` | at most `rpm` requests in any sliding 60-second window; omitted means no request limit |
| `tpm` | at most `tpm` tokens in any sliding 60-second window; omitted means no token limit |
| `max_concurrent` | hard cap on in-flight requests, independent of `rpm` and `tpm` |

Before a request is dispatched its prompt is estimated from the word count of
the rendered messages (`1 token ~= 0.75 words`, rounded up) and
`estimated_prompt_tokens + max_tokens` is reserved in the token window; when the
response arrives the reservation is replaced by the `prompt_tokens +
completion_tokens` the API reported. With both limits configured a request waits
until both windows have room, so the tighter of the two paces the run — with
`rpm: 600`, `tpm: 10000` and ~612-token requests, the token budget is what
binds.

Judge calls pass through the same limiter. An agentic loop holds one
concurrency slot for its whole lifetime, and every request it makes counts
toward `rpm` and `tpm`.

## Concurrency

Rows are processed as concurrent asyncio tasks over a shared HTTP connection
pool, with in-flight work capped per task at `max(8, min(rpm, 256))` rows (at
least `max_concurrent`, never more than that task's row count); tasks run
against that pool at the same time. Requests themselves are gated by the
limiter above. With no `rate_limits` the client keeps its queue non-empty
rather than pacing itself, and measured throughput lands at ~99% of the
configured `rpm` against a server whose capacity is `rpm` (see
`tests/test_all.py`). New connections ramp over the first ~0.25 s to avoid
overflowing a small listen backlog. Rows are paired with their outputs by input
index, so overlapping requests never swap results.

## Cost tracking

```yaml
defaults:
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0

tasks:
  code_gen:
    cost:
      prompt_cost_per_1k: 0.005
      completion_cost_per_1k: 0.015
```

Each call costs
`prompt_tokens / 1000 * prompt_cost_per_1k + completion_tokens / 1000 *
completion_cost_per_1k`, summed over every task, judge call and agentic
iteration. `--budget` overrides `cost.budget`.

When the running total reaches the budget, no new request is sent: in-flight
work finishes, the rows that completed are written, the summary is printed and
the exit code stays `0`. Rows that could not finish are left out of the output.
The summary grows a `cost` block (omitted entirely when no task configures
`cost`):

```json
{"cost": {"total": 12.45, "prompt": 4.50, "completion": 7.95,
          "budget": 50.0, "budget_remaining": 37.55, "budget_exceeded": false}}
```

## Structured output

```yaml
tasks:
  code_gen:
    output_schema:
      type: "object"
      required: ["code", "explanation"]
      properties:
        code: {type: "string"}
        explanation: {type: "string"}
```

With `output_schema` the response is parsed as JSON and validated before any
other evaluation; unparseable JSON is a schema failure. The supported draft 7
keywords are `type`, `required`, `properties`, `items`, `enum`, `minimum`,
`maximum`, `minLength`, `maxLength` and `pattern`.

On success the parsed value (not the raw string) is stored under the task's
`output_field` and `result.schema_valid` is `true`:

```json
{"output": {"code": {"code": "def add(a, b): return a + b",
                     "explanation": "Simple addition function"}},
 "result": {"passed": true, "schema_valid": true}}
```

On failure the row keeps `output: null`, `result.schema_valid: false` and a
readable `result.schema_error`, and evaluation is skipped:

```json
{"output": null,
 "result": {"passed": false, "schema_valid": false,
            "schema_error": "Missing required field: explanation"}}
```

A failed schema is a failed attempt for `rejection` (which may then try again)
and `passed: false` for `greedy` and `sample`. `rejection` may be gated by
`output_schema` alone, with no `evaluation` section; when both are configured
the schema runs first.

## Resume

`--resume` inspects an existing output file, skips that many leading input rows
(outputs are written in input order, so the line count is the number of
completed rows) and appends the rest. Multi-task runs resume each task's file
separately. A trailing row that is an unfinished multi-solution or rejection
result — fewer passing solutions than `num_solutions` — is dropped and
reprocessed from scratch. The summary covers only the newly processed rows and
reports `resumed_from`:

```json
{"total": 50, "resumed_from": 50, "passed": 42, "failed": 8}
```

## Dry run

`--dry-run` validates the config and the inputs, counts the rows of each task
and prints an estimate to stdout without sending a single request (exit `0`).
Prompt tokens are estimated as `average prompt word count * 1.33`, completion
tokens as `max_tokens` per input, cost from the configured rates, and time as
`inputs * avg_attempts / rpm` minutes (`avg_attempts` is `1` for `greedy` and
`sample`, the rejection attempt budget for `rejection`):

```json
{"tasks": {"gsm8k": {"inputs": 1000, "est_prompt_tokens": 45000,
                     "est_completion_tokens": 512000,
                     "est_total_tokens": 557000, "est_cost": 20.31}},
 "total_inputs": 1000, "est_total_tokens": 557000,
 "est_total_cost": 20.31, "est_time_minutes": 9.3}
```

## Progress

`--progress` prints one line to stderr every 5 seconds or every 10% of the
inputs, whichever comes first (stdout still carries only the summary):

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The `passed`/`failed` field appears only when evaluation (or `output_schema`)
is configured and `$... spent` only when cost tracking is.

## Retries

HTTP `5xx` responses and transport errors are retried up to 3 times (4 HTTP
calls maximum per logical attempt) with exponential backoff. Every HTTP call
counts toward `total_api_calls`, but retries never increase `result.attempts`.
When retries are exhausted the row is emitted with `output: null`, counted as
failed, and the run continues. HTTP `4xx` is treated as an immediate row failure.

## Tests

```bash
.venv/bin/python tests/test_all.py     # parts 1-4
.venv/bin/python tests/test_part5.py   # part 5
```

Spawns mock servers (`tests/mock_server.py`, which queues requests behind a
worker pool so its capacity is a real rpm ceiling) and exercises all three
schemes, every evaluation and extract method, retry/failure paths, CLI
overrides, config/input validation, and the throughput target, plus multi-task
configs: `defaults` merging, both input modes, `--task` selection, `--eval-model`,
judge scoring/metadata/retries, and script pass/fail/timeout handling. Part 3
adds ICL message layout, inline and file-backed setups, every strategy, `k`
selection, all scheme/`num_solutions` combinations, partial rejection results,
the list output format, the new summary fields, the CLI overrides, and the ICL
validation errors (which must exit 1 with no request sent). Part 4 adds the
agentic loop (single and multiple tool calls, every handler type, script
failures and timeouts, `max_iterations`, list-format loops, concurrency), the
completions endpoint and payload shape, exact renderings of all four built-in
templates for multi-turn conversations, agentic tool calling over
`/v1/completions`, and the new CLI/config validation errors.

`tests/test_part5.py` (mock server: `tests/mock5.py`, which replies with JSON
and reports per-request timestamps) covers `max_concurrent`, the sliding RPM
window, TPM reservations and their refill from reported usage, cost totals and
per-task rate merging, budget exhaustion (partial output, exit `0`), schema
success/failure paths including schema-gated rejection, `--dry-run`,
`--resume` (including reprocessing an unfinished row) and the `--progress`
line format. The RPM window test deliberately waits out a 60-second window, so
the part 5 suite takes about 1.5 minutes.
