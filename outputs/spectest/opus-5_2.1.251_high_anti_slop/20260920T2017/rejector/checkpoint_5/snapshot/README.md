# rejector

A CLI that runs YAML-configured generation tasks over JSONL input files
against an OpenAI-compatible API, evaluates each response, and writes one
JSONL result per input row. Tasks can sample, reject-sample, or call tools in
an agentic loop, against either the chat or the text completions endpoint.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

One task, one input file, one output file:

```bash
.venv/bin/python rejector.py run \
    --config examples/task.yaml \
    --input examples/data.jsonl \
    --output results.jsonl
```

Several tasks in one config, each with its own input file and its own
`<output_dir>/<task>.jsonl`:

```bash
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input gsm8k=examples/data/gsm8k.jsonl --input mmlu=examples/data/mmlu.jsonl \
    --output results/

.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input-dir examples/data --output results/ --task gsm8k
```

An agentic task with its tools, run the same way (see `examples/agentic.yaml`):

```bash
.venv/bin/python rejector.py run --config examples/agentic.yaml \
    --input examples/data/lookup.jsonl --output results.jsonl
```

A task whose responses must be JSON, validated against a schema (see
`examples/structured.yaml`):

```bash
.venv/bin/python rejector.py run --config examples/structured.yaml \
    --input examples/data/structured.jsonl --output results.jsonl
```

`--input` and `--input-dir` are alternative ways to find inputs and cannot be
combined; `--input-dir` looks for `<task_name>.jsonl`. `--task` is repeatable
and limits the run to the tasks it names — other tasks are neither validated
nor given an input.

`--api-url`, `--model`, `--rpm`, `--tpm`, `--max-concurrent`, `--budget`,
`--max-tokens`, `--scheme`, `--temperature`, `--n`, `--eval-model`,
`--num-solutions`, `--icl-strategy`, `--icl-k`, `--api-type` and
`--chat-template` override the matching config values for every task that runs.
`--icl-strategy` and `--icl-k` only reach tasks that configure ICL, as
`--eval-model` only reaches tasks that evaluate.

`--resume` continues a run that was interrupted, `--dry-run` estimates a run
instead of making it, and `--progress` reports on a run while it is in flight.
The command exits `0` on success and `1` on a configuration or input error;
a run stopped by its cost budget still exits `0`.

## Configuration

A single-task config is one `task` mapping (see `examples/task.yaml`). A
multi-task config is a `defaults` mapping plus a `tasks` mapping keyed by task
name (see `examples/multi.yaml`); each task is layered onto `defaults`, with
nested sections such as `prompt`, `generation`, `evaluation`, `rate_limits` and
`cost` merged key by key. Required fields may come from either layer.

## Evaluation

| Type | Passes when |
| --- | --- |
| `exact_match` | the extracted answer equals the row's `answer_field`. |
| `contains` | the row's `answer_field` appears in the response. |
| `regex` | `pattern` matches the response. |
| `script` | the rendered `command_template` exits with `success_exit_code`. |
| `llm_judge` | the judge's score is `>= threshold`. |

`extract` picks the value an answer is compared as: `last_number`,
`first_number`, `last_line`, `letter` (an `A`-`D` multiple choice answer) or
`full`.

A `script` command is rendered from the input row and run in a shell, with a
10 second timeout. Both the template and any row field it expands may use
`{__response__}` for the generated text:

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

