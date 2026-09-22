# rejector

CLI for running YAML-configured generation tasks against an
OpenAI-compatible chat completions API.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Run

Single-task config (Part 1 format, a top-level `task` key):

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Multi-task config (`defaults` plus a `tasks` mapping):

```bash
# explicit mapping mode
.venv/bin/python rejector.py run --config multi.yaml \
    --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/

# directory mode: looks for <task_name>.jsonl
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/

# run a subset
.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl \
    --output results/ --task gsm8k
```

The two input modes are alternatives and may not be combined. For multi-task
configs `--output` is a directory and one `<task_name>.jsonl` is written per
executed task; single-task configs still write one file.

Optional overrides: `--api-url`, `--model`, `--rpm`, `--max-tokens`,
`--scheme`, `--temperature`, `--n`, `--task` (repeatable), `--eval-model`
(judge model for `llm_judge` tasks), `--num-solutions`, `--icl-strategy`,
`--icl-k`, `--api-type`, `--chat-template`.

## In-context learning and multiple solutions

A task may declare named ICL setups and ask for several solutions per input:

```yaml
tasks:
  gsm8k:
    generation: {scheme: "rejection", temperature: 0.7, max_attempts: 15}
    num_solutions: 5
    icl:
      setups:
        - name: "chain_of_thought"
          examples:
            - input: {question: "What is 2+2?"}
              output: "2 + 2 = 4\n#### 4"
        - name: "detailed"
          file: "icl/gsm8k_detailed.jsonl"     # relative to the config file
      k: 2                                      # default: every example
      strategy: "round_robin"                   # fixed | random | round_robin
```

Example turns are inserted between the system message and the final user
message, alternating user/assistant; each example `input` is rendered with
`prompt.user` and each `output` is used verbatim. File-backed setups are JSONL
(`{"input": {...}, "output": "..."}` per non-empty line) and are validated
before any request is sent.

Per scheme, with `num_solutions > 1`: `greedy` walks the setups in declared
order at most once each (so its cap is the setup count), `sample` makes one
request per requested solution and keeps every one, and `rejection` keeps
generating until enough solutions pass or `max_attempts` (default
`3 * num_solutions`) is spent.

When ICL is configured or `num_solutions > 1`, `output` and `meta` become
lists: each output item carries the task's `output_field` plus `icl_setup`,
each metadata entry gains `icl_setup` and `evaluation_passed`, and `result`
becomes `{passed, failed, attempts}` counts. A task with `num_solutions: 1`
and no ICL keeps the Part 1 row format and Part 1 rejection bounds. Per-task
summaries gain `total_solutions` and `avg_solutions_per_input`.

## Agentic tasks

`generation.scheme: "agentic"` lets the model call tools in a loop before
answering:

```yaml
    generation: {scheme: "agentic", max_iterations: 10, temperature: 0.0}
    tools:
      - name: "lookup"
        description: "Look up a value in the database by key"
        parameters:
          type: "object"
          properties: {key: {type: "string"}}
          required: ["key"]
        handler:
          type: "static_map"
          mapping: {"employees": "142"}
          default: "KEY_NOT_FOUND"
```

Handlers are `echo` (the parsed arguments as a JSON string), `static_map` (the
first required parameter looked up in `mapping`, else `default`, which itself
defaults to `"NOT_FOUND"`) and `script` (`command` run with the value of
`arg_field` as one argument; stdout, or `"ERROR: ..."` on timeout or non-zero
exit). `max_iterations` defaults to 10.

Each iteration is one API request. Tool-call responses are executed, appended
to the conversation and the loop continues; a response with final text and no
tool calls ends it. Hitting `max_iterations` writes `output: null` and
`meta.finish_reason: "max_iterations"`. A row's `result` gains `iterations` and
`tool_calls` (`{iteration, tool, args, result}` per call) and `meta` becomes
`{total_prompt_tokens, total_completion_tokens, total_tokens, latency_ms,
finish_reason, iterations_detail}`. With ICL or `num_solutions > 1` the
checkpoint 3 list format applies, one loop per emitted item, and each `meta`
entry carries that loop's aggregate alongside `icl_setup` /
`evaluation_passed`.

## Completions mode

`api_type: "completions"` (config `defaults`, per task, or `--api-type`) posts
a rendered prompt string to `{api_url}/v1/completions` and reads
`choices[0].text`. `chat_template` (or `--chat-template`) picks one of
`chatml`, `llama3`, `mistral`, `zephyr`; it defaults to `chatml` and handles
multi-turn conversations by repeating each template's role markers. Agentic
tasks render their tool catalogue into the system turn and parse
`<tool_call>{"name": ..., "arguments": {...}}</tool_call>` blocks out of the
response text.

