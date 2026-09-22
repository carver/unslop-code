# rejector

CLI tool that reads a YAML config and JSONL input, sends prompts to an
OpenAI-compatible chat completions API, and writes one JSONL result per row.
A config may describe a single task (Part 1) or several named tasks (Part 2).
Tasks may also carry in-context learning (ICL) setups and collect several
solutions per input (Part 3).

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Usage

Single task:

```bash
./.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Multiple tasks (`defaults` + `tasks` in the config); `--output` is a directory
and each task writes `<output_dir>/<task_name>.jsonl`:

```bash
# explicit mapping
./.venv/bin/python rejector.py run --config multi.yaml \
    --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/

# directory mode: looks for <task_name>.jsonl
./.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/

# run a subset; only the selected tasks need input files
./.venv/bin/python rejector.py run --config multi.yaml --input gsm8k=math.jsonl \
    --output results/ --task gsm8k
```

`--input` and `--input-dir` are alternative modes and cannot be combined.

Optional overrides: `--api-url`, `--model`, `--eval-model`, `--rpm`,
`--max-tokens`, `--scheme {greedy,sample,rejection}`, `--temperature`, `--n`,
`--num-solutions`, `--icl-strategy {fixed,random,round_robin}`, `--icl-k`.

Exit codes: `0` success, `1` configuration or input error (message on stderr).
The JSON summary is the only thing written to stdout.

## Config

`defaults` supplies shared values and each task overrides them; nested sections
(`prompt`, `generation`, `evaluation`, `judge_prompt`) are merged key by key, so
required fields may come from either place. A top-level `task` key always means
the Part 1 single-task format, and the task name is `task.name`.

Evaluation types: `exact_match`, `contains`, `regex`, `llm_judge`, `script`.
Extract methods: `last_number`, `first_number`, `last_line`, `letter`, `full`.

`llm_judge` sends a second request through the same server (model from
`evaluation.model`, `--eval-model`, or the task's model), extracts a score from
the reply and passes when `score >= threshold`. The row's `result` gains
`judge_score`, and the generation's `meta` gains a `judge_meta` object. Judge
calls count toward `total_api_calls`, the per-task totals, and throughput.

`script` renders `command_template` from the row plus `__response__` (a row
field that itself expands to `{__response__}` is substituted too) and runs it in
a shell with a 10 second timeout. Exit code `success_exit_code` passes;
anything else, including a timeout, fails. The command's stdout and stderr are
captured but never written to the JSONL output.

## In-context learning

A task may declare named ICL setups; each has a `name` and exactly one of
`examples` (inline) or `file` (a JSONL path relative to the config file).

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

Each file line must be `{"input": <object>, "output": <string>}`; a malformed
line or a missing key ends the run with exit code 1 before any request is sent.

Examples sit between the system message and the final user message as
alternating user/assistant turns: the example `input` is rendered with the
task's `prompt.user` template, the `output` is used verbatim. `k` defaults to
every example in the setup and otherwise takes the first `k`.

`strategy` picks a setup per attempt: `fixed` always uses the first, `random`
chooses independently each time, `round_robin` cycles in declared order.
`greedy` with `num_solutions > 1` ignores the strategy and walks the setups in
declared order, at most once each — re-running a setup at temperature 0 would
only repeat it, so the setup count caps the number of solutions.

## Multiple solutions

`num_solutions` (in `defaults` or per task, overridden by `--num-solutions`)
asks for several solutions per input:

- `greedy`: one temperature-0 generation per setup, stopping once enough
  solutions are collected or the setups run out
- `sample`: one sampled generation per requested solution; evaluation records
  a verdict but does not gate inclusion
- `rejection`: keep generating until `num_solutions` solutions pass or
  `generation.max_attempts` is exhausted (`max_attempts` defaults to
  `3 * num_solutions`)

When ICL is configured or `num_solutions > 1`, `output` becomes a list of
`{<output_field>, icl_setup}` objects, `meta` a list with one entry per attempt
(each gaining `icl_setup` and `evaluation_passed`), and `result` becomes
`{passed, failed, attempts}` counts. `icl_setup` is `null` without ICL, and
`evaluation_passed` is `null` when no evaluation is configured — in which case
`passed` counts emitted outputs and `failed` the attempts that produced none.
With `num_solutions == 1` and no ICL the Part 1 row format is kept, and
rejection still makes `generation.n` attempts, ignoring `max_attempts`.

Per-task summaries gain `total_solutions` and `avg_solutions_per_input`.

## Notes

- Requests run concurrently through a worker pool sized from `rpm`, so a server
  that queues internally stays saturated; rows are dispatched in input order and
  each response is matched to its own row. Tasks run concurrently with each
  other and their requests may interleave, but each output file keeps input
  order.
- `greedy` forces `temperature: 0.0`; `sample` and `rejection` require
  `temperature > 0`; `rejection` makes up to `n` attempts and keeps the first
  passing response.
- HTTP 5xx (and connection errors) are retried up to 3 total requests per
  attempt. Retries count toward `total_api_calls` but not `result.attempts`.
- The stdout summary adds a `tasks` object for multi-task configs, keyed by the
  tasks that actually ran. Single-task runs keep the Part 1 summary exactly.

## Tests

```bash
./.venv/bin/python tests/run_tests.py
```

Spins up a mock API server that queues requests and takes real processing time,
then checks output shape, all three schemes, every evaluation type and extract
method, retry behaviour, validation errors, CLI overrides, ordering, throughput,
multi-task configs (defaults merging, task selection, both input modes, per-task
output files and summaries, cross-task interleaving), `llm_judge` scoring and
metadata, `script` evaluation including exit codes and timeouts, ICL message
layout, `k`, file-backed setups and their error cases, every setup strategy,
the greedy setup cap, multi-solution sampling and rejection (including partial
results and the `max_attempts` default), the list output format, and the
preserved single-solution format.
