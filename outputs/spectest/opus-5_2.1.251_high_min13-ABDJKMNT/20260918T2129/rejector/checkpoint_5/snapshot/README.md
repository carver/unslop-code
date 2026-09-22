# rejector

A CLI that runs YAML-configured generation tasks over JSONL input against an
OpenAI-compatible API - chat completions, or text completions with a chat
template - and writes one JSONL result per input row.

```bash
# single-task config (Part 1 format)
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

# multi-task config, explicit input mapping
python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/

# multi-task config, one <task_name>.jsonl per task in a directory
python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

A config with a top-level `task` mapping is the single-task format; a config
with `defaults` plus a `tasks` mapping declares several named tasks, each
merged over `defaults`. Multi-task runs write `<output_dir>/<task_name>.jsonl`
and add a `tasks` breakdown to the summary.

Optional overrides: `--api-url`, `--model`, `--rpm`, `--tpm`,
`--max-concurrent`, `--budget`, `--max-tokens`, `--scheme`, `--temperature`,
`--n`, `--eval-model`, `--num-solutions`, `--icl-strategy`, `--icl-k`,
`--api-type`, `--chat-template`, and `--task` (repeatable) to run a subset of
the configured tasks. Run modes: `--resume`, `--dry-run`, `--progress`. Exit
code `0` on success, `1` for a configuration or input error (message on
stderr). The run summary is printed to stdout as a single JSON object.

## Evaluation types

| Type | Passes when |
| --- | --- |
| `exact_match` | the extracted value equals `answer_field` |
| `contains` | the response contains the `answer_field` value |
| `regex` | the response matches `pattern` |
| `script` | a rendered shell command exits with `success_exit_code` |
| `llm_judge` | a second model call scores the response `>= threshold` |

Extract methods: `last_number`, `first_number`, `last_line`, `letter`, `full`.

## In-context learning and multiple solutions

A task may declare named ICL setups, inline or from a JSONL file resolved
against the config's directory, and ask for several solutions per input:

```yaml
icl:
  setups:
    - name: "chain_of_thought"
      examples:
        - input: {question: "What is 2+2?"}
          output: "Let me think step by step.\n2 + 2 = 4\n#### 4"
    - name: "detailed"
      file: "icl/gsm8k_detailed.jsonl"
  k: 2                      # examples per prompt; defaults to all of them
  strategy: "round_robin"   # fixed | random | round_robin
num_solutions: 5
```

The `k` selected examples are replayed between the system message and the
row's own question as user/assistant turns. One setup is chosen per attempt:
`fixed` keeps to the first, `random` draws for each attempt, `round_robin`
cycles, and greedy decoding asking for several solutions walks the setups in
declared order instead, once each.

| Scheme | Attempts per row | Solutions kept |
| --- | --- | --- |
| `greedy` | one per setup, capped by `num_solutions` | every response |
| `sample` | `num_solutions` | every response |
| `rejection` | up to `max_attempts` (default `3 * num_solutions`) | passing responses only |
| `agentic` | one tool-calling loop per solution | every loop that answered |

With ICL configured or `num_solutions > 1`, each row's `output` and `meta`
become lists — one entry per kept solution and per attempt — `result` reports
`passed`/`failed`/`attempts` as counts, and the per-task summary adds
`total_solutions` and `avg_solutions_per_input`. A task with one solution and
no ICL keeps the Part 1 row format, including rejection's `generation.n`
attempt budget.

## Agentic tasks

`scheme: "agentic"` lets the model call tools before it answers. Each
iteration is one API request: tool calls are executed locally, appended to the
conversation as tool results, and the loop continues until the model replies
with text or `max_iterations` requests have been made.

```yaml
generation:
  scheme: "agentic"
  max_iterations: 10
tools:
  - name: "lookup"
    description: "Look up a value in the database by key"
    parameters:
      type: "object"
      properties:
        key: {type: "string"}
      required: ["key"]
    handler:
      type: "static_map"
      mapping: {"employees": "142"}
      default: "KEY_NOT_FOUND"
```

| Handler | Result |
| --- | --- |
| `echo` | the parsed arguments as a JSON string |
| `static_map` | `mapping[<first required parameter>]`, else `default` (`NOT_FOUND`) |
| `script` | the stdout of `command <args[arg_field]>`, else `ERROR: ...` |

The `script` handler accepts an optional `timeout` in seconds, defaulting to
ten. A row's `result` gains `iterations` and a `tool_calls` trace, and its
`meta` reports the loop's aggregated tokens and latency plus one
`iterations_detail` entry per request. A loop that never produces text writes
`output: null` with `finish_reason: "max_iterations"`. With ICL or
`num_solutions > 1` each solution is an independent loop, and the row keeps
the list format: `result` counts loops, and each `meta` entry is one loop's
aggregate.

## Completions mode

`api_type: "completions"` posts to `{api_url}/v1/completions` with the
conversation rendered by `chat_template` into a single `prompt` string, and
reads the response from `choices[0].text`. Built-in templates: `chatml`,
`llama3`, `mistral`, `zephyr`; each repeats its role markers for every
message, including the `tool` turns an agentic loop feeds back. Tool
definitions ride in the prompt, and the loop parses tool calls out of
`<tool_call>` blocks in the response text.

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"
```

