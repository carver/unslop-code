# rejector

A CLI that runs a YAML-configured generation task over a JSONL input file
against an OpenAI-compatible chat completions API, and writes one JSONL
result per input row.

```bash
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Optional overrides: `--api-url`, `--model`, `--rpm`, `--max-tokens`,
`--scheme`, `--temperature`, `--n`. Exit code `0` on success, `1` for a
configuration or input error (message on stderr). The run summary is printed
to stdout as a single JSON object.

## Layout

| Module | Responsibility |
| --- | --- |
| `rejector.py` | Entry point |
| `rejector_core/cli.py` | Flags, override wiring, exit codes |
| `rejector_core/config.py` | YAML loading and task validation |
| `rejector_core/dataset.py` | JSONL input loading |
| `rejector_core/prompts.py` | `{field}` templating and row field checks |
| `rejector_core/api.py` | Request shaping, 5xx retries, call accounting |
| `rejector_core/runner.py` | Concurrency and per-row attempt logic |
| `rejector_core/evaluation.py` | Extract methods and evaluation types |
| `rejector_core/reporting.py` | Row documents and the run summary |

Rows are processed concurrently with an in-flight budget derived from `rpm`;
results are written in input order. Reading decisions taken where the spec
allows more than one behaviour are recorded in `AMBIGUITIES.md`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest            # tests drive the CLI against a fake API server
```
