# rejector

CLI tool that reads a YAML task config and a JSONL input file, sends prompts to
an OpenAI-compatible chat completions API, and writes one JSONL result per row.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
./.venv/bin/python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Optional overrides: `--api-url`, `--model`, `--rpm`, `--max-tokens`,
`--scheme {greedy,sample,rejection}`, `--temperature`, `--n`.

Exit codes: `0` success, `1` configuration or input error (message on stderr).
The JSON summary is the only thing written to stdout.

## Notes

- Requests run concurrently through a worker pool sized from `rpm`, so a server
  that queues internally stays saturated; rows are dispatched in input order and
  each response is matched to its own row.
- `greedy` forces `temperature: 0.0`; `sample` and `rejection` require
  `temperature > 0`; `rejection` makes up to `n` attempts and keeps the first
  passing response.
- HTTP 5xx (and connection errors) are retried up to 3 total requests per
  attempt. Retries count toward `total_api_calls` but not `result.attempts`.

## Tests

```bash
./.venv/bin/python tests/run_tests.py
```

Spins up a mock API server that queues requests and takes real processing time,
then checks output shape, all three schemes, every evaluation type and extract
method, retry behaviour, validation errors, CLI overrides, ordering, and
throughput against the configured `rpm`.
