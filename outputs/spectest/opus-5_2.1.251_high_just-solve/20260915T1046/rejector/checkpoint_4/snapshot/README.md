# rejector

A CLI that reads a YAML config plus JSONL input, calls an OpenAI-compatible
`/v1/chat/completions` (or `/v1/completions`) endpoint concurrently, and writes
one JSONL result per input row. A config holds either a single task (`task:`) or
several named tasks (`defaults:` + `tasks:`) that run together. Tasks may carry
in-context learning (ICL) setups, collect several solutions per input, and call
tools in an agentic loop.

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

ICL setups and several solutions per input:

```bash
.venv/bin/python rejector.py run --config examples/icl.yaml \
    --input-dir examples/data --output results/ \
    --num-solutions 3 --icl-strategy round_robin --icl-k 2
```

Agentic tasks and `/v1/completions`:

```bash
.venv/bin/python rejector.py run --config examples/agentic.yaml \
    --input examples/agentic.jsonl --output results.jsonl

.venv/bin/python rejector.py run --config examples/task.yaml \
    --input examples/data.jsonl --output results.jsonl \
    --api-type completions --chat-template llama3
```

Optional overrides (each replaces the corresponding config value, for every
selected task): `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature`, `--n`, `--num-solutions`, `--icl-strategy`, `--icl-k`,
`--api-type`, `--chat-template`, and `--eval-model` (the judge model of every
selected `llm_judge` task).

Exit codes: `0` on success, `1` on any configuration or input error (message on stderr).

## Multi-task configs

`defaults` supplies shared values and each task overrides them; nested sections
(`prompt`, `generation`, `evaluation`, `judge_prompt`, `icl`) are merged key by
key, so
a task can override `generation.scheme` while inheriting `generation.max_tokens`.
Required fields may come from either side. The task name is the key in `tasks`.
A config with a top-level `task` key is the single-task format and behaves
exactly as before (its name is `task.name`).

`--input <task=path>` and `--input-dir` are alternative modes and cannot be
combined. `--output` must be a directory for multi-task configs; each executed
task writes `<output_dir>/<task_name>.jsonl`, in input order. Tasks run
concurrently and their requests interleave.

## Schemes

With `num_solutions: 1` and no `icl` section (the part 1/2 default):

| scheme | temperature | attempts |
|---|---|---|
| `greedy` | forced to `0.0` | 1 (`n` ignored) |
| `sample` | must be `> 0` | 1 (`n` ignored) |
| `rejection` | must be `> 0` | up to `n`, stops at the first response that passes evaluation |
| `agentic` | used as given | 1 loop of up to `max_iterations` API requests |

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


## In-context learning

A task may define named ICL setups; each one is a list of examples that are
replayed as alternating user/assistant turns between the system message and the
final user message. Example inputs are rendered with the task's `prompt.user`
template and example outputs are sent verbatim.

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
        - name: "detailed"
          file: "icl/gsm8k_detailed.jsonl"
      k: 2
      strategy: "round_robin"
```

Each setup has a `name` and exactly one of `examples` or `file`. A `file` path is
relative to the config file's directory and must be JSONL whose every non-empty
line is `{"input": <object>, "output": <string>}`; a malformed line ends the run
with exit code 1 before any request is sent. `k` (default: all of the setup's
examples) keeps the first `k` examples of whichever setup is selected.

`strategy` (default `fixed`) decides which setup an attempt uses:

| strategy | behaviour |
|---|---|
| `fixed` | always the first setup |
| `random` | chosen independently for each attempt |
| `round_robin` | cycles through the setups in order across a row's attempts |

`greedy` with ICL and `num_solutions > 1` ignores `strategy`: it walks the setups
in declared order, at most once each, so it can never produce more solutions than
there are setups.

## Multiple solutions

`num_solutions` (in `defaults` or per task, overridden by `--num-solutions`)
asks for several solutions per input row:

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

| scheme | with ICL | without ICL |
|---|---|---|
| `greedy` | one attempt per setup at temperature 0, until `num_solutions` are collected or the setups run out | a single attempt |
| `sample` | one sampled attempt per requested solution, using `strategy` | `num_solutions` independent sampled attempts |
| `rejection` | attempts until `num_solutions` pass or `max_attempts` is spent | the same, with the same prompt every attempt |
| `agentic` | one full tool-calling loop per requested solution, using `strategy` | `num_solutions` independent loops |

Evaluation only gates `rejection`: `greedy` and `sample` emit every generation
they get and record whether it passed. `max_attempts` applies to `rejection` and
defaults to `3 * num_solutions`.

When `num_solutions == 1` and no ICL is configured the part 1 behaviour is kept
exactly: `rejection` makes up to `generation.n` attempts, `max_attempts` is
ignored, and the row keeps the part 1 output shape.

## Agentic generation

`scheme: "agentic"` lets the model call tools in a loop before answering. The
task lists the tools; every handler runs locally in this process.

```yaml
tasks:
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools."
      user: "{question}"
    generation:
      scheme: "agentic"
      max_iterations: 10      # API requests per loop, default 10
      temperature: 0.0
      max_tokens: 512
    output_field: "answer"
    tools:
      - name: "lookup"
        description: "Look up a value in the database by key"
        parameters:           # JSON schema, sent verbatim as the tool's parameters
          type: "object"
          properties:
            key: {type: "string"}
          required: ["key"]
        handler:
          type: "static_map"
          mapping: {"employees": "142"}
          default: "KEY_NOT_FOUND"
