# rejector

CLI that runs YAML-configured generation tasks over JSONL input against an
OpenAI-compatible chat completions API, and writes one JSONL result row per
input row.

```bash
# single-task config (Part 1 shape: a top-level `task:` mapping)
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

# multi-task config (`defaults:` plus a `tasks:` mapping)
python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/
python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

`--input` and `--input-dir` are alternative input modes; directory mode looks
for `<task_name>.jsonl`. A multi-task run writes `<output_dir>/<task>.jsonl`
for each task that ran. Optional overrides: `--api-url`, `--model`, `--rpm`,
`--tpm`, `--max-concurrent`, `--budget`, `--max-tokens`, `--scheme`,
`--temperature`, `--n`, `--eval-model`, `--num-solutions`, `--icl-strategy`,
`--icl-k`, `--api-type`, `--chat-template`, plus the `--resume`, `--dry-run`
and `--progress` modes below. Exit code `0` on success, `1` on a configuration
or input error.

## Scheduling, cost, and structured output

`rate_limits` paces a task: `rpm` and `tpm` are sliding 60-second windows and
`max_concurrent` is a hard cap on in-flight requests. Each request reserves
its estimated prompt tokens (`1 token ~= 0.75 words`) plus `max_tokens` before
it is sent, and the reservation is rewritten with the usage the response
reports. Judge calls are paced by their task's limiter, and an agentic loop
holds one concurrency slot from its first request to its last. Omitting `rpm`
turns request limiting off for that task.

`cost` prices each call from `prompt_cost_per_1k` and `completion_cost_per_1k`
and reports the run's `cost` block in the summary. Once the running total
reaches `cost.budget` no further requests are sent: the in-flight ones finish,
their rows are written, the summary says `budget_exceeded`, and the run still
exits `0`.

`output_schema` requires the response to be JSON satisfying a draft 7 subset
(`type`, `required`, `properties`, `items`, `enum`, `minimum`, `maximum`,
`minLength`, `maxLength`, `pattern`). Validation runs before any evaluation:
a valid response is stored parsed in `output`, an invalid one writes `null`
output with `result.schema_valid` and `result.schema_error` -- or, under
`rejection`, counts as a failed attempt and triggers another try.

`--resume` skips the leading input rows an earlier output file already covers
and appends the rest, reprocessing a trailing row that holds fewer solutions
than the task asked for; its summary counts only the new rows and reports
`resumed_from`. `--dry-run` validates everything, prints a token, cost and
time estimate, and calls nothing. `--progress` prints a status line to stderr
every five seconds or every tenth of the inputs.

## In-context learning and multiple solutions

A task may declare named `icl.setups`, each holding `examples` inline or a
JSONL `file` (resolved against the config file's directory). The first `icl.k`
examples of the selected setup are inserted between the system message and the
row's own user message as alternating user/assistant turns, and `icl.strategy`
(`fixed`, `random` or `round_robin`) picks the setup for each attempt.

`num_solutions` asks for several solutions per row: `sample` makes one request
per solution, `rejection` keeps going until enough attempts pass or
`generation.max_attempts` (default `3 * num_solutions`) runs out, and `greedy`
walks each setup at most once. Such rows report a list of solutions, each
tagged with its `icl_setup`, and one metadata entry per attempt. A task with
one solution and no ICL keeps the Part 1 row shape and the Part 1 rejection
behaviour.

## Agentic tasks and completions mode

`generation.scheme: agentic` turns each solution into a loop: the task's
`tools` are offered to the model, every `tool_calls` response is executed and
fed back, and the loop ends on the first response that is plain text or at
`generation.max_iterations` (default 10), which writes `null` output and a
`max_iterations` finish reason. A tool's `handler` is `echo` (the arguments as
JSON), `static_map` (the first required argument looked up in `mapping`, else
`default`) or `script` (a command run over one argument, whose failures come
back as `ERROR: ...`). Such a row reports `result.iterations`,
`result.tool_calls`, and a `meta` aggregated over the loop with one
`iterations_detail` entry per request.

`api_type: completions` sends `prompt`, `temperature`, `max_tokens` and
`model` to `{api_url}/v1/completions` and reads `choices[0].text`. The
conversation -- system turn, ICL turns, tool results and all -- is rendered by
the `chat_template` (`chatml`, `llama3`, `mistral` or `zephyr`). Agentic tasks
in this mode describe their tools in the prompt and read the model's
`<tool_call>` blocks out of the response text.

Evaluations are `exact_match`, `contains`, `regex`, `script` (a shell command
whose exit code decides the row, with a 10s timeout) and `llm_judge` (a second
API call whose extracted score is compared to `threshold`).

## Layout

| Path | Role |
| --- | --- |
| `rejector.py` | entry point |
| `rejector_lib/cli.py` | argument parsing, run orchestration |
| `rejector_lib/config.py` | YAML loading, `defaults` merging, validation |
| `rejector_lib/errors.py` | the two exit-code-1 failure types |
| `rejector_lib/icl.py` | ICL setups: loading, rendering, strategy rotation |
| `rejector_lib/plan.py` | task selection and input/output file resolution |
| `rejector_lib/inputs.py` | JSONL reading, row validation, template rendering |
| `rejector_lib/api.py` | async client for both endpoints, retries, usage tallies |
| `rejector_lib/limits.py` | the sliding RPM/TPM windows and the concurrency cap |
| `rejector_lib/cost.py` | per-call pricing, the run's total, and the budget |
| `rejector_lib/schema.py` | the JSON Schema draft 7 subset for `output_schema` |
| `rejector_lib/templates.py` | the built-in chat templates for completions mode |
| `rejector_lib/tools.py` | tool definitions, handlers, and tool-call parsing |
| `rejector_lib/agentic.py` | the agentic tool-calling loop |
| `rejector_lib/runner.py` | greedy/sample/rejection schemes, per-task concurrency |
| `rejector_lib/solutions.py` | collecting several solutions for one row |
| `rejector_lib/scoring.py` | applying a task's evaluation to one response |
| `rejector_lib/evaluation.py` | extraction and the deterministic evaluations |
| `rejector_lib/judge.py` | the `llm_judge` scoring call |
| `rejector_lib/script_eval.py` | the `script` evaluation's shell command |
| `rejector_lib/report.py` | result rows and the stdout summary |
| `rejector_lib/resume.py` | how much of an existing output file to keep |
| `rejector_lib/estimate.py` | the `--dry-run` estimate |
| `rejector_lib/progress.py` | the `--progress` status line |
| `tests/mock_server.py` | mock API with configurable capacity and failures |

Requests run concurrently: each task keeps up to `rate_limits.max_concurrent`
in flight (without one, a minute's worth of `rpm`, capped at 256), tasks run
alongside each other, and a task's judge calls share its budgets and its
per-task totals. `AMBIGUITIES.md` records where the spec allowed more than one
reading and which one this implementation takes.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
