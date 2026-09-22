# rejector

A CLI that runs prompt tasks from a YAML config over JSONL datasets against an
OpenAI compatible `/v1/chat/completions` or `/v1/completions` endpoint,
evaluates each response, and writes one JSONL result per input row. A task may
also be agentic: the model then calls the tools the task declares until it can
answer.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

A single task config takes one input file and writes one output file:

```bash
python rejector.py run --config examples/task.yaml \
                       --input examples/data.jsonl \
                       --output results.jsonl
```

A multi task config takes one input per task and writes one output file per task
into an output directory, either by naming each input:

```bash
python rejector.py run --config examples/multi.yaml \
                       --input gsm8k=examples/data/gsm8k.jsonl \
                       --input mmlu=examples/data/mmlu.jsonl \
                       --output results/
```

or by pointing at a directory holding `<task_name>.jsonl` for each task:

```bash
python rejector.py run --config examples/multi.yaml \
                       --input-dir examples/data/ \
                       --output results/
```

The two input modes cannot be combined. `--task <name>` is repeatable and limits
the run to the tasks named; inputs and outputs of the other tasks are then
neither required nor touched:

```bash
python rejector.py run --config examples/multi.yaml \
                       --input gsm8k=examples/data/gsm8k.jsonl \
                       --output results/ --task gsm8k
```

`--api-url`, `--model`, `--rpm`, `--scheme`, `--temperature`, `--max-tokens`,
`--n`, `--num-solutions`, `--icl-strategy`, `--icl-k`, `--api-type` and
`--chat-template` override the matching config values for every task that runs,
and `--eval-model` overrides the judge model of the `llm_judge` tasks among
them. The
run summary is printed to stdout as a single JSON object; configuration and input
problems are reported on stderr with exit code `1`.

## Configuration

```yaml
task:
  name: "gsm8k_solve"
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60                       # request budget, also the target throughput
  api_type: "chat"              # chat | completions
  chat_template: "chatml"       # completions only: chatml | llama3 | mistral | zephyr

  prompt:
    system: "Solve the math problem. Put your final answer after ####."
    user: "{question}"          # {field} placeholders come from the input row

  generation:
    scheme: "greedy"            # greedy | sample | rejection | agentic
    temperature: 0.0            # must be > 0 for sample and rejection
    max_tokens: 512
    n: 1                        # single solution rejection: attempts per row
    max_attempts: 3             # multiple solution rejection: attempts per row
    max_iterations: 10          # agentic: API requests one loop may make

  evaluation:                   # required for rejection, optional otherwise
    type: "exact_match"         # exact_match | contains | regex | script | llm_judge
    answer_field: "answer"      # exact_match and contains
    extract: "last_number"      # last_number | first_number | last_line | letter | full
    # pattern: "####\\s*(\\d+)" # regex only

  output_field: "solution"
```

A config may instead define several named tasks, each with its own prompt,
generation settings, evaluation and output field. `defaults` holds the values
they share; a task overrides them, with `prompt`, `generation` and `evaluation`
merged key by key. Every required field must come from one of the two, and the
task name is the key under `tasks`:

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
      scheme: "rejection"       # inherits max_tokens: 512
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
        user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"
```

`examples/multi.yaml` is a fuller version of this with four tasks.

Schemes:

| scheme | behaviour |
| --- | --- |
| `greedy` | one attempt at temperature `0.0` |
| `sample` | one attempt at the configured temperature |
| `rejection` | up to `n` attempts, keeping the first that passes evaluation; `output` is `null` if none do |
| `agentic` | one [tool calling loop](#agentic-tasks), whose final text is the response |

This is the behaviour of a task that asks for one solution and configures no ICL.
[Multiple solutions](#multiple-solutions) changes every one of them.

Evaluation types:

| type | behaviour |
| --- | --- |
| `exact_match` | extract a value with `extract` and compare it to `answer_field` |
| `contains` | look for the `answer_field` value as a substring |
| `regex` | search for `pattern`; its first capturing group, if any, is the extracted answer |
| `script` | render `command_template` and run it in a shell |
| `llm_judge` | ask a model to score the response and compare that score to `threshold` |

Without an `evaluation` block `result.passed` is `null`.

Extraction methods pull the comparison value out of a response: `last_number`
and `first_number` take a number, `letter` takes the first standalone `A` to `D`
choice (`A`, `(A)`, `A)` or `Answer: A` all yield `A`), `last_line` takes the
last non-empty line and `full` takes the whole response.

### In-context learning

A task may carry named ICL setups, each a list of demonstrations replayed as
alternating user and assistant turns between the system message and the row's
own question. Each example's `input` goes through the task's `prompt.user`
template; its `output` becomes the assistant reply verbatim:

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
            - input: {question: "If I have 3 cats and get 2 more, how many cats do I have?"}
              output: "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5"
        - name: "direct"
          examples:
            - input: {question: "What is 2+2?"}
              output: "#### 4"
            - input: {question: "If I have 3 cats and get 2 more, how many cats do I have?"}
              output: "#### 5"
      k: 2
      strategy: "round_robin"
```

