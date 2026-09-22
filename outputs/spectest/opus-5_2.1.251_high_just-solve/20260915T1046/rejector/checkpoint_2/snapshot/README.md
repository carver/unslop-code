# rejector

A CLI that reads a YAML config plus JSONL input, calls an OpenAI-compatible
`/v1/chat/completions` endpoint concurrently, and writes one JSONL result per
input row. A config holds either a single task (`task:`) or several named tasks
(`defaults:` + `tasks:`) that run together.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python rejector.py run --config examples/task.yaml \
    --input examples/data.jsonl --output results.jsonl
```

Multiple named tasks:

```bash
# explicit mapping mode
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input gsm8k=examples/data/gsm8k.jsonl --input mmlu=examples/data/mmlu.jsonl \
    --output results/

# directory mode: looks for <task_name>.jsonl
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input-dir examples/data --output results/

# run a subset; inputs for unselected tasks are neither required nor read
.venv/bin/python rejector.py run --config examples/multi.yaml \
    --input-dir examples/data --output results/ --task gsm8k --task review
```

Optional overrides (each replaces the corresponding config value, for every
selected task): `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature`, `--n`, and `--eval-model` (the judge model of every selected
`llm_judge` task).

Exit codes: `0` on success, `1` on any configuration or input error (message on stderr).

## Multi-task configs

`defaults` supplies shared values and each task overrides them; nested sections
(`prompt`, `generation`, `evaluation`, `judge_prompt`) are merged key by key, so
a task can override `generation.scheme` while inheriting `generation.max_tokens`.
Required fields may come from either side. The task name is the key in `tasks`.
A config with a top-level `task` key is the single-task format and behaves
exactly as before (its name is `task.name`).

`--input <task=path>` and `--input-dir` are alternative modes and cannot be
combined. `--output` must be a directory for multi-task configs; each executed
task writes `<output_dir>/<task_name>.jsonl`, in input order. Tasks run
concurrently and their requests interleave.

## Schemes

| scheme | temperature | attempts |
|---|---|---|
| `greedy` | forced to `0.0` | 1 (`n` ignored) |
| `sample` | must be `> 0` | 1 (`n` ignored) |
| `rejection` | must be `> 0` | up to `n`, stops at the first response that passes evaluation |

`evaluation` is required for `rejection`, optional otherwise; when it is omitted
`result.passed` is `null` and such rows count as passed in the summary as long as
the API call succeeded.

Evaluation types: `exact_match` and `contains` (both need `answer_field`),
`regex` (needs `pattern`), `script` and `llm_judge`. Extract methods:
`last_number`, `last_line`, `full` (default), `letter` and `first_number`.
`exact_match` compares the extracted value to the row's `answer_field`,
tolerating surrounding whitespace, thousands separators, `$`/`%` and a trailing
period, and comparing numerically when both sides are numeric.

`letter` picks the first standalone `A`-`D` (`A`, `(A)`, `A)`, `Answer: A`);
`first_number` picks the first integer or decimal.

### `script`

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

`command_template` may reference row fields and `__response__`; if a row field
expands to text that itself contains `{__response__}`, that is substituted too,
so a row can carry its own test snippet. The rendered command runs in a shell
(its own process group) and passes when its exit code equals `success_exit_code`.
stdout and stderr are captured but never written to the output. The command is
killed after 10 seconds, which counts as a failed evaluation.

### `llm_judge`

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7
  extract: "first_number"
  model: "gpt-4"          # optional; defaults to the task's model
```

The judge is a second call to the same server, made after the generation it
scores. The score is extracted with `extract` (default `first_number`) and the
row passes when `score >= threshold`. `result.judge_score` holds the score and
`meta.judge_meta` the judge call's tokens, latency, model and finish reason (one
per attempt for rejection rows). Judge calls count toward throughput,
`total_api_calls` and the task's `total_api_calls`, and interleave freely with
other work.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"<output_field>": "..."} , "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {...}}
```

`output` is `null` when every attempt fails; `meta` is a single object for
one-attempt rows and a list (one entry per logical attempt) for multi-attempt
rejection rows. `llm_judge` rows add `result.judge_score` and `meta.judge_meta`.

A JSON summary is printed to stdout when the run finishes. For multi-task
configs it also carries a `tasks` object, keyed by the name of each task that
actually ran:

```json
{"total": 200, "passed": 170, "failed": 30, "total_api_calls": 350,
 "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
 "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_api_calls": 142}}}
```

## Concurrency

Rows are processed as concurrent asyncio tasks over a shared HTTP connection
pool, with in-flight work capped per task at `max(8, min(rpm, 256))` requests
(never more than that task's row count); tasks run against that pool at the same
time. The server queues internally, so the client keeps its
queue non-empty rather than pacing itself; measured throughput lands at ~99% of
the configured `rpm` against a server whose capacity is `rpm` (see
`tests/test_all.py`). New connections ramp over the first ~0.25 s to avoid
overflowing a small listen backlog.

## Retries

HTTP `5xx` responses and transport errors are retried up to 3 times (4 HTTP
calls maximum per logical attempt) with exponential backoff. Every HTTP call
counts toward `total_api_calls`, but retries never increase `result.attempts`.
When retries are exhausted the row is emitted with `output: null`, counted as
failed, and the run continues. HTTP `4xx` is treated as an immediate row failure.

## Tests

```bash
.venv/bin/python tests/test_all.py
```

Spawns mock servers (`tests/mock_server.py`, which queues requests behind a
worker pool so its capacity is a real rpm ceiling) and exercises all three
schemes, every evaluation and extract method, retry/failure paths, CLI
overrides, config/input validation, and the throughput target, plus multi-task
configs: `defaults` merging, both input modes, `--task` selection, `--eval-model`,
judge scoring/metadata/retries, and script pass/fail/timeout handling.
