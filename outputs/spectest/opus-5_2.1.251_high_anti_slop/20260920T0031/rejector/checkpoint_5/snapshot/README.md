# rejector

A CLI that runs YAML-defined prompt tasks over JSONL datasets against an
OpenAI-compatible chat completions or completions API, evaluates each response,
and writes one JSONL result row per input row. Tasks can answer in one request
or work through their own tools first.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

One task, one input file, one output file:

```bash
python rejector.py run --config examples/greedy.yaml \
                       --input examples/data.jsonl \
                       --output results.jsonl
```

Several tasks from one config, either by naming each input or by pointing at a
directory holding `<task_name>.jsonl`:

```bash
python rejector.py run --config examples/multi.yaml \
                       --input gsm8k=math.jsonl --input mmlu=qa.jsonl \
                       --output results/

python rejector.py run --config examples/multi.yaml \
                       --input-dir examples/data/ --output results/ --task gsm8k --task review
```

`--input` and `--input-dir` are alternatives; combining them is an error. A
multi-task config writes `<output>/<task_name>.jsonl` for every task that ran,
so `--output` must be a directory (it is created if missing). With `--task`,
only the selected tasks are validated, run and written — the others need no
input file.

Optional flags override the matching config value for every selected task:
`--api-url`, `--model`, `--rpm`, `--tpm`, `--max-concurrent`, `--budget`,
`--max-tokens`, `--scheme`, `--temperature`, `--n`, `--num-solutions`,
`--icl-strategy`, `--icl-k`, `--api-type`, `--chat-template`, and
`--eval-model` for the judge model of `llm_judge` tasks.

Three flags change what a run does rather than how a task is configured:
`--dry-run` estimates the run instead of making it, `--resume` picks up where an
interrupted run stopped, and `--progress` reports on stderr while it proceeds.

Exit codes: `0` on success, `1` for a configuration or input error (the message
goes to stderr). The run summary is printed to stdout as a single JSON object.
A run that spends its cost budget is not an error: it stops early and still
exits `0`.

## Configuration

A single-task config is a `task` mapping:

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"   # required
  model: "gpt-4"                     # required

  rate_limits:                       # see Rate limits; `rpm: 60` may also be written here
    rpm: 100
    tpm: 50000
    max_concurrent: 10

  cost:                              # see Cost tracking; omit it to leave the run uncosted
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0

  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"               # required; {field} is taken from the input row

  api_type: "chat"                   # chat | completions (default chat)
  chat_template: "chatml"            # completions only: chatml | llama3 | mistral | zephyr

  generation:
    scheme: "greedy"                 # greedy | sample | rejection | agentic (default greedy)
    temperature: 0.0
    max_tokens: 512                  # default 512
    n: 1                             # rejection sampling attempts (default 1)
    max_iterations: 10               # agentic requests per loop (default 10)

  evaluation:                        # required for rejection, optional otherwise
    type: "exact_match"              # exact_match | contains | regex | llm_judge | script
    answer_field: "answer"           # required for exact_match and contains
    extract: "last_number"           # last_number | first_number | letter | last_line | full
    # pattern: "####\\s+\\d+"        # required for regex

  output_schema:                     # optional; see Structured output
    type: "object"
    required: ["code"]

  num_solutions: 1                   # solutions to collect per input row (default 1)

  output_field: "solution"           # required; names the key inside "output"
```

A multi-task config names its tasks under `tasks` and shares values through
`defaults` (see `examples/multi.yaml`):

```yaml
defaults:
  api_url: "http://localhost:8000"
  model: "gpt-4"
  generation:
    max_tokens: 512
  rate_limits:
    rpm: 100
  cost:
    prompt_cost_per_1k: 0.01

tasks:
  gsm8k:
    prompt: { system: "Solve it.", user: "{question}" }
    generation: { scheme: "rejection", temperature: 0.7, n: 5 }
    evaluation: { type: "exact_match", answer_field: "answer", extract: "last_number" }
    output_field: "solution"

  mmlu:
    prompt: { system: "Answer with a single letter.", user: "{question}" }
    evaluation: { type: "exact_match", answer_field: "answer", extract: "letter" }
    output_field: "choice"
