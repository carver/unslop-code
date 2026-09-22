# rejector

CLI that runs a YAML-configured generation task against an OpenAI-compatible
chat completions API over a JSONL input file, one JSONL result per row.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Overrides for `--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`,
`--temperature` and `--n` replace the corresponding config values. Exit code
`1` means a configuration or input error, with the reason on stderr; the run
summary is printed to stdout as one JSON object.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | Entry point |
| `taskrunner/cli.py` | Argument parsing, wiring, exit codes |
| `taskrunner/config.py` | YAML config parsing, defaults, validation rules |
| `taskrunner/prompts.py` | `{field}` template rendering and row requirements |
| `taskrunner/evaluation.py` | Extract methods and evaluation types |
| `taskrunner/api.py` | Async chat completions client with 5xx retries |
| `taskrunner/generation.py` | Greedy / sample / rejection schemes per row |
| `taskrunner/runner.py` | Ordered, concurrent execution across rows |
| `taskrunner/records.py` | Output row and summary shaping |
| `taskrunner/jsonl.py` | JSONL reading and writing |

Rows are admitted to a worker pool in input order with up to `rpm` requests in
flight, so the configured request budget stays saturated while each row keeps
its own response. Rejection attempts are sequential within a row.

`AMBIGUITIES.md` records where the spec allowed more than one reading and which
one this implementation takes. Tests live in `tests/`, each section commented
with the spec phrase it covers; `tests/fake_api.py` is a threaded stand-in for
the API that models queueing capacity.
