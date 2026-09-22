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

Optional overrides: `--api-url`, `--model`, `--rpm`, `--max-tokens`,
`--scheme`, `--temperature`, `--n`, `--eval-model`, `--num-solutions`,
`--icl-strategy`, `--icl-k`, `--api-type`, `--chat-template`, and `--task`
(repeatable) to run a subset of the configured tasks. Exit code `0` on success, `1` for a
configuration or input error (message on stderr). The run summary is printed
to stdout as a single JSON object.

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
| `rejector_core/runner.py` | Concurrency and per-row attempt logic |
| `rejector_core/solutions.py` | Multi-solution collection per row |
| `rejector_core/evaluation.py` | Match, script, and LLM-judge evaluators |
| `rejector_core/reporting.py` | Row documents and the run summary |

Rows are processed concurrently with an in-flight budget derived from each
task's `rpm`, and tasks run concurrently with each other; results are written
in input order within every task's file. Reading decisions taken where the
spec allows more than one behaviour are recorded in `AMBIGUITIES.md`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest            # tests drive the CLI against a fake API server
```
