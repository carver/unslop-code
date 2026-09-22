# rejector

CLI that runs YAML-configured generation tasks over JSONL input against an
OpenAI-compatible chat completions API, and writes one JSONL result row per
input row.

```bash
# single-task config (Part 1 shape: a top-level `task:` mapping)
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

# multi-task config (`defaults:` plus a `tasks:` mapping)
python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/
python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

`--input` and `--input-dir` are alternative input modes; directory mode looks
for `<task_name>.jsonl`. A multi-task run writes `<output_dir>/<task>.jsonl`
for each task that ran. Optional overrides: `--api-url`, `--model`, `--rpm`,
`--max-tokens`, `--scheme`, `--temperature`, `--n`, `--eval-model`,
`--num-solutions`, `--icl-strategy`, `--icl-k`. Exit code `0` on success, `1`
on a configuration or input error.

## In-context learning and multiple solutions

A task may declare named `icl.setups`, each holding `examples` inline or a
JSONL `file` (resolved against the config file's directory). The first `icl.k`
examples of the selected setup are inserted between the system message and the
row's own user message as alternating user/assistant turns, and `icl.strategy`
(`fixed`, `random` or `round_robin`) picks the setup for each attempt.

`num_solutions` asks for several solutions per row: `sample` makes one request
per solution, `rejection` keeps going until enough attempts pass or
`generation.max_attempts` (default `3 * num_solutions`) runs out, and `greedy`
walks each setup at most once. Such rows report a list of solutions, each
tagged with its `icl_setup`, and one metadata entry per attempt. A task with
one solution and no ICL keeps the Part 1 row shape and the Part 1 rejection
behaviour.

Evaluations are `exact_match`, `contains`, `regex`, `script` (a shell command
whose exit code decides the row, with a 10s timeout) and `llm_judge` (a second
API call whose extracted score is compared to `threshold`).

## Layout

| Path | Role |
| --- | --- |
| `rejector.py` | entry point |
| `rejector_lib/cli.py` | argument parsing, run orchestration |
| `rejector_lib/config.py` | YAML loading, `defaults` merging, validation |
| `rejector_lib/errors.py` | the two exit-code-1 failure types |
| `rejector_lib/icl.py` | ICL setups: loading, rendering, strategy rotation |
| `rejector_lib/plan.py` | task selection and input/output file resolution |
| `rejector_lib/inputs.py` | JSONL reading, row validation, template rendering |
| `rejector_lib/api.py` | async chat completions client, retries, usage tallies |
| `rejector_lib/runner.py` | greedy/sample/rejection schemes, per-task concurrency |
| `rejector_lib/solutions.py` | collecting several solutions for one row |
| `rejector_lib/scoring.py` | applying a task's evaluation to one response |
| `rejector_lib/evaluation.py` | extraction and the deterministic evaluations |
| `rejector_lib/judge.py` | the `llm_judge` scoring call |
| `rejector_lib/script_eval.py` | the `script` evaluation's shell command |
| `rejector_lib/report.py` | result rows and the stdout summary |
| `tests/mock_server.py` | mock API with configurable capacity and failures |

Requests run concurrently: each task keeps up to its `rpm` (capped at 256) in
flight, tasks run alongside each other, and a task's judge calls share its
budget and its per-task totals. `AMBIGUITIES.md` records where the spec
allowed more than one reading and which one this implementation takes.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
