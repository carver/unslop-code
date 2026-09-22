# rejector

A CLI that runs YAML-described generation tasks over JSONL input files against
an OpenAI-compatible API — chat completions or text completions, with optional
tool-calling loops — evaluates each response, and writes one JSONL result per
input row.

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

Any of `--api-url`, `--model`, `--rpm`, `--tpm`, `--max-concurrent`,
`--budget`, `--max-tokens`, `--scheme`, `--temperature`, `--n`,
`--num-solutions`, `--icl-strategy`, `--icl-k`, `--api-type`, and
`--chat-template` override the matching config value for every task that runs,
and `--eval-model` overrides the judge model of every `llm_judge` task. The run
prints a JSON summary to stdout and exits `0`; configuration and input problems
print a message to stderr and exit `1`.

Three flags change what a run does rather than what it is configured with:

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl \
  --output results.jsonl --resume --progress

.venv/bin/python rejector.py run --config task.yaml --input data.jsonl \
  --output results.jsonl --dry-run
```

- `--resume` continues an interrupted run; see [Resume](#resume).
- `--dry-run` estimates the run instead of making it; see
  [Dry runs](#dry-runs).
- `--progress` reports progress to stderr; see
  [Progress reporting](#progress-reporting).

## Configuration

`examples/task.yaml` is the single-task format: one top-level `task` mapping,
whose `name` names the task. `examples/multi.yaml` is the multi-task format:
each entry of `tasks` is layered on top of `defaults`, with nested sections
(`prompt`, `generation`, `evaluation`, `rate_limits`, `cost`) merged key by key,
so shared settings live in `defaults` and each task overrides only what
differs. Every required
field must come from one of the two.

- `prompt.system` / `prompt.user` are templates with `{field}` placeholders
  filled from each input row. `prompt.system` is optional.
- `generation.scheme`:
  - `greedy` forces `temperature` to `0.0`, one response per row.
  - `sample` requires `temperature > 0`, one response per row.
  - `rejection` requires `temperature > 0` and an `evaluation`; it makes up to
    `n` attempts and keeps the first response that passes.
  - `agentic` lets the model call the task's `tools` before answering; see
    [Agentic tasks](#agentic-tasks).
- `num_solutions` (default `1`) asks for several solutions per row; see
  [Multiple solutions](#multiple-solutions).
- `evaluation.extract` selects the value reported as
  `result.extracted_answer`: `last_number`, `first_number`, `last_line`,
  `letter` (the first standalone `A`–`D`, so `B`, `(B)`, `B)` and `Answer: B`
  all yield `B`), or `full`. The default is `full`, except for `llm_judge`
  where a score has to be numeric and the default is `first_number`.
- `output_field` names the key the response is written under.
- `api_type` (`chat` by default) and `chat_template` choose the endpoint the
  task talks to; see [Completions mode](#completions-mode).
- `rate_limits` and `cost` pace a task's requests and price them; see
  [Rate limits](#rate-limits) and [Cost and budget](#cost-and-budget).
- `output_schema` requires the response to be JSON of a given shape; see
  [Structured output](#structured-output).

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

### Agentic tasks

`scheme: agentic` turns a row into a loop: the task's `tools` go out with every
request, whatever the model asks for is executed locally, and the results are
appended to the conversation until the model replies with plain text or
`generation.max_iterations` (default `10`) requests have been spent.

```yaml
generation:
  scheme: "agentic"
  max_iterations: 10
  temperature: 0.0
tools:
  - name: "lookup"
    description: "Look up a value in the database by key"
    parameters:
      type: "object"
      properties:
        key: {type: "string", description: "The database key to look up"}
      required: ["key"]
    handler:
      type: "static_map"
      mapping: {"employees": "142"}
      default: "KEY_NOT_FOUND"
