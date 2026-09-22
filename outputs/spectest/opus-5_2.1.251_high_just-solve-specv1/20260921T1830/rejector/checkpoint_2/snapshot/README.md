# rejector

A CLI that reads a YAML configuration and JSONL input, sends prompts to an
OpenAI-compatible chat completions API concurrently, and writes one JSONL result
per input row. A config either describes a single task (Part 1) or several named
tasks sharing `defaults` (Part 2).

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
`--n`. `--eval-model <string>` overrides the judge model of every selected
`llm_judge` task. `--task <name>` is repeatable and restricts the run to the
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

See `examples/multi.yaml` (all four evaluation styles) and `examples/data/`.

## Schemes

| Scheme      | Behaviour |
|-------------|-----------|
| `greedy`    | `temperature` is forced to `0.0`; `n` is ignored; one attempt per row. |
| `sample`    | Requires `temperature > 0`; `n` is ignored; one attempt per row. |
| `rejection` | Requires `temperature > 0` and an `evaluation` section; makes up to `n` sequential attempts per row and keeps the first passing response. If every attempt is rejected, `output` is `null` and `result.passed` is `false`. |

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
```

Each suite starts and stops its own mock server on a free port. Set `MOCK_PORT`
to point at a server you started yourself instead. Run them one at a time: both
assert on request ordering and throughput.

`tests/mock_server.py` emulates a server that queues work internally: it
processes `capacity` requests at a time, each taking `latency` seconds, so total
throughput is capped and a sequential client cannot reach it. Prompt markers
drive its behaviour: `ALWAYS_500`, `FLAKY2`, `BAD_REQUEST`, `REJECT<n>`,
`NEVER`, `SAY:<text>` (reply verbatim) and, for judge requests, `SCORE=<n>` or
`SCORE=<n1>,<n2>,...` (one score per repeat of the same prompt).

The Part 1 suite covers all three schemes, every Part 1 evaluation type and
extract method, retry/failure behaviour, output and summary shapes, CLI
overrides, config/input validation, ordering and throughput. The Part 2 suite
covers `defaults`/task merging, both input modes, task selection, output
directories, the `letter` and `first_number` extracts, `script` evaluation
(exit codes, nested `{__response__}`, timeout, stream suppression), `llm_judge`
(scores, thresholds, `judge_meta`, model resolution, rejection loops, call
accounting), the per-task summary, and cross-task concurrency.