```

Each task overrides `defaults`, and the `prompt`, `generation`, `evaluation`,
`icl`, `rate_limits` and `cost` sections are merged key by key, so a task only
restates what it changes. Every
field that is required of a single task must still come from `defaults` or from
the task itself. Task names come from the `tasks` keys; for a single-task
config the name is `task.name`.

### Schemes

With one solution asked for and no ICL configured:

| Scheme | Temperature | Attempts per row |
| --- | --- | --- |
| `greedy` | forced to `0.0` | 1 |
| `sample` | must be `> 0` | 1 |
| `rejection` | must be `> 0` | up to `n`, stopping at the first response that passes evaluation |
| `agentic` | as configured | 1, but that attempt is a whole [tool-calling loop](#agentic-generation) |

A rejection row that never passes is written with `"output": null`,
`"passed": false` and one metadata entry per attempt.

A task that asks for several solutions, or that configures ICL, follows the
budget described under [Multiple solutions](#multiple-solutions) instead.

### Evaluation

`exact_match` compares the extracted answer with the row's `answer_field`;
numbers compare by value (`8` == `8.0`) and other text compares
case-insensitively. `contains` tests whether the response text contains the
`answer_field` value. `regex` searches the response text for `pattern`.
Without an `evaluation` section, `result.passed` is `null` and any row the API
answered counts as passed in the summary.

Extraction methods: `last_number` and `first_number` take a number out of the
response, `letter` takes the first standalone `A`–`D` choice (`B`, `(B)`, `B)`
or `Answer: B`), `last_line` takes the last non-empty line and `full` the whole
response.

`llm_judge` rates the response with a second model call:

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7          # required; the row passes when the score is >= threshold
  extract: "first_number"
  model: "gpt-4"        # optional; defaults to the task's model
```

The judge prompt uses row fields plus `{__response__}`, and `extract` pulls the
score out of the judge's reply into `result.extracted_answer`. The row's
`result` also gains a `judge_score`, and its `meta` gains a `judge_meta` object
with the judge call's tokens, latency, model and finish reason. Judge calls go to the same server through the same
rate limiter as the generations, so they are paced, interleaved and counted
with them.

`script` hands the decision to a shell command:

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0  # default 0
```

The command is rendered from row fields and `{__response__}`, including a
`{__response__}` that a row field such as `test_code` brings in itself, and is
run in a shell. Exiting with `success_exit_code` passes the row; any other exit
code, or taking longer than 10 seconds, fails it. The command's output is
captured but never written to the results.

### Agentic generation

An `agentic` task lets the model call the task's tools before it answers. Each
attempt is a loop: the conversation goes out, every tool the model asks for is
executed, the results are appended and the conversation goes out again, until
the model replies with text or `generation.max_iterations` requests are spent.

```yaml
generation:
  scheme: "agentic"
  max_iterations: 10
  temperature: 0.0

tools:
  - name: "lookup"
    description: "Look up a value in the database by key"
    parameters:                       # JSON Schema, sent to the model as-is
      type: "object"
      properties:
        key: {type: "string", description: "The database key to look up"}
      required: ["key"]
    handler:
      type: "static_map"
      mapping: {"revenue_q1": "1250000", "employees": "142"}
      default: "KEY_NOT_FOUND"        # default "NOT_FOUND"
```

A task using the scheme needs at least one tool. Handlers answer a call
locally:

| `handler.type` | Result |
| --- | --- |
| `echo` | the parsed call arguments as a JSON string |
| `static_map` | `mapping[<first required parameter>]`, or `default` when the key is unknown |
| `script` | the stdout of `command` run with `args[arg_field]` as its single argument |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

A script that exits non-zero or runs longer than 10 seconds returns
`"ERROR: <stderr or timeout message>"` instead of its output, which the model
sees like any other result.

Chat tasks send the tool definitions in the request's `tools` field and read
back native `tool_calls`; completions tasks get the same definitions written
into their prompt and reply with `<tool_call>` blocks (see
[Completions mode](#completions-mode)). Either way every call in one response
is executed, in order, before the next request. Each request inside a loop is
paced and counted like any other, and loops of different rows run concurrently.

A single-solution agentic row reports the loop alongside the Part 1 fields:

```json
{
  "input": {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"},
  "output": {"answer": "The total revenue for Q1 and Q2 is 2730000."},
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
      {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230, "latency_ms": 300,
       "finish_reason": "tool_calls"}
    ]
  }
}
```

`result.iterations` counts the loop's API requests and `result.tool_calls`
records every call it made. The `meta` totals cover all of those requests,
`meta.latency_ms` is the loop's wall-clock time and `meta.iterations_detail`
holds one entry per request. A loop that answers finishes with
`finish_reason: "stop"`; one that runs out of iterations writes
`"output": null` with `finish_reason: "max_iterations"`, and evaluation fails
because there is no answer to score.

`agentic` combines with ICL and `num_solutions`, each solution being its own
loop. Such a row keeps the [list format](#output-format): `result.attempts`
counts the loops, not their requests, and each `meta` entry is one loop's
aggregated metadata next to its `icl_setup` and `evaluation_passed`.

### Completions mode

`api_type: "completions"` sends `{api_url}/v1/completions` a rendered prompt
string instead of a messages array, and reads the answer from
`choices[0].text`:

```json
{"model": "meta-llama/llama-3-70b", "prompt": "<rendered template string>",
 "temperature": 0.0, "max_tokens": 512}