A setup has a `name` and exactly one of `examples` or `file`. A `file` is a JSONL
path relative to the config file's directory, one `{"input": {...}, "output":
"..."}` per line; a malformed line ends the run with exit code `1` before any
request is sent.

`k` is how many of the setup's examples to use, the first `k` of them, and
defaults to all. `strategy` picks the setup of each attempt:

| strategy | behaviour |
| --- | --- |
| `fixed` | always the first setup (the default) |
| `random` | an independent choice per attempt |
| `round_robin` | the setups in order, cycling across the row's attempts |

`examples/multi_solution.yaml` shows both an inline and a file backed setup.

### Multiple solutions

`num_solutions`, in `defaults` or on a task, asks for several responses per input
row. Every scheme then collects up to that many:

| scheme | behaviour |
| --- | --- |
| `greedy` | one attempt per setup at temperature `0.0`, walking the setups in declared order rather than by `strategy`; the same setup is deterministic, so the number of setups caps the solutions |
| `sample` | one sampled attempt per requested solution, each with a setup from `strategy`; evaluation does not gate what is written out |
| `rejection` | attempts, each with a setup from `strategy`, until `num_solutions` of them pass evaluation or `max_attempts` is spent; only passing responses are written out |

`generation.max_attempts` defaults to three attempts per requested solution. A
run that exhausts it keeps the solutions it did collect.

A task that asks for a single solution and configures no ICL keeps the Part 1
behaviour and result shape throughout: rejection sampling makes at most
`generation.n` attempts and ignores `max_attempts`.

### Script evaluation

```yaml
evaluation:
  type: "script"
  command_template: "python3 -c \"{test_code}\""
  success_exit_code: 0          # any other exit code fails the row
```

`command_template` may reference row fields and `{__response__}`. A row field
that itself expands to text containing `{__response__}`, such as a `test_code`
holding the assertions for a generated function, has it substituted too. The
command runs in a shell with a 10 second timeout; timing out fails the row. Its
stdout and stderr are captured and discarded rather than written to the results.

### LLM judge evaluation

```yaml
evaluation:
  type: "llm_judge"
  judge_prompt:                 # same template rules, plus {__response__}
    system: "You are a quality evaluator. Respond with only a single integer from 1 to 10."
    user: "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
  threshold: 7                  # a score >= threshold passes
  extract: "first_number"       # applied to the judge's reply
  model: "gpt-4"                # optional; defaults to the task's model
```

The judge request is a separate call to the same server, made at temperature
`0.0` once the response it scores exists. Under the `rejection` scheme every
attempt is judged until one passes.

### Agentic tasks

An `agentic` task gives the model tools and lets it work: each API request
either asks for tool calls, which are executed and fed back, or answers in
text, which ends the loop. `generation.max_iterations` caps the requests one
loop may make.

```yaml
tasks:
  data_lookup:
    prompt:
      system: "You are a data analysis assistant. Use the provided tools to look up data and answer questions."
      user: "{question}"
    generation:
      scheme: "agentic"
      max_iterations: 10
      temperature: 0.0
      max_tokens: 512
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "answer"
    tools:
      - name: "lookup"
        description: "Look up a value in the database by key"
        parameters:                 # the JSON schema sent to the model
          type: "object"
          properties:
            key:
              type: "string"
              description: "The database key to look up"
          required: ["key"]
        handler:
          type: "static_map"
          mapping:
            "revenue_q1": "1250000"
            "employees": "142"
          default: "KEY_NOT_FOUND"  # defaults to "NOT_FOUND"

      - name: "calculate"
        description: "Evaluate a mathematical expression"
        parameters:
          type: "object"
          properties:
            expression:
              type: "string"
          required: ["expression"]
        handler:
          type: "echo"
