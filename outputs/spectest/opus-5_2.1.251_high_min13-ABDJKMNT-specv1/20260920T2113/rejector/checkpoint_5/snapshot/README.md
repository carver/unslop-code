# rejector

CLI tool that runs YAML-defined generation tasks over JSONL input files against
an OpenAI-compatible API - chat completions or text completions - and writes one
JSONL result per input row. A config holds either a single Part 1 `task` or a `defaults` section
plus a `tasks` mapping of named tasks.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

Single-task config:

```bash
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Multi-task config, one input per task or a directory of `<task_name>.jsonl`:

```bash
python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/
python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

Shared options:

```
[--task NAME]... [--eval-model NAME]
[--api-url URL] [--model NAME] [--rpm N] [--tpm N] [--max-concurrent N]
[--budget F] [--max-tokens N]
[--scheme greedy|sample|rejection|agentic] [--temperature F] [--n N]
[--num-solutions N] [--icl-strategy fixed|random|round_robin] [--icl-k N]
[--api-type chat|completions] [--chat-template chatml|llama3|mistral|zephyr]
[--resume] [--dry-run] [--progress]
```

The two input modes are alternatives for a multi-task config. `--output` is a
file for single-task configs and a directory for multi-task ones, where each
executed task writes `<task_name>.jsonl`. Exit code `0` on success, `1` on a
configuration or input error (message on stderr). A JSON summary is printed to
stdout when the run finishes; multi-task runs add a per-task `tasks` object.

## Rate limits and cost

A `rate_limits` section - in `defaults`, per task, or via `--rpm` / `--tpm` /
`--max-concurrent` - paces a task's requests:

```yaml
defaults:
  rate_limits:
    rpm: 100
    tpm: 50000
    max_concurrent: 10
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0
```

`rpm` and `tpm` are sliding 60-second budgets over the requests and the tokens of
the last minute; a request waits until both have room. Before dispatch a request
reserves `ceil(prompt words / 0.75) + max_tokens` tokens, and the reply's real
`prompt_tokens + completion_tokens` then replaces that reservation. Omitting
`rpm` or `tpm` disables that budget. `max_concurrent` caps in-flight requests on
top of both; an agentic loop holds one slot for its whole lifetime. Judge calls
and agentic iterations are paced and billed like any other request.

A `cost` section prices calls at `tokens / 1000 * rate` and the summary reports
`cost.total`, `cost.prompt`, `cost.completion`, `budget`, `budget_remaining` and
`budget_exceeded`. When the running total reaches `budget` the run stops sending
requests, writes what it finished, prints the summary and exits `0`. Without any
cost configuration the summary has no `cost` field.

## Structured output

A task may require its response to be JSON satisfying an `output_schema`:

```yaml
output_schema:
  type: "object"
  required: ["code", "explanation"]
  properties:
    code: {type: "string"}
    explanation: {type: "string"}
```

The supported draft 7 keywords are `type`, `required`, `properties`, `items`,
`enum`, `minimum`, `maximum`, `minLength`, `maxLength` and `pattern`. Validation
runs before any evaluation and replaces the row's raw text output with the parsed
value; `result.schema_valid` records the verdict and `result.schema_error` the
reason a response was rejected. A failure sets `output` to `null` and fails the
row for `greedy` and `sample`, counts as a failed attempt under `rejection`
(which may then rely on the schema alone, without an `evaluation` block), and
invalid JSON counts as a failure like any other.

## Resume, dry runs and progress

`--resume` inspects the existing output file (per task file for multi-task
configs), skips the input rows whose results are already there and appends the
rest; a trailing row with fewer solutions than `num_solutions` is dropped and
processed again. The summary then covers only the new rows and reports
`resumed_from`.

`--dry-run` validates the config and inputs, then prints an estimate - rows,
prompt tokens (`average prompt word count * 1.33`), completion tokens
(`max_tokens` per row), cost and `est_time_minutes` - without calling the API.

`--progress` reports on stderr every five seconds or every 10% of the rows:

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The pass/fail field appears only with an evaluation and the spend only with cost
tracking.

## In-context learning and multiple solutions

A task may carry an `icl` section listing named setups, each holding inline
`examples` or pointing at a JSONL `file` of `{"input": ..., "output": ...}`
lines resolved relative to the config file. The first `icl.k` examples of the
selected setup are sent as alternating user/assistant turns between the system
message and the row's own message, and `icl.strategy` (`fixed`, `random` or
`round_robin`) decides which setup each attempt uses.

`num_solutions` asks for several solutions per input row: greedy walks its
setups once each, sample makes one request per requested solution, and rejection
keeps generating until enough attempts pass or `generation.max_attempts`
(default `3 * num_solutions`) is spent. Rows of a task that configures ICL or
asks for more than one solution use the list output format - `output` and `meta`
become lists, each carrying the `icl_setup` that produced them, and `result`
reports `passed`/`failed`/`attempts`. A task with one solution and no ICL keeps
the Part 1 row format and Part 1 rejection behaviour (`generation.n` attempts).

