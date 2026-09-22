# rejector

A CLI that reads a YAML task config plus JSONL input, sends prompts to an
OpenAI-compatible chat completions API concurrently, and writes one JSONL result
per input row. A config can hold a single task or many named tasks that run
together.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

Single-task config -> one input file, one output file:

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Multi-task config -> one input per task, one output file per task in a directory.
Either map inputs explicitly or point at a directory of `<task_name>.jsonl`:

```bash
.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/
```

The two input modes are alternatives; combining them is an error.

`--task <name>` (repeatable) restricts the run to the named tasks. Unselected
tasks are skipped entirely: they need no input file, are not validated, and get
no output file.

```bash
.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --output results/ --task gsm8k
```

Optional overrides, each replacing the matching config value for every task that
runs: `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature`, `--n`, `--num-solutions`, `--icl-strategy`, `--icl-k`, and
`--eval-model` (the judge model for `llm_judge` tasks).

Exit codes: `0` on success, `1` on a configuration or input error (message on stderr).

## Config

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60
  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"
  generation:
    scheme: "greedy"      # greedy | sample | rejection
    temperature: 0.0
    max_tokens: 512
    n: 1
  evaluation:
    type: "exact_match"   # exact_match | contains | regex
    answer_field: "answer"
    extract: "last_number"  # last_number | last_line | full
  output_field: "solution"
```

### Multi-task config

`defaults` supplies shared values and `tasks` maps a name to each task. Every
required field may come from either side, and nested sections (`prompt`,
`generation`, `evaluation`) are merged key by key with the task winning.

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

  review:
    prompt:
      system: "You are a writing assistant. Write a response to the given prompt."
      user: "{prompt_text}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
        user: "Rate the quality of this response.\n\nResponse:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"
```

A config with a top-level `task` key is the single-task format above; its task
name is `task.name`.

### Notes

