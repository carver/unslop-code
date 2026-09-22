# rejector

CLI that runs a YAML-configured generation task over a JSONL input file
against an OpenAI-compatible chat completions API, and writes one JSONL
result row per input row.

```bash
python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
```

Optional overrides: `--api-url`, `--model`, `--rpm`, `--max-tokens`,
`--scheme`, `--temperature`, `--n`. Exit code `0` on success, `1` on a
configuration or input error.

## Layout

| Path | Role |
| --- | --- |
| `rejector.py` | entry point |
| `rejector_lib/cli.py` | argument parsing, run orchestration |
| `rejector_lib/config.py` | YAML config loading, overrides, validation |
| `rejector_lib/inputs.py` | JSONL reading, row validation, prompt rendering |
| `rejector_lib/api.py` | async chat completions client, retries, usage tally |
| `rejector_lib/runner.py` | greedy/sample/rejection schemes, concurrency |
| `rejector_lib/report.py` | result rows and the stdout summary |
| `tests/mock_server.py` | mock API with configurable capacity and failures |

Requests run concurrently: up to `rpm` (capped at 256) are kept in flight so
the server's queue stays busy. `AMBIGUITIES.md` records where the spec allowed
more than one reading and which one this implementation takes.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```
