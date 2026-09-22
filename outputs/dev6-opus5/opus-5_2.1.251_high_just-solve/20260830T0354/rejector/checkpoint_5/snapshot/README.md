# rejector

A CLI that reads a YAML task config plus JSONL input, sends prompts to an
OpenAI-compatible chat completions API concurrently, and writes one JSONL result
per input row. A config can hold a single task or many named tasks that run
together.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

Single-task config -> one input file, one output file:

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Multi-task config -> one input per task, one output file per task in a directory.
Either map inputs explicitly or point at a directory of `<task_name>.jsonl`:

```bash
.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/
```

The two input modes are alternatives; combining them is an error.

`--task <name>` (repeatable) restricts the run to the named tasks. Unselected
tasks are skipped entirely: they need no input file, are not validated, and get
no output file.

```bash
.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --output results/ --task gsm8k
```

Optional overrides, each replacing the matching config value for every task that
runs: `--api-url`, `--model`, `--rpm`, `--tpm`, `--max-concurrent`, `--budget`,
`--max-tokens`, `--scheme`, `--temperature`, `--n`, `--num-solutions`,
`--icl-strategy`, `--icl-k`, `--api-type`, `--chat-template`,
`--max-iterations`, and `--eval-model` (the judge model for `llm_judge` tasks).

Run modifiers: `--resume` continues an interrupted run, `--dry-run` prints an
estimate without sending anything, and `--progress` reports to stderr while the
run is going.

Exit codes: `0` on success, `1` on a configuration or input error (message on stderr).
A run that stops because it hit its cost `budget` still exits `0`.

## Config

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60
  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"
  generation:
    scheme: "greedy"      # greedy | sample | rejection | agentic
    temperature: 0.0
    max_tokens: 512
    n: 1
  evaluation:
    type: "exact_match"   # exact_match | contains | regex
    answer_field: "answer"
    extract: "last_number"  # last_number | last_line | full
  output_field: "solution"
```

### Multi-task config

`defaults` supplies shared values and `tasks` maps a name to each task. Every
required field may come from either side, and nested sections (`prompt`,
`generation`, `evaluation`) are merged key by key with the task winning.

```yaml
defaults:
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60
  generation:
    max_tokens: 512

tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem step by step. Put your final answer after ####."
      user: "{question}"
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"

  review:
    prompt:
      system: "You are a writing assistant. Write a response to the given prompt."
      user: "{prompt_text}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
        user: "Rate the quality of this response.\n\nResponse:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"
```

A config with a top-level `task` key is the single-task format above; its task
name is `task.name`.

### Notes

- `greedy` forces `temperature: 0.0` and ignores `n`.
- `agentic` ignores `n` and is bounded by `generation.max_iterations`
  (see [Agentic generation](#agentic-generation)).
- `sample` and `rejection` require `temperature > 0`; `sample` ignores `n`.
- `rejection` makes up to `n` attempts and keeps the first response that passes
  evaluation; if none pass, `output` is `null` and `result.passed` is `false`.
  With ICL or `num_solutions > 1`, `generation.max_attempts` takes over from `n`
  (see [Multiple solutions](#multiple-solutions)).
- `evaluation` is required for `rejection` and optional otherwise - an
  `output_schema` satisfies that requirement on its own. Without either,
  `result.passed` is `null`.

### Extraction methods

| `extract` | takes |
| --- | --- |
| `full` | the whole response, stripped |
| `last_line` | the last non-blank line |
| `last_number` | the last integer or decimal |
| `first_number` | the first integer or decimal |
| `letter` | the first standalone `A`-`D`, so `A`, `(A)`, `A)` and `Answer: A` all give `A` |

### Evaluation types

`exact_match`, `contains` and `regex` work on the response text as in Part 1.

`llm_judge` scores the response with a second API call through the same server:

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7
  extract: "first_number"
  model: "gpt-4"        # optional; defaults to the task's model
```

`judge_prompt` follows the normal template rules, plus `{__response__}` for the
generated text. The extracted score lands in `result.judge_score` and passes
when it is `>= threshold`; the judge call's own usage, latency, model and finish
reason land in `meta.judge_meta`. Judge calls count toward throughput,
`total_api_calls` and the task's API call total, and are paced and interleaved
alongside every other request.

`script` runs a shell command and checks its exit code:

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