```

`parameters` is the JSON schema the model sees; `handler` decides what a call
returns, and never leaves the machine running the task:

| Handler | Fields | Returns |
| --- | --- | --- |
| `echo` | — | the parsed call arguments as a JSON string |
| `static_map` | `mapping`, `default` | `mapping[<first required parameter>]`, or `default` (`"NOT_FOUND"` when unset) |
| `script` | `command`, `arg_field` | the stdout of `command` run with `args[arg_field]` as its single argument |

A `script` handler that exits non-zero or outruns `SCRIPT_TIMEOUT_SECONDS`
(10s) returns `"ERROR: <stderr or timeout message>"` instead, as does a call to
a tool the task does not define. Every call of one response is executed, in the
order the model asked for them, before the next request goes out.

Each iteration is a separate API request counted in `total_api_calls`, and rows
keep running concurrently while any one of them loops, so a slow row never
blocks the rest of the batch. `agentic` composes with `icl` and
`num_solutions`, where each solution is its own independent loop; evaluation
always runs against the final text, so a loop that hits `max_iterations`
produces no output and fails.

### Completions mode

`api_type: "completions"` sends `{model, prompt, temperature, max_tokens}` to
`{api_url}/v1/completions` and reads the reply from `choices[0].text`, instead
of posting a messages array to `/v1/chat/completions`. The conversation the
chat endpoint would have received is flattened with `chat_template`, one of
`chatml` (the default), `llama3`, `mistral`, or `zephyr`, repeating the role
markers for every turn.

```yaml
defaults:
  api_type: "completions"
  chat_template: "llama3"

tasks:
  gsm8k:
    api_type: "completions"
    chat_template: "chatml"
```

`--api-type` and `--chat-template` override both. An agentic task works the
same way in completions mode, with the parts a chat request keeps in dedicated
fields moved into the prompt: the tool definitions are appended to the system
turn, the model asks for a call by writing

```text
<tool_call>
{"name": "lookup", "arguments": {"key": "revenue_q1"}}
</tool_call>
```

and each result is handed back as a `tool` turn holding a `<tool_response>`
block, rendered with the template's own role markers.

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

### Structured output

A task with an `output_schema` must answer with JSON that satisfies it
(`examples/structured.yaml`):

```yaml
output_schema:
  type: "object"
  required: ["code", "explanation"]
  properties:
    code:
      type: "string"
    explanation:
      type: "string"