Evaluation types: `exact_match`, `contains`, `regex`, `script` (shell command,
10 s timeout), `llm_judge` (a second API call whose reply is scored against a
`threshold`). Extract methods: `full`, `last_line`, `last_number`,
`first_number`, `letter`.

## Rate limits, cost and budget

```yaml
defaults:
  rate_limits: {rpm: 100, tpm: 50000, max_concurrent: 10}
  cost: {prompt_cost_per_1k: 0.01, completion_cost_per_1k: 0.03, budget: 50.0}
tasks:
  code_gen:
    rate_limits: {tpm: 30000}        # overrides only `tpm`
    cost: {prompt_cost_per_1k: 0.005}
```

Both blocks merge from `defaults` per key, like `prompt` / `generation` /
`evaluation`. `rate_limits.rpm` supersedes the older task-level `rpm:`; with
no rpm configured anywhere, RPM limiting is off for that task. RPM and TPM are
sliding 60-second windows per task: before dispatch a request reserves
`estimated_prompt_tokens + max_tokens` (words in the rendered messages at
`1 token ~= 0.75 words`, rounded up), and the reservation is rewritten to the
response's real `prompt_tokens + completion_tokens`. `max_concurrent` caps
in-flight requests independently; an agentic loop holds one slot for its whole
lifetime while each of its requests still paces against RPM and TPM. Judge
calls go through the same limiter.

Cost is `prompt_tokens/1000 * prompt_cost_per_1k + completion_tokens/1000 *
completion_cost_per_1k` per call, judge calls and agentic iterations included,
and is reported to four decimals in `summary.cost` (omitted when no cost block
is configured). When the running total reaches `budget` the run stops
scheduling requests, lets in-flight work finish, writes what completed, prints
the summary with `cost.budget_exceeded: true` and exits `0`.

Flags: `--tpm`, `--max-concurrent`, `--budget`.

## Structured output

```yaml
    output_schema:
      type: "object"
      required: ["code", "explanation"]
      properties: {code: {type: "string"}, explanation: {type: "string"}}
```

The response is parsed as JSON and checked against a JSON Schema draft 7
subset (`type`, `required`, `properties`, `items`, `enum`, `minimum`,
`maximum`, `minLength`, `maxLength`, `pattern`) before any evaluation runs;
invalid JSON is a schema failure. On success the parsed value — not the raw
string — is stored under `output_field` and `result.schema_valid` is `true`.
On failure a non-rejection row gets `output: null`, `schema_valid: false` and a
`schema_error` message, and evaluation is skipped. For `rejection` a schema
failure is just a failed attempt, and `output_schema` alone satisfies that
scheme's accept test when no `evaluation` block is configured.

## Resume, dry run and progress

`--resume` skips the leading input rows already present in the output file
(per task file for multi-task configs) and appends the rest; a prior row with
fewer passing solutions than `num_solutions` — including a rejection row that
produced none — is reprocessed, and the file is truncated there. The summary
covers only the new rows and carries `resumed_from`.

`--dry-run` validates the config and inputs, makes no API calls, and prints an
estimate (`inputs`, `est_prompt_tokens` from `average prompt word count *
1.33`, `est_completion_tokens`, `est_total_tokens`, `est_cost` per task, plus
run totals and `est_time_minutes`) to stdout before exiting `0`.

`--progress` writes updates to stderr every 5 seconds or every 10% of total
inputs:

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The passed/failed field appears only with evaluation (or a schema) configured
and the spend field only with cost tracking.

Exit codes: `0` success, `1` configuration or input error. One JSON result
object is written per input row (in input order, per task) and a single JSON
summary is printed to stdout; multi-task runs add a `tasks` object to it.

Requests are issued concurrently across all executed tasks on one event loop:
the in-flight budget is sized from the configured `rpm` and capped by the work
available.

## Tests

```bash
.venv/bin/python -m pytest
```

Tests are organised phrase-by-phrase against the spec — `tests/test_spec.py`
for Part 1, `tests/test_spec_part2.py` for Part 2,
`tests/test_spec_part3.py` for Part 3, `tests/test_spec_part4.py` for Part 4
and `tests/test_spec_part5.py` for Part 5. `tests/conftest.py`
provides a threaded mock API server (configurable per-request status, body and
delay), subprocess CLI runners for both config shapes, and a background runner
for observing the rate limiter mid-flight.

Interpretation decisions for under-specified behaviour are recorded in
`AMBIGUITIES.md`.
