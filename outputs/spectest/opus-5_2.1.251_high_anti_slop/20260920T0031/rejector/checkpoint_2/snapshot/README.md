# rejector

A CLI that runs YAML-defined prompt tasks over JSONL datasets against an
OpenAI-compatible chat completions API, evaluates each response, and writes one
JSONL result row per input row.

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
`--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`, `--temperature`,
`--n`, and `--eval-model` for the judge model of `llm_judge` tasks.

Exit codes: `0` on success, `1` for a configuration or input error (the message
goes to stderr). The run summary is printed to stdout as a single JSON object.

## Configuration

A single-task config is a `task` mapping:

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"   # required
  model: "gpt-4"                     # required
  rpm: 60                            # request budget per minute (default 60)

  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"               # required; {field} is taken from the input row

  generation:
    scheme: "greedy"                 # greedy | sample | rejection (default greedy)
    temperature: 0.0
    max_tokens: 512                  # default 512
    n: 1                             # rejection sampling attempts (default 1)

  evaluation:                        # required for rejection, optional otherwise
    type: "exact_match"              # exact_match | contains | regex | llm_judge | script
    answer_field: "answer"           # required for exact_match and contains
    extract: "last_number"           # last_number | first_number | letter | last_line | full
    # pattern: "####\\s+\\d+"        # required for regex

  output_field: "solution"           # required; names the key inside "output"
```

A multi-task config names its tasks under `tasks` and shares values through
`defaults` (see `examples/multi.yaml`):

```yaml
defaults:
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60
  generation:
    max_tokens: 512

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

Each task overrides `defaults`, and the `prompt`, `generation` and `evaluation`
sections are merged key by key, so a task only restates what it changes. Every
field that is required of a single task must still come from `defaults` or from
the task itself. Task names come from the `tasks` keys; for a single-task
config the name is `task.name`.

### Schemes

| Scheme | Temperature | Attempts per row |
| --- | --- | --- |
| `greedy` | forced to `0.0` | 1 |
| `sample` | must be `> 0` | 1 |
| `rejection` | must be `> 0` | up to `n`, stopping at the first response that passes evaluation |

A rejection row that never passes is written with `"output": null`,
`"passed": false` and one metadata entry per attempt.

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

## Behaviour notes

- **Concurrency.** Each task paces its own requests with a token bucket sized to
  its `rpm`. The bucket starts full, so a run can put a minute of budget in
  flight immediately and then settles at `rpm` requests per minute — enough
  in-flight work to keep a queueing server busy instead of idling between
  responses. Tasks run concurrently with each other, and their requests may be
  interleaved, but each output file keeps its input's row order.
- **Retries.** An HTTP 5xx is retried up to 3 times (4 requests in total). Once
  the budget is spent the row is written with a `null` output and counted as
  failed. Retries count toward `total_api_calls` but never toward
  `result.attempts`, which only counts logical generation attempts. Any other
  non-2xx status is reported as an error and stops the run with exit code 1.
- **Summary.** `total_api_calls`, `throughput_rpm` and the token totals cover
  every request the run made, judge calls included. The `tasks` object breaks
  the counts down by task, listing only the tasks that ran.
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
| `dataset.py` | JSONL input/output and per-row validation |
| `templates.py` | prompt, judge prompt and command template rendering |
| `api.py` | async chat completions client, rate limiter, retries |
| `evaluation.py` | answer extraction and the text-only pass/fail checks |
| `judge.py` | `llm_judge` evaluation |
| `script_eval.py` | `script` evaluation |
| `runner.py` | per-row schemes, evaluation dispatch, concurrency |
| `summary.py` | run and per-task aggregation of the finished rows |
| `errors.py` | the user-facing error type |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

`tests/mock_server.py` is a standalone OpenAI-compatible mock used by the
end-to-end tests; it processes a bounded number of requests at a time so extra
requests queue, and it can inject 5xx failures and wrong answers:

```bash
.venv/bin/python tests/mock_server.py --port 8000 --rpm 60 --latency 3.0 --accuracy 0.5
python rejector.py run --config examples/rejection.yaml --input tests/data.jsonl --output out.jsonl
python rejector.py run --config examples/multi.yaml --input-dir examples/data --output results/
```

It answers with the last number in the prompt, which is why `tests/data.jsonl`
states each expected answer in the question — and why the multi-task example
exercises the plumbing rather than producing sensible letters or ratings.