```

The supported keywords are the JSON Schema draft 7 subset a generation task
needs: `type`, `required`, `properties`, `items`, `enum`, `minimum`, `maximum`,
`minLength`, `maxLength`, and `pattern`.

The schema is checked before anything else, and a response that fails it is
never evaluated. A response that satisfies it is reported as the parsed JSON
document rather than as the raw string, under the task's `output_field`.
Unparseable JSON counts as a schema failure.

- `greedy`, `sample`, and `agentic` rows fail: `output` is `null`,
  `result.passed` is `false`, `result.schema_valid` is `false`, and
  `result.schema_error` says what was wrong.
- `rejection` treats a schema failure as a failed attempt and tries again,
  which makes `output_schema` enough on its own — such a task needs no
  `evaluation` block.
- A task with a schema and no evaluation passes on any response the schema
  accepts.

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

An agentic row reports its loop instead of a single call: `result` adds the
`iterations` it spent and every `tool_calls` entry in execution order, and
`meta` holds the totals across those iterations plus one `iterations_detail`
entry each.

```json
{
  "input": {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"},
  "output": {"answer": "The total revenue for Q1 and Q2 is $2,730,000."},
  "result": {"passed": true, "extracted_answer": "2730000", "attempts": 1, "iterations": 3,
             "tool_calls": [{"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
                             "result": "1250000"}]},
  "meta": {"total_prompt_tokens": 850, "total_completion_tokens": 120, "total_tokens": 970,
           "latency_ms": 1200, "finish_reason": "stop",
           "iterations_detail": [{"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230,
                                  "latency_ms": 300, "finish_reason": "tool_calls"}]}
}
```

A loop that spends its whole budget writes `output: null`, `result.passed`
`false`, and `finish_reason` `"max_iterations"`. With ICL or
`num_solutions > 1`, an agentic row keeps the list format above: one output
entry and one `meta` entry per loop, each `meta` entry carrying that loop's
aggregated totals and `iterations_detail` alongside `icl_setup` and
`evaluation_passed`, and `result.attempts` counting loops rather than the API
requests they spent.

A task with an `output_schema` adds `schema_valid` to `result`, plus a
`schema_error` when the response was rejected, and reports the parsed document
as its output:

```json
{
  "output": {"code": {"code": "def add(a, b): return a + b",
                      "explanation": "Simple addition function"}},
  "result": {"passed": true, "extracted_answer": null, "attempts": 1, "schema_valid": true}
}
```

The stdout summary adds a `tasks` object, keyed by the tasks that actually ran,
to the Part 1 totals; single-task configs keep the Part 1 summary unchanged.
`cost` is there whenever a task priced its calls, and `resumed_from` whenever
the run was resumed.

```json
{
  "total": 200, "passed": 170, "failed": 30,
  "total_prompt_tokens": 4100, "total_completion_tokens": 9000,
  "total_api_calls": 850, "elapsed_seconds": 45.2, "throughput_rpm": 464.6,
  "resumed_from": 50,
  "cost": {"total": 12.45, "prompt": 4.5, "completion": 7.95,
           "budget": 50.0, "budget_remaining": 37.55, "budget_exceeded": false},
  "tasks": {"gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_solutions": 450,
                      "avg_solutions_per_input": 4.5, "total_api_calls": 850}}
}
```

## Rate limits

Each task is paced against its own `rate_limits` block, which `defaults` shares
with every task and each task overrides key by key:

```yaml
defaults:
  rate_limits:
    rpm: 100
    tpm: 50000
    max_concurrent: 10

tasks:
  code_gen:
    rate_limits:
      tpm: 30000
```

- `rpm` caps the requests started in any 60 seconds. A task that sets no `rpm`
  — in `rate_limits` or as the older top-level `rpm` key — is not limited by
  request count.
- `tpm` caps the tokens spent in any 60 seconds. Before a request is sent it
  reserves the tokens it is expected to cost: the prompt's word count converted
  at `1 token ~= 0.75 words`, plus `max_tokens`. When the response arrives the
  reservation is replaced by the `prompt_tokens + completion_tokens` the API
  reported, so an over-estimate is handed straight back to the next request.
  This is what makes `tpm` rather than `rpm` the binding limit for large
  prompts: with `rpm: 600`, `tpm: 10000`, and requests of about 612 tokens, the
  scheduler paces at the token budget's 16 requests a minute, not the request
  budget's 600.
- Both budgets are sliding 60-second windows, so a task may open with a full
  budget's worth of requests and then paces itself as the window fills. A
  request waits until it fits in both.
- `max_concurrent` caps the requests in flight. It sizes the task's worker pool,
  and since one worker owns one row at a time and a row's requests are
  sequential, an agentic row holds its slot for the whole of its loop while the
  other workers keep their own rows' requests in flight.

Judge calls, retries, and every iteration of an agentic loop go through the same
limiter as the generation requests they belong to. A task without
`max_concurrent` keeps a minute of request budget in flight, capped at
`MAX_WORKERS`. Tasks run concurrently over one shared HTTP client, so their
requests interleave. Workers pull row indices from their task's queue in input
order and each one owns its row's response, so every output file stays aligned
with its input regardless of completion order.

A `5xx` response or a transport failure is retried up to 3 requests in total per
attempt. Retries count toward `total_api_calls` but not toward
`result.attempts`; a row that never gets a response has `output: null` and is
counted as failed.

## Cost and budget

A `cost` block prices a task's calls, and is merged from `defaults` key by key
like `rate_limits`:

```yaml
defaults:
  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
    budget: 50.0
