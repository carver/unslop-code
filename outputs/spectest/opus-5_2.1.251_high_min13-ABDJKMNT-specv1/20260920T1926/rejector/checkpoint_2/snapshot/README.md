# rejector

CLI that runs YAML-configured generation tasks against an OpenAI-compatible
chat completions API over JSONL input, one JSONL result per row.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# one task (Part 1 `task:` config)
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

# several tasks (`defaults:` + `tasks:` config), inputs named explicitly
.venv/bin/python rejector.py run --config multi.yaml \
    --input gsm8k=math.jsonl --input mmlu=qa.jsonl --output results/

# ... or picked up from a directory as <task_name>.jsonl, for selected tasks only
.venv/bin/python rejector.py run --config multi.yaml --input-dir data/ --output results/ --task gsm8k
```

A multi-task config layers each task over `defaults`, writes
`<output_dir>/<task_name>.jsonl` per task that ran, and adds a `tasks` object
to the stdout summary. `--input <task>=<path>` and `--input-dir` are
alternative modes and cannot be combined.

Overrides for `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature` and `--n` replace the corresponding config values for every
task; `--eval-model` replaces the judge model of `llm_judge` tasks. Exit code
`1` means a configuration or input error, with the reason on stderr; the run
summary is printed to stdout as one JSON object.

Evaluation types are `exact_match`, `contains`, `regex`, `script` (render a
shell command per row and compare its exit code, 10s timeout) and `llm_judge`
(score the response with a second model call and compare to a `threshold`).
Extract methods are `last_number`, `first_number`, `letter`, `last_line` and
`full`.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | Entry point |
| `taskrunner/cli.py` | Argument parsing, wiring, exit codes |
| `taskrunner/config.py` | YAML parsing, `defaults`/`tasks` merging, validation |
| `taskrunner/inputs.py` | Task selection and input/output path resolution |
| `taskrunner/prompts.py` | `{field}` template rendering and row requirements |
| `taskrunner/evaluation.py` | Extract methods and evaluation dispatch |
| `taskrunner/script_eval.py` | Shell command rendering and exit-code checks |
| `taskrunner/judge.py` | The judge request and its score |
| `taskrunner/api.py` | Async chat completions client with 5xx retries |
| `taskrunner/generation.py` | Greedy / sample / rejection schemes per row |
| `taskrunner/runner.py` | Ordered, concurrent execution across tasks and rows |
| `taskrunner/records.py` | Output row and summary shaping |
| `taskrunner/jsonl.py` | JSONL reading and writing |

Rows are admitted to a per-task worker pool in input order with up to `rpm`
requests in flight, so the configured request budget stays saturated while each
row keeps its own response. Rejection attempts are sequential within a row;
tasks share one HTTP session and run concurrently, so their requests interleave.

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation takes. Tests live in `tests/`, each section commented
with the spec phrase it covers; `tests/fake_api.py` is a threaded stand-in for
the API that models queueing capacity.