## Rate limits and cost

```yaml
defaults:
  rate_limits:
    rpm: 100            # sliding 60-second request window; omit to disable
    tpm: 50000          # sliding 60-second token window
    max_concurrent: 10  # hard cap on in-flight requests
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0
```

Before a request is sent its prompt tokens are estimated from the word count
of the rendered messages (`1 token ~= 0.75 words`, rounded up) and
`estimated + max_tokens` is reserved against the token window; the response's
reported usage then replaces that reservation. Judge calls and every agentic
iteration go through the same limiter, and an agentic loop holds one
concurrency slot for its whole lifetime. `rpm` may also be written directly on
the task, as in earlier checkpoints.

Cost is tracked across all tasks at each task's own rates and reported in the
summary's `cost` block. When the running total reaches `budget` the run stops
dispatching, lets in-flight work finish, writes the rows that completed, and
still exits `0` with `cost.budget_exceeded: true`.

## Structured output

```yaml
output_schema:
  type: "object"
  required: ["code", "explanation"]
  properties:
    code: {type: "string"}
    explanation: {type: "string"}
```

The response is parsed as JSON and validated against the draft 7 keywords
`type`, `required`, `properties`, `items`, `enum`, `minimum`, `maximum`,
`minLength`, `maxLength`, and `pattern` before any evaluation runs. A valid
document is stored parsed in the row's `output` field and sets
`result.schema_valid`; a failure (including unparsable JSON) nulls `output`,
records `result.schema_error`, and skips evaluation. Rejection sampling treats
a schema failure as a failed attempt and tries again, and may use
`output_schema` as its only pass/fail signal.

## Resume, dry run, and progress

`--resume` counts the rows an earlier run already wrote to each task's output
file, skips that many input rows, and appends the rest; a trailing row left
incomplete by a multi-solution or rejection task is dropped and produced
again. The summary then covers only the new rows and reports `resumed_from`.

`--dry-run` validates the config and inputs, then prints a JSON estimate of
input counts, tokens, cost, and minutes without calling the API.

`--progress` prints a status line to stderr every five seconds or every 10% of
the inputs, whichever comes first:

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | Entry point |
| `rejector_core/cli.py` | Flags, override wiring, exit codes |
| `rejector_core/config.py` | YAML loading, `defaults` merging, validation |
| `rejector_core/paths.py` | Input/output path resolution per task |
| `rejector_core/dataset.py` | JSONL input loading |
| `rejector_core/templates.py` | `{field}` template rendering |
| `rejector_core/prompts.py` | Chat message assembly and row field checks |
| `rejector_core/icl.py` | ICL setups, example files, per-attempt selection |
| `rejector_core/extraction.py` | Extract methods |
| `rejector_core/api.py` | Request shaping per API type, 5xx retries, call accounting |
| `rejector_core/chat_templates.py` | Rendering a conversation into a completions prompt |
| `rejector_core/tools.py` | Tool declarations and the handlers behind them |
| `rejector_core/agentic.py` | The tool-calling loop and its aggregated metadata |
| `rejector_core/limits.py` | Sliding RPM/TPM windows, slots, token estimates |
| `rejector_core/cost.py` | Per-call charging and the run-wide budget |
| `rejector_core/schema.py` | The JSON Schema draft 7 subset |
| `rejector_core/resume.py` | Reading an existing output file back |
| `rejector_core/estimate.py` | The `--dry-run` projection |
| `rejector_core/progress.py` | The `--progress` status line |
| `rejector_core/runner.py` | Concurrency and per-row attempt logic |
| `rejector_core/solutions.py` | Multi-solution collection per row |
| `rejector_core/evaluation.py` | Match, script, and LLM-judge evaluators |
| `rejector_core/reporting.py` | Row documents and the run summary |

Rows are processed concurrently under each task's `max_concurrent` budget -
or, when the task sets none, one derived from its `rpm` - and tasks run
concurrently with each other; results are written in input order within every
task's file. Reading decisions taken where the
spec allows more than one behaviour are recorded in `AMBIGUITIES.md`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest            # tests drive the CLI against a fake API server
```