```

Every call — including judge calls and each agentic iteration — is charged as
`prompt_tokens / 1000 * prompt_cost_per_1k + completion_tokens / 1000 *
completion_cost_per_1k`, and the totals are reported in the summary's `cost`
object to four decimal places. Without any `cost` block there is no `cost`
field.

`budget` caps the spend of the run as a whole; when tasks configure different
budgets the smallest applies. Once the running total reaches it, no further row
is started: the rows already in flight finish, their results are written, the
summary reports `budget_exceeded: true`, and the run exits `0`. Exhausting the
budget is not an error, and the partial output is a valid resumption point.
Because a row that has started runs to the end, the final total can overshoot
the budget by the rows that were in flight.

## Resume

`--resume` continues into an output file an earlier run left behind. Results are
written in input order, so the number of finished leading rows is also the index
of the first row still to do; those rows are kept as they are and new results
are appended after them. Multi-task runs resume each task from its own output
file, and the summary covers only the newly processed rows, reporting the rows
skipped as `resumed_from`.

A leading row counts as finished unless it is a `rejection` or multi-solution
row that collected fewer than `num_solutions` passing solutions, or a line an
interrupted write left truncated. Those rows, and everything after them, are
produced again from scratch.

## Dry runs

`--dry-run` validates the config and the input files, prints an estimate of the
run, and exits `0` without calling the API. Prompt tokens are estimated as the
average prompt's word count times `1.33`, completions as `max_tokens` per row,
and the time as `inputs * attempts / rpm` minutes — where a `rejection` task is
planned for its worst case and an agentic one for its full iteration budget.

```json
{
  "tasks": {"gsm8k": {"inputs": 1000, "est_prompt_tokens": 45000,
                      "est_completion_tokens": 512000, "est_total_tokens": 557000,
                      "est_cost": 15.81}},
  "total_inputs": 1000, "est_total_tokens": 557000,
  "est_total_cost": 15.81, "est_time_minutes": 10.0
}
```

## Progress reporting

`--progress` writes one line to stderr every five seconds or every tenth of the
run's rows, whichever comes first:

```text
[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
```

The pass/fail field appears only when something can fail the rows — an
evaluation or an `output_schema` — and the spend field only when a task priced
its calls.

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
| `chat_templates.py` | built-in templates flattening a conversation into a prompt |
| `tools.py` | tool definitions, prompt rendering, and handlers |
| `schemes.py` | greedy / sample / rejection generation logic |
| `agentic.py` | the agentic tool-calling loop |
| `pipeline.py` | worker pools and per-run orchestration |
| `ratelimit.py` | request and token pacing |
| `accounting.py` | call counters, token costs, the spend budget |
| `progress.py` | the stderr progress line |
| `resume.py` | how much of an existing output file to keep |
| `estimate.py` | `--dry-run` estimates |
| `api.py` | HTTP client, retries, call statistics |
| `extraction.py` | answer extraction methods |
| `evaluation.py` | schema validation and pass/fail checks |
| `output_schema.py` | the JSON Schema subset responses are validated against |
| `judge.py` | `llm_judge` scoring calls |
| `script_eval.py` | `script` command execution |
| `results.py` | result records, JSONL output, run summary |
| `errors.py` | user-facing error types |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

`tests/mock_server.py` is a small stand-in API serving both endpoints. It
serves a fixed number of requests concurrently after a configurable delay, can
fail a prompt's first `N` attempts (`--pass-after`), pass only every `N`th
attempt (`--pass-every`) or reply `503` to everything (`--always-fail`), and
answers any prompt whose system message mentions "judge" with `--judge-score`.
With `--answer-only` it replies with the answer alone, which is how a test hands
the client an exact response such as a JSON document, and a `GET /` reports the
most requests it ever had in flight at once.
Its replies echo the last user message (the whole rendered prompt in
completions mode), the temperature, and the number of messages received, so
tests can see which ICL turns and tool results were sent. A `CALL <tool>
<json args>` marker in a question makes it request that tool once per
conversation, or on every request with `--always-call-tools`.
