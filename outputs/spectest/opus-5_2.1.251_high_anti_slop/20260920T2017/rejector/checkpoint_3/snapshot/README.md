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
`--n`, `--eval-model`, `--num-solutions`, `--icl-strategy` and `--icl-k`
override the matching config values for every task that runs. `--icl-strategy`
and `--icl-k` only reach tasks that configure ICL, as `--eval-model` only
reaches tasks that evaluate. The command exits `0` on success and `1` on a
configuration or input error.

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

A task asking for a single solution and no ICL examples behaves as before:

| Scheme | Behaviour |
| --- | --- |
| `greedy` | One attempt at `temperature` 0.0; `n` is ignored. |
| `sample` | One attempt at the configured `temperature` (must be > 0); `n` is ignored. |
| `rejection` | Up to `n` attempts, keeping the first that passes the evaluation. Requires an `evaluation` block. |

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
| `icl.py` | ICL setups, their example files, and the setup each attempt uses. |
| `jobs.py` | Matching tasks to their input and output files. |
| `prompts.py` | Template substitution and the messages of one request. |
| `dataset.py` | JSONL reading, prompt preparation, result writing. |
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
with a fixed worker pool that can inject `5xx` responses, control which
attempts pass evaluation, and echo back the ICL examples it was sent.
