# rejector

CLI tool that runs YAML-defined generation tasks over JSONL input files against
an OpenAI-compatible chat completions API, and writes one JSONL result per
input row. A config holds either a single Part 1 `task` or a `defaults` section
plus a `tasks` mapping of named tasks.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

Single-task config:

```bash
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Multi-task config, one input per task or a directory of `<task_name>.jsonl`:

```bash
python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/
python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

Shared options:

```
[--task NAME]... [--eval-model NAME]
[--api-url URL] [--model NAME] [--rpm N] [--max-tokens N]
[--scheme greedy|sample|rejection] [--temperature F] [--n N]
```

The two input modes are alternatives for a multi-task config. `--output` is a
file for single-task configs and a directory for multi-task ones, where each
executed task writes `<task_name>.jsonl`. Exit code `0` on success, `1` on a
configuration or input error (message on stderr). A JSON summary is printed to
stdout when the run finishes; multi-task runs add a per-task `tasks` object.

Evaluations are `exact_match`, `contains`, `regex`, `script` (exit code of a
rendered shell command) and `llm_judge` (a second model call whose score is
compared against a threshold). Extract methods are `last_number`,
`first_number`, `last_line`, `letter` and `full`.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | argument parsing and the top-level run sequence |
| `rejlib/config.py` | YAML loading, `defaults`/task merging, CLI overrides, validation |
| `rejlib/inputs.py` | mapping the input flags to per-task rows, output target checks |
| `rejlib/prompts.py` | `{field}` template rendering, per-row field requirements |
| `rejlib/extraction.py` | the extract methods |
| `rejlib/evaluation.py` | verdicts: the in-memory types plus script and judge dispatch |
| `rejlib/script_eval.py` | running a `script` evaluation's shell command |
| `rejlib/judge.py` | the `llm_judge` scoring call |
| `rejlib/api.py` | chat completions client, 5xx retries, per-task counters |
| `rejlib/ratelimit.py` | token bucket pacing requests against the `rpm` budget |
| `rejlib/schemes.py` | greedy / sample / rejection generation per row |
| `rejlib/runner.py` | concurrent fan-out per task, output row assembly, summary |
| `rejlib/jsonl.py` | JSONL input parsing and output writing |

Concurrency: selected tasks run concurrently, each with its own `rpm` budget.
Within a task, rows are dispatched in input order, up to one minute of budget in
flight, and each task's output file keeps input order. Judge calls share their
task's budget and counters. See `AMBIGUITIES.md` for the interpretation
decisions behind the behaviour.

## Tests

```bash
.venv/bin/python -m pytest
```

`tests/fake_api.py` provides a threaded OpenAI-compatible stand-in with
scriptable responses, an optional per-request delay, and a request log.
