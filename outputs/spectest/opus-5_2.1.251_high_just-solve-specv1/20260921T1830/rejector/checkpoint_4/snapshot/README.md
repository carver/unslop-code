# rejector

A CLI that reads a YAML configuration and JSONL input, sends prompts to an
OpenAI-compatible completions API concurrently, and writes one JSONL result
per input row. A config either describes a single task (Part 1) or several named
tasks sharing `defaults` (Part 2). Tasks may add in-context learning (ICL)
setups and collect several solutions per input (Part 3). A task may also let the
model call tools in a loop (`agentic`) and talk to `/v1/completions` with a
rendered chat template instead of `/v1/chat/completions` (Part 4).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
# single-task config: one input file, one output file
.venv/bin/python rejector.py run --config <path> --input <path> --output <path>

# multi-task config: one input per task, an output directory
.venv/bin/python rejector.py run --config multi.yaml \
  --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/

# multi-task config: inputs discovered as <task_name>.jsonl in a directory
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/

# run only some tasks
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ \
  --output results/ --task gsm8k --task review
```

Optional overrides replace the matching config value for every selected task:
`--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`, `--temperature`,
`--n`, `--num-solutions`, `--icl-strategy <fixed|random|round_robin>`,
`--icl-k`, `--api-type <chat|completions>`,
`--chat-template <chatml|llama3|mistral|zephyr>`. `--eval-model <string>`
overrides the judge model of every selected `llm_judge` task. `--task <name>` is repeatable and restricts the run to the
named tasks.

Exit codes: `0` on success, `1` on any configuration or input error.

Example:

```bash
.venv/bin/python rejector.py run \
  --config examples/multi.yaml \
  --input-dir examples/data \
  --output results/
```

### Input rules

| Config | Accepted input |
|--------|----------------|
| single task | `--input <path>`, or `--input-dir <dir>` holding `<task_name>.jsonl` |
| multi task  | repeated `--input <task>=<path>`, **or** `--input-dir <dir>` |

`--input` and `--input-dir` are alternative modes and cannot be combined. With
`--task`, only the selected tasks need an input; inputs for unselected tasks are
ignored and unselected tasks are not validated.

### Output rules

For single-task configs `--output` is the JSONL file to write. For multi-task
configs `--output` must be a directory (created if missing) and each executed
task is written to `<output_dir>/<task_name>.jsonl`. Only the tasks that ran are
written. Within each file, row order matches input order.

## Multi-task configuration

`defaults` holds shared values; each task overrides them. Nested sections
(`prompt`, `generation`, `evaluation`) are merged key by key, so a task can
replace just `prompt.user` or just `generation.scheme`. Required fields may come
from either place. A config that still uses a top-level `task` key is treated as
the Part 1 single-task format, with `task.name` as the task name.

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

  mmlu:
    prompt:
      system: "Answer the multiple choice question with a single letter."
      user: "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "letter"
    output_field: "choice"
```

See `examples/multi.yaml` (all four evaluation styles), `examples/icl.yaml`
(ICL setups and several solutions per input), `examples/agentic.yaml` (tools and
the tool-calling loop), `examples/completions.yaml` (completions mode) and
`examples/data/`.

## Schemes

| Scheme      | Behaviour |
|-------------|-----------|
| `greedy`    | `temperature` is forced to `0.0`; `n` is ignored; one attempt per row. |
| `sample`    | Requires `temperature > 0`; `n` is ignored; one attempt per row. |
| `rejection` | Requires `temperature > 0` and an `evaluation` section; makes up to `n` sequential attempts per row and keeps the first passing response. If every attempt is rejected, `output` is `null` and `result.passed` is `false`. |
| `agentic`   | Calls the model repeatedly, running the task's `tools` on every request that asks for them, until the model answers or `max_iterations` requests have been made. |

The table above describes a task with no ICL setups and `num_solutions: 1`;
in-context learning and multiple solutions change what each scheme does per row.

## Evaluation

`exact_match` compares an extracted value against the row's `answer_field`
(numeric values compare numerically, so `8` matches `8.0`). `contains` checks
that the `answer_field` value appears in the response. `regex` searches the
response for `pattern` and needs no `answer_field`.

Extract methods:

| Method | Takes |
|--------|-------|
| `last_number`  | last integer/decimal (comma separators ignored) |
| `first_number` | first integer/decimal |
| `last_line`    | last non-empty line |
| `letter`       | first uppercase choice `A`-`D`, as `A`, `(A)`, `A)` or `Answer: A` (a letter introduced by "answer"/"choice"/"option" wins over a bare one, so an echoed option list does not shadow the verdict) |
| `full`         | whole response, stripped |

