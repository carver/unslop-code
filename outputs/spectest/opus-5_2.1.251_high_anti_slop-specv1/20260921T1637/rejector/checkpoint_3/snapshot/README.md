# rejector

A CLI that runs YAML-described generation tasks over JSONL input files against
an OpenAI-compatible chat completions API, evaluates each response, and writes
one JSONL result per input row.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

A single-task config takes one input file and writes one output file:

```bash
.venv/bin/python rejector.py run \
  --config examples/task.yaml \
  --input examples/data.jsonl \
  --output results.jsonl
```

A multi-task config writes `<output_dir>/<task_name>.jsonl` per task, and takes
its inputs either as `task=path` pairs or from a directory of
`<task_name>.jsonl` files (the two modes cannot be combined):

```bash
.venv/bin/python rejector.py run --config examples/multi.yaml \
  --input gsm8k=examples/data/gsm8k.jsonl --input mmlu=examples/data/mmlu.jsonl \
  --output results/ --task gsm8k --task mmlu

.venv/bin/python rejector.py run --config examples/multi.yaml \
  --input-dir examples/data --output results/
```

`--task` is repeatable and restricts the run: tasks it leaves out need no input
file and produce no output file.

Any of `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature`, `--n`, `--num-solutions`, `--icl-strategy`, and `--icl-k`
override the matching config value for every task that runs, and
`--eval-model` overrides the judge model of every `llm_judge` task. The run
prints a JSON summary to stdout and exits `0`; configuration and input problems
print a message to stderr and exit `1`.

## Configuration

`examples/task.yaml` is the single-task format: one top-level `task` mapping,
whose `name` names the task. `examples/multi.yaml` is the multi-task format:
each entry of `tasks` is layered on top of `defaults`, with nested sections
(`prompt`, `generation`, `evaluation`) merged key by key, so shared settings
live in `defaults` and each task overrides only what differs. Every required
field must come from one of the two.

- `prompt.system` / `prompt.user` are templates with `{field}` placeholders
  filled from each input row. `prompt.system` is optional.
- `generation.scheme`:
  - `greedy` forces `temperature` to `0.0`, one response per row.
  - `sample` requires `temperature > 0`, one response per row.
  - `rejection` requires `temperature > 0` and an `evaluation`; it makes up to
    `n` attempts and keeps the first response that passes.