`command_template` may reference row fields and `{__response__}`. When a row
field expands to text that itself contains `{__response__}` - a `test_code`
column carrying its own harness, say - that placeholder is substituted before
the command runs. Exiting with `success_exit_code` passes; anything else fails.
Command output is captured (so a chatty script cannot deadlock on a full pipe)
but never written to the JSONL. Commands run in their own process group and are
killed after 10 seconds, which counts as a failed evaluation.

## In-context learning

A task may carry named ICL setups. Each setup is inserted between the system
message and the real user message as alternating user/assistant turns: every
example's `input` is rendered with the task's own `prompt.user` template and its
`output` becomes the assistant reply verbatim.

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
        - name: "direct"
          examples:
            - input: {question: "What is 2+2?"}
              output: "#### 4"
        - name: "detailed"
          file: "icl/gsm8k_detailed.jsonl"
      k: 2
      strategy: "round_robin"
```

Each setup needs a `name` and exactly one of `examples` or `file`. A `file` path
is resolved against the config file's directory and must be JSONL whose non-empty
lines each look like:

```jsonl
{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"}
```

A malformed line, or one missing `input`/`output`, ends the run with exit code 1
before any request is sent.

`icl.k` caps how many of the setup's examples are used, taking the first `k`; it
defaults to all of them. `icl.strategy` picks which setup an attempt uses:

| `strategy` | picks |
| --- | --- |
| `fixed` | the first setup, every attempt |
| `random` | an independently chosen setup per attempt |
| `round_robin` | the setups in order, cycling: `A B C A B ...` |

`greedy` with ICL and `num_solutions > 1` is the one exception: it ignores the
strategy and walks the setups in declared order, using each at most once.

## Multiple solutions

`num_solutions` asks for more than one solution per input row. It may live in
`defaults` or on a task, and `--num-solutions` overrides both.

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

How each scheme collects them:

| scheme | with ICL | without ICL |
| --- | --- | --- |
| `greedy` | one `temperature: 0` call per setup, in declared order, stopping at `num_solutions` or when the setups run out | a single deterministic call |
| `sample` | one sampled call per requested solution, choosing a setup by `icl.strategy`; evaluation does not gate inclusion | `num_solutions` independent sampled calls |
| `rejection` | keeps generating and evaluating until `num_solutions` pass or `max_attempts` is spent | the same, with the same prompt every attempt |

Because a greedy setup is deterministic, greedy can never produce more solutions
than there are setups - two setups with `num_solutions: 5` yield two solutions,
and no setup is retried to manufacture more.

`generation.max_attempts` bounds rejection sampling and defaults to
`3 * num_solutions`. As a compatibility carve-out, a task with
`num_solutions: 1` and no ICL keeps the Part 1 rejection behaviour exactly:
`generation.n` logical attempts, and `max_attempts` is ignored.

## Agentic generation

`scheme: "agentic"` lets the model call the task's tools in a loop before it
answers. Each loop is: send the conversation, run whatever tools the response
asks for, append the results, and go again until the model replies with plain
text or `generation.max_iterations` API requests have been spent (default 10).

```yaml
tasks:
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools to answer questions."
      user: "{question}"
    generation:
      scheme: "agentic"
      max_iterations: 10
      temperature: 0.0
      max_tokens: 512
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "answer"
    tools:
      - name: "lookup"
        description: "Look up a value in the database by key"
        parameters:
          type: "object"
          properties:
            key:
              type: "string"
              description: "The database key to look up"
          required: ["key"]
        handler:
          type: "static_map"
          mapping:
            "revenue_q1": "1250000"
            "revenue_q2": "1480000"
          default: "KEY_NOT_FOUND"
```

In chat mode the tools travel in the request body as OpenAI `tools` entries and
tool calls come back in `choices[0].message.tool_calls`; `function.arguments` is
parsed as JSON before the handler runs. Every call in one response is executed,
in order, and all of them are recorded against that iteration.

### Handlers

| `handler.type` | returns |
| --- | --- |
| `echo` | the parsed arguments as a JSON string |
| `static_map` | `mapping[<first required parameter>]`, else `default` (itself defaulting to `"NOT_FOUND"`) |
| `script` | the stdout of `command` run with the `arg_field` value as a single argument |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

A `script` handler that times out (10 seconds) or exits non-zero returns
`"ERROR: <stderr or timeout message>"` instead of stdout, so the model sees the
failure and can keep going. A call to a tool the task does not define comes back
as `"ERROR: unknown tool ..."`.

Each request inside a loop counts separately toward `total_api_calls` and the
throughput budget, and loops from different rows interleave freely: a row
waiting on a tool never blocks another row's request.

### Agentic output

```json
{
  "input": {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"},
  "output": {"answer": "The total revenue for Q1 and Q2 is $2,730,000."},
  "result": {
    "passed": true, "extracted_answer": "2730000", "attempts": 1, "iterations": 3,
    "tool_calls": [
      {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
      {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"}
    ]
  },
  "meta": {
    "total_prompt_tokens": 850, "total_completion_tokens": 120, "total_tokens": 970,
    "latency_ms": 1200, "finish_reason": "stop",
    "iterations_detail": [
      {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230, "latency_ms": 300, "finish_reason": "tool_calls"},
      {"prompt_tokens": 350, "completion_tokens": 40, "total_tokens": 390, "latency_ms": 400, "finish_reason": "tool_calls"},
      {"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350, "latency_ms": 500, "finish_reason": "stop"}
    ]
  }
}
```

`result.iterations` is the number of API requests the loop made and
`result.tool_calls` lists every call in execution order. `meta` aggregates the
whole loop: token totals across iterations, wall-clock `latency_ms` for the
loop, and one `iterations_detail` entry per request. `meta.finish_reason` is
`"stop"` for a final text answer and `"max_iterations"` when the limit ran out -
in which case `output` is `null`, so evaluation fails.

Only the final text is evaluated. With ICL or `num_solutions > 1` each solution
is an independent loop and the row keeps the list format below: `result.attempts`
counts loops (not requests), and every `meta` entry carries that loop's
`icl_setup` and `evaluation_passed` alongside its aggregated totals,
`finish_reason` and `iterations_detail`.

## Completions mode

`api_type: "completions"` posts to `{api_url}/v1/completions` with a single
rendered `prompt` string instead of a messages array, and reads the reply from
`choices[0].text`.

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"

tasks:
  gsm8k:
    api_type: "completions"
    chat_template: "chatml"
```

`--api-type <chat|completions>` and `--chat-template <chatml|llama3|mistral|zephyr>`
override the config for every task that runs:

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl \
    --api-type completions --chat-template llama3
```

The request sends `prompt`, `temperature`, `max_tokens` and `model`. The four
built-in templates repeat their role markers for every message, so ICL turns,
agentic tool results and any other multi-turn conversation render correctly:

| `chat_template` | one turn looks like |
| --- | --- |
| `chatml` | `<\|im_start\|>{role}\n{content}<\|im_end\|>\n`, closing with `<\|im_start\|>assistant\n` |
| `llama3` | `<\|start_header_id\|>{role}<\|end_header_id\|>\n\n{content}<\|eot_id\|>` after a leading `<\|begin_of_text\|>` |
| `mistral` | `[INST] {content} [/INST]` per user turn, system text folded into the next user turn |
| `zephyr` | `<\|{role}\|>\n{content}</s>\n`, closing with `<\|assistant\|>\n` |

Agentic tasks work in completions mode too. There is no native `tools` field, so
the tool definitions are described in the system block and the model asks for a
call by emitting

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

Those blocks are parsed out of the response text, executed, and fed back as
tool-role turns in the next rendered prompt.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"solution": "..."}, "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {"model": "gpt-4", "prompt_tokens": 45, "completion_tokens": 120, "total_tokens": 165, "latency_ms": 230, "finish_reason": "stop"}}
```

`meta` is a single object for one-attempt rows and a list (one entry per attempt)
for rejection rows that took more than one attempt. For `llm_judge` tasks each
attempt's `meta` carries a `judge_meta` object and `result` carries
`judge_score`.

### Rows with ICL or multiple solutions

As soon as a task configures `icl` or sets `num_solutions > 1`, the row format
switches: `output` becomes a list, and `meta` is always a list with one entry per
attempt. A task with `num_solutions: 1` and no ICL keeps the format above.

```json
{
  "input": {"question": "What is 15 + 27?", "answer": "42"},
  "output": [
    {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
    {"solution": "#### 42", "icl_setup": "direct"}
  ],
  "result": {"passed": 2, "failed": 5, "attempts": 7},
  "meta": [
    {"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15, "total_tokens": 95,
     "latency_ms": 200, "finish_reason": "stop", "icl_setup": "chain_of_thought",
     "evaluation_passed": true}
  ]
}
```

Each output item holds the task's `output_field` plus the `icl_setup` that
produced it, which is `null` when the task has no ICL. `result.attempts` counts
every generation attempt for the row, `result.passed` counts the passing
solutions and `result.failed` is the rest. When `evaluation` is omitted,
`evaluation_passed` is `null` on every entry, `result.passed` is the number of
emitted outputs and `result.failed` is the number of attempts that produced
none.

Rejection stops early once it has `num_solutions` passing solutions, and writes
whatever it collected if `max_attempts` runs out first - `num_solutions: 5` with
`max_attempts: 10` and only two passes reports `passed: 2`, `failed: 8`,
`attempts: 10`.

Multi-task runs write `<output_dir>/<task_name>.jsonl` per executed task; row
order within each file matches its input file.

A JSON summary is printed to stdout when the run finishes. For multi-task
configs it also carries a `tasks` object holding the tasks that actually ran:

```json
{
  "total": 200, "passed": 170, "failed": 30,
  "total_prompt_tokens": 9000, "total_completion_tokens": 24000,
  "total_api_calls": 350, "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
  "tasks": {
    "gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
              "avg_solutions_per_input": 4.5, "total_api_calls": 142},
    "review": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 100,
               "avg_solutions_per_input": 1.0, "total_api_calls": 208}
  }
}
```

A task's `total_solutions` is how many output items it wrote in total and
`avg_solutions_per_input` divides that by its row count. A row counts as
`passed` when it produced at least one passing solution. The run-wide summary
gains the same two fields whenever any row used the list format, a `cost` object
whenever [cost tracking](#cost-tracking) is configured, and `resumed_from`
whenever the run was started with [`--resume`](#resume).

## Rate limits

`rate_limits` bounds a task three ways at once. In a multi-task config it lives
under `defaults` and merges into each task key by key, exactly like `prompt`,
`generation` and `evaluation`, so a task overriding one key keeps the rest.

```yaml
defaults:
  rate_limits:
    rpm: 100
    tpm: 50000
    max_concurrent: 10

tasks:
  code_gen:
    rate_limits:
      tpm: 30000        # rpm and max_concurrent still come from defaults
```

`--tpm` and `--max-concurrent` (and `--rpm`, from Part 1) override the config
for every task that runs.

| limit | means |
| --- | --- |
| `rpm` | at most this many requests in any sliding 60-second window |
| `tpm` | at most this many tokens in any sliding 60-second window |
| `max_concurrent` | a hard cap on requests in flight, independent of the other two |

Omitting `rpm` disables request-rate limiting for that task; omitting `tpm`
disables the token budget. When both are set a request goes out only once both
have room for it.

Before a request is sent its prompt is estimated by counting words in the
rendered messages at `1 token ~= 0.75 words`, rounded up, and
`estimated_prompt_tokens + max_tokens` is reserved against the token window.
When the response comes back the reservation is replaced by the actual
`prompt_tokens + completion_tokens` the API reported, so an over- or
under-estimate is corrected within the same window rather than compounding.

Every request is metered: each `llm_judge` call, each rejection attempt, and
each iteration of an agentic loop. An agentic loop holds a single concurrency
slot for its whole lifetime, so a loop waiting on a tool never releases its slot
mid-conversation, while its individual requests still count separately toward
`rpm` and `tpm`.

Admission is first come, first served, so rows are dispatched in input order and
each row is still paired with its own response no matter how much the requests
overlap.

Tasks pointed at the same `api_url` share one set of windows and one
concurrency cap, which keeps the limits a budget for that server rather than a
per-task multiplier; a task that configures something stricter also gets a
private window of its own on top.

## Cost tracking

`cost` prices a task's tokens. Like `rate_limits`, it merges out of `defaults`
key by key.

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

Each API call costs
`(prompt_tokens / 1000 * prompt_cost_per_1k) + (completion_tokens / 1000 * completion_cost_per_1k)`,
counted across every task and including judge calls and every agentic
iteration. `--budget <float>` overrides the configured budget.

```json
{
  "cost": {
    "total": 12.45, "prompt": 4.50, "completion": 7.95,
    "budget": 50.0, "budget_remaining": 37.55, "budget_exceeded": false
  }
}
```

When the running total reaches the budget the run stops scheduling new requests
immediately, lets what is in flight finish, writes the completed rows, prints
the summary with `budget_exceeded: true` and exits `0`. Budget exhaustion is not
an error and the partial output is valid: rows that never started are simply not
written, so the output stays a prefix of the input and `--resume` picks up
exactly where the run stopped. With no cost configuration at all the `cost`
field is left out of the summary.

## Structured output

`output_schema` makes a task require JSON that satisfies a schema.

```yaml
tasks:
  code_gen:
    output_schema:
      type: "object"
      required: ["code", "explanation"]
      properties:
        code:
          type: "string"
        explanation:
          type: "string"
```

The response is parsed as JSON and validated before anything else runs;
unparseable JSON is a schema failure like any other. The supported JSON Schema
draft 7 keywords are `type`, `required`, `properties`, `items`, `enum`,
`minimum`, `maximum`, `minLength`, `maxLength` and `pattern`, nested to any
depth.

On success the parsed JSON value - not the raw response string - is what lands
in the row's `output`:

```json
{
  "output": {"code": {"code": "def add(a, b): return a + b",
                      "explanation": "Simple addition function"}},
  "result": {"passed": true, "schema_valid": true}
}
```

On failure the row keeps `output: null`:

```json
{
  "output": null,
  "result": {"passed": false, "schema_valid": false,
             "schema_error": "Missing required field: explanation"}
}
```

For `greedy` and `sample` a schema failure sets `result.passed` to `false`. For
`rejection` it is just a failed attempt and the next one is tried; a schema is
enough to drive rejection sampling even with no `evaluation` block at all. When
both are configured the schema runs first and evaluation is skipped entirely if
it fails.

## Resume

`--resume` continues a run whose output file already exists. Rows are matched by
input row index - outputs are written in input order, so the existing line count
is the number of leading rows to skip - and new rows are appended after them. In
a multi-task run each task's output file resumes independently.

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl --resume
```

A prior row that stopped short of what it was asked for - a multi-solution or
rejection row with fewer passing solutions than `num_solutions` and attempts to
spare - is not skipped; the run redoes it from scratch and continues from there.
A row that spent its whole attempt budget is finished even if nothing passed.

The summary covers only the newly processed rows and reports how many were
skipped:

```json
{"total": 50, "resumed_from": 50, "passed": 42, "failed": 8}
```

## Dry run

`--dry-run` validates the config and every input file, then prints an estimate
and exits `0` without sending a single request. Prompt tokens are estimated as
`average prompt word count * 1.33`, completion tokens as `max_tokens` per row,
and cost from the configured rates. `est_time_minutes` is
`total_inputs * avg_attempts / rpm`, where `avg_attempts` is `1` for `greedy`
and `sample` and the attempt ceiling for `rejection` worst-case planning.

```json
{
  "tasks": {
    "gsm8k": {"inputs": 1000, "est_prompt_tokens": 45000,
              "est_completion_tokens": 512000, "est_total_tokens": 557000,
              "est_cost": 20.31}
  },
  "total_inputs": 1000, "est_total_tokens": 557000,
  "est_total_cost": 20.31, "est_time_minutes": 9.3
}
```

## Progress reporting

`--progress` prints to stderr every 5 seconds or every 10% of the total input
rows, whichever comes first. stdout still carries nothing but the final summary.

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The `passed` / `failed` field appears only when the run can actually fail a row
(an `evaluation` or an `output_schema`), and `$... spent` only when cost
tracking is configured.

## Concurrency

Requests are issued concurrently. The sliding 60-second windows described under
[Rate limits](#rate-limits) are the hard guarantee; alongside each one a leaky
bucket does the pacing, so a run issues steadily at the configured rate instead
of firing a whole minute's budget at once and then stalling. Each bucket's
capacity — how much it will allow in flight — starts small and grows with
observed latency (Little's law: sustaining `rate` per second against `L`-second
requests needs `rate * L` in flight). That fills the pipeline once, then holds
the steady-state issue rate at roughly the configured budget. `5xx` responses are
retried up to 3 times; retries count toward `total_api_calls` but not toward
`result.attempts`.

Every task in a multi-task run shares one transport and one event loop, so rows
from different tasks are issued concurrently and interleave freely.

## Tests

```bash
.venv/bin/python tests/run_tests.py
```

Spins up a mock OpenAI-compatible server (`tests/mock_server.py`) that queues
requests with a bounded worker pool, and exercises the schemes, evaluation types,
extraction methods, ICL setups and strategies, multi-solution collection,
agentic tool loops and handlers, completions-mode templates, retry behaviour,
validation errors, throughput, RPM/TPM/concurrency limits, cost and budget
accounting, structured output validation, resume, dry-run estimates and
progress reporting.
