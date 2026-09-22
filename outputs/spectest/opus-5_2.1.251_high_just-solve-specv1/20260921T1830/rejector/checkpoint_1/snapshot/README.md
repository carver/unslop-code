# rejector

A CLI that reads a YAML task configuration and a JSONL input file, sends prompts
to an OpenAI-compatible chat completions API concurrently, and writes one JSONL
result per input row.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python rejector.py run --config <path> --input <path> --output <path> [options]
```

Optional overrides replace the matching config value: `--api-url`, `--model`,
`--rpm`, `--max-tokens`, `--scheme`, `--temperature`, `--n`.

Exit codes: `0` on success, `1` on any configuration or input error.

Example:

```bash
.venv/bin/python rejector.py run \
  --config examples/greedy.yaml \
  --input examples/data.jsonl \
  --output results.jsonl
```

A JSON summary is printed to stdout when the run finishes:

```json
{"total": 30, "passed": 30, "failed": 0, "total_prompt_tokens": 300,
 "total_completion_tokens": 150, "total_api_calls": 30,
 "elapsed_seconds": 30.1, "throughput_rpm": 59.9}
```

## Schemes

| Scheme      | Behaviour |
|-------------|-----------|
| `greedy`    | `temperature` is forced to `0.0`; `n` is ignored; one attempt per row. |
| `sample`    | Requires `temperature > 0`; `n` is ignored; one attempt per row. |
| `rejection` | Requires `temperature > 0` and an `evaluation` section; makes up to `n` sequential attempts per row and keeps the first passing response. If every attempt is rejected, `output` is `null` and `result.passed` is `false`. |

## Evaluation

`exact_match` compares an extracted value against the row's `answer_field`
(numeric values compare numerically, so `8` matches `8.0`). `contains` checks
that the `answer_field` value appears in the response. `regex` searches the
response for `pattern` and needs no `answer_field`.

Extract methods: `last_number` (last integer/decimal, comma separators ignored),
`last_line` (last non-empty line), `full` (whole response, stripped). When
`evaluation` is omitted for `greedy`/`sample`, `result.passed` is `null`.

## Concurrency

Requests are dispatched in input order by a worker pool sized from the
configured `rpm` (capped by the row count). Workers ramp up over a bounded
window so requests also reach the server in input order; each response is
awaited by the worker that sent it, so a row can never consume another row's
response. Against a mock server capped at its configured rpm the tool sustains
~99% of that capacity, versus ~50% for a sequential client.

## Failure handling

An HTTP 5xx or a transport error is retried up to 3 total requests per logical
attempt. After the third failure the row is failed: `output` is `null`, the row
counts as failed in the summary, and the run continues. Retries count toward
`total_api_calls` but never increase `result.attempts`.

## Tests

```bash
.venv/bin/python tests/test_rejector.py
```

The suite starts and stops its own mock server on a free port (takes ~4
minutes, since it exercises real throughput against a rate-capped server).
Set `MOCK_PORT` to point at a server you started yourself instead.

`tests/mock_server.py` emulates a server that queues work internally: it
processes `capacity` requests at a time, each taking `latency` seconds, so total
throughput is capped and a sequential client cannot reach it. The suite covers
all three schemes, every evaluation type and extract method, retry/failure
behaviour, output and summary shapes, CLI overrides, config/input validation,
ordering and throughput.