```

Handlers:

| type | behaviour |
|---|---|
| `echo` | returns the parsed tool arguments as a JSON string |
| `static_map` | looks the first required parameter up in `mapping`, else `default` (itself defaulting to `"NOT_FOUND"`) |
| `script` | runs `command` with the `arg_field` value as one extra argv entry and returns stdout |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

A `script` handler that exits non-zero or runs longer than 10 seconds returns
`"ERROR: <stderr or timeout message>"` instead of stdout.

The loop builds the conversation (system prompt, optional ICL examples, user
prompt) and then, per iteration, sends one API request — in chat mode with the
tool definitions in the request body. A response with `tool_calls` has every
call executed (arguments are parsed as JSON first); the assistant tool-call
message and one `tool` message per result are appended and the loop continues.
A response with text and no tool calls ends the loop. Reaching
`max_iterations` first writes `output: null` and `finish_reason:
"max_iterations"`.

Every request in the loop counts separately toward `total_api_calls`, and rows
keep running concurrently: several rows' loops overlap in flight.

```json
{"input": {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"},
 "output": {"answer": "The total revenue for Q1 and Q2 is $2,730,000."},
 "result": {"passed": true, "extracted_answer": "2730000", "attempts": 1, "iterations": 3,
            "tool_calls": [{"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
                            "result": "1250000"}]},
 "meta": {"total_prompt_tokens": 850, "total_completion_tokens": 120, "total_tokens": 970,
          "latency_ms": 1200, "finish_reason": "stop",
          "iterations_detail": [{"prompt_tokens": 200, "completion_tokens": 30,
                                 "total_tokens": 230, "latency_ms": 300,
                                 "finish_reason": "tool_calls"}]}}
```

`result.iterations` is the number of API requests in the loop and
`result.tool_calls` lists every call in execution order. `meta.total_*` are
summed over the iterations, `meta.latency_ms` is the loop's wall-clock time and
`meta.iterations_detail` holds one entry per request. Evaluation sees the final
text only, so a `max_iterations` row fails; without an `evaluation` section
`result.passed` stays `null`.

`agentic` combines with ICL and `num_solutions`, where each solution is an
independent loop. The row then keeps the list output format: `result.attempts`
counts loops (not requests), `result.passed`/`result.failed` count as before,
and each `meta` entry carries that loop's `total_prompt_tokens`,
`total_completion_tokens`, `total_tokens`, `latency_ms`, `finish_reason`,
`iterations`, `tool_calls` and `iterations_detail` next to checkpoint 3's
`icl_setup` and `evaluation_passed`.

## Completions mode

`api_type: "completions"` (in `defaults`, per task, or via `--api-type`) sends
requests to `{api_url}/v1/completions` with the conversation rendered into a
single `prompt` string by `chat_template` (`--chat-template`, default
`chatml`):

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"

tasks:
  gsm8k:
    api_type: "completions"
    chat_template: "chatml"
```

The request carries `model`, `prompt`, `temperature` and `max_tokens`, and the
reply is read from `choices[0].text`. Built-in templates are `chatml`,
`llama3`, `mistral` and `zephyr`; each repeats its role markers for every
message, so ICL turns and agentic tool results render correctly (`mistral` has
no system role, so system text is folded into the first instruction block).
Judge calls of an `llm_judge` evaluation use the same endpoint and template.

In completions mode an agentic task renders its tool declarations into the
prompt instead of sending a `tools` field, and reads tool calls back out of the
response text:

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

Results are appended as `tool`-role turns and rendered with the template's tool
markers for the next iteration.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"<output_field>": "..."} , "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {...}}
```

`output` is `null` when every attempt fails; `meta` is a single object for
one-attempt rows and a list (one entry per logical attempt) for multi-attempt
rejection rows. `llm_judge` rows add `result.judge_score` and `meta.judge_meta`.

As soon as a task configures ICL or asks for more than one solution, that row
format changes: `output` becomes a list and `meta` always a list, one entry per
attempt.

```json
{"input": {"question": "What is 15 + 27?", "answer": "42"},
 "output": [{"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
            {"solution": "#### 42", "icl_setup": "direct"}],
 "result": {"passed": 2, "failed": 5, "attempts": 7},
 "meta": [{"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
           "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
           "icl_setup": "chain_of_thought", "evaluation_passed": true}]}
```

Each solution carries the task's `output_field` plus `icl_setup` (the setup that
produced it, or `null` without ICL). `result.passed` counts passing solutions,
`result.failed` counts failed attempts and `result.attempts` counts all
generation attempts for the row. Without an `evaluation` section every
`evaluation_passed` is `null`, `result.passed` is the number of emitted outputs
and `result.failed` the number of attempts that produced none.

A JSON summary is printed to stdout when the run finishes. For multi-task
configs it also carries a `tasks` object, keyed by the name of each task that
actually ran:

```json
{"total": 200, "passed": 170, "failed": 30, "total_api_calls": 350,
 "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
 "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
                     "avg_solutions_per_input": 4.5, "total_api_calls": 850}}}
```

Every per-task entry reports `total_solutions` and `avg_solutions_per_input`; a
row counts as passed when at least one of its solutions passed. The same two
fields appear at the top level when any task in the run emits multiple
solutions.

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
judge scoring/metadata/retries, and script pass/fail/timeout handling. Part 3
adds ICL message layout, inline and file-backed setups, every strategy, `k`
selection, all scheme/`num_solutions` combinations, partial rejection results,
the list output format, the new summary fields, the CLI overrides, and the ICL
validation errors (which must exit 1 with no request sent). Part 4 adds the
agentic loop (single and multiple tool calls, every handler type, script
failures and timeouts, `max_iterations`, list-format loops, concurrency), the
completions endpoint and payload shape, exact renderings of all four built-in
templates for multi-turn conversations, agentic tool calling over
`/v1/completions`, and the new CLI/config validation errors.
