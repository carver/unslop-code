# rejector

A CLI that runs a YAML-configured generation task over a JSONL input file
against an OpenAI-compatible chat completions API, evaluates each response,
and writes one JSONL result per input row.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python rejector.py run \
    --config examples/task.yaml \
    --input examples/data.jsonl \
    --output results.jsonl
```

`--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`, `--temperature`
and `--n` override the matching config values. The command exits `0` on
success and `1` on a configuration or input error.

A run prints a JSON summary to stdout:

```json
{"total": 3, "passed": 3, "failed": 0, "total_prompt_tokens": 30,
 "total_completion_tokens": 15, "total_api_calls": 3, "elapsed_seconds": 3.1,
 "throughput_rpm": 58.1}
```

## Generation schemes

| Scheme | Behaviour |
| --- | --- |
| `greedy` | One attempt at `temperature` 0.0; `n` is ignored. |
| `sample` | One attempt at the configured `temperature` (must be > 0); `n` is ignored. |
| `rejection` | Up to `n` attempts, keeping the first that passes the evaluation. Requires an `evaluation` block. |

Rows that never produce a passing response are written with `"output": null`
and `"passed": false`.

## Throughput

Rows are processed concurrently. `RateLimiter` paces request starts at the
configured `rpm`, with a few seconds of burst allowance so the server's queue
stays fed instead of being drip-fed one request at a time. Against a server
whose capacity matches `rpm`, runs measure at roughly 100% of the budget.

## Layout

| File | Contents |
| --- | --- |
| `rejector.py` | Argument parsing and the top-level run/exit-code flow. |
| `config.py` | Task config dataclasses, defaults, and validation. |
| `dataset.py` | JSONL reading, prompt rendering, result writing. |
| `evaluation.py` | Answer extraction and the `exact_match`/`contains`/`regex` checks. |
| `client.py` | Rate limiting, HTTP calls, retries, and run counters. |
| `runner.py` | Per-row schemes, concurrency, records, and the summary. |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

The end-to-end tests drive the CLI against `tests/mock_server.py`, a mock API
with a fixed worker pool that can inject `5xx` responses and control which
attempt passes evaluation.