- `greedy` forces `temperature: 0.0` and ignores `n`.
- `sample` and `rejection` require `temperature > 0`; `sample` ignores `n`.
- `rejection` makes up to `n` attempts and keeps the first response that passes
  evaluation; if none pass, `output` is `null` and `result.passed` is `false`.
  With ICL or `num_solutions > 1`, `generation.max_attempts` takes over from `n`
  (see [Multiple solutions](#multiple-solutions)).
- `evaluation` is required for `rejection` and optional otherwise. Without it,
  `result.passed` is `null`.

### Extraction methods

| `extract` | takes |
| --- | --- |
| `full` | the whole response, stripped |
| `last_line` | the last non-blank line |
| `last_number` | the last integer or decimal |
| `first_number` | the first integer or decimal |
| `letter` | the first standalone `A`-`D`, so `A`, `(A)`, `A)` and `Answer: A` all give `A` |

### Evaluation types

`exact_match`, `contains` and `regex` work on the response text as in Part 1.

`llm_judge` scores the response with a second API call through the same server:

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:
    system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7
  extract: "first_number"
  model: "gpt-4"        # optional; defaults to the task's model
```

`judge_prompt` follows the normal template rules, plus `{__response__}` for the
generated text. The extracted score lands in `result.judge_score` and passes
when it is `>= threshold`; the judge call's own usage, latency, model and finish
reason land in `meta.judge_meta`. Judge calls count toward throughput,
`total_api_calls` and the task's API call total, and are paced and interleaved
alongside every other request.

`script` runs a shell command and checks its exit code:

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

`command_template` may reference row fields and `{__response__}`. When a row
field expands to text that itself contains `{__response__}` - a `test_code`
column carrying its own harness, say - that placeholder is substituted before
the command runs. Exiting with `success_exit_code` passes; anything else fails.
Command output is captured (so a chatty script cannot deadlock on a full pipe)
but never written to the JSONL. Commands run in their own process group and are
killed after 10 seconds, which counts as a failed evaluation.

## In-context learning

A task may carry named ICL setups. Each setup is inserted between the system
message and the real user message as alternating user/assistant turns: every
example's `input` is rendered with the task's own `prompt.user` template and its
`output` becomes the assistant reply verbatim.

```yaml
tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem step by step. Final answer after ####."
      user: "{question}"
    icl:
      setups:
        - name: "chain_of_thought"
          examples:
            - input: {question: "What is 2+2?"}
              output: "Let me think step by step.\n2 + 2 = 4\n#### 4"
        - name: "direct"
          examples:
            - input: {question: "What is 2+2?"}
              output: "#### 4"
        - name: "detailed"
          file: "icl/gsm8k_detailed.jsonl"
      k: 2
      strategy: "round_robin"
```

Each setup needs a `name` and exactly one of `examples` or `file`. A `file` path
is resolved against the config file's directory and must be JSONL whose non-empty
lines each look like:

```jsonl
{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"}
```

A malformed line, or one missing `input`/`output`, ends the run with exit code 1
before any request is sent.

`icl.k` caps how many of the setup's examples are used, taking the first `k`; it
defaults to all of them. `icl.strategy` picks which setup an attempt uses:

| `strategy` | picks |
| --- | --- |
| `fixed` | the first setup, every attempt |
| `random` | an independently chosen setup per attempt |
| `round_robin` | the setups in order, cycling: `A B C A B ...` |

`greedy` with ICL and `num_solutions > 1` is the one exception: it ignores the
strategy and walks the setups in declared order, using each at most once.

## Multiple solutions

`num_solutions` asks for more than one solution per input row. It may live in
`defaults` or on a task, and `--num-solutions` overrides both.

```yaml
tasks:
  gsm8k:
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
      max_attempts: 15
    num_solutions: 5
```

How each scheme collects them:

| scheme | with ICL | without ICL |
| --- | --- | --- |
| `greedy` | one `temperature: 0` call per setup, in declared order, stopping at `num_solutions` or when the setups run out | a single deterministic call |
| `sample` | one sampled call per requested solution, choosing a setup by `icl.strategy`; evaluation does not gate inclusion | `num_solutions` independent sampled calls |
| `rejection` | keeps generating and evaluating until `num_solutions` pass or `max_attempts` is spent | the same, with the same prompt every attempt |

Because a greedy setup is deterministic, greedy can never produce more solutions
than there are setups - two setups with `num_solutions: 5` yield two solutions,
and no setup is retried to manufacture more.

`generation.max_attempts` bounds rejection sampling and defaults to
`3 * num_solutions`. As a compatibility carve-out, a task with
`num_solutions: 1` and no ICL keeps the Part 1 rejection behaviour exactly:
`generation.n` logical attempts, and `max_attempts` is ignored.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"solution": "..."}, "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {"model": "gpt-4", "prompt_tokens": 45, "completion_tokens": 120, "total_tokens": 165, "latency_ms": 230, "finish_reason": "stop"}}
```

`meta` is a single object for one-attempt rows and a list (one entry per attempt)
for rejection rows that took more than one attempt. For `llm_judge` tasks each
attempt's `meta` carries a `judge_meta` object and `result` carries
`judge_score`.

### Rows with ICL or multiple solutions

As soon as a task configures `icl` or sets `num_solutions > 1`, the row format
switches: `output` becomes a list, and `meta` is always a list with one entry per
attempt. A task with `num_solutions: 1` and no ICL keeps the format above.

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

Each output item holds the task's `output_field` plus the `icl_setup` that
produced it, which is `null` when the task has no ICL. `result.attempts` counts
every generation attempt for the row, `result.passed` counts the passing
solutions and `result.failed` is the rest. When `evaluation` is omitted,
`evaluation_passed` is `null` on every entry, `result.passed` is the number of
emitted outputs and `result.failed` is the number of attempts that produced
none.

Rejection stops early once it has `num_solutions` passing solutions, and writes
whatever it collected if `max_attempts` runs out first - `num_solutions: 5` with
`max_attempts: 10` and only two passes reports `passed: 2`, `failed: 8`,
`attempts: 10`.

Multi-task runs write `<output_dir>/<task_name>.jsonl` per executed task; row
order within each file matches its input file.

A JSON summary is printed to stdout when the run finishes. For multi-task
configs it also carries a `tasks` object holding the tasks that actually ran:

```json
{
  "total": 200, "passed": 170, "failed": 30,
  "total_prompt_tokens": 9000, "total_completion_tokens": 24000,
  "total_api_calls": 350, "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
  "tasks": {
    "gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
              "avg_solutions_per_input": 4.5, "total_api_calls": 142},
    "review": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 100,
               "avg_solutions_per_input": 1.0, "total_api_calls": 208}
  }
}
```

A task's `total_solutions` is how many output items it wrote in total and
`avg_solutions_per_input` divides that by its row count. A row counts as
`passed` when it produced at least one passing solution. The run-wide summary
gains the same two fields whenever any row used the list format.

## Concurrency

Requests are issued concurrently and paced by a token bucket set to the
configured `rpm`. The bucket's capacity — the number of requests allowed in
flight — starts small and grows with observed latency (Little's law: sustaining
`rate` requests per second against `L`-second requests needs `rate * L` in
flight). That fills the pipeline once, then holds the steady-state issue rate at
roughly the configured budget. `5xx` responses are retried up to 3 times; retries
count toward `total_api_calls` but not toward `result.attempts`.

Every task in a multi-task run shares one transport and one event loop, so rows
from different tasks are issued concurrently and interleave freely. Tasks that
target the same `api_url` share a rate limiter, which keeps `rpm` a budget for
that server rather than a per-task multiplier.

## Tests

```bash
.venv/bin/python tests/run_tests.py
```

Spins up a mock OpenAI-compatible server (`tests/mock_server.py`) that queues
requests with a bounded worker pool, and exercises the schemes, evaluation types,
extraction methods, ICL setups and strategies, multi-solution collection, retry
behaviour, validation errors, and throughput.
