# rejector

CLI that runs YAML-configured generation tasks against an OpenAI-compatible
API over JSONL input, one JSONL result per row. Tasks generate in one call or
in an agentic tool-calling loop, over `/v1/chat/completions` or a templated
`/v1/completions`.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# one task (Part 1 `task:` config)
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

# several tasks (`defaults:` + `tasks:` config), inputs named explicitly
.venv/bin/python rejector.py run --config multi.yaml \
    --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/

# ... or picked up from a directory as <task_name>.jsonl, for selected tasks only
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k

# against /v1/completions with a rendered prompt instead of a messages array
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl \
    --api-type completions --chat-template llama3
```

A multi-task config layers each task over `defaults`, writes
`<output_dir>/<task_name>.jsonl` per task that ran, and adds a `tasks` object
to the stdout summary. `--input <task>=<path>` and `--input-dir` are
alternative modes and cannot be combined.

Overrides for `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature`, `--n`, `--num-solutions`, `--icl-strategy`, `--icl-k`,
`--api-type` and `--chat-template` replace the corresponding config values
for every task; `--eval-model` replaces the judge model of `llm_judge` tasks. Exit code `1` means a
configuration or input error, with the reason on stderr; the run summary is
printed to stdout as one JSON object.

## In-context learning and multiple solutions

A task may declare named `icl.setups`, each with inline `examples` or a
`file` of JSONL demonstrations resolved against the config's directory. The
first `icl.k` demonstrations of the selected setup are sent as alternating
user/assistant turns between the system message and the row's own user
message; `icl.strategy` (`fixed`, `random` or `round_robin`) picks the setup
per attempt, except for greedy runs asking for several solutions, which walk
the setups in declared order instead.

`num_solutions` says how many solutions to collect per row: `sample` makes one
request per solution, `rejection` keeps generating until that many attempts
pass or `generation.max_attempts` (default `3 * num_solutions`) runs out, and
`greedy` produces at most one per setup. Such rows are written in a list
format — `output` is a list of `{<output_field>, icl_setup}` objects, `result`
counts `passed`/`failed`/`attempts`, and `meta` holds one entry per attempt
with its `icl_setup` and `evaluation_passed`. A task that asks for one
solution and configures no ICL keeps the Part 1 row shape and the Part 1
`generation.n` rejection budget.

## Agentic tasks

`generation.scheme: agentic` lets the model call the task's `tools` in a loop
before answering. Each iteration sends the conversation, executes every
`tool_calls` entry the reply asks for, and appends the assistant turn plus one
`tool` turn per result; the loop ends at the first reply with text and no tool
calls, or after `generation.max_iterations` requests (default 10), which
writes `output: null` and `finish_reason: "max_iterations"`. Handlers are
`echo` (the parsed arguments as JSON), `static_map` (a table keyed on the
tool's first required parameter, falling back to `default`, itself defaulting
to `NOT_FOUND`) and `script` (`command` run with one argument, answering with
its stdout or `ERROR: ...`).

A single-solution row records `result.iterations` and `result.tool_calls`, and
its `meta` aggregates the loop: `total_prompt_tokens`,
`total_completion_tokens`, `total_tokens`, `latency_ms`, `finish_reason` and
one `iterations_detail` entry per iteration. With ICL or `num_solutions > 1`
the row keeps the list format, one independent loop per requested solution,
and each `meta` entry carries that loop's aggregate.

## Completions mode

`api_type: completions` sends `{model, prompt, temperature, max_tokens}` to
`{api_url}/v1/completions` and reads `choices[0].text`. The conversation is
flattened by `chat_template`, one of `chatml`, `llama3`, `mistral` or
`zephyr`; each repeats its role markers per message, so ICL demonstrations and
agentic tool turns render as extra turns. Agentic tasks in this mode describe
their tools in the system turn and read `<tool_call>` JSON blocks out of the
response text instead of using the native `tools` field.

Evaluation types are `exact_match`, `contains`, `regex`, `script` (render a
shell command per row and compare its exit code, 10s timeout) and `llm_judge`
(score the response with a second model call and compare to a `threshold`).
Extract methods are `last_number`, `first_number`, `letter`, `last_line` and
`full`.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | Entry point |
| `taskrunner/cli.py` | Argument parsing, wiring, exit codes |
| `taskrunner/config.py` | YAML parsing, `defaults`/`tasks` merging, validation |
| `taskrunner/errors.py` | The `ConfigError` every bad config or input becomes |
| `taskrunner/icl.py` | ICL setups: parsing, example files, per-attempt choice |
| `taskrunner/inputs.py` | Task selection and input/output path resolution |
| `taskrunner/prompts.py` | `{field}` template rendering and row requirements |
| `taskrunner/evaluation.py` | Extract methods and evaluation dispatch |
| `taskrunner/script_eval.py` | Shell command rendering and exit-code checks |
| `taskrunner/judge.py` | The judge request and its score |
| `taskrunner/tools.py` | Tool definitions and the handlers that answer calls |
| `taskrunner/templates.py` | Built-in chat templates and the `<tool_call>` protocol |
| `taskrunner/api.py` | Async chat and completions clients with 5xx retries |
| `taskrunner/agentic.py` | The tool-calling loop one agentic solution runs |
| `taskrunner/generation.py` | Attempt planning and the per-row attempt loop |
| `taskrunner/runner.py` | Ordered, concurrent execution across tasks and rows |
| `taskrunner/records.py` | Output row and summary shaping |
| `taskrunner/jsonl.py` | JSONL reading and writing |

Rows are admitted to a per-task worker pool in input order with up to `rpm`
requests in flight, so the configured request budget stays saturated while each
row keeps its own response. Rejection attempts and agentic iterations are
sequential within a row, but rows run in parallel, so a short batch of agentic
rows still overlaps in flight; tasks share one HTTP session and run
concurrently, so their requests interleave.

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation takes. Tests live in `tests/`, each section commented
with the spec phrase it covers; `tests/fake_api.py` is a threaded stand-in for
the API that models queueing capacity.