```

`chat_template` picks how the conversation is written out. The four built-in
templates — `chatml`, `llama3`, `mistral` and `zephyr` — repeat their role
markers for every turn, so multi-turn conversations and tool results render the
same way a single question does. `--api-type` and `--chat-template` override
the config:

```bash
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl \
                       --api-type completions --chat-template llama3
```

An agentic task in this mode describes its tools in the prompt and asks for a
call by writing a block into its response:

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

The results are handed back through the template's tool-role markers and the
loop continues exactly as it does in chat mode.

### In-context learning

A task may show the model worked examples before the row's own question. Each
named setup lists its examples inline or points at a JSONL file:

```yaml
icl:
  setups:
    - name: "chain_of_thought"
      examples:
        - input: {question: "What is 2+2?"}
          output: "Let me think step by step.\n2 + 2 = 4\n#### 4"
        - input: {question: "If I have 3 cats and get 2 more, how many cats do I have?"}
          output: "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5"
    - name: "detailed"
      file: "icl/gsm8k_detailed.jsonl"
  k: 2                  # examples shown from the chosen setup (default: all of them)
  strategy: "round_robin"   # fixed | random | round_robin (default fixed)
```

Every setup needs a `name` and exactly one of `examples` or `file`. A `file`
path is relative to the config file's directory and holds one example per line:

```jsonl
{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"}
```

Example files are read and checked before the first request, so a malformed
line or a missing `input`/`output` key ends the run with exit code 1 and no API
calls spent. `k` takes the first `k` examples of the setup and defaults to all
of them.

The examples are rendered with the task's own `prompt.user` template and sit
between the system message and the row's question as alternating user and
assistant turns; each example's `output` is sent verbatim as the assistant
message. The strategy picks the setup of each attempt: `fixed` always uses the
first, `random` draws one per attempt, and `round_robin` cycles through them in
order (`A`, `B`, `C`, `A`, `B`, …).

### Multiple solutions

`num_solutions` (in `defaults`, in a task, or from `--num-solutions`) asks for
more than one solution per input row:

```yaml
generation:
  scheme: "rejection"
  temperature: 0.7
  max_attempts: 15      # defaults to 3 * num_solutions for rejection
num_solutions: 5
```

| Scheme | Attempts per row |
| --- | --- |
| `greedy` | one per ICL setup, in declared order, until `num_solutions` are collected — a setup is deterministic, so it is never retried |
| `sample` | one per requested solution; evaluation does not decide what is kept |
| `rejection` | up to `max_attempts`, keeping only the responses that pass, until `num_solutions` of them are collected |

Without ICL each attempt sends the same prompt, so `greedy` still produces at
most one solution. A row that runs out of attempts keeps the solutions it did
collect.

A task asking for a single solution without ICL keeps the Part 1 behaviour
exactly: rejection sampling spends `generation.n` attempts and `max_attempts`
does not apply.

### Output format

As soon as ICL is configured or `num_solutions` is above one, a row lists its
solutions instead of naming a single one:

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

`icl_setup` is the name of the setup that produced the entry, or `null` for a
task without ICL. `result.passed` counts the attempts that passed evaluation,
`result.failed` the rest of them, and `result.attempts` every generation the row
made; `meta` carries one entry per answered attempt. Without an `evaluation`
section every `evaluation_passed` is `null`, `result.passed` counts the emitted
solutions and `result.failed` the attempts the API never answered.

### Structured output

A task may require its answer to be a JSON document matching a schema:

```yaml
output_schema:
  type: "object"
  required: ["code", "explanation"]
  properties:
    code: {type: "string"}
    explanation: {type: "string"}
```

The response is parsed and validated before anything else scores it, and the
parsed value — not the raw text — is what the row writes:

```json
{"output": {"code": {"code": "def add(a, b): return a + b",
                     "explanation": "Simple addition function"}},
 "result": {"passed": true, "schema_valid": true}}
```

A response that is not JSON, or that breaks a constraint, fails the schema. The
row then writes `"output": null` and says which constraint it broke:

```json
{"output": null,
 "result": {"passed": false, "schema_valid": false,
            "schema_error": "Missing required field: explanation"}}
```

Supported keywords are the draft 7 subset `type`, `required`, `properties`,
`items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength` and `pattern`;
the first one a response breaks is the one reported. For rejection sampling a
schema failure is a failed attempt like any other, so the row tries again — and
a rejection task may be gated by `output_schema` alone, without an `evaluation`
section. Evaluation is skipped for a response that failed the schema.

`schema_valid` and `schema_error` belong to the single-solution row; a task
using the [list format](#output-format) simply does not keep a solution that
failed validation.

### Rate limits

A task's budgets live in `rate_limits`, in `defaults`, or on the command line
through `--rpm`, `--tpm` and `--max-concurrent`:

```yaml
rate_limits:
  rpm: 100              # requests per minute; omit it to leave requests unpaced
  tpm: 50000            # tokens per minute; omit it to leave tokens uncounted
  max_concurrent: 10    # in-flight rows, whatever the other two allow
```

Both budgets are sliding 60-second windows, so a run may start with a full
minute of work in flight and then settles at the configured rate. Before a
request goes out it reserves `estimated prompt tokens + max_tokens` against the
token window, sizing the prompt at one token per 0.75 words; once the response
arrives the reservation is replaced with the `prompt_tokens + completion_tokens`
the API reported. A request is sent only when both windows have room, which lets
the tighter budget set the pace — with `rpm: 600`, `tpm: 10000` and requests of
about 612 tokens, it is the token budget that paces the run.

`max_concurrent` is a hard cap independent of the other two; it defaults to a
minute of the request budget, or to 10 when `rpm` is omitted. Judge calls go
through the same limiter as the generations, and every request of an agentic
loop is paced and counted like any other while the loop holds its concurrency
slot for its whole lifetime. `rpm` may still be written as a task-level key the
way earlier versions spelled it.

### Cost tracking

Token prices and the run's budget live in `cost`, in `defaults`, or on the
command line through `--budget`:

```yaml
cost:
  prompt_cost_per_1k: 0.01
  completion_cost_per_1k: 0.03
  budget: 50.0
```

Each call costs `prompt_tokens / 1000 * prompt_cost_per_1k +
completion_tokens / 1000 * completion_cost_per_1k`, judge calls and every
agentic iteration included, and the summary gains a `cost` object:

```json
{"cost": {"total": 12.45, "prompt": 4.50, "completion": 7.95,
          "budget": 50.0, "budget_remaining": 37.55, "budget_exceeded": false}}
```

Tasks price their own tokens but share one budget — the tightest any of them
sets. Reaching it stops new requests immediately; requests already in flight
finish, their rows are written, the summary is printed and the run exits `0`.
Rows that never started are simply absent from the output, which makes the
partial result a valid input for `--resume`. A run with no `cost` section
anywhere reports no `cost` field at all.

### Resume

`--resume` reads the output file an earlier run left behind and skips the input
rows it already covers:

```bash
python rejector.py run --config task.yaml --input data.jsonl \
                       --output results.jsonl --resume
```

Results are written in input order, so the count of complete leading rows is the
number of input rows to skip; new rows are appended after them. A multi-task run
resumes each task from its own output file. A row is not complete — and is
generated again from scratch — when it is a rejection or multi-solution row
holding fewer solutions than `num_solutions`, or when it is the half-written
line an interrupted run left at the end. Every input row is still validated, so
a malformed row is reported against its position in the input file whether or
not the resumed run would have sent it.

The summary covers only the rows the resumed run processed itself, and says how
many it found done:

```json
{"total": 50, "resumed_from": 50, "passed": 42, "failed": 8}
```

### Dry run

`--dry-run` validates the config and the inputs, then prints an estimate to
stdout and exits `0` without making a single request:

```json
{
  "tasks": {
    "gsm8k": {"inputs": 1000, "est_prompt_tokens": 45000, "est_completion_tokens": 512000,
              "est_total_tokens": 557000, "est_cost": 20.31}
  },
  "total_inputs": 1000,
  "est_total_tokens": 557000,
  "est_total_cost": 20.31,
  "est_time_minutes": 9.3
}
```

Prompt tokens are the task's average rendered prompt at `1.33` tokens per word,
completion tokens are `max_tokens` per row, and the cost follows the configured
rates. The time is `inputs * attempts / rpm`, counting one attempt per row for
`greedy` and `sample` and the whole attempt budget for `rejection`; a task
without an `rpm` contributes no time.

### Progress

`--progress` writes a line to stderr every five seconds or every tenth of the
run, whichever comes first:

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The pass/fail field appears only when a task configures evaluation, and the
spend only when the run is costed.

## Behaviour notes

- **Concurrency.** Each task runs `max_concurrent` rows at once against its own
  server, paced by its own [rate limits](#rate-limits). Tasks run concurrently
  with each other, and their requests may be interleaved, but each output file
  keeps its input's row order. An agentic row holds one of those concurrency
  slots for its whole loop, so the requests of different rows still overlap
  instead of queueing behind one another.
- **Retries.** An HTTP 5xx is retried up to 3 times (4 requests in total). Once
  the budget is spent the row is written with a `null` output and counted as
  failed. Retries count toward `total_api_calls` but never toward
  `result.attempts`, which only counts logical generation attempts. Any other
  non-2xx status is reported as an error and stops the run with exit code 1.
- **Summary.** `total_api_calls`, `throughput_rpm` and the token totals cover
  every request the run made, judge calls and every iteration of an agentic loop
  included. The `tasks` object breaks the counts down by task, listing only the
  tasks that ran, and adds `total_solutions` and `avg_solutions_per_input` for
  each of them. A row counts as passed once it has at least one solution. A
  costed run adds `cost` and a resumed one `resumed_from`.
- **Validation order.** Every selected task's config and input rows are
  validated before the first request, so a missing prompt, judge prompt or
  command field fails fast (`input row 0: missing field 'question'`) without
  spending API calls.

## Layout

| File | Responsibility |
| --- | --- |
| `rejector.py` | CLI parsing, wiring and exit codes |
| `config.py` | YAML loading, defaults merging, CLI overrides, validation |
| `plan.py` | resolving inputs and outputs into the work each task will do |
| `icl.py` | ICL setups: their examples, the turns they add and how one is picked |
| `tools.py` | tool definitions, the calls a model asks for and the handlers that answer them |
| `chat_templates.py` | the built-in chat templates that render a conversation into a prompt |
| `endpoints.py` | request bodies, response parsing and conversation turns of the two API shapes |
| `agentic.py` | the agentic loop and the metadata it aggregates |
| `dataset.py` | JSONL input/output and per-row validation |
| `templates.py` | prompt, judge prompt and command template rendering |
| `api.py` | async API client, retries, per-call billing |
| `limits.py` | the sliding request and token windows requests are paced by |
| `cost.py` | per-call cost, the run's running total and its budget |
| `tracking.py` | run-wide timing and counters, and the `--progress` line |
| `schema.py` | JSON parsing and draft 7 validation of structured output |
| `resume.py` | how much of an existing output file a resumed run keeps |
| `estimate.py` | the `--dry-run` estimate |
| `evaluation.py` | answer extraction and the text-only pass/fail checks |
| `judge.py` | `llm_judge` evaluation |
| `script_eval.py` | `script` evaluation |
| `schedule.py` | the attempt budget of a row and the setup each attempt uses |
| `runner.py` | per-row schemes, evaluation dispatch, concurrency |
| `rows.py` | the single-solution and list result rows |
| `summary.py` | run and per-task aggregation of the finished rows |
| `errors.py` | the user-facing error type |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

`tests/mock_server.py` is a standalone OpenAI-compatible mock used by the
end-to-end tests. It serves both endpoints, processes a bounded number of
requests at a time so extra requests queue, and can inject 5xx failures and
wrong answers. When a request offers tools it asks for `--tool-calls` of them
before answering, which is what drives an agentic loop:

```bash
.venv/bin/python tests/mock_server.py --port 8000 --rpm 60 --latency 3.0 --accuracy 0.5
python rejector.py run --config examples/rejection.yaml --input tests/data.jsonl --output out.jsonl
python rejector.py run --config examples/multi.yaml --input-dir examples/data --output results/
python rejector.py run --config examples/icl.yaml --input tests/data.jsonl --output icl.jsonl --rpm 600
python rejector.py run --config examples/agentic.yaml --input examples/data/data_lookup.jsonl \
                       --output agentic.jsonl --api-type completions --chat-template llama3
python rejector.py run --config examples/multi.yaml --input-dir examples/data --output results/ --dry-run
python rejector.py run --config examples/structured.yaml --input examples/data/code_gen.jsonl \
                       --output structured.jsonl --progress
```

It answers with the last number in the prompt, which is why `tests/data.jsonl`
states each expected answer in the question — and why the multi-task, agentic
and structured examples exercise the plumbing rather than producing sensible
letters, ratings, lookup keys or JSON.