```

Handler types:

| type | behaviour |
| --- | --- |
| `echo` | return the parsed call arguments as a JSON string |
| `static_map` | look the first required argument up in `mapping`, falling back to `default` |
| `script` | run `command` with the value of `arg_field` as a single argument and return its stdout |

```yaml
handler:
  type: "script"
  command: "python3 -c"
  arg_field: "code"
```

A script handler that times out or exits non-zero returns `ERROR: <stderr or
timeout message>` to the model rather than failing the row; the 10 second
timeout of [script evaluation](#script-evaluation) applies. A call to a tool
the task does not declare returns an error the same way.

Evaluation sees the final text only. A loop that reaches `max_iterations`
produces no text at all, so the row is written with `"output": null` and fails.
`agentic` combines with ICL and `num_solutions`: each solution is an
independent loop starting from that setup's examples, and the row then takes
the [list output format](#multiple-solutions).

`examples/agentic.yaml` has a `static_map`, an `echo` and a `script` tool.

### Completions mode

`api_type: "completions"` sends `{"model", "prompt", "temperature",
"max_tokens"}` to `{api_url}/v1/completions` and reads the reply from
`choices[0].text`. The conversation is rendered into the single prompt string
by `chat_template`, which repeats its role markers for every turn, ICL examples
and tool exchanges included:

| template | turn |
| --- | --- |
| `chatml` | `<\|im_start\|>{role}\n{content}<\|im_end\|>` |
| `llama3` | `<\|start_header_id\|>{role}<\|end_header_id\|>\n\n{content}<\|eot_id\|>` |
| `mistral` | `[INST] {content} [/INST]`, with the system turn folded into the first user turn |
| `zephyr` | `<\|{role}\|>\n{content}</s>` |

Both settings belong in `defaults` or on a task, and `--api-type` and
`--chat-template` override them for a whole run:

```bash
python rejector.py run --config examples/task.yaml \
                       --input examples/data.jsonl \
                       --output results.jsonl \
                       --api-type completions --chat-template llama3
