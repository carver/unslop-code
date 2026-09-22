# rejector

A CLI that runs YAML-configured generation tasks over JSONL input against an
OpenAI-compatible chat completions API, and writes one JSONL result per input
row.

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
`--scheme`, `--temperature`, `--n`, `--eval-model`, and `--task` (repeatable)
to run a subset of the configured tasks. Exit code `0` on success, `1` for a
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

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | Entry point |
| `rejector_core/cli.py` | Flags, override wiring, exit codes |
| `rejector_core/config.py` | YAML loading, `defaults` merging, validation |
| `rejector_core/paths.py` | Input/output path resolution per task |
| `rejector_core/dataset.py` | JSONL input loading |
| `rejector_core/prompts.py` | `{field}` templating and row field checks |
| `rejector_core/extraction.py` | Extract methods |
| `rejector_core/api.py` | Request shaping, 5xx retries, call accounting |
| `rejector_core/runner.py` | Concurrency and per-row attempt logic |
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
