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
[--api-url URL] [--model NAME] [--rpm N] [--max-tokens N]
[--scheme greedy|sample|rejection|agentic] [--temperature F] [--n N]
[--num-solutions N] [--icl-strategy fixed|random|round_robin] [--icl-k N]
[--api-type chat|completions] [--chat-template chatml|llama3|mistral|zephyr]
```

The two input modes are alternatives for a multi-task config. `--output` is a
file for single-task configs and a directory for multi-task ones, where each
executed task writes `<task_name>.jsonl`. Exit code `0` on success, `1` on a
configuration or input error (message on stderr). A JSON summary is printed to
stdout when the run finishes; multi-task runs add a per-task `tasks` object.

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
| `rejlib/templates.py` | the four built-in chat templates |
| `rejlib/tools.py` | tool definitions, the three handlers, tool-call parsing |
| `rejlib/agentic.py` | the tool-calling loop and the metadata it aggregates |
| `rejlib/ratelimit.py` | token bucket pacing requests against the `rpm` budget |
| `rejlib/schemes.py` | greedy / sample / rejection / agentic generation per row |
| `rejlib/runner.py` | concurrent fan-out per task |
| `rejlib/rows.py` | output row assembly in both formats, and the run summary |
| `rejlib/jsonl.py` | JSONL input parsing and output writing |

Concurrency: selected tasks run concurrently, each with its own `rpm` budget.
Within a task, rows are dispatched in input order, up to one minute of budget in
flight, and each task's output file keeps input order. Judge calls share their
task's budget and counters. See `AMBIGUITIES.md` for the interpretation
decisions behind the behaviour.

## Tests

```bash
.venv/bin/python -m pytest
```

`tests/fake_api.py` provides a threaded OpenAI-compatible stand-in serving both
endpoints, with scriptable responses (including tool calls), an optional
per-request delay, and a request log.
