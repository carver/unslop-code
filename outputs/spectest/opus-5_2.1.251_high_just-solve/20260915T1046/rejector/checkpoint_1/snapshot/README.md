# rejector

A CLI that reads a YAML task config plus a JSONL input file, calls an
OpenAI-compatible `/v1/chat/completions` endpoint concurrently, and writes one
JSONL result per input row.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python rejector.py run --config examples/task.yaml \
    --input examples/data.jsonl --output results.jsonl
```

Optional overrides (each replaces the corresponding config value):
`--api-url`, `--model`, `--rpm`, `--max-tokens`, `--scheme`, `--temperature`, `--n`.

Exit codes: `0` on success, `1` on any configuration or input error (message on stderr).

## Schemes

| scheme | temperature | attempts |
|---|---|---|
| `greedy` | forced to `0.0` | 1 (`n` ignored) |
| `sample` | must be `> 0` | 1 (`n` ignored) |
| `rejection` | must be `> 0` | up to `n`, stops at the first response that passes evaluation |

`evaluation` is required for `rejection`, optional otherwise; when it is omitted
`result.passed` is `null` and such rows count as passed in the summary as long as
the API call succeeded.

Evaluation types: `exact_match` and `contains` (both need `answer_field`), and
`regex` (needs `pattern`). Extract methods: `last_number`, `last_line`, `full`
(default `full`). `exact_match` compares the extracted value to the row's
`answer_field`, tolerating surrounding whitespace, thousands separators, `$`/`%`
and a trailing period, and comparing numerically when both sides are numeric.

## Output

One JSON object per input row, in input order:

```json
{"input": {...}, "output": {"<output_field>": "..."} , "result": {"passed": true, "extracted_answer": "8", "attempts": 1}, "meta": {...}}
```

`output` is `null` when every attempt fails; `meta` is a single object for
one-attempt rows and a list (one entry per logical attempt) for multi-attempt
rejection rows. A JSON summary is printed to stdout when the run finishes.

## Concurrency

Rows are processed as concurrent asyncio tasks over a shared HTTP connection
pool, with in-flight work capped at `max(8, min(rpm, 256))` requests (never more
than the number of rows). The server queues internally, so the client keeps its
queue non-empty rather than pacing itself; measured throughput lands at ~99% of
the configured `rpm` against a server whose capacity is `rpm` (see
`tests/test_all.py`). New connections ramp over the first ~0.25 s to avoid
overflowing a small listen backlog.

## Retries

HTTP `5xx` responses and transport errors are retried up to 3 times (4 HTTP
calls maximum per logical attempt) with exponential backoff. Every HTTP call
counts toward `total_api_calls`, but retries never increase `result.attempts`.
When retries are exhausted the row is emitted with `output: null`, counted as
failed, and the run continues. HTTP `4xx` is treated as an immediate row failure.

## Tests

```bash
.venv/bin/python tests/test_all.py
```

Spawns mock servers (`tests/mock_server.py`, which queues requests behind a
worker pool so its capacity is a real rpm ceiling) and exercises all three
schemes, every evaluation and extract method, retry/failure paths, CLI
overrides, config/input validation, and the throughput target.