## Agentic tasks

`generation.scheme: agentic` lets the model call tools before answering. The
task's `tools` list gives each tool a `name`, `description`, JSON-schema
`parameters` and a `handler`: `echo` returns the parsed arguments, `static_map`
looks the first required parameter up in a `mapping` (falling back to `default`,
itself defaulting to `NOT_FOUND`), and `script` runs `command` with the value of
`arg_field` as one argument and returns its stdout, or `ERROR: ...` on a timeout
or non-zero exit.

Each loop sends a request, executes every tool call the reply asks for, appends
the assistant message and one message per result, and repeats until the model
answers in text or `generation.max_iterations` (default 10) requests are spent.
A row that runs out of iterations writes `output: null` and
`meta.finish_reason: "max_iterations"`. Its `result` adds `iterations` - the
number of requests - and `tool_calls`, one entry per executed call; its `meta`
aggregates the loop's token counts and wall-clock latency and records an
`iterations_detail` entry per request. ICL and `num_solutions` work as for any
other scheme, each solution being its own loop, and switch the row to the list
format where every `meta` entry holds one loop's aggregate.

## Completions mode

`api_type: completions` (in `defaults`, per task, or via `--api-type`) posts to
`{api_url}/v1/completions` with the conversation rendered into a `prompt` string
by `chat_template` (`--chat-template`; `chatml`, `llama3`, `mistral` or
`zephyr`, default `chatml`), and reads the reply from `choices[0].text`. Agentic
tasks in this mode describe their tools inside the system prompt and read tool
calls back out of `<tool_call>{...}</tool_call>` blocks in the response text.

## Evaluation

Evaluations are `exact_match`, `contains`, `regex`, `script` (exit code of a
rendered shell command) and `llm_judge` (a second model call whose score is
compared against a threshold). Extract methods are `last_number`,
`first_number`, `last_line`, `letter` and `full`.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | argument parsing and the top-level run sequence |
| `rejlib/config.py` | YAML loading, `defaults`/task merging, CLI overrides, validation |
| `rejlib/validate.py` | the small value validators the loaders share |
| `rejlib/icl.py` | ICL setups: loading examples and picking one setup per attempt |
| `rejlib/inputs.py` | mapping the input flags to per-task rows, output target checks |
| `rejlib/prompts.py` | `{field}` template rendering, per-row field requirements |
| `rejlib/extraction.py` | the extract methods |
| `rejlib/evaluation.py` | verdicts: the in-memory types plus script and judge dispatch |
| `rejlib/script_eval.py` | running a `script` evaluation's shell command |
| `rejlib/judge.py` | the `llm_judge` scoring call |
| `rejlib/api.py` | chat and completions client, 5xx retries, per-task counters |
| `rejlib/tokens.py` | word-based token estimates for scheduling and dry runs |
| `rejlib/scheduler.py` | what gates a request: rate budgets, concurrency, cost |
| `rejlib/cost.py` | per-call charges, the run-wide ledger and the budget |
| `rejlib/schema.py` | `output_schema` validation against a draft 7 subset |
| `rejlib/resume.py` | how much of an output file is already complete |
| `rejlib/dryrun.py` | the token, cost and time estimate of a dry run |
| `rejlib/progress.py` | the periodic status line on stderr |
| `rejlib/plan.py` | resolving CLI arguments into one run's work and outputs |
| `rejlib/templates.py` | the four built-in chat templates |
| `rejlib/tools.py` | tool definitions, the three handlers, tool-call parsing |
| `rejlib/agentic.py` | the tool-calling loop and the metadata it aggregates |
| `rejlib/ratelimit.py` | the sliding request/token windows and the concurrency cap |
| `rejlib/schemes.py` | greedy / sample / rejection / agentic generation per row |
| `rejlib/runner.py` | concurrent fan-out per task |
| `rejlib/rows.py` | output row assembly in both formats, and the run summary |
| `rejlib/jsonl.py` | JSONL input parsing and output writing |

Concurrency: selected tasks run concurrently, each with its own rate budgets and
concurrency cap. Within a task, rows are dispatched in input order, and each
task's output file keeps input order however much the requests overlap. Judge
calls share their task's budgets, counters and cost. The cost ledger is shared by
every task, since the budget applies to the run as a whole. See `AMBIGUITIES.md`
for the interpretation decisions behind the behaviour.

## Tests

```bash
.venv/bin/python -m pytest
```

`tests/fake_api.py` provides a threaded OpenAI-compatible stand-in serving both
endpoints, with scriptable responses (including tool calls), an optional
per-request delay, and a request log.
