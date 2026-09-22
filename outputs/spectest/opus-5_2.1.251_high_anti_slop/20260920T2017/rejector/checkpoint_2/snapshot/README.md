# rejector

A CLI that runs YAML-configured generation tasks over JSONL input files
against an OpenAI-compatible chat completions API, evaluates each response,
and writes one JSONL result per input row.

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

`--input` and `--input-dir` are alternative ways to find inputs and cannot be
combined; `--input-dir` looks for `<task_name>.jsonl`. `--task` is repeatable
and limits the run to the tasks it names — other tasks are neither validated
nor given an input.

`--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`, `--temperature`,
`--n` and `--eval-model` override the matching config values for every task
that runs. The command exits `0` on success and `1` on a configuration or
input error.

## Configuration

A single-task config is one `task` mapping (see `examples/task.yaml`). A
multi-task config is a `defaults` mapping plus a `tasks` mapping keyed by task
name (see `examples/multi.yaml`); each task is layered onto `defaults`, with
nested sections such as `prompt`, `generation` and `evaluation` merged key by
key. Required fields may come from either layer.

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

| Scheme | Behaviour |
| --- | --- |
| `greedy` | One attempt at `temperature` 0.0; `n` is ignored. |
| `sample` | One attempt at the configured `temperature` (must be > 0); `n` is ignored. |
| `rejection` | Up to `n` attempts, keeping the first that passes the evaluation. Requires an `evaluation` block. |

Rows that never produce a passing response are written with `"output": null`
and `"passed": false`.

## Summary

A run prints a JSON summary to stdout. A multi-task run adds a `tasks` object
holding the same counts for each task that ran, including the API calls its
judge made:

```json
{"total": 200, "passed": 170, "failed": 30, "total_prompt_tokens": 2000,
 "total_completion_tokens": 1000, "total_api_calls": 350,
 "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
 "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_api_calls": 142},
           "review": {"total": 100, "passed": 85, "failed": 15, "total_api_calls": 208}}}
```

## Throughput

Rows are processed concurrently, and so are the tasks themselves: requests
from different tasks interleave freely. Each task has its own `RateLimiter`
pacing its request starts at its `rpm`, with a few seconds of burst allowance
so the server's queue stays fed instead of being drip-fed one request at a
time. Within each task's output file, rows stay in input order.

## Layout

| File | Contents |
| --- | --- |
| `rejector.py` | Argument parsing and the top-level run/exit-code flow. |
| `config.py` | Task config dataclasses, defaults merging, and validation. |
| `jobs.py` | Matching tasks to their input and output files. |
| `dataset.py` | JSONL reading, template rendering, result writing. |
| `evaluation.py` | Answer extraction and the response-only checks. |
| `verdicts.py` | Judging a response, including the `script` and `llm_judge` modes. |
| `client.py` | Rate limiting, HTTP calls, retries, and run counters. |
| `runner.py` | Per-row schemes, concurrency, records, and the summary. |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

The end-to-end tests drive the CLI against `tests/mock_server.py`, a mock API
with a fixed worker pool that can inject `5xx` responses and control which
attempt passes evaluation.