An `llm_judge` scores the response with a second API call, made through the
same server with `evaluation.model` (the task's model by default). The row's
`result` carries the `judge_score` and its `meta` carries a `judge_meta`
object for that call; judge calls count towards the run's API totals.

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7
  extract: "first_number"
```

## Generation schemes

A task asking for a single solution and no ICL examples behaves as before:

| Scheme | Behaviour |
| --- | --- |
| `greedy` | One attempt at `temperature` 0.0; `n` is ignored. |
| `sample` | One attempt at the configured `temperature` (must be > 0); `n` is ignored. |
| `rejection` | Up to `n` attempts, keeping the first that passes. Requires an `evaluation` block or an `output_schema` to reject on. |
| `agentic` | One tool-calling loop, of up to `max_iterations` API requests. |

Rows that never produce a passing response are written with `"output": null`
and `"passed": false`.

## In-context learning

A task may prompt with named sets of examples. Each setup lists its examples
inline or names a JSONL file, whose path is relative to the config file:

```yaml
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

```jsonl
{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"}
```

A setup has a `name` and exactly one of `examples` or `file`. Every non-empty
line of a file must be an object with an object `input` and a string `output`;
a malformed line ends the run with exit code 1 before any request is sent.

The chosen setup's examples sit between the system message and the row's own
user message as alternating user and assistant turns. Each example's `input` is
rendered with the task's `prompt.user` template and its `output` is used
verbatim. `k` caps how many of a setup's examples are shown, taking the first
`k`; it defaults to all of them.

`strategy` decides which setup an attempt uses: `fixed` always takes the first,
`random` draws one per attempt, and `round_robin` cycles through them in order,
so three setups are used `A`, `B`, `C`, `A`, `B` across five attempts.

## Multiple solutions

`num_solutions` asks for several solutions per input row, in `defaults` or on a
single task:

```yaml
generation:
  scheme: "rejection"
  temperature: 0.7
  max_attempts: 15
num_solutions: 5
```

| Scheme | Behaviour |
| --- | --- |
| `greedy` | One attempt per setup, in declared order, stopping at `num_solutions`. Deterministic, so a task can produce no more solutions than it has setups — one without ICL produces one. |
| `sample` | One sampled attempt per requested solution, each using the ICL strategy. The evaluation does not gate which are kept. |
| `rejection` | Attempts until `num_solutions` responses pass the evaluation or `max_attempts` is spent; only passing responses are kept. |

`max_attempts` bounds rejection sampling and defaults to `3 * num_solutions`. A
task that asks for one solution and configures no ICL keeps using `n` instead.

## Results

One JSON object per input row. A task with no ICL that asks for a single
solution writes the original format: an `output` object, a `result` holding
`passed`, `extracted_answer` and `attempts`, and one `meta` object per row.

Configuring ICL or asking for more than one solution switches the row to the
list format, where `output` holds one object per solution and `meta` one entry
per attempt:

```json
{"input": {"question": "What is 15 + 27?", "answer": "42"},
 "output": [{"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
            {"solution": "#### 42", "icl_setup": "direct"}],
 "result": {"passed": 2, "failed": 5, "attempts": 7},
 "meta": [{"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
           "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
           "icl_setup": "chain_of_thought", "evaluation_passed": true}]}
```

`icl_setup` names the setup an attempt used, and is `null` when the task
configures no ICL. `result.attempts` counts every generation the row made,
`passed` those the evaluation accepted, and `failed` the rest. Without an
evaluation, `evaluation_passed` is `null` and `passed` counts the solutions
that were written.

## Agentic generation

An `agentic` task lets the model call tools before it answers. Each pass
through the loop is one API request: a response holding tool calls is answered
with their results and the loop goes round again, while a response holding only
text ends it. `max_iterations` caps the requests one loop may make and defaults
to 10.

```yaml
generation:
  scheme: "agentic"
  max_iterations: 10
  temperature: 0.0
  max_tokens: 512

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
        "employees": "142"
      default: "KEY_NOT_FOUND"
```

`parameters` is the JSON schema the model is shown, and `handler` is what runs
when the tool is called:

| Handler | Result |
| --- | --- |
| `echo` | the parsed arguments, as a JSON string. |
| `static_map` | `mapping[<first required parameter>]`, or `default` (`"NOT_FOUND"` if unset). |
| `script` | the stdout of `command` run with the value of `arg_field` as its single argument. |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

A script that fails, or outlives the 10 second timeout, returns
`"ERROR: <reason>"` to the model rather than ending the run, as does a call to
a tool the task does not declare. Every tool call of one response is executed,
and each iteration's requests count towards the run's API totals.

`agentic` combines with ICL and `num_solutions`; each solution is an
independent loop. Rows stay concurrent throughout, so the loops of different
rows overlap in flight rather than taking turns.

### Agentic results

A single-solution row keeps the part 1 format, with the loop's own fields added
to `result` and its aggregated counters in `meta`:

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

`result.iterations` counts the loop's API requests and `result.tool_calls`
records every call in execution order. `meta.latency_ms` is the wall-clock time
of the whole loop and `meta.iterations_detail` holds one entry per request.

A loop that reaches `max_iterations` writes `"output": null` and
`"finish_reason": "max_iterations"`; with nothing to judge, its evaluation
fails. Evaluation always runs against the final text alone.

ICL or `num_solutions > 1` switches the row to the list format, where each
emitted output is one completed loop and `result.attempts` counts the loops
started, not the requests they made. Each `meta` entry keeps its `icl_setup`
and `evaluation_passed` alongside that loop's aggregated counters.

## Completions mode

`api_type` picks the endpoint a task posts to, and `chat_template` the markup a
`completions` task renders its conversation with. Both may sit in `defaults`,
on a single task, or come from `--api-type` and `--chat-template`:

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"
```

```bash
.venv/bin/python rejector.py run --config examples/task.yaml \
    --input examples/data.jsonl --output results.jsonl \
    --api-type completions --chat-template llama3
```

A `chat` task posts a messages array to `/v1/chat/completions` and reads
`choices[].message`. A `completions` task posts `prompt`, `temperature`,
`max_tokens` and `model` to `/v1/completions` and reads `choices[].text`.

`chat_template` is one of `chatml`, `llama3`, `mistral` or `zephyr`. Each
repeats its role markers for every message, so multi-turn conversations, ICL
examples and tool results are all marked up correctly.

An agentic task in completions mode has no `tools` field to send, so the tool
definitions are appended to the system message and the model is asked to reply
with a block the loop parses back out:

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

Results are fed back as `tool` messages, which the template renders with its
own role markers.

## Rate limits

Each task paces itself against its own budgets, in `defaults` or on a single
task, and `--rpm`, `--tpm` and `--max-concurrent` override them:

```yaml
defaults:
  rate_limits:
    rpm: 100
    tpm: 50000
    max_concurrent: 10

tasks:
  code_gen:
    rate_limits:
      tpm: 30000
```

| Budget | Effect |
| --- | --- |
| `rpm` | requests per sliding 60-second window; omitted, requests are not limited. |
| `tpm` | tokens per sliding 60-second window. |
| `max_concurrent` | units of work in flight, independent of `rpm` and `tpm`. |

A task-level `rpm`, as configs wrote it before `rate_limits` existed, is still
read as the default for `rate_limits.rpm`.

A request is sent once every configured budget has room for it, so the tighter
of `rpm` and `tpm` is what a run settles at: with `rpm: 600`, `tpm: 10000` and
requests of about 612 tokens, the token budget binds and the run paces at about
16 requests a minute rather than 600.

Before a request is sent, its prompt is estimated at `1 token ~= 0.75 words`
over the rendered messages, and `estimated_prompt_tokens + max_tokens` is
booked in the token window. Once the response arrives, the booking is replaced
by the `prompt_tokens + completion_tokens` it actually reported, which frees
whatever the estimate over-reserved.

A unit of work holds one `max_concurrent` slot: a single request, or a whole
agentic loop, which keeps its slot across every iteration it makes. Judge calls
are paced and counted like any other request. Rows stay paired with their
outputs in input order however much their requests overlap.

## Cost tracking

Token prices and a budget may sit in `defaults` or on a single task, and
`--budget` overrides the budget:

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

Every API call costs
`prompt_tokens / 1000 * prompt_cost_per_1k + completion_tokens / 1000 *
completion_cost_per_1k` at its own task's rates, judge calls and agentic
iterations included. The totals are shared by the whole run, and the run's
budget is the lowest any task sets.

Once the running total reaches the budget, no further request is sent: the
requests already in flight finish, the rows that finished are written, the
summary is printed, and the command exits `0`. Budget exhaustion is not an
error, and partial output is valid — the rows written are the leading run of
finished rows, so `--resume` picks up exactly where the budget ran out.

## Structured output

A task may require its responses to be JSON matching a schema:

```yaml
output_schema:
  type: "object"
  required: ["code", "explanation"]
  properties:
    code:
      type: "string"
    explanation:
      type: "string"
```

The supported JSON Schema draft 7 keywords are `type`, `required`,
`properties`, `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`
and `pattern`.

Validation runs before any evaluation, and a response that fails it is not
evaluated at all. Text that is not JSON fails the same way as JSON that does
not match. A valid response records its parsed value rather than the raw text:

```json
{"output": {"code": {"code": "def add(a, b): return a + b",
                     "explanation": "Simple addition function"}},
 "result": {"passed": true, "extracted_answer": null, "attempts": 1,
            "schema_valid": true}}
```

```json
{"output": null,
 "result": {"passed": false, "extracted_answer": null, "attempts": 1,
            "schema_valid": false,
            "schema_error": "Missing required field: explanation"}}
```

For `greedy` and `sample`, a schema failure fails the row. For `rejection` it
is a failed attempt like any other and the row tries again, which lets a
rejection task reject on its schema alone, with no `evaluation` block at all.

## Resume

`--resume` continues a run whose output file already exists. Rows are written
in input order, so the finished rows at the front of the file are the input rows
the new run skips; it appends its own rows after them. A row asking for several
solutions counts as unfinished while it holds fewer than `num_solutions`, as
does a half-written line, and everything from the first unfinished row on is
run again.

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl \
    --output results.jsonl --resume
```

Each task of a multi-task config resumes from its own output file. The summary
covers only the rows the new run processed, and reports how many it skipped as
`resumed_from`.

## Dry run

`--dry-run` validates the config and the inputs, counts the rows, and prints an
estimate to stdout without sending a request:

```json
{"tasks": {"gsm8k": {"inputs": 1000, "est_prompt_tokens": 45000,
                     "est_completion_tokens": 512000,
                     "est_total_tokens": 557000, "est_cost": 20.31}},
 "total_inputs": 1000, "est_total_tokens": 557000, "est_total_cost": 20.31,
 "est_time_minutes": 9.3}
```

A row's prompt is estimated at `average prompt word count * 1.33` tokens and
its completion at `max_tokens`, priced at the task's own rates. The time
estimate is `inputs * attempts / rpm`, counting one attempt a row for `greedy`
and `sample`, the worst case for `rejection`, and `max_iterations` for
`agentic`; tasks run at the same time, so the run is estimated at its slowest
task, and a task with no `rpm` to pace it is left out.

## Progress reporting

`--progress` reports to stderr every five seconds, or every tenth of the run's
rows, whichever comes first:

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The verdict field is only shown when the run has something judging its rows,
and the cost field only when it tracks cost.

## Summary

A run prints a JSON summary to stdout. A multi-task run adds a `tasks` object
holding the same counts for each task that ran, including the API calls its
judge made:

```json
{"total": 200, "passed": 170, "failed": 30, "total_solutions": 900,
 "avg_solutions_per_input": 4.5, "total_prompt_tokens": 2000,
 "total_completion_tokens": 1000, "total_api_calls": 350,
 "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
 "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
                     "avg_solutions_per_input": 4.5, "total_api_calls": 142},
           "review": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
                      "avg_solutions_per_input": 4.5, "total_api_calls": 208}}}
```

A row counts as `passed` once it has produced one solution nothing rejected.

A run that tracks cost adds a `cost` object, and a resumed run adds
`resumed_from`:

```json
{"total": 50, "passed": 42, "failed": 8, "resumed_from": 50,
 "cost": {"total": 12.45, "prompt": 4.5, "completion": 7.95, "budget": 50.0,
          "budget_remaining": 37.55, "budget_exceeded": false}}
```

## Throughput

Rows are processed concurrently, and so are the tasks themselves: requests
from different tasks interleave freely. Each task has its own `RequestLimiter`
admitting requests as its sliding request and token windows allow, and holding
work back when `max_concurrent` is reached. A window that is not full admits
requests at once, so the server's queue stays fed instead of being drip-fed one
request at a time. Within each task's output file, rows stay in input order.

## Layout

| File | Contents |
| --- | --- |
| `rejector.py` | Argument parsing and the top-level run/exit-code flow. |
| `config.py` | Task config dataclasses, defaults merging, and validation. |
| `icl.py` | ICL setups, their example files, and the setup each attempt uses. |
| `tools.py` | Tool definitions and the handlers that answer a call. |
| `agentic.py` | The tool-calling loop and the metadata one run reports. |
| `templates.py` | Chat templates, and the text form of a tool call. |
| `jobs.py` | Matching tasks to their input and output files. |
| `prompts.py` | Template substitution and the messages of one request. |
| `dataset.py` | JSONL reading, prompt preparation, result writing. |
| `evaluation.py` | Answer extraction and the response-only checks. |
| `verdicts.py` | Judging a response, including the `script` and `llm_judge` modes. |
| `client.py` | HTTP calls, retries, usage charging, and run counters. |
| `limits.py` | Token estimation, the sliding windows, and the concurrency cap. |
| `cost.py` | What a run has spent, and the budget that stops it. |
| `schema.py` | Structured output validation against an `output_schema`. |
| `runner.py` | Per-row schemes, concurrency, and the summary. |
| `records.py` | The shape of an output record, and the counts read back from it. |
| `resume.py` | How many written rows a resumed run may skip. |
| `estimate.py` | The `--dry-run` estimate. |
| `progress.py` | The `--progress` updates printed while a run is in flight. |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

The end-to-end tests drive the CLI against `tests/mock_server.py`, a mock API
with a fixed worker pool that can inject `5xx` responses, control which
attempts pass evaluation, report the token usage a test asks for, echo back the
ICL examples it was sent, answer a row's `JSON=<object>` marker with structured
output, and answer its `TOOL=<name>:<args>` markers with tool calls on either
endpoint.