When `evaluation` is omitted for `greedy`/`sample`, `result.passed` is `null`.

### `script`

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

The command template may reference row fields and `__response__`; if a row field
expands to text that itself contains `{__response__}` that placeholder is
substituted too. The rendered command runs in a shell with a 10 second timeout.
Exiting with `success_exit_code` (default `0`) passes; any other exit code, a
signal, or a timeout fails. stdout and stderr are captured and discarded, so they
never reach the JSONL output.

### `llm_judge`

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7
  extract: "first_number"
  model: "gpt-4"
```

After a response is generated, a second request scores it through the same
server. The judge prompt follows the normal template rules plus `__response__`.
The judge model is `evaluation.model`, else the task's `model`, and
`--eval-model` overrides both. `extract` defaults to `first_number`; a score
`>= threshold` passes. `result` gains `judge_score` (and `extracted_answer` is
the text `extract` took from the judge's reply), `meta` gains a `judge_meta`
object with the judge call's token usage, latency, model and finish reason.
Judge calls are sent at temperature `0.0`, and count toward `total_api_calls`,
the per-task totals and the measured throughput.

## In-context learning

A task (or `defaults`) may define named ICL setups. Each setup supplies few-shot
examples that are inserted between the system message and the row's user
message, as alternating user/assistant turns: every example `input` is rendered
with the task's `prompt.user` template, and every example `output` becomes the
assistant reply verbatim.

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

Each setup has a `name` and exactly one of `examples` or `file`. A `file` path is
relative to the config file's directory and holds JSONL, one example per
non-empty line:

```jsonl
{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"}
```

A line that is not valid JSON, or that lacks an object `input` or a string
`output`, ends the run with exit code 1 before any API request is sent.

`k` limits how many of a setup's examples are used; it defaults to all of them,
and a smaller `k` keeps the first `k`. `strategy` decides which setup an attempt
uses:

| Strategy      | Behaviour |
|---------------|-----------|
| `fixed`       | always the first setup (default) |
| `random`      | chosen independently for each attempt |
| `round_robin` | cycles through the setups in order across attempts (`A`, `B`, `C`, `A`, ...) |

`greedy` with `num_solutions > 1` ignores the strategy: it walks the setups in
declared order, at most once each, because repeating a setup at temperature `0`
would only repeat the answer.

## Multiple solutions

`num_solutions` (in `defaults` or on a task, overridden by `--num-solutions`)
asks for several solutions per input. `generation.max_attempts` bounds rejection
sampling and defaults to `3 * num_solutions`.

```yaml
tasks:
  gsm8k:
    generation:
      scheme: "rejection"
      temperature: 0.7
      max_attempts: 15
    num_solutions: 5
```

| Scheme | With several solutions requested |
|--------|----------------------------------|
| `greedy` | one attempt per ICL setup, in declared order, until `num_solutions` solutions exist or the setups run out - so at most one solution per setup, and one in total without ICL |
| `sample` | one sampled attempt per requested solution; evaluation does not gate whether a solution is kept |
| `rejection` | attempts until `num_solutions` of them pass or `max_attempts` is spent; only passing attempts are kept |

Without ICL every attempt uses the same prompt. A hard API failure ends the row,
so it may yield fewer solutions than requested.

When `num_solutions == 1` and no ICL is configured, the task keeps the earlier
behaviour exactly: rejection makes `generation.n` logical attempts,
`max_attempts` is not applied, and the row keeps the Part 1 output shape.

### Output shape with ICL or several solutions

`output` and `meta` become lists:

```json
{
  "input": {"question": "What is 15 + 27?", "answer": "42"},
  "output": [
    {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
    {"solution": "#### 42", "icl_setup": "direct"}
  ],
  "result": {"passed": 2, "failed": 5, "attempts": 7},
  "meta": [
    {"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
     "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
     "icl_setup": "chain_of_thought", "evaluation_passed": true}
  ]
}
```

Each output item holds the task's `output_field` plus `icl_setup`, which is the
chosen setup name or `null` when no ICL is configured. `result.passed` counts
passing solutions, `result.failed` counts failed attempts and `result.attempts`
counts every generation attempt for the row; `meta` has one entry per attempt.
Without an `evaluation` section `evaluation_passed` is `null`, `result.passed` is
the number of emitted outputs and `result.failed` is the number of attempts that
produced none. A row counts as passed in the summary when it produced at least
one passing solution.

This shape is used whenever ICL is configured or `num_solutions > 1`, including
with `num_solutions: 1` and ICL.

## Agentic generation

`scheme: agentic` turns a task into a tool-calling loop. The task lists the
tools it offers; `generation.max_iterations` (default `10`) bounds how many API
requests one loop may make.

```yaml
tasks:
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools to look up data and answer questions."
      user: "{question}"
    generation:
      scheme: "agentic"
      max_iterations: 10
      temperature: 0.0
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
            "employees": "142"
          default: "KEY_NOT_FOUND"
```

The loop builds the conversation from the system prompt, any ICL examples and
the row's user prompt, then repeats: send a request (in chat mode the tool
definitions travel in the request body as `tools`), and if the response asks for
tools, run every requested call, append the assistant tool-call turn plus one
`tool` message per result, and go again. A response with final text and no tool
calls ends the loop. Each request inside the loop is a separate API request and
counts toward `total_api_calls`, while rows still run concurrently, so a long
loop never blocks the other inputs.

`function.arguments` is parsed as JSON before the handler runs. Problems with a
call (unknown tool, unparsable arguments, a failing command) come back to the
model as an `ERROR: ...` tool result instead of ending the row.

### Tool handlers

| Handler | Result |
|---------|--------|
| `echo` | the parsed arguments, as a JSON string |
| `static_map` | `mapping[<first required parameter>]`, else `default` (itself defaulting to `NOT_FOUND`) |
| `script` | stdout of `command` run with the `arg_field` value as a single argument; on a non-zero exit or a 10 second timeout, `"ERROR: <stderr or timeout message>"` |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

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
      {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230,
       "latency_ms": 300, "finish_reason": "tool_calls"}
    ]
  }
}
```

`result.iterations` is the number of API requests the loop made and
`result.tool_calls` lists every call in execution order with its `iteration`,
`tool`, parsed `args` and handler `result`. `meta` aggregates the loop:
`total_*` sums every iteration, `latency_ms` is the loop's wall-clock time, and
`iterations_detail` holds one entry per request. `meta.finish_reason` is `stop`
for a final text answer.

Only the final text is evaluated. When `max_iterations` is reached first the row
gets `output: null`, `meta.finish_reason: "max_iterations"` and
`result.passed: false` - also without an `evaluation` section, where a finished
loop would instead report `passed: null`.

`agentic` also works with ICL and `num_solutions`: each solution is an
independent loop and the output keeps the Part 3 list format. There,
`result.attempts` counts the loops started for the row (not their requests),
each output item is one completed loop, and each `meta` entry keeps `icl_setup`
and `evaluation_passed` next to that loop's `total_prompt_tokens`,
`total_completion_tokens`, `total_tokens`, `latency_ms`, `finish_reason` and
`iterations_detail`. Without an `evaluation` section the Part 3 counting rules
apply: `result.passed` is the number of emitted outputs, `result.failed` the
number of loops that produced none, and `evaluation_passed` is `null`.

## Completions mode

With `api_type: "completions"` requests go to `{api_url}/v1/completions` and
carry a rendered `prompt` string instead of a messages array; the response text
is read from `choices[].text`.

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"

tasks:
  gsm8k:
    api_type: "completions"
    chat_template: "chatml"
```

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl   --output results.jsonl --api-type completions --chat-template llama3
```

`--api-type <chat|completions>` and `--chat-template <chatml|llama3|mistral|zephyr>`
override the config for every selected task. The request body holds `model`,
`prompt`, `temperature` and `max_tokens`; judge calls use the same endpoint and
template.

Four templates are built in, each rendering the whole conversation - system,
ICL example turns, assistant replies and tool results - by repeating its role
markers, and each ending with the assistant marker so the model continues from
there.

| Template | Per-message form |
|----------|------------------|
| `chatml`  | `<\|im_start\|>{role}\n{content}<\|im_end\|>\n` |
| `llama3`  | `<\|start_header_id\|>{role}<\|end_header_id\|>\n\n{content}<\|eot_id\|>`, after one leading `<\|begin_of_text\|>` |
| `mistral` | `[INST] {system}\n\n{user} [/INST]`, assistant turns as ` {content}</s>` |
| `zephyr`  | `<\|{role}\|>\n{content}</s>\n` |

In completions mode an agentic task has no native `tools` field to use, so the
tool documentation is folded into the system prompt and the model is asked to
reply with

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

blocks. Those are parsed out of the response text, executed exactly as in chat
mode, and their results go back into the next prompt through the template's
tool-role formatting.

## Output and summary

Each result row is `{"input": ..., "output": {<output_field>: ...}, "result":
..., "meta": ...}`. `meta` is one object per row, or a list with one entry per
attempt when a rejection row needed more than one.

A JSON summary is printed to stdout when the run finishes. Single-task configs
keep the Part 1 keys exactly; multi-task configs add a `tasks` object holding
only the tasks that ran:

```json
{"total": 200, "passed": 170, "failed": 30, "total_prompt_tokens": 2400,
 "total_completion_tokens": 1200, "total_api_calls": 350,
 "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
 "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15,
                     "total_api_calls": 142},
           "review": {"total": 100, "passed": 85, "failed": 15,
                      "total_api_calls": 208}}}
```

Tasks that can produce several solutions per input also report
`total_solutions` and `avg_solutions_per_input`, and the run summary reports the
same two totals across those tasks:

```json
{"tasks": {"gsm8k": {"total": 100, "passed": 96, "failed": 4,
                     "total_solutions": 450, "avg_solutions_per_input": 4.5,
                     "total_api_calls": 850}}}
```

## Concurrency

Work items from all selected tasks are queued round-robin (task by task, keeping
each task's rows in input order) and dispatched by a worker pool sized from the
summed `rpm` of the running tasks, capped by the number of work items. Workers
ramp up over a bounded window so requests also reach the server in input order;
each response is awaited by the worker that sent it, so a row can never consume
another row's response. Requests from different tasks therefore run concurrently
and interleave, while each output file stays in input order. Against a mock
server capped at its configured rpm the tool sustains ~99% of that capacity,
versus ~50% for a sequential client.

## Failure handling

An HTTP 5xx or a transport error is retried up to 3 total requests per logical
attempt. After the third failure the row is failed: `output` is `null`, the row
counts as failed in the summary, and the run continues. Retries count toward
`total_api_calls` but never increase `result.attempts`. A judge call that fails
this way fails the evaluation and records the error in `judge_meta`.

## Tests

```bash
.venv/bin/python tests/test_rejector.py   # Part 1 (~4 minutes)
.venv/bin/python tests/test_part2.py      # Part 2 (~40 seconds)
.venv/bin/python tests/test_part3.py      # Part 3 (~25 seconds)
.venv/bin/python tests/test_part4.py      # Part 4 (~40 seconds)
```

Each suite starts and stops its own mock server on a free port. Set `MOCK_PORT`
to point at a server you started yourself instead. Run them one at a time: both
assert on request ordering and throughput.

`tests/mock_server.py` emulates a server that queues work internally: it
processes `capacity` requests at a time, each taking `latency` seconds, so total
throughput is capped and a sequential client cannot reach it. It serves both `/v1/chat/completions` and `/v1/completions`, and `/requests`
returns the recent request bodies. Prompt markers drive its behaviour:
`ALWAYS_500`, `FLAKY2`, `BAD_REQUEST`, `REJECT<n>`, `NEVER`, `SAY:<text>`
(reply verbatim), `SCORE=<n>` or `SCORE=<n1>,<n2>,...` for judge requests (one
score per repeat of the same prompt), `TOOLS:<round>|<round>` plus optional
`LOOP_TOOLS` and `FINAL:<text>` for agentic loops, and `ECHO_PROMPT` to hand a
rendered completions prompt back.

The Part 4 suite covers the agentic loop (iterations, recorded tool calls,
every handler type and its error paths, `max_iterations`, the list format with
ICL and `num_solutions`, evaluation of the final text, request accounting and
cross-row overlap), completions mode (endpoint, request body, `choices[].text`,
the four templates single- and multi-turn, the CLI overrides), agentic requests
over `/v1/completions`, and the new configuration validation.

The Part 1 suite covers all three schemes, every Part 1 evaluation type and
extract method, retry/failure behaviour, output and summary shapes, CLI
overrides, config/input validation, ordering and throughput. The Part 2 suite
covers `defaults`/task merging, both input modes, task selection, output
directories, the `letter` and `first_number` extracts, `script` evaluation
(exit codes, nested `{__response__}`, timeout, stream suppression), `llm_judge`
(scores, thresholds, `judge_meta`, model resolution, rejection loops, call
accounting), the per-task summary, and cross-task concurrency. The Part 3 suite
covers ICL prompt assembly, inline and file-backed setups, `k`, all three
strategies, every scheme with `num_solutions > 1`, the rejection budget, the
list output format, the new summary fields, ICL config validation and the
unchanged legacy behaviour.
