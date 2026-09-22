# rejector

CLI for running a YAML-configured generation task against an
OpenAI-compatible chat completions API.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl \
    [--api-url URL] [--model NAME] [--rpm INT] [--max-tokens INT] \
    [--scheme greedy|sample|rejection] [--temperature FLOAT] [--n INT]
```

Exit codes: `0` success, `1` configuration or input error. One JSON result
object is written per input row (in input order) and a single JSON summary is
printed to stdout.

Requests are issued concurrently: the in-flight budget is sized from the
configured `rpm` and capped by the work available.

## Tests

```bash
.venv/bin/python -m pytest
```

Tests are organised phrase-by-phrase against the spec; `tests/conftest.py`
provides a threaded mock API server (configurable per-request status, body and
delay) and a subprocess CLI runner.

Interpretation decisions for under-specified behaviour are recorded in
`AMBIGUITIES.md`.