- `num_solutions` (default `1`) asks for several solutions per row; see
  [Multiple solutions](#multiple-solutions).
- `evaluation.extract` selects the value reported as
  `result.extracted_answer`: `last_number`, `first_number`, `last_line`,
  `letter` (the first standalone `A`–`D`, so `B`, `(B)`, `B)` and `Answer: B`
  all yield `B`), or `full`. The default is `full`, except for `llm_judge`
  where a score has to be numeric and the default is `first_number`.
- `output_field` names the key the response is written under.

### Evaluation types

Without an `evaluation` block, `result.passed` is `null`.

| Type | Required fields | Passes when |
| --- | --- | --- |
| `exact_match` | `answer_field` | the extracted answer equals the row's answer, compared numerically when both sides are numbers |
| `contains` | `answer_field` | the row's answer appears anywhere in the response |
| `regex` | `pattern` | the pattern matches the response |
| `script` | `command_template` | the command exits with `success_exit_code` (default `0`) |
| `llm_judge` | `judge_prompt`, `threshold` | the judge's score is `>= threshold` |

`script` renders `command_template` from the row plus `{__response__}` and runs
it in a shell. A row field may itself contain `{__response__}` — a `test_code`
field holding the test harness, say — and it is substituted before the command
runs, so the generated code can be executed directly:

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0
```

The command's stdout and stderr are captured and discarded; only the exit code
decides. A command still running after `COMMAND_TIMEOUT_SECONDS` (10s) is
killed and the row fails.

`llm_judge` sends a second request through the same server, using
`evaluation.model` or the task's model, and the same template rules with
`{__response__}` bound to the generated response. The score parsed out of the
judge's reply is reported as `result.judge_score`, the text `extract` took from
that reply is `result.extracted_answer`, and the judge call's own metadata is
nested in the row's `meta` as `judge_meta`. Judge calls share the task's rate
budget and count toward `total_api_calls` and the task's throughput.

### In-context learning

A task may carry an `icl` block of named setups, each holding demonstrations
that are inserted between the system message and the row's own question as
alternating user and assistant turns. Every example's `input` is rendered with
the task's `prompt.user` template; its `output` is used verbatim as the
assistant reply.

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

A setup defines exactly one of `examples` and `file`. A `file` is a JSONL file
of `{"input": {...}, "output": "..."}` objects, resolved relative to the config
file; a malformed line or a missing key ends the run with exit code 1 before
any request is sent. `k` caps how many of a setup's examples are shown (the
first `k`, all of them by default).

`strategy` decides which setup an attempt uses: `fixed` always takes the first,
`random` draws one per attempt, and `round_robin` cycles through them in
declared order. Greedy generation ignores the strategy: being deterministic, it
walks the setups in order and uses each at most once, so it can never produce
more solutions than there are setups.

`examples/icl.yaml` is a worked example of both setup styles.

### Multiple solutions

`num_solutions` may be set in `defaults` or on a task, and asks for that many
solutions per input row:

- `greedy` generates once per setup, in declared order.
- `sample` makes one sampled request per requested solution and keeps each
  response, whatever the evaluation says.
- `rejection` keeps generating and evaluating until `num_solutions` responses
  have passed or `generation.max_attempts` is exhausted, keeping only the
  passing ones. `max_attempts` defaults to three attempts per requested
  solution.

A task asking for one solution without ICL keeps the Part 1 behaviour: the
`rejection` scheme makes up to `generation.n` attempts and `max_attempts` does
not apply.

## Output

One JSON object per input row, in input order:

```json
{
  "input": {"prompt_text": "...", "criteria": "clarity"},
  "output": {"response": "..."},
  "result": {"passed": true, "extracted_answer": "8", "attempts": 1, "judge_score": 8},
  "meta": {"model": "gpt-4", "prompt_tokens": 12, "completion_tokens": 40,
           "total_tokens": 52, "latency_ms": 310, "finish_reason": "stop",
           "judge_meta": {"model": "gpt-4", "...": "..."}}
}
```

`judge_score` and `judge_meta` appear only for `llm_judge` tasks, and `meta` is
a list of per-attempt objects when a rejection task made several attempts.

A task with ICL or `num_solutions > 1` writes the list format instead: `output`
holds one object per kept solution, naming the `icl_setup` that produced it
(`null` without ICL), `result` counts solutions rather than describing one, and
`meta` always has one entry per attempt.

```json
{
  "input": {"question": "What is 15 + 27?", "answer": "42"},
  "output": [{"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"}],
  "result": {"passed": 1, "failed": 2, "attempts": 3},
  "meta": [{"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
            "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
            "icl_setup": "chain_of_thought", "evaluation_passed": true}]
}
```

`result.passed` counts the solutions that passed their evaluation, or the
emitted solutions when the task has no evaluation, and `result.failed` is the
rest of the attempts. Without an evaluation, `evaluation_passed` is `null`.

The stdout summary adds a `tasks` object, keyed by the tasks that actually ran,
to the Part 1 totals; single-task configs keep the Part 1 summary unchanged.

```json
{
  "total": 200, "passed": 170, "failed": 30,
  "total_prompt_tokens": 4100, "total_completion_tokens": 9000,
  "total_api_calls": 850, "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
  "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
                      "avg_solutions_per_input": 4.5, "total_api_calls": 850}}
}
```

## Throughput

`rpm` is treated as the server's request budget. Each task gets its own token
bucket (`ratelimit.py`) pacing requests at that rate, allowing a tenth of the
budget as an initial burst so the server's queue fills immediately, and its own
pool of workers (sized to the budget, capped at `MAX_WORKERS`) keeping that
many requests in flight. Tasks run concurrently over one shared HTTP client, so
their requests interleave. Workers pull row indices from their task's queue in
input order and each one owns its row's response, so every output file stays
aligned with its input regardless of completion order.

A `5xx` response or a transport failure is retried up to 3 requests in total per
attempt. Retries count toward `total_api_calls` but not toward
`result.attempts`; a row that never gets a response has `output: null` and is
counted as failed.

## Layout

| File | Responsibility |
| --- | --- |
| `rejector.py` | entry point |
| `cli.py` | argument parsing, exit codes, summary printing |
| `config.py` | YAML loading, defaults merging, override merging, validation |
| `jobs.py` | task selection and input/output file resolution |
| `dataset.py` | JSONL loading, prompt rendering, per-row field checks |
| `templates.py` | `{field}` template rendering |
| `icl.py` | ICL setups: loading, rendering, per-attempt selection |
| `schemes.py` | greedy / sample / rejection generation logic |
| `pipeline.py` | worker pools and per-run orchestration |
| `ratelimit.py` | request pacing |
| `api.py` | HTTP client, retries, call statistics |
| `extraction.py` | answer extraction methods |
| `evaluation.py` | pass/fail checks |
| `judge.py` | `llm_judge` scoring calls |
| `script_eval.py` | `script` command execution |
| `results.py` | result records, JSONL output, run summary |
| `errors.py` | user-facing error types |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

`tests/mock_server.py` is a small stand-in API that serves a fixed number of
requests concurrently after a configurable delay, can fail a prompt's first
`N` attempts (`--pass-after`), pass only every `N`th attempt (`--pass-every`)
or reply `503` to everything (`--always-fail`), and answers any prompt whose
system message mentions "judge" with `--judge-score`. Its replies echo the
last user message, the temperature, and the number of messages received, so
tests can see which ICL turns were sent.