```

The endpoint has no native tool calling, so an agentic task in this mode
describes its tools in the system turn and parses the calls back out of the
response text:

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

Each result is replayed in the next prompt as a `<tool_response>` block in the
template's tool role.

## Output

One JSON object per input row, in input order:

```json
{
  "input": {"question": "What is 2 + 3?", "answer": "5"},
  "output": {"solution": "2 + 3 = 5\n#### 5"},
  "result": {"passed": true, "extracted_answer": "5", "attempts": 1},
  "meta": {"model": "gpt-4", "prompt_tokens": 30, "completion_tokens": 10,
           "total_tokens": 40, "latency_ms": 150, "finish_reason": "stop"}
}
```

`meta` becomes a list with one entry per attempt when rejection sampling makes
more than one. A row whose request kept failing gets `"output": null` and
`"meta": null`.

A task with ICL or with `num_solutions` above one writes a list of outputs
instead, each tagged with the setup that produced it, and one metadata entry per
attempt rather than per kept response:

```json
{
  "input": {"question": "What is 15 + 27?", "answer": "42"},
  "output": [
    {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
    {"solution": "#### 42", "icl_setup": "direct"}
  ],
  "result": {"passed": 2, "failed": 5, "attempts": 7},
  "meta": [
    {"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
     "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
     "icl_setup": "chain_of_thought", "evaluation_passed": true}
  ]
}
```

`result.passed` counts the responses that passed evaluation, `result.failed` the
attempts that did not, and `result.attempts` every attempt the row made.
`icl_setup` is `null` for a task without ICL, and so is `evaluation_passed` for a
task without an evaluation — where `result.passed` instead counts the responses
written out.

An agentic row reports the loop behind its response: `result.iterations` is how
many API requests it took, `result.tool_calls` every call in execution order,
and `meta` the totals across the loop with one entry per request:

```json
{
  "input": {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"},
  "output": {"answer": "The total revenue for Q1 and Q2 is 2730000."},
  "result": {
    "passed": true, "extracted_answer": "2730000", "attempts": 1, "iterations": 3,
    "tool_calls": [
      {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
      {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"}
    ]
  },
  "meta": {
    "total_prompt_tokens": 850, "total_completion_tokens": 120, "total_tokens": 970,
    "latency_ms": 1200, "finish_reason": "stop",
    "iterations_detail": [
      {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230,
       "latency_ms": 300, "finish_reason": "tool_calls"},
      {"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350,
       "latency_ms": 500, "finish_reason": "stop"}
    ]
  }
}
```

`meta.finish_reason` is the last request's, or `max_iterations` for a loop that
ran out of them. In the list format `result.attempts` counts the loops the row
started rather than the requests they made, and each `meta` entry carries its
own loop's totals and `iterations_detail` alongside `icl_setup` and
`evaluation_passed`.

An `llm_judge` task adds the judge's score to `result` and the judge call's own
metadata to the attempt it scored, with `extracted_answer` holding the text
`extract` took from the judge's reply:

```json
{
  "result": {"passed": true, "extracted_answer": "8", "attempts": 1, "judge_score": 8},
  "meta": {"model": "gpt-4", "prompt_tokens": 30, "completion_tokens": 10,
           "total_tokens": 40, "latency_ms": 150, "finish_reason": "stop",
           "judge_meta": {"model": "gpt-4", "prompt_tokens": 60, "completion_tokens": 1,
                          "total_tokens": 61, "latency_ms": 90, "finish_reason": "stop"}}
}
```

## Summary

```json
{
  "total": 200, "passed": 170, "failed": 30,
  "total_prompt_tokens": 12000, "total_completion_tokens": 4000,
  "total_api_calls": 350, "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
  "tasks": {
    "gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
              "avg_solutions_per_input": 4.5, "total_api_calls": 142},
    "review": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 100,
               "avg_solutions_per_input": 1.0, "total_api_calls": 208}
  }
}
```

The `tasks` object lists the tasks that actually ran and is only present for a
multi task config. A task counts as passing a row once it wrote any output for
it; `total_solutions` is how many responses it wrote in all. Judge calls count toward the totals and toward the task that
made them. Every request an agentic loop makes counts, and its tokens are
totalled from each iteration.

## Throughput

Requests run concurrently: up to `rpm` rows of a task are in flight at once and a
token bucket paces that task's request starts at `rpm` per minute with a one
minute burst, so a slow server is kept busy without exceeding the configured
budget. Selected tasks run concurrently with each other, so their requests
interleave. An agentic loop holds its row for as many requests as it takes,
while the other rows keep making progress around it. Rows are claimed in input order and results are stored by row index,
so a late response can never be attributed to another row, and each output file
follows its input order. HTTP `5xx` responses are retried up to three requests in
total; the retries count toward `total_api_calls` but not toward
`result.attempts`.

## Layout

| file | contents |
| --- | --- |
| `rejector.py` | CLI parsing, wiring, exit codes |
| `config.py` | YAML loading, defaults merging, CLI override merging, validation |
| `jobs.py` | resolving inputs and outputs into the work a run performs |
| `icl.py` | in-context learning setups, their files and setup selection |
| `tools.py` | the tools an agentic task declares and their handlers |
| `agentic.py` | the tool calling loop and the metadata it aggregates |
| `templates.py` | chat templates and the text tool protocol of completions mode |
| `prompts.py` | prompt, ICL example and command template rendering |
| `evaluation.py` | answer extraction and the evaluation types |
| `shell.py` | running script evaluation commands |
| `client.py` | the chat and completions clients, retries, rate limiting |
| `runner.py` | concurrency and row dispatch |
| `schemes.py` | the generation schemes and what each keeps |
| `records.py` | output record shapes and the run summary |
| `jsonl.py` | JSONL reading and writing |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

`tests/mock_server.py` stands in for both endpoints: it queues requests and
serves a limited number in parallel. It also runs standalone for manual tries,
answering with the sum of the numbers in the prompt and scoring judge prompts
with `--score`. A request offering tools is answered with one call carrying the
backquoted part of the question, which is what the rows of
`examples/data/data_lookup.jsonl` and `examples/data/code_exec.jsonl` put
there:

```bash
python tests/mock_server.py --port 8000 --delay 0.5 --capacity 8 --wrong-first 2
```
